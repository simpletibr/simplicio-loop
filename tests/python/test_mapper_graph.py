"""Direct unit tests for simplicio_mapper.mapper.graph (issue #159 split).

Exercises call-graph/architecture/symbol construction in isolation --
imports straight from ``simplicio_mapper.mapper.graph``.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.graph import (  # noqa: E402
    _build_call_graph,
    _build_symbol_index,
    _is_macro_screen,
    _macro_roles_for_path,
    build_macro_map,
)
from simplicio_mapper.mapper.parse import _build_file_inventory, _now_iso  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class MacroHelpersTest(unittest.TestCase):
    def test_macro_roles_for_path_detects_entrypoint(self) -> None:
        roles = _macro_roles_for_path("src/index.js", "index.js", "index.js", [])
        self.assertIn("entrypoint", roles)

    def test_is_macro_screen_detects_nextjs_pages_route(self) -> None:
        self.assertTrue(_is_macro_screen("pages/index.tsx", "index.tsx", "typescript"))
        self.assertFalse(_is_macro_screen("src/utils/math.py", "math.py", "python"))


class BuildMacroMapTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "src/index.js", "module.exports = () => {};\n")
        _write(self.dir, "package.json", '{"name": "fixture", "main": "src/index.js"}')

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_macro_map_has_expected_schema_and_entrypoint(self) -> None:
        macro = build_macro_map(str(self.dir))
        self.assertEqual(macro["schema"], "simplicio.macro-map/v1")
        self.assertIn("src/index.js", macro["entry_points"])


class SymbolAndCallGraphTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "src/greet.py", "def greet(name):\n    return f'hi {name}'\n")
        _write(
            self.dir,
            "src/main.py",
            "from src.greet import greet\n\n\ndef run():\n    return greet('world')\n",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_symbol_index_and_call_graph_over_two_files(self) -> None:
        files = _build_file_inventory(str(self.dir), {}, {}, None)
        generated_at = _now_iso()
        symbol_index = _build_symbol_index(str(self.dir), files, generated_at)
        self.assertEqual(symbol_index["schema"], "simplicio.symbol-index/v1")
        names = {s["name"] for s in symbol_index["symbols"]}
        self.assertIn("greet", names)
        self.assertIn("run", names)

        call_graph = _build_call_graph(str(self.dir), files, symbol_index, generated_at)
        self.assertEqual(call_graph["schema"], "simplicio.call-graph/v1")
        self.assertIsInstance(call_graph["edges"], list)


if __name__ == "__main__":
    unittest.main()
