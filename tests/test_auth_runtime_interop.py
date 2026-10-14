"""The REAL Runtime still accepts the shared login file after the loop refreshed it (review of #1584, item 1).

The Runtime's StoredVerification has no serde(default), so a `verification` block without all of its keys makes the
WHOLE file unreadable for it ("invalid Runtime login state ... missing field auth_base_url"). This test runs
`simplicio auth status --json` on a file the loop wrote. Everything is FAKE and local: a temp HOME, fake tokens, and the
Runtime runs in an empty network namespace (`unshare -rn`), so nothing can leave the machine. Skipped when the Runtime,
`unshare` or user namespaces are missing.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

from simplicio_loop import auth

RUNTIME = shutil.which("simplicio")
UNSHARE = shutil.which("unshare")
REJECTED = "invalid Runtime login state"

pytestmark = pytest.mark.skipif(RUNTIME is None or UNSHARE is None or os.name == "nt",
                                reason="needs the Simplicio Runtime and unshare on a POSIX host")


@pytest.fixture(scope="module", autouse=True)
def offline_namespace():
    probe = subprocess.run([UNSHARE, "-rn", "true"], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip(f"no network namespace to isolate the Runtime: {probe.stderr.strip()}")


def runtime_status(tmp_path, login_file) -> str:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "SIMPLICIO_AUTH_FILE": str(login_file)}
    done = subprocess.run([UNSHARE, "-rn", RUNTIME, "auth", "status", "--json"], env=env, capture_output=True,
                          text=True, timeout=60, stdin=subprocess.DEVNULL)
    return done.stdout + done.stderr


ENTITLED = {"access_token": "FAKE_NEW", "refresh_token": "FAKE_REF2", "expires_in": 900,
            "entitlement": {"active": True, "tier": "pro", "status": "active", "source": "stripe"}}


@pytest.fixture
def login(tmp_path):
    tmp_path.chmod(0o700)
    return tmp_path / "login.json"


def stale_login(**extra):
    return {"access_token": "FAKE_OLD", "refresh_token": "FAKE_REF", "access_expires_at": int(time.time()) - 5,
            "refresh_token_expires_at": 0, **extra}


def test_the_harness_sees_a_rejected_file(tmp_path, login):
    """Control: the partial block an older loop wrote IS rejected, so a green result below means something."""
    auth.write_login(stale_login(verification={"validated": {"ok": True}}), login)
    assert REJECTED in runtime_status(tmp_path, login)


def test_a_refresh_with_an_entitlement_leaves_a_file_the_runtime_reads(tmp_path, login):
    auth.write_login(stale_login(), login)
    auth.refresh_if_due(login, lambda payload: dict(ENTITLED))
    assert REJECTED not in runtime_status(tmp_path, login)


def test_a_refresh_over_a_complete_runtime_verification_leaves_a_file_the_runtime_reads(tmp_path, login):
    block = {"auth_base_url": "https://auth.example.invalid/api", "token_digest": "d" * 64, "verified_at": 5,
             "next_check_at": 9, "validated": {"active": True, "user": {"email": "w@x.org"}}}
    auth.write_login(stale_login(verification=block), login)
    auth.refresh_if_due(login, lambda payload: dict(ENTITLED))
    assert REJECTED not in runtime_status(tmp_path, login)


def test_a_login_the_old_loop_damaged_is_healed_by_the_next_refresh(tmp_path, login):
    auth.write_login(stale_login(verification={"validated": {"ok": True}}), login)
    assert REJECTED in runtime_status(tmp_path, login)
    auth.refresh_if_due(login, lambda payload: dict(ENTITLED))
    assert REJECTED not in runtime_status(tmp_path, login)
