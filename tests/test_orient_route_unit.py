"""orient answers the delivery flow for every task count."""
import json

from simplicio_loop.cli_impl import _orient_route, delivery_execute_verb


def _survey(root, files, edges=()):
    out = root / ".simplicio-loop"
    out.mkdir()
    (out / "project-map.json").write_text(json.dumps({"files": [{"path": f} for f in files]}))
    (out / "symbol-index.json").write_text(json.dumps({"symbols": []}))
    (out / "call-graph.json").write_text(json.dumps({"edges": list(edges)}))


def test_delivery_verb_is_tick_for_one_task_and_wave_for_more():
    assert delivery_execute_verb(1) == "tick"
    assert delivery_execute_verb(2) == "wave"
    assert delivery_execute_verb(4) == "wave"


def test_every_task_routes_through_prepare_tick_or_wave_and_verify(tmp_path):
    _survey(tmp_path, ["cadastro.html", "README.md"])
    route = _orient_route(tmp_path, "Edit cadastro.html: add a phone field")
    assert route["mode"] == "deliver"
    joined = " ".join(route["next"])
    assert "simplicio-loop prepare --task tasks.md" in joined
    assert "edit-plan-<N>.json" in joined
    assert "simplicio-loop tick" in joined
    assert "simplicio-loop wave" in joined
    assert "simplicio-loop verify" in joined
    assert "simplicio-dev-cli edit --plan ops.json" not in joined


def test_multi_file_task_uses_the_same_delivery_flow(tmp_path):
    _survey(tmp_path, ["a.html", "b.html"])
    route = _orient_route(tmp_path, "Edit a.html and b.html")
    assert route["mode"] == "deliver"
    assert route["execute_rule"] == "1 task -> tick; 2 or more -> wave"


def test_missing_survey_still_requires_the_delivery_flow(tmp_path):
    route = _orient_route(tmp_path, "Edit cadastro.html")
    assert route["mode"] == "deliver"
    assert any("simplicio-loop verify" in step for step in route["next"])


def test_route_is_the_first_key_of_the_orient_payload(tmp_path):
    """Agents read orient with `| head`; the route must survive truncation."""
    from simplicio_loop.cli_impl import _seal_orient_payload

    payload = {"schema": "x", "status": "OK", "mapper": {"big": "x" * 5000}}
    _seal_orient_payload(payload, root=tmp_path, task="Edit a.html")
    assert list(payload)[0] == "route"
    assert "status" in payload and "receipt" in payload
