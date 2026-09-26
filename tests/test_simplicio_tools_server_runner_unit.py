import json

from engine import simplicio_mcp


def test_mcp_advertises_explicit_runner_state_machine_tool():
    response = simplicio_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = {item["name"]: item for item in response["result"]["tools"]}
    schema = tools["simplicio_runner"]["inputSchema"]
    assert schema["required"] == ["action"]
    assert schema["properties"]["action"]["enum"] == ["arm", "status", "resume", "tick", "batch", "cancel"]


def test_mcp_runner_status_delegates_to_persisted_runner(monkeypatch, tmp_path):
    from simplicio_loop import runner
    expected = {"run_id": "run-1", "state": {"phase": "planning"}}
    monkeypatch.setattr(runner, "read_status", lambda repo, run_id=None: expected)
    response = simplicio_mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "simplicio_runner", "arguments": {"action": "status", "repo": str(tmp_path), "run_id": "run-1"}}})
    assert json.loads(response["result"]["content"][0]["text"]) == expected


def test_mcp_runner_rejects_unknown_action():
    response = simplicio_mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "simplicio_runner", "arguments": {"action": ""}}})
    assert "action must be one of" in response["result"]["content"][0]["text"]


def test_mcp_runner_batch_rejects_non_integer_indices():
    response = simplicio_mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "simplicio_runner", "arguments": {"action": "batch", "run_id": "run-1", "task_indices": ["1"]}}})
    assert "task_indices must be an array of integers" in response["result"]["content"][0]["text"]
