"""Unit coverage for the LOCAL_ONLY/REMOTE_READY/REMOTE_MEASURED tri-state (#286).

`simplicio_loop/remote_worker_measurement.py` backs the `scripts/doctor.py`
"remote worker (#286)" check. These tests operate against an isolated `tmp_path`
"repo" so they never touch this checkout's real `.simplicio-loop/orchestrator/` state.
"""
import json
import os
import subprocess
import sys

import pytest

from simplicio_loop.remote_worker_measurement import (
    ACCEPTED_PROOFS, LOCAL_ONLY, REMOTE_MEASURED, REMOTE_READY,
    clear_measurement, is_remote_configured, measurement_path, read_measurement,
    record_measurement, remote_worker_status,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_local_only_when_unconfigured_and_unmeasured(tmp_path):
    status = remote_worker_status(str(tmp_path), env={})
    assert status["status"] == LOCAL_ONLY
    assert status["configured"] is False
    assert status["measurement"] is None


def test_remote_ready_when_configured_but_unmeasured(tmp_path):
    status = remote_worker_status(str(tmp_path), env={"SIMPLICIO_REMOTE_QUEUE_URL": "https://q.example"})
    assert status["status"] == REMOTE_READY
    assert status["configured"] is True
    assert status["measurement"] is None


def test_remote_ready_recognizes_environment_id_too(tmp_path):
    status = remote_worker_status(str(tmp_path), env={"SIMPLICIO_REMOTE_ENVIRONMENT_ID": "prod-queue"})
    assert status["status"] == REMOTE_READY


def test_remote_measured_after_recording_an_accepted_proof(tmp_path):
    payload = record_measurement(str(tmp_path), proof="tests/test_remote_worker_http_e2e.py")
    assert payload["status"] == REMOTE_MEASURED
    assert payload["proof"] == "tests/test_remote_worker_http_e2e.py"
    assert "measured_at" in payload and "host" in payload

    status = remote_worker_status(str(tmp_path), env={})
    assert status["status"] == REMOTE_MEASURED
    assert status["measurement"]["proof"] == "tests/test_remote_worker_http_e2e.py"


def test_measurement_survives_even_without_current_env_config(tmp_path):
    # A prior genuine proof is durable evidence -- doctor should not "forget" it just
    # because the current shell happens not to have the remote queue URL exported.
    record_measurement(str(tmp_path), proof="tests/test_remote_worker_e2e.py")
    status = remote_worker_status(str(tmp_path), env={})
    assert status["status"] == REMOTE_MEASURED


def test_record_measurement_rejects_unrecognized_proof(tmp_path):
    with pytest.raises(ValueError):
        record_measurement(str(tmp_path), proof="i-made-this-up")


def test_record_measurement_requires_explicit_recognition_for_physical_tier(tmp_path):
    # physical-two-machine IS accepted, but only via an explicit call -- nothing in this
    # module calls it automatically, which is what "never fabricate" means in practice.
    assert "physical-two-machine" in ACCEPTED_PROOFS
    payload = record_measurement(str(tmp_path), proof="physical-two-machine",
                                  extra={"note": "manually observed across two real laptops"})
    assert payload["proof"] == "physical-two-machine"


def test_clear_measurement_removes_the_receipt(tmp_path):
    record_measurement(str(tmp_path), proof="tests/test_remote_worker_http_e2e.py")
    assert measurement_path(str(tmp_path)).is_file()
    assert clear_measurement(str(tmp_path)) is True
    assert read_measurement(str(tmp_path)) is None
    # calling clear again on an already-clear repo is a no-op, not an error
    assert clear_measurement(str(tmp_path)) is False


def test_read_measurement_ignores_corrupt_receipt(tmp_path):
    path = measurement_path(str(tmp_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert read_measurement(str(tmp_path)) is None


def test_read_measurement_ignores_receipt_with_unrecognized_proof(tmp_path):
    path = measurement_path(str(tmp_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": REMOTE_MEASURED, "proof": "hand-waved"}), encoding="utf-8")
    assert read_measurement(str(tmp_path)) is None


def test_is_remote_configured_false_for_blank_env_values(tmp_path):
    assert is_remote_configured({"SIMPLICIO_REMOTE_QUEUE_URL": "   "}) is False


def test_cli_status_reports_json(tmp_path):
    script = os.path.join(REPO, "scripts", "remote_worker_measurement.py")
    env = dict(os.environ)
    env.pop("SIMPLICIO_REMOTE_QUEUE_URL", None)
    env.pop("SIMPLICIO_REMOTE_ENVIRONMENT_ID", None)
    r = subprocess.run([sys.executable, script, "status", "--json"], cwd=REPO,
                        capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["status"] in (LOCAL_ONLY, REMOTE_READY, REMOTE_MEASURED)


def test_cli_record_rejects_unknown_proof_choice():
    script = os.path.join(REPO, "scripts", "remote_worker_measurement.py")
    r = subprocess.run([sys.executable, script, "record", "--proof", "bogus"], cwd=REPO,
                        capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    assert r.returncode == 2, r.stdout + r.stderr


def test_cli_record_physical_tier_requires_note():
    script = os.path.join(REPO, "scripts", "remote_worker_measurement.py")
    r = subprocess.run([sys.executable, script, "record", "--proof", "physical-two-machine"],
                        cwd=REPO, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "--note" in (r.stdout + r.stderr)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_remote_worker_measurement_unit")
