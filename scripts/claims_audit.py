#!/usr/bin/env python3
"""simplicio-loop — claims audit (turn asserted docs into checked facts; fail-closed).

The repo makes many claims in prose. This audits the mechanical ones so a doc can't drift away from
the code. Deterministic, stdlib-only, no network. Exits 0 when every check passes, 1 otherwise —
so it can gate a commit/push (`scripts/check.py`, or a git pre-push hook). NOT a GitHub Action;
runs locally, free.

Thirteen checks:
  1. referenced-scripts-exist  Every `scripts/<name>.py` mentioned in the docs actually exists.
  2. extension-point-count      Every "<N> extension points / named (binding) points" figure agrees
                                with EACH OTHER *and* with the actual row count of the extension-points
                                table in extension-points.md (the source of truth, not just consensus).
  3. cited-commands-run         Each doc-cited worker script is invokable: its `selftest` passes if
                                it has one, else it `py_compile`s and prints usage cleanly. Also a
                                meta-check: every `scripts/*.py` that defines a `selftest` subcommand
                                must be registered here (a selftest the gate never runs is worse than
                                none — its presence implies coverage that doesn't exist).
  4. bundle-parity              Every shipped file under `.claude/skills/`, `hooks/`, the bundled
                                runtime helper `scripts/`, and bundled parity `tests/` is
                                byte-identical under `simplicio_loop/_bundle/` — checked in BOTH
                                directions, so an orphan left behind in `_bundle/` after a source
                                rename/delete is caught too (not just a forward source->bundle walk).
  5. plugin-parity              The lean marketplace plugin tree mirrors the source files it ships
                                (skills + wired hooks + runtime helper scripts + parity tests).
  6. skill-count                Every "<N> skills" claim agrees with the seven canonical
                                `.claude/skills/*/SKILL.md` entries; accelerator integrations are
                                shipped alongside the core but are not counted as skills.
  7. adapter-install-contract   `scripts/verify_adapters.py claude` — a fast, representative subset
                                of the full 11-runtime installer e2e (`verify_adapters.py` with no
                                args) — proves the install contract isn't dead assurance. Run the
                                full sweep manually / in a slower CI job; it is too slow (~45s per
                                runtime) for this fast local gate.
  8. quantitative-claims        Every quantitative number in README/SKILLs has a corresponding entry
                                in `scripts/claims_manifest.py` with a receipt or "unverified" label.
                                Unknown/missing numbers => check red. Any claim marked "verified"
                                must additionally cite a receipt bound to a REAL commit reachable
                                in this repo's git history (`commit` + `generated_at`/`created_at`
                                fields) — a fabricated or foreign-commit receipt is rejected (#294).
  9. prose-commands-valid       Every doc-cited worker invocation (flags + verbs) is validated against
                                the worker's real CLI via `--describe-cli`. Workers that emit
                                `--describe-cli` JSON are checked for flag existence; divergences are
                                reported with file:line.
  10. skill-pair-parity         Shared references under `.claude/skills/simplicio-loop/` and
                                `.claude/skills/simplicio-tasks/` are byte-identical for every file
                                that exists in BOTH `references/` trees (the tasks tree is a
                                deliberate subset; `SKILL.md` differs by design and is excluded).
  11. turn-header-format        `loop_progress.py render --turn-header` output still matches the
                                documented contract shape.
  12. install-mutations-doc     `docs/INSTALL_MUTATIONS.md` matches its generator.
  13. canonical-manifest        `scripts/canonical_manifest.py check` (#294 AC6/AC7): version
                                (release_manifest), skill count, and CHANGELOG.md's latest
                                released version all agree, AND the runtime/adapter count in
                                README/adapters/MATRIX.md agrees with the actual `adapters/` tree
                                (legacy compat shims collapsed to their canonical runtime).

Usage:
    python3 scripts/claims_audit.py [--core] [--json] [--only 1,2,3,4]
"""
import json
import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CORE_MODE = False

if HERE not in sys.path:
    sys.path.insert(0, HERE)
from mirror_manifest import LEAN_SCRIPTS, LEAN_TESTS  # noqa: E402 — single source of truth (#74)
from claims_manifest import CLAIMS, extract_claims  # noqa: E402 — quantitative claims (#96)

