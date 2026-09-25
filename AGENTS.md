# AGENTS.md — simplicio-loop

> **Full map + step-by-step:** [docs/ECOSYSTEM_LLM_GUIDE.md](docs/ECOSYSTEM_LLM_GUIDE.md) · ADR [0009](docs/adr/0009-loop-inside-runtime-operators-standalone.md) · [0010](docs/adr/0010-execution-metrics-report-standard.md)  
> **Max-speed LLM orientation (always):** [docs/LLM_MAX_SPEED_ORIENTATION.md](docs/LLM_MAX_SPEED_ORIENTATION.md) — also re-fed every loop turn via `SIMPLICIO-LLM-ORIENTATION` in the loop skill.

## Simplicio Ecosystem Contract (canonical)

This loop is the convergence layer of one Simplicio ecosystem. For every non-trivial task: run `simplicio runtime map --repo . --for-llm markdown`, then `simplicio memory "<task>"`, rank/load relevant skills, execute through the native `simplicio` CLI, validate, and record evidence. MCP is fallback transport only.

## Worker startup and centralized artifacts (mandatory)

Every subagent, worker, and provider session MUST read `AGENTS.md`, `CLAUDE.md`, and every relevant local skill before operating. For Loop work, the baseline skills are `.claude/skills/simplicio-loop/SKILL.md`, `.claude/skills/simplicio-prism/SKILL.md`, and `.claude/skills/simplicio-runtime/SKILL.md`; load additional satellite skills selected by the task before mutation.

The canonical default branch owns one centrally built binary/artifact set. Workers consume that binary read-only; they MUST NOT rebuild binaries or regenerate canonical Mapper/Fast artifacts. Worktrees isolate source edits and receipts only. Every receipt/handoff MUST record repository and revision, binary digest/version, Mapper generation and artifact digest. Missing, stale, incompatible, or mismatched central artifacts fail closed and route to the central rebuild path only; a worker may not repair them locally or fall back to fabricated/uncertified context.


### Full-stack boundaries
`simplicio-mapper` / `simplicio-dev-cli` / `simplicio-fast` observe, plan, and edit — **they work alone** without Runtime. `simplicio-runtime` owns contracts, gates, validation, receipts, **the full loop subsystem** (activation + convergence authority), and **mandatory execution-report metrics** (per task + consolidated). **Runtime alone decides when to activate the loop** (`simplicio loop decide`). This package is the protocol + host-hook implementation under Runtime authority. Coordinators own cognition, not loop activation. See `docs/adr/0009` and `docs/adr/0010`. Providers are workers, never authorities.

Use `simplicio`/`simplicio shell compact` for inspection, `simplicio edit --plan` or governed dev-cli for mutation, preserve `simplicio.io/v1`, run `simplicio contracts smoke --json` and `simplicio validate "<task>" --repo . --json`, and close only with real tests plus `simplicio evidence`. Facts are `MEASURED|` only with receipts; otherwise `UNVERIFIED|`. Savings come only from `simplicio savings report --repo . --json`. Missing dependencies fail closed; never fabricate context, tests, savings or provider output.
This repository ships a runtime-agnostic **super-plugin**: the Universal Looping AI
Orchestrator plus five satellite skills, packaged for 15 runtimes. Any agent runtime that
reads `AGENTS.md` / skill folders can run it.

## What to load

The orchestrator IS the protocol — load it and follow it end-to-end:

```
.claude/skills/simplicio-loop/SKILL.md
```

It is self-contained and uses only standard tools (shell, git, gh, file edit, web), so it
works on any strong LLM. When present, it DELEGATES to its five satellites for deeper,
token-cheaper behavior (it never requires them):

| Skill | Absorbs | Role |
|---|---|---|
| `simplicio-loop` | Ralph Wiggum loop | re-feed the goal until an evidence-gated `<promise>` or a `max_iterations` cap; durable run-journal (attempt memory) + stall detector so it changes strategy instead of oscillating (`scripts/loop_journal.py`); a local **task backlog** (`scripts/task_backlog.py`) freezes a vague goal's multi-item decomposition (per-item ACs, dependency-ordered, genesis-aware) and gates each item's close on the task anchor |
| `simplicio-orient` | rtk + caveman terminal discipline | terminal-first execution, output-reduction catalog, tee-cache, signatures-read |
| `simplicio-review` | thermos | parallel adversarial review on distinct rubrics → deduped verdict |
| `simplicio-compress` | caveman | prose + memory compression, byte-preserving, fail-closed `transform_guard` |
| `simplicio-learn` | continual-learning + teaching | retrospective → durable, deduped lessons in memory |

