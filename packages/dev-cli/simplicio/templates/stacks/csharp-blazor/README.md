# csharp-blazor

C# 12 + Blazor Server scaffold for interactive .NET web UIs.

## When to use this stack

- .NET team wants server-rendered interactive UI
- App benefits from C# across backend and frontend logic
- Initial scope is internal dashboards or operational tools

## Layout produced

```
<project_name>/
|-- src/App.Web/App.Web.csproj
|-- src/App.Web/Program.cs
|-- src/App.Web/Components/App.razor
`-- README.md
```

## Verify loop

- `install`: `dotnet restore`
- `test`: `dotnet test`
- `lint`: `dotnet format --verify-no-changes`
