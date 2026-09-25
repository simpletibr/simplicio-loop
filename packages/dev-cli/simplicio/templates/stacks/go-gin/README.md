# go-gin

Go 1.22 + Gin scaffold for small REST APIs where fast startup, simple
deployment, and a single static binary matter.

## When to use this stack

- Backend-only JSON API
- Team wants compile-time checks and low runtime overhead
- Service should ship as a container or single binary
- CRUD or webhook service with straightforward HTTP routing

## When NOT to use this stack

- SSR web application - use `ts-nextjs`
- Laravel ecosystem or PHP team conventions - use `php-laravel`
- Heavy async Python ecosystem integrations - use `py-fastapi`

## Layout produced

```
<project_name>/
+-- cmd/server/main.go          # entrypoint
+-- internal/http/              # Gin router and handlers
+-- go.mod
+-- README.md
```

## Verify-loop

- `install`: `go mod tidy`
- `test`:    `go test ./...`
- `lint`:    `go vet ./...`
