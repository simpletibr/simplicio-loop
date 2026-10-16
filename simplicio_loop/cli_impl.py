"""CLI implementation: install skills/hooks and expose task-contract utilities."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import io
import itertools
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
try:
    from . import prototype_cli as _prototype_cli
except Exception:  # pragma: no cover - keeps `simplicio-loop` importable if this is missing
    _prototype_cli = None

from . import __version__
from .state_dir import ensure_state_dir
from .checkpoint_lifecycle import CheckpointLifecycle, LifecycleError
from . import delivery
from .drain import (
    SCHEMA as DRAIN_SCHEMA,
    DrainReceiptError,
    evaluate_drain,
    load_drain_receipt,
    persist_drain_receipt,
)
def _lazy_runner(name: str):
    """The ``runner`` function ``name``, looked up on first call: importing ``runner`` costs ~140 ms and most commands never call it."""
    def call(*args, **kwargs):
        from . import runner
        return getattr(runner, name)(*args, **kwargs)
    call.__name__ = call.__qualname__ = name
    return call


arm_run = _lazy_runner("arm_run")
conduct_run = _lazy_runner("conduct_run")
apply_human_decision = _lazy_runner("apply_human_decision")
change_phase = _lazy_runner("change_phase")
defer_maintenance_backlog_only = _lazy_runner("defer_maintenance_backlog_only")
execute_operator = _lazy_runner("execute_operator")
execute_operator_batch = _lazy_runner("execute_operator_batch")
read_status = _lazy_runner("read_status")
reconcile_delivery = _lazy_runner("reconcile_delivery")
sync_source_state = _lazy_runner("sync_source_state")
verify_run = _lazy_runner("verify_run")
from .loop_execution_receipt import (
    SCHEMA as LOOP_EXECUTION_SCHEMA,
    publish_loop_execution_for_flow,
)
from .execution_adapters import expected_governor_blocked, persist_execution_envelope
from .task_contract import EXAMPLE_TASK, compile_many, main as task_contract_main, preview_contract
from . import next_step
from .ops_ledger import (
    CONTEXT_SCHEMA,
    HANDSHAKE_SCHEMA,
    REQUIRED_CONTEXT_FIELDS,
    EventLedger,
    LedgerError,
    validate_handshake,
)
from . import inspection_cli as _inspection_cli
from .progress import stream as stream_progress
from .oracle import evaluate_matrix, persist_completion_receipt
from .delivery import DELIVERY_ORDER
from .evidence import redact_sensitive_text
from .economy_profile import (
    llm_max_speed_orientation_contract,
    prism_batches,
    prism_is_eligible,
    resolve_prism_batch_size,
)
from .auth_cli import configure_commands as configure_auth_commands, dispatch as dispatch_auth
from . import setup_cli
from .distribution import bundle_root
from .map_service_cli import configure_commands as configure_map_commands, dispatch as dispatch_map
from .squads import configure_commands as configure_squads_commands, dispatch as dispatch_squads
from .serverless_deploy import build_plan as build_serverless_plan, execute_plan as execute_serverless_plan
from .json_order import stable_first

# Command groups (#1818): cli_impl re-exports everything it used to define, so the cli facade, tests and
# monkeypatching of cli_impl keep working. Each group module owns its names.  # noqa: F401
from .cli_commands.install import (
    _copy_tree, _resync_hosts, _install_lines, install, add_install, add_update,
)
from .cli_commands.dashboard import (
    _pid_file, _gui_available, _port_up, _stop_dashboard, dashboard, add_dashboard,
)
from .cli_commands.turbo import (
    add_turbo,
)
from .cli_commands.plan import (
    _write_task_contract, plan, prepare, run, _ORIGINAL_RUN, _redirect_run_to_wave, add_task,
    add_prototype, add_plan, add_prepare,
)
from .cli_commands.orient_mapper import (
    ORIENT_SCHEMA, ORIENT_RECEIPT_SCHEMA, _DEFAULT_MAPPER_INDEX_TIMEOUT_S,
    _mapper_index_timeout_seconds, _DEFAULT_ORIENT_BUDGET_S, _orient_budget_seconds,
    MapperIndexTimedOut, MapperIndexRunning, OrientBudgetExceeded, _orient_deadline,
    _orient_remaining, _current_tree_state, _ensure_project_map, _MAPPER_INDEX_LOCK_NAME,
    _MAPPER_INDEX_LOG_NAME, _mapper_index_running_info, _mapper_index_reconcile_finished,
    _wait_for_exit, _ensure_project_map_bounded,
)
from .cli_commands.orient import (
    _orient_hash, _orient_revision, _orient_provider_provenance, COMMAND_CARD_SCHEMA,
    COMMAND_CARD_MAX_BYTES, TURBO_EXECUTE_RULE, turbo_command, delivery_flow_commands,
    _orient_command_card, _orient_route, _seal_orient_payload, _mapper_orient_fallback,
    _orient_extract_fallback_reason, _orient_context_summary, _orient_trim_verbose_fields,
    ORIENT_TARGETS_SCHEMA, _ORIENT_IDENTIFIER_RE, _ORIENT_WORD_SPLIT_RE, _ORIENT_SKIP_DIRS,
    _ORIENT_SOURCE_EXT, ORIENT_TARGET_MAX_FILES, ORIENT_TARGET_MAX_TOTAL_BYTES,
    ORIENT_TARGET_FULL_FILE_MAX_BYTES, ORIENT_TARGET_SPAN_CONTEXT_LINES,
    ORIENT_TINY_REPO_FILE_LIMIT, _orient_split_identifier, _orient_task_terms,
    _orient_iter_source_files, _orient_file_score, _orient_lexical_rank_candidates,
    _orient_sibling_test_paths, _orient_line_numbered, _orient_symbol_span,
    _orient_build_target_entry, _orient_target_seed_candidates, _orient_build_targets,
    _ORIENT_GIT_CHECK_TIMEOUT_S, _is_git_worktree, _orient_not_a_git_repo_payload, _orient_core,
    _brief_dump, _mapper_index_budget_payload, orient, _orient_impl, add_orient, add_apply,
    add_retrieve,
)
from .cli_commands.orient_brief import (
    ORIENT_BRIEF_SCHEMA, ORIENT_BRIEF_TARGET_CAP_BYTES, _brief_head_tail, _brief_suggest_checks,
    ORIENT_BRIEF_TOTAL_BUDGET_BYTES, _brief_order_candidates_named_first, _brief_clip_to_budget,
    _brief_build_targets, _brief_plan_groups, _brief_annotate_route_next, _brief_apply_command,
    _orient_brief_impl, orient_brief,
)
from .cli_commands.execution import (
    _dispatch_failure_payload, _dispatch_exit_code, _reconcile_prism_wave, _public_flow_run_dir,
    _attach_dispatch, _finalize_public_flow, _public_flow_from_status, _persist_prism_wave_receipt,
    resume, tick, batch, cancel, add_resume, add_tick, add_batch, add_wave, add_prism, add_cancel,
)
from .cli_commands.status import (
    _render_status_text, status, progress, preflight, verify, add_status, add_preflight,
    add_verify, add_progress,
)
from .cli_commands.lifecycle import (
    checkpoint_lifecycle, oracle, maintenance_deferred, deliver, decide, sync_source, add_oracle,
    add_checkpoint, add_maintenance, add_deliver, add_decide, add_sync_source,
)
from .cli_commands.drain import (
    _drain_cli_failure, _read_drain_snapshot, _valid_drain_result, drain, add_drain,
)
from .cli_commands.ledger import (
    _load_handshake, ledger_replay, findings_command, retrospective_command, add_ledger,
)
from .cli_commands.doctor import (
    extensions_doctor, _load_stack_components, stack_command, stack_doctor_command,
    source_doctor_command, add_extensions, add_stack, add_doctor, add_inspect,
)
from .cli_commands.economy import (
    economy_command, add_economy,
)

BUNDLE = bundle_root()  # importlib.resources, not a source-tree path: the same call works from a frozen binary
DASHBOARD = BUNDLE / "hooks" / "simplicio_dashboard.py"


def _prose_words(argv: Sequence[str]) -> list[str]:
    return list(itertools.takewhile(lambda item: not item.startswith("-"), argv))


def _prose_as_turbo(argv: Sequence[str]) -> list[str]:
    """`simplicio-loop "<task>" [flags]` runs `simplicio-loop turbo --repo . --task "<task>" [flags]`."""
    words = _prose_words(argv)
    return ["turbo", "--repo", ".", "--task", " ".join(words), *argv[len(words):]]


_WATCH247_QUIET = ("The GitHub token is never an argument: pipe it to --github-token-stdin (with --email), "
                   "or run `watch247 setup` in a terminal for a hidden prompt. See --help.")


class _Parser(argparse.ArgumentParser):
    """``ArgumentParser`` whose ``quiet`` instances never repeat what the user typed.

    argparse puts the offending value into its own errors (``ignored explicit argument 'ghp_...'``, ``invalid
    choice: 'ghp_...'``, ``unrecognized arguments: ...``, ``ambiguous option: --x=ghp_... could match``). For a command
    that is asked for a secret, a slip of the keys would print that secret in the user's terminal. A quiet parser prints
    its usage and a fixed message. The parent reports the arguments a subcommand left unrecognized, so it is quiet too
    whenever the command line names that subcommand.
    """

    def __init__(self, *args: Any, quiet: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._quiet = quiet

    def error(self, message: str):  # type: ignore[override]
        if not self._quiet:
            super().error(message)
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments; what you typed is not repeated. {self._quiet}\n")


def _finish_pending_update() -> None:
    """Windows binary: a verified file that `update` staged replaces the running one at the next start."""
    from .self_update import apply_pending
    try:
        if apply_pending():
            print("simplicio-loop: the staged update is in place. Run: simplicio-loop install --global", file=sys.stderr)
    except OSError as exc:
        print(f"simplicio-loop: could not apply the staged update: {exc}", file=sys.stderr)


def main(argv=None) -> int:
    argv_list = list(argv) if argv is not None else list(sys.argv[1:])
    if os.name == "nt" and getattr(sys, "frozen", False):
        _finish_pending_update()
    if argv_list[:1] == ["hub-drain-plan"]:
        from .github_drain_intake_cli import main as drain_intake_main
        forwarded = argv_list[1:]
        return drain_intake_main(forwarded[1:] if forwarded[:1] == ["--"] else forwarded)
    if argv_list[:1] == ["tasks"]:
        from .tasks_cli import main as tasks_main
        return tasks_main(argv_list[1:])
    if argv_list[:1] == ["intake"]:
        from .intake_cli import main as intake_main
        return intake_main(argv_list[1:])
    if argv_list[:1] == ["handoff"]:
        from .handoff_cli import main as handoff_main
        return handoff_main(argv_list[1:])
    if argv_list[:1] == ["author"]:
        from .author_cli import main as author_main
        return author_main(argv_list[1:])
    if argv_list[:1] == ["run"]:
        return _redirect_run_to_wave(argv_list[1:])
    if argv_list[:1] == ["daemon"]:  # never a task: the frozen binary and Windows reach this parser with it (#1633)
        from .frozen import daemon_command
        return daemon_command(argv_list[1:])
    parser = _Parser(
        prog="simplicio-loop",
        description=(
            "Install the simplicio-loop super-plugin, open the Token Monitor dashboard, "
            "or compile task markdown into a canonical task contract."
        ),
        quiet=_WATCH247_QUIET if "watch247" in argv_list else setup_cli.QUIET if "setup" in argv_list else "",  # a flag typed before the subcommand is echoed by this parser
    )
    parser.add_argument("-V", "--version", action="version", version=f"simplicio-loop {__version__}")
    # Bare `simplicio-loop` (no subcommand at all) falls through to `install` below with these
    # defaults — mirror p_install's own defaults here so that fallback doesn't crash with
    # AttributeError when no subparser ever ran to populate args.target/args.globally.
    parser.set_defaults(target=".", globally=False, prune_project_copies=False)
    sub = parser.add_subparsers(dest="command", parser_class=_Parser)

    add_install(sub)

    add_turbo(sub)

    add_update(sub)

    configure_auth_commands(sub)  # login, logout, auth status: one login shared with the Simplicio Runtime
    setup_cli.configure(sub)  # setup: prerequisites, agent CLIs and the GitHub login, after install

    add_dashboard(sub, argv_list)

    add_task(sub)

    add_prototype(sub)

    add_plan(sub)

    add_prepare(sub)

    add_orient(sub)

    add_apply(sub)

    add_retrieve(sub)

    add_extensions(sub)

    add_oracle(sub)

    add_status(sub)

    add_stack(sub)

    add_doctor(sub)

    add_inspect(sub)

    p_map = sub.add_parser("map", help="map-service cross-module status")
    map_sub = p_map.add_subparsers(dest="map_command", required=True)
    configure_map_commands(map_sub)

    p_squads = sub.add_parser("squads", help="plan squads and check the squad merge gate")
    configure_squads_commands(p_squads.add_subparsers(dest="squads_command", required=True))

    add_preflight(sub)

    add_economy(sub)

    p_ecc = sub.add_parser("ecc", help="inspect the opt-in ECC advisory integration")
    ecc_sub = p_ecc.add_subparsers(dest="ecc_command", required=True)
    p_ecc_doctor = ecc_sub.add_parser("doctor", help="verify ECC provenance and safety policy")
    p_ecc_doctor.add_argument("--repo", default=".", help="repository root")
    p_ecc_doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    p_deploy = sub.add_parser(
        "deploy", help="plan a gated serverless deployment (dry-run unless --apply is explicit)"
    )
    p_deploy.add_argument("--repo", default=".")
    p_deploy.add_argument("--backend", choices=("modal", "daytona"), default="modal")
    p_deploy.add_argument("--environment", default="")
    p_deploy.add_argument("--image", default="")
    p_deploy.add_argument("--apply", action="store_true")
    p_deploy.add_argument("--action-gate", action="store_true")

    add_verify(sub)

    p_watch247 = sub.add_parser(
        "watch247", help="run the 24/7 watcher for simplicio-* repos", allow_abbrev=False,
        quiet=_WATCH247_QUIET)
    p_watch247.add_argument("action", nargs="?", choices=["login-check", "setup"],
                            help="login-check: exec CLI logins (#1467); setup: first-run credentials")
    p_watch247.add_argument("--email", help="setup: the Simplicio account e-mail")
    p_watch247.add_argument("--github-token-stdin", action="store_true",
                            help="setup: read the GitHub token from stdin (never an argument: argv shows in ps)")
    p_watch247.add_argument("--check", action="store_true",
                            help="setup: only check the Simplicio account step (after the login); no token is asked")
    p_watch247.add_argument("--once", action="store_true", help="run one tick and exit")
    p_watch247.add_argument("--dry-run", action="store_true", help="simulate without mutations")
    p_watch247.add_argument("--state-dir", help="override state directory")
    p_watch247.add_argument(
        "--mode", choices=("batch", "lockfree"), default=None,
        help="merge train mode (default: batch, or SIMPLICIO_247_MERGE_MODE when set). batch: one cumulative test per batch of up to 4 approved PRs, bisect on red, "
             "serial merge. lockfree (opt-in, #1820): merge each approved PR whose targeted tests are green, run the impacted "
             "tests on main after it, and open a revert PR on red (never force-push, never merge a revert). The approval gate "
             "applies to both modes; a merge still needs SIMPLICIO_247_AUTO_MERGE=1. See docs/MERGE_LOCKFREE.md.")

    add_progress(sub)

    add_resume(sub)

    add_tick(sub)


    add_batch(sub)
    add_wave(sub)
    add_prism(sub)

    add_cancel(sub)

    add_checkpoint(sub)

    add_maintenance(sub)

    add_deliver(sub)

    add_decide(sub)

    add_sync_source(sub)

    add_drain(sub)
    p_slots = sub.add_parser("agent-slots", help="inspect and reclaim Loop-owned agent capacity")
    p_slots.add_argument("slot_args", nargs=argparse.REMAINDER,
                         help="pass-through args for the JSON-first agent slot registry")
    p_generation_broker = sub.add_parser(
        "generation-broker", help="operate persisted generation bindings")
    p_generation_broker.add_argument("broker_args", nargs=argparse.REMAINDER)
    p_queue = sub.add_parser("queue", help="operate the durable local task queue")
    p_queue.add_argument("--repo", default=".")
    p_queue.add_argument(
        "--route", choices=("legacy", "mapper"), default="mapper",
        help="storage route (default: mapper; use legacy only for compatibility actions)",
    )
    p_queue.add_argument("--mapper-db", default=None)
    p_queue.add_argument("--mapper-init", action="store_true")
    queue_sub = p_queue.add_subparsers(dest="queue_action", required=True)
    queue_help = {
        "status": "show queue health and pending work",
        "resume": "resume a legacy queue task",
        "doctor": "check queue storage and MapperStore readiness",
        "reclaim": "reclaim abandoned queue work",
    }
    for queue_action in ("status", "resume", "doctor", "reclaim"):
        queue_sub.add_parser(queue_action, help=queue_help[queue_action])
    queue_migrate = queue_sub.add_parser("migrate", help="migrate legacy queue state into MapperStore")
    queue_migrate.add_argument("--apply", action="store_true")
    queue_top = queue_sub.add_parser("top", help="list the highest-priority ready queue tasks")
    queue_top.add_argument("--limit", type=int, default=20)
    queue_drain = queue_sub.add_parser("drain", help="wait for active queue work to finish")
    queue_drain.add_argument("--timeout", type=float, default=0.0)
    queue_gc = queue_sub.add_parser("gc", help="garbage-collect retained queue state")
    queue_gc.add_argument("--apply", action="store_true")
    for queue_action in ("inspect", "cancel"):
        queue_help_text = {
            "inspect": "inspect one task by id",
            "cancel": "cancel one task by id",
        }
        queue_command = queue_sub.add_parser(queue_action, help=queue_help_text[queue_action])
        queue_command.add_argument("task_id")
    sub.add_parser(
        "hub-drain-plan",
        help="read-only PT-BR/EN GitHub drain intake; never executes the plan",
    )
    add_ledger(sub)

    if argv_list:
        from .github_drain_intake_cli import looks_like_natural_request, main as drain_intake_main
        if looks_like_natural_request(argv_list) and (
            argv_list[0] not in sub.choices or argv_list[0].lower() == "drain"
        ):
            return drain_intake_main(argv_list)
        if not argv_list[0].startswith("-") and argv_list[0] not in sub.choices:
            words = _prose_words(argv_list)
            if len(words) == 1 and not any(char.isspace() for char in words[0]):  # a mistyped command, not a task
                print(f"simplicio-loop: unknown command {words[0]!r}; valid commands: {', '.join(sorted(sub.choices))}; "
                      'a task is more than one word: simplicio-loop "<task>"', file=sys.stderr)
                return 2
            argv_list = _prose_as_turbo(argv_list)
    args = parser.parse_args(argv_list)
    command = args.command or "install"
    if command == "turbo":
        from .turbo_cli import run as run_turbo_cli
        return run_turbo_cli(args.repo, args.task, target=args.target, context=args.context,
                             tasks_file=args.tasks_file, verify=args.verify, apply=args.apply,
                             provider=args.provider, run_id=args.run_id,
                             leave_open=args.leave_open, windows=args.window)
    if command == "update":
        from .self_update import run_update, write_check
        return run_update(check=args.check, force=args.force, dry_run=args.dry_run, record=write_check)
    if command in {"login", "logout", "auth"}:
        return dispatch_auth(args)
    if command == "setup":
        return setup_cli.main(args)
    if command == "dashboard":
        from .dashboard import cli as dashboard_cli
        return dashboard_cli.run(args)
    if command == "task":
        forwarded = list(args.task_args or [])
        if forwarded and forwarded[0] == "--":
            forwarded = forwarded[1:]
        return task_contract_main(forwarded)
    if command == "prototype":
        if _prototype_cli is None:
            parser.error("prototype_cli module not importable")
        forwarded = list(args.prototype_args or [])
        if forwarded and forwarded[0] == "--":
            forwarded = forwarded[1:]
        return _prototype_cli.main(forwarded)
    if command == "plan":
        return plan(args.task, args.out)
    if command in {"prepare", "arm"}:
        if getattr(args, "example", False):
            sys.stdout.write(EXAMPLE_TASK)
            return 0
        if not args.task:
            parser.error("prepare requires --task <markdown file> (or --example to print a valid one)")
        return prepare(args.repo, args.task, args.delivery, args.max_iterations)
    if command == "orient":
        task_list = list(args.tasks or [])
        if not task_list:
            parser.error("orient requires at least one --task")
        return orient(args.repo, task_list[0], args.tee,
                      args.targets, args.verbose, args.brief, task_list, args.pretty)
    if command == "apply":
        from .apply import main as apply_main
        return apply_main(args.ops, args.repo, pretty=args.pretty)
    if command == "retrieve":
        from .tee_cache import retrieve
        try:
            print(retrieve(args.path, args.repo), end="")
            return 0
        except (OSError, ValueError) as exc:
            print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
            return 2
    if command == "extensions":
        return extensions_doctor(args.provider, args.policy, args.schema)
    if command == "oracle":
        return oracle(args.loop_dir, args.run_dir, args.response_text, args.flow_gap,
                      args.write_receipt)
    if command == "status":
        return status(args.repo, args.run_id, args.json, args.as_text)
    if command == "stack":
        return stack_command(args)
    if command == "doctor" and getattr(args, "doctor_command", None) == "stack":
        return stack_doctor_command(args)
    if command == "doctor" and getattr(args, "doctor_command", None) == "source":
        return source_doctor_command(args)
    if command == "doctor" and getattr(args, "doctor_command", None) == "mapper":
        from .mapper_doctor import main as mapper_doctor_main
        forwarded = ["--repo", args.repo]
        if args.mapper_json:
            forwarded.append("--json")
        return mapper_doctor_main(forwarded)
    if command == "doctor" and getattr(args, "doctor_command", None) in {"all", "login"}:
        from .doctor_overview import run as doctor_overview
        if args.doctor_command == "login":
            return doctor_overview(as_json=getattr(args, "login_json", False) or getattr(args, "json", False), only="login")
        return doctor_overview(as_json=getattr(args, "all_json", False) or getattr(args, "json", False),
                               online=getattr(args, "all_online", False) or getattr(args, "online", False))
    if command == "doctor" and not getattr(args, "storage", False):  # bare `doctor` executes overview (same as `doctor all`)
        from .doctor_overview import run as doctor_overview
        return doctor_overview(as_json=getattr(args, "json", False), online=getattr(args, "online", False))
    if command in {"doctor", "inspect"}:
        from .store_adapter import storage_cli
        forwarded = ["--route", args.route]
        if args.data_dir:
            forwarded += ["--data-dir", args.data_dir]
        if getattr(args, "repo", None):
            forwarded += ["--repo", args.repo]
        for capability in args.require_capability:
            forwarded += ["--require-capability", capability]
        return storage_cli(forwarded)
    if command == "map":
        return dispatch_map(args)
    if command == "squads":
        return dispatch_squads(args)
    if command == "preflight":
        return preflight(args.repo, args.json, strict=bool(getattr(args, "strict", False)))
    if command == "ecc":
        from .ecc_guidance import doctor_command
        return doctor_command(args.repo, as_json=bool(args.json))
    if command == "deploy":
        try:
            deploy_plan = build_serverless_plan(args.repo, backend=args.backend,
                                                environment=args.environment, image=args.image)
            result = execute_serverless_plan(deploy_plan, apply=args.apply,
                                             action_gate=args.action_gate)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if not args.apply or result.get("status") == "PLAN_READY" else 2
        except (ValueError, RuntimeError) as exc:
            print(json.dumps({"schema": "simplicio.loop-serverless-deploy/v1",
                              "status": "BLOCKED", "reason_code": type(exc).__name__,
                              "error": str(exc), "effects_attempted": False}, sort_keys=True))
            return 2
    if command == "findings":
        return findings_command(args)
    if command == "learn":
        if args.learn_command == "retrospective":
            return retrospective_command(args)
        parser.error("unknown learn command")
    if command == "economy":
        return economy_command(args)
    if command == "verify":
        return verify(args.repo, args.run_id)
    if command == "watch247" and args.action == "login-check":
        from .watcher247.login_check import main as login_check_main
        return login_check_main()
    if command == "watch247" and args.action == "setup":
        from .watcher247.onboarding import main as setup_main
        return setup_main(email=args.email, token_stdin=args.github_token_stdin,
                          state_dir=args.state_dir, check_only=args.check)
    if command == "watch247":
        import asyncio
        from .watcher247 import config as watcher247_config
        from .watcher247.__main__ import main as watcher247_main
        if args.state_dir:
            watcher247_config.set_state_dir(args.state_dir)
        if args.mode:  # the merge train's mode for this run (#1820); not given = batch, or whatever the environment already says
            from . import merge_lockfree
            os.environ[merge_lockfree.MODE_ENV] = args.mode
        return asyncio.run(watcher247_main(once=args.once, dry_run=args.dry_run))
    if command == "progress":
        run_id = args.run_id or args.run_flag
        # An omitted run id means the latest run in --repo, matching the
        # status command and keeping the public zero-config progress command
        # useful immediately after `run`.
        return progress(args.repo, run_id, args.fmt, args.once, args.interval,
                        args.no_animation, args.ascii_only)
    if command == "resume":
        return resume(args.repo, args.run_id)
    if command == "tick":
        return tick(args.repo, args.run_id, args.task_index, args.provider_worker)
    if command == "batch":
        batch_args = [args.repo, args.run_id, args.task_indices, args.max_workers,
                      args.retry_budget, args.serial, args.batch_size]
        if args.provider_worker is not None:
            batch_args.append(args.provider_worker)
        return batch(*batch_args)
    if command in {"wave", "prism"}:
        batch_args = [args.repo, args.run_id, args.task_indices, args.max_workers,
                      args.retry_budget, args.serial, args.batch_size]
        if args.provider_worker is not None:
            batch_args.append(args.provider_worker)
        return batch(*batch_args, flow=command)
    if command == "cancel":
        return cancel(args.repo, args.run_id)
    if command == "checkpoint":
        if args.lifecycle_action == "inspect":
            if len(args.candidate_id) != 1:
                parser.error("checkpoint inspect requires exactly one --candidate-id")
            args.candidate_id = args.candidate_id[0]
        return checkpoint_lifecycle(args)
    if command in {"maintenance-deferred", "defer-maintenance"}:
        return maintenance_deferred(
            args.repo, args.run_id, args.mode, args.disposition,
            args.correction_summary, args.deferral_reason,
            args.resume_instruction, args.evidence_status,
        )
    if command == "deliver":
        return deliver(args.repo, args.run_id, args.state, args.source_kind, args.payload_file)
    if command == "decide":
        return decide(args.repo, args.run_id, args.decision_id, args.answer, args.impact)
    if command == "sync-source":
        return sync_source(args.repo, args.run_id, args.source, args.external_repo, args.pr, args.tag)
    if command == "drain":
        return drain(args.action, args.snapshot_path, args.receipt_path, args.polls_required)
    if command == "agent-slots":
        from .agent_slots import cli_main as agent_slots_main
        forwarded = list(args.slot_args or [])
        if forwarded and forwarded[0] == "--":
            forwarded = forwarded[1:]
        return agent_slots_main(forwarded)
    if command == "generation-broker":
        from .generation_broker_cli import cli_main as generation_broker_main
        return generation_broker_main(list(args.broker_args or []))
    if command == "queue":
        from .local_task_queue_cli import cli_main as local_queue_main
        forwarded = ["--repo", args.repo, "--route", args.route]
        if args.mapper_db:
            forwarded += ["--mapper-db", args.mapper_db]
        if args.mapper_init:
            forwarded.append("--mapper-init")
        forwarded.append(args.queue_action)
        if args.queue_action == "top":
            forwarded += ["--limit", str(args.limit)]
        elif args.queue_action == "drain":
            forwarded += ["--timeout", str(args.timeout)]
        elif args.queue_action in {"gc", "migrate"} and args.apply:
            forwarded.append("--apply")
        elif args.queue_action in {"inspect", "cancel"}:
            forwarded.append(args.task_id)
        return local_queue_main(forwarded)
    if command == "ledger":
        return ledger_replay(
            args.path,
            args.compatibility,
            args.recover_trailing,
            args.handshake_json,
            args.handshake_file,
            args.ledger_command,
        )
    return install(
        Path(args.target).resolve(),
        args.globally,
        getattr(args, "host", "claude"),
        getattr(args, "dry_run", False),
        getattr(args, "uninstall", False),
        getattr(args, "verify", False),
        getattr(args, "check", False),
        getattr(args, "json", False),
        prune_project_copies=getattr(args, "prune_project_copies", False),
    )


if __name__ == "__main__":
    raise SystemExit(main())
