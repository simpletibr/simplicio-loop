"""action_gate hand-edit gate unit tests.

There is no Runtime/MCP backend in this stack; ``mcp_force_sync.py`` and its
MCP-force gate in ``action_gate.py`` were removed with it.
"""

from __future__ import annotations


def test_action_gate_hand_edit_forbidden_under_strict(monkeypatch):
    import action_gate as ag

    monkeypatch.setenv("SIMPLICIO_LOOP_STRICT", "1")
    assert ag._hand_edit_forbidden() is True
    monkeypatch.delenv("SIMPLICIO_LOOP_STRICT", raising=False)
    monkeypatch.delenv("SIMPLICIO_LOOP_FORBID_HAND_EDIT", raising=False)
    monkeypatch.delenv("SIMPLICIO_LOOP_MODE", raising=False)
    assert ag._hand_edit_forbidden() is False


def _pretooluse(ag, monkeypatch, tool_input, tool="Write"):
    import io
    import json

    import pytest

    monkeypatch.setattr(ag, "_project_relevant", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": tool, "tool_input": tool_input})))
    with pytest.raises(SystemExit) as exc:
        ag.from_pretooluse()
    return exc.value.code


def test_strict_mode_lets_the_host_write_the_turbo_plan_and_nothing_else(monkeypatch, capsys):
    """The plan file is loop state the invoking model must write; every other hand edit stays blocked."""
    import action_gate as ag

    monkeypatch.setenv("SIMPLICIO_LOOP_STRICT", "1")
    assert _pretooluse(ag, monkeypatch, {"file_path": "/repo/.simplicio-loop/turbo/plan.json"}) == 0
    assert _pretooluse(ag, monkeypatch, {"file_path": ".simplicio-loop/turbo/plan.json"}) == 0
    assert _pretooluse(ag, monkeypatch, {"file_path": "/repo/src/app.py"}) == 2
    assert _pretooluse(ag, monkeypatch, {"file_path": "/repo/.simplicio-loop/turbo/plan.json.py"}) == 2
    assert _pretooluse(ag, monkeypatch, {"file_path": "/repo/.simplicio-loop/turbo/plan.json/../../app.py"}) == 2
    capsys.readouterr()
