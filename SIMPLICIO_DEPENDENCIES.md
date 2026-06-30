# Simplicio Ecosystem Dependencies

```
simplicio-runtime (Rust) — core runtime
  ↓ CLI calls
simplicio-dev-cli (Python) — CLI adapter
  ↓ pip dependency
simplicio-mapper (Python) — project mapper
  ↓ used by loop hooks
simplicio-loop (Python/Plugin) — loop orchestrator
```

## Dependency Graph

| Package | Lang | Role | Depends On |
|---|---|---|---|
| **simplicio-runtime** | Rust | Core runtime (binary `simplicio`) | — |
| **simplicio-dev-cli** | Python | CLI adapter, discovers & routes to Rust binary | simplicio-mapper, simplicio-prompt |
| **simplicio-mapper** | Python | Project structure mapper | — |
| **simplicio-prompt** | Python | Prompt library / skill templates | — |
| **simplicio-loop** | Python | Loop orchestrator (verify-loop) | simplicio-mapper |

## Runtime Bridge

The `simplicio/runtime_bridge.py` module in simplicio-dev-cli handles:

- **`discover_simplicio()`** — locates the `simplicio` Rust binary on `$PATH`
- **`call_simplicio(args)`** — subprocess delegation to the Rust binary
- **`simplicio_available()`** — boolean check for Rust binary presence
- **`use_native_implementation()`** — decision logic (Rust vs Python)

## Routing Rules

| Command | Default | `--native` | `--python` |
|---|---|---|---|
| `gate` | Rust if available, else Python | Force Rust | Force Python |
| `nest` | Rust if available, else Python | Force Rust | Force Python |
| `score-skill` | Rust if available, else Python | Force Rust | Force Python |
| Other commands | Python only | Python only | Python only |
