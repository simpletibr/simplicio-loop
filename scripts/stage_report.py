#!/usr/bin/env python3
"""simplicio-loop — stage_report worker (#433 "Portable Stage Agents" + #442 identity/idempotency
spec): idempotent, per-work-item GitHub progress comments across the FULL lifecycle
(discovered -> claimed -> intake/planning -> implementation -> safety -> review -> delivery/
PR/checks/merge -> feedback/retry/recovery -> final audit -> COMPLETE|PARTIAL|BLOCKED|REGRESSED),
on both the source issue and the linked PR, never a false "done" claimed by the comment alone.

This is the CLI surface for `simplicio_loop/stage_report.py` — the envelope/identity/idempotency-
key module. It reuses `scripts/pr_evidence.py::publish_comment`/`find_existing_comment` (the same
fail-closed, marker-based, no-shell-interpolation primitive #285/#295/#301 already hardened)
rather than re-implementing a second create-or-update path.

Verbs:
  preview   Render the stage-report body to stdout. Never touches the network.
  publish   Render + publish (create-or-update, idempotent) to an issue and/or a PR, then
            re-query and confirm the observed body hash. `--dry-run` (or omitting BOTH --issue
            and --pr) renders and prints without calling `gh`. A publish that cannot be
            confirmed by re-query BLOCKS (exit 3) rather than claiming success.
  selftest  Prove identity formatting, idempotency-key stability, marker-based find-and-update
            (fake `gh` runner, no network), status-tag validation, and sanitization/truncation —
            deterministically, no files, no network.

Usage:
    python3 scripts/stage_report.py preview --run-id r1 --item T1 --stage implementation \\
        --name Claude --role Implementer --model claude-sonnet-5 --status PASS
    python3 scripts/stage_report.py publish --run-id r1 --item T1 --stage delivery \\
        --name Claude --role Implementer --model claude-sonnet-5 --status PASS \\
        --repo acme/widgets --issue 12 --pr 34
    python3 scripts/stage_report.py selftest
"""
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from simplicio_loop.stage_report import (  # noqa: E402
    STAGE_REPORT_SCHEMA, STATUS_TAGS, build_marker, format_agent_identity, hostname_abbrev,
    idempotency_key, publish_stage_report, render_stage_report, sanitize, truncate_body,
)
from simplicio_loop.pr_evidence import PublishError, publish_comment  # noqa: E402

_BLOCKED = 3


def log(msg):
    print("  " + msg, file=sys.stderr)


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


def _repo_slug_from_opts(opts):
    """Resolve 'owner/name' from --repo ONLY — no implicit git-remote auto-detect (same
    "no silent fallback" discipline as `pr_evidence._repo_slug_from_opts`)."""
    repo_opt = opts.get("repo")
    if isinstance(repo_opt, str) and "/" in repo_opt:
        return tuple(repo_opt.strip().split("/", 1))
    return None


def _identity_from_opts(opts):
    if isinstance(opts.get("agent-identity"), str):
        return opts["agent-identity"]
    return format_agent_identity(
        opts.get("name") if isinstance(opts.get("name"), str) else "agent",
        opts.get("role") if isinstance(opts.get("role"), str) else "worker",
        opts.get("model") if isinstance(opts.get("model"), str) else "unknown-model",
        hostname=opts.get("hostname") if isinstance(opts.get("hostname"), str) else None,
    )


def _render_kwargs_from_opts(opts):
    evidence = opts.get("evidence")
    evidence_list = [e.strip() for e in evidence.split(",")] if isinstance(evidence, str) else None
    return dict(
        run_id=opts.get("run-id") or "run",
        item=opts.get("item") or "item",
        stage=opts.get("stage") or "implementation",
        agent_identity=_identity_from_opts(opts),
        status=opts.get("status") or "BLOCKED",
        attempt=opts.get("attempt") or 1,
        fence=opts.get("fence") if isinstance(opts.get("fence"), str) else "",
        transition=opts.get("transition") if isinstance(opts.get("transition"), str) else "update",
        reason_code=opts.get("reason-code") if isinstance(opts.get("reason-code"), str) else "",
        receipt_id=opts.get("receipt-id") if isinstance(opts.get("receipt-id"), str) else "",
        issue=opts.get("issue") if isinstance(opts.get("issue"), str) else None,
        pr=opts.get("pr") if isinstance(opts.get("pr"), str) else None,
        commit=opts.get("commit") if isinstance(opts.get("commit"), str) else "",
        evidence=evidence_list,
        next_gate=opts.get("next-gate") if isinstance(opts.get("next-gate"), str) else "",
    )


