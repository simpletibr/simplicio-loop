"""The delivery evidence tools (#1843): what `setup`, `install` and `doctor` check, install and prove.

The evidence (screenshots and clips of a delivery) runs on Playwright. The code calls exactly these tools on that path:
Node.js 22 or newer, the Playwright test runner (`@playwright/test`, which ships the `playwright` command), and the
Chromium build that runner drives (`playwright install chromium` also fetches the ffmpeg build it records video with).
FFmpeg and the hyperframes explainer are optional and not checked here. browser-use and cua are not called anywhere in
this repository, so they are not required.

The tools live in one folder of the loop, `<state dir>/evidence-tools`: a `package.json` that pins `@playwright/test`,
its `node_modules`, and the browser cache Playwright keeps (`PLAYWRIGHT_BROWSERS_PATH` or its default). Nothing goes into
the Python environment: no Python package is on this path. Node.js itself is only checked, never installed.

`step` probes, installs what is missing and, when asked (or after an install), proves the tools with a real run: a local
page is opened, a screenshot is taken and a short clip is recorded. `probe_rows` gives `doctor` the same facts without
installing anything or starting a browser.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Optional

from . import setup_hardening
from .prereqs import Action, Check

MIN_NODE = 22  # references/video-evidence.md: "Node.js 22+"
PLAYWRIGHT_VERSION = "1.64.1"  # the exact @playwright/test the evidence runs on; its Chromium build is the one it drives
FOLDER = "evidence-tools"
NODE, PLAYWRIGHT, CHROMIUM, CHECK = "evidence:node", "evidence:playwright", "evidence:chromium", "evidence:check"
NODE_FIX = "install Node.js 22 or newer: https://nodejs.org, or `brew install node`"
SETUP_FIX = "simplicio-loop setup"
MARKER = "INSTALLATION_COMPLETE"  # Playwright writes it last, when a browser build is complete
PROBE_S, INSTALL_S, PROOF_S = 60.0, 900.0, 300.0
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_NODE_VERSION = re.compile(r"\s*v?(\d+)\.(\d+)(?:\.(\d+))?")
_HEADER = re.compile(r"^\s*(?P<label>[^()\n]+?)\s*\(playwright chromium v(?P<build>\d+)\)\s*$", re.MULTILINE)
_LOCATION = re.compile(r"Install location:\s*(?P<path>\S.*?)\s*$", re.MULTILINE)
PAGE = ('<!doctype html>\n<html><head><meta charset="utf-8"><title>simplicio evidence check</title></head>\n'
        "<body><h1>simplicio evidence check</h1></body></html>\n")
SPEC = """const { test, expect } = require('@playwright/test');
const path = require('path');
const { pathToFileURL } = require('url');

test.use({ video: { mode: 'on', size: { width: 640, height: 360 } } });

test('evidence check', async ({ page }) => {
  await page.goto(pathToFileURL(path.join(__dirname, 'page.html')).href, { waitUntil: 'load', timeout: 30000 });
  await expect(page.getByText('simplicio evidence check')).toBeVisible({ timeout: 15000 });
  await page.screenshot({ path: path.join(__dirname, 'shot.png'), fullPage: true });
  await page.waitForTimeout(500);
});
"""

Run = Callable[..., tuple[Optional[int], str]]
Which = Callable[[str], Optional[str]]


def execute(argv: Sequence[object], timeout: float, cwd: Optional[Path] = None,
            env: Optional[Mapping[str, str]] = None) -> tuple[Optional[int], str]:
    """Run a program without a shell: (exit code, the last 4 KiB of its output). The code is None when it did not start or ran out of time."""
    try:
        done = subprocess.run([str(part) for part in argv], capture_output=True, text=True, errors="replace",
                              stdin=subprocess.DEVNULL, timeout=timeout, shell=False, cwd=cwd,
                              env=None if env is None else dict(env))
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return done.returncode, (done.stdout + done.stderr)[-4096:]


def folder(state_dir: Path) -> Path:
    return Path(state_dir) / FOLDER


def _bin(project: Path) -> Path:
    return project / "node_modules" / ".bin" / ("playwright.cmd" if os.name == "nt" else "playwright")


def _env(environ: Mapping[str, str], node: Optional[str], *, install: bool) -> dict[str, str]:
    """The children's environment: the keys every setup step passes, the checked node first on PATH, the browser cache setting."""
    env = dict(setup_hardening.install_env(environ) if install else setup_hardening.probe_env(environ))
    if node:
        env["PATH"] = os.pathsep.join(part for part in (os.path.dirname(node), env.get("PATH", "")) if part)
    if environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        env["PLAYWRIGHT_BROWSERS_PATH"] = environ["PLAYWRIGHT_BROWSERS_PATH"]
    return env


