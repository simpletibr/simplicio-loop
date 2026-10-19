"""MiMo Code adapter: the shared AGENTS.md-surface contract, bound to this host's row in adapters/mimo-code/adapter.py."""
import importlib

from tests.agents_md_host_contract import assert_self_paced_agents_md_host

ROW = importlib.import_module("adapters.mimo-code.adapter").HOST


def test_mimo_code_is_a_self_paced_agents_md_host(tmp_path):
    assert_self_paced_agents_md_host(ROW, tmp_path)
