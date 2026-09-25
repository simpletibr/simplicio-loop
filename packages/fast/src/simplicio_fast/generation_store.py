"""Immutable Fast generations with isolated overlays, pins, fences and safe GC."""

from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import time
from pathlib import Path
from typing import Mapping

SCHEMA = "simplicio.fast-generation/v1"


def _sha(data):
    return hashlib.sha256(
        data
        if isinstance(data, bytes)
        else json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class GenerationError(RuntimeError):
    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class Generation:
    id: str
    repo: str
    commit: str
    config_hash: str
    parser_hash: str
    base: Mapping[str, bytes]


class GenerationStore:
    def __init__(self, root):
        self.root = Path(root)
        self.generations = {}
        self.overlays = {}
        self.pins = {}
        self.fences = {}

    def create(self, repo, commit, config_hash, parser_hash, files):
        manifest = {k: _sha(v) for k, v in sorted(files.items())}
        gid = _sha(
            {
                "schema": SCHEMA,
                "repo": repo,
                "commit": commit,
                "config": config_hash,
                "parser": parser_hash,
                "manifest": manifest,
            }
        )
        existing = self.generations.get(gid)
        candidate = Generation(gid, repo, commit, config_hash, parser_hash, dict(files))
        if existing and existing != candidate:
            raise GenerationError("generation_corrupt")
        self.generations[gid] = candidate
        return candidate

    def pin(self, gid, attempt, fence, ttl=60):
        if gid not in self.generations:
            raise GenerationError("generation_missing")
        current = self.fences.get((gid, attempt))
        if current and current != fence:
            raise GenerationError("fence_stale")
        self.fences[(gid, attempt)] = fence
        self.pins[(gid, attempt, fence)] = time.monotonic() + min(ttl, 3600)

    def write(self, gid, slot, fence, path, data):
        if not any(
            k[0] == gid and k[2] == fence and until > time.monotonic()
            for k, until in self.pins.items()
        ):
            raise GenerationError("pin_stale")
        if path.startswith("/") or ".." in Path(path).parts:
            raise GenerationError("overlay_escape")
        self.overlays.setdefault((gid, slot, fence), {})[path] = data

    def tombstone(self, gid, slot, fence, path):
        self.write(gid, slot, fence, path, None)

    def read(self, gid, slot, fence, path):
        generation = self.generations[gid]
        overlay = self.overlays.get((gid, slot, fence), {})
        if path in overlay:
            return overlay[path]
        return generation.base.get(path)

    def gc(self, dry_run=True):
        now = time.monotonic()
        protected = {g for (g, _, _), until in self.pins.items() if until > now}
        removable = sorted(set(self.generations) - protected)
        if not dry_run:
            for gid in removable:
                self.generations.pop(gid)
                self.overlays = {k: v for k, v in self.overlays.items() if k[0] != gid}
        return removable
