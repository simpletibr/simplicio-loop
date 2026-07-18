"""End-to-end CLI coverage for `simplicio-mapper canonical build|status`
(`simplicio_mapper/cli/_canonical.py`) -- issue #266.

Drives the real CLI entry point (`main()`) against real, throwaway git
repositories -- never mocks the git subprocess boundary -- and asserts:

* `build`/`status` work against `main`, `master`, and a custom default
  branch name.
* `status` reports a dirty worktree overlay correctly and never builds or
  writes anything.
* `--json` mode emits a schema-versioned, machine-parseable envelope.
* The status/build receipt never leaks an absolute path, a raw remote URL,
  or file content -- the explicit privacy requirement from the issue.
* Non-git directory, detached HEAD, unavailable `git`, and a corrupt
  `manifest.json` all degrade to a stable fallback receipt, never a
  traceback.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main
from simplicio_mapper.cli._canonical import (
    CANONICAL_BUILD_SCHEMA,
    CANONICAL_STATUS_SCHEMA,
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


class CanonicalCliBranchMatrixTests(unittest.TestCase):
    """`build` + `status` against main/master/custom default branch names."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def _build_and_status(self, repo: Path) -> tuple[dict, dict]:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "build", str(repo), "--json"])
        self.assertEqual(code, 0, out.getvalue())
        build_receipt = json.loads(out.getvalue())

        out2 = StringIO()
        with redirect_stdout(out2):
            code2 = main(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code2, 0, out2.getvalue())
        status_receipt = json.loads(out2.getvalue())
        return build_receipt, status_receipt

    def test_main_branch(self) -> None:
        repo = self.base / "repo-main"
        _init_repo(repo, default_branch="main")
        build_receipt, status_receipt = self._build_and_status(repo)
        self.assertEqual(build_receipt["schema"], CANONICAL_BUILD_SCHEMA)
        self.assertEqual(build_receipt["status"], "ok")
        self.assertFalse(build_receipt["reused"])
        self.assertEqual(build_receipt["key"]["default_branch"], "main")
        self.assertEqual(status_receipt["schema"], CANONICAL_STATUS_SCHEMA)
        self.assertEqual(status_receipt["status"], "ok")
        self.assertEqual(status_receipt["key"]["default_branch"], "main")
        self.assertEqual(status_receipt["key"]["key_digest"], build_receipt["key"]["key_digest"])

    def test_master_branch(self) -> None:
        repo = self.base / "repo-master"
        _init_repo(repo, default_branch="master")
        build_receipt, status_receipt = self._build_and_status(repo)
        self.assertEqual(build_receipt["key"]["default_branch"], "master")
        self.assertEqual(status_receipt["key"]["default_branch"], "master")

    def test_custom_branch_name(self) -> None:
        repo = self.base / "repo-custom"
        _init_repo(repo, default_branch="trunk-canonical")
        build_receipt, status_receipt = self._build_and_status(repo)
        self.assertEqual(build_receipt["key"]["default_branch"], "trunk-canonical")
        self.assertEqual(status_receipt["key"]["default_branch"], "trunk-canonical")

    def test_second_build_call_reuses_existing_manifest(self) -> None:
        repo = self.base / "repo-reuse"
        _init_repo(repo)
        first, _ = self._build_and_status(repo)
        self.assertFalse(first["reused"])
        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "build", str(repo), "--json"])
        self.assertEqual(code, 0)
        second = json.loads(out.getvalue())
        self.assertTrue(second["reused"])
        self.assertEqual(second["key"]["key_digest"], first["key"]["key_digest"])


