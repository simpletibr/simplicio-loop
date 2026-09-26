#!/usr/bin/env python3
"""simplicio-autoresearch — evolutionary mutate/eval/keep-revert optimizer, yool-guardrailed.

Adapts Karpathy's `autoresearch` pattern (mutate a target -> evaluate against fixed criteria ->
KEEP if the score improves (commit) -> REVERT if it doesn't (git checkout) -> repeat, with a
plateau-break after N stagnated runs) into a deterministic, model-free BOOKKEEPING harness. This
worker never calls an LLM and never invents a mutation itself — the skill (the LLM driving the
loop) proposes the edit; this script enforces the mechanical contract around it: mandatory
iteration/token caps (yool guardrails §11 — a cap-less loop is a review-blocker, not a nice-to-
have), git-isolated branch discipline (never `main`/`master`), an anti-Goodhart eval order
(correctness GATE first, score SECOND — a failing gate is always `revert`, regardless of score),
and a `simplicio.savings-event/v1`-shaped receipt per run.

State: `<git-root>/.simplicio-loop/orchestrator/autoresearch/<slug>/` (override with --store or
$SIMPLICIO_AUTORESEARCH_STORE):
    config.json    guardrails + eval command + baseline, frozen at `init`
    journal.jsonl  one append-only record per attempt: {iteration, gate, score, decision, note, ts}
    receipt.json   written by `finish` — the run's savings-event receipt

Verbs:
  init      Freeze the run: --target FILE --eval "CMD" --max-iterations N --max-token-budget N
            (BOTH caps are MANDATORY — yool §11; a cap-less loop refuses to start). Resolves the
            target's git root, refuses to run on main/master, creates/checks out an isolated
            `autoresearch/<slug>` branch, records the pre-mutation HEAD, and runs the eval command
            ONCE to capture the baseline (gate + score).
  eval      Run the frozen eval command now against the current tree; parse + print gate/score.
  record    Append one attempt: --iteration N (must be <= max-iterations, else BLOCKED) plus
            either --gate/--score (explicit, e.g. for scripted/test use) or nothing (runs the
            live eval). Decides keep|revert (gate-first: any non-"pass" gate is ALWAYS revert,
            no matter how good the score) and performs the matching scoped git action
            (`git add <target> && git commit` on keep; `git checkout -- <target>` on revert —
            never touches anything outside the target file(s)).
  plateau   PROGRESS | PLATEAU verdict from the trailing consecutive-revert streak (--plateau-n,
            default 5, frozen at init). Exit 10 on PLATEAU with --exit-code — the loop must then
            plateau-break (a full rewrite of the target, not another small nudge) and record it
            with `record --plateau-break` to reset the streak.
  finish    Squash every kept commit since the branch's start HEAD into one Conventional Commit,
            write the run receipt (`simplicio.savings-event/v1`), and print a summary. Refuses
            (BLOCKED, exit 12) if the final kept state's gate isn't "pass".
  status    Print config + plateau streak + a tail of the journal.
  selftest  Prove decide()/plateau_verdict()/parse_eval_output()/slugify() deterministically — no
            git, no files, no network.

Usage:
    python3 scripts/autoresearch.py init --target src/encoder.py --eval "pytest -q tests/test_encoder.py" \\
        --max-iterations 20 --max-token-budget 50000
    python3 scripts/autoresearch.py record --iteration 1 --note "tried delta-encoding the offsets"
    python3 scripts/autoresearch.py plateau --exit-code
    python3 scripts/autoresearch.py finish --message "perf: shrink TOON encoder output"
    python3 scripts/autoresearch.py selftest
"""
import json
import os
import re
import subprocess
import sys
import time

try:  # Windows consoles default to cp1252 and choke on non-ASCII — force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

