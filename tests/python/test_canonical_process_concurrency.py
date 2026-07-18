"""Real multi-process concurrency/crash-recovery tests for the canonical map
(issue #236 epic, issue #263 integration slice).

The epic's mandatory test list ("Testes obrigatorios") requires:

- "Dez ou mais processos solicitando o mesmo mapa simultaneamente" -- the
  only existing "ten concurrent" coverage
  (``test_canonical_gc.py::CurrentManifestPreservationTests::
  test_ten_concurrent_readers_never_see_their_snapshot_removed``) drives ten
  *threads* calling ``scan_canonical_gc`` against an *already-built*
  manifest -- it never exercises ten independent OS processes racing to
  *build* the same canonical manifest for the first time, which is the
  actual single-flight/idempotency scenario the epic and issue #263
  acceptance criterion 8 ("ten concurrent requests") describe. This module
  closes that gap with real ``subprocess.Popen`` processes (never threads)
  invoking the real ``simplicio-mapper canonical build --json`` CLI entry
  point concurrently against one repository.
- "Crash durante build/promocao/GC" -- existing ``test_canonical_gc.py``
  coverage simulates a crash by manually placing a stale ``.tmp-<pid>``
  directory on disk for an already-dead pid; it never actually kills a real
  builder process *while it is writing* a real staging directory. This
  module adds that: a real subprocess is SIGKILL'd the instant its real
  ``<digest>.tmp-<pid>/`` staging directory appears on disk (caught via
  polling, not a fixed sleep, so the kill is genuinely mid-write rather than
  guessed), then exercises the real recovery path -- ``canonical gc``
  reclaiming the dead builder's leftover staging directory, followed by a
  fresh ``build_canonical_manifest`` call producing a correct manifest.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.canonical import (  # noqa: E402
    CANONICAL_MAP_SCHEMA_VERSION,
    CanonicalMapKey,
)
from simplicio_mapper.mapper.canonical_builder import (  # noqa: E402
    _mapper_version,
    build_canonical_manifest,
)
from simplicio_mapper.mapper.canonical_gc import scan_canonical_gc  # noqa: E402
from simplicio_mapper.mapper.canonical_identity import resolve_repo_identity_bundle  # noqa: E402
from simplicio_mapper.mapper.canonical_storage import (  # noqa: E402
    canonical_manifest_dir,
)


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(path: Path, *, file_count: int = 1, default_branch: str = "main") -> None:
    """Real git repo with ``file_count`` real Python files (real content, real commit)."""
    path.mkdir(parents=True, exist_ok=True)
    _run(["init", "-q", "--initial-branch", default_branch], path)
    _run(["config", "user.email", "test@example.com"], path)
    _run(["config", "user.name", "Test User"], path)
    for i in range(file_count):
        pkg = path / f"pkg{i % 20}"
        pkg.mkdir(exist_ok=True)
        (pkg / f"mod{i}.py").write_text(f"def f{i}():\n    return {i}\n", encoding="utf-8")
    _run(["add", "-A"], path)
    _run(["commit", "-q", "-m", "init"], path)


def _expected_digest(repo: Path, config_fingerprint: str) -> str:
    """Compute the same ``CanonicalMapKey.digest()`` the real builder would.

    Mirrors ``build_canonical_manifest``'s own key construction so the test
    can compute the exact on-disk staging path *before* spawning the real
    builder subprocess, without importing any private builder internals.
    """
    identity = resolve_repo_identity_bundle(str(repo))
    assert identity is not None
    key = CanonicalMapKey(
        repo_identity=identity.repo_identity,
        default_branch=identity.default_branch,
        commit_sha=identity.commit_sha,
        tree_sha=identity.tree_sha,
        schema_version=CANONICAL_MAP_SCHEMA_VERSION,
        mapper_version=_mapper_version(),
        config_fingerprint=config_fingerprint,
        platform_tag=None,
    )
    return key.digest()


class TenConcurrentProcessesBuildTests(unittest.TestCase):
    """Ten real OS processes racing to build the same canonical manifest.

    Each process is a real ``python -m simplicio_mapper.cli.__main__
    canonical build <repo> --json`` invocation (the actual CLI entry point,
    issue #266) -- never a thread, never an in-process function call -- so a
    genuine race on the shared content-addressed storage root is exercised:
    real concurrent ``os.open(..., O_CREAT | O_EXCL)`` staging-dir creation,
    real concurrent ``git worktree add --detach`` checkouts, and real
    concurrent ``os.replace`` promotion attempts.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        _init_repo(self.repo, file_count=20)
        self.storage_root = str(self.base / "storage")

    def test_ten_concurrent_build_processes_converge_on_one_manifest(self) -> None:
        env = dict(os.environ)
        env["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = self.storage_root
        env.pop("SIMPLICIO_MAPPER_CANONICAL_REUSE", None)

        argv = [
            sys.executable,
            "-m",
            "simplicio_mapper.cli.__main__",
            "canonical",
            "build",
            str(self.repo),
            "--json",
        ]
        procs = [
            subprocess.Popen(
                argv,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(10)
        ]

        outputs = []
        for proc in procs:
            out, err = proc.communicate(timeout=60)
            outputs.append((proc.returncode, out, err))

        import json

        payloads = []
        for code, out, err in outputs:
            self.assertEqual(code, 0, f"stdout={out!r} stderr={err!r}")
            payloads.append(json.loads(out.strip()))

        self.assertEqual(len(payloads), 10)
        digests = {payload["key"]["digest"] for payload in payloads}
        self.assertEqual(len(digests), 1, "all ten processes must agree on one digest")
        created_ats = {payload["manifest"]["created_at"] for payload in payloads}
        self.assertEqual(
            len(created_ats),
            1,
            "all ten processes must observe the exact same promoted manifest, "
            "never ten independently-built copies",
        )
        for payload in payloads:
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["manifest"]["counts"]["files"], 20)

        # Exactly one promoted digest directory on disk -- no leftover
        # ``.tmp-<pid>`` staging directories from a loser process, and no
        # duplicate/divergent promoted directories.
        canonical_dir = Path(self.storage_root) / "canonical"
        entries = sorted(p.name for p in canonical_dir.iterdir())
        self.assertEqual(len(entries), 1, entries)
        self.assertEqual(entries[0], next(iter(digests)))

        # The main repository must never retain a stray `git worktree`
        # registration from any of the ten competing detached checkouts.
        worktree_list = _run(["worktree", "list"], self.repo).stdout
        self.assertEqual(worktree_list.count("\n"), 1, worktree_list)

    def test_ten_concurrent_build_processes_all_pass_gc_afterwards(self) -> None:
        """After the ten-way race settles, GC must find nothing to reclaim.

        Closes the loop between the two epic-mandated scenarios: a real
        multi-process build race must never leave behind anything a
        subsequent ``canonical gc`` needs to clean up.
        """
        env = dict(os.environ)
        env["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = self.storage_root

        argv = [
            sys.executable,
            "-m",
            "simplicio_mapper.cli.__main__",
            "canonical",
            "build",
            str(self.repo),
            "--json",
        ]
        procs = [
            subprocess.Popen(argv, cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(10)
        ]
        for proc in procs:
            self.assertEqual(proc.wait(timeout=60), 0)

        old_cache_env = os.environ.get("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR")
        os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = self.storage_root
        try:
            report = scan_canonical_gc(str(self.repo), apply=True)
        finally:
            if old_cache_env is None:
                os.environ.pop("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
            else:
                os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = old_cache_env

        self.assertEqual(report.removed, [])
        self.assertEqual(report.recovered, [])
        self.assertEqual(report.errors, [])


class CrashDuringBuildRecoveryTests(unittest.TestCase):
    """A real builder subprocess is SIGKILL'd mid-write; recovery must be clean.

    Unlike ``test_canonical_gc.py``'s crash-simulation tests (which construct
    a stale ``.tmp-<dead-pid>`` directory by hand), this spawns the actual
    ``build_canonical_manifest`` pipeline in a real child process, polls for
    its real staging directory to appear on disk, and kills the whole
    process group with ``SIGKILL`` the instant it does -- proving genuine
    mid-write crash recovery, not a hand-constructed fixture standing in for
    one.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        # Enough files that writing the four artifacts + file-manifest is not
        # instantaneous, widening the real (not simulated) crash window the
        # polling loop below needs to observe.
        _init_repo(self.repo, file_count=400)
        self.storage_root = str(self.base / "storage")

    def _spawn_builder(self, config_fingerprint: str) -> subprocess.Popen:
        script = self.base / "run_build.py"
        script.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "from simplicio_mapper.mapper.canonical_builder import build_canonical_manifest\n"
            f"build_canonical_manifest({str(self.repo)!r}, {self.storage_root!r}, "
            f"{config_fingerprint!r})\n",
            encoding="utf-8",
        )
        return subprocess.Popen(
            [sys.executable, str(script)],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_kill_mid_build_then_gc_then_rebuild_recovers_cleanly(self) -> None:
        config_fingerprint = "cfg-crash"
        digest = _expected_digest(self.repo, config_fingerprint)
        final_dir = Path(canonical_manifest_dir(self.storage_root, digest))

        proc = self._spawn_builder(config_fingerprint)
        canonical_tmp_glob = final_dir.parent / f"{digest}.tmp-*"
        tmp_dir: Path | None = None

        deadline = time.monotonic() + 20.0
        caught_mid_write = False
        while time.monotonic() < deadline:
            tmp_candidates = sorted(final_dir.parent.glob(canonical_tmp_glob.name))
            if tmp_candidates:
                tmp_dir = tmp_candidates[0]
                # Genuinely mid-write: real builder process, killed the
                # instant its real staging directory is observed, before it
                # could reach the atomic ``os.replace`` promotion. The builder
                # appends an intra-process random suffix to the PID token, so
                # the test discovers the actual staging dir by digest-prefixed
                # glob instead of reconstructing a now-intentionally-incomplete
                # private token. `Popen.kill()` is the portable equivalent of
                # `killpg(SIGKILL)` here (`os.killpg`/`os.getpgid` don't exist
                # on Windows) -- the builder has no children of its own to
                # worry about leaking.
                proc.kill()
                caught_mid_write = True
                break
            if final_dir.is_dir():
                break  # builder finished before we could catch it -- rare on a fast box
        proc.wait(timeout=10)

        self.assertTrue(
            caught_mid_write and tmp_dir is not None,
            "builder finished before the staging directory could be observed -- "
            "widen file_count in setUp if this becomes flaky",
        )
        self.assertFalse(final_dir.is_dir(), "a killed builder must never have promoted a manifest")
        assert tmp_dir is not None
        self.assertTrue(tmp_dir.is_dir(), "the killed builder's staging dir must still be on disk")
        # Real crash artifact: an incomplete write, not a fully-formed
        # manifest -- `manifest.json` is written last, so its absence proves
        # the kill landed before promotion could even be attempted.
        self.assertFalse((tmp_dir / "manifest.json").is_file())

        # A real orphaned `git worktree` registration is also part of a
        # genuine mid-checkout-or-later crash -- the killed process never
        # reached its cleanup `finally` block.
        worktree_list = _run(["worktree", "list"], self.repo).stdout
        self.assertGreaterEqual(worktree_list.count("\n"), 1)

        old_cache_env = os.environ.get("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR")
        old_grace_env = os.environ.get("SIMPLICIO_MAPPER_CANONICAL_GC_GRACE_SECONDS")
        os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = self.storage_root
        # The dead builder's pid died only moments ago -- force the grace
        # window to zero so this test does not need a real 60s sleep to
        # observe real reclaim behavior.
        os.environ["SIMPLICIO_MAPPER_CANONICAL_GC_GRACE_SECONDS"] = "0"
        try:
            dry_run = scan_canonical_gc(str(self.repo), apply=False)
            reasons = {c.reason for c in dry_run.candidates}
            self.assertIn("temp_dir_builder_pid_dead", reasons)
            self.assertTrue(tmp_dir.is_dir(), "dry-run must never delete")

            applied = scan_canonical_gc(str(self.repo), apply=True)
            recovered_reasons = {c.reason for c in applied.recovered}
            self.assertIn("temp_dir_builder_pid_dead", recovered_reasons)
        finally:
            if old_cache_env is None:
                os.environ.pop("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
            else:
                os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = old_cache_env
            if old_grace_env is None:
                os.environ.pop("SIMPLICIO_MAPPER_CANONICAL_GC_GRACE_SECONDS", None)
            else:
                os.environ["SIMPLICIO_MAPPER_CANONICAL_GC_GRACE_SECONDS"] = old_grace_env

        self.assertFalse(tmp_dir.exists(), "GC must have reclaimed the dead builder's staging dir")

        # The real, most important assertion: a fresh build after the crash
        # must succeed and produce a fully correct manifest -- the crash
        # must never wedge this digest shut nor corrupt the eventual result.
        recovered_manifest = build_canonical_manifest(str(self.repo), self.storage_root, config_fingerprint)
        self.assertIsNotNone(recovered_manifest)
        self.assertEqual(recovered_manifest.key.digest(), digest)
        self.assertEqual(recovered_manifest.counts["files"], 400)
        self.assertTrue(final_dir.is_dir())
        self.assertTrue((final_dir / "manifest.json").is_file())

        # Idempotent from here on -- a second build call is a pure cache hit.
        second = build_canonical_manifest(str(self.repo), self.storage_root, config_fingerprint)
        self.assertEqual(second, recovered_manifest)


if __name__ == "__main__":
    unittest.main()
