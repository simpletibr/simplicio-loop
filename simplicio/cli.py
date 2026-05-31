"""CLI entrypoint for simplicio."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


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
        print(f"simplicio: auto-activation skipped ({e})", file=sys.stderr)
        return False
    if (
        report.skill_installed
        or report.hook_script_installed
        or report.settings_updated
    ):
        print(
            "simplicio: auto-activation installed in Claude Code "
            "(skill + UserPromptSubmit hook). "
            "Disable next time with SIMPLICIO_SKIP_AUTO_INIT=1.",
            file=sys.stderr,
        )
        return True
    return False


def _dispatch_nested(argv: list[str]) -> int | None:
    if argv and argv[0] == "scratch":
        maybe_autoinstall("scratch")
        from .scratch.cli import main as scratch_main

        return scratch_main(argv[1:])
    if argv and argv[0] == "skill":
        maybe_autoinstall("skill")
        args = argv[1:]
        if not args or args[0] != "new":
            print(
                'usage: simplicio skill new "<description>" [--planner ...] [--dry-run]',
                file=sys.stderr,
            )
            return 2
        from .scratch.skill_opt import main as skill_main

        return skill_main(args[1:])
    return None


def _add_task_args(p: argparse.ArgumentParser, *, target_required: bool) -> None:
    p.add_argument("goal")
    p.add_argument("--root", default=".")
    p.add_argument("--stack", default="angular")
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
        help="force the in-process local model (Qwen2.5-Coder-1.5B GGUF, "
        "no API key); overrides SIMPLICIO_MODEL/SIMPLICIO_BASE_URL",
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
        # Force Path 4: pin the local model and drop any HTTP endpoint so the
        # in-process llama backend wins regardless of the ambient config.
        os.environ["SIMPLICIO_MODEL"] = "local-llama/default"
        os.environ.pop("SIMPLICIO_BASE_URL", None)


def _run_task_command(a: argparse.Namespace) -> int:
    from .pipeline import run, run_task

    _force_local_if_requested(a)
    stack = a.stack or "angular"
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
        print("simplicio run --scope feature requires --stack <slug>", file=sys.stderr)
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
        print(f"simplicio run: {exc}", file=sys.stderr)
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
        print("simplicio run --scope sprint requires --max-cost", file=sys.stderr)
        return 2
    if not a.stack:
        print("simplicio run --scope sprint requires --stack <slug>", file=sys.stderr)
        return 2
    from .dod import load_dod, load_sprint_dod, run_dod_gates
    from .orchestrator import run_feature
    from .orchestrator.cost_governor import CostGovernor, provider_budget
    from .sprint_loader import load_sprint

    sprint_name = a.sprint or _infer_sprint_name(a.goal)
    if not sprint_name:
        print("simplicio run --scope sprint requires --sprint sprint-XX", file=sys.stderr)
        return 2

    try:
        sprint = load_sprint(a.root, sprint_name)
    except FileNotFoundError as exc:
        print(f"simplicio run: {exc}", file=sys.stderr)
        return 2

    try:
        CostGovernor.from_value(a.max_cost)
    except ValueError as exc:
        print(f"simplicio run: {exc}", file=sys.stderr)
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
        print(f"simplicio run: sprint has no task specs: {sprint.root}", file=sys.stderr)
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
                print(f"simplicio run: {exc}", file=sys.stderr)
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


def _run_status_command(a: argparse.Namespace) -> int:
    state_path = Path(a.root) / ".simplicio" / "sprint_state.json"
    if not state_path.is_file():
        payload = {"state": "none", "path": str(state_path)}
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"no simplicio sprint state at {state_path}")
        return 0
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"simplicio status: invalid state file: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(payload, sort_keys=True))
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


def _run_run_command(a: argparse.Namespace) -> int:
    from .intent import AUTO_CONFIDENCE_THRESHOLD, classify_goal

    result = classify_goal(a.goal, explicit_scope=a.scope)
    if result.confidence < AUTO_CONFIDENCE_THRESHOLD:
        print(
            "simplicio run: goal is ambiguous; pass --scope task|feature|sprint|scratch",
            file=sys.stderr,
        )
        return 2

    if result.scope == "task":
        if not a.target:
            a.target = _first_file_signal(result.signals)
        if not a.target and a.scope != "auto":
            a.target = _first_file_signal(classify_goal(a.goal).signals)
        if not a.target:
            print("simplicio run --scope task requires --target or a file in goal", file=sys.stderr)
            return 2
        return _run_task_command(a)
    if result.scope == "scratch":
        return _run_scratch_command(a)
    if result.scope == "feature":
        return _run_feature_command(a)
    if result.scope == "sprint":
        return _run_sprint_command(a)
    print(f"simplicio run: unsupported scope {result.scope!r}", file=sys.stderr)
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
        print(f"simplicio: ecosystem check skipped ({e})", file=sys.stderr)

    nested = _dispatch_nested(argv)
    if nested is not None:
        return nested

    ap = argparse.ArgumentParser(prog="simplicio")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="index/cache the repo (once, or after changes)")
    pi.add_argument("root_arg", nargs="?", help="project root; same as --root")
    pi.add_argument("--root", default=".")
    pi.add_argument("--stack", default="angular")

    pt = sub.add_parser("task", help="run a task")
    _add_task_args(pt, target_required=True)

    pr = sub.add_parser("run", help="run a task, feature, sprint, or scratch goal")
    _add_run_args(pr)

    pb = sub.add_parser("bench", help="compare with vs without (real numbers)")
    pb.add_argument("--root", default=".")
    pb.add_argument("--stack", default="angular")
    pb.add_argument("--cases", default="bench/cases.json")

    pc = sub.add_parser("cache", help="inspect or clear completion cache")
    pc_sub = pc.add_subparsers(dest="cache_cmd", required=True)
    pc_stats = pc_sub.add_parser("stats", help="print completion cache statistics")
    pc_stats.add_argument("--json", action="store_true")
    pc_clear = pc_sub.add_parser("clear", help="clear completion cache")
    pc_clear.add_argument("--force", action="store_true", help="required to clear")

    sub.add_parser(
        "smoke", help="one proof call: connect+generate (needs SIMPLICIO_MODEL+KEY)"
    )

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

    p_status = sub.add_parser("status", help="show current simplicio run state")
    p_status.add_argument("--root", default=".")
    p_status.add_argument("--json", action="store_true")

    p_env_export = sub.add_parser(
        "env-export",
        help="print shell-safe exports from a dotenv file without sourcing it",
    )
    p_env_export.add_argument("env_file")
    p_env_export.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)
    maybe_autoinstall(a.cmd)
    if a.cmd == "index":
        from .precedent import index_repo

        index_repo(a.root_arg or a.root, a.stack)
    elif a.cmd == "smoke":
        from .providers import generate, info

        print("provider:", info())
        out = generate("Reply exactly: OK simplicio connected.")
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
                print("simplicio cache clear requires --force", file=sys.stderr)
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
    elif a.cmd == "env-export":
        from .runtime_env import parse_env_file, shell_export_lines

        try:
            values = parse_env_file(a.env_file)
        except OSError as exc:
            print(f"simplicio env-export: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"simplicio env-export: {exc}", file=sys.stderr)
            return 2
        if a.json:
            print(json.dumps(values, sort_keys=True))
        else:
            print("\n".join(shell_export_lines(values)))
        return 0
    elif a.cmd == "task":
        return _run_task_command(a)
    elif a.cmd == "run":
        return _run_run_command(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