CONFIG_NAME = "config.json"
JOURNAL_NAME = "journal.jsonl"
RECEIPT_NAME = "receipt.json"
PROTECTED_BRANCHES = ("main", "master")
DEFAULT_CPU_QUOTA_PCT = 60
DEFAULT_DISK_QUOTA_MB = 100
DEFAULT_TIMEOUT_S = 300
DEFAULT_PLATEAU_N = 5
DEFAULT_MARGIN = 0.0
DEFAULT_DIRECTION = "max"
DEFAULT_METRIC_KEY = "score"
YOOL_ID = "agent.dev.autoresearch"
HEALTH_CHECK_EVERY = 10
SCHEMA = "simplicio.savings-event/v1"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_GATE_RE = re.compile(r"\bgate\s*[:=]\s*(pass|fail)\b", re.I)
_SCORE_RE = re.compile(r"\bscore\s*[:=]\s*(-?\d+(?:\.\d+)?)\b", re.I)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)


def log(msg):
    print("  " + msg)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ----- pure helpers (selftest exercises these directly, no I/O) -----------------------------------

def slugify(text, max_len=40):
    """Deterministic, filesystem-safe slug — used to name the isolated branch + store dir."""
    s = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return (s or "target")[:max_len].strip("-") or "target"


def decide(gate, score, best_score, margin=DEFAULT_MARGIN, direction=DEFAULT_DIRECTION):
    """The anti-Goodhart core: correctness gate FIRST, score SECOND.

    A non-"pass" gate is ALWAYS "revert", regardless of how good the score looks — a mutation
    that breaks the correctness gate can never be kept no matter what it does to the metric.
    Only once the gate passes does the score decide: "keep" when it improves on best_score by
    more than `margin` in the configured `direction` (max = higher is better, min = lower is
    better, e.g. token count / latency). The FIRST passing attempt (best_score is None) is always
    kept — it establishes the run's working baseline-of-record.
    """
    if gate != "pass":
        return "revert"
    if best_score is None:
        return "keep"
    if score is None:
        return "revert"
    if direction == "min":
        improved = score < (best_score - margin)
    else:
        improved = score > (best_score + margin)
    return "keep" if improved else "revert"


def plateau_verdict(decisions, k=DEFAULT_PLATEAU_N):
    """PROGRESS | PLATEAU from the trailing consecutive-revert streak.

    `decisions` is the chronological list of "keep" / "revert" / "plateau-break" strings. A
    "keep" OR an explicit "plateau-break" marker resets the streak (the latter lets the loop
    acknowledge a plateau-break rewrite without needing a real keep first). PLATEAU when the
    trailing streak of consecutive "revert" reaches k.
    """
    streak = 0
    for d in decisions:
        if d == "revert":
            streak += 1
        else:
            streak = 0
    verdict = "PLATEAU" if streak >= k else "PROGRESS"
    return {"verdict": verdict, "streak": streak, "k": k}


def needs_health_check(iteration):
    """True every HEALTH_CHECK_EVERY iterations (run 10, 20, ...) — remind the loop to re-validate
    the binary criteria + validation set haven't quietly drifted (Goodhart creep)."""
    return iteration > 0 and iteration % HEALTH_CHECK_EVERY == 0


def parse_eval_output(text, metric_key=DEFAULT_METRIC_KEY):
    """Turn the eval command's raw stdout+stderr into (gate, score).

    Tries, in order: (1) the WHOLE output as one JSON object; (2) the LAST balanced-looking
    `{...}` blob in the output as JSON; (3) `gate: pass|fail` / `score: <num>` regex lines. A
    boolean `gate` (true/false) is accepted and mapped to pass/fail. Anything unparseable is
    treated as gate="fail" (a metric the harness can't read can never justify a "keep" — the
    correctness-first rule extends to the plumbing itself), never silently ignored.
    """
    text = (text or "").strip()
    if not text:
        return "fail", None

    def _from_obj(obj):
        if not isinstance(obj, dict):
            return None
        gate = obj.get("gate")
        if isinstance(gate, bool):
            gate = "pass" if gate else "fail"
        gate = str(gate).strip().lower() if gate is not None else None
        score = obj.get(metric_key)
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        if gate not in ("pass", "fail"):
            return None
        return gate, score

    try:
        got = _from_obj(json.loads(text))
        if got:
            return got
    except ValueError:
        pass

    m = _JSON_OBJ_RE.search(text)
    if m:
        try:
            got = _from_obj(json.loads(m.group(0)))
            if got:
                return got
        except ValueError:
            pass

    gm = _GATE_RE.search(text)
    sm = _SCORE_RE.search(text)
    if gm:
        gate = gm.group(1).lower()
        score = float(sm.group(1)) if sm else None
        return gate, score

    return "fail", None


