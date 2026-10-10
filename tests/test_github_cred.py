"""github_cred (#1588): the token goes only to api.github.com, is never shown, and is stored only when the user typed it."""
from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from simplicio_loop import github_cred, setup_hardening
from simplicio_loop.github_cred import CredError

GOOD = "ghp_FAKEFAKEFAKEFAKEFAKE0001"
FINE = "github_pat_FAKEFAKEFAKEFAKE0002"
TWO = "ghp_FAKEFAKEFAKEFAKEFAKE0003"
BAD = "ghp_FAKEFAKEFAKEFAKEFAKE0004"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX modes, symlinks and sh scripts")


class Api:
    """A local stand-in for api.github.com. `routes` maps a token to (status, headers, body); every request is recorded."""

    def __init__(self, routes=None, delay=0.0):
        self.routes, self.hits, self.delay = dict(routes or {}), [], delay
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append({"path": self.path, "headers": dict(self.headers)})
                time.sleep(outer.delay)
                token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
                status, headers, body = outer.routes.get(token, (401, {}, b"{}"))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def ok(login="octocat", scopes="repo, workflow"):
    headers = {} if scopes is None else {"X-OAuth-Scopes": scopes}
    return 200, headers, json.dumps({"login": login}).encode()


@pytest.fixture
def api():
    made = []

    def make(routes=None, delay=0.0):
        made.append(Api(routes, delay))
        return made[-1]

    yield make
    for item in made:
        item.close()


@pytest.fixture(autouse=True)
def direct_connections(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")


def closed_port_url():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def raised(call, *args, **kwargs):
    with pytest.raises(CredError) as caught:
        call(*args, **kwargs)
    return caught.value


# --- mask and the credential ----------------------------------------------------------------------------------------


def test_mask_shows_four_and_four_and_nothing_for_short_values():
    assert github_cred.mask(GOOD) == "ghp_...0001"
    assert github_cred.mask("short") == "****" and github_cred.mask("x" * 12) == "****"


def test_the_credential_never_shows_its_token():
    cred = github_cred.GitHubCredential("gh", "octocat", ("repo",), ("workflow",), github_cred.mask(GOOD), GOOD)
    assert GOOD not in repr(cred) and GOOD not in json.dumps(cred.public()) and "token" not in cred.public()
    assert cred.public() == {"source": "gh", "login": "octocat", "masked": "ghp_...0001", "scopes": ["repo"],
                             "missing_scopes": ["workflow"]}
    assert github_cred.GitHubCredential("gh", "o", (), (), "m", GOOD).public()["scopes"] == []  # none is not unknown
    assert github_cred.GitHubCredential("gh", "o", None, (), "m", GOOD).public()["scopes"] is None


# --- validate -------------------------------------------------------------------------------------------------------


def test_validate_returns_login_and_scopes_and_sends_a_bearer_header_only(api):
    server = api({GOOD: ok()})
    assert github_cred.validate(GOOD, base_url=server.url) == ("octocat", ("repo", "workflow"))
    sent = server.hits[0]["headers"]
    assert server.hits[0]["path"] == "/user" and sent["Authorization"] == f"Bearer {GOOD}"
    assert sent["User-Agent"] == "simplicio-loop-setup" and sent["X-GitHub-Api-Version"] == "2022-11-28"


def test_scopes_none_means_unknown_and_an_empty_header_means_none(api):
    server = api({FINE: ok(scopes=None), GOOD: ok(scopes=""), TWO: ok(scopes="repo")})
    assert github_cred.validate(FINE, base_url=server.url)[1] is None
    assert github_cred.validate(GOOD, base_url=server.url)[1] == ()
    assert github_cred.missing_scopes(None) == () and github_cred.missing_scopes(()) == ("repo", "workflow")
    assert github_cred.missing_scopes(("repo",)) == ("workflow",)
    assert github_cred.missing_scopes(("repo", "workflow", "gist")) == ()


@pytest.mark.parametrize("status, code", [(401, "rejected"), (403, "rejected"), (500, "bad_response"), (404, "bad_response")])
def test_validate_maps_http_errors(api, status, code):
    server = api({GOOD: (status, {}, b"{}")})
    assert raised(github_cred.validate, GOOD, base_url=server.url).reason_code == code


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"login": "!!bad!!"}', b'{"login": ""}', b"{}"])
def test_validate_refuses_an_answer_without_a_valid_login(api, body):
    server = api({GOOD: (200, {}, body)})
    assert raised(github_cred.validate, GOOD, base_url=server.url).reason_code == "bad_response"


