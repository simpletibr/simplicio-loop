# ts-remix best practices

## Project structure
- Keep loader/action code inside route modules until reuse is clear.
- Use resource routes for JSON-only endpoints.
- Keep shared UI under `app/components/`.

## UI and data
- Validate form input in actions and return typed errors.
- Prefer server loaders over client-side fetches for initial data.
- Keep route boundaries narrow and predictable.

## Testing
- Unit-test pure loader/action helpers.
- Use Vitest for route-adjacent functions and build for integration confidence.
- Keep `npm run build` as the final SSR compatibility check.

## Dependencies discipline
- Do not add state libraries before exhausting route data and forms.
- Keep direct browser APIs guarded when code can run on the server.
