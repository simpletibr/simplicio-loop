"""Tests for ``simplicio_mapper.mapper.canonical_verify`` (issue #267).

Proves ``canonical verify``'s independent-parity claim against real git
repositories and a real ``build_canonical_manifest``/``compute_worktree_overlay``
chain -- never mocks on the Git/overlay/remap seam. Covers:

- clean worktree (no overlay delta) -> match
- staged, unstaged, untracked, renamed, and deleted changes -> match (the
  overlay correctly reconciles all five against the same canonical base)
- divergent (committed-ahead) and detached-HEAD worktrees -> match
- non-git fallback -> fails closed with a precise reason
- invalid/missing canonical contract (``file_manifest`` artifact key absent)
  -> fails closed, never declares parity from missing data
- a genuine mutation (canonical artifact corrupted after build) -> the tool
  actually detects the divergence (mismatch), proving it does not always
  report "match"
- unit coverage of the receipt digest/shape helpers
- CLI subprocess integration: ``python -m simplicio_mapper.cli canonical
  verify <root> --json``, including the mutation case via subprocess too

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli._canonical import _DEFAULT_CONFIG_FINGERPRINT as _CLI_DEFAULT_FINGERPRINT  # noqa: E402
from simplicio_mapper.cli._canonical import run_canonical_cli  # noqa: E402
from simplicio_mapper.mapper.canonical_builder import build_canonical_manifest  # noqa: E402
from simplicio_mapper.mapper.canonical_storage import canonical_manifest_dir  # noqa: E402
from simplicio_mapper.mapper.canonical_verify import (  # noqa: E402
    CANONICAL_VERIFY_SCHEMA,
    CANONICAL_VERIFY_SCHEMA_VERSION,
    _receipt_digest,
    verify_canonical_parity,
)


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _init_repo(path: Path, *, default_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "--initial-branch", default_branch], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test User"], path)
    (path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (path / "b.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    (path / "c.py").write_text("def h():\n    return 3\n", encoding="utf-8")
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)


class CanonicalVerifyReceiptShapeTests(unittest.TestCase):
    """Unit coverage: the receipt digest helper and schema constants."""

    def test_receipt_digest_is_stable_and_order_independent_of_dict_construction(self) -> None:
        effective = {"a.py": "h1", "b.py": "h2"}
        remap = {"a.py": "h1", "b.py": "h2"}
        first = _receipt_digest("key-digest", effective, remap)
        second = _receipt_digest(
            "key-digest",
            {"b.py": "h2", "a.py": "h1"},
            {"b.py": "h2", "a.py": "h1"},
        )
        self.assertEqual(first, second)

    def test_receipt_digest_changes_when_content_differs(self) -> None:
        base = _receipt_digest("key", {"a.py": "h1"}, {"a.py": "h1"})
        changed = _receipt_digest("key", {"a.py": "h1"}, {"a.py": "h2"})
        self.assertNotEqual(base, changed)

    def test_receipt_digest_is_a_plain_hex_string(self) -> None:
        digest = _receipt_digest("key", {"rel/x.py": "h1"}, {"rel/x.py": "h1"})
        self.assertRegex(digest, r"^[0-9a-f]{48}$")


class CanonicalVerifyIntegrationTests(unittest.TestCase):
    """Real builder + real overlay + real remap, against real temp git repos."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.storage_root = str(self.base / "storage")

    def _verify(self, repo: Path, **kwargs) -> dict:
        return verify_canonical_parity(str(repo), storage_root=self.storage_root, **kwargs)

    def test_clean_worktree_matches(self) -> None:
        repo = self.base / "repo-clean"
        _init_repo(repo)
        receipt = self._verify(repo)
        self.assertEqual(receipt["schema"], CANONICAL_VERIFY_SCHEMA)
        self.assertEqual(receipt["schema_version"], CANONICAL_VERIFY_SCHEMA_VERSION)
        self.assertEqual(receipt["result"], "match")
        self.assertIsNone(receipt["failure_reason"])
        self.assertEqual(receipt["counts"]["mismatches"], 0)
        self.assertEqual(receipt["counts"]["canonical_files"], 3)

    def test_staged_modification_matches(self) -> None:
        repo = self.base / "repo-staged"
        _init_repo(repo)
        (repo / "a.py").write_text("def f():\n    return 100\n", encoding="utf-8")
        _run_git(["add", "a.py"], repo)
        receipt = self._verify(repo)
        self.assertEqual(receipt["result"], "match", receipt)
        self.assertGreaterEqual(receipt["counts"]["overlay_changed_files"], 1)

    def test_unstaged_modification_matches(self) -> None:
        repo = self.base / "repo-unstaged"
        _init_repo(repo)
        (repo / "b.py").write_text("def g():\n    return 200\n", encoding="utf-8")
        receipt = self._verify(repo)
        self.assertEqual(receipt["result"], "match", receipt)

    def test_untracked_addition_matches(self) -> None:
        repo = self.base / "repo-untracked"
        _init_repo(repo)
        (repo / "new_thing.py").write_text("NEW = True\n", encoding="utf-8")
        receipt = self._verify(repo)
        self.assertEqual(receipt["result"], "match", receipt)
        self.assertEqual(receipt["counts"]["canonical_files"] + 1, receipt["counts"]["effective_files"])

    def test_renamed_file_matches(self) -> None:
        repo = self.base / "repo-renamed"
        _init_repo(repo)
        _run_git(["mv", "c.py", "renamed.py"], repo)
        receipt = self._verify(repo)
        self.assertEqual(receipt["result"], "match", receipt)

    def test_deleted_file_matches(self) -> None:
        repo = self.base / "repo-deleted"
        _init_repo(repo)
        (repo / "c.py").unlink()
        receipt = self._verify(repo)
        self.assertEqual(receipt["result"], "match", receipt)
        self.assertEqual(receipt["counts"]["effective_files"], receipt["counts"]["canonical_files"] - 1)

    def test_mixed_staged_unstaged_untracked_rename_delete_all_together_matches(self) -> None:
        repo = self.base / "repo-mixed"
        _init_repo(repo)
        (repo / "a.py").write_text("def f():\n    return 100\n", encoding="utf-8")
        _run_git(["add", "a.py"], repo)  # staged
        (repo / "b.py").write_text("def g():\n    return 200\n", encoding="utf-8")  # unstaged
        (repo / "new_thing.py").write_text("NEW = True\n", encoding="utf-8")  # untracked
        (repo / "d.py").write_text("D = 1\n", encoding="utf-8")
        _run_git(["add", "d.py"], repo)
        _run_git(["commit", "-m", "add d for rename source"], repo)
        _run_git(["mv", "d.py", "renamed.py"], repo)  # renamed (staged)
        (repo / "c.py").unlink()  # deleted
        receipt = self._verify(repo)
        self.assertEqual(receipt["result"], "match", receipt)
        self.assertEqual(receipt["counts"]["mismatches"], 0)

    def test_divergent_committed_ahead_worktree_matches(self) -> None:
        repo = self.base / "repo-divergent"
        _init_repo(repo)
        _run_git(["checkout", "-b", "feature"], repo)
        (repo / "feature_only.py").write_text("FEATURE = True\n", encoding="utf-8")
        _run_git(["add", "."], repo)
        _run_git(["commit", "-m", "feature work, diverges from main"], repo)
        receipt = self._verify(repo)
        self.assertEqual(receipt["result"], "match", receipt)
        self.assertEqual(receipt["counts"]["canonical_files"], 3)
        self.assertEqual(receipt["counts"]["effective_files"], 4)

    def test_detached_head_worktree_matches(self) -> None:
        repo = self.base / "repo-detached"
        _init_repo(repo)
        head = _run_git(["rev-parse", "HEAD"], repo).stdout.strip()
        (repo / "extra.py").write_text("EXTRA = 1\n", encoding="utf-8")
        _run_git(["add", "."], repo)
        _run_git(["commit", "-m", "second commit"], repo)
        _run_git(["checkout", head], repo)  # now detached at the first commit
        self.assertIn(
            "HEAD detached",
            _run_git(["status"], repo).stdout,
        )
        receipt = self._verify(repo)
        self.assertEqual(receipt["result"], "match", receipt)

    def test_non_git_directory_fails_closed(self) -> None:
        plain = self.base / "plain"
        plain.mkdir()
        receipt = self._verify(plain)
        self.assertEqual(receipt["result"], "fail")
        self.assertEqual(receipt["failure_reason"], "not_a_git_repository")
        self.assertEqual(receipt["counts"], {})

    def test_invalid_canonical_contract_missing_file_manifest_fails_closed(self) -> None:
        """Corrupt the canonical manifest's own contract (no file_manifest key).

        Must never fall through to a false "match" just because the digest
        maps end up empty/equal on both sides.
        """
        repo = self.base / "repo-invalid-contract"
        _init_repo(repo)
        manifest = build_canonical_manifest(str(repo), self.storage_root, "default")
        self.assertIsNotNone(manifest)
        digest_dir = Path(canonical_manifest_dir(self.storage_root, manifest.key.digest()))
        manifest_json_path = digest_dir / "manifest.json"
        payload = json.loads(manifest_json_path.read_text(encoding="utf-8"))
        del payload["artifact_paths"]["file_manifest"]
        manifest_json_path.write_text(json.dumps(payload), encoding="utf-8")

        receipt = self._verify(repo)
        self.assertEqual(receipt["result"], "fail")
        self.assertEqual(
            receipt["failure_reason"], "canonical_manifest_missing_file_manifest_artifact"
        )

    def test_mutation_that_must_diverge_is_detected(self) -> None:
        """Corrupt an already-built canonical artifact's recorded hash -- must mismatch.

        This is the required "mutation case" (issue #267 AC): proves the
        tool is not hardwired to always report parity -- a real, deliberate
        divergence between the canonical side and the live worktree is
        actually caught.
        """
        repo = self.base / "repo-mutated"
        _init_repo(repo)
        manifest = build_canonical_manifest(str(repo), self.storage_root, "default")
        self.assertIsNotNone(manifest)
        digest_dir = Path(canonical_manifest_dir(self.storage_root, manifest.key.digest()))
        file_manifest_path = digest_dir / manifest.artifact_paths["file_manifest"]
        lines = file_manifest_path.read_text(encoding="utf-8").splitlines()
        mutated_lines = []
        for line in lines:
            entry = json.loads(line)
            if entry["path"] == "a.py":
                entry["file_hash"] = "0" * 64  # deliberately wrong
            mutated_lines.append(json.dumps(entry))
        file_manifest_path.write_text("\n".join(mutated_lines) + "\n", encoding="utf-8")

        receipt = self._verify(repo)
        self.assertEqual(receipt["result"], "mismatch")
        self.assertEqual(receipt["failure_reason"], "digest_mismatch")
        self.assertEqual(receipt["counts"]["mismatches"], 1)
        paths = {item["path"] for item in receipt["mismatches"]}
        self.assertIn("a.py", paths)

    def test_file_limit_bounds_comparison_deterministically(self) -> None:
        repo = self.base / "repo-limit"
        _init_repo(repo)
        receipt_full = self._verify(repo, file_limit=0)
        receipt_bounded = self._verify(repo, file_limit=1)
        self.assertEqual(receipt_full["result"], "match")
        self.assertEqual(receipt_bounded["counts"]["effective_files"], 1)
        self.assertEqual(receipt_bounded["counts"]["remap_files"], 1)
        # Still a real, deterministic parity check over the bounded subset.
        self.assertEqual(receipt_bounded["result"], "match")

    def test_receipt_never_contains_absolute_paths_or_worktree_path(self) -> None:
        repo = self.base / "repo-no-leak"
        _init_repo(repo)
        receipt = self._verify(repo)
        serialized = json.dumps(receipt)
        self.assertNotIn(str(repo), serialized)
        self.assertNotIn(self.storage_root, serialized)


