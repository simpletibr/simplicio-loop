"""Issue #1812, observations 2-5: every BLOCKED result of `squads plan`, `prepare` and `wave` prints a
plain `next:` line that names the exact command or the exact missing element (line number for task files),
and `prepare --example` prints a task file that parses.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import cli_impl, next_step, runner_core, runner_preflight, task_contract

ISSUE_OK = {"number": 101, "title": "Setup db", "body": "", "labels": [], "paths": ["db/**"]}


def _next_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("next:")]


# --- observation 2: squads plan -------------------------------------------------------------------------------------


def test_issue_list_with_an_id_key_names_number_in_the_next_line(capsys):
    code = cli_impl.main(["squads", "plan", "--issues", json.dumps([{"id": 1, "title": "x", "body": ""}]), "--json"])
    captured = capsys.readouterr()

    assert code == 2
    lines = _next_lines(captured.err)
    assert len(lines) == 1
    assert '"number"' in lines[0] and '"id"' in lines[0]
    assert "issues[0]" in lines[0]
    assert "number" in json.loads(captured.out)["reason"]


@pytest.mark.parametrize("raw", [
    "not json {",
    json.dumps(["just", "strings"]),
    json.dumps([{"number": "abc", "title": "bad"}]),
])
def test_every_blocked_squads_plan_result_prints_one_next_line(raw, capsys):
    code = cli_impl.main(["squads", "plan", "--issues", raw, "--json"])
    captured = capsys.readouterr()

    assert code == 2
    assert json.loads(captured.out)["status"] == "BLOCKED"
    assert len(_next_lines(captured.err)) == 1


def test_squads_plan_help_shows_the_issue_shape(capsys):
    with pytest.raises(SystemExit):
        cli_impl.main(["squads", "plan", "--help"])
    text = capsys.readouterr().out
    for key in ('"number"', '"title"', '"paths"', '"depends_on"'):
        assert key in text


def test_a_valid_issue_list_has_no_next_line(capsys):
    code = cli_impl.main(["squads", "plan", "--issues", json.dumps([ISSUE_OK]), "--json"])
    captured = capsys.readouterr()
    assert code == 0
    assert _next_lines(captured.err) == []


# --- observation 3: prepare task contract ---------------------------------------------------------------------------

HASH_HEADING_TASK = """System: calc
Feature: add mul(a, b)
Type: Feature

AS a calc user
I WANT a mul(a, b) function in calc/ops.py
SO THAT I can multiply numbers

#### 1. Acceptance Criteria

Scenario 1: mul multiplies two numbers
  Given calc/ops.py
  When I call mul(3, 4)
  Then it returns 12 [RN01]

2. Business Rules

RN01 - mul lives in calc/ops.py next to add.

8. Additional Information

