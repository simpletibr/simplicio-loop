#!/usr/bin/env python3
"""simplicio_rag — minimal, honest retrieval (RAG) layer over the CCR memory store.

Stdlib-only. This is the deterministic, **keyword / TF-IDF cosine** answer to the
"RAG" gap. It is explicitly **NOT** embedding- or vector-database-based: there is
no neural model, no semantic similarity, no approximate-nearest-neighbour index.
It tokenizes text into lowercased word characters, drops a small stopword set,
weighs terms by TF-IDF, and ranks documents by cosine similarity against the
query's TF-IDF vector. Honest scope: it retrieves on lexical overlap, so a query
phrased with different words than the stored doc will not match the way an
embedding model would. What it gives you is a real, working, reproducible
relevance ranking with zero dependencies.

It reads the Simplicio CCR memory store at ``$SIMPLICIO_HOME/memory.json``
(default ``~/.simplicio-loop/memory.json``). The plaintext values are obtained through
``simplicio_memory.recall`` / ``simplicio_memory.list_keys`` (which transparently
decompress the zlib+base64 blobs). If that import fails for any reason, it falls
back to reading the raw JSON store directly and using any string values it finds.

API
---
- ``index(docs)``    -> build a TF-IDF index over ``{key: text}``.
- ``search(query, index, top_k=5)`` -> ``[(key, score, snippet), ...]``.
- ``retrieve(query, top_k=5)`` -> load store, index, search; convenience.

CLI
---
    python3 simplicio_rag.py "<query>" [--top 5] [--json]
    python3 simplicio_rag.py remember <key> <text>
"""

import argparse
import json
import math
import os
import re
import sys
from collections import Counter

# Small, intentionally minimal stopword set. Kept short on purpose: aggressive
# stopword removal hurts short technical docs more than it helps.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "do", "does",
        "for", "from", "how", "i", "if", "in", "into", "is", "it", "its", "of",
        "on", "or", "that", "the", "their", "then", "there", "these", "they",
        "this", "to", "was", "were", "what", "when", "where", "which", "who",
        "will", "with", "you", "your",
    }
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def tokenize(text):
    """Lowercase, split on word characters, drop stopwords and 1-char tokens."""
    return [
        tok
        for tok in _WORD_RE.findall(str(text).lower())
        if tok not in STOPWORDS and len(tok) > 1
    ]


def index(docs):
    """Build a TF-IDF index over ``docs`` ({key: text}).

    Returns a dict with:
      - ``docs``: original {key: text}
      - ``idf``: {term: inverse-document-frequency}
      - ``tf``: {key: Counter(term -> count)}
      - ``vectors``: {key: {term -> tfidf weight}}
      - ``norms``: {key: L2 norm of the tfidf vector}
    """
    docs = {str(k): str(v) for k, v in dict(docs).items()}
    tf = {key: Counter(tokenize(text)) for key, text in docs.items()}
    n_docs = len(docs)

    df = Counter()
    for counts in tf.values():
        for term in counts:
            df[term] += 1

    # Smoothed idf: ln((1 + N) / (1 + df)) + 1, always positive.
    idf = {
        term: math.log((1 + n_docs) / (1 + d)) + 1.0
        for term, d in df.items()
    }

    vectors = {}
    norms = {}
    for key, counts in tf.items():
        vec = {term: count * idf.get(term, 0.0) for term, count in counts.items()}
        vectors[key] = vec
        norms[key] = math.sqrt(sum(w * w for w in vec.values()))

    return {
        "docs": docs,
        "idf": idf,
        "tf": tf,
        "vectors": vectors,
        "norms": norms,
    }


def _query_vector(query, idx):
    """TF-IDF vector for the query, using the index's idf (0 for unseen terms)."""
    counts = Counter(tokenize(query))
    idf = idx["idf"]
    return {term: count * idf.get(term, 0.0) for term, count in counts.items()}


def _cosine(qvec, qnorm, dvec, dnorm):
    """Cosine similarity between two sparse {term: weight} vectors."""
    if qnorm == 0.0 or dnorm == 0.0:
        return 0.0
    # Iterate the smaller vector for the dot product.
    if len(qvec) > len(dvec):
        qvec, dvec = dvec, qvec
    dot = 0.0
    for term, w in qvec.items():
        other = dvec.get(term)
        if other is not None:
            dot += w * other
    return dot / (qnorm * dnorm)


