"""Unit tests for `simplicio-loop orient --brief` (issue #1310).

`--brief` renders a compact multi-task payload from the SAME Mapper survey
+ Fast context orient always used -- route first (its one next step is the
`simplicio-loop turbo` command for these tasks), target file content
(deduped, capped), plan groups, suggested checks, mapper/fast generation +
context hash, and the ops format of `simplicio-loop apply`. The non-brief route is
covered by test_orient_route_unit.py.
"""
from __future__ import annotations

import json
import shlex
import subprocess

from simplicio_loop.cli_impl import ORIENT_BRIEF_SCHEMA, TURBO_EXECUTE_RULE, orient_brief, turbo_command

# Commands of the host-writes-the-plan flow. The brief's `route["next"]` must not carry any of them.
OLD_FLOW = ("simplicio-loop prepare", "simplicio-loop tick", "simplicio-loop wave", "edit-plan",
            "simplicio-dev-cli edit", "tasks.md")


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


def test_brief_apply_command_is_the_turbo_command_and_keeps_the_ops_format(tmp_path):
    """`apply.command` is the same turbo command as `route.next`. The ops format below it documents
    the input of the still-public `simplicio-loop apply`; it does not depend on the route."""
    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html"])
    apply_block = payload["apply"]
    assert apply_block["command"] == payload["route"]["next"][0]["step"]
    assert apply_block["command"].startswith("simplicio-loop turbo --repo ")
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
    assert from_list["route"]["mode"] == "deliver"
    assert from_list["route"]["execute"] == "turbo"
    assert len(from_list["targets"]) >= 1


def test_brief_no_tasks_is_blocked(tmp_path):
    payload = orient_brief(tmp_path, [])
    assert payload["status"] == "BLOCKED"


def test_brief_carries_per_phase_effort_hint(tmp_path):
    """Per-phase reasoning-effort hints stay in the brief. The one next step is the
    execute phase: turbo asks the model for the plan, the host only runs the command."""
    from simplicio_loop.effort import PHASE_EFFORT

    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html"])
    assert payload["effort"] == PHASE_EFFORT
    assert payload["route"]["next"]
    assert payload["route"]["next"][0]["phase"] == "execute"
    assert payload["route"]["next"][0]["effort"] == PHASE_EFFORT["execute"]


def test_brief_route_next_is_one_turbo_step_for_one_task(tmp_path):
    """One task: the single next step is the turbo command, in the execute phase."""
    from simplicio_loop.effort import PHASE_EFFORT

    _repo(tmp_path, {"a.html": "<html></html>"})
    route = orient_brief(tmp_path, ["Edit a.html"])["route"]
    assert route["execute"] == "turbo"
    assert route["execute_rule"] == TURBO_EXECUTE_RULE
    assert route["next"] == [{"step": turbo_command(tmp_path, ["Edit a.html"]), "phase": "execute",
                              "effort": PHASE_EFFORT["execute"]}]
    text = " ".join(step["step"] for step in route["next"])
    assert not [needle for needle in OLD_FLOW if needle in text]


def test_brief_route_next_carries_every_task_and_verify_in_one_turbo_step(tmp_path):
    """Many tasks: still ONE step. The command carries one `--task` per task, in order, and `--verify`."""
    _repo(tmp_path, {"a.html": "<html></html>", "b.html": "<html></html>"})
    tasks = ["Edit a.html", "Edit b.html"]
    route = orient_brief(tmp_path, tasks)["route"]
    assert route["execute"] == "turbo"
    assert len(route["next"]) == 1 and route["next"][0]["phase"] == "execute"
    argv = shlex.split(route["next"][0]["step"])
    assert argv[:2] == ["simplicio-loop", "turbo"]
    assert argv[argv.index("--repo") + 1] == str(tmp_path)
    assert [argv[i + 1] for i, part in enumerate(argv) if part == "--task"] == tasks
    assert "--verify" in argv
    assert not [needle for needle in OLD_FLOW if needle in route["next"][0]["step"]]


def test_brief_targets_named_file_comes_first(tmp_path):
    """issue #1318: the file a task names first must sort first in
    ``targets``, ahead of any other candidate the same task's ranking
    surfaced (a tiny repo returns every file as a candidate for every
    task)."""
    _repo(tmp_path, {"cadastro.html": "<html>cadastro</html>", "login.html": "<html>login</html>"})
    payload = orient_brief(tmp_path, ["Replace login.html placeholder with a real login form"])
    paths = [t["path"] for t in payload["targets"]]
    assert paths[0] == "login.html"


