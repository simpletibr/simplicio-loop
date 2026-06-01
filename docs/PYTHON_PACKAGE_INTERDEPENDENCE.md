# Python Package Interdependence

Status: 2026-06-01

## Current Graph

```text
simplicio-prompt 1.13.2
simplicio-mapper 0.7.2
  ^          ^
  |          |
simplicio-cli 0.5.15
  ^
  |
simplicio-sprint 1.2.10
```

## Rules

- `simplicio-prompt` stays dependency-free at runtime.
- `simplicio-mapper` stays independent from the executor and sprint packages.
- `simplicio-cli` may depend on `simplicio-mapper` and `simplicio-prompt`.
- `simplicio-sprint` may depend on `simplicio-cli`, `simplicio-mapper`, and
  `simplicio-prompt`.
- No package may depend on `simplicio-sprint`; this keeps the orchestration
  layer at the edge and prevents cycles.

## Local LLM Standard

- Primary: `openbmb/minicpm5:latest` via local Ollama.
- Fallback: `Qwen_Qwen3.5-2B-Q6_K.gguf` via `local-llama/default`.
