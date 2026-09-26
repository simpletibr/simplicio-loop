"""Materialize intake items through the canonical Loop run boundary."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .runner import arm_run

RECEIPT_SCHEMA = "simplicio.tasks-materialization-receipt/v1"

class ContractMaterializationError(RuntimeError):
    pass

def _safe(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-") or "item"

def _digest(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

def _git_text(repo: Path, *args: str) -> str:
    argv = ["git", "-C", str(repo), *args]
    if os.name == "nt":
        with tempfile.TemporaryDirectory(prefix="simplicio-tasks-base-") as directory:
            output = Path(directory) / "stdout.txt"
            error = Path(directory) / "stderr.txt"
            result = None
            for attempt in range(5):
                try:
                    with output.open("w", encoding="utf-8") as stdout_handle, \
                            error.open("w", encoding="utf-8") as stderr_handle:
                        result = subprocess.run(argv, shell=False, stdout=stdout_handle,
                                                stderr=stderr_handle, stdin=subprocess.DEVNULL,
                                                close_fds=False, text=True,
                                                timeout=10, check=False)
                    break
                except OSError as exc:
                    if getattr(exc, "winerror", None) not in {6, 50}:
                        return ""
                    if attempt < 4:
                        time.sleep(0.25)
            if result is None:
                return ""
            stdout = output.read_text(encoding="utf-8", errors="replace") if output.exists() else ""
    else:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
        stdout = result.stdout
    if result.returncode != 0:
        return ""
    return stdout.strip()

def _task_markdown(number: str, item: Mapping[str, Any]) -> str:
    title = str(item.get("title") or f"Issue {number}")
    criteria = item.get("acceptance_criteria") or []
    statements = [str(row.get("statement") or row.get("text") or "").strip() for row in criteria if isinstance(row, Mapping)]
    if not statements:
        statements = ["a implementação satisfaz o objetivo e a verificação declarada da issue"]
    scenarios = "\n\n".join(
        f"Cenário {index}: {title}\n  Dado o contexto congelado da issue #{number}\n"
        f"  Quando a implementação for verificada\n  Então {statement} [RN{index:02d}]"
        for index, statement in enumerate(statements, start=1)
    )
    rules = "\n".join(
        f"RN{index:02d} – {statement}"
        for index, statement in enumerate(statements, start=1)
    )
    return (f"Sistema: Simplicio Loop\nFuncionalidade: {title}\nTipo: Evolução\n\n"
            f"COMO mantenedor,\nQUERO resolver a issue #{number},\nPARA entregar o comportamento solicitado.\n\n"
            f"1. Critérios de Aceite\n\n{scenarios}\n\n"
            f"2. Regras de Negócio\n\n{rules}\n")

class LoopRunContractMaterializer:
    def __init__(self, repo: str, *, arm: Callable[..., Mapping[str, Any]] = arm_run, delivery: str = "pr", max_iterations: int = 12):
        self.repo = Path(repo).resolve()
        self.arm = arm
        self.delivery = delivery
        self.max_iterations = max_iterations

    def _row(self, number: str, item: Mapping[str, Any], armed: Mapping[str, Any]) -> Mapping[str, Any]:
        if not armed.get("run_dir"):
            state = armed.get("state", {})
            raise ContractMaterializationError(f"issue {number} run preflight blocked: {state.get('blockers', [])}")
        run_dir = Path(str(armed["run_dir"])).resolve()
        runs_root = (self.repo / ".simplicio-loop" / "loop-runs").resolve()
        if run_dir == runs_root or runs_root not in run_dir.parents:
            raise ContractMaterializationError(f"issue {number} run_dir escapes canonical loop-runs root")
        state_path = run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else armed.get("state", {})
        if state.get("phase") != "awaiting_decision":
            raise ContractMaterializationError(f"issue {number} run preflight blocked: {state.get('blockers', [])}")
        plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
        targets = list(((plan.get("steps") or [{}])[0].get("candidate_targets") or []))
        if not targets:
            raise ContractMaterializationError(f"issue {number} has no authorized targets")
        authority = {"request": str(item.get("title") or ""), "source": {"issue": str(number), "revision": item.get("source_revision"), "planning_receipt": item.get("planning_receipt")}, "command": {"delivery": self.delivery, "max_iterations": self.max_iterations}, "targets": targets, "operator": "simplicio-dev-cli"}
        authority["receipt_hash"] = _digest(authority)
        base_ref = str(item.get("base_ref") or "")
        if not base_ref:
            base_ref = _git_text(self.repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        if not base_ref:
            base_ref = f"origin/{item.get('default_branch') or 'main'}"
        base_sha = str(item.get("base_sha") or _git_text(self.repo, "rev-parse", "--verify", base_ref))
        if not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha):
            raise ContractMaterializationError(f"issue {number} has no canonical base SHA for {base_ref}")
        return {"repo": str(self.repo), "run_id": armed["manifest"]["run_id"], "task_index": 1, "task_id": f"issue-{number}", "isolation": "worktree", "isolation_key": f"issue-{number}", "authority_receipt": authority, "expected_base_ref": base_ref, "expected_base_sha": base_sha, "task_spec": {"id": f"issue-{number}", "goal": str(item.get("title") or ""), "files_affected": targets}}
    def __call__(self, intake: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        identity = intake.get("run_identity", {})
        batch = _safe(identity.get("run_id") or identity.get("request_digest") or "tasks")
        task_dir = self.repo / ".simplicio-loop" / "tasks-run" / batch
        task_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = task_dir / "materialization-receipt.json"
        if receipt_path.exists():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                raise ContractMaterializationError(f"invalid materialization receipt: {exc}") from exc
            stored_hash = receipt.pop("receipt_hash", None)
            if receipt.get("schema") != RECEIPT_SCHEMA or not isinstance(receipt.get("items"), dict):
                raise ContractMaterializationError("invalid materialization receipt schema")
            if not stored_hash or stored_hash != _digest(receipt):
                raise ContractMaterializationError("invalid materialization receipt hash")
        else:
            receipt = {"schema": RECEIPT_SCHEMA, "items": {}}
        rows = []
        for number, item in sorted((intake.get("items") or {}).items(), key=lambda row: str(row[0])):
            if item.get("state") != "planned":
                continue
            fingerprint = _digest({"number": number, "source_revision": item.get("source_revision"), "planning_receipt": item.get("planning_receipt")})
            saved = receipt["items"].get(str(number), {})
            if saved.get("fingerprint") == fingerprint:
                armed = saved.get("armed", {})
                rows.append(self._row(str(number), item, armed))
                continue
            task_path = task_dir / f"issue-{_safe(number)}.md"
            task_path.write_text(_task_markdown(str(number), item), encoding="utf-8")
            armed = self.arm(str(self.repo), str(task_path), self.delivery, self.max_iterations)
            row = self._row(str(number), item, armed)
            receipt["items"][str(number)] = {"fingerprint": fingerprint, "armed": {"manifest": armed["manifest"], "run_dir": armed["run_dir"]}}
            persisted = dict(receipt)
            persisted["receipt_hash"] = _digest(receipt)
            receipt_path.write_text(json.dumps(persisted, sort_keys=True, indent=2), encoding="utf-8")
            rows.append(row)
        return rows
