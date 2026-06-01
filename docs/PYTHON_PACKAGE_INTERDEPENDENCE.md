# Python Package Interdependence

Status: 2026-06-01

## Current Graph

```text
simplicio-prompt 1.13.3
simplicio-mapper 0.7.3
  ^          ^
  |          |
simplicio-cli 0.5.17
  ^
  |
simplicio-sprint 1.2.11
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

- Primary: `local-llama/default` via `llama.cpp` / `llama-cpp-python`.
- Default GGUF: `Qwen_Qwen3.5-2B-Q6_K.gguf`.
- Ollama is no longer part of the local default path; it remains an explicit
  OpenAI-compatible provider option only when configured by the user.
