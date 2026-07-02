"""
precedent.py — finds PRECEDENT using the cache (only embeds new blocks).
"""

import glob
import os
import re
import numpy as np
from .cache import EmbeddingCache
from .mapper import rank_precedents

_emb = None


def _embedder():
    global _emb
    if _emb is None:
        from sentence_transformers import SentenceTransformer

        _emb = SentenceTransformer("all-MiniLM-L6-v2")
    return _emb


PATTERNS = {
    "angular": [
        r"\*ngIf",
        r"\[hidden\]",
        r"\[disabled\]",
        r"hasPerm",
        r"ngxPermission",
        r"canActivate",
    ],
    "react": [
        r"&&\s*<",
        r"\?\s*<[A-Z]",
        r"usePermission",
        r"\bcan\(",
        r"hasRole",
        r"<Protected",
    ],
    "dotnet": [
        r"\[Authorize",
        r"HasPermission",
        r"User\.IsInRole",
        r"\[HasPolicy",
        r"RequireClaim",
    ],
}
EXT = {
    "angular": (".html", ".ts"),
    "react": (".tsx", ".jsx", ".ts"),
    "dotnet": (".cs", ".cshtml", ".razor"),
}
SKIP = (
    "node_modules",
    "/.git/",
    "/dist/",
    "/bin/",
    "/obj/",
    "/.angular/",
    "/.simplicio/",
)


def _resolve_stack_key(stack):
    """Map rich project stack labels to the lightweight precedent scanners."""
    key = (stack or "").strip().lower()
    if key in PATTERNS:
        return key
    compact = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    if "angular" in compact:
        return "angular"
    if "react" in compact or "next" in compact or "vite" in compact:
        return "react"
    if (
        "dotnet" in compact
        or "aspnet" in compact
        or "csharp" in compact
        or "blazor" in compact
    ):
        return "dotnet"
    return None


def _embedding_index_enabled():
    return os.getenv("SIMPLICIO_ENABLE_EMBED_INDEX", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def grep_candidates(root, stack, window=1):
    stack_key = _resolve_stack_key(stack)
    if stack_key is None:
        return []
    pats = [re.compile(p) for p in PATTERNS[stack_key]]
    exts = EXT[stack_key]
    cands = []
    for fp in glob.glob(f"{root}/**/*", recursive=True):
        if not os.path.isfile(fp) or not fp.endswith(exts):
            continue
        if any(s in fp for s in SKIP):
            continue
        try:
            lines = open(fp, encoding="utf-8", errors="ignore").read().splitlines()
        except Exception:
            continue
        for i, ln in enumerate(lines):
            if any(p.search(ln) for p in pats):
                block = "\n".join(lines[max(0, i - window) : i + window + 1])
                cands.append({"file": fp, "line": i + 1, "code": block})
    return cands


def index_repo(root, stack, verbose=True):
    """Index: embed ONLY new blocks, persist cache. Returns stats."""
    cache = EmbeddingCache(root)
    cands = grep_candidates(root, stack)
    texts = list({c["code"] for c in cands})  # dedup
    missing = cache.get_missing(texts)
    embedded = 0
    if missing and _embedding_index_enabled():
        vectors = _embedder().encode(missing, show_progress_bar=False)
        cache.add(missing, vectors)
        cache.save()
        embedded = len(missing)
    if verbose:
        print(
            f"[index] candidates={len(cands)} newly_embedded={embedded} "
            f"cache_total={cache.stats()['cached_blocks']}"
        )
    return cache, cands


def build_precedent_block(root, stack, task, k=2):
    indexed = rank_precedents(root, task, stack=stack, k=k)
    if indexed:
        lines = [
            "[PRECEDENT]",
            "Precedents:",
        ]
        for c in indexed:
            rel = c.get("path", "(unknown)")
            line = c.get("line", 1)
            summary = c.get("summary") or c.get("change_type") or "similar code"
            tags = (
                ", ".join(str(t) for t in c.get("tags", [])[:8])
                if isinstance(c.get("tags"), list)
                else ""
            )
            lines.append(f"\n# {rel}:{line} ({summary})")
            if tags:
                lines.append(f"tags: {tags}")
            if c.get("snippet"):
                lines.append(str(c["snippet"])[:1200])
        return "\n".join(lines)

    stack_key = _resolve_stack_key(stack)
    if stack_key is None:
        return (
            "[PRECEDENT]\n"
            f"(no scanner {stack!r})"
        )

    cache, cands = index_repo(root, stack_key, verbose=False)
    if not cands:
        return "[PRECEDENT]\n(no match)"
    texts = [c["code"] for c in cands]
    vc = cache.lookup(texts)  # from cache, no re-embed
    vt = _embedder().encode([task])[0]  # only the task (short)
    for c, v in zip(cands, vc):
        c["score"] = float(np.dot(vt, v) / (np.linalg.norm(vt) * np.linalg.norm(v)))
    seen, out = set(), []
    for c in sorted(cands, key=lambda x: x["score"], reverse=True):
        if c["code"] in seen:
            continue
        seen.add(c["code"])
        out.append(c)
    tops = out[:k]
    lines = [
        "[PRECEDENT]",
        "Similar code:",
    ]
    for c in tops:
        rel = os.path.relpath(c["file"], root)
        lines.append(f"\n# {rel}:{c['line']} (s{c['score']:.2f})")
        lines.append(c["code"])
    return "\n".join(lines)
