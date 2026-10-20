"""Claude Code hook wiring: Loop's entries in `.claude/settings.json`.

`simplicio-loop install` (planner.py) and the git-clone installer (scripts/install_lib.py) both use this module, so the
wiring has one implementation. `wire` adds only the entries that are missing and keeps everything the user has.
`unwire` removes exactly the entries the ownership receipt recorded, and the containers install created that are empty
by then. When the user has not changed the file since install, uninstall writes back the exact bytes install found.
A file that cannot be parsed is never overwritten.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SETTINGS = Path(".claude") / "settings.json"
_WHERE = ".claude/settings.json"


class SettingsError(RuntimeError):
    """`.claude/settings.json` cannot be read, or does not have the shape the merge needs. Nothing was written."""


@dataclass(frozen=True)
class Entry:
    event: str  # the hook event: "Stop" or "PreToolUse"
    file: str  # the hook file the entry runs; a command that already names it counts as wired
    command: str
    matcher: str | None = None  # None: every tool call; "Bash": Bash calls only

    def record(self) -> dict[str, Any]:
        return {"event": self.event, "matcher": self.matcher, "command": self.command}


@dataclass(frozen=True)
class Wiring:
    data: dict[str, Any]  # the settings object after the merge
    added: list[Entry]  # the entries this merge adds; none means the file needs no write
    created_events: list[str]  # hook events whose list this merge created
    created_hooks: bool  # whether this merge created the "hooks" object
    created_file: bool  # whether the file did not exist before this merge
    original: str | None = None  # the file's text before this merge, as it is on disk; None when there was no file


@dataclass(frozen=True)
class Unwiring:
    data: dict[str, Any] | None  # what the file should hold, or None when there is no file
    removed: int  # hook entries removed
    delete: bool  # install created the file and nothing else is left in it
    restore: str | None = None  # the text install found, when the user has not changed the file since: written back as is


def entries(hooks_dir: Path, *, is_global: bool, available: Callable[[str], bool]) -> list[Entry]:
    """The entries to wire, in order. A hook the bundle does not ship is not wired: nothing would run it."""

    def command(name: str) -> str:
        if is_global:  # a global session's cwd varies, so the hook is named by its absolute path
            path = os.path.abspath(hooks_dir / name).replace("\\", "/")
            return f'python3 "{path}"'
        return f"python3 ./hooks/{name}"  # a project names its hooks relative to the project root

    wanted = [
        Entry("Stop", "loop_stop.py", command("loop_stop.py")),
        # No matcher on purpose: the STRICT hand-edit gate in action_gate.py must also see host Write/Edit calls.
        Entry("PreToolUse", "action_gate.py", command("action_gate.py")),
    ]
    if not is_global:  # orient_rewrite rewrites Bash calls, so it is opt-in per project and never global
        wanted.append(Entry("PreToolUse", "orient_rewrite.py", command("orient_rewrite.py"), matcher="Bash"))
    return [entry for entry in wanted if available(entry.file)]


def read(path: Path) -> dict[str, Any] | None:
    """The settings object, or None when the file does not exist. An empty file counts as an empty object."""
    text = read_raw(path)
    return None if text is None else parse(text, str(path))


def read_raw(path: Path) -> str | None:
    """The file's text exactly as it is on disk, or None when there is no file. Nothing is translated, because uninstall
    may have to write these bytes back."""
    if not path.exists():
        return None
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, ValueError) as exc:
        raise SettingsError(f"{path} cannot be read: {exc}") from exc


def parse(text: str, where: str) -> dict[str, Any]:
    """The settings object that `text` holds. Blank text counts as an empty object; `where` names the file in errors."""
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SettingsError(f"{where} is not valid JSON ({exc}); fix it, then run the command again") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{where} must hold a JSON object")
    return data


def wire(current: Mapping[str, Any] | None, wanted: Sequence[Entry], original: str | None = None) -> Wiring:
    """Merge the entries that are missing into `current`. An entry counts as present when a hook of the same event
    already runs a command that names its file, whoever wrote it. Nothing already in the object changes. `original` is
    the file's text as it was before the merge (`read_raw`), which the receipt keeps when this is the first install."""
    base = dict(current) if current is not None else {}
    hooks = base.get("hooks", {})
    if not isinstance(hooks, dict):
        raise SettingsError(f'{_WHERE}: "hooks" must be an object')
    missing = [entry for entry in wanted if not _has(hooks, entry)]
    if not missing:
        return Wiring(data=base, added=[], created_events=[], created_hooks=False, created_file=False,
                      original=original)
    data = copy.deepcopy(base)
    created_hooks = "hooks" not in data
    target = data.setdefault("hooks", {})
    created_events: list[str] = []
    for entry in missing:
        if entry.event not in target:
            target[entry.event] = []
            created_events.append(entry.event)
        elif not isinstance(target[entry.event], list) or not all(_valid_group(g) for g in target[entry.event]):
            raise SettingsError(f'{_WHERE}: "hooks.{entry.event}" must be a list of hook groups')
        group: dict[str, Any] = {"hooks": [{"type": "command", "command": entry.command}]}
        if entry.matcher is not None:
            group = {"matcher": entry.matcher, **group}
        target[entry.event].append(group)
    return Wiring(data=data, added=missing, created_events=created_events,
                  created_hooks=created_hooks, created_file=current is None, original=original)


