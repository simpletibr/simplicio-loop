"""Unit coverage for simplicio/commands/gate.py (N-Nest corrective gate)."""

from __future__ import annotations

import json

from simplicio.commands import gate


def test_sha16_length_and_determinism():
    a = gate.sha16("hello")
    b = gate.sha16("hello")
    assert a == b
    assert len(a) == 16


def test_agent_pid_and_watcher_pid_differ():
    assert gate.agent_pid("addr") != gate.watcher_pid("addr")


def test_truth_deterministic():
    assert gate.truth("addr") == gate.truth("addr")


def test_gate_ok_true_and_false():
    assert gate.gate_ok("a", "a") is True
    assert gate.gate_ok("a", "b") is False


def test_make_agent_honest():
    agent = gate.make_agent("node-a")
    assert agent["gate_ok"] is True
    assert agent["reported"] == agent["truth"]


def test_make_agent_confabulated():
    agent = gate.make_agent("node-a", confabulate=True)
    assert agent["gate_ok"] is False
    assert agent["reported"] != agent["truth"]


def test_tamper_with_explicit_addr():
    agent = gate.tamper("agent/1")
    assert agent["addr"] == "agent/1"
    assert agent["gate_ok"] is False


def test_tamper_random_addr():
    agent = gate.tamper()
    assert agent["addr"].startswith("agent/")
    assert agent["gate_ok"] is False


def test_verify_tree_single_dict():
    agent = gate.make_agent("node-a")
    result = gate.verify_tree(agent)
    assert result["total"] == 1
    assert result["passed"] == 1
    assert result["all_pass"] is True


def test_verify_tree_nested_structure():
    honest = gate.make_agent("node-a")
    tampered = gate.make_agent("node-b", confabulate=True)
    tree = {"nodes": [honest, {"children": [tampered]}]}
    result = gate.verify_tree(tree)
    assert result["total"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert result["all_pass"] is False


def test_verify_tree_list_input():
    honest = gate.make_agent("node-a")
    result = gate.verify_tree([honest])
    assert result["total"] == 1


def test_verify_tree_missing_fields_defaults():
    result = gate.verify_tree({"addr": "node-x"})
    assert result["nodes"][0]["reported"] == ""
    assert result["nodes"][0]["watcherTruth"] == ""
    assert result["nodes"][0]["gate_ok"] is True  # "" == ""


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def test_main_check_pass_text(capsys):
    rc = gate.main(["check", "abc", "abc"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "GATE PASS" in out


def test_main_check_fail_text(capsys):
    rc = gate.main(["check", "abc", "def"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "GATE FAIL" in out


def test_main_check_json(capsys):
    rc = gate.main(["check", "abc", "abc", "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert rc == 0
    assert data["gate_ok"] is True


def test_main_verify_from_file_text(tmp_path, capsys):
    agent = gate.make_agent("node-a")
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(json.dumps(agent), encoding="utf-8")

    rc = gate.main(["verify", str(tree_file)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ALL PASS" in out


def test_main_verify_from_file_json(tmp_path, capsys):
    agent = gate.make_agent("node-a", confabulate=True)
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(json.dumps(agent), encoding="utf-8")

    rc = gate.main(["verify", str(tree_file), "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert rc == 1
    assert data["all_pass"] is False


def test_main_verify_from_stdin(monkeypatch, capsys):
    agent = gate.make_agent("node-a")
    monkeypatch.setattr(gate.sys, "stdin", __import__("io").StringIO(json.dumps(agent)))
    rc = gate.main(["verify"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ALL PASS" in out


def test_main_verify_invalid_json(tmp_path, capsys):
    tree_file = tmp_path / "bad.json"
    tree_file.write_text("not json", encoding="utf-8")
    rc = gate.main(["verify", str(tree_file)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "invalid JSON" in err


def test_main_verify_prints_failures_to_stderr(tmp_path, capsys):
    tampered = gate.make_agent("node-a", confabulate=True)
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(json.dumps(tampered), encoding="utf-8")

    rc = gate.main(["verify", str(tree_file)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "FAIL node-a" in err


def test_main_tamper_text(capsys):
    rc = gate.main(["tamper", "agent/99"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "confabulated agent" in out
    assert "tamper detected" in out


def test_main_tamper_json(capsys):
    rc = gate.main(["tamper", "agent/99", "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert rc == 0
    assert data["addr"] == "agent/99"
