import importlib.metadata
import json
import sys
import types
from pathlib import Path

import pytest

from simplicio_loop.store_adapter import (
    StorageRoute,
    StorageRouter,
    StoreAdapterError,
    probe_mapper,
    storage_doctor,
)


def fake_mapper(monkeypatch, version="0.26.9"):
    module = types.ModuleType("simplicio_mapper.store")
    module.OperationsStore = object
    module.inspect_store = object
    module.resolve_store_location = object
    package = types.ModuleType("simplicio_mapper")
    package.__version__ = version
    monkeypatch.setitem(sys.modules, "simplicio_mapper", package)
    monkeypatch.setitem(sys.modules, "simplicio_mapper.store", module)
    return module


def test_mapper_route_is_the_default(monkeypatch):
    # The legacy SQLite hookwall refuses to write (LEGACY_HOOKWALL_READ_ONLY),
    # so a legacy default made every fresh run fail at the first effect.
    fake_mapper(monkeypatch)
    report = storage_doctor()
    assert report["status"] == "READY"
    assert report["selected"] == "mapper"
    assert report["writer_authority"] == "mapper-store"
    assert report["effects_attempted"] is False


def test_runner_effect_journal_defaults_to_mapper(monkeypatch):
    from simplicio_loop import runner

    monkeypatch.delenv("SIMPLICIO_STORAGE_ROUTE", raising=False)
    assert runner._mapper_journal_enabled() is True
    monkeypatch.setenv("SIMPLICIO_STORAGE_ROUTE", "legacy")
    assert runner._mapper_journal_enabled() is False


def test_runner_hookwall_route_uses_legacy_only_when_requested(monkeypatch, tmp_path):
    from simplicio_loop import runner

    selected = []

    class FakeLedger:
        def __init__(self, database, **kwargs):
            selected.append((database, kwargs))

    monkeypatch.setenv("SIMPLICIO_STORAGE_ROUTE", "legacy")
    monkeypatch.setattr(runner, "HookwallEffectLedger", FakeLedger)
    runner._hookwall_ledger(tmp_path)
    assert selected == [(tmp_path / ".simplicio" / "orchestrator" / "hookwall.sqlite3", {})]


def test_mapper_route_selects_installed_capabilities_without_creating_state(
    monkeypatch, tmp_path
):
    fake_mapper(monkeypatch)
    report = storage_doctor(requested="mapper", data_dir=tmp_path / "data")
    assert report["status"] == "READY"
    assert report["selected"] == "mapper"
    assert not (tmp_path / "data").exists()


def test_missing_mapper_blocks_before_first_write(monkeypatch):
    monkeypatch.setitem(sys.modules, "simplicio_mapper", None)
    monkeypatch.setitem(sys.modules, "simplicio_mapper.store", None)
    router = StorageRouter(requested="mapper")
    result = router.select()
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "MAPPER_NOT_INSTALLED"
    with pytest.raises(StoreAdapterError, match="MAPPER_NOT_INSTALLED"):
        router.freeze("claim")


def test_installed_mapper_without_store_api_is_incompatible(monkeypatch):
    package = types.ModuleType("simplicio_mapper")
    package.__version__ = "0.26.9"
    monkeypatch.setitem(sys.modules, "simplicio_mapper", package)
    monkeypatch.setitem(sys.modules, "simplicio_mapper.store", None)
    report = probe_mapper()
    assert report.status == "incompatible"
    assert report.reason_code == "MAPPER_API_INCOMPATIBLE"
    assert report.mapper_version == "0.26.9"


def test_old_mapper_and_missing_capability_fail_closed(monkeypatch):
    fake_mapper(monkeypatch, version="0.25.9")
    assert probe_mapper().reason_code == "MAPPER_VERSION_TOO_OLD"
    fake_mapper(monkeypatch)
    assert (
        probe_mapper(required_capabilities=("sqlite-vec",)).reason_code
        == "MAPPER_CAPABILITY_MISSING"
    )


def test_shadow_route_freezes_and_rejects_fallback(monkeypatch):
    fake_mapper(monkeypatch)
    router = StorageRouter(requested=StorageRoute.SHADOW)
    assert router.select()["selected"] == "shadow"
    router.freeze("first_write")
    with pytest.raises(StoreAdapterError, match="ROUTE_FROZEN_AFTER_FIRST_WRITE"):
        router.select_again("legacy")
    receipt = router.receipt()
    assert receipt["schema"] == "simplicio.loop-store-route-receipt/v1"
    assert receipt["immutable"] is True
    assert receipt["receipt_hash"].startswith("sha256:")


