"""`watch247 --mode {batch,lockfree}` (#1820): batch unless asked, lockfree only for that exact value, and a help text that says so."""

import os
import subprocess
import sys

import pytest

from simplicio_loop import cli_impl, merge_lockfree


@pytest.fixture
def watcher(monkeypatch):
    """Replace the watcher's loop with a recorder; the mode variable is cleared before and after, whatever the test does."""
    os.environ.pop(merge_lockfree.MODE_ENV, None)
    calls = []

    async def fake_main(once=False, dry_run=False):
        calls.append({"once": once, "dry_run": dry_run, "mode": os.environ.get(merge_lockfree.MODE_ENV)})
        return 0

    monkeypatch.setattr("simplicio_loop.watcher247.__main__.main", fake_main)
    yield calls
    os.environ.pop(merge_lockfree.MODE_ENV, None)


def test_the_help_names_both_modes_the_default_and_the_gate():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    result = subprocess.run([sys.executable, "-m", "simplicio_loop.cli", "watch247", "--help"], capture_output=True, text=True,
                            env=env, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    text = " ".join((result.stdout + result.stderr).split())
    assert "--mode {batch,lockfree}" in text
    assert "default: batch" in text
    assert "lockfree (opt-in, #1820)" in text
    assert "approval gate applies to both modes" in text
    assert "docs/MERGE_LOCKFREE.md" in text


def test_without_the_flag_the_run_is_not_switched_to_lockfree(watcher):
    assert cli_impl.main(["watch247", "--once"]) == 0
    assert watcher == [{"once": True, "dry_run": False, "mode": None}]
    assert merge_lockfree.mode_from_env() == "batch"


def test_the_flag_sets_the_mode_of_this_run(watcher):
    assert cli_impl.main(["watch247", "--mode", "lockfree", "--dry-run"]) == 0
    assert watcher == [{"once": False, "dry_run": True, "mode": "lockfree"}]


def test_an_explicit_batch_keeps_batch(watcher):
    assert cli_impl.main(["watch247", "--mode", "batch", "--once"]) == 0
    assert watcher[0]["mode"] == "batch"


def test_a_value_other_than_batch_or_lockfree_is_refused_before_anything_runs(watcher, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli_impl.main(["watch247", "--mode", "lock-free", "--once"])
    assert exit_info.value.code == 2
    assert watcher == []
    assert "lockfree" in capsys.readouterr().err