def cmd_preview(opts):
    kwargs = _render_kwargs_from_opts(opts)
    try:
        body = render_stage_report(**kwargs)
    except ValueError as exc:
        print("blocked")
        log("BLOCKED — %s" % exc)
        sys.exit(_BLOCKED)
    sys.stdout.write(body)


def cmd_publish(opts):
    kwargs = _render_kwargs_from_opts(opts)
    try:
        body_preview = render_stage_report(**kwargs)
    except ValueError as exc:
        print("blocked")
        log("BLOCKED — %s" % exc)
        sys.exit(_BLOCKED)

    issue = opts.get("issue")
    pr = opts.get("pr")
    dry_run = bool(opts.get("dry-run")) or (not issue and not pr)
    if dry_run:
        sys.stdout.write(body_preview)
        log("dry-run — no --issue/--pr (or explicit --dry-run); nothing published")
        return

    slug = _repo_slug_from_opts(opts)
    if not slug:
        log("BLOCKED — publish requires an explicit --repo owner/name.")
        sys.exit(_BLOCKED)
    owner, repo = slug

    targets = []
    if isinstance(issue, str):
        targets.append(("issue", issue))
    if isinstance(pr, str):
        targets.append(("pr", pr))

    receipts = []
    for kind, number in targets:
        try:
            receipt = publish_stage_report(
                owner=owner, repo=repo, target_number=number,
                publish_comment_fn=publish_comment, **kwargs,
            )
        except PublishError as exc:
            log("BLOCKED — could not publish stage report to %s/%s#%s (%s): %s" %
                (owner, repo, number, kind, exc))
            sys.exit(_BLOCKED)
        receipts.append((kind, number, receipt))

    ok = True
    for kind, number, receipt in receipts:
        if not receipt.get("verified"):
            ok = False
            log("BLOCKED — stage report to %s/%s#%s (%s) published but NOT confirmed by "
                "re-query (comment_id=%s)." % (owner, repo, number, kind, receipt.get("comment_id")))
        else:
            log("published (%s) comment id=%s on %s/%s#%s (%s)" %
                (receipt.get("action"), receipt.get("comment_id"), owner, repo, number, kind))
    print(json.dumps({"schema": STAGE_REPORT_SCHEMA,
                      "receipts": [r for _, _, r in receipts]}))
    if not ok:
        sys.exit(_BLOCKED)


