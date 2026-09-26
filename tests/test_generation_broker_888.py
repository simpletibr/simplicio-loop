from __future__ import annotations

import json
import hashlib
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from simplicio_loop.checkpoint_lifecycle import CheckpointLifecycle, LifecycleError
from simplicio_loop.generation_broker import CanonicalGeneration
from simplicio_loop.generation_broker import GenerationBroker, _digest
from simplicio_loop.generation_broker_cli import _load, cli_main
from simplicio_loop.map_service import MapServiceRegistry, RepositoryIdentity


def broker(tmp_path: Path) -> tuple[GenerationBroker, str, CanonicalGeneration]:
    base = tmp_path / "base"
    base.mkdir()
    registry = MapServiceRegistry()
    identity = RepositoryIdentity(
        repository="owner/project", canonical_root=str(base), base_sha="abc"
    )
    identity_key = registry.register(identity)
    generation = CanonicalGeneration("generation-1", "ctx", "abc", "plan", "receipt")
    lifecycle = CheckpointLifecycle(
        tmp_path / "runs",
        task_id="task-888",
        attempt_id="attempt-1",
        source_commit="abc",
        mapper_generation=generation.generation,
        base_path=base,
    )
    return GenerationBroker(registry, lifecycle), identity_key, generation


def test_candidates_share_canonical_cache_but_keep_isolated_overlays(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)
    first = service.bind(
        identity_key,
        tree_hash="tree",
        files=["b.py", "a.py"],
        candidate_id="a",
        generation=generation,
    )
    second = service.bind(
        identity_key,
        tree_hash="tree",
        files=["a.py", "b.py"],
        candidate_id="b",
        generation=generation,
    )

    assert first.canonical_cache_key == second.canonical_cache_key
    assert first.overlay_path != second.overlay_path
    assert first.receipt_hash != second.receipt_hash
    marker = json.loads((Path(first.overlay_path) / "overlay.json").read_text())
    assert marker["base_read_only"] is True
    assert first.mapper_generation == generation.generation
    assert first.schema == "simplicio.loop.generation-binding/v1"
    assert service.inspect("a") == first
    assert service.status()["metrics"]["cache_misses"] == 1
    assert service.status()["metrics"]["cache_hits"] == 1
    manifest_path = next((service.lifecycle.attempt / "generation-manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text())
    assert manifest["canonical_cache_key"] == first.canonical_cache_key
    assert manifest["schema"] == "simplicio.loop.generation-binding/v1"


def test_stale_generation_fails_before_overlay_creation(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)
    stale = CanonicalGeneration("generation-2", "ctx", "abc", "plan", "receipt")

    with pytest.raises(LifecycleError, match="stale canonical generation"):
        service.bind(
            identity_key,
            tree_hash="tree",
            files=[],
            candidate_id="stale",
            generation=stale,
        )

    assert not service.lifecycle.overlays.exists()
    assert generation.generation == service.lifecycle.mapper_generation


@pytest.mark.parametrize("candidate_id", ["../escape", "a/b", "a\\b", "..", "", " a"])
def test_candidate_paths_fail_closed_at_broker_and_lifecycle(tmp_path: Path, candidate_id: str):
    service, identity_key, generation = broker(tmp_path)
    with pytest.raises(LifecycleError, match="unsafe candidate_id"):
        service.bind(
            identity_key,
            tree_hash="tree",
            files=[],
            candidate_id=candidate_id,
            generation=generation,
        )
    with pytest.raises(LifecycleError, match="unsafe candidate_id"):
        service.lifecycle.create_overlay(candidate_id)


def test_concurrent_bindings_share_generation_without_overlay_collisions(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)

    def bind(candidate_id: str):
        return service.bind(
            identity_key,
            tree_hash="tree",
            files=["a.py"],
            candidate_id=candidate_id,
            generation=generation,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        bindings = list(executor.map(bind, (f"candidate-{index}" for index in range(20))))

    assert len({item.canonical_cache_key for item in bindings}) == 1
    assert len({item.overlay_path for item in bindings}) == len(bindings)
    assert all(Path(item.overlay_path).is_dir() for item in bindings)
    assert service.status()["canonical_bases"] == 1
    assert service.status()["metrics"]["cache_misses"] == 1


def test_same_candidate_is_idempotent_and_fenced(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)

    def bind():
        return service.bind(
            identity_key, tree_hash="tree", files=["a.py"], candidate_id="same", generation=generation
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        bindings = list(executor.map(lambda _: bind(), range(20)))
    assert len({item.receipt_hash for item in bindings}) == 1
    with pytest.raises(LifecycleError, match="fence mismatch"):
        service.bind(
            identity_key, tree_hash="changed", files=[], candidate_id="same", generation=generation
        )


def test_bind_and_gc_are_atomic(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)
    service.bind(
        identity_key, tree_hash="tree", files=[], candidate_id="old", generation=generation
    )
    service.lifecycle.checkpoint("old", "candidate", "CANCELLED")
    service.lifecycle.cancel(["old"], reason="done")
    service.release("old")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_binding = executor.submit(
            service.bind,
            identity_key,
            tree_hash="tree",
            files=[],
            candidate_id="new",
            generation=generation,
        )
        future_gc = executor.submit(service.gc, retention_ns=0, now_ns=10**30, apply=True)
    assert service.inspect("new") == future_binding.result()
    assert future_gc.result()["removed"] == ["old"]


def test_gc_preserves_pinned_overlay_then_reclaims_cancelled_candidate(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)
    binding = service.bind(
        identity_key,
        tree_hash="tree",
        files=["a.py"],
        candidate_id="a",
        generation=generation,
    )
    service.lifecycle.checkpoint("a", "candidate", "CANCELLED")
    service.lifecycle.cancel(["a"], reason="lost")
    service.lifecycle.lease("a", expires_ns=200)

    assert service.gc(retention_ns=0, now_ns=100, apply=True)["removed"] == []
    assert service.gc(retention_ns=0, now_ns=300, apply=True)["removed"] == ["a"]
    assert not Path(binding.overlay_path).exists()


def test_corrupt_manifest_fails_inspect_and_doctor_reports_it(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)
    binding = service.bind(
        identity_key, tree_hash="tree", files=[], candidate_id="a", generation=generation
    )
    path = Path(binding.overlay_path) / "generation-binding.json"
    value = json.loads(path.read_text())
    value["tree_hash"] = "tampered"
    path.write_text(json.dumps(value))
    service._bindings.clear()

    with pytest.raises(LifecycleError, match="receipt mismatch"):
        service.inspect("a")
    assert service.doctor()["healthy"] is False
    assert service.doctor()["corrupt"] == ["a"]


def test_reconcile_recovers_after_coordinator_restart_and_pin_release(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)
    binding = service.bind(
        identity_key, tree_hash="tree", files=[], candidate_id="a", generation=generation
    )
    restarted = GenerationBroker(service.registry, service.lifecycle)
    assert restarted.reconcile()["recovered"] == ["a"]
    pinned = restarted.pin("a", expires_ns=binding.lease_expires_ns + 1)
    assert pinned.receipt_hash != binding.receipt_hash
    restarted.release("a")
    assert restarted.inspect("a").lease_expires_ns == 0
    assert restarted.status()["events"][-1]["event"] == "release"


def test_cross_worktree_identity_fails_before_overlay(tmp_path: Path):
    service, _, generation = broker(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    identity_key = service.registry.register(
        RepositoryIdentity("owner/project", str(other), base_sha="abc")
    )
    with pytest.raises(LifecycleError, match="cross-worktree"):
        service.bind(
            identity_key, tree_hash="tree", files=[], candidate_id="a", generation=generation
        )
    assert not service.lifecycle.overlays.exists()


def test_promotion_preserves_active_pin_and_records_event(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)
    binding = service.bind(
        identity_key, tree_hash="tree", files=[], candidate_id="a", generation=generation
    )
    promoted = CanonicalGeneration("generation-2", "ctx2", "def", "plan2", "receipt2")
    assert service.promote(promoted)["generation"] == "generation-2"
    assert service.inspect("a") == binding
    assert service.status()["promoted_generation"] == "generation-2"
    event = service.event("mapper_background_refresh", identity_key=identity_key)
    assert event["event"] == "mapper_background_refresh"
    assert service.inspect("a") == binding
    next_binding = service.bind(
        identity_key, tree_hash="tree-2", files=[], candidate_id="b", generation=promoted
    )
    assert next_binding.mapper_generation == "generation-2"


def test_trusted_anchor_rejects_rehashed_repository_tamper(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)
    binding = service.bind(
        identity_key, tree_hash="tree", files=[], candidate_id="a", generation=generation
    )
    path = Path(binding.overlay_path) / "generation-binding.json"
    value = json.loads(path.read_text())
    value["repository_base_sha"] = "attacker"
    payload = dict(value)
    payload.pop("receipt_hash")
    value["receipt_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps(value))
    service._bindings.clear()
    with pytest.raises(LifecycleError, match="trusted-anchor mismatch"):
        service.inspect("a")


@pytest.mark.parametrize("field", ["task_id", "attempt_id"])
def test_lifecycle_rejects_unsafe_path_identity(tmp_path: Path, field: str):
    kwargs = {"task_id": "task", "attempt_id": "attempt"}
    kwargs[field] = "../escape"
    with pytest.raises(LifecycleError, match=f"unsafe {field}"):
        CheckpointLifecycle(
            tmp_path / "runs",
            source_commit="abc",
            mapper_generation="generation",
            base_path=tmp_path,
            **kwargs,
        )


def test_lifecycle_rejects_unsafe_shard(tmp_path: Path):
    service, _, _ = broker(tmp_path)
    with pytest.raises(LifecycleError, match="unsafe shard_id"):
        service.lifecycle.checkpoint("a", "../escape", "PLANNED")


def test_json_cli_uses_authoritative_broker_for_inspect_pin_release(tmp_path: Path, capsys):
    service, identity_key, generation = broker(tmp_path)
    service.bind(
        identity_key, tree_hash="tree", files=[], candidate_id="a", generation=generation
    )
    attempt = str(service.lifecycle.attempt)
    assert cli_main(["inspect", "--attempt-dir", attempt, "--candidate-id", "a"]) == 0
    assert json.loads(capsys.readouterr().out)["candidate_id"] == "a"
    assert cli_main([
        "pin", "--attempt-dir", attempt, "--candidate-id", "a", "--expires-ns", "999"
    ]) == 0
    assert json.loads(capsys.readouterr().out)["lease_expires_ns"] == 999
    assert cli_main(["release", "--attempt-dir", attempt, "--candidate-id", "a"]) == 0
    assert json.loads(capsys.readouterr().out)["lease_expires_ns"] == 0


def test_first_bind_rejects_source_provenance_mismatch(tmp_path: Path):
    service, identity_key, _ = broker(tmp_path)
    mismatch = CanonicalGeneration("generation-1", "ctx", "different", "plan", "receipt")
    with pytest.raises(LifecycleError, match="provenance mismatch"):
        service.bind(
            identity_key, tree_hash="tree", files=[], candidate_id="a", generation=mismatch
        )


def test_restart_rolls_back_prepared_dry_run_gc_and_doctor_finds_orphan(tmp_path: Path):
    service, _, _ = broker(tmp_path)
    transaction = {
        "schema": "simplicio.loop.generation-binding/v1",
        "state": "PREPARED",
        "created_ns": 1,
        "retention_ns": 0,
        "now_ns": 2,
        "apply": False,
    }
    transaction["receipt_hash"] = _digest(transaction)
    journal = service.lifecycle.attempt / "generation-gc-journal.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps(transaction))
    (service.lifecycle.overlays / "orphan").mkdir(parents=True)
    restarted = GenerationBroker(service.registry, service.lifecycle)
    assert json.loads(journal.read_text())["state"] == "ROLLED_BACK"
    result = restarted.doctor()
    assert result["healthy"] is False
    assert result["overlay_orphans"] == ["orphan"]


def test_gc_recovery_completes_partially_deleted_candidate(tmp_path: Path):
    service, identity_key, generation = broker(tmp_path)
    binding = service.bind(
        identity_key, tree_hash="tree", files=[], candidate_id="a", generation=generation
    )
    service.lifecycle.checkpoint("a", "candidate", "CANCELLED")
    service.lifecycle.cancel(["a"], reason="done")
    service.release("a")
    shutil.rmtree(binding.overlay_path)
    transaction = {
        "schema": "simplicio.loop.generation-binding/v1",
        "state": "PREPARED",
        "created_ns": 1,
        "retention_ns": 0,
        "now_ns": 10**30,
        "apply": True,
    }
    transaction["receipt_hash"] = _digest(transaction)
    journal = service.lifecycle.attempt / "generation-gc-journal.json"
    journal.write_text(json.dumps(transaction))
    GenerationBroker(service.registry, service.lifecycle)
    assert json.loads(journal.read_text())["state"] == "COMMITTED"
    assert not (service.lifecycle.cancellations / "a.json").exists()
    assert not (service.lifecycle.leases / "a.json").exists()
    assert GenerationBroker(service.registry, service.lifecycle).doctor()["healthy"] is True


def test_no_binding_promotion_persists_and_fresh_cli_reloads(tmp_path: Path, capsys):
    service, identity_key, _ = broker(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    service.registry.restore_identity(
        RepositoryIdentity("owner/unrelated", str(unrelated), base_sha="abc")
    )
    promoted = CanonicalGeneration("generation-2", "ctx2", "def", "plan2", "receipt2")
    service.promote(promoted)
    attempt = str(service.lifecycle.attempt)
    assert cli_main(["status", "--attempt-dir", attempt]) == 0
    assert json.loads(capsys.readouterr().out)["promoted_generation"] == "generation-2"
    reloaded = _load(service.lifecycle.attempt.resolve())
    binding = reloaded.bind(
        identity_key, tree_hash="tree-2", files=[], candidate_id="first", generation=promoted
    )
    assert binding.source_commit == "def"


def test_no_binding_promotion_fails_closed_for_ambiguous_lifecycle_identity(tmp_path: Path):
    service, _, _ = broker(tmp_path)
    service.registry.restore_identity(
        RepositoryIdentity("other/project", str(service.lifecycle.base_path), base_sha="abc")
    )
    promoted = CanonicalGeneration("generation-2", "ctx2", "def", "plan2", "receipt2")
    with pytest.raises(LifecycleError, match="requires one lifecycle repository identity"):
        service.promote(promoted)


def test_reloaded_zero_binding_broker_can_promote_twice_then_first_bind(tmp_path: Path):
    service, identity_key, _ = broker(tmp_path)
    second = CanonicalGeneration("generation-2", "ctx2", "def", "plan2", "receipt2")
    service.promote(second)
    reloaded = _load(service.lifecycle.attempt.resolve())
    third = CanonicalGeneration("generation-3", "ctx3", "ghi", "plan3", "receipt3")
    reloaded.promote(third)
    final = _load(service.lifecycle.attempt.resolve())
    binding = final.bind(
        identity_key, tree_hash="tree-3", files=[], candidate_id="first", generation=third
    )
    assert binding.source_commit == "ghi"
    assert binding.mapper_generation == "generation-3"