## Hooks (cross-platform Python, fail-open)

`hooks/` makes the loop + token economy deterministic where the runtime supports hooks:
`loop_stop.py` / `loop_capture.py` (the loop), `orient_clamp.py` (clamp any command's output +
tee-on-failure — works with NO wiring on every runtime), `orient_rewrite.py` (opt-in
auto-clamp). See [`hooks/README.md`](hooks/README.md).

## Runtimes

15 runtimes are documented in [`adapters/MATRIX.md`](adapters/MATRIX.md): Claude Code · Codex ·
VS Code (Copilot) · Cursor · Antigravity · Kiro · OpenCode · Gemini (CLI/Code Assist) · Kimi ·
Qwen (Code/CLI) · DeepSeek · Aider · Simplicio Agent (formerly Hermes) · OpenClaw · Orca. Install
12 of them with `scripts/install.sh <runtime>` (or `install.ps1`); Kimi/Qwen/DeepSeek are not yet
wired into the installer — see their adapter READMEs for manual/best-effort steps. The native
`simplicio-runtime` MCP bind is optional on all 15; its integrations are used only when available
— see [`docs/MCP_SETUP.md`](docs/MCP_SETUP.md).

## Activation

The user invokes it with a target body of work:

```
/simplicio-loop finish all the open issues
/simplicio-loop clear the CI queue
/simplicio-loop drain the Jira board
```

If no argument is given, default to "all open work-items in the default source" and
confirm scope in one line only if ambiguous.

## LLM quick flow

The compact current sequence is canonical in [`llms.txt`](llms.txt): Mapper `--help` →
`scan`/`inspect`/`handoff`, Fast bounded context, Dev CLI governed edit/verify, focused gates,
then live PR re-query. Default is standalone/off; Runtime/MCP is opt-in only.

## Extension points (bind native when available)

The skill defines **50 named extension points** (see the Step 1b table in `SKILL.md`).
For each point, if this runtime exposes a faster native capability, **bind it** —
the step becomes deterministic and near-zero-token. The skill never requires a specific
runtime; the binding lives here in the host, not in the skill.

`simplicio-runtime` (MCP or CLI) is optional on every host. When available it enables native
integrations; when absent, the loop records that those integrations were skipped and continues
with the required `simplicio-mapper` and `simplicio-dev-cli` operators.

## Canonical source per topic (#119 — avoid re-stating the same pitch in N docs)

Each topic below has exactly ONE canonical doc; every other file that touches the topic should
link to it instead of repeating the content. When editing one of these topics, edit the canonical
file and let secondary docs (`GEMINI.md`, `PYPI.md`, `llms.txt`, etc.) stay short pointers.