def _state(code: Optional[int]) -> str:
    return "did not start or ran out of time" if code is None else f"exit {code}"


def _tail(text: str) -> str:
    return " ".join(text.split())[-300:]


def browser_location(text: str) -> Optional[tuple[str, str, str]]:
    """(label, build, folder) of the Chromium build that `playwright install --dry-run chromium` names; None when it names none."""
    for header in _HEADER.finditer(text):
        location = _LOCATION.search(text, header.end())
        if location:
            return header.group("label"), header.group("build"), location.group("path")
    return None


# --- probing ---------------------------------------------------------------------------------------------------------


def _node(which: Which, run: Run) -> tuple[Check, Optional[str]]:
    """The checked node and its path (None when it is not usable)."""
    path = which("node")
    if path is None:
        return Check(NODE, "missing", True, None, None, str(MIN_NODE), NODE_FIX, ""), None
    code, text = run([path, "--version"], PROBE_S)
    match = _NODE_VERSION.match(text or "") if code == 0 else None
    if match is None:
        return Check(NODE, "missing", True, None, None, str(MIN_NODE), NODE_FIX, ""), None
    version = ".".join(part for part in match.groups() if part is not None)
    if int(match.group(1)) < MIN_NODE:
        return Check(NODE, "outdated", True, path, version, str(MIN_NODE), NODE_FIX, ""), None
    return Check(NODE, "ok", True, path, version, str(MIN_NODE), "", ""), path


