"""Deterministic Prototype-First adapter for the dev CLI."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_PLAN = "simplicio.prototype-plan/v1"
SCHEMA_RECEIPT = "simplicio.prototype-receipt/v1"
SCHEMA_DECISION = "simplicio.prototype-decision/v1"
TYPES = ("schema", "data_model", "failing_test", "mock", "code_spike", "vertical_slice")


class PrototypeError(RuntimeError):
    """User-facing, fail-closed prototype error."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _tree(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not root.exists():
        return result
    for item in sorted(root.rglob("*")):
        if item.is_file() and ".git" not in item.parts:
            result[item.relative_to(root).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrototypeError(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PrototypeError(f"JSON artifact must be an object: {path}")
    return payload


def _plan_from_args(args: Any) -> dict[str, Any]:
    payload = _read_json(args.input) if args.input else {"goal": args.goal, "prototype_type": args.prototype_type, "source_sha": ""}
    if payload.get("schema", SCHEMA_PLAN) != SCHEMA_PLAN:
        raise PrototypeError(f"unsupported plan schema; expected {SCHEMA_PLAN}")
    prototype_type = payload.get("prototype_type", payload.get("type"))
    if prototype_type not in TYPES:
        raise PrototypeError(f"prototype_type must be one of: {', '.join(TYPES)}")
    goal = payload.get("goal") or ""
    if not isinstance(goal, str) or not goal.strip():
        raise PrototypeError("plan requires a non-empty goal")
    payload = dict(payload)
    payload.update({"schema": SCHEMA_PLAN, "prototype_type": prototype_type, "goal": goal})
    payload.setdefault("validators", [])
    if not isinstance(payload["validators"], list) or not all(isinstance(x, str) and x.strip() for x in payload["validators"]):
        raise PrototypeError("validators must be a list of command strings")
    payload["plan_hash"] = _sha({k: v for k, v in payload.items() if k != "plan_hash"})
    return payload


def _candidate_dir(args: Any, plan: dict[str, Any]) -> Path:
    return Path(args.candidate).resolve() if args.candidate else Path(args.root).resolve() / ".simplicio" / "prototypes" / plan["plan_hash"][:16]


def _skeleton(plan: dict[str, Any]) -> dict[str, str]:
    kind = plan["prototype_type"]
    name = str(plan.get("name") or "prototype")
    if kind == "schema":
        return {f"{name}.schema.json": json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "title": name, "type": "object", "properties": {}}, indent=2) + "\n"}
    if kind == "data_model":
        return {"MODEL.md": f"# {name}\n\nData model prototype.\n\nGoal: {plan['goal']}\n"}
    if kind == "failing_test":
        return {"test_prototype.py": "def test_prototype_reproducer():\n    raise AssertionError('prototype reproducer: implement expected behavior')\n"}
    if kind == "mock":
        return {"mock_adapter.py": "class PrototypeAdapter:\n    \"\"\"Contract-only adapter; no production side effects.\"\"\"\n\n    def call(self, *args, **kwargs):\n        raise NotImplementedError('prototype adapter')\n"}
    if kind == "code_spike":
        return {"spike.py": f"\"\"\"Bounded code spike for: {plan['goal']}\"\"\"\n\n\ndef run():\n    raise NotImplementedError('prototype spike')\n"}
    return {"VERTICAL_SLICE.md": f"# Vertical slice: {name}\n\nGoal: {plan['goal']}\n\n- [ ] implement one reversible real path\n"}


