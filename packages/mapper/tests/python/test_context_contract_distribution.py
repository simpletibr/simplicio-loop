"""Prove ContextSnapshot v1 consumers can validate from a wheel alone."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ContextContractDistributionTests(unittest.TestCase):
    timeout_seconds = 90

    def run_command(self, args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        # This test proves a consumer can install the built wheel into a
        # clean interpreter/venv and use it "from a wheel alone" -- a
        # PYTHONPATH pointed at this repo's own source checkout (as local
        # dev/CI harnesses often set, to run these very tests against an
        # editable-style checkout) would leak the raw source tree into
        # every subprocess spawned here and silently satisfy imports that
        # should only resolve from the installed wheel, defeating the
        # test's premise (issue #645).
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        try:
            return subprocess.run(
                args,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            self.fail(f"command timed out after {self.timeout_seconds}s: {exc.cmd}")

    def test_wheel_installs_contract_and_validates_without_optional_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            dist = temp / "dist"
            build = self.run_command(
                [sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", str(dist)], cwd=ROOT
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            wheel = next(dist.glob("simplicio_mapper-*.whl"))

            consumer = temp / "consumer"
            consumer.mkdir()
            venv = consumer / "venv"
            create_venv = self.run_command([sys.executable, "-m", "venv", str(venv)], cwd=consumer)
            self.assertEqual(create_venv.returncode, 0, create_venv.stderr)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            install = self.run_command(
                [str(python), "-m", "pip", "install", "--no-deps", "--disable-pip-version-check", str(wheel)],
                cwd=consumer,
            )
            self.assertEqual(install.returncode, 0, install.stderr)

            dependency_probe = self.run_command(
                [
                    str(python),
                    "-c",
                    "import importlib.util; raise SystemExit(any(importlib.util.find_spec(x) for x in ('diskcache','orjson','tiktoken')))",
                ],
                cwd=consumer,
            )
            self.assertEqual(dependency_probe.returncode, 0, dependency_probe.stderr)

            installed_contract = self.run_command(
                [
                    str(python),
                    "-c",
                    "from importlib.resources import files; "
                    "root=files('simplicio_mapper'); "
                    "required=('contracts/context-snapshot/v1/consumer-example/validate_snapshot.py',"
                    "'contracts/execution-context/v1/schemas/execution-context.schema.json',"
                    "'contracts/execution-context/v1/fixtures/valid/minimal/execution-context.json'); "
                    "raise SystemExit(not all(root.joinpath(path).is_file() for path in required))",
                ],
                cwd=consumer,
            )
            self.assertEqual(installed_contract.returncode, 0, installed_contract.stderr)

            materialize = self.run_command(
                [
                    str(python),
                    "-c",
                    "from importlib.resources import files; from pathlib import Path; "
                    "root=files('simplicio_mapper'); target=Path('contract-assets'); "
                    "paths=('contracts/context-snapshot/v1/consumer-example/validate_snapshot.py',"
                    "'contracts/context-snapshot/v1/fixtures/valid/minimal/context-snapshot.json',"
                    "'contracts/context-snapshot/v1/fixtures/invalid/dev-cli-incompatible/context-snapshot.json'); "
                    "[(target / path).parent.mkdir(parents=True, exist_ok=True) or "
                    "(target / path).write_bytes(root.joinpath(path).read_bytes()) for path in paths]",
                ],
                cwd=consumer,
            )
            self.assertEqual(materialize.returncode, 0, materialize.stderr)
            assets = consumer / "contract-assets" / "contracts" / "context-snapshot" / "v1"
            example = assets / "consumer-example" / "validate_snapshot.py"
            valid = assets / "fixtures" / "valid" / "minimal" / "context-snapshot.json"
            incompatible = assets / "fixtures" / "invalid" / "dev-cli-incompatible" / "context-snapshot.json"
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            for fixture, expected in ((valid, 0), (incompatible, 1)):
                try:
                    result = subprocess.run(
                        [str(python), str(example), str(fixture)],
                        cwd=consumer,
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout_seconds,
                    )
                except subprocess.TimeoutExpired as exc:
                    self.fail(f"consumer example timed out after {self.timeout_seconds}s: {exc.cmd}")
                self.assertEqual(result.returncode, expected, result.stderr)
                payload = json.loads(result.stdout)
                self.assertIsInstance(payload.get("reason_codes"), list)
                self.assertEqual(payload.get("valid"), expected == 0)
