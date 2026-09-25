# rust-cli best practices

## Project structure
- Keep argument parsing in a small `Args` struct.
- Move business logic into functions that return `anyhow::Result`.
- Keep stdout for user output and stderr for diagnostics.

## CLI design
- Prefer explicit flags and Clap validation.
- Use clear exit errors instead of panics.
- Keep output stable when tests depend on it.

## Testing
- Unit-test parsing-adjacent pure functions.
- Add integration tests once command behavior grows.
- Run Clippy with warnings denied before release.

## Dependencies discipline
- Keep the CLI dependency graph small.
- Avoid async runtimes unless the tool performs real concurrent I/O.
