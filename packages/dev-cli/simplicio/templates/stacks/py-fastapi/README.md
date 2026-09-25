# py-fastapi

Python 3.12 + FastAPI 0.115+ scaffold for REST APIs with async endpoints,
SQLAlchemy 2.0 ORM, pytest + httpx for tests, and ruff for linting.

## When to use this stack

- REST or JSON-RPC backend service
- Need async I/O (DB calls, external HTTP fans-out, WebSockets)
- Single-team service where Python is the team lingua franca
- Test-first project: pytest + httpx are standard in this stack

## When NOT to use this stack

- Multi-region SSR app — pick `ts-nextjs` or `php-laravel`
- Heavy CPU work (image processing, ML inference) — Python GIL hurts;
  consider `rust-axum` or `go-gin`
- Single-page UI without API — use a frontend-only template

## Layout produced

```
<project_name>/
├── src/
│   ├── api/            # routers, one file per resource
│   ├── db/             # SQLAlchemy session + models
│   ├── core/           # config, security, dependencies
│   └── main.py         # FastAPI() app factory + uvicorn entry
├── tests/
│   ├── api/            # endpoint integration tests (httpx)
│   └── db/             # ORM unit tests
├── pyproject.toml      # PEP 621 metadata + dev extras
├── .gitignore
├── ruff.toml
└── README.md
```

## Conventions encoded

- All ORM models in `src/db/models.py` until that file exceeds 300 lines
- One router per resource in `src/api/<resource>.py`; mount in `main.py`
- Dependencies (DB session, auth user) declared in `src/core/deps.py`
- Tests mirror source: `tests/api/test_<resource>.py`

## How verify-loop runs

- `install`: `pip install -e .[dev]`
- `test`:    `pytest -q`
- `lint`:    `ruff check src tests`

A task is considered done when its `verify` command exits 0.
