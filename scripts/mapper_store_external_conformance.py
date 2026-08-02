#!/usr/bin/env python3
"""Produce hash-bound MapperStore conformance receipts in a clean sandbox.

The final Mapper gate is deliberately read-only and does not import consumer
packages. This command is the complementary producer: it installs the
supplied wheels into a disposable venv, runs one explicitly named scenario,
and emits ``simplicio.mapper-store-conformance-evidence/v1``. Unsupported
platforms or missing upgrade seeds remain ``unverified``; this tool never
turns a skipped lane into a pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.mapper-store-conformance-evidence/v1"
SCENARIOS = (
    "fresh standalone",
    "upgrade standalone",
    "fresh runtime-backed",
    "upgrade runtime-backed",
    "sqlite-vec present",
    "sqlite-vec absent",
    "crash during migration",
    "legacy database corrupted",
    "Windows",
    "Linux",
    "macOS",
)
REPOSITORIES = ("mapper", "loop", "dev-cli", "runtime")


def canonical_hash(value: Mapping[str, Any]) -> str:
    """Hash a receipt without its self-referential ``evidence_hash`` field."""
    payload = {key: item for key, item in value.items() if key != "evidence_hash"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _run(command: list[str], *, cwd: Path, env: Mapping[str, str], timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "command": command,
            "returncode": None,
            "status": "blocked",
            "error": type(error).__name__,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    return {
        "command": command,
        "returncode": result.returncode,
        "status": "pass" if result.returncode == 0 else "fail",
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _git_revision(root: Path) -> tuple[str, bool]:
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if revision.returncode != 0:
        raise RuntimeError(f"not a git checkout: {root}")
    return revision.stdout.strip(), status.returncode == 0 and not status.stdout.strip()


def repository_evidence(repos: Mapping[str, Path]) -> tuple[dict[str, Any], bool]:
    evidence: dict[str, Any] = {}
    clean = True
    for name in REPOSITORIES:
        revision, working_tree_clean = _git_revision(repos[name])
        evidence[name] = {"revision": revision}
        clean = clean and working_tree_clean
    return evidence, clean


def _host_platform() -> str:
    system = platform.system().lower()
    return {"darwin": "macOS", "windows": "Windows", "linux": "Linux"}.get(system, system)


def _platform_for_scenario(scenario: str) -> str | None:
    return scenario if scenario in {"Windows", "Linux", "macOS"} else None


def _last_json(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if text:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value
    decoder = json.JSONDecoder()
    starts = [index for index, character in enumerate(stdout) if character == "{"]
    for start in starts:
        try:
            value, _ = decoder.raw_decode(stdout[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _inventory(repos: Mapping[str, Path]) -> tuple[dict[str, Any] | None, str | None]:
    """Run the source inventory read-only; never claim zero legacy writers."""
    mapper_root = repos["mapper"]
    if str(mapper_root) not in sys.path:
        sys.path.insert(0, str(mapper_root))
    try:
        from scripts.mapper_store_inventory import build_inventory

        payload = build_inventory(
            [(name, repos[name]) for name in REPOSITORIES], [], deterministic=True
        )
    except (ImportError, OSError, RuntimeError) as error:
        return None, f"inventory producer unavailable: {type(error).__name__}"
    return payload, None


def _receipt(
    *,
    scenario: str,
    repositories: Mapping[str, Any],
    working_tree_clean: bool,
    status: str,
    ok: bool,
    reason: str,
    platform_name: str,
    legacy_ddl_matches: int = 0,
    observations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "check": "scenario",
        "scenario_id": scenario,
        "status": status,
        "ok": ok,
        "reason": reason,
        "sandbox": {
            "disposable": True,
            "working_tree_clean": working_tree_clean,
            "platform": platform_name,
        },
        "repositories": dict(repositories),
        "writer_authority": "mapper-store",
        "legacy_ddl_matches": legacy_ddl_matches,
        "effects_attempted": False,
        "rollback_verified": False,
        "fault_injection_verified": False,
    }
    if observations:
        value["observations"] = dict(observations)
    value["evidence_hash"] = canonical_hash(value)
    return value


def _install_wheels(
    py: Path,
    wheels: Mapping[str, Path],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
) -> dict[str, Any]:
    command = [
        str(py),
        "-m",
        "pip",
        "install",
        "--ignore-installed",
        "--no-index",
        "--no-deps",
        *(str(wheels[name]) for name in ("mapper", "dev-cli", "loop")),
    ]
    return _run(command, cwd=cwd, env=env, timeout=timeout)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _standalone(
    *,
    wheels: Mapping[str, Path],
    legacy_memory_dir: Path | None,
    upgrade: bool,
    timeout: float,
) -> tuple[bool, str, dict[str, Any]]:
    if legacy_memory_dir is not None and not legacy_memory_dir.is_dir():
        return False, "upgrade seed directory does not exist", {}
    with tempfile.TemporaryDirectory(prefix="mapper-store-conformance-") as raw:
        sandbox = Path(raw)
        fixture = sandbox / "fixture"
        (fixture / "src").mkdir(parents=True)
        (fixture / "src" / "app.py").write_text("def greet(name):\n    return f'hello {name}'\n", encoding="utf-8")
        memory = fixture / "memory"
        if legacy_memory_dir is not None:
            shutil.copytree(legacy_memory_dir, memory)
        else:
            memory.mkdir()
        legacy_candidates = [memory / "index.sqlite3", memory / "memory" / "index.sqlite3"]
        legacy_before = {
            str(path.relative_to(fixture)): _file_hash(path)
            for path in legacy_candidates
            if path.exists()
        }

        venv_root = sandbox / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=True, clear=True).create(venv_root)
        py = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        bin_root = py.parent
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join([str(bin_root), "/usr/bin", "/bin"])
        install = _install_wheels(py, wheels, cwd=fixture, env=env, timeout=timeout)
        observations: dict[str, Any] = {"install": install}
        if install["status"] != "pass":
            return False, "consumer wheel installation failed", observations

        dev = bin_root / ("simplicio-dev-cli.exe" if os.name == "nt" else "simplicio-dev-cli")
        loop = bin_root / ("simplicio-loop.exe" if os.name == "nt" else "simplicio-loop")
        commands: list[tuple[str, list[str]]] = [
            ("memory_init", [str(dev), "memory", "init", "--dir", str(memory), "--json"]),
            (
                "memory_store",
                [str(dev), "memory", "store", "conformance", "standalone receipt", "--dir", str(memory), "--json"],
            ),
            (
                "memory_recall",
                [str(dev), "memory", "recall", "standalone", "--dir", str(memory), "--mode", "hybrid", "--json"],
            ),
            (
                "memory_validate",
                [str(dev), "memory", "validate", "--dir", str(memory), "--strict", "--json"],
            ),
            (
                "memory_handoff",
                [str(dev), "memory", "handoff", "standalone", "--dir", str(memory), "--from-agent", "harness", "--to-agent", "gate", "--json"],
            ),
            ("loop_preflight", [str(loop), "preflight", "--repo", str(fixture), "--json"]),
            (
                "loop_orient",
                [str(loop), "orient", "--repo", str(fixture), "--task", "inspect src/app.py", "--fast", "off"],
            ),
        ]
        for name, command in commands:
            result = _run(command, cwd=fixture, env=env, timeout=timeout)
            observations[name] = result
            if result["status"] != "pass":
                return False, f"{name} failed", observations

        legacy_paths = [fixture / "index.sqlite3", *legacy_candidates]
        observations["legacy_sqlite_paths"] = [str(path) for path in legacy_paths if path.exists()]
        legacy_after = {
            str(path.relative_to(fixture)): _file_hash(path)
            for path in legacy_candidates
            if path.exists()
        }
        observations["legacy_before"] = legacy_before
        observations["legacy_after"] = legacy_after
        observations["mapper_store_paths"] = sorted(
            str(path.relative_to(fixture))
            for path in fixture.rglob("*")
            if path.is_file() and ".simplicio/mapper-store" in str(path.relative_to(fixture))
        )
        if not upgrade and observations["legacy_sqlite_paths"]:
            return False, "legacy SQLite writer materialized a database", observations
        if upgrade and legacy_before != legacy_after:
            return False, "upgrade changed the preserved legacy SQLite index", observations
        validate_payload = _last_json(observations["memory_validate"].get("stdout", ""))
        if not validate_payload or validate_payload.get("ok") is not True:
            return False, "installed memory validation did not report ok", observations
        index_path = str((validate_payload.get("index") or {}).get("path", ""))
        if ".simplicio/mapper-store" not in index_path:
            return False, "installed memory validation did not select MapperStore", observations
        preflight_payload = _last_json(observations["loop_preflight"].get("stdout", ""))
        if not preflight_payload or preflight_payload.get("all_present") is not True:
            return False, "installed Loop preflight did not report required operators", observations
        return True, (
            "upgrade standalone installed consumer lane passed"
            if upgrade
            else "fresh standalone installed consumer lane passed"
        ), observations


def run_scenario(
    *,
    scenario: str,
    repos: Mapping[str, Path],
    wheels: Mapping[str, Path],
    legacy_memory_dir: Path | None,
    timeout: float,
) -> dict[str, Any]:
    repository_revisions, clean = repository_evidence(repos)
    inventory, inventory_error = _inventory(repos)
    if inventory_error:
        return _receipt(
            scenario=scenario,
            repositories=repository_revisions,
            working_tree_clean=clean,
            status="unverified",
            ok=False,
            reason=inventory_error,
            platform_name=_host_platform(),
        )
    policy = (inventory or {}).get("policy") or {}
    legacy_ddl_matches = int(policy.get("legacy_ddl_matches", 0))
    inventory_observation = {
        "legacy_ddl_matches": legacy_ddl_matches,
        "policy_status": policy.get("status"),
        "legacy_ddl_files": policy.get("legacy_ddl_files", []),
    }
    host = _host_platform()
    target_platform = _platform_for_scenario(scenario)
    if target_platform is not None and target_platform != host:
        return _receipt(
            scenario=scenario,
            repositories=repository_revisions,
            working_tree_clean=clean,
            status="unverified",
            ok=False,
            reason=f"scenario requires {target_platform}; producer host is {host}",
            platform_name=host,
            legacy_ddl_matches=legacy_ddl_matches,
            observations={"inventory": inventory_observation},
        )
    if scenario not in {"fresh standalone", "upgrade standalone"}:
        return _receipt(
            scenario=scenario,
            repositories=repository_revisions,
            working_tree_clean=clean,
            status="unverified",
            ok=False,
            reason="this producer currently covers only standalone installed consumers",
            platform_name=host,
            legacy_ddl_matches=legacy_ddl_matches,
            observations={"inventory": inventory_observation},
        )
    if scenario == "upgrade standalone" and legacy_memory_dir is None:
        return _receipt(
            scenario=scenario,
            repositories=repository_revisions,
            working_tree_clean=clean,
            status="unverified",
            ok=False,
            reason="upgrade requires an explicit legacy memory seed directory",
            platform_name=host,
            legacy_ddl_matches=legacy_ddl_matches,
            observations={"inventory": inventory_observation},
        )
    ok, reason, observations = _standalone(
        wheels=wheels,
        legacy_memory_dir=legacy_memory_dir,
        upgrade=scenario == "upgrade standalone",
        timeout=timeout,
    )
    observations["inventory"] = inventory_observation
    if legacy_ddl_matches:
        ok = False
        reason = "source inventory found external legacy DDL writers"
    return _receipt(
        scenario=scenario,
        repositories=repository_revisions,
        working_tree_clean=clean,
        status="pass" if ok else "fail",
        ok=ok,
        reason=reason,
        platform_name=host,
        legacy_ddl_matches=legacy_ddl_matches,
        observations=observations,
    )


def _named_paths(values: list[str], names: tuple[str, ...]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"expected name=path, got {value!r}")
        name, raw = value.split("=", 1)
        if name not in names:
            raise SystemExit(f"unknown name {name!r}")
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"path does not exist: {path}")
        result[name] = path
    missing = [name for name in names if name not in result]
    if missing:
        raise SystemExit(f"missing named paths: {', '.join(missing)}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--repo", action="append", default=[], help="clean producer checkout as name=path")
    parser.add_argument("--wheel", action="append", default=[], help="consumer wheel as name=path (mapper, dev-cli, loop)")
    parser.add_argument("--legacy-memory-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    repos = _named_paths(args.repo, REPOSITORIES)
    wheels = _named_paths(args.wheel, ("mapper", "dev-cli", "loop"))
    legacy = args.legacy_memory_dir.expanduser().resolve() if args.legacy_memory_dir else None
    receipt = run_scenario(
        scenario=args.scenario,
        repos=repos,
        wheels=wheels,
        legacy_memory_dir=legacy,
        timeout=args.timeout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
