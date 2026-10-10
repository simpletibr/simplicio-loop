"""The GitHub credential for `simplicio-loop setup` (#1588): reuse what exists, else ask, and check it on the API.

Order: a token piped by the user, GH_TOKEN, GITHUB_TOKEN, the logged-in `gh`, the git credential helper for github.com,
the token stored by an earlier setup, then the hidden prompt. The first source whose token GitHub accepts wins.

A token is never printed, logged, put in an error message or `repr`, or passed in argv. It goes only to
`https://api.github.com` (a loopback address is allowed so tests can use a local server), and a redirect is refused,
so the token cannot be forwarded to another host. Only a token the user typed or piped is stored (`save_token`); a token
from the environment, `gh` or the git helper is used in memory and never copied.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx

from . import auth, setup_hardening

API_URL = "https://api.github.com"
TOKEN_ENVS = ("GH_TOKEN", "GITHUB_TOKEN")
NEEDED_SCOPES = ("repo", "workflow")  # repo, pull requests and issues; workflow files
STORE_NAME = "github.json"
STORE_SCHEMA = "simplicio.github-credential/v1"

# Every GitHub token format is letters, digits, `_` and `-`. Anything else could break a header or a command line.
_TOKEN = re.compile(r"[A-Za-z0-9_-]{20,255}")
_LOGIN = re.compile(r"[A-Za-z0-9\[\]-]{1,60}")
_SCOPE = re.compile(r"[A-Za-z0-9:_.-]{1,60}")
_LOOPBACK = ("127.0.0.1", "::1", "localhost")
_CHILD_ENV = ("PATH", "HOME", "USERPROFILE", "LANG", "SYSTEMROOT", "APPDATA", "XDG_CONFIG_HOME", "GH_CONFIG_DIR")
_STORE_CODES = {"login_symlink": "store_symlink", "login_permissions": "store_permissions",
                "login_lock_timeout": "store_locked", "login_missing": "store_missing"}

Run = Callable[[list[str], dict[str, str], Optional[str], Optional[str]], tuple[Optional[int], str]]
Which = Callable[[str], Optional[str]]


class CredError(Exception):
    """`reason_code` is stable; the message is fixed text and never holds a token."""

    def __init__(self, reason_code: str, message: str = "") -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


def mask(token: str) -> str:
    """`ghp_...wxyz`: the first 4 and the last 4 characters; nothing for a short value."""
    return "****" if len(token) <= 12 else f"{token[:4]}...{token[-4:]}"


@dataclass(frozen=True)
class GitHubCredential:
    source: str  # provided | env:GH_TOKEN | env:GITHUB_TOKEN | gh | git-credential | stored | prompt
    login: str
    scopes: Optional[tuple[str, ...]]  # None: GitHub sent no scope header (a fine-grained token)
    missing_scopes: tuple[str, ...]
    masked: str
    token: str = field(repr=False, compare=False)

    def public(self) -> dict:
        """Everything but the token."""
        return {"source": self.source, "login": self.login, "masked": self.masked,
                "scopes": None if self.scopes is None else list(self.scopes), "missing_scopes": list(self.missing_scopes)}


@dataclass(frozen=True)
class Resolution:
    credential: Optional[GitHubCredential]
    tried: tuple[tuple[str, str], ...]  # (source, outcome): missing | invalid | rejected | unreachable | ok


# --- the API --------------------------------------------------------------------------------------------------------


def _check_base(base_url: str) -> None:
    """https on api.github.com, or http(s) on loopback. Nothing else ever receives a token."""
    try:
        parts = urlsplit(base_url)
        host, _ = parts.hostname or "", parts.port  # reading the port raises ValueError when it is not a number
    except ValueError:
        raise CredError("host_not_allowed", "the GitHub API address is not valid") from None
    github = parts.scheme == "https" and host == "api.github.com"
    local = parts.scheme in ("http", "https") and host in _LOOPBACK
    if parts.username or parts.password or not (github or local):
        raise CredError("host_not_allowed", "a GitHub token is only sent to https://api.github.com")


def validate(token: str, *, base_url: str = API_URL, timeout: float = 15.0) -> tuple[str, Optional[tuple[str, ...]]]:
    """(login, scopes) of a token from `GET /user`. Raises CredError: invalid_token, host_not_allowed,
    redirect_refused, rejected, unreachable, bad_response."""
    if not _TOKEN.fullmatch(token):
        raise CredError("invalid_token", "the token has a length or characters that GitHub tokens never have")
    _check_base(base_url)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "simplicio-loop-setup"}
    try:
        with httpx.Client(follow_redirects=False, timeout=timeout) as client:
            response = client.get(f"{base_url.rstrip('/')}/user", headers=headers)
    except httpx.HTTPError:
        raise CredError("unreachable", "GitHub did not answer") from None
    if response.is_redirect:
        raise CredError("redirect_refused", "GitHub answered with a redirect; the token was not sent anywhere else")
    if response.status_code in (401, 403):
        raise CredError("rejected", f"GitHub did not accept the token (HTTP {response.status_code})")
    if response.status_code != 200:
        raise CredError("bad_response", f"GitHub answered HTTP {response.status_code}")
    try:
        login = str(response.json().get("login") or "")
    except (ValueError, AttributeError):
        login = ""
    if not _LOGIN.fullmatch(login):
        raise CredError("bad_response", "GitHub answered without a valid login")
    header = response.headers.get("x-oauth-scopes")
    if header is None:
        return login, None
    return login, tuple(s for s in (p.strip() for p in header.split(",")) if _SCOPE.fullmatch(s))


def missing_scopes(scopes: Optional[tuple[str, ...]]) -> tuple[str, ...]:
    return () if scopes is None else tuple(s for s in NEEDED_SCOPES if s not in scopes)


# --- the store ------------------------------------------------------------------------------------------------------


def _store_error(exc: auth.LoginError) -> CredError:
    return CredError(_STORE_CODES.get(exc.reason_code, "store_invalid"),
                     "the GitHub credential file cannot be used safely; remove it and run `simplicio-loop setup`")


def save_token(state_dir: Path, token: str, login: str) -> Path:
    """Write the token to `<state_dir>/github.json`: mode 600, folder 700 when new, under the flock of `github.lock`."""
    path = Path(state_dir) / STORE_NAME
    document = {"schema": STORE_SCHEMA, "token": token, "login": login, "saved_at": int(time.time())}
    try:
        with auth.file_lock(path):
            auth.write_login(document, path)
    except auth.LoginError as exc:
        raise _store_error(exc) from None
    return path


def load_token(state_dir: Path) -> Optional[str]:
    """The stored token, or None when nothing is stored. Raises CredError for a symlink or a file others can read."""
    try:
        document = auth.read_login(Path(state_dir) / STORE_NAME)
    except auth.LoginError as exc:
        if exc.reason_code == "login_missing":
            return None
        raise _store_error(exc) from None
    token = document.get("token")
    return token if isinstance(token, str) else None


# --- the sources ----------------------------------------------------------------------------------------------------


def _run(argv: list[str], env: dict[str, str], input_text: Optional[str], cwd: Optional[str] = None) -> tuple[Optional[int], str]:
    try:
        done = subprocess.run(argv, env=env, input=input_text, cwd=cwd, stdin=None if input_text is not None else subprocess.DEVNULL,
                              capture_output=True, text=True, errors="replace", timeout=10, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return done.returncode, done.stdout


run_command = _run  # what `setup_cli` wraps to check a file again right before it runs


def _child_env(environ: Mapping[str, str], **extra: str) -> dict[str, str]:
    env = {name: environ[name] for name in _CHILD_ENV if name in environ}
    if "PATH" in env:
        env["PATH"] = setup_hardening.probe_env(environ)["PATH"]  # no relative, other-writable or ~/.local/bin entry
    return {**env, **extra}


@contextmanager
def _isolated(environ: Mapping[str, str], **extra: str) -> Iterator[tuple[str, dict[str, str]]]:
    """(empty folder outside any repository, child env): where `gh` and `git` run, so no cwd or local config reaches them."""
    with setup_hardening.isolated_git_cwd(environ) as (workdir, isolated):
        yield workdir, {**isolated, **_child_env(environ, **extra)}


def _from_gh(environ: Mapping[str, str], run: Run, which: Which) -> Optional[str]:
    """The token of the logged-in GitHub CLI. The env is an allowlist, so GH_TOKEN cannot answer in its place.

    `gh` is the file `which` finds on the PATH without its unsafe entries; there is none to run when it finds nothing."""
    gh = which("gh")
    if gh is None:
        return None
    with _isolated(environ, GH_PROMPT_DISABLED="1", NO_COLOR="1") as (workdir, env):
        code, out = run([gh, "auth", "token", "--hostname", "github.com"], env, None, workdir)
    return out.strip() if code == 0 else None


def _from_git(environ: Mapping[str, str], run: Run, which: Which) -> Optional[str]:
    """The password the git credential helper holds for github.com; a reply for another host is refused.

    It runs in an empty folder outside any repository, so the `credential.helper` of a local `.git/config` cannot run code.
    The global and system helpers still answer. `git` comes from the PATH without its unsafe entries."""
    git = which("git")
    if git is None:
        return None
    with _isolated(environ, GCM_INTERACTIVE="never") as (workdir, env):
        code, out = run([git, "credential", "fill"], env, "protocol=https\nhost=github.com\n\n", workdir)
    if code != 0:
        return None
    reply = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return reply.get("password") if reply.get("host") == "github.com" else None


def resolve(environ: Optional[Mapping[str, str]] = None, *, state_dir: Path, provided: Optional[str] = None,
            ask: Optional[Callable[[], str]] = None, run: Optional[Run] = None, which: Optional[Which] = None,
            trusted: Optional[Mapping[str, str]] = None, base_url: str = API_URL, timeout: float = 15.0) -> Resolution:
    """Walk the sources in order; the first token GitHub accepts wins. Nothing is stored here.

    A rejected token moves on to the next source. When GitHub cannot be reached nothing can be judged, so the walk stops.
    A token the user piped (`provided`) is final: if it fails, no other source is tried in its place.
    `gh` and `git` are found on the PATH without its unsafe entries; `trusted` names exact files the setup verified.
    """
    environ = os.environ if environ is None else environ
    run = run or _run
    which = which or setup_hardening.safe_which(environ, trusted)
    _check_base(base_url)
    sources: list[tuple[str, Callable[[], Optional[str]]]] = []
    if provided is not None:
        sources.append(("provided", lambda: provided))
    sources += [(f"env:{name}", lambda name=name: environ.get(name)) for name in TOKEN_ENVS]
    sources += [("gh", lambda: _from_gh(environ, run, which)), ("git-credential", lambda: _from_git(environ, run, which)),
                ("stored", lambda: load_token(state_dir))]
    if ask is not None:
        sources.append(("prompt", ask))
    tried: list[tuple[str, str]] = []
    for source, read in sources:
        try:
            token = (read() or "").strip()
        except CredError:
            tried.append((source, "invalid"))
            continue
        if not token:
            tried.append((source, "missing"))
            continue
        try:
            login, scopes = validate(token, base_url=base_url, timeout=timeout)
        except CredError as exc:
            outcome = exc.reason_code if exc.reason_code in ("rejected", "unreachable") else "invalid"
            tried.append((source, outcome))
            if outcome == "unreachable" or source == "provided":
                return Resolution(None, tuple(tried))
            continue
        tried.append((source, "ok"))
        return Resolution(GitHubCredential(source, login, scopes, missing_scopes(scopes), mask(token), token), tuple(tried))
    return Resolution(None, tuple(tried))
