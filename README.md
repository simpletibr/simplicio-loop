# 🔁 simplicio-loop — The Universal Looping AI Orchestrator

<p align="center">
  <img src="assets/simplicio-loop-hero-stage-agents-2026.webp" alt="simplicio-loop portable stage agents, evidence gates, durable memory, and connected work-item reporting" width="920" />
</p>

<p align="center">
  <a href="docs/REPOSITORY_GOVERNANCE.md"><img src="https://img.shields.io/badge/CI-local%20gate%20is%20authoritative-888888" alt="Validation status: the local scripts/check.py gate is authoritative; GitHub Actions is not required evidence"></a>
  <a href="https://github.com/simpletibr/simplicio-loop/stargazers"><img src="https://img.shields.io/github/stars/simpletibr/simplicio-loop?style=social" alt="Stars"></a>
  <a href="#-the-7-skills--5-accelerators"><img src="https://img.shields.io/badge/skills-7-7C3AED" alt="7 skills"></a>
  <a href="#-source-adapters"><img src="https://img.shields.io/badge/source%20adapters-5-00E08A" alt="5 source adapters"></a>
  <a href="#-15-runtimes-one-protocol"><img src="https://img.shields.io/badge/runtimes-15%20(3%20guaranteed%2B12%20best--effort)-2563EB" alt="15 runtimes (3 guaranteed + 12 best-effort)"></a>
  <a href="#-the-50-extension-points"><img src="https://img.shields.io/badge/extension%20points-50-00E08A" alt="50 extension points"></a>
  <a href="#measured-benchmark-issue-17"><img src="https://img.shields.io/badge/bench%20%2317-90%25%20fewer%20est.%20tokens-00E08A" alt="Issue #17 bench: ~90% fewer estimated tokens with loop"></a>
  <a href="#-token-economy"><img src="https://img.shields.io/badge/savings-mixed%20(see%20bench)-2563EB" alt="Savings — see measured bench + evidence-gated monitor"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="https://discord.gg/wM6tr7xVb"><img src="https://img.shields.io/badge/Discord-Join%20Simplicio-5865F2?logo=discord&logoColor=white" alt="Join the Simplicio Discord"></a>
</p>

<p align="center">
  <a href="#-tldr">TL;DR</a> ·
  <a href="#-the-7-skills--5-accelerators">7 Skills</a> ·
  <a href="#-source-adapters">Source Adapters</a> ·
  <a href="#-15-runtimes-one-protocol">15 Runtimes</a> ·
  <a href="#-the-loop">The Loop</a> ·
  <a href="#-token-economy">Token Economy</a> ·
  <a href="#measured-benchmark-issue-17">Bench #17</a> ·
  <a href="#-token-economy">Capture Engine</a> ·
  <a href="#-install--use">Install</a>
</p>

<p align="center">
  <strong>🌍 Languages:</strong><br>
  <a href="README.md">🇬🇧 English</a> |
  <a href="READMEs/README.pt-BR.md">🇧🇷 Português</a> |
  <a href="READMEs/README.es-ES.md">🇪🇸 Español</a> |
  <a href="READMEs/README.fr-FR.md">🇫🇷 Français</a> |
  <a href="READMEs/README.de-DE.md">🇩🇪 Deutsch</a> |
  <a href="READMEs/README.it-IT.md">🇮🇹 Italiano</a> |
  <a href="READMEs/README.ja-JP.md">🇯🇵 日本語</a> |
  <a href="READMEs/README.ko-KR.md">🇰🇷 한국어</a> |
  <a href="READMEs/README.zh-CN.md">🇨🇳 简体中文</a> |
  <a href="READMEs/README.ru-RU.md">🇷🇺 Русский</a> |
  <a href="READMEs/README.pl-PL.md">🇵🇱 Polski</a> |
  <a href="READMEs/README.tr-TR.md">🇹🇷 Türkçe</a> |
  <a href="READMEs/README.nl-NL.md">🇳🇱 Nederlands</a> |
  <a href="READMEs/README.hi-IN.md">🇮🇳 हिन्दी</a> |
  <a href="READMEs/README.ar-SA.md">🇸🇦 العربية</a>
</p>

---

<!-- visual-story:start -->
## 🚀 The new generation — an operating system for verified agent work

**simplicio-loop has evolved far beyond a repeat-until-done prompt.** It now compiles intent into a frozen task contract, maps the repository, schedules dependency-aware work, fans execution out into isolated worktrees, collects structured receipts, verifies independently, rolls back safely, remembers every attempt, and keeps the source of record synchronized through delivery.

- **Contract first** — acceptance criteria, dependencies, risks, source state, and the completion oracle are explicit before execution.
- **Parallel without corruption** — ready tasks run in isolated lanes/worktrees and converge through an operational ledger.
- **Automatic fan-out by default** — `batch` provisions one owned worktree per independent,
  authorized task; overlap, missing evidence, or unavailable isolation falls back to a
  visible serial lane. See [`docs/AUTO_FAN_OUT.md`](docs/AUTO_FAN_OUT.md).
- **Proof before completion** — tests, impact/flow checks, watcher challenges, delivery receipts, and HBP evidence reject false done states.
- **Memory that changes behavior** — the journal, stall detector, checkpoints, and cross-agent wiki prevent oscillation and make handoffs durable.

<p align="center">
  <img src="assets/simplicio-loop-parallel-worktrees.png" alt="simplicio-loop parallel isolated worktree execution" width="920" />
</p>

<p align="center"><em>Dependency-aware fan-out: isolated workers execute concurrently, return evidence, and converge into one verified delivery.</em></p>

<p align="center">
  <img src="assets/simplicio-loop-lifecycle-2026.svg" alt="simplicio-loop lifecycle from intake to durable memory" width="920" />
</p>

<p align="center"><em>Every stage is explicit, bounded, observable, and reversible.</em></p>

<p align="center">
  <img src="assets/simplicio-loop-evidence-memory.png" alt="simplicio-loop evidence memory verification rollback and completion" width="920" />
</p>

<p align="center"><em>Evidence and memory are part of the execution path—not a report written after the fact.</em></p>

That architecture lets one goal become a governed delivery system: from a single hard task to an entire backlog, across sessions and runtimes, with local-first operators and receipts strong enough for humans, CI, or another agent to audit.

<p align="center">
  <img src="assets/simplicio-loop-architecture-2026.svg" alt="simplicio-loop control execution evidence and delivery planes" width="920" />
</p>
<!-- visual-story:end -->

<!-- stage-agents-roadmap:start -->
## 🤖 Shipped: a concrete agent behind every stage

