"""The login file shared with the Simplicio Runtime (#1575): one reader, one writer, one lock.

Every token in this file is FAKE and every path is under tmp_path: the real ~/.simplicio is never read or written.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from simplicio_loop import auth

REPO = Path(__file__).resolve().parents[1]
FAKE_ACCESS = "fake-access-token-0001"
FAKE_REFRESH = "fake-refresh-token-0001"


def put(path: Path, data: dict, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)  # the store refuses a folder that group or others can write, whatever the umask
    path.write_text(json.dumps(data))
    path.chmod(mode)
    return path


VERIFICATION_KEYS = ("auth_base_url", "token_digest", "verified_at", "next_check_at", "validated")


def runtime_verification(**over) -> dict:
    """The `verification` block as the Runtime 3.10.0 writes it: StoredVerification has NO serde(default) on these keys."""
    block = {"auth_base_url": "https://auth.example.invalid/api", "token_digest": "d" * 64, "verified_at": 5,
             "next_check_at": 9, "validated": {"active": True, "user": {"email": "w@x.org"},
                                                "entitlement": {"tier": "pro", "status": "active"}}}
    block.update(over)
    return block


def assert_runtime_accepts(doc: dict) -> None:
    """Mirror of the Runtime's serde rules for StoredAuth (src/runtime_auth.rs): a violation makes it reject the file."""
    assert isinstance(doc.get("access_token"), str) and isinstance(doc.get("access_expires_at"), int)
    assert doc.get("refresh_token") is None or isinstance(doc["refresh_token"], str)
    assert isinstance(doc.get("refresh_token_expires_at", 0), int)
    assert doc.get("refresh_request_id") is None or isinstance(doc["refresh_request_id"], str)
    verification = doc.get("verification")
    if verification is not None:
        missing = [key for key in VERIFICATION_KEYS if key not in verification]
        assert not missing, f"the Runtime would reject this file: verification lacks {missing}"


def sample(**over) -> dict:
    data = {"access_token": FAKE_ACCESS, "refresh_token": FAKE_REFRESH, "access_expires_at": 0}
    data.update(over)
    return data


@pytest.fixture(autouse=True)
def normal_umask():
    """The store refuses a folder that group or others can write: these tests assume the usual umask, not a group one."""
    old = os.umask(0o022)
    yield
    os.umask(old)


@pytest.fixture
def login(tmp_path):
    return tmp_path / "home" / ".simplicio" / "login.json"


# --- where the file is ---------------------------------------------------------------------------------------------


def test_path_order_is_watcher_env_then_runtime_env_then_home(tmp_path):
    env = {"HOME": str(tmp_path)}
    assert auth.login_path(env) == tmp_path / ".simplicio" / "login.json"
    assert auth.login_path({**env, "SIMPLICIO_AUTH_FILE": str(tmp_path / "rt.json")}) == tmp_path / "rt.json"
    both = {**env, "SIMPLICIO_AUTH_FILE": str(tmp_path / "rt.json"), "SIMPLICIO_247_LOGIN": str(tmp_path / "w.json")}
    assert auth.login_path(both) == tmp_path / "w.json"
    assert auth.login_path({**env, "SIMPLICIO_247_LOGIN": "  "}) == tmp_path / ".simplicio" / "login.json"


def test_runtime_path_ignores_the_watcher_env(tmp_path):
    env = {"HOME": str(tmp_path), "SIMPLICIO_247_LOGIN": str(tmp_path / "w.json")}
    assert auth.runtime_login_path(env) == tmp_path / ".simplicio" / "login.json"
    assert auth.runtime_login_path({**env, "SIMPLICIO_AUTH_FILE": str(tmp_path / "rt.json")}) == tmp_path / "rt.json"


def test_lock_file_is_the_runtime_sidecar(tmp_path):
    # the Runtime locks `login.lock` (the login file name with the extension changed): the same file or no exclusion
    assert auth.lock_path(tmp_path / "login.json") == tmp_path / "login.lock"
    assert auth.lock_path(tmp_path / "custom") == tmp_path / "custom.lock"


# --- read: validation ----------------------------------------------------------------------------------------------


