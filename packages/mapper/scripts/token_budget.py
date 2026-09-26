#!/usr/bin/env python3
"""simplicio-mapper — Token/Context Budget Guard (issue #174).

Ports the pattern from `simplicio-loop`'s `scripts/token_budget.py`: estimate
the token cost of the artifacts an LLM/loop loads before or while driving
this repo (the cross-agent contract docs, the largest mapper modules most
likely to be read whole, and the real `.simplicio-loop/*.json`-shaped artifacts a
fixture produces), report the delta against a committed baseline, and FAIL
when a tracked artifact regresses past its threshold — so a doc/module/
artifact that quietly balloons in size (burning context on every session
that reads it) gets caught the same way a broken test would.

Estimator: `tiktoken` (cl100k_base) is used when importable, but it is NOT a
dependency of this repo or package — the default, always-available path is a
stdlib-only heuristic (`heuristic:chars-div-4`, ~4 characters per token, a
standard rough approximation for English/markdown/code) so this guard never
needs a new heavy dependency. The estimator actually used is recorded in the
baseline/report so a swap is never silently mixed with old numbers.

Tracked artifacts:
  - The largest modules under `simplicio_mapper/` an agent is likely to read
    whole while working on the mapper/graph/CLI layers.
  - `.simplicio-loop/*.json`-shaped mapper artifacts: rather than inventing a new
    throwaway fixture, this tracks the REAL mapper output already committed
    at `contracts/mapper-artifacts/v1/fixtures/python-minimal/artifacts/*.json`
    (issue #157) and `.../mapper-index-result.json` — genuine output of
    `simplicio-mapper index`/`map` run against the tiny `python-minimal`
    fixture source already used by `tests/python/test_regen_contract_fixtures.py`,
    regenerated via `python3 scripts/regen_contract_fixtures.py update`.

Usage:
    python3 scripts/token_budget.py                    # report + gate against the baseline
    python3 scripts/token_budget.py --check             # same, but quiet unless it fails (CI-friendly)
    python3 scripts/token_budget.py --update-baseline   # regenerate token_budget_baseline.json
                                                          # after a deliberate, reviewed size change
    python3 scripts/token_budget.py --self-test         # negative test: proves the guard actually
                                                          # fails on a simulated size regression

Exit codes: 0 = within budget (or self-test passed), 1 = a tracked artifact
exceeded its threshold (or self-test failed to catch a simulated regression).
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BASELINE_PATH = os.path.join(HERE, "token_budget_baseline.json")

# (label, path relative to REPO). Growth headroom over the recorded baseline
# before the guard fails is applied uniformly (see THRESHOLD_GROWTH) — this
# keeps the guard self-maintaining instead of hand-picked magic numbers per
# file that drift out of date.
TRACKED_ARTIFACTS = [
    ("mapper/parse.py", "simplicio_mapper/mapper/parse.py"),
    ("mapper/graph.py", "simplicio_mapper/mapper/graph.py"),
    ("mapper/emit.py", "simplicio_mapper/mapper/emit.py"),
    ("cli/_flowchart.py", "simplicio_mapper/cli/_flowchart.py"),
    ("toon.py", "simplicio_mapper/toon.py"),
]

# `.simplicio-loop/*.json`-shaped mapper artifacts: real output committed under
# the mapper-artifacts contract fixture (issue #157), not a hand-written
# stand-in. Regenerate with `python3 scripts/regen_contract_fixtures.py update`.
FIXTURE_ARTIFACTS_DIR = os.path.join(
    "simplicio_mapper", "contracts", "mapper-artifacts", "v1", "fixtures", "python-minimal", "artifacts",
)
FIXTURE_INDEX_RESULT = os.path.join(
    "simplicio_mapper", "contracts", "mapper-artifacts", "v1", "fixtures", "python-minimal", "mapper-index-result.json",
)

# Allowed growth over the committed baseline before the guard fails. 25% is
# generous enough for routine edits but catches a genuine regression (e.g.
# accidentally pasting a large section into a tracked module).
THRESHOLD_GROWTH = 0.25


def _try_tiktoken_estimator():
    try:
        import tiktoken  # noqa: F401 — optional; not a dependency of this repo
    except Exception:  # noqa: BLE001 - optional dependency probe, any failure means "unavailable"
        return None
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda text: len(enc.encode(text))), "tiktoken:cl100k_base"
    except Exception:  # noqa: BLE001 - optional dependency probe, any failure means "unavailable"
        return None


def _heuristic_estimator(text):
    # stdlib-only fallback: ~4 chars/token, a standard rough estimate for
    # English/markdown/code. This is the DEFAULT so the guard never requires
    # installing a new heavy dependency.
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
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def discover_fixture_artifacts():
    """Real `.simplicio-loop/*.json`-shaped mapper artifacts committed under the
    mapper-artifacts contract fixture (issue #157) — genuine mapper output,
    not a synthetic stand-in."""
    out = []
    pattern = os.path.join(REPO, FIXTURE_ARTIFACTS_DIR, "*.json")
    for p in sorted(glob.glob(pattern)):
        rel = os.path.relpath(p, REPO)
        out.append((f"fixture artifact ({os.path.basename(p)})", rel))
    index_result_abs = os.path.join(REPO, FIXTURE_INDEX_RESULT)
    if os.path.isfile(index_result_abs):
        out.append(("fixture artifact (mapper-index-result.json)", FIXTURE_INDEX_RESULT))
    return out


def measure(estimate_fn, extra_artifacts=None):
    """Return {rel_path: {"label":..., "tokens": int, "words": int, "chars": int}}
    for artifacts that exist on disk. Missing artifacts are skipped, not
    treated as a failure — this guard adapts to whatever the repo actually
    ships at the time it runs."""
    out = {}
    artifacts = list(TRACKED_ARTIFACTS) + discover_fixture_artifacts()
    if extra_artifacts:
        artifacts = artifacts + list(extra_artifacts)
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
        with open(BASELINE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_baseline(measurements, estimator_id):
    payload = {
        "$schema_note": "simplicio-mapper token/context budget baseline (issue #174). Regenerate "
                        "with `python3 scripts/token_budget.py --update-baseline` after a "
                        "deliberate, reviewed size change to a tracked artifact -- never to "
                        "silence a regression you haven't looked at.",
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


def report(measurements, baseline, estimator_id, quiet=False, threshold_growth=None):
    """Print the report and return True if everything is within budget."""
    growth = THRESHOLD_GROWTH if threshold_growth is None else threshold_growth
    ok = True
    baseline_artifacts = (baseline or {}).get("artifacts", {})
    baseline_estimator = (baseline or {}).get("estimator")
    lines = []
    for rel, m in sorted(measurements.items()):
        base = baseline_artifacts.get(rel)
        tokens = m["tokens"]
        if base is None:
            lines.append(f"[NEW] {rel:<60s} {tokens:6d} tok  ({m['words']} words) -- no baseline yet")
            continue
        base_tokens = base["tokens"]
        threshold = int(base_tokens * (1 + growth)) if base_tokens else tokens
        delta = tokens - base_tokens
        pct = (delta / base_tokens * 100) if base_tokens else 0.0
        status = "ok"
        if tokens > threshold:
            status = "FAIL"
            ok = False
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"[{status}] {rel:<60s} {tokens:6d} tok  "
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


def self_test() -> int:
    """Negative test (issue #174 AC): prove the guard actually fails when a
    tracked artifact regresses past its threshold, instead of only ever
    exercising the green path. Uses synthetic in-memory measurements/baseline
    — no files are touched on disk."""
    estimator_id = "heuristic:chars-div-4"
    baseline = {
        "estimator": estimator_id,
        "artifacts": {
            "fake/regressed.md": {"label": "fake/regressed.md", "tokens": 1000, "words": 500},
            "fake/stable.md": {"label": "fake/stable.md", "tokens": 1000, "words": 500},
        },
    }

    # Case 1: a 50% size regression on one artifact (past the 25% threshold)
    # must be reported as FAIL, and the overall gate must return False.
    regressed = {
        "fake/regressed.md": {"label": "fake/regressed.md", "tokens": 1500, "words": 750, "chars": 6000},
        "fake/stable.md": {"label": "fake/stable.md", "tokens": 1010, "words": 505, "chars": 4040},
    }
    ok = report(regressed, baseline, estimator_id, quiet=True)
    if ok:
        print("self-test FAILED: guard did not flag a simulated 50% size regression", file=sys.stderr)
        return 1
    print("self-test: guard correctly FAILED a simulated 50% size regression on fake/regressed.md")

    # Case 2: growth within the allowed threshold must still PASS (proves the
    # guard is not simply always-failing).
    within_budget = {
        "fake/regressed.md": {"label": "fake/regressed.md", "tokens": 1100, "words": 550, "chars": 4400},
        "fake/stable.md": {"label": "fake/stable.md", "tokens": 1000, "words": 500, "chars": 4000},
    }
    ok = report(within_budget, baseline, estimator_id, quiet=True)
    if not ok:
        print("self-test FAILED: guard flagged a 10% growth that is within the 25% threshold", file=sys.stderr)
        return 1
    print("self-test: guard correctly PASSED a 10% growth within the 25% threshold")

    print("self-test: PASS (guard's fail path and pass path both verified)")
    return 0


def main():
    args = sys.argv[1:]
    update = "--update-baseline" in args
    quiet = "--check" in args
    run_self_test = "--self-test" in args

    if run_self_test:
        return self_test()

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
