"""`orient`, `apply` and `retrieve`: Mapper-backed orientation and the tee cache.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Mapping
from typing import Sequence
import asyncio
import hashlib
import json
import re
import subprocess
import tempfile

from ._base import impl

from ..economy_profile import llm_max_speed_orientation_contract
from ..json_order import stable_first
from ..state_dir import ensure_state_dir
from .orient_mapper import (MapperIndexRunning, MapperIndexTimedOut, ORIENT_RECEIPT_SCHEMA, ORIENT_SCHEMA, OrientBudgetExceeded, _orient_deadline, _orient_remaining)

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
    asyncio.run(impl()._ensure_project_map(root, budget=_orient_remaining(deadline)))
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
        payload = impl().orient_brief(root, task_list, targets=targets)
        if tee:
            from ..tee_cache import write
            path = write(root, _brief_dump(payload, pretty=pretty))
            payload["tee_path"] = str(path)
        print(_brief_dump(payload, pretty=pretty))
        return 0 if payload.get("status") in {"READY", "FALLBACK"} else 2
    try:
        payload, code = impl()._orient_core(root, task, targets, verbose)
    except (MapperIndexTimedOut, MapperIndexRunning) as exc:
        payload = _mapper_index_budget_payload(ORIENT_SCHEMA, exc, root)
        if tee:
            from ..tee_cache import write
            path = write(root, json.dumps(payload, ensure_ascii=False, indent=2))
            payload["tee_path"] = str(path)
        print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
        return 2
    if payload.get("status") != "BLOCKED":
        from ..survey import write_survey
        prov = _orient_provider_provenance(payload)
        write_survey(root, [{"task": task, "operator": prov.get("operator"),
                             "generation": prov.get("generation"),
                             "context_hash": prov.get("context_hash")}])
    if tee:
        from ..tee_cache import write
        path = write(root, json.dumps(payload, ensure_ascii=False, indent=2))
        payload["tee_path"] = str(path)
    print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
    return code


def add_orient(sub):
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


def add_apply(sub):
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


def add_retrieve(sub):
    p_retrieve = sub.add_parser("retrieve", help="retrieve and verify a tee-cache output")
    p_retrieve.add_argument("path")
    p_retrieve.add_argument("--repo", default=".")