def test_read_missing_file(login):
    with pytest.raises(auth.LoginError) as err:
        auth.read_login(login)
    assert err.value.reason_code == "login_missing"


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", '"text"'])
def test_read_invalid_content_is_not_a_login(login, raw):
    login.parent.mkdir(parents=True)
    login.write_text(raw)
    login.chmod(0o600)
    with pytest.raises(auth.LoginError) as err:
        auth.read_login(login)
    assert err.value.reason_code == "login_invalid"


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666])
def test_read_refuses_a_file_that_group_or_others_can_read(login, mode):
    put(login, sample(), mode)
    with pytest.raises(auth.LoginError) as err:
        auth.read_login(login)
    assert err.value.reason_code == "login_permissions"
    assert str(login) in str(err.value) and "chmod 600" in str(err.value)
    assert FAKE_ACCESS not in str(err.value)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_read_refuses_a_symlink(tmp_path, login):
    real = put(tmp_path / "real.json", sample())
    login.parent.mkdir(parents=True)
    login.symlink_to(real)
    with pytest.raises(auth.LoginError) as err:
        auth.read_login(login)
    assert err.value.reason_code == "login_symlink"


def test_read_returns_the_content_of_a_private_file(login):
    put(login, sample(extra={"a": 1}))
    assert auth.read_login(login)["extra"] == {"a": 1}


# --- write ---------------------------------------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_write_creates_a_private_file_and_a_private_folder(login):
    auth.write_login(sample(), login)
    assert stat.S_IMODE(login.stat().st_mode) == 0o600
    assert stat.S_IMODE(login.parent.stat().st_mode) == 0o700
    assert json.loads(login.read_text())["access_token"] == FAKE_ACCESS
    assert [p.name for p in login.parent.iterdir()] == ["login.json"]  # no temp file left behind


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_write_is_private_even_with_a_permissive_umask(login):
    old = os.umask(0)
    try:
        auth.write_login(sample(), login)
    finally:
        os.umask(old)
    assert stat.S_IMODE(login.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_temp_file_is_private_before_the_content_is_written(login, monkeypatch):
    seen = []
    real_write = os.write

    def spy(fd, data):
        seen.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", spy)
    old = os.umask(0)
    try:
        auth.write_login(sample(), login)
    finally:
        os.umask(old)
    assert seen and set(seen) == {0o600}


def test_write_syncs_the_file_before_the_rename(login, monkeypatch):
    order = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: order.append("fsync") or real_fsync(fd))
    monkeypatch.setattr(os, "replace", lambda a, b: order.append("replace") or real_replace(a, b))
    auth.write_login(sample(), login)
    assert order.index("fsync") < order.index("replace")


