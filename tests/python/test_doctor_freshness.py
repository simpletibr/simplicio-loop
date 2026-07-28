"""Doctor dependency-freshness check (no network — PyPI + installed are mocked)."""

from __future__ import annotations

import json

from simplicio import cli, doctor, ecosystem


def test_tracked_packages_includes_ecosystem_and_pyproject_deps() -> None:
    names = ecosystem.tracked_packages()

    # simplicio ecosystem triplet comes first
    assert names[:3] == ("simplicio-prompt", "simplicio-mapper", "simplicio-sprint")
    # declared pyproject dependencies are folded in
    for expected in ("numpy", "sentence-transformers"):
        assert expected in names
    # no duplicates (simplicio-mapper / simplicio-prompt declared in both places)
    assert len(names) == len(set(names))


def _stub_versions(monkeypatch, installed: dict, latest: dict) -> None:
    monkeypatch.setattr(ecosystem, "_installed_version", lambda n: installed.get(n))
    monkeypatch.setattr(ecosystem, "_pypi_latest", lambda n, timeout=5.0, refresh=False: latest.get(n))


def test_doctor_json_reports_available_updates(monkeypatch, capsys) -> None:
    monkeypatch.setattr(doctor, "tracked_packages", lambda: ("anthropic", "numpy"))
    _stub_versions(
        monkeypatch,
        installed={"anthropic": "0.105.2", "numpy": "2.5.0"},
        latest={"anthropic": "0.112.0", "numpy": "2.5.0"},
    )

    code = doctor.main(["--json"])
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["dependencies"]["updates_available"] == ["anthropic"]
    assert out["dependencies"]["upgraded"] == []


def test_doctor_no_check_updates_skips_dependency_block(monkeypatch, capsys) -> None:
    def boom() -> tuple:  # must never run
        raise AssertionError("freshness check ran despite --no-check-updates")

    monkeypatch.setattr(doctor, "_ecosystem_freshness", lambda **kw: boom())

    code = doctor.main(["--json", "--no-check-updates"])
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert "dependencies" not in out


def test_doctor_upgrade_calls_ensure_latest(monkeypatch, capsys) -> None:
    monkeypatch.setattr(doctor, "tracked_packages", lambda: ("anthropic",))
    _stub_versions(
        monkeypatch,
        installed={"anthropic": "0.112.0"},
        latest={"anthropic": "0.112.0"},
    )
    seen = {}

    def fake_ensure(force=False, dry_run=False, packages=ecosystem.ECOSYSTEM):
        seen["force"] = force
        seen["packages"] = packages
        return ["anthropic"]

    monkeypatch.setattr(doctor, "eco_ensure_latest", fake_ensure)

    code = doctor.main(["--json", "--upgrade"])
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert seen["force"] is True
    assert out["dependencies"]["upgraded"] == ["anthropic"]


def test_cli_forwards_new_doctor_flags(monkeypatch) -> None:
    seen = {}
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    def fake_doctor_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("simplicio.doctor.main", fake_doctor_main)

    code = cli.main(["doctor", "--refresh", "--upgrade", "--no-check-updates"])

    assert code == 0
    assert seen["argv"] == ["--no-check-updates", "--refresh", "--upgrade"]


# --------------------------------------------------------------------------- #
# native-vs-python delegation aggregate (issue #111)
# --------------------------------------------------------------------------- #


def test_doctor_json_reports_native_delegation_aggregate(tmp_path, capsys) -> None:
    from simplicio.runtime_bridge import record_delegation

    root = str(tmp_path)
    record_delegation("gate", "native", root=root)
    record_delegation("gate", "native", root=root)
    record_delegation("gate", "python-fallback", root=root, reason="binary-not-found")
    record_delegation("edit", "python-forced", root=root, reason="user-forced-python")

    code = doctor.main(["--json", "--no-check-updates", "--root", root])
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    delegation = out["native_delegation"]
    assert delegation["exists"] is True
    assert delegation["total"] == 4
    assert delegation["native_pct"] == 50.0
    assert delegation["verbs"]["gate"]["total"] == 3
    assert delegation["verbs"]["gate"]["native"] == 2
    assert delegation["verbs"]["edit"]["python-forced"] == 1


def test_doctor_json_reports_empty_native_delegation_when_no_events(tmp_path, capsys) -> None:
    code = doctor.main(["--json", "--no-check-updates", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["native_delegation"]["exists"] is False
    assert out["native_delegation"]["total"] == 0


def test_doctor_human_output_renders_native_delegation_section(tmp_path, capsys) -> None:
    from simplicio.runtime_bridge import record_delegation

    root = str(tmp_path)
    record_delegation("test-run", "native", root=root)

    code = doctor.main(["--no-check-updates", "--root", root])
    out = capsys.readouterr().out

    assert code == 0
    assert "native-vs-python delegation (issue #111):" in out
    assert "test-run" in out
