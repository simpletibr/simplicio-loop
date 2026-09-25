"""``simplicio-py mechanical-edit`` / ``simplicio-py edit``.

Extracted from `cli.py`'s `_run_mechanical_edit_command`/`_run_edit_command`
(issue #103). Legacy plans retain their established Runtime delegation
behavior. Versioned ``simplicio.dev-cli.edit-plan/v1`` plans always use the
Dev CLI-owned deterministic kernel so the native Runtime adapter cannot
silently select a second Mapper edit vocabulary.
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


def _verification_payload(root: str, *, applied: bool) -> dict[str, Any]:
    """Run SIMPLICIO_TEST_CMD after apply, or mark verify skipped explicitly."""
    from ..pipeline_stages import _configured_test_command, _verification_timeout_seconds
    from ..runtime_env import prepare_project_command, project_subprocess_env

    if not applied:
        return {
            "status": "skipped",
            "reason_code": "verify_skipped_not_applied",
            "commands": [],
            "results": [],
        }
    command, configuration_error = _configured_test_command(root)
    if configuration_error or not command:
        return {
            "status": "skipped",
            "reason_code": "verify_skipped_no_test_cmd",
            "commands": [],
            "results": [],
        }
    cmd, use_shell = prepare_project_command(root, command)
    completed = subprocess.run(
        cmd,
        shell=use_shell,
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_verification_timeout_seconds(),
        check=False,
        env=project_subprocess_env(root),
    )
    passed = completed.returncode == 0
    return {
        "status": "passed" if passed else "failed",
        "reason_code": "verification_passed" if passed else "verification_failed",
        "commands": [command],
        "results": [
            {
                "command": command,
                "exit_code": completed.returncode,
                "stdout_tail": (completed.stdout or "")[-2000:],
                "stderr_tail": (completed.stderr or "")[-2000:],
            }
        ],
    }


def _decode_native_json(stdout: Any) -> Any:
    """Decode Runtime's final JSON receipt after any human-readable output."""
    if not isinstance(stdout, str):
        return None
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def run_mechanical_edit(a: argparse.Namespace) -> int:
    from ..mechanical_edit import execute_plan_json

    try:
        plan_text = read_text_source(a.plan)
    except OSError as exc:
        print(f"{CLI_PROG} mechanical-edit: {exc}", file=sys.stderr)
        return 2
    try:
        decoded_plan = json.loads(plan_text)
        plan_schema = decoded_plan.get("schema") if isinstance(decoded_plan, dict) else None
    except (TypeError, json.JSONDecodeError):
        plan_schema = None
    result_schema = (
        "simplicio.dev-cli.edit-receipt/v1"
        if plan_schema == "simplicio.dev-cli.edit-plan/v1"
        else "simplicio.mechanical-edit-result/v1"
    )
    policy = standalone_policy_for_root(a.root)
    result: dict[str, Any]
    if a.apply and not policy.write_allowed:
        result = {
            "schema": result_schema,
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
        verify = _verification_payload(a.root, applied=bool(result.get("applied")))
        result["verify"] = verify
        result["mutation_receipt"] = mutation_receipt(
            "standalone",
            entrypoint="edit",
            policy=policy,
            verification=verify,
            final_status=(
                "applied"
                if result.get("applied") and verify.get("status") in {"passed", "skipped"}
                else "failed"
                if verify.get("status") == "failed"
                else result.get("status")
            ),
        )
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

    payload = _decode_native_json(completed.stdout)
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
        result = _decode_native_json(getattr(completed, "stdout", ""))
        if result is None:
            errors.append(
                {
                    "code": "native_delegation_malformed_output",
                    "message": getattr(completed, "stdout", "").strip(),
                    "path": native_plan.get("file"),
                }
            )
            continue
        native_status = result.get("status") if isinstance(result, dict) else None
        final_status = result.get("final_status", native_status) if isinstance(result, dict) else None
        if native_status not in {"ok", "success"} or final_status not in {"ok", "success"}:
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


def _llm_full_file_budget_errors(plan: Any, root: str) -> list[dict[str, Any]]:
    """Reject a Mode 3 (Llm) plan attempting full-file generation.

    Only inspects plans explicitly marked ``effect_mode: "llm"`` by the
    effect router (issue #709) -- an additive, opt-in marker that leaves
    every other plan shape (Mode 1/Mode 2, and any plan predating the
    router) untouched. For each operation, ``old`` is the anchor/selector
    text if present (``find`` for ``replace_anchor``, otherwise absent for
    line-range ops) and ``new`` is the replacement text; both are checked
    against the current on-disk size of the touched file via
    ``simplicio.effect_router.validate_llm_edit``.
    """
    if not isinstance(plan, dict) or plan.get("effect_mode") != "llm":
        return []
    operations = plan.get("operations")
    if not isinstance(operations, list):
        return []
    from ..effect_router import validate_llm_edit

    errors: list[dict[str, Any]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        op_name = operation.get("op")
        path = operation.get("path", plan.get("file"))
        if not isinstance(path, str):
            continue
        if op_name == "replace_anchor":
            # An anchor op already requires a non-empty, unique `find` --
            # never full-file generation by construction. Nothing to guard.
            continue
        if op_name not in {"replace_range", "delete_range"}:
            # insert_before/insert_after/create_file/json_patch/ast_patch/
            # move_file/delete_file never overwrite a whole existing file's
            # content in one op; the Mode 3 budget guard is only meaningful
            # for a range op that could plausibly span the entire file.
            continue
        try:
            source = (Path(root) / path).read_text(encoding="utf-8")
        except OSError:
            continue
        total_lines = max(len(source.splitlines()), 1)
        start_line = operation.get("start_line")
        end_line = operation.get("end_line")
        if not isinstance(start_line, int) or not isinstance(end_line, int):
            continue
        if start_line > 1 or end_line < total_lines:
            # A partial range is a bounded edit, not full-file generation --
            # do not flag it just because the replacement text happens to be
            # a large fraction of a small file's byte size.
            continue
        new = str(operation.get("text", ""))
        file_size = len(source.encode("utf-8"))
        for error in validate_llm_edit(None, new, file_size):
            errors.append({**error, "path": path})
    return errors


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
    if plan.get("schema") == "simplicio.dev-cli.edit-plan/v1":
        operations = plan.get("operations")
        if not isinstance(operations, list) or not operations:
            return [{"code": "invalid_plan", "message": "Dev CLI edit operations must be a non-empty list"}]
        return (
            []
            if all(isinstance(item, dict) and isinstance(item.get("op"), str) for item in operations)
            else [{"code": "invalid_plan", "message": "Dev CLI edit operations must be objects with an op"}]
        )
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


def compile_host_plan(root: str, plan: Any) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Freeze a host's minimal ``{"operations": [{path, find, replace}]}`` plan.

    The host (an LLM) decides the change; Dev CLI pins the current file hashes
    and source tree into the mapper binding and fills every digest, so a later
    ``edit --apply`` refuses the plan if the files drifted in between.
    """
    import hashlib

    from ..mapper_binding import build_mapper_binding
    from ..mechanical_edit import TextEdit, build_edit_plan

    operations = plan.get("operations") if isinstance(plan, dict) else None
    if not isinstance(operations, list) or not operations:
        return None, [{"code": "invalid_plan", "message": "plan needs a non-empty operations list"}]
    errors: list[dict[str, Any]] = []
    edits: list[TextEdit] = []
    hashes: dict[str, str] = {}
    for index, op in enumerate(operations):
        if (
            not isinstance(op, dict)
            or not all(isinstance(op.get(key), str) for key in ("path", "find", "replace"))
            or not op["find"]
        ):
            errors.append(
                {
                    "code": "invalid_operation",
                    "index": index,
                    "message": "each operation needs string path, non-empty find, replace",
                }
            )
            continue
        path = op["path"]
        try:
            data = (Path(root) / path).read_bytes()
        except OSError as exc:
            errors.append({"code": "file_unreadable", "path": path, "message": str(exc)})
            continue
        count = data.decode("utf-8", "surrogateescape").count(op["find"])
        if count != 1:
            code = "missing_anchor" if count == 0 else "ambiguous_anchor"
            errors.append(
                {"code": code, "path": path, "message": f"find must match exactly once, matched {count}"}
            )
            continue
        hashes[path] = hashlib.sha256(data).hexdigest()
        edits.append(TextEdit(path, op["find"], op["replace"]))
    if errors:
        return None, errors
    tree = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD^{tree}"], capture_output=True, text=True, check=False
    )
    if tree.returncode != 0:
        return None, [{"code": "git_tree_unavailable", "message": tree.stderr.strip()}]
    source_tree = tree.stdout.strip()
    generation = source_tree
    snapshot = Path(root) / ".simplicio" / "context-snapshot.json"
    if snapshot.is_file():
        try:
            snapshot_id = json.loads(snapshot.read_text(encoding="utf-8")).get("snapshot_id")
            generation = str(snapshot_id or source_tree)
        except (OSError, ValueError):
            generation = source_tree
    binding = build_mapper_binding(f"local/{Path(root).resolve().name}", generation, source_tree, hashes)
    return build_edit_plan(edits, mapper_binding=binding), []


def _run_compile(a: argparse.Namespace, plan: Any) -> int:
    compiled, errors = compile_host_plan(a.root, plan)
    if compiled is None:
        result = {
            "schema": "simplicio.mechanical-edit-result/v1",
            "status": "refused",
            "applied": False,
            "noop": False,
            "operation_count": 0,
            "files": [],
            "errors": errors,
            "mutation_receipt": mutation_receipt("blocked", entrypoint="edit"),
        }
        return _print_edit_result(result, a)
    Path(a.compile).write_text(json.dumps(compiled, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": "simplicio.dev-cli.edit-compile/v1",
                "status": "ok",
                "plan": a.compile,
                "touched_files": compiled["touched_files"],
            }
        )
    )
    return 0


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
    if getattr(a, "compile", None):
        return _run_compile(a, plan)
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

    # Effect router (issue #709), Mode 3 budget: a plan explicitly marked
    # ``effect_mode: "llm"`` never gets to write a whole file. This is
    # additive and opt-in via the marker field -- plans without it (the
    # overwhelming majority, produced by Mode 1/Mode 2) are unaffected.
    llm_budget_errors = _llm_full_file_budget_errors(plan, a.root)
    if llm_budget_errors:
        result = {
            "schema": "simplicio.mechanical-edit-result/v1",
            "status": "refused",
            "applied": False,
            "noop": False,
            "operation_count": 0,
            "files": [],
            "errors": llm_budget_errors,
            "mutation_receipt": mutation_receipt("blocked", entrypoint="edit"),
        }
        emit_mutation_route(
            root=a.root, entrypoint="edit", route="blocked", reason_code="LLM_FULL_FILE_REJECTED"
        )
        return _print_edit_result(result, a)

    # The Dev CLI-owned plan is already in the canonical kernel vocabulary.
    # Do not hand it to the legacy Runtime Mapper edit endpoint, whose older
    # operation engine has different semantics. Runtime-backed callers can
    # authorize the resulting effect at their boundary; the local kernel is
    # the only implementation of this versioned plan.
    if plan.get("schema") == "simplicio.dev-cli.edit-plan/v1":
        record_delegation("edit", "python-forced", root=a.root, reason="canonical-dev-cli-plan")
        return run_mechanical_edit(a)

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
