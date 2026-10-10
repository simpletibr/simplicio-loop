"""`simplicio-loop setup` (#1588): the first-run check that follows `install`.

One command, safe to run again (a second run says `unchanged`):

1. prerequisites: python, pip, venv, git, gh, bwrap, uv (node only when an installed host needs it);
2. agent CLIs: which of the hosts in `host_detect.HOSTS` are installed, their version, login, watcher support;
3. GitHub: reuse GH_TOKEN, the logged-in `gh`, the git credential helper or a stored token; else ask (hidden input);
4. install what is missing when that is safe (`prereqs.ensure`: user-folder installs with SHA256; system packages only
   with --yes and root or `sudo -n`);
5. write `~/.simplicio-loop/setup.json` (mode 600, no token, no e-mail) that `doctor` and the watcher read.

Exit codes: 0 nothing pending, 10 something is pending (`--check` exits 10 when a run would change something),
2 refused (bad input or unsafe file; nothing was changed). Without a terminal the command never waits for input.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import shlex
import stat
import sys
import time
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, TextIO

from . import auth, setup_hardening

if TYPE_CHECKING:  # the steps import httpx; they load only when the command runs, so every other command starts fast
    from . import github_cred, host_detect

SCHEMA = "simplicio.setup/v1"
SETUP_FILE = "setup.json"
PENDING = 10
MAX_TOKEN_INPUT = 1024
MAX_SUMMARY_BYTES = 256 * 1024
COMMAND = "simplicio-loop setup"
INSTALLED_TOOLS = ("gh", "uv")  # what `prereqs.ensure` puts in ~/.local/bin; the only files PATH hygiene lets run from there
QUIET = "The GitHub token is never an argument: pipe it to --github-token-stdin, or run `setup` in a terminal for a hidden prompt."


class Refused(Exception):
    """Bad input or an unsafe file: nothing was changed."""


@dataclass(frozen=True)
class Options:
    check: bool = False
    dry_run: bool = False
    json_out: bool = False
    yes: bool = False
    token_stdin: bool = False
    host: Optional[str] = None


def _hidden(prompt: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)  # getpass warns BEFORE it falls back to an echoing read
        try:
            return getpass.getpass(prompt).strip()
        except getpass.GetPassWarning:
            raise Refused("this terminal cannot hide the input; pipe the token to --github-token-stdin") from None


def _terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


@dataclass(frozen=True)
class Seams:
    """The collaborators of the flow; tests replace them, the command uses the real ones."""

    detect: Callable[..., list]
    check_all: Callable[..., list]
    ensure: Callable[..., list]
    resolve: Callable[..., github_cred.Resolution]
    save_token: Callable[..., Path]
    load_token: Callable[..., Optional[str]]
    isatty: Callable[[], bool]
    ask: Callable[[], str]
    read_stdin: Callable[[int], str]


def real_seams() -> Seams:
    from . import github_cred, host_detect, prereqs
    return Seams(detect=host_detect.detect, check_all=prereqs.check_all, ensure=prereqs.ensure, resolve=github_cred.resolve,
                 save_token=github_cred.save_token, load_token=github_cred.load_token, isatty=_terminal,
                 ask=lambda: _hidden("GitHub token (input is hidden, Enter to skip): "), read_stdin=lambda size: sys.stdin.read(size))


# --- the summary file ---------------------------------------------------------------------------------------------


def summary_path(directory: Optional[Path] = None) -> Path:
    from .self_update import default_state_dir
    return (directory or default_state_dir()) / SETUP_FILE


def read_summary(directory: Optional[Path] = None) -> Optional[dict]:
    """The setup summary for `doctor` and the watcher; None when absent, too big, or not a `simplicio.setup/v1` object."""
    try:
        path = summary_path(directory)
        data = json.loads(setup_hardening.read_private_text(path, MAX_SUMMARY_BYTES))
    except (OSError, ValueError, setup_hardening.UnsafeFileError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else None


def default_family(environ: Mapping[str, str]) -> Optional[str]:
    """The exec family of the default host the setup chose (claude, codex, ...), for the watcher; None when there is none."""
    home = environ.get("SIMPLICIO_HOME") or environ.get("HOME") or environ.get("USERPROFILE")
    family = (read_summary(Path(home) / ".simplicio-loop") if home else None) or {}
    family = family.get("default_family")
    return family if isinstance(family, str) and family else None


def doctor_row(directory: Optional[Path] = None) -> dict:
    """The `setup` check of `doctor`: status ok|warn, a one-line summary, the fix. No secret is in the summary file."""
    summary = read_summary(directory)
    if summary is None:
        return {"name": "setup", "status": "warn", "summary": "setup has not run on this machine yet", "fix": COMMAND, "detail": {}}
    github, host = summary.get("github") or {}, summary.get("default_host")
    problems = [f"{p.get('name')} {p.get('status')}" for p in summary.get("prereqs") or [] if p.get("required") and p.get("status") != "ok"]
    if github.get("status") != "ok":
        problems.append(f"GitHub {github.get('status', 'unknown')}")
    elif github.get("missing_scopes"):
        problems.append("GitHub token lacks " + ", ".join(github["missing_scopes"]))
    if not host:
        problems.append("no default agent CLI")
    ok = f"GitHub {github.get('login')} (via {github.get('source')}); default agent CLI {host}; setup of {summary.get('updated_at')}"
    return {"name": "setup", "status": "warn" if problems else "ok", "fix": COMMAND if problems else None,
            "summary": "; ".join(problems) if problems else ok, "detail": {"default_host": host, "github": github.get("status")}}


def _stable(doc: Mapping[str, Any]) -> dict:
    return {key: value for key, value in doc.items() if key != "updated_at"}


def _write_summary(doc: dict, directory: Path) -> bool:
    """Write the summary when it differs from the file (the time of the run does not count). True = written."""
    path = summary_path(directory)
    current = read_summary(directory)
    if current is not None and _stable(current) == _stable(doc):
        return False
    stamped = {**doc, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        auth.write_login(stamped, path)  # atomic, mode 600 before the content, refuses a symlink or a loose folder
    except auth.LoginError as exc:
        raise Refused(f"cannot write {path} safely ({exc.reason_code}); fix the folder or file, then run `{COMMAND}`") from None
    return True


# --- input --------------------------------------------------------------------------------------------------------


def _piped_token(options: Options, seams: Seams) -> Optional[str]:
    if not options.token_stdin:
        return None
    if seams.isatty():
        raise Refused("--github-token-stdin reads a pipe; in a terminal run the command without it and type the token hidden")
    raw = seams.read_stdin(MAX_TOKEN_INPUT + 1)
    if len(raw) > MAX_TOKEN_INPUT:
        raise Refused("the token input is too long; nothing was stored")
    return raw.strip()


# --- the steps ----------------------------------------------------------------------------------------------------


def _platform() -> dict:
    system = platform.system().lower()
    return {"system": system, "machine": platform.machine().lower(), "os_verified": system == "linux"}


def _home(environ: Mapping[str, str]) -> str:
    return environ.get("HOME") or environ.get("USERPROFILE") or str(Path.home())


def _bin_dir(environ: Mapping[str, str]) -> Path:
    return Path(_home(environ)) / ".local" / "bin"


def _exe(name: str) -> str:
    return name + (".exe" if sys.platform.startswith("win") else "")


def _digest(path: Path) -> Optional[str]:
    """SHA256 of a regular file that is not a symlink (opened with O_NOFOLLOW); None when there is no such file."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    sha = hashlib.sha256()
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        while chunk := os.read(fd, 1 << 20):
            sha.update(chunk)
    except OSError:
        return None
    finally:
        os.close(fd)
    return sha.hexdigest()


