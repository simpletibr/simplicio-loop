"""`simplicio-loop update` for every distribution (#1575), tested OFFLINE with a fake release API and fake assets.

The HTTP layer is injected: nothing here touches the network, the real executable or the real HOME.
"""
from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import stat
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from simplicio_loop import distribution, self_update as su

OLD = b"#!/bin/sh\necho 'simplicio-loop 3.48.1'\n"
PLATFORM = ("linux", "x86_64")
posix = pytest.mark.skipif(os.name == "nt", reason="shell script binaries")


def new_binary(version="3.49.0") -> bytes:
    return f"#!/bin/sh\necho 'simplicio-loop {version}'\n".encode()


class FakeNet:
    """The injected HTTP layer: url -> file-like. Records every url asked for."""

    def __init__(self, files: dict):
        self.files, self.asked = files, []

    def __call__(self, url: str):
        self.asked.append(url)
        if url not in self.files:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        value = self.files[url]
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(value)

    def downloaded(self, name: str) -> bool:
        return any(url.endswith("/" + name) for url in self.asked)


def release(version="3.49.0", *, content=None, asset=True, sums=True, sums_line=True, digest=None,
            platform=PLATFORM, extra_sums="") -> tuple:
    """(net, asset name, asset bytes) for a fake GitHub release of `version`."""
    name = distribution.binary_asset_name(version, *platform)
    content = new_binary(version) if content is None else content
    base = f"https://example.invalid/download/v{version}"
    files, assets = {}, []
    if asset:
        assets.append({"name": name, "browser_download_url": f"{base}/{name}"})
        files[f"{base}/{name}"] = content
    if sums:
        assets.append({"name": "SHA256SUMS", "browser_download_url": f"{base}/SHA256SUMS"})
        line = f"{digest or hashlib.sha256(content).hexdigest()}  {name}\n" if sums_line else ""
        files[f"{base}/SHA256SUMS"] = (extra_sums + line).encode()
    files[su.LATEST_URL] = json.dumps({"tag_name": f"v{version}", "assets": assets}).encode()
    return FakeNet(files), name, content


@pytest.fixture
def exe(tmp_path):
    path = tmp_path / "bin" / "simplicio-loop"
    path.parent.mkdir()
    path.write_bytes(OLD)
    path.chmod(0o755)
    return path


class Calls:
    def __init__(self):
        self.runs, self.records = [], []

    def runner(self, cmd):
        self.runs.append(list(cmd))
        return 0

    def record(self, info):
        self.records.append(dict(info))


def update(exe, net, calls, *, installed="3.48.1", probe=None, expect="3.49.0", **kw):
    kw.setdefault("platform", PLATFORM)
    kw.setdefault("state_dir", exe.parent.parent / "state")  # the update lock lives here, never in the real HOME
    return su.run_update(installed=installed, kind=distribution.BINARY, http=net, exe=exe, runner=calls.runner,
                         record=calls.record, probe=probe or (lambda path: f"simplicio-loop {expect}"), **kw)


def untouched(exe, tmp_path):
    assert exe.read_bytes() == OLD
    assert sorted(p.name for p in exe.parent.iterdir()) == ["simplicio-loop"], "a staged or backup file was left"


# --- --check -----------------------------------------------------------------------------------------------------------


def test_check_up_to_date_is_exit_0_and_downloads_nothing(exe, tmp_path, capsys):
    net, name, _ = release("3.48.1")
    calls = Calls()
    assert update(exe, net, calls, check=True) == 0
    assert "up to date" in capsys.readouterr().out
    assert net.asked == [su.LATEST_URL] and calls.runs == []
    untouched(exe, tmp_path)


def test_check_with_an_update_is_exit_10_and_changes_nothing(exe, tmp_path, capsys):
    net, name, _ = release()
    calls = Calls()
    assert update(exe, net, calls, check=True) == su.EXIT_UPDATE_AVAILABLE == 10
    assert "3.48.1 -> 3.49.0" in capsys.readouterr().out
    assert not net.downloaded(name) and calls.runs == []
    untouched(exe, tmp_path)
    assert calls.records[-1]["latest"] == "3.49.0" and calls.records[-1]["update_available"] is True
    assert calls.records[-1]["kind"] == "binary" and calls.records[-1]["installed"] == "3.48.1"


