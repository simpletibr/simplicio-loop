from __future__ import annotations

import json

import pytest

from simplicio_loop import cli_impl


def test_tick_does_not_report_completed_without_a_v1_publication(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_impl,
        "execute_operator",
        lambda *args, **kwargs: {"status": "completed", "run_id": "run-1"},
    )

    assert cli_impl.tick("missing-repo", "run-1", 1) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"].lower() in {"blocked", "partial"}
    assert payload["schema"] == "simplicio.loop-execution/v1"
    assert payload["verified"] is False


@pytest.mark.parametrize("phase", ["blocked", "partial", "error"])
def test_nonterminal_public_flow_preserves_diagnostic_state(tmp_path, phase):
    state = {
        "phase": phase,
        "blockers": [f"{phase}-diagnostic"],
        "completion": {"ready": False, "tag": "UNVERIFIED"},
    }
    status = {
        "manifest": {"run_id": "run-1", "repo": str(tmp_path)},
        "run_dir": str(tmp_path / ".simplicio" / "loop-runs" / "run-1"),
        "state": state,
    }

    result = cli_impl._public_flow_from_status(
        status, "run", {"status": phase, "run_id": "run-1"}
    )

    assert result["status"] in {"BLOCKED", "PARTIAL", "ERROR"}
    assert result["status"] not in {"COMPLETE", "VERIFIED"}
    assert result["verified"] is False
    assert result["state"] == state
