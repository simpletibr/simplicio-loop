#!/usr/bin/env python3
"""Sync multi-LLM operator-flow rules into every supported host surface.

Idempotent. Creates dirs; overwrites only Simplicio-owned rule files.
Does not delete foreign user rules.

Usage:
  python3 scripts/host_rule_sync.py --global --json
  python3 scripts/host_rule_sync.py --target /path/to/repo --json
  python3 scripts/host_rule_sync.py --global --target . --json
  python3 scripts/host_rule_sync.py --check --target . --json   # drift check, no writes (#1305)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
RULE_SRC = SOURCE / "packaging" / "host-rules" / "simplicio-loop-operator-flow.md"
RULE_NAME = "simplicio-loop-operator-flow.md"
OWNED_MARKERS = ("simplicio-loop-operator-flow", "SIMPLICIO_LOOP_STRICT")


def _home() -> Path:
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


def sync(*, do_global: bool, target: Path | None) -> dict:
    if not RULE_SRC.is_file():
        raise FileNotFoundError(f"missing rule source: {RULE_SRC}")
    body = RULE_SRC.read_text(encoding="utf-8")
    written: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    home = _home()

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
    byte-identical to `packaging/host-rules/simplicio-loop-operator-flow.md`. A
    destination that does not exist yet is not drift (not every host is synced in
    every checkout); a destination that exists but differs is.
    """
    if not RULE_SRC.is_file():
        raise FileNotFoundError(f"missing rule source: {RULE_SRC}")
    body = RULE_SRC.read_text(encoding="utf-8")
    drift: list[dict[str, str]] = []
    checked: list[str] = []
    for name, path in project_destinations(target):
        if path.suffix in (".ps1", ".sh"):
            continue  # env files carry generated env content, not the rule doc
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global", dest="do_global", action="store_true")
    p.add_argument("--target", type=str, default=None)
    p.add_argument("--check", action="store_true", help="read-only drift check; no writes")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if args.check:
        target = Path(args.target).resolve() if args.target else Path.cwd()
        try:
            receipt = check(target=target)
        except Exception as exc:
            err = {"schema": "simplicio.host-rule-sync-check/v1", "ok": False, "error": str(exc)}
            print(json.dumps(err, indent=2) if args.json else f"host_rule_sync --check FAIL: {exc}")
            return 1
        if args.json:
            print(json.dumps(receipt, indent=2, sort_keys=True))
        else:
            print(f"host_rule_sync --check: {'OK' if receipt['ok'] else 'DRIFT'} "
                  f"({len(receipt['checked'])} checked, {len(receipt['drift'])} drifted)")
            for item in receipt["drift"]:
                print(f"  - {item['surface']}: {item['path']}")
        return 0 if receipt["ok"] else 1
    if not args.do_global and not args.target:
        args.do_global = True
    try:
        receipt = sync(
            do_global=args.do_global,
            target=Path(args.target) if args.target else None,
        )
    except Exception as exc:
        err = {"schema": "simplicio.host-rule-sync/v1", "ok": False, "error": str(exc)}
        print(json.dumps(err, indent=2) if args.json else f"host_rule_sync FAIL: {exc}")
        return 1
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(f"host_rule_sync: wrote {receipt['count']} surfaces")
        for item in receipt["written"]:
            print(f"  - {item['surface']}: {item['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
