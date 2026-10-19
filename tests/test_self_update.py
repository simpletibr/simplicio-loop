import http.server
import io
import sys
import threading
import urllib.error
import urllib.request

import pytest

from simplicio_loop import distribution, self_update as su

SPEC = "simplicio-loop @ git+https://github.com/simpletibr/simplicio-loop@v3.44.0"


@pytest.fixture(autouse=True)
def plain_pip(monkeypatch):
    """The pip path runs `python -m pip`; a uv-made venv (where these tests may run) would switch to `uv pip`. The uv tests
    below choose that themselves."""
    monkeypatch.setattr(su, "_uv_for", lambda python: None)


def test_parse_and_compare():
    assert su.parse_version("v3.43.17") == (3, 43, 17)
    assert su.parse_version("simplicio-loop v3.44.0") == (3, 44, 0)
    assert su.parse_version("3.43.17") > su.parse_version("3.43.9")


def test_check_only_reports_without_installing(capsys):
    calls = []
    rc = su.run_update(check=True, installed="3.43.16", fetch=lambda: "v3.43.17",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=False)
    assert rc == 10 and calls == []  # #1575: 10 = an update is available (0 = up to date, 2 = error)
    assert "3.43.16 -> 3.43.17" in capsys.readouterr().out


def test_up_to_date_is_noop(capsys):
    calls = []
    rc = su.run_update(installed="3.43.17", fetch=lambda: "v3.43.17",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=False, legacy=[])
    assert rc == 0 and calls == []
    assert "up to date" in capsys.readouterr().out


def test_update_installs_tag_then_refreshes_global():
    calls = []
    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.43.17",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=False, legacy=[])
    assert rc == 0 and len(calls) == 2
    assert "git+https://github.com/simpletibr/simplicio-loop@v3.43.17" in calls[0][-1]
    assert calls[1][-3:] == ["simplicio_loop.cli", "install", "--global"] or "--global" in calls[1]


def test_editable_checkout_refuses(capsys):
    calls = []
    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.43.17",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=True)
    assert rc == 2 and calls == []
    assert "git pull" in capsys.readouterr().out


def test_fetch_failure_fails_closed(capsys):
    def boom():
        raise OSError("offline")
    rc = su.run_update(installed="3.43.16", fetch=boom, runner=lambda c: 0, editable=False)
    assert rc == 1


def test_update_retires_legacy_standalone_distributions_before_installing():
    # simplicio-cli / simplicio-mapper wrote the same paths the single wheel now owns;
    # uninstalling them AFTER the install would delete the new files.
    calls = []
    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.44.0",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=False,
                       legacy=["simplicio-cli", "simplicio-mapper"])
    assert rc == 0 and len(calls) == 3
    assert calls[0][3:] == ["uninstall", "-y", "simplicio-cli", "simplicio-mapper"]
    assert "install" in calls[1] and "--upgrade" in calls[1]


def test_legacy_uninstall_failure_stops_before_install():
    calls = []
    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.44.0",
                       runner=lambda cmd: calls.append(cmd) or 1, editable=False,
                       legacy=["simplicio-cli"])
    assert rc == 1 and len(calls) == 1


def test_up_to_date_with_legacy_distributions_repairs_them(capsys):
    calls = []
    rc = su.run_update(installed="3.44.1", fetch=lambda: "v3.44.1",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=False,
                       legacy=["simplicio-cli", "simplicio-mapper"])
    assert rc == 0 and len(calls) == 2
    assert calls[0][3:] == ["uninstall", "-y", "simplicio-cli", "simplicio-mapper"]
    assert "--force-reinstall" in calls[1] and "--no-deps" in calls[1]
    assert calls[1][-1].endswith("@v3.44.1")


class Calls:
    def __init__(self):
        self.runs, self.records = [], []

    def runner(self, cmd):
        self.runs.append(list(cmd))
        return 0

    def record(self, info):
        self.records.append(dict(info))


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


def test_the_kind_comes_from_the_distribution_module(monkeypatch):
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


def test_the_update_command_passes_its_flags_and_records_the_check(monkeypatch):
    from simplicio_loop import cli

    seen = {}
    monkeypatch.setattr(su, "run_update", lambda **kw: seen.update(kw) or 10)
    assert cli.main(["update", "--check", "--dry-run", "--force"]) == 10
    assert seen["check"] and seen["dry_run"] and seen["force"] and seen["record"] is su.write_check


# --- the token goes to the API only, never to a download ----------------------------------------------------------


def test_the_github_token_is_sent_to_the_api_and_never_to_a_download(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "fake-gh-token-123")
    api = su._request(su.LATEST_URL)
    download = su._request("https://github.com/simpletibr/simplicio-loop/releases/download/v1/x")
    assert api.get_header("Authorization") == "Bearer fake-gh-token-123"
    assert download.get_header("Authorization") is None


def test_in_a_uv_made_venv_the_update_installs_with_uv_pip_into_that_python(monkeypatch):
    # a `uv venv` or `uv tool install` has no pip: the package goes in with `uv pip --python`, and the rest is unchanged
    monkeypatch.setattr(su, "_uv_for", lambda python: "/fake/bin/uv")
    calls = []
    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.44.0", runner=lambda cmd: calls.append(cmd) or 0,
                       editable=False, legacy=[], externally_managed=False)
    assert rc == 0
    assert calls[0] == ["/fake/bin/uv", "pip", "install", "--python", sys.executable, "--upgrade", SPEC]
    assert calls[1][-2:] == ["install", "--global"]


def test_in_a_uv_made_venv_the_legacy_uninstall_and_the_repair_use_uv_pip_too(monkeypatch):
    monkeypatch.setattr(su, "_uv_for", lambda python: "/fake/bin/uv")
    calls = []
    rc = su.run_update(installed="3.44.1", fetch=lambda: "v3.44.1", runner=lambda cmd: calls.append(cmd) or 0,
                       editable=False, legacy=["simplicio-cli"], externally_managed=False)
    assert rc == 0 and len(calls) == 2
    assert calls[0] == ["/fake/bin/uv", "pip", "uninstall", "--python", sys.executable, "simplicio-cli"]  # uv has no -y
    assert calls[1] == ["/fake/bin/uv", "pip", "install", "--python", sys.executable, "--reinstall", "--no-deps",
                        "simplicio-loop @ git+https://github.com/simpletibr/simplicio-loop@v3.44.1"]


def test_a_failed_install_step_after_the_package_update_is_reported_and_the_update_still_succeeds(capsys):
    recorded, calls = [], []

    def runner(cmd):
        calls.append(cmd)
        return 2 if cmd[-1] == "--global" else 0  # `install --global` does not finish; the package itself was updated

    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.44.0", runner=runner, editable=False, legacy=[],
                       externally_managed=False, record=recorded.append)
    out = capsys.readouterr().out
    assert rc == 0  # only a failed package update fails the update
    assert recorded[-1]["installed"] == "3.44.0" and recorded[-1]["update_available"] is False  # `update --check` agrees now
    assert "install --global" in out and "next:" in out


def test_a_failed_package_update_fails_the_update_and_records_nothing(capsys):
    recorded = []
    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.44.0", runner=lambda cmd: 1 if "--upgrade" in cmd else 0,
                       editable=False, legacy=[], externally_managed=False, record=recorded.append)
    assert rc == 1
    assert all(item["installed"] == "3.43.16" for item in recorded)  # the failed update never records the new version
    assert "pip install failed" in capsys.readouterr().out
