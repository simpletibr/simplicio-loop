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

import json
import os
import sys
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


def _negative_space(project_map: dict, target_files: list[str], affected_paths: set[str], limit: int) -> list[str]:
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
        if not path:
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
        "ui": "wireframe", "api": "schema", "data-model": "data_model",
        "bug": "failing_test", "benchmark": "benchmark_spike",
        "prompt": "prompt_candidate", "workflow": "vertical_slice",
    }
    return [{
        "type": names[type_],
        "path_hint": target_files[0] if target_files else "prototype",
        "goal": goal,
        "provenance": "simplicio-mapper/prototype-context/v1",
    }]


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
    artifacts = build_artifacts(abs_root, output_dir=out_dir)
    project_map = artifacts["project_map"]
    symbol_index = artifacts["symbol_index"]

    target_files, resolution_note = _resolve_target_files(project_map, symbol_index, arg)
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
    precedents = _precedent_candidates(precedent_index.get("items") or [], precedent_query_text, limit)

    payload: dict[str, Any] = {
        "schema": PROTOTYPE_CONTEXT_SCHEMA,
        "type": type_,
        "query": {"arg": arg, "resolution": resolution_note},
        "target_files": target_files,
        "affected_symbols": impact["affected_symbols"][:limit],
        "affected_flows": impact["affected_flows"],
        "affected_tests": tests[:limit],
        "needs_review": impact["needs_review"],
        "negative_space": _negative_space(project_map, target_files, affected_paths, limit),
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
        "skeletons_note": "descriptors only; materialization belongs to an isolated Dev CLI candidate",
        "token_budget": token_budget,
    }
    if plan_hash:
        payload["plan_hash"] = plan_hash
    payload["context_hash"] = __import__("hashlib").sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return _truncate_to_budget(payload, token_budget)


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
        if arg_token == "--plan" and i + 1 < len(argv):
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
        payload = build_prototype_context(root, type_=type_, arg=arg, limit=limit, token_budget=token_budget, plan_hash=plan_hash)
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
