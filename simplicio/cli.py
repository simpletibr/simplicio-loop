"""CLI entrypoint for the Python Simplicio adapter."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

CLI_PROG = "simplicio-py"


def maybe_autoinstall(cmd: str | None) -> bool:
    """Install skill + hook on first run when Claude Code is detected."""
    if os.environ.get("SIMPLICIO_SKIP_AUTO_INIT"):
        return False
    if cmd in ("init", "detect"):
        return False
    home = Path(os.environ["HOME"]) if os.environ.get("HOME") else Path.home()
    claude_home = home / ".claude"
    if not claude_home.is_dir():
        return False
    hook_path = claude_home / "hooks" / "simplicio-userpromptsubmit.sh"
    if hook_path.exists():
        return False
    try:
        from .init import install

        report = install(claude_home=claude_home, dry_run=False)
    except Exception as e:
        print(f"{CLI_PROG}: auto-activation skipped ({e})", file=sys.stderr)
        return False
    if (
        report.skill_installed
        or report.hook_script_installed
        or report.settings_updated
    ):
        print(
            f"{CLI_PROG}: auto-activation installed in Claude Code "
            "(skill + UserPromptSubmit hook). "
            "Disable next time with SIMPLICIO_SKIP_AUTO_INIT=1.",
            file=sys.stderr,
        )
        return True
    return False


def _parse_rust_flags(
    args: list[str],
) -> tuple[list[str], bool, bool]:
    """Strip ``--native`` and ``--python`` flags from *args*.

    Returns ``(cleaned_args, native_flag, python_flag)`` where the flags
    have been removed from the argument list.
    """
    cleaned: list[str] = []
    native = False
    python = False
    for a in args:
        if a == "--native":
            native = True
        elif a == "--python":
            python = True
        else:
            cleaned.append(a)
    return cleaned, native, python


def _try_route_via_simplicio(
    cmd_name: str,
    args: list[str],
    *,
    prefer_native: bool = True,
    prefer_python: bool = False,
) -> int | None:
    """Attempt to route *cmd_name* via the Rust ``simplicio`` binary.

    Returns the exit code if the binary handled the command, or ``None``
    if the caller should fall back to the Python implementation.
    """
    try:
        from .commands import route_command

        return route_command(
            cmd_name,
            args,
            prefer_native=prefer_native,
            prefer_python=prefer_python,
        )
    except ImportError:
        return None


def _dispatch_nested(argv: list[str]) -> int | None:
    if argv and argv[0] == "gate":
        clean_args, native, python = _parse_rust_flags(argv[1:])
        result = _try_route_via_simplicio(
            "gate", clean_args, prefer_native=native or not python, prefer_python=python
        )
        if result is not None:
            return result
        from .commands.gate import main as gate_main

        return gate_main(clean_args)
    if argv and argv[0] == "nest":
        clean_args, native, python = _parse_rust_flags(argv[1:])
        result = _try_route_via_simplicio(
            "nest", clean_args, prefer_native=native or not python, prefer_python=python
        )
        if result is not None:
            return result
        from .commands.nest import main as nest_main

        return nest_main(clean_args)
    if argv and argv[0] == "scratch":
        maybe_autoinstall("scratch")
        from .scratch.cli import main as scratch_main

        return scratch_main(argv[1:])
    if argv and argv[0] == "skill":
        maybe_autoinstall("skill")
        args = argv[1:]
        if not args or args[0] != "new":
            print(
                f'usage: {CLI_PROG} skill new "<description>" [--planner ...] [--dry-run]',
                file=sys.stderr,
            )
            return 2
        from .scratch.skill_opt import main as skill_main

        return skill_main(args[1:])
    return None


def _add_task_args(p: argparse.ArgumentParser, *, target_required: bool) -> None:
    p.add_argument("goal")
    p.add_argument("--root", default=".")
    p.add_argument("--stack", default=None)
    p.add_argument("--target", required=target_required)
    p.add_argument("--criteria", default="- true state\n- false state")
    p.add_argument("--constraints", default="- build passes")
    p.add_argument(
        "--dry-run-task",
        action="store_true",
        help="generate the would-be task output without applying/testing",
    )
    p.add_argument(
        "--json", action="store_true", help="emit stable structured task output"
    )
    p.add_argument(
        "--bound-paths",
        action="append",
        default=[],
        help="glob limiting which paths the task may change; repeatable",
    )
    p.add_argument(
        "--local",
        action="store_true",
        help="force local llama.cpp with MiniCPM5; overrides "
        "SIMPLICIO_MODEL/SIMPLICIO_BASE_URL",
    )


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("goal")
    p.add_argument("--scope", choices=["auto", "task", "feature", "sprint", "scratch"], default="auto")
    p.add_argument("--root", default=".")
    p.add_argument("--stack", default=None)
    p.add_argument("--target")
    p.add_argument("--criteria", default="- true state\n- false state")
    p.add_argument("--constraints", default="- build passes")
    p.add_argument("--dry-run-task", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--bound-paths", action="append", default=[])
    p.add_argument("--local", action="store_true")
    p.add_argument("--max-cost", default=None)
    p.add_argument("--max-iter", type=int, default=3)
    p.add_argument("--sprint", help="sprint directory name, e.g. sprint-01")
    p.add_argument("--name", default=None, help="scratch project directory name")
    p.add_argument("--dest", default=".", help="scratch destination parent")
    p.add_argument("--planner", default=None, help="scratch planner override")
    p.add_argument("--plan-only", action="store_true", help="scratch plan only")
    p.add_argument("--skip-install", action="store_true", help="scratch skip install")
    p.add_argument("--slot", action="append", default=[], metavar="KEY=VALUE")


def _force_local_if_requested(a: argparse.Namespace) -> None:
    if getattr(a, "local", False):
        # Force Path 4: local in-process llama.cpp. This keeps local execution
        # independent from Ollama or any HTTP service.
        from .providers import LOCAL_DEFAULT_MODEL

        os.environ["SIMPLICIO_MODEL"] = LOCAL_DEFAULT_MODEL
        os.environ.pop("SIMPLICIO_BASE_URL", None)
        os.environ.pop("SIMPLICIO_API_KEY", None)


def _run_task_command(a: argparse.Namespace) -> int:
    from .pipeline import run_task
    from .precedent import auto_detect_stack

    _force_local_if_requested(a)
    stack = auto_detect_stack(a.root, a.stack)
    if a.json or a.dry_run_task:
        result = run_task(
            a.root,
            stack,
            a.goal,
            a.target,
            a.criteria,
            a.constraints,
            dry_run_task=a.dry_run_task,
            bound_paths=a.bound_paths,
            quiet=a.json,
        )
        if a.json:
            print(json.dumps(result, sort_keys=True))
        else:
            status = "DRY-RUN" if a.dry_run_task else "DONE"
            print(f"{status}: {result['diff_summary']}")
            for warning in result["warnings"]:
                print(f"warning: {warning}", file=sys.stderr)
        return 0 if (a.dry_run_task or result["applied"]) else 1
    result = run_task(
        a.root,
        stack,
        a.goal,
        a.target,
        a.criteria,
        a.constraints,
        bound_paths=a.bound_paths,
    )
    status = "DONE" if result["applied"] else "FAILED"
    print(f"{status}: {result['diff_summary']}")
    for warning in result["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    return 0 if result["applied"] else 1


def _first_file_signal(signals: list[str]) -> str | None:
    for signal in signals:
        if signal.startswith("file:"):
            return signal.split(":", 1)[1]
    return None


def _run_scratch_command(a: argparse.Namespace) -> int:
    from .scratch.cli import main as scratch_main

    scratch_argv = [a.goal]
    if a.stack:
        scratch_argv += ["--stack", a.stack]
    if a.root:
        scratch_argv += ["--root", a.root]
    if a.name:
        scratch_argv += ["--name", a.name]
    if a.dest:
        scratch_argv += ["--dest", a.dest]
    if a.planner:
        scratch_argv += ["--planner", a.planner]
    for slot in a.slot:
        scratch_argv += ["--slot", slot]
    if a.plan_only:
        scratch_argv.append("--plan-only")
    if a.skip_install:
        scratch_argv.append("--skip-install")
    if a.json:
        scratch_argv.append("--json")
    return scratch_main(scratch_argv)


def _run_feature_command(a: argparse.Namespace) -> int:
    if not a.stack:
        print(f"{CLI_PROG} run --scope feature requires --stack <slug>", file=sys.stderr)
        return 2
    from .orchestrator import run_feature

    _force_local_if_requested(a)
    try:
        result = run_feature(
            root=a.root,
            stack_slug=a.stack,
            goal=a.goal,
            max_iter=a.max_iter,
            max_cost=a.max_cost,
            quiet=a.json,
        )
    except ValueError as exc:
        print(f"{CLI_PROG} run: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(result, sort_keys=True))
    else:
        status = "DONE" if result["applied"] else "FAILED"
        print(
            f"{status}: feature tasks={len(result['tasks'])} "
            f"replans={result['replans']}"
        )
        for warning in result["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)
    return 0 if result["applied"] else 1


def _infer_sprint_name(goal: str) -> str | None:
    match = re.search(r"\bsprint[-\s_]*(\d+)\b", goal, flags=re.IGNORECASE)
    if not match:
        return None
    return f"sprint-{int(match.group(1)):02d}"


def _run_sprint_command(a: argparse.Namespace) -> int:
    if not a.max_cost:
        print(f"{CLI_PROG} run --scope sprint requires --max-cost", file=sys.stderr)
        return 2
    if not a.stack:
        print(f"{CLI_PROG} run --scope sprint requires --stack <slug>", file=sys.stderr)
        return 2
    from .dod import load_dod, load_sprint_dod, run_dod_gates
    from .orchestrator import run_feature
    from .orchestrator.cost_governor import CostGovernor, provider_budget
    from .sprint_loader import load_sprint

    sprint_name = a.sprint or _infer_sprint_name(a.goal)
    if not sprint_name:
        print(f"{CLI_PROG} run --scope sprint requires --sprint sprint-XX", file=sys.stderr)
        return 2

    try:
        sprint = load_sprint(a.root, sprint_name)
    except FileNotFoundError as exc:
        print(f"{CLI_PROG} run: {exc}", file=sys.stderr)
        return 2

    try:
        CostGovernor.from_value(a.max_cost)
    except ValueError as exc:
        print(f"{CLI_PROG} run: {exc}", file=sys.stderr)
        return 2

    state_dir = Path(a.root) / ".simplicio"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "sprint_state.json"
    if not sprint.tasks:
        _write_sprint_state(
            state_path,
            sprint=sprint,
            sprint_name=sprint_name,
            stack=a.stack,
            max_cost=a.max_cost,
            results=[],
            dod_results=[],
            complete=False,
            cost=None,
        )
        print(f"{CLI_PROG} run: sprint has no task specs: {sprint.root}", file=sys.stderr)
        return 2

    results = _load_resumable_sprint_results(state_path, sprint_name, a.stack)
    resumed = bool(results)
    duplicate_titles = {
        task.title
        for task in sprint.tasks
        if sum(1 for other in sprint.tasks if other.title == task.title) > 1
    }
    if duplicate_titles:
        results = [row for row in results if row.get("task_id")]
    completed_task_ids = {
        row.get("task_id")
        for row in results
        if isinstance(row.get("result"), dict) and row["result"].get("applied")
    }
    completed_tasks = {
        row["task"]
        for row in results
        if isinstance(row.get("result"), dict) and row["result"].get("applied")
    }
    with provider_budget(a.max_cost) as governor:
        for task in sprint.tasks:
            task_id = _sprint_task_id(task)
            if task_id in completed_task_ids or (
                task.title not in duplicate_titles and task.title in completed_tasks
            ):
                continue
            try:
                result = run_feature(
                    root=a.root,
                    stack_slug=a.stack,
                    goal=task.goal,
                    max_iter=a.max_iter,
                    max_cost=None,
                    quiet=a.json,
                )
            except ValueError as exc:
                result = {
                    "scope": "feature",
                    "goal": task.goal,
                    "stack": a.stack,
                    "applied": False,
                    "tasks": [],
                    "replans": 0,
                    "warnings": [str(exc)],
                }
                results.append({"task": task.title, "task_id": task_id, "result": result})
                governor.refresh_from_env()
                cost = governor.report()
                _write_sprint_state(
                    state_path,
                    sprint=sprint,
                    sprint_name=sprint_name,
                    stack=a.stack,
                    max_cost=a.max_cost,
                    results=results,
                    dod_results=[],
                    complete=False,
                    cost=cost,
                )
                print(f"{CLI_PROG} run: {exc}", file=sys.stderr)
                return 2
            governor.refresh_from_env()
            results.append({"task": task.title, "task_id": task_id, "result": result})
            _write_sprint_state(
                state_path,
                sprint=sprint,
                sprint_name=sprint_name,
                stack=a.stack,
                max_cost=a.max_cost,
                results=results,
                dod_results=[],
                complete=False,
                cost=governor.report(),
            )
            if not result["applied"]:
                break

        dod_gates = [*load_dod(a.root), *load_sprint_dod(sprint.root)]
        dod_results = run_dod_gates(a.root, dod_gates)
        applied = (
            len(results) == len(sprint.tasks)
            and all(row["result"]["applied"] for row in results)
            and all(row["passed"] for row in dod_results)
        )
        governor.refresh_from_env()
        cost = governor.report()
        _write_sprint_state(
            state_path,
            sprint=sprint,
            sprint_name=sprint_name,
            stack=a.stack,
            max_cost=a.max_cost,
            results=results,
            dod_results=dod_results,
            complete=applied,
            cost=cost,
        )
        payload = {
            "scope": "sprint",
            "sprint": sprint.title,
            "applied": applied,
            "features": results,
            "dod": dod_results,
            "cost": cost,
            "resumed": resumed,
        }
    if a.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        status = "DONE" if applied else "FAILED"
        print(f"{status}: sprint features={len(results)} dod_gates={len(dod_results)}")
    return 0 if applied else 1


def _load_resumable_sprint_results(
    path: Path,
    sprint_name: str,
    stack: str,
) -> list[dict]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if payload.get("scope") != "sprint":
        return []
    if payload.get("sprint_name") != sprint_name or payload.get("stack") != stack:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [
        row
        for row in results
        if isinstance(row, dict)
        and isinstance(row.get("result"), dict)
        and row["result"].get("applied") is True
        and row.get("task")
    ]


def _sprint_task_id(task) -> str:
    try:
        return task.path.name
    except AttributeError:
        return str(getattr(task, "title", ""))


def _write_sprint_state(
    path: Path,
    *,
    sprint,
    sprint_name: str,
    stack: str,
    max_cost: str,
    results: list[dict],
    dod_results: list[dict],
    complete: bool,
    cost: dict[str, str | None] | None = None,
) -> None:
    total = len(sprint.tasks)
    completed = sum(1 for row in results if row["result"]["applied"])
    failed = [row for row in results if not row["result"]["applied"]]
    failed_gates = [row["label"] for row in dod_results if not row["passed"]]
    state = "complete" if complete else "in-progress"
    if failed or failed_gates or (total == 0 and not complete):
        state = "failed"
    payload = {
        "scope": "sprint",
        "state": state,
        "sprint": sprint.title,
        "sprint_name": sprint_name,
        "stack": stack,
        "max_cost": max_cost,
        "total_features": total,
        "completed_features": completed,
        "failed_features": [row["task"] for row in failed],
        "failed_dod_gates": failed_gates,
        "complete": complete,
        "updated_at": int(time.time()),
        "results": results,
        "dod": dod_results,
        "cost": cost,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _status_claims_gate(payload: dict[str, object]) -> dict[str, object]:
    """Return a low-risk claim contract for ``status --json`` consumers.

    A persisted sprint state can prove that this adapter recorded a fresh,
    passing local execution for the tracked sprint flow. It still cannot prove
    repo-wide green on its own, so downstream consumers must not escalate that
    broader claim from a single status payload.
    """

    failed_features = payload.get("failed_features")
    failed_dod_gates = payload.get("failed_dod_gates")
    state = payload.get("state") or ("complete" if payload.get("complete") else "in-progress")
    has_fresh_passing_state = (
        bool(payload.get("complete"))
        and state == "complete"
        and not failed_features
        and not failed_dod_gates
    )
    if not has_fresh_passing_state:
        return {
            "allow_fresh_verification_claim": False,
            "allow_repo_green_claim": False,
            "proof_scope": "none",
            "reason": "fresh passing verification evidence is not available",
        }
    return {
        "allow_fresh_verification_claim": True,
        "allow_repo_green_claim": False,
        "proof_scope": "sprint_state",
        "reason": (
            "last passing evidence came from the stored sprint state; "
            "it does not prove repo-wide green"
        ),
    }


def _run_status_command(a: argparse.Namespace) -> int:
    from .mapper import artifact_status

    root = Path(a.root).resolve()
    state_path = root / ".simplicio" / "sprint_state.json"
    if not state_path.is_file():
        payload = {
            "schema": "simplicio.dev-cli.status/v1",
            "root": str(root),
            "state": "none",
            "path": str(state_path),
            "artifacts": artifact_status(root),
        }
        payload["claims_gate"] = _status_claims_gate(payload)
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"no simplicio sprint state at {state_path}")
        return 0
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{CLI_PROG} status: invalid state file: {exc}", file=sys.stderr)
        return 2
    json_payload = {
        "schema": "simplicio.dev-cli.status/v1",
        "root": str(root),
        **payload,
        "artifacts": artifact_status(root),
    }
    json_payload["claims_gate"] = _status_claims_gate(json_payload)
    if a.json:
        print(json.dumps(json_payload, sort_keys=True))
        return 0
    completed = payload.get("completed_features", 0)
    total = payload.get("total_features", 0)
    state = payload.get("state") or ("complete" if payload.get("complete") else "in-progress")
    if payload.get("failed_features") or payload.get("failed_dod_gates"):
        state = "failed"
    cost_suffix = ""
    cost = payload.get("cost")
    if isinstance(cost, dict):
        spent = cost.get("spent_usd")
        budget = cost.get("budget_usd")
        if spent is not None and budget is not None:
            cost_suffix = f" cost={spent}/{budget}"
    print(
        f"{state}: {payload.get('sprint', 'sprint')} "
        f"{completed}/{total} features"
        f"{cost_suffix}"
    )
    for failed in payload.get("failed_features", []):
        print(f"failed: {failed}", file=sys.stderr)
    for failed in payload.get("failed_dod_gates", []):
        print(f"failed DoD: {failed}", file=sys.stderr)
    return 0


def _read_text_source(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _run_mechanical_edit_command(a: argparse.Namespace) -> int:
    from .mechanical_edit import execute_plan_json

    try:
        plan_text = _read_text_source(a.plan)
    except OSError as exc:
        print(f"{CLI_PROG} mechanical-edit: {exc}", file=sys.stderr)
        return 2
    result = execute_plan_json(plan_text, root=a.root, apply=a.apply)
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


def _run_edit_command(a: argparse.Namespace) -> int:
    runtime = None if a.no_runtime else _runtime_edit_binary()
    if runtime:
        cmd = [runtime, "edit", "--plan", a.plan, "--repo", a.root]
        if a.json:
            cmd.append("--json")
        if not a.apply:
            cmd.append("--dry-run")
        try:
            plan_stdin = _read_text_source("-") if a.plan == "-" else None
            completed = subprocess.run(cmd, input=plan_stdin, text=True)
        except OSError as exc:
            print(f"{CLI_PROG} edit: runtime delegation failed ({exc}); using local fallback", file=sys.stderr)
        else:
            return completed.returncode
    return _run_mechanical_edit_command(a)


def _run_token_command(a: argparse.Namespace) -> int:
    from .token_primitives import (
        ContextCache,
        build_retry_payload,
        evaluate_postconditions,
        git_diff_review,
        model_routing_decision,
        summarize_log,
    )

    try:
        if a.token_cmd == "log-summary":
            payload = summarize_log(_read_text_source(a.file), max_chars=a.max_chars)
        elif a.token_cmd == "diff-review":
            payload = git_diff_review(a.root, max_patch_chars=a.max_patch_chars)
        elif a.token_cmd == "postconditions":
            checks = json.loads(_read_text_source(a.file))
            payload = evaluate_postconditions(checks, root=a.root)
        elif a.token_cmd == "retry":
            log = _read_text_source(a.log_file) if a.log_file else ""
            failure = json.loads(a.failure_json) if a.failure_json else {}
            payload = build_retry_payload(
                reason=a.reason,
                failure=failure,
                log=log,
                max_log_chars=a.max_log_chars,
            )
        elif a.token_cmd == "model-routing":
            payload = model_routing_decision(json.loads(_read_text_source(a.file)))
        elif a.token_cmd == "context-cache":
            cache = ContextCache(a.root)
            content = _read_text_source(a.content_file) if a.content_file else ""
            if a.cache_cmd == "get":
                payload = cache.get(a.key, content)
            elif a.cache_cmd == "put":
                summary = json.loads(_read_text_source(a.summary_file))
                payload = cache.put(a.key, content, summary)
            else:
                payload = cache.invalidate(a.key)
        else:
            print(f"{CLI_PROG} token: unsupported command", file=sys.stderr)
            return 2
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"{CLI_PROG} token {a.token_cmd}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


def _run_runtime_command(a: argparse.Namespace) -> int:
    from .runtime_contracts import doctor_contract

    if a.runtime_cmd == "doctor":
        payload = doctor_contract(a.root)
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"{CLI_PROG} runtime doctor: {payload['package']['version']}")
            for name, status in payload["tools"].items():
                state = "ok" if status["available"] else "missing"
                print(f"  {name}: {state}")
        return 0
    print(f"{CLI_PROG} runtime: unsupported command", file=sys.stderr)
    return 2


def _run_serve_command(a: argparse.Namespace) -> int:
    if not a.mcp:
        print(f"{CLI_PROG} serve: only --mcp is supported today", file=sys.stderr)
        return 2
    from .mcp_server import serve_stdio

    serve_stdio()
    return 0


def _run_memory_command(a: argparse.Namespace) -> int:
    from .memory_store import init_memory, recall_memory, store_memory

    if a.memory_cmd == "init":
        payload = init_memory(root=a.dir)
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"{CLI_PROG} memory init: {payload['dir']} (created={payload['created']}, git={payload['git_initialized']})")
        return 0
    if a.memory_cmd == "store":
        tags = [t.strip() for t in a.tags.split(",") if t.strip()] if a.tags else None
        payload = store_memory(a.topic, a.content, tags=tags, root=a.dir)
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"{CLI_PROG} memory store: {payload['path']} (committed={payload['committed']})")
        return 0
    if a.memory_cmd == "recall":
        results = recall_memory(a.query, limit=a.limit, root=a.dir)
        if a.json:
            print(json.dumps({"results": results}, sort_keys=True))
        else:
            if not results:
                print(f"{CLI_PROG} memory recall: no matches")
            for r in results:
                print(f"[{r['score']}] {r['topic']}: {r['snippet'][:120]}")
        return 0
    print(f"{CLI_PROG} memory: unsupported command", file=sys.stderr)
    return 2


def _run_claims_command(a: argparse.Namespace) -> int:
    from .commands.claims import main as claims_main

    claims_argv = [a.claims_cmd]
    if a.claims_cmd in {"check", "tag"}:
        claims_argv.extend(a.statement)
    elif a.claims_cmd == "report":
        if a.path:
            claims_argv += ["--path", a.path]
        if a.json_file:
            claims_argv += ["--json", a.json_file]
        claims_argv.extend(a.claims)
    return claims_main(claims_argv)


def _run_file_command(a: argparse.Namespace) -> int:
    from .commands.file_read import run as file_read_run

    if a.file_cmd == "read":
        return file_read_run(a)
    print(f"{CLI_PROG} file: unsupported command", file=sys.stderr)
    return 2


def _run_test_command(a: argparse.Namespace) -> int:
    from .commands.test_run import run as test_run_run

    if a.test_cmd == "run":
        extra_args = a.extra_args
        if extra_args and extra_args[0] == "--":
            extra_args = extra_args[1:]
        # `--cmd` is parsed into `test_program` to avoid colliding with the
        # top-level subparser's `dest="cmd"`; translate to the attribute
        # name `commands/test_run.py` expects.
        a.cmd = a.test_program
        return test_run_run(a, extra_args)
    print(f"{CLI_PROG} test: unsupported command", file=sys.stderr)
    return 2


def _run_inspect_command(a: argparse.Namespace) -> int:
    from .mapper import inspect_target

    payload = {
        "schema": "simplicio.dev-cli.inspect/v1",
        **inspect_target(a.root, a.target, goal=a.goal),
    }
    if a.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(payload["context"])
    return 0


def _run_run_command(a: argparse.Namespace) -> int:
    from .intent import AUTO_CONFIDENCE_THRESHOLD, classify_goal

    result = classify_goal(a.goal, explicit_scope=a.scope)
    if result.confidence < AUTO_CONFIDENCE_THRESHOLD:
        print(
            f"{CLI_PROG} run: goal is ambiguous; pass --scope task|feature|sprint|scratch",
            file=sys.stderr,
        )
        return 2

    if result.scope == "task":
        if not a.target:
            a.target = _first_file_signal(result.signals)
        if not a.target and a.scope != "auto":
            a.target = _first_file_signal(classify_goal(a.goal).signals)
        if not a.target:
            print(f"{CLI_PROG} run --scope task requires --target or a file in goal", file=sys.stderr)
            return 2
        return _run_task_command(a)
    if result.scope == "scratch":
        return _run_scratch_command(a)
    if result.scope == "feature":
        return _run_feature_command(a)
    if result.scope == "sprint":
        return _run_sprint_command(a)
    print(f"{CLI_PROG} run: unsupported scope {result.scope!r}", file=sys.stderr)
    return 2


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # Session-start ecosystem-freshness check (closes the runtime gap where
    # pyproject pins >=X but the installed version is older). Idempotent +
    # opt-out via SIMPLICIO_NO_AUTO_UPGRADE=1. See simplicio/ecosystem.py.
    try:
        from .ecosystem import maybe_run_session_start
        maybe_run_session_start()
    except Exception as e:
        # Never let the freshness check break the CLI.
        print(f"{CLI_PROG}: ecosystem check skipped ({e})", file=sys.stderr)

    nested = _dispatch_nested(argv)
    if nested is not None:
        return nested

    ap = argparse.ArgumentParser(prog=CLI_PROG)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="index/cache the repo (once, or after changes)")
    pi.add_argument("root_arg", nargs="?", help="project root; same as --root")
    pi.add_argument("--root", default=".")
    pi.add_argument("--stack", default=None)

    pt = sub.add_parser("task", help="run a task")
    _add_task_args(pt, target_required=True)

    pr = sub.add_parser("run", help="run a task, feature, sprint, or scratch goal")
    _add_run_args(pr)

    pb = sub.add_parser("bench", help="compare with vs without (real numbers)")
    pb.add_argument("--root", default=".")
    pb.add_argument("--stack", default=None, help="stack slug (auto-detected if omitted)")
    pb.add_argument("--cases", default="bench/cases.json")

    pc = sub.add_parser("cache", help="inspect or clear completion cache")
    pc_sub = pc.add_subparsers(dest="cache_cmd", required=True)
    pc_stats = pc_sub.add_parser("stats", help="print completion cache statistics")
    pc_stats.add_argument("--json", action="store_true")
    pc_clear = pc_sub.add_parser("clear", help="clear completion cache")
    pc_clear.add_argument("--force", action="store_true", help="required to clear")

    p_smoke = sub.add_parser(
        "smoke", help="one proof call: connect+generate (needs SIMPLICIO_MODEL+KEY)"
    )
    p_smoke.add_argument("--json", action="store_true")
    p_smoke.add_argument("--root", default=".")

    p_init = sub.add_parser(
        "init", help="install skill + UserPromptSubmit hook into ~/.claude/"
    )
    p_init.add_argument("--claude-home", help="override ~/.claude (for tests)")
    p_init.add_argument("--dry-run", action="store_true")

    p_det = sub.add_parser("detect", help="heuristic: is a prompt a code-edit task")
    p_det.add_argument("prompt_words", nargs="*", help=argparse.SUPPRESS)
    p_det.add_argument("--prompt", help="prompt text (default: read from stdin)")
    p_det.add_argument("--quiet", action="store_true")
    p_det.add_argument("--json", action="store_true")

    p_status = sub.add_parser("status", help="show current simplicio-py run state")
    p_status.add_argument("--root", default=".")
    p_status.add_argument("--json", action="store_true")

    p_claims = sub.add_parser("claims", help="claims-gate checks and report generation")
    claims_sub = p_claims.add_subparsers(dest="claims_cmd", required=True)
    p_claims_check = claims_sub.add_parser("check", help="verify a claim against the 8 rules")
    p_claims_check.add_argument("statement", nargs="+")
    p_claims_tag = claims_sub.add_parser("tag", help="suggest MEASURED|CANON|UNVERIFIED")
    p_claims_tag.add_argument("statement", nargs="+")
    p_claims_report = claims_sub.add_parser("report", help="generate/load a claims report")
    p_claims_report.add_argument("claims", nargs="*")
    p_claims_report.add_argument("--path")
    p_claims_report.add_argument("--json", dest="json_file")

    p_inspect = sub.add_parser("inspect", help="inspect a target with mapper-backed context")
    p_inspect.add_argument("target")
    p_inspect.add_argument("--root", default=".")
    p_inspect.add_argument("--goal", default="")
    p_inspect.add_argument("--json", action="store_true")

    p_doctor = sub.add_parser(
        "doctor",
        help="check local llama.cpp readiness and dependency freshness",
    )
    p_doctor.add_argument("--install", action="store_true")
    p_doctor.add_argument("--json", action="store_true")
    p_doctor.add_argument("--list-tiers", action="store_true")
    p_doctor.add_argument("--no-check-updates", action="store_true")
    p_doctor.add_argument("--refresh", action="store_true")
    p_doctor.add_argument("--upgrade", action="store_true")

    p_env_export = sub.add_parser(
        "env-export",
        help="print shell-safe exports from a dotenv file without sourcing it",
    )
    p_env_export.add_argument("env_file")
    p_env_export.add_argument("--json", action="store_true")

    p_mechanical = sub.add_parser(
        "mechanical-edit",
        help="execute simplicio.mechanical-edit/v1 dry-run or apply",
    )
    p_mechanical.add_argument("--root", default=".")
    p_mechanical.add_argument("--plan", default="-", help="plan JSON path, or - for stdin")
    p_mechanical.add_argument("--apply", action="store_true")
    p_mechanical.add_argument("--dry-run", action="store_true")
    p_mechanical.add_argument("--json", action="store_true")

    p_edit = sub.add_parser(
        "edit",
        help="apply a mechanical edit plan via simplicio-runtime when available",
    )
    p_edit.add_argument("--root", "--repo", dest="root", default=".")
    p_edit.add_argument("--plan", default="-", help="plan JSON path, or - for stdin")
    p_edit.add_argument("--apply", action="store_true")
    p_edit.add_argument("--dry-run", action="store_true")
    p_edit.add_argument("--json", action="store_true")
    p_edit.add_argument(
        "--no-runtime",
        action="store_true",
        help="use the Python mechanical-edit fallback instead of delegating to simplicio edit",
    )

    p_file = sub.add_parser("file", help="read raw file contents")
    file_sub = p_file.add_subparsers(dest="file_cmd", required=True)
    p_file_read = file_sub.add_parser(
        "read", help="print a file's contents, optionally sliced by line range"
    )
    p_file_read.add_argument("path")
    p_file_read.add_argument("--json", action="store_true")
    p_file_read.add_argument("--start", type=int, default=None, help="1-indexed inclusive start line")
    p_file_read.add_argument("--end", type=int, default=None, help="1-indexed inclusive end line")
    p_file_read.add_argument("--max-bytes", type=int, default=None, dest="max_bytes")
    p_file_read.add_argument("--repo", default=".")

    p_test = sub.add_parser("test", help="run a test command and report results")
    test_sub = p_test.add_subparsers(dest="test_cmd", required=True)
    p_test_run = test_sub.add_parser("run", help="run a test command (default: pytest)")
    p_test_run.add_argument("--cmd", dest="test_program", default="pytest")
    p_test_run.add_argument("--json", action="store_true")
    p_test_run.add_argument("--repo", default=".")
    p_test_run.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="seconds to wait for the test command before giving up (default: 120)",
    )
    p_test_run.add_argument(
        "extra_args",
        nargs=argparse.REMAINDER,
        help="extra args passed through to --cmd after a literal --",
    )

    p_token = sub.add_parser("token", help="token-efficient execution primitives")
    token_sub = p_token.add_subparsers(dest="token_cmd", required=True)
    p_log = token_sub.add_parser("log-summary")
    p_log.add_argument("--file", default="-")
    p_log.add_argument("--max-chars", type=int, default=1200)
    p_diff = token_sub.add_parser("diff-review")
    p_diff.add_argument("--root", default=".")
    p_diff.add_argument("--max-patch-chars", type=int, default=4000)
    p_post = token_sub.add_parser("postconditions")
    p_post.add_argument("--file", default="-")
    p_post.add_argument("--root", default=".")
    p_retry = token_sub.add_parser("retry")
    p_retry.add_argument("--reason", required=True)
    p_retry.add_argument("--failure-json", default="{}")
    p_retry.add_argument("--log-file")
    p_retry.add_argument("--max-log-chars", type=int, default=1000)
    p_route = token_sub.add_parser("model-routing")
    p_route.add_argument("--file", default="-")
    p_cache = token_sub.add_parser("context-cache")
    cache_sub = p_cache.add_subparsers(dest="cache_cmd", required=True)
    for p_cache_action in (
        cache_sub.add_parser("get"),
        cache_sub.add_parser("put"),
        cache_sub.add_parser("invalidate"),
    ):
        p_cache_action.add_argument("--root", default=".")
        p_cache_action.add_argument("--key")
        p_cache_action.add_argument("--content-file")
    cache_sub.choices["put"].add_argument("--summary-file", required=True)

    p_score_skill = sub.add_parser(
        "score-skill",
        help="deterministic SkillOpt-style scorer for skill/law text",
    )
    p_score_skill.add_argument(
        "skill",
        nargs="?",
        default="-",
        help="skill/law text file path, or - for stdin (default: -)",
    )
    p_score_skill.add_argument(
        "--scenario", "-s",
        dest="scenario_sources",
        action="append",
        default=[],
        help="JSON scenario file path (repeatable); falls back to builtin scenarios",
    )
    p_score_skill.add_argument(
        "--extra-scenario",
        action="append",
        default=[],
        help="inline JSON scenario string (repeatable)",
    )
    p_score_skill.add_argument("--json", action="store_true")
    p_score_skill.add_argument(
        "--verbose", "-v", action="store_true",
        help="print per-scenario detail even on success",
    )
    p_score_skill.add_argument(
        "--native",
        action="store_true",
        help="force the Rust simplicio binary for this command",
    )
    p_score_skill.add_argument(
        "--python",
        action="store_true",
        help="force the Python implementation for this command",
    )

    p_runtime = sub.add_parser("runtime", help="runtime-facing dev-cli contracts")
    runtime_sub = p_runtime.add_subparsers(dest="runtime_cmd", required=True)
    p_runtime_doctor = runtime_sub.add_parser("doctor")
    p_runtime_doctor.add_argument("--root", default=".")
    p_runtime_doctor.add_argument("--json", action="store_true")

    p_serve = sub.add_parser(
        "serve", help="run simplicio-dev-cli as a server (--mcp for the MCP stdio protocol)"
    )
    p_serve.add_argument(
        "--mcp",
        action="store_true",
        help="serve MCP tools (dev_cli_edit, dev_cli_validate, dev_cli_memory) over stdio",
    )

    p_memory = sub.add_parser(
        "memory", help="cross-vendor memory handoff (markdown + git under ~/.simplicio/memory)"
    )
    memory_sub = p_memory.add_subparsers(dest="memory_cmd", required=True)
    p_mem_init = memory_sub.add_parser("init", help="create the memory store")
    p_mem_init.add_argument("--dir", default=None, help="override memory dir (default ~/.simplicio/memory)")
    p_mem_init.add_argument("--json", action="store_true")
    p_mem_store = memory_sub.add_parser("store", help="append a note")
    p_mem_store.add_argument("topic")
    p_mem_store.add_argument("content")
    p_mem_store.add_argument("--tags", default="", help="comma-separated tags")
    p_mem_store.add_argument("--dir", default=None)
    p_mem_store.add_argument("--json", action="store_true")
    p_mem_recall = memory_sub.add_parser("recall", help="keyword search over stored notes")
    p_mem_recall.add_argument("query")
    p_mem_recall.add_argument("--limit", type=int, default=5)
    p_mem_recall.add_argument("--dir", default=None)
    p_mem_recall.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)
    maybe_autoinstall(a.cmd)
    if a.cmd == "index":
        from .precedent import index_repo

        index_repo(a.root_arg or a.root, a.stack)
    elif a.cmd == "smoke":
        from .providers import generate, info
        from .runtime_contracts import smoke_contract

        provider = info()
        out = generate("Reply exactly: OK simplicio connected.")
        if a.json:
            print(json.dumps(smoke_contract(provider=provider, reply=out, root=a.root), sort_keys=True))
        else:
            print("provider:", provider)
            print("model reply:", out.strip()[:200])
    elif a.cmd == "bench":
        from .bench import run_bench

        run_bench(a.root, a.stack, a.cases)
    elif a.cmd == "cache":
        from ._cache import cache

        c = cache()
        if a.cache_cmd == "stats":
            stats = c.stats()
            if a.json:
                print(json.dumps(stats, sort_keys=True))
            else:
                print(f"root: {stats['root']}")
                print(f"enabled: {stats['enabled']}  bust: {stats['bust']}")
                print(f"entries: {stats['entries']}  size: {stats['mb']} MB")
                print(f"ttl_days: {stats['ttl_days']}  max_mb: {stats['max_mb']}")
            return 0
        if a.cache_cmd == "clear":
            if not a.force:
                print(f"{CLI_PROG} cache clear requires --force", file=sys.stderr)
                return 2
            removed = c.clear()
            print(f"cleared {removed} cached completion(s)")
            return 0
    elif a.cmd == "init":
        from .init import main as init_main

        init_argv = []
        if a.claude_home:
            init_argv += ["--claude-home", a.claude_home]
        if a.dry_run:
            init_argv += ["--dry-run"]
        return init_main(init_argv)
    elif a.cmd == "detect":
        from .detect import main as detect_main

        detect_argv = []
        prompt = a.prompt
        if prompt is None and a.prompt_words:
            prompt = " ".join(a.prompt_words)
        if prompt is not None:
            detect_argv += ["--prompt", prompt]
        if a.quiet:
            detect_argv += ["--quiet"]
        if a.json:
            detect_argv += ["--json"]
        return detect_main(detect_argv)
    elif a.cmd == "status":
        return _run_status_command(a)
    elif a.cmd == "claims":
        return _run_claims_command(a)
    elif a.cmd == "inspect":
        return _run_inspect_command(a)
    elif a.cmd == "doctor":
        from .doctor import main as doctor_main

        doctor_argv = []
        if a.install:
            doctor_argv.append("--install")
        if a.json:
            doctor_argv.append("--json")
        if a.list_tiers:
            doctor_argv.append("--list-tiers")
        if a.no_check_updates:
            doctor_argv.append("--no-check-updates")
        if a.refresh:
            doctor_argv.append("--refresh")
        if a.upgrade:
            doctor_argv.append("--upgrade")
        return doctor_main(doctor_argv)
    elif a.cmd == "env-export":
        from .runtime_env import parse_env_file, shell_export_lines

        try:
            values = parse_env_file(a.env_file)
        except OSError as exc:
            print(f"{CLI_PROG} env-export: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"{CLI_PROG} env-export: {exc}", file=sys.stderr)
            return 2
        if a.json:
            print(json.dumps(values, sort_keys=True))
        else:
            print("\n".join(shell_export_lines(values)))
        return 0
    elif a.cmd == "mechanical-edit":
        return _run_mechanical_edit_command(a)
    elif a.cmd == "edit":
        return _run_edit_command(a)
    elif a.cmd == "file":
        return _run_file_command(a)
    elif a.cmd == "test":
        return _run_test_command(a)
    elif a.cmd == "token":
        return _run_token_command(a)
    elif a.cmd == "score-skill":
        score_argv = [a.skill]
        for s in a.scenario_sources:
            score_argv += ["--scenario", s]
        for e in a.extra_scenario:
            score_argv += ["--extra-scenario", e]
        if a.json:
            score_argv.append("--json")
        if a.verbose:
            score_argv.append("--verbose")
        # Try Rust binary first, then fall back to Python
        result = _try_route_via_simplicio(
            "score-skill",
            score_argv,
            prefer_native=a.native or not a.python,
            prefer_python=a.python,
        )
        if result is not None:
            return result
        from .commands.score_skill import main as score_skill_main

        return score_skill_main(score_argv)
    elif a.cmd == "runtime":
        return _run_runtime_command(a)
    elif a.cmd == "serve":
        return _run_serve_command(a)
    elif a.cmd == "memory":
        return _run_memory_command(a)
    elif a.cmd == "task":
        return _run_task_command(a)
    elif a.cmd == "run":
        return _run_run_command(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
