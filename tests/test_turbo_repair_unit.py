"""3.45.2: the repair after a failed --verify may repeat `find: ""` for a file the first plan created.

dev-cli refuses that as `create_target_exists`, so on a create task the repair never got a chance (5 of 15 repair
attempts in the benchmark). The repair path turns such an operation into a whole-file replacement: `find` is the
file's current text. Only that path does; the first plan and host mode keep dev-cli's refusal.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

from simplicio_loop import turbo_provider
from simplicio_loop.cli_impl import main as cli_main
from simplicio_loop.turbo import _rewrite_existing_creates, repair_with_test_output

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "bench" / "llm_ab" / "fixture_hard"
SOLUTION = ROOT / "tests" / "fixtures" / "llm_ab_hard_solution"
HIDDEN = ROOT / "bench" / "llm_ab" / "hidden" / "check_hard.py"
EXISTS_LINE = "the files above already exist; to rewrite one, send its whole current text as find"
STUB = "def order_total(items, coupon=None):\n    return 0\n"


def _seed(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"],
                 ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    return repo


def _reply(operations):
    return {"ok": True, "content": json.dumps({"operations": operations}), "prompt_tokens": 100,
            "cached_tokens": 80, "completion_tokens": 40, "cost": 0.0001}


def test_a_create_task_whose_repair_repeats_the_empty_find_ends_ok(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    good = (SOLUTION / "pricing.py").read_text(encoding="utf-8")
    turns = []

    async def fake_complete(arm, messages, **kwargs):
        turns.append(messages[-1]["content"])
        # Both plans are creates: the repair repeats `find: ""` for the file the first plan already wrote.
        return _reply([{"path": "pricing.py", "find": "", "replace": STUB if len(turns) == 1 else good}])

    monkeypatch.setattr(turbo_provider, "complete", fake_complete)
    verify = f'"{sys.executable}" "{HIDDEN}" --stage 1'
    rc = cli_main(["turbo", "--provider", "openrouter", "--repo", str(repo),
                   "--task", "Create pricing.py with order_total as specified.", "--verify", verify])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0, out
    assert out["status"] == "ok" and out["verify"]["passed"] is True and out["model_calls"] == 2
    assert out["verify_retry"] == {"attempted": True, "applied": True, "reason": None, "passed": True}
    assert (repo / "pricing.py").read_text(encoding="utf-8") == good
    assert "The tests failed after your plan was applied" in turns[1] and EXISTS_LINE in turns[1]


def test_the_repair_prompt_tells_the_model_the_listed_files_already_exist(tmp_path, monkeypatch):
    repo = _seed(tmp_path)
    (repo / ".simplicio-loop").mkdir()
    (repo / ".simplicio-loop" / "project-map.json").write_text('{"files":[]}', encoding="utf-8")
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", AsyncMock(return_value=None))
    seen = []
    tasks = [{"index": 1, "text": "Fix inventory.py", "target": "inventory.py", "context": [], "depends_on": []}]

    async def complete(arm, messages, **kwargs):
        seen.append(messages)
        return _reply([{"path": "notes.txt", "find": "", "replace": "x\n"}])

    result = asyncio.run(repair_with_test_output(repo, tasks, complete, "FAIL: nope"))
    last = seen[0][-1]["content"]
    assert last.startswith("The tests failed after your plan was applied:\nFAIL: nope")
    assert EXISTS_LINE in last and last.rstrip().endswith("Return a JSON plan that makes them pass.")
    assert "Current inventory.py:" in seen[0][1]["content"]  # the files the line talks about are the ones above
    assert result["applied"] is True


def test_only_an_empty_find_on_an_existing_file_becomes_a_whole_file_replacement(tmp_path):
    (tmp_path / "a.py").write_text("old\n", encoding="utf-8")
    (tmp_path / "empty.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    rewritten = _rewrite_existing_creates(tmp_path, [
        {"path": "a.py", "find": "", "replace": "new\n"},
        {"path": "a.py", "replace": "no find key at all\n"},
        {"path": "fresh.py", "find": "", "replace": "fresh\n"},
        {"path": "a.py", "find": "old", "replace": "x"},
        {"path": "empty.py", "find": "", "replace": "z"},
        {"path": "pkg", "find": "", "replace": "z"},
        {"path": "../outside.py", "find": "", "replace": "z"},
        {"path": "/etc/hosts", "find": "", "replace": "z"},
    ])
    assert rewritten == [
        {"path": "a.py", "find": "old\n", "replace": "new\n"},
        {"path": "a.py", "find": "old\n", "replace": "no find key at all\n"},
        {"path": "fresh.py", "find": "", "replace": "fresh\n"},  # a new file is still a create
        {"path": "a.py", "find": "old", "replace": "x"},  # a real find is left to dev-cli
        {"path": "empty.py", "find": "", "replace": "z"},  # an empty file cannot be a find
        {"path": "pkg", "find": "", "replace": "z"},
        {"path": "../outside.py", "find": "", "replace": "z"},  # never read outside the repository
        {"path": "/etc/hosts", "find": "", "replace": "z"},
    ]


def test_the_rewrite_keeps_the_files_own_line_endings_and_leaves_what_it_cannot_read(tmp_path):
    (tmp_path / "crlf.txt").write_bytes(b"a\r\nb\r\n")
    (tmp_path / "latin1.txt").write_bytes("caf\xe9\n".encode("latin-1"))
    rewritten = _rewrite_existing_creates(tmp_path, [
        {"path": "crlf.txt", "find": "", "replace": "x"},
        {"path": "latin1.txt", "find": "", "replace": "x"},
    ])
    assert rewritten[0]["find"] == "a\r\nb\r\n"  # byte exact: dev-cli matches the file as it is on disk
    assert rewritten[1] == {"path": "latin1.txt", "find": "", "replace": "x"}  # not UTF-8: dev-cli refuses it


def test_the_rewrite_does_not_mutate_the_operations_it_was_given(tmp_path):
    (tmp_path / "a.py").write_text("old\n", encoding="utf-8")
    operations = [{"path": "a.py", "find": "", "replace": "new\n"}]
    _rewrite_existing_creates(tmp_path, operations)
    assert operations == [{"path": "a.py", "find": "", "replace": "new\n"}]
