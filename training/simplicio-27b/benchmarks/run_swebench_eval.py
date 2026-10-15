"""
SWE-bench style scaffold for Simplicio 27B.
Formats repository context into a 5-phase Simplicio-Loop prompt (<orient>, <plan>, <patch>, <validate>, <deliver>)
for three sample instances. It does NOT run a model, export all_preds.jsonl or publish a score.
"""

import os
import json
import argparse
from typing import Dict, List

SAMPLE_SWEBENCH_INSTANCES = [
    {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "base_commit": "4e76a084ebba",
        "problem_statement": "UsernameValidator allows trailing newline in ASCII/Unicode validators regex.",
        "hints_text": r"Need to add \A and \Z anchors or change $ to \Z in regex.",
        "test_patch": "tests/validators/tests.py"
    },
    {
        "instance_id": "sympy__sympy-13480",
        "repo": "sympy/sympy",
        "base_commit": "c479e0004",
        "problem_statement": "coth(log(tan(x))) produces NameError or infinite recursion.",
        "hints_text": "Check hyperbolic simplification in sympy/functions/elementary/hyperbolic.py",
        "test_patch": "sympy/functions/elementary/tests/test_hyperbolic.py"
    },
    {
        "instance_id": "pytest-dev__pytest-5221",
        "repo": "pytest-dev/pytest",
        "base_commit": "21d27976e",
        "problem_statement": "Display fixture scope in pytest --fixtures output.",
        "hints_text": "Inspect _pytest/fixtures.py showfixtures()",
        "test_patch": "testing/test_fixtures.py"
    }
]

def format_swebench_prompt(instance: Dict) -> str:
    """Formats instance prompt conforming to Simplicio-Loop Phase I (<orient>)."""
    return (
        f"<|im_start|>system\n"
        f"You are Simplicio 27B, specialized in autonomous repository bug resolution.\n"
        f"Strictly execute the 5 phases of Simplicio-Loop: <orient>, <plan>, <patch>, <validate>, and <deliver>.\n"
        f"<|im_end|>\n"
        f"<|im_start|>user\n"
        f"Repository: {instance['repo']}\n"
        f"Instance ID: {instance['instance_id']}\n"
        f"Base Commit: {instance['base_commit']}\n\n"
        f"Problem Description:\n{instance['problem_statement']}\n\n"
        f"Emit an atomic surgical diff patching the bug cleanly.\n"
        f"<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

def main():
    print("=" * 80)
    print("SWE-BENCH STYLE SCAFFOLD (SIMPLICIO 27B)")
    print("Formats sample repository issues into Simplicio-Loop prompts.")
    print("=" * 80)
    print(f"Loaded {len(SAMPLE_SWEBENCH_INSTANCES)} sample SWE-bench-style instances.")
    for inst in SAMPLE_SWEBENCH_INSTANCES:
        print(f"  - [{inst['instance_id']}] Repo: {inst['repo']}")
    print("\nScaffold only: no model inference or swebench.harness evaluation is wired in, so no result is produced.")


if __name__ == "__main__":
    main()
