#!/usr/bin/env python3
"""simplicio-loop — web_verify worker (front-end proof via Playwright).

The runnable form of the `web_verify` extension point documented in
`.claude/skills/simplicio-loop/references/web-evidence.md`. Drives a real headless browser to
PROVE a front-end change renders, and captures a **screenshot + trace** as evidence. Evidence is
ALWAYS a file path + a boolean verdict — never DOM, pixels, or page HTML (token economy).

Three verbs:

  detect   Cheap FE-diff gate (terminal, no browser). Lists changed front-end files vs a base
           ref. Exit 0 + "skip" when none changed; exit 0 + "fe-changed" when the gate should
           fire. Pass --exit-code to instead exit 10 when FE changed (for CI `if:` gating).
  run      Drive headless Chromium to a URL, assert --expect text is present, write a
           screenshot + trace + console scan under the evidence dir, append a ledger row, and
           print the one-line MACHINE-tier verdict. Two runnable backends via --runner:
             playwright (default) the spec runs on the installed Playwright of the loop's evidence
                                  tools (`simplicio-loop setup`, simplicio_loop/evidence_tools.py), never `npx`
             pytest  this Python's `pytest` (`python -m pytest`) + playwright-python — Fallback B (Python repos)
           A missing tool is BLOCKED with its fix; a failed check is FAIL with Playwright's own output.
           playwright-mcp is the richer path when a worker has the MCP server registered.
  verify   detect, then run only if the diff is front-end; otherwise record a SKIP ledger note.
           This is the gate the quality loop (Step 4b) calls.

CI artifact upload (the second half of issue #10):
  - GitHub Actions:  .github/workflows/web-verify.yml uploads `.simplicio-loop/orchestrator/tee/web` via
    actions/upload-artifact (gated on a front-end path filter; manual run via workflow_dispatch).
  - locally / ad-hoc: `run --upload --pr <N>` runs `gh release upload` + `gh pr comment` with the
    artifact URLs (links, never bytes). See web-evidence.md "Attach to the PR".

Usage:
    python3 scripts/web_verify.py detect [--base origin/main] [--exit-code]
    python3 scripts/web_verify.py run --url http://localhost:3000/login \\
        --expect "Sign in" [--runner playwright|pytest] [--out DIR] [--issue 10] [--upload --pr N]
    python3 scripts/web_verify.py verify --url URL --expect TEXT [--base REF] [--issue N]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:  # Windows consoles default to cp1252 and choke on non-ASCII — force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get("SIMPLICIO_REPO") or os.path.dirname(HERE))  # the repo a run acts on
DEFAULT_OUT = os.path.join(REPO, ".simplicio-loop/orchestrator", "tee", "web")
# same matcher as web-evidence.md "When it fires"
FE_RE = re.compile(r"\.(tsx|jsx|vue|svelte|css|scss|html)$|^(components|pages|app|public|src/ui)/", re.I)

if HERE not in sys.path:
    sys.path.insert(0, HERE)


def log(msg):
    print("  " + msg)


def _emit_progress(status, outcome=None, detail=""):
    """Fail-open progress-feedback hook (#301) — never raises, never blocks web_verify."""
    try:
        import loop_progress
        loop_progress.emit_event("evidence", status=status, outcome=outcome, detail=detail,
                                 source="web_verify.py")
    except Exception:
        pass


def _exe(name):
    """Resolve an executable on PATH (finds npx.cmd/git.cmd on Windows); fall back to the name."""
    return shutil.which(name) or name


def _run(argv, **kw):
    """Run a command WITHOUT a shell. Returns the CompletedProcess, or None if the exe is absent."""
    try:
        return subprocess.run([_exe(argv[0])] + argv[1:], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", **kw)
    except FileNotFoundError:
        return None


def fe_changed_files(base):
    """Front-end files changed vs `base` (terminal, not LLM). [] means SKIP the gate."""
    r = _run(["git", "-C", REPO, "diff", "--name-only", "%s...HEAD" % base])
    if r is None:
        log("! git not found on PATH")
        return []
    if r.returncode != 0:
        # base ref not found (shallow clone / detached) — fall back to last commit
        r = _run(["git", "-C", REPO, "diff", "--name-only", "HEAD~1...HEAD"])
    files = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    return [f for f in files if FE_RE.search(f)]


def cmd_detect(opts):
    base = opts.get("base", "origin/main")
    fe = fe_changed_files(base)
    if fe:
        print("fe-changed: %d file(s)" % len(fe))
        for f in fe[:20]:
            log(f)
        if opts.get("exit-code"):
            sys.exit(10)
    else:
        print("skip: no front-end files changed vs %s" % base)


# the spec of the default runner: one page, the expected text, a screenshot and the console errors. It runs on the installed
# Playwright (evidence_tools) and its values are JSON literals, so no URL, path or text can break the JavaScript.
PLAYWRIGHT_SPEC = r"""
const {{ test, expect }} = require('@playwright/test');
test('web_verify', async ({{ page }}) => {{
  const errors = [];
  page.on('console', m => {{ if (m.type() === 'error') errors.push(m.text()); }});
  await page.goto({url}, {{ waitUntil: 'load', timeout: 30000 }});
  {expect_line}
  await page.screenshot({{ path: {shot}, fullPage: true }});
  require('fs').writeFileSync({errlog}, JSON.stringify(errors, null, 2));
  expect(errors, 'console errors: ' + JSON.stringify(errors)).toHaveLength(0);
}});
"""

# self-contained playwright-python test (Fallback B, pytest) — traces programmatically
PY_SPEC = r"""
import json
from playwright.sync_api import sync_playwright
def test_web_verify():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.tracing.start(screenshots=True, snapshots=True)
        page = ctx.new_page()
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.goto({url!r}, wait_until='load', timeout=30000)
        {expect_line}
        page.screenshot(path={shot!r}, full_page=True)
        ctx.tracing.stop(path={trace_zip!r})
        browser.close()
    with open({errlog!r}, 'w') as f:
        json.dump(errors, f)
    assert not errors, 'console errors: %s' % errors
"""


def _append_ledger(out, line):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "ledger.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _blocked(out, msg):
    _append_ledger(out, "web_verify: BLOCKED — " + msg)
    print("blocked")
    log(msg)
    _emit_progress("blocked", outcome="blocked", detail=msg[:400])
    sys.exit(3)


def cmd_run(opts):
    if "url" not in opts:
        print("run requires --url")
        sys.exit(2)
    url = opts["url"]
    _emit_progress("begin", detail="web_verify: %s" % url)
    expect = opts.get("expect", "")
    issue = str(opts.get("issue", "x"))
    out = os.path.abspath(opts.get("out", DEFAULT_OUT))  # the spec writes these paths: they must not depend on a cwd
    runner = opts.get("runner", "playwright")
    os.makedirs(out, exist_ok=True)
    shot = os.path.join(out, "%s-web.png" % issue)
    trace_dir = os.path.join(out, "trace-%s" % issue)
    trace_zip = os.path.join(out, "%s-trace.zip" % issue)
    errlog = os.path.join(out, "%s-console.json" % issue)

    if runner == "pytest":
        ok, trace_ref, failure = _run_pytest(url, expect, shot, trace_zip, errlog, out)
    else:
        ok, trace_ref, failure = _run_playwright(url, expect, shot, errlog, trace_dir, out)
    verdict = "web_verify: %s — %s (expect=%r, runner=%s) shot=%s trace=%s" % (
        "PASS" if ok else "FAIL", url, expect, runner, shot, trace_ref)
    if failure:
        verdict += " — " + failure
    _append_ledger(out, verdict)
    print("done" if ok else "fail")
    log(verdict)
    _emit_progress("end", outcome=("pass" if ok else "fail"),
                  detail="%s, screenshots em %s" % (verdict, out))
    if opts.get("upload") and opts.get("pr"):
        _upload(out, str(opts["pr"]), shot, trace_ref)
    sys.exit(0 if ok else 1)


def _run_playwright(url, expect, shot, errlog, trace_dir, out):
    """The default runner: the spec on the installed Playwright (evidence_tools), with a trace. Returns (ok, trace ref, failure)."""
    expect_line = ("await expect(page.getByText(%s, {exact: false}).first())"
                   ".toBeVisible({timeout: 15000});" % json.dumps(expect)) if expect else ""
    spec = PLAYWRIGHT_SPEC.format(url=json.dumps(url), expect_line=expect_line, shot=json.dumps(shot),
                                  errlog=json.dumps(errlog))
    run = _playwright(spec, {"outputDir": trace_dir, "use": {"trace": "on"}}, out)
    return run.code == 0, trace_dir, "" if run.code == 0 else run.failure


def _playwright(spec, config, out):
    """Run the spec on the installed Playwright: the SpecRun, or BLOCKED with the missing piece and its fix."""
    try:
        from simplicio_loop import evidence_tools
        from simplicio_loop.self_update import default_state_dir
    except ImportError as exc:
        _blocked(out, "simplicio_loop is not importable (%s): run this worker with the loop's own python" % exc)
    run = evidence_tools.run_spec(default_state_dir(), spec=spec, config=config, environ=os.environ)
    if run.blocked is not None:
        _blocked(out, run.blocked)
    if run.code is None:
        _blocked(out, "Playwright did not start or ran out of time")
    return run


def _run_pytest(url, expect, shot, trace_zip, errlog, out):
    """The Fallback B runner (playwright-python under pytest). The spec runs in a fresh folder of the system temp dir, removed
    when the run is over, under this Python's own pytest (`python -m pytest`, not whatever `pytest` the PATH finds). Returns
    (ok, trace ref, failure): the failure is the end of pytest's output, on one line."""
    expect_line = ("page.get_by_text(%r).first.wait_for(timeout=15000)" % expect) if expect else "pass"
    spec = PY_SPEC.format(url=url, expect_line=expect_line, shot=shot, trace_zip=trace_zip, errlog=errlog)
    run_dir = tempfile.mkdtemp(prefix="web-verify-pytest-")
    try:
        spec_path = os.path.join(run_dir, "test_web_verify.py")
        with open(spec_path, "w", encoding="utf-8") as f:
            f.write(spec)
        cmd = [sys.executable, "-m", "pytest", spec_path, "-q", "-p", "no:cacheprovider"]
        log("running (pytest): %s" % " ".join(cmd))
        r = _run(cmd, cwd=run_dir)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    if r is None:
        _blocked(out, "pytest did not start (%s)" % sys.executable)
    output = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 and "no module named pytest" in output.lower():
        _blocked(out, "pytest is not installed for this Python (%s): `pip install pytest pytest-playwright`" % sys.executable)
    if r.returncode != 0 and "no module named 'playwright'" in output.lower():
        _blocked(out, "Playwright for Python is not installed for this Python (%s): "
                      "`pip install pytest-playwright && playwright install`" % sys.executable)
    if r.returncode == 0:
        return True, trace_zip, ""
    return False, trace_zip, " ".join(output.split())[-600:]


def _upload(out, pr, shot, trace_ref):
    """Attach evidence to the PR as LINKS (web-evidence.md). Best-effort; logs the gh calls."""
    tag = "evidence-pr%s" % pr
    rel = _run(["gh", "release", "create", tag, "--notes", "web_verify evidence", shot], cwd=REPO)
    if rel is None:
        log("! gh not found — skipping upload (artifacts remain at %s)" % out)
        return
    if rel.returncode != 0:  # release may already exist — upload into it
        _run(["gh", "release", "upload", tag, shot, "--clobber"], cwd=REPO)
    body = ("web_verify ✅  screenshot + trace attached to release `%s` "
            "(open trace in trace.playwright.dev)" % tag)
    _run(["gh", "pr", "comment", pr, "--body", body], cwd=REPO)
    log("uploaded evidence -> release %s, commented on PR #%s" % (tag, pr))


def cmd_verify(opts):
    base = opts.get("base", "origin/main")
    out = opts.get("out", DEFAULT_OUT)
    fe = fe_changed_files(base)
    if not fe:
        _append_ledger(out, "web_verify: SKIP — no front-end files changed vs %s" % base)
        print("skip")
        log("no front-end diff — gate skipped (PASS by exemption)")
        return
    log("front-end diff detected (%d files) — running web_verify" % len(fe))
    cmd_run(opts)


def _parse(args):
    opts = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                opts[key] = args[i + 1]
                i += 2
            else:
                opts[key] = True
                i += 1
        else:
            i += 1
    return opts


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(2)
    if argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    sub, opts = argv[0], _parse(argv[1:])
    {"detect": cmd_detect, "run": cmd_run, "verify": cmd_verify}.get(
        sub, lambda _o: (print("unknown command '%s'. choices: detect run verify" % sub),
                         sys.exit(2)))(opts)


if __name__ == "__main__":
    main()
