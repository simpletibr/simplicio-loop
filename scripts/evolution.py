#!/usr/bin/env python3
"""simplicio-loop — continuous-evolution coordinator (MVP core of GH #467).

GH #467 asks for a full "Continuous Evolution" coordinator: discover/classify/prioritize
improvement opportunities, open/route GitHub issues for them, enforce a budget across whole
runs, and render an RFC. This worker is deliberately the **genuine, working MVP CORE only** —
GitHub issue creation/routing, budget enforcement across whole runs, and RFC rendering are
explicitly OUT of scope for this slice and tracked in a follow-up issue. What this gives you:

  1. An `EvolutionProposal` record — a classified, deduplicated improvement opportunity (NOT a
     defect/regression — see the DEFECT GUARD below), keyed by a stable **fingerprint** so
     near-identical proposals collapse into ONE record instead of N duplicates.
  2. A **DEFECT GUARD**: `propose()` REFUSES (returns an error result, never raises) any
     `class in ("defect", "regression")` — "o coordenador não pode rotular defeito como
     melhoria" (GH #467). Bugs/regressions belong in `scripts/finding_collector.py`'s finding->issue
     lifecycle, not here.
  3. Deterministic, EXPLAINABLE priority scoring (`compute_priority`): a pure function of fixed
     impact/effort/risk weights — no randomness, no LLM call, same inputs always produce the
     same score. The raw impact/effort/risk values are stored alongside the score so a report
     can show "why" a proposal ranked where it did.
  4. Dedup by fingerprint (sha256 of component+class+normalized(problem), reusing
     `finding_collector.py:normalize_signature` so a symptom/problem string collapses the same way in
     both stores) — a repeat proposal for the SAME (component, class, problem) updates the
     existing record instead of creating a new one.
  5. A per-run BUDGET (`--budget-max`, default 20): refuses to grow the store past N DISTINCT
     fingerprints ever recorded. Simplification (documented, MVP scope): the cap counts every
     fingerprint ever written to `proposals.jsonl` regardless of state or date, NOT just
     "proposals created today" — tracking a rolling per-day window is left to the follow-up
     issue alongside GitHub issue creation.
  6. `list` / `report` / `doctor` — read-only views: the deduped proposals, an "Evolution
     Ledger" summary by class/state (counts + top proposals by priority), and a store
     sanity check.

Deterministic and model-free: `compute_priority` + fingerprinting are pure functions (no I/O),
unit-testable in isolation, same discipline as `loop_journal.py:fingerprint()`,
`task_anchor.py:goal_fingerprint()`, and `finding_collector.py:compute_fingerprint()`.

State (override the directory with $SIMPLICIO_EVOLUTION_DIR):
    .simplicio-loop/orchestrator/evolution/proposals.jsonl   one JSON record per proposal, keyed by fingerprint
                                               (rewritten in place on update — NOT append-only,
                                               same discipline as finding_collector.py's store)

EvolutionProposal fields: proposal_id, fingerprint, class, component, problem, benefit, impact,
effort, risk, priority_score, state, created_at, updated_at, occurrences.

class   one of: defect|regression|improvement|evolution|optimization|hardening|discovery|
                maintenance   (defect/regression are REFUSED by propose() — see DEFECT GUARD)
impact  one of: low|medium|high|critical
effort  one of: low|medium|high
risk    one of: low|medium|high
state   one of: observed|validated|issue-created|linked|deferred|rejected|delivered

Priority scoring (see `compute_priority`):
    priority_score = impact_weight*W1 + (1/effort_weight)*W2 - risk_weight*W3
    W1=10.0 (impact), W2=5.0 (effort, inverted so LOW effort scores higher), W3=3.0 (risk)
    impact_weight:  low=1 medium=2 high=3 critical=4
    effort_weight:  low=1 medium=2 high=3
    risk_weight:    low=1 medium=2 high=3

Verbs:
  propose   Create or update a proposal. --class --component --problem --benefit --impact
            --effort --risk are required. REFUSES (exit 2, state unchanged) if --class is
            defect/regression (defect guard) or if the budget cap would be exceeded (state
            "rejected", reason "budget_exceeded") on a genuinely NEW fingerprint.
            --budget-max N overrides the default cap of 20 distinct fingerprints.
            Prints the resulting record + {"created": true/false} with --json.
  list      Print all proposals (deduped, one per fingerprint) as a JSON array with --json.
  report    Print the "Evolution Ledger": counts by class/state + top proposals by
            priority_score, with --json.
  doctor    Sanity-check the store (file exists/parseable, no duplicate fingerprints with
            different proposal_id, stored priority_score matches a fresh recompute).
            --exit-code -> exit 1 if issues were found.
  selftest  Exercise propose/list/report/doctor plus the defect-guard and budget-cap paths.
            PASS/FAIL, exit 0/1.

Usage:
    python3 scripts/evolution.py propose --class improvement --component scripts/loop_progress.py \\
        --problem "status --json is O(n) rescans on every call" \\
        --benefit "cache last render, 10x fewer rescans" \\
        --impact medium --effort low --risk low --json
    python3 scripts/evolution.py list --json
    python3 scripts/evolution.py report --json
    python3 scripts/evolution.py doctor --json --exit-code
    python3 scripts/evolution.py selftest
"""
import argparse
import hashlib
import json
import os
import sys
import time