def test_check_is_exit_2_when_the_release_cannot_be_read(exe, tmp_path, capsys):
    calls = Calls()
    assert update(exe, FakeNet({}), calls, check=True) == 2
    assert "cannot read the latest release" in capsys.readouterr().out
    assert calls.records == []
    broken = FakeNet({su.LATEST_URL: b"<html>not json</html>"})
    assert update(exe, broken, calls, check=True) == 2


def test_check_is_exit_2_when_the_update_has_no_asset_for_this_platform(exe, tmp_path, capsys):
    net, _, _ = release(asset=False)
    assert update(exe, net, Calls(), check=True) == 2
    assert "no asset" in capsys.readouterr().out
    net, _, _ = release(sums=False)
    assert update(exe, net, Calls(), check=True) == 2
    assert "SHA256SUMS" in capsys.readouterr().out


# --- the update --------------------------------------------------------------------------------------------------------


@posix
def test_update_replaces_the_binary_keeps_a_backup_and_resyncs(exe, tmp_path, capsys):
    net, name, content = release()
    calls = Calls()
    assert update(exe, net, calls) == 0
    out = capsys.readouterr().out
    assert "3.48.1 -> 3.49.0" in out and "SHA256 verified" in out
    assert exe.read_bytes() == content
    assert (exe.parent / "simplicio-loop.bak").read_bytes() == OLD
    assert sorted(p.name for p in exe.parent.iterdir()) == ["simplicio-loop", "simplicio-loop.bak"]
    assert stat.S_IMODE(exe.stat().st_mode) & 0o111, "the new binary must stay executable"
    # the NEW binary resyncs the skills and host rules (#1480): it is the one that knows the new bundle
    assert calls.runs == [[str(exe), "install", "--global"]]
    assert calls.records[-1]["installed"] == "3.49.0" and calls.records[-1]["update_available"] is False


@posix
def test_the_checksum_is_verified_before_anything_is_touched(exe, tmp_path, capsys):
    net, name, _ = release(digest="0" * 64)
    calls = Calls()
    assert update(exe, net, calls) == 2
    assert "checksum" in capsys.readouterr().out
    assert net.downloaded(name), "the asset must be downloaded to be checked"
    untouched(exe, tmp_path)
    assert calls.runs == []


@pytest.mark.parametrize("flaw,needle", [
    ({"asset": False}, "no asset"),
    ({"sums": False}, "SHA256SUMS"),
    ({"sums_line": False}, "no checksum line"),
])
def test_a_missing_asset_or_checksum_refuses_without_downloading_the_binary(exe, tmp_path, capsys, flaw, needle):
    net, name, _ = release(**flaw)
    calls = Calls()
    assert update(exe, net, calls) == 2
    assert needle in capsys.readouterr().out
    assert not net.downloaded(name)
    untouched(exe, tmp_path)


def test_a_checksum_line_for_another_file_is_not_enough(exe, tmp_path, capsys):
    other = f"{'a' * 64}  simplicio-loop-v3.49.0-darwin-aarch64\n"
    net, name, _ = release(sums_line=False, extra_sums=other)
    assert update(exe, net, Calls()) == 2
    assert "no checksum line" in capsys.readouterr().out
    untouched(exe, tmp_path)


@posix
def test_a_downgrade_is_refused_unless_forced(exe, tmp_path, capsys):
    net, name, content = release("3.49.0")
    calls = Calls()
    assert update(exe, net, calls, installed="3.50.0") == 2
    assert "downgrade" in capsys.readouterr().out and not net.downloaded(name)
    untouched(exe, tmp_path)
    assert update(exe, net, calls, installed="3.50.0", force=True) == 0
    assert exe.read_bytes() == content


