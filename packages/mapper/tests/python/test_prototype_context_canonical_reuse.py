"""Tests for the issue #286 canonical-map-reuse follow-up in
`simplicio_mapper/prototype_context.py` (ADR-012 addendum).

Issue #286's own last status comment named this as the one genuinely open
piece: "Canonical default-branch map reuse / per-worktree overlays (steps 1,
7, 8) -- depends on #236/#263's operational lifecycle, which this command
does not consume yet". Issue #236/#263 (the canonical-map/overlay epic) is
now closed, including the public sync API
`simplicio_mapper.mapper.canonical_api.get_effective_map_view`. This module
wires `build_prototype_context()` to that API as a fallback-safe, opt-in
*performance* layer -- never a change to the returned
`simplicio.prototype-context/v1` envelope's content or schema.

Covers, per this repo's Python-package DoD (7 dimensions, `AGENTS.md`):

- **Unit**: the pure branching helpers in isolation
  (`_canonical_reuse_enabled`, `_overlay_is_worktree_identical`,
  `_resolve_artifacts`) with real (not stubbed) canonical dataclasses.
- **Integration**: a real git fixture repo, a real canonical manifest built
  via `canonical_builder.build_canonical_manifest`, then
  `build_prototype_context` actually consuming it
  (`_load_artifacts_from_canonical_view`).
- **System**: the real `simplicio-mapper prototype-context ... --json` CLI
  entry point, once with canonical data available and once forced off via
  `--no-canonical-reuse`.
- **Regression**: behavior-preservation proof -- the canonical-reuse path
  forced ON vs. forced OFF against the exact same repo/query produces an
  observably identical envelope (every field except the inherently-variable
  timing/truncation-derived ones); a non-git fixture (as already exercised by
  `test_prototype_context.py`) still resolves via the pre-existing
  fresh-resolve path, byte-for-byte the same as before this feature existed.
- **Perf benchmark**: an honest timing comparison for a repeated query
  against the same commit -- printed, not assumed, and not asserted to be
  a win (see module docstring "if it isn't [faster] ... report that
  honestly").

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import simplicio_mapper.prototype_context as prototype_context  # noqa: E402
from simplicio_mapper.mapper.canonical_api import get_effective_map_view  # noqa: E402
from simplicio_mapper.mapper.canonical_builder import build_canonical_manifest  # noqa: E402
from simplicio_mapper.mapper.canonical_reuse import compute_config_fingerprint  # noqa: E402
from simplicio_mapper.mapper.canonical_storage import CANONICAL_CACHE_DIR_ENV_VAR  # noqa: E402
from simplicio_mapper.prototype_context import (  # noqa: E402
    CANONICAL_REUSE_KILL_SWITCH,
    _canonical_reuse_enabled,
    _overlay_is_worktree_identical,
    _resolve_artifacts,
    build_prototype_context,
    run_prototype_context_cli,
)


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _write_source_files(root: Path, extra_modules: int = 0) -> None:
    src = root / "src"
    tests_dir = root / "tests"
    src.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    (src / "app.py").write_text(
        "def greet(name):\n    return f'hello {name}'\n\ndef main():\n    print(greet('world'))\n",
        encoding="utf-8",
    )
    (src / "util.py").write_text("def unrelated():\n    return 1\n", encoding="utf-8")
    (tests_dir / "test_app.py").write_text(
        "from src.app import greet\n\ndef test_greet():\n    assert greet('world') == 'hello world'\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    for index in range(extra_modules):
        (src / f"extra_{index}.py").write_text(
            f"def helper_{index}(value):\n    return value + {index}\n\n"
            f"class Extra{index}:\n    def run(self):\n        return helper_{index}(1)\n",
            encoding="utf-8",
        )


def _init_git_repo(root: Path, *, extra_modules: int = 0, default_branch: str = "main") -> None:
    root.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "--initial-branch", default_branch], root)
    _run_git(["config", "user.email", "test@example.com"], root)
    _run_git(["config", "user.name", "Test User"], root)
    _write_source_files(root, extra_modules=extra_modules)
    _run_git(["add", "."], root)
    _run_git(["commit", "-m", "init"], root)


def _clean_out_dir(root: Path, out_dir: str = ".simplicio-loop") -> None:
    """Remove ``<root>/<out_dir>`` if present.

    A fresh-resolve `build_prototype_context()` call runs `build_artifacts()`,
    which persists a `FileProcessingCache` under `<out_dir>/cache/` as a
    side effect of `_build_artifacts_sync` -- entirely pre-existing behavior,
    unrelated to the canonical-reuse feature under test here. Left in place,
    that cache directory would make the *next* call's `git status
    --porcelain` (and therefore `source_binding.dirty` /
    `canonical_reuse.eligible`) see the previous call's own untracked
    artifact as worktree drift, contaminating an ON-vs-OFF comparison run
    back-to-back against the same repo. Cleaning between calls isolates each
    call's observable result from the other's disk side effects.
    """
    out_path = root / out_dir
    if out_path.exists():
        shutil.rmtree(out_path)


def _strip_volatile(payload: dict) -> dict:
    """Drop the fields expected to differ between a canonical-reuse call and
    a fresh-resolve call for reasons that are NOT a behavior change in this
    feature:

    - ``measurements``/``context_hash``/``tokens_estimated``/``truncated``/
      ``omitted_counts`` -- wall-clock timing and the truncation/hash fields
      derived from it.
    - ``source_binding.dirty`` / ``canonical_reuse.eligible`` -- these
      reflect `git status --porcelain` at the moment `_source_binding` runs.
      The fresh-resolve path calls the pre-existing `build_artifacts()`,
      whose `FileProcessingCache` persists a cache under `<out>/cache/` as a
      documented side effect *before* `_source_binding` runs in that same
      call -- so a fresh-resolve call on an otherwise byte-identical worktree
      self-reports `dirty=True` even though nothing about the *source* the
      caller queried actually changed. This is pre-existing
      `build_artifacts()` behavior, unrelated to and unaffected by whether
      canonical reuse is used -- genuine worktree dirtiness (an actual edit
      to a real source file) is covered independently by
      `test_dirty_worktree_falls_back_to_fresh_resolve_even_when_canonical_enabled`,
      which does not rely on this comparison.
    """
    stripped = dict(payload)
    for key in ("measurements", "context_hash", "tokens_estimated", "truncated", "omitted_counts"):
        stripped.pop(key, None)
    if "source_binding" in stripped:
        source_binding = dict(stripped["source_binding"])
        source_binding.pop("dirty", None)
        stripped["source_binding"] = source_binding
    if "canonical_reuse" in stripped:
        canonical_reuse = dict(stripped["canonical_reuse"])
        canonical_reuse.pop("eligible", None)
        stripped["canonical_reuse"] = canonical_reuse
    return stripped


class _CanonicalFixture(unittest.TestCase):
    """Shared setup: an isolated canonical cache dir + a real git fixture repo
    with a real canonical manifest built for its HEAD commit."""

    extra_modules = 0

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.root = self.base / "repo"
        _init_git_repo(self.root, extra_modules=self.extra_modules)

        self._cache_dir = self.base / "canonical-cache"
        self._saved_cache_env = os.environ.pop(CANONICAL_CACHE_DIR_ENV_VAR, None)
        os.environ[CANONICAL_CACHE_DIR_ENV_VAR] = str(self._cache_dir)
        self.addCleanup(self._restore_cache_env)

        self.config_fingerprint = compute_config_fingerprint(None, ".simplicio-loop")
        manifest = build_canonical_manifest(str(self.root), str(self._cache_dir), self.config_fingerprint)
        self.assertIsNotNone(manifest, "test setup requires a real canonical manifest to build successfully")
        self.manifest = manifest

    def _restore_cache_env(self) -> None:
        if self._saved_cache_env is not None:
            os.environ[CANONICAL_CACHE_DIR_ENV_VAR] = self._saved_cache_env
        else:
            os.environ.pop(CANONICAL_CACHE_DIR_ENV_VAR, None)

    def _assert_view_is_clean_and_reusable(self) -> None:
        view = get_effective_map_view(str(self.root), out=".simplicio-loop")
        self.assertIsNotNone(view, "canonical view must resolve for a clean worktree at the canonical commit")
        assert view is not None
        self.assertTrue(_overlay_is_worktree_identical(view, ".simplicio-loop"))


class CanonicalReuseEnabledUnitTest(unittest.TestCase):
    """Unit coverage of `_canonical_reuse_enabled` -- no git, no I/O."""

    def setUp(self) -> None:
        self._saved = os.environ.pop(CANONICAL_REUSE_KILL_SWITCH, None)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        if self._saved is not None:
            os.environ[CANONICAL_REUSE_KILL_SWITCH] = self._saved
        else:
            os.environ.pop(CANONICAL_REUSE_KILL_SWITCH, None)

    def test_explicit_true_wins_even_if_kill_switch_set(self) -> None:
        os.environ[CANONICAL_REUSE_KILL_SWITCH] = "1"
        self.assertTrue(_canonical_reuse_enabled(True))

    def test_explicit_false_wins_even_if_kill_switch_unset(self) -> None:
        os.environ.pop(CANONICAL_REUSE_KILL_SWITCH, None)
        self.assertFalse(_canonical_reuse_enabled(False))

    def test_default_is_enabled_when_kill_switch_unset(self) -> None:
        os.environ.pop(CANONICAL_REUSE_KILL_SWITCH, None)
        self.assertTrue(_canonical_reuse_enabled(None))

    def test_kill_switch_disables_by_default(self) -> None:
        os.environ[CANONICAL_REUSE_KILL_SWITCH] = "1"
        self.assertFalse(_canonical_reuse_enabled(None))


class ResolveArtifactsUnitTest(unittest.TestCase):
    """Unit coverage of `_resolve_artifacts`'s branching, with
    `get_effective_map_view`/`_load_artifacts_from_canonical_view` mocked out
    -- proves the fallback wiring itself without needing a real git repo."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        _write_source_files(Path(self.root))

    def test_falls_back_to_fresh_resolve_when_view_is_none(self) -> None:
        original = prototype_context.get_effective_map_view
        prototype_context.get_effective_map_view = lambda *a, **k: None
        try:
            artifacts, served_from_canonical = _resolve_artifacts(self.root, ".simplicio-loop", None)
        finally:
            prototype_context.get_effective_map_view = original
        self.assertFalse(served_from_canonical)
        self.assertIn("project_map", artifacts)

    def test_falls_back_to_fresh_resolve_when_canonical_load_fails(self) -> None:
        original_view = prototype_context.get_effective_map_view
        original_load = prototype_context._load_artifacts_from_canonical_view
        prototype_context.get_effective_map_view = lambda *a, **k: object()
        prototype_context._load_artifacts_from_canonical_view = lambda *a, **k: None
        try:
            artifacts, served_from_canonical = _resolve_artifacts(self.root, ".simplicio-loop", None)
        finally:
            prototype_context.get_effective_map_view = original_view
            prototype_context._load_artifacts_from_canonical_view = original_load
        self.assertFalse(served_from_canonical)
        self.assertIn("project_map", artifacts)

    def test_uses_canonical_artifacts_when_view_and_load_succeed(self) -> None:
        sentinel_artifacts = {
            "project_map": {"files": []},
            "precedent_index": {"items": []},
            "architecture_inventory": {},
            "symbol_index": {"symbols": []},
            "call_graph": {"edges": []},
        }
        original_view = prototype_context.get_effective_map_view
        original_load = prototype_context._load_artifacts_from_canonical_view
        prototype_context.get_effective_map_view = lambda *a, **k: object()
        prototype_context._load_artifacts_from_canonical_view = lambda *a, **k: sentinel_artifacts
        try:
            artifacts, served_from_canonical = _resolve_artifacts(self.root, ".simplicio-loop", None)
        finally:
            prototype_context.get_effective_map_view = original_view
            prototype_context._load_artifacts_from_canonical_view = original_load
        self.assertTrue(served_from_canonical)
        self.assertIs(artifacts, sentinel_artifacts)

    def test_use_canonical_false_never_calls_get_effective_map_view(self) -> None:
        calls: list[str] = []
        original = prototype_context.get_effective_map_view

        def _tracking_stub(*_args, **_kwargs):
            calls.append("called")
            return None

        prototype_context.get_effective_map_view = _tracking_stub
        try:
            _resolve_artifacts(self.root, ".simplicio-loop", False)
        finally:
            prototype_context.get_effective_map_view = original
        self.assertEqual(calls, [])


class OverlayIdenticalUnitTest(_CanonicalFixture):
    """Unit coverage of `_overlay_is_worktree_identical` against a real,
    composed `EffectiveMapView` (clean vs. dirty vs. committed-drift)."""

    def test_clean_worktree_is_reusable(self) -> None:
        self._assert_view_is_clean_and_reusable()

    def test_dirty_worktree_is_not_reusable(self) -> None:
        (self.root / "README.md").write_text("dirty\n", encoding="utf-8")
        view = get_effective_map_view(str(self.root), out=".simplicio-loop")
        self.assertIsNotNone(view)
        assert view is not None
        self.assertTrue(view.overlay.dirty)
        self.assertFalse(_overlay_is_worktree_identical(view, ".simplicio-loop"))

    def test_committed_drift_is_not_reusable(self) -> None:
        # `default_branch` resolution (`main`, per `_init_git_repo`) is
        # independent of whatever branch is currently checked out -- so a
        # commit on a *divergent* branch, with `main` left untouched at the
        # commit the canonical manifest was built for, is what actually
        # reproduces "worktree HEAD has committed drift vs. the canonical
        # base commit". Committing straight onto `main` would instead just
        # advance the canonical key's own commit_sha (a fresh manifest would
        # be built for it, trivially "clean" against itself) -- not a useful
        # regression case.
        _run_git(["checkout", "-b", "feature"], self.root)
        (self.root / "src" / "new_module.py").write_text("def added():\n    return 2\n", encoding="utf-8")
        _run_git(["add", "."], self.root)
        _run_git(["commit", "-m", "drift"], self.root)
        view = get_effective_map_view(str(self.root), out=".simplicio-loop")
        self.assertIsNotNone(view)
        assert view is not None
        self.assertTrue(view.overlay.changed_files)
        self.assertFalse(_overlay_is_worktree_identical(view, ".simplicio-loop"))

    def test_output_dir_only_noise_is_still_reusable(self) -> None:
        # A freshly-created `.simplicio-loop/` artifact (e.g. from an unrelated
        # earlier run) must never count as worktree drift -- otherwise the
        # very act of using this mapper would starve its own reuse path.
        out_dir = self.root / ".simplicio-loop"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "scratch.json").write_text("{}", encoding="utf-8")
        view = get_effective_map_view(str(self.root), out=".simplicio-loop")
        self.assertIsNotNone(view)
        assert view is not None
        self.assertTrue(_overlay_is_worktree_identical(view, ".simplicio-loop"))


class CanonicalReuseIntegrationTest(_CanonicalFixture):
    """Integration: `build_prototype_context` actually consuming a real
    canonical manifest end-to-end."""

    def test_canonical_path_is_used_when_available_and_clean(self) -> None:
        self._assert_view_is_clean_and_reusable()
        payload = build_prototype_context(str(self.root), type_="bug", arg="src/app.py", use_canonical=True)
        self.assertEqual(payload["measurements"]["artifacts_source"], "canonical-manifest")

    def test_forced_off_uses_fresh_resolve_even_when_canonical_available(self) -> None:
        payload = build_prototype_context(str(self.root), type_="bug", arg="src/app.py", use_canonical=False)
        self.assertEqual(payload["measurements"]["artifacts_source"], "fresh-resolve")

    def test_kill_switch_forces_fresh_resolve(self) -> None:
        os.environ[CANONICAL_REUSE_KILL_SWITCH] = "1"
        try:
            payload = build_prototype_context(str(self.root), type_="bug", arg="src/app.py")
        finally:
            os.environ.pop(CANONICAL_REUSE_KILL_SWITCH, None)
        self.assertEqual(payload["measurements"]["artifacts_source"], "fresh-resolve")

    def test_dirty_worktree_falls_back_to_fresh_resolve_even_when_canonical_enabled(self) -> None:
        (self.root / "src" / "util.py").write_text("def unrelated():\n    return 999\n", encoding="utf-8")
        payload = build_prototype_context(str(self.root), type_="bug", arg="src/app.py", use_canonical=True)
        self.assertEqual(payload["measurements"]["artifacts_source"], "fresh-resolve")

    def test_envelope_is_behavior_identical_on_vs_off(self) -> None:
        """Behavior-preservation proof (issue #286 follow-up requirement):
        the canonical-reuse path forced ON vs. forced OFF against the exact
        same repo/query must produce an observably identical envelope --
        only performance/internal-resolution may differ, never the result.
        """
        payload_on = build_prototype_context(str(self.root), type_="bug", arg="src/app.py", use_canonical=True)
        _clean_out_dir(self.root)
        payload_off = build_prototype_context(str(self.root), type_="bug", arg="src/app.py", use_canonical=False)
        _clean_out_dir(self.root)

        self.assertEqual(payload_on["measurements"]["artifacts_source"], "canonical-manifest")
        self.assertEqual(payload_off["measurements"]["artifacts_source"], "fresh-resolve")
        self.assertEqual(payload_on["context_hash_algorithm"], payload_off["context_hash_algorithm"])

        self.assertEqual(_strip_volatile(payload_on), _strip_volatile(payload_off))


class CanonicalReuseCliSystemTest(_CanonicalFixture):
    """System: the real `simplicio-mapper prototype-context ... --json` CLI
    entry point, once with canonical data available, once forced off."""

    def _run_cli(self, argv: list[str]) -> dict:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = run_prototype_context_cli(argv)
        self.assertEqual(exit_code, 0, buffer.getvalue())
        return json.loads(buffer.getvalue())

    def test_cli_with_canonical_data_available(self) -> None:
        self._assert_view_is_clean_and_reusable()
        payload = self._run_cli([str(self.root), "--type", "bug", "--arg", "src/app.py", "--json"])
        self.assertEqual(payload["schema"], "simplicio.prototype-context/v1")
        self.assertEqual(payload["measurements"]["artifacts_source"], "canonical-manifest")

    def test_cli_without_canonical_reuse_flag(self) -> None:
        payload = self._run_cli(
            [str(self.root), "--type", "bug", "--arg", "src/app.py", "--json", "--no-canonical-reuse"]
        )
        self.assertEqual(payload["schema"], "simplicio.prototype-context/v1")
        self.assertEqual(payload["measurements"]["artifacts_source"], "fresh-resolve")

    def test_cli_envelopes_are_behavior_identical(self) -> None:
        payload_on = self._run_cli([str(self.root), "--type", "bug", "--arg", "src/app.py", "--json"])
        _clean_out_dir(self.root)
        payload_off = self._run_cli(
            [str(self.root), "--type", "bug", "--arg", "src/app.py", "--json", "--no-canonical-reuse"]
        )
        _clean_out_dir(self.root)
        self.assertEqual(_strip_volatile(payload_on), _strip_volatile(payload_off))


class NonGitRepoRegressionTest(unittest.TestCase):
    """Regression: a non-git fixture (the shape every existing
    `test_prototype_context.py` case already uses) must keep resolving via
    the exact pre-existing fresh-resolve path, exactly as before this
    feature existed -- `get_effective_map_view` returns `None` for a non-git
    directory, so canonical reuse is never even attempted."""

    def test_non_git_directory_always_uses_fresh_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_source_files(Path(tmp))
            payload = build_prototype_context(tmp, type_="bug", arg="src/app.py")
            self.assertEqual(payload["measurements"]["artifacts_source"], "fresh-resolve")
            self.assertEqual(payload["schema"], "simplicio.prototype-context/v1")


class CanonicalReusePerfBenchmarkTest(_CanonicalFixture):
    """Perf benchmark (DoD dimension, `AGENTS.md` Python-package DoD):
    measures -- honestly, without assuming a result -- whether the
    canonical-reuse path is actually faster than a fresh `build_artifacts()`
    resolve for a repeated query against the same commit. This asserts only
    that both paths complete and produce a valid envelope; the timing
    numbers are printed for the PR record rather than asserted on, since a
    small fixture repo's absolute timings are dominated by fixed overhead
    (git subprocess spawns for the canonical path, filesystem parse for the
    fresh path) that will not generalize to every repo size.
    """

    extra_modules = 40

    def test_repeated_query_timing_report(self) -> None:
        iterations = 5

        fresh_seconds = []
        for _ in range(iterations):
            started = time.perf_counter()
            payload = build_prototype_context(str(self.root), type_="bug", arg="src/app.py", use_canonical=False)
            fresh_seconds.append(time.perf_counter() - started)
            self.assertEqual(payload["measurements"]["artifacts_source"], "fresh-resolve")

        canonical_seconds = []
        for _ in range(iterations):
            started = time.perf_counter()
            payload = build_prototype_context(str(self.root), type_="bug", arg="src/app.py", use_canonical=True)
            canonical_seconds.append(time.perf_counter() - started)
            self.assertEqual(payload["measurements"]["artifacts_source"], "canonical-manifest")

        avg_fresh = sum(fresh_seconds) / len(fresh_seconds)
        avg_canonical = sum(canonical_seconds) / len(canonical_seconds)
        speedup = (avg_fresh / avg_canonical) if avg_canonical else float("inf")
        print(
            "\n[perf-benchmark] prototype-context canonical-reuse vs fresh-resolve "
            f"(repeated query, same commit, {self.extra_modules + 3} files): "
            f"fresh avg={avg_fresh:.4f}s canonical avg={avg_canonical:.4f}s "
            f"speedup={speedup:.2f}x "
            f"({'canonical faster' if speedup > 1 else 'canonical NOT faster -- reported honestly'})"
        )


if __name__ == "__main__":
    unittest.main()
