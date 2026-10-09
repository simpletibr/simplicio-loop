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
import json
import os
import platform
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


def _bin_dir(environ: Mapping[str, str]) -> Path:
    return Path(environ.get("HOME") or environ.get("USERPROFILE") or Path.home()) / ".local" / "bin"


def _with_dir_on_path(environ: Mapping[str, str], directory: Path) -> dict:
    return {**environ, "PATH": os.pathsep.join([str(directory), environ.get("PATH", "")])}


def _prereq_step(options: Options, environ: Mapping[str, str], seams: Seams, node_for: Sequence[str]) -> tuple[list, list]:
    """(checks after the installs, actions). Installs run only on a real run; --check and --dry-run only plan them."""
    checks = seams.check_all(environ, node_for=node_for)
    actions = seams.ensure(checks, yes=options.yes, dry_run=options.check or options.dry_run, environ=environ)
    if any(a.result == "installed" for a in actions):
        checks = seams.check_all(_with_dir_on_path(environ, _bin_dir(environ)), node_for=node_for)
    return checks, actions


def _github_step(options: Options, environ: Mapping[str, str], seams: Seams,
                 directory: Path) -> tuple[dict, Optional[github_cred.GitHubCredential]]:
    planning = options.check or options.dry_run
    provided = None if options.check else _piped_token(options, seams)
    ask = seams.ask if (seams.isatty() and not planning) else None
    resolution = seams.resolve(environ, state_dir=directory, provided=provided, ask=ask)
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
             statuses: Sequence[Any], stale: bool) -> list[dict]:
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
               f"install one agent CLI (see `{COMMAND} --json`, hosts_detected[].install)")
        items.append({"item": "host", "why": choice.reason, "fix": fix})
    if stale:
        items.append({"item": "summary", "why": f"{SETUP_FILE} is missing or out of date", "fix": COMMAND})
    return items


def _path_hint(checks: Sequence[Any], environ: Mapping[str, str]) -> list:
    """A tool the installer put in ~/.local/bin is invisible when that folder is not on PATH: say so."""
    directory = _bin_dir(environ)
    fixed = []
    for check in checks:
        if check.status != "ok" and check.name in ("gh", "uv") and (directory / check.name).exists():
            hint = f'add {directory} to PATH, for example: export PATH="{directory}:$PATH"'
            check = replace(check, fix=hint)
        fixed.append(check)
    return fixed


def collect(options: Options, environ: Mapping[str, str], seams: Seams, directory: Path) -> tuple[dict, dict]:
    """Run the steps. Returns (summary for the file, the report for the screen and --json)."""
    from . import host_detect
    statuses = seams.detect(environ)
    if options.host and not any(s.installed and s.id == options.host for s in statuses):
        raise Refused(f"--host {options.host} is not installed")
    node_for = [s.id for s in statuses if s.installed and s.needs_node]
    checks, actions = _prereq_step(options, environ, seams, node_for)
    checks = _path_hint(checks, environ)
    github, cred = _github_step(options, environ, seams, directory)
    current = read_summary(directory)
    choice = host_detect.choose_default(statuses, requested=options.host, previous=(current or {}).get("default_host"))
    summary = {
        "schema": SCHEMA,
        "platform": _platform(),
        "prereqs": [{k: v for k, v in c.as_dict().items() if k in ("name", "status", "required", "path", "version", "minimum")}
                    for c in checks],
        "github": {k: v for k, v in github.items() if k != "tried"},
        "hosts": _host_rows(statuses),
        "default_host": choice.host,
        "default_login": choice.login or None,
        "default_family": next((h.family for h in host_detect.HOSTS if h.id == choice.host and h.family), None),  # for the watcher
    }
    stale = current is None or _stable(current) != summary
    report = {**summary, "github": {**github, **({"masked": cred.masked} if cred else {})},
              "hosts_detected": [s.as_dict() for s in statuses], "choice_reason": choice.reason,
              "undetectable_hosts": list(host_detect.NO_EXECUTABLE),
              "actions": [a.as_dict() for a in actions], "checks": [c.as_dict() for c in checks],
              "pending": _pending(checks, github, choice, statuses, stale and options.check)}
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
