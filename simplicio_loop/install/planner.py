"""Single host-aware install planner for the simplicio-loop wheel.

`scripts/install_lib.py` remains the repo checkout entry. This module is what
the packaged `simplicio-loop install` command uses so the wheel is not a
Claude-only generic copy.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Iterator, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .. import __version__, distribution
from . import claude_hooks, entry

SCHEMA = "simplicio.loop-install-plan/v1"
OWNERSHIP_SCHEMA = "simplicio.loop-install-ownership/v2"
RECEIPT = Path(".simplicio-loop") / "install-ownership.json"
# The state folder ignores itself: `*` keeps the receipt and this file out of git; `!loop.toml` keeps the opt-in file
# the user writes there visible, so the user can commit it (the repo's own .gitignore has the same exception).
STATE_IGNORE = RECEIPT.parent / ".gitignore"
STATE_IGNORE_BODY = b"*\n!loop.toml\n"
CATALOG = Path(__file__).resolve().parents[1] / "_catalog" / "harnesses.json"
# Hosts whose surface is `.claude/skills/` + an AGENTS.md marker block (catalog surface ".claude/skills/ + AGENTS.md").
# One row per host: the layout below and the host's adapter (adapters/<host>/) follow from this list.
AGENTS_MD_HOSTS = (
    "codex", "grok", "antigravity", "mimo-code", "amp", "openclaude", "pi", "oh-my-pi", "devin", "goose", "auggie",
    "autohand", "charm", "cline", "codebuff", "command-code", "droid", "kilocode", "kimi", "mistral-vibe", "rovo-dev",
    "orca",
)
# Client opt-in: installable by name (`--host orca-dev`), never part of `--host all`.
OPT_IN_HOSTS = ("orca",)
HOSTS = (
    "claude", "cursor", "vscode", "kiro",
    "opencode", "gemini", "aider", "simplicio_agent", "openclaw", "github-copilot", "continue", "qwen",
    *(host for host in AGENTS_MD_HOSTS if host not in OPT_IN_HOSTS),
)
# THE host table. One row per installer runtime: the project surface as `destination -> kind`. `skills` copies the
# bundled skills, `hooks` copies the bundled hooks, `entry` merges the marker block into the host's instructions file
# (the rest of the file stays), and `config` writes the file a host reads when it is absent (an existing one is the
# user's). `.claude/skills` is the universal copy: every entry block names it. The other skill root of a row is the one
# the host's own docs say it scans (the catalog `source` of each host); a host whose docs name none gets only the
# universal copy (aider, continue, orca).
AGENTS_MD_LAYOUT = {".claude/skills": "skills", "AGENTS.md": "entry"}
HOST_LAYOUT = {
    "claude": {".claude/skills": "skills", "hooks": "hooks"},
    "cursor": {".claude/skills": "skills", ".cursor/skills": "skills", "hooks": "hooks"},
    "vscode": {".claude/skills": "skills", ".github/skills": "skills", ".github/copilot-instructions.md": "entry"},
    "kiro": {".claude/skills": "skills", ".kiro/skills": "skills", ".kiro/steering/simplicio-loop.md": "entry"},
    "github-copilot": {".claude/skills": "skills", ".github/skills": "skills", ".github/copilot-instructions.md": "entry"},
    "opencode": {".claude/skills": "skills", ".opencode/skills": "skills", "AGENTS.md": "entry"},
    "simplicio_agent": {".claude/skills": "skills", ".hermes/skills": "skills"},
    "continue": {".claude/skills": "skills", ".continue/rules/simplicio-loop.md": "entry"},
    "qwen": {".claude/skills": "skills", ".qwen/skills": "skills", "QWEN.md": "entry"},
    "gemini": {".claude/skills": "skills", ".gemini/skills": "skills", "GEMINI.md": "entry"},
    "aider": {".claude/skills": "skills", "CONVENTIONS.md": "entry", ".aider.conf.yml": "config"},
    "openclaw": {".claude/skills": "skills", ".agents/skills": "skills"},
    "codex": {".claude/skills": "skills", ".agents/skills": "skills", "AGENTS.md": "entry"},
    "grok": {".claude/skills": "skills", ".grok/skills": "skills", "AGENTS.md": "entry"},
    "antigravity": {".claude/skills": "skills", ".agents/skills": "skills", "AGENTS.md": "entry"},
    "mimo-code": {".claude/skills": "skills", ".mimocode/skills": "skills", "AGENTS.md": "entry"},
    "amp": {".claude/skills": "skills", ".agents/skills": "skills", "AGENTS.md": "entry"},
    "openclaude": {".claude/skills": "skills", ".openclaude/skills": "skills", "AGENTS.md": "entry"},
    "pi": {".claude/skills": "skills", ".pi/skills": "skills", "AGENTS.md": "entry"},
    "oh-my-pi": {".claude/skills": "skills", ".omp/skills": "skills", "AGENTS.md": "entry"},
    "devin": {".claude/skills": "skills", ".devin/skills": "skills", "AGENTS.md": "entry"},
    "goose": {".claude/skills": "skills", ".agents/skills": "skills", "AGENTS.md": "entry"},
    "auggie": {".claude/skills": "skills", ".augment/skills": "skills", "AGENTS.md": "entry"},
    "autohand": {".claude/skills": "skills", ".autohand/skills": "skills", "AGENTS.md": "entry"},
    "charm": {".claude/skills": "skills", ".crush/skills": "skills", "AGENTS.md": "entry"},
    "cline": {".claude/skills": "skills", ".cline/skills": "skills", "AGENTS.md": "entry"},
    "codebuff": {".claude/skills": "skills", ".agents/skills": "skills", "AGENTS.md": "entry"},
    "command-code": {".claude/skills": "skills", ".commandcode/skills": "skills", "AGENTS.md": "entry"},
    "droid": {".claude/skills": "skills", ".factory/skills": "skills", "AGENTS.md": "entry"},
    "kilocode": {".claude/skills": "skills", ".kilo/skills": "skills", "AGENTS.md": "entry"},
    "kimi": {".claude/skills": "skills", ".kimi-code/skills": "skills", "AGENTS.md": "entry"},
    "mistral-vibe": {".claude/skills": "skills", ".vibe/skills": "skills", "AGENTS.md": "entry"},
    "rovo-dev": {".claude/skills": "skills", ".rovodev/skills": "skills", "AGENTS.md": "entry"},
    "orca": dict(AGENTS_MD_LAYOUT),
}
# A --global install writes into $HOME, at the paths each host's docs name for user-level config. The universal
# `~/.claude/skills` and `~/.claude/hooks` always; the host's own user-level skill root (`GLOBAL_SKILL_ROOTS`); and, for a
# host that has a project entry file, the user-level instruction file it reads (`GLOBAL_ENTRIES`). A host with a project
# entry and no documented user-level file is not written: the plan lists it in `global_skipped`.
GLOBAL_SKILL_ROOTS = {
    "amp": ".config/amp/skills", "antigravity": ".gemini/antigravity-cli/skills", "auggie": ".augment/skills",
    "autohand": ".autohand/skills", "charm": ".config/crush/skills", "cline": ".cline/skills",
    "codebuff": ".agents/skills", "codex": ".agents/skills", "command-code": ".commandcode/skills",
    "cursor": ".cursor/skills", "devin": ".config/devin/skills", "droid": ".factory/skills", "gemini": ".gemini/skills",
    "github-copilot": ".copilot/skills", "goose": ".agents/skills", "grok": ".grok/skills", "kilocode": ".kilo/skills",
    "kimi": ".kimi-code/skills", "kiro": ".kiro/skills", "mimo-code": ".config/mimocode/skills",
    "mistral-vibe": ".vibe/skills", "oh-my-pi": ".omp/agent/skills", "opencode": ".config/opencode/skills",
    "openclaude": ".openclaude/skills", "openclaw": ".agents/skills", "pi": ".pi/agent/skills", "qwen": ".qwen/skills",
    "rovo-dev": ".rovodev/skills", "simplicio_agent": ".hermes/skills", "vscode": ".copilot/skills",
}
GLOBAL_ENTRIES = {
    "amp": ".config/amp/AGENTS.md", "antigravity": ".gemini/GEMINI.md", "auggie": ".augment/rules/simplicio-loop.md",
    "autohand": ".autohand/AGENTS.md", "charm": ".config/crush/CRUSH.md", "cline": "Documents/Cline/Rules/simplicio-loop.md",
    "codebuff": ".knowledge.md", "codex": ".codex/AGENTS.md", "command-code": ".commandcode/AGENTS.md",
    "devin": ".config/devin/AGENTS.md", "gemini": ".gemini/GEMINI.md", "github-copilot": ".copilot/copilot-instructions.md",
    "goose": ".config/goose/.goosehints", "kilocode": ".config/kilo/AGENTS.md", "kimi": ".kimi-code/AGENTS.md",
    "kiro": ".kiro/steering/simplicio-loop.md", "mimo-code": ".config/mimocode/AGENTS.md",
    "mistral-vibe": ".vibe/AGENTS.md", "oh-my-pi": ".omp/agent/AGENTS.md", "opencode": ".config/opencode/AGENTS.md",
    "pi": ".pi/agent/AGENTS.md", "qwen": ".qwen/QWEN.md", "rovo-dev": ".rovodev/AGENTS.md",
    "vscode": ".copilot/copilot-instructions.md",
}


class InstallError(RuntimeError):
    """Host unknown, version drift, or unsafe uninstall."""


def _digest(value: Any) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _bundle_root():
    return distribution.bundle_root()  # importlib.resources: the same call works from a wheel and a checkout


def _files(node, prefix: tuple = ()) -> Iterator[tuple]:
    """(path parts, Traversable) of every file under `node`, sorted; compiled caches are never shipped."""
    for child in sorted(node.iterdir(), key=lambda item: item.name):
        if child.name == "__pycache__" or child.name.endswith(".pyc"):
            continue
        if child.is_dir():
            yield from _files(child, prefix + (child.name,))
        else:
            yield prefix + (child.name,), child


def _put(path: Path, data: bytes, source, changes: dict, root: Path, dry_run: bool, made: set) -> None:
    """Classify one file (created, updated or unchanged) and write it only when it differs. `made` collects the
    directories this write creates, so uninstall can remove exactly those again."""
    rel = path.relative_to(root).as_posix()
    if path.is_file() and path.read_bytes() == data:
        changes["unchanged"] += 1
        return
    changes["updated" if path.is_file() else "created"].append(rel)
    if dry_run:
        return
    parent = path.parent
    while parent != root and not parent.exists():
        made.add(parent.relative_to(root).as_posix())
        parent = parent.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if isinstance(source, Path):  # keep the executable bit of a hook
        shutil.copymode(source, path)


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(CATALOG.read_text(encoding="utf-8"))["harnesses"])


def runtime_for(host: str) -> str:
    """The installer runtime a host id names: a runtime id, or a catalog id or alias (`orca-dev`, `hermes`, `qwen-code`).
    A model provider is not a host, so the planner refuses it, and a name that is neither is unknown."""
    installable = (*HOSTS, *OPT_IN_HOSTS)
    if host in installable:
        return host
    for item in _catalog():
        if host in [item["id"], *item["aliases"]]:
            install = item["install"]
            if install["status"] == "provider":
                raise InstallError(f"{host} is a model provider, not an install host: point a host at its API")
            if install["runtime"] in installable:
                return install["runtime"]
    raise InstallError(f"unknown host: {host}")


def _has_entry(runtime: str) -> bool:
    return any(kind == "entry" for kind in HOST_LAYOUT.get(runtime, {}).values())


def _layout(runtime: str, globally: bool) -> dict[str, str]:
    """The surface one runtime installs. Under $HOME that is the universal `.claude/skills` and `.claude/hooks`, the
    host's own user-level skill root, and the user-level instruction file the host reads (only for a host that has a
    project entry). A config file is project-scoped: the host reads it from the project it runs in."""
    layout = dict(HOST_LAYOUT.get(runtime, {".claude/skills": "skills"}))
    if not globally:
        return layout
    home = {".claude/skills": "skills", ".claude/hooks": "hooks"}
    if runtime in GLOBAL_SKILL_ROOTS:
        home[GLOBAL_SKILL_ROOTS[runtime]] = "skills"
    if _has_entry(runtime) and runtime in GLOBAL_ENTRIES:
        home[GLOBAL_ENTRIES[runtime]] = "entry"
    return home


def plan_install(
    target: str | Path,
    *,
    host: str = "claude",
    globally: bool = False,
    version: str = __version__,
) -> dict[str, Any]:
    hosts = list(HOSTS) if host == "all" else [runtime_for(host)]
    root = Path(target).resolve()
    actions = []
    for item in hosts:
        layout = _layout(item, globally)
        for dest, kind in layout.items():
            actions.append({
                "host": item,
                "kind": kind,
                "destination": dest,
                "owner": "simplicio-loop",
            })
        if item == "claude":  # the hooks are registered in settings.json; the copies alone never run them
            actions.append({
                "host": item,
                "kind": "claude_settings",
                "destination": claude_hooks.SETTINGS.as_posix(),
                "owner": "simplicio-loop",
            })
    plan = {
        "schema": SCHEMA,
        "version": version,
        "target": str(root),
        "scope": "global" if globally else "project",
        "hosts": hosts,
        "actions": actions,
        "entrypoint": "simplicio-loop=simplicio_loop.cli:main",
        # the hosts whose project entry file has no documented user-level file: a --global install does not write them
        "global_skipped": [item for item in hosts if globally and _has_entry(item) and item not in GLOBAL_ENTRIES],
    }
    plan["digest"] = _digest({key: plan[key] for key in ("schema", "version", "hosts", "actions", "scope")})
    return plan


def _blocks(payload: Mapping[str, Any]) -> dict[str, bool]:
    """The marker blocks a receipt registers: path -> whether install created that file (uninstall may delete it)."""
    blocks: dict[str, bool] = {}
    for item in payload.get("blocks") or []:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("created"), bool):
            raise InstallError("ownership receipt is malformed: `blocks` must list {path, created} objects")
        blocks[item["path"]] = item["created"]
    return blocks


def _previous_receipt(root: Path) -> dict[str, Any]:
    """What an earlier install registered, so a second host installed later does not drop the first one's files, and
    a re-install keeps the marker blocks and the hook entries an earlier install added. A receipt of another schema is
    not read: install rewrites it, and its paths are not trusted."""
    empty: dict[str, Any] = {"paths": [], "dirs": [], "blocks": {}, "claude_settings": None}
    marker = root / RECEIPT
    if not marker.is_file():
        return empty
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if payload.get("owner") != "simplicio-loop" or payload.get("schema") != OWNERSHIP_SCHEMA:
        return empty
    try:
        blocks = _blocks(payload)
    except InstallError:
        return empty
    record = payload.get("claude_settings")
    return {
        "paths": list(payload.get("paths") or []),
        "dirs": list(payload.get("dirs") or []),
        "blocks": blocks,
        "claude_settings": record if claude_hooks.valid_record(record) else None,
    }


def _claude_wiring(plan: Mapping[str, Any], root: Path, hooks_src: Any) -> claude_hooks.Wiring | None:
    """The merge of Loop's hook entries into `.claude/settings.json`, or None when this plan does not wire Claude.
    It only reads: `apply_plan` writes the result once every other check has passed."""
    if not any(action.get("kind") == "claude_settings" for action in plan.get("actions") or []):
        return None
    wanted = claude_hooks.entries(
        root / ".claude" / "hooks",
        is_global=plan.get("scope") == "global",
        available=lambda name: hooks_src.joinpath(name).is_file(),
    )
    path = root / claude_hooks.SETTINGS
    try:
        text = claude_hooks.read_raw(path)  # read once: the parsed object and the bytes install found are the same file
        current = None if text is None else claude_hooks.parse(text, str(path))
        return claude_hooks.wire(current, wanted, original=text)
    except claude_hooks.SettingsError as exc:
        raise InstallError(str(exc)) from exc


def _settings_unwiring(root: Path, receipt: Mapping[str, Any]) -> claude_hooks.Unwiring | None:
    """What uninstall does to `.claude/settings.json`, read before any file is removed so a refusal removes nothing."""
    record = receipt.get("claude_settings")
    if record is None:
        return None
    if not claude_hooks.valid_record(record):
        raise InstallError("ownership receipt is malformed: `claude_settings` must list the hook entries Loop added")
    try:
        return claude_hooks.unwire_file(root / claude_hooks.SETTINGS, record)
    except claude_hooks.SettingsError as exc:
        raise InstallError(f"{exc}; nothing was removed") from exc


def _unwired(settings: claude_hooks.Unwiring | None) -> dict[str, int]:
    """The settings file, and how many of Loop's hook entries were taken out of it."""
    if settings is None or not settings.removed:
        return {}
    return {claude_hooks.SETTINGS.as_posix(): settings.removed}


