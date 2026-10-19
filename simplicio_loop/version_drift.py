"""Version drift between the running simplicio-loop and its source checkout (issue #1812, observation 1).

``preflight`` and ``doctor`` compare the running version with two things from the source checkout:
the ``version`` in its ``pyproject.toml`` and its latest ``v*`` git tag. When the running version is
older than either, one line names both versions and the fix command. The checkout is found from, in
order: ``SIMPLICIO_LOOP_SOURCE`` (``off`` turns the comparison off), the ``--repo`` path when it is a
simplicio-loop checkout, and the ``direct_url.json`` pip writes for a local install. With none of them,
nothing is compared.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import unquote, urlparse

from . import distribution, self_update

_NAME_RE = re.compile(r'^name\s*=\s*"simplicio-loop"\s*$', re.M)
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"\s*$', re.M)
_OPT_OUT = frozenset(("off", "0", "none", "false"))  # SIMPLICIO_LOOP_SOURCE=off disables the comparison


def running_version() -> str:
    """The version of the simplicio-loop that is executing: its install record's version, else the package's own."""
    version = distribution.installed_version()
    if version:
        return version
    from . import __version__

    return str(__version__)


def _is_loop_checkout(path: Path) -> bool:
    pyproject = path / "pyproject.toml"
    try:
        return bool(_NAME_RE.search(pyproject.read_text(encoding="utf-8")))
    except OSError:
        return False


def _installed_source_dir() -> Optional[Path]:
    """The directory pip installed simplicio-loop from (a local path install records it in direct_url.json)."""
    record = distribution.install_record()
    raw = record.read_text("direct_url.json") if record is not None else None
    if not raw:
        return None
    try:
        url = str(json.loads(raw).get("url") or "")
    except ValueError:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "file" or not parsed.path:
        return None
    return Path(unquote(parsed.path))


def source_checkout(repo: Any = None, environ: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """The simplicio-loop checkout this install is compared with, or None when there is none."""
    env = os.environ if environ is None else environ
    candidates: list[Optional[Path]] = []
    explicit = str(env.get("SIMPLICIO_LOOP_SOURCE") or "").strip()
    if explicit.lower() in _OPT_OUT:
        return None
    if explicit:
        candidates.append(Path(explicit))
    if repo:
        candidates.append(Path(repo))
    candidates.append(_installed_source_dir())
    for candidate in candidates:
        if candidate is not None and candidate.is_dir() and _is_loop_checkout(candidate):
            return candidate.resolve()
    return None


def checkout_version(checkout: Path) -> str:
    try:
        match = _VERSION_RE.search((checkout / "pyproject.toml").read_text(encoding="utf-8"))
    except OSError:
        return ""
    return match.group(1) if match else ""


def _common_git_dir(checkout: Path) -> Optional[Path]:
    """The repository's git dir (the common one for a linked worktree), read from the files, not by running git."""
    dot_git = checkout / ".git"
    try:
        if dot_git.is_dir():
            git_dir = dot_git
        elif dot_git.is_file():
            text = dot_git.read_text(encoding="utf-8").strip()
            if not text.startswith("gitdir:"):
                return None
            git_dir = (checkout / text.split(":", 1)[1].strip()).resolve()
        else:
            return None
        commondir = git_dir / "commondir"
        if commondir.is_file():
            return (git_dir / commondir.read_text(encoding="utf-8").strip()).resolve()
        return git_dir
    except OSError:
        return None


def latest_tag(checkout: Path) -> str:
    """The highest ``v*`` tag of the checkout (loose refs and packed-refs), or '' when there is none."""
    common = _common_git_dir(checkout)
    if common is None:
        return ""
    names: set[str] = set()
    try:
        for ref in (common / "refs" / "tags").rglob("*"):
            if ref.is_file():
                names.add(ref.relative_to(common / "refs" / "tags").as_posix())
    except OSError:
        pass
    try:
        for line in (common / "packed-refs").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].startswith("refs/tags/"):
                names.add(parts[1][len("refs/tags/"):])
    except OSError:
        pass
    best, best_key = "", None
    for name in names:
        if not name.startswith("v"):
            continue
        try:
            key = self_update.parse_version(name)
        except ValueError:
            continue
        if best_key is None or key > best_key:
            best, best_key = name, key
    return best


def _parse(text: str) -> Optional[tuple]:
    try:
        return self_update.parse_version(text)
    except ValueError:
        return None


def fix_command(checkout: Path) -> str:
    return f"python3 -m pip install --upgrade {shlex.quote(str(checkout))}"


def check(installed: str, *, repo: Any = None, environ: Optional[Mapping[str, str]] = None) -> Optional[dict]:
    """Compare ``installed`` with the checkout. None when no checkout is known or no version can be read."""
    checkout = source_checkout(repo, environ)
    if checkout is None:
        return None
    source = checkout_version(checkout)
    tag = latest_tag(checkout)
    targets = [(text, _parse(text)) for text in (source, tag) if _parse(text) is not None]
    current = _parse(installed)
    if not targets or current is None:
        return None
    newest_text, newest = max(targets, key=lambda item: item[1])
    return {
        "installed": installed,
        "source": source,
        "tag": tag,
        "checkout": str(checkout),
        "behind": current < newest,
        "newest": newest_text,
        "fix": fix_command(checkout),
    }


def format_line(report: Optional[Mapping[str, Any]]) -> Optional[str]:
    """One line for a stale install; None when the install is current or no report exists."""
    if not report or not report.get("behind"):
        return None
    tag = f", latest tag {report['tag']}" if report.get("tag") else ""
    return (
        f"version drift: running simplicio-loop {report['installed']} is older than the checkout "
        f"{report['source'] or report['newest']}{tag}; fix: {report['fix']}"
    )


__all__ = ["check", "checkout_version", "fix_command", "format_line", "latest_tag",
           "running_version", "source_checkout"]
