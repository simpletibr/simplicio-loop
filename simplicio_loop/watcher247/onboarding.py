"""First run of the 24/7 watcher: `simplicio-loop watch247 setup`.

The watcher ships with no credentials and assumes none. The user gives two things when starting it:

* the GitHub token: asked with hidden input (or piped with --github-token-stdin, never as an argument, because argv is
  visible in `ps`), checked with a real `gh api user` call, then written as GH_TOKEN to the service env file
  (mode 600, atomic replace);
* the Simplicio account e-mail: recorded in the state dir (not a secret) and compared with the account of login.json.
  The login itself is the Runtime flow `simplicio login google`: this repo has no login flow, so setup prints the
  exact command for the service user and then reports the reason code of the existing subscription check.

Without the credentials the tick stays idle and `status.json` says which one is missing and what to run
(idle_status), so a service with Restart=always never crash-loops on them.

Exit codes: 0 all set, 1 a step is still open (token rejected, login to do, ...), 2 refused (bad input or unsafe
target; nothing was changed). The token is never printed, logged or stored anywhere but the env file.
"""
from __future__ import annotations

import asyncio
import contextlib
import errno
import getpass
import json
import os
import re
import stat
import sys
import tempfile
import warnings
from collections.abc import Mapping
from pathlib import Path

from . import config, env_guard, login_check, proc, state, subscription

COMMAND = "simplicio-loop watch247 setup"
LOGIN_COMMAND = f"sudo -u {login_check.SERVICE_USER} -H simplicio login google"  # `simplicio --help`: login google
LOGOUT_COMMAND = f"sudo -u {login_check.SERVICE_USER} -H simplicio logout"
RESTART_COMMAND = "systemctl restart simplicio-loop-247"
KEY = "GH_TOKEN"
TOKEN_ENV = ("GH_TOKEN", "GITHUB_TOKEN")  # the variables gh reads
MAX_INPUT = 1024

# Every GitHub token format (ghp_, github_pat_, gho_, ghs_, 40 hex) is letters, digits and underscore. Nothing that a
# shell or systemd reads specially (quotes, $, #, backslash, space) can pass, so the env file line cannot be abused.
_TOKEN = re.compile(r"[A-Za-z0-9_-]{20,255}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+'-]{1,64}@([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}")
_LOGIN = re.compile(r"[A-Za-z0-9\[\]-]{1,60}")
_SCOPE = re.compile(r"[A-Za-z0-9:_.-]{1,60}")
_BROAD = frozenset({"delete_repo", "workflow", "write:packages", "delete:packages", "codespace"})

_HINTS = {
    "login_missing": f"no Simplicio login for the service user yet. Run: {LOGIN_COMMAND}  then run `{COMMAND} --check`",
    "account_mismatch": ("login.json belongs to another Simplicio account than the e-mail you gave. "
                         f"Run: {LOGOUT_COMMAND}  then {LOGIN_COMMAND}"),
    "refresh_failed": f"the login expired. Run: {LOGIN_COMMAND}",
    "subscription_required": "the account has no active paid subscription",
    "entitlement_required": "the Simplicio server did not confirm the entitlement",
    "validate_unreachable": "the Simplicio server did not answer; run this command again later",
}


class Refused(Exception):
    """Bad input or an unsafe target: nothing was changed."""


class Failed(Exception):
    """A check against GitHub failed: nothing was stored."""


# --- the watcher side: what the idle tick reports -----------------------------------------------------------------


def missing_github_token(environ: Mapping[str, str] | None = None) -> str | None:
    """'github_token_missing' when neither GH_TOKEN nor GITHUB_TOKEN holds a value, else None."""
    env = os.environ if environ is None else environ
    return None if any((env.get(name) or "").strip() for name in TOKEN_ENV) else "github_token_missing"


def idle_status(reason: str) -> dict:
    """The status.json fields of a tick that waits for the setup: the reason and the exact command to run."""
    if reason == "login_missing":
        detail = f"No Simplicio login for the service user. Run: {LOGIN_COMMAND}  or run: {COMMAND}"
    else:
        detail = f"No GitHub token in the service environment. Run: {COMMAND}  then: {RESTART_COMMAND}"
    return {"phase": "setup_required", "reason_code": reason, "command": COMMAND, "detail": detail}


# --- input --------------------------------------------------------------------------------------------------------


def is_broad(scope: str) -> bool:
    return scope.startswith("admin:") or scope in _BROAD


def valid_email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not _EMAIL.fullmatch(value):
        raise Refused("the account e-mail is not valid (ASCII address, for example name@example.com)")
    return value