def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp(login, monkeypatch):
    put(login, sample())
    before = login.read_text()
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        auth.write_login(sample(access_token="new"), login)
    assert login.read_text() == before
    assert [p.name for p in login.parent.iterdir()] == ["login.json"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_write_refuses_a_symlink_and_leaves_the_target_alone(tmp_path, login):
    real = put(tmp_path / "real.json", sample())
    login.parent.mkdir(parents=True)
    login.symlink_to(real)
    with pytest.raises(auth.LoginError) as err:
        auth.write_login(sample(access_token="new"), login)
    assert err.value.reason_code == "login_symlink"
    assert json.loads(real.read_text())["access_token"] == FAKE_ACCESS
    assert login.is_symlink()


# --- tokens and the public summary ---------------------------------------------------------------------------------


def test_apply_tokens_matches_the_watcher_rules():
    login = sample(verification=runtime_verification())
    auth.apply_tokens(login, {"access_token": "n1", "refresh_token": "n2", "expires_in": 3600,
                              "refresh_token_expires_in": 7200,
                              "entitlement": {"active": True, "tier": "pro"}}, now=1000)
    assert login["access_token"] == "n1" and login["refresh_token"] == "n2"
    assert login["access_expires_at"] == 1000 + 3600 - 30
    assert login["refresh_token_expires_at"] == 1000 + 7200
    assert login["verification"]["validated"]["entitlement"] == {"active": True, "tier": "pro"}
    assert login["verification"]["validated"]["active"] is True
    auth.apply_tokens(login, {"access_token": "n3", "refresh_token": "n4", "refresh_token_persistent": True}, now=1000)
    assert login["refresh_token_expires_at"] == 0


def test_apply_tokens_needs_an_access_token():
    with pytest.raises(auth.LoginError) as err:
        auth.apply_tokens(sample(), {"refresh_token": "only-refresh"}, now=1)
    assert err.value.reason_code == "token_response_invalid"


def test_a_response_without_a_new_refresh_token_keeps_the_old_one():
    # the Runtime does the same: a server that does not rotate the refresh token is not an error
    login = sample()
    auth.apply_tokens(login, {"access_token": "n1", "expires_in": 3600}, now=1000)
    assert login["access_token"] == "n1" and login["refresh_token"] == FAKE_REFRESH


@pytest.mark.parametrize("email,masked", [
    ("wesley@gmail.com", "w***@gmail.com"),
    ("a@x.org", "a***@x.org"),
    ("", ""),
    ("not-an-email", ""),
])
def test_mask_email(email, masked):
    assert auth.mask_email(email) == masked


def test_summary_has_no_secret_and_masks_the_email():
    data = sample(access_expires_at=2000, refresh_token_expires_at=9000,
                  verification={"validated": {"user": {"email": "wesley@gmail.com"},
                                              "entitlement": {"tier": "pro", "status": "active",
                                                              "source": "stripe", "plan": "p", "active": True}}})
    out = auth.summary(data, now=1000)
    blob = json.dumps(out)
    assert FAKE_ACCESS not in blob and FAKE_REFRESH not in blob and "wesley" not in blob
    assert out["email"] == "w***@gmail.com"
    assert out["access_expires_at"] == 2000 and out["access_expired"] is False
    assert out["refresh_expired"] is False and out["has_refresh_token"] is True
    assert out["entitlement"]["tier"] == "pro"
    assert auth.summary(data, now=3000)["access_expired"] is True
    assert auth.summary(data, now=10000)["refresh_expired"] is True


def test_summary_of_a_login_without_cached_validation():
    out = auth.summary(sample(), now=5)
    assert out["email"] == "" and out["entitlement"] is None and out["access_expired"] is True


# --- refresh: lock, re-read, one request ---------------------------------------------------------------------------


def new_tokens(**over):
    return {"access_token": "fresh-access", "refresh_token": "fresh-refresh", "expires_in": 3600, **over}


def test_refresh_posts_once_and_stores_the_tokens(login):
    put(login, sample())
    seen = []

    def post(payload):
        seen.append(payload)
        return new_tokens()

    result, refreshed = auth.refresh_if_due(login, post, now=1000)
    assert refreshed is True and result["access_token"] == "fresh-access"
    assert seen == [{"grant_type": "refresh_token", "refresh_token": FAKE_REFRESH, "client_id": auth.MCP_CLIENT_ID}]
    assert json.loads(login.read_text())["refresh_token"] == "fresh-refresh"


def test_refresh_is_skipped_while_the_access_token_is_fresh(login):
    put(login, sample(access_expires_at=1000 + 61))
    result, refreshed = auth.refresh_if_due(login, lambda p: pytest.fail("no request expected"), now=1000)
    assert refreshed is False and result["access_token"] == FAKE_ACCESS


def test_refresh_happens_when_the_token_expires_within_60_seconds(login):
    put(login, sample(access_expires_at=1000 + 60))
    _, refreshed = auth.refresh_if_due(login, lambda p: new_tokens(), now=1000)
    assert refreshed is True


def test_no_refresh_token_means_no_request(login):
    put(login, {"access_token": FAKE_ACCESS, "access_expires_at": 0})
    result, refreshed = auth.refresh_if_due(login, lambda p: pytest.fail("no request expected"), now=1000)
    assert refreshed is False and result["access_token"] == FAKE_ACCESS


def test_foreign_keys_written_by_the_runtime_survive_a_refresh(login):
    put(login, sample(verification={"auth_base_url": "https://x", "token_digest": "abc", "verified_at": 5,
                                    "next_check_at": 9, "validated": {"user": {"email": "w@x.org"}}},
                      runtime_only={"nested": [1, 2, 3]}, refresh_request_id="rid-1"))
    seen = []
    auth.refresh_if_due(login, lambda p: seen.append(p) or new_tokens(), now=1000)
    stored = json.loads(login.read_text())
    assert stored["runtime_only"] == {"nested": [1, 2, 3]}
    assert stored["verification"]["token_digest"] == "abc"
    assert stored["verification"]["validated"]["user"]["email"] == "w@x.org"
    # a pending request id of the Runtime goes with the request (the server can answer with the same successor)
    # and is dropped after a success, like the Runtime does
    assert seen[0]["refresh_request_id"] == "rid-1"
    assert "refresh_request_id" not in stored


def test_keys_the_runtime_adds_while_we_wait_are_kept(login, monkeypatch):
    """The login is read AGAIN under the lock: a key written between our first look and the lock is not lost."""
    put(login, sample())

    def post(payload):
        return new_tokens()

    real_lock = auth.file_lock

    def lock_after_runtime_write(path, **kw):
        put(path, sample(added_by_runtime=True))  # the Runtime wrote the file before we got the lock
        return real_lock(path, **kw)

    monkeypatch.setattr(auth, "file_lock", lock_after_runtime_write)
    auth.refresh_if_due(login, post, now=1000)
    assert json.loads(login.read_text())["added_by_runtime"] is True


def test_a_failed_request_changes_nothing(login):
    put(login, sample())
    before = login.read_text()

    def post(payload):
        raise OSError("server down")

    with pytest.raises(OSError):
        auth.refresh_if_due(login, post, now=1000)
    assert login.read_text() == before


def test_a_response_without_tokens_changes_nothing(login):
    put(login, sample())
    before = login.read_text()
    with pytest.raises(auth.LoginError):
        auth.refresh_if_due(login, lambda p: {"error": "invalid_grant"}, now=1000)
    assert login.read_text() == before


# --- the file stays one the Runtime accepts (review of #1584, item 1) --------------------------------------------------

ENTITLED = {"access_token": "fresh-access", "refresh_token": "fresh-refresh", "expires_in": 3600,
            "entitlement": {"active": True, "tier": "team", "status": "active", "source": "stripe"}}


def test_a_refresh_with_an_entitlement_never_creates_a_partial_verification(login):
    put(login, sample())  # no verification yet, as after a Runtime refresh
    auth.refresh_if_due(login, lambda p: dict(ENTITLED), now=1000)
    stored = json.loads(login.read_text())
    assert "verification" not in stored
    assert_runtime_accepts(stored)


def test_a_refresh_keeps_the_complete_runtime_verification_and_updates_only_the_entitlement(login):
    put(login, sample(verification=runtime_verification()))
    auth.refresh_if_due(login, lambda p: dict(ENTITLED), now=1000)
    stored = json.loads(login.read_text())
    assert_runtime_accepts(stored)
    assert stored["verification"]["token_digest"] == "d" * 64
    assert stored["verification"]["auth_base_url"] == "https://auth.example.invalid/api"
    assert stored["verification"]["validated"]["user"] == {"email": "w@x.org"}
    assert stored["verification"]["validated"]["entitlement"]["tier"] == "team"


def test_a_partial_verification_left_by_an_older_loop_is_removed_so_the_runtime_can_read_the_file(login):
    put(login, sample(verification={"validated": {"ok": True, "entitlement": {"tier": "pro"}}}))
    auth.refresh_if_due(login, lambda p: new_tokens(), now=1000)  # even a response without an entitlement heals it
    stored = json.loads(login.read_text())
    assert "verification" not in stored
    assert_runtime_accepts(stored)


def test_every_refreshed_shape_is_accepted_by_the_runtime_schema(login):
    for before in (sample(), sample(verification=runtime_verification()), sample(refresh_request_id="rid-1"),
                   sample(verification={"validated": {}})):
        for response in (new_tokens(), dict(ENTITLED), new_tokens(refresh_token_persistent=True)):
            put(login, before)
            auth.refresh_if_due(login, lambda p, r=response: dict(r), now=1000)
            assert_runtime_accepts(json.loads(login.read_text()))


def test_a_response_without_refresh_token_expires_in_writes_no_expiry_it_does_not_know(login):
    put(login, sample())
    auth.refresh_if_due(login, lambda p: new_tokens(), now=1000)  # no refresh_token_expires_in in the response
    stored = json.loads(login.read_text())
    assert stored["refresh_token_expires_at"] == 0  # unknown, like the Runtime's refresh_expiry
    assert auth.summary(stored, now=1000 + 99999)["refresh_expired"] is False
    refreshed = {}
    auth.apply_tokens(refreshed, {"access_token": "a", "refresh_token": "r", "refresh_token_expires_in": 7200}, now=1000)
    assert refreshed["refresh_token_expires_at"] == 8200
    auth.apply_tokens(refreshed, {"access_token": "a", "refresh_token_expires_in": -5}, now=1000)
    assert refreshed["refresh_token_expires_at"] == 0


# --- what is not a login file (review of #1584, items 4 and 5) ----------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX files")
def test_a_directory_is_not_a_login_file_and_gives_no_traceback(login):
    login.mkdir(parents=True)
    with pytest.raises(auth.LoginError) as err:
        auth.read_login(login)
    assert err.value.reason_code == "login_invalid" and "regular file" in str(err.value)
    assert auth.describe({"HOME": str(login.parent.parent), "SIMPLICIO_AUTH_FILE": str(login)})["reason_code"] == "login_invalid"


@pytest.mark.skipif(os.name == "nt", reason="POSIX files")
def test_a_fifo_does_not_hang_the_read(login):
    login.parent.mkdir(parents=True)
    login.parent.chmod(0o700)
    os.mkfifo(login, 0o600)
    started = time.monotonic()
    with pytest.raises(auth.LoginError) as err:
        auth.read_login(login)
    assert err.value.reason_code == "login_invalid" and time.monotonic() - started < 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_a_dangling_symlink_is_refused_and_its_target_is_not_created(tmp_path, login):
    login.parent.mkdir(parents=True)
    login.parent.chmod(0o700)
    target = tmp_path / "nowhere.json"
    login.symlink_to(target)
    with pytest.raises(auth.LoginError) as err:
        auth.read_login(login)
    assert err.value.reason_code == "login_symlink"
    with pytest.raises(auth.LoginError):
        auth.write_login(sample(), login)
    assert not target.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_clearing_a_directory_is_refused_without_a_traceback(login):
    login.mkdir(parents=True)
    with pytest.raises(auth.LoginError) as err:
        auth.clear_login(login)
    assert err.value.reason_code == "login_invalid" and login.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
@pytest.mark.parametrize("mode", [0o777, 0o775, 0o770, 0o707, 0o722])  # 0775 is what umask 002 gives mkdir
def test_a_folder_that_group_or_others_can_write_is_refused_for_read_and_write(login, mode):
    put(login, sample())
    login.parent.chmod(mode)
    with pytest.raises(auth.LoginError) as err:
        auth.read_login(login)
    assert err.value.reason_code == "login_permissions" and "chmod 700" in str(err.value)
    assert err.value.fix == f"chmod 700 {login.parent}"  # the fix names the folder, not the file
    env = {"HOME": str(login.parent.parent), "SIMPLICIO_AUTH_FILE": str(login)}
    assert auth.describe(env)["fix"] == f"chmod 700 {login.parent}"
    with pytest.raises(auth.LoginError) as err:
        auth.write_login(sample(access_token="new"), login)
    assert err.value.reason_code == "login_permissions"
    assert json.loads(login.read_text())["access_token"] == FAKE_ACCESS
    with pytest.raises(auth.LoginError):
        with auth.file_lock(login, wait_s=0.1):
            pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_sticky_folder_we_own_is_accepted(login):
    put(login, sample())
    login.parent.chmod(0o1777)
    assert auth.read_login(login)["access_token"] == FAKE_ACCESS
    login.parent.chmod(0o755)
    assert auth.read_login(login)["access_token"] == FAKE_ACCESS


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
@pytest.mark.parametrize("mode", [0o644, 0o660, 0o666, 0o604])
def test_an_existing_lock_file_that_others_can_open_is_refused(tmp_path, mode):
    path = tmp_path / "login.json"
    lock = auth.lock_path(path)
    lock.write_text("")
    lock.chmod(mode)
    with pytest.raises(auth.LoginError) as err:
        with auth.file_lock(path, wait_s=0.1):
            pytest.fail("the lock must not be taken on a file others can open")
    assert err.value.reason_code == "login_permissions" and "chmod 600" in str(err.value)


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_lock_file_owned_by_another_user_is_refused_unless_we_are_root(tmp_path, monkeypatch):
    path = tmp_path / "login.json"
    lock = auth.lock_path(path)
    lock.write_text("")
    lock.chmod(0o600)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(lock).st_uid + 1)  # a different, non-root user
    with pytest.raises(auth.LoginError) as err:
        with auth.file_lock(path, wait_s=0.1):
            pytest.fail("not our lock file")
    assert err.value.reason_code == "login_permissions" and "owned by" in str(err.value)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with auth.file_lock(path, wait_s=0.1):  # root may use a service user's lock (watch247 setup)
        pass


