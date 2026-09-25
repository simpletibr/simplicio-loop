"""CLI wiring for the issue #709 Mode 3 budget guard in ``simplicio edit``.

Verifies that a plan explicitly marked ``effect_mode: "llm"`` is refused
before any file write when it looks like full-file generation, and that the
existing preimage/anchor enforcement in ``execute_plan`` is untouched for
plans that do not carry the marker (the "bypass de write sem preimage
fechado no agent path" acceptance criterion).
"""

from __future__ import annotations

import argparse
import json

import pytest

from simplicio.commands import edit as edit_cmd


def _args(tmp_path, plan_path, *, apply: bool) -> argparse.Namespace:
    return argparse.Namespace(
        root=str(tmp_path),
        plan=str(plan_path),
        apply=apply,
        json=True,
        no_runtime=True,
    )


def test_llm_full_file_plan_is_rejected_before_any_write(tmp_path, capsys) -> None:
    target = tmp_path / "a.py"
    target.write_text("x" * 1000, encoding="utf-8")
    plan = {
        "effect_mode": "llm",
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [
            {
                "op": "replace_range",
                "path": "a.py",
                "start_line": 1,
                "end_line": 1,
                "text": "y" * 960,
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    code = edit_cmd.run_edit(_args(tmp_path, plan_path, apply=True))

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "refused"
    assert payload["applied"] is False
    assert payload["errors"][0]["code"] == "full_file_generation_rejected"
    assert payload["errors"][0]["path"] == "a.py"
    # The rejected plan must never touch the file.
    assert target.read_text(encoding="utf-8") == "x" * 1000


def test_llm_bounded_edit_without_full_file_marker_is_not_rejected_by_budget_guard(tmp_path, capsys) -> None:
    # A multi-line file where the op only touches ONE of many lines is a
    # bounded edit, not full-file generation, even though the replacement
    # text is not tiny relative to that single line.
    original = "\n".join(f"line {i}" for i in range(1, 21)) + "\n"
    target = tmp_path / "a.py"
    target.write_text(original, encoding="utf-8")
    plan = {
        "effect_mode": "llm",
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [
            {
                "op": "replace_range",
                "path": "a.py",
                "start_line": 10,
                "end_line": 10,
                "text": "line ten, rewritten\n",
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    code = edit_cmd.run_edit(_args(tmp_path, plan_path, apply=True))

    payload = json.loads(capsys.readouterr().out)
    # Bounded, single-line edit within a larger file -- not full-file, so
    # the budget guard does not fire.
    assert payload["errors"] == [] or payload["errors"][0]["code"] != "full_file_generation_rejected"
    assert code == 0
    assert "line ten, rewritten" in target.read_text(encoding="utf-8")


def test_plan_without_effect_mode_marker_is_unaffected_by_budget_guard(tmp_path, capsys) -> None:
    """Plans that do not opt into the router (the overwhelming majority
    today) see no behavior change at all -- the guard only inspects plans
    explicitly marked ``effect_mode: "llm"``.
    """
    target = tmp_path / "a.py"
    target.write_text("x" * 1000, encoding="utf-8")
    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [
            {
                "op": "replace_range",
                "path": "a.py",
                "start_line": 1,
                "end_line": 1,
                "text": "y" * 960,
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    code = edit_cmd.run_edit(_args(tmp_path, plan_path, apply=True))

    payload = json.loads(capsys.readouterr().out)
    assert not any(error.get("code") == "full_file_generation_rejected" for error in payload["errors"])
    assert code == 0


def test_llm_plan_still_enforces_preimage_anchor_checks_no_new_bypass(tmp_path, capsys) -> None:
    """Regression for "bypass de write sem preimage fechado no agent path":
    an ``effect_mode: "llm"`` plan that is NOT full-file still goes through
    the same ``execute_plan`` preimage/anchor machinery as any other plan --
    the router adds a guard, it never removes one.
    """
    target = tmp_path / "a.py"
    target.write_text("hello world\n", encoding="utf-8")
    plan = {
        "effect_mode": "llm",
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [
            {
                "op": "replace_anchor",
                "path": "a.py",
                "find": "this text does not exist in the file",
                "replace": "irrelevant",
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    code = edit_cmd.run_edit(_args(tmp_path, plan_path, apply=True))

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "refused"
    assert payload["errors"][0]["code"] == "missing_anchor"
    assert target.read_text(encoding="utf-8") == "hello world\n"


@pytest.mark.parametrize("apply", [False, True])
def test_llm_full_file_rejection_is_stable_dry_run_and_apply(tmp_path, capsys, apply) -> None:
    target = tmp_path / "a.py"
    target.write_text("x" * 500, encoding="utf-8")
    plan = {
        "effect_mode": "llm",
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [
            {
                "op": "replace_range",
                "path": "a.py",
                "start_line": 1,
                "end_line": 1,
                "text": "y" * 480,
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    code = edit_cmd.run_edit(_args(tmp_path, plan_path, apply=apply))

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["errors"][0]["code"] == "full_file_generation_rejected"
    assert payload["applied"] is False
