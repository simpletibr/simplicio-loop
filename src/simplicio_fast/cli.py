import argparse
import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .processor import ProjectProcessor, load_changeset
from .parser_adapter import adapter_capability, build_payload_from_mapper
from .mapper_ingest import MapperIngestError, validate_handoff
from .mapper_snapshot import compile_mapper_payload
from .rollout import RolloutController
from .snapshot import (
    DEFAULT_BUILD_TIMEOUT_SECONDS,
    DEFAULT_MAX_SOURCE_FILE_BYTES,
    Snapshot,
    SnapshotBuildTimeout,
    SourceParseError,
    StaleSnapshotError,
    build_snapshot,
)
from .adapters import capability_report
from .workspace import MANIFEST_SCHEMA, OVERLAY_SCHEMA, WorkspaceStore
from .engine import EngineSelection, EngineSelectionError
from .runtime_backend import (
    RuntimeBackendError,
    RuntimeSelection,
    select_runtime_backend as select_engine,
)
from .delivery import DeliveryEngine
from .query_planner import plan_query
from .navigation import DIRECTIONS, RELATIONS, NavigationBudget, NavigationIndex
from .rust_session import RustCoreSession, RustSessionError
from .semantic_scoring import (
    SemanticBudgets,
    SemanticScorer,
    SourceDocument,
    semantic_capabilities,
)
from .tokenizers import resolve_tokenizer
from .users.http import serve
from .users.repository import JsonUserRepository
from .users.service import UserService
from .compatibility import compatibility_manifest
from .context_adapters import adapter_manifest
from .context_security import security_manifest
from .sdk import SDK_SCHEMA, SDK_SUPPORT_MATRIX

DEFAULT_STATE_DIR = ".simplicio/fast"
DEFAULT_SNAPSHOT = f"{DEFAULT_STATE_DIR}/project.sfast"
DEFAULT_MAPPER_MODE = "integrated"
WRITE_ALLOW_ENV = "SIMPLICIO_FAST_ALLOW_WRITE"
INTEGRATED_HANDOFF_REQUIRED = (
    "--mapper-handoff is required when --mapper-mode is integrated (the default). "
    "Pass a Mapper handoff JSON, or set --mapper-mode bootstrap for the explicit "
    "development fallback. Fast never silently bootstraps."
)
WRITE_DISABLED_MESSAGE = (
    "--write is disabled. Mutation owner is simplicio-dev-cli; Fast does not "
    "mutate source as the hot path. Dry-run is the default. Set "
    f"{WRITE_ALLOW_ENV}=1 only for the explicit bootstrap write path."
)
_RUST_SESSIONS: dict[str, RustCoreSession] = {}


class WriteDisabledError(ValueError):
    reason_code = "write_disabled"

    def __init__(self, message: str = WRITE_DISABLED_MESSAGE) -> None:
        super().__init__(message)


def _close_rust_sessions() -> None:
    for session in tuple(_RUST_SESSIONS.values()):
        close = getattr(session, "close", None)
        if close is not None:
            close()
    _RUST_SESSIONS.clear()


atexit.register(_close_rust_sessions)


def emit(value: object) -> None:
    # JSON is a machine-readable CLI contract.  Escape non-ASCII characters so
    # Windows consoles using a legacy code page cannot fail while emitting a
    # valid receipt containing source text or Unicode symbols.
    print(json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True))


def _cli_engine_receipt(
    selection: RuntimeSelection | EngineSelection,
) -> dict[str, object]:
    receipt = dict(selection.receipt())
    if isinstance(selection, RuntimeSelection):
        receipt.update(
            {
                "requested": selection.requested,
                "selected": selection.selected,
                "reason": selection.reason_code,
            }
        )
    return receipt


def source_commit(root: Path) -> tuple[str | None, str | None]:
    """Return the checked-out commit, or a reason when root is outside Git."""
    if not (root / ".git").exists():
        return None, "not_a_git_checkout"
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            close_fds=True,
        )
    except OSError:
        return None, "git_unavailable"
    commit = result.stdout.strip()
    if result.returncode or not commit:
        return None, "not_a_git_checkout"
    return commit, None


def _runtime_bridge_request(args: argparse.Namespace) -> tuple[str, dict[str, object], str]:
    if args.command == "stats":
        return "stats", {"snapshot": str(Path(args.snapshot))}, "simplicio.fast.stats/v1"
    if args.command == "query":
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        return (
            "query",
            {
                "snapshot": str(Path(args.snapshot)),
                "term": args.term,
                "limit": args.limit,
            },
            "simplicio.fast.query/v1",
        )
    if min(args.max_results, args.max_lines, args.max_bytes, args.max_tokens) < 1:
        raise ValueError("context limits must be positive")
    return (
        "context",
        {
            "snapshot": str(Path(args.snapshot)),
            "root": str(Path(args.root).resolve()),
            "term": args.term,
            "limit": args.max_results,
            "max_lines": args.max_lines,
            "max_bytes": args.max_bytes,
            "max_tokens": args.max_tokens,
        },
        "simplicio.fast.context/v1",
    )


def _rust_bridge(
    selection: RuntimeSelection | EngineSelection, args: argparse.Namespace
) -> dict[str, object] | None:
    """Dispatch read-only snapshot commands through the admitted backend."""
    if selection.selected != "rust" or args.command not in {
        "stats",
        "query",
        "context",
    }:
        return None
    operation, payload, expected_schema = _runtime_bridge_request(args)
    if isinstance(selection, RuntimeSelection):
        result = selection.execute(operation, payload)
        return {
            "schema": expected_schema,
            "engine": "rust",
            "transport": "hbp-stdio",
            **result,
        }
    executable = selection.executable
    if not executable:
        raise EngineSelectionError(
            {
                "schema": "simplicio.fast.engine-selection/v1",
                "requested": selection.requested,
                "selected": "unavailable",
                "reason": "rust_executable_missing_for_bridge",
                "executable": None,
                "manifest": selection.manifest,
            }
        )
    try:
        key = str(Path(executable).resolve())
        session = _RUST_SESSIONS.get(key)
        if session is None:
            session = RustCoreSession(executable, selection.manifest)
            _RUST_SESSIONS[key] = session
        result = session.call(operation, payload)
    except RustSessionError as error:
        raise RuntimeError(f"rust_bridge_failed: {error}") from error
    return {
        "schema": expected_schema,
        "engine": "rust",
        "transport": "resident-session",
        **result,
    }


def json_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", help="emit deterministic JSON (the default)"
    )