def _state_ignore(root: Path, previous: Mapping[str, Any], owned: list[str], released: set[str],
                  changes: dict[str, Any], dry_run: bool, made: set[str]) -> None:
    """Write `.simplicio-loop/.gitignore` (`*` hides the state folder from git; `!loop.toml` keeps the opt-in file
    visible) and own it.

    Install owns the file only when it creates it, or when the file it wrote is still there as written. Any other file
    there is the user's or another command's: it is left alone and not owned, so uninstall never removes it.
    """
    rel = STATE_IGNORE.as_posix()
    path = root / STATE_IGNORE
    if not path.exists() and not path.is_symlink():
        _put(path, STATE_IGNORE_BODY, None, changes, root, dry_run, made)
        owned.append(rel)
    elif (rel in previous["paths"] and path.is_file() and not path.is_symlink()
          and path.read_bytes() == STATE_IGNORE_BODY):
        changes["unchanged"] += 1
    else:
        changes["left_alone"].append(rel)
        released.add(rel)


def _public(ownership: dict[str, Any]) -> dict[str, Any]:
    """The receipt as the command reports it. The settings text the receipt keeps (`original`) stays in the file: output
    never prints the user's settings, which may hold secrets."""
    record = ownership.get("claude_settings")
    if not record or "original" not in record:
        return ownership
    return {**ownership, "claude_settings": {key: value for key, value in record.items() if key != "original"}}