try:  # Windows consoles default to cp1252 and choke on non-ASCII — force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EVOLUTION_DIR = os.environ.get("SIMPLICIO_EVOLUTION_DIR") or os.path.join(
    REPO, ".simplicio-loop/orchestrator", "evolution")
PROPOSALS_FILE = os.path.join(EVOLUTION_DIR, "proposals.jsonl")

if HERE not in sys.path:
    sys.path.insert(0, HERE)
# Reuse the symptom/problem normalizer from finding_collector.py (#466) instead of reimplementing it —
# a problem string normalizes the SAME way whether it lands in findings.jsonl or here.
from finding_collector import normalize_signature  # noqa: E402

CLASSES = ("defect", "regression", "improvement", "evolution", "optimization", "hardening",
          "discovery", "maintenance")
# The defect guard: these classes must go through scripts/finding_collector.py instead of being proposed
# here as an "improvement". Kept as its own tuple so the guard condition reads intent-first.
DEFECT_CLASSES = ("defect", "regression")
IMPACTS = ("low", "medium", "high", "critical")
EFFORTS = ("low", "medium", "high")
RISKS = ("low", "medium", "high")
STATES = ("observed", "validated", "issue-created", "linked", "deferred", "rejected", "delivered")

DEFAULT_BUDGET_MAX = 20

# Fixed, documented weights — deterministic and explainable, never tuned by an LLM at run time.
W1_IMPACT = 10.0
W2_EFFORT = 5.0
W3_RISK = 3.0

IMPACT_WEIGHTS = {"low": 1, "medium": 2, "high": 3, "critical": 4}
EFFORT_WEIGHTS = {"low": 1, "medium": 2, "high": 3}
RISK_WEIGHTS = {"low": 1, "medium": 2, "high": 3}


def log(msg):
    print("  " + msg)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ----- pure helpers (selftest / unit tests exercise these directly, no I/O) ------------------------

def compute_priority(impact, effort, risk):
    """Deterministic, explainable priority score. Pure, no I/O, no randomness.

    priority_score = impact_weight*W1_IMPACT + (1/effort_weight)*W2_EFFORT - risk_weight*W3_RISK

    Higher impact, lower effort, and lower risk all push the score UP — same (impact, effort,
    risk) ALWAYS yields the SAME score. Raises ValueError on an unrecognized value so a bad
    value fails loudly rather than silently defaulting.
    """
    iw = IMPACT_WEIGHTS.get((impact or "").strip().lower())
    ew = EFFORT_WEIGHTS.get((effort or "").strip().lower())
    rw = RISK_WEIGHTS.get((risk or "").strip().lower())
    if iw is None:
        raise ValueError("impact must be one of %s" % ", ".join(IMPACTS))
    if ew is None:
        raise ValueError("effort must be one of %s" % ", ".join(EFFORTS))
    if rw is None:
        raise ValueError("risk must be one of %s" % ", ".join(RISKS))
    score = (iw * W1_IMPACT) + ((1.0 / ew) * W2_EFFORT) - (rw * W3_RISK)
    return round(score, 4)


