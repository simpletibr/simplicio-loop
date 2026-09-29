"""Release packaging regression gate (#1153).

Ensures:
- project.license uses an SPDX string (not deprecated TOML table);
- obsolete license classifiers are not reintroduced;
- setuptools discovers intentional namespace packages (_contracts, subpackages);
- required _contracts JSON files remain present and declared in package-data.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

from setuptools import find_namespace_packages

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
CONTRACTS = ROOT / "simplicio_loop" / "_contracts"

# Floor observed on main (39 JSON contracts); fail if packaging tree shrinks badly.
MIN_CONTRACT_JSON = 35

REQUIRED_PACKAGE_MARKERS = (
    "simplicio_loop",
    "simplicio_loop._contracts",
    "simplicio_loop._catalog",
    "simplicio_loop._bundle",
    "simplicio_loop.safety_agents",
    "simplicio_loop.quality_providers",
)


def _manifest() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_license_is_spdx_string() -> None:
    license_field = _manifest()["project"]["license"]
    assert isinstance(license_field, str), f"expected SPDX string, got {type(license_field)!r}"
    assert license_field == "MIT"


def test_license_classifier_removed() -> None:
    classifiers = _manifest()["project"].get("classifiers", [])
    license_classifiers = [c for c in classifiers if c.startswith("License ::")]
    assert license_classifiers == [], f"deprecated license classifiers present: {license_classifiers}"


def test_build_system_requires_setuptools_77_plus() -> None:
    requires = _manifest()["build-system"]["requires"]
    setuptools_req = next(r for r in requires if r.lower().startswith("setuptools"))
    assert ">=77" in setuptools_req or ">77" in setuptools_req, setuptools_req


def test_namespace_package_discovery_is_configured() -> None:
    setuptools_tool = _manifest()["tool"]["setuptools"]
    find = setuptools_tool["packages"]["find"]
    assert find.get("namespaces") is True
    include = find.get("include") or []
    assert any(item.startswith("simplicio_loop") for item in include)
    # Explicit packages list must not reappear (would reintroduce discovery warnings).
    assert not isinstance(setuptools_tool.get("packages"), list)


def test_find_namespace_packages_includes_contracts_and_subpackages() -> None:
    packages = set(find_namespace_packages(where=str(ROOT), include=["simplicio_loop*"]))
    missing = [name for name in REQUIRED_PACKAGE_MARKERS if name not in packages]
    assert missing == [], f"namespace discovery missing packages: {missing}"


def test_required_contracts_json_files_present() -> None:
    files = sorted(CONTRACTS.rglob("*.json"))
    assert len(files) >= MIN_CONTRACT_JSON, (
        f"expected >= {MIN_CONTRACT_JSON} _contracts JSON files, found {len(files)}"
    )
    relative = {f.relative_to(CONTRACTS).as_posix() for f in files}
    assert "registry/v1/registry.json" in relative


def test_package_data_declares_contracts_and_catalog() -> None:
    pdata = _manifest()["tool"]["setuptools"]["package-data"]
    blob = json.dumps(pdata, sort_keys=True)
    assert "_contracts" in blob
    assert "_catalog" in blob
    assert "_bundle" in blob
