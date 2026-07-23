"""Deterministic, indexed, token-budgeted context selection (issue #199).

This module replaces the per-query full-file scan in ``task_context`` with a
two-stage retrieval system:

* **Stage A (index build).** A versioned *retrieval index* is derived from the
  mapper artifacts (``project-map``/``symbol-index``/``call-graph``) during the
  normal scan/index pass -- never during a query. The index carries per-file
  token frequency, document frequency and the term corpus needed for an IDF/BM25
  scorer, plus discriminative fields (path tokens, symbols, roles, importance,
  related tests, dependency edges).
* **Stage B (query planning).** The task is normalized into weighted query
  fields so that an explicit target path, an AC/RN/NFR identifier or an exact
  symbol name outweighs generic natural-language terms.
* **Stage C (ranking).** Deterministic weighted features (exact target/symbol
  match, BM25 content score, call-graph proximity, affected-test relationship,
  recent-change relevance, role/penalty signals) produce an *explainable* score
  with per-candidate ``reason_codes`` -- never a single opaque number built from
  raw set overlap alone.
* **Stage D (span expansion).** For the top candidates only, exact symbol/range
  spans are expanded; every omitted adjacent/full block gets a stable
  ``expand_handle`` so downstream can retrieve it without rerunning whole-repo
  mapping.
* **Stage E (token-budget fitting).** The serialized pack is fitted against an
  explicit token budget using a declared tokenizer policy. When required spans
  exceed the budget the engine returns ``needs_broader_context=True`` with
  ``broader_context`` reason codes instead of silently truncating a load-bearing
  span.
* **Stage F (fidelity gate).** Before declaring the pack sufficient, a vector of
  measurable coverage dimensions (target, identifiers, AC/RN/NFR, referenced
  paths/versions, stack/layer coverage, a verification/test route) is checked
  and an honest ``sufficient`` verdict is returned. High generic lexical overlap
  alone cannot pass.

No third-party dependency is added (stdlib only). The scorer is a documented
deterministic BM25/IDF variant, not LLM-based, and recency never creates
relevance.

The module is intentionally importable and testable without the rest of the
package: every stage has a pure function entry point.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, unquote

from .savings import ESTIMATOR_LABEL, estimate_tokens

# --------------------------------------------------------------------------- #
# Schema / version constants
# --------------------------------------------------------------------------- #
RETRIEVAL_INDEX_SCHEMA = "simplicio.retrieval-index/v1"
RETRIEVAL_SELECTION_SCHEMA = "simplicio.retrieval-selection/v1"
RETRIEVAL_INDEX_VERSION = 1
BUILDER_REVISION = "199.2"

# Tokenizer policy recorded in every receipt so the serialized-byte measurement
# is never silently mistaken for provider-measured usage.
TOKENIZER_POLICY = ESTIMATOR_LABEL

# The legacy chars/4 estimate remains available for span-cost compatibility.
# Final pack enforcement uses the exact canonical UTF-8 JSON bytes instead.
SERIALIZED_TOKEN_TOLERANCE = 0

# Default serialized token budget for the context pack (Stage E). Measured on
# the reference CI runner; overridable via --token-budget.
DEFAULT_TOKEN_BUDGET = 8000

# Penalty applied to generated/vendor/archive/large generic files unless the
# task explicitly targets them.
GENERIC_FILE_PENALTY = 0.4
LARGE_GENERIC_FILE_THRESHOLD_BYTES = 64 * 1024

# Stop words: generic ecosystem / natural-language vocabulary that must not
# dominate coverage. Augmented with the project's existing stop list.
_STOP_WORDS = {
    "about",
    "after",
    "antes",
    "apenas",
    "como",
    "com",
    "cada",
    "das",
    "dos",
    "depois",
    "deve",
    "entre",
    "essa",
    "esse",
    "esta",
    "este",
    "for",
    "from",
    "mais",
    "nao",
    "onde",
    "para",
    "pela",
    "pelo",
    "pode",
    "por",
    "primeiro",
    "quando",
    "que",
    "sao",
    "sem",
    "ser",
    "that",
    "the",
    "then",
    "this",
    "tipo",
    "task",
    "system",
    "uma",
    "uns",
    "with",
    "and",
    "a",
    "an",
    "of",
    "to",
    "in",
    "on",
    "is",
    "are",
    "be",
    "by",
    "as",
    "at",
    "or",
    "it",
    "its",
    "use",
    "using",
    "file",
    "files",
    "code",
    "function",
    "functions",
    "class",
    "module",
    "project",
    "add",
    "update",
    "fix",
    "implement",
    "support",
    "handle",
    "make",
    "set",
    "get",
    "new",
    "old",
    "via",
    "into",
    "when",
    "please",
    "should",
    "want",
    "need",
    "change",
    "changes",
}

# Paths containing these fragments are treated as generated / vendor / archive
# and penalized unless explicitly targeted.
_GENERIC_PATH_FRAGMENTS = (
    "/node_modules/",
    "/vendor/",
    "/.git/",
    "/dist/",
    "/build/",
    "/target/",
    "/__pycache__/",
    "/.simplicio/",
    "/coverage/",
    "/.next/",
    "/out/",
)
_ARCHIVE_PATH_FRAGMENTS = (
    "/archive/",
    "/archives/",
    "/backup/",
    "/backups/",
    "/legacy/",
    "/old/",
)
_GENERATED_BASENAME_HINTS = (
    ".min.",
    "lock.json",
    ".lock",
    "-lock.json",
    ".generated.",
    ".gen.",
)
_ARCHIVE_BASENAME_HINTS = ("archive", "backup", ".bak", ".old")


# --------------------------------------------------------------------------- #
# Text / token helpers
# --------------------------------------------------------------------------- #
def _normalized_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.lower().split())


_TOKEN_RE = re.compile(r"[a-z0-9_][a-z0-9_.]*")
# Case-preserving token regex for symbol detection (camelCase/snake_case).
_SYMBOL_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:[A-Z][a-z0-9_]+)+|[a-z0-9]+_[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    """Tokenize already-normalized-ish text into lowercased alphanumeric tokens."""
    return _TOKEN_RE.findall(_normalized_text(text))


def _is_stopword(token: str) -> bool:
    return token in _STOP_WORDS


def _path_tokens(path: str) -> list[str]:
    norm = path.replace(os.sep, "/").lower()
    parts: list[str] = []
    for chunk in re.split(r"[/._-]+", norm):
        if not chunk:
            continue
        parts.append(chunk)
        # Split camelCase / snake boundaries so `sort_lines` yields sort, lines.
        for sub in re.findall(r"[a-z0-9]+", chunk):
            if len(sub) >= 3:
                parts.append(sub)
    return parts


def _generic_file_flags(path: str, size_bytes: int = 0) -> list[str]:
    norm = "/" + path.replace(os.sep, "/").lower().lstrip("/")
    base = os.path.basename(norm)
    flags: list[str] = []
    if any(frag in norm for frag in _GENERIC_PATH_FRAGMENTS):
        flags.append("generated_or_vendor")
    if any(frag in norm for frag in _ARCHIVE_PATH_FRAGMENTS) or any(
        hint in base for hint in _ARCHIVE_BASENAME_HINTS
    ):
        flags.append("archive")
    if any(hint in base for hint in _GENERATED_BASENAME_HINTS):
        flags.append("generated_or_vendor")
    if int(size_bytes or 0) > LARGE_GENERIC_FILE_THRESHOLD_BYTES:
        flags.append("large")
    return sorted(set(flags))


def _looks_generated(path: str) -> bool:
    """Backward-compatible generated/vendor/archive classification."""
    return bool(_generic_file_flags(path))


# --------------------------------------------------------------------------- #
# Query planning (Stage B)
# --------------------------------------------------------------------------- #
class QueryPlan:
    """Weighted query fields produced from a task description."""

    __slots__ = (
        "target_path",
        "exact_identifiers",
        "path_terms",
        "symbol_terms",
        "ac_ids",
        "error_terms",
        "domain_terms",
        "generic_terms",
    )

    def __init__(
        self,
        *,
        target_path: str = "",
        exact_identifiers: Sequence[str] | None = None,
        path_terms: Sequence[str] | None = None,
        symbol_terms: Sequence[str] | None = None,
        ac_ids: Sequence[str] | None = None,
        error_terms: Sequence[str] | None = None,
        domain_terms: Sequence[str] | None = None,
        generic_terms: Sequence[str] | None = None,
    ) -> None:
        self.target_path = target_path.replace(os.sep, "/").strip()
        self.exact_identifiers = list(exact_identifiers or [])
        self.path_terms = list(path_terms or [])
        self.symbol_terms = list(symbol_terms or [])
        self.ac_ids = list(ac_ids or [])
        self.error_terms = list(error_terms or [])
        self.domain_terms = list(domain_terms or [])
        self.generic_terms = list(generic_terms or [])

    @property
    def all_terms(self) -> list[str]:
        out: list[str] = []
        for group in (
            self.exact_identifiers,
            self.path_terms,
            self.symbol_terms,
            self.ac_ids,
            self.error_terms,
            self.domain_terms,
            self.generic_terms,
        ):
            out.extend(group)
        # de-dup preserving order
        seen: set[str] = set()
        return [t for t in out if not (t in seen or seen.add(t))]

    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "target_path": self.target_path,
                "exact_identifiers": sorted(self.exact_identifiers),
                "path_terms": sorted(self.path_terms),
                "symbol_terms": sorted(self.symbol_terms),
                "ac_ids": sorted(self.ac_ids),
                "error_terms": sorted(self.error_terms),
                "domain_terms": sorted(self.domain_terms),
                "generic_terms": sorted(self.generic_terms),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_path": self.target_path,
            "exact_identifiers": self.exact_identifiers,
            "path_terms": self.path_terms,
            "symbol_terms": self.symbol_terms,
            "ac_ids": self.ac_ids,
            "error_terms": self.error_terms,
            "domain_terms": self.domain_terms,
            "generic_terms": self.generic_terms,
        }


# Identifiers likely to be exact: RN##, AC##, NFR##, error codes, versions.
_IDENTIFIER_RE = re.compile(r"\b([A-Z]{1,4}\d{1,4}|[a-z_]+error|[a-z_]+exception|v\d+\.\d+\.\d+)\b")
_AC_RE = re.compile(r"\b((?:AC|RN|NFR|US)\d{1,4})\b", re.IGNORECASE)


def _is_camel_or_symbol(token: str) -> bool:
    # symbol-like tokens such as sort_lines, TokenCache, buildContextPack
    if "_" in token and len(token) >= 4:
        return True
    if any(c.isupper() for c in token) and any(c.islower() for c in token) and len(token) >= 4:
        return True
    return False


def _symbol_tokens(text: str) -> list[str]:
    """Extract case-preserving symbol-like tokens (camelCase/snake_case)."""
    return [t for t in _SYMBOL_TOKEN_RE.findall(text) if len(t) >= 4]


_TASK_INTENT_NOISE_KEYS = {"schema", "fingerprint"}


def _task_intent_text(value: Any) -> list[str]:
    """Collect only the free-text *values* of a normalized task-intent
    object, skipping its own reserved schema key names (`schema`,
    `fingerprint`) and skipping key names generally.

    `parse_task_intent()` always returns the full normalized schema shape
    (`story`, `acceptance_criteria`, `business_rules`,
    `non_functional_requirements`, `additional_information`, ... - see
    `task_intent.py`), most of which are empty for any given task. Naively
    `json.dumps()`-ing that whole object and tokenizing it (as this used to
    do) fed every one of those field *names* into `domain_terms` as if they
    were part of the task's own vocabulary, on every single task -- diluting
    `coverage_ratio` (matched_count / query_term_count) so badly that a
    task with real, present evidence in the repo (e.g. the word "temporal"
    verbatim in a source comment) could still fail the minimum-coverage gate
    and get an incorrect `needs_broader_context: true`/abstention, because
    the denominator was inflated by ~15+ schema-noise tokens that can never
    match anything.
    """
    texts: list[str] = []
    if isinstance(value, Mapping):
        for key, sub_value in value.items():
            if key in _TASK_INTENT_NOISE_KEYS:
                continue
            texts.extend(_task_intent_text(sub_value))
    elif isinstance(value, (list, tuple)):
        for item in value:
            texts.extend(_task_intent_text(item))
    elif isinstance(value, str):
        if value:
            texts.append(value)
    return texts


def build_query_plan(
    goal: str = "",
    *,
    task_intent: Mapping[str, Any] | None = None,
    target: str = "",
    query_terms: Sequence[str] | None = None,
) -> QueryPlan:
    """Normalize a task into weighted query fields (Stage B)."""
    chunks = [goal]
    if task_intent:
        chunks.extend(_task_intent_text(task_intent))
    text = " ".join(chunks)
    norm = _normalized_text(text)

    exact_identifiers: list[str] = []
    ac_ids: list[str] = []
    for m in _IDENTIFIER_RE.finditer(text):
        tok = m.group(1).lower()
        if _is_stopword(tok):
            continue
        exact_identifiers.append(tok)
        if _AC_RE.fullmatch(m.group(1)):
            ac_ids.append(m.group(1).upper())
    # Also capture explicit AC/RN/NFR inside natural text.
    for m in _AC_RE.finditer(text):
        ac_ids.append(m.group(1).upper())

    # Symbol-like terms (camelCase / snake_case) are strong discriminators.
    symbol_terms: list[str] = []
    for tok in _symbol_tokens(text):
        if len(tok) < 4:
            continue
        symbol_terms.append(tok)

    # Path terms from the goal (slash-delimited hints, file-ish strings).
    path_terms: list[str] = []
    for m in re.finditer(r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,6}", goal):
        seg = m.group(0)
        path_terms.extend(t for t in _path_tokens(seg) if len(t) >= 3 and not _is_stopword(t))

    # Error / exception / version terms.
    error_terms: list[str] = []
    # Domain terms: non-stopword tokens that are not symbol/path specific.
    domain_terms: list[str] = []
    for tok in tokenize(norm):
        if len(tok) < 3 or _is_stopword(tok):
            continue
        if "error" in tok or "exception" in tok or tok.startswith("v") and re.fullmatch(r"v\d+", tok):
            error_terms.append(tok)
        elif tok not in symbol_terms and tok not in exact_identifiers:
            domain_terms.append(tok)

    # If explicit query_terms were supplied, treat them as domain terms too
    # (backward compatibility with select_context_targets callers).
    if query_terms:
        for tok in query_terms:
            t = tok.lower()
            if len(t) >= 3 and not _is_stopword(t) and t not in domain_terms:
                domain_terms.append(t)

    # De-duplicate: a symbol/exact identifier must not also appear (lower-cased)
    # as a generic domain term, otherwise it is double-weighted and the
    # case-preserving form is lost in coverage scoring.
    reserved = {t.lower() for t in symbol_terms} | {t.lower() for t in exact_identifiers}
    domain_terms = [t for t in domain_terms if t.lower() not in reserved]

    return QueryPlan(
        target_path=target,
        exact_identifiers=sorted(set(exact_identifiers)),
        path_terms=sorted(set(path_terms)),
        symbol_terms=sorted(set(symbol_terms)),
        ac_ids=sorted(set(ac_ids)),
        error_terms=sorted(set(error_terms)),
        domain_terms=sorted(set(domain_terms)),
    )


# --------------------------------------------------------------------------- #
# Stage A — retrieval index build
# --------------------------------------------------------------------------- #
def _safe_get_list(value: Any, key: str) -> list:
    if isinstance(value, Mapping) and isinstance(value.get(key), list):
        return value[key]
    return []


def _normalized_path(path: str) -> str:
    return str(path or "").replace(os.sep, "/")


def _stable_hash(payload: Any, *, size: int = 16) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()[:size]


def _chunk_bounds(symbol: Mapping[str, Any]) -> tuple[int, int]:
    line = int(symbol.get("line", 0) or 0)
    start = max(1, line) if line else 0
    end = int(symbol.get("end_line", 0) or 0)
    if start and end < start:
        end = start
    return start, end or start


def _document_fingerprint(entry: Mapping[str, Any], symbols: Sequence[Mapping[str, Any]]) -> str:
    payload = {
        "path": _normalized_path(str(entry.get("path") or "")),
        "language": str(entry.get("language") or ""),
        "roles": sorted(str(v) for v in _safe_get_list(entry, "roles")),
        "importance": float(entry.get("importance", 0.0) or 0.0),
        "size_bytes": int(entry.get("size_bytes", 0) or 0),
        "file_hash": str(entry.get("file_hash") or ""),
        "content_hash": str(entry.get("content_hash") or ""),
        "summary": str(entry.get("summary") or ""),
        "imports": sorted(str(v) for v in _safe_get_list(entry, "imports")),
        "exports": sorted(str(v) for v in _safe_get_list(entry, "exports")),
        "tags": sorted(str(v) for v in _safe_get_list(entry, "tags")),
        "symbols": [
            {
                "name": str(sym.get("name") or ""),
                "qualified_name": str(sym.get("qualified_name") or ""),
                "kind": str(sym.get("kind") or ""),
                "start_line": _chunk_bounds(sym)[0],
                "end_line": _chunk_bounds(sym)[1],
            }
            for sym in sorted(
                symbols,
                key=lambda item: (
                    str(item.get("name") or ""),
                    str(item.get("qualified_name") or ""),
                    int(item.get("line", 0) or 0),
                ),
            )
        ],
    }
    return _stable_hash(payload, size=24)


def _build_chunks(path: str, symbols: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for sym in sorted(
        symbols,
        key=lambda item: (
            int(item.get("line", 0) or 0),
            str(item.get("name") or ""),
            str(item.get("qualified_name") or ""),
        ),
    ):
        start, end = _chunk_bounds(sym)
        if start < 1:
            continue
        name = str(sym.get("name") or "")
        kind = str(sym.get("kind") or "")
        qualified = str(sym.get("qualified_name") or "")
        chunk_identity = {
            "path": path,
            "name": name,
            "kind": kind,
            "qualified_name": qualified,
            "start_line": start,
            "end_line": end,
        }
        chunks.append(
            {
                "chunk_id": f"chunk:{_stable_hash(chunk_identity, size=20)}",
                "symbol": name,
                "kind": kind,
                "qualified_name": qualified,
                "start_line": start,
                "end_line": end,
            }
        )
    if not chunks:
        chunks.append(
            {
                "chunk_id": f"chunk:{_stable_hash({'path': path, 'kind': 'file'}, size=20)}",
                "symbol": "",
                "kind": "file",
                "qualified_name": path,
                "start_line": 1,
                "end_line": 1,
            }
        )
    return chunks


def _source_text(root: str, path: str) -> str:
    """Read source once while building/updating the index, never during ranking."""
    if not root or not path:
        return ""
    root_abs = os.path.abspath(root)
    candidate = os.path.abspath(os.path.join(root_abs, path.replace("/", os.sep)))
    try:
        if os.path.commonpath([root_abs, candidate]) != root_abs:
            return ""
        with open(candidate, encoding="utf-8", errors="replace") as handle:
            return handle.read(1_048_576)
    except (OSError, UnicodeError):
        return ""


def _build_document(
    entry: Mapping[str, Any],
    symbols: Sequence[Mapping[str, Any]],
    *,
    root: str = "",
) -> dict[str, Any]:
    path = _normalized_path(str(entry.get("path") or ""))
    source_text = _source_text(root, path)
    text_parts: list[str] = [path]
    if source_text:
        text_parts.append(source_text)
    text_parts.extend(_path_tokens(path))
    for sym in symbols:
        text_parts.append(str(sym.get("name") or ""))
        text_parts.append(str(sym.get("qualified_name") or ""))
    for key in ("language", "summary", "role", "roles"):
        val = entry.get(key)
        if isinstance(val, str):
            text_parts.append(val)
        elif isinstance(val, list):
            text_parts.extend(str(v) for v in val)
    text_parts.extend(str(v) for v in _safe_get_list(entry, "imports"))
    text_parts.extend(str(v) for v in _safe_get_list(entry, "exports"))
    text_parts.extend(str(v) for v in _safe_get_list(entry, "tags"))

    tokens = [t for t in tokenize(" ".join(text_parts)) if len(t) >= 3]
    tf: dict[str, int] = {}
    for tok in tokens:
        tf[tok] = tf.get(tok, 0) + 1

    return {
        "path": path,
        "document_id": f"doc:{_stable_hash({'path': path}, size=20)}",
        "source_fingerprint": _document_fingerprint(entry, symbols),
        "language": str(entry.get("language") or ""),
        "roles": _safe_get_list(entry, "roles"),
        "importance": float(entry.get("importance", 0.0) or 0.0),
        "size_bytes": int(entry.get("size_bytes", 0) or 0),
        "file_hash": str(entry.get("file_hash") or ""),
        "content_hash": str(entry.get("content_hash") or ""),
        "symbols": [str(s.get("name") or "") for s in symbols],
        "chunks": _build_chunks(path, symbols),
        "tf": tf,
        "token_count": len(tokens),
        "generic_flags": _generic_file_flags(path, int(entry.get("size_bytes", 0) or 0)),
        "generated": _looks_generated(path),
        "large": int(entry.get("size_bytes", 0) or 0) > LARGE_GENERIC_FILE_THRESHOLD_BYTES,
    }


def build_retrieval_index(
    project_map: Mapping[str, Any],
    *,
    symbol_index: Mapping[str, Any] | None = None,
    call_graph: Mapping[str, Any] | None = None,
    root: str = "",
) -> dict[str, Any]:
    """Build a versioned retrieval index derived from mapper artifacts.

    The index is built during scan/index, not during a query. It stores the
    document frequency table and per-file token statistics so that warm queries
    never reopen or read the body of any source file.
    """
    symbol_index = symbol_index or {}
    call_graph = call_graph or {}

    # Map symbol -> file and file -> symbols.
    symbols_by_file: dict[str, list[dict]] = {}
    for sym in symbol_index.get("symbols", []):
        if not isinstance(sym, Mapping):
            continue
        dfn = str(sym.get("defined_in") or "").replace(os.sep, "/")
        symbols_by_file.setdefault(dfn, []).append(dict(sym))

    # Call-graph edges (callers/callees + imports).
    edges = []
    for key in ("edges", "imports", "calls"):
        for edge in call_graph.get(key, []) or []:
            if isinstance(edge, Mapping) and edge.get("from") and edge.get("to"):
                edges.append((str(edge["from"]).replace(os.sep, "/"), str(edge["to"]).replace(os.sep, "/")))

    return update_retrieval_index(
        None,
        project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        root=root,
    )


def update_retrieval_index(
    previous_index: Mapping[str, Any] | None,
    project_map: Mapping[str, Any],
    *,
    symbol_index: Mapping[str, Any] | None = None,
    call_graph: Mapping[str, Any] | None = None,
    changed_paths: Sequence[str] | None = None,
    root: str = "",
) -> dict[str, Any]:
    """Incrementally rebuild only changed document/chunk state when possible."""
    symbol_index = symbol_index or {}
    call_graph = call_graph or {}
    changed = {_normalized_path(path) for path in (changed_paths or []) if path}

    pm_files: list[Mapping[str, Any]] = sorted(
        (item for item in project_map.get("files", []) if isinstance(item, Mapping)),
        key=lambda item: _normalized_path(str(item.get("path") or "")),
    )

    symbols_by_file: dict[str, list[dict]] = {}
    for sym in symbol_index.get("symbols", []):
        if not isinstance(sym, Mapping):
            continue
        dfn = _normalized_path(str(sym.get("defined_in") or ""))
        symbols_by_file.setdefault(dfn, []).append(dict(sym))

    prev_docs = {}
    if isinstance(previous_index, Mapping) and previous_index.get("schema") == RETRIEVAL_INDEX_SCHEMA:
        prev_docs = {
            _normalized_path(str(doc.get("path") or "")): dict(doc)
            for doc in previous_index.get("documents", [])
            if isinstance(doc, Mapping) and doc.get("path")
        }

    file_docs: list[dict[str, Any]] = []
    reused_paths: list[str] = []
    invalidated_paths: list[str] = []

    for entry in pm_files:
        path = _normalized_path(str(entry.get("path") or ""))
        if not path:
            continue
        symbols = symbols_by_file.get(path, [])
        prev_doc = prev_docs.get(path)
        entry_for_index = dict(entry)
        source_text = _source_text(root, path)
        if source_text and not entry_for_index.get("content_hash"):
            entry_for_index["content_hash"] = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        fingerprint = _document_fingerprint(entry_for_index, symbols)
        if prev_doc and path not in changed and str(prev_doc.get("source_fingerprint") or "") == fingerprint:
            file_docs.append(prev_doc)
            reused_paths.append(path)
            continue
        file_docs.append(_build_document(entry_for_index, symbols, root=root))
        invalidated_paths.append(path)

    file_docs.sort(key=lambda doc: doc["path"])
    live_paths = {doc["path"] for doc in file_docs}
    removed_paths = sorted(set(prev_docs) - live_paths)

    df: dict[str, set[str]] = {}
    for doc in file_docs:
        for tok in doc.get("tf", {}):
            df.setdefault(tok, set()).add(doc["path"])
    df_counts = {tok: len(docset) for tok, docset in sorted(df.items())}
    N = len(file_docs)

    edges = []
    for key in ("edges", "imports", "calls"):
        for edge in call_graph.get(key, []) or []:
            if isinstance(edge, Mapping) and edge.get("from") and edge.get("to"):
                edges.append((_normalized_path(str(edge["from"])), _normalized_path(str(edge["to"]))))

    callees: dict[str, set[str]] = {}
    callers: dict[str, set[str]] = {}
    for src, dst in edges:
        callees.setdefault(src, set()).add(dst)
        callers.setdefault(dst, set()).add(src)

    graph_dependents = set()
    for path in invalidated_paths:
        graph_dependents.update(callees.get(path, set()))
        graph_dependents.update(callers.get(path, set()))
    graph_dependents.difference_update(invalidated_paths)

    related_tests = _related_tests_map(project_map, live_paths)
    root_norm = _normalized_path(root)
    index_payload = {
        "documents": [
            {
                "path": doc["path"],
                "document_id": doc.get("document_id", ""),
                "source_fingerprint": doc.get("source_fingerprint", ""),
                "chunks": [
                    {
                        "chunk_id": chunk.get("chunk_id", ""),
                        "start_line": int(chunk.get("start_line", 0) or 0),
                        "end_line": int(chunk.get("end_line", 0) or 0),
                    }
                    for chunk in doc.get("chunks", [])
                ],
            }
            for doc in file_docs
        ],
        "df": df_counts,
        "call_graph": {
            "callees": {k: sorted(v) for k, v in callees.items()},
            "callers": {k: sorted(v) for k, v in callers.items()},
        },
        "related_tests": related_tests,
        "root": root_norm,
        "rev": BUILDER_REVISION,
    }

    return {
        "schema": RETRIEVAL_INDEX_SCHEMA,
        "version": RETRIEVAL_INDEX_VERSION,
        "builder_revision": BUILDER_REVISION,
        "tokenizer_policy": TOKENIZER_POLICY,
        "document_count": N,
        "document_frequency": df_counts,
        "documents": file_docs,
        "call_graph": index_payload["call_graph"],
        "related_tests": related_tests,
        "root": root_norm,
        "index_id": _stable_hash(index_payload, size=24),
        "incremental": {
            "changed_paths": sorted(changed),
            "invalidated_paths": sorted(set(invalidated_paths)),
            "reused_paths": sorted(reused_paths),
            "removed_paths": removed_paths,
            "graph_dependent_paths": sorted(graph_dependents),
            "reused_document_count": len(reused_paths),
        },
    }


def _related_tests_map(project_map: Mapping[str, Any], paths: set[str]) -> dict[str, list[str]]:
    tests_by_base: dict[str, list[str]] = {}
    for entry in project_map.get("files", []):
        if not isinstance(entry, Mapping):
            continue
        path = str(entry.get("path") or "").replace(os.sep, "/")
        roles = entry.get("roles", []) or []
        if "test" in roles:
            base = os.path.splitext(os.path.basename(path))[0]
            if base:
                tests_by_base.setdefault(base, []).append(path)
    out: dict[str, list[str]] = {}
    for path in paths:
        base = os.path.splitext(os.path.basename(path))[0]
        matches = []
        if base:
            matches = tests_by_base.get(base, [])
        out[path] = sorted(set(matches))
    return out


def write_retrieval_index(root: str, out: str, index: Mapping[str, Any]) -> str:
    """Persist the retrieval index under the artifacts directory."""
    abs_out = os.path.abspath(os.path.join(root, out))
    os.makedirs(abs_out, exist_ok=True)
    path = os.path.join(abs_out, "retrieval-index.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def load_retrieval_index(root: str, out: str = ".simplicio") -> dict | None:
    path = os.path.join(os.path.abspath(os.path.join(root, out)), "retrieval-index.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, Mapping) or data.get("schema") != RETRIEVAL_INDEX_SCHEMA:
        return None
    return dict(data)


# --------------------------------------------------------------------------- #
# Stage C — candidate ranking (discriminative, explainable)
# --------------------------------------------------------------------------- #
def _bm25_score(
    tf: Mapping[str, int],
    query_terms: Sequence[str],
    df_counts: Mapping[str, int],
    document_count: int,
    doc_len: int,
    avg_len: float,
) -> tuple[float, list[str], dict[str, float]]:
    """Deterministic BM25 (Robertson/Sparck-Jones) over the index vocabulary."""
    if document_count <= 0 or not query_terms:
        return 0.0, [], {}
    k1, b = 1.5, 0.75
    score = 0.0
    matched: list[str] = []
    idf_terms: dict[str, float] = {}
    for term in query_terms:
        f = tf.get(term, 0)
        if f == 0:
            continue
        matched.append(term)
        n_t = df_counts.get(term, 0)
        idf = math.log(1 + (document_count - n_t + 0.5) / (n_t + 0.5))
        idf_terms[term] = round(idf, 6)
        denom = f + k1 * (1 - b + b * (doc_len / avg_len if avg_len else 1.0))
        score += idf * (f * (k1 + 1)) / denom
    return score, matched, idf_terms


def _avg_doc_len(index: Mapping[str, Any]) -> float:
    docs = index.get("documents", [])
    if not docs:
        return 1.0
    total = sum(max(1, d.get("token_count", 1) or 1) for d in docs)
    return total / len(docs)


def _graph_distance(index: Mapping[str, Any], src: str, targets: set[str]) -> int | None:
    """BFS hop distance from ``src`` to any target path via call edges."""
    if not targets:
        return None
    if src in targets:
        return 0
    callees = index.get("call_graph", {}).get("callees", {})
    callers = index.get("call_graph", {}).get("callers", {})
    visited = {src}
    frontier = {src}
    dist = 0
    while frontier and dist < 3:
        dist += 1
        nxt: set[str] = set()
        for node in frontier:
            for nb in (*callees.get(node, []), *callers.get(node, [])):
                if nb in targets:
                    return dist
                if nb not in visited:
                    visited.add(nb)
                    nxt.add(nb)
        frontier = nxt
    return None


def rank_candidates(
    index: Mapping[str, Any],
    plan: QueryPlan,
    *,
    recent_paths: set[str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return ranked candidates with explainable score components (Stage C)."""
    recent_paths = recent_paths or set()
    df_counts = index.get("document_frequency", {})
    document_count = max(1, index.get("document_count", 1))
    avg_len = _avg_doc_len(index)
    related_tests = index.get("related_tests", {})

    target_path = plan.target_path
    exact_query_terms = [term.lower() for term in plan.all_terms]

    ranked: list[dict[str, Any]] = []
    for doc in index.get("documents", []):
        path = doc["path"]
        tf = doc.get("tf", {})
        roles = doc.get("roles", []) or []
        generated = bool(doc.get("generated"))
        generic_flags = set(
            doc.get("generic_flags") or _generic_file_flags(path, int(doc.get("size_bytes", 0) or 0))
        )
        large = bool(doc.get("large") or "large" in generic_flags)

        # BM25 over the *discriminative* query terms (domain+symbol+identifiers).
        bm25, bm25_matched, idf_terms = _bm25_score(
            tf,
            exact_query_terms,
            df_counts,
            document_count,
            max(1, doc.get("token_count", 1) or 1),
            avg_len,
        )

        # Exact target / path match (highest weight).
        exact_target = bool(target_path and path == target_path)

        # Symbol / identifier exact name match inside the file (case-insensitive).
        symbols = set(s.lower() for s in doc.get("symbols", []))
        sym_matches = sorted(
            {t.lower() for t in plan.symbol_terms if t.lower() in symbols}
            | {t.lower() for t in plan.exact_identifiers if t.lower() in symbols}
        )

        # Path-term match (directory / filename hint).
        path_tok_set = set(_path_tokens(path))
        path_matches = sorted(set(plan.path_terms) & path_tok_set)

        # Call-graph proximity to any explicitly-targeted / symbol-bearing file.
        graph_targets: set[str] = set()
        if target_path:
            graph_targets.add(target_path)
        for t in plan.symbol_terms:
            for d2 in index.get("documents", []):
                if t.lower() in {s.lower() for s in d2.get("symbols", [])}:
                    graph_targets.add(d2["path"])
        graph_dist = _graph_distance(index, path, graph_targets) if graph_targets else None

        # Affected-test relationship: the candidate's base name has a paired test
        # file (e.g. sort_lines.py <-> test_sort_lines.py) and the task's symbols
        # are among the tested surface.
        related = set(s.lower() for s in plan.symbol_terms) | {i.lower() for i in plan.exact_identifiers}
        paired_tests = related_tests.get(path, [])
        test_matches = sorted(set(t for t in (paired_tests or [])) if (related & symbols) else set())

        matched_terms = sorted(set(bm25_matched) | set(sym_matches) | set(path_matches) | set(test_matches))

        # Relevance requires at least one discriminative match OR an exact target.
        has_relevance = bool(exact_target or matched_terms)
        if not has_relevance:
            continue

        # ---- Feature scoring (deterministic, explainable) ------------------
        components: dict[str, float] = {}
        reason_codes: list[str] = []

        if exact_target:
            components["explicit_target"] = 5.0
            reason_codes.append("explicit_target")
        if sym_matches:
            components["symbol_match"] = 2.0 * len(sym_matches)
            reason_codes.append("symbol_match=" + ",".join(sym_matches))
        if path_matches:
            components["path_match"] = 1.0 * len(path_matches)
            reason_codes.append("path_match=" + ",".join(path_matches))
        if test_matches:
            components["affected_test"] = 1.5 * len(test_matches)
            reason_codes.append("affected_test=" + ",".join(test_matches))
        if bm25 > 0:
            components["bm25"] = round(bm25, 6)
            reason_codes.append("bm25")
        if idf_terms:
            reason_codes.append(
                "idf_terms=" + ",".join(f"{term}:{idf_terms[term]:.3f}" for term in sorted(idf_terms))
            )
        if graph_dist is not None and graph_dist <= 2:
            components["call_graph_proximity"] = max(0.0, 1.5 - 0.5 * graph_dist)
            reason_codes.append(f"call_graph_proximity=dist{graph_dist}")
        if "test" in roles:
            components["role_test"] = 0.5
            reason_codes.append("role_test")
        if matched_terms:
            reason_codes.append("matched_terms=" + ",".join(matched_terms))

        # Recency is ONLY a boost after semantic relevance (never a source).
        recent_boost = bool(matched_terms and path in recent_paths)
        if recent_boost:
            components["recent_change_boost"] = 0.3
            reason_codes.append("relevant_recent_change")

        # Importance micro-boost (<=1% scale, never dominant).
        imp = min(max(float(doc.get("importance", 0.0) or 0.0), 0.0), 1.0)
        components["importance"] = imp * 0.01

        # Penalties for generated/vendor/archive/large generic files unless
        # explicitly targeted.
        penalty = 0.0
        if generated and not exact_target:
            penalty += GENERIC_FILE_PENALTY
            reason_codes.append("generated_or_vendor_penalty")
        if "archive" in generic_flags and not exact_target:
            reason_codes.append("archive_penalty")
        if large and not exact_target:
            penalty += GENERIC_FILE_PENALTY
            reason_codes.append("large_generic_penalty")
        if "docs" in roles and not exact_target and not sym_matches:
            penalty += 0.2
            reason_codes.append("generic_docs_penalty")

        score = round(sum(components.values()) - penalty, 6)
        if score <= 0 and not exact_target:
            # Never surface a penalized, non-target file with zero relevance.
            continue

        ranked.append(
            {
                "path": path,
                "relevance_score": score,
                "score_components": {k: round(v, 6) for k, v in components.items()},
                "idf_terms": idf_terms,
                "reason_codes": reason_codes,
                "matched_terms": matched_terms,
                "symbol_matches": sym_matches,
                "path_matches": path_matches,
                "recent_change_boost": recent_boost,
                "generated": generated,
                "generic_flags": sorted(generic_flags),
                "large": large,
                "language": doc.get("language", ""),
                "roles": roles,
            }
        )

    ranked.sort(key=lambda row: (-row["relevance_score"], row["path"]))
    return ranked[: max(1, limit)]


