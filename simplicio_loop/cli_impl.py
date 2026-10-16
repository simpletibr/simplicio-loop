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

BUNDLE = bundle_root()  # importlib.resources, not a source-tree path: the same call works from a frozen binary
DASHBOARD = BUNDLE / "hooks" / "simplicio_dashboard.py"


def _orient_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _orient_revision(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(root), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            close_fds=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = (result.stdout or "").strip()
    return revision if result.returncode == 0 and revision else None


def _orient_provider_provenance(payload: Mapping[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or "")
    provider_payload = payload.get("mapper")
    provider_payload = provider_payload if isinstance(provider_payload, Mapping) else {}
    ingest = provider_payload.get("ingest") if isinstance(provider_payload.get("ingest"), Mapping) else {}
    mapper_result = provider_payload.get("result") if isinstance(provider_payload.get("result"), Mapping) else {}
    snapshot = mapper_result.get("source_snapshot") if isinstance(mapper_result.get("source_snapshot"), Mapping) else {}
    context_pack = mapper_result.get("context_pack") if isinstance(mapper_result.get("context_pack"), Mapping) else {}
    probe = ingest.get("probe") if isinstance(ingest.get("probe"), Mapping) else {}
    return {
        "operator": provider or None,
        "operator_version": probe.get("version"),
        "generation": provider_payload.get("generation") or ingest.get("generation") or snapshot.get("snapshot_id"),
        "context_hash": provider_payload.get("context_hash") or context_pack.get("pack_hash") or snapshot.get("root_hash"),
        "plan_hash": provider_payload.get("plan_hash"),
        "source_revision": ingest.get("source_commit") or snapshot.get("revision"),
        "provider_payload_hash": _orient_hash(provider_payload),
    }


COMMAND_CARD_SCHEMA = "simplicio.loop-command-card/v1"
COMMAND_CARD_MAX_BYTES = 1_500
TURBO_EXECUTE_RULE = (
    "simplicio-loop turbo prints a needs_plan request with the text of the files and one apply command: run "
    "that command once with your JSON plan as its heredoc body; dev-cli makes every edit; do not explore, "
    "list or read files, and do not run tests yourself"
)


def turbo_command(root: Path, tasks: Sequence[str] = ()) -> str:
    """The first of the two commands every host runs: it prints the plan request (`--apply -` is the second)."""
    import shlex

    parts = [f"simplicio-loop turbo --repo {shlex.quote(str(root))}"]
    for task in tasks or ["<goal, naming the files to change>"]:
        parts.append(f"--task {shlex.quote(' '.join(str(task).split()))}")
    parts.append('--verify "<test command>"')
    return " ".join(parts)


def delivery_flow_commands(root: Path, tasks: Sequence[str] = ()) -> list[str]:
    """Literal command orient gives the host for any task count: the turbo engine."""
    return [turbo_command(root, tasks)]


def _orient_command_card(root: Path) -> dict[str, Any]:
    """The exact next command for this repo: the benchmarked turbo engine, in host mode.

    The host runs it, then runs the one printed apply command with its plan as the heredoc body, and reports
    the JSON that prints.
    """
    return {
        "schema": COMMAND_CARD_SCHEMA,
        "turbo": turbo_command(root),
        "flow": ["turbo", "apply"],
        "execute_rule": TURBO_EXECUTE_RULE,
        "requires": "no provider and no key",
        "done": "status ok, and verify.passed when --verify was given",
    }


def _orient_route(root: Path, task: str) -> dict[str, Any]:
    """One flow for every task count: the host runs ``simplicio-loop turbo``.

    Turbo surveys with Mapper, asks the model for the plan and applies it with
    dev-cli; ``--verify`` runs the tests. A one-file goal takes the same path.
    """
    goal = " ".join(str(task).split())
    return {
        "mode": "deliver",
        "justification": (
            "turbo"
            + (f" for {goal[:80]}" if goal else "")
            + ": Mapper once, you write the plan, dev-cli applies it, --verify runs the tests"
        ),
        "resolved_files": [],
        "execute_rule": TURBO_EXECUTE_RULE,
        "next": delivery_flow_commands(root, [goal] if goal else ()),
    }


def _seal_orient_payload(
    payload: dict[str, Any], *, root: Path, task: str,
) -> dict[str, Any]:
    contract = llm_max_speed_orientation_contract()
    payload["llm_orientation"] = contract
    payload["commands"] = _orient_command_card(root)
    # Route first: hosts often read orient through `| head`.
    rest = list(payload.items())
    payload.clear()
    payload["route"] = _orient_route(root, task)
    payload.update(rest)
    provenance = _orient_provider_provenance(payload)
    receipt = {
        "schema": ORIENT_RECEIPT_SCHEMA,
        "orient_schema": ORIENT_SCHEMA,
        "status": payload.get("status"),
        "provider": payload.get("provider"),
        "fallback": bool(payload.get("fallback")),
        "fallback_reason": payload.get("fallback_reason"),
        "repo": str(root),
        "source_revision": provenance.get("source_revision") or _orient_revision(root),
        "task_hash": _orient_hash(str(task).strip()),
        "contract_hash": _orient_hash(contract),
        "provenance": provenance,
    }
    receipt["receipt_hash"] = _orient_hash(receipt)
    payload["receipt"] = receipt
    return payload

def _mapper_orient_fallback(root: Path, task: str, *, timeout: float = 180) -> dict:
    """Run Mapper's read-only orient surface for the task.

    The scratch task-file MUST live under ``.simplicio-loop/`` (not the repo
    root): Mapper's own signature computation hashes ``git status`` output,
    excluding only its own output directory (default ``.simplicio-loop``) by
    pathspec. A dotfile prefix alone does not put this file inside that
    directory, so a repo-root temp file is untracked and visible to `git
    status` for the brief window this subprocess runs -- exactly when Mapper
    snapshots its own status_hash. That transient extra untracked file
    changed status_hash on every orient call, even against an unchanged
    source tree, making a purely read-only re-survey between `prepare` and
    `wave` look like "active attempt mapper generation changed" drift.
    """
    task_path = None
    try:
        scratch_dir = root / ".simplicio-loop"
        scratch_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md",
                                         prefix="loop-orient-",
                                         dir=str(scratch_dir), delete=False) as handle:
            handle.write(task)
            task_path = Path(handle.name)
        proc = subprocess.run(
            ["simplicio-mapper", "orient", str(root), "--task-file", str(task_path), "--json"],
            cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, close_fds=True, timeout=timeout, check=False,
        )
        raw = (proc.stdout or "").strip()
        try:
            result = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            result = {"raw_tail": raw[-4000:]}
        return {"status": "READY" if proc.returncode == 0 else "BLOCKED",
                "returncode": proc.returncode, "result": result,
                "stderr": (proc.stderr or "")[-2000:]}
    except subprocess.TimeoutExpired as exc:
        raise OrientBudgetExceeded(
            f"simplicio-mapper orient exceeded the remaining orient budget ({timeout:.0f}s)"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "BLOCKED", "returncode": None, "reason": str(exc)}
    finally:
        if task_path is not None:
            try:
                task_path.unlink()
            except OSError:
                pass

def _orient_extract_fallback_reason(mapper_payload: Mapping[str, Any] | None) -> str:
    """Pull the real cause out of a Mapper orient BLOCKED payload.

    Reading only the top-level ``reason`` key silently collapses every real
    cause into a generic fallback, so this also checks the nested
    ``result`` payload Mapper's own orient CLI returns.
    """
    payload = mapper_payload or {}
    top_level = payload.get("reason")
    if top_level:
        return str(top_level)
    result = payload.get("result")
    if isinstance(result, Mapping):
        value = result.get("reason")
        if value:
            return str(value)
    return ""


def _orient_context_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Bounded, task-relevant leading context (issue #1288 AC2/AC3).

    Extracted from the Mapper survey selection so the top of the payload
    always carries paths/symbols instead of only receipts/policy text.
    """
    mapper = payload.get("mapper") if isinstance(payload.get("mapper"), Mapping) else {}
    result = mapper.get("result") if isinstance(mapper.get("result"), Mapping) else {}
    selection = result.get("selection") if isinstance(result.get("selection"), Mapping) else {}
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    targets = selection.get("targets") if isinstance(selection.get("targets"), list) else []
    return {
        "paths": [str(item) for item in targets if isinstance(item, str)],
        "symbols": [],
        "candidate_count": len(candidates),
        "gaps": list(result.get("gaps") or []),
    }


def _orient_trim_verbose_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Move receipts/probes/policy text out of the default (non-verbose) view.

    Kept fields stay byte-identical; this only removes the bulk of the
    non-task-relevant payload (issue #1288 AC2) so the default response leads
    with ``context`` instead of ~9.5KB of receipts. The full payload remains
    available via ``--verbose`` or the ``--tee`` cache.
    """
    trimmed = dict(payload)
    trimmed.pop("llm_orientation", None)
    mapper = trimmed.get("mapper")
    if isinstance(mapper, Mapping):
        mapper = dict(mapper)
        mapper.pop("stderr", None)
        trimmed["mapper"] = mapper
    return trimmed


ORIENT_TARGETS_SCHEMA = "simplicio.loop-orient-targets/v1"
_ORIENT_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ORIENT_WORD_SPLIT_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_ORIENT_SKIP_DIRS = {
    ".git", ".simplicio-loop", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".tox", ".ruff_cache",
    "egg-info", ".pytest-cache",
}
_ORIENT_SOURCE_EXT = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs",
    ".java", ".rb", ".php", ".cs", ".cpp", ".cc", ".c", ".h", ".hpp",
    # Non-code deliverables are real targets too (issue #1310 benchmark is
    # pure-HTML create/edit tasks) -- never leave a plain-HTML/CSS task with
    # 0 candidates just because it has no function/class identifiers.
    ".html", ".htm", ".css", ".md",
}
ORIENT_TARGET_MAX_FILES = 5
ORIENT_TARGET_MAX_TOTAL_BYTES = 6 * 1024
ORIENT_TARGET_FULL_FILE_MAX_BYTES = 2 * 1024
ORIENT_TARGET_SPAN_CONTEXT_LINES = 15
ORIENT_TINY_REPO_FILE_LIMIT = 30


def _orient_split_identifier(token: str) -> list[str]:
    return [part.lower() for part in _ORIENT_WORD_SPLIT_RE.findall(token) if part]


def _orient_task_terms(task: str) -> set[str]:
    terms: set[str] = set()
    for ident in _ORIENT_IDENTIFIER_RE.findall(task):
        terms.add(ident.lower())
        terms.update(_orient_split_identifier(ident))
    return {term for term in terms if len(term) > 1}


def _orient_iter_source_files(root: Path, *, limit: int = 4000) -> list[Path]:
    """Every tracked-looking source/test file under ``root``, bounded."""
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(found) >= limit:
            break
        if not path.is_file():
            continue
        if any(part in _ORIENT_SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in _ORIENT_SOURCE_EXT:
            continue
        found.append(path)
    return found


def _orient_file_score(path: Path, terms: set[str]) -> int:
    path_terms: set[str] = set()
    for part in path.parts:
        path_terms.add(part.lower())
        path_terms.update(_orient_split_identifier(part))
    score = len(terms & path_terms) * 2
    try:
        if path.stat().st_size <= 200_000:
            content = path.read_text(encoding="utf-8", errors="ignore")
            symbol_terms: set[str] = set()
            for ident in _ORIENT_IDENTIFIER_RE.findall(content):
                symbol_terms.add(ident.lower())
                symbol_terms.update(_orient_split_identifier(ident))
            score += len(terms & symbol_terms)
    except OSError:
        pass
    return score


def _orient_lexical_rank_candidates(root: Path, task: str) -> list[Path]:
    """Deterministic lexical-overlap ranking used when Mapper selection
    is empty or FALLBACK, so the host is never left ungrounded (issue: 0
    Mapper candidates must never mean 0 real file content).

    Ranks repo source/test files by overlap of task terms with path parts
    and in-file identifiers; tiny repos (<= ``ORIENT_TINY_REPO_FILE_LIMIT``
    tracked source files) include every file as a candidate regardless of
    score, since scanning all of them is cheap and safe.
    """
    terms = _orient_task_terms(task)
    files = _orient_iter_source_files(root)
    scored = [(_orient_file_score(path, terms), path) for path in files]
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    if len(files) <= ORIENT_TINY_REPO_FILE_LIMIT:
        return [path for _, path in scored]
    return [path for score, path in scored if score > 0]


def _orient_sibling_test_paths(root: Path, path: Path) -> list[str]:
    stem = path.stem
    if stem.startswith("test_") or stem.endswith("_test") or stem.endswith(".test") or stem.endswith(".spec"):
        return []
    names = {
        f"test_{stem}{path.suffix}", f"{stem}_test{path.suffix}",
        f"{stem}.test{path.suffix}", f"{stem}.spec{path.suffix}",
    }
    found: set[str] = set()
    for base in (root / "tests", root / "test", path.parent):
        if not base.is_dir():
            continue
        for name in names:
            candidate = base / name
            if candidate.is_file():
                found.add(str(candidate.relative_to(root)))
    return sorted(found)


def _orient_line_numbered(lines: list[str], start: int, end: int) -> str:
    return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1) if i <= len(lines))


