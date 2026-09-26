"""A tasks.md dependency written the way an LLM naturally writes it must
resolve to the same task alias the runner uses (`task-N`)."""

from simplicio_loop.runner import _dependency_references


def test_dependencies_section_line_keeps_only_the_reference():
    raw = {"state": "declared", "items": ["Depends on: task 1 (cadastro.html)"]}
    assert _dependency_references(raw) == ["task-1"]


def test_natural_task_number_forms_map_to_task_alias():
    assert _dependency_references(["task 2", "Task #3", "#4", "tarefa 5"]) == [
        "task-2", "task-3", "task-4", "task-5",
    ]


def test_ids_and_titles_pass_through_without_parenthetical_note():
    assert _dependency_references("SIMP-12 (login), cadastro-html-task-1") == [
        "SIMP-12", "cadastro-html-task-1",
    ]
