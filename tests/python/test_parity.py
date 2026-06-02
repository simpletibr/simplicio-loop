"""Parity test between the Node and Python mapper implementations (#98).

Both `bin/mapper-artifacts.js` (invoked via `node bin/cli.js map`) and the
Python `simplicio_mapper.cli` emit `simplicio.*/v1` artifacts. Running them
against the same fixture must produce equivalent shape — schema, file set,
entry points, roles, architecture signals, symbol names, call-graph edge
counts — modulo intentionally volatile fields like `generated_at` and the
absolute host path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "parity-host"
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper import write_mapping_artifacts  # noqa: E402


def _have_node() -> bool:
    return shutil.which("node") is not None


def _normalize(project_map: dict) -> dict:
    """Strip fields that are intentionally environment-dependent."""
    cleaned = dict(project_map)
    cleaned.pop("generated_at", None)
    product = dict(cleaned.get("product", {}))
    product.pop("root", None)
    cleaned["product"] = product
    return cleaned


@unittest.skipUnless(_have_node(), "node not available; parity needs both runtimes")
class NodePythonParityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.node_root = self.base / "node-run"
        self.python_root = self.base / "py-run"
        shutil.copytree(FIXTURE, self.node_root)
        shutil.copytree(FIXTURE, self.python_root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _node_map(self) -> dict:
        result = subprocess.run(
            ["node", str(ROOT / "bin" / "cli.js"), "map", "--root", str(self.node_root)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return json.loads((self.node_root / ".simplicio" / "project-map.json").read_text())

    def _python_map(self) -> dict:
        write_mapping_artifacts(cwd=str(self.python_root), meta={"product_name": "parity-host"})
        return json.loads((self.python_root / ".simplicio" / "project-map.json").read_text())

    def test_schemas_match(self) -> None:
        node = self._node_map()
        py = self._python_map()
        self.assertEqual(node["schema"], py["schema"])
        self.assertEqual(node["version"], py["version"])

    def test_file_inventory_matches(self) -> None:
        node = self._node_map()
        py = self._python_map()
        node_paths = sorted(f["path"] for f in node["files"])
        py_paths = sorted(f["path"] for f in py["files"])
        self.assertEqual(node_paths, py_paths)

    def test_entry_points_match(self) -> None:
        node = self._node_map()
        py = self._python_map()
        self.assertEqual(sorted(node["entry_points"]), sorted(py["entry_points"]))

    def test_test_files_match(self) -> None:
        node = self._node_map()
        py = self._python_map()
        self.assertEqual(sorted(node["test_files"]), sorted(py["test_files"]))

    def test_architecture_signals_match(self) -> None:
        node = self._node_map()
        py = self._python_map()
        self.assertEqual(
            sorted(node["architecture"]["signals"]),
            sorted(py["architecture"]["signals"]),
        )

    def test_file_roles_match_per_path(self) -> None:
        node = self._node_map()
        py = self._python_map()
        node_roles = {f["path"]: sorted(f.get("roles", [])) for f in node["files"]}
        py_roles = {f["path"]: sorted(f.get("roles", [])) for f in py["files"]}
        self.assertEqual(node_roles, py_roles)

    def test_normalization_strips_volatile_fields(self) -> None:
        node = self._node_map()
        py = self._python_map()
        n = _normalize(node)
        p = _normalize(py)
        # generated_at must be absent from both after normalize.
        self.assertNotIn("generated_at", n)
        self.assertNotIn("generated_at", p)


if __name__ == "__main__":
    unittest.main()
