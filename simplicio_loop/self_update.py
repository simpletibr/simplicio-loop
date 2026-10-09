"""`simplicio-loop update`: install the latest GitHub release of simpletibr/simplicio-loop, for every distribution (#1575).

* pip (a wheel): install the release tag with pip, then `install --global` (as before).
* source (git checkout, editable): refused; `git pull` and `bash scripts/dev_install.sh` are the update.
* binary (frozen executable): download the asset `simplicio-loop-v<version>-<os>-<arch>[.exe]` and `SHA256SUMS` of the
  release, check the SHA256 BEFORE anything is touched, swap the file by one atomic rename, keep the old one as
  `<name>.bak`, run the new one with `--version` and put the old one back if it does not answer as the new version.
  A downgrade needs --force. Windows cannot replace a running image: the verified file waits as `<name>.new` and
  `apply_pending` swaps it in at the next start (UNVERIFIED on a real Windows host).

`--check` changes nothing: exit 0 up to date, 10 update available, 2 error. `--dry-run` prints what would happen.
The HTTP layer is a parameter (`http(url)` returns a file-like object), so tests use a fake release and fake assets.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence, Tuple

from . import auth, distribution
from .stack_manifest import installed_legacy_distributions

REPO = "simpletibr/simplicio-loop"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
EXIT_UPDATE_AVAILABLE = 10
SUMS_NAME = "SHA256SUMS"
CHECK_FILE = "update-check.json"
_API = "https://api.github.com/"
_SUMS_LINE = re.compile(r"([0-9A-Fa-f]{64})  (\S.*?)\s*")

Http = Callable[[str], Any]


class Refused(Exception):
    """The update stops before it changes anything (or after it put everything back)."""


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


# --- the binary --------------------------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _download(http: Http, url: str, dest: Path) -> None:
    """Stream `url` into `dest`. The SHA256 is taken afterwards from the file ON DISK, which is what gets installed."""
    with http(url) as response, open(dest, "wb") as out:
        for chunk in iter(lambda: response.read(1 << 20), b""):
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())


@contextlib.contextmanager
def _update_lock(state_dir: Optional[Path]) -> Iterator[None]:
    """One update at a time per user: a second one stops before it downloads anything."""
    lock = auth.file_lock((state_dir or default_state_dir()) / "update", wait_s=0, strict=False)
    try:
        lock.__enter__()
    except auth.LoginError as exc:
        if exc.reason_code == "login_lock_timeout":
            raise Refused("another update is running; wait for it to end, then run `simplicio-loop update` again") from None
        raise Refused(str(exc)) from None
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def _checksum(sums: str, name: str) -> str:
    """The SHA256 that SHA256SUMS (lines `<64 hex>  <file name>`) lists for `name`."""
    found = {m.group(1).lower() for line in sums.splitlines() if (m := _SUMS_LINE.fullmatch(line)) and m.group(2) == name}
    if len(found) != 1:
        raise Refused(f"{SUMS_NAME} has no checksum line for {name}" if not found
                      else f"{SUMS_NAME} lists {name} with different checksums")
    return found.pop()


def _probe_version(exe: Path) -> str:
    done = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60,
                          stdin=subprocess.DEVNULL)
    return done.stdout


def apply_pending(exe: Optional[Path] = None, *, windows: Optional[bool] = None) -> bool:
    """Windows: swap in the verified `<name>.new` that `update` staged. True when the swap happened.

    The staged file is checked against the SHA256 recorded when it was downloaded; a changed file is deleted.
    """
    exe = Path(exe or sys.executable)
    windows = os.name == "nt" if windows is None else windows
    staged, side = exe.with_name(exe.name + ".new"), exe.with_name(exe.name + ".new.sha256")
    if not windows or not staged.is_file():
        return False
    try:
        want = side.read_text(encoding="utf-8").strip()
    except OSError:
        want = ""
    if not want or _sha256(staged) != want:
        _remove(staged)
        _remove(side)
        return False
    backup = exe.with_name(exe.name + ".bak")
    os.replace(exe, backup)  # Windows lets a running image be renamed, not overwritten or deleted
    try:
        os.replace(staged, exe)
    except OSError:
        os.replace(backup, exe)
        raise
    _remove(side)
    return True


def _binary_plan(release: dict, label: str, platform: Optional[tuple]) -> tuple:
    """(asset name, asset url, SHA256SUMS url) of this platform, or Refused."""
    os_name, arch = platform or distribution.platform_key()
    name = distribution.binary_asset_name(label, os_name, arch)
    urls = {str(a.get("name")): str(a.get("browser_download_url") or "") for a in release.get("assets") or []
            if isinstance(a, dict)}
    if not urls.get(name):
        raise Refused(f"release v{label} has no asset {name} for {os_name}-{arch}; nothing was changed")
    if not urls.get(SUMS_NAME):
        raise Refused(f"release v{label} has no {SUMS_NAME} file, so {name} cannot be verified; nothing was changed")
    for url in (urls[name], urls[SUMS_NAME]):
        if not url.startswith("https://"):
            raise Refused(f"release v{label} lists a download that is not https: {url}")
    return name, urls[name], urls[SUMS_NAME]


def _swap(exe: Path, staged: Path, label: str, probe: Callable[[Path], str]) -> None:
    """Atomic replace with a backup; puts the old file back when the new one does not answer as `label`."""
    backup = exe.with_name(exe.name + ".bak")
    _remove(backup)
    try:
        os.link(exe, backup)  # the old inode stays reachable, so the swap below is ONE rename
    except OSError:
        shutil.copy2(exe, backup)
    try:
        os.replace(staged, exe)
    except OSError as exc:
        _remove(backup)
        raise Refused(f"cannot replace {exe}: {exc.strerror or exc}; nothing was changed") from None
    try:
        answer = probe(exe)
    except (OSError, subprocess.SubprocessError) as exc:
        answer = f"<{exc}>"
    if answer.strip().splitlines()[:1] != [f"simplicio-loop {label}"]:
        os.replace(backup, exe)
        raise Refused(f"the new binary did not answer `--version` as simplicio-loop {label} (it said {answer.strip()[:80]!r}); "
                      "the old file is put back")


def _update_binary(*, installed: str, force: bool, check: bool, dry_run: bool, http: Http, exe: Optional[Path],
                   platform: Optional[tuple], windows: Optional[bool], probe: Callable[[Path], str],
                   runner: Callable[[Sequence[str]], int], record: Callable[[dict], None],
                   state_dir: Optional[Path] = None) -> int:
    try:
        with http(LATEST_URL) as response:
            release = json.loads(response.read().decode("utf-8"))
        tag = str(release["tag_name"])
        latest = parse_version(tag)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"update: cannot read the latest release of {REPO}: {exc}")
        return 2 if check else 1
    current = parse_version(installed)
    label = ".".join(map(str, latest))
    available = latest > current
    info = {"installed": installed, "latest": label, "update_available": available, "kind": distribution.BINARY}
    if not dry_run:
        record(info)
    if not available and not force:
        if latest < current and not check:
            print(f"update: the latest release {label} is older than the installed {installed}; "
                  "refusing a downgrade (use --force to install it anyway)")
            return 2
        print(f"simplicio-loop {installed} is up to date (latest release {label})")
        return 0
    print(f"simplicio-loop {installed} -> {label}")
    exe = Path(exe or sys.executable).resolve()
    windows = os.name == "nt" if windows is None else windows
    backup = exe.with_name(exe.name + ".bak")
    try:
        name, asset_url, sums_url = _binary_plan(release, label, platform)
        if check:
            return EXIT_UPDATE_AVAILABLE if available else 0
        with http(sums_url) as response:
            want = _checksum(response.read().decode("utf-8", errors="replace"), name)
        if dry_run:
            print(f"update: dry run, nothing was changed. It would download {name} and check it against {SUMS_NAME}, "
                  f"replace {exe} by one rename, keep the old file as {backup}, run the new file with --version "
                  "and then run `install --global`.")
            return 0
        if not os.access(exe.parent, os.W_OK):
            raise Refused(f"{exe.parent} is not writable; run the update with the rights that installed the binary")
        with _update_lock(state_dir):
            fd, temp = tempfile.mkstemp(dir=exe.parent, prefix=exe.name + ".", suffix=".new")  # a unique name per run
            os.close(fd)
            staged = Path(temp)
            try:
                _download(http, asset_url, staged)
                got = _sha256(staged)
                if got != want:
                    raise Refused(f"checksum mismatch for {name}: {SUMS_NAME} says {want[:12]}..., the file on disk is "
                                  f"{got[:12]}...; nothing was changed")
                print(f"update: SHA256 verified for {name}")
                if os.name != "nt":
                    os.chmod(staged, (stat.S_IMODE(exe.stat().st_mode) if exe.exists() else 0o755) | 0o111)
                if windows:  # a running image cannot be replaced: the next start does it, after checking the digest again
                    waiting = exe.with_name(exe.name + ".new")
                    os.replace(staged, waiting)
                    exe.with_name(exe.name + ".new.sha256").write_text(got + "\n", encoding="utf-8")
                    print(f"update: {waiting.name} is staged and verified; it replaces {exe.name} at the next start")
                    return 0
                _swap(exe, staged, label, probe)
            finally:
                _remove(staged)
    except Refused as exc:
        print(f"update: {exc}")
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"update: failed: {exc}")
        return 2
    record({**info, "installed": label, "update_available": False})
    print(f"update: {exe} is now {label}; the old file is kept as {backup.name}")
    return runner([str(exe), "install", "--global"])  # the NEW binary knows the new skills and host rules


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
    http: Optional[Http] = None,
    exe: Optional[Path] = None,
    platform: Optional[tuple] = None,
    windows: Optional[bool] = None,
    probe: Callable[[Path], str] = _probe_version,
    record: Optional[Callable[[dict], None]] = None,
    state_dir: Optional[Path] = None,
) -> int:
    if installed is None:
        from . import __version__ as installed
    record = record or (lambda info: None)
    kind = kind or distribution.kind()
    if kind == distribution.BINARY:
        return _update_binary(installed=installed, force=force, check=check, dry_run=dry_run, http=http or _open,
                              exe=exe, platform=platform, windows=windows, probe=probe, runner=runner, record=record,
                              state_dir=state_dir)
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
    if latest <= current and not force:
        print(f"simplicio-loop {installed} is up to date (latest release {label})")
        stale = list(installed_legacy_distributions() if legacy is None else legacy)
        if not stale or check or source:
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
        return EXIT_UPDATE_AVAILABLE if available else 0
    if source:
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
    rc = runner([sys.executable, "-m", "simplicio_loop.cli", "install", "--global"])
    if dry_run:
        print("update: dry run, nothing was changed.")
    elif rc == 0:
        record({**info, "installed": label, "update_available": False})
    return rc
