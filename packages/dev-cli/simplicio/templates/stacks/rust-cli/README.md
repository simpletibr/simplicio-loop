# rust-cli

Rust + Clap scaffold for fast, typed command-line tools.

## When to use this stack

- CLI needs a single static binary
- Argument parsing and error handling must be robust
- Performance and distribution size matter

## Layout produced

```
<project_name>/
|-- Cargo.toml
|-- src/main.rs
`-- README.md
```

## Verify loop

- `install`: `cargo fetch`
- `test`: `cargo test`
- `lint`: `cargo clippy --all-targets -- -D warnings`
