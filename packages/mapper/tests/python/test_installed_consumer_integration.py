from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from simplicio_mapper.contract import validate_instance

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "simplicio_mapper" / "contracts" / "consumer-integration" / "v1"
SCHEMAS = CONTRACT_ROOT / "schemas"
FIXTURES = CONTRACT_ROOT / "fixtures"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema(name: str) -> dict:
    return _load_json(SCHEMAS / name)


class ConsumerIntegrationFixtureContractTest(unittest.TestCase):
    def test_committed_fixtures_validate(self) -> None:
        cases = [
            (
                FIXTURES / "dev-cli-minimal" / "receipt.json",
                _schema("dev-cli-consumer-receipt.schema.json"),
            ),
            (
                FIXTURES / "loop-minimal" / "receipt.json",
                _schema("loop-consumer-receipt.schema.json"),
            ),
        ]
        for fixture_path, schema in cases:
            with self.subTest(fixture=str(fixture_path)):
                errors = validate_instance(_load_json(fixture_path), schema)
                self.assertEqual(errors, [], errors)


class InstalledWheelConsumerIntegrationTest(unittest.TestCase):
    maxDiff = None

    def _venv_python(self, venv_dir: Path) -> Path:
        if os.name == "nt":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _run(self, argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL
        )

    def _build_and_install(self, tmp: Path) -> Path:
        dist_dir = tmp / "dist"
        dist_dir.mkdir()
        build = self._run([sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)], cwd=ROOT)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        wheels = sorted(dist_dir.glob("*.whl"))
        self.assertEqual(len(wheels), 1, [str(path) for path in wheels])

        venv_dir = tmp / "venv"
        create_venv = self._run([sys.executable, "-m", "venv", str(venv_dir)], cwd=tmp)
        self.assertEqual(create_venv.returncode, 0, create_venv.stdout + create_venv.stderr)

        py = self._venv_python(venv_dir)
        install = self._run([str(py), "-m", "pip", "install", str(wheels[0])], cwd=tmp)
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        return py

    def _run_installed_script(self, py: Path, script: str, *, cwd: Path) -> dict:
        script_path = cwd / "consumer_check.py"
        script_path.write_text(textwrap.dedent(script), encoding="utf-8")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [str(py), str(script_path)],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def test_installed_wheel_supports_dev_cli_and_loop_shaped_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            py = self._build_and_install(tmp)

            repo_under_test = tmp / "consumer-repo"
            (repo_under_test / "src" / "cache").mkdir(parents=True)
            (repo_under_test / "tests").mkdir()
            (repo_under_test / "docs").mkdir()
            (repo_under_test / "src" / "cache" / "token_cache.py").write_text(
                "class TokenCache:\n    def evict(self):\n        return None\n",
                encoding="utf-8",
            )
            (repo_under_test / "tests" / "test_token_cache.py").write_text(
                "def test_placeholder():\n    assert True\n",
                encoding="utf-8",
            )
            (repo_under_test / "docs" / "release-notes.md").write_text("notes\n", encoding="utf-8")

            dev_cli_receipt = self._run_installed_script(
                py,
                f"""
                import json
                import os
                from pathlib import Path
                from simplicio_mapper import retrieval_index as ri
                import simplicio_mapper

                root = Path({json.dumps(str(repo_under_test))})
                project_map = {{
                    "files": [
                        {{
                            "path": "src/cache/token_cache.py",
                            "roles": ["domain"],
                            "importance": 0.8,
                            "language": "python",
                            "size_bytes": 80,
                            "imports": [],
                            "exports": ["TokenCache"],
                        }},
                        {{
                            "path": "tests/test_token_cache.py",
                            "roles": ["test"],
                            "importance": 0.4,
                            "language": "python",
                            "size_bytes": 40,
                            "imports": [],
                            "exports": ["test_placeholder"],
                        }},
                        {{
                            "path": "docs/release-notes.md",
                            "roles": ["docs"],
                            "importance": 0.1,
                            "language": "markdown",
                            "size_bytes": 10,
                            "imports": [],
                            "exports": [],
                        }},
                    ],
                    "recent_changes": [{{"path": "src/cache/token_cache.py", "status": "modified"}}],
                }}
                symbol_index = {{
                    "symbols": [
                        {{
                            "defined_in": "src/cache/token_cache.py",
                            "name": "TokenCache",
                            "kind": "class",
                            "line": 1,
                            "qualified_name": "src/cache/token_cache.py::TokenCache",
                        }}
                    ]
                }}
                call_graph = {{"edges": []}}
                index = ri.build_retrieval_index(project_map, symbol_index=symbol_index, call_graph=call_graph, root=str(root))
                selection = ri.select_context_targets(
                    str(root),
                    project_map,
                    goal="Fix TokenCache eviction in src/cache/token_cache.py",
                    target="src/cache/token_cache.py",
                    symbol_index=symbol_index,
                    call_graph=call_graph,
                    retrieval_index=index,
                )
                receipt = {{
                    "schema": "simplicio.consumer-dev-cli-receipt/v1",
                    "consumer": {{"name": "simplicio-dev-cli", "shape": "dev-cli"}},
                    "install": {{
                        "module_file": simplicio_mapper.__file__,
                        "site_packages": "site-packages" in simplicio_mapper.__file__.replace("\\\\", "/").lower(),
                    }},
                    "retrieval": {{
                        "index_schema": index["schema"],
                        "selection_schema": selection["schema"],
                        "index_id": index["index_id"],
                        "selected_paths": [item["path"] for item in selection["targets"]],
                        "matched_terms": selection["coverage"]["matched_terms"],
                    }},
                    "flags": {{
                        "abstained": selection["abstained"],
                        "needs_broader_context": selection["needs_broader_context"],
                        "fidelity_sufficient": selection["fidelity"]["sufficient"],
                        "target_status": selection["target_resolution"]["status"],
                    }},
                }}
                print(json.dumps(receipt))
                """,
                cwd=tmp,
            )
            loop_receipt = self._run_installed_script(
                py,
                f"""
                import json
                from pathlib import Path
                from simplicio_mapper.context_snapshot import (
                    CONTEXT_GRAPH_SCHEMA,
                    CONTEXT_SNAPSHOT_SCHEMA,
                    build_context_snapshot,
                    from_package,
                )
                import simplicio_mapper

                snapshot = build_context_snapshot(
                    {json.dumps(str(repo_under_test))},
                    project_map={{
                        "product": {{"name": "consumer-repo", "stack": "python"}},
                        "files": [
                            {{
                                "path": "src/cache/token_cache.py",
                                "language": "python",
                                "roles": ["domain"],
                                "imports": [],
                                "exports": ["TokenCache"],
                            }}
                        ],
                    }},
                    symbol_index={{
                        "symbols": [
                            {{
                                "defined_in": "src/cache/token_cache.py",
                                "name": "TokenCache",
                                "kind": "class",
                                "line": 1,
                                "qualified_name": "src/cache/token_cache.py::TokenCache",
                            }}
                        ]
                    }},
                    revision="r-consumer",
                )
                snapshot_schema = from_package(CONTEXT_SNAPSHOT_SCHEMA)
                graph_schema = from_package(CONTEXT_GRAPH_SCHEMA)
                receipt = {{
                    "schema": "simplicio.consumer-loop-receipt/v1",
                    "consumer": {{"name": "simplicio-loop", "shape": "simplicio-loop"}},
                    "install": {{
                        "module_file": simplicio_mapper.__file__,
                        "site_packages": "site-packages" in simplicio_mapper.__file__.replace("\\\\", "/").lower(),
                    }},
                    "snapshot": {{
                        "snapshot_schema": snapshot["schema"],
                        "graph_schema": snapshot["graph"]["schema"],
                        "snapshot_id": snapshot["snapshot_id"],
                        "repository_id": snapshot["repository_id"],
                        "omissions": snapshot["task"]["omissions"],
                    }},
                    "flags": {{
                        "needs_broader_context": snapshot["needs_broader_context"],
                        "drilldown_reversible": snapshot["drilldown"]["reversible"],
                        "fidelity_status": snapshot["fidelity"]["status"],
                    }},
                    "schema_titles": {{
                        "snapshot": snapshot_schema["$id"],
                        "graph": graph_schema["$id"],
                    }},
                }}
                print(json.dumps(receipt))
                """,
                cwd=tmp,
            )

            dev_cli_errors = validate_instance(dev_cli_receipt, _schema("dev-cli-consumer-receipt.schema.json"))
            self.assertEqual(dev_cli_errors, [], dev_cli_errors)
            self.assertTrue(dev_cli_receipt["install"]["site_packages"], dev_cli_receipt)
            self.assertIn("src/cache/token_cache.py", dev_cli_receipt["retrieval"]["selected_paths"])
            self.assertFalse(dev_cli_receipt["flags"]["abstained"])
            self.assertFalse(dev_cli_receipt["flags"]["needs_broader_context"])
            self.assertTrue(dev_cli_receipt["flags"]["fidelity_sufficient"])
            self.assertEqual(dev_cli_receipt["flags"]["target_status"], "included")

            loop_errors = validate_instance(loop_receipt, _schema("loop-consumer-receipt.schema.json"))
            self.assertEqual(loop_errors, [], loop_errors)
            self.assertTrue(loop_receipt["install"]["site_packages"], loop_receipt)
            self.assertTrue(loop_receipt["flags"]["needs_broader_context"])
            self.assertTrue(loop_receipt["flags"]["drilldown_reversible"])
            self.assertEqual(loop_receipt["flags"]["fidelity_status"], "partial")
            self.assertIn("call-graph", loop_receipt["snapshot"]["omissions"])


if __name__ == "__main__":
    unittest.main()