class CanonicalCliStatusOverlayTests(unittest.TestCase):
    """`status` correctly reports a dirty worktree overlay, read-only."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_status_reports_dirty_overlay_without_writing_anything(self) -> None:
        repo = self.base / "repo-dirty"
        _init_repo(repo)
        out = StringIO()
        with redirect_stdout(out):
            main(["canonical", "build", str(repo), "--json"])
        build_receipt = json.loads(out.getvalue())

        # Dirty the real worktree: modify a tracked file, add an untracked one.
        (repo / "src" / "mod.py").write_text("def foo():\n    return 2\n", encoding="utf-8")
        (repo / "src" / "new_thing.py").write_text("NEW = True\n", encoding="utf-8")

        out2 = StringIO()
        with redirect_stdout(out2):
            code = main(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code, 0)
        status_receipt = json.loads(out2.getvalue())

        self.assertTrue(status_receipt["overlay"]["dirty"])
        self.assertEqual(status_receipt["overlay"]["changed_files_count"], 2)
        self.assertTrue(status_receipt["freshness"]["worktree_dirty"])
        # Same canonical manifest -- status must not have rebuilt anything.
        self.assertEqual(status_receipt["key"]["key_digest"], build_receipt["key"]["key_digest"])

    def test_status_clean_worktree_reports_no_overlay_delta(self) -> None:
        repo = self.base / "repo-clean"
        _init_repo(repo)
        out = StringIO()
        with redirect_stdout(out):
            main(["canonical", "build", str(repo), "--json"])

        out2 = StringIO()
        with redirect_stdout(out2):
            code = main(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code, 0)
        status_receipt = json.loads(out2.getvalue())
        self.assertFalse(status_receipt["overlay"]["dirty"])
        self.assertEqual(status_receipt["overlay"]["changed_files_count"], 0)
        self.assertEqual(status_receipt["overlay"]["tombstones_count"], 0)
        self.assertTrue(status_receipt["freshness"]["worktree_same_commit_as_canonical"])


class CanonicalCliPrivacySchemaTests(unittest.TestCase):
    """Schema + privacy assertions on both receipts (issue #266 hard requirement)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_status_receipt_never_leaks_absolute_path_or_remote_url_or_content(self) -> None:
        repo = self.base / "repo-privacy"
        _init_repo(repo)
        _run(["remote", "add", "origin", "https://example.invalid/acme/super-secret-repo.git"], repo)
        (repo / "SECRET.md").write_text("top-secret-file-content-marker\n", encoding="utf-8")
        _run(["add", "."], repo)
        _run(["commit", "-m", "add secret"], repo)

        out = StringIO()
        with redirect_stdout(out):
            main(["canonical", "build", str(repo), "--json"])
        out2 = StringIO()
        with redirect_stdout(out2):
            code = main(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code, 0)
        raw = out2.getvalue()
        receipt = json.loads(raw)

        # Schema/version present and correct.
        self.assertEqual(receipt["schema"], CANONICAL_STATUS_SCHEMA)
        self.assertEqual(receipt["schema_version"], 1)

        # No absolute filesystem path anywhere in the serialized receipt.
        self.assertNotIn(str(repo), raw)
        self.assertNotIn(str(self.base), raw)
        # No raw remote URL.
        self.assertNotIn("example.invalid", raw)
        self.assertNotIn("super-secret-repo", raw)
        # No file content.
        self.assertNotIn("top-secret-file-content-marker", raw)
        # No storage_root / worktree_path keys at all (would themselves be
        # absolute paths even if not caught by the substring checks above).
        self.assertNotIn("storage_root", raw)
        self.assertNotIn("worktree_path", raw)
        self.assertNotIn("repo_identity", raw)

        # Only a short (12-char) commit prefix is ever exposed, never the
        # full 40-char SHA.
        commit_short = receipt["key"]["commit_sha_short"]
        self.assertEqual(len(commit_short), 12)

    def test_build_receipt_never_leaks_absolute_path_or_remote_url(self) -> None:
        repo = self.base / "repo-privacy-build"
        _init_repo(repo)
        _run(["remote", "add", "origin", "https://example.invalid/acme/other-secret.git"], repo)

        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "build", str(repo), "--json"])
        self.assertEqual(code, 0)
        raw = out.getvalue()
        receipt = json.loads(raw)
        self.assertEqual(receipt["schema"], CANONICAL_BUILD_SCHEMA)
        self.assertNotIn(str(repo), raw)
        self.assertNotIn("example.invalid", raw)
        self.assertNotIn("other-secret", raw)
        self.assertNotIn("storage_root", raw)
        self.assertNotIn("repo_identity", raw)


