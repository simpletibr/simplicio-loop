"""Aggregate the deterministic `selftest` of every worker that ships one.

Each worker with a model-free `selftest` proves its own contract with no external services. This
runs them as subprocesses and asserts exit 0 + a PASS line — so `python3 scripts/check.py`
(or pytest) re-proves them on every change.
"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# worker script → the subcommand that runs its self-check
SELFTESTS = [
    ("scripts/loop_journal.py", "selftest"),
    ("scripts/savings_harness.py", "selftest"),
    ("scripts/task_anchor.py", "selftest"),
    ("scripts/task_backlog.py", "selftest"),
    ("scripts/test_infra_probe.py", "selftest"),
    ("scripts/pr_evidence.py", "selftest"),
    ("scripts/flow_audit.py", "selftest"),
    ("scripts/impact_audit.py", "selftest"),
    ("scripts/toon_codec.py", "selftest"),
    ("scripts/autoresearch.py", "selftest"),
    ("scripts/clean_env_contract.py", "selftest"),
    ("scripts/completion_oracle.py", "selftest"),
    ("scripts/mirror_parity.py", "selftest"),
    ("scripts/run_state.py", "selftest"),
]


def _run(script, sub):
    return subprocess.run([sys.executable, os.path.join(REPO, script), sub],
                          capture_output=True, text=True, cwd=REPO,
                          stdin=subprocess.DEVNULL)


def test_loop_journal_selftest():
    r = _run("scripts/loop_journal.py", "selftest")
    assert r.returncode == 0, "loop_journal selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


@pytest.mark.satellite
def test_savings_harness_selftest():
    r = _run("scripts/savings_harness.py", "selftest")
    assert r.returncode == 0, "savings_harness selftest failed:\n%s%s" % (r.stdout, r.stderr)
    # savings_harness prints "selftest passed" / "OK"; accept either a 0 exit with no FAIL
    assert "FAIL" not in r.stdout.upper() or "PASS" in r.stdout.upper(), r.stdout


def test_task_anchor_selftest():
    r = _run("scripts/task_anchor.py", "selftest")
    assert r.returncode == 0, "task_anchor selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_test_infra_probe_selftest():
    r = _run("scripts/test_infra_probe.py", "selftest")
    assert r.returncode == 0, "test_infra_probe selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_task_backlog_selftest():
    r = _run("scripts/task_backlog.py", "selftest")
    assert r.returncode == 0, "task_backlog selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_pr_evidence_selftest():
    r = _run("scripts/pr_evidence.py", "selftest")
    assert r.returncode == 0, "pr_evidence selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_flow_audit_selftest():
    r = _run("scripts/flow_audit.py", "selftest")
    assert r.returncode == 0, "flow_audit selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_impact_audit_selftest():
    r = _run("scripts/impact_audit.py", "selftest")
    assert r.returncode == 0, "impact_audit selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_watcher_verify_selftest():
    r = _run("scripts/watcher_verify.py", "selftest")
    assert r.returncode == 0, "watcher_verify selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_handoff_selftest():
    r = _run("scripts/handoff.py", "selftest")
    assert r.returncode == 0, "handoff selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_install_services_selftest():
    r = _run("scripts/install_services.py", "selftest")
    assert r.returncode == 0, "install_services selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_mirror_manifest_selftest():
    r = _run("scripts/mirror_manifest.py", "selftest")
    assert r.returncode == 0, "mirror_manifest selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_toon_codec_selftest():
    r = _run("scripts/toon_codec.py", "selftest")
    assert r.returncode == 0, "toon_codec selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


@pytest.mark.satellite
def test_autoresearch_selftest():
    r = _run("scripts/autoresearch.py", "selftest")
    assert r.returncode == 0, "autoresearch selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


@pytest.mark.satellite
def test_e2e_demo_selftest():
    r = _run("scripts/e2e_demo.py", "selftest")
    assert r.returncode == 0, "e2e_demo selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


@pytest.mark.satellite
def test_check_e2e_demo_contract_selftest():
    r = _run("scripts/check_e2e_demo_contract.py", "selftest")
    assert r.returncode == 0, "check_e2e_demo_contract selftest failed:\n%s%s" % (
        r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_check_e2e_installed_selftest():
    r = _run("scripts/check_e2e_installed.py", "selftest")
    assert r.returncode == 0, "check_e2e_installed selftest failed:\n%s%s" % (
        r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_mirror_parity_selftest():
    r = _run("scripts/mirror_parity.py", "selftest")
    assert r.returncode == 0, "mirror_parity selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_clean_env_contract_selftest():
    r = _run("scripts/clean_env_contract.py", "selftest")
    assert r.returncode == 0, "clean_env_contract selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_completion_oracle_selftest():
    r = _run("scripts/completion_oracle.py", "selftest")
    assert r.returncode == 0, "completion_oracle selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_run_state_selftest():
    r = _run("scripts/run_state.py", "selftest")
    assert r.returncode == 0, "run_state selftest failed:\n%s%s" % (r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_worker_selftests")
