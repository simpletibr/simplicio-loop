"""Tests for issue #111: native-vs-python delegation telemetry.

Covers `simplicio.runtime_bridge.record_delegation` itself, plus every
delegable verb's call site (`gate`/`nest` in `cli.py`, `commands/edit.py`,
`commands/file_read.py`, `commands/test_run.py`) — each is exercised with a
fake/absent `simplicio` binary (no real Rust runtime in this environment,
same pattern `tests/contracts/conftest.py`'s `stub_runtime_binary` and
`test_end_to_end_flow.py` already use) so the route (`native` /
`python-fallback` / `python-forced`) is asserted from the resulting
`.simplicio/events.jsonl` / `.simplicio/ledger/savings-events.jsonl`
records rather than from internal call counts.
"""

from __future__ import annotations

import argparse
import json
import stat

import pytest

from simplicio import cli
from simplicio.commands import edit as edit_cmd
from simplicio.commands import file_read as file_read_cmd
from simplicio.commands import test_run as test_run_cmd
from simplicio.runtime_bridge import DELEGATION_ROUTES, record_delegation


def _events(root) -> list[dict]:
    out = root / ".simplicio" / "events.jsonl"
    if not out.exists():
        return []
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]


def _delegation_events(root) -> list[dict]:
    return [e for e in _events(root) if e["event"] == "native_delegation"]


def _savings_events(root) -> list[dict]:
    out = root / ".simplicio" / "ledger" / "savings-events.jsonl"
    if not out.exists():
        return []
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]


# --------------------------------------------------------------------------- #
# record_delegation itself
# --------------------------------------------------------------------------- #


def test_record_delegation_rejects_unknown_route(tmp_path):
    with pytest.raises(ValueError, match="route"):
        record_delegation("gate", "sideways", root=str(tmp_path))


