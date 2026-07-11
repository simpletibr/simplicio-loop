"""Stable JSON contracts consumed by simplicio-runtime."""

from __future__ import annotations

import shutil
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
                "reject_products": ["simplicio-agent", "hermes"],
                "diagnostic": (
                    "Expected Simplicio Runtime on `simplicio`; if PATH resolves to "
                    "Agent/Desktop, use `simplicio-agent` for that binary and point "
                    "runtime consumers at the Rust runtime explicitly."
                ),
            },
        },
        "dependencies": {"simplicio-mapper": mapper},
    }


def doctor_contract(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    tools = {
        name: _tool_status(name)
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


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
