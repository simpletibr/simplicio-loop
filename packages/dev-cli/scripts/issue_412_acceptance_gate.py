"""Build a fail-closed acceptance matrix for issue #412 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.dev-cli.issue-412-acceptance/v1"
REPORT_SCHEMAS = {
    "issue-414": "simplicio.dev-cli.issue-414-binary-benchmark/v1",
    "issue-415": "simplicio.dev-cli.issue-415-verification-benchmark/v1",
    "issue-416": "simplicio.dev-cli.issue-416-transaction-benchmark/v1",
    "issue-417": "simplicio.dev-cli.issue-417-context-cache-benchmark/v1",
    "issue-422": "simplicio.dev-cli.issue-422-evidence/v1",
    "quality": "simplicio.dev-cli.quality-gate-receipt/v1",
}
REQUIRED_REPORTS = tuple(REPORT_SCHEMAS)
BLOCKING_STATUSES = {"BLOCKED", "FAIL", "UNVERIFIED"}


def _git_sha(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _row(criterion: str, status: str, reason: str, evidence: list[str] | None = None) -> dict[str, Any]:
    return {
        "criterion": criterion,
        "status": status,
        "reason": reason,
        "evidence": evidence or [],
    }


def _missing(criterion: str, report_name: str) -> dict[str, Any]:
    return _row(criterion, "BLOCKED", f"required evidence report is missing: {report_name}")


def _load_reports(
    root: Path, report_paths: dict[str, Path]
) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    reports: dict[str, dict[str, Any]] = {}
    digests: dict[str, str] = {}
    errors: list[dict[str, Any]] = []
    for name, schema in REPORT_SCHEMAS.items():
        path = report_paths.get(name)
        if path is None:
            errors.append(_missing("report:" + name, name))
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(_row("report:" + name, "FAIL", f"report unreadable: {type(exc).__name__}"))
            continue
        if not isinstance(payload, dict) or payload.get("schema") != schema:
            errors.append(_row("report:" + name, "FAIL", f"schema mismatch for {name}"))
            continue
        reports[name] = payload
        digests[name] = _digest(path)
    return reports, digests, errors


def _bound_to_sha(name: str, payload: dict[str, Any], current_sha: str | None) -> tuple[bool, str]:
    report_sha = payload.get("commit_sha")
    if not isinstance(report_sha, str) or not report_sha:
        return False, f"{name} report has no commit_sha"
    if current_sha is None or report_sha != current_sha:
        return False, f"{name} report commit_sha is stale or current SHA is unavailable"
    return True, "commit SHA matches current checkout"


def _benchmark_row(payload: dict[str, Any], lane: str, sizes: tuple[int, ...]) -> tuple[bool, str]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return False, "benchmark rows are missing"
    selected = [row for row in rows if isinstance(row, dict) and row.get("lane") == lane]
    if {row.get("size") for row in selected} != set(sizes):
        return False, f"benchmark lane {lane} does not cover sizes {list(sizes)}"
    if any(row.get("status") != "PASS" or _repeat_count(row.get("repeats")) < 10 for row in selected):
        return False, f"benchmark lane {lane} contains non-PASS or fewer than 10 repetitions"
    return True, f"{lane} PASS for sizes {list(sizes)} with >=10 repetitions"


def _repeat_count(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _files_hashed(row: Any, lane: str) -> int:
    value = row.get(lane) if isinstance(row, dict) else None
    return value.get("files_hashed", -1) if isinstance(value, dict) else -1


def _effect_boundary_row(root: Path) -> dict[str, Any]:
    command = root / "scripts" / "check_effect_boundary.py"
    if not command.is_file():
        return _missing("single-effect-boundary", "scripts/check_effect_boundary.py")
    result = subprocess.run(
        ["python3", str(command), "--root", str(root)],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return _row(
            "single-effect-boundary", "PASS", "effect-boundary inventory matches its reviewed baseline"
        )
    detail = (result.stdout + result.stderr).strip().splitlines()
    return _row("single-effect-boundary", "FAIL", detail[-1] if detail else "effect-boundary guard failed")


def build_matrix(root: Path, report_paths: dict[str, Path]) -> dict[str, Any]:
    root = root.resolve()
    current_sha = _git_sha(root)
    reports, digests, rows = _load_reports(root, report_paths)
    evidence = [f"{name}:{digest}" for name, digest in sorted(digests.items())]
    rows.insert(0, _effect_boundary_row(root))

    quality = reports.get("quality")
    if quality is None:
        rows.append(_missing("local-quality-gate", "quality"))
    else:
        bound, reason = _bound_to_sha("quality", quality, current_sha)
        passed = quality.get("passed") is True and quality.get("dirty") is False
        rows.append(
            _row(
                "local-quality-gate",
                "PASS" if bound and passed else "FAIL",
                reason if bound else reason,
                evidence,
            )
        )

    binary = reports.get("issue-414")
    if binary is None:
        rows.append(_missing("fast-binary-envelope", "issue-414"))
    else:
        bound, reason = _bound_to_sha("issue-414", binary, current_sha)
        python_ok, python_reason = _benchmark_row(binary, "binary_fast_adapter", (1, 20, 200))
        rust_ok, rust_reason = _benchmark_row(binary, "binary_fast_rust_adapter", (1, 20, 200))
        ok = bound and python_ok and rust_ok
        rows.append(
            _row(
                "fast-binary-envelope",
                "PASS" if ok else "UNVERIFIED",
                "; ".join((reason, python_reason, rust_reason)),
                evidence,
            )
        )

    verification = reports.get("issue-415")
    if verification is None:
        rows.append(_missing("mapper-incremental-generation", "issue-415"))
    else:
        bound, reason = _bound_to_sha("issue-415", verification, current_sha)
        benchmark_rows = verification.get("rows", [])
        causal_ok = (
            isinstance(benchmark_rows, list)
            and len(benchmark_rows) == 9
            and all(
                isinstance(item, dict)
                and _files_hashed(item, "full") > _files_hashed(item, "causal")
                and _files_hashed(item, "causal") == 1
                for item in benchmark_rows
            )
        )
        rows.append(
            _row(
                "mapper-incremental-generation",
                "PASS" if bound and causal_ok else "UNVERIFIED",
                reason if causal_ok else "causal verification did not prove a reduced read-set",
                evidence,
            )
        )

    transaction = reports.get("issue-416")
    if transaction is None:
        rows.append(_missing("atomic-recoverable-transaction", "issue-416"))
    else:
        bound, reason = _bound_to_sha("issue-416", transaction, current_sha)
        transaction_rows = transaction.get("rows", [])
        tx_rows = [
            row
            for row in (transaction_rows if isinstance(transaction_rows, list) else [])
            if isinstance(row, dict) and row.get("lane") == "python_transaction"
        ]
        tx_ok = len(tx_rows) == 3 and all(
            row.get("status") == "PASS" and _repeat_count(row.get("repeats")) >= 10 for row in tx_rows
        )
        recovery_ok = (
            isinstance(transaction.get("recovery"), dict) and transaction["recovery"].get("status") == "PASS"
        )
        rows.append(
            _row(
                "atomic-recoverable-transaction",
                "PASS" if bound and tx_ok and recovery_ok else "UNVERIFIED",
                reason
                if tx_ok and recovery_ok
                else "transaction benchmark does not prove crash recovery for the complete write-set",
                evidence,
            )
        )

    cache = reports.get("issue-417")
    if cache is None:
        rows.append(_missing("concurrent-cache-integrity", "issue-417"))
    else:
        bound, reason = _bound_to_sha("issue-417", cache, current_sha)
        cases = cache.get("cases", [])
        cache_ok = (
            cache.get("all_chains_valid") is True
            and {case.get("writers") for case in cases if isinstance(case, dict)} == {1, 10, 50}
            if isinstance(cases, list)
            else False
        )
        rows.append(
            _row(
                "concurrent-cache-integrity",
                "PASS" if bound and cache_ok else "UNVERIFIED",
                reason if cache_ok else "cache benchmark does not prove all writer lanes and valid chains",
                evidence,
            )
        )

    e2e = reports.get("issue-422")
    if e2e is None:
        rows.append(_missing("installed-cross-repo-e2e", "issue-422"))
    else:
        bound, reason = _bound_to_sha("issue-422", e2e, current_sha)
        required = {
            "auto_without_runtime",
            "standalone_changeset_1",
            "standalone_changeset_20",
            "standalone_changeset_200",
            "fast_python_binary_1",
            "fast_python_binary_20",
            "fast_python_binary_200",
            "windows_locked_file",
            "fast_rust",
            "mapper_producer",
            "runtime_backed",
            "worktree_isolation_10",
            "adversarial_generation_replay",
        }
        scenario_rows = e2e.get("scenarios", [])
        scenarios = (
            {row.get("scenario"): row for row in scenario_rows if isinstance(row, dict)}
            if isinstance(scenario_rows, list)
            else {}
        )
        e2e_ok = (
            e2e.get("overall") == "PASS"
            and required <= scenarios.keys()
            and all(scenarios[name].get("status") == "PASS" for name in required)
        )
        rows.append(
            _row(
                "installed-cross-repo-e2e",
                "PASS" if bound and e2e_ok else "UNVERIFIED",
                reason
                if e2e_ok
                else "E2E is not PASS for every required standalone, Fast, Runtime, Mapper and Windows lane",
                evidence,
            )
        )

    rows.extend(
        [
            _missing("fast-hot-path-selective-refresh", "issue-419"),
            _missing("typed-state-trace-and-ownership", "issue-420"),
            _missing("runtime-backed-reconciliation", "issue-413/418"),
        ]
    )
    blocking = [row for row in rows if row.get("status") in BLOCKING_STATUSES]
    return {
        "schema": SCHEMA,
        "issue": 412,
        "commit_sha": current_sha,
        "platform": platform.platform(),
        "reports": digests,
        "criteria": rows,
        "ready_to_close": not blocking and bool(rows),
        "blocking_criteria": [row["criterion"] for row in blocking],
    }


def _parse_reports(values: list[str], root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or name not in REPORT_SCHEMAS or not raw_path:
            raise ValueError(f"report must be NAME=PATH where NAME is one of {', '.join(REQUIRED_REPORTS)}")
        path = Path(raw_path)
        result[name] = path if path.is_absolute() else root / path
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--report", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    payload = build_matrix(root, _parse_reports(args.report, root))
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["ready_to_close"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
