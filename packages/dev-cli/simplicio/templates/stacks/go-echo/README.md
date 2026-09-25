# go-echo

Go + Echo scaffold for compact JSON APIs.

## When to use this stack

- HTTP API with a small dependency surface
- Team wants Go's standard deployment shape
- Middleware, validation, and routing should stay explicit

## Layout produced

```
<project_name>/
|-- cmd/server/main.go
|-- internal/http/router.go
|-- internal/http/router_test.go
|-- go.mod
`-- README.md
```

## Verify loop

- `install`: `go mod download`
- `test`: `go test ./...`
- `lint`: `go vet ./...`
