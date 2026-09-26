from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

from simplicio_loop import stack_manifest as manifest


ROOT = Path(__file__).parents[1]


def test_loop_declares_both_required_operator_distributions_directly() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = manifest._dependency_specs_from_pyproject(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "simplicio-mapper" in dependencies
    assert "simplicio-cli" in dependencies
    assert "simplicio-fast" not in dependencies
    assert "simplicio-fast" not in {name for name, _role in manifest._COMPONENT_ROLES}
    assert "simplicio-fast" not in manifest._FALLBACK_FLOORS
    assert "simplicio-prompt" not in dependencies
    assert "simplicio-prompt" not in {name for name, _role in manifest._COMPONENT_ROLES}
    scripts = project["scripts"]
    assert "simplicio-loop" in scripts
    assert "simplicio-loop-stack" in scripts
    assert "simplicio" not in scripts
    assert "savings_cli" not in str(scripts)
    assert "simplicio-dev-cli" not in {
        str(spec).split(";", 1)[0].split(">", 1)[0].split("<", 1)[0].strip()
        for spec in project["dependencies"]
    }


def test_stack_manifest_proves_operator_distribution_and_entrypoint_ownership(monkeypatch) -> None:
    monkeypatch.setattr(
        manifest,
        "_declared_dependency_specs",
        lambda: {"simplicio-mapper": "simplicio-mapper>=1.0", "simplicio-cli": "simplicio-cli>=1.0"},
    )
    monkeypatch.setattr(manifest, "_installed_version", lambda _name: "1.0.0")
    monkeypatch.setattr(
        manifest,
        "_console_entrypoint_owners",
        lambda: {
            "simplicio-mapper": {"simplicio-mapper"},
            "simplicio-cli": {"simplicio-dev-cli"},
        },
    )
    monkeypatch.setattr(manifest.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(manifest, "_train_components", lambda: [("simplicio-loop", "run", "1.0.0")])
    monkeypatch.setattr(
        manifest,
        "_mapper_identity",
        lambda _binding: {"status": "ok", "reason_code": "mapper-identity-verified"},
    )

    report = manifest.stack_manifest()

    assert report["healthy"] is True
    assert report["operator_contract_healthy"] is True
    bindings = {item["operator"]: item for item in report["operator_bindings"]}
    assert bindings["simplicio-mapper"]["status"] == "ok"
    assert bindings["simplicio-dev-cli"]["distribution"] == "simplicio-cli"
    assert bindings["simplicio-dev-cli"]["entrypoint_declared"] is True


def test_stack_manifest_fails_when_mapper_dependency_or_dev_cli_entrypoint_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "_declared_dependency_specs", lambda: {"simplicio-cli": "simplicio-cli>=1.0"})
    monkeypatch.setattr(manifest, "_installed_version", lambda _name: "1.0.0")
    monkeypatch.setattr(
        manifest,
        "_console_entrypoint_owners",
        lambda: {"simplicio-cli": set()},
    )
    monkeypatch.setattr(manifest.shutil, "which", lambda _name: None)
    monkeypatch.setattr(manifest, "_train_components", lambda: [("simplicio-loop", "run", "1.0.0")])

    report = manifest.stack_manifest()

    bindings = {item["operator"]: item for item in report["operator_bindings"]}
    assert report["healthy"] is False
    assert report["operator_contract_healthy"] is False
    assert bindings["simplicio-mapper"]["status"] == "dependency-not-declared"
    assert bindings["simplicio-dev-cli"]["status"] == "entrypoint-not-declared"
    assert set(report["missing_or_drifted"]) == {"simplicio-mapper", "simplicio-dev-cli"}


def _mapper_binding(executable: Path) -> dict[str, object]:
    return {
        "status": "ok",
        "dependency_spec": "simplicio-mapper>=0.26.26,<0.27",
        "installed": "0.26.26",
        "distribution": "simplicio-mapper",
        "entrypoint": "simplicio-mapper",
        "entrypoint_declared": True,
        "resolved": str(executable),
    }


def _mapper_receipt(**updates: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema": manifest.MAPPER_VERSION_SCHEMA,
        "component": "simplicio-mapper",
        "version": "0.26.26",
        "artifact_digest": "sha256:" + "a" * 64,
        "capabilities": list(manifest.REQUIRED_MAPPER_CAPABILITIES),
        "protocols": list(manifest.REQUIRED_MAPPER_PROTOCOLS),
    }
    receipt.update(updates)
    return receipt


def test_mapper_identity_proves_selected_artifact_executable_and_capabilities(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "simplicio-mapper"
    executable.write_bytes(b"mapper executable")
    completed = subprocess.CompletedProcess(
        args=[str(executable), "version", "--json"],
        returncode=0,
        stdout=json.dumps(_mapper_receipt()),
        stderr="",
    )
    monkeypatch.setattr(manifest.subprocess, "run", lambda *args, **kwargs: completed)

    identity = manifest._mapper_identity(_mapper_binding(executable))

    assert identity["status"] == "ok"
    assert identity["reason_code"] == "mapper-identity-verified"
    assert identity["requested"] == "simplicio-mapper>=0.26.26,<0.27"
    assert identity["selected"] == "0.26.26"
    assert identity["artifact_digest"] == "sha256:" + "a" * 64
    assert identity["executable_sha256"] == "sha256:" + hashlib.sha256(
        b"mapper executable"
    ).hexdigest()
    assert identity["capability_result"] == "compatible"


def test_mapper_identity_fails_closed_on_invalid_json(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "simplicio-mapper"
    executable.write_bytes(b"mapper executable")
    completed = subprocess.CompletedProcess(
        args=[str(executable), "version", "--json"],
        returncode=0,
        stdout="not-json",
        stderr="sensitive detail is not returned",
    )
    monkeypatch.setattr(manifest.subprocess, "run", lambda *args, **kwargs: completed)

    identity = manifest._mapper_identity(_mapper_binding(executable))

    assert identity["status"] == "blocked"
    assert identity["reason_code"] == "mapper-version-invalid-json"
    assert "stderr" not in identity


def test_mapper_identity_fails_closed_on_missing_capability(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "simplicio-mapper"
    executable.write_bytes(b"mapper executable")
    capabilities = list(manifest.REQUIRED_MAPPER_CAPABILITIES[:-1])
    completed = subprocess.CompletedProcess(
        args=[str(executable), "version", "--json"],
        returncode=0,
        stdout=json.dumps(_mapper_receipt(capabilities=capabilities)),
        stderr="",
    )
    monkeypatch.setattr(manifest.subprocess, "run", lambda *args, **kwargs: completed)

    identity = manifest._mapper_identity(_mapper_binding(executable))

    assert identity["status"] == "blocked"
    assert identity["reason_code"] == "mapper-capabilities-missing"
    assert identity["missing_capabilities"] == [manifest.REQUIRED_MAPPER_CAPABILITIES[-1]]


def test_mapper_identity_bounds_output_and_timeout(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "simplicio-mapper"
    executable.write_bytes(b"mapper executable")
    oversized = subprocess.CompletedProcess(
        args=[str(executable), "version", "--json"],
        returncode=0,
        stdout="x" * (manifest.MAX_MAPPER_VERSION_OUTPUT_BYTES + 1),
        stderr="",
    )
    monkeypatch.setattr(manifest.subprocess, "run", lambda *args, **kwargs: oversized)
    identity = manifest._mapper_identity(_mapper_binding(executable))
    assert identity["reason_code"] == "mapper-version-output-too-large"

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(manifest.subprocess, "run", raise_timeout)
    identity = manifest._mapper_identity(_mapper_binding(executable))
    assert identity["reason_code"] == "mapper-version-timeout"
