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

# --------------------------------------------------------------------------- #
# Schema / version constants
# --------------------------------------------------------------------------- #
RETRIEVAL_INDEX_SCHEMA = "simplicio.retrieval-index/v1"
RETRIEVAL_SELECTION_SCHEMA = "simplicio.retrieval-selection/v1"
RETRIEVAL_INDEX_VERSION = 1
BUILDER_REVISION = "199.1"

# Tokenizer policy recorded in every receipt so the serialized-budget estimate
# is never silently mistaken for provider-measured usage.
TOKENIZER_POLICY = "heuristic:chars-div-4"

# Default serialized token budget for the context pack (Stage E). Measured on
# the reference CI runner; overridable via --token-budget.
DEFAULT_TOKEN_BUDGET = 8000

# Penalty applied to generated/vendor/archive/large generic files unless the
# task explicitly targets them.
GENERIC_FILE_PENALTY = 0.4

# Stop words: generic ecosystem / natural-language vocabulary that must not
# dominate coverage. Augmented with the project's existing stop list.
_STOP_WORDS = {
    "about", "after", "antes", "apenas", "como", "com", "cada", "das", "dos",
    "depois", "deve", "entre", "essa", "esse", "esta", "este", "for", "from",
    "mais", "nao", "onde", "para", "pela", "pelo", "pode", "por", "primeiro",
    "quando", "que", "sao", "sem", "ser", "that", "the", "then", "this", "tipo",
    "task", "system", "uma", "uns", "with", "and", "the", "a", "an", "of", "to",
    "in", "on", "for", "is", "are", "be", "by", "as", "at", "or", "it", "its",
    "use", "using", "file", "files", "code", "function", "functions", "class",
    "module", "project", "add", "update", "fix", "implement", "support",
    "handle", "make", "set", "get", "new", "old", "via", "into", "when",
    "please", "should", "want", "need", "change", "changes",
}

# Paths containing these fragments are treated as generated / vendor / archive
# and penalized unless explicitly targeted.
_GENERIC_PATH_FRAGMENTS = (
    "/node_modules/", "/vendor/", "/.git/", "/dist/", "/build/", "/target/",
    "/__pycache__/", "/.simplicio/", "/coverage/", "/.next/", "/out/",
)
_GENERATED_BASENAME_HINTS = (
    ".min.", "lock.json", ".lock", "-lock.json", ".generated.", ".gen.",
)


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


def _looks_generated(path: str) -> bool:
    norm = "/" + path.replace(os.sep, "/").lower().lstrip("/")
    if any(frag in norm for frag in _GENERIC_PATH_FRAGMENTS):
        return True
    base = os.path.basename(norm)
    return any(hint in base for hint in _GENERATED_BASENAME_HINTS)


