from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import json
import multiprocessing

import pytest

from simplicio_fast.validation_cache import ValidationCache, ValidationCacheError, ValidationKey, ValidationResult, _canonical, _digest


def key() -> ValidationKey:
    return ValidationKey("sha256:source", "sha256:lock", "python-3.14", ("pytest", "tests/a.py"), (("CI", "1"),), generation="g1")


def _save_cache_from_process(arguments: tuple[str, int]) -> bool:
    path, index = arguments
    cache = ValidationCache()
    cache.put(
        ValidationKey(
            f"sha256:source-{index}",
            "sha256:lock",
            "python-3.14",
            ("pytest",),
            generation=f"g{index}",
        ),
        status="pass",
        result={"index": index},
    )
    cache.save(path)
    return True


def test_validation_key_is_content_addressed_and_cache_respects_freshness() -> None:
    first = key()
    second = key()
    assert first.digest == second.digest
    cache = ValidationCache()
    stale = cache.put(first, status="pass", result={"ok": True}, fresh=False)
    assert cache.get(second) == stale
    assert cache.get(second, require_fresh=True) is None
    fresh = cache.put(first, status="pass", result={"ok": True}, fresh=True)
    assert cache.get(second, require_fresh=True) == fresh


def test_validation_key_snapshots_mutable_command_and_environment_inputs() -> None:
    command = ["pytest", "tests/a.py"]
    environment = [["CI", "1"]]
    item = ValidationKey("sha256:source", "sha256:lock", "python-3.14", command, environment)
    digest = item.digest

    command.append("--external")
    environment[0][1] = "mutated"
    environment.append(["NEW", "value"])

    assert item.command == ("pytest", "tests/a.py")
    assert item.environment == (("CI", "1"),)
    assert item.digest == digest


def test_affected_selection_is_deterministic_and_bounded() -> None:
    result = ValidationCache().affected(("h2", "h1"), {"h1": ("test/z", "test/a"), "h2": ("test/b",)}, max_tests=2)
    assert result["tests"] == ["test/a", "test/b"]
    assert result["complete"] is False
    assert result["truncation_reasons"] == ["test_budget"]


def test_invalid_cache_inputs_fail_closed() -> None:
    with pytest.raises(ValidationCacheError, match="cache_key_required_missing"):
        ValidationKey("", "lock", "tool", ("test",)).to_dict()
    with pytest.raises(ValidationCacheError, match="selection_budget_invalid"):
        ValidationCache().affected(("h",), {}, max_tests=0)
    with pytest.raises(ValidationCacheError, match="changed_handles_invalid"):
        ValidationCache().affected(("h", 1), {})
    with pytest.raises(ValidationCacheError, match="test_values_invalid"):
        ValidationCache().affected(("h",), {"h": ("test/a", 1)})
    with pytest.raises(ValidationCacheError, match="gc_generations_invalid"):
        ValidationCache().gc(keep_generations=(True,))


def test_validation_cache_persistence_is_deterministic_and_tamper_evident(tmp_path) -> None:
    cache = ValidationCache()
    cache.put(key(), status="pass", result={"ok": True}, evidence=("receipt:1",))
    path = tmp_path / "cache.json"
    receipt = cache.save(path)
    restored = ValidationCache.load(path)
    assert receipt["entries"] == 1
    assert restored.get(key()) == cache.get(key())
    path.write_text(path.read_text(encoding="utf-8").replace("receipt:1", "receipt:2"), encoding="utf-8")
    with pytest.raises(ValidationCacheError, match="cache_digest_mismatch"):
        ValidationCache.load(path)


def test_validation_cache_requires_provenance_for_reusable_verified_hits() -> None:
    cache = ValidationCache()
    item = cache.put(key(), status="pass", result={"ok": True}, fresh=True)
    assert item.verified is False
    assert cache.get(key(), reusable=True) is None
    verified = cache.put(
        key(), status="pass", result={"ok": True}, fresh=True,
        verified=True, provenance=("runtime:receipt:1",), evidence=("receipt:1",),
    )
    assert cache.get(key(), reusable=True) == verified


