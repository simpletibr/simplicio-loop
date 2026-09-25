#!/usr/bin/env python3
"""Regenerate ``simplicio/data/capabilities.json`` from the live argparse surface.

Run after any change to ``simplicio/cli.py`` that adds/removes/renames a
command or flag. ``tests/python/test_capabilities_manifest.py`` fails if the
packaged file drifts from what this script would produce, so drift cannot
silently ship.

Usage:
    python3 scripts/gen_capabilities_manifest.py           # write the file
    python3 scripts/gen_capabilities_manifest.py --check   # exit 1 if stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simplicio.capabilities_introspect import build_capabilities_manifest  # noqa: E402
from simplicio.cli import _build_parser  # noqa: E402

OUT_PATH = ROOT / "simplicio" / "data" / "capabilities.json"


def _package_version() -> str:
    from importlib import metadata

    try:
        return metadata.version("simplicio-cli")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def generate() -> dict:
    parser = _build_parser()
    return build_capabilities_manifest(
        parser,
        package_name="simplicio-cli",
        package_version=_package_version(),
        adapter_command="simplicio-dev-cli",
        python_adapter_command="simplicio-py",
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    check_only = "--check" in args
    manifest = generate()
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.is_file() else None
    if check_only:
        if current != rendered:
            print(f"stale: {OUT_PATH} does not match the live argparse surface", file=sys.stderr)
            return 1
        print(f"ok: {OUT_PATH} matches the live argparse surface")
        return 0
    OUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
