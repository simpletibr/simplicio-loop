# csharp-blazor best practices

## Project structure
- Keep reusable UI in `Components/`.
- Keep page components under `Components/Pages/`.
- Move business logic to services registered through dependency injection.

## UI design
- Keep first screen functional and task-focused.
- Use form components with validation once inputs appear.
- Avoid long-running work on the UI thread.

## Testing
- Keep pure services unit-tested.
- Add component tests once UI behavior grows.
- Keep `dotnet test` as the baseline gate.

## Dependencies discipline
- Prefer built-in Blazor components until a design system is chosen.
- Keep JavaScript interop narrow and explicit.
