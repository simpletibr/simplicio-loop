"""Keep the kit's phase icons in lockstep with the CLI's ``PHASE_META`` (issue #1399).

The browser cannot import Python, so ``static/components/phase-meta.js`` is generated from
``simplicio_loop.progress.PHASE_META``/``PHASES`` and committed.  ``--check`` fails when the
committed module drifts from the CLI; without arguments it rewrites the module.

    python -m simplicio_loop.dashboard.phase_meta          # regenerate
    python -m simplicio_loop.dashboard.phase_meta --check  # exit 1 on drift
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from simplicio_loop.dashboard import COMPONENTS_DIR
from simplicio_loop.progress import PHASE_META, PHASES

MODULE_PATH = COMPONENTS_DIR / "phase-meta.js"


def render_module() -> str:
    """Return the ES module source for the current ``PHASE_META``."""
    meta = {phase: {"icon": icon, "label": label} for phase, (icon, label) in PHASE_META.items()}
    return (
        "// Generated from simplicio_loop/progress.py PHASE_META by\n"
        "// `python -m simplicio_loop.dashboard.phase_meta`. Do not edit by hand.\n"
        f"export const PHASES = Object.freeze({json.dumps(list(PHASES), ensure_ascii=False)});\n"
        f"export const PHASE_META = Object.freeze({json.dumps(meta, ensure_ascii=False, indent=2)});\n"
        "export function phaseMeta(phase) {\n"
        "  const key = String(phase ?? \"\");\n"
        "  return PHASE_META[key] ?? { icon: \"•\", label: key.replace(/_/g, \" \").replace(/^./, (c) => c.toUpperCase()) };\n"
        "}\n"
    )


def sync(path: Path = MODULE_PATH, *, check: bool = False) -> bool:
    """Write (or with ``check`` only compare) the module; return True when it is current."""
    expected = render_module()
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == expected:
        return True
    if not check:
        path.write_text(expected, encoding="utf-8", newline="\n")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m simplicio_loop.dashboard.phase_meta",
        description="Generate static/components/phase-meta.js from progress.PHASE_META.",
    )
    parser.add_argument("--check", action="store_true", help="exit 1 if phase-meta.js is stale; write nothing")
    args = parser.parse_args(argv)
    current = sync(check=args.check)
    if args.check and not current:
        print(f"stale: {MODULE_PATH} (run python -m simplicio_loop.dashboard.phase_meta)", file=sys.stderr)
        return 1
    print(f"{'current' if current else 'written'}: {MODULE_PATH}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
