"""Disk budget of the central map: one base plus one overlay per worktree (#1672, part of #1574).

Measured with `scripts/benchmark_central_map.py --files 1500 --worktrees 4 --funcs 15 --edits 3`: an
overlay holds 0.32 of the bytes of a full index of the same worktree, and base + overlays hold 0.41 of
one full index per worktree. The limits below keep a margin over those numbers. Each worktree gets a
full index first (its own cache, so it cannot touch the central base), then the overlay alone.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.central_overlay import apply_overlay  # noqa: E402
from simplicio_mapper.mapper.emit import write_mapping_artifacts  # noqa: E402

CACHE_ENV = "SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"
OVERLAY_SHARE = 0.50  # overlay bytes / full-index bytes of the same worktree (measured 0.32)
TOTAL_SHARE = 0.60  # (base + every overlay) / (one full index per worktree) (measured 0.41)
HEAVY = ("call-graph.json", "retrieval-index.json")
WORKTREES = 3
EDITS = 2
# Timings in overlay metadata may change length by a few bytes; a duplicated artifact is kilobytes.
REWRITE_SLACK_BYTES = 256

PY = (
    "from pkg.mod{dep} import helper_{dep}\n\n\n"
    "def helper_{i}(x):\n    return x + {i}\n\n\n"
    "def func_{i}_a(x):\n    return helper_{dep}(x) + helper_{i}(x)\n\n\n"
    "class Thing{i}:\n    def method_{i}(self):\n        return func_{i}_a({i})\n"
)


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(path: Path, files: int = 60) -> list[str]:
    path.mkdir(parents=True)
    _git(["init", "-q", "--initial-branch", "main"], path)
    _git(["config", "user.email", "t@example.com"], path)
    _git(["config", "user.name", "T"], path)
    rels = []
    for i in range(files):
        rel = f"pkg/mod{i}.py"
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(PY.format(i=i, dep=(i * 7 + 3) % files), encoding="utf-8")
        rels.append(rel)
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "base"], path)
    return rels


def dir_bytes(path: str | Path) -> int:
    total = 0
    for dirpath, _dirs, names in os.walk(str(path)):
        for name in names:
            total += os.lstat(os.path.join(dirpath, name)).st_size
    return total


def file_set(*roots: str | Path) -> list[str]:
    out = []
    for root in roots:
        for dirpath, _dirs, names in os.walk(str(root)):
            out.extend(os.path.join(dirpath, name) for name in names)
    return sorted(out)


def budget_violations(cache: str, full_bytes: dict[str, int], states: dict[str, Path]) -> list[str]:
    """Every way the measured disk use breaks the budget; empty when it holds."""
    out = []
    bases = os.listdir(os.path.join(cache, "canonical"))
    if len(bases) != 1:
        out.append(f"{len(bases)} central bases, expected exactly 1: {sorted(bases)}")
    total = dir_bytes(cache)
    for name, state in states.items():
        size = dir_bytes(state)
        total += size
        share = size / full_bytes[name]
        if share > OVERLAY_SHARE:
            out.append(f"overlay {name}: {size} bytes = {share:.2f} of the full index ({full_bytes[name]})")
        for heavy in HEAVY:
            if (state / heavy).exists():
                out.append(f"overlay {name} holds {heavy}")
    full_total = sum(full_bytes.values())
    if total > TOTAL_SHARE * full_total:
        out.append(f"base + overlays: {total} bytes = {total / full_total:.2f} of {full_total}")
    return out


class DiskBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.main = self.base / "main"
        self.rels = make_repo(self.main)
        self.cache = str(self.base / "cache")
        os.environ[CACHE_ENV] = self.cache
        self.addCleanup(os.environ.pop, CACHE_ENV, None)
        self.full_bytes: dict[str, int] = {}
        self.full_dirs: dict[str, Path] = {}
        self.states: dict[str, Path] = {}
        self.worktrees: dict[str, Path] = {}
        for k in range(WORKTREES):
            name = f"wt{k}"
            wt = self.base / name
            _git(["worktree", "add", "-q", "-b", f"b-{name}", str(wt), "main"], self.main)
            for n, rel in enumerate(self.rels[k * EDITS:(k + 1) * EDITS]):
                (wt / rel).write_text(f"def edited_{k}_{n}(x):\n    return x + {n}\n", encoding="utf-8")
            state = wt / ".simplicio-loop"
            with mock.patch.dict(os.environ, {CACHE_ENV: str(self.base / "full-cache")}):
                write_mapping_artifacts(str(wt))
            self.full_bytes[name] = dir_bytes(state)
            self.assertGreater(self.full_bytes[name], 0)
            self.full_dirs[name] = self.base / "full" / name
            shutil.copytree(state, self.full_dirs[name])
            shutil.rmtree(state)
            outcome = apply_overlay(str(wt))
            self.assertIsNotNone(outcome.artifacts, outcome.receipt)
            self.states[name] = state
            self.worktrees[name] = wt

    def violations(self) -> list[str]:
        return budget_violations(self.cache, self.full_bytes, self.states)

    def test_each_overlay_and_the_total_stay_within_the_budget(self) -> None:
        overlays = {name: dir_bytes(state) for name, state in self.states.items()}
        measured = (
            f"full={self.full_bytes} overlays={overlays} base={dir_bytes(self.cache)} "
            f"total_share={(dir_bytes(self.cache) + sum(overlays.values())) / sum(self.full_bytes.values()):.2f}"
        )
        self.assertEqual(self.violations(), [], measured)

    def test_a_second_overlay_run_without_changes_adds_no_bytes(self) -> None:
        roots = [self.cache, *self.states.values()]
        before_files = file_set(*roots)
        before = sum(dir_bytes(root) for root in roots)
        outcome = apply_overlay(str(self.worktrees["wt1"]))
        self.assertIsNotNone(outcome.artifacts, outcome.receipt)
        after = sum(dir_bytes(root) for root in roots)
        self.assertEqual(file_set(*roots), before_files, "a second run must not add an artifact")
        self.assertLessEqual(after, before + REWRITE_SLACK_BYTES, f"before={before} after={after}")
        self.assertEqual(self.violations(), [])

    def test_mutant_overlay_that_copies_the_call_graph_breaks_the_budget(self) -> None:
        self.assertEqual(self.violations(), [])
        shutil.copy(self.full_dirs["wt0"] / "call-graph.json", self.states["wt0"] / "call-graph.json")
        self.assertTrue(any("call-graph.json" in v for v in self.violations()), self.violations())

    def test_mutant_overlay_that_copies_the_retrieval_index_breaks_the_budget(self) -> None:
        self.assertEqual(self.violations(), [])
        source = self.full_dirs["wt0"] / "retrieval-index.json"
        if not source.exists():
            source = self.full_dirs["wt0"] / "call-graph.json"
        shutil.copy(source, self.states["wt0"] / "retrieval-index.json")
        self.assertTrue(any("retrieval-index.json" in v for v in self.violations()), self.violations())

    def test_mutant_that_builds_the_base_twice_breaks_the_budget(self) -> None:
        self.assertEqual(self.violations(), [])
        canonical = os.path.join(self.cache, "canonical")
        (digest,) = os.listdir(canonical)
        shutil.copytree(os.path.join(canonical, digest), os.path.join(canonical, digest + "-second"))
        self.assertTrue(any("central bases" in v for v in self.violations()), self.violations())


if __name__ == "__main__":
    unittest.main()
