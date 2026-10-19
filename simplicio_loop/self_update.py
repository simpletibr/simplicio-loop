"""`simplicio-loop update`: install the latest GitHub release of simpletibr/simplicio-loop (#1575).

* pip (a wheel): install the release tag with pip, then `install --global` (as before).
* source (git checkout, editable): refused; `git pull` and `bash scripts/dev_install.sh` are the update.

`--check` changes nothing: exit 0 up to date, 10 update available, 2 error. `--dry-run` prints what would happen.
The release lookup is a parameter (`fetch`), so tests use a fake release.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple

from . import distribution
from .stack_manifest import installed_legacy_distributions

REPO = "simpletibr/simplicio-loop"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
EXIT_UPDATE_AVAILABLE = 10
CHECK_FILE = "update-check.json"
_API = "https://api.github.com/"


def is_pep668_environment(
    *,
    prefix: Optional[str] = None,
    base_prefix: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[bool, Optional[str]]:
    """Detect if the Python environment is externally managed per PEP 668.

    Returns (True, details) if externally managed and PEP 668 protection is active,
    or (False, None) otherwise.
    """
    env = os.environ if environ is None else environ
    if env.get("PIP_BREAK_SYSTEM_PACKAGES") == "1":
        return False, None

    pfx = sys.prefix if prefix is None else prefix
    bpfx = getattr(sys, "base_prefix", sys.prefix) if base_prefix is None else base_prefix

    # Inside a virtual environment, sys.prefix != sys.base_prefix
    if pfx != bpfx or (prefix is None and hasattr(sys, "real_prefix")):
        return False, None

    candidate_paths: list[Path] = []
    if prefix is None:
        try:
            stdlib = sysconfig.get_path("stdlib")
            if stdlib:
                candidate_paths.append(Path(stdlib) / "EXTERNALLY-MANAGED")
        except Exception:
            pass

    try:
        candidate_paths.append(
            Path(pfx) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "EXTERNALLY-MANAGED"
        )
    except Exception:
        pass

    for candidate in candidate_paths:
        try:
            if candidate.is_file():
                try:
                    content = candidate.read_text(encoding="utf-8")
                except OSError:
                    content = ""
                return True, content
        except OSError:
            continue

    return False, None


def pep668_diagnostic_message(details: Optional[str] = None) -> str:
    msg = [
        "update: detected externally-managed-environment (PEP 668).",
        "Direct pip execution in this system Python environment is restricted to protect system packages.",
    ]
    if details:
        clean = details.strip()
        if clean:
            msg.append(f"\nSystem manager explanation:\n{clean}\n")
    msg.extend([
        "Recommended remediation options:",
        "  1. Use a virtual environment (recommended):",
        "       python3 -m venv ~/.venvs/simplicio-loop",
        "       source ~/.venvs/simplicio-loop/bin/activate",
        "       pip install -U simplicio-loop",
        "  2. Use uv pip:",
        "       uv tool install simplicio-loop (or: uv pip install --system -U simplicio-loop)",
        "  3. Use pipx:",
        "       pipx install simplicio-loop (or: pipx upgrade simplicio-loop)",
        "  4. If authorized, override PEP 668 protection with --break-system-packages:",
        "       PIP_BREAK_SYSTEM_PACKAGES=1 simplicio-loop update",
    ])
    return "\n".join(msg)


def parse_version(text: str) -> Tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        raise ValueError(f"no version in {text!r}")
    return tuple(int(part) for part in match.groups())


def _request(url: str) -> urllib.request.Request:
    """The GitHub token goes to the API only: a download can redirect to another host, which must never see it."""
    headers = {"User-Agent": "simplicio-loop-update",
               "Accept": "application/vnd.github+json" if url.startswith(_API) else "application/octet-stream"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(_API):
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies every header into a redirected request: this handler removes the GitHub token when the redirect
    leaves the host, and refuses a redirect from https to plain http."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if old.scheme == "https" and new.scheme != "https":
            raise urllib.error.HTTPError(req.full_url, code, "a redirect from https to plain http is refused", headers, fp)
        moved = super().redirect_request(req, fp, code, msg, headers, newurl)
        if moved is not None and old.netloc != new.netloc:
            moved.remove_header("Authorization")
        return moved


_OPENER = urllib.request.build_opener(_SameHostRedirect)


def _open(url: str):
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-https url: {url}")
    return _OPENER.open(_request(url), timeout=60)  # https only, checked above


def fetch_latest_tag() -> str:
    if shutil.which("gh"):
        done = subprocess.run(
            ["gh", "release", "view", "-R", REPO, "--json", "tagName", "-q", ".tagName"],
            capture_output=True, text=True, timeout=30,
        )
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    with _open(LATEST_URL) as response:
        return str(json.load(response)["tag_name"])


def _run(cmd: Sequence[str]) -> int:
    return subprocess.call(list(cmd))


def _dry_runner(cmd: Sequence[str]) -> int:
    print("  would run: " + " ".join(cmd))
    return 0


# --- the last check, for `doctor` to show offline ----------------------------------------------------------------------


def default_state_dir() -> Path:
    home = os.environ.get("SIMPLICIO_HOME") or os.environ.get("HOME") or os.path.expanduser("~")
    return Path(home) / ".simplicio-loop"


def read_check(state_dir: Optional[Path] = None) -> Optional[dict]:
    """The answer of the last `update --check`: installed, latest, update_available, kind, checked_at. None if none."""
    try:
        data = json.loads(((state_dir or default_state_dir()) / CHECK_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_check(info: dict, state_dir: Optional[Path] = None) -> None:
    """Best effort and atomic: a cache that cannot be written never fails an update."""
    directory = state_dir or default_state_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=CHECK_FILE + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({**info, "checked_at": int(time.time())}, handle, sort_keys=True)
        os.replace(tmp, directory / CHECK_FILE)
    except OSError:
        pass


# --- the command -------------------------------------------------------------------------------------------------------


def run_update(
    check: bool = False,
    force: bool = False,
    installed: Optional[str] = None,
    fetch: Callable[[], str] = fetch_latest_tag,
    runner: Callable[[Sequence[str]], int] = _run,
    editable: Optional[bool] = None,
    legacy: Optional[Sequence[str]] = None,
    *,
    dry_run: bool = False,
    kind: Optional[str] = None,
    record: Optional[Callable[[dict], None]] = None,
    externally_managed: Optional[bool] = None,
) -> int:
    if installed is None:
        from . import __version__ as installed
    record = record or (lambda info: None)
    kind = kind or distribution.kind()
    source = editable if editable is not None else kind == distribution.SOURCE
    label_kind = distribution.SOURCE if source else distribution.PIP
    if dry_run:
        runner = _dry_runner
    try:
        tag = fetch()
        latest = parse_version(tag)
    except (OSError, ValueError, KeyError) as exc:
        print(f"update: cannot read the latest release of {REPO}: {exc}")
        return 2 if check else 1
    current = parse_version(installed)
    label = ".".join(map(str, latest))
    available = latest > current
    info = {"installed": installed, "latest": label, "update_available": available, "kind": label_kind}
    if not dry_run:
        record(info)
    is_pep668, pep668_details = (
        (bool(externally_managed), None)
        if externally_managed is not None
        else is_pep668_environment()
    )
    if latest <= current and not force:
        print(f"simplicio-loop {installed} is up to date (latest release {label})")
        stale = list(installed_legacy_distributions() if legacy is None else legacy)
        if not stale or check or source:
            return 0
        if is_pep668:
            print(pep668_diagnostic_message(pep668_details))
            return 2
        # `pip install -U` from 3.43.x leaves the standalone distributions on top of the
        # wheel's files; remove them and restore the wheel's copies of those files.
        print("update: removing standalone " + ", ".join(stale) + " (now bundled in simplicio-loop)")
        rc = runner([sys.executable, "-m", "pip", "uninstall", "-y", *stale])
        if rc != 0:
            return rc
        return runner([sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps",
                       f"simplicio-loop @ git+https://github.com/{REPO}@{tag}"])
    print(f"simplicio-loop {installed} -> {label}")
    if check:
        return EXIT_UPDATE_AVAILABLE if available else 0
    if source:
        print("update: editable checkout install; run `git pull` in the repo, then `bash scripts/dev_install.sh`.")
        return 2
    if is_pep668:
        print(pep668_diagnostic_message(pep668_details))
        return 2
    stale = list(installed_legacy_distributions() if legacy is None else legacy)
    if stale:
        print("update: removing standalone " + ", ".join(stale) + " (now bundled in simplicio-loop)")
        rc = runner([sys.executable, "-m", "pip", "uninstall", "-y", *stale])
        if rc != 0:
            print("update: could not remove the standalone distributions; nothing else was changed.")
            return rc
    spec = f"simplicio-loop @ git+https://github.com/{REPO}@{tag}"
    rc = runner([sys.executable, "-m", "pip", "install", "--upgrade", spec])
    if rc != 0:
        print("update: pip install failed; re-run `simplicio-loop update` once git access to the repo works.")
        return rc
    rc = runner([sys.executable, "-m", "simplicio_loop.cli", "install", "--global"])
    if dry_run:
        print("update: dry run, nothing was changed.")
    elif rc == 0:
        record({**info, "installed": label, "update_available": False})
    return rc