@pytest.mark.skipif(os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() != 0,
                    reason="needs a process running as root, to hand files to another uid")
def test_a_root_process_may_use_files_owned_by_the_service_user_and_keeps_their_owner(login):
    """Any process with euid 0 is exempt from the owner check (not only `watch247 setup`), with REAL foreign owners."""
    put(login, sample())
    lock = auth.lock_path(login)
    lock.write_text("")
    lock.chmod(0o600)
    for path in (login, lock, login.parent):
        os.chown(path, 4242, 4242)
    assert auth.read_login(login)["access_token"] == FAKE_ACCESS
    with auth.file_lock(login, wait_s=0.2):
        pass
    auth.refresh_if_due(login, lambda p: new_tokens(), now=1000)
    after = login.stat()
    assert (after.st_uid, after.st_gid) == (4242, 4242), "a root refresh must not hand the user's file to root"
    assert json.loads(login.read_text())["access_token"] == "fresh-access"


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_login_file_owned_by_another_user_is_refused(login, monkeypatch):
    put(login, sample())
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(login).st_uid + 1)
    with pytest.raises(auth.LoginError) as err:
        auth.read_login(login)
    assert err.value.reason_code == "login_permissions" and "owned by" in str(err.value)


# --- the lock ------------------------------------------------------------------------------------------------------


