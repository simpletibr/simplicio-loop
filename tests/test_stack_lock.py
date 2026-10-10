from __future__ import annotations

import json

import pytest

from simplicio_loop import runner as runner_mod
from simplicio_loop import stack_lock as stack_lock_mod
from simplicio_loop.cli_impl import main
from simplicio_loop.stack_lock import (
    STACK_LOCK_SCHEMA,
    STACK_REGISTRY_SCHEMA,
    StackCompatibilityRegistry,
    StackLock,
    StackLockError,
    diagnose_stack,
    load_stack_lock,
    observe_component,
    observe_components,
    validate_stack_lock,
    write_stack_lock,
)
from tests.runner_patch import patch_runner


def _component(tmp_path, name="simplicio-mapper", content=b"mapper"):
    binary = tmp_path / name
    binary.write_bytes(content)
    return observe_component(name, "1.0.0", binary, build_sha="build", capabilities=("map",))


def _stack_registry():
    return StackCompatibilityRegistry.from_dict({
        "schema": STACK_REGISTRY_SCHEMA,
        "generation": "registry-2026-08",
        "components": [
            {
                "name": "simplicio-loop",
                "version_range": ">=1.0.0,<2.0.0",
                "required_capabilities": ["orchestrator"],
                "routes": ["standalone"],
            },
            {
                "name": "simplicio-mapper",
                "version_range": ">=1.0.0,<2.0.0",
                "required_capabilities": ["map"],
                "routes": ["standalone"],
            },
        ],
        "compatibility": [{
            "producer": "simplicio-mapper",
            "consumer": "simplicio-loop",
            "producer_range": ">=1.0.0,<2.0.0",
            "consumer_range": ">=1.0.0,<2.0.0",
            "required_capabilities": ["map"],
        }],
        "upgrade_groups": [{
            "name": "core",
            "components": ["simplicio-loop", "simplicio-mapper"],
        }],
    })


def test_lock_hash_is_order_independent_and_only_the_standalone_route_exists(tmp_path):
    mapper = _component(tmp_path)
    cli = _component(tmp_path, "simplicio-cli", b"cli")
    first = StackLock.create([cli, mapper], "standalone", run_id="run-1")
    second = StackLock.create([mapper, cli], "standalone", run_id="run-1")
    assert first.lock_hash == second.lock_hash
    assert first.to_dict()["schema"] == STACK_LOCK_SCHEMA
    first.verify_unchanged([mapper, cli], "standalone")
    with pytest.raises(StackLockError, match="invalid route"):
        first.verify_unchanged([mapper, cli], "runtime-backed")
    with pytest.raises(StackLockError, match="invalid route"):
        StackLock.create([mapper], "runtime-backed")


def test_artifact_drift_blocks_a_frozen_lock(tmp_path):
    mapper = _component(tmp_path)
    lock = StackLock.create([mapper], "standalone")
    (tmp_path / "simplicio-mapper").write_bytes(b"mapper-upgraded")
    changed = observe_component(
        "simplicio-mapper", "1.0.0", tmp_path / "simplicio-mapper", build_sha="build", capabilities=("map",),
    )
    with pytest.raises(StackLockError, match="stack drift"):
        lock.verify_unchanged([changed], "standalone")


def test_serialized_lock_is_checked(tmp_path):
    mapper = _component(tmp_path)
    lock = StackLock.create([mapper], "standalone")
    payload = lock.to_dict()
    assert validate_stack_lock(payload) == []
    payload["lock_hash"] = "bad"
    assert "lock_hash_invalid" in validate_stack_lock(payload)


def test_persistence_is_atomic_and_immutable(tmp_path):
    mapper = _component(tmp_path)
    lock = StackLock.create([mapper], "standalone", run_id="run-1")
    path = tmp_path / "run" / "stack-lock.json"

    assert write_stack_lock(lock, path) == path
    assert load_stack_lock(path).lock_hash == lock.lock_hash
    assert write_stack_lock(lock, path) == path

    changed = StackLock.create([_component(tmp_path, content=b"changed")], "standalone", run_id="run-1")
    with pytest.raises(StackLockError, match="different hash"):
        write_stack_lock(changed, path)


