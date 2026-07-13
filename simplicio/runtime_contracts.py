"""Stable JSON contracts consumed by simplicio-runtime."""

from __future__ import annotations

import json
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
    "simplicio.dev-cli.patch-receipt/v1",
    "simplicio.dev-cli.evidence-ledger/v1",
    "simplicio.dev-cli.task-batch/v1",
    "simplicio.prompt-envelope/v1",
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


def runtime_verify_contract(*, timeout: int = 30) -> dict[str, Any]:
    """Probe the real reserved runtime without silently falling back."""
    binary = shutil.which(RUNTIME_COMMAND)
    base = {
        "schema": "simplicio.dev-cli.runtime-verify/v1",
        "expected_product": RUNTIME_PRODUCT,
        "binary": binary,
    }
    if binary is None:
        return {**base, "verified": False, "reason": "runtime-binary-not-found", "capabilities": []}
    try:
        completed = subprocess.run(
            [binary, "runtime", "smoke", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**base, "verified": False, "reason": f"runtime-probe-failed: {exc}", "capabilities": []}
    try:
        response = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        response = {}
    product = str(response.get("runtime", ""))
    names = sorted(
        str(check.get("name", ""))
        for check in response.get("checks", [])
        if isinstance(check, dict) and check.get("name")
    )
    missing = sorted(cap for cap in RUNTIME_CAPABILITIES if not any(cap in name for name in names))
    if product != RUNTIME_PRODUCT:
        reason = "wrong-runtime-product"
    elif response.get("status") != "passed":
        reason = "runtime-status-failed"
    elif missing:
        reason = "capability-handshake-missing"
    elif completed.returncode != 0:
        reason = "runtime-probe-nonzero"
    else:
        reason = "ok"
    return {
        **base,
        "verified": reason == "ok",
        "reason": reason,
        "product": product or None,
        "capabilities": names,
        "missing_capabilities": missing,
        "legacy_alias": is_legacy_runtime_alias(product),
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
    return {
        "schema": "simplicio.dev-cli.smoke/v1",
        "root": str(Path(root)),
        "provider": provider,
        "reply": reply.strip()[:500],
        "ok": "OK simplicio connected." in reply,
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
