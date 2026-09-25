# py-flask best practices

## Project structure
- Keep the application factory in `src/app.py` as `create_app()`.
- Put routes in blueprints once the project has more than one resource.
- Keep config in environment variables and read it once at app creation.

## API design
- Return JSON objects consistently with `jsonify`.
- Use explicit HTTP status codes for create, update, and error paths.
- Validate request payloads at the boundary before touching business logic.

## Testing
- Use Flask's test client through pytest fixtures.
- Keep health and smoke tests cheap so the verify loop can run often.
- Add one focused test file per route module.

## Dependencies discipline
- Prefer Flask built-ins until a real extension is needed.
- Do not add global mutable state outside the app factory.
- Keep lint and test tools in the dev extra.