def test_persisted_component_tampering_is_rejected(tmp_path):
    mapper = _component(tmp_path)
    lock = StackLock.create([mapper], "standalone")
    path = tmp_path / "stack-lock.json"
    write_stack_lock(lock, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["components"][0]["version"] = "9.9.9"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(StackLockError, match="lock_hash_mismatch"):
        load_stack_lock(path)


def test_stack_cli_lock_and_verify_fail_closed_on_artifact_drift(tmp_path, capsys):
    binary = tmp_path / "simplicio-mapper"
    binary.write_bytes(b"mapper")
    components = tmp_path / "components.json"
    components.write_text(json.dumps({
        "components": [{
            "name": "simplicio-mapper",
            "version": "1.0.0",
            "executable": str(binary),
            "build_sha": "build",
            "capabilities": ["map"],
        }]
    }), encoding="utf-8")
    lock_path = tmp_path / "stack-lock.json"

    assert main([
        "stack", "lock", "--components", str(components), "--route", "standalone",
        "--run-id", "run-1", "--output", str(lock_path),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "LOCKED"

    assert main([
        "stack", "verify", "--lock", str(lock_path), "--components", str(components),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED"

    binary.write_bytes(b"mapper-upgraded")
    assert main([
        "stack", "verify", "--lock", str(lock_path), "--components", str(components),
    ]) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["status"] == "BLOCKED"
    assert "stack drift" in blocked["error"]


def test_observation_payload_and_stack_doctor_report_routes(tmp_path, monkeypatch, capsys):
    loop_binary = tmp_path / "simplicio-loop"
    mapper_binary = tmp_path / "simplicio-mapper"
    loop_binary.write_bytes(b"loop")
    mapper_binary.write_bytes(b"mapper")
    observations = {
        "components": [
            {"name": "simplicio-loop", "version": "1.0.0", "executable": str(loop_binary)},
            {"name": "simplicio-mapper", "version": "1.0.0", "executable": str(mapper_binary)},
        ]
    }
    assert len(observe_components(observations)) == 2
    path = tmp_path / "components.json"
    path.write_text(json.dumps(observations), encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_STACK_COMPONENTS_FILE", str(path))

    assert main(["doctor", "stack", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema"] == "simplicio.stack-doctor/v1"
    assert result["status"] == "READY"
    assert result["routes"]["standalone"]["available"] is True
    assert "runtime-backed" not in result["routes"]


def test_runner_freezes_and_verifies_stack_lock_at_boundaries(tmp_path, monkeypatch):
    binary = tmp_path / "simplicio-mapper"
    binary.write_bytes(b"mapper")
    def discover():
        return (observe_component("simplicio-mapper", "1.0.0", binary, capabilities=("map",)),)

    patch_runner(monkeypatch, "discover_installed_components", discover)
    monkeypatch.setenv("SIMPLICIO_EXECUTION_PROFILE", "standalone")
    run_root = tmp_path / "run"
    run_root.mkdir()

    lock = runner_mod._freeze_stack_lock(run_root, "run-1")
    assert (run_root / "stack-lock.json").exists()
    assert runner_mod._verify_run_stack_lock(run_root).lock_hash == lock.lock_hash

    binary.write_bytes(b"mapper-upgraded")
    with pytest.raises(StackLockError, match="stack drift"):
        runner_mod._verify_run_stack_lock(run_root)


def test_stack_registry_roundtrip_is_deterministic():
    registry = _stack_registry()
    payload = registry.to_dict()
    assert payload["schema"] == STACK_REGISTRY_SCHEMA
    assert StackCompatibilityRegistry.from_dict(payload) == registry
    assert len(registry.registry_hash) == 64
    assert [entry.name for entry in registry.components] == [
        "simplicio-loop", "simplicio-mapper",
    ]


def test_stack_diagnosis_blocks_duplicate_binary_and_matrix_mismatch(tmp_path):
    registry = _stack_registry()
    loop_binary = tmp_path / "loop"
    mapper_a = tmp_path / "mapper-a"
    mapper_b = tmp_path / "mapper-b"
    loop_binary.write_bytes(b"loop")
    mapper_a.write_bytes(b"mapper-a")
    mapper_b.write_bytes(b"mapper-b")
    loop = observe_component(
        "simplicio-loop", "1.0.0", loop_binary, capabilities=("orchestrator",)
    )
    mapper_a_observation = observe_component(
        "simplicio-mapper", "2.0.0", mapper_a, capabilities=("map",)
    )
    mapper_b_observation = observe_component(
        "simplicio-mapper", "1.0.0", mapper_b, capabilities=("map",)
    )

    diagnosis = diagnose_stack(
        [loop, mapper_a_observation, mapper_b_observation], registry, "standalone"
    )

    assert diagnosis.status == "BLOCKED"
    assert {issue.code for issue in diagnosis.issues} == {
        "duplicate_binary", "version_incompatible", "compatibility_mismatch",
    }
    duplicate = next(issue for issue in diagnosis.issues if issue.code == "duplicate_binary")
    assert "mapper-a" in duplicate.details[0][1]
    assert "remove the shadowed binary" in duplicate.action


def test_stack_diagnosis_reports_partial_upgrade_against_frozen_lock(tmp_path):
    registry = _stack_registry()
    loop_binary = tmp_path / "loop"
    mapper_binary = tmp_path / "mapper"
    loop_binary.write_bytes(b"loop-v1")
    mapper_binary.write_bytes(b"mapper-v1")
    loop = observe_component(
        "simplicio-loop", "1.0.0", loop_binary, capabilities=("orchestrator",)
    )
    mapper = observe_component(
        "simplicio-mapper", "1.0.0", mapper_binary, capabilities=("map",)
    )
    lock = StackLock.create([loop, mapper], "standalone", run_id="run-1")

    mapper_binary.write_bytes(b"mapper-v2")
    upgraded = observe_component(
        "simplicio-mapper", "1.1.0", mapper_binary, capabilities=("map",)
    )
    diagnosis = diagnose_stack(
        [loop, upgraded], registry, "standalone", locked=lock
    )

    assert diagnosis.status == "BLOCKED"
    assert any(issue.code == "partial_upgrade" for issue in diagnosis.issues)




def test_stack_cli_registry_allows_standalone(tmp_path, capsys):
    loop_binary = tmp_path / "simplicio-loop"
    mapper_binary = tmp_path / "simplicio-mapper"
    loop_binary.write_bytes(b"loop")
    mapper_binary.write_bytes(b"mapper")
    components = tmp_path / "components.json"
    components.write_text(
        json.dumps({
            "components": [
                {
                    "name": "simplicio-loop",
                    "version": "1.0.0",
                    "executable": str(loop_binary),
                    "capabilities": ["orchestrator"],
                },
                {
                    "name": "simplicio-mapper",
                    "version": "1.0.0",
                    "executable": str(mapper_binary),
                    "capabilities": ["map"],
                },
            ]
        }),
        encoding="utf-8",
    )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(_stack_registry().to_dict()), encoding="utf-8")
    lock_path = tmp_path / "stack-lock.json"

    assert main([
        "stack", "lock", "--components", str(components), "--route", "standalone",
        "--registry", str(registry), "--output", str(lock_path),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "LOCKED"
    assert lock_path.is_file()


def test_stack_cli_registry_blocks_duplicate_before_writing_lock(tmp_path, capsys):
    loop_binary = tmp_path / "simplicio-loop"
    mapper_a = tmp_path / "mapper-a"
    mapper_b = tmp_path / "mapper-b"
    for path, content in (
        (loop_binary, b"loop"),
        (mapper_a, b"mapper-a"),
        (mapper_b, b"mapper-b"),
    ):
        path.write_bytes(content)
    components = tmp_path / "components.json"
    components.write_text(
        json.dumps({
            "components": [
                {
                    "name": "simplicio-loop",
                    "version": "1.0.0",
                    "executable": str(loop_binary),
                    "capabilities": ["orchestrator"],
                },
                {
                    "name": "simplicio-mapper",
                    "version": "2.0.0",
                    "executable": str(mapper_a),
                    "capabilities": ["map"],
                },
                {
                    "name": "simplicio-mapper",
                    "version": "1.0.0",
                    "executable": str(mapper_b),
                    "capabilities": ["map"],
                },
            ]
        }),
        encoding="utf-8",
    )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(_stack_registry().to_dict()), encoding="utf-8")
    lock_path = tmp_path / "stack-lock.json"

    assert main([
        "stack", "lock", "--components", str(components), "--route", "standalone",
        "--registry", str(registry), "--output", str(lock_path),
    ]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "stack_compatibility_blocked"
    assert payload["diagnostics"]["status"] == "BLOCKED"
    assert not lock_path.exists()


def test_discovered_stack_has_only_loop_mapper_and_cli(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_STACK_COMPONENTS_FILE", raising=False)
    names = [item.name for item in stack_lock_mod.discover_installed_components()]
    assert "simplicio-fast" not in names
    assert "simplicio-runtime" not in names
    assert {"simplicio-loop", "simplicio-mapper", "simplicio-cli"} <= set(names)
