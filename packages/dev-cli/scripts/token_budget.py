#!/usr/bin/env python3
"""simplicio-dev-cli -- Token/Context Budget Guard (issue #111).

Ported from simplicio-loop's `scripts/token_budget.py` (#121): estimates the
token cost of the critical context artifacts an LLM/agent loads before it can
work in this repo (the cross-agent contract docs, plus the largest modules
under `simplicio/`), reports the delta against a committed baseline, and
FAILS when a tracked artifact regresses past its threshold -- so a doc/module
that quietly balloons in size (burning context on every fresh session) gets
caught the same way a broken test would.

Estimator: a single, fixed stdlib-only heuristic (`heuristic:chars-div-4`,
~4 characters per token, a standard rough approximation for
English/markdown/code) -- deliberately the ONLY estimator, not "the default
when an optional tokenizer is missing". `scripts/check.py --package dev-cli`
runs this guard inside a hermetic, network-stripped gate subprocess
(`simplicio_loop/quality_process.py`'s `_repo_env`); an optional
network-fetched tokenizer (e.g. `tiktoken`, which downloads its BPE file on
first use) would measure differently there than under plain `pytest`
(which still has network), making the guard's pass/fail depend on which
harness ran it. `python3 scripts/token_budget.py` never needs a new
dependency. The estimator actually used is recorded in the baseline/report
so a deliberate future estimator swap is never silently mixed with old
numbers.

Tracked artifacts:
  - `AGENTS.md`, `CLAUDE.md` -- the cross-agent / Claude-specific contract
    docs every session reads first.
  - `.simplicio-loop/*.json` -- mapper survey artifacts, if this repo has been
    mapped locally (not committed; skipped when absent).
  - the largest modules under `simplicio/` an agent is likely to read
    whole while working a task: `providers.py`, `commands/claims.py`,
    `mechanical_edit.py`, `mapper.py`, `pipeline.py`, `cli.py`, `intent.py`,
    `observability.py`.

Usage:
    python3 scripts/token_budget.py                    # report + gate against the baseline
    python3 scripts/token_budget.py --check             # same, but quiet unless it fails (CI-friendly)
    python3 scripts/token_budget.py --update-baseline    # regenerate token_budget_baseline.json
                                                          # after a deliberate, reviewed size change
    python3 scripts/token_budget.py --self-test          # prove the guard actually catches a
                                                          # real regression (negative test, no pytest needed)

Exit codes: 0 = within budget (or self-test passed), 1 = a tracked artifact
exceeded its threshold (or self-test failed to catch a synthetic regression).
"""

from __future__ import annotations

import glob
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BASELINE_PATH = os.path.join(HERE, "token_budget_baseline.json")

# (label, path relative to REPO). Growth headroom over the recorded baseline
# before the guard fails is applied uniformly (see THRESHOLD_GROWTH) -- this
# keeps the guard self-maintaining instead of hand-picked magic numbers per
# file that drift out of date.
TRACKED_ARTIFACTS = [
    ("AGENTS.md", "AGENTS.md"),
    ("CLAUDE.md", "CLAUDE.md"),
    ("providers.py", "simplicio/providers.py"),
    ("commands/claims.py", "simplicio/commands/claims.py"),
    ("mechanical_edit.py", "simplicio/mechanical_edit.py"),
    ("mapper.py", "simplicio/mapper.py"),
    ("pipeline.py", "simplicio/pipeline.py"),
    ("pipeline_stages.py", "simplicio/pipeline_stages.py"),
    ("cli.py", "simplicio/cli.py"),
    ("intent.py", "simplicio/intent.py"),
    ("observability.py", "simplicio/observability.py"),
]

# Allowed growth over the committed baseline before the guard fails. 25% is
# generous enough for routine edits but catches a genuine regression (e.g.
# accidentally pasting a large block into AGENTS.md).
THRESHOLD_GROWTH = 0.25


