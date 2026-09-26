"""issue #1346 part 2: the WHOLE ``orient``/``orient --brief`` call shares one
deadline. #1339 bounded only the Mapper index; the Mapper ``orient`` survey
subprocess that follows was still unbounded (4m13s cold on the monorepo).

A real fake ``simplicio-mapper`` on PATH: ``index`` is instant, ``orient``
sleeps past the budget. No mocking of the process boundary.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from simplicio_loop import cli_impl


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"],
                   cwd=str(repo), check=True)
    return repo


@pytest.fixture()
def slow_orient_mapper(tmp_path, monkeypatch):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    script = bin_dir / "simplicio-mapper"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time, pathlib\n"
        "args = sys.argv[1:]\n"
        "if args and args[0] == 'index':\n"
        "    root = pathlib.Path(args[1])\n"
        "    (root / '.simplicio-loop').mkdir(parents=True, exist_ok=True)\n"
        "    (root / '.simplicio-loop' / 'project-map.json').write_text(json.dumps({'files': []}))\n"
        "    print(json.dumps({'status': 'ok'}))\n"
        "else:\n"
        "    time.sleep(30)\n"
        "    print(json.dumps({'status': 'ok'}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("SIMPLICIO_LOOP_ORIENT_BUDGET_S", "2")
    return bin_dir


@pytest.mark.parametrize("brief", [False, True])
def test_orient_total_wall_stays_within_budget(tmp_path, slow_orient_mapper, capsys, brief):
    repo = _git_repo(tmp_path)
    started = time.monotonic()
    if brief:
        code = cli_impl.orient(str(repo), "t", brief=True, tasks=["t"])
    else:
        code = cli_impl.orient(str(repo), "t")
    elapsed = time.monotonic() - started
    payload = json.loads(capsys.readouterr().out)
    assert elapsed < 10, elapsed
    assert code != 0
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "orient_budget_exceeded", payload