def _snippet(text, query_terms, max_chars=240):
    """Return the highest-scoring ~1-2 sentences/lines containing query terms."""
    text = str(text).strip()
    if not text:
        return ""
    qset = set(query_terms)
    fragments = [f.strip() for f in _SENT_SPLIT_RE.split(text) if f.strip()]
    if not fragments:
        fragments = [text]

    best_i = 0
    best_score = -1
    for i, frag in enumerate(fragments):
        frag_terms = set(tokenize(frag))
        score = len(frag_terms & qset)
        if score > best_score:
            best_score = score
            best_i = i

    # Stitch the best fragment with a neighbour to give ~2 lines of context.
    chosen = [fragments[best_i]]
    if best_i + 1 < len(fragments) and len(chosen[0]) < max_chars // 2:
        chosen.append(fragments[best_i + 1])
    snippet = " ".join(chosen)
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 1].rstrip() + "…"
    return snippet


def search(query, idx, top_k=5):
    """Rank docs in ``idx`` by cosine TF-IDF similarity to ``query``.

    Returns ``[(key, score, snippet), ...]`` for the top_k docs with score > 0,
    sorted by descending score (ties broken by key for determinism).
    """
    if not idx or not idx.get("docs"):
        return []
    qvec = _query_vector(query, idx)
    qnorm = math.sqrt(sum(w * w for w in qvec.values()))
    if qnorm == 0.0:
        return []

    query_terms = list(qvec.keys())
    scored = []
    for key in idx["docs"]:
        score = _cosine(qvec, qnorm, idx["vectors"][key], idx["norms"][key])
        if score > 0.0:
            snippet = _snippet(idx["docs"][key], query_terms)
            scored.append((key, score, snippet))

    scored.sort(key=lambda r: (-r[1], r[0]))
    return scored[: max(0, int(top_k))]


def load_memories():
    """Load all plaintext memories from the live store as ``{key: text}``.

    Primary path: ``simplicio_memory.list_keys`` + ``recall`` (decompresses the
    zlib+base64 blobs). Fallback: read the raw JSON store and keep any string
    values directly.
    """
    try:
        import simplicio_memory  # noqa: PLC0415 — intentional lazy import for fallback

        docs = {}
        for key in simplicio_memory.list_keys():
            val = simplicio_memory.recall(key)
            if isinstance(val, str):
                docs[key] = val
        return docs
    except Exception:
        return _load_memories_raw()


def _load_memories_raw():
    """Fallback: read the raw JSON store; keep string values as-is."""
    home = os.path.expanduser("~")
    data_dir = os.environ.get("SIMPLICIO_HOME", os.path.join(home, ".simplicio-loop"))
    store_path = os.path.join(data_dir, "memory.json")
    try:
        with open(store_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    docs = {}
    for key, entry in data.items():
        if isinstance(entry, str):
            docs[str(key)] = entry
        elif isinstance(entry, dict) and isinstance(entry.get("value"), str):
            docs[str(key)] = entry["value"]
    return docs


def retrieve(query, top_k=5):
    """Convenience: load the live store, index it, search, return results."""
    docs = load_memories()
    idx = index(docs)
    return search(query, idx, top_k=top_k)


def _remember(key, text):
    """Store ``text`` under ``key`` via simplicio_memory (populate the store)."""
    try:
        import simplicio_memory  # noqa: PLC0415

        simplicio_memory.remember(key, text)
        return True
    except Exception as exc:  # pragma: no cover — surfaced to CLI
        print(f"error: could not store via simplicio_memory: {exc}", file=sys.stderr)
        return False


def _cli(argv):
    if argv and argv[0] == "remember":
        if len(argv) < 3:
            print("usage: simplicio_rag.py remember <key> <text>", file=sys.stderr)
            return 2
        key = argv[1]
        text = " ".join(argv[2:])
        ok = _remember(key, text)
        if ok:
            print(f"remembered {key} ({len(text.encode('utf-8'))} bytes)")
        return 0 if ok else 1

    parser = argparse.ArgumentParser(
        prog="simplicio_rag.py",
        description="Honest TF-IDF cosine retrieval over the Simplicio CCR memory store.",
    )
    parser.add_argument("query", help="the search query")
    parser.add_argument("--top", type=int, default=5, help="number of results (default 5)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    results = retrieve(args.query, top_k=args.top)

    if args.json:
        payload = [
            {"key": key, "score": round(score, 6), "snippet": snippet}
            for key, score, snippet in results
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not results:
        print("no memories indexed" if not load_memories() else "no matches")
        return 0

    for rank, (key, score, snippet) in enumerate(results, 1):
        print(f"{rank}. {key}  (score {score:.4f})")
        if snippet:
            print(f"   {snippet}")
    return 0


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print('usage: simplicio_rag.py "<query>" [--top 5] [--json]', file=sys.stderr)
        print("       simplicio_rag.py remember <key> <text>", file=sys.stderr)
        return 2
    return _cli(argv)


if __name__ == "__main__":
    sys.exit(main())
