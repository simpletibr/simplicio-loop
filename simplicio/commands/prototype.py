"""Deterministic Prototype-First adapter for the dev CLI."""

from __future__ import annotations

import glob as glob_module
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

SCHEMA_PLAN = "simplicio.prototype-plan/v1"
SCHEMA_RECEIPT = "simplicio.prototype-receipt/v1"
SCHEMA_DECISION = "simplicio.prototype-decision/v1"
TYPES = ("wireframe", "architecture_diagram", "schema", "data_model", "failing_reproducer", "benchmark_spike", "mock_or_fake", "code_spike", "vertical_slice", "prompt_candidate", "workflow_simulation", "storyboard", "policy_or_security_model")
# Bookkeeping directories the prototype adapter itself writes into (candidate
# sandboxes, receipts, decisions). Excluded from the source-tree hash so that
# scaffolding/validating a candidate never perturbs the very source_sha it is
# compared against (issue #236 stale-candidate detection).
_SOURCE_EXCLUDES = (".git", ".simplicio")


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


def _source_tree(root: Path) -> dict[str, str]:
    """Like `_tree`, but also excludes the adapter's own bookkeeping dirs
    (`.simplicio/`) so that scaffolding a candidate never changes the
    source-tree hash it is later checked against (stale-candidate gate)."""
    result: dict[str, str] = {}
    if not root.exists():
        return result
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        parts = item.relative_to(root).parts
        if parts and parts[0] in _SOURCE_EXCLUDES:
            continue
        result[item.relative_to(root).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    return result


def _source_sha(root: Path) -> str:
    return _sha(_source_tree(root))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
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
    payload = (
        _read_json(args.input) if args.input else {"goal": args.goal, "prototype_type": args.prototype_type}
    )
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
    if not isinstance(payload["validators"], list) or not all(
        isinstance(x, str) and x.strip() for x in payload["validators"]
    ):
        raise PrototypeError("validators must be a list of command strings")
    # source_sha anchors the plan to the state of --root at plan time. An
    # upstream producer (Loop/Mapper context pack, #568) may already supply
    # one via --input; otherwise compute it locally from --root so the
    # stale-candidate gate (see `_assert_not_stale`) has a real baseline
    # instead of silently no-op'ing.
    if not payload.get("source_sha"):
        payload["source_sha"] = _source_sha(Path(args.root).resolve())
    payload["plan_hash"] = _sha({k: v for k, v in payload.items() if k != "plan_hash"})
    return payload


def _assert_not_stale(args: Any, plan: dict[str, Any]) -> None:
    """Reject validate/promote against a candidate whose plan was anchored to
    a --root source tree that has since changed (issue #236 AC: stale
    candidates must be detected and rejected). No-ops when the plan carries
    no `source_sha` baseline at all (e.g. a hand-built plan file predating
    this gate) — that is a deliberate, documented back-compat escape hatch,
    not silent success on a real mismatch."""
    expected = plan.get("source_sha")
    if not expected:
        return
    current = _source_sha(Path(args.root).resolve())
    if current != expected:
        raise PrototypeError(
            "stale candidate: source tree under --root changed since this plan was created "
            f"(expected source_sha={expected[:12]}…, current={current[:12]}…); re-plan and re-scaffold"
        )


def _candidate_dir(args: Any, plan: dict[str, Any]) -> Path:
    # `batch` has no meaningful single `--candidate` override (it fans out
    # over many plans, each keyed by its own plan_hash), so its parser omits
    # the flag entirely; getattr keeps this helper shared without forcing a
    # dead argument onto that subcommand.
    candidate_override = getattr(args, "candidate", None)
    return (
        Path(candidate_override).resolve()
        if candidate_override
        else Path(args.root).resolve() / ".simplicio" / "prototypes" / plan["plan_hash"][:16]
    )


def _skeleton(plan: dict[str, Any]) -> dict[str, str]:
    kind = plan["prototype_type"]
    name = str(plan.get("name") or "prototype")
    if kind == "schema":
        return {
            f"{name}.schema.json": json.dumps(
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "title": name,
                    "type": "object",
                    "properties": {},
                },
                indent=2,
            )
            + "\n"
        }
    if kind == "data_model":
        return {"MODEL.md": f"# {name}\n\nData model prototype.\n\nGoal: {plan['goal']}\n"}
    if kind in {"failing_test", "failing_reproducer"}:
        return {"test_prototype.py": "def test_prototype_reproducer():\n    raise AssertionError('prototype reproducer: implement expected behavior')\n"}
    if kind in {"mock", "mock_or_fake"}:
        return {"mock_adapter.py": "class PrototypeAdapter:\n    \"\"\"Contract-only adapter; no production side effects.\"\"\"\n\n    def call(self, *args, **kwargs):\n        raise NotImplementedError('prototype adapter')\n"}
    if kind in {"code_spike", "benchmark_spike"}:
        return {"spike.py": f"\"\"\"Bounded code spike for: {plan['goal']}\"\"\"\n\n\ndef run():\n    raise NotImplementedError('prototype spike')\n"}
    return {"PROTOTYPE.md": f"# {kind}: {name}\n\nGoal: {plan['goal']}\n\n- [ ] implement one bounded, reversible candidate\n"}


