"""Stable JSON contracts consumed by simplicio-runtime."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

from . import __version__
from .providers import LOCAL_DEFAULT_MODEL
from .task_spec import TASK_SPEC_COMPATIBILITY

DEV_CLI_PACKAGE = "simplicio-cli"
PRIMARY_ADAPTER_COMMAND = "simplicio-dev-cli"
PYTHON_ADAPTER_COMMAND = "simplicio-py"
RUNTIME_COMMAND = "simplicio"
RUNTIME_PRODUCT = "simplicio-runtime"
DEV_CLI_PRODUCT = "simplicio-dev-cli"
EFFECT_TRANSACTION_CAPABILITY = "simplicio.effect-transaction/v1"

# Issue #167 (ecosystem rebrand): products that used to occupy the
# `simplicio` runtime command slot before the Hermes -> Simplicio Runtime
# rename. `version_contract()` publishes this list so a runtime consumer can
# reject a stale binary; `runtime_verify_contract()` reuses the same list to
# flag when the probed binary specifically resolves to one of these known
# legacy aliases (as opposed to some other unrelated/unknown product).
LEGACY_RUNTIME_ALIASES = ["simplicio-agent", "hermes"]

RUNTIME_CAPABILITIES = [
    "simplicio.task-spec/v2",
    "simplicio.execution-contract/v1",
    "simplicio.orientation-plan/v1",
    "simplicio.transaction/v1",
    EFFECT_TRANSACTION_CAPABILITY,
    "simplicio.dev-cli.patch-receipt/v1",
    "simplicio.dev-cli.evidence-ledger/v1",
    "simplicio.dev-cli.task-batch/v1",
    "simplicio.prompt-envelope/v1",
    "simplicio.plan-dag/v1",
    "simplicio.plan-projection/v1",
]

RUNTIME_VERIFY_CAPABILITIES = [
    EFFECT_TRANSACTION_CAPABILITY,
    "simplicio.compatibility-matrix/v1",
    "simplicio.context-pack/v1",
    "simplicio.mechanical-edit/v1",
    "simplicio.mechanical-edit-result/v1",
    "simplicio.artifact-response/v1",
    "simplicio.workflow-ledger/v1",
]

AGENT_FIRST_BOUNDARY_FORBIDDEN_FIELDS = [
    "memory",
    "memory_id",
    "memory_ref",
    "next_action",
    "provider",
    "provider_choice",
    "provider_config",
    "provider_selection",
    "tool_choice",
    "tool_choices",
    "tool_selection",
    "transcript",
    "transcript_ref",
    "transcript_sha256",
]


def validate_version_contract(payload: dict[str, Any]) -> list[str]:
    """Return actionable diagnostics for a malformed/incompatible handshake."""
    problems: list[str] = []
    if payload.get("schema") != "simplicio.dev-cli.version/v1":
        problems.append("version contract schema must be simplicio.dev-cli.version/v1")
    identity = payload.get("identity")
    if not isinstance(identity, dict) or identity.get("product") != DEV_CLI_PRODUCT:
        problems.append(f"expected product {DEV_CLI_PRODUCT!r}, not an agent/runtime binary")
    entrypoints = payload.get("entrypoints")
    if not isinstance(entrypoints, dict) or entrypoints.get("reserved_runtime") != RUNTIME_COMMAND:
        problems.append(f"runtime command must remain reserved as {RUNTIME_COMMAND!r}")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        problems.append("capabilities must be a JSON list")
    else:
        missing = sorted(set(RUNTIME_CAPABILITIES) - set(capabilities))
        if missing:
            problems.append(f"missing capabilities: {', '.join(missing)}")
    return problems


def agent_first_boundary_contract() -> dict[str, Any]:
    """Machine-readable ownership boundary for Runtime issue #3134.

    This is intentionally narrow and additive: it does not attempt to solve
    integration maturity (#3136), retention/erasure (#3137), quantum
    scheduling (#3138), or crypto-agility (#3139). It only publishes the
    agent-first ownership split the current cross-repo contracts already
    imply, so runtime consumers can assert that dev-cli handoff payloads stay
    effect-focused and never smuggle Agent-owned control-plane state.
    """

    return {
        "schema": "simplicio.agent-first-boundary/v1",
        "issues": {
            "runtime_epic": "simplicio-runtime#3134",
            "contracts_parent": "simplicio-runtime#3135",
            "dev_cli_plan_compiler": "simplicio-dev-cli#166",
        },
        "owners": {
            "simplicio-agent": {
                "role": "session_driver",
                "owns": [
                    "transcript",
                    "memory",
                    "provider_selection",
                    "tool_choice",
                    "next_action",
                ],
            },
            "simplicio-dev-cli": {
                "role": "effect_free_plan_compiler",
                "owns": [
                    "goal_envelope",
                    "plan_dag",
                    "effect_plan",
                    "verification_plan",
                ],
                "must_not_apply_effects": True,
            },
            "simplicio-runtime": {
                "role": "deterministic_coprocessor",
                "owns": [
                    "gate_decision",
                    "mechanical_edit",
                    "validation",
                    "effect_receipt",
                ],
                "must_not_own": [
                    "transcript",
                    "memory",
                    "provider_selection",
                    "tool_choice",
                    "next_action",
                ],
            },
        },
        "runtime_handoff_forbidden_fields": list(AGENT_FIRST_BOUNDARY_FORBIDDEN_FIELDS),
        "evidence": {
            "dev_cli_integrated_mode": "compile plan -> hand EffectPlan to sink -> never write directly",
            "runtime_handoff_scope": "PlanDAG/EffectPlan/VerificationPlan payloads stay effect-focused",
        },
    }


def version_contract() -> dict[str, Any]:
    """Return the canonical dev-cli identity and capability handshake."""
    try:
        from .mapper_api import mapper_version

        mapper = mapper_version()
    except Exception:
        mapper = None
    return {
        "schema": "simplicio.dev-cli.version/v1",
        "package": {"name": DEV_CLI_PACKAGE, "version": __version__},
        "identity": {
            "product": DEV_CLI_PRODUCT,
            "role": "adapter",
            "family": "simplicio",
            "canonical_entrypoint": PRIMARY_ADAPTER_COMMAND,
        },
        "entrypoints": {
            "adapter": PRIMARY_ADAPTER_COMMAND,
            "python_adapter": PYTHON_ADAPTER_COMMAND,
            "reserved_runtime": RUNTIME_COMMAND,
        },
        "capabilities": RUNTIME_CAPABILITIES,
        "compatibility": {
            "task_spec": TASK_SPEC_COMPATIBILITY,
            "runtime": {
                "product": RUNTIME_PRODUCT,
                "reserved_command": RUNTIME_COMMAND,
                "reject_products": LEGACY_RUNTIME_ALIASES,
                "diagnostic": (
                    "Expected Simplicio Runtime on `simplicio`; if PATH resolves to "
                    "Agent/Desktop, use `simplicio-agent` for that binary and point "
                    "runtime consumers at the Rust runtime explicitly."
                ),
            },
        },
        "ownership_boundary": agent_first_boundary_contract(),
        "dependencies": {"simplicio-mapper": mapper},
    }


def is_legacy_runtime_alias(product: str | None) -> bool:
    """True when *product* is a known pre-rebrand alias (issue #167).

    Reuses the same :data:`LEGACY_RUNTIME_ALIASES` list `version_contract()`
    publishes as ``reject_products`` — this does not invent new detection
    logic, it just names the existing check so callers (e.g. `simplicio-py
    runtime verify`) can decide whether to surface a compat warning.
    """
    if not product:
        return False
    return product.strip().lower() in LEGACY_RUNTIME_ALIASES


def runtime_verify_contract(*, timeout: int | None = None) -> dict[str, Any]:
    """Probe the real reserved runtime without silently falling back.

    Identity comes from the runtime's canonical ``version --json`` surface
    (#113). Runtime-side contract capabilities come from
    ``contracts smoke --json`` because that fast smoke publishes the schema
    chain the runtime actually exposes/consumes; ``runtime smoke`` is broader
    and heavier and its ``checks[]`` names are not the handshake surface.
    """
    binary = shutil.which(RUNTIME_COMMAND)
    base = {
        "schema": "simplicio.dev-cli.runtime-verify/v1",
        "expected_product": RUNTIME_PRODUCT,
        "binary": binary,
    }
    if os.environ.get("SIMPLICIO_RUNTIME_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return {
            **base,
            "binary": "offline-local",
            "verified": True,
            "reason": "offline-local",
            "version": "1.0.0",
            "transport": "offline-local",
            "capabilities": [EFFECT_TRANSACTION_CAPABILITY],
        }
    if binary is None:
        return {**base, "verified": False, "reason": "runtime-binary-not-found", "capabilities": []}
    probe_root = os.environ.get("SIMPLICIO_RUNTIME_PROBE_ROOT", "").strip()
    probe_cwd = Path(probe_root).resolve() if probe_root else None
    if probe_cwd is not None and not probe_cwd.is_dir():
        probe_cwd = None
    probe_kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
    }
    if probe_cwd is not None:
        probe_kwargs["cwd"] = str(probe_cwd)
    try:
        version_completed = subprocess.run(
            [binary, "version", "--json"],
            **probe_kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            **base,
            "verified": False,
            "reason": f"runtime-version-probe-failed: {exc}",
            "capabilities": [],
        }
    try:
        version_response = json.loads(version_completed.stdout or "{}")
    except json.JSONDecodeError:
        version_response = {}

    runtime_block = version_response.get("runtime")
    if isinstance(runtime_block, dict):
        product = str(runtime_block.get("name") or runtime_block.get("product") or "")
        version = runtime_block.get("version")
    else:
        product = str(version_response.get("runtime") or version_response.get("product") or "")
        version = version_response.get("version")

    if product != RUNTIME_PRODUCT:
        reason = "wrong-runtime-product"
        return {
            **base,
            "verified": False,
            "reason": reason,
            "product": product or None,
            "version": version,
            "capabilities": [],
            "missing_capabilities": [],
            "legacy_alias": is_legacy_runtime_alias(product),
        }

    try:
        contracts_completed = subprocess.run(
            [binary, "contracts", "smoke", "--json"],
            **probe_kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            **base,
            "verified": False,
            "reason": f"runtime-contracts-probe-failed: {exc}",
            "product": product or None,
            "version": version,
            "capabilities": [],
            "missing_capabilities": RUNTIME_VERIFY_CAPABILITIES,
            "legacy_alias": False,
        }

    try:
        contracts_response = json.loads(contracts_completed.stdout or "{}")
    except json.JSONDecodeError:
        contracts_response = {}

    names = sorted(
        {
            str(value)
            for value in (contracts_response.get("schemas") or {}).values()
            if isinstance(value, str) and value
        }
        | {
            str(contracts_response.get("standard_io"))
            if isinstance(contracts_response.get("standard_io"), str)
            else ""
        }
        | {
            str((contracts_response.get("compatibility") or {}).get("schema"))
            if isinstance(contracts_response.get("compatibility"), dict)
            and isinstance((contracts_response.get("compatibility") or {}).get("schema"), str)
            else ""
        }
        - {""}
    )
    checks = [check for check in contracts_response.get("checks", []) if isinstance(check, dict)]
    failed_checks = sorted(
        str(check.get("name")) for check in checks if check.get("passed") is False and check.get("name")
    )
    blocking_checks = sorted(
        str(check.get("name"))
        for check in checks
        if check.get("passed") is False
        and check.get("name")
        and check.get("required") is True
        and check.get("not_applicable") is not True
    )
    missing = sorted(cap for cap in RUNTIME_VERIFY_CAPABILITIES if cap not in names)
    if contracts_response.get("runtime") != RUNTIME_PRODUCT:
        reason = "wrong-runtime-product"
    elif blocking_checks:
        reason = "runtime-contracts-status-failed"
    elif missing:
        reason = "capability-handshake-missing"
    elif contracts_completed.returncode != 0 and (blocking_checks or missing or not names):
        reason = "runtime-contracts-probe-nonzero"
    else:
        reason = "ok"
    return {
        **base,
        "verified": reason == "ok",
        "reason": reason,
        "product": product or None,
        "version": version,
        "capabilities": names,
        "missing_capabilities": missing,
        "failed_checks": failed_checks,
        "blocking_checks": blocking_checks,
        "legacy_alias": False,
    }


def doctor_contract(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    tools = {
        name: (
            _tool_status_any("simplicio-prompt", "simplicio-subagents")
            if name == "simplicio-prompt"
            else _tool_status_any("simplicio-sprint", "sendsprint")
            if name == "simplicio-sprint"
            else _tool_status(name)
        )
        for name in (
            "simplicio-mapper",
            PRIMARY_ADAPTER_COMMAND,
            PYTHON_ADAPTER_COMMAND,
            "simplicio-prompt",
            "simplicio-sprint",
            "llama-server",
        )
    }
    packages = {
        name: {"version": _installed_or_local_package_version(name)}
        for name in (
            DEV_CLI_PACKAGE,
            "simplicio-mapper",
            "simplicio-prompt",
            "simplicio-sprint",
        )
    }
    return {
        "schema": "simplicio.dev-cli.doctor/v1",
        "root": str(root_path),
        "package": {
            "name": DEV_CLI_PACKAGE,
            "version": packages[DEV_CLI_PACKAGE]["version"],
        },
        "identity": {
            "product": DEV_CLI_PRODUCT,
            "role": "adapter",
            "family": "simplicio",
            "canonical_entrypoint": PRIMARY_ADAPTER_COMMAND,
        },
        "entrypoints": {
            "adapter": PRIMARY_ADAPTER_COMMAND,
            "python_adapter": PYTHON_ADAPTER_COMMAND,
            "reserved_runtime": RUNTIME_COMMAND,
        },
        "tools": tools,
        "packages": packages,
        "runtime": {
            "local_first": True,
            "model": LOCAL_DEFAULT_MODEL,
            "llama_cpp": tools["llama-server"]["available"],
        },
    }


def task_contract(task_result: dict[str, Any], *, root: str | Path = ".") -> dict[str, Any]:
    """Wrap a task result into a stable runtime contract.

    Issue #93: the contract now carries an optional ``impact`` block
    (``callers``, ``tests_run``, ``result``, ``status``) so downstream
    consumers — CI, PR templates, ``runs.jsonl`` — have verifiable evidence
    that the change's blast-radius was checked.
    Issue #118: the contract also carries the primary verification receipt so
    downstream consumers can reason about the test command, exit code, and
    digest without scraping the transaction journal.
    """
    payload = {
        "schema": "simplicio.dev-cli.task/v1",
        "root": str(Path(root)),
        "applied": bool(task_result.get("applied")),
        "files_changed": task_result.get("files_changed", []),
        "warnings": task_result.get("warnings", []),
        "task": task_result,
    }
    impact = task_result.get("impact")
    if impact is not None:
        payload["impact"] = {
            "callers": impact.get("callers", []),
            "tests_run": impact.get("tests_run", []),
            "result": impact.get("result", "unverified"),
            "status": impact.get("status", "unverified"),
        }
    prompt_envelope = task_result.get("prompt_envelope")
    if prompt_envelope is not None:
        payload["prompt_envelope"] = prompt_envelope
    verify = task_result.get("verify")
    if verify is not None:
        payload["verify"] = verify
    return payload


def smoke_contract(*, provider: str, reply: str, root: str | Path = ".") -> dict[str, Any]:
    deterministic_only = "provider=disabled" in provider and "LLM execution disabled" in reply
    return {
        "schema": "simplicio.dev-cli.smoke/v1",
        "root": str(Path(root)),
        "provider": provider,
        "reply": reply.strip()[:500],
        "ok": deterministic_only or "OK simplicio connected." in reply,
    }


def run_contract(run_result: dict[str, Any], *, root: str | Path = ".") -> dict[str, Any]:
    return {
        "schema": "simplicio.dev-cli.run/v1",
        "root": str(Path(root)),
        "scope": run_result.get("scope"),
        "applied": bool(run_result.get("applied")),
        "result": run_result,
    }


def _installed_or_local_package_version(name: str) -> str | None:
    version = _package_version(name)
    if version is not None:
        return version
    if name == DEV_CLI_PACKAGE:
        return __version__
    return None


def _tool_status(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {"available": path is not None, "path": path}


def _tool_status_any(*names: str) -> dict[str, Any]:
    for name in names:
        path = shutil.which(name)
        if path is not None:
            return {"available": True, "path": path, "resolved_command": name}
    return {"available": False, "path": None, "resolved_command": None}


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
