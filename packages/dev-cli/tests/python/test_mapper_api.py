from __future__ import annotations

from types import SimpleNamespace

from simplicio import mapper_api, mapper_module, mapper_version


def test_mapper_module_proxies_import(monkeypatch) -> None:
    fake_module = SimpleNamespace(artifact_status="ok")

    monkeypatch.setattr(mapper_api, "import_module", lambda name: fake_module)

    assert mapper_module() is fake_module
    assert mapper_api.artifact_status == "ok"


def test_mapper_version_reads_distribution_version(monkeypatch) -> None:
    monkeypatch.setattr(mapper_api, "version", lambda name: "0.18.0")

    assert mapper_version() == "0.18.0"
