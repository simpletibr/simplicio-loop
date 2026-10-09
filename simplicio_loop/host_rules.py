"""Host operator-flow rules: write them into every supported host surface and keep them fresh.

Ships in the wheel (the rule text lives in ``simplicio_loop/_bundle/host-rules/``).
``scripts/host_rule_sync.py`` is the checkout CLI over this module; ``operator_check`` and
the doctor use ``stale_rules`` / ``resync_installed_rules`` to refresh the rule copies a host
ALREADY has after a package upgrade (#1472).

Idempotent. Creates dirs; overwrites only Simplicio-owned rule files. Never deletes foreign
user rules.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

RULE_NAME = "simplicio-loop-operator-flow.md"
RULE_SRC = Path(__file__).resolve().parent / "_bundle" / "host-rules" / RULE_NAME
OWNED_MARKERS = ("simplicio-loop-operator-flow", "SIMPLICIO_LOOP_STRICT")

PathLike = Union[str, os.PathLike]


def default_home() -> Path:
    return Path(os.environ.get("SIMPLICIO_HOME") or os.environ.get("HOME") or Path.home())


def global_destinations(home: Path) -> list[tuple[str, Path]]:
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    return [
        ("claude_rules", home / ".claude" / "rules" / RULE_NAME),
        ("claude_skill_ref", home / ".claude" / "skills" / "simplicio-loop" / "references" / "host-operator-flow.md"),
        ("codex", home / ".codex" / "rules" / RULE_NAME),
        ("grok", home / ".grok" / "rules" / RULE_NAME),
        ("agents", home / ".agents" / "rules" / RULE_NAME),
        ("cursor_user", home / ".cursor" / "rules" / RULE_NAME),
        ("vscode_skills", home / ".vscode" / "simplicio-skills" / "rules" / RULE_NAME),
        ("vscode_user", appdata / "Code" / "User" / "simplicio-rules" / RULE_NAME),
        ("copilot", home / ".copilot" / "rules" / RULE_NAME),
        ("antigravity", home / ".antigravity" / "rules" / RULE_NAME),
        ("kiro_user", home / ".kiro" / "steering" / RULE_NAME),
        ("hermes", home / ".hermes" / "rules" / RULE_NAME),
        ("simplicio_agent", home / ".simplicio-loop" / "rules" / RULE_NAME),
        ("opencode", home / ".config" / "opencode" / "rules" / RULE_NAME),
        ("env_ps1", home / ".simplicio-loop" / "loop-env.ps1"),
        ("env_sh", home / ".simplicio-loop" / "loop-env.sh"),
    ]


def project_destinations(root: Path) -> list[tuple[str, Path]]:
    return [
        ("project_claude", root / ".claude" / "rules" / RULE_NAME),
        ("project_cursor", root / ".cursor" / "rules" / RULE_NAME),
        ("project_kiro", root / ".kiro" / "steering" / RULE_NAME),
        ("project_github", root / ".github" / "simplicio-loop-operator-flow.md"),
        ("project_simplicio", root / ".simplicio-loop" / "host-rules" / RULE_NAME),
    ]


ENV_PS1 = """# Simplicio loop strict operator floor (synced by host_rule_sync.py)
# Core = mapper + dev-cli. There is no Runtime/MCP backend.
$env:SIMPLICIO_LOOP = "1"
$env:SIMPLICIO_LOOP_STRICT = "1"
$env:SIMPLICIO_REQUIRE_MUTATION_AUTHORITY = "1"
$env:SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT = "1"
$env:SIMPLICIO_LOOP_FORBID_HAND_EDIT = "1"
$env:SIMPLICIO_EXECUTION_PROFILE = "standalone"
"""

ENV_SH = """# Simplicio loop strict operator floor (synced by host_rule_sync.py)
# Core = mapper + dev-cli. There is no Runtime/MCP backend.
export SIMPLICIO_LOOP=1
export SIMPLICIO_LOOP_STRICT=1
export SIMPLICIO_REQUIRE_MUTATION_AUTHORITY=1
export SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT=1
export SIMPLICIO_LOOP_FORBID_HAND_EDIT=1
export SIMPLICIO_EXECUTION_PROFILE=standalone
"""


def _write(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return str(path)


def _is_ours(path: Path) -> bool:
    if not path.is_file():
        return True
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return True
    return any(marker in text for marker in OWNED_MARKERS)


def _rule_body() -> str:
    if not RULE_SRC.is_file():
        raise FileNotFoundError(f"missing rule source: {RULE_SRC}")
    return RULE_SRC.read_text(encoding="utf-8")


def sync(*, do_global: bool, target: Path | None) -> dict:
    body = _rule_body()
    written: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    home = default_home()

    pairs: list[tuple[str, Path]] = []
    if do_global:
        pairs.extend(global_destinations(home))
    if target is not None:
        pairs.extend(project_destinations(Path(target).resolve()))

    for name, path in pairs:
        if path.name.endswith(".ps1"):
            written.append({"surface": name, "path": _write(path, ENV_PS1), "kind": "env"})
            continue
        if path.name.endswith(".sh"):
            written.append({"surface": name, "path": _write(path, ENV_SH), "kind": "env"})
            continue
        if path.is_file() and not _is_ours(path):
            alt = path.with_name(path.stem + ".simplicio-loop" + path.suffix)
            written.append({"surface": name, "path": _write(alt, body), "kind": "rule-sidecar"})
            skipped.append({"surface": name, "path": str(path), "reason": "foreign_file_preserved"})
            continue
        written.append({"surface": name, "path": _write(path, body), "kind": "rule"})

    return {
        "schema": "simplicio.host-rule-sync/v1",
        "ok": True,
        "source": str(RULE_SRC),
        "written": written,
        "skipped": skipped,
        "count": len(written),
    }


def check(*, target: Path) -> dict:
    """Read-only drift check (#1305): every already-synced project rule file must be
    byte-identical to the packaged rule. A destination that does not exist yet is not drift
    (not every host is synced in every checkout); a destination that exists but differs is.
    """
    body = _rule_body()
    drift: list[dict[str, str]] = []
    checked: list[str] = []
    for name, path in project_destinations(target):
        if not path.is_file():
            continue
        checked.append(name)
        text = path.read_text(encoding="utf-8", errors="replace")
        if text != body:
            drift.append({"surface": name, "path": str(path)})
    return {
        "schema": "simplicio.host-rule-sync-check/v1",
        "ok": not drift,
        "source": str(RULE_SRC),
        "checked": checked,
        "drift": drift,
    }


def installed_rules(home: Optional[PathLike] = None) -> dict:
    """surface -> path, for Simplicio-owned global rule files a host ALREADY has."""
    base = Path(home) if home is not None else default_home()
    return {name: path for name, path in global_destinations(base)
            if path.suffix == ".md" and path.is_file() and _is_ours(path)}


def stale_rules(home: Optional[PathLike] = None) -> list:
    """Installed global rule files whose content differs from the packaged rule."""
    body = _rule_body()
    return [{"surface": name, "path": str(path)}
            for name, path in sorted(installed_rules(home).items())
            if path.read_text(encoding="utf-8", errors="replace") != body]


def resync_installed_rules(home: Optional[PathLike] = None) -> dict:
    """Rewrite stale rule files; hosts without the rule are never given one.

    Returns ``{"synced": [surface, ...], "errors": [{"host", "error"}, ...]}``.
    """
    body = _rule_body()
    report = {"synced": [], "errors": []}
    for entry in stale_rules(home):
        try:
            _write(Path(entry["path"]), body)
            report["synced"].append(entry["surface"])
        except OSError as exc:
            report["errors"].append({"host": entry["surface"], "error": str(exc)})
    return report