def _heuristic_estimator(text):
    # stdlib-only estimator: ~4 chars/token, a standard rough estimate for
    # English/markdown/code. This is the ONLY estimator the guard uses --
    # deliberately, not just "the default when tiktoken is unavailable".
    # `scripts/check.py --package dev-cli` runs this gate inside a hermetic
    # subprocess (simplicio_loop/quality_process.py's `_repo_env`) that
    # strips proxy/network env vars on purpose; an optional tiktoken path
    # would silently fall back to this same heuristic there while using
    # tiktoken's real BPE count under plain `pytest` (which still has
    # network), making the guard's pass/fail depend on which harness ran it.
    # Recorded `estimator` in the baseline is checked below so a future
    # deliberate estimator swap can't silently mix with old numbers.
    if not text:
        return 0
    return max(1, len(text) // 4)


def get_estimator():
    return _heuristic_estimator, "heuristic:chars-div-4"


def _read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _normalize_rel(path: str) -> str:
    return path.replace("\\", "/")


def discover_mapper_artifacts(repo=REPO):
    """`.simplicio-loop/*.json` -- only present if this repo has been mapped
    locally; not committed."""
    pattern = os.path.join(repo, ".simplicio-loop", "*.json")
    out = []
    for p in sorted(glob.glob(pattern)):
        rel = _normalize_rel(os.path.relpath(p, repo))
        out.append((f"mapper artifact ({os.path.basename(p)})", rel))
    return out


def measure(estimate_fn, repo=REPO, artifacts=None):
    """Return {rel_path: {"label":..., "tokens": int, "words": int, "chars": int}}
    for artifacts that exist on disk. Missing artifacts are skipped, not
    treated as a failure -- this guard adapts to whatever the repo actually
    ships."""
    out = {}
    all_artifacts = list(artifacts if artifacts is not None else TRACKED_ARTIFACTS)
    if artifacts is None:
        all_artifacts += discover_mapper_artifacts(repo)
    for label, rel in all_artifacts:
        rel = _normalize_rel(rel)
        abspath = os.path.join(repo, rel)
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


def load_baseline(path=BASELINE_PATH):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_baseline(measurements, estimator_id, path=BASELINE_PATH):
    payload = {
        "$schema_note": (
            "simplicio-dev-cli token/context budget baseline (issue #111). Regenerate with "
            "`python3 scripts/token_budget.py --update-baseline` after a deliberate, reviewed "
            "size change to a tracked artifact -- never to silence a regression you haven't "
            "looked at."
        ),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "estimator": estimator_id,
        "threshold_growth": THRESHOLD_GROWTH,
        "artifacts": {
            rel: {"label": m["label"], "tokens": m["tokens"], "words": m["words"]}
            for rel, m in sorted(measurements.items())
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    return payload


def report(measurements, baseline, estimator_id, quiet=False):
    """Print the report and return True if everything is within budget."""
    ok = True
    baseline_artifacts = (baseline or {}).get("artifacts", {})
    baseline_estimator = (baseline or {}).get("estimator")
    threshold_growth = (baseline or {}).get("threshold_growth", THRESHOLD_GROWTH)
    lines = []
    for rel, m in sorted(measurements.items()):
        base = baseline_artifacts.get(rel)
        tokens = m["tokens"]
        if base is None:
            lines.append(f"[NEW] {rel:<45s} {tokens:6d} tok  ({m['words']} words) -- no baseline yet")
            continue
        base_tokens = base["tokens"]
        threshold = int(base_tokens * (1 + threshold_growth)) if base_tokens else tokens
        delta = tokens - base_tokens
        pct = (delta / base_tokens * 100) if base_tokens else 0.0
        status = "ok"
        if tokens > threshold:
            status = "FAIL"
            ok = False
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"[{status}] {rel:<45s} {tokens:6d} tok  "
            f"(baseline {base_tokens}, {sign}{delta}, {pct:+.1f}%, threshold {threshold})"
        )
    if not quiet or not ok:
        print(f"=== token/context budget ({estimator_id}) ===")
        for line in lines:
            print(line)
        if baseline_estimator and baseline_estimator != estimator_id:
            print(
                f"NOTE: baseline was recorded with estimator {baseline_estimator!r}, this run used "
                f"{estimator_id!r} -- numbers are not directly comparable; consider --update-baseline."
            )
        print(f"token-budget: {'PASS' if ok else 'FAIL'}")
    return ok


def self_test() -> bool:
    """Prove the guard actually fails on a real size regression (issue #111
    AC: negative test, no pytest fixture required). Builds an isolated
    baseline + a grown artifact in a tmp dir, asserts `report()` catches it,
    and also asserts an unchanged artifact does NOT false-positive."""
    estimate_fn, estimator_id = get_estimator()
    small_text = "hello simplicio world " * 20
    grown_text = small_text * 5  # well past the 25% growth threshold

    with tempfile.TemporaryDirectory() as td:
        small_path = os.path.join(td, "fake.txt")
        with open(small_path, "w", encoding="utf-8") as f:
            f.write(small_text)
        baseline_measurements = measure(estimate_fn, repo=td, artifacts=[("fake.txt", "fake.txt")])
        baseline = write_baseline(baseline_measurements, estimator_id, path=os.path.join(td, "baseline.json"))

        # Regression case: same path, content grown past the threshold.
        with open(small_path, "w", encoding="utf-8") as f:
            f.write(grown_text)
        grown_measurements = measure(estimate_fn, repo=td, artifacts=[("fake.txt", "fake.txt")])
        regression_caught = not report(grown_measurements, baseline, estimator_id, quiet=True)

        # Control case: no change -> must NOT be flagged (no false positive).
        no_regression_ok = report(baseline_measurements, baseline, estimator_id, quiet=True)

    print(
        f"self-test: regression correctly detected={regression_caught}  "
        f"no-false-positive-on-unchanged-artifact={no_regression_ok}"
    )
    passed = regression_caught and no_regression_ok
    print(f"token-budget self-test: {'PASS' if passed else 'FAIL'}")
    return passed


def main():
    args = sys.argv[1:]
    update = "--update-baseline" in args
    quiet = "--check" in args
    self_test_mode = "--self-test" in args

    if self_test_mode:
        return 0 if self_test() else 1

    estimate_fn, estimator_id = get_estimator()
    measurements = measure(estimate_fn)

    if update:
        payload = write_baseline(measurements, estimator_id)
        print(f"wrote {BASELINE_PATH} ({len(payload['artifacts'])} artifacts, estimator={estimator_id})")
        return 0

    baseline = load_baseline()
    if baseline is None:
        print(f"no baseline at {BASELINE_PATH} -- run --update-baseline first")
        # First run ever: still report sizes, but don't fail the gate on a
        # missing baseline.
        report(measurements, None, estimator_id, quiet=False)
        return 0

    ok = report(measurements, baseline, estimator_id, quiet=quiet)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
