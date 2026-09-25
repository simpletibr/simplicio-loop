"""Public CLI help is an executable part of the Loop contract."""

from __future__ import annotations

import os
import subprocess
import sys


ROOT_COMMANDS = {
    "install": "install bundled",
    "plan": "compile a raw task",
    "wave": "dispatch a governed wave",
    "orient": "orient a task",
    "preflight": "verify bound operators",
    "deploy": "plan a gated",
    "verify": "run the independent",
    "batch": "continuously dispatch",
    "queue": "operate the durable",
    "findings": "inspect and reconcile",
}


def _help(*args: str) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    result = subprocess.run(
        [sys.executable, "-m", "simplicio_loop.cli", *args, "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout + result.stderr


def _module_help(module: str) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout + result.stderr


def test_root_commands_explain_their_purpose():
    output = _help()
    for command, phrase in ROOT_COMMANDS.items():
        assert f"    {command}" in output, command
        assert phrase in output, command


def test_queue_help_explains_every_action():
    output = _help("queue")
    for action in (
        "status",
        "resume",
        "doctor",
        "reclaim",
        "migrate",
        "top",
        "drain",
        "gc",
        "inspect",
        "cancel",
    ):
        assert f"    {action}" in output, action


def test_generation_broker_help_explains_every_action():
    output = _module_help("simplicio_loop.generation_broker_cli")
    for action in ("status", "reconcile", "doctor", "inspect", "pin", "release"):
        assert f"    {action}" in output, action
