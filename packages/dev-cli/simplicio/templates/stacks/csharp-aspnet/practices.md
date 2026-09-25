# csharp-aspnet best practices

## Project structure
- Keep the API in `src/App.Api`.
- Keep tests in `tests/App.Tests`.
- Move endpoints into extension methods once `Program.cs` grows.

## API design
- Use typed records for request and response contracts.
- Return `Results.Ok`, `Results.Created`, and explicit error results.
- Keep dependency injection registrations close to startup.

## Testing
- Unit-test pure services separately from HTTP integration tests.
- Use xUnit for the initial test harness.
- Keep `dotnet test` as the primary gate.

## Dependencies discipline
- Use the shared ASP.NET Core framework before adding packages.
- Avoid reflection-heavy libraries in the initial scaffold.