@posix
def test_up_to_date_does_nothing_unless_forced(exe, tmp_path, capsys):
    net, name, content = release("3.48.1", content=new_binary("3.48.1"))
    calls = Calls()
    assert update(exe, net, calls, expect="3.48.1") == 0
    assert "up to date" in capsys.readouterr().out and not net.downloaded(name)
    untouched(exe, tmp_path)
    assert update(exe, net, calls, force=True, expect="3.48.1") == 0
    assert net.downloaded(name) and exe.read_bytes() == content


def test_dry_run_looks_up_the_plan_and_changes_nothing(exe, tmp_path, capsys):
    net, name, _ = release()
    calls = Calls()
    assert update(exe, net, calls, dry_run=True) == 0
    out = capsys.readouterr().out
    assert name in out and str(exe) in out and "dry run" in out.lower()
    assert not net.downloaded(name) and calls.runs == [] and calls.records == []
    untouched(exe, tmp_path)


def test_dry_run_still_refuses_what_a_real_run_would_refuse(exe, tmp_path):
    net, _, _ = release(sums_line=False)
    assert update(exe, net, Calls(), dry_run=True) == 2
    net, _, _ = release()
    assert update(exe, net, Calls(), dry_run=True, installed="3.50.0") == 2


def test_an_unsupported_platform_is_exit_2(exe, tmp_path, monkeypatch, capsys):
    def refuse():
        raise distribution.UnsupportedPlatform("no release for the CPU 'riscv64'")

    monkeypatch.setattr(distribution, "platform_key", refuse)
    net, _, _ = release()
    assert update(exe, net, Calls(), platform=None) == 2
    assert "riscv64" in capsys.readouterr().out
    untouched(exe, tmp_path)


# --- rollback and atomicity ----------------------------------------------------------------------------------------------


@posix
def test_a_new_binary_that_does_not_answer_is_rolled_back(exe, tmp_path, capsys):
    net, name, _ = release()
    calls = Calls()
    assert update(exe, net, calls, probe=lambda path: "something else") == 2
    out = capsys.readouterr().out
    assert "put back" in out
    assert exe.read_bytes() == OLD
    assert sorted(p.name for p in exe.parent.iterdir()) == ["simplicio-loop"]
    assert calls.runs == []


@posix
def test_a_probe_that_crashes_is_rolled_back(exe, tmp_path):
    net, _, _ = release()

    def crash(path):
        raise OSError("exec format error")

    assert update(exe, net, Calls(), probe=crash) == 2
    assert exe.read_bytes() == OLD


@posix
def test_the_swap_is_one_rename_and_a_failed_rename_changes_nothing(exe, tmp_path, monkeypatch, capsys):
    net, _, _ = release()
    real = os.replace
    renames = []

    def failing(src, dst):
        renames.append((Path(src).name, Path(dst).name))
        if Path(src).name.endswith(".new") and Path(dst).name == "simplicio-loop":
            raise PermissionError(13, "read-only file system")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", failing)
    assert update(exe, net, Calls()) == 2
    assert len(renames) == 1 and renames[0][1] == "simplicio-loop"  # ONE rename, from the unique staged name
    assert renames[0][0].startswith("simplicio-loop.") and renames[0][0].endswith(".new")
    assert exe.read_bytes() == OLD
    assert sorted(p.name for p in exe.parent.iterdir()) == ["simplicio-loop"]
    assert "read-only" in capsys.readouterr().out


@posix
def test_the_real_probe_runs_the_new_binary(exe, tmp_path, capsys):
    net, _, content = release()
    state = exe.parent.parent / "state"
    assert su.run_update(installed="3.48.1", kind=distribution.BINARY, http=net, exe=exe, platform=PLATFORM,
                         runner=Calls().runner, state_dir=state) == 0
    assert exe.read_bytes() == content
    # ... and a binary that reports another version is not accepted
    exe.write_bytes(OLD)
    net, _, _ = release(content=new_binary("9.9.9"))
    assert su.run_update(installed="3.48.1", kind=distribution.BINARY, http=net, exe=exe, platform=PLATFORM,
                         runner=Calls().runner, state_dir=state) == 2
    assert exe.read_bytes() == OLD


