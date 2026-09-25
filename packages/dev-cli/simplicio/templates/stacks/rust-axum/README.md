# rust-axum

Rust + Axum scaffold for small JSON APIs where type safety, predictable
latency, and a compact service binary matter.

## When to use this stack

- Backend-only JSON API
- Team wants Rust ownership and compile-time guarantees
- Service needs async request handling without a heavy framework
- CRUD or webhook service with explicit routing and typed payloads

## When NOT to use this stack

- SSR web application - use `ts-nextjs`
- Laravel ecosystem or PHP team conventions - use `php-laravel`
- Python ML or data integrations - use `py-fastapi`

## Layout produced

```
<project_name>/
+-- src/main.rs        # router, health handler, and entrypoint
+-- Cargo.toml
+-- README.md
```

## Verify-loop

- `install`: `cargo fetch`
- `test`:    `cargo test`
- `lint`:    `cargo clippy --all-targets -- -D warnings`