def _private_dir(path: Path) -> bool:
    """The folder is not writable by others and belongs to root or the current user: nothing in it can be swapped from outside."""
    if os.name == "nt":
        return True
    try:
        info = os.stat(path)
    except OSError:
        return False
    return not info.st_mode & stat.S_IWOTH and info.st_uid in (0, os.geteuid())


def _vouched_installs(summary: Optional[Mapping[str, Any]], bin_dir: Path) -> dict[str, str]:
    """Tools an earlier setup installed in `bin_dir` whose bytes still match the SHA256 it recorded: name -> that SHA256."""
    records = (summary or {}).get("installs")
    vouched: dict[str, str] = {}
    for name in INSTALLED_TOOLS if _private_dir(bin_dir) else ():
        recorded = records.get(name) if isinstance(records, dict) else None
        if isinstance(recorded, str) and _digest(bin_dir / _exe(name)) == recorded:
            vouched[name] = recorded
    return vouched


def _paths(environ: Mapping[str, str], vouched: Mapping[str, str]) -> dict[str, str]:
    """name -> exact file, for the tools in `vouched`."""
    return {name: str(_bin_dir(environ) / _exe(name)) for name in vouched}


def _pinned(environ: Mapping[str, str], vouched: Mapping[str, str], inner: Callable[..., Any]) -> Callable[..., Any]:
    """`inner` (the function that starts a program: argv first) that refuses a vouched file whose bytes changed.

    The SHA256 is read again right before the program starts, so a swap after the approval cannot run; the refusal looks
    like a program that did not start. What remains is the time between this read and the exec itself."""
    pins = {str(path): vouched[name] for name, path in _paths(environ, vouched).items()}

    def run(argv: Sequence[str], *args: Any, **kwargs: Any) -> Any:
        want = pins.get(str(argv[0])) if argv else None
        if want is not None and _digest(Path(argv[0])) != want:
            return None, ""
        return inner(argv, *args, **kwargs)

    return run