| Topic | Canonical doc | Secondary docs that point here instead of repeating it |
|---|---|---|
| Elevator pitch / what this repo is | `README.md` | `GEMINI.md`, `llms.txt` (one-line summary + link) |
| Runtime-agnostic contract (extension points, non-negotiables) | `AGENTS.md` (this file) | `CLAUDE.md` (Claude-specific overlay only), `GEMINI.md`, `.windsurf/rules/agents.md`, `.kiro/steering/agents.md` (symlinks) |
| Ecosystem / cross-repo dependencies | `SIMPLICIO_ECOSYSTEM.md` | — |
| Pricing / monetization | `PRICING.md` | — |
| Loop mechanics (protocol, exit gates) | `.claude/skills/simplicio-loop/SKILL.md` + `references/*.md` | `AGENTS.md` § Video evidence links in rather than re-describing |
| PyPI package listing copy | `PYPI.md` (wired as `readme` in `pyproject.toml`) | — (this is itself the PyPI-rendered page, so it necessarily carries its own condensed pitch) |
| LLM quick-orientation index | `llms.txt` | — |
| `scripts/*.py` core vs satellite classification | `docs/SCRIPTS_INVENTORY.md` (#118) | `README.md` § Tests & local checks links in rather than re-listing |

## Video evidence (hyperframes)

The orchestrator can **create demo videos** of a screen/feature on request
(`/simplicio-loop make a demo video of screen X`) and reuse them as proof a change works.
The `video_evidence` extension point binds [hyperframes](https://github.com/heygen-com/hyperframes)
(deterministic HTML→MP4; Node 22+ + FFmpeg, no API keys). Worker: `scripts/video_evidence.py`;
contract: `.claude/skills/simplicio-loop/references/video-evidence.md`. It chains after
`web_verify` (screenshots → captioned, deterministic MP4 walkthrough). Evidence is always a file
path + verdict; a missing toolchain BLOCKS, never a fake pass.

## Non-negotiables

Delivery work follows the bounded WIP, frozen-AC, finding classification, review-cap, ownership,
rebase, and release rules in [ADR 0008](docs/adr/0008-bounded-delivery-policy.md) and the canonical
[`simplicio-loop` policy](.claude/skills/simplicio-loop/SKILL.md#bounded-delivery-policy).

- Run commands for real — never simulate output.
- **GitHub issue signature first:** before taking an issue, publish the canonical `CLAIMED`
  lifecycle comment with the worker/run/attempt identity and goal. Do this before mutation or a
  worktree; never take a live claimed issue. A PR reviewer signs its assessment on the PR instead
  and does not steal the implementation lease.
- Never mark an item done without green gates + evidence ("works, not just compiles").
- Secret-scan every diff; route irreversible ops through the human gate. Where hooks exist this is
  ENFORCED fail-closed by `hooks/action_gate.py` (PreToolUse/pre-push) — not left to the model.
- Unattended 24/7 runs require persistent source auth, human gate + secret scan, and a reachable
  STOP/cancel path.
- Report token-savings ONLY when a measured receipt backs it (clamp / signatures-read / cache hit /
  `deterministic_edit` / `savings_ledger`); never fabricate a figure. No measured economy → no
  savings line. Credited only on a passing quality gate.
- Verify claims locally before pushing: `python3 scripts/check.py` (test suite + claims-audit +
  `_bundle ≡ source` parity + the token/context budget guard, `scripts/token_budget.py`, #121).
  It requires importable `pytest` from `pip install "simplicio-loop[dev]"`; missing pytest is a
  failing gate result, never a bare-Python fallback. Keep it green.
- **Big refactors/doc rewrites:** run `python3 scripts/check.py --token-budget` and treat a FAIL
  as a real regression to justify or trim, not to silence with `--update-baseline` unreviewed.
- `simplicio-runtime` native binding (MCP or CLI) is optional. `simplicio doctor --json` can
  diagnose an installed runtime; its absence is reported as degraded runtime integration and
  never blocks the mapper/dev-cli loop.

## LLM command and feature index

The complete installed-entry-point and `simplicio-loop` command map is
[`docs/CLI_COMMANDS.md`](docs/CLI_COMMANDS.md). Run the most specific
`--help` before invoking a command. Every new public command must have
meaningful `help=` text, documentation in that file, and a help regression
check. The current train is Mapper 0.26.34, Dev CLI 0.18.16, Fast 2.0.35, and
Loop 3.43.16.

For GitHub work items, keep the body focused on objective, implementation,
deployment, and tests. Do not add an Acceptance Criteria section to new or
updated issues; report incomplete implementation or failed tests as such.

<!-- simplicio-global-llm-architecture-rules:start -->
## Regras arquiteturais obrigatórias para qualquer LLM

Estas regras valem para análise, planejamento, implementação, revisão, testes,
release e documentação neste ecossistema. O agente deve lê-las antes de agir:

1. **Não mantenha compatibilidade retroativa.** O que está obsoleto deve ser
   deletado diretamente. Não adicione camadas de compatibilidade, migrações ou
   fallbacks.
2. **Escolha a implementação mais simples que atende à necessidade atual.**
   Não crie abstrações preventivas nem camadas de configuração desnecessárias.
3. **Divida o sistema em camadas longas.** Faça primeiro uma versão mínima
   end-to-end funcionando; depois adicione capacidades por cima. Não desmonte
   algo que funciona por complexidades inacabadas.
4. **Mantenha os componentes modulares**, com responsabilidades claramente
   separadas e limites explícitos.
5. **Priorize bibliotecas maduras e mantidas.** Não reescreva do zero sem
   motivo técnico explícito e registrado.
6. **Inspecione primeiro as dependências existentes.** Antes de adicionar um
   pacote ou escrever uma solução própria, verifique o que o projeto já possui.
7. **Decida a arquitetura pensando no longo prazo.** Não aceite soluções
   temporárias com a intenção de mudar depois.
8. **Use padrões de produtos maduros.** Pesquise como soluções consolidadas
   resolvem o mesmo problema e reutilize padrões validados; não reinvente a roda.

<!-- simplicio-global-llm-architecture-rules:end -->



## Language precedence

[docs/LLM_OPERATING_INSTRUCTIONS.md](docs/LLM_OPERATING_INSTRUCTIONS.md) is the authoritative active instruction set and is written in English. Any other-language passage retained in this compatibility/reference file is non-normative; do not execute it as an instruction.
