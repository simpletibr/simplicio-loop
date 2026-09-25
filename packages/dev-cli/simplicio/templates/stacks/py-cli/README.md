# py-cli

Python 3.12 + Typer + Rich scaffold for command-line tools, local automations,
and developer workflow utilities.

## When to use this stack

- Command-line app with subcommands and typed options
- Tool needs polished terminal output
- Python packaging and pytest are the desired defaults

## Layout produced

```
<project_name>/
|-- src/app/cli.py
|-- tests/test_cli.py
|-- pyproject.toml
`-- README.md
```

## Verify loop

- `install`: `python3 -m pip install -e .[dev]`
- `test`: `pytest -q`
- `lint`: `ruff check src tests`