def _prereq_step(options: Options, environ: Mapping[str, str], seams: Seams, node_for: Sequence[str],
                 vouched: Mapping[str, str]) -> tuple[list, list, dict[str, str]]:
    """(checks after the installs, actions, tools vouched for: name -> SHA256). Installs run only on a real run.

    PATH hygiene keeps ~/.local/bin out of the search, so a tool installed in this run is vouched for by its exact path.
    Its SHA256 is the one `ensure` took when it wrote the file. The file must still match it now, and a tool installed
    without such a hash is not vouched for. A hash taken here, after the rest of `ensure`, would approve a swapped file."""
    from . import prereqs
    checks = seams.check_all(environ, node_for=node_for, trusted=_paths(environ, vouched),
                             run=_pinned(environ, vouched, prereqs.run_command))
    actions = seams.ensure(checks, yes=options.yes, dry_run=options.check or options.dry_run, environ=environ)
    bin_dir = _bin_dir(environ)
    fresh = {a.name: a.sha256 for a in actions if a.result == "installed" and a.name in INSTALLED_TOOLS and a.sha256
             and _private_dir(bin_dir) and _digest(bin_dir / _exe(a.name)) == a.sha256}
    if fresh:
        vouched = {**vouched, **fresh}
        checks = seams.check_all(environ, node_for=node_for, trusted=_paths(environ, vouched),
                                 run=_pinned(environ, vouched, prereqs.run_command))
    return checks, actions, dict(vouched)


def _github_step(options: Options, environ: Mapping[str, str], seams: Seams, directory: Path,
                 vouched: Mapping[str, str]) -> tuple[dict, Optional[github_cred.GitHubCredential]]:
    from . import github_cred
    planning = options.check or options.dry_run
    provided = None if options.check else _piped_token(options, seams)
    ask = seams.ask if (seams.isatty() and not planning) else None
    resolution = seams.resolve(environ, state_dir=directory, provided=provided, ask=ask, trusted=_paths(environ, vouched),
                               run=_pinned(environ, vouched, github_cred.run_command))
    cred = resolution.credential
    if cred is None:
        outcomes = {outcome for _, outcome in resolution.tried}
        status = "unverified" if "unreachable" in outcomes else "rejected" if "rejected" in outcomes else "missing"
        return {"status": status, "tried": [{"source": s, "outcome": o} for s, o in resolution.tried]}, None
    source = cred.source
    if source in ("provided", "prompt"):
        source = "stored"  # the next run finds it there, so the summary reads the same
        if not planning and seams.load_token(directory) != cred.token:
            seams.save_token(directory, cred.token, cred.login)
    scopes = None if cred.scopes is None else list(cred.scopes)
    return {"status": "ok", "source": source, "login": cred.login, "scopes": scopes,
            "missing_scopes": list(cred.missing_scopes)}, cred


def _host_rows(statuses: Sequence[Any]) -> list[dict]:
    return [{"id": s.id, "path": s.path, "version": s.version, "login": s.login, "watcher": s.watcher}
            for s in statuses if s.installed]