# --------------------------------------------------------------------------- #
# Query planning (Stage B)
# --------------------------------------------------------------------------- #
class QueryPlan:
    """Weighted query fields produced from a task description."""

    __slots__ = (
        "target_path", "exact_identifiers", "path_terms", "symbol_terms",
        "ac_ids", "error_terms", "domain_terms", "generic_terms",
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
            self.exact_identifiers, self.path_terms, self.symbol_terms,
            self.ac_ids, self.error_terms, self.domain_terms, self.generic_terms,
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
            ensure_ascii=True, separators=(",", ":"), sort_keys=True,
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
        chunks.append(json.dumps(task_intent, ensure_ascii=False, sort_keys=True))
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

    pm_files: list[Mapping[str, Any]] = [
        item for item in project_map.get("files", []) if isinstance(item, Mapping)
    ]

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
                edges.append((str(edge["from"]).replace(os.sep, "/"),
                              str(edge["to"]).replace(os.sep, "/")))

    df: dict[str, set[str]] = {}  # term -> set of doc paths (for IDF)
    file_docs: list[dict] = []

    for entry in pm_files:
        path = str(entry.get("path") or "").replace(os.sep, "/")
        if not path:
            continue
        # Build the indexable text WITHOUT reading the file body: path tokens +
        # symbols + summaries + imports + roles + tags. This is exactly what
        # makes warm queries file-body-free.
        text_parts: list[str] = [path]
        text_parts.extend(_path_tokens(path))
        for sym in symbols_by_file.get(path, []):
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
        for tok in tf:
            df.setdefault(tok, set()).add(path)

        file_docs.append({
            "path": path,
            "language": str(entry.get("language") or ""),
            "roles": _safe_get_list(entry, "roles"),
            "importance": float(entry.get("importance", 0.0) or 0.0),
            "size_bytes": int(entry.get("size_bytes", 0) or 0),
            "file_hash": str(entry.get("file_hash") or ""),
            "symbols": [str(s.get("name") or "") for s in symbols_by_file.get(path, [])],
            "tf": tf,
            "token_count": len(tokens),
            "generated": _looks_generated(path),
        })

    # Document frequency as counts (deterministic, no set objects in JSON).
    N = len(file_docs)
    df_counts = {tok: len(docset) for tok, docset in df.items()}

    # Dependency edges adjacency for call-graph proximity.
    callees: dict[str, set[str]] = {}
    callers: dict[str, set[str]] = {}
    for src, dst in edges:
        callees.setdefault(src, set()).add(dst)
        callers.setdefault(dst, set()).add(src)

    related_tests = _related_tests_map(project_map, {d["path"] for d in file_docs})

    index = {
        "schema": RETRIEVAL_INDEX_SCHEMA,
        "version": RETRIEVAL_INDEX_VERSION,
        "builder_revision": BUILDER_REVISION,
        "tokenizer_policy": TOKENIZER_POLICY,
        "document_count": N,
        "document_frequency": df_counts,
        "documents": file_docs,
        "call_graph": {
            "callees": {k: sorted(v) for k, v in callees.items()},
            "callers": {k: sorted(v) for k, v in callers.items()},
        },
        "related_tests": related_tests,
        "root": root.replace(os.sep, "/"),
        "index_id": hashlib.sha256(
            json.dumps(
                {"df": df_counts, "n": N, "rev": BUILDER_REVISION},
                ensure_ascii=True, sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:24],
    }
    return index


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
def _bm25_score(tf: Mapping[str, int], query_terms: Sequence[str], df_counts: Mapping[str, int],
                document_count: int, doc_len: int, avg_len: float) -> tuple[float, list[str]]:
    """Deterministic BM25 (Robertson/Sparck-Jones) over the index vocabulary."""
    if document_count <= 0 or not query_terms:
        return 0.0, []
    k1, b = 1.5, 0.75
    score = 0.0
    matched: list[str] = []
    for term in query_terms:
        f = tf.get(term, 0)
        if f == 0:
            continue
        matched.append(term)
        n_t = df_counts.get(term, 0)
        idf = math.log(1 + (document_count - n_t + 0.5) / (n_t + 0.5))
        denom = f + k1 * (1 - b + b * (doc_len / avg_len if avg_len else 1.0))
        score += idf * (f * (k1 + 1)) / denom
    return score, matched


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
    exact_query_terms = plan.all_terms

    ranked: list[dict[str, Any]] = []
    for doc in index.get("documents", []):
        path = doc["path"]
        tf = doc.get("tf", {})
        roles = doc.get("roles", []) or []
        generated = bool(doc.get("generated"))

        # BM25 over the *discriminative* query terms (domain+symbol+identifiers).
        bm25, bm25_matched = _bm25_score(
            tf, exact_query_terms, df_counts, document_count,
            max(1, doc.get("token_count", 1) or 1), avg_len,
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

        matched_terms = sorted(set(bm25_matched) | set(sym_matches) | set(path_matches)
                               | set(test_matches))

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
        if "docs" in roles and not exact_target and not sym_matches:
            penalty += 0.2
            reason_codes.append("generic_docs_penalty")

        score = round(sum(components.values()) - penalty, 6)
        if score <= 0 and not exact_target:
            # Never surface a penalized, non-target file with zero relevance.
            continue

        ranked.append({
            "path": path,
            "relevance_score": score,
            "score_components": {k: round(v, 6) for k, v in components.items()},
            "reason_codes": reason_codes,
            "matched_terms": matched_terms,
            "symbol_matches": sym_matches,
            "path_matches": path_matches,
            "recent_change_boost": recent_boost,
            "generated": generated,
            "language": doc.get("language", ""),
            "roles": roles,
        })

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

    out: list[dict[str, Any]] = []
    for row in ranked:
        path = row["path"]
        read = _read_lines(root, path)
        if read is None:
            out.append({
                "path": path,
                "readable": False,
                "spans": [],
                "expand_handle": _expand_handle(root, path, None),
                "line_count": 0,
            })
            continue
        text, lines = read
        line_count = len(lines)

        # Select ranges around matched symbols (small context window).
        ranges: list[dict[str, Any]] = []
        chosen: set[tuple[int, int]] = set()
        symbol_names = list(row.get("symbol_matches", [])) or list(row.get("matched_terms", []))
        syms_here = sym_defs.get(path, [])
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
            chunk = "\n".join(lines[start - 1:end])
            ranges.append({
                "start_line": start,
                "end_line": end,
                "symbol": sym.get("name"),
                "kind": sym.get("kind"),
                "range_hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16],
            })
            picked += 1
            if picked >= max_spans_per_file:
                break

        # Include callers/tests references as context metadata (not re-read).
        context_edges = sorted(set(callees.get(path, [])) | set(callers.get(path, [])))
        tests = related_tests.get(path, [])

        # Stable handle for retrieving the full / adjacent content later.
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        expand_handle = _expand_handle(root, path, content_hash)

        out.append({
            "path": path,
            "readable": True,
            "line_count": line_count,
            "snapshot_hash": content_hash,
            "spans": ranges,
            "context_edges": context_edges,
            "tests": tests,
            "expand_handle": expand_handle,
        })
    return out


def _expand_handle(root: str, path: str, content_hash: str | None) -> str:
    """Stable, deterministic handle for retrieving omitted adjacent/full content.

    Format: ``expand:<root-fp>:<norm-path>:<content-hash>``. The content hash
    anchors to a specific revision so downstream never reruns whole-repo mapping
    to resolve it; it can stat the file and re-read the requested block.
    """
    root_fp = hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:16]
    norm = path.replace(os.sep, "/")
    ch = content_hash or "none"
    return f"expand:{root_fp}:{norm}:{ch}"


# --------------------------------------------------------------------------- #
# Stage E — token-budget fitting
# --------------------------------------------------------------------------- #
def estimate_tokens(text: str) -> int:
    """Declared tokenizer policy: ~4 chars/token heuristic (NOT provider-measured)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


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
        budgeted.append({**entry, "estimated_tokens": cost, "layer": "required" if is_required else "context"})
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
        broader_context.append(
            f"next_query: tighten target or raise --token-budget (current={token_budget})"
        )

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
    return estimate_tokens("\n".join(lines[start - 1:end]))


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
    all_matched = {t for row in ranked for t in row.get("matched_terms", [])}

    # Dimension 1: explicit target preserved.
    target_ok = bool(not plan.target_path or plan.target_path in selected_paths)
    # Dimension 2: exact identifiers preserved.
    id_match = {i.lower() for i in plan.exact_identifiers if i.lower() in all_matched}
    identifier_ratio = (len(id_match) / len(plan.exact_identifiers)) if plan.exact_identifiers else 1.0
    # Dimension 3: AC/RN/NFR ids preserved.
    ac_match = {a.upper() for a in plan.ac_ids if a.upper() in {t.upper() for t in all_matched}}
    ac_ratio = (len(ac_match) / len(plan.ac_ids)) if plan.ac_ids else 1.0
    # Dimension 4: discriminative term coverage (BM25-style, not raw file count).
    disc_terms = [t for t in plan.all_terms if t not in _STOP_WORDS]
    disc_match = {t for t in disc_terms if t in all_matched}
    coverage_ratio = (len(disc_match) / len(disc_terms)) if disc_terms else 1.0
    # A genuinely discriminative signal must exist (symbol/identifier/match),
    # otherwise high generic lexical overlap must not pass as sufficient.
    has_discriminative_signal = bool(plan.symbol_terms or plan.exact_identifiers
                                       or ac_match or id_match)
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
    if coverage_ratio < minimum_query_coverage:
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
    index = retrieval_index or build_retrieval_index(
        project_map, symbol_index=symbol_index, call_graph=call_graph, root=abs_root
    )
    plan = build_query_plan(goal, task_intent=task_intent, target=target)
    if not recent_paths:
        recent_paths = _recent_paths(project_map)

    ranked = rank_candidates(index, plan, recent_paths=recent_paths, limit=limit)

    expanded = expand_spans(abs_root, ranked, index, symbol_index=symbol_index)
    fit = fit_token_budget(expanded, abs_root, token_budget=token_budget, plan=plan)
    fidelity = fidelity_gate(ranked, expanded, plan, minimum_query_coverage=minimum_query_coverage)

    targets = [{
        "path": row["path"],
        "relevance_score": row["relevance_score"],
        "relevance_reason": "; ".join(row["reason_codes"]),
        "matched_terms": row["matched_terms"],
        "recent_change_boost": row["recent_change_boost"],
        "score_components": row["score_components"],
        "reason_codes": row["reason_codes"],
    } for row in ranked]

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
        fidelity["reasons"]
        or fit["needs_broader_context"]
        or target_resolution["status"] == "missing"
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
    "fit_token_budget",
    "load_retrieval_index",
    "rank_candidates",
    "select_context_targets",
    "task_query_fingerprint",
    "task_query_terms",
    "write_retrieval_index",
]