def _pinned_version(project: Path) -> Optional[str]:
    try:
        manifest = json.loads((project / "node_modules" / "@playwright" / "test" / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = manifest.get("version") if isinstance(manifest, dict) else None
    return version if isinstance(version, str) else None


def _playwright(project: Path, node_ok: bool) -> Check:
    fix = SETUP_FIX if node_ok else NODE_FIX
    version = _pinned_version(project)
    if version is None:
        return Check(PLAYWRIGHT, "missing", True, None, None, PLAYWRIGHT_VERSION, fix, "user")
    if version != PLAYWRIGHT_VERSION:
        return Check(PLAYWRIGHT, "outdated", True, str(project), version, PLAYWRIGHT_VERSION, fix, "user")
    if not _bin(project).is_file():
        return Check(PLAYWRIGHT, "missing", True, None, version, PLAYWRIGHT_VERSION, fix, "user")
    return Check(PLAYWRIGHT, "ok", True, str(project), version, PLAYWRIGHT_VERSION, "", "user")


def _chromium(project: Path, node_path: Optional[str], environ: Mapping[str, str], run: Run) -> Check:
    if node_path is None or not _bin(project).is_file():
        return Check(CHROMIUM, "missing", True, None, None, None, NODE_FIX if node_path is None else SETUP_FIX, "user")
    code, text = run([_bin(project), "install", "--dry-run", "chromium"], PROBE_S, cwd=project,
                     env=_env(environ, node_path, install=False))
    found = browser_location(text or "") if code == 0 else None
    if found is None:
        return Check(CHROMIUM, "missing", True, None, None, None, SETUP_FIX, "user")
    label, build, where = found
    version = f"{label}, build {build}"
    if (Path(where) / MARKER).is_file():
        return Check(CHROMIUM, "ok", True, where, version, None, "", "user")
    return Check(CHROMIUM, "missing", True, where, version, None, SETUP_FIX, "user")


def check_all(state_dir: Path, *, environ: Mapping[str, str], which: Which, run: Run) -> list[Check]:
    """node, the pinned @playwright/test and the Chromium build it drives. Looks only: nothing is installed or started."""
    node, node_path = _node(which, run)
    project = folder(state_dir)
    return [node, _playwright(project, node.status == "ok"), _chromium(project, node_path, environ, run)]


# --- installing ------------------------------------------------------------------------------------------------------


def _write_manifest(project: Path) -> None:
    manifest = {"name": "simplicio-evidence-tools", "private": True,
                "description": "Playwright test runner of the delivery evidence (web_verify, video_evidence). Managed by simplicio-loop setup.",
                "dependencies": {"@playwright/test": PLAYWRIGHT_VERSION}}
    (project / "package.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _install_package(project: Path, npm: Optional[str], env: Mapping[str, str], run: Run, dry_run: bool) -> Action:
    if dry_run:
        return Action(PLAYWRIGHT, "would-install", f"@playwright/test {PLAYWRIGHT_VERSION} in {project}")
    if npm is None:
        return Action(PLAYWRIGHT, "failed", "npm is not on the PATH setup trusts (it comes with Node.js)")
    try:
        project.mkdir(parents=True, exist_ok=True)
        _write_manifest(project)
    except OSError as exc:
        return Action(PLAYWRIGHT, "failed", f"cannot write {project}: {exc.strerror or exc}")
    code, text = run([npm, "install", "--no-audit", "--no-fund", "--loglevel=error"], INSTALL_S, cwd=project, env=env)
    if code != 0:
        return Action(PLAYWRIGHT, "failed", f"`npm install` in {project} did not finish ({_state(code)}): {_tail(text)}")
    return Action(PLAYWRIGHT, "installed", f"@playwright/test {PLAYWRIGHT_VERSION} in {project}")


def _install_browser(project: Path, env: Mapping[str, str], run: Run, dry_run: bool) -> Action:
    if dry_run:
        return Action(CHROMIUM, "would-install", f"the Chromium build of @playwright/test {PLAYWRIGHT_VERSION}")
    code, text = run([_bin(project), "install", "chromium"], INSTALL_S, cwd=project, env=env)
    if code != 0:
        return Action(CHROMIUM, "failed", f"`playwright install chromium` did not finish ({_state(code)}): {_tail(text)}")
    return Action(CHROMIUM, "installed", f"the Chromium build of @playwright/test {PLAYWRIGHT_VERSION}")


def install_missing(state_dir: Path, checks: Sequence[Check], *, environ: Mapping[str, str], which: Which, run: Run,
                    dry_run: bool) -> list[Action]:
    """Install what the checks found missing, in order: the pinned package, then its browser. Node.js is never installed."""
    by_name = {check.name: check for check in checks}
    node = by_name[NODE]
    if node.status != "ok":
        return [Action(NODE, "skipped", NODE_FIX)] + [
            Action(name, "skipped", f"needs Node.js {MIN_NODE} or newer") for name in (PLAYWRIGHT, CHROMIUM) if by_name[name].status != "ok"]
    project = folder(state_dir)
    env = _env(environ, node.path, install=True)
    actions: list[Action] = []
    ready = True
    if by_name[PLAYWRIGHT].status != "ok":
        actions.append(_install_package(project, which("npm"), env, run, dry_run))
        ready = actions[-1].result in ("installed", "would-install")
    if by_name[CHROMIUM].status != "ok":
        if ready:
            actions.append(_install_browser(project, env, run, dry_run))
        else:
            actions.append(Action(CHROMIUM, "skipped", f"{PLAYWRIGHT} is not ready, so its browser is not installed"))
    return actions


# --- proving ---------------------------------------------------------------------------------------------------------


def prove(state_dir: Path, *, environ: Mapping[str, str], run: Run, node_path: Optional[str]) -> Action:
    """A real run: a local page is opened, a screenshot is taken and a short clip is recorded. Nothing of it is kept."""
    project = folder(state_dir)
    work: Optional[Path] = None
    try:
        work = Path(tempfile.mkdtemp(prefix="check-", dir=project))  # inside the project: its @playwright/test resolves
        (work / "page.html").write_text(PAGE, encoding="utf-8")
        spec = work / "evidence_check.spec.js"
        spec.write_text(SPEC, encoding="utf-8")
        out = work / "out"
        code, text = run([_bin(project), "test", spec, "--output", out, "--reporter", "line", "--workers", "1"], PROOF_S,
                         cwd=project, env=_env(environ, node_path, install=False))
        shot, clips = work / "shot.png", sorted(out.rglob("*.webm"))
        if code != 0:
            return Action(CHECK, "failed", f"the browser check did not pass ({_state(code)}): {_tail(text)}")
        if not (shot.is_file() and shot.read_bytes()[:8] == PNG_SIGNATURE):
            return Action(CHECK, "failed", "the browser check passed but no screenshot was taken")
        if not clips or clips[0].stat().st_size == 0:
            return Action(CHECK, "failed", "the browser check passed but no clip was recorded")
        return Action(CHECK, "validated", f"screenshot {shot.stat().st_size} bytes, clip {clips[0].stat().st_size} bytes")
    except OSError as exc:
        return Action(CHECK, "failed", f"could not run the browser check: {exc.strerror or exc}")
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)


# --- the steps -------------------------------------------------------------------------------------------------------


def step(state_dir: Path, *, environ: Mapping[str, str], which: Which, run: Run, dry_run: bool,
         validate: bool) -> tuple[list[Check], list[Action]]:
    """Probe, install what is missing, and prove the tools when `validate` is set or something was installed.

    `dry_run` plans only: it installs nothing and starts no browser. A tool that is still not ok is a required check
    that is not ok, so the caller reports it and does not call the install complete."""
    checks = check_all(state_dir, environ=environ, which=which, run=run)
    actions = install_missing(state_dir, checks, environ=environ, which=which, run=run, dry_run=dry_run)
    installed = any(action.result == "installed" for action in actions)
    if dry_run or not (validate or installed):
        return checks, actions
    checks = check_all(state_dir, environ=environ, which=which, run=run)  # what is on the machine after the installs
    if any(check.status != "ok" for check in checks):
        return checks, actions
    proof = prove(state_dir, environ=environ, run=run, node_path=checks[0].path)
    passed = proof.result == "validated"
    checks = [*checks, Check(CHECK, "ok" if passed else "failed", True, None, proof.detail if passed else None, None,
                             "" if passed else SETUP_FIX, "")]
    return checks, [*actions, proof]


def _summary(check: Check) -> str:
    if check.name == NODE:
        if check.version:
            return f"node {check.version} at {check.path} (needs {MIN_NODE} or newer)"
        return f"Node.js is not available (the evidence tools need {MIN_NODE} or newer)"
    if check.name == PLAYWRIGHT:
        if check.status == "ok":
            return f"@playwright/test {check.version} in {check.path} (the test runner of web_verify and video_evidence)"
        if check.version:
            return f"@playwright/test {check.version} is not the pinned {PLAYWRIGHT_VERSION} or is incomplete"
        return f"@playwright/test is not installed (pinned {PLAYWRIGHT_VERSION})"
    if check.status == "ok":
        return f"{check.version} at {check.path}"  # e.g. "Chrome for Testing 156.0.8078.4, build 1248 at <cache>/chromium-1248"
    return f"Chromium is not installed for @playwright/test {PLAYWRIGHT_VERSION}"


def probe_rows(state_dir: Path, *, environ: Mapping[str, str], which: Optional[Which] = None,
               run: Optional[Run] = None) -> list[dict]:
    """The `doctor` rows: ok with the version and the place, or warn with the exact fix. Nothing is installed or started."""
    checks = check_all(state_dir, environ=environ, which=which or setup_hardening.safe_which(environ), run=run or execute)
    rows = []
    for check in checks:
        ok = check.status == "ok"
        rows.append({"name": check.name, "status": "ok" if ok else "warn", "summary": _summary(check),
                     "fix": None if ok else check.fix or None,
                     "detail": {"state": check.status, "version": check.version, "path": check.path}})
    return rows
