#!/usr/bin/env python3
"""Create the deterministic corpus and runner used by Mapper perf evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any

CORPUS_SCHEMA = "simplicio.mapper-perf-corpus/v1"
CORPUS_SIZES = {"tiny": 54, "small": 440, "medium": 1814, "xlarge": 7800}


def corpus_manifest(size: str) -> dict[str, Any]:
    if size not in CORPUS_SIZES:
        raise ValueError(f"unknown corpus size: {size}")
    return {
        "schema": CORPUS_SCHEMA,
        "size": size,
        "files": CORPUS_SIZES[size],
        "generator": "mapper_perf_corpus/v1",
        "language_mix": {"python": 0.75, "javascript": 0.15, "json": 0.10},
    }


def _file_text(index: int, language: str) -> str:
    if language == "python":
        return (
            f'"""Deterministic Mapper perf fixture {index}."""\n\n'
            f"from pathlib import Path\n\n\n"
            f"def function_{index}(value: int) -> int:\n"
            f"    return value + {index}\n"
        )
    if language == "javascript":
        return (
            f"import {{ helper_{index} }} from './helper_{index}.js';\n\n"
            f"export function module_{index}(value) {{\n"
            f"  return helper_{index}(value) + {index};\n"
            f"}}\n"
        )
    return json.dumps({"index": index, "kind": "mapper-perf-fixture", "value": index}, sort_keys=True) + "\n"


def materialize(root: str | Path, size: str) -> dict[str, Any]:
    destination = Path(root).resolve()
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    count = CORPUS_SIZES[size]
    for index in range(count):
        if index % 20 == 0:
            language = "json"
        elif index % 7 == 0:
            language = "javascript"
        else:
            language = "python"
        extension = {"python": "py", "javascript": "js", "json": "json"}[language]
        path = destination / "packages" / f"pkg_{index % 40:02d}" / f"module_{index:05d}.{extension}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_file_text(index, language), encoding="utf-8", newline="\n")
    manifest = corpus_manifest(size)
    manifest["root"] = str(destination)
    manifest["content_sha256"] = content_digest(destination)
    (destination / "corpus-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def content_digest(root: str | Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        if path.is_file() and path.name != "corpus-manifest.json":
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def run(root: str | Path, size: str, samples: int) -> dict[str, Any]:
    if samples <= 0:
        raise ValueError("samples must be positive")
    destination = Path(root).resolve()
    if not (destination / "corpus-manifest.json").exists():
        materialize(destination, size)
    samples_out: list[dict[str, Any]] = []
    for sample in range(samples):
        started = time.perf_counter()
        from simplicio_mapper.mapper.emit import build_artifacts

        build_artifacts(str(destination), output_dir=".simplicio")
        samples_out.append({"sample": sample + 1, "wall_ms": (time.perf_counter() - started) * 1000})
    return {
        "schema": "simplicio.mapper-perf-run/v1",
        "corpus": corpus_manifest(size),
        "fingerprint": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "commit": _git_commit(destination),
        },
        "samples": samples_out,
    }


def _git_commit(root: Path) -> str | None:
    try:
        import subprocess

        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--size", choices=sorted(CORPUS_SIZES), required=True)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--materialize", action="store_true")
    args = parser.parse_args(argv)
    payload = materialize(args.root, args.size) if args.materialize else run(args.root, args.size, args.samples)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
