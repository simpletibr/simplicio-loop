#!/usr/bin/env python3
"""Deterministic SkillOpt-style scorer for skill/law text (Harness-edit port).

Port of Asolaria's Harness-edit deterministic scorer.  Evaluates a piece of
skill/law text against a battery of scenarios, each of which declares
*must_include_any* groups (at least one phrase from each group must be present)
and *must_not_include* phrases (none may appear).  A scenario passes iff every
*must_include_any* group is satisfied AND no *must_not_include* phrase matches.

Exit codes: 0 = all scenarios pass, 1 = one or more failures, 2 = invalid input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def norm(text: str) -> str:
    """Lowercase, collapse whitespace to single spaces, strip edges."""
    return " ".join(text.lower().split())


def phrase_present(text: str, phrase: str) -> bool:
    """Return True if *phrase* (normalised) is a substring of *text*."""
    return norm(phrase) in text


def score(skill_text: str, scenarios: list[dict]) -> dict:
    """Deterministic scenario-based skill scoring.

    Parameters
    ----------
    skill_text:
        Raw (un-normalised) skill/law text to evaluate.
    scenarios:
        List of scenario dicts with optional keys:
            id                    – scenario identifier
            must_include_any      – list of lists; each inner list is an OR group
            must_not_include      – list of forbidden phrases
            failure               – human-readable failure label

    Returns
    -------
    dict with keys:
        ok        – True iff all scenarios passed
        passed    – count of passed scenarios
        total     – total scenarios
        score     – passed / total (0.0 if empty)
        results   – per-scenario detail
    """
    text = norm(skill_text)
    results: list[dict] = []
    passed = 0

    for scenario in scenarios:
        missing_groups: list[list[str]] = []
        for group in scenario.get("must_include_any", []):
            if not any(phrase_present(text, phrase) for phrase in group):
                missing_groups.append(group)

        forbidden_hits: list[str] = [
            p for p in scenario.get("must_not_include", [])
            if phrase_present(text, p)
        ]

        ok = not missing_groups and not forbidden_hits
        passed += 1 if ok else 0

        results.append({
            "id": scenario.get("id"),
            "ok": ok,
            "failure": scenario.get("failure", ""),
            "missing_groups": missing_groups,
            "forbidden_hits": forbidden_hits,
        })

    total = len(scenarios)
    return {
        "ok": passed == total,
        "passed": passed,
        "total": total,
        "score": passed / total if total else 0.0,
        "results": results,
    }


def _load_text(source: str) -> str:
    """Read text from a file path or ``-`` for stdin."""
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def _resolve_scenarios(
    scenario_sources: list[str],
    extra_scenarios: list[str],
    builtin_dir: Path,
) -> list[dict]:
    """Load and merge scenario definitions.

    *scenario_sources*  – paths (or ``-``) to JSON scenario files.
    *extra_scenarios*   – inline JSON strings.
    *builtin_dir*       – ``commands/scenarios/`` directory with builtin *.json
                          files (loaded when no explicit sources are given).

    Returns a flat list of scenario dicts.
    """
    all_scenarios: list[dict] = []

    if scenario_sources:
        for src in scenario_sources:
            raw = _load_text(src)
            data = json.loads(raw)
            if isinstance(data, list):
                all_scenarios.extend(data)
            elif isinstance(data, dict):
                all_scenarios.append(data)
            else:
                raise ValueError(f"unexpected JSON structure in {src!r}")
    else:
        # Fall back to builtin scenarios
        builtin_files = sorted(builtin_dir.glob("*.json")) if builtin_dir.is_dir() else []
        for bf in builtin_files:
            data = json.loads(bf.read_text(encoding="utf-8"))
            if isinstance(data, list):
                all_scenarios.extend(data)
            elif isinstance(data, dict):
                all_scenarios.append(data)

    for raw in extra_scenarios:
        data = json.loads(raw)
        if isinstance(data, list):
            all_scenarios.extend(data)
        elif isinstance(data, dict):
            all_scenarios.append(data)

    return all_scenarios


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="simplicio score-skill",
        description="Deterministic SkillOpt-style scorer for skill/law text.",
        epilog=(
            "Exit codes: 0 = all scenarios pass, "
            "1 = one or more failures, 2 = invalid input."
        ),
    )
    ap.add_argument(
        "skill",
        nargs="?",
        default="-",
        help="path to skill/law text file, or - for stdin (default: -)",
    )
    ap.add_argument(
        "--scenario",
        "-s",
        dest="scenario_sources",
        action="append",
        default=[],
        help="path to a JSON scenario file (repeatable); when absent, builtin "
        "scenarios from commands/scenarios/*.json are used",
    )
    ap.add_argument(
        "--extra-scenario",
        action="append",
        default=[],
        help="inline JSON scenario string (repeatable, appended after --scenario files)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON result",
    )
    ap.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="print per-scenario detail even on success",
    )

    args = ap.parse_args(argv)

    # Locate builtin scenarios directory relative to this file
    builtin_dir = Path(__file__).resolve().parent / "scenarios"

    try:
        skill_text = _load_text(args.skill)
        scenarios = _resolve_scenarios(
            args.scenario_sources,
            args.extra_scenario,
            builtin_dir,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"simplicio score-skill: {exc}", file=sys.stderr)
        return 2

    if not scenarios:
        print(
            "simplicio score-skill: no scenarios found "
            "(pass --scenario or ensure builtin scenarios exist)",
            file=sys.stderr,
        )
        return 2

    result = score(skill_text, scenarios)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Score: {result['score']:.0%} ({result['passed']}/{result['total']})")
        print(f"All ok: {result['ok']}")
        if result["results"] and (not result["ok"] or args.verbose):
            print()
            for r in result["results"]:
                status = "\u2705" if r["ok"] else "\u274c"
                print(f"  {status} {r.get('id', '(unnamed)')}")
                if not r["ok"]:
                    if r["missing_groups"]:
                        for grp in r["missing_groups"]:
                            print(f"       missing any of: {grp}")
                    if r["forbidden_hits"]:
                        for hit in r["forbidden_hits"]:
                            print(f"       forbidden hit: {hit!r}")
                    if r.get("failure"):
                        print(f"       failure: {r['failure']}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
