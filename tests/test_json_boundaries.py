from pathlib import Path

from scripts.check_json_boundaries import check


def test_checked_in_state_is_inventory_classified():
    assert check(Path(__file__).parents[1]) == []


def test_unclassified_internal_state_is_blocked(tmp_path):
    source = Path(__file__).parents[1]
    (tmp_path / "config").mkdir()
    (tmp_path / ".simplicio").mkdir()
    (tmp_path / "config" / "json-boundaries.toml").write_text(
        (source / "config" / "json-boundaries.toml").read_text(), encoding="utf-8"
    )
    (tmp_path / ".simplicio" / "new-state.json").write_text("{}", encoding="utf-8")
    assert "UNCLASSIFIED .simplicio/new-state.json" in check(tmp_path)
