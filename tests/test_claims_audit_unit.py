"""Unit tests for the claims_audit.py checks that were fixed by #70/#72/#76: authoritative
extension-point counting, bidirectional bundle-parity, and skill-count consistency.

These build a small throwaway fixture repo and monkeypatch claims_audit's module-level path
globals to point at it, so the checks run against a KNOWN state instead of the real repo (which
is already exercised end-to-end by `scripts/check.py` in CI).
"""
import json
import os
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import claims_audit  # noqa: E402


def _write(path, content=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _patched(fixture_root):
    """Context-manager-free monkeypatch: returns a restore() callable."""
    saved = {
        "REPO": claims_audit.REPO,
        "EXTENSION_POINTS_DOC": claims_audit.EXTENSION_POINTS_DOC,
    }
    claims_audit.REPO = fixture_root
    claims_audit.EXTENSION_POINTS_DOC = os.path.join(
        fixture_root, ".claude", "skills", "simplicio-tasks", "references", "extension-points.md")

    def restore():
        claims_audit.REPO = saved["REPO"]
        claims_audit.EXTENSION_POINTS_DOC = saved["EXTENSION_POINTS_DOC"]
    return restore


EXT_TABLE = """# Extension points — the 2 named binding points

| Extension point | What it does | LLM fallback (always available) |
|---|---|---|
| `orient` | a | b |
| `execute` | a | b |
"""


def test_extension_count_matches_actual_table():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "README.md"), "badge: 2 extension points")
        _write(os.path.join(tmp, "AGENTS.md"), "2 named binding points")
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-tasks", "references",
                             "extension-points.md"), EXT_TABLE)
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_extension_count()
            assert ok, detail
            assert "2" in detail
        finally:
            restore()


def test_extension_count_flags_claim_disagreeing_with_table():
    # #72: docs agreeing with EACH OTHER is not enough — a uniformly wrong count must fail now
    # that the check compares against the actual table row count.
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "README.md"), "badge: 5 extension points")
        _write(os.path.join(tmp, "AGENTS.md"), "5 named binding points")
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-tasks", "references",
                             "extension-points.md"), EXT_TABLE)  # table actually has 2 rows
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_extension_count()
            assert not ok, "a claim (5) disagreeing with the real table (2) must fail"
            assert "2" in detail and "5" in detail
        finally:
            restore()


def test_extension_count_catches_named_extension_points_phrasing():
    # The phrasing that escaped the original regex (#72 evidence: AGENTS.md "48 named extension
    # points").
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "AGENTS.md"), "This repo has 5 named extension points.")
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-tasks", "references",
                             "extension-points.md"), EXT_TABLE)  # table has 2 rows
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_extension_count()
            assert not ok, "the 'named extension points' phrasing must now be audited: %s" % detail
        finally:
            restore()


def _skills_tree(root, names):
    for n in names:
        _write(os.path.join(root, ".claude", "skills", n, "SKILL.md"), "---\n---\nbody\n")


def test_skill_count_matches_tree():
    with tempfile.TemporaryDirectory() as tmp:
        _skills_tree(tmp, ["simplicio-loop", "simplicio-tasks", "simplicio-orient"])
        _write(os.path.join(tmp, "README.md"), "badge: skills-3-blue")
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_skill_count()
            assert ok, detail
        finally:
            restore()


def test_skill_count_flags_stale_claim():
    # #76: "11 skills" badge vs an actual 6-directory tree — the drift class this check exists for.
    with tempfile.TemporaryDirectory() as tmp:
        _skills_tree(tmp, ["simplicio-loop", "simplicio-tasks", "simplicio-orient"])
        _write(os.path.join(tmp, "README.md"), "badge: skills-11-blue")
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_skill_count()
            assert not ok, "a stale skill-count claim (11) vs the real tree (3) must fail: %s" % detail
        finally:
            restore()


