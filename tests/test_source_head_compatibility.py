"""Compatibility checks for the requested source-head integration train."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]

# Measured from the source heads used by the 2026-09-13 integration audit.
SOURCE_HEAD_VERSIONS = {
    "simplicio-mapper": "0.26.31",
    "simplicio-fast": "2.0.32",
    "simplicio-cli": "0.18.12",
}

CLI_ENVIRONMENT = {
    "SIMPLICIO_AUTO_UPGRADE": "0",
    "SIMPLICIO_SKIP_AUTO_INIT": "1",
    "SIMPLICIO_NO_NETWORK": "1",
}

PROBE_TIMEOUT_SECONDS = 30

REQUIRED_TASK_FLAGS = (
    "--context-snapshot-id",
    "--context-pack-hash",
    "--dry-run-task",
    "--verify-only",
    "--task-spec",
    "--execution-context",
    "--effect-authorization",
    "--attempt-id",
    "--lease-id",
    "--fencing-token",
)

MAPPER_API_PROBE = r'''
import importlib.metadata as metadata
import json
import sys
from pathlib import Path

from simplicio_mapper.store import OperationsStore, resolve_store_location

root = Path(sys.argv[1])
location = resolve_store_location(
    data_dir=root / "mapper-data",
    repo_root=root,
    allow_temp=False,
)
assert location.source == "flag", location
assert location.root == root / "mapper-data", location.root
location.ensure_root()
store = OperationsStore(location.database("operations.sqlite"))
initialized = store.initialize()
assert initialized["schema"] == "simplicio.mapper-store.operations-api/v1"

queued = store.enqueue(
    "compatibility-task",
    {"goal": "source-head compatibility", "write_set": ["module.py"]},
    idempotency_key="source-head-compatibility",
)
assert queued["status"] == "queued", queued
claimed = store.claim("compatibility-worker", task_id="compatibility-task")
assert claimed is not None, claimed
checkpointed = store.checkpoint(
    claimed["attempt_id"],
    claimed["fence_token"],
    1,
    {"phase": "public-api-probe"},
)
assert checkpointed["status"] == "checkpointed", checkpointed
completed = store.complete(
    claimed["attempt_id"],
    claimed["fence_token"],
    receipt={"evidence": "operations-store"},
)
assert completed["status"] == "completed", completed
status = store.status("compatibility-task")
assert status["state"] == "completed", status

print(json.dumps({
    "installed_version": metadata.version("simplicio-mapper"),
    "store_schema": initialized["schema"],
    "resolved_source": location.source,
    "task_status": status["state"],
}))
'''

FAST_API_PROBE = r'''
import importlib.metadata as metadata
import json
import sys
from pathlib import Path

from simplicio_fast import OperationReceipt, OperationsProjection, WorkspaceStore
from simplicio_fast.generation_receipts import seal_receipt, verify_receipt

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
source = root / "module.py"
source.write_text(
    "class CompatibilityTarget:\n"
    "    pass\n",
    encoding="utf-8",
)
storage = root / "fast-data"
store = WorkspaceStore(root, storage)
manifest = store.build_base(config={"source_head_compatibility": True})
snapshot = storage / "base" / manifest.generation_id / manifest.snapshot
store.validate_snapshot(snapshot, manifest.snapshot_sha256)

operation = OperationReceipt(
    handle="source-head-compatibility",
    kind="build",
    status="completed",
    generation=manifest.generation_id,
    sequence=1,
    source_schema="simplicio.fast.operations-receipt/v1",
    payload={"snapshot": manifest.snapshot},
)
projection = OperationsProjection(str(root), manifest.generation_id)
ingested = projection.ingest([operation])
projected = projection.snapshot()
assert operation.to_dict()["schema"] == "simplicio.fast.operations-receipt/v1"
assert ingested["schema"] == "simplicio.fast.operations-delta/v1"
assert projected["schema"] == "simplicio.fast.operations-projection/v1"

receipt = seal_receipt(
    kind="build",
    repo=str(root),
    commit=manifest.commit,
    snapshot_digest=manifest.snapshot_sha256,
    generation=manifest.generation_id,
    source_hashes=manifest.source_hashes,
    backend="python",
)
verified = verify_receipt(
    receipt,
    expected_repo=str(root),
    expected_commit=manifest.commit,
    expected_generation=manifest.generation_id,
    expected_source_hashes=manifest.source_hashes,
)
assert receipt["schema"] == "simplicio.fast-generation-receipt/v1"
assert verified["receipt_hash"] == receipt["receipt_hash"], verified
receipt_files = list((storage / "receipts").glob("*.json"))
assert receipt_files, receipt_files

print(json.dumps({
    "installed_version": metadata.version("simplicio-fast"),
    "operation_receipt_schema": operation.to_dict()["schema"],
    "receipt_schema": receipt["schema"],
    "projection_schema": projected["schema"],
    "snapshot_exists": snapshot.is_file(),
    "receipt_verified": True,
    "receipt_count": len(receipt_files),
}))
'''

DEV_CLI_API_PROBE = r'''
import importlib.metadata as metadata
import json

from simplicio.plan_compiler import PLAN_DAG_SCHEMA, PlanDAG, PlanNode, VerificationPlan

edit = PlanNode(
    node_id="edit",
    capability="edit.apply",
    write_set=["module.py"],
    acceptance_criteria_refs=["compatibility"],
    requires_gate=True,
)
verify = PlanNode(
    node_id="verify",
    capability="test.run",
    depends_on=["edit"],
)
plan = PlanDAG(
    plan_id="source-head-compatibility",
    goal_id="source-head-compatibility",
    context_snapshot_id="source-head-context",
    revision="source-head",
    nodes=[edit, verify],
    producer_id="simplicio-dev-cli",
)
verification = VerificationPlan(
    verification_id="compatibility-verification",
    plan_node_id="verify",
    verifier="pytest",
    command_or_capability="python -m pytest",
    timeout_s=30,
    acceptance_criteria_refs=["compatibility"],
)
plan.validate(verifications=[verification])
round_trip = PlanDAG.from_dict(plan.to_dict())
assert plan.to_dict()["schema"] == PLAN_DAG_SCHEMA == "simplicio.plan-dag/v1"
assert round_trip.canonical_hash() == plan.canonical_hash()

print(json.dumps({
    "installed_version": metadata.version("simplicio-cli"),
    "plan_schema": PLAN_DAG_SCHEMA,
    "node_count": len(round_trip.nodes),
    "round_trip_hash": round_trip.canonical_hash(),
}))
'''


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _bounds(dependency: str, name: str) -> tuple[str, str]:
    match = re.fullmatch(rf"{re.escape(name)}>=(\d+\.\d+\.\d+),<(\d+(?:\.\d+){{0,2}})", dependency)
    assert match, f"unexpected dependency declaration for {name}: {dependency}"
    return match.group(1), match.group(2)


def _operator_binary(name: str) -> str:
    binary = shutil.which(name)
    assert binary, (
        f"required installed public operator {name!r} is unavailable on PATH; "
        "source-head compatibility evidence cannot be collected"
    )
    return binary


def _offline_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(CLI_ENVIRONMENT)
    for key in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        environment.pop(key, None)
    return environment


def _script_interpreter(binary: str) -> str | None:
    try:
        first_line = Path(binary).read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeError, IndexError):
        return None
    if not first_line.startswith("#!"):
        return None
    parts = shlex.split(first_line[2:])
    if not parts:
        return None
    if Path(parts[0]).name == "env":
        if len(parts) < 2:
            return None
        return shutil.which(parts[1])
    return parts[0] if Path(parts[0]).exists() else None


def _operator_python(binary_name: str, module_name: str) -> str:
    binary = _operator_binary(binary_name)
    interpreter = _script_interpreter(binary)
    if interpreter:
        return interpreter
    assert importlib.util.find_spec(module_name) is not None, (
        f"{binary_name!r} is installed but its public API module {module_name!r} "
        "is unavailable in the test interpreter"
    )
    return sys.executable


def _run_cli(binary_name: str, arguments: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    binary = _operator_binary(binary_name)
    result = subprocess.run(
        [binary, *arguments],
        cwd=cwd,
        env=_offline_environment(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, (
        f"{binary_name} {' '.join(arguments)} failed with exit code "
        f"{result.returncode}: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    return result


def _run_api_probe(
    binary_name: str,
    module_name: str,
    source: str,
    root: Path,
) -> dict[str, object]:
    interpreter = _operator_python(binary_name, module_name)
    result = subprocess.run(
        [interpreter, "-c", source, str(root)],
        cwd=ROOT,
        env=_offline_environment(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, (
        f"{binary_name} public API probe failed with exit code {result.returncode}: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    try:
        evidence = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"{binary_name} public API probe did not return JSON: {result.stdout!r}"
        ) from error
    assert isinstance(evidence, dict), evidence
    return evidence


def _assert_installed_version(name: str, installed_version: object) -> None:
    assert isinstance(installed_version, str), installed_version
    assert re.fullmatch(r"\d+\.\d+\.\d+", installed_version), installed_version
    requested_version = SOURCE_HEAD_VERSIONS[name]
    assert _version(installed_version) >= _version(requested_version), (
        f"installed {name} {installed_version} is older than requested source head "
        f"{requested_version}"
    )
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = manifest["project"]["dependencies"]
    declaration = next(
        dependency for dependency in dependencies
        if dependency.startswith(f"{name}>=")
    )
    floor, ceiling = _bounds(declaration, name)
    assert _version(floor) <= _version(installed_version) < _version(ceiling), (
        f"installed {name} {installed_version} falls outside {declaration}"
    )


def _run_operator_contract_probes(root: Path) -> dict[str, dict[str, object]]:
    mapper_cli = _run_cli("simplicio-mapper", ["version", "--json"], cwd=ROOT)
    mapper_cli_evidence = json.loads(mapper_cli.stdout)
    mapper_evidence = _run_api_probe(
        "simplicio-mapper", "simplicio_mapper", MAPPER_API_PROBE, root / "mapper-api"
    )
    _assert_installed_version("simplicio-mapper", mapper_evidence["installed_version"])
    assert mapper_cli_evidence["schema"] == "simplicio.mapper-version/v1", mapper_cli_evidence
    assert mapper_cli_evidence["component"] == "simplicio-mapper", mapper_cli_evidence
    assert mapper_cli_evidence["version"] == mapper_evidence["installed_version"]
    assert mapper_evidence["resolved_source"] == "flag", mapper_evidence

    fast_root = root / "fast-api"
    fast_evidence = _run_api_probe("simplicio-fast", "simplicio_fast", FAST_API_PROBE, fast_root)
    _assert_installed_version("simplicio-fast", fast_evidence["installed_version"])
    fast_version = _run_cli("simplicio-fast", ["--version"], cwd=ROOT).stdout.strip()
    assert fast_evidence["installed_version"] in fast_version, fast_version

    fast_cli_root = root / "fast-cli"
    fast_cli_root.mkdir(parents=True, exist_ok=True)
    (fast_cli_root / "module.py").write_text(
        "class CompatibilityTarget:\n"
        "    pass\n",
        encoding="utf-8",
    )
    snapshot = fast_cli_root / "project.sfast"
    build = json.loads(_run_cli(
        "simplicio-fast",
        [
            "--fast-engine",
            "python",
            "build",
            str(fast_cli_root),
            "--output",
            str(snapshot),
            "--json",
        ],
        cwd=ROOT,
    ).stdout)
    assert build["schema"] == "simplicio.fast.build/v1", build
    assert snapshot.is_file(), snapshot
    stats = json.loads(_run_cli(
        "simplicio-fast",
        ["--fast-engine", "python", "stats", "--snapshot", str(snapshot), "--json"],
        cwd=ROOT,
    ).stdout)
    assert stats["schema"] == "simplicio.fast.stats/v1", stats
    search = json.loads(_run_cli(
        "simplicio-fast",
        [
            "--fast-engine",
            "python",
            "search",
            "CompatibilityTarget",
            "--snapshot",
            str(snapshot),
            "--json",
        ],
        cwd=ROOT,
    ).stdout)
    assert search["schema"] == "simplicio.fast.search/v1", search
    assert search["matches"], search
    fast_evidence["cli_search_schema"] = search["schema"]

    dev_cli_version = _run_cli("simplicio-dev-cli", ["--version"], cwd=ROOT).stdout
    dev_cli_evidence = _run_api_probe(
        "simplicio-dev-cli", "simplicio", DEV_CLI_API_PROBE, root / "dev-cli-api"
    )
    _assert_installed_version("simplicio-cli", dev_cli_evidence["installed_version"])
    assert dev_cli_evidence["installed_version"] in dev_cli_version, dev_cli_version
    task_help = _run_cli("simplicio-dev-cli", ["task", "--help"], cwd=ROOT).stdout
    for flag in REQUIRED_TASK_FLAGS:
        assert flag in task_help, f"simplicio-dev-cli task help lacks public flag {flag}"

    return {
        "mapper": mapper_evidence,
        "fast": fast_evidence,
        "dev_cli": dev_cli_evidence,
    }


def test_requested_source_heads_satisfy_loop_dependency_floors() -> None:
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = manifest["project"]["dependencies"]

    for name, source_version in SOURCE_HEAD_VERSIONS.items():
        declaration = next(
            dependency for dependency in dependencies
            if dependency.startswith(f"{name}>=")
        )
        floor, ceiling = _bounds(declaration, name)
        assert _version(floor) <= _version(source_version) < _version(ceiling), (
            f"{name} declaration {declaration} excludes requested source head "
            f"{source_version}"
        )


def test_source_heads_are_exercised_by_public_operator_surfaces(tmp_path) -> None:
    evidence = _run_operator_contract_probes(tmp_path)

    assert evidence["mapper"]["store_schema"] == "simplicio.mapper-store.operations-api/v1"
    assert evidence["fast"]["operation_receipt_schema"] == "simplicio.fast.operations-receipt/v1"
    assert evidence["fast"]["receipt_schema"] == "simplicio.fast-generation-receipt/v1"
    assert evidence["fast"]["cli_search_schema"] == "simplicio.fast.search/v1"
    assert evidence["dev_cli"]["plan_schema"] == "simplicio.plan-dag/v1"