def compute_fingerprint(component, class_, problem):
    """Stable sha256 fingerprint of (component, class, normalized problem). Pure, no I/O.

    Same (component, class, problem-that-normalizes-the-same) -> same fingerprint, regardless of
    incidental timestamps/line numbers/paths in the problem text (reuses finding_collector.py's
    normalize_signature so both stores collapse near-duplicates identically).
    """
    sig = "%s|%s|%s" % (
        (component or "").strip().lower(),
        (class_ or "").strip().lower(),
        normalize_signature(problem),
    )
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()


# ----- store I/O -------------------------------------------------------------------------------

def _load_proposals(path=None):
    """Return (proposals_by_fingerprint dict (insertion order), corrupt_count). Tolerant reader —
    a truncated/illegible line is counted, never silently dropped (mirrors finding_collector.py)."""
    path = path or PROPOSALS_FILE
    proposals = {}
    corrupt = 0
    if not os.path.exists(path):
        return proposals, corrupt
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                corrupt += 1
                continue
            fp = rec.get("fingerprint")
            if not fp:
                corrupt += 1
                continue
            proposals[fp] = rec  # last write for a fingerprint wins
    return proposals, corrupt


def _save_proposals(proposals, path=None):
    path = path or PROPOSALS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in proposals.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _next_proposal_id(proposals):
    """Deterministic sequential id: E0001, E0002, ... based on how many proposals exist already."""
    n = len(proposals) + 1
    while True:
        pid = "E%04d" % n
        if not any(rec.get("proposal_id") == pid for rec in proposals.values()):
            return pid
        n += 1


def propose(proposal_dict, proposals_path=None, budget_max=DEFAULT_BUDGET_MAX):
    """Create-or-update an EvolutionProposal. Returns (record_or_None, created: bool, error: str).

    `error` is non-empty (and record is None) when propose() REFUSES:
      - defect guard: class is "defect" or "regression"
      - budget cap: a genuinely NEW fingerprint would push the store past `budget_max` distinct
        fingerprints ever recorded (MVP simplification — see module docstring point 5).
    Never raises for either refusal path — both are ordinary, expected control flow.

    If an existing record shares the fingerprint (and is not already rejected/deferred — a
    rejected/deferred proposal is a closed decision, not something a fresh observation should
    silently reopen), it is NOT duplicated: `occurrences` is bumped and fields are refreshed,
    and NO new record/id is created. Otherwise a new proposal is created with occurrences=1.
    """
    class_ = (proposal_dict.get("class") or "").strip().lower()
    if class_ in DEFECT_CLASSES:
        return None, False, (
            "refused: class=%r is a defect/regression, not an improvement — file it through "
            "the findings lifecycle instead (scripts/finding_collector.py record --type bug ...). "
            "The evolution coordinator must never relabel a defect as a melhoria." % class_)
    if class_ not in CLASSES:
        return None, False, "refused: class must be one of %s" % ", ".join(CLASSES)

    component = proposal_dict.get("component", "")
    problem = proposal_dict.get("problem", "")
    fp = compute_fingerprint(component, class_, problem)
    now = proposal_dict.get("_now") or _now()

    proposals, _corrupt = _load_proposals(proposals_path)
    existing = proposals.get(fp)
    # A rejected/deferred proposal is a closed decision — treat a repeat as genuinely new so it
    # doesn't silently get glued back onto a decision that already resolved it.
    reopen = existing is not None and existing.get("state") in ("rejected", "deferred")
    is_new = existing is None or reopen

    if is_new and len(proposals) >= budget_max and fp not in proposals:
        return None, False, (
            "budget_exceeded: %d distinct fingerprints already recorded (--budget-max %d) — "
            "refusing to create a new proposal this run" % (len(proposals), budget_max))

    try:
        impact = proposal_dict.get("impact", "")
        effort = proposal_dict.get("effort", "")
        risk = proposal_dict.get("risk", "")
        score = compute_priority(impact, effort, risk)
    except ValueError as exc:
        return None, False, "refused: %s" % exc

    if existing and not reopen:
        existing["occurrences"] = int(existing.get("occurrences", 1)) + 1
        existing["benefit"] = proposal_dict.get("benefit", existing.get("benefit", ""))
        existing["impact"] = impact
        existing["effort"] = effort
        existing["risk"] = risk
        existing["priority_score"] = score
        existing["updated_at"] = now
        rec = existing
        created = False
    else:
        rec = {
            "proposal_id": _next_proposal_id(proposals),
            "fingerprint": fp,
            "class": class_,
            "component": component,
            "problem": problem,
            "benefit": proposal_dict.get("benefit", "") or "",
            "impact": impact,
            "effort": effort,
            "risk": risk,
            "priority_score": score,
            "state": proposal_dict.get("state") or "observed",
            "created_at": now,
            "updated_at": now,
            "occurrences": 1,
        }
        proposals[fp] = rec
        created = True
    _save_proposals(proposals, proposals_path)
    return rec, created, ""


