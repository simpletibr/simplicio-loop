from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import tomllib
from pathlib import Path

import pytest
import simplicio_mapper

from simplicio_loop import stack_manifest as manifest


ROOT = Path(__file__).parents[1]
# Version of the installed simplicio-loop distribution in the binding fixtures; the mapper
# receipt is compared to the *bundled* simplicio_mapper.__version__, not to this value.
LOOP_DISTRIBUTION_VERSION = "3.0.0"


@pytest.fixture(autouse=True)
def _launcher_independent_argv(monkeypatch, tmp_path: Path) -> None:
    # _mapper_identity() compares the resolved binary with a sibling of sys.argv[0]; pin argv
    # so the tests do not depend on how pytest was launched (`pytest` script vs `python -m`).
    monkeypatch.setattr(manifest.sys, "argv", [str(tmp_path / "pytest")])


def test_loop_bundles_both_required_operators_instead_of_depending_on_them() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    dependencies = manifest._dependency_specs_from_pyproject(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    # Single wheel: mapper and dev-cli ship inside simplicio-loop, so neither external
    # PyPI distribution may be a dependency (a second copy could shadow the bundled one).
    assert "simplicio-mapper" not in dependencies
    assert "simplicio-cli" not in dependencies
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

    # Both operator entrypoints are exported by the loop's own distribution and resolve to
    # real callables from the packages that setuptools bundles into the same wheel.
    assert scripts["simplicio-mapper"] == "simplicio_mapper.cli:main"
    assert scripts["simplicio-dev-cli"] == "simplicio.cli:main"
    for target in (scripts["simplicio-mapper"], scripts["simplicio-dev-cli"]):
        module_name, _, attribute = target.partition(":")
        assert callable(getattr(importlib.import_module(module_name), attribute))
    wheel_roots = set(pyproject["tool"]["setuptools"]["packages"]["find"]["where"])
    assert {"packages/mapper", "packages/dev-cli"} <= wheel_roots
    assert [name for name, _role in manifest._COMPONENT_ROLES] == ["simplicio-loop"]
    assert {
        (operator, distribution)
        for operator, distribution, _entrypoint in manifest.REQUIRED_OPERATOR_BINDINGS
    } == {("simplicio-mapper", "simplicio-loop"), ("simplicio-dev-cli", "simplicio-loop")}
    assert {
        entrypoint for _operator, _distribution, entrypoint in manifest.REQUIRED_OPERATOR_BINDINGS
    } <= set(scripts)


def test_stack_manifest_proves_operator_distribution_and_entrypoint_ownership(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "_installed_version", {"simplicio-loop": "1.0.0"}.get)
    monkeypatch.setattr(
        manifest,
        "_console_entrypoint_owners",
        lambda: {"simplicio-loop": {"simplicio-mapper", "simplicio-dev-cli"}},
    )
    monkeypatch.setattr(manifest.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(
        manifest,
        "_train_components",
        lambda: [("simplicio-loop", "understand,change,verify,run", "1.0.0")],
    )
    monkeypatch.setattr(
        manifest,
        "_mapper_identity",
        lambda _binding: {"status": "ok", "reason_code": "mapper-identity-verified"},
    )

    report = manifest.stack_manifest()

    assert report["healthy"] is True
    assert report["operator_contract_healthy"] is True
    assert report["legacy_distributions"] == []
    assert [item["distribution"] for item in report["components"]] == ["simplicio-loop"]
    bindings = {item["operator"]: item for item in report["operator_bindings"]}
    assert bindings["simplicio-mapper"]["status"] == "ok"
    assert bindings["simplicio-mapper"]["distribution"] == "simplicio-loop"
    assert bindings["simplicio-dev-cli"]["status"] == "ok"
    assert bindings["simplicio-dev-cli"]["distribution"] == "simplicio-loop"
    assert bindings["simplicio-dev-cli"]["entrypoint_declared"] is True
    assert bindings["simplicio-dev-cli"]["dependency_spec"] == "bundled in simplicio-loop"


def _stack_report(monkeypatch, *, installed, owners, on_path=False, legacy=()):
    # Only simplicio-loop (and any explicitly listed legacy standalone distribution) is installed.
    versions = {"simplicio-loop": installed, **{name: "0.1.0" for name in legacy}}
    monkeypatch.setattr(manifest, "_installed_version", versions.get)
    monkeypatch.setattr(manifest, "_console_entrypoint_owners", lambda: owners)
    monkeypatch.setattr(
        manifest.shutil, "which", lambda name: "/bin/" + name if on_path else None
    )
    monkeypatch.setattr(manifest, "_train_components", lambda: [("simplicio-loop", "run", "1.0.0")])
    report = manifest.stack_manifest()
    return report, {item["operator"]: item for item in report["operator_bindings"]}


def test_stack_manifest_fails_when_mapper_or_dev_cli_entrypoint_is_missing(monkeypatch) -> None:
    # A stale or partial install: the loop distribution is present but its metadata does
    # not export the operator entrypoints, so it must not look like a complete stack.
    report, bindings = _stack_report(
        monkeypatch, installed="1.0.0", owners={"simplicio-loop": set()}
    )

    assert report["healthy"] is False
    assert report["operator_contract_healthy"] is False
    assert bindings["simplicio-mapper"]["status"] == "entrypoint-not-declared"
    assert bindings["simplicio-dev-cli"]["status"] == "entrypoint-not-declared"
    assert set(report["missing_or_drifted"]) == {"simplicio-mapper", "simplicio-dev-cli"}


def test_stack_manifest_rejects_operator_entrypoints_owned_by_external_distributions(
    monkeypatch,
) -> None:
    # Pre-monorepo installs got the operators from separate PyPI distributions; only the
    # single simplicio-loop distribution satisfies the operator contract now.
    report, bindings = _stack_report(
        monkeypatch,
        installed="1.0.0",
        owners={
            "simplicio-mapper": {"simplicio-mapper"},
            "simplicio-cli": {"simplicio-dev-cli"},
        },
        on_path=True,
        legacy=manifest.LEGACY_DISTRIBUTIONS,
    )

    assert report["healthy"] is False
    assert report["operator_contract_healthy"] is False
    assert bindings["simplicio-mapper"]["status"] == "entrypoint-not-declared"
    assert bindings["simplicio-dev-cli"]["status"] == "entrypoint-not-declared"
    assert {"simplicio-mapper", "simplicio-dev-cli"} <= set(report["missing_or_drifted"])
    assert set(report["legacy_distributions"]) == {"simplicio-cli", "simplicio-mapper"}


def test_stack_manifest_fails_when_the_loop_distribution_is_missing(monkeypatch) -> None:
    report, bindings = _stack_report(monkeypatch, installed=None, owners={})

    assert report["healthy"] is False
    assert report["operator_contract_healthy"] is False
    assert bindings["simplicio-mapper"]["status"] == "dependency-missing"
    assert bindings["simplicio-dev-cli"]["status"] == "dependency-missing"
    assert set(report["missing_or_drifted"]) == {
        "simplicio-loop",
        "simplicio-mapper",
        "simplicio-dev-cli",
    }


def _mapper_binding(executable: Path) -> dict[str, object]:
    return {
        "status": "ok",
        "dependency_spec": "bundled in simplicio-loop",
        "installed": LOOP_DISTRIBUTION_VERSION,
        "distribution": "simplicio-loop",
        "entrypoint": "simplicio-mapper",
        "entrypoint_declared": True,
        "resolved": str(executable),
    }


def _mapper_receipt(**updates: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema": manifest.MAPPER_VERSION_SCHEMA,
        "component": "simplicio-mapper",
        "version": simplicio_mapper.__version__,
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
    assert identity["requested"] == "bundled in simplicio-loop"
    assert identity["selected"] == LOOP_DISTRIBUTION_VERSION
    assert identity["distribution"] == "simplicio-loop"
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


def test_mapper_identity_fails_closed_when_receipt_is_not_the_bundled_mapper_version(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "simplicio-mapper"
    executable.write_bytes(b"mapper executable")
    completed = subprocess.CompletedProcess(
        args=[str(executable), "version", "--json"],
        returncode=0,
        stdout=json.dumps(_mapper_receipt(version="0.0.1")),
        stderr="",
    )
    monkeypatch.setattr(manifest.subprocess, "run", lambda *args, **kwargs: completed)

    identity = manifest._mapper_identity(_mapper_binding(executable))

    assert simplicio_mapper.__version__ != "0.0.1"
    assert identity["status"] == "blocked"
    assert identity["reason_code"] == "mapper-version-mismatch"


def test_mapper_identity_rejects_entrypoint_that_is_not_the_running_installs_script(
    monkeypatch, tmp_path: Path
) -> None:
    scripts_dir = tmp_path / "bin"
    scripts_dir.mkdir()
    (scripts_dir / "simplicio-mapper").write_bytes(b"script next to the running install")
    stale = tmp_path / "elsewhere" / "simplicio-mapper"
    stale.parent.mkdir()
    stale.write_bytes(b"stale copy earlier on PATH")
    monkeypatch.setattr(manifest.sys, "argv", [str(scripts_dir / "simplicio-loop-stack")])

    identity = manifest._mapper_identity(_mapper_binding(stale))

    assert identity["status"] == "blocked"
    assert identity["reason_code"] == "mapper-entrypoint-stale-path"


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
