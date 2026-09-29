#!/usr/bin/env python3
"""simplicio-loop — pr_evidence worker (every PR carries prints + an item-by-item AC checklist).

The complaint this closes: "ao abrir a PR, o loop não está evidenciando com prints, com checagem
item a item da tarefa" — PRs were opened without screenshots and without a per-criterion check of
the task. The skill DESCRIBED attaching evidence (Step 6/6b) but nothing ASSEMBLED it, so it was
skippable. This worker makes the PR body deterministic and model-free, gathering:

  • the **item-by-item acceptance-criteria checklist** from the task anchor (`task_anchor.py`) —
    one line per AC, with its status + the receipt that verified it;
  • the **prints / screenshots** captured by `web_verify.py` under `.simplicio-loop/orchestrator/tee/web`
    (`--shots-dir`) AND any demo video from `video_evidence.py` under `.simplicio-loop/orchestrator/tee/video`
    (`--video-dir`) — embedded as markdown image links / a video link (paths + a count, never the
    bytes — token economy);
  • the gate receipts / ledger rows already on disk.

It honors `.github/PULL_REQUEST_TEMPLATE.md` when present (fills its sections), else a clear default
layout. Crucially it is **fail-closed on evidence**: with `--require-evidence`, if there is neither
an AC checklist nor a single captured print, it prints `blocked` and exits 3 — the loop cannot open
an evidence-less PR by accident (same never-fake-pass discipline as the evidence producers).

Deterministic, stdlib-only, no network. Pairs with `task_anchor.py` (the checklist source) and
`web_verify.py` / `video_evidence.py` (the prints).

Verbs:
  build      Emit the full PR body markdown (stdout or --out FILE). --require-evidence → exit 3 if
             there is no checklist and no print to show. --local-report (#526 Etapa 4) writes the
             body to a local file instead — auto-triggered, no flag needed, whenever the anchored
             delivery contract (`task_anchor.py set --delivery`) declares `open_pr: false`; the PR
             API is never called in this mode. Also folds in a "Delivery contract compliance"
             section (MEASURED, one line per clause) whenever a delivery contract is anchored,
             --local-report or not.
  comment    Emit the shorter source-item evidence comment (PR link + verification summary +
             checklist + a count of attached prints) — the comment Step 6 posts back on the issue.
             Always prints to stdout; with `--publish --issue N [--repo owner/name]` ALSO delegates
             it to the #285 canonical GitHub lifecycle comment
             (`simplicio_loop.github_lifecycle.publish_lifecycle_state`, state `PR_OPEN` when
             `--pr` is given, else `VERIFYING`) — the SAME single status comment `claim`/`PLANNED`
             already use, never a second stray comment. `--run-id`/`--attempt-id`/`--state`
             override the identity/state used for that publish. A publish failure, or a
             publish that a re-query cannot confirm, BLOCKS (exit 3) rather than silently
             claiming success.
  progress-comment  Publish/update ONE idempotent progress comment on an issue (#301), marked with
             an invisible HTML anchor so a re-run edits the SAME comment instead of spamming new
             ones. Rate-limited (default 60s between remote updates) and fully fail-open: no `gh`
             CLI / network / token ⇒ exit 0, silent log, never blocks the loop. `--now-epoch` and
             `--state-path` are a clock-injection seam (#301 AC7) letting a CLI-level test drive
             the rate limiter deterministically without sleeping.
  selftest   Prove the assembly + the evidence-gate deterministically — no files, no network.

Usage:
    python3 scripts/pr_evidence.py build --title "Add SSO login" --item 12 \\
        --summary "Adds an SSO button and the IdP redirect." \\
        --shots-dir .simplicio-loop/orchestrator/tee/web --require-evidence --out .simplicio-loop/orchestrator/pr_body.md
    python3 scripts/pr_evidence.py comment --item 12 --pr 34
    python3 scripts/pr_evidence.py comment --item 12 --pr 34 --publish --issue 12 \\
        --repo wesleysimplicio/simplicio-loop
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

try:  # Windows consoles default to cp1252 and choke on non-ASCII — force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:  # so `from simplicio_loop import github_lifecycle` resolves (#285)
    sys.path.insert(0, REPO)
DEFAULT_SHOTS = os.path.join(REPO, ".simplicio-loop/orchestrator", "tee", "web")
# video_evidence.py's REAL default output dir (see its DEFAULT_OUT) — a separate directory from
# DEFAULT_SHOTS. #81 found this drift: docs claimed recordings land under tee/web too, but the
# producer actually writes tee/video, so a demo video was silently never picked up by
# `build`/`comment` unless the caller manually widened --shots-dir. Scanned in ADDITION to
# --shots-dir by default so the evidence chain connects without extra flags.
DEFAULT_VIDEO_SHOTS = os.path.join(REPO, ".simplicio-loop/orchestrator", "tee", "video")
DEFAULT_TEMPLATE = os.path.join(REPO, ".github", "PULL_REQUEST_TEMPLATE.md")

IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
VID_EXT = (".mp4", ".webm", ".mov", ".gif")
_BLOCKED = 3  # same BLOCKED exit code the evidence producers use (web_verify / video_evidence)

# import the anchor's pure helpers so the checklist renders identically here and in task_anchor.
sys.path.insert(0, HERE)
try:
    from task_anchor import render_checklist, coverage, ANCHOR as ANCHOR_DEFAULT
except Exception:  # pragma: no cover - keep pr_evidence usable even if the import path shifts
    ANCHOR_DEFAULT = os.path.join(REPO, ".simplicio-loop/orchestrator", "loop", "anchor.json")

    def coverage(criteria):
        total = len(criteria)
        done = sum(1 for c in criteria if c.get("status") == "done")
        return done, total, [c.get("id") for c in criteria if c.get("status") != "done"]

    def render_checklist(criteria, heading="Acceptance criteria (item-by-item)"):
        lines = ["### %s" % heading]
        if not criteria:
            return lines[0] + "\n- _(no acceptance criteria were anchored for this item)_"
        for c in criteria:
            box = {"done": "x", "partial": "~"}.get(c.get("status"), " ")
            line = "- [%s] **%s** %s" % (box, c.get("id"), c.get("text"))
            if (c.get("evidence") or "").strip():
                line += " — _evidence:_ %s" % c["evidence"].strip()
            lines.append(line)
        d, t, _ = coverage(criteria)
        lines += ["", "**Coverage:** %d/%d criteria verified." % (d, t)]
        return "\n".join(lines)

try:
    from task_backlog import render_backlog_table
except Exception:  # pragma: no cover
    render_backlog_table = None

# #526 Etapa 4 — the delivery contract worker. Best-effort import: an install that predates the
# delivery contract (or one missing the sibling script) simply skips the compliance section and
# the open_pr:false auto-trigger, never blocking the ordinary PR-evidence flow over it.
try:
    import delivery_contract as _delivery
except Exception:  # pragma: no cover
    _delivery = None

DEFAULT_LOCAL_REPORT = os.path.join(REPO, ".simplicio-loop/orchestrator", "loop", "delivery_report.md")


def log(msg):
    print("  " + msg, file=sys.stderr)


def _emit_progress(status, outcome=None, detail=""):
    """Fail-open progress-feedback hook (#301) — never raises, never blocks pr_evidence."""
    try:
        import loop_progress
        loop_progress.emit_event("evidence", status=status, outcome=outcome, detail=detail,
                                 source="pr_evidence.py")
    except Exception:
        pass


def render_progress_section():
    """`## Progresso do run` — auto-included whenever a backlog/anchor exists on disk. Never
    fabricates a %: with neither source, prints the converge-mode ACs x/y line, no invented number
    (#301 AC2)."""
    try:
        import loop_progress
        snap = loop_progress.build_snapshot()
        header = loop_progress.render_turn_header(snap)
    except Exception:
        return ""
    lines = ["### Progresso do run", "", header, ""]
    return "\n".join(lines)


# ----- progress-comment (idempotent, rate-limited, fail-open) --------------------------------

PROGRESS_COMMENT_MARKER = "<!-- simplicio-loop:progress -->"
PROGRESS_COMMENT_STATE = os.path.join(REPO, ".simplicio-loop/orchestrator", "loop", "progress_comment_state.json")
DEFAULT_MIN_INTERVAL_S = 60.0


def _gh_run(cmd, timeout=30):
    """Injectable gh-CLI runner — tests pass a fake in place of this. None on any failure."""
    try:
        return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def build_progress_comment_body():
    try:
        import loop_progress
        snap = loop_progress.build_snapshot()
        header = loop_progress.render_turn_header(snap)
    except Exception:
        header = "UNVERIFIED|pct=?"
    return "\n".join([
        PROGRESS_COMMENT_MARKER, "",
        "**simplicio-loop progress**", "",
        header, "",
        "_updated: %s_" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    ]) + "\n"


def _rate_limited(min_interval=DEFAULT_MIN_INTERVAL_S, now=None, state_path=None):
    state_path = state_path or PROGRESS_COMMENT_STATE
    now = now if now is not None else time.time()
    last = 0.0
    try:
        with open(state_path, encoding="utf-8") as f:
            last = float(json.load(f).get("last_posted_at") or 0)
    except Exception:
        last = 0.0
    return (now - last) < min_interval


def _record_post(now=None, state_path=None):
    state_path = state_path or PROGRESS_COMMENT_STATE
    now = now if now is not None else time.time()
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump({"last_posted_at": now}, f)
    except Exception:
        pass


def find_existing_progress_comment(issue, runner=None):
    """Return the comment id whose body contains the anchor marker, or None. `runner` is
    injectable so tests never shell out to a real `gh`."""
    runner = runner or _gh_run
    r = runner(["gh", "api", "repos/:owner/:repo/issues/%s/comments" % issue, "--paginate"])
    if r is None or r.returncode != 0:
        return None
    try:
        comments = json.loads(r.stdout or "[]")
    except ValueError:
        return None
    if not isinstance(comments, list):
        return None
    for c in comments:
        if isinstance(c, dict) and PROGRESS_COMMENT_MARKER in (c.get("body") or ""):
            return c.get("id")
    return None


# --- Idempotent GitHub comment publish (#295 audit: "pr_evidence.py comment gera Markdown em
# stdout, mas não publica nem valida o comentário na issue") ------------------------------------
#
# `cmd_comment` always rendered the evidence comment markdown to stdout only -- nothing actually
# posted it back to the source issue, and nothing verified a post landed. This closes that gap
# with a real, idempotent publish path: `--publish --repo owner/name --issue N` posts the comment
# via `gh api` (never `gh issue comment`, which has no built-in "find and update my own prior
# comment" primitive), tagging the body with a hidden HTML marker so a SECOND run on the same
# issue UPDATES the existing comment instead of appending a duplicate — the same idempotency
# discipline the rest of the loop's evidence/receipt path requires (#295 invariant: "Idempotência
# ponta a ponta: repetir claim, comentário, receipt, merge ou reconciliação não duplica efeitos").
#
# The GitHub call is injected as a `runner` (defaults to subprocess.run) so this is unit-testable
# without ever touching the network or a real repo — the same injected-`runner` pattern as
# `simplicio_loop/github_lifecycle.py`.
#
# `publish_comment`/`find_existing_comment`/`PR_EVIDENCE_COMMENT_MARKER` remain the general
# idempotent create-or-update PRIMITIVE (no shell interpolation, JSON payload on stdin,
# `PublishError` fail-closed on any `gh` failure) — `simplicio_loop/github_lifecycle.py` itself
# takes this exact function in as its injected `publish_comment_fn`. What changed for #285 is
# WHO calls it and with WHICH marker: `cmd_comment --publish` used to call it directly with
# `PR_EVIDENCE_COMMENT_MARKER`, opening a SECOND, stray comment on the issue distinct from the
# canonical `LIFECYCLE_COMMENT_MARKER` one — a direct violation of #285's "Um comentário
# canônico: claim, planejamento, progresso, evidência e fechamento atualizam o mesmo comment
# ID." `publish_evidence_via_lifecycle` below now routes the SAME rendered evidence body through
# `github_lifecycle.publish_lifecycle_state` as the `tests_and_evidence`/`delivery` fields of the
# ONE canonical lifecycle comment (state `VERIFYING`/`PR_OPEN`), so there is only ever one active
# status comment per issue, matching the `PLANNED` wiring `planning_gate.publish_planning_receipt`
# already does for the planning receipt. `PR_EVIDENCE_COMMENT_MARKER` is kept only as the
# underlying primitive's default marker (used directly by `github_lifecycle.py`'s own CLI and by
# `cmd_progress_comment`'s separate progress-comment, which is intentionally its own lightweight,
# rate-limited, fail-open comment and out of scope for the #285 lifecycle machinery).
PR_EVIDENCE_COMMENT_MARKER = "<!-- simplicio-loop:pr-evidence-comment -->"


class PublishError(RuntimeError):
    """Raised when the GitHub comment publish could not be completed or verified."""


def _run_gh(args, runner, timeout, input_text=None):
    # `text=True` without an explicit encoding falls back to the platform's default
    # locale encoding (cp1252 on Windows), which raises `UnicodeDecodeError` on any
    # issue title/body/comment containing non-Latin1 characters (emoji, non-ASCII
    # names, ...) -- a real failure observed live against wesleysimplicio/simplicio-loop
    # issue #347 during the #285 lifecycle-adapter E2E. `gh` always emits UTF-8.
    completed = runner(["gh"] + args, capture_output=True, text=True, timeout=timeout,
                        check=False, input=input_text, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise PublishError("gh %s failed: %s" % (" ".join(args), stderr or "unknown error"))
    return completed.stdout


def find_existing_comment(owner, repo, issue, marker=PR_EVIDENCE_COMMENT_MARKER,
                           runner=subprocess.run, timeout=20):
    """Return the numeric id of a prior comment on `issue` whose body carries `marker`, or None.

    Paginates through `gh api repos/{owner}/{repo}/issues/{issue}/comments` and returns the FIRST
    match (there should only ever be one, since publish always reuses it) so a re-run edits rather
    than appends.
    """
    stdout = _run_gh(
        ["api", "repos/%s/%s/issues/%s/comments" % (owner, repo, issue), "--paginate"],
        runner, timeout)
    try:
        comments = json.loads(stdout)
    except ValueError:
        raise PublishError("gh api returned non-JSON comment list")
    if not isinstance(comments, list):
        comments = []
    for c in comments:
        if marker in (c.get("body") or ""):
            return c.get("id")
    return None


def _resolve_now(opts):
    """Clock-injection seam for the rate limiter (#301 AC7). Precedence: `--now-epoch` CLI flag >
    `SIMPLICIO_PROGRESS_COMMENT_NOW` env var > real `time.time()`. Lets a CLI-level test drive
    `progress-comment` twice with a controlled "now" (e.g. 1s apart vs 61s apart) and assert the
    rate-limit gate deterministically, without sleeping or mocking internals."""
    raw = opts.get("now-epoch")
    if raw is None or raw is True:
        raw = os.environ.get("SIMPLICIO_PROGRESS_COMMENT_NOW")
    if raw is None or raw is True:
        return time.time()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return time.time()


def cmd_progress_comment(opts):
    """Publish/update ONE idempotent progress comment on an issue (#301 § 3). Fail-open: no `gh`,
    no network, or any error -> exit 0, silent log, never blocks the loop."""
    issue = opts.get("issue")
    if not issue:
        print("blocked")
        log("progress-comment requires --issue")
        return
    try:
        min_interval = float(opts.get("min-interval") or DEFAULT_MIN_INTERVAL_S)
    except (TypeError, ValueError):
        min_interval = DEFAULT_MIN_INTERVAL_S
    now = _resolve_now(opts)
    state_path = opts.get("state-path") or None
    if opts.get("state-path") is True:
        state_path = None
    if not shutil.which("gh"):
        print("skip")
        log("gh CLI not found — progress-comment is a no-op (fail-open)")
        return
    if _rate_limited(min_interval, now=now, state_path=state_path):
        print("skip")
        log("rate-limited — last update <%.0fs ago" % min_interval)
        return
    body = build_progress_comment_body()
    ok = False
    try:
        existing = find_existing_progress_comment(issue)
        if existing:
            r = _gh_run(["gh", "api", "-X", "PATCH",
                        "repos/:owner/:repo/issues/comments/%s" % existing,
                        "-f", "body=%s" % body])
        else:
            r = _gh_run(["gh", "api", "repos/:owner/:repo/issues/%s/comments" % issue,
                        "-f", "body=%s" % body])
        ok = r is not None and r.returncode == 0
    except Exception:
        ok = False
    _record_post(now=now, state_path=state_path)
    tag = "MEASURED" if ok else "UNVERIFIED"
    print("%s|progress-comment %s" % (tag, "updated" if ok else "attempted (see stderr for gh output)"))


def publish_comment(owner, repo, issue, body, marker=PR_EVIDENCE_COMMENT_MARKER,
                     runner=subprocess.run, timeout=20):
    """Publish `body` to `issue` idempotently. Returns {"action": "created"|"updated", "id": int}.

    Tags the body with the hidden marker (added once, not duplicated if already present), then
    either PATCHes the existing tagged comment or POSTs a new one. Raises `PublishError` on any
    `gh` failure -- callers must treat that as BLOCKED, never as a silent success, per the
    "no silent fallback" invariant (#295): a comment that failed to post must never be reported as
    posted.

    The request body is sent as a JSON payload on stdin (`gh api ... --input -`), never via
    `-f body=@path`/shell interpolation of the rendered markdown -- this avoids any quoting/shell
    injection surface from untrusted acceptance-criteria text or file paths ending up in the
    argument vector.
    """
    tagged_body = body if marker in body else (body.rstrip("\n") + "\n\n" + marker + "\n")
    existing_id = find_existing_comment(owner, repo, issue, marker=marker, runner=runner,
                                        timeout=timeout)
    payload = json.dumps({"body": tagged_body})
    if existing_id is not None:
        _run_gh(["api", "-X", "PATCH",
                 "repos/%s/%s/issues/comments/%s" % (owner, repo, existing_id),
                 "--input", "-"], runner, timeout, input_text=payload)
        return {"action": "updated", "id": existing_id}
    stdout = _run_gh(["api", "-X", "POST",
                      "repos/%s/%s/issues/%s/comments" % (owner, repo, issue),
                      "--input", "-"], runner, timeout, input_text=payload)
    try:
        created = json.loads(stdout)
        new_id = created.get("id")
    except ValueError:
        new_id = None
    return {"action": "created", "id": new_id}


def publish_evidence_via_lifecycle(owner, repo, issue, body, *, pr=None, run_id="", attempt_id="",
                                    state=None, runner=None, timeout=20, require_active=None,
                                    outbox_dir=None, **render_kwargs):
    """Delegate the source-item evidence comment to the #285 canonical lifecycle comment.

    Projects `body` (the same PR-link + coverage + checklist markdown `cmd_comment` always
    rendered) as the `tests_and_evidence` section of `github_lifecycle.py`'s ONE canonical
    status comment, updating state to `PR_OPEN` when a `pr` number is known, else `VERIFYING` —
    instead of posting a second, separate comment. Mirrors
    `simplicio_loop.planning_gate.publish_planning_receipt`'s wiring of the `PLANNED` state onto
    the same comment: same `publish_comment_fn` primitive, same re-query-verified
    `simplicio.github-lifecycle-receipt/v1` return type. `run_id`/`attempt_id` default to
    stable, non-empty placeholders (never blank) so the receipt's `operation_id` stays
    deterministic even when the caller (a bare CLI invocation) has no run/attempt identity to
    hand in. A transport failure from `publish_comment_fn` (`PublishError`) propagates
    fail-closed, same as the direct `publish_comment` path this replaces.
    """
    from simplicio_loop import github_lifecycle as _gh

    resolved_state = state or ("PR_OPEN" if pr else "VERIFYING")
    render_kwargs = dict(render_kwargs)
    render_kwargs.setdefault("tests_and_evidence", body)
    if pr and "delivery" not in render_kwargs:
        render_kwargs["delivery"] = "PR #%s" % str(pr).lstrip("#")
    kwargs = dict(
        owner=owner, repo=repo, issue=str(issue).lstrip("#"), state=resolved_state,
        run_id=run_id or "pr-evidence", attempt_id=attempt_id or ("issue-%s" % str(issue).lstrip("#")),
        publish_comment_fn=publish_comment, timeout=timeout,
        require_active=require_active, outbox_dir=outbox_dir, **render_kwargs,
    )
    if runner is not None:
        kwargs["runner"] = runner
    return _gh.publish_lifecycle_state(**kwargs)


def _load_anchor(opts):
    path = opts.get("anchor") if isinstance(opts.get("anchor"), str) else ANCHOR_DEFAULT
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _load_backlog(opts):
    if render_backlog_table is None:
        return None, []
    path = (opts.get("backlog") if isinstance(opts.get("backlog"), str) else
            os.environ.get("SIMPLICIO_BACKLOG_FILE") or
            os.path.join(REPO, ".simplicio-loop/orchestrator", "backlog", "backlog.jsonl"))
    if not os.path.exists(path):
        return None, []
    master = None
    items = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                obj = json.loads(s)
                if obj.get("kind") == "master":
                    master = obj
                elif obj.get("kind") == "item":
                    items.append(obj)
    except (OSError, ValueError):
        return None, []
    return master, items


def collect_prints(shots_dir):
    """Return (images, videos) of evidence files under shots_dir, as repo-relative paths, sorted."""
    images, videos = [], []
    if not shots_dir or not os.path.isdir(shots_dir):
        return images, videos
    for root, dirs, names in os.walk(shots_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for n in sorted(names):
            low = n.lower()
            p = os.path.join(root, n)
            try:
                rel = os.path.relpath(p, REPO)
            except ValueError:
                rel = p
            rel = rel.replace(os.sep, "/")
            if low.endswith(IMG_EXT):
                images.append(rel)
            elif low.endswith(VID_EXT):
                videos.append(rel)
    return sorted(images), sorted(videos)


def collect_all_evidence(opts):
    """Merge prints from --shots-dir (default tee/web) AND --video-dir (default tee/video, the
    real video_evidence.py output dir — #81) into one deduped (images, videos) pair."""
    shots_dir = opts.get("shots-dir") if isinstance(opts.get("shots-dir"), str) else DEFAULT_SHOTS
    video_dir = opts.get("video-dir") if isinstance(opts.get("video-dir"), str) else DEFAULT_VIDEO_SHOTS
    images, videos = collect_prints(shots_dir)
    if os.path.abspath(video_dir) != os.path.abspath(shots_dir):
        more_images, more_videos = collect_prints(video_dir)
        images = sorted(set(images) | set(more_images))
        videos = sorted(set(videos) | set(more_videos))
    return images, videos


def render_evidence(images, videos, heading="Evidence — prints & recordings"):
    """Markdown block embedding each print as an image and each recording as a link."""
    lines = ["### %s" % heading]
    if not images and not videos:
        lines.append("- _(no prints captured — run `web_verify.py` / `video_evidence.py` first)_")
        return "\n".join(lines)
    for rel in images:
        name = os.path.basename(rel)
        lines.append("![%s](%s)" % (name, rel))
    for rel in videos:
        name = os.path.basename(rel)
        lines.append("- 🎬 [%s](%s)" % (name, rel))
    lines.append("")
    lines.append("_%d print(s), %d recording(s) attached._" % (len(images), len(videos)))
    return "\n".join(lines)


def _fill_template(tpl, blocks):
    """Append our evidence blocks to a discovered PR template (never drop the maintainer's sections).

    We do not try to surgically rewrite arbitrary templates (untrusted content); we keep the
    template verbatim and append the AC checklist + evidence under a clear divider, so the PR always
    has both the maintainer's layout AND the proof.
    """
    parts = [tpl.rstrip(), "", "---", ""]
    parts += blocks
    return "\n".join(parts).rstrip() + "\n"


def build_body(opts):
    """Assemble the PR body. Returns (markdown, has_evidence)."""
    anchor = _load_anchor(opts)
    criteria = anchor.get("criteria", [])
    backlog_master, backlog_items = _load_backlog(opts)
    images, videos = collect_all_evidence(opts)
    has_evidence = bool(criteria) or bool(backlog_items) or bool(images) or bool(videos)

    title = opts.get("title") or anchor.get("goal") or "Untitled change"
    item = opts.get("item") or anchor.get("item") or ""
    summary = opts.get("summary") or ""

    backlog_md = ""
    if backlog_items and render_backlog_table is not None:
        backlog_md = render_backlog_table(backlog_master, backlog_items, anchor=anchor)
    checklist_md = render_checklist(criteria)
    evidence_md = render_evidence(images, videos)
    how = opts.get("how") or "Run the project's test gate (`python3 scripts/check.py`) and the " \
                             "captured `web_verify` / `video_evidence` flow above."

    progress_md = render_progress_section()

    # #526 Etapa 4 — every PR/local report lists the frozen delivery contract and the MEASURED
    # compliance of each clause, when one is anchored. Silent when no contract or the sibling
    # worker is unavailable (fail-open, never blocks assembling the rest of the body).
    delivery_md = ""
    if _delivery is not None and isinstance(anchor.get("delivery"), dict):
        try:
            delivery_md = _delivery.render_compliance_report(anchor, REPO)
        except Exception:
            delivery_md = ""

    blocks = []
    if summary:
        blocks += ["### Summary", summary, ""]
    if item:
        blocks += ["Closes #%s" % str(item).lstrip("#"), ""]
    if progress_md:
        blocks += [progress_md, ""]
    if backlog_md:
        blocks += [backlog_md, ""]
    blocks += [checklist_md, "", evidence_md, "", "### How to verify", how, ""]
    if delivery_md:
        blocks += [delivery_md, ""]

    tpl_path = opts.get("template") if isinstance(opts.get("template"), str) else DEFAULT_TEMPLATE
    if tpl_path and os.path.exists(tpl_path):
        try:
            with open(tpl_path, encoding="utf-8", errors="replace") as f:
                tpl = f.read()
            body = "# %s\n\n" % title + _fill_template(tpl, blocks)
            return body, has_evidence
        except OSError:
            pass
    body = "# %s\n\n" % title + "\n".join(blocks).rstrip() + "\n"
    return body, has_evidence


def _local_report_active(opts):
    """True when this build must run in --local-report mode: explicit `--local-report`, OR the
    anchored delivery contract declares `open_pr: false` (#526 Etapa 4) — auto-triggered, the
    caller never has to remember the flag."""
    if opts.get("local-report"):
        return True
    anchor = _load_anchor(opts)
    delivery = anchor.get("delivery")
    return isinstance(delivery, dict) and delivery.get("open_pr") is False


def cmd_build(opts):
    _emit_progress("begin", detail="pr_evidence.py build")
    body, has_evidence = build_body(opts)
    if opts.get("require-evidence") and not has_evidence:
        print("blocked")
        log("BLOCKED — no acceptance-criteria checklist and no prints to attach. "
            "Anchor the ACs (task_anchor.py set) and capture prints (web_verify.py) before "
            "opening the PR. Refusing to open an evidence-less PR.")
        _emit_progress("blocked", outcome="blocked", detail="no checklist and no prints")
        sys.exit(_BLOCKED)
    local_report = _local_report_active(opts)
    out = opts.get("out")
    if local_report:
        # open_pr: false (or an explicit --local-report) -- write the evidence body to a LOCAL
        # file only. This mode never calls the PR API (`cmd_build` never did to begin with; this
        # just makes the "no PR" intent explicit in the artifact itself and picks a stable default
        # path so the caller doesn't have to remember one).
        if not isinstance(out, str):
            out = DEFAULT_LOCAL_REPORT
        banner = ("> **Local delivery report** — `open_pr: false` in the frozen delivery "
                  "contract; no PR was opened or will be opened from this artifact.\n\n")
        body = banner + body
    if isinstance(out, str):
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(body)
        log("wrote %s body -> %s (%d bytes)" % ("local-report" if local_report else "PR", out,
                                                 len(body)))
        print("done %s" % out)
        _emit_progress("end", outcome="pass", detail="%s -> %s" % (
            "local-report" if local_report else "PR body", out))
    else:
        sys.stdout.write(body)
        _emit_progress("end", outcome="pass", detail="PR body -> stdout (%d bytes)" % len(body))


def _repo_slug_from_opts(opts):
    """Resolve 'owner/name' from --repo ONLY.

    Deliberately no implicit fallback to `git remote get-url origin`: a "helpful" auto-detect here
    would mean a bare `--publish` invocation silently targets whatever repo the CWD happens to be
    in — exactly the "no silent fallback" anti-pattern (#295) this feature otherwise refuses to
    allow. Callers (the skill/loop driver) must pass the target explicitly.
    """
    repo_opt = opts.get("repo")
    if isinstance(repo_opt, str) and "/" in repo_opt:
        return tuple(repo_opt.strip().split("/", 1))
    return None


def cmd_comment(opts):
    """The shorter evidence comment posted back on the source item.

    Always renders to stdout (unchanged default behavior). With --publish (and --issue N and
    --repo owner/name — BOTH required explicitly, no implicit git-remote auto-detect), ALSO posts
    it to the GitHub issue — idempotently (a second run on the same issue updates the SAME comment
    via the hidden marker, never appends a duplicate). A publish failure (gh missing, auth,
    network, non-existent issue) BLOCKS (exit 3) with a clear message rather than silently
    claiming success — the same never-fake-pass discipline as the evidence producers (#295 audit:
    "pr_evidence.py comment gera Markdown em stdout, mas não publica nem valida o comentário na
    issue").
    """
    anchor = _load_anchor(opts)
    criteria = anchor.get("criteria", [])
    done, total, pending = coverage(criteria)
    backlog_master, backlog_items = _load_backlog(opts)
    images, videos = collect_all_evidence(opts)
    pr = opts.get("pr")
    lines = []
    if pr:
        lines.append("PR: #%s" % str(pr).lstrip("#"))
    lines.append("Verification: %d/%d acceptance criteria met · %d print(s), %d recording(s)."
                 % (done, total, len(images), len(videos)))
    if backlog_items:
        done_items = sum(1 for item in backlog_items if item.get("status") == "done")
        skipped = sum(1 for item in backlog_items if item.get("status") == "skipped")
        lines.append("Body of work: %d/%d done · %d skipped." %
                     (done_items, len(backlog_items), skipped))
    lines.append("")
    lines.append(render_checklist(criteria))
    if pending:
        lines += ["", "Still open: %s" % ", ".join(pending)]
    body = "\n".join(lines).rstrip() + "\n"
    sys.stdout.write(body)

    if not opts.get("publish"):
        return

    issue = opts.get("issue") or opts.get("item") or anchor.get("item")
    if not issue:
        log("BLOCKED — --publish requires --issue N (or an anchored item) to know which issue "
            "to comment on.")
        sys.exit(_BLOCKED)
    slug = _repo_slug_from_opts(opts)
    if not slug:
        log("BLOCKED — --publish requires an explicit --repo owner/name (no implicit git-remote "
            "auto-detect, by design — see _repo_slug_from_opts).")
        sys.exit(_BLOCKED)
    owner, repo = slug
    try:
        lifecycle_receipt = publish_evidence_via_lifecycle(
            owner, repo, issue, body, pr=pr,
            run_id=opts.get("run-id") if isinstance(opts.get("run-id"), str) else "",
            attempt_id=opts.get("attempt-id") if isinstance(opts.get("attempt-id"), str) else "",
            state=opts.get("state") if isinstance(opts.get("state"), str) else None,
        )
    except PublishError as exc:
        log("BLOCKED — could not publish the evidence comment to %s/%s#%s: %s" %
            (owner, repo, issue, exc))
        sys.exit(_BLOCKED)
    except Exception as exc:  # e.g. the github_lifecycle adapter failed to import
        log("BLOCKED — could not delegate the evidence comment to the #285 lifecycle adapter "
            "for %s/%s#%s: %s" % (owner, repo, issue, exc))
        sys.exit(_BLOCKED)
    if not lifecycle_receipt.get("verified"):
        log("BLOCKED — evidence comment published but NOT confirmed by re-query on %s/%s#%s "
            "(comment_id=%s) — treating as failed, never a silent success." %
            (owner, repo, issue, lifecycle_receipt.get("comment_id")))
        sys.exit(_BLOCKED)
    log("published (%s) comment id=%s on %s/%s#%s via the #285 canonical lifecycle comment "
        "(state=%s)" % (lifecycle_receipt.get("action"), lifecycle_receipt.get("comment_id"),
                        owner, repo, issue, lifecycle_receipt.get("state")))


def cmd_selftest(_opts):
    checks = []

    def chk(name, cond):
        checks.append(bool(cond))
        print("  [%s] %s" % ("ok" if cond else "XX", name))

    # render_evidence embeds images and links videos
    ev = render_evidence(["a/b/login.png"], ["a/b/demo.mp4"])
    chk("evidence.embeds_image", "![login.png](a/b/login.png)" in ev)
    chk("evidence.links_video", "demo.mp4" in ev and "🎬" in ev)
    chk("evidence.empty_note", "no prints captured" in render_evidence([], []))

    # build_body with an anchor present -> checklist appears, has_evidence True
    crit = [{"id": "AC1", "text": "Renders", "status": "done", "evidence": "x.png"},
            {"id": "AC2", "text": "Redirects", "status": "pending", "evidence": ""}]
    body = render_checklist(crit)
    chk("checklist.line_per_ac", body.count("- [") == 2)
    chk("checklist.done_box", "[x] **AC1**" in body)
    chk("checklist.pending_box", "[ ] **AC2**" in body)
    chk("checklist.coverage", "1/2" in body)

    # the evidence gate: no criteria + no prints => not has_evidence (build would BLOCK)
    d, t, p = coverage([])
    chk("coverage.empty", (d, t, p) == (0, 0, []))
    chk("coverage.partial", coverage(crit)[:2] == (1, 2))
    if render_backlog_table is not None:
        table = render_backlog_table({"kind": "master", "goal": "Phase 0"},
                                     [{"kind": "item", "id": "T1", "goal": "Fix | pipes",
                                       "goal_fp": "fp1", "acs": ["x"], "status": "done",
                                       "evidence": ["shot.png"], "done_criteria": 1,
                                       "total_criteria": 1, "skip_reason": ""}], anchor={})
        chk("backlog.heading", "Body of work" in table)
        chk("backlog.row", "T1" in table and "1/1" in table)
        chk("backlog.escaping", r"Fix \| pipes" in table)
    chk("backlog.fail_open", _load_backlog({"backlog": "definitely-missing.jsonl"}) == (None, []))

    # publish_comment idempotency: a fake `gh` runner records calls; first call with no existing
    # marked comment POSTs, second call (marker now present in the fake "comment list") PATCHes
    # the SAME id instead of creating a duplicate.
    calls = []

    def fake_runner_no_existing(cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ["gh", "api"] and "comments" in cmd[2] and "-X" not in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
        if "-X" in cmd and "POST" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"id": 555}), stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unexpected call")

    r1 = publish_comment("acme", "widgets", "12", "hello world", runner=fake_runner_no_existing)
    chk("publish.creates_when_absent", r1 == {"action": "created", "id": 555})
    chk("publish.posts_once", sum(1 for c in calls if "-X" in c and "POST" in c) == 1)

    calls2 = []

    def fake_runner_with_existing(cmd, **kw):
        calls2.append(cmd)
        if cmd[:2] == ["gh", "api"] and "comments" in cmd[2] and "-X" not in cmd:
            marked = [{"id": 999, "body": "old\n\n" + PR_EVIDENCE_COMMENT_MARKER + "\n"}]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(marked), stderr="")
        if "-X" in cmd and "PATCH" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unexpected call")

    r2 = publish_comment("acme", "widgets", "12", "hello again", runner=fake_runner_with_existing)
    chk("publish.updates_when_marker_found", r2 == {"action": "updated", "id": 999})
    chk("publish.never_posts_when_marker_found",
        not any("-X" in c and "POST" in c for c in calls2))

    def fake_runner_failure(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP 404: Not Found")

    try:
        publish_comment("acme", "widgets", "999999", "x", runner=fake_runner_failure)
        chk("publish.raises_on_gh_failure", False)
    except PublishError:
        chk("publish.raises_on_gh_failure", True)

    ok = all(checks)
    print("selftest: %s (%d/%d)" % ("PASS" if ok else "FAIL", sum(checks), len(checks)))
    sys.exit(0 if ok else 1)


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
    # --describe-cli: emit JSON spec of accepted verbs + flags
    if argv[0] == "--describe-cli":
        import json
        print(json.dumps({
            "verbs": ["build", "comment", "progress-comment", "selftest"],
            "flags": [
                "--anchor",
                "--attempt-id",
                "--backlog",
                "--help",
                "--how",
                "--issue",
                "--item",
                "--local-report",
                "--min-interval",
                "--now-epoch",
                "--out",
                "--pr",
                "--publish",
                "--repo",
                "--require-evidence",
                "--run-id",
                "--shots-dir",
                "--state",
                "--state-path",
                "--summary",
                "--template",
                "--title",
                "--video-dir",
            ],
        }))
        sys.exit(0)
    sub, opts = argv[0], _parse(argv[1:])
    {"build": cmd_build, "comment": cmd_comment, "progress-comment": cmd_progress_comment,
     "selftest": cmd_selftest}.get(
        sub, lambda _o: (print("unknown command '%s'. choices: build comment progress-comment "
                               "selftest" % sub), sys.exit(2)))(opts)


if __name__ == "__main__":
    main()
