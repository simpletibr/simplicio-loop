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
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ..runtime_bridge import delegated_command, record_delegation
from ..standalone_migration import (
    effect_unknown_details,
    effect_unknown_pending,
    emit_mutation_route,
    mutation_receipt,
    record_effect_unknown,
    standalone_policy_for_root,
)
from ._shared import read_text_source

CLI_PROG = "simplicio-py"
RUNTIME_EDIT_TIMEOUT_S = 30.0


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
        # ``edit`` is the standalone local executor.  Runtime-backed callers
        # use the explicit delegation path below; never let an installed
        # Runtime binary silently change standalone ownership.
        result = execute_plan_json(plan_text, root=a.root, apply=a.apply, allow_native=False)
        result["mutation_receipt"] = mutation_receipt("standalone", entrypoint="edit", policy=policy)
        if a.apply:
            emit_mutation_route(
                root=a.root,
                entrypoint="edit",
                route="standalone",
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
    binary = shutil.which("simplicio")
    if os.environ.get("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT"):
        return None
    return binary


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


def _run_atomic_native_create_plans(
    runtime: str, native_plans: list[dict], a: argparse.Namespace
) -> dict[str, Any]:
    """Apply a translated create-file batch through one Runtime transaction."""
    from ..mechanical_edit import MechanicalEditError, _safe_path

    root = Path(a.root).resolve()
    transaction_files: list[dict[str, Any]] = []
    for native_plan in native_plans:
        relative = str(native_plan["file"])
        try:
            target = _safe_path(root, relative)
        except MechanicalEditError:
            return {
                "schema": "simplicio.mechanical-edit-result/v1",
                "status": "refused",
                "applied": False,
                "noop": False,
                "operation_count": 0,
                "files": [],
                "errors": [{"code": "unsafe_path", "message": f"path escapes root: {relative}"}],
                "mutation_receipt": mutation_receipt("blocked", entrypoint="edit"),
            }
        if target.exists():
            return {
                "schema": "simplicio.mechanical-edit-result/v1",
                "status": "refused",
                "applied": False,
                "noop": False,
                "operation_count": 0,
                "files": [],
                "errors": [
                    {"code": "file_exists", "message": f"{relative} already exists", "path": relative}
                ],
                "mutation_receipt": mutation_receipt("blocked", entrypoint="edit"),
            }
        operation = native_plan["operations"][0]
        transaction_files.append(
            {
                "file": str(target),
                "operations": [{"op": "create", "text": str(operation.get("text", ""))}],
            }
        )

    try:
        transaction_text = json.dumps({"files": transaction_files})
        cmd = delegated_command(runtime, ["cross-file-txn", "--plan", transaction_text, "--json"])
        completed = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            cwd=root,
            text=True,
            capture_output=True,
            shell=False,
            timeout=RUNTIME_EDIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        record_effect_unknown(a.root)
        return {
            "schema": "simplicio.mechanical-edit-result/v1",
            "status": "effect_unknown",
            "applied": False,
            "noop": False,
            "operation_count": len(native_plans),
            "files": [],
            "errors": [{"code": "native_delegation_failed", "message": str(exc)}],
            "mutation_receipt": mutation_receipt(
                "runtime_effect_api", entrypoint="edit", runtime_gate_verified=False
            ),
        }

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    result_files = payload.get("files") if isinstance(payload, dict) else None
    actual_files = (
        {str(item.get("file")) for item in result_files if isinstance(item, dict)}
        if isinstance(result_files, list)
        else set()
    )
    expected_files = {str(item["file"]) for item in transaction_files}
    if (
        completed.returncode != 0
        or not isinstance(payload, dict)
        or payload.get("status") != "committed"
        or payload.get("file_count") != len(transaction_files)
        or actual_files != expected_files
    ):
        record_effect_unknown(a.root)
        message = (completed.stderr or completed.stdout).strip()
        return {
            "schema": "simplicio.mechanical-edit-result/v1",
            "status": "effect_unknown",
            "applied": False,
            "noop": False,
            "operation_count": len(native_plans),
            "files": [],
            "errors": [{"code": "native_delegation_failed", "message": message}],
            "mutation_receipt": mutation_receipt(
                "runtime_effect_api", entrypoint="edit", runtime_gate_verified=False
            ),
        }

    return {
        "schema": "simplicio.mechanical-edit-result/v1",
        "status": "ok",
        "applied": True,
        "noop": False,
        "operation_count": len(native_plans),
        "files": [
            {"path": native_plan["file"], "before_sha256": None, "after_sha256": None}
            for native_plan in native_plans
        ],
        "errors": [],
        "mutation_receipt": mutation_receipt(
            "runtime_effect_api", entrypoint="edit", runtime_gate_verified=True
        ),
    }


def _run_native_edit_plans(
    runtime: str,
    native_plans: list[dict],
    a: argparse.Namespace,
    *,
    stdin_text: str | None = None,
    plan_arg: str = "-",
    plan_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Delegate validated plans while retaining exact stdin and causal proof."""
    from ..mechanical_edit import MechanicalEditError, _safe_path

    files: list[dict] = []
    errors: list[dict] = []
    root = Path(a.root).resolve()
    for native_plan in native_plans:
        paths = [native_plan.get("file")] if "file" in native_plan else []
        for operation in native_plan.get("operations", []):
            if isinstance(operation, dict):
                paths.extend(operation.get(key) for key in ("path", "dest") if key in operation)
        for relative in paths:
            try:
                if not isinstance(relative, str):
                    raise MechanicalEditError("unsafe_path", "native plan path must be a string")
                _safe_path(root, relative)
            except MechanicalEditError as exc:
                return {
                    "schema": "simplicio.mechanical-edit-result/v1",
                    "status": "refused",
                    "applied": False,
                    "noop": False,
                    "operation_count": 0,
                    "files": [],
                    "errors": [exc.to_dict()],
                    "mutation_receipt": mutation_receipt("blocked", entrypoint="edit"),
                }
    if a.apply and len(native_plans) > 1:
        return _run_atomic_native_create_plans(runtime, native_plans, a)
    for _index, native_plan in enumerate(native_plans):
        current_plan_arg = plan_arg if len(native_plans) == 1 else "-"
        cmd = delegated_command(runtime, ["edit", "--plan", current_plan_arg, "--repo", a.root, "--json"])
        if not a.apply:
            cmd.append("--dry-run")
        input_text = (
            stdin_text
            if stdin_text is not None
            else (json.dumps(native_plan) if current_plan_arg == "-" else None)
        )
        run_kwargs: dict[str, Any] = {
            "cwd": root,
            "text": True,
            "capture_output": True,
            "shell": False,
            "timeout": RUNTIME_EDIT_TIMEOUT_S,
        }
        if input_text is None:
            run_kwargs["stdin"] = subprocess.DEVNULL
        else:
            run_kwargs["input"] = input_text
            # ``input=`` owns the child's stdin handle. Supplying stdin=PIPE
            # as well is rejected by subprocess.run and obscures the exact
            # plan bytes being delegated.
        try:
            completed = subprocess.run(cmd, **run_kwargs)
        except subprocess.TimeoutExpired:
            errors.append(
                {
                    "code": "native_delegation_timeout",
                    "message": f"Runtime edit exceeded {RUNTIME_EDIT_TIMEOUT_S:g}s",
                    "path": native_plan.get("file"),
                }
            )
            continue
        except OSError as exc:
            errors.append(
                {"code": "native_delegation_failed", "message": str(exc), "path": native_plan.get("file")}
            )
            continue
        if completed.returncode != 0:
            errors.append(
                {
                    "code": "native_delegation_failed",
                    "message": getattr(completed, "stderr", "").strip()
                    or getattr(completed, "stdout", "").strip(),
                    "path": native_plan.get("file"),
                }
            )
            continue
        try:
            result = json.loads(getattr(completed, "stdout", ""))
        except json.JSONDecodeError:
            errors.append(
                {
                    "code": "native_delegation_malformed_output",
                    "message": getattr(completed, "stdout", "").strip(),
                    "path": native_plan.get("file"),
                }
            )
            continue
        if not isinstance(result, dict) or result.get("status") != "ok":
            errors.append(
                {
                    "code": "native_delegation_invalid_result",
                    "message": "Runtime returned no successful edit proof",
                    "path": native_plan.get("file"),
                }
            )
            continue
        files.append(
            {
                "path": native_plan.get("file"),
                "before_sha256": result.get("before_sha256"),
                "after_sha256": result.get("after_sha256"),
            }
        )
    if errors and a.apply:
        context = effect_unknown_details(
            a.root,
            plan=plan_context,
            native_plans=native_plans,
            files=files,
        )
        record_effect_unknown(a.root, context)
    return {
        "schema": "simplicio.mechanical-edit-result/v1",
        "status": "ok" if not errors else ("effect_unknown" if a.apply else "error"),
        "applied": bool(a.apply) and not errors,
        "noop": False,
        "operation_count": len(native_plans),
        "files": files,
        "errors": errors,
        "mutation_receipt": mutation_receipt(
            "runtime_effect_api", entrypoint="edit", runtime_gate_verified=not errors
        ),
    }


def _invalid_delegated_plan(plan: Any) -> list[dict[str, Any]]:
    if not isinstance(plan, dict):
        return [{"code": "invalid_json", "message": "plan root must be a JSON object"}]
    if "file" in plan:
        file_name = plan.get("file")
        operations = plan.get("operations")
        portable_path = PurePosixPath(file_name.replace("\\", "/")) if isinstance(file_name, str) else None
        if (
            not isinstance(file_name, str)
            or not file_name.strip()
            or Path(file_name).is_absolute()
            or PureWindowsPath(file_name).is_absolute()
            or (portable_path is not None and (portable_path.is_absolute() or ".." in portable_path.parts))
        ):
            return [{"code": "invalid_plan", "message": "Runtime plan file must be a safe relative path"}]
        if not isinstance(operations, list) or not operations:
            return [{"code": "invalid_plan", "message": "Runtime plan operations must be a non-empty list"}]
        if not all(isinstance(item, dict) and isinstance(item.get("op"), str) for item in operations):
            return [{"code": "invalid_plan", "message": "Runtime plan operations must be objects with an op"}]
        return []
    if plan.get("schema") != "simplicio.mechanical-edit/v1":
        return [{"code": "missing_schema", "message": "plan schema is unsupported"}]
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        return [{"code": "invalid_plan", "message": "mechanical-edit operations must be a non-empty list"}]
    return (
        []
        if all(isinstance(item, dict) and isinstance(item.get("op"), str) for item in operations)
        else [{"code": "invalid_plan", "message": "mechanical-edit operations must be objects with an op"}]
    )


def _print_edit_result(result: dict[str, Any], a: argparse.Namespace) -> int:
    if a.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"{result['status']}: applied={result['applied']} noop={result['noop']}")
        for error in result.get("errors", []):
            print(f"error: {error.get('code')}: {error.get('message')}", file=sys.stderr)
    return 0 if result["status"] == "ok" else 1


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
        return _print_edit_result(blocked_result, a)
    try:
        plan_text = read_text_source(a.plan)
        plan = json.loads(plan_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result = {
            "schema": "simplicio.mechanical-edit-result/v1",
            "status": "refused",
            "applied": False,
            "noop": False,
            "operation_count": 0,
            "files": [],
            "errors": [{"code": "invalid_plan", "message": str(exc)}],
            "mutation_receipt": mutation_receipt("blocked", entrypoint="edit"),
        }
        emit_mutation_route(
            root=a.root, entrypoint="edit", route="blocked", reason_code="PLAN_VALIDATION_FAILED"
        )
        return _print_edit_result(result, a)
    validation_errors = _invalid_delegated_plan(plan)
    if validation_errors:
        result = {
            "schema": "simplicio.mechanical-edit-result/v1",
            "status": "refused",
            "applied": False,
            "noop": False,
            "operation_count": 0,
            "files": [],
            "errors": validation_errors,
            "mutation_receipt": mutation_receipt("blocked", entrypoint="edit"),
        }
        emit_mutation_route(
            root=a.root, entrypoint="edit", route="blocked", reason_code="PLAN_VALIDATION_FAILED"
        )
        return _print_edit_result(result, a)

    runtime = None if a.no_runtime else _runtime_edit_binary()
    if runtime:
        native_plans = None
        if isinstance(plan, dict) and "file" not in plan:
            native_plans = _translate_create_file_plan_for_native(plan)
        if native_plans is not None:
            result = _run_native_edit_plans(runtime, native_plans, a, plan_context=plan)
            record_delegation("edit", "native", root=a.root, reason="translated:create_file")
            if a.apply:
                emit_mutation_route(
                    root=a.root,
                    entrypoint="edit",
                    route="runtime_effect_api",
                    reason_code="RUNTIME_NATIVE_EDIT",
                )
            return _print_edit_result(result, a)
        result = _run_native_edit_plans(
            runtime,
            [plan],
            a,
            stdin_text=plan_text if a.plan == "-" else None,
            plan_arg="-" if a.plan == "-" else a.plan,
            plan_context=plan,
        )
        record_delegation("edit", "native", root=a.root)
        if a.apply:
            emit_mutation_route(
                root=a.root, entrypoint="edit", route="runtime_effect_api", reason_code="RUNTIME_NATIVE_EDIT"
            )
        return _print_edit_result(result, a)
    if a.no_runtime:
        reason = "user-forced-python (--no-runtime)"
    elif os.environ.get("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT"):
        reason = "user-forced-python (SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT)"
    else:
        reason = "binary-not-found"
    route = "python-forced" if reason.startswith("user-forced-python") else "python-fallback"
    record_delegation("edit", route, root=a.root, reason=reason)
    return run_mechanical_edit(a)
