# go-gin best practices (planner reference)

## Project structure

- `cmd/server/main.go` creates the router and starts the HTTP server.
- `internal/http/router.go` owns route registration.
- One file per resource handler under `internal/http/`.
- Keep domain logic out of handlers when it grows beyond a tiny first draft.

## API design

- Use `gin.New()` plus explicit middleware instead of hidden globals.
- Return JSON with `c.JSON(status, payload)`.
- Keep handler function names action-oriented: `ListUnits`, `CreateUnit`.
- Validate request bodies before mutation and return `400` with an error object.

## Testing

- Use `httptest.NewRecorder()` and `http.NewRequest()` for handler tests.
- Keep tests under the same package when they inspect unexported helpers.
- Every route task should add or update a `go test ./...` passing test.

## Output the planner SHOULD produce for this stack

- Tasks order: router setup -> resource model -> handlers -> tests.
- Each task touches ONE file.
- `test_command` = `go test ./...`
- `lint_command` = `go vet ./...`
