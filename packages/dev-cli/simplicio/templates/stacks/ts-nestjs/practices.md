# ts-nestjs best practices

## Project structure
- Keep feature modules explicit; each resource gets module, controller, service.
- Use DTO classes for request bodies and response contracts.
- Keep infrastructure adapters behind injectable providers.

## API design
- Controllers should be thin and delegate to services.
- Use pipes for validation and filters for error mapping.
- Prefer Fastify-compatible APIs when touching response objects directly.

## Testing
- Unit-test services without a Nest application when possible.
- Use Nest testing module for controller integration behavior.
- Keep `npm test`, `npm run lint`, and `npm run build` green.

## Dependencies discipline
- Do not mix Nest and raw Express route registration.
- Add persistence libraries only after a storage boundary is planned.
