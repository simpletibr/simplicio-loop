# elixir-phoenix best practices

## Project structure
- Keep supervision under the application module.
- Keep web routing in `lib/app_web/router.ex`.
- Put contexts in `lib/app/` once domain boundaries appear.

## API design
- Return explicit JSON maps for API endpoints.
- Use contexts for data and business logic.
- Keep controllers thin.

## Testing
- Use ExUnit for controllers and contexts.
- Keep ConnCase-style helpers once the router grows.
- Run formatter checks before committing.

## Dependencies discipline
- Add OTP processes deliberately and supervise them.
- Keep LiveView dependencies only when UI needs them.
