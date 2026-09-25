#!/usr/bin/env python3
"""Differential shadow harness for Python and the shared Rust Mapper core."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from simplicio_mapper import _native  # noqa: E402
from simplicio_mapper.mapper.parse import (  # noqa: E402
    _parse_imports,
    _sha256,
)

try:
    from scripts.mapper_runtime_adapter import (  # noqa: E402
        build_request,
        run_binary,
    )
except ModuleNotFoundError:
    from mapper_runtime_adapter import (  # type: ignore[no-redef]  # noqa: E402
        build_request,
        run_binary,
    )

try:
    from scripts.mapper_capability_matrix import behavior_fingerprint  # noqa: E402
except ModuleNotFoundError:
    from mapper_capability_matrix import behavior_fingerprint  # type: ignore[no-redef]  # noqa: E402

SCHEMA = "simplicio.mapper-differential/v1"
RESULT_SCHEMA = "simplicio.mapper-core-result/v1"
CONTRACT_VERSION = "v1"
SUPPORTED_LANGUAGES = ("python", "javascript", "typescript", "csharp", "razor", "go")
SUPPORTED_CAPABILITIES = ("files", "imports", "batch")
FIXTURE_RELATIVE = Path("contracts/mapper-artifacts/v1/fixtures/canonical-matrix/source")
LANGUAGE_SUFFIXES = {
    "python": (".py", ".pyi"),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "typescript": (".ts", ".tsx"),
    "csharp": (".cs",),
    "razor": (".razor",),
    "go": (".go",),
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def source_generation_digest(sources: list[tuple[str, str]]) -> str:
    return digest([{"path": path, "content": content} for path, content in sorted(sources)])


def _semantic_payload(
    capability: str,
    language: str,
    sources: list[tuple[str, str]],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    # Make this call through the production Python functions while explicitly
    # disabling the optional extension. This is the canonical reference side,
    # not a second parser embedded in the harness.
    native_state = _native.HAS_NATIVE
    try:
        _native.HAS_NATIVE = False
        for path, content in sorted(sources, key=lambda item: item[0]):
            record: dict[str, Any] = {"path": path}
            if capability in {"files", "batch"}:
                record["file_hash"] = _sha256(content)
            if capability in {"imports", "batch"}:
                record["imports"] = _parse_imports(content, language)
            records.append(record)
    finally:
        _native.HAS_NATIVE = native_state
    return {
        "schema": RESULT_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "capability": capability,
        "language": language,
        "coverage": {
            "requested": len(sources),
            "observed": len(sources),
            "omitted": 0,
            "status": "complete",
        },
        "artifact": records,
    }


def fixture_sources(fixture_root: Path, language: str) -> list[tuple[str, str]]:
    suffixes = LANGUAGE_SUFFIXES[language]
    files = [
        path
        for path in fixture_root.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    ]
    return [
        (
            path.relative_to(fixture_root).as_posix(),
            path.read_text(encoding="utf-8", errors="replace"),
        )
        for path in sorted(files)
    ]


def compare_semantic_outputs(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []

    def walk(left: Any, right: Any, path: str) -> None:
        if type(left) is not type(right):
            differences.append({"path": path, "expected": left, "actual": right})
            return
        if isinstance(left, dict):
            for key in sorted(set(left) | set(right)):
                child = f"{path}.{key}"
                if key not in left:
                    differences.append({"path": child, "expected": None, "actual": right[key]})
                elif key not in right:
                    differences.append({"path": child, "expected": left[key], "actual": None})
                else:
                    walk(left[key], right[key], child)
            return
        if isinstance(left, list):
            for index in range(max(len(left), len(right))):
                child = f"{path}[{index}]"
                if index >= len(left):
                    differences.append({"path": child, "expected": None, "actual": right[index]})
                elif index >= len(right):
                    differences.append({"path": child, "expected": left[index], "actual": None})
                else:
                    walk(left[index], right[index], child)
            return
        if left != right:
            differences.append({"path": path, "expected": left, "actual": right})

    walk(expected, actual, "$")
    return {
        "status": "match" if not differences else "mismatch",
        "diff": differences,
        "native_default": not differences,
    }


def unsupported_result(reason: str) -> dict[str, Any]:
    return {
        "status": "unsupported",
        "reason": reason,
        "diff": [],
        "native_default": False,
    }


def _build_adapter(root: Path) -> tuple[Path | None, str | None]:
    manifest = root / "rust" / "runtime-adapter" / "Cargo.toml"
    target = root / "rust" / "target" / "debug" / "simplicio-mapper-runtime-adapter"
    if os.name == "nt":
        target = target.with_suffix(".exe")
    try:
        completed = subprocess.run(
            ["cargo", "build", "--quiet", "--manifest-path", str(manifest)],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"rust_build_unavailable:{error}"
    if completed.returncode != 0 or not target.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()
        return None, f"rust_build_failed:{detail}"
    return target, None


def _pair_result(
    root: Path,
    executable: Path | None,
    capability: str,
    language: str,
    sources: list[tuple[str, str]],
) -> dict[str, Any]:
    request = build_request(capability, language, sources)
    python_first = _semantic_payload(capability, language, sources)
    python_second = _semantic_payload(capability, language, sources)
    if python_first != python_second:
        result = compare_semantic_outputs(python_first, python_second)
        result.update({"reason": "python_nondeterministic", "native_default": False})
        return result
    if executable is None:
        return unsupported_result("rust_adapter_unavailable")
    rust_first, first_error = run_binary(executable, request, root)
    rust_second, second_error = run_binary(executable, request, root)
    if rust_first is None or rust_second is None:
        return unsupported_result(first_error or second_error or "rust_adapter_unavailable")
    if rust_first != rust_second:
        result = compare_semantic_outputs(rust_first, rust_second)
        result.update({"reason": "rust_nondeterministic", "native_default": False})
        return result
    result = compare_semantic_outputs(python_first, rust_first)
    result.update(
        {
            "python_digest": digest(python_first),
            "python_repeat_digest": digest(python_second),
            "rust_digest": digest(rust_first),
            "rust_repeat_digest": digest(rust_second),
            "repeated": True,
            "source_generation_digest": source_generation_digest(sources),
            "coverage": python_first["coverage"],
        }
    )
    return result


def run_differential(root: Path, fixture_root: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    fixture = (fixture_root or root / FIXTURE_RELATIVE).resolve()
    executable, build_error = _build_adapter(root)
    results: list[dict[str, Any]] = []
    for language in SUPPORTED_LANGUAGES:
        sources = fixture_sources(fixture, language)
        for capability in SUPPORTED_CAPABILITIES:
            result = _pair_result(root, executable, capability, language, sources)
            results.append(
                {
                    "language": language,
                    "capability": capability,
                    "contract_version": CONTRACT_VERSION,
                    **result,
                }
            )
    statuses = {result["status"] for result in results}
    status = "mismatch" if "mismatch" in statuses else ("unsupported" if "unsupported" in statuses else "match")
    return {
        "schema": SCHEMA,
        "mapper_version": _mapper_version(),
        "contract_version": CONTRACT_VERSION,
        "behavior_fingerprint": behavior_fingerprint(root),
        "fixture": fixture.relative_to(root).as_posix() if fixture.is_relative_to(root) else str(fixture),
        "build_error": build_error,
        "status": status,
        "results": results,
    }


def _mapper_version() -> str:
    from simplicio_mapper import __version__

    return __version__


def write_report(output_dir: Path, payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    body = {key: value for key, value in payload.items() if key != "report_digest"}
    sealed = {**body, "report_digest": digest(body)}
    destination = output_dir / "mapper-differential.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(canonical_json(sealed) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--fixture")
    parser.add_argument("--output", help="directory for mapper-differential.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repo).resolve()
    payload = run_differential(root, Path(args.fixture).resolve() if args.fixture else None)
    if args.output:
        path = write_report(Path(args.output), payload)
        payload = {**payload, "report_file": str(path)}
    if args.json:
        print(canonical_json(payload))
    else:
        print(f"mapper differential: {payload['status']}")
        for result in payload["results"]:
            print(
                f"- {result['language']}/{result['capability']}@{result['contract_version']}: "
                f"{result['status']}"
            )
    return {"match": 0, "mismatch": 1, "unsupported": 2}[payload["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
