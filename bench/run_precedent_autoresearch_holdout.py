#!/usr/bin/env python3
"""run_precedent_autoresearch_holdout.py — anti-overfit check for the #90 autoresearch run.

Run ONCE against the baseline (pre-run) `simplicio/precedent.py` and ONCE against the final
(post-run) version, over `HOLDOUT_CASES` — a fixed fixture set NEVER seen by the loop's
eval-cmd (`run_precedent_autoresearch_eval.py` only ever sees `SCORE_CASES`). If the final
version's holdout average tokens is not lower (or ties) vs baseline, AND the content markers
still hold, the win generalizes rather than being an artifact of the loop overfitting the
exact wording of the score cases.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bench.precedent_autoresearch_fixtures import HOLDOUT_CASES, render_case, required_markers
from simplicio.observability import ESTIMATOR_LABEL, estimate_tokens


def main():
    totals = []
    for case in HOLDOUT_CASES:
        block = render_case(case)
        for marker in required_markers(case):
            if marker not in block:
                print(
                    "content-preservation check FAILED for holdout case %r: missing %r"
                    % (case["id"], marker),
                    file=sys.stderr,
                )
                sys.exit(1)
        tokens = estimate_tokens(block)
        totals.append(tokens)
        print("holdout case=%-32s tokens=%d" % (case["id"], tokens))
    avg = sum(totals) / len(totals)
    print("estimator=%s cases=%d" % (ESTIMATOR_LABEL, len(totals)))
    print("%.4f" % avg)


if __name__ == "__main__":
    main()
