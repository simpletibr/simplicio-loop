"""The evidence workers run their specs on the installed Playwright (`evidence_tools.run_spec`), never on `npx --yes`.

`run_spec` is replaced by a recorder: these tests pin what a worker asks for (its spec, its config, its output folder) and
how it reports what comes back: a pass, a failure with Playwright's own words, or a block that names the missing piece.
The runner itself (where its folder is, its argv, its cleanup) is tested in tests/test_evidence_tools.py.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from simplicio_loop import evidence_tools as ev

REPO = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:3000/login"


def load_script(name: str):
    path = REPO / "scripts" / name
    spec = importlib.util.spec_from_file_location("evidence_worker_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


web_verify = load_script("web_verify.py")
video_evidence = load_script("video_evidence.py")


class Recorder:
    """Stands in for `evidence_tools.run_spec`: records each request and answers with the outcome it was given."""

    def __init__(self, outcome: ev.SpecRun, on_run=None):
        self.outcome, self.on_run, self.requests = outcome, on_run, []

    def __call__(self, state_dir, **request):
        self.requests.append({"state_dir": state_dir, **request})
        if self.on_run is not None:
            self.on_run(request)
        return self.outcome


@pytest.fixture
def toolchain(monkeypatch, tmp_path):
    """The workers look for the tools in <SIMPLICIO_HOME>/.simplicio-loop; `install(outcome)` replaces the runner."""
    monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "home"))

    def install(outcome, on_run=None):
        recorder = Recorder(outcome, on_run)
        monkeypatch.setattr(ev, "run_spec", recorder)
        return recorder

    return install


def exit_code(call) -> int:
    with pytest.raises(SystemExit) as exc:
        call()
    return exc.value.code


def web_options(out: Path) -> dict:
    return {"url": URL, "expect": "Sign in", "issue": "7", "out": str(out)}


def video_options(out: Path) -> dict:
    return {"url": URL, "name": "login-demo", "issue": "7", "out": str(out), "expect": "Sign in"}


def ledger(out: Path) -> str:
    return (out / "ledger.txt").read_text(encoding="utf-8")


# --- web_verify ------------------------------------------------------------------------------------------------------


def test_web_verify_runs_its_spec_on_the_installed_playwright_and_passes(tmp_path, toolchain):
    recorder = toolchain(ev.SpecRun(None, 0, "1 passed"))
    out = tmp_path / "out"
    assert exit_code(lambda: web_verify.cmd_run(web_options(out))) == 0
    [request] = recorder.requests
    assert request["state_dir"] == tmp_path / "home" / ".simplicio-loop"  # the folder `setup` installs into
    assert "require('@playwright/test')" in request["spec"] and json.dumps(URL) in request["spec"]
    assert json.dumps(str(out / "7-web.png")) in request["spec"]  # the screenshot lands in the evidence folder
    assert request["config"] == {"outputDir": str(out / "trace-7"), "use": {"trace": "on"}}
    assert "web_verify: PASS" in ledger(out) and "runner=playwright" in ledger(out)


def test_web_verify_fails_and_names_playwrights_own_failure(tmp_path, toolchain, capsys):
    toolchain(ev.SpecRun(None, 1, "Error: expect(locator).toBeVisible() failed\nLocator: getByText('Sign in')"))
    out = tmp_path / "out"
    assert exit_code(lambda: web_verify.cmd_run(web_options(out))) == 1
    assert "fail" in capsys.readouterr().out.split()
    assert "web_verify: FAIL" in ledger(out) and "toBeVisible() failed" in ledger(out)
    assert "reachable" not in ledger(out)


def test_web_verify_blocked_names_the_missing_piece_and_its_fix(tmp_path, toolchain, capsys):
    toolchain(ev.SpecRun("@playwright/test is not installed (pinned 1.64.1): simplicio-loop setup", None, ""))
    out = tmp_path / "out"
    assert exit_code(lambda: web_verify.cmd_run(web_options(out))) == 3
    shown = capsys.readouterr().out
    assert "blocked" in shown and "simplicio-loop setup" in shown and "reachable" not in shown
    assert "web_verify: BLOCKED" in ledger(out)


def test_web_verify_blocks_when_its_run_does_not_start(tmp_path, toolchain):
    toolchain(ev.SpecRun(None, None, ""))
    out = tmp_path / "out"
    assert exit_code(lambda: web_verify.cmd_run(web_options(out))) == 3
    assert "web_verify: BLOCKED" in ledger(out)


# --- video_evidence (the Playwright recording, the default engine) ---------------------------------------------------


def test_video_evidence_records_the_session_with_playwright_by_default(tmp_path, toolchain, monkeypatch):
    def session(request):  # what Playwright leaves when `use.video` is on: a .webm under the output folder
        clip = Path(request["config"]["outputDir"]) / "login-demo" / "video.webm"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"\x1aE\xdf\xa3" + b"0" * 64)

    recorder = toolchain(ev.SpecRun(None, 0, "1 passed"), on_run=session)
    monkeypatch.setattr(video_evidence.shutil, "which", lambda name: None)  # no FFmpeg here: the .webm is the recording
    out = tmp_path / "out"
    assert exit_code(lambda: video_evidence.cmd_verify(video_options(out))) == 0
    [request] = recorder.requests
    assert json.dumps(URL) in request["spec"] and "page.goto(" in request["spec"]
    assert request["config"]["use"] == {"video": {"mode": "on", "size": {"width": 1280, "height": 720}}}
    assert request["config"]["outputDir"] == str(out / "login-demo-7-pw")
    assert "video_evidence: PASS — demo video (playwright)" in ledger(out) and ".webm" in ledger(out)


def test_video_evidence_fails_with_the_real_failure_of_the_session(tmp_path, toolchain):
    toolchain(ev.SpecRun(None, 1, "Error: page.goto: net::ERR_CONNECTION_REFUSED at " + URL))
    out = tmp_path / "out"
    assert exit_code(lambda: video_evidence.cmd_verify(video_options(out))) == 1
    assert "video_evidence: FAIL" in ledger(out) and "ERR_CONNECTION_REFUSED" in ledger(out)
    assert "reachable" not in ledger(out)


def test_video_evidence_fails_when_the_session_passes_but_records_nothing(tmp_path, toolchain):
    toolchain(ev.SpecRun(None, 0, "1 passed"))
    out = tmp_path / "out"
    assert exit_code(lambda: video_evidence.cmd_verify(video_options(out))) == 1
    assert "video_evidence: FAIL" in ledger(out)


def test_video_evidence_blocked_names_the_missing_piece_and_its_fix(tmp_path, toolchain, capsys):
    toolchain(ev.SpecRun("Chromium is not installed for @playwright/test 1.64.1: simplicio-loop setup", None, ""))
    out = tmp_path / "out"
    assert exit_code(lambda: video_evidence.cmd_verify(video_options(out))) == 3
    shown = capsys.readouterr().out
    assert "blocked" in shown and "simplicio-loop setup" in shown and "reachable" not in shown


def test_video_evidence_without_a_url_is_blocked_before_any_run(tmp_path, toolchain):
    recorder = toolchain(ev.SpecRun(None, 0, "1 passed"))
    out = tmp_path / "out"
    options = video_options(out)
    del options["url"]
    assert exit_code(lambda: video_evidence.cmd_verify(options)) == 3
    assert recorder.requests == []
