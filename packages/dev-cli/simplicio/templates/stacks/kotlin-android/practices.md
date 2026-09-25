# kotlin-android best practices

## Project structure
- Keep UI in composable functions and state in view models.
- Keep platform integrations behind small adapters.
- Split features once navigation grows.

## UI design
- Use Material components and accessibility labels.
- Keep previews deterministic.
- Avoid business logic inside composables.

## Testing
- Unit-test view models and pure state reducers.
- Add Compose UI tests for critical flows.
- Keep Gradle lint and test tasks green.

## Dependencies discipline
- Use AndroidX defaults before adding large architecture libraries.
- Keep coroutine scopes lifecycle-aware.
