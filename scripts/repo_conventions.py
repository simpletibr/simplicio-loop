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
import hashlib
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

# The conventional-commit type vocabulary (Angular convention + common extras).
CC_TYPES = ["build", "chore", "ci", "docs", "feat", "fix", "perf", "refactor",
            "revert", "style", "test"]
CC_RE = re.compile(
    r"^(?P<type>%s)(?P<scope>\([^)]*\))?(?P<bang>!)?:\s" % "|".join(CC_TYPES), re.I)
# A ticket id like JIRA-123 / ABC-9 (project key + number).
TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
# Branch prefixes that map onto a commit/work type.
BRANCH_PREFIX_ALIASES = {
    "feature": "feat", "feat": "feat", "feats": "feat",
    "fix": "fix", "bugfix": "fix", "hotfix": "fix", "bug": "fix",
    "chore": "chore", "docs": "docs", "doc": "docs", "refactor": "refactor",
    "test": "test", "tests": "test", "ci": "ci", "build": "build",
    "perf": "perf", "style": "style", "release": "chore",
}
# Item-type (issue/card label) -> branch/commit type. Used by `branch` when given an alias.
DEFAULT_ITEM_MAP = {
    "bug": "fix", "defect": "fix", "regression": "fix", "security": "fix",
    "feature": "feat", "enhancement": "feat", "story": "feat", "epic": "feat",
    "task": "chore", "chore": "chore", "maintenance": "chore",
    "docs": "docs", "documentation": "docs",
    "refactor": "refactor", "test": "test", "ci": "ci", "build": "build",
    "performance": "perf", "perf": "perf",
}
# Branch names that carry no convention signal — exclude from prefix inference.
TRUNK_BRANCHES = {"main", "master", "develop", "development", "trunk", "release",
                  "staging", "production", "prod", "head", "gh-pages"}
MIN_BRANCH_SAMPLES = 3
MIN_COMMIT_SAMPLES = 8


def log(msg):
    print("  " + msg)


def _git(args):
    try:
        r = subprocess.run(["git"] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=REPO)
        return r.stdout if r.returncode == 0 else None
    except FileNotFoundError:
        return None


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


# ---- pure inference (no I/O — the selftest exercises THESE) ---------------------------------

def _dominant_sep(texts, seps=("-", "_")):
    """Which separator dominates inside slugs (kebab vs snake)."""
    counts = {s: sum(t.count(s) for t in texts) for s in seps}
    return max(counts, key=counts.get) if any(counts.values()) else "-"


