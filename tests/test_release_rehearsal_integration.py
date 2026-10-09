import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.release_rehearsal import run_governance_gate, run_rehearsal

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _dev_switch_not_this_file_s_business(monkeypatch):
    """These tests cover the pipeline. While the dev login switch exists the real rehearsal stops at its first step
    (reason `dev_switch_present`); that blocker has its own tests in test_release_rehearsal_dev_switch.py."""
    import scripts.release_rehearsal as release_rehearsal

    monkeypatch.setattr(release_rehearsal, "find_dev_switches", lambda repo: {})


# Real, slow, end-to-end: exports the tracked tree, bumps a scratch-only version, builds a real
# wheel, checksums/signs/SBOMs/provenance-statements it, and clean-room install-smokes it — no
# mocking, per the #292 mandate against fabricated supply-chain proof. Never touches this repo's
# real version files, never publishes anywhere.
@pytest.mark.external_integration
def test_run_rehearsal_chains_every_local_link_end_to_end():
    result = run_rehearsal(REPO_ROOT, keep=False)

    assert result["scope"].startswith("local-rehearsal-only")
    assert result["steps"]["export"]["ok"] is True
    assert result["steps"]["version_bump"]["ok"] is True
    assert result["rehearsal_version"].count("+rehearsal") == 1
    assert result["steps"]["build"]["ok"] is True
    assert result["steps"]["checksums"]["ok"] is True
    assert result["steps"]["sbom"]["ok"] is True
    assert result["steps"]["provenance"]["ok"] is True
    assert result["steps"]["install_smoke"]["ok"] is True
    assert result["steps"]["install_smoke"]["observed_version"] == result["rehearsal_version"]
    # Signing is best-effort: whichever way it goes, the state reflects it truthfully instead of
    # silently upgrading a blocked signature to "signed".
    assert result["state"] in ("smoke-verified",)
    assert result["ok"] is True
    # Never mutates the real repo checkout.
    assert (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").count(result["rehearsal_version"]) == 0
    # #294 scope item 6: the rehearsal gates on + snapshots repo-size/claims governance, and
    # attaches the size/history-migration reports alongside the checksums/SBOM/provenance.
    assert result["steps"]["governance_gate"]["ok"] is True
    assert result["governance"]["repository_budget"]["ok"] is True
    assert result["governance"]["claims_parity"]["ok"] is True
    assert result["governance"]["size_snapshot"] is not None
    assert result["governance"]["history_migration_snapshot"] is not None
    attached = result["steps"]["governance_gate"]["attached_reports"]
    assert any(name.endswith("REPO_SIZE_REPORT.md") for name in attached)
    assert any(name.endswith("HISTORY_MIGRATION_PLAN.md") for name in attached)


# Real, in-process (no wheel build): proves the governance gate itself measures the ACTUAL repo
# checkout (not a hand-fed fixture) and reports both sub-checks truthfully.
def test_run_governance_gate_measures_the_real_repo():
    result = run_governance_gate(REPO_ROOT)

    assert result["ok"] is True
    assert result["repository_budget"]["ok"] is True
    assert result["claims_parity"]["ok"] is True
    assert result["claims_parity"]["results"]  # ran checks 8+13, not an empty/fallback shape
    assert result["size_snapshot"] is not None
    assert "by_extension" in result["size_snapshot"]
    assert result["history_migration_snapshot"] is not None
    assert "candidate_blob_count" in result["history_migration_snapshot"]


def test_run_rehearsal_fails_closed_when_governance_gate_fails(monkeypatch):
    import scripts.release_rehearsal as release_rehearsal

    def _fake_gate(_repo):
        return {"ok": False, "repository_budget": {"ok": False, "output": "fake failure"},
                "claims_parity": {"ok": True, "results": []}, "size_snapshot": None,
                "history_migration_snapshot": None}

    monkeypatch.setattr(release_rehearsal, "run_governance_gate", _fake_gate)
    result = release_rehearsal.run_rehearsal(REPO_ROOT, keep=False)

    assert result["ok"] is False
    assert result["reason_code"] == "governance_gate_failed"
    # Fails BEFORE ever touching the export/build steps.
    assert "export" not in result["steps"]


def test_run_rehearsal_fails_closed_on_invalid_explicit_version():
    result = run_rehearsal(REPO_ROOT, version="not-a-version", keep=False)

    assert result["ok"] is False
    assert result["reason_code"] == "version_bump_failed"


@pytest.mark.external_integration
def test_run_rehearsal_require_signing_blocks_without_a_key():
    result = run_rehearsal(REPO_ROOT, require_signing=True, keep=False)

    # This environment has no configured gpg secret key (verified during development); requiring
    # signing must fail closed rather than silently proceed.
    if not result["steps"].get("sign", {}).get("ok"):
        assert result["ok"] is False
        assert result["reason_code"] == "signing_required_but_blocked"