def _pending(checks: Sequence[Any], github: Mapping[str, Any], choice: host_detect.Choice,
             statuses: Sequence[Any], stale: bool, ignored: Sequence[Mapping[str, str]] = ()) -> list[dict]:
    items = [{"item": c.name, "why": c.status, "fix": c.fix} for c in checks if c.required and c.status != "ok"]
    if github["status"] != "ok":
        why = {"unverified": "GitHub did not answer; the credential could not be checked",
               "rejected": "GitHub rejected the token"}
        fix = (f"run `{COMMAND}` again" if github["status"] == "unverified" else
               f"run `{COMMAND}` in a terminal and type a token, or pipe it: ... | {COMMAND} --github-token-stdin")
        items.append({"item": "github", "why": why.get(github["status"], "no GitHub credential found"), "fix": fix})
    elif github["missing_scopes"]:
        items.append({"item": "github-scopes", "why": "the token lacks: " + ", ".join(github["missing_scopes"]),
                      "fix": f"create a token with the repo and workflow scopes, then run {COMMAND}"})
    if choice.host is None:
        installed = any(s.installed for s in statuses)
        fix = ("log in to one installed agent CLI with its own login command" if installed else
               f"{ignored[0]['host']} is in an ignored PATH entry: see Agent CLIs above" if ignored else
               f"install one agent CLI (see `{COMMAND} --json`, hosts_detected[].install)")
        items.append({"item": "host", "why": choice.reason, "fix": fix})
    if stale:
        items.append({"item": "summary", "why": f"{SETUP_FILE} is missing or out of date", "fix": COMMAND})
    return items


def _path_hint(checks: Sequence[Any], environ: Mapping[str, str], vouched: Mapping[str, str]) -> list:
    """gh or uv sits in ~/.local/bin but the setup cannot vouch for it: it is never run, so say what to do."""
    directory = _bin_dir(environ)
    fixed = []
    for check in checks:
        file = directory / _exe(check.name)
        if check.status != "ok" and check.name in INSTALLED_TOOLS and check.name not in vouched and file.exists():
            if _private_dir(directory):
                fix = f"remove {file} (the setup did not install it, so it is not run), then run `{COMMAND}`"
            else:
                fix = f"make {directory} writable only by you (chmod go-w {directory}), then run `{COMMAND}`"
            check = replace(check, fix=fix)
        fixed.append(check)
    return fixed


def _loose_parent(path: str) -> Optional[str]:
    """The first folder above `path` (or above where its links lead) that anyone can rewrite: it has `o+w` and no sticky bit."""
    folder = os.path.dirname(path)
    real = os.path.realpath(folder)
    for start in (os.path.normpath(folder), real):
        holder = start
        while (parent := os.path.dirname(holder)) != holder:
            holder = parent
            try:
                info = os.lstat(holder)
            except OSError:
                break
            if stat.S_ISDIR(info.st_mode) and info.st_mode & stat.S_IWOTH and not info.st_mode & stat.S_ISVTX and holder != real:
                return holder
    return None


def _ignored_fix(path: str, reason: str) -> str:
    """What to do about a program in a PATH entry that is not searched. Every path is quoted for a shell.

    `chmod go-w` only helps when you own the folder and it is the folder itself that others can write."""
    folder = os.path.dirname(path) or "."
    install = f"`sudo install -m 755 {shlex.quote(path)} {shlex.quote('/usr/local/bin/' + os.path.basename(path))}`"
    if reason == "user_local_bin":
        return f"install it where only root writes, for example {install}"
    if reason == "relative":
        return "use only absolute folders in PATH"
    if reason == "foreign_owner":
        return f"its folder belongs to another user, so you cannot make it private. Install it where only root writes, for example {install}"
    if reason == "writable_parent":
        parent = _loose_parent(path)
        if parent is not None:
            return (f"a folder above it can be rewritten by anyone: remove that write permission (`chmod o-w {shlex.quote(parent)}`), "
                    f"or install it where only root writes, for example {install}")
        return f"a folder above it can be rewritten by anyone. Install it where only root writes, for example {install}"
    return f"make its folder private (`chmod go-w {shlex.quote(folder)}`), or move the program to /usr/local/bin"


