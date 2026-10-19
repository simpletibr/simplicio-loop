"""The evidence tools of the delivery flow (#1843): probed, installed and proven without the real network or browser.

`run` and `which` are fakes. `FakeMachine` answers like the real commands did on this Mac and leaves the files the real
installs leave (package.json, node_modules/@playwright/test, the chromium folder with INSTALLATION_COMPLETE), so every
state of the machine is reachable in a temp folder.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop import evidence_tools as ev

PIN = ev.PLAYWRIGHT_VERSION
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
DRY_RUN = """Chrome for Testing 156.0.8078.4 (playwright chromium v1248)
  Install location:    {cache}/chromium-1248
  Download url:        https://cdn.playwright.dev/builds/cft/156.0.8078.4/mac-arm64/chrome-mac-arm64.zip

FFmpeg (playwright ffmpeg v1013)
  Install location:    {cache}/ffmpeg-1013
  Download url:        https://cdn.playwright.dev/dbazure/download/playwright/builds/ffmpeg/1013/ffmpeg-mac-arm64.zip

Chrome Headless Shell 156.0.8078.4 (playwright chromium-headless-shell v1248)
  Install location:    {cache}/chromium_headless_shell-1248
  Download url:        https://cdn.playwright.dev/builds/cft/156.0.8078.4/mac-arm64/chrome-headless-shell-mac-arm64.zip