def list_proposals(proposals_path=None):
    proposals, _corrupt = _load_proposals(proposals_path)
    return list(proposals.values())


def report_summary(proposals_path=None, top_n=5):
    """The "Evolution Ledger" — deliberately distinct from finding_collector.py's report: it ranks by
    priority_score (explainable, not just a count) instead of summarizing defect volume."""
    proposals = list_proposals(proposals_path)
    by_class = {}
    by_state = {}
    for rec in proposals:
        c = rec.get("class", "other")
        s = rec.get("state", "observed")
        by_class[c] = by_class.get(c, 0) + 1
        by_state[s] = by_state.get(s, 0) + 1
    ranked = sorted(proposals, key=lambda r: r.get("priority_score", 0), reverse=True)
    top = [{"proposal_id": r.get("proposal_id"), "component": r.get("component"),
           "class": r.get("class"), "priority_score": r.get("priority_score"),
           "impact": r.get("impact"), "effort": r.get("effort"), "risk": r.get("risk")}
          for r in ranked[:top_n]]
    return {
        "ledger": "Evolution Ledger",
        "total": len(proposals),
        "by_class": by_class,
        "by_state": by_state,
        "top_by_priority": top,
    }


def doctor_check(proposals_path=None):
    """Sanity-check the store. Returns {"ok": bool, "issues": [...]}."""
    path = proposals_path or PROPOSALS_FILE
    issues = []
    if not os.path.exists(path):
        return {"ok": True, "issues": []}  # no store yet is not an error
    seen_fp_to_id = {}
    line_no = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line_no += 1
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    rec = json.loads(stripped)
                except ValueError:
                    issues.append("line %d: unparseable JSON" % line_no)
                    continue
                fp = rec.get("fingerprint")
                pid = rec.get("proposal_id")
                if not fp:
                    issues.append("line %d: missing fingerprint" % line_no)
                    continue
                if not pid:
                    issues.append("line %d: missing proposal_id (fingerprint=%s)" % (line_no, fp))
                    continue
                if fp in seen_fp_to_id and seen_fp_to_id[fp] != pid:
                    issues.append(
                        "duplicate fingerprint %s with different proposal_id: %s vs %s" % (
                            fp, seen_fp_to_id[fp], pid))
                seen_fp_to_id[fp] = pid
                if rec.get("class") in DEFECT_CLASSES:
                    issues.append(
                        "proposal_id=%s carries a defect-guard-violating class=%r "
                        "(should never have been written)" % (pid, rec.get("class")))
                try:
                    fresh = compute_priority(rec.get("impact"), rec.get("effort"), rec.get("risk"))
                    if fresh != rec.get("priority_score"):
                        issues.append(
                            "proposal_id=%s stored priority_score=%s != recomputed %s "
                            "(stale scoring weights?)" % (pid, rec.get("priority_score"), fresh))
                except ValueError as exc:
                    issues.append("proposal_id=%s: %s" % (pid, exc))
    except OSError as exc:
        issues.append("could not read store: %s" % exc)
    return {"ok": not issues, "issues": issues}


