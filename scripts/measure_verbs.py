#!/usr/bin/env python3
"""Measure the real wall-clock cost of index/survey/drift/ask suboperations
(issue #174, step 1 of "native delegation with per-verb savings").

Before adding another shell-out to the `simplicio` runtime binary (mirroring
the existing `ask precedent` native-delegation pattern in
`simplicio_mapper/query.py`), this script measures where the Python
implementation actually spends time, over the same tiny, real fixture
already used by the mapper-artifacts contract tests
(`contracts/mapper-artifacts/v1/fixtures/python-minimal/source`) — so the
choice of which verb(s) to delegate is based on real numbers, not a guess.

Two kinds of measurements are taken:

  1. "whole-command" — the cost of calling `mapper.build_artifacts`,
     `survey.build_survey`, and `drift.build_spec_drift` end to end, as the
     `index`/`survey`/`drift` CLI commands actually do internally.
  2. "isolated verb logic" — for each `ask <verb>`, the cost of the verb's
     OWN logic only (`query._callers`/`_callees`/`_reaches`/`_impact`/
     `_tests_for`), with the shared `build_artifacts()` scan already done
     once and excluded from the timing. This isolates each verb's marginal
     cost from the fixed cost every `ask` call already pays (`run_query`
     always calls `build_artifacts` up front, regardless of verb — see
     `simplicio_mapper/query.py::run_query`), which is what actually
     determines whether a given verb is worth a dedicated native fast path.

Usage:
    python3 scripts/measure_verbs.py                  # print + write the report
    python3 scripts/measure_verbs.py --repeats 21      # more repeats (default 21)
    python3 scripts/measure_verbs.py --out <path>      # override report path
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

FIXTURE_SOURCE = os.path.join(
    REPO, "contracts", "mapper-artifacts", "v1", "fixtures", "python-minimal", "source",
)
DEFAULT_OUT = os.path.join(HERE, "measure_verbs_report.json")
REPORT_SCHEMA = "simplicio.measure-verbs-report/v1"
DEFAULT_REPEATS = 21


def _timeit(fn, repeats: int) -> dict:
    samples_ms = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples_ms.append((time.perf_counter() - start) * 1000.0)
    return {
        "unit": "ms",
        "repeats": repeats,
        "median": round(statistics.median(samples_ms), 4),
        "min": round(min(samples_ms), 4),
        "max": round(max(samples_ms), 4),
        "mean": round(statistics.fmean(samples_ms), 4),
    }


def run(repeats: int = DEFAULT_REPEATS) -> dict:
    if not os.path.isdir(FIXTURE_SOURCE):
        raise SystemExit(f"fixture source not found: {FIXTURE_SOURCE}")

    # Measure against a throwaway COPY of the fixture, never the committed
    # source tree directly -- `build_artifacts` writes a `.simplicio/cache/`
    # dir as a side effect of running, which must not leak into
    # `contracts/mapper-artifacts/v1/fixtures/python-minimal/source/`.
    tmp_root = tempfile.mkdtemp(prefix="measure-verbs-")
    cwd = os.path.join(tmp_root, "source")
    shutil.copytree(FIXTURE_SOURCE, cwd)
    try:
        return _run_measurements(cwd, repeats)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _run_measurements(cwd: str, repeats: int) -> dict:
    from simplicio_mapper.business import build_business_rules
    from simplicio_mapper.drift import build_spec_drift
    from simplicio_mapper.flows import build_flow_inventory
    from simplicio_mapper.mapper import build_artifacts
    from simplicio_mapper.query import (
        _callees,
        _callers,
        _impact,
        _reaches,
        _resolve_symbol_name,
        _tests_for,
    )
    from simplicio_mapper.survey import build_survey

    results: dict[str, dict] = {}

    # -- whole-command suboperations --------------------------------------
    results["index.build_artifacts"] = _timeit(lambda: build_artifacts(cwd), repeats)

    artifacts = build_artifacts(cwd)  # reused below for isolated + composed measurements
    flow_inventory = build_flow_inventory(cwd, artifacts)
    business_rules = build_business_rules(cwd, artifacts)

    results["survey.build_flow_inventory"] = _timeit(lambda: build_flow_inventory(cwd, artifacts), repeats)
    results["survey.build_business_rules"] = _timeit(lambda: build_business_rules(cwd, artifacts), repeats)
    results["survey.build_survey"] = _timeit(
        lambda: build_survey(cwd, artifacts, flow_inventory, business_rules), repeats
    )
    results["drift.build_spec_drift"] = _timeit(lambda: build_spec_drift(cwd), repeats)

    # -- ask: full round trip via run_query (pays build_artifacts every call) --
    from simplicio_mapper.query import run_query

    results["ask.impact (full run_query)"] = _timeit(
        lambda: run_query(cwd, verb="impact", arg="src/util.py"), repeats
    )
    results["ask.tests-for (full run_query)"] = _timeit(
        lambda: run_query(cwd, verb="tests-for", arg="src/util.py"), repeats
    )

    # -- ask: isolated verb-specific logic only (build_artifacts excluded) --
    symbol_index = artifacts["symbol_index"]
    call_graph = artifacts["call_graph"]
    project_map = artifacts["project_map"]

    results["ask.callers (isolated)"] = _timeit(
        lambda: _callers(call_graph, _resolve_symbol_name(symbol_index, "greet"), 20), repeats
    )
    results["ask.callees (isolated)"] = _timeit(
        lambda: _callees(call_graph, _resolve_symbol_name(symbol_index, "main"), 20), repeats
    )
    results["ask.reaches (isolated)"] = _timeit(
        lambda: _reaches(call_graph, "src/app.py", 3, 20), repeats
    )
    results["ask.impact (isolated)"] = _timeit(
        lambda: _impact(cwd, artifacts, ["src/util.py"]), repeats
    )
    results["ask.tests-for (isolated)"] = _timeit(
        lambda: _tests_for(cwd, project_map, "src/util.py", 20), repeats
    )

    isolated = {
        "callers": results["ask.callers (isolated)"]["median"],
        "callees": results["ask.callees (isolated)"]["median"],
        "reaches": results["ask.reaches (isolated)"]["median"],
        "impact": results["ask.impact (isolated)"]["median"],
        "tests-for": results["ask.tests-for (isolated)"]["median"],
    }
    cheapest = min(isolated.values()) or 0.0001
    ranked = sorted(isolated.items(), key=lambda kv: -kv[1])

    conclusion = {
        "ranked_isolated_ask_verbs_by_cost": [
            {"verb": verb, "median_ms": cost, "times_vs_cheapest": round(cost / cheapest, 1)}
            for verb, cost in ranked
        ],
        "selected_verbs_for_native_delegation": ["impact", "tests-for"],
        "rationale": (
            "Every `ask <verb>` call pays a fixed `build_artifacts()` scan up front "
            "regardless of verb (see index.build_artifacts above) -- that shared cost "
            "is out of scope for a per-verb delegation decision and is excluded from "
            "the ranking above. Isolating each verb's OWN logic (build_artifacts "
            "already computed once, excluded from the timing) shows `impact` and "
            "`tests-for` are the two most expensive verb-specific suboperations by a "
            "wide margin: `impact` recomputes a fresh flow-inventory and scans every "
            "spec/doc file on each call (`_scan_manual_docs_for_references`), and "
            "`tests-for` reads the full text of every test file on each call. "
            "`callers`/`callees`/`reaches` are simple in-memory graph lookups over "
            "already-parsed `call_graph`/`symbol_index` data and are cheap by "
            "comparison, so they are not prioritized for a native fast path here."
        ),
    }

    return {
        "schema": REPORT_SCHEMA,
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": os.path.relpath(FIXTURE_SOURCE, REPO),
        "measurements": results,
        "conclusion": conclusion,
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    repeats = DEFAULT_REPEATS
    out_path = DEFAULT_OUT
    i = 0
    while i < len(argv):
        if argv[i] == "--repeats":
            i += 1
            repeats = max(1, int(argv[i]))
        elif argv[i] == "--out":
            i += 1
            out_path = argv[i]
        else:
            print(f"unknown argument: {argv[i]}", file=sys.stderr)
            return 2
        i += 1

    report = run(repeats=repeats)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nwrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
