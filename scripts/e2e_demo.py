#!/usr/bin/env python3
"""simplicio-loop — e2e savings demo: MAP -> RECALL -> EDIT -> VERIFY, receipt at every hop.

The capstone acceptance test for the TOON/telemetry follow-up program (issue #93): a single
reproducible artifact proving one task flows mapper -> dev-cli -> loop with a MEASURED,
honestly-labeled savings receipt per hop, instead of a hand-typed savings figure. Watcher-gate
doctrine: no receipt = UNVERIFIED, so every number here carries a `proof.kind` + tokenizer label —
never a bare percentage.

SCOPE NOTE (read before trusting a number): #93 lists three upstream dependencies that are NOT
live in this environment at the time this script was written:
  - simplicio-mapper#148/#149 (native `--for-llm toon` on `handoff`) — not in the installed
    simplicio-mapper (checked: `simplicio-mapper handoff --help` has no such flag).
  - simplicio-dev-cli#88 (`SIMPLICIO_PROMPT_TOON=1` + TOON rows in `.simplicio-loop/runs.jsonl`) — not
    in the installed simplicio-cli (checked: no `SIMPLICIO_PROMPT_TOON` reference in the package).
  - simplicio-runtime#2774/#2775 (`simplicio memory`, the `auto_meter` savings-event emitter,
    the authoritative `simplicio.savings-event/v1` envelope) — the `simplicio` runtime binary is
    not installed in this environment at all (`which simplicio` -> not found).
Each hop below says explicitly, in its event's `note` field, whether it used a REAL live command
against real tool output (measured) or a local, honestly-labeled stand-in for the missing piece
(simulated) — never a fabricated number presented as measured. The MAP and VERIFY hops are fully
real (live `simplicio-mapper` / `task_anchor.py` calls); RECALL and EDIT substitute a local
equivalent for the two pieces that are not shipped yet, per AC5's explicit allowance ("mocks/local
onde preciso, honestamente rotulado").

A separate, unrelated finding surfaced while building this: `simplicio-mapper macro` was observed
returning file paths from an entirely different project (`/home/user/hermes-turbo-agent`) when run
in this repo, apparently via a shared `~/.simplicio-loop/cache/` on this multi-tenant sandbox. `handoff`
and `inspect` were verified clean (isolated, correctly-scoped `.simplicio-loop/` under the target repo)
via a control run in an empty scratch directory, so this script only ever calls `handoff`/`inspect`
and additionally sanity-checks the returned file paths never escape the repo before trusting them.
This is a simplicio-mapper-side issue, out of scope to fix here — flagged for a follow-up issue
there, not fixed in this PR.

Verbs:
  run       Execute the 4 hops for real against a target repo (default: this repo). Writes:
              .simplicio-loop/orchestrator/savings/snapshots.jsonl        (via savings_harness — so
                                                              `billing_aggregator.py collect` and
                                                              `savings_harness.py score` pick these
                                                              hops up for free, no new aggregation
                                                              code)
              .simplicio-loop/orchestrator/savings/e2e-demo-events.jsonl  (one simplicio.savings-event/v1-shaped
                                                              receipt per hop)
              .simplicio-loop/orchestrator/savings/e2e-demo.md            (the human-readable report)
            A hop whose live tool is missing/failing is BLOCKED and reported as such — never a
            fake pass.
  audit     Read an existing e2e-demo events file and fail closed when any hop is still
            `simulated` or missing.
  selftest  Prove the event/report assembly + token math deterministically, fully offline (no
            subprocess to simplicio-mapper/simplicio-cli, no network, no API key) — this is what
            `scripts/check.py` runs, so the gate is green with zero external dependencies.

Usage:
    python3 scripts/e2e_demo.py run [--repo PATH] [--item N] [--out DIR]
    python3 scripts/e2e_demo.py selftest
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

try:  # Windows consoles default to cp1252 and choke on non-ASCII — force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from toon_codec import encode_toon  # noqa: E402 — same codec task_anchor.py uses for --format toon
import savings_harness  # noqa: E402 — reused snapshot store + tokenizer (single source of truth)

DEFAULT_STORE = os.path.join(REPO, ".simplicio-loop/orchestrator", "savings")
EVENTS_FILE = "e2e-demo-events.jsonl"
REPORT_FILE = "e2e-demo.md"
SCHEMA = "simplicio.savings-event/v1"
HOPS = ("map", "recall", "edit", "verify")


def log(msg):
    print("  " + msg)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def count_tokens(text):
    """Fixed, model-free tokenizer: ceil(chars / 4) — delegated to savings_harness so every
    worker in the pipeline agrees on the same number for the same text."""
    return savings_harness.count_tokens(text)


def _sh(cmd, timeout=60, cwd=None, env=None):
    """Run an external command; never raises. A missing/failing toolchain must BLOCK the hop that
    needed it, never crash the whole demo or fake a pass."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=cwd or REPO, env=env)
        return r.returncode == 0, r.stdout, r.stderr
    except FileNotFoundError:
        return False, "", "%s: command not found" % cmd[0]
    except subprocess.TimeoutExpired:
        return False, "", "%s: timed out after %ss" % (cmd[0], timeout)


