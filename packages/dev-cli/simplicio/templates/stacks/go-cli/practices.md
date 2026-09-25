# go-cli best practices

## Project structure
- Keep Cobra command wiring in `cmd/`.
- Keep reusable logic outside command construction.
- Keep config loading explicit and testable.

## CLI design
- Prefer flags with clear defaults over positional ambiguity.
- Return errors from command handlers instead of calling `os.Exit`.
- Keep stdout machine-readable when possible.

## Testing
- Test command output through an injected buffer.
- Test pure command logic without invoking the process.
- Run `go vet ./...` before release.

## Dependencies discipline
- Keep command packages small.
- Use Viper only when config sources go beyond flags and env.
