from __future__ import annotations

import json
from pathlib import Path

from scripts import build_component_release as component_release
from scripts import release_train_conformance as conformance_script
from scripts import release_train_reconcile as reconciler
from simplicio import release_train as rt


def _event() -> dict:
    wheel = "sha256:" + "1" * 64
    source = "sha256:" + "2" * 64
    manifest = {
        "schema": rt.MANIFEST_SCHEMA,
        "component": "simplicio-mapper",
        "version": "0.26.28",
        "commit_sha": "d" * 40,
        "commit_sha_source": "immutable tag",
        "generated_at": "2026-09-06T00:00:00Z",
        "distribution": {"pypi_package": "simplicio-mapper"},
        "schema_versions": {"component-release": "v1"},
        "protocols": ["simplicio.component-release/v1"],
        "capabilities": ["simplicio.mapper-artifacts/v1"],
        "compatibility": {"simplicio-dev-cli": {"mapper-artifacts": "v1"}},
        "artifact_digest": wheel,
        "artifact_digests": {
            "whl": {"filename": "mapper.whl", "digest": wheel},
            "sdist": {"filename": "mapper.tar.gz", "digest": source},
        },
        "signing": {"status": "not-implemented"},
        "downstream_events": {"deduplication": "event_id"},
    }
    return rt.build_release_event(manifest, channel="canary")


def test_reconcile_updates_only_mapper_and_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "1.0.0"\ndependencies = ["simplicio-mapper>=0.26.27,<0.27"]\n',
        encoding="utf-8",
    )
    wheel = "sha256:" + "1" * 64
    source = "sha256:" + "2" * 64
    (tmp_path / "uv.lock").write_text(
        "[[package]]\n"
        'name = "simplicio-mapper"\nversion = "0.26.28"\n'
        f'sdist = {{ url = "https://example.test/mapper.tar.gz", hash = "{source}", size = 2 }}\n'
        "wheels = [\n"
        f'  {{ url = "https://example.test/mapper.whl", hash = "{wheel}", size = 1 }},\n'
        "]\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "release-train-mapper.json").write_text(
        json.dumps({"dependency": {"release": {}}, "schema": "simplicio.release-train/v1"}), encoding="utf-8"
    )
    monkeypatch.setattr(reconciler, "_resolve_lock", lambda root, version: None)
    event = _event()
    first = reconciler.reconcile(tmp_path, event, lock_path=Path("config/release-train-lock.json"))
    assert first["status"] == "reconciled"
    assert first["changed"] is True
    assert "simplicio-mapper>=0.26.28,<0.27" in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    before = (tmp_path / "config" / "release-train-lock.json").read_bytes()
    second = reconciler.reconcile(tmp_path, event, lock_path=Path("config/release-train-lock.json"))
    assert second == first
    assert (tmp_path / "config" / "release-train-lock.json").read_bytes() == before


def test_build_component_manifest_hashes_each_release_artifact(tmp_path: Path, monkeypatch) -> None:
    artifact_dir = tmp_path / "dist"
    artifact_dir.mkdir()
    wheel = artifact_dir / "simplicio_cli-0.18.12-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    monkeypatch.setattr(component_release, "declared_own_version", lambda root: "0.18.12")
    monkeypatch.setattr(component_release, "own_commit", lambda root: "e" * 40)
    monkeypatch.setattr(component_release, "own_schema_versions", lambda root: {"x": "v1"})
    monkeypatch.setattr(component_release, "declared_dependency_range", lambda name, root: ">=0.26.28,<0.27")
    payload = component_release.build_manifest(
        tmp_path,
        artifact_dir,
        channel="stable",
        signature="base64:signature",
        sbom="sha256:" + "a" * 64,
        provenance="https://example.test/provenance",
        changelog=["release"],
    )
    assert payload["component"] == "simplicio-dev-cli"
    assert payload["artifacts"][0]["digest"].startswith("sha256:")
    assert payload["artifacts"][0]["size"] == 5


def test_conformance_does_not_accept_failed_n_minus_1_contract_lane(tmp_path: Path, monkeypatch) -> None:
    event = _event()
    mapper_source = tmp_path / "n"
    n_minus_1_source = tmp_path / "n-minus-1"
    mapper_source.mkdir()
    n_minus_1_source.mkdir()
    monkeypatch.setattr(
        conformance_script.importlib.metadata,
        "version",
        lambda name: event["version"],
    )
    monkeypatch.setattr(
        conformance_script,
        "tested_dependency_artifacts",
        lambda name, root: (
            event["version"],
            {
                "sdist": {"digest": event["artifact_digests"]["sdist"]["digest"]},
                "wheels": [{"digest": event["artifact_digests"]["whl"]["digest"]}],
            },
            "locked_in_uv.lock",
        ),
    )
    monkeypatch.setattr(conformance_script, "_git_commit", lambda path: event["commit_sha"])
    monkeypatch.setattr(conformance_script, "_smoke", lambda: {"status": "passed"})
    monkeypatch.setattr(conformance_script.shutil, "which", lambda name: "/usr/bin/uv")

    def run_contracts(argv, *, cwd):
        return {"status": "failed" if cwd == n_minus_1_source else "passed"}

    monkeypatch.setattr(conformance_script, "_run_contracts", run_contracts)
    result = conformance_script.conformance(
        tmp_path,
        event,
        None,
        n_minus_1_version="0.26.27",
        mapper_source=mapper_source,
        n_minus_1_source=n_minus_1_source,
    )
    assert result["n"] == "passed"
    assert result["n_minus_1"] == "UNVERIFIED"
    assert result["status"] == "UNVERIFIED"
