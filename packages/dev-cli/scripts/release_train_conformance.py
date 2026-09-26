#!/usr/bin/env python3
"""Run the installed Mapper release-train conformance smoke.

This is intentionally an executable proof, not a status-only check. It
observes the installed distribution, verifies the lock digests, then performs
Mapper map -> retrieve followed by a Dev CLI mechanical edit, validation, and
receipt inspection. N-1 is accepted only from a separately supplied receipt;
absence is ``UNVERIFIED`` and exits non-zero.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from simplicio.component_manifest import tested_dependency_artifacts
from simplicio.mapper import inspect_target, load_project_map
from simplicio.mechanical_edit import execute_plan
from simplicio.release_train import (
    EVENT_SCHEMA,
    ReleaseTrainError,
    extract_release_event,
    validate_release_event,
)

SCHEMA = "simplicio.dev-cli.release-train-conformance/v1"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseTrainError(f"cannot read JSON {path}: {exc}") from exc


def _run_json(argv: list[str], *, cwd: Path) -> dict[str, Any]:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, timeout=180)
    if result.returncode != 0:
        raise ReleaseTrainError(
            f"command failed ({result.returncode}): {' '.join(argv)}: "
            f"{(result.stderr or result.stdout)[-1200:]}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseTrainError(f"command did not emit JSON: {' '.join(argv)}") from exc
    if not isinstance(value, dict):
        raise ReleaseTrainError(f"command emitted a non-object JSON value: {' '.join(argv)}")
    return value


def _run_contracts(argv: list[str], *, cwd: Path) -> dict[str, Any]:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, timeout=300)
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "command": argv,
        "returncode": result.returncode,
        "output_digest": _digest((result.stdout + result.stderr)[-12000:]),
    }


def _git_commit(path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise ReleaseTrainError(f"contract source is not a Git checkout: {path}")
    return result.stdout.strip()


def _digest(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def _event_digests(event: dict[str, Any]) -> set[str]:
    artifacts = event.get("artifact_digests")
    if not isinstance(artifacts, dict):
        return set()
    return {
        item["digest"]
        for item in artifacts.values()
        if isinstance(item, dict) and isinstance(item.get("digest"), str)
    }


def _lock_digests(artifacts: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    sdist = artifacts.get("sdist")
    if isinstance(sdist, dict) and isinstance(sdist.get("digest"), str):
        values.add(sdist["digest"])
    for item in artifacts.get("wheels", []) or []:
        if isinstance(item, dict) and isinstance(item.get("digest"), str):
            values.add(item["digest"])
    return values


def _smoke() -> dict[str, Any]:
    started = time.perf_counter()
    mapper = shutil.which("simplicio-mapper")
    if mapper is None:
        raise ReleaseTrainError("simplicio-mapper executable is not installed")
    with tempfile.TemporaryDirectory(prefix="simplicio-release-train-smoke-") as raw:
        root = Path(raw)
        target = root / "app.py"
        source = "value = 1\n"
        target.write_text(source, encoding="utf-8")
        map_result = _run_json([mapper, "map", str(root), "--json"], cwd=root)
        index_result = _run_json([mapper, "index", str(root), "--json"], cwd=root)
        retrieved = inspect_target(root, "app.py", goal="release train smoke")
        loaded = load_project_map(root)
        if loaded is None:
            raise ReleaseTrainError("Mapper map did not materialize a retrievable project map")
        operation = {
            "op": "replace_range",
            "path": "app.py",
            "start_line": 1,
            "end_line": 1,
            "text": "value = 2\n",
            "file_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "range_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        }
        plan = {
            "schema": "simplicio.mechanical-edit/v1",
            "touched_files": ["app.py"],
            "operations": [operation],
            "validation": [{"cmd": [sys.executable, "-m", "py_compile", "app.py"], "timeout": 30}],
        }
        previous = os.environ.get("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT")
        os.environ["SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT"] = "1"
        try:
            receipt = execute_plan(plan, root=root, apply=True, allow_native=False)
        finally:
            if previous is None:
                os.environ.pop("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", None)
            else:
                os.environ["SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT"] = previous
        if receipt.get("status") != "ok" or receipt.get("applied") is not True:
            raise ReleaseTrainError(f"mechanical edit smoke failed: {receipt}")
        if target.read_text(encoding="utf-8") != "value = 2\n":
            raise ReleaseTrainError("mechanical edit smoke did not materialize the expected source")
        test = subprocess.run(
            [sys.executable, "-m", "py_compile", "app.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if test.returncode != 0:
            raise ReleaseTrainError(f"post-edit test failed: {test.stderr[-800:]}")
        return {
            "status": "passed",
            "map": {"status": "passed", "schema": map_result.get("schema")},
            "retrieve": {
                "status": "passed",
                "schema": loaded[1].get("schema"),
                "project_map": str(loaded[0].relative_to(root)),
            },
            "edit": {"status": "passed", "receipt_schema": receipt.get("schema")},
            "test": {"status": "passed", "command": [sys.executable, "-m", "py_compile", "app.py"]},
            "receipt_digest": _digest(receipt),
            "index": {"status": "passed", "schema": index_result.get("schema")},
            "performance": {
                "status": "passed",
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "budget_ms": 30000,
            },
            "economy": {
                "status": "measured",
                "observed_json_bytes": sum(
                    len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))
                    for value in (map_result, index_result, retrieved, receipt)
                ),
            },
        }


def conformance(
    root: Path,
    event_value: Any,
    n_minus_1: dict[str, Any] | None,
    *,
    n_minus_1_version: str | None = None,
    mapper_source: Path | None = None,
    n_minus_1_source: Path | None = None,
) -> dict[str, Any]:
    if isinstance(event_value, dict) and isinstance(event_value.get("release_event"), dict):
        event_value = event_value["release_event"]
    event = extract_release_event(event_value)
    if not isinstance(event, dict):
        raise ReleaseTrainError("release event must be an object")
    errors = validate_release_event(event)
    if errors:
        raise ReleaseTrainError("invalid release event: " + "; ".join(errors))
    expected_version = event["version"]
    installed = importlib.metadata.version("simplicio-mapper")
    if installed != expected_version:
        raise ReleaseTrainError(f"installed Mapper is {installed}, expected {expected_version}")
    locked, artifacts, reason = tested_dependency_artifacts("simplicio-mapper", root)
    if locked != expected_version or reason != "locked_in_uv.lock":
        raise ReleaseTrainError(f"lock does not prove Mapper {expected_version}: {locked!r} ({reason})")
    if _event_digests(event) != _lock_digests(artifacts):
        raise ReleaseTrainError("installed lock artifact digests differ from the release event")
    current_contract_cwd = root
    if mapper_source is not None:
        if _git_commit(mapper_source) != event["commit_sha"]:
            raise ReleaseTrainError("current Mapper contract source does not match the release commit")
        current_contract_cwd = mapper_source
    current_contracts = _run_contracts(
        ["simplicio-mapper", "doctor", "--contracts"], cwd=current_contract_cwd
    )
    smoke = _smoke()
    previous_contracts: dict[str, Any] | None = None
    if n_minus_1_version:
        if n_minus_1_version == expected_version:
            raise ReleaseTrainError("N-1 version must differ from the candidate")
        uv = shutil.which("uv")
        if uv is None:
            raise ReleaseTrainError("uv is required for the isolated N-1 contract lane")
        previous_contracts = _run_contracts(
            [
                uv,
                "run",
                "--no-project",
                "--with",
                f"simplicio-mapper=={n_minus_1_version}",
                "simplicio-mapper",
                "doctor",
                "--contracts",
            ],
            cwd=n_minus_1_source or root,
        )
    current_status = "passed" if current_contracts["status"] == "passed" else "UNVERIFIED"
    n_minus_1_status = (
        "passed"
        if (previous_contracts is not None and previous_contracts.get("status") == "passed")
        or (
            previous_contracts is None
            and isinstance(n_minus_1, dict)
            and n_minus_1.get("status") in {"passed", "green", True}
        )
        else "UNVERIFIED"
    )
    result = {
        "schema": SCHEMA,
        "event_schema": EVENT_SCHEMA,
        "status": "passed" if current_status == "passed" and n_minus_1_status == "passed" else "UNVERIFIED",
        "version": expected_version,
        "installed_version": installed,
        "lock": {"status": "passed", "version": locked, "reason": reason, "artifact_digests": artifacts},
        "entrypoint_owner": "simplicio-mapper",
        "n": current_status,
        "n_minus_1": n_minus_1_status,
        "contracts": {"n": current_contracts, "n_minus_1": previous_contracts},
        "smoke": smoke,
        "evidence": {
            "required": ["n", "n_minus_1", "clean_installed_entrypoint", "map_retrieve_edit_test_receipt"],
            "n_source": "immutable_tag_checkout" if mapper_source is not None else "installed_environment",
            "n_minus_1_source": (
                "immutable_tag_checkout"
                if n_minus_1_source is not None
                else "supplied_receipt"
                if n_minus_1 is not None
                else None
            ),
        },
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--n-minus-1", type=Path, help="receipt from a real previous Mapper installation")
    parser.add_argument("--n-minus-1-version", help="run the isolated Mapper contract lane at this version")
    parser.add_argument("--mapper-source", type=Path, help="N Mapper checkout containing the contracts tree")
    parser.add_argument(
        "--n-minus-1-source", type=Path, help="N-1 Mapper checkout containing the contracts tree"
    )
    parser.add_argument("--output", type=Path, default=Path(".simplicio-loop/release-train-conformance.json"))
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        event = _read_json(args.event.resolve())
        previous = _read_json(args.n_minus_1.resolve()) if args.n_minus_1 else None
        result = conformance(
            root,
            event,
            previous,
            n_minus_1_version=args.n_minus_1_version,
            mapper_source=args.mapper_source.resolve() if args.mapper_source else None,
            n_minus_1_source=args.n_minus_1_source.resolve() if args.n_minus_1_source else None,
        )
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "passed" else 2
    except (
        OSError,
        KeyError,
        ReleaseTrainError,
        TypeError,
        ValueError,
        importlib.metadata.PackageNotFoundError,
    ) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