def _scaffold_candidate(candidate: Path, plan: dict[str, Any], *, force: bool) -> dict[str, Any]:
    """Write the plan's skeleton into an isolated candidate dir and return the
    scaffold receipt payload. Shared by the single-candidate `scaffold`
    command and the `batch` fan-out so both stay byte-identical."""
    if candidate.exists() and any(candidate.iterdir()) and not force:
        raise PrototypeError(f"candidate exists; use --force explicitly: {candidate}")
    candidate.mkdir(parents=True, exist_ok=True)
    for relative, content in _skeleton(plan).items():
        target = candidate / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    tree = _tree(candidate)
    payload = {
        "schema": SCHEMA_RECEIPT,
        "kind": "scaffold",
        "plan_hash": plan["plan_hash"],
        "candidate": str(candidate),
        "candidate_tree": tree,
        "candidate_hash": _sha(tree),
    }
    _write_json(candidate / ".prototype-receipt.json", payload)
    return payload


def _validate_candidate(args: Any, plan: dict[str, Any], candidate: Path) -> dict[str, Any]:
    """Run the plan's validators inside the candidate sandbox and return the
    validation receipt payload. Shared by the single-candidate `validate`
    command and the `batch` fan-out."""
    _assert_not_stale(args, plan)
    results = []
    for command_line in plan.get("validators", []):
        proc = subprocess.run(
            command_line,
            cwd=candidate,
            shell=True,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
        results.append(
            {
                "command": command_line,
                "exit_code": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
        )
    tree = _tree(candidate)
    payload = {
        "schema": SCHEMA_RECEIPT,
        "kind": "validation",
        "plan_hash": plan["plan_hash"],
        "candidate": str(candidate),
        "candidate_tree": tree,
        "candidate_hash": _sha(tree),
        "validators": results,
        "valid": all(x["exit_code"] == 0 for x in results),
    }
    _write_json(candidate / ".prototype-receipt.json", payload)
    return payload


def _load_bound_plan(plan_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read a plan file and verify its self-describing hash/schema, the same
    check every non-`plan` prototype command performs before trusting it."""
    plan = _read_json(plan_path)
    if plan.get("schema") != SCHEMA_PLAN or plan.get("plan_hash") != _sha(
        {k: v for k, v in plan.items() if k != "plan_hash"}
    ):
        raise PrototypeError(f"plan hash/schema mismatch: {plan_path}")
    return plan


def _discover_plan_paths(plans_arg: str) -> list[Path]:
    """Resolve `--plans` (a directory of plan JSONs, or a glob pattern) into a
    deterministic, sorted list of plan files. Never silently returns an empty
    batch — an empty match is a configuration error, not a no-op success."""
    base = Path(plans_arg)
    if base.is_dir():
        paths = sorted(base.glob("*.json"))
    else:
        paths = sorted(Path(p) for p in glob_module.glob(plans_arg))
    if not paths:
        raise PrototypeError(f"no plan files matched --plans {plans_arg!r}")
    return paths


def _process_one_plan(plan_path: Path, args: Any) -> dict[str, Any]:
    """Scaffold + validate a single plan file for the `batch` fan-out.

    Deliberately swallows every exception into an `error` status instead of
    propagating: one candidate's validator crashing (bad command, malformed
    plan, OS error) must never abort or corrupt sibling candidates running
    concurrently in the same batch (issue #236 AC: failure isolation).
    """
    try:
        plan = _load_bound_plan(plan_path)
        candidate = _candidate_dir(args, plan)
        _scaffold_candidate(candidate, plan, force=args.force)
        receipt = _validate_candidate(args, plan, candidate)
        return {
            "plan": str(plan_path),
            "plan_hash": plan.get("plan_hash"),
            "candidate": receipt["candidate"],
            "status": "ok" if receipt["valid"] else "failed",
            "valid": receipt["valid"],
            "validators": receipt["validators"],
        }
    except Exception as exc:  # noqa: BLE001 - batch isolation boundary, see docstring
        return {
            "plan": str(plan_path),
            "plan_hash": None,
            "candidate": None,
            "status": "error",
            "valid": False,
            "error": str(exc),
            "error_type": exc.__class__.__name__,
        }


def _run_batch(args: Any) -> dict[str, Any]:
    """Scaffold+validate every plan under `--plans`, bounded to `--concurrency`
    concurrent workers (backpressure): later plans queue behind the
    ThreadPoolExecutor's fixed worker count rather than spawning unbounded
    threads/processes. Mirrors the bounded-fan-out pattern already used by
    `simplicio/orchestrator/multi_task.py::TaskBatch.drain`
    (`ThreadPoolExecutor(max_workers=min(concurrency, len(plans)))`).
    """
    concurrency = args.concurrency
    if concurrency < 1:
        raise PrototypeError("--concurrency must be >= 1")
    plan_paths = _discover_plan_paths(args.plans)

    if concurrency == 1 or len(plan_paths) < 2:
        results = {str(p): _process_one_plan(p, args) for p in plan_paths}
    else:
        results = {}
        with ThreadPoolExecutor(max_workers=min(concurrency, len(plan_paths))) as pool:
            futures = {pool.submit(_process_one_plan, p, args): p for p in plan_paths}
            for future in as_completed(futures):
                results[str(futures[future])] = future.result()

    ordered = [results[str(p)] for p in plan_paths]
    return {
        "schema": SCHEMA_RECEIPT,
        "kind": "batch",
        "plans": str(args.plans),
        "concurrency": concurrency,
        "total": len(ordered),
        "ok": sum(1 for r in ordered if r["status"] == "ok"),
        "failed": sum(1 for r in ordered if r["status"] == "failed"),
        "errored": sum(1 for r in ordered if r["status"] == "error"),
        "results": ordered,
    }


def run(args: Any) -> int:
    try:
        command = args.prototype_cmd
        if command == "plan":
            payload = _plan_from_args(args)
            _write_json(Path(args.output).resolve(), payload)
            return _emit(args, payload)
        if command == "doctor":
            return _emit(
                args,
                {
                    "schema": SCHEMA_RECEIPT,
                    "plan_schema": SCHEMA_PLAN,
                    "receipt_schema": SCHEMA_RECEIPT,
                    "decision_schema": SCHEMA_DECISION,
                    "isolated_default": True,
                    "ok": True,
                },
            )
        if command == "batch":
            payload = _run_batch(args)
            return _emit(args, payload, status=0 if payload["failed"] == 0 and payload["errored"] == 0 else 1)
        plan = _load_bound_plan(args.plan)
        candidate = _candidate_dir(args, plan)
        if command == "scaffold":
            payload = _scaffold_candidate(candidate, plan, force=args.force)
            return _emit(args, payload)
        if not candidate.is_dir():
            raise PrototypeError(f"candidate does not exist: {candidate}")
        if command == "dry-run":
            return _emit(
                args,
                {
                    "schema": SCHEMA_RECEIPT,
                    "kind": "dry-run",
                    "plan_hash": plan["plan_hash"],
                    "candidate": str(candidate),
                    "writes": sorted(_tree(candidate)),
                },
            )
        if command == "diff":
            before, after = _tree(Path(args.target).resolve()), _tree(candidate)
            return _emit(
                args,
                {
                    "schema": SCHEMA_RECEIPT,
                    "kind": "diff",
                    "plan_hash": plan["plan_hash"],
                    "added": sorted(set(after) - set(before)),
                    "removed": sorted(set(before) - set(after)),
                    "changed": sorted(k for k in set(before) & set(after) if before[k] != after[k]),
                },
            )
        if command == "validate":
            payload = _validate_candidate(args, plan, candidate)
            return _emit(args, payload, status=0 if payload["valid"] else 1)
        if command in {"promote", "reject"}:
            receipt = _read_json(args.receipt or candidate / ".prototype-receipt.json")
            if receipt.get("schema") != SCHEMA_RECEIPT or receipt.get("plan_hash") != plan["plan_hash"]:
                raise PrototypeError("receipt is not bound to this plan")
            decision = "ACCEPT" if command == "promote" else "REJECT"
            if command == "promote":
                _assert_not_stale(args, plan)
                if receipt.get("kind") != "validation" or not receipt.get("valid"):
                    raise PrototypeError("cannot promote without a successful validation receipt")
                decision_payload = _read_json(args.decision or candidate / ".prototype-decision.json")
                if (
                    decision_payload.get("schema") != SCHEMA_DECISION
                    or decision_payload.get("decision") != "ACCEPT"
                    or decision_payload.get("plan_hash") != plan["plan_hash"]
                    or decision_payload.get("candidate_hash") != receipt.get("candidate_hash")
                ):
                    raise PrototypeError("promote requires a current ACCEPT decision receipt")
                target = Path(args.target).resolve() if args.target else None
                if target is None:
                    raise PrototypeError("promote requires an explicit --target")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = Path(tempfile.mkdtemp(prefix="simplicio-promote-", dir=target.parent))
                try:
                    shutil.copytree(
                        candidate,
                        temporary,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".prototype-receipt.json", ".prototype-decision.json"),
                    )
                    if target.exists():
                        backup = target.with_name(target.name + ".prototype-backup")
                        if backup.exists():
                            shutil.rmtree(backup)
                        os.replace(target, backup)
                    os.replace(temporary, target)
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
            payload = {
                "schema": SCHEMA_DECISION,
                "decision": decision,
                "plan_hash": plan["plan_hash"],
                "candidate_hash": receipt.get("candidate_hash"),
                "receipt_hash": _sha(receipt),
            }
            _write_json(Path(args.decision or candidate / ".prototype-decision.json"), payload)
            return _emit(args, payload)
        raise PrototypeError(f"unknown prototype command: {command}")
    except (PrototypeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"simplicio-py prototype: error: {exc}", file=sys.stderr)
        return 2


def _emit(args: Any, payload: dict[str, Any], *, status: int = 0) -> int:
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if args.json
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return status