def run(args: Any) -> int:
    try:
        command = args.prototype_cmd
        if command == "plan":
            payload = _plan_from_args(args)
            _write_json(Path(args.output).resolve(), payload)
            return _emit(args, payload)
        if command == "doctor":
            return _emit(args, {"schema": SCHEMA_RECEIPT, "plan_schema": SCHEMA_PLAN, "receipt_schema": SCHEMA_RECEIPT, "decision_schema": SCHEMA_DECISION, "isolated_default": True, "ok": True})
        plan = _read_json(args.plan)
        if plan.get("schema") != SCHEMA_PLAN or plan.get("plan_hash") != _sha({k: v for k, v in plan.items() if k != "plan_hash"}):
            raise PrototypeError("plan hash/schema mismatch")
        candidate = _candidate_dir(args, plan)
        if command == "scaffold":
            if candidate.exists() and any(candidate.iterdir()) and not args.force:
                raise PrototypeError(f"candidate exists; use --force explicitly: {candidate}")
            candidate.mkdir(parents=True, exist_ok=True)
            for relative, content in _skeleton(plan).items():
                target = candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="\n")
            tree = _tree(candidate)
            payload = {"schema": SCHEMA_RECEIPT, "kind": "scaffold", "plan_hash": plan["plan_hash"], "candidate": str(candidate), "candidate_tree": tree, "candidate_hash": _sha(tree)}
            _write_json(candidate / ".prototype-receipt.json", payload)
            return _emit(args, payload)
        if not candidate.is_dir():
            raise PrototypeError(f"candidate does not exist: {candidate}")
        if command == "dry-run":
            return _emit(args, {"schema": SCHEMA_RECEIPT, "kind": "dry-run", "plan_hash": plan["plan_hash"], "candidate": str(candidate), "writes": sorted(_tree(candidate))})
        if command == "diff":
            before, after = _tree(Path(args.target).resolve()), _tree(candidate)
            return _emit(args, {"schema": SCHEMA_RECEIPT, "kind": "diff", "plan_hash": plan["plan_hash"], "added": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after)), "changed": sorted(k for k in set(before) & set(after) if before[k] != after[k])})
        if command == "validate":
            results = []
            for command_line in plan.get("validators", []):
                proc = subprocess.run(command_line, cwd=candidate, shell=True, capture_output=True, text=True, timeout=args.timeout, check=False)
                results.append({"command": command_line, "exit_code": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]})
            tree = _tree(candidate)
            payload = {"schema": SCHEMA_RECEIPT, "kind": "validation", "plan_hash": plan["plan_hash"], "candidate": str(candidate), "candidate_tree": tree, "candidate_hash": _sha(tree), "validators": results, "valid": all(x["exit_code"] == 0 for x in results)}
            _write_json(candidate / ".prototype-receipt.json", payload)
            return _emit(args, payload, status=0 if payload["valid"] else 1)
        if command in {"promote", "reject"}:
            receipt = _read_json(args.receipt or candidate / ".prototype-receipt.json")
            if receipt.get("schema") != SCHEMA_RECEIPT or receipt.get("plan_hash") != plan["plan_hash"]:
                raise PrototypeError("receipt is not bound to this plan")
            decision = "ACCEPT" if command == "promote" else "REJECT"
            if command == "promote":
                if receipt.get("kind") != "validation" or not receipt.get("valid"):
                    raise PrototypeError("cannot promote without a successful validation receipt")
                decision_payload = _read_json(args.decision or candidate / ".prototype-decision.json")
                if decision_payload.get("schema") != SCHEMA_DECISION or decision_payload.get("decision") != "ACCEPT" or decision_payload.get("plan_hash") != plan["plan_hash"] or decision_payload.get("candidate_hash") != receipt.get("candidate_hash"):
                    raise PrototypeError("promote requires a current ACCEPT decision receipt")
                target = Path(args.target).resolve() if args.target else None
                if target is None:
                    raise PrototypeError("promote requires an explicit --target")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = Path(tempfile.mkdtemp(prefix="simplicio-promote-", dir=target.parent))
                try:
                    shutil.copytree(candidate, temporary, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".prototype-receipt.json", ".prototype-decision.json"))
                    if target.exists():
                        backup = target.with_name(target.name + ".prototype-backup")
                        if backup.exists(): shutil.rmtree(backup)
                        os.replace(target, backup)
                    os.replace(temporary, target)
                finally:
                    if temporary.exists(): shutil.rmtree(temporary)
            payload = {"schema": SCHEMA_DECISION, "decision": decision, "plan_hash": plan["plan_hash"], "candidate_hash": receipt.get("candidate_hash"), "receipt_hash": _sha(receipt)}
            _write_json(Path(args.decision or candidate / ".prototype-decision.json"), payload)
            return _emit(args, payload)
        raise PrototypeError(f"unknown prototype command: {command}")
    except (PrototypeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"simplicio-py prototype: error: {exc}", file=sys.stderr)
        return 2


def _emit(args: Any, payload: dict[str, Any], *, status: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True) if args.json else json.dumps(payload, ensure_ascii=False, indent=2))
    return status