# --------------------------------------------------------------------------- #
# Stage D — span expansion with stable handles
# --------------------------------------------------------------------------- #
def _read_lines(root: str, path: str) -> tuple[str, list[str]] | None:
    abs_path = path if os.path.isabs(path) else os.path.join(root, path)
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    return text, text.splitlines()


def expand_spans(
    root: str,
    ranked: Sequence[Mapping[str, Any]],
    index: Mapping[str, Any],
    *,
    symbol_index: Mapping[str, Any] | None = None,
    max_spans_per_file: int = 4,
) -> list[dict[str, Any]]:
    """Expand extractive spans for the top candidates (Stage D).

    Returns per-file entries with selected symbol/line ranges, stable
    ``expand_handle`` values for omitted content, and line anchors + hashes.
    """
    symbol_index = symbol_index or {}
    sym_defs: dict[str, list[dict]] = {}
    for sym in symbol_index.get("symbols", []):
        if isinstance(sym, Mapping):
            dfn = str(sym.get("defined_in") or "").replace(os.sep, "/")
            sym_defs.setdefault(dfn, []).append(dict(sym))

    callees = index.get("call_graph", {}).get("callees", {})
    callers = index.get("call_graph", {}).get("callers", {})
    related_tests = index.get("related_tests", {})
    docs_by_path = {
        _normalized_path(str(doc.get("path") or "")): doc
        for doc in index.get("documents", [])
        if isinstance(doc, Mapping) and doc.get("path")
    }

    out: list[dict[str, Any]] = []
    for row in ranked:
        path = row["path"]
        doc = docs_by_path.get(path, {})
        read = _read_lines(root, path)
        if read is None:
            out.append(
                {
                    "path": path,
                    "readable": False,
                    "spans": [],
                    "expand_handle": _expand_handle(root, path, None, kind="full"),
                    "line_count": 0,
                }
            )
            continue
        text, lines = read
        line_count = len(lines)

        # Select ranges around matched symbols (small context window).
        ranges: list[dict[str, Any]] = []
        chosen: set[tuple[int, int]] = set()
        symbol_names = list(row.get("symbol_matches", [])) or list(row.get("matched_terms", []))
        syms_here = sym_defs.get(path, [])
        chunks_here = doc.get("chunks", []) if isinstance(doc, Mapping) else []
        picked = 0
        for sym in syms_here:
            sname = str(sym.get("name") or "").lower()
            if sname not in {s.lower() for s in symbol_names}:
                continue
            line = int(sym.get("line", 0) or 0)
            if line < 1:
                continue
            start = max(1, line - 2)
            end = min(line_count, line + 8)
            key = (start, end)
            if key in chosen:
                continue
            chosen.add(key)
            chunk = "\n".join(lines[start - 1 : end])
            chunk_id = ""
            for chunk_meta in chunks_here:
                if str(chunk_meta.get("symbol") or "").lower() == sname:
                    chunk_id = str(chunk_meta.get("chunk_id") or "")
                    break
            ranges.append(
                {
                    "start_line": start,
                    "end_line": end,
                    "symbol": sym.get("name"),
                    "kind": sym.get("kind"),
                    "chunk_id": chunk_id,
                    "range_hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16],
                }
            )
            picked += 1
            if picked >= max_spans_per_file:
                break

        # Include callers/tests references as context metadata (not re-read).
        context_edges = sorted(set(callees.get(path, [])) | set(callers.get(path, [])))
        tests = related_tests.get(path, [])

        # Stable handle for retrieving the full / adjacent content later.
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        expand_handle = _expand_handle(root, path, content_hash, kind="full")
        omitted_ranges = [
            {
                "kind": "full",
                "start_line": 1,
                "end_line": line_count,
                "expand_handle": expand_handle,
            }
        ]
        for span in ranges:
            if span["start_line"] > 1:
                omitted_ranges.append(
                    {
                        "kind": "before",
                        "start_line": 1,
                        "end_line": span["start_line"] - 1,
                        "expand_handle": _expand_handle(
                            root,
                            path,
                            content_hash,
                            kind="range",
                            start_line=1,
                            end_line=span["start_line"] - 1,
                        ),
                    }
                )
            if span["end_line"] < line_count:
                omitted_ranges.append(
                    {
                        "kind": "after",
                        "start_line": span["end_line"] + 1,
                        "end_line": line_count,
                        "expand_handle": _expand_handle(
                            root,
                            path,
                            content_hash,
                            kind="range",
                            start_line=span["end_line"] + 1,
                            end_line=line_count,
                        ),
                    }
                )

        out.append(
            {
                "path": path,
                "readable": True,
                "line_count": line_count,
                "snapshot_hash": content_hash,
                "spans": ranges,
                "context_edges": context_edges,
                "tests": tests,
                "expand_handle": expand_handle,
                "omitted_ranges": omitted_ranges,
            }
        )
    return out


