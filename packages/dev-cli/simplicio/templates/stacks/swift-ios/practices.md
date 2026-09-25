# swift-ios best practices

## Project structure
- Keep SwiftUI views small and composable.
- Move state management into observable models as behavior grows.
- Keep platform integrations behind services.

## UI design
- Make the first screen functional and accessible.
- Use semantic SwiftUI controls.
- Keep preview data deterministic.

## Testing
- Unit-test view models and formatters.
- Add UI tests for core flows once navigation exists.
- Keep Xcode schemes deterministic.

## Dependencies discipline
- Prefer SwiftUI and Foundation before third-party packages.
- Keep async work explicit with structured concurrency.