def test_validation_cache_demotes_conflicting_result_and_explains_affected_tests() -> None:
    cache = ValidationCache()
    cache.put(key(), status="pass", result={"ok": True}, fresh=True, verified=True, provenance=("r1",))
    conflicting = cache.put(key(), status="pass", result={"ok": False}, fresh=True, verified=True, provenance=("r2",))
    assert conflicting.nondeterministic is True
    assert cache.get(key(), reusable=True) is None
    affected = cache.affected(("h1",), {"h1": ("test/a", "test/a")})
    assert affected["reason_paths"] == [{"handle": "h1", "tests": ["test/a"], "reason": "changed_handle"}]


def test_validation_cache_gc_is_bounded_and_respects_leases() -> None:
    cache = ValidationCache()
    retained = key()
    evictable = ValidationKey(
        "sha256:other", "sha256:lock", "python-3.14", ("pytest",), generation="g2"
    )
    cache.put(retained, status="pass", result={"ok": True})
    cache.put(evictable, status="pass", result={"ok": True})
    cache.acquire_lease(retained, "lease-1")
    plan = cache.gc(keep_generations=("g1",), dry_run=True)
    assert plan["status"] == "planned"
    assert evictable.digest in plan["candidates"]
    assert retained.digest not in plan["candidates"]
    applied = cache.gc(keep_generations=("g1",), dry_run=False)
    assert applied["removed"] == [evictable.digest]
    assert cache.get(retained) is not None
    assert cache.get(evictable) is None
    cache.release_lease(retained, "lease-1")
    with pytest.raises(ValidationCacheError, match="lease_id_invalid"):
        cache.acquire_lease(retained, "bad/lease")
    with pytest.raises(ValidationCacheError, match="gc_budget_invalid"):
        cache.gc(max_entries=0)


def test_validation_cache_serializes_concurrent_publication_and_save(tmp_path) -> None:
    cache = ValidationCache()
    keys = [
        ValidationKey(
            f"sha256:source-{index}", "sha256:lock", "python-3.14", ("pytest",),
            generation=f"g{index}",
        )
        for index in range(24)
    ]

    def publish(item: tuple[int, ValidationKey]) -> None:
        index, item_key = item
        cache.put(item_key, status="pass", result={"index": index})
        cache.acquire_lease(item_key, f"lease-{index}")
        cache.gc(max_entries=1, dry_run=True)
        cache.release_lease(item_key, f"lease-{index}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(publish, enumerate(keys)))

    receipt = cache.save(tmp_path / "concurrent-cache.json")
    assert receipt["entries"] == len(keys)
    assert len(ValidationCache.load(tmp_path / "concurrent-cache.json")._entries) == len(keys)


def test_validation_cache_save_is_cross_process_atomic(tmp_path) -> None:
    path = tmp_path / "cross-process-cache.json"
    context = multiprocessing.get_context("spawn")
    arguments = [(str(path), index) for index in range(4)]
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as pool:
        assert list(pool.map(_save_cache_from_process, arguments)) == [True] * 4

    restored = ValidationCache.load(path)
    assert len(restored._entries) == 1
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))


def test_validation_cache_failed_replace_preserves_previous_generation(tmp_path, monkeypatch) -> None:
    path = tmp_path / "recovery-cache.json"
    original = ValidationCache()
    original.put(key(), status="pass", result={"generation": "old"})
    original.save(path)

    replacement = ValidationCache()
    replacement.put(
        ValidationKey("sha256:new", "sha256:lock", "python-3.14", ("pytest",), generation="g2"),
        status="pass",
        result={"generation": "new"},
    )

    def fail_replace(*_arguments: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("simplicio_fast.validation_cache.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        replacement.save(path)

    assert ValidationCache.load(path).get(key()).result_digest == original.get(key()).result_digest
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))


