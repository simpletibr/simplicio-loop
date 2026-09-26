#!/usr/bin/env python3
"""Benchmark: full-file-read vs `prototype-context` token cost (issue #286,
step 12 -- "medir reducao de leitura, remapping, tokens e missed-impact").

Scope for this pass: measures the one axis this repo can measure honestly on
its own -- the *token* cost of the two approaches an agent could take before
starting a prototype for a given query:

  - ``full_read``: read every source file in the fixture repo end to end
    (the naive "just read the whole project" baseline).
  - ``prototype_context``: call ``build_prototype_context()`` for the same
    query and measure the serialized envelope it returns.

Remapping-cost and missed-impact-rate measurement (the other two metrics
step 12 names) are now covered by two sibling scripts instead of here:

- ``scripts/prototype_remap_cost_benchmark.py`` -- real wall-clock cost of a
  full remap vs the canonical-map/overlay path for a small (one-file)
  change, using the now-existing ``canonical_builder.py``/
  ``canonical_overlay.py``/``effective_view.py`` APIs (issue #236/#263).
- ``scripts/prototype_impact_accuracy_benchmark.py`` -- recall/precision of
  ``build_prototype_context()``'s impact set against a hand-labeled ground
  truth fixture (``tests/fixtures/impact-ground-truth/python-rename-greet``).

This script only ever reports the token-cost axis.

Two scenarios, both real (no synthetic data):

  - ``--fixture contracts/mapper-artifacts/v1/fixtures/python-minimal/source``
    (the default): the same tiny fixture the other `scripts/*_benchmark.py`
    scripts use for a fast, fully reproducible run. Honest caveat: at this
    fixture's size (4-5 files) the context-pack's fixed envelope fields
    (schema/budget/source-binding metadata) can outweigh the handful of
    tokens a full read of the whole fixture would cost, so this scenario can
    legitimately show *negative* savings -- reported as-is, not hidden.
  - ``--fixture . --scope simplicio_mapper`` (this repo's own package): a
    realistically sized target, closer to what issue #286 is meant to help
    with -- read every file under `simplicio_mapper/` vs a bounded context
    pack for one query, which is where the token-cost gap actually shows up.

Uses the same ``estimate_tokens`` heuristic as `token_budget.py`/`savings.py`
-- a real, printed number, never dressed up as a measured provider token
count.

Run: ``python3 scripts/prototype_context_benchmark.py``
Run (repo-scale scenario): ``python3 scripts/prototype_context_benchmark.py --fixture . --scope simplicio_mapper --arg simplicio_mapper/prototype_context.py``
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

# ruff: noqa: E402, I001
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from simplicio_mapper.prototype_context import build_prototype_context
from simplicio_mapper.savings import estimate_tokens

REPORT_SCHEMA = "simplicio.prototype-context-benchmark/v1"
FIXTURE_SOURCE = REPO / "simplicio_mapper" / "contracts" / "mapper-artifacts" / "v1" / "fixtures" / "python-minimal" / "source"

# Same sample query the module's own tests use as their canonical fixture
# target, so the number this script prints is reproducible against the
# committed test suite.
DEFAULT_TYPE = "bug"
DEFAULT_ARG = "src/app.py"

_READ_EXCLUDE_DIRS = {".git", "__pycache__", ".simplicio-loop"}


def _iter_source_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(part in _READ_EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    return files


def _full_read_tokens(scope_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    total_tokens = 0
    files = _iter_source_files(scope_root)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="surrogateescape")
        except OSError:
            continue
        total_tokens += estimate_tokens(text)
    elapsed = round(time.perf_counter() - started, 6)
    return {"tokens": total_tokens, "file_count": len(files), "seconds": elapsed}


def _prototype_context_tokens(root: Path, type_: str, arg: str) -> dict[str, Any]:
    started = time.perf_counter()
    payload = build_prototype_context(str(root), type_=type_, arg=arg)
    elapsed = round(time.perf_counter() - started, 6)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {
        "tokens": estimate_tokens(serialized),
        "seconds": elapsed,
        "reported_tokens_estimated": payload.get("tokens_estimated"),
    }


def run(
    type_: str = DEFAULT_TYPE,
    arg: str = DEFAULT_ARG,
    fixture: Path = FIXTURE_SOURCE,
    scope: str | None = None,
) -> dict[str, Any]:
    if not fixture.is_dir():
        raise SystemExit(f"fixture not found: {fixture}")
    scope_root = (fixture / scope) if scope else fixture
    if not scope_root.is_dir():
        raise SystemExit(f"scope not found: {scope_root}")

    full_read = _full_read_tokens(scope_root)
    context = _prototype_context_tokens(fixture, type_, arg)

    baseline = full_read["tokens"]
    actual = context["tokens"]
    saved = baseline - actual
    pct_saved = round((saved / baseline) * 100, 2) if baseline else 0.0

    fixture_rel = str(fixture.relative_to(REPO)) if fixture != REPO else "."
    return {
        "schema": REPORT_SCHEMA,
        "query": {"type": type_, "arg": arg},
        "fixture": fixture_rel,
        "scope": scope or fixture_rel,
        "full_read": full_read,
        "prototype_context": context,
        "tokens_saved": saved,
        "pct_saved": pct_saved,
        "estimator": "heuristic:chars-div-4-or-tiktoken",
        "proof_kind": "estimated",
        "proof_kind_note": (
            "tokens_saved/pct_saved are computed from real estimate_tokens() calls over "
            "real serialized artifacts produced in this run (a genuine measurement of "
            "*this run's* byte counts, not an a-priori guess) -- but estimate_tokens() "
            "itself is a local estimator (tiktoken when installed, chars/4 heuristic "
            "otherwise), never a real provider-billed token count, so proof_kind stays "
            "'estimated' per the ecosystem convention (savings.py docstring / CLAUDE.md "
            "'Token savings report' rule): only real provider-reported usage earns "
            "'measured'"
        ),
        "deferred": [],
        "see_also": [
            "scripts/prototype_remap_cost_benchmark.py (remapping-cost comparison)",
            "scripts/prototype_impact_accuracy_benchmark.py (missed-impact-rate scoring)",
        ],
    }


def main(argv: list[str]) -> int:
    type_ = DEFAULT_TYPE
    arg = DEFAULT_ARG
    fixture = FIXTURE_SOURCE
    scope = None
    if "--type" in argv:
        type_ = argv[argv.index("--type") + 1]
    if "--arg" in argv:
        arg = argv[argv.index("--arg") + 1]
    if "--fixture" in argv:
        raw = argv[argv.index("--fixture") + 1]
        fixture = REPO if raw == "." else Path(raw)
        if not fixture.is_absolute():
            fixture = (REPO / raw).resolve() if raw != "." else REPO
    if "--scope" in argv:
        scope = argv[argv.index("--scope") + 1]

    report = run(type_, arg, fixture=fixture, scope=scope)
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"query:              type={report['query']['type']} arg={report['query']['arg']}")
        print(f"fixture:            {report['fixture']}")
        print(
            f"full_read:          {report['full_read']['tokens']} tokens "
            f"({report['full_read']['file_count']} files, {report['full_read']['seconds']}s)"
        )
        print(
            f"prototype_context:  {report['prototype_context']['tokens']} tokens "
            f"({report['prototype_context']['seconds']}s)"
        )
        print(f"tokens_saved:       {report['tokens_saved']} ({report['pct_saved']}%)")
        print(f"proof_kind:         {report['proof_kind']}")
        for item in report["deferred"]:
            print(f"deferred:           {item}")
        for item in report["see_also"]:
            print(f"see_also:           {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
