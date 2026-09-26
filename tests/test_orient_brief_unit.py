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
import subprocess

from simplicio_loop.cli_impl import ORIENT_BRIEF_SCHEMA, orient_brief


def _repo(tmp_path, files):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def test_brief_route_is_first_key(tmp_path):
    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html: add a title"])
    assert next(iter(payload)) == "route"


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


def test_brief_carries_per_phase_effort_hint(tmp_path):
    """Per-phase reasoning-effort hints (plan high / execute low / review
    medium) so the host that calls the LLM knows what the NEXT turn --
    writing ops.json, i.e. the plan phase -- should run at."""
    from simplicio_loop.effort import PHASE_EFFORT

    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html"])
    assert payload["effort"] == PHASE_EFFORT
    assert payload["route"]["next"]
    assert payload["route"]["next"][0]["phase"] == "plan"
    assert payload["route"]["next"][0]["effort"] == PHASE_EFFORT["plan"]


def test_brief_route_next_is_apply_hot_path_for_one_task(tmp_path):
    """Issue #1315: the brief must steer the host to ``simplicio-loop apply``
    (plan high -> execute low), never to the legacy dev-cli compile/apply
    pair, even for a one-task fast-path route."""
    from simplicio_loop.effort import PHASE_EFFORT

    _repo(tmp_path, {"a.html": "<html></html>"})
    steps = orient_brief(tmp_path, ["Edit a.html"])["route"]["next"]
    text = " ".join(s["step"] for s in steps)
    assert "simplicio-loop apply .simplicio-loop/ops.json" in text
    assert "simplicio-dev-cli" not in text
    assert steps[0]["phase"] == "plan"
    assert steps[0]["effort"] == PHASE_EFFORT["plan"]
    assert steps[1]["phase"] == "execute"
    assert steps[1]["effort"] == PHASE_EFFORT["execute"]


def test_brief_route_next_is_apply_hot_path_for_many_tasks(tmp_path):
    _repo(tmp_path, {"a.html": "<html></html>", "b.html": "<html></html>"})
    steps = orient_brief(tmp_path, ["Edit a.html", "Edit b.html"])["route"]["next"]
    assert any("simplicio-loop apply .simplicio-loop/ops.json" in s["step"] for s in steps)
    assert not any("prepare" in s["step"] or "wave" in s["step"] for s in steps)


def test_brief_targets_named_file_comes_first(tmp_path):
    """issue #1318: the file a task names first must sort first in
    ``targets``, ahead of any other candidate the same task's ranking
    surfaced (a tiny repo returns every file as a candidate for every
    task)."""
    _repo(tmp_path, {"cadastro.html": "<html>cadastro</html>", "login.html": "<html>login</html>"})
    payload = orient_brief(tmp_path, ["Replace login.html placeholder with a real login form"])
    paths = [t["path"] for t in payload["targets"]]
    assert paths[0] == "login.html"


def test_brief_verifier_file_included_by_path_with_head_only(tmp_path):
    """A verifier/test/check file (path under tests/, or a name starting
    with test_/check_) is worth pointing at, but its full body is not --
    only the path plus a short head."""
    lines = [f"line {i}\n" for i in range(1, 61)]
    _repo(tmp_path, {
        "a.html": "<html></html>",
        "tests/test_a.py": "".join(lines),
    })
    payload = orient_brief(tmp_path, ["Edit a.html, verified by tests/test_a.py"])
    entry = next(t for t in payload["targets"] if t["path"] == "tests/test_a.py")
    assert entry["truncated"] is True
    kept_lines = entry["content"].splitlines()
    assert len(kept_lines) <= 20
    assert kept_lines[0] == "line 1"
    assert "line 60" not in entry["content"]


def test_brief_total_content_budget_is_enforced(tmp_path):
    """issue #1318: the brief stays under a total target-content budget (24KB)
    even across many tasks/files, with truncation markers where it clips."""
    files = {f"f{i}.py": ("X" * 6000) for i in range(6)}
    _repo(tmp_path, files)
    tasks = [f"Edit f{i}.py: change something" for i in range(6)]
    payload = orient_brief(tmp_path, tasks)
    total = sum(len(t["content"].encode("utf-8")) for t in payload["targets"])
    assert total <= 24 * 1024
    assert any(t["truncated"] for t in payload["targets"])


def test_brief_writes_itself_to_state_dir_with_generations(tmp_path):
    """Issue #1318: the brief persists `.simplicio-loop/brief.json` (the
    Mapper + Fast provenance `apply` requires) and its ops format asks for
    `brief_generations`."""
    import json as _json

    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html"])
    saved = _json.loads((tmp_path / ".simplicio-loop" / "brief.json").read_text())
    assert saved["generations"] == payload["generations"]
    assert "brief_generations" in payload["apply"]["ops_format"]