def _bundle_pairs_fixture(tmp):
    src_scripts = os.path.join(tmp, "scripts")
    bun_scripts = os.path.join(tmp, "simplicio_loop", "_bundle", "scripts")
    src_tests = os.path.join(tmp, "tests")
    bun_tests = os.path.join(tmp, "simplicio_loop", "_bundle", "tests")
    for d in (os.path.join(tmp, ".claude", "skills"),
              os.path.join(tmp, "simplicio_loop", "_bundle", "skills"),
              os.path.join(tmp, "hooks"),
              os.path.join(tmp, "simplicio_loop", "_bundle", "hooks")):
        os.makedirs(d, exist_ok=True)
    _write(os.path.join(src_scripts, "cross_agent_wiki.py"), "x = 1\n")
    _write(os.path.join(bun_scripts, "cross_agent_wiki.py"), "x = 1\n")
    _write(os.path.join(src_tests, "test_loop_e2e.py"), "y = 1\n")
    _write(os.path.join(bun_tests, "test_loop_e2e.py"), "y = 1\n")
    _write(os.path.join(tmp, "adapters", "claude", "adapter.py"), "z = 1\n")
    _write(os.path.join(tmp, "simplicio_loop", "_bundle", "adapters", "claude", "adapter.py"), "z = 1\n")
    _write(os.path.join(tmp, "packaging", "host-rules", "simplicio-loop-operator-flow.md"), "rule\n")
    _write(os.path.join(tmp, "simplicio_loop", "_bundle", "host-rules", "simplicio-loop-operator-flow.md"), "rule\n")
    return src_scripts, bun_scripts, src_tests, bun_tests


def test_bundle_parity_passes_when_mirrored():
    with tempfile.TemporaryDirectory() as tmp:
        _bundle_pairs_fixture(tmp)
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_bundle_parity()
            assert ok, detail
        finally:
            restore()


def test_bundle_parity_catches_orphan_in_bundle():
    # #70 repro (from the issue): rename/delete a source script -> the OLD copy is left behind in
    # `_bundle/` and previously passed the forward-only check while still shipping in the wheel.
    with tempfile.TemporaryDirectory() as tmp:
        src_scripts, bun_scripts, _, _ = _bundle_pairs_fixture(tmp)
        os.remove(os.path.join(src_scripts, "cross_agent_wiki.py"))  # simulate the rename/delete
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_bundle_parity()
            assert not ok, "an orphan file left in _bundle/ with no source must be caught"
            assert "orphan" in detail
        finally:
            restore()


def test_bundle_parity_catches_unshipped_adapter():
    # #1410: the Claude adapter `hooks/user_prompt_submit.py` imports must ship in the bundle.
    with tempfile.TemporaryDirectory() as tmp:
        _bundle_pairs_fixture(tmp)
        os.remove(os.path.join(tmp, "simplicio_loop", "_bundle", "adapters", "claude", "adapter.py"))
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_bundle_parity()
            assert not ok
            assert "adapters/claude: missing in bundle: adapter.py" in detail
        finally:
            restore()


def test_skill_pair_parity_passes_for_identical_shared_reference():
    with tempfile.TemporaryDirectory() as tmp:
        rel = os.path.join("quality-safety-delivery.md")
        content = "same bytes\n"
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-loop", "references", rel), content)
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-tasks", "references", rel), content)
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_skill_pair_parity()
            assert ok, detail
        finally:
            restore()


def test_skill_pair_parity_flags_divergent_shared_reference():
    with tempfile.TemporaryDirectory() as tmp:
        rel = os.path.join("quality-safety-delivery.md")
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-loop", "references", rel),
               "loop bytes\n")
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-tasks", "references", rel),
               "tasks bytes\n")
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_skill_pair_parity()
            assert not ok, "shared reference drift must fail: %s" % detail
            assert "quality-safety-delivery.md" in detail
        finally:
            restore()


def _init_git_repo(tmp):
    """Real git repo with one commit; returns its full sha. Used to prove receipt validation
    (#294) checks against ACTUAL git history, not a stubbed lookup.

    Retries each `git` invocation on a transient process-spawn error: rapid back-to-back
    subprocess creation on Windows occasionally raises `OSError: [WinError 50]` (request not
    supported) with no relation to git itself — a host/AV quirk, not a logic bug."""
    def _run(args):
        last_exc = None
        for attempt in range(5):
            try:
                r = subprocess.run(["git"] + args, cwd=tmp, capture_output=True, text=True)
                if r.returncode != 0:
                    raise RuntimeError("git %s failed: %s" % (args, r.stderr))
                return r
            except OSError as e:
                last_exc = e
                time.sleep(0.05 * (attempt + 1))
        raise last_exc
    _run(["init", "-q"])
    _run(["config", "user.email", "test@example.com"])
    _run(["config", "user.name", "Test"])
    _write(os.path.join(tmp, "README.md"), "hello\n")
    _run(["add", "."])
    _run(["commit", "-q", "-m", "init"])
    r = _run(["rev-parse", "HEAD"])
    return r.stdout.strip()


