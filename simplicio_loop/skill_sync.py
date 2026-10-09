"""Keep the skills installed in host config dirs in sync with the installed package (#1472).

``operator_check maybe-upgrade`` only runs ``pip install -U``; the copies that
``install_lib.py`` dropped under ``~/.claude/skills`` and friends stay frozen at the
old version. This module ships in the wheel and compares / refreshes those copies
against the skills bundled in ``simplicio_loop/_bundle/skills`` (the same tree in a
checkout and in a pip install).

Only skill directories that are ALREADY installed are touched: a host the user never
installed stays untouched, and nothing outside the fixed skill list is deleted.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Optional, Union

SKILLS = ("simplicio-tasks", "simplicio-loop", "simplicio-orient",
          "simplicio-review", "simplicio-compress", "simplicio-learn",
          "simplicio-autoresearch")

# host -> skills root under $HOME. Single table: the doctor digest and the resync both read it.
# `claude` is also where every generic `--global` install lands (target = $HOME).
HOST_SKILL_ROOTS = {
    "claude": ".claude/skills",
    "cursor": ".cursor/skills",
    "codex": ".codex/skills",
    "grok": ".grok/skills",
    "agents": ".agents/skills",
    "copilot": ".copilot/skills",
    "vscode": ".vscode/simplicio-skills",
    "opencode": ".config/opencode/skills",
    "amp": ".config/amp/skills",
    "kiro": ".kiro/steering",
    "simplicio_agent": ".simplicio-loop/skills",
}

# Written into the installed loop skill by the host-rule sync (simplicio_loop.host_rules), not
# shipped in the package skill: skill digests and resyncs leave it alone.
HOST_RULE_REF = "references/host-operator-flow.md"

PathLike = Union[str, os.PathLike]


def _skill_files(root: Path) -> list:
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts
                  and p.relative_to(root).as_posix() != HOST_RULE_REF)


def package_skills_dir() -> Path:
    return Path(__file__).resolve().parent / "_bundle" / "skills"


def default_home() -> Path:
    return Path(os.environ.get("SIMPLICIO_HOME") or os.environ.get("HOME")
                or os.path.expanduser("~"))


def skill_digest(skill_dir: PathLike) -> str:
    """SHA256 over relative paths + bytes of every file under ``skill_dir`` ('' if absent)."""
    root = Path(skill_dir)
    if not root.is_dir():
        return ""
    h = hashlib.sha256()
    for path in _skill_files(root):
        h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        h.update(path.read_bytes())
    return h.hexdigest()


def installed_skill_hosts(home: Optional[PathLike] = None) -> dict:
    """host -> skills root, for hosts that already have ``simplicio-loop`` installed."""
    base = Path(home) if home is not None else default_home()
    return {host: base / rel for host, rel in HOST_SKILL_ROOTS.items()
            if (base / rel / "simplicio-loop").is_dir()}


def stale_skills(home: Optional[PathLike] = None) -> list:
    """Installed skill dirs whose digest differs from the package copy.

    One entry per (host, skill): ``{"host", "skill", "path", "reason"}`` where reason is
    ``stale`` (content differs) or ``missing`` (the host has the loop skill but not this one).
    """
    source = package_skills_dir()
    out = []
    for host, root in sorted(installed_skill_hosts(home).items()):
        for skill in SKILLS:
            want = skill_digest(source / skill)
            if not want:
                continue
            have = skill_digest(root / skill)
            if have != want:
                out.append({"host": host, "skill": skill, "path": str(root / skill),
                            "reason": "missing" if not have else "stale"})
    return out


def resync_installed_skills(home: Optional[PathLike] = None) -> dict:
    """Replace stale/missing skills of every already-installed host with the package copy.

    Returns ``{"synced": [host, ...], "errors": [{"host", "error"}, ...]}``; ``synced`` lists
    only hosts where at least one skill was rewritten.
    """
    source = package_skills_dir()
    report = {"synced": [], "errors": []}
    for entry in stale_skills(home):
        host = entry["host"]
        dst = Path(entry["path"])
        try:
            src = source / entry["skill"]
            keep = {p.relative_to(src) for p in _skill_files(src)}
            if dst.exists():
                for old in _skill_files(dst):
                    if old.relative_to(dst) not in keep:
                        old.unlink()
            shutil.copytree(src, dst, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
            if host not in report["synced"]:
                report["synced"].append(host)
        except OSError as exc:
            report["errors"].append({"host": host, "error": "%s: %s" % (entry["skill"], exc)})
    return report
