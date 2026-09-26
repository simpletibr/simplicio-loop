#!/usr/bin/env python3
"""Reproducible local evidence runner for the Mapper/Dev CLI proof (#422).

Unavailable cross-repository capabilities are recorded as ``UNVERIFIED``;
they are never converted to pass or silently replaced with synthetic data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# Always exercise the checkout under test instead of an older installed
# simplicio package that may be earlier on the interpreter's import path.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from simplicio.changeset_v2 import execute_changeset  # noqa: E402
from simplicio.execution_mode import negotiate_execution_mode  # noqa: E402
from simplicio.plan_compiler.canonical_hash import canonical_hash  # noqa: E402
from simplicio.plan_compiler.runtime_effect_sink import HttpRuntimeTransport, RuntimeEffectError  # noqa: E402
from simplicio.runtime_contracts import runtime_verify_contract  # noqa: E402

SCHEMA = "simplicio.dev-cli.issue-422-evidence/v1"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_sha(root: Path) -> str | None:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        close_fds=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _changeset(count: int) -> dict[str, Any]:
    operations = [
        {"kind": "create", "path": f"files/file-{index:03d}.txt", "content": f"value-{index}\n"}
        for index in range(count)
    ]
    return {
        "schema": "simplicio.fast.changeset/v2",
        "changeset_id": f"issue-422-{count}",
        "correlation_id": f"issue-422-{count}",
        "generation": "generation-1",
        "allowlist": [item["path"] for item in operations],
        "operations": operations,
    }


def _transaction_scenario(count: int, repeats: int) -> dict[str, Any]:
    samples: list[float] = []
    with tempfile.TemporaryDirectory(prefix=f"simplicio-422-{count}-") as raw_root:
        root = Path(raw_root)
        changeset = _changeset(count)
        first: dict[str, Any] | None = None
        for _ in range(repeats):
            started = time.perf_counter()
            result = execute_changeset(changeset, root=root, apply=True)
            samples.append((time.perf_counter() - started) * 1000)
            first = first or result
            if result.get("status") != "ok":
                return {
                    "scenario": f"standalone_changeset_{count}",
                    "status": "FAIL",
                    "repetitions": len(samples),
                    "error": result.get("errors"),
                }
        replay = execute_changeset(changeset, root=root, apply=True)
        files = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
        return {
            "scenario": f"standalone_changeset_{count}",
            "status": "PASS",
            "repetitions": repeats,
            "warmup": 1,
            "p50_ms": statistics.median(samples),
            "p95_ms": sorted(samples)[max(0, int(len(samples) * 0.95) - 1)],
            "replay_status": replay.get("status"),
            "replayed": replay.get("replayed", False),
            "files": len(files),
            "first_transaction": first.get("transaction") if first else None,
        }


def _worktree_isolation_scenario() -> dict[str, Any]:
    """Exercise ten concurrent roots and verify each receives only its own edit."""

    def apply_one(index: int) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix=f"simplicio-422-worktree-{index}-") as raw_root:
            root = Path(raw_root)
            relative = f"files/worktree-{index:02d}.txt"
            value = f"isolated-{index}\n"
            changeset = {
                "schema": "simplicio.fast.changeset/v2",
                "changeset_id": f"issue-422-worktree-{index}",
                "correlation_id": f"issue-422-worktree-{index}",
                "generation": "generation-1",
                "allowlist": [relative],
                "operations": [{"kind": "create", "path": relative, "content": value}],
            }
            result = execute_changeset(changeset, root=root, apply=True)
            path = root / relative
            return {
                "status": result.get("status"),
                "content": path.read_text(encoding="utf-8") if path.is_file() else None,
                "root": str(root),
            }

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(apply_one, range(10)))
    passed = all(
        row["status"] == "ok" and row["content"] == f"isolated-{index}\n" for index, row in enumerate(results)
    )
    return {
        "scenario": "worktree_isolation_10",
        "status": "PASS" if passed and len({row["root"] for row in results}) == 10 else "FAIL",
        "worktrees": len(results),
        "unique_roots": len({row["root"] for row in results}),
        "scheduler_count": 1,
        "reason": None if passed else "one or more roots received an incorrect result",
    }


def _auto_without_runtime(root: Path) -> dict[str, Any]:
    profile = negotiate_execution_mode(
        "auto",
        root=root,
        runtime_handshake={"verified": False, "capabilities": [], "reason": "runtime-absent"},
    )
    return {
        "scenario": "auto_without_runtime",
        "status": "PASS" if profile.effective_mode == "standalone" else "FAIL",
        "effective_mode": profile.effective_mode,
        "reason_code": profile.reason_code,
    }


def _adversarial_generation_replay_scenario() -> dict[str, Any]:
    """Prove stale generation and conflicting replay fail before a second write."""

    with tempfile.TemporaryDirectory(prefix="simplicio-422-adversarial-") as raw_root:
        root = Path(raw_root)
        original = _changeset(1)
        stale = execute_changeset(original, root=root, apply=True, current_generation="generation-stale")
        first = execute_changeset(original, root=root, apply=True)
        conflicting = dict(original)
        conflicting["operations"] = [{"kind": "create", "path": "files/file-000.txt", "content": "changed\n"}]
        conflict = execute_changeset(conflicting, root=root, apply=True)
        target = root / "files" / "file-000.txt"
        stale_code = stale.get("errors", [{}])[0].get("code")
        conflict_code = conflict.get("errors", [{}])[0].get("code")
        passed = (
            stale.get("status") == "refused"
            and stale_code == "stale_generation"
            and first.get("status") == "ok"
            and conflict.get("status") == "refused"
            and conflict_code == "REPLAY_CONFLICT"
            and target.read_text(encoding="utf-8") == "value-0\n"
        )
        return {
            "scenario": "adversarial_generation_replay",
            "status": "PASS" if passed else "FAIL",
            "stale_generation": stale_code,
            "first_status": first.get("status"),
            "conflict_status": conflict_code,
            "final_content": target.read_text(encoding="utf-8") if target.is_file() else None,
            "reason": None if passed else "stale or conflicting replay did not fail closed",
        }


def _windows_locked_file_scenario() -> dict[str, Any]:
    """Exercise a real Windows sharing violation and verify rollback."""

    if os.name != "nt":
        return {
            "scenario": "windows_locked_file",
            "status": "UNAVAILABLE",
            "reason": "locked-file lane requires a real Windows host",
        }
    with tempfile.TemporaryDirectory(prefix="simplicio-422-locked-") as raw_root:
        root = Path(raw_root)
        target = root / "files" / "locked.txt"
        target.parent.mkdir(parents=True)
        target.write_text("before\n", encoding="utf-8")
        handle = target.open("r+b")
        try:
            changeset = {
                "schema": "simplicio.fast.changeset/v2",
                "changeset_id": "issue-422-locked-file",
                "correlation_id": "issue-422-locked-file",
                "generation": "generation-1",
                "allowlist": ["files/locked.txt"],
                "operations": [{"kind": "delete", "path": "files/locked.txt"}],
            }
            result = execute_changeset(changeset, root=root, apply=True)
            preserved = target.is_file() and target.read_text(encoding="utf-8") == "before\n"
            error_codes = [row.get("code") for row in result.get("errors", [])]
            passed = result.get("status") == "refused" and "COMMIT_PARTIAL" in error_codes and preserved
            return {
                "scenario": "windows_locked_file",
                "status": "PASS" if passed else "FAIL",
                "receipt_status": result.get("status"),
                "error_codes": error_codes,
                "preserved": preserved,
                "reason": None if passed else "locked-file failure did not preserve the original file",
            }
        finally:
            handle.close()


def _capability_scenario(name: str, available: bool, version: str | None) -> dict[str, Any]:
    return {
        "scenario": name,
        "status": "UNVERIFIED" if not available else "AVAILABLE_NOT_E2E",
        "version": version,
        "reason": "capability not installed; no synthetic replacement executed" if not available else None,
    }


def _runtime_mcp_tool(binary: str, name: str, arguments: dict[str, Any], *, cwd: Path) -> dict[str, Any]:
    """Call one Runtime-owned MCP tool over its real stdio server."""

    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "simplicio-dev-cli-422", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    ]
    process = subprocess.Popen(
        [binary, "serve", "--mcp", "--stdio"],
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    request = "".join(json.dumps(message, separators=(",", ":")) + "\n" for message in messages)
    try:
        stdout, stderr = process.communicate(request, timeout=60)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        tail_stdout, tail_stderr = process.communicate()
        stdout = (exc.stdout or "") + (tail_stdout or "")
        stderr = (exc.stderr or "") + (tail_stderr or "")
        raise RuntimeEffectError("runtime_mcp_timeout", "Runtime MCP authorization timed out") from exc
    responses: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            responses.append(value)
    response = next((value for value in responses if value.get("id") == 2), None)
    if response is None:
        detail = (stderr or stdout).strip()[-1000:]
        raise RuntimeEffectError(
            "runtime_mcp_no_response", f"Runtime MCP returned no tool response: {detail}"
        )
    if "error" in response:
        raise RuntimeEffectError("runtime_mcp_error", str(response["error"]))
    result = response.get("result")
    content = result.get("content") if isinstance(result, dict) else None
    text = content[0].get("text") if isinstance(content, list) and content else None
    if not isinstance(text, str):
        raise RuntimeEffectError(
            "runtime_mcp_malformed", "Runtime MCP authorization response has no text content"
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeEffectError(
            "runtime_mcp_malformed", "Runtime MCP authorization returned non-JSON text"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeEffectError("runtime_mcp_malformed", "Runtime MCP authorization returned a non-object")
    return payload


def _runtime_scenario() -> dict[str, Any]:
    """Exercise Runtime's real HTTP effect transport when explicitly configured.

    The Runtime server owns its repository root, so the runner requires callers
    to provide an isolated root that the server was started against.  This
    avoids claiming an E2E run against a different checkout or mutating the
    repository that launched the evidence runner.
    """
    probe_root = os.environ.get("SIMPLICIO_RUNTIME_E2E_ROOT", "").strip()
    if probe_root:
        os.environ.setdefault("SIMPLICIO_RUNTIME_PROBE_ROOT", probe_root)
    handshake = runtime_verify_contract(timeout=60)
    base = {
        "scenario": "runtime_backed",
        "version": handshake.get("version"),
        "binary": handshake.get("binary"),
        "capabilities": handshake.get("capabilities", []),
    }
    if handshake.get("verified") is not True:
        return {
            **base,
            "status": "UNVERIFIED",
            "reason": str(handshake.get("reason") or "runtime-contract-not-verified"),
        }
    base_url = os.environ.get("SIMPLICIO_RUNTIME_EFFECT_URL", "").strip()
    root_value = os.environ.get("SIMPLICIO_RUNTIME_E2E_ROOT", "").strip()
    if not base_url or not root_value:
        return {
            **base,
            "status": "AVAILABLE_NOT_E2E",
            "reason": (
                "runtime contract verified; set SIMPLICIO_RUNTIME_EFFECT_URL and SIMPLICIO_RUNTIME_E2E_ROOT"
            ),
        }
    root = Path(root_value).resolve()
    if not root.is_dir():
        return {
            **base,
            "status": "UNVERIFIED",
            "reason": "SIMPLICIO_RUNTIME_E2E_ROOT is not an existing directory",
        }
    run_id = f"issue-422-runtime-{os.getpid()}"
    artifact_dir = root / ".simplicio-loop" / "issue-422-runtime" / run_id
    target = artifact_dir / "result.txt"
    artifact = artifact_dir / "effect-plan.json"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    target.write_text("before\n", encoding="utf-8")
    artifact.write_text(
        json.dumps(
            {
                "schema": "simplicio.mechanical-edit/v1",
                "file": target.relative_to(root).as_posix(),
                "operations": [{"op": "append", "text": "runtime-e2e\n"}],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    effect = {"artifact_ref": artifact.relative_to(root).as_posix()}
    effect_digest = canonical_hash(effect)
    source = {"revision": run_id, "files": [target.relative_to(root).as_posix()]}
    context = {"task": "issue-422-runtime", "root": str(root)}
    lease_id = f"lease-{run_id}"
    issued_at = int(time.time())
    proposal = {
        "schema": "simplicio.change-proposal/v1",
        "proposal_id": f"proposal-{run_id}",
        "effect_id": run_id,
        "repo": str(root),
        "worktree": str(root),
        "branch": "e2e",
        "write_set": [target.relative_to(root).as_posix()],
        "capability": "simplicio_edit",
        "attempt_id": run_id,
        "lease_id": lease_id,
        "fencing_token": 1,
        "policy_revision": "issue-422-e2e",
        "issued_at": issued_at,
        "expires_at": issued_at + 300,
        "mode": "ask",
        "route": "runtime",
        "irreversible": False,
        "human_gate_receipt": "issue-422-local-gate",
        "source": source,
        "context": context,
        "source_digest": "sha256:" + canonical_hash(source),
        "context_digest": "sha256:" + canonical_hash(context),
        "plan_digest": "sha256:" + "f" * 64,
        "effect_digest": "sha256:" + effect_digest,
        "before_digest": "sha256:" + "0" * 64,
        "after_digest": "sha256:" + "1" * 64,
    }
    proposal["proposal_digest"] = "sha256:" + canonical_hash(proposal)
    binary_override = os.environ.get("SIMPLICIO_RUNTIME_BIN", "").strip()
    binary = binary_override or handshake.get("binary")
    if not isinstance(binary, str) or not binary:
        return {
            **base,
            "status": "UNVERIFIED",
            "reason": "Runtime binary path missing for durable authorization",
        }
    try:
        authorization = _runtime_mcp_tool(
            binary,
            "simplicio_effect_authorize",
            {"proposal": proposal, "repo": str(root)},
            cwd=root,
        )
    except (OSError, RuntimeEffectError) as exc:
        return {**base, "status": "UNVERIFIED", "reason": f"runtime-authorization-failed: {exc}"}
    if authorization.get("status") != "authorized":
        detail = authorization.get("reason") or "authorization denied"
        return {**base, "status": "UNVERIFIED", "reason": f"runtime-authorization-denied: {detail}"}
    causal = {
        "coordinator_kind": "issue-422-evidence",
        "coordinator_id": run_id,
        "session_id": run_id,
        "turn_id": "runtime",
        "attempt": "1",
        "subworkflow_id": run_id,
        "plan_id": run_id,
        "goal_id": "issue-422",
        "plan_node_id": "runtime-effect",
        "effect_id": run_id,
    }
    key = canonical_hash([causal, canonical_hash(effect), None])
    transaction = {
        "schema": "simplicio.effect-transaction/v1",
        "repo": str(root),
        "worktree": str(root),
        "branch": "e2e",
        "capability": "simplicio_edit",
        "context_digest": proposal["context_digest"],
        "plan_digest": proposal["plan_digest"],
        "policy_revision": "issue-422-e2e",
        "source": source,
        "context": context,
        "human_gate_receipt": "issue-422-local-gate",
        "idempotency_key": key,
        "effect_digest": effect_digest,
        "proposal_digest": proposal["proposal_digest"],
        "authorization_digest": authorization["authorization_digest"],
        "proposal": proposal,
        "authorization": authorization,
        "causal": causal,
        "effect": effect,
        "base_hash": proposal["before_digest"],
        "source_hash": proposal["source_digest"],
        "lease": {"id": lease_id, "fencing_token": 1},
        "preconditions": [{"kind": "isolated-root", "root": str(root)}],
        "write_set": [target.relative_to(root).as_posix()],
        "acceptance_criteria_refs": ["simplicio-dev-cli#422"],
    }
    try:
        transport = HttpRuntimeTransport(base_url, timeout_s=20.0)
        capabilities = transport.capabilities()
        schemas = capabilities.get("effect_transaction_schemas", [])
        if "simplicio.effect-transaction/v1" not in schemas:
            return {
                **base,
                "status": "UNVERIFIED",
                "reason": "Runtime capability response lacks effect transaction schema",
            }
        receipt = transport.submit(transaction)
        replay = transport.query(key)
    except (RuntimeEffectError, OSError, ValueError) as exc:
        return {**base, "status": "UNVERIFIED", "reason": f"runtime-effect-e2e-failed: {exc}"}
    content = target.read_text(encoding="utf-8")
    expected_content = "before\nruntime-e2e\n"
    if (
        receipt.get("state") != "completed"
        or replay.get("state") != "completed"
        or content != expected_content
    ):
        return {
            **base,
            "status": "FAIL",
            "reason": "Runtime receipt or materialized artifact did not match the submitted transaction",
            "receipt_state": receipt.get("state"),
            "replay_state": replay.get("state"),
            "content": content,
        }
    before_hash = _sha(b"before\n")
    after_hash = _sha(expected_content.encode("utf-8"))
    evidence = {
        "schema": "simplicio.effect-reconciliation-evidence/v1",
        "idempotency_key": key,
        "repo": str(root),
        "files": [
            {
                "path": target.relative_to(root).as_posix(),
                "before_sha256": before_hash,
                "after_sha256": after_hash,
            }
        ],
    }
    evidence["evidence_sha256"] = canonical_hash(evidence)
    evidence_file = artifact_dir / "reconciliation-evidence.json"
    evidence_file.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    firewall_transaction = {
        "schema": "simplicio.effect-transaction/v1",
        "executor": "simplicio-runtime",
        "request": {
            "schema": "simplicio.effect-request/v1",
            "capability": "simplicio_effect_reconcile",
            "identity": {
                "session": run_id,
                "turn": "runtime-reconcile",
                "tool_call": key,
                "attempt": "1",
                "transaction": key,
            },
            "authority": "issue-422-evidence",
            "policy_receipt": "issue-422-local-gate",
            "idempotency_key": key,
            "action_digest": "sha256:" + canonical_hash(evidence),
            "validation_plan": "runtime-file-hashes",
            "rollback_plan": "safe-boundary-only",
            "redaction_plan": "none",
            "write_set": [".simplicio-loop/ops/mcp-effects/hbp-inbox.bin"],
            "preconditions": ["isolated-root"],
            "lease": {"id": lease_id, "fence": 1},
            "deadline_ms": int(time.time() * 1000) + 300_000,
            "cancellation": "safe_boundary_only",
        },
    }
    try:
        reconciliation = _runtime_mcp_tool(
            binary,
            "simplicio_effect_reconcile",
            {
                "idempotency_key": key,
                "repo": str(root),
                "evidence_file": str(evidence_file),
                "transaction": transaction,
                "__runtime_effect_transaction": firewall_transaction,
            },
            cwd=root,
        )
    except (OSError, RuntimeEffectError) as exc:
        return {**base, "status": "UNVERIFIED", "reason": f"runtime-reconciliation-failed: {exc}"}
    if reconciliation.get("status") != "reconciled" or reconciliation.get("verdict") != "proven-after":
        return {
            **base,
            "status": "FAIL",
            "reason": "Runtime positive reconciliation did not return proven-after",
            "reconciliation": reconciliation,
        }
    return {
        **base,
        "status": "PASS",
        "transport": "http-json",
        "idempotency_key": key,
        "receipt_state": receipt.get("state"),
        "replay_state": replay.get("state"),
        "materialized": target.relative_to(root).as_posix(),
        "reconciliation_status": reconciliation.get("status"),
        "reconciliation_verdict": reconciliation.get("verdict"),
    }


def _mapper_producer_scenario() -> dict[str, Any]:
    """Run the installed Mapper producer and validate its terminal handoff."""
    binary = shutil.which("simplicio-mapper")
    if binary is None:
        return {
            "scenario": "mapper_producer",
            "status": "UNVERIFIED",
            "reason": "simplicio-mapper executable not found; no synthetic replacement executed",
        }
    with tempfile.TemporaryDirectory(prefix="simplicio-422-mapper-") as raw_root:
        worktree = Path(raw_root)
        source = worktree / "src"
        source.mkdir()
        (source / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        index = subprocess.run(
            [binary, "index", str(worktree), "--json"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            close_fds=True,
        )
        if index.returncode != 0:
            return {
                "scenario": "mapper_producer",
                "status": "FAIL",
                "reason": "mapper index failed",
                "returncode": index.returncode,
                "output_tail": (index.stdout + index.stderr)[-2000:],
            }
        handoff = subprocess.run(
            [binary, "handoff", str(worktree), "--goal", "verify app", "--json"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            close_fds=True,
        )
        try:
            payload = json.loads(handoff.stdout)
        except json.JSONDecodeError:
            payload = {}
        status = payload.get("status") if isinstance(payload, dict) else {}
        counts = status.get("counts") if isinstance(status, dict) else {}
        passed = (
            handoff.returncode == 0
            and isinstance(status, dict)
            and status.get("terminal") is True
            and status.get("fresh") is True
            and status.get("lock") is False
            and isinstance(counts, dict)
            and int(counts.get("files", 0)) >= 1
        )
        return {
            "scenario": "mapper_producer",
            "status": "PASS" if passed else "FAIL",
            "binary": binary,
            "index_returncode": index.returncode,
            "handoff_returncode": handoff.returncode,
            "terminal": status.get("terminal") if isinstance(status, dict) else None,
            "fresh": status.get("fresh") if isinstance(status, dict) else None,
            "lock": status.get("lock") if isinstance(status, dict) else None,
            "counts": counts,
            "reason": None if passed else "Mapper handoff was not a fresh terminal unlocked receipt",
        }


def run(root: Path, *, repeats: int = 10) -> dict[str, Any]:
    rows = [_auto_without_runtime(root)]
    rows.extend(_transaction_scenario(count, repeats) for count in (1, 20, 200))
    rows.append(_worktree_isolation_scenario())
    rows.append(_adversarial_generation_replay_scenario())
    rows.append(_windows_locked_file_scenario())
    mapper_version = _version("simplicio-mapper")
    mapper_row = _mapper_producer_scenario()
    mapper_row["version"] = mapper_version
    rows.append(mapper_row)
    runtime_row = _runtime_scenario()
    rows.append(runtime_row)
    statuses = {row["status"] for row in rows}
    overall = "FAIL" if "FAIL" in statuses else "PASS_WITH_UNVERIFIED" if "UNVERIFIED" in statuses else "PASS"
    return {
        "schema": SCHEMA,
        "commit_sha": _git_sha(root),
        "platform": platform.platform(),
        "python": sys.version,
        "filesystem": str(root.anchor),
        "configuration": {"repeats": repeats, "network": False, "root": str(root.resolve())},
        "components": {
            "dev_cli": _version("simplicio-dev-cli"),
            "mapper": _version("simplicio-mapper"),
            "runtime": runtime_row,
        },
        "scenarios": rows,
        "claims": {"performance_improvement": None, "reason": "no baseline comparison was run"},
        "overall": overall,
    }


def write_reports(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    json_path = output.with_suffix(".json")
    markdown_path = (
        output if output.suffix.lower() not in {".json", ".jsonl", ".csv"} else output.with_suffix(".md")
    )
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    jsonl = output.with_suffix(".jsonl")
    jsonl.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in payload["scenarios"]) + "\n",
        encoding="utf-8",
    )
    with output.with_suffix(".csv").open("w", newline="", encoding="utf-8") as handle:
        fields = sorted({key for row in payload["scenarios"] for key in row})
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(payload["scenarios"])
    lines = [
        "# Issue #422 local evidence",
        "",
        f"- schema: `{payload['schema']}`",
        f"- commit: `{payload['commit_sha']}`",
        f"- overall: `{payload['overall']}`",
        "",
        "| Scenario | Status | p50 ms | p95 ms | Reason |",
        "|---|---:|---:|---:|---|",
    ]
    for row in payload["scenarios"]:
        lines.append(
            f"| {row['scenario']} | {row['status']} | {row.get('p50_ms', '')} | "
            f"{row.get('p95_ms', '')} | {row.get('reason', '') or ''} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/issue-422-e2e.md"))
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args(argv)
    if args.repeats < 10:
        parser.error("--repeats must be at least 10")
    payload = run(args.root.resolve(), repeats=args.repeats)
    output = args.output if args.output.is_absolute() else args.root / args.output
    write_reports(payload, output)
    print(json.dumps({"schema": payload["schema"], "overall": payload["overall"], "output": str(output)}))
    return 0 if payload["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
