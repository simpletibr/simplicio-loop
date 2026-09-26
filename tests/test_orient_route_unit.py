"""orient answers the route itself (installed CLI, no repo-local script):
one task on one leaf file -> fast-path with the exact dev-cli commands."""
import json

from simplicio_loop.cli_impl import _orient_route


def _survey(root, files, edges=()):
    out = root / ".simplicio-loop"
    out.mkdir()
    (out / "project-map.json").write_text(json.dumps({"files": [{"path": f} for f in files]}))
    (out / "symbol-index.json").write_text(json.dumps({"symbols": []}))
    (out / "call-graph.json").write_text(json.dumps({"edges": list(edges)}))


def test_single_leaf_file_task_routes_fast_path_with_commands(tmp_path):
    _survey(tmp_path, ["cadastro.html", "README.md"])
    route = _orient_route(tmp_path, "Edit cadastro.html: add a phone field")
    assert route["mode"] == "fast-path"
    joined = " ".join(route["next"])
    assert "simplicio-dev-cli edit --plan ops.json --compile plan.json" in joined
    assert "simplicio-dev-cli edit --plan plan.json --apply --json" in joined


def test_multi_file_task_routes_to_wave(tmp_path):
    _survey(tmp_path, ["a.html", "b.html"])
    route = _orient_route(tmp_path, "Edit a.html and b.html")
    assert route["mode"] == "converge"
    assert any("simplicio-loop prepare" in step for step in route["next"])


def test_missing_survey_fails_closed_to_wave(tmp_path):
    route = _orient_route(tmp_path, "Edit cadastro.html")
    assert route["mode"] == "converge"


def test_route_is_the_first_key_of_the_orient_payload(tmp_path):
    """Agents read orient with `| head`; the route must survive truncation."""
    from simplicio_loop.cli_impl import _seal_orient_payload

    payload = {"schema": "x", "status": "OK", "fast": {"big": "x" * 5000}}
    _seal_orient_payload(payload, root=tmp_path, task="Edit a.html", fast_mode="auto",
                         fast_engine="python", fast_context_budget=1000)
    assert list(payload)[0] == "route"
    assert "status" in payload and "receipt" in payload
