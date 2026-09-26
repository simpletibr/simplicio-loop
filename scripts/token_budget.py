#!/usr/bin/env python3
"""simplicio-loop — Token/Context Budget Guard (#121).

Estimates the token cost of the critical context artifacts an LLM/runtime loads before it can
drive `/simplicio-loop` (the skill file, the cross-agent contract docs, and the handful of large
scripts most likely to be read whole), reports the delta against a committed baseline, and FAILS
when a tracked artifact regresses past its threshold — so a doc/script that quietly balloons in
size (burning context on every fresh session) gets caught the same way a broken test would.

Estimator: `tiktoken` (o200k_base) is the packaged default. A stdlib-only heuristic
(`heuristic:chars-div-4`) remains a fail-open fallback for constrained/broken installs, so the
budget guard never prevents a loop from reporting its state.
The estimator actually used is recorded in the baseline/report so a swap is never silently mixed
with old numbers.

Tracked artifacts (adjusted to what this repo actually ships — no `mapper.py`/`.simplicio-loop/*.json`
survey artifacts exist here since this repo IS the orchestrator skill, not a project that has been
mapped; the check includes any `.simplicio-loop/*.json` it finds anyway, for parity with repos that do
have them):
  - `.claude/skills/simplicio-loop/SKILL.md` — the skill a fresh runtime loads every session
  - `AGENTS.md` — the single cross-agent contract doc
  - `.simplicio-loop/*.json` — mapper survey artifacts, if this repo has been mapped locally
  - the largest scripts a task is likely to read whole: `simplicio_loop/cli.py`,
    `scripts/loop_journal.py`, `scripts/task_anchor.py`, `scripts/claims_audit.py`,
    `scripts/video_evidence.py`, `scripts/check.py`

Usage:
    python3 scripts/token_budget.py                    # report + gate against the baseline
    python3 scripts/token_budget.py --check             # same, but quiet unless it fails (CI-friendly)
    python3 scripts/token_budget.py --update-baseline    # regenerate token_budget_baseline.json
                                                          # after a deliberate, reviewed size change

Exit codes: 0 = within budget, 1 = a tracked artifact exceeded its threshold.
"""
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BASELINE_PATH = os.path.join(HERE, "token_budget_baseline.json")

# (label, path relative to REPO). Growth headroom over the recorded baseline before the guard
# fails is applied uniformly (see THRESHOLD_GROWTH) — this keeps the guard self-maintaining
# instead of hand-picked magic numbers per file that drift out of date.
TRACKED_ARTIFACTS = [
    ("SKILL.md (simplicio-loop)", ".claude/skills/simplicio-loop/SKILL.md"),
    ("AGENTS.md", "AGENTS.md"),
    ("cli.py", "simplicio_loop/cli.py"),
    ("loop_journal.py", "scripts/loop_journal.py"),
    ("task_anchor.py", "scripts/task_anchor.py"),
    ("claims_audit.py", "scripts/claims_audit.py"),
    ("video_evidence.py", "scripts/video_evidence.py"),
    ("check.py", "scripts/check.py"),
]

# Allowed growth over the committed baseline before the guard fails. 25% is generous enough for
# routine edits but catches a genuine regression (e.g. accidentally pasting 2000 extra words into
# SKILL.md, per the #121 acceptance test).
THRESHOLD_GROWTH = 0.25


def _try_tiktoken_estimator():
    try:
        import tiktoken  # noqa: F401 — optional; not a dependency of this repo
    except Exception:
        return None
    try:
        enc = tiktoken.get_encoding("o200k_base")
        return (lambda text: len(enc.encode(text))), "tiktoken:o200k_base"
    except Exception:
        return None


