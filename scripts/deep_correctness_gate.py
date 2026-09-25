#!/usr/bin/env python3
"""simplicio-loop — deep-correctness gate (issue #579, DOD.md Layer 1 + Layer 2).

Two real bugs (see `DOD.md`'s "Why this exists") slipped through repos that already had a
documented 7-pillar Definition of Done and green CI: a `mechanical_edit.py` plan applied out of
order while reporting `"status": "ok"`, and a `mapper/graph.py` regex silently reporting the
wrong line number on the single most common PEP8 pattern in existence. Neither is the kind of gap
a code review catches by vibes — both are mechanically checkable, cheaply, if anyone asks the
right question at the right time.

This worker asks three of those questions, mechanically, against a diff/PR — the subset of
`DOD.md`'s Layer 1 (universal) + Layer 2 (risk-surface) that is actually automatable today without
inventing a fuzzing harness or a cross-repo contract-test framework (those are real, but bigger
than one script — tracked as follow-up in issue #579, not faked here):

  1. **Regression test on a fix (DOD.md 1.3)** — if any commit message in the range being checked
     is a Conventional-Commits `fix:`/`fix(scope):`, the diff must contain a hunk that ADDS lines
     to a test-shaped file (`tests?/`, `spec/`, `__tests__/`, `test_*`, `*_test`, `*.test.*`,
     `*.spec.*`). A bug fix with no accompanying test is exactly how the dev-cli bug's silent
     corruption would have gone unnoticed a second time.
  2. **Invariant question answered (DOD.md 2.3)** — when a PR body is supplied, it must contain a
     non-empty `## Invariant(e)` section. This is a presence check, not a correctness judgment: it
     proves the question "do these two functions use the same granularity/partitioning key?" was
     asked and answered, not silently skipped. No PR body supplied -> not applicable, not a
     failure (this worker is also usable diff-only, e.g. from a local pre-push hook).
  3. **Coverage gate enforced in CI (DOD.md 1.4)** — the TARGET repo's `.github/workflows/*.yml`
     must contain a real coverage-gate signal (`--cov-fail-under`, `coverage_gate.py`,
     `codecov-action`, `--cov=`, ...), not merely a coverage percentage asserted in a doc that
     nobody re-checks.

Diff + commit messages can be supplied explicitly (`--diff`, `--commit-msg`, repeatable) or
derived from git directly (`--base-ref origin/main` diffs/logs `base...HEAD` inside
`--repo-root`). Explicit flags win over derived values when both are given.

Stdlib only. Deterministic. No network. Exit 0 when every applicable check passes, 1 otherwise —
gates a commit/push the same way `scripts/claims_audit.py` and `scripts/coverage_gate.py` do.

Usage:
    python3 scripts/deep_correctness_gate.py check --repo-root /path/to/target/repo \\
        --base-ref origin/main --pr-body @pr_body.md
    python3 scripts/deep_correctness_gate.py check --repo-root . \\
        --commit-msg "fix: stop corrupting multi-file edit plans" --diff @change.diff --json
    python3 scripts/deep_correctness_gate.py selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

FIX_COMMIT_RE = re.compile(r"^fix(\([^)]*\))?(!)?:\s*\S", re.I)

TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|spec|__tests__)/"      # under a tests/, test/, spec/, __tests__/ dir
    r"|(^|/)test_[\w.-]+\.\w+$"           # test_foo.py
    r"|(^|/)[\w.-]+_test\.\w+$"           # foo_test.go
    r"|(^|/)[\w.-]+\.test\.\w+$"          # foo.test.ts
    r"|(^|/)[\w.-]+\.spec\.\w+$",         # foo.spec.ts
    re.I,
)

INVARIANT_HEADER_RE = re.compile(r"^#{1,4}\s*invariant(e)?s?\b.*$", re.I | re.M)
NEXT_HEADER_RE = re.compile(r"^#{1,6}\s+\S", re.M)

COVERAGE_GATE_SIGNAL_RE = re.compile(
    r"cov-fail-under|coverage[-_]gate\.py|codecov(?:-action)?|--cov(?:=|\b)|pytest-cov|cov-report",
    re.I,
)


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _resolve_text_arg(value):
    """`--flag @path` reads a file; anything else is used literally. Mirrors pr_dod_review.py."""
    if value and value.startswith("@"):
        return _read(value[1:])
    return value or ""


def _git(args, cwd):
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return r.returncode, r.stdout, r.stderr
    except OSError as e:
        return 1, "", str(e)


def derive_from_git(repo_root, base_ref):
    """Diff text + commit subject lines for `base_ref...HEAD` inside `repo_root`. Best-effort:
    a repo_root that isn't a git repo, or a base_ref that doesn't resolve, yields empty results
    rather than raising — callers fall back to whatever was passed explicitly."""
    rc, out, _err = _git(["diff", "%s...HEAD" % base_ref], repo_root)
    diff_text = out if rc == 0 else ""
    rc2, out2, _err2 = _git(["log", "%s..HEAD" % base_ref, "--format=%s"], repo_root)
    commit_msgs = [ln for ln in out2.splitlines() if ln.strip()] if rc2 == 0 else []
    return diff_text, commit_msgs


def parse_diff_file_blocks(diff_text):
    """Split a unified diff into (path, added_lines) per touched file, from `+++ b/<path>`
    headers onward. Deliberately simple (stdlib-only, no diff library): good enough to tell
    "a test file received new content" from "a test file was only touched/deleted"."""
    blocks = []
    current_path = None
    current_added = []
    for line in diff_text.splitlines():
        m = re.match(r"^\+\+\+ b/(.+)$", line)
        if m:
            if current_path is not None:
                blocks.append((current_path, current_added))
            current_path = m.group(1)
            current_added = []
            continue
        if current_path is not None and line.startswith("+") and not line.startswith("+++"):
            current_added.append(line[1:])
    if current_path is not None:
        blocks.append((current_path, current_added))
    return blocks


def check_regression_test(commit_msgs, diff_text):
    """DOD.md 1.3 — a `fix:` commit must be accompanied by a test file receiving added lines."""
    is_fix = any(FIX_COMMIT_RE.match(m.strip()) for m in commit_msgs)
    if not is_fix:
        return True, "no 'fix:' commit in range — regression-test check not applicable", {
            "applicable": False}
    if not diff_text.strip():
        return False, ("a 'fix:' commit was found but no diff text was supplied — cannot verify "
                        "a regression test was added"), {"applicable": True, "test_files_touched": []}
    blocks = parse_diff_file_blocks(diff_text)
    touched = [p for p, _added in blocks if TEST_PATH_RE.search(p)]
    with_added_lines = [p for p, added in blocks
                        if TEST_PATH_RE.search(p) and any(ln.strip() for ln in added)]
    if not with_added_lines:
        return False, (
            "a 'fix:' commit was found but no test-shaped file received added lines in the "
            "diff — a bug fix with no regression test that would have caught it (test files "
            "touched with no added content: %s)" % (", ".join(touched) or "(none)")
        ), {"applicable": True, "test_files_touched": touched}
    return True, "fix: commit accompanied by test changes: %s" % ", ".join(with_added_lines), {
        "applicable": True, "test_files_touched": with_added_lines}


def _extract_section(text, header_re):
    m = header_re.search(text)
    if m is None:
        return None
    rest = text[m.end():]
    m2 = NEXT_HEADER_RE.search(rest)
    body = rest[:m2.start()] if m2 else rest
    return body.strip()


def check_invariant_answer(pr_body):
    """DOD.md 2.3 — presence, not correctness: an explicit '## Invariant(e)' section answered."""
    if not pr_body or not pr_body.strip():
        return True, "no PR body supplied — invariant-question check skipped", {"applicable": False}
    section = _extract_section(pr_body, INVARIANT_HEADER_RE)
    if section is None:
        return False, (
            "PR body has no '## Invariant(e)' section — issue #579's invariant-review question "
            "('do these two functions use the same granularity/partitioning key?') was not "
            "answered, explicitly or as 'n/a'"
        ), {"applicable": True}
    if len(section) < 2:
        return False, "PR body has an '## Invariant(e)' section but it is empty", {
            "applicable": True}
    return True, "invariant question answered: %r" % section[:120], {
        "applicable": True, "answer": section}


def check_coverage_gate_workflow(repo_root):
    """DOD.md 1.4 — a real coverage threshold must run in CI, not just be quoted in a doc."""
    wf_dir = os.path.join(repo_root, ".github", "workflows")
    if not os.path.isdir(wf_dir):
        return False, "no .github/workflows/ directory found under --repo-root", {
            "applicable": True, "workflows_scanned": []}
    scanned = []
    hits = []
    for name in sorted(os.listdir(wf_dir)):
        if not name.endswith((".yml", ".yaml")):
            continue
        scanned.append(name)
        try:
            text = _read(os.path.join(wf_dir, name))
        except OSError:
            continue
        if COVERAGE_GATE_SIGNAL_RE.search(text):
            hits.append(name)
    if not scanned:
        return False, "no workflow files (*.yml/*.yaml) found under .github/workflows/", {
            "applicable": True, "workflows_scanned": []}
    if not hits:
        return False, (
            "no coverage-gate signal found in any workflow (%s) — a coverage threshold must run "
            "in CI, not just be documented" % ", ".join(scanned)
        ), {"applicable": True, "workflows_scanned": scanned}
    return True, "coverage-gate signal found in: %s" % ", ".join(hits), {
        "applicable": True, "workflows_scanned": scanned, "workflows_with_gate": hits}


def build_verdict(repo_root, commit_msgs, diff_text, pr_body):
    checks = []
    for check_id, ok, detail, meta in (
        ("layer1.regression_test_on_fix",) + check_regression_test(commit_msgs, diff_text),
        ("layer2.invariant_question_answered",) + check_invariant_answer(pr_body),
        ("layer1.coverage_gate_in_ci",) + check_coverage_gate_workflow(repo_root),
    ):
        entry = {"id": check_id, "ok": ok, "detail": detail}
        entry.update(meta)
        checks.append(entry)
    ok = all(c["ok"] for c in checks)
    return {
        "schema": "simplicio.deep-correctness-gate/v1",
        "ok": ok,
        "checks": checks,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def render_text(verdict):
    lines = []
    for c in verdict["checks"]:
        lines.append("[%s] %s — %s" % ("ok" if c["ok"] else "XX", c["id"], c["detail"]))
    lines.append("deep-correctness-gate: %s" % ("PASS" if verdict["ok"] else "FAIL"))
    return "\n".join(lines)


def cmd_check(args):
    diff_text = args.diff_text
    commit_msgs = args.commit_msgs
    if args.base_ref and (not diff_text or not commit_msgs):
        derived_diff, derived_msgs = derive_from_git(args.repo_root, args.base_ref)
        diff_text = diff_text or derived_diff
        commit_msgs = commit_msgs or derived_msgs
    verdict = build_verdict(args.repo_root, commit_msgs, diff_text, args.pr_body)
    if args.json:
        print(json.dumps(verdict, indent=2, ensure_ascii=False))
    else:
        print(render_text(verdict))
    return 0 if verdict["ok"] else 1


def cmd_selftest(_args):
    checks = []

    def chk(name, got, want):
        ok = got == want
        checks.append(ok)
        print("  [%s] %-42s got=%r want=%r" % ("ok" if ok else "XX", name, got, want))

    # 1: no fix: commit -> regression-test check not applicable, passes
    ok, _detail, meta = check_regression_test(["feat: add a thing"], "")
    chk("regression.not_applicable_without_fix", (ok, meta["applicable"]), (True, False))

    # 2: fix: commit + no diff at all -> fails (cannot verify)
    ok, _detail, _meta = check_regression_test(["fix: stop corrupting the file"], "")
    chk("regression.fix_without_diff_fails", ok, False)

    # 3: fix: commit + diff touching only source, no test -> fails
    src_only_diff = (
        "diff --git a/mechanical_edit.py b/mechanical_edit.py\n"
        "+++ b/mechanical_edit.py\n"
        "+    fixed_line = True\n"
    )
    ok, _detail, meta = check_regression_test(["fix: order bug"], src_only_diff)
    chk("regression.fix_without_test_fails", ok, False)
    chk("regression.reports_touched_but_empty", meta["test_files_touched"], [])

    # 4: fix: commit + diff adding lines to a test file -> passes
    with_test_diff = (
        src_only_diff +
        "diff --git a/tests/test_mechanical_edit.py b/tests/test_mechanical_edit.py\n"
        "+++ b/tests/test_mechanical_edit.py\n"
        "+def test_multi_file_order_regression():\n"
        "+    assert True\n"
    )
    ok, _detail, meta = check_regression_test(["fix: order bug"], with_test_diff)
    chk("regression.fix_with_test_passes", ok, True)
    chk("regression.names_test_file", meta["test_files_touched"],
        ["tests/test_mechanical_edit.py"])

    # 5: a test file touched with ONLY deletions (no added lines) still fails — deleting
    # assertions is not adding a regression test.
    deletion_only_diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
    )
    ok, _detail, meta = check_regression_test(["fix: something"], deletion_only_diff)
    chk("regression.deletion_only_still_fails", ok, False)

    # 6: fix(scope)! conventional-commit variants also trigger the check
    ok, _detail, _meta = check_regression_test(["fix(mapper)!: breaking line-number fix"], "")
    chk("regression.scoped_bang_variant_triggers", ok, False)

    # 7: no PR body -> invariant check not applicable, passes
    ok, _detail, meta = check_invariant_answer("")
    chk("invariant.not_applicable_without_body", (ok, meta["applicable"]), (True, False))

    # 8: PR body with no Invariant section -> fails
    ok, _detail, _meta = check_invariant_answer("## Summary\nJust a small change.\n")
    chk("invariant.missing_section_fails", ok, False)

    # 9: PR body with an EMPTY Invariant section -> fails
    ok, _detail, _meta = check_invariant_answer("## Summary\nx\n\n## Invariant\n\n## Test plan\ny\n")
    chk("invariant.empty_section_fails", ok, False)

    # 10: PR body with a real answer (English heading) -> passes
    ok, _detail, meta = check_invariant_answer(
        "## Summary\nx\n\n## Invariant\nYes — both partition by file path.\n\n## Test plan\ny\n"
    )
    chk("invariant.answered_en_passes", ok, True)
    chk("invariant.answer_captured", "partition by file path" in meta["answer"], True)

    # 11: Portuguese heading "Invariante" also recognized
    ok, _detail, _meta = check_invariant_answer(
        "## Invariante\nNao, uma particiona por arquivo e outra pelo plano inteiro.\n"
    )
    chk("invariant.answered_pt_passes", ok, True)

    # 12: "n/a" is a valid explicit answer (not silently blank)
    ok, _detail, _meta = check_invariant_answer("## Invariant\nn/a — no dual-processing code here.\n")
    chk("invariant.na_is_a_valid_answer", ok, True)

    # 13: coverage-gate check — repo with no .github/workflows -> fails
    import tempfile
    with tempfile.TemporaryDirectory(prefix="deep_correctness_gate_selftest_") as tmp:
        ok, _detail, _meta = check_coverage_gate_workflow(tmp)
        chk("coverage.no_workflows_dir_fails", ok, False)

        # 14: workflows dir present but no yml files -> fails
        wf_dir = os.path.join(tmp, ".github", "workflows")
        os.makedirs(wf_dir)
        ok, _detail, _meta = check_coverage_gate_workflow(tmp)
        chk("coverage.empty_workflows_dir_fails", ok, False)

        # 15: a workflow with no coverage signal -> fails
        with open(os.path.join(wf_dir, "ci.yml"), "w", encoding="utf-8") as f:
            f.write("name: ci\non: push\njobs:\n  build:\n    steps:\n      - run: echo hi\n")
        ok, _detail, meta = check_coverage_gate_workflow(tmp)
        chk("coverage.no_signal_fails", ok, False)
        chk("coverage.scanned_lists_file", meta["workflows_scanned"], ["ci.yml"])

        # 16: a workflow WITH a coverage-gate signal -> passes
        with open(os.path.join(wf_dir, "ci.yml"), "w", encoding="utf-8") as f:
            f.write("name: ci\njobs:\n  build:\n    steps:\n"
                    "      - run: pytest --cov=pkg --cov-fail-under=88\n")
        ok, _detail, meta = check_coverage_gate_workflow(tmp)
        chk("coverage.signal_present_passes", ok, True)
        chk("coverage.hit_named", meta["workflows_with_gate"], ["ci.yml"])

    # 17: build_verdict aggregates ok=False when any applicable check fails
    v = build_verdict(REPO, ["fix: bug"], "", "")
    chk("verdict.aggregates_failure", v["ok"], False)
    chk("verdict.schema_tagged", v["schema"], "simplicio.deep-correctness-gate/v1")

    # 18: build_verdict is ok=True when nothing applicable (no fix:, no PR body) AND the target
    # repo's CI has a coverage gate — this repo (simplicio-loop) deliberately runs no paid CI
    # coverage gate of its own (see AGENTS.md "no paid CI"), so a fresh fixture repo proves this
    # instead of relying on REPO's own workflow tree.
    with tempfile.TemporaryDirectory(prefix="deep_correctness_gate_selftest_verdict_") as tmp2:
        wf_dir2 = os.path.join(tmp2, ".github", "workflows")
        os.makedirs(wf_dir2)
        with open(os.path.join(wf_dir2, "ci.yml"), "w", encoding="utf-8") as f:
            f.write("name: ci\njobs:\n  build:\n    steps:\n"
                    "      - run: pytest --cov=pkg --cov-fail-under=88\n")
        v2 = build_verdict(tmp2, ["feat: unrelated"], "", "")
        chk("verdict.all_inapplicable_or_passing", v2["ok"], True)

    # 19: render_text mentions PASS/FAIL and every check id
    rendered = render_text(v2)
    chk("render.has_verdict_line", "deep-correctness-gate: PASS" in rendered, True)
    chk("render.lists_all_checks", all(c["id"] in rendered for c in v2["checks"]), True)

    # 20: diff-block parser splits multiple files correctly
    blocks = parse_diff_file_blocks(with_test_diff)
    chk("parse.block_count", len(blocks), 2)
    chk("parse.first_path", blocks[0][0], "mechanical_edit.py")
    chk("parse.second_path", blocks[1][0], "tests/test_mechanical_edit.py")

    ok = all(checks)
    print("selftest: %s (%d/%d)" % ("PASS" if ok else "FAIL", sum(checks), len(checks)))
    return 0 if ok else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--describe-cli":
        print(json.dumps({
            "verbs": ["check", "selftest"],
            "flags": ["--repo-root", "--base-ref", "--diff", "--commit-msg", "--pr-body",
                      "--json", "--help"],
        }))
        return 0

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="subcommand")

    check_p = sub.add_parser("check", help="run the deep-correctness verdict")
    check_p.add_argument("--repo-root", default=".", help="target repo root (for the CI-workflow check)")
    check_p.add_argument("--base-ref", default=None,
                         help="derive diff + commit subjects via `git diff/log <ref>...HEAD`")
    check_p.add_argument("--diff", dest="diff_raw", default=None,
                         help="unified diff text, or @path to a file; overrides --base-ref-derived diff")
    check_p.add_argument("--commit-msg", dest="commit_msgs_raw", action="append", default=None,
                         help="commit subject line (repeatable); overrides --base-ref-derived subjects")
    check_p.add_argument("--pr-body", dest="pr_body_raw", default=None,
                         help="PR body text, or @path to a file")
    check_p.add_argument("--json", action="store_true")

    sub.add_parser("selftest", help="run embedded self-checks")

    args = parser.parse_args(argv)
    if args.subcommand == "selftest" or args.subcommand is None:
        if args.subcommand is None:
            parser.print_help()
            return 2
        return cmd_selftest(args)

    args.repo_root = os.path.abspath(args.repo_root)
    args.diff_text = _resolve_text_arg(args.diff_raw) if args.diff_raw else ""
    args.commit_msgs = list(args.commit_msgs_raw or [])
    args.pr_body = _resolve_text_arg(args.pr_body_raw) if args.pr_body_raw else ""
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