def test_record_delegation_writes_event_and_honest_zero_savings(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    record_delegation("gate", "native", root=str(tmp_path))

    events = _delegation_events(tmp_path)
    assert len(events) == 1
    assert events[0]["payload"] == {"verb": "gate", "route": "native"}
    assert events[0]["level"] == "info"

    savings = _savings_events(tmp_path)
    assert len(savings) == 1
    assert savings[0]["source"] == "native-delegation:gate"
    assert savings[0]["proof_kind"] == "estimated"
    assert savings[0]["tokens"] == {"baseline": 0, "actual": 0, "saved": 0, "pct_saved": 0.0}


def test_record_delegation_routine_fallback_stays_info_level(tmp_path):
    record_delegation("file", "python-fallback", root=str(tmp_path), reason="binary-not-found")
    events = _delegation_events(tmp_path)
    assert events[0]["level"] == "info"


def test_record_delegation_real_failure_fallback_is_warning_level(tmp_path):
    record_delegation("file", "python-fallback", root=str(tmp_path), reason="schema-mismatch")
    events = _delegation_events(tmp_path)
    assert events[0]["level"] == "warning"
    assert events[0]["payload"]["reason"] == "schema-mismatch"


def test_delegation_routes_constant_covers_expected_set():
    assert set(DELEGATION_ROUTES) == {"native", "python-fallback", "python-forced"}


# --------------------------------------------------------------------------- #
# gate / nest (cli.py::_dispatch_nested)
# --------------------------------------------------------------------------- #


def test_gate_check_records_python_fallback_when_binary_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.delenv("SIMPLICIO_BIN", raising=False)
    monkeypatch.setattr("simplicio.runtime_bridge.shutil.which", lambda name: None)

    code = cli.main(["gate", "check", "abc", "abc"])

    assert code == 0
    events = _delegation_events(tmp_path)
    assert len(events) == 1
    assert events[0]["payload"]["verb"] == "gate"
    assert events[0]["payload"]["route"] == "python-fallback"
    assert events[0]["payload"]["reason"] == "binary-not-found"


def test_gate_check_records_python_forced_with_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main(["gate", "check", "abc", "abc", "--python"])

    assert code == 0
    events = _delegation_events(tmp_path)
    assert events[0]["payload"]["route"] == "python-forced"
    assert events[0]["payload"]["reason"] == "user-forced-python"


def test_nest_build_records_native_when_binary_available(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    script = tmp_path / "bin" / "simplicio"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "#!/usr/bin/env python3\nprint('{\"ok\": true}')\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("SIMPLICIO_BIN", str(script))

    code = cli.main(["nest", "build", "2", "1"])

    assert code == 0
    events = _delegation_events(tmp_path)
    assert events[0]["payload"] == {"verb": "nest", "route": "native"}


def test_gate_help_does_not_record_delegation(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    with pytest.raises(SystemExit):
        cli.main(["gate", "--help"])
    capsys.readouterr()
    assert _delegation_events(tmp_path) == []


# --------------------------------------------------------------------------- #
# edit (commands/edit.py::run_edit)
# --------------------------------------------------------------------------- #


def _plan_path(tmp_path):
    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [{"op": "create_file", "path": "x.txt", "text": "hi\n"}],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return plan_path


def test_run_edit_records_python_forced_via_no_runtime_flag(tmp_path):
    code = edit_cmd.run_edit(
        argparse.Namespace(
            root=str(tmp_path), plan=str(_plan_path(tmp_path)), apply=True, json=True, no_runtime=True
        )
    )
    assert code == 0
    events = _delegation_events(tmp_path)
    assert events[0]["payload"]["verb"] == "edit"
    assert events[0]["payload"]["route"] == "python-forced"


def test_run_edit_records_python_fallback_via_env_disable(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    code = edit_cmd.run_edit(
        argparse.Namespace(
            root=str(tmp_path), plan=str(_plan_path(tmp_path)), apply=True, json=True, no_runtime=False
        )
    )
    assert code == 0
    events = _delegation_events(tmp_path)
    assert events[0]["payload"]["route"] == "python-forced"
    assert "SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT" in events[0]["payload"]["reason"]


def test_run_edit_records_python_fallback_when_no_binary_on_path(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", raising=False)
    monkeypatch.setattr("simplicio.commands.edit.shutil.which", lambda name: None)
    code = edit_cmd.run_edit(
        argparse.Namespace(
            root=str(tmp_path), plan=str(_plan_path(tmp_path)), apply=True, json=True, no_runtime=False
        )
    )
    assert code == 0
    events = _delegation_events(tmp_path)
    assert events[0]["payload"]["route"] == "python-fallback"
    assert events[0]["payload"]["reason"] == "binary-not-found"


# --------------------------------------------------------------------------- #
# file read (commands/file_read.py::run)
# --------------------------------------------------------------------------- #


def test_file_read_records_python_fallback_when_no_binary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("simplicio.commands.file_read.discover_simplicio", lambda: None)
    target = tmp_path / "hello.txt"
    target.write_text("hi\n", encoding="utf-8")

    code = file_read_cmd.run(
        argparse.Namespace(
            path="hello.txt", json=True, start=None, end=None, max_bytes=None, repo=str(tmp_path)
        )
    )

    assert code == 0
    capsys.readouterr()
    events = _delegation_events(tmp_path)
    assert events[0]["payload"]["verb"] == "file"
    assert events[0]["payload"]["route"] == "python-fallback"
    assert events[0]["payload"]["reason"] == "binary-not-found"


# --------------------------------------------------------------------------- #
# test run (commands/test_run.py::run)
# --------------------------------------------------------------------------- #


def test_test_run_records_python_fallback_when_no_binary(tmp_path, monkeypatch, capsys):
    import sys

    monkeypatch.setattr("simplicio.commands.test_run.discover_simplicio", lambda: None)

    code = test_run_cmd.run(
        argparse.Namespace(cmd=sys.executable, json=True, repo=str(tmp_path), timeout=30.0),
        ["-c", "print(1)"],
    )

    assert code == 0
    capsys.readouterr()
    events = _delegation_events(tmp_path)
    assert events[0]["payload"]["verb"] == "test-run"
    assert events[0]["payload"]["route"] == "python-fallback"
    assert events[0]["payload"]["reason"] == "binary-not-found"
