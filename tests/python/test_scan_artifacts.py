"""Tests for scripts/scan_artifacts.py (#167 AC "Artifacts passam scanner").

Builds tiny synthetic wheel/sdist fixtures in-memory (stdlib zipfile/tarfile
only, no new dependency) to prove the scanner both catches an injected
fake-secret^Wbrand-leak pattern and passes clean on an allowlisted file, then
separately exercises it against this package's real, freshly built sdist/
wheel to prove the real release artifact is clean.
"""

from __future__ import annotations

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_scan_artifacts_module():
    script_path = REPO_ROOT / "scripts" / "scan_artifacts.py"
    spec = importlib.util.spec_from_file_location("scan_artifacts_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_fixture_wheel(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def _write_fixture_sdist(path: Path, package_name: str, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name=f"{package_name}/{name}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


def test_scan_artifact_flags_unallowlisted_hermes_mention_in_wheel(tmp_path: Path) -> None:
    module = _load_scan_artifacts_module()
    whl = tmp_path / "fixture-0.0.0-py3-none-any.whl"
    _write_fixture_wheel(
        whl,
        {
            "fixture/__init__.py": b"# clean module\n",
            # Simulates a leftover legacy-brand mention in a file that has no
            # documented compat-surface exception.
            "fixture/leaky.py": b"# TODO: still calls out to the old Hermes bridge\n",
        },
    )

    offenders = module.scan_artifact(whl)

    assert offenders == ["fixture-0.0.0-py3-none-any.whl:fixture/leaky.py"]


def test_scan_artifact_allows_documented_compat_surface_file_in_wheel(tmp_path: Path) -> None:
    module = _load_scan_artifacts_module()
    whl = tmp_path / "fixture-0.0.0-py3-none-any.whl"
    _write_fixture_wheel(
        whl,
        {
            "fixture/__init__.py": b"# clean module\n",
            # Same allowlisted path this repo's real package ships.
            "simplicio/plan_compiler/compat_adapter.py": (
                b'"""Compatibilidade Hermes fica em uma borda registrada."""\n'
            ),
        },
    )

    offenders = module.scan_artifact(whl)

    assert offenders == []


def test_scan_artifact_flags_unallowlisted_hermes_mention_in_sdist(tmp_path: Path) -> None:
    module = _load_scan_artifacts_module()
    sdist = tmp_path / "fixture-0.0.0.tar.gz"
    _write_fixture_sdist(
        sdist,
        "fixture-0.0.0",
        {
            "fixture/leaky.py": b"# uses the legacy Hermes client under the hood\n",
        },
    )

    offenders = module.scan_artifact(sdist)

    assert offenders == ["fixture-0.0.0.tar.gz:fixture/leaky.py"]


def test_scan_artifact_allows_documented_compat_surface_file_in_sdist(tmp_path: Path) -> None:
    module = _load_scan_artifacts_module()
    sdist = tmp_path / "fixture-0.0.0.tar.gz"
    _write_fixture_sdist(
        sdist,
        "fixture-0.0.0",
        {
            "simplicio/runtime_contracts.py": b"# legacy runtime alias (Hermes/Agent) detection\n",
        },
    )

    offenders = module.scan_artifact(sdist)

    assert offenders == []


@pytest.mark.skipif(
    not list((REPO_ROOT / "dist").glob("*.whl")) or not list((REPO_ROOT / "dist").glob("*.tar.gz")),
    reason="dist/*.whl and dist/*.tar.gz must be built first (`python -m build`)",
)
def test_real_built_artifacts_pass_the_scanner() -> None:
    """Confirms this package's actual release artifacts are clean — not just
    the synthetic fixtures above. Requires `python -m build` to have been run
    first (the same precondition `scripts/scan_artifacts.py --check` has)."""
    module = _load_scan_artifacts_module()
    dist_dir = REPO_ROOT / "dist"
    artifacts = sorted(dist_dir.glob("*.whl")) + sorted(dist_dir.glob("*.tar.gz"))

    offenders: list[str] = []
    for artifact in artifacts:
        offenders.extend(module.scan_artifact(artifact))

    assert offenders == []
