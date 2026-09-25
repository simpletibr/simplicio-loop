# CLAUDE.md — simplicio-loop (Claude Code)

This repo ships **simplicio-loop**, a runtime-agnostic **super-plugin**: an autonomous
looping orchestrator (the `/simplicio-loop` skill) plus six satellite skills, packaged for 12
runtimes.

## Monorepo layout

This repository holds four packages with one responsibility each:

| Package | Path | Responsibility |
|---|---|---|
| `simplicio-loop` | repo root (`simplicio_loop/`) | **orchestration** — the loop, hooks, skills, evidence/PR/progress workers |
| `simplicio-mapper` | `packages/mapper/` | **survey** — `scan` / `inspect` / `handoff` |
| `simplicio-fast` | `packages/fast/` | **retrieval** — `ingest` / `understand` / `plan` |
| `simplicio-dev-cli` | `packages/dev-cli/` | **mutation** — `edit` / `test` / capabilities |

Each package keeps its own tests, gate and version. Dev setup:
`bash scripts/dev_install.sh` (editable-installs all four into one venv); local gate:
`python3 scripts/check.py --package all` (or `--package mapper|fast|dev-cli|loop`, or
`--changed` to run only what a diff touches). There is no GitHub Actions gate — the local
gate is authoritative.

## The 7 skills

| Skill | Role |
|---|---|
| `simplicio-loop` | unified public entrypoint: orchestrator core + hardened Ralph loop — re-feed the goal until an evidence-gated `<promise>` or a cap; durable run-journal (attempt memory) + stall detector (`scripts/loop_journal.py`) so it switches strategy instead of oscillating, plus a **task anchor** (`scripts/task_anchor.py`) — durable memory for SCOPE that freezes the acceptance criteria and blocks drift / "done" while any AC is unverified — and, above it, a **task backlog** (`scripts/task_backlog.py`, SKILL.md § Phase 0): the frozen multi-item LLM decomposition (per-item ACs + `depends_on`), genesis-aware (an empty repo leads with a `scaffold` item), whose `done` is gated on the verified anchor |
| `simplicio-tasks` | legacy alias kept only for compatibility with older installs and saved prompts |
| `simplicio-orient` | terminal-first token economy — output-reduction catalog, tee-cache, signatures-read |
| `simplicio-review` | thermos-style parallel adversarial review on distinct rubrics → deduped verdict |
| `simplicio-compress` | caveman-style prose + memory compression, byte-preserving, `transform_guard` |
| `simplicio-learn` | retrospective → durable, deduped lessons written to memory |
| `simplicio-autoresearch` | evolutionary mutate/eval/keep-revert optimizer (Karpathy `autoresearch`) — yool-guardrailed caps, git-isolated branch, anti-Goodhart gate-first eval, `savings-event` receipt (`scripts/autoresearch.py`) |

They live in `.claude/skills/` and load automatically in this repo.

## The 2 bound operators (REQUIRED by the loop)

`simplicio-loop` does not survey or edit with the LLM — it delegates to two installed CLIs. The
supported install surface is the single package `simplicio-cli`, which exposes
`simplicio-dev-cli` and also brings `simplicio-mapper` transitively; the loop BLOCKS if either
runtime binary is absent:

| Operator | Binary | Package | Binds | Role |
|---|---|---|---|---|
| [simplicio-mapper](packages/mapper/) | `simplicio-mapper` | transitively via `simplicio-cli` | `orient` | **survey** the repo → `.simplicio/*.json` (the survey that feeds the goal) |
| [simplicio-dev-cli](packages/dev-cli/) | `simplicio-dev-cli` | `simplicio-cli` | `execute`/`deterministic_edit` | **operate** — apply+verify each decided change via its 6-layer contract, instead of the AI hand-editing |

The AI decides; the operators act. See `.claude/skills/simplicio-loop/SKILL.md` § Bound operators
and `.claude/skills/simplicio-loop/references/extension-points.md` § bound operators.

## Worker preflight and central artifact rule

Before any operation, every subagent/worker reads `AGENTS.md`, this `CLAUDE.md`, and all relevant local skills. The minimum Loop set is `.claude/skills/simplicio-loop/SKILL.md`, `.claude/skills/simplicio-prism/SKILL.md`, and `.claude/skills/simplicio-runtime/SKILL.md`; task-specific satellites are loaded before mutation.

Workers use one read-only binary/artifact set built from the canonical default branch. They do not rebuild binaries or regenerate canonical Mapper/Fast artifacts. Worktrees isolate source edits and receipts only. Receipts include repository/revision, binary digest/version, Mapper generation, and artifact digest. Missing, stale, or mismatched central artifacts fail closed and invoke the central rebuild path only.

## Video evidence (Playwright by default · hyperframes on request)