def build_receipt(config, journal, final):
    kept = sum(1 for r in journal if r.get("decision") == "keep")
    reverted = sum(1 for r in journal if r.get("decision") == "revert")
    plateau_breaks = sum(1 for r in journal if r.get("decision") == "plateau-break")
    baseline = config.get("baseline", {})
    return {
        "schema": SCHEMA,
        "source": "autoresearch",
        "yool_id": YOOL_ID,
        "target": config.get("target"),
        "branch": config.get("branch"),
        "created_at": _now(),
        "baseline": {"gate": baseline.get("gate"), "score": baseline.get("score")},
        "actual": {"gate": final.get("gate"), "score": final.get("score")},
        "proof": {"kind": "autoresearch-eval-log",
                  "path": os.path.join(config.get("store_rel", ""), JOURNAL_NAME)},
        "tokenizer": config.get("tokenizer_id", "n/a"),
        "metric_key": config.get("metric_key", DEFAULT_METRIC_KEY),
        "direction": config.get("direction", DEFAULT_DIRECTION),
        "iterations": len(journal),
        "kept": kept,
        "reverted": reverted,
        "plateau_breaks": plateau_breaks,
        "guardrails": config.get("guardrails", {}),
    }


# ----- git + process helpers ----------------------------------------------------------------------

def _git(args, cwd):
    try:
        r = subprocess.run(["git"] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=cwd)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 127, "", "git not found"


def _git_root(path):
    rc, out, _ = _git(["rev-parse", "--show-toplevel"], cwd=path)
    return out if rc == 0 and out else None


def _current_branch(repo_root):
    rc, out, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    return out if rc == 0 else ""


def _run_eval(cmd, cwd, timeout_s):
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout_s or None)
        return (r.stdout or "") + "\n" + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return json.dumps({"gate": "fail", "score": None,
                            "error": "eval command timed out after %ss" % timeout_s})


# ----- I/O + commands ------------------------------------------------------------------------------

def _default_store_root(repo_root, slug):
    return os.path.join(repo_root, ".simplicio-loop/orchestrator", "autoresearch", slug)


def _resolve_store(opts, required=True):
    store = opts.get("store") or os.environ.get("SIMPLICIO_AUTORESEARCH_STORE")
    if not store and required:
        print("autoresearch: no --store given (and $SIMPLICIO_AUTORESEARCH_STORE unset) — "
              "run `init` first and reuse its printed --store path.")
        sys.exit(2)
    return store