def _orient_symbol_span(content: str, terms: set[str]) -> tuple[int, int]:
    lines = content.splitlines()
    if not lines:
        return (1, 0)
    for idx, line in enumerate(lines, start=1):
        line_terms = {ident.lower() for ident in _ORIENT_IDENTIFIER_RE.findall(line)}
        if line_terms & terms:
            start = max(1, idx - ORIENT_TARGET_SPAN_CONTEXT_LINES)
            end = min(len(lines), idx + ORIENT_TARGET_SPAN_CONTEXT_LINES)
            return (start, end)
    return (1, min(len(lines), ORIENT_TARGET_SPAN_CONTEXT_LINES * 2))


def _orient_build_target_entry(
    root: Path, path: Path, terms: set[str], remaining_bytes: int,
) -> tuple[dict[str, Any], int] | None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    rel = str(path.relative_to(root))
    encoded_len = len(content.encode("utf-8"))
    if encoded_len <= min(ORIENT_TARGET_FULL_FILE_MAX_BYTES, remaining_bytes):
        entry = {"path": rel, "content": content, "span": None}
        return entry, encoded_len
    lines = content.splitlines()
    start, end = _orient_symbol_span(content, terms)
    snippet = _orient_line_numbered(lines, start, end)
    snippet_bytes = snippet.encode("utf-8")
    if len(snippet_bytes) > remaining_bytes:
        out_lines: list[str] = []
        used = 0
        for line in snippet.splitlines():
            line_len = len(line.encode("utf-8")) + 1
            if used + line_len > remaining_bytes:
                break
            out_lines.append(line)
            used += line_len
        snippet = "\n".join(out_lines)
    entry = {
        "path": rel, "content": None,
        "span": {"start": start, "end": end, "text": snippet},
    }
    return entry, len(snippet.encode("utf-8"))


def _orient_target_seed_candidates(
    root: Path, task: str, context_summary: Mapping[str, Any],
) -> list[Path]:
    """Prefer Mapper's own selection when it named real files; fall back
    to the deterministic lexical ranking only when that selection is empty."""
    seeds: list[Path] = []
    for rel in context_summary.get("paths") or []:
        if not isinstance(rel, str):
            continue
        candidate = (root / rel)
        if candidate.is_file():
            seeds.append(candidate)
    if seeds:
        return seeds
    return _orient_lexical_rank_candidates(root, task)


def _orient_build_targets(root: Path, task: str, context_summary: Mapping[str, Any]) -> dict[str, Any]:
    """Bounded, grounded file targets (issue: never leave the host to
    hallucinate paths/APIs when Mapper selection came back empty).

    Keeps the whole thing small: at most ``ORIENT_TARGET_MAX_FILES`` files
    and ``ORIENT_TARGET_MAX_TOTAL_BYTES`` combined, exact content for small
    files, a line-numbered symbol span for larger ones, plus sibling test
    file paths per candidate.
    """
    terms = _orient_task_terms(task)
    candidates = _orient_target_seed_candidates(root, task, context_summary)
    files_entries: list[dict[str, Any]] = []
    remaining = ORIENT_TARGET_MAX_TOTAL_BYTES
    for path in candidates:
        if len(files_entries) >= ORIENT_TARGET_MAX_FILES or remaining <= 0:
            break
        built = _orient_build_target_entry(root, path, terms, remaining)
        if built is None:
            continue
        entry, used = built
        entry["tests"] = _orient_sibling_test_paths(root, path)
        files_entries.append(entry)
        remaining -= used
    return {
        "schema": ORIENT_TARGETS_SCHEMA,
        "candidate_count": len(candidates),
        "files": files_entries,
    }


_ORIENT_GIT_CHECK_TIMEOUT_S = 5


