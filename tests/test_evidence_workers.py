"""The evidence workers run their specs on the installed Playwright (`evidence_tools.run_spec`), never on `npx --yes`.

`run_spec` is replaced by a recorder: these tests pin what a worker asks for (its spec, its config, its output folder) and
how it reports what comes back: a pass, a failure with Playwright's own words, or a block that names the missing piece.
The runner itself (where its folder is, its argv, its cleanup) is tested in tests/test_evidence_tools.py.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
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


# --- FFmpeg: a binary is used only when it answers `-version`; the .webm stays when it does not --------------------------

BROKEN_LIBVPX = "dyld: Library not loaded: /opt/homebrew/opt/libvpx/lib/libvpx.9.dylib"


def test_a_broken_ffmpeg_is_named_with_its_fix_and_the_webm_is_kept(tmp_path, toolchain, monkeypatch, capsys):
    def session(request):
        clip = Path(request["config"]["outputDir"]) / "login-demo" / "video.webm"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"\x1aE\xdf\xa3" + b"0" * 64)

    toolchain(ev.SpecRun(None, 0, "1 passed"), on_run=session)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append([str(part) for part in argv])
        return completed(argv, 1, stderr=BROKEN_LIBVPX)  # the Homebrew ffmpeg that is on PATH but does not load

    monkeypatch.setattr(video_evidence.shutil, "which", lambda name: "/opt/homebrew/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(video_evidence, "_run", fake_run)
    out = tmp_path / "out"
    assert exit_code(lambda: video_evidence.cmd_verify(video_options(out))) == 0
    assert calls == [["/opt/homebrew/bin/ffmpeg", "-version"]]  # checked, and never used for the conversion
    shown = capsys.readouterr().out
    assert "brew reinstall ffmpeg" in shown and "HYPERFRAMES_FFMPEG_PATH" in shown and BROKEN_LIBVPX in shown
    assert "video_evidence: PASS" in ledger(out) and ".webm" in ledger(out)


def test_a_working_ffmpeg_converts_the_recording_to_mp4(tmp_path, toolchain, monkeypatch):
    def session(request):
        clip = Path(request["config"]["outputDir"]) / "login-demo" / "video.webm"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"\x1aE\xdf\xa3" + b"0" * 64)

    toolchain(ev.SpecRun(None, 0, "1 passed"), on_run=session)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append([str(part) for part in argv])
        if "-version" not in argv:
            Path(argv[-1]).write_bytes(b"mp4")
        return completed(argv, 0)

    monkeypatch.setattr(video_evidence.shutil, "which", lambda name: "/fake/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(video_evidence, "_run", fake_run)
    out = tmp_path / "out"
    assert exit_code(lambda: video_evidence.cmd_verify(video_options(out))) == 0
    assert any(call[1:3] == ["-y", "-i"] for call in calls) and ".mp4" in ledger(out)


def test_a_failed_conversion_is_reported_with_the_ffmpeg_stderr_tail_and_the_webm_is_kept(tmp_path, toolchain, monkeypatch, capsys):
    def session(request):
        clip = Path(request["config"]["outputDir"]) / "login-demo" / "video.webm"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"\x1aE\xdf\xa3" + b"0" * 64)

    toolchain(ev.SpecRun(None, 0, "1 passed"), on_run=session)
    calls = []
    stderr = "[mov,mp4 @ 0x7f] moov atom not found\nvideo.webm: Invalid data found when processing input\n"

    def fake_run(argv, **kwargs):
        calls.append([str(part) for part in argv])
        if "-version" in argv:
            return completed(argv, 0)
        return completed(argv, 1, stderr=stderr)  # FFmpeg starts, then fails on the recording

    monkeypatch.setattr(video_evidence.shutil, "which", lambda name: "/fake/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(video_evidence, "_run", fake_run)
    out = tmp_path / "out"
    assert exit_code(lambda: video_evidence.cmd_verify(video_options(out))) == 0  # the recording itself passed
    assert any(call[1:3] == ["-y", "-i"] for call in calls)  # the conversion was attempted
    assert not (out / "login-demo-7.mp4").exists()
    assert "video_evidence: PASS" in ledger(out) and "video.webm" in ledger(out)
    assert "mp4 conversion failed (ffmpeg exit 1" in ledger(out)
    assert "Invalid data found when processing input" in ledger(out)  # the reason is kept, not only the outcome
    assert "Invalid data found when processing input" in capsys.readouterr().out  # and printed for the operator


def test_render_is_blocked_with_the_fix_when_ffmpeg_does_not_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "home"))
    install_hyperframes(tmp_path / "home")
    monkeypatch.setattr(video_evidence.shutil, "which", lambda name: "/opt/homebrew/bin/ffmpeg" if name == "ffmpeg" else None)

    def fake_run(argv, **kwargs):
        if Path(argv[0]).name == "node":
            return completed(argv, 0, stdout="v26.0.0\n")
        if "-version" in argv:
            return completed(argv, 1, stderr=BROKEN_LIBVPX)
        pytest.fail("the explainer must not render with a broken ffmpeg")

    monkeypatch.setattr(video_evidence, "_run", fake_run)
    out = tmp_path / "out"
    (out / "demo").mkdir(parents=True)
    (out / "demo" / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    assert exit_code(lambda: video_evidence.cmd_render({"name": "demo", "out": str(out), "issue": "7"})) == 3
    assert "brew reinstall ffmpeg" in ledger(out) and "HYPERFRAMES_FFMPEG_PATH" in ledger(out)


def test_a_failed_render_says_why_with_the_tail_of_hyperframes_stderr(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "home"))
    install_hyperframes(tmp_path / "home")
    monkeypatch.setattr(video_evidence.shutil, "which", lambda name: "/fake/ffmpeg" if name == "ffmpeg" else None)

    def fake_run(argv, **kwargs):
        if Path(argv[0]).name == "node":
            return completed(argv, 0, stdout="v26.0.0\n")
        if "-version" in argv:
            return completed(argv, 0)
        return completed(argv, 1, stderr="warning: slow frame\nError: no Chrome found at /Applications/Chrome.app\n")

    monkeypatch.setattr(video_evidence, "_run", fake_run)
    out = tmp_path / "out"
    (out / "demo").mkdir(parents=True)
    (out / "demo" / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    assert exit_code(lambda: video_evidence.cmd_render({"name": "demo", "out": str(out), "issue": "7"})) == 1
    assert "video_evidence: FAIL" in ledger(out) and "mp4=(not produced)" in ledger(out)
    assert "Error: no Chrome found at /Applications/Chrome.app" in ledger(out)  # the reason, not only the outcome


def test_the_ffmpeg_named_by_hyperframes_ffmpeg_path_is_the_one_that_is_checked(monkeypatch):
    monkeypatch.setenv("HYPERFRAMES_FFMPEG_PATH", "/opt/ffmpeg-good/ffmpeg")
    calls = []
    monkeypatch.setattr(video_evidence, "_run", lambda argv, **kw: calls.append([str(p) for p in argv]) or completed(argv, 0))
    monkeypatch.setattr(video_evidence.shutil, "which", lambda name: pytest.fail("the env path needs no PATH search"))
    assert video_evidence._ffmpeg() == ("/opt/ffmpeg-good/ffmpeg", None)
    assert calls == [["/opt/ffmpeg-good/ffmpeg", "-version"]]


def test_no_ffmpeg_at_all_is_named_with_the_install_fix(monkeypatch):
    monkeypatch.delenv("HYPERFRAMES_FFMPEG_PATH", raising=False)
    monkeypatch.setattr(video_evidence.shutil, "which", lambda name: None)
    monkeypatch.setattr(video_evidence, "_run", lambda argv, **kw: pytest.fail("nothing to run without ffmpeg"))
    path, problem = video_evidence._ffmpeg()
    assert path is None and "not found" in problem and "brew install ffmpeg" in problem
    assert "sudo apt-get install -y ffmpeg" in problem  # the Linux install, next to the macOS one


# --- a consumer repository: a pip install has no checkout, so a run writes into the repo it is bound to (SIMPLICIO_REPO) --


@contextlib.contextmanager
def _set_aside_modules(*names):
    """Remove `names` from sys.modules while a worker loads, then put back what was there (and drop what the load added)."""
    saved = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def load_bound(name: str, monkeypatch, simplicio_repo=None):
    """Load scripts/<name> as a fresh module, bound the way consumer_cli binds a run: SIMPLICIO_REPO, else the checkout."""
    if simplicio_repo is None:
        monkeypatch.delenv("SIMPLICIO_REPO", raising=False)
    else:
        monkeypatch.setenv("SIMPLICIO_REPO", str(simplicio_repo))
    monkeypatch.delenv("SIMPLICIO_ANCHOR_FILE", raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))  # a worker's sys.path insertions end with this test
    path = REPO / "scripts" / name
    spec = importlib.util.spec_from_file_location("evidence_worker_bound_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    with _set_aside_modules("task_anchor", "task_backlog", "delivery_contract", "loop_progress", "toon_codec"):
        spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name, defaults", [
    ("web_verify.py", ["DEFAULT_OUT"]),
    ("video_evidence.py", ["DEFAULT_OUT"]),
    ("pr_evidence.py", ["DEFAULT_SHOTS", "DEFAULT_VIDEO_SHOTS", "ANCHOR_DEFAULT"]),
])
def test_a_consumer_run_writes_its_evidence_under_simplicio_repo(name, defaults, tmp_path, monkeypatch):
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    worker = load_bound(name, monkeypatch, simplicio_repo=consumer)
    for attr in defaults:
        assert getattr(worker, attr).startswith(str(consumer) + os.sep), (attr, getattr(worker, attr))


def test_without_simplicio_repo_a_checkout_run_still_writes_into_its_own_checkout(monkeypatch):
    worker = load_bound("web_verify.py", monkeypatch, simplicio_repo=None)
    assert worker.DEFAULT_OUT == os.path.join(str(REPO), ".simplicio-loop/orchestrator", "tee", "web")


def test_a_consumer_bound_pr_evidence_keeps_the_checkout_on_sys_path_not_the_consumer(tmp_path, monkeypatch):
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    load_bound("pr_evidence.py", monkeypatch, simplicio_repo=consumer)
    assert str(consumer) not in sys.path  # `from simplicio_loop import ...` resolves from the source, never the consumer


def test_how_to_verify_names_the_check_script_only_where_the_repository_has_it(tmp_path, monkeypatch):
    bare = tmp_path / "bare"
    bare.mkdir()
    gated = tmp_path / "gated"
    (gated / "scripts").mkdir(parents=True)
    (gated / "scripts" / "check.py").write_text("print('gate')\n", encoding="utf-8")
    plain_body, _ = load_bound("pr_evidence.py", monkeypatch, simplicio_repo=bare).build_body({"title": "t", "item": "7"})
    gated_body, _ = load_bound("pr_evidence.py", monkeypatch, simplicio_repo=gated).build_body({"title": "t", "item": "7"})
    assert "### How to verify" in plain_body and "Run the repository's tests" in plain_body
    assert "scripts/check.py" not in plain_body
    assert "python3 scripts/check.py" in gated_body
