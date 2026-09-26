"""Task table for the LLM A/B benchmark: exactly 2 dependent HTML tasks.

Task 2 depends on task 1 and runs on the tree task 1 left (same
``cadastro.html``, same simplicio-loop run in the simplicio arms). The
acceptance check is harness-owned (``fixture/tests/check_cadastro.py``) --
the benchmarked model is never asked to write tests.
"""
from __future__ import annotations

TASKS = [
    {
        "index": 1,
        "kind": "create",
        "depends_on": [],
        "target": "cadastro.html",
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
        "text": (
            "Edit cadastro.html: add a labeled phone field (input name=phone, "
            "type=tel) and a confirm-password field (name=password_confirm, "
            "type=password, required, minlength=8) to the same form, keeping "
            "the existing fields."
        ),
        "verify_stage": 2,
    },
]


def tasks_by_kind() -> dict[str, list[dict]]:
    """Group ``TASKS`` by their ``kind`` (create/edit), preserving order."""
    grouped: dict[str, list[dict]] = {}
    for task in TASKS:
        grouped.setdefault(task["kind"], []).append(task)
    return grouped


def verifier_command(stage: int) -> str:
    """The single harness-owned verifier command for a given task stage.

    Used identically as the Independent verifier and as every declared
    quality-lane command (Unit/Integration/System/Regression/Benchmark) for
    that task -- there is no separate test suite for the model to satisfy.
    """
    return f"python3 tests/check_cadastro.py --stage {stage}"
