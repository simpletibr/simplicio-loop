#!/usr/bin/env python3
"""Pure planner for the simplicio-loop installer (#293, scoped first slice).

`build_plan()` has NO side effects: no filesystem writes, no network, no
subprocess calls. Given the same `(runtime, mode, scope, target, flags)` it
returns the same `simplicio.install-transaction/v1` plan every time, so a
`--dry-run` install can show the user exactly what would happen before any
mutation runs.

This intentionally does not implement the full #293 scope (rollback, hash-based
idempotency, full effect inventory of install_services.py / setup scripts). It
is one concrete, testable step of "separar planner e executor": the planner
half, wired to `install_lib.py --dry-run`.
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Dict, List, Sequence

SCHEMA = "simplicio.install-transaction/v1"

MODES = ("minimal", "runtime", "full-stack", "ci", "dry-run", "rollback")
SCOPES = ("project", "user", "system")

# The 7 skills the installer actually copies today (install_lib.py SKILLS) — kept as a
# local constant rather than importing install_lib to keep the planner import-light and
# side-effect-free even if install_lib.py grows heavier module-level behavior later.
SKILLS = ["simplicio-tasks", "simplicio-loop", "simplicio-orient",
          "simplicio-review", "simplicio-compress", "simplicio-learn",
          "simplicio-autoresearch"]

# Runtimes whose entry file lives outside .claude/ and therefore counts as a "create or
# update" file effect distinct from the skills copy. Mirrors `install_lib.RUNTIMES` (a test
# keeps the two equal); it is a literal so this planner stays import-light.
ENTRY_FILES = {
    "codex": "AGENTS.md",
    "grok": "AGENTS.md",
    "vscode": ".github/copilot-instructions.md",
    "antigravity": "AGENTS.md",
    "kiro": ".kiro/steering/simplicio-loop.md",
    "opencode": "AGENTS.md",
    "gemini": "GEMINI.md",
    "aider": "CONVENTIONS.md",
    "orca": "AGENTS.md",
    "github-copilot": ".github/copilot-instructions.md",
    "mimo-code": "AGENTS.md",
    "amp": "AGENTS.md",
    "openclaude": "AGENTS.md",
    "pi": "AGENTS.md",
    "oh-my-pi": "AGENTS.md",
    "devin": "AGENTS.md",
    "goose": "AGENTS.md",
    "auggie": "AGENTS.md",
    "autohand": "AGENTS.md",
    "charm": "AGENTS.md",
    "cline": "AGENTS.md",
    "codebuff": "AGENTS.md",
    "command-code": "AGENTS.md",
    "continue": ".continue/rules/simplicio-loop.md",
    "droid": "AGENTS.md",
    "kilocode": "AGENTS.md",
    "kimi": "AGENTS.md",
    "mistral-vibe": "AGENTS.md",
    "qwen": "QWEN.md",
    "rovo-dev": "AGENTS.md",
}


def _transaction_id(runtime: str, mode: str, scope: str, target: str) -> str:
    """Deterministic id: same inputs -> same id, so a dry-run plan and the eventual
    applied transaction can be correlated by re-deriving it, without persisting state."""
    digest = hashlib.sha256(
        ("|".join([runtime, mode, scope, os.path.normpath(target)])).encode("utf-8")
    ).hexdigest()[:16]
    return "install-%s-%s-%s" % (mode, scope, digest)


def _file_effects(target: str, is_global: bool, runtime: str) -> List[Dict[str, Any]]:
    effects: List[Dict[str, Any]] = []
    skills_root = os.path.join(target, ".claude", "skills")
    for skill in SKILLS:
        path = os.path.join(skills_root, skill)
        action = "update" if os.path.isdir(path) else "create"
        effects.append({"path": path, "action": action, "reversible": True,
                        "hash_before": None, "hash_after": None})
    hooks_dst = os.path.join(target, ".claude", "hooks") if is_global else os.path.join(target, "hooks")
    effects.append({"path": hooks_dst, "action": "update" if os.path.isdir(hooks_dst) else "create",
                    "reversible": True, "hash_before": None, "hash_after": None})
    entry_rel = ENTRY_FILES.get(runtime)
    if entry_rel:
        entry_path = os.path.join(target, entry_rel)
        effects.append({"path": entry_path, "action": "update" if os.path.exists(entry_path) else "create",
                        "reversible": True, "hash_before": None, "hash_after": None})
    if runtime == "claude":
        settings_path = os.path.join(target, ".claude", "settings.json")
        effects.append({"path": settings_path,
                        "action": "update" if os.path.exists(settings_path) else "create",
                        "reversible": True, "hash_before": None, "hash_after": None})
    return effects


def _permissions_required(mode: str, scope: str, allow_break_system_packages: bool,
                          with_service: bool, with_proxy: bool) -> List[str]:
    perms: List[str] = []
    if scope in ("user", "system") or mode == "full-stack":
        perms.append("global_package")
    if allow_break_system_packages:
        perms.append("break_system_packages")
    if scope != "project":
        perms.append("path_write")
        perms.append("symlink")
    if with_service or mode == "full-stack":
        perms.append("service")
    if with_proxy or mode == "full-stack":
        perms.append("proxy")
    return perms


def build_plan(runtime: str, *, mode: str = "minimal", scope: str = "project",
               target: str, requested_version: str = "", resolved_version: str = "",
               allow_break_system_packages: bool = False, with_service: bool = False,
               with_proxy: bool = False, commands: Sequence[str] = ()) -> Dict[str, Any]:
    """Return a `simplicio.install-transaction/v1` plan. Pure: no I/O side effects,
    though it MAY stat the target directory to classify create-vs-update (read-only)."""
    if mode not in MODES:
        raise ValueError("unknown mode: %r (choices: %s)" % (mode, ", ".join(MODES)))
    if scope not in SCOPES:
        raise ValueError("unknown scope: %r (choices: %s)" % (scope, ", ".join(SCOPES)))
    if not str(target).strip():
        raise ValueError("target is required")
    is_global = scope != "project"
    files = _file_effects(target, is_global, runtime)
    permissions = _permissions_required(mode, scope, allow_break_system_packages,
                                        with_service, with_proxy)
    # #293 step 2.4: "impedir que --global, serviço ou proxy sejam inferidos silenciosamente" —
    # choosing mode="full-stack" must NOT by itself grant the service/proxy consent it requires.
    # full-stack only reaches PLANNED when the caller ALSO passes the same explicit
    # --with-service/--with-proxy flags that gate a plain service/proxy request in any other
    # mode; the mode name alone is never treated as approval.
    blocked_reasons: List[str] = []
    if "break_system_packages" in permissions and not allow_break_system_packages:
        blocked_reasons.append("break_system_packages")
    if mode == "full-stack" and not (with_service and with_proxy):
        blocked_reasons.append("full_stack_confirmation")
    status = "BLOCKED" if blocked_reasons else "PLANNED"
    plan = {
        "schema": SCHEMA,
        "transaction_id": _transaction_id(runtime, mode, scope, target),
        "mode": mode,
        "scope": scope,
        "runtime": runtime,
        "target": os.path.normpath(target),
        "requested_version": requested_version,
        "resolved_version": resolved_version,
        # #293 mode `ci`: "instalação não interativa ... com versões fixadas" — vs `minimal`'s
        # potentially-floating `pip install -U`. This field is purely a function of `mode`
        # (keeping this planner side-effect-free, per its own module docstring); the actual
        # version RESOLUTION (network/local pip query) happens in
        # `install_lib.ensure_operators(pin_versions=...)`, not here.
        "version_pinning": "pinned" if mode == "ci" else "floating",
        "files": files,
        "symlinks": [],
        "path_additions": [],
        "services": [{"name": "capture-proxy", "action": "install"}] if (with_service or mode == "full-stack") else [],
        "env_vars": [],
        "commands": list(commands),
        "permissions_required": permissions,
        "backup_path": None,
        "status": status,
        "blocked_reasons": blocked_reasons,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    plan["receipt_hash"] = hashlib.sha256(
        repr(sorted((k, v) for k, v in plan.items() if k not in ("generated_at", "receipt_hash"))).encode("utf-8")
    ).hexdigest()
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Print a simplicio.install-transaction/v1 plan (no mutation).")
    parser.add_argument("runtime")
    parser.add_argument("--mode", default="minimal", choices=MODES)
    parser.add_argument("--scope", default="project", choices=SCOPES)
    parser.add_argument("--target", required=True)
    parser.add_argument("--allow-break-system-packages", action="store_true")
    parser.add_argument("--with-service", action="store_true")
    parser.add_argument("--with-proxy", action="store_true")
    args = parser.parse_args(argv)
    plan = build_plan(args.runtime, mode=args.mode, scope=args.scope, target=args.target,
                      allow_break_system_packages=args.allow_break_system_packages,
                      with_service=args.with_service, with_proxy=args.with_proxy)
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0 if plan["status"] != "BLOCKED" else 3


if __name__ == "__main__":
    import sys
    sys.exit(main())