# ----- CLI -------------------------------------------------------------------------------------

def cmd_propose(args):
    rec, created, error = propose({
        "class": args.klass,
        "component": args.component,
        "problem": args.problem,
        "benefit": args.benefit,
        "impact": args.impact,
        "effort": args.effort,
        "risk": args.risk,
    }, budget_max=args.budget_max)
    if error:
        if args.json:
            print(json.dumps({"error": error, "created": False}, ensure_ascii=False))
        else:
            print("evolution: %s" % error)
        sys.exit(2)
    if args.json:
        print(json.dumps({"proposal": rec, "created": created}, ensure_ascii=False))
    else:
        print("%s proposal %s (fingerprint=%s, priority_score=%s, occurrences=%d)" % (
            "created" if created else "updated", rec["proposal_id"], rec["fingerprint"][:12],
            rec["priority_score"], rec["occurrences"]))


def cmd_list(args):
    proposals = list_proposals()
    if args.json:
        print(json.dumps(proposals, ensure_ascii=False))
    else:
        if not proposals:
            print("evolution: no proposals recorded")
        for rec in proposals:
            log("%s [%-13s] %-11s priority=%-8s %s" % (
                rec.get("proposal_id"), rec.get("state"), rec.get("class"),
                rec.get("priority_score"), rec.get("problem", "")[:50]))


def cmd_report(args):
    summary = report_summary()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print("Evolution Ledger: total=%d" % summary["total"])
        log("by class: %s" % json.dumps(summary["by_class"]))
        log("by state: %s" % json.dumps(summary["by_state"]))
        log("top by priority:")
        for t in summary["top_by_priority"]:
            log("  %s %-11s priority=%-8s impact=%s effort=%s risk=%s" % (
                t["proposal_id"], t["class"], t["priority_score"], t["impact"], t["effort"],
                t["risk"]))


def cmd_doctor(args):
    result = doctor_check()
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print("ok" if result["ok"] else "not-ok")
        for issue in result["issues"]:
            log(issue)
    if args.exit_code and not result["ok"]:
        sys.exit(1)


