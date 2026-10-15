"""System test for docs/FIRST_RUN.md (issue #1812, acceptance criterion 4).

The commands of the block marked ```bash first-run``` run through a `simplicio-loop` shim on PATH, in a
throwaway git repository. `<run_id>` is replaced by the run that `prepare` printed. The model writes the
plan between `prepare` and `wave`, so this test stops at the last deterministic step: `wave` without a plan
is BLOCKED at plan_required, and its top-level block and its one `next:` line are asserted.

The task file of the doc is produced by `prepare --example`, so the example is exercised here too.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "FIRST_RUN.md"

pytestmark = pytest.mark.skipif(
    shutil.which("simplicio-mapper") is None or shutil.which("simplicio-dev-cli") is None,
    reason="simplicio-mapper / simplicio-dev-cli (bound operators) not installed",
)


def _first_run_block() -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(r"```bash first-run\n(.*?)```", text, re.S)
    assert match, "docs/FIRST_RUN.md must hold a ```bash first-run``` block"
    return [line.strip() for line in match.group(1).splitlines() if line.strip() and not line.startswith("#")]


def _shim(bin_dir: Path) -> None:
    """A `simplicio-loop` on PATH that runs this checkout, not an installed copy."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "simplicio-loop"
    script.write_text(
        "#!/bin/sh\n"
        f"exec {sys.executable!r} -c 'import sys; from simplicio_loop.cli import main; "
        "sys.exit(main(sys.argv[1:]))' \"$@\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


def _repo(root: Path) -> Path:
    """The empty repository of step 2 in the doc, with one initial commit."""
    (root / "calc").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "calc" / "ops.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "calc" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "test_ops.py").write_text(
        "def test_add():\n    from calc.ops import add\n    assert add(1, 2) == 3\n", encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "initial calc"], cwd=root, check=True, env=env)
    return root


def _run(line: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(line, shell=True, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)


def test_the_first_run_block_runs_and_stops_at_plan_required_with_a_next_line(tmp_path):
    block = _first_run_block()
    assert [line.split()[0] for line in block] == ["simplicio-loop"] * len(block)
    assert "<run_id>" in block[-1], "the last line of the block is the wave step"

    repo = _repo(tmp_path / "calc")
    shim = tmp_path / "bin"
    _shim(shim)
    env = {**os.environ,
           "PATH": f"{shim}{os.pathsep}{os.environ.get('PATH', '')}",
           "PYTHONPATH": os.pathsep.join([str(REPO), str(REPO / "packages" / "mapper"),
                                          str(REPO / "packages" / "dev-cli")]),
           "SIMPLICIO_LOOP_DAEMON": "0"}

    run_id = ""
    results: dict[str, subprocess.CompletedProcess[str]] = {}
    for line in block:
        command = line.replace("<run_id>", run_id) if "<run_id>" in line else line
        result = _run(command, repo, env)
        results[command] = result
        if command.startswith("simplicio-loop prepare --repo"):
            run_id = json.loads(result.stdout)["run_id"]
            assert run_id.startswith("run-")

    def _result(prefix: str) -> subprocess.CompletedProcess[str]:
        matches = [r for c, r in results.items() if c.startswith(prefix)]
        assert len(matches) == 1, prefix
        return matches[0]

    assert _result("simplicio-loop preflight").returncode == 0, _result("simplicio-loop preflight").stderr
    orient = _result("simplicio-loop orient")
    assert orient.returncode == 0, orient.stderr
    assert _result("simplicio-loop prepare --example").returncode == 0
    assert (repo / "task.md").is_file()
    assert "Scenario 1:" in (repo / "task.md").read_text(encoding="utf-8")
    prepared = _result("simplicio-loop prepare --repo")
    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(prepared.stdout)["status"] == "prepared"

    wave = _result("simplicio-loop wave ")
    assert wave.returncode == 2
    payload = json.loads(wave.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["plan_required"]["schema"] == "simplicio.dev-cli.edit-plan/v1"
    assert payload["plan_required"]["schema_path"].endswith("edit-plan.schema.json")
    assert payload["plan_required"]["apply_steps"][2].startswith("simplicio-loop wave ")

    next_lines = [line for line in wave.stderr.splitlines() if line.startswith("next:")]
    assert len(next_lines) == 1
    assert f"run {run_id} is blocked at plan_required" in next_lines[0]
    assert "simplicio.dev-cli.edit-plan/v1" in next_lines[0]


def test_the_first_run_task_is_the_example_and_parses(tmp_path):
    """The block's task file (`prepare --example`) compiles with no contract errors."""
    shim = tmp_path / "bin"
    _shim(shim)
    env = {**os.environ, "PATH": f"{shim}{os.pathsep}{os.environ.get('PATH', '')}",
           "PYTHONPATH": str(REPO), "SIMPLICIO_LOOP_DAEMON": "0"}
    result = _run("simplicio-loop prepare --example", tmp_path, env)
    assert result.returncode == 0, result.stderr
    from simplicio_loop import task_contract

    compiled = task_contract.compile_many(result.stdout)
    assert compiled["task_count"] == 1
    assert task_contract.validate_contract(compiled["tasks"][0])["errors"] == []
