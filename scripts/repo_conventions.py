#!/usr/bin/env python3
"""simplicio-loop / simplicio-tasks — repo_conventions worker (learn the repo's own playbook).

The runnable form of the `repo_conventions` extension point. Most teams never DOCUMENT how they
name branches, write commits, or shape PRs — the pattern lives only in the git history and the
merged PRs. This worker MINES that history deterministically and emits one structured profile so
Steps 4-6 mirror the user's/company's established style instead of inventing one.

It is model-free: every inference is a terminal/regex tally over `git` (and optionally `gh`) output,
so a run is reproducible and the `selftest` proves the logic with no git and no files (same
discipline as `loop_journal`/`savings_harness`). A missing/empty history is NOT a fake pass — it
DEGRADES to an honest, clearly-labelled `source="default"` Conventional-Commits profile.

Untrusted-content note: PR titles/bodies are treated as DATA — only their heading STRUCTURE is
extracted (never executed), and the emitted profile is hash-pinned (`inputs_sha256`) so a later
turn can detect tampering. A learned convention never overrides a safety gate.

State: `.simplicio-loop/orchestrator/conventions.json` — the load-bearing profile (guard with `transform_guard`):
    {"version", "source": "history|config|default", "confidence",
     "branch": {...}, "commit": {...}, "pr": {...}, "item_type_to_branch": {...},
     "samples": {...}, "inputs_sha256"}

Verbs:
  learn     Mine `git` (branches + commit subjects) and, when present, `gh` (merged PRs) → write
            `.simplicio-loop/orchestrator/conventions.json`. Prints a compact summary line. `gh` is OPTIONAL here
            (git alone is enough); its absence degrades, never blocks.
  show      Print the current profile (computes a default if none learned yet).
  branch    Format a branch name per the learned scheme:
            `branch --type fix --slug "login timeout" [--ticket ABC-12]` -> e.g. `fix/abc-12-login-timeout`.
  commit    Format a commit subject per the learned convention:
            `commit --type fix --scope auth --subject "handle null token"` -> `fix(auth): handle null token`.
  selftest  Prove the inference + formatters deterministically — no git, no files.

Usage:
    python3 scripts/repo_conventions.py learn [--out .simplicio-loop/orchestrator/conventions.json] [--limit 400]
    python3 scripts/repo_conventions.py branch --type feat --slug "add SSO" [--ticket JIRA-9]
    python3 scripts/repo_conventions.py commit --type fix --scope api --subject "retry on 503"
    python3 scripts/repo_conventions.py show [--json]
    python3 scripts/repo_conventions.py selftest
"""
import json
import os
import re
import subprocess
import sys

try:  # Windows consoles default to cp1252 and choke on non-ASCII — force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(REPO, ".simplicio-loop/orchestrator", "conventions.json")

# The inference lives in the package (the wheel ships it, `scripts/` does not); this file is the CLI.
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from simplicio_loop.repo_conventions import (  # noqa: E402
    CC_TYPES, build_profile, discover_architecture, profile_for_repo, summary_lines,
)


def log(msg):
    print("  " + msg)