def _heuristic_estimator(text):
    # stdlib-only fallback: ~4 chars/token, a standard rough estimate for English/markdown/code.
    # This is the DEFAULT so the guard never requires installing a new heavy dependency.
    if not text:
        return 0
    return max(1, len(text) // 4)


def get_estimator():
    tk = _try_tiktoken_estimator()
    if tk is not None:
        return tk
    return _heuristic_estimator, "heuristic:chars-div-4"


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def discover_mapper_artifacts():
    """`.simplicio-loop/*.json` — only present if this repo has been mapped locally; not committed."""
    pattern = os.path.join(REPO, ".simplicio-loop", "*.json")
    out = []
    for p in sorted(glob.glob(pattern)):
        rel = os.path.relpath(p, REPO)
        out.append(("mapper artifact (%s)" % os.path.basename(p), rel))
    return out


def measure(estimate_fn):
    """Return {rel_path: {"label":..., "tokens": int, "words": int, "chars": int}} for artifacts
    that exist on disk. Missing artifacts (e.g. an artifact list entry not present in some repos) are skipped, not
    treated as a failure — this guard adapts to whatever the repo actually ships."""
    out = {}
    artifacts = list(TRACKED_ARTIFACTS) + discover_mapper_artifacts()
    for label, rel in artifacts:
        abspath = os.path.join(REPO, rel)
        text = _read_text(abspath)
        if text is None:
            continue
        out[rel] = {
            "label": label,
            "tokens": estimate_fn(text),
            "words": len(text.split()),
            "chars": len(text),
        }
    return out


def load_baseline():
    if not os.path.exists(BASELINE_PATH):
        return None
    try:
        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_baseline(measurements, estimator_id):
    payload = {
        "$schema_note": "simplicio-loop token/context budget baseline (#121). Regenerate with "
                        "`python3 scripts/token_budget.py --update-baseline` after a deliberate, "
                        "reviewed size change to a tracked artifact -- never to silence a "
                        "regression you haven't looked at.",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "estimator": estimator_id,
        "threshold_growth": THRESHOLD_GROWTH,
        "artifacts": {
            rel: {"label": m["label"], "tokens": m["tokens"], "words": m["words"]}
            for rel, m in sorted(measurements.items())
        },
    }
    with open(BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    return payload


def report(measurements, baseline, estimator_id, quiet=False):
    """Print the report and return True if everything is within budget."""
    ok = True
    baseline_artifacts = (baseline or {}).get("artifacts", {})
    baseline_estimator = (baseline or {}).get("estimator")
    lines = []
    for rel, m in sorted(measurements.items()):
        base = baseline_artifacts.get(rel)
        tokens = m["tokens"]
        if base is None:
            lines.append("[NEW] %-45s %6d tok  (%d words) -- no baseline yet" % (
                rel, tokens, m["words"]))
            continue
        base_tokens = base["tokens"]
        threshold = int(base_tokens * (1 + THRESHOLD_GROWTH)) if base_tokens else tokens
        delta = tokens - base_tokens
        pct = (delta / base_tokens * 100) if base_tokens else 0.0
        status = "ok"
        if tokens > threshold:
            status = "FAIL"
            ok = False
        sign = "+" if delta >= 0 else ""
        lines.append("[%s] %-45s %6d tok  (baseline %d, %s%d, %+.1f%%, threshold %d)" % (
            status, rel, tokens, base_tokens, sign, delta, pct, threshold))
    if not quiet or not ok:
        print("=== token/context budget (%s) ===" % estimator_id)
        for line in lines:
            print(line)
        if baseline_estimator and baseline_estimator != estimator_id:
            print("NOTE: baseline was recorded with estimator %r, this run used %r -- "
                  "numbers are not directly comparable; consider --update-baseline."
                  % (baseline_estimator, estimator_id))
        print("token-budget: %s" % ("PASS" if ok else "FAIL"))
    return ok


def main():
    args = sys.argv[1:]
    update = "--update-baseline" in args
    quiet = "--check" in args

    estimate_fn, estimator_id = get_estimator()
    measurements = measure(estimate_fn)

    if update:
        payload = write_baseline(measurements, estimator_id)
        print("wrote %s (%d artifacts, estimator=%s)" % (
            BASELINE_PATH, len(payload["artifacts"]), estimator_id))
        return 0

    baseline = load_baseline()
    if baseline is None:
        print("no baseline at %s -- run --update-baseline first" % BASELINE_PATH)
        # First run ever: still report sizes, but don't fail the gate on a missing baseline.
        report(measurements, None, estimator_id, quiet=False)
        return 0

    ok = report(measurements, baseline, estimator_id, quiet=quiet)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
