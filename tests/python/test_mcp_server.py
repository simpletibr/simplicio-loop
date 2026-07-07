"""simplicio-dev-cli as an MCP stdio server — stdlib-only JSON-RPC 2.0
dispatcher (issue #89 P0). `handle_message` is exercised directly (no real
stdio) so these tests are fast and deterministic."""

import io
import json

from simplicio import mcp_server


def test_initialize_reports_protocol_and_tools_capability():
    resp = mcp_server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSION
    assert "tools" in resp["result"]["capabilities"]
    assert resp["result"]["serverInfo"]["name"] == "simplicio-dev-cli"


def test_initialized_notification_has_no_response():
    resp = mcp_server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp is None


def test_tools_list_exposes_the_three_p0_tools():
    resp = mcp_server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"dev_cli_edit", "dev_cli_validate", "dev_cli_memory"}
    for tool in resp["result"]["tools"]:
        assert "inputSchema" in tool
        assert "description" in tool


def test_unknown_method_is_a_jsonrpc_error():
    resp = mcp_server.handle_message({"jsonrpc": "2.0", "id": 3, "method": "nope/nope"})
    assert resp["error"]["code"] == -32601


def test_unknown_method_notification_is_silently_ignored():
    resp = mcp_server.handle_message({"jsonrpc": "2.0", "method": "nope/nope"})
    assert resp is None


def test_tools_call_unknown_tool_is_a_jsonrpc_error():
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        }
    )
    assert resp["error"]["code"] == -32602


def test_tools_call_dev_cli_validate_ok(tmp_path):
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "dev_cli_validate",
                "arguments": {
                    "output": "diff --git a/x b/x\n--- a/x\n+++ b/x\nTEST:\nassert True",
                },
            },
        }
    )
    result = resp["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True


def test_tools_call_dev_cli_validate_missing_diff_flags_hint():
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "dev_cli_validate", "arguments": {"output": "no diff here"}},
        }
    )
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["ok"] is False
    assert payload["hints"]


def test_tools_call_dev_cli_memory_init_store_recall(tmp_path):
    mem_dir = str(tmp_path / "mem")

    init_resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "dev_cli_memory", "arguments": {"action": "init", "dir": mem_dir}},
        }
    )
    init_payload = json.loads(init_resp["result"]["content"][0]["text"])
    assert init_payload["created"] is True

    store_resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "dev_cli_memory",
                "arguments": {
                    "action": "store",
                    "dir": mem_dir,
                    "topic": "handoff test",
                    "content": "cross-vendor note",
                },
            },
        }
    )
    store_payload = json.loads(store_resp["result"]["content"][0]["text"])
    assert store_payload["slug"] == "handoff-test"

    recall_resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "dev_cli_memory",
                "arguments": {"action": "recall", "dir": mem_dir, "query": "cross-vendor"},
            },
        }
    )
    recall_payload = json.loads(recall_resp["result"]["content"][0]["text"])
    assert len(recall_payload["results"]) == 1


def test_tools_call_dev_cli_memory_unknown_action_is_iserror():
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "dev_cli_memory", "arguments": {"action": "delete-everything"}},
        }
    )
    assert resp["result"]["isError"] is True


def test_tools_call_dev_cli_edit_dry_run(tmp_path):
    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [
            {"op": "create_file", "path": "hello.txt", "content": "hi\n"},
        ],
    }
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "dev_cli_edit",
                "arguments": {"root": str(tmp_path), "plan": plan, "apply": False},
            },
        }
    )
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["status"] == "ok"
    assert not (tmp_path / "hello.txt").exists()  # dry-run: nothing applied


def test_serve_stdio_round_trips_over_string_streams():
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
    stdin = io.StringIO(request)
    stdout = io.StringIO()
    mcp_server.serve_stdio(stdin=stdin, stdout=stdout)
    lines = [line for line in stdout.getvalue().splitlines() if line]
    assert len(lines) == 1
    response = json.loads(lines[0])
    assert response["result"]["serverInfo"]["name"] == "simplicio-dev-cli"


def test_serve_stdio_malformed_json_gets_parse_error():
    stdin = io.StringIO("not json\n")
    stdout = io.StringIO()
    mcp_server.serve_stdio(stdin=stdin, stdout=stdout)
    response = json.loads(stdout.getvalue().strip())
    assert response["error"]["code"] == -32700


def test_cli_serve_mcp_delegates_to_serve_stdio(tmp_path, monkeypatch):
    from simplicio import cli

    monkeypatch.setenv("HOME", str(tmp_path))  # no .claude dir -> no autoinstall side effects
    calls = []
    monkeypatch.setattr(mcp_server, "serve_stdio", lambda: calls.append(True))
    code = cli.main(["serve", "--mcp"])
    assert code == 0
    assert calls == [True]


def test_cli_serve_without_mcp_flag_errors(tmp_path, monkeypatch):
    from simplicio import cli

    monkeypatch.setenv("HOME", str(tmp_path))
    code = cli.main(["serve"])
    assert code == 2
