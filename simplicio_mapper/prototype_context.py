"""``simplicio-mapper prototype-context`` -- Phase-0 bounded context pack for
Prototype-First (issue #286, upstream contract `simplicio-loop#568`).

Issue #286 asks for a large, cross-repo Prototype-First context pipeline:
canonical-map-backed context packs shared across worktrees with incremental
overlays, deterministic skeleton generation for schemas/data-models/failing
tests/vertical slices, precedent ranking with provenance/confidence,
token/context byte budgets with semantic truncation, receipt/hash
integration with the Loop and Runtime, and a benchmark comparing
full-read/remap against this command across golden repos in four languages
plus a monorepo. Building all of that in one slice would be speculating
about the canonical-map/overlay lifecycle (issue #236, still in progress
itself -- see `simplicio_mapper/cli/_canonical.py`) and about a Loop/Runtime
receipt contract that does not exist yet on this side.

This module implements only the slice that is genuinely buildable and
verifiable from within this repo today, using artifacts this repo already
produces (`build_artifacts()` -- the same in-memory artifacts F10 `ask`
already answers from, see `simplicio_mapper/query.py`):

- a query-by-type surface (`--type {ui,api,data-model,bug,benchmark,prompt,
  workflow}`, issue #286 step 2) that resolves a symbol-or-path argument
  into a bounded set of affected symbols, tests, and doc references,
  reusing `query._impact` / `query._tests_for` (step 3);
- a best-effort "negative space" hint -- files under top-level directories
  the impact set never touches (step 4) -- explicitly labeled as a heuristic
  boundary hint, never a guarantee of completeness;
- a token/byte budget with truncation that trims the largest lists first and
  always reports how many entries were omitted (step 9), using the same
  `heuristic:chars-div-4` estimator as `savings.py`/`token_budget.py`;
- a stable `simplicio.prototype-context/v1` envelope exposed via
  `simplicio-mapper prototype-context <root> --type <type> --arg <target>
  --json` (step 10, partial -- only this one entry point);
- **precedent ranking integrated into the envelope** (step 6, follow-up
  landed in this same slice): the `precedents` field reuses
  `query._local_precedent_fallback` -- the same local keyword-overlap
  ranking `ask precedent` already falls back to when the native
  `simplicio` runtime binary is absent -- against `precedent-index.json`,
  annotated with a `confidence` (token-overlap count) and `provenance`
  string on every entry. This is explicitly a **local, estimated** ranking:
  it does not shell out to the native runtime the way `ask precedent`
  itself can, and `confidence` is never presented as a measured relevance
  score, only a keyword-overlap count.

Explicitly out of scope here (left for follow-up issues once the
cross-repo/canonical-map pieces they depend on exist):

- Canonical default-branch map reuse / per-worktree overlays (steps 1, 7, 8)
  -- depends on issue #236/#263 landing an operational canonical lifecycle
  first; this command always resolves from the worktree it is run in.
- Deterministic skeleton generation for schemas/data models/failing tests/
  vertical slices (step 5) -- a separate, larger feature; the envelope's
  `skeletons` field is always an empty list with a `note` saying so, never a
  fake/placeholder skeleton.
- Native-runtime delegation for the `precedents` field above -- unlike `ask
  precedent`, this envelope never shells out to the `simplicio` runtime
  binary; it only ever uses the local fallback ranking.
- Receipt/hash integration with the Loop/Runtime (step 11) and the
  full-read/remap benchmark across golden repos (step 12, benchmark) --
  both require infrastructure/consumers this repo does not own.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from typing import Any

from .mapper import build_artifacts
from .query import _impact, _local_precedent_fallback, _resolve_symbol_name, _tests_for, _tokenize
from .savings import estimate_tokens

PROTOTYPE_CONTEXT_SCHEMA = "simplicio.prototype-context/v1"

# Query types named explicitly by issue #286 step 2 ("Definir query por
# tipo: UI, API, data model, bug, benchmark, prompt, workflow"), kebab-cased
# for CLI/JSON use.
ALLOWED_TYPES = (
    "ui",
    "api",
    "data-model",
    "bug",
    "benchmark",
    "prompt",
    "workflow",
)

DEFAULT_LIMIT = 20
DEFAULT_TOKEN_BUDGET = 8000

_SECRET_BASENAME_MARKERS = (".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
_SECRET_SUBSTRINGS = ("secret", "token", "password", "passwd", "credential", "private-key", "private_key")
_BINARY_EXTENSIONS = (
    ".7z",
    ".bin",
    ".bmp",
    ".class",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".lockb",
    ".mp4",
    ".o",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".wasm",
    ".webp",
    ".zip",
)

_MIN_TRUNCATE_ITEMS = 1
_MAX_TRUNCATE_ITERATIONS = 20

_TRUNCATABLE_FIELDS = (
    "affected_symbols",
    "affected_tests",
    "needs_review",
    "negative_space",
    "precedents",
)


class PrototypeContextError(RuntimeError):
    """Raised for invalid input (unknown type, missing/empty target)."""


def _is_forbidden_context_path(path: str) -> bool:
    """Return True for paths that must not enter a prototype context pack.

    This command is a boundary for downstream prototype generation. Even if a
    lower-level mapper artifact contains a sensitive-looking path, the context
    pack refuses to surface it as target/impact/negative-space/precedent
    evidence. The check is intentionally conservative and path-only: it avoids
    reading file contents while still catching common secret names and binary
    artifacts requested by issue #286's acceptance criteria.
    """
    normalized = path.replace("\\", "/").strip("/").lower()
    if not normalized:
        return True
    basename = normalized.rsplit("/", 1)[-1]
    if basename in _SECRET_BASENAME_MARKERS or basename.startswith(".env."):
        return True
    if any(marker in normalized for marker in _SECRET_SUBSTRINGS):
        return True
    return normalized.endswith(_BINARY_EXTENSIONS)


def _filter_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    excluded: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        if _is_forbidden_context_path(path):
            excluded.append(path)
        else:
            kept.append(path)
    return kept, excluded


def _resolve_target_files(project_map: dict, symbol_index: dict, arg: str) -> tuple[list[str], str]:
    """Resolve *arg* to a list of target files plus a note on how it resolved.

    Accepts either a path already present in ``project_map["files"]`` (used
    as-is) or a symbol name resolved via the symbol index to its
    ``defined_in`` file. Falls back to treating *arg* as a literal path when
    neither matches, so the impact/tests-for computation always has
    *something* to work from and the caller can see why in ``note``.
    """
    known_paths = {f["path"] for f in project_map.get("files", []) if f.get("path")}
    if arg in known_paths:
        return [arg], "resolved-as-path"
    resolved_name = _resolve_symbol_name(symbol_index, arg)
    for symbol in symbol_index.get("symbols", []):
        if symbol.get("qualified_name") == resolved_name and symbol.get("defined_in"):
            return [symbol["defined_in"]], "resolved-as-symbol"
    return [arg], "unresolved-literal"


def _negative_space(
    project_map: dict, target_files: list[str], affected_paths: set[str], limit: int
) -> list[str]:
    """Best-effort "do not touch" hint (issue #286 step 4): files under a
    top-level directory that neither the target nor the impact set touches
    at all. This is a coarse heuristic, not a proof of non-impact -- callers
    must not treat omission from this list as a guarantee either.
    """
    touched_dirs = set()
    for path in list(target_files) + sorted(affected_paths):
        top = path.split("/", 1)[0] if "/" in path else path
        touched_dirs.add(top)
    candidates = []
    for entry in project_map.get("files", []):
        path = entry.get("path")
        if not path or _is_forbidden_context_path(path):
            continue
        top = path.split("/", 1)[0] if "/" in path else path
        if top not in touched_dirs:
            candidates.append(path)
    candidates.sort()
    return candidates[:limit]


def _precedent_candidates(precedent_items: list[dict], query_text: str, limit: int) -> list[dict]:
    """Rank `precedent-index.json` items relevant to *query_text* (issue #286
    step 6, follow-up to the `ask precedent` local fallback).

    Reuses `query._local_precedent_fallback` for the actual ranking/ordering
    -- the same keyword-overlap logic `ask precedent` already falls back to
    locally -- then re-derives a per-item `confidence` (the raw token-overlap
    count) using the same `_tokenize` helper, since the shared fallback
    returns only the ranked items, not their scores. `confidence` is always
    an estimated overlap count, never a claimed measured relevance score.
    """
    ranked = _local_precedent_fallback(precedent_items, query_text, limit)
    query_tokens = _tokenize(query_text)
    candidates = []
    for item in ranked:
        haystack = " ".join(item.get("tags") or []) + " " + str(item.get("summary") or "")
        overlap = len(query_tokens & _tokenize(haystack))
        candidates.append(
            {
                "precedent_id": item.get("id"),
                "path": item.get("path"),
                "summary": item.get("summary"),
                "tags": item.get("tags") or [],
                "confidence": overlap,
                "provenance": "local-keyword-overlap:precedent-index",
            }
        )
    return candidates


def _skeletons(type_: str, target_files: list[str], goal: str) -> list[dict[str, Any]]:
    """Return deterministic, non-production skeleton descriptors."""
    names = {
        "ui": "wireframe",
        "api": "schema",
        "data-model": "data_model",
        "bug": "failing_test",
        "benchmark": "benchmark_spike",
        "prompt": "prompt_candidate",
        "workflow": "vertical_slice",
    }
    return [
        {
            "type": names[type_],
            "path_hint": target_files[0] if target_files else "prototype",
            "goal": goal,
            "provenance": "simplicio-mapper/prototype-context/v1",
        }
    ]


def _truncate_to_budget(payload: dict, token_budget: int) -> dict:
    """Trim the largest of `_TRUNCATABLE_FIELDS` first, tracking omitted
    counts per field, until the serialized payload fits `token_budget` or no
    further trimming is possible. Never raises; a budget too small to fit
    even the minimum shape is honestly reported via `truncated=True` and
    `tokens_estimated` left over-budget rather than silently dropped.
    """
    omitted: dict[str, int] = {}
    iterations = 0
    while iterations < _MAX_TRUNCATE_ITERATIONS:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        tokens = estimate_tokens(serialized)
        if tokens <= token_budget:
            payload["tokens_estimated"] = tokens
            payload["truncated"] = bool(omitted)
            payload["omitted_counts"] = omitted
            return payload
        # pick the longest truncatable list still above the floor
        target_field = None
        target_len = _MIN_TRUNCATE_ITEMS
        for field in _TRUNCATABLE_FIELDS:
            current = payload.get(field) or []
            if len(current) > target_len:
                target_field = field
                target_len = len(current)
        if target_field is None:
            payload["tokens_estimated"] = tokens
            payload["truncated"] = bool(omitted)
            payload["omitted_counts"] = omitted
            return payload
        current = payload[target_field]
        keep = max(_MIN_TRUNCATE_ITEMS, len(current) // 2)
        omitted[target_field] = omitted.get(target_field, 0) + (len(current) - keep)
        payload[target_field] = current[:keep]
        iterations += 1
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    payload["tokens_estimated"] = estimate_tokens(serialized)
    payload["truncated"] = bool(omitted)
    payload["omitted_counts"] = omitted
    return payload


def _run_git(args: list[str], root: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _tree_source_sha(root: str, project_map: dict) -> str:
    digest = hashlib.sha256()
    for entry in sorted(project_map.get("files", []), key=lambda item: item.get("path") or ""):
        path = entry.get("path") or ""
        if not path or _is_forbidden_context_path(path):
            continue
        digest.update(path.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(entry.get("hash") or entry.get("sha256") or "").encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _source_binding(root: str, project_map: dict, context_paths: list[str]) -> dict[str, Any]:
    head = _run_git(["rev-parse", "HEAD"], root)
    tree = _run_git(["rev-parse", "HEAD^{tree}"], root)
    status = _run_git(["status", "--porcelain", "--untracked-files=all"], root)
    source_sha = head or _tree_source_sha(root, project_map)
    shard_digest = hashlib.sha256()
    shards: set[str] = set()
    for path in sorted({p for p in context_paths if p and not _is_forbidden_context_path(p)}):
        shards.add(path.split("/", 1)[0] if "/" in path else path)
        shard_digest.update(path.encode("utf-8", errors="surrogateescape"))
        shard_digest.update(b"\0")
    return {
        "source_sha": source_sha,
        "tree_sha": tree or "",
        "dirty": bool(status),
        "source_kind": "git" if head else "tree-digest",
        "affected_shards": sorted(shards),
        "affected_shards_hash": shard_digest.hexdigest(),
        "invalidation": "invalidate-only-listed-shards-on-source-drift",
    }


def _hash_bound_payload(payload: dict[str, Any]) -> dict[str, Any]:
    final_payload = dict(payload)
    final_payload.pop("context_hash", None)
    canonical = json.dumps(final_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    final_payload["context_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    final_payload["context_hash_algorithm"] = "sha256:canonical-json-without-context_hash"
    return final_payload


def build_prototype_context(
    root: str,
    out_dir: str = ".simplicio",
    type_: str = "",
    arg: str = "",
    limit: int = DEFAULT_LIMIT,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    plan_hash: str = "",
) -> dict[str, Any]:
    """Build the ``simplicio.prototype-context/v1`` envelope for *arg* under
    query *type_*. Raises `PrototypeContextError` for an unknown type or an
    empty target -- never silently defaults either.
    """
    if type_ not in ALLOWED_TYPES:
        raise PrototypeContextError(
            f"unknown prototype-context type: {type_!r} (expected one of {', '.join(ALLOWED_TYPES)})"
        )
    if not arg:
        raise PrototypeContextError("prototype-context requires a non-empty target (--arg)")

    abs_root = os.path.abspath(root)
    started = time.perf_counter()
    artifacts = build_artifacts(abs_root, output_dir=out_dir)
    full_remap_seconds = round(time.perf_counter() - started, 6)
    extraction_started = time.perf_counter()
    project_map = artifacts["project_map"]
    symbol_index = artifacts["symbol_index"]

    target_files, resolution_note = _resolve_target_files(project_map, symbol_index, arg)
    target_files, excluded_target_files = _filter_paths(target_files)
    if not target_files:
        raise PrototypeContextError("prototype-context target resolves only to forbidden/secret/binary paths")
    impact = _impact(abs_root, artifacts, target_files)

    tests: list[str] = []
    seen_tests: set[str] = set()
    for target_file in target_files:
        matches, _total = _tests_for(abs_root, project_map, target_file, limit)
        for match in matches:
            if match not in seen_tests:
                seen_tests.add(match)
                tests.append(match)
    tests.sort()
    tests, excluded_tests = _filter_paths(tests)

    filtered_symbols = []
    excluded_symbol_paths = []
    for sym in impact["affected_symbols"]:
        path = sym.get("path") or ""
        if _is_forbidden_context_path(path):
            excluded_symbol_paths.append(path)
            continue
        filtered_symbols.append(sym)
    impact["affected_symbols"] = filtered_symbols

    affected_paths = {sym["path"] for sym in impact["affected_symbols"] if sym.get("path")}
    affected_paths.update(target_files)
    affected_paths.update(tests)

    precedent_index = artifacts.get("precedent_index") or {}
    precedent_query_text = " ".join(
        filter(
            None,
            [
                type_,
                arg,
                *target_files,
                *(sym.get("symbol") for sym in impact["affected_symbols"] if sym.get("symbol")),
            ],
        )
    )
    precedents = [
        item
        for item in _precedent_candidates(precedent_index.get("items") or [], precedent_query_text, limit)
        if not _is_forbidden_context_path(str(item.get("path") or ""))
    ]
    negative_space = _negative_space(project_map, target_files, affected_paths, limit)
    context_paths = (
        target_files
        + [sym.get("path", "") for sym in impact["affected_symbols"]]
        + tests
        + negative_space
        + [str(item.get("path") or "") for item in precedents]
    )
    source_binding = _source_binding(abs_root, project_map, context_paths)
    extraction_seconds = round(time.perf_counter() - extraction_started, 6)

    payload: dict[str, Any] = {
        "schema": PROTOTYPE_CONTEXT_SCHEMA,
        "type": type_,
        "query": {"arg": arg, "resolution": resolution_note},
        "target_files": target_files,
        "affected_symbols": impact["affected_symbols"][:limit],
        "affected_flows": impact["affected_flows"],
        "affected_tests": tests[:limit],
        "needs_review": impact["needs_review"],
        "negative_space": negative_space,
        "precedents": precedents,
        "precedents_note": (
            "local keyword-overlap ranking against precedent-index.json (issue "
            "#286 step 6, follow-up slice) -- the same fallback `ask precedent` "
            "uses when the native `simplicio` runtime binary is unavailable; "
            "`confidence` is an estimated token-overlap count, never a measured "
            "relevance score, and this envelope never shells out to the native "
            "runtime the way `ask precedent` itself can"
        ),
        "skeletons": _skeletons(type_, target_files, arg),
        "skeletons_note": "deterministic descriptors only; materialization belongs to an isolated Dev CLI candidate and never claims implementation",
        "token_budget": token_budget,
        "budget_policy": {"estimator": "heuristic:chars-div-4", "semantic_truncation": "largest-list-first"},
        "source_binding": source_binding,
        "canonical_reuse": {
            "eligible": not source_binding["dirty"],
            "mode": "worktree-local-effective-context",
            "note": "context pack is hash-bound to source_sha and affected_shards; canonical reuse can supply artifacts before this extraction when index/scan opt in",
        },
        "excluded_context": {
            "paths": sorted(set(excluded_target_files + excluded_tests + excluded_symbol_paths)),
            "policy": "exclude secret-like names and binary extensions from prototype-context",
        },
        "measurements": {
            "full_remap_seconds": full_remap_seconds,
            "prototype_extraction_seconds": extraction_seconds,
            "comparison": "full-remap-build-artifacts-vs-prototype-context-extraction",
        },
    }
    if plan_hash:
        payload["plan_hash"] = plan_hash
    bounded = _truncate_to_budget(payload, token_budget)
    return _hash_bound_payload(bounded)


def run_prototype_context_cli(argv: list[str]) -> int:
    """Entry point for ``simplicio-mapper prototype-context <root> --type
    <type> --arg <target> [--json] [--limit N] [--token-budget N]``.
    """
    root = os.getcwd()
    type_ = ""
    arg = ""
    limit = DEFAULT_LIMIT
    token_budget = DEFAULT_TOKEN_BUDGET
    plan_hash = ""
    as_json = "--json" in argv

    positionals = []
    i = 0
    while i < len(argv):
        arg_token = argv[i]
        if arg_token == "--type" and i + 1 < len(argv):  # noqa: S105 - CLI flag literal, not a credential
            type_ = argv[i + 1]
            i += 2
            continue
        if arg_token == "--arg" and i + 1 < len(argv):  # noqa: S105 - CLI flag literal, not a credential
            arg = argv[i + 1]
            i += 2
            continue
        if arg_token == "--limit" and i + 1 < len(argv):  # noqa: S105 - CLI flag literal, not a credential
            try:
                limit = int(argv[i + 1])
            except ValueError:
                print("--limit requires an integer", file=sys.stderr)
                return 2
            i += 2
            continue
        if arg_token == "--token-budget" and i + 1 < len(argv):  # noqa: S105 - CLI flag literal, not a credential
            try:
                token_budget = int(argv[i + 1])
            except ValueError:
                print("--token-budget requires an integer", file=sys.stderr)
                return 2
            i += 2
            continue
        if arg_token == "--plan" and i + 1 < len(argv):  # noqa: S105 - CLI flag literal, not a credential
            try:
                plan_payload = json.loads(open(argv[i + 1], encoding="utf-8").read())
                plan_hash = str(plan_payload.get("plan_hash") or "")
            except (OSError, ValueError):
                print("--plan requires a readable JSON plan", file=sys.stderr)
                return 2
            i += 2
            continue
        if arg_token == "--json":  # noqa: S105 - CLI flag literal, not a credential
            i += 1
            continue
        if not arg_token.startswith("-"):
            positionals.append(arg_token)
        i += 1

    if positionals:
        root = positionals[0]
        if len(positionals) > 1 and not arg:
            arg = positionals[1]

    try:
        payload = build_prototype_context(
            root, type_=type_, arg=arg, limit=limit, token_budget=token_budget, plan_hash=plan_hash
        )
    except PrototypeContextError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"type:            {payload['type']}")
        print(f"target_files:    {', '.join(payload['target_files'])}")
        print(f"affected_symbols:{len(payload['affected_symbols'])}")
        print(f"affected_tests:  {len(payload['affected_tests'])}")
        print(f"precedents:      {len(payload['precedents'])}")
        print(f"negative_space:  {len(payload['negative_space'])}")
        print(f"tokens_estimated:{payload['tokens_estimated']} (budget {payload['token_budget']})")
        print(f"truncated:       {payload['truncated']}")
    return 0
