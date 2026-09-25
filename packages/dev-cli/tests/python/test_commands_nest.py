"""Unit tests for ``simplicio nest`` (N-Nest tree build/verify/tamper), a
previously 0%-covered module (simplicio/commands/nest.py) with no existing
test file.
"""

from __future__ import annotations

import json

from simplicio.commands import nest


def test_build_tree_intact_when_untampered():
    tree = nest.build_tree(2, 2)
    result = nest.verify_tree(tree)
    assert result["all_gate_ok"] is True
    assert result["all_subtree_ok"] is True
    assert result["failed_gates"] == []
    # a depth-2 binary tree has 1 (root) + 2 + 4 = 7 nodes
    assert result["total_nodes"] == 7


def test_build_tree_deterministic_hashes():
    tree_a = nest.build_tree(2, 2)
    tree_b = nest.build_tree(2, 2)
    assert tree_a["root"]["true_val"] == tree_b["root"]["true_val"]


def test_build_tree_tamper_breaks_gate_at_addr_and_propagates_to_root():
    tree = nest.build_tree(2, 2, tamper_addr="R.0")
    result = nest.verify_tree(tree)
    assert result["all_gate_ok"] is False
    tampered_addrs = {n["addr"] for n in result["failed_gates"]}
    assert tampered_addrs == {"R.0"}
    # the tamper propagates subtree_ok=False up to the root
    root_node = next(n for n in result["nodes"] if n["addr"] == "R")
    assert root_node["subtree_ok"] is False
    assert root_node["gate_ok"] is True  # root's own gate is untouched


def test_walk_nodes_returns_flat_preorder_list():
    tree = nest.build_tree(2, 1)
    nodes = nest.walk_nodes(tree["root"])
    addrs = [n["addr"] for n in nodes]
    assert addrs == ["R", "R.0", "R.1"]


def test_sha16_is_deterministic_and_16_hex_chars():
    digest = nest.sha16("hello")
    assert len(digest) == 16
    assert digest == nest.sha16("hello")
    assert digest != nest.sha16("world")


# --------------------------------------------------------------------------- #
# CLI handlers
# --------------------------------------------------------------------------- #


def test_cmd_build_text_output_intact(capsys):
    code = nest.cmd_build(["2", "2"])
    assert code == 0
    out = capsys.readouterr().out
    assert "=> INTACT" in out


def test_cmd_build_json_output(capsys):
    code = nest.cmd_build(["2", "1", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["branching"] == 2
    assert payload["depth"] == 1
    assert payload["verification"]["all_gate_ok"] is True


def test_cmd_build_with_tamper_reports_failure(capsys):
    code = nest.cmd_build(["2", "1", "--tamper", "R.0"])
    assert code == 1
    captured = capsys.readouterr()
    assert "=> TAMPERED" in captured.out
    assert "GATE FAIL" in captured.err


def test_cmd_build_rejects_invalid_branching(capsys):
    code = nest.cmd_build(["1", "2"])
    assert code == 2
    assert "branching must be >= 2" in capsys.readouterr().err


def test_cmd_build_rejects_invalid_depth(capsys):
    code = nest.cmd_build(["2", "0"])
    assert code == 2
    assert "depth must be >= 1" in capsys.readouterr().err


def test_cmd_verify_from_file(tmp_path, capsys):
    tree = nest.build_tree(2, 1)
    tree_path = tmp_path / "tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    code = nest.cmd_verify([str(tree_path)])
    assert code == 0
    assert "=> INTACT" in capsys.readouterr().out


def test_cmd_verify_json_output(tmp_path, capsys):
    tree = nest.build_tree(2, 1, tamper_addr="R.1")
    tree_path = tmp_path / "tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    code = nest.cmd_verify([str(tree_path), "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["all_gate_ok"] is False


def test_cmd_verify_missing_file_returns_error(tmp_path, capsys):
    code = nest.cmd_verify([str(tmp_path / "does-not-exist.json")])
    assert code == 2
    assert "nest verify" in capsys.readouterr().err


def test_cmd_verify_bad_json_returns_error(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    code = nest.cmd_verify([str(bad)])
    assert code == 2
    assert "nest verify" in capsys.readouterr().err


def test_cmd_tamper_reports_gate_and_propagated_subtree_failure(capsys):
    code = nest.cmd_tamper(["2", "2", "R.0"])
    assert code == 1
    captured = capsys.readouterr()
    assert "=> TAMPERED" in captured.out
    assert "GATE FAIL" in captured.err
    assert "SUBTREE FAIL (propagated)" in captured.err


def test_cmd_tamper_json_output(capsys):
    code = nest.cmd_tamper(["2", "1", "R.0", "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["tamper_addr"] == "R.0"


def test_cmd_tamper_rejects_invalid_branching(capsys):
    code = nest.cmd_tamper(["1", "2", "R.0"])
    assert code == 2
    assert "branching must be >= 2" in capsys.readouterr().err


def test_cmd_tamper_rejects_invalid_depth(capsys):
    code = nest.cmd_tamper(["2", "0", "R.0"])
    assert code == 2
    assert "depth must be >= 1" in capsys.readouterr().err


def test_main_dispatches_build(capsys):
    code = nest.main(["build", "2", "1"])
    assert code == 0
    assert "=> INTACT" in capsys.readouterr().out


def test_main_dispatches_verify(tmp_path, capsys):
    tree = nest.build_tree(2, 1)
    tree_path = tmp_path / "tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")
    code = nest.main(["verify", str(tree_path)])
    assert code == 0


def test_main_dispatches_tamper(capsys):
    code = nest.main(["tamper", "2", "1", "R.0"])
    assert code == 1
