"""ecosystem.py — keep simplicio-mapper / simplicio-sprint in sync with the
floors declared in pyproject.toml.

simplicio-prompt is forbidden on the hot path and is not a base dependency.
The pyproject pin only gates install-time. This module closes the gap where
an already-installed package is older than the current floor.

API:
  check() -> list[DepStatus]   # compare installed vs floor vs pypi-latest
  ensure_latest(force=False, dry_run=False) -> list[str]
                                # pip install -U everything that drifted
                                # returns list of packages upgraded

Cached: PyPI lookups go through a 24h cache in ~/.simplicio/cache/pypi_versions.json
so we don't hit pypi.org on every invocation.

Controls:
  SIMPLICIO_AUTO_UPGRADE=1      # enable session-start upgrade check
  SIMPLICIO_NO_AUTO_UPGRADE=1   # skip it even when AUTO_UPGRADE is set
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .observability import info, warn

ECOSYSTEM = ("simplicio-mapper", "simplicio-sprint")
PYPI_TTL_SECONDS = 86400  # 24h


@dataclass
class DepStatus:
    name: str
    installed: str | None
    floor: str | None  # the >= pin from pyproject
    latest: str | None  # latest on PyPI
    needs_upgrade: bool  # installed < latest (or installed < floor)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "installed": self.installed,
            "floor": self.floor,
            "latest": self.latest,
            "needs_upgrade": self.needs_upgrade,
            "reason": self.reason,
        }


def _pyproject_path() -> Path | None:
    candidates = [
        Path.cwd() / "pyproject.toml",
        Path(__file__).resolve().parent.parent / "pyproject.toml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _read_floor(name: str) -> str | None:
    p = _pyproject_path()
    if not p:
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    # Match a line like '"simplicio-mapper>=0.26.28,<0.27",'
    m = re.search(rf'["\']?{re.escape(name)}\s*>=\s*([0-9][0-9.a-zA-Z-]*)["\']?', text)
    return m.group(1) if m else None


def _installed_version(name: str) -> str | None:
    try:
        from importlib import metadata

        return metadata.version(name)
    except Exception:
        return None


def _cache_path() -> Path:
    root = os.environ.get("SIMPLICIO_CACHE_DIR")
    if root:
        return Path(root) / "pypi_versions.json"
    return Path.home() / ".simplicio" / "cache" / "pypi_versions.json"


def _read_pypi_cache() -> dict:
    path = _cache_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_pypi_cache(payload: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def _pypi_latest(name: str, timeout: float = 5.0, refresh: bool = False) -> str | None:
    """Return the latest published version on PyPI, with a 24h disk cache.

    refresh=True bypasses the cache and forces a live PyPI lookup (used by
    `doctor --refresh`).
    """
    cache = _read_pypi_cache()
    now = time.time()
    entry = cache.get(name)
    if not refresh and entry and (now - entry.get("ts", 0)) < PYPI_TTL_SECONDS:
        return entry.get("version")
    try:
        req = urllib.request.Request(
            f"https://pypi.org/pypi/{name}/json",
            headers={"User-Agent": "simplicio-cli/ecosystem-check"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        version = data.get("info", {}).get("version")
        if version:
            cache[name] = {"version": version, "ts": now}
            _write_pypi_cache(cache)
            return version
    except Exception:
        # Cache miss with fallback to last known if any
        if entry:
            return entry.get("version")
    return None


def _version_lt(a: str | None, b: str | None) -> bool:
    """PEP-440-lite compare for numeric releases plus dev/a/b/rc prereleases."""
    if a is None or b is None:
        return False

    def parse(v: str) -> tuple[tuple[int, ...], tuple[int, int]]:
        match = re.match(r"^\s*(\d+(?:\.\d+)*)\s*([A-Za-z]+)?\s*(\d+)?\s*$", v)
        if not match:
            raise ValueError(v)
        release = tuple(int(part) for part in match.group(1).split("."))
        stage_raw = (match.group(2) or "").lower()
        stage_num = int(match.group(3) or 0)
        stage_order = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "rc": 3, "c": 3, "": 4}
        return release, (stage_order.get(stage_raw, 4), stage_num)

    try:
        return parse(a) < parse(b)
    except Exception:
        return False


def _pyproject_dep_names() -> list[str]:
    """Parse package names from [project].dependencies and every
    [project.optional-dependencies] group in pyproject.toml.

    Prefers tomllib (3.11+); falls back to a scoped regex on older runtimes so
    the doctor still works on Python 3.10."""
    p = _pyproject_path()
    if not p:
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    reqs: list[str] = []
    try:
        import tomllib  # type: ignore[import-not-found]

        proj = tomllib.loads(text).get("project", {})
        reqs = list(proj.get("dependencies", []) or [])
        for group in (proj.get("optional-dependencies", {}) or {}).values():
            reqs.extend(group or [])
    except Exception:
        reqs = re.findall(r'["\']([A-Za-z0-9._\-\[\]]+\s*[<>=!~][^"\']*)["\']', text)
    out: list[str] = []
    for r in reqs:
        m = re.match(r"\s*([A-Za-z0-9._-]+)", r)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def tracked_packages() -> tuple[str, ...]:
    """The full set the doctor checks for freshness: the simplicio ecosystem
    triplet first, then every declared pyproject dependency (deduped)."""
    names = list(ECOSYSTEM)
    for n in _pyproject_dep_names():
        if n not in names:
            names.append(n)
    return tuple(names)


def check(packages: tuple[str, ...] = ECOSYSTEM, refresh: bool = False) -> list[DepStatus]:
    """Compare installed vs floor vs pypi-latest for each package."""
    out: list[DepStatus] = []
    for name in packages:
        installed = _installed_version(name)
        floor = _read_floor(name)
        latest = _pypi_latest(name, refresh=refresh)
        # needs_upgrade = installed is older than the better of floor / latest
        target = latest or floor
        needs = _version_lt(installed, target)
        reason = ""
        if needs:
            if _version_lt(installed, floor):
                reason = f"installed {installed} < pyproject floor {floor}"
            else:
                reason = f"installed {installed} < latest {latest}"
        out.append(
            DepStatus(
                name=name,
                installed=installed,
                floor=floor,
                latest=latest,
                needs_upgrade=needs,
                reason=reason,
            )
        )
    return out


def ensure_latest(
    force: bool = False, dry_run: bool = False, packages: tuple[str, ...] = ECOSYSTEM
) -> list[str]:
    """Pip-install -U everything that has drifted. Returns names upgraded.

    Honors SIMPLICIO_NO_AUTO_UPGRADE=1 unless force=True.
    Calls pip silently (--quiet); errors get printed to stderr but never raise.
    """
    if not force and os.environ.get("SIMPLICIO_NO_AUTO_UPGRADE", "").strip() in (
        "1",
        "true",
        "True",
        "yes",
    ):
        return []
    drifting = [s for s in check(packages) if s.needs_upgrade]
    if not drifting:
        return []
    targets = [s.name for s in drifting]
    if dry_run:
        return targets
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "-U", *targets]
    try:
        subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as e:
        warn(f"simplicio: ecosystem auto-upgrade failed ({e})")
        return []
    return targets


# --------------------------------------------------------------------------- #
# Session-start hook called from simplicio.cli.main()
# --------------------------------------------------------------------------- #


_SENTINEL_NAME = "simplicio_ecosystem_check_done"


def maybe_run_session_start() -> None:
    """Run once per process. Idempotent + cheap-fail.

    Skips when:
      - SIMPLICIO_NO_AUTO_UPGRADE=1
      - SIMPLICIO_HOOK_GUARD=1  (we're a nested invocation; parent already ran)
      - SIMPLICIO_SKIP_AUTO_INIT=1
      - this process has already run the check
    """
    if hasattr(sys.modules[__name__], _SENTINEL_NAME):
        return
    setattr(sys.modules[__name__], _SENTINEL_NAME, True)

    if os.environ.get("SIMPLICIO_HOOK_GUARD"):
        return
    if os.environ.get("SIMPLICIO_SKIP_AUTO_INIT"):
        return
    if os.environ.get("SIMPLICIO_NO_AUTO_UPGRADE", "").strip() in (
        "1",
        "true",
        "True",
        "yes",
    ):
        return
    if os.environ.get("SIMPLICIO_AUTO_UPGRADE", "").strip().lower() not in {"1", "true", "yes"}:
        return

    upgraded = ensure_latest()
    if upgraded:
        info(
            f"simplicio: auto-upgraded {len(upgraded)} ecosystem package(s): "
            f"{', '.join(upgraded)}. Disable via SIMPLICIO_NO_AUTO_UPGRADE=1."
        )
