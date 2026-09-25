# Scripts

`--check`-able, deterministic scripts for the real Python product (`simplicio/`):

- `token_budget.py`: tracks token-budget regressions against
  `scripts/token_budget_baseline.json`.
- `verify_default_branch.py`: queries public GitHub metadata and emits a JSON
  receipt proving that `main` is the default while recording the `main` and
  compatibility `master` commit SHAs. The receipt also fails closed if those
  tips diverge, proving that the retained branch has not received independent
  commits. Run it after changing the repository setting for issue #98:

  ```bash
  python3 scripts/verify_default_branch.py
  ```
- `scan_artifacts.py --check`: scans the built `dist/*.whl`/`dist/*.tar.gz`
  contents for stray legacy-brand ("Hermes") mentions outside the documented
  compat surface (issue #167 plan step 24, "Escanear artifacts com regra
  Agent #194"). Run this **before packaging a release**, after `python -m
  build`:

  ```bash
  python -m build
  python3 scripts/scan_artifacts.py --check
  ```
- `release_train_reconcile.py reconcile`: consumes one authenticated Mapper
  release event, updates the bounded dependency floor, resolves the candidate
  into `uv.lock`, and records the single-PR lock receipt.
- `release_train_conformance.py`: verifies installed Mapper version/digests
  and runs the observable map → retrieve → edit → test → receipt smoke. It
  accepts immutable N/N-1 Mapper source checkouts for contract validation and
  exits non-zero when that evidence is missing.
- `build_component_release.py`: hashes `dist` artifacts and emits the signed
  Dev CLI `component-release/v1` manifest used by the Loop dispatch workflow.
- `quality_gate.py`: runs and persists the local, SHA-bound quality gate
  (json-boundaries, ruff, ruff-format, mypy, pytest, coverage-gate,
  token-budget, wheel/mapper-matrix smoke, cli/changeset help).
