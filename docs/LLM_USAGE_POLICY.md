# Official LLM Usage Policy — Simplicio Ecosystem

**Status:** Official default (2026-06-01)

## Core Principle

- **Planning** (task decomposition, architecture decisions, high-level reasoning) → best available model, with remote models allowed as fallback
- **Execution** (writing code, applying changes, following a plan) → fast, deterministic local model with strong contract + mapper context

## Default Configuration

### Execution (Local)
- Primary local executor: **Qwen3.5-2B-Q6_K.gguf**
- Fallback local executors: **Qwen2.5-Coder-1.5B-Instruct-Q8_0.gguf**, then **Qwen2.5-Coder-1.5B-Instruct-Q6_K_L.gguf**

These GGUF files should be used via llama.cpp / llama-cpp-python (not the default Ollama tag) when maximum determinism and instruction following on the small-local class is required.

## Project-Specific Rules

### simplicio-code (mandatory)
- On project bootstrap / SessionStart / first run in a new workspace:
  - The system **must** verify that the local Qwen3.5 Q6_K executor is present and keep the legacy Qwen2.5 executor files as fallbacks.
  - If missing, it **must** download them before allowing agent execution.
- This is a hard requirement for the SimplicioCode product.

### simplicio-dev-cli and simplicio-sprint (recommended)
- The above split (Qwen3.5-2B Q6_K for execution + legacy Qwen2.5 fallback files) is the **recommended** configuration for local development.
- Not enforced at runtime, but all examples, benchmarks, and documentation use this setup.

## Rationale

From extensive benchmarking (see `simplicio-dev-cli` quant curves and live gates):
- Even the best 1.5B model struggles with complex structured output on its own.
- When combined with rich mapper precedent + strict 6-layer contract + verification loop, the small high-quant model becomes predictable enough for execution.
- Remote models remain available as explicit fallbacks when a task needs more reasoning headroom.

## How to Configure

```bash
# Execution (local, deterministic)
export SIMPLICIO_MODEL=local-llama/default
# equivalent explicit route:
export SIMPLICIO_MODEL=local-llama/bartowski/Qwen_Qwen3.5-2B-GGUF::Qwen3.5-2B-Q6_K.gguf
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
