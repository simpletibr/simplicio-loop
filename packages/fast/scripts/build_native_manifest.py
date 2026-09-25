"""Generate the deterministic manifest consumed by native_backend.py."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ABI = "simplicio.fast-native/v1"
SUPPORTED = {"linux-x86_64", "linux-aarch64", "macos-aarch64", "windows-x86_64"}


def build_manifest(
    binary: Path, *, platform: str, version: str, source_commit: str, toolchain: str
) -> dict[str, object]:
    if platform not in SUPPORTED:
        raise ValueError(f"unsupported platform: {platform}")
    content = binary.read_bytes()
    return {
        "abi": ABI,
        "platform": platform,
        "filename": binary.name,
        "version": version,
        "source_commit": source_commit,
        "toolchain": toolchain,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_manifest(
        args.binary,
        platform=args.platform,
        version=args.version,
        source_commit=args.source_commit,
        toolchain=args.toolchain,
    )
    args.output.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
