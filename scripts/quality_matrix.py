#!/usr/bin/env python3
"""CLI shell for the fail-closed quality-matrix gate (#278, extended by #283).

    python3 scripts/quality_matrix.py build --run-dir <dir> [--coverage-threshold N] [--change-type T] [--run-id ID] [--work-item-source github --work-item-id 283 --work-item-type feat --work-item-title "..."]
    python3 scripts/quality_matrix.py check --run-dir <dir>
    python3 scripts/quality_matrix.py classify --title "..." [--label L ...]
    python3 scripts/quality_matrix.py populate --run-dir <dir> [--base origin/main] [--benchmark-na "..."] [--run-id ID] [--work-item-source github --work-item-id 283]
    python3 scripts/quality_matrix.py tdd-red --run-dir <dir> --test-id <pytest-node-id>
    python3 scripts/quality_matrix.py tdd-green --run-dir <dir> --test-id <pytest-node-id>
    python3 scripts/quality_matrix.py reverify --run-dir <dir> [--no-rerun]
    python3 scripts/quality_matrix.py selftest

`populate`/`tdd-red`/`tdd-green`/`reverify` are #283's scope: auto-populating the receipt
from `scripts/coverage_gate.py`/`scripts/regression_test_gate.py`/`scripts/perf_gate.py` instead of
hand-typed values, structurally re-checkable TDD RED/GREEN evidence, and an independent watcher
re-verification pass (also wired into `scripts/watcher_verify.py cmd_verify`).

`--run-id`/`--work-item-*` and the receipt's nested `tests.{unit,integration,system,regression}`
mirror (kept in lockstep via `simplicio_loop.quality_matrix.sync_tests_envelope`) cover #283's last
documented gap: the literal `simplicio.quality-gate/v1` envelope example in the issue body
(`run_id`, `work_item`, nested per-category `tests` object). `evaluate_quality_matrix` reads a
lane from either the flat `requirements.<lane>` entry (still the canonical/authoritative one) or
the nested `tests.<lane>` entry, so a receipt authored in either shape evaluates identically.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from simplicio_loop.quality_matrix import (
    CHANGE_TYPES,
    DEFAULT_COVERAGE_THRESHOLD,
    build_quality_matrix_template,
    classify_change_type,
    default_policy_for_change_type,
    evaluate_quality_matrix,
    independent_reverify_quality_matrix,
    receipt_path,
    sync_tests_envelope,
)


def _work_item_from_args(args: argparse.Namespace) -> dict | None:
    """#283: build the optional `work_item` block from --work-item-* flags, matching the
    issue's literal envelope example (`work_item.source`/`.id`/`.type`/`.title`)."""
    fields = {
        "source": getattr(args, "work_item_source", None),
        "id": getattr(args, "work_item_id", None),
        "type": getattr(args, "work_item_type", None),
        "title": getattr(args, "work_item_title", None),
        "head_sha": getattr(args, "work_item_head_sha", None),
    }
    fields = {k: v for k, v in fields.items() if v}
    return fields or None


