"""After every evidence gate passes on a host-edit-plan run, the loop records the
exact promise for the Completion Oracle, exactly as it does for the
OpenRouter coordinator route (there is no agent message to capture in a CLI run)."""
from __future__ import annotations

import json

from simplicio_loop import runner


def _run_dir(tmp_path, route):
    (tmp_path / "loop").mkdir()
    (tmp_path / "loop" / "scratchpad.md").write_text(
        '---\niteration: 1\ncompletion_promise: "ALL DONE"\n---\ngoal\n', encoding="utf-8")
    (tmp_path / "operator-receipt.json").write_text(json.dumps({"provider_config": {"route": route}}))
    return tmp_path


def test_host_edit_plan_route_records_the_exact_promise(tmp_path):
    run_dir = _run_dir(tmp_path, "host-edit-plan")
    path = runner._persist_external_completion_response(run_dir)
    assert path and "<promise>ALL DONE</promise>" in (run_dir / "loop" / "last_response.txt").read_text()


def test_unknown_routes_record_nothing(tmp_path):
    run_dir = _run_dir(tmp_path, "something-else")
    assert runner._persist_external_completion_response(run_dir) == ""
