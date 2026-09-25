# Language adapter coverage — issues 247/248/249 — 2026-08-01

Command:

```text
coverage run --branch --source=simplicio_fast.adapters -m pytest -q tests/test_csharp_adapter_247.py tests/test_typescript_adapter_248.py tests/test_rust_adapter_249.py tests/test_adapters_coverage.py
```

- Tests: 14 passed.
- Statements: 114 total, 0 missed — 100% line coverage.
- Branches: 34 total, 0 partial — 100% branch coverage.
- Covered: capability negotiation, unsupported paths, Python nesting/async, C# declarations, TypeScript module/declaration forms, Rust modifiers/impls and workspace-facing lexical paths.

This satisfies the focused adapter coverage threshold; each language issue still needs its real multi-project/corpus, invalidation, Mapper parity, benchmark and installed cross-platform ACs.

