from pathlib import Path

from simplicio_loop.fast_integration import (
    FAST_CHANGESET_SCHEMA,
    FAST_PLAN_SCHEMA,
    _validate_plan_policy,
)


def _mutation_plan(*targets: str) -> dict:
    return {
        "schema": FAST_PLAN_SCHEMA,
        "nodes": [
            {
                "id": "modify",
                "kind": "structured_patch",
                "inputs": {
                    "format": FAST_CHANGESET_SCHEMA,
                    "allowed_files": list(targets),
                },
            }
        ],
    }


def _creation_task(target: str = "site/checkers.html", verifier: str = "") -> str:
    return (
        "System: Simplicio\n"
        "Type: criação\n"
        f"Target: {target}\n"
        "Create the target.\n"
        f"Additional Information: {verifier}"
    )


def _reasons(blockers: list[dict]) -> set[str]:
    return {item["reason"] for item in blockers}


def test_creation_ignores_absolute_path_inside_documented_verifier_command(tmp_path: Path):
    target = "site/checkers.html"
    verifier = (
        "`node /projetos/ai/benchmark-checkers-v2-support/browser/validate_checkers.mjs "
        "--site site/checkers.html --task TASK-CHECKERS-001 --json`"
    )

    policy, blockers = _validate_plan_policy(
        tmp_path,
        _creation_task(target, verifier),
        {"context": [{"file": target}], "files": [target]},
        _mutation_plan(target),
    )

    assert policy["validated"] is True
    assert "/projetos/ai/benchmark-checkers-v2-support/browser/validate_checkers.mjs" not in policy["explicit_targets"]
    assert "TARGET_PATH_INVALID" not in _reasons(blockers)


def test_creation_allows_preexisting_support_file_outside_target_corridor(tmp_path: Path):
    target = "site/checkers.html"
    support = "scripts/watcher_verify.py"
    support_path = tmp_path / support
    support_path.parent.mkdir(parents=True)
    support_path.write_text("pass\n", encoding="utf-8")

    policy, blockers = _validate_plan_policy(
        tmp_path,
        _creation_task(target),
        {"context": [{"file": target}], "files": [target]},
        _mutation_plan(target, support),
    )

    assert policy["validated"] is True
    assert "TARGET_CORRIDOR_MISMATCH" not in _reasons(blockers)


def test_creation_target_is_relevant_before_the_file_exists(tmp_path: Path):
    target = "site/checkers.html"

    policy, blockers = _validate_plan_policy(
        tmp_path,
        _creation_task(target),
        {"context": [{"file": "README.md"}], "files": ["README.md"]},
        _mutation_plan(target),
    )

    assert policy["validated"] is True
    assert "TARGET_RELEVANCE_INSUFFICIENT" not in _reasons(blockers)


def test_absolute_path_in_declared_creation_target_remains_invalid(tmp_path: Path):
    target = "/outside/site/checkers.html"

    policy, blockers = _validate_plan_policy(
        tmp_path,
        _creation_task(target),
        {"context": [], "files": []},
        _mutation_plan(target),
    )

    assert policy["validated"] is False
    assert {"TARGET_PATH_INVALID", "MUTATION_TARGET_INVALID"} <= _reasons(blockers)


def test_missing_support_file_outside_creation_corridor_remains_blocked(tmp_path: Path):
    target = "site/checkers.html"
    support = "scripts/missing_watcher_verify.py"

    policy, blockers = _validate_plan_policy(
        tmp_path,
        _creation_task(target),
        {"context": [{"file": target}], "files": [target]},
        _mutation_plan(target, support),
    )

    assert policy["validated"] is False
    assert "TARGET_CORRIDOR_MISMATCH" in _reasons(blockers)


def test_dependent_edit_can_prepare_a_target_pending_its_creation(tmp_path: Path):
    target = "site/checkers.html"

    policy, blockers = _validate_plan_policy(
        tmp_path,
        "Type: edição\nTarget: site/checkers.html\nEdit the created target.",
        {"context": [{"file": "README.md"}], "files": ["README.md"]},
        _mutation_plan(target),
        pending_creation_targets=[target],
    )

    assert policy["validated"] is True
    assert not blockers


def test_pending_edit_ignores_preexisting_fast_support_selection(tmp_path: Path):
    target = "site/checkers.html"
    support = "scripts/watcher_verify.py"
    support_path = tmp_path / support
    support_path.parent.mkdir(parents=True)
    support_path.write_text("pass\n", encoding="utf-8")

    policy, blockers = _validate_plan_policy(
        tmp_path,
        "Type: edição\nTarget: site/checkers.html\nEdit the created target.",
        {"context": [{"file": "README.md"}], "files": ["README.md"]},
        _mutation_plan(target, support),
        pending_creation_targets=[target],
    )

    assert policy["validated"] is True
    assert not blockers


def test_edit_with_existing_target_keeps_real_corridor_violations_blocked(tmp_path: Path):
    target = "site/checkers.html"
    support = "scripts/watcher_verify.py"
    target_path = tmp_path / target
    support_path = tmp_path / support
    target_path.parent.mkdir(parents=True)
    support_path.parent.mkdir(parents=True)
    target_path.write_text("<html></html>\n", encoding="utf-8")
    support_path.write_text("pass\n", encoding="utf-8")

    policy, blockers = _validate_plan_policy(
        tmp_path,
        "Type: edição\nTarget: site/checkers.html\nEdit the existing target.",
        {"context": [{"file": target}], "files": [target]},
        _mutation_plan(target, support),
    )

    assert policy["validated"] is False
    assert "TARGET_CORRIDOR_MISMATCH" in _reasons(blockers)
