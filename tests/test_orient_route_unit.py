"""orient answers with the turbo command for every task count."""
import json
import shlex

from simplicio_loop.cli_impl import (
    COMMAND_CARD_MAX_BYTES, COMMAND_CARD_SCHEMA, TURBO_EXECUTE_RULE, _orient_command_card, _orient_route,
    turbo_command,
)

# Commands of the host-writes-the-plan flow. `next` must not carry any of them.
OLD_FLOW = ("simplicio-loop prepare", "simplicio-loop tick", "simplicio-loop wave", "edit-plan",
            "simplicio-dev-cli edit", "tasks.md")


def _survey(root, files, edges=()):
    out = root / ".simplicio-loop"
    out.mkdir()
    (out / "project-map.json").write_text(json.dumps({"files": [{"path": f} for f in files]}))
    (out / "symbol-index.json").write_text(json.dumps({"symbols": []}))
    (out / "call-graph.json").write_text(json.dumps({"edges": list(edges)}))


def test_every_task_routes_through_the_turbo_command(tmp_path):
    _survey(tmp_path, ["cadastro.html", "README.md"])
    goal = "Edit cadastro.html: add a phone field"
    route = _orient_route(tmp_path, goal)
    assert route["mode"] == "deliver"
    assert route["next"] == [turbo_command(tmp_path, [goal])]
    argv = shlex.split(route["next"][0])
    assert argv[:2] == ["simplicio-loop", "turbo"]
    assert argv[argv.index("--repo") + 1] == str(tmp_path)
    assert argv[argv.index("--task") + 1] == goal
    assert "--verify" in argv


def test_route_next_carries_no_host_plan_guidance(tmp_path):
    _survey(tmp_path, ["cadastro.html"])
    joined = " ".join(_orient_route(tmp_path, "Edit cadastro.html: add a phone field")["next"])
    assert not [needle for needle in OLD_FLOW if needle in joined]


def test_multi_file_task_uses_the_same_turbo_command(tmp_path):
    _survey(tmp_path, ["a.html", "b.html"])
    route = _orient_route(tmp_path, "Edit a.html and b.html")
    assert route["mode"] == "deliver"
    assert route["execute_rule"] == TURBO_EXECUTE_RULE
    assert route["next"] == [turbo_command(tmp_path, ["Edit a.html and b.html"])]


def test_missing_survey_still_routes_to_turbo(tmp_path):
    route = _orient_route(tmp_path, "Edit cadastro.html")
    assert route["mode"] == "deliver"
    assert [step.split()[:2] for step in route["next"]] == [["simplicio-loop", "turbo"]]


def test_turbo_command_carries_every_task_and_the_verify_flag(tmp_path):
    argv = shlex.split(turbo_command(tmp_path, ["Create a.py with f()", "Fix the 'quoted' bug in b.py"]))
    tasks = [argv[i + 1] for i, part in enumerate(argv) if part == "--task"]
    assert tasks == ["Create a.py with f()", "Fix the 'quoted' bug in b.py"]
    assert argv.count("--verify") == 1


def test_turbo_command_without_tasks_names_a_placeholder_goal(tmp_path):
    argv = shlex.split(turbo_command(tmp_path))
    assert argv.count("--task") == 1
    assert argv[argv.index("--task") + 1].startswith("<goal")


def test_orient_command_card_is_the_turbo_card(tmp_path):
    card = _orient_command_card(tmp_path)
    assert card["schema"] == COMMAND_CARD_SCHEMA
    assert card["turbo"] == turbo_command(tmp_path)
    assert card["flow"] == ["turbo"]
    assert card["execute_rule"] == TURBO_EXECUTE_RULE
    assert card["requires"] == "OPENROUTER_API_KEY"
    assert "deepseek/deepseek-v4.1-flash" in card["model"]
    assert "verify.passed" in card["done"]
    assert len(json.dumps(card).encode("utf-8")) < COMMAND_CARD_MAX_BYTES
    assert not [needle for needle in OLD_FLOW if needle in json.dumps(card)]


def test_orient_llm_orientation_payload_points_at_turbo():
    """`orient --json` carries `llm_orientation` and `economy status` carries `hot_path`: both name turbo."""
    from simplicio_loop.economy_profile import llm_max_speed_orientation_contract, profile_status

    assert llm_max_speed_orientation_contract()["mutation_boundary"]["next_surfaces"] == ["simplicio-loop turbo"]
    hot_path = " ".join(profile_status()["hot_path"])
    assert "simplicio-loop turbo" in hot_path
    for hand_step in ("simplicio-mapper scan", "simplicio-mapper handoff", "edit --plan"):
        assert hand_step not in hot_path


def test_route_is_the_first_key_of_the_orient_payload(tmp_path):
    """Agents read orient with `| head`; the route must survive truncation."""
    from simplicio_loop.cli_impl import _seal_orient_payload

    payload = {"schema": "x", "status": "OK", "mapper": {"big": "x" * 5000}}
    _seal_orient_payload(payload, root=tmp_path, task="Edit a.html")
    assert list(payload)[0] == "route"
    assert "status" in payload and "receipt" in payload
