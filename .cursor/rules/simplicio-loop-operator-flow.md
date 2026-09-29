# Simplicio loop — mandatory operator flow (all hosts)

**Applies to:** Claude Code, Codex, Grok, Cursor, VS Code / Copilot, Antigravity,
Kiro, Hermes / Simplicio Agent, OpenCode, Gemini, Aider, and any host that loads
Simplicio skills. **Orca is not default** — enable only when the client requests it
(`docs/CLIENT_INTEGRATIONS.md`).

Installers copy this file into each host's always-on surface via
`python3 scripts/host_rule_sync.py --global`.

## MUST

0. **`/simplicio-loop` is the entrypoint. There is no Runtime/MCP backend in this stack.**
   - Start the loop directly: `/simplicio-loop <body of work>`.
   - **Bound operators (required):** `simplicio-mapper` (survey) + `simplicio-dev-cli`
     (mutate). They are the whole operator stack.
   - **Metrics mandatory:** every run writes `simplicio.execution-report/v1`
     (per task/issue + consolidated: speed, latency, CPU/RAM when MEASURED, tokens in/out).
     CLI: `python -m simplicio_loop.execution_report …`. Never invent numbers.
   - ADR: loop `docs/adr/0009`, `0010`.

1. **Economy-parallel env** before autonomous work (fastest tokens + parallel):
   ```bash
   simplicio-loop economy apply --json   # or: source ~/.simplicio-loop/economy-parallel-env.sh
   ```
   - `SIMPLICIO_LOOP=1` · `SIMPLICIO_LOOP_STRICT=1`
   - `SIMPLICIO_EXECUTION_PROFILE=standalone` (the only execution profile)
   - `SIMPLICIO_LOOP_AUTO_FAN_OUT=1` (parallel worktrees on `batch`)
   - `SIMPLICIO_LOOP_OPERATOR_WORKERS` / `SIMPLICIO_PRISM_SLOTS` / `SIMPLICIO_ASYNC_IO_MAX_CONCURRENCY` (CPU-bounded)
   - `SIMPLICIO_OPERATOR_ALWAYS_LATEST=1`
   - Safety: mutation authority + planning receipt + forbid hand-edit
   - Opt out of economy defaults: `SIMPLICIO_ECONOMY_PARALLEL=0`

2. **Preflight (blocking):** `simplicio-loop preflight --strict --json`  
   Core operators = **mapper + dev-cli**. Terminal-first: prefer real
   shell/CLI commands (`simplicio-orient`) over host bulk Read/Grep/cat.

3. **Survey:** `simplicio-mapper` (scan / inspect / handoff) — not ad-hoc full-tree LLM walks.

4. **Hot path:** `simplicio-loop "<task>" [--verify "<tests>"]` (short for `simplicio-loop turbo --repo .
   --task "<task>"`). Mapper surveys and the command prints a `needs_plan` request; no key, no provider.
   You are the model: write the JSON plan to `plan_path`, run the printed `apply` command (Dev CLI
   applies it and runs `--verify`), and on `failed` fix the plan once from the reported reason. Queue
   goals: the same two commands per item, in order.

5. **Mutate:** through `simplicio-loop turbo --apply` under STRICT (Dev CLI makes every edit).  
   Host Write / Edit / StrReplace / ApplyPatch are **forbidden** as the primary mutation path
   when STRICT is on (`hooks/action_gate.py` PreToolUse on Claude/Cursor; instruction law on
   self-paced hosts).

6. **GitHub** = default coordination SoT for Issues/PRs when the remote is GitHub.

7. **Drain:** claim → real ACs → PR to main with `Closes #N` → merge. Prefer Prism waves
   (`python3 scripts/arm_drain_prism.py --repo . --slots 0 --batch-size N --json`;
   `slots 0` = machine physical max; batch default/min 10, larger explicit OK).

8. **Evidence-gated exit:** MEASURED tags; no theater AC stubs; no false completion.

9. **Parallelism** only with lease/claim + isolation + reducer — no double-writers without coordination.
   1–3 tasks = direct parallelism; >3 = Prism. Layers: Prism · operator workers ·
   asyncio I/O · **writes serialized**. See `docs/LLM_MAX_SPEED_ORIENTATION.md`.

10. **Integrations** (Orca, Linear, …) only if the **client requested** them
    (`SIMPLICIO_LOOP_CLIENT_INTEGRATIONS` or `.simplicio-loop/client-integrations.json`).

11. **Max-speed orientation (always):** act > narrate; Mapper→dev-cli hot path;
    smallest gate that proves the AC; no full-repo residual thrash; no 3-reviewer panels on
    metadata-only diffs; end each message with `DONE | NEXT | BLOCKED`.
    Canonical: `docs/LLM_MAX_SPEED_ORIENTATION.md` (re-feed block in SKILL.md).

## MUST NOT

- Mass-close issues with hardcoded `status=implemented` stubs
- Invent `open=0` without live issue re-query
- Reinstall operators every turn (TTL pin + `operator_check maybe-upgrade`)
- Hand-edit under STRICT to "go faster"
- Auto-enable Orca or other host side-channels
- Force physical Prism thrash above machine auto (`--slots 0` / economy recommend)

## Loop drive by host

| Host | Drive | Hand-edit gate |
|------|--------|----------------|
| Claude Code | Stop + PreToolUse | `action_gate` under STRICT |
| Cursor | stop + afterAgentResponse | hooks + this rule |
| Codex / Grok / VS Code / Antigravity / Kiro / Hermes | **self-paced** | this rule + env STRICT as hard law |
| Simplicio Agent | native tick | native + this rule |

Self-paced: re-read `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn;
triage → decide → operate → verify → journal.

## Invoke

```text
/simplicio-loop <body of work>
python3 scripts/arm_drain_prism.py --repo . --slots 4 --json
```

Protocol: `.claude/skills/simplicio-loop/SKILL.md`  
Contract: `docs/MULTI_LLM_CONTRACT.md`

<!-- simplicio-global-llm-architecture-rules:start -->
## Regras arquiteturais globais (obrigatórias)

- Delete diretamente o obsoleto; não preserve compatibilidade retroativa, não crie
  migrações e não deixe fallbacks.
- Escolha a solução mais simples para a necessidade atual, sem abstrações
  preventivas ou configuração desnecessária.
- Faça o mínimo end-to-end funcionar primeiro e evolua por camadas longas, sem
  desmontar o que funciona por complexidade inacabada.
- Mantenha modularidade e separação de responsabilidades.
- Prefira bibliotecas maduras e mantidas; reescreva do zero apenas com motivo
  técnico explícito.
- Inspecione dependências existentes antes de adicionar pacotes ou reimplementar.
- Tome decisões para o longo prazo; não deixe soluções temporárias.
- Reutilize padrões validados por produtos maduros; não reinvente a roda.

<!-- simplicio-global-llm-architecture-rules:end -->