# --- Windows: stage now, swap on the next start ------------------------------------------------------------------------------


# --- two updates at once, and what is hashed (review of #1584, item 6) -----------------------------------------------


class BlockedAsset(FakeNet):
    """The asset download stops until `go` is set, and says when it started."""

    def __init__(self, files, asset_name, entered, go):
        super().__init__(files)
        self.asset_name, self.entered, self.go = asset_name, entered, go

    def __call__(self, url):
        body = super().__call__(url)
        if url.endswith("/" + self.asset_name):
            entered, go = self.entered, self.go

            class Held(io.BytesIO):
                def read(self, size=-1):
                    entered.set()
                    go.wait(15)
                    return super().read(size)

            return Held(body.getvalue())
        return body


@posix
def test_two_updates_at_once_the_second_is_refused_and_the_staged_names_are_unique(exe, tmp_path, capsys):
    net, name, content = release()
    entered, go = threading.Event(), threading.Event()
    first = BlockedAsset(net.files, name, entered, go)
    result = {}
    worker = threading.Thread(target=lambda: result.update(rc=update(exe, first, Calls())))
    worker.start()
    try:
        assert entered.wait(15), "the first update never reached its download"
        staged = sorted(p.name for p in exe.parent.iterdir() if p.name.endswith(".new"))
        assert len(staged) == 1 and staged[0] != "simplicio-loop.new"  # a unique name, not a fixed one
        second = FakeNet(dict(net.files))
        assert update(exe, second, Calls()) == 2
        assert not second.downloaded(name), "the second update must stop before it downloads"
    finally:
        go.set()
        worker.join(30)
    assert result["rc"] == 0 and exe.read_bytes() == content
    assert "another update is running" in capsys.readouterr().out
    assert sorted(p.name for p in exe.parent.iterdir()) == ["simplicio-loop", "simplicio-loop.bak"]
    # the lock is released: a later update runs
    net2, _, _ = release("3.50.0")
    assert update(exe, net2, Calls(), installed="3.49.0", expect="3.50.0") == 0


@posix
def test_the_sha256_is_taken_from_the_file_on_disk_not_from_the_stream(exe, tmp_path, monkeypatch, capsys):
    net, name, _ = release()
    real = su._download

    def altered_after_the_download(http, url, dest):
        digest = real(http, url, dest)
        dest.write_bytes(dest.read_bytes() + b"# appended on disk\n")  # what the stream said no longer matches the file
        return digest

    monkeypatch.setattr(su, "_download", altered_after_the_download)
    assert update(exe, net, Calls()) == 2
    assert "checksum" in capsys.readouterr().out
    untouched(exe, tmp_path)


def test_an_asset_url_that_is_not_https_is_refused_before_any_download(exe, tmp_path, capsys):
    net, name, _ = release()
    listing = json.loads(net.files[su.LATEST_URL])
    for asset in listing["assets"]:
        asset["browser_download_url"] = asset["browser_download_url"].replace("https://", "http://")
    net.files[su.LATEST_URL] = json.dumps(listing).encode()
    assert update(exe, net, Calls()) == 2
    assert "not https" in capsys.readouterr().out
    assert not net.downloaded(name)
    untouched(exe, tmp_path)


# --- an authenticated request never follows a redirect to another host (review of #1584, item 3) ---------------------------


