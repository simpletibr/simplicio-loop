# swift-vapor best practices

## Project structure
- Keep route registration in small functions.
- Move domain logic out of route closures.
- Keep configuration in environment variables.

## API design
- Return `Content` structs for JSON responses.
- Use Vapor validation before touching domain services.
- Keep async route handlers explicit.

## Testing
- Use XCTest for pure functions and application route tests.
- Keep app boot small for fast tests.
- Run SwiftPM tests before release.

## Dependencies discipline
- Add Fluent only when persistence is part of the goal.
- Keep middleware deliberate and ordered.
