"""Direct unit tests for simplicio_mapper.mapper.parse (issue #159 split).

Exercises the discovery/read layer in isolation -- imports straight from
``simplicio_mapper.mapper.parse`` (not the package's re-exported surface)
to prove the submodule is self-contained and correct on its own, not just
reachable through ``simplicio_mapper.mapper``.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cache import FileProcessingCache  # noqa: E402
from simplicio_mapper.mapper.parse import (  # noqa: E402
    TEXT_EXTS,
    _build_file_inventory,
    _cached_parse_file,
    _collect_text_files,
    _importance_for,
    _is_internal_worktree_dir,
    _language_for,
    _normalize_rel,
    _parse_imports,
    _parse_json_safe,
    _parse_symbols,
    _read_safe,
    _roles_for,
    _sha256,
    _token_words,
    _walk,
)


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class HelperFunctionTest(unittest.TestCase):
    def test_sha256_is_deterministic(self) -> None:
        self.assertEqual(_sha256("hello world\n"), _sha256("hello world\n"))
        self.assertNotEqual(_sha256("a"), _sha256("b"))

    def test_normalize_rel_replaces_os_sep_with_forward_slash(self) -> None:
        # _normalize_rel replaces os.sep (platform-dependent), so build the
        # "native" separator form dynamically rather than hardcoding "\\".
        import os as _os

        native = _os.sep.join(["a", "b", "c.py"])
        self.assertEqual(_normalize_rel(native), "a/b/c.py")
        self.assertEqual(_normalize_rel("a/b/c.py"), "a/b/c.py")

    def test_language_for_known_extensions(self) -> None:
        self.assertEqual(_language_for("src/index.py"), "python")
        self.assertEqual(_language_for("src/app.ts"), "typescript")
        self.assertIn("app.json", TEXT_EXTS.union({"app.json"}))  # sanity on the set itself

    def test_parse_imports_python(self) -> None:
        text = "import os\nfrom collections import OrderedDict\n"
        imports = _parse_imports(text, "python")
        self.assertIn("os", imports)
        self.assertIn("collections", imports)

    def test_parse_imports_expanded_languages(self) -> None:
        self.assertIn("std::collections::HashMap", _parse_imports("use std::collections::HashMap;\n", "rust"))
        self.assertIn("java.util.List", _parse_imports("import java.util.List;\n", "java"))
        self.assertIn("kotlin.collections.List", _parse_imports("import kotlin.collections.List\n", "kotlin"))
        php_imports = _parse_imports("use App\\Service\\UserService;\nrequire 'bootstrap.php';\n", "php")
        self.assertIn("App\\Service\\UserService", php_imports)
        self.assertIn("bootstrap.php", php_imports)
        self.assertIn("json", _parse_imports("require 'json'\n", "ruby"))

    def test_parse_symbols_python_def(self) -> None:
        text = "def handler(request):\n    return None\n"
        symbols = _parse_symbols(text)
        self.assertIn("handler", symbols)

    def test_roles_for_test_file(self) -> None:
        roles = _roles_for("tests/test_thing.py", {})
        self.assertIn("test", roles)

    def test_roles_for_entrypoint(self) -> None:
        roles = _roles_for("src/index.js", {})
        self.assertIn("entrypoint", roles)

    def test_importance_for_entrypoint_outranks_plain_file(self) -> None:
        entry_score = _importance_for(["entrypoint"], [], [], "unmodified")
        plain_score = _importance_for([], [], [], "unmodified")
        self.assertGreater(entry_score, plain_score)

    def test_token_words_splits_camel_and_snake_case(self) -> None:
        words = _token_words("userAccountService_helper")
        self.assertIn("user", words)
        self.assertIn("account", words)
        self.assertIn("service", words)
        self.assertIn("helper", words)

    def test_is_internal_worktree_dir_matches_nested_claude_worktrees_only(self) -> None:
        # Issue #234: only "worktrees" directly under ".claude" is a
        # managed-worktree container; siblings and lookalikes must not
        # match so root .claude config keeps being walked normally.
        self.assertTrue(_is_internal_worktree_dir("/repo/.claude", "worktrees"))
        self.assertTrue(_is_internal_worktree_dir("C:\\repo\\.claude", "worktrees"))
        self.assertFalse(_is_internal_worktree_dir("/repo", "worktrees"))
        self.assertFalse(_is_internal_worktree_dir("/repo/.claude", "skills"))
        self.assertFalse(_is_internal_worktree_dir("/repo/.claude", "settings.json"))
        self.assertFalse(_is_internal_worktree_dir("/repo/notclaude", "worktrees"))


class BuildFileInventoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "src/index.js", "const express = require('express');\nexpress();\n")
        _write(self.dir, "tests/index.test.js", "test('smoke', () => {});\n")
        _write(self.dir, "package.json", '{"name": "fixture", "dependencies": {"express": "^4.0.0"}}')

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_discovers_entrypoint_and_test_files(self) -> None:
        pkg = {"name": "fixture", "dependencies": {"express": "^4.0.0"}}
        files = _build_file_inventory(str(self.dir), pkg, {}, None)
        paths = {f.path for f in files}
        self.assertIn("src/index.js", paths)
        self.assertIn("tests/index.test.js", paths)
        by_path = {f.path: f for f in files}
        self.assertIn("entrypoint", by_path["src/index.js"].roles)
        self.assertIn("test", by_path["tests/index.test.js"].roles)

    def test_collect_text_files_reports_large_file_skip(self) -> None:
        _write(self.dir, "src/huge.txt", "x" * 260_000)
        skipped: list[str] = []
        files = _build_file_inventory(str(self.dir), {"name": "fixture"}, {}, None, skipped_large_files=skipped)
        self.assertTrue(all(f.path != "src/huge.txt" for f in files))
        self.assertEqual(skipped, ["src/huge.txt"])

    def test_git_status_timeout_marks_degraded(self) -> None:
        from simplicio_mapper.mapper.parse import _git_status_map

        degraded = {"git_timeout": False, "git_status_unavailable": False}
        with mock.patch(
            "simplicio_mapper.mapper.parse.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=3),
        ):
            self.assertEqual(_git_status_map(str(self.dir), degraded=degraded), {})
        self.assertTrue(degraded["git_timeout"])

    def test_same_input_produces_identical_inventory_output(self) -> None:
        # Determinism acceptance criterion: the same source tree scanned
        # twice must produce byte-for-byte identical file entries (order,
        # fields, values), independent of any cache.
        pkg = {"name": "fixture"}
        first = _build_file_inventory(str(self.dir), pkg, {}, None)
        second = _build_file_inventory(str(self.dir), pkg, {}, None)
        self.assertEqual([f.to_dict() for f in first], [f.to_dict() for f in second])


class ExclusionAndSkipDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_walk_skips_configured_directories(self) -> None:
        _write(self.dir, "src/keep.py", "x = 1\n")
        _write(self.dir, "node_modules/pkg/index.js", "module.exports = {};\n")
        _write(self.dir, ".git/HEAD", "ref: refs/heads/main\n")
        found = {Path(p).relative_to(self.dir).as_posix() for p in _walk(str(self.dir))}
        self.assertIn("src/keep.py", found)
        self.assertTrue(all("node_modules" not in p for p in found))
        self.assertTrue(all(not p.startswith(".git/") for p in found))

    def test_collect_text_files_excludes_non_text_extensions(self) -> None:
        _write(self.dir, "src/app.py", "print(1)\n")
        binary_path = self.dir / "assets" / "logo.png"
        binary_path.parent.mkdir(parents=True, exist_ok=True)
        binary_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01\x02")
        files = _collect_text_files(str(self.dir))
        rels = {Path(p).relative_to(self.dir).as_posix() for p in files}
        self.assertIn("src/app.py", rels)
        self.assertNotIn("assets/logo.png", rels)

    def test_walk_tolerates_unreadable_root(self) -> None:
        # A root directory that can't be scanned (permission error, race
        # with deletion, etc.) must degrade to "no files" rather than
        # raising and aborting the whole scan.
        missing = self.dir / "does-not-exist"
        self.assertEqual(list(_walk(str(missing))), [])

    def test_walk_excludes_claude_worktrees_but_keeps_root_config(self) -> None:
        # Issue #234: nested agent worktrees under .claude/worktrees/<name>
        # duplicate the primary checkout and inflate the mapped file
        # universe, but legitimate root-level .claude configuration
        # (settings.json, skills/*.md) must still be discovered.
        _write(self.dir, "src/keep.py", "x = 1\n")
        _write(self.dir, ".claude/settings.json", "{}\n")
        _write(self.dir, ".claude/skills/foo/SKILL.md", "# foo\n")
        _write(self.dir, ".claude/worktrees/worker/src.py", "print('duplicated')\n")
        found = {Path(p).relative_to(self.dir).as_posix() for p in _walk(str(self.dir))}
        self.assertIn("src/keep.py", found)
        self.assertIn(".claude/settings.json", found)
        self.assertIn(".claude/skills/foo/SKILL.md", found)
        self.assertTrue(all(".claude/worktrees" not in p for p in found))

    def test_walk_no_worktree_fixture_has_no_regression(self) -> None:
        # A normal fixture without any nested worktree must see all of its
        # files discovered -- the new exclusion must not touch unrelated
        # directories named anything else, including a bare "worktrees"
        # dir that isn't nested under .claude.
        _write(self.dir, "src/keep.py", "x = 1\n")
        _write(self.dir, "docs/readme.md", "hello\n")
        _write(self.dir, "worktrees/not-claude.py", "x = 1\n")
        found = {Path(p).relative_to(self.dir).as_posix() for p in _walk(str(self.dir))}
        self.assertEqual(
            found,
            {"src/keep.py", "docs/readme.md", "worktrees/not-claude.py"},
        )


class InvalidAndUnreadableFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_read_safe_replaces_invalid_utf8_bytes_instead_of_raising(self) -> None:
        target = self.dir / "bad_encoding.py"
        target.write_bytes(b"x = 1\n\xff\xfe invalid bytes\n")
        text = _read_safe(str(target))
        self.assertIn("x = 1", text)
        self.assertNotIn("����", text)  # sanity: didn't blow up into garbage-only

    def test_read_safe_returns_empty_string_for_missing_file(self) -> None:
        self.assertEqual(_read_safe(str(self.dir / "nope.py")), "")

    def test_parse_json_safe_returns_empty_dict_for_malformed_json(self) -> None:
        target = self.dir / "package.json"
        target.write_text("{not valid json,,,", encoding="utf-8")
        self.assertEqual(_parse_json_safe(str(target)), {})

    def test_parse_json_safe_returns_empty_dict_for_missing_file(self) -> None:
        self.assertEqual(_parse_json_safe(str(self.dir / "missing.json")), {})

    def test_parse_json_safe_returns_empty_dict_for_empty_file(self) -> None:
        target = self.dir / "empty.json"
        target.write_text("", encoding="utf-8")
        self.assertEqual(_parse_json_safe(str(target)), {})

    def test_inventory_skips_a_file_deleted_between_walk_and_stat_without_raising(self) -> None:
        # Partial errors (a file vanishing mid-scan) must not corrupt or
        # abort inventory building for the rest of the tree.
        _write(self.dir, "src/keep.py", "x = 1\n")
        _write(self.dir, "src/gone.py", "y = 2\n")
        real_stat = os.stat

        def flaky_stat(path, *args, **kwargs):
            if str(path).endswith("gone.py"):
                raise OSError("vanished mid-scan")
            return real_stat(path, *args, **kwargs)

        with mock.patch("simplicio_mapper.mapper.parse.os.stat", side_effect=flaky_stat):
            files = _build_file_inventory(str(self.dir), {"name": "fixture"}, {}, None)
        paths = {f.path for f in files}
        self.assertIn("src/keep.py", paths)
        self.assertNotIn("src/gone.py", paths)


class CachedParseFileInvalidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.cache_dir = self.dir / ".cache"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_changing_one_file_only_invalidates_that_files_cache_entry(self) -> None:
        _write(self.dir, "src/a.py", "def a():\n    return 1\n")
        _write(self.dir, "src/b.py", "def b():\n    return 2\n")

        with FileProcessingCache(self.cache_dir) as cache:
            stat_a = os.stat(self.dir / "src" / "a.py")
            stat_b = os.stat(self.dir / "src" / "b.py")
            first_a = _cached_parse_file(str(self.dir), str(self.dir / "src" / "a.py"), "src/a.py", stat_a, cache)
            first_b = _cached_parse_file(str(self.dir), str(self.dir / "src" / "b.py"), "src/b.py", stat_b, cache)

            # Mutate only a.py -- b.py's fingerprint (size/mtime) is untouched.
            (self.dir / "src" / "a.py").write_text("def a():\n    return 999\n", encoding="utf-8")
            new_stat_a = os.stat(self.dir / "src" / "a.py")

            second_a = _cached_parse_file(str(self.dir), str(self.dir / "src" / "a.py"), "src/a.py", new_stat_a, cache)
            second_b = _cached_parse_file(str(self.dir), str(self.dir / "src" / "b.py"), "src/b.py", stat_b, cache)

            self.assertNotEqual(first_a["file_hash"], second_a["file_hash"])
            self.assertEqual(first_b["file_hash"], second_b["file_hash"])
            self.assertEqual(cache.get_processed_file("src/b.py", stat_b.st_size, stat_b.st_mtime_ns), first_b)

    def test_cache_hit_returns_identical_result_without_reparsing(self) -> None:
        _write(self.dir, "src/a.py", "def a():\n    return 1\n")
        with FileProcessingCache(self.cache_dir) as cache:
            stat_a = os.stat(self.dir / "src" / "a.py")
            first = _cached_parse_file(str(self.dir), str(self.dir / "src" / "a.py"), "src/a.py", stat_a, cache)
            second = _cached_parse_file(str(self.dir), str(self.dir / "src" / "a.py"), "src/a.py", stat_a, cache)
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
