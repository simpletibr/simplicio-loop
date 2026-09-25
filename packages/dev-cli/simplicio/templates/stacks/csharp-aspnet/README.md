# csharp-aspnet

C# 12 + ASP.NET Core 8 minimal API scaffold for typed JSON services.

## When to use this stack

- .NET team wants a small HTTP API
- Minimal API is sufficient before controllers are needed
- Strong typing and SDK tooling are desired from the start

## Layout produced

```
<project_name>/
|-- src/App.Api/App.Api.csproj
|-- src/App.Api/Program.cs
|-- tests/App.Tests/App.Tests.csproj
`-- README.md
```

## Verify loop

- `install`: `dotnet restore`
- `test`: `dotnet test`
- `lint`: `dotnet format --verify-no-changes`