def serve(handler):
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_authorization_header_is_dropped_when_a_redirect_leaves_the_host():
    seen = []

    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    target = serve(Target)
    where = f"http://127.0.0.1:{target.server_port}/download"

    class Redirect(Target):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", self.server.location)
            self.end_headers()

    other = serve(Redirect)
    other.location = where
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{other.server_port}/api",
                                         headers={"Authorization": "Bearer FAKE_GH_TOKEN"})
        assert su._OPENER.open(request, timeout=10).read() == b"ok"
        assert seen == [None], "the token followed the redirect to another host"
        # a redirect inside the same host keeps the header: it is still the same server

        class Same(Target):
            def do_GET(self):
                seen.append(self.headers.get("Authorization"))
                if self.path == "/api":
                    self.send_response(302)
                    self.send_header("Location", "/elsewhere")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()

        same = serve(Same)
        seen.clear()
        request = urllib.request.Request(f"http://127.0.0.1:{same.server_port}/api",
                                         headers={"Authorization": "Bearer FAKE_GH_TOKEN"})
        su._OPENER.open(request, timeout=10).read()
        assert seen == ["Bearer FAKE_GH_TOKEN", "Bearer FAKE_GH_TOKEN"]
        same.shutdown()
    finally:
        target.shutdown()
        other.shutdown()


def test_a_redirect_from_https_to_plain_http_is_refused():
    handler = su._SameHostRedirect()
    request = urllib.request.Request("https://api.github.com/repos/x/releases/latest",
                                     headers={"Authorization": "Bearer FAKE_GH_TOKEN"})
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(request, io.BytesIO(b""), 302, "Found", {}, "http://example.invalid/asset")
    # https to https on ANOTHER host is the normal GitHub download redirect: allowed, without the token
    moved = handler.redirect_request(request, io.BytesIO(b""), 302, "Found", {}, "https://objects.example.invalid/asset")
    assert moved is not None and moved.get_header("Authorization") is None


def test_the_real_opener_refuses_plain_http_urls():
    with pytest.raises(ValueError):
        su._open("http://example.invalid/x")


def test_windows_stages_the_verified_file_and_swaps_on_the_next_start(tmp_path, capsys):
    exe = tmp_path / "simplicio-loop.exe"
    exe.write_bytes(b"OLD EXE")
    net, name, content = release(platform=("windows", "x86_64"), content=b"NEW EXE")
    calls = Calls()
    assert update(exe, net, calls, platform=("windows", "x86_64"), windows=True) == 0
    out = capsys.readouterr().out
    assert "next start" in out
    assert exe.read_bytes() == b"OLD EXE" and not (tmp_path / "simplicio-loop.exe.bak").exists()
    assert (tmp_path / "simplicio-loop.exe.new").read_bytes() == b"NEW EXE"
    assert calls.runs == []
    assert su.apply_pending(exe, windows=True) is True
    assert exe.read_bytes() == b"NEW EXE"
    assert (tmp_path / "simplicio-loop.exe.bak").read_bytes() == b"OLD EXE"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["simplicio-loop.exe", "simplicio-loop.exe.bak"]
    assert su.apply_pending(exe, windows=True) is False


def test_a_staged_file_that_changed_after_the_check_is_not_swapped_in(tmp_path):
    exe = tmp_path / "simplicio-loop.exe"
    exe.write_bytes(b"OLD EXE")
    net, _, _ = release(platform=("windows", "x86_64"), content=b"NEW EXE")
    assert update(exe, net, Calls(), platform=("windows", "x86_64"), windows=True) == 0
    (tmp_path / "simplicio-loop.exe.new").write_bytes(b"TAMPERED")
    assert su.apply_pending(exe, windows=True) is False
    assert exe.read_bytes() == b"OLD EXE"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["simplicio-loop.exe"]


def test_nothing_pending_is_a_no_op(tmp_path):
    exe = tmp_path / "simplicio-loop.exe"
    exe.write_bytes(b"OLD EXE")
    assert su.apply_pending(exe, windows=True) is False
    assert su.apply_pending(exe, windows=False) is False


# --- the other distributions ---------------------------------------------------------------------------------------------


