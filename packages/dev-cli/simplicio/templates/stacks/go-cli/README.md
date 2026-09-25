# go-cli

Go + Cobra + Viper scaffold for compiled command-line tools.

## When to use this stack

- Cross-platform CLI with subcommands
- Static binary distribution is useful
- Configuration should come from flags, env, and config files

## Layout produced

```
<project_name>/
|-- cmd/root.go
|-- main.go
|-- go.mod
`-- README.md
```

## Verify loop

- `install`: `go mod download`
- `test`: `go test ./...`
- `lint`: `go vet ./...`
