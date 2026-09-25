"""Derive a versioned capability manifest from the real argparse surface.

Issue: callers (notably a host loop) used to discover Dev CLI's command
surface by shelling out to ``--help`` / ``edit --help`` / ``--version``
*per attempt* -- three subprocess spawns and a parser build every time, with
no way to cache the answer across a run. ``simplicio-dev-cli capabilities
--json`` replaces that with one static, versioned document; this module is
the *single* place that walks argparse into that document shape, so the
packaged JSON (``simplicio/data/capabilities.json``) and the runtime fast
path can never drift from the real parser -- ``tests/python/
test_capabilities_manifest.py`` regenerates from ``_build_parser()`` and
diffs byte-for-byte against the packaged file.

This module is imported ONLY by the generator script and the drift test --
never by the runtime fast path (``simplicio/capabilities.py``), which reads
the packaged JSON directly so the common case never pays argparse-build or
``simplicio.cli`` import cost.
"""

from __future__ import annotations

import argparse
from typing import Any

SCHEMA = "simplicio.dev-cli.capabilities/v1"

# The one thing argparse cannot tell us: the minimal host plan shape that
# `edit --compile` freezes into a full plan. Kept here (not re-derived from
# a help string) so the manifest states it as structured data a caller can
# consume without parsing prose.
MINIMAL_HOST_PLAN_EXAMPLE: dict[str, Any] = {
    "operations": [{"path": "<repo-relative path>", "find": "<exact unique text>", "replace": "<new text>"}]
}
COMPILED_EDIT_PLAN_SCHEMA = "simplicio.dev-cli.edit-plan/v1"


def _action_flags(action: argparse.Action) -> list[str]:
    return sorted(action.option_strings) if action.option_strings else []


def _walk_parser(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Return {flags: [...], subcommands: {name: {...recursive...}}} for one parser level."""
    flags: list[str] = []
    subcommands: dict[str, Any] = {}
    for action in parser._actions:  # noqa: SLF001 - argparse has no public walk API
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for name, subparser in action.choices.items():
                subcommands[name] = _walk_parser(subparser)
                subcommands[name]["help"] = _sub_help(action, name)
            continue
        for flag in _action_flags(action):
            if flag not in flags:
                flags.append(flag)
    flags.sort()
    return {"flags": flags, "subcommands": subcommands}


def _sub_help(action: argparse._SubParsersAction, name: str) -> str:  # noqa: SLF001
    for sub_action in action._choices_actions:  # noqa: SLF001
        if sub_action.dest == name:
            return sub_action.help or ""
    return ""


def build_capabilities_manifest(
    parser: argparse.ArgumentParser,
    *,
    package_name: str,
    package_version: str,
    adapter_command: str,
    python_adapter_command: str,
) -> dict[str, Any]:
    """Build the full manifest dict from a live top-level parser.

    Deterministic and side-effect free: same parser in, same dict out, so the
    packaged JSON and a freshly-built parser can be diffed for drift.
    """
    tree = _walk_parser(parser)
    return {
        "schema": SCHEMA,
        "package": {"name": package_name, "version": package_version},
        "entrypoints": {
            "adapter": adapter_command,
            "python_adapter": python_adapter_command,
        },
        "commands": tree["subcommands"],
        "top_level_flags": tree["flags"],
        "edit_plan_formats": {
            "minimal_host_plan": MINIMAL_HOST_PLAN_EXAMPLE,
            "compiled_plan_schema": COMPILED_EDIT_PLAN_SCHEMA,
        },
    }
