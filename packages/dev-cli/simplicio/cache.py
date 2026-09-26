"""
cache.py — embedding cache keyed by content HASH.

Why hash, not file: if a code block didn't change, the hash is the same ->
reuse the vector. File changes but the relevant snippet didn't? Still a
cache hit. Snippet changes -> new hash -> only that one is re-embedded. Granular.

Persisted in .simplicio-loop/emb_cache.npz (vectors) + .json (hash->row index).
"""

import hashlib
import json
import os

import numpy as np


class EmbeddingCacheMissError(KeyError):
    """Raised by EmbeddingCache.lookup() when one or more texts have no cached
    vector yet (e.g. embedding indexing was skipped/disabled). Callers should
    check whether indexing is enabled before calling lookup(); this exists as
    a defensive guard so a miss surfaces as a clear, actionable error instead
    of a raw KeyError on an opaque hash string."""


class EmbeddingCache:
    def __init__(self, root):
        self.dir = os.path.join(root, ".simplicio-loop")
        os.makedirs(self.dir, exist_ok=True)
        self.vec_path = os.path.join(self.dir, "emb_cache.npz")
        self.idx_path = os.path.join(self.dir, "emb_index.json")
        self.index = {}  # hash -> row position in the matrix
        self.vectors = None  # np.ndarray [N, dim]
        self._load()

    @staticmethod
    def h(text):
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def _load(self):
        if os.path.exists(self.idx_path) and os.path.exists(self.vec_path):
            self.index = json.load(open(self.idx_path))
            self.vectors = np.load(self.vec_path)["v"]

    def save(self):
        json.dump(self.index, open(self.idx_path, "w"))
        if self.vectors is not None:
            np.savez_compressed(self.vec_path, v=self.vectors)

    def get_missing(self, texts):
        """Returns the texts NOT in the cache (need embedding)."""
        return [t for t in texts if self.h(t) not in self.index]

    def add(self, texts, vectors):
        """Adds new texts+vectors to the cache."""
        if not texts:
            return
        vectors = np.asarray(vectors)
        base = 0 if self.vectors is None else self.vectors.shape[0]
        self.vectors = vectors if self.vectors is None else np.vstack([self.vectors, vectors])
        for i, t in enumerate(texts):
            self.index[self.h(t)] = base + i

    def lookup(self, texts):
        """Returns a matrix of vectors in the texts' order (all already cached).

        Raises EmbeddingCacheMissError (a KeyError subclass) instead of a raw
        KeyError when a text's hash isn't cached yet, so callers get an
        actionable message instead of an opaque hash lookup failure.
        """
        missing = [t for t in texts if self.h(t) not in self.index]
        if missing:
            raise EmbeddingCacheMissError(
                f"{len(missing)} of {len(texts)} text block(s) are not in the "
                "embedding cache yet. This usually means embedding indexing "
                "was skipped (SIMPLICIO_ENABLE_EMBED_INDEX not set) or the "
                "cache is stale. Enable indexing and re-run index_repo(), or "
                "avoid calling lookup() when indexing is disabled."
            )
        rows = [self.index[self.h(t)] for t in texts]
        return self.vectors[rows]

    def stats(self):
        return {
            "cached_blocks": len(self.index),
            "dim": 0 if self.vectors is None else int(self.vectors.shape[1]),
        }
