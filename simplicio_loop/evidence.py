from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

SCHEMA = "simplicio.evidence-receipt/v1"
SAFE_EXECUTABLES = {
    "python",
    "python3",
    "python.exe",
    "py",
    "pytest",
    "git",
    "gh",
    "node",
    "npm",
    "pnpm",
    "yarn",
    "simplicio-mapper",
    "simplicio-dev-cli",
}
UNSAFE_SHELL_TOKENS = ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n", "\r")
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{10,})['\"]?"),
]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stable_hash(data: Any) -> str:
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def redact_sensitive_text(text: str) -> str:
    redacted = text or ""
    for rx in SECRET_PATTERNS:
        redacted = rx.sub("[REDACTED_SECRET]", redacted)
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b(\s*[:=]\s*['\"]?)([A-Za-z0-9_\-]{10,})(['\"]?)",
        r"\1\2[REDACTED]\4",
        redacted,
    )
    return redacted


def _command_policy(check: Dict[str, Any]) -> tuple[List[str] | None, str]:
    argv = check.get("argv")
    if isinstance(argv, list) and argv:
        normalized = [str(part) for part in argv if str(part)]
    else:
        command = (check.get("command") or "").strip()
        if not command:
            return None, "no command declared"
        if any(token in command for token in UNSAFE_SHELL_TOKENS):
            return None, "command contains unsafe shell syntax"
        try:
            normalized = shlex.split(command, posix=os.name != "nt")
        except ValueError as exc:
            return None, f"cannot parse command: {exc}"
    if not normalized:
        return None, "no argv resolved"
    exe = Path(normalized[0]).name.lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    # Test runners and receipts often pass an absolute interpreter path
    # (python3.11, python3.14, ...). Treat versioned Python executables as
    # equivalent to the explicitly allowlisted python/python3 commands.
    python_executable = exe == "python" or exe.startswith("python3.")
    if exe not in SAFE_EXECUTABLES and not python_executable and not normalized[0].lower().endswith(".py"):
        return None, f"command executable not allowlisted: {normalized[0]}"
    return normalized, "allowed"


def _git_meta(root: Path) -> Dict[str, str]:
    def _run(*args: str) -> str:
        try:
            done = subprocess.run(["git", *args], cwd=str(root), capture_output=True, stdin=subprocess.DEVNULL, text=True,
                                  timeout=15)
            return (done.stdout or "").strip() if done.returncode == 0 else ""
        except Exception:
            return ""

    diff = ""
    staged = False
    try:
        # .simplicio/ is the loop's own bookkeeping; it changes between the
        # evidence receipt and the watcher, so it is never part of the run diff.
        scope = ("--", ".", ":(exclude).simplicio")
        status = _run("status", "--porcelain", "--untracked-files=all", *scope)
        if status:
            add = subprocess.run(
                ["git", "add", "-A", *scope], cwd=str(root), capture_output=True,
                stdin=subprocess.DEVNULL, text=True, timeout=15,
            )
            staged = add.returncode == 0
        diff = _run("diff", "--no-ext-diff", "--cached", "HEAD", *scope) if staged else _run(
            "diff", "--no-ext-diff", "HEAD", *scope
        )
    finally:
        if staged:
            subprocess.run(
                ["git", "reset", "-q"], cwd=str(root), capture_output=True,
                stdin=subprocess.DEVNULL, text=True, timeout=15,
            )
    return {
        "commit_sha": _run("rev-parse", "HEAD"),
        "diff_hash": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
    }


def _changed_paths(root: Path) -> List[str]:
    out: List[str] = []

    def _run(*args: str) -> List[str]:
        try:
            done = subprocess.run(["git", *args], cwd=str(root), capture_output=True, stdin=subprocess.DEVNULL, text=True, timeout=15)
            if done.returncode != 0:
                return []
            return [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]
        except Exception:
            return []

    out.extend(_run("diff", "--name-only", "HEAD"))
    # Ask Git directly for untracked files instead of parsing porcelain status.
    # On Windows, rapid init/write/status cycles can intermittently yield an empty
    # porcelain snapshot under captured subprocess output; ls-files is the narrower,
    # deterministic source for exactly the untracked paths this coverage gate needs.
    out.extend(_run("ls-files", "--others", "--exclude-standard"))

    def _is_verifier_byproduct(path: str) -> bool:
        # Same non-source, tool-generated-byproduct category as __pycache__/
        # .pyc/.pyo below: pytest-cov/coverage.py rewrites `.coverage` (and,
        # in parallel mode, `.coverage.<host>.<pid>.<rand>` siblings) with
        # fresh content on every run of a task's own Coverage verifier lane.
        # Left uncounted here, running that lane before this diff-coverage
        # check (e.g. a run-scoped `verify` regenerating a stale quality
        # matrix) makes its own byproduct look like drift no operator
        # receipt accounts for.
        name = path.rsplit("/", 1)[-1]
        return (
            name == ".coverage" or name.startswith(".coverage.")
            or path == "htmlcov" or path.startswith("htmlcov/") or "/htmlcov/" in path
        )

    return sorted({
        path for path in out
        if path
        and not path.startswith(".simplicio/orchestrator/")
        and not path.startswith(".simplicio/")
        and "__pycache__" not in path
        and not path.endswith((".pyc", ".pyo"))
        and not _is_verifier_byproduct(path)
    })


def _operator_diff_coverage(root: Path, operator: Dict[str, Any]) -> Dict[str, Any]:
    changed = _changed_paths(root)
    covered = sorted(set(str(path) for path in (operator.get("changed_paths") or []) if str(path)))
    uncovered = [path for path in changed if path not in covered]
    return {
        "changed_paths": changed,
        "covered_paths": covered,
        "uncovered_paths": uncovered,
        "coverage_ok": not uncovered,
    }


def build_evidence_receipt(run_dir: str) -> Dict[str, Any]:
    root = Path(run_dir)
    repo_root = root.parents[2] if len(root.parents) >= 3 else root
    manifest_path = root / "manifest.json"
    task_contract_path = root / "task-contract.json"
    operator_path = root / "operator-receipt.json"
    mapper_path = root / "mapper-context.json"
    plan_path = root / "plan.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    task_contract = json.loads(task_contract_path.read_text(encoding="utf-8"))
    operator = json.loads(operator_path.read_text(encoding="utf-8"))
    mapper = json.loads(mapper_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
    tasks = task_contract.get("tasks") or []

    scenarios: List[Dict[str, Any]] = []
    rules: List[Dict[str, Any]] = []
    criteria: List[Dict[str, Any]] = []
    criterion_index = 1
    for task_index, task in enumerate(tasks, start=1):
        for scenario in task.get("scenarios") or []:
            verification_state = "proposed" if operator.get("execution_state") == "dry_run" else "unverified"
            scenarios.append(
                {
                    "task_index": task_index,
                    "id": scenario.get("id"),
                    "title": scenario.get("title"),
                    "rule_refs": scenario.get("rule_refs") or [],
                    "verification_intent": scenario.get("verification_intent", ""),
                    "verification_state": verification_state,
                    "proof_refs": [str(operator_path)],
                }
            )
            criteria.append(
                {
                    "id": f"AC{criterion_index}",
                    "scenario_id": scenario.get("id"),
                    "title": scenario.get("title"),
                    "rule_refs": scenario.get("rule_refs") or [],
                    "verification_state": verification_state,
                    "proof_refs": [str(operator_path)],
                }
            )
            criterion_index += 1
        for rule in task.get("rules") or []:
            rules.append(
                {
                    "task_index": task_index,
                    "id": rule.get("id"),
                    "scenario_refs": rule.get("scenario_refs") or [],
                    "verification_state": "proposed"
                    if operator.get("execution_state") == "dry_run"
                    else "unverified",
                    "proof_refs": [str(operator_path)],
                }
            )

    checks = []
    for task_index, task in enumerate(tasks, start=1):
        verifier_command = ""
        for entry in task.get("additional_information") or []:
            text = entry if isinstance(entry, str) else str((entry or {}).get("text") or "")
            match = re.search(r"Independent verifier:\s*`([^`]+)`", text, flags=re.I)
            if match:
                verifier_command = match.group(1).strip()
                break
        if verifier_command:
            checks.append(
                {
                    "id": f"task-{task_index}-independent-verifier",
                    "kind": "independent_filesystem_verifier",
                    "argv": shlex.split(verifier_command),
                    "cwd": str(repo_root),
                    "expected_exit_code": 0,
                    "proof_ref": str(operator_path),
                    "status": "proposed",
                }
            )
    if operator.get("execution_state") == "dry_run":
        checks.append(
            {
                "id": "operator_dry_run_receipt",
                "kind": "operator_receipt",
                "command": "",
                "cwd": "",
                "expected_exit_code": 0,
                "proof_ref": str(operator_path),
                "status": "proposed",
            }
        )

    git_meta = _git_meta(repo_root)
    diff_coverage = _operator_diff_coverage(repo_root, operator)
    receipt = {
        "schema": SCHEMA,
        "run_id": manifest.get("run_id"),
        "delivery_target": manifest.get("delivery_target"),
        "status": "UNVERIFIED",
        "measured_at": _now(),
        "run": {
            "manifest_path": str(manifest_path),
            "task_contract_path": str(task_contract_path),
            "plan_path": str(plan_path) if plan_path.exists() else "",
            "task_contract_hash": task_contract.get("collection_hash") or _file_hash(task_contract_path),
            "plan_hash": _file_hash(plan_path) if plan_path.exists() else "",
            "commit_sha": git_meta["commit_sha"],
            "diff_hash": git_meta["diff_hash"],
        },
        "operator": {
            "mode": operator.get("mode"),
            "execution_state": operator.get("execution_state"),
            "target": operator.get("target"),
            "receipt_path": str(operator_path),
            "changed_paths": diff_coverage["changed_paths"],
            "covered_paths": diff_coverage["covered_paths"],
            "uncovered_paths": diff_coverage["uncovered_paths"],
            "coverage_ok": diff_coverage["coverage_ok"],
        },
        "mapper": {
            "receipt_path": str(mapper_path),
            "targets": (((mapper.get("handoff") or {}).get("stdout") or {}).get("context_pack") or {}).get("files", []),
        },
        "task_contract_path": str(task_contract_path),
        "criteria": criteria,
        "scenarios": scenarios,
        "rules": rules,
        "checks": checks,
        "summary": {
            "criteria_total": len(criteria),
            "criteria_verified": sum(1 for c in criteria if c["verification_state"] == "verified"),
            "scenario_total": len(scenarios),
            "scenario_verified": sum(1 for s in scenarios if s["verification_state"] == "verified"),
            "rule_total": len(rules),
            "rule_verified": sum(1 for r in rules if r["verification_state"] == "verified"),
        },
    }
    if checks:
        verification = execute_receipt_checks(receipt)
        receipt["check_results"] = verification["results"]
        result_by_id = {
            str(item.get("id")): item for item in verification["results"]
        }
        for check in receipt["checks"]:
            result = result_by_id.get(str(check.get("id")))
            if result is not None:
                check["status"] = result.get("status", "UNVERIFIED")
        if verification["all_passed"] and receipt["operator"]["coverage_ok"]:
            for collection in (receipt["criteria"], receipt["scenarios"], receipt["rules"]):
                for item in collection:
                    item["verification_state"] = "verified"
            receipt["summary"]["criteria_verified"] = receipt["summary"]["criteria_total"]
            receipt["summary"]["scenario_verified"] = receipt["summary"]["scenario_total"]
            receipt["summary"]["rule_verified"] = receipt["summary"]["rule_total"]
            receipt["status"] = "VERIFIED"
            anchor_path = root / "loop" / "anchor.json"
            try:
                anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
                for item in anchor.get("criteria") or []:
                    item["status"] = "done"
                anchor_path.write_text(
                    json.dumps(anchor, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except (OSError, TypeError, ValueError):
                # The evidence receipt remains truthful; the watcher will fail closed
                # if its independently required anchor cannot be updated.
                pass
    return receipt


def watcher_truth_from_receipt(receipt: Dict[str, Any]) -> Dict[str, Any]:
    summary = receipt.get("summary") or {}
    criteria_total = int(summary.get("criteria_total") or 0)
    criteria_verified = int(summary.get("criteria_verified") or 0)
    scenario_total = int(summary.get("scenario_total") or 0)
    scenario_verified = int(summary.get("scenario_verified") or 0)
    rule_total = int(summary.get("rule_total") or 0)
    rule_verified = int(summary.get("rule_verified") or 0)
    direct_criteria = receipt.get("criteria") or []
    direct_rules = receipt.get("rules") or []
    if direct_criteria:
        criteria_ready = all((item.get("verification_state") == "verified") for item in direct_criteria)
        rules_ready = all((item.get("verification_state") == "verified") for item in direct_rules)
        if not direct_rules and rule_total:
            rules_ready = rule_verified == rule_total
        ready = criteria_ready and rules_ready and receipt.get("status") == "VERIFIED"
        verified = sum(1 for item in direct_criteria if item.get("verification_state") == "verified")
        total = len(direct_criteria)
    else:
        total = criteria_total or (scenario_total + rule_total)
        verified = criteria_verified or (scenario_verified + rule_verified)
        ready = bool(total) and verified == total and receipt.get("status") == "VERIFIED"
    return {
        "ready": ready,
        "reported": f"{verified}/{total} evidence checks verified",
        "status": "MEASURED" if ready else "UNVERIFIED",
    }


def execute_receipt_checks(receipt: Dict[str, Any]) -> Dict[str, Any]:
    checks = receipt.get("checks") or []
    results = []
    all_passed = True
    for check in checks:
        expected = int(check.get("expected_exit_code", 0))
        argv, policy_reason = _command_policy(check)
        if argv is None:
            results.append(
                {
                    "id": check.get("id"),
                    "status": "UNVERIFIED",
                    "reason": policy_reason,
                    "returncode": None,
                    "proof_ref": check.get("proof_ref", ""),
                    "policy": "blocked",
                }
            )
            all_passed = False
            continue
        try:
            completed = subprocess.run(argv, shell=False, cwd=check.get("cwd") or None,
                                       capture_output=True, text=True, timeout=60)
            ok = completed.returncode == expected
            results.append(
                {
                    "id": check.get("id"),
                    "status": "MEASURED" if ok else "UNVERIFIED",
                    "reason": "command matched expected exit code" if ok else "command failed",
                    "returncode": completed.returncode,
                    "stdout": redact_sensitive_text((completed.stdout or "").strip()),
                    "stderr": redact_sensitive_text((completed.stderr or "").strip()),
                    "proof_ref": check.get("proof_ref", ""),
                    "policy": "allowed",
                    "argv": argv,
                }
            )
            all_passed = all_passed and ok
        except Exception as exc:
            results.append(
                {
                    "id": check.get("id"),
                    "status": "UNVERIFIED",
                    "reason": redact_sensitive_text(str(exc)),
                    "returncode": None,
                    "proof_ref": check.get("proof_ref", ""),
                    "policy": "error",
                    "argv": argv,
                }
            )
            all_passed = False
    return {"all_passed": all_passed, "results": results}


def _write_receipt(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_build(args: argparse.Namespace) -> int:
    payload = build_evidence_receipt(args.run_dir)
    out = Path(args.out) if args.out else (Path(args.run_dir) / "evidence-receipt.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_receipt(out, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    fake = {
        "schema": SCHEMA,
        "status": "UNVERIFIED",
        "criteria": [{"id": "AC1", "verification_state": "verified"}, {"id": "AC2", "verification_state": "unverified"}],
        "summary": {"criteria_total": 2, "criteria_verified": 1, "scenario_total": 2, "scenario_verified": 1, "rule_total": 1, "rule_verified": 0},
    }
    verdict = watcher_truth_from_receipt(fake)
    assert verdict["ready"] is False
    fake["status"] = "VERIFIED"
    fake["criteria"] = [{"id": "AC1", "verification_state": "verified"}, {"id": "AC2", "verification_state": "verified"}]
    fake["summary"] = {"criteria_total": 2, "criteria_verified": 2, "scenario_total": 1, "scenario_verified": 1, "rule_total": 1, "rule_verified": 1}
    verdict = watcher_truth_from_receipt(fake)
    assert verdict["ready"] is True
    exec_result = execute_receipt_checks({
        "checks": [{"id": "ok", "argv": [__import__("sys").executable, "-c", "print(1)"],
                    "expected_exit_code": 0}]
    })
    assert exec_result["all_passed"] is True
    print("selftest: PASS evidence-receipt")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evidence_receipt")
    sub = parser.add_subparsers(dest="verb", required=True)
    p_build = sub.add_parser("build", help="build a signed evidence receipt from a run directory")
    p_build.add_argument("--run-dir", required=True)
    p_build.add_argument("--out")
    p_build.set_defaults(func=cmd_build)
    p_self = sub.add_parser("selftest", help="run the deterministic evidence-receipt selftest")
    p_self.set_defaults(func=cmd_selftest)
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
