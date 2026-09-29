"""`simplicio-loop update`: install the latest GitHub release of simpletibr/simplicio-loop."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from importlib import metadata
from typing import Callable, Optional, Sequence, Tuple

from .stack_manifest import installed_legacy_distributions

REPO = "simpletibr/simplicio-loop"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse_version(text: str) -> Tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        raise ValueError(f"no version in {text!r}")
    return tuple(int(part) for part in match.groups())


def fetch_latest_tag() -> str:
    if shutil.which("gh"):
        done = subprocess.run(
            ["gh", "release", "view", "-R", REPO, "--json", "tagName", "-q", ".tagName"],
            capture_output=True, text=True, timeout=30,
        )
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(LATEST_URL, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - fixed https URL
        return str(json.load(response)["tag_name"])


def _editable_install() -> bool:
    try:
        raw = metadata.distribution("simplicio-loop").read_text("direct_url.json")
        return bool(raw and json.loads(raw).get("dir_info", {}).get("editable"))
    except (metadata.PackageNotFoundError, ValueError):
        return False


def _run(cmd: Sequence[str]) -> int:
    return subprocess.call(list(cmd))


def run_update(
    check: bool = False,
    force: bool = False,
    installed: Optional[str] = None,
    fetch: Callable[[], str] = fetch_latest_tag,
    runner: Callable[[Sequence[str]], int] = _run,
    editable: Optional[bool] = None,
    legacy: Optional[Sequence[str]] = None,
) -> int:
    if installed is None:
        from . import __version__ as installed
    try:
        tag = fetch()
        latest = parse_version(tag)
    except (OSError, ValueError, KeyError) as exc:
        print(f"update: cannot read the latest release of {REPO}: {exc}")
        return 1
    current = parse_version(installed)
    label = ".".join(map(str, latest))
    if latest <= current and not force:
        print(f"simplicio-loop {installed} is up to date (latest release {label})")
        stale = list(installed_legacy_distributions() if legacy is None else legacy)
        if not stale or check or (_editable_install() if editable is None else editable):
            return 0
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
        return 0
    if _editable_install() if editable is None else editable:
        print("update: editable checkout install; run `git pull` in the repo, then `bash scripts/dev_install.sh`.")
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
    return runner([sys.executable, "-m", "simplicio_loop.cli", "install", "--global"])
