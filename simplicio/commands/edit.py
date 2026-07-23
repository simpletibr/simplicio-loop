"""``simplicio-py mechanical-edit`` / ``simplicio-py edit``.

Extracted from `cli.py`'s `_run_mechanical_edit_command`/`_run_edit_command`
(issue #103); behavior unchanged. ``edit`` delegates to the native
``simplicio`` Rust binary when available, falling back to
``run_mechanical_edit`` (the pure-Python implementation) otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import Any

from ..runtime_bridge import delegated_command, record_delegation
from ..standalone_migration import (
    effect_unknown_pending,
    emit_mutation_route,
    mutation_receipt,
    record_effect_unknown,
    standalone_policy_for_root,
)
from ._shared import read_text_source

CLI_PROG = "simplicio-py"


def run_mechanical_edit(a: argparse.Namespace) -> int:
    from ..mechanical_edit import execute_plan_json

    try:
        plan_text = read_text_source(a.plan)
    except OSError as exc:
        print(f"{CLI_PROG} mechanical-edit: {exc}", file=sys.stderr)
        return 2
    policy = standalone_policy_for_root(a.root)
    result: dict[str, Any]
    if a.apply and not policy.write_allowed:
        result = {
            "schema": "simplicio.mechanical-edit-result/v1",
            "status": "refused",
            "applied": False,
            "noop": False,
            "operation_count": 0,
            "files": [],
            "errors": [
                {
                    "code": policy.reason_code,
                    "message": "local mutation is disabled by standalone migration policy",
                }
            ],
            "mutation_receipt": mutation_receipt("blocked", entrypoint="edit", policy=policy),
        }
        emit_mutation_route(
            root=a.root,
            entrypoint="edit",
            route="blocked",
            reason_code=policy.reason_code,
            policy=policy,
        )
    else:
        result = execute_plan_json(plan_text, root=a.root, apply=a.apply)
        result["mutation_receipt"] = mutation_receipt("legacy_standalone", entrypoint="edit", policy=policy)
        if a.apply:
            emit_mutation_route(
                root=a.root,
                entrypoint="edit",
                route="legacy_standalone",
                reason_code=policy.reason_code,
                policy=policy,
            )
    if a.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"{result['status']}: applied={result['applied']} noop={result['noop']}")
        if result.get("planned_diff"):
            print(result["planned_diff"])
        for error in result.get("errors", []):
            print(f"error: {error.get('code')}: {error.get('message')}", file=sys.stderr)
    return 0 if result["status"] == "ok" else 1


def _runtime_edit_binary() -> str | None:
    if os.environ.get("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT"):
        return None
    return shutil.which("simplicio")


# The native `simplicio edit` binary and this package's own Python
# mechanical-edit implementation (`../mechanical_edit.py`) speak two
# DIFFERENT operation vocabularies over two different plan shapes:
#
#   - dev-cli's own `simplicio.mechanical-edit/v1` plans are multi-file
#     (`{"operations": [{"op": ..., "path": ...}, ...]}`) with ops
#     `replace_range`/`insert_before`/`insert_after`/`delete_range`/
#     `create_file`/`json_patch`/`ast_patch`/`move_file`/`delete_file`.
#   - the native binary's plans are single-file
#     (`{"file": "...", "operations": [{"op": ...}, ...]}`) with ops
#     `replace_all`/`insert_before`/`insert_after`/`replace_line`/
#     `delete_line`/`append`/`prepend` (see `src/cross_file_txn.rs` in
#     simplicio-runtime) -- no `create_file` at all; a nonexistent target
#     file is simply created by the first `append`/`prepend`.
#
# Handing a dev-cli-shaped plan to the native binary unchanged fails
# outright ("edit plan must specify a target file") for any plan with more
# than one file, and silently means something different even for a single
# file since the op names don't universally overlap. This translator
# handles ONLY the one case that's unambiguous and safe: a plan whose every
# operation is `create_file` (the common "write a brand-new file" case) --
# each becomes a single-file native plan with one `append` op against a
# fresh path, which the native binary auto-creates. Any other operation
# type is left untranslated on purpose (never guessed at) so the caller
# falls back to the Python implementation instead of risking a silent
# mistranslation.
def _translate_create_file_plan_for_native(plan: dict) -> list[dict] | None:
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        return None
    native_plans = []
    for op in operations:
        if not isinstance(op, dict) or op.get("op") != "create_file":
            return None
        path = op.get("path")
        if not isinstance(path, str) or not path:
            return None
        native_plans.append({"file": path, "operations": [{"op": "append", "text": str(op.get("text", ""))}]})
    return native_plans


def _run_native_edit_plans(runtime: str, native_plans: list[dict], a: argparse.Namespace) -> dict[str, Any]:
    """Delegate one or more single-file native plans, one subprocess call
    per file (the native binary only ever addresses one file per `--plan`),
    and combine the results into the same shape `run_mechanical_edit`
    returns (`applied`/`files`/`errors`/`operation_count`) so callers see a
    consistent result regardless of which path answered."""
    files: list[dict] = []
    errors: list[dict] = []
    if a.apply and len(native_plans) > 1:
        return {
            "schema": "simplicio.mechanical-edit-result/v1",
            "status": "refused",
            "applied": False,
            "noop": False,
            "operation_count": 0,
            "files": [],
            "errors": [
                {
                    "code": "RUNTIME_ATOMIC_MULTI_FILE_REQUIRED",
                    "message": "multi-file apply requires one atomic Runtime transaction",
                }
            ],
            "mutation_receipt": mutation_receipt("blocked", entrypoint="edit"),
        }
    for native_plan in native_plans:
        cmd = delegated_command(runtime, ["edit", "--plan", "-", "--repo", a.root, "--json"])
        if not a.apply:
            cmd.append("--dry-run")
        completed = subprocess.run(cmd, input=json.dumps(native_plan), text=True, capture_output=True)
        if completed.returncode != 0:
            errors.append(
                {
                    "code": "native_delegation_failed",
                    "message": completed.stderr.strip() or completed.stdout.strip(),
                    "path": native_plan["file"],
                }
            )
            continue
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            errors.append(
                {
                    "code": "native_delegation_malformed_output",
                    "message": completed.stdout.strip(),
                    "path": native_plan["file"],
                }
            )
            continue
        files.append(
            {
                "path": native_plan["file"],
                "before_sha256": result.get("before_sha256"),
                "after_sha256": result.get("after_sha256"),
            }
        )
    if errors and a.apply:
        record_effect_unknown(a.root)
    return {
        "schema": "simplicio.mechanical-edit-result/v1",
        "status": "ok" if not errors else ("effect_unknown" if a.apply else "error"),
        "applied": bool(a.apply) and not errors,
        "noop": False,
        "operation_count": len(native_plans),
        "files": files,
        "errors": errors,
        "mutation_receipt": mutation_receipt("runtime_effect_api", entrypoint="edit"),
    }


def run_edit(a: argparse.Namespace) -> int:
    if a.apply and effect_unknown_pending(a.root):
        policy = standalone_policy_for_root(a.root)
        blocked_result = {
            "schema": "simplicio.mechanical-edit-result/v1",
            "status": "refused",
            "applied": False,
            "noop": False,
            "operation_count": 0,
            "files": [],
            "errors": [
                {
                    "code": "EFFECT_UNKNOWN_RECONCILIATION_REQUIRED",
                    "message": "reconcile the prior Runtime effect before another mutation",
                }
            ],
            "mutation_receipt": mutation_receipt("blocked", entrypoint="edit", policy=policy),
        }
        emit_mutation_route(
            root=a.root,
            entrypoint="edit",
            route="blocked",
            reason_code="EFFECT_UNKNOWN_RECONCILIATION_REQUIRED",
            policy=policy,
        )
        if a.json:
            print(json.dumps(blocked_result, sort_keys=True))
        else:
            print(f"{blocked_result['status']}: applied=False noop=False")
            print("error: EFFECT_UNKNOWN_RECONCILIATION_REQUIRED", file=sys.stderr)
        return 1
    runtime = None if a.no_runtime else _runtime_edit_binary()
    if runtime:
        try:
            plan_text = read_text_source(a.plan)
            plan = json.loads(plan_text)
        except (OSError, json.JSONDecodeError):
            plan = None
        native_plans = None
        if isinstance(plan, dict) and "file" not in plan:
            native_plans = _translate_create_file_plan_for_native(plan)
        if native_plans is not None:
            result = _run_native_edit_plans(runtime, native_plans, a)
            record_delegation("edit", "native", root=a.root, reason="translated:create_file")
            if a.apply:
                emit_mutation_route(
                    root=a.root,
                    entrypoint="edit",
                    route="runtime_effect_api",
                    reason_code="RUNTIME_NATIVE_EDIT",
                )
            if a.json:
                print(json.dumps(result, sort_keys=True))
            else:
                print(f"{result['status']}: applied={result['applied']} noop={result['noop']}")
                for error in result.get("errors", []):
                    print(f"error: {error.get('code')}: {error.get('message')}", file=sys.stderr)
            return 0 if result["status"] == "ok" else 1

        cmd = delegated_command(runtime, ["edit", "--plan", a.plan, "--repo", a.root])
        if a.json:
            cmd.append("--json")
        if not a.apply:
            cmd.append("--dry-run")
        try:
            plan_stdin = read_text_source("-") if a.plan == "-" else None
            completed = subprocess.run(cmd, input=plan_stdin, text=True)
        except OSError as exc:
            print(
                f"{CLI_PROG} edit: runtime delegation failed ({exc}); using local fallback", file=sys.stderr
            )
            record_delegation("edit", "python-fallback", root=a.root, reason=f"delegation-error: {exc}")
        else:
            record_delegation("edit", "native", root=a.root)
            if a.apply and completed.returncode != 0:
                record_effect_unknown(a.root)
            if a.apply:
                emit_mutation_route(
                    root=a.root,
                    entrypoint="edit",
                    route="runtime_effect_api",
                    reason_code="RUNTIME_NATIVE_EDIT",
                )
            return completed.returncode
    else:
        if a.no_runtime:
            reason = "user-forced-python (--no-runtime)"
        elif os.environ.get("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT"):
            reason = "user-forced-python (SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT)"
        else:
            reason = "binary-not-found"
        route = "python-forced" if reason.startswith("user-forced-python") else "python-fallback"
        record_delegation("edit", route, root=a.root, reason=reason)
    return run_mechanical_edit(a)
