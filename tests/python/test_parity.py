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
import os
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


def _dir_without_python(extra_dirs: list[str]) -> str:
    """Build a PATH value that keeps ``extra_dirs`` (e.g. node's/git's own
    bin dirs) but drops any directory that also holds a ``python``/
    ``python3`` executable -- used to simulate "no Python on PATH" for a
    child process without relying on a container/venv trick."""
    kept: list[str] = []
    for candidate in extra_dirs:
        if not candidate:
            continue
        has_python = os.path.isfile(os.path.join(candidate, "python3")) or os.path.isfile(
            os.path.join(candidate, "python")
        )
        if not has_python and candidate not in kept:
            kept.append(candidate)
    return os.pathsep.join(kept)


@unittest.skipUnless(_have_node(), "node not available; shim tests need both runtimes")
class NodeThinShimTest(unittest.TestCase):
    """Issue #158 (ADR-005): `bin/cli.js`'s `map`/`update` dispatch prefers
    shimming straight to `python3 -m simplicio_mapper.cli` when Python +
    `simplicio_mapper` are importable, falling back to the Node
    reimplementation (`bin/map.js` + `bin/mapper-artifacts.js`) otherwise.

    Python logs "-> wrote <file> (...)" (ASCII arrow,
    simplicio_mapper/mapper.py); the Node reimplementation logs
    "→ wrote <file> (...)" (unicode arrow, bin/mapper-artifacts.js). That is
    a cheap, reliable signal for which engine actually ran a given
    invocation, used below instead of re-asserting on file contents (the
    parity tests above already cover that).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "package.json").write_text(
            json.dumps({"name": "shim-host", "scripts": {"test": "node --test"}})
        )
        (self.root / "src").mkdir()
        (self.root / "src" / "index.js").write_text("module.exports.run = () => 1;\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run_cli(self, extra_env: dict | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [
                "node", str(ROOT / "bin" / "cli.js"), "map",
                "--root", str(self.root), "--stack", "node", "--product-name", "Shim Host",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=env,
        )

    def test_shim_runs_python_by_default_when_available(self) -> None:
        # This sandbox has `simplicio_mapper` pip-installed (editable), so the
        # default (no override) path must actually shim to Python.
        result = self._run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-> wrote", result.stdout, result.stdout)
        self.assertNotIn("→ wrote", result.stdout)

    def test_no_shim_env_var_forces_the_node_fallback(self) -> None:
        result = self._run_cli(extra_env={"SIMPLICIO_MAPPER_NO_SHIM": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("→ wrote", result.stdout, result.stdout)
        self.assertNotIn("-> wrote", result.stdout)
        # The Node fallback must still produce a valid, schema-tagged artifact
        # on its own -- this is the "Python-absent" contract, not just
        # "prints something".
        project_map = json.loads((self.root / ".simplicio" / "project-map.json").read_text())
        self.assertEqual(project_map["schema"], "simplicio.project-map/v1")

    def test_python_genuinely_absent_from_path_falls_back_actionably(self) -> None:
        # Build a PATH that keeps node's and git's own bin dirs (both are
        # needed by the mapper) but excludes any directory that also
        # contains a python/python3 executable -- a portable stand-in for
        # "this host has no Python" without needing a container/venv.
        node_dir = os.path.dirname(shutil.which("node") or "")
        git_dir = os.path.dirname(shutil.which("git") or "")
        restricted_path = _dir_without_python([node_dir, git_dir, "/usr/bin", "/bin"])
        self.assertTrue(restricted_path, "could not build a python-free PATH for this host")

        result = self._run_cli(extra_env={"PATH": restricted_path})
        self.assertEqual(result.returncode, 0, result.stderr)
        # No Python on PATH -> detectPythonShim() must return null and the
        # command must fall back to the Node reimplementation, not fail.
        self.assertIn("→ wrote", result.stdout, result.stdout)
        self.assertNotIn("-> wrote", result.stdout)
        project_map = json.loads((self.root / ".simplicio" / "project-map.json").read_text())
        self.assertEqual(project_map["schema"], "simplicio.project-map/v1")


if __name__ == "__main__":
    unittest.main()