def add_mapper_mode_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mapper-mode",
        choices=("bootstrap", "integrated"),
        default=DEFAULT_MAPPER_MODE,
        help=(
            "snapshot input mode (default: integrated). Integrated consumes only "
            "the supplied canonical Mapper handoff; bootstrap is an explicit "
            "development fallback and never the default"
        ),
    )
    parser.add_argument(
        "--mapper-handoff",
        default=None,
        help=(
            "JSON file emitted by `simplicio-mapper fast-handoff` "
            "(required when --mapper-mode is integrated)"
        ),
    )


# Fast indexes the whole repository, so the handoff it asks for is unscoped;
# it is read from a pipe, never shown to an LLM, so the budget is only a cap.
MAPPER_HANDOFF_TOKEN_BUDGET = 2_000_000


def _mapper_json(mapper: str, verb: str, root: Path, *extra: str) -> dict[str, object]:
    result = subprocess.run(
        [mapper, verb, str(root), "--json", *extra],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    try:
        payload = json.loads(result.stdout or "")
    except json.JSONDecodeError:
        payload = None
    if result.returncode != 0 or not isinstance(payload, dict):
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()[:400]
        raise MapperIngestError("mapper_handoff_unavailable", f"simplicio-mapper {verb}: {detail}")
    return payload


def _request_mapper_handoff(root: Path) -> dict[str, object]:
    """Ask the installed Mapper for the canonical handoff (scan once if stale)."""
    mapper = shutil.which("simplicio-mapper")
    if mapper is None:
        raise MapperIngestError("mapper_missing", INTEGRATED_HANDOFF_REQUIRED)
    budget = ("--token-budget", str(MAPPER_HANDOFF_TOKEN_BUDGET))
    handoff = _mapper_json(mapper, "handoff", root, *budget)
    if handoff.get("ready") is not True:
        _mapper_json(mapper, "scan", root, "--sync")
        handoff = _mapper_json(mapper, "handoff", root, *budget)
    if handoff.get("ready") is not True:
        raise MapperIngestError("mapper_not_ready", str(handoff.get("reason") or "unknown"))
    return handoff


def _load_mapper_handoff(path: str | None, root: Path) -> dict[str, object]:
    if not path:
        return _request_mapper_handoff(root)
    try:
        handoff = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MapperIngestError("mapper_handoff_unreadable", f"{path}: {error}") from error
    if not isinstance(handoff, dict):
        raise ValueError("--mapper-handoff must contain a JSON object")
    return handoff


def _require_write_authorization() -> None:
    if os.environ.get(WRITE_ALLOW_ENV) != "1":
        raise WriteDisabledError()


def _compile_mapper_snapshot(
    root: Path, output: Path, mapper_handoff: dict[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    """Compile a `.sfast` projection from one validated Mapper handoff."""

    provenance = validate_handoff(root, mapper_handoff)
    payload = build_payload_from_mapper(root, mapper_handoff)
    compiled = compile_mapper_payload(
        root,
        payload,
        output,
        mapper_generation=str(provenance["generation"]),
        handoff_sha256=str(provenance["handoff_sha256"]),
        mapper_provenance=provenance,
    )
    return compiled, provenance


def snapshot_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-s",
        "--snapshot",
        default=DEFAULT_SNAPSHOT,
        help=f"snapshot path (default: {DEFAULT_SNAPSHOT})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simplicio-fast",
        description=(
            "Simplicio Fast is semantic project memory for AI coding tools.\n\n"
            "It ingests a repository into an incremental binary/mmap snapshot and returns\n"
            "bounded hash-verified context. Mapper owns canonical extraction; Fast owns\n"
            "cache, query and context; simplicio-dev-cli owns mechanical source mutation;\n"
            "Loop owns convergence. Fast does not mutate source as the hot path."
        ),
        epilog=(
            "Typical flow: ingest (Mapper handoff) -> context or query.\n"
            "Default --mapper-mode is integrated and requires --mapper-handoff.\n"
            "Mutation owner is simplicio-dev-cli. apply/delivery/--write remain for one\n"
            "cycle as dry-run by default; writes require SIMPLICIO_FAST_ALLOW_WRITE=1.\n"
            "Never read .sfast offsets directly: use versioned Fast or Mapper handles."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--fast-engine",
        choices=("auto", "rust", "python", "off"),
        default="auto",
        help="select the Fast engine: Rust only after a healthy probe, or Python fallback (default: auto)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("build", "refresh", "ingest"):
        command = commands.add_parser(
            name,
            help=(
                "build a snapshot, reusing unchanged files"
                if name == "build"
                else (
                    "incrementally refresh the snapshot after source changes"
                    if name == "refresh"
                    else "absorb a project into the binary semantic processor"
                )
            ),
            description=(
                "Publish a bounded snapshot under .simplicio/fast/project.sfast. "
                "Default --mapper-mode integrated projects a validated canonical "
                "Mapper handoff and fails closed without --mapper-handoff. "
                "Bootstrap mode is an explicit development-only choice."
            ),
        )
        command.add_argument(
            "root", nargs="?", default=".", help="repository root (default: .)"
        )
        command.add_argument(
            "-o",
            "--output",
            default=DEFAULT_SNAPSHOT,
            help=f"output snapshot path (default: {DEFAULT_SNAPSHOT})",
        )
        command.add_argument(
            "--timeout",
            type=float,
            default=DEFAULT_BUILD_TIMEOUT_SECONDS,
            help=f"maximum build time in seconds before failing without publishing (default: {DEFAULT_BUILD_TIMEOUT_SECONDS:g})",
        )
        command.add_argument(
            "--max-file-bytes",
            type=int,
            default=DEFAULT_MAX_SOURCE_FILE_BYTES,
            help=(
                "reject a source file larger than this before parsing "
                f"(default: {DEFAULT_MAX_SOURCE_FILE_BYTES})"
            ),
        )
        add_mapper_mode_arguments(command)
        json_option(command)
    query = commands.add_parser(
        "query",
        help="find classes and functions in a snapshot",
        description="Return matching semantic symbols as deterministic JSON.",
    )
    query.add_argument(
        "term", help="case-insensitive symbol or qualified-name substring"
    )
    snapshot_argument(query)
    query.add_argument(
        "--limit", type=int, default=50, help="maximum matches (default: 50)"
    )
    json_option(query)

    search = commands.add_parser(
        "search",
        help="search direct indexes by name, path or kind",
        description="Resolve symbols from direct indexes without deserializing the full symbol table.",
    )
    search.add_argument(
        "term", help="case-insensitive name or qualified-name substring"
    )
    snapshot_argument(search)
    search.add_argument(
        "--limit", type=int, default=50, help="maximum matches (default: 50)"
    )
    search.add_argument(
        "--prefix", action="store_true", help="match names beginning with term"
    )
    search.add_argument("--path", help="restrict matches to a relative source path")
    search.add_argument("--kind", choices=("class", "function", "async_function"))
    json_option(search)

    context = commands.add_parser(
        "context",
        help="return verified source spans for an LLM or agent",
        description=(
            "Resolve symbols through mmap, verify current source hashes and emit bounded source spans."
        ),
    )
    context.add_argument(
        "term", help="case-insensitive symbol or qualified-name substring"
    )
    context.add_argument("--root", default=".", help="repository root (default: .)")
    snapshot_argument(context)
    context.add_argument("--max-results", type=int, default=10)
    context.add_argument("--max-lines", type=int, default=120)
    context.add_argument("--max-bytes", type=int, default=32_000)
    context.add_argument("--max-tokens", type=int, default=8_000)
    json_option(context)

    navigate_command = commands.add_parser(
        "navigate",
        help="navigate one bounded structural hop from a canonical symbol handle",
        description="Python reference-engine navigation; use --fast-engine python until Rust parity exists.",
    )
    navigate_command.add_argument("handle", help="canonical snapshot symbol ID")
    navigate_command.add_argument("relation", choices=sorted(RELATIONS))
    navigate_command.add_argument("direction", choices=sorted(DIRECTIONS))
    snapshot_argument(navigate_command)
    navigate_command.add_argument("--max-nodes", type=int, default=20)
    navigate_command.add_argument("--max-bytes", type=int, default=8192)
    navigate_command.add_argument("--max-depth", type=int, default=1)
    navigate_command.add_argument("--cursor")
    navigate_command.add_argument("--generation")
    json_option(navigate_command)

    impact = commands.add_parser(
        "impact",
        help="return typed imports, references, calls and test relations",
        description="Return bounded deterministic impact relationships for a symbol or term.",
    )
    impact.add_argument("term", help="symbol, path or relation term")
    snapshot_argument(impact)
    impact.add_argument("--limit", type=int, default=100)
    json_option(impact)

    stats = commands.add_parser(
        "stats", help="show snapshot generation and section statistics"
    )
    snapshot_argument(stats)
    json_option(stats)

    query_plan = commands.add_parser(
        "query-plan",
        help="explain the deterministic index and budget plan for a query",
        description="Return QueryIR-style planning evidence without materializing source spans.",
    )
    query_plan.add_argument("term")
    snapshot_argument(query_plan)
    query_plan.add_argument(
        "--operation", choices=("query", "search", "context", "impact"), default="query"
    )
    query_plan.add_argument("--prefix", action="store_true")
    query_plan.add_argument("--path")
    query_plan.add_argument("--kind", choices=("class", "function", "async_function"))
    query_plan.add_argument("--max-results", type=int, default=50)
    query_plan.add_argument("--max-bytes", type=int, default=32_000)
    query_plan.add_argument("--max-tokens", type=int, default=8_000)
    json_option(query_plan)

    segments = commands.add_parser(
        "segments",
        help="publish, validate or map immutable snapshot sections",
        description="Expose the bounded segmented-storage contract without exposing raw snapshot offsets.",
    )
    segments.add_argument("action", choices=("publish", "validate", "map"))
    segments.add_argument(
        "--directory", required=True, help="segmented storage directory"
    )
    segments.add_argument(
        "--snapshot", default=DEFAULT_SNAPSHOT, help="source SFAST snapshot for publish"
    )
    segments.add_argument("--name", help="segment name for map")
    json_option(segments)

    for name in ("understand", "plan"):
        command = commands.add_parser(
            name,
            help=(
                "understand a task using bounded project context"
                if name == "understand"
                else "compile a task and semantic context into a PlanDAG"
            ),
        )
        command.add_argument("task", help="task or goal in natural language")
        command.add_argument("--root", default=".", help="repository root (default: .)")
        snapshot_argument(command)
        command.add_argument("--max-bytes", type=int, default=48_000)
        command.add_argument(
            "--max-file-bytes",
            type=int,
            default=DEFAULT_MAX_SOURCE_FILE_BYTES,
            help=(
                "reject a source file larger than this when bootstrapping a snapshot "
                f"(default: {DEFAULT_MAX_SOURCE_FILE_BYTES})"
            ),
        )
        command.add_argument(
            "--selection-mode",
            choices=("semantic", "legacy-regex"),
            default="semantic",
        )
        add_mapper_mode_arguments(command)

    delivery = commands.add_parser(
        "delivery",
        help=(
            "prepare a guarded delivery receipt; mutation owner is simplicio-dev-cli"
        ),
        description=(
            "Fast does not mutate source as the hot path. Mutation owner is "
            "simplicio-dev-cli. Delivery remains for one cycle as a dry-run "
            "receipt surface. --write requires SIMPLICIO_FAST_ALLOW_WRITE=1."
        ),
    )
    delivery.add_argument("task", help="task or issue text")
    delivery.add_argument("--root", default=".", help="repository root (default: .)")
    snapshot_argument(delivery)
    delivery.add_argument("--cache", default=None, help="delivery cache directory")
    delivery.add_argument(
        "--profile", choices=("full", "loop-standalone"), default="loop-standalone"
    )
    add_mapper_mode_arguments(delivery)
    delivery.add_argument(
        "--selection-mode",
        choices=("semantic", "legacy-regex"),
        default="semantic",
        help="bounded semantic ranking by default; legacy-regex is explicit fallback",
    )
    delivery.add_argument(
        "--tokenizer-id",
        default=None,
        help=(
            "optional exact tokenizer, e.g. tiktoken:cl100k_base or "
            "tiktoken:model:gpt-4o; unavailable providers use labeled estimates"
        ),
    )
    delivery.add_argument("--max-bytes", type=int, default=32_000)
    delivery.add_argument(
        "--changeset", default=None, help="optional simplicio.fast.changeset/v2 JSON"
    )
    delivery.add_argument(
        "--write",
        action="store_true",
        help=(
            "legacy bootstrap write; disabled unless SIMPLICIO_FAST_ALLOW_WRITE=1. "
            "Mutation owner is simplicio-dev-cli"
        ),
    )
    delivery.add_argument(
        "--idempotency-key", default=None, help="stable delivery replay key"
    )
    delivery.add_argument(
        "--runtime-transaction",
        default=None,
        help="coordinator-issued simplicio.effect-transaction/v1 JSON for Full writes",
    )

    apply_command = commands.add_parser(
        "apply",
        help=(
            "legacy dry-run changeset validator; mutation owner is simplicio-dev-cli"
        ),
        description=(
            "Fast does not mutate source as the hot path. Mutation owner is "
            "simplicio-dev-cli. This command remains for one cycle as a dry-run "
            "validator. --write requires SIMPLICIO_FAST_ALLOW_WRITE=1."
        ),
    )
    apply_command.add_argument(
        "changeset", help="path to simplicio.fast.changeset/v2 JSON"
    )
    apply_command.add_argument(
        "--root", default=".", help="repository root (default: .)"
    )
    apply_command.add_argument(
        "--write",
        action="store_true",
        help=(
            "legacy bootstrap write; disabled unless SIMPLICIO_FAST_ALLOW_WRITE=1. "
            "Mutation owner is simplicio-dev-cli"
        ),
    )

    changeset = commands.add_parser(
        "changeset",
        help="prepare, validate, inspect and materialize a binary changeset",
        description="Public binary changeset lifecycle; all output is versioned JSON.",
    )
    changeset_commands = changeset.add_subparsers(
        dest="changeset_action", required=True
    )

    prepare = changeset_commands.add_parser(
        "prepare", help="compile JSON intent into a sealed binary changeset"
    )
    prepare.add_argument("input_json", help="JSON file containing operations")
    prepare.add_argument("--root", default=".")
    prepare.add_argument("--output", required=True, help="output binary changeset path")
    for option in (
        "base-generation",
        "overlay-generation",
        "attempt",
        "worktree-id",
        "lease-id",
        "fencing-token",
    ):
        prepare.add_argument(f"--{option}", required=True)
    prepare.add_argument("--allowed-path", action="append", default=None)
    prepare.add_argument("--verification-command", action="append", default=[])

    validate_changeset = changeset_commands.add_parser(
        "validate", help="validate a binary changeset against source hashes"
    )
    validate_changeset.add_argument("binary")
    validate_changeset.add_argument("--root", default=".")
    validate_changeset.add_argument("--lease-id")
    validate_changeset.add_argument("--fencing-token")

    seal = changeset_commands.add_parser(
        "seal", help="copy and verify a binary changeset into a sealed output"
    )
    seal.add_argument("binary")
    seal.add_argument("--output", required=True)

    inspect_changeset = changeset_commands.add_parser(
        "inspect", help="inspect binary metadata without exposing offsets"
    )
    inspect_changeset.add_argument("binary")

    export_json = changeset_commands.add_parser(
        "export-json", help="export a binary changeset as versioned JSON"
    )
    export_json.add_argument("binary")

    materialize_changeset = changeset_commands.add_parser(
        "materialize",
        help=(
            "legacy materialize through Dev CLI; mutation owner is simplicio-dev-cli"
        ),
        description=(
            "Fast does not mutate source as the hot path. Mutation owner is "
            "simplicio-dev-cli. Dry-run is the default. --write requires "
            "SIMPLICIO_FAST_ALLOW_WRITE=1."
        ),
    )
    materialize_changeset.add_argument("binary")
    materialize_changeset.add_argument("--root", default=".")
    materialize_changeset.add_argument("--journal", required=True)
    materialize_changeset.add_argument(
        "--write",
        action="store_true",
        help=(
            "legacy bootstrap write; disabled unless SIMPLICIO_FAST_ALLOW_WRITE=1. "
            "Mutation owner is simplicio-dev-cli"
        ),
    )

    reconcile = changeset_commands.add_parser(
        "reconcile", help="reconcile a locked unknown Dev CLI effect before retry"
    )
    reconcile.add_argument("binary")
    reconcile.add_argument("--root", default=".")
    reconcile.add_argument("--journal", required=True)

    recover = changeset_commands.add_parser(
        "recover", help="recover an incomplete binary journal tail"
    )
    recover.add_argument("journal")
    recover.add_argument("--worktree-id", required=True)
    recover.add_argument("--lease-id", required=True)
    recover.add_argument("--fencing-token", required=True)

    doctor = commands.add_parser(
        "doctor",
        help="validate installation and snapshot integrity",
        description="Check Python, snapshot structure and query readiness; emits JSON.",
    )
    snapshot_argument(doctor)
    doctor.add_argument(
        "--installation",
        action="store_true",
        help="report local Python/Rust artifacts without downloading",
    )
    doctor.add_argument(
        "--smoke",
        action="store_true",
        help="run a disposable installed Python CLI smoke flow",
    )
    json_option(doctor)

    rollout = commands.add_parser(
        "rollout",
        help="record an atomic shadow/canary/integrated rollout receipt",
    )
    rollout.add_argument(
        "mode",
        choices=("shadow", "canary", "integrated", "fallback", "rollback"),
    )
    rollout.add_argument("--state", default=f"{DEFAULT_STATE_DIR}/rollout.json")
    rollout.add_argument("--generation")
    rollout.add_argument("--reason")

    server = commands.add_parser("serve", help="run the user CRUD proof-of-concept API")
    server.add_argument("--port", type=int, default=3000)

    base = commands.add_parser(
        "base", help="build an immutable canonical base generation"
    )
    base.add_argument("root", nargs="?", default=".")
    base.add_argument("--storage", default=None, help="generation storage directory")

    overlay = commands.add_parser("overlay", help="build an isolated worktree overlay")
    overlay.add_argument("root", nargs="?", default=".")
    overlay.add_argument("--storage", default=None)
    overlay.add_argument("--base-generation", required=True)
    overlay.add_argument("--worktree-id", required=True)

    delta = commands.add_parser(
        "delta", help="build a changed-path delta against a canonical base"
    )
    delta.add_argument("root", nargs="?", default=".")
    delta.add_argument("--storage", default=None)
    delta.add_argument("--base-generation", required=True)
    delta.add_argument("--worktree-id", required=True)
    delta.add_argument("--changed-path", action="append", default=None)
    delta.add_argument("--config-fingerprint", default=None)

    handoff = commands.add_parser(
        "handoff", help="emit canonical snapshot and changed-path delta handoff"
    )
    handoff.add_argument("root", nargs="?", default=".")
    handoff.add_argument("--storage", default=None)
    handoff.add_argument("--base-generation", required=True)
    handoff.add_argument("--worktree-id", required=True)
    handoff.add_argument("--delta-generation", default=None)
    handoff.add_argument("--changed-path", action="append", default=None)
    handoff.add_argument("--config-fingerprint", default=None)
    handoff.add_argument("--parity-snapshot", default=None)

    merge = commands.add_parser("merge", help="query a composed base plus overlay view")
    merge.add_argument("term", nargs="?", default="")
    merge.add_argument("--root", default=".")
    merge.add_argument("--storage", default=None)
    merge.add_argument("--base-generation", required=True)
    merge.add_argument("--worktree-id")
    merge.add_argument("--overlay-generation")
    merge.add_argument("--max-results", type=int, default=50)

    semantic = commands.add_parser(
        "semantic-score",
        help="rank bounded candidates with optional Runtime inference and deterministic fallback",
        description=(
            "Read canonical candidate handles/text from JSON and emit semantic-score/v1 rows. "
            "The CLI offline path never downloads a model and remains fully deterministic."
        ),
    )
    semantic.add_argument("query")
    semantic.add_argument("--generation", required=True)
    semantic.add_argument(
        "--candidates", required=True, help="JSON list of canonical_id/text records"
    )
    semantic.add_argument("--max-candidates", type=int, default=128)
    semantic.add_argument("--max-results", type=int, default=10)
    semantic.add_argument("--max-request-bytes", type=int, default=256_000)
    semantic.add_argument("--max-tokens", type=int, default=8_000)
    semantic.add_argument(
        "--no-model",
        action="store_true",
        help="explicitly select the deterministic offline lane (the CLI never loads a model)",
    )
    json_option(semantic)

    commands.add_parser("capabilities", help="report parser capability negotiation")

    mapper_payload = commands.add_parser(
        "parser-payload",
        help="compile a validated Mapper handoff into parser-adapter/v1 JSON",
    )
    mapper_payload.add_argument("root", nargs="?", default=".")
    mapper_payload.add_argument("--mapper-handoff", required=True)
    mapper_payload.add_argument("--output", default=None)
    json_option(mapper_payload)

    pin = commands.add_parser(
        "pin", help="acquire a lease protecting a generation from GC"
    )
    pin.add_argument("generation")
    pin.add_argument("--root", default=".")
    pin.add_argument("--storage", default=None)
    pin.add_argument("--owner", required=True)
    pin.add_argument("--ttl", type=float, default=3600)

    release = commands.add_parser("release", help="release a generation lease")
    release.add_argument("lease_id")
    release.add_argument("--root", default=".")
    release.add_argument("--storage", default=None)

    gc = commands.add_parser("gc", help="list or remove unleased generations")
    gc.add_argument("--root", default=".")
    gc.add_argument("--storage", default=None)
    gc.add_argument("--apply", action="store_true")

    watch = commands.add_parser(
        "watch", help="refresh an overlay once after source changes"
    )
    watch.add_argument("root", nargs="?", default=".")
    watch.add_argument("--storage", default=None)
    watch.add_argument("--base-generation", required=True)
    watch.add_argument("--worktree-id", required=True)

    # Accept the selector both before and after the subcommand.  Suppressing
    # the subparser default preserves an explicit top-level value.
    for command in commands.choices.values():
        command.add_argument(
            "--fast-engine",
            dest="fast_engine",
            choices=("auto", "rust", "python", "off"),
            default=argparse.SUPPRESS,
            help=argparse.SUPPRESS,
        )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if getattr(args, "write", False):
            _require_write_authorization()
        selection = select_engine(args.fast_engine)
        bridged = _rust_bridge(selection, args)
        if bridged is not None:
            emit(bridged)
            return 0
        if args.command in {"build", "refresh", "ingest"}:
            processor = ProjectProcessor(Path(args.root), Path(args.output))
            if args.command == "ingest":
                if args.mapper_mode == "integrated":
                    handoff = _load_mapper_handoff(args.mapper_handoff, Path(args.root).resolve())
                    compiled, provenance = _compile_mapper_snapshot(
                        Path(args.root).resolve(), Path(args.output), handoff
                    )
                    emit(
                        {
                            "schema": "simplicio.fast.ingest/v2",
                            "snapshot": str(Path(args.output)),
                            "mapper": provenance,
                            "projection": compiled,
                        }
                    )
                    return 0
                emit(
                    processor.ingest(
                        timeout_seconds=args.timeout,
                        max_file_bytes=args.max_file_bytes,
                    )
                )
                return 0
            if args.mapper_mode == "integrated":
                handoff = _load_mapper_handoff(args.mapper_handoff, Path(args.root).resolve())
                compiled, provenance = _compile_mapper_snapshot(
                    Path(args.root).resolve(), Path(args.output), handoff
                )
                emit(
                    {
                        "schema": "simplicio.fast.build/v1",
                        "version": __version__,
                        "snapshot": str(Path(args.output)),
                        "mapper": provenance,
                        "projection": compiled,
                    }
                )
                return 0
            emit(
                {
                    "schema": "simplicio.fast.build/v1",
                    "version": __version__,
                    "snapshot": str(Path(args.output)),
                    "metrics": asdict(
                        build_snapshot(
                            Path(args.root),
                            Path(args.output),
                            timeout_seconds=args.timeout,
                            max_file_bytes=args.max_file_bytes,
                        )
                    ),
                }
            )
        elif args.command == "query":
            if args.limit < 1:
                parser.error("--limit must be positive")
            with Snapshot(Path(args.snapshot)) as snapshot:
                emit(
                    {
                        "schema": "simplicio.fast.query/v1",
                        "snapshot_version": snapshot.format_version,
                        "snapshot_generation": snapshot.generation,
                        "snapshot_provenance": snapshot.provenance,
                        "matches": [
                            asdict(item)
                            for item in snapshot.find(args.term)[: args.limit]
                        ],
                    }
                )
        elif args.command == "search":
            if args.limit < 1:
                parser.error("--limit must be positive")
            with Snapshot(Path(args.snapshot)) as snapshot:
                matches = snapshot.search(
                    args.term, prefix=args.prefix, path=args.path, kind=args.kind
                )
                emit(
                    {
                        "schema": "simplicio.fast.search/v1",
                        "snapshot_version": snapshot.format_version,
                        "snapshot_generation": snapshot.generation,
                        "snapshot_provenance": snapshot.provenance,
                        "filters": {
                            "prefix": args.prefix,
                            "path": args.path,
                            "kind": args.kind,
                        },
                        "matches": [asdict(item) for item in matches[: args.limit]],
                    }
                )
        elif args.command in {"understand", "plan"}:
            processor = ProjectProcessor(Path(args.root), Path(args.snapshot))
            if args.mapper_mode == "integrated":
                handoff = _load_mapper_handoff(args.mapper_handoff, Path(args.root).resolve())
                _compile_mapper_snapshot(
                    Path(args.root).resolve(), Path(args.snapshot), handoff
                )
            if args.command == "understand":
                emit(
                    asdict(
                        processor.understand(
                            args.task,
                            max_bytes=args.max_bytes,
                            max_file_bytes=args.max_file_bytes,
                            selection_mode=args.selection_mode,
                        )
                    )
                )
            else:
                emit(
                    processor.plan(
                        args.task,
                        max_bytes=args.max_bytes,
                        max_file_bytes=args.max_file_bytes,
                        selection_mode=args.selection_mode,
                    )
                )
        elif args.command == "delivery":
            delivery_engine = DeliveryEngine(
                Path(args.root),
                Path(args.snapshot),
                Path(args.cache) if args.cache else None,
            )
            if args.changeset:
                runtime_transaction = None
                if args.runtime_transaction:
                    runtime_transaction = json.loads(
                        Path(args.runtime_transaction).read_text(encoding="utf-8")
                    )
                    if not isinstance(runtime_transaction, dict):
                        raise ValueError(
                            "--runtime-transaction must contain a JSON object"
                        )
                emit(
                    delivery_engine.deliver(
                        load_changeset(Path(args.changeset)),
                        profile=args.profile,
                        engine_receipt=_cli_engine_receipt(selection),
                        write=args.write,
                        idempotency_key=args.idempotency_key,
                        runtime_transaction=runtime_transaction,
                    )
                )
            else:
                mapper_handoff = None
                if args.mapper_mode == "integrated" or args.mapper_handoff:
                    mapper_handoff = _load_mapper_handoff(args.mapper_handoff, Path(args.root).resolve())
                emit(
                    delivery_engine.prepare(
                        args.task,
                        profile=args.profile,
                        engine_receipt=_cli_engine_receipt(selection),
                        mode=args.mapper_mode,
                        mapper_handoff=mapper_handoff,
                        selection_mode=args.selection_mode,
                        tokenizer_id=args.tokenizer_id,
                        tokenizer=resolve_tokenizer(args.tokenizer_id),
                    )
                )
        elif args.command == "changeset":
            from .binary_changeset import (
                BinaryChangeJournal,
                inspect_binary,
                materialize,
                prepare_from_json,
                read_binary,
                reconcile_unknown_effect,
            )

            action = args.changeset_action
            if action == "prepare":
                value = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("input_json must contain an object")
                changeset = prepare_from_json(
                    value,
                    root=Path(args.root),
                    base_generation=args.base_generation,
                    overlay_generation=args.overlay_generation,
                    attempt=args.attempt,
                    worktree_id=args.worktree_id,
                    lease_id=args.lease_id,
                    fencing_token=args.fencing_token,
                    allowed_paths=args.allowed_path,
                    verification_commands=args.verification_command,
                )
                emit(changeset.seal_to(Path(args.output)))
            elif action == "validate":
                changeset = read_binary(Path(args.binary))
                emit(
                    {
                        "schema": "simplicio.fast.binary-changeset-cli-validation/v1",
                        "status": "valid",
                        "changeset_id": changeset.changeset_id,
                        "validation": changeset.validate(
                            Path(args.root),
                            lease_id=args.lease_id,
                            fencing_token=args.fencing_token,
                        ),
                    }
                )
            elif action == "seal":
                emit(read_binary(Path(args.binary)).seal_to(Path(args.output)))
            elif action == "inspect":
                emit(inspect_binary(Path(args.binary)))
            elif action == "export-json":
                emit(read_binary(Path(args.binary)).to_dict())
            elif action == "materialize":
                changeset = read_binary(Path(args.binary))
                if not args.write:
                    emit(
                        {
                            "schema": "simplicio.fast.binary-changeset-cli-materialize/v1",
                            "status": "dry_run",
                            "changeset_id": changeset.changeset_id,
                            "validation": changeset.validate(Path(args.root)),
                            "write_required": True,
                        }
                    )
                else:
                    journal = BinaryChangeJournal(
                        Path(args.journal),
                        worktree_id=changeset.worktree_id,
                        lease_id=changeset.lease_id,
                        fencing_token=changeset.fencing_token,
                    )
                    receipt = materialize(changeset, Path(args.root), journal)
                    emit(receipt)
                    return (
                        0 if receipt.get("status") in {"applied", "idempotent"} else 1
                    )
            elif action == "reconcile":
                changeset = read_binary(Path(args.binary))
                journal = BinaryChangeJournal(
                    Path(args.journal),
                    worktree_id=changeset.worktree_id,
                    lease_id=changeset.lease_id,
                    fencing_token=changeset.fencing_token,
                )
                receipt = reconcile_unknown_effect(changeset, Path(args.root), journal)
                emit(receipt)
                return 0 if receipt.get("status") == "reconciled" else 1
            else:
                journal = BinaryChangeJournal(
                    Path(args.journal),
                    worktree_id=args.worktree_id,
                    lease_id=args.lease_id,
                    fencing_token=args.fencing_token,
                )
                emit(journal.recover())
        elif args.command == "apply":
            processor = ProjectProcessor(Path(args.root), Path(DEFAULT_SNAPSHOT))
            emit(
                processor.apply_changeset(
                    load_changeset(Path(args.changeset)), write=args.write
                )
            )
        elif args.command == "context":
            if (
                min(args.max_results, args.max_lines, args.max_bytes, args.max_tokens)
                < 1
            ):
                parser.error("context limits must be positive")
            root = Path(args.root).resolve()
            snapshot_path = Path(args.snapshot).resolve()
            limits = {
                "max_results": args.max_results,
                "max_lines": args.max_lines,
                "max_bytes": args.max_bytes,
                "max_tokens": args.max_tokens,
            }
            with Snapshot(snapshot_path) as snapshot:
                spans = snapshot.context(
                    root,
                    args.term,
                    max_results=args.max_results,
                    max_lines=args.max_lines,
                    max_bytes=args.max_bytes,
                    max_tokens=args.max_tokens,
                )
                commit, commit_reason = source_commit(root)
                emit(
                    {
                        "schema": "simplicio.fast.context/v1",
                        "snapshot_version": snapshot.format_version,
                        "limits": limits,
                        "provenance": {
                            "schema": "simplicio.fast.provenance/v1",
                            "repository_root": str(root),
                            "source_commit": commit,
                            "source_commit_reason": commit_reason,
                            "snapshot_path": str(snapshot_path),
                            "snapshot_sha256": snapshot.sha256,
                            "snapshot_generation": snapshot.generation,
                            "snapshot_provenance": snapshot.provenance,
                            "span_count": len(spans),
                            "limits": {
                                "max_results": args.max_results,
                                "max_lines": args.max_lines,
                                "max_bytes": args.max_bytes,
                                "max_tokens": args.max_tokens,
                            },
                        },
                        "spans": [asdict(item) for item in spans],
                    }
                )
        elif args.command == "navigate":
            if args.fast_engine != "python":
                raise RuntimeError("navigate_requires_explicit_python_engine")
            budget = NavigationBudget(
                max_nodes=args.max_nodes,
                max_bytes=args.max_bytes,
                max_depth=args.max_depth,
            )
            with Snapshot(Path(args.snapshot)) as snapshot:
                page = NavigationIndex(snapshot).navigate(
                    args.handle,
                    args.relation,
                    args.direction,
                    budget,
                    cursor=args.cursor,
                    generation=args.generation,
                )
                emit(page.to_dict())
        elif args.command == "impact":
            if args.limit < 1:
                parser.error("--limit must be positive")
            with Snapshot(Path(args.snapshot)) as snapshot:
                emit(
                    {
                        "schema": "simplicio.fast.impact/v1",
                        "snapshot_version": snapshot.format_version,
                        "snapshot_generation": snapshot.generation,
                        "snapshot_provenance": snapshot.provenance,
                        "query": args.term,
                        "relations": [
                            asdict(item)
                            for item in snapshot.impact(args.term)[: args.limit]
                        ],
                    }
                )
        elif args.command == "stats":
            with Snapshot(Path(args.snapshot)) as snapshot:
                emit({"schema": "simplicio.fast.stats/v1", "stats": snapshot.stats()})
        elif args.command == "query-plan":
            with Snapshot(Path(args.snapshot)) as snapshot:
                emit(
                    plan_query(
                        snapshot,
                        args.term,
                        operation=args.operation,
                        prefix=args.prefix,
                        path=args.path,
                        kind=args.kind,
                        max_results=args.max_results,
                        max_bytes=args.max_bytes,
                        max_tokens=args.max_tokens,
                    ).to_dict()
                )
        elif args.command == "segments":
            from .segments import SegmentStore

            store = SegmentStore(Path(args.directory))
            if args.action == "publish":
                emit(store.publish(Path(args.snapshot)))
            elif args.action == "validate":
                emit(store.validate())
            else:
                if not args.name:
                    raise ValueError("--name is required for segments map")
                with store.map(args.name) as mapped:
                    emit(
                        {
                            "schema": "simplicio.fast.segment-map/v1",
                            "name": args.name,
                            "bytes": len(mapped),
                            "sha256": hashlib.sha256(bytes(mapped)).hexdigest(),
                        }
                    )
        elif args.command == "doctor":
            if args.installation:
                from .installation import python_smoke, report

                payload = report()
                if args.smoke:
                    payload["python_smoke"] = python_smoke()
                emit(payload)
                return
            path = Path(args.snapshot)
            from .integrations import integration_status

            integration = integration_status()
            parser_adapter = adapter_capability()
            checks: list[dict[str, object]] = [
                {"name": "python", "status": "pass", "detail": sys.version.split()[0]},
                {
                    "name": "parser_adapter",
                    "status": "pass" if parser_adapter["health"] == "ready" else "fail",
                    "detail": parser_adapter,
                },
                {
                    "name": "snapshot_exists",
                    "status": "pass" if path.is_file() else "fail",
                    "detail": str(path),
                },
            ]
            if path.is_file():
                try:
                    with Snapshot(path) as snapshot:
                        checks.append(
                            {
                                "name": "snapshot_integrity",
                                "status": "pass",
                                "detail": snapshot.stats(),
                            }
                        )
                except (OSError, ValueError) as error:
                    checks.append(
                        {
                            "name": "snapshot_integrity",
                            "status": "fail",
                            "detail": {
                                "error": type(error).__name__,
                                "message": str(error),
                                "recovery_code": "snapshot_corrupt_rebuild",
                                "remediation": (
                                    "run simplicio-fast refresh . --json; source files remain "
                                    "authoritative and the replacement is validated before publication"
                                ),
                                "snapshot": str(path),
                            },
                        }
                    )
            snapshot_ready = all(check["status"] == "pass" for check in checks)
            integrated_ready = snapshot_ready and bool(integration["integrated_ready"])
            emit(
                {
                    "schema": "simplicio.fast.doctor/v1",
                    "ready": integrated_ready,
                    "integrated_ready": integrated_ready,
                    "integration": integration,
                    "parser_adapter": parser_adapter,
                    "checks": checks,
                }
            )
            if not integrated_ready:
                raise SystemExit(1)
        elif args.command == "rollout":
            emit(
                RolloutController(Path(args.state)).transition(
                    args.mode, generation=args.generation, reason=args.reason
                )
            )
        elif args.command == "serve":
            service = UserService(JsonUserRepository(Path("data/users.json")))
            print(f"simplicio-fast listening on http://127.0.0.1:{args.port}")
            serve(service, port=args.port)
        elif args.command == "base":
            manifest = WorkspaceStore(
                Path(args.root), Path(args.storage) if args.storage else None
            ).build_base()
            emit({"schema": MANIFEST_SCHEMA, "manifest": manifest.to_dict()})
        elif args.command == "overlay":
            overlay_value = WorkspaceStore(
                Path(args.root), Path(args.storage) if args.storage else None
            ).create_overlay(args.worktree_id, args.base_generation)
            emit({"schema": OVERLAY_SCHEMA, "overlay": asdict(overlay_value)})
        elif args.command == "delta":
            store = WorkspaceStore(
                Path(args.root), Path(args.storage) if args.storage else None
            )
            delta_value = store.create_delta(
                args.base_generation,
                args.worktree_id,
                args.changed_path,
                config_fingerprint=args.config_fingerprint,
            )
            emit({"schema": delta_value.schema, "delta": delta_value.to_dict()})
        elif args.command == "handoff":
            store = WorkspaceStore(
                Path(args.root), Path(args.storage) if args.storage else None
            )
            emit(
                store.handoff(
                    args.base_generation,
                    args.worktree_id,
                    args.changed_path,
                    delta_generation=args.delta_generation,
                    config_fingerprint=args.config_fingerprint,
                    parity_snapshot=Path(args.parity_snapshot)
                    if args.parity_snapshot
                    else None,
                )
            )
        elif args.command == "merge":
            if args.worktree_id and not args.overlay_generation:
                raise ValueError("--overlay-generation is required with --worktree-id")
            with WorkspaceStore(
                Path(args.root), Path(args.storage) if args.storage else None
            ).open(
                args.base_generation,
                worktree_id=args.worktree_id,
                overlay_generation=args.overlay_generation,
            ) as view:
                matches = (
                    view.find(args.term)[: args.max_results]
                    if args.term
                    else view.symbols()[: args.max_results]
                )
                emit(
                    {
                        "schema": "simplicio.fast.merge/v1",
                        "base_generation": view.base_generation,
                        "overlay_generation": view.overlay_generation,
                        "matches": [asdict(item) for item in matches],
                    }
                )
        elif args.command == "semantic-score":
            raw_candidates = json.loads(
                Path(args.candidates).read_text(encoding="utf-8")
            )
            if not isinstance(raw_candidates, list):
                raise ValueError("--candidates must contain a JSON list")
            candidates = []
            for raw in raw_candidates:
                if not isinstance(raw, dict):
                    raise ValueError("each semantic candidate must be an object")
                text = raw.get("text")
                canonical_id = raw.get("canonical_id")
                if not isinstance(text, str) or not isinstance(canonical_id, str):
                    raise ValueError(
                        "semantic candidates require canonical_id and text"
                    )
                if raw.get("source_sha256") is None:
                    candidates.append(
                        SourceDocument.create(
                            canonical_id,
                            text,
                            structural_score=float(raw.get("structural_score", 0.0)),
                        )
                    )
                else:
                    candidates.append(
                        SourceDocument(
                            canonical_id,
                            text,
                            raw["source_sha256"],
                            float(raw.get("structural_score", 0.0)),
                        )
                    )
            budgets = SemanticBudgets(
                max_candidates=args.max_candidates,
                max_selected=args.max_results,
                max_request_bytes=args.max_request_bytes,
                max_selected_tokens=args.max_tokens,
            )
            emit(
                SemanticScorer(budgets=budgets).score(
                    generation=args.generation,
                    query=args.query,
                    candidates=tuple(candidates),
                )
            )
        elif args.command == "parser-payload":
            root = Path(args.root).resolve()
            handoff = json.loads(Path(args.mapper_handoff).read_text(encoding="utf-8"))
            payload = build_payload_from_mapper(root, handoff)
            if args.output:
                output = Path(args.output).resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
                emit(
                    {
                        "schema": "simplicio.fast.parser-payload-receipt/v1",
                        "output": str(output),
                        "payload_sha256": payload["payload_sha256"],
                        "files": len(payload["files"]),
                        "symbols": len(payload["symbols"]),
                        "relations": len(payload["relations"]),
                    }
                )
            else:
                emit(payload)
        elif args.command == "capabilities":
            emit(
                {
                    "schema": "simplicio.fast.capabilities/v1",
                    "engine": _cli_engine_receipt(selection),
                    "engine_manifest": _cli_engine_receipt(selection),
                    "capabilities": [asdict(item) for item in capability_report()],
                    "parser_adapter": adapter_capability(),
                    "semantic_scoring": semantic_capabilities(),
                    "sdk": {
                        "schema": "simplicio.fast.sdk-capabilities/v1",
                        "sdk": SDK_SCHEMA,
                        "operations": [
                            "publish",
                            "compile_delta",
                            "query",
                            "query_async",
                            "snapshot",
                            "save",
                            "open",
                            "close",
                            "context",
                            "context_async",
                        ],
                        "support_matrix": [
                            {**item, "operations": list(item["operations"])}
                            for item in SDK_SUPPORT_MATRIX
                        ],
                        "compatibility": compatibility_manifest(),
                        "source_adapters": adapter_manifest(),
                        "context_security": security_manifest(),
                        "authority": "derived_read_only",
                    },
                }
            )
        elif args.command == "pin":
            lease = WorkspaceStore(
                Path(args.root), Path(args.storage) if args.storage else None
            ).pin(args.generation, args.owner, args.ttl)
            emit({"schema": "simplicio.fast.lease/v1", "lease": asdict(lease)})
        elif args.command == "release":
            WorkspaceStore(
                Path(args.root), Path(args.storage) if args.storage else None
            ).release_lease(args.lease_id)
            emit({"schema": "simplicio.fast.lease/v1", "released": args.lease_id})
        elif args.command == "gc":
            emit(
                WorkspaceStore(
                    Path(args.root), Path(args.storage) if args.storage else None
                ).gc(apply=args.apply)
            )
        elif args.command == "watch":
            store = WorkspaceStore(
                Path(args.root), Path(args.storage) if args.storage else None
            )
            overlay_value, _ = store.watch_once(args.worktree_id, args.base_generation)
            emit(
                {
                    "schema": "simplicio.fast.watch/v1",
                    "changed": overlay_value is not None,
                    "overlay": asdict(overlay_value) if overlay_value else None,
                }
            )
        return 0

    except EngineSelectionError as error:
        emit(error.receipt)
        raise SystemExit(2) from error
    except (
        FileNotFoundError,
        RuntimeError,
        ValueError,
        SnapshotBuildTimeout,
        StaleSnapshotError,
    ) as error:
        payload = {
            "schema": "simplicio.fast.error/v1",
            "error": type(error).__name__,
            "message": str(error),
        }
        if isinstance(error, RuntimeBackendError):
            payload.update(
                {
                    "reason_code": error.reason_code,
                    "detail": error.detail,
                }
            )
        reason_code = getattr(error, "reason_code", None)
        if isinstance(reason_code, str) and reason_code:
            payload["reason_code"] = reason_code
        if isinstance(error, SnapshotBuildTimeout):
            payload.update(
                {
                    "recovery_code": error.code,
                    "recovery": error.recovery,
                    "progress": error.progress,
                }
            )
        if isinstance(error, SourceParseError):
            payload.update(
                {
                    "reason_code": error.code,
                    "path": error.path,
                    "line": error.line,
                    "column": error.column,
                    "recovery": error.recovery,
                }
            )
        emit(payload)
        raise SystemExit(2) from error


if __name__ == "__main__":
    raise SystemExit(main())
