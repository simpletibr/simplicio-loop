# Contributing to simplicio-loop

## Local gate

Before opening a PR, run the authoritative local gate:

```bash
python3 scripts/check.py   # audit + mirror-parity + tests + loop-contract + clean-env + token-budget
```

This runs the full `tests/` suite, `scripts/check_loop_contract.py` (fixture contract),
`scripts/check_dashboard_event_contract.py` (`simplicio.dashboard-event/v1` schema + fixture drift),
`scripts/claims_audit.py`, `scripts/clean_env_contract.py`, and `scripts/token_budget.py`. A
non-zero exit means the PR is not ready.

If your change touches versioned packaging metadata, also re-check:

```bash
python3 scripts/release_manifest.py --json
python3 -m pytest -q tests/test_release_manifest_unit.py
```

## Definition of Done (DoD) — mandatory quality gate

This repo dogfoods its own rule (`.claude/skills/simplicio-loop/SKILL.md` §
"Definition of Done"): every PR must show evidence for all seven of the following before it is
considered done. A partial pass (e.g. unit tests green but no coverage number, or an
implementation with no regression/perf evidence) is NOT done — keep iterating.

1. ✅ **Implementation** — the change itself, present and working.
2. ✅ **Unit tests** — unit-level coverage of the new/changed logic.
3. ✅ **Integration tests** — the change verified against its real collaborators (no mocks for
   the seam under test).
4. ✅ **System tests** — an end-to-end pass through the actual command/CLI/API surface a user or
   caller would hit.
5. ✅ **Regression tests** — the existing suite still green; no prior behavior silently broken
   (`python3 -m pytest -q tests/`).
6. ✅ **Performance benchmark** — a measured number (latency/throughput/memory) for any change
   that touches a hot path, so a regression is caught by a number, not a feeling.
7. ✅ **Coverage** — line/branch coverage ≥ 85% (target 90%) for the touched files, checked with
   the project's own coverage tool (`pytest-cov`, see `pyproject.toml` `[tool.coverage.*]` /
   `python3 -m pytest --cov=simplicio_loop --cov-report=term-missing`).

Please note in the PR description, item by item, how each of the seven was satisfied (or why it
does not apply — e.g. a docs-only change has no perf-benchmark surface).
