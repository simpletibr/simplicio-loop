"""The agent CLIs ("hosts") that `simplicio-loop setup` looks for, from ONE table (#1588).

`HOSTS` uses the host ids of the Simplicio Runtime (`host_registry.rs`, plus `grok` from its adapter list); a test keeps
them equal when the Runtime source is present. The Runtime registry holds ids only, so the executable names, the version
and login commands and the install text live here.

Detection finds the EXACT executable name on PATH and runs its version command. PATH entries that are relative, writable by
others or `~/.local/bin` are skipped (`setup_hardening.path_warnings`): nothing in them is run, not even indirectly. The login state comes only from the
official status command of the host (`claude auth status`, `codex login status`, `opencode auth list`); a host without
one is `UNVERIFIED`. No credential file is opened, and no CLI output is shown: only a version number is kept.

Names marked `exe_verified` were seen on a real install. The others come from the vendors' documents and are UNVERIFIED,
as is every lookup on Windows and macOS (`shutil.which` handles PATHEXT, `.cmd` and `.exe`, but nothing was run there).
"""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from . import exec_planner, setup_hardening
from .watcher247 import sandbox

VERSION = re.compile(r"\d+\.\d+\.\d+")  # no suffix: a suffix could carry text of the output
CREDENTIAL_COUNT = re.compile(r"^\W*(\d+) credentials?\s*$", re.MULTILINE)
VERSION_TIMEOUT_S = 5
DEFAULT_ORDER = ("claude-code", "codex", "grok", "opencode", "antigravity", "gemini")  # then the table order

Run = Callable[[Sequence[str], Mapping[str, str]], tuple[Optional[int], str]]


@dataclass(frozen=True)
class HostSpec:
    id: str
    name: str
    exes: tuple[str, ...] = ()  # exact executable names; () = an editor or extension, nothing to detect
    family: str = ""  # the exec_planner family when the watcher can run it
    version_args: tuple[str, ...] = ("--version",)
    login_args: Optional[tuple[str, ...]] = None  # the official status command; None = login is UNVERIFIED
    login_count: bool = False  # the status prints "N credentials" and N > 0 means logged in (opencode)
    install: str = ""  # official install text; it is shown, never run
    needs_node: bool = False  # a node app: it cannot run without node
    exe_verified: bool = False


@dataclass(frozen=True)
class HostStatus:
    id: str
    name: str
    installed: bool
    path: Optional[str]
    version: Optional[str]
    login: str  # ok | no | UNVERIFIED | n/a (not installed)
    watcher: bool  # the 24/7 watcher can run this host
    install: str
    needs_node: bool
    exe_verified: bool

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Choice:
    host: Optional[str]
    login: str  # ok | UNVERIFIED | ""
    reason: str  # requested | kept | chosen | chosen_unverified | requested_not_installed | no_host_logged_in | no_host_installed


