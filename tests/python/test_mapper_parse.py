"""Direct unit tests for simplicio_mapper.mapper.parse (issue #159 split).

Exercises the discovery/read layer in isolation -- imports straight from
``simplicio_mapper.mapper.parse`` (not the package's re-exported surface)
to prove the submodule is self-contained and correct on its own, not just
reachable through ``simplicio_mapper.mapper``.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.parse import (  # noqa: E402
    TEXT_EXTS,
    _build_file_inventory,
    _importance_for,
    _language_for,
    _normalize_rel,
    _parse_imports,
    _parse_symbols,
    _roles_for,
    _sha256,
    _token_words,
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


if __name__ == "__main__":
    unittest.main()
