"""Governed LiteRT workflow surface (#357).

Dev CLI diagnoses and plans; Runtime owns execution. Destructive actions require
an explicit plan and never overwrite source artifacts.
"""

from __future__ import annotations

import json
import platform
import shutil
import sys
from pathlib import Path
from typing import Any


class LiteRTError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def doctor(*, runtime_adapter_present: bool = False) -> dict[str, Any]:
    """Report LiteRT-related capabilities without claiming unsupported platforms."""
    which = shutil.which("litert") or shutil.which("tflite_runtime")
    return {
        "schema": "simplicio.litert-doctor/v1",
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
        },
        "cli_found": which is not None,
        "cli_path": which,
        "runtime_adapter_present": runtime_adapter_present,
        "preview": True,
        "capabilities": {
            "doctor": True,
            "convert": True,
            "quantize": True,
            "compile": True,
            "benchmark": True,
            "download": False,
            "delete": False,
        },
        "notes": [
            "LiteRT upstream tooling may be preview; receipts mark preview=true.",
            "Destructive download/clean/delete require explicit policy outside this surface.",
        ],
    }


def _artifact_plan(
    action: str,
    source: str | Path,
    *,
    out_dir: str | Path,
    confirm: bool,
) -> dict[str, Any]:
    if action not in {"convert", "quantize", "compile", "benchmark"}:
        raise LiteRTError("UNSUPPORTED_ACTION", action)
    src = Path(source)
    if not src.exists():
        raise LiteRTError("SOURCE_MISSING", str(src))
    if src.is_symlink():
        raise LiteRTError("SYMLINK_BLOCKED", str(src))
    destination_root = Path(out_dir)
    if destination_root.resolve() == src.resolve():
        raise LiteRTError("OVERWRITE_FORBIDDEN", "out_dir equals source")
    if not confirm:
        raise LiteRTError("CONFIRMATION_REQUIRED", action)
    destination_root.mkdir(parents=True, exist_ok=True)
    output = destination_root / f"{src.stem}.{action}.artifact"
    if output.exists():
        raise LiteRTError("ARTIFACT_EXISTS", str(output))
    # Plan only — Runtime performs the actual conversion.
    plan = {
        "schema": "simplicio.litert-plan/v1",
        "action": action,
        "source": str(src),
        "output": str(output),
        "overwrite_source": False,
        "preview": True,
        "status": "planned",
        "requires_runtime": True,
    }
    receipt_path = destination_root / f"{src.stem}.{action}.plan.json"
    receipt_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    plan["plan_path"] = str(receipt_path)
    return plan


def convert(source: str | Path, *, out_dir: str | Path, confirm: bool = False) -> dict[str, Any]:
    return _artifact_plan("convert", source, out_dir=out_dir, confirm=confirm)


def quantize(source: str | Path, *, out_dir: str | Path, confirm: bool = False) -> dict[str, Any]:
    return _artifact_plan("quantize", source, out_dir=out_dir, confirm=confirm)


def compile(source: str | Path, *, out_dir: str | Path, confirm: bool = False) -> dict[str, Any]:
    return _artifact_plan("compile", source, out_dir=out_dir, confirm=confirm)


def benchmark(source: str | Path, *, out_dir: str | Path, confirm: bool = False) -> dict[str, Any]:
    return _artifact_plan("benchmark", source, out_dir=out_dir, confirm=confirm)
