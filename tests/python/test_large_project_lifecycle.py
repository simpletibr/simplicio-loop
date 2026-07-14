"""System-level validation for issue #221.

Exercises the mapper against a real, versioned, multi-language project tree
that mimics a small monorepo, through the lifecycle scenarios called out in
the issue's acceptance criteria:

- initial + incremental indexing on a real git-backed source tree;
- rename, move, delete and restore of files;
- branch switch and an interrupted/partial checkout;
- corrupted (invalid-encoding) files and a partially-supported language;
- output artifacts validated against their committed JSON Schemas, so a
  consumer (dev-cli/loop/agent) can read them without manual adaptation.

The fixture tree is generated on the fly (not checked in) because the
scenarios below mutate it in place (renames, branch checkouts, corruption);
what *is* fixed and reproducible is the generator itself, seeded and
deterministic, so every CI run builds byte-identical inputs.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_mapper.contract import validate_instance  # noqa: E402
from simplicio_mapper.incremental import run_incremental_scan  # noqa: E402
from simplicio_mapper.mapper import build_artifacts  # noqa: E402

SCHEMA_ROOT = ROOT / "contracts" / "mapper-artifacts" / "v1" / "schemas"


def _load_schema(name: str) -> dict:
    import json

    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _build_monorepo(root: Path) -> None:
    """Deterministic small "monorepo": a python service, a JS package, and
    shared docs -- large enough to exercise nested dirs, multiple
    languages, and cross-package references."""
    for i in range(6):
        _write(
            root,
            f"services/api/src/handlers/handler_{i}.py",
            f"def handle_{i}(request):\n    return call_{i}(request)\n\n"
            f"def call_{i}(request):\n    return request\n",
        )
    _write(
        root,
        "services/api/src/app.py",
        "from services.api.src.handlers.handler_0 import handle_0\n\n"
        "def main():\n    return handle_0({})\n",
    )
    for i in range(4):
        _write(
            root,
            f"packages/web/src/components/Widget{i}.js",
            f"export function Widget{i}() {{ return {i}; }}\n",
        )
    _write(root, "packages/web/package.json", '{"name": "web", "version": "1.0.0"}\n')
    _write(root, "docs/README.md", "# Monorepo fixture\n")
    _write(root, "services/api/src/handlers/legacy.rs", "fn legacy() -> i32 { 1 }\n")


class LargeProjectLifecycleTest(unittest.TestCase):
    """Real fixture (not schema-only) coverage for AC: fixtures reais,
    contratos validados, atualização incremental consistente,
    recuperação após interrupção."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        _build_monorepo(self.root)
        _git(self.root, "init", "-q")
        _git(self.root, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A")
        _git(self.root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "seed")
        self.snapshot_schema = _load_schema("graph-snapshot.schema.json")
        self.delta_schema = _load_schema("graph-delta.schema.json")
        self.project_map_schema = _load_schema("project-map.schema.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _rescan(self, changed_paths: list[str] | None = None) -> dict:
        return run_incremental_scan(str(self.root), changed_paths=changed_paths)

    def test_initial_scan_produces_schema_valid_snapshot_over_real_tree(self) -> None:
        result = self._rescan()
        self.assertEqual(result["event_type"], "initial_snapshot")
        errors = validate_instance(result["snapshot"], self.snapshot_schema)
        self.assertEqual(errors, [], errors)
        self.assertGreaterEqual(len(result["snapshot"]["entities"]), 10)

        artifacts = build_artifacts(str(self.root))
        errors = validate_instance(artifacts["project_map"], self.project_map_schema)
        self.assertEqual(errors, [], errors)
        # A consumer (dev-cli/loop/agent) should be able to read files
        # straight off the artifact without any bespoke adaptation.
        paths = {f["path"] for f in artifacts["project_map"]["files"]}
        self.assertIn("services/api/src/app.py", paths)
        self.assertIn("packages/web/src/components/Widget0.js", paths)

    def test_rename_move_delete_and_restore_are_reflected_incrementally(self) -> None:
        self._rescan()

        # Rename in place.
        old = self.root / "services/api/src/handlers/handler_1.py"
        renamed = self.root / "services/api/src/handlers/handler_1_renamed.py"
        old.rename(renamed)
        rename_delta = self._rescan(changed_paths=["services/api/src/handlers/handler_1_renamed.py"])
        self.assertEqual(rename_delta["event_type"], "delta")
        errors = validate_instance(rename_delta, self.delta_schema)
        self.assertEqual(errors, [], errors)
        ops = {(e["op"], e["affected_paths"][0]) for e in rename_delta["events"] if e["entity_type"] == "entity"}
        self.assertIn(("remove", "services/api/src/handlers/handler_1.py"), ops)
        self.assertIn(("add", "services/api/src/handlers/handler_1_renamed.py"), ops)

        # Move to a different directory.
        moved_dir = self.root / "services/api/src/moved"
        moved_dir.mkdir(parents=True)
        moved = moved_dir / "handler_1_renamed.py"
        renamed.rename(moved)
        move_delta = self._rescan(changed_paths=["services/api/src/moved/handler_1_renamed.py"])
        ops = {(e["op"], e["affected_paths"][0]) for e in move_delta["events"] if e["entity_type"] == "entity"}
        self.assertIn(("remove", "services/api/src/handlers/handler_1_renamed.py"), ops)
        self.assertIn(("add", "services/api/src/moved/handler_1_renamed.py"), ops)

        # Delete outright.
        moved.unlink()
        delete_delta = self._rescan()
        ops = {(e["op"], e["affected_paths"][0]) for e in delete_delta["events"] if e["entity_type"] == "entity"}
        self.assertIn(("remove", "services/api/src/moved/handler_1_renamed.py"), ops)

        # Restore the original file from git history (checkout of a
        # previously-deleted/renamed path) and confirm the mapper's view
        # converges back to the pre-mutation snapshot.
        _git(self.root, "checkout", "HEAD", "--", "services/api/src/handlers/handler_1.py")
        restore_delta = self._rescan(changed_paths=["services/api/src/handlers/handler_1.py"])
        ops = {(e["op"], e["affected_paths"][0]) for e in restore_delta["events"] if e["entity_type"] == "entity"}
        self.assertIn(("add", "services/api/src/handlers/handler_1.py"), ops)

        final = build_artifacts(str(self.root))
        paths = {f["path"] for f in final["project_map"]["files"]}
        self.assertIn("services/api/src/handlers/handler_1.py", paths)
        self.assertNotIn("services/api/src/moved/handler_1_renamed.py", paths)

    def test_branch_switch_and_incomplete_checkout_do_not_corrupt_state(self) -> None:
        self._rescan()  # baseline on main/master

        _git(self.root, "checkout", "-q", "-b", "feature")
        _write(self.root, "services/api/src/handlers/feature_only.py", "def feature():\n    return 1\n")
        _git(self.root, "add", "-A")
        _git(self.root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "feature file")
        feature_delta = self._rescan(changed_paths=["services/api/src/handlers/feature_only.py"])
        ops = {(e["op"], e["affected_paths"][0]) for e in feature_delta["events"] if e["entity_type"] == "entity"}
        self.assertIn(("add", "services/api/src/handlers/feature_only.py"), ops)

        base_branch = _git(self.root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        self.assertEqual(base_branch, "feature")

        # Simulate an interrupted/partial checkout back to the base branch:
        # the working tree loses the feature-only file (as `git checkout`
        # would remove it) but nothing else has caught up yet -- the mapper
        # must degrade gracefully rather than raise or produce a malformed
        # delta.
        (self.root / "services/api/src/handlers/feature_only.py").unlink()
        interrupted_delta = self._rescan()
        self.assertIn(interrupted_delta["event_type"], {"delta", "resync_required"})
        if interrupted_delta["event_type"] == "delta":
            errors = validate_instance(interrupted_delta, self.delta_schema)
            self.assertEqual(errors, [], errors)
            ops = {(e["op"], e["affected_paths"][0]) for e in interrupted_delta["events"] if e["entity_type"] == "entity"}
            self.assertIn(("remove", "services/api/src/handlers/feature_only.py"), ops)

        # Completing the checkout (restoring the working tree to match
        # HEAD, as a resumed `git checkout` would) then re-scanning must
        # recover a fully consistent, schema-valid state.
        _git(self.root, "checkout", "--", "services/api/src/handlers/feature_only.py")
        recovered_delta = self._rescan(changed_paths=["services/api/src/handlers/feature_only.py"])
        errors = validate_instance(recovered_delta, self.delta_schema)
        self.assertEqual(errors, [], errors)
        artifacts = build_artifacts(str(self.root))
        paths = {f["path"] for f in artifacts["project_map"]["files"]}
        self.assertIn("services/api/src/handlers/feature_only.py", paths)

    def test_corrupted_file_and_partially_supported_language_do_not_crash_scan(self) -> None:
        self._rescan()

        # A "corrupted" source file: bytes that are not valid UTF-8.
        corrupted = self.root / "services/api/src/handlers/corrupted.py"
        corrupted.write_bytes(b"def broken(:\xff\xfe not valid utf-8 \x00\x01\n")

        # A file in a language the mapper only partially recognizes: it is
        # walked and language-tagged, but has no dedicated symbol parser
        # (tier-3 "niche/basic" support) -- must degrade gracefully, not
        # crash or silently corrupt the rest of the scan.
        _write(self.root, "services/api/src/legacy/script.lua", "local function noop() end\n")

        # A file with an extension the mapper does not recognize at all
        # must be excluded from the artifacts without raising.
        _write(self.root, "tools/build.zig", "pub fn main() void {}\n")

        result = self._rescan(changed_paths=[
            "services/api/src/handlers/corrupted.py",
            "services/api/src/legacy/script.lua",
            "tools/build.zig",
        ])
        self.assertEqual(result["event_type"], "delta")
        errors = validate_instance(result, self.delta_schema)
        self.assertEqual(errors, [], errors)

        artifacts = build_artifacts(str(self.root))
        by_path = {f["path"]: f for f in artifacts["project_map"]["files"]}
        self.assertIn("services/api/src/handlers/corrupted.py", by_path)
        self.assertIn("services/api/src/legacy/script.lua", by_path)
        self.assertEqual(by_path["services/api/src/legacy/script.lua"]["language"], "lua")
        self.assertNotIn("tools/build.zig", by_path)

    def test_recovery_after_interruption_then_consistent_incremental_resync(self) -> None:
        first = self._rescan()
        self.assertEqual(first["event_type"], "initial_snapshot")

        # Simulate a crash mid-write: the persisted snapshot state is
        # truncated/corrupted, as if the process died while writing it.
        state_path = self.root / ".simplicio" / "graph-snapshot.json"
        state_path.write_text("{not valid json", encoding="utf-8")

        recovered = self._rescan()
        self.assertEqual(recovered["event_type"], "initial_snapshot")
        errors = validate_instance(recovered["snapshot"], self.snapshot_schema)
        self.assertEqual(errors, [], errors)

        # A subsequent incremental scan must be fully consistent again.
        _write(self.root, "services/api/src/handlers/post_recovery.py", "def post():\n    return 1\n")
        follow_up = self._rescan(changed_paths=["services/api/src/handlers/post_recovery.py"])
        self.assertEqual(follow_up["event_type"], "delta")
        errors = validate_instance(follow_up, self.delta_schema)
        self.assertEqual(errors, [], errors)


if __name__ == "__main__":
    unittest.main()