def test_validation_cache_contract_boundaries_and_lease_lifecycle(tmp_path) -> None:
    with pytest.raises(ValidationCacheError, match="cache_key_not_json"):
        _canonical({"bad": object()})
    with pytest.raises(ValidationCacheError, match="cache_environment_invalid"):
        ValidationKey("source", "lock", "tool", ("test",), (("CI", 1),)).to_dict()
    with pytest.raises(ValidationCacheError, match="result_status_invalid"):
        ValidationResult("key", "unknown", "result", ("test",), True)
    with pytest.raises(ValidationCacheError, match="result_digest_invalid"):
        ValidationResult("", "pass", "result", ("test",), True)
    with pytest.raises(ValidationCacheError, match="result_provenance_required"):
        ValidationResult("key", "pass", "result", ("test",), True, verified=True)
    with pytest.raises(ValidationCacheError, match="cache_key_optional_field_invalid"):
        ValidationKey("source", "lock", "tool", ("test",), config_digest=1).to_dict()
    result = ValidationResult(
        "key", "pass", "result", ["test"], True, ["evidence"],
        provenance=["receipt"], verified=True,
    )
    assert result.command == ("test",)
    assert result.evidence == ("evidence",)
    assert result.provenance == ("receipt",)

    cache = ValidationCache()
    missing = ValidationKey("missing", "lock", "tool", ("test",))
    with pytest.raises(ValidationCacheError, match="cache_entry_missing"):
        cache.acquire_lease(missing, "lease")
    with pytest.raises(ValidationCacheError, match="lease_id_invalid"):
        cache.release_lease(missing, "")
    cache.put(key(), status="pass", result={"ok": True})
    with pytest.raises(ValidationCacheError, match="result_provenance_required"):
        cache.put(key(), status="pass", result={"ok": True}, verified=True)
    cache.acquire_lease(key(), "lease-a")
    cache.acquire_lease(key(), "lease-b")
    cache.release_lease(key(), "lease-a")
    assert key().digest in cache._leases
    cache.release_lease(key(), "lease-b")
    assert key().digest not in cache._leases

    invalid = [
        ("{", "cache_document_invalid"),
        ("[]", "cache_document_invalid"),
        ('{"body":{"schema":"wrong"},"cache_sha256":"x"}', "cache_schema_unsupported"),
    ]
    for index, (content, reason) in enumerate(invalid):
        path = tmp_path / f"invalid-{index}.json"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ValidationCacheError, match=reason):
            ValidationCache.load(path)
    valid_path = tmp_path / "valid.json"
    cache.save(valid_path)
    document = json.loads(valid_path.read_text(encoding="utf-8"))
    document["body"]["entries"] = [1]
    document["cache_sha256"] = _digest(document["body"])
    valid_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationCacheError, match="cache_entries_invalid"):
        ValidationCache.load(valid_path)
    document["body"]["entries"] = [{"key_digest": "x", "status": "pass", "result_digest": "x"}]
    document["cache_sha256"] = _digest(document["body"])
    valid_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationCacheError, match="cache_entry_invalid"):
        ValidationCache.load(valid_path)
    document["body"]["entries"] = "not-a-list"
    document["cache_sha256"] = _digest(document["body"])
    valid_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationCacheError, match="cache_entries_invalid"):
        ValidationCache.load(valid_path)


def test_validation_cache_load_rejects_type_coercion_and_duplicate_entries(tmp_path) -> None:
    cache = ValidationCache()
    cache.put(key(), status="pass", result={"ok": True})
    path = tmp_path / "poisoned.json"
    cache.save(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["body"]["entries"][0]["fresh"] = "false"
    document["cache_sha256"] = _digest(document["body"])
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationCacheError, match="cache_entry_invalid"):
        ValidationCache.load(path)
    cache.save(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["body"]["entries"].append(dict(document["body"]["entries"][0]))
    document["cache_sha256"] = _digest(document["body"])
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationCacheError, match="cache_duplicate_entry"):
        ValidationCache.load(path)


def test_validation_cache_rejects_optional_key_types_and_string_sequence_coercion() -> None:
    with pytest.raises(ValidationCacheError, match="cache_key_optional_field_invalid"):
        ValidationKey(
            "source", "lock", "tool", ("pytest",), config_digest=1  # type: ignore[arg-type]
        ).to_dict()
    cache = ValidationCache()
    with pytest.raises(ValidationCacheError, match="result_command_invalid"):
        cache.put(key(), status="pass", result={}, command="pytest")  # type: ignore[arg-type]
    with pytest.raises(ValidationCacheError, match="result_evidence_invalid"):
        cache.put(key(), status="pass", result={}, evidence="receipt:1")  # type: ignore[arg-type]