def _load_config(store):
    path = os.path.join(store, CONFIG_NAME)
    if not os.path.exists(path):
        print("autoresearch: no run initialized at %s — run `init` first." % store)
        sys.exit(2)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_config(store, config):
    os.makedirs(store, exist_ok=True)
    with open(os.path.join(store, CONFIG_NAME), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _load_journal(store):
    path = os.path.join(store, JOURNAL_NAME)
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _append_journal(store, record):
    with open(os.path.join(store, JOURNAL_NAME), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _positive_int(opts, key, label):
    raw = opts.get(key)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = -1
    if n <= 0:
        print("autoresearch: BLOCKED — --%s is MANDATORY and must be a positive integer "
              "(yool guardrails §11: a cap-less loop is blocked, not optional). got: %r"
              % (label, raw))
        sys.exit(2)
    return n


def cmd_init(opts):
    target = opts.get("target")
    eval_cmd = opts.get("eval")
    if not target or not os.path.isfile(target):
        print("autoresearch: --target must be an existing file. got: %r" % target)
        sys.exit(2)
    if not eval_cmd or not str(eval_cmd).strip():
        print("autoresearch: --eval \"<command>\" is required.")
        sys.exit(2)

    max_iterations = _positive_int(opts, "max-iterations", "max-iterations")
    max_token_budget = _positive_int(opts, "max-token-budget", "max-token-budget")

    target_abs = os.path.abspath(target)
    repo_root = _git_root(os.path.dirname(target_abs))
    if not repo_root:
        print("autoresearch: --target is not inside a git repo — git isolation is mandatory.")
        sys.exit(2)

    slug = slugify(opts.get("slug") or os.path.basename(target_abs))
    branch = opts.get("branch") or ("autoresearch/%s-%s" % (slug, time.strftime("%Y%m%d%H%M%S")))
    if not branch.startswith("autoresearch/") and not opts.get("allow-any-branch"):
        branch = "autoresearch/%s" % branch
    if branch.rsplit("/", 1)[-1] in PROTECTED_BRANCHES or branch in PROTECTED_BRANCHES:
        print("autoresearch: BLOCKED — refusing to run on %s. Isolated branch required." % branch)
        sys.exit(2)

    starting_branch = _current_branch(repo_root)
    if starting_branch in PROTECTED_BRANCHES and not opts.get("branch") and not opts.get("force"):
        log("currently on %r — creating isolated branch %r before mutating anything"
            % (starting_branch, branch))

    rc, _, _ = _git(["rev-parse", "--verify", branch], cwd=repo_root)
    if rc == 0:
        co_rc, _, co_err = _git(["checkout", branch], cwd=repo_root)
    else:
        co_rc, _, co_err = _git(["checkout", "-b", branch], cwd=repo_root)
    if co_rc != 0:
        print("autoresearch: BLOCKED — could not check out isolated branch %r: %s" % (branch, co_err))
        sys.exit(2)

    now_branch = _current_branch(repo_root)
    if now_branch in PROTECTED_BRANCHES:
        print("autoresearch: BLOCKED — refusing to proceed on %s after checkout." % now_branch)
        sys.exit(2)

    start_sha = _git(["rev-parse", "HEAD"], cwd=repo_root)[1]
    timeout_s = int(opts.get("timeout-s") or DEFAULT_TIMEOUT_S)

    store = opts.get("store") or _default_store_root(repo_root, slug)
    target_rel = os.path.relpath(target_abs, repo_root)

    baseline_raw = _run_eval(eval_cmd, repo_root, timeout_s)
    metric_key = opts.get("metric-key") or DEFAULT_METRIC_KEY
    b_gate, b_score = parse_eval_output(baseline_raw, metric_key)

    config = {
        "target": target_rel,
        "eval": eval_cmd,
        "repo_root": repo_root,
        "branch": branch,
        "start_sha": start_sha,
        "store_rel": os.path.relpath(store, repo_root),
        "slug": slug,
        "metric_key": metric_key,
        "direction": (opts.get("direction") or DEFAULT_DIRECTION).lower(),
        "margin": float(opts.get("margin") or DEFAULT_MARGIN),
        "plateau_n": int(opts.get("plateau-n") or DEFAULT_PLATEAU_N),
        "tokenizer_id": opts.get("tokenizer-id") or "n/a",
        "guardrails": {
            "cpu_quota_pct": int(opts.get("cpu-quota-pct") or DEFAULT_CPU_QUOTA_PCT),
            "disk_quota_mb": int(opts.get("disk-quota-mb") or DEFAULT_DISK_QUOTA_MB),
            "timeout_s": timeout_s,
            "max_iterations": max_iterations,
            "max_token_budget": max_token_budget,
        },
        "baseline": {"gate": b_gate, "score": b_score, "raw_excerpt": baseline_raw[:400]},
        "created_at": _now(),
    }
    _save_config(store, config)
    # truncate/create an empty journal for a fresh run
    open(os.path.join(store, JOURNAL_NAME), "w", encoding="utf-8").close()

    log("branch=%s (isolated, never main/master)" % branch)
    log("guardrails: max_iterations=%d max_token_budget=%d cpu_quota_pct=%d disk_quota_mb=%d "
        "timeout_s=%d" % (max_iterations, max_token_budget, config["guardrails"]["cpu_quota_pct"],
                          config["guardrails"]["disk_quota_mb"], timeout_s))
    print("MEASURED|baseline gate=%s score=%s" % (b_gate, b_score))
    print("store=%s" % store)


def cmd_eval(opts):
    store = _resolve_store(opts)
    config = _load_config(store)
    raw = _run_eval(config["eval"], config["repo_root"], config["guardrails"]["timeout_s"])
    gate, score = parse_eval_output(raw, config.get("metric_key", DEFAULT_METRIC_KEY))
    if opts.get("json"):
        print(json.dumps({"gate": gate, "score": score}))
    else:
        tag = "MEASURED" if gate in ("pass", "fail") else "UNVERIFIED"
        print("%s|gate=%s score=%s" % (tag, gate, score))


def cmd_record(opts):
    store = _resolve_store(opts)
    config = _load_config(store)
    journal = _load_journal(store)

    try:
        iteration = int(opts.get("iteration"))
    except (TypeError, ValueError):
        print("autoresearch: --iteration <N> is required.")
        sys.exit(2)
    max_iterations = config["guardrails"]["max_iterations"]
    if iteration > max_iterations:
        print("autoresearch: BLOCKED — iteration %d exceeds the frozen max_iterations cap %d. "
              "The loop MUST stop here (yool guardrail)." % (iteration, max_iterations))
        sys.exit(12)

    if opts.get("plateau-break"):
        gate = opts.get("gate") or "fail"
        score = float(opts["score"]) if opts.get("score") is not None else None
        decision = "plateau-break"
    else:
        if opts.get("gate") is not None:
            gate = str(opts["gate"]).strip().lower()
            score = float(opts["score"]) if opts.get("score") is not None else None
        else:
            raw = _run_eval(config["eval"], config["repo_root"], config["guardrails"]["timeout_s"])
            gate, score = parse_eval_output(raw, config.get("metric_key", DEFAULT_METRIC_KEY))

        kept = [r for r in journal if r.get("decision") == "keep"]
        best_score = kept[-1]["score"] if kept else config["baseline"].get("score")
        decision = decide(gate, score, best_score, config.get("margin", DEFAULT_MARGIN),
                          config.get("direction", DEFAULT_DIRECTION))

    target_rel = config["target"]
    repo_root = config["repo_root"]
    note = ""
    if decision == "keep":
        _git(["add", "--", target_rel], cwd=repo_root)
        msg = "autoresearch: iter %d score=%s gate=%s" % (iteration, score, gate)
        rc, out, err = _git(["commit", "-m", msg, "--", target_rel], cwd=repo_root)
        note = "committed" if rc == 0 else ("no-op: %s" % (err or out or "nothing to commit"))
    elif decision == "revert":
        rc, out, err = _git(["checkout", "--", target_rel], cwd=repo_root)
        note = "reverted" if rc == 0 else ("revert failed: %s" % (err or out))
    else:  # plateau-break marker — no git action, just resets the streak
        note = opts.get("note") or "plateau-break recorded"

    record = {
        "iteration": iteration,
        "gate": gate,
        "score": score,
        "decision": decision,
        "note": opts.get("note") or note,
        "mutation_summary": opts.get("mutation-summary") or "",
        "ts": _now(),
    }
    _append_journal(store, record)

    tag = "MEASURED" if gate in ("pass", "fail") else "UNVERIFIED"
    print("%s|iteration=%d decision=%s gate=%s score=%s (%s)" % (
        tag, iteration, decision, gate, score, note))
    if needs_health_check(iteration):
        print("HEALTH-CHECK|iteration %d — re-validate the binary criteria + validation set "
              "haven't drifted before continuing (anti-Goodhart)." % iteration)


def cmd_plateau(opts):
    store = _resolve_store(opts)
    config = _load_config(store)
    journal = _load_journal(store)
    k = int(opts.get("k") or config.get("plateau_n", DEFAULT_PLATEAU_N))
    decisions = [r.get("decision") for r in journal]
    v = plateau_verdict(decisions, k)
    print(v["verdict"].lower())
    log("streak=%d/%d consecutive reverts" % (v["streak"], k))
    if v["verdict"] == "PLATEAU":
        log("recommended: plateau-break — a full rewrite of the target, not another small nudge. "
            "Record it with `record --plateau-break` to reset the streak.")
    if opts.get("exit-code") and v["verdict"] == "PLATEAU":
        sys.exit(10)


def cmd_finish(opts):
    store = _resolve_store(opts)
    config = _load_config(store)
    journal = _load_journal(store)
    repo_root = config["repo_root"]

    kept = [r for r in journal if r.get("decision") == "keep"]
    final = kept[-1] if kept else dict(config["baseline"])
    if final.get("gate") != "pass":
        print("autoresearch: BLOCKED — the final kept state's gate is %r, not 'pass'. Refusing "
              "to finish a run whose winner doesn't pass the correctness gate." % final.get("gate"))
        sys.exit(12)

    commit_sha = None
    if kept and not opts.get("dry-run"):
        message = opts.get("message") or (
            "perf: autoresearch optimization of %s (score %s -> %s)"
            % (config["target"], config["baseline"].get("score"), final.get("score")))
        rc, _, err = _git(["reset", "--soft", config["start_sha"]], cwd=repo_root)
        if rc != 0:
            print("autoresearch: BLOCKED — could not squash to start_sha: %s" % err)
            sys.exit(2)
        rc, _, err = _git(["commit", "-m", message], cwd=repo_root)
        if rc != 0:
            print("autoresearch: BLOCKED — squash commit failed: %s" % err)
            sys.exit(2)
        commit_sha = _git(["rev-parse", "HEAD"], cwd=repo_root)[1]

    receipt = build_receipt(config, journal, final)
    if not opts.get("dry-run"):
        with open(os.path.join(store, RECEIPT_NAME), "w", encoding="utf-8") as f:
            json.dump(receipt, f, ensure_ascii=False, indent=2)

    print("MEASURED|verdict=done kept=%d reverted=%d plateau_breaks=%d" % (
        receipt["kept"], receipt["reverted"], receipt["plateau_breaks"]))
    print("MEASURED|baseline=%s final=%s" % (receipt["baseline"]["score"], receipt["actual"]["score"]))
    print("commit=%s" % (commit_sha or "none (nothing kept)"))
    if not opts.get("dry-run"):
        print("receipt=%s" % os.path.join(store, RECEIPT_NAME))


def cmd_status(opts):
    store = _resolve_store(opts)
    config = _load_config(store)
    journal = _load_journal(store)
    n = int(opts.get("n") or 10)
    decisions = [r.get("decision") for r in journal]
    v = plateau_verdict(decisions, config.get("plateau_n", DEFAULT_PLATEAU_N))
    log("target=%s branch=%s repo=%s" % (config["target"], config["branch"], config["repo_root"]))
    log("guardrails: %s" % json.dumps(config["guardrails"]))
    log("baseline: %s" % json.dumps(config["baseline"]))
    log("iterations recorded: %d · plateau streak: %d/%d" % (
        len(journal), v["streak"], v["k"]))
    for r in journal[-n:]:
        log("  [%3s] %-8s gate=%-5s score=%-8s %s" % (
            r.get("iteration"), r.get("decision"), r.get("gate"), r.get("score"),
            r.get("note", "")))


def cmd_selftest(_opts):
    checks = []

    def chk(name, got, want):
        # No got=/want= echo (unlike most other workers' selftest): this worker's own data
        # legitimately contains the bare word "fail" (a gate value), which would read as a
        # real failure to claims_audit's `bad_output` scan of this command's stdout. Report
        # just the check name + verdict instead — same style as mirror_manifest.py's selftest.
        ok = got == want
        checks.append(ok)
        print("  [%s] %s" % ("ok" if ok else "XX", name))
        if not ok:
            print("        (see scripts/autoresearch.py cmd_selftest for the %s assertion)" % name)

    # slugify: deterministic, filesystem-safe
    chk("slug.basic", slugify("TOON Encoder.py"), "toon-encoder-py")
    chk("slug.empty", slugify(""), "target")
    chk("slug.stable", slugify("a  B_c") == slugify("A B C"), True)

    # decide(): correctness gate FIRST — a failing gate is ALWAYS revert, no matter the score
    chk("decide.gate_fail_wins", decide("fail", 999999, 1.0), "revert")
    chk("decide.first_pass_is_keep", decide("pass", 5.0, None), "keep")
    chk("decide.improve_max", decide("pass", 6.0, 5.0, margin=0.0, direction="max"), "keep")
    chk("decide.no_improve_max", decide("pass", 5.0, 5.0, margin=0.0, direction="max"), "revert")
    chk("decide.margin_blocks_tiny_gain", decide("pass", 5.05, 5.0, margin=0.1, direction="max"),
        "revert")
    chk("decide.improve_min", decide("pass", 4.0, 5.0, margin=0.0, direction="min"), "keep")
    chk("decide.no_improve_min", decide("pass", 6.0, 5.0, margin=0.0, direction="min"), "revert")
    chk("decide.none_score_reverts", decide("pass", None, 5.0), "revert")

    # plateau: k consecutive trailing reverts -> PLATEAU; a keep or plateau-break resets it
    chk("plateau.progress", plateau_verdict(["keep", "revert", "revert"], k=3)["verdict"],
        "PROGRESS")
    chk("plateau.hit", plateau_verdict(["keep", "revert", "revert", "revert"], k=3)["verdict"],
        "PLATEAU")
    chk("plateau.reset_by_break",
        plateau_verdict(["revert", "revert", "revert", "plateau-break", "revert"], k=3)["verdict"],
        "PROGRESS")
    chk("plateau.streak_count",
        plateau_verdict(["keep", "revert", "revert", "revert"], k=5)["streak"], 3)

    # health-check reminder fires every 10th iteration only
    chk("health.at_10", needs_health_check(10), True)
    chk("health.at_9", needs_health_check(9), False)
    chk("health.at_0", needs_health_check(0), False)
    chk("health.at_20", needs_health_check(20), True)

    # parse_eval_output: JSON object, embedded JSON, regex fallback, and unparseable -> fail
    chk("parse.json_whole", parse_eval_output('{"gate": "pass", "score": 12.5}'), ("pass", 12.5))
    chk("parse.json_embedded",
        parse_eval_output('running...\n{"gate": "fail", "score": 3}\ndone'), ("fail", 3.0))
    chk("parse.regex_fallback", parse_eval_output("gate: pass\nscore: 7"), ("pass", 7.0))
    chk("parse.bool_gate", parse_eval_output('{"gate": true, "score": 1}'), ("pass", 1.0))
    chk("parse.unparseable_is_fail", parse_eval_output("no idea what happened")[0], "fail")
    chk("parse.empty_is_fail", parse_eval_output(""), ("fail", None))

    # receipt shape: schema + source + gate-first fields present
    cfg = {"target": "t.py", "branch": "autoresearch/x", "store_rel": ".simplicio-loop/orchestrator/autoresearch/x",
          "tokenizer_id": "n/a", "metric_key": "score", "direction": "max",
          "baseline": {"gate": "pass", "score": 5.0}, "guardrails": {"max_iterations": 5}}
    journal = [{"decision": "keep", "gate": "pass", "score": 7.0},
              {"decision": "revert", "gate": "fail", "score": None}]
    receipt = build_receipt(cfg, journal, {"gate": "pass", "score": 7.0})
    chk("receipt.schema", receipt["schema"], SCHEMA)
    chk("receipt.source", receipt["source"], "autoresearch")
    chk("receipt.kept", receipt["kept"], 1)
    chk("receipt.reverted", receipt["reverted"], 1)
    chk("receipt.baseline_score", receipt["baseline"]["score"], 5.0)
    chk("receipt.actual_score", receipt["actual"]["score"], 7.0)

    ok = all(checks)
    print("selftest: %s (%d/%d)" % ("PASS" if ok else "FAIL", sum(checks), len(checks)))
    sys.exit(0 if ok else 1)


def _parse(args):
    """Parse --k v / --flag (bare flags become True)."""
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
    sub, opts = argv[0], _parse(argv[1:])
    {"init": cmd_init, "eval": cmd_eval, "record": cmd_record, "plateau": cmd_plateau,
     "finish": cmd_finish, "status": cmd_status, "selftest": cmd_selftest}.get(
        sub, lambda _o: (print("unknown command %r. choices: init eval record plateau finish "
                               "status selftest" % sub), sys.exit(2)))(opts)


if __name__ == "__main__":
    main()
