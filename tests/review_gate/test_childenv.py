from __future__ import annotations

import sys

from simplicio_loop.review_gate import childenv, mutation


def test_scrubbed_drops_secrets_and_points_home_at_the_tree(monkeypatch, tmp_path):
    monkeypatch.setenv("GH_TOKEN", "ghp_secret")
    monkeypatch.setenv("HOME", "/root")
    env = childenv.scrubbed(tmp_path, {"EXTRA": "1"})
    assert "GH_TOKEN" not in env
    assert env["HOME"] == str(tmp_path)
    assert env["EXTRA"] == "1"
    assert "PATH" in env


def test_mutation_run_does_not_leak_the_watcher_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("GH_TOKEN", "ghp_secret")
    probe = [sys.executable, "-c", "import os, sys; sys.exit(1 if 'GH_TOKEN' in os.environ else 0)"]
    assert mutation._run(tmp_path, probe, 60, lambda argv: argv, None) == 0