def test_lock_is_released_on_exit_and_after_an_error(tmp_path):
    path = tmp_path / "login.json"
    with auth.file_lock(path):
        pass
    with pytest.raises(RuntimeError):
        with auth.file_lock(path):
            raise RuntimeError("boom")
    with auth.file_lock(path, wait_s=0.2):  # taken again at once
        pass


@pytest.mark.skipif(os.name == "nt", reason="flock")
def test_a_stale_lock_file_does_not_block(tmp_path):
    """The kernel drops a flock when its owner dies; the file a dead process leaves behind is not a lock."""
    path = tmp_path / "login.json"
    stale = auth.lock_path(path)
    stale.write_text("pid 424242 died here\n")
    stale.chmod(0o600)
    started = time.monotonic()
    with auth.file_lock(path, wait_s=2):
        pass
    assert time.monotonic() - started < 1.5


HOLDER = textwrap.dedent("""
    import sys, time
    from simplicio_loop import auth
    with auth.file_lock(sys.argv[1], wait_s=5):
        print("held", flush=True)
        time.sleep(float(sys.argv[2]))
""")


def env_for_children():
    return {**os.environ, "PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1"}


@pytest.mark.skipif(os.name == "nt", reason="flock")
def test_a_held_lock_blocks_then_times_out(tmp_path):
    path = tmp_path / "login.json"
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(path), "3"], stdout=subprocess.PIPE, text=True,
                              env=env_for_children())
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(auth.LoginError) as err:
            with auth.file_lock(path, wait_s=0.3):
                pytest.fail("the lock was not held by the other process")
        assert err.value.reason_code == "login_lock_timeout"
    finally:
        holder.kill()
        holder.wait()
    with auth.file_lock(path, wait_s=2):  # the dead holder no longer holds it
        pass


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
def test_a_symlinked_lock_file_is_refused(tmp_path):
    path = tmp_path / "login.json"
    target = tmp_path / "elsewhere"
    target.write_text("")
    auth.lock_path(path).symlink_to(target)
    with pytest.raises(auth.LoginError) as err:
        with auth.file_lock(path, wait_s=0.2):
            pass
    assert err.value.reason_code == "login_symlink"


