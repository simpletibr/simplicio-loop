from pathlib import Path

import pytest

from scripts.check_json_boundaries import check

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 optional backport
    import tomli as tomllib  # type: ignore[no-redef]

SOURCE = Path(__file__).parents[1]


def test_checked_in_state_is_inventory_classified():
    assert check(Path(__file__).parents[1]) == []


def test_unclassified_internal_state_is_blocked(tmp_path):
    source = Path(__file__).parents[1]
    (tmp_path / "config").mkdir()
    (tmp_path / ".simplicio-loop/orchestrator").mkdir(parents=True)
    (tmp_path / "config" / "json-boundaries.toml").write_text(
        (source / "config" / "json-boundaries.toml").read_text(), encoding="utf-8"
    )
    (tmp_path / ".simplicio-loop/orchestrator" / "unexpected.json").write_text(
        "{}", encoding="utf-8"
    )
    assert "UNCLASSIFIED .simplicio-loop/orchestrator/unexpected.json" in check(
        tmp_path
    )


def _registry_root(tmp_path: Path, registry: str | None = None) -> Path:
    (tmp_path / "config").mkdir()
    text = (
        registry
        if registry is not None
        else (SOURCE / "config" / "json-boundaries.toml").read_text(encoding="utf-8")
    )
    (tmp_path / "config" / "json-boundaries.toml").write_text(text, encoding="utf-8")
    return tmp_path


def test_checked_in_registry_carries_only_permanent_classifications():
    registry = tomllib.loads(
        (SOURCE / "config" / "json-boundaries.toml").read_text(encoding="utf-8")
    )
    permanent = {"path", "category", "owner", "reason"}
    offending = {
        entry["path"]: sorted(set(entry) - permanent)
        for entry in registry.get("exceptions", [])
        if set(entry) - permanent
    }
    assert offending == {}


def test_savings_snapshots_are_a_permanent_classification(tmp_path):
    root = _registry_root(tmp_path)
    snapshots = (
        root / ".simplicio-loop" / "orchestrator" / "savings" / "snapshots.jsonl"
    )
    snapshots.parent.mkdir(parents=True)
    snapshots.write_text('{"item": "1"}\n', encoding="utf-8")
    assert check(root) == []


@pytest.mark.parametrize("dated_key", ["expires='2099-01-01'", "target='hbp'"])
def test_registry_rejects_dated_waivers_and_migration_targets(tmp_path, dated_key: str):
    root = _registry_root(
        tmp_path,
        "version=1\npolicy='internal-json-deny'\n"
        "[scanner]\ninternal_roots=['.simplicio-loop']\nformats=['.json']\n"
        "[[exceptions]]\npath='.simplicio-loop/legacy.json'\ncategory='runtime-ledger'\n"
        f"owner='loop'\nreason='runtime output'\n{dated_key}\n",
    )
    with pytest.raises(ValueError, match="unsupported keys"):
        check(root)


@pytest.mark.parametrize("path", [".simplicio-loop/runs/", ".simplicio-loop/*.json"])
def test_registry_rejects_directory_and_wildcard_entries(tmp_path, path: str):
    root = _registry_root(
        tmp_path,
        "version=1\npolicy='internal-json-deny'\n"
        "[scanner]\ninternal_roots=['.simplicio-loop']\nformats=['.json']\n"
        f"[[exceptions]]\npath='{path}'\ncategory='runtime-ledger'\nowner='loop'\nreason='runtime output'\n",
    )
    with pytest.raises(ValueError, match="exact path"):
        check(root)
