# py-cli best practices

## Project structure
- Keep the Typer app in `src/app/cli.py`.
- Put reusable command logic in small pure functions before wiring Typer.
- Keep side effects at the command boundary.

## CLI design
- Prefer explicit options over positional argument overloads.
- Return clear non-zero exits for recoverable user errors.
- Use Rich only for presentation; keep data transformations plain.

## Testing
- Test pure functions directly.
- Use Typer's `CliRunner` for command behavior and exit codes.
- Keep command output stable enough for assertions.

## Dependencies discipline
- Avoid shelling out when a Python library gives a structured API.
- Keep optional integrations behind subcommands or extras.
