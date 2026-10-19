"""`simplicio-loop setup` and the evidence tools (#1843): the evidence step is a fake, the report and the exit codes are real."""
from __future__ import annotations

import json

from simplicio_loop import prereqs, setup_cli

from .fakes import Fakes, check, run, summary_file


def chromium_will_not_install(fakes):
    fakes.evidence_checks = [check("evidence:node"), check("evidence:playwright"),
                             prereqs.Check("evidence:chromium", "missing", True, None, None, None, "simplicio-loop setup", "user")]
    fakes.evidence_actions = [prereqs.Action("evidence:chromium", "failed", "`playwright install chromium` did not finish (exit 1)")]


def test_a_browser_that_will_not_install_is_named_and_setup_is_pending_with_the_fix(home):
    fakes = Fakes()
    chromium_will_not_install(fakes)
    code, text = run(fakes, home)
    assert code == setup_cli.PENDING
    assert "Evidence tools" in text and "did not finish (exit 1)" in text
    assert "evidence:chromium: missing. Fix: simplicio-loop setup" in text
    assert json.loads(summary_file(home).read_text())["schema"] == "simplicio.setup/v1"  # the rest of setup is still recorded


def test_the_json_report_carries_the_evidence_checks_actions_and_the_pending_item(home):
    fakes = Fakes()
    chromium_will_not_install(fakes)
    code, text = run(fakes, home, json_out=True)
    doc = json.loads(text)
    assert code == setup_cli.PENDING
    assert [c["name"] for c in doc["evidence"]] == ["evidence:node", "evidence:playwright", "evidence:chromium"]
    assert {"item": "evidence:chromium", "why": "missing", "fix": "simplicio-loop setup"} in doc["pending"]
    assert any(a["name"] == "evidence:chromium" and a["result"] == "failed" for a in doc["actions"])


def test_a_real_run_installs_and_proves_while_check_and_dry_run_only_plan(home):
    fakes = Fakes()
    assert run(fakes, home)[0] == 0
    call = [c for c in fakes.calls if c[0] == "evidence"][-1][1]
    assert call["dry_run"] is False and call["validate"] is True and call["state_dir"] == home / ".simplicio-loop"
    fakes.calls.clear()
    run(fakes, home, check=True)
    call = [c for c in fakes.calls if c[0] == "evidence"][-1][1]
    assert call["dry_run"] is True and call["validate"] is False
    fakes.calls.clear()
    run(fakes, home, dry_run=True)
    assert [c for c in fakes.calls if c[0] == "evidence"][-1][1]["dry_run"] is True


def test_check_reports_a_missing_tool_as_pending_and_says_it_would_install(home):
    fakes = Fakes()
    chromium_will_not_install(fakes)
    fakes.evidence_actions = [prereqs.Action("evidence:chromium", "would-install", "Chromium for @playwright/test 1.64.1")]
    code, text = run(fakes, home, check=True)
    assert code == setup_cli.PENDING and "would-install" in text
    assert not summary_file(home).exists()  # a check writes nothing


def test_setup_asks_the_evidence_step_for_the_explainer_only_with_with_hyperframes(home):
    fakes = Fakes()
    assert run(fakes, home)[0] == 0
    assert [c for c in fakes.calls if c[0] == "evidence"][-1][1]["hyperframes"] is False
    fakes.calls.clear()
    assert run(fakes, home, with_hyperframes=True)[0] == 0
    assert [c for c in fakes.calls if c[0] == "evidence"][-1][1]["hyperframes"] is True


def test_setup_is_complete_when_every_evidence_tool_is_ok(home):
    fakes = Fakes()
    code, text = run(fakes, home)
    assert code == 0 and "Pending" not in text