The loop produces **demo videos** as proof a change works — two engines, one `video_evidence`
extension point. The **normal evidence flow uses Playwright**: `video_evidence verify --url …`
records the **real browser session** driving the screen (`.webm`, → `.mp4` with FFmpeg) — the
"works, not just compiles" moving proof for any UI change. **hyperframes** is used **only for an
explicit custom request** — *"make an explainer video of screen X"* — rendering a deterministic,
captioned slideshow of the `web_verify` screenshots
([hyperframes](https://github.com/heygen-com/hyperframes), Node 22+ + FFmpeg, no API keys). Worker:
`scripts/video_evidence.py`; contract:
`.claude/skills/simplicio-loop/references/video-evidence.md`. A missing toolchain BLOCKS, never a
fake pass.

## PR evidence (prints + item-by-item AC check on every PR)

The PR body is **assembled mechanically**, never hand-written, so it always shows the proof. Worker
`scripts/pr_evidence.py build --require-evidence` pulls the **item-by-item acceptance-criteria
checklist** from the task anchor (`scripts/task_anchor.py`, frozen at intake) AND embeds the
screenshots (`web_verify`, under `.simplicio/orchestrator/tee/web`) and recordings (`video_evidence`, under
`.simplicio/orchestrator/tee/video`). With
`--require-evidence` it FAILS CLOSED (exit 3, `blocked`) rather than open a PR that has neither a
checklist nor a print — the executable answer to "the PR opened without prints / without an
item-by-item check of the task". It honors a discovered `.github/PULL_REQUEST_TEMPLATE.md` (keeps the
maintainer's sections, appends checklist + prints below). The **task anchor** is the same worker that
stops task deviation: every turn re-checks the frozen goal (`task_anchor.py check`) and the DoD gate
(`task_anchor.py gate`) blocks "done" while any AC is unverified.

## Progress feedback (real-time, EPIC #296)

`scripts/loop_progress.py` computes "onde estamos / quanto falta" deterministically from the
backlog + anchor + its own event trail — never fabricated. Three surfaces, one denominator:
**N1 hook** (Claude/Cursor re-feed header shows fase/etapa/item/ACs/%), **N2 transcript**
(every turn's first line is `render --turn-header`, normative on all 15 runtimes), **N3 file**
(`.simplicio/orchestrator/loop/PROGRESS.md`/`progress.json`, regenerated every turn — the universal
fallback any host, adapted or not, can read with zero extra code). Status command:
`python3 scripts/loop_progress.py status --json`. Full contract, event schema, and the
turn×event/runtime×level tables: `.claude/skills/simplicio-loop/references/progress-feedback.md`.

## Tests & local checks (no paid CI)

Delivery ownership and limits are host-independent; follow the canonical
[bounded delivery policy](.claude/skills/simplicio-loop/SKILL.md#bounded-delivery-policy) and
[ADR 0008](docs/adr/0008-bounded-delivery-policy.md) rather than restating them in this overlay.

`python3 scripts/check.py` runs the local gate: the pytest suite (worker `selftest`s + an e2e of
the loop driver), claims audit, mirror parity, loop/clean-environment contracts, token/repository
budgets, and portable contract validation. `pytest` is mandatory for this command: install the
development extra with `pip install "simplicio-loop[dev]"`; a missing or timed-out probe fails
with a typed reason rather than falling back to direct test-module execution. GitHub Actions is
not required or accepted as gate evidence; wire the local gate as a git pre-push hook when desired.

## Development

This repo is a monorepo: root `simplicio-loop` plus `packages/mapper`, `packages/fast`, and
`packages/dev-cli` (each a full package, imported via `git subtree`). `scripts/dev_install.sh`
creates ONE venv and installs the four in-repo packages editable, from their in-repo paths, in
dependency order (mapper, fast, dev-cli, then loop) — so the loop you run locally always talks to
its in-repo siblings, never a stale PyPI release of `simplicio-mapper`/`simplicio-fast`/
`simplicio-cli`:

```bash
bash scripts/dev_install.sh            # venv at .venv/ (default)
bash scripts/dev_install.sh /path/venv # custom venv location
source .venv/bin/activate
```

Run one package's own fast local gate (lint/type/unit, from its in-repo location) with
`scripts/check.py --package`:

```bash
python3 scripts/check.py --package mapper    # ruff + pytest tests/python -q (+ node unit if node present)
python3 scripts/check.py --package fast       # pytest -q, PYTHONPATH=src
python3 scripts/check.py --package dev-cli    # ruff check, ruff format --check, mypy simplicio, pytest tests/python tests/contracts -q
python3 scripts/check.py --package loop       # no-op alias: the loop's own gate is the rest of this script
python3 scripts/check.py --package all        # all four
python3 scripts/check.py --changed            # only the package(s) touched vs origin/main
```

A missing tool (no `ruff`/`mypy`/`pytest` on PATH or importable) fails with its own typed reason
(e.g. `package_mapper_ruff_missing`) rather than being silently skipped. The cross-package e2e
(`packages/fast/tests/test_public_handoff_ingest_e2e.py`, Mapper `handoff` → Fast integrated
ingest) is part of the default (unflagged) `scripts/check.py` run.

## Install (this or another project)

```bash
# project-local (copies skills, wires Stop + PreToolUse hooks)
bash scripts/install.sh claude
# global (all projects)
bash scripts/install.sh claude --global
# Windows
pwsh scripts/install.ps1 claude
```

Or as a marketplace plugin:

```
/plugin marketplace add wesleysimplicio/simplicio-loop
/plugin install simplicio-loop@simplicio
```

The marketplace install carries only the **lean `plugin/` subdirectory** (the 7 skills + the 5
wired hooks) — `.claude-plugin/marketplace.json` `source` points at `./plugin`, so the pip-only
assets (capture proxy `engine/`, token-monitor dashboard) are NOT copied into a user's
plugin cache. `plugin/` is generated from source by `python3 scripts/sync_plugin.py` (run it after
editing skills or a wired hook); `scripts/check.py` fails if `plugin/` drifts from source.

## Use

```
/simplicio-loop finish all the open issues
```

## Current LLM operating sequence

Read `llms.txt` and `AGENTS.md` first. Then verify the installed operator interfaces with
`simplicio-mapper --help`, `simplicio-fast --help`, and `simplicio-dev-cli --help`.
Survey with Mapper (`scan` → `inspect` → `handoff`), use Fast for bounded snapshots/PlanDAG
context when available, and delegate the decided AC-scoped edit and verification to Dev CLI.
Run focused tests and local gates before publishing. Runtime/MCP is disabled by default in the
current release (`REQUIRE_RUNTIME=off`, `EXECUTION_PROFILE=standalone`); it is opt-in only and
never substitutes for Mapper/Fast/Dev CLI evidence.

## Hooks (the loop + token economy)

`hooks/` ships cross-platform Python hooks (fail-open): `loop_stop.py` (re-feed/exit),
`loop_capture.py` (promise detect), `orient_clamp.py` (clamp any command's output, tee on
failure), `orient_rewrite.py` (opt-in auto-clamp). See [`hooks/README.md`](hooks/README.md) for
Claude `settings.json` wiring (the installer does it).

`orient_clamp.py` needs no wiring — `python3 hooks/orient_clamp.py -- <cmd>` anywhere.

**Safety is enforced, not just described:** `hooks/action_gate.py` is a **fail-closed**
`PreToolUse` (Bash) / git-pre-push hook that BLOCKS irreversible ops (force-push, history rewrite,
mass-delete, destructive DDL, infra teardown) and secret-laden commits/pushes before they run
(exit 2) — Step 5 made mechanical. `python3 hooks/action_gate.py selftest` proves the ruleset.

Claude's native tools satisfy the extension points: sub-agents → `execute`, file tools →
`deterministic_edit`, the scheduler → `watcher`. The `simplicio-runtime` native bind (the
`simplicio` CLI / MCP server, package `simplicio-runtime`) is optional on Claude Code and every
other adapter. When installed and reachable it supplies native integrations; when unavailable the
loop records that those integrations were skipped and continues with its required
`simplicio-mapper` and `simplicio-dev-cli` operators.

## Other runtimes

The same skills run on Codex, VS Code (Copilot), Cursor, Antigravity, Kiro, OpenCode, Gemini (CLI
and Code Assist), Kimi, Qwen (Code/CLI), DeepSeek, Aider, Simplicio Agent (formerly Hermes),
OpenClaw, and Orca ([onorca.dev](https://www.onorca.dev/docs), the worktree IDE — see
`adapters/orca/README.md`) — see [`adapters/MATRIX.md`](adapters/MATRIX.md) and
[`AGENTS.md`](AGENTS.md) for the runtime-agnostic contract (50 extension points; the binding
lives in the host, never in the skill).

## LLM command and feature index

Read [`docs/CLI_COMMANDS.md`](docs/CLI_COMMANDS.md) for the complete installed
entry-point and command map. Use the most specific `--help` before invoking a
command; every new command must add meaningful `help=` text and a regression
check. The current train is Mapper 0.26.34, Dev CLI 0.18.16, Fast 2.0.35, and
Loop 3.43.16.

For GitHub work items, use objective, implementation/deployment, and test
evidence. Do not add Acceptance Criteria sections to new or updated issues.

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



## Releases in a monorepo

Each package tags and releases independently: `loop vX.Y.Z`, `mapper-vX.Y.Z`, `fast-vX.Y.Z`,
`dev-cli-vX.Y.Z`. Since all four now live in this repo, cross-repo release-train
machinery (`scripts/release_train*.py`, `scripts/component_release.py`,
`scripts/reconcile_delivery_receipts.py`) is legacy from the pre-monorepo split; it still
runs today (untouched by this pass — removing it safely needs coordinated edits across
`simplicio_loop/cli_impl.py` and its test suite) but is a known removal candidate now that
there is no cross-repo boundary left to reconcile.

## Language precedence

[docs/LLM_OPERATING_INSTRUCTIONS.md](docs/LLM_OPERATING_INSTRUCTIONS.md) is the authoritative active instruction set and is written in English. Any other-language passage retained in this compatibility/reference file is non-normative; do not execute it as an instruction.