Independent verifier: `python3 -m pytest -q`
"""


def test_a_hash_prefixed_section_heading_is_reported_with_its_line_number():
    hints = task_contract.contract_hints(HASH_HEADING_TASK)

    assert hints, "the contract problem must be located"
    first = hints[0]
    assert first["line"] == 9
    assert first["found"] == "#### 1. Acceptance Criteria"
    assert "1. Acceptance Criteria" in first["fix"] and "without '#'" in first["fix"]


def test_prepare_prints_the_offending_task_line_as_its_next_line(tmp_path, monkeypatch, capsys):
    from simplicio_loop import survey

    task = tmp_path / "task.md"
    task.write_text(HASH_HEADING_TASK, encoding="utf-8")
    monkeypatch.setattr(survey, "provenance", lambda repo: {"ok": True})  # past the mapper gate

    code = cli_impl.main(["prepare", "--repo", str(tmp_path), "--task", str(task)])
    captured = capsys.readouterr()

    assert code == 2
    payload = json.loads(captured.out)
    assert payload["reason_code"] == "prepare_failed"
    assert "invalid task contract" in payload["error"]
    lines = _next_lines(captured.err)
    assert len(lines) == 1
    assert "line 9" in lines[0] and "1. Acceptance Criteria" in lines[0] and "without '#'" in lines[0]
    assert "simplicio-loop prepare --example" in lines[0]


def test_a_scenario_without_then_is_located_at_the_scenario_line():
    text = HASH_HEADING_TASK.replace("#### 1. Acceptance Criteria", "1. Acceptance Criteria").replace(
        "  Then it returns 12 [RN01]\n", "")
    hints = task_contract.contract_hints(text)
    scenario_line = next(i for i, line in enumerate(text.splitlines(), start=1) if line.startswith("Scenario 1:"))
    assert any(h["line"] == scenario_line and "Then" in h["problem"] for h in hints)


def test_missing_acceptance_heading_is_reported_once_with_the_expected_line():
    text = "System: calc\nFeature: x\nType: Feature\n\nScenario 1: a\n  Given a\n  When b\n  Then c\n"
    hints = task_contract.contract_hints(text)
    assert hints and "1. Acceptance Criteria" in hints[0]["fix"]


def test_prepare_missing_mapper_survey_prints_the_orient_command(tmp_path, capsys):
    task = tmp_path / "task.md"
    task.write_text("System: calc\nFeature: add mul\n", encoding="utf-8")

    code = cli_impl.main(["prepare", "--repo", str(tmp_path), "--task", str(task)])
    captured = capsys.readouterr()

    assert code == 2
    lines = _next_lines(captured.err)
    assert len(lines) == 1
    assert lines[0].startswith("next: simplicio-loop orient --brief --repo ")


MISSING_TARGETS_MESSAGE = ("mapper-derived plan failed validation: "
                           "task[1] target_missing_without_to_create:calc/ops.py, "
                           "task[1] target_missing_without_to_create:tests/test_ops.py")


@pytest.mark.parametrize("blocker", [
    MISSING_TARGETS_MESSAGE,
    {"kind": "run_preflight", "reason_code": "no_authorized_target", "message": MISSING_TARGETS_MESSAGE},
], ids=["text", "mapping"])
def test_prepare_blocked_on_a_missing_target_names_the_paths_and_the_new_file_syntax(tmp_path, monkeypatch, capsys,
                                                                                     blocker):
    """A task that names files the repo lacks is blocked with target_missing_without_to_create. The one next
    line names every missing path and the task-file lines that declare a new file, not a generic status command."""
    from simplicio_loop import survey

    monkeypatch.setattr(survey, "provenance", lambda repo: {"ok": True})  # past the mapper gate
    monkeypatch.setattr(cli_impl, "arm_run", lambda *args, **kwargs: {
        "manifest": {"run_id": "run-x"}, "run_dir": str(tmp_path / "run-x"),
        "state": {"phase": "blocked", "blockers": [blocker]},
    })
    task = tmp_path / "task.md"
    task.write_text("System: calc\nFeature: add mul\n", encoding="utf-8")

    code = cli_impl.main(["prepare", "--repo", str(tmp_path), "--task", str(task)])
    captured = capsys.readouterr()

    assert code == 2
    lines = _next_lines(captured.err)
    assert len(lines) == 1
    assert lines[0].startswith(f"next: calc/ops.py, tests/test_ops.py not found in {tmp_path}")
    assert "'Type: Creation'" in lines[0] and "'Target: <path>'" in lines[0]


def test_the_new_file_syntax_the_next_line_names_is_the_one_the_planner_reads(tmp_path):
    from simplicio_loop import runner_plan

    text = "System: calc\nFeature: add mul\nType: Creation\nTarget: calc/ops.py\n"
    assert runner_plan._extract_declared_task_target(text, tmp_path) == ["calc/ops.py"]
    assert runner_plan._is_creation_task_type("Creation")


# --- observation 4: stale mapper context lists changed paths -------------------------------------------------------


def _git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    for index in range(7):
        (root / f"f{index}.py").write_text(f"x = {index}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True, env=env)
    return root


def test_stale_context_message_lists_the_first_five_changed_paths_and_says_orient(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    planned = runner_core._repo_fingerprint(repo)
    for index in range(7):
        (repo / f"f{index}.py").write_text(f"x = {index + 100}\n", encoding="utf-8")

    message = runner_preflight._stale_context_message(repo, planned)

    assert message.startswith("stale mapper context: repository changed after planning")
    assert "first 5 of 7" in message
    listed = [name for name in (f"f{i}.py" for i in range(7)) if name in message]
    assert len(listed) == 5
    assert "re-run `orient`" in message


def test_stale_context_message_names_an_untracked_task_file_written_after_orient(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    planned = runner_core._repo_fingerprint(repo)
    (repo / "task-notes.md").write_text("written inside the repo after orient\n", encoding="utf-8")

    message = runner_preflight._stale_context_message(repo, planned)

    assert "task-notes.md" in message and "first 1 of 1" in message


# --- observation 5: wave with plan_required -------------------------------------------------------------------------


def test_plan_required_is_printed_at_top_level_with_schema_and_apply_steps(tmp_path):
    run_dir = tmp_path / ".simplicio-loop" / "loop-runs" / "run-x"
    run_dir.mkdir(parents=True)
    payload = {
        "schema": "simplicio.loop-execution/v1", "status": "BLOCKED", "verified": False,
        "reason_code": "flow_not_terminal", "run_id": "run-x",
        "state": {"phase": "blocked", "operator": {"reason_code": "plan_required", "target": "calc/ops.py"}},
    }

    annotated = next_step.annotate_blocked(payload, repo=str(tmp_path), run_id="run-x", flow="wave", run_dir=run_dir)

    block = annotated["plan_required"]
    assert block["schema"] == "simplicio.dev-cli.edit-plan/v1"
    assert block["schema_path"] == "packages/dev-cli/contracts/dev-cli-edit/edit-plan.schema.json"
    assert block["apply_command"].startswith("simplicio-loop wave ")
    assert block["apply_steps"][0].startswith("simplicio-loop prepare --repo ")
    assert block["apply_steps"][2].startswith("simplicio-loop wave ")


def test_wave_blocked_on_plan_required_prints_exactly_one_next_line(tmp_path, capsys):
    run_dir = tmp_path / ".simplicio-loop" / "loop-runs" / "run-x"
    run_dir.mkdir(parents=True)
    payload = {"status": "BLOCKED", "reason_code": "flow_not_terminal", "run_id": "run-x",
               "state": {"phase": "blocked", "operator": {"reason_code": "plan_required"}}}

    next_step.annotate_blocked(payload, repo=str(tmp_path), run_id="run-x", flow="wave", run_dir=run_dir)

    lines = _next_lines(capsys.readouterr().err)
    assert len(lines) == 1
    assert "plan" in lines[0] and "simplicio.dev-cli.edit-plan/v1" in lines[0]


# --- prepare --example ----------------------------------------------------------------------------------------------


def test_prepare_example_text_parses_and_validates_with_no_errors():
    text = task_contract.EXAMPLE_TASK
    compiled = task_contract.compile_many(text)
    assert compiled["task_count"] == 1
    verdict = task_contract.validate_contract(compiled["tasks"][0])
    assert verdict["errors"] == []


def test_prepare_example_prints_the_task_file_without_a_task_argument(capsys):
    code = cli_impl.main(["prepare", "--example"])
    out = capsys.readouterr().out
    assert code == 0
    assert out == task_contract.EXAMPLE_TASK
    assert task_contract.validate_contract(task_contract.compile_many(out)["tasks"][0])["errors"] == []


def test_prepare_without_task_or_example_is_a_usage_error(capsys):
    with pytest.raises(SystemExit):
        cli_impl.main(["prepare"])
    assert "--task" in capsys.readouterr().err


def test_prepare_help_explains_the_example_flag_and_the_task_shape(capsys):
    with pytest.raises(SystemExit):
        cli_impl.main(["prepare", "--help"])
    text = capsys.readouterr().out
    assert "--example" in text and "--task" in text
    assert "valid markdown task file" in text