def _expand_handle(
    root: str,
    path: str,
    content_hash: str | None,
    *,
    kind: str = "full",
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Stable, deterministic handle for retrieving omitted adjacent/full content.

    Format: ``expand:<root-fp>:<norm-path>:<content-hash>:<kind>:<range>``. The content hash
    anchors to a specific revision so downstream never reruns whole-repo mapping
    to resolve it; it can stat the file and re-read the requested block.
    """
    root_fp = hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:16]
    norm = quote(path.replace(os.sep, "/"), safe="/._-")
    ch = content_hash or "none"
    if kind == "range" and start_line is not None and end_line is not None:
        return f"expand:{root_fp}:{norm}:{ch}:range:{start_line}-{end_line}"
    return f"expand:{root_fp}:{norm}:{ch}:{kind}:all"


def fill_full_content_spans(
    root: str,
    ranked: Sequence[Mapping[str, Any]],
    expanded: list[dict[str, Any]],
    fit: dict[str, Any],
    plan: QueryPlan,
) -> int:
    """Attach real, bounded source content to high-relevance targets (issue #308).

    Without this, ``expanded_spans[].spans`` stays empty for any file whose
    only match was lexical/BM25 (no symbol-name hit), leaving downstream
    consumers with only an ``expand_handle`` pointer + ``omitted_ranges`` even
    when the file's whole content would have fit comfortably inside the
    requested token budget. This fills ``spans`` with the same bounded,
    read-only content ``simplicio-mapper preview`` already produces
    (``preview_source``, capped at ``DEFAULT_PREVIEW_LINES``/``DEFAULT_PREVIEW_BYTES``)
    for the top-ranked target and the explicit ``--target`` (when included),
    but only while the remaining token budget after selection/reasoning
    metadata allows it -- otherwise the existing pointer-only behavior is kept.

    Returns the number of tokens consumed by the content that was attached,
    so callers can keep ``estimated_tokens`` honest about what was actually
    delivered, not just what was reasoned about.
    """
    if not expanded or not ranked:
        return 0
    usable = int(fit.get("token_budget", 0)) - int(fit.get("safety_margin_tokens", 0))
    remaining = usable - int(fit.get("estimated_tokens", 0))
    if remaining <= 0:
        return 0
    added_tokens = 0
    from .visualization import preview_source

    for index, (row, entry) in enumerate(zip(ranked, expanded, strict=False)):
        if not entry.get("readable") or entry.get("spans"):
            continue
        is_top_relevance = index == 0
        is_explicit_target = bool(plan.target_path) and row.get("path") == plan.target_path
        if not (is_top_relevance or is_explicit_target):
            continue
        try:
            preview = preview_source(root, path=entry["path"], allow_full_content=False)
        except (OSError, ValueError):
            continue
        content = str(preview.get("content") or "")
        if not content:
            continue
        cost = estimate_tokens(content)
        if cost > remaining:
            continue
        entry["spans"] = [
            {
                "start_line": preview.get("line_start", 1),
                "end_line": preview.get("line_end", entry.get("line_count", 0)),
                "symbol": None,
                "kind": "full_content",
                "chunk_id": "",
                "range_hash": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
                "text": content,
                "truncated": bool(preview.get("truncated", False)),
            }
        ]
        remaining -= cost
        added_tokens += cost
    return added_tokens


def resolve_expand_handle(
    root: str,
    expand_handle: str,
    *,
    max_lines: int | None = None,
) -> dict[str, Any]:
    """Resolve an expansion handle into real file content without rerunning mapping."""
    parts = expand_handle.split(":")
    if len(parts) < 6 or parts[0] != "expand":
        raise ValueError(f"invalid expand handle: {expand_handle}")
    root_fp = parts[1]
    path = unquote(":".join(parts[2:-3]))
    expected_hash, kind, payload = parts[-3:]
    if not path or kind not in {"full", "range"}:
        raise ValueError(f"invalid expand handle: {expand_handle}")
    actual_root_fp = hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:16]
    if root_fp != actual_root_fp:
        raise ValueError("expand handle belongs to a different root")
    read = _read_lines(root, path)
    if read is None:
        raise FileNotFoundError(path)
    text, lines = read
    snapshot_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    stale = expected_hash not in {"", "none", snapshot_hash}

    if kind == "range":
        start_s, end_s = payload.split("-", 1)
        start_line = max(1, int(start_s))
        end_line = min(len(lines), int(end_s))
    else:
        start_line = 1
        end_line = len(lines)

    if max_lines is not None and max_lines > 0:
        end_line = min(end_line, start_line + max_lines - 1)

    snippet = "\n".join(lines[start_line - 1 : end_line]) if lines else ""
    return {
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
        "snapshot_hash": snapshot_hash,
        "stale": stale,
        "text": snippet,
    }


# --------------------------------------------------------------------------- #
# Stage E — token-budget fitting
# --------------------------------------------------------------------------- #
def serialized_json_bytes(payload: Any) -> bytes:
    """Return the canonical bytes that the CLI emits for a JSON payload."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def serialized_token_count(payload: Any) -> int:
    """Measure the exact serialized JSON with the declared BPE tokenizer."""
    return estimate_tokens(serialized_json_bytes(payload).decode("utf-8"))


def fit_token_budget(
    expanded: Sequence[Mapping[str, Any]],
    root: str,
    *,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    plan: QueryPlan | None = None,
) -> dict[str, Any]:
    """Fit the serialized pack to an explicit token budget (Stage E).

    Required target/AC/symbol spans are allocated first; remaining budget is
    shared across dependency/test context. If required spans cannot fit, the
    engine reports ``needs_broader_context=True`` with ``broader_context``
    reason codes instead of silently truncating a load-bearing span.
    """
    plan = plan or QueryPlan()
    required_paths = set()
    if plan.target_path:
        required_paths.add(plan.target_path)

    # Deterministic allocation by layer:
    #   1. required target/spans
    #   2. dependency/caller context
    #   3. tests/evidence
    #   4. safety margin
    SAFETY_MARGIN = int(token_budget * 0.05)
    usable = token_budget - SAFETY_MARGIN

    budgeted: list[dict[str, Any]] = []
    used = 0
    overflow_required: list[str] = []

    # Layer 1: required target spans first.
    for entry in expanded:
        path = entry["path"]
        is_required = bool(path in required_paths) or entry.get("required", False)
        cost = 0
        # Cost = sum of selected span token estimates (read only those spans).
        for span in entry.get("spans", []):
            cost += _span_cost(root, path, span)
        # If no spans selected, estimate a single representative block.
        if cost == 0:
            cost = min(estimate_tokens(_read_head(root, path, 200)), usable)
        if is_required and used + cost > usable:
            overflow_required.append(path)
            continue
        budgeted.append(
            {**entry, "estimated_tokens": cost, "layer": "required" if is_required else "context"}
        )
        used += cost

    # Layer 2/3: context edges + tests metadata (cheap, deterministic).
    for entry in budgeted:
        extra = estimate_tokens(json.dumps(entry.get("context_edges", []), ensure_ascii=False))
        extra += estimate_tokens(json.dumps(entry.get("tests", []), ensure_ascii=False))
        used += extra

    needs_broader = bool(overflow_required)
    broader_context: list[str] = []
    if needs_broader:
        broader_context.append(
            "required spans exceed token budget for: " + ", ".join(sorted(overflow_required))
        )
        broader_context.append(f"next_query: tighten target or raise --token-budget (current={token_budget})")

    return {
        "token_budget": token_budget,
        "tokenizer_policy": TOKENIZER_POLICY,
        "estimated_tokens": used,
        "safety_margin_tokens": SAFETY_MARGIN,
        "budgeted_count": len(budgeted),
        "needs_broader_context": needs_broader,
        "broader_context": broader_context,
        "entries": budgeted,
    }


def _read_head(root: str, path: str, n: int) -> str:
    read = _read_lines(root, path)
    if read is None:
        return ""
    return "\n".join(read[1][:n])


def _span_cost(root: str, path: str, span: Mapping[str, Any]) -> int:
    read = _read_lines(root, path)
    start = int(span.get("start_line", 1) or 1)
    end = int(span.get("end_line", start) or start)
    if start < 1 or end < start:
        return 0
    if read is None:
        # File body not available (e.g. synthetic/declared span): estimate from
        # the declared line range so the budget guard still fires honestly.
        return estimate_tokens("x" * (end - start + 1) * 40)
    lines = read[1]
    end = min(end, len(lines))
    return estimate_tokens("\n".join(lines[start - 1 : end]))


# --------------------------------------------------------------------------- #
# Stage F — fidelity / sufficiency gate
# --------------------------------------------------------------------------- #
def fidelity_gate(
    ranked: Sequence[Mapping[str, Any]],
    expanded: Sequence[Mapping[str, Any]],
    plan: QueryPlan,
    *,
    minimum_query_coverage: float = 0.2,
) -> dict[str, Any]:
    """Multi-dimensional fidelity coverage + honest sufficiency verdict (Stage F)."""
    selected_paths = {row["path"] for row in ranked}
    all_matched = {str(t).lower() for row in ranked for t in row.get("matched_terms", [])}

    # Dimension 1: explicit target preserved.
    target_ok = bool(not plan.target_path or plan.target_path in selected_paths)
    # Dimension 2: exact identifiers preserved.
    id_match = {i.lower() for i in plan.exact_identifiers if i.lower() in all_matched}
    identifier_ratio = (len(id_match) / len(plan.exact_identifiers)) if plan.exact_identifiers else 1.0
    # Dimension 3: AC/RN/NFR ids preserved.
    ac_match = {a.upper() for a in plan.ac_ids if a.lower() in all_matched}
    ac_ratio = (len(ac_match) / len(plan.ac_ids)) if plan.ac_ids else 1.0
    # Dimension 4: discriminative term coverage (BM25-style, not raw file count).
    disc_terms = [t for t in plan.all_terms if t.lower() not in _STOP_WORDS]
    disc_match = {t for t in disc_terms if t.lower() in all_matched}
    coverage_ratio = (len(disc_match) / len(disc_terms)) if disc_terms else 1.0
    # A genuinely discriminative signal must exist (symbol/identifier/AC or a
    # multi-term domain match from indexed source text). A single generic word
    # is not enough, but natural-language tasks without a named symbol still
    # need a truthful route to their load-bearing source spans.
    domain_terms = {t.lower() for t in plan.domain_terms}
    domain_match = {t for t in disc_match if t.lower() in domain_terms}
    non_documentation_route = any(
        not ({str(role).lower() for role in (row.get("roles") or [])} & {"docs", "documentation"})
        for row in ranked
    )
    has_discriminative_signal = bool(
        plan.symbol_terms
        or plan.exact_identifiers
        or ac_match
        or id_match
        or (len(domain_match) >= 2 and non_documentation_route)
    )
    # Dimension 5: verification/test route present when the task is executable.
    has_test_route = any("test" in (r.get("roles") or []) for r in ranked)
    # Dimension 6: stack/layer coverage.
    layers = {r.get("language", "") for r in ranked if r.get("language")}

    # Sufficiency requires genuine discriminative coverage (not generic overlap)
    # and preservation of required identifiers.
    sufficient = (
        coverage_ratio >= minimum_query_coverage
        and identifier_ratio >= 1.0
        and ac_ratio >= 1.0
        and target_ok
        and has_discriminative_signal
    )
    # Negative / no-match corpus: if ranked is empty, abstain.
    abstained = len(ranked) == 0

    dimensions = {
        "target_preserved": target_ok,
        "identifier_coverage_ratio": round(identifier_ratio, 6),
        "ac_coverage_ratio": round(ac_ratio, 6),
        "discriminative_coverage_ratio": round(coverage_ratio, 6),
        "verification_route_present": bool(has_test_route) if (plan.ac_ids or plan.symbol_terms) else None,
        "layer_count": len(layers),
        "has_discriminative_signal": has_discriminative_signal,
        "matched_domain_terms": sorted(domain_match),
    }

    reasons: list[str] = []
    if abstained:
        reasons.append("no_relevant_targets")
    if not target_ok:
        reasons.append(f"target_not_selected:{plan.target_path}")
    if plan.exact_identifiers and identifier_ratio < 1.0:
        missing = sorted(set(plan.exact_identifiers) - id_match)
        reasons.append("missing_identifiers:" + ",".join(missing))
    if plan.ac_ids and ac_ratio < 1.0:
        missing = sorted({a.upper() for a in plan.ac_ids} - ac_match)
        reasons.append("missing_ac_ids:" + ",".join(missing))
    if not has_discriminative_signal and disc_terms and not abstained:
        reasons.append("no_discriminative_signal")
    if coverage_ratio < minimum_query_coverage and not abstained:
        reasons.append(
            f"discriminative_coverage {coverage_ratio:.3f} below minimum {minimum_query_coverage:.3f}"
        )

    return {
        "sufficient": sufficient and not abstained,
        "abstained": abstained,
        "coverage_ratio": round(coverage_ratio, 6),
        "dimensions": dimensions,
        "reasons": reasons,
    }


# --------------------------------------------------------------------------- #
# Orchestration — drop-in replacement for select_context_targets
# --------------------------------------------------------------------------- #
def select_context_targets(
    root: str,
    project_map: Mapping[str, Any],
    *,
    goal: str = "",
    task_intent: Mapping[str, Any] | None = None,
    task_fingerprint: str = "",
    target: str = "",
    limit: int = 8,
    symbol_index: Mapping[str, Any] | None = None,
    call_graph: Mapping[str, Any] | None = None,
    recent_paths: set[str] | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    minimum_query_coverage: float = 0.2,
    retrieval_index: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Indexed, token-budgeted, explainable replacement for the legacy selector.

    Backward compatible: when no retrieval index is supplied it is built from
    ``project_map`` (+ optional ``symbol_index``/``call_graph``). Warm queries
    that pass a prebuilt index never reopen source files.
    """
    abs_root = os.path.abspath(root)
    # Warm task-aware queries consume the index persisted by scan/index. A
    # direct library call without a persisted index gets metadata-only ranking;
    # it must not reopen every candidate body just to answer one query.
    index = retrieval_index or load_retrieval_index(abs_root)
    if index is None:
        index = build_retrieval_index(project_map, symbol_index=symbol_index, call_graph=call_graph, root="")
    plan = build_query_plan(goal, task_intent=task_intent, target=target)
    if not recent_paths:
        recent_paths = _recent_paths(project_map)

    ranked = rank_candidates(index, plan, recent_paths=recent_paths, limit=limit)

    expanded = expand_spans(abs_root, ranked, index, symbol_index=symbol_index)
    fit = fit_token_budget(expanded, abs_root, token_budget=token_budget, plan=plan)
    added_content_tokens = fill_full_content_spans(abs_root, ranked, expanded, fit, plan)
    if added_content_tokens:
        fit["estimated_tokens"] = int(fit["estimated_tokens"]) + added_content_tokens
    fidelity = fidelity_gate(ranked, expanded, plan, minimum_query_coverage=minimum_query_coverage)

    targets = [
        {
            "path": row["path"],
            "relevance_score": row["relevance_score"],
            "relevance_reason": "; ".join(row["reason_codes"]),
            "matched_terms": row["matched_terms"],
            "recent_change_boost": row["recent_change_boost"],
            "score_components": row["score_components"],
            "reason_codes": row["reason_codes"],
        }
        for row in ranked
    ]

    query_terms = plan.all_terms
    matched_union = sorted({t for row in ranked for t in row["matched_terms"]})
    coverage_ratio = (len(matched_union) / len(query_terms)) if query_terms else 0.0

    target_exists = bool(target and os.path.isfile(os.path.join(abs_root, target.replace(os.sep, "/"))))
    if not target:
        target_resolution = {"requested": "", "status": "not_requested", "reason": ""}
    elif not target_exists:
        target_resolution = {
            "requested": target.replace(os.sep, "/"),
            "status": "missing",
            "reason": f"target does not exist: {target.replace(os.sep, '/')}",
        }
    else:
        sel_paths = {row["path"] for row in ranked}
        t = target.replace(os.sep, "/")
        target_resolution = {
            "requested": t,
            "status": "included" if t in sel_paths else "excluded",
            "reason": "explicit target selected" if t in sel_paths else "target excluded by limit",
        }

    needs_broader = bool(
        fidelity["reasons"] or fit["needs_broader_context"] or target_resolution["status"] == "missing"
    )

    return {
        "schema": RETRIEVAL_SELECTION_SCHEMA,
        "query_plan": plan.to_dict(),
        "query_fingerprint": plan.fingerprint(),
        "query_terms": query_terms,
        "targets": targets,
        "expanded_spans": expanded,
        "token_budget_fit": {
            "token_budget": fit["token_budget"],
            "tokenizer_policy": fit["tokenizer_policy"],
            "estimated_tokens": fit["estimated_tokens"],
            "needs_broader_context": fit["needs_broader_context"],
            "broader_context": fit["broader_context"],
        },
        "fidelity": fidelity,
        "coverage": {
            "matched_terms": matched_union,
            "matched_count": len(matched_union),
            "query_term_count": len(query_terms),
            "ratio": round(coverage_ratio, 6),
        },
        "target_resolution": target_resolution,
        "abstained": bool(fidelity["abstained"] or len(ranked) == 0),
        "abstention_reason": "; ".join(fidelity["reasons"]) or ("no_relevant_targets" if not ranked else ""),
        "needs_broader_context": needs_broader,
        "needs_broader_context_reason": "; ".join(fidelity["reasons"] + fit["broader_context"]),
        "metrics": {
            "candidate_count": index.get("document_count", 0),
            "relevant_count": len(ranked),
            "selected_count": len(targets),
            "precision_at_k": 1.0 if targets else 0.0,
            "index_id": index.get("index_id", ""),
        },
    }


def _recent_paths(project_map: Mapping[str, Any]) -> set[str]:
    values = project_map.get("recent_changes") or project_map.get("changed_files") or []
    paths: set[str] = set()
    if not isinstance(values, list):
        return paths
    for value in values:
        path = value.get("path") if isinstance(value, Mapping) else value
        if isinstance(path, str) and path:
            paths.add(path.replace(os.sep, "/"))
    return paths


def task_query_terms(goal: str = "", task_intent: Mapping[str, Any] | None = None) -> list[str]:
    """Backward-compatible helper that mirrors the legacy module's behavior."""
    return build_query_plan(goal, task_intent=task_intent).all_terms


def task_query_fingerprint(
    *,
    goal: str = "",
    task_intent: Mapping[str, Any] | None = None,
    task_fingerprint: str = "",
    target: str = "",
    query_terms: list[str] | None = None,
) -> str:
    """Backward-compatible fingerprint (ignores new weighted fields)."""
    terms = sorted(set(query_terms or task_query_terms(goal, task_intent)))
    identity = {
        "goal": _normalized_text(goal),
        "intent": task_intent or {},
        "task_fingerprint": task_fingerprint.strip(),
        "target": target.replace(os.sep, "/").strip(),
        "terms": terms,
    }
    canonical = json.dumps(identity, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_TOKEN_BUDGET",
    "RETRIEVAL_INDEX_SCHEMA",
    "RETRIEVAL_SELECTION_SCHEMA",
    "QueryPlan",
    "build_query_plan",
    "build_retrieval_index",
    "expand_spans",
    "fidelity_gate",
    "fill_full_content_spans",
    "fit_token_budget",
    "load_retrieval_index",
    "rank_candidates",
    "resolve_expand_handle",
    "serialized_json_bytes",
    "serialized_token_count",
    "select_context_targets",
    "task_query_fingerprint",
    "task_query_terms",
    "update_retrieval_index",
    "write_retrieval_index",
]