# Host specifications (id, name, exes, family, login_args, install, needs_node, exe_verified)
HOSTS: tuple[HostSpec, ...] = (
    HostSpec("codex", "Codex CLI", ("codex",), "codex", login_args=("login", "status"), install="npm install -g @openai/codex", needs_node=False, exe_verified=True),
    HostSpec("claude-code", "Claude Code", ("claude",), "claude", login_args=("auth", "status"), install="npm install -g @anthropic-ai/claude-code", needs_node=False, exe_verified=True),
    HostSpec("cursor", "Cursor Agent CLI", ("cursor-agent",), "", install="see https://cursor.com/cli", needs_node=False, exe_verified=False),
    HostSpec("gemini", "Gemini CLI", ("gemini",), "gemini", install="npm install -g @google/gemini-cli", needs_node=True, exe_verified=False),
    HostSpec("kiro", "Kiro CLI", ("kiro-cli",), "", install="see https://kiro.dev/cli", needs_node=False, exe_verified=False),
    HostSpec("vscode", "VS Code with GitHub Copilot", (), "", install="", needs_node=False, exe_verified=False),
    HostSpec("antigravity", "Antigravity CLI (agy)", ("agy",), "agy", install="see https://antigravity.google", needs_node=False, exe_verified=True),
    HostSpec("opencode", "OpenCode", ("opencode",), "opencode", login_args=("auth", "list"), login_count=True, install="npm install -g opencode-ai", needs_node=False, exe_verified=True),
    HostSpec("orca-dev", "Orca", (), "", install="", needs_node=False, exe_verified=False),
    HostSpec("hermes", "Hermes Agent", ("hermes",), "", install="see https://github.com/NousResearch/hermes-agent", needs_node=False, exe_verified=True),
    HostSpec("github-copilot", "GitHub Copilot CLI", ("copilot",), "", install="npm install -g @github/copilot", needs_node=True, exe_verified=False),
    HostSpec("mimo-code", "MiMo Code", (), "", install="", needs_node=False, exe_verified=False),
    HostSpec("amp", "Amp", ("amp",), "", install="npm install -g @sourcegraph/amp", needs_node=True, exe_verified=False),
    HostSpec("openclaude", "OpenClaude", ("openclaude",), "", install="npm install -g @gitlawb/openclaude", needs_node=True, exe_verified=False),
    HostSpec("pi", "Pi", ("pi",), "", install="npm install -g @mariozechner/pi-coding-agent", needs_node=True, exe_verified=True),
    HostSpec("oh-my-pi", "oh-my-pi", ("omp",), "", install="see https://github.com/can1357/oh-my-pi", needs_node=False, exe_verified=False),
    HostSpec("devin", "Devin for Terminal", ("devin",), "", install="see https://docs.devin.ai", needs_node=False, exe_verified=False),
    HostSpec("goose", "Goose", ("goose",), "", install="see https://block.github.io/goose", needs_node=False, exe_verified=False),
    HostSpec("auggie", "Auggie", ("auggie",), "", install="npm install -g @augmentcode/auggie", needs_node=True, exe_verified=False),
    HostSpec("autohand", "Autohand Code", ("autohand",), "", install="see https://autohand.ai", needs_node=False, exe_verified=False),
    HostSpec("charm", "Charm Crush", ("crush",), "", install="npm install -g @charmland/crush", needs_node=False, exe_verified=False),
    HostSpec("cline", "Cline CLI", ("cline",), "", install="npm install -g cline", needs_node=True, exe_verified=False),
    HostSpec("codebuff", "Codebuff", ("codebuff",), "", install="npm install -g codebuff", needs_node=True, exe_verified=False),
    HostSpec("command-code", "Command Code", (), "", install="", needs_node=False, exe_verified=False),
    HostSpec("continue", "Continue CLI", ("cn",), "", install="npm install -g @continuedev/cli", needs_node=True, exe_verified=False),
    HostSpec("droid", "Factory Droid", ("droid",), "", install="see https://docs.factory.ai", needs_node=False, exe_verified=False),
    HostSpec("kilocode", "Kilo Code CLI", ("kilocode",), "", install="npm install -g @kilocode/cli", needs_node=True, exe_verified=False),
    HostSpec("kimi", "Kimi Code CLI", ("kimi", "kimi-cli"), "", install="uv tool install --python 3.13 kimi-cli", needs_node=False, exe_verified=False),
    HostSpec("mistral-vibe", "Mistral Vibe", ("vibe",), "", install="uv tool install mistral-vibe", needs_node=False, exe_verified=False),
    HostSpec("qwen-code", "Qwen Code", ("qwen",), "", install="npm install -g @qwen-code/qwen-code", needs_node=True, exe_verified=False),
    HostSpec("rovo-dev", "Atlassian Rovo Dev", ("acli",), "", install="see https://developer.atlassian.com/cloud/acli/", needs_node=False, exe_verified=False),
    HostSpec("grok", "Grok Build", ("grok",), "grok", install="see the Grok Build page at https://x.ai", needs_node=False, exe_verified=True),
)

