"""Task table for the LLM A/B benchmark.

The base set is 2 dependent HTML tasks on ``cadastro.html`` (create, then
edit). ``--tasks 4`` (``task_set(4)``) extends it with 2 more dependent
tasks on a second page, ``login.html`` -- create, then edit -- run.py picks
the set via ``task_set(n)``. Task 2 depends on task 1 (and, in the 4-task
set, task 3 depends on task 2, task 4 on task 3) so every arm runs on the
tree the previous task actually left, same simplicio-loop run in the
simplicio arms). Each task declares its own ``checker`` filename (shipped in
``fixture/tests/``) -- the acceptance check is always harness-owned, never
asked of the benchmarked model.
"""
from __future__ import annotations

TASKS = [
    {
        "index": 1,
        "kind": "create",
        "depends_on": [],
        "target": "cadastro.html",
        "checker": "check_cadastro.py",
        "text": (
            'Create cadastro.html: a pure HTML (no JS framework, no external '
            'CSS/JS) user registration page with a <form id="cadastro"> '
            "containing labeled inputs name (text, required), email "
            "(type=email, required), password (type=password, required, "
            "minlength=8) and a submit button."
        ),
        "verify_stage": 1,
    },
    {
        "index": 2,
        "kind": "edit",
        "depends_on": [1],
        "target": "cadastro.html",
        "checker": "check_cadastro.py",
        "text": (
            "Edit cadastro.html: add a labeled phone field (input name=phone, "
            "type=tel) and a confirm-password field (name=password_confirm, "
            "type=password, required, minlength=8) to the same form, keeping "
            "the existing fields."
        ),
        "verify_stage": 2,
    },
]

LOGIN_TASKS = [
    {
        "index": 3,
        "kind": "create",
        "depends_on": [2],
        "target": "login.html",
        "checker": "check_login.py",
        "text": (
            'Create login.html: a pure HTML (no JS framework, no external '
            'CSS/JS) login page with a <form id="login"> containing labeled '
            "inputs email (type=email, required) and password "
            "(type=password, required) and a submit button."
        ),
        "verify_stage": 1,
    },
    {
        "index": 4,
        "kind": "edit",
        "depends_on": [3],
        "target": "login.html",
        "checker": "check_login.py",
        "text": (
            "Edit login.html: add a checkbox input (name=remember) to the "
            'same form, and add a link <a href="cadastro.html"> to the '
            "signup page somewhere on the page."
        ),
        "verify_stage": 2,
    },
]

TASK_SET_CHOICES = (1, 2, 4)


def task_set(n: int) -> list[dict]:
    """The task list for ``--tasks n`` (1, 2, or 4). Returns fresh dict
    references from ``TASKS``/``LOGIN_TASKS`` (a new list each call, though
    the task dicts themselves are shared and never mutated by callers)."""
    if n == 1:
        return TASKS[:1]
    if n == 2:
        return list(TASKS)
    if n == 4:
        return list(TASKS) + list(LOGIN_TASKS)
    raise ValueError(f"unsupported task count {n!r}; choose from {TASK_SET_CHOICES}")


def tasks_by_kind() -> dict[str, list[dict]]:
    """Group ``TASKS`` by their ``kind`` (create/edit), preserving order."""
    grouped: dict[str, list[dict]] = {}
    for task in TASKS:
        grouped.setdefault(task["kind"], []).append(task)
    return grouped


def verifier_command(stage: int, checker: str = "check_cadastro.py") -> str:
    """The single harness-owned verifier command for a given task stage.

    Used identically as the Independent verifier and as every declared
    quality-lane command (Unit/Integration/System/Regression/Benchmark) for
    that task -- there is no separate test suite for the model to satisfy.
    """
    return f"python3 tests/{checker} --stage {stage}"
