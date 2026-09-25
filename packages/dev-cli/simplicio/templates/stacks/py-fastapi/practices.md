# py-fastapi best practices (planner reference)

## Project structure
- `src/main.py` — `create_app() -> FastAPI` factory + `if __name__ == "__main__"` uvicorn entry
- `src/api/` — one module per resource; each module exports a `router` of type `APIRouter`
- `src/db/` — `session.py` (engine, SessionLocal, get_db dep), `models.py` (Declarative base + models), `init.py` (create_all for tests)
- `src/core/` — `config.py` (Settings via pydantic-settings), `security.py` (auth deps), `deps.py` (`get_current_user`, etc.)
- `tests/` — mirrors `src/`. One test file per source module.

## Typing & validation
- All public function signatures fully typed; mypy-friendly even though we don't ship mypy by default
- Pydantic v2 models for every request/response body
- Path/query params use `Annotated[..., Query(...)]` form, not raw default args
- SQLAlchemy 2.0 declarative style (`Mapped[X]` columns, NOT legacy `Column(...)` assignments)

## API design
- Resource routes mounted with explicit prefix: `app.include_router(units.router, prefix="/units", tags=["units"])`
- Status codes explicit: `@router.post("", status_code=201)`
- Response models declared: `response_model=UnitRead`
- Errors via `HTTPException` only; never raise generic exceptions to the framework
- Pagination: `?limit=&offset=` with hard cap (e.g. `limit <= 100`)

## Database
- `get_db()` dependency yields a session; commits on success, rollbacks on exception
- Never instantiate SessionLocal inside a route — always via DI
- Connection URL from `Settings.DATABASE_URL`, never hardcoded
- Migrations: Alembic when the project has more than 3 models; SQLite + create_all OK for first draft

## Testing
- pytest fixtures in `tests/conftest.py`: `test_client` (httpx.AsyncClient or TestClient), `db_session` with SQLite in-memory
- Each test creates + tears down its own data — no global state
- API tests use `test_client.post(...)`; assert response.status_code AND response.json()
- One assertion per concern; do not chain unrelated asserts

## Config
- Single `Settings` class in `src/core/config.py` reading from env via pydantic-settings
- All env vars prefixed with the project namespace (e.g. `APP_DATABASE_URL`)
- No `.env` committed; `.env.example` is fine

## Errors & logging
- `logging.getLogger(__name__)` at module level; no `print()` in production code
- Errors at boundary: log + raise HTTPException; do not silently swallow
- Structured log format set in `main.py`: `logging.basicConfig(level=INFO, format=...)`

## Dependencies discipline
- Pin top-level deps with floor (`>=`) not exact
- Test/lint/format tools live in `[project.optional-dependencies] dev`
- Do NOT add: requests (we have httpx), flask, django, sqlmodel (we use SQLAlchemy directly)

## Output the planner SHOULD produce for this stack
- Tasks order: settings/config → DB session → models → schemas (pydantic) → routes → tests
- Each task touches ONE file
- `verify` per task references the test file directly (e.g. `pytest tests/db/test_models.py -q`)
- `test_command` (top-level) = `pytest -q`
- `lint_command` = `ruff check src tests`
