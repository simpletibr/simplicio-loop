# bash-cli best practices

## Script structure
- Start with `set -euo pipefail`.
- Keep parsing, validation, and command execution in separate functions.
- Quote variables unless intentionally expanding words.

## CLI design
- Support `--help` and clear error messages.
- Avoid hidden global state; pass values explicitly to functions.
- Prefer small commands composed by pipes over large monolithic functions.

## Testing
- Use Bats for command behavior and exit codes.
- Test failure paths and help output.
- Use temp directories instead of mutating the working tree.

## Dependencies discipline
- Prefer POSIX tools when portability matters.
- Gate non-standard binaries with an explicit command check.
