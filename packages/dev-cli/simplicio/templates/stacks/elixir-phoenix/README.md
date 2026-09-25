# elixir-phoenix

Elixir 1.17 + Phoenix 1.7 scaffold for concurrent web apps and APIs.

## When to use this stack

- Real-time or concurrent web workload
- Team wants Phoenix routing and supervision from the start
- LiveView may become part of the UI surface

## Layout produced

```
<project_name>/
|-- mix.exs
|-- lib/app_web/router.ex
|-- lib/app_web/controllers/health_controller.ex
`-- README.md
```

## Verify loop

- `install`: `mix deps.get`
- `test`: `mix test`
- `lint`: `mix format --check-formatted`
