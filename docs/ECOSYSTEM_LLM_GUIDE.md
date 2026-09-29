# Simplicio Ecosystem — LLM orientation guide (canonical)

**Audience:** Claude, Codex, Cursor, VS Code, Gemini, Grok, Kiro, OpenCode, Orca (opt-in), Hermes, OpenClaw, Aider, Antigravity, and any coding agent.

**Read this first** every session when working on Simplicio product delivery. The single agent-instruction file (`AGENTS.md`, plus adapter READMEs) points here for the full map.

**There is no Runtime/MCP backend in this stack.** Every project below is standalone;
`simplicio-loop` is the entrypoint and activates directly.

---

## 1. What each project is

| Project | Role (one line) | Install surface | Works alone? |
|---------|-----------------|-----------------|--------------|
| **simplicio-loop** | Orchestrator core + hardened Ralph loop — the entrypoint | `pip install simplicio-loop` + skills/hooks | **Yes** |
| **simplicio-mapper** | Read-only repo observer / map / handoff | `simplicio-mapper` CLI (built into the `simplicio-loop` wheel) | **Yes** |
| **simplicio-dev-cli** | Focused plan compiler + deterministic edits | `simplicio-dev-cli` / `simplicio-py` (built into the `simplicio-loop` wheel) | **Yes** |

**Law (bound operators, ADR 0009/0010):**

1. `simplicio-loop` activates directly via `/simplicio-loop <body of work>` — no external
   activation decision, no Runtime.
2. `mapper` + `dev-cli` are the **required** bound operators (survey / mutate) and the
   whole operator stack.
3. Every loop run emits **`simplicio.execution-report/v1`**: per task/issue + consolidated
   metrics (speed, latency, CPU/RAM when MEASURED, tokens in/out). **Never invent numbers.**

---

## 2. Mental model

```text
  Host LLM (Claude / Cursor / Codex / …)
       │ thinks, plans, selects tools
       ▼
  simplicio-loop protocol (journal / anchor / backlog / hooks)
       │ turbo: survey → plan → apply
       ├── simplicio-mapper   (required, standalone)
       └── simplicio-dev-cli  (required, standalone)
```

---

## 3. Step-by-step — first-time install

```bash
pip install -U simplicio-loop   # one wheel: also provides simplicio-mapper and simplicio-dev-cli
```

Mapper and dev-cli are built into the `simplicio-loop` wheel; there are no separate PyPI
packages to install. Update later with `simplicio-loop update` (`--check` only reports).

Or as a marketplace plugin:

```
/plugin marketplace add wesleysimplicio/simplicio-loop
/plugin install simplicio-loop@simplicio
```

### Prove 100% operational (smoke)

```bash
simplicio-loop --version
simplicio-loop preflight --strict --json
simplicio-mapper --help
simplicio-dev-cli --help
```

Expected: preflight green, or explicit degraded labels — never a silent fake OK.

---

## 4. Step-by-step — every non-trivial task

1. **Run turbo:** `simplicio-loop turbo --repo <path> --task "<task>" [--task "<task 2>" ...] [--verify "<tests>"]`.
   Mapper reads the repo once, the model returns the plan, `simplicio-dev-cli` applies it. Name every
   file to change in the task text. It needs `OPENROUTER_API_KEY`; without it the command prints
   `status: blocked` (`turbo_provider_key_missing`) and you stop: no plans and no edits by hand.
2. **Read its JSON:** `status` (ok/failed/blocked), `applied`, `failed`, `model_calls`,
   `cache_hit_pct`, `cost_usd`, `verify`. On `failed`, re-run once with a sharper `--task`.
3. **Record metrics per task/issue:**
   ```text
   python -m simplicio_loop.execution_report record-task --task-id t1 --issue 42 --title "…" \
     --outcome COMPLETE --wall-ms N --tokens-in N --tokens-out N --operator mapper --operator dev-cli --json
   ```
4. **Validate:** the task's own focused gate; `python3 scripts/check.py` before publishing.
5. **Evidence-gated exit:** MEASURED only with receipts; no theater closes.

---

## 5. Commands cheat sheet

| Intent | Command |
|--------|---------|
| Preflight (blocking) | `simplicio-loop preflight --strict --json` |
| Orient + route | `simplicio-loop orient --task "…" --json` |
| Run a task (default) | `simplicio-loop turbo --repo . --task "…" --verify "<tests>"` |
| Governed run from a tasks.md | `simplicio-loop prepare --task tasks.md` → `wave` → `verify` |
| Drain a queue | `python3 scripts/arm_drain_prism.py --repo . --slots 0 --batch-size N --json` |
| Start metrics report | `python -m simplicio_loop.execution_report start --json` |
| Per-task metrics | `python -m simplicio_loop.execution_report record-task …` |
| Consolidated | `python -m simplicio_loop.execution_report consolidate --json` |

---

## 6. Host notes (all hosts)

| Host | How loop ticks | Hand-edit |
|------|----------------|-----------|
| Claude Code | Stop + PreToolUse hooks | `action_gate` under STRICT |
| Cursor | stop + afterAgentResponse | hooks + rules |
| Codex / Grok / VS Code / Kiro / Hermes / OpenCode | self-paced | STRICT env + this guide |
| Orca | **opt-in only** (`CLIENT_INTEGRATIONS`) | same |
| Gemini / Aider / Antigravity | self-paced / conventions file | STRICT |

Self-paced: re-read `.simplicio-loop/orchestrator/loop/scratchpad.md` each turn.

---

## 7. Related ADRs

- Loop: `docs/adr/0009-loop-inside-runtime-operators-standalone.md`
- Loop: `docs/adr/0010-execution-metrics-report-standard.md`
- Rejected Runtime routing design (kept for history): `docs/adr/0011-runtime-operator-routing.md`

---

## 8. Honesty

- Facts are `MEASURED|` only with receipts; else `UNVERIFIED|`.
- Tokens/CPU/RAM: never fabricate; use `null` + `unavailable_reasons`.