def valid_token(value: str) -> str:
    value = value.strip()
    if not _TOKEN.fullmatch(value):
        raise Refused("the GitHub token has a length or characters that GitHub tokens never have; nothing was stored")
    return value


def _hidden(prompt: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)  # getpass warns BEFORE it falls back to an echoing read
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise Refused("this terminal cannot hide the input; use --github-token-stdin") from None


def collect(email: str | None, token_stdin: bool) -> tuple[str, str]:
    tty = sys.stdin.isatty()
    if not tty and not token_stdin:
        raise Refused("stdin is not a terminal: pass --github-token-stdin and pipe the token, with --email")
    if not tty and email is None:
        raise Refused("--email is required with --github-token-stdin when stdin is not a terminal")
    if email is None:
        email = input("Simplicio account e-mail: ")
    email = valid_email(email)
    if token_stdin and not tty:
        raw = sys.stdin.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise Refused("the token input is too long; nothing was stored")
    else:
        raw = _hidden("GitHub token (input is hidden): ")
    return email, valid_token(raw)


# --- the env file ---------------------------------------------------------------------------------------------------


def check_target(path: Path) -> None:
    if path.is_symlink():
        raise Refused(f"{path} is a symlink; point SIMPLICIO_247_ENV_FILE at the real file")
    if not path.parent.is_dir():
        raise Refused(f"the directory {path.parent} does not exist")
    if not os.access(path.parent, os.W_OK):
        raise Refused(f"cannot write in {path.parent}: run as root, or point SIMPLICIO_247_ENV_FILE at a file you own")
    if path.exists() and not path.is_file():
        raise Refused(f"{path} is not a regular file")
    if env_guard.refusal(path):
        raise Refused(f"{path} is readable by group or others, so the watcher would refuse to start. "
                      f"Fix it, then run setup again: chmod 600 {path}")