DOC_GLOBS = ["README.md", "AGENTS.md", "INSTALL.md", "PYPI.md"]
# CHANGELOG.md is deliberately NOT in DOC_GLOBS: it is a historical log whose entries correctly
# describe counts as they were AT THE TIME of that change (e.g. "6 skills" in an old entry, now
# 7) — checking it against skill-count/extension-point-count checks 2/6 would false-positive on
# every entry that predates the current count. Its version-drift exposure (#294 AC7) is instead
# checked narrowly and correctly in `scripts/canonical_manifest.py` (latest released entry vs
# `pyproject.toml`, not a skill/extension-point count comparison).
DOC_DIRS = [os.path.join(".claude", "skills")]
EXTENSION_POINTS_DOC = os.path.join(
    REPO, ".claude", "skills", "simplicio-tasks", "references", "extension-points.md")

SCRIPT_RE = re.compile(r"((?:scripts|hooks)/[a-zA-Z0-9_]+\.py)")
# "44 extension points", "the 44 named binding points", "44 named points", "44 named extension
# points" (a phrasing that escaped the original two patterns — #72), badge "...points-44-...".
COUNT_RES = [
    re.compile(r"\b(\d{1,3})\s+extension points", re.I),
    re.compile(r"\b(\d{1,3})\s+named (?:binding )?points", re.I),
    re.compile(r"\b(\d{1,3})\s+named extension points", re.I),
    re.compile(r"extension%20points-(\d{1,3})-"),
]
# "6 skills", "the 6 skills", badge "skills-6-..." — deliberately NOT matching "11 skills &
# accelerators" rollups (those are a different, non-audited marketing number by design).
SKILL_COUNT_RES = [
    re.compile(r"\b(\d{1,2})\s+skills\b(?!\s*&)", re.I),
    re.compile(r"skills-(\d{1,2})-", re.I),
]
# The public "7 skills" claim names the protocol core.  The five accelerator/integration
# directories are shipped beside it, but are intentionally not part of that advertised count.
CORE_SKILL_NAMES = frozenset({
    "simplicio-loop",
    "simplicio-tasks",
    "simplicio-orient",
    "simplicio-review",
    "simplicio-compress",
    "simplicio-learn",
    "simplicio-autoresearch",
})
# worker/hook scripts whose `selftest` proves them; others just need to be invokable
SELFTEST_SCRIPTS = [
    "scripts/loop_journal.py",
    "scripts/billing_aggregator.py",
    "scripts/savings_harness.py",
    "scripts/repo_conventions.py",
    "scripts/task_anchor.py",
    "scripts/task_backlog.py",
    "scripts/test_infra_probe.py",
    "scripts/pr_evidence.py",
    "scripts/flow_audit.py",
    "scripts/impact_audit.py",
    "scripts/cross_agent_wiki.py",
    "scripts/hierarchical_planner.py",
    "scripts/watcher_verify.py",
    "scripts/handoff.py",
    "scripts/install_services.py",
    "scripts/mirror_manifest.py",
    "scripts/toon_codec.py",
    "scripts/autoresearch.py",
    "scripts/e2e_demo.py",
    "scripts/check_e2e_demo_contract.py",
    "scripts/check_e2e_installed.py",
    "scripts/clean_env_contract.py",
    "scripts/completion_oracle.py",
    "scripts/quality_matrix.py",
    "scripts/planning_gate.py",
    "scripts/github_lifecycle.py",
    "scripts/mirror_parity.py",
    "scripts/run_state.py",
    "scripts/claims_manifest.py",
    "scripts/fan_out.py",
    "scripts/worktree_queue.py",
    "scripts/worktree_cleanup.py",
    "scripts/schema_verify.py",
    "scripts/loop_progress.py",
    "hooks/action_gate.py",
    "scripts/repository_budget.py",
    "scripts/repo_history_scan.py",
    "scripts/history_migration_plan.py",
    "scripts/canonical_manifest.py",
    "scripts/package_content_check.py",
    "scripts/test_categories.py",
    "scripts/stage_report.py",
    "scripts/completion_auditor.py",
    "scripts/review_panel.py",
    "scripts/stage_coordinator.py",
    "scripts/finding_collector.py",
    "scripts/coordinator.py",
    "scripts/evolution.py",
    "scripts/agent_replication.py",
    "scripts/workflow_topology.py",
    "scripts/pr_dod_review.py",
    "scripts/release_check.py",
    "scripts/operator_check.py",
    "scripts/supervisor_enforcement.py",
    "scripts/deep_correctness_gate.py",
]
SATELLITE_SCRIPT_PATHS = frozenset({
    "scripts/agentsview_adapter.py",
    "scripts/autoresearch.py",
    "scripts/az_boards_adapter.py",
    "scripts/billing_aggregator.py",
    "scripts/check_e2e_demo_contract.py",
    "scripts/check_e2e_installed.py",
    "scripts/e2e_demo.py",
    "scripts/fan_out.py",
    "scripts/independent_watcher.py",
    "scripts/repo_conventions.py",
    "scripts/savings_harness.py",
    "scripts/schema_verify.py",
})
# scripts intentionally excluded from the "every selftest is registered" meta-check (check 3): a
# `selftest`-shaped function/subcommand that isn't the worker's own self-check, or a script this
# repo has decided NOT to gate (document why here, don't just silently exclude).
SELFTEST_EXEMPT = set()


