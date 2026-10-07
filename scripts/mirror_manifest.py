#!/usr/bin/env python3
"""simplicio-loop — single source of truth for the "lean mirror" sets (#74).

`scripts/sync_plugin.py` (writes `plugin/`) and `scripts/claims_audit.py` (validates
`simplicio_loop/_bundle/` and `plugin/` parity) previously hard-coded the SAME lean subset of
hooks/scripts/tests independently. Editing one and forgetting the other let the syncer copy one
set while the auditor validated another — drift that passed the gate silently. This module is the
ONE place those sets are declared; both consumers import from here.

No behavior of its own — pure data, imported by `sync_plugin.py` and `claims_audit.py`.
"""

# The ONLY hook files the marketplace plugin ships: those wired in hooks.claude.json + their deps.
# loop_stop (Stop) · action_gate/orient_rewrite (PreToolUse) · orient_clamp (orient_rewrite shells
# out to it) · hooks.claude.json (the wiring) · pre-commit.py (auto-sync, #98).
LEAN_HOOKS = ["loop_stop.py", "action_gate.py", "orient_rewrite.py", "user_prompt_submit.py",
              "orient_clamp.py", "hooks.claude.json", "pre-commit.py",
              "_dashboard_emit.py"]

# Every scripts/<name>.py the simplicio-loop SKILL.md normative protocol actually shells out to,
# plus their same-directory transitive imports (_locked_append/toon_codec/agent_identity) — the
# full set, not a 2-script sample, or the shipped plugin ImportErrors at runtime (runtime#3304).
# Mirrored into both plugin/scripts/ and simplicio_loop/_bundle/scripts/.
LEAN_SCRIPTS = [
    "coordinator.py", "cross_agent_wiki.py", "delivery_contract.py", "diff_escalation.py",
    "flow_audit.py", "handoff.py", "hierarchical_planner.py", "impact_audit.py",
    "loop_journal.py", "loop_progress.py", "operator_check.py", "operator_preflight.py",
    "pr_dod_review.py", "route_mode.py", "task_anchor.py", "task_backlog.py",
    "test_infra_probe.py", "video_evidence.py", "watcher_verify.py", "web_verify.py",
    "worktree_cleanup.py", "_locked_append.py", "toon_codec.py", "agent_identity.py",
    "dashboard_events.py",
]

# Minimal parity coverage for the shipped loop/runtime helpers — mirrored into both
# plugin/tests/ and simplicio_loop/_bundle/tests/.
LEAN_TESTS = ["_selfrun.py", "test_loop_e2e.py", "test_cross_agent_wiki.py"]

# Source directories `hooks/pre-commit.py` watches for auto-sync (#98): a staged change under
# any of these triggers `scripts/sync_plugin.py` (writes `plugin/`) and `scripts/sync_bundle.py`
# (writes `simplicio_loop/_bundle/`). This is the ONLY place the watched-path list is declared —
# pre-commit.py imports it rather than hard-coding its own copy, so there is exactly one list to
# keep in sync with what the two syncers actually mirror. Directory-level (not the individual
# LEAN_* filenames) on purpose: `.claude/skills/` and `hooks/` are mirrored as full subtrees, and
# watching the whole `scripts/`/`tests/` directories (rather than enumerating just the LEAN_*
# filenames again here) is the conservative choice — it can only over-trigger a redundant sync,
# never under-trigger and miss a real drift.
WATCHED_SOURCE_DIRS = [".claude/skills", "hooks", "scripts", "tests", "adapters/claude"]


def selftest():
    checks = [
        ("LEAN_HOOKS non-empty", bool(LEAN_HOOKS)),
        ("LEAN_SCRIPTS non-empty", bool(LEAN_SCRIPTS)),
        ("LEAN_TESTS non-empty", bool(LEAN_TESTS)),
        ("LEAN_HOOKS has no dupes", len(LEAN_HOOKS) == len(set(LEAN_HOOKS))),
        ("LEAN_SCRIPTS has no dupes", len(LEAN_SCRIPTS) == len(set(LEAN_SCRIPTS))),
        ("LEAN_TESTS has no dupes", len(LEAN_TESTS) == len(set(LEAN_TESTS))),
        ("WATCHED_SOURCE_DIRS non-empty", bool(WATCHED_SOURCE_DIRS)),
        ("WATCHED_SOURCE_DIRS has no dupes",
         len(WATCHED_SOURCE_DIRS) == len(set(WATCHED_SOURCE_DIRS))),
    ]
    ok = all(v for _, v in checks)
    for name, v in checks:
        print("  [%s] %s" % ("ok" if v else "XX", name))
    print("mirror_manifest selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    print(__doc__)