class CanonicalCliFallbackTests(unittest.TestCase):
    """Non-git dir, detached HEAD, git-unavailable, invalid manifest -- all stable, no traceback."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_non_git_directory_returns_stable_fallback(self) -> None:
        not_git = self.base / "not-a-repo"
        not_git.mkdir()
        (not_git / "file.txt").write_text("hi\n", encoding="utf-8")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "status", str(not_git), "--json"])
        self.assertEqual(code, 1)
        receipt = json.loads(out.getvalue())
        self.assertEqual(receipt["status"], "fallback")
        self.assertEqual(receipt["reason"], "not_a_git_repository")
        self.assertNotIn("key", receipt)

        out2 = StringIO()
        with redirect_stdout(out2):
            code2 = main(["canonical", "build", str(not_git), "--json"])
        self.assertEqual(code2, 1)
        build_receipt = json.loads(out2.getvalue())
        self.assertEqual(build_receipt["status"], "fallback")
        self.assertEqual(build_receipt["reason"], "not_a_git_repository")

    def test_detached_head_worktree_still_produces_a_stable_ok_receipt(self) -> None:
        repo = self.base / "repo-detached"
        _init_repo(repo)
        out = StringIO()
        with redirect_stdout(out):
            main(["canonical", "build", str(repo), "--json"])

        _run(["checkout", "--detach", "HEAD"], repo)

        out2 = StringIO()
        err2 = StringIO()
        with redirect_stdout(out2), redirect_stderr(err2):
            code = main(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code, 0, err2.getvalue())
        receipt = json.loads(out2.getvalue())
        self.assertEqual(receipt["status"], "ok")
        self.assertIsNotNone(receipt["freshness"]["worktree_head_sha_short"])
        self.assertEqual(err2.getvalue(), "")

    def test_git_unavailable_returns_stable_fallback_not_traceback(self) -> None:
        repo = self.base / "repo-no-git-binary"
        _init_repo(repo)

        from simplicio_mapper.cli import _canonical

        original = _canonical._git_available
        _canonical._git_available = lambda: False
        try:
            out = StringIO()
            with redirect_stdout(out):
                code = main(["canonical", "status", str(repo), "--json"])
            self.assertEqual(code, 1)
            receipt = json.loads(out.getvalue())
            self.assertEqual(receipt["status"], "fallback")
            self.assertEqual(receipt["reason"], "git_unavailable")
        finally:
            _canonical._git_available = original

    def test_invalid_manifest_json_returns_stable_fallback(self) -> None:
        repo = self.base / "repo-invalid-manifest"
        _init_repo(repo)
        out = StringIO()
        with redirect_stdout(out):
            main(["canonical", "build", str(repo), "--json"])
        build_receipt = json.loads(out.getvalue())
        digest = build_receipt["key"]["key_digest"]

        from simplicio_mapper.mapper.canonical_identity import resolve_common_git_dir
        from simplicio_mapper.mapper.canonical_storage import (
            canonical_manifest_dir,
            resolve_canonical_cache_root,
        )

        common_git_dir = resolve_common_git_dir(str(repo))
        cache_root = resolve_canonical_cache_root(common_git_dir)
        digest_dir = Path(canonical_manifest_dir(cache_root, digest))
        manifest_path = digest_dir / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest_path.write_text("{not valid json", encoding="utf-8")

        out2 = StringIO()
        with redirect_stdout(out2):
            code = main(["canonical", "status", str(repo), "--json"])
        self.assertEqual(code, 1)
        receipt = json.loads(out2.getvalue())
        self.assertEqual(receipt["status"], "fallback")
        self.assertEqual(receipt["reason"], "invalid_manifest")


class CanonicalCliHelpTests(unittest.TestCase):
    def test_top_level_help_documents_canonical_subcommands(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        text = out.getvalue()
        self.assertIn("canonical build", text)
        self.assertIn("canonical status", text)
        self.assertIn("simplicio.canonical-build/v1", text)
        self.assertIn("simplicio.canonical-status/v1", text)

    def test_canonical_help_subcommand(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("canonical build", out.getvalue())
        self.assertIn("canonical status", out.getvalue())

    def test_unknown_canonical_subcommand_is_rejected(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["canonical", "gc", "/tmp"])
        self.assertEqual(code, 2)
        self.assertIn("unknown canonical sub-command", err.getvalue())


class CanonicalCliUnitReceiptTests(unittest.TestCase):
    """Direct unit coverage of the receipt-building functions (no CLI dispatch)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_status_receipt_function_directly(self) -> None:
        from simplicio_mapper.cli._canonical import _DEFAULT_CONFIG_FINGERPRINT, _status_receipt

        repo = self.base / "repo-unit"
        _init_repo(repo)
        receipt = _status_receipt(str(repo), _DEFAULT_CONFIG_FINGERPRINT)
        self.assertEqual(receipt["status"], "fallback")
        self.assertEqual(receipt["reason"], "no_canonical_manifest")

    def test_build_receipt_function_directly(self) -> None:
        from simplicio_mapper.cli._canonical import _DEFAULT_CONFIG_FINGERPRINT, _build_receipt

        repo = self.base / "repo-unit-build"
        _init_repo(repo)
        receipt = _build_receipt(str(repo), _DEFAULT_CONFIG_FINGERPRINT)
        self.assertEqual(receipt["status"], "ok")
        self.assertFalse(receipt["reused"])


if __name__ == "__main__":
    unittest.main()
