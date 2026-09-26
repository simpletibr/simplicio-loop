"""Issue #1343: the Mapper no longer carries any Simplicio Fast integration surface."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli._data import run_data_cli
from simplicio_mapper.cli._snapshot import run_snapshot_cli
from simplicio_mapper.ecosystem_contract import run_doctor_cli
from simplicio_mapper.store import MAPPER_STORE_READERS
from simplicio_mapper.store.catalog import layout_tree

PACKAGE = Path(__file__).resolve().parents[2] / "simplicio_mapper"


def test_doctor_no_longer_offers_a_fast_diagnostic() -> None:
    assert run_doctor_cli(["--fast", "--json"]) == 2


def test_snapshot_rejects_the_removed_backend_flags(tmp_path: Path) -> None:
    assert run_snapshot_cli(["build", "--backend", "local", str(tmp_path)]) == 2
    assert run_snapshot_cli(["build", "--fast-manifest", "m.json", str(tmp_path)]) == 2


def test_data_status_reports_no_fast_link(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    output = StringIO()
    with redirect_stdout(output):
        code = run_data_cli(["status", "--data-dir", str(tmp_path / "data"), "--json"])
    assert code == 0
    payload = json.loads(output.getvalue())
    assert "mapper_fast" not in payload


def test_catalog_layout_has_no_fast_integration() -> None:
    rendered = json.dumps(layout_tree())
    assert "mapper_fast_integration" not in rendered
    assert "sfast" not in rendered
    assert "simplicio-fast" not in rendered


def test_store_readers_and_registry_drop_fast() -> None:
    assert "fast" not in MAPPER_STORE_READERS
    registry = json.loads((PACKAGE / "contracts/contract-registry/v1/registry.json").read_text(encoding="utf-8"))
    for contract in registry["contracts"]:
        assert "fast" not in contract["id"]
        assert "fast" not in contract.get("producers", [])
        assert "fast" not in contract.get("consumers", [])