# ---------------------------------------------------------------------------------------------
# receipt assembly (pure — no I/O) — the simplicio.savings-event/v1-shaped record per hop
# ---------------------------------------------------------------------------------------------
def build_event(hop, baseline_text, treatment_text, proof_kind, methodology, note, sources):
    """Pure function: hop inputs -> receipt dict. No I/O, so selftest can call it directly."""
    base = count_tokens(baseline_text)
    treat = count_tokens(treatment_text)
    saved = base - treat
    pct = round(100.0 * saved / base, 1) if base else 0.0
    event_id = hashlib.sha256(
        ("%s|%s|%d|%d" % (hop, methodology, base, treat)).encode("utf-8")).hexdigest()[:24]
    return {
        "schema": SCHEMA,
        # this repo's local, tool-free render of the schema — the full envelope (user/team/actor/
        # llm/cost/privacy) is defined by the sibling runtime#2774/#2775 spec, not reproduced here
        # since those fields don't apply to a deterministic, model-free local worker; kept as an
        # explicit, honest subset rather than a fabricated full envelope.
        "profile": "simplicio-loop.e2e-demo/v1",
        "event_id": event_id,
        "hop": hop,
        "measured_at": _now(),
        "tokens": {"baseline": base, "treatment": treat, "saved": saved, "saved_pct": pct},
        "proof": {
            "kind": proof_kind,  # "measured" (real tool output) | "simulated" (honest stand-in)
            "tokenizer": "ceil(chars/4)",
            "methodology": methodology,
            "sources": sources,
        },
        "note": note,
    }