def _docs():
    files = [os.path.join(REPO, f) for f in DOC_GLOBS if os.path.exists(os.path.join(REPO, f))]
    for d in DOC_DIRS:
        for root, _, names in os.walk(os.path.join(REPO, d)):
            files += [os.path.join(root, n) for n in names if n.endswith(".md")]
    return files


def _read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def check_scripts_exist():
    missing = {}
    for doc in _docs():
        for rel in SCRIPT_RE.findall(_read(doc)):
            if not os.path.exists(os.path.join(REPO, rel)):
                missing.setdefault(rel, []).append(os.path.relpath(doc, REPO))
    ok = not missing
    return ok, ("all referenced scripts exist" if ok else
                "missing scripts: %s" % json.dumps(missing))


def _extension_point_table_count():
    """Row count of the ACTUAL extension-points table in extension-points.md — the source of
    truth check 2 compares every doc claim against (#72), not just mutual doc consensus."""
    if not os.path.exists(EXTENSION_POINTS_DOC):
        return None
    in_table = False
    count = 0
    for line in _read(EXTENSION_POINTS_DOC).splitlines():
        s = line.strip()
        if s.startswith("| Extension point |"):
            in_table = True
            continue
        if not in_table:
            continue
        if s.startswith("|---"):
            continue
        if s.startswith("|"):
            count += 1
        else:
            break  # blank line / prose ends the table
    return count


def check_extension_count():
    found = {}  # number -> [files]
    for doc in _docs():
        txt = _read(doc)
        for rx in COUNT_RES:
            for n in rx.findall(txt):
                found.setdefault(int(n), set()).add(os.path.relpath(doc, REPO))
    actual = _extension_point_table_count()
    if not found:
        if actual is None:
            return True, "no extension-point counters found (nothing to check)"
        return True, "no extension-point counters found in docs; table has %d rows" % actual
    detail = {n: sorted(files) for n, files in found.items()}
    if len(found) > 1:
        return False, "extension-point counters DISAGREE: %s" % json.dumps(detail)
    n = next(iter(found))
    if actual is not None and n != actual:
        return False, ("extension-point count claimed as %d does not match the actual "
                        "extension-points.md table (%d rows): %s" % (n, actual, json.dumps(detail)))
    return True, "extension-point count consistent with the table: %d" % n


def check_skill_count():
    skills_dir = os.path.join(REPO, ".claude", "skills")
    actual = len([n for n in (os.listdir(skills_dir) if os.path.isdir(skills_dir) else [])
                  if n in CORE_SKILL_NAMES
                  and os.path.isfile(os.path.join(skills_dir, n, "SKILL.md"))])
    found = {}
    for doc in _docs():
        txt = _read(doc)
        for rx in SKILL_COUNT_RES:
            for n in rx.findall(txt):
                found.setdefault(int(n), set()).add(os.path.relpath(doc, REPO))
    if not found:
        return True, "no skill-count claims found; tree has %d skills" % actual
    detail = {n: sorted(files) for n, files in found.items()}
    if len(found) > 1 or actual not in found:
        return False, ("skill-count claim(s) %s do not match the actual tree (%d skills under "
                ".claude/skills/ core): %s" % (sorted(found), actual, json.dumps(detail)))
    return True, "skill count consistent with the canonical core tree: %d" % actual


