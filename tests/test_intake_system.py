"""System test for `simplicio-loop intake` (issue #1312).

Real CLI: normalize a Jira-shaped export with 3 items (one depends on
another) into tasks.md, then arm a run with `simplicio-loop prepare` against
a real temp git repo and assert the compiled task contract reports all 3
tasks with the dependency wired through. `prepare` may still end up
`blocked` further downstream (mapper/operator targeting on a bare repo with
no real source files) — that is unrelated to intake; this test stops at the
frozen task-contract artifact `prepare` writes before that later stage runs,
per the task's own "stop at prepare" guidance for a low-CPU machine.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = [sys.executable, "-m", "simplicio_loop.cli"]

JIRA_FIXTURE = [
    {
        "key": "ABC-1",
        "fields": {
            "summary": "Prerequisite work",
            "description": "Lay the groundwork.",
            "labels": ["infra"],
        },
    },
    {
        "key": "ABC-2",
        "fields": {
            "summary": "Ship the feature",
            "description": "Build on the groundwork.",
            "labels": ["feature"],
            "issuelinks": [
                {
                    "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
                    "inwardIssue": {"key": "ABC-1"},
                }
            ],
        },
    },
    {
        "key": "ABC-3",
        "fields": {
            "summary": "Polish and document",
            "description": "Final pass.",
            "labels": [],
        },
    },
]


def _run(cmd, cwd):
    # Force the CLI subprocess to import THIS checkout's simplicio_loop package
    # rather than whatever editable install happens to be active on PATH (a
    # worktree may have its own, unrelated editable install registered).
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd, timeout=60, stdin=subprocess.DEVNULL, env=env
    )


def _git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)


def test_intake_from_jira_json_to_prepare(tmp_path):
    jira_path = tmp_path / "jira.json"
    jira_path.write_text(json.dumps(JIRA_FIXTURE), encoding="utf-8")

    _git_repo(str(tmp_path))

    intake_result = _run(
        CLI + ["intake", "--from", str(jira_path), "--repo", str(tmp_path), "--out", "tasks.md", "--json"],
        cwd=str(tmp_path),
    )
    assert intake_result.returncode == 0, intake_result.stderr
    summary = json.loads(intake_result.stdout)
    assert summary["item_count"] == 3
    tasks_md = tmp_path / "tasks.md"
    assert tasks_md.is_file()

    subprocess.run(["git", "add", "tasks.md"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "intake"], cwd=str(tmp_path), check=True)

    # Every flow goes through Mapper + Fast first (issue #1318).
    oriented = _run(CLI + ["orient", "--repo", str(tmp_path), "--task", "survey the repo", "--json"],
                    cwd=str(tmp_path))
    assert oriented.returncode == 0, oriented.stderr[-2000:]
    prepare_result = _run(
        CLI + ["prepare", "--task", "tasks.md", "--repo", str(tmp_path)],
        cwd=str(tmp_path),
    )
    payload = json.loads(prepare_result.stdout)
    assert payload["schema"] == "simplicio.prepare-receipt/v1"
    run_dir = payload["run_dir"]
    assert run_dir, prepare_result.stdout

    contract_path = os.path.join(run_dir, "task-contract.json")
    assert os.path.isfile(contract_path), "prepare must freeze task-contract.json before any later gate"
    contract = json.loads(open(contract_path, encoding="utf-8").read())
    assert contract["task_count"] == 3

    tasks = contract["tasks"]
    dep_task = tasks[1]  # ABC-2 depends on ABC-1 -> second item in intake order
    dep_items = dep_task["dependencies"]["items"]
    assert any("task 1" in dep.lower() for dep in dep_items), dep_items

    state_path = os.path.join(run_dir, "state.json")
    state = json.loads(open(state_path, encoding="utf-8").read())
    assert state["task_count"] == 3
    assert state["validation"]["errors"] == []