> **Implementation status:** [#422](https://github.com/simpletibr/simplicio-loop/issues/422)–[#436](https://github.com/simpletibr/simplicio-loop/issues/436) — the whole EPIC — is **closed and shipped** as of v3.37.0, including the full mandatory stage-reporting gate ([#433](https://github.com/simpletibr/simplicio-loop/issues/433)) and the multi-tracker interface ([#436](https://github.com/simpletibr/simplicio-loop/issues/436)). v3.38.0 adds the multi-agent coordination layer on top (`scripts/coordinator.py`, `scripts/pr_dod_review.py`) — see [§ What's new](#-whats-new-in-v3380--the-multi-agent-coordination-release).

The portable driver assigns one accountable agent to intake/planning, implementation, safety,
delivery, feedback/recovery, and final completion audit. Review fans out to four independent agents
— security/correctness, code quality, runtime reproduction, and blast radius — before it can
reconverge. Every transition emits an event and receipt; the completion auditor accepts evidence,
never self-reported confidence.

<p align="center">
  <img src="assets/simplicio-loop-stage-agents-reporting-2026.webp" alt="simplicio-loop stage agents with four-way review, evidence ledger, recovery, completion audit, and work-item comments" width="920" />
</p>

### Work-item comment policy

| Work tracker | Reporting policy | Completion meaning |
|---|---|---|
| **GitHub Issues / PRs** | **Required** for GitHub-bound runs | `COMPLETE` waits for a remotely observed comment receipt |
| **Azure DevOps** | Only when its connector is detected, authenticated, authorized, and target-resolved | Connected providers report; `NOT_CONNECTED` is an explicit, non-blocking skip |
| **Jira** | Only when connected | Same canonical timeline, provider-specific confirmation |
| **Asana** | Only when connected | Same canonical timeline, provider-specific confirmation |
| **Trello** | Only when connected | Same canonical timeline, provider-specific confirmation |

```mermaid
flowchart LR
  SOURCE["Issue · task · queue"] --> COORD["Portable coordinator"]
  COORD --> PLAN["Intake + Planner agent"]
  PLAN --> BUILD["Implementation agent"]
  BUILD --> SAFE["Safety agent"]
  SAFE --> R1["Review agent · security"]
  SAFE --> R2["Review agent · quality"]
  SAFE --> R3["Review agent · runtime/E2E"]
  SAFE --> R4["Review agent · blast radius"]
  R1 --> DELIVER["Delivery agent"]
  R2 --> DELIVER
  R3 --> DELIVER
  R4 --> DELIVER
  DELIVER --> RECOVER["Feedback + Recovery agent"]
  RECOVER --> BUILD
  DELIVER --> AUDIT["Completion auditor"]
  AUDIT --> VERDICT{"COMPLETE · PARTIAL · BLOCKED · REGRESSED"}
  PLAN -. "events + receipts" .-> LEDGER["Append-only stage ledger"]
  BUILD -.-> LEDGER
  SAFE -.-> LEDGER
  DELIVER -.-> LEDGER
  AUDIT -.-> LEDGER
  LEDGER --> GH["GitHub comments · REQUIRED"]
  LEDGER -. "only if connected" .-> AZ["Azure DevOps comments"]
  LEDGER -. "only if connected" .-> JIRA["Jira comments"]
  LEDGER -. "only if connected" .-> ASANA["Asana comments"]
  LEDGER -. "only if connected" .-> TRELLO["Trello comments"]
  GH --> AUDIT
```

The provider-neutral contract, capability probes, idempotent markers, durable outboxes, recovery
rules, sandbox E2E matrix, and acceptance criteria are specified in
[#436](https://github.com/simpletibr/simplicio-loop/issues/436). An optional provider is never
treated as connected merely because a CLI exists, and no remote acknowledgment is ever invented.
<!-- stage-agents-roadmap:end -->

## 🆕 What's new in v3.38.0 — the multi-agent coordination release

This release is about one hard problem that only shows up once **several agent sessions work the
same repo at once**: how does a session know what's already claimed, what's already merged-but-
incomplete, and what to do with its own idle time instead of duplicating a sibling's work? Every
item below was built, tested, and shipped against the **live, multi-session state of this very
repo** — not a synthetic scenario.

- **`scripts/coordinator.py` — the decision core.** Given today's GitHub state (open-issue claim
  comments + merged PRs), it returns one deterministic action per issue: `OWN` (nothing claimed
  yet), `CONTINUE_OWN` (you're already the latest claimant), `DEFER_ACTIVE_CLAIM` (a sibling
  session claimed it recently — don't duplicate), `RECLAIM_STALE` (that claim went cold, safe to
  pick up), or `VERIFY_PARTIAL` (a PR already merged for this issue, but it's still open — check
  what's actually done before assuming either "nothing happened" or "it's finished"). It also
  raises a `duplicate_risk` flag the instant two sessions claim the same issue close together.
  Caught, live, on day one: two sessions independently building a findings collector for the same
  issue under two different filenames.
- **`scripts/pr_dod_review.py` — the reviewer for idle time.** When every open issue is already
  claimed, a session's highest-leverage move isn't to wait — it's to check the open PRs against
  this repo's own bar: the 7-dimension Definition of Done (implementation, unit/integration/
  system/regression tests, a performance benchmark, ≥85% coverage) and the underlying issue's
  frozen acceptance-criteria checklist. `check --post` posts a mechanical, line-by-line verdict as
  a PR comment instead of a vibe-based approval. Proven against a real, already-merged "MVP slice"
  PR: it correctly flagged **17 of 17** acceptance criteria on the parent epic as still unresolved.
- **`scripts/finding_collector.py` — durable, deduplicated defect memory (issue #466, phase 1).**
  A `simplicio.finding/v1` record per distinct defect, fingerprinted so the *same* underlying bug —
  seen by any agent, any run, any timestamp — collapses into one record with an occurrence count
  instead of spawning duplicate noise. No GitHub calls yet; that's the next phase.
  `scripts/evolution.py` (taxonomy + priority + dedup) and `scripts/workflow_topology.py` (DAG
  diff + validator) shipped as the first MVP slices of the companion Continuous Evolution (#467)
  and Adaptive Architecture (#468) epics; `scripts/agent_replication.py` did the same for Elastic
  Replication (#469) — admission control and winner-selection for speculative duplicate execution.
- **`references/multi-agent-coordination.md` + `references/background-verification.md`** — two new
  documented conventions wired straight into `SKILL.md`'s triage step: check coordinator ownership
  before touching an issue, review PRs instead of idling once everything's claimed, and launch
  slow verification commands (tests/`claims_audit.py`) in the background so a turn keeps making
  progress instead of watching a progress bar.
- **Mandatory post-merge cleanup (`scripts/worktree_cleanup.py`, #484)** — a merged branch's local
  worktree and branch ref are now removed automatically instead of accumulating across sessions.
- **CLI contract additions (WI-471)** — a `preflight` subcommand and a `--json` flag on `status`,
  so an external supervisor can machine-check readiness before arming a run.
- **Continuous Findings wiring (WI-466)** — the completion gate now genuinely consults the finding
  store, and a store/repo consistency bug was found and fixed in the same pass.
- **Two real regressions caught and fixed on `main` itself, live, this release cycle** — a PR that
  silently deleted a function definition (breaking `loop_progress.py`'s own selftest) merged once,
  and a squash-merge race then reintroduced the exact same broken code onto `main` a second time.
  Both were found by actually running the affected script, not by trusting a green PR description —
  the whole reason `coordinator.py` and `pr_dod_review.py` exist now.
- **Carried forward from v3.37.0's Portable Stage Agents epic (#422–#436)** — a concrete,
  independently verifiable agent behind every stage (intake/planner, implementation, four-way
  review panel, safety gate, delivery, feedback/recovery, completion auditor), a portable contract
  validator for the shared graph/receipt schema, human-readable agent identities, and optional
  native binds for `simplicio-runtime`, `simplicio-mapper`, and `simplicio-dev-cli`. Runtime rows
  are capability inventory; a runtime is counted as executed only by the separate installed lane
  when its binary and executable adapter are actually available.
- **Test-suite inventory is measured, not hard-coded.** The checkout and the latest local gate
  receipt are the source of truth for file and result counts. `scripts/test_categories.py` reports
  the unit/integration/system/regression convention where it applies, including any uncategorized
  files; `scripts/claims_audit.py` stayed at 14/14 through every merge this cycle.

**What this means for you, concretely:** if you run `simplicio-loop` across more than one session
or machine against the same repo, it now actively protects you from the two failure modes that
actually happen in practice — two agents quietly redoing the same work, and a "done" PR that
merged but left the real issue only partially solved. Neither used to be visible; both now are,
mechanically, every triage pass.

See [`CHANGELOG.md`](CHANGELOG.md) for the full list and the
[v3.38.0 release](https://github.com/simpletibr/simplicio-loop/releases/tag/v3.38.0) for
signed artifacts (wheel, sdist, SBOM, provenance).

## ⚡ TL;DR

**simplicio-loop** is a runtime-agnostic **super-plugin** — one autonomous looping
orchestrator (invoked as **`/simplicio-loop`**) plus **six satellite skills and five
accelerators** — that turns any
strong LLM (Claude, Codex, Copilot, Gemini, Cursor, local models) into a self-driving worker. You
point it at a body of work — *"finish all the open issues"*, *"clear the CI queue"*, *"drain the Jira board"* — and it
runs the whole lifecycle on its own:

> **discover → understand → decide → act → verify → correct → record → repeat**

It discovers work from any source (GitHub Issues, Jira, Azure DevOps, agentsview sessions, and
more), dedups, auto-scales an agent fleet to your machine, implements each item through a quality
loop that **runs the code (not just compiles it)**, opens PRs, resolves CI/review feedback, merges,
and keeps watching **24/7** for new work — all behind safety gates and evidence checks.

```text
/simplicio-loop finish all open issues
→ identity + pre-flight (auth, watcher, STOP path)
→ discover 50 issues · dedup · build dependency DAG
→ autoscale fleet = 14 · pipeline implement→review→merge
→ each item: read body+ACs → orient code → plan → edit → run → verify → PR
→ merge · close with evidence · rollback if main breaks
→ keep looping every ~2 min until the queue is dry (evidence-gated, never a false "done")
```

Three things make it different: it is a **super-plugin of focused skills**, it runs the **same
protocol on 15 runtimes**, and it does all of this with **aggressive, honest token economy**.

The skill installs **standalone**: there is no Runtime/MCP backend, and no mandatory
native component, to use `simplicio-loop`. The two bound operators (`simplicio-mapper`,
`simplicio-dev-cli`) are the whole stack.

<p align="center">
  <img src="assets/simplicio-loop-infographic.png" alt="simplicio-loop detailed infographic: standalone install, 7 skills, 5 accelerators, 15 runtimes, 5 source adapters, and proof gates" width="920" />
</p>

Within the Simplicio product line, this repo is also the **current reference task flow** for
company work: its evidence-gated converge/drain discipline, durable attempt journal, and worker
coordination patterns are the pattern other Simplicio tools reuse.

### 👁️ Progresso visual, honesto e portátil

Cada execução pode ser acompanhada por texto, Markdown, JSON ou uma animação ANSI. Todas as
superfícies consomem o mesmo evento `simplicio.progress/v1`, incluindo ícones de etapa, gates de
evidence/watcher/oracle, lanes de worktrees e eventos de `worker_claimed` até `delivery_reconciled`.

```powershell
simplicio-loop progress <run-id> --format text --once
simplicio-loop progress <run-id> --format markdown --once   # LLM/chat
simplicio-loop progress <run-id> --format json --once       # dashboard/adapters
simplicio-loop progress <run-id> --format text --ascii --no-animation  # log/PowerShell
```

`100%` só aparece com receipt do oracle pronto (`COMPLETE`/`DRAINED`); uma fase `done` sem prova
fica quase concluída e mostra o blocker. Consulte o contrato completo em
[`docs/PROGRESS_PROTOCOL.md`](docs/PROGRESS_PROTOCOL.md).

---

## 📦 Monorepo packages

This repository holds three packages, each with one responsibility:

| Package | Path | Responsibility |
|---|---|---|
| **`simplicio-loop`** | repo root (`simplicio_loop/`) | **orchestration** — the loop, skills, hooks, and the evidence/PR/progress workers described below |
| **`simplicio-mapper`** | [`packages/mapper/`](packages/mapper/) | **survey** — `scan` / `inspect` / `handoff` |
| **`simplicio-dev-cli`** | [`packages/dev-cli/`](packages/dev-cli/) | **mutation** — `edit` / `test` / capabilities |

Dev setup (editable-installs all three into one venv): `bash scripts/dev_install.sh`. Local
gate: `python3 scripts/check.py --package all` (or `--package mapper|dev-cli|loop`, or
`--changed` to run only what a diff touches). There is no GitHub Actions gate here — the
local gate is authoritative. The delivery flow for any task count is two commands:
**`simplicio-loop "<task>"`** (short for `simplicio-loop turbo`) — Mapper surveys once and prints the one apply
command; the invoking model runs it with its plan in the heredoc, Dev CLI applies it and `--verify` runs the
tests; no provider and no API key (see [Zero-config execution](#zero-config-execution)).

---

## 🤖 LLM front door

If you are an agent/runtime entering this repo cold, read `llms.txt` first for the short operational contract, then `AGENTS.md`, then `.claude/skills/simplicio-loop/SKILL.md`.

---

## 📘 Official capability record

The complete, official roster of what `simplicio-loop` ships — every capability below is **real,
runnable, and tested** by the applicable local gate. Exact collected/executed/skipped/deselected
counts belong to that gate receipt, not this document. Each capability links to its deep section
and its worker.

| Capability | What it does | Proof / worker | Details |
|---|---|---|---|
| 🎬 **Video evidence** (`video_evidence`) | Records the **real browser session** as moving proof a UI change works (Playwright, default); renders a **deterministic captioned MP4** with [hyperframes](https://github.com/heygen-com/hyperframes) for an explicit explainer request (`/simplicio-loop make a video of screen X`) | `scripts/video_evidence.py` · BLOCKED (never fake-pass) without the toolchain | [§ Video evidence](#-video-evidence--playwright-by-default-hyperframes-on-request) |
| 🧠 **Attempt memory + stall detector** | A durable run-journal (`.simplicio-loop/orchestrator/loop/journal.jsonl`) + a stall detector so the loop **changes strategy instead of oscillating**; incremental triage (`since`) reads only the delta each turn, and optional stage lineage makes retries/governance explicit | `scripts/loop_journal.py` · `selftest` 13/13 | [§ Anti-oscillation](#-attempt-memory--stall-detector-anti-oscillation) |
| 🧭 **Repo conventions** (`repo_conventions`) | **Learns the repo's own playbook** — mines git history + merged PRs + static config into `.simplicio-loop/orchestrator/conventions.json` so every new branch/commit/PR mirrors the team's established style; worktree-per-item isolation is the default | `scripts/repo_conventions.py` · `selftest` 19/19 | [§ The full flow](#️-the-full-flow--from-demand-to-delivery) |
| 🧩 **Scope reflection** (`dependency_graph`) | Maps local dependencies, reverse dependents, and related tests from the planned touched files; blocks task plans that ignore callers, sibling files, or proof points before the edit starts | `scripts/impact_audit.py` · `selftest` | [§ Tests & local checks](#-tests--local-checks-no-paid-ci) |
| 🕸️ **Flow coverage** (`endpoint_compare`) | Maps mixed front/back/service workspaces: UI actions → frontend HTTP calls → backend endpoints → service calls; blocks frontend calls with no backend endpoint and stubbed endpoints, and surfaces unclassified loose ends | `scripts/flow_audit.py` · `selftest` | [§ Tests & local checks](#-tests--local-checks-no-paid-ci) |
| 🔒 **Fail-closed safety gate** (`action_gate`) | A `PreToolUse`/git-pre-push hook that **mechanically blocks** force-push, history rewrite, mass-delete, destructive DDL, infra teardown, and secret-laden commits/pushes — Step 5 made executable, not prose | `hooks/action_gate.py` · `selftest` 15/15 | [§ Safety](#-safety-non-negotiable) |
| 🔬 **Local verification** | A test suite (worker selftests + an **e2e of the loop driver** proving evidence-gated exit) + a **claims-audit** (referenced scripts exist · counts consistent · `_bundle ≡ source`) — all local, **no paid CI** | `scripts/check.py` · `scripts/claims_audit.py` · `tests/` | [§ Tests & local checks](#-tests--local-checks-no-paid-ci) |
| ✅ **Honest savings** | The savings line is now **evidence-gated, not mandatory** — a number is shown only with a measured receipt (clamp/signatures/cache/`deterministic_edit`/ledger); never fabricated | token-economy contract | [§ Token economy](#-token-economy) |
| 🤝 **Multi-agent coordinator** (`coordinator.py`) | Decides `OWN` / `CONTINUE_OWN` / `DEFER_ACTIVE_CLAIM` / `RECLAIM_STALE` / `VERIFY_PARTIAL` per issue from live claim comments + merged PRs, so two sessions never duplicate the same work | `scripts/coordinator.py` · `selftest` 10/10 | [§ The full flow](#️-the-full-flow--from-demand-to-delivery) |
| 🕵️ **PR DoD/AC reviewer** (`pr_dod_review`) | When every issue is claimed, reviews open PRs against the 7-dimension Definition of Done + the issue's own acceptance-criteria checklist — a mechanical verdict, not a vibe-based approval | `scripts/pr_dod_review.py` · `selftest` 13/13 | [§ The full flow](#️-the-full-flow--from-demand-to-delivery) |
| 🐞 **Finding collector** (`finding_collector`) | Fingerprinted, deduplicated defect memory — the same underlying bug collapses into one record with an occurrence count, no matter how many agents/runs observe it | `scripts/finding_collector.py` · `selftest` 9/9 | [§ Official capability record](#-official-capability-record) |
| 🔔 **Release check** (`release_check`) | Compares the local canonical version against the latest GitHub release and tells the driving LLM to update instead of quietly working on a stale checkout — fail-open when offline | `scripts/release_check.py` · `selftest` 8/8 | [§ Install & use](#-install--use) |

Two loop **modes** make termination explicit: **converge** (a single hard task — ends on the
evidence-gated `<promise>` or a stall escalation) vs **drain** (a queue — ends when the source
re-query stays empty K rounds). Both still obey the universal exits (promise+evidence,
`max_iterations`, STOP).

> Loop scoring across this line of work: **7.5** (strong design, unproven) → **9** (attempt memory +
> anti-oscillation) → **9.5** (reproducible local proof) → **~10** (enforced safety + complete loop
> semantics). The verification infra now catches the project's own regressions as it grows.

---

## 🧠 The 7 skills + 5 accelerators

The orchestrator core + six satellites + five accelerators/integrations. Each satellite is
**optional** — when loaded, the orchestrator delegates to it (richer + cheaper); when absent, the
inline protocol covers 100%. Accelerators are **auto-detected** — present = used, absent = LLM
fallback.

| # | Capability | Absorbs | What it does | Token impact |
|---|---|---|---|---|
| 1 | 🔁 **simplicio-loop** | — | Unified public entrypoint: orchestrator core + hardened loop behind one command | Core + loop |
| 2 | ↩️ **simplicio-tasks** | legacy alias | Compatibility shim for older installs and saved prompts | Legacy alias |
| 3 | 🧱 **simplicio-orient** | [rtk](https://github.com/rtk-ai/rtk) + [caveman](https://github.com/JuliusBrussee/caveman) | Terminal-first execution, output-reduction catalog, tee-cache, signatures-read | L0 deterministic |
| 4 | 🔥 **simplicio-review** | [thermos](https://github.com/cursor/plugins/tree/main/thermos) | Parallel adversarial review on distinct rubrics → deduped verdict | Quality gate |
| 5 | 🗜️ **simplicio-compress** | [caveman](https://github.com/JuliusBrussee/caveman) | Output + memory compression, fail-closed `transform_guard` | 40-60% fewer |
| 6 | 🎓 **simplicio-learn** | [teaching](https://github.com/cursor/plugins/tree/main/teaching) | Post-run retrospective → durable, deduped lessons in memory | Smarter each run |
| 7 | 🧪 **simplicio-autoresearch** | Karpathy [autoresearch](https://github.com/balukosuri/Andrej-Karpathy-s-Autoresearch-As-a-Universal-Skill) + ECC `autoresearch-agent` | Evolutionary mutate/eval/keep-revert loop: yool-guardrailed caps, git-isolated branch, anti-Goodhart gate-first eval, `savings-event` receipt | Auto-optimize |
| 8 | 🧭 **Understand Anything** | [Egonex-AI](https://github.com/Egonex-AI/Understand-Anything) | Knowledge graph orient: semantic search, guided tours, dependency graph | **L0 zero tokens** |
| 9 | 📊 **agentsview** | [kenn-io](https://github.com/kenn-io/agentsview) | Session analytics, cost tracking, stalled-session discovery | **L1** SQL only |
| 10 | ⚡ **LMCache** | [LMCache](https://github.com/LMCache/LMCache) | KV cache between loop turns — 40-70% TTFT reduction on local models | GPU time ↓ |
| 11 | 🗜️ **Simplicio capture engine** | `engine/simplicio_engine.py` (native, stdlib-only) | Transparent capture proxy: forwards to the real provider, measures + deterministically compresses, writes `proxy_savings.json` | **deterministic** |
| 12 | 🎬 **video_evidence** | Playwright (default) · [hyperframes](https://github.com/heygen-com/hyperframes) (on request) | Records the **real session** as moving proof of a UI change (Playwright); renders a **deterministic captioned MP4** explainer with hyperframes when the video IS the deliverable | Evidence producer |

Each skill lives under [`.claude/skills/`](.claude/skills); each accelerator has a reference doc
under `.claude/skills/simplicio-loop/references/` (the video producer:
[`video-evidence.md`](.claude/skills/simplicio-loop/references/video-evidence.md), worker
[`scripts/video_evidence.py`](scripts/video_evidence.py)).

---

## 📡 Source adapters

The orchestrator discovers work from any source via pluggable adapters. Each exposes six verbs:
`list_ready`, `get_details`, `claim`, `update_status`, `attach_evidence`, `close`.

| Source | Adapter | Purpose |
|---|---|---|
| GitHub Issues/PRs | `gh` CLI (native) | Primary work-item source; canonical lifecycle comments ship today |
| Azure DevOps | `az boards` / host connector | Azure Boards discovery; stage comments only after a real connected-capability probe |
| Jira | host connector | Jira discovery; stage comments only when connected |
| Asana | host connector | Asana discovery; stage comments only when connected |
| Trello | host connector | Trello discovery; stage comments only when connected |
| ClickUp / Linear / Notion | host connector | Board/project discovery; no stage-comment claim without a certified adapter |
| **agentsview sessions** | `scripts/agentsview_adapter.py` | Stalled session recovery + cost observability |
| Local files / CI queue | filesystem / CI API | Internal work tracking |

See each adapter's reference doc under `.claude/skills/simplicio-loop/references/`.

---

## 🌐 15 runtimes, one protocol — 3 guaranteed + 12 best-effort

One universal skill core + one set of hooks drives every runtime. An adapter is thin: it tells a
runtime *where to load the skills* and *how to arm the loop*. **The skill names no runtime; the
runtime detects the skill.** There is no Runtime/MCP backend in this stack — every host runs the
same standalone loop against `simplicio-mapper` and `simplicio-dev-cli`.

### Tier 1 — Guaranteed (gated on every commit)

| Runtime | Skill load | Loop drive |
|---|---|---|
| **Claude Code** | `.claude/skills/` + plugin | `Stop` hook |
| **Codex** | `AGENTS.md` | self-paced |
| **Cursor** | `.cursor-plugin/` | `stop`+`afterAgentResponse` |

### Tier 2 — Best-effort (contributions welcome, no gate)

| Runtime | Skill load | Loop drive |
|---|---|---|
| **VS Code (Copilot)** | `copilot-instructions.md` | tasks |
| **Antigravity** | rules / `AGENTS.md` | self-paced |
| **Kiro** | `.kiro/steering/` | specs |
| **OpenCode** | `AGENTS.md` | self-paced |
| **Gemini** (CLI/Code Assist) | `GEMINI.md` | self-paced |
| **Kimi** | inlined conventions | self-paced |
| **Qwen** (Code/CLI) | `AGENTS.md`-equivalent | self-paced |
| **DeepSeek** | inlined conventions | self-paced |
| **Aider** | `CONVENTIONS.md` | self-paced |
| **Simplicio Agent** *(formerly Hermes)* | native recall | native loop |
| **OpenClaw** | plugin SDK | native scheduler |
| **Orca** | via inner agent + skills registry | inner hook / scheduled automations |

The promise: **same protocol, same gates, same safety on all 15 — Tier 1 verified mechanically,
Tier 2 best-effort.** `orient_clamp.py` (token economy) works on every runtime with zero wiring. See
[`adapters/MATRIX.md`](adapters/MATRIX.md) for the promotion/demotion rules.

---

## 🗺️ The full flow — from demand to delivery

Every layer the orchestrator acts on, in order — from reading the demand (issues, tasks, assigns)
to delivering merged, evidenced work, then looping 24/7 for more.

```mermaid
flowchart LR
  IN["Intent: issue · task · queue"] --> CONTRACT["1 · Freeze task contract"]
  CONTRACT --> MAP["2 · Map source + normalize"]
  MAP --> COORD{"3 · Coordinator decide (multi-session)"}
  COORD -->|"OWN / CONTINUE_OWN / RECLAIM_STALE"| PLAN["4 · Dependency DAG + acceptance criteria"]
  COORD -->|"DEFER_ACTIVE_CLAIM (all issues)"| REVIEW["PR DoD/AC review — never idle"]
  COORD -->|"VERIFY_PARTIAL"| RECHECK["Verify what's actually merged before continuing"]
  RECHECK --> PLAN
  REVIEW --> IN
  PLAN --> ROUTE{"5 · Ready task?"}
  ROUTE -->|"solo / small"| SOLO["Targeted lane"]
  ROUTE -->|"parallel / medium+"| FAN["Bounded fan-out"]
  FAN --> A["Isolated worktree A"]
  FAN --> B["Isolated worktree B"]
  FAN --> C["Isolated worktree C"]
  SOLO --> VERIFY["6 · Test + impact/flow evidence"]
  A --> VERIFY
  B --> VERIFY
  C --> VERIFY
  VERIFY --> RECEIPT["Watcher challenge + evidence receipt"]
  RECEIPT --> ORACLE{"7 · Completion oracle"}
  ORACLE -->|"pending / blocked"| RECOVER["Journal · checkpoint · rollback · backlog-only maintenance"]
  RECOVER --> PLAN
  ORACLE -->|"verified / measured"| DELIVER["8 · Source sync · PR · merge"]
  DELIVER --> CLEANUP["Post-merge worktree/branch cleanup"]
  CLEANUP --> MEMORY["9 · Ledger · wiki · durable attempt memory"]
  MEMORY --> WATCH["10 · Re-feed · watcher · STOP path"]
  WATCH -->|"new work"| IN
```

**Multi-agent coordination (new in v3.38.0).** Step 3 is the mechanical answer to "is a sibling
session already on this?" — `scripts/coordinator.py` decides from live GitHub state, never a guess.
When every candidate issue comes back deferred, the loop doesn't idle: it reviews open PRs against
the DoD + acceptance criteria (`scripts/pr_dod_review.py`) instead. Full detail:
[`references/multi-agent-coordination.md`](.claude/skills/simplicio-loop/references/multi-agent-coordination.md).

**Planning gate (issue #284).** Steps 1–3 above are not just guidance — `simplicio_loop/planning_gate.py`
makes them a fail-closed mechanical barrier between "claimed" and "mutating": every real
`arm_run()` self-builds a `planning-receipt.json` binding run/attempt/contract/plan/lease/fence
(and, on a GitHub source, the source-snapshot hash) into a single-use `mutation_authority` token,
and `execute_operator()`/`execute_operator_batch()` refuse to run without a matching one. Both
halves of the gate (`SIMPLICIO_REQUIRE_MUTATION_AUTHORITY`, `SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT`)
are mandatory by default — see `.claude/skills/simplicio-loop/references/planning-gate.md` and
`docs/adr/0004-planning-gate-rollout.md`.

---


## 🔌 The 50 extension points

These are the named places a host can bind a native capability. The full contract,
including the two required bindings (Mapper on `orient`, Dev CLI on `deterministic_edit`),
is [`.claude/skills/simplicio-loop/references/extension-points.md`](.claude/skills/simplicio-loop/references/extension-points.md).
Every delivery run still closes through the same flow: orient, prepare, one edit plan per
task, `tick` for one task or `wave` for two or more, then verify.

`orient` · `pattern_match` · `recall` · `normalize` · `deterministic_edit` · `autoscale` ·
`plan` · `execute` · `issue_factory` · `claim` · `worktree` · `diagnostics` · `validate` ·
`pr` · `watcher` · `savings_ledger` · `capability_rank` · `compress` · `trajectory` ·
`learn` · `human_gate` · `shell_exec` · `retry` · `convergence_policy` · `status` ·
`security` · `intake` · `dependency_graph` · `durable_workflow` · `work_queue` ·
`resource_governor` · `delivery_gate` · `action_gate` · `repo_conventions` · `pr_template` ·
`reuse_precedent` · `sibling_search` · `source_adapter` · `prompt_budget` · `model_route` ·
`model_preflight` · `toolchain_detect` · `checkpoint_restore` · `notify` · `endpoint_compare` ·
`web_verify` · `video_evidence` · `web_research` · `transform_guard` · `judge`

## 🔁 The loop

The **Evidence-Gated Loop** is the core mechanism. It re-feeds the same goal each turn so the
agent sees its own prior work. Exit is ONLY via:

1. **Evidence-gated `<promise>`** — the turn that emits the promise MUST also carry concrete
   proof (passing test, merged PR, closed-item re-query). A promise with no evidence = ignored.
2. **`max_iterations` cap** — hard safety backstop
3. **STOP signal** — `.simplicio-loop/orchestrator/STOP` or channel command

Between turns, LMCache (when available) caches the KV state so re-feed costs near-zero prefill.

### 🧠 Attempt memory + stall detector (anti-oscillation)

A re-feed loop that remembers nothing oscillates — try X, fail, try X again — until the cap burns.
simplicio-loop keeps a **durable run-journal** (`.simplicio-loop/orchestrator/loop/journal.jsonl`, append-only:
`iteration · action · hypothesis · gate · error-fingerprint`, plus optional lineage like
`execution_state · stage_id · validator · decision · retry_count`) and a **stall detector**
([`scripts/loop_journal.py`](scripts/loop_journal.py), deterministic + model-free):

- **Error fingerprint** — the failing gate output is reduced to a stable hash with line numbers,
  paths, hex/uuids, timestamps and durations normalized away, so the *same* bug is recognized
  across turns even when the incidental text differs.
- **Stall = K identical-fingerprint failures in a row** (default K=3). A changing fingerprint means
  the loop is moving (PROGRESS); the same one K times means it is spinning (STALLED).
- On STALLED the loop does **not** re-feed the same goal — it names the **dead-end actions** to
  avoid, then **switches strategy** or **escalates to the human gate** with the fingerprint.
- `loop_journal.py resume` is read at the top of every turn, so a fresh process continues without
  re-deriving prior attempts (real resume) and never retries a known dead-end.
- When the loop is doing extraction, validation, or governed retries, `record` can also stamp
  `--execution-state`, `--stage-id`, `--source-artifact`, `--chunk-id`, `--validator`,
  `--decision`, `--retry-count`, `--blocked-reason`, and `--next-action`, so the next turn knows
  not just *what* failed, but *where in the flow* it failed.

```bash
loop_journal.py resume                       # what was tried + dead-ends to avoid
loop_journal.py record --iteration N --action "…" --gate fail --gate-output test.log \
  --execution-state planned --stage-id validate --validator pytest --decision retry
loop_journal.py stall --k 3 --exit-code      # PROGRESS → re-feed · STALLED → switch/escalate
```

### 📦 Exported contract for other runtimes — `simplicio.loop-execution/v1`

`simplicio-loop` is the reference implementation of this converge/drain discipline. So that
`simplicio-runtime` (or any other consumer) reuses this semantics instead of inventing a second,
incompatible execution contract (#115), the discipline is published as versioned, testable fixtures
under [`contracts/loop-execution/v1/`](contracts/loop-execution/v1/SCHEMA.md): converge success,
stall + escalation, drain with empty rounds, the STOP path, evidence-gated completion, and the
minimal append-only journal shape. `python3 scripts/check_loop_contract.py` (wired into
`scripts/check.py`) validates every fixture against the REAL producers (`hooks/loop_stop.py`,
`scripts/loop_journal.py`) by actually running them in an isolated temp directory — not a
re-description of them — so a runtime implementing its own executor can diff its behavior against
each fixture's `expected.json` instead of re-deriving the rules from prose. See
[`contracts/loop-execution/v1/SCHEMA.md`](contracts/loop-execution/v1/SCHEMA.md) for the full
contract and how to consume it.

---

## 🎬 Video evidence — Playwright by default, hyperframes on request

The loop produces **demo videos** as proof a change works — **two engines**, one `video_evidence`
extension point (worker [`scripts/video_evidence.py`](scripts/video_evidence.py), contract
[`references/video-evidence.md`](.claude/skills/simplicio-loop/references/video-evidence.md)):

1. **Default — the normal evidence flow uses Playwright.** After a UI change, `video_evidence`
   records the **real browser session** driving the screen (Playwright native video → `.webm`, →
   `.mp4` with FFmpeg) — the strongest "works, not just compiles" receipt (Step 4b) and a valid
   evidence-gated `<promise>`.

   ```bash
   python3 scripts/video_evidence.py verify --url http://localhost:3000/login \
       --name login-demo --expect "Sign in" --issue 42 [--upload --pr 42]
   ```

2. **On request — a personalized explainer uses hyperframes.** When the deliverable IS a video
   ("make an explainer video of screen X"), the orchestrator renders a **deterministic, captioned
   slideshow** of the `web_verify` screenshots with
   [**hyperframes**](https://github.com/heygen-com/hyperframes) (by HeyGen — "same input, same
   frames, same output", CI-reproducible, no API keys, local render via headless Chrome + FFmpeg).

   ```text
   /simplicio-loop make an explainer video of the system login screen
   → detect: video-creation request → web_verify captures the screens
   → video_evidence verify --engine hyperframes → deterministic MP4 → attached to the PR
   ```

Either engine: a video that never recorded/rendered yields **BLOCKED**, never a fake pass. Evidence
is always a **file path + boolean verdict** — never video bytes in context (token economy).

---

## 📊 Token economy

| Technique | Savings |
|---|---|
| `deterministic_edit` (L0) | 100% of edit tokens (file written mechanically, never by LLM) |
| Terminal-first execution | Facts from shell, not LLM hallucination |
| Output-reduction catalog | Caps per command type (`CAP_ERRORS=20`, `CAP_WARNINGS=10`, `CAP_LIST=20`) — `orient_clamp.py` |
| Tee+CCR cache on failure | Never re-run a failed command — read the cached output |
| Signatures-only reads | `simplicio-cli signatures <file>` — 870-line file → 65 lines (**93% saved**), bodies stripped |
| `simplicio-compress` | Terse prose + one-time memory compaction |
| `orient_clamp.py` | Clamp + tee on every shell command, zero wiring |
| Native response cache | repeated deterministic (temp=0) request → served from cache, skips the LLM call (**100% on hit**) — `simplicio-cli cache`, on by default (`SIMPLICIO_CACHE=0` to disable) |
| **Simplicio capture proxy + MCP** | 60-95% fewer tokens on tool outputs via a transparent compression daemon — **unverified** (no receipt snapshot exists) |

Savings only count on a verified-correct outcome. Baseline = the cheapest sensible non-orchestrated
path to the same result. **Savings reporting is evidence-gated, not mandatory:** a savings figure is
shown only when a turn actually ran an economy-producing command and the number traces to a
measured receipt (clamp tee, signatures-read, cache hit, `deterministic_edit`, `savings_ledger`).
No measured economy → no savings line; the orchestrator never fabricates a baseline or a percentage.
**Most quantitative savings figures in this README remain UNVERIFIED** (no receipt snapshot in
`.simplicio-loop/orchestrator/savings/snapshots.jsonl`) — except the **measured comparative bench**
below. See `references/token-economy.md` and `scripts/claims_manifest.py`.

### Measured benchmark (issue #17)

**Task:** [simplicio-agent#17](https://github.com/simpletibr/simplicio-agent/issues/17) — Asolaria
HRM + N-Nest-Prime, **P0 slice completed in both arms**: Brown-Hilbert `port.port.port` addressing +
Agent/Watcher corrective gate (`agent/asolaria_nest_contract.py` + unit tests, both arms green).

**Arms (same machine, Windows):**

| Arm | How work was done |
|---|---|
| **Without loop** | Ad-hoc `gh` + `rg` + **full-file reads** of candidate modules (LLM-style survey) |
| **With loop** | STRICT env → `preflight --strict` → `simplicio-mapper` scan/inspect/handoff → operator doctor → `arm_drain_prism` → **signatures-only** reads |

**Stack measured:** `simplicio-loop 3.38.9` · `mapper 0.26.0` · `cli 0.18.0` (historical run; that stack still carried an optional accelerator operator that has since been removed).

| Metric | Without loop | With loop | Ratio (with/without) |
|---|---:|---:|---:|
| **Wall time** | 2.72 s | 13.20 s | **4.86× slower** (operator startup) |
| **Est. tokens** *(context_bytes ÷ 4)* | ~156 576 | **~15 246** | **0.097×** |
| **Token savings** | — | **~90.3% fewer** est. tokens | — |
| **Context bytes** | 626 303 | 60 982 | 0.097× |
| **Shell/tool commands** | 16 | 12 | — |
| **Operator calls** | 0 | 6 | preflight + mapper×3 + doctor + arm |
| **Tests success** | true | true | same deliverable |

**Phase times (seconds):**

| Phase | Without | With |
|---|---:|---:|
| preflight | — | 2.78 |
| survey | 1.50 | 7.31 |
| plan / arm | ~0 | 1.99 |
| implement | ~0 | ~0 |
| test | 1.21 | 1.13 |

**How to read this:** the loop **cuts intake context/tokens hard** (good for multi-turn LLM cost).
Wall-clock can be **higher on a cold operator run** (preflight + mapper). Over a long session the
token reduction usually dominates billed cost; wall-clock amortizes when the map/snapshot is warm.

**Caveats (honest):**

- “Tokens” here are **estimated** as `context_bytes / 4`, not provider-billed usage.
- Implementation code was the **same P0 contract** in both arms so the comparison isolates
  **survey/orchestration**, not two different implementations of the full epic.
- Not a substitute for the Token Monitor (proxy-routed measurement).

**Artifacts:** PDF report [`docs/evidence/issue17_loop_vs_baseline.pdf`](docs/evidence/issue17_loop_vs_baseline.pdf) ·
raw metrics in the bench scratch (re-run with the harness under `docs/evidence/` notes).

### 🔎 Running `simplicio-loop`: economy vs measurement (per runtime)

Two different things happen when you call **`simplicio-loop`**, and they behave differently per runtime:

- **Economy** — compression, output clamps, signatures-only reads, `deterministic_edit` — applies **every
  time the skill runs and loads `simplicio-orient` / `simplicio-compress`, on any runtime.** It is the
  skill's behavior plus the hooks (strongest where hooks exist: `orient_clamp.py` auto-clamps on Claude and
  Cursor; elsewhere it is instruction-driven).
- **Measurement** — the Token Monitor's live numbers — only counts traffic that flows **through the
  capture proxy.**

| Runtime | Economy (skill) | Measurement (monitor) |
|---|---|---|
| **Simplicio Agent** | ✓ | ✓ **automatic** — already routed through the proxy (`base_url → :8788`) |
| **Claude** | ✓ (skill + hooks) | ✗ by default — Claude talks to `api.anthropic.com` directly; measured only once routed (`simplicio-cli wrap claude`, or `ANTHROPIC_BASE_URL → http://127.0.0.1:8788`) |
| **Codex** | ✓ (skill) | ✗ by default — `simplicio-cli init codex` adds the MCP tools but does not route LLM traffic; measured with `simplicio-cli wrap codex` or an OpenAI base-url pointing at the proxy |

So: the **savings happen on every runtime**; the **monitor tallies them automatically on Simplicio Agent**, and on
Claude/Codex after a **one-time routing step** (`simplicio-cli wrap …` / base-url → `:8788`). Without routing,
the economy still applies — the monitor just won't count those tokens. `scripts/simplicio-economy.sh wire`
does this routing for OpenAI-compatible clients at install time.

### 📈 Simplicio Token Monitor

A view of the savings you open when you want — only the capture is always-on:

- **Capture proxy** — **always-on** (the one auto-started service; the wired clients need it
  reachable). It silently captures + measures Claude + Codex + Simplicio Agent in the background.
- **Web dashboard** — `http://127.0.0.1:9090` — real-time token chart, savings gauge, the LLMs/runtimes
  and providers we intercept, a live proxy log. **Opens once on the first install**
  so you see it works, then it's **on-demand** — re-open it any of these ways:
  - `simplicio-loop dashboard` — works from anywhere after the pip install (no repo path needed);
    `simplicio-loop dashboard --stop` to close, `--no-browser` to just start the server.
  - `bash scripts/simplicio-economy.sh monitor` (repo checkout) · `… monitor stop` to close.
  - just **ask the agent** — "open the token dashboard".
- **Menu-bar / tray widget** — live tokens saved in the system tray (macOS rumps · Windows/Linux pystray).
  **On-demand:** `bash scripts/simplicio-economy.sh tray` · `… tray stop`.

Install auto-starts **only the capture proxy** (macOS launchd · Linux systemd · Windows Startup). The
dashboard opens **once** on a fresh install (marker-guarded — a re-install/update never reopens it; opt
out with `SIMPLICIO_NO_DASHBOARD=1`), and the tray never opens by itself — nothing is forced to stay
open. Manage the stack: `scripts/simplicio-economy.sh {status|up|monitor|tray|wire}`. After install,
capture runs **without invoking the loop** — see `references/token-capture.md`.

### 🧪 e2e savings demo — one task, four hops, a receipt at every one

`scripts/e2e_demo.py` is the capstone acceptance test for this program: it drives ONE task through
**MAP → RECALL → EDIT → VERIFY** and writes a `simplicio.savings-event/v1`-shaped receipt per hop,
never a bare percentage.

```bash
python3 scripts/e2e_demo.py run         # live: real simplicio-mapper + task_anchor.py calls
python3 scripts/e2e_demo.py selftest    # offline: proves the receipt/report math, no external tools
```

`run` writes `.simplicio-loop/orchestrator/savings/e2e-demo.md` (the report), `e2e-demo-events.jsonl` (one receipt
per hop), and feeds the same `snapshots.jsonl` store `savings_harness.py score` and
`billing_aggregator.py collect`/`meter` already read — so this demo's numbers roll up into the
existing aggregation with no new code. MAP and VERIFY call real live tools
(`simplicio-mapper handoff`, `task_anchor.py check --format json|toon`); RECALL and EDIT
honestly label a local stand-in where an upstream dependency (mapper's native `--for-llm toon`,
dev-cli's `SIMPLICIO_PROMPT_TOON`) isn't shipped yet — every hop's `note` says exactly which.
`selftest` is fully offline (no subprocess to `simplicio-mapper`/`simplicio-cli`, no network, no
API key) and is what `scripts/check.py` runs.

### 🛠️ The capture engine — one native module, every command

[`engine/simplicio_engine.py`](engine/simplicio_engine.py) is the native Simplicio capture engine
(stdlib-only, fail-open) — a **native, transparent capture proxy + deterministic compression engine
with no external dependency**. Run any
command via the [`scripts/simplicio-engine`](scripts/simplicio-engine) wrapper (e.g. `simplicio-engine doctor`):

| Command | What it does |
|---|---|
| `proxy` | the transparent capture proxy — routes each model to its **real** provider, compresses + measures + caches (no model swap) |
| `doctor` | proxy reachability + lifetime savings |
| `cache` | native response cache (`stats`/`clear`) — a repeated deterministic request is served from cache, skipping the LLM call |
| `signatures` | signatures-only view of a source file (bodies stripped, ~93% fewer tokens to read code) |
| `semantic` | reversible extractive (semantic-lite) compression |
| `detect` | content-type detection + smart per-block routing |
| `rag` | TF-IDF (or `--ml` embedding) retrieval over the CCR memory store |
| `memory` | CCR compress-cache-retrieve store (`remember`/`recall`/`forget`/`list`/`stats`) |
| `mcp` | native stdio MCP server (compress / retrieve / stats tools) |
| `init` / `wrap` | register Simplicio into a client (Claude / Codex / Copilot / OpenClaw) · run a client with capture routing |
| `report` / `audit` / `capture` / `evals` | savings report · audit a tree for compression opportunity · dry-run a request · compression regression gate |

---

## 🏛️ Design pillars (in detail)

Four mechanisms sustain the orchestration power:

| Pillar | Focus | Lives in |
|---|---|---|
| **DAG + pipeline** | parallelism by dependency, staged per item | `references/orchestration.md` (Step 3 pool + pipeline) |
| **Isolation by worktree** | parallel edits without corrupting the tree, merge-gated | `references/orchestration.md` |
| **Adversarial verify** | panel of skeptics before "delivered" | `references/quality-safety-delivery.md` · skill `simplicio-review` |
| **Bounded loop cap** | anti-infinite-loop, evidence-gated exit | `references/standing-loop-247.md` · skill `simplicio-loop` |

---

## 🚀 Install & use

**Fast path: standalone skill install.** If you only want the `simplicio-loop` skill bundle, this
is enough — **no native runtime dependency is required**:

```bash
pip install simplicio-loop
simplicio-loop install            # current project
simplicio-loop install --global   # user-wide
```

That installs the skills + hooks only. If your runtime can bind native helpers, they are an
**optional speed-up**, not a prerequisite. `pip install simplicio-loop` is one wheel: mapper and
dev-cli are built into it, so it also provides the two required operators, `simplicio-mapper`
(survey) and `simplicio-dev-cli` (mutation) — there is no separate `simplicio-mapper` /
`simplicio-cli` package to install.

**Full-stack path: repo installer.** Use this when you also want the broader Simplicio local stack
(operators, capture proxy, dashboards, services, runtime wiring):

```bash
git clone https://github.com/simpletibr/simplicio-loop
cd simplicio-loop

# install for your runtime (omit <runtime> to auto-detect)
bash scripts/install.sh <runtime> [--global] [--minimal]        # macOS / Linux
pwsh scripts/install.ps1 <runtime> [-Global]                    # Windows
# <runtime> ∈ claude codex vscode cursor antigravity kiro opencode gemini aider simplicio_agent openclaw
#            (hermes still accepted as a legacy alias for simplicio_agent)
```

**The repo installer is full-stack by default — it installs everything.** One command sets up the whole stack:
the operators (`simplicio-mapper` and `simplicio-dev-cli`, built into the single `simplicio-loop`
wheel and installed with it, auto-handling PEP 668 / externally-managed Python and symlinking
the binaries onto `PATH`), the **full Python stack** (the package itself),
the **7 skills + hooks** with the loop's Stop hook wired, and the **always-on capture proxy**
with Claude + Codex + Simplicio Agent **routed and measured** in the background. The **dashboard opens once** on a
fresh install, then it's on-demand (`simplicio-loop dashboard` / `simplicio-economy.sh monitor`); the
**menu-bar tray never opens by itself** — nothing is forced to stay open.
Pass **`--minimal`** only for headless/CI to skip the heavy deps + the machine services. Verify any time:
`bash scripts/simplicio-economy.sh status`.

### Update

```bash
python3 scripts/release_check.py check   # is a newer release published? — never auto-updates
bash scripts/update.sh [<runtime>]       # git pull → reinstall skills/hooks/operators → restart services
simplicio-loop update                    # pip-installed: latest GitHub release (--check: report only, --force: reinstall)
```

`simplicio-loop update` installs the latest GitHub release of `simpletibr/simplicio-loop` and
refreshes the global skills. Because mapper and dev-cli are bundled in the wheel, it first removes
any pre-monorepo standalone `simplicio-cli` / `simplicio-mapper` distributions (they own the same
files); an editable checkout install is told to `git pull` and re-run `scripts/dev_install.sh`.

`release_check.py` compares the local canonical version (`pyproject.toml`) against the latest
GitHub release tag and prints an explicit `MEASURED|release-check: a newer release is available …`
line (exit 10) when you're behind — the agent/LLM driving `simplicio-loop` is meant to read that
line and run the update itself, not silently keep working on a stale checkout. It never applies the
update — a detected-but-declined update is never auto-installed — and it fails open (`UNVERIFIED|`,
exit 0) when `gh`/network is unavailable, so an offline dev environment never looks broken. `doctor`
(below) runs the same check as one OPTIONAL line in its report.

`update.sh` stashes local edits, fast-forwards `main`, reinstalls from the fresh source, restarts the
launchd/systemd services so they run the new code, and prints the live stack + savings.

## 🧭 CLI command map — what each command does

### Required Mapper context and automatic machine capacity

Every Loop execution workflow requires **Simplicio Mapper**, including standalone,
sequential and Prism/wave execution. Prepare context centrally and
bind workers to its current generation and digest.
Runtime remains optional for ordinary orchestration. Missing or stale Mapper
context blocks work until central preparation succeeds.

The intended worker default is automatic physical admission from available machine
capacity, preserving foreground responsiveness. The source changes remove fixed
defaults in batch/tasks/fan-out entrypoints; validation is still in progress and
these edits are not part of the installed 3.43.10 release yet.

Mapper context reuse does not itself prove a provider cache hit. Report token and
cost savings only from attributable provider usage and passing quality gates.
The fastest/cheapest production route is **not yet established**. See the
[ten-task benchmark protocol, command sequence and evidence status](docs/QUEUE_BENCHMARK_PROTOCOL.md)
before using historical synthetic scheduler measurements as a recommendation.

The main `simplicio-loop` entry point is the user-facing control surface for planning, executing, verifying, and delivering work. Use the most specific `--help` for the exact options available in the installed version.

**Standalone by design.** Runtime is optional: without it, Loop uses its own scheduler/hooks plus the Mapper and Dev CLI operators. When Runtime is available, it adds governed activation, physical admission, gates, receipts, and reconciliation; it does not replace the Loop.

### Zero-config execution

The default entry point is `simplicio-loop "<task>"` (short for `simplicio-loop turbo --repo . --task "<task>"`):
one entry point for one task or many. It needs no provider and no API key: the model that invoked the skill
plans and `simplicio-dev-cli` edits, in exactly two commands. Command 1 surveys with Mapper and prints a
`needs_plan` request (the task, the map slice, the current text of the files it names, the plan format and the
exact apply command). Command 2 is that apply command: the model puts its JSON find/replace plan in the
heredoc body, `simplicio-dev-cli` applies it and `--verify` runs your tests (`status`, `applied`, `failed` with
the dev-cli reason and a file excerpt, `verify`). Headless automation can ask OpenRouter for the plan instead;
see [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md).

```bash
simplicio-loop "Create pricing.py with order_total and fix the two bugs in inventory.py" --verify "python -m pytest -q"
# then run the printed command once, with the plan as its heredoc body (the plan can also come from a file: --apply plan.json):
simplicio-loop turbo --repo . --apply - --verify "python -m pytest -q" <<'PLAN'
{"operations":[{"path":"pricing.py","find":"","replace":"..."}]}
PLAN
```

Governed runs from a `tasks.md` (queues, batches, Prism) use the `wave` flow (with automatic reconciliation barriers):

```bash
# Preparar / Armar run a partir de especificação markdown:
simplicio-loop prepare --task task.md --repo .

# Executar via fluxo wave padrão (recomendado):
simplicio-loop wave <run_id>

# Uma tarefa usa tick; duas ou mais usam wave. As duas fecham com verify:
simplicio-loop tick <run_id> --repo . --task-index 1
simplicio-loop verify <run_id> --repo .
```

> **Aviso de Descontinuação do `run`**: O comando `simplicio-loop run` foi descontinuado e excluído da interface pública. Caso seja invocado (`simplicio-loop run --task task.md` ou `simplicio-loop run <run_id>`), o comando é automaticamente interceptado e redirecionado para o fluxo padrão `simplicio-loop wave`, garantindo execução com barreira de integridade e a máxima velocidade.

> **Operador Obrigatório**: O ecossistema opera com `simplicio-mapper` estritamente obrigatório. O `simplicio-mapper` garante a integridade estrutural do repositório e o prefix caching determinístico da LLM.

| Area | Commands | What they do |
|---|---|---|
| Install and utilities | `install`, `dashboard`, `learn` | Install the bundled skills/hooks; open or stop the token-monitor dashboard; derive and persist a retrospective from completed runs. |
| Intake and planning | `task`, `prototype`, `plan`, `orient` | Validate/preview task contracts; route prototype planning; compile Markdown into a frozen contract; build bounded Mapper context and an orientation receipt. |
| Execution | `turbo`, `wave`, `prism`, `batch`, `tick` | Run tasks through the default engine (`turbo`: Mapper survey, model plan, Dev CLI apply, `--verify`); dispatch ready tasks through governed wave barriers (`wave`, default flow); execute through isolated worktrees (`prism`); continuous background dispatch (`batch`); step-by-step single-task execution (`tick`). Exactly one prepared task executes with `tick`; two or more execute with `wave`. Both close with `verify`. *(Nota: `run` foi descontinuado e redireciona para `wave`)*. |
| Run lifecycle | `status`, `progress`, `resume`, `cancel`, `verify`, `oracle`, `checkpoint` | Inspect a run; render progress as text/JSON/Markdown/ANSI; resume or cancel non-terminal work; run independent watcher/delivery gates; evaluate completion/parity; manage candidate checkpoints. |
| Repository and operators | `preflight`, `map`, `inspect`, `doctor`, `stack`, `extensions`, `retrieve` | Check Mapper/Dev CLI/Runtime readiness; inspect map-service receipts; inspect MapperStore capabilities; diagnose stack/source/resource/storage; lock or verify installed components; verify extension handshakes; retrieve tee-cache results. |
| Queues and coordination | `queue`, `drain`, `agent-slots`, `generation-broker`, `ledger`, `hub-drain-plan`, `hub-drain-admit` | Operate the durable queue; evaluate or persist queue-drain receipts; inspect/reclaim Loop capacity; reconcile generation bindings; replay/validate the operational ledger; plan or admit GitHub drain work. |
| Delivery and source control | `deliver`, `decide`, `sync-source`, `findings`, `maintenance-deferred`, `defer-maintenance` | Reconcile delivery with source evidence; apply a human decision and invalidate dependent artifacts; requery external source state; list/report/reconcile/diagnose/import findings; record deferred maintenance. `defer-maintenance` is the alias form. |
| Economy, safety, and deployment | `economy`, `ecc`, `deploy` | Inspect/print/apply the economy-parallel environment; verify ECC provenance and safety policy; plan a gated deployment (`--apply` is explicit). |

### Guia de Decisão para a LLM / Agentes: Qual fluxo escolher?

Para garantir os melhores resultados de velocidade, economia e confiabilidade:

| Cenário / Demanda | Fluxo Recomendado | Comando | Por que escolher? |
|---|---|---|---|
| **Qualquer tarefa (padrão)** | `turbo` | `simplicio-loop "…" --verify "<testes>"` | **Padrão**: o motor medido no benchmark. O Mapper lê o repositório uma vez, o modelo que invocou a skill escreve o plano e o Dev CLI aplica. Sem provedor e sem chave de API. |
| **1 tarefa em run governada (`tasks.md`)** | o mesmo fluxo de entrega | `simplicio-loop prepare` → `tick <run_id> --task-index 1` → `verify <run_id>` | Uma tarefa fica no checkout compartilhado. O fechamento continua sendo o `verify`. |
| **Multi-tarefas Padrão (2 a 30+ tarefas)** | `wave` *(Padrão)* | `simplicio-loop wave <run_id>` | **Máxima Velocidade e Confiabilidade**: Despacha ondas concorrentes com barreiras de reconciliação de estado entre cada onda. Evita race conditions em arquivos compartilhados e aproveita 96%+ de cache hit. |
| **Alta Concorrência em Árvores Isoladas** | `prism` | `simplicio-loop prism <run_id> --batch-size 10` | **Isolamento Total**: Worktrees Git isoladas para tarefas independentes que alteram partes distintas do código sem colisão. |
| **Fila Contínua de Tarefas** | `batch` | `simplicio-loop batch <run_id>` | **Processamento em Massa**: Mantém workers ocupados continuamente processando tarefas prontas da fila até o esgotamento. |
| **Depuração Passo a Passo / Inspeção** | `tick` | `simplicio-loop tick <run_id> --task-index N` | **Controle Fino**: Executa exatamente uma tarefa por vez com controle cirúrgico de inspeção e validação pré/pós. |

### Dinâmica de Prompt Caching da LLM: Por que o cache aumenta em lotes maiores (10 vs 20 vs 30 tarefas)?

Em tarefas orquestradas pelo `simplicio-loop` com `simplicio-mapper` obrigatório, o prefixo de contexto (árvore do projeto, AST, regras e instruções do sistema) é fixo e canônico. Os provedores de LLM (como DeepSeek v4.1 Flash via OpenRouter ou Claude/Anthropic) aplicam **KV Cache Prefix Matching**:

1. **Amortização do Cold-Start**:
   - **Na 1ª tarefa (Cold-Start)**: O prefixo é enviado e processado pela primeira vez. A LLM grava o KV-cache (`cache_creation` ou cache miss).
   - **Da 2ª à 30ª tarefa (Cache Hit)**: O prefixo idêntico é encontrado no cache do provedor (dentro da janela de TTL de 5 a 10 minutos). Apenas o delta da tarefa é processado como novos tokens de entrada.
2. **Evolução do Hit Rate Conforme o Volume de Tarefas**:
   - **10 tarefas**: 1 cold-start + 9 cache hits = **90.0% de reaproveitamento de cache**.
   - **20 tarefas**: 1 cold-start + 19 cache hits = **95.0% de reaproveitamento de cache**.
   - **30 tarefas**: 1 cold-start + 29 cache hits = **96.7% de reaproveitamento de cache**.
3. **Impacto no Custo e na Latência**:
   - O custo de tokens de entrada em cache hit cai em até **90%** (de \$0.14/M para \$0.014/M de tokens no DeepSeek v4.1 Flash).
   - A latência por tarefa (Time to First Token - TTFT) despenca drasticamente, pois a LLM não recalcula os embeddings nem a atenção de todo o repositório a cada iteração.
   - Portanto, a percepção de que *"o cache vai aumentando a cada rodada de 30 tarefas"* é matematicamente real e um benefício direto da arquitetura do `simplicio-mapper`.

### Candidate governed flow for 10 tasks — not yet a measured winner

Ten tasks are above the three-task direct-parallel threshold, so the Loop routes them through a Prism wave: isolated worktrees, leases, a wave barrier, and serialized writes. Execution is always standalone — there is no Runtime/MCP backend in this stack.

```bash
# 1. Inspect the profile before applying environment changes
simplicio-loop economy status --json

# 2. Block until the required operators and strict mutation policy are ready
simplicio-loop preflight --strict --json

# 3. Survey and enrich context through the bound operators
simplicio-mapper scan . --sync --json
simplicio-mapper inspect . --json
simplicio-mapper handoff . --task-file task.md --execution-context --json

# 4. Arm the drain scratchpad; this does NOT start workers
# The CLI resolves slots=0 via its machine-capacity recommendation.
python3 scripts/arm_drain_prism.py --repo . --slots 0 --batch-size 10 --json

# 5. Each task follows claim → implement → focused gate → evidence → PR/merge
#    The next wave starts only after reconcile-before-next.
```

Do not interpret ten logical tasks as ten unrestricted processes: physical CPU/RAM/backpressure limits are still enforced, and writes are serialized by path. For only one to three tasks, use direct parallelism instead of Prism.

### Where Prism fits

The public `simplicio-loop prism` and `simplicio-loop wave` commands dispatch through the same governed batch implementation, with typed receipts and a reconcile-before-next barrier. The `simplicio-prism` skill/layer classifies the work and composes Mapper, Loop, and Dev CLI. The concrete drain-wave operator is `scripts/arm_drain_prism.py`.

A wave ends with lease/result reconciliation before the next group is admitted.
Arming is preparation, not execution. Mapper remains mandatory. See the
[Prism/wave interface details](docs/CLI_COMMANDS.md#prism-and-wave).

**Measured benchmark status (2026-09-11):** ten simulated tasks pass the independent
verifier after real OpenRouter proposals and native edits. This is a diagnostic
composed route, not a completed serial/Prism/Fast comparison. No fastest or
cheapest standard is proven. The [detailed report](docs/QUEUE_BENCHMARK_PROTOCOL.md)
records failures, retries, commands, receipts and the remaining qualification gates.
Open the [charts and measured command tables](.lavish/queue-benchmark-20260911/report.html)
or the [raw metrics and receipt hashes](.lavish/queue-benchmark-20260911/summary.json).

The [release qualification results](docs/BENCHMARK_RELEASE_QUALIFICATION.md)
separately record the restarted native CLI probes, exact commands, CPU/RAM,
and blockers. Failed admission, dry-run, and time-to-failure never qualify as
completed tasks or a performance winner.

Important nested command surfaces:

- `queue`: `status`, `top`, `drain`, `resume`, `doctor`, `reclaim`, `migrate`, `gc`, `inspect`, `cancel`.
- `findings`: `list`, `report`, `reconcile`, `doctor`, `import`.
- `economy`: `status`, `print`, `apply`.
- `stack`: `lock`, `verify`; `extensions` and `ecc` each expose `doctor`.

Typical single-task commands:

```bash
simplicio-loop "<task>" --verify "<tests>"   # default; you write the plan, Dev CLI applies it; no API key
simplicio-loop preflight --repo . --json
simplicio-loop orient --task "understand this repository" --repo .
simplicio-loop plan --task task.md --out contract.json
simplicio-loop prepare --task task.md --repo . --max-iterations 5
simplicio-loop wave <run_id>
simplicio-loop status --repo . --text
simplicio-loop progress --repo . --format markdown --once
simplicio-loop queue status
simplicio-loop verify <run_id>
```

The complete command reference is [`docs/CLI_COMMANDS.md`](docs/CLI_COMMANDS.md). The command surface can vary by installed package version, so check `simplicio-loop --version` and `simplicio-loop --help`; the current repository source is `3.43.11`.

The restarted comparison includes `wave`, `batch`, `batch --serial`, `tasks run`,
Prism, wave-policy variations and a limited semaphore control. See the
[flow matrix and mandatory Mapper/cache contract](docs/BENCHMARK_FLOW_MATRIX.md).
The limited control is not a public legacy command; `tasks run` currently has
a PR/merge delivery boundary and cannot be ranked against local edits alone.

---

### Doctor — verify + repair

```bash
python3 scripts/doctor.py            # report the whole stack (REQUIRED vs OPTIONAL)
python3 scripts/doctor.py --repair   # install/wire what's fixable; make everything operational
python3 scripts/preflight.py --json   # fail-closed mapper + dev-cli; optional Runtime is reported separately
# also: bash scripts/simplicio-economy.sh doctor [--repair]
```

`doctor` separates **REQUIRED** (python3, the loop package and its bundled mapper/dev-cli bins,
the 7 skills, the loop hooks, the capture proxy — `--repair` installs/wires them) from
**OPTIONAL** accelerators (the native Simplicio Runtime bind and the tray dependency).
**Missing an optional piece is never a failure and
never blocks** — the Python engine + the deterministic path cover everything; the exit code is 0 as
long as every REQUIRED item is healthy.

Or, on Claude Code / Cursor, install it straight from the latest GitHub release (no marketplace):

```bash
gh release download --repo simpletibr/simplicio-loop --archive tar.gz
tar xzf simplicio-loop-*.tar.gz && cd simplicio-loop-*/
bash scripts/install.sh claude    # or: bash scripts/install.sh cursor
```

Then:

```
/simplicio-loop finish all the open issues
```

For the standalone skill install, the only requirement is **python3** on PATH. For the repo
installer and GitHub-backed sources, you also want `git` + an authenticated `gh`. See [`INSTALL.md`](INSTALL.md) and
[`adapters/MATRIX.md`](adapters/MATRIX.md).

**Before an unattended 24/7 run:** confirm source auth is persistent, keep the irreversible-op
human gate + secret-scan on, and ensure a reachable STOP/cancel path is configured.

---

## 🔒 Safety (non-negotiable)

- **Secret-scan** every diff; block on hit.
- **Irreversible-op human gate** — force-push, history rewrite, prod deploy, data/schema delete,
  mass-file delete → stop and ask. Headless + no approver → remove the destructive capability.
- **Enforced, not just promised** — `hooks/action_gate.py` is a **fail-closed** `PreToolUse` /
  git-pre-push hook that mechanically blocks the above (and secret-laden commits) *before* they run.
  The safety contract holds even if the model forgets it. `selftest` proves the ruleset (15/15).
- **4-state pre-execution verdict** — optimization may never raise a command's risk tier.
- **Trust-before-load** — perception-shaping config (clamp profiles, suppression lists) is
  untrusted until a human reviews and hash-pins it.
- **Prompt-injection hardening** — item/PR/comment content can never override the contract.
- **Evidence-gated** completion (never a false "done"); **fail-open** hooks (never trap the agent
  in a loop); explicit STOP/cancel path for unattended runs.

---

## ✅ Tests & local checks (no paid CI)

Claims are verified, not just asserted — and the gate runs **locally**, with zero CI cost:

```bash
python3 scripts/check.py             # complete local gate; runs only the tests the change can affect
python3 scripts/check.py --full      # every test file (run before a release tag)
python3 scripts/check.py --base REF  # diff against REF instead of origin/main
python3 scripts/check.py --core-gate # mandatory offline/bounded core; external lanes excluded
python3 scripts/impact_tests.py      # print the test files the change affects
```

The default test selection is symbol-level (`scripts/impact_tests.py`): it diffs the working tree against
`--base` (default `origin/main`), keeps the top-level functions, classes and assignments whose source
changed, and selects the test files that name such a symbol and reach its module. Tests that name a
changed non-Python file (for example `SKILL.md`) and changed test files are selected too; generated
mirrors (`plugin/`, `simplicio_loop/_bundle/`) are covered by the parity gates. `--full` runs every
test file; `--core-gate` keeps its fixed core selection.

Monorepo (`packages/mapper`, `packages/dev-cli`): `bash scripts/dev_install.sh`
sets up one venv with all three packages editable from their in-repo paths, and
`python3 scripts/check.py --package mapper|dev-cli|loop|all` (or `--changed`, scoped to what
you touched vs `origin/main`) runs one package's own fast gate from its in-repo location — see [`AGENTS.md` § Development](AGENTS.md#development).

Both commands require an importable `pytest`; its absence is `pytest_unavailable`, never a
direct-execution fallback. The core gate runs claims audit, mirror parity, core pytest tests,
loop contract, clean-environment contract, token/repository budgets, and portable stage-contract
validation. It uses a sanitized subprocess environment, disables third-party pytest autoload,
and applies the loopback/AF_UNIX socket restriction to pytest and Python descendants that inherit
the gate environment; it does not sandbox arbitrary external CLIs. It has a 600-second global deadline plus shorter
per-phase deadlines, and fails if no mandatory test actually ran. Installed runtimes, live APIs,
sibling repositories, release builds, and other real external integrations stay in explicitly
marked lanes and are reported as unavailable/excluded — never silently promoted to PASS.

[`docs/SCRIPTS_INVENTORY.md`](docs/SCRIPTS_INVENTORY.md) documents the gate-relevant **core**
(required for the loop drive or this gate) and **satellite** (opt-in/advanced) boundaries; it is
not a census of every utility under `scripts/`. The current checkout and its local gate receipt
are authoritative for inventory and execution counts. Lead with the core; treat the rest as
advanced, opt-in capabilities you reach for when the task calls for them.

- **Test suite** (`tests/`, requires `pytest`) — the workers' deterministic `selftest`s, plus an **e2e of the loop
  driver** (`hooks/loop_stop.py`): it proves the loop **stops on evidence**, **ignores a bare
  `<promise>`**, and **stops on the cap** as distinct exits — and that the evidence producers
  **BLOCK** (never fake-pass) when their toolchain is absent. Individual legacy test modules may
  retain a developer self-runner, but `scripts/check.py` never treats that partial mechanism as a
  substitute for pytest collection.
- **Claims audit** (`scripts/claims_audit.py`, fail-closed) — every `scripts/*.py` the docs
  reference exists · the extension-point count agrees across all files · each cited worker command
  actually runs · the shipped `simplicio_loop/_bundle/` skills are **byte-identical** to source.
- **Impact audit** (`scripts/impact_audit.py`) — for any code task, proves the declared task
  surface covers the local blast radius: dependencies, reverse dependents, and related tests.
  ```bash
  python3 scripts/impact_audit.py audit . --file path/to/seed.py --cover path/to/seed.py --fail-on high
  ```
- **Flow audit** (`scripts/flow_audit.py`) — for mixed front/back/service repos, produces the
  `endpoint_compare` evidence map and fails on objective integration gaps:
  ```bash
  python3 scripts/flow_audit.py audit . --fail-on high
  ```
- **Wire it as a git pre-push hook** to keep `main` honest for free:
  ```bash
  printf '#!/bin/sh\npython3 scripts/check.py\n' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push
  ```

Install the development extra (`pip install "simplicio-loop[dev]"`) before running
`scripts/check.py`: pytest is a required gate dependency.

---

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=simpletibr/simplicio-loop&type=Date)](https://star-history.com/#simpletibr/simplicio-loop&Date)

---

## 📄 License

MIT

<!-- simplicio-loop:github-comment-coordination:v1 -->
## 🌐 Work-item comment coordination across runtimes

`simplicio-loop` can run at the same time in Claude Code, Codex, Cursor, Gemini, and Hermes. When a run is bound to a GitHub issue, it publishes idempotent lifecycle updates to that issue's canonical comment: claim, plan, progress, evidence, PR, and close. Agents on different machines can coordinate through the same GitHub thread without a shared local filesystem.

```powershell
pwsh scripts/install.ps1 claude -Global
pwsh scripts/install.ps1 codex -Global
pwsh scripts/install.ps1 cursor -Global
pwsh scripts/install.ps1 gemini -Global
pwsh scripts/install.ps1 hermes -Global   # legacy alias for simplicio_agent
```

Local queues, leases, worktrees, heartbeats, and evidence remain active on every machine; GitHub comments are the shipped shared coordination projection. Today, an unavailable or unauthenticated GitHub records a sync failure without inventing a remote acknowledgment. The stage-agent roadmap tightens this for GitHub-bound runs: [#433](https://github.com/simpletibr/simplicio-loop/issues/433) makes the comment confirmation mandatory before `COMPLETE`. [#436](https://github.com/simpletibr/simplicio-loop/issues/436) adds the same projection to Azure DevOps, Jira, Asana, and Trello only when each connector is proven connected; disconnected optional trackers are explicitly skipped.

GitHub Actions is not required or accepted as validation evidence for this repository; the local
gate is authoritative. Lifecycle state is projected by the local runtime integration when
configured; it can manage the `simplicio:status:<state>` label and a
GitHub Projects v2 Status field. The projection is runtime-neutral: it accepts Claude, Codex,
Cursor, Gemini, Kiro, Antigravity, Hermes/Simplicio Agent, OpenClaw, and future providers. Set
these repository variables to enable Project v2 movement:

```text
SIMPLICIO_PROJECT_NUMBER       # project number, for example 7
SIMPLICIO_PROJECT_OWNER        # optional; defaults to the repository owner
SIMPLICIO_PROJECT_OWNER_TYPE   # organization (default) or user
SIMPLICIO_PROJECT_STATUS_FIELD # optional; defaults to Status
```

Labels still update when no Project is configured. Human comments do not move cards; only the
marked Simplicio lifecycle comment, issue open/close/reopen events, or an explicit workflow
dispatch can change the status. The workflow uses `issues: write` and `repository-projects: write`
and never posts a second coordination comment.

## What the model sees

An agent using this repository sees `AGENTS.md`, the loaded `SKILL.md` files,
and the compact JSON printed by `simplicio-loop` (`orient --brief`, `prepare`,
`apply`, `wave`, `verify`). Source files enter the context only as the targets
those commands name, never as a full-tree dump.

### Token effect

The loop answers repository facts with the Mapper survey and deterministic
commands instead of model reads, and each command prints compact JSON. Input
tokens therefore grow with the task's targets, not with the repository size.

### KV cache effect

Every contract starts with an immutable header, and every loop JSON prints
`schema` and stable fields first, with volatile fields (`run_id`, timestamps,
paths) last. The prompt prefix stays byte-identical across turns, so the
provider serves it from cache after the first call. The benchmark fails a run
when a later call reads no cache (`bench/llm_ab`).
