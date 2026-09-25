# Fast parser adapter v1

`parser-adapter/v1` is a bounded data contract around language extraction. It
is not a replacement for Mapper's public ContextGraph and it never exposes
SFAST offsets, private AST nodes, or language-specific binary structures.

## Modes

Integrated mode is used only after a Mapper-owned identity is supplied:

```python
payload = build_payload(
    root,
    mode="integrated",
    mapper_generation="<mapper-generation>",
    commit="<40 lowercase hex characters>",
)
```

It fails closed with `mapper_required` when either identity is missing. The
payload preserves `mapper_generation`, `commit`, source file SHA-256 values,
stable symbol IDs, relations, diagnostics, completeness, and a canonical
`payload_sha256`.

Bootstrap mode is an explicit local diagnostic path:

```python
payload = build_payload(root, mode="bootstrap")
```

Bootstrap output has `mode: "bootstrap"` and must not be represented as a
Mapper handle or advertised as an integrated production graph.

## Bounded contract

The default limits are:

| Resource | Limit |
|---|---:|
| Source files | 10,000 |
| Symbols | 1,000,000 |
| Relations | 2,000,000 |
| Canonical payload | 64 MiB |

`build_payload(..., limits={...})` may lower these limits for a bounded
request. A request exceeding a limit fails before returning a partial success
with one of `file_limit_exceeded`, `symbol_limit_exceeded`,
`relation_limit_exceeded`, or `payload_limit_exceeded`.

`validate_payload` applies the default upper bounds and also rejects unsafe
paths, invalid UTF-8 metadata, malformed SHA-256 values, duplicate symbol IDs,
invalid ranges, unknown relation kinds, invalid confidence values, malformed
Mapper identity, and digest drift.

## Payload identity

Each file records a normalized relative path, language, UTF-8 encoding and
content SHA-256. Each symbol records its stable ID, name, qualified name,
kind, language, file and source range. Relations use only the public kinds
`import`, `reference`, `call`, `definition`, and `test`, with confidence and
optional stable IDs.

The canonical digest is computed over the payload without `payload_sha256`,
using sorted keys and compact JSON. Consumers must validate it before using
any graph data.

## Failure and compatibility rules

- Unknown schema, producer, mode, relation kind, path escape, digest drift or
  bounds violation fails closed.
- A partial parse is represented by `completeness: "partial"` plus diagnostics;
  it is never silently converted to complete success.
- Optional lexical adapters for TypeScript, Rust and C# emit deterministic
  public relations, but native compiler/toolchain conformance remains a
  separate capability gate.
- Mapper remains authoritative for integrated stable IDs and graph provenance.

Rust payload callers may provide the selected Cargo feature set through
`rust_features`. The normalized feature list is included in the Rust workspace
fingerprint, so changing feature selection invalidates the generation identity;
omitting it preserves the existing default behavior.

The implementation is in `src/simplicio_fast/parser_adapter.py`; the focused
contract tests are in `tests/test_parser_adapter_244.py`.