def cmd_selftest(_opts):
    checks = []

    def chk(name, cond):
        checks.append(bool(cond))
        print("  [%s] %s" % ("ok" if cond else "XX", name))

    chk("hostname.always_4_chars", len(hostname_abbrev("ab")) == 4)
    chk("hostname.uppercase", hostname_abbrev("myhost.local") == "MYHO")
    chk("hostname.short_padded", hostname_abbrev("a1") == "A1XX")

    ident = format_agent_identity("Claude", "Implementer", "claude-sonnet-5", hostname="devbox01")
    chk("identity.format", ident == "Claude/Implementer - #DEVB - claude-sonnet-5")
    chk("identity.same_model_diff_host_differs",
        format_agent_identity("Claude", "Implementer", "claude-sonnet-5", hostname="alpha01") !=
        format_agent_identity("Claude", "Implementer", "claude-sonnet-5", hostname="beta02"))

    k1 = idempotency_key("r1", "T1", "implementation", 1, "retry")
    k2 = idempotency_key("r1", "T1", "implementation", 1, "retry")
    k3 = idempotency_key("r1", "T1", "implementation", 2, "retry")
    chk("idempotency.stable_across_retries", k1 == k2)
    chk("idempotency.differs_on_attempt", k1 != k3)

    chk("marker.scoped_to_run_and_item", build_marker("r1", "T1") == build_marker("r1", "T1"))
    chk("marker.differs_across_items", build_marker("r1", "T1") != build_marker("r1", "T2"))

    body = render_stage_report(run_id="r1", item="T1", stage="review", agent_identity=ident,
                                status="PASS", issue="12", pr="34", commit="abc123",
                                evidence=["shot.png"], next_gate="merge")
    chk("render.has_marker", build_marker("r1", "T1") in body)
    chk("render.has_links", "Issue #12" in body and "PR #34" in body and "abc123" in body)
    chk("render.has_status", "**PASS**" in body)

    try:
        render_stage_report(run_id="r1", item="T1", stage="review", agent_identity=ident,
                            status="NOT-A-STATUS")
        chk("render.rejects_bad_status", False)
    except ValueError:
        chk("render.rejects_bad_status", True)

    chk("sanitize.redacts_token", "[REDACTED-TOKEN]" in sanitize("ghp_" + "x" * 30))
    chk("sanitize.redacts_secret_field", "[REDACTED]" in sanitize("api_key: super-secret-value"))
    chk("truncate.caps_length", len(truncate_body("x" * 100, max_chars=50)) <= 60)
    chk("truncate.passthrough_under_cap", truncate_body("short", max_chars=50) == "short")

    # publish_stage_report: query-before-decide is genuinely wired (not just unit-tested standalone)
    # — a fake publish_comment_fn records whether it was called with the item's marker.
    seen = {}

    def fake_publish_comment_fn(owner, repo, number, body, marker=None, runner=None, timeout=20):
        seen["marker"] = marker
        seen["number"] = number
        return {"action": "created", "id": 42}

    receipt = publish_stage_report(
        owner="acme", repo="widgets", target_number="12", run_id="r1", item="T1",
        stage="delivery", agent_identity=ident, status="PASS",
        publish_comment_fn=fake_publish_comment_fn,
    )
    chk("publish.wires_item_marker", seen.get("marker") == build_marker("r1", "T1"))
    chk("publish.targets_given_number", seen.get("number") == "12")
    chk("publish.returns_comment_id", receipt.get("comment_id") == 42)
    chk("publish.unverified_without_requery", receipt.get("verified") is False)

    def fake_get_comment_body_fn(owner, repo, comment_id, runner, timeout):
        # simulate the exact body that was just published
        return render_stage_report(run_id="r1", item="T1", stage="delivery",
                                    agent_identity=ident, status="PASS")

    receipt2 = publish_stage_report(
        owner="acme", repo="widgets", target_number="12", run_id="r1", item="T1",
        stage="delivery", agent_identity=ident, status="PASS",
        publish_comment_fn=fake_publish_comment_fn,
        get_comment_body_fn=fake_get_comment_body_fn,
    )
    chk("publish.verified_when_requery_matches", receipt2.get("verified") is True)

    # idempotent create-vs-update, driven through the REAL scripts.pr_evidence.publish_comment
    # primitive (not a reimplementation), proving stage_report reuses rather than duplicates it.
    calls = []

    def gh_no_existing(cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ["gh", "api"] and "comments" in cmd[2] and "-X" not in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
        if "-X" in cmd and "POST" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"id": 777}), stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unexpected")

    r3 = publish_stage_report(
        owner="acme", repo="widgets", target_number="12", run_id="r1", item="T1",
        stage="delivery", agent_identity=ident, status="PASS",
        publish_comment_fn=publish_comment, runner=gh_no_existing,
    )
    chk("publish.real_primitive_creates", r3.get("action") == "created" and r3.get("comment_id") == 777)

    calls2 = []
    marker = build_marker("r1", "T1")

    def gh_with_existing(cmd, **kw):
        calls2.append(cmd)
        if cmd[:2] == ["gh", "api"] and "comments" in cmd[2] and "-X" not in cmd:
            marked = [{"id": 888, "body": "old\n\n" + marker + "\n"}]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(marked), stderr="")
        if "-X" in cmd and "PATCH" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unexpected")

    r4 = publish_stage_report(
        owner="acme", repo="widgets", target_number="12", run_id="r1", item="T1",
        stage="delivery", agent_identity=ident, status="REGRESSED",
        publish_comment_fn=publish_comment, runner=gh_with_existing,
    )
    chk("publish.real_primitive_updates_same_id", r4.get("action") == "updated" and r4.get("comment_id") == 888)
    chk("publish.never_duplicates", not any("-X" in c and "POST" in c for c in calls2))

    ok = all(checks)
    print("selftest: %s (%d/%d)" % ("PASS" if ok else "FAIL", sum(checks), len(checks)))
    sys.exit(0 if ok else 1)


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(2)
    if argv[0] == "--describe-cli":
        print(json.dumps({
            "verbs": ["preview", "publish", "selftest"],
            "flags": [
                "--agent-identity", "--attempt", "--commit", "--dry-run", "--evidence",
                "--fence", "--help", "--hostname", "--issue", "--item", "--model",
                "--name", "--next-gate", "--pr", "--reason-code", "--receipt-id", "--repo",
                "--role", "--run-id", "--stage", "--status", "--transition",
            ],
        }))
        sys.exit(0)
    sub, opts = argv[0], _parse(argv[1:])
    {"preview": cmd_preview, "publish": cmd_publish, "selftest": cmd_selftest}.get(
        sub, lambda _o: (print("unknown command '%s'. choices: preview publish selftest" % sub),
                        sys.exit(2)))(opts)


if __name__ == "__main__":
    main()
