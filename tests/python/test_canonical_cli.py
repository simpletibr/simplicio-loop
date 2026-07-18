"""Unit/integration tests for ``simplicio-mapper canonical build|status`` (issue #266).

Parent: #263; epic: #236. Covers the read-safe CLI surface over the
already-merged canonical-map machinery: ``main`` sub-command dispatch,
``--json`` envelope shape/versioning, default-branch name variants, dirty
worktrees, privacy (no absolute path / raw remote URL leak), and the stable
error-receipt paths for a non-git directory, detached HEAD, and a corrupt
manifest already on disk. Every scenario runs against a real temporary git
repository (never a mocked subprocess), matching this repo's existing
``test_canonical_builder.py``/``test_mapper_canonical_identity.py`` style.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.cli._canonical import run_canonical_cli  # noqa: E402
from simplicio_mapper.cli._shared import (  # noqa: E402
    CANONICAL_BUILD_SCHEMA,
    CANONICAL_STATUS_SCHEMA,
)
from simplicio_mapper.mapper.canonical_storage import (  # noqa: E402
    CANONICAL_CACHE_DIR_ENV_VAR,
)


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


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


def _invoke_json(argv: list[str]) -> tuple[int, dict, str]:
    out = StringIO()
    with redirect_stdout(out):
        code = main(argv)
    raw = out.getvalue().strip()
    return code, json.loads(raw), raw


class CanonicalCliBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        # Isolate the content-addressed cache per test so concurrent test
        # processes/tests never collide on a shared common-git-dir cache.
        self._cache_dir = self.base / "canonical-cache"
        os.environ[CANONICAL_CACHE_DIR_ENV_VAR] = str(self._cache_dir)
        self.addCleanup(os.environ.pop, CANONICAL_CACHE_DIR_ENV_VAR, None)

    def test_build_main_default_branch(self) -> None:
        repo = self.base / "repo-main"
        _init_repo(repo, default_branch="main")
        code, payload, raw = _invoke_json(["canonical", "build", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        self.assertEqual(payload["schema"], CANONICAL_BUILD_SCHEMA)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["key"]["default_branch"], "main")
        self.assertFalse(payload["reused_existing"])
        self.assertEqual(payload["manifest"]["counts"]["files"], 2)

    def test_build_master_default_branch(self) -> None:
        repo = self.base / "repo-master"
        _init_repo(repo, default_branch="master")
        code, payload, raw = _invoke_json(["canonical", "build", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        self.assertEqual(payload["key"]["default_branch"], "master")

    def test_build_custom_default_branch_name(self) -> None:
        repo = self.base / "repo-trunk"
        _init_repo(repo, default_branch="trunk")
        code, payload, raw = _invoke_json(["canonical", "build", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        self.assertEqual(payload["key"]["default_branch"], "trunk")

    def test_build_is_idempotent_second_call_reuses(self) -> None:
        repo = self.base / "repo-idem"
        _init_repo(repo)
        code1, first, raw1 = _invoke_json(["canonical", "build", str(repo), "--json"])
        code2, second, raw2 = _invoke_json(["canonical", "build", str(repo), "--json"])
        self.assertEqual(code1, 0, raw1)
        self.assertEqual(code2, 0, raw2)
        self.assertFalse(first["reused_existing"])
        self.assertTrue(second["reused_existing"])
        self.assertEqual(first["key"]["digest"], second["key"]["digest"])
        self.assertEqual(first["manifest"]["created_at"], second["manifest"]["created_at"])

    def test_build_dirty_worktree_still_builds_clean_commit(self) -> None:
        repo = self.base / "repo-dirty"
        _init_repo(repo)
        (repo / "README.md").write_text("locally edited\n", encoding="utf-8")
        (repo / "src" / "untracked.py").write_text("X = 1\n", encoding="utf-8")
        code, payload, raw = _invoke_json(["canonical", "build", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        self.assertEqual(payload["status"], "ok")
        # Dirty state never leaks into the canonical count -- still 2 files
        # (README.md + src/mod.py), not 3.
        self.assertEqual(payload["manifest"]["counts"]["files"], 2)

    def test_build_does_not_touch_dot_simplicio(self) -> None:
        repo = self.base / "repo-isolated"
        _init_repo(repo)
        _invoke_json(["canonical", "build", str(repo), "--json"])
        self.assertFalse((repo / ".simplicio").exists())

    def test_build_non_git_directory_returns_stable_error_receipt(self) -> None:
        plain = self.base / "plain-dir"
        plain.mkdir()
        code, payload, raw = _invoke_json(["canonical", "build", str(plain), "--json"])
        self.assertEqual(code, 1, raw)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["reason"], "not_a_git_repository_or_git_unavailable")


class CanonicalCliStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self._cache_dir = self.base / "canonical-cache"
        os.environ[CANONICAL_CACHE_DIR_ENV_VAR] = str(self._cache_dir)
        self.addCleanup(os.environ.pop, CANONICAL_CACHE_DIR_ENV_VAR, None)

    def test_status_before_build_reports_no_manifest(self) -> None:
        repo = self.base / "repo-status-fresh"
        _init_repo(repo)
        code, payload, raw = _invoke_json(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        self.assertEqual(payload["schema"], CANONICAL_STATUS_SCHEMA)
        self.assertFalse(payload["freshness"]["manifest_exists"])
        self.assertFalse(payload["freshness"]["matches_current_key"])
        self.assertEqual(payload["freshness"]["invalidation_reason"], "no_manifest_for_current_key")
        self.assertIsNone(payload["overlay"])

    def test_status_never_writes_any_manifest(self) -> None:
        repo = self.base / "repo-status-readonly"
        _init_repo(repo)
        _invoke_json(["canonical", "status", str(repo), "--json"])
        # No canonical cache directory should have been created by a
        # read-only `status` call.
        self.assertFalse(self._cache_dir.exists())

    def test_status_after_build_reports_fresh_and_overlay(self) -> None:
        repo = self.base / "repo-status-fresh-after-build"
        _init_repo(repo)
        _invoke_json(["canonical", "build", str(repo), "--json"])
        code, payload, raw = _invoke_json(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        self.assertTrue(payload["freshness"]["manifest_exists"])
        self.assertTrue(payload["freshness"]["matches_current_key"])
        self.assertIsNone(payload["freshness"]["invalidation_reason"])
        self.assertIsNotNone(payload["overlay"])
        self.assertTrue(payload["overlay"]["present"])
        self.assertFalse(payload["overlay"]["dirty"])
        self.assertEqual(payload["overlay"]["files_remapped"], 0)
        self.assertEqual(payload["overlay"]["files_reused"], 2)

    def test_status_reports_dirty_overlay(self) -> None:
        repo = self.base / "repo-status-dirty"
        _init_repo(repo)
        _invoke_json(["canonical", "build", str(repo), "--json"])
        (repo / "README.md").write_text("edited locally\n", encoding="utf-8")
        code, payload, raw = _invoke_json(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        self.assertTrue(payload["overlay"]["dirty"])
        self.assertEqual(payload["overlay"]["files_remapped"], 1)
        self.assertEqual(payload["overlay"]["files_reused"], 1)

    def test_status_non_git_directory_returns_stable_error_receipt(self) -> None:
        plain = self.base / "plain-dir"
        plain.mkdir()
        code, payload, raw = _invoke_json(["canonical", "status", str(plain), "--json"])
        self.assertEqual(code, 1, raw)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["reason"], "not_a_git_repository_or_git_unavailable")
        self.assertFalse(payload["git"]["is_git_repository"])

    def test_status_detached_head_still_resolves(self) -> None:
        repo = self.base / "repo-detached"
        _init_repo(repo)
        head_sha = _run(["rev-parse", "HEAD"], repo).stdout.strip()
        _run(["checkout", "--detach", head_sha], repo)
        code, payload, raw = _invoke_json(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["git"]["detached_head"])
        self.assertEqual(payload["key"]["default_branch"], "main")
        self.assertEqual(payload["key"]["commit_sha"], head_sha)

    def test_status_reports_corrupt_manifest_on_disk(self) -> None:
        repo = self.base / "repo-corrupt"
        _init_repo(repo)
        code, built, raw = _invoke_json(["canonical", "build", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        digest = built["key"]["digest"]
        manifest_path = self._cache_dir / "canonical" / digest / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest_path.write_text("{not valid json", encoding="utf-8")

        code2, payload, raw2 = _invoke_json(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code2, 0, raw2)
        self.assertTrue(payload["freshness"]["manifest_exists"])
        self.assertFalse(payload["freshness"]["matches_current_key"])
        self.assertEqual(payload["freshness"]["invalidation_reason"], "corrupt_manifest")

    def test_status_privacy_no_absolute_path_or_remote_url_leak(self) -> None:
        repo = self.base / "repo-privacy-check"
        _init_repo(repo)
        secret_remote = "https://example-secret-host.invalid/wesleysimplicio/private-repo.git"
        _run(["remote", "add", "origin", secret_remote], repo)

        code, _payload, raw = _invoke_json(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        self.assertNotIn(str(repo), raw)
        self.assertNotIn(str(repo).replace("\\", "/"), raw)
        self.assertNotIn(secret_remote, raw)
        self.assertNotIn("example-secret-host.invalid", raw)
        self.assertNotIn(str(self._cache_dir), raw)

    def test_build_privacy_no_absolute_path_or_remote_url_leak(self) -> None:
        repo = self.base / "repo-privacy-check-build"
        _init_repo(repo)
        secret_remote = "git@example-secret-host.invalid:wesleysimplicio/private-repo.git"
        _run(["remote", "add", "origin", secret_remote], repo)

        code, _payload, raw = _invoke_json(["canonical", "build", str(repo), "--json"])
        self.assertEqual(code, 0, raw)
        self.assertNotIn(str(repo), raw)
        self.assertNotIn(str(repo).replace("\\", "/"), raw)
        self.assertNotIn(secret_remote, raw)
        self.assertNotIn("example-secret-host.invalid", raw)
        self.assertNotIn(str(self._cache_dir), raw)


class CanonicalCliDispatchTests(unittest.TestCase):
    """Cover CLI-surface dispatch itself: --help, unknown sub-command, human mode."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        os.environ[CANONICAL_CACHE_DIR_ENV_VAR] = str(self.base / "cache")
        self.addCleanup(os.environ.pop, CANONICAL_CACHE_DIR_ENV_VAR, None)

    def test_help_via_main(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_canonical_help_prints_usage_and_exits_zero(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = run_canonical_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("canonical build", out.getvalue())
        self.assertIn("canonical status", out.getvalue())

    def test_unknown_subcommand_exits_2(self) -> None:
        code = run_canonical_cli(["bogus", "."])
        self.assertEqual(code, 2)

    def test_no_args_prints_usage_and_exits_0(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = run_canonical_cli([])
        self.assertEqual(code, 0)
        self.assertIn("usage:", out.getvalue())

    def test_status_human_mode_smoke(self) -> None:
        repo = self.base / "repo-human"
        _init_repo(repo)
        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "status", str(repo)])
        self.assertEqual(code, 0)
        self.assertIn("canonical status", out.getvalue())

    def test_help_lists_canonical_subcommands(self) -> None:
        out = StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            main(["--help"])
        text = out.getvalue()
        self.assertIn("canonical build", text)
        self.assertIn("canonical status", text)

    def test_build_human_mode_smoke(self) -> None:
        repo = self.base / "repo-human-build"
        _init_repo(repo)
        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "build", str(repo)])
        self.assertEqual(code, 0)
        self.assertIn("canonical build ok", out.getvalue())
        self.assertIn("files=2", out.getvalue())

    def test_error_human_mode_smoke(self) -> None:
        plain = self.base / "plain-human"
        plain.mkdir()
        code = run_canonical_cli(["status", str(plain)])
        self.assertEqual(code, 1)

    def test_root_flag_used_instead_of_positional(self) -> None:
        repo = self.base / "repo-root-flag"
        _init_repo(repo)
        out = StringIO()
        with redirect_stdout(out):
            code = run_canonical_cli(["status", "--root", str(repo), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue().strip())
        self.assertEqual(payload["status"], "ok")

    def test_root_flag_missing_value_exits_2(self) -> None:
        code = run_canonical_cli(["status", "--root"])
        self.assertEqual(code, 2)

    def test_unknown_option_exits_2(self) -> None:
        code = run_canonical_cli(["status", ".", "--bogus"])
        self.assertEqual(code, 2)

    def test_build_subcommand_help_exits_0(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = run_canonical_cli(["build", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage:", out.getvalue())


if __name__ == "__main__":
    unittest.main()
