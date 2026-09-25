"""``simplicio-py index`` — index/cache the repo (once, or after changes).

Extracted from `cli.py`'s `main()` body (issue #103); behavior unchanged.
"""

from __future__ import annotations

import argparse


def run(a: argparse.Namespace) -> int:
    from ..precedent import index_repo

    index_repo(a.root_arg or a.root, a.stack)
    return 0
