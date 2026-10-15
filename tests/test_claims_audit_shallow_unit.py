"""#1825: claims-audit check 8 must not FAIL because a shallow clone lacks the receipt's commit.

A receipt commit older than the clone depth is unreachable by construction. That is a missing-history
condition, not a forged receipt, so the check reports it as ``UNVERIFIED (shallow clone)`` and stays
green. A malformed or absent commit in a full clone is still a hard rejection (#294).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import claims_audit  # noqa: E402

UNVERIFIED = "UNVERIFIED (shallow clone)"
STAMP = "2026-01-01T00:00:00Z"


def _git(args, cwd):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, "git %s failed: %s" % (args, result.stderr)
    return result.stdout.strip()


def _make_history(root):
    """A real two-commit repo; returns (old_sha, head_sha). ``old_sha`` falls outside a depth-1 clone."""
    os.makedirs(root)
    _git(["init", "-q"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    shas = []
    for name in ("one", "two"):
        with open(os.path.join(root, name + ".txt"), "w", encoding="utf-8") as handle:
            handle.write(name + "\n")
        _git(["add", "."], root)
        _git(["commit", "-q", "-m", name], root)
        shas.append(_git(["rev-parse", "HEAD"], root))
    return shas[0], shas[1]


def _shallow_clone(source, dest):
    _git(["clone", "-q", "--depth", "1", "file://" + source, dest], os.path.dirname(dest))
    assert _git(["rev-parse", "--is-shallow-repository"], dest) == "true"


def _write_receipt(root, commit):
    path = os.path.join(root, "receipt.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"commit": commit, "generated_at": STAMP}, handle)
    return path


def _check_with_claim(root, receipt_rel):
    claims = [{"id": "c1", "doc": "README.md", "text_glob": "x", "status": "verified",
               "receipt": receipt_rel, "note": "n"}]
    saved = (claims_audit.REPO, claims_audit.CLAIMS, claims_audit.extract_claims)
    claims_audit.REPO, claims_audit.CLAIMS, claims_audit.extract_claims = root, claims, lambda: []
    try:
        return claims_audit.check_quantitative_claims()
    finally:
        claims_audit.REPO, claims_audit.CLAIMS, claims_audit.extract_claims = saved


def test_receipt_commit_outside_a_shallow_clone_is_unverified_not_failed():
    with tempfile.TemporaryDirectory() as tmp:
        old_sha, head_sha = _make_history(os.path.join(tmp, "full"))
        clone = os.path.join(tmp, "shallow")
        _shallow_clone(os.path.join(tmp, "full"), clone)
        assert not claims_audit._git_commit_exists(old_sha, clone)  # precondition: history really is missing
        assert claims_audit._git_commit_exists(head_sha, clone)

        ok, reason = claims_audit.validate_receipt(_write_receipt(clone, old_sha), clone)
        assert ok and reason.startswith(UNVERIFIED), reason
        assert old_sha in reason

        ok, detail = _check_with_claim(clone, "receipt.json")
        assert ok, detail
        assert UNVERIFIED in detail and "c1" in detail  # the pass is labelled, never silent


def test_receipt_commit_present_in_a_shallow_clone_is_still_verified():
    with tempfile.TemporaryDirectory() as tmp:
        _, head_sha = _make_history(os.path.join(tmp, "full"))
        clone = os.path.join(tmp, "shallow")
        _shallow_clone(os.path.join(tmp, "full"), clone)
        ok, reason = claims_audit.validate_receipt(_write_receipt(clone, head_sha), clone)
        assert ok and "bound to real commit" in reason and UNVERIFIED not in reason, reason
        ok, detail = _check_with_claim(clone, "receipt.json")
        assert ok and UNVERIFIED not in detail, detail


def test_malformed_commit_in_a_shallow_clone_is_still_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        _make_history(os.path.join(tmp, "full"))
        clone = os.path.join(tmp, "shallow")
        _shallow_clone(os.path.join(tmp, "full"), clone)
        for bogus in ("not-a-sha", "zzzzzzz", "12"):
            ok, reason = claims_audit.validate_receipt(_write_receipt(clone, bogus), clone)
            assert not ok and UNVERIFIED not in reason, (bogus, reason)
        ok, detail = _check_with_claim(clone, "receipt.json")
        assert not ok


def test_absent_commit_in_a_full_clone_is_still_a_hard_failure():
    with tempfile.TemporaryDirectory() as tmp:
        full = os.path.join(tmp, "full")
        _make_history(full)
        assert _git(["rev-parse", "--is-shallow-repository"], full) == "false"
        forged = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        ok, reason = claims_audit.validate_receipt(_write_receipt(full, forged), full)
        assert not ok and "does not resolve" in reason and UNVERIFIED not in reason, reason
        ok, detail = _check_with_claim(full, "receipt.json")
        assert not ok and UNVERIFIED not in detail


def test_is_shallow_repo_tells_full_and_shallow_clones_apart():
    with tempfile.TemporaryDirectory() as tmp:
        full = os.path.join(tmp, "full")
        _make_history(full)
        clone = os.path.join(tmp, "shallow")
        _shallow_clone(full, clone)
        assert claims_audit._is_shallow_repo(clone) is True
        assert claims_audit._is_shallow_repo(full) is False
        assert claims_audit._is_shallow_repo(os.path.join(tmp, "missing")) is False  # no such directory: not shallow