def _read_env(path: Path) -> str:
    """The current content ('' when the file is absent). O_NOFOLLOW: a symlink put there after check_target is refused,
    never read through (its target would be copied into the new file)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise Refused(f"{path} became a symlink while setup ran; nothing was stored") from None
        raise
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise Refused(f"{path} is not a regular file")
        return handle.read().decode("utf-8", "surrogateescape")


def store_token(path: Path, token: str) -> None:
    """Set GH_TOKEN in the env file: keep every other line, replace the old GH_TOKEN line in place.

    The new file is a temp file in the same directory, mode 600 BEFORE the content is written, then os.replace.
    """
    lines = _read_env(path).split("\n")
    if lines[-1] == "":
        lines.pop()
    out: list[str] = []
    placed = False
    for line in lines:
        if line.partition("=")[0].strip() != KEY:
            out.append(line)
        elif not placed:
            out.append(f"{KEY}={token}")
            placed = True
    if not placed:
        out.append(f"{KEY}={token}")
    data = ("\n".join(out) + "\n").encode("utf-8", "surrogateescape")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


# --- GitHub -----------------------------------------------------------------------------------------------------------


_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[@-Z\\-_])")


def _plain(text: str, token: str) -> str:
    """Printable ASCII only and without the token, for text that came from gh.

    Escape sequences and control characters are DELETED before the token is redacted: one of them inside the token
    (ANSI colour between its characters, a carriage return) would keep it from matching, and it would be shown.
    """
    text = re.sub(r"[^\x20-\x7e\n\t]", "", _ESCAPE.sub("", text))
    for secret in (token, token[:8], token[-8:]):  # the whole token, then a partial echo of its start or end
        text = text.replace(secret, "***")
    return re.sub(r"\s+", " ", text).strip()[:200]


async def check_token(token: str) -> tuple[str, list[str] | None]:
    """(login, scopes) of the token from a real `gh api -i user`; the token goes to the child's environment only.

    scopes is None when GitHub sends no X-OAuth-Scopes header (a fine-grained token).
    """
    env = {name: os.environ[name] for name in ("PATH", "HOME", "GH_HOST") if name in os.environ}
    env |= {KEY: token, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}
    try:
        result = await proc.run(["gh", "api", "-i", "user"], timeout=30, env=env)
    except FileNotFoundError:
        raise Failed("the gh CLI is not installed or not on PATH") from None
    except TimeoutError:
        raise Failed("GitHub did not answer within 30 seconds") from None
    head, _, body = result.stdout.replace("\r\n", "\n").partition("\n\n")
    code = re.match(r"HTTP/\S+ (\d{3})", head)
    if result.returncode != 0:
        if code:
            raise Failed(f"GitHub did not accept the token (HTTP {code.group(1)})")
        raise Failed("gh api user failed: " + _plain(result.stderr, token))
    try:
        login = str(json.loads(body).get("login") or "")
    except (ValueError, AttributeError):
        login = ""
    if not _LOGIN.fullmatch(login):
        raise Failed("GitHub answered without a valid login")
    for line in head.split("\n")[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "x-oauth-scopes":
            return login, [s for s in (p.strip() for p in value.split(",")) if _SCOPE.fullmatch(s)]
    return login, None


def _report_token(login: str, scopes: list[str] | None) -> None:
    print(f"GitHub token: accepted (login: {login})")
    if scopes is None:
        print("GitHub token scopes: none reported (fine-grained token)")
        return
    print("GitHub token scopes: " + (", ".join(scopes) or "none"))
    for scope in scopes:
        if is_broad(scope):
            print(f"WARN: the scope {scope} is broader than the watcher needs")
    print("A classic token cannot be limited to chosen repositories. Prefer a fine-grained token limited to the "
          "opted-in repositories (Contents, Issues and Pull requests: read and write).")


# --- the Simplicio account ----------------------------------------------------------------------------------------


def _login_state() -> tuple[tuple[int, int] | None, str]:
    """(owner of login.json or None when it is absent, the account e-mail it holds or '')."""
    try:
        info = config.LOGIN.stat()
    except OSError:
        return None, ""
    try:
        found = json.loads(config.LOGIN.read_text())["verification"]["validated"]["user"]["email"]
    except (OSError, ValueError, KeyError, TypeError):
        found = ""
    return (info.st_uid, info.st_gid), found if isinstance(found, str) else ""


async def account_reason(email: str) -> str:
    """Reason code of the existing subscription check, or account_mismatch when login.json is another account."""
    owner, logged_in = await asyncio.to_thread(_login_state)
    if logged_in and logged_in.casefold() != email.casefold():
        return "account_mismatch"
    try:
        return str((await subscription.mcp_subscription()).get("reason"))
    finally:  # a refresh rewrites login.json: as root that would hand the service user's file to root
        if owner is not None and os.geteuid() == 0:
            with contextlib.suppress(OSError):
                os.chown(config.LOGIN, *owner, follow_symlinks=False)


# --- the command ------------------------------------------------------------------------------------------------------


async def _run(email: str, token: str, target: Path) -> int:
    try:
        login, scopes = await check_token(token)
    except Failed as exc:
        print(f"GitHub token: not stored. {exc}")
        return 1
    _report_token(login, scopes)
    try:
        await asyncio.to_thread(store_token, target, token)
    except OSError as exc:
        print(f"cannot write {target} ({exc.strerror}): run as root, or point SIMPLICIO_247_ENV_FILE at a file you own")
        return 2
    print(f"GitHub token: stored in {target} (mode 600)")
    try:
        await state.save(config.ROOT / "account.json", {"email": email, "recorded_at": state.iso(state.now())})
        print(f"Account e-mail: {email} (recorded in {config.ROOT / 'account.json'})")
    except OSError as exc:
        print(f"WARN: the account e-mail was not recorded ({exc.strerror})")
    code = await _account(email)
    print(f"Restart the service to load the token: {RESTART_COMMAND}")
    return code


async def _account(email: str) -> int:
    reason = await account_reason(email)
    print(f"Simplicio subscription: {reason}")
    if reason != "ok":
        print(f"  {_HINTS.get(reason, 'run this command again later')}")
    return 0 if reason == "ok" else 1


def _recorded_email() -> str | None:
    try:
        return valid_email(str(json.loads((config.ROOT / "account.json").read_text())["email"]))
    except (OSError, ValueError, KeyError, TypeError, Refused):
        return None


def check(email: str | None) -> int:
    """--check: only the account step, for after the login. No token is asked, checked or stored."""
    email = valid_email(email) if email is not None else _recorded_email()
    if email is None:
        raise Refused(f"no account e-mail recorded yet: run `{COMMAND}` first, or pass --email")
    return asyncio.run(_account(email))


def main(email: str | None = None, token_stdin: bool = False,
         state_dir: str | None = None, check_only: bool = False) -> int:
    if state_dir:
        config.set_state_dir(state_dir)
    try:
        if check_only:
            return check(email)
        email, token = collect(email, token_stdin)
        target = env_guard.env_file()
        check_target(target)
        return asyncio.run(_run(email, token, target))
    except Refused as exc:
        print(f"setup refused: {exc}")
    except (EOFError, KeyboardInterrupt):
        print("setup cancelled; nothing was stored")
    return 2
