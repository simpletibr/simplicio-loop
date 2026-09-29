"""System tests — the whole `simplicio-loop` local gate as a black box, driven exactly the way a
git pre-push hook drives it (see AGENTS.md § Tests & local checks). These don't test one script;
they test the SYSTEM: `scripts/check.py` orchestrating the audit + the full test tree together.

`--tests-only` is asserted to PASS (that's this very suite, self-consistently green). `--audit-only`
is asserted to run to completion and print every numbered claims-audit check without crashing —
its pass/fail verdict is reported but not hard-asserted, since claims-audit tracks doc/bundle
drift that is orthogonal to "does the test suite work" and may legitimately be red between doc
edits; a hard assert here would make an unrelated doc change fail the *test* suite.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(REPO, "scripts", "check.py")

# `--tests-only`/no-flags re-run this very test file (it lives under tests/), which would spawn
# scripts/check.py from inside scripts/check.py forever. This guard lets the OUTER invocation do
# the real system-level run while the INNER (nested) one is a cheap no-op — one level of nesting,
# never infinite.
NESTED_GUARD = "SIMPLICIO_SYSTEM_TEST_NESTED"


# The gate runs only the tests a change can affect (scripts/impact_tests.py, against `--base`). Against
# HEAD a clean tree selects none, so the runs below prove the gate's plumbing end to end without
# re-running the whole suite inside one test; a dirty tree runs exactly the tests it can affect.
IMPACT_BASE = ["--base", "HEAD"]


def _run(args):
    env = dict(os.environ)
    env[NESTED_GUARD] = "1"
    return subprocess.run([sys.executable, CHECK] + args, capture_output=True, text=True,
                          cwd=REPO, timeout=300, env=env, stdin=subprocess.DEVNULL)


def test_tests_only_gate_is_green():
    if os.environ.get(NESTED_GUARD):
        return
    r = _run(["--tests-only", *IMPACT_BASE])
    assert r.returncode == 0, "the test suite itself must always be green:\n%s%s" % (
        r.stdout, r.stderr)
    assert "check: PASS" in r.stdout, r.stdout


def test_audit_only_runs_every_numbered_check_without_crashing():
    r = _run(["--audit-only"])
    assert "Traceback (most recent call last)" not in r.stderr, r.stderr
    for n in range(1, 7):
        assert ("] %d " % n) in r.stdout, "check %d missing from audit output:\n%s" % (
            n, r.stdout)
    assert r.returncode in (0, 1)


def test_mirror_parity_only_runs_as_distinct_gate():
    r = _run(["--mirror-parity-only"])
    assert "=== mirror-parity ===" in r.stdout
    assert "check:" in r.stdout
    assert r.returncode in (0, 1)


def test_clean_env_only_runs_as_distinct_gate():
    r = _run(["--clean-env-only"])
    assert "=== clean-env-contract ===" in r.stdout
    assert "check:" in r.stdout
    assert r.returncode in (0, 1)


def test_check_with_no_flags_runs_both_audit_and_tests():
    if os.environ.get(NESTED_GUARD):
        return
    r = _run(IMPACT_BASE)
    assert "=== claims-audit ===" in r.stdout
    assert "=== mirror-parity ===" in r.stdout
    assert "=== clean-env-contract ===" in r.stdout
    assert "pytest tests/" in r.stdout or "stdlib self-run" in r.stdout or "no test is affected" in r.stdout
    assert "check: %s" % ("PASS" if r.returncode == 0 else "FAIL") in r.stdout


def test_sync_plugin_check_verb_runs_without_crashing():
    # System-level packaging invariant (#74): plugin/ must stay a mirror of source; the --check
    # verb must run to completion and report drift as data, never a traceback.
    r = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "sync_plugin.py"), "--check"],
                       capture_output=True, text=True, cwd=REPO, timeout=60,
                       stdin=subprocess.DEVNULL)
    assert "Traceback (most recent call last)" not in r.stderr, r.stderr
    assert r.returncode in (0, 1)
    assert "plugin sync:" in r.stdout


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_system_check")