def test_validate_says_unreachable_for_a_closed_port_and_for_a_slow_server(api):
    assert raised(github_cred.validate, GOOD, base_url=closed_port_url(), timeout=2).reason_code == "unreachable"
    slow = api({GOOD: ok()}, delay=1.5)
    assert raised(github_cred.validate, GOOD, base_url=slow.url, timeout=0.2).reason_code == "unreachable"


def test_a_redirect_is_refused_and_its_target_never_gets_a_request(api):
    elsewhere = api({GOOD: ok()})
    server = api({GOOD: (302, {"Location": elsewhere.url + "/user"}, b"")})
    assert raised(github_cred.validate, GOOD, base_url=server.url).reason_code == "redirect_refused"
    assert len(server.hits) == 1 and elsewhere.hits == []


@pytest.mark.parametrize("base", [
    "https://evil.example", "http://evil.example", "https://api.github.com.evil.example", "https://evil.example/api.github.com",
    "https://api.github.com@evil.example", "https://user:pw@api.github.com", "http://api.github.com", "ftp://127.0.0.1",
    "https://github.com", "https://api.github.com:bad", "", "api.github.com",
])
def test_a_token_is_never_sent_to_another_host(base):
    error = raised(github_cred.validate, GOOD, base_url=base)
    assert error.reason_code == "host_not_allowed" and GOOD not in str(error)


@pytest.mark.parametrize("token", ["", "short", "ghp_has space_FAKEFAKEFAKE0001", GOOD + "\nX-Evil: 1", "ghp_é" + "x" * 30, "x" * 300])
def test_a_token_with_a_wrong_shape_is_refused_before_any_request(api, token):
    server = api({GOOD: ok()})
    error = raised(github_cred.validate, token, base_url=server.url)
    assert error.reason_code == "invalid_token" and server.hits == []


# --- resolve --------------------------------------------------------------------------------------------------------


class Runner:
    """A fake `run`: answers `gh auth token` and `git credential fill`, and records every call."""

    def __init__(self, gh=None, git=None, git_host="github.com"):
        self.gh, self.git, self.git_host, self.calls = gh, git, git_host, []

    def __call__(self, argv, env, input_text, cwd=None):
        self.calls.append((argv, dict(env), input_text, cwd))
        if argv[0] == "gh":
            return (0, self.gh + "\n") if self.gh else (1, "")
        reply = f"protocol=https\nhost={self.git_host}\nusername=x\n" + (f"password={self.git}\n" if self.git else "")
        return (0, reply)

    def asked(self, program):
        return [call for call in self.calls if call[0][0] == program]


def by_name(name):
    """A fake `which`: the program is its own name, so a fake `run` sees `gh` and `git` as before."""
    return name


def resolve(tmp_path, api_server, environ=None, **kw):
    kw.setdefault("which", by_name)
    return github_cred.resolve({} if environ is None else environ, state_dir=tmp_path / "state", base_url=api_server.url,
                               timeout=5, **kw)