def _gh_merged_prs(limit):
    """Optional: merged-PR title/head/labels/body via `gh`. [] when gh is absent/unauthed."""
    try:
        r = subprocess.run(
            ["gh", "pr", "list", "--state", "merged", "--limit", str(limit),
             "--json", "title,headRefName,labels,body"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO)
    except FileNotFoundError:
        return []
    if r.returncode != 0:
        return []
    try:
        return json.loads(r.stdout or "[]")
    except ValueError:
        return []


# ---- default profile (inference: simplicio_loop.repo_conventions) ---------------------------------

def default_profile():
    return build_profile([], [], [], architecture=discover_architecture(REPO))


# ---- formatters (deterministic apply — Steps 4-6 call these, never an LLM) ------------------

def slugify(text, sep="-"):
    s = re.sub(r"[^a-zA-Z0-9]+", sep, (text or "").strip().lower())
    return s.strip(sep) or "change"


def resolve_type(profile, type_):
    """Map an item-type alias (e.g. 'bug', 'feature') onto a branch/commit type.

    A valid Conventional-Commits type is ALWAYS honored as-is — even if the repo's history
    never happened to use it (a conventional repo accepts the whole CC vocabulary). Only an
    UNKNOWN, non-CC alias falls back to the repo's dominant type ('fix', else first learned).
    """
    t = (type_ or "").strip().lower()
    t = profile.get("item_type_to_branch", {}).get(t, t)
    if t in CC_TYPES:
        return t
    vocab = profile["branch"]["types"]
    if "fix" in vocab:
        return "fix"
    return vocab[0] if vocab else "fix"


def format_branch(profile, type_, slug, ticket=None):
    b = profile["branch"]
    t = resolve_type(profile, type_)
    core = slugify(slug, b["slug_sep"])
    if b.get("has_ticket") and ticket:
        core = "%s%s%s" % (ticket.strip().upper(), b["slug_sep"], core)
    return "%s%s%s" % (t, b["prefix_sep"], core)


def format_commit(profile, type_, subject, scope=None):
    c = profile["commit"]
    subject = (subject or "").strip()
    if c["convention"] != "conventional":
        return subject
    t = resolve_type(profile, type_)
    head = "%s(%s)" % (t, scope.strip()) if scope else t
    return "%s: %s" % (head, subject)


# ---- verbs ---------------------------------------------------------------------------------

def _load_profile(out):
    if os.path.exists(out):
        try:
            with open(out, encoding="utf-8") as f:
                return json.load(f)
        except (ValueError, OSError):
            pass
    return default_profile()


def cmd_learn(opts):
    out = opts.get("out", DEFAULT_OUT)
    limit = int(opts.get("limit", 400))
    profile = profile_for_repo(REPO, limit, fetch_prs=_gh_merged_prs)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
        f.write("\n")

    header, scheme, architecture = summary_lines(profile)
    print("learned")
    log("%s -> %s" % (header, out))
    log(scheme)
    log(architecture)


def cmd_show(opts):
    profile = _load_profile(opts.get("out", DEFAULT_OUT))
    if opts.get("json"):
        print(json.dumps(profile, indent=2, ensure_ascii=False))
        return
    b, c = profile["branch"], profile["commit"]
    print("conventions: source=%s conf=%.2f" % (profile["source"], profile["confidence"]))
    log("branch: %s%s{slug}  types=%s  ticket=%s" % (
        "{type}", b["prefix_sep"], ",".join(b["types"]) or "-", b["ticket_pattern"] or "-"))
    log("commit: %s  scopes=%s  subject_max=%d" % (
        c["convention"], ",".join(list(c["scopes"])[:6]) or "-", c["subject_max"]))
    arch = profile.get("architecture") or {"docs": [], "test_runner": None, "lint_cmd": None}
    log("architecture: docs=%s test=%s lint=%s" % (
        ",".join(arch["docs"]) or "-", arch["test_runner"] or "-", arch["lint_cmd"] or "-"))


def cmd_branch(opts):
    profile = _load_profile(opts.get("out", DEFAULT_OUT))
    name = format_branch(profile, opts.get("type", "fix"),
                         opts.get("slug", ""), opts.get("ticket"))
    print(name)


def cmd_commit(opts):
    profile = _load_profile(opts.get("out", DEFAULT_OUT))
    head = format_commit(profile, opts.get("type", "fix"),
                         opts.get("subject", ""), opts.get("scope"))
    print(head)


def cmd_selftest(_opts):
    checks = []

    def chk(name, got, want):
        ok = got == want
        checks.append(ok)
        print("  [%s] %-26s got=%r want=%r" % ("ok" if ok else "XX", name, got, want))

    # history with a clear feat/fix + JIRA pattern -> source=history, ticket detected
    branches = ["origin/main", "feat/JIRA-12-add-sso", "fix/JIRA-15-null-token",
                "feat/JIRA-20-export-csv", "fix/JIRA-22-retry", "chore/JIRA-30-bump"]
    subjects = ["feat(auth): add SSO", "fix(api): retry on 503", "fix(auth): handle null token",
                "docs: update readme", "feat(export): csv writer", "chore(deps): bump lib",
                "refactor(core): split module", "fix(ui): button align"]
    prof = build_profile(branches, subjects, [])
    chk("history.source", prof["source"], "history")
    chk("history.ticket", prof["branch"]["has_ticket"], True)
    chk("commit.conventional", prof["commit"]["convention"], "conventional")
    chk("commit.top_scope", next(iter(prof["commit"]["scopes"])), "auth")
    chk("branch.format", format_branch(prof, "feature", "Add Reports", "JIRA-99"),
        "feat/JIRA-99-add-reports")
    chk("branch.alias_bug", format_branch(prof, "bug", "fix login").split("/")[0], "fix")
    chk("commit.format", format_commit(prof, "fix", "handle 503", scope="api"),
        "fix(api): handle 503")

    # sparse/plain history -> honest default fallback, NOT an over-fit guess
    weak = build_profile(["main", "tmp"], ["wip", "stuff", "more"], [])
    chk("weak.source", weak["source"], "default")
    chk("weak.default_conv", weak["commit"]["convention"], "conventional")
    chk("weak.no_ticket", weak["branch"]["has_ticket"], False)
    chk("default.branch", format_branch(default_profile(), "feature", "My Thing"),
        "feat/my-thing")
    chk("default.commit_plain_subject",
        format_commit(default_profile(), "docs", "tidy", scope=None), "docs: tidy")
    chk("slugify.clean", slugify("Hello,  World!!"), "hello-world")

    # the default profile must honor the FULL Conventional-Commits vocab, not coerce to 'fix'
    chk("default.commit_ci", format_commit(default_profile(), "ci", "fix workflow"),
        "ci: fix workflow")
    chk("default.commit_perf", format_commit(default_profile(), "perf", "speed up"),
        "perf: speed up")
    chk("default.branch_perf", format_branch(default_profile(), "perf", "speed up loop"),
        "perf/speed-up-loop")
    # a repo-valid explicit commit type survives even when the BRANCH vocab differs
    prof_split = build_profile(["feat/a", "feat/b", "feat/c", "feat/d"],
                               ["fix: a", "fix: b", "fix: c", "fix: d",
                                "fix: e", "fix: f", "fix: g", "fix: h"], [])
    chk("vocab.commit_independent", format_commit(prof_split, "fix", "do x"), "fix: do x")
    # PR-template headings seed body sections when there is no merged-PR history
    tmpl = build_profile([], [], [], pr_template_sections=["What", "Why", "How to test"])
    chk("pr_template.sections", tmpl["pr"]["body_sections"], ["What", "Why", "How to test"])
    # a null PR title (explicit JSON null) must not crash inference
    chk("null_title.safe",
        build_profile([], [], [{"title": None, "body": None, "labels": None}])["source"],
        "default")

    # architecture discovery: an empty dir has no signal (honest empty, never fabricated)
    import tempfile
    with tempfile.TemporaryDirectory() as empty_dir:
        arch = discover_architecture(empty_dir)
        chk("architecture.empty_docs", arch["docs"], [])
        chk("architecture.empty_test_runner", arch["test_runner"], None)
        chk("architecture.empty_lint_cmd", arch["lint_cmd"], None)

    # architecture discovery: a repo carrying its own docs + Makefile targets is found, not guessed
    with tempfile.TemporaryDirectory() as fixture_dir:
        with open(os.path.join(fixture_dir, "ARCHITECTURE.md"), "w") as f:
            f.write("# Architecture\n")
        with open(os.path.join(fixture_dir, "Makefile"), "w") as f:
            f.write("test:\n\tpytest\nlint:\n\truff check .\n")
        arch = discover_architecture(fixture_dir)
        chk("architecture.found_doc", arch["docs"], ["ARCHITECTURE.md"])
        chk("architecture.found_test_runner", arch["test_runner"], "make test")
        chk("architecture.found_lint_cmd", arch["lint_cmd"], "make lint")

    ok = all(checks)
    print("repo_conventions selftest: %s (%d/%d)" % (
        "PASS" if ok else "incomplete", sum(checks), len(checks)))
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
    if argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    sub, opts = argv[0], _parse(argv[1:])
    {"learn": cmd_learn, "show": cmd_show, "branch": cmd_branch,
     "commit": cmd_commit, "selftest": cmd_selftest}.get(
        sub, lambda _o: (print("unknown command '%s'. choices: learn show branch commit selftest"
                               % sub), sys.exit(2)))(opts)


if __name__ == "__main__":
    main()
