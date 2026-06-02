# Python Package Interdependence

Status: 2026-06-02

## Current Graph

```text
simplicio-prompt 1.14.0
simplicio-mapper 0.8.0
  ^          ^
  |          |
simplicio-cli 0.5.19
  ^
  |
simplicio-sprint 1.2.13
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

- Primary: `openbmb/minicpm5:latest` via `llama.cpp` / `llama-cpp-python`.
- Default GGUF: `MiniCPM5-1B-Q4_K_M.gguf` from `openbmb/MiniCPM5-1B-GGUF`.
- Ollama is no longer part of the local default path; it remains an explicit
  OpenAI-compatible provider option only when configured by the user.
