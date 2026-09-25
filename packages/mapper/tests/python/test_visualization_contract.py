import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.contract import find_contract_root, validate_payload
from simplicio_mapper.mapper import build_artifacts
from simplicio_mapper.visualization import (
    _provenance,
    _safe_remote,
    build_visualization_bundle,
    preview_source,
)


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )


class VisualizationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def greet():\n    return 'safe'\n", encoding="utf-8")
        (self.root / "src" / "app.ts").write_text("export function run() { return 1; }\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=do-not-preview\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_bundle_has_normalized_language_diagnostics_and_stable_ids(self) -> None:
        artifacts = build_artifacts(str(self.root), output_dir=".simplicio")
        first = build_visualization_bundle(str(self.root), artifacts, generated_at="1970-01-01T00:00:00.000Z")
        second = build_visualization_bundle(str(self.root), artifacts, generated_at="1970-01-01T00:00:00.000Z")
        self.assertEqual(first, second)
        self.assertEqual(validate_payload(first, find_contract_root(str(self.root)))[1], [])
        languages = {item["path"]: item["language"] for item in first["language_diagnostics"]}
        self.assertEqual(languages["src/app.py"], "python")
        self.assertEqual(languages["src/app.ts"], "typescript")
        self.assertIn("language-diagnostics", first["capabilities"])

    def test_preview_is_bounded_and_reports_fingerprint(self) -> None:
        payload = preview_source(str(self.root), path="src/app.py", max_bytes=8, max_lines=1)
        self.assertEqual(validate_payload(payload, find_contract_root(str(self.root)))[1], [])
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["language"], "python")
        self.assertTrue(payload["read_only"])
        self.assertEqual(len(payload["revision_fingerprint"]), 64)

    def test_preview_denies_traversal_symlinks_secrets_and_binary(self) -> None:
        cases = ["../outside.py", ".env"]
        for path in cases:
            with self.subTest(path=path), self.assertRaises(ValueError):
                preview_source(str(self.root), path=path)
        (self.root / "image.bin").write_bytes(b"\x00\x01")
        with self.assertRaises(ValueError):
            preview_source(str(self.root), path="image.bin")
        link = self.root / "src" / "link.py"
        outside = self.root.parent / "outside-preview.py"
        outside.write_text("nope", encoding="utf-8")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this Windows environment")
        with self.assertRaises(ValueError):
            preview_source(str(self.root), path="src/link.py")

    def test_symbol_entity_preview_is_read_only_and_full_export_is_explicit(self) -> None:
        artifacts = build_artifacts(str(self.root), output_dir=".simplicio")
        bundle = build_visualization_bundle(str(self.root), artifacts, generated_at="1970-01-01T00:00:00.000Z")
        symbol = next(node for node in bundle["nodes"] if node["kind"] == "symbol" and node["name"] == "greet")
        payload = preview_source(str(self.root), entity_id=symbol["id"], allow_full_content=True)
        self.assertEqual(payload["path"], "src/app.py")
        self.assertEqual(payload["sensitivity_warning"], "full-content export was explicitly requested")
        self.assertTrue(payload["read_only"])


class ProvenanceGitTests(unittest.TestCase):
    """`_provenance()` git-derived fields (issue #185) only exercise their
    real branches against an actual `.git` worktree with a remote -- every
    other visualization test in this module uses a plain (non-git) fixture,
    so these branches were previously untested."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def greet():\n    return 'safe'\n", encoding="utf-8")
        try:
            _run_git(self.root, "init", "-q", "-b", "main")
            _run_git(self.root, "config", "user.email", "test@example.com")
            _run_git(self.root, "config", "user.name", "Test")
            _run_git(self.root, "remote", "add", "origin", "https://github.com/acme/widgets.git")
            _run_git(self.root, "add", "-A")
            _run_git(self.root, "commit", "-q", "-m", "initial")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is unavailable in this environment")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_provenance_reports_remote_host_owner_and_repository(self) -> None:
        provenance = _provenance(str(self.root))
        self.assertEqual(provenance["remote_url"], "https://github.com/acme/widgets.git")
        self.assertEqual(provenance["host"], "github.com")
        self.assertEqual(provenance["owner"], "acme")
        self.assertEqual(provenance["repository"], "widgets")
        self.assertEqual(provenance["branch"], "main")
        self.assertTrue(provenance["commit_sha"])
        self.assertEqual(provenance["clone_type"], "git-clone")
        self.assertFalse(provenance["dirty"])

    def test_provenance_marks_dirty_when_worktree_has_uncommitted_changes(self) -> None:
        (self.root / "src" / "app.py").write_text("def greet():\n    return 'changed'\n", encoding="utf-8")
        provenance = _provenance(str(self.root))
        self.assertTrue(provenance["dirty"])

    def test_provenance_detects_monorepo_roots(self) -> None:
        (self.root / "packages" / "core").mkdir(parents=True)
        (self.root / "packages" / "core" / "package.json").write_text("{}", encoding="utf-8")
        provenance = _provenance(str(self.root))
        self.assertIn("packages/core", provenance["monorepo_roots"])

    def test_bundle_from_a_git_worktree_uses_remote_derived_repo_identity(self) -> None:
        bundle = build_visualization_bundle(str(self.root), generated_at="1970-01-01T00:00:00.000Z")
        self.assertEqual(bundle["provenance"]["host"], "github.com")


class SafeRemoteNormalizationTests(unittest.TestCase):
    def test_scp_style_remote_is_normalized_to_https(self) -> None:
        self.assertEqual(_safe_remote("git@github.com:acme/widgets.git"), "https://github.com/acme/widgets.git")

    def test_ssh_scheme_remote_is_normalized_to_https(self) -> None:
        self.assertEqual(_safe_remote("ssh://git@github.com/acme/widgets.git"), "https://github.com/acme/widgets.git")

    def test_https_remote_strips_embedded_credentials_and_query(self) -> None:
        self.assertEqual(
            _safe_remote("https://user:pass@github.com/acme/widgets.git?x=1#frag"),
            "https://github.com/acme/widgets.git",
        )


if __name__ == "__main__":
    unittest.main()
