# php-symfony best practices

## Project structure
- Keep HTTP controllers under `src/Controller`.
- Put domain services under `src/Service` once behavior grows.
- Keep configuration declarative and environment-specific values outside code.

## API design
- Use route attributes for small APIs.
- Return `JsonResponse` for API endpoints.
- Validate request DTOs before calling services.

## Testing
- Use PHPUnit for controller and service behavior.
- Keep framework boot cost low by testing pure services directly.
- Run syntax checks for generated PHP before the full suite.

## Dependencies discipline
- Add bundles only when the framework integration is needed.
- Keep dev-only tools in `require-dev`.
