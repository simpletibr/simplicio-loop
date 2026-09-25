# Issue #41: conformance golden corpus

This slice introduces `simplicio.fast.golden-corpus/v1` at
`fixtures/conformance/v1/corpus.json`. It is a versioned, source-only contract for the
Python, TypeScript, Rust and C# cases that future engines must read and write
identically. Each checked-in source file has a SHA-256 digest in the manifest.

The corpus deliberately includes imports, namespaces, overloads, calls, tests, a
removed-file tombstone, partial capability, abstention and corruption scenarios.
`tests/test_golden_corpus.py` verifies the manifest, all four language entries and
fail-closed detection after a fixture mutation.

This is a contract/fixture slice only. The current differential harness can prove
Python/Rust stats, query and bounded context for a generated SFAST snapshot. Before comparing
normalized fields, it now requires each versioned response envelope and requires Rust responses
to identify `engine: rust`; schema or engine-identity drift fails closed and cannot produce a
passing conformance receipt. It still does not parse TypeScript or C#, perform bidirectional
cross-language write/read, run mutation/fuzz/schema matrices, or gate auto-selection on this
corpus. Those remain open acceptance criteria for issue #41.

Run the focused receipt with:

```text
python -m unittest tests.test_golden_corpus -v
python scripts/conformance.py --snapshot <snapshot> --rust <binary> --term UserService --context-term UserService --root .
```
