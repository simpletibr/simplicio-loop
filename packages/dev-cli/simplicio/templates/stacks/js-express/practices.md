# js-express best practices

## Project structure
- Export the Express app from `src/app.js`; start the listener in `src/server.js`.
- Keep routers under `src/routes/` once a second resource appears.
- Keep request validation close to route boundaries.

## API design
- Always return JSON from API routes.
- Use explicit status codes and centralized error middleware.
- Keep route handlers small and move domain logic to plain modules.

## Testing
- Use `node --test` for fast smoke checks.
- Use Supertest for HTTP behavior once dependencies are installed.
- Keep health and route tests deterministic and independent.

## Dependencies discipline
- Avoid global mutable process state in tests.
- Use structured middleware instead of ad hoc request parsing.
