"""``simplicio-py doctor`` — local llama.cpp readiness + dependency freshness.

Extracted from `cli.py`'s `main()` body (issue #103); behavior unchanged.
The actual doctor implementation lives in `simplicio/doctor.py`.
"""

from __future__ import annotations

import argparse


def run(a: argparse.Namespace) -> int:
    from ..doctor import main as doctor_main

    doctor_argv = []
    if a.install:
        doctor_argv.append("--install")
    if a.json:
        doctor_argv.append("--json")
    if a.list_tiers:
        doctor_argv.append("--list-tiers")
    if a.no_check_updates:
        doctor_argv.append("--no-check-updates")
    if a.refresh:
        doctor_argv.append("--refresh")
    if a.upgrade:
        doctor_argv.append("--upgrade")
    return doctor_main(doctor_argv)