def test_the_order_is_provided_env_gh_git_stored_prompt(tmp_path, api):
    server = api({t: ok(login=name) for t, name in ((GOOD, "provided"), (TWO, "env"), (FINE, "gh"), (BAD, "stored"))})
    runner = Runner(gh=FINE, git=TWO)
    github_cred.save_token(tmp_path / "state", BAD, "stored")
    env = {"GH_TOKEN": TWO}
    seen = []
    for kwargs, source in [({"provided": GOOD}, "provided"), ({}, "env:GH_TOKEN")]:
        got = resolve(tmp_path, server, env, run=runner, ask=lambda: seen.append(1) or GOOD, **kwargs).credential
        assert got.source == source
    assert resolve(tmp_path, server, {"GITHUB_TOKEN": TWO}, run=runner).credential.source == "env:GITHUB_TOKEN"
    assert resolve(tmp_path, server, run=runner).credential.source == "gh"
    assert resolve(tmp_path, server, run=Runner(git=TWO)).credential.source == "git-credential"
    assert resolve(tmp_path, server, run=Runner()).credential.source == "stored"
    (tmp_path / "state" / "github.json").unlink()
    prompted = resolve(tmp_path, server, run=Runner(), ask=lambda: GOOD).credential
    assert prompted.source == "prompt" and prompted.login == "provided" and seen == []  # the prompt only runs last


def test_a_rejected_source_falls_through_and_a_later_one_wins(tmp_path, api):
    server = api({FINE: ok(login="from-gh")})
    result = resolve(tmp_path, server, {"GH_TOKEN": BAD}, run=Runner(gh=FINE))
    assert result.credential.login == "from-gh"
    assert result.tried == (("env:GH_TOKEN", "rejected"), ("env:GITHUB_TOKEN", "missing"), ("gh", "ok"))


def test_unreachable_stops_the_walk_without_claiming_anything(tmp_path):
    runner = Runner(gh=GOOD)
    result = github_cred.resolve({"GH_TOKEN": TWO}, state_dir=tmp_path / "s", base_url=closed_port_url(), timeout=2, run=runner, which=by_name)
    assert result.credential is None and result.tried == (("env:GH_TOKEN", "unreachable"),)
    assert runner.calls == []  # gh and git were not even asked


def test_a_piped_token_is_final(tmp_path, api):
    server = api({TWO: ok()})
    runner = Runner(gh=TWO)
    result = resolve(tmp_path, server, {"GH_TOKEN": TWO}, provided=BAD, run=runner)
    assert result.credential is None and result.tried == (("provided", "rejected"),) and runner.calls == []
    result = resolve(tmp_path, server, provided="not a token", run=runner)
    assert result.credential is None and result.tried == (("provided", "invalid"),)


def test_nothing_found_lists_every_source_as_missing(tmp_path, api):
    result = resolve(tmp_path, api(), run=Runner())
    assert result.credential is None
    assert [source for source, _ in result.tried] == ["env:GH_TOKEN", "env:GITHUB_TOKEN", "gh", "git-credential", "stored"]
    assert {outcome for _, outcome in result.tried} == {"missing"}


