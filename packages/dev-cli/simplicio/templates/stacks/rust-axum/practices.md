# rust-axum best practices (planner reference)

## Project structure

- Keep the first scaffold small: `src/main.rs` can own router setup until the
  app grows past a few routes.
- Move handlers into `src/routes/` when a resource needs more than one small
  endpoint.
- Keep domain structs and validation near the handler until there is real reuse.

## API design

- Build routers with `Router::new().route(...)` and compose nested routers
  explicitly.
- Return typed responses such as `Json<T>` and `StatusCode` tuples.
- Derive `Serialize` for response DTOs and `Deserialize` for request DTOs.
- Keep handler functions async and focused on one route concern.

## Testing

- Use `tower::ServiceExt::oneshot` with `Request<Body>` for handler tests.
- Keep the first health or smoke test in `src/main.rs` with the scaffold.
- Every route task should add or update a `cargo test` passing test.

## Output the planner SHOULD produce for this stack

- Tasks order: router setup -> resource DTO -> handlers -> tests.
- Each task touches ONE file.
- `test_command` = `cargo test`
- `lint_command` = `cargo clippy --all-targets -- -D warnings`
