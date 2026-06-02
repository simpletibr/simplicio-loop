# Official LLM Usage Policy — Simplicio Ecosystem

**Status:** Official default (2026-06-02)

## Core Principle

- **Planning** (task decomposition, architecture decisions, high-level reasoning) → best available model, with remote models allowed as fallback
- **Execution** (writing code, applying changes, following a plan) → fast, deterministic local model with strong contract + mapper context

## Default Configuration

### Execution (Local)
- Primary local executor: **`openbmb/minicpm5:latest`** via `llama.cpp` /
  `llama-cpp-python`
- Default GGUF: **`MiniCPM5-1B-Q4_K_M.gguf`** from
  `openbmb/MiniCPM5-1B-GGUF`
- Safe local limits: context defaults to `2048` and is clamped to `4096`;
  threads default to/cap at `4`; generation defaults to `512` tokens and is
  capped at `2048`; batch defaults to `128`, micro-batch to `32`, GPU layers to
  `0`, `mmap` stays enabled, and `mlock` stays disabled.

The local default must not require Ollama or any HTTP service. Remote or
OpenAI-compatible endpoints remain explicit opt-ins via `SIMPLICIO_MODEL`,
`SIMPLICIO_BASE_URL`, and credentials.

## Project-Specific Rules

### simplicio-code (mandatory)
- On project bootstrap / SessionStart / first run in a new workspace:
  - The system **must** verify that `MiniCPM5-1B-Q4_K_M.gguf` is present and
    has a valid `GGUF` header.
  - If it is missing, it **must** download/prepare it before allowing local
    agent execution.
- This is a hard requirement for the SimplicioCode product.

### simplicio-dev-cli and simplicio-sprint (recommended)
- The above `openbmb/minicpm5:latest` MiniCPM5 Q4_K_M GGUF setup is the
  **recommended** configuration for local development.
- `simplicio doctor` validates this setup at runtime.

## Rationale

From extensive benchmarking (see `simplicio-dev-cli` quant curves and live gates):
- Even the best 1.5B model struggles with complex structured output on its own.
- When combined with rich mapper precedent + strict 6-layer contract + verification loop, the small high-quant model becomes predictable enough for execution.
- Remote models remain available as explicit fallbacks when a task needs more reasoning headroom.

## How to Configure

```bash
# Execution (local llama.cpp default)
unset SIMPLICIO_MODEL SIMPLICIO_BASE_URL SIMPLICIO_API_KEY
simplicio doctor --install

# Explicit route:
export SIMPLICIO_MODEL=openbmb/minicpm5:latest
# Backing weights when an explicit GGUF route is needed:
export SIMPLICIO_MODEL=local-llama/openbmb/MiniCPM5-1B-GGUF::MiniCPM5-1B-Q4_K_M.gguf
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

## Native Packaged Runtime Direction

The goal is not to rewrite Simplicio in C++ or Rust. The practical direction is
to package the existing Python implementation as a faster, reproducible native
runtime:

- a single launcher/binary that bootstraps the pinned Python package, extras,
  `llama.cpp` bindings, GGUF path, cache, and mapper state;
- optional Rust/C++ hot-path helpers for process spawning, file locks, task
  queues, diff/apply operations, and local-agent scheduling;
- configurable local worker pools, so a `20 agents` request can be accepted by
  the interface while the runtime governs safe concurrency for RAM/CPU.

This keeps the current Python feature velocity while making the mechanical
execution path feel like a program instead of a pile of setup commands.
