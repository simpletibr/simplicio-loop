"""Unit tests for `simplicio-loop orient --brief` (issue #1310, Turn 1 of
the plan-once/apply-once hot path).

`--brief` renders a compact multi-task payload from the SAME Mapper survey
+ Fast context orient always used -- route first, target file content
(deduped, capped), plan groups, suggested checks, mapper/fast generation +
context hash, and the exact `apply` command/ops format. Non-brief output
must stay byte-identical to before (covered by test_cli_fast_orient.py /
test_orient_route_unit.py, unchanged here).
"""
from __future__ import annotations

import json

from simplicio_loop.cli_impl import orient_brief, ORIENT_BRIEF_SCHEMA


def _repo(tmp_path, files):
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def test_brief_route_is_first_key(tmp_path):
    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html: add a title"])
    assert list(payload)[0] == "route"


def test_brief_schema_and_status(tmp_path):
    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html"])
    assert payload["schema"] == ORIENT_BRIEF_SCHEMA
    assert payload["status"] in {"READY", "FALLBACK", "BLOCKED"}


def test_brief_carries_target_content_no_separate_cat_needed(tmp_path):
    _repo(tmp_path, {"a.html": "<html><body>hi</body></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html: change body text"])
    targets = payload["targets"]
    assert any(t["path"] == "a.html" and "hi" in t["content"] for t in targets)


def test_brief_targets_are_deduped_across_tasks(tmp_path):
    _repo(tmp_path, {"a.html": "<html></html>", "b.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html", "Edit a.html again"])
    paths = [t["path"] for t in payload["targets"]]
    assert paths.count("a.html") == 1


def test_brief_target_content_capped_at_16kb_head_tail(tmp_path):
    big = "X" * 40_000
    _repo(tmp_path, {"big.py": big})
    payload = orient_brief(tmp_path, ["Edit big.py: change something"])
    entry = next(t for t in payload["targets"] if t["path"] == "big.py")
    assert len(entry["content"].encode("utf-8")) <= 16 * 1024 + 64
    assert entry["truncated"] is True


def test_brief_plan_groups_disjoint_tasks_are_parallel(tmp_path):
    _repo(tmp_path, {"a.html": "<html></html>", "b.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html", "Edit b.html"])
    groups = payload["plan"]
    assert set(groups["parallel"]) == {"Edit a.html", "Edit b.html"}
    assert groups["ordered"] == []


def test_brief_plan_groups_shared_file_is_ordered(tmp_path):
    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html: step 1", "Edit a.html: step 2"])
    groups = payload["plan"]
    assert groups["parallel"] == []
    assert len(groups["ordered"]) == 1
    assert set(groups["ordered"][0]) == {"Edit a.html: step 1", "Edit a.html: step 2"}


def test_brief_suggested_checks_present(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    _repo(tmp_path, {"a.py": "x = 1\n"})
    payload = orient_brief(tmp_path, ["Edit a.py"])
    assert payload["checks"]
    assert any("pytest" in c for c in payload["checks"])


def test_brief_has_generation_and_context_hash(tmp_path):
    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html"])
    assert "repo_state_chain" in payload
    assert "tree_hash" in payload["repo_state_chain"]
    assert "generations" in payload


def test_brief_apply_command_and_ops_format(tmp_path):
    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html"])
    apply_block = payload["apply"]
    assert "simplicio-loop apply" in apply_block["command"]
    assert "operations" in apply_block["ops_format"]["tasks"][0]
    assert "repo_state_chain" in apply_block["ops_format"]


def test_brief_size_is_compact(tmp_path):
    """The brief (excluding target content bulk) stays small -- this is the
    whole point of the hot path vs. the ~9.5KB verbose non-brief payload."""
    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html"])
    slim = dict(payload)
    slim.pop("targets", None)
    size = len(json.dumps(slim, ensure_ascii=False).encode("utf-8"))
    assert size < 4096


def test_brief_single_task_shorthand_matches_list_form(tmp_path):
    _repo(tmp_path, {"a.html": "<html></html>"})
    from_list = orient_brief(tmp_path, ["Edit a.html"])
    assert from_list["route"]["mode"] in {"fast-path", "converge"}
    assert len(from_list["targets"]) >= 1


def test_brief_no_tasks_is_blocked(tmp_path):
    payload = orient_brief(tmp_path, [])
    assert payload["status"] == "BLOCKED"
