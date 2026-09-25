"""``simplicio-py detect`` — heuristic: is a prompt a code-edit task.

Extracted from `cli.py`'s `main()` body (issue #103); behavior unchanged.
The actual detection heuristic lives in `simplicio/detect.py`.
"""

from __future__ import annotations

import argparse


def run(a: argparse.Namespace) -> int:
    from ..detect import main as detect_main

    detect_argv = []
    prompt = a.prompt
    if prompt is None and a.prompt_words:
        prompt = " ".join(a.prompt_words)
    if prompt is not None:
        detect_argv += ["--prompt", prompt]
    if a.quiet:
        detect_argv += ["--quiet"]
    if a.json:
        detect_argv += ["--json"]
    return detect_main(detect_argv)
