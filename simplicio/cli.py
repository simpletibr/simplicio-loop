"""CLI entrypoint for the Python Simplicio adapter.

Issue #103: this module is argparse construction + dispatch only. Every
subcommand's actual behavior lives in `simplicio/commands/<name>.py` (or, for
`doctor`/`init`/`detect`/`bench`, a thin `commands/<name>.py` adapter around
the pre-existing top-level implementation module of the same name) — see
each command module's docstring for what moved from here and why.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CLI_PROG = "simplicio-py"


def maybe_autoinstall(cmd: str | None) -> bool:
    """Install skill + hook on first run when Claude Code is detected."""
    import os

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
    if report.skill_installed or report.hook_script_installed or report.settings_updated:
        print(
            f"{CLI_PROG}: auto-activation installed in Claude Code "
            "(skill + UserPromptSubmit hook). "
            "Disable next time with SIMPLICIO_SKIP_AUTO_INIT=1.",
            file=sys.stderr,
        )
        return True
    return False


def _delegation_route(*, forced_python: bool, native_available: bool, delegated: bool) -> tuple[str, str]:
    """Classify a gate/nest delegation attempt into (route, reason) for
    `runtime_bridge.record_delegation` (issue #111)."""
    if forced_python:
        return "python-forced", "user-forced-python"
    if delegated:
        return "native", ""
    if not native_available:
        return "python-fallback", "binary-not-found"
    return "python-fallback", "delegation-error"


def _dispatch_nested(argv: list[str]) -> int | None:
    """``gate``/``nest``/``scratch``/``skill`` bypass the main argparse
    parser entirely — each owns its own argv[0]-based dispatch and arg
    parsing (unchanged by issue #103's cli.py cleanup)."""
    from .commands._shared import parse_rust_flags, try_route_via_simplicio
    from .runtime_bridge import record_delegation, simplicio_available

    def wants_help(args: list[str]) -> bool:
        return any(arg in {"-h", "--help"} for arg in args)

    if argv and argv[0] == "gate":
        clean_args, native, python = parse_rust_flags(argv[1:])
        if not wants_help(clean_args):
            native_available = simplicio_available()
            result = try_route_via_simplicio(
                "gate", clean_args, prefer_native=native or not python, prefer_python=python
            )
            route, reason = _delegation_route(
                forced_python=python, native_available=native_available, delegated=result is not None
            )
            record_delegation("gate", route, reason=reason or None)
            if result is not None:
                return result
        from .commands.gate import main as gate_main

        return gate_main(clean_args)
    if argv and argv[0] == "nest":
        clean_args, native, python = parse_rust_flags(argv[1:])
        if not wants_help(clean_args):
            native_available = simplicio_available()
            result = try_route_via_simplicio(
                "nest", clean_args, prefer_native=native or not python, prefer_python=python
            )
            route, reason = _delegation_route(
                forced_python=python, native_available=native_available, delegated=result is not None
            )
            record_delegation("nest", route, reason=reason or None)
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
    p.add_argument("goal", nargs="?")
    p.add_argument("--root", default=".")
    p.add_argument("--repo-root", default=None, help="declared repository root for the mutation contract")
    p.add_argument("--scope-root", default=None, help="declared writable scope root inside repo_root")
    p.add_argument("--context-snapshot-id", default=None, help="Mapper snapshot identity")
    p.add_argument("--context-pack-hash", default=None, help="Mapper ContextPack identity")
    p.add_argument("--stack", default=None)
    p.add_argument("--target", required=False)
    p.add_argument("--criteria", default="- true state\n- false state")
    p.add_argument("--constraints", default="- build passes")
    p.add_argument(
        "--dry-run-task",
        action="store_true",
        help="generate the would-be task output without applying/testing",
    )
    p.add_argument(
        "--verify-only",
        action="store_true",
        help="run SIMPLICIO_TEST_CMD without model generation or repository mutation",
    )
    p.add_argument("--json", action="store_true", help="emit stable structured task output")
    p.add_argument(
        "--bound-paths",
        action="append",
        default=[],
        help="glob limiting which paths the task may change; repeatable",
    )
    p.add_argument("--mode", choices=["auto", "integrated", "standalone"], default=None)
    task_spec_source = p.add_mutually_exclusive_group()
    task_spec_source.add_argument(
        "--task-spec",
        metavar="PATH",
        help="read one exported simplicio.task-spec/v2 JSON document from PATH",
    )
    task_spec_source.add_argument(
        "--task-spec-stdin",
        action="store_true",
        help="read one exported simplicio.task-spec/v2 JSON document from stdin",
    )
    p.add_argument("--context-snapshot", help="canonical Mapper ContextSnapshot JSON path")
    p.add_argument("--context-pack", help="canonical Mapper ContextPack JSON path")
    p.add_argument("--execution-context", help="Mapper execution-context/v1 provenance JSON path")
    p.add_argument("--effect-authorization", help="coordinator-issued EffectAuthorization JSON path")
    p.add_argument("--attempt-id", help="coordinator-owned atomic attempt ID")
    p.add_argument("--lease-id", help="coordinator-owned lease ID")
    p.add_argument("--fencing-token", help="coordinator-owned fencing token")
    p.add_argument("--context-handle", help="canonical snapshot ID bound to the attempt")
    p.add_argument("--coordinator-kind", help="coordinator type recorded in the execution profile")
    p.add_argument("--coordinator-id", help="coordinator identity recorded in the execution profile")


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("goal")
    p.add_argument("--scope", choices=["auto", "task", "feature", "sprint", "scratch"], default="auto")
    p.add_argument("--root", default=".")
    p.add_argument("--repo-root", default=None, help="declared repository root for the mutation contract")
    p.add_argument("--scope-root", default=None, help="declared writable scope root inside repo_root")
    p.add_argument("--context-snapshot-id", default=None, help="Mapper snapshot identity")
    p.add_argument("--context-pack-hash", default=None, help="Mapper ContextPack identity")
    p.add_argument("--stack", default=None)
    p.add_argument("--target")
    p.add_argument("--criteria", default="- true state\n- false state")
    p.add_argument("--constraints", default="- build passes")
    p.add_argument("--dry-run-task", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--bound-paths", action="append", default=[])
    p.add_argument("--max-cost", default=None)
    p.add_argument("--max-iter", type=int, default=3)
    p.add_argument("--sprint", help="sprint directory name, e.g. sprint-01")
    p.add_argument("--name", default=None, help="scratch project directory name")
    p.add_argument("--dest", default=".", help="scratch destination parent")
    p.add_argument("--planner", default=None, help="scratch planner override")
    p.add_argument("--plan-only", action="store_true", help="scratch plan only")
    p.add_argument("--skip-install", action="store_true", help="scratch skip install")
    p.add_argument("--slot", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--mode", choices=["auto", "integrated", "standalone"], default=None)
    p.add_argument("--context-snapshot", help="canonical Mapper ContextSnapshot JSON path")
    p.add_argument("--context-pack", help="canonical Mapper ContextPack JSON path")
    p.add_argument("--execution-context", help="Mapper execution-context/v1 provenance JSON path")
    p.add_argument("--effect-authorization", help="coordinator-issued EffectAuthorization JSON path")
    p.add_argument("--attempt-id", help="coordinator-owned atomic attempt ID")
    p.add_argument("--lease-id", help="coordinator-owned lease ID")
    p.add_argument("--fencing-token", help="coordinator-owned fencing token")
    p.add_argument("--context-handle", help="canonical snapshot ID bound to the attempt")
    p.add_argument("--coordinator-kind", help="coordinator type recorded in the execution profile")
    p.add_argument("--coordinator-id", help="coordinator identity recorded in the execution profile")


def _extract_global_verbosity(argv: list[str]) -> tuple[bool, bool, list[str]]:
    """Consume a leading ``--quiet``/``-q``/``--verbose``/``-v`` before the subcommand.

    Only flags appearing *before* the first positional token (the subcommand
    name) are treated as global verbosity controls for
    :func:`simplicio.observability.configure_logging` (issue #106). Any
    subcommand-local ``--quiet``/``--verbose`` (e.g. ``detect --quiet``,
    ``score-skill --verbose``) appear *after* the subcommand token and are
    left untouched, so this is purely additive — existing invocations are
    unaffected.
    """
    quiet = False
    verbose = False
    remaining: list[str] = []
    consuming_global = True
    for token in argv:
        if consuming_global and token in ("--quiet", "-q"):
            quiet = True
            continue
        if consuming_global and token in ("--verbose", "-v"):
            verbose = True
            continue
        if consuming_global and not token.startswith("-"):
            consuming_global = False
        remaining.append(token)
    return quiet, verbose, remaining


def _build_parser() -> argparse.ArgumentParser:
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

    p_smoke = sub.add_parser("smoke", help="check the deterministic-only adapter; never contacts an LLM")
    p_smoke.add_argument("--json", action="store_true")
    p_smoke.add_argument("--root", default=".")

    p_init = sub.add_parser("init", help="install skill + UserPromptSubmit hook into ~/.claude/")
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
    p_inspect.add_argument(
        "--context",
        action="store_true",
        help="explain why each Mapper file/symbol was selected",
    )
    p_inspect.add_argument("--json", action="store_true")

    p_intake = sub.add_parser(
        "intake",
        help="parse raw task cards into the provider-free TaskSpec v2 contract",
    )
    p_intake.add_argument("text", nargs="?", help="raw task text; defaults to stdin")
    p_intake.add_argument("--root", default=".", help="repository root used for plan-only mapper discovery")
    p_intake.add_argument("--file", help="read task Markdown/text from a file")
    p_intake.add_argument("--stdin", action="store_true", help="read task Markdown/text from stdin")
    p_intake.add_argument("--url", help="fetch task Markdown/text from an HTTP(S) URL")
    p_intake.add_argument("--source-url", help="preserve an external source URL without fetching it")
    p_intake.add_argument(
        "--validate-only",
        action="store_true",
        help="validate and wrap the TaskSpec in a validation result",
    )
    p_intake.add_argument(
        "--contract",
        action="store_true",
        help="compile each TaskSpec into an immutable ExecutionContract",
    )
    p_intake.add_argument(
        "--execution-mode",
        action="store_true",
        help="fail closed when the compiled contract is not executable",
    )
    p_intake.add_argument(
        "--plan-only",
        action="store_true",
        help="emit a contract-backed plan preview without dispatch or mutation",
    )
    p_intake.add_argument(
        "--batch-path",
        help="persist the frozen multi-task batch at this path (explicitly mutating)",
    )
    p_intake.add_argument("--json", action="store_true", help="emit stable structured JSON")

    p_doctor = sub.add_parser(
        "doctor",
        help="check deterministic readiness and dependency freshness",
    )
    p_doctor.add_argument("--json", action="store_true")
    p_doctor.add_argument("--list-tiers", action="store_true")
    p_doctor.add_argument("--no-check-updates", action="store_true")
    p_doctor.add_argument("--refresh", action="store_true")
    p_doctor.add_argument("--upgrade", action="store_true")

    p_fast = sub.add_parser("fast", help="negotiate optional Simplicio Fast capabilities")
    fast_sub = p_fast.add_subparsers(dest="fast_cmd", required=True)
    for fast_name, fast_help in (
        ("capabilities", "report versioned schemas, languages, commands and availability"),
        ("doctor", "diagnose Fast installation, compatibility, parser and snapshot"),
    ):
        p_fast_command = fast_sub.add_parser(fast_name, help=fast_help)
        p_fast_command.add_argument("--json", action="store_true", help="emit stable machine-readable JSON")
        p_fast_command.add_argument(
            "--offline",
            action="store_true",
            help="report an offline-safe installation correction without network access",
        )
        p_fast_command.add_argument(
            "--receipt",
            metavar="PATH",
            help="append a local metadata-only receipt; never includes source code",
        )
        if fast_name == "doctor":
            p_fast_command.add_argument(
                "--snapshot",
                metavar="PATH",
                help="validate a canonical Mapper snapshot without reading mmap internals",
            )

    p_versions = sub.add_parser(
        "versions",
        help=(
            "report simplicio-mapper installed/declared/tested versions, drift, "
            "and this repo's own component-release manifest (issue #232)"
        ),
    )
    p_versions.add_argument(
        "--root",
        default=None,
        help=(
            "simplicio-cli checkout to introspect for pyproject.toml/uv.lock/git commit "
            "(NOT the target project root); default: auto-detect (cwd, then this "
            "installed package's own directory)"
        ),
    )
    p_versions.add_argument("--json", action="store_true", help="machine-readable output")

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

    p_changeset = sub.add_parser(
        "changeset",
        help="execute simplicio.fast.changeset/v2 through the mechanical-edit boundary",
    )
    p_changeset.add_argument("--root", default=".", help="repository root")
    p_changeset.add_argument("--plan", default="-", help="changeset JSON path, or - for stdin")
    p_changeset.add_argument("--apply", action="store_true", help="atomically apply; default is dry-run")
    p_changeset.add_argument(
        "--current-generation",
        help="reject the changeset unless its generation matches this value",
    )
    p_changeset.add_argument("--json", action="store_true", help="emit a stable v2 receipt")

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
    p_file_read = file_sub.add_parser("read", help="print a file's contents, optionally sliced by line range")
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
        "--scenario",
        "-s",
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
        "--verbose",
        "-v",
        action="store_true",
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
    p_runtime_verify = runtime_sub.add_parser(
        "verify", help="verify the real reserved Simplicio Runtime identity and capabilities"
    )
    p_runtime_verify.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="optional Runtime probe deadline in seconds (default: no deadline)",
    )
    p_runtime_capabilities = runtime_sub.add_parser("capabilities")
    p_runtime_capabilities.add_argument("--root", default=".")
    p_runtime_capabilities.add_argument("--mode", choices=["auto", "integrated", "standalone"])
    p_runtime_capabilities.add_argument(
        "--context-snapshot", help="canonical Mapper ContextSnapshot JSON path"
    )
    p_runtime_capabilities.add_argument("--context-pack", help="canonical Mapper ContextPack JSON path")
    p_runtime_capabilities.add_argument(
        "--execution-context", help="Mapper execution-context/v1 provenance JSON path"
    )
    p_runtime_capabilities.add_argument(
        "--effect-authorization", help="coordinator-issued EffectAuthorization JSON path"
    )
    p_runtime_capabilities.add_argument("--attempt-id", help="coordinator-owned atomic attempt ID")
    p_runtime_capabilities.add_argument("--lease-id", help="coordinator-owned lease ID")
    p_runtime_capabilities.add_argument("--fencing-token", help="coordinator-owned fencing token")
    p_runtime_capabilities.add_argument("--context-handle", help="canonical snapshot ID bound to the attempt")
    p_runtime_capabilities.add_argument("--coordinator-kind")
    p_runtime_capabilities.add_argument("--coordinator-id")
    p_runtime_capabilities.add_argument("--json", action="store_true")

    p_prototype = sub.add_parser(
        "prototype", help="Prototype-First plan, scaffold, validate and promotion gate"
    )
    prototype_sub = p_prototype.add_subparsers(dest="prototype_cmd", required=True)
    p_proto_plan = prototype_sub.add_parser("plan")
    p_proto_plan.add_argument("--input", help="Loop/Mapper prototype-plan JSON")
    p_proto_plan.add_argument("--goal", default="")
    p_proto_plan.add_argument(
        "--type",
        dest="prototype_type",
        default="code_spike",
        choices=(
            "wireframe",
            "architecture_diagram",
            "schema",
            "data_model",
            "failing_reproducer",
            "benchmark_spike",
            "mock_or_fake",
            "code_spike",
            "vertical_slice",
            "prompt_candidate",
            "workflow_simulation",
            "storyboard",
            "policy_or_security_model",
        ),  # noqa: E501
    )
    p_proto_plan.add_argument("--root", default=".", help="source tree the plan's source_sha is anchored to")
    p_proto_plan.add_argument("--output", default=".simplicio/prototype-plan.json")
    p_proto_plan.add_argument("--json", action="store_true")
    for name in ("scaffold", "dry-run", "validate", "diff", "promote", "reject"):
        p = prototype_sub.add_parser(name)
        p.add_argument("--root", default=".")
        p.add_argument("--plan", required=True)
        p.add_argument("--candidate")
        p.add_argument("--target")
        p.add_argument("--receipt")
        p.add_argument("--decision")
        p.add_argument("--force", action="store_true")
        p.add_argument("--timeout", type=float, default=60.0)
        p.add_argument("--json", action="store_true")
    p_proto_doctor = prototype_sub.add_parser("doctor")
    p_proto_doctor.add_argument("--json", action="store_true")
    p_proto_batch = prototype_sub.add_parser(
        "batch", help="scaffold+validate many plans concurrently, bounded by --concurrency"
    )
    p_proto_batch.add_argument("--root", default=".")
    p_proto_batch.add_argument(
        "--plans", required=True, help="directory of plan JSON files, or a glob pattern"
    )
    p_proto_batch.add_argument(
        "--concurrency", type=int, default=4, help="max concurrent scaffold+validate workers"
    )
    p_proto_batch.add_argument("--force", action="store_true")
    p_proto_batch.add_argument("--timeout", type=float, default=60.0)
    p_proto_batch.add_argument("--json", action="store_true")

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
    p_mem_recall.add_argument("--mode", choices=("fts5", "vector", "hybrid"), default="hybrid")
    p_mem_recall.add_argument("--dir", default=None)
    p_mem_recall.add_argument("--json", action="store_true")
    p_mem_validate = memory_sub.add_parser("validate", help="audit markdown memory store integrity")
    p_mem_validate.add_argument("--dir", default=None)
    p_mem_validate.add_argument("--strict", action="store_true", help="exit 2 when validation fails")
    p_mem_validate.add_argument("--json", action="store_true")
    p_mem_handoff = memory_sub.add_parser(
        "handoff",
        help="build a deterministic cross-vendor handoff packet from recall hits",
    )
    p_mem_handoff.add_argument("query")
    p_mem_handoff.add_argument("--limit", type=int, default=5)
    p_mem_handoff.add_argument("--dir", default=None)
    p_mem_handoff.add_argument("--from-agent", default=None)
    p_mem_handoff.add_argument("--to-agent", default=None)
    p_mem_handoff.add_argument("--json", action="store_true")

    return ap


# Dispatch table: subcommand name -> `simplicio/commands/<name>.py`'s
# `run(a) -> int`. This is the entire body of what used to be a long
# if/elif chain in `main()` (issue #103).
_COMMAND_MODULES = {
    "index": "index",
    "task": "task",
    "run": "run",
    "bench": "bench",
    "cache": "cache",
    "smoke": "smoke",
    "init": "init",
    "detect": "detect",
    "status": "status",
    "claims": "claims",
    "inspect": "inspect",
    "intake": "intake",
    "doctor": "doctor",
    "fast": "fast",
    "versions": "versions",
    "env-export": "env_export",
    "changeset": "changeset",
    "file": "file",
    "test": "test",
    "token": "token",
    "runtime": "runtime",
    "prototype": "prototype",
    "memory": "memory",
}


def _main_unwrapped(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # Stage ABI mutations fail closed before verbosity/parser/dispatch can run.
    from .mutation_dispatch import guard_mutable_dispatch

    guard_mutable_dispatch(argv)

    quiet, verbose, argv = _extract_global_verbosity(argv)
    from .observability import configure_logging

    configure_logging(quiet=quiet, verbose=verbose)

    if argv and argv[0] in {"--version", "version"}:
        import json

        from .runtime_contracts import version_contract

        payload = version_contract()
        if "--json" in argv[1:]:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"{CLI_PROG} {payload['package']['version']}")
        return 0

    try:
        # Session-start ecosystem-freshness check (closes the runtime gap where
        # pyproject pins >=X but the installed version is older). Idempotent +
        # opt-in via SIMPLICIO_AUTO_UPGRADE=1. See simplicio/ecosystem.py.
        try:
            from .ecosystem import maybe_run_session_start

            maybe_run_session_start()
        except Exception as e:
            # Never let the freshness check break the CLI.
            print(f"{CLI_PROG}: ecosystem check skipped ({e})", file=sys.stderr)

        nested = _dispatch_nested(argv)
        if nested is not None:
            return nested

        ap = _build_parser()
        a = ap.parse_args(argv)
        maybe_autoinstall(a.cmd)

        # `mechanical-edit`/`edit`/`score-skill` need a little dispatch logic
        # of their own (edit falls back to mechanical-edit; score-skill tries
        # the Rust binary first) that doesn't fit the flat name->module table.
        if a.cmd == "mechanical-edit":
            from .commands.edit import run_mechanical_edit

            return run_mechanical_edit(a)
        if a.cmd == "edit":
            from .commands.edit import run_edit

            return run_edit(a)
        if a.cmd == "score-skill":
            from .commands.score_skill import run as score_skill_run

            return score_skill_run(a)

        module_name = _COMMAND_MODULES.get(a.cmd)
        if module_name is None:
            return 0
        import importlib

        command_module = importlib.import_module(f".commands.{module_name}", package=__package__)
        return command_module.run(a)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 130
    except Exception as exc:
        if verbose:
            raise
        print(f"{CLI_PROG}: error: {exc}", file=sys.stderr)
        return 1


def main(argv=None):
    """Run legacy commands directly or wrap Stage ABI mutations pre-to-post."""
    args = list(sys.argv[1:] if argv is None else argv)
    from .stage_main import run_stage_or_legacy

    return run_stage_or_legacy(args, _main_unwrapped)


if __name__ == "__main__":
    raise SystemExit(main())
