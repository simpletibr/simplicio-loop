# rust-leptos

Rust + Leptos scaffold for full-stack Rust web applications and SSR-capable UI.

## When to use this stack

- Rust team wants a web UI without leaving Rust
- SSR or progressive hydration is part of the target
- Strong typing across UI and server logic matters

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
