# py-flask

Python 3.12 + Flask 3 scaffold for small synchronous JSON APIs and server-side
apps where a lightweight WSGI shape is the right default.

## When to use this stack

- Small REST API or internal tool
- Synchronous request handling is acceptable
- The team wants simple Flask conventions instead of a larger framework

## Layout produced

```
<project_name>/
|-- src/app.py
|-- tests/test_health.py
|-- pyproject.toml
|-- ruff.toml
`-- README.md
```

## Verify loop

- `install`: `python3 -m pip install -e .[dev]`
- `test`: `pytest -q`
- `lint`: `ruff check src tests`
