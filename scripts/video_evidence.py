#!/usr/bin/env python3
"""simplicio-tasks / simplicio-loop — video_evidence worker (demo-video proof, two engines).

The runnable form of the `video_evidence` extension point documented in
`.claude/skills/simplicio-tasks/references/video-evidence.md`. Produces a demo video of a
screen/feature and records it as evidence a change works. Evidence is ALWAYS a file path + a boolean
verdict — never the video bytes, frames, or HTML are fed back into the model context (token economy).

TWO engines, one producer:
  • **playwright** (DEFAULT — the normal evidence flow): records the REAL browser session driving
    the screen to a video (`.webm`, → `.mp4` when FFmpeg is present). This is the "works, not just
    compiles" proof for any UI change (Step 4b).
  • **hyperframes** (an EXPLICIT custom request only — "make an explainer video of screen X"):
    renders a deterministic, captioned slideshow of the captured screenshots to MP4
    (https://github.com/heygen-com/hyperframes) — "same input, same frames, same output", CI-reproducible.

Either engine: a missing toolchain yields BLOCKED, never a fake pass.

Verbs:

  detect    Cheap intent gate (no toolchain). Decide whether a goal/work-item is an explicit
            video-creation request (e.g. `/simplicio-tasks make an explainer video of screen X`) —
            those route to the hyperframes engine. Exit 0 + "video-task" / "skip"; --exit-code → 10.
  record    engine=playwright: drive --url with Playwright recording on → a real session video. The session
            runs on the installed Playwright of the loop's evidence tools (simplicio_loop/evidence_tools.py,
            `simplicio-loop setup`), never `npx`. BLOCKED when that tool is not ready (naming the fix); FAIL with
            Playwright's own output when the session fails or records nothing.
  scaffold  engine=hyperframes: turn captured screenshots (--frames DIR / --shots a.png,b.png) into
            a hyperframes composition.
  render    engine=hyperframes: `hyperframes render` (the pinned explainer of the evidence tools) the composition to MP4.
  lint      engine=hyperframes: `hyperframes lint` — validate the composition before rendering.
  verify    The gate Step 4b / the loop's evidence gate calls. DEFAULT → `record` (playwright);
            `--engine hyperframes` → scaffold (if needed) + render. Appends a ledger row, prints the
            MACHINE-tier verdict (`done|fail|skip|blocked`).

Pairs with web_verify.py: web_verify asserts the UI renders + captures screenshots; video_evidence
records the moving proof (playwright) or assembles the captioned explainer (hyperframes).

Usage:
    python3 scripts/video_evidence.py detect --goal "make an explainer video of the login screen" [--exit-code]
    # normal evidence flow (default = playwright):
    python3 scripts/video_evidence.py verify --url http://localhost:3000/login \\
        --name login-demo --expect "Sign in" [--seconds 4] [--issue 12] [--upload --pr N]
    # explicit custom explainer (hyperframes):
    python3 scripts/video_evidence.py verify --engine hyperframes --name login-demo \\
        --frames .simplicio-loop/orchestrator/tee/web --title "Login screen" [--seconds 2.0] [--issue 12]
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

try:  # Windows consoles default to cp1252 and choke on non-ASCII — force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(REPO, ".simplicio-loop/orchestrator", "tee", "video")
# Multilingual intent matcher for "create a demonstration video of screen/feature X".
# Matches a video noun near a make/show/demo verb (EN/PT/ES). Deliberately broad but anchored
# on an explicit video noun so a normal code task never trips it.
VIDEO_NOUN = r"v[ií]deo|video|screencast|screen[- ]?recording|walkthrough|demo\s+reel|gif"
VIDEO_VERB = (r"fa[çc]a|fazer|crie|criar|gere|gerar|grav[ae]r?|demonstr|"
              r"make|create|record|generate|produce|show|capture|demo")
VIDEO_RE = re.compile(r"(?=.*(%s))(?=.*(%s))" % (VIDEO_NOUN, VIDEO_VERB), re.I | re.S)


if HERE not in sys.path:
    sys.path.insert(0, HERE)


def log(msg):
    print("  " + msg)


def _emit_progress(status, outcome=None, detail=""):
    """Fail-open progress-feedback hook (#301) — never raises, never blocks video_evidence."""
    try:
        import loop_progress
        loop_progress.emit_event("evidence", status=status, outcome=outcome, detail=detail,
                                 source="video_evidence.py")
    except Exception:
        pass


def _exe(name):
    """Resolve an executable on PATH (finds npx.cmd/ffmpeg.exe on Windows); fall back to the name."""
    return shutil.which(name) or name


def _run(argv, **kw):
    """Run a command WITHOUT a shell. Returns the CompletedProcess, or None if the exe is absent."""
    try:
        return subprocess.run([_exe(argv[0])] + argv[1:], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", **kw)
    except FileNotFoundError:
        return None


FFMPEG_CHECK_S = 15  # `ffmpeg -version` answers at once, and a binary whose libraries do not load fails at once too


def _tail(text, limit=400):
    """The end of a command's output on one line: what says why it failed."""
    return " ".join((text or "").split())[-limit:]


def _ffmpeg():
    """The FFmpeg to run, as (path, None), or (None, what is wrong and its fix).

    HYPERFRAMES_FFMPEG_PATH names it when set, else the one on PATH. `shutil.which` only finds a file: a Homebrew ffmpeg whose
    libvpx is broken is found and does not run, so it is checked with `-version` before anything uses it."""
    exe = os.environ.get("HYPERFRAMES_FFMPEG_PATH") or shutil.which("ffmpeg")
    if exe is None:
        return None, "FFmpeg not found: install it (`brew install ffmpeg`) or set HYPERFRAMES_FFMPEG_PATH to a working ffmpeg"
    fix = "fix: `brew reinstall ffmpeg`, or set HYPERFRAMES_FFMPEG_PATH to a working ffmpeg"
    try:
        done = _run([exe, "-version"], timeout=FFMPEG_CHECK_S)
    except subprocess.TimeoutExpired:
        return None, f"FFmpeg at {exe} did not answer `-version` within {FFMPEG_CHECK_S} s; {fix}"
    if done is None:
        return None, f"FFmpeg at {exe} does not start; {fix}"
    if done.returncode != 0:
        return None, f"FFmpeg at {exe} does not run (`-version` exit {done.returncode}: {_tail(done.stderr or done.stdout)}); {fix}"
    return exe, None


def is_video_request(text):
    """True when the goal/work-item text asks for a demonstration video (terminal, not LLM)."""
    return bool(text) and bool(VIDEO_RE.search(text))


def cmd_detect(opts):
    goal = opts.get("goal", "") or os.environ.get("SIMPLICIO_GOAL", "")
    if is_video_request(goal):
        print("video-task: hyperframes demo-video request detected")
        log("goal matched the video-evidence intent — route to the video_evidence producer")
        if opts.get("exit-code"):
            sys.exit(10)
    else:
        print("skip: not a video-creation request")


def _proj_dir(name, out):
    return os.path.join(out, name)


def _node_major():
    r = _run(["node", "--version"])
    if r is None or r.returncode != 0:
        return None
    m = re.search(r"v(\d+)\.", r.stdout or "")
    return int(m.group(1)) if m else None


def _collect_shots(opts):
    """Resolve the ordered list of screenshot PNGs to assemble into the demo."""
    shots = []
    if opts.get("shots"):
        shots = [s.strip() for s in str(opts["shots"]).split(",") if s.strip()]
    elif opts.get("frames"):
        frames = opts["frames"]
        if not os.path.isabs(frames):
            frames = os.path.join(REPO, frames)
        shots = sorted(glob.glob(os.path.join(frames, "*.png")))
    return [s for s in shots if os.path.exists(s)]


# hyperframes composition (schema v0.7.x): the project's `index.html` carries a `#root` wrapper
# with `data-composition-id` + `data-duration`/`data-width`/`data-height`; each screenshot is one
# timed `.clip` (the framework gates a clip's visibility by its `data-start`/`data-duration`
# window), and a paused GSAP timeline registered on `window.__timelines[<id>]` fades each scene in.
# Deterministic: no Date.now()/Math.random()/runtime fetches (GSAP is a static CDN <script>).
COMPOSITION = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width={width}, height={height}" />
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ width: {width}px; height: {height}px; overflow: hidden; background: #0b0f17; }}
    body {{ font-family: "Inter", system-ui, Segoe UI, Roboto, sans-serif; color: #e6edf3; }}
    .clip {{ position: absolute; inset: 0; display: flex; flex-direction: column;
             align-items: center; justify-content: center; gap: 22px; }}
    .clip img {{ max-width: 90%; max-height: 78%; border-radius: 12px;
                 box-shadow: 0 16px 50px rgba(0,0,0,.55); border: 1px solid #1f2733; }}
    .cap {{ font-size: 27px; font-weight: 600; letter-spacing: .2px;
            padding: 0 48px; text-align: center; }}
    .brand {{ position: absolute; left: 26px; bottom: 18px; font-size: 14px; opacity: .5; }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-duration="{duration}"
       data-width="{width}" data-height="{height}">
{clips}
    <div class="brand">{brand}</div>
  </div>
  <script>
    window.__timelines = window.__timelines || {{}};
    const tl = gsap.timeline({{ paused: true }});
{fades}
    window.__timelines["main"] = tl;
  </script>
</body>
</html>
"""

CLIP = ('      <div class="clip" id="s{n}" data-start="{start}" data-duration="{dur}" '
        'data-track-index="1">\n'
        '        <img src="assets/{asset}" alt="{alt}" />\n'
        '        <div class="cap">{cap}</div>\n'
        '      </div>')

FADE = '    tl.from("#s{n}", {{ opacity: 0, duration: 0.4 }}, {start});'


def cmd_scaffold(opts):
    name = opts.get("name", "simplicio-demo")
    out = opts.get("out", DEFAULT_OUT)
    title = opts.get("title", "Demo")
    seconds = float(opts.get("seconds", 2.0))
    os.makedirs(out, exist_ok=True)
    proj = _proj_dir(name, out)

    shots = _collect_shots(opts)
    if not shots:
        log("! no screenshots found (--frames DIR / --shots a.png,b.png). Run web_verify first "
            "to capture per-step shots into .simplicio-loop/orchestrator/tee/web/.")
        sys.exit(2)

    hf = _hyperframes(out)  # BLOCKED, with the fix, when the pinned explainer is not installed
    # `hyperframes init` scaffolds the project skeleton; best-effort (we still write our own
    # index.html + assets below, so the worker is useful even if init is unavailable). The pinned init refuses a
    # non-interactive run without an example, and checks AI skills on GitHub unless HYPERFRAMES_SKIP_SKILLS is set.
    if not os.path.isdir(proj):
        r = _run([hf, "init", name, "--non-interactive", "--example", "blank", "--skip-transcribe"], cwd=out,
                 env={**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1"})
        if r is None:
            log("! hyperframes did not start — the composition is written without the project skeleton")
    assets = os.path.join(proj, "assets")
    os.makedirs(assets, exist_ok=True)

    # hyperframes renders the project over a local file server, so every asset MUST live inside
    # the project tree (a ../.. path back to the capture dir would not resolve). Copy each shot
    # into assets/ in capture order; each becomes one timed .clip in the index.html timeline.
    clips, fades, start = [], [], 0.0
    for i, s in enumerate(shots, 1):
        asset = "frame%02d.png" % i
        shutil.copy2(s, os.path.join(assets, asset))
        cap = _pretty_cap(title, s)
        clips.append(CLIP.format(n=i, start=_fmt(start), dur=_fmt(seconds), asset=asset,
                                 alt=_esc(os.path.splitext(asset)[0]), cap=_esc(cap)))
        fades.append(FADE.format(n=i, start=_fmt(start)))
        start = round(start + seconds, 3)
    width = int(opts.get("width", 1280))
    height = int(opts.get("height", 720))
    brand = opts.get("brand", "github.com/simpletibr/simplicio-loop")
    html = COMPOSITION.format(width=width, height=height, duration=_fmt(start),
                              clips="\n".join(clips), fades="\n".join(fades), brand=_esc(brand))
    comp_path = os.path.join(proj, "index.html")
    with open(comp_path, "w", encoding="utf-8") as f:
        f.write(html)
    log("scaffolded %d-scene composition (%.1fs) -> %s" % (len(shots), start, comp_path))
    print("scaffolded")


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _fmt(x):
    """Seconds → compact HTML attr value (2.0 -> '2', 12.0 -> '12', 2.5 -> '2.5')."""
    return "%g" % float(x)


def _pretty_cap(title, path):
    """Caption from the shot filename: drop the ordering prefix, humanize, keep ACRONYMS."""
    base = os.path.splitext(os.path.basename(path))[0]
    base = re.sub(r"^\d+[-_.]+", "", base)            # strip a leading "03-" ordering prefix
    label = re.sub(r"[-_]+", " ", base).strip()
    label = " ".join(w if w.isupper() else w.capitalize() for w in label.split())
    return ("%s · %s" % (title, label)) if (title and label) else (label or title)


def _append_ledger(out, line):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "ledger.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _blocked(out, msg):
    _append_ledger(out, "video_evidence: BLOCKED — " + msg)
    print("blocked")
    log(msg)
    _emit_progress("blocked", outcome="blocked", detail=msg[:400])
    sys.exit(3)


def _hyperframes(out):
    """The pinned hyperframes binary of the evidence tools (simplicio_loop/evidence_tools.py): its path, or BLOCKED with the fix.
    Never `npx`: that fetches whatever version is current, and a sandboxed run has no writable npm cache."""
    try:
        from simplicio_loop import evidence_tools
        from simplicio_loop.self_update import default_state_dir
    except ImportError as exc:
        _blocked(out, "simplicio_loop is not importable (%s): run this worker with the loop's own python" % exc)
    state = default_state_dir()
    blocked = evidence_tools.hyperframes_block(state)
    if blocked is not None:
        _blocked(out, blocked)
    return str(evidence_tools.hyperframes_bin(state))


def cmd_lint(opts):
    name = opts.get("name", "simplicio-demo")
    out = opts.get("out", DEFAULT_OUT)
    proj = _proj_dir(name, out)
    r = _run([_hyperframes(out), "lint"], cwd=proj)
    if r is None:
        _blocked(out, "hyperframes did not start")
    ok = r.returncode == 0
    print("done" if ok else "fail")
    log((r.stdout or r.stderr or "").strip()[:400])
    sys.exit(0 if ok else 1)


def _render_failure(done):
    """Why `hyperframes render` did not give an MP4: its exit code and the tail of its stderr (its stdout when stderr is empty)."""
    if done.returncode != 0:
        return "hyperframes exited %d: %s" % (done.returncode, _tail(done.stderr or done.stdout) or "no output")
    return "hyperframes exited 0 but wrote no MP4"


def cmd_render(opts):
    name = opts.get("name", "simplicio-demo")
    out = opts.get("out", DEFAULT_OUT)
    issue = str(opts.get("issue", "x"))
    proj = _proj_dir(name, out)
    comp = os.path.join(proj, "index.html")

    # Preflight the toolchain — BLOCK (never fake-pass) when it is missing.
    hf = _hyperframes(out)
    nm = _node_major()
    if nm is not None and nm < 22:
        _blocked(out, "Node %d detected — hyperframes requires Node 22+" % nm)
    _, problem = _ffmpeg()
    if problem:
        _blocked(out, "hyperframes renders MP4 via FFmpeg — " + problem)
    if not os.path.exists(comp):
        _blocked(out, "no composition at %s — run `scaffold` first" % comp)

    mp4 = os.path.join(out, "%s-%s.mp4" % (name, issue))
    fps = str(opts.get("fps", 30))
    quality = str(opts.get("quality", "standard"))
    # hyperframes render takes the PROJECT DIR positionally and renders its index.html.
    cmd = [hf, "render", proj, "-o", mp4, "-f", fps, "-q", quality]
    log("rendering: %s" % " ".join(cmd))
    r = _run(cmd, cwd=proj)
    if r is None:
        _blocked(out, "hyperframes did not start")
    ok = r.returncode == 0 and os.path.exists(mp4)
    verdict = "video_evidence: %s — demo MP4 (hyperframes) project=%s mp4=%s" % (
        "PASS" if ok else "FAIL", name, mp4 if ok else "(not produced)")
    if not ok:
        verdict += " — " + _render_failure(r)
    _append_ledger(out, verdict)
    print("done" if ok else "fail")
    log(verdict)
    if ok and opts.get("upload") and opts.get("pr"):
        _upload(out, str(opts["pr"]), mp4)
    sys.exit(0 if ok else 1)


def _upload(out, pr, mp4, engine="hyperframes"):
    """Attach the demo video to the PR as a LINK (never bytes). Best-effort."""
    tag = "evidence-pr%s" % pr
    rel = _run(["gh", "release", "create", tag, "--notes", "video_evidence demo", mp4], cwd=REPO)
    if rel is None:
        log("! gh not found — skipping upload (video remains at %s)" % mp4)
        return
    if rel.returncode != 0:  # release may already exist — upload into it
        _run(["gh", "release", "upload", tag, mp4, "--clobber"], cwd=REPO)
    how = ("[hyperframes](https://github.com/heygen-com/hyperframes)" if engine == "hyperframes"
           else "Playwright")
    body = ("🎬 video_evidence ✅  demo video produced with %s attached to release `%s`" % (how, tag))
    _run(["gh", "pr", "comment", pr, "--body", body], cwd=REPO)
    log("uploaded demo video -> release %s, commented on PR #%s" % (tag, pr))


# Playwright NATIVE video — records the REAL browser session to a video file. The other engine
# (hyperframes) assembles web_verify screenshots into a deterministic slideshow; this one is a live
# capture of the screen actually driving. The run's config turns `use.video` on: Playwright writes a .webm per page.
# Its values are JSON literals, so no URL or text can break the JavaScript.
PLAYWRIGHT_VIDEO_SPEC = r"""
const {{ test }} = require('@playwright/test');
test('video_evidence', async ({{ page }}) => {{
  await page.goto({url}, {{ waitUntil: 'load', timeout: 30000 }});
  {expect_line}
  await page.waitForTimeout({hold_ms});
}});
"""


def _playwright(spec, config, out):
    """Run the spec on the installed Playwright (evidence_tools): the SpecRun, or BLOCKED with the missing piece and its fix."""
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


def _conversion_failure(done):
    """Why the .webm did not become an .mp4: FFmpeg's exit and the tail of its stderr. The recording stays .webm."""
    if done is None:
        return "mp4 conversion did not run (FFmpeg did not start); the recording stays .webm"
    if done.returncode != 0:
        return "mp4 conversion failed (ffmpeg exit %d: %s); the recording stays .webm" % (
            done.returncode, _tail(done.stderr or done.stdout))
    return "mp4 conversion wrote no file; the recording stays .webm"


def cmd_record(opts):
    """Engine=playwright: drive --url with Playwright recording on -> a real session video.

    BLOCK (never fake-pass) when the installed Playwright is not ready, naming the fix. FAIL when the session fails or
    records nothing, with Playwright's own output. Output is .webm (Playwright-native); converted to .mp4 when FFmpeg is
    present. Evidence = path, never bytes.
    """
    out = os.path.abspath(opts.get("out", DEFAULT_OUT))  # the spec writes this path: it must not depend on a cwd
    name = opts.get("name", "simplicio-demo")
    issue = str(opts.get("issue", "x"))
    url = opts.get("url")
    os.makedirs(out, exist_ok=True)
    _emit_progress("begin", detail="video_evidence: %s (%s)" % (url or "no-url", name))
    if not url:
        _blocked(out, "the playwright engine needs --url (the screen to record) — or use --engine hyperframes")
    width = int(opts.get("width", 1280))
    height = int(opts.get("height", 720))
    hold_ms = int(float(opts.get("seconds", 4.0)) * 1000)
    expect = opts.get("expect", "")
    expect_line = ("await page.getByText(%s, {exact: false}).first().waitFor({timeout: 15000});"
                   % json.dumps(expect)) if expect else ""
    rec_dir = os.path.join(out, "%s-%s-pw" % (name, issue))
    spec = PLAYWRIGHT_VIDEO_SPEC.format(url=json.dumps(url), hold_ms=hold_ms, expect_line=expect_line)
    video = {"mode": "on", "size": {"width": width, "height": height}}  # Playwright writes one .webm per page
    run = _playwright(spec, {"outputDir": rec_dir, "use": {"video": video}}, out)
    webms = sorted(glob.glob(os.path.join(rec_dir, "**", "*.webm"), recursive=True))
    ok = run.code == 0 and bool(webms)  # the session ran clean and Playwright left its recording
    produced = webms[0] if webms else "(not produced)"
    conversion = ""
    if ok:
        ffmpeg, problem = _ffmpeg()
        if ffmpeg is not None:
            mp4 = os.path.join(out, "%s-%s.mp4" % (name, issue))
            cv = _run([ffmpeg, "-y", "-i", produced, mp4])
            if cv is not None and cv.returncode == 0 and os.path.exists(mp4):
                produced = mp4
            else:
                conversion = _conversion_failure(cv)
        else:
            log(problem + " — the recording stays .webm")
    verdict = "video_evidence: %s — demo video (playwright) project=%s file=%s" % (
        "PASS" if ok else "FAIL", name, produced)
    if not ok:
        verdict += " — " + (run.failure if run.code != 0 else "Playwright passed but recorded no video")
    if conversion:
        verdict += " — " + conversion
    _append_ledger(out, verdict)
    print("done" if ok else "fail")
    log(verdict)
    _emit_progress("end", outcome=("pass" if ok else "fail"), detail=verdict)
    if ok and opts.get("upload") and opts.get("pr"):
        _upload(out, str(opts["pr"]), produced, engine="playwright")
    sys.exit(0 if ok else 1)


def cmd_verify(opts):
    # DEFAULT = a live Playwright recording of the screen actually running (the normal evidence
    # flow — "works, not just compiles"). Hyperframes (a deterministic captioned slideshow) is the
    # engine for an EXPLICIT custom request only — "make an explainer video of screen X" — selected
    # with `--engine hyperframes`.
    if opts.get("engine") == "hyperframes":
        out = opts.get("out", DEFAULT_OUT)
        name = opts.get("name", "simplicio-demo")
        proj = _proj_dir(name, out)
        if not os.path.exists(os.path.join(proj, "index.html")):
            cmd_scaffold(opts)  # exits non-zero if no shots are available
        return cmd_render(opts)
    return cmd_record(opts)  # playwright = default evidence flow


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
    {"detect": cmd_detect, "scaffold": cmd_scaffold, "render": cmd_render,
     "lint": cmd_lint, "record": cmd_record, "verify": cmd_verify}.get(
        sub, lambda _o: (print("unknown command '%s'. choices: detect scaffold render lint record "
                               "verify" % sub), sys.exit(2)))(opts)


if __name__ == "__main__":
    main()
