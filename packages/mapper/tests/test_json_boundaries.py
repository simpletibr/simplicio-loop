from pathlib import Path

import pytest

from scripts.check_json_boundaries import _load, check, main


def test_checked_in_state_is_explicitly_inventory_classified():
    assert check(Path(__file__).parents[1]) == []


def test_new_internal_json_is_blocked(tmp_path):
    root = Path(__file__).parents[1]
    (tmp_path / "config").mkdir()
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / "config" / "json-boundaries.toml").write_text(
        (root / "config" / "json-boundaries.toml").read_text(), encoding="utf-8"
    )
    (tmp_path / ".simplicio-loop" / "unexpected.json").write_text("{}", encoding="utf-8")
    assert "UNCLASSIFIED .simplicio-loop/unexpected.json" in check(tmp_path)


def test_release_strict_mode_rejects_classified_legacy_json():
    findings = check(Path(__file__).parents[1], mode="strict")
    assert findings
    assert all(item.startswith("INTERNAL_JSON ") for item in findings)


@pytest.mark.parametrize("path", [".simplicio-loop/*.json", "../escape.json", "/tmp/state.json"])
def test_exception_paths_must_be_exact_and_repository_relative(tmp_path, path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "json-boundaries.toml").write_text(
        f'''version = 1
[scanner]
internal_roots = [".simplicio-loop"]
formats = [".json"]
[[exceptions]]
path = "{path}"
category = "legacy-internal"
target = "hbi"
owner = "mapper"
reason = "bounded migration"
expires = 2099-01-01
''',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        _load(tmp_path)


def test_cli_reports_baseline_pass(capsys):
    assert main(["--root", str(Path(__file__).parents[1]), "--mode", "baseline"]) == 0
    assert "baseline=pass" in capsys.readouterr().out


def test_cli_reports_strict_findings(capsys):
    assert main(["--root", str(Path(__file__).parents[1]), "--strict"]) == 1
    assert "strict=blocked" in capsys.readouterr().out


def test_cli_fails_closed_for_missing_configuration(tmp_path, capsys):
    assert main(["--root", str(tmp_path)]) == 2
    assert "configuration error" in capsys.readouterr().err


def test_stale_exception_is_rejected(tmp_path):
    (tmp_path / "config").mkdir()
    source = Path(__file__).parents[1] / "config" / "json-boundaries.toml"
    (tmp_path / "config" / "json-boundaries.toml").write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert check(tmp_path)[0].startswith("STALE_EXCEPTION ")
