"""Fakes of the `setup` steps, shared by the flow tests and the wiring tests (#1588)."""
from __future__ import annotations

import io

from simplicio_loop import github_cred, host_detect, prereqs, setup_cli

TOKEN = "ghp_FAKEFAKEFAKEFAKEFAKE0042"
OTHER_TOKEN = "ghp_FAKEFAKEFAKEFAKEFAKE0043"


def check(name, status="ok", required=True, fix=""):
    return prereqs.Check(name=name, status=status, required=required, path=f"/usr/bin/{name}" if status == "ok" else None,
                         version="1.0.0" if status == "ok" else None, minimum=None, fix=fix, auto="")


def host(id, installed=True, login="ok", watcher=True, needs_node=False):
    return host_detect.HostStatus(
        id=id, name=id, installed=installed, path=f"/bin/{id}" if installed else None,
        version="2.0.0" if installed else None, login=login if installed else "n/a", watcher=watcher,
        install="npm install -g x", needs_node=needs_node, exe_verified=True)


def credential(source="gh", token=TOKEN, scopes=("repo", "workflow"), missing=()):
    return github_cred.GitHubCredential(source=source, login="octocat", scopes=scopes, missing_scopes=missing,
                                        masked=github_cred.mask(token), token=token)


class Fakes:
    """Records every call; each step answers from a plain attribute."""

    def __init__(self):
        self.hosts = [host("claude-code"), host("codex", login="no"), host("gemini", installed=False)]
        self.checks = [check("python"), check("git"), check("gh")]
        self.actions = []
        self.resolution = github_cred.Resolution(credential(), (("gh", "ok"),))
        self.stored = None
        self.calls = []
        self.tty = False
        self.stdin_text = ""
        self.ask_value = TOKEN
        self.during_resolve = None  # called inside the GitHub step: lets a test change a file mid-run

    def seams(self):
        def detect(environ, **_):
            self.calls.append(("detect",))
            return self.hosts

        def check_all(environ, **kw):
            self.calls.append(("check_all", dict(kw), environ.get("PATH")))
            return list(self.checks)

        def ensure(checks, **kw):
            self.calls.append(("ensure", dict(kw)))
            return list(self.actions)

        def resolve(environ, **kw):
            self.calls.append(("resolve", {k: v for k, v in kw.items() if k != "state_dir"}))
            if self.during_resolve:
                self.during_resolve()
            return self.resolution

        def save_token(directory, token, login):
            self.calls.append(("save", login))
            self.stored = token
            return directory / "github.json"

        return setup_cli.Seams(
            detect=detect, check_all=check_all, ensure=ensure, resolve=resolve, save_token=save_token,
            load_token=lambda directory: self.stored, isatty=lambda: self.tty,
            ask=lambda: self.ask_value, read_stdin=lambda size: self.stdin_text[:size])

    def names(self):
        return [call[0] for call in self.calls]


def run(fakes, home, path="/usr/bin", **options):
    out = io.StringIO()
    code = setup_cli.run(setup_cli.Options(**options), environ={"HOME": str(home), "PATH": path},
                         seams=fakes.seams(), out=out)
    return code, out.getvalue()


def summary_file(home):
    return home / ".simplicio-loop" / "setup.json"
