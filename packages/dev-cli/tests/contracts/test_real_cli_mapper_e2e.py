"""Real-process E2E coverage for the Dev CLI and Mapper contract (#201)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    assert executable is not None, f"required E2E executable is not on PATH: {name}"
    return executable


def _json_stdout(process: subprocess.CompletedProcess[str], command: str) -> dict:
    assert process.returncode == 0, (
        f"{command} exited with {process.returncode}\nstdout:\n{process.stdout}\nstderr:\n{process.stderr}"
    )
    assert "Traceback" not in process.stderr, process.stderr
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"{command} did not emit one JSON document on stdout\n"
            f"stdout:\n{process.stdout}\n"
            f"stderr:\n{process.stderr}"
        ) from error
    assert isinstance(payload, dict), f"{command} stdout must be a JSON object"
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_console_entrypoints_map_and_inspect_fresh_project(sample_project: Path) -> None:
    mapper = _required_executable("simplicio-mapper")
    dev_cli = _required_executable("simplicio-dev-cli")

    artifacts = sample_project / ".simplicio-loop"
    shutil.rmtree(artifacts)
    source = sample_project / "src" / "app.py"
    source_before = _sha256(source)

    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update(
        {
            "SIMPLICIO_SKIP_AUTO_INIT": "1",
            "SIMPLICIO_DEV_CLI_NO_RUNTIME_PRECEDENT": "1",
            "SIMPLICIO_MAPPER_CLI": "1",
            "PYTHONPATH": os.pathsep.join(
                part for part in (str(project_root), env.get("PYTHONPATH", "")) if part
            ),
        }
    )

    mapper_process = subprocess.run(
        [mapper, "index", str(sample_project), "--json"],
        cwd=sample_project,
        env=env,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=120,
        check=False,
    )
    mapper_payload = _json_stdout(mapper_process, "simplicio-mapper index")
    assert mapper_payload["schema"] == "simplicio.mapper-index/v1"
    assert mapper_payload["status"] == "updated"
    assert mapper_payload.get("error") is None
    assert mapper_payload.get("skipped_reason") is None
    assert mapper_payload["counts"]["files"] >= 1

    project_map_path = artifacts / "project-map.json"
    assert Path(mapper_payload["paths"]["project_map"]).resolve() == project_map_path.resolve()
    assert project_map_path.is_file()
    project_map = json.loads(project_map_path.read_text(encoding="utf-8"))
    assert project_map["schema"] == "simplicio.project-map/v1"

    inspect_process = subprocess.run(
        [
            dev_cli,
            "inspect",
            "src/app.py",
            "--root",
            str(sample_project),
            "--goal",
            "fix the greeting",
            "--json",
        ],
        cwd=sample_project,
        env=env,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=120,
        check=False,
    )
    inspect_payload = _json_stdout(inspect_process, "simplicio-dev-cli inspect")

    assert inspect_payload["schema"] == "simplicio.dev-cli.inspect/v1"
    assert inspect_payload["target"] == "src/app.py"
    assert inspect_payload["artifacts"]["project_map"]["present"] is True
    assert inspect_payload["artifacts"]["inspection"]["schema"] == "simplicio.map-inspection/v1"
    assert any(item.get("path") == "src/app.py" for item in inspect_payload["relevant_files"])
    assert "src/app.py" in inspect_payload["context"]
    assert _sha256(source) == source_before
