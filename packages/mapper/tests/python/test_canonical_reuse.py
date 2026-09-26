"""Tests for simplicio_mapper.mapper.canonical_reuse (issue #269, ADR-008 step 6).

Covers the opt-in canonical-map reuse wiring for ``index``/``scan``:

- Unit coverage of the module's pure helpers (config fingerprint, trivial-
  overlay detection, opt-in switch resolution).
- Integration coverage of ``attempt_canonical_reuse`` against real temporary
  git repositories (never mocked ``git`` output) -- hit, dirty-worktree
  fallback, divergent-worktree fallback, invalid-cache fallback.
- System (real subprocess, real ``simplicio-mapper`` entry point) coverage
  proving: opt-in hit end-to-end, default behavior is unaffected byte-for-
  byte when the flag is absent, and ``scan`` propagates the flag to its
  spawned deep-pass worker.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli._args import _parse_args  # noqa: E402
from simplicio_mapper.cli._background import _spawn_index_process  # noqa: E402
from simplicio_mapper.mapper import canonical_reuse  # noqa: E402
from simplicio_mapper.mapper.canonical_reuse import (  # noqa: E402
    CANONICAL_REUSE_ENV_VAR,
    attempt_canonical_reuse,
    compute_config_fingerprint,
    is_canonical_reuse_enabled,
)


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(path: Path, *, default_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["init", "--initial-branch", default_branch], path)
    _run(["config", "user.email", "test@example.com"], path)
    _run(["config", "user.name", "Test User"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    src = path / "src"
    src.mkdir(exist_ok=True)
    (src / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _run(["add", "."], path)
    _run(["commit", "-m", "init"], path)


class ConfigFingerprintTests(unittest.TestCase):
    def test_different_stack_overrides_never_share_a_fingerprint(self) -> None:
        fp_a = compute_config_fingerprint({"stack": "python"}, ".simplicio-loop")
        fp_b = compute_config_fingerprint({"stack": "node"}, ".simplicio-loop")
        self.assertNotEqual(fp_a, fp_b)

    def test_different_out_dir_never_shares_a_fingerprint(self) -> None:
        fp_a = compute_config_fingerprint({}, ".simplicio-loop")
        fp_b = compute_config_fingerprint({}, ".simplicio-alt")
        self.assertNotEqual(fp_a, fp_b)

    def test_same_inputs_are_deterministic(self) -> None:
        meta = {"stack": "python", "product_name": "demo"}
        self.assertEqual(
            compute_config_fingerprint(meta, ".simplicio-loop"),
            compute_config_fingerprint(dict(meta), ".simplicio-loop"),
        )

    def test_none_meta_does_not_raise(self) -> None:
        # attempt_canonical_reuse is always called with a real dict, but the
        # signature accepts None defensively -- must not raise either way.
        self.assertTrue(compute_config_fingerprint(None, ".simplicio-loop"))


class OptInSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop(CANONICAL_REUSE_ENV_VAR, None)
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        if self._saved is not None:
            os.environ[CANONICAL_REUSE_ENV_VAR] = self._saved
        else:
            os.environ.pop(CANONICAL_REUSE_ENV_VAR, None)

    def test_default_is_disabled(self) -> None:
        self.assertFalse(is_canonical_reuse_enabled({}))
        self.assertFalse(is_canonical_reuse_enabled({"canonical_reuse": False}))

    def test_opt_in_flag_enables(self) -> None:
        self.assertTrue(is_canonical_reuse_enabled({"canonical_reuse": True}))

    def test_opt_in_env_var_enables(self) -> None:
        os.environ[CANONICAL_REUSE_ENV_VAR] = "1"
        self.assertTrue(is_canonical_reuse_enabled({}))

    def test_env_var_is_case_insensitive_and_accepts_yes_on_true(self) -> None:
        for value in ("true", "YES", "On"):
            os.environ[CANONICAL_REUSE_ENV_VAR] = value
            self.assertTrue(is_canonical_reuse_enabled({}), value)

    def test_env_var_garbage_does_not_enable(self) -> None:
        os.environ[CANONICAL_REUSE_ENV_VAR] = "nope"
        self.assertFalse(is_canonical_reuse_enabled({}))


class CliFlagParsingTests(unittest.TestCase):
    def test_default_opts_have_canonical_reuse_off(self) -> None:
        opts = _parse_args(["index", "/tmp/whatever"])
        self.assertFalse(opts["canonical_reuse"])

    def test_flag_turns_it_on(self) -> None:
        opts = _parse_args(["index", "/tmp/whatever", "--canonical-reuse"])
        self.assertTrue(opts["canonical_reuse"])

    def test_no_flag_turns_it_back_off(self) -> None:
        opts = _parse_args(["index", "/tmp/whatever", "--canonical-reuse", "--no-canonical-reuse"])
        self.assertFalse(opts["canonical_reuse"])

    def test_scan_spawn_propagates_flag_to_deep_pass_worker(self) -> None:
        opts = _parse_args(["scan", "/tmp/whatever", "--canonical-reuse"])
        opts["root"] = "/tmp/whatever"
        # _spawn_index_process builds the argv for the detached/synchronous
        # deep-pass worker; issue #269 requires --canonical-reuse to reach
        # it too (scan itself never maps directly, it delegates to `index`).
        import inspect

        src = inspect.getsource(_spawn_index_process)
        self.assertIn('"--canonical-reuse"', src)


class AttemptCanonicalReuseIntegrationTests(unittest.TestCase):
    """Real temporary git repos, real canonical builder/overlay -- no mocked git."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self._env_saved = os.environ.pop(canonical_reuse.CANONICAL_REUSE_ENV_VAR, None)
        self._cache_env_saved = os.environ.pop("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        for key, value in (
            (canonical_reuse.CANONICAL_REUSE_ENV_VAR, self._env_saved),
            ("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", self._cache_env_saved),
        ):
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

    def test_clean_worktree_at_canonical_commit_is_a_hit(self) -> None:
        repo = self.base / "repo-clean"
        _init_repo(repo)
        outcome = attempt_canonical_reuse(str(repo), ".simplicio-loop", {})
        self.assertTrue(outcome.receipt["hit"], outcome.receipt)
        self.assertIsNone(outcome.receipt["fallback_reason"])
        self.assertIsNotNone(outcome.run_result)
        self.assertEqual(outcome.receipt["files_reused"], 2)
        self.assertEqual(outcome.receipt["files_remapped"], 0)
        self.assertEqual(outcome.run_result["project_map"]["files"].__len__(), 2)

    def test_first_call_never_blocks_on_the_build_lock_wait_budget(self) -> None:
        """Regression for a self-deadlock between two independent locks at
        the same path (issue #236 cross-worktree lock generalization).

        ``attempt_canonical_reuse`` used to wrap
        ``build_canonical_manifest`` in its own ad-hoc advisory single-flight
        lock (``_single_flight_build``), written directly at
        ``canonical_storage.canonical_build_lock_path``'s path -- the exact
        same file :func:`~simplicio_mapper.mapper.canonical_builder.build_canonical_manifest_with_diagnostics`
        also locks via ``file_lock.acquire_lock_at``. Because the outer
        advisory lock held that file for the whole duration of the call, the
        inner lock's ``os.open(..., O_CREAT | O_EXCL)`` always raised
        ``FileExistsError`` against its own caller's PID, which
        ``inspect_lock_at`` then classified as a live, non-reclaimable
        "legacy" owner -- since the PID belonged to the very process asking,
        it was always alive, so the lock could never free up. The result was
        a guaranteed, single-process self-deadlock: `build_canonical_manifest`
        polled for the full `SIMPLICIO_MAPPER_CANONICAL_BUILD_LOCK_WAIT_SECONDS`
        budget (600s default) before giving up with
        ``fallback_reason="canonical_build_failed"``, even for a totally
        uncontended, freshly created repo with no other process anywhere
        near it.

        A completely isolated, single-process, single-call scenario like
        this one must never come anywhere close to the lock-wait budget --
        bounding the wall-clock duration here at a small fraction of that
        budget catches any future reintroduction of a second, colliding lock
        implementation at the same path, not just this specific one.
        """
        repo = self.base / "repo-no-self-deadlock"
        _init_repo(repo)
        start = time.monotonic()
        outcome = attempt_canonical_reuse(str(repo), ".simplicio-loop", {})
        elapsed = time.monotonic() - start
        self.assertTrue(outcome.receipt["hit"], outcome.receipt)
        self.assertLess(
            elapsed,
            10.0,
            f"attempt_canonical_reuse took {elapsed:.1f}s -- expected a few "
            "seconds at most for an uncontended, freshly created repo; a "
            "duration anywhere near the lock-wait budget indicates the "
            "build lock is self-blocked again",
        )
        self.assertLess(outcome.receipt["duration_s"], 10.0, outcome.receipt)

    def test_uncommitted_change_is_a_non_trivial_fallback(self) -> None:
        repo = self.base / "repo-dirty"
        _init_repo(repo)
        (repo / "README.md").write_text("edited locally\n", encoding="utf-8")
        outcome = attempt_canonical_reuse(str(repo), ".simplicio-loop", {})
        self.assertFalse(outcome.receipt["hit"])
        self.assertEqual(outcome.receipt["fallback_reason"], "overlay_not_trivial")
        self.assertIsNone(outcome.run_result)

    def test_untracked_file_is_a_non_trivial_fallback(self) -> None:
        repo = self.base / "repo-untracked"
        _init_repo(repo)
        (repo / "src" / "new_file.py").write_text("X = 1\n", encoding="utf-8")
        outcome = attempt_canonical_reuse(str(repo), ".simplicio-loop", {})
        self.assertFalse(outcome.receipt["hit"])
        self.assertEqual(outcome.receipt["fallback_reason"], "overlay_not_trivial")

    def test_divergent_worktree_commit_is_a_non_trivial_fallback(self) -> None:
        repo = self.base / "repo-divergent"
        _init_repo(repo)
        first_commit = _run(["rev-parse", "HEAD"], repo).stdout.strip()
        (repo / "src" / "second.py").write_text("Y = 2\n", encoding="utf-8")
        _run(["add", "."], repo)
        _run(["commit", "-m", "second"], repo)

        # A second worktree checked out at the *first* commit -- the
        # resolved default branch (main) has since moved to the second
        # commit, so this worktree's HEAD diverges from the canonical base.
        divergent_wt = self.base / "repo-divergent-wt"
        _run(["worktree", "add", "--detach", str(divergent_wt), first_commit], repo)
        try:
            outcome = attempt_canonical_reuse(str(divergent_wt), ".simplicio-loop", {})
            self.assertFalse(outcome.receipt["hit"])
            self.assertEqual(outcome.receipt["fallback_reason"], "overlay_not_trivial")
            self.assertIsNone(outcome.run_result)
        finally:
            _run(["worktree", "remove", "--force", str(divergent_wt)], repo)

    def test_non_git_directory_falls_back_to_identity_unresolved(self) -> None:
        plain = self.base / "plain"
        plain.mkdir()
        outcome = attempt_canonical_reuse(str(plain), ".simplicio-loop", {})
        self.assertFalse(outcome.receipt["hit"])
        self.assertEqual(outcome.receipt["fallback_reason"], "identity_unresolved")
        self.assertIsNone(outcome.run_result)

    def test_invalid_cache_root_falls_back_without_raising(self) -> None:
        """A cache root that cannot be a directory (e.g. a stray file at that
        path) must never crash the caller -- forced failure fallback."""
        repo = self.base / "repo-invalid-cache"
        _init_repo(repo)
        bogus_cache_root = self.base / "bogus-cache-root"
        bogus_cache_root.write_text("not a directory\n", encoding="utf-8")
        os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = str(bogus_cache_root)
        outcome = attempt_canonical_reuse(str(repo), ".simplicio-loop", {})
        self.assertFalse(outcome.receipt["hit"])
        self.assertIsNotNone(outcome.receipt["fallback_reason"])
        self.assertIsNone(outcome.run_result)

    def test_second_worktree_on_same_commit_also_hits(self) -> None:
        repo = self.base / "repo-multi"
        _init_repo(repo)
        second_wt = self.base / "repo-multi-second"
        _run(["worktree", "add", str(second_wt)], repo)
        try:
            first = attempt_canonical_reuse(str(repo), ".simplicio-loop", {})
            second = attempt_canonical_reuse(str(second_wt), ".simplicio-loop", {})
            self.assertTrue(first.receipt["hit"])
            self.assertTrue(second.receipt["hit"])
            self.assertEqual(
                first.receipt["canonical_key_digest"],
                second.receipt["canonical_key_digest"],
            )
        finally:
            _run(["worktree", "remove", "--force", str(second_wt)], repo)

    def test_receipt_never_leaks_internal_timer_field(self) -> None:
        repo = self.base / "repo-receipt-shape"
        _init_repo(repo)
        outcome = attempt_canonical_reuse(str(repo), ".simplicio-loop", {})
        self.assertNotIn("_t0", outcome.receipt)
        self.assertEqual(outcome.receipt["schema"], canonical_reuse.RECEIPT_SCHEMA)
        self.assertEqual(outcome.receipt["schema_version"], canonical_reuse.RECEIPT_SCHEMA_VERSION)


