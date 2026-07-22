# Issue #262 quality-gate evidence

Date: 2026-07-22. Branch base: `f0f9231` (`upstream/main`). Python 3.12.13 on
Linux x86_64.

## Implemented and exercised

- `python3 scripts/check_json_boundaries.py --strict`: 0 unclassified findings.
- `pytest -q tests/python/test_json_boundaries.py tests/python/test_local_quality_gate.py
  --cov=scripts.check_json_boundaries --cov-branch --cov-report=term-missing`:
  14 passed; scanner coverage 88% including branches.
- `python -m build` and `python -m twine check dist/*`: wheel and sdist built and
  passed metadata checks. Scanning each archive returned 0 packaged internal JSON
  findings.
- Adversarial archive tests inject `.simplicio/generated.json` into wheel and
  sdist layouts; strict scanning rejects both. A malformed archive fails closed,
  while an external `schema.json` remains allowed.
- Exact-registry tests reject traversal, absolute paths, wildcard paths, missing
  owners, missing reasons, and missing expiration dates.
- The benchmark command and measured values are recorded in
  `issue-262-scanner-benchmark.md`; unobservable metrics are not represented as
  zero.

## Repository-wide gate state

The focused issue gate is green. The repository-wide commands are not green on
the unmodified `main` baseline: `ruff check .` reports 24 existing findings,
`mypy simplicio` reports 5 existing errors, and `pytest -q` reports 26 failures
(1,822 passed, 16 skipped). The failures include stale CLI snapshots, stale
Mapper dependency assertions, provider behavior, and unrelated task validation.
They are outside issue #262 and were not rewritten in this focused change.

## Criteria not proven by this repository change

This PR does not claim Runtime HBI conformance, HBP migration lineage, atomic
legacy migration, cross-repository released-package compatibility, or the
Linux/macOS/Windows matrix. The repository still contains the dated legacy
exceptions listed in `config/json-boundaries.toml`; classification is enforced,
but their underlying producers have not all migrated. These are explicit
release blockers rather than passing zeroes. The PR must remain unmerged until
those criteria have executable evidence and the repository-wide gate is green.
