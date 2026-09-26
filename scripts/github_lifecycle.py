#!/usr/bin/env python3
"""CLI shell for the #285 GitHub lifecycle adapter (canonical status comment).

    python3 scripts/github_lifecycle.py render --state PLANNED --run-id r1 --attempt-id a1
    python3 scripts/github_lifecycle.py publish --owner acme --repo widgets --issue 12 \
        --state CLAIMED --run-id r1 --attempt-id a1
    python3 scripts/github_lifecycle.py list-ready --owner acme --repo widgets
    python3 scripts/github_lifecycle.py get-details --owner acme --repo widgets --issue 12
    python3 scripts/github_lifecycle.py requery --owner acme --repo widgets --issue 12
    python3 scripts/github_lifecycle.py reconcile --owner acme --repo widgets --issue 12 \
        --operation-id <op-id> --outbox-dir .simplicio-loop/orchestrator/github-outbox
    python3 scripts/github_lifecycle.py close --owner acme --repo widgets --issue 12 \
        --run-id r1 --attempt-id a1
    python3 scripts/github_lifecycle.py reconcile-duplicates --owner acme --repo widgets \
        --issue 12
    python3 scripts/github_lifecycle.py selftest

`publish`/`close` shell out to the real `gh` CLI (via `scripts/pr_evidence.py::publish_comment`,
the same #295 idempotent create-or-update primitive) and re-query the same comment to
confirm the id/body-hash match before reporting success. `close` is fail-closed: it only
reports the issue closed after a post-close re-query confirms `state == closed`, and it
reports `CLOSE_PENDING_RECONCILIATION` (never a fake success) when the remote close
succeeds but the final comment update cannot be confirmed -- see
`simplicio_loop/github_lifecycle.py` for the full contract.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from pr_evidence import publish_comment  # noqa: E402

from simplicio_loop.github_lifecycle import (  # noqa: E402
    LIFECYCLE_STATES,
    close_source_issue,
    get_details,
    list_ready,
    persist_lifecycle_receipt,
    publish_lifecycle_state,
    reconcile,
    reconcile_duplicate_comments,
    render_lifecycle_comment,
    requery,
)


def cmd_render(args: argparse.Namespace) -> int:
    body = render_lifecycle_comment(state=args.state, run_id=args.run_id, attempt_id=args.attempt_id,
                                    goal=args.goal or "")
    print(body)
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    receipt = publish_lifecycle_state(
        owner=args.owner, repo=args.repo, issue=args.issue, state=args.state,
        run_id=args.run_id, attempt_id=args.attempt_id, fencing_token=args.fencing_token,
        publish_comment_fn=publish_comment, goal=args.goal or "",
    )
    if args.run_dir:
        persist_lifecycle_receipt(receipt, args.run_dir)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["verified"] else 1


def cmd_list_ready(args: argparse.Namespace) -> int:
    labels = [l for l in (args.labels or "").split(",") if l]
    result = list_ready(args.owner, args.repo, state=args.state, labels=labels,
                       assignee=args.assignee or "", milestone=args.milestone or "")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_get_details(args: argparse.Namespace) -> int:
    snapshot = get_details(args.owner, args.repo, args.issue)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def cmd_requery(args: argparse.Namespace) -> int:
    comment_id = int(args.comment_id) if args.comment_id else None
    snapshot = requery(args.owner, args.repo, args.issue, comment_id=comment_id)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    comment_id = int(args.comment_id) if args.comment_id else None
    receipt = reconcile(args.operation_id, outbox_dir=args.outbox_dir, owner=args.owner,
                        repo=args.repo, issue=args.issue, comment_id=comment_id,
                        expected_body_hash=args.expected_body_hash or "")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt.get("outcome") == "reconciled" else 1


def cmd_close(args: argparse.Namespace) -> int:
    planning_snapshot = None
    if args.planning_snapshot:
        with open(args.planning_snapshot, "r", encoding="utf-8") as fh:
            planning_snapshot = json.load(fh)
    receipt = close_source_issue(
        owner=args.owner, repo=args.repo, issue=args.issue, run_id=args.run_id,
        attempt_id=args.attempt_id, fencing_token=args.fencing_token,
        publish_comment_fn=publish_comment, outbox_dir=args.outbox_dir, goal=args.goal or "",
        planning_snapshot=planning_snapshot,
    )
    if args.run_dir:
        # Persists even a CLOSE_PENDING_RECONCILIATION outcome -- the completion oracle
        # (`simplicio_loop.oracle.evaluate_completion`) reads this file and blocks COMPLETE
        # while it says so, rather than that reason code being an inert status (#285).
        persist_lifecycle_receipt(receipt, args.run_dir)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt.get("outcome") == "closed" else 1


def cmd_reconcile_duplicates(args: argparse.Namespace) -> int:
    receipt = reconcile_duplicate_comments(args.owner, args.repo, args.issue,
                                           own_login=args.own_login or None)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    from simplicio_loop.github_lifecycle import (
        elect_canonical_comment,
        find_marker_comments,
        mark_comment_superseded,
        validate_transition,
    )

    checks = []

    def chk(name, got, want):
        ok = got == want
        checks.append(ok)
        print("  [%s] %-40s got=%r want=%r" % ("ok" if ok else "XX", name, got, want))

    chk("transition.valid", validate_transition("CLAIMED", "PLANNED")["ok"], True)
    chk("transition.invalid", validate_transition("CLAIMED", "MERGED")["ok"], False)
    chk("transition.duplicate_noop", validate_transition("PLANNED", "PLANNED")["reason_code"], "duplicate_noop")
    chk("transition.regression_needs_reason",
        validate_transition("PR_OPEN", "IN_PROGRESS", reason_code="SOURCE_CHANGED")["ok"], True)

    body = render_lifecycle_comment(state="CLAIMED", run_id="r", attempt_id="a")
    chk("render.has_marker", "simplicio-loop:lifecycle-status:v1" in body, True)
    chk("all_states_valid_arg", set(LIFECYCLE_STATES) >= {"CLAIMED", "PLANNED", "CLOSED"}, True)

    marker_comments = find_marker_comments([
        {"id": 5, "body": body, "user": {"login": "bot-a"}},
        {"id": 2, "body": body, "user": {"login": "bot-a"}},
        {"id": 9, "body": "no marker here", "user": {"login": "human"}},
    ])
    chk("dedupe.finds_only_marker_comments", len(marker_comments), 2)
    canonical, duplicates = elect_canonical_comment(marker_comments)
    chk("dedupe.elects_lowest_id", canonical["id"] if canonical else None, 2)
    chk("dedupe.duplicate_count", len(duplicates), 1)
    foreign_action = mark_comment_superseded(
        "acme", "widgets", {"id": 5, "body": body, "user": {"login": "someone-else"}},
        own_login="bot-a",
    )
    chk("dedupe.never_touches_foreign_author", foreign_action["action"], "skipped_foreign_author")

    ok = all(checks)
    print("selftest: %s (%d/%d) github-lifecycle" % ("PASS" if ok else "FAIL", sum(checks), len(checks)))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="github_lifecycle")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_render = sub.add_parser("render")
    p_render.add_argument("--state", required=True, choices=list(LIFECYCLE_STATES))
    p_render.add_argument("--run-id", required=True)
    p_render.add_argument("--attempt-id", required=True)
    p_render.add_argument("--goal", default="")
    p_render.set_defaults(func=cmd_render)

    p_publish = sub.add_parser("publish")
    p_publish.add_argument("--owner", required=True)
    p_publish.add_argument("--repo", required=True)
    p_publish.add_argument("--issue", required=True)
    p_publish.add_argument("--state", required=True, choices=list(LIFECYCLE_STATES))
    p_publish.add_argument("--run-id", required=True)
    p_publish.add_argument("--attempt-id", required=True)
    p_publish.add_argument("--fencing-token", default="")
    p_publish.add_argument("--goal", default="")
    p_publish.add_argument("--run-dir", default="",
                           help="if given, persist the receipt to <run-dir>/%s for the "
                                "completion oracle to read" % "github-lifecycle-receipt.json")
    p_publish.set_defaults(func=cmd_publish)

    p_list_ready = sub.add_parser("list-ready")
    p_list_ready.add_argument("--owner", required=True)
    p_list_ready.add_argument("--repo", required=True)
    p_list_ready.add_argument("--state", default="open")
    p_list_ready.add_argument("--labels", default="")
    p_list_ready.add_argument("--assignee", default="")
    p_list_ready.add_argument("--milestone", default="")
    p_list_ready.set_defaults(func=cmd_list_ready)

    p_details = sub.add_parser("get-details")
    p_details.add_argument("--owner", required=True)
    p_details.add_argument("--repo", required=True)
    p_details.add_argument("--issue", required=True)
    p_details.set_defaults(func=cmd_get_details)

    p_requery = sub.add_parser("requery")
    p_requery.add_argument("--owner", required=True)
    p_requery.add_argument("--repo", required=True)
    p_requery.add_argument("--issue", required=True)
    p_requery.add_argument("--comment-id", default="")
    p_requery.set_defaults(func=cmd_requery)

    p_reconcile = sub.add_parser("reconcile")
    p_reconcile.add_argument("--owner", required=True)
    p_reconcile.add_argument("--repo", required=True)
    p_reconcile.add_argument("--issue", required=True)
    p_reconcile.add_argument("--operation-id", required=True)
    p_reconcile.add_argument("--outbox-dir", required=True)
    p_reconcile.add_argument("--comment-id", default="")
    p_reconcile.add_argument("--expected-body-hash", default="")
    p_reconcile.set_defaults(func=cmd_reconcile)

    p_close = sub.add_parser("close")
    p_close.add_argument("--owner", required=True)
    p_close.add_argument("--repo", required=True)
    p_close.add_argument("--issue", required=True)
    p_close.add_argument("--run-id", required=True)
    p_close.add_argument("--attempt-id", required=True)
    p_close.add_argument("--fencing-token", default="")
    p_close.add_argument("--outbox-dir", default=None)
    p_close.add_argument("--goal", default="")
    p_close.add_argument("--planning-snapshot", default="",
                         help="path to a get_details()-shaped JSON snapshot captured at "
                              "planning/claim time -- if given, a material human edit or new "
                              "human comment since then blocks the close with SOURCE_CHANGED")
    p_close.add_argument("--run-dir", default="",
                         help="if given, persist the receipt to <run-dir>/%s for the "
                              "completion oracle to read" % "github-lifecycle-receipt.json")
    p_close.set_defaults(func=cmd_close)

    p_dedupe = sub.add_parser("reconcile-duplicates")
    p_dedupe.add_argument("--owner", required=True)
    p_dedupe.add_argument("--repo", required=True)
    p_dedupe.add_argument("--issue", required=True)
    p_dedupe.add_argument("--own-login", default="",
                          help="skip the live gh-authenticated-login lookup and scope "
                               "SUPERSEDED edits to this login instead")
    p_dedupe.set_defaults(func=cmd_reconcile_duplicates)

    p_self = sub.add_parser("selftest")
    p_self.set_defaults(func=cmd_selftest)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
