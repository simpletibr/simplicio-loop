# Scripts

Scripts should make the project runnable and verifiable without tribal knowledge.

Expected scripts:

- `start.ps1` / `start.sh`: start local services or print the commands to start them.
- `test.ps1` / `test.sh`: run the project's relevant validation.
- `evidence.ps1` / `evidence.sh`: capture Playwright evidence for a smoke scenario.
- `update-starter.ps1` / `update-starter.sh`: update the installed starter structure safely.

Adapt these scripts to the real stack after applying the starter.

Rules:

- Fail with a non-zero exit code on errors.
- Print clear next steps when a required command is missing.
- Keep secrets out of scripts.
- Prefer environment variables for URLs and credentials.

Update command:

```powershell
.\scripts\update-starter.ps1
```

Use `LLM_PROJECT_MAPPER_SOURCE` to test from a local clone instead of npm:

```powershell
$env:LLM_PROJECT_MAPPER_SOURCE="C:\Users\you\source\repos\llm-project-mapper"
.\scripts\update-starter.ps1
```

## Python package scripts (`simplicio-cli`)

These are `--check`-able, deterministic scripts for the real Python product
(`simplicio/`), not the embedded starter harness above:

- `gen_package_interdependence.py --check`: fails if
  `docs/PYTHON_PACKAGE_INTERDEPENDENCE.md` drifted from `pyproject.toml` (#101).
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

  This complements, but does not replace, `tests/python/test_naming_contract.py`
  (which guards the source tree, not the packaged artifact) and is
  intentionally narrower than `simplicio-agent` issue #194's own scanner —
  see `scripts/scan_artifacts.py`'s module docstring for the scoping
  rationale.
- `release_train_reconcile.py reconcile`: consumes one authenticated Mapper
  release event, updates the bounded dependency floor, resolves the candidate
  into `uv.lock`, and records the single-PR lock receipt.
- `release_train_conformance.py`: verifies installed Mapper version/digests
  and runs the observable map → retrieve → edit → test → receipt smoke. It
  accepts immutable N/N-1 Mapper source checkouts for contract validation and
  exits non-zero when that evidence is missing.
- `build_component_release.py`: hashes `dist` artifacts and emits the signed
  Dev CLI `component-release/v1` manifest used by the Loop dispatch workflow.