def _claims_patched(fixture_root, claims):
    restore_repo = _patched(fixture_root)
    saved_claims = claims_audit.CLAIMS
    claims_audit.CLAIMS = claims

    def restore():
        restore_repo()
        claims_audit.CLAIMS = saved_claims
    return restore


def test_verified_claim_with_receipt_bound_to_real_commit_passes():
    with tempfile.TemporaryDirectory() as tmp:
        sha = _init_git_repo(tmp)
        _write(os.path.join(tmp, "receipts", "r1.json"),
               json.dumps({"commit": sha, "generated_at": "2026-01-01T00:00:00Z"}))
        claims = [{"id": "c1", "doc": "README.md", "text_glob": "x", "status": "verified",
                   "receipt": "receipts/r1.json", "note": "n"}]
        restore = _claims_patched(tmp, claims)
        try:
            ok, detail = claims_audit.check_quantitative_claims()
            assert ok, detail
        finally:
            restore()


def test_verified_claim_with_foreign_commit_receipt_is_rejected():
    # #294: a receipt whose `commit` field is a fabricated/foreign hash (not reachable in this
    # repo's history) must NOT be able to back a "verified" claim.
    with tempfile.TemporaryDirectory() as tmp:
        _init_git_repo(tmp)
        foreign_sha = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        _write(os.path.join(tmp, "receipts", "r2.json"),
               json.dumps({"commit": foreign_sha, "generated_at": "2026-01-01T00:00:00Z"}))
        claims = [{"id": "c2", "doc": "README.md", "text_glob": "x", "status": "verified",
                   "receipt": "receipts/r2.json", "note": "n"}]
        restore = _claims_patched(tmp, claims)
        try:
            ok, detail = claims_audit.check_quantitative_claims()
            assert not ok, "a receipt citing a foreign/fabricated commit must be rejected"
            assert "another commit/version rejected" in detail or "does not resolve" in detail
        finally:
            restore()


def test_verified_claim_with_receipt_missing_commit_field_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        _init_git_repo(tmp)
        _write(os.path.join(tmp, "receipts", "r3.json"),
               json.dumps({"generated_at": "2026-01-01T00:00:00Z"}))
        claims = [{"id": "c3", "doc": "README.md", "text_glob": "x", "status": "verified",
                   "receipt": "receipts/r3.json", "note": "n"}]
        restore = _claims_patched(tmp, claims)
        try:
            ok, detail = claims_audit.check_quantitative_claims()
            assert not ok, "a receipt with no 'commit' field must be rejected"
            assert "missing 'commit'" in detail
        finally:
            restore()


def test_verified_claim_with_receipt_missing_timestamp_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        sha = _init_git_repo(tmp)
        _write(os.path.join(tmp, "receipts", "r4.json"), json.dumps({"commit": sha}))
        claims = [{"id": "c4", "doc": "README.md", "text_glob": "x", "status": "verified",
                   "receipt": "receipts/r4.json", "note": "n"}]
        restore = _claims_patched(tmp, claims)
        try:
            ok, detail = claims_audit.check_quantitative_claims()
            assert not ok, "a receipt with no timestamp must be rejected"
            assert "missing 'generated_at'/'created_at'" in detail
        finally:
            restore()


def test_unverified_claim_with_receipt_still_requires_the_file_to_exist():
    # Unverified claims are not required to have a git-bound receipt, but if a receipt path IS
    # declared it must still exist (pre-existing behavior, unchanged by #294).
    with tempfile.TemporaryDirectory() as tmp:
        _init_git_repo(tmp)
        claims = [{"id": "c5", "doc": "README.md", "text_glob": "x", "status": "unverified",
                   "receipt": "receipts/missing.json", "note": "n"}]
        restore = _claims_patched(tmp, claims)
        try:
            ok, detail = claims_audit.check_quantitative_claims()
            assert not ok
            assert "receipt missing" in detail
        finally:
            restore()


HEADER = "<!-- simplicio-contract:begin -->\ncontract: %s/x\nschema: simplicio.skill-reference/v1\n<!-- simplicio-contract:end -->\n"


def test_skill_pair_parity_ignores_the_contract_headers_own_skill_name():
    # #1342: each skill's immutable header names itself (`contract: simplicio-loop/x` vs `simplicio-tasks/x`), so the
    # shared references cannot be byte-identical; the rest of the file must be.
    with tempfile.TemporaryDirectory() as tmp:
        body = "\n# Shared reference\n\nsame body\n"
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-loop", "references", "x.md"),
               HEADER % "simplicio-loop" + body)
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-tasks", "references", "x.md"),
               HEADER % "simplicio-tasks" + body)
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_skill_pair_parity()
            assert ok, detail
        finally:
            restore()


