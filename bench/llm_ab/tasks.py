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

import os

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


HARD_CHECKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hidden", "check_hard.py")


def hard_task_set() -> list[dict]:
    """Four independent Python tasks on ``fixture_hard/`` (``--tasks 4 --hard``).

    Logic with a rounding trap, a two-bug fix, a two-file refactor and a parser
    with edge cases. Their acceptance tests live in ``hidden/check_hard.py``,
    outside the fixture, so neither arm can read them; the task text states
    every rule the tests check.
    """
    texts = (
        ("pricing.py", None,
         "Create pricing.py with a function order_total(items, coupon=None) that returns the order "
         "total in integer cents. items is a list of dicts with integer keys price_cents and qty. "
         "Rules: qty must be at least 1 and price_cents must be at least 0, otherwise raise ValueError. "
         "subtotal = sum of price_cents * qty. coupon None means no discount. coupon \"PCT10\" takes 10% "
         "off the subtotal, rounded half up to the cent (so 100.5 becomes 101). coupon \"OFF500\" takes "
         "500 cents off, but only when the subtotal is at least 2000; below that it gives no discount. "
         "Any other coupon raises ValueError. Shipping: free when the subtotal before discount is at "
         "least 10000 cents; otherwise add 799 cents after the discount. An empty order pays shipping."),
        ("inventory.py", None,
         "inventory.py has two bugs reported by users: adding stock to a SKU that already exists loses "
         "the previous quantity, and reserving exactly the remaining quantity of a SKU fails. Fix both "
         "without changing the public API (Inventory.add, Inventory.reserve, Inventory.available). "
         "reserve(sku, qty) must still return False and change nothing when there is not enough stock "
         "(including an unknown SKU), and must now raise ValueError when qty is less than 1."),
        ("shop/money.py", ["shop/report.py", "shop/invoice.py"],
         "Refactor: shop/report.py (summary) and shop/invoice.py (invoice_total) duplicate the per-line "
         "total in cents: net = unit_cents * qty, plus tax = net * tax_pct / 100 rounded half up. Create "
         "shop/money.py with line_total(line) -> int holding that logic, and change both functions to "
         "call line_total instead of computing it themselves. Their results must not change."),
        ("duration.py", None,
         "Create duration.py with parse_duration(text) -> int that converts a duration like \"1h30m\", "
         "\"45s\", \"2h\" or \"1h2m3s\" to seconds. Format: one or more components, each a non-negative "
         "integer immediately followed by its unit h, m or s; units appear in that order (h before m "
         "before s) and each at most once; no spaces or other characters. \"0s\" is valid and returns 0. "
         "Anything else (empty string, missing unit, unknown unit, wrong order, repeated unit, sign, "
         "decimal, spaces) raises ValueError."),
    )
    tasks = []
    for index, (target, context, text) in enumerate(texts, start=1):
        task = {
            "index": index,
            "kind": "hard",
            "depends_on": [],
            "target": target,
            "checker": HARD_CHECKER,
            "text": text,
            "verify_stage": index,
        }
        if context:
            task["context"] = list(context)
        tasks.append(task)
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
