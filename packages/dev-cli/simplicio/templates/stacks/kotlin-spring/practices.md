# kotlin-spring best practices

## Project structure
- Keep controllers, services, and configuration in separate packages.
- Use data classes for request and response contracts.
- Prefer constructor injection and immutable dependencies.

## API design
- Keep controllers thin.
- Use validation annotations at the request boundary.
- Return explicit response types for public endpoints.

## Testing
- Unit-test pure services without Spring context.
- Use Spring tests only for integration behavior.
- Keep Gradle tasks deterministic in CI.

## Dependencies discipline
- Keep coroutine usage explicit.
- Add Spring starters only when the feature is used.