def cmd_selftest(_args):
    import shutil
    import tempfile

    checks = []

    def chk(name, got, want):
        ok = got == want
        checks.append(ok)
        print("  [%s] %-36s got=%r want=%r" % ("ok" if ok else "XX", name, got, want))

    # --- pure helpers, no I/O ---
    # determinism: same inputs -> same score, every time
    s1 = compute_priority("high", "low", "low")
    s2 = compute_priority("high", "low", "low")
    chk("priority.deterministic", s1 == s2, True)
    # ordering: higher impact + lower effort + lower risk => higher score
    best = compute_priority("critical", "low", "low")
    worst = compute_priority("low", "high", "high")
    chk("priority.ordering_impact", compute_priority("high", "low", "low") >
        compute_priority("low", "low", "low"), True)
    chk("priority.ordering_effort", compute_priority("medium", "low", "low") >
        compute_priority("medium", "high", "low"), True)
    chk("priority.ordering_risk", compute_priority("medium", "medium", "low") >
        compute_priority("medium", "medium", "high"), True)
    chk("priority.best_beats_worst", best > worst, True)
    try:
        compute_priority("nonsense", "low", "low")
        chk("priority.bad_impact_raises", False, True)
    except ValueError:
        chk("priority.bad_impact_raises", True, True)

    fp1 = compute_fingerprint("scripts/x.py", "improvement", "cold path rescans at line 42")
    fp2 = compute_fingerprint("scripts/x.py", "improvement", "cold path rescans at line 99")
    fp3 = compute_fingerprint("scripts/x.py", "improvement", "totally different problem text")
    chk("fingerprint.stable_ignores_line_numbers", fp1 == fp2, True)
    chk("fingerprint.distinct", fp1 != fp3, True)
    chk("fingerprint.class_distinct",
        fp1 != compute_fingerprint("scripts/x.py", "hardening", "cold path rescans every call"), True)

    # --- defect guard: propose() REFUSES, does not raise, for defect/regression ---
    err_rec, err_created, err = propose({
        "class": "defect", "component": "scripts/x.py", "problem": "crashes on empty input",
        "benefit": "no crash", "impact": "high", "effort": "low", "risk": "low",
    })
    chk("defect_guard.refuses_defect", err_rec is None and err_created is False, True)
    chk("defect_guard.error_mentions_findings", "finding_collector.py" in err, True)
    err_rec2, _c, err2 = propose({
        "class": "regression", "component": "scripts/x.py", "problem": "used to work, now fails",
        "benefit": "restore behavior", "impact": "high", "effort": "low", "risk": "low",
    })
    chk("defect_guard.refuses_regression", err_rec2 is None and bool(err2), True)

    # --- store operations against a temp dir ---
    tmp = tempfile.mkdtemp(prefix="evolution_selftest_")
    try:
        ppath = os.path.join(tmp, "proposals.jsonl")
        rec1, created1, e1 = propose({
            "class": "improvement", "component": "scripts/loop_progress.py",
            "problem": "status --json rescans the whole backlog every call (seen at line 10)",
            "benefit": "cache last render, fewer rescans",
            "impact": "medium", "effort": "low", "risk": "low",
        }, ppath)
        chk("propose.created", created1 and not e1, True)
        chk("propose.occurrences_initial", rec1["occurrences"], 1)
        chk("propose.score_matches_pure_fn", rec1["priority_score"],
            compute_priority("medium", "low", "low"))

        # dedup: SAME (component, class, problem-that-normalizes-the-same) updates, not creates —
        # only the embedded line number differs, which normalize_signature collapses away
        rec2, created2, e2 = propose({
            "class": "improvement", "component": "scripts/loop_progress.py",
            "problem": "status --json rescans the whole backlog every call (seen at line 99)",
            "benefit": "cache last render, fewer rescans, refined",
            "impact": "high", "effort": "low", "risk": "low",
        }, ppath)
        chk("propose.dedup_not_created", created2, False)
        chk("propose.dedup_occurrences_bumped", rec2["occurrences"], 2)
        chk("propose.dedup_same_id", rec2["proposal_id"], rec1["proposal_id"])
        chk("propose.dedup_score_refreshed", rec2["priority_score"],
            compute_priority("high", "low", "low"))

        # a distinct problem creates a distinct proposal
        rec3, created3, e3 = propose({
            "class": "hardening", "component": "scripts/loop_progress.py",
            "problem": "a totally unrelated hardening opportunity",
            "benefit": "b", "impact": "low", "effort": "high", "risk": "medium",
        }, ppath)
        chk("propose.distinct_creates_new", created3 and not e3, True)
        chk("propose.distinct_id", rec3["proposal_id"] != rec1["proposal_id"], True)

        all_props = list_proposals(ppath)
        chk("list.count", len(all_props), 2)

        summary = report_summary(ppath)
        chk("report.total", summary["total"], 2)
        chk("report.ledger_label", summary["ledger"], "Evolution Ledger")
        chk("report.by_class_improvement", summary["by_class"].get("improvement"), 1)
        chk("report.top_ranked_first", summary["top_by_priority"][0]["proposal_id"],
            rec1["proposal_id"])  # higher priority_score after dedup update ranks first

        doc = doctor_check(ppath)
        chk("doctor.clean_ok", doc["ok"], True)
        chk("doctor.no_issues", doc["issues"], [])

        # doctor catches a duplicate fingerprint with a mismatched proposal_id
        bad_path = os.path.join(tmp, "bad_proposals.jsonl")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"fingerprint": "abc", "proposal_id": "E0001",
                                "class": "improvement", "impact": "low", "effort": "low",
                                "risk": "low", "priority_score": compute_priority("low", "low", "low")}) + "\n")
            f.write(json.dumps({"fingerprint": "abc", "proposal_id": "E0002",
                                "class": "improvement", "impact": "low", "effort": "low",
                                "risk": "low", "priority_score": compute_priority("low", "low", "low")}) + "\n")
        bad_doc = doctor_check(bad_path)
        chk("doctor.detects_dup_fingerprint", bad_doc["ok"], False)

        # doctor detects a stale/tampered priority_score
        stale_path = os.path.join(tmp, "stale_proposals.jsonl")
        with open(stale_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"fingerprint": "def", "proposal_id": "E0001",
                                "class": "improvement", "impact": "high", "effort": "low",
                                "risk": "low", "priority_score": 0.0}) + "\n")
        stale_doc = doctor_check(stale_path)
        chk("doctor.detects_stale_score", stale_doc["ok"], False)

        # doctor on a missing store is clean (nothing recorded yet is not an error)
        missing_doc = doctor_check(os.path.join(tmp, "does_not_exist.jsonl"))
        chk("doctor.missing_store_ok", missing_doc["ok"], True)

        # --- budget cap: refuses a NEW fingerprint once the cap is reached; existing
        # fingerprints can still be updated (that's not growth) ---
        # NOTE: use distinct WORDS, not numeric suffixes — normalize_signature collapses any
        # bare integer to "N", so "...problem #0" / "#1" / "#2" would all fingerprint IDENTICAL.
        budget_path = os.path.join(tmp, "budget_proposals.jsonl")
        for word in ("alpha", "beta", "gamma"):
            _r, _c, _e = propose({
                "class": "maintenance", "component": "scripts/x.py",
                "problem": "distinct budget-test problem %s" % word,
                "benefit": "b", "impact": "low", "effort": "low", "risk": "low",
            }, budget_path, budget_max=3)
        chk("budget.fills_to_cap", len(list_proposals(budget_path)), 3)
        over_rec, over_created, over_err = propose({
            "class": "maintenance", "component": "scripts/x.py",
            "problem": "one problem too many for the budget",
            "benefit": "b", "impact": "low", "effort": "low", "risk": "low",
        }, budget_path, budget_max=3)
        chk("budget.refuses_over_cap", over_rec is None and over_created is False, True)
        chk("budget.error_names_reason", "budget_exceeded" in over_err, True)
        chk("budget.store_unchanged_after_refusal", len(list_proposals(budget_path)), 3)
        # updating an EXISTING fingerprint at-cap is allowed (not growth)
        upd_rec, upd_created, upd_err = propose({
            "class": "maintenance", "component": "scripts/x.py",
            "problem": "distinct budget-test problem alpha",
            "benefit": "refined benefit", "impact": "medium", "effort": "low", "risk": "low",
        }, budget_path, budget_max=3)
        chk("budget.update_at_cap_allowed", upd_created is False and not upd_err, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = all(checks)
    print("selftest: %s (%d/%d)" % ("PASS" if ok else "FAIL", sum(checks), len(checks)))
    sys.exit(0 if ok else 1)


def build_parser():
    p = argparse.ArgumentParser(prog="evolution.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    pp = sub.add_parser("propose", help="create or update an evolution proposal")
    pp.add_argument("--class", required=True, dest="klass")
    pp.add_argument("--component", required=True)
    pp.add_argument("--problem", required=True)
    pp.add_argument("--benefit", required=True)
    pp.add_argument("--impact", required=True)
    pp.add_argument("--effort", required=True)
    pp.add_argument("--risk", required=True)
    pp.add_argument("--budget-max", dest="budget_max", type=int, default=DEFAULT_BUDGET_MAX)
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_propose)

    pl = sub.add_parser("list", help="list all deduped proposals")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list)

    prp = sub.add_parser("report", help="the Evolution Ledger: counts + top proposals by priority")
    prp.add_argument("--json", action="store_true")
    prp.set_defaults(func=cmd_report)

    pd = sub.add_parser("doctor", help="sanity-check the store")
    pd.add_argument("--json", action="store_true")
    pd.add_argument("--exit-code", dest="exit_code", action="store_true")
    pd.set_defaults(func=cmd_doctor)

    ps = sub.add_parser("selftest",
                        help="exercise propose/list/report/doctor + defect-guard + budget-cap")
    ps.set_defaults(func=cmd_selftest)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "cmd", None):
        parser.print_help()
        sys.exit(2)
    args.func(args)


if __name__ == "__main__":
    main()
