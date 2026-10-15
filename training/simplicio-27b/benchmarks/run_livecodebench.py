"""
LiveCodeBench-style scaffold for Simplicio 27B.
Lists two sample problems. It does NOT run a model, execute test cases or publish a score.
"""

import sys
import json
from typing import Dict, List

SAMPLE_LCB_PROBLEMS = [
    {
        "question_id": "LCB_2026_01",
        "title": "Minimum Operations to Make Array Continuous",
        "difficulty": "Medium",
        "prompt": "Given an integer array nums, return the minimum number of operations to make nums continuous.\nIn one operation, you can replace any element with any integer.",
        "test_cases": [
            {"input": "[4, 2, 5, 3]", "expected": "0"},
            {"input": "[1, 2, 3, 5, 6]", "expected": "1"},
            {"input": "[1, 10, 100, 1000]", "expected": "3"}
        ]
    },
    {
        "question_id": "LCB_2026_02",
        "title": "Find the Longest Valid Obstacle Course",
        "difficulty": "Hard",
        "prompt": "You want to build some obstacle courses. You are given a 0-indexed integer array obstacles of length n. Return an array ans of length n, where ans[i] is the length of the longest obstacle course ending at index i.",
        "test_cases": [
            {"input": "[1, 2, 3, 2]", "expected": "[1, 2, 3, 3]"},
            {"input": "[2, 2, 1]", "expected": "[1, 2, 1]"},
            {"input": "[3, 1, 5, 6, 4, 2]", "expected": "[1, 1, 2, 3, 2, 2]"}
        ]
    }
]

def main():
    print("=" * 80)
    print("LIVECODEBENCH-STYLE SCAFFOLD (SIMPLICIO 27B)")
    print("Sample competitive-coding problems with their test cases.")
    print("=" * 80)
    print(f"Loaded {len(SAMPLE_LCB_PROBLEMS)} sample LiveCodeBench-style problems.")
    for p in SAMPLE_LCB_PROBLEMS:
        print(f"  - [{p['question_id']}] {p['title']} ({p['difficulty']})")
    print("\nScaffold only: no model inference or test execution is wired in, so no result is produced.")


if __name__ == "__main__":
    main()