def test_skill_pair_parity_still_flags_a_body_difference_behind_the_header():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-loop", "references", "x.md"),
               HEADER % "simplicio-loop" + "\nloop body\n")
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-tasks", "references", "x.md"),
               HEADER % "simplicio-tasks" + "\ntasks body\n")
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_skill_pair_parity()
            assert not ok and "x.md" in detail, detail
        finally:
            restore()


def test_skill_pair_parity_ignores_unilateral_files_and_skill_md():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-loop", "references", "only-loop.md"),
               "exists only here\n")
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-loop", "SKILL.md"), "loop skill\n")
        _write(os.path.join(tmp, ".claude", "skills", "simplicio-tasks", "SKILL.md"), "tasks skill drift\n")
        restore = _patched(tmp)
        try:
            ok, detail = claims_audit.check_skill_pair_parity()
            assert ok, detail
        finally:
            restore()


def test_core_mode_does_not_execute_satellite_selftests():
    with tempfile.TemporaryDirectory() as tmp:
        marker = os.path.join(tmp, "satellite-ran")
        core = """import sys\ndef selftest(): pass\nif __name__ == '__main__' and sys.argv[1] == \"selftest\": print('PASS')\n"""
        satellite = """import pathlib,sys\ndef selftest(): pass\nif __name__ == '__main__' and sys.argv[1] == \"selftest\": pathlib.Path(%r).write_text('ran'); print('PASS')\n""" % marker
        _write(os.path.join(tmp, "scripts", "core.py"), core)
        _write(os.path.join(tmp, "scripts", "autoresearch.py"), satellite)
        restore = _patched(tmp)
        saved_scripts = claims_audit.SELFTEST_SCRIPTS
        saved_core = claims_audit.CORE_MODE
        claims_audit.SELFTEST_SCRIPTS = ["scripts/core.py", "scripts/autoresearch.py"]
        claims_audit.CORE_MODE = True
        try:
            ok, detail = claims_audit.check_commands_run()
            assert ok, detail
            assert "satellite selftests excluded=1" in detail
            assert not os.path.exists(marker)
            claims_audit.CORE_MODE = False
            ok, detail = claims_audit.check_commands_run()
            assert ok, detail
            assert detail == "all cited commands run"
            assert os.path.exists(marker)
        finally:
            claims_audit.SELFTEST_SCRIPTS = saved_scripts
            claims_audit.CORE_MODE = saved_core
            restore()


def test_core_mode_does_not_probe_satellite_cli():
    with tempfile.TemporaryDirectory() as tmp:
        marker = os.path.join(tmp, "satellite-cli-ran")
        _write(os.path.join(tmp, "README.md"),
               "`python3 scripts/autoresearch.py run --goal test`\n")
        _write(os.path.join(tmp, "scripts", "autoresearch.py"),
               "import pathlib\npathlib.Path(%r).write_text('ran')\n" % marker)
        restore = _patched(tmp)
        saved_core = claims_audit.CORE_MODE
        claims_audit.CORE_MODE = True
        try:
            ok, detail = claims_audit.check_prose_commands()
            assert ok, detail
            assert "satellite command probes excluded=1" in detail
            assert not os.path.exists(marker)
            claims_audit.CORE_MODE = False
            ok, detail = claims_audit.check_prose_commands()
            assert ok, detail
            assert detail == "all doc-cited commands validated against --describe-cli"
            assert os.path.exists(marker)
        finally:
            claims_audit.CORE_MODE = saved_core
            restore()


def test_core_mode_keeps_satellite_selftest_meta_check_static():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "scripts", "autoresearch.py"),
               'def selftest(): pass\nif "selftest" in __import__("sys").argv: selftest()\n')
        restore = _patched(tmp)
        saved_scripts = claims_audit.SELFTEST_SCRIPTS
        saved_core = claims_audit.CORE_MODE
        claims_audit.SELFTEST_SCRIPTS = []
        claims_audit.CORE_MODE = True
        try:
            ok, detail = claims_audit.check_commands_run()
            assert not ok
            assert "scripts/autoresearch.py" in detail
        finally:
            claims_audit.SELFTEST_SCRIPTS = saved_scripts
            claims_audit.CORE_MODE = saved_core
            restore()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_claims_audit")
