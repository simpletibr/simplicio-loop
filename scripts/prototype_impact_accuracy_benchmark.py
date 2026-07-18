#!/usr/bin/env python3
"""Benchmark: missed-impact-rate of `prototype-context`'s impact graph
(issue #286 step 12 -- the second metric `scripts/prototype_context_benchmark.py`
explicitly deferred: "missed-impact-rate scoring (needs a labeled corpus of
known-correct impact sets)").

This script builds that corpus (one fixture so far, more can be added the
same way) and scores `build_prototype_context()`'s predicted impact set
against it with real recall/precision -- never invented percentages.

Fixture: `tests/fixtures/impact-ground-truth/python-rename-greet/`. One
concrete change (rename `greet` -> `greet_person` in `src/greeter.py`);
`ground_truth.json` lists the real files that import/call `greet`
(hand-verified by reading the fixture source) and one deliberate noise file
that never references it.

Predicted set (what this script scores): `build_prototype_context()`'s
`target_files` + `affected_symbols[*].path` + `affected_tests`, minus the
target file itself (the target file is the change site, not something the
impact graph needs to "discover").

Honest caveat this run's numbers already surface (not hidden): `_impact()`
(`simplicio_mapper/query.py`) only collects symbols *defined in* the target
file(s) -- it does not walk the call graph to find callers of a renamed
symbol. `affected_tests` (`_tests_for()`) is a text search for the target
file's path/stem/top-level-module string inside each known test file, which
can hit by coincidence (e.g. every file in the fixture importing from the
same top-level `src` module) rather than by a real call-graph edge. Both are
real, current behaviors of `prototype_context.py`/`query.py` -- this
benchmark measures them as they exist today, it does not patch them up to
score better.

`proof_kind: estimated` throughout -- recall/precision are computed from a
real run of `build_prototype_context()` against a real fixture in this
session (never a guess), but "impact" here is defined by this repo's own
current heuristics, not a ground truth an external oracle certified, so the
numbers describe *this pipeline's* behavior on *this one fixture*, not a
universal accuracy claim.

Run: ``python3 scripts/prototype_impact_accuracy_benchmark.py``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# ruff: noqa: E402, I001
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from simplicio_mapper.prototype_context import build_prototype_context

REPORT_SCHEMA = "simplicio.prototype-impact-accuracy-benchmark/v1"
DEFAULT_FIXTURE = REPO / "tests" / "fixtures" / "impact-ground-truth" / "python-rename-greet"


def _load_ground_truth(fixture: Path) -> dict[str, Any]:
    path = fixture / "ground_truth.json"
    if not path.is_file():
        raise SystemExit(f"ground truth not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _predicted_impact_set(payload: dict[str, Any], target_file: str) -> set[str]:
    predicted: set[str] = set()
    for path in payload.get("target_files") or []:
        predicted.add(path)
    for symbol in payload.get("affected_symbols") or []:
        path = symbol.get("path")
        if path:
            predicted.add(path)
    for path in payload.get("affected_tests") or []:
        predicted.add(path)
    # The target file is the change site itself, not a "discovery" -- scoring
    # it as a hit/miss either way would inflate both recall and precision
    # for free on every fixture, so it is excluded from the scored set.
    predicted.discard(target_file)
    return predicted


def _score(predicted: set[str], impacted: set[str], non_impacted: set[str]) -> dict[str, Any]:
    true_positives = sorted(predicted & impacted)
    false_negatives = sorted(impacted - predicted)
    false_positives_noise = sorted(predicted & non_impacted)
    false_positives_unlabeled = sorted(predicted - impacted - non_impacted)

    recall = round(len(true_positives) / len(impacted), 4) if impacted else None
    scored_predicted = predicted & (impacted | non_impacted)
    precision = round(len(true_positives) / len(scored_predicted), 4) if scored_predicted else None

    return {
        "predicted": sorted(predicted),
        "true_positives": true_positives,
        "false_negatives_missed_impact": false_negatives,
        "false_positives_labeled_noise": false_positives_noise,
        "false_positives_unlabeled": false_positives_unlabeled,
        "recall": recall,
        "precision": precision,
        "missed_impact_rate": round(1 - recall, 4) if recall is not None else None,
    }


def run(fixture: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    if not fixture.is_dir():
        raise SystemExit(f"fixture not found: {fixture}")
    ground_truth = _load_ground_truth(fixture)
    change = ground_truth["change"]
    impacted = set(ground_truth.get("impacted_files") or [])
    non_impacted = set(ground_truth.get("non_impacted_files") or [])

    payload = build_prototype_context(
        str(fixture),
        type_=change.get("query_type", "bug"),
        arg=change["query_arg"],
    )
    predicted = _predicted_impact_set(payload, change["target_file"])
    scoring = _score(predicted, impacted, non_impacted)

    return {
        "schema": REPORT_SCHEMA,
        "fixture": str(fixture.relative_to(REPO)),
        "change": change,
        "ground_truth": {
            "impacted_files": sorted(impacted),
            "non_impacted_files": sorted(non_impacted),
        },
        "scoring": scoring,
        "proof_kind": "estimated",
        "proof_kind_note": (
            "recall/precision are computed from a real build_prototype_context() call "
            "against a real, committed fixture in this session -- but 'ground truth' here is "
            "this repo's own hand-authored labels for one fixture, not an external oracle, "
            "so this is a real measurement of this pipeline's current behavior, not a "
            "universal accuracy guarantee"
        ),
        "known_limitation": (
            "_impact() (query.py) only collects symbols defined in the target file(s); it "
            "does not walk the call graph for callers of a renamed symbol, so non-test caller "
            "files are structurally invisible to prototype-context's impact graph today -- "
            "this benchmark's false_negatives_missed_impact makes that gap visible with a real "
            "number instead of leaving it as an assumption."
        ),
    }


def main(argv: list[str]) -> int:
    fixture = DEFAULT_FIXTURE
    if "--fixture" in argv:
        raw = argv[argv.index("--fixture") + 1]
        fixture = Path(raw)
        if not fixture.is_absolute():
            fixture = (REPO / raw).resolve()

    report = run(fixture)
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0

    scoring = report["scoring"]
    print(f"fixture:              {report['fixture']}")
    print(f"change:               rename {report['change']['symbol']} in {report['change']['target_file']}")
    print(f"ground_truth impacted: {report['ground_truth']['impacted_files']}")
    print(f"predicted:            {scoring['predicted']}")
    print(f"true_positives:       {scoring['true_positives']}")
    print(f"false_negatives (missed): {scoring['false_negatives_missed_impact']}")
    print(f"false_positives (noise): {scoring['false_positives_labeled_noise']}")
    print(f"recall:               {scoring['recall']}")
    print(f"precision:            {scoring['precision']}")
    print(f"missed_impact_rate:   {scoring['missed_impact_rate']}")
    print(f"proof_kind:           {report['proof_kind']}")
    print(f"known_limitation:     {report['known_limitation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
