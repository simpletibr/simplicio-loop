<!-- simplicio-contract:begin -->
contract: agents
schema: simplicio.agents/v1
purpose: Operating contract for every agent in this repository: layout, bound operators, skills, and delivery rules.
rules: Read before operating; mutable data (versions, dates, counts) lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# AGENTS.md — simplicio-loop

> **Full map + step-by-step:** [docs/ECOSYSTEM_LLM_GUIDE.md](docs/ECOSYSTEM_LLM_GUIDE.md) · ADR [0009](docs/adr/0009-loop-inside-runtime-operators-standalone.md) · [0010](docs/adr/0010-execution-metrics-report-standard.md)  
> **Max-speed LLM orientation (always):** [docs/LLM_MAX_SPEED_ORIENTATION.md](docs/LLM_MAX_SPEED_ORIENTATION.md) — also re-fed every loop turn via `SIMPLICIO-LLM-ORIENTATION` in the loop skill.

## Monorepo layout

Three packages, one responsibility each: root `simplicio_loop/` = **orchestration** (this
package); `packages/mapper/` = **survey** (`scan`/`inspect`/`handoff`); `packages/dev-cli/` =
**mutation** (`edit`/`test`/capabilities). All three ship in ONE wheel: `pip install simplicio-loop`
provides `simplicio-mapper`, `simplicio-dev-cli` and every other console script (there are no
separate `simplicio-mapper` / `simplicio-cli` PyPI dependencies; update with `simplicio-loop update`).
`packages/fast/` was removed entirely (issue #1343):
the survey that every flow requires is now Mapper-only. Dev setup: `bash scripts/dev_install.sh`. Local gate:
`python3 scripts/check.py` (by default it runs only the tests the change can affect; `--full` runs every
test file; `--package all` / `--package <name>` / `--changed` scope the package gates). No GitHub
Actions gate — the local gate is authoritative.

## Simplicio Ecosystem Contract (canonical)

This loop is the convergence layer of one Simplicio ecosystem. For every non-trivial task: survey
with `simplicio-mapper` (`scan`/`inspect`/`handoff`), rank/load relevant skills, mutate through
`simplicio-dev-cli`, validate, and record evidence. There is no Runtime/MCP backend in this stack.

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

`simplicio-loop` does not survey or edit with the LLM — it delegates to two in-repo packages. The
loop BLOCKS if either runtime binary is absent:

| Operator | Binary | Package | Binds | Role |
|---|---|---|---|---|
| [simplicio-mapper](packages/mapper/) | `simplicio-mapper` | `packages/mapper/` | `orient` | **survey** the repo → `.simplicio-loop/*.json` (the survey that feeds the goal) |
| [simplicio-dev-cli](packages/dev-cli/) | `simplicio-dev-cli` | `packages/dev-cli/` | `execute`/`deterministic_edit` | **operate** — apply+verify each decided change via its 6-layer contract, instead of the AI hand-editing |

The AI decides; the operators act. See `.claude/skills/simplicio-loop/SKILL.md` § Bound operators
and `.claude/skills/simplicio-loop/references/extension-points.md` § bound operators.

## Worker startup and centralized artifacts (mandatory)

Every subagent, worker, and provider session MUST read `AGENTS.md` and every relevant local skill before operating. For Loop work, the baseline skills are `.claude/skills/simplicio-loop/SKILL.md` and `.claude/skills/simplicio-prism/SKILL.md`; load additional satellite skills selected by the task before mutation.

The canonical default branch owns one centrally built binary/artifact set. Workers consume that binary read-only; they MUST NOT rebuild binaries or regenerate canonical Mapper artifacts. Worktrees isolate source edits and receipts only. Every receipt/handoff MUST record repository and revision, binary digest/version, Mapper generation and artifact digest. Missing, stale, incompatible, or mismatched central artifacts fail closed and route to the central rebuild path only; a worker may not repair them locally or fall back to fabricated/uncertified context.


### Full-stack boundaries
`simplicio-mapper` / `simplicio-dev-cli` observe, plan, and edit **standalone
— there is no Runtime/MCP backend in this stack.** `simplicio-loop` owns the full loop subsystem
(activation + convergence authority) and **mandatory execution-report metrics** (per task +
consolidated). Coordinators own cognition, not loop activation. See `docs/adr/0009` and
`docs/adr/0010`. Providers are workers, never authorities.

Delivery runs through `simplicio-loop turbo` (`simplicio-mapper` surveys, the invoking model plans,
`simplicio-dev-cli` applies), preserve `simplicio.io/v1`, and close only with real tests plus
recorded evidence. Facts are `MEASURED|`
only with receipts; otherwise `UNVERIFIED|`. Missing dependencies fail closed; never fabricate
context, tests, savings or provider output.
This repository ships a runtime-agnostic **super-plugin**: the Universal Looping AI
Orchestrator plus five satellite skills, packaged for 35 runtimes. Any agent runtime that
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

35 runtimes are listed in [`simplicio_loop/_catalog/harnesses.json`](simplicio_loop/_catalog/harnesses.json)
and documented in [`adapters/MATRIX.md`](adapters/MATRIX.md): the 32 host surfaces of `simpletibr/simplicio`
(Claude Code, Codex, Grok, Cursor, GitHub Copilot, OpenCode, MiMo Code, Amp, OpenClaude, Antigravity, Pi,
oh-my-pi, Hermes / Simplicio Agent, Devin, goose, Auggie, Autohand Code, Charm, Cline, Codebuff, Command
Code, Continue, Droid, Kilo Code, Kimi, Kiro, Mistral Vibe, Qwen Code, Rovo Dev, Gemini, VS Code, Orca) plus
Aider, DeepSeek and OpenClaw. Install every `wired` one with `scripts/install.sh <runtime>` (or `install.ps1`);
DeepSeek is a model provider, not a host, so its adapter README lists manual steps.

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

The compact current sequence is canonical in [`llms.txt`](llms.txt): run
`simplicio-loop "<task>" [--verify "<tests>"]` (short for `simplicio-loop turbo --repo . --task "<task>"`) once.
With a host CLI (OpenCode, Claude Code, ...: [docs/HARNESSES.md](docs/HARNESSES.md)) that one command runs Mapper, the
model through your own CLI, Dev CLI apply, `--verify` and one repair, and prints the result: `status` ok or failed is
final. Only when it prints a `needs_plan` request (`reason: "hybrid_unavailable: <cause>"`), run the printed `apply`
command once with your JSON plan as its heredoc body (`simplicio-loop turbo --repo . --apply - --verify "<tests>"
<<'PLAN'`; Dev CLI applies it and runs `--verify`; on `failed` fix the plan once and run it again). Do not explore,
list or read files, and do not run the tests yourself. Then run the focused gates and the live PR re-query. No
provider and no API key. Never hand-edit; Dev CLI makes every edit.
Execution is always standalone; there is no Runtime/MCP backend.

## Extension points (bind native when available)

The skill defines **48 named extension points** (see the Step 1b table in `SKILL.md`).
For each point, if this runtime exposes a faster native capability, **bind it** —
the step becomes deterministic and near-zero-token. The skill never requires a specific
runtime; the binding lives here in the host, not in the skill.

There is no Runtime/MCP backend in this stack. When a host cannot bind a given extension
point natively, the loop records that it was skipped and continues with the required
`simplicio-mapper` and `simplicio-dev-cli` operators.

## Canonical source per topic (#119 — avoid re-stating the same pitch in N docs)

Each topic below has exactly ONE canonical doc; every other file that touches the topic should
link to it instead of repeating the content. When editing one of these topics, edit the canonical
file and let secondary docs (`PYPI.md`, `llms.txt`, etc.) stay short pointers.

| Topic | Canonical doc | Secondary docs that point here instead of repeating it |
|---|---|---|
| Elevator pitch / what this repo is | `README.md` | `llms.txt` (one-line summary + link) |
| Runtime-agnostic contract (extension points, non-negotiables) | `AGENTS.md` (this file, the single agent-instruction file for every runtime) | — |
| Ecosystem / cross-repo dependencies | `SIMPLICIO_ECOSYSTEM.md` | — |
| Pricing / monetization | `PRICING.md` | — |
| Loop mechanics (protocol, exit gates) | `.claude/skills/simplicio-loop/SKILL.md` + `references/*.md` | `AGENTS.md` § Video evidence links in rather than re-describing |
| PyPI package listing copy | `PYPI.md` (wired as `readme` in `pyproject.toml`) | — (this is itself the PyPI-rendered page, so it necessarily carries its own condensed pitch) |
| LLM quick-orientation index | `llms.txt` | — |
| `scripts/*.py` core vs satellite classification | `docs/SCRIPTS_INVENTORY.md` (#118) | `README.md` § Tests & local checks links in rather than re-listing |

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
screenshots (`web_verify`, under `.simplicio-loop/orchestrator/tee/web`) and recordings (`video_evidence`, under
`.simplicio-loop/orchestrator/tee/video`). With `--require-evidence` it FAILS CLOSED (exit 3, `blocked`)
rather than open a PR that has neither a checklist nor a print. It honors a discovered
`.github/PULL_REQUEST_TEMPLATE.md` (keeps the maintainer's sections, appends checklist + prints
below). The task anchor is the same worker that stops task deviation: every turn re-checks the
frozen goal (`task_anchor.py check`) and the DoD gate (`task_anchor.py gate`) blocks "done" while
any AC is unverified.

## Progress feedback (real-time)

`scripts/loop_progress.py` computes "where are we / how much is left" deterministically from the
backlog + anchor + its own event trail — never fabricated. Three surfaces, one denominator:
**N1 hook** (Claude/Cursor re-feed header shows phase/step/item/ACs/%), **N2 transcript** (every
turn's first line is `render --turn-header`, normative on all runtimes), **N3 file**
(`.simplicio-loop/orchestrator/loop/PROGRESS.md`/`progress.json`, regenerated every turn — the universal
fallback any host, adapted or not, can read with zero extra code). Status command:
`python3 scripts/loop_progress.py status --json`. Full contract, event schema, and the
turn×event/runtime×level tables: `.claude/skills/simplicio-loop/references/progress-feedback.md`.

## Development

`scripts/dev_install.sh` creates ONE venv and installs the root package editable (mapper and
dev-cli are built into the single `simplicio-loop` wheel) — so the loop you run locally always
talks to its in-repo siblings, never a stale PyPI release:

```bash
bash scripts/dev_install.sh            # venv at .venv/ (default)
source .venv/bin/activate
python3 scripts/check.py                     # default: impact-based, only the tests the change can affect vs origin/main
python3 scripts/check.py --full              # every test file (run before a release tag)
python3 scripts/check.py --base REF          # diff against REF instead of origin/main
python3 scripts/impact_tests.py --json       # the test files the change affects, and the symbols that selected them
python3 scripts/check.py --package mapper    # ruff + pytest tests/python -q (impacted files only; --full for all)
python3 scripts/check.py --package dev-cli   # ruff + mypy + pytest tests/python tests/contracts -q
python3 scripts/check.py --package loop      # no-op alias: the loop's own gate is the rest of this script
python3 scripts/check.py --package all       # all four
python3 scripts/check.py --changed           # only the package(s) touched vs origin/main
```

A missing tool (no `ruff`/`mypy`/`pytest` on PATH or importable) fails with its own typed reason
rather than being silently skipped.

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

The marketplace install carries only the **lean `plugin/` subdirectory** (the 7 skills + the wired
hooks) — `.claude-plugin/marketplace.json` `source` points at `./plugin`, so the pip-only assets
(capture proxy `engine/`, token-monitor dashboard) are NOT copied into a user's plugin cache.
`plugin/` is generated from source by `python3 scripts/sync_plugin.py` (run it after editing skills
or a wired hook); `scripts/check.py` fails if `plugin/` drifts from source.

The installer writes an **`AGENTS.md`-based** entry file into the target project for every runtime
that needs one (Codex, Antigravity, OpenCode, Orca, Grok → `AGENTS.md`; VS Code/Copilot →
`.github/copilot-instructions.md`; Kiro → `.kiro/steering/simplicio-loop.md`; Gemini →
`GEMINI.md`; Aider → `CONVENTIONS.md`) by appending a marker block that points at the installed
skills — it never ships a copy of this repo's own instruction file. Claude Code and Cursor need no
entry file (they discover `.claude/skills/` / `.cursor/` directly).

## Hooks (the loop + token economy)

`hooks/` ships cross-platform Python hooks (fail-open): `loop_stop.py` (re-feed/exit),
`loop_capture.py` (promise detect), `orient_clamp.py` (clamp any command's output, tee on
failure), `orient_rewrite.py` (opt-in auto-clamp). See [`hooks/README.md`](hooks/README.md) for
`settings.json` wiring (the installer does it).

`orient_clamp.py` needs no wiring — `python3 hooks/orient_clamp.py -- <cmd>` anywhere.

**Safety is enforced, not just described:** `hooks/action_gate.py` is a **fail-closed**
`PreToolUse` (Bash) / git pre-push hook that BLOCKS irreversible ops (force-push, history rewrite,
mass-delete, destructive DDL, infra teardown) and secret-laden commits/pushes before they run
(exit 2). `python3 hooks/action_gate.py selftest` proves the ruleset.

## Releases in a monorepo

One wheel, one tag: `vX.Y.Z` releases `simplicio-loop`, which carries the Mapper and the Dev CLI
(their own `__version__` values are component versions, not separate releases). Bump every surface with
`python3 scripts/version_sync.py apply --version X.Y.Z`. There is no GitHub Actions gate and no
cross-repo release-train machinery; `python3 scripts/check.py` is the authoritative local gate
before any tag.

## Non-negotiables

Delivery work follows the bounded WIP, frozen-AC, finding classification, review-cap, ownership,
rebase, and release rules in [ADR 0008](docs/adr/0008-bounded-delivery-policy.md) and the canonical
[`simplicio-loop` policy](.claude/skills/simplicio-loop/references/full-flow.md#bounded-delivery-policy).

- Run commands for real — never simulate output.
- **TDD is mandatory:** every new function or behavior change starts with a
  failing test (red), then the minimal code to pass (green), then refactor.
  No production code without a test written first.
- **GitHub issue signature first:** before taking an issue, publish the canonical `CLAIMED`
  lifecycle comment with the worker/run/attempt identity and goal. Do this before mutation or a
  worktree; never take a live claimed issue. A PR reviewer signs its assessment on the PR instead
  and does not steal the implementation lease.
- Never mark an item done without green gates + evidence ("works, not just compiles").
- Secret-scan every diff; route irreversible ops through the human gate. Where hooks exist this is
  ENFORCED fail-closed by `hooks/action_gate.py` (PreToolUse/pre-push) — not left to the model.
- Report token-savings ONLY when a measured receipt backs it (clamp / signatures-read / cache hit /
  `deterministic_edit` / `savings_ledger`); never fabricate a figure. No measured economy → no
  savings line. Credited only on a passing quality gate.
- Verify claims locally before pushing: `python3 scripts/check.py` (the impacted tests — the default
  selection is `scripts/impact_tests.py` against `origin/main`, `--full` runs every test file — plus
  claims-audit + `_bundle ≡ source` parity + the token/context budget guard, `scripts/token_budget.py`, #121).
  It requires importable `pytest` from `pip install "simplicio-loop[dev]"`; missing pytest is a
  failing gate result, never a bare-Python fallback. Keep it green.
- **Big refactors/doc rewrites:** run `python3 scripts/check.py --token-budget` and treat a FAIL
  as a real regression to justify or trim, not to silence with `--update-baseline` unreviewed.

## LLM command and feature index

The complete installed-entry-point and `simplicio-loop` command map is
[`docs/CLI_COMMANDS.md`](docs/CLI_COMMANDS.md). Run the most specific
`--help` before invoking a command (not `simplicio-loop turbo` for a task run: the skill and the quick flow
above give its command in full). Every new public command must have
meaningful `help=` text, documentation in that file, and a help regression
check. Current release: Loop 3.47.0 (Mapper 0.26.34 and Dev CLI 0.18.16 are bundled).

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
