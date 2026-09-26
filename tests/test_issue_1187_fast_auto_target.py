import json
from pathlib import Path

from simplicio_loop.fast_integration import (
    FAST_CHANGESET_SCHEMA,
    FAST_PLAN_SCHEMA,
    _validate_plan_policy,
    mapper_selected_targets,
)


TASK = (
    "Fix issue #10: preserve the last valid Bot roster when the active "
    "gateway does not support profiles.list."
)


def _mutation_plan(allowed="plugin.js"):
    return {
        "schema": FAST_PLAN_SCHEMA,
        "nodes": [
            {
                "id": "modify",
                "kind": "structured_patch",
                "inputs": {
                    "format": FAST_CHANGESET_SCHEMA,
                    "allowed_files": [allowed],
                },
            }
        ],
    }


def test_bare_plugin_js_in_task_resolves_when_file_exists(tmp_path: Path):
    (tmp_path / "plugin.js").write_text("export {}\n", encoding="utf-8")
    policy, blockers = _validate_plan_policy(
        tmp_path,
        TASK + " Change plugin.js only.",
        {"context": [{"file": "plugin.js"}], "files": ["plugin.js"]},
        _mutation_plan(),
    )
    assert "plugin.js" in policy["explicit_targets"]
    assert "TARGET_PATH_UNRESOLVED" not in {item["reason"] for item in blockers}


def test_node_js_is_not_treated_as_an_orient_target(tmp_path: Path):
    (tmp_path / "plugin.js").write_text("export {}\n", encoding="utf-8")
    policy, blockers = _validate_plan_policy(
        tmp_path,
        TASK + " Requires Node.js. Change plugin.js.",
        {"context": [{"file": "plugin.js"}], "files": ["plugin.js"]},
        _mutation_plan(),
    )
    assert "Node.js" not in policy["explicit_targets"]
    assert "plugin.js" in policy["explicit_targets"]
    assert "TARGET_PATH_UNRESOLVED" not in {item["reason"] for item in blockers}


def test_mapper_handoff_supplies_selected_target_when_task_has_no_path(tmp_path: Path):
    (tmp_path / "plugin.js").write_text("export {}\n", encoding="utf-8")
    pack_dir = tmp_path / ".simplicio-loop" / "handoff-objects"
    pack_dir.mkdir(parents=True)
    (pack_dir / "context_pack-ready.json").write_text(
        json.dumps({
            "explicit_target_added": "plugin.js",
            "files": [
                {"path": "plugin.js", "selection_reason": "explicit_task_target", "tests": []},
            ],
        }),
        encoding="utf-8",
    )
    assert mapper_selected_targets(tmp_path) == ["plugin.js"]
    policy, blockers = _validate_plan_policy(
        tmp_path,
        TASK,
        {"context": [{"file": "plugin.js"}], "files": ["plugin.js"]},
        _mutation_plan(),
    )
    assert policy["explicit_targets"] == ["plugin.js"]
    assert "TARGET_PATH_UNRESOLVED" not in {item["reason"] for item in blockers}


def test_unresolved_target_emits_concrete_next_command(tmp_path: Path):
    (tmp_path / "plugin.js").write_text("export {}\n", encoding="utf-8")
    pack_dir = tmp_path / ".simplicio-loop" / "handoff-objects"
    pack_dir.mkdir(parents=True)
    (pack_dir / "context_pack-ready.json").write_text(
        json.dumps({"explicit_target_added": "plugin.js", "files": [{"path": "plugin.js"}]}),
        encoding="utf-8",
    )
    policy, blockers = _validate_plan_policy(
        tmp_path,
        "update missing/path.py",
        {"context": [{"file": "plugin.js"}], "files": ["plugin.js"]},
        _mutation_plan("missing/path.py"),
    )
    reasons = {item["reason"] for item in blockers}
    assert "TARGET_PATH_UNRESOLVED" in reasons
    unresolved = next(item for item in blockers if item["reason"] == "TARGET_PATH_UNRESOLVED")
    assert "--target plugin.js" in unresolved["next_command"]
    assert unresolved["accepted_target_form"].startswith("repo-relative")
    assert "plugin.js" in unresolved["message"]


def test_cli_target_flag_is_accepted_by_plan_policy(tmp_path: Path):
    (tmp_path / "plugin.js").write_text("export {}\n", encoding="utf-8")
    policy, blockers = _validate_plan_policy(
        tmp_path,
        TASK,
        {"context": [{"file": "plugin.js"}], "files": ["plugin.js"]},
        _mutation_plan(),
        extra_targets=["plugin.js"],
    )
    assert policy["explicit_targets"] == ["plugin.js"]
    assert "TARGET_PATH_UNRESOLVED" not in {item["reason"] for item in blockers}
