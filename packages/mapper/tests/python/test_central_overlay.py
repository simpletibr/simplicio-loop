"""Worktree overlay over the central default-branch base (#1574).

The correctness bar: ``base + overlay`` equals a fresh full mapping of that worktree's tree. Every
scenario below builds the base once, mutates ONE worktree in some way, and compares the canonical
digest of the overlay's project-map / symbol-index / precedent-index with ``build_artifacts`` run
directly on that worktree (the oracle: no canonical/overlay machinery involved).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.canonical_artifacts import canonical_digest  # noqa: E402
from simplicio_mapper.mapper.central_overlay import (  # noqa: E402
    OVERLAY_STATE_FILE,
    apply_overlay,
    compute_overlay,
)
from simplicio_mapper.mapper.emit import build_artifacts  # noqa: E402

NAMES = ("project_map", "symbol_index", "precedent_index")


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout.strip()


PY = "import os\nfrom pkg.mod{dep} import helper_{dep}\n\n\ndef func_{i}_a(x):\n    try:\n        return helper_{dep}(x) + {i}\n    except ValueError:\n        return 0\n\n\nclass Thing{i}:\n    def method_{i}(self):\n        return func_{i}_a(1)\n"
JS = "export function jsFunc{i}(a) {{\n  return a + {i};\n}}\nexport const k{i} = jsFunc{i};\n"
TEST = "from pkg.mod{dep} import helper_{dep}\n\n\ndef test_it_{i}():\n    assert helper_{dep}(1) is not None\n"


def _write_file(root: Path, rel: str, kind: str, i: int, dep: int) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {"py": PY, "js": JS, "test": TEST}[kind].format(i=i, dep=dep)
    if kind == "py":
        body += f"\n\ndef helper_{i}(x):\n    return x\n"
    target.write_text(body, encoding="utf-8")


def make_repo(path: Path, seed: int = 0, files: int = 12) -> list[str]:
    rnd = random.Random(seed)
    path.mkdir(parents=True)
    _git(["init", "-q", "--initial-branch", "main"], path)
    _git(["config", "user.email", "t@example.com"], path)
    _git(["config", "user.name", "T"], path)
    rels = []
    for i in range(files):
        kind = rnd.choice(["py", "py", "js", "test"])
        ext = {"py": "py", "js": "js", "test": "py"}[kind]
        rel = f"pkg/{'tests/' if kind == 'test' else ''}mod{i}.{ext}"
        _write_file(path, rel, kind, i, rnd.randrange(files))
        rels.append(rel)
    (path / "README.md").write_text("# demo\n\nsome docs\n", encoding="utf-8")
    (path / "package.json").write_text(
        json.dumps({"name": "demo-app", "main": "pkg/mod0.js", "dependencies": {"left-pad": "1"}}),
        encoding="utf-8",
    )
    (path / ".gitignore").write_text("ignored_*.py\n", encoding="utf-8")
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "base"], path)
    return rels


def semantic(artifacts: dict, names=NAMES) -> dict[str, str]:
    return {name: canonical_digest(artifacts[name]) for name in names}


class OverlayCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.main = self.base / "main"
        self.rels = make_repo(self.main)
        self.cache = str(self.base / "cache")
        os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = self.cache
        self.addCleanup(os.environ.pop, "SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
        self.counter = 0

    def worktree(self, name: str = "wt", *, detach: bool = False, at: str = "main") -> Path:
        path = self.base / name
        args = ["worktree", "add", "-q"]
        args += ["--detach", str(path), at] if detach else ["-b", f"b-{name}", str(path), at]
        _git(args, self.main)
        return path

    def assert_equivalent(self, wt: Path, meta: dict | None = None) -> dict:
        outcome = compute_overlay(str(wt), meta=meta)
        self.assertIsNotNone(outcome.artifacts, outcome.receipt)
        fresh = build_artifacts(str(wt), meta=meta)
        got, want = semantic(outcome.artifacts), semantic(fresh)
        for name in NAMES:
            self.assertEqual(got[name], want[name], f"{name} differs from a fresh full mapping")
        # The file lists must match exactly as well (a stronger, readable check).
        self.assertEqual(
            [f["path"] for f in outcome.artifacts["project_map"]["files"]],
            [f["path"] for f in fresh["project_map"]["files"]],
        )
        return outcome.receipt

    def base_fingerprint(self) -> dict[str, str]:
        """sha256 of every byte under the central base store."""
        out = {}
        for dirpath, _dirs, names in os.walk(os.path.join(self.cache, "canonical")):
            for name in names:
                path = os.path.join(dirpath, name)
                out[os.path.relpath(path, self.cache)] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return out


class EquivalenceTests(OverlayCase):
    def test_clean_worktree_equals_the_base_and_reuses_every_file(self) -> None:
        wt = self.worktree()
        receipt = self.assert_equivalent(wt)
        self.assertEqual(receipt["files_remapped"], 0)
        self.assertGreater(receipt["files_reused"], 10)

    def test_modified_file(self) -> None:
        wt = self.worktree()
        (wt / self.rels[0]).write_text("def brand_new():\n    return 42\n", encoding="utf-8")
        receipt = self.assert_equivalent(wt)
        self.assertEqual(receipt["files_remapped"], 1)

    def test_added_untracked_file_and_new_import(self) -> None:
        wt = self.worktree()
        (wt / "pkg" / "fresh.py").write_text("from pkg.mod1 import helper_1\n\ndef added():\n    return helper_1(0)\n", encoding="utf-8")
        self.assert_equivalent(wt)

    def test_deleted_file_unstaged_and_staged(self) -> None:
        wt = self.worktree()
        (wt / self.rels[1]).unlink()
        _git(["rm", "-q", self.rels[2]], wt)
        self.assert_equivalent(wt)

    def test_rename_and_rename_with_edit(self) -> None:
        wt = self.worktree()
        _git(["mv", self.rels[3], "pkg/renamed3.py" if self.rels[3].endswith(".py") else "pkg/renamed3.js"], wt)
        _git(["mv", self.rels[4], "pkg/renamed4" + os.path.splitext(self.rels[4])[1]], wt)
        edited = wt / "pkg" / ("renamed4" + os.path.splitext(self.rels[4])[1])
        edited.write_text(edited.read_text(encoding="utf-8") + "\n# edited after rename\n", encoding="utf-8")
        self.assert_equivalent(wt)

    def test_head_ahead_of_the_base_with_uncommitted_changes_on_top(self) -> None:
        wt = self.worktree()
        (wt / self.rels[5]).write_text("def committed():\n    return 1\n", encoding="utf-8")
        _git(["add", "-A"], wt)
        _git(["commit", "-q", "-m", "wt work"], wt)
        (wt / "pkg" / "later.py").write_text("def later():\n    return 2\n", encoding="utf-8")
        (wt / self.rels[6]).write_text("def uncommitted():\n    return 3\n", encoding="utf-8")
        self.assert_equivalent(wt)

    def test_head_behind_the_base(self) -> None:
        old = self.worktree("old")
        (self.main / "pkg" / "moved_on.py").write_text("def moved_on():\n    return 1\n", encoding="utf-8")
        (self.main / self.rels[7]).write_text("def main_changed():\n    return 7\n", encoding="utf-8")
        _git(["add", "-A"], self.main)
        _git(["commit", "-q", "-m", "main moves on"], self.main)
        # The base is now the NEW main tree; the old worktree sits at the previous commit.
        receipt = self.assert_equivalent(old)
        # Only the edited file still exists in the old tree (re-parsed); the file main added is a
        # deletion from the old worktree's point of view.
        self.assertEqual(receipt["files_remapped"], 1)
        self.assertIn("pkg/moved_on.py", receipt["delta"]["removed"])

    def test_detached_head(self) -> None:
        wt = self.worktree("det", detach=True)
        (wt / self.rels[8]).write_text("def detached_edit():\n    return 8\n", encoding="utf-8")
        self.assert_equivalent(wt)

    def test_package_json_change_re_derives_roles_for_the_whole_tree(self) -> None:
        wt = self.worktree()
        (wt / "package.json").write_text(
            json.dumps({"name": "renamed-app", "main": "pkg/mod3.py", "type": "module"}), encoding="utf-8"
        )
        self.assert_equivalent(wt)

    def test_git_ignored_file_that_the_mapper_still_walks(self) -> None:
        wt = self.worktree()
        (wt / "ignored_local.py").write_text("def local_only():\n    return 1\n", encoding="utf-8")
        self.assert_equivalent(wt)

    def test_large_file_is_skipped_like_the_full_mapping_skips_it(self) -> None:
        wt = self.worktree()
        (wt / "pkg" / "huge.py").write_text("x = 1\n" * 60000, encoding="utf-8")
        self.assert_equivalent(wt)

    def test_file_names_with_spaces_and_non_ascii_characters(self) -> None:
        for name in ("pkg/with space.py", "pkg/módulo_ação.py"):
            target = self.main / name
            target.write_text("def original():\n    return 1\n", encoding="utf-8")
        _git(["add", "-A"], self.main)
        _git(["commit", "-q", "-m", "odd names"], self.main)
        wt = self.worktree()
        for name in ("pkg/with space.py", "pkg/módulo_ação.py"):
            # Same size on purpose: only the delta paths (not the size guard) can notice it.
            (wt / name).write_text("def original():\n    return 2\n", encoding="utf-8")
        receipt = self.assert_equivalent(wt)
        self.assertEqual(receipt["files_remapped"], 2)

    def test_a_modified_then_restored_file_is_reused_from_the_base(self) -> None:
        wt = self.worktree()
        original = (wt / self.rels[0]).read_text(encoding="utf-8")
        (wt / self.rels[0]).write_text("changed\n", encoding="utf-8")
        (wt / self.rels[0]).write_text(original, encoding="utf-8")
        receipt = self.assert_equivalent(wt)
        self.assertEqual(receipt["files_remapped"], 0)

    def test_meta_overrides_make_their_own_base_and_still_match_a_fresh_mapping(self) -> None:
        wt = self.worktree()
        (wt / self.rels[0]).write_text("def meta_edit():\n    return 1\n", encoding="utf-8")
        self.assert_equivalent(wt, meta={"stack": "python", "product_name": "custom"})

    def test_random_edit_sequences(self) -> None:
        for seed in range(6):
            with self.subTest(seed=seed):
                rnd = random.Random(seed)
                wt = self.worktree(f"rand{seed}")
                live = list(self.rels)
                for step in range(rnd.randrange(3, 9)):
                    op = rnd.choice(["edit", "add", "delete", "rename", "commit", "restore"])
                    if op == "edit" and live:
                        (wt / rnd.choice(live)).write_text(f"def e{seed}_{step}():\n    return {step}\n", encoding="utf-8")
                    elif op == "add":
                        _write_file(wt, f"pkg/new{seed}_{step}.py", "py", 100 + step, rnd.randrange(12))
                    elif op == "delete" and len(live) > 3:
                        victim = live.pop(rnd.randrange(len(live)))
                        (wt / victim).unlink()
                    elif op == "rename" and live:
                        victim = live.pop(rnd.randrange(len(live)))
                        target = f"pkg/r{seed}_{step}{os.path.splitext(victim)[1]}"
                        _git(["mv", victim, target], wt)
                        live.append(target)
                    elif op == "commit":
                        _git(["add", "-A"], wt)
                        subprocess.run(["git", "commit", "-q", "-m", f"s{step}", "--allow-empty"], cwd=str(wt), check=True)
                    elif op == "restore" and live:
                        subprocess.run(["git", "checkout", "-q", "main", "--", live[0]], cwd=str(wt), check=False)
                self.assert_equivalent(wt)


class IsolationTests(OverlayCase):
    def test_a_change_in_one_worktree_is_invisible_in_the_other_and_in_the_base(self) -> None:
        a, b = self.worktree("a"), self.worktree("b")
        compute_overlay(str(b))  # builds the base once
        before = self.base_fingerprint()
        (a / self.rels[0]).write_text("def only_in_a():\n    return 1\n", encoding="utf-8")
        apply_overlay(str(a))
        b_outcome = apply_overlay(str(b))
        self.assertEqual(self.base_fingerprint(), before, "an overlay run must never write into the base")
        b_map = json.loads((b / ".simplicio-loop" / "project-map.json").read_text(encoding="utf-8"))
        a_map = json.loads((a / ".simplicio-loop" / "project-map.json").read_text(encoding="utf-8"))
        symbols_b = json.loads((b / ".simplicio-loop" / "symbol-index.json").read_text(encoding="utf-8"))
        symbols_a = json.loads((a / ".simplicio-loop" / "symbol-index.json").read_text(encoding="utf-8"))
        self.assertIn("only_in_a", {s["name"] for s in symbols_a["symbols"]})
        self.assertNotIn("only_in_a", {s["name"] for s in symbols_b["symbols"]})
        by_hash_a = {f["path"]: f["file_hash"] for f in a_map["files"]}
        by_hash_b = {f["path"]: f["file_hash"] for f in b_map["files"]}
        self.assertNotEqual(by_hash_a[self.rels[0]], by_hash_b[self.rels[0]])
        self.assertEqual(b_outcome.receipt["files_remapped"], 0)
        self.assertEqual(len(os.listdir(os.path.join(self.cache, "canonical"))), 1, "one base for both")

    def test_the_overlay_state_is_the_worktrees_own_and_references_the_base(self) -> None:
        wt = self.worktree()
        (wt / self.rels[0]).write_text("def x():\n    return 1\n", encoding="utf-8")
        receipt = apply_overlay(str(wt)).receipt
        state = json.loads((wt / ".simplicio-loop" / OVERLAY_STATE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(state["base_digest"], receipt["base_digest"])
        self.assertEqual(state["schema"], "simplicio.worktree-overlay-state/v1")
        self.assertIn(self.rels[0], state["delta"]["modified"])
        self.assertEqual(state["base_commit"], _git(["rev-parse", "main"], self.main))
        # Nothing was written outside the worktree's own state and the central store.
        self.assertFalse((self.main / ".simplicio-loop").exists())

    def test_heavy_derived_artifacts_are_not_copied_into_the_worktree(self) -> None:
        wt = self.worktree()
        state = wt / ".simplicio-loop"
        state.mkdir()
        for stale in ("call-graph.json", "architecture-inventory.json", "retrieval-index.json", "artifact-manifest.json"):
            (state / stale).write_text("{}", encoding="utf-8")
        apply_overlay(str(wt))
        written = sorted(os.listdir(state))
        for stale in ("call-graph.json", "architecture-inventory.json", "retrieval-index.json", "artifact-manifest.json"):
            self.assertNotIn(stale, written, "a superseded generation must not stay behind")
        for name in ("project-map.json", "symbol-index.json", "precedent-index.json", OVERLAY_STATE_FILE):
            self.assertIn(name, written)

    def test_cli_build_verify_and_the_overlay_all_use_one_base(self) -> None:
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        argv = [sys.executable, "-m", "simplicio_mapper.cli.__main__", "canonical"]
        subprocess.run(argv + ["build", str(self.main), "--json"], check=True, capture_output=True, env=env)
        wt = self.worktree()
        receipt = apply_overlay(str(wt)).receipt
        self.assertEqual(receipt["base_build"], "reused_cache_hit", "the overlay must find the CLI-built base")
        subprocess.run(argv + ["verify", str(wt), "--json"], capture_output=True, env=env)
        self.assertEqual(len(os.listdir(os.path.join(self.cache, "canonical"))), 1, "exactly one base per tree")

    def test_two_worktrees_asking_at_once_share_one_base_build(self) -> None:
        import threading

        wts = [self.worktree(f"c{i}") for i in range(4)]
        results: list[object] = []
        gate = threading.Barrier(len(wts))

        def run(path: Path) -> None:
            gate.wait()
            results.append(apply_overlay(str(path)).receipt)

        threads = [threading.Thread(target=run, args=(wt,)) for wt in wts]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        self.assertEqual(len(results), 4)
        self.assertEqual({r["base_digest"] for r in results}, {results[0]["base_digest"]})
        self.assertEqual(len(os.listdir(os.path.join(self.cache, "canonical"))), 1)


class FallbackTests(OverlayCase):
    def test_non_git_directory_falls_back_without_writing_anything(self) -> None:
        plain = self.base / "plain"
        plain.mkdir()
        (plain / "a.py").write_text("x = 1\n", encoding="utf-8")
        outcome = apply_overlay(str(plain))
        self.assertIsNone(outcome.artifacts)
        self.assertEqual(outcome.receipt["status"], "fallback")
        self.assertEqual(outcome.receipt["fallback_reason"], "identity_unresolved")
        self.assertFalse((plain / ".simplicio-loop").exists())

    def test_base_build_failure_falls_back(self) -> None:
        from unittest import mock

        from simplicio_mapper.mapper import canonical_builder

        wt = self.worktree()
        with mock.patch.object(canonical_builder, "build_artifacts", side_effect=RuntimeError("boom")):
            outcome = apply_overlay(str(wt))
        self.assertIsNone(outcome.artifacts)
        self.assertEqual(outcome.receipt["fallback_reason"], "canonical_build_failed")
        self.assertFalse((wt / ".simplicio-loop" / OVERLAY_STATE_FILE).exists())


if __name__ == "__main__":
    unittest.main()