def test_an_empty_environment_is_not_replaced_by_the_real_one(tmp_path, api, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", GOOD)
    server = api({GOOD: ok()})
    assert resolve(tmp_path, server, {}, run=Runner()).credential is None
    assert github_cred.resolve(None, state_dir=tmp_path / "s", base_url=server.url, run=Runner(), which=by_name).credential.source == "env:GH_TOKEN"


def test_a_git_reply_for_another_host_or_without_a_password_is_refused(tmp_path, api):
    server = api({GOOD: ok()})
    for runner in (Runner(git=GOOD, git_host="evil.example"), Runner(git=None), Runner(git="x y")):
        result = resolve(tmp_path, server, run=runner)
        assert result.credential is None, runner.git_host


def test_gh_and_git_get_a_small_environment_and_the_right_question(tmp_path, api):
    server = api({GOOD: ok()})
    runner = Runner(gh=None, git=GOOD)
    secret_env = {"PATH": "/bin", "HOME": "/h", "GH_ENTERPRISE_TOKEN": "s1", "OPENAI_API_KEY": "s2", "GH_TOKEN": ""}
    resolve(tmp_path, server, secret_env, run=runner)
    (gh_argv, gh_env, gh_input, gh_cwd), (git_argv, git_env, git_input, git_cwd) = runner.calls
    assert gh_argv == ["gh", "auth", "token", "--hostname", "github.com"] and gh_input is None and gh_cwd is not None
    assert git_argv == ["git", "credential", "fill"] and git_input == "protocol=https\nhost=github.com\n\n" and git_cwd is not None
    assert git_env["GIT_TERMINAL_PROMPT"] == "0" and git_env["GCM_INTERACTIVE"] == "never" and gh_env["GH_PROMPT_DISABLED"] == "1"
    for env in (gh_env, git_env):
        assert not {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "OPENAI_API_KEY"} & set(env)


def test_the_real_runner_runs_fake_gh_and_git_programs(tmp_path, api):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dump = tmp_path / "env.txt"
    (bin_dir / "gh").write_text(f"#!/bin/sh\n/usr/bin/env > {dump}\necho {GOOD}\n")
    (bin_dir / "git").write_text(f"#!/bin/sh\n/bin/cat > {tmp_path / 'stdin.txt'}\nprintf 'host=github.com\\npassword={TWO}\\n'\n")
    for name in ("gh", "git"):
        (bin_dir / name).chmod(0o755)
    server = api({GOOD: ok(login="via-gh"), TWO: ok(login="via-git")})
    env = {"PATH": str(bin_dir), "HOME": str(tmp_path), "GH_ENTERPRISE_TOKEN": "leak-me"}
    assert resolve(tmp_path, server, env).credential.login == "via-gh"
    assert "leak-me" not in dump.read_text() and "GH_PROMPT_DISABLED=1" in dump.read_text()
    (bin_dir / "gh").write_text("#!/bin/sh\nexit 1\n")
    assert resolve(tmp_path, server, env).credential.login == "via-git"
    assert (tmp_path / "stdin.txt").read_text() == "protocol=https\nhost=github.com\n\n"


def test_a_missing_gh_or_git_program_is_just_a_missing_source(tmp_path, api):
    result = resolve(tmp_path, api(), {"PATH": str(tmp_path)})
    assert result.credential is None and ("gh", "missing") in result.tried and ("git-credential", "missing") in result.tried


def test_resolve_never_stores_anything_and_never_copies_a_found_token(tmp_path, api):
    server = api({GOOD: ok(), TWO: ok(), FINE: ok()})
    resolve(tmp_path, server, {"GH_TOKEN": GOOD}, run=Runner(gh=TWO, git=FINE))
    resolve(tmp_path, server, run=Runner(gh=TWO))
    resolve(tmp_path, server, run=Runner(), ask=lambda: FINE)  # even the prompt: the caller decides to store
    assert not (tmp_path / "state").exists()


def test_a_prompt_that_fails_or_is_empty_is_not_a_credential(tmp_path, api):
    server = api({GOOD: ok()})
    assert resolve(tmp_path, server, run=Runner(), ask=lambda: "").tried[-1] == ("prompt", "missing")
    assert resolve(tmp_path, server, run=Runner(), ask=lambda: BAD).tried[-1] == ("prompt", "rejected")

    def refuse():
        raise RuntimeError("cannot hide the input")

    with pytest.raises(RuntimeError):  # a refusal of the prompt is the caller's to handle, not swallowed
        resolve(tmp_path, server, run=Runner(), ask=refuse)


def test_resolve_refuses_a_foreign_api_host_before_reading_any_source(tmp_path):
    runner = Runner(gh=GOOD)
    error = raised(github_cred.resolve, {"GH_TOKEN": GOOD}, state_dir=tmp_path, base_url="https://evil.example", run=runner, which=by_name)
    assert error.reason_code == "host_not_allowed" and runner.calls == []


# --- the store ------------------------------------------------------------------------------------------------------


def test_save_token_is_private_atomic_and_locked(tmp_path):
    state = tmp_path / "fresh" / ".simplicio-loop"
    path = github_cred.save_token(state, GOOD, "octocat")
    assert path == state / "github.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(state.stat().st_mode) == 0o700
    lock = state / "github.lock"
    assert lock.exists() and stat.S_IMODE(lock.stat().st_mode) == 0o600
    document = json.loads(path.read_text())
    assert document["schema"] == "simplicio.github-credential/v1" and document["token"] == GOOD and document["login"] == "octocat"
    assert github_cred.load_token(state) == GOOD
    assert [p.name for p in state.iterdir()] == ["github.json", "github.lock"]  # no temp file left


def test_save_token_into_a_blocked_folder_is_a_cred_error_not_an_os_error(tmp_path):
    (tmp_path / "blocked").write_text("a file where the folder should be", encoding="utf-8")
    with pytest.raises(CredError) as raised:
        github_cred.save_token(tmp_path / "blocked", GOOD, "octocat")
    assert raised.value.reason_code == "store_invalid"
    assert GOOD not in str(raised.value)  # the message never holds the token


def test_save_token_waits_for_the_lock(tmp_path, monkeypatch):
    state = tmp_path / "s"
    calls = []
    real = github_cred.auth.file_lock

    def spy(path, **kw):
        calls.append(path.name)
        return real(path, **kw)

    monkeypatch.setattr(github_cred.auth, "file_lock", spy)
    github_cred.save_token(state, GOOD, "octocat")
    assert calls == ["github.json"]


def test_a_replaced_token_replaces_the_old_one(tmp_path):
    github_cred.save_token(tmp_path, GOOD, "a")
    github_cred.save_token(tmp_path, TWO, "b")
    assert github_cred.load_token(tmp_path) == TWO


def test_load_token_is_none_without_a_file_and_refuses_unsafe_files(tmp_path):
    assert github_cred.load_token(tmp_path) is None
    path = github_cred.save_token(tmp_path, GOOD, "a")
    path.chmod(0o644)
    assert raised(github_cred.load_token, tmp_path).reason_code == "store_permissions"
    path.unlink()
    victim = tmp_path / "victim"
    victim.write_text(json.dumps({"token": GOOD}))
    victim.chmod(0o600)
    path.symlink_to(victim)
    assert raised(github_cred.load_token, tmp_path).reason_code == "store_symlink"
    path.unlink()
    path.write_text("[]")
    path.chmod(0o600)
    assert raised(github_cred.load_token, tmp_path).reason_code == "store_invalid"
    path.write_text(json.dumps({"token": 5}))
    assert github_cred.load_token(tmp_path) is None


def test_save_token_refuses_a_symlink_and_a_folder_others_can_write(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    victim = tmp_path / "victim"
    victim.write_text("keep")
    (state / "github.json").symlink_to(victim)
    assert raised(github_cred.save_token, state, GOOD, "a").reason_code == "store_symlink"
    assert victim.read_text() == "keep"
    (state / "github.json").unlink()
    state.chmod(0o777)
    assert raised(github_cred.save_token, state, GOOD, "a").reason_code == "store_permissions"
    assert not (state / "github.json").exists()


def test_an_existing_folder_with_mode_755_is_left_as_it_is(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o755)
    github_cred.save_token(state, GOOD, "a")
    assert stat.S_IMODE(state.stat().st_mode) == 0o755


# --- nothing leaks ----------------------------------------------------------------------------------------------------


def test_no_token_reaches_output_logs_errors_or_any_file_but_the_store(tmp_path, api, capsys, caplog):
    server = api({GOOD: ok(), FINE: (500, {}, b"{}"), BAD: (302, {"Location": "http://127.0.0.1:1/"}, b"")})
    errors = []
    nobody = "ghp_FAKEFAKEFAKEFAKEFAKE0099"  # the server answers 401 for a token it does not know
    for token in (FINE, BAD, nobody, "\n" + GOOD, "x" * 30):
        try:
            github_cred.validate(token, base_url=server.url)
        except CredError as exc:
            errors.append(str(exc) + repr(exc))
    errors.append(str(raised(github_cred.validate, GOOD, base_url="https://evil.example")))
    result = resolve(tmp_path, server, {"GH_TOKEN": FINE}, run=Runner(gh=GOOD))
    github_cred.save_token(tmp_path / "state", TWO, "octocat")
    seen = capsys.readouterr()
    blob = " ".join(errors) + repr(result) + json.dumps(result.credential.public()) + seen.out + seen.err + caplog.text
    for token in (GOOD, FINE, BAD, TWO, nobody):
        assert token not in blob
    holders = [p for p in tmp_path.rglob("*") if p.is_file() and TWO.encode() in p.read_bytes()]
    assert holders == [tmp_path / "state" / "github.json"]
    for token in (GOOD, FINE, BAD):
        assert not [p for p in tmp_path.rglob("*") if p.is_file() and token.encode() in p.read_bytes()]


# --- git credential fill outside the user's repository (#1657) ---------------------------------------------------------


def git_world(tmp_path, monkeypatch, global_config=""):
    """A real repository whose own config holds a hostile helper, an empty HOME, and the environ to hand to `_from_git`."""
    for name in ("GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_COUNT", "GIT_DIR", "GIT_WORK_TREE"):
        monkeypatch.delenv(name, raising=False)
    home, repo, marker = tmp_path / "home", tmp_path / "repo", tmp_path / "helper-ran"
    home.mkdir()
    repo.mkdir()
    (home / ".gitconfig").write_text(global_config)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env={**os.environ, "HOME": str(home)})
    with open(repo / ".git" / "config", "a") as config:
        config.write(f"[credential]\n\thelper = !touch {marker}\n")
    monkeypatch.chdir(repo)
    return {"PATH": os.environ["PATH"], "HOME": str(home)}, marker


def test_a_credential_helper_of_the_local_git_config_never_runs(tmp_path, monkeypatch):
    environ, marker = git_world(tmp_path, monkeypatch)
    assert github_cred._from_git(environ, github_cred._run, setup_hardening.safe_which(environ)) is None  # nothing global answers
    assert not marker.exists()


def test_git_credential_fill_runs_outside_any_repository_and_never_prompts(tmp_path, monkeypatch):
    environ, _ = git_world(tmp_path, monkeypatch)
    seen = []
    real_run = subprocess.run

    def spy(argv, **kwargs):
        seen.append((argv, kwargs))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(github_cred.subprocess, "run", spy)
    github_cred._from_git(environ, github_cred._run, setup_hardening.safe_which(environ))
    (argv, kwargs), = seen
    assert Path(argv[0]).name == "git" and argv[1:] == ["credential", "fill"] and kwargs["shell"] is False
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0" and kwargs["env"]["GCM_INTERACTIVE"] == "never"
    cwd = Path(kwargs["cwd"])
    assert cwd != Path.cwd() and not any((parent / ".git").exists() for parent in (cwd, *cwd.parents))
    assert kwargs["env"]["GIT_CEILING_DIRECTORIES"] == str(cwd.parent)
    assert not cwd.exists()  # the empty folder is removed afterwards


def test_a_global_credential_helper_still_answers_from_the_isolated_folder(tmp_path, monkeypatch):
    helper = '[credential]\n\thelper = "!f() { test \\"$1\\" = get && echo username=u && echo password=' + GOOD + '; }; f"\n'
    environ, marker = git_world(tmp_path, monkeypatch, global_config=helper)
    assert github_cred._from_git(environ, github_cred._run, setup_hardening.safe_which(environ)) == GOOD
    assert not marker.exists()


# --- gh and git are looked up like every other probe: never through an unsafe PATH entry (#1657) ------------------------


def fake_programs(directory, tag):
    """A `gh` and a `git` that write a marker named after `tag` and then answer with a valid token."""
    directory.mkdir(parents=True, exist_ok=True)
    markers = {}
    for name, body in (("gh", f"echo {GOOD}\n"),
                       ("git", f"cat > /dev/null\nprintf 'protocol=https\\nhost=github.com\\nusername=u\\npassword={GOOD}\\n'\n")):
        markers[name] = directory.parent / f"ran-{tag}-{name}"
        script = directory / name
        script.write_text(f"#!/bin/sh\n: > {markers[name]}\n{body}")
        script.chmod(0o755)
    return markers


def hostile_machine(tmp_path, monkeypatch, kind):
    """(environ, markers of the unsafe programs, markers of the safe ones); the unsafe entry comes first on PATH."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(tmp_path)
    unsafe = {"writable_by_others": tmp_path / "shared", "user_local_bin": home / ".local" / "bin",
              "relative": tmp_path / "reldir", "empty": tmp_path}[kind]
    entry = {"relative": "reldir", "empty": ""}.get(kind, str(unsafe))
    bad = fake_programs(unsafe, "bad")
    if kind == "writable_by_others":
        unsafe.chmod(0o777)
    safe = tmp_path / "safe" / "bin"
    good = fake_programs(safe, "good")
    return {"PATH": os.pathsep.join([entry, str(safe)]), "HOME": str(home)}, bad, good


UNSAFE_KINDS = ("writable_by_others", "user_local_bin", "relative", "empty")


@pytest.mark.parametrize("kind", UNSAFE_KINDS)
def test_gh_and_git_from_an_unsafe_path_entry_are_never_run_and_the_safe_ones_are(tmp_path, monkeypatch, api, kind):
    environ, bad, good = hostile_machine(tmp_path, monkeypatch, kind)
    server = api({})  # every token is rejected, so the walk reaches gh and then git
    result = github_cred.resolve(environ, state_dir=tmp_path / "state", base_url=server.url, timeout=5)
    assert [name for name, marker in bad.items() if marker.exists()] == []
    assert all(marker.exists() for marker in good.values())  # the safe gh and git, later on PATH, did answer
    assert result.tried[-3:-1] == (("gh", "rejected"), ("git-credential", "rejected"))


@pytest.mark.parametrize("kind", UNSAFE_KINDS)
def test_with_only_unsafe_entries_gh_and_git_count_as_missing_and_nothing_runs(tmp_path, monkeypatch, kind):
    environ, bad, _ = hostile_machine(tmp_path, monkeypatch, kind)
    environ["PATH"] = environ["PATH"].split(os.pathsep)[0]
    result = github_cred.resolve(environ, state_dir=tmp_path / "state", base_url=closed_port_url(), timeout=2)
    assert [name for name, marker in bad.items() if marker.exists()] == []
    assert result.tried == (("env:GH_TOKEN", "missing"), ("env:GITHUB_TOKEN", "missing"), ("gh", "missing"),
                            ("git-credential", "missing"), ("stored", "missing"))


def test_a_vouched_gh_runs_from_its_exact_path_even_in_local_bin(tmp_path, monkeypatch, api):
    environ, bad, _ = hostile_machine(tmp_path, monkeypatch, "user_local_bin")
    environ["PATH"] = "/nonexistent-dir"
    vouched = tmp_path / "home" / ".local" / "bin" / "gh"
    server = api({GOOD: ok()})
    result = github_cred.resolve(environ, state_dir=tmp_path / "state", base_url=server.url, timeout=5, trusted={"gh": str(vouched)})
    assert result.credential.source == "gh" and bad["gh"].exists() and not bad["git"].exists()


def test_gh_and_git_run_in_an_empty_folder_outside_any_repository_with_a_clean_path(tmp_path, monkeypatch, api):
    environ, _, _ = hostile_machine(tmp_path, monkeypatch, "relative")
    seen = []
    real_run = subprocess.run

    def spy(argv, **kwargs):
        seen.append((argv, kwargs))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(github_cred.subprocess, "run", spy)
    github_cred.resolve(environ, state_dir=tmp_path / "state", base_url=api({}).url, timeout=5)
    assert [Path(argv[0]).name for argv, _ in seen] == ["gh", "git"]
    for argv, kwargs in seen:
        assert Path(argv[0]).parent == tmp_path / "safe" / "bin"  # the file `which` found, not a bare name
        assert kwargs["cwd"] and Path(kwargs["cwd"]) != tmp_path
        assert kwargs["env"]["PATH"] == str(tmp_path / "safe" / "bin")
