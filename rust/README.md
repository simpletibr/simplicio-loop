# simplicio-mapper Rust adapters

`mapper-core/` is the reusable, effect-free Rust semantic core introduced for
Mapper #616. It owns deterministic hashing, import parsing, bounded batch
parsing, and canonicalization kernels. It does not own filesystem lifecycle,
auth, effects, fallback orchestration, source edits, or Runtime knowledge.

The root crate is the optional Python/PyO3 adapter. `runtime-adapter/` is a
thin, JSON-boundary Runtime adapter used by the local differential harness;
the separate Simplicio Runtime repository consumes the core through the
sequenced migration plan in `docs/evidence/mapper-616-runtime-migration-plan.md`.

```bash
cargo test --manifest-path rust/mapper-core/Cargo.toml
cargo test --manifest-path rust/runtime-adapter/Cargo.toml
cargo test --manifest-path rust/Cargo.toml --workspace
python3 scripts/mapper_differential.py --repo . --json
```

## Python/PyO3 adapter

Optional Rust acceleration crate for [simplicio-mapper](https://pypi.org/project/simplicio-mapper/).

Exposes two PyO3-bound functions used by the mapper's hot paths:

- `sha256_hex(text)` — content hash for the file inventory.
- `parse_imports(text, language)` — language-aware import extractor for
  JavaScript/TypeScript, Python, C#/Razor and Go.

The Python package falls back to pure-Python equivalents when this crate is not
installed, so it remains entirely optional.

## Build (development)

```bash
pip install maturin
cd rust
maturin develop --release
```

This builds the extension into the active virtualenv as
`simplicio_mapper_rs`.

## Build a wheel

```bash
maturin build --release
```

Wheels are written to `target/wheels/`.

## License

MIT
