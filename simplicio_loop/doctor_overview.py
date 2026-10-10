"""`simplicio-loop doctor` (no subcommand) and `doctor all|login`: the overview (#1575).

Eight checks, each `ok`, `warn` or `fail` with the command that fixes it:

* login          the shared login file: present, expired, entitlement, Runtime version, same file as the Runtime
* update         offline by default (the cached answer of the last `update --check`, with its time); --online asks GitHub
* distribution   pip | source | binary
* runtime        coexistence with the Simplicio Runtime (optional)
* operators      a `simplicio-mapper` / `simplicio-dev-cli` on PATH that is not the bundled one (path_operators)
* disk           free space of the state folders against the floor `squad_capacity` uses
* map-store      size of `<git-common-dir>/simplicio`, `baseline-build-*` older than 1 h, bytes `map gc` frees (#1671)
* setup          `simplicio-loop setup` ran, and its summary shows no open item (tools, GitHub login, default agent CLI)

Exit 0 unless a check is `fail` (a login file that exists but cannot be used safely). Nothing here prints a token.
The older forms (`doctor stack|source|mapper|--storage`) are separate and unchanged.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import __version__, auth, distribution, path_operators, self_update, setup_cli, squad_capacity

SCHEMA = "simplicio.doctor/v1"
SECTIONS = ("login", "update", "distribution", "runtime", "operators", "disk", "map-store", "setup")
_RANK = {"ok": 0, "warn": 1, "fail": 2}
GIB = 1 << 30
MAP_STORE_WARN_BYTES = GIB  # `<git-common-dir>/simplicio` above this is a warning (#1671)


def _row(name: str, status: str, summary: str, fix: Optional[str] = None, detail: Optional[dict] = None) -> dict:
    return {"name": name, "status": status, "summary": summary, "fix": fix, "detail": detail or {}}


def _stamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _login(environ: Optional[dict], now: float) -> dict:
    doc = auth.describe(environ, now)
    runtime = doc["runtime"]
    rt = f"Runtime {runtime['version'] or 'of unknown version'}" if runtime["found"] else "Runtime not installed"
    if not doc["logged_in"]:
        status = "warn" if doc["reason_code"] in {"login_missing", "login_expired"} else "fail"
        detail = f": {doc['detail']}" if doc.get("detail") else ""
        return _row("login", status, f"not logged in ({doc['reason_code']}); file {doc['path']}; {rt}{detail}",
                    doc["fix"], doc)
    ent = doc.get("entitlement") or {}
    tier = f"entitlement {ent.get('tier')} ({ent.get('status')}, cached)" if ent else "entitlement not cached yet"
    expiry = "expired" if doc["access_expired"] else f"expires {_stamp(doc['access_expires_at'])}"
    summary = (f"logged in as {doc['email'] or 'an unknown account'}; access token {expiry}; {tier}; {rt}; "
               f"file {doc['path']}")
    if runtime["found"] and not doc["shared_with_runtime"]:
        return _row("login", "warn", summary + f"; the loop reads a DIFFERENT login file than the Runtime "
                    f"(Runtime uses {doc['runtime_path']}), so they do not share the login",
                    f"unset SIMPLICIO_247_LOGIN, or set SIMPLICIO_AUTH_FILE to the same file for both", doc)
    return _row("login", "ok", summary, None, doc)


def _update(online: bool, installed: str, fetch: Callable[[], str], state_dir: Path, kind: str) -> dict:
    fix = "simplicio-loop update"
    if online:
        try:
            latest = ".".join(map(str, self_update.parse_version(fetch())))
        except (OSError, ValueError, KeyError) as exc:
            return _row("update", "warn", f"could not query the latest release of {self_update.REPO}: {exc}")
        available = self_update.parse_version(latest) > self_update.parse_version(installed)
        self_update.write_check({"installed": installed, "latest": latest, "update_available": available,
                                 "kind": kind}, state_dir)
        detail = {"installed": installed, "latest": latest, "update_available": available, "checked_at": int(time.time())}
        if available:
            return _row("update", "warn", f"update available: {installed} -> {latest} (asked GitHub now)", fix, detail)
        return _row("update", "ok", f"up to date: {installed} (latest release {latest}, asked GitHub now)", None, detail)
    cached = self_update.read_check(state_dir)
    if not cached or not cached.get("latest"):
        return _row("update", "ok", "no cached check yet; run `simplicio-loop update --check` or `simplicio-loop doctor --online`")
    try:
        available = self_update.parse_version(str(cached["latest"])) > self_update.parse_version(installed)
    except ValueError:
        return _row("update", "ok", "the cached check is unreadable; run `simplicio-loop doctor --online`")
    when = _stamp(float(cached.get("checked_at") or 0))
    detail = {**cached, "installed": installed, "update_available": available}
    if available:
        return _row("update", "warn", f"update available: {installed} -> {cached['latest']} "
                    f"(cached check of {when}; `doctor --online` asks GitHub)", fix, detail)
    return _row("update", "ok", f"up to date: {installed} (latest release {cached['latest']}, cached check of {when})",
                None, detail)


def _distribution(kind: str, installed: str) -> dict:
    what = {distribution.PIP: f"pip: the installed wheel {installed}",
            distribution.SOURCE: f"source: a git checkout or an editable install, version {installed}",
            distribution.BINARY: f"binary: {sys.executable}, version {installed}"}[kind]
    return _row("distribution", "ok", what, None, {"kind": kind, "version": installed})


def _runtime(environ: Optional[dict]) -> dict:
    binary = auth.runtime_binary(environ)
    if binary is None:
        return _row("runtime", "ok", "Simplicio Runtime not installed (optional: only `simplicio-loop login` needs it)",
                    None, {"found": False})
    version = auth.runtime_version(binary)
    same = auth.login_path(environ) == auth.runtime_login_path(environ)
    return _row("runtime", "ok", f"Simplicio Runtime {version or '(unknown version)'} at {binary}; "
                + ("it shares the login file with simplicio-loop" if same else "it uses another login file than simplicio-loop"),
                None, {"found": True, "path": str(binary), "version": version, "shared_login": same})


def _operators(kind: str, operators: Callable[..., list]) -> dict:
    try:
        rows = operators(frozen_exe=sys.executable if kind == distribution.BINARY else None)
    except (OSError, ValueError) as exc:
        return _row("operators", "warn", f"could not check the operators on PATH: {exc}")
    stale = [row for row in rows if row["status"] == "stale"]
    if not stale:
        return _row("operators", "ok", "simplicio-mapper and simplicio-dev-cli on PATH match the bundled ones (or are absent)",
                    None, {"stale": [], "checked": [row["name"] for row in rows]})
    summary = "; ".join(f"{row['path']} is not the bundled {row['name']} ({row['reason_code']})" for row in stale)
    return _row("operators", "warn", summary, " ; ".join(dict.fromkeys(row["fix"] for row in stale)),
                {"stale": stale, "checked": [row["name"] for row in rows]})


def _nearest_existing(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _disk(dirs: list, usage: Callable[[Any], Any]) -> dict:
    floor = squad_capacity.DISK_FLOOR_BYTES
    measured, low = [], []
    for directory in dirs:
        where = _nearest_existing(Path(directory))
        try:
            free = int(usage(where).free)
        except OSError as exc:
            return _row("disk", "warn", f"could not measure the free space of {where}: {exc}")
        measured.append({"dir": str(directory), "measured_at": str(where), "free_bytes": free})
        if free < floor:
            low.append(f"{directory}: {free / GIB:.1f} GiB free")
    detail = {"floor_bytes": floor, "dirs": measured}
    if low:
        return _row("disk", "warn", "free space below the floor of " + f"{floor / GIB:.1f} GiB (the floor `squads` capacity uses): "
                    + "; ".join(low), "free disk space, or move the state folders to a larger disk", detail)
    shown = "; ".join(f"{m['dir']}: {m['free_bytes'] / GIB:.1f} GiB free" for m in measured)
    return _row("disk", "ok", f"{shown} (floor {floor / GIB:.1f} GiB)", None, detail)


def _mib(size: int) -> str:
    return f"{size / (1 << 20):.1f} MiB" if size < GIB else f"{size / GIB:.2f} GiB"


def _map_store(repo: Any, limit: int, now: float) -> dict:
    """`<git-common-dir>/simplicio`: its size, the `baseline-build-*` older than an hour and the bytes `map gc` frees (#1671)."""
    from . import map_service_gc as gc
    from .map_service_git import GitDiscoveryError, git_common_dir

    fix = "simplicio-loop map gc"
    try:
        store = git_common_dir(str(repo)) / "simplicio"
    except (GitDiscoveryError, OSError, ValueError, subprocess.SubprocessError):
        return _row("map-store", "ok", f"{repo} is not a git repository: no map store to measure", None, {"store": None})
    if not store.is_dir():
        return _row("map-store", "ok", f"{store}: not created yet (0 B)", None, {"store": str(store), "size_bytes": 0})
    try:
        size = gc.tree_size(store)
        map_dir = store / "map"
        builds = [entry for entry in sorted(map_dir.iterdir())
                  if entry.name.startswith(gc.SCRATCH_PREFIX) and entry.is_dir() and not entry.is_symlink()] \
            if map_dir.is_dir() else []
        old_builds = [entry for entry in builds if now - gc.newest_mtime(entry) > gc.STALE_AFTER_SECONDS]
        freeable = gc.plan_gc(str(repo), now=now).would_free_bytes
    except (GitDiscoveryError, OSError, ValueError, subprocess.SubprocessError) as exc:
        return _row("map-store", "warn", f"could not measure {store}: {exc}", fix)
    detail = {"store": str(store), "size_bytes": size, "limit_bytes": limit,
              "baseline_build_total": len(builds), "baseline_build_older_than_1h": len(old_builds),
              "freeable_bytes": freeable}
    summary = (f"{store}: {_mib(size)}; {len(old_builds)} baseline-build-* older than 1 h; "
               f"{_mib(freeable)} freeable by `map gc` (limit {_mib(limit)})")
    if size > limit:
        return _row("map-store", "warn", summary, fix, detail)
    return _row("map-store", "ok", summary, None, detail)


def _state_dirs(repo: Path, state_dir: Path) -> list:
    from .watcher247 import config as watcher_config

    dirs = [state_dir]
    for extra in (repo / ".simplicio-loop", Path(watcher_config.STATE_DIR)):
        if extra.is_dir():
            dirs.append(extra)
    return dirs


def collect(*, online: bool = False, environ: Optional[dict] = None, now: Optional[float] = None,
            fetch: Optional[Callable[[], str]] = None, operators: Optional[Callable[..., list]] = None,
            usage: Optional[Callable[[Any], Any]] = None, installed: Optional[str] = None, kind: Optional[str] = None,
            repo: Any = ".", state_dir: Optional[Path] = None, only: Optional[str] = None,
            map_store_limit: int = MAP_STORE_WARN_BYTES) -> dict:
    stamp = time.time() if now is None else now
    installed = installed or __version__
    state_dir = state_dir or self_update.default_state_dir()
    wanted = [only] if only else list(SECTIONS)
    kind = kind or (distribution.kind() if set(wanted) & {"update", "distribution", "operators"} else "")
    makers = {
        "login": lambda: _login(environ, stamp),
        "update": lambda: _update(online, installed, fetch or self_update.fetch_latest_tag, state_dir, kind),
        "distribution": lambda: _distribution(kind, installed),
        "runtime": lambda: _runtime(environ),
        "operators": lambda: _operators(kind, operators or path_operators.check),
        "disk": lambda: _disk(_state_dirs(Path(repo), state_dir), usage or shutil.disk_usage),
        "map-store": lambda: _map_store(repo, map_store_limit, stamp),
        "setup": lambda: setup_cli.doctor_row(state_dir),
    }
    checks = [makers[name]() for name in wanted]
    worst = max((check["status"] for check in checks), key=_RANK.__getitem__, default="ok")
    return {"schema": SCHEMA, "status": worst, "version": installed, "checks": checks}


def run(*, as_json: bool = False, online: bool = False, only: Optional[str] = None, **kw: Any) -> int:
    doc = collect(online=online, only=only, **kw)
    if as_json:
        print(json.dumps(doc, ensure_ascii=False, sort_keys=True))
    else:
        print(f"simplicio-loop doctor: {doc['status']}")
        for check in doc["checks"]:
            print(f"  {check['status']:<5} {check['name']:<13} {check['summary']}")
            if check["fix"]:
                print(f"        fix: {check['fix']}")
    return 1 if doc["status"] == "fail" else 0