def test_pip_check_exit_codes(capsys):
    calls = Calls()
    run = lambda fetch, **kw: su.run_update(check=True, installed="3.48.1", fetch=fetch, runner=calls.runner,
                                            editable=False, legacy=[], record=calls.record, **kw)
    assert run(lambda: "v3.48.1") == 0
    assert run(lambda: "v3.49.0") == 10
    assert [r["update_available"] for r in calls.records] == [False, True]
    assert {r["kind"] for r in calls.records} == {"pip"}

    def boom():
        raise OSError("offline")

    assert run(boom) == 2
    assert calls.runs == []


def test_pip_dry_run_prints_the_commands_and_runs_none(capsys):
    calls = Calls()
    rc = su.run_update(dry_run=True, installed="3.48.1", fetch=lambda: "v3.49.0", runner=calls.runner,
                       editable=False, legacy=["simplicio-cli"], record=calls.record)
    out = capsys.readouterr().out
    assert rc == 0 and calls.runs == [] and calls.records == []
    assert "would run" in out and "pip install --upgrade" in out and "@v3.49.0" in out and "uninstall" in out
    assert "install --global" in out


def test_source_checkout_is_refused_even_in_a_dry_run(capsys):
    calls = Calls()
    rc = su.run_update(dry_run=True, installed="3.48.1", fetch=lambda: "v3.49.0", runner=calls.runner, editable=True)
    assert rc == 2 and "git pull" in capsys.readouterr().out and calls.runs == []


def test_the_kind_comes_from_the_distribution_module(monkeypatch, exe, tmp_path):
    seen = []
    monkeypatch.setattr(distribution, "kind", lambda **kw: seen.append(1) or distribution.SOURCE)
    rc = su.run_update(installed="3.48.1", fetch=lambda: "v3.49.0", runner=Calls().runner, legacy=[])
    assert seen and rc == 2  # a source checkout is not updated in place


# --- the cache `doctor` reads offline ------------------------------------------------------------------------------------


def test_the_last_check_round_trips_through_the_state_dir(tmp_path):
    assert su.read_check(tmp_path) is None
    su.write_check({"installed": "3.48.1", "latest": "3.49.0", "update_available": True, "kind": "pip"}, tmp_path)
    got = su.read_check(tmp_path)
    assert got["latest"] == "3.49.0" and got["update_available"] is True and got["checked_at"] > 0
    assert [p.name for p in tmp_path.iterdir()] == ["update-check.json"]
    (tmp_path / "update-check.json").write_text("{not json")
    assert su.read_check(tmp_path) is None


def test_writing_the_cache_never_fails_an_update(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    su.write_check({"latest": "1.0.0"}, blocker / "cannot-be-a-dir")  # no exception


def test_the_state_dir_follows_simplicio_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path))
    assert su.default_state_dir() == tmp_path / ".simplicio-loop"


# --- the token goes to the API only, never to a download --------------------------------------------------------------------


def test_the_update_command_passes_its_flags_and_records_the_check(monkeypatch):
    from simplicio_loop import cli

    seen = {}
    monkeypatch.setattr(su, "run_update", lambda **kw: seen.update(kw) or 10)
    assert cli.main(["update", "--check", "--dry-run", "--force"]) == 10
    assert seen["check"] and seen["dry_run"] and seen["force"] and seen["record"] is su.write_check


def test_the_staged_update_is_applied_at_start_on_a_frozen_windows_binary(monkeypatch, capsys):
    from simplicio_loop import cli_impl

    monkeypatch.setattr(su, "apply_pending", lambda: True)
    cli_impl._finish_pending_update()
    assert "install --global" in capsys.readouterr().err

    def broken():
        raise PermissionError(13, "in use")

    monkeypatch.setattr(su, "apply_pending", broken)
    cli_impl._finish_pending_update()  # never stops the command the user typed
    assert "could not apply" in capsys.readouterr().err



def test_the_github_token_is_sent_to_the_api_and_never_to_a_download(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "fake-gh-token-123")
    api = su._request(su.LATEST_URL)
    download = su._request("https://github.com/simpletibr/simplicio-loop/releases/download/v1/x")
    assert api.get_header("Authorization") == "Bearer fake-gh-token-123"
    assert download.get_header("Authorization") is None