def check_commands_run():
    failures = []
    selected = [rel for rel in SELFTEST_SCRIPTS
                if not CORE_MODE or rel not in SATELLITE_SCRIPT_PATHS]
    for rel in selected:
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            failures.append("%s: not found" % rel)
            continue
        r = subprocess.run([sys.executable, path, "selftest"],
                           capture_output=True, text=True, cwd=REPO)
        bad_output = re.search(r"\bFAIL(?:ED)?\b|\[XX\]|\[ER\]", r.stdout.upper().replace("PASS", ""))
        if r.returncode != 0 or bad_output:
            failures.append("%s selftest rc=%d" % (rel, r.returncode))
    # meta-check (#75): any scripts/*.py that DEFINES a `selftest` subcommand but isn't
    # registered above is dead assurance — its presence implies coverage that never runs.
    registered = set(SELFTEST_SCRIPTS) | SELFTEST_EXEMPT
    scripts_dir = os.path.join(REPO, "scripts")
    orphans = []
    for name in sorted(os.listdir(scripts_dir)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        rel = "scripts/%s" % name
        if rel in registered:
            continue
        path = os.path.join(scripts_dir, name)
        try:
            text = _read(path)
        except OSError:
            continue
        # a script that both DEFINES a selftest and dispatches it from argv is a real, runnable
        # selftest the gate is skipping — not just an unrelated function named "selftest".
        if re.search(r"def\s+(?:cmd_)?selftest\b", text) and '"selftest"' in text:
            orphans.append(rel)
    if orphans:
        failures.append("selftest defined but not registered in SELFTEST_SCRIPTS/SELFTEST_EXEMPT: "
                         "%s" % ", ".join(orphans))
    # other cited scripts: must at least py_compile without crashing
    cited = set()
    for doc in _docs():
        cited.update(SCRIPT_RE.findall(_read(doc)))
    for rel in sorted(cited - set(SELFTEST_SCRIPTS)):
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            continue  # caught by check 1
        c = subprocess.run([sys.executable, "-m", "py_compile", path],
                           capture_output=True, text=True, cwd=REPO)
        if c.returncode != 0:
            failures.append("%s: py_compile failed" % rel)
    ok = not failures
    if not ok:
        return False, "; ".join(failures)
    if CORE_MODE:
        excluded = len(SELFTEST_SCRIPTS) - len(selected)
        return True, "all core cited commands run; satellite selftests excluded=%d" % excluded
    return True, "all cited commands run"


def check_bundle_parity():
    # The pip bundle ships the skills, hooks, runtime helper scripts, and shipped parity tests —
    # all must mirror source byte-for-byte, checked in BOTH directions (#70): forward
    # (source -> bundle: nothing shipped is missing/stale) AND reverse (bundle -> source: no
    # orphan file left behind by a rename/delete still ships in the pip wheel undetected).
    pairs = [
        (os.path.join(REPO, ".claude", "skills"),
         os.path.join(REPO, "simplicio_loop", "_bundle", "skills")),
        (os.path.join(REPO, "hooks"),
         os.path.join(REPO, "simplicio_loop", "_bundle", "hooks")),
        (os.path.join(REPO, "scripts"),
         os.path.join(REPO, "simplicio_loop", "_bundle", "scripts"),
         set(LEAN_SCRIPTS)),
        (os.path.join(REPO, "tests"),
         os.path.join(REPO, "simplicio_loop", "_bundle", "tests"),
         set(LEAN_TESTS)),
    ]
    drift = []

    def _walk_rel(root, include):
        out = set()
        for r, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for n in names:
                if n.endswith((".pyc", ".pyo")):
                    continue
                rel = os.path.relpath(os.path.join(r, n), root)
                if include is not None and rel not in include:
                    continue
                out.add(rel)
        return out

    for pair in pairs:
        if len(pair) == 2:
            src_root, bun_root = pair
            include = None
        else:
            src_root, bun_root, include = pair
        tag = os.path.basename(bun_root)
        if not os.path.isdir(bun_root):
            drift.append("bundle dir missing: _bundle/%s" % tag)
            continue
        src_files = _walk_rel(src_root, include)
        # bundle-side include filter mirrors the source-side one; extra dirs under a bundle
        # subtree with no `include` restriction are legitimately part of the mirror.
        bun_files = _walk_rel(bun_root, include if include is not None else None)
        for rel in sorted(src_files - bun_files):
            drift.append("%s: missing in bundle: %s" % (tag, rel))
        for rel in sorted(bun_files - src_files):
            drift.append("%s: orphan in bundle (no matching source file): %s" % (tag, rel))
        for rel in sorted(src_files & bun_files):
            sp, bp = os.path.join(src_root, rel), os.path.join(bun_root, rel)
            if _read(sp) != _read(bp):
                drift.append("%s: differs: %s" % (tag, rel))
    ok = not drift
    return ok, ("bundle ≡ source, both directions (skills + hooks + runtime scripts + parity tests)"
                if ok else "; ".join(drift))


def check_plugin_sync():
    # The lean marketplace plugin tree (plugin/) must mirror source — skills byte-identical,
    # hooks exactly the wired set. scripts/sync_plugin.py --check is the source of truth.
    r = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "sync_plugin.py"), "--check"],
                       capture_output=True, text=True, cwd=REPO)
    ok = r.returncode == 0
    detail = [ln for ln in (r.stdout or r.stderr or "").splitlines() if ln.strip()]
    return ok, ("plugin ≡ source (lean marketplace tree)" if ok else "; ".join(detail[-6:]))