class CliSubprocessSystemTests(unittest.TestCase):
    """Real ``python -m simplicio_mapper.cli`` invocations (system-level, issue #269)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        _init_repo(self.repo)

    def _cli(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        # Explicit PYTHONPATH (rather than relying on `cwd`-derived sys.path[0]
        # alone): `scan` spawns a *nested* `index` subprocess whose own cwd is
        # the mapped repo, not this worktree, so it cannot fall back to a
        # cwd-based import -- it needs this worktree's `simplicio_mapper` on
        # PYTHONPATH to resolve correctly instead of whatever copy happens to
        # be editable-installed globally (e.g. a sibling worktree's checkout).
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT), existing]) if existing else str(ROOT)
        return subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.cli", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            env=env,
        )

    def _last_json(self, result: subprocess.CompletedProcess) -> dict:
        self.assertTrue(result.stdout.strip(), result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_default_index_has_no_canonical_reuse_key_at_all(self) -> None:
        """Regression: default behavior must stay byte-for-byte unchanged."""
        result = self._cli("index", str(self.repo), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = self._last_json(result)
        self.assertNotIn("canonical_reuse", payload)
        receipt_path = self.repo / ".simplicio-loop" / "canonical-reuse-receipt.json"
        self.assertFalse(receipt_path.exists())

    def test_opt_in_flag_hits_and_writes_a_versioned_receipt(self) -> None:
        result = self._cli("index", str(self.repo), "--canonical-reuse", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = self._last_json(result)
        self.assertIn("canonical_reuse", payload)
        self.assertTrue(payload["canonical_reuse"]["hit"], payload["canonical_reuse"])

        receipt_path = self.repo / ".simplicio-loop" / "canonical-reuse-receipt.json"
        self.assertTrue(receipt_path.exists())
        on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["schema"], "simplicio.canonical-reuse-receipt/v1")
        self.assertTrue(on_disk["hit"])

        project_map_path = self.repo / ".simplicio-loop" / "project-map.json"
        self.assertTrue(project_map_path.is_file())
        project_map = json.loads(project_map_path.read_text(encoding="utf-8"))
        self.assertEqual(len(project_map["files"]), 2)

    def test_env_var_opt_in_also_hits(self) -> None:
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT), existing]) if existing else str(ROOT)
        env["SIMPLICIO_MAPPER_CANONICAL_REUSE"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.cli", "index", str(self.repo), "--json"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
            env=env,
        )
        payload = self._last_json(result)
        self.assertIn("canonical_reuse", payload)
        self.assertTrue(payload["canonical_reuse"]["hit"])

    def test_dirty_worktree_opt_in_falls_back_and_still_produces_fresh_artifacts(self) -> None:
        (self.repo / "README.md").write_text("changed after canonical commit\n", encoding="utf-8")
        result = self._cli("index", str(self.repo), "--canonical-reuse", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = self._last_json(result)
        self.assertIn("canonical_reuse", payload)
        self.assertFalse(payload["canonical_reuse"]["hit"])
        self.assertEqual(payload["canonical_reuse"]["fallback_reason"], "overlay_not_trivial")

        # Never stale: the fallback full map must reflect the *real* current
        # file, not a cached/serve-from-canonical README entry.
        project_map = json.loads((self.repo / ".simplicio-loop" / "project-map.json").read_text(encoding="utf-8"))
        readme_entries = [f for f in project_map["files"] if f["path"] == "README.md"]
        self.assertEqual(len(readme_entries), 1)

    def test_scan_sync_baseline_never_writes_a_receipt(self) -> None:
        result = self._cli("scan", str(self.repo), "--sync", "--timeout", "60", "--json", timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt_path = self.repo / ".simplicio-loop" / "canonical-reuse-receipt.json"
        self.assertFalse(receipt_path.exists())

    def test_scan_sync_propagates_opt_in_to_deep_pass_worker(self) -> None:
        # A fresh repo (no prior index-state.json) so the spawned deep pass
        # actually runs the mapping path instead of short-circuiting on
        # "already_fresh" -- that skip branch never calls `_run_once` at all,
        # so it would never be able to prove the flag reached the worker.
        result = self._cli(
            "scan",
            str(self.repo),
            "--sync",
            "--timeout",
            "60",
            "--canonical-reuse",
            "--json",
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt_path = self.repo / ".simplicio-loop" / "canonical-reuse-receipt.json"
        self.assertTrue(receipt_path.exists())
        on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertTrue(on_disk["hit"], on_disk)


if __name__ == "__main__":
    unittest.main()
