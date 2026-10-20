"""Tests for simplicio_loop/external_verifiers.py (#290 Fase 4 — byte-level release verifiers).

Covers the real SHA-256 digest helper, checksum-manifest parsing, and the three verifier
dimensions (checksums/signatures/SBOM) failing closed with a stable reason code whenever the
corresponding proof material is absent, unparseable, or mismatched — never a favorable default.
A final integration test hits the real `simpletibr/simplicio-loop` GitHub release with the
real `gh` CLI (skipped if `gh`/network is unavailable) to prove the download + digest path works
against real bytes, not just mocks.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simplicio_loop import external_verifiers as ev


def _fake_completed(returncode=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_sha256_file_matches_hashlib_on_real_bytes(tmp_path):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"simplicio-loop #290 byte-level verifier fixture" * 100)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert ev.sha256_file(path) == expected


def test_parse_checksum_manifest_sha256sum_style():
    text = "aaaa" * 16 + "  simplicio_loop-1.0.0-py3-none-any.whl\n" + "bbbb" * 16 + " *simplicio_loop-1.0.0.tar.gz\n"
    parsed = ev.parse_checksum_manifest(text)
    assert parsed["simplicio_loop-1.0.0-py3-none-any.whl"] == "aaaa" * 16
    assert parsed["simplicio_loop-1.0.0.tar.gz"] == "bbbb" * 16


def test_parse_checksum_manifest_name_colon_hash_style():
    text = f"simplicio_loop-1.0.0.tar.gz: {'cc' * 32}\n"
    parsed = ev.parse_checksum_manifest(text)
    assert parsed["simplicio_loop-1.0.0.tar.gz"] == "cc" * 32


def test_parse_checksum_manifest_ignores_garbage_lines():
    assert ev.parse_checksum_manifest("not a checksum line\n\n") == {}


# ---------------------------------------------------------------------------
# verify_release_artifacts — fail-closed dimensions, real downloaded-bytes digesting
# ---------------------------------------------------------------------------

def _stage_download(tmp_path, files):
    dest = tmp_path / "download"
    dest.mkdir()
    for name, content in files.items():
        (dest / name).write_bytes(content if isinstance(content, bytes) else content.encode())
    return [str(dest / name) for name in files]


def test_verify_release_artifacts_no_manifest_fails_closed_with_reason_code(tmp_path, monkeypatch):
    wheel_bytes = b"fake wheel bytes"
    downloaded = _stage_download(tmp_path, {"pkg-1.0.0-py3-none-any.whl": wheel_bytes})
    monkeypatch.setattr(ev, "download_release_assets",
                        lambda repo, tag, dest, asset_names=None: {"ok": True, "downloaded": downloaded})
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(returncode=1, stderr="no attestations found"))
    result = ev.verify_release_artifacts("acme/widgets", "v1.0.0", [], workdir=str(tmp_path))
    assert result["checksums_verified"] is False
    assert result["checksum_reason_code"] == "checksum_manifest_absent"
    assert result["signatures_verified"] is False
    assert result["signature_reason_code"] == "attestation_not_found"
    assert result["sbom_present"] is False
    assert result["sbom_reason_code"] == "sbom_asset_absent"
    assert result["digests"]["pkg-1.0.0-py3-none-any.whl"] == hashlib.sha256(wheel_bytes).hexdigest()


def test_verify_release_artifacts_matching_manifest_and_sbom_verifies_real_digest(tmp_path, monkeypatch):
    wheel_bytes = b"another fake wheel"
    digest = hashlib.sha256(wheel_bytes).hexdigest()
    sbom = json.dumps({"spdxVersion": "SPDX-2.3", "packages": []})
    files = {
        "pkg-1.0.0-py3-none-any.whl": wheel_bytes,
        "checksums.txt": f"{digest}  pkg-1.0.0-py3-none-any.whl\n",
        "pkg-1.0.0.spdx.json": sbom,
    }
    downloaded = _stage_download(tmp_path, files)
    monkeypatch.setattr(ev, "download_release_assets",
                        lambda repo, tag, dest, asset_names=None: {"ok": True, "downloaded": downloaded})
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(returncode=0))
    result = ev.verify_release_artifacts("acme/widgets", "v1.0.0", [], workdir=str(tmp_path))
    assert result["checksums_verified"] is True
    assert result["assets_verified"] == ["pkg-1.0.0-py3-none-any.whl"]
    assert result["signatures_verified"] is True
    assert result["sbom_present"] is True


def test_verify_release_artifacts_checksum_mismatch_blocks(tmp_path, monkeypatch):
    wheel_bytes = b"tampered bytes"
    wrong_digest = "0" * 64
    files = {
        "pkg-1.0.0-py3-none-any.whl": wheel_bytes,
        "checksums.txt": f"{wrong_digest}  pkg-1.0.0-py3-none-any.whl\n",
    }
    downloaded = _stage_download(tmp_path, files)
    monkeypatch.setattr(ev, "download_release_assets",
                        lambda repo, tag, dest, asset_names=None: {"ok": True, "downloaded": downloaded})
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(returncode=1))
    result = ev.verify_release_artifacts("acme/widgets", "v1.0.0", [], workdir=str(tmp_path))
    assert result["checksums_verified"] is False
    assert result["checksum_reason_code"] == "checksum_mismatch"


def test_verify_release_artifacts_download_failure_fails_all_dimensions_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "download_release_assets",
                        lambda repo, tag, dest, asset_names=None: {"ok": False, "reason_code": "release_download_failed", "downloaded": []})
    result = ev.verify_release_artifacts("acme/widgets", "v1.0.0", [], workdir=str(tmp_path))
    assert result["checksums_verified"] is False
    assert result["checksum_reason_code"] == "release_download_failed"
    assert result["signatures_verified"] is False
    assert result["signature_reason_code"] == "release_download_failed"
    assert result["sbom_present"] is False
    assert result["sbom_reason_code"] == "release_download_failed"


def test_verify_release_artifacts_sbom_wrong_format_is_not_present(tmp_path, monkeypatch):
    files = {
        "pkg-1.0.0-py3-none-any.whl": b"bytes",
        "sbom.json": json.dumps({"not_a_real_sbom": True}),
    }
    downloaded = _stage_download(tmp_path, files)
    monkeypatch.setattr(ev, "download_release_assets",
                        lambda repo, tag, dest, asset_names=None: {"ok": True, "downloaded": downloaded})
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(returncode=1))
    result = ev.verify_release_artifacts("acme/widgets", "v1.0.0", [], workdir=str(tmp_path))
    assert result["sbom_present"] is False
    assert result["sbom_reason_code"] == "sbom_format_unrecognized"


# ---------------------------------------------------------------------------
# run_install_smoke
# ---------------------------------------------------------------------------

def test_run_install_smoke_missing_wheel_fails_closed():
    result = ev.run_install_smoke("/no/such/wheel.whl")
    assert result == {"passed": False, "reason_code": "wheel_not_found"}


def test_run_install_smoke_venv_create_failure(tmp_path, monkeypatch):
    wheel = tmp_path / "pkg.whl"
    wheel.write_bytes(b"x")
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(returncode=1, stderr="venv boom"))
    result = ev.run_install_smoke(str(wheel))
    assert result["passed"] is False
    assert result["reason_code"] == "venv_create_failed"


def test_run_install_smoke_all_steps_succeed(tmp_path, monkeypatch):
    wheel = tmp_path / "pkg.whl"
    wheel.write_bytes(b"x")
    calls = {"n": 0}

    def fake_run(args, cwd=None, timeout=180):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_completed(returncode=0)  # venv create
        if calls["n"] == 2:
            return _fake_completed(returncode=0)  # pip install
        return _fake_completed(returncode=0, stdout="1.2.3\n")  # import probe

    monkeypatch.setattr(ev, "_run", fake_run)
    result = ev.run_install_smoke(str(wheel))
    assert result["passed"] is True
    assert result["version"] == "1.2.3"


# ---------------------------------------------------------------------------
# Live integration — real gh CLI, real release bytes (skipped if unavailable)
# ---------------------------------------------------------------------------

def _gh_available():
    return shutil.which("gh") is not None


@pytest.mark.skipif(not _gh_available(), reason="gh CLI not installed")
@pytest.mark.external_integration
def test_download_release_assets_real_repo_computes_real_digest():
    """MEASURED: downloads the real simpletibr/simplicio-loop v3.34.1 release asset via
    `gh release download` and recomputes its sha256 over the actual downloaded bytes — proving
    the download + digest path works end-to-end against real GitHub-hosted bytes, not a mock."""
    with tempfile.TemporaryDirectory(prefix="simplicio-loop-live-verify-") as workdir:
        result = ev.download_release_assets(
            "simpletibr/simplicio-loop", "v3.34.1", workdir,
            asset_names=["simplicio_loop-3.34.1-py3-none-any.whl"],
        )
        if not result["ok"]:
            pytest.skip(f"network/gh unavailable in this environment: {result.get('error')}")
        assert result["downloaded"], "expected at least one downloaded asset"
        wheel_path = Path(result["downloaded"][0])
        assert wheel_path.stat().st_size > 0
        digest = ev.sha256_file(wheel_path)
        assert len(digest) == 64


# ---------------------------------------------------------------------------
# BranchReachabilityVerifier (#290 Fase 3) — discover_default_branch / compare_commits /
# verify_branch_reachability / git_is_ancestor
# ---------------------------------------------------------------------------

def test_discover_default_branch_parses_real_shape(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180:
                        _fake_completed(stdout=json.dumps({"default_branch": "trunk"})))
    result = ev.discover_default_branch("acme/widgets")
    assert result == {"ok": True, "default_branch": "trunk"}


def test_discover_default_branch_fails_closed_on_transport_error(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180:
                        _fake_completed(returncode=1, stderr="HTTP 404"))
    result = ev.discover_default_branch("acme/widgets")
    assert result["ok"] is False
    assert result["reason_code"] == "default_branch_query_failed"


def test_discover_default_branch_fails_closed_on_malformed_json(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(stdout="not json"))
    result = ev.discover_default_branch("acme/widgets")
    assert result["ok"] is False
    assert result["reason_code"] == "default_branch_response_malformed"


def test_compare_commits_parses_status_and_counts(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180:
                        _fake_completed(stdout=json.dumps({"status": "behind", "ahead_by": 0, "behind_by": 3})))
    result = ev.compare_commits("acme/widgets", "main", "deadbeef")
    assert result == {"ok": True, "status": "behind", "ahead_by": 0, "behind_by": 3}


def test_compare_commits_fails_closed_on_transport_error(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180:
                        _fake_completed(returncode=1, stderr="rate limited"))
    result = ev.compare_commits("acme/widgets", "main", "deadbeef")
    assert result["ok"] is False
    assert result["reason_code"] == "compare_query_failed"


def test_verify_branch_reachability_identical_is_reachable(monkeypatch):
    monkeypatch.setattr(ev, "discover_default_branch", lambda repo: {"ok": True, "default_branch": "main"})
    monkeypatch.setattr(ev, "compare_commits", lambda repo, base, head: {"ok": True, "status": "identical"})
    result = ev.verify_branch_reachability("acme/widgets", "deadbeef")
    assert result["ok"] is True
    assert result["reachable"] is True
    assert result["default_branch"] == "main"
    assert result["reason_code"] is None


def test_verify_branch_reachability_behind_is_reachable(monkeypatch):
    monkeypatch.setattr(ev, "discover_default_branch", lambda repo: {"ok": True, "default_branch": "main"})
    monkeypatch.setattr(ev, "compare_commits", lambda repo, base, head: {"ok": True, "status": "behind"})
    result = ev.verify_branch_reachability("acme/widgets", "deadbeef")
    assert result["reachable"] is True


def test_verify_branch_reachability_diverged_is_not_reachable(monkeypatch):
    monkeypatch.setattr(ev, "discover_default_branch", lambda repo: {"ok": True, "default_branch": "main"})
    monkeypatch.setattr(ev, "compare_commits", lambda repo, base, head: {"ok": True, "status": "diverged"})
    result = ev.verify_branch_reachability("acme/widgets", "deadbeef")
    assert result["reachable"] is False
    assert result["reason_code"] == "merge_commit_not_reachable"


def test_verify_branch_reachability_ahead_is_not_reachable(monkeypatch):
    # `ahead` means the claimed commit is not yet on the default branch at all (e.g. a
    # squash-merge whose PR head never became part of main's history under a different sha).
    monkeypatch.setattr(ev, "discover_default_branch", lambda repo: {"ok": True, "default_branch": "main"})
    monkeypatch.setattr(ev, "compare_commits", lambda repo, base, head: {"ok": True, "status": "ahead"})
    result = ev.verify_branch_reachability("acme/widgets", "deadbeef")
    assert result["reachable"] is False
    assert result["reason_code"] == "merge_commit_not_reachable"


def test_verify_branch_reachability_missing_commit_sha_fails_closed():
    result = ev.verify_branch_reachability("acme/widgets", "")
    assert result["ok"] is False
    assert result["reachable"] is False
    assert result["reason_code"] == "commit_sha_missing"


def test_verify_branch_reachability_default_branch_discovery_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(ev, "discover_default_branch",
                        lambda repo: {"ok": False, "reason_code": "default_branch_query_failed"})
    result = ev.verify_branch_reachability("acme/widgets", "deadbeef")
    assert result["ok"] is False
    assert result["reachable"] is False
    assert result["reason_code"] == "default_branch_query_failed"


def test_verify_branch_reachability_expected_default_branch_mismatch_fails_closed(monkeypatch):
    monkeypatch.setattr(ev, "discover_default_branch", lambda repo: {"ok": True, "default_branch": "trunk"})
    result = ev.verify_branch_reachability("acme/widgets", "deadbeef", expected_default_branch="main")
    assert result["ok"] is False
    assert result["reachable"] is False
    assert result["reason_code"] == "default_branch_mismatch"


def test_git_is_ancestor_exit_zero_is_reachable(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(returncode=0))
    result = ev.git_is_ancestor("/repo", "deadbeef", "origin/main")
    assert result == {"ok": True, "reachable": True, "reason_code": None}


def test_git_is_ancestor_exit_one_is_not_ancestor(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(returncode=1))
    result = ev.git_is_ancestor("/repo", "deadbeef", "origin/main")
    assert result == {"ok": True, "reachable": False, "reason_code": "merge_commit_not_reachable"}


def test_git_is_ancestor_other_exit_code_fails_closed(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(returncode=128, stderr="fatal: bad object"))
    result = ev.git_is_ancestor("/repo", "deadbeef", "origin/main")
    assert result["ok"] is False
    assert result["reachable"] is False
    assert result["reason_code"] == "git_merge_base_error"


def test_git_is_ancestor_real_local_repo_proves_ancestry():
    """MEASURED: runs the real `git merge-base --is-ancestor` subprocess (no mock) against
    this checkout's own history -- the current HEAD's parent commit must be a real ancestor
    of HEAD, and an unrelated/unknown sha must not be."""
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    repo_root = str(Path(__file__).resolve().parent.parent)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, timeout=20)
    parent = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=repo_root, capture_output=True, text=True, timeout=20)
    if head.returncode != 0 or parent.returncode != 0:
        pytest.skip("not enough git history in this checkout")
    result = ev.git_is_ancestor(repo_root, parent.stdout.strip(), head.stdout.strip())
    assert result == {"ok": True, "reachable": True, "reason_code": None}


# ---------------------------------------------------------------------------
# retry_transient (#290 fault-injection: transient GitHub API failure retries,
# a real negative fact never gets retried into a false PASS)
# ---------------------------------------------------------------------------

def test_retry_transient_succeeds_after_n_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            return {"ok": False, "reason_code": "default_branch_query_failed"}
        return {"ok": True, "default_branch": "main"}

    result = ev.retry_transient(flaky, attempts=5, backoff=0, sleep=lambda s: None)
    assert result == {"ok": True, "default_branch": "main"}
    assert calls["n"] == 3


def test_retry_transient_exhausts_budget_and_stays_unverified():
    calls = {"n": 0}

    def always_flaky():
        calls["n"] += 1
        return {"ok": False, "reason_code": "compare_query_failed"}

    result = ev.retry_transient(always_flaky, attempts=3, backoff=0, sleep=lambda s: None)
    assert result["ok"] is False
    assert result["reason_code"] == "compare_query_failed"
    assert calls["n"] == 3


def test_retry_transient_never_retries_a_real_negative_verdict():
    """A real observed fact (e.g. commit not reachable) is not a transport failure -- it must
    come back on the very first attempt, never retried into a different, possibly favorable,
    outcome."""
    calls = {"n": 0}

    def real_fail():
        calls["n"] += 1
        return {"ok": True, "reachable": False, "reason_code": "merge_commit_not_reachable"}

    result = ev.retry_transient(real_fail, attempts=5, backoff=0, sleep=lambda s: None)
    assert result == {"ok": True, "reachable": False, "reason_code": "merge_commit_not_reachable"}
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# resolve_release_commit
# ---------------------------------------------------------------------------

def test_resolve_release_commit_parses_real_shape(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(
        stdout=json.dumps({"target_commitish": "deadbeef", "draft": False, "prerelease": False})))
    result = ev.resolve_release_commit("acme/widgets", "v1.0.0")
    assert result == {"ok": True, "target_commitish": "deadbeef", "draft": False, "prerelease": False}


def test_resolve_release_commit_fails_closed_on_transport_error(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180:
                        _fake_completed(returncode=1, stderr="HTTP 404"))
    result = ev.resolve_release_commit("acme/widgets", "v1.0.0")
    assert result["ok"] is False
    assert result["reason_code"] == "deployment_release_query_failed"


def test_resolve_release_commit_fails_closed_on_malformed_json(monkeypatch):
    monkeypatch.setattr(ev, "_run", lambda args, cwd=None, timeout=180: _fake_completed(stdout="not json"))
    result = ev.resolve_release_commit("acme/widgets", "v1.0.0")
    assert result["ok"] is False
    assert result["reason_code"] == "deployment_release_response_malformed"


# ---------------------------------------------------------------------------
# DeploymentVerifier (#290 Fase 5) — composes ReleaseArtifactVerifier + InstallSmokeVerifier
# with BranchReachabilityVerifier to represent "deployed" as "installable from the
# reachability-proven, byte-verified release artifact".
# ---------------------------------------------------------------------------

def test_deployment_verifier_missing_environment_fails_closed():
    result = ev.DeploymentVerifier().verify("acme/widgets", "v1.0.0", "")
    assert result["ok"] is False
    assert result["reason_code"] == "deployment_environment_missing"


def test_deployment_verifier_release_query_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(ev, "resolve_release_commit",
                        lambda repo, tag: {"ok": False, "reason_code": "deployment_release_query_failed"})
    result = ev.DeploymentVerifier().verify("acme/widgets", "v1.0.0", "prod")
    assert result["ok"] is False
    assert result["reason_code"] == "deployment_release_query_failed"


def test_deployment_verifier_draft_release_blocks(monkeypatch):
    monkeypatch.setattr(ev, "resolve_release_commit",
                        lambda repo, tag: {"ok": True, "target_commitish": "deadbeef", "draft": True, "prerelease": False})
    result = ev.DeploymentVerifier().verify("acme/widgets", "v1.0.0", "prod")
    assert result["ok"] is False
    assert result["reason_code"] == "deployment_release_not_promotable"


def test_deployment_verifier_commit_mismatch_blocks(monkeypatch):
    monkeypatch.setattr(ev, "resolve_release_commit",
                        lambda repo, tag: {"ok": True, "target_commitish": "deadbeef", "draft": False, "prerelease": False})
    result = ev.DeploymentVerifier().verify("acme/widgets", "v1.0.0", "prod", expected_commit_sha="cafebabe")
    assert result["ok"] is False
    assert result["reason_code"] == "deployment_commit_mismatch"


def test_deployment_verifier_unreachable_commit_blocks(monkeypatch):
    monkeypatch.setattr(ev, "resolve_release_commit",
                        lambda repo, tag: {"ok": True, "target_commitish": "deadbeef", "draft": False, "prerelease": False})
    monkeypatch.setattr(ev, "verify_branch_reachability",
                        lambda repo, sha, **kw: {"ok": True, "reachable": False, "reason_code": "merge_commit_not_reachable"})
    result = ev.DeploymentVerifier().verify("acme/widgets", "v1.0.0", "prod")
    assert result["ok"] is False
    assert result["reason_code"] == "merge_commit_not_reachable"


def test_deployment_verifier_unverified_artifact_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "resolve_release_commit",
                        lambda repo, tag: {"ok": True, "target_commitish": "deadbeef", "draft": False, "prerelease": False})
    monkeypatch.setattr(ev, "verify_branch_reachability",
                        lambda repo, sha, **kw: {"ok": True, "reachable": True, "reason_code": None})
    monkeypatch.setattr(ev, "verify_release_artifacts", lambda repo, tag, names, workdir=None: {
        "checksums_verified": False, "checksum_reason_code": "checksum_manifest_absent",
        "signatures_verified": False, "sbom_present": False, "digests": {}, "assets_verified": [],
    })
    result = ev.DeploymentVerifier(workdir=str(tmp_path)).verify("acme/widgets", "v1.0.0", "prod")
    assert result["ok"] is False
    assert result["reason_code"] == "checksum_manifest_absent"


def test_deployment_verifier_all_dimensions_pass_reports_deployed(tmp_path, monkeypatch):
    wheel = tmp_path / "pkg-1.0.0-py3-none-any.whl"
    wheel.write_bytes(b"real wheel bytes")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    monkeypatch.setattr(ev, "resolve_release_commit",
                        lambda repo, tag: {"ok": True, "target_commitish": "deadbeef", "draft": False, "prerelease": False})
    monkeypatch.setattr(ev, "verify_branch_reachability",
                        lambda repo, sha, **kw: {"ok": True, "reachable": True, "reason_code": None})
    monkeypatch.setattr(ev, "verify_release_artifacts", lambda repo, tag, names, workdir=None: {
        "checksums_verified": True, "signatures_verified": True, "sbom_present": True,
        "digests": {wheel.name: digest}, "assets_verified": [wheel.name],
    })
    monkeypatch.setattr(ev, "run_install_smoke", lambda path, module_name="simplicio_loop":
                        {"passed": True, "reason_code": None, "version": "1.0.0"})
    result = ev.DeploymentVerifier(workdir=str(tmp_path)).verify("acme/widgets", "v1.0.0", "prod")
    assert result["ok"] is True
    assert result["environment"] == "prod"
    assert result["commit_sha"] == "deadbeef"
    assert result["artifact_digest"] == digest
    assert result["smoke"]["passed"] is True
    assert result["reason_code"] is None
    assert result["verified_at"]


def test_deployment_verifier_smoke_failure_reports_not_deployed(tmp_path, monkeypatch):
    wheel = tmp_path / "pkg-1.0.0-py3-none-any.whl"
    wheel.write_bytes(b"real wheel bytes")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    monkeypatch.setattr(ev, "resolve_release_commit",
                        lambda repo, tag: {"ok": True, "target_commitish": "deadbeef", "draft": False, "prerelease": False})
    monkeypatch.setattr(ev, "verify_branch_reachability",
                        lambda repo, sha, **kw: {"ok": True, "reachable": True, "reason_code": None})
    monkeypatch.setattr(ev, "verify_release_artifacts", lambda repo, tag, names, workdir=None: {
        "checksums_verified": True, "signatures_verified": True, "sbom_present": True,
        "digests": {wheel.name: digest}, "assets_verified": [wheel.name],
    })
    monkeypatch.setattr(ev, "run_install_smoke", lambda path, module_name="simplicio_loop":
                        {"passed": False, "reason_code": "import_smoke_failed"})
    result = ev.DeploymentVerifier(workdir=str(tmp_path)).verify("acme/widgets", "v1.0.0", "prod")
    assert result["ok"] is False
    assert result["smoke"]["passed"] is False
    assert result["reason_code"] == "import_smoke_failed"
