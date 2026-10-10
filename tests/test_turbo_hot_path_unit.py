"""The turbo hot path (#1675): no eager import of ``runner``, ``jsonschema`` or ``dashboard.cli``, and one dev-cli spawn per apply."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import turbo

ROOT = Path(__file__).resolve().parent.parent
HEAVY =("simplicio_loop.runner", "jsonschema", "simplicio_loop.dashboard.cli")

_PROBE = """
import json, sys
from simplicio_loop.cli_impl import main
try:
    main(sys.argv[1:])
except SystemExit:
    pass
print("LOADED " + json.dumps(sorted(name for name in %r if name in sys.modules)))
""" % (HEAVY,)


def _loaded(args: list[str], cwd: Path) -> list[str]:
    done = subprocess.run([sys.executable, "-c", _PROBE, *args], cwd=cwd, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=120, env={**os.environ, "SIMPLICIO_LOOP_DAEMON": "0", "PYTHONPATH": str(ROOT)})
    line = next((l for l in done.stdout.splitlines() if l.startswith("LOADED ")), None)
    assert line is not None, done.stdout + done.stderr
    return json.loads(line[len("LOADED "):])


def test_turbo_task_does_not_import_the_heavy_modules(tmp_path):
    assert _loaded(["turbo", "--repo", str(tmp_path), "--task", "rename a to b"], tmp_path) == []


def test_turbo_apply_does_not_import_the_heavy_modules(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text('{"operations": []}', encoding="utf-8")
    assert _loaded(["turbo", "--repo", str(tmp_path), "--apply", str(plan)], tmp_path) == []


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("a\n", encoding="utf-8")
    return tmp_path


def _recording_dev_cli(tmp_path: Path, stdout: str) -> tuple[str, Path]:
    calls = tmp_path / "calls.txt"
    script = tmp_path / "dev-cli"
    script.write_text(f"#!{sys.executable}\nimport sys\nopen({str(calls)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
                      f"print({stdout!r})\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script), calls


OPS = [{"path": "src/a.txt", "find": "a", "replace": "b"}]


def test_apply_spawns_dev_cli_once(tmp_path):
    (tmp_path / "repo").mkdir()
    repo = _repo(tmp_path / "repo")
    receipt = json.dumps({"schema": "simplicio.dev-cli.edit-receipt/v1", "applied": True})
    binary, calls = _recording_dev_cli(tmp_path, receipt)
    result = asyncio.run(turbo.apply_plan(repo, OPS, "t", binary))
    lines = calls.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and "--compile" in lines[0] and "--apply" in lines[0]
    assert result["applied"] is True


def test_apply_counts_operator_exec_calls(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    repo = _repo(tmp_path / "repo")
    seen: list[list[str]] = []

    async def fake_run(cmd, timeout=None):
        seen.append(list(cmd))
        return 0, json.dumps({"schema": "simplicio.dev-cli.edit-receipt/v1", "applied": True}), ""

    monkeypatch.setattr(turbo.operator_exec, "run", fake_run)
    result = asyncio.run(turbo.apply_plan(repo, OPS, "t", "dev-cli"))
    assert len(seen) == 1 and result["applied"] is True


def test_apply_falls_back_to_a_separate_apply_for_a_dev_cli_that_only_compiles(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    repo = _repo(tmp_path / "repo")
    seen: list[list[str]] = []

    async def old_dev_cli(cmd, timeout=None):
        seen.append(list(cmd))
        if "--compile" in cmd:
            return 0, json.dumps({"schema": "simplicio.dev-cli.edit-compile/v1", "status": "ok"}), ""
        return 0, json.dumps({"schema": "simplicio.dev-cli.edit-receipt/v1", "applied": True}), ""

    monkeypatch.setattr(turbo.operator_exec, "run", old_dev_cli)
    result = asyncio.run(turbo.apply_plan(repo, OPS, "t", "dev-cli"))
    assert len(seen) == 2 and "--compile" not in seen[1] and "--apply" in seen[1]
    assert result["applied"] is True


@pytest.mark.parametrize("returncode", [1, 2])
def test_apply_stops_at_the_first_refusal(tmp_path, monkeypatch, returncode):
    (tmp_path / "repo").mkdir()
    repo = _repo(tmp_path / "repo")
    seen: list[list[str]] = []

    async def refusing(cmd, timeout=None):
        seen.append(list(cmd))
        return returncode, "refused", ""

    monkeypatch.setattr(turbo.operator_exec, "run", refusing)
    result = asyncio.run(turbo.apply_plan(repo, OPS, "t", "dev-cli"))
    assert len(seen) == 1 and result["applied"] is False
