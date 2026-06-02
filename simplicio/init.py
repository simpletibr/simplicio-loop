"""init.py — install skill + UserPromptSubmit hook into ~/.claude/.

Idempotent: re-running upgrades the skill, re-installs the hook script, and
re-merges the settings.json hook entry without duplicating.
"""
from __future__ import annotations

import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from .utils.serialization import dumps_str, loads

try:
    from importlib.resources import files as _res_files
except ImportError:  # pragma: no cover
    from importlib_resources import files as _res_files  # type: ignore

HOOK_MARKER = "simplicio-userpromptsubmit"


@dataclass
class InstallReport:
    claude_home: Path
    skill_path: Path
    hook_script_path: Path
    settings_path: Path
    skill_installed: bool
    hook_script_installed: bool
    settings_updated: bool
    dry_run: bool


def install(claude_home=None, dry_run: bool = False) -> InstallReport:
    home = Path(claude_home) if claude_home else Path.home() / ".claude"
    skill_dir = home / "skills" / "simplicio-cli"
    hooks_dir = home / "hooks"
    settings_path = home / "settings.json"

    skill_target = skill_dir / "SKILL.md"
    hook_target = hooks_dir / "simplicio-userpromptsubmit.sh"

    skill_src = _resource_text("SKILL.md")
    hook_src = _resource_text("userpromptsubmit-hook.sh")

    skill_changed = _file_differs(skill_target, skill_src)
    hook_changed = _file_differs(hook_target, hook_src)
    settings_changed, new_settings = _plan_settings_update(settings_path, hook_target)

    if not dry_run:
        home.mkdir(parents=True, exist_ok=True)
        skill_dir.mkdir(parents=True, exist_ok=True)
        hooks_dir.mkdir(parents=True, exist_ok=True)

        if skill_changed:
            skill_target.write_text(skill_src, encoding="utf-8")
        if hook_changed:
            hook_target.write_text(hook_src, encoding="utf-8")
            hook_target.chmod(hook_target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if settings_changed:
            if settings_path.exists():
                shutil.copy2(settings_path, settings_path.with_suffix(".json.bak"))
            settings_path.write_text(dumps_str(new_settings, indent=True) + "\n", encoding="utf-8")

    return InstallReport(
        claude_home=home,
        skill_path=skill_target,
        hook_script_path=hook_target,
        settings_path=settings_path,
        skill_installed=skill_changed,
        hook_script_installed=hook_changed,
        settings_updated=settings_changed,
        dry_run=dry_run,
    )


def _resource_text(name: str) -> str:
    pkg = _res_files("simplicio") / "templates" / name
    return pkg.read_text(encoding="utf-8")


def _file_differs(target: Path, new_content: str) -> bool:
    if not target.exists():
        return True
    try:
        return target.read_text(encoding="utf-8") != new_content
    except OSError:
        return True


def _plan_settings_update(settings_path: Path, hook_target: Path):
    settings: dict = {}
    if settings_path.exists():
        try:
            settings = loads(settings_path.read_bytes())
        except ValueError:
            return False, settings

    if not isinstance(settings, dict):
        return False, settings

    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return False, settings

    entries = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(entries, list):
        return False, settings

    command_str = str(hook_target)
    already_present = any(
        _entry_matches(e, command_str) for e in entries if isinstance(e, dict)
    )
    if already_present:
        return False, settings

    entries.append({
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": command_str,
        }],
    })
    return True, settings


def _entry_matches(entry: dict, command_str: str) -> bool:
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    for h in hooks:
        if not isinstance(h, dict):
            continue
        cmd = h.get("command", "")
        if HOOK_MARKER in cmd or cmd == command_str:
            return True
    return False


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="simplicio-py init",
        description="Install simplicio-cli skill + UserPromptSubmit hook into ~/.claude/",
    )
    ap.add_argument("--claude-home", help="override ~/.claude (for tests)")
    ap.add_argument("--dry-run", action="store_true", help="show what would change, don't write")
    args = ap.parse_args(argv)

    home = Path(args.claude_home) if args.claude_home else None
    report = install(claude_home=home, dry_run=args.dry_run)

    print(f"claude_home:         {report.claude_home}")
    print(f"skill:               {report.skill_path}  ({'updated' if report.skill_installed else 'unchanged'})")
    print(f"hook script:         {report.hook_script_path}  ({'updated' if report.hook_script_installed else 'unchanged'})")
    print(f"settings.json:       {report.settings_path}  ({'updated' if report.settings_updated else 'unchanged'})")
    if report.dry_run:
        print("(dry-run — no files written)")
    else:
        print()
        print("done. open a new Claude Code session — skill auto-fires on code-edit prompts,")
        print("and the UserPromptSubmit hook prints a hint as a deterministic fallback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