def _ignored_line(row: Mapping[str, str]) -> str:
    return (f"{row['host']}: {row['path']} is in an ignored PATH entry ({row['reason']}) and is not run. "
            f"Fix: {_ignored_fix(row['path'], row['reason'])}")


def _ignored_hosts(statuses: Sequence[Any], environ: Mapping[str, str]) -> list[dict]:
    """Agent CLIs that are not installed as far as setup can tell but have a program in a PATH entry it does not search."""
    from . import host_detect
    wanted = {s.id for s in statuses if not s.installed}
    exes = {exe: spec.id for spec in host_detect.HOSTS if spec.id in wanted for exe in spec.exes}
    found = setup_hardening.find_ignored(environ, list(exes))
    rows: dict[str, dict] = {}
    for exe, (path, reason) in found.items():
        rows.setdefault(exes[exe], {"host": exes[exe], "path": path, "reason": reason})
    return list(rows.values())


def collect(options: Options, environ: Mapping[str, str], seams: Seams, directory: Path) -> tuple[dict, dict]:
    """Run the steps. Returns (summary for the file, the report for the screen and --json)."""
    from . import host_detect
    statuses = seams.detect(environ)
    if options.host and not any(s.installed and s.id == options.host for s in statuses):
        hint = next((_ignored_line(row) for row in _ignored_hosts(statuses, environ) if row["host"] == options.host), "")
        raise Refused(f"--host {options.host} is not installed" + (f". {hint}" if hint else ""))
    node_for = [s.id for s in statuses if s.installed and s.needs_node]
    current = read_summary(directory)
    checks, actions, vouched = _prereq_step(options, environ, seams, node_for, _vouched_installs(current, _bin_dir(environ)))
    checks = _path_hint(checks, environ, vouched)
    github, cred = _github_step(options, environ, seams, directory, vouched)
    ignored = _ignored_hosts(statuses, environ)
    choice = host_detect.choose_default(statuses, requested=options.host, previous=(current or {}).get("default_host"))
    summary = {
        "schema": SCHEMA,
        "platform": _platform(),
        "prereqs": [{k: v for k, v in c.as_dict().items() if k in ("name", "status", "required", "path", "version", "minimum")}
                    for c in checks],
        "github": {k: v for k, v in github.items() if k != "tried"},
        "hosts": _host_rows(statuses),
        "installs": dict(vouched),  # SHA256 of what setup installed, taken when it was verified
        "default_host": choice.host,
        "default_login": choice.login or None,
        "default_family": next((h.family for h in host_detect.HOSTS if h.id == choice.host and h.family), None),  # for the watcher
    }
    stale = current is None or _stable(current) != summary
    report = {**summary, "github": {**github, **({"masked": cred.masked} if cred else {})},
              "hosts_detected": [s.as_dict() for s in statuses], "choice_reason": choice.reason,
              "undetectable_hosts": list(host_detect.NO_EXECUTABLE), "ignored_hosts": ignored,
              "path_warnings": [{"entry": entry, "reason": reason} for entry, reason in
                                setup_hardening.path_warnings(environ.get("PATH", os.defpath), _home(environ))],
              "actions": [a.as_dict() for a in actions], "checks": [c.as_dict() for c in checks],
              "pending": _pending(checks, github, choice, statuses, stale and options.check, ignored)}
    return summary, report


# --- output -------------------------------------------------------------------------------------------------------


