"""What `simplicio-loop` needs to run, and the safe way to install what is missing (#1588).

`check_all` only looks. `ensure` installs, and only in these ways:

* python: `uv python install` into the user's folder; uv, if missing, comes from its official release;
* gh and uv: the release pinned in `setup_pins.json` goes to ~/.local/bin after its SHA256 matched the pin and the release
  checksums (`release_fetch`); a tool or platform without a pin is not downloaded;
* git and bwrap (system packages): only with `yes`, and only as root or when `sudo -n` works. Otherwise the exact
  command of the package manager is returned and nothing runs. There is no `curl | sh` and no sudo prompt.

Nothing runs through a shell. A tool that is already there is never replaced.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform as platform_module
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import setup_hardening
from .release_fetch import FetchError, default_get, install_binary

MIN_PYTHON = (3, 11)  # `requires-python` of pyproject.toml; a test keeps them equal
MIN_NODE = 18
PY_TARGET = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
NEEDS_ROOT = ("apt", "dnf", "pacman")  # brew and winget run as the user
TIMEOUT_S = 10.0
INSTALL_TIMEOUT_S = 900.0
GH_FIX = ("run `simplicio-loop setup` (it installs the GitHub CLI pinned in this release, with its SHA256 checked), "
          "or install it from https://cli.github.com")

Run = Callable[[Sequence[str], float], tuple[Optional[int], str]]
Which = Callable[[str], Optional[str]]
_UNSET = object()
_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
_PYTHON = re.compile(r"Python (\d+)\.(\d+)\.(\d+)")
_TAG = re.compile(r"v?\d+\.\d+\.\d+")  # gh tags start with v, uv tags do not
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PACKAGES = {
    "apt": {"git": "git", "bwrap": "bubblewrap", "pip": "python3-pip", "venv": "python3-venv"},
    "dnf": {"git": "git", "bwrap": "bubblewrap", "pip": "python3-pip"},
    "pacman": {"git": "git", "bwrap": "bubblewrap", "pip": "python-pip"},
    "brew": {"git": "git"},
    "winget": {"git": "Git.Git"},
}
_UV_TRIPLE = {("linux", "amd64"): "x86_64-unknown-linux-gnu", ("linux", "arm64"): "aarch64-unknown-linux-gnu",
              ("macos", "amd64"): "x86_64-apple-darwin", ("macos", "arm64"): "aarch64-apple-darwin",
              ("windows", "amd64"): "x86_64-pc-windows-msvc", ("windows", "arm64"): "aarch64-pc-windows-msvc"}


@dataclass(frozen=True)
class Check:
    name: str  # python | pip | venv | git | gh | bwrap | uv | node
    status: str  # ok | missing | outdated
    required: bool
    path: Optional[str]
    version: Optional[str]
    minimum: Optional[str]
    fix: str  # the exact command or instruction when not ok
    auto: str  # "" | "user" (installed in the user's folder) | "system" (a package manager)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Action:
    name: str
    result: str  # unchanged | installed | would-install | skipped | failed
    detail: str  # for "skipped": the exact command to run; never a secret
    sha256: Optional[str] = field(default=None, compare=False)  # of the bytes written by an install, taken at that moment

    def as_dict(self) -> dict:
        return {"name": self.name, "result": self.result, "detail": self.detail}


# --- looking --------------------------------------------------------------------------------------------------------


def _execute(argv: Sequence[str], timeout: float, env: dict[str, str]) -> tuple[Optional[int], str]:
    """(exit code, stdout + stderr cut at 4 KiB); the code is None when the command timed out or could not start."""
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                              timeout=timeout, shell=False, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return done.returncode, (done.stdout + done.stderr)[:4096]


def _run(argv: Sequence[str], timeout: float = TIMEOUT_S) -> tuple[Optional[int], str]:
    """A probe: `--version` and the like, with no proxy or certificate setting."""
    return _execute(argv, timeout, setup_hardening.probe_env())


def _run_install(argv: Sequence[str], timeout: float = TIMEOUT_S) -> tuple[Optional[int], str]:
    """An install step: it downloads, so it keeps the proxy and certificate settings."""
    return _execute(argv, timeout, setup_hardening.install_env())


run_command = _run  # what `setup_cli` wraps to check a file again right before it runs
install_command = _run_install  # what `setup_cli` wraps for the installs


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _numbers(text: str) -> Optional[tuple[int, ...]]:
    found = _VERSION.search(text)
    return tuple(int(part) for part in found.groups() if part is not None) if found else None


def _text(numbers: Optional[Sequence[int]]) -> Optional[str]:
    return ".".join(str(n) for n in numbers) if numbers else None


def package_manager(*, which: Optional[Which] = None, platform: Optional[str] = None) -> Optional[str]:
    """"apt", "dnf", "pacman", "brew" or "winget" for this system, else None."""
    which, platform = which or shutil.which, platform or sys.platform
    candidates = (("apt-get", "apt"), ("dnf", "dnf"), ("pacman", "pacman")) if platform.startswith("linux") else (
        (("brew", "brew"),) if platform.startswith("darwin") else ((("winget", "winget"),) if platform.startswith("win") else ()))
    return next((manager for program, manager in candidates if which(program)), None)


def system_command(manager: str, packages: Sequence[str]) -> list[str]:
    """The install argv (no sudo) for logical package names (git, bwrap, pip, venv); [] when the manager has none of them."""
    names = [_PACKAGES[manager][p] for p in packages if p in _PACKAGES.get(manager, {})]
    if not names:
        return []
    return {"apt": ["apt-get", "install", "-y"], "dnf": ["dnf", "install", "-y"],
            "pacman": ["pacman", "-S", "--needed", "--noconfirm"], "brew": ["brew", "install"],
            "winget": ["winget", "install", "-e", "--id"]}[manager] + (names[:1] if manager == "winget" else names)


def _system_fix(manager: Optional[str], packages: Sequence[str]) -> str:
    command = system_command(manager, packages) if manager else []
    if not command:
        return f"install {' and '.join(packages)} with your system package manager"
    return " ".join((["sudo"] if manager in NEEDS_ROOT and not _is_root() else []) + command)


def _python(interpreter: Optional[str], which: Which, run: Run) -> Check:
    def probe(exe: str) -> Optional[tuple[int, ...]]:
        code, text = run([exe, "--version"], TIMEOUT_S)
        found = _PYTHON.search(text) if code == 0 else None
        return tuple(int(part) for part in found.groups()) if found else None

    best: Optional[tuple[tuple[int, ...], str]] = None
    candidates = [exe for exe in dict.fromkeys([interpreter, which("python3"), which("python")]) if exe]
    for stage in range(2):
        for exe in candidates:
            version = probe(exe)
            if version and version[:2] >= MIN_PYTHON:
                return Check("python", "ok", True, exe, _text(version), None, "", "")
            if version and (best is None or version > best[0]):
                best = (version, exe)
        uv = which("uv")
        if stage == 1 or not uv:
            break
        code, text = run([uv, "python", "find", f">={PY_TARGET}"], 30.0)  # a Python uv installed is not on PATH
        candidates = [text.strip().splitlines()[-1]] if code == 0 and text.strip() else []
    fix = f"uv python install {PY_TARGET}"
    if best:
        return Check("python", "outdated", True, best[1], _text(best[0]), PY_TARGET, fix, "user")
    return Check("python", "missing", True, None, None, PY_TARGET, fix, "user")


def _module(name: str, python: Check, run: Run, manager: Optional[str], argv: Sequence[str]) -> Check:
    code, text = run([python.path, *argv], TIMEOUT_S)
    if code == 0:
        return Check(name, "ok", True, python.path, _text(_numbers(text)) if name == "pip" else None, None, "", "")
    return Check(name, "missing", True, None, None, None, _system_fix(manager, [name]), "")


def _tool(name: str, which: Which, run: Run, *, required: bool = True, auto: str = "", fix: str = "") -> Check:
    path = which(name)
    if path is None:
        return Check(name, "missing", required, None, None, None, fix, auto)
    code, text = run([path, "--version"], TIMEOUT_S)
    return Check(name, "ok", required, path, _text(_numbers(text)) if code == 0 else None, None, "", "")


def check_all(environ: Optional[Mapping[str, str]] = None, *, which: Optional[Which] = None, run: Optional[Run] = None,
              platform: Optional[str] = None, interpreter: object = _UNSET, node_for: Sequence[str] = (),
              trusted: Optional[Mapping[str, str]] = None) -> list[Check]:
    """Look at python, pip, venv, git, gh, bwrap (Linux), uv, and node (only when `node_for` names hosts that need it).

    `interpreter` is the Python that runs this program (None in the standalone binary, which has none to offer).
    Tools are looked up on PATH without its unsafe entries (relative, writable by others, `~/.local/bin`): nothing there is run.
    `trusted` maps a tool name to the exact file the setup installed and verified; that file is used even in `~/.local/bin`."""
    env = os.environ if environ is None else environ
    which = which or setup_hardening.safe_which(env, trusted)
    run, platform = run or _run, platform or sys.platform
    if interpreter is _UNSET:
        interpreter = None if getattr(sys, "frozen", False) else sys.executable
    manager = package_manager(which=which, platform=platform)
    python = _python(interpreter, which, run)  # type: ignore[arg-type]
    checks = [python]
    if python.path:  # without a python there is nothing to ask about pip and venv
        checks += [_module("pip", python, run, manager, ["-m", "pip", "--version"]),
                   _module("venv", python, run, manager, ["-c", "import venv, ensurepip"])]
    checks += [_tool("git", which, run, auto="system", fix=_system_fix(manager, ["git"])),
               _tool("gh", which, run, auto="user", fix=GH_FIX)]
    if platform.startswith("linux"):  # the 24/7 watcher refuses to run a subprocess without it
        checks.append(_tool("bwrap", which, run, auto="system", fix=_system_fix(manager, ["bwrap"])))
    checks.append(_tool("uv", which, run, required=python.status != "ok", auto="user",
                        fix="run `simplicio-loop setup` (it installs the uv pinned in this release, with its SHA256 checked), "
                            "or see https://docs.astral.sh/uv/"))
    if node_for:
        fix = f"install Node.js {MIN_NODE} or newer from https://nodejs.org (needed by: {', '.join(node_for)})"
        node = _tool("node", which, run, fix=fix)
        major = _numbers(node.version or "")
        if node.status == "ok" and (major is None or major[0] < MIN_NODE):
            node = Check("node", "outdated", True, node.path, node.version, str(MIN_NODE), fix, "")
        checks.append(node)
    return checks


# --- installing -----------------------------------------------------------------------------------------------------


def _target(platform: str, machine: str) -> Optional[tuple[str, str]]:
    system = "linux" if platform.startswith("linux") else "macos" if platform.startswith("darwin") else \
        "windows" if platform.startswith("win") else ""
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine.lower(), "")
    return (system, arch) if system and arch else None


def _release_files(tool: str, tag: str, system: str, arch: str) -> tuple[str, str, str, str]:
    """(archive name, checksums url, archive url, member) of the official release of gh or uv."""
    exe = ".exe" if system == "windows" else ""
    if tool == "gh":
        version = tag.removeprefix("v")
        stem = f"gh_{version}_{'macOS' if system == 'macos' else system}_{arch}"
        archive = f"{stem}.{'tar.gz' if system == 'linux' else 'zip'}"
        base = f"https://github.com/cli/cli/releases/download/{tag}/"
        return archive, f"{base}gh_{version}_checksums.txt", base + archive, f"{stem}/bin/gh{exe}"
    stem = f"uv-{_UV_TRIPLE[(system, arch)]}"
    archive = f"{stem}.{'zip' if system == 'windows' else 'tar.gz'}"
    base = f"https://github.com/astral-sh/uv/releases/download/{tag}/"
    return archive, f"{base}{archive}.sha256", base + archive, "uv.exe" if system == "windows" else f"{stem}/uv"


@dataclass(frozen=True)
class _Where:
    """Where an installer puts files, on which system, how it downloads, and which releases it may install (None: any latest)."""

    bin_dir: Path
    platform: str
    machine: str
    get: Callable[[str], bytes]
    pins: Optional[Mapping[str, Any]] = None

    def exe(self, tool: str) -> Path:
        return self.bin_dir / (tool + (".exe" if self.platform.startswith("win") else ""))


def _pin(tool: str, pins: Mapping[str, Any], system: str, arch: str) -> Optional[tuple[str, str, str]]:
    """(tag, archive, SHA256) that `pins` approves for this tool and platform; None when there is no usable pin."""
    entry = pins.get(tool)
    if not isinstance(entry, Mapping) or not isinstance(entry.get("assets"), Mapping):
        return None
    asset = entry["assets"].get(f"{system}-{arch}")
    if not isinstance(asset, Mapping):
        return None
    tag, archive, sha = entry.get("tag"), asset.get("archive"), asset.get("sha256")
    if not (isinstance(tag, str) and _TAG.fullmatch(tag) and isinstance(sha, str) and _SHA256.fullmatch(sha)):
        return None
    if archive != _release_files(tool, tag, system, arch)[0]:
        return None
    return tag, archive, sha


def _install_release(tool: str, where: _Where, dry_run: bool) -> Action:
    target = _target(where.platform, where.machine)
    if target is None:
        return Action(tool, "skipped", f"no official {tool} release for {where.platform} {where.machine}; install {tool} yourself")
    dest = where.exe(tool)
    if os.path.lexists(dest):
        return Action(tool, "unchanged", f"{dest} exists but is not verified (this setup did not install it), so it is not used; "
                                         f"remove it to let setup install {tool}")
    pin = None
    if where.pins is not None:
        pin = _pin(tool, where.pins, *target)
        if pin is None:
            return Action(tool, "skipped", f"no pinned {tool} release for {target[0]}-{target[1]} in this version of simplicio-loop; "
                                           f"install {tool} yourself")
    if dry_run:
        return Action(tool, "would-install", f"{dest} from the official {tool} release (SHA256 checked)")
    written: list[str] = []
    try:
        if pin is None:
            repo = "cli/cli" if tool == "gh" else "astral-sh/uv"
            tag = json.loads(where.get(f"https://api.github.com/repos/{repo}/releases/latest")).get("tag_name")
            if not isinstance(tag, str) or not _TAG.fullmatch(tag):
                raise FetchError("bad_response", f"the latest {tool} release has no usable tag")
            archive, sums_url, archive_url, member = _release_files(tool, tag, *target)
            result = install_binary(archive_url=archive_url, archive_name=archive, checksums_url=sums_url, member=member,
                                    dest=dest, get=where.get, on_installed=written.append)
        else:
            tag, archive, sha = pin
            _, sums_url, archive_url, member = _release_files(tool, tag, *target)
            result = install_binary(archive_url=archive_url, archive_name=archive, checksums_url=sums_url, member=member,
                                    dest=dest, get=where.get, on_installed=written.append, expected_sha256=sha)
    except FetchError as exc:
        return Action(tool, "failed", f"{exc.reason_code}: {exc}")
    except (ValueError, AttributeError):
        return Action(tool, "failed", "bad_response: the release answer is not JSON")
    proof = "SHA256 pinned" if pin else "SHA256 checked"
    return Action(tool, result, f"{tag} {dest} ({proof})", written[0] if result == "installed" and written else None)


def _expect(path: str, sha256: str, inner: Run) -> Run:
    """`inner` that refuses to start `path` when its bytes are no longer `sha256`; the refusal looks like a program that did not start."""
    def run(argv: Sequence[str], timeout: float = TIMEOUT_S) -> tuple[Optional[int], str]:
        if argv and str(argv[0]) == path:
            try:
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            except OSError:
                return None, ""
            try:
                with os.fdopen(fd, "rb") as handle:
                    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode) or hashlib.file_digest(handle, "sha256").hexdigest() != sha256:
                        return None, ""
            except OSError:
                return None, ""
        return inner(argv, timeout)
    return run


def _install_python(uv: Optional[Check], where: _Where, run: Run, dry_run: bool) -> list[Action]:
    command = f"uv python install {PY_TARGET}"
    if dry_run:
        return [Action("python", "would-install", f"{command} (in your user folder; uv is installed first if missing)")]
    actions, uv_path = [], uv.path if uv else None
    if uv_path is None:
        actions.append(_install_release("uv", where, dry_run=False))
        if actions[-1].result == "unchanged":  # a file nobody verified: it is not run
            return actions + [Action("python", "skipped", f"uv is not verified, so `{command}` did not run; "
                                     f"remove {where.exe('uv')} and run `simplicio-loop setup`")]
        if actions[-1].result != "installed":
            return actions
        uv_path = str(where.exe("uv"))
        if actions[-1].sha256:
            run = _expect(uv_path, actions[-1].sha256, run)  # the file this run wrote must still be the bytes it wrote
    code, _ = run([uv_path, "python", "install", PY_TARGET], INSTALL_TIMEOUT_S)
    if code != 0:
        return actions + [Action("python", "failed", f"`{command}` did not finish (exit {code})")]
    code, text = run([uv_path, "python", "find", PY_TARGET], 30.0)
    return actions + [Action("python", "installed", text.strip().splitlines()[-1] if code == 0 and text.strip() else command)]


def _install_system(names: Sequence[str], *, yes: bool, dry_run: bool, which: Which, run: Run, platform: str) -> list[Action]:
    manager = package_manager(which=which, platform=platform)
    command = system_command(manager, names) if manager else []
    if not command:
        return [Action(name, "skipped", f"install {name} with your system package manager") for name in names]
    sudo = manager in NEEDS_ROOT and not _is_root()
    shown = " ".join((["sudo"] if sudo else []) + command)
    if not yes:
        return [Action(name, "skipped", shown) for name in names]  # the user runs it, or passes --yes
    if dry_run:
        return [Action(name, "would-install", shown) for name in names]
    argv = command
    if sudo:
        if run(["sudo", "-n", "true"], TIMEOUT_S)[0] != 0:  # sudo would ask for a password: never prompt
            return [Action(name, "skipped", shown) for name in names]
        argv = ["sudo", "-n", *command]
    code, _ = run(argv, INSTALL_TIMEOUT_S)
    return [Action(name, "installed", shown) if code == 0 else Action(name, "failed", f"`{shown}` did not finish (exit {code})")
            for name in names]


def ensure(checks: Sequence[Check], *, yes: bool = False, dry_run: bool = False, environ: Optional[Mapping[str, str]] = None,
           which: Optional[Which] = None, run: Optional[Run] = None, get: Callable[[str], bytes] = default_get,
           bin_dir: Optional[Path] = None, platform: Optional[str] = None, machine: Optional[str] = None,
           pins: Optional[Mapping[str, Any]] = None) -> list[Action]:
    """One Action per required check that is not ok. `dry_run` runs and downloads nothing.

    `pins` (`setup_pins.load()`) limits gh and uv to the pinned releases; None installs the latest one, checked against its checksums."""
    env = os.environ if environ is None else environ
    which = which or setup_hardening.safe_which(env)
    run, platform = run or _run_install, platform or sys.platform
    home = Path(env.get("HOME") or env.get("USERPROFILE") or Path.home())
    where = _Where(bin_dir or home / ".local" / "bin", platform, machine or platform_module.machine(), get, pins)
    todo = [check for check in checks if check.status != "ok" and check.required]
    uv = next((check for check in checks if check.name == "uv"), None)
    actions: list[Action] = []
    for check in todo:
        if check.name == "python":
            actions += _install_python(uv, where, run, dry_run)
        elif check.name == "gh":
            actions.append(_install_release("gh", where, dry_run))
        elif check.name != "uv" and check.auto != "system":
            actions.append(Action(check.name, "skipped", check.fix))
    system = [check.name for check in todo if check.auto == "system"]
    return actions + (_install_system(system, yes=yes, dry_run=dry_run, which=which, run=run, platform=platform) if system else [])
