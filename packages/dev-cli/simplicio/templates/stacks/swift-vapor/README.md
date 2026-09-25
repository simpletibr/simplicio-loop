# swift-vapor

Swift 5 + Vapor 4 scaffold for server-side Swift APIs.

## When to use this stack

- Swift team wants backend API services
- Shared Swift models with app clients are useful
- Vapor routing and middleware are desired

## Layout produced

```
<project_name>/
|-- Package.swift
|-- Sources/App/main.swift
|-- Tests/AppTests/HealthTests.swift
`-- README.md
```

## Verify loop

- `install`: `swift package resolve`
- `test`: `swift test`
- `lint`: `swift package diagnose-api-breaking-changes`
