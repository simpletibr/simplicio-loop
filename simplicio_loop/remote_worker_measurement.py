"""Tri-state remote-worker capability measurement for `scripts/doctor.py` (issue #286).

The loop's remote-worker protocol (`simplicio.remote-worker/v2`,
`docs/REMOTE_QUEUE.md`) can be exercised entirely on one machine — the repo's own
test suite proves the wire contract with real, separate OS processes talking over
a real HTTP socket (`tests/test_remote_worker_http_e2e.py`). That is real evidence
the *protocol* works, but it is not the same claim as "a task created on one
physical device was discovered/claimed/executed by a worker on a different
physical device" — the epic's actual acceptance criterion. `doctor.py` must never
blur those two things together, so it reports three distinct states instead of a
single "remote worker: ok/fail" boolean:

  LOCAL_ONLY      -- no remote queue destination is configured
                     (`SIMPLICIO_REMOTE_QUEUE_URL` / `SIMPLICIO_REMOTE_ENVIRONMENT_ID`
                     both unset). The loop only ever dispatches in-process /
                     same-host. This is the default and is NOT a failure.
  REMOTE_READY    -- a remote queue destination is configured, but this checkout
                     has never recorded a passing cross-process proof. Configured,
                     unproven.
  REMOTE_MEASURED -- a real proof has actually run and recorded a measurement
                     receipt via `record_measurement()`. Only ever set by a proof
                     that genuinely passed in the current process -- never
                     inferred from source code merely existing, and never
                     upgraded to "physical multi-machine" without a human
                     recording that tier explicitly (see ACCEPTED_PROOFS).

`scripts/remote_worker_measurement.py` is the CLI: `status` prints the tri-state,
`record` re-runs an accepted proof for real and only writes the receipt if it
actually passed, `clear` deletes the receipt to force a fresh re-proof.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

LOCAL_ONLY = "LOCAL_ONLY"
REMOTE_READY = "REMOTE_READY"
REMOTE_MEASURED = "REMOTE_MEASURED"
STATES = (LOCAL_ONLY, REMOTE_READY, REMOTE_MEASURED)

# Proofs this repo recognizes as satisfying "the #366 HTTP-loopback E2E or better".
# "physical-two-machine" exists so a human who actually runs the protocol across two
# real devices can record that tier -- nothing in this module fabricates it
# automatically; there is no code path that sets this proof without an operator
# explicitly invoking `record --proof physical-two-machine` after a genuine run.
ACCEPTED_PROOFS = (
    "tests/test_remote_worker_http_e2e.py",
    "tests/test_remote_worker_e2e.py",
    "physical-two-machine",
)

# The strongest proof this repo can run today without a second physical machine.
DEFAULT_PROOF = "tests/test_remote_worker_http_e2e.py"

DEFAULT_MEASUREMENT_PATH = ".simplicio-loop/orchestrator/remote-worker/measurement.json"

REMOTE_ENV_VARS = ("SIMPLICIO_REMOTE_QUEUE_URL", "SIMPLICIO_REMOTE_ENVIRONMENT_ID")


def _git_sha(repo: str) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                              text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def measurement_path(repo: str) -> Path:
    return Path(repo) / DEFAULT_MEASUREMENT_PATH


def is_remote_configured(env: Optional[Dict[str, str]] = None) -> bool:
    e = env if env is not None else os.environ
    return any(bool(e.get(v, "").strip()) for v in REMOTE_ENV_VARS)


def record_measurement(repo: str, *, proof: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Write a REMOTE_MEASURED receipt. Callers MUST only call this after `proof` has
    genuinely passed in the current process -- never speculatively."""
    if proof not in ACCEPTED_PROOFS:
        raise ValueError("proof %r is not a recognized cross-process proof (accepted: %s)"
                          % (proof, ", ".join(ACCEPTED_PROOFS)))
    payload: Dict[str, Any] = {
        "status": REMOTE_MEASURED,
        "proof": proof,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": _git_sha(repo),
        "host": platform.node(),
    }
    if extra:
        payload["extra"] = extra
    path = measurement_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def clear_measurement(repo: str) -> bool:
    path = measurement_path(repo)
    if path.is_file():
        path.unlink()
        return True
    return False


def read_measurement(repo: str) -> Optional[Dict[str, Any]]:
    path = measurement_path(repo)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict) or data.get("status") != REMOTE_MEASURED:
        return None
    if data.get("proof") not in ACCEPTED_PROOFS:
        return None
    return data


def remote_worker_status(repo: str, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Compute the tri-state status. Never fabricates REMOTE_MEASURED -- that only
    comes from a receipt a genuinely-passing proof wrote via `record_measurement()`."""
    configured = is_remote_configured(env)
    measurement = read_measurement(repo)
    if measurement is not None:
        status = REMOTE_MEASURED
    elif configured:
        status = REMOTE_READY
    else:
        status = LOCAL_ONLY
    return {
        "status": status,
        "configured": configured,
        "measurement": measurement,
    }


def run_proof(repo: str, proof: str, *, timeout: int = 300) -> "subprocess.CompletedProcess[str]":
    """Actually execute the named proof as a real subprocess (pytest) and return its
    CompletedProcess. Does NOT record a measurement -- callers decide what to do with
    the result (see `record` in the CLI, which only records on returncode == 0)."""
    if proof not in ACCEPTED_PROOFS or proof == "physical-two-machine":
        raise ValueError("%r cannot be run automatically; record it manually after a genuine run" % proof)
    import sys
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", proof],
        cwd=repo, capture_output=True, text=True, timeout=timeout,
    )
