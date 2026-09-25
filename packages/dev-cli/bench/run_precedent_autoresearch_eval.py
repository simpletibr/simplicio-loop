#!/usr/bin/env python3
"""run_precedent_autoresearch_eval.py — eval-cmd for the #90 autoresearch run.

Score = average token count (canonical estimator, `simplicio.observability.estimate_tokens`,
the single estimator #88 unified — words*4/3, labeled) of `build_precedent_block()`'s output
across the FIXED `SCORE_CASES` set. Lower is better (`--minimize` in the autoresearch worker).

Also re-checks the content-preservation markers (anti-Goodhart: a mutation that shrinks tokens
by deleting the actual precedent path/line/marker instead of trimming prose must fail here, on
top of whatever the pytest gate already checks). Prints per-case tokens for visibility, then the
single float score on the LAST stdout line, per the autoresearch worker's eval-cmd contract.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bench.precedent_autoresearch_fixtures import SCORE_CASES, render_case, required_markers
from simplicio.observability import ESTIMATOR_LABEL, estimate_tokens


def main():
    totals = []
    for case in SCORE_CASES:
        block = render_case(case)
        for marker in required_markers(case):
            if marker not in block:
                print(
                    "content-preservation check FAILED for case %r: missing %r"
                    % (case["id"], marker),
                    file=sys.stderr,
                )
                sys.exit(1)
        tokens = estimate_tokens(block)
        totals.append(tokens)
        print("case=%-32s tokens=%d" % (case["id"], tokens))
    avg = sum(totals) / len(totals)
    print("estimator=%s cases=%d" % (ESTIMATOR_LABEL, len(totals)))
    print("%.4f" % avg)


if __name__ == "__main__":
    main()