class CanonicalCliInProcessTests(unittest.TestCase):
    """In-process coverage of ``run_canonical_cli``'s own argv parsing/dispatch.

    Complements ``CanonicalVerifyCliIntegrationTests`` below (real
    subprocess) with fast, in-process coverage of the parsing/error branches
    that don't need a second process to prove.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.storage_root = str(self.base / "storage")

    def test_no_subcommand_prints_usage_and_returns_two(self) -> None:
        # Once #266/#268 merged in alongside this issue's `verify`, a bare
        # `canonical` (no sub-command) prints the unified usage/help text
        # and exits 0 -- same convention as `canonical --help`.
        self.assertEqual(run_canonical_cli([]), 0)

    def test_unknown_subcommand_returns_two(self) -> None:
        self.assertEqual(run_canonical_cli(["bogus"]), 2)

    def test_verify_help_returns_zero(self) -> None:
        self.assertEqual(run_canonical_cli(["verify", "--help"]), 0)

    def test_verify_unknown_option_returns_two(self) -> None:
        self.assertEqual(run_canonical_cli(["verify", "--nope"]), 2)

    def test_verify_invalid_limit_returns_two(self) -> None:
        self.assertEqual(run_canonical_cli(["verify", ".", "--limit", "not-a-number"]), 2)

    def test_verify_json_and_options_dispatch_to_match(self) -> None:
        repo = self.base / "repo-inprocess"
        _init_repo(repo)
        code = run_canonical_cli(
            [
                "verify",
                str(repo),
                "--json",
                "--storage-root",
                self.storage_root,
                "--config-fingerprint",
                "cfg-inprocess",
                "--limit",
                "100",
            ]
        )
        self.assertEqual(code, 0)

    def test_verify_human_output_on_mismatch_returns_one(self) -> None:
        repo = self.base / "repo-inprocess-mismatch"
        _init_repo(repo)
        manifest = build_canonical_manifest(str(repo), self.storage_root, _CLI_DEFAULT_FINGERPRINT)
        self.assertIsNotNone(manifest)
        digest_dir = Path(canonical_manifest_dir(self.storage_root, manifest.key.digest()))
        file_manifest_path = digest_dir / manifest.artifact_paths["file_manifest"]
        lines = file_manifest_path.read_text(encoding="utf-8").splitlines()
        mutated = []
        for line in lines:
            entry = json.loads(line)
            if entry["path"] == "a.py":
                entry["file_hash"] = "1" * 64
            mutated.append(json.dumps(entry))
        file_manifest_path.write_text("\n".join(mutated) + "\n", encoding="utf-8")
        code = run_canonical_cli(["verify", str(repo), "--storage-root", self.storage_root])
        self.assertEqual(code, 1)


class CanonicalVerifyCliIntegrationTests(unittest.TestCase):
    """Subprocess integration: the real ``simplicio-mapper canonical verify`` CLI."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.storage_root = str(self.base / "storage")
        self.env = dict(os.environ)
        self.env["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = self.storage_root

    def _cli(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.cli", "canonical", "verify", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=self.env,
            timeout=timeout,
        )

    def test_cli_reports_match_and_exit_zero_for_clean_repo(self) -> None:
        repo = self.base / "repo-cli-clean"
        _init_repo(repo)
        result = self._cli(str(repo), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout.strip())
        self.assertEqual(receipt["schema"], CANONICAL_VERIFY_SCHEMA)
        self.assertEqual(receipt["result"], "match")

    def test_cli_human_output_reports_match(self) -> None:
        repo = self.base / "repo-cli-human"
        _init_repo(repo)
        result = self._cli(str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("canonical verify: match", result.stdout)

    def test_cli_reports_mismatch_and_exit_one_for_mutation(self) -> None:
        repo = self.base / "repo-cli-mutated"
        _init_repo(repo)
        manifest = build_canonical_manifest(str(repo), self.storage_root, _CLI_DEFAULT_FINGERPRINT)
        self.assertIsNotNone(manifest)
        digest_dir = Path(canonical_manifest_dir(self.storage_root, manifest.key.digest()))
        file_manifest_path = digest_dir / manifest.artifact_paths["file_manifest"]
        lines = file_manifest_path.read_text(encoding="utf-8").splitlines()
        mutated_lines = []
        for line in lines:
            entry = json.loads(line)
            if entry["path"] == "a.py":
                entry["file_hash"] = "f" * 64
            mutated_lines.append(json.dumps(entry))
        file_manifest_path.write_text("\n".join(mutated_lines) + "\n", encoding="utf-8")

        result = self._cli(str(repo), "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        receipt = json.loads(result.stdout.strip())
        self.assertEqual(receipt["result"], "mismatch")
        self.assertEqual(receipt["failure_reason"], "digest_mismatch")

    def test_cli_non_git_directory_fails_closed_with_exit_one(self) -> None:
        plain = self.base / "plain-cli"
        plain.mkdir()
        result = self._cli(str(plain), "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        receipt = json.loads(result.stdout.strip())
        self.assertEqual(receipt["result"], "fail")
        self.assertEqual(receipt["failure_reason"], "not_a_git_repository")

    def test_cli_unknown_canonical_subcommand_errors(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.cli", "canonical", "bogus"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown canonical subcommand", result.stderr)


if __name__ == "__main__":
    unittest.main()