def apply_plan(
    plan: Mapping[str, Any],
    *,
    dry_run: bool = False,
    bundle: Any = None,  # a path, or any importlib.resources Traversable; None = the bundle of this package
) -> dict[str, Any]:
    """Copy the bundled skills and hooks into the plan's target, merge the marker block into each entry file, and register
    the Claude Code hooks in `.claude/settings.json`. Idempotent: a file that is already identical is not rewritten, a
    settings file that already has the entries is not touched, and a marker block that is already in place is refreshed
    where it stands. `changes` says what was created, what was updated, how many were unchanged and what was left alone
    (files in the target that Loop does not own).

    The ownership receipt registers exactly the files Loop wrote or found identical, the directories it created, the
    marker blocks it put into entry files (AGENTS.md ...): a block is Loop's, the rest of that file is not, and the hook
    entries it added to the settings file. uninstall removes only those.
    """
    root = Path(plan["target"])
    owned: list[str] = []
    block_files: list[str] = []
    released: set[str] = set()  # files an earlier install owned that the user has changed since: not Loop's any more
    made: set[str] = set()
    changes: dict[str, Any] = {"created": [], "updated": [], "unchanged": 0, "left_alone": []}
    previous = _previous_receipt(root)
    blocks: dict[str, bool] = {}
    source = Path(bundle) if isinstance(bundle, str) else bundle if bundle is not None else _bundle_root()
    skills_src = source.joinpath("skills")
    hooks_src = source.joinpath("hooks")
    if not skills_src.is_dir():
        raise InstallError("bundled skills not found in the installed package.")
    # Read and merge the settings before anything is written: a settings file that cannot be parsed stops the install
    # while the target is still untouched.
    wiring = _claude_wiring(plan, root, hooks_src)
    for action in plan.get("actions") or []:
        dest = root / action["destination"]
        kind = action["kind"]
        if kind == "claude_settings":  # written below, with the rest of the Claude wiring, once every other check has passed
            continue
        rel = dest.relative_to(root).as_posix()
        if kind == "entry":  # the marker block is merged into the entry file; the file's other text stays as it is
            existed = dest.is_file()
            current = dest.read_text(encoding="utf-8") if existed else ""
            # a user-level file is read from any project, so its block names the user-level skill copy
            skills_root = "~/.claude/skills" if plan.get("scope") == "global" else ".claude/skills"
            _put(dest, entry.body_for(rel, current, skills_root).encode("utf-8"), None, changes, root, dry_run, made)
            blocks.setdefault(rel, previous["blocks"].get(rel, not existed))  # the first write of this run decides
            block_files.append(rel)
            continue
        if kind == "config":  # what the host reads: created when absent; an existing file is the user's, left alone
            body = entry.CONFIG[rel].encode("utf-8")
            if not dest.exists():
                _put(dest, body, None, changes, root, dry_run, made)
                owned.append(rel)
            elif dest.read_bytes() == body and rel in previous["paths"]:
                changes["unchanged"] += 1
            else:
                changes["left_alone"].append(rel)
                released.add(rel)  # no longer Loop's: uninstall keeps it
            continue
        src = skills_src if kind == "skills" else hooks_src
        top = set()
        for parts, node in _files(src):
            top.add(parts[0])
            file_path = dest.joinpath(*parts)
            _put(file_path, node.read_bytes(), node, changes, root, dry_run, made)
            owned.append(file_path.relative_to(root).as_posix())
        if dest.is_dir():
            changes["left_alone"] += [child.relative_to(root).as_posix() for child in sorted(dest.iterdir())
                                      if child.name not in top and child.name != "__pycache__"]
    settings_record = previous["claude_settings"]
    if wiring is not None:
        if wiring.added:
            _put(root / claude_hooks.SETTINGS, claude_hooks.render(wiring.data), None, changes, root, dry_run, made)
        elif (root / claude_hooks.SETTINGS).is_file():
            changes["unchanged"] += 1
        settings_record = claude_hooks.record_of(settings_record, wiring)
    if not (root / RECEIPT.parent).exists():  # the receipt's own directory is one more thing install creates
        made.add(RECEIPT.parent.as_posix())
    _state_ignore(root, previous, owned, released, changes, dry_run, made)
    all_blocks = {**previous["blocks"], **blocks}
    ownership: dict[str, Any] = {
        "schema": OWNERSHIP_SCHEMA,
        "owner": "simplicio-loop",
        "version": plan["version"],
        # an entry file is owned through its block, never as a whole: a receipt of an older install that listed it is corrected
        "paths": sorted((set(owned) | set(previous["paths"])) - set(block_files) - released),
        "dirs": sorted(made | set(previous["dirs"])),
        "blocks": [{"path": rel, "created": created} for rel, created in sorted(all_blocks.items())],
    }
    if settings_record is not None:
        ownership["claude_settings"] = settings_record
    # The digest describes what the receipt registers, not the last plan: installing another host later leaves it alone
    # when nothing it lists changed, so a no-op install writes nothing.
    ownership["digest"] = _digest(ownership)
    body = (json.dumps(ownership, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _put(root / RECEIPT, body, None, changes, root, dry_run, made)
    if not dry_run and "original" in (settings_record or {}):  # the receipt holds the user's settings text: owner only
        (root / RECEIPT).chmod(0o600)
    pending = len(changes["created"]) + len(changes["updated"])
    return {
        "schema": SCHEMA,
        "status": "dry_run" if dry_run else "applied",
        "written": 0 if dry_run else pending,
        "up_to_date": pending == 0,
        "changes": changes,
        "owned": sorted(set(owned) | set(block_files)),
        "ownership": _public(ownership),
        "digest": plan["digest"],
        "global_skipped": list(plan.get("global_skipped") or []),
    }


def _receipt_path(root: Path, rel: str) -> Path:
    """A receipt path is relative and stays under the target, symlinks included (`root` is resolved); anything else
    is a receipt that cannot be trusted."""
    parts = Path(rel).parts
    if not rel or not parts or Path(rel).is_absolute() or ".." in parts:
        raise InstallError(f"ownership receipt path escapes the target: {rel}")
    path = root.joinpath(*parts)
    if not Path(os.path.realpath(path.parent)).is_relative_to(root):
        raise InstallError(f"ownership receipt path escapes the target through a symlink: {rel}")
    return path


def _listed(receipt: dict[str, Any], key: str) -> list[str]:
    value = receipt.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InstallError(f"ownership receipt is malformed: `{key}` must be a list of paths")
    return value


def _read_receipt(root: Path) -> dict[str, Any]:
    marker = root / RECEIPT
    if not marker.is_file():
        raise InstallError("no Loop ownership receipt; refusing to uninstall unmanaged files")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError(f"ownership receipt is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("owner") != "simplicio-loop":
        raise InstallError("ownership receipt is not Loop-owned")
    if payload.get("schema") != OWNERSHIP_SCHEMA:
        raise InstallError(f"ownership receipt uses an obsolete schema ({payload.get('schema')}); run "
                           "`simplicio-loop install` once to rewrite it, then uninstall")
    return payload


def _entry_edits(root: Path, receipt: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    """What taking Loop's marker blocks out of the entry files does: the text each edited file keeps, and the files
    install created that hold nothing but the block now. Nothing is written here; the caller decides."""
    edits: dict[str, str] = {}
    emptied: list[str] = []
    for rel, created in sorted(_blocks(receipt).items()):  # only the marker block goes; the rest of the file stays
        path = _receipt_path(root, rel)
        if not path.is_file():
            continue
        rest = entry.remove(path.read_text(encoding="utf-8"))
        if rest is None:
            continue
        # install created this file, and nothing but the block (and the frontmatter install put in front of it) is in it
        if created and rest.strip() in ("", entry.FRONTMATTER.get(rel, "").strip()):
            emptied.append(rel)
        else:
            edits[rel] = rest
    return edits, emptied


def uninstall(target: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Remove the files the receipt registers, strip the marker blocks it wrote into entry files (deleting a file only
    when install created it and nothing else is left), take the hook entries it added out of `.claude/settings.json`
    (deleting that file only when install created it and nothing else is left), then remove the registered directories
    that are empty by then. A directory that holds anything Loop did not register (a user's skill, rule or hook) is
    kept, and so is every directory that install did not create. `dry_run` returns the same lists and touches nothing;
    then `removed` is what would go.
    """
    root = Path(target).resolve()
    receipt = _read_receipt(root)
    settings = _settings_unwiring(root, receipt)
    edits, emptied = _entry_edits(root, receipt)
    files = sorted({RECEIPT.as_posix(), *_listed(receipt, "paths"), *emptied})
    gone: set[str] = set()
    removed: list[str] = []
    skipped: list[str] = []
    for rel in files:
        path = _receipt_path(root, rel)
        if path.is_file():
            removed.append(rel)
            gone.add(rel)
        elif path.exists():  # a directory where a file was registered: not Loop's to delete
            skipped.append(rel)
    if settings is not None and settings.delete:
        removed.append(claude_hooks.SETTINGS.as_posix())
        gone.add(claude_hooks.SETTINGS.as_posix())
    removed_dirs: list[str] = []
    kept: list[str] = []
    for rel in sorted(set(_listed(receipt, "dirs")), key=lambda item: item.count("/"), reverse=True):
        path = _receipt_path(root, rel)
        if path.is_symlink() or not path.is_dir():  # a link is the user's, whatever it points at
            continue
        if all(child.relative_to(root).as_posix() in gone for child in path.iterdir()):
            removed_dirs.append(rel)
            gone.add(rel)
        else:
            kept.append(rel)
    if not dry_run:
        for rel, text in edits.items():
            _receipt_path(root, rel).write_text(text, encoding="utf-8", newline="\n")
        for rel in removed:
            _receipt_path(root, rel).unlink()
        if settings is not None and settings.removed and not settings.delete:
            claude_hooks.write(root / claude_hooks.SETTINGS, settings.data or {}, settings.restore)
        for rel in removed_dirs:
            _receipt_path(root, rel).rmdir()
    return {
        "schema": OWNERSHIP_SCHEMA,
        "status": "dry_run" if dry_run else "removed",
        "removed": removed,
        "edited": sorted(edits),
        "removed_dirs": removed_dirs,
        "kept": kept,
        "skipped": skipped,
        "unwired": _unwired(settings),
    }


def verify_plan(plan: Mapping[str, Any], expected_version: str = __version__) -> dict[str, Any]:
    if plan.get("version") != expected_version:
        raise InstallError(
            f"descriptor version mismatch: plan={plan.get('version')} wheel={expected_version}"
        )
    return {"ok": True, "version": expected_version, "digest": plan.get("digest")}


def prune_project_copies(target: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Detect and remove legacy/stale project-scope copies when Loop is installed globally.

    Scans the project target for:
    - Files registered in .simplicio-loop/install-ownership.json (if present)
    - Project-scope simplicio-* skill directories (.claude/skills, .cursor/skills, etc.)
    - Project-scope Loop rule files (.claude/rules, .cursor/rules, .github, etc.)
    - Project-scope hooks installed by Loop
    - The Loop marker blocks in the entry files (AGENTS.md ...) and the hook entries in .claude/settings.json that the
      receipt registers: only those go, and a file is deleted only when install created it and nothing else is left
    - The .simplicio-loop directory itself

    Never deletes foreign user files or unmanaged user directories.
    """
    root = Path(target).resolve()
    removed: list[str] = []
    removed_dirs: list[str] = []
    kept: list[str] = []

    receipt_data = None
    marker = root / RECEIPT
    if marker.is_file():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            if payload.get("owner") == "simplicio-loop":
                receipt_data = payload
        except (OSError, ValueError):
            pass

    # The marker blocks and the hook entries the project's install added are taken out with the files they point at.
    # Read first, so an unreadable receipt or settings file stops the prune before anything is deleted.
    entry_edits: dict[str, str] = {}
    emptied: list[str] = []
    if receipt_data is not None:
        entry_edits, emptied = _entry_edits(root, receipt_data)
    settings = None
    if receipt_data is not None and claude_hooks.valid_record(receipt_data.get("claude_settings")):
        try:
            settings = claude_hooks.unwire_file(root / claude_hooks.SETTINGS, receipt_data["claude_settings"])
        except claude_hooks.SettingsError as exc:
            raise InstallError(f"{exc}; nothing was removed") from exc

    candidates: set[Path] = {root / rel for rel in emptied}
    dirs_to_check: set[Path] = set()

    if receipt_data:
        for rel in receipt_data.get("paths") or []:
            p = root / rel
            if p.is_file():
                candidates.add(p)
        for rel in receipt_data.get("dirs") or []:
            dirs_to_check.add(root / rel)
        candidates.add(marker)
        dirs_to_check.add(marker.parent)

    from ..host_rules import project_destinations
    for _name, rule_path in project_destinations(root):
        if rule_path.is_file():
            candidates.add(rule_path)
            dirs_to_check.add(rule_path.parent)

    kiro_entry = root / ".kiro" / "steering" / "simplicio-loop.md"
    if kiro_entry.is_file():
        candidates.add(kiro_entry)
        dirs_to_check.add(kiro_entry.parent)

    from ..skill_sync import SKILLS
    for skill_parent in (root / ".claude" / "skills", root / ".cursor" / "skills"):
        if skill_parent.is_dir():
            for skill in SKILLS:
                s_dir = skill_parent / skill
                if s_dir.is_dir():
                    for p in s_dir.rglob("*"):
                        if p.is_file():
                            candidates.add(p)
                    dirs_to_check.add(s_dir)
            dirs_to_check.add(skill_parent)

    hooks_dir = root / "hooks"
    if hooks_dir.is_dir():
        for p in hooks_dir.iterdir():
            if p.is_file() and p.name.startswith("loop_"):
                candidates.add(p)
        dirs_to_check.add(hooks_dir)

    simplicio_dir = root / ".simplicio-loop"
    if simplicio_dir.is_dir():
        for p in simplicio_dir.rglob("*"):
            if p.is_file():
                candidates.add(p)
        dirs_to_check.add(simplicio_dir)

    gone: set[Path] = set()
    for file_path in sorted(candidates):
        if file_path.is_file():
            rel = file_path.relative_to(root).as_posix()
            removed.append(rel)
            gone.add(file_path)
            if not dry_run:
                try:
                    file_path.unlink()
                except OSError:
                    pass

    for rel, text in entry_edits.items():
        if not dry_run:
            _receipt_path(root, rel).write_text(text, encoding="utf-8", newline="\n")

    if settings is not None:
        if settings.delete:
            removed.append(claude_hooks.SETTINGS.as_posix())
            gone.add(root / claude_hooks.SETTINGS)
            if not dry_run:
                try:
                    (root / claude_hooks.SETTINGS).unlink()
                except OSError:
                    pass
        elif settings.removed and not dry_run:
            claude_hooks.write(root / claude_hooks.SETTINGS, settings.data or {}, settings.restore)

    all_dirs: set[Path] = set()
    for d in dirs_to_check:
        cur = d
        while cur != root and cur.parent != cur:
            all_dirs.add(cur)
            cur = cur.parent

    for dir_path in sorted(all_dirs, key=lambda d: len(d.parts), reverse=True):
        if not dir_path.exists() or not dir_path.is_dir():
            continue
        try:
            remaining_children = [c for c in dir_path.iterdir() if c not in gone]
            if not remaining_children:
                rel = dir_path.relative_to(root).as_posix()
                removed_dirs.append(rel)
                gone.add(dir_path)
                if not dry_run:
                    dir_path.rmdir()
            else:
                rel = dir_path.relative_to(root).as_posix()
                if rel not in kept:
                    kept.append(rel)
        except OSError:
            pass

    return {
        "schema": OWNERSHIP_SCHEMA,
        "status": "dry_run" if dry_run else "removed",
        "removed": sorted(removed),
        "removed_dirs": sorted(removed_dirs),
        "kept": sorted(kept),
        "edited": sorted(entry_edits),
        "unwired": _unwired(settings),
    }
