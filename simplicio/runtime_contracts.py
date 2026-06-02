"""Stable JSON contracts consumed by simplicio-runtime."""

from __future__ import annotations

import shutil
from importlib import metadata
from pathlib import Path
from typing import Any

from . import __version__
from .providers import LOCAL_DEFAULT_MODEL


def doctor_contract(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    tools = {
        name: _tool_status(name)
        for name in (
            "simplicio-mapper",
            "simplicio-dev-cli",
            "simplicio",
            "simplicio-prompt",
            "simplicio-sprint",
            "llama-server",
        )
    }
    packages = {
        name: {"version": __version__ if name == "simplicio-cli" else _package_version(name)}
        for name in (
            "simplicio-cli",
            "simplicio-mapper",
            "simplicio-prompt",
            "simplicio-sprint",
        )
    }
    return {
        "schema": "simplicio.dev-cli.doctor/v1",
        "root": str(root_path),
        "package": {"name": "simplicio-cli", "version": __version__},
        "tools": tools,
        "packages": packages,
        "runtime": {
            "local_first": True,
            "model": LOCAL_DEFAULT_MODEL,
            "llama_cpp": tools["llama-server"]["available"],
        },
    }


def task_contract(task_result: dict[str, Any], *, root: str | Path = ".") -> dict[str, Any]:
    return {
        "schema": "simplicio.dev-cli.task/v1",
        "root": str(Path(root)),
        "applied": bool(task_result.get("applied")),
        "files_changed": task_result.get("files_changed", []),
        "warnings": task_result.get("warnings", []),
        "task": task_result,
    }


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


def _tool_status(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {"available": path is not None, "path": path}


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
