import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.install_smoke import run_smoke

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = [
    pytest.mark.external_integration,
    pytest.mark.skipif(
        importlib.util.find_spec("build") is None,
        reason=(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[build_backend]: "
            "the real wheel smoke lane requires the optional build module"
        ),
    ),
]


# Both tests below are real, slow (build a wheel + create a throwaway venv) end-to-end checks —
# no mocking, per the #292 mandate against fabricated supply-chain proof.
def test_run_smoke_builds_installs_and_proves_isolation():
    """Real end-to-end: builds the actual wheel, installs it with its dependencies into a throwaway venv
    (needs the package index), and proves the imported module comes from the venv's site-packages, not this
    repo checkout — the clean-room contract Fase 7 asks for, minus the registry round-trip
    (documented in the script's module docstring and docs/SUPPLY_CHAIN.md)."""
    result = run_smoke(REPO_ROOT, expected_version=None, keep=False)
    assert result["scope"].startswith("local-build-only")
    assert result["build"]["ok"] is True, result["build"]
    assert result["install"]["ok"] is True, result["install"]
    assert "--no-deps" not in result["install"]["command"]
    assert result["module_from_repo_checkout"] is False
    assert result["observed_version"]
    assert result["ok"] is True


def test_run_smoke_fails_closed_on_version_mismatch():
    result = run_smoke(REPO_ROOT, expected_version="0.0.0-does-not-exist", keep=False)
    assert result["ok"] is False
    assert result["reason_code"] == "version_or_isolation_mismatch"
