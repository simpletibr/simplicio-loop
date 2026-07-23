# CI and Local Quality Gate (issues #202, #246, #251)

Hosted GitHub Actions are intentionally absent. The repository's release gate
is local and fail-closed: maintainers run it before a push, release or publish
and attach its evidence to the pull request. Pull requests target
`main`; the retained `master` branch is compatibility-only.

## Reproducible local equivalent

Install the development tools and run the following commands from the
repository root. Attach the command output to the pull request:

```bash
python -m pip install -e ".[dev]" build twine
python3 scripts/check_json_boundaries.py --strict
python3 tools/policy_scan.py --repo . --mode strict \
  --markdown docs/evidence/no-internal-json-scan.md \
  --hbp docs/evidence/no-internal-json-scan.hbp
ruff check .
ruff format --check .
mypy simplicio
pytest --cov=simplicio --cov-report=json:coverage.json
python3 scripts/coverage_gate.py --report coverage.json
python3 scripts/token_budget.py --check
python3 scripts/gen_package_interdependence.py --check
python -m build
python -m twine check dist/*
python3 scripts/check_json_boundaries.py --strict --artifact-dir dist
simplicio-py --help
simplicio-cli --help
simplicio-dev-cli --help
```

The embedded Node/Playwright starter is separate from the Python product. Run
`npx playwright test` only when the starter harness changes.

## Coverage contract

- `[tool.coverage.report].fail_under = 85` is the global floor.
- `[tool.coverage.simplicio_critical]` lists modules that must clear 90%.
- `scripts/coverage_gate.py` reads `coverage.json` and enforces both floors.
- `python3 scripts/coverage_gate.py --self-test` proves the guard accepts and
  rejects synthetic reports correctly.

The cross-platform hooks `.claude/hooks/pre-commit.sh` and
`.claude/hooks/pre-commit.ps1` apply the 85% global floor when Python files are
staged and `pytest-cov` is installed. The explicit gate above remains the
source of truth for the coverage thresholds because it also covers the
stricter critical-module floor. The remaining local commands cover token
budget, generated documentation, packaging, and CLI entrypoints.

## Public-interface and regression policy

`tests/python/test_cli_help_snapshot.py` byte-compares `--help` output against
the fixtures in `tests/python/fixtures/cli_help/`. Public CLI changes must
update the matching fixture in the same pull request.

Every bug fix must include a regression test that fails before the fix and
passes afterward. This policy is reviewed locally together with the
adversarial verification required by `DOD.md`; automation never replaces that
review.
