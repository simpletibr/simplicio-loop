"""Contract tests ("testes de contrato") — every worker script that ships a `selftest` verb must
honor the SAME CLI shape, regardless of what it internally does:

  * `<script>.py selftest` exits 0 and prints something recognizable as a pass (never silent).
  * a bogus/unknown verb never crashes with an uncaught traceback — a broken CLI contract is
    itself a defect, independent of whether the underlying feature works.

This is the cross-script surface contract; `test_worker_selftests.py` already re-proves each
selftest's own PASS marker in depth — this file only proves the CLI SHAPE is consistent.
"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# scripts whose selftest is the deterministic, model-free, no-external-service contract proof
WORKERS_WITH_SELFTEST = [
    "loop_journal.py",
    "task_anchor.py",
    "task_contract.py",
    "task_backlog.py",
    "run_state.py",
    "evidence_receipt.py",
    "completion_oracle.py",
    "mirror_parity.py",
    "clean_env_contract.py",
    "pr_evidence.py",
    "flow_audit.py",
    "impact_audit.py",
    "toon_codec.py",
    "claims_manifest.py",
]

SATELLITE_WORKERS_WITH_SELFTEST = [
    "autoresearch.py",
    "fan_out.py",
    "schema_verify.py",
]


def _run(script, *args):
    return subprocess.run([sys.executable, os.path.join(REPO, "scripts", script)] + list(args),
                          capture_output=True, text=True, cwd=REPO, timeout=60,
                          stdin=subprocess.DEVNULL)


def test_every_worker_selftest_exits_zero():
    failures = []
    for script in WORKERS_WITH_SELFTEST:
        r = _run(script, "selftest")
        if r.returncode != 0:
            failures.append("%s: exit %d\n%s%s" % (script, r.returncode, r.stdout, r.stderr))
    assert not failures, "selftest contract broken for:\n" + "\n---\n".join(failures)


def test_every_worker_selftest_prints_a_pass_marker():
    failures = []
    for script in WORKERS_WITH_SELFTEST:
        r = _run(script, "selftest")
        combined = (r.stdout + r.stderr).upper()
        if "PASS" not in combined and "OK" not in combined:
            failures.append("%s: no PASS/OK marker in output:\n%s" % (script, r.stdout))
    assert not failures, "\n---\n".join(failures)


def test_every_worker_survives_an_unknown_verb_without_traceback():
    failures = []
    for script in WORKERS_WITH_SELFTEST:
        r = _run(script, "definitely-not-a-real-verb-xyz")
        if "Traceback (most recent call last)" in r.stderr:
            failures.append("%s: uncaught traceback on unknown verb:\n%s" % (script, r.stderr))
    assert not failures, "\n---\n".join(failures)


@pytest.mark.satellite
def test_every_satellite_worker_selftest_exits_zero():
    failures = []
    for script in SATELLITE_WORKERS_WITH_SELFTEST:
        r = _run(script, "selftest")
        if r.returncode != 0:
            failures.append("%s: exit %d\n%s%s" % (script, r.returncode, r.stdout, r.stderr))
    assert not failures, "satellite selftest contract broken for:\n" + "\n---\n".join(failures)


@pytest.mark.satellite
def test_every_satellite_worker_selftest_prints_a_pass_marker():
    failures = []
    for script in SATELLITE_WORKERS_WITH_SELFTEST:
        r = _run(script, "selftest")
        combined = (r.stdout + r.stderr).upper()
        if "PASS" not in combined and "OK" not in combined:
            failures.append("%s: no PASS/OK marker in output:\n%s" % (script, r.stdout))
    assert not failures, "\n---\n".join(failures)


@pytest.mark.satellite
def test_every_satellite_worker_survives_an_unknown_verb_without_traceback():
    failures = []
    for script in SATELLITE_WORKERS_WITH_SELFTEST:
        r = _run(script, "definitely-not-a-real-verb-xyz")
        if "Traceback (most recent call last)" in r.stderr:
            failures.append("%s: uncaught traceback on unknown verb:\n%s" % (script, r.stderr))
    assert not failures, "\n---\n".join(failures)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_worker_cli_contract")