def test_frozen_route_receipt_rejects_environment_drift(monkeypatch, tmp_path):
    from simplicio_loop import runner

    monkeypatch.setenv("SIMPLICIO_STORAGE_ROUTE", "legacy")
    receipt = runner._freeze_storage_route(tmp_path, "run-1")
    assert receipt["selected"] == "legacy"
    assert runner._verify_storage_route(tmp_path)["receipt_hash"] == receipt["receipt_hash"]
    monkeypatch.setenv("SIMPLICIO_STORAGE_ROUTE", "mapper")
    with pytest.raises(StoreAdapterError, match="ROUTE_FROZEN_AFTER_FIRST_WRITE"):
        runner._verify_storage_route(tmp_path)


def test_mapper_route_freezes_only_with_verified_installed_api(monkeypatch, tmp_path):
    from simplicio_loop import runner

    fake_mapper(monkeypatch)
    monkeypatch.setenv("SIMPLICIO_STORAGE_ROUTE", "mapper")
    receipt = runner._freeze_storage_route(tmp_path, "run-2")
    assert receipt["selected"] == "mapper"
    assert runner._verify_storage_route(tmp_path)["selected"] == "mapper"


def test_mapper_route_never_falls_back_when_api_is_missing(monkeypatch, tmp_path):
    from simplicio_loop import runner

    monkeypatch.setenv("SIMPLICIO_STORAGE_ROUTE", "mapper")
    monkeypatch.setitem(sys.modules, "simplicio_mapper", None)
    monkeypatch.setitem(sys.modules, "simplicio_mapper.store", None)
    with pytest.raises(StoreAdapterError, match="MAPPER_NOT_INSTALLED"):
        runner._freeze_storage_route(tmp_path, "run-3")
    assert not (tmp_path / runner.STORAGE_ROUTE_RECEIPT).exists()


def test_select_again_is_allowed_before_freeze(monkeypatch):
    fake_mapper(monkeypatch)
    router = StorageRouter(requested="legacy")
    assert router.select()["selected"] == "legacy"
    assert router.select_again("mapper")["selected"] == "mapper"


def test_invalid_route_and_invalid_root_fail_closed():
    with pytest.raises(StoreAdapterError, match="STORAGE_ROUTE_INVALID"):
        StorageRouter(requested="automatic")
    with pytest.raises(StoreAdapterError, match="filesystem root"):
        storage_doctor(data_dir="/")


def test_cli_surface_and_json_contract(monkeypatch, capsys):
    fake_mapper(monkeypatch)
    from simplicio_loop.cli import main

    assert main(["doctor", "--storage", "--route", "mapper", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.loop-store-adapter/v1"
    assert main(["inspect", "--storage", "--route", "legacy", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["selected"] == "legacy"


def test_versioned_route_fixtures_match_the_schema():
    root = Path(__file__).parents[1]
    schema = json.loads(
        (
            root / "simplicio_loop/_contracts/mapper-store/v1/route-receipt.schema.json"
        ).read_text()
    )
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema)
    for fixture in ("route-legacy.json", "route-blocked.json"):
        payload = json.loads(
            (
                root / "simplicio_loop/_contracts/mapper-store/v1/fixtures" / fixture
            ).read_text()
        )
        validator.validate(payload)


@pytest.mark.parametrize(
    ("version", "reason_code"),
    (
        (None, "MAPPER_VERSION_UNAVAILABLE"),
        ("", "MAPPER_VERSION_UNAVAILABLE"),
        ("not-a-version", "MAPPER_VERSION_INVALID"),
        ("0..26.1", "MAPPER_VERSION_INVALID"),
    ),
)
def test_mapper_route_fails_closed_for_missing_empty_or_invalid_version(
    monkeypatch, version, reason_code
):
    fake_mapper(monkeypatch)
    package = sys.modules["simplicio_mapper"]
    if version is None:
        package.__version__ = None
    else:
        package.__version__ = version

    report = probe_mapper()
    assert report.status == "incompatible"
    assert report.reason_code == reason_code

    result = StorageRouter(requested="mapper").select()
    assert result["status"] == "BLOCKED"
    assert result["selected"] is None
    assert result["reason_code"] == reason_code


def test_mapper_route_fails_closed_when_version_is_absent_everywhere(monkeypatch):
    fake_mapper(monkeypatch)
    del sys.modules["simplicio_mapper"].__version__

    def missing_metadata(_):
        raise importlib.metadata.PackageNotFoundError("simplicio-mapper")

    monkeypatch.setattr(importlib.metadata, "version", missing_metadata)
    report = probe_mapper()
    assert report.status == "incompatible"
    assert report.reason_code == "MAPPER_VERSION_UNAVAILABLE"


def test_mapper_route_keeps_metadata_version_fallback(monkeypatch):
    fake_mapper(monkeypatch)
    del sys.modules["simplicio_mapper"].__version__
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "0.26.9")

    report = probe_mapper()
    assert report.status == "available"
    assert report.mapper_version == "0.26.9"
