#!/usr/bin/env python3
"""Verify and record the repository's remote default-branch migration (#98).

The command reads public GitHub metadata, verifies that the configured default
branch is ``main``, and emits a deterministic JSON receipt containing the
current tips of both ``main`` and the compatibility branch. It never reads or
prints credentials.

Exit codes: 0 = migration verified; 1 = metadata mismatch or request failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

API_ROOT = "https://api.github.com"
SCHEMA = "simplicio.default-branch-evidence/v1"


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "simplicio-default-branch-check"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"expected an object from {url}")
    return payload


def verify(
    repository: str,
    *,
    expected: str = "main",
    compatibility: str = "master",
    fetch_json: Callable[[str], dict[str, Any]] = _fetch_json,
) -> tuple[bool, dict[str, Any]]:
    """Return migration status and a machine-readable evidence receipt."""
    repo_url = f"{API_ROOT}/repos/{repository}"
    metadata = fetch_json(repo_url)
    observed = metadata.get("default_branch")
    tips: dict[str, str | None] = {}
    for branch in dict.fromkeys((expected, compatibility)):
        branch_data = fetch_json(f"{repo_url}/branches/{branch}")
        commit = branch_data.get("commit")
        tips[branch] = commit.get("sha") if isinstance(commit, dict) else None

    reasons: list[str] = []
    if observed != expected:
        reasons.append(f"default_branch is {observed!r}, expected {expected!r}")
    for branch, sha in tips.items():
        if not sha:
            reasons.append(f"branch {branch!r} has no observable commit SHA")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "repository": repository,
        "expected_default": expected,
        "observed_default": observed,
        "compatibility_branch": compatibility,
        "branch_tips": tips,
        "verified": not reasons,
        "reasons": reasons,
    }
    return not reasons, receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="wesleysimplicio/simplicio-dev-cli")
    parser.add_argument("--expected", default="main")
    parser.add_argument("--compatibility", default="master")
    args = parser.parse_args(argv)

    try:
        ok, receipt = verify(
            args.repository,
            expected=args.expected,
            compatibility=args.compatibility,
        )
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        receipt = {
            "schema": SCHEMA,
            "repository": args.repository,
            "expected_default": args.expected,
            "verified": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        ok = False

    output = sys.stdout if ok else sys.stderr
    print(json.dumps(receipt, indent=2, sort_keys=True), file=output)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
