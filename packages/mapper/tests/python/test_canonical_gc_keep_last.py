"""Count-based retention for canonical bases: newest N + digests live worktrees reference (#1574)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.canonical_gc import scan_canonical_gc  # noqa: E402
from simplicio_mapper.mapper.canonical_identity import resolve_repo_identity_bundle  # noqa: E402


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


class KeepLastTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        _git(["init", "--initial-branch", "main"], self.repo)
        _git(["config", "user.email", "t@example.com"], self.repo)
        _git(["config", "user.name", "T"], self.repo)
        (self.repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _git(["add", "."], self.repo)
        _git(["commit", "-m", "init"], self.repo)
        self.cache_root = base / "cache"
        (self.cache_root / "canonical").mkdir(parents=True)
        self.identity = resolve_repo_identity_bundle(str(self.repo))
        assert self.identity is not None
        self.now = time.time()

    def _manifest(
        self, name: str, *, age_hours: float, commit: str | None = None, repo_identity: str | None = None
    ) -> Path:
        directory = self.cache_root / "canonical" / name
        directory.mkdir()
        (directory / "project-map.json").write_text("{}" * 50, encoding="utf-8")
        created = self.now - age_hours * 3600
        (directory / "manifest.json").write_text(json.dumps({
            "schema": "simplicio.canonical-map/v1",
            "created_at": _iso(created),
            "key": {
                "repo_identity": repo_identity or self.identity.repo_identity,
                "default_branch": self.identity.default_branch,
                "commit_sha": commit or ("f" * 40),
            },
        }), encoding="utf-8")
        for item in (directory / "manifest.json", directory / "project-map.json", directory):
            os.utime(item, (created, created))
        return directory

    def _scan(self, **kwargs):
        return scan_canonical_gc(
            str(self.repo), storage_root=str(self.cache_root), now=self.now, **kwargs
        )

    def test_keep_last_keeps_the_newest_n_and_candidates_the_rest(self) -> None:
        names = ["d%d" % index for index in range(6)]
        for index, name in enumerate(names):
            self._manifest(name, age_hours=2 + index)  # d0 newest ... d5 oldest
        report = self._scan(keep_last=3)
        candidates = sorted(c.relative_path for c in report.candidates)
        self.assertEqual(candidates, ["canonical/d3", "canonical/d4", "canonical/d5"])
        kept = {c.relative_path: c.reason for c in report.preserved}
        self.assertEqual(kept["canonical/d0"], "kept_newest_3")

    def test_a_digest_a_live_worktree_overlay_references_is_never_a_candidate(self) -> None:
        for index in range(5):
            self._manifest("d%d" % index, age_hours=2 + index)
        report = self._scan(keep_last=1, referenced_digests=frozenset({"d4"}))
        candidates = {c.relative_path for c in report.candidates}
        self.assertNotIn("canonical/d4", candidates)
        self.assertNotIn("canonical/d0", candidates)
        self.assertEqual(candidates, {"canonical/d1", "canonical/d2", "canonical/d3"})
        reasons = {c.relative_path: c.reason for c in report.preserved}
        self.assertEqual(reasons["canonical/d4"], "referenced_by_worktree_overlay")

    def test_the_current_default_branch_base_is_always_kept(self) -> None:
        current = self._manifest("cur", age_hours=500, commit=self.identity.commit_sha)
        self._manifest("new1", age_hours=1)
        report = self._scan(keep_last=1)
        self.assertNotIn("canonical/cur", {c.relative_path for c in report.candidates})
        self.assertTrue(current.exists())

    def test_apply_removes_only_the_candidates(self) -> None:
        dirs = [self._manifest("d%d" % index, age_hours=2 + index) for index in range(4)]
        report = self._scan(keep_last=2, apply=True)
        self.assertEqual(len(report.removed), 2)
        self.assertTrue(dirs[0].exists() and dirs[1].exists())
        self.assertFalse(dirs[2].exists() or dirs[3].exists())

    def test_another_repositorys_base_in_a_shared_cache_dir_is_never_touched(self) -> None:
        """SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR may be shared: `--keep 0` must not eat a neighbour's base."""
        ours = [self._manifest("o%d" % i, age_hours=5 + i) for i in range(3)]
        theirs = [self._manifest("x%d" % i, age_hours=500 + i, repo_identity="other-repo") for i in range(3)]
        report = self._scan(keep_last=0, apply=True)
        self.assertEqual(len(report.removed), 3, [c.relative_path for c in report.removed])
        self.assertTrue(all(path.exists() for path in theirs))
        self.assertFalse(any(path.exists() for path in ours))
        reasons = {c.relative_path: c.reason for c in report.preserved}
        self.assertEqual(reasons["canonical/x0"], "other_repository")

    def test_the_newest_n_are_counted_per_repository(self) -> None:
        for i in range(3):
            self._manifest("o%d" % i, age_hours=50 + i)
        for i in range(3):
            self._manifest("x%d" % i, age_hours=1 + i, repo_identity="other-repo")  # newer, but not ours
        report = self._scan(keep_last=1)
        self.assertEqual(sorted(c.relative_path for c in report.candidates), ["canonical/o1", "canonical/o2"])

    def test_without_keep_last_the_ttl_policy_is_unchanged(self) -> None:
        for index in range(5):
            self._manifest("d%d" % index, age_hours=2 + index)
        report = self._scan()  # default 7-day TTL: nothing is old enough
        self.assertEqual(report.candidates, [])

    def test_a_fresh_promotion_inside_the_grace_window_survives_keep_zero(self) -> None:
        fresh = self._manifest("fresh", age_hours=0.0)
        report = self._scan(keep_last=0)
        self.assertNotIn("canonical/fresh", {c.relative_path for c in report.candidates})
        self.assertTrue(fresh.exists())


if __name__ == "__main__":
    unittest.main()