def infer_branch(branch_names):
    """Branch short-names -> scheme profile. Pure."""
    considered, prefixed, types, tails = 0, 0, {}, []
    has_ticket = 0
    for raw in branch_names:
        name = raw.strip().split("/", 1)
        if len(name) == 2 and name[0] in ("origin", "remotes"):
            raw = name[1] if name[0] == "origin" else raw.split("/", 1)[1]
        raw = raw.strip()
        if not raw or raw.lower() in TRUNK_BRANCHES:
            continue
        considered += 1
        if TICKET_RE.search(raw):
            has_ticket += 1
        if "/" in raw:
            prefix, tail = raw.split("/", 1)
            t = BRANCH_PREFIX_ALIASES.get(prefix.lower())
            if t:
                prefixed += 1
                types[t] = types.get(t, 0) + 1
                tails.append(tail)
    conf = (prefixed / considered) if considered else 0.0
    slug_sep = _dominant_sep(tails) if tails else "-"
    return {
        "prefix_sep": "/",
        "slug_sep": slug_sep,
        "types": sorted(types, key=lambda k: -types[k]),
        "type_counts": types,
        "has_ticket": considered > 0 and has_ticket >= max(1, considered // 2),
        "ticket_pattern": TICKET_RE.pattern if has_ticket else None,
        "confidence": round(conf, 3),
        "samples": considered,
    }


def _percentile(values, q):
    if not values:
        return 0
    s = sorted(values)
    idx = min(len(s) - 1, int(round((q / 100.0) * (len(s) - 1))))
    return s[idx]


def infer_commit(subjects):
    """Commit subjects -> convention profile. Pure."""
    total, conv, types, scopes, ticketed, lengths = 0, 0, {}, {}, 0, []
    for s in subjects:
        s = s.strip()
        if not s:
            continue
        total += 1
        lengths.append(len(s))
        if TICKET_RE.search(s):
            ticketed += 1
        m = CC_RE.match(s)
        if m:
            conv += 1
            t = m.group("type").lower()
            types[t] = types.get(t, 0) + 1
            sc = m.group("scope")
            if sc:
                name = sc.strip("()").strip()
                if name:
                    scopes[name] = scopes.get(name, 0) + 1
    conf = (conv / total) if total else 0.0
    subject_max = max(50, min(72, _percentile(lengths, 90))) if lengths else 72
    return {
        "convention": "conventional" if conf >= 0.6 else "plain",
        "types": types,
        "scopes": dict(sorted(scopes.items(), key=lambda kv: -kv[1])),
        "ticket_in_subject": total > 0 and ticketed >= max(1, total // 2),
        "subject_max": int(subject_max),
        "confidence": round(conf, 3),
        "samples": total,
    }


def _md_headings(text):
    """Ordered markdown H1-H3 heading texts (PR-body / template section STRUCTURE only)."""
    out = []
    for line in (text or "").splitlines():
        hm = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if hm:
            out.append(hm.group(1).strip())
    return out


ARCHITECTURE_DOC_CANDIDATES = [
    "ARCHITECTURE.md", "DESIGN.md", os.path.join("docs", "ARCHITECTURE.md"),
    os.path.join("docs", "DESIGN.md"), os.path.join(".specs", "architecture", "DESIGN.md"),
    os.path.join(".specs", "architecture", "PATTERNS.md"), os.path.join(".specs", "README.md"),
    "CONTRIBUTING.md", "AGENTS.md",
]
ARCHITECTURE_DOC_GLOBS = [
    os.path.join(".specs", "architecture", "ADR-*.md"),
    os.path.join("docs", "adr", "*.md"),
    os.path.join("docs", "architecture", "*.md"),
]
# Makefile/package.json/pyproject.toml targets that name the project's OWN test/lint/typecheck
# command — so generated code is checked with the tool the maintainers actually use, not a guess.
TEST_RUNNER_CANDIDATES = [
    (os.path.join("scripts", "check.py"), "python3 scripts/check.py"),
    (os.path.join("scripts", "run_tests.sh"), "bash scripts/run_tests.sh"),
    ("Makefile", None),  # parsed for a `test:` target below
    ("package.json", None),  # parsed for scripts.test below
    ("pyproject.toml", "pytest"),
]
LINT_CANDIDATES = [
    ("Makefile", None),  # parsed for a `lint:` target below
    ("package.json", None),  # parsed for scripts.lint below
    (".eslintrc.json", "eslint ."), (".eslintrc.js", "eslint ."), (".eslintrc", "eslint ."),
    ("ruff.toml", "ruff check ."), (".ruff.toml", "ruff check ."),
    ("setup.cfg", "flake8"),
]


def _makefile_target(repo_root, target):
    mk = os.path.join(repo_root, "Makefile")
    if not os.path.exists(mk):
        return None
    try:
        with open(mk, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    if re.search(r"^%s:" % re.escape(target), text, re.M):
        return "make %s" % target
    return None


def _package_json_script(repo_root, script):
    pj = os.path.join(repo_root, "package.json")
    if not os.path.exists(pj):
        return None
    try:
        with open(pj, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and script in (data.get("scripts") or {}):
        return "npm run %s" % script
    return None


def discover_architecture(repo_root=REPO):
    """Find the repo's OWN architecture docs + test/lint command — mined, not guessed.

    Pure I/O-only (no git needed), so it degrades honestly to empty lists/None on a repo with
    none of these — never fabricates a doc or command that isn't actually there.
    """
    import glob as _glob

    docs = []
    for rel in ARCHITECTURE_DOC_CANDIDATES:
        if os.path.isfile(os.path.join(repo_root, rel)):
            docs.append(rel.replace(os.sep, "/"))
    for pattern in ARCHITECTURE_DOC_GLOBS:
        for hit in sorted(_glob.glob(os.path.join(repo_root, pattern))):
            docs.append(os.path.relpath(hit, repo_root).replace(os.sep, "/"))

    test_runner = _makefile_target(repo_root, "test") or _package_json_script(repo_root, "test")
    if not test_runner:
        for rel, cmd in TEST_RUNNER_CANDIDATES:
            if cmd and os.path.isfile(os.path.join(repo_root, rel)):
                test_runner = cmd
                break

    lint_cmd = _makefile_target(repo_root, "lint") or _package_json_script(repo_root, "lint")
    if not lint_cmd:
        for rel, cmd in LINT_CANDIDATES:
            if cmd and os.path.isfile(os.path.join(repo_root, rel)):
                lint_cmd = cmd
                break

    return {"docs": docs, "test_runner": test_runner, "lint_cmd": lint_cmd}


def infer_pr(prs):
    """Merged-PR records -> title convention + label vocab + body section structure. Pure."""
    titles = [(p.get("title") or "") for p in prs]
    conv = sum(1 for t in titles if CC_RE.match(t.strip()))
    labels, sections = {}, {}
    for p in prs:
        for lb in p.get("labels", []) or []:
            nm = lb.get("name") if isinstance(lb, dict) else str(lb)
            if nm:
                labels[nm] = labels.get(nm, 0) + 1
        for sec in _md_headings(p.get("body", "")):
            sections[sec] = sections.get(sec, 0) + 1
    return {
        "convention": "conventional" if (titles and conv >= len(titles) * 0.6) else "plain",
        "labels": [k for k, _ in sorted(labels.items(), key=lambda kv: -kv[1])][:20],
        "body_sections": [k for k, _ in sorted(sections.items(), key=lambda kv: -kv[1])][:10],
        "samples": len(prs),
    }


def build_profile(branch_names, subjects, prs, config_hint=False, pr_template_sections=None,
                  architecture=None):
    """Aggregate the three signals into one profile + decide source/confidence. Pure."""
    b = infer_branch(branch_names)
    c = infer_commit(subjects)
    p = infer_pr(prs)
    # No merged-PR history to learn sections from? Fall back to the repo's PR TEMPLATE structure.
    if not p["body_sections"] and pr_template_sections:
        p["body_sections"] = list(pr_template_sections)[:10]
    samples_ok = b["samples"] >= MIN_BRANCH_SAMPLES or c["samples"] >= MIN_COMMIT_SAMPLES
    if samples_ok:
        overall = max(b["confidence"], c["confidence"])
    else:
        overall = round(min(b["confidence"], c["confidence"]) * 0.5, 3)

    if overall >= 0.5 and samples_ok:
        source = "history"
    elif config_hint:
        source = "config"
    else:
        source = "default"

    if source != "history":
        # Honest fallback: a clean Conventional-Commits default, not an over-fit guess.
        b = {"prefix_sep": "/", "slug_sep": "-",
             "types": list(CC_TYPES),
             "type_counts": {}, "has_ticket": False, "ticket_pattern": None,
             "confidence": b["confidence"], "samples": b["samples"]}
        c = {"convention": "conventional", "types": c["types"], "scopes": c["scopes"],
             "ticket_in_subject": False, "subject_max": c["subject_max"],
             "confidence": c["confidence"], "samples": c["samples"]}

    item_map = dict(DEFAULT_ITEM_MAP)
    vocab = set(b["types"]) | set(c["types"])
    if vocab:  # only map onto types the repo actually uses; else keep the safe default map
        for k, v in list(item_map.items()):
            if v not in vocab:
                item_map[k] = "fix" if "fix" in vocab else (b["types"][0] if b["types"] else v)

    blob = "\n".join(sorted(branch_names) + sorted(subjects) +
                     [(pr.get("title") or "") for pr in prs]).encode("utf-8")
    return {
        "version": 1,
        "source": source,
        "confidence": overall,
        "branch": b,
        "commit": c,
        "pr": p,
        "item_type_to_branch": item_map,
        "samples": {"branches": b["samples"], "commits": c["samples"], "prs": p["samples"]},
        "architecture": architecture or {"docs": [], "test_runner": None, "lint_cmd": None},
        "inputs_sha256": hashlib.sha256(blob).hexdigest(),
    }


def default_profile():
    return build_profile([], [], [], architecture=discover_architecture())


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
    branches_raw = _git(["for-each-ref", "--format=%(refname:short)",
                         "refs/remotes", "refs/heads"])
    if branches_raw is None:
        log("! no git history available — emitting an honest default Conventional-Commits profile")
        branches, subjects, prs = [], [], []
    else:
        branches = [b for b in branches_raw.splitlines() if b.strip()]
        subjects_raw = _git(["log", "--no-merges", "--pretty=%s", "-n", str(limit)]) or ""
        subjects = [s for s in subjects_raw.splitlines() if s.strip()]
        prs = _gh_merged_prs(min(limit, 100))

    # Static config (a hint only): does the repo DOCUMENT Conventional Commits / commitizen?
    config_hint = False
    for rel in ("CONTRIBUTING.md", "AGENTS.md", os.path.join(".github", "CONTRIBUTING.md"),
                "pyproject.toml"):
        cp = os.path.join(REPO, rel)
        if not os.path.exists(cp):
            continue
        try:
            with open(cp, encoding="utf-8", errors="replace") as f:
                if re.search(r"conventional[ -]?commit|commitizen|\[tool\.commitizen\]",
                             f.read(), re.I):
                    config_hint = True
                    break
        except OSError:
            pass

    # PR template: its section headings seed the PR-body structure when there is no merged-PR
    # history to learn from (so a freshly-mined repo still fills PRs in the maintainer's format).
    tmpl_sections = []
    for rel in (os.path.join(".github", "PULL_REQUEST_TEMPLATE.md"),
                os.path.join(".github", "pull_request_template.md"),
                "PULL_REQUEST_TEMPLATE.md"):
        tp = os.path.join(REPO, rel)
        if os.path.exists(tp):
            try:
                with open(tp, encoding="utf-8", errors="replace") as f:
                    tmpl_sections = _md_headings(f.read())
            except OSError:
                tmpl_sections = []
            if tmpl_sections:
                break

    architecture = discover_architecture()
    profile = build_profile(branches, subjects, prs, config_hint=config_hint,
                            pr_template_sections=tmpl_sections, architecture=architecture)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
        f.write("\n")

    b, c, p = profile["branch"], profile["commit"], profile["pr"]
    scopes = ",".join(list(c["scopes"])[:4]) or "-"
    ticket = b["ticket_pattern"] or "-"
    print("learned")
    log("conventions: source=%s conf=%.2f -> %s" % (
        profile["source"], profile["confidence"], out))
    log("branch=%s%s{slug} commit=%s(scopes:%s) ticket=%s pr-sections=%d  [b=%d c=%d pr=%d]" % (
        "{type}", b["prefix_sep"], c["convention"], scopes, ticket,
        len(p["body_sections"]), profile["samples"]["branches"],
        profile["samples"]["commits"], profile["samples"]["prs"]))
    log("architecture: docs=%d test=%s lint=%s" % (
        len(architecture["docs"]), architecture["test_runner"] or "-",
        architecture["lint_cmd"] or "-"))


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