def cmd_build(args: argparse.Namespace) -> int:
    template = build_quality_matrix_template(
        args.coverage_threshold, change_type=args.change_type,
        run_id=args.run_id, work_item=_work_item_from_args(args),
    )
    out = receipt_path(args.run_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(template, ensure_ascii=False, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    verdict = evaluate_quality_matrix(args.run_dir)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["ready"] else 1


def cmd_classify(args: argparse.Namespace) -> int:
    change_type = classify_change_type(args.title or "", args.label or [])
    policy = default_policy_for_change_type(change_type)
    print(json.dumps({"change_type": change_type, "policy": policy}, ensure_ascii=False, indent=2))
    return 0


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_receipt(run_dir: Path, coverage_threshold: float, change_type) -> dict:
    path = receipt_path(str(run_dir))
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return build_quality_matrix_template(coverage_threshold, change_type=change_type)


def _save_receipt(run_dir: Path, receipt: dict) -> None:
    path = receipt_path(str(run_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_populate(args: argparse.Namespace) -> int:
    """#283: auto-populate the unit/integration/system/regression/benchmark/coverage lanes from
    the real gate scripts.

    `implementation` still has no dedicated standalone gate script (it is inherently
    change-specific -- there is no generic "did you implement it" check to run), so that lane is
    left untouched here. Every other measurable lane now has one:
    `scripts/test_categories.py run --category {unit,integration,system}` (the per-category
    test-runner split -- reads the `tests/*_<category>.py` filename convention, see that script's
    module docstring for exactly which files are and are not covered by it today),
    regression (`scripts/regression_test_gate.py`), benchmark (`scripts/perf_gate.py`), coverage
    (`scripts/coverage_gate.py`).
    """
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    receipt = _load_receipt(run_dir, args.coverage_threshold, args.change_type)
    requirements = receipt.setdefault("requirements", {})
    if args.run_id and not receipt.get("run_id"):
        receipt["run_id"] = args.run_id
    work_item = _work_item_from_args(args)
    if work_item and not receipt.get("work_item"):
        receipt["work_item"] = work_item

    skip_category = {
        "unit": args.skip_unit,
        "integration": args.skip_integration,
        "system": args.skip_system,
    }
    for category, skip in skip_category.items():
        if skip:
            continue
        report_path = run_dir / f"{category}-test-gate-report.json"
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, "test_categories.py"),
             "run", "--category", category, "--emit-json", str(report_path)],
            cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        if report.get("status") == "blocked":
            requirements[category] = {
                "status": "blocked",
                "proof_ref": str(report_path),
                "detail": report.get("detail", "category has zero matching test files"),
            }
        else:
            ok = proc.returncode == 0
            requirements[category] = {
                "status": "pass" if ok else "fail",
                "proof_ref": str(report_path),
                "detail": report.get("detail", "") or (proc.stdout or proc.stderr or "").strip()[-500:],
            }

    if not args.skip_regression:
        report_path = run_dir / "regression-gate-report.json"
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, "regression_test_gate.py"),
             "--base", args.base, "--emit-json", str(report_path)],
            cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        ok = proc.returncode == 0
        requirements["regression"] = {
            "status": "pass" if ok else "fail",
            "proof_ref": str(report_path),
            "detail": report.get("detail", "") or (proc.stdout or proc.stderr or "").strip()[-500:],
        }

    if args.benchmark_na:
        receipt.setdefault("policy", {})["allow_justified_not_applicable"] = True
        requirements["benchmark"] = {"status": "not_applicable", "justification": args.benchmark_na}
    elif not args.skip_benchmark:
        report_path = run_dir / "benchmark-gate-report.json"
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, "perf_gate.py"), "--emit-json", str(report_path)],
            cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        ok = proc.returncode == 0
        requirements["benchmark"] = {
            "status": "pass" if ok else "fail",
            "proof_ref": str(report_path),
            "detail": "; ".join(report.get("failures") or []) or "perf-gate passed",
        }

    if not args.skip_coverage:
        report_path = run_dir / "coverage-gate-report.json"
        diag_dir = run_dir / "coverage-diagnostics"
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, "coverage_gate.py"),
             "--global-threshold", str(args.coverage_threshold),
             "--diagnostics-dir", str(diag_dir), "--emit-json", str(report_path)],
            cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        receipt["coverage"] = {
            "measured": report.get("global_pct"),
            "report_ref": str(report_path),
        }
        if proc.returncode != 0 and "global_pct" not in report:
            print(proc.stdout, file=sys.stderr)
            print(proc.stderr, file=sys.stderr)

    sync_tests_envelope(receipt)  # #283: keep the nested "tests" mirror in lockstep
    _save_receipt(run_dir, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    verdict = evaluate_quality_matrix(str(run_dir))
    return 0 if verdict["ready"] else 1


def cmd_tdd_red(args: argparse.Namespace) -> int:
    """#283: record a structurally re-checkable RED receipt -- FAILS CLOSED if the referenced test
    does not actually fail right now (a real RED capture only happens before the fix lands)."""
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", args.test_id], cwd=REPO,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
    receipt = {
        "schema": "simplicio.tdd-red-receipt/v1",
        "test_id": args.test_id,
        "exit_code": proc.returncode,
        "commit_sha": commit,
        "written_at": _now(),
        "stdout_tail": (proc.stdout or proc.stderr or "").strip()[-1000:],
    }
    out = run_dir / "tdd-red-receipt.json"
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    if proc.returncode == 0:
        print("[tdd-red] REJECTED: test passed -- a RED receipt must capture a genuinely failing "
              "test, before the fix lands. Not writing a false RED.", file=sys.stderr)
        return 1
    print(f"[tdd-red] OK: {args.test_id} failed as expected at {commit[:12]} -> {out}")
    return 0


def cmd_tdd_green(args: argparse.Namespace) -> int:
    """#283: record a structurally re-checkable GREEN receipt -- FAILS CLOSED if the referenced
    test does not pass, or if no prior RED receipt exists for the same test id in this run dir."""
    run_dir = Path(args.run_dir)
    red_path = run_dir / "tdd-red-receipt.json"
    if not red_path.exists():
        print("[tdd-green] REJECTED: no tdd-red-receipt.json in this run dir -- run tdd-red first.",
              file=sys.stderr)
        return 1
    red = json.loads(red_path.read_text(encoding="utf-8"))
    if red.get("test_id") != args.test_id:
        print(f"[tdd-green] REJECTED: RED receipt is for {red.get('test_id')!r}, not {args.test_id!r}.",
              file=sys.stderr)
        return 1
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", args.test_id], cwd=REPO,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
    receipt = {
        "schema": "simplicio.tdd-green-receipt/v1",
        "test_id": args.test_id,
        "exit_code": proc.returncode,
        "commit_sha": commit,
        "written_at": _now(),
        "stdout_tail": (proc.stdout or proc.stderr or "").strip()[-1000:],
    }
    out = run_dir / "tdd-green-receipt.json"
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    if proc.returncode != 0:
        print("[tdd-green] REJECTED: test still fails -- GREEN requires the same test to now pass.",
              file=sys.stderr)
        return 1
    if commit == red.get("commit_sha"):
        print("[tdd-green] REJECTED: same commit as RED -- no implementation change is recorded "
              "between the failing and passing runs.", file=sys.stderr)
        return 1
    print(f"[tdd-green] OK: {args.test_id} passed at {commit[:12]} (RED was {red.get('commit_sha', '')[:12]}) -> {out}")
    return 0


def cmd_reverify(args: argparse.Namespace) -> int:
    verdict = independent_reverify_quality_matrix(args.run_dir, repo=REPO, rerun=not args.no_rerun)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["ready"] else 1


def cmd_selftest(_args: argparse.Namespace) -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        verdict = evaluate_quality_matrix(str(run_dir))
        assert verdict["ready"] is False
        assert verdict["reason_code"] == "quality_matrix_missing"

        template = build_quality_matrix_template()
        (run_dir / "quality-matrix.json").write_text(json.dumps(template), encoding="utf-8")
        verdict = evaluate_quality_matrix(str(run_dir))
        assert verdict["ready"] is False  # template is all-unset by design

        passing = {
            "schema": "simplicio.quality-matrix/v1",
            "coverage_threshold": DEFAULT_COVERAGE_THRESHOLD,
            "requirements": {
                name: {"status": "pass", "proof_ref": f"tests/{name}"}
                for name in ("implementation", "unit", "integration", "system", "regression", "benchmark")
            },
            "coverage": {"measured": 90.0},
        }
        (run_dir / "quality-matrix.json").write_text(json.dumps(passing), encoding="utf-8")
        verdict = evaluate_quality_matrix(str(run_dir))
        assert verdict["ready"] is True

        # #283: change classification is deterministic and label-authoritative.
        assert classify_change_type("", ["bug"]) == "bug"
        assert classify_change_type("fix null pointer crash", []) == "fix"
        assert classify_change_type("add SSO login feature", []) == "feat"
        assert classify_change_type("update docs for the API", []) == "chore"
        assert classify_change_type("unrelated title", []) == "task"

        # #283: opt-in TDD lane — absent by default (no regression on #278 receipts),
        # required and validated (distinct RED != GREEN refs) once policy opts in.
        tdd_policy = dict(passing, policy={"tdd_required": True})
        (run_dir / "quality-matrix.json").write_text(json.dumps(tdd_policy), encoding="utf-8")
        verdict = evaluate_quality_matrix(str(run_dir))
        assert verdict["ready"] is False
        assert verdict["reason_code"] == "quality_tdd_missing"

        tdd_passing = dict(tdd_policy)
        tdd_passing["requirements"] = dict(passing["requirements"], tdd={
            "status": "pass", "red_proof_ref": "tests/test_x.py::red", "green_proof_ref": "tests/test_x.py::green",
        })
        (run_dir / "quality-matrix.json").write_text(json.dumps(tdd_passing), encoding="utf-8")
        verdict = evaluate_quality_matrix(str(run_dir))
        assert verdict["ready"] is True

        # #283: justified NOT_APPLICABLE benchmark, only when policy opts in.
        na_receipt = dict(passing, policy={"allow_justified_not_applicable": True})
        na_receipt["requirements"] = dict(passing["requirements"])
        na_receipt["requirements"]["benchmark"] = {"status": "not_applicable", "justification": "no perf-sensitive code path touched"}
        (run_dir / "quality-matrix.json").write_text(json.dumps(na_receipt), encoding="utf-8")
        verdict = evaluate_quality_matrix(str(run_dir))
        assert verdict["ready"] is True

        # #283: independent TDD re-verification is a SEPARATE code path from the self-reported
        # status string -- a receipt that claims "pass" with no backing receipt files is caught.
        from simplicio_loop.quality_matrix import independent_reverify_tdd_lane

        claim_only = {"status": "pass", "red_proof_ref": "tdd-red-receipt.json", "green_proof_ref": "tdd-green-receipt.json"}
        gate = independent_reverify_tdd_lane(str(run_dir), claim_only)
        assert gate["status"] == "fail"
        assert gate["reason_code"] == "quality_tdd_reverify_receipt_missing"

        (run_dir / "tdd-red-receipt.json").write_text(json.dumps(
            {"test_id": "t", "exit_code": 1, "commit_sha": "aaa111"}), encoding="utf-8")
        (run_dir / "tdd-green-receipt.json").write_text(json.dumps(
            {"test_id": "t", "exit_code": 0, "commit_sha": "bbb222"}), encoding="utf-8")
        gate = independent_reverify_tdd_lane(str(run_dir), claim_only)
        assert gate["status"] == "pass", gate

        # same commit for RED and GREEN => nothing proven to have changed => reject.
        (run_dir / "tdd-green-receipt.json").write_text(json.dumps(
            {"test_id": "t", "exit_code": 0, "commit_sha": "aaa111"}), encoding="utf-8")
        gate = independent_reverify_tdd_lane(str(run_dir), claim_only)
        assert gate["status"] == "fail"
        assert gate["reason_code"] == "quality_tdd_reverify_no_commit_delta"

        # RED receipt claiming a PASSING (exit_code 0) run is not a real RED -- reject.
        (run_dir / "tdd-red-receipt.json").write_text(json.dumps(
            {"test_id": "t", "exit_code": 0, "commit_sha": "aaa111"}), encoding="utf-8")
        (run_dir / "tdd-green-receipt.json").write_text(json.dumps(
            {"test_id": "t", "exit_code": 0, "commit_sha": "bbb222"}), encoding="utf-8")
        gate = independent_reverify_tdd_lane(str(run_dir), claim_only)
        assert gate["status"] == "fail"
        assert gate["reason_code"] == "quality_tdd_reverify_red_not_failing"
    print("selftest: PASS quality-matrix")
    return 0


def _add_work_item_args(parser: argparse.ArgumentParser) -> None:
    """#283: --run-id/--work-item-* flags populate the issue's literal envelope example
    (`run_id`, `work_item.source`/`.id`/`.type`/`.title`). All optional/additive -- omitting
    them keeps the exact pre-existing receipt shape (empty string/dict, never fabricated).

    `--work-item-head-sha` (#290) additionally binds this quality-matrix receipt to the commit
    the delivery/#288 evidence claims for `merge-ready`+ targets -- `oracle.py`'s
    `_commit_binding_gate` rejects completion when this is absent or mismatched at those states."""
    parser.add_argument("--run-id", default=None, help="cross-link this receipt to a run id (delivery/evidence receipt, task anchor)")
    parser.add_argument("--work-item-source", default=None, help="e.g. github")
    parser.add_argument("--work-item-id", default=None)
    parser.add_argument("--work-item-type", default=None, choices=["bug", "task", "feat", "fix", "chore"])
    parser.add_argument("--work-item-title", default=None)
    parser.add_argument("--work-item-head-sha", default=None, help="commit sha this evidence was gathered for (#290 commit binding)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quality_matrix")
    sub = parser.add_subparsers(dest="verb", required=True)
    p_build = sub.add_parser("build")
    p_build.add_argument("--run-dir", required=True)
    p_build.add_argument("--coverage-threshold", type=float, default=DEFAULT_COVERAGE_THRESHOLD)
    p_build.add_argument("--change-type", choices=list(CHANGE_TYPES), default=None)
    _add_work_item_args(p_build)
    p_build.set_defaults(func=cmd_build)
    p_check = sub.add_parser("check")
    p_check.add_argument("--run-dir", required=True)
    p_check.set_defaults(func=cmd_check)
    p_classify = sub.add_parser("classify")
    p_classify.add_argument("--title", default="")
    p_classify.add_argument("--label", action="append", default=[])
    p_classify.set_defaults(func=cmd_classify)
    p_self = sub.add_parser("selftest")
    p_self.set_defaults(func=cmd_selftest)
    p_populate = sub.add_parser("populate")
    p_populate.add_argument("--run-dir", required=True)
    p_populate.add_argument("--base", default="origin/main")
    p_populate.add_argument("--coverage-threshold", type=float, default=DEFAULT_COVERAGE_THRESHOLD)
    p_populate.add_argument("--change-type", choices=list(CHANGE_TYPES), default=None)
    p_populate.add_argument("--benchmark-na", default=None, help="excuse benchmark as justified NOT_APPLICABLE instead of running perf_gate.py")
    p_populate.add_argument("--skip-unit", action="store_true")
    p_populate.add_argument("--skip-integration", action="store_true")
    p_populate.add_argument("--skip-system", action="store_true")
    p_populate.add_argument("--skip-regression", action="store_true")
    p_populate.add_argument("--skip-benchmark", action="store_true")
    p_populate.add_argument("--skip-coverage", action="store_true")
    _add_work_item_args(p_populate)
    p_populate.set_defaults(func=cmd_populate)
    p_tdd_red = sub.add_parser("tdd-red")
    p_tdd_red.add_argument("--run-dir", required=True)
    p_tdd_red.add_argument("--test-id", required=True)
    p_tdd_red.set_defaults(func=cmd_tdd_red)
    p_tdd_green = sub.add_parser("tdd-green")
    p_tdd_green.add_argument("--run-dir", required=True)
    p_tdd_green.add_argument("--test-id", required=True)
    p_tdd_green.set_defaults(func=cmd_tdd_green)
    p_reverify = sub.add_parser("reverify")
    p_reverify.add_argument("--run-dir", required=True)
    p_reverify.add_argument("--no-rerun", action="store_true", help="skip live re-execution of regression/benchmark gates; artifact-only")
    p_reverify.set_defaults(func=cmd_reverify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
