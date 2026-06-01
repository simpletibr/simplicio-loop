# Official LLM Usage Policy — Simplicio Ecosystem

**Status:** Official default (2026-06-01)

## Core Principle

- **Planning** (task decomposition, architecture decisions, high-level reasoning) → best available model, with remote models allowed as fallback
- **Execution** (writing code, applying changes, following a plan) → fast, deterministic local model with strong contract + mapper context

## Default Configuration

### Execution (Local)
- Primary local executor: **`openbmb/minicpm5:latest`** via local Ollama
- Fallback local executor: **`Qwen_Qwen3.5-2B-Q6_K.gguf`** from `bartowski/Qwen_Qwen3.5-2B-GGUF`

The GGUF fallback should be used via llama.cpp / llama-cpp-python only when
Ollama is unavailable or the MiniCPM5 call fails.

## Project-Specific Rules

### simplicio-code (mandatory)
- On project bootstrap / SessionStart / first run in a new workspace:
  - The system **must** verify that `openbmb/minicpm5:latest` is available in local Ollama.
  - The system **must** verify that `Qwen_Qwen3.5-2B-Q6_K.gguf` is present as the fallback file.
  - If either is missing, it **must** install it before allowing agent execution.
- This is a hard requirement for the SimplicioCode product.

### simplicio-dev-cli and simplicio-sprint (recommended)
- The above split (`openbmb/minicpm5:latest` primary + Qwen3.5 Q6_K GGUF fallback) is the **recommended** configuration for local development.
- Not enforced at runtime, but all examples, benchmarks, and documentation use this setup.

## Rationale

From extensive benchmarking (see `simplicio-dev-cli` quant curves and live gates):
- Even the best 1.5B model struggles with complex structured output on its own.
- When combined with rich mapper precedent + strict 6-layer contract + verification loop, the small high-quant model becomes predictable enough for execution.
- Remote models remain available as explicit fallbacks when a task needs more reasoning headroom.

## How to Configure

```bash
# Execution (local Ollama primary)
export SIMPLICIO_MODEL=openbmb/minicpm5:latest
export SIMPLICIO_BASE_URL=http://localhost:11434/v1
export SIMPLICIO_API_KEY=ollama

# fallback explicit route:
export SIMPLICIO_MODEL=local-llama/bartowski/Qwen_Qwen3.5-2B-GGUF::Qwen_Qwen3.5-2B-Q6_K.gguf
```

In SimplicioCode the equivalent is done via the Simplicio1 tier system + explicit GGUF routing for the executor role.


## Default Usage Mode for simplicio-dev-cli

**Official default stack (recommended for all users):**

```bash
simplicio-dev-cli + simplicio-prompt + agents
```

- `simplicio-dev-cli`: core 6-layer contract + verification loop for task execution.
- `simplicio-prompt`: subagent runtime + fan-out + behavior consensus for complex or parallel work.
- `agents` / `.skills/` + `.agents/`: reusable skills and custom sub-agents from the Simplicio starter.

This combination is the **recommended and documented default** when using `simplicio-dev-cli`. All new examples, benchmarks, and onboarding materials assume this full stack.

When starting a new project with the Simplicio starter, the bootstrap configures the environment to use this trio by default.
