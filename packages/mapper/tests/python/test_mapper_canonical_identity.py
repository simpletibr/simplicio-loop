"""Unit tests for simplicio_mapper.mapper.canonical_identity (issue #236, ADR-008 step 2).

Covers the pure git-identity resolution functions used to build a
``CanonicalMapKey`` -- ``repo_identity``, ``default_branch``, ``commit_sha``,
``tree_sha`` and ``common_git_dir`` -- against real temporary git
repositories (never mocked subprocess output, so the test matrix proves the
functions actually parse real ``git`` command output). No production
pipeline wiring exists yet; these tests only exercise the new module in
isolation, per the ADR's migration plan.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper import canonical_identity  # noqa: E402
from simplicio_mapper.mapper.canonical_identity import (  # noqa: E402
    ResolvedRepoIdentity,
    _run_git,
    is_git_repository,
    normalize_remote_url,
    resolve_branch_commit_sha,
    resolve_commit_tree_sha,
    resolve_common_git_dir,
    resolve_default_branch,
    resolve_origin_url,
    resolve_repo_identity,
    resolve_repo_identity_bundle,
)


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _init_repo(path: Path, *, default_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["init", "--initial-branch", default_branch], path)
    _run(["config", "user.email", "test@example.com"], path)
    _run(["config", "user.name", "Test User"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run(["add", "."], path)
    _run(["commit", "-m", "init"], path)


def _current_commit_sha(path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(path), capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _current_tree_sha(path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=str(path),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class NormalizeRemoteUrlTests(unittest.TestCase):
    def test_https_and_ssh_and_scp_forms_normalize_equal(self) -> None:
        https = normalize_remote_url("https://Github.com/Org/Repo.git")
        ssh = normalize_remote_url("ssh://git@github.com/Org/Repo.git")
        scp = normalize_remote_url("git@github.com:Org/Repo.git")
        self.assertEqual(https, ssh)
        self.assertEqual(ssh, scp)
        self.assertEqual(https, "github.com/Org/Repo")

    def test_trailing_slash_is_stripped(self) -> None:
        self.assertEqual(
            normalize_remote_url("https://github.com/org/repo/"),
            normalize_remote_url("https://github.com/org/repo"),
        )

    def test_empty_url_normalizes_to_empty_string(self) -> None:
        self.assertEqual(normalize_remote_url(""), "")
        self.assertEqual(normalize_remote_url("   "), "")

    def test_file_remote_with_no_host_hits_hostless_branch(self) -> None:
        # file:// remotes (used by local-remote fixtures elsewhere in this
        # test module) have no netloc/host -- exercises the hostless
        # normalization branch distinct from the github.com case above.
        normalized = normalize_remote_url("file:///tmp/some/repo.git")
        self.assertEqual(normalized, "tmp/some/repo")


class RunGitErrorHandlingTests(unittest.TestCase):
    def test_run_git_returns_none_when_subprocess_cannot_spawn(self) -> None:
        with patch.object(
            canonical_identity.subprocess,
            "run",
            side_effect=FileNotFoundError("git not on PATH"),
        ):
            self.assertIsNone(_run_git(["rev-parse", "HEAD"], "."))

    def test_run_git_returns_none_on_timeout(self) -> None:
        with patch.object(
            canonical_identity.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
        ):
            self.assertIsNone(_run_git(["rev-parse", "HEAD"], "."))

    def test_resolve_common_git_dir_none_for_non_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(resolve_common_git_dir(tmp))


class GitRepoIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_is_git_repository_false_for_non_repo_dir(self) -> None:
        plain_dir = self.root / "plain"
        plain_dir.mkdir()
        self.assertFalse(is_git_repository(str(plain_dir)))

    def test_default_branch_named_main(self) -> None:
        repo = self.root / "repo-main"
        _init_repo(repo, default_branch="main")
        self.assertTrue(is_git_repository(str(repo)))
        self.assertEqual(resolve_default_branch(str(repo)), "main")

    def test_default_branch_named_master(self) -> None:
        repo = self.root / "repo-master"
        _init_repo(repo, default_branch="master")
        self.assertEqual(resolve_default_branch(str(repo)), "master")

    def test_default_branch_custom_name_via_symbolic_ref(self) -> None:
        # Simulate "cloned with a remote HEAD ref" by creating a bare remote
        # and cloning it -- this populates refs/remotes/origin/HEAD for real,
        # rather than asserting against a mocked git call.
        remote = self.root / "remote.git"
        remote.mkdir()
        _run(["init", "--bare", "--initial-branch", "trunk"], remote)

        seed = self.root / "seed"
        _init_repo(seed, default_branch="trunk")
        _run(["remote", "add", "origin", str(remote)], seed)
        _run(["push", "origin", "trunk"], seed)
        _run(["symbolic-ref", "HEAD", "refs/heads/trunk"], remote)

        clone = self.root / "clone"
        subprocess.run(
            ["git", "clone", str(remote), str(clone)],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(resolve_default_branch(str(clone)), "trunk")
        expected_sha = _current_commit_sha(seed)
        self.assertEqual(resolve_branch_commit_sha(str(clone), "trunk"), expected_sha)

    def test_no_origin_remote_falls_back_to_common_git_dir_hash(self) -> None:
        repo = self.root / "repo-no-remote"
        _init_repo(repo)
        self.assertIsNone(resolve_origin_url(str(repo)))

        common_dir = resolve_common_git_dir(str(repo))
        self.assertIsNotNone(common_dir)
        self.assertTrue(Path(common_dir).is_absolute())

        identity = resolve_repo_identity(str(repo))
        self.assertIsNotNone(identity)
        # Same repo resolved twice must be stable/deterministic.
        self.assertEqual(identity, resolve_repo_identity(str(repo)))

    def test_repo_identity_shared_when_origin_matches_across_clones(self) -> None:
        remote = self.root / "shared-remote.git"
        remote.mkdir()
        _run(["init", "--bare", "--initial-branch", "main"], remote)

        seed = self.root / "shared-seed"
        _init_repo(seed, default_branch="main")
        _run(["remote", "add", "origin", str(remote)], seed)
        _run(["push", "origin", "main"], seed)

        clone_a = self.root / "clone-a"
        clone_b = self.root / "clone-b"
        for clone in (clone_a, clone_b):
            subprocess.run(
                ["git", "clone", str(remote), str(clone)],
                capture_output=True,
                text=True,
                check=True,
            )

        self.assertEqual(
            resolve_repo_identity(str(clone_a)), resolve_repo_identity(str(clone_b))
        )

    def test_branch_commit_sha_none_for_nonexistent_branch(self) -> None:
        repo = self.root / "repo-no-such-branch"
        _init_repo(repo)
        self.assertIsNone(resolve_branch_commit_sha(str(repo), "does-not-exist"))

    def test_commit_tree_sha_none_for_bad_commit_sha(self) -> None:
        repo = self.root / "repo-bad-commit-sha"
        _init_repo(repo)
        self.assertIsNone(resolve_commit_tree_sha(str(repo), "0" * 40))

    def test_commit_sha_and_tree_sha_match_head(self) -> None:
        repo = self.root / "repo-shas"
        _init_repo(repo)
        expected_commit = _current_commit_sha(repo)
        expected_tree = _current_tree_sha(repo)

        commit_sha = resolve_branch_commit_sha(str(repo), "main")
        self.assertEqual(commit_sha, expected_commit)
        self.assertEqual(resolve_commit_tree_sha(str(repo), commit_sha), expected_tree)

    def test_default_branch_none_when_no_commits_and_no_remote(self) -> None:
        # An unborn-HEAD repo (git init, zero commits) has no local branches
        # and no remote -- every fallback in resolve_default_branch must
        # exhaust and return None rather than guessing.
        repo = self.root / "repo-empty"
        repo.mkdir()
        _run(["init", "--initial-branch", "main"], repo)
        self.assertTrue(is_git_repository(str(repo)))
        self.assertIsNone(resolve_default_branch(str(repo)))

    def test_default_branch_resolved_via_remote_show_when_no_local_head_ref(self) -> None:
        # "git remote add" + "git fetch" (no full clone) never populates
        # refs/remotes/origin/HEAD, so symbolic-ref must fail and
        # `git remote show origin` must be the thing that resolves the name.
        remote = self.root / "show-remote.git"
        remote.mkdir()
        _run(["init", "--bare", "--initial-branch", "trunk"], remote)

        seed = self.root / "show-seed"
        _init_repo(seed, default_branch="trunk")
        _run(["remote", "add", "origin", str(remote)], seed)
        _run(["push", "origin", "trunk"], seed)

        local = self.root / "show-local"
        local.mkdir()
        _run(["init", "--initial-branch", "trunk"], local)
        _run(["remote", "add", "origin", str(remote)], local)
        _run(["fetch", "origin"], local)

        # A plain "remote add" + "fetch" (no full clone) can still leave the
        # local repo with a real refs/remotes/origin/HEAD in some git
        # versions, which would make symbolic-ref succeed and this test
        # would no longer exercise the "remote show" fallback it targets.
        # Force that specific call to miss so the real `git remote show
        # origin` subprocess (unmocked) is what resolves the branch name.
        real_run_git = canonical_identity._run_git

        def _run_git_forcing_symbolic_ref_miss(args, cwd, timeout=canonical_identity._GIT_TIMEOUT_SECONDS):
            if args[:1] == ["symbolic-ref"]:
                return None
            return real_run_git(args, cwd, timeout)

        with patch.object(
            canonical_identity, "_run_git", side_effect=_run_git_forcing_symbolic_ref_miss
        ):
            self.assertEqual(resolve_default_branch(str(local)), "trunk")

    def test_resolve_repo_identity_bundle_returns_none_for_non_repo(self) -> None:
        plain_dir = self.root / "plain2"
        plain_dir.mkdir()
        self.assertIsNone(resolve_repo_identity_bundle(str(plain_dir)))

    def test_resolve_repo_identity_bundle_none_when_default_branch_unresolvable(self) -> None:
        repo = self.root / "repo-empty-bundle"
        repo.mkdir()
        _run(["init", "--initial-branch", "main"], repo)
        self.assertIsNone(resolve_repo_identity_bundle(str(repo)))

    def test_resolve_repo_identity_bundle_none_when_commit_sha_unresolvable(self) -> None:
        repo = self.root / "repo-patched-bundle"
        _init_repo(repo)
        with patch(
            "simplicio_mapper.mapper.canonical_identity.resolve_branch_commit_sha",
            return_value=None,
        ):
            self.assertIsNone(resolve_repo_identity_bundle(str(repo)))

    def test_resolve_repo_identity_bundle_none_when_tree_sha_unresolvable(self) -> None:
        repo = self.root / "repo-patched-bundle-tree"
        _init_repo(repo)
        with patch(
            "simplicio_mapper.mapper.canonical_identity.resolve_commit_tree_sha",
            return_value=None,
        ):
            self.assertIsNone(resolve_repo_identity_bundle(str(repo)))

    def test_resolve_repo_identity_bundle_none_when_repo_identity_unresolvable(self) -> None:
        repo = self.root / "repo-patched-bundle-identity"
        _init_repo(repo)
        with patch(
            "simplicio_mapper.mapper.canonical_identity.resolve_repo_identity",
            return_value=None,
        ):
            self.assertIsNone(resolve_repo_identity_bundle(str(repo)))

    def test_resolve_repo_identity_bundle_full_shape(self) -> None:
        repo = self.root / "repo-bundle"
        _init_repo(repo)
        bundle = resolve_repo_identity_bundle(str(repo))
        self.assertIsInstance(bundle, ResolvedRepoIdentity)
        self.assertEqual(bundle.default_branch, "main")
        self.assertEqual(bundle.commit_sha, _current_commit_sha(repo))
        self.assertEqual(bundle.tree_sha, _current_tree_sha(repo))
        self.assertTrue(Path(bundle.common_git_dir).is_absolute())
        self.assertTrue(bundle.repo_identity)


class GitWorktreeCommonDirTests(unittest.TestCase):
    """Proves ``git-common-dir`` resolves to the shared ``.git``, not the
    worktree's own private git dir -- the specific proof the ADR/issue #236
    test matrix calls out explicitly."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_worktree_shares_common_git_dir_with_main_checkout(self) -> None:
        main_repo = self.root / "main-checkout"
        _init_repo(main_repo, default_branch="main")

        worktree_path = self.root / "linked-worktree"
        _run(["branch", "feature-branch"], main_repo)
        _run(
            ["worktree", "add", str(worktree_path), "feature-branch"],
            main_repo,
        )

        main_common_dir = resolve_common_git_dir(str(main_repo))
        worktree_common_dir = resolve_common_git_dir(str(worktree_path))

        self.assertIsNotNone(main_common_dir)
        self.assertEqual(main_common_dir, worktree_common_dir)

        # The worktree's own private git dir (holding its own HEAD/index)
        # must NOT equal the shared common dir -- otherwise this assertion
        # would be vacuously true for any path.
        worktree_private_git_dir = worktree_path / ".git"
        self.assertTrue(worktree_private_git_dir.exists())
        self.assertNotEqual(str(worktree_private_git_dir.resolve()), worktree_common_dir)

        # repo_identity resolved from the worktree must match the one
        # resolved from the main checkout -- same repo, same identity.
        self.assertEqual(
            resolve_repo_identity(str(main_repo)), resolve_repo_identity(str(worktree_path))
        )


if __name__ == "__main__":
    unittest.main()
