#!/usr/bin/env python3
"""Single source of truth + mechanical apply for every published version surface (#292 Fase 1).

`scripts/release_manifest.py` already proves whether the published surfaces agree (`ready`/
`mismatches`); it does not, on its own, give a contributor a single mechanical command to bump
every surface together, which is what let the drift described in #292 happen in the first place
(`pyproject.toml` bumped, plugin/fallback left behind). This module is deliberately a thin
layer on top of `release_manifest.build_manifest()` — it does not re-implement version discovery,
it adds the missing `apply` mutation and re-exposes `check`/`manifest` under the exact CLI surface
the issue's Fase 1 specifies:

    python3 scripts/version_sync.py check
    python3 scripts/version_sync.py apply --version X.Y.Z
    python3 scripts/version_sync.py manifest --json

`check` fails (non-zero) on any drift, invalid version, or unreadable source — it is the local gate
a contributor (or a future CI job) runs before a release PR. `apply` rewrites every derived surface
in one shot so a version bump is always a single, complete, mechanical edit rather than a
multi-file hand-edit that can drift.

This intentionally does NOT implement the rest of #292 (build-once, OIDC/Trusted Publishing, SBOM,
provenance/attestation, signing, install smoke, environment-gated release) — those remain open.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release_manifest import SCHEMA as RELEASE_MANIFEST_SCHEMA  # noqa: E402
from release_manifest import VERSION_RE, build_manifest  # noqa: E402

SCHEMA = "simplicio.version-sync/v1"

# These surfaces are published or loaded independently from the Python package.  Keeping them
# in this one mechanical command prevents a new package release from leaving an older host
# adapter/marketplace descriptor behind (the exact failure mode tracked by #558).
ADAPTER_VERSION_FILES = (
    "adapters/claude/adapter.py",
    "adapters/codex/adapter.py",
    "adapters/cursor/adapter.py",
    "adapters/grok/adapter.py",
    "adapters/kiro/adapter.py",
    "adapters/vscode/adapter.py",
)
CLAUDE_DESCRIPTOR_FILES = (
    "adapters/claude/descriptor.json",
    "plugin/.claude-plugin/plugin.json",
)


class VersionSyncError(ValueError):
    """Raised when a version is malformed or a derived surface cannot be rewritten."""


def _validate_version(version: str) -> str:
    if not VERSION_RE.match(version or ""):
        raise VersionSyncError(
            f"version {version!r} is not a valid semantic MAJOR.MINOR.PATCH[-pre][+build]"
        )
    return version


def _apply_pyproject(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(?m)^(version\s*=\s*)["\'][^"\']+["\']',
        lambda m: f'{m.group(1)}"{version}"',
        text,
        count=1,
    )
    if count == 0:
        raise VersionSyncError(f"{path}: no `version = \"...\"` line found to rewrite")
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def _apply_json_version(path: Path, version: str) -> bool:
    # Rewrite only the `"version": "..."` line in place via regex rather than a full
    # json.loads/json.dumps round-trip: these files carry hand-authored formatting (2-space
    # indent, \uXXXX-escaped non-ASCII in .cursor-plugin/plugin.json) that a generic dumper would
    # silently reflow/re-escape, turning a one-field version bump into an unrelated whole-file
    # diff.
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if data.get("version") == version:
        return False
    new_text, count = re.subn(
        r'("version"\s*:\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{version}"',
        text,
        count=1,
    )
    if count == 0:
        raise VersionSyncError(f'{path}: no "version": "..." field found to rewrite')
    path.write_text(new_text, encoding="utf-8")
    return True


def _apply_source_fallback(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(__version__\s*=\s*)["\'][^"\']+["\']',
        lambda m: f'{m.group(1)}"{version}"',
        text,
    )
    if count == 0:
        raise VersionSyncError(f"{path}: no `__version__ = \"...\"` assignment found to rewrite")
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def _apply_stack_manifest_fallback(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(?m)^(\s*"simplicio-loop"\s*:\s*)"[^"]+"(,\s*)$',
        lambda match: f'{match.group(1)}"{version}"{match.group(2)}',
        text,
        count=1,
    )
    if count == 0:
        raise VersionSyncError(f"{path}: no simplicio-loop fallback floor found")
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def _apply_adapter_version(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(?m)^(ADAPTER_VERSION\s*=\s*)["\'][^"\']+["\']',
        lambda m: f'{m.group(1)}"{version}"',
        text,
        count=1,
    )
    if count == 0:
        raise VersionSyncError(f"{path}: no ADAPTER_VERSION assignment found to rewrite")
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def _claude_descriptor_digest(version: str) -> str:
    payload = {
        "schema": "simplicio.plugin-descriptor/v1",
        "name": "simplicio-loop",
        "host": "claude",
        "version": version,
        "entrypoint": "simplicio-loop=simplicio_loop.cli:main",
        "lifecycle": ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"],
        "hooks": {
            "SessionStart": "hooks/session_start.py",
            "UserPromptSubmit": "hooks/user_prompt_submit.py",
            "PreToolUse": "hooks/pre_tool_use.py",
            "PostToolUse": "hooks/post_tool_use.py",
            "Stop": "hooks/stop.py",
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _apply_claude_descriptor(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise VersionSyncError(f"{path}: descriptor must be a JSON object")
    desired_digest = _claude_descriptor_digest(version)
    if data.get("version") == version and data.get("digest") == desired_digest:
        return False
    new_text, version_count = re.subn(
        r'("version"\s*:\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{version}"',
        text,
        count=1,
    )
    if version_count == 0:
        raise VersionSyncError(f'{path}: no "version" field found to rewrite')
    new_text, digest_count = re.subn(
        r'("digest"\s*:\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{desired_digest}"',
        new_text,
        count=1,
    )
    if digest_count == 0:
        raise VersionSyncError(f'{path}: no "digest" field found to rewrite')
    path.write_text(new_text, encoding="utf-8")
    return True


def apply_version(repo: Path, version: str) -> dict:
    _validate_version(version)
    changed = []
    pyproject = repo / "pyproject.toml"
    if _apply_pyproject(pyproject, version):
        changed.append(str(pyproject.relative_to(repo)))
    cursor_plugin = repo / ".cursor-plugin" / "plugin.json"
    if cursor_plugin.exists() and _apply_json_version(cursor_plugin, version):
        changed.append(str(cursor_plugin.relative_to(repo)))
    fallback = repo / "simplicio_loop" / "__init__.py"
    if fallback.exists() and _apply_source_fallback(fallback, version):
        changed.append(str(fallback.relative_to(repo)))
    stack_manifest = repo / "simplicio_loop" / "stack_manifest.py"
    if stack_manifest.exists() and _apply_stack_manifest_fallback(stack_manifest, version):
        changed.append(str(stack_manifest.relative_to(repo)))
    for relative in ADAPTER_VERSION_FILES:
        path = repo / relative
        if path.exists() and _apply_adapter_version(path, version):
            changed.append(relative)
    for relative in CLAUDE_DESCRIPTOR_FILES:
        path = repo / relative
        if path.exists() and _apply_claude_descriptor(path, version):
            changed.append(relative)
    manifest = build_manifest(repo)
    return {
        "schema": SCHEMA,
        "action": "apply",
        "version": version,
        "changed_files": changed,
        "manifest": manifest,
        "ok": manifest["ready"],
    }


def check_version(repo: Path, *, tag: Optional[str] = None) -> dict:
    manifest = build_manifest(repo, tag=tag)
    return {
        "schema": SCHEMA,
        "action": "check",
        "manifest": manifest,
        "ok": manifest["ready"],
    }


def _cmd_check(args: argparse.Namespace) -> int:
    result = check_version(Path(args.repo).resolve(), tag=args.tag)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        manifest = result["manifest"]
        print(f"version-sync check: {'READY' if result['ok'] else 'BLOCKED'} "
              f"(canonical={manifest['canonical_version']!r})")
        for issue in manifest["errors"] + manifest["mismatches"]:
            print(f"- {issue}")
    return 0 if result["ok"] else 1


def _cmd_apply(args: argparse.Namespace) -> int:
    try:
        result = apply_version(Path(args.repo).resolve(), args.version)
    except VersionSyncError as exc:
        print(json.dumps({"schema": SCHEMA, "action": "apply", "ok": False, "error": str(exc)}))
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"version-sync apply: {'READY' if result['ok'] else 'BLOCKED'} "
              f"(version={result['version']!r})")
        for path in result["changed_files"]:
            print(f"- updated {path}")
    return 0 if result["ok"] else 1


def _cmd_manifest(args: argparse.Namespace) -> int:
    manifest = build_manifest(Path(args.repo).resolve(), tag=args.tag)
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    else:
        print(f"release manifest: {'READY' if manifest['ready'] else 'BLOCKED'}")
        for item in manifest["sources"]:
            print(f"- {item['name']}: {item.get('version') or 'missing'}")
    return 0 if manifest["ready"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="version_sync", description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    # --json and --repo are accepted both before AND after the subcommand (`version_sync.py
    # --json check` and `version_sync.py check --json` both work) — agents/CI scripts should not
    # have to remember flag ordering relative to the subcommand.
    p_check = sub.add_parser("check", help="fail if any published surface disagrees with pyproject.toml")
    p_check.add_argument("--tag", default=None)
    p_check.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_check.add_argument("--repo", default=argparse.SUPPRESS)
    p_check.set_defaults(func=_cmd_check)

    p_apply = sub.add_parser("apply", help="rewrite every derived surface to one version, in one shot")
    p_apply.add_argument("--version", required=True)
    p_apply.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_apply.add_argument("--repo", default=argparse.SUPPRESS)
    p_apply.set_defaults(func=_cmd_apply)

    p_manifest = sub.add_parser("manifest", help="print the release manifest (same shape as release_manifest.py)")
    p_manifest.add_argument("--tag", default=None)
    p_manifest.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_manifest.add_argument("--repo", default=argparse.SUPPRESS)
    p_manifest.set_defaults(func=_cmd_manifest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
