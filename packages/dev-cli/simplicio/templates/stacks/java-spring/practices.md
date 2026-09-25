# java-spring best practices

## Project structure
- Keep application bootstrap in `Application`.
- Put controllers, services, and repositories in separate packages as they grow.
- Prefer constructor injection over field injection.

## API design
- Use typed request and response records for payloads.
- Return explicit status codes with `ResponseEntity` when behavior branches.
- Keep validation at controller boundaries.

## Testing
- Unit-test services without Spring context when possible.
- Use `@SpringBootTest` sparingly.
- Keep `./gradlew test` green before expanding the template.

## Dependencies discipline
- Add starters only when the project uses that subsystem.
- Avoid mixing multiple web frameworks in one service.