def test_windows_lock_uses_msvcrt_byte_lock(tmp_path, monkeypatch):
    calls = []

    class FakeMsvcrt:
        LK_NBLCK = 2
        LK_UNLCK = 0

        @staticmethod
        def locking(fd, mode, nbytes):
            calls.append((mode, nbytes))

    monkeypatch.setattr(auth, "fcntl", None)
    monkeypatch.setattr(auth, "msvcrt", FakeMsvcrt)
    with auth.file_lock(tmp_path / "login.json", wait_s=1):
        assert calls == [(FakeMsvcrt.LK_NBLCK, 1)]
    assert calls == [(FakeMsvcrt.LK_NBLCK, 1), (FakeMsvcrt.LK_UNLCK, 1)]


def test_windows_lock_retries_while_busy(tmp_path, monkeypatch):
    calls = []

    class BusyThenFree:
        LK_NBLCK = 2
        LK_UNLCK = 0

        @staticmethod
        def locking(fd, mode, nbytes):
            calls.append(mode)
            if mode == 2 and calls.count(2) < 3:
                raise OSError(13, "busy")

    monkeypatch.setattr(auth, "fcntl", None)
    monkeypatch.setattr(auth, "msvcrt", BusyThenFree)
    with auth.file_lock(tmp_path / "login.json", wait_s=2):
        pass
    assert calls.count(2) == 3


