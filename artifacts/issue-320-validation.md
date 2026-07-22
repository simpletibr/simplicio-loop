# Issue 320 validation evidence

## Environment
```text
a6a7610860f01b43e11e1246306ebe1a4977ab2f
Python 3.12.13
v20.20.2
11.4.2
```

## Focused unit/integration/regression checks
```text
...................                                                      [100%]
19 passed in 0.68s
```

## System failure-path check (expected release block)
```text
# Mapper quality gate

- Generated: 2026-07-22T20:37:25+00:00
- Overall: **BLOCKED**
- Execution mode: local/offline; GitHub Actions not required

| Criterion | Result | Evidence |
| --- | --- | --- |
| Internal JSON inventory | fail | INTERNAL_JSON .orchestrator/learn/pending.jsonl<br>INTERNAL_JSON .orchestrator/loop/journal.jsonl<br>INTERNAL_JSON .simplicio/architecture-inventory.json<br>INTERNAL_JSON .simplicio/business-rules.json<br>INTERNAL_JSON .simplicio/call-graph.json<br>INTERNAL_JSON .simplicio/flow-inventory.json<br>INTERNAL_JSON .simplicio/ledger/savings-events.jsonl<br>INTERNAL_JSON .simplicio/map-job.json<br>INTERNAL_JSON .simplicio/precedent-index.json<br>INTERNAL_JSON .simplicio/project-map.json<br>INTERNAL_JSON .simplicio/runs/sprint-1782916597218-47883/events.jsonl<br>INTERNAL_JSON .simplicio/runs/sprint-1782916597218-47883/state.json<br>INTERNAL_JSON .simplicio/savings-ledger.jsonl<br>INTERNAL_JSON .simplicio/session-hooks/06887c3c-e6d0-4eaf-a16e-2cd82ed16fcc-1782935876.json<br>INTERNAL_JSON .simplicio/session-hooks/23ebc9a5-7b62-47d3-b3e4-9b8536e07d8d-1783000499.json<br>INTERNAL_JSON .simplicio/session-hooks/23ebc9a5-7b62-47d3-b3e4-9b8536e07d8d-1783000837.json<br>INTERNAL_JSON .simplicio/session-hooks/23ebc9a5-7b62-47d3-b3e4-9b8536e07d8d-1783001202.json<br>INTERNAL_JSON .simplicio/session-hooks/23ebc9a5-7b62-47d3-b3e4-9b8536e07d8d-1783001262.json<br>INTERNAL_JSON .simplicio/session-hooks/8f6d9a4a-fc5c-4325-b3f3-9400ef51fce0-1783429467.json<br>INTERNAL_JSON .simplicio/session-hooks/8f6d9a4a-fc5c-4325-b3f3-9400ef51fce0-1783429504.json<br>INTERNAL_JSON .simplicio/session-hooks/8f6d9a4a-fc5c-4325-b3f3-9400ef51fce0-1783429543.json<br>INTERNAL_JSON .simplicio/spec-drift.json<br>INTERNAL_JSON .simplicio/symbol-index.json<br>json-boundaries: 23 finding(s); strict=blocked |
| Runtime ecosystem doctor | null | required local tool is unavailable |
| Cross-repository E2E | null | adjacent released packages were not exercised |
| Performance | null | benchmark workload and hardware were not recorded |
| HBP receipt | null | a conformant HBP execution receipt was not recorded |
| HBI conformance | null | Runtime HBI conformance was not recorded |

A null result is unavailable evidence, never a passing zero.
exit_code=1
```

## Additional checks

```text
ruff check scripts/mapper_quality_gate.py scripts/check_json_boundaries.py tests/test_mapper_quality_gate.py tests/test_json_boundaries.py
All checks passed!

npm test
92 passed, 1 skipped, 0 failed

npm pack --dry-run
454 files; 938.0 kB package; 4.5 MB unpacked

python -m pytest tests/test_mapper_quality_gate.py tests/test_json_boundaries.py -q
19 passed in 0.73s; elapsed_seconds=1.722
```

## Environment limitations and pre-existing failures

```text
python -m pytest tests/python -q
collection error: ModuleNotFoundError: No module named 'hypothesis'

python -m pytest ... --cov=...
pytest error: unrecognized arguments --cov (pytest-cov unavailable)

python3 scripts/token_budget.py --check
pre-existing threshold failures: AGENTS.md, CLAUDE.md, simplicio_mapper/mapper/emit.py

npm run lint
0 errors; warnings: shellcheck/PSScriptAnalyzer unavailable and pre-existing trailing whitespace in two docs
```
