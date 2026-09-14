from pathlib import Path

from simplicio_loop.fast_integration import (
    FAST_CHANGESET_SCHEMA,
    FAST_PLAN_SCHEMA,
    _validate_plan_policy,
)


def _mutation_plan(target: str) -> dict:
    return {
        "schema": FAST_PLAN_SCHEMA,
        "nodes": [
            {
                "id": "modify",
                "kind": "structured_patch",
                "inputs": {
                    "format": FAST_CHANGESET_SCHEMA,
                    "allowed_files": [target],
                },
            }
        ],
    }


def _creation_task(target: str) -> str:
    return f"Type: creation\nTarget: {target}\nCreate the target."


def _edit_task(target: str) -> str:
    return f"Type: edit\nTarget: {target}\nEdit the target."


def test_absent_creation_target_is_a_valid_fast_mutation_corridor(tmp_path: Path):
    target = "site/checkers.html"
    policy, blockers = _validate_plan_policy(
        tmp_path,
        _creation_task(target),
        {"context": [{"file": target}], "files": [target]},
        _mutation_plan(target),
    )

    assert policy["validated"] is True
    assert "TARGET_PATH_UNRESOLVED" not in {item["reason"] for item in blockers}


def test_absent_edit_target_remains_unresolved(tmp_path: Path):
    target = "site/checkers.html"
    policy, blockers = _validate_plan_policy(
        tmp_path,
        _edit_task(target),
        {"context": [{"file": target}], "files": [target]},
        _mutation_plan(target),
    )

    assert policy["validated"] is False
    assert "TARGET_PATH_UNRESOLVED" in {item["reason"] for item in blockers}


def test_creation_target_escaping_root_remains_invalid(tmp_path: Path):
    target = "../outside.html"
    policy, blockers = _validate_plan_policy(
        tmp_path,
        _creation_task(target),
        {"context": [], "files": []},
        _mutation_plan(target),
    )

    reasons = {item["reason"] for item in blockers}
    assert policy["validated"] is False
    assert "TARGET_PATH_INVALID" in reasons
    assert "MUTATION_TARGET_INVALID" in reasons