# --- two programs refresh at once ----------------------------------------------------------------------------------

REFRESHER = textwrap.dedent("""
    import json, sys, time
    from simplicio_loop import auth

    path, calls, start = sys.argv[1], sys.argv[2], float(sys.argv[3])

    def post(payload):
        time.sleep(0.5)  # the server is slow: the other process reaches the lock while this request runs
        with open(calls, "a") as handle:
            handle.write(json.dumps(payload) + "\\n")
        return {"access_token": "fresh-access", "refresh_token": "fresh-refresh", "expires_in": 3600}

    while time.time() < start:
        time.sleep(0.005)
    login, refreshed = auth.refresh_if_due(path, post)
    print(json.dumps({"access": login["access_token"], "refresh": login["refresh_token"], "refreshed": refreshed}))
""")


@pytest.mark.skipif(os.name == "nt", reason="flock")
def test_two_processes_refresh_with_exactly_one_request(tmp_path):
    path = put(tmp_path / "home" / "login.json", sample())
    calls = tmp_path / "calls.log"
    start = time.time() + 1.5
    procs = [subprocess.Popen([sys.executable, "-c", REFRESHER, str(path), str(calls), str(start)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env_for_children())
             for _ in range(2)]
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
        results.append(json.loads(out.strip().splitlines()[-1]))
    assert len(calls.read_text().splitlines()) == 1, "the rotating refresh token was used twice"
    assert [r["access"] for r in results] == ["fresh-access", "fresh-access"]
    assert [r["refresh"] for r in results] == ["fresh-refresh", "fresh-refresh"]
    assert sorted(r["refreshed"] for r in results) == [False, True]
    assert json.loads(path.read_text())["refresh_token"] == "fresh-refresh"


# --- logout --------------------------------------------------------------------------------------------------------


def test_clear_removes_the_file_under_the_lock(login):
    put(login, sample())
    assert auth.clear_login(login) is True
    assert not login.exists()
    assert auth.clear_login(login) is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_clear_removes_a_symlink_but_never_its_target(tmp_path, login):
    real = put(tmp_path / "real.json", sample())
    login.parent.mkdir(parents=True)
    login.symlink_to(real)
    assert auth.clear_login(login) is True
    assert real.exists() and not login.is_symlink()


# --- the Runtime ---------------------------------------------------------------------------------------------------


def fake_runtime(directory: Path, text: str = "simplicio 3.10.0\nexecutable: x\ncomponent: runtime-kernel 3.10.0") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "simplicio"
    script.write_text(f"#!/bin/sh\ncat <<'EOF'\n{text}\nEOF\n")
    script.chmod(0o755)
    return script


@pytest.mark.skipif(os.name == "nt", reason="shell script")
def test_runtime_is_found_on_path_first_then_in_its_bin_folder(tmp_path):
    on_path = fake_runtime(tmp_path / "bin")
    managed = fake_runtime(tmp_path / "home" / ".simplicio" / "bin")
    env = {"HOME": str(tmp_path / "home"), "PATH": str(tmp_path / "bin")}
    assert auth.runtime_binary(env) == on_path
    assert auth.runtime_binary({"HOME": env["HOME"], "PATH": str(tmp_path / "empty")}) == managed
    assert auth.runtime_binary({"HOME": str(tmp_path / "nohome"), "PATH": str(tmp_path / "empty")}) is None


@pytest.mark.skipif(os.name == "nt", reason="shell script")
def test_runtime_version_is_read_from_version_output(tmp_path):
    binary = fake_runtime(tmp_path / "bin")
    assert auth.runtime_version(binary) == "3.10.0"
    broken = tmp_path / "bin2" / "simplicio"
    broken.parent.mkdir()
    broken.write_text("#!/bin/sh\nexit 3\n")
    broken.chmod(0o755)
    assert auth.runtime_version(broken) is None
    assert auth.runtime_version(tmp_path / "missing") is None
