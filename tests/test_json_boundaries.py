from pathlib import Path

from scripts.check_json_boundaries import check


def test_checked_in_state_is_explicitly_inventory_classified():
    assert check(Path(__file__).parents[1]) == []


def test_new_internal_json_is_blocked(tmp_path):
    root = Path(__file__).parents[1]
    (tmp_path / "config").mkdir()
    (tmp_path / ".simplicio").mkdir()
    (tmp_path / "config" / "json-boundaries.toml").write_text(
        (root / "config" / "json-boundaries.toml").read_text(), encoding="utf-8"
    )
    (tmp_path / ".simplicio" / "unexpected.json").write_text("{}", encoding="utf-8")
    assert "UNCLASSIFIED .simplicio/unexpected.json" in check(tmp_path)