NO_EXECUTABLE: tuple[str, ...] = tuple(h.id for h in HOSTS if not h.exes)


def _run(argv: Sequence[str], env: Mapping[str, str]) -> tuple[Optional[int], str]:
    """(exit code, stdout + stderr cut at 4 KiB); the code is None on a timeout or when the program cannot start."""
    try:
        done = subprocess.run(list(argv), shell=False, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              errors="replace", timeout=VERSION_TIMEOUT_S, env=dict(env))
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return done.returncode, (done.stdout + done.stderr)[:4096]


def _login(spec: HostSpec, path: str, run: Run, env: Mapping[str, str]) -> str:
    if spec.login_args is None:
        return "UNVERIFIED"
    code, text = run([path, *spec.login_args], env)
    if code is None:
        return "UNVERIFIED"
    if spec.login_count:
        counts = CREDENTIAL_COUNT.findall(text)
        return "ok" if code == 0 and counts and int(counts[-1]) > 0 else "no"
    return "ok" if code == 0 else "no"


def _detect_one(spec: HostSpec, which: Callable[[str], Optional[str]], run: Run, env: Mapping[str, str]) -> HostStatus:
    watcher = spec.family in exec_planner.SUPPORTED_FAMILIES
    fixed = (spec.id, spec.name)
    tail = (watcher, spec.install, spec.needs_node, spec.exe_verified)
    path = next((found for exe in spec.exes if (found := which(exe))), None)
    if path is None:
        return HostStatus(*fixed, False, None, None, "n/a", *tail)
    code, text = run([path, *spec.version_args], env)
    found = VERSION.search(text) if code == 0 else None
    return HostStatus(*fixed, True, path, found.group(0) if found else None, _login(spec, path, run, env), *tail)


def detect(environ: Optional[Mapping[str, str]] = None, *, which: Optional[Callable[[str], Optional[str]]] = None,
           run: Optional[Run] = None) -> list[HostStatus]:
    """One HostStatus per host that has an executable to look for, in table order. Child processes get a scrubbed env
    whose PATH, like the lookup, leaves out the unsafe entries."""
    env = os.environ if environ is None else environ
    which = which or setup_hardening.safe_which(env)
    home = Path(env.get("HOME") or env.get("USERPROFILE") or Path.home())
    child_env = sandbox.scrubbed_env(env, home=home)
    child_env["PATH"] = setup_hardening.exec_path(child_env["PATH"], str(home))
    specs = [spec for spec in HOSTS if spec.exes]
    with ThreadPoolExecutor(max_workers=8) as pool:  # a slow CLI start must not add up: the answer takes the slowest one
        return list(pool.map(lambda spec: _detect_one(spec, which, run or _run, child_env), specs))


def choose_default(statuses: Sequence[HostStatus], *, requested: Optional[str] = None, previous: Optional[str] = None) -> Choice:
    """The default host: the requested one if installed; else an installed host whose login is ok (the previous one stays),
    else one whose login is UNVERIFIED; the order is DEFAULT_ORDER, then the table order."""
    installed = {s.id: s for s in statuses if s.installed}
    if requested is not None:
        found = installed.get(requested)
        if found is None:
            return Choice(None, "", "requested_not_installed")
        return Choice(requested, found.login if found.login in ("ok", "UNVERIFIED") else "", "requested")
    rank = {host: position for position, host in enumerate(DEFAULT_ORDER)}
    for login, reason in (("ok", "chosen"), ("UNVERIFIED", "chosen_unverified")):
        pool = [s.id for s in statuses if s.installed and s.login == login]
        if previous in pool:
            return Choice(previous, login, "kept")
        if pool:
            return Choice(min(pool, key=lambda host: rank.get(host, len(rank))), login, reason)
    return Choice(None, "", "no_host_logged_in" if installed else "no_host_installed")
