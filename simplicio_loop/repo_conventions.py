"""Mine a repo's own conventions (branch scheme, commit style, PR sections, test/lint command).

The single implementation behind the `repo_conventions` extension point. It lives in the package
(not in `scripts/`) because the installed watcher needs it and `scripts/` does not ship in the
wheel; `scripts/repo_conventions.py` is the CLI over it, `watcher247/points/repo_conventions.py`
the intake point.

Every inference is a deterministic tally over `git` output and the files on disk -- model-free.
A missing/empty history is NOT a fake pass: it degrades to an honest `source="default"`
Conventional-Commits profile.
"""
import glob
import hashlib
import json
import os
import re
import subprocess

from .pr_evidence import find_pr_template

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
# Branch names that carry no convention signal -- exclude from prefix inference.
TRUNK_BRANCHES = {"main", "master", "develop", "development", "trunk", "release",
                  "staging", "production", "prod", "head", "gh-pages"}
MIN_BRANCH_SAMPLES = 3
MIN_COMMIT_SAMPLES = 8


# ---- pure inference (no I/O) ----------------------------------------------------------------

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
# command -- so generated code is checked with the tool the maintainers actually use, not a guess.
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


def discover_architecture(repo_root):
    """Find the repo's OWN architecture docs + test/lint command -- mined, not guessed.

    Pure I/O-only (no git needed), so it degrades honestly to empty lists/None on a repo with
    none of these -- never fabricates a doc or command that isn't actually there.
    """
    docs = []
    for rel in ARCHITECTURE_DOC_CANDIDATES:
        if os.path.isfile(os.path.join(repo_root, rel)):
            docs.append(rel.replace(os.sep, "/"))
    for pattern in ARCHITECTURE_DOC_GLOBS:
        for hit in sorted(glob.glob(os.path.join(repo_root, pattern))):
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


# ---- mining a repo on disk -------------------------------------------------------------------

def _git(root, args):
    try:
        r = subprocess.run(["git"] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=root)
        return r.stdout if r.returncode == 0 else None
    except FileNotFoundError:
        return None


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def profile_for_repo(root, limit=400, fetch_prs=None):
    """Mine `root` (git branches + commit subjects, docs, PR template) into one profile.

    `fetch_prs(limit)` is an optional source of merged-PR records (the CLI passes `gh`); without
    it, git alone is enough. With no git history the result is the honest default profile.
    """
    branches_raw = _git(root, ["for-each-ref", "--format=%(refname:short)",
                               "refs/remotes", "refs/heads"])
    if branches_raw is None:
        branches, subjects, prs = [], [], []
    else:
        branches = [b for b in branches_raw.splitlines() if b.strip()]
        subjects_raw = _git(root, ["log", "--no-merges", "--pretty=%s", "-n", str(limit)]) or ""
        subjects = [s for s in subjects_raw.splitlines() if s.strip()]
        prs = fetch_prs(min(limit, 100)) if fetch_prs else []

    # Static config (a hint only): does the repo DOCUMENT Conventional Commits / commitizen?
    config_hint = any(
        re.search(r"conventional[ -]?commit|commitizen|\[tool\.commitizen\]",
                  _read(os.path.join(root, rel)), re.I)
        for rel in ("CONTRIBUTING.md", "AGENTS.md", os.path.join(".github", "CONTRIBUTING.md"),
                    "pyproject.toml"))

    # The PR template's headings seed the PR-body structure when there is no merged-PR history.
    template = find_pr_template(root)
    tmpl_sections = _md_headings(_read(os.path.join(root, template))) if template else []

    return build_profile(branches, subjects, prs, config_hint=config_hint,
                         pr_template_sections=tmpl_sections,
                         architecture=discover_architecture(root))


def summary_lines(profile):
    """The compact human summary of a profile: header, branch/commit/PR scheme, architecture."""
    b, c, p = profile["branch"], profile["commit"], profile["pr"]
    arch = profile["architecture"]
    scopes = ",".join(list(c["scopes"])[:4]) or "-"
    return [
        "conventions: source=%s conf=%.2f" % (profile["source"], profile["confidence"]),
        "branch=%s%s{slug} commit=%s(scopes:%s) ticket=%s pr-sections=%d  [b=%d c=%d pr=%d]" % (
            "{type}", b["prefix_sep"], c["convention"], scopes, b["ticket_pattern"] or "-",
            len(p["body_sections"]), profile["samples"]["branches"],
            profile["samples"]["commits"], profile["samples"]["prs"]),
        "architecture: docs=%d test=%s lint=%s" % (
            len(arch["docs"]), arch["test_runner"] or "-", arch["lint_cmd"] or "-"),
    ]