def unwire(data: Mapping[str, Any], record: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """`data` without the entries `record` lists, and without the containers install created that are empty now.
    Returns the new object and how many hook entries were removed."""
    result = copy.deepcopy(dict(data))
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result, 0
    removed = 0
    for entry in record["entries"]:
        groups = hooks.get(entry["event"])
        if isinstance(groups, list) and _remove_one(groups, entry):
            removed += 1
    for event in record["created_events"]:
        if hooks.get(event) == []:
            del hooks[event]
    if record["created_hooks"] and hooks == {}:
        del result["hooks"]
    return result, removed


def unwire_file(path: Path, record: Mapping[str, Any]) -> Unwiring:
    """Read `path` and undo `record` on it. Nothing is written here: the caller decides."""
    current = read(path)
    if current is None:
        return Unwiring(data=None, removed=0, delete=False)
    data, removed = unwire(current, record)
    delete = bool(record["file_created"]) and data == {} and not path.is_symlink()
    return Unwiring(data=data, removed=removed, delete=delete, restore=_as_found(record.get("original"), data))


def _as_found(original: str | None, data: Mapping[str, Any]) -> str | None:
    """The stored text when it holds exactly `data`, which means the user has not changed the file since install. Any
    other change returns None, and uninstall keeps the user's change by writing `data` as it renders."""
    if original is None:
        return None
    try:
        return original if parse(original, _WHERE) == data else None
    except SettingsError:
        return None


def record_of(previous: Mapping[str, Any] | None, wiring: Wiring) -> dict[str, Any] | None:
    """What the ownership receipt records about the file: every entry Loop added, including in earlier installs, what
    Loop created, and the text the file had before Loop first wired it. None when Loop has never added an entry here."""
    prior = dict(previous or {})
    recorded = [dict(item) for item in prior.get("entries", [])]
    for entry in wiring.added:
        if entry.record() not in recorded:
            recorded.append(entry.record())
    if not recorded:
        return None
    created_events = list(prior.get("created_events", []))
    created_events += [event for event in wiring.created_events if event not in created_events]
    record: dict[str, Any] = {
        "entries": recorded,
        "created_events": created_events,
        "created_hooks": bool(prior.get("created_hooks")) or wiring.created_hooks,
        "file_created": bool(prior.get("file_created")) or wiring.created_file,
    }
    # The first install that wires an existing file keeps its text; a re-install keeps that text, never the wired one.
    if previous is None:
        original = None if wiring.created_file else wiring.original
    else:
        original = prior.get("original")
    if original is not None:
        record["original"] = original
    return record


def valid_record(value: Any) -> bool:
    """Whether a receipt's `claude_settings` record has the shape `unwire` reads. A receipt is data, so nothing is
    removed on the strength of a record that does not validate."""
    if not isinstance(value, dict):
        return False
    entries_ = value.get("entries")
    events = value.get("created_events")
    if not isinstance(entries_, list) or not isinstance(events, list):
        return False
    if not all(isinstance(event, str) for event in events):
        return False
    if not isinstance(value.get("created_hooks"), bool) or not isinstance(value.get("file_created"), bool):
        return False
    if "original" in value and not isinstance(value["original"], str):
        return False
    return all(_valid_entry(item) for item in entries_)


def render(data: Mapping[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write(path: Path, data: Mapping[str, Any], text: str | None = None) -> None:
    """Write the settings object `data` as JSON, or `text` exactly as it is when given (uninstall's restore)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render(data) if text is None else text.encode("utf-8"))


def _has(hooks: Mapping[str, Any], entry: Entry) -> bool:
    groups = hooks.get(entry.event)
    if not isinstance(groups, list):
        return False
    for group in groups:
        inner = group.get("hooks") if isinstance(group, dict) else None
        if isinstance(inner, list) and any(
            isinstance(hook, dict) and entry.file in str(hook.get("command", "")) for hook in inner
        ):
            return True
    return False


def _remove_one(groups: list[Any], entry: Mapping[str, Any]) -> bool:
    """Remove the first hook that runs the recorded command for the recorded matcher. A group left empty goes too."""
    for group in groups:
        inner = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(inner, list) or group.get("matcher") != entry.get("matcher"):
            continue
        for hook in inner:
            if isinstance(hook, dict) and hook.get("command") == entry["command"]:
                inner.remove(hook)
                if not inner:
                    groups.remove(group)
                return True
    return False


def _valid_group(group: Any) -> bool:
    return isinstance(group, dict) and ("hooks" not in group or isinstance(group["hooks"], list))


def _valid_entry(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    matcher = item.get("matcher")
    return (isinstance(item.get("event"), str) and isinstance(item.get("command"), str)
            and (matcher is None or isinstance(matcher, str)))