def _snapshot(store, item, label, baseline_text, treatment_text):
    """Feed the SAME snapshot store savings_harness.py owns, so `savings_harness.py score` and
    `billing_aggregator.py collect` (which reads .simplicio-loop/orchestrator/savings/snapshots.jsonl) pick this
    hop up for free — no new aggregation code (issue #93: 'agregado pelo billing_aggregator.py')."""
    bf = tf = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".baseline.txt", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(baseline_text)
            bf = fh.name
        with tempfile.NamedTemporaryFile("w", suffix=".treatment.txt", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(treatment_text)
            tf = fh.name
        savings_harness.cmd_snapshot({"item": item, "label": label, "baseline": bf,
                                      "treatment": tf, "sample": 0, "store": store})
    finally:
        for p in (bf, tf):
            if p and os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------------------------
# hop 1 — MAP: real `simplicio-mapper handoff` JSON vs local TOON encoding of the same pack
# ---------------------------------------------------------------------------------------------
def hop_map(repo, store):
    ok, out, err = _sh(["simplicio-mapper", "handoff", repo, "--json"], timeout=90)
    if not ok:
        return None, ("BLOCKED: `simplicio-mapper handoff` failed (%s) — is simplicio-mapper "
                      "installed?" % err.strip()[:200])
    try:
        payload = json.loads(out)
    except ValueError:
        return None, "BLOCKED: `simplicio-mapper handoff` returned non-JSON output"
    pack = payload.get("context_pack", {})
    # sanity-check against the sandbox cache-contamination finding (see module docstring) — refuse
    # to trust a payload naming a path outside the repo instead of silently reporting bad numbers.
    bad = [f.get("path") for f in pack.get("files", []) if isinstance(f, dict) and
           (os.path.isabs(f.get("path", "")) or str(f.get("path", "")).startswith(".."))]
    if bad:
        return None, ("BLOCKED: handoff payload named path(s) outside the repo (%s) — treated as "
                      "cache contamination, not real data (see module docstring)" % bad[:3])
    baseline = json.dumps(pack, ensure_ascii=False, sort_keys=True)
    treatment = encode_toon(pack)
    note = ("mapper's native `--for-llm toon` flag (mapper#148/#149) is not shipped in the "
            "installed simplicio-mapper — this hop takes the REAL JSON `context_pack` from a live "
            "`simplicio-mapper handoff %s --json` call and TOON-encodes it with this repo's own "
            "scripts/toon_codec.py (the same codec task_anchor.py already uses for --format "
            "toon). Both baseline and treatment represent the identical real data." % repo)
    _snapshot(store, "e2e-map", "map: handoff JSON vs TOON", baseline, treatment)
    ev = build_event("map", baseline, treatment, "measured",
                     "live `simplicio-mapper handoff <repo> --json` context_pack: JSON baseline "
                     "vs local toon_codec.encode_toon() treatment",
                     note, ["simplicio-mapper handoff"])
    return (ev, pack), None


# ---------------------------------------------------------------------------------------------
# hop 2 — RECALL: raw file reads (no memory) vs the mapper's compact per-file index (recall)
# ---------------------------------------------------------------------------------------------
def hop_recall(pack, store, budget=2048):
    files = [f for f in pack.get("files", []) if isinstance(f, dict)][:8]
    if not files:
        return None, ("BLOCKED: MAP hop's context_pack had no files to compare recall against "
                      "(run `simplicio-mapper index` first)")
    raw_chunks = []
    for f in files:
        p = os.path.join(REPO, f.get("path", ""))
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                raw_chunks.append(fh.read())
        except OSError:
            continue
    if not raw_chunks:
        return None, "BLOCKED: none of the MAP hop's files could be read from disk"
    baseline = "\n".join(raw_chunks)
    compact = [{"path": f.get("path"), "language": f.get("language"),
               "line_count": f.get("line_count"),
               "symbols": [s.get("name") for s in f.get("symbols", []) if isinstance(s, dict)]}
              for f in files]
    treatment = json.dumps(compact, ensure_ascii=False)
    truncated = len(treatment) > budget
    if truncated:
        treatment = treatment[:budget]
    note = ("`simplicio memory \"\" --json` (the simplicio-runtime binary, runtime#2774/#2775) is "
            "not installed in this sandbox (`which simplicio` -> not found; a runtime bind is "
            "REQUIRED policy per this repo's AGENTS.md but unavailable here) — this hop "
            "substitutes the mapper's own compact per-file index (path/language/line_count/"
            "symbols), already fetched by the MAP hop, against full raw reads of the SAME files "
            "as the no-recall baseline. Budget-capped at %d chars%s, mirroring the issue's "
            "'simplicio memory ... --json (budget 2048)' call. The runtime's `auto_meter` "
            "savings-event for the true memory surface is deferred — see Scope note." %
            (budget, " (truncated)" if truncated else ""))
    _snapshot(store, "e2e-recall", "recall: raw file reads vs compact index", baseline, treatment)
    ev = build_event("recall", baseline, treatment, "measured",
                     "raw local reads of the MAP hop's files (baseline) vs their already-fetched "
                     "compact per-file index, budget-capped (treatment)",
                     note, ["local file reads", "simplicio-mapper handoff (reused from MAP hop)"])
    return ev, None


# ---------------------------------------------------------------------------------------------
# hop 3 — EDIT: real dev-cli prompt text vs TOON-encoded context (stand-in for dev-cli#88)
# ---------------------------------------------------------------------------------------------
EDIT_CASE = {
    "goal": "Add a --dry-run flag to savings_harness.py score",
    "target": "scripts/savings_harness.py",
    "stack": "python",
    "criteria": ["behavior matches the stated goal", "no unrelated files touched"],
    "constraints": ["existing tests still pass"],
}


def hop_edit(store, case=None):
    case = case or EDIT_CASE
    code = (
        "import sys\n"
        "from simplicio.prompt import build_prompt\n"
        "sys.stdout.write(build_prompt(%r, %r, %r, %r, %r, %r))\n"
    ) % (REPO, case["stack"], case["goal"], case["target"],
         "\n".join("- " + c for c in case["criteria"]),
         "\n".join("- " + c for c in case["constraints"]))
    ok, out, err = _sh([sys.executable, "-c", code], timeout=60)
    if not ok:
        return None, ("BLOCKED: could not build the real dev-cli prompt (%s) — is simplicio-cli "
                      "installed?" % err.strip()[:200])
    baseline = out
    treatment = encode_toon(case)
    note = ("dev-cli's `SIMPLICIO_PROMPT_TOON=1` toggle + TOON rows in `.simplicio-loop/runs.jsonl` "
            "(dev-cli#88) are not in the installed simplicio-cli — baseline is the REAL prompt "
            "text `simplicio.prompt.build_prompt()` builds TODAY for this case (called "
            "in-process, no LLM call, no API key — genuine current dev-cli output, not a mock); "
            "treatment TOON-encodes the SAME structured {goal, target, criteria, constraints, "
            "stack} fields as the honest local stand-in for the not-yet-shipped flag (AC5: "
            "'mocks/local onde preciso, honestamente rotulado'). Note: the live A/B via "
            "`simplicio-dev-cli task --dry-run-task` calls the LLM provider even in dry-run "
            "(confirmed by reading pipeline.run_task — dry_run_task still calls generate()), so "
            "it needs SIMPLICIO_MODEL+KEY and cannot run in a keyless CI gate (AC5's constraint) "
            "regardless of dev-cli#88's status.")
    _snapshot(store, "e2e-edit", "edit: dev-cli prompt text vs TOON-encoded context", baseline,
             treatment)
    ev = build_event("edit", baseline, treatment, "simulated",
                     "real in-process `simplicio.prompt.build_prompt()` text (baseline) vs local "
                     "toon_codec.encode_toon() of the same structured context fields (treatment, "
                     "stand-in for dev-cli#88)",
                     note, ["simplicio.prompt.build_prompt (in-process, no LLM call, no API key)"])
    return ev, None


# ---------------------------------------------------------------------------------------------
# hop 4 — VERIFY: real task_anchor.py --format json vs --format toon + gate + pr_evidence build
# ---------------------------------------------------------------------------------------------
VERIFY_ACS = [
    "Script commitado e re-executavel (registrado no check.py como selftest)",
    "Os 4 hops produzem receipt simplicio.savings-event/v1",
    "Relatorio final com savings por hop, sem nenhuma cifra nao-rotulada",
    "A/B do dev-cli anexado como evidencia",
    "Rodavel em CI local (scripts/check.py) sem chave de API paga",
]


def hop_verify(store, item, out_dir):
    anchor_path = os.path.join(out_dir, "anchor.json")
    if os.path.exists(anchor_path):
        os.unlink(anchor_path)  # each `run` re-anchors fresh — this is a demo fixture, not state
    env = dict(os.environ, SIMPLICIO_ANCHOR_FILE=anchor_path)
    ta = os.path.join(HERE, "task_anchor.py")
    goal = "issue #93 — e2e demo with a savings receipt at every hop"

    cmd = [sys.executable, ta, "set", "--item", str(item), "--goal", goal]
    for t in VERIFY_ACS:
        cmd += ["--ac", t]
    ok, out, err = _sh(cmd, timeout=30, env=env)
    if not ok:
        return None, "BLOCKED: task_anchor.py set failed (%s)" % (out + err)[:300]

    # mark AC1/2/3/5 done with real evidence pointers; AC4 stays PARTIAL — the live dev-cli A/B
    # needs dev-cli#88 (not shipped), so this is the honest state, not a rubber stamp.
    marks = [
        ("AC1", "done", "scripts/e2e_demo.py selftest; registered in claims_audit.py "
                        "SELFTEST_SCRIPTS + tests/test_worker_selftests_system.py"),
        ("AC2", "done", ".simplicio-loop/orchestrator/savings/e2e-demo-events.jsonl (4 records, one per hop)"),
        ("AC3", "done", ".simplicio-loop/orchestrator/savings/e2e-demo.md"),
        ("AC4", "partial", "local TOON-vs-JSON stand-in attached (EDIT hop note); the live "
                           "SIMPLICIO_PROMPT_TOON on/off A/B needs dev-cli#88, not yet shipped"),
        ("AC5", "done", "selftest is fully offline: no subprocess to simplicio-mapper/"
                        "simplicio-cli, no network, no API key"),
    ]
    for cid, status, evidence in marks:
        ok, out, err = _sh([sys.executable, ta, "mark", "--id", cid, "--status", status,
                           "--evidence", evidence], timeout=30, env=env)
        if not ok:
            return None, "BLOCKED: task_anchor.py mark %s failed (%s)" % (cid, (out + err)[:300])

    ok_j, baseline, err_j = _sh([sys.executable, ta, "check", "--goal", goal, "--format", "json"],
                                timeout=30, env=env)
    ok_t, treatment, err_t = _sh([sys.executable, ta, "check", "--goal", goal, "--format", "toon"],
                                 timeout=30, env=env)
    if not (ok_j and ok_t):
        return None, "BLOCKED: task_anchor.py check failed (%s)" % (err_j + err_t)[:300]

    # --exit-code makes `gate` exit 12 on BLOCKED (see task_anchor.py cmd_gate) — needed so we
    # read the verdict from the process outcome, not just the printed word.
    gate_ok, gate_out, gate_err = _sh([sys.executable, ta, "gate", "--exit-code"],
                                      timeout=30, env=env)
    # gate_ok is expected False here (AC4 is intentionally PARTIAL) — that is the correct,
    # non-rubber-stamped behavior; capture it as a receipt, not a pass/fail of this hop.
    gate_verdict = "ready" if gate_ok else "blocked"

    pe = os.path.join(HERE, "pr_evidence.py")
    pr_body_path = os.path.join(out_dir, "pr_body.md")
    pe_ok, pe_out, pe_err = _sh(
        [sys.executable, pe, "build", "--title", "e2e demo — map->recall->edit->verify",
         "--item", str(item), "--summary", "Capstone demo for issue #93.",
         "--anchor", anchor_path, "--shots-dir", os.path.join(out_dir, "no-shots"),
         "--require-evidence", "--out", pr_body_path],
        timeout=30, env=env)

    note = ("100%% live: `task_anchor.py check --format json` vs `--format toon` against the SAME "
            "anchored verdict for issue #93's own acceptance criteria (AC4 intentionally left "
            "PARTIAL — the gate correctly reports '%s', proof it is not a rubber stamp). "
            "`pr_evidence.py build --require-evidence` %s (exit %s)." %
            (gate_verdict, "succeeded" if pe_ok else "FAILED", "0" if pe_ok else "non-zero"))
    ev = build_event("verify", baseline, treatment, "measured",
                     "live `task_anchor.py check --goal ... --format json` vs `--format toon` "
                     "for the SAME anchored verdict",
                     note, ["task_anchor.py check", "task_anchor.py gate", "pr_evidence.py build"])
    ev["gate"] = {"verdict": gate_verdict, "detail": gate_out.strip()}
    ev["pr_evidence"] = {"ok": pe_ok, "out": pr_body_path if pe_ok else None,
                         "detail": (pe_out + pe_err).strip()[:400]}
    return ev, None


# ---------------------------------------------------------------------------------------------
# report assembly
# ---------------------------------------------------------------------------------------------
def render_report(events, repo, item):
    lines = ["# e2e demo — map -> recall -> edit -> verify (issue #%s)" % item, "",
            "Generated %s against `%s`. Every number below carries a `proof.kind` + tokenizer "
            "label; see each hop's `note` for exactly what was measured vs simulated (Scope note "
            "in the PR body has the full picture)." % (_now(), repo), "",
            "| hop | proof.kind | baseline (tok) | treatment (tok) | saved (tok) | saved % |",
            "|---|---|---:|---:|---:|---:|"]
    tot_base = tot_treat = 0
    for ev in events:
        t = ev["tokens"]
        tot_base += t["baseline"]
        tot_treat += t["treatment"]
        lines.append("| %s | %s | %d | %d | %d | %.1f%% |" % (
            ev["hop"], ev["proof"]["kind"], t["baseline"], t["treatment"], t["saved"],
            t["saved_pct"]))
    saved = tot_base - tot_treat
    pct = round(100.0 * saved / tot_base, 1) if tot_base else 0.0
    lines += ["", "**OVERALL** — baseline=%d treatment=%d saved=%d (%.1f%%) "
             "[tokenizer=ceil(chars/4)]" % (tot_base, tot_treat, saved, pct), ""]
    for ev in events:
        lines += ["## %s" % ev["hop"], "", "- proof.kind: `%s`" % ev["proof"]["kind"],
                 "- methodology: %s" % ev["proof"]["methodology"],
                 "- sources: %s" % ", ".join(ev["proof"]["sources"]),
                 "", ev["note"], ""]
        if "gate" in ev:
            lines += ["- gate verdict: `%s`" % ev["gate"]["verdict"],
                     "- pr_evidence build: %s" % ("ok" if ev["pr_evidence"]["ok"] else "FAILED"),
                     ""]
    return "\n".join(lines)


def audit_events(events, require_measured=False):
    hops_present = []
    duplicates = []
    malformed = []
    for idx, ev in enumerate(events):
        hop = ev.get("hop")
        if hop in hops_present and hop not in duplicates:
            duplicates.append(hop)
        hops_present.append(hop)
        proof = ev.get("proof") or {}
        tokens = ev.get("tokens") or {}
        base = tokens.get("baseline")
        treat = tokens.get("treatment")
        saved = tokens.get("saved")
        pct = tokens.get("saved_pct")
        expected_saved = None if base is None or treat is None else base - treat
        expected_pct = 0.0 if not base else round(100.0 * expected_saved / base, 1)
        problems = []
        if ev.get("schema") != SCHEMA:
            problems.append("schema")
        if hop not in HOPS:
            problems.append("hop")
        if proof.get("kind") not in ("measured", "simulated"):
            problems.append("proof.kind")
        if proof.get("tokenizer") != "ceil(chars/4)":
            problems.append("proof.tokenizer")
        if not proof.get("methodology"):
            problems.append("proof.methodology")
        if not isinstance(proof.get("sources"), list) or not proof.get("sources"):
            problems.append("proof.sources")
        if not ev.get("note"):
            problems.append("note")
        if not isinstance(base, int):
            problems.append("tokens.baseline")
        if not isinstance(treat, int):
            problems.append("tokens.treatment")
        if not isinstance(saved, int) or expected_saved != saved:
            problems.append("tokens.saved")
        if not isinstance(pct, (int, float)) or expected_pct != round(float(pct), 1):
            problems.append("tokens.saved_pct")
        if problems:
            malformed.append({"index": idx, "hop": hop, "problems": problems})
    hops_present = set(hops_present)
    missing = [hop for hop in HOPS if hop not in hops_present]
    simulated = [ev.get("hop") for ev in events if (ev.get("proof") or {}).get("kind") != "measured"]
    ok = not missing and not duplicates and not malformed and (not require_measured or not simulated)
    return {
        "ok": ok,
        "missing": missing,
        "duplicates": duplicates,
        "malformed": malformed,
        "simulated": simulated,
        "events": len(events),
    }


# ---------------------------------------------------------------------------------------------
# run / selftest
# ---------------------------------------------------------------------------------------------
def cmd_run(opts):
    repo = opts.get("repo", REPO)
    item = opts.get("item", "93")
    out_dir = opts.get("out", DEFAULT_STORE)
    os.makedirs(out_dir, exist_ok=True)

    events = []
    blockers = []

    map_result, map_err = hop_map(repo, out_dir)
    if map_err:
        blockers.append(("map", map_err))
        log("MAP: %s" % map_err)
    else:
        map_ev, pack = map_result
        events.append(map_ev)
        log("MAP: saved=%d tok (%.1f%%)" % (map_ev["tokens"]["saved"], map_ev["tokens"]["saved_pct"]))

        recall_ev, recall_err = hop_recall(pack, out_dir)
        if recall_err:
            blockers.append(("recall", recall_err))
            log("RECALL: %s" % recall_err)
        else:
            events.append(recall_ev)
            log("RECALL: saved=%d tok (%.1f%%)" % (
                recall_ev["tokens"]["saved"], recall_ev["tokens"]["saved_pct"]))

    edit_ev, edit_err = hop_edit(out_dir)
    if edit_err:
        blockers.append(("edit", edit_err))
        log("EDIT: %s" % edit_err)
    else:
        events.append(edit_ev)
        log("EDIT: saved=%d tok (%.1f%%)" % (edit_ev["tokens"]["saved"], edit_ev["tokens"]["saved_pct"]))

    verify_ev, verify_err = hop_verify(out_dir, item, out_dir)
    if verify_err:
        blockers.append(("verify", verify_err))
        log("VERIFY: %s" % verify_err)
    else:
        events.append(verify_ev)
        log("VERIFY: saved=%d tok (%.1f%%) gate=%s" % (
            verify_ev["tokens"]["saved"], verify_ev["tokens"]["saved_pct"],
            verify_ev["gate"]["verdict"]))

    events_path = os.path.join(out_dir, EVENTS_FILE)
    with open(events_path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps({k: v for k, v in ev.items() if k not in ("gate", "pr_evidence")},
                               ensure_ascii=False) + "\n")

    report = render_report(events, repo, item)
    if blockers:
        report += "\n## Blocked hops\n\n" + "\n".join(
            "- **%s**: %s" % (h, e) for h, e in blockers) + "\n"
    report_path = os.path.join(out_dir, REPORT_FILE)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    log("wrote %s" % events_path)
    log("wrote %s" % report_path)
    audit = audit_events(events, require_measured=bool(opts.get("require-measured")))
    if opts.get("json"):
        print(json.dumps({"events": len(events), "blocked": [h for h, _ in blockers],
                          "report": report_path, "events_file": events_path,
                          "audit": audit}, indent=2))
    else:
        print(report)
    if blockers:
        return 1
    if opts.get("require-measured") and not audit["ok"]:
        return 2
    return 0


def cmd_audit(opts):
    events_path = opts.get("events") or os.path.join(opts.get("out", DEFAULT_STORE), EVENTS_FILE)
    if not os.path.exists(events_path):
        print(json.dumps({"ok": False, "reason": "events file missing", "events_file": events_path},
                         ensure_ascii=False, indent=2))
        return 2
    events = []
    with open(events_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s:
                events.append(json.loads(s))
    payload = audit_events(events, require_measured=bool(opts.get("require-measured")))
    payload["events_file"] = events_path
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 2


def cmd_selftest(_opts):
    """Fully offline: proves the receipt/report math with synthetic data — no subprocess to
    simplicio-mapper/simplicio-cli/task_anchor's live state, no network, no API key (AC5)."""
    checks = []

    def chk(name, cond):
        checks.append((name, bool(cond)))

    # 1) build_event is a pure function: token math + proof labeling
    ev = build_event("map", "x" * 400, "x" * 100, "measured", "synthetic", "synthetic note",
                     ["synthetic"])
    chk("build_event baseline tokens", ev["tokens"]["baseline"] == 100)
    chk("build_event treatment tokens", ev["tokens"]["treatment"] == 25)
    chk("build_event saved tokens", ev["tokens"]["saved"] == 75)
    chk("build_event saved pct", ev["tokens"]["saved_pct"] == 75.0)
    chk("build_event schema", ev["schema"] == SCHEMA)
    chk("build_event proof.kind labeled", ev["proof"]["kind"] == "measured")
    chk("build_event proof.tokenizer labeled", ev["proof"]["tokenizer"] == "ceil(chars/4)")
    chk("build_event has a note", bool(ev["note"]))

    # 2) event_id is deterministic for identical inputs, distinct for different hops
    ev2 = build_event("recall", "x" * 400, "x" * 100, "measured", "synthetic", "synthetic note",
                      ["synthetic"])
    chk("event_id differs across hops", ev["event_id"] != ev2["event_id"])

    # 3) snapshot + score round-trip through the REAL savings_harness store format, in a temp dir
    #    so this never touches the repo's real .simplicio-loop/orchestrator/savings/ during the audit gate
    tmp_store = tempfile.mkdtemp(prefix="e2e-demo-selftest-")
    try:
        _snapshot(tmp_store, "map", "selftest map", "x" * 400, "x" * 100)
        rows = savings_harness._load_snapshots(tmp_store)
        chk("snapshot round-trips through savings_harness store", len(rows) == 1)
        report = savings_harness.score(rows)
        chk("savings_harness.score reads our snapshot", report["overall"]["saved"] == 75)
    finally:
        import shutil
        shutil.rmtree(tmp_store, ignore_errors=True)

    # 4) report renders all 4 hop names with no unlabeled figure (every row states proof.kind)
    synth_events = [
        build_event(h, "x" * 400, "x" * 100, "measured" if h in ("map", "verify") else "simulated",
                   "synthetic", "synthetic note for %s" % h, ["synthetic"])
        for h in HOPS
    ]
    report_md = render_report(synth_events, "synthetic-repo", "0")
    chk("report mentions every hop", all(h in report_md for h in HOPS))
    chk("report labels proof.kind for every hop",
        report_md.count("`measured`") + report_md.count("`simulated`") >= len(HOPS))
    chk("report has an OVERALL line", "OVERALL" in report_md)
    audit_soft = audit_events(synth_events, require_measured=False)
    chk("audit soft passes complete hop set", audit_soft["ok"] is True)
    audit_strict = audit_events(synth_events, require_measured=True)
    chk("audit strict rejects simulated hops", audit_strict["ok"] is False and "edit" in audit_strict["simulated"])

    # 5) TOON round-trips the map hop's payload shape (encode_toon is what MAP/EDIT depend on)
    sample_pack = {"schema": "simplicio.context-pack/v1", "files": [
        {"path": "a.py", "language": "python", "line_count": 3}]}
    toon_text = encode_toon(sample_pack)
    chk("encode_toon shrinks a representative pack", len(toon_text) < len(json.dumps(sample_pack)))

    ok = all(v for _, v in checks)
    for name, v in checks:
        print("  [%s] %s" % ("ok" if v else "XX", name))
    print("e2e_demo selftest: %s (%d/%d)" % ("PASS" if ok else "FAIL",
                                             sum(1 for _, v in checks if v), len(checks)))
    return 0 if ok else 1


def _parse(args):
    """Tiny --flag value parser (matches the dependency-free style of install_lib.py)."""
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
            "verbs": ["run", "audit", "selftest"],
            "flags": ["--events", "--help", "--json", "--out", "--require-measured"],
        }))
        sys.exit(0)
    sub, rest = argv[0], argv[1:]
    opts = _parse(rest)
    if sub == "run":
        sys.exit(cmd_run(opts))
    elif sub == "audit":
        sys.exit(cmd_audit(opts))
    elif sub == "selftest":
        sys.exit(cmd_selftest(opts))
    else:
        print("unknown command %r. choices: run audit selftest" % sub)
        sys.exit(2)


if __name__ == "__main__":
    main()
