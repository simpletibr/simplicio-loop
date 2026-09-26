"""Preflight operate-binary probes are in-process (no --version/--help subprocess)."""
from __future__ import annotations

from simplicio_loop import strict_mode


def test_sanitize_version_banner_drops_usage():
    assert strict_mode._sanitize_version_banner("usage: simplicio-py [-h]") == ""
    assert strict_mode._sanitize_version_banner("simplicio-dev-cli 0.18.6") == "simplicio-dev-cli 0.18.6"


def test_action_operator_status_reads_the_capabilities_manifest_in_process(monkeypatch):
    """No subprocess: presence/version come from the packaged manifest."""
    manifest = {
        "schema": "simplicio.dev-cli.capabilities/v1",
        "package": {"name": "simplicio-cli", "version": "0.18.16"},
        "entrypoints": {"adapter": "simplicio-dev-cli", "python_adapter": "simplicio-py"},
    }
    monkeypatch.setattr(strict_mode, "_load_dev_cli_capabilities", lambda: manifest)

    def boom(*_a, **_k):
        raise AssertionError("action_operator_status must not spawn a subprocess")

    monkeypatch.setattr(strict_mode.subprocess, "run", boom)

    status = strict_mode.action_operator_status({})
    assert status["operational"] is True
    assert status["resolved_as"] == "simplicio-dev-cli"
    assert status["version"] == "0.18.16"
    assert status["capabilities_schema"] == "simplicio.dev-cli.capabilities/v1"


def test_action_operator_status_fails_closed_when_the_manifest_is_unavailable(monkeypatch):
    def missing():
        raise ModuleNotFoundError("no module named simplicio.capabilities")

    monkeypatch.setattr(strict_mode, "_load_dev_cli_capabilities", missing)
    status = strict_mode.action_operator_status({})
    assert status["operational"] is False
    assert status["present"] is False
    assert status["reason"] == "dev_cli_capabilities_unavailable"
    assert "dev_cli_capabilities_unavailable" in status["error"]


def test_mapper_status_reads_package_metadata_in_process(monkeypatch):
    def fake_version(package: str) -> str:
        return {"simplicio-mapper": "0.26.11"}[package]

    def boom(*_a, **_k):
        raise AssertionError("mapper status must not spawn a subprocess")

    monkeypatch.setattr(strict_mode._metadata, "version", fake_version)
    monkeypatch.setattr(strict_mode.subprocess, "run", boom)

    mapper = strict_mode.mapper_status()
    assert mapper["operational"] is True and mapper["version"] == "0.26.11"


def test_mapper_status_fails_closed_when_the_distribution_is_missing(monkeypatch):
    def missing_version(package: str) -> str:
        raise strict_mode._metadata.PackageNotFoundError(package)

    monkeypatch.setattr(strict_mode._metadata, "version", missing_version)
    status = strict_mode.mapper_status()
    assert status["operational"] is False
    assert status["present"] is False
    assert status["reason"] == "package_not_installed"


def test_preflight_payload_reports_real_versions_from_in_process_probes(monkeypatch, tmp_path):
    manifest = {
        "schema": "simplicio.dev-cli.capabilities/v1",
        "package": {"name": "simplicio-cli", "version": "0.18.16"},
        "entrypoints": {"adapter": "simplicio-dev-cli", "python_adapter": "simplicio-py"},
    }
    monkeypatch.setattr(strict_mode, "_load_dev_cli_capabilities", lambda: manifest)

    def fake_version(package: str) -> str:
        return {"simplicio-mapper": "0.26.11"}[package]

    monkeypatch.setattr(strict_mode._metadata, "version", fake_version)

    receipt = strict_mode.preflight_payload(str(tmp_path), strict=True)
    ops = {item["name"]: item for item in receipt["operators"]}
    assert ops["simplicio-mapper"]["present"] is True
    assert ops["simplicio-mapper"]["version"] == "0.26.11"
    assert ops["simplicio-dev-cli"]["present"] is True
    assert ops["simplicio-dev-cli"]["version"] == "0.18.16"
    assert not ops["simplicio-dev-cli"]["version"].lower().startswith("usage:")
    assert ops["simplicio-py"]["present"] is True
    assert ops["simplicio-py"]["version"] == "0.18.16"
    assert "simplicio-fast" not in ops
