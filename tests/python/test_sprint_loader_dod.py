import sys

from simplicio.dod import load_sprint_dod, parse_dod, run_dod_gates
from simplicio.sprint_loader import load_sprint


def test_load_sprint_reads_task_goals(tmp_path):
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "SPRINT.md").write_text("# Sprint 01\n", encoding="utf-8")
    (sprint_dir / "01-login.task.md").write_text(
        "# Login\n\n## Goal\nImplement login flow\n\n## Notes\nx",
        encoding="utf-8",
    )

    sprint = load_sprint(tmp_path, "sprint-01")

    assert sprint.title == "Sprint 01"
    assert len(sprint.tasks) == 1
    assert sprint.tasks[0].title == "Login"
    assert sprint.tasks[0].goal == "Implement login flow"


def test_load_sprint_falls_back_to_task_body_when_goal_section_is_absent(tmp_path):
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "01-example.task.md").write_text(
        "# Example\n\n## Contexto\nUse the full spec.\n\n## Acceptance Criteria\n- ok\n",
        encoding="utf-8",
    )

    sprint = load_sprint(tmp_path, "sprint-01")

    assert sprint.tasks[0].title == "Example"
    assert "Use the full spec" in sprint.tasks[0].goal
    assert "Acceptance Criteria" in sprint.tasks[0].goal


def test_parse_and_run_dod_command_gate(tmp_path):
    command = f'"{sys.executable}" -c "raise SystemExit(0)"'
    gates = parse_dod(f"- [ ] Unit tests pass (`{command}`)\n- [ ] Evidence attached\n")

    assert [gate.command for gate in gates] == [command, None]
    results = run_dod_gates(tmp_path, gates)
    assert [row["passed"] for row in results] == [True, False]
    assert results[1]["manual"] is True
    assert "not checked" in results[1]["log"]


def test_checked_manual_dod_item_passes(tmp_path):
    gates = parse_dod("- [x] Evidence attached\n")

    results = run_dod_gates(tmp_path, gates)

    assert results == [
        {
            "label": "Evidence attached",
            "passed": True,
            "command": None,
            "log": "",
            "manual": True,
        }
    ]


def test_load_sprint_dod_reads_sprint_and_task_checklists(tmp_path):
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "SPRINT.md").write_text("- [x] Sprint note\n", encoding="utf-8")
    (sprint_dir / "01-example.task.md").write_text("- [ ] Task note\n", encoding="utf-8")

    gates = load_sprint_dod(sprint_dir)

    assert [gate.label for gate in gates] == ["Sprint note", "Task note"]


def test_run_dod_gates_blocks_shell_metacharacters_by_default(tmp_path):
    gates = parse_dod("- [ ] Shell (`echo ok | cat`)\n")

    results = run_dod_gates(tmp_path, gates)

    assert results[0]["passed"] is False
    assert "SIMPLICIO_DOD_ALLOW_SHELL=1" in results[0]["log"]


def test_run_dod_gates_allows_shell_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DOD_ALLOW_SHELL", "1")
    # `findstr` is Windows-only; use `grep`, the portable Unix equivalent
    # (this suite runs on macOS/Linux), so the piped-shell gate actually
    # exercises the metacharacter opt-in rather than failing on a missing
    # binary.
    gates = parse_dod("- [ ] Shell (`echo ok | grep ok`)\n")

    results = run_dod_gates(tmp_path, gates)

    assert results[0]["passed"] is True


def test_run_dod_gates_timeout_returns_failed_result(tmp_path, monkeypatch):
    def fake_timeout(*args, **kwargs):
        raise __import__("subprocess").TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr("simplicio.dod.subprocess.run", fake_timeout)
    gates = parse_dod(f"- [ ] Slow (`{sys.executable} -c \"print('ok')\"`)\n")

    results = run_dod_gates(tmp_path, gates)

    assert results[0]["passed"] is False
    assert "timed out" in results[0]["log"]