def test_brief_verifier_file_included_in_full_within_budget(tmp_path):
    """issue #1323: a verifier/test/check file (path under tests/, or a name
    starting with test_/check_) IS the acceptance spec -- when it fits the
    existing 24 KB total budget it comes back in full, not head-only, so the
    host never re-`cat`s it to see its real assertions."""
    lines = [f"line {i}\n" for i in range(1, 61)]
    _repo(tmp_path, {
        "a.html": "<html></html>",
        "tests/test_a.py": "".join(lines),
    })
    payload = orient_brief(tmp_path, ["Edit a.html, verified by tests/test_a.py"])
    entry = next(t for t in payload["targets"] if t["path"] == "tests/test_a.py")
    assert entry["truncated"] is False
    kept_lines = entry["content"].splitlines()
    assert len(kept_lines) == 60
    assert kept_lines[0] == "line 1"
    assert "line 60" in entry["content"]


def test_brief_verifier_file_over_budget_still_truncates(tmp_path):
    """A verifier file bigger than the per-file 16 KB cap is still head+tail
    truncated like any other target -- the fix removes the head-only special
    case, not the size ceiling itself."""
    big = "".join(f"line {i}\n" for i in range(1, 4000))
    _repo(tmp_path, {
        "a.html": "<html></html>",
        "tests/test_big.py": big,
    })
    payload = orient_brief(tmp_path, ["Edit a.html, verified by tests/test_big.py"])
    entry = next(t for t in payload["targets"] if t["path"] == "tests/test_big.py")
    assert entry["truncated"] is True
    assert "...<truncated>..." in entry["content"]


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


def test_brief_apply_example_is_a_valid_concrete_ops_json(tmp_path):
    """issue #1323: `apply.example` is a real, runnable ops.json -- not a
    placeholder template -- covering a create (`find: ""`), a dependent edit
    (`depends_on`), a `check`, and `repo_state_chain`/`brief_generations`
    copied verbatim from this same brief, so the host never has to open
    `simplicio_loop/apply.py` to learn the shape."""
    from simplicio_loop.apply import _normalize_tasks

    _repo(tmp_path, {"a.html": "<html></html>"})
    payload = orient_brief(tmp_path, ["Edit a.html"])
    example = payload["apply"]["example"]

    assert example["repo_state_chain"] == payload["repo_state_chain"]
    assert example["brief_generations"] == payload["generations"]

    tasks = _normalize_tasks(example)
    assert len(tasks) >= 2
    creates = [t for t in tasks if any(op["find"] == "" for op in t["operations"])]
    assert creates, "example must include a create operation (find: \"\")"
    dependents = [t for t in tasks if t["depends_on"]]
    assert dependents, "example must include a dependent edit (depends_on)"
    checked = [t for t in tasks if t["check"]]
    assert checked, "example must include a task with a check command"


# --- issue #1336: compact, deterministic `orient --brief` CLI stdout -------


def _git_repo_with_file(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.html").write_text("<html></html>", encoding="utf-8")
    return tmp_path


def test_brief_cli_stdout_is_a_single_line_no_indentation(tmp_path, capsys):
    """Compact JSON (no ``indent=2``) by default: this text is fed back to
    the model as OpenCode tool output and becomes part of the next prompt,
    so its size directly affects the prompt-cache-relevant prefix."""
    from simplicio_loop import cli

    repo = _git_repo_with_file(tmp_path)
    assert cli.orient(str(repo), "Edit a.html", brief=True, tasks=["Edit a.html"]) in (0, 2)
    out = capsys.readouterr().out
    assert out.rstrip("\n").count("\n") == 0


def test_brief_cli_stdout_is_deterministic_across_two_runs_on_same_tree(tmp_path, capsys):
    from simplicio_loop import cli

    repo = _git_repo_with_file(tmp_path)
    cli.orient(str(repo), "Edit a.html", brief=True, tasks=["Edit a.html"])
    first = capsys.readouterr().out
    cli.orient(str(repo), "Edit a.html", brief=True, tasks=["Edit a.html"])
    second = capsys.readouterr().out
    assert first == second


def test_brief_cli_stdout_compact_is_smaller_than_pretty(tmp_path, capsys):
    from simplicio_loop import cli

    repo = _git_repo_with_file(tmp_path)
    cli.orient(str(repo), "Edit a.html", brief=True, tasks=["Edit a.html"])
    compact = capsys.readouterr().out
    cli.orient(str(repo), "Edit a.html", brief=True, tasks=["Edit a.html"], pretty=True)
    pretty = capsys.readouterr().out
    assert json.loads(compact) == json.loads(pretty)
    assert len(compact.encode("utf-8")) < len(pretty.encode("utf-8"))
    assert pretty.rstrip("\n").count("\n") > 0


def test_brief_cli_pretty_flag_keeps_route_as_first_key(tmp_path, capsys):
    """``--pretty`` only changes formatting, never key order/content."""
    from simplicio_loop import cli

    repo = _git_repo_with_file(tmp_path)
    cli.orient(str(repo), "Edit a.html", brief=True, tasks=["Edit a.html"], pretty=True)
    out = capsys.readouterr().out
    assert next(iter(json.loads(out))) == "route"
