"""``simplicio-py bench`` — compare with vs without (real numbers).

Extracted from `cli.py`'s `main()` body (issue #103); behavior unchanged.
"""

from __future__ import annotations

import argparse


def run(a: argparse.Namespace) -> int:
    from ..bench import run_bench

    run_bench(a.root, a.stack, a.cases)
    return 0