def _is_git_worktree(root: Path) -> bool:
    """True iff ``root`` is inside a git work tree -- checked with a short
    timeout so a huge or unreachable directory can never turn this into a
    slow scan (issue #1318 cause 4: `orient` run against `/root` took
    163.7s). A non-git directory (or a `git` that errors/hangs) is simply
    not a work tree; never raises."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(root), capture_output=True, text=True,
            timeout=_ORIENT_GIT_CHECK_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _orient_not_a_git_repo_payload(root: Path, task: str, *,
                                    verbose: bool) -> dict[str, Any]:
    payload = {"schema": ORIENT_SCHEMA, "status": "BLOCKED",
               "provider": None, "fallback": False,
               "reason": "not_a_git_repo", "reason_code": "not_a_git_repo",
               "hint": f"{root} is not inside a git work tree; orient refuses to survey it",
               "local_llm": False}
    _seal_orient_payload(payload, root=root, task=str(task))
    if not verbose:
        payload = _orient_trim_verbose_fields(payload)
    return payload


def _orient_core(root: Path, task: str, targets: list[str] | None,
                  verbose: bool, *, deadline: float | None = None) -> tuple[dict[str, Any], int]:
    """Compute one task's orient payload via the Mapper survey (issue #1343:
    Fast removed, Mapper is the sole survey operator) without printing/tee --
    shared by ``orient()`` (CLI, single task) and ``orient_brief()`` (Turn 1
    of issue #1310's plan-once/apply-once hot path, N tasks).
    """
    if not root.is_dir() or not str(task).strip():
        payload = {"schema": ORIENT_SCHEMA, "status": "BLOCKED",
                   "provider": None, "fallback": False,
                   "reason": "repo_or_task_invalid", "local_llm": False}
        _seal_orient_payload(payload, root=root, task=str(task))
        return payload, 2
    if not _is_git_worktree(root):
        payload = _orient_not_a_git_repo_payload(root, task, verbose=verbose)
        return payload, 2
    # issue #1343: ensure the Mapper project-map/generation exists (bounded,
    # tree-state cached) BEFORE the Mapper `orient` survey call below. With
    # Fast gone, `orient` is the first thing that ever touches this repo's
    # Mapper state; without this, a genesis/near-empty repo's first `orient`
    # call can trigger Mapper's own scaffold side effects (e.g. generated
    # `.agents/`/`.catalog/` files) mid-survey, then a second call on the
    # now-changed tree sees a different candidate set -- breaking the
    # same-tree determinism `orient --brief` promises. May raise
    # ``MapperIndexTimedOut``/``MapperIndexRunning``; callers handle those.
    deadline = _orient_deadline() if deadline is None else deadline
    asyncio.run(_ensure_project_map(root, budget=_orient_remaining(deadline)))
    mapper = _mapper_orient_fallback(root, str(task), timeout=_orient_remaining(deadline))
    status = "READY" if mapper.get("status") == "READY" else "BLOCKED"
    payload = {"schema": ORIENT_SCHEMA, "status": status,
                      "provider": "simplicio-mapper", "fallback": False,
                      "mapper": mapper, "local_llm": False}
    if status == "BLOCKED":
        payload["fallback_reason"] = _orient_extract_fallback_reason(mapper) or "mapper_not_ready"
    _seal_orient_payload(payload, root=root, task=str(task))
    payload["context"] = _orient_context_summary(payload)
    payload["targets"] = _orient_build_targets(root, str(task), payload["context"])
    if not verbose:
        payload = _orient_trim_verbose_fields(payload)
    return payload, (0 if status == "READY" else 2)


def _brief_dump(payload: dict, *, pretty: bool = False) -> str:
    """Render an ``orient --brief`` payload for stdout/tee (issue #1336).

    Default: no indentation, no space after ``,``/``:`` -- compact, and
    deterministic because it preserves the payload dict's own insertion
    order (``route`` first, see ``orient_brief``) rather than sorting keys.
    A byte-identical prompt-cache-relevant tool output across turns/sessions
    on an unchanged tree is the whole point: this text becomes part of the
    OpenCode conversation the model prompt is built from, so shrinking and
    stabilizing it raises the cross-call prompt-cache hit rate. ``pretty``
    opts back into human-readable ``indent=2`` for interactive/debug use.
    """
    if pretty:
        return json.dumps(stable_first(payload, schema_first=False), ensure_ascii=False, indent=2)
    return json.dumps(stable_first(payload, schema_first=False), ensure_ascii=False, separators=(",", ":"))


def _mapper_index_budget_payload(schema: str, exc: Exception, root: Path) -> dict[str, Any]:
    """Typed BLOCKED payload for a ``MapperIndexTimedOut``/``MapperIndexRunning``
    (issue #1339) -- ``orient``/``orient --brief`` never block silently past
    their budget; this is the JSON they print instead."""
    reason_code = getattr(exc, "reason_code", "mapper_index_blocked")
    return {
        "schema": schema,
        "status": "BLOCKED",
        "reason": str(exc),
        "reason_code": reason_code,
        "next": (
            f"the simplicio-mapper index for {root} is running detached in its own "
            f"process group; re-run this exact orient command once it finishes -- "
            f"it reuses the survey instead of re-indexing (see the log path above)"
        ),
    }


def orient(repo: str, task: str,
           tee: bool = False, targets: list[str] | None = None,
           verbose: bool = False, brief: bool = False,
           tasks: list[str] | None = None, pretty: bool = False) -> int:
    """Run orient through the Mapper survey (issue #1343: Fast removed).

    ``brief=True`` (issue #1310) renders Turn 1 of the plan-once/apply-once
    hot path: a compact, multi-task payload built from the SAME Mapper
    survey ``orient`` always runs -- never a shortcut around it.

    issue #1339: this always prints valid JSON. An exception ANYWHERE in the
    computation below (Mapper, the project-map ensure step) is caught here
    and rendered as a typed BLOCKED payload instead of leaving stdout empty
    -- the one thing a caller piping this into ``json.tool`` can never
    tolerate.
    """
    root = Path(repo).resolve()
    try:
        return _orient_impl(root, task, tee, targets, verbose, brief, tasks, pretty)
    except Exception as exc:
        payload = {"schema": ORIENT_SCHEMA, "status": "BLOCKED", "provider": None,
                   "fallback": False, "reason": str(exc),
                   "reason_code": "orient_internal_error", "local_llm": False}
        print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
        return 2


def _orient_impl(root: Path, task: str, tee: bool, targets: list[str] | None,
                  verbose: bool, brief: bool, tasks: list[str] | None, pretty: bool) -> int:
    if root.is_dir():
        ensure_state_dir(root)
    if brief:
        task_list = list(tasks or ([task] if task else []))
        payload = orient_brief(root, task_list, targets=targets)
        if tee:
            from .tee_cache import write
            path = write(root, _brief_dump(payload, pretty=pretty))
            payload["tee_path"] = str(path)
        print(_brief_dump(payload, pretty=pretty))
        return 0 if payload.get("status") in {"READY", "FALLBACK"} else 2
    try:
        payload, code = _orient_core(root, task, targets, verbose)
    except (MapperIndexTimedOut, MapperIndexRunning) as exc:
        payload = _mapper_index_budget_payload(ORIENT_SCHEMA, exc, root)
        if tee:
            from .tee_cache import write
            path = write(root, json.dumps(payload, ensure_ascii=False, indent=2))
            payload["tee_path"] = str(path)
        print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
        return 2
    if payload.get("status") != "BLOCKED":
        from .survey import write_survey
        prov = _orient_provider_provenance(payload)
        write_survey(root, [{"task": task, "operator": prov.get("operator"),
                             "generation": prov.get("generation"),
                             "context_hash": prov.get("context_hash")}])
    if tee:
        from .tee_cache import write
        path = write(root, json.dumps(payload, ensure_ascii=False, indent=2))
        payload["tee_path"] = str(path)
    print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
    return code


ORIENT_BRIEF_SCHEMA = "simplicio.loop-orient-brief/v1"
ORIENT_BRIEF_TARGET_CAP_BYTES = 16 * 1024


def _brief_head_tail(text: str, cap_bytes: int = ORIENT_BRIEF_TARGET_CAP_BYTES) -> tuple[str, bool]:
    """Head+tail truncation to ``cap_bytes`` (issue #1310: 16 KB/file cap on
    the brief's target content, so `apply --brief` never needs a separate
    `cat` even for a file larger than the old 2 KB inline-content ceiling)."""
    encoded = text.encode("utf-8", "surrogateescape")
    if len(encoded) <= cap_bytes:
        return text, False
    half = cap_bytes // 2
    head = encoded[:half].decode("utf-8", "replace")
    tail = encoded[-half:].decode("utf-8", "replace")
    return head + "\n...<truncated>...\n" + tail, True


def _brief_suggest_checks(root: Path) -> list[str]:
    """Suggested checks from the toolchain already on disk (issue #1310);
    never invents a command the repo has no evidence of supporting."""
    checks: list[str] = []
    if any((root / name).is_file() for name in ("pyproject.toml", "pytest.ini", "setup.cfg")):
        checks.append("pytest -q")
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        scripts = data.get("scripts") if isinstance(data, Mapping) else None
        if isinstance(scripts, Mapping) and "test" in scripts:
            checks.append("npm test")
    if (root / "Makefile").is_file():
        checks.append("make check")
    return checks


ORIENT_BRIEF_TOTAL_BUDGET_BYTES = 24 * 1024


def _brief_order_candidates_named_first(task: str, candidates: Sequence[Path]) -> list[Path]:
    """A file the task text literally names sorts before any other candidate
    the same task's ranking surfaced (issue #1318: "targets put the files
    each task names first")."""
    task_lower = task.lower()
    named = [p for p in candidates if p.name.lower() in task_lower]
    rest = [p for p in candidates if p not in named]
    return named + rest


def _brief_clip_to_budget(text: str, budget_bytes: int) -> tuple[str, bool]:
    """Hard-clip ``text`` to at most ``budget_bytes`` UTF-8 bytes, on a line
    boundary where possible, marking it truncated whenever it clips."""
    encoded = text.encode("utf-8", "surrogateescape")
    if len(encoded) <= budget_bytes:
        return text, False
    out_lines: list[str] = []
    used = 0
    for line in text.splitlines():
        line_len = len(line.encode("utf-8", "surrogateescape")) + 1
        if used + line_len > budget_bytes:
            break
        out_lines.append(line)
        used += line_len
    return "\n".join(out_lines), True


def _brief_build_targets(root: Path, tasks: Sequence[str],
                         per_task_context: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Target files with content, deduped across tasks, capped per file and,
    combined, under a total size budget (issue #1310/#1318: "the target
    files with content, no separate cat" -- but bounded, and with the file
    a task names first).

    Verifier/check/test files get the SAME head+tail treatment as any other
    target (issue #1323): they ARE the acceptance spec, so a check file that
    fits the per-file/total budget comes back in full, not a fixed head.
    """
    seen: dict[str, dict[str, Any]] = {}
    remaining_budget = ORIENT_BRIEF_TOTAL_BUDGET_BYTES
    for task, context in zip(tasks, per_task_context):
        candidates = _orient_target_seed_candidates(root, task, context)
        ordered = _brief_order_candidates_named_first(task, candidates)[:ORIENT_TARGET_MAX_FILES]
        for path in ordered:
            rel = str(path.relative_to(root))
            if rel in seen:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            trimmed, truncated = _brief_head_tail(content)
            if remaining_budget <= 0:
                seen[rel] = {"path": rel, "content": "", "truncated": True}
                continue
            clipped, budget_truncated = _brief_clip_to_budget(trimmed, remaining_budget)
            entry_bytes = len(clipped.encode("utf-8", "surrogateescape"))
            remaining_budget -= entry_bytes
            seen[rel] = {"path": rel, "content": clipped, "truncated": truncated or budget_truncated}
    return list(seen.values())


def _brief_plan_groups(tasks: Sequence[str], per_task_targets: Sequence[Sequence[str]]) -> dict[str, Any]:
    """``parallel`` for tasks touching disjoint target files, ``ordered``
    groups (declared-order lists) for tasks that share one (issue #1310)."""
    n = len(tasks)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    path_owner: dict[str, int] = {}
    for i, paths in enumerate(per_task_targets):
        for path in paths:
            if path in path_owner:
                union(path_owner[path], i)
            else:
                path_owner[path] = i

    groups: dict[int, list[str]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(tasks[i])
    parallel = [group[0] for group in groups.values() if len(group) == 1]
    ordered = [group for group in groups.values() if len(group) > 1]
    return {"parallel": parallel, "ordered": ordered}


def _brief_annotate_route_next(route: Mapping[str, Any], root: Path,
                               status: str, task_count: int = 1,
                               tasks: Sequence[str] = ()) -> dict[str, Any]:
    """Point ``route["next"]`` at ``simplicio-loop turbo`` for these tasks.

    The host runs that one command; turbo plans with the model, applies with
    dev-cli and verifies with ``--verify``. A BLOCKED brief passes through unchanged.
    """
    from .effort import PHASE_EFFORT

    if status == "BLOCKED":
        return dict(route)
    del task_count
    out = dict(route)
    out["mode"] = "deliver"
    out["execute"] = "turbo"
    out["execute_rule"] = TURBO_EXECUTE_RULE
    out["next"] = [
        {"step": turbo_command(root, tasks), "phase": "execute", "effort": PHASE_EFFORT["execute"]},
    ]
    return out


def _brief_apply_command(root: Path, repo_state_chain: Mapping[str, Any],
                         generations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """issue #1323: ``example`` is a concrete, valid ops.json -- a create
    (``find: ""``), a dependent edit (``depends_on``) and a ``check`` -- with
    ``repo_state_chain``/``brief_generations`` copied verbatim from this same
    brief, so the host never opens ``simplicio_loop/apply.py`` to learn the
    ops format."""
    example = {
        "tasks": [
            {
                "id": "example-create-notes",
                "operations": [{"path": "NOTES.md", "find": "", "replace": "# Notes\n"}],
                "check": None,
                "depends_on": [],
            },
            {
                "id": "example-extend-notes",
                "operations": [{"path": "NOTES.md", "find": "# Notes\n",
                                "replace": "# Notes\n\n## Details\n"}],
                "check": "python3 -c \"assert 'Details' in open('NOTES.md').read()\"",
                "depends_on": ["example-create-notes"],
            },
        ],
        "repo_state_chain": dict(repo_state_chain),
        "brief_generations": [dict(g) for g in generations],
    }
    return {
        "command": f"simplicio-loop apply .simplicio-loop/ops.json --repo {root} --json",
        "ops_format": {
            "tasks": [{
                "id": "<task-id>",
                "operations": [{"path": "<repo-relative>", "find": "<exact unique text>", "replace": "<new text>"}],
                "check": "<optional shell check command>",
                "depends_on": ["<other task id, optional>"],
            }],
            "repo_state_chain": "<copy verbatim from this brief's own repo_state_chain field>",
            "brief_generations": "<copy verbatim from this brief's own generations field (Mapper provenance)>",
        },
        "example": example,
    }


def _orient_brief_impl(root: Path, tasks: list[str], *,
                  targets: list[str] | None = None) -> dict[str, Any]:
    """Turn 1 of the plan-once/apply-once hot path (issue #1310): a compact
    rendering of the SAME Mapper survey ``orient`` always runs, for one or
    more tasks -- never a shortcut around it. Route first, then deduped
    target content, plan groups, suggested checks, the Mapper generation +
    context hash (so cache reuse stays measurable), and the exact ``apply``
    command.
    """
    task_list = [str(t) for t in tasks if str(t).strip()]
    if not task_list:
        return {
            "schema": ORIENT_BRIEF_SCHEMA, "status": "BLOCKED", "reason": "no_tasks",
            "route": {"mode": "converge", "justification": "no task given", "resolved_files": [], "next": []},
        }
    if not _is_git_worktree(root):
        return {
            "schema": ORIENT_BRIEF_SCHEMA, "status": "BLOCKED",
            "reason": "not_a_git_repo", "reason_code": "not_a_git_repo",
            "hint": f"{root} is not inside a git work tree; orient refuses to survey it",
            "route": {"mode": "converge", "justification": "not a git work tree",
                      "resolved_files": [], "next": []},
        }

    per_task: list[dict[str, Any]] = []
    deadline = _orient_deadline()
    for task in task_list:
        try:
            payload, code = _orient_core(root, task, targets, verbose=True, deadline=deadline)
        except (MapperIndexTimedOut, MapperIndexRunning) as exc:
            blocked = _mapper_index_budget_payload(ORIENT_BRIEF_SCHEMA, exc, root)
            blocked["tasks"] = task_list
            blocked["route"] = {"mode": "converge", "justification": blocked["reason"],
                                 "resolved_files": [], "next": [blocked["next"]]}
            return blocked
        per_task.append({"task": task, "payload": payload, "exit_code": code})

    routes = [item["payload"].get("route") or {} for item in per_task]
    if len(task_list) == 1:
        overall_route = routes[0]
    else:
        overall_mode = "converge" if any(r.get("mode") == "converge" for r in routes) else "fast-path"
        overall_route = {
            "mode": overall_mode,
            "justification": f"{len(task_list)} tasks: " + "; ".join(
                f"{item['task']}={r.get('mode')}" for item, r in zip(per_task, routes)
            ),
            "resolved_files": sorted({f for r in routes for f in (r.get("resolved_files") or [])}),
            "per_task": [{"task": item["task"], "mode": r.get("mode")} for item, r in zip(per_task, routes)],
        }

    contexts = [item["payload"].get("context") or {} for item in per_task]
    per_task_target_lists = []
    for item, context in zip(per_task, contexts):
        entries = ((item["payload"].get("targets") or {}).get("files")) or []
        all_paths = [e["path"] for e in entries if isinstance(e, Mapping) and e.get("path")]
        # Plan grouping cares about which file(s) a task actually names, not
        # every candidate a tiny/ambiguous repo's ranking surfaced (a 2-file
        # repo returns both files as "candidates" for every task) -- prefer
        # the path(s) literally mentioned in the task text when any match.
        named = [p for p in all_paths if Path(p).name.lower() in item["task"].lower()]
        per_task_target_lists.append(named or all_paths[:1])

    statuses = [item["payload"].get("status") for item in per_task]
    overall_status = "BLOCKED" if all(s == "BLOCKED" for s in statuses) else (
        "READY" if all(s in {"READY", "FALLBACK"} for s in statuses) and any(s == "READY" for s in statuses)
        else "FALLBACK"
    )

    generations = []
    for item in per_task:
        provenance = _orient_provider_provenance(item["payload"])
        generations.append({
            "task": item["task"],
            "operator": provenance.get("operator"),
            "generation": provenance.get("generation"),
            "context_hash": provenance.get("context_hash"),
        })

    from .runner import _repo_fingerprint
    repo_state_chain = _repo_fingerprint(root)

    from .effort import PHASE_EFFORT
    overall_route = _brief_annotate_route_next(overall_route, root, overall_status, len(task_list),
                                               tasks=[str(t) for t in task_list])

    payload: dict[str, Any] = {}
    payload["route"] = overall_route
    payload["schema"] = ORIENT_BRIEF_SCHEMA
    payload["status"] = overall_status
    payload["tasks"] = task_list
    payload["targets"] = _brief_build_targets(root, task_list, contexts)
    payload["plan"] = _brief_plan_groups(task_list, per_task_target_lists)
    payload["checks"] = _brief_suggest_checks(root)
    payload["generations"] = generations
    payload["repo_state_chain"] = repo_state_chain
    payload["apply"] = _brief_apply_command(root, repo_state_chain, generations)
    execute_steps = [
        step.get("step") for step in overall_route.get("next") or []
        if isinstance(step, Mapping) and step.get("phase") == "execute"
    ]
    if execute_steps:
        payload["apply"]["command"] = execute_steps[0]
    payload["effort"] = dict(PHASE_EFFORT)
    if overall_status != "BLOCKED":
        # `apply` refuses to run without this Mapper survey (issue #1318).
        # The project-map/generation is already ensured per-task above (in
        # the `_orient_core` loop), so this is just the survey write.
        brief_path = ensure_state_dir(root) / "brief.json"
        brief_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        from .survey import write_survey
        write_survey(root, generations)
    return payload


def orient_brief(root: Path, tasks: list[str], *,
                  targets: list[str] | None = None) -> dict[str, Any]:
    """Public entry point (issue #1339): always returns a JSON-serializable
    dict, never raises -- any unexpected exception inside ``_orient_brief_impl``
    becomes a typed BLOCKED payload instead of propagating to the caller."""
    try:
        return _orient_brief_impl(root, tasks, targets=targets)
    except Exception as exc:
        return {
            "schema": ORIENT_BRIEF_SCHEMA, "status": "BLOCKED",
            "reason": str(exc), "reason_code": "orient_internal_error",
            "tasks": [str(t) for t in (tasks or [])],
            "route": {"mode": "converge", "justification": str(exc),
                       "resolved_files": [], "next": []},
        }


def extensions_doctor(provider: str, policy: str, schema: str) -> int:
    from .extension_handshake import ExtensionHandshakeError, extension_handshake
    try:
        payload = extension_handshake(provider, policy, requested_schema=schema)
    except ExtensionHandshakeError as exc:
        payload = {"schema": schema, "status": "BLOCKED", "reason_code": exc.reason_code, "detail": exc.detail}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def verify(repo: str, run_id: str) -> int:
    from .runner import verify_run
    payload = verify_run(repo, run_id)
    print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
    return 0 if payload["state"].get("phase") == "done" else 1


def _render_status_text(payload: dict) -> str:
    """Human-readable one-screen summary of a run status payload."""
    state = payload.get("state") or {}
    lines = ["simplicio-loop run status", ""]
    run_dir = payload.get("run_dir", "")
    if run_dir:
        lines.append(f"run_dir: {run_dir}")
    completion = state.get("completion") or {}
    lines.append(f"phase: {state.get('phase', 'UNKNOWN')}")
    lines.append(f"completion_tag: {completion.get('tag', 'UNVERIFIED')}")
    coverage = completion.get("coverage")
    if coverage:
        lines.append(f"coverage: {coverage}")
    delivery = state.get("delivery") or {}
    lines.append(f"delivery_ready: {delivery.get('ready', False)}")
    route = payload.get("execution_route") or state.get("execution_route") or {}
    lines.append(f"execution_route: {route.get('route', 'UNVERIFIED')}")
    lines.append(f"route_receipt_sha: {route.get('receipt_sha', '') or 'UNVERIFIED'}")
    lines.append(f"route_backend: {route.get('backend', 'UNVERIFIED')}")
    return "\n".join(lines) + "\n"


def status(repo: str, run_id: str, as_json: bool = False, as_text: bool = False) -> int:
    try:
        payload = read_status(repo, run_id)
        if (payload.get("state") or {}).get("phase") == "no_runs":
            payload.update({"schema": "simplicio.status/v1", "status": "UNVERIFIED",
                            "reason_code": "run_missing"})
    except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
        payload = {"schema": "simplicio.status/v1", "status": "UNVERIFIED",
                   "reason_code": "run_missing", "error": str(exc)}
    # Default remains JSON (backwards-compatible). --text opts into the human summary.
    if as_text and not as_json:
        print(_render_status_text(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def economy_command(args) -> int:
    """economy status | print | apply — fastest token path + parallel defaults."""
    import json as _json

    from .economy_profile import (
        economy_parallel_env,
        persist_user_profile,
        profile_status,
        render_shell_exports,
    )

    sub = getattr(args, "economy_command", None)
    if sub == "status":
        payload = profile_status()
        if args.json:
            print(_json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"economy profile: {payload['profile']} enabled={payload['enabled']}")
            print(
                f"  execution_profile={payload.get('execution_profile')} "
                f"runtime_operational={payload.get('runtime_operational')}"
            )
            if payload.get("note"):
                print(f"  note: {payload['note']}")
            print(f"  cpu={payload['cpu_count']} aligned={payload['aligned']}")
            print(f"  workers={payload['recommended'].get('SIMPLICIO_LOOP_OPERATOR_WORKERS')}")
            print(f"  prism_slots={payload['recommended'].get('SIMPLICIO_PRISM_SLOTS')}")
            print(f"  async={payload['recommended'].get('SIMPLICIO_ASYNC_IO_MAX_CONCURRENCY')}")
            print(f"  fan_out={payload['recommended'].get('SIMPLICIO_LOOP_AUTO_FAN_OUT')}")
            if payload["drift_keys"]:
                print(f"  drift: {', '.join(payload['drift_keys'][:12])}")
                if payload.get("drift_explanation"):
                    print(f"  why: {payload['drift_explanation']}")
                if payload.get("drift_fix"):
                    print(f"  fix: {payload['drift_fix']}")
            print("  backends: Runtime Tokio · Python asyncio · Prism slots")
        return 0 if payload.get("enabled") else 1
    if sub == "print":
        env_map = economy_parallel_env()
        if args.json:
            print(_json.dumps({"schema": "simplicio.economy-parallel-profile/v1", "env": env_map},
                              ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_shell_exports(env_map, shell=args.shell), end="")
        return 0
    if sub == "apply":
        no_user = bool(getattr(args, "no_user", False))
        if no_user:
            import os as _os

            applied = economy_parallel_env()
            for key, value in applied.items():
                _os.environ[key] = value
            payload = {
                "schema": "simplicio.economy-parallel-profile/v1",
                "ok": True,
                "scope": "process",
                "env": applied,
            }
        else:
            payload = persist_user_profile(set_windows_user_env=True)
        if args.json:
            print(_json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"economy apply ok={payload.get('ok')} profile={payload.get('profile')}")
            paths = payload.get("paths") or {}
            if paths.get("ps1"):
                print(f"  ps1: {paths['ps1']}")
            if paths.get("sh"):
                print(f"  sh:  {paths['sh']}")
            if payload.get("rc_files_changed"):
                print(f"  rc_files_changed: {', '.join(payload['rc_files_changed'])}")
            print(f"  workers={payload.get('env', {}).get('SIMPLICIO_LOOP_OPERATOR_WORKERS')}")
            print(f"  prism_slots={payload.get('env', {}).get('SIMPLICIO_PRISM_SLOTS')}")
        return 0 if payload.get("ok", True) else 1
    print("unknown economy command", file=sys.stderr)
    return 2


def preflight(repo: str, as_json: bool = False, *, strict: bool = False) -> int:
    """Verify the bound operators (mapper, dev-cli).

    Under ``--strict`` / ``SIMPLICIO_LOOP_STRICT=1`` hand-edit is reported as
    forbidden.

    Returns exit 0 when all *required* operators are present, 1 otherwise.
    """
    import os as _os

    from .finding_router import route_finding as _route_finding
    from .strict_mode import preflight_payload, recommended_env

    repo_path = Path(repo).resolve()
    if strict:
        _os.environ["SIMPLICIO_LOOP_STRICT"] = "1"
    from . import version_drift

    payload = preflight_payload(str(repo_path), strict=strict)
    all_present = bool(payload.get("all_present"))
    missing = list(payload.get("missing_operators") or [])
    drift = version_drift.check(version_drift.running_version(), repo=repo_path)
    if drift is not None:
        payload["version_drift"] = drift
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("simplicio-loop preflight" + (" [STRICT]" if payload.get("strict") else ""))
        required = set(payload.get("required_operators") or [])
        for op in payload.get("operators") or []:
            name = op.get("name", "")
            present = bool(op.get("present"))
            if present:
                mark = "OK "
            elif name in required or name in {"simplicio-mapper", "simplicio-dev-cli"}:
                mark = "MISSING"
            else:
                mark = "OPTIONAL"
            ver = f" ({op['version']})" if op.get("version") else ""
            extra = ""
            if name == "simplicio-dev-cli" and op.get("resolved_as"):
                extra = f" via {op['resolved_as']}"
            print(f"  [{mark}] {name}{ver}{extra}")
        print("  all_present: true" if all_present else "  NOT ALL REQUIRED OPERATORS PRESENT")
        print(f"  execution_profile: {payload.get('execution_profile')}")
        print(f"  hand_edit_forbidden: {payload.get('hand_edit_forbidden')}")
        if payload.get("strict"):
            print("  recommended_env:")
            for key, value in (recommended_env() or {}).items():
                print(f"    {key}={value}")
        drift_line = version_drift.format_line(drift)
        if drift_line:
            print(drift_line)
    if not all_present:
        for name in missing:
            _route_finding(
                stage="preflight",
                finding_id=f"missing-operator-{name}",
                severity="high",
                source=f"preflight:{name}",
                confirmed=True,
                item_id=None,
                repo=str(repo_path),
                detail=f"bound operator {name} not present or not operational",
            )
    return 0 if all_present else 1


def resume(repo: str, run_id: str) -> int:
    payload = change_phase(repo, run_id, "awaiting_decision", "resume requested from CLI")
    print(__import__("json").dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _dispatch_failure_payload(schema: str, repo: str, run_id: str, error: Exception,
                              task_indices: Optional[Sequence[int]] = None) -> dict:
    payload = {
        "schema": schema,
        "status": "blocked",
        "reason_code": "operator_dispatch_failed",
        "repo": str(repo),
        "run_id": str(run_id),
        "task_indices": list(task_indices or []),
        "error_type": type(error).__name__,
        "error": redact_sensitive_text(str(error)),
    }
    payload["receipt_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def _dispatch_exit_code(payload: Mapping[str, Any]) -> int:
    """Return non-zero whenever a dispatch receipt is not a verified success."""
    if not payload:
        return 0  # preserve the thin CLI seam used by compatibility callers
    status = str(payload.get("status") or "").lower()
    if status in {"blocked", "held", "failed", "cancelled", "error"}:
        return 2
    if str(payload.get("phase") or "").lower() in {"blocked", "cancelled"}:
        return 2
    if str(payload.get("execution_state") or "").lower() in {"blocked", "uncertain"}:
        return 2
    if str(payload.get("action") or "") in {
        "operator_failed", "operator_batch_blocked", "operator_batch_preflight_blocked",
    }:
        return 2
    if payload.get("failed") or payload.get("blocked") or payload.get("dead_letter") or payload.get("blockers"):
        return 2
    admission = payload.get("capacity") or payload.get("admission")
    if isinstance(admission, Mapping) and admission.get("admitted") is False:
        return 2
    workers = payload.get("workers")
    if isinstance(workers, list) and any(
        not isinstance(worker, Mapping) or worker.get("status") not in {"succeeded", "completed"}
        for worker in workers
    ):
        return 2
    if payload.get("requested_tasks") and isinstance(workers, list) and not workers:
        return 2
    return 0


def _reconcile_prism_wave(task_indices: Sequence[int], result: Mapping[str, Any]) -> dict:
    requested = [int(index) for index in task_indices]
    requested_set = set(requested)
    workers = result.get("workers") if isinstance(result, Mapping) else None
    workers = workers if isinstance(workers, list) else []
    completed = {
        int(index) for index in (result.get("completed_tasks") or [])
        if isinstance(index, (int, str)) and str(index).lstrip("-").isdigit()
    } if isinstance(result, Mapping) else set()
    worker_by_task = {}
    failed = []
    for worker in workers:
        if not isinstance(worker, Mapping):
            failed.append(None)
            continue
        try:
            task_index = int(worker.get("task_index"))
        except (TypeError, ValueError):
            failed.append(None)
            continue
        worker_by_task[task_index] = worker
        if worker.get("status") not in {"succeeded", "completed"}:
            failed.append(task_index)
    missing = sorted(requested_set - set(worker_by_task) - completed)
    if failed:
        reason_code = "wave_worker_failed"
    elif missing:
        reason_code = "wave_receipt_missing"
    elif not workers and not completed:
        reason_code = "wave_receipt_invalid"
    elif isinstance(result, Mapping) and str(result.get("status") or "").lower() not in {"completed", "succeeded", "success"}:
        reason_code = "wave_not_terminal"
    else:
        reason_code = "wave_receipts_reconciled"
    ok = reason_code == "wave_receipts_reconciled"
    return {
        "schema": "simplicio.prism-wave-reconciliation/v1",
        "status": "reconciled" if ok else "held",
        "ok": ok,
        "requested_tasks": requested,
        "missing": missing,
        "failed": sorted(index for index in failed if index is not None),
        "reason_code": reason_code,
    }


def _public_flow_run_dir(repo: str, run_id: str) -> Path:
    """Resolve the run directory without inventing a successful artifact."""
    try:
        status = read_status(repo, run_id)
        candidate = Path(status["run_dir"])
        return candidate
    except (KeyError, OSError, TypeError, ValueError):
        return Path(repo).resolve() / ".simplicio-loop" / "loop-runs" / str(run_id)


def _attach_dispatch(public_payload: Mapping[str, Any], dispatch: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(public_payload)
    payload["dispatch"] = dict(dispatch)
    for key in ("route", "reason_code", "missing_tools", "provider_worker"):
        if key in dispatch and (key not in payload or key == "reason_code"):
            payload[key] = dispatch[key]
    return payload


def _finalize_public_flow(repo: str, run_id: str, flow: str, dispatch: Mapping[str, Any]) -> dict[str, Any]:
    """Return one v1 public result and persist the v2 adapter envelope once."""

    def _done(payload: Mapping[str, Any]) -> dict[str, Any]:
        persist_execution_envelope(
            flow=flow,
            repo=repo,
            run_id=run_id,
            observed={"run_id": run_id, "result": dict(dispatch), **dict(dispatch)},
        )
        return dict(payload)

    raw_status = str(
        dispatch.get("status")
        or dispatch.get("phase")
        or dispatch.get("execution_state")
        or ""
    ).strip().lower()
    nonterminal = {
        "blocked", "partial", "error", "failed", "held", "cancelled", "canceled",
        "unverified", "infrastructure_failure",
    }
    if raw_status in nonterminal or _dispatch_exit_code(dispatch) != 0:
        flow_result = {"status": raw_status or "blocked", "run_id": run_id}
        if isinstance(dispatch.get("state"), Mapping):
            flow_result["state"] = dict(dispatch["state"])
        diagnostic = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=_public_flow_run_dir(repo, run_id),
            flow=flow,
            flow_result=flow_result,
        )
        return _done(_attach_dispatch(diagnostic, dispatch))
    try:
        verified_status = verify_run(repo, run_id, flow=flow)
        state = verified_status.get("state") if isinstance(verified_status, Mapping) else {}
        loop_execution = state.get("loop_execution") if isinstance(state, Mapping) else {}
        if (
            isinstance(state, Mapping)
            and state.get("phase") == "done"
            and isinstance(loop_execution, Mapping)
            and loop_execution.get("status") == "VERIFIED"
        ):
            receipt_path = Path(repo).resolve() / ".simplicio-loop" / "loop-execution.json"
            envelope = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                isinstance(envelope, Mapping)
                and envelope.get("schema") == LOOP_EXECUTION_SCHEMA
                and (envelope.get("result") or {}).get("status") == "VERIFIED"
                and (envelope.get("result") or {}).get("verified") is True
            ):
                result = dict(envelope)
                result["status"] = "VERIFIED"
                result["verified"] = True
                return _done(_attach_dispatch(result, dispatch))
        phase = str((state or {}).get("phase") or "blocked")
        flow_result = {"status": phase, "run_id": run_id}
        if isinstance(state, Mapping):
            flow_result["state"] = dict(state)
        diagnostic = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=_public_flow_run_dir(repo, run_id),
            flow=flow,
            flow_result=flow_result,
        )
        return _done(_attach_dispatch(diagnostic, dispatch))
    except Exception as exc:
        diagnostic = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=_public_flow_run_dir(repo, run_id),
            flow=flow,
            flow_result={"status": "blocked", "run_id": run_id},
        )
        diagnostic["reason_code"] = "v1_publication_failed"
        diagnostic["reason"] = f"public flow could not reach a verified v1 receipt: {redact_sensitive_text(str(exc))}"
        return _done(_attach_dispatch(diagnostic, dispatch))


def _public_flow_from_status(status: Mapping[str, Any], flow: str, dispatch: Mapping[str, Any]) -> dict[str, Any]:
    """Project an already-conducted run without invoking publication again."""
    state = status.get("state") if isinstance(status, Mapping) else {}
    loop_execution = state.get("loop_execution") if isinstance(state, Mapping) else {}
    run_id = str(
        (status.get("manifest") or {}).get("run_id")
        or dispatch.get("run_id")
        or ""
    ) if isinstance(status, Mapping) else str(dispatch.get("run_id") or "")
    if (
        isinstance(state, Mapping)
        and state.get("phase") == "done"
        and isinstance(loop_execution, Mapping)
        and loop_execution.get("status") == "VERIFIED"
    ):
        repo = str((status.get("manifest") or {}).get("repo") or dispatch.get("repo") or ".")
        receipt_path = Path(repo).resolve() / ".simplicio-loop" / "loop-execution.json"
        try:
            envelope = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            envelope = {}
        if (
            isinstance(envelope, Mapping)
            and envelope.get("schema") == LOOP_EXECUTION_SCHEMA
            and (envelope.get("result") or {}).get("status") == "VERIFIED"
            and (envelope.get("result") or {}).get("verified") is True
        ):
            result = dict(envelope)
            result["status"] = "VERIFIED"
            result["verified"] = True
            return _attach_dispatch(result, dispatch)
    phase = str((state or {}).get("phase") or "blocked")
    flow_result = {"status": phase, "run_id": run_id}
    if isinstance(state, Mapping):
        flow_result["state"] = dict(state)
    diagnostic = publish_loop_execution_for_flow(
        repo=Path(str((status.get("manifest") or {}).get("repo") or dispatch.get("repo") or ".")),
        run_dir=Path(str(status.get("run_dir") or "")) if status.get("run_dir") else Path("."),
        flow=flow,
        flow_result=flow_result,
    )
    return _attach_dispatch(diagnostic, dispatch)


def _persist_prism_wave_receipt(repo: str, run_id: str, payload: dict) -> str:
    try:
        status = read_status(repo, run_id)
        run_dir = Path(status["run_dir"])
        if not run_dir.is_dir():
            return ""
        path = run_dir / "prism-wave-dispatch.json"
        payload["receipt_path"] = str(path)
        unsigned = dict(payload)
        unsigned.pop("receipt_hash", None)
        payload["receipt_hash"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return str(path)
    except (KeyError, OSError, TypeError, ValueError):
        return ""


def tick(repo: str, run_id: str, task_index: int, provider_worker: str | None = None) -> int:
    try:
        current = read_status(repo, run_id)
    except Exception:
        current = {}
    governor = expected_governor_blocked(current)
    if governor is not None:
        payload = {
            "schema": "simplicio.tick-receipt/v1", "status": "blocked",
            "reason_code": governor["reason_code"], "governor": governor,
            "run_id": run_id, "task_indices": [task_index],
        }
        public_payload = _finalize_public_flow(repo, run_id, "tick", payload)
        print(json.dumps(stable_first(public_payload), ensure_ascii=False, indent=2))
        return _dispatch_exit_code(public_payload)
    try:
        operator_kwargs = {"task_index": task_index}
        if provider_worker is not None:
            operator_kwargs["provider_worker"] = provider_worker
        payload = execute_operator(repo, run_id, **operator_kwargs)
    except Exception as exc:
        payload = _dispatch_failure_payload("simplicio.tick-receipt/v1", repo, run_id, exc, [task_index])
    public_payload = _finalize_public_flow(repo, run_id, "tick", payload)
    print(json.dumps(stable_first(public_payload), ensure_ascii=False, indent=2))
    return _dispatch_exit_code(public_payload)


def batch(repo: str, run_id: str, task_indices: str, max_workers: int, retry_budget: int,
          serial: bool = False, batch_size: Optional[int] = None,
          provider_worker: str | None = None, *, flow: str = "batch") -> int:
    """One task stays direct. Two or more tasks enter the wave; Prism schedules a wave wider than three."""
    indices = None
    if task_indices.strip():
        try:
            indices = [int(value.strip()) for value in task_indices.split(",") if value.strip()]
        except ValueError as exc:
            payload = _dispatch_failure_payload(
                "simplicio.operator-batch-receipt/v1", repo, run_id, exc,
            )
            persist_execution_envelope(flow=flow, repo=repo, run_id=run_id,
                                       observed={"run_id": run_id, "result": payload, "error": str(exc)})
            print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
            raise ValueError("--task-indices must be a comma-separated list of integers") from exc

    if indices is None:
        try:
            status = read_status(repo, run_id)
            contract_path = Path(status["run_dir"]) / "task-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            indices = list(range(1, len(contract.get("tasks") or []) + 1))
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            indices = None

    try:
        current = read_status(repo, run_id)
    except Exception:
        current = {}
    governor = expected_governor_blocked(current)
    if governor is not None:
        payload = {
            "schema": "simplicio.operator-batch-receipt/v1", "status": "blocked",
            "reason_code": governor["reason_code"], "run_id": run_id,
            "task_indices": list(indices or []), "governor": governor,
        }
        persist_execution_envelope(flow=flow, repo=repo, run_id=run_id,
                                   observed={**current, "result": payload, "governor": governor})
        payload = next_step.annotate_blocked(payload, repo=repo, run_id=run_id, flow=flow,
                                             run_dir=_public_flow_run_dir(repo, run_id))
        print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
        return 2

    eligibility = prism_is_eligible(len(indices or []), explicit_serial=serial)
    if not eligibility["eligible"]:
        try:
            batch_kwargs = {
                "max_workers": max_workers or None,
                "retry_budget": retry_budget,
                "auto_fan_out": not serial,
            }
            if provider_worker is not None:
                batch_kwargs["provider_worker"] = provider_worker
            payload = execute_operator_batch(repo, run_id, indices, **batch_kwargs)
        except Exception as exc:
            payload = _dispatch_failure_payload("simplicio.operator-batch-receipt/v1", repo, run_id, exc, indices)
        payload["prism"] = {**eligibility, "batch_size": None, "waves": 1}
        public_payload = _finalize_public_flow(repo, run_id, flow, payload)
        public_payload = next_step.annotate_blocked(public_payload, repo=repo, run_id=run_id, flow=flow,
                                                    run_dir=_public_flow_run_dir(repo, run_id))
        print(json.dumps(stable_first(public_payload), ensure_ascii=False, indent=2))
        return _dispatch_exit_code(public_payload)

    width = resolve_prism_batch_size(batch_size)
    waves = prism_batches(indices, width)
    worker_limit = min(max_workers or width, width)
    wave_results = []
    all_reconciled = True
    for wave_number, wave in enumerate(waves, start=1):
        try:
            batch_kwargs = {
                "max_workers": worker_limit,
                "retry_budget": retry_budget,
                "auto_fan_out": True,
            }
            if provider_worker is not None:
                batch_kwargs["provider_worker"] = provider_worker
            result = execute_operator_batch(repo, run_id, wave, **batch_kwargs)
        except Exception as exc:
            result = _dispatch_failure_payload("simplicio.operator-batch-receipt/v1", repo, run_id, exc, wave)
        reconciliation = _reconcile_prism_wave(wave, result)
        wave_results.append({"wave": wave_number, "task_indices": wave, "result": result,
                             "reconciliation": reconciliation})
        if not reconciliation["ok"]:
            all_reconciled = False
            break

    workers = [worker for wave in wave_results for worker in (wave["result"].get("workers") or [])]
    payload = {
        "schema": "simplicio.prism-wave-dispatch/v1",
        "status": "completed" if all_reconciled and len(wave_results) == len(waves) else "held",
        "prism": {
            **eligibility,
            "batch_size": width,
            "wave_barrier": "reconcile-before-next",
            "waves": len(waves),
            "requested_tasks": indices,
        },
        "waves": wave_results,
        "workers": workers,
    }
    _persist_prism_wave_receipt(repo, run_id, payload)
    public_payload = _finalize_public_flow(repo, run_id, flow, payload)
    public_payload = next_step.annotate_blocked(public_payload, repo=repo, run_id=run_id, flow=flow,
                                                run_dir=_public_flow_run_dir(repo, run_id))
    print(json.dumps(stable_first(public_payload), ensure_ascii=False, indent=2))
    return _dispatch_exit_code(public_payload)


def cancel(repo: str, run_id: str) -> int:
    payload = change_phase(repo, run_id, "cancelled", "cancel requested from CLI")
    print(__import__("json").dumps(payload, ensure_ascii=False, indent=2))
    return 0


def checkpoint_lifecycle(args) -> int:
    root = Path(args.repo).resolve()
    lifecycle = CheckpointLifecycle(
        root / ".simplicio-loop" / "loop-runs",
        task_id=args.task_id,
        attempt_id=args.attempt_id,
        source_commit=args.source_commit,
        mapper_generation=args.mapper_generation,
        base_path=args.base_path or root,
    )
    try:
        if args.lifecycle_action == "inspect":
            payload = lifecycle.load(args.candidate_id, args.shard_id)
        elif args.lifecycle_action == "cancel":
            payload = lifecycle.cancel(args.candidate_id, reason=args.reason)
        elif args.lifecycle_action == "gc":
            payload = lifecycle.gc(
                retention_ns=max(0, args.retention_seconds) * 1_000_000_000,
                apply=args.apply,
            )
        else:
            raise LifecycleError("unsupported lifecycle action")
    except (LifecycleError, OSError, ValueError) as exc:
        payload = {"schema": "simplicio.loop.checkpoint-lifecycle/v1",
                   "status": "HELD", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def oracle(loop_dir: str, run_dir: str, response_text: str, flow_gap: str,
           write_receipt: bool) -> int:
    """Evaluate the shared completion oracle and its cross-runtime parity."""
    payload = evaluate_matrix(loop_dir, run_dir, response_text=response_text, flow_gap=flow_gap)
    if write_receipt:
        # Persist the canonical verdict once; the matrix is only the parity proof.
        from .oracle import evaluate_completion
        verdict = evaluate_completion(loop_dir, run_dir, response_text=response_text,
                                      flow_gap=flow_gap)
        payload["receipt_path"] = persist_completion_receipt(verdict, loop_dir, run_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("parity") and payload.get("signature", [False])[0] else 1


def progress(repo: str, run_id: str, fmt: str, once: bool, interval: float,
             no_animation: bool = False, ascii_only: bool = False) -> int:
    """Render a run's portable progress event for an LLM, terminal, or dashboard."""
    try:
        status = read_status(repo, run_id)
    except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"schema": "simplicio.progress/v1", "status": "UNVERIFIED",
                          "reason_code": "run_missing", "error": str(exc)}, ensure_ascii=False))
        return 2
    if not status or not status.get("run_dir"):
        print(json.dumps({"schema": "simplicio.progress/v1", "status": "UNVERIFIED",
                          "reason_code": "run_missing"}, ensure_ascii=False))
        return 2
    if fmt != "json":
        try:
            from .dashboard import cli as dashboard_cli
            hint = dashboard_cli.panel_hint()
            if hint is not None:
                print(hint, file=sys.stderr)
        except Exception:
            pass
    stream_progress(status["run_dir"], fmt=fmt, once=once, interval=interval,
                    no_animation=no_animation, ascii_only=ascii_only)
    return 0


def maintenance_deferred(repo: str, run_id: str, mode: str, disposition: str,
                         correction_summary: str, deferral_reason: str,
                         resume_instructions: list[str], evidence_status: str) -> int:
    if mode != "maintenance_deferred" or disposition != "backlog_only":
        print(json.dumps({
            "ready": False,
            "reason_code": "maintenance_mode_invalid",
            "tag": "UNVERIFIED",
        }, ensure_ascii=False, sort_keys=True))
        return 2
    payload = defer_maintenance_backlog_only(
        repo,
        run_id,
        correction_summary=correction_summary,
        deferral_reason=deferral_reason,
        resume_instructions=resume_instructions,
        evidence_status=evidence_status,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def deliver(repo: str, run_id: str, state: str, source_kind: str, payload_file: str) -> int:
    source_payload = {}
    if payload_file:
        source_payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
    payload = reconcile_delivery(repo, run_id, state, source_kind=source_kind, source_payload=source_payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def decide(repo: str, run_id: str, decision_id: str, answer: str, impact: str) -> int:
    payload = apply_human_decision(repo, run_id, decision_id, answer, impact=impact)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def sync_source(repo: str, run_id: str, source: str, external_repo: str, pr: int, tag: str) -> int:
    payload = sync_source_state(repo, run_id, source, external_repo=external_repo, pr=pr or None, tag=tag)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _drain_cli_failure(reason_code: str, reason: str, **extra) -> dict:
    """Compatibility wrapper for the focused command helpers."""
    return _inspection_cli.drain_cli_failure(DRAIN_SCHEMA, reason_code, reason, **extra)


def _read_drain_snapshot(path: str):
    return _inspection_cli.read_drain_snapshot(path, _drain_cli_failure)


def _valid_drain_result(payload) -> bool:
    return _inspection_cli.valid_drain_result(DRAIN_SCHEMA, payload)


def drain(action: str, snapshot_path: str, receipt_path: str, polls_required: int) -> int:
    """Compatibility wrapper that preserves CLI-level dependency monkeypatches."""
    return _inspection_cli.drain(
        action, snapshot_path, receipt_path, polls_required,
        evaluator=evaluate_drain, persist=persist_drain_receipt, load=load_drain_receipt,
        receipt_error=DrainReceiptError, failure=_drain_cli_failure,
        snapshot_reader=_read_drain_snapshot, result_validator=_valid_drain_result,
    )
def _load_handshake(handshake_json: str, handshake_file: str):
    """Compatibility wrapper that preserves CLI-level validator monkeypatches."""
    return _inspection_cli._load_handshake(
        handshake_json, handshake_file, validator=validate_handshake,
        ledger_error=LedgerError,
    )


def ledger_replay(path: str, compatibility: bool, recover_trailing: bool,
                  handshake_json: str, handshake_file: str, command: str = "replay") -> int:
    """Compatibility wrapper for the focused read-only ledger surface."""
    return _inspection_cli.ledger_replay(
        path, compatibility, recover_trailing, handshake_json, handshake_file,
        command, handshake_loader=_load_handshake, event_ledger=EventLedger,
        ledger_error=LedgerError, context_schema=CONTEXT_SCHEMA,
        handshake_schema=HANDSHAKE_SCHEMA, required_context_fields=REQUIRED_CONTEXT_FIELDS,
    )


def findings_command(args) -> int:
    """Compatibility wrapper for the focused findings command surface."""
    return _inspection_cli.findings_command(args)


def retrospective_command(args) -> int:
    from .retrospective import retrospective
    result = retrospective(args.repo, args.run_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _load_stack_components(path: str):
    from .stack_lock import load_component_observations

    try:
        return load_component_observations(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read component observations: {exc}") from exc


def stack_command(args) -> int:
    from .stack_lock import (
        StackLock,
        StackLockError,
        diagnose_stack,
        load_stack_lock,
        load_stack_registry,
        write_stack_lock,
    )

    try:
        if args.stack_command == "lock":
            components = _load_stack_components(args.components)
            registry_path = getattr(args, "registry", "")
            if registry_path:
                diagnosis = diagnose_stack(
                    components,
                    load_stack_registry(registry_path),
                    args.route,
                )
                if diagnosis.status != "READY":
                    print(json.dumps({
                        "schema": "simplicio.stack-lock-command/v1",
                        "status": "BLOCKED",
                        "reason_code": "stack_compatibility_blocked",
                        "diagnostics": diagnosis.to_dict(),
                    }, ensure_ascii=False, sort_keys=True))
                    return 2
            lock = StackLock.create(components, args.route, run_id=args.run_id)
            path = write_stack_lock(lock, args.output)
            result = {
                "schema": "simplicio.stack-lock-command/v1",
                "status": "LOCKED",
                "path": str(path),
                "lock_hash": lock.lock_hash,
                "route": lock.route,
                "run_id": lock.run_id,
            }
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0

        lock = load_stack_lock(args.lock)
        route = args.route or lock.route
        lock.verify_unchanged(_load_stack_components(args.components), route)
        result = {
            "schema": "simplicio.stack-lock-command/v1",
            "status": "VERIFIED",
            "path": str(args.lock),
            "lock_hash": lock.lock_hash,
            "route": route,
            "run_id": lock.run_id,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, StackLockError) as exc:
        print(json.dumps({
            "schema": "simplicio.stack-lock-command/v1",
            "status": "BLOCKED",
            "reason_code": "stack_lock_invalid",
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2


def stack_doctor_command(args) -> int:
    """Report installed stack identity and route readiness without side effects."""
    from .stack_lock import discover_installed_components

    try:
        components = discover_installed_components()
        by_name = {component.name: component for component in components}
        required = ("simplicio-loop", "simplicio-mapper")
        missing = [name for name in required if not by_name.get(name, None) or not by_name[name].available]
        routes = {
            "standalone": {
                "available": not missing,
                "missing": missing,
            },
        }
        status = "READY" if routes["standalone"]["available"] else "BLOCKED"
        result = {
            "schema": "simplicio.stack-doctor/v1",
            "status": status,
            "components": [component.to_dict() for component in components],
            "routes": routes,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if status == "READY" else 2
    except (OSError, ValueError) as exc:
        print(json.dumps({
            "schema": "simplicio.stack-doctor/v1",
            "status": "BLOCKED",
            "reason_code": "stack_observation_invalid",
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2


def source_doctor_command(args) -> int:
    """Report SourceAdapter v1 contract readiness without contacting a provider."""
    from .source_contract import SourceCapabilities

    profiles = {
        "local": "local-reference",
        "github": "github-reference",
        "azure-devops": "azure-devops-fixture",
        "jira-cloud": "jira-cloud-fixture",
        "asana": "asana-fixture",
        "trello": "trello-fixture",
    }
    provider = str(args.source_provider)
    capabilities = SourceCapabilities(provider, profiles[provider])
    result = {
        "schema": "simplicio.source-doctor/v1",
        "status": "READY",
        "provider": provider,
        "profile": capabilities.profile,
        "capabilities": capabilities.as_dict(),
        "transport": "fixture-or-injected",
        "real_provider_auth": "UNVERIFIED",
        "effects_attempted": False,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


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

    p_orient = sub.add_parser("orient", help="orient a task through the Mapper survey")
    p_orient.add_argument("--repo", default=".", help="repository root")
    p_orient.add_argument(
        "--task", dest="tasks", action="append", default=[],
        help="task text or issue objective (repeatable with --brief for N tasks)",
    )
    p_orient.add_argument(
        "--brief", action="store_true",
        help=(
            "compact multi-task rendering (issue #1310, Turn 1 of the "
            "plan-once/apply-once hot path): route first, deduped target "
            "content, plan groups, suggested checks, Mapper "
            "generation + context hash, and the exact `apply` command"
        ),
    )
    p_orient.add_argument("--tee", action="store_true", help="persist full JSON output in the reversible tee cache")
    p_orient.add_argument(
        "--target", dest="targets", action="append", default=[],
        help="repo-relative source file selected by Mapper or the task (repeatable)",
    )
    p_orient.add_argument(
        "--verbose", action="store_true",
        help="include full receipts/probes/policy text (default: leads with bounded context only)",
    )
    p_orient.add_argument(
        "--json", action="store_true",
        help="no-op: orient always emits exactly one JSON document on stdout",
    )
    p_orient.add_argument(
        "--pretty", action="store_true",
        help=(
            "indent --brief output for humans (issue #1336: default is compact, "
            "no-indent JSON -- the smaller and more stable the OpenCode tool "
            "output, the higher the prompt-cache hit rate on repeat turns)"
        ),
    )

    p_apply = sub.add_parser(
        "apply",
        help="apply one ops.json (Turn 2 of the plan-once/apply-once hot path, issue #1310)",
    )
    p_apply.add_argument("ops", help="ops.json path, or - for stdin")
    p_apply.add_argument("--repo", default=".", help="repository root")
    p_apply.add_argument(
        "--json", action="store_true",
        help="no-op: apply always emits exactly one JSON document on stdout",
    )
    p_apply.add_argument(
        "--pretty", action="store_true",
        help=(
            "print the full receipt-shaped result, indented (issue #1336: default "
            "is a compact short summary -- status, per-task status/tail on failure, "
            "next_effort, receipt_path -- full per-task/diff detail stays in the "
            "receipt file)"
        ),
    )

    p_retrieve = sub.add_parser("retrieve", help="retrieve and verify a tee-cache output")
    p_retrieve.add_argument("path")
    p_retrieve.add_argument("--repo", default=".")

    p_extensions = sub.add_parser("extensions", help="negotiate installed Loop extension runtimes")
    extensions_sub = p_extensions.add_subparsers(dest="extensions_command", required=True)
    p_ext_doctor = extensions_sub.add_parser("doctor", help="dry-run an exact provider/runtime handshake")
    p_ext_doctor.add_argument("--provider", required=True)
    p_ext_doctor.add_argument("--policy", default="strict-default")
    p_ext_doctor.add_argument("--schema", default="simplicio.extension-handshake/v1")
    p_ext_doctor.add_argument("--json", action="store_true", help="machine-readable output (always JSON)")

    p_oracle = sub.add_parser("oracle", help="evaluate completion and cross-runtime parity")
    p_oracle.add_argument("--loop-dir", default=os.path.join(".simplicio-loop/orchestrator", "loop"))
    p_oracle.add_argument("--run-dir", default=os.environ.get("SIMPLICIO_RUN_DIR", ""))
    p_oracle.add_argument("--response-text", default="")
    p_oracle.add_argument("--flow-gap", default="")
    p_oracle.add_argument("--write-receipt", action="store_true")

    p_status = sub.add_parser("status", help="show the latest run state or a specific run")
    p_status.add_argument("--repo", default=".", help="repository root")
    p_status.add_argument("--run-id", default="", help="run id to inspect")
    p_status.add_argument("--json", action="store_true",
                          help="emit machine-readable JSON (this is also the default)")
    p_status.add_argument("--text", dest="as_text", action="store_true",
                          help="emit human-readable text instead of JSON")

    p_stack = sub.add_parser("stack", help="create or verify an installed-stack lock")
    stack_sub = p_stack.add_subparsers(dest="stack_command", required=True)
    p_stack_lock = stack_sub.add_parser(
        "lock", help="persist a deterministic lock from JSON component observations"
    )
    p_stack_lock.add_argument("--components", required=True, help="JSON component observations")
    p_stack_lock.add_argument(
        "--registry",
        default="",
        help="optional simplicio.stack-registry/v1 compatibility registry; blocks incompatible locks",
    )
    p_stack_lock.add_argument("--route", choices=("standalone",), required=True)
    p_stack_lock.add_argument("--run-id", default="")
    p_stack_lock.add_argument(
        "--output", default=os.path.join(".simplicio-loop", "orchestrator", "stack-lock.json")
    )
    p_stack_verify = stack_sub.add_parser(
        "verify", help="verify current observations against a persisted lock"
    )
    p_stack_verify.add_argument("--lock", required=True, help="persisted stack lock JSON")
    p_stack_verify.add_argument("--components", required=True, help="JSON component observations")
    p_stack_verify.add_argument("--route", choices=("standalone",), default=None)

    p_doctor = sub.add_parser(
        "doctor",
        help="inspect the installed stack or storage routing (default: stack health overview)",
        description=(
            "Inspect stack health and component readiness. "
            "Running without a subcommand executes the general stack health overview "
            "(equivalent to 'doctor all') without requiring --storage or a subcommand."
        ),
    )
    p_doctor.set_defaults(doctor_command=None, stack_json=False, doctor_json=False, all_json=False, all_online=False,
                          login_json=False, online=False)
    p_doctor.add_argument("--online", action="store_true",
                          help="overview: ask GitHub for the latest release (offline by default)")
    p_doctor.add_argument("--storage", action="store_true",
                          help="inspect the Loop storage adapter boundary")
    p_doctor.add_argument("--route", choices=("legacy", "shadow", "mapper"), default="mapper")
    p_doctor.add_argument("--data-dir", default=None)
    p_doctor.add_argument("--repo", default=".", help="repository root for cutover diagnostics")
    p_doctor.add_argument("--require-capability", action="append", default=[])
    p_doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    doctor_sub = p_doctor.add_subparsers(
        dest="doctor_command",
        title="subcommands",
        description="subcommands for targeted component inspection (default: runs overview)",
    )
    p_doctor_stack = doctor_sub.add_parser(
        "stack", help="report installed component identity and route readiness"
    )
    p_doctor_stack.add_argument("--json", dest="stack_json", action="store_true",
                                help="emit machine-readable JSON")
    p_doctor_source = doctor_sub.add_parser(
        "source", help="report SourceAdapter v1 contract readiness"
    )
    p_doctor_source.add_argument(
        "--provider",
        dest="source_provider",
        choices=("local", "github", "azure-devops", "jira-cloud", "asana", "trello"),
        default="local",
    )
    p_doctor_source.add_argument("--json", dest="doctor_json", action="store_true",
                                 help="emit machine-readable JSON")

    p_doctor_all = doctor_sub.add_parser(
        "all", help="overview: login, update, distribution, Runtime, PATH operators, disk (same as bare `doctor`)"
    )
    p_doctor_all.add_argument("--json", dest="all_json", action="store_true", help="emit machine-readable JSON")
    p_doctor_all.add_argument("--online", dest="all_online", action="store_true",
                              help="ask GitHub for the latest release (offline by default)")
    p_doctor_login = doctor_sub.add_parser("login", help="only the login check (shared with the Runtime)")
    p_doctor_login.add_argument("--json", dest="login_json", action="store_true", help="emit machine-readable JSON")

    p_doctor_mapper = doctor_sub.add_parser(
        "mapper", help="check that the installed simplicio_mapper is the expected build"
    )
    p_doctor_mapper.add_argument("--repo", default=".", help="monorepo checkout to compare the commit with")
    p_doctor_mapper.add_argument("--json", dest="mapper_json", action="store_true",
                                 help="emit machine-readable JSON")

    p_inspect = sub.add_parser("inspect", help="inspect storage routing and MapperStore capabilities")
    p_inspect.add_argument("--storage", action="store_true", required=True,
                           help="inspect the Loop storage adapter boundary")
    p_inspect.add_argument("--route", choices=("legacy", "shadow", "mapper"), default="mapper")
    p_inspect.add_argument("--data-dir", default=None)
    p_inspect.add_argument("--repo", default=".", help="repository root for cutover diagnostics")
    p_inspect.add_argument("--require-capability", action="append", default=[])
    p_inspect.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    p_map = sub.add_parser("map", help="map-service cross-module status")
    map_sub = p_map.add_subparsers(dest="map_command", required=True)
    configure_map_commands(map_sub)

    p_squads = sub.add_parser("squads", help="plan squads and check the squad merge gate")
    configure_squads_commands(p_squads.add_subparsers(dest="squads_command", required=True))

    p_preflight = sub.add_parser(
        "preflight", help="verify bound operators (mapper/dev-cli) are installed")
    p_preflight.add_argument("--repo", default=".", help="repository root")
    p_preflight.add_argument("--json", action="store_true",
                             help="emit machine-readable JSON (default: human-readable text)")
    p_preflight.add_argument(
        "--strict",
        action="store_true",
        help="arm SIMPLICIO_LOOP_STRICT: forbid hand-edit, lock evidence/mutation authority",
    )

    p_economy = sub.add_parser(
        "economy",
        help="fastest + cheapest profile: token economy, bounded CPU/RAM, Prism/asyncio parallel",
    )
    economy_sub = p_economy.add_subparsers(dest="economy_command", required=True)
    p_economy_status = economy_sub.add_parser(
        "status", help="show recommended vs applied economy-parallel env"
    )
    p_economy_status.add_argument("--json", action="store_true")
    p_economy_print = economy_sub.add_parser(
        "print", help="print shell exports (ps1 on Windows, sh elsewhere)"
    )
    p_economy_print.add_argument(
        "--shell", choices=("auto", "ps1", "sh"), default="auto"
    )
    p_economy_print.add_argument("--json", action="store_true")
    p_economy_apply = economy_sub.add_parser(
        "apply",
        help="apply profile to this process + ~/.simplicio-loop + Windows User env",
    )
    p_economy_apply.add_argument(
        "--user",
        action="store_true",
        default=True,
        help="persist to Windows User env / shell files (default)",
    )
    p_economy_apply.add_argument(
        "--no-user",
        action="store_true",
        help="only mutate the current process environ",
    )
    p_economy_apply.add_argument("--json", action="store_true")

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

    p_verify = sub.add_parser("verify", help="run the independent watcher and delivery gates")
    p_verify.add_argument("--repo", default=".", help="repository root")
    p_verify.add_argument("run_id", help="run id to verify")

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

    p_progress = sub.add_parser("progress", help="render visual progress for a run")
    p_progress.add_argument("--repo", default=".", help="repository root")
    p_progress.add_argument("run_id", nargs="?", help="run id to render (legacy positional form)")
    p_progress.add_argument("--run", dest="run_flag", default="",
                            help="run id to render (explicit form)")
    p_progress.add_argument("--format", choices=("text", "json", "markdown", "ansi"),
                            default="text", dest="fmt", help="output format")
    p_progress.add_argument("--once", action="store_true", help="render one snapshot")
    p_progress.add_argument("--no-animation", action="store_true",
                            help="emit one static snapshot without spinner/ANSI control codes")
    p_progress.add_argument("--ascii", action="store_true", dest="ascii_only",
                            help="use ASCII icons/bar for terminals without Unicode support")
    p_progress.add_argument("--interval", type=float, default=0.25,
                            help="animation polling interval in seconds")

    p_resume = sub.add_parser("resume", help="resume a non-terminal run")
    p_resume.add_argument("--repo", default=".", help="repository root")
    p_resume.add_argument("run_id", help="run id to resume")

    p_tick = sub.add_parser("tick", help="execute one planned task through simplicio-dev-cli")
    p_tick.add_argument("--repo", default=".", help="repository root")
    p_tick.add_argument("run_id", help="run id to tick")
    p_tick.add_argument("--task-index", type=int, default=1, help="1-based task index")
    p_tick.add_argument(
        "--provider-worker", choices=("openrouter",), default=None,
        help="explicitly authorize the external OpenRouter proposal worker",
    )

    def _configure_batch_parser(parser):
        parser.add_argument("--repo", default=".", help="repository root")
        parser.add_argument("run_id", help="run id to dispatch")
        parser.add_argument(
            "--task-indices",
            default="",
            help="comma-separated 1-based task indices (default: every task in the contract)",
        )
        parser.add_argument(
            "--max-workers",
            type=int,
            default=0,
            help="worker demand (default/0: automatic; live CPU/RAM/disk admission governs concurrency; positive values set an explicit ceiling)",
        )
        parser.add_argument("--retry-budget", type=int, default=3, help="retries after the first attempt")
        parser.add_argument(
            "--provider-worker", choices=("openrouter",), default=None,
            help="explicitly authorize the external OpenRouter proposal worker",
        )
        parser.add_argument(
            "--batch-size", type=int, default=None,
            help="Prism wave width (default/minimum: 10; no logical upper bound, e.g. 30)",
        )
        parser.add_argument(
            "--serial", action="store_true",
            help="disable the default isolated fan-out and force the shared-run serial lane",
        )

    p_batch = sub.add_parser("batch", help="continuously dispatch ready tasks through simplicio-dev-cli")
    _configure_batch_parser(p_batch)
    p_wave = sub.add_parser("wave", help="dispatch a governed wave with reconciliation barriers")
    _configure_batch_parser(p_wave)
    p_prism = sub.add_parser("prism", help="dispatch work through the governed Prism route")
    _configure_batch_parser(p_prism)

    p_cancel = sub.add_parser("cancel", help="cancel a non-terminal run")
    p_cancel.add_argument("--repo", default=".", help="repository root")
    p_cancel.add_argument("run_id", help="run id to cancel")

    p_checkpoint = sub.add_parser(
        "checkpoint", help="inspect, cancel, or garbage-collect candidate checkpoints")
    p_checkpoint.add_argument("lifecycle_action", choices=("inspect", "cancel", "gc"))
    p_checkpoint.add_argument("--repo", default=".")
    p_checkpoint.add_argument("--task-id", required=True)
    p_checkpoint.add_argument("--attempt-id", required=True)
    p_checkpoint.add_argument("--source-commit", required=True)
    p_checkpoint.add_argument("--mapper-generation", required=True)
    p_checkpoint.add_argument("--base-path", default="")
    p_checkpoint.add_argument("--candidate-id", action="append", default=[])
    p_checkpoint.add_argument("--shard-id", default="candidate")
    p_checkpoint.add_argument("--reason", default="operator_cancelled")
    p_checkpoint.add_argument("--retention-seconds", type=int, default=86400)
    p_checkpoint.add_argument("--apply", action="store_true")

    p_maintenance = sub.add_parser(
        "maintenance-deferred",
        aliases=["defer-maintenance"],
        help="record a maintenance-deferred backlog-only transition",
    )
    p_maintenance.add_argument("--repo", default=".", help="repository root")
    p_maintenance.add_argument("run_id", help="run id to update")
    p_maintenance.add_argument(
        "--mode", choices=("active", "maintenance_deferred"), required=True,
        help="explicit runner mode",
    )
    p_maintenance.add_argument(
        "--disposition", choices=("operator", "backlog_only"), required=True,
        help="explicit runner disposition",
    )
    p_maintenance.add_argument("--correction-summary", required=True)
    p_maintenance.add_argument("--deferral-reason", required=True)
    p_maintenance.add_argument("--resume-instruction", action="append", default=[])
    p_maintenance.add_argument("--evidence-status", default="UNVERIFIED")

    p_deliver = sub.add_parser("deliver", help="reconcile delivery state against local/external source evidence")
    p_deliver.add_argument("--repo", default=".", help="repository root")
    p_deliver.add_argument("run_id", help="run id to reconcile")
    p_deliver.add_argument("--state", required=True, help="delivery state reached")
    p_deliver.add_argument("--source-kind", default="local", help="source kind for this reconciliation")
    p_deliver.add_argument("--payload-file", default="", help="JSON file with source evidence payload")

    p_decide = sub.add_parser("decide", help="apply a human decision and invalidate dependent artifacts")
    p_decide.add_argument("--repo", default=".", help="repository root")
    p_decide.add_argument("run_id", help="run id to update")
    p_decide.add_argument("--decision-id", required=True, help="decision/question identifier")
    p_decide.add_argument("--answer", required=True, help="human answer")
    p_decide.add_argument("--impact", default="behavior-change", help="impact classification")

    p_sync = sub.add_parser("sync-source", help="requery external source state and reconcile delivery")
    p_sync.add_argument("--repo", default=".", help="repository root")
    p_sync.add_argument("run_id", help="run id to update")
    p_sync.add_argument("--source", required=True, help="external source kind")
    p_sync.add_argument("--external-repo", default="", help="external repo identifier, ex owner/name")
    p_sync.add_argument("--pr", type=int, default=0, help="pull request number")
    p_sync.add_argument("--tag", default="", help="release tag")

    p_drain = sub.add_parser("drain", help="evaluate, persist, or load a queue-drain receipt")
    p_drain.add_argument("action", nargs="?", default="",
                          help="operation to perform: evaluate, persist, or load")
    p_drain.add_argument("--snapshot", "--snapshot-file", dest="snapshot_path", default="",
                         help="JSON scheduler/source snapshot (evaluate and persist)")
    p_drain.add_argument("--receipt", "--receipt-file", dest="receipt_path", default="",
                         help="receipt JSON path (persist and load)")
    p_drain.add_argument("--polls-required", type=int, default=2,
                         help="identical empty polls required (default: %(default)s)")
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
    p_ledger = sub.add_parser("ledger", help="validate/replay the operational event ledger")
    p_findings = sub.add_parser("findings", help="WI-466: inspect and reconcile continuous findings")
    findings_sub = p_findings.add_subparsers(dest="findings_command", required=True)
    p_f_list = findings_sub.add_parser("list", help="list all routed findings (JSONL)")
    p_f_list.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_report = findings_sub.add_parser("report", help="show aggregated finding counts by stage/severity")
    p_f_report.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_reconcile = findings_sub.add_parser("reconcile", help="show dedup state and untracked findings")
    p_f_reconcile.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_doctor = findings_sub.add_parser("doctor", help="health-check the findings store and router state")
    p_f_doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_import = findings_sub.add_parser("import", help="create one GitHub issue for each JSON finding")
    p_f_import.add_argument("path", help="JSON array of findings or object with findings array")
    p_f_import.add_argument("--repo-map", default="", help="JSON map from source parent to owner/repo")
    p_f_import.add_argument("--label", action="append", default=[], help="label to add to each issue (repeatable)")
    p_f_import.add_argument("--dry-run", action="store_true", help="resolve repositories without creating issues")
    p_f_import.add_argument("--receipt", default="", help="persistent batch receipt path for safe retries")
    p_learn = sub.add_parser("learn", help="derive durable lessons from completed runs")
    learn_sub = p_learn.add_subparsers(dest="learn_command", required=True)
    p_ret = learn_sub.add_parser("retrospective", help="deduplicate trajectory lessons and write a receipt")
    p_ret.add_argument("--repo", default=".")
    p_ret.add_argument("--run", dest="run_id", default=None)
    ledger_sub = p_ledger.add_subparsers(dest="ledger_command", required=True)
    for ledger_command in ("replay", "validate"):
        p_ledger_action = ledger_sub.add_parser(
            ledger_command,
            help="%s events with hash-chain and context validation" % ledger_command,
        )
        p_ledger_action.add_argument("--path", required=True, help="JSONL EventLedger path")
        p_ledger_action.add_argument(
            "--compatibility",
            action="store_true",
            help="explicitly allow legacy v1 rows without context/handshake",
        )
        p_ledger_action.add_argument(
            "--recover-trailing",
            action="store_true",
            help="drop one corrupt trailing JSONL row under the ledger lock",
        )
        handshake = p_ledger_action.add_mutually_exclusive_group()
        handshake.add_argument(
            "--handshake-json",
            default="",
            help="inline executor handshake JSON (strict mode requires it)",
        )
        handshake.add_argument(
            "--handshake-file",
            default="",
            help="file containing executor handshake JSON (strict mode requires it)",
        )

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
