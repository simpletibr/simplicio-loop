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

def page_tasks(n: int = 10, independent: bool = False) -> list[dict]:
    """``n`` HTML pages, ``p01.html`` .. ``pNN.html``.

    The standard set chains each page to the previous one (``depends_on``),
    so every release is compared on the same serial shape. ``independent``
    drops that chain: the pages touch different files, so the wave can fan
    them out; it is measured under its own results filename.

    Each page is one harness task. ``--stage`` on ``check_page.py`` is the
    page number. Used by the 10-task turbo comparison; the 1/2/4 cadastro
    set is unchanged.
    """
    tasks = []
    for index in range(1, n + 1):
        pid = f"p{index:02d}"
        tasks.append({
            "index": index,
            "kind": "create",
            "depends_on": [index - 1] if index > 1 and not independent else [],
            "target": f"{pid}.html",
            "checker": "check_page.py",
            "text": (
                f"Create {pid}.html: a pure HTML page (no JS framework, no "
                f'external CSS/JS) with a <form id="{pid}"> containing a '
                "labeled input email (type=email, name=email, required) and "
                "a submit button."
            ),
            "verify_stage": index,
        })
    return tasks


TASK_SET_CHOICES = (1, 2, 4, 10)


def task_set(n: int, independent: bool = False) -> list[dict]:
    """The task list for ``--tasks n`` (1, 2, or 4). Returns fresh dict
    references from ``TASKS``/``LOGIN_TASKS`` (a new list each call, though
    the task dicts themselves are shared and never mutated by callers)."""
    if n == 1:
        return TASKS[:1]
    if n == 2:
        return list(TASKS)
    if n == 4:
        return list(TASKS) + list(LOGIN_TASKS)
    if n == 10:
        return page_tasks(10, independent=independent)
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
