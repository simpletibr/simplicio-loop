"""The evidence workers run their specs on the installed Playwright (`evidence_tools.run_spec`), never on `npx --yes`.

`run_spec` is replaced by a recorder: these tests pin what a worker asks for (its spec, its config, its output folder) and
how it reports what comes back: a pass, a failure with Playwright's own words, or a block that names the missing piece.
The runner itself (where its folder is, its argv, its cleanup) is tested in tests/test_evidence_tools.py.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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


# --- web_verify, the pytest runner (Fallback B): a fresh folder, this Python's pytest, and the failure text -------------

PYTEST_OPTIONS = {"runner": "pytest"}


def completed(argv, code, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr=stderr)


def test_the_pytest_runner_runs_its_spec_in_a_fresh_folder_with_this_pythons_pytest_and_reports_the_failure(tmp_path, monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(argv=list(argv), cwd=kwargs.get("cwd"), spec_existed=Path(argv[3]).is_file())
        return completed(argv, 1, stdout="F", stderr="E   AssertionError: 'Sign in' not found\n")

    monkeypatch.setattr(web_verify, "_run", fake_run)
    out = tmp_path / "out"
    assert exit_code(lambda: web_verify.cmd_run({**web_options(out), **PYTEST_OPTIONS})) == 1
    assert seen["argv"][:3] == [sys.executable, "-m", "pytest"]  # not whatever `pytest` the PATH finds
    assert seen["spec_existed"] and Path(seen["argv"][3]).parent == Path(seen["cwd"])
    assert not Path(seen["cwd"]).exists()  # the run folder is removed when the run is over
    assert "web_verify: FAIL" in ledger(out) and "AssertionError: 'Sign in' not found" in ledger(out)


def test_the_pytest_runner_passes_on_exit_zero_and_leaves_no_folder(tmp_path, monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["cwd"] = kwargs.get("cwd")
        return completed(argv, 0, stdout="1 passed")

    monkeypatch.setattr(web_verify, "_run", fake_run)
    out = tmp_path / "out"
    assert exit_code(lambda: web_verify.cmd_run({**web_options(out), **PYTEST_OPTIONS})) == 0
    assert "web_verify: PASS" in ledger(out) and "runner=pytest" in ledger(out)
    assert not Path(seen["cwd"]).exists()


def test_the_pytest_runner_is_blocked_with_the_fix_when_this_python_has_no_pytest(tmp_path, monkeypatch):
    monkeypatch.setattr(web_verify, "_run", lambda argv, **kw: completed(argv, 1, stderr="No module named pytest\n"))
    out = tmp_path / "out"
    assert exit_code(lambda: web_verify.cmd_run({**web_options(out), **PYTEST_OPTIONS})) == 3
    assert "web_verify: BLOCKED" in ledger(out) and "pytest is not installed" in ledger(out) and "pip install" in ledger(out)


# --- video_evidence, the hyperframes explainer: the pinned binary of the tools folder, never `npx` ---------------------


def install_hyperframes(home: Path) -> Path:
    """What `setup` leaves for the explainer: the pinned hyperframes in its own folder, with its bin."""
    state = home / ".simplicio-loop"
    package = ev.hyperframes_folder(state) / "node_modules" / "hyperframes"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": "hyperframes", "version": ev.HYPERFRAMES_VERSION}))
    binary = ev.hyperframes_bin(state)
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    return binary


def test_the_explainer_renders_with_the_pinned_hyperframes_of_the_tools_folder_and_never_npx(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "home"))
    binary = install_hyperframes(tmp_path / "home")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append([str(part) for part in argv])
        if Path(argv[0]).name == "node":
            return completed(argv, 0, stdout="v26.0.0\n")
        if "render" in argv:
            Path(argv[argv.index("-o") + 1]).write_bytes(b"mp4")
        return completed(argv, 0)

    monkeypatch.setattr(video_evidence, "_run", fake_run)
    monkeypatch.setattr(video_evidence.shutil, "which", lambda name: "/fake/ffmpeg" if name == "ffmpeg" else None)
    out = tmp_path / "out"
    (out / "demo").mkdir(parents=True)
    (out / "demo" / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    assert exit_code(lambda: video_evidence.cmd_render({"name": "demo", "out": str(out), "issue": "7"})) == 0
    [render] = [call for call in calls if "render" in call]
    assert render[0] == str(binary)
    assert not any("npx" in call[0] for call in calls)


def test_the_explainer_scaffolds_with_a_non_interactive_init_that_names_an_example_and_skips_the_skills_check(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "home"))
    binary = install_hyperframes(tmp_path / "home")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(([str(part) for part in argv], kwargs.get("env") or {}))
        return completed(argv, 0)

    monkeypatch.setattr(video_evidence, "_run", fake_run)
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "1-web.png").write_bytes(b"png")
    video_evidence.cmd_scaffold({"name": "demo", "out": str(tmp_path / "out"), "frames": str(shots), "title": "Sign in"})
    [(init, env)] = [(argv, env) for argv, env in calls if "init" in argv]
    assert init[0] == str(binary)
    assert init[init.index("--example") + 1] == "blank" and "--non-interactive" in init  # init refuses to run without an example
    assert env.get("HYPERFRAMES_SKIP_SKILLS") == "1"  # the pinned init checks skills on GitHub unless told not to


def test_the_explainer_lints_with_the_pinned_hyperframes_of_the_tools_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "home"))
    binary = install_hyperframes(tmp_path / "home")
    calls = []
    monkeypatch.setattr(video_evidence, "_run", lambda argv, **kw: calls.append([str(part) for part in argv]) or completed(argv, 0))
    out = tmp_path / "out"
    assert exit_code(lambda: video_evidence.cmd_lint({"name": "demo", "out": str(out)})) == 0
    assert calls == [[str(binary), "lint"]]


def test_the_explainer_is_blocked_with_the_fix_when_its_hyperframes_is_not_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(video_evidence, "_run", lambda argv, **kw: pytest.fail("no command may run without hyperframes"))
    out = tmp_path / "out"
    assert exit_code(lambda: video_evidence.cmd_lint({"name": "demo", "out": str(out)})) == 3
    assert "video_evidence: BLOCKED" in ledger(out) and "simplicio-loop setup" in ledger(out)
