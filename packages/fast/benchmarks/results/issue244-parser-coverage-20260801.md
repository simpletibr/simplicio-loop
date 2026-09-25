# Issue 244 parser adapter coverage — 2026-08-01

Measured with:

```text
coverage run --branch --source=simplicio_fast.parser_adapter -m pytest -q tests/test_parser_adapter_244.py
coverage report -m
```

- Tests: 25 passed, 16 subtests passed.
- Statements: 469 total, 34 missed — 91% line coverage.
- Branches: 246 total, 29 partial — 217 covered, 88.2% branch coverage.
- Threshold: 90% lines / 85% branches — passed.

This is the focused parser-adapter evidence only; full #244 acceptance remains open for frozen legacy parity, property/fuzz, benchmark resource receipts and installed cross-platform E2E.

