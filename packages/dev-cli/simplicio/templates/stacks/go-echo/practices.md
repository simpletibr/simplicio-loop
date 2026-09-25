# go-echo best practices

## Project structure
- Keep router construction in `internal/http`.
- Keep `cmd/server/main.go` limited to startup and configuration.
- Put persistence and domain logic in separate internal packages as they appear.

## API design
- Return typed response structs or maps with stable keys.
- Use middleware explicitly and keep side effects visible.
- Keep request validation at the handler boundary.

## Testing
- Use `httptest` against the Echo router.
- Keep tests package-local to handlers while the API is small.
- Run `go test ./...` and `go vet ./...`.

## Dependencies discipline
- Avoid adding ORMs until persistence exists.
- Keep handler dependencies injectable.