def render(report: Mapping[str, Any], summary_state: str) -> str:
    lines = [f"simplicio-loop setup ({report['platform']['system']} {report['platform']['machine']})"]
    if not report["platform"]["os_verified"]:
        lines.append("  note: only Linux is tested; results on this system are UNVERIFIED")
    lines += ["", "Prerequisites"]
    for c in report["checks"]:
        shown = " ".join(x for x in (c["version"] or "", c["path"] or "") if x)
        lines.append(f"  {c['name']:<7} {c['status']:<9} {shown}".rstrip())
    if report["path_warnings"]:
        lines += ["", "PATH entries that are not searched (nothing in them is run)"]
        lines += [f"  {w['entry'] or '(empty)'}  ({w['reason']})" for w in report["path_warnings"]]
    lines += ["", "Agent CLIs"]
    installed = [h for h in report["hosts_detected"] if h["installed"]]
    for h in installed:
        lines.append(f"  {h['id']:<14} {h['version'] or 'version UNVERIFIED':<22} login {h['login']:<10}"
                     f" watcher {'yes' if h['watcher'] else 'no'}  {h['path']}")
    if not installed:
        lines.append("  none found")
    missing = [h["id"] for h in report["hosts_detected"] if not h["installed"]]
    if missing:
        lines.append("  not installed: " + ", ".join(missing))
    lines += [f"  {_ignored_line(row)}" for row in report["ignored_hosts"]]
    lines.append("  no executable to detect (editor or extension): " + ", ".join(report["undetectable_hosts"]))
    github = report["github"]
    lines += ["", "GitHub"]
    if github["status"] == "ok":
        scopes = "unknown (fine-grained token)" if github["scopes"] is None else ", ".join(github["scopes"]) or "none"
        lines.append(f"  login {github['login']}  source {github['source']}  token {github['masked']}  scopes {scopes}")
    else:
        lines.append(f"  {github['status']}")
    lines += ["", f"Default host: {report['default_host'] or 'none'}"]
    for action in report["actions"]:
        lines.append(f"  {action['name']}: {action['result']} {action['detail']}".rstrip())
    lines.append(f"{SETUP_FILE}: {summary_state}")
    if report["pending"]:
        lines += ["", "Pending"]
        lines += [f"  {p['item']}: {p['why']}. Fix: {p['fix']}" for p in report["pending"]]
    return "\n".join(lines)


# --- the command --------------------------------------------------------------------------------------------------


def run(options: Options, *, environ: Optional[Mapping[str, str]] = None, seams: Optional[Seams] = None,
        out: Optional[TextIO] = None) -> int:
    from . import github_cred
    from .self_update import default_state_dir
    environ = os.environ if environ is None else environ
    seams = seams or real_seams()
    out = out or sys.stdout
    directory = default_state_dir()
    planning = options.check or options.dry_run
    try:
        summary, report = collect(options, environ, seams, directory)
        written = False if planning else _write_summary(summary, directory)
    except (Refused, github_cred.CredError) as exc:
        print(f"setup refused: {exc}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("setup cancelled; nothing was stored", file=sys.stderr)
        return 2
    state = "not written" if planning else "updated" if written else "unchanged"
    if options.json_out:
        print(json.dumps({**report, "summary_file": state}, indent=2, sort_keys=True), file=out)
    else:
        print(render(report, state), file=out)
    return PENDING if report["pending"] else 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--check", action="store_true",
                        help="change nothing and ask nothing; exit 0 when nothing is pending, 10 when something is")
    parser.add_argument("--dry-run", action="store_true", help="show what would be installed or written; change nothing")
    parser.add_argument("--json", dest="json_out", action="store_true", help="print one JSON document (no token)")
    parser.add_argument("--yes", action="store_true",
                        help="also install system packages (git, bwrap) when you are root or `sudo -n` works")
    parser.add_argument("--github-token-stdin", dest="token_stdin", action="store_true",
                        help="read the GitHub token from a pipe (never as an argument)")
    parser.add_argument("--host", default=None, help="make this installed agent CLI the default host (a host id, for example codex)")


def configure(sub: Any) -> None:
    """Add `setup` to the subparsers of the main parser."""
    parser = sub.add_parser("setup", quiet=QUIET, help="check the machine, find agent CLIs and the GitHub login (run it after install)")
    add_arguments(parser)


def main(args: argparse.Namespace) -> int:
    return run(Options(check=args.check, dry_run=args.dry_run, json_out=args.json_out, yes=args.yes,
                       token_stdin=args.token_stdin, host=args.host))


def after_install(*, interactive: Optional[bool] = None, out: Optional[TextIO] = None) -> None:
    """The last lines of `install`: start the setup in a terminal, else say how to run it. Never fails the install.

    Once a summary exists the setup has run, so a later install or update stays quiet (`doctor` shows the state)."""
    out = out or sys.stdout
    if read_summary() is not None:
        return
    if _terminal() if interactive is None else interactive:
        print("\nNext: setup (prerequisites, agent CLIs, GitHub).\n", file=out)
        run(Options(), out=out)
    else:
        print(f"\nNext: run `{COMMAND}` (prerequisites, agent CLIs, GitHub login).", file=out)
