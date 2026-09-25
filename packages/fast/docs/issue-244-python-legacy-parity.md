# Issue #244 Python legacy parity

`benchmarks/bench_parser_legacy_parity_244.py` runs the current
`parser_adapter.build_payload()` and the legacy `_parse_file()` extractor over
the frozen `fixtures/conformance/v1` corpus. For every Python file it compares
public symbol identity/ranges, public relation triples and source SHA-256. It
also rebuilds the adapter payload twice and records byte-identical payload
identity.

The receipt labels native C#/TypeScript/Rust implementations as a separate
partial gate; their absence is never converted into empty success. Generate
the Windows receipt with:

```text
python benchmarks/bench_parser_legacy_parity_244.py `
  --root fixtures/conformance/v1 `
  --json-out benchmarks/results/issue244-python-legacy-parity-windows-20260802.json
```