def check_adapter_contract():
    # #75: verify_adapters.py was previously referenced only in docs/snapshots, never actually run
    # by the gate — "runnable in CI" was an unrun claim. This runs the fast, representative
    # "claude" runtime for real (installs into a throwaway target, asserts skills/entry/hooks
    # landed); the full 11-runtime sweep (`python3 scripts/verify_adapters.py`) is documented in
    # adapters/MATRIX.md as a slower manual/CI-optional check.
    path = os.path.join(REPO, "scripts", "verify_adapters.py")
    if not os.path.exists(path):
        return True, "scripts/verify_adapters.py not present (nothing to check)"
    try:
        r = subprocess.run([sys.executable, path, "claude"],
                           capture_output=True, text=True, cwd=REPO, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "verify_adapters.py claude timed out (>60s)"
    ok = r.returncode == 0
    detail = [ln for ln in (r.stdout or r.stderr or "").splitlines() if ln.strip()]
    return ok, ("adapter install-contract verified (claude)" if ok else "; ".join(detail[-8:]))


def _git_commit_exists(sha, repo_root):
    """True if `sha` resolves to a real, reachable commit object inside `repo_root`'s git
    history. A fabricated hash, a hash from an unrelated repo, or a non-hex string all fail this
    (#294 step 4/step 5: 'claim quantitativo com receipt de outro commit/versão é rejeitado')."""
    if not sha or not re.match(r"^[0-9a-fA-F]{7,40}$", str(sha)):
        return False
    # Retry on a transient process-spawn error (observed on Windows as `OSError: [WinError 50]`
    # under rapid subprocess creation) — a host quirk, not a verdict on the commit itself.
    for attempt in range(3):
        try:
            r = subprocess.run(["git", "cat-file", "-e", str(sha) + "^{commit}"],
                               capture_output=True, text=True, cwd=repo_root)
            return r.returncode == 0
        except OSError:
            if attempt == 2:
                return False
            import time as _time
            _time.sleep(0.05 * (attempt + 1))
    return False


def validate_receipt(receipt_path, repo_root=REPO):
    """A receipt backing a 'verified' claim must be a real artifact bound to THIS repo's git
    history, not an arbitrary/copied JSON blob (#294 step 4: 'claims quantitativos com receipt,
    data, commit e validade').

    Required fields:
      - `commit`:  a git commit sha that actually resolves inside `repo_root`'s object db.
      - `generated_at` (or `created_at`): an ISO-ish timestamp string.

    Returns (ok, reason). A receipt whose `commit` doesn't resolve to a real reachable commit
    (fabricated, foreign-repo, or stale-format hash) is rejected — this is the mechanical answer
    to "receipt de outro commit/versão é rejeitado".
    """
    try:
        with open(receipt_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return False, "receipt %s: unreadable/invalid JSON (%s)" % (receipt_path, e)
    if not isinstance(data, dict):
        return False, "receipt %s: not a JSON object" % receipt_path
    commit = data.get("commit")
    ts = data.get("generated_at") or data.get("created_at")
    if not commit:
        return False, "receipt %s: missing 'commit' field" % receipt_path
    if not ts:
        return False, "receipt %s: missing 'generated_at'/'created_at' timestamp" % receipt_path
    if not _git_commit_exists(commit, repo_root):
        return False, ("receipt %s: commit '%s' does not resolve to a real commit reachable in "
                        "this repo's history — receipt from another commit/version rejected" %
                        (receipt_path, commit))
    return True, "receipt %s bound to real commit %s" % (receipt_path, commit)


def check_quantitative_claims():
    """#96/#294: every quantitative number in README/SKILLs must cite a receipt or be
    'unverified', and any claim marked 'verified' must cite a receipt genuinely bound to this
    repo's history (not a fabricated or foreign-commit artifact).

    Checks:
      a) All claims in CLAIMS manifest have valid status.
      b) Unknown quantitative numbers in scanned docs are flagged.
      c) Any claim marked 'verified' has a receipt that validates (real commit + timestamp).
    """
    failures = []
    # a) Manifest integrity
    for c in CLAIMS:
        if c["status"] not in ("verified", "unverified"):
            failures.append("claim %s: invalid status '%s'" % (c["id"], c["status"]))
        if c["receipt"] is not None:
            rpath = os.path.join(REPO, c["receipt"])
            if not os.path.exists(rpath):
                failures.append("claim %s: receipt missing: %s" % (c["id"], c["receipt"]))
                continue
            # c) a claim asserting "verified" must have a receipt genuinely bound to this repo's
            # history — a stale/foreign/fabricated commit can't back a "measured" claim.
            if c["status"] == "verified":
                r_ok, r_reason = validate_receipt(rpath, REPO)
                if not r_ok:
                    failures.append("claim %s: %s" % (c["id"], r_reason))
    # Manifest must not be empty
    if not CLAIMS:
        failures.append("claims_manifest.CLAIMS is empty — no claims registered")
    # b) Unknown claims found in docs
    unknown = extract_claims()
    for doc_rel, match_text in unknown:
        failures.append(
            "quantitative claim '%s' in %s is not in claims_manifest.py — "
            "add it or mark as 'unverified'" % (match_text, doc_rel)
        )
    ok = not failures
    return ok, ("all quantitative claims registered in manifest (%d total)" % len(CLAIMS)
                if ok else "; ".join(failures))


def check_prose_commands():
    """#97: validate doc-cited worker invocations against the real CLI via --describe-cli.

    Extracts code blocks and inline commands from SKILL.md and references/*.md,
    parses the invoked flags/verbs, and checks each against the worker's real
    `--describe-cli` output (JSON of accepted verbs + flags).

    Workers that do NOT support --describe-cli are silently skipped.
    """
    failures = []
    excluded = set()
    # Documents to scan
    prose_docs = [os.path.join(REPO, "README.md"), os.path.join(REPO, "AGENTS.md")]
    skills_dir = os.path.join(REPO, ".claude", "skills")
    if os.path.isdir(skills_dir):
        for sname in os.listdir(skills_dir):
            sdir = os.path.join(skills_dir, sname)
            smd = os.path.join(sdir, "SKILL.md")
            if os.path.isfile(smd):
                prose_docs.append(smd)
            refs_dir = os.path.join(sdir, "references")
            if os.path.isdir(refs_dir):
                for rname in os.listdir(refs_dir):
                    if rname.endswith(".md"):
                        prose_docs.append(os.path.join(refs_dir, rname))

    # Regex: python3 scripts/some_worker.py <verb> [--flags ...]
    INVOCATION_RE = re.compile(
        r"(?:python3\s+)?(scripts/([a-zA-Z0-9_]+)\.py)\s+([a-z_]+)"
        r"(?:\s+((?:-{1,2}[a-zA-Z0-9_-]+(?:\s+\S+)?\s*)*))?",
        re.I,
    )

    for doc_path in prose_docs:
        if not os.path.exists(doc_path):
            continue
        doc_rel = os.path.relpath(doc_path, REPO)
        with open(doc_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        for m in INVOCATION_RE.finditer(text):
            script_rel = m.group(1)  # e.g. "scripts/task_anchor.py"
            verb = m.group(3)
            flags_str = m.group(4) or ""
            script_path = os.path.join(REPO, script_rel)

            if not os.path.exists(script_path):
                continue  # caught by check 1
            if CORE_MODE and script_rel in SATELLITE_SCRIPT_PATHS:
                excluded.add(script_rel)
                continue

            # Try --describe-cli
            r = subprocess.run(
                [sys.executable, script_path, "--describe-cli"],
                capture_output=True, text=True, timeout=15, cwd=REPO,
            )
            if r.returncode != 0:
                continue  # worker doesn't support --describe-cli; skip

            try:
                cli_spec = json.loads(r.stdout)
            except (json.JSONDecodeError, ValueError):
                continue

            accepted_verbs = cli_spec.get("verbs", [])
            accepted_flags = cli_spec.get("flags", [])

            # Check verb
            if verb not in accepted_verbs:
                failures.append(
                    "%s:%d: verb '%s' not in --describe-cli for %s (accepted: %s)" %
                    (doc_rel, text[:m.start()].count("\n") + 1,
                     verb, script_rel, accepted_verbs)
                )

            # Check flags (crude: extract flag names only, not values)
            for token in flags_str.split():
                if token.startswith("--") or token.startswith("-"):
                    flag_name = token.split("=")[0]
                    if flag_name not in accepted_flags and flag_name not in ("--help",):
                        failures.append(
                            "%s:%d: flag '%s' not in --describe-cli for %s (accepted: %s)" %
                            (doc_rel, text[:m.start()].count("\n") + 1,
                             flag_name, script_rel, accepted_flags)
                        )

    ok = not failures
    if not ok:
        return False, "; ".join(failures)
    detail = "all doc-cited core commands validated against --describe-cli"
    if CORE_MODE:
        detail += "; satellite command probes excluded=%d" % len(excluded)
    else:
        detail = "all doc-cited commands validated against --describe-cli"
    return True, detail


def check_skill_pair_parity():
    """Compare ONLY the shared `references/` files between simplicio-loop and simplicio-tasks.

    `SKILL.md` is intentionally excluded: `simplicio-tasks` is a compatibility alias and differs
    from `simplicio-loop` by design. Missing dirs pass so fixture repos can exercise the check in
    isolation without mirroring the full skill tree.
    """
    loop_refs = os.path.join(REPO, ".claude", "skills", "simplicio-loop", "references")
    tasks_refs = os.path.join(REPO, ".claude", "skills", "simplicio-tasks", "references")
    if not os.path.isdir(loop_refs) or not os.path.isdir(tasks_refs):
        return True, "skill pair parity skipped — references/ dir absent"

    def _walk(root):
        out = set()
        for r, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for n in names:
                rel = os.path.relpath(os.path.join(r, n), root)
                if rel == "SKILL.md":
                    continue
                out.add(rel)
        return out

    shared = _walk(loop_refs) & _walk(tasks_refs)
    drift = []
    for rel in sorted(shared):
        lp = os.path.join(loop_refs, rel)
        tp = os.path.join(tasks_refs, rel)
        try:
            with open(lp, "rb") as f:
                lbytes = f.read()
            with open(tp, "rb") as f:
                tbytes = f.read()
        except OSError as e:
            drift.append("%s: read failed (%s)" % (rel, e))
            continue
        if lbytes != tbytes:
            drift.append(rel)
    ok = not drift
    return ok, ("shared skill references are byte-identical"
                if ok else "skill-pair drift: %s" % ", ".join(drift))


def check_turn_header_format():
    """#304 § 2.2 — the turn-header format `render --turn-header` actually prints must match the
    frozen shape cited in `references/progress-feedback.md`. Prevents doc<->code drift on the
    contract the user reads every turn: adulterating either side alone makes this check fail."""
    doc_path = os.path.join(REPO, ".claude", "skills", "simplicio-loop", "references",
                            "progress-feedback.md")
    try:
        with open(doc_path, encoding="utf-8") as f:
            doc = f.read()
    except OSError:
        return False, "progress-feedback.md not found"
    if "fase F1 · etapa 5/9 operate · item T3" not in doc:
        return False, "progress-feedback.md no longer cites the frozen turn-header example"

    header_re = re.compile(
        r"^(MEASURED|UNVERIFIED)\|\[simplicio-loop\] fase F\d+ · etapa \d+/\d+ \S+ · "
        r"item \S+ \(\d+/\d+ itens\) · ACs \S+ · \d+% geral · iter \d+(/\d+)?$"
    )
    with tempfile.TemporaryDirectory(prefix="claims_audit_turnheader_") as tmp:
        anchor_path = os.path.join(tmp, "anchor.json")
        backlog_path = os.path.join(tmp, "backlog.jsonl")
        with open(anchor_path, "w", encoding="utf-8") as f:
            json.dump({"item": "T3", "criteria": [
                {"id": "AC1", "status": "done"}, {"id": "AC2", "status": "pending"},
                {"id": "AC3", "status": "pending"}]}, f)
        with open(backlog_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "master", "goal": "g"}) + "\n")
            for i, st in enumerate(["done", "done", "running", "ready", "ready"], start=1):
                f.write(json.dumps({"kind": "item", "id": "T%d" % i, "status": st}) + "\n")
        env = dict(os.environ)
        env.update({"SIMPLICIO_PROGRESS_DIR": tmp, "SIMPLICIO_ANCHOR_FILE": anchor_path,
                   "SIMPLICIO_BACKLOG_FILE": backlog_path})
        script = os.path.join(REPO, "scripts", "loop_progress.py")
        subprocess.run([sys.executable, script, "emit", "--step", "operate", "--status", "begin",
                       "--item", "T3"], capture_output=True, text=True, encoding="utf-8",
                      errors="replace", cwd=tmp, env=env, stdin=subprocess.DEVNULL)
        r = subprocess.run([sys.executable, script, "render", "--turn-header"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=tmp, env=env, stdin=subprocess.DEVNULL)
    line = (r.stdout or "").strip()
    if not header_re.match(line):
        return False, "render --turn-header output %r no longer matches the documented shape" % line
    return True, "turn-header format matches the documented contract"


def check_install_mutations_doc_generated():
    """#293 §7: `docs/INSTALL_MUTATIONS.md` is generated from `scripts/gen_install_mutations_doc.py`,
    not hand-maintained — this re-renders it and fails if the file on disk differs by a byte, the
    same drift-check contract as `check_bundle_parity()`/`check_plugin_sync()` above."""
    generator = os.path.join(REPO, "scripts", "gen_install_mutations_doc.py")
    if not os.path.exists(generator):
        return False, "missing scripts/gen_install_mutations_doc.py"
    r = subprocess.run([sys.executable, generator, "--check"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=REPO, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        return False, (r.stdout + r.stderr).strip() or "docs/INSTALL_MUTATIONS.md has drifted"
    return True, "docs/INSTALL_MUTATIONS.md matches its generator"


def check_canonical_manifest():
    """#294 AC6/AC7: `scripts/canonical_manifest.py check` — the single canonical manifest that
    ties version (release_manifest), skill count, runtime/adapter count, and CHANGELOG.md version
    drift together. Existing checks 2/6 already cover extension-point/skill-count drift against
    README/AGENTS/CLAUDE/INSTALL/PYPI/CHANGELOG; this check adds the runtime-count cross-check and
    the CHANGELOG-vs-pyproject version cross-check no other check owned."""
    path = os.path.join(REPO, "scripts", "canonical_manifest.py")
    if not os.path.exists(path):
        return False, "missing scripts/canonical_manifest.py"
    r = subprocess.run([sys.executable, path, "check"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=REPO, stdin=subprocess.DEVNULL)
    ok = r.returncode == 0
    detail = [ln for ln in (r.stdout or r.stderr or "").splitlines() if ln.strip()]
    return ok, ("; ".join(detail) if detail else ("canonical manifest ready" if ok else "canonical-manifest check failed"))


def check_contract_parity():
    """#458 item 2: the canonical stage-agents contracts tree (`contracts/stage-agents/v1/`)
    must be byte-identical to its pip-bundle mirror (`simplicio_loop/_contracts/stage-agents/v1/`).
    `scripts/sync_plugin.py --check-contracts` is the source of truth for what 'in sync' means."""
    path = os.path.join(REPO, "scripts", "sync_plugin.py")
    if not os.path.exists(path):
        return False, "missing scripts/sync_plugin.py"
    r = subprocess.run([sys.executable, path, "--check-contracts"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=REPO, stdin=subprocess.DEVNULL)
    ok = r.returncode == 0
    detail = [ln for ln in (r.stdout or r.stderr or "").splitlines() if ln.strip()]
    return ok, ("contracts ≡ source (stage-agents/v1)" if ok else "; ".join(detail[-6:]))


CHECKS = [
    ("1 referenced-scripts-exist", check_scripts_exist),
    ("2 extension-point-count", check_extension_count),
    ("3 cited-commands-run", check_commands_run),
    ("4 bundle-parity", check_bundle_parity),
    ("5 plugin-parity", check_plugin_sync),
    ("6 skill-count", check_skill_count),
    ("7 adapter-install-contract", check_adapter_contract),
    ("8 quantitative-claims", check_quantitative_claims),
    ("9 prose-commands-valid", check_prose_commands),
    ("10 skill-pair-parity", check_skill_pair_parity),
    ("11 turn-header-format", check_turn_header_format),
    ("12 install-mutations-doc-generated", check_install_mutations_doc_generated),
    ("13 canonical-manifest", check_canonical_manifest),
    ("14 contract-parity", check_contract_parity),
]


def main():
    global CORE_MODE
    args = sys.argv[1:]
    CORE_MODE = "--core" in args
    as_json = "--json" in args
    only = None
    if "--only" in args:
        only = set(args[args.index("--only") + 1].split(","))
    results = []
    for label, fn in CHECKS:
        if only and label.split()[0] not in only:
            continue
        try:
            ok, detail = fn()
        except Exception as e:  # a crashing check is a failed check (fail-closed)
            ok, detail = False, "check crashed: %s" % e
        results.append({"check": label, "ok": ok, "detail": detail})
    failed = [r for r in results if not r["ok"]]
    if as_json:
        print(json.dumps({"ok": not failed, "results": results}, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print("[%s] %s — %s" % ("ok" if r["ok"] else "XX", r["check"], r["detail"]))
        print("claims-audit: %s (%d/%d)" % ("PASS" if not failed else "FAIL",
                                            len(results) - len(failed), len(results)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
