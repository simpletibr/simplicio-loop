# dart-flutter best practices

## Project structure
- Keep widgets small and split feature folders as navigation grows.
- Keep state management explicit and testable.
- Put API clients outside widget trees.

## UI design
- Use Material components unless platform design says otherwise.
- Keep text readable across small screens.
- Avoid business logic inside `build` methods.

## Testing
- Use widget tests for visible behavior.
- Unit-test state and formatting separately.
- Run `flutter analyze` before release.

## Dependencies discipline
- Prefer Flutter SDK primitives before adding packages.
- Keep platform channels narrow and documented.
