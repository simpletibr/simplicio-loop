"""``simplicio-py init`` — install skill + UserPromptSubmit hook into ~/.claude/.

Extracted from `cli.py`'s `main()` body (issue #103); behavior unchanged.
The actual install logic lives in `simplicio/init.py` (`install()`).
"""

from __future__ import annotations

import argparse


def run(a: argparse.Namespace) -> int:
    from ..init import main as init_main

    init_argv = []
    if a.claude_home:
        init_argv += ["--claude-home", a.claude_home]
    if a.dry_run:
        init_argv += ["--dry-run"]
    return init_main(init_argv)
