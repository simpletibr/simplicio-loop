# kotlin-ktor best practices

## Project structure
- Keep routing modules small and grouped by resource.
- Put serialization setup in one application module.
- Keep business logic outside route lambdas.

## API design
- Return typed DTOs once response shape grows.
- Use Ktor plugins for content negotiation and status pages.
- Keep route validation explicit.

## Testing
- Use `testApplication` for HTTP route tests.
- Unit-test pure services without spinning up Ktor.
- Keep Gradle tests fast and deterministic.

## Dependencies discipline
- Add plugins intentionally and configure them centrally.
- Avoid mixing Spring and Ktor patterns.
