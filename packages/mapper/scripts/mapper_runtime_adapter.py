#!/usr/bin/env python3
"""Transport helpers for the effect-free Rust Runtime Mapper adapter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

REQUEST_SCHEMA = "simplicio.mapper-core-request/v1"
RESULT_SCHEMA = "simplicio.mapper-core-result/v1"
CONTRACT_VERSION = "v1"


def build_request(
    capability: str,
    language: str,
    sources: list[tuple[str, str]],
) -> dict[str, Any]:
    """Build the exact source-generation boundary consumed by Runtime."""
    return {
        "schema": REQUEST_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "capability": capability,
        "language": language,
        "source_generation": [
            {"path": path, "content": content}
            for path, content in sorted(sources, key=lambda item: item[0])
        ],
    }


def normalize_result(value: Any) -> dict[str, Any]:
    """Drop implementation metadata before differential semantic comparison."""
    if not isinstance(value, dict):
        raise ValueError("runtime adapter result must be an object")
    if value.get("schema") != RESULT_SCHEMA:
        raise ValueError("runtime adapter result schema is unsupported")
    if value.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("runtime adapter result contract version is unsupported")
    required = ("capability", "language", "coverage", "artifact")
    if any(key not in value for key in required):
        raise ValueError("runtime adapter result is incomplete")
    return {
        "schema": value["schema"],
        "contract_version": value["contract_version"],
        "capability": value["capability"],
        "language": value["language"],
        "coverage": value["coverage"],
        "artifact": value["artifact"],
    }


def run_binary(
    executable: Path,
    request: dict[str, Any],
    root: Path,
    *,
    runner=subprocess.run,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the Runtime adapter once; errors are unsupported, never fallback."""
    try:
        completed = runner(
            [str(executable)],
            cwd=str(root),
            input=json.dumps(request, ensure_ascii=False, separators=(",", ":")),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"runtime_adapter_execution_failed:{error}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return None, f"runtime_adapter_nonzero_exit:{completed.returncode}:{detail}"
    try:
        return normalize_result(json.loads(completed.stdout)), None
    except (ValueError, json.JSONDecodeError) as error:
        return None, f"runtime_adapter_invalid_result:{error}"
