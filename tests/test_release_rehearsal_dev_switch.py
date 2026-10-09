"""Release blocker: a dev-only switch (SIMPLICIO_247_NO_LOGIN) under simplicio_loop/ fails the release rehearsal."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.release_rehearsal as rr

REPO_ROOT = Path(__file__).resolve().parents[1]
SWITCH = "SIMPLICIO_247_NO_LOGIN"


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_switch_name_is_the_one_the_watcher_reads():
    from simplicio_loop.watcher247 import subscription

    assert rr.DEV_SWITCHES == (subscription.NO_LOGIN_ENV,) == (SWITCH,)


def test_finds_the_switch_anywhere_under_simplicio_loop(tmp_path):
    repo = _repo(tmp_path, {"simplicio_loop/a/b/deep.py": f'os.environ.get("{SWITCH}")\n', "simplicio_loop/other.py": "clean\n"})
    assert rr.find_dev_switches(repo) == {SWITCH: ["simplicio_loop/a/b/deep.py"]}


def test_ignores_everything_outside_simplicio_loop_and_bytecode(tmp_path):
    repo = _repo(tmp_path, {"scripts/x.py": SWITCH, "tests/t.py": SWITCH, "docs/RELEASE.md": SWITCH,
                            "simplicio_loop/clean.py": "no switch here\n", "simplicio_loop/__pycache__/m.pyc": SWITCH})
    assert rr.find_dev_switches(repo) == {}


def test_a_missing_package_dir_is_clean(tmp_path):
    assert rr.find_dev_switches(tmp_path) == {}


def test_rehearsal_fails_closed_before_any_other_step(tmp_path):
    repo = _repo(tmp_path, {"simplicio_loop/tick.py": f'x = "{SWITCH}"\n'})
    result = rr.run_rehearsal(repo, keep=False)
    assert result["ok"] is False and result["reason_code"] == "dev_switch_present"
    assert result["steps"]["dev_switches"] == {"ok": False, "found": {SWITCH: ["simplicio_loop/tick.py"]}}
    assert "governance_gate" not in result["steps"] and "export" not in result["steps"]


def test_cli_exit_code_and_files(tmp_path, capsys):
    dirty = _repo(tmp_path / "dirty", {"simplicio_loop/tick.py": SWITCH})
    clean = _repo(tmp_path / "clean", {"simplicio_loop/tick.py": "nothing\n"})
    assert rr.main(["dev-switches", "--repo", str(dirty)]) == 1
    assert json.loads(capsys.readouterr().out) == {"ok": False, "found": {SWITCH: ["simplicio_loop/tick.py"]}}
    assert rr.main(["dev-switches", "--repo", str(clean)]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "found": {}}


def test_the_real_repo_is_blocked_exactly_while_the_switch_exists():
    found = rr.find_dev_switches(REPO_ROOT)
    if not found:
        pytest.skip("the dev switch is gone: the release is not blocked by it")
    assert SWITCH in found and "simplicio_loop/watcher247/subscription.py" in found[SWITCH]
    result = rr.run_rehearsal(REPO_ROOT, keep=False)  # returns at the first step, so it is cheap
    assert result["ok"] is False and result["reason_code"] == "dev_switch_present"


def test_the_release_checklist_names_the_blocker_and_the_command():
    text = (REPO_ROOT / "docs" / "RELEASE.md").read_text(encoding="utf-8")
    assert SWITCH in text and "release_rehearsal.py dev-switches" in text
    assert "Release blockers" in text