"""


class FakeMachine:
    """Answers like the real commands: `node --version`, `npm install`, `playwright install`, `playwright test`."""

    def __init__(self, tmp: Path, *, node="v26.0.0", npm_exit=0, browser_exit=0, test_exit=0, proof="full"):
        self.cache = tmp / "ms-playwright"
        self.node, self.npm_exit, self.browser_exit, self.test_exit, self.proof = node, npm_exit, browser_exit, test_exit, proof
        self.calls: list[list[str]] = []
        self.envs: list[dict] = []

    def which(self, name: str):
        if name == "node" and self.node is None:
            return None
        return f"/opt/fake/bin/{name}"

    def run(self, argv, timeout, cwd=None, env=None):
        argv = [str(part) for part in argv]
        self.calls.append(argv)
        self.envs.append(dict(env or {}))
        head = Path(argv[0]).name
        if head == "node":
            return (0, f"{self.node}\n") if self.node else (None, "")
        if head == "npm":
            if self.npm_exit:
                return self.npm_exit, "npm ERR! network request failed"
            pkg = Path(cwd) / "node_modules" / "@playwright" / "test"
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "package.json").write_text(json.dumps({"name": "@playwright/test", "version": PIN}))
            (Path(cwd) / "node_modules" / ".bin").mkdir(parents=True, exist_ok=True)
            (Path(cwd) / "node_modules" / ".bin" / "playwright").write_text("#!/bin/sh\n")
            return 0, "added 3 packages"
        if head == "playwright":
            if argv[1:4] == ["install", "--dry-run", "chromium"]:
                return 0, DRY_RUN.format(cache=self.cache)
            if argv[1:3] == ["install", "chromium"]:
                if self.browser_exit:
                    return self.browser_exit, "Error: download of chromium-1248 failed"
                build = self.cache / "chromium-1248"
                build.mkdir(parents=True, exist_ok=True)
                (build / "INSTALLATION_COMPLETE").write_text("")
                return 0, "chromium-1248 installed"
            if argv[1] == "test":
                if self.test_exit:
                    return self.test_exit, "Error: Executable doesn't exist at chromium-1248"
                spec = Path(argv[2])
                if self.proof in ("full", "no-clip"):
                    (spec.parent / "shot.png").write_bytes(PNG)
                if self.proof == "full":
                    out = Path(argv[argv.index("--output") + 1]) / "evidence-check-chromium" / "video.webm"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(b"\x1aE\xdf\xa3" + b"0" * 64)
                return 0, "1 passed"
        return None, ""


def environ_for(tmp: Path) -> dict:
    return {"HOME": str(tmp), "PATH": "/opt/fake/bin"}


def by_name(rows, name):
    return next(row for row in rows if row.name == name)


# --- what the code calls ---------------------------------------------------------------------------------------------


def test_the_chromium_build_is_read_from_the_dry_run_output(tmp_path):
    found = ev.browser_location(DRY_RUN.format(cache="/Users/x/Library/Caches/ms-playwright"))
    assert found == ("Chrome for Testing 156.0.8078.4", "1248", "/Users/x/Library/Caches/ms-playwright/chromium-1248")
    assert ev.browser_location("no browser here") is None


def test_the_pin_is_the_version_the_evidence_flow_runs_on_and_node_must_be_22_or_newer():
    assert ev.MIN_NODE == 22
    assert PIN == "1.64.1"


# --- probing ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("version,status", [("v22.1.0", "ok"), ("v26.0.0", "ok"), ("v20.11.1", "outdated")])
def test_node_is_ok_at_22_or_newer_and_outdated_below(tmp_path, version, status):
    machine = FakeMachine(tmp_path, node=version)
    node = by_name(ev.check_all(tmp_path / "state", environ=environ_for(tmp_path), which=machine.which, run=machine.run), ev.NODE)
    assert node.status == status and node.required
    if status == "outdated":
        assert "22" in node.fix


def test_missing_node_is_missing_with_the_install_fix_and_nothing_else_is_probed(tmp_path):
    machine = FakeMachine(tmp_path, node=None)
    checks = ev.check_all(tmp_path / "state", environ=environ_for(tmp_path), which=machine.which, run=machine.run)
    assert by_name(checks, ev.NODE).status == "missing" and "Node.js" in by_name(checks, ev.NODE).fix
    assert by_name(checks, ev.CHROMIUM).status == "missing" and "Node.js" in by_name(checks, ev.CHROMIUM).fix
    assert not any(Path(argv[0]).name == "playwright" for argv in machine.calls)  # no browser is started to look


def test_the_playwright_folder_is_ok_only_at_the_pinned_version(tmp_path):
    state = tmp_path / "state"
    project = ev.folder(state)
    package = project / "node_modules" / "@playwright" / "test"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"version": "1.10.0"}))
    machine = FakeMachine(tmp_path)
    assert by_name(ev.check_all(state, environ=environ_for(tmp_path), which=machine.which, run=machine.run), ev.PLAYWRIGHT).status == "outdated"
    (package / "package.json").write_text(json.dumps({"version": PIN}))
    assert by_name(ev.check_all(state, environ=environ_for(tmp_path), which=machine.which, run=machine.run), ev.PLAYWRIGHT).status == "missing"  # no bin yet
    (project / "node_modules" / ".bin").mkdir(parents=True)
    (project / "node_modules" / ".bin" / "playwright").write_text("#!/bin/sh\n")
    assert by_name(ev.check_all(state, environ=environ_for(tmp_path), which=machine.which, run=machine.run), ev.PLAYWRIGHT).status == "ok"


def test_chromium_is_ok_only_when_its_build_folder_is_complete(tmp_path):
    machine = FakeMachine(tmp_path)
    state = tmp_path / "state"
    machine.run(["npm"], 1, cwd=ev.folder(state))  # lays down the project the way npm does
    (ev.folder(state) / "node_modules" / ".bin" / "playwright").write_text("#!/bin/sh\n")
    chromium = by_name(ev.check_all(state, environ=environ_for(tmp_path), which=machine.which, run=machine.run), ev.CHROMIUM)
    assert chromium.status == "missing" and chromium.fix == "simplicio-loop setup"
    (machine.cache / "chromium-1248").mkdir(parents=True)
    (machine.cache / "chromium-1248" / "INSTALLATION_COMPLETE").write_text("")
    chromium = by_name(ev.check_all(state, environ=environ_for(tmp_path), which=machine.which, run=machine.run), ev.CHROMIUM)
    assert chromium.status == "ok" and chromium.path == str(machine.cache / "chromium-1248") and "156.0.8078.4" in chromium.version


# --- installing ------------------------------------------------------------------------------------------------------


def test_missing_tools_are_installed_in_the_loop_folder_then_proven(tmp_path):
    machine = FakeMachine(tmp_path)
    state = tmp_path / "state"
    checks, actions = ev.step(state, environ=environ_for(tmp_path), which=machine.which, run=machine.run,
                              dry_run=False, validate=True)
    assert [(a.name, a.result) for a in actions] == [(ev.PLAYWRIGHT, "installed"), (ev.CHROMIUM, "installed"), (ev.CHECK, "validated")]
    assert all(c.status == "ok" for c in checks), checks
    package = json.loads((ev.folder(state) / "package.json").read_text())
    assert package["dependencies"] == {"@playwright/test": PIN}  # the exact pin, not a range
    npm = next(call for call in machine.calls if Path(call[0]).name == "npm")
    assert npm[1] == "install" and "--prefix" not in npm  # run inside the loop folder
    assert [Path(c[0]).name for c in machine.calls].count("playwright") == 3  # browser install, dry-run probe, validation run


def test_the_children_get_the_checked_node_first_on_their_path_and_the_browser_cache_setting(tmp_path):
    machine = FakeMachine(tmp_path)
    environ = {**environ_for(tmp_path), "PLAYWRIGHT_BROWSERS_PATH": "/cache/ms", "AWS_SECRET_ACCESS_KEY": "nope"}
    ev.step(tmp_path / "state", environ=environ, which=machine.which, run=machine.run, dry_run=False, validate=False)
    npm_at = [Path(argv[0]).name for argv in machine.calls].index("npm")
    install_env = machine.envs[npm_at]
    assert install_env["PATH"].split(":")[0] == "/opt/fake/bin"
    assert install_env["PLAYWRIGHT_BROWSERS_PATH"] == "/cache/ms"
    assert "AWS_SECRET_ACCESS_KEY" not in install_env


def test_a_failed_npm_install_names_the_tool_and_leaves_it_missing(tmp_path):
    machine = FakeMachine(tmp_path, npm_exit=1)
    checks, actions = ev.step(tmp_path / "state", environ=environ_for(tmp_path), which=machine.which, run=machine.run,
                              dry_run=False, validate=True)
    failed = [a for a in actions if a.result == "failed"]
    assert [a.name for a in failed] == [ev.PLAYWRIGHT] and "exit 1" in failed[0].detail
    assert by_name(checks, ev.PLAYWRIGHT).status == "missing"
    assert ev.CHECK not in [c.name for c in checks]  # nothing is proven when a tool is missing
    assert not any(Path(argv[0]).name == "playwright" and argv[1] == "test" for argv in machine.calls)


def test_a_failed_browser_install_is_named_and_the_proof_is_not_run(tmp_path):
    machine = FakeMachine(tmp_path, browser_exit=1)
    checks, actions = ev.step(tmp_path / "state", environ=environ_for(tmp_path), which=machine.which, run=machine.run,
                              dry_run=False, validate=True)
    assert [(a.name, a.result) for a in actions if a.result == "failed"] == [(ev.CHROMIUM, "failed")]
    assert "download of chromium-1248 failed" in next(a for a in actions if a.name == ev.CHROMIUM).detail
    assert by_name(checks, ev.CHROMIUM).status == "missing"
    assert not any(Path(argv[0]).name == "playwright" and argv[1] == "test" for argv in machine.calls)


def test_a_dry_run_installs_nothing_and_starts_no_browser(tmp_path):
    machine = FakeMachine(tmp_path)
    _, actions = ev.step(tmp_path / "state", environ=environ_for(tmp_path), which=machine.which, run=machine.run,
                         dry_run=True, validate=True)
    assert [(a.name, a.result) for a in actions] == [(ev.PLAYWRIGHT, "would-install"), (ev.CHROMIUM, "would-install")]
    assert not any(Path(argv[0]).name == "npm" for argv in machine.calls)
    assert not any(argv[1:2] == ["test"] for argv in machine.calls)


def test_the_proof_runs_after_an_install_even_without_validate_but_not_on_a_plain_check(tmp_path):
    machine = FakeMachine(tmp_path)
    state = tmp_path / "state"
    ev.step(state, environ=environ_for(tmp_path), which=machine.which, run=machine.run, dry_run=False, validate=False)
    assert any(argv[1:2] == ["test"] for argv in machine.calls)  # something was installed in this run, so it is proven
    plain = FakeMachine(tmp_path)  # the same machine the next day: the folder and the browser are already there
    checks, actions = ev.step(state, environ=environ_for(tmp_path), which=plain.which, run=plain.run, dry_run=False, validate=False)
    assert [a.name for a in actions] == [] and all(c.status == "ok" for c in checks)
    assert not any(argv[1:2] == ["test"] for argv in plain.calls)


# --- proving ---------------------------------------------------------------------------------------------------------


def test_the_proof_passes_only_with_a_png_screenshot_and_a_webm_clip(tmp_path):
    machine = FakeMachine(tmp_path)
    _, actions = ev.step(tmp_path / "state", environ=environ_for(tmp_path), which=machine.which, run=machine.run,
                         dry_run=False, validate=True)
    proof = next(a for a in actions if a.name == ev.CHECK)
    assert proof.result == "validated" and "screenshot" in proof.detail and "clip" in proof.detail
    run_argv = next(argv for argv in machine.calls if argv[1:2] == ["test"])
    assert run_argv[3] == "--output" and run_argv[5:] == ["--reporter", "line", "--workers", "1"]  # a headless run, one worker


@pytest.mark.parametrize("proof,words", [("no-clip", "clip"), ("none", "screenshot")])
def test_a_run_without_its_proof_fails_and_says_which_part_is_missing(tmp_path, proof, words):
    machine = FakeMachine(tmp_path, proof=proof)
    checks, actions = ev.step(tmp_path / "state", environ=environ_for(tmp_path), which=machine.which, run=machine.run,
                              dry_run=False, validate=True)
    result = next(a for a in actions if a.name == ev.CHECK)
    assert result.result == "failed" and words in result.detail
    assert by_name(checks, ev.CHECK).status == "failed" and by_name(checks, ev.CHECK).fix == "simplicio-loop setup"


def test_a_failed_test_run_reports_the_tail_of_its_output(tmp_path):
    machine = FakeMachine(tmp_path, test_exit=1)
    _, actions = ev.step(tmp_path / "state", environ=environ_for(tmp_path), which=machine.which, run=machine.run,
                         dry_run=False, validate=True)
    result = next(a for a in actions if a.name == ev.CHECK)
    assert result.result == "failed" and "Executable doesn't exist" in result.detail and "exit 1" in result.detail


def test_the_proof_leaves_no_page_or_spec_behind(tmp_path):
    machine = FakeMachine(tmp_path)
    state = tmp_path / "state"
    ev.step(state, environ=environ_for(tmp_path), which=machine.which, run=machine.run, dry_run=False, validate=True)
    assert [p.name for p in ev.folder(state).iterdir() if p.name.startswith("check-")] == []


# --- doctor rows -----------------------------------------------------------------------------------------------------


def test_probe_rows_are_ok_with_the_version_or_warn_with_the_fix_and_install_nothing(tmp_path):
    machine = FakeMachine(tmp_path)
    state = tmp_path / "state"
    rows = ev.probe_rows(state, environ=environ_for(tmp_path), which=machine.which, run=machine.run)
    assert [(r["name"], r["status"]) for r in rows] == [(ev.NODE, "ok"), (ev.PLAYWRIGHT, "warn"), (ev.CHROMIUM, "warn")]
    assert all(r["fix"] for r in rows if r["status"] == "warn") and rows[0]["summary"].startswith("node 26.0.0")
    assert not any(Path(argv[0]).name == "npm" or argv[1:2] == ["test"] for argv in machine.calls)
    machine.run(["npm"], 1, cwd=ev.folder(state))  # lays down the folder the install would make: the pin and the bin
    (machine.cache / "chromium-1248").mkdir(parents=True)
    (machine.cache / "chromium-1248" / "INSTALLATION_COMPLETE").write_text("")
    rows = ev.probe_rows(state, environ=environ_for(tmp_path), which=machine.which, run=machine.run)
    assert [r["status"] for r in rows] == ["ok", "ok", "ok"]
    assert PIN in rows[1]["summary"] and "156.0.8078.4" in rows[2]["summary"] and rows[2]["fix"] is None
