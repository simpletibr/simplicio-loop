INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/IDE_TOOL_INTEGRATION.md','project_doc','doc://simplicio-runtime/docs/IDE_TOOL_INTEGRATION.md','doc: IDE & Tool Integration Guides','# IDE & Tool Integration Guides

> How VS Code, GitHub Copilot, Kiro, Cursor, and other tools should invoke the
> Simplicio runtime. Every path below treats `simplicio` as the canonical
> control plane — see `AGENTS.md` and `docs/INDEX.md`.

Simplicio is the task runner and control plane. Provider LLMs (Copilot, Cursor,
Kiro, VS Code''s agent mode, Claude, Codex, …) **orient, decompose, review, and
escalate** but must not bypass Simplicio for task execution, mutation,
validation, evidence, leases, or handoff. The runtime gives every tool:

- **Deterministic edits** (`simplicio edit`) that apply with zero LLM tokens.
- **Gated mutations** + an evidence ledger, so a tool''s actions are auditable.
- **Token savings**: the cheap deterministic step (map → memory → edit → gate →
  validate) runs before any model call, so the model pays only for reasoning.

The single principle for every integration: **call `simplicio` first, the model
second.** Below are the minimal and advanced paths per tool.

---

## 1. VS Code — Output panel flow

VS Code sees Simplicio as a CLI it invokes from Tasks, the Terminal, or an
extension. The Output panel is how you watch the deterministic pipeline run.

### Minimal

`.vscode/tasks.json` — run a task through Simplicio and watch the Output panel:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Simplicio: run task",
      "type": "shell",
      "command": "simplicio run \"${input:task}\" --repo ${workspaceFolder} --evidence --json",
      "problemMatcher": [],
      "presentation": { "reveal": "always", "panel": "new" },
      "group": "build"
    }
  ],
  "inputs": [
    { "id": "task", "type": "promptString", "description": "Task for Simplicio" }
  ]
}
```

Open **View → Output**, pick the *Simplicio: run task* channel. Output is NDJSON
evidence — every edit, gate decision, and validation is logged.

### Advanced

Wire Simplicio into the **Terminal** as the default task runner and add an
orientation task that stamps the session before any agent reads files:

```json
{
  "label": "Simplicio: orient (session gate)",
  "type": "shell",
  "command": "simplicio runtime map --repo ${workspaceFolder} --for-llm markdown",
  "problemMatcher": []
},
{
  "label": "Simplicio: edit via plan",
  "type": "shell",
  "command": "simplicio edit --plan ${workspaceFolder}/.simplicio-loop/plans/last.json",
  "problemMatcher": [],
  "dependsOn": "Simplicio: orient (session gate)"
}
```

Add `simplicio serve --mcp --stdio` to `.vscode/mcp.json` to let VS Code''s agent
mode call Simplicio tools directly (see §5 for the MCP contract).

### Token savings

Running `simplicio runtime map` before raw reads replaces dozens of file reads;
`simplicio edit` replaces hand-written diffs. Typical session: **40–70% fewer
tokens** on mechanical work vs. letting the model read-and-edit directly.

---

## 2. GitHub Copilot — external task flow

Copilot (in VS Code, the `copilot` CLI, or `gh copilot`) should delegate
execution to the runtime rather than mutate files itself.

### Minimal

From the Copilot Chat or the `copilot` CLI, ask Copilot to emit a Simplicio edit
plan, then run it:

```sh
# Copilot proposes the plan; you (or a hook) apply it deterministically:
simplicio edit --plan /tmp/copilot-plan.json
```

A `.github/copilot-instructions.md` (symlinked to `AGENTS.md`) tells Copilot the
rule: *do not edit source directly; produce a `simplicio edit` plan.*

### Advanced

Register the runtime as an MCP server so Copilot''s agent loop calls Simplicio
tools instead of raw file writes:

```json
{
  "mcpServers": {
    "simplicio": {
      "command": "simplicio",
      "args": ["serve", "--mcp", "--stdio"]
    }
  }
}
```

Then Copilot''s flow becomes: `simplicio_map` → `simplicio_memory` →
`simplicio_edit` → `simplicio_gate` → `simplicio_validate`, where the model only
reasons and Simplicio does the mutation + proof.

### Token savings

Copilot stops re-deriving repo structure and re-reading files; recall + map cover
context, and deterministic edits remove the "write-then-fix" loop. Expect
**30–60% fewer tokens** per task and far fewer round-trips.

---

## 3. Kiro — spec-to-runtime flow

Kiro works in *spec → requirements → design → tasks*. Map each Kiro task onto a
Simplicio `run` with evidence, so the spec is executed and proven, not just
documented.

### Minimal

```sh
simplicio run "implement Kiro task <id>: <title>" \
  --repo . --evidence --json > kiro-task-evidence.json
```

Pipe Kiro''s task description straight into `simplicio run`; the runtime orients,
edits, gates, and validates, returning a verifiable evidence chain.

### Advanced

Drive Kiro tasks from a Simplicio sprint so leases and status stay in sync:

```sh
simplicio sprint plan --repo . --from kiro-spec.md --json
simplicio sprint run   --repo . --json
simplicio deliver      --repo . --json   # gate + checkpoint before handoff
```

Kiro owns the *what*; Simplicio owns the *how* (deterministic execution +
evidence). The sprint graph doubles as the live status surface for Kiro.

### Token savings

Kiro stops generating implementation prose the model then has to re-read; the
runtime executes directly from the spec. **50%+ token reduction** on
spec-to-code, plus an auditable trail Kiro alone doesn''t produce.

---

## 4. Cursor — context-reduction flow

Cursor''s strength is in-editor edits; its weakness is context bloat. Use
Simplicio to shrink what Cursor loads into context.

### Minimal

Before asking Cursor to act, generate a zero-copy orientation pack and point
Cursor at the materialized snippets instead of whole files:

```sh
simplicio orientation pack --repo . --json
# Opens read-only via mmap; agents receive materialized snippets, not raw files.
```

In Cursor''s rules (`.cursorrules` → symlink of `AGENTS.md`), require: *"Run
`simplicio runtime map` before reading source; edit via `simplicio edit`."*

### Advanced

Give Cursor the MCP server and a `simplicio_search` / `simplicio_symbol` first
step so it fetches only the `pa','docs/IDE_TOOL_INTEGRATION.md','c25056f1bbb0673e4ed6cebfef04a8ef33e00e6c87b29519d58d324895fc9a30','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/INDEX.md','project_doc','doc://simplicio-runtime/docs/INDEX.md','doc: Simplicio — Documentation Index (read this first)','# Simplicio — Documentation Index (read this first)

> **Purpose.** This is the canonical map of *all* Simplicio documentation, in
> reading order. An LLM/agent (or human) should skim this index, then read the
> **Tier 0** files in full and the topic files relevant to the task, so it always
> knows the current state of the system before acting.
>
> Generated/maintained as the single entry point. Canonical setup files stay at
> the repo root by convention (tooling, tests, and `bootstrap.sh` reference
> them); everything else lives under `docs/`.

---

## Tier 0 — Always read first (the contract & system state)

| Order | File | What it is |
|---|---|---|
| 1 | [`AGENTS.md`](../AGENTS.md) | **Cross-agent contract.** The rules every agent follows each session. Read in full. |
| 2 | [`CLAUDE.md`](../CLAUDE.md) | Claude-specific project context, active build programs, naming/distribution rules, standing instructions. |
| 3 | [`docs/SIMPLICIO_OPERATIONAL_MANUAL.md`](SIMPLICIO_OPERATIONAL_MANUAL.md) | **Consolidated operational manual** — runtime rules, load order, deterministic flow, multi-agent loop, scale limits, neural guardians, contracts, *Hermes-Parity Foundations*, and an embedded source archive of many docs. The source of truth for "how the system works now". |
| 4 | [`README.md`](../README.md) · [`README.pt-BR.md`](../README.pt-BR.md) | Project overview / getting started (EN / PT-BR). |
| 5 | [`docs/SUPER_RUNTIME.md`](SUPER_RUNTIME.md) | **North star** — Simplicio Super Runtime product boundary, design pillars, token economy (#38). |

## Tier 1 — Setup & build (root, referenced by tooling — do not move)

| File | What it is |
|---|---|
| [`INSTALL.md`](../INSTALL.md) | Installing the LLM Project Mapper into an existing project. |
| [`INIT.md`](../INIT.md) | Guided initialization of the mapper. |
| [`_BOOTSTRAP.md`](../_BOOTSTRAP.md) | Bootstrap entry point (used by `bootstrap.sh`). |
| [`BUILDING.md`](../BUILDING.md) | Building the Rust runtime (used by `scripts/build.sh`). |
| [`CHANGELOG.md`](../CHANGELOG.md) | Release history. |
| [`docs/SIMPLICIO_INSTALL.md`](SIMPLICIO_INSTALL.md) | Instalação, configuração e quick start (consolidado). |
| [`docs/getting-started.md`](getting-started.md) | Hands-on first steps. |

## Tier 2 — Architecture & core subsystems

| File | What it is |
|---|---|
| [`docs/architecture/llm-integration.md`](architecture/llm-integration.md) | LLM/provider integration architecture. |
| [`docs/YOOL_INTEGRATION.md`](YOOL_INTEGRATION.md) | Yool tuple-space / HAMT orchestration. |
| [`docs/HERMES_AGENT_PORT_MATRIX.md`](HERMES_AGENT_PORT_MATRIX.md) | Port coverage matrix: Hermes `agent/` package (113 files, ~72k LOC) → Rust modules. |
| [`docs/SCRIPT_OWNERSHIP_QUARANTINE.md`](SCRIPT_OWNERSHIP_QUARANTINE.md) | Ownership/quarantine matrix for residual Python/Node/Shell/hooks/workflow surfaces. |
| [`docs/HERMES_UX_PORT_PLAN.md`](HERMES_UX_PORT_PLAN.md) | Hermes UX port plan: terminal comparison, gaps, decisions. |
| [`docs/SCHEDULER.md`](SCHEDULER.md) | Scheduler + decision engine. |
| [`docs/MECHANICAL_CONTRACTS.md`](MECHANICAL_CONTRACTS.md) | Contract registry (`mechanical-edit/v1`, `test-gated-edit/v1`, …) and how they run. |
| [`docs/specs/HBI-v1.md`](specs/HBI-v1.md) · [`docs/specs/HBP-v1.md`](specs/HBP-v1.md) | Versioned binary index and append-only receipt contracts, compatibility rules, and consumer identity receipt. |
| [`docs/contracts/agent-handoff.md`](contracts/agent-handoff.md) | Typed continuation contract for agent-to-agent handoff with execution state, lineage, and evidence refs. |
| [`docs/CHAT_OPERATIONAL.md`](CHAT_OPERATIONAL.md) | Operational chat / action bridge behavior. |
| [`docs/VIDEO_PIPELINE.md`](VIDEO_PIPELINE.md) | Deterministic video creation pipeline. |

## Tier 3 — Design / evaluation (proposed, pre-implementation)

| File | Issue | What it is |
|---|---|---|
| [`docs/design/voice-first.md`](design/voice-first.md) | #701 | Voice-first architecture (piper-rs + whisper, barge-in via `conversation_control`). |
| [`docs/design/browser-control.md`](design/browser-control.md) | #707 #710 | Browser automation (fantoccini/CDP + `browse-plan/v1`); covers BR product-search sites. |
| [`docs/design/desktop-control.md`](design/desktop-control.md) | #706 | Desktop computer-use (a11y-tree-first + `desktop-plan/v1`). |
| [`docs/design/conversation-loop.md`](design/conversation-loop.md) | #712 | Hermes `run_conversation` mapped onto the landed Rust foundations. |
| [`docs/design/coding-support.md`](design/coding-support.md) | #709 | ACP completeness + IDE clients + `code-review/v1`. |
| [`docs/design/social-media-ops.md`](design/social-media-ops.md) | #708 | Social actions: official APIs + browser fallback, gated. |
| [`docs/design/customer-service-verticals.md`](design/customer-service-verticals.md) | #719 #720 #721 | WhatsApp/IG + veterinary + dental over one conversation engine. |
| [`docs/design/vestibular-study.md`](design/vestibular-study.md) | #717 | Voice-first adaptive study assistant (ENEM/Fuvest). |

## Tier 4 — Quality, benchmarks & competitive analysis

| File | What it is |
|---|---|
| [`docs/DELIVERY_QUALITY.md`](DELIVERY_QUALITY.md) | "Delivered" definition-of-done & quality gates. |
| [`docs/HERMES_PARITY.md`](HERMES_PARITY.md) | Feature parity tracking vs Hermes Agent. |
| [`docs/COMPETITIVE_BENCHMARK.md`](COMPETITIVE_BENCHMARK.md) | Simplicio × Hermes × OpenClaw / OpenHands / Aider / claude-task-master benchmarks and setup notes. |
| [`docs/CASE_STUDY_002_DETERMINISTIC_LANE.md`](CASE_STUDY_002_DETERMINISTIC_LANE.md) | Real measured case study: deterministic pipeline, 0 LLM tokens, wall times. |
| [`docs/CASE_STUDY_003_VELOCIDADE_TOKENS_DETERMINISMO.md`](CASE_STUDY_003_VELOCIDADE_TOKENS_DETERMINISMO.md) | Case study de latencia, tokens, THINK vs NO-THINK, e memoizacao deterministica L0. |
| [`docs/SESSION_BENCHMARKS_2026-06-05.md`](SESSION_BENCHMARKS_2026-06-05.md) | Dated benchmark session. |
| [`docs/AGENT_BATTERY_2026_06_05.md`](','docs/INDEX.md','34c04901aaaf2e73e752a4952cea0eb4dcfb0f20360b3e719fc481ced6e278bb','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/innovation-scan/2026-06-25-state-of-the-art.md','project_doc','doc://simplicio-runtime/docs/innovation-scan/2026-06-25-state-of-the-art.md','doc: Innovation scan — state-of-the-art for Simplicio (2026-06-25)','# Innovation scan — state-of-the-art for Simplicio (2026-06-25)','docs/innovation-scan/2026-06-25-state-of-the-art.md','6502db93a95052f6fb15a6872042d144d65ada19fc1a3556d2736e4c73dcdd0a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/INSTALLATION_MODEL.md','project_doc','doc://simplicio-runtime/docs/INSTALLATION_MODEL.md','doc: Installation Model','# Installation Model

How `simplicio` is installed and how a fresh machine is bootstrapped (#27).

## One-command bootstrap

```sh
bash scripts/bootstrap-fresh-machine.sh          # POSIX
pwsh scripts/bootstrap-fresh-machine.ps1 -Apply   # Windows
```

The script is **offline-first**: it never downloads unexpected binaries or
models. It records a transcript under `.simplicio-loop/bootstrap/`:

| Step | Command | Artifact |
|------|---------|----------|
| before | `simplicio doctor --repo . --json` | `doctor-before.json` |
| plan | `simplicio install --global --dry-run --json` | `install-plan.json` |
| ecosystem | `bash scripts/install-ecosystem.sh --venv` | four Simplicio packages |
| llm | verify `llama-server` on PATH (opt-in install) | report |
| repair | `simplicio doctor --repair --json` | `doctor-after.json` + `repair-report.json` |

## Install Experience

- The user does **not** memorize four `pip install` commands — the bootstrap
  script installs `simplicio-cli`, `simplicio-mapper`, `simplicio-prompt`,
  `simplicio-sprint` via `requirements-ecosystem.txt`.
- `doctor --repair` fixes common missing pieces (`.simplicio-loop` layout, `[tools]`
  pointers for a project venv, cached GGUF) and re-verifies with real before/
  after values (never assumed).
- After bootstrap, **offline-first mode** works: `simplicio doctor` reports
  `offline_first_ready` once adapters are available; remote model downloads are
  an explicit opt-in, not a side effect.

## Global LLM and Tool Configuration

`simplicio install --global` produces a reviewable plan (`install-plan.json`):
`--dry-run` prints it, `--yes` applies it, and every changed assistant config is
backed up under `.simplicio-loop/backups/assistant-configs`. `simplicio adapters
rollback` restores the previous state — installation is always reversible.

## Assistant Adapters

Detected adapters: codex, claude, cursor, vscode, github-copilot, kiro,
generic-mcp, shell-agents, local-llm-tools. Each is wired by `install --global`
with a diff preview and a backup before any mutation.','docs/INSTALLATION_MODEL.md','e5ef5ff408d54df08d7a9702984c78a469e12e7c029834b98886b5a26e401945','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/INTEGRATIONS.md','project_doc','doc://simplicio-runtime/docs/INTEGRATIONS.md','doc: Integrations — Using Simplicio Runtime with Premium LLMs','# Integrations — Using Simplicio Runtime with Premium LLMs

This guide shows how premium LLMs (OpenAI **Codex**, Anthropic **Claude**, and
other agents) should use the Simplicio runtime as local execution infrastructure.

The core principle: **a premium LLM plans, reviews, and escalates — Simplicio
executes locally.** Premium reasoning is expensive; spend it on decomposition
and review, not on shell plumbing. Simplicio''s CLI is the canonical execution
surface for all agents (`simplicio <cmd>`), with MCP (`simplicio serve --mcp
--stdio`) as a fallback when a client already has the server wired.

---

## Why route execution through Simplicio

- **Deterministic edits, zero LLM tokens** — `simplicio edit` writes code from a
  plan the LLM proposes; no free-form file mutation.
- **Local execution + verifiable evidence** — `doctor`, `run`, `sprint`, and
  `deliver` produce receipts you can read back as JSON.
- **Token-saving** — `runtime map --for-llm` returns compressed context; `memory`
  and `skills recall` reuse prior work instead of regenerating it.
- **Gate + validation** — the pre-commit gate and `validate` surface HIGH-severity
  findings before they land.

---

## Codex workflow

### Before (raw shell)

```
$ find . -name ''*.rs'' | xargs grep -l TODO
$ sed -i ''s/.../.../'' ...
$ cargo build      # slow, on the agent''s machine
```

Codex shells out, mutates files by hand, and pays build cost itself.

### After (Simplicio)

```
# orient
$ simplicio runtime map --for-llm markdown
$ simplicio memory "authentication flow"

# plan + deterministic edit (no free-form mutation)
$ simplicio edit --plan /tmp/plan.json

# validate locally + read evidence
$ simplicio doctor
$ simplicio run --cmd "cargo check" --json
```

Codex proposes; Simplicio writes and proves. The premium model is reserved for
the plan, not the plumbing.

### When to call the runtime

- Reading compressed repo state before making changes (`runtime map`).
- Writing deterministic edits (`edit`) instead of sed/awk/heredoc.
- Running `doctor`, `plan`, `run`, `sprint`, and `deliver` to get evidence.
- Escalating to a paid model only when local generation can''t close the gap.

### Reading JSON output

`simplicio run --json` and `simplicio doctor --json` emit `simplicio.io/v1`
envelopes. Parse the `receipt` / `evidence` fields; surface HIGH-severity
findings to the user before proceeding.

---

## Claude workflow

### Before (raw shell)

```
> grep -rn "TODO" src/
> edit the file in place
> run the tests locally
```

Claude edits files directly and runs builds, spending premium tokens on
mechanical execution.

### After (Simplicio)

```
# orient
$ simplicio runtime map --for-llm markdown
$ simplicio skills recall "add a new command"

# deterministic edit
$ simplicio edit --plan /tmp/plan.json

# validate + evidence
$ simplicio validate --level syntax-format-and-changed-files
$ simplicio deliver --json
```

Claude reserves reasoning for planning and review; Simplicio handles the
execution and the evidence chain.

### When to call the runtime

- Orienting on a fresh clone (`runtime map`, `memory`).
- Any mutation → `edit` (deterministic, token-free).
- Validation gates (`validate`, `deliver`) instead of local ad-hoc test runs.
- `sprint` for multi-step task graphs with leases.

### Reading JSON output

Pipe `--json` output to your JSON tool of choice. The receipt carries the
evidence chain (`HBP`); a passing gate means the change is safe to commit
(commit via `SIMPLICIO_GATE_SKIP` only when the orchestrator centralizes
builds).

---

## Prompt snippets

**Codex (shell agent)**
```
You are integrating with the Simplicio runtime. Before any file change, run
`simplicio runtime map --for-llm markdown` and `simplicio memory "<topic>"`.
Propose edits as a `simplicio edit --plan` JSON file; do NOT sed/awk/write files
directly. Validate with `simplicio doctor --json` and `simplicio run --json`.
Reserve your reasoning for planning/review/escalation — Simplicio executes.
```

**Claude (IDE agent)**
```
Use the Simplicio CLI as the canonical execution surface. Orient with
`simplicio runtime map --for-llm markdown`, recall with `simplicio skills recall
"<task>"`, and apply changes via `simplicio edit --plan`. Validate with
`simplicio validate` and `simplicio deliver --json`. Never bypass Simplicio for
mutation, validation, or evidence.
```

---

## Acceptance checklist (issue #22)

- [x] Before/after workflows for Codex and Claude.
- [x] Example command transcripts using `doctor`, `plan`, `run`, `sprint`, and evidence.
- [x] Guidance that reserves the premium LLM for planning/review/escalation.
- [x] Prompt snippets for both agents.
- [x] How to read JSON output / evidence.

Closes #22','docs/INTEGRATIONS.md','e2b73da36b09b1a80b7409d92459603241fff1bdcc2153fad2a5678bd6cef8c4','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ISSUE_3439_CRASH_INJECTION.md','project_doc','doc://simplicio-runtime/docs/ISSUE_3439_CRASH_INJECTION.md','doc: Issue #3439 — transactional crash injection','# Issue #3439 — transactional crash injection

This slice adds a Runtime-side crash-injection executor for the Runtime-100 /
RR84 transaction boundaries: `reserve`, `claim`, `edit`, `artifact`, `receipt`,
and `cleanup`.

The executor persists its state before advancing a boundary, writes edits to an
atomic partial file, renames the artifact only after hashing it, appends a
receipt JSONL record before committing state, and releases the lease last.
Recovery is idempotent:

- a receipt-backed artifact is finalized and its lease is released;
- any state without a receipt-backed commit removes the partial/final artifact,
  claim marker, and lease, then appends `rollback_reconciled` evidence;
- retrying the same work item starts a new attempt and does not duplicate a
  committed artifact.

The test matrix covers all six boundaries, partial artifacts, five repeated
restart cycles, and the four requested scenarios (`baseline`, `runtime`,
`runtime+loop`, `full-stack`) with one warmup plus five repetitions. Token and
cost fields remain null unless the runtime emits them.

The implementation lives in `src/crash_injection.rs` and is registered by the
Runtime binary. It is deliberately filesystem-backed so recovery exercises the
same persistence and rollback path used after a process exit.','docs/ISSUE_3439_CRASH_INJECTION.md','ea8b37d60c4b986289274d707e3a7555ba62193e381a57b3f5369dad033fa457','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ISSUE_AUDIT_2026-06-27.md','project_doc','doc://simplicio-runtime/docs/ISSUE_AUDIT_2026-06-27.md','doc: Issue Implementation Audit — 2026-06-27','# Issue Implementation Audit — 2026-06-27

**Question audited:** of every issue closed as "completed", was the code actually
implemented — or closed without it (the Fischer #618 pattern)?

**Method (two distinct layers — important for integrity):**
1. **Mechanical coverage pass — the Simplicio MCP server, ZERO LLM.**
   `scripts/audit_issues.py` drove the real `simplicio serve --mcp --stdio`,
   calling `simplicio_search` (deterministic CodeGraph symbol lookup) + path/schema
   existence checks, for every issue. No model inference — pure index. This is the
   dogfood: **586 MCP calls over 1580 issues, p50 1.8 ms, 0 errors, 2.5 s wall.**
2. **Adversarial verification — a frontier LLM (Claude), NOT a local model.**
   The mechanical pass only flags *artifact-missing* (which over-counts: a feature
   is often implemented under a different filename). The judgment "real ghost vs
   rename" was done by spawned Claude subagents (~3.6 M tokens across 59 agents),
   each searching the repo hard before concluding. The in-process local LLM (qwen)
   was OFF (lean `--no-default-features` build) and was not used.

This is exactly the CLAUDE.md contract: *Simplicio searches deterministically; the
frontier LLM decides.* We do **not** claim Simplicio auto-audited itself with a
local model — it didn''t. It supplied the cheap deterministic layer; the reasoning
was the frontier.

## Coverage

| | count |
|---|---|
| Closed issues audited (mechanical, via MCP) | **1480 / 1480 (100%)** |
| Open issues audited | 100 / 187 |
| Mechanical verdicts | REAL 422 · suspect 342 · NO_CLAIM 816 |
| Suspects adversarially verified | 343 (3 batches) |
| Verified outcome | REAL 258 · PARTIAL 51 · **GHOST 25** |

So of 342 mechanical suspects, only **25 are confirmed artifact-ghosts** (~1.7 % of
closed issues). Most mechanical flags were false positives (capability present under
another name).

## Confirmed ghosts (closed as completed, claimed artifact absent)

### A. Genuine capability gaps — feature not implemented (priority)
| # | claim | evidence |
|---|---|---|
| 283 | `get_execution_details()` | not found; only `input_history`/`execution_result_summary` exist |
| 503 | `runtime_client.rs` thin client | no RuntimeClient module / thin-client layer |
| 1040 | voice TTS/STT in-process | tts/voice modules return `not yet ported`; no piper/cpal/rodio deps |
| 1043 | fantoccini WebDriver `BrowserController` | stub returns "not implemented"; no `struct BrowserController` |
| 1077 | `conflict_heatmap` | only in the advertised-features string; no handler/impl |
| 1078 | cross-file transactional edits | only a cross-file dependency graph; no transaction support |
| 1121 | diff/patch engine | only a plan + naive byte-compare stub; commit was `plan(#1121)` not `feat` |
| 1138 | dead-code remediation infra | `fabrication_audit.rs`/`behavioral_test_ratchet.rs` NOT wired in `main.rs` |
| 1167 | plugin hot-reload (dlopen/WASM) | only YAML manifest verification; no dynamic loading |
| 2105 | enterprise multi-user / team RBAC | only Teams-platform integration; no RBAC |
| 2125 | `skill_loop/auto_create.rs` autonomous skill creation | directory/file absent |
| 2142 | `life/family.rs` | absent |
| 2144 | `desktop/dashboard/adaptive.rs` priority calc | absent |
| 2145 | `desktop/transparency.rs` live feed | absent |
| 2146 | `sharing/invite.rs` | absent |

### B. Renames / trackers / doc-path mismatches (capability present or weak claim)
| # | note |
|---|---|
| 22 | docs exist under different names (`docs/planning/INTEGRATIONS_EPIC.md`) |
| 481 / 482 | window-state/clipboard via Electron/xclip, not the claimed Tauri plugins |
| 607 | HBP exists natively in Rust (`src/hbp/mod.rs`); only the `.ts` artifact is absent |
| 841 | similar-named audit docs exist |
| 847 | claim too generic to verify |
| 921 | agent budget exists as `IterationBudget` (`src/iteration_budget.rs`) |
| 1039 / 1041 / 1042 | "Make #N real" trackers; the parent feature IS implemented |

## Already fixed this session
- **#618 (Fischer Kernel)** — was a true ghost (closed, no code). Now native:
  `src/fischer_kernel.rs` (3 tiers PROCEED/cpl0, BLOCK/cpl999, BLOCK/cpl500),
  emitting onto the existing HBP chain. 5/5 unit tests green. On main.

## Recommended next actions
1. Re-open or annotate the 15 Group-A ghosts with this evidence (closed-without-code).
2. Close the highest-value gaps in the loop (e.g. #1043 browser, #1077/#1078 edit
   features) or explicitly mark them as deferred/won''t-do.
3. Group-B can be closed as "implemented under a different name" with a pointer.
4. Finish the remaining 87 open issues'' audit for 100% total coverage.

Tooling: `scripts/audit_issues.py` (re-runnable). Raw verdicts were produced over
the fetched issue corpus; the mechanical pass is reproducible against any issue JSONL.

---

## Full-coverage pass (2026-06-27, all 1580 closed)

Extended the mechanical audit to the FULL closed-issue corpus via the MCP server:
**1580 / 1580 closed issues, 586 MCP calls, p50 1.9 ms, 0 errors, 4.1 s.** A second
multi-agent adversarial pass verified the newer suspects (224 verified: REAL 147,
PARTIAL 37, **GHOST 40**).

### Closed this pass — activated as real CLI commands (multi-agent, verified live)
`diff-patch` (#1121) · `rbac` (#2105) · `skill-autocreate` (#2125) · `family`
(#2142) · `desktop-priority` (#2144) · `transparency` (#2145) · `share` (#2146) —
each a real command keeping the no-fake-success rule. 136 module unit tests green.

### Confirmed ghosts NOT yet closed (large / out-of-session-scope)
| cluster | issues | reality |
|---|---|---|
| **Mesh network** | #2127-2131 | `src/mesh/*` absent — only MESH_NETWORK_ARCHITECTURE.md (design, zero impl) |
| **Cloud services** | #2133-2137 | `src/cloud/*` absent — only CLOUD_ARCHITECTURE.md (CRDT/HLC/Ed25519 planned, zero impl) |
| ~~Deleted code~~ **(FALSE POSITIVE)** | #1155, #1156 | NOT ghosts — the code was RELOCATED in overhaul #2304, not lost: #1155''s symbols (`FunctionDef`/`SourceAnalyser`/`Doma','docs/ISSUE_AUDIT_2026-06-27.md','700d801eec048a4f60f2ce76ea7458d387c84fda6126bd09e2e47e35c7bce3db','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ISSUE_ROADMAP.md','project_doc','doc://simplicio-runtime/docs/ISSUE_ROADMAP.md','doc: Issue Roadmap — Capability Packs','# Issue Roadmap — Capability Packs

Status board for capability-pack work. Issue-scoped tracking for #36 and its
follow-ups.

## #36 — best-in-class programming capability packs  ✅ implemented

Goal: absorb the strongest programming patterns from Hermes, ECC, Codex-style,
IDE, MCP, and Simplicio into a runtime pack registry that activates from task/repo
evidence instead of loading globally.

Acceptance criteria → evidence:

| Criterion | Evidence |
|-----------|----------|
| `simplicio capabilities list --json` groups by pack | `capability_packs()` derives distinct packs from `capability_catalog()`; emitted in `capability-list/v1` and `runtime map`. |
| `simplicio skills rank ... --json` reports which pack selected each skill | `capability_ranking_json` emits `selected_packs` + per-row `reason` (`pack <pack> selected for task kind <kind>`). |
| Runtime explains pack selection for frontend / API / Rust / .NET / Python package / release / PR-review | `packs_for(kind, task)` dispatch table + keyword triggers; unit fixtures in `src/main_parts/chunk_15.rs`. |
| Packs benchmarked for token savings vs manual flow | `simplicio.benchmark-row/v1` rows in `capability_ranking_json`. |
| Pack selection visible in event logs + final reports | `BuildDecision.selected_packs` rendered into `simplicio.decision/v1`, runtime map, and event log; `src/commands/run.rs` guarantees requested pack presence. |

Evidence artifacts added this pass (issue #36 acceptance docs that were dropped during
the runtime doc consolidation, `ff006028`):

- `docs/CAPABILITY_CURATION.md` — registry model, the 10 packs, selection matrix, worked examples, validation commands.
- `examples/capability-packs/registry.fixture.json` — pack-registry snapshot fixture.
- `docs/ISSUE_ROADMAP.md` — this file.

## Pack coverage map

| Pack | Status | Notes |
|------|--------|-------|
| repo-intelligence | ✅ | baseline pack |
| debugging | ✅ | api/rust/.net/python/frontend trigger |
| tdd-verification | ✅ | baseline pack |
| browser-evidence | ✅ | e2e / frontend trigger |
| code-review | ✅ | review / pr / security trigger |
| source-control | ✅ | pr / sprint trigger |
| docs-research | ✅ | docs/context7/research trigger |
| agent-ops | ✅ | sprint trigger |
| token-economy | ✅ | token/cache/context-budget trigger |
| release-ops | ✅ | release / deploy-check trigger |

## Follow-ups (not blocking #36)

- Expose `selected_packs` in the TUI decision panel (`src/tui_app_parts/*`).
- Add a `capabilities packs --json` convenience subcommand that renders only the
  registry (currently derived via `capability_packs`).
- Track token-savings benchmark rows over real runs, not just fixtures.','docs/ISSUE_ROADMAP.md','6ebf737d6fd33db04b2d4da511cd6a680cf7abbe2589ded0c92c37e72b47f4ef','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ISSUE_TRIAGE_2026_06_04.md','project_doc','doc://simplicio-runtime/docs/ISSUE_TRIAGE_2026_06_04.md','doc: Triagem & Roadmap de Issues — gerado pelo Simplicio','# Triagem & Roadmap de Issues — gerado pelo Simplicio

- **Data:** 2026-06-04
- **Fonte:** 37 issues abertas de `wesleysimplicio/simplicio-runtime`, buscadas e indexadas na memória neural via `simplicio memory ingest` (ingestor `project-github`, kind `github_issue`).
- **Classificação:** cada issue passou por `simplicio plan "<título>" --repo . --json` (decisão determinística `simplicio.decision/v1`). Os campos `task_kind` e `model_strategy` abaixo vêm direto do runtime — não são opinião manual.
- **Binário:** `target/release/simplicio` v0.3.16 (rebuild do `main` atual).

## Tratáveis sem LLM neste sandbox (4)

O simplicio marcou estas como `no-llm deterministic-first` — implementáveis aqui sem modelo local/remoto:

- **#178** (map) — Avaliar codegraph para melhorar o contexto do mapper e memória neural
- **#237** (test) — Diagnostics Feedback: parsers de toolchain (rustc/clippy/cargo test, tsc, pyright/pytest) como contrato que dirige o reparo
- **#255** (test) — Delivery Certificate &amp; Quality Score: `simplicio.delivery-certificate/v1` automatizado por entrega
- **#256** (docs) — Consolidate examples into a single Markdown file

As demais o runtime classificou como `local-first qwen…` (precisam de LLM para os passos de geração/edição autônoma).

## EPIC #235 — Chat Operacional (melhor que Hermes)

> Próximo passo de código (CLAUDE.md): #190 → #231 → #230.

| Issue | Título | `task_kind` | Estratégia | Sem LLM? |
|---|---|---|---|---|
| #190 | P1 Hermes: implementar cérebro de conversa com intent, contexto ordena | `edit` | local-first qwen | — |
| #193 | P2 Pi.dev: implementar camada de extensões, pacotes e sessão/RPC para  | `edit` | local-first qwen | — |
| #194 | Indexar todas as skills na memória neural e consultar memória antes do | `edit` | local-first qwen | — |
| #230 | P1.5 Action Bridge: ligar o chat à execução determinística (a &#34;cam | `edit` | local-first qwen | — |
| #231 | Action Gate: aprovação, allowlist/blocklist e modos (ask/auto/safe) pa | `edit` | local-first qwen | — |
| #232 | Checkpoints &amp; rollback (/undo): tornar reversível toda ação inicia | `release` | local-first qwen | — |
| #233 | Context Files &amp; Identity: carregar SOUL.md/AGENTS.md/.cursorrules  | `edit` | local-first qwen | — |
| #234 | Memory Tool Actions: salvar/atualizar/esquecer memória e perfil do usu | `edit` | local-first qwen | — |
| #236 | P1.6 Coding Loop: executor iterate-until-green dirigido pelo chat (edi | `e2e` | local-first qwen | — |
| #237 | Diagnostics Feedback: parsers de toolchain (rustc/clippy/cargo test, t | `test` | no-LLM (determinístico) | ✅ |
| #238 | In-Chat Command Surface: dispatcher determinístico de slash/quick comm | `e2e` | local-first qwen | — |
| #239 | Action Trajectory &amp; Self-Improvement: trilha replayável das ações  | `edit` | local-first qwen | — |
| #235 | EPIC: Chat Operacional — Simplicio melhor que Hermes (interpretar e ag | `edit` | local-first qwen | — |

## EPIC #240 — Criação de Vídeos (melhor que Claude/Codex/Hermes)

> Próximo passo de código (CLAUDE.md): #241 → #242 → #244.

| Issue | Título | `task_kind` | Estratégia | Sem LLM? |
|---|---|---|---|---|
| #241 | Video Pipeline &amp; Orchestrator ⭐: `simplicio video` determinístico  | `edit` | local-first qwen | — |
| #242 | Roteiro/Storyboard: tópico → `simplicio.video-script/v1` (cenas, narra | `e2e` | local-first qwen | — |
| #243 | Remotion backend: render React→MP4 determinístico via CLI (render-até- | `api` | local-first qwen | — |
| #244 | HyperFrames backend: render HTML/CSS/JS→MP4 determinístico (headless,  | `api` | local-first qwen | — |
| #245 | Higgsfield MCP backend (gated): geração de vídeo/imagem + virality/ups | `api` | local-first qwen | — |
| #246 | Timeline/EDL &amp; Editing: `simplicio.video-timeline/v1` + compositor | `edit` | local-first qwen | — |
| #247 | Áudio: voiceover por cena (TTS) + música + mix determinístico (ducking | `edit` | local-first qwen | — |
| #248 | Legendas/Captions: SRT/ASS de roteiro + word-timestamps (whisper), bur | `edit` | local-first qwen | — |
| #249 | Video Skills (memória-primeiro #194) + catálogo de assets com proveniê | `edit` | local-first qwen | — |
| #240 | EPIC: Criação de Vídeos — Simplicio melhor que Claude/Codex/Hermes (ch | `edit` | local-first qwen | — |

## EPIC #250 — Entrega com Qualidade (funciona, não só compila)

> Próximo passo de código (CLAUDE.md): #251 → #252.

| Issue | Título | `task_kind` | Estratégia | Sem LLM? |
|---|---|---|---|---|
| #251 | DoD &amp; Acceptance Gate ⭐: extrair e enforçar acceptance_criteria co | `edit` | local-first qwen | — |
| #252 | Run-Verification / Works-Check (Dogfood): rodar o entregável de verdad | `edit` | local-first qwen | — |
| #253 | Regression Guard: testes existentes seguem verdes + diff de comportame | `edit` | local-first qwen | — |
| #254 | Pre-Delivery Self-Review: review determinístico+LLM do diff (correção/ | `review` | local-first qwen | — |
| #255 | Delivery Certificate &amp; Quality Score: `simplicio.delivery-certific | `test` | no-LLM (determinístico) | ✅ |
| #250 | EPIC: Entrega com Qualidade — Simplicio melhor que Claude/Codex/Hermes | `edit` | local-first qwen | — |

## Skills / Memória / RAG — pesquisa & frameworks (standalone)

> Issues de fundação para skills, RAG e multi-agent; várias são research.

| Issue | Título | `task_kind` | Estratégia | Sem LLM? |
|---|---|---|---|---|
| #173 | Implementar Agent Skills Framework robusto no simplicio-runtime (inspi | `edit` | local-first qwen | — |
| #174 | Integrar padrões de Agentic RAG / Graph RAG na memória neural do proje | `edit` | local-first qwen | — |
| #175 | Suporte a MCP / Browser Automation Tools como skills nativas no runtim | `e2e` | local-first qwen | — |
| #176 | Explorar Multi-Agent Orchestration patterns (ex: TradingAgents) no con | `edit` | local-first qwen | — |
| #177 | Avaliar integração de TradingAgents patterns no Yool / multi-agent orc | `edit` | local-first qwen | — |
| #178 | Avaliar codegrap','docs/ISSUE_TRIAGE_2026_06_04.md','9d5ffe726af950d2eeea5251a654f45f7c2008cf070e086755e8ab90af431d85','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1031.md','project_doc','doc://simplicio-runtime/docs/issues/1031.md','doc: Issue #1031 — Browser automation: implementar BrowserController com fantoccini','# Issue #1031 — Browser automation: implementar BrowserController com fantoccini

## Context

The design doc (`docs/design/browser-control.md`) defines a `BrowserController` trait and 5 milestones. No implementation exists yet in the codebase. The existing browser code (`browser_provider.rs`, `htool_browser_tool.rs`, `htool_browser_cdp_tool.rs`, `plugins/browser/*`) handles cloud providers (Browserbase, BrowserUse, Firecrawl) via CDP and the agent-browser CLI. None of it uses fantoccini or WebDriver.

fantoccini is an async crate requiring tokio + hyper. The current runtime uses `std::process::Command` for all I/O (no async runtime). This is the main architectural constraint.

## Sub-issues

### 1031-A: Cargo feature flag `browser` + fantoccini dependency

**Files:** `Cargo.toml`
**Work:**
- Add `[features] browser = ["fantoccini", "tokio"]` with optional deps.
- Add `fantoccini = { version = "0.21", optional = true }` and `tokio = { version = "1", features = ["rt-multi-thread", "macros"], optional = true }`.
- All subsequent browser-controller code is gated behind `#[cfg(feature = "browser")]`.

**Acceptance:** `cargo check` passes with and without `--features browser`.

---

### 1031-B: `BrowserController` trait + `Selector` + `BrowserError` types

**Files:** new `src/browser_controller.rs`
**Work:**
- Define the trait from the design doc: `goto`, `find`, `click`, `fill`, `text`, `screenshot`, `current_url`.
- `Selector` enum: `Css(String)`, `XPath(String)`, `Text(String)` — serializable with serde.
- `BrowserError` enum with variants: `Navigation`, `ElementNotFound`, `DriverConnection`, `Timeout`, `DomainNotAllowed`.
- `Element` struct with `tag`, `text`, `attributes` fields.
- All behind `#[cfg(feature = "browser")]`.
- Add `mod browser_controller;` to `main.rs` behind the feature gate.

**Acceptance:** `cargo check --features browser` passes; trait is importable.

---

### 1031-C: fantoccini `BrowserController` implementation

**Files:** new `src/browser_fantoccini.rs`
**Work:**
- `FantocciniController` struct wrapping `fantoccini::Client` + a `tokio::runtime::Runtime` handle.
- Constructor takes `driver_url: &str` (e.g. `http://localhost:4444`), connects via `fantoccini::ClientBuilder`.
- Implement `BrowserController` for `FantocciniController`. Each method blocks on the tokio runtime (`rt.block_on(...)`) to bridge sync trait to async fantoccini.
- Domain allowlist: `Vec<String>` checked in `goto` before navigation; returns `BrowserError::DomainNotAllowed` on violation.
- `screenshot` returns PNG bytes via `fantoccini::Client::screenshot`.
- Add `mod browser_fantoccini;` to `main.rs` behind `#[cfg(feature = "browser")]`.

**Acceptance:** Unit test that starts a fantoccini client against a mock/local page, navigates, reads text.

---

### 1031-D: Evidence ledger integration for browser actions

**Files:** `src/browser_fantoccini.rs` (or a wrapper)
**Work:**
- Wrap each `BrowserController` method call to emit a step record to the evidence ledger (existing `evidence.rs` or `ledger.rs` — identify the correct module).
- Screenshots from `screenshot()` are saved as evidence artifacts with a deterministic filename (`browser_step_{n}.png`).
- Step records include: timestamp, action name, selector used, success/failure, url after action.

**Acceptance:** After a `goto` + `text` sequence, the ledger contains 2 step entries.

---

### 1031-E: `browse-plan/v1` contract executor

**Files:** new `src/contract_browse_plan.rs`
**Work:**
- Define `BrowsePlanStep` struct: `op` (enum: Goto, Click, Fill, Text, Screenshot, WaitFor), `selector` (Option), `value` (Option), `expect` (Option — postcondition).
- `BrowsePlan` struct: `domain_allowlist: Vec<String>`, `steps: Vec<BrowsePlanStep>`.
- `execute_browse_plan(plan: &BrowsePlan, ctrl: &mut impl BrowserController) -> Result<BrowsePlanResult, BrowserError>`:
  - Iterates steps in order.
  - After each step, evaluates postconditions (`url_contains`, `text_present`).
  - On failure: captures screenshot, records failing step index, returns error with evidence.
- Register schema `simplicio.browse-plan/v1` in the contract registry.

**Acceptance:** A plan with 3 steps executes in order; a failing postcondition halts execution and returns the step index + screenshot.

---

### 1031-F: `htool_browser_controller.rs` tool surface

**Files:** new `src/htool_browser_controller.rs`, edit `src/main.rs` (or `tool_registry.rs`)
**Work:**
- Tool actions: `browser_ctrl_goto`, `browser_ctrl_click`, `browser_ctrl_fill`, `browser_ctrl_text`, `browser_ctrl_screenshot`, `browser_ctrl_execute_plan`.
- JSON schema for each action.
- Dispatch function `browser_controller_dispatch(action, args_json) -> Result<String, String>`.
- Wire into `main.rs` / tool registry dispatch match arms.
- `check_requirements`: returns available=true only when `#[cfg(feature = "browser")]` is active and a WebDriver URL is configured.

**Acceptance:** `schema` action returns valid JSON; `check_requirements` returns `{"available": false}` without the feature flag.

---

### 1031-G: BR-site product-search skills (depends on #710)

**Files:** new skill definitions (likely YAML/JSON in `skills/` or `contracts/`)
**Work:**
- Product search skills for Mercado Livre, Magalu, Americanas, Shopee.
- Each skill is a `browse-plan/v1` contract with site-specific selectors.
- Domain allowlists scoped per skill.

**Deferred:** depends on 1031-E being complete and real site testing.

---

### 1031-H: Optional chromiumoxide CDP backend

**Files:** new `src/browser_chromiumoxide.rs`, edit `Cargo.toml`
**Work:**
- Add `chromiumoxide = { version = "0.7", optional = true }` behind a `browser-cdp-native` feature.
- Implement `BrowserController` for a `ChromiumoxideController`.
- Selection between fantoccini and chromiumoxide via config (`browser.backend = "webdriver" | "cdp"`).

**Deferred:** milestone 5, after fantoccini path is stable.

## Dependency graph

```
1031-A (feature flag)
  └─> 1031-B (trait + types)','docs/issues/1031.md','b93a02b45e42541c395f57c797b9bd853347f7bc248e023c0ccc5c259fea1f56','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1034.md','project_doc','doc://simplicio-runtime/docs/issues/1034.md','doc: Issue #1034 — TTS/STT/Voice: implementar voice-first nativo (paridade Hermes)','# Issue #1034 — TTS/STT/Voice: implementar voice-first nativo (paridade Hermes)

> Epic decomposition. Design doc: `docs/design/voice-first.md` (research-verified 2026-06-11).

## Status da infraestrutura existente

| Arquivo | Estado |
|---|---|
| `src/voice_stt.rs` | WAV reader + model path resolver (whisper); STT real via shell-out, não in-process |
| `src/tts_provider.rs` | TtsRegistry completo (traits, catalog, format resolution) — sem engines nativos ligados |
| `src/htool_voice_mode.rs` | Audio env detection, hallucination filter, stubs para record/transcribe/play |
| `src/htool_tts_tool.rs` | TTS dispatch tool (shell-out para edge-tts, espeak, etc.) |
| `src/htool_neutts_synth.rs` | NeuTTS zero-shot cloning via subprocess Python |
| `src/voice_command.rs` | VoiceCommand event contract + subscription API (completo) |
| `src/voice_orb.rs` | Terminal orb UI + push-to-talk loop (shell-out STT/TTS) |
| `src/wake_on_voice.rs` | Wake-word detector struct (sem audio real — precisa cpal) |
| `src/gateway/voice_relay.rs` | Gateway voice note relay (shell-out whisper CLI + espeak) |
| `Cargo.toml` | Feature flag `voice = ["dep:whisper-rs"]` existe; sem piper-rs, cpal, rodio, ort |

## Sub-tasks (cada uma = 1 PR independente)

### Sub-task 1: Piper-rs in-process TTS

**Objetivo:** Substituir shell-out `espeak`/`piper` CLI por síntese in-process via `piper-rs` (MIT).

**Escopo:**
- Adicionar `piper-rs` como dependência opcional em `Cargo.toml` sob feature `voice`
- Criar `src/tts_piper.rs`: wrapper que carrega modelo ONNX pt_BR, expõe `fn synthesize(text: &str) -> Result<Vec<i16>, String>`
- Registrar `"piper"` como provider no `TtsRegistry` (`src/tts_provider.rs`)
- Atualizar `htool_tts_tool.rs` para rotear para piper in-process quando feature ativa
- Modelo default: `~/.simplicio-loop/models/piper/pt_BR-faber-medium.onnx` (~63 MB)
- Fallback: se modelo ausente, `Err` com instrução de download (sem panic)

**Deps:** `piper-rs` (MIT), nenhuma GPL

**Testes:** unit test com WAV fixture curto; cfg-gated `#[cfg(feature = "voice")]`

---

### Sub-task 2: Whisper.cpp in-process STT

**Objetivo:** Substituir shell-out `whisper` CLI por transcricao in-process via `whisper-rs`.

**Escopo:**
- `whisper-rs` ja esta em Cargo.toml (feature `voice`); validar que compila
- Criar `src/stt_whisper.rs`: wrapper in-process que usa `whisper-rs::WhisperContext`
  - `fn transcribe(samples: &[f32], lang: &str) -> Result<String, String>`
  - Language hint default `"pt"` (PT-first, conforme design doc)
  - Filtro de alucinacao integrado (reusar `htool_voice_mode::is_whisper_hallucination`)
- Atualizar `voice_stt.rs` para delegar ao wrapper in-process quando feature ativa
- Atualizar `gateway/voice_relay.rs` para usar in-process em vez de `Command::new("whisper")`
- Manter fallback CLI para builds sem feature `voice`

**Deps:** `whisper-rs` (MIT), ja declarado

**Testes:** unit test com fixture WAV 16kHz mono "ola" (cfg-gated)

---

### Sub-task 3: CLI `simplicio voice`

**Objetivo:** Subcomando CLI que inicia o voice orb interativo.

**Escopo:**
- Adicionar subcomando `voice` no parser de args (clap ou manual) em `src/main.rs`
- Delegar para `voice_orb::run_voice_loop()` (ja existe esqueleto)
- Integrar cpal para captura de mic real (feature `voice`)
  - Adicionar `cpal` + `rodio` como deps opcionais em Cargo.toml
  - `src/audio_io.rs`: abstração de captura (16kHz mono f32) e playback
- Conectar pipeline: cpal capture -> VAD -> STT -> spine -> TTS -> rodio playback
- Sem feature `voice`: subcomando imprime erro explicativo e sai

**Deps:** `cpal`, `rodio` (ambos MIT/Apache-2.0)

**Testes:** integration test que verifica subcomando existe e retorna erro sem feature

---

### Sub-task 4: Modality mirroring

**Objetivo:** Reply mirrors inbound modality (audio in -> audio out).

**Escopo:**
- Definir enum `Modality { Text, Audio }` em `src/modality.rs` (ou dentro de conversation context)
- Propagar `Modality` no `ConversationContext` (#692) / turn metadata
- No reply path, se `Modality::Audio`:
  - Sintetizar resposta via TTS (piper ou kokoro conforme tier)
  - Enviar audio + texto (texto fica no session log)
- Helo pode downgrade voice->text para: code blocks, listas longas (>5 items), confianca STT < 0.4
- Gateway voice_relay: setar `Modality::Audio` quando nota de voz chega
- CLI voice orb: sempre `Modality::Audio`

**Deps:** nenhuma nova; usa infra de sub-tasks 1-3

**Testes:** unit test que verifica mirroring e downgrade rules

---

### Sub-task 5: Barge-in / interrupcao

**Objetivo:** Permitir que o usuario interrompa a fala do agente (barge-in).

**Escopo:**
- Adicionar `webrtc-audio-processing` (crate tonari, MIT) como dep opcional
- `src/aec.rs`: wrapper para Acoustic Echo Cancellation (AEC3)
  - Detectar se headphones (skip AEC) vs speaker
  - Cancelar echo do proprio TTS output antes de alimentar VAD
- `src/barge_in.rs`: monitor que durante playback TTS:
  - Roda VAD sobre mic input (pos-AEC)
  - Se voz detectada > 300ms: interrompe playback, inicia nova captura STT
  - Emite evento `BargeIn` para o TurnController (#700)
- Integrar com voice_orb: estado `Speaking` -> detecta barge-in -> `Listening`
- Feature flag: `voice-bargein` (superset de `voice`)

**Deps:** `webrtc-audio-processing` (MIT), `ort` para Silero VAD (se nao estiver ja)

**Testes:** unit test com fixtures simulando overlap audio

---

### Sub-task 6: voice_relay upgrade (gateway)

**Objetivo:** Upgrade do `gateway/voice_relay.rs` de shell-out para engines in-process.

**Escopo:**
- Remover `Command::new("whisper")` e `Command::new("espeak")` quando feature `voice` ativa
- Usar `stt_whisper::transcribe()` (sub-task 2) para transcricao
- Usar `tts_piper::synthesize()` (sub-task 1) para resposta audio
- Adicionar suporte a Kokoro-82M como TTS primario (melhor pt-BR):
  - `src/tts_kokoro.rs`: wrapper ONNX via `ort`, vozes `pf_dora` / `pm_alex`
  - Registrar no TtsRegistry como provider
- Manter shell-out como fallback para builds sem feature
- Atualiza','docs/issues/1034.md','742c2b5c387ed7da86cc1749d866ebd076a979dbea685d00e79e4198401ad93b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1035.md','project_doc','doc://simplicio-runtime/docs/issues/1035.md','doc: Issue #1035 — Skills Hub: descoberta e instalacao de skills (paridade Hermes)','# Issue #1035 — Skills Hub: descoberta e instalacao de skills (paridade Hermes)

## Contexto

O Rust `src/skills_command.rs` implementa apenas operacoes locais (list, enable, disable, run) sobre skills ja instaladas no disco. O Python `tools/skills_hub.py` implementa o pipeline completo do Hermes Skills Hub:

- **9+ source adapters** (GitHubSource, WellKnownSkillSource, UrlSource, SkillsShSource, ClawHubSource, ClaudeMarketplaceSource, LobeHubSource, BrowseShSource, OptionalSkillSource, HermesIndexSource)
- **GitHub auth** (PAT, gh CLI, GitHub App)
- **Index cache** com TTL (skills/index-cache/*.json)
- **Quarantine + scan** pipeline (quarantine_bundle -> scan -> install_from_quarantine)
- **Lock file** (HubLockFile em .hub/lock.json) para rastrear proveniencia
- **Taps manager** (TapsManager, .hub/taps.json) para registros customizados
- **Uninstall** com validacao de path traversal

O TUI `tui/src/components/skillsHub.tsx` ja existe e faz RPC `skills.manage` para o gateway, mas o backend Rust nao responde a acoes de search/install/uninstall.

## Decomposicao em subtasks

### Subtask 1: Modelo de dados e index cache (Rust)
**Arquivo:** `src/skills_hub_models.rs` (novo)

Portar para Rust:
- `SkillMeta` struct (name, description, source, identifier, trust_level, repo, path, tags, extra)
- `SkillBundle` struct (name, files HashMap, source, identifier, trust_level, metadata)
- `HubLockEntry` / `HubLockFile` — leitura/escrita de `.hub/lock.json` via serde_json
- `TapsConfig` — leitura/escrita de `.hub/taps.json`
- Funcoes de validacao de path (`_normalize_bundle_path`, `_validate_skill_name`, `_normalize_lock_install_path`, `_resolve_lock_install_path`) com as mesmas regras de seguranca (rejeitar traversal, symlinks, junctions)
- Index cache: ler/escrever JSONs em `skills/.hub/index-cache/` com TTL de 1h

**Dependencias:** apenas std + serde + serde_json.

**Estimativa:** 1-2 dias.

### Subtask 2: GitHub auth e HTTP client (Rust)
**Arquivo:** `src/skills_hub_github.rs` (novo)

Portar para Rust (usando apenas std):
- `GitHubAuth`: resolver token via GITHUB_TOKEN/GH_TOKEN env var, `gh auth token` subprocess, ou anonimo (sem GitHub App JWT — requer crate extra)
- `github_get()`: GET com retry/backoff em 403/429/5xx, parsing de X-RateLimit-Remaining/Reset
- `guarded_http_get()`: validacao SSRF basica (rejeitar URLs privadas/localhost) antes de fetch

**Nota:** sem httpx disponivel em Rust puro, usar `std::net::TcpStream` com HTTP/1.1 manual ou aceitar dependencia minima (ureq). Se restrito a std+serde, implementar HTTP GET minimo sobre TcpStream com TLS via rustls ou aceitar que este subtask requer uma dependencia adicional. Alternativa: delegar fetch ao Python via subprocess como ponte temporaria.

**Estimativa:** 2-3 dias (depende da decisao sobre HTTP client).

### Subtask 3: Source adapters — GitHub e index-based (Rust)
**Arquivo:** `src/skills_hub_sources.rs` (novo)

Implementar o trait `SkillSource` com:
- `search(query, limit) -> Vec<SkillMeta>`
- `fetch(identifier) -> Option<SkillBundle>`
- `inspect(identifier) -> Option<SkillMeta>`
- `source_id() -> &str`

Adapters prioritarios (por uso):
1. **GitHubSource** — list skills via Contents API, fetch via recursive tree, search com match em nome+descricao+tags. Portar `_list_skills_in_repo`, `_download_directory`, `_download_directory_via_tree`, tree cache.
2. **HermesIndexSource** — ler index pre-construido de `skills/index-cache/` (ja cached localmente).
3. **OptionalSkillSource** — listar skills do proprio repo que nao estao ativadas por default.

Adapters secundarios (podem ficar como stubs inicialmente):
- ClaudeMarketplaceSource, LobeHubSource, WellKnownSkillSource, ClawHubSource, SkillsShSource, BrowseShSource, UrlSource

**Dependencia:** subtask 2 (HTTP client).

**Estimativa:** 3-4 dias.

### Subtask 4: Quarantine, scan e install pipeline (Rust)
**Arquivo:** `src/skills_hub_install.rs` (novo)

Portar:
- `quarantine_bundle()` — escrever arquivos do bundle em `.hub/quarantine/<name>/`, validando cada path relativo
- `install_from_quarantine()` — mover de quarantine para skills dir, atualizar lock file, log de auditoria
- `uninstall_skill()` — resolver path via lock file, validar contra traversal/symlinks/junctions, remover diretorio, atualizar lock file
- `content_hash()` — SHA-256 do conteudo para verificacao de integridade
- Validacao de seguranca: rejeitar symlinks/junctions em cada passo, verificar `is_relative_to` apos resolve

**Dependencia:** subtask 1 (modelos).

**Estimativa:** 2-3 dias.

### Subtask 5: Subcomandos CLI search/install/uninstall (Rust)
**Arquivo:** editar `src/skills_command.rs`

Adicionar ao `SkillManager`:
- `search(query: &str, limit: usize) -> Result<Vec<SkillMeta>, String>` — agregar resultados de todos os sources configurados, deduplicar por identifier preferindo maior trust_level
- `install(identifier: &str) -> Result<String, String>` — fetch -> quarantine -> scan -> install
- `uninstall(name: &str) -> Result<String, String>` — lookup no lock file -> validar path -> remover
- `inspect(identifier: &str) -> Result<SkillMeta, String>` — preview de metadata sem download completo

Registrar no dispatch de main.rs/tool_registry.rs os novos subcomandos.

**Dependencia:** subtasks 1-4.

**Estimativa:** 1-2 dias.

### Subtask 6: Integrar TUI skillsHub.tsx com backend Rust via gateway RPC
**Arquivo:** editar `tui/src/components/skillsHub.tsx` + gateway RPC handler

O TUI ja faz `gw.request(''skills.manage'', { action: ''list'' })`. Adicionar suporte no handler RPC do gateway para:
- `{ action: ''search'', query: ''...'' }` -> chamar SkillManager.search()
- `{ action: ''install'', identifier: ''...'' }` -> chamar SkillManager.install()
- `{ action: ''uninstall'', name: ''...'' }` -> chamar SkillManager.uninstall()
- `{ action: ''inspect'', identifier: ''...'' }` -> chamar SkillManager.inspect()

No TUI, adicionar:
- Campo de busca com input de texto
- Lista de resultados com source/trust badges
- Acao de install com feedback de progres','docs/issues/1035.md','f674cbbc3349c815842ad2d30b372ee0cee60d410d74bf395223e21e557b5831','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1038.md','project_doc','doc://simplicio-runtime/docs/issues/1038.md','doc: Epic #1038: Make partial/not_found audit issues real (2026-06-12)','# Epic #1038: Make partial/not_found audit issues real (2026-06-12)

## Summary

Integration audit found 129 issues where previously closed work was incomplete:
128 classified as **partial** (code exists but is stub/placeholder/fabricated)
and 1 as **not_found** (expected code absent entirely). Each child issue requires
verifying the current state and completing the real implementation.

## Current state

- **Remediation batches b01--b21** have been created under
  `.simplicio-loop/remediation/status/` grouping related findings into actionable
  blocks. Each batch status file tracks which findings are fixed.
- **Handoff documents** exist under `.simplicio-loop/remediation/` for major subsystems
  (mcp, webhook, cron, video, etc.) describing wiring instructions.
- **37 open issues** remain in `.simplicio-loop/issues/open-issues.jsonl` (numbers
  173--256) covering architecture-level features not yet implemented.
- The audit report files referenced in the epic
  (`.simplicio-loop/reports/issue-integration-audit-2026-06-12.md` and
  `.simplicio-loop/reports/issue-remediation-created-2026-06-12.json`) do not exist on
  disk; the remediation tracking lives in the batch status files instead.

## Decomposition

The 129 child issues fall into the following categories, mapped to remediation
batches and source modules. Each batch should be triaged and resolved
independently.

### Phase 1: Already-in-progress batches (b01--b21)

These batches group the 128 partial findings by functional area. Each batch
status file documents which findings are fixed and which remain.

| Batch | Area | Key modules | Est. findings |
|-------|------|-------------|---------------|
| b01 | tools-discover, contracts-smoke, decision-route | main.rs ~1600--3050 | 4 |
| b02 | yool migration, AGI loop | yool_integration.rs, yool_agent_sync.rs | 5--7 |
| b03 | eval harness, audio, scheduler | benchmark_harness.rs, cron_scheduler.rs | 5--7 |
| b04 | curator wiring | curator_agent.rs, curator_parity.rs | 4--6 |
| b05 | IPC, slash commands, trajectory | hermes_parity_ipc.rs, trajectory.rs | 5--7 |
| b06 | parity wiring (Hermes) | hermes_parity_*.rs | 6--8 |
| b07 | benchmark external | benchmark_suite.rs | 3--5 |
| b08 | adapters, service, PR | hermes_parity_adapters.rs, prs_batch.rs | 5--7 |
| b09 | browser legacy | htool_browser_*.rs, browser_provider.rs | 4--6 |
| b10 | exec-graph, sandbox | exec_graph.rs, exec_graph_runtime.rs | 4--6 |
| b11 | human-in-loop, polyglot, convo, Jira | conversation.rs, skill_jira_task_runner.rs | 5--7 |
| b12 | task-source, webhook, WhatsApp | webhook_command.rs, htool_send_message_tool.rs | 5--7 |
| b13 | voice, quality, personal-memory | voice_command.rs, memoria_v2.rs | 5--7 |
| b14 | value-demo, marketing, evidence | growth_*.rs, delivery_certificate.rs | 5--7 |
| b15 | fixtures, quality gates | test_helpers.rs, compilation_gate.rs | 4--6 |
| b16 | recipe, bench, cron, adapter | scheduler.rs, cron_scheduler.rs | 5--7 |
| b17 | trace-zip, lifecycle | trajectory.rs, turn_lifecycle.rs | 4--6 |
| b18 | observability, browser daemon | htool_browser_supervisor.rs | 4--6 |
| b19 | pool, yool-tokio, learn, msg-gateway | tokio_runtime.rs, inference_pool.rs | 5--7 |
| b20 | cron-sched, deploy-env, deep-memory | cron_scheduler.rs, daytona_deploy.rs | 5--7 |
| b21 | verticals, voice, native | voice_command.rs, desktop_app.rs | 4--6 |

### Phase 2: The not_found issue (1 finding)

One finding is classified as **not_found** -- the expected implementation is
entirely absent. This requires:

1. Identifying which capability/contract was expected.
2. Creating the module from scratch (new `src/htool_*.rs` or extending an
   existing module).
3. Wiring into `tool_registry.rs` dispatch and declaring `mod` in `main.rs`.

The specific finding should be located by searching the batch status files for
any entry not yet marked as fixed, or by re-running the audit command.

### Phase 3: Standalone remediation areas

The non-batched status files cover additional subsystem remediations:

| Status file | Area |
|-------------|------|
| browser-tools.md | Browser tool integration |
| cache-compress.md | Cache and compression |
| chatschema.md | Chat schema validation |
| cron.md | Cron scheduling |
| curator.md | Curator agent |
| deploy.md | Deployment pipeline |
| dist-m1.md | M1/ARM distribution |
| email.md | Email platform |
| gchat.md | Google Chat platform |
| hermescompat.md | Hermes compatibility layer |
| hooks.md | Shell hooks |
| hybrid.md | Hybrid state management |
| irc.md | IRC platform |
| login.md | Login/auth command |
| mattermost.md | Mattermost platform |
| mcp.md | MCP server management |
| meet-lsp.md | Google Meet + LSP |
| memory.md | Memory subsystem |
| misc-skills.md | Miscellaneous skills |
| prov-ds-gem-mis.md | Provider: DeepSeek/Gemini/Mistral |
| prov-or-ant.md | Provider: OpenRouter/Anthropic |
| receipt.md | Sealed receipts |
| recovery-pairing.md | Recovery and pairing |
| setup-dump.md | Setup/dump commands |
| skills-plugins.md | Skills and plugins |
| socialops.md | Social operations |
| structconc.md | Structured concurrency |
| teams.md | Teams platform |
| tests-1.md, tests-2.md, tests-3.md | Test suites |
| tui-electron.md | TUI and Electron |
| update.md | Update mechanism |
| video.md | Video pipeline |
| webextract-media.md | Web extraction and media |
| webhook.md | Webhook system |
| websearch.md | Web search |
| yoolsync-traj.md | Yool sync and trajectory |

## Execution strategy

1. **Triage each batch**: Read the batch status file, identify unfixed findings,
   verify current code state.
2. **Fix in priority order**: Batches touching core runtime (b01, b04, b05, b06)
   before peripheral integrations (b09, b12, b18).
3. **One issue per batch finding**: Each finding becomes an individual
   implementable issue -- read the stub, implement real logic using only
   std+serde+serde_json, no `.unwrap()` in production paths.
4. **Validate after each batch**: `cargo check`, `cargo test --locked --quiet`','docs/issues/1038.md','65d249a5774745f0a99c07a07d95cf74f87924c660cde53bb027e3d8c619052e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1039.md','project_doc','doc://simplicio-runtime/docs/issues/1039.md','doc: Issue #1039 — Skills Hub: Discovery and Installation','# Issue #1039 — Skills Hub: Discovery and Installation

## Current State

### What exists

| Layer | File(s) | Lines | Status |
|-------|---------|-------|--------|
| Rust core | `src/skills_command.rs` | 481 | Fully implemented `SkillManager` with scan/list/enable/disable/run + tests. **Declared as `mod` in main.rs (line 282) but never referenced** — `SkillManager` is dead code. |
| Rust htool | `src/htool_skills_hub.rs` | 1191 | Source adapters, lock file, taps, quarantine/install/uninstall, parallel search, cache, audit log. Registered in `tool_registry.rs` (line 496) and dispatched (line 941). |
| Rust htool | `src/htool_skill_manager_tool.rs` | 1266 | Skill manager tool surface. Registered (line 467) and dispatched (line 923). |
| Rust htool | `src/htool_skills_tool.rs` | 1683 | Skills tool. Registered (line 460) and dispatched (line 917). |
| Rust htool | `src/htool_skills_sync.rs` | 1229 | Skills sync. Registered (line 502) and dispatched (line 945). |
| Rust CLI | `src/main.rs` fn `skills()` (line 23608) | ~80 | CLI dispatch for `simplicio skills install|remove|list|index|recall|create|delete|guard|curator`. Implemented but does **not** use `SkillManager` from `skills_command.rs`. |
| Rust | `src/skills_v2.rs` | 410 | Reached via `"skills-v2"` CLI verb (line 2052). |
| Python tools | `tools/skills_hub.py`, `tools/skill_manager_tool.py`, `tools/skills_tool.py`, `tools/skills_sync.py` | — | Original Python implementations; the Rust htool_* modules are ports of these. |
| Python agent | `agent/skill_commands.py`, `agent/skill_bundles.py`, `agent/skill_utils.py`, `agent/skill_preprocessing.py` | — | Agent-side skill helpers used by the Python conversation loop. |
| TUI | `tui/src/components/skillsHub.tsx` | 308 | React component for the skills hub UI. |

### Key gaps

1. **`SkillManager` is not wired into the runtime.** The CLI `skills()` function reimplements discovery/install/remove without using `SkillManager`. The `mod skills_command` declaration is dead.
2. **No end-to-end integration tests** proving that `simplicio skills install <url>` actually downloads, quarantines, scans, and installs a skill bundle through the full htool pipeline.
3. **htool_skills_hub network stubs.** The module header says "All network/IO stubs return Err -- implement when the runtime is wired." Source adapter `fetch()` calls are placeholders.
4. **TUI is disconnected.** `skillsHub.tsx` exists but there is no evidence it communicates with the Rust backend (no IPC/WebSocket/HTTP call to `skills_hub` dispatch).
5. **Python/Rust parity gap.** The Python agent modules (`skill_commands.py`, `skill_bundles.py`) have logic that may not be fully ported to the Rust htool layer.

---

## Decomposition

### Sub-task 1: Wire `SkillManager` into CLI `skills()` function

**Scope:** Replace the ad-hoc discovery logic inside `fn skills()` (main.rs:23608) with calls to `skills_command::SkillManager`. The manager already handles scan, list, enable, disable, run. The CLI verbs `list`, `install`, `remove` should delegate to it.

**Files:** `src/main.rs` (fn `skills`, fn `skills_list_installed`, fn `skills_install`, fn `skills_remove`)

**Estimated effort:** Small (wiring, no new logic).

---

### Sub-task 2: Implement real network fetch in `htool_skills_hub` source adapters

**Scope:** The source adapters (GitHub, ClaWHub, Claude Marketplace, LobEHub) currently return stub errors. Implement actual HTTP fetch using `std::process::Command` calling `curl`/`Invoke-WebRequest` (no external crate constraint), or add a minimal HTTP client if the project already vendors one.

**Files:** `src/htool_skills_hub.rs`

**Estimated effort:** Medium. Requires deciding the HTTP strategy and implementing download + JSON parsing for each source''s API format.

---

### Sub-task 3: End-to-end install/remove flow through quarantine + guard

**Scope:** Connect the pipeline: `skills install <url>` -> htool_skills_hub `fetch` -> `SkillBundle` -> quarantine dir -> `skills guard` scan -> move to installed dir -> `SkillManager.scan()` picks it up. Same for remove: `skills remove <name>` -> delete dir + update lock file.

**Files:** `src/main.rs` (fn `skills_install`, fn `skills_remove`), `src/htool_skills_hub.rs`, `src/skills_command.rs`

**Depends on:** Sub-tasks 1 and 2.

**Estimated effort:** Medium-Large.

---

### Sub-task 4: Fixture-based behavioral tests for the full lifecycle

**Scope:** Integration tests using temp dirs with real SKILL.md manifests and real entrypoint scripts (`.sh`/`.bat`) that prove:
- `scan` discovers skills from disk
- `install` from a local path creates the right directory structure
- `guard` rejects a skill with dangerous patterns
- `run` executes and captures real output
- `remove` cleans up and updates lock
- `enable`/`disable` persists across manager instances

**Files:** New `tests/skills_integration.rs` or extend `src/skills_command.rs` tests.

**Estimated effort:** Medium.

---

### Sub-task 5: Negative tests for missing config/deps

**Scope:** Tests proving graceful errors when:
- Skills dir does not exist (scan returns 0, no crash)
- SKILL.md has no frontmatter (fallback description works)
- Entrypoint binary is missing (clear error, not panic)
- Network fetch fails (source adapter returns descriptive error)
- Lock file is corrupted (re-create rather than crash)

**Files:** `src/skills_command.rs` (tests), `src/htool_skills_hub.rs` (tests)

**Estimated effort:** Small.

---

### Sub-task 6: TUI <-> Rust backend integration

**Scope:** Wire `tui/src/components/skillsHub.tsx` to the Rust backend. Determine the IPC mechanism (the TUI likely uses stdin/stdout JSON-RPC or a local HTTP server) and implement the calls to `skills_hub` dispatch for search, install, remove, list.

**Files:** `tui/src/components/skillsHub.tsx`, possibly a new TUI API route file.

**Depends on:** Sub-tasks 2 and 3.

**Estimated effort:** Medium.

---

### Sub-task 7: Python agent skill_commands parity audit

**Scope:** Diff `agent/skill_com','docs/issues/1039.md','b4291e0f5d22c5f93ef34ac21b80a9b21feb873efea6c3781e843482f9ecd185','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1040.md','project_doc','doc://simplicio-runtime/docs/issues/1040.md','doc: Issue #1040 — Make #1034 real: TTS/STT/Voice voice-first nativo','# Issue #1040 — Make #1034 real: TTS/STT/Voice voice-first nativo

> Parent epic: #1034. Design doc: `docs/design/voice-first.md`.
> This issue tracks the concrete PR decomposition to turn the existing
> stubs and shell-outs into a working end-to-end voice pipeline.

## Current state (2026-06-13)

The codebase has **substantial scaffolding** but zero in-process audio:

- `voice_stt.rs`: WAV reader + model path resolver; STT is shell-out to `whisper` CLI.
- `tts_provider.rs`: Full `TtsRegistry` with traits, catalog, format resolution — no native engine wired.
- `htool_voice_mode.rs`: Environment detection + hallucination filter; record/transcribe/play are stubs returning `Err`.
- `htool_tts_tool.rs`: Dispatch surface for 10 backends — all return `Err("not yet ported")`.
- `htool_neutts_synth.rs`: NeuTTS via Python subprocess.
- `voice_command.rs`: Event contract + subscription API (complete, usable as-is).
- `voice_orb.rs`: Terminal orb UI + push-to-talk loop — delegates to shell-out STT/TTS.
- `wake_on_voice.rs`: Wake-word detector struct with no audio backend (needs cpal).
- `gateway/voice_relay.rs`: Voice note relay using `Command::new("whisper")` + `Command::new("espeak")`.
- `skill_whisper.rs`: Whisper skill (shell-out).
- `Cargo.toml`: Feature `voice = ["dep:whisper-rs"]` declared; no piper-rs, cpal, rodio, ort.

## PR decomposition (6 PRs, dependency order)

### PR 1: Whisper.cpp in-process STT

**Files:** `src/stt_whisper.rs` (new), `src/voice_stt.rs` (update), `src/main.rs` (add mod), `Cargo.toml`

**Work:**
1. Validate `whisper-rs` compiles under feature `voice` (it is declared but may not build cleanly).
2. Create `src/stt_whisper.rs`:
   - `pub fn transcribe(samples: &[f32], lang: &str) -> Result<String, String>`
   - Load `WhisperContext` lazily via `OnceLock<Result<WhisperContext, String>>`
   - Model path via existing `voice_stt::model_path()`
   - Integrate hallucination filter from `htool_voice_mode::is_whisper_hallucination`
   - Language hint default `"pt"` (PT-first per design doc)
3. Update `voice_stt.rs`: add `pub fn transcribe_in_process(path: &Path) -> Result<String, String>` that reads WAV via existing `read_wav_16k_mono` then calls `stt_whisper::transcribe`.
4. Gate everything behind `#[cfg(feature = "voice")]`.

**Deps:** `whisper-rs` (already in Cargo.toml)
**Test:** unit test with short WAV fixture, cfg-gated.
**Estimated size:** ~200 lines new code.

---

### PR 2: Piper-rs in-process TTS (parallelizable with PR 1)

**Files:** `src/tts_piper.rs` (new), `src/tts_provider.rs` (update), `src/htool_tts_tool.rs` (update), `src/main.rs` (add mod), `Cargo.toml`

**Work:**
1. Add `piper-rs` as optional dep under feature `voice` in `Cargo.toml`.
2. Create `src/tts_piper.rs`:
   - `pub fn synthesize(text: &str) -> Result<Vec<i16>, String>`
   - Lazy model load from `~/.simplicio-loop/models/piper/pt_BR-faber-medium.onnx`
   - `Err` with download instructions if model missing (no panic)
3. Register `"piper"` in `TtsRegistry` as a native provider (it is already in `BUILTIN_NAMES`).
4. Update `htool_tts_tool.rs` piper match arm: call `tts_piper::synthesize` when feature `voice` is active, fall through to shell-out otherwise.

**Deps:** `piper-rs` (MIT) — new dependency
**Test:** unit test with short text, cfg-gated.
**Estimated size:** ~150 lines new code.

---

### PR 3: Audio I/O + CLI `simplicio voice` (depends on PR 1 + PR 2)

**Files:** `src/audio_io.rs` (new), `src/voice_orb.rs` (update), `src/main.rs` (update), `Cargo.toml`

**Work:**
1. Add `cpal` + `rodio` as optional deps under feature `voice`.
2. Create `src/audio_io.rs`:
   - `pub fn capture_mic_16k_mono() -> Result<Receiver<Vec<f32>>, String>` — cpal input stream, 16kHz mono f32
   - `pub fn play_pcm_i16(samples: &[i16], sample_rate: u32) -> Result<(), String>` — rodio playback
   - Device enumeration: `pub fn list_audio_devices() -> Vec<String>`
3. Update `voice_orb.rs`: replace shell-out record/play with `audio_io` calls when feature `voice` active.
4. Add `voice` subcommand in `main.rs` arg parsing: delegates to `voice_orb::run_voice_loop()`.
5. Without feature `voice`: subcommand prints error with `--features voice` hint and exits.

**Deps:** `cpal` (Apache-2.0), `rodio` (MIT/Apache-2.0) — new dependencies
**Test:** integration test verifying subcommand exists; audio round-trip test cfg-gated.
**Estimated size:** ~250 lines new code.

---

### PR 4: Modality mirroring (depends on PR 3)

**Files:** `src/modality.rs` (new), `src/voice_orb.rs` (update), `src/gateway/voice_relay.rs` (update), `src/main.rs` (add mod)

**Work:**
1. Create `src/modality.rs`:
   - `pub enum Modality { Text, Audio }`
   - `pub fn should_downgrade_to_text(reply: &str, stt_confidence: f64) -> bool` — returns true for code blocks, lists >5 items, confidence <0.4
2. Wire `Modality` into conversation context / turn metadata (touch `ConversationContext` if #692 is landed, otherwise standalone field).
3. Update `voice_orb.rs`: set `Modality::Audio` on every voice turn; on reply, call TTS if modality is Audio.
4. Update `gateway/voice_relay.rs`: set `Modality::Audio` when voice note arrives; generate audio reply via TTS.

**Deps:** none new
**Test:** unit tests for downgrade rules.
**Estimated size:** ~120 lines new code.

---

### PR 5: Gateway voice_relay upgrade (depends on PR 1 + PR 2 + PR 4)

**Files:** `src/gateway/voice_relay.rs` (update), `src/tts_kokoro.rs` (new), `src/tts_provider.rs` (update), `src/main.rs` (add mod), `Cargo.toml`

**Work:**
1. Replace `Command::new("whisper")` with `stt_whisper::transcribe()` (from PR 1) behind `#[cfg(feature = "voice")]`.
2. Replace `Command::new("espeak")` with `tts_piper::synthesize()` (from PR 2) behind `#[cfg(feature = "voice")]`.
3. Add Kokoro-82M as primary TTS for pt-BR:
   - Add `ort` as optional dep under feature `voice-kokoro`.
   - Create `src/tts_kokoro.rs`: ONNX inference wrapper for Kokoro-82M with voices `pf_dora` / `pm_alex`.
   - Register in `TtsRegistry`.
4. Priority: Kokoro (if','docs/issues/1040.md','e2ccdf64136ac4f853d12d2add7ed16195378926302be346e210ad579fe81503','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1117-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1117-plan.md','doc: Plan: #1117 — Native git integration (git2/libgit2)','# Plan: #1117 — Native git integration (git2/libgit2)

## Goal

Replace all shell-based git operations (`Command::new("git")`) in
`src/git_integrations.rs` with the `git2` crate (Rust bindings for libgit2),
eliminating the runtime dependency on a system-installed `git` binary for core
git operations.

## Current state

- `src/git_integrations.rs` — 1558 lines.
- `git2` is **not** listed in `Cargo.toml`.
- Shell calls via `Command::new("git")` occur in:
  - `git_run()` (line 14) — used by `NativeGit::status`, `diff`, `log`.
  - `blame()` (line 106) — standalone blame function.
- `Command::new("sqlite3")` (line 258) is unrelated to git and out of scope.

## Sub-tasks

### 1. Add `git2` dependency to `Cargo.toml`
- Add `git2 = "0.19"` under `[dependencies]`.
- Run `cargo check` to confirm it compiles.
- **Files:** `Cargo.toml`

### 2. Rewrite `NativeGit::status` with `git2`
- Use `git2::Repository::open` + `repo.statuses(None)` to get file statuses.
- Map `git2::Status` flags to the two-letter porcelain codes for backward
  compatibility.
- Remove dependence on `git_run`.
- **Files:** `src/git_integrations.rs`

### 3. Rewrite `NativeGit::diff` with `git2`
- Use `repo.diff_index_to_workdir` (or `diff_tree_to_index` for staged changes).
- Return the patch text via `diff.print(DiffFormat::Patch, ...)`.
- **Files:** `src/git_integrations.rs`

### 4. Rewrite `NativeGit::log` with `git2`
- Use `repo.revwalk()` to iterate commits, extract hash/author/message.
- Respect the `count` parameter.
- **Files:** `src/git_integrations.rs`

### 5. Rewrite `blame()` with `git2`
- Use `repo.blame_file()` to get `BlameHunk` data.
- Map hunk fields to the existing `BlameInfo` struct.
- **Files:** `src/git_integrations.rs`

### 6. Remove `git_run` helper
- After all callers are converted, delete the `git_run` function and the
  `use std::process::Command` import (if no other caller remains).
- **Files:** `src/git_integrations.rs`

### 7. Add integration tests with temp repo fixtures
- Use `tempfile::TempDir` + `git2::Repository::init` to create real repos.
- Test `status`, `diff`, `log`, `blame` against known commits.
- **Files:** `tests/git2_integration.rs` (new)

### 8. Wire to runtime surface (if needed)
- Verify `git_integrations_command` and any tool-registry match arms still work
  with the new implementation. Adjust if signatures changed.
- **Files:** `src/git_integrations.rs`, possibly `src/tool_registry.rs`

## Ordering and dependencies

```
1 ──> 2 ──> 3 ──> 4 ──> 5 ──> 6 ──> 7 ──> 8
```

Sub-tasks 2-5 can be done in any order after 1, but sequential delivery keeps
each PR reviewable. Sub-task 6 requires all of 2-5 complete. Sub-tasks 7 and 8
depend on the conversions being done.

## Risk notes

- `git2` bundles libgit2 via `libgit2-sys`; this adds C compilation to the
  build. The project already has C/C++ deps (`rusqlite` bundled, `llama-cpp-2`,
  `whisper-rs`), so toolchain requirements do not change.
- Porcelain status codes must match exactly to avoid breaking downstream
  consumers that parse the two-letter codes.','docs/issues/1117-plan.md','e35562d80acdcbddc6ed959ea664195be60735ba655c72aba9dfd96898c26b84','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1119-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1119-plan.md','doc: Epic #1119: Built-in REPL Rhai/WASM','# Epic #1119: Built-in REPL Rhai/WASM

## Current State

- **Rhai**: No dependency, no code. Completely absent from the codebase.
- **WASM**: `PluginKind` enum exists in `src/plugins/registry.rs` with `.wasm` manifest discovery, but actual WASM execution is stubbed with "not implemented" errors. No `wasmtime` dependency in `Cargo.toml`.
- **REPL**: A basic REPL loop exists (with optional `reedline` feature for rich editing), but it only handles CLI commands -- no script evaluation engine.

## Sub-issues

### Sub-issue 1: Add Rhai scripting engine
**Files**: `Cargo.toml`, `src/plugins/rhai_engine.rs` (new), `src/plugins/mod.rs`
- Add `rhai` crate as an optional dependency behind a `scripting` feature flag.
- Create `rhai_engine.rs` with:
  - `RhaiEngine` struct wrapping `rhai::Engine` with Simplicio-specific API bindings.
  - Functions to register host-side callbacks (memory access, plugin queries, tool invocation).
  - `eval_script(code: &str) -> Result<String, String>` entry point.
- Unit tests for expression evaluation, error handling, and host callback registration.

### Sub-issue 2: Implement WASM plugin execution via wasmtime
**Files**: `Cargo.toml`, `src/plugins/wasm_runner.rs` (new), `src/plugins/registry.rs`
- Add `wasmtime` crate as an optional dependency behind a `wasm-plugins` feature flag.
- Create `wasm_runner.rs` with:
  - `WasmRunner` struct that loads, validates, and executes `.wasm` modules.
  - Host-import definitions for Simplicio ABI (memory read/write, tool dispatch).
  - Sandboxed execution with fuel/memory limits.
- Replace existing "not implemented" stubs in `registry.rs` with real `WasmRunner` calls.
- Tests: load a trivial `.wasm` module, verify sandboxing limits, test error paths.

### Sub-issue 3: Wire Rhai REPL mode into CLI
**Files**: `src/main.rs`, `src/repl.rs` (or existing REPL module)
- Add `simplicio repl --lang rhai` (or `simplicio rhai`) CLI subcommand.
- Implement interactive REPL loop:
  - Read input (multiline support with `reedline` when available).
  - Evaluate via `RhaiEngine::eval_script`.
  - Print result or formatted error.
  - Support `:load <file>`, `:reset`, `:quit` meta-commands.
- Integration test: feed script lines via stdin, assert expected stdout.

### Sub-issue 4: WASM REPL and unified script dispatch
**Files**: `src/main.rs`, `src/repl.rs`
- Extend REPL to support `--lang wasm` mode that loads and runs `.wasm` modules interactively.
- Create a unified `ScriptDispatcher` trait so both Rhai and WASM share the same REPL shell.
- Add `simplicio run <file>` command that auto-detects `.rhai` vs `.wasm` by extension.
- End-to-end tests for both engines through the CLI surface.

## Dependency Order

```
Sub-issue 1 (Rhai engine) ──┐
                             ├──> Sub-issue 3 (Rhai REPL CLI)
Sub-issue 2 (WASM runner) ──┤
                             └──> Sub-issue 4 (WASM REPL + unified dispatch)
```

Sub-issues 1 and 2 are independent and can be worked in parallel.
Sub-issues 3 and 4 depend on their respective engines.

## Feature Flags

All new dependencies are optional to preserve the minimal default binary footprint:
- `scripting` -- enables Rhai engine
- `wasm-plugins` -- enables wasmtime WASM execution
- `rich-repl` -- already exists, enhances REPL line editing (orthogonal)','docs/issues/1119-plan.md','30de7b354b7d9d840ab1ff7fd0dca1439e5a88fcacfba1710d64ee754b9fb663','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1120-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1120-plan.md','doc: Epic #1120 — Real Telemetry/Observability with OpenTelemetry','# Epic #1120 — Real Telemetry/Observability with OpenTelemetry

## Current State

- Custom in-memory `Telemetry` struct in `src/infra_advanced.rs` (lines 647-919) with OTLP-shaped JSON serialization
- No `opentelemetry` crate in `Cargo.toml`; no HTTP/gRPC exporter
- No `TracerProvider` or `MeterProvider` from the real OpenTelemetry SDK
- Usage limited to tests and demo prints
- Python observability plugins exist: `plugins/observability/nemo_relay/` and `plugins/observability/langfuse/`

## Decomposition

### Sub-task 1: Add OpenTelemetry crates to Cargo.toml
**Files:** `Cargo.toml`
**Work:**
- Add `opentelemetry = "0.27"` and `opentelemetry-otlp = { version = "0.27", features = ["http-proto", "reqwest-client"] }` as optional dependencies behind an `otel` feature flag
- Add `opentelemetry_sdk = "0.27"` for `TracerProvider` / `MeterProvider`
- Keep the default build unchanged (feature-gated so binary size is unaffected unless opted in)

### Sub-task 2: Replace custom Telemetry struct with real SDK TracerProvider
**Files:** `src/infra_advanced.rs`
**Work:**
- Behind `#[cfg(feature = "otel")]`, replace the custom `Telemetry` struct with a thin wrapper around `opentelemetry_sdk::trace::TracerProvider`
- Keep the existing struct available under `#[cfg(not(feature = "otel"))]` for backward compatibility
- Map existing `TelemetrySpan`, `TelemetryMetric` to real OTel `Span` and metric instruments
- Preserve the OTLP-shaped JSON serialization as a fallback/debug mode

### Sub-task 3: Wire tracing into runtime dispatch (main.rs)
**Files:** `src/main.rs`
**Work:**
- Initialize `TracerProvider` early in `main()` when `otel` feature is enabled
- Read endpoint from `OTEL_EXPORTER_OTLP_ENDPOINT` env var (standard OTel convention)
- Fail closed: if the env var is set but the exporter cannot connect, log a warning and continue without telemetry (do not crash)
- Shut down the provider gracefully on exit (`provider.shutdown()`)
- Instrument key dispatch points with `tracer.start("operation_name")`

### Sub-task 4: Configurable exporter endpoint with fail-closed behavior
**Files:** `src/infra_advanced.rs`, `src/main.rs`
**Work:**
- Support `OTEL_EXPORTER_OTLP_ENDPOINT` (default), plus a `simplicio.toml` config key `[telemetry] endpoint = "..."` 
- If no endpoint configured, telemetry is silently disabled (no-op)
- If endpoint configured but unreachable, log error and fall back to no-op (fail closed, never panic)
- Support `OTEL_SERVICE_NAME` defaulting to `"simplicio-runtime"`

### Sub-task 5: Reconcile with Python observability plugins
**Files:** `plugins/observability/nemo_relay/__init__.py`, `plugins/observability/langfuse/__init__.py`
**Work:**
- Document how the Rust-side OTel traces relate to the Python plugin traces
- If nemo_relay forwards spans to an OTLP collector, ensure no duplicate spans when both Rust and Python layers are active
- Add a `trace_id` propagation mechanism: Rust runtime passes W3C `traceparent` header to Python plugin subprocess via env var
- Update plugin README with configuration examples

### Sub-task 6: Behavioral tests with mock collector
**Files:** `tests/test_otel.rs` (new)
**Work:**
- Create a minimal mock OTLP HTTP collector (bind to `127.0.0.1:0`, accept `/v1/traces`)
- Test that spans are exported when endpoint is configured
- Test that no panic occurs when endpoint is unreachable (fail-closed)
- Test that no spans are exported when endpoint is unconfigured (no-op mode)
- Test graceful shutdown flushes pending spans

## Estimated Effort

| Sub-task | Size | Dependencies |
|----------|------|-------------|
| 1. Add crates | S | None |
| 2. Replace Telemetry | L | 1 |
| 3. Wire main.rs | M | 1, 2 |
| 4. Config endpoint | M | 1, 2 |
| 5. Python plugins | M | 3, 4 |
| 6. Tests | M | 2, 3, 4 |

**Total:** Epic (L-XL), recommend splitting into 3-4 PRs:
- PR A: Sub-tasks 1 + 2 (foundation)
- PR B: Sub-tasks 3 + 4 (integration)
- PR C: Sub-task 5 (plugin reconciliation)
- PR D: Sub-task 6 (tests)','docs/issues/1120-plan.md','1d60157b07d60071cf802bc94c6be25a627e83c35af2abb1b58e6908e16b3e78','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1121-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1121-plan.md','doc: Epic #1121: Binary diff/patch for large edits','# Epic #1121: Binary diff/patch for large edits

## Current State

`infra_advanced.rs` L513-519 contains a trivial `binary_diff` stub that only returns
byte positions where `new` differs from `old`. It does not handle length changes,
has no patch format, no apply function, and is not wired into the CLI or tool registry.

## Sub-tasks

### 1. Core diff algorithm (`infra_advanced.rs`)
- Replace the naive byte-compare with a real binary diff algorithm (bsdiff-style or
  vcdiff-style, implemented in pure Rust with std only).
- Produce a `BinaryPatch` struct containing copy/insert operations.
- Handle files of different lengths (insertions, deletions).
- All error paths must use `Result`, no `.unwrap()` in production code.

### 2. Patch serialization format (`infra_advanced.rs`)
- Define a compact binary serialization for `BinaryPatch` (magic bytes + version +
  operations list).
- Implement `BinaryPatch::serialize(&self) -> Vec<u8>` and
  `BinaryPatch::deserialize(data: &[u8]) -> Result<Self, String>`.
- Include a checksum of the original file for validation on apply.

### 3. Patch-apply function (`infra_advanced.rs`)
- Implement `binary_patch_apply(old: &[u8], patch: &BinaryPatch) -> Result<Vec<u8>, String>`.
- Validate source checksum before applying.
- Roundtrip property: `apply(old, diff(old, new)) == new` for all inputs.

### 4. Integration with parallel_edit (`parallel_edit.rs`)
- Add a `BinaryDiff` variant to the parallel edit operation enum.
- Wire binary diff/patch into the parallel edit pipeline so large file edits
  can use binary patches instead of full-content replacement.
- Respect existing conflict detection and lock_range infrastructure.

### 5. CLI dispatch (`main.rs`)
- Add `binary-diff` and `binary-patch-apply` subcommands.
- `binary-diff <old-file> <new-file> -o <patch-file>` -- produce a patch file.
- `binary-patch-apply <old-file> <patch-file> -o <new-file>` -- apply a patch.
- Proper error handling and exit codes.

### 6. Tool registry registration (`tool_registry.rs`)
- Register `binary_diff` and `binary_patch_apply` as tools in the registry.
- Define JSON schema for input/output (base64-encoded binary data or file paths).

### 7. Tests
- Unit tests for diff/patch roundtrip on: empty files, identical files, single-byte
  change, insertion, deletion, complete replacement, large random data.
- Negative tests: corrupted patch, wrong source file, truncated patch data.
- Integration test: CLI end-to-end with temp files.

## Dependencies

- Sub-tasks 1-3 are sequential (each builds on the previous).
- Sub-tasks 4, 5, 6 depend on sub-tasks 1-3.
- Sub-task 7 depends on all others.

## Constraints

- std + serde + serde_json only (no external diff crates).
- No `.unwrap()` in production code.','docs/issues/1121-plan.md','d4a504145c4fd87c15e3d31cfa9dc3043258949a883d13c58fa0484eebf6ecb5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1124-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1124-plan.md','doc: Epic #1124 — Agent Sandbox / Isolation: Decomposition Plan','# Epic #1124 — Agent Sandbox / Isolation: Decomposition Plan

## Current State

Overlay filesystem isolation is **not implemented end-to-end**. Partial pieces exist across multiple modules:

| Module | What exists | Gap |
|---|---|---|
| `src/file_safety.rs` | Write-deny lists, read-block checks, sandbox-mirror warnings | Soft/defense-in-depth only; no actual FS overlay enforcement |
| `src/daytona_deploy.rs` | CLI wrapper for `daytona create/sandbox` | Shells out to external CLI; no overlay FS integration |
| `.simplicio-loop/sandbox-policy.json` | Schema with `trust=restricted` | Schema-only; not enforced at runtime |
| `src/htool_delegate_tool.rs` | Isolated context descriptions for sub-agents | No FS overlay applied to spawned sub-agents |
| `src/htool_code_execution_tool.rs` | Temp dir for code execution | Uses plain temp dirs, not overlay FS |
| `src/capability_broker.rs` | Capability request/approve/deny/revoke/run lifecycle | Policy from sandbox-policy.json not wired through |

## Decomposition into Sub-Issues

### Sub-issue 1: Define and implement overlay filesystem layer

**Files:** new `src/overlay_fs.rs`

- Define `OverlayFs` struct: upper (writable) layer backed by a temp dir, lower (read-only) layer pointing to the real workspace.
- On Linux: use `mount -t overlay` via `unshare` (no root needed with user namespaces).
- On macOS/Windows: use a copy-on-write directory approach (copy file on first write, redirect all writes to upper layer).
- Provide `OverlayFs::mount()`, `OverlayFs::unmount()`, `OverlayFs::merged_path()`.
- All operations return `Result<_, String>` — no `.unwrap()`.
- Unit tests: create overlay, write a file, verify original untouched, verify written file visible in merged view.

**Estimate:** 3-5 days

### Sub-issue 2: Wire sandbox-policy.json enforcement through capability_broker

**Files:** `src/capability_broker.rs`, `.simplicio-loop/sandbox-policy.json`

- Parse `sandbox-policy.json` at startup (serde_json).
- Add `is_capability_allowed(capability: &str, scope: &str) -> bool` that checks the policy.
- In `capability_run()`, enforce the policy before executing: if `trust == "restricted"`, deny capabilities not explicitly listed.
- Default-deny: any capability not in the allowlist is rejected.
- Add `--enforce-policy` flag to `capability run` subcommand.

**Estimate:** 2-3 days

### Sub-issue 3: Integrate overlay FS into file_safety.rs write guards

**Files:** `src/file_safety.rs`, `src/overlay_fs.rs`

- Replace soft warnings (`get_sandbox_mirror_warning`, `get_container_mirror_warning`) with hard enforcement when overlay is active.
- `is_write_denied()` should check if overlay FS is mounted; if so, redirect writes to upper layer instead of denying.
- When overlay is not available, fall back to current deny-list behavior with explicit error messages.

**Estimate:** 1-2 days

### Sub-issue 4: Integrate overlay FS into delegate_tool sub-agent spawning

**Files:** `src/htool_delegate_tool.rs`, `src/overlay_fs.rs`

- When spawning a sub-agent, mount an overlay FS for its workspace.
- Sub-agent writes go to the overlay upper layer; reads see merged view.
- On sub-agent completion, the orchestrator can inspect the upper layer for changes before merging.
- Add `isolation_mode` field to delegate tool input schema: `"overlay"` (default when available), `"tempdir"` (fallback), `"none"` (explicit opt-out).

**Estimate:** 2-3 days

### Sub-issue 5: Integrate overlay FS into code_execution_tool

**Files:** `src/htool_code_execution_tool.rs`, `src/overlay_fs.rs`

- Replace plain temp dir with overlay FS mount.
- Code execution sees project files read-only; writes are captured in upper layer.
- On execution completion, discard the overlay (no persistent side effects).
- Fallback to current temp dir behavior if overlay mount fails, with a warning.

**Estimate:** 1-2 days

### Sub-issue 6: Behavioral tests proving isolation

**Files:** new `tests/sandbox_isolation.rs`

- **Positive tests:** agent writes are contained in overlay upper layer; original files unchanged.
- **Negative tests:** attempts to escape overlay (symlink traversal, `..` path components, hardlink to outside, mount namespace escape) all fail.
- **Policy tests:** restricted capabilities are denied; allowed capabilities succeed.
- **Integration test:** delegate_tool spawns sub-agent in overlay, sub-agent writes file, orchestrator verifies file only in upper layer.

**Estimate:** 2-3 days

### Sub-issue 7: Threat model documentation

**Files:** new `docs/threat-model-sandbox.md`

- Document trust boundaries: orchestrator vs. sub-agent, user workspace vs. overlay.
- Enumerate attack vectors: symlink escape, path traversal, race conditions (TOCTOU), capability escalation.
- Document mitigations for each vector.
- Document platform-specific limitations (no user namespaces on macOS, Windows limitations).
- Document the fallback behavior when overlay is unavailable.

**Estimate:** 1-2 days

### Sub-issue 8: Remove or convert stubs/placeholders to explicit errors

**Files:** all target files

- Audit all `todo!()`, `unimplemented!()`, placeholder comments, and no-op branches.
- Convert each to either: (a) a real implementation (from sub-issues above), or (b) an explicit `Err(...)` with a clear message explaining what is not yet supported.
- Remove `#[allow(dead_code)]` from modules that are now wired in.

**Estimate:** 1 day

## Suggested Implementation Order

```
Sub-issue 1 (overlay_fs core)
    |
    +---> Sub-issue 3 (file_safety integration)
    +---> Sub-issue 4 (delegate_tool integration)
    +---> Sub-issue 5 (code_execution integration)
    |
Sub-issue 2 (policy enforcement) --- can proceed in parallel with 1
    |
    +---> Sub-issue 6 (behavioral tests) --- after 1-5
    |
Sub-issue 7 (threat model) --- can proceed in parallel
Sub-issue 8 (stub cleanup) --- after 1-5
```

## Total Estimate

15-21 days of engineering effort.

## Dependencies

- `serde` + `serde_json` (already in use)
- No new external crates requir','docs/issues/1124-plan.md','d7b56100b6a9239145b32da89b29abbddc5cef67dbc01ecfb8c528283f85e321','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1125-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1125-evidence.md','doc: Issue #1125 — Test Impact Analysis: Evidence','# Issue #1125 — Test Impact Analysis: Evidence

## Status: Already Implemented

### Core function

- **`affected_by_change()`** — `src/infra_advanced.rs:256-265`
  Accepts a changed file path and a `HashMap<String, Vec<String>>` test map,
  returns the list of test names whose dependency sets contain the changed file.

### Feature registration

- `src/infra_advanced.rs:202` — `test_impact` listed in the JSON feature array
  returned by the infra-advanced schema.
- `src/infra_advanced.rs:208` — `test_impact` listed in the human-readable
  feature summary string.
- `src/main.rs:71303` — `test_impact` included in the CLI schema output for
  `simplicio infra-advanced`.

### Section marker

- `src/infra_advanced.rs:255` — `// ===== #886: Test Impact Analysis =====`','docs/issues/1125-evidence.md','220bbb83e2b26aafd6ca710a48a8e5b44eabcdc495f69526819f3ec73d00474a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1127-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1127-plan.md','doc: Epic #1127 — Native LSP client embutido','# Epic #1127 — Native LSP client embutido

## Status Quo

Four LSP client modules exist (`lsp_client.rs`, `lsp_protocol.rs`, `lsp_manager.rs`, `lsp_servers.rs`) but **none are wired into `main.rs`** — only the old `lsp_server.rs` (framing-only, line 131) is declared. All four modules carry `#![allow(dead_code)]` and depend on unimplemented siblings (`lsp_workspace`, `lsp_install`).

## Decomposition

### Sub-task 1: Implement `lsp_workspace.rs` stub
- **What:** Create `src/lsp_workspace.rs` with `nearest_root(start, markers, ceiling, excludes) -> Option<PathBuf>` — walks upward from `start` looking for marker files.
- **Why:** `lsp_servers.rs` calls `nearest_root` via a local stub that must be replaced by a real module.
- **Files:** `src/lsp_workspace.rs` (new)

### Sub-task 2: Implement `lsp_install.rs` stub
- **What:** Create `src/lsp_install.rs` with `try_install(server_id) -> Result<PathBuf, ...>` — checks if a language server binary is available, returns its path. Initial version: no auto-download, just `which`/`where` lookup.
- **Why:** `lsp_servers.rs` calls `try_install` to resolve server binaries.
- **Files:** `src/lsp_install.rs` (new)

### Sub-task 3: Wire all LSP modules into `main.rs`
- **What:** Add `mod lsp_protocol; mod lsp_client; mod lsp_servers; mod lsp_workspace; mod lsp_install; mod lsp_manager;` to `main.rs`. Fix any `use super::` / `use crate::` import issues. Remove inline stubs in `lsp_servers.rs` (replace with `use crate::lsp_workspace::nearest_root` etc.). Ensure `cargo check` passes.
- **Why:** Modules exist but are dead code — they must be part of the module tree to compile.
- **Files:** `src/main.rs`, `src/lsp_servers.rs`, `src/lsp_client.rs`

### Sub-task 4: Integrate `LspService` into `AppState` / runtime startup
- **What:** Add an `Option<LspService>` field to `AppState` (or equivalent runtime context struct). Initialize it at startup when the `lsp` feature/config is enabled. Wire shutdown into the graceful-exit path.
- **Why:** The manager must be alive for the coding loop to request diagnostics.
- **Files:** `src/main.rs` (or `src/app_state.rs`), `src/lsp_manager.rs`

### Sub-task 5: Expose CLI surface (`simplicio lsp status`)
- **What:** Add a `lsp` subcommand (or `lsp status`) that prints active LSP clients, their workspace roots, and connection state. Wire into existing CLI dispatch.
- **Why:** Observability — users and the agent need to see what servers are running.
- **Files:** `src/main.rs` (CLI dispatch), `src/lsp_manager.rs`

### Sub-task 6: Connect to coding-loop dispatch
- **What:** After every file edit in the coding loop, call `lsp_service.get_diagnostics_sync(file, content)` and surface errors/warnings. Wire into `tool_registry.rs` or the edit-tool handler.
- **Why:** This is the primary value — lint-after-edit without external tooling.
- **Files:** `src/tool_registry.rs`, `src/htool_*.rs` (edit tools), `src/lsp_manager.rs`

### Sub-task 7: Add behavioral and negative tests
- **What:** Unit tests for `lsp_protocol` (encode/decode round-trip, error cases), integration tests for `lsp_client` (mock server via `tokio::process`), negative tests for broken-set handling in `lsp_manager`.
- **Why:** The modules have zero test coverage today.
- **Files:** inline `#[cfg(test)]` modules, possibly `tests/lsp_integration.rs`

### Sub-task 8: Remove `#![allow(dead_code)]` and placeholder stubs
- **What:** Final cleanup — remove all `#![allow(dead_code)]` from LSP modules, delete any remaining inline stubs, audit public API surface.
- **Why:** Hygiene — dead_code suppression hides real issues once modules are wired in.
- **Files:** all `src/lsp_*.rs`

## Dependency Order

```
Sub-task 1 ─┐
Sub-task 2 ─┤
            ├─► Sub-task 3 ─► Sub-task 4 ─┬─► Sub-task 5
            │                              ├─► Sub-task 6
            │                              └─► Sub-task 7 ─► Sub-task 8
```

## Estimated Effort

8 sub-tasks, ~2-4h each depending on test depth. Sub-tasks 1-3 can be done in a single PR. Sub-tasks 5 and 6 are independent once 4 lands.','docs/issues/1127-plan.md','121b767a0c919d3342df5e7b23e73085d92056de0d7285e5729da68221d134c7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1131-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1131-plan.md','doc: Epic #1131: Parallel Edit Orchestration — Decomposition Plan','# Epic #1131: Parallel Edit Orchestration — Decomposition Plan

## Status Summary

**Audit classification:** partial — code exists but is not proven end-to-end.

### Landed Modules (exist in `src/`)

| Module | File | Tests |
|--------|------|-------|
| parallel_edit | `parallel_edit.rs` | ~15 tests |
| line_range_lock | `line_range_lock.rs` | ~7 tests |
| line_shift | `line_shift.rs` | present |
| edit_transaction | `edit_transaction.rs` | present |
| compilation_gate | `compilation_gate.rs` | present |
| agent_broadcast | `agent_broadcast.rs` | present |
| distributed_lock | `distributed_lock.rs` | present |

### Missing Modules (not found in `src/`)

| Module | Purpose |
|--------|---------|
| ast_context.rs | AST-aware context for edits (scope/function boundaries) |
| dependency_graph.rs | File-level dependency tracking for cascading edits |
| memmap_index.rs | Memory-mapped index for large file line lookups |
| offset_index.rs | Byte-offset to line-number translation layer |

---

## Decomposition into Sub-Issues

### Phase 1: Audit & Stabilize Existing Modules

**Sub-issue 1.1:** Inventory and verify landed code
- Run `cargo test` on the 7 existing modules
- Confirm all 15 parallel_edit tests and 7 line_range_lock tests pass
- Document any reverted or dead code paths
- Estimated effort: 1 session

**Sub-issue 1.2:** Add missing test coverage for under-tested modules
- line_shift: add shift-overlap and negative-shift tests
- edit_transaction: add rollback and conflict-resolution tests
- compilation_gate: add timeout and concurrent-gate tests
- agent_broadcast: add multi-subscriber fan-out tests
- distributed_lock: add lock-expiry and re-entrance tests
- Estimated effort: 2 sessions

### Phase 2: Implement Missing Modules

**Sub-issue 2.1:** `offset_index.rs` — Byte-offset to line-number index
- Builds a line-start offset table from file bytes
- O(log n) lookup: byte offset -> line number and vice versa
- No external deps (std only)
- Estimated effort: 1 session

**Sub-issue 2.2:** `memmap_index.rs` — Memory-mapped line index
- Decision gate: if files are always < 10 MB, de-scope this and use offset_index with `std::fs::read`
- If needed: use `memmap2` crate (or implement with `std::fs::File` + manual paging)
- Provides `LineIndex` trait that offset_index also implements
- Estimated effort: 1-2 sessions (or 0 if de-scoped)

**Sub-issue 2.3:** `ast_context.rs` — AST-aware edit context
- Given a file path + line range, return the enclosing function/struct/impl block
- Use tree-sitter bindings or a simplified brace-matching heuristic
- Decision gate: tree-sitter adds a native dep; brace-matching is simpler but less accurate
- Estimated effort: 2 sessions

**Sub-issue 2.4:** `dependency_graph.rs` — File dependency tracker
- Track `mod`, `use`, and `pub use` relationships between files
- When an edit changes a public signature, flag dependent files for re-check
- Integrates with compilation_gate to block dependent edits until parent compiles
- Estimated effort: 2 sessions

### Phase 3: Wire End-to-End Flow

**Sub-issue 3.1:** Integrate offset_index (and optionally memmap_index) into line_range_lock
- line_range_lock currently works on line numbers; connect it to the index layer
- Estimated effort: 1 session

**Sub-issue 3.2:** Wire parallel_edit -> line_range_lock -> edit_transaction -> compilation_gate -> agent_broadcast
- Ensure the full pipeline: acquire lock, apply edit, shift lines, check compilation, broadcast result
- Add `mod` declarations in main.rs for new modules
- Register any new tool arms in tool_registry.rs
- Estimated effort: 2 sessions

**Sub-issue 3.3:** Integrate ast_context into edit_transaction
- Before applying an edit, validate it doesn''t cross AST boundaries unexpectedly
- Optional: provide AST context to agents for smarter edits
- Estimated effort: 1 session

**Sub-issue 3.4:** Integrate dependency_graph into compilation_gate
- After a successful compilation gate, propagate re-check signals to dependent files
- Estimated effort: 1 session

### Phase 4: Concurrent Multi-Agent Fixtures

**Sub-issue 4.1:** Create test fixtures for concurrent editing
- 2+ agents editing the same file in non-overlapping ranges (should succeed)
- 2+ agents editing overlapping ranges (should serialize or conflict)
- Agent A edits, agent B''s lock shifts correctly
- Estimated effort: 2 sessions

**Sub-issue 4.2:** End-to-end integration test
- Spawn multiple tokio tasks simulating agents
- Each acquires locks, applies edits, runs through compilation gate, receives broadcasts
- Assert final file state is consistent
- Estimated effort: 2 sessions

---

## Decision Gates

1. **memmap_index**: De-scope if target files are always < 10 MB. Use simple `Vec<u64>` offset table instead.
2. **ast_context**: Choose between tree-sitter (accurate, heavy dep) vs brace-matching heuristic (lightweight, less accurate). Recommend brace-matching for v1.
3. **dependency_graph**: For v1, limit to same-crate `mod`/`use` tracking. Cross-crate deps can be deferred.

## Estimated Total Effort

- Phase 1: 3 sessions
- Phase 2: 4-7 sessions (depending on de-scoping decisions)
- Phase 3: 5 sessions
- Phase 4: 4 sessions
- **Total: 16-19 sessions**

## Recommended Execution Order

1.1 -> 1.2 -> 2.1 -> 2.2 (decision gate) -> 3.1 -> 2.3 -> 2.4 -> 3.2 -> 3.3 -> 3.4 -> 4.1 -> 4.2','docs/issues/1131-plan.md','cbb0aad534445ba90ac0096de932f0da15319c6e5fbee09307f9cf5a163348bb','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1132-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1132-plan.md','doc: Plan: #1132 — Precisao Fabricada 21 Itens','# Plan: #1132 — Precisao Fabricada 21 Itens

Epic decomposition for removing stubs, placeholders, and fake implementations across 6+ areas of the codebase.

---

## Area 1: chat_completion_helpers.rs (15 stubs)

**File:** `src/chat_completion_helpers.rs` (1014 lines)

### Sub-task 1.1: Remove PARTIAL_STREAM_STUB_ID sentinel
- Replace `PARTIAL_STREAM_STUB_ID` with real partial-stream handling.
- Requires reqwest + tokio streaming integration.

### Sub-task 1.2: Implement robust URL host extraction (line ~354, ~361)
- Replace TODO stubs with `url` crate-based host extraction.
- Add tests for edge cases (IPv6, ports, paths).

### Sub-task 1.3: Implement UTF-8 surrogate handling (line ~377)
- Current stub is a no-op. Implement proper sanitization for non-UTF-8 inputs from external sources.

### Sub-task 1.4: Implement regex-based redaction patterns (line ~395)
- Port redaction logic from Python module.
- Add positive/negative tests for PII patterns.

### Sub-task 1.5: Remaining stubs (touch_activity, buffer_status, etc.)
- Audit lines 12-22 docblock for full list of stubbed functions.
- Implement each with real logic; add behavioral tests.

---

## Area 2: hybrid_state.rs (4 stubs/placeholders)

**File:** `src/hybrid_state.rs` (472 lines)

### Sub-task 2.1: Remove placeholder state persistence
- Line 6: ensure state persistence is never a placeholder.
- Line 374: remove fake .gz extension workaround; use real compressed format or honest naming.

### Sub-task 2.2: Fix eviction to persist real state
- Line 388: test `eviction_persists_real_state_not_placeholder` exists but verify the implementation backing it is complete.
- Add negative tests (eviction with corrupt state, empty state).

---

## Area 3: prompt_caching.rs + prompt_caching_parity.rs (eviction logic)

**Files:** `src/prompt_caching.rs` (158 lines), `src/prompt_caching_parity.rs` (350 lines)

### Sub-task 3.1: Fix eviction algorithm
- Audit current eviction policy for correctness (LRU vs FIFO vs priority).
- Ensure cache invalidation is real, not simulated.

### Sub-task 3.2: Parity with reference implementation
- Compare parity file against prompt_caching.rs; identify divergences.
- Add behavioral tests: cache hit, cache miss, eviction under pressure, TTL expiry.

---

## Area 4: anthropic_adapter_parity.rs (stubs)

**File:** `src/anthropic_adapter_parity.rs` (2509 lines)

### Sub-task 4.1: Complete nullable-union stripping (line ~396-399)
- Current `_normalize_tool_input_schema` is a stub covering only Anthropic-required cases.
- Implement full nullable-union stripping logic.

### Sub-task 4.2: Image placeholder replacement (line ~1324)
- Verify base64 image replacement with text placeholder is correct behavior vs. a stub.
- Add tests for multi-image conversations, mixed content blocks.

---

## Area 5: schema_registry.rs

**File:** `src/schema_registry.rs` (752 lines)

### Sub-task 5.1: Audit for fabricated schema entries
- Search for hardcoded/fake schema definitions.
- Replace with dynamically loaded or properly validated schemas.

---

## Area 6: context_compression.rs, transport_types.rs, lazy_agent.rs

### Sub-task 6.1: context_compression.rs (359 lines)
- Verify `extract_message_summary` handles all content types (errors, decisions, TODOs) genuinely.

### Sub-task 6.2: transport_types.rs (1779 lines)
- Audit for lossy chat_schema serialization.
- Ensure round-trip fidelity in JSON serialization/deserialization.

### Sub-task 6.3: lazy_agent.rs (343 lines)
- Check for lazy-init patterns that silently return defaults instead of real state.

---

## Area 7: REPL Trajectory (cross-cutting)

### Sub-task 7.1: Fix always-green trajectory reporting
- Identify where REPL trajectory status is determined.
- Ensure failures propagate correctly instead of being masked.

### Sub-task 7.2: Evidence fixtures
- Remove any test fixtures that fabricate passing evidence.
- Replace with real behavioral assertions.

---

## Execution Order (recommended)

1. **Phase 1 (high impact):** Areas 1, 2, 3 — these are the most stub-heavy and affect core runtime behavior.
2. **Phase 2 (correctness):** Areas 4, 5 — adapter and schema correctness.
3. **Phase 3 (observability):** Areas 6, 7 — compression fidelity, trajectory honesty.

## Acceptance Criteria

- Zero `todo!()`, `unimplemented!()`, `stub`, `fake`, or `placeholder` markers remain in target files (except legitimate placeholder text for image replacement in adapter).
- Each sub-task has at least one positive and one negative behavioral test.
- `cargo check` and `cargo test` pass.
- No `.unwrap()` in production paths.','docs/issues/1132-plan.md','249ddf0bfe04a4e9974afb264c821be8210aeb657b9de9db7f1bb0dac554b26b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1133-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1133-plan.md','doc: Issue #1133 — Decomposition Plan: web_search backends fabricados','# Issue #1133 — Decomposition Plan: web_search backends fabricados

## Overview

Epic covering multiple unfinished subsystems in simplicio-runtime. This plan decomposes the work into concrete, independently deliverable tasks.

---

## Task 1: Wire Firecrawl web_search backend

**Files:** `src/plugins/web/firecrawl.rs`, `src/web_search_provider.rs`  
**Status:** Returns honest `Err("not wired")`. Real HTTP call never made.  
**Work:**
- Implement `search()` method using Firecrawl Search API (`POST /v1/search`)
- Parse JSON response into `WebSearchResult` structs
- Register provider in `web_search_provider.rs` registry
- Add `FIRECRAWL_API_KEY` env var handling with proper error on missing key

**Acceptance:** `cargo test` passes; manual test with valid API key returns real results.

---

## Task 2: Wire SearXNG web_search backend

**Files:** `src/plugins/web/searxng.rs`, `src/web_search_provider.rs`  
**Status:** Returns honest `Err("not wired")`.  
**Work:**
- Implement `search()` using SearXNG JSON API (`GET /search?format=json&q=...`)
- SearXNG is self-hosted, so use `SEARXNG_BASE_URL` env var
- Parse response into `WebSearchResult`
- Register in provider registry

**Acceptance:** `cargo test` passes; works against a local SearXNG instance.

---

## Task 3: Wire image_generate HTTP backends (Fal, OpenAI, xAI)

**Files:** `src/tools_image_generate.rs`, `src/htool_image_generation_tool.rs`  
**Status:** All 3 providers return honest "not implemented" errors. No HTTP calls wired.  
**Work:**
- **Fal:** POST to `https://fal.run/{model_id}` with bearer token, poll for result
- **OpenAI:** POST to `https://api.openai.com/v1/images/generations` (DALL-E 3)
- **xAI:** POST to xAI image generation endpoint (Grok Vision)
- Each needs: API key env var, request building, response parsing, error handling (no `.unwrap()`)
- Return image URL or base64 in tool result

**Acceptance:** `cargo check` passes; each provider tested with valid API key.

---

## Task 4: Integrate web_search_provider registry with tool dispatch

**Files:** `src/main.rs`, `src/tool_registry.rs`, `src/web_search_provider.rs`  
**Work:**
- Ensure `web_search` tool dispatch in `main.rs`/`tool_registry.rs` routes to the provider registry
- Provider selection via `SIMPLICIO_SEARCH_PROVIDER` env var or config
- Fallback chain: try preferred provider, fall back to next available

**Acceptance:** Changing env var switches search provider at runtime.

---

## Task 5: Audit and remediate stub modules

**Modules to investigate:**
- `lsp` — Language Server Protocol integration
- `mcp` — Model Context Protocol
- `curator` — content curation
- `social_ops` — social operations
- `hermes_compat` — Hermes compatibility layer
- `pairing` — agent pairing
- `error_recovery` — error recovery strategies
- `levi` — unknown purpose

**Work per module:**
1. Classify: stub (returns fake data), skeleton (compiles but no-ops), or partial (some real logic)
2. For stubs returning fake data: convert to honest `Err("not implemented")`
3. For skeletons: document intended behavior, leave as-is or remove if dead code
4. For partial: document what works and what doesn''t

**Acceptance:** No module silently returns fabricated data.

---

## Task 6: End-to-end behavioral tests

**Work:**
- Add integration tests for each web_search provider (mock HTTP or use recorded responses)
- Add integration tests for image_generate providers
- Add smoke tests for stub modules (verify they return proper errors, not fake data)
- Use `#[cfg(test)]` modules with mock HTTP clients

**Acceptance:** `cargo test` covers all provider paths; CI passes.

---

## Suggested execution order

1. Task 5 (audit stubs) — low risk, high info gain
2. Task 1 + Task 2 (Firecrawl + SearXNG) — independent, can parallelize
3. Task 4 (registry integration) — depends on 1+2
4. Task 3 (image_generate) — independent of search work
5. Task 6 (tests) — after all implementations land

## Estimated effort

- Tasks 1, 2: ~2h each
- Task 3: ~4h (3 providers)
- Task 4: ~1h
- Task 5: ~3h (8 modules to audit)
- Task 6: ~4h
- **Total: ~16h**','docs/issues/1133-plan.md','2acfc773529659029695bdb0398404c738af405bd6aa6427855df43ce4b5f765','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1134-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1134-plan.md','doc: Epic #1134 — Suites Verticais arg-echo','# Epic #1134 — Suites Verticais arg-echo

## Overview

Epic covering ~30 issues (#692-#721) across multiple independent domains. Current state: commands are dispatched in `main.rs` (lines ~2819-2841) and implementations (lines ~75100-75860) already return honest `Err` for unimplemented paths. This plan decomposes the epic into per-module sub-issues.

---

## Sub-issues

### 1. LanceDB Memory Backend
- **Scope**: Replace in-memory stub with real LanceDB-backed vector store for conversation memory.
- **Files**: `src/main.rs` (memory dispatch), new `src/htool_lancedb_memory.rs`
- **Acceptance**: Insert/query/delete operations work; negative test for missing collection.

### 2. Conversation Loop Driver
- **Scope**: Implement real conversation loop with turn management, context window, and tool-call orchestration.
- **Files**: `src/conversation_loop_driver.rs`, `src/conversation.rs`
- **Acceptance**: Multi-turn conversation completes; test that stale context is pruned.

### 3. Social Actions Module
- **Scope**: Implement social platform integrations (post, reply, react) with proper error handling.
- **Files**: `src/main.rs` (social_actions dispatch), new `src/htool_social_actions.rs`
- **Acceptance**: API call stubs with configurable backends; negative test for auth failure.

### 4. Coding Agent Module
- **Scope**: Implement code generation/review/refactor agent with sandboxed execution.
- **Files**: new `src/htool_coding_agent.rs`
- **Acceptance**: Generate, review, and refactor commands return structured output; test for invalid language.

### 5. Car Assistant (Vertical)
- **Scope**: Android Auto integration, vehicle diagnostics, navigation commands.
- **Files**: new `src/vertical_car_assistant.rs`
- **Acceptance**: Command dispatch works; negative test for unsupported vehicle protocol.

### 6. Mae Mode (Vertical)
- **Scope**: Persona engine for maternal/caring interaction style.
- **Files**: new `src/vertical_mae_mode.rs`
- **Acceptance**: Persona context is injected into conversation; test for persona reset.

### 7. Vestibular (Vertical)
- **Scope**: Quiz engine for Brazilian college entrance exam preparation.
- **Files**: new `src/vertical_vestibular.rs`
- **Acceptance**: Question bank CRUD, quiz session with scoring; negative test for empty bank.

### 8. Messaging Bot (Vertical)
- **Scope**: Multi-platform messaging bot (WhatsApp, Telegram) with webhook handling.
- **Files**: new `src/vertical_messaging_bot.rs`
- **Acceptance**: Message receive/send pipeline; negative test for invalid webhook signature.

### 9. Vet Module (Vertical)
- **Scope**: Veterinary consultation assistant with species-specific knowledge base.
- **Files**: new `src/vertical_vet_module.rs`
- **Acceptance**: Symptom lookup, breed-specific advice; negative test for unknown species.

### 10. Dental Module (Vertical)
- **Scope**: Dental clinic assistant with procedure tracking and patient history.
- **Files**: new `src/vertical_dental_module.rs`
- **Acceptance**: Procedure CRUD, appointment suggestions; negative test for invalid procedure code.

---

## Cross-cutting Requirements

- **No `.unwrap()` in production code** — all errors must be handled via `Result`.
- **Dependencies**: `std` + `serde` + `serde_json` only (no additional crates without approval).
- **Each sub-issue must include**:
  - Behavioral tests proving old stubs fail (before implementation).
  - Negative tests for error paths.
  - `cargo check` + `cargo test` passing.

## Suggested Order

1. Conversation Loop Driver (#2) — foundation for all verticals
2. LanceDB Memory Backend (#1) — needed by conversation loop
3. Coding Agent (#4) and Social Actions (#3) — independent, can parallelize
4. Verticals (#5-#10) — independent, can parallelize after #1 and #2','docs/issues/1134-plan.md','7953af875907508c94e17f5ff62342174ba40cb16e2da9b49eb87d077ac77b30','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1136-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1136-plan.md','doc: Epic #1136 — fake O: static-status families','# Epic #1136 — fake O: static-status families

Decomposition plan for converting ~615 fake findings across ~25 families from
PRINTS_BUT_NO_ACTION / HARDCODED_DATA / STUB_NO_LOGIC to honest `Err` returns
or real implementations, plus behavioral tests.

## Sub-tasks

### 1. Fake Observability (obs_status / logs / metrics / dashboard)
- **Files**: `main.rs` (lines ~1735-93795, obs-related sections), `audit_command.rs` (1075 lines, 62 fake markers)
- **Scope**: ~98 critical fakes in main.rs for status/health/metrics endpoints that return hardcoded "ok" or print success without doing anything.
- **Action**: Replace static status returns with real checks or honest `Err("not implemented")`. Extract obs logic from main.rs into dedicated `htool_obs_status.rs`.

### 2. Fake Messaging — Email
- **Files**: `email_platform.rs` (531 lines)
- **Scope**: Send/receive email functions that print success but never connect to SMTP/IMAP.
- **Action**: Return `Err` with clear message or implement via `lettre` crate if real sending is desired.

### 3. Fake Messaging — Teams
- **Files**: `teams_platform.rs` (328 lines)
- **Scope**: Teams webhook/API calls that return hardcoded success.
- **Action**: Convert to honest `Err` or implement real webhook POST via `ureq`/`reqwest`.

### 4. Fake Messaging — Google Chat / IRC / Mattermost / WhatsApp / Webhook
- **Files**: `platform_google_chat.rs` (188 lines), `platform_irc.rs` (612 lines), `platform_mattermost.rs` (372 lines), `webhook_command.rs` (451 lines)
- **Scope**: All messaging platform stubs that simulate sending/receiving.
- **Action**: Return `Err("platform not configured")` for unconfigured platforms. For webhook_command, implement real HTTP POST if URL is provided.

### 5. Fake Browser Automation
- **Files**: `tools_browser.rs` (803 lines)
- **Scope**: 3 independent browser automation surfaces (screenshot, navigate, interact) returning fake data.
- **Action**: Return honest errors. Real browser automation requires headless Chrome integration (out of scope for initial fix; mark as `Err("requires headless browser runtime")`).

### 6. Fake Provider Integrations
- **Files**: `integration_openrouter.rs` (283 lines), `integration_anthropic.rs` (249 lines), `integration_deepseek.rs` (179 lines), `integration_gemini.rs` (180 lines)
- **Scope**: LLM provider calls that return hardcoded completions or fake token counts.
- **Action**: Implement real HTTP calls to each provider API using API keys from env vars, or return `Err("API key not configured")`.

### 7. Fake Deploy Backends
- **Files**: `daytona_deploy.rs` (166 lines), `singularity_backend.rs` (215 lines)
- **Scope**: Deploy/container functions that print "deployed successfully" without doing anything.
- **Action**: Return `Err("deploy backend not available")` or implement real API calls.

### 8. Fake Persistence (memory / checkpoint / sealed_receipt)
- **Files**: `memory_command.rs` (172 lines), `sealed_receipt.rs` (407 lines)
- **Scope**: Memory save/load and receipt sealing that uses hardcoded data or no-ops.
- **Action**: Implement real file-based persistence for memory. For sealed_receipt, implement real HMAC signing or return `Err`.

### 9. Fake Security Controls
- **Scope**: Scattered across main.rs — auth checks, permission gates, encryption stubs that always return "authorized" or "encrypted".
- **Action**: Extract into `htool_security.rs`. Return `Err("security module not configured")` for unconfigured controls.

### 10. Fake Benchmarks
- **Scope**: Benchmark functions in main.rs that return hardcoded performance numbers.
- **Action**: Either run real micro-benchmarks or return `Err("benchmarks disabled")`.

## Priority Order

1. Sub-task 6 (Provider Integrations) — highest user impact
2. Sub-task 1 (Observability) — largest volume of fakes
3. Sub-task 8 (Persistence) — data integrity risk
4. Sub-task 9 (Security Controls) — safety critical
5. Sub-task 2-4 (Messaging) — moderate impact
6. Sub-task 5 (Browser) — lower priority, complex deps
7. Sub-task 7 (Deploy) — environment-specific
8. Sub-task 10 (Benchmarks) — lowest priority

## Constraints

- Only `std` + `serde` + `serde_json` unless new deps are approved per sub-task.
- No `.unwrap()` in production code.
- Each sub-task must include behavioral tests proving the fake is gone.
- Each sub-task gets its own PR for reviewability.','docs/issues/1136-plan.md','b02aa25c7b146f98b7fa51280b1216c466bac76021504072b7fadf57888d01e3','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1138-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1138-plan.md','doc: Issue #1138 — Dead Code: Parity Blocks Orfaos','# Issue #1138 — Dead Code: Parity Blocks Orfaos

## Summary

The simplicio-runtime codebase has 11 orphan parity modules (9,761 lines / 425 KB total) that are never declared as `mod` in `main.rs` and therefore are completely dead code. Additionally, 550+ `#[allow(dead_code)]` annotations exist across the `src/` directory, many of which mask genuinely unused items in wired modules.

## Orphan Parity Modules (not declared in main.rs)

| Module | Lines | Bytes |
|--------|------:|------:|
| curator_parity | 1,860 | 77,235 |
| display_parity | 1,368 | 57,745 |
| hermes_parity_planner_loop | 657 | 23,549 |
| memory_manager_parity | 1,148 | 48,784 |
| memory_provider_parity | 576 | 24,233 |
| prompt_caching_parity | 309 | 13,209 |
| tool_executor_parity | 1,906 | 84,684 |
| trajectory_parity | 206 | 8,970 |
| turn_context_parity | 865 | 42,462 |
| turn_finalizer_parity | 710 | 35,392 |
| turn_retry_state_parity | 156 | 8,867 |

**Total: 9,761 lines across 11 files**

## Wired Parity Modules (declared in main.rs)

These 18 modules ARE declared and at least partially used:
- hermes_parity_bare_task, hermes_parity_canonical_loop, hermes_parity_ipc, hermes_parity_narrative
- hermes_parity_run_loop, hermes_parity_policy, hermes_parity_adapters
- hermes_parity_agent_runner, hermes_parity_benchmark_agents, hermes_parity_capabilities_ext
- hermes_parity_context, hermes_parity_learn_ext, hermes_parity_provider_ux, hermes_parity_readiness
- anthropic_adapter_parity, error_classifier_parity, i18n_parity, prompt_builder_parity

## Decomposition into Sub-Tasks

### Sub-task 1: Triage Orphan Modules (decide: wire or delete)

For each of the 11 orphan modules, determine:
- Does the module contain functionality that overlaps with a wired module? (likely duplicate)
- Does it implement a feature not yet surfaced? (candidate for wiring)
- Is it purely scaffolding/prototype code? (candidate for deletion)

**Deliverable:** A decision table (wire / delete / merge) for each orphan.

### Sub-task 2: Delete Confirmed Dead Orphan Files

Remove orphan files confirmed as dead in sub-task 1. This alone eliminates ~9,700 lines.

**Validation:** `cargo build` must pass. No new warnings introduced.

### Sub-task 3: Wire Salvageable Orphan Modules

For orphan modules worth keeping:
1. Add `mod <name>;` in `main.rs`
2. Add `use` imports for public API
3. Wire into CLI match arms or tool_registry as appropriate
4. Remove `#[allow(dead_code)]` from items that are now reachable

**Validation:** `cargo build` + `cargo test` pass.

### Sub-task 4: Audit `#[allow(dead_code)]` in Wired Modules

Across the 18 wired parity modules and rest of codebase (550+ annotations):
1. Remove `#[allow(dead_code)]` annotations one module at a time
2. For each compiler warning produced, decide: expose publicly, add test, or delete
3. Prioritize by module size (largest modules = most hidden dead code)

**Validation:** `cargo build` with no new `dead_code` warnings.

### Sub-task 5: Add Behavioral Tests

For each module that survives (wired or newly wired):
1. Add positive test: call the public API with valid input, assert success
2. Add negative test: call with invalid input, assert proper error (no panics)
3. Ensure no `.unwrap()` in production paths

**Validation:** `cargo test` passes, coverage for parity modules > 0%.

### Sub-task 6: Final Validation

- `cargo build --release` passes
- `cargo test` passes
- `cargo clippy` has no new warnings
- No remaining `#[allow(dead_code)]` without justification comment

## Suggested Execution Order

1. Sub-task 1 (triage) — blocks all others
2. Sub-task 2 (delete) — quick win, reduces noise
3. Sub-task 3 (wire) — depends on triage decisions
4. Sub-task 4 (audit allow(dead_code)) — can run in parallel with 3
5. Sub-task 5 (tests) — after 3 and 4 stabilize
6. Sub-task 6 (final validation)

## Risk Notes

- Some orphan modules may have cross-dependencies with wired modules via `use crate::` imports inside the orphan files. These won''t cause build errors (orphans are never compiled) but may indicate shared design intent.
- The `hermes_parity_planner_loop` module (657 lines) was referenced in a comment at line 190 of main.rs but never actually declared as `mod` — likely an incomplete integration.','docs/issues/1138-plan.md','ac84f285faf28248c485db2a92cf43eadd435a019f566f25f6ba62a5ad66f2cc','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1139-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1139-plan.md','doc: Plan: #1139 - Substituir 232+ testes is_ok()-only por assercoes comportamentais','# Plan: #1139 - Substituir 232+ testes is_ok()-only por assercoes comportamentais

## Problema

Centenas de testes no simplicio-runtime usam apenas `assert!(result.is_ok())` sem verificar o comportamento real (conteudo do retorno, efeitos colaterais, estado mutado). Esses testes passam mesmo com stubs vazios, nao detectam regressoes.

## Scan atual

- **~844 ocorrencias** de `assert.*is_ok()` em **60+ arquivos** sob `src/`
- Concentracao massiva em `main.rs` (235 ocorrencias) e `main.rs.bak*`
- Arquivos `.bak` devem ser ignorados (nao sao codigo ativo)

## Decomposicao em sub-issues

### Sub-issue 1: Agents core (estimativa: 35-40 testes)
**Arquivos:** `agent_chat.rs`, `agent_bootstrap.rs`, `agent_runtime_helpers.rs`, `agent_broadcast.rs`, `agent_store.rs`, `agent_rooms.rs`, `agent_collaboration.rs`
**Acao:** Verificar conteudo de mensagens, estado do agente apos operacao, campos esperados no retorno.

### Sub-issue 2: Action/Gate layer (estimativa: 15-20 testes)
**Arquivos:** `action_bridge.rs`, `action_gate.rs`, `auto_fix.rs`
**Acao:** Validar que bridge roteia corretamente, gate bloqueia/permite conforme regras, auto_fix aplica correcao esperada.

### Sub-issue 3: Batch runner (estimativa: 10-15 testes)
**Arquivos:** `batch_runner/mod.rs`, `batch_runner/trajectory.rs`, `batch_runner/gc_envelope.rs`
**Acao:** Verificar trajetoria gerada, envelope GC contem campos corretos, batch produz resultados esperados.

### Sub-issue 4: Benchmark/Audit (estimativa: 10-15 testes)
**Arquivos:** `benchmark_harness.rs`, `benchmark_suite.rs`, `audit_command.rs`
**Acao:** Validar metricas retornadas, formato de relatorio de audit.

### Sub-issue 5: Adapters/Providers (estimativa: 10-15 testes)
**Arquivos:** `anthropic_adapter_parity.rs`, `bedrock_adapter.rs`, `azure_identity.rs`, `capability_broker.rs`
**Acao:** Verificar paridade de formatos, tokens parseados, capabilities mapeadas corretamente.

### Sub-issue 6: Plugins - Google Meet (estimativa: 15-20 testes)
**Arquivos:** `plugins/google_meet/audio.rs`, `plugins/google_meet/bot.rs`, `plugins/google_meet/mod.rs`, `plugins/google_meet/realtime.rs`
**Acao:** Validar audio buffers, estado do bot, mensagens realtime parseadas.

### Sub-issue 7: Plugins - Web/Search (estimativa: 10-12 testes)
**Arquivos:** `plugins/web/xai.rs`, `plugins/web/tavily.rs`, `plugins/web/searxng.rs`, `plugins/web/parallel.rs`, `plugins/web/firecrawl.rs`
**Acao:** Verificar resultados de busca parseados, parallel merge correto.

### Sub-issue 8: HTools (estimativa: 25-30 testes)
**Arquivos:** `htool_browser_supervisor.rs`, `htool_debug_helpers.rs`, `htool_file_state.rs`, `htool_file_tools.rs`, `htool_neutts_synth.rs`, `htool_path_security.rs`, `htool_skills_ast_audit.rs`, `htool_skills_hub.rs`, `htool_skills_sync.rs`, `htool_transcription_tools.rs`, `htool_website_policy.rs`, `htool_web_tools.rs`, `htool_x_search_tool.rs`
**Acao:** Validar JSON retornado, paths sanitizados, resultados de ferramentas com campos esperados.

### Sub-issue 9: Hermes parity (estimativa: 12-15 testes)
**Arquivos:** `hermes_parity_canonical_loop.rs`, `hermes_parity_capabilities_ext.rs`, `hermes_parity_ipc.rs`, `hermes_parity_learn_ext.rs`
**Acao:** Verificar compatibilidade de mensagens IPC, capabilities corretas.

### Sub-issue 10: Infra/Misc (estimativa: 20-25 testes)
**Arquivos:** `background_review.rs`, `apple_notes.rs`, `apple_reminders.rs`, `autonomia_engine.rs`, `backup_command.rs`, `license.rs`, `final_modules.rs`, `conversation_compression.rs`, `conversation_loop_driver.rs`, `distributed_lock.rs`, `inbox_agent.rs`, `novelty_gate.rs`, `process_bootstrap.rs`, `sealed_receipt.rs`, `growth_stripe.rs`
**Acao:** Validar estados, compressao real, locks adquiridos/liberados, receipts com assinatura.

### Sub-issue 11: main.rs mega-cleanup (estimativa: ~235 testes)
**Arquivos:** `main.rs`
**Acao:** Maior concentracao. Separar por funcao testada, extrair para modulos de teste dedicados. Verificar retornos de cada handler.

### Sub-issue 12: Integration tests (estimativa: 5-10 testes)
**Arquivos:** `tests/hermes_core_integration.rs`, `tests/edit_lock_range_cli.rs`
**Acao:** Validar fluxos end-to-end, outputs CLI esperados.

### Sub-issue 13: Testes negativos transversais
**Acao:** Para cada sub-issue acima, adicionar pelo menos 1 teste negativo por modulo que verifica `is_err()` com mensagem de erro especifica quando config/dependencia ausente.

## Padrao de correcao

**Antes (fake):**
```rust
#[test]
fn test_agent_chat_send() {
    let result = send_message("hello");
    assert!(result.is_ok());
}
```

**Depois (comportamental):**
```rust
#[test]
fn test_agent_chat_send() {
    let result = send_message("hello").expect("send_message should succeed");
    assert_eq!(result.status, MessageStatus::Delivered);
    assert!(!result.id.is_empty(), "message id must be non-empty");
    assert!(result.timestamp > 0, "timestamp must be set");
}

#[test]
fn test_agent_chat_send_fails_without_config() {
    let result = send_message_no_config("hello");
    assert!(result.is_err());
    let err = result.unwrap_err().to_string();
    assert!(err.contains("config"), "error should mention missing config");
}
```

## Prioridade de execucao

1. **main.rs** (sub-issue 11) - maior impacto, 235 testes
2. **HTools** (sub-issue 8) - ferramentas user-facing
3. **Agents core** (sub-issue 1) - logica central
4. **Hermes parity** (sub-issue 9) - compatibilidade critica
5. Restante em qualquer ordem

## Estimativa total

- ~232-280 testes a corrigir (excluindo .bak files)
- ~13 sub-issues
- ~2-4h por sub-issue = 26-52h de trabalho','docs/issues/1139-plan.md','797b0634e61849526da797c2bd617d35b7a8f889621983defcbff9a20833f9ee','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1140-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1140-plan.md','doc: Epic #1140: Lifecycle Commands — Decomposition Plan','# Epic #1140: Lifecycle Commands — Decomposition Plan

## Overview

This epic covers 9+ lifecycle command families that exist as partial/stubbed implementations across the codebase. Each sub-task requires removing stubs, wiring to the public API surface, and adding tests.

## Sub-tasks

### 1. Skills Install/List/Run/Remove with Hub Discovery and Health Checks
**Files:** `skills_v2.rs`, `skill_commands.rs`, `skills_command.rs`, `htool_skills_tool.rs`, `htool_skills_hub.rs`, `htool_skill_manager_tool.rs`, `skill_health.rs`
- Wire `skills install <name>` to hub discovery (`htool_skills_hub.rs`)
- Implement `skills list` with health status from `skill_health.rs`
- Implement `skills run <name>` dispatching through `skills_v2.rs`
- Implement `skills remove <name>` with cleanup
- Add health check polling and status reporting
- Register all skill tools in `tool_registry.rs`
- Tests: install from hub, list installed, run a skill, remove, health check pass/fail

### 2. Setup Command Wiring
**Files:** `setup_command.rs`, `main.rs`, `tool_registry.rs`
- Wire `setup_command` to the CLI/runtime surface
- Replace any stubs with real initialization logic (config creation, directory scaffolding)
- Add match arm in `tool_registry.rs` or CLI dispatcher
- Tests: fresh setup, re-setup idempotency, setup with missing permissions

### 3. Dump Command Wiring
**Files:** `dump_command.rs`, `main.rs`, `tool_registry.rs`
- Wire `dump_command` to produce diagnostic output (config, state, versions)
- Format output as structured JSON via `serde_json`
- Register in tool registry
- Tests: dump with valid state, dump with partial state

### 4. Node TUI / Electron App Integration
**Files:** `node_tui.rs`, `electron_app.rs`
- Wire TUI launch command to spawn node process
- Wire Electron app launch with proper IPC channel setup
- Handle process lifecycle (start, health check, graceful shutdown)
- Tests: launch mock process, shutdown, handle spawn failure

### 5. Daemon Instance Management
**Files:** `main.rs`, `tool_registry.rs` (+ new `daemon_instances.rs` if needed)
- Implement daemon start/stop/status/list commands
- PID file management and stale process detection
- Graceful shutdown with timeout
- Tests: start daemon, query status, stop, detect stale PID

### 6. Conversation NLU Hookup
**Files:** `turn_lifecycle.rs`, `tool_registry.rs`
- Wire `turn_lifecycle.rs` to process conversation turns
- Connect NLU intent parsing to command dispatch
- Handle ambiguous intents with clarification flow
- Tests: recognized intent, unknown intent, multi-turn context

### 7. Video Legacy Pipeline
**Files:** `video_pipeline.rs`
- Wire video pipeline commands (transcode, thumbnail, metadata)
- Implement pipeline stage orchestration with error propagation
- Handle partial failures gracefully (no `.unwrap()`)
- Tests: full pipeline success, stage failure, invalid input

## Constraints
- **Dependencies:** `std`, `serde`, `serde_json` only
- **Error handling:** No `.unwrap()` in production code; use `Result` throughout
- **Registration:** Each command family must be registered in `tool_registry.rs` with a match arm
- **Module declaration:** New modules must be declared in `main.rs`

## Suggested Execution Order
1. Setup + Dump (foundational, low risk)
2. Skills lifecycle (core feature, highest value)
3. Daemon instances (infrastructure)
4. Node TUI / Electron (UI integration)
5. Conversation NLU (depends on turn_lifecycle)
6. Video pipeline (independent, can parallelize)','docs/issues/1140-plan.md','c4114667c59d7a1a15d6c88d3afa27372bbe3c47967b4ee7a95e450ecd5f499b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1141-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1141-plan.md','doc: Epic #1141 — fake K: schedulers/exec/voice','# Epic #1141 — fake K: schedulers/exec/voice

## Overview

This epic covers removing stubs/placeholders across 6+ subsystems, connecting
real backends (or returning honest errors with actionable guidance), and adding
behavioral tests. The codebase currently compiles but every voice/audio operation
returns `Err` with "not yet implemented" messages.

---

## Sub-issue 1: Voice TTS — real provider dispatch

**Files:** `src/htool_tts_tool.rs`, `src/htool_neutts_synth.rs`

**Current state:** `synthesize_speech()` has 10 provider arms (edge, elevenlabs,
openai, minimax, xai, mistral, gemini, neutts, kittentts, piper) — every one
returns `Err("... not yet implemented ...")`. Plugin dispatch exists but no
plugins are registered.

**Work required:**
1. Implement at least 2 providers end-to-end (edge-tts via subprocess,
   openai via HTTPS/curl) with proper env-var config (`OPENAI_API_KEY`, etc.).
2. Wire `htool_neutts_synth.rs` as a real NeuTTS backend instead of stub.
3. Add integration tests: successful synthesis (mocked HTTP), missing API key,
   unknown provider, empty text input.
4. Replace all `"not yet implemented"` strings with either real logic or
   `"provider not available — install/configure X"` with concrete steps.

**Acceptance criteria:**
- `cargo test` passes with at least 4 new tests (2 positive, 2 negative).
- At least one provider produces a real audio file when configured.

---

## Sub-issue 2: Voice STT — recording and transcription

**Files:** `src/htool_voice_mode.rs`, `src/htool_transcription_tools.rs`,
`src/transcription_provider.rs`, `src/skill_whisper.rs`

**Current state:**
- `start_recording()` and `stop_recording()` are stubs returning `Err` with
  "native audio capture not implemented in Rust" (lines 576-604).
- `transcribe()` works via curl→Whisper/Groq/OpenAI when env vars are set,
  but has no fallback or error recovery.
- `transcription_provider.rs` has a registry but no backends connected.
- `htool_transcription_tools.rs` has all cloud providers returning `Err`.

**Work required:**
1. Implement recording via subprocess (`arecord`/`sox`/`ffmpeg`) with
   platform detection (Linux/macOS/Windows).
2. Connect at least 1 real transcription backend in the provider registry
   (Whisper API via curl, already partially implemented in voice_mode).
3. Remove duplicate transcription logic between `htool_voice_mode.rs` and
   `htool_transcription_tools.rs` — consolidate into `transcription_provider.rs`.
4. Add tests: transcription with mock server, missing WAV file, empty audio,
   unsupported format, provider fallback chain.

**Acceptance criteria:**
- `cargo test` passes with at least 5 new tests.
- `transcription_provider.rs` registry has at least 1 functional backend.
- Recording returns actionable error with install commands per platform.

---

## Sub-issue 3: Cron scheduler integration validation

**Files:** `src/cron_scheduler.rs`

**Current state:** CLI commands are wired, cron parsing works, but real
spawn/exit-code handling needs validation. 622 lines of code, unclear if
`spawn` properly handles edge cases (zombie processes, signal forwarding,
non-zero exit codes).

**Work required:**
1. Add integration tests that spawn real subprocesses and verify exit codes.
2. Validate cron expression edge cases (leap seconds, DST transitions,
   `@reboot` special syntax).
3. Add proper signal forwarding (SIGTERM/SIGINT) to spawned children.
4. Add test for overlapping schedule execution (prevent double-spawn).
5. Verify cleanup on scheduler shutdown (no orphan processes).

**Acceptance criteria:**
- `cargo test` passes with at least 4 new tests covering spawn lifecycle.
- No `.unwrap()` in production code paths.

---

## Sub-issue 4: Structured concurrency + hybrid state integration

**Files:** `src/structured_concurrency.rs`, `src/hybrid_state.rs`

**Current state:** Both modules are declared and compile, but integration is
"not proven" — no tests verify they work together or with the rest of the
runtime.

**Work required:**
1. Add unit tests for `structured_concurrency.rs`: task spawning, cancellation
   propagation, parent-child lifecycle, panic handling.
2. Add unit tests for `hybrid_state.rs`: state transitions, concurrent access,
   serialization round-trip.
3. Add integration test proving structured concurrency + hybrid state work
   together (e.g., concurrent tasks sharing hybrid state with proper isolation).
4. Wire into `main.rs` if not already connected.

**Acceptance criteria:**
- `cargo test` passes with at least 6 new tests (3 per module).
- Integration test demonstrates cross-module correctness.

---

## Priority order

1. **Sub-issue 3** (cron scheduler) — smallest scope, highest confidence.
2. **Sub-issue 4** (structured concurrency + hybrid state) — no external deps.
3. **Sub-issue 1** (TTS) — needs HTTP client strategy decision.
4. **Sub-issue 2** (STT) — largest scope, depends on TTS patterns.

## Cross-cutting concerns

- **No `.unwrap()` in production** — enforce via clippy lint or grep in CI.
- **std + serde + serde_json only** — no new crate dependencies.
- **All stubs must either become real or return honest structured errors** with
  fields: `error`, `provider`, `action_required`, `install_hint`.','docs/issues/1141-plan.md','f33ec9b6d78c091e81f7cfe7206cb29242699b748635656f973498acc013a989','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1142-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1142-plan.md','doc: Plan: #1142 — fake J: quality theater','# Plan: #1142 — fake J: quality theater

## Current State

Hardcoded quality scores were removed and replaced with honest `Err("not implemented")` messages. The "fake" quality theater is partially remediated. However, the three core subsystems have no real implementations:

- `quality_dimensions()` returns empty
- `refine_run` / `optimize_run` return not-implemented errors
- `auto_learn` and `hermes_parity_update` have file-based implementations (more substantial)

## Decomposition

### Sub-issue #381: Quality Gates (real measurement pipeline)

**Goal:** Replace empty `quality_dimensions()` with actual quality measurement.

**Tasks:**
1. Integrate `cargo test` execution and parse results (pass/fail counts, test names)
2. Integrate `cargo clippy` execution and parse warnings/errors
3. Add benchmark integration via `cargo bench` (optional, gated)
4. Define a `QualityReport` struct with dimensions: correctness (tests), lint (clippy), performance (bench)
5. Implement scoring logic: each dimension produces a 0.0-1.0 score with justification
6. Wire `quality_dimensions()` to return real `QualityReport`
7. Add tests for the quality measurement pipeline

**Estimated effort:** Medium (2-3 focused sessions)

### Sub-issue #382: Iterative Refinement Engine

**Goal:** Implement `refine_run` with a real iterative improvement loop.

**Tasks:**
1. Define `RefinementConfig` (max iterations, convergence threshold, target dimensions)
2. Implement single-step refinement: measure quality, identify worst dimension, suggest fix
3. Implement loop controller: run steps until convergence or max iterations
4. Add diff-based change tracking between iterations
5. Persist refinement history to disk (JSON log)
6. Wire `refine_run` tool to use the engine
7. Add tests with mock quality measurements

**Estimated effort:** Medium-High (3-4 focused sessions)

### Sub-issue #383: Multi-Objective Optimization

**Goal:** Implement `optimize_run` with real multi-objective optimization.

**Tasks:**
1. Define objective functions (correctness, lint cleanliness, performance, code size)
2. Implement Pareto frontier tracking for multiple objectives
3. Implement a simple weighted-sum or epsilon-constraint solver
4. Add constraint support (e.g., "tests must pass" as hard constraint)
5. Produce optimization report with trade-off analysis
6. Wire `optimize_run` tool to use the solver
7. Add tests with synthetic objective functions

**Estimated effort:** High (4-5 focused sessions)

### Existing implementations (lower priority)

- **auto_learn**: Already has file-based implementation. May need quality gate integration to validate learned patterns.
- **hermes_parity_update**: Already has file-based implementation. May need refinement engine integration for iterative parity improvements.

## Dependency Order

```
#381 Quality Gates
  |
  +---> #382 Iterative Refinement (depends on quality measurement)
  |         |
  +---> #383 Multi-Objective Optimization (depends on quality measurement)
              |
              v
         auto_learn + hermes_parity integration (depends on all three)
```

## Constraints

- **std + serde + serde_json only** — no additional crate dependencies for core logic
- **No `.unwrap()` in production** — all errors must be propagated
- **Subprocess execution** — quality measurement requires running cargo commands; use existing `shell_command_for_current_platform()` infrastructure','docs/issues/1142-plan.md','fec42ba4bd7f280d188069d25419ef999a5db353da0af8f19291c78a045731cc','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1143-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1143-evidence.md','doc: Issue #1143 — fake I: decisao financeira fabricada','# Issue #1143 — fake I: decisao financeira fabricada

## Status: Already Implemented

## Evidence

### 1. `risk_configure` persists limits (src/main.rs ~line 48361)
- Writes user-defined risk limits to `.simplicio-loop/risk-config.json`
- Validates input and returns error when no flags are provided

### 2. `risk_check` reads persisted config (src/main.rs ~line 48286)
- Reads from `.simplicio-loop/risk-config.json` instead of using hardcoded $50 value
- Ensures financial decisions use real, user-configured limits

### 3. `polymarket_bet` returns honest errors (src/main.rs ~line 48198)
- Returns `Err` instead of fabricating successful results
- No fake financial data is produced

### 4. Tests confirming correct behavior
- `risk_configure_persists_and_limits_reads_back` (src/main.rs ~line 90914)
- `risk_configure_no_flags_errs` (src/main.rs ~line 90956)
- `poly_agents_risk_honest_err` (src/main.rs ~line 91150)

### 5. Old behavior preserved in .bak files
- Backup files confirm the previous hardcoded behavior existed and was replaced','docs/issues/1143-evidence.md','0a970fee93a9940f7dff5664c1160a55789cb5138e476ecc65e240befadb0d7a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1145-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1145-plan.md','doc: Issue #1145 — fake G: persistencia mentirosa','# Issue #1145 — fake G: persistencia mentirosa

## Resumo

Epic cobrindo 7+ subsistemas de persistencia no simplicio-runtime que alegam persistir dados mas nao o fazem de verdade, ou persistem parcialmente sem testes que comprovem.

## Decomposicao em sub-issues

### Sub-issue 1: yool get/query — persistencia real de tuples
- **Arquivos**: `src/yool_integration.rs`
- **Problema**: `yool_tokio_persist` retorna `Err` honesto mas nao ha persistencia real de tuples.
- **Entrega**: Implementar persistencia JSONL para tuples do yool; testes positivo (persiste e recupera) e negativo (arquivo corrompido / ausente).

### Sub-issue 2: personal_memory — integracao end-to-end
- **Arquivos**: `src/plugins/memory/mod.rs`, `src/plugins/memory/mem0.rs`
- **Problema**: Ja tem persistencia JSONL real em `.simplicio-loop/personal-memory.json`, mas falta integracao end-to-end com runtime surface e testes comportamentais.
- **Entrega**: Conectar personal_memory ao tool_registry; testes que provem round-trip (write -> restart -> read).

### Sub-issue 3: deep_mem (#453) — init flow e testes sqlite
- **Arquivos**: `src/organism/human_memory.rs`
- **Problema**: Usa sqlite3 externo via shell, retorna `Err` honesto se DB nao existe. Falta init flow automatico e testes.
- **Entrega**: Criar DB automaticamente no primeiro uso; testes positivo (insert+query) e negativo (sqlite3 ausente no PATH).

### Sub-issue 4: exec_checkpoint — verificar persistencia real
- **Arquivos**: `src/organism/persistence.rs`
- **Problema**: Implementado com save/restore/list/status mas pode ser apenas in-memory.
- **Entrega**: Verificar e corrigir para persistencia em disco; testes que provem sobrevivencia a restart.

### Sub-issue 5: migrate_apply — fixture data e testes de rollback
- **Arquivos**: `src/mapper_memory.rs`
- **Problema**: Tem implementacao com ledger JSON mas falta fixture data e testes de rollback/idempotencia.
- **Entrega**: Criar fixtures; testes de apply, rollback e idempotencia.

### Sub-issue 6: yool_tokio (#441) — honestidade do persist sub-command
- **Arquivos**: `src/tools_memory_providers.rs`
- **Problema**: persist sub-command retorna `Err` explicito dizendo que usa JSONL flat e nao SQLite como alegado.
- **Entrega**: Ou implementar SQLite real ou atualizar documentacao/mensagens para refletir JSONL. Testes de persistencia real.

### Sub-issue 7: memory reset — comando explicito
- **Arquivos**: `src/main.rs`, `src/plugins/memory/mod.rs`
- **Problema**: Nao encontrado como comando explicito.
- **Entrega**: Implementar `memory reset` que limpa todos os stores de persistencia com confirmacao; testes positivo e negativo.

## Criterios de aceite por sub-issue

Cada sub-issue deve ter:
1. Teste positivo: prova que dados persistem e sao recuperados corretamente
2. Teste negativo: prova comportamento correto em cenarios de erro (arquivo ausente, corrompido, permissao negada)
3. Evidencia de persistencia real: teste que simula restart (drop da struct + re-init + leitura)

## Ordem sugerida

1. Sub-issue 4 (exec_checkpoint) — verificacao rapida
2. Sub-issue 2 (personal_memory) — ja parcialmente pronto
3. Sub-issue 1 (yool tuples) — fundacional
4. Sub-issue 5 (migrate_apply) — testes apenas
5. Sub-issue 3 (deep_mem) — dependencia externa sqlite3
6. Sub-issue 6 (yool_tokio) — decisao arquitetural necessaria
7. Sub-issue 7 (memory reset) — depende dos outros estarem prontos','docs/issues/1145-plan.md','1def7a8cff20010e5a4fb162baf1db1a8e08ea851be8e4d13836953f1bb92691','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1146-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1146-plan.md','doc: Epic #1146: deploy/infra — Decomposition Plan','# Epic #1146: deploy/infra — Decomposition Plan

## Current State

- **DaytonaDeploy** (`src/daytona_deploy.rs`): CLI wrapper that delegates to the `daytona` binary. Returns honest `Err` when binary is absent. Marked `#[allow(dead_code)]` — not wired into dispatch.
- **SingularityBackend** (`src/singularity_backend.rs`): CLI wrapper for `singularity` binary. Same pattern as Daytona — honest errors, dead code.
- **ModalDeploy** (`src/modal_deploy.rs`): Honest stub (not yet implemented).
- **deploy_env command** (`src/main.rs`, ~lines 73144-73275): `status` and `list` work (read registry file). `deploy`, `destroy`, `hibernate`, `wake` are hard-coded `Err` stubs with no provider selection.

## Sub-issues

### 1. Define provider trait and dispatch pattern
**Files:** `src/deploy_provider.rs` (new), `src/main.rs`

- Create a `DeployProvider` trait with methods: `deploy`, `destroy`, `hibernate`, `wake`, `status`.
- Each backend (Daytona, Singularity, Modal) implements this trait.
- Add `--target <provider>` argument to `deploy_env` subcommand.
- Implement provider selection logic in a factory function.

### 2. Wire DaytonaDeploy into deploy_env dispatch
**Files:** `src/daytona_deploy.rs`, `src/main.rs`

- Remove `#[allow(dead_code)]` from DaytonaDeploy.
- Implement `DeployProvider` for `DaytonaDeploy`.
- Wire `deploy`, `destroy`, `hibernate`, `wake` through the Daytona CLI wrapper.
- Add credential/binary detection (`which daytona`, env var checks).

### 3. Wire SingularityBackend into deploy_env dispatch
**Files:** `src/singularity_backend.rs`, `src/main.rs`

- Remove `#[allow(dead_code)]` from SingularityBackend.
- Implement `DeployProvider` for `SingularityBackend`.
- Wire actions through the Singularity CLI wrapper.
- Add credential/binary detection.

### 4. Implement ModalDeploy provider
**Files:** `src/modal_deploy.rs`

- Implement real Modal CLI integration (replace stub).
- Implement `DeployProvider` for `ModalDeploy`.
- Add credential detection (`modal token` or env vars).

### 5. Provider credential detection and auto-selection
**Files:** `src/deploy_provider.rs`, `src/main.rs`

- When `--target` is omitted, auto-detect available providers by checking for CLI binaries and credentials.
- Return informative error when no provider is available.
- Support `SIMPLICIO_DEPLOY_PROVIDER` env var as default.

### 6. Behavioral tests
**Files:** `tests/deploy_provider_tests.rs` (new)

- Test that old stubs fail with expected error messages.
- Test provider dispatch routes to correct backend.
- Test `--target` argument parsing.
- Negative tests: missing credentials, missing CLI binary, invalid provider name.
- Mock-based tests for each provider''s deploy/destroy/hibernate/wake.

## Suggested order

1 → 2 → 3 → 4 → 5 → 6

Sub-issues 2, 3, 4 can be parallelized after 1 is merged.

## Constraints

- `std` + `serde` + `serde_json` only (no additional dependencies).
- No `.unwrap()` in production code.
- All errors must be descriptive and actionable.','docs/issues/1146-plan.md','b7db110fbcb138ec71f202956caed5074b5b3cc7630fdb58a4c4a3daaba581b2','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1148-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1148-plan.md','doc: Epic #1148 — fake D: plataformas mensagem sem I/O','# Epic #1148 — fake D: plataformas mensagem sem I/O

## Problem

Multiple messaging platform adapters in `src/gateway/platforms/` and `src/plugins/platforms/` contain silent no-op methods that return `Ok(())` without performing any real work. This hides failures from callers — e.g., `add_reaction` silently succeeds on platforms that don''t support reactions (email, IRC). Additionally, credential/config validation is inconsistent, and the plugin layer may duplicate stubs instead of delegating to gateway adapters.

## Affected Platforms

| # | Platform | Gateway file | Plugin file |
|---|----------|-------------|-------------|
| 1 | Email | `gateway/platforms/email.rs` | — |
| 2 | Teams | `gateway/platforms/teams.rs` | `plugins/platforms/teams.rs` |
| 3 | Google Chat | `gateway/platforms/google_chat.rs` | `plugins/platforms/google_chat.rs` |
| 4 | IRC | `gateway/platforms/irc.rs` | `plugins/platforms/irc.rs` |
| 5 | Mattermost | `gateway/platforms/mattermost.rs` | `plugins/platforms/mattermost.rs` |
| 6 | WhatsApp | `gateway/platforms/whatsapp.rs` | — |

## Sub-tasks

### Sub-task 1: Email adapter honesty audit
- **Files**: `src/gateway/platforms/email.rs`
- Convert `add_reaction`, `start_listening`, `register_webhook` silent `Ok(())` to `Err("email: <method> not supported")`.
- Add negative test for missing SMTP credentials (empty token).
- Add behavioral test proving `add_reaction` returns `Err`.

### Sub-task 2: Teams adapter honesty audit
- **Files**: `src/gateway/platforms/teams.rs`, `src/plugins/platforms/teams.rs`
- Audit `connect()`, `start_listening()`, `add_reaction()` — convert silent no-ops to explicit errors.
- Validate that `plugins/platforms/teams.rs` delegates to the gateway adapter, not a duplicated stub.
- Add negative test for missing webhook URL / tenant credentials.

### Sub-task 3: Google Chat adapter honesty audit
- **Files**: `src/gateway/platforms/google_chat.rs`, `src/plugins/platforms/google_chat.rs`
- Convert `connect()`, `start_listening()`, `add_reaction()` silent `Ok(())` to `Err`.
- Verify plugin mirrors gateway.
- Add credential-missing negative test.

### Sub-task 4: IRC adapter honesty audit
- **Files**: `src/gateway/platforms/irc.rs`, `src/plugins/platforms/irc.rs`
- Convert `add_reaction` `Ok(())` to `Err("irc: reactions not supported")`.
- Audit `connect()` and `start_listening()` for silent failures.
- Verify plugin-to-gateway wiring.

### Sub-task 5: Mattermost adapter honesty audit
- **Files**: `src/gateway/platforms/mattermost.rs`, `src/plugins/platforms/mattermost.rs`
- Same pattern: convert no-ops, verify plugin delegation, add negative tests.

### Sub-task 6: WhatsApp adapter + audio STT/TTS validation
- **Files**: `src/gateway/platforms/whatsapp.rs`
- Audit all `Ok(())` returns (there are many — ~10 instances).
- Validate `whatsapp_audio` end-to-end STT/TTS backend calls actually error when backend is unavailable.
- Add negative test for missing WhatsApp API token.

### Sub-task 7: Webhook path audit (cross-platform)
- **Files**: all six gateway adapters above + `mod.rs`
- Audit `register_webhook` / `unregister_webhook` across all platforms.
- Ensure paths that silently succeed without real I/O return `Err`.

### Sub-task 8: `htool_send_message_tool.rs` integration
- **File**: `src/htool_send_message_tool.rs`
- Verify the tool properly surfaces errors from gateway adapters instead of swallowing them.
- Add integration-level test showing tool returns error JSON when platform adapter fails.

### Sub-task 9: CHANGELOG + documentation
- Update CHANGELOG with entries for each platform fix.
- Document the "honest error" pattern for future platform contributors.

## Execution Order

```
Sub-tasks 1-5 can run in parallel (independent platforms).
Sub-task 6 (WhatsApp) can run in parallel with 1-5.
Sub-task 7 depends on 1-6 (cross-cutting audit).
Sub-task 8 depends on 1-6 (integration layer).
Sub-task 9 is last.
```

## Acceptance Criteria

- [ ] No platform adapter method returns silent `Ok(())` for operations it cannot perform.
- [ ] Every platform has a negative test for missing credentials/config.
- [ ] `plugins/platforms/*` modules delegate to `gateway/platforms/*`, no duplicated stubs.
- [ ] `htool_send_message_tool` surfaces adapter errors in JSON output.
- [ ] `cargo check` and `cargo test` pass.
- [ ] CHANGELOG updated.','docs/issues/1148-plan.md','39c7c3ec9d10db10671bbbe3835615f285c58705fba1be7b97b0f3004a4daed7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1151-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1151-evidence.md','doc: Issue #1151 — Evidence: Already Implemented','# Issue #1151 — Evidence: Already Implemented

## Gap 1: Hardcoded passed: true in contracts_smoke runtime check
- **File**: src/main.rs lines 3466-3475
- **Fix**: 
untime_self_check() function performs real validation (sealed-receipt crypto round-trip, benchmark suite instantiation, VERSION check)
- **Introduced by**: commit 13506ced feat(#1170)

## Gap 2: sealed_receipt not wired into evidence pipeline
- **File**: src/main.rs lines 52396-52430
- **Fix**: write_evidence_bundle() now hashes all evidence artifacts via sealed_receipt::ReceiptBuilder and writes vidence/sealed-receipt.json
- **Introduced by**: commit 75782c1f feat(#1179)

## Gap 3: eval/benchmark path returns "not implemented"
- **File**: src/main.rs lines 11275-11340
- **Fix**: val_command() delegates 
un/ench to enchmark_harness::benchmark_harness_command(), status runs real self-check via enchmark_suite, list shows available harness tasks
- **Introduced by**: commit 13506ced feat(#1170)','docs/issues/1151-evidence.md','cf8f1892807d2969edd203381345e1b62533108f6138d0678ca3aa6ebd99f41f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1152-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1152-plan.md','doc: Plan: Epic #1152 - Anti-Fake Remediation (615 findings)','# Plan: Epic #1152 - Anti-Fake Remediation (615 findings)

Parent epic: #1038 | Source audit: #858

## Overview

Audit scan found 1,647 occurrences of `todo!`, `unimplemented!`, `stub`, `placeholder`, `fake`, and `mock` across 177 source files. This plan decomposes the remediation into prioritized work packages.

## Methodology

Each finding must be triaged as:
- **CRITICAL**: stub/placeholder in production code path (runtime panic risk)
- **HIGH**: fake/mock logic returned as real data
- **MEDIUM**: unimplemented feature behind feature flag or secondary path
- **LOW**: test helpers, dev-only mocks, or intentional todo markers for future features

## Work Packages

### WP-1: Core Runtime Stubs (CRITICAL, ~80 findings)
Files with highest stub density in critical paths:

| File | Count | Category |
|------|-------|----------|
| `main.rs` | 277 | Command dispatch stubs |
| `audit_command.rs` | 74 | Audit logic placeholders |
| `htool_vision_tools.rs` | 38 | Vision tool stubs |
| `length_continuation.rs` | 35 | Continuation logic stubs |
| `htool_send_message_tool.rs` | 22 | Message sending stubs |
| `htool_browser_cdp_tool.rs` | 22 | Browser CDP stubs |

**Action**: Replace each `todo!()` / `unimplemented!()` with proper error handling (`Err(...)`) or real implementation. No `.unwrap()` in production.

### WP-2: Agent & Conversation Loop (CRITICAL, ~70 findings)
| File | Count |
|------|-------|
| `agent_runtime_helpers.rs` | 21 |
| `conversation_loop_driver.rs` | 17 |
| `image_routing.rs` | 17 |
| `htool_code_execution_tool.rs` | 14 |
| `chat_completion_helpers.rs` | 15 |
| `context_compressor.rs` | 14 |
| `curator_parity.rs` | 14 |
| `htool_xai_http.rs` | 14 |

### WP-3: Tool Implementations (HIGH, ~120 findings)
htool_* files with stubs:

| File | Count |
|------|-------|
| `htool_transcription_tools.rs` | 20 |
| `htool_file_tools.rs` | 18 |
| `htool_browser_supervisor.rs` | 16 |
| `htool_voice_mode.rs` | 16 |
| `htool_computer_use_tool.rs` | 13 |
| `htool_yuanbao_tools.rs` | 13 |
| `htool_skills_hub.rs` | 13 |
| `htool_delegate_tool.rs` | 15 |
| `htool_mcp_tool.rs` | 12 |
| `htool_vision_tools.rs` | 38 |
| Other htool_* files | ~40 |

### WP-4: Platform Integrations (MEDIUM, ~30 findings)
| File | Count |
|------|-------|
| `platform_irc.rs` | 7 |
| `platform_google_chat.rs` | 5 |
| `platform_mattermost.rs` | 3 |
| `plugins/google_meet/*.rs` | ~44 |
| `tools_browser.rs` | 16 |

### WP-5: Skills & Growth (MEDIUM, ~50 findings)
| File | Count |
|------|-------|
| `skill_commands.rs` | 9 |
| `growth_landing_builder.rs` | 9 |
| `growth_asset_rights.rs` | 7 |
| `skill_fastmcp.rs` | 6 |
| `skill_bundles.rs` | 4 |
| Other skill_*.rs | ~15 |

### WP-6: Infrastructure & Parity (MEDIUM, ~40 findings)
| File | Count |
|------|-------|
| `update_command.rs` | 10 |
| `tui_app.rs` | 10 |
| `video_pipeline.rs` | 11 |
| `anthropic_adapter_parity.rs` | 9 |
| `prompt_builder_parity.rs` | 8 |
| `message_repair.rs` | 8 |
| `turn_context_parity.rs` | 7 |
| `lsp_manager.rs` | 7 |
| `distributed_lock.rs` | 6 |

### WP-7: Low-Priority & Test Helpers (LOW, ~30 findings)
| File | Count |
|------|-------|
| `test_helpers.rs` | 3 |
| `final_modules.rs` | 9 |
| `models_dev.rs` | 5 |
| Various single-occurrence files | ~15 |

## Suggested Issue Decomposition

Create child issues for each work package:
1. **#TBD** - WP-1: Remediate main.rs and audit_command.rs stubs (CRITICAL)
2. **#TBD** - WP-2: Remediate agent loop and conversation driver stubs (CRITICAL)
3. **#TBD** - WP-3: Remediate htool_* tool stubs (HIGH) - split into 3-4 sub-issues by tool category
4. **#TBD** - WP-4: Remediate platform integration stubs (MEDIUM)
5. **#TBD** - WP-5: Remediate skill and growth module stubs (MEDIUM)
6. **#TBD** - WP-6: Remediate infra and parity stubs (MEDIUM)
7. **#TBD** - WP-7: Triage low-priority stubs (LOW)

## Acceptance Criteria per Finding

1. Identify the stub/placeholder (`todo!()`, `unimplemented!()`, fake return value)
2. Replace with real implementation OR proper error propagation (`Result<_, Error>`)
3. No `.unwrap()` in production code paths
4. Add at least one behavioral test and one negative test
5. `cargo build` and `cargo test` pass
6. PR reviewed and merged

## Estimated Effort

- **CRITICAL (WP-1 + WP-2)**: ~150 findings, 5-8 sprints
- **HIGH (WP-3)**: ~120 findings, 4-6 sprints
- **MEDIUM (WP-4 + WP-5 + WP-6)**: ~120 findings, 3-5 sprints
- **LOW (WP-7)**: ~30 findings, 1 sprint
- **Total**: ~420 actionable findings (remaining ~195 are in .bak files or test-only code)','docs/issues/1152-plan.md','d7a1d763bb90c495f6a87bcc4d9147b2f2051ef19ddd5739d0948b029b7d03c8','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1154-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1154-plan.md','doc: Epic #1154: Video Creation Pipeline — Decomposition Plan','# Epic #1154: Video Creation Pipeline — Decomposition Plan

## Overview

The video pipeline has extensive scaffolding across Rust runtime and Python agent layers, but all actual video generation returns `Err("not implemented")`. This plan decomposes the epic into concrete, independently deliverable sub-tasks.

---

## Sub-task 1: Wire public dispatch for video pipeline commands

**Files:** `src/main.rs`, `src/tool_registry.rs`, `src/htool_video_generation_tool.rs`

- Register `video_generate` as a recognized tool in the tool registry match arm.
- Ensure `htool_video_generation_tool.rs` is declared as a module in `main.rs`.
- Route incoming tool calls to `video_pipeline.rs` subcommands (script, audio, timeline, render, captions, orchestrate).
- Validate input schema (provider, prompt, duration, resolution) with proper error handling.

**Acceptance:** `cargo check` passes; calling the tool with valid input reaches the pipeline dispatch (returns "not implemented" at provider level, not "unknown tool").

---

## Sub-task 2: Implement provider abstraction and registry

**Files:** `src/video_provider.rs`, `agent/video_gen_provider.py`, `agent/video_gen_registry.py`

- Define `VideoProvider` trait in Rust with `submit_job`, `poll_status`, `download_result` async methods.
- Implement provider registry that loads provider configs from environment variables (API keys, endpoints).
- Python-side `video_gen_registry.py`: mirror registry for agent layer, mapping provider names to handler classes.
- Return structured errors for missing credentials or unsupported providers.

**Acceptance:** Registry correctly resolves provider by name; missing config returns descriptive error (not panic).

---

## Sub-task 3: Implement first real provider (HTTP job submission)

**Files:** `src/video_provider.rs`, `agent/video_gen_provider.py`, `hermes_port_staging/video_provider.rs`

- Pick one provider with a public API (e.g., Runway, Pika, or Higgsfield) and implement real HTTP calls using `reqwest` or `ureq`.
- Implement job submission (POST with prompt + parameters), status polling, and result URL retrieval.
- Use `serde_json` for request/response serialization.
- No `.unwrap()` in production code — all errors propagated via `Result`.
- Python agent fallback in `video_gen_provider.py` for the same provider.

**Acceptance:** Submitting a job with valid credentials returns a job ID; polling returns status; invalid credentials return auth error.

---

## Sub-task 4: Replace stubs in video_pipeline.rs with real orchestration

**Files:** `src/video_pipeline.rs`, `src/tools_video_generate.rs`

- Wire `video_pipeline.rs` subcommands to use the provider abstraction from Sub-task 2.
- `orchestrate` subcommand: coordinate script generation, audio, timeline, render, and captions in sequence.
- `render` subcommand: call the real provider from Sub-task 3.
- Remove all `Err("not implemented")` returns, replacing with actual logic or `Err("provider X not configured")` for unconfigured providers.
- Multi-provider detection in `tools_video_generate.rs`: select provider based on config/user preference.

**Acceptance:** Full pipeline from prompt to submitted render job works end-to-end with at least one provider.

---

## Sub-task 5: Test suite

**Files:** `tests/video_pipeline_test.rs` (new), `tests/video_provider_test.rs` (new)

- **Behavioral tests:** Verify old stubs fail with expected error messages (regression guard).
- **Negative tests:** Missing API key returns config error; invalid provider name returns "unsupported provider"; malformed input returns validation error.
- **Integration test (mock):** Mock HTTP responses for the chosen provider; verify job submission, polling, and result retrieval.
- **End-to-end validation:** With env vars set, submit a real job (gated behind `#[ignore]` or feature flag for CI).

**Acceptance:** `cargo test` passes; negative cases covered; at least one mock integration test.

---

## Sub-task 6: Update CHANGELOG and documentation

**Files:** `CHANGELOG.md`, `README.md` (if applicable)

- Add entry for video pipeline feature.
- Document supported providers, required environment variables, and usage examples.
- Document the tool schema for `video_generate`.

**Acceptance:** CHANGELOG updated; docs match implemented behavior.

---

## Suggested implementation order

1. Sub-task 1 (wire dispatch) — unblocks everything
2. Sub-task 2 (provider abstraction) — needed before real implementation
3. Sub-task 3 (first real provider) — core value delivery
4. Sub-task 4 (replace stubs) — full pipeline wiring
5. Sub-task 5 (tests) — can start in parallel with Sub-tasks 3-4
6. Sub-task 6 (docs) — after implementation stabilizes

## Estimated scope

- **Sub-tasks 1-2:** Small (~50-100 lines each)
- **Sub-task 3:** Medium (~200-400 lines)
- **Sub-task 4:** Medium (~150-300 lines)
- **Sub-task 5:** Medium (~200-300 lines)
- **Sub-task 6:** Small (~50 lines)','docs/issues/1154-plan.md','b8be7ebd1b696f0bd19048e222248fe44a076f9f400b91c756c6ed40cb25f5d5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1157-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1157-plan.md','doc: Epic #1157 — Auditoria pronto-que-nao-esta-pronto','# Epic #1157 — Auditoria pronto-que-nao-esta-pronto

Decomposition plan for remediating ~615 fake-code findings from audit #841.

---

## Sub-issue 1 (P0): Delivery gates that cannot fail

**Priority:** CRITICAL — blocks release
**Scope:** ~8 findings (A.6, A.7, A.8, H.35–H.39)
**Files:** `main.rs` (lines ~45529, ~1735), `sealed_receipt.rs`, `hooks_command.rs`, `login_command.rs`
**Work:**
- `write_foreground_functional_gates`: make gates actually evaluate conditions and return real pass/fail
- `contracts_smoke`: wire real contract invocation or return Err if no contracts configured
- `sealed_receipt.rs`: replace SipHash with real SHA-256 (use `sha2` crate or std-compatible impl); fix `verify` to do full hash comparison
- `hooks_command.rs`: `test` must actually run the hook script; `doctor` must perform real filesystem checks
- `login_command.rs`: `logout` must delete token file; `status` must read real provider auth state
- `sandbox_set_policy`: persist policy to config file and enforce on subsequent commands
**Acceptance:** `cargo test` passes; gates return `Err` on invalid input; `verify` rejects tampered receipts

---

## Sub-issue 2 (P1): Fake recovery and state persistence suite

**Priority:** CRITICAL
**Scope:** ~20 findings (G.27–G.34, K.46, plus checkpoint/state/memory commands)
**Files:** `memory_command.rs`, `main.rs` (lines ~41341, ~66630, ~37371, ~37013, ~38356, ~7152, ~6362, ~65090)
**Work:**
- `memory_command::reset()`: actually clear memory store files
- `personal_memory_store/recall`: implement file-based read/write to `.simplicio-loop/memory/`
- `deep_mem_*`: wire to real SQLite or file store; remove hardcoded counts
- `exec_checkpoint_save/restore`: serialize/deserialize process state to disk
- `yool_get_command/yool_query_command`: read from the same path `yool_put` writes to
- `migrate_apply_command`: create real ledger and backup files
- `agent_state_publish`, `human_agent_publish`, `exec_graph_define`: write to Yool blackboard for real
- `cron_sched_*`: implement real cron parsing (not always `0 9 * * *`)
**Acceptance:** round-trip tests (store then recall returns stored data); checkpoint save/restore preserves state

---

## Sub-issue 3 (P1): Fake observability suite

**Priority:** CRITICAL
**Scope:** ~11 findings (B.9, J.42–J.44)
**Files:** `main.rs` (lines ~63461–63586, ~40962–41296, ~65509–65598, ~65416)
**Work:**
- `obs_status/logs/audit/metrics/dashboard/export`: read real process metrics (timestamps, actual log files, real CPU/mem via `sysinfo` or `/proc`)
- `quality_dimensions/gates_run/status/configure/report`: implement real measurement or return Err("not configured")
- `auto_learn_*`: wire to real learning cycle state or remove
- `hermes_parity_update`: persist parity status changes to file
- `evidence_show_summary/ledger/tokens`: read from `.simplicio-loop/runs/` directory
**Acceptance:** `obs_export` creates a real file; quality gates can fail; evidence reads real ledger data

---

## Sub-issue 4 (P1): Fake tool integrations (browser, messaging, providers)

**Priority:** CRITICAL
**Scope:** ~25 findings (C.10–C.13, D.14–D.21, E.22)
**Files:** `tools_browser.rs`, `email_platform.rs`, `teams_platform.rs`, `platform_google_chat.rs`, `platform_irc.rs`, `platform_mattermost.rs`, `webhook_command.rs`, `integration_openrouter.rs`, `integration_anthropic.rs`, `integration_deepseek.rs`, `integration_gemini.rs`
**Work:**
- Browser tools: return `Err("browser daemon not running")` instead of fake success when no CDP session exists
- Email: return `Err("SMTP not configured")` / `Err("IMAP not configured")` instead of fake send/receive
- Teams/Mattermost/IRC/Google Chat: return `Err` when no valid connection; remove hardcoded URLs and tokens from production paths
- Webhook: return `Err("no listener bound")` instead of claiming listener started
- Provider integrations (4 files): replace hardcoded `"ready"` with real HTTP health check or honest `Err("not implemented")`; mark model catalogs as `last_updated` with real dates or remove stale pricing
**Acceptance:** all integrations return `Err` when unconfigured; no hardcoded tokens/URLs in production code

---

## Sub-issue 5 (P2): Fake deploy/infra and subprocess patterns

**Priority:** HIGH
**Scope:** ~10 findings (F.23–F.26, K.45, K.47–K.48)
**Files:** `daytona_deploy.rs`, `singularity_backend.rs`, `main.rs` (lines ~26777, ~66327, ~8739, ~8344, ~40744, ~68058)
**Work:**
- `daytona_deploy.rs`: return `Err("deploy backend not configured")` or wire real API call
- `singularity_backend.rs`: same pattern
- `service` command: use real process check (tasklist/systemctl) for status
- `deploy_env_*`: return `Err` or wire real deploy
- `scheduler_capacity_command`: read real CPU/RAM via system calls
- `eval_command`, `agi_bench_run_command`: return `Err("eval engine not available")`
- Voice commands: return `Err("TTS/STT not configured")`
- Benchmark commands (A.1–A.3): remove fabricated competitive data; return `Err` or run real measurements
**Acceptance:** no command prints success without performing work; `cargo check` passes

---

## Sub-issue 6 (P3): 335 shape-only tests

**Priority:** MEDIUM
**Scope:** ~250 fake tests (232 `is_ok()`-only + ~100 others)
**Files:** test modules across codebase
**Work:**
- Audit all `#[test]` functions that only assert `is_ok()` or `is_some()`
- For each: add behavioral assertions (check output content, verify side effects, test error paths)
- Add negative tests: invalid input returns `Err`, missing config returns `Err`
- Remove tests that codify fake network success (asserting hardcoded strings)
- Ensure test coverage for all P0–P2 remediations above
**Acceptance:** `cargo test` passes; no test asserts only `is_ok()` without checking the value; negative test coverage for all critical paths

---

## Execution Order

```
P0 (Sub-issue 1) ──► P1 (Sub-issues 2, 3, 4 in parallel) ──► P2 (Sub-issue 5) ──► P3 (Sub-issue 6)
```

Each sub-issue should be a separate PR with `cargo check` + `cargo test` pass','docs/issues/1157-plan.md','347668413ef0042ad37ba169d166fe6f26ba3236a1beec0387ea332184004423','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1158-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1158-evidence.md','doc: Issue #1158 — Flaky: 2 testes background-task TUI','# Issue #1158 — Flaky: 2 testes background-task TUI

## Status: Already Implemented

All three changes from the edit plan (`.simplicio-loop/edit-plan-test-fixes-5-tui.json`) have already been applied to `src/tui_app.rs`.

## Evidence

### 1. NTFS mtime race fix (line 19472-19487)

The NTFS directory mtime retry loop is present at `src/tui_app.rs:19472`:

```
// NTFS directory mtime resolution can be ~16ms under load — recreate
// the file until the newer run dir''s mtime is strictly past the older''s
for _ in 0..100 {
    ...
    if fs::metadata(&newer).unwrap().modified().unwrap() > older_mtime { break; }
    std::thread::sleep(std::time::Duration::from_millis(10));
}
```

### 2. Poll timeout increase + is_empty check for /map test (line 20785-20792)

`wait_for_background_output(&mut app, 600, |_| true)` at `src/tui_app.rs:20787` — the generous 600-iteration budget is in place with the "Generous budget" comment.

### 3. Poll timeout increase + is_empty check for busy-inline test (line 20748-20750)

`wait_for_background_output(&mut app, 1800, |_| true)` at `src/tui_app.rs:20750` — even more generous budget for this test, with the background_tasks.is_empty() check handled inside `wait_for_background_output`.','docs/issues/1158-evidence.md','57ea01991c7b720f2425a2cc498db538e4f40a61326ff9daf670650e3298fb6b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1159-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1159-evidence.md','doc: Issue #1159: Cleanup: fn entitlement orfao','# Issue #1159: Cleanup: fn entitlement orfao

## Status: Already Done

The orphaned `fn entitlement(config: RuntimeConfig) -> Result<(), String>` function no longer exists on `main`.

## Evidence

- `git show main:src/main.rs | Select-String "fn entitlement\("` returns no matches.
- The only `entitlement`-prefixed functions on main are helpers that are actively used:
  - `fn entitlement_window_name(window: &str) -> String`
  - `fn entitlement_subscription_check_json(window: &str) -> String`
  - `fn entitlement_policy_json() -> String`
- The dispatch at line ~1971 routes `"entitlement"` to `license::license_command`, confirming no call site ever existed for the orphan.

## Conclusion

The dead code was already removed in a prior commit. No further action needed.','docs/issues/1159-evidence.md','c7ef2cf0b44f60d5803f51155034872e335c4be0566741a5a79a2ef47061c6ee','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1160-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1160-plan.md','doc: Plan: Savings Dashboard v2 (#1160)','# Plan: Savings Dashboard v2 (#1160)

## Overview

The savings dashboard v2 code partially exists (savings_dashboard_json, savings_dashboard_markdown, by_client/by_model/task_link aggregation in main.rs, cost_ledger.rs for per-mechanism tracking). This epic completes the end-to-end implementation across recording, aggregation, presentation, CLI dispatch, and test coverage.

## Sub-tasks

### 1. Recording: Populate client and model attribution fields
- **Files**: `src/main.rs` (write_cost_ledger, savings_record), `src/cost_ledger.rs`
- **Work**: Ensure `client` and `model` fields are consistently captured from the runtime context (current LLM provider, model ID) at every savings_record call site. Currently these fields are declared but often written as empty strings.
- **Acceptance**: Every cost ledger entry has non-empty `client` and `model` when the runtime context provides them.

### 2. Recording: Populate task/sprint linkage
- **Files**: `src/main.rs` (savings_record, task runner integration)
- **Work**: Pass `task_id` and `sprint_id` from the task runner into savings_record instead of empty strings. Requires threading these values through the call chain from the task dispatch.
- **Acceptance**: Ledger entries created during task execution carry the correct task and sprint identifiers.

### 3. Aggregation: Validate by_client / by_model / task_link grouping
- **Files**: `src/main.rs` (savings_dashboard_json)
- **Work**: Review and fix the aggregation logic so that populated client/model/task fields produce correct grouped summaries. Handle edge cases (unknown client, missing model).
- **Acceptance**: JSON dashboard output groups costs correctly by client, model, and task.

### 4. Presentation: Markdown and JSON output
- **Files**: `src/main.rs` (savings_dashboard_markdown), `schemas/growth-dashboard.schema.json`
- **Work**: Ensure markdown renderer uses the new aggregation fields. Update the JSON schema to reflect v2 fields (client, model, task_link). Add totals row and percentage-of-savings columns.
- **Acceptance**: Both markdown and JSON outputs include all v2 fields and match the schema.

### 5. CLI dispatch: Wire `simplicio savings report`
- **Files**: `src/dashboard_command.rs`, `src/main.rs` (CLI arg parsing)
- **Work**: Add/complete the `savings report` subcommand that calls savings_dashboard_json or savings_dashboard_markdown based on `--format` flag. Register in CLI dispatch.
- **Acceptance**: `simplicio savings report` and `simplicio savings report --format json` produce correct output.

### 6. Tests: Behavioral tests for partial/missing data
- **Files**: new test module or `tests/` directory
- **Work**:
  - Test that old partial behavior (empty client/model) is detected and handled gracefully.
  - Test missing config/credentials scenarios return meaningful errors (not panics).
  - Test aggregation with mixed populated/empty fields.
  - Test CLI dispatch returns correct exit codes.
- **Acceptance**: All tests pass with `cargo test`. No `.unwrap()` on user-facing paths.

### 7. Documentation
- **Files**: README or docs
- **Work**: Document the `savings report` command, its flags, and output format.
- **Acceptance**: Usage documented.

## Suggested implementation order

1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7

Sub-tasks 1 and 2 are prerequisites for 3. Sub-task 5 depends on 4. Tests (6) should be written alongside or after each sub-task.

## Constraints

- std + serde + serde_json only
- No `.unwrap()` in production code
- All errors must be propagated with `Result` types','docs/issues/1160-plan.md','b8e559a9afce035b08506b1b8dd80038cb44f753c47d8b617ede42d8f967af82','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1164-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1164-plan.md','doc: Epic #1164: Monetizacao — licenca + billing','# Epic #1164: Monetizacao — licenca + billing

## Status atual (auditoria)

| Subsistema | Arquivo(s) | Estado |
|---|---|---|
| License key (ed25519) | `src/license.rs` | Implementado: parse, verify, tiers (Free/Trial/Economy/Pro), grace period. **Nao wired no dispatch.** |
| Stripe checkout/portal | `src/growth_stripe.rs` | Implementado: `stripe_post`, checkout session, customer portal, funnel. **Enforcement desabilitado.** |
| Entitlement schema | `schemas/entitlement.schema.json` | Schema definido com campos `enforcement`, `future_gate`, `subscription_check`. |
| PHP endpoints | `site/api/stripe-checkout.php`, `stripe-sync.php`, `entitlement.php`, `entitlement-public.php` | Existem, webhooks parciais. |
| Action gate | `src/action_gate.rs` | Gate de seguranca existente, **sem integracao com license tier**. |
| Tool registry | `src/tool_registry.rs` | Dispatch de comandos, **sem tier check**. |

## Decomposicao em sub-issues

### Sub-issue 1: Wire license check into runtime command dispatch
**Prioridade:** P0 (pre-requisito para tudo)

- Em `tool_registry.rs`, importar `license::{load_active_license, Tier}`.
- Antes de cada dispatch, chamar `load_active_license()` e comparar o tier contra o tier minimo do comando.
- Comandos free-tier (map, edit, gate, checkpoint, validate) passam sempre.
- Comandos economy+ (token-savings, batch, cost-ledger) exigem `Tier::Economy`.
- Comandos pro (local-llm routing, managed remote) exigem `Tier::Pro`.
- Retornar erro estruturado `simplicio.license-denied/v1` com tier atual, tier requerido, e URL de upgrade.
- **Testes:** unitarios para cada tier boundary + teste de regressao para comandos free.

### Sub-issue 2: Enable Stripe subscription enforcement (fail-closed)
**Prioridade:** P1

- Em `growth_stripe.rs`, implementar `verify_subscription_active(email: &str) -> Result<bool, String>`.
- Respeitar `entitlement.schema.json` campo `enforcement`: quando `"strict"`, falhar se Stripe retornar subscription inativa.
- Implementar cache local (arquivo JSON em `~/.simplicio-loop/stripe_cache.json`) com TTL de 24h para evitar chamadas excessivas.
- Fail-closed: se a verificacao falhar (rede, timeout, erro Stripe), negar acesso a features pagas.
- Grace period: 3 dias apos expiracao para permitir reativacao sem perda de acesso.
- **Testes:** mock de respostas Stripe (sucesso, falha, timeout), verificacao de fail-closed.

### Sub-issue 3: Behavioral + negative tests para license validation
**Prioridade:** P1

- Criar `tests/license_validation.rs` com:
  - Chave valida com cada tier -> acesso correto.
  - Chave expirada -> deny com grace period.
  - Chave expirada alem do grace -> deny total.
  - Assinatura invalida -> reject.
  - Payload malformado (JSON invalido, campos faltando) -> reject.
  - Clock skew simulation (data futura/passada).
  - Chave com tier desconhecido -> fallback para Free.
- Rodar com `cargo test --test license_validation`.

### Sub-issue 4: Behavioral tests para Stripe checkout/portal flows
**Prioridade:** P2

- Criar `tests/stripe_flows.rs` com:
  - Checkout session creation (dry-run mode) -> JSON valido com session URL.
  - Customer portal session (dry-run) -> JSON valido com portal URL.
  - Funnel completo (dry-run) -> encadeia checkout + customer lookup.
  - Erro de STRIPE_SECRET_KEY ausente -> mensagem clara.
  - Resposta Stripe com `error` object -> propagacao correta.
  - Rate limiting (429) -> retry com backoff.
- **Nota:** testes live requerem `STRIPE_SECRET_KEY` de teste; CI usa dry-run.

### Sub-issue 5: Integrate entitlement policy into gate decisions
**Prioridade:** P2

- Em `action_gate.rs`, alem do risk analysis atual, consultar entitlement policy.
- Carregar `entitlement.schema.json` policy file de `~/.simplicio-loop/entitlement.json`.
- Se `current_phase == "free"` e acao requer paid tier -> deny com mensagem de upgrade.
- Se `subscription_check.enabled == true` e `should_check_now == true` -> chamar `verify_subscription_active`.
- Adicionar campo `entitlement_status` ao JSON de decisao do gate.
- **Testes:** gate decisions com diferentes combinacoes de tier + entitlement policy.

### Sub-issue 6: PHP webhook hardening + sync
**Prioridade:** P3

- `stripe-sync.php`: validar assinatura do webhook (`Stripe-Signature` header) com HMAC.
- `stripe-checkout.php`: adicionar CSRF token, rate limiting.
- `entitlement.php`: retornar entitlement status baseado em subscription ativa.
- `entitlement-public.php`: endpoint read-only para CLI verificar tier sem credentials.
- **Testes:** integration tests com PHPUnit ou equivalente.

## Ordem de execucao recomendada

```
Sub-issue 3 (testes license) ─┐
                               ├──> Sub-issue 1 (wire license) ──> Sub-issue 5 (gate integration)
Sub-issue 4 (testes stripe)  ─┤
                               └──> Sub-issue 2 (stripe enforcement)
                                                                    └──> Sub-issue 6 (PHP hardening)
```

## Riscos

1. **Chave privada ed25519**: nunca deve aparecer em commit. Verificar `.gitignore` e CI secrets.
2. **Fail-closed vs fail-open**: decisao de produto. Recomendacao: fail-closed para Pro, fail-open para Economy (grace).
3. **Clock manipulation**: usuario pode alterar relogio do sistema para estender trial. Mitigacao: nonce monotono persistido localmente.
4. **Stripe test vs live keys**: CI deve usar apenas test keys. Guardrail no codigo para rejeitar `sk_live_*` em modo teste.','docs/issues/1164-plan.md','da56ef3a36f331093e5a43fed202cd3c2eb2849e75ecdd2bf36c1a52d31e0a1a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1165-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1165-evidence.md','doc: Issue #1165 — search_brave() placeholder — ALREADY IMPLEMENTED','# Issue #1165 — search_brave() placeholder — ALREADY IMPLEMENTED

## Evidence

### 1. `src/tools_web_search.rs` (lines 93-156)

Full implementation of `search_brave()` that:
- Reads `BRAVE_SEARCH_API_KEY` (line 94-97), returns error if missing
- Clamps limit to 1..20 (line 98)
- Builds URL to `https://api.search.brave.com/res/v1/web/search` (lines 99-103)
- Executes real HTTP call via `curl` with proper headers including `X-Subscription-Token` (lines 105-118)
- Checks HTTP status and reports errors (lines 120-123)
- Parses JSON response, extracts `web.results[]` array (lines 126-134)
- Maps each result to `SearchResult { title, url, snippet, source: "brave" }` (lines 136-153)

### 2. `src/htool_web_tools.rs` (lines 403-449)

Independent implementation of `web_search_brave()` that:
- URL-encodes the query (lines 405-414)
- Calls `https://api.search.brave.com/res/v1/web/search` via `run_curl` (lines 416-430)
- Parses JSON response and extracts `web.results` (lines 432-435)
- Returns structured JSON with title, url, description, position (lines 437-448)

### 3. Test coverage

- `brave_requires_api_key` test verifies missing API key returns an error
- Response parsing tests cover multiple search providers (exa, tavily, xai, ddg fixtures)

## Conclusion

The `search_brave()` function is **not a placeholder**. Both implementations make real HTTP calls to the Brave Search API, parse JSON responses, and return structured results. The original placeholder concern from #816 has been fully resolved.','docs/issues/1165-evidence.md','c1fc47769d2fe76a9eb780d400adf308baa8e074110cfcdd9a46f868aa0e1736','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1167-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1167-plan.md','doc: Epic #1167 — Hot-reload de módulos (plugin .so/.dll)','# Epic #1167 — Hot-reload de módulos (plugin .so/.dll)

## Problem

The current plugin system uses compile-time static dispatch. `infra_advanced.rs` has advisory-only `HotReloadMode::Unsupported/Experimental` structs that never call `dlopen`/`libloading`/`LoadLibrary`. The reload command always returns an error. No dynamic library loading exists.

## Decomposition

### Sub-task 1: Define stable C ABI plugin interface

- **Files:** `src/plugins/abi.rs` (new)
- Create a `#[repr(C)]` struct `PluginDeclaration` with: plugin name, version, init/deinit function pointers, and a vtable of capability function pointers.
- Define `extern "C"` function signatures for: `plugin_init`, `plugin_deinit`, `plugin_execute`, `plugin_version`.
- Add ABI version constant for forward compatibility checks.
- **Estimate:** 1 sub-issue

### Sub-task 2: Integrate `libloading` for dynamic library loading

- **Files:** `src/plugins/loader.rs` (new), `Cargo.toml`
- Add `libloading` crate dependency.
- Implement `PluginLoader` struct that wraps `libloading::Library`.
- Safe load/unload with proper error handling (no `.unwrap()`).
- Cross-platform extension resolution: `.so` (Linux), `.dll` (Windows), `.dylib` (macOS).
- **Estimate:** 1 sub-issue

### Sub-task 3: Implement plugin lifecycle manager

- **Files:** `src/plugins/lifecycle.rs` (new)
- Load plugin: open library, resolve `plugin_init` symbol, call it, verify ABI version.
- Unload plugin: call `plugin_deinit`, drop library handle.
- Reload plugin: unload old, load new, verify version is newer or equal.
- Failure isolation: catch panics at FFI boundary, return errors instead of crashing.
- **Estimate:** 1 sub-issue

### Sub-task 4: FileSystemWatcher for automatic reload detection

- **Files:** `src/plugins/watcher.rs` (new)
- Watch a configured plugin directory for `.so`/`.dll`/`.dylib` file changes.
- Use `notify` crate (or polling fallback with `std::fs::metadata` timestamps).
- Debounce rapid changes (e.g., file being written).
- On change detected, trigger reload via lifecycle manager.
- **Estimate:** 1 sub-issue

### Sub-task 5: Wire into existing PluginRegistry

- **Files:** `src/plugins/mod.rs`, `src/plugins/registry.rs`
- Add `DynamicPlugin` variant alongside existing static plugins.
- Registry methods: `register_dynamic`, `unregister_dynamic`, `reload_dynamic`.
- Thread-safe access with `Arc<RwLock<>>` for hot-swap without blocking readers.
- **Estimate:** 1 sub-issue

### Sub-task 6: Update infra_advanced.rs and main.rs

- **Files:** `src/infra_advanced.rs`, `src/main.rs`
- Replace advisory `HotReloadMode` with functional implementation.
- Wire watcher startup into main initialization.
- Add CLI flag or config for plugin directory path.
- Remove "not shipped" error message, replace with actual reload logic.
- **Estimate:** 1 sub-issue

### Sub-task 7: Implement directory-based plugin discovery

- **Files:** `src/memory_provider_parity.rs`, `src/plugins/discovery.rs` (new)
- Resolve the TODO in `memory_provider_parity.rs`.
- Scan plugin directory on startup, load all valid plugins.
- Maintain manifest of loaded plugins with metadata (path, version, load time).
- **Estimate:** 1 sub-issue

### Sub-task 8: Comprehensive tests with fixture plugins

- **Files:** `tests/plugin_hotreload.rs` (new), `tests/fixtures/` (new)
- Create minimal test plugins (C ABI) that can be compiled as `.so`/`.dll`.
- Test: load, unload, reload, version mismatch rejection, corrupt library handling.
- Test: watcher detects file change and triggers reload.
- Test: concurrent access during reload does not panic.
- **Estimate:** 1 sub-issue

## Dependencies

- `libloading` crate (well-established, cross-platform)
- `notify` crate (optional, for filesystem watching — can use polling fallback)
- A C compiler in CI for building test fixture plugins

## Risks

1. **Undefined behavior:** Incorrect FFI usage can cause UB. Mitigate with `catch_unwind` at boundaries and strict ABI versioning.
2. **Platform differences:** Windows DLL loading semantics differ from Unix. `libloading` abstracts most of this.
3. **Memory leaks on unload:** Plugins that allocate must deallocate before unload. The `plugin_deinit` contract must be enforced.

## Suggested order

1 → 2 → 3 → 5 → 6 → 4 → 7 → 8','docs/issues/1167-plan.md','9d836fb0b52216dbfb719534b3fe7444e9e6095931198f0633d91dafc0f51d63','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1168-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1168-plan.md','doc: Plan: #1168 — [Hermes parity] Roadmap UX agente vivo','# Plan: #1168 — [Hermes parity] Roadmap UX agente vivo

## Overview

Epic covering 7 phases to achieve full Hermes parity for the live agent UX in simplicio-runtime. Each phase builds on the previous and can be implemented as an independent issue.

---

## Phase 1: Doctor / Adapters / Contracts Smoke

**Goal:** Validate that all adapters, contracts, and the doctor subsystem pass smoke tests before any agent run.

**Files involved:**
- `src/doctor.rs` — extend with Hermes-parity adapter checks
- `src/hermes_parity_adapters.rs` — ensure adapter contracts match Hermes signatures
- `src/diagnostics.rs` — add smoke-test diagnostics for each adapter

**Deliverables:**
- `doctor hermes-check` subcommand that validates adapter readiness
- Smoke test suite covering all Hermes-compat adapters
- Exit with actionable error messages on contract mismatch

---

## Phase 2: Agent Run --until-green (Observe-Plan-Act-Repair Loop)

**Goal:** Implement the core agent loop with `--until-green` flag that iterates observe-plan-act-repair until all checks pass.

**Files involved:**
- `src/hermes_parity_agent_runner.rs` — main runner with loop logic
- `src/hermes_parity_canonical_loop.rs` — canonical loop implementation
- `src/hermes_parity_run_loop.rs` — run-loop state machine
- `src/message_repair.rs` — message repair on failure
- `src/agent_runtime_helpers.rs` — runtime helper functions

**Deliverables:**
- `agent run --until-green` CLI flag
- Observe-plan-act-repair loop with configurable max iterations
- Repair strategy selection (message repair, context reset, provider fallback)
- Structured logging of each loop iteration

---

## Phase 3: Provider UX Multi-Provider

**Goal:** Seamless multi-provider experience allowing agent to fall back or switch providers mid-run.

**Files involved:**
- `src/hermes_parity_provider_ux.rs` — provider UX orchestration
- `src/provider_registry.rs` — provider registry with fallback chains
- `src/hermes_parity_policy.rs` — policy engine for provider selection

**Deliverables:**
- Provider fallback chain configuration
- Automatic provider switch on rate-limit or error
- Provider health monitoring during agent runs
- UX indicators showing active provider

---

## Phase 4: Import Hermes Metadata

**Goal:** Import and reconcile metadata from Hermes (agent definitions, capability declarations, tool schemas).

**Files involved:**
- `src/hermes_import.rs` — metadata import logic
- `src/hermes_compat.rs` — compatibility layer
- `src/hermes_parity_context.rs` — context mapping from Hermes format

**Deliverables:**
- `hermes import <path>` command to ingest Hermes agent definitions
- Schema validation for imported metadata
- Mapping layer from Hermes capability format to simplicio tool registry

---

## Phase 5: Preserve Memory/Evidence Without Regression

**Goal:** Ensure agent memory and evidence persist across runs without regression in existing functionality.

**Files involved:**
- `src/memory_v2.rs` / `src/memoria_v2.rs` — memory subsystem
- `src/hermes_parity_learn_ext.rs` — learning extension for evidence
- `src/hermes_parity_narrative.rs` — narrative/evidence tracking

**Deliverables:**
- Evidence persistence layer (file-backed, survives restarts)
- Regression test suite comparing memory state before/after agent runs
- Evidence chain linking observations to actions taken
- Non-destructive memory merge on concurrent agent runs

---

## Phase 6: Official Multi-Agent Benchmark

**Goal:** Establish an official benchmark suite for multi-agent scenarios matching Hermes benchmarks.

**Files involved:**
- `src/benchmark_harness.rs` — benchmark execution harness
- `src/hermes_parity_benchmark_agents.rs` — benchmark agent definitions
- `src/tool_executor_parity.rs` — tool execution parity checks
- `src/hermes_parity_readiness.rs` — readiness scoring

**Deliverables:**
- Benchmark suite with at least 5 multi-agent scenarios
- Parity score computation (simplicio vs Hermes baseline)
- Automated benchmark CI integration
- Results report with per-scenario pass/fail and latency metrics

---

## Phase 7: Bare Command UX Final

**Goal:** Polish the bare `agent` command UX for end-user simplicity — no flags required for common workflows.

**Files involved:**
- `src/hermes_parity_bare_task.rs` — bare task execution
- `src/hermes_parity_capabilities_ext.rs` — capability extensions
- `src/hermes_parity_ipc.rs` — IPC for agent coordination
- `agent/` directory — agent configuration and templates

**Deliverables:**
- `simplicio agent` with zero-config defaults
- Interactive mode with progress indicators
- Auto-detection of project context and appropriate agent profile
- Graceful degradation when optional features are unavailable

---

## Dependency Graph

```
Phase 1 (Doctor/Smoke)
    |
    v
Phase 2 (--until-green loop)
    |
    +---> Phase 3 (Multi-provider UX)
    |
    +---> Phase 4 (Hermes metadata import)
    |
    v
Phase 5 (Memory/Evidence)
    |
    v
Phase 6 (Benchmark)
    |
    v
Phase 7 (Bare command UX)
```

## Existing Partial Implementations

The following files already exist with partial implementations and should be extended rather than rewritten:
- `hermes_parity_agent_runner.rs`
- `hermes_parity_benchmark_agents.rs`
- `hermes_parity_policy.rs`
- `benchmark_harness.rs`
- `tool_executor_parity.rs`
- `diagnostics.rs`
- `message_repair.rs`
- `agent_runtime_helpers.rs`','docs/issues/1168-plan.md','3ef1185979c201542df5fa0919860caf20a49d8da04fcfc8904e367f39fc5bf2','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1169-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1169-evidence.md','doc: Issue #1169 — [Hermes parity] Entrada direta de tarefa','# Issue #1169 — [Hermes parity] Entrada direta de tarefa

**Status:** Already implemented.

## Evidence

### Core module: `src/hermes_parity_bare_task.rs`

| Feature | Lines | Detail |
|---|---|---|
| `BareTask` struct | L78-95 | Normalized task contract with `simplicio.task/v1` schema |
| `normalize_task()` | exported fn | Normalizes free-text into structured task |
| `classify_risk()` | enum `RiskLevel` (L26-33) | Safe / Moderate / High classification |
| `classify_intent()` | enum `IntentClass` (L47-61) | Query / Generate / Edit / Delete / Execute / Unknown |
| `TASK_SCHEMA` | L17 | `simplicio.task/v1` |
| `EVIDENCE_LEDGER_SCHEMA` | L20 | `simplicio.evidence-ledger/v1` — ledger integration |
| `bare_task_command()` | exported fn | CLI sub-command handler |
| Unit tests | 21 `#[test]` functions | Comprehensive coverage |

### Wiring: `src/main.rs`

| Feature | Lines | Detail |
|---|---|---|
| Module declaration | L172 | `mod hermes_parity_bare_task;` |
| Import | L176 | `use hermes_parity_bare_task::bare_task_command;` |
| Bare-command fallback | L2927-2964 | `simplicio "<task>"` routes through `bare_task_command` |
| Self-test integration | L41937-42116 | bare_task exercised in self-test with JSON output |

### Acceptance criteria covered

- Task normalization (free-text to `simplicio.task/v1`)
- Risk classification: Safe / Moderate / High
- Intent classification: Query / Generate / Edit / Delete / Execute
- Action gate for write/deploy (Moderate/High risk)
- Read-only tasks execute without unnecessary confirmation (Safe)','docs/issues/1169-evidence.md','5118d86f27a47f39235a13a997adfbf47f68e7c575d83d4187c08e7038dba158','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1172-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1172-plan.md','doc: Plan: #1172 — [Hermes parity] Conversation state/summaries/compression','# Plan: #1172 — [Hermes parity] Conversation state/summaries/compression

## Status

All core modules exist but are marked `#![allow(dead_code)]` with explicit `WIRING TODO` comments. None are integrated into the live runtime.

### Existing modules (not wired)

| Module | Purpose |
|---|---|
| `src/conversation_compression.rs` | `compress_context` entry point, session splitting, image shrinking |
| `src/context_summarize.rs` | LLM summarization seam, prompt construction, prefix constants |
| `src/context_compressor.rs` | `HermesContextCompressor` — token tracking, should_compress/compress |
| `src/context_compression.rs` | Deterministic budget selection, head/tail protection, boundary alignment |
| `src/conversation_loop_driver.rs` | `run_conversation` orchestrator skeleton |
| `src/conversation_control.rs` | Conversation flow control signals |
| `src/conversation.rs` | Conversation data structures |
| `src/organism/conversation.rs` | Organism-level conversation abstraction |
| `src/organism/summarization.rs` | Organism-level summarization |

---

## Sub-tasks

### 1. Wire compression into conversation loop
**Priority: P0 — prerequisite for everything else**

- In `conversation_loop_driver.rs`, after each LLM response, call `HermesContextCompressor::update_from_response()` with token counts.
- Before each outbound API call, call `should_compress()`. If true, call `compress()` and replace the message list.
- Connect `compress_context` (from `conversation_compression.rs`) as the backend for the compressor''s `compress()` method.
- Wire `context_summarize::Summarizer` into the compression pipeline so dropped turns get LLM-summarized.
- Remove `#![allow(dead_code)]` from wired modules.

**Files:** `conversation_loop_driver.rs`, `context_compressor.rs`, `conversation_compression.rs`, `context_summarize.rs`, `main.rs`

### 2. CLI subcommands
**Priority: P1**

Add three CLI subcommands that do not exist yet:

- `chat context` — display current conversation context (token count, message count, compression state)
- `context summarize` — manually trigger summarization of the current context
- `context compress` — manually trigger compression

**Files:** new `src/cli_context.rs` or extend existing CLI module, `main.rs` (match arms)

### 3. Configurable token limits per profile
**Priority: P1**

- Add `compression_threshold`, `min_context_length`, `compression_model` fields to the profile config struct.
- Load from profile TOML/JSON.
- Pass through to `HermesContextCompressor` and `check_compression_model_feasibility`.

**Files:** profile config module, `context_compressor.rs`

### 4. Evidence tracking for summaries
**Priority: P2**

- Track which original messages were summarized and when.
- Store summary metadata (original message IDs, timestamp, token savings) in session state.
- Expose via `chat context` CLI subcommand.

**Files:** `conversation_compression.rs`, session storage module

### 5. Isa/Helo memory integration
**Priority: P2**

- After compression, notify Isa/Helo memory providers so they can persist important context that was dropped.
- Use the existing plugin/context-engine trait pattern (no direct neural access).
- Ensure compressed summaries are available to memory recall.

**Files:** `conversation_compression.rs`, `organism/summarization.rs`, memory provider modules

### 6. Secrets-filtering tests for summaries
**Priority: P2**

- Add tests verifying that LLM-generated summaries do not leak secrets/credentials.
- Test that known secret patterns (API keys, tokens, passwords) in original messages are absent from summaries.
- Add a `filter_secrets_from_summary` pass if the summarizer does not already strip them.

**Files:** new test module or extend `context_summarize.rs` tests

### 7. Integration tests
**Priority: P3**

- End-to-end test: conversation exceeds token threshold -> compression fires -> context is reduced -> conversation continues.
- Test session ID rotation after compression.
- Test image shrinking fallback path.
- Test CLI subcommands produce expected output.

**Files:** `tests/` directory

---

## Dependency graph

```
[1. Wire compression] ──> [2. CLI subcommands]
        │                         │
        ├──> [3. Token limits]    │
        │                         │
        ├──> [4. Evidence tracking] ──> [2. CLI (display)]
        │
        ├──> [5. Memory integration]
        │
        └──> [6. Secrets filtering]
                                  
All ──> [7. Integration tests]
```

## Estimated effort

| Sub-task | Estimate |
|---|---|
| 1. Wire compression | L (3-5 days) |
| 2. CLI subcommands | M (1-2 days) |
| 3. Token limits config | S (0.5-1 day) |
| 4. Evidence tracking | M (1-2 days) |
| 5. Memory integration | M (1-2 days) |
| 6. Secrets filtering | S (0.5-1 day) |
| 7. Integration tests | M (1-2 days) |','docs/issues/1172-plan.md','27b579e741e3a1f5aac36bda9e586d597b7c5dde14ebf392174293d6bc131d97','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1173-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1173-plan.md','doc: Plan: #1173 — [Hermes parity] Superfície fluida de ferramentas','# Plan: #1173 — [Hermes parity] Superfície fluida de ferramentas

## Overview

This epic implements a fluid tool surface for the Simplicio runtime, bringing it to parity with the Hermes agent architecture. The work spans five acceptance criteria, each mapped to a concrete sub-issue below.

## Current State

- `tool_registry.rs`: ToolSpec with name/schema/toolset/class fields exists.
- `tool_guardrails.rs`: Classification for idempotent/mutating tool calls exists.
- `toolsets.py`: Toolset grouping exists.
- `tool_result_classification.py`: Basic result classification exists.

## Sub-issues

### Sub-issue 1: Capability-based tool lookup in agent runner

**Files:** `src/tool_registry.rs`, `agent/tool_dispatch_helpers.py`

Today tools are resolved by exact name. This sub-issue adds a capability tag system to `ToolSpec` (e.g., `capabilities: Vec<String>`) and a `lookup_by_capability(cap: &str) -> Vec<ToolSpec>` function in the registry. The agent runner should prefer capability-based lookup, falling back to name-based lookup for backward compatibility.

**Acceptance criteria:**
- ToolSpec has a `capabilities` field.
- `lookup_by_capability` returns ranked tools matching a capability.
- Agent runner calls capability lookup before name lookup.

---

### Sub-issue 2: Git write gating with clean-state check

**Files:** `src/tool_guardrails.rs`, `agent/tool_guardrails.py`

`ToolClass::Mutating` exists but has no git-specific pre-flight checks. This sub-issue adds a `GitWriteGuard` that, before any mutating file/git tool call:
1. Checks `git status --porcelain` for unexpected dirty state.
2. Acquires a lightweight lock (pid file) to prevent concurrent mutations.
3. Returns `Err` with actionable message if the guard fails.

**Acceptance criteria:**
- Mutating file tools are blocked when working tree has uncommitted changes outside the tool''s target paths.
- A lock file prevents concurrent mutating tool calls.
- Guard failures produce clear, actionable error messages.

---

### Sub-issue 3: Fallback chains for browser and API tools

**Files:** `tools/browser_tool.py`, `src/tool_registry.rs`

Implement explicit fallback chains so that when a primary tool fails (e.g., headless browser times out), the runtime automatically retries with a fallback (e.g., HTTP fetch, then cached snapshot). Configuration lives in `ToolSpec` as `fallback_chain: Vec<String>` (ordered list of tool names).

**Acceptance criteria:**
- `ToolSpec` has a `fallback_chain` field.
- Runtime tries each fallback in order on tool failure.
- Fallback attempts are logged with reason for primary failure.

---

### Sub-issue 4: Lazy skill ranking with on-demand loading

**Files:** `tools/skills_tool.py`, `toolsets.py`

Skills are currently listed eagerly. This sub-issue adds:
1. A ranking function that scores skills by relevance to the current task context.
2. Lazy loading: skill definitions are loaded only when they enter the top-N ranked set.
3. A TTL cache to avoid re-ranking on every tool call.

**Acceptance criteria:**
- Skills are ranked by relevance before being offered to the model.
- Skill definitions are loaded on-demand (not at startup).
- Ranking results are cached with a configurable TTL.

---

### Sub-issue 5: Evidence trail per tool call

**Files:** `agent/tool_result_classification.py`, `src/tool_registry.rs`

Each tool call must produce a structured evidence record containing:
- `safe_command`: sanitized version of the command (secrets redacted).
- `exit_code`: numeric exit code or equivalent status.
- `artifacts`: list of file paths or URIs produced.
- `duration_ms`: wall-clock time of execution.
- `classification`: idempotent | mutating | read-only.

These records are appended to a per-session evidence log.

**Acceptance criteria:**
- Every tool call produces an `EvidenceRecord`.
- Secrets/tokens in commands are redacted.
- Evidence log is queryable by session ID.

---

## Suggested Implementation Order

1. Sub-issue 5 (evidence trail) — foundational, other features benefit from observability.
2. Sub-issue 1 (capability lookup) — enables smarter tool selection for sub-issues 3 and 4.
3. Sub-issue 2 (git write gating) — safety gate, independent of others.
4. Sub-issue 3 (fallback chains) — builds on capability lookup.
5. Sub-issue 4 (lazy skill ranking) — builds on capability lookup and evidence trail.','docs/issues/1173-plan.md','3e2b4b2676b7f10d763e485aa4eeeac42ce7e37c9402ad970a7946d523c4014c','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1176-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1176-evidence.md','doc: Issue #1176 — [Hermes parity] Loop melhoria prompts/skills/routing','# Issue #1176 — [Hermes parity] Loop melhoria prompts/skills/routing

## Status: Already Implemented

All four commands and supporting infrastructure are fully wired and tested.

## Evidence

### 1. CLI commands wired in main.rs

- `src/main.rs:1977` — `learn suggest` dispatches to `hermes_parity_learn_ext::learn_suggest_command`
- `src/main.rs:1979` — `prompts improve` dispatches to `hermes_parity_learn_ext::prompts_improve_command`
- `src/main.rs:1982` — `skills propose` dispatches to `hermes_parity_learn_ext::skills_propose_command`
- `src/main.rs:1985` — `reasoning tune` dispatches to `hermes_parity_learn_ext::reasoning_tune_command`

### 2. Full implementation in hermes_parity_learn_ext.rs

- `src/hermes_parity_learn_ext.rs:138` — `pub fn learn_suggest_command`
- `src/hermes_parity_learn_ext.rs:178` — `pub fn prompts_improve_command`
- `src/hermes_parity_learn_ext.rs:216` — `pub fn skills_propose_command`
- `src/hermes_parity_learn_ext.rs:257` — `pub fn reasoning_tune_command`
- `src/hermes_parity_learn_ext.rs:105` — `pub(crate) fn build_suggestions` (shared builder)

### 3. Self-improvement pipeline (self_improvement.rs)

- `src/self_improvement.rs:20` — `pub struct RunOutcome` (history record)
- `src/self_improvement.rs:38` — `pub struct SkillProposal` (occurrence-based promotion)
- `src/self_improvement.rs:108` — `pub fn propose_skills` (mines RunOutcome history)
- Tests at line 146+ verify the full proposal flow.

### 4. Darwinian evolutionary prompt loop (skill_darwinian.rs)

- `src/skill_darwinian.rs:2` — Module docstring: "Darwinian evolutionary-prompt loop"
- `src/skill_darwinian.rs:174` — `pub fn evaluate_with` (organism evaluation)
- `src/skill_darwinian.rs:221` — `pub fn improvement_prompt` (mutation prompt generation)
- `src/skill_darwinian.rs:241` — `pub fn extract_mutation` (mutation extraction)
- `src/skill_darwinian.rs:401` — `pub fn evolve_with` (full evolutionary loop)

### 5. Evidence pipeline and approval gates

- `src/main.rs:5506` — `learning_suggestion_json` writes learn-suggestion.json artifacts
- `src/main.rs:5533` — `run.write_artifact("learn-suggestion.json", ...)` persists artifacts
- `src/main.rs:5580` — `pending_inputs_from_learn_suggestion_json` processes suggestions
- `src/main.rs:20498` — `gate_required: bool` field enforces approval gates
- `src/main.rs:39122` — `fn pending_inputs_from_learn_suggestion_json` test helper

### 6. Tests

- `src/main.rs:41996` — Integration test using `hermes_parity_learn_ext::build_suggestions`
- `src/hermes_parity_learn_ext.rs:486` — Unit test for `build_suggestions`
- `src/self_improvement.rs:146` — Unit tests for `propose_skills` with `RunOutcome` fixtures','docs/issues/1176-evidence.md','ae43b35a77d5b71b6fc4bc8b06a3ad0e9e38fae9447ab7326f271b4180e2f0d6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1177-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1177-evidence.md','doc: Issue #1177 — Evidence: already implemented','# Issue #1177 — Evidence: already implemented

## Summary

All acceptance criteria for "[Hermes parity] Benchmark Simplicio x Hermes x others" are implemented.

## Evidence

### Module wired into main.rs

- `src/main.rs:186` — `mod hermes_parity_benchmark_agents;`
- `src/main.rs:1991-1995` — CLI subcommand match arm dispatching `benchmark agents`

### Core implementation: `src/hermes_parity_benchmark_agents.rs` (818 lines)

- **Line 2-12**: Module doc — `simplicio benchmark agents --sample --json [--competitor ...]`
- **Line 19**: Schema constant `simplicio.benchmark-agents/v1`
- **Lines 35-55**: All 10 required metrics in `BenchMetrics`:
  - `time_to_green_ms` (L35)
  - `command_count` (L37)
  - `estimated_cost_usd` (L39)
  - `local_tokens` (L41)
  - `remote_tokens` (L43)
  - `recovered_failures` (L45)
  - `diff_quality` (L47)
  - `evidence_generated` (L49)
  - `completion_rate` (L53)
  - `regressions_introduced` (L55)
- **Noop/fake competitor**: always available, no external credentials needed
- **Optional plugins**: Hermes/OpenClaw/Codex/Claude detected on PATH, skipped with clear reason when absent
- **Temp-dir fixture repo**: never mutates the main repo

### Supporting infrastructure

- `src/benchmark_harness.rs` — 3-way benchmark harness
- `src/benchmark_suite.rs` — generic benchmark suite
- `scripts/benchmark-coding-3way.sh` — shell script for 3-way comparison
- `scripts/benchmark-simplicio-vs-hermes.sh` — shell script for Simplicio vs Hermes

### Integration points

- `src/main.rs:26153` — `resolve_binary_pub` used for binary resolution
- `src/main.rs:42016` — `detect_competitors()` called for competitor detection
- `src/main.rs:42036` — `"benchmark-agents"` registered
- `src/main.rs:85028` — test assertion for `benchmark_agents`','docs/issues/1177-evidence.md','bc223b171a46691d149406813d4d7dcb5dda4026f9ed12840cb550baed988023','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1181-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1181-plan.md','doc: Plan: #1181 — [Hermes parity] host-hermes-pack','# Plan: #1181 — [Hermes parity] host-hermes-pack

## Overview

This epic adds full Hermes metadata parsing, capability indexing, and CLI commands
to import and rank Hermes-originated capabilities within simplicio-runtime.

Currently `host-hermes-pack` is listed as "disabled" in the capability registry and
`hermes_import.rs` only handles session/state data migration — none of the requested
functionality exists.

---

## Sub-tasks

### 1. Hermes metadata parser (`src/hermes_metadata.rs`)

- Parse real Hermes metadata: model metadata, token estimator, pricing tables,
  provider prefixes, streaming event schemas, skill metadata, prompt patterns,
  and repair loop patterns.
- Input: a Hermes clone directory (or path to extracted pack).
- Output: structured `HermesMetadata` with all parsed fields.
- Use `serde` + `serde_json` for deserialization; no `.unwrap()` in production.
- Include a secrets filter that strips API keys, tokens, and credentials from
  parsed metadata before indexing.

### 2. Governed index in `.simplicio-loop/` (`src/hermes_index.rs`)

- Persist an index file at `~/.simplicio-loop/hermes-index.json` tracking imported
  Hermes capabilities with provenance (clone path, git commit SHA, import timestamp).
- Support incremental updates (re-import only changed capabilities).
- Schema: `{ version, entries: [{ id, source_path, commit, imported_at, metadata_hash }] }`.

### 3. CLI commands (`src/hermes_parity_capabilities_ext.rs` + CLI wiring)

Three new commands:

| Command | Description |
|---------|-------------|
| `hermes import --metadata-only` | Parse and index Hermes metadata without importing sessions/state. |
| `skills rank --source hermes` | Rank indexed skills by relevance, filtering to Hermes-originated ones. |
| `capabilities import-hermes --dry-run` | Preview what would be imported without writing to the index. |

- Wire into `main.rs` arg parsing and `tool_registry.rs` match arms.
- Each command prints JSON output to stdout.

### 4. Helo integration (`src/hermes_helo_bridge.rs`)

- After indexing, notify Helo (if available) to register the new capabilities.
- Use the existing Helo bridge pattern (HTTP POST to local Helo endpoint).
- Graceful degradation if Helo is not running.

### 5. Test fixtures and integration tests

- Create `tests/fixtures/mini-hermes-clone/` simulating a minimal Hermes repo
  structure with sample metadata files.
- Integration tests for:
  - Metadata parsing (valid and malformed input).
  - Index creation and incremental update.
  - Secrets filtering (ensure no keys leak into index).
  - CLI command output format.
  - Dry-run mode (no side effects).

---

## Dependency order

```
[1] Hermes metadata parser
 |
 v
[2] Governed index -----> [4] Helo integration
 |
 v
[3] CLI commands
 |
 v
[5] Test fixtures & integration tests
```

Sub-tasks 1 and 2 can be developed in parallel once interfaces are agreed.
Sub-task 3 depends on both 1 and 2. Sub-task 4 depends on 2.
Sub-task 5 can be built incrementally alongside each sub-task.

## Files to create/modify

- **New:** `src/hermes_metadata.rs`, `src/hermes_index.rs`, `src/hermes_helo_bridge.rs`
- **Modify:** `src/hermes_parity_capabilities_ext.rs`, `src/hermes_import.rs`, `src/main.rs`, `src/tool_registry.rs`
- **New:** `tests/fixtures/mini-hermes-clone/` (sample metadata files)
- **New:** `tests/hermes_parity_test.rs`','docs/issues/1181-plan.md','2855712313ee33bb7cc5459cd02013f48a332ea338490ebd7d8f22a687d286c9','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1184-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1184-evidence.md','doc: Issue #1184 — [Hermes parity] run --until-green','# Issue #1184 — [Hermes parity] run --until-green

## Status: Already Implemented

## Evidence

### Core loop: `run_until_green()`
- **File:** `src/hermes_parity_run_loop.rs`
- **Line 72:** `pub fn run_until_green(...)` — observe/plan/act/repair loop with stop conditions (green, max_cycles_reached)
- **Line 30:** `RunUntilGreenResult` struct with JSON output and evidence fields

### CLI wiring: `--until-green` flag
- **File:** `src/main.rs`
- **Line 1799-1849:** `run` subcommand checks for `--until-green` flag and delegates to `hermes_parity_run_loop::run_until_green`
- **Line 9023:** `agent loop --repair` / `--until-green` also wired

### Tests
- **File:** `src/hermes_parity_run_loop.rs`
- **Line 264:** `run_until_green_trivial_cmds` — trivial-green scenario
- **Line 273:** `run_until_green_always_fails_hits_max` — always-fails-hits-max scenario','docs/issues/1184-evidence.md','d756f1a227f80a7510557754ed7b9fa22b0b0be5852b1e13b73c40b7f19c02a2','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1186-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1186-plan.md','doc: Epic #1186: Growth Autopilot — Decomposition Plan','# Epic #1186: Growth Autopilot — Decomposition Plan

## Overview

Growth Autopilot is a full SaaS sales automation pipeline covering intake, strategy, funnel building, creative generation, distribution, measurement, learning, and iteration. It is decomposed into 26 child issues (#1187–#1212), each representing a self-contained module.

## Child Issues

| # | Title | Category | Dependencies |
|---|-------|----------|--------------|
| 1187 | Lead Intake Agent | Intake | — |
| 1188 | ICP Scoring Engine | Intake | #1187 |
| 1189 | Market Intelligence Collector | Strategy | — |
| 1190 | Strategy Planner Agent | Strategy | #1188, #1189 |
| 1191 | Funnel Blueprint Generator | Funnel | #1190 |
| 1192 | Landing Page Builder Agent | Funnel | #1191 |
| 1193 | Email Sequence Generator | Funnel | #1191 |
| 1194 | Ad Copy Generator | Creative | #1190 |
| 1195 | Image/Banner Creative Agent | Creative | #1194 |
| 1196 | Video Script Generator | Creative | #1194 |
| 1197 | A/B Variant Factory | Creative | #1194, #1195, #1196 |
| 1198 | Social Media Distributor | Distribution | #1195, #1196 |
| 1199 | Email Campaign Dispatcher | Distribution | #1193 |
| 1200 | Ad Platform Connector | Distribution | #1194, #1195 |
| 1201 | SEO Content Pipeline | Distribution | #1190 |
| 1202 | Analytics Collector Agent | Measurement | #1198, #1199, #1200 |
| 1203 | Conversion Tracker | Measurement | #1202 |
| 1204 | Attribution Model Engine | Measurement | #1203 |
| 1205 | Dashboard Builder Agent | Measurement | #1202, #1203, #1204 |
| 1206 | Performance Anomaly Detector | Learning | #1202 |
| 1207 | Budget Optimizer Agent | Learning | #1204, #1206 |
| 1208 | Audience Segment Refiner | Learning | #1203, #1206 |
| 1209 | Creative Performance Ranker | Learning | #1197, #1202 |
| 1210 | Iteration Planner Agent | Iteration | #1207, #1208, #1209 |
| 1211 | Campaign Lifecycle Manager | Iteration | #1210 |
| 1212 | Growth Report Generator | Iteration | #1205, #1211 |

## Implementation Phases

### Phase 1 — Foundation (Issues #1187–#1190)
Intake pipeline and strategy engine. No external distribution yet. Sets up lead scoring, ICP matching, market data collection, and strategic planning.

### Phase 2 — Funnel & Creative (Issues #1191–#1197)
Funnel blueprint generation, landing pages, email sequences, ad copy, image/banner creation, video scripts, and A/B variant factory.

### Phase 3 — Distribution (Issues #1198–#1201)
Social media distribution, email campaign dispatch, ad platform connectors, and SEO content pipeline.

### Phase 4 — Measurement (Issues #1202–#1205)
Analytics collection, conversion tracking, attribution modeling, and dashboard building.

### Phase 5 — Learning & Iteration (Issues #1206–#1212)
Anomaly detection, budget optimization, audience refinement, creative ranking, iteration planning, campaign lifecycle management, and growth reporting.

## Architecture Notes

- Each agent is a standalone Rust module (`src/htool_growth_*.rs`) registered via `tool_registry.rs`.
- Agents communicate through the neural DB (namespaced per module).
- Cron jobs handle periodic tasks (data collection, report generation, budget reallocation).
- All modules use `std + serde + serde_json` only; no `.unwrap()` in production code.

## Recommended Execution Order

Implement child issues sequentially by phase. Each issue should pass `cargo check` independently before moving to the next.','docs/issues/1186-plan.md','f7c20bd800c236fe78dfa6498a4459338d76c3eb9680546dfd377fd92df0726d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1187-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1187-plan.md','doc: Epic #1187 — Growth Autopilot Command — Decomposition Plan','# Epic #1187 — Growth Autopilot Command — Decomposition Plan

## Current State

`src/growth_autopilot.rs` handles fixed subcommands: `e2e-sandbox`, `daemon`, `landing`, `checkout`, `portal`, `funnel`. None of the capabilities required by #1187 exist today.

---

## Sub-issues

### 1. Free-text intake and prompt normalization
**Files:** `src/growth_autopilot.rs`, `schemas/growth-run.schema.json`
- Add a catch-all arm in `growth_command` that accepts free-text (no recognized subcommand).
- Parse free-text into a `GrowthRunV1` struct matching `growth-run/v1` schema.
- Validate against `schemas/growth-run.schema.json` (create schema if missing).
- If fields are missing, trigger clarification flow (sub-issue 3).

### 2. Six new subcommands: plan / run / status / approve / pause / resume / report
**Files:** `src/growth_autopilot.rs`, `src/growth_run_engine.rs` (new)
- `plan <run-id|text>` — generate a task graph from a GrowthRunV1, persist to neural DB.
- `run <run-id>` — execute the task graph (kicks off multi-agent orchestration).
- `status <run-id>` — show current state of all tasks in the run.
- `approve <run-id> [--task <id>]` — advance past an approval gate.
- `pause <run-id>` / `resume <run-id>` — pause/resume execution.
- `report <run-id>` — generate a summary report with evidence references.
- Add match arms in `growth_command`; delegate to `growth_run_engine`.

### 3. Clarification flow for missing fields
**Files:** `src/growth_clarify.rs` (new)
- When free-text normalization leaves required fields empty, emit structured questions.
- Support `--json` output for programmatic consumers.
- Re-validate after answers are provided; loop until GrowthRunV1 is complete.

### 4. Neural DB namespaces: growth_runs / tasks / assumptions / constraints
**Files:** `src/growth_neuraldb.rs` (new)
- Four namespaces with CRUD operations backed by serde_json file storage.
- `growth_runs` — top-level run metadata (id, status, schema version, timestamps).
- `tasks` — individual tasks within a run (id, run_id, agent, status, deps).
- `assumptions` — assumptions extracted from the prompt or clarification.
- `constraints` — hard constraints (budget, timeline, tech stack, compliance).
- Index by run_id; support listing, filtering by status.

### 5. Multi-agent orchestration with lease/handoff
**Files:** `src/growth_orchestrator.rs` (new)
- Define 4 agent roles: Strategist, Builder, Analyst, Reviewer.
- Lease system: agent acquires a task lease (with TTL), performs work, releases.
- Handoff protocol: agent marks task done, orchestrator assigns next eligible task to next agent.
- Respect task graph dependencies (topological order).
- Persist lease state in `tasks` namespace.

### 6. Approval gates with preview / dry-run / rollback
**Files:** `src/growth_approval.rs` (new)
- Before executing a task marked `requires_approval`, pause and emit a preview.
- `--dry-run` flag simulates execution without side effects.
- On approval failure or explicit rollback, revert completed tasks in reverse order.
- Integrate with `approve` subcommand from sub-issue 2.

### 7. Evidence ledger integration
**Files:** `src/growth_evidence.rs` (new)
- Each agent action appends an entry to an append-only evidence ledger (JSONL).
- Entry: `{ timestamp, run_id, task_id, agent, action, input_hash, output_hash, verdict }`.
- `report` subcommand reads the ledger to produce summaries.
- Integrate with existing evidence infrastructure if available.

### 8. Task graph generation
**Files:** `src/growth_taskgraph.rs` (new)
- Given a `GrowthRunV1`, generate a DAG of tasks with dependencies.
- Each node: task_id, agent assignment, estimated duration, approval_required flag.
- Serialize to `tasks` namespace in neural DB.
- Support visualization via `--json` (adjacency list format).

---

## Dependency Order

```
[1] Free-text intake + schema
 └─► [3] Clarification flow
      └─► [4] Neural DB namespaces
           ├─► [8] Task graph generation
           │    └─► [5] Multi-agent orchestration
           │         └─► [6] Approval gates
           │              └─► [7] Evidence ledger
           └─► [2] Subcommands (iterative, wired up as each piece lands)
```

## Estimated Effort

| Sub-issue | Effort |
|-----------|--------|
| 1. Free-text intake | M |
| 2. Six subcommands | L (shell wiring) |
| 3. Clarification flow | S |
| 4. Neural DB namespaces | M |
| 5. Multi-agent orchestrator | L |
| 6. Approval gates | M |
| 7. Evidence ledger | S |
| 8. Task graph generation | M |

S = small (< 1 day), M = medium (1-2 days), L = large (3+ days)','docs/issues/1187-plan.md','1f622a50dfb0de9ed65926abcfdc4379a911697ed552067876298a95edd6111d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1188-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1188-plan.md','doc: Issue #1188 — Growth Neural Memory: Epic Decomposition Plan','# Issue #1188 — Growth Neural Memory: Epic Decomposition Plan

## Overview

The growth neural memory layer adds 7 namespaces on top of the existing neural memory infrastructure (SQLite FTS5, Isa/Helo concepts, retrieval). It requires new DB tables, 3 agent implementations, cron integration, PII approval gates, and an evidence ledger.

Schema reference: `schemas/growth-neural-memory.schema.json`

---

## Sub-Issues

### 1. Growth DB Tables & Namespace Registry
**Scope:** Create SQLite tables for all 7 growth namespaces (`growth_profiles`, `growth_assets`, `growth_experiments`, `growth_leads`, `growth_revenue_events`, `growth_lessons`, `growth_blacklist`). Register them in the namespace registry so existing FTS5 retrieval can query them.

**Files:** `src/main.rs` (migrations), new `src/growth_db.rs`
**Acceptance:** `cargo test` passes; tables created on init; namespace list includes all 7.

---

### 2. Growth Artifact Read/Write Contract
**Scope:** Implement the CRUD contract for growth artifacts — typed read/write/list/delete across all 7 namespaces. Enforce schema validation against `growth-neural-memory.schema.json` on write.

**Files:** new `src/htool_growth_memory.rs`, `src/tool_registry.rs` (match arms)
**Acceptance:** Tools `growth_memory_read`, `growth_memory_write`, `growth_memory_list`, `growth_memory_delete` registered and functional.

---

### 3. Isa-Memory-Agent Implementation
**Scope:** Agent that curates `growth_profiles` and `growth_leads` — enriches profiles with context from conversations, deduplicates leads, maintains freshness scores. Uses lease/handoff pattern.

**Files:** new `src/agents/isa_memory_agent.rs`
**Acceptance:** Agent can be spawned, acquires lease, processes profile/lead queue, hands off cleanly.

---

### 4. Helo-Schema-Agent Implementation
**Scope:** Agent that validates and evolves the growth schema — detects schema drift, proposes migrations, enforces backward compatibility for `growth_experiments` and `growth_revenue_events`.

**Files:** new `src/agents/helo_schema_agent.rs`
**Acceptance:** Agent detects schema changes, logs migration proposals, blocks incompatible writes.

---

### 5. Learning-Curator-Agent Implementation
**Scope:** Agent that manages `growth_lessons` and `growth_assets` — extracts lessons from completed experiments, links assets to outcomes, prunes stale entries. Uses lease/handoff.

**Files:** new `src/agents/learning_curator_agent.rs`
**Acceptance:** Agent processes experiment completions, creates lesson entries, links assets.

---

### 6. Cron/Scheduler for Growth Memory Compaction
**Scope:** Integrate cron jobs for periodic compaction — merge duplicate profiles, archive old experiments, compact FTS5 indexes for growth namespaces, enforce retention policies on `growth_blacklist`.

**Files:** `src/main.rs` (scheduler init), new `src/growth_compaction.rs`
**Acceptance:** Compaction runs on schedule; logs compaction stats; no data loss on active records.

---

### 7. PII Approval Gates & Evidence Ledger
**Scope:** Add approval gates before writing PII-containing data to `growth_profiles` and `growth_leads`. Implement evidence ledger that logs every PII access/write with timestamp, actor, and justification. Support audit queries.

**Files:** new `src/growth_pii_gate.rs`, new `src/growth_evidence_ledger.rs`
**Acceptance:** PII writes blocked without approval; ledger entries queryable; audit trail complete.

---

## Dependency Order

```
1. Growth DB Tables & Namespace Registry
   └─► 2. Growth Artifact Read/Write Contract
        ├─► 3. Isa-Memory-Agent
        ├─► 4. Helo-Schema-Agent
        └─► 5. Learning-Curator-Agent
   └─► 7. PII Approval Gates & Evidence Ledger
        └─► 6. Cron/Scheduler (depends on all above)
```

## Constraints

- **std + serde + serde_json only** — no additional crate dependencies.
- **No `.unwrap()` in production** — all errors propagated via `Result`.
- Each sub-issue should be a separate PR for reviewability.','docs/issues/1188-plan.md','6535a37522be05376b8884cd494406504c9989fe56e17f47e33de2faae5522fd','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1190-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1190-plan.md','doc: Plan: #1190 — Offer and Pricing Builder','# Plan: #1190 — Offer and Pricing Builder

## Context

The `growth-offer.schema.json` schema already exists, covering offer records
with price, billing model, promise, approval gates, and provenance. However,
there is no runtime code implementing the full offer-and-pricing lifecycle:
no pricing experiments, no Stripe integration, no dedicated agents, no cron
review, and no neural memory namespaces for pricing data.

## Sub-issues

### 1. Runtime command/API surface + dry-run (`#1190-1`)
- Add `simplicio offer` command surface: `offer create`, `offer list`,
  `offer update`, `offer archive`, `offer dry-run`.
- Implement `src/htool_offer.rs` with CRUD backed by `growth-offer.schema.json`.
- Validate all inputs against the schema; `dry-run` returns the would-be offer
  without persisting.
- Wire into `tool_registry.rs` and `main.rs`.

### 2. Pricing experiments module (`#1190-2`)
- New schema `schemas/growth-pricing-experiment.schema.json` for A/B price
  tests (variant, control, metric, duration, status).
- Implement `src/htool_pricing_experiment.rs`: `pricing-experiment create`,
  `start`, `stop`, `evaluate`.
- Evaluation computes lift/significance from recorded revenue events
  (`growth-revenue-event.schema.json`).

### 3. Stripe Billing integration (`#1190-3`)
- New module `src/stripe_billing.rs`: create/update Stripe Products, Prices,
  and Checkout Sessions via the Stripe REST API (HTTP client, no SDK).
- Map `growth-offer` fields (price, currency, billing_model) to Stripe
  objects.
- Gated by Action Gate (`action_gate_decide`) — all Stripe mutations require
  approval unless `approval_required: false` on the offer.
- Environment: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.

### 4. Neural memory namespaces (`#1190-4`)
- Create namespaces in `.simplicio-loop/memory/`: `offer-history`,
  `pricing-decisions`, `objection-patterns`, `checkout-analytics`.
- Integrate with `memory_v2` for semantic recall of prior pricing decisions.
- Auto-store every offer create/update/archive event with provenance.

### 5. Agent lease/handoff for 5 agents (`#1190-5`)
- Define agent roles: `offer-agent`, `pricing-agent`, `stripe-agent`,
  `copy-chief-agent`, `risk-reviewer-agent`.
- Implement agent configs in the sub-agent fabric (async-runtime).
- Handoff protocol: `offer-agent` orchestrates; delegates to `pricing-agent`
  for experiment design, `stripe-agent` for billing sync, `copy-chief-agent`
  for offer copy review, `risk-reviewer-agent` for risk/compliance check.
- Each agent has a lease (max duration, max tokens) and reports evidence to
  the HBP ledger.

### 6. Cron scheduler for pricing review (`#1190-6`)
- Add a `pricing-review` cron job to the `scheduler` module.
- Runs daily (configurable): evaluates active experiments, flags stale offers,
  alerts on revenue anomalies.
- Integrates with the daemon mode (`growth-daemon-mode.schema.json`).

### 7. Approval gates (`#1190-7`)
- Extend the existing Action Gate for offer-specific policies:
  `price_change > 20%` requires manual approval, `new_billing_model` requires
  risk review, `stripe_live_mode` requires explicit confirmation.
- Gate decisions recorded in the evidence ledger with provenance.

### 8. Tests and evidence ledger (`#1190-8`)
- Unit tests for `htool_offer.rs`, `htool_pricing_experiment.rs`,
  `stripe_billing.rs`.
- Integration tests for the agent handoff flow (mock Stripe).
- Evidence ledger entries for all offer lifecycle events, priced via the
  token economy.
- `cargo test` must pass for all new modules.

## Dependency order

```
#1190-1 (command surface)
   |
   +---> #1190-2 (pricing experiments)
   |        |
   |        +---> #1190-6 (cron review)
   |
   +---> #1190-4 (neural memory)
   |
   +---> #1190-3 (Stripe integration)
   |        |
   |        +---> #1190-7 (approval gates)
   |
   +---> #1190-5 (agents)
   |
   +---> #1190-8 (tests) [after all above]
```

## Estimated effort

| Sub-issue | Size | Notes |
|-----------|------|-------|
| #1190-1 | M | Schema exists; CRUD + CLI wiring |
| #1190-2 | M | New schema + experiment logic |
| #1190-3 | L | HTTP client for Stripe, gated |
| #1190-4 | S | Namespace creation + memory hooks |
| #1190-5 | L | 5 agents, handoff protocol |
| #1190-6 | S | Cron config + evaluation trigger |
| #1190-7 | S | Policy rules on existing gate |
| #1190-8 | M | Tests across all modules |','docs/issues/1190-plan.md','6ee3bec775723284e579fe0453c19b25c623bf19d10b61120030400827ff1511','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1191-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1191-plan.md','doc: Epic Plan: #1191 — Stripe Revenue Funnel','# Epic Plan: #1191 — Stripe Revenue Funnel

## Current State

`growth_stripe.rs` already implements:
- Checkout Sessions (one-time + subscription)
- Customer Portal
- `stripe-funnel` end-to-end command
- Find/create customer
- Attribution JSONL logging
- Dry-run support and tests

## Sub-Issues

### 1. Webhook Handler (`stripe-webhook-handler`)
**Files:** `src/growth_stripe.rs`, `site/api/stripe-webhook.php`

- Handle events: `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `payment_intent.succeeded`, `payment_intent.payment_failed`, `subscription.created`, `subscription.updated`, `subscription.deleted`
- Signature verification via `Stripe-Signature` header (HMAC-SHA256)
- Idempotency: deduplicate by event ID using neural DB `stripe_events` namespace
- Structured receipt logging to `.simplicio-loop/runs/`
- Error handling: return 200 on success, 400 on bad signature, 500 on processing failure (no `.unwrap()`)

### 2. Neural DB Schemas (`stripe-neural-schemas`)
**Files:** `schemas/stripe-customers.schema.json`, `schemas/stripe-sessions.schema.json`, `schemas/stripe-events.schema.json`, `schemas/revenue-attribution.schema.json`, `schemas/subscription-status.schema.json`

Namespace schemas:
- `stripe_customers`: customer_id, email, name, created_at, metadata
- `stripe_sessions`: session_id, customer_id, mode, status, amount, currency, created_at
- `stripe_events`: event_id, type, processed_at, idempotency_key, payload_hash
- `revenue_attribution`: session_id, source, medium, campaign, revenue, currency, timestamp
- `subscription_status`: subscription_id, customer_id, plan, status, current_period_start, current_period_end, cancel_at

### 3. Cron/Scheduler for Reconciliation (`stripe-cron`)
**Files:** `src/growth_autopilot.rs`, `src/growth_stripe.rs`

- Hourly: webhook reconciliation — compare Stripe API list of recent events against `stripe_events` namespace, flag/process any missed events
- Daily: revenue attribution report — aggregate revenue by source/campaign, write summary to `.simplicio-loop/runs/daily-revenue-YYYY-MM-DD.json`
- Integration with existing autopilot scheduler

### 4. Agent Lease/Handoff Integration (`stripe-agent-leases`)
**Files:** `src/growth_stripe.rs`, `src/growth_autopilot.rs`

Required agents (5):
1. **stripe-checkout-agent** — creates checkout sessions, monitors completion
2. **stripe-webhook-agent** — processes incoming webhook events
3. **stripe-reconciliation-agent** — runs hourly reconciliation
4. **stripe-attribution-agent** — computes daily attribution reports
5. **stripe-portal-agent** — manages customer portal sessions and subscription changes

Each agent needs:
- Lease acquisition/release via existing lease system
- Handoff protocol between agents (e.g., checkout-agent hands off to webhook-agent on session completion)
- Timeout and retry logic

### 5. Approval Gates (`stripe-approval-gates`)
**Files:** `src/growth_stripe.rs`

Gates requiring human approval before execution:
- Switching from test mode to live mode
- Creating or modifying prices/products
- Processing refunds
- Canceling subscriptions
- Any operation above a configurable monetary threshold

Implementation: integrate with existing `.simplicio-loop` approval gate system, log gate decisions to evidence ledger.

### 6. Evidence Ledger and Structured Receipts (`stripe-evidence-ledger`)
**Files:** `src/growth_stripe.rs`

- Write structured JSON receipts to `.simplicio-loop/runs/` for every Stripe operation
- Receipt format: `{ operation, timestamp, agent, input_hash, output_hash, stripe_ids, approval_gate, dry_run }`
- Index file at `.simplicio-loop/runs/stripe-ledger-index.jsonl`
- Retention policy configuration

### 7. Integration/Smoke Tests (`stripe-integration-tests`)
**Files:** `tests/stripe_integration.rs`

- Tests beyond dry-run using Stripe test mode API keys
- End-to-end: create customer, create checkout session, simulate webhook, verify DB state
- Reconciliation test: inject missed event, verify cron catches it
- Approval gate test: verify gate blocks live-mode operations
- Agent lease test: verify handoff between checkout and webhook agents

### 8. Documentation (`stripe-docs`)
**Files:** `docs/stripe-revenue-funnel.md`

- Setup guide (API keys, webhook endpoint configuration)
- Architecture overview with data flow diagram
- Agent responsibilities and handoff protocol
- Approval gate configuration
- Troubleshooting guide
- Revenue attribution report format

## Suggested Implementation Order

1. Neural DB Schemas (foundation for everything else)
2. Webhook Handler (core event processing)
3. Evidence Ledger (needed by all subsequent work)
4. Approval Gates (safety before live operations)
5. Agent Lease/Handoff Integration
6. Cron/Scheduler
7. Integration Tests
8. Documentation','docs/issues/1191-plan.md','b94f64029d88b7c104294f4e28ba8e2b1b93d5f59db34d6a4c0407e637e0c838','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1193-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1193-plan.md','doc: Epic #1193: Growth Analytics and Evidence Ledger — Decomposition Plan','# Epic #1193: Growth Analytics and Evidence Ledger — Decomposition Plan

Parent epic: #1186

## Overview

This epic implements a full growth-analytics pipeline with append-only event ingestion,
multi-source integration, funnel reporting, and evidence ledger traceability. It requires
decomposition into the following sub-issues.

---

## Sub-issues

### 1. Schema definition and neural DB namespaces
- Create `schemas/growth-analytics-ledger.schema.json` with event envelope, attribution, funnel stage enums
- Define 7 neural DB namespaces: `growth_events`, `attribution_map`, `funnel_stages`, `campaign_metadata`, `evidence_chain`, `agent_leases`, `approval_gates`
- Wire namespace registration in `src/main.rs`

### 2. Append-only event ingestion with idempotency
- New file: `src/htool_growth_ingest.rs`
- Implement `growth_ingest` tool: accepts event payload, deduplicates by event_id hash, appends to `growth_events` namespace
- Idempotency via SHA-256 of (source + event_id + timestamp) stored in a dedup index
- No `.unwrap()` — all errors return structured `ToolError`

### 3. Stripe integration events
- New file: `src/htool_growth_stripe.rs`
- Implement `growth_stripe_sync` tool: polls Stripe webhook payloads (checkout.session.completed, subscription events, invoice.paid)
- Maps Stripe metadata to growth event schema
- Writes to `growth_events` with source=stripe

### 4. Social and outbound event integration
- New file: `src/htool_growth_social.rs`
- Implement `growth_social_ingest` tool: accepts social platform events (shares, clicks, impressions)
- Implement `growth_outbound_ingest` tool: accepts outbound campaign events (email opens, link clicks)
- Both write to `growth_events` with appropriate source tags

### 5. UTM and campaign attribution joining
- New file: `src/htool_growth_attribution.rs`
- Implement `growth_attribute` tool: joins events by session_id/user_id with UTM parameters
- Reads from `growth_events`, writes attribution records to `attribution_map`
- Supports first-touch, last-touch, and linear attribution models

### 6. Funnel report generation
- New file: `src/htool_growth_funnel.rs`
- Implement `growth_funnel_report` tool: aggregates events by funnel stage (awareness, acquisition, activation, revenue, retention, referral)
- Reads from `growth_events` + `attribution_map`
- Outputs JSON report with stage counts, conversion rates, time-in-stage

### 7. Dedicated agents with lease/handoff (4 agents)
- New file: `src/htool_growth_agents.rs`
- Agent definitions: `ingest_agent`, `attribution_agent`, `reporting_agent`, `cleanup_agent`
- Lease protocol: acquire lease in `agent_leases` namespace with TTL, heartbeat, release
- Handoff: structured message passing between agents via `evidence_chain` namespace

### 8. Cron schedules (3 schedules)
- Register 3 cron entries:
  - `growth_hourly_ingest`: hourly event pull from external sources
  - `growth_daily_attribution`: daily attribution join pass
  - `growth_weekly_report`: weekly funnel report generation and archival
- Wire in `src/main.rs` cron registration

### 9. Approval and safety gates
- New file: `src/htool_growth_gates.rs`
- Implement `growth_gate_check` tool: validates events against safety rules before ingestion
- Rules: rate limiting per source, schema validation, anomaly detection (spike > 3 sigma)
- Records gate decisions in `approval_gates` namespace

### 10. PII minimization
- Implement PII scrubbing in the ingestion pipeline
- Hash email/phone/IP before storage using SHA-256 + salt
- Strip PII fields from funnel reports
- Configurable allowlist of fields that bypass scrubbing

### 11. Evidence ledger integration
- Extend existing evidence ledger to record all growth analytics decisions
- Each ingestion, attribution join, gate decision, and report generation creates an evidence entry
- Evidence entries are append-only with cryptographic chaining (each entry references hash of previous)
- Query tool: `growth_evidence_query` for audit trail retrieval

---

## Dependency order

```
[1] Schema + namespaces
 |
 v
[2] Event ingestion + idempotency
 |
 +---> [3] Stripe integration
 +---> [4] Social/outbound integration
 |
 v
[5] Attribution joining
 |
 v
[6] Funnel reporting
 |
 v
[7] Agent lease/handoff
 |
 v
[8] Cron schedules
```

Items [9] (gates), [10] (PII), and [11] (evidence ledger) are cross-cutting and should be
implemented alongside items [2]-[6] as each subsystem is built.

## Estimated effort

11 sub-issues, each implementable as a single PR. Expected total: ~15-20 files, ~3000-4000 lines of Rust.','docs/issues/1193-plan.md','3fec2ee5ff7dc82fb730459a31f60bc293fd8515d2ef14409b5b4e919774a6f7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1194-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1194-evidence.md','doc: Issue #1194 — Creative Factory: Evidence of Implementation','# Issue #1194 — Creative Factory: Evidence of Implementation

## Status: Already Implemented

## Core module

- **`src/growth_creative_factory.rs`** (850 lines)
  - Brand kit generation: `brand_kit_json()` at line 73
  - Creative spec/prompt generation (static ads, carousels, thumbnails): `CreativeSpec` struct at line 11
  - Compliance review via `assess_asset_rights`: line 1 (import), line 246 (call)
  - Approval gates (required/approved/denied/blocked): lines 233-254, CLI flag at line 386
  - Dry-run support: `--dry-run` / `--render` flags at lines 371-373
  - Evidence ledger / provenance: `--evidence-path` flag at line 329
  - Neural memory namespace mapping (`brand_kit`, `creative_assets`, `creative_prompts`, `asset_performance`, `usage_rights`): verified in test at lines 788-801
  - Artifact manifest writing and human-readable report: `--report-path` flag at line 329

## Wiring in main.rs

- **`src/main.rs`**
  - Module declaration: line 165 (`mod growth_creative_factory;`)
  - Command match arm: lines 2213-2214 (`"growth-creative" | "creative-factory" | "growth-creative-factory"`)

## Tests

- **`src/growth_creative_factory.rs`**, lines 758-849:
  1. `creative_factory_builds_brand_kit_and_manifest` (line 763): generates ad variants with brand kit, 3 creative assets, and memory namespace map
  2. `approved_dry_run_marks_manifest_approved_and_keeps_render_skipped` (line 805): approved dry-run keeps render skipped
  3. `fake_testimonial_copy_gets_blocked` (line 833): blocks fake testimonials via `assess_asset_rights`

## Schema

- Schema constant: `CREATIVE_FACTORY_SCHEMA = "simplicio.growth-creative-factory/v1"` (line 8)','docs/issues/1194-evidence.md','6eac7879b225d09cc2beb9e27dcd8b7bae0e80d03e6f02001c7cf3933221bbcd','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1195-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1195-plan.md','doc: Epic #1195 — Video Factory: Decomposition Plan','# Epic #1195 — Video Factory: Decomposition Plan

Parent epic: #1186

## Overview

The Video Factory epic connects the existing `video_pipeline.rs` (script, storyboard, audio, timeline, render, captions, orchestrate) to the growth-autopilot surface and adds multi-agent orchestration, neural memory, scheduling, approval gates, and evidence ledger integration.

## Existing Foundation

- `src/video_pipeline.rs` — deterministic pipeline with subcommands: script, audio, timeline, render, captions, assets, pipeline (full run), ingest, reference, orchestrate.
- `src/growth_autopilot.rs` — growth command surface (e2e-sandbox, daemon, checkout, portal, funnel, landing-builder).
- Runtime ledger and evidence infrastructure already exist in the codebase.

---

## Sub-Issues

### Sub-issue 1: Growth-Autopilot Video Integration

**Goal:** Wire `growth video-plan`, `growth video-batch`, and `growth video-shorts` subcommands into `growth_autopilot.rs`, delegating to `video_pipeline.rs`.

**Files:** `src/growth_autopilot.rs`, new `src/growth_video.rs`

**Work:**
- Add match arms in `growth_command` for `video-plan`, `video-batch`, `video-shorts`.
- `growth_video.rs`: accept a topic/niche + date range, call `video_command(["pipeline", topic])` in a loop.
- `--dry-run` flag that prints the plan without executing.
- JSON output for each generated video (path, sha256, duration).

---

### Sub-issue 2: Specialized Video Agents (Ledger-Based Orchestration)

**Goal:** Implement 5 agent roles that claim work via the runtime ledger: video-strategist, scriptwriter, video-generation, caption-agent, compliance-reviewer.

**Files:** new `src/video_agents.rs`, `agent/video_gen_provider.py`, `agent/video_gen_registry.py`

**Work:**
- Define agent role enum and lease/claim/handoff protocol using existing ledger primitives.
- Each agent: claim a task from the ledger, execute its stage, write result + sha256 back to ledger, release lease.
- `video orchestrate` already exists — extend it to use ledger-based dispatch instead of sequential calls.
- Python agent helpers (`video_gen_provider.py`, `video_gen_registry.py`) for external video generation API calls (Higgsfield, RunwayML, etc.).

---

### Sub-issue 3: Neural DB Namespaces for Video

**Goal:** Create 5 neural memory namespaces with provenance metadata: `video_scripts`, `storyboards`, `video_assets`, `caption_files`, `video_performance`.

**Files:** new `src/video_memory.rs`, integration in `video_pipeline.rs`

**Work:**
- Define namespace constants and provenance schema (source_agent, timestamp, sha256, parent_id).
- Store/retrieve functions for each namespace using the existing neural DB infrastructure.
- Auto-store after each pipeline stage completes.
- Query interface: `simplicio video memory <namespace> [--query <text>] [--list]`.

---

### Sub-issue 4: Cron/Scheduler for Video Batch Plans

**Goal:** Weekly batch plan generation and daily shorts auto-generation via the existing daemon/cron infrastructure.

**Files:** `src/growth_video.rs` (from sub-issue 1), integration with `src/growth_daemon.rs`

**Work:**
- Register two cron entries: `video-weekly-plan` (Sunday 00:00) and `video-daily-shorts` (daily 06:00).
- Weekly plan: analyze `video_performance` namespace, pick top-performing topics, generate next week''s content calendar as JSON.
- Daily shorts: pick next item from the weekly plan, run full pipeline, store result.
- `--dry-run` and `--json` flags throughout.
- Resume-after-interruption: check ledger for incomplete runs before starting new ones.

---

### Sub-issue 5: Approval Gates and Compliance Review

**Goal:** Insert human-approval checkpoints before any video is uploaded/published.

**Files:** new `src/video_approval.rs`, integration in `video_pipeline.rs`

**Work:**
- After render completes, write an approval-request entry to the ledger with status `pending_review`.
- `simplicio video approve <id>` / `simplicio video deny <id> --reason <text>` commands.
- Denial generates a denial receipt in the evidence ledger with sha256 of the denied artifact.
- Compliance-reviewer agent (from sub-issue 2) can auto-flag but cannot auto-approve.
- Blocked videos remain in `pending` state; approved videos proceed to upload stage.

---

### Sub-issue 6: Evidence Ledger Integration and Testing

**Goal:** Full evidence trail with sha256 checksums for every artifact, plus comprehensive test scenarios.

**Files:** integration across all video modules, new `tests/video_factory_tests.rs`

**Work:**
- Every pipeline stage writes an evidence entry: `{stage, input_sha256, output_sha256, agent, timestamp, duration_ms}`.
- `simplicio video audit <run-id>` — print full evidence chain for a pipeline run.
- Test scenarios:
  - Dry-run: `simplicio growth video-batch --dry-run` produces plan JSON without side effects.
  - Resume-after-interruption: simulate crash mid-pipeline, verify resume picks up from last completed stage.
  - Denial receipt: deny a video, verify evidence ledger contains denial with correct sha256.
  - Full pipeline: script → render → approve → evidence chain is complete and verifiable.

---

## Dependency Order

```
Sub-issue 1 (growth integration)  ──┐
Sub-issue 3 (neural memory)       ──┼──> Sub-issue 4 (cron/scheduler)
Sub-issue 2 (agents)              ──┤
                                    └──> Sub-issue 5 (approval gates)
                                              │
                                              v
                                    Sub-issue 6 (evidence + tests)
```

Sub-issues 1, 2, and 3 can be developed in parallel. Sub-issues 4 and 5 depend on 1+2+3. Sub-issue 6 is the final integration and testing pass.

## Estimated Effort

| Sub-issue | Estimate |
|-----------|----------|
| 1 — Growth integration | Medium |
| 2 — Specialized agents | Large |
| 3 — Neural DB namespaces | Medium |
| 4 — Cron/scheduler | Medium |
| 5 — Approval gates | Medium |
| 6 — Evidence + tests | Large |','docs/issues/1195-plan.md','872c1badb668da4d95d58a512de319015f9624cc93b752cf49ec87602d28b1d7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1196-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1196-plan.md','doc: Issue #1196 — Social Publisher: Epic Decomposition Plan','# Issue #1196 — Social Publisher: Epic Decomposition Plan

## Current State

`src/social_ops.rs` already provides basic `post`, `schedule` (via `--at`), `dry-run`, `analyze`, and `trends` commands for X and Facebook text posts. The schema `simplicio.social-ops/v1` exists.

## What the Epic Requires (beyond current state)

1. **5 coordinated agents** — social-strategist, platform-adapter, copy-chief, approval-gate, analytics
2. **Cron/scheduler** — daily calendar execution, metric ingestion at 2h/24h/72h post-publish
3. **5 Neural DB namespaces** — social_posts, social_accounts, publishing_calendar, post_metrics, approval_records
4. **Approval gate integration** — wired to `htool_write_approval`
5. **Evidence ledger receipts** — for every publish action
6. **Agent lease/handoff protocol** — coordinated multi-agent workflow

---

## Sub-issues

### 1. Neural DB namespaces for social publisher
**Files:** `src/neural_db.rs`, `schemas/social-publisher.schema.json`
- Create 5 namespaces: `social_posts`, `social_accounts`, `publishing_calendar`, `post_metrics`, `approval_records`
- Define JSON schemas for each namespace''s documents
- Add CRUD operations scoped to each namespace
- **Depends on:** nothing

### 2. Approval gate wiring
**Files:** `src/htool_write_approval.rs`, `src/social_ops.rs`
- Wire `social_ops::post` to require approval via `htool_write_approval` before real API calls
- Add `approval_records` namespace writes on approve/reject
- Support auto-approve for dry-run and schedule-only flows
- **Depends on:** sub-issue 1 (approval_records namespace)

### 3. Cron/scheduler integration
**Files:** `src/social_ops.rs`, `src/cron.rs` (new or extend existing)
- Daily calendar scan: read `publishing_calendar` namespace, execute due posts
- Metric ingestion cron: at publish+2h, +24h, +72h, fetch platform metrics and write to `post_metrics`
- Retry/backoff for failed API calls
- **Depends on:** sub-issue 1 (publishing_calendar, post_metrics namespaces)

### 4. Agent definitions and lease protocol
**Files:** `src/social_agents.rs` (new), `src/main.rs`
- Define 5 agent roles: social-strategist, platform-adapter, copy-chief, approval-gate, analytics
- Implement agent lease acquisition/release (mutex-style, file-based or in-memory)
- Define handoff protocol: strategist -> copy-chief -> approval-gate -> platform-adapter -> analytics
- Register agents in `main.rs`
- **Depends on:** sub-issues 1, 2, 3

### 5. Metrics collection loop
**Files:** `src/social_ops.rs`, `src/social_agents.rs`
- Analytics agent polls platform APIs at 2h/24h/72h after publish
- Writes structured metrics (impressions, engagement, clicks, shares) to `post_metrics` namespace
- Generates evidence ledger receipts for each collection
- **Depends on:** sub-issues 1, 3, 4

### 6. Tests and validation
**Files:** `tests/social_publisher_test.rs` (new)
- Unit tests for each namespace CRUD
- Integration test for full pipeline: strategist -> copy -> approve -> publish -> metrics
- Dry-run end-to-end test (no real API calls)
- Approval rejection flow test
- Cron scheduling test with mock clock
- **Depends on:** sub-issues 1-5

---

## Suggested Implementation Order

```
1 ─── Neural DB namespaces (no deps)
2 ─── Approval gate wiring (needs 1)
3 ─── Cron/scheduler integration (needs 1)
4 ─── Agent definitions + lease protocol (needs 1,2,3)
5 ─── Metrics collection loop (needs 1,3,4)
6 ─── Tests and validation (needs all)
```

## Constraints

- std + serde + serde_json + sha2 only (no additional crates without justification)
- No `.unwrap()` in production code
- All publish actions must produce evidence ledger receipts
- Real API calls gated behind env-var credentials (never fabricate post IDs)','docs/issues/1196-plan.md','3a8ca16561bd234ecfbc5b04f6060b5dc1192793e69c8f64a9e08c5ead100207','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1197-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1197-plan.md','doc: Plan: #1197 — Content Calendar and Cron Scheduler','# Plan: #1197 — Content Calendar and Cron Scheduler

## Overview

This epic delivers an end-to-end content-calendar pipeline: strategy → calendar generation → scheduled drafting/publishing → retrospective analysis. It requires coordination across multiple agents, cron-based scheduling, approval gates, and neural-memory provenance.

---

## Work Units

### WU-1: Calendar Agent — Strategy-to-Calendar Conversion
**Files:** `src/htool_content_calendar.rs`, `schemas/growth-content-calendar.schema.json`
- Accept a strategy document (brand voice, audience, goals, platform mix).
- Generate 7/14/30-day content calendars conforming to the existing schema.
- Each calendar entry: date, platform, content-type, topic, suggested-copy, hashtags, optimal-time.
- Validate output against `growth-content-calendar.schema.json`.
- Write calendar to neural memory namespace `content_calendar` with provenance metadata.

### WU-2: Cron Schedule Wiring (4 schedules)
**Files:** `src/htool_cronjob_tools.rs`, `src/scheduler.rs`
- **Daily plan/draft** (`0 7 * * *`): trigger calendar-agent to prepare today''s drafts.
- **Weekday publish-check** (`0 10 * * 1-5`): verify drafts are approved and queue for publishing.
- **Weekly retrospective** (`0 9 * * 1`): trigger analytics agent to produce weekly retro.
- **Monthly calendar refresh** (`0 8 1 * *`): regenerate next 30-day calendar from updated strategy.
- All schedules must support: dry-run mode, pause/resume, idempotency (skip if already executed for period).
- Store schedule state in neural memory namespace `cron_jobs`.

### WU-3: Neural Memory Namespaces
**Files:** `src/htool_memory.rs` (or equivalent memory tool)
- Create and register 4 namespaces:
  - `content_calendar` — calendar entries and revisions.
  - `cron_jobs` — schedule definitions and execution history.
  - `scheduled_tasks` — individual task execution records.
  - `calendar_retrospectives` — weekly/monthly retro reports.
- Every write must include provenance: agent-id, timestamp, source-action, correlation-id.

### WU-4: Approval Gate Integration
**Files:** `src/htool_approval.rs`
- All publish side-effects must pass through the existing approval gate.
- Calendar-agent drafts are marked `pending_approval`.
- Publish-check cron only proceeds for `approved` items.
- Support bulk-approve and single-approve flows.
- Timeout handling: items pending > 48h trigger a reminder notification.

### WU-5: Evidence Ledger Receipts
**Files:** `src/htool_evidence.rs` or extend existing ledger
- Every significant action (calendar generated, draft created, approval granted, content published, retro completed) writes an evidence receipt.
- Receipt format: `{ action, agent_id, timestamp, inputs_hash, outputs_hash, correlation_id }`.
- Receipts stored in append-only ledger with tamper detection (hash chain).

### WU-6: Multi-Agent Coordination (5 agents)
**Files:** `src/scheduler.rs`, `src/tool_registry.rs`, `src/main.rs`
- Agents: calendar, scheduler, social, creative, analytics.
- Lease-based handoff: an agent acquires a lease on a work item before processing.
- Lease expiry and recovery: if an agent crashes mid-task, lease expires and item returns to queue.
- Register new tool handlers in `tool_registry.rs`; add modules in `main.rs`.

### WU-7: Tests (7+ scenarios)
**Files:** `tests/test_content_calendar.rs` or `src/*` (unit tests)
1. Calendar generation from strategy produces valid schema output.
2. Cron dry-run does not trigger side effects.
3. Cron idempotency: duplicate trigger for same period is no-op.
4. Approval gate blocks unapproved publishes.
5. Approval gate passes approved items.
6. Evidence receipt chain integrity (hash chain verification).
7. Lease expiry returns item to queue.
8. Pause/resume cron schedule.

---

## Dependency Order

```
WU-3 (namespaces) → WU-1 (calendar agent) → WU-2 (cron wiring)
WU-4 (approval gate) — can be parallel with WU-1
WU-5 (evidence ledger) — can be parallel with WU-1
WU-6 (multi-agent coord) — depends on WU-1, WU-2, WU-4
WU-7 (tests) — after all others
```

## Constraints

- Rust only: std + serde + serde_json. No `.unwrap()` in production code.
- All errors use `Result<T, E>` with descriptive error types.
- Each WU should be a separate PR for reviewability.','docs/issues/1197-plan.md','269f4c624c5dfebf81add077be0e04a4902e878cf29ca0e15f2e1abe64d949e7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1198-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1198-plan.md','doc: Epic #1198: Outbound CRM — Decomposition Plan','# Epic #1198: Outbound CRM — Decomposition Plan

## Overview

The Outbound CRM capability enables automated lead research, sequence drafting, CRM synchronization, approval gating, and privacy/compliance management. This epic requires 5 new agents, 7 neural DB namespaces, 3 cron jobs, approval gates, and full evidence ledger integration.

---

## Sub-issues

### 1. Schema and Contracts Finalization
- Finalize `growth-outbound-crm.schema.json` with full field definitions for leads, sequences, templates, opt-outs, and tracking events.
- Define inter-agent message contracts (input/output types for each agent).
- Add JSON Schema validation tests.

### 2. Agent Lease and Handoff Scaffolding
- Create the 5 agent modules in `src/`:
  - `htool_lead_research.rs` — lead discovery and enrichment
  - `htool_crm.rs` — CRM sync (create/update/read contacts, deals, activities)
  - `htool_copy_chief.rs` — sequence and email copy drafting
  - `htool_approval_gate.rs` — human-in-the-loop approval for outbound sequences
  - `htool_privacy.rs` — opt-out, suppression list, LGPD/GDPR compliance
- Register all agents in `tool_registry.rs` and wire `mod` declarations in `main.rs`.
- Implement agent lease protocol (acquire/release/heartbeat) for safe concurrent execution.

### 3. Lead Ingestion and Enrichment Pipeline
- Implement lead ingestion from external sources (CSV, webhook, API).
- Build enrichment pipeline: company data, contact info, social profiles.
- Store enriched leads in neural DB namespace `outbound-leads`.
- Create namespace `outbound-companies` for company-level data.
- Evidence ledger: log every enrichment source and timestamp.

### 4. Sequence Drafting and Approval Gate
- Implement multi-step sequence builder (email, follow-up, LinkedIn touch).
- `copy-chief` agent drafts personalized copy per lead segment.
- `approval-gate` agent queues sequences for human review before sending.
- Store drafts in neural DB namespace `outbound-sequences`.
- Store approved/rejected decisions in namespace `outbound-approvals`.
- Evidence ledger: record each draft version, reviewer, and decision.

### 5. Tracking, Opt-out, and Suppression
- Implement open/click/reply tracking events.
- Store events in neural DB namespace `outbound-tracking`.
- `privacy` agent manages suppression lists (namespace `outbound-suppressions`).
- Honor opt-out requests within SLA (immediate suppression).
- Evidence ledger: log all opt-out requests and suppression actions.

### 6. Cron Integration
- Cron 1: **Lead sync** — periodic ingestion and enrichment refresh (e.g., daily).
- Cron 2: **Sequence executor** — send approved sequences on schedule, respecting rate limits and send windows.
- Cron 3: **Suppression audit** — periodic scan to verify suppression list integrity and flag stale leads.
- Register crons in the existing cron infrastructure.

### 7. Tests and Evidence
- Unit tests for each agent module (schema validation, edge cases, error handling).
- Integration tests for the full pipeline: ingest -> enrich -> draft -> approve -> send -> track.
- Evidence ledger integration tests: verify all actions produce audit entries.
- Neural DB namespace isolation tests.

---

## Neural DB Namespaces (7 total)

| Namespace | Purpose |
|---|---|
| `outbound-leads` | Enriched lead profiles |
| `outbound-companies` | Company-level data |
| `outbound-sequences` | Draft and finalized sequences |
| `outbound-approvals` | Approval/rejection decisions |
| `outbound-tracking` | Open/click/reply events |
| `outbound-suppressions` | Opt-out and suppression lists |
| `outbound-evidence` | Full audit/evidence ledger |

## Dependencies

- Existing approval gate infrastructure (`htool_approval.rs`)
- Existing cron scheduling system
- Neural DB read/write capabilities
- Evidence ledger system

## Risks

- Privacy compliance varies by jurisdiction; `privacy` agent must be configurable per region.
- Rate limiting on outbound sends requires careful cron tuning.
- Approval gate latency may delay sequence execution windows.','docs/issues/1198-plan.md','0fc281090fdfb1086550040386e9d6303850b771f6dae1f1f4e25f93ee73820c','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1199-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1199-plan.md','doc: Epic #1199 — Email/DM Sender Adapters: Decomposition Plan','# Epic #1199 — Email/DM Sender Adapters: Decomposition Plan

## Overview

Implement an abstract sender infrastructure supporting email and DM channels with dry-run/test-sink/live modes, dedicated agents, cron-based queue dispatch, bounce/reply ingestion, rate limiting, privacy controls, and analytics — all integrated with the evidence ledger.

## Sub-issues

### 1. Schema: `growth-email-dm-sender.schema.json`
- Define the JSON schema for sender configuration (channel type, mode, recipient, subject, body, metadata).
- Include enums for `mode: dry_run | test_sink | live` and `channel: email | dm`.
- Add fields for rate-limit config, privacy flags, and tracking IDs.

### 2. Sender Trait and Adapter Layer (`src/htool_email_dm_sender.rs`)
- Define `SenderAdapter` trait with `async fn send(&self, payload: &SenderPayload) -> Result<SenderReceipt, SenderError>`.
- Implement three adapter structs: `DryRunSender`, `TestSinkSender`, `LiveSender`.
- `DryRunSender`: logs the payload, returns synthetic receipt.
- `TestSinkSender`: writes to a local file/neural-db namespace for inspection.
- `LiveSender`: calls external HTTP endpoints (email API, DM API) via `ureq` or raw `std::net`.
- Wire into `tool_registry.rs` and `main.rs`.

### 3. Queue and Receipt Storage (neural-db namespaces)
- Create namespace `email_dm_outbox` — pending messages awaiting dispatch.
- Create namespace `email_dm_sent` — successfully dispatched messages with receipts.
- Create namespace `email_dm_failed` — messages that failed after retries.
- Create namespace `email_dm_bounced` — bounce-back records.
- Create namespace `email_dm_replies` — ingested reply records.
- Each record links back to the originating campaign/run via `run_id`.

### 4. Rate Limiter Module (`src/htool_email_dm_rate_limiter.rs`)
- Token-bucket or sliding-window rate limiter per channel and per recipient domain.
- Configurable via schema fields (`max_per_minute`, `max_per_hour`, `max_per_day`).
- Integrates with the outbox queue: messages exceeding limits are deferred, not dropped.

### 5. Privacy Filter (`src/htool_email_dm_privacy.rs`)
- Pre-send check: validate recipient consent flags in neural-db.
- Strip or redact PII fields based on policy (LGPD/GDPR tags in schema).
- Block sends to opt-out recipients; log blocked attempts to evidence ledger.

### 6. Bounce and Reply Ingestion Cron (`src/cron_email_dm_ingest.rs`)
- Cron job polling an inbound mailbox/webhook endpoint for bounces and replies.
- Parse bounce type (hard/soft) and update `email_dm_bounced` namespace.
- Parse replies and store in `email_dm_replies` namespace.
- Hard bounces trigger automatic opt-out of the recipient.

### 7. Queue Dispatch Cron (`src/cron_email_dm_dispatch.rs`)
- Cron job that reads from `email_dm_outbox`, respects rate limits, and calls the sender adapter.
- Moves successful sends to `email_dm_sent`, failures to `email_dm_failed` (with retry count).
- Writes evidence-ledger entries for each dispatch attempt.

### 8. Dedicated Agents (5 agents with lease wiring)
- **email-sender-agent**: orchestrates email dispatch via the adapter.
- **dm-sender-agent**: orchestrates DM dispatch via the adapter.
- **rate-limit-agent**: monitors and enforces rate limits, can pause/resume queues.
- **privacy-agent**: runs pre-send privacy checks, audits consent records.
- **analytics-agent**: aggregates send/bounce/reply metrics, writes summary to neural-db.
- Each agent uses the existing `agent-lease.schema.json` for coordination.

### 9. Approval Gates
- Before `live` mode sends, require approval gate (reuse `growth-approval.schema.json`).
- Approval can be auto-granted for `dry_run` and `test_sink` modes.
- Gate decision recorded in evidence ledger.

### 10. Evidence Ledger Integration
- Every send attempt, bounce, reply, rate-limit hit, privacy block, and approval decision writes an entry to the evidence ledger (`evidence-ledger.schema.json`).
- Enables full audit trail for compliance.

## Suggested Implementation Order

1. Schema (#1)
2. Sender trait + dry-run adapter (#2)
3. Queue namespaces (#3)
4. Rate limiter (#4)
5. Privacy filter (#5)
6. Dispatch cron (#7)
7. Bounce/reply ingestion cron (#6)
8. Agents (#8)
9. Approval gates (#9)
10. Evidence ledger wiring (#10)

## Dependencies

- `serde`, `serde_json` (already in Cargo.toml)
- `agent-lease.schema.json`, `growth-approval.schema.json`, `evidence-ledger.schema.json` (already exist)
- `cron.schema.json` (already exists)','docs/issues/1199-plan.md','cbbe379881db63dc56319209492f10e95bd7dc3217e801c78ee5bedfd323b15b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1200-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1200-plan.md','doc: Epic #1200 — Ads Planner and Spend Gate','# Epic #1200 — Ads Planner and Spend Gate

## Overview

End-to-end ads lifecycle inside simplicio-runtime: planning, creative generation,
budget approval, spend gating, metrics ingestion, and auto-pause/scale logic.
Requires 5 specialized agents, 6 neural DB namespaces, cron jobs, hard caps,
approval flow, dry-run mode, and evidence ledger integration.

---

## Sub-issues

### 1. Runtime command surface + dry-run mode
**Files:** `src/htool_ads_planner.rs`, `src/tool_registry.rs`, `src/main.rs`

- Register commands: `ads.plan`, `ads.launch`, `ads.pause`, `ads.scale`, `ads.report`, `ads.approve`, `ads.reject`.
- Each command accepts `--dry-run` flag; when set, the command simulates execution, logs intent to the evidence ledger, and returns projected results without side effects.
- Wire into `tool_registry.rs` match arms and declare `mod` in `main.rs`.

### 2. Neural DB namespace setup
**Files:** `schemas/growth-ads-planner.schema.json`, `src/neural_db.rs` (or adapter)

Six namespaces to create/validate on startup:
| Namespace | Purpose |
|-----------|---------|
| `ads.campaigns` | Campaign definitions, targeting, schedule |
| `ads.creatives` | Creative assets, copy variants, A/B test groups |
| `ads.budgets` | Budget allocations, daily/total caps per campaign |
| `ads.metrics` | Ingested platform metrics (impressions, clicks, conversions, spend) |
| `ads.approvals` | Approval requests, decisions, audit trail |
| `ads.evidence` | Ledger entries linking actions to outcomes |

### 3. Agent lease and handoff wiring
**Files:** `src/scheduler.rs`, `src/acp_adapter/permissions_gate.rs`

Five agents with lease-based scheduling:
| Agent | Role | Lease TTL |
|-------|------|-----------|
| `ads-strategist` | Plans campaigns, selects audiences, sets KPIs | 300s |
| `ads-creative` | Generates/selects creatives, runs A/B variants | 300s |
| `ads-finance` | Sets budgets, tracks spend, triggers pause on cap | 120s |
| `ads-approval-gate` | Enforces approval policy before spend commits | 60s |
| `ads-analytics` | Ingests metrics, computes ROAS, recommends scale/pause | 180s |

Handoff chain: strategist -> creative -> finance -> approval-gate -> (launch) -> analytics -> (loop back to strategist for optimization).

### 4. Spend gate + approval flow
**Files:** `src/acp_adapter/permissions_gate.rs`, `schemas/growth-approval-policy.schema.json`

- Hard cap enforcement: every spend action checks remaining budget before execution; reject if exceeds daily or total cap.
- Approval policy (from schema): campaigns above a configurable threshold require explicit human approval via `ads.approve` command.
- Three-tier thresholds:
  - **auto-approve**: spend < $50/day
  - **single-approval**: $50-$500/day
  - **dual-approval**: > $500/day
- All gate decisions logged to `ads.approvals` namespace with timestamp, actor, and rationale.

### 5. Cron / scheduler integration
**Files:** `src/scheduler.rs`

Two recurring jobs:
| Job | Interval | Action |
|-----|----------|--------|
| `ads.budget_pacing` | Every 24h (midnight UTC) | Compare actual spend vs. planned pace; alert or auto-adjust bids |
| `ads.pause_check` | Every 2h | Query `ads.metrics` for campaigns exceeding CPA threshold or exhausting budget; auto-pause and log evidence |

Jobs registered via existing scheduler cron infrastructure; each emits structured events to the evidence ledger.

### 6. Metrics ingestion + pause/scale logic
**Files:** `src/htool_ads_metrics.rs`, `src/htool_ads_planner.rs`

- `ads.ingest` command: accepts platform metrics payload (JSON matching `ads.metrics` namespace schema), validates, stores.
- Pause logic: if spend > daily cap OR CPA > 2x target, auto-pause campaign and notify.
- Scale logic: if ROAS > target AND budget headroom exists, recommend (or auto-apply in non-gated mode) bid increase up to cap.
- All decisions written to `ads.evidence` with before/after snapshots.

### 7. Tests + documentation
**Files:** `tests/ads_planner_test.rs`, `docs/ads-planner.md`

- Unit tests for spend gate logic (cap enforcement, threshold tiers).
- Unit tests for dry-run mode (no side effects, correct projections).
- Integration test for full handoff chain (mock agents).
- Documentation: command reference, approval flow diagram, configuration guide.

---

## Dependency order

```
[2] Neural DB namespaces
 |
 v
[1] Command surface + dry-run  ──>  [3] Agent lease/handoff
 |                                        |
 v                                        v
[4] Spend gate + approval      ──>  [5] Cron/scheduler
 |                                        |
 v                                        v
[6] Metrics + pause/scale      ──>  [7] Tests + docs
```

## Estimated effort

| Sub-issue | Estimate |
|-----------|----------|
| 1. Command surface | 1-2 days |
| 2. Neural DB namespaces | 0.5 day |
| 3. Agent wiring | 1-2 days |
| 4. Spend gate | 1-2 days |
| 5. Cron integration | 0.5-1 day |
| 6. Metrics + logic | 1-2 days |
| 7. Tests + docs | 1-2 days |
| **Total** | **6-11 days** |','docs/issues/1200-plan.md','7c12afeb6ad54a1730f8c0e2eddc2df30d693f8fa6a63d2c8c567a53a7362865','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1201-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1201-plan.md','doc: Epic #1201 — Experiment Runner: A/B Tests','# Epic #1201 — Experiment Runner: A/B Tests

## Status

Epic. Schema exists (`schemas/growth-experiment.schema.json`), no Rust implementation of experiment-runner or experiment-agent exists yet.

## Scope

Full A/B test lifecycle: hypothesis definition, variant creation, metric tracking, statistical analysis, decision gates, and structured evidence. Requires 5 distinct agents with lease/handoff, 6 neural DB namespaces, cron integration, and approval gates.

## Existing Assets

- **Schema:** `schemas/growth-experiment.schema.json` (v1) — defines `experiment_id`, `run_id`, `hypothesis`, `primary_metric`, `status` (draft/running/paused/completed/blocked/cancelled), `variant_a`, `variant_b`, `confidence`, `lift_percent`, `sample_size`, `provenance`.
- **Infra references:** `src/infra_advanced.rs` and `src/main.rs` mention experiments but have no runner implementation.
- **Growth modules:** `src/growth_creative_factory.rs`, `src/growth_landing_builder.rs` reference experiments tangentially.

## Sub-Issue Decomposition

### Sub-issue 1: Schema & Contracts (`#1201.1`)

**Files:** `schemas/growth-experiment.schema.json`, new `schemas/experiment-run.schema.json`, new `schemas/experiment-decision.schema.json`

- Extend v1 schema to v2 with: `variants: Vec<Variant>` (not just a/b), `guardrail_metrics`, `minimum_sample_size`, `minimum_duration_hours`, `approval_gate`.
- Add `experiment-run.schema.json`: per-run snapshot with `run_id`, `variant_assignments`, `metric_snapshots`, `statistical_results`.
- Add `experiment-decision.schema.json`: `decision` (ship_variant/rollback/extend/inconclusive), `evidence_refs`, `approver`, `approved_at_unix`.

### Sub-issue 2: Runtime Command Surface (`#1201.2`)

**Files:** new `src/htool_experiment.rs`, `src/main.rs`, `src/tool_registry.rs`

- `simplicio experiment create` — create experiment from hypothesis + variants + metrics.
- `simplicio experiment start <id>` — transition draft to running, set start timestamp.
- `simplicio experiment pause/resume <id>` — pause/resume with reason.
- `simplicio experiment snapshot <id>` — collect current metric values, compute stats.
- `simplicio experiment decide <id>` — evaluate stopping criteria, propose decision.
- `simplicio experiment list` — list all experiments with status.
- `simplicio experiment show <id>` — full experiment detail with run history.
- Register all commands in `tool_registry.rs` and `main.rs` match arms.

### Sub-issue 3: Neural DB Namespaces (`#1201.3`)

**Files:** new `src/experiment_store.rs`, touches `src/infra_advanced.rs`

Six namespaces in the neural DB (SQLite FTS + vector):

1. `experiment:hypotheses` — all hypotheses with embeddings for similarity search.
2. `experiment:runs` — per-run snapshots and metric data.
3. `experiment:decisions` — decision records with evidence refs.
4. `experiment:learnings` — reusable learnings extracted from completed experiments.
5. `experiment:guardrails` — guardrail metric definitions and thresholds.
6. `experiment:templates` — reusable experiment templates (e.g., "landing page CTA test").

Each namespace uses the existing `memory_v2` vector store interface.

### Sub-issue 4: Agent Lease/Handoff (`#1201.4`)

**Files:** new `src/experiment_agents.rs`

Five agents with lease-based coordination:

1. **HypothesisAgent** — formulates and refines hypotheses from growth data. Lease: owns the hypothesis until `status=running`.
2. **VariantAgent** — generates variant implementations (copy, layout, config). Lease: owns variant creation until all variants are ready.
3. **MetricsAgent** — defines metrics, collects snapshots, computes statistical significance. Lease: continuous during `status=running`.
4. **DecisionAgent** — evaluates stopping criteria, proposes ship/rollback/extend. Lease: activated when metrics meet minimum sample/duration.
5. **EvidenceAgent** — packages structured evidence (HBP chain entries) for each experiment outcome. Lease: activated on decision, owns evidence until certified.

Handoff protocol: each agent acquires a lease via `agent_store`, does work, then hands off to the next agent in the pipeline. Lease timeout = 5 minutes (configurable). Failed lease = automatic retry with backoff.

### Sub-issue 5: Cron Integration (`#1201.5`)

**Files:** new `src/experiment_cron.rs`, touches `src/scheduler.rs`

- **Daily job:** `experiment:snapshot` — for all running experiments, collect metric snapshots and check guardrails. If guardrail violated, auto-pause + alert.
- **Weekly job:** `experiment:review` — for all running experiments past minimum duration, trigger DecisionAgent evaluation. Generate weekly digest.
- **On-demand:** `experiment:cleanup` — archive completed experiments older than 90 days to cold storage namespace.
- Register jobs in the existing `scheduler` infrastructure.

### Sub-issue 6: Statistical Engine (`#1201.6`)

**Files:** new `src/experiment_stats.rs`

- Two-sample z-test for proportions (conversion rates).
- Welch''s t-test for continuous metrics (revenue, time-on-page).
- Confidence interval computation (95% default, configurable).
- Minimum detectable effect (MDE) calculator for sample size planning.
- Sequential testing support (optional early stopping with alpha spending).
- All pure Rust, no external crate dependencies (std + serde only).

### Sub-issue 7: Tests (`#1201.7`)

**Files:** new `tests/experiment_*.rs`, unit tests in each module

- Unit tests for statistical functions (known inputs/outputs).
- Unit tests for schema validation (valid/invalid experiment records).
- Integration tests for the create-start-snapshot-decide lifecycle.
- Agent lease/handoff tests (concurrent lease acquisition, timeout, retry).
- Cron job tests (mock clock, verify snapshot collection).

### Sub-issue 8: Documentation (`#1201.8`)

**Files:** `docs/SIMPLICIO_OPERATIONAL_MANUAL.md`, new `docs/experiment-runner.md`

- Command reference for `simplicio experiment *`.
- Architecture diagram: agent pipeline, lease/handoff flow.
- Example walkthrough: la','docs/issues/1201-plan.md','951f23286687a332dd71673f52255eb77d52e0d47c415e62da066b9078e62dee','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1203-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1203-plan.md','doc: Epic #1203: Growth Agent Roster and Task Leases — Decomposition Plan','# Epic #1203: Growth Agent Roster and Task Leases — Decomposition Plan

## Overview

This epic implements a full agent roster system with 12 specialized growth agents,
task lease management, handoff protocols, heartbeat monitoring, and approval gates.
The system runs on the Simplicio runtime with neural DB backing and Rust implementation.

---

## Sub-issues

### 1. Schema-to-Runtime Codegen (`#1203-a`)
- **Input**: `schemas/growth-agent-roster.schema.json`
- **Output**: Rust structs in `src/agents/roster_types.rs`
- **Details**: Generate serde-compatible Rust types for all 12 agent roles, lease records,
  handoff records, evidence entries, and failure entries from the JSON schema.
- **Files**: `src/agents/mod.rs`, `src/agents/roster_types.rs`

### 2. Neural DB Namespace Creation (`#1203-b`)
- **Namespaces to create**:
  1. `growth_agents` — agent definitions and capabilities
  2. `agent_leases` — active lease records (agent_id, task_id, claimed_at, expires_at, status)
  3. `handoffs` — inter-agent handoff log (from_agent, to_agent, task_id, reason, timestamp)
  4. `agent_evidence` — evidence ledger per agent action (agent_id, action, evidence_json, timestamp)
  5. `agent_failures` — failure records with retry metadata (agent_id, task_id, error, retry_count, last_attempt)
- **Files**: `src/agents/db_namespaces.rs`, migration scripts
- **Depends on**: #1203-a

### 3. Lease Claim/Release CLI (`#1203-c`)
- **Commands**:
  - `agent lease claim <agent_id> <task_id> --ttl <seconds>` — atomic claim with conflict detection
  - `agent lease release <agent_id> <task_id>` — graceful release
  - `agent lease list` — show all active leases
  - `agent lease inspect <task_id>` — show lease holder and expiry
- **Logic**: Optimistic locking to prevent double-claim. Return error if task already leased.
- **Files**: `src/htool_agent_lease.rs`, `src/tool_registry.rs` (match arm)
- **Depends on**: #1203-b

### 4. Per-Agent Role Definitions (`#1203-d`)
- **12 specialized agents**:
  1. `growth-scout` — identifies expansion opportunities
  2. `growth-analyst` — analyzes metrics and trends
  3. `growth-writer` — generates copy and content
  4. `growth-designer` — UI/UX asset generation
  5. `growth-deployer` — pushes changes to staging/prod
  6. `growth-monitor` — watches deployed changes for regressions
  7. `growth-optimizer` — A/B test design and winner selection
  8. `growth-researcher` — market and competitor research
  9. `growth-planner` — sprint and roadmap planning
  10. `growth-reviewer` — code and content review gate
  11. `growth-support` — user feedback triage
  12. `growth-ops` — infrastructure and reliability
- **Each role defines**: capabilities, allowed mutations, required approvals, max concurrent leases
- **Files**: `src/agents/roles/*.rs` (one per role), `src/agents/roles/mod.rs`
- **Depends on**: #1203-a

### 5. Heartbeat Cron and Stale Lease Reaper (`#1203-e`)
- **Heartbeat**: Each agent with an active lease must send heartbeat every N seconds (configurable).
  Heartbeat updates `last_heartbeat_at` in `agent_leases` namespace.
- **Reaper**: Cron job (configurable interval, default 60s) scans `agent_leases` for entries where
  `now - last_heartbeat_at > ttl`. Stale leases are marked `expired`, task returned to queue.
- **Idempotency**: Reaper must be safe to run concurrently (multiple instances).
- **Files**: `src/agents/heartbeat.rs`, `src/agents/reaper.rs`
- **Depends on**: #1203-b, #1203-c

### 6. Approval Gate Enforcement (`#1203-f`)
- **Rule**: Any agent action classified as a "live mutation" (deploy, publish, delete, schema change)
  must pass through an approval gate before execution.
- **Flow**: Agent requests approval -> record created in `agent_evidence` with status `pending_approval`
  -> human or `growth-reviewer` agent approves/rejects -> action proceeds or is blocked.
- **Config**: Per-role approval requirements defined in role definitions (#1203-d).
- **Files**: `src/agents/approval_gate.rs`
- **Depends on**: #1203-d, #1203-b

### 7. Evidence Ledger Integration (`#1203-g`)
- **Every agent action** produces an evidence entry: what was done, why, inputs, outputs, duration.
- **Queryable**: CLI command `agent evidence list --agent <id> --since <timestamp>`
- **Immutable**: Evidence records are append-only. No updates or deletes.
- **Files**: `src/agents/evidence.rs`, `src/htool_agent_evidence.rs`
- **Depends on**: #1203-b

### 8. Agent Handoff Protocol (`#1203-h`)
- **Handoff flow**: Agent A completes subtask -> creates handoff record -> releases lease ->
  Agent B claims next task referencing handoff.
- **Handoff record**: Contains context payload (arbitrary JSON), reason, priority hint.
- **Validation**: Target agent must have capability matching the task type.
- **Files**: `src/agents/handoff.rs`
- **Depends on**: #1203-c, #1203-d

### 9. Desktop UI — Agents Page (`#1203-i`)
- **File**: `apps/desktop/src/pages/Agents.tsx`
- **Features**: List all 12 agents with status (idle/active/failed), active leases,
  recent evidence entries, pending approvals.
- **Nav**: Add entry in `apps/desktop/src/lib/nav.ts`
- **Depends on**: #1203-d, #1203-g

### 10. Kanban Plugin Integration (`#1203-j`)
- **File**: `plugins/kanban/dashboard/plugin_api.py`
- **Features**: Surface agent tasks as kanban cards, show lease status, allow manual
  reassignment through drag-and-drop.
- **Depends on**: #1203-c, #1203-i

### 11. Test Suite (`#1203-k`)
- **Scenarios**:
  - Concurrent lease claims (two agents claim same task — one must fail)
  - Lease expiry and reaper reclaim
  - Heartbeat timeout detection
  - Approval gate blocks unapproved mutations
  - Handoff context preservation
  - Idempotent reaper execution
  - Resume-after-interruption (agent crashes mid-task, lease expires, another agent picks up)
  - Evidence ledger immutability
- **Files**: `tests/agent_roster_tests.rs`, `tests/lease_concurrency_tests.rs`
- **Depends on**: All above

---

## Dependency Graph

```
#1203-a (Schema Codegen)
   |','docs/issues/1203-plan.md','e4261c1f539bececab6c11ddca776ec101b95a028b30958a6686bf77d79f9a49','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1204-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1204-plan.md','doc: Epic #1204: Market/Competitor Research Loop — Decomposition Plan','# Epic #1204: Market/Competitor Research Loop — Decomposition Plan

## Overview

Implement an automated market and competitor research pipeline with four specialized agents, neural DB storage, weekly cron refresh, governed external data ingestion, and provenance/confidence tracking.

## Current State

- A JSON schema stub exists at `schemas/growth-market-research.schema.json`
- No runtime command handler, agent implementations, neural DB namespaces, cron integration, or evidence ledger wiring

## Sub-Issues

### Sub-issue 1: Runtime Command and API Surface

**Files:** `src/main.rs`, `src/cmd_market_research.rs`, `src/tool_registry.rs`

- Add `market-research` command with subcommands: `run`, `status`, `dry-run`, `report`
- Wire into `tool_registry.rs` match arms
- `dry-run` mode validates config and agent availability without executing
- Input/output types derived from `growth-market-research.schema.json`
- Error handling with `Result<T, MarketResearchError>` (no `.unwrap()`)

### Sub-issue 2: Agent Implementations (Market Research, Levi External, Strategy, Evidence)

**Files:** `src/agents/market_research_agent.rs`, `src/agents/levi_external_agent.rs`, `src/agents/strategy_agent.rs`, `src/agents/evidence_agent.rs`, `src/agents/mod.rs`

- **market-research-agent**: orchestrator that coordinates the research loop, manages agent leases, handles handoff protocol
- **levi-external-agent**: governed external data ingestion (web scraping, API calls) with rate limiting, source validation, and data sanitization
- **strategy-agent**: analyzes collected data, identifies market trends, generates competitive positioning recommendations
- **evidence-agent**: validates claims with citations, assigns confidence scores, maintains provenance chain
- Each agent implements a common `Agent` trait with `lease()`, `execute()`, `handoff()`, `release()` methods

### Sub-issue 3: Neural DB Namespaces

**Files:** `src/neural_db.rs` or `src/db/mod.rs`

Create five namespaces:
1. `market-research/competitors` — competitor profiles and updates
2. `market-research/trends` — market trend data points
3. `market-research/sources` — raw ingested source material with provenance
4. `market-research/analysis` — strategy agent outputs and recommendations
5. `market-research/evidence` — evidence ledger entries with confidence scores

Each namespace needs CRUD operations and vector similarity search support.

### Sub-issue 4: Cron/Scheduler Integration for Weekly Competitor Refresh

**Files:** `src/cron.rs` or `src/scheduler.rs`, config files

- Register a weekly cron job for competitor data refresh
- Configurable schedule via `growth-market-research.schema.json` or runtime config
- Idempotent execution (safe to re-run)
- Logging and alerting on failures
- Manual trigger capability via the `market-research run --refresh` command

### Sub-issue 5: Provenance, Confidence Tracking, and Evidence Ledger

**Files:** `src/evidence_ledger.rs`, `src/provenance.rs`

- Every data point tracks: source URL/API, retrieval timestamp, agent that processed it, confidence score (0.0-1.0)
- Evidence ledger records all claims with supporting/contradicting evidence
- Confidence decay over time (stale data loses confidence)
- Audit trail for all agent decisions
- Integration with the evidence-agent for validation

### Sub-issue 6: Tests and Documentation

**Files:** `tests/market_research_*.rs`, `docs/growth-autopilot/README.md`

- Unit tests for each agent
- Integration test for the full research loop (with mocked external sources)
- `dry-run` mode test
- Update `docs/growth-autopilot/README.md` with usage instructions, architecture diagram, and configuration reference

## Suggested Implementation Order

1. Sub-issue 1 (command surface) — foundation for everything else
2. Sub-issue 3 (neural DB namespaces) — agents need storage
3. Sub-issue 2 (agents) — core logic, depends on 1 and 3
4. Sub-issue 5 (provenance/evidence) — cross-cutting, integrates with agents
5. Sub-issue 4 (cron) — depends on working agents
6. Sub-issue 6 (tests/docs) — parallel with later sub-issues

## Dependencies

- `std`, `serde`, `serde_json` only (no additional crates)
- Existing neural DB infrastructure (if any)
- Existing agent trait/framework (if any)','docs/issues/1204-plan.md','9dbb20dd105c5a7d97c737b8ee68e371d0786a66d3547aff626bda31d52ff4cd','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1205-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1205-plan.md','doc: Plan: Customer Discovery Autopilot (#1205)','# Plan: Customer Discovery Autopilot (#1205)

## Status

Epic — requires decomposition into implementable sub-issues.

## Context

The JSON schema `schemas/growth-customer-discovery.schema.json` exists but no Rust implementation backs it. This plan decomposes the epic into concrete, ordered sub-issues.

## Sub-issues

### 1. Neural DB namespace setup

**Files:** `src/growth_autopilot.rs`, new `src/neural_db_namespaces.rs`

Create the five neural DB namespaces required by the schema:

- `customer_interviews`
- `survey_responses`
- `feedback_items`
- `pain_points`
- `voice_of_customer`

Implement namespace creation, migration check, and health probe. No `.unwrap()` — all errors propagated via `Result`.

### 2. Agent definitions (4 agents)

**Files:** new `src/agents/customer_research_agent.rs`, `src/agents/copy_chief_agent.rs`, `src/agents/crm_agent.rs`, `src/agents/learning_curator_agent.rs`, `src/agents/mod.rs`

Define agent structs with:

- Lease acquisition / release
- Handoff protocol between agents
- Retry + back-off on lease contention
- Dry-run mode (no side-effects)

### 3. Runtime command + dry-run

**Files:** `src/main.rs`, `src/growth_autopilot.rs`

- Add `customer-discovery` command to CLI / API surface in `main.rs`
- Wire match arm in `tool_registry.rs` (if applicable)
- Support `--dry-run` flag that validates config and prints planned actions without executing

### 4. Cron / scheduler integration

**Files:** `src/growth_daemon.rs`, new `src/cron/customer_discovery_cron.rs`

- Weekly planning job: generates discovery plan for the week
- Daily ingestion job: pulls new interview/survey/feedback data into neural DB namespaces
- Register jobs in `growth_daemon.rs`

### 5. Approval gate integration

**Files:** `src/growth_autopilot.rs`

- Before executing discovery actions that cost money or contact customers, require approval gate
- Integrate with existing approval gate mechanism (if any) or define new trait
- Support auto-approve in dry-run / test mode

### 6. Evidence ledger writes

**Files:** `src/growth_autopilot.rs`

- Every agent action writes to the evidence ledger
- Include timestamp, agent ID, action type, input hash, output summary
- Ledger entries must be append-only and auditable

### 7. Tests

**Files:** new `tests/customer_discovery_test.rs`, unit tests in each module

- Unit tests for namespace creation
- Unit tests for agent lease/handoff
- Integration test for full dry-run pipeline
- Test that evidence ledger entries are written correctly

## Dependency order

```
1 (namespaces) → 2 (agents) → 3 (command) → 4 (cron) → 5 (approval) → 6 (ledger) → 7 (tests)
```

Sub-issues 5 and 6 can be parallelized after 3 is done. Sub-issue 7 should be developed incrementally alongside each sub-issue.

## Constraints

- `std` + `serde` + `serde_json` only
- No `.unwrap()` in production code
- All errors use `Result<T, E>` with descriptive error types','docs/issues/1205-plan.md','7d7d357135cd19735317cf379019c4a2feac33b0c007c612423e99c34d5e959a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1207-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1207-plan.md','doc: Epic #1207 — Growth Cockpit Dashboard','# Epic #1207 — Growth Cockpit Dashboard

## Overview

Transform the minimal `dashboard_command.rs` status page into a full growth cockpit with campaign management, approval workflows, Stripe revenue integration, funnel metrics, experiment tracking, and agent orchestration.

## Sub-Issues

### Phase 1: Data Layer (Neural DB Namespaces)

**#1207-A: Create 5 new neural DB namespaces**
- `dashboard_snapshots` — periodic state captures for historical view
- `approval_queue` — pending approve/deny/pause/resume items
- `campaign_status` — campaign pipeline state and transitions
- `revenue_summary` — Stripe revenue aggregation cache
- `next_actions` — prioritized action items and blocked tasks
- Files: `src/plugins/neural_db/mod.rs`, namespace registration in `src/plugins/registry.rs`

### Phase 2: Core Dashboard Backend

**#1207-B: Campaign pipeline view**
- CRUD for campaigns with status transitions (draft → active → paused → completed)
- Pipeline stage tracking and visualization data
- Files: `src/dashboard_command.rs`, new `src/htool_campaign_pipeline.rs`

**#1207-C: Approval queue with actions**
- Queue data model: item, requester, approver, status, timestamps
- Actions: approve, deny, pause, resume
- Audit trail for every action
- Files: new `src/htool_approval_queue.rs`, `src/plugins/dashboard_auth/mod.rs`

**#1207-D: Stripe revenue cards**
- Integrate with `src/growth_stripe.rs` for revenue data
- Summary cards: MRR, ARR, churn, new revenue, expansion
- Daily/weekly/monthly aggregation into `revenue_summary` namespace
- Files: `src/growth_stripe.rs`, new `src/htool_revenue_cards.rs`

**#1207-E: Funnel metrics and experiment tracking**
- Funnel stage definitions and conversion tracking
- A/B experiment status, variants, results
- Files: new `src/htool_funnel_metrics.rs`, new `src/htool_experiments.rs`

**#1207-F: Blocked tasks view**
- Surface tasks blocked by dependencies, approvals, or errors
- Integration with `next_actions` namespace
- Files: new `src/htool_blocked_tasks.rs`

### Phase 3: Agent Roles

**#1207-G: Define 4 agent roles**
- `dashboard-agent` — serves dashboard data, handles refresh
- `analytics-agent` — computes metrics, funnel analysis, experiment results
- `approval-gate-agent` — manages approval workflow, enforces policies
- `orchestrator-agent` — coordinates agents, schedules tasks, daily digests
- Files: `src/plugins/registry.rs`, new `src/agents/` module

### Phase 4: Scheduling and Automation

**#1207-H: Cron/scheduler for live refresh and daily digests**
- Periodic snapshot into `dashboard_snapshots`
- Daily digest generation and delivery
- Configurable refresh intervals
- Files: new `src/scheduler.rs` or integration with existing cron

### Phase 5: Audit and Evidence

**#1207-I: Audit event logging and evidence ledger integration**
- Every approval action, campaign change, and agent decision logged
- Evidence ledger entries for compliance
- Files: new `src/htool_audit_log.rs`, integration with existing evidence ledger

### Phase 6: Auth and Security

**#1207-J: Dashboard authentication enhancements**
- Role-based access for dashboard sections
- Extend `src/plugins/dashboard_auth/basic.rs` for new agent roles
- Files: `src/plugins/dashboard_auth/mod.rs`, `src/plugins/dashboard_auth/basic.rs`

## Implementation Order

1. #1207-A (namespaces) — foundation for all other work
2. #1207-B, #1207-C, #1207-D in parallel — core features
3. #1207-E, #1207-F — secondary features
4. #1207-G — agent roles (depends on core features)
5. #1207-H — scheduling (depends on agents)
6. #1207-I, #1207-J — cross-cutting concerns, last

## Constraints

- Rust std + serde + serde_json only
- No `.unwrap()` in production code
- Each sub-issue should pass `cargo check` independently','docs/issues/1207-plan.md','3ea7ce2b708cf1ff4f663c9f88f161188ffc72ff539b6dcc9a70215b05281282','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1208-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1208-plan.md','doc: Epic #1208 — Post-sale Onboarding and Retention','# Epic #1208 — Post-sale Onboarding and Retention

## Overview

Implement a complete post-sale customer success pipeline: from Stripe checkout webhook through onboarding steps, activation tracking, health scoring, and churn prevention. Currently only a JSON schema exists (`schemas/growth-customer-onboarding.schema.json`); no runtime code supports this workflow.

---

## Sub-issues

### 1. Neural DB namespaces for customer data
- Create namespaces: `customers`, `onboarding_steps`, `activation_events`, `retention_metrics`, `churn_risks`
- Define CRUD helpers in a new `src/htool_customer_db.rs`
- Wire into `tool_registry.rs`

### 2. Stripe checkout webhook handler
- New `src/htool_stripe_webhook.rs`
- Verify Stripe webhook signatures (HMAC)
- On `checkout.session.completed`: create customer record in neural DB, enqueue welcome email, initialize onboarding checklist
- Register in `tool_registry.rs`

### 3. Customer-success agent
- New `src/htool_customer_success.rs`
- Orchestrates onboarding flow: tracks step completion, computes activation score
- Triggers nudge emails when steps are stalled
- Escalates to human via approval gate when health score drops below threshold

### 4. Email agent
- New `src/htool_email_agent.rs`
- Template-based email sending (welcome, nudge, milestone, churn-risk)
- All customer-facing messages go through approval gate before sending
- Queue-based with retry logic

### 5. Analytics agent
- New `src/htool_analytics_agent.rs`
- Computes customer health score from activation events and usage data
- Generates weekly churn-risk report
- Stores metrics in `retention_metrics` namespace

### 6. Scheduled jobs (cron)
- **Daily health check**: recompute health scores, flag at-risk customers
- **Weekly churn report**: aggregate churn-risk data, send summary to customer success team
- Integration with existing cron/scheduler infrastructure

### 7. Approval gate integration
- Wire approval gates for all customer-facing messages (emails, in-app notifications)
- Human-in-the-loop review before any outbound communication
- Audit trail in neural DB

### 8. End-to-end tests
- Test scenario: new checkout -> onboarding flow -> activation -> healthy state
- Test scenario: stalled onboarding -> nudge -> recovery
- Test scenario: declining health -> churn risk alert -> intervention
- Mock Stripe webhooks and email delivery

---

## Dependency order

```
1 (DB namespaces)
  -> 2 (Stripe webhook)
  -> 3 (Customer-success agent)  <- depends on 1, 2
  -> 4 (Email agent)             <- depends on 7
  -> 5 (Analytics agent)         <- depends on 1
  -> 6 (Cron jobs)               <- depends on 3, 5
  -> 7 (Approval gate)           <- depends on 1
  -> 8 (E2E tests)               <- depends on all above
```

## Constraints

- Rust only, std + serde + serde_json
- No `.unwrap()` in production code; use `Result` propagation
- Each sub-issue should be a separate PR for reviewability','docs/issues/1208-plan.md','bfbf4f979613b7294e923c3049f581cc1f9d13aefa4fec25e1fd0e747bfb9cca','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1209-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1209-plan.md','doc: Epic #1209 — Growth Daemon Mode: Decomposition Plan','# Epic #1209 — Growth Daemon Mode: Decomposition Plan

## Current State

`src/growth_daemon.rs` is a governed stub that parses CLI flags and emits a JSON receipt describing daemon state. It does **not**:

- Run a persistent loop or heartbeat
- Integrate with neural DB namespaces
- Enforce pause/resume/kill-switch at runtime
- Perform crash recovery
- Write evidence ledger entries
- Schedule via cron
- Enforce approval gates
- Have any tests

## Sub-tasks

### 1. Schema & Contracts
**Files:** `schemas/growth-daemon-mode.schema.json`
- Define JSON Schema for daemon state, campaign config, heartbeat payloads, kill-switch signals, checkpoint format, and evidence ledger entries.
- All downstream sub-tasks consume these contracts.

### 2. Daemon Loop with Heartbeat
**Files:** `src/growth_daemon.rs`, `src/organism/daemon.rs`
- Implement a persistent `run_loop()` that:
  - Emits heartbeat every N seconds (configurable).
  - Reads campaign queue and dispatches work.
  - Writes heartbeat records to `growth_daemon_state` DB namespace.
- No `.unwrap()` in production paths; all errors propagated via `Result`.

### 3. Pause / Resume / Kill-switch Runtime Enforcement
**Files:** `src/growth_daemon.rs`
- On each loop tick, check `kill_switches` namespace for active signals.
- If `--pause` flag or DB signal is set, transition to paused state (idle loop, heartbeat continues with `"status": "paused"`).
- `--resume` or DB signal transitions back to active.
- Kill-switch immediately halts all campaign work, writes evidence, and exits cleanly.

### 4. Crash Recovery Scan
**Files:** `src/growth_daemon.rs`, `src/organism/daemon.rs`
- On startup, scan `crash_recovery` namespace for incomplete runs.
- Read last checkpoint from `resume_points` namespace.
- Emit structured log of recovered state.
- Resume from last checkpoint or mark run as failed with evidence.

### 5. Neural DB Namespace Integration
**Files:** `src/growth_daemon.rs`, `src/organism/daemon.rs`
- Integrate 5 DB namespaces via `htool_memory_tool` / `lmdb_store`:
  1. `growth_daemon_state` — current daemon status, heartbeat history.
  2. `active_campaigns` — campaign configs and progress.
  3. `kill_switches` — active kill-switch signals.
  4. `resume_points` — checkpoint data for crash recovery.
  5. `crash_recovery` — incomplete run records.
- All reads/writes go through a `DaemonStore` trait for testability.

### 6. Cron / Scheduler Wiring
**Files:** `src/htool_cronjob_tools.rs`, `src/cron_scheduler.rs`
- Register `growth-daemon-heartbeat` as a cron job via `htool_cronjob_tools`.
- Allow scheduling daemon start/stop via cron expressions.
- Integrate with existing `cron_scheduler.rs` infrastructure.

### 7. Approval Gate Enforcement
**Files:** `src/growth_daemon.rs`, `src/growth_autopilot.rs`
- Before executing campaign actions, check approval queue.
- If `--approval-id` is pending, block execution until approved.
- Integrate with `growth_autopilot.rs` for auto-approval in sandbox mode.
- Write approval decisions to evidence ledger.

### 8. Agent Roles
**Files:** `src/organism/daemon.rs`
- Define 4 agent roles within daemon context:
  1. **Orchestrator** — manages campaign queue and dispatches work.
  2. **Executor** — runs individual campaign actions.
  3. **Monitor** — watches heartbeat, triggers kill-switch on anomalies.
  4. **Auditor** — writes evidence ledger, validates receipts.
- Each role is a logical component within the daemon loop (not separate processes).

### 9. Unit and Integration Tests
**Files:** `tests/growth_daemon_tests.rs` (new)
- Unit tests for:
  - CLI argument parsing (existing + new flags).
  - State machine transitions (active -> paused -> resumed -> killed).
  - Checkpoint serialization/deserialization.
  - Kill-switch detection.
  - Crash recovery scan logic.
- Integration tests for:
  - Full daemon lifecycle (start -> heartbeat -> pause -> resume -> stop).
  - Crash recovery from simulated incomplete run.
  - Approval gate blocking and unblocking.
  - Cron scheduling round-trip.

## Dependency Order

```
1. Schema & Contracts
   |
   v
2. Neural DB Namespace Integration
   |
   +---> 3. Daemon Loop with Heartbeat
   |        |
   |        +---> 4. Pause/Resume/Kill-switch
   |        |
   |        +---> 5. Crash Recovery
   |
   +---> 7. Approval Gate Enforcement
   |
   +---> 6. Cron/Scheduler Wiring
   |
   v
8. Agent Roles (cross-cutting, after loop + DB)
   |
   v
9. Tests (after all implementation)
```

## Estimated Effort

| Sub-task | Complexity | Files touched |
|----------|-----------|---------------|
| 1. Schema | Low | 1 new |
| 2. Daemon loop | High | 2 |
| 3. Pause/resume/kill | Medium | 1 |
| 4. Crash recovery | Medium | 2 |
| 5. DB namespaces | High | 2 |
| 6. Cron wiring | Medium | 2 |
| 7. Approval gates | Medium | 2 |
| 8. Agent roles | High | 1 |
| 9. Tests | High | 1 new |','docs/issues/1209-plan.md','c4ac0bc85815e4f92742643f650b533e8571e5ea3df2ce936b152923ab58fd63','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1211-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1211-plan.md','doc: Plan: #1211 — Growth Autopilot Manual, Examples & Schemas','# Plan: #1211 — Growth Autopilot Manual, Examples & Schemas

## Context

The Growth Autopilot subsystem (`src/growth_autopilot.rs`, `src/growth_daemon.rs`, `src/growth_stripe.rs`, `src/growth_landing_builder.rs`) and its 9 schemas (`schemas/growth-*.schema.json`) are implemented but lack documentation, example fixtures, operator runbooks, and test coverage.

## Sub-issues

### 1. Operational Manual (`docs/growth-autopilot-manual.md`)
- Document the full command flow: `simplicio growth <subcommand>`
- Cover subcommands: `e2e-sandbox`, `daemon-mode`, `checkout`, `portal`, `funnel`, `landing-builder`
- Document env vars (`STRIPE_SECRET_KEY`, etc.), `--dry-run` flags, `--json` output
- Include architecture diagram (text-based) showing agent handoff flow

### 2. Example SaaS Fixtures (`examples/growth/`)
- `examples/growth/saas-basic.json` — minimal growth-run with one campaign
- `examples/growth/saas-multi-offer.json` — multiple offers with experiments
- `examples/growth/e2e-sandbox-fixture.json` — full sandbox config
- `examples/growth/landing-page-fixture.json` — landing builder input
- All fixtures must validate against their respective schemas

### 3. Schema Documentation (`docs/growth-schemas.md`)
- Document each of the 9 schemas with field descriptions, required vs optional, and example values:
  - `growth-run`, `growth-campaign`, `growth-offer`, `growth-asset`
  - `growth-approval`, `growth-experiment`, `growth-revenue-event`
  - `growth-e2e-sandbox`, `growth-daemon-mode`
- Add JSON Schema `$id` and `description` fields to schemas missing them

### 4. Operator Safety Checklist (`docs/growth-operator-checklist.md`)
- Pre-launch checklist (env vars set, Stripe test mode, sandbox validated)
- Go-live checklist (switch to live keys, confirm webhook endpoints)
- Rollback procedures
- Monitoring and alerting guidance

### 5. Neural Memory Namespace Setup
- Register namespaces: `growth_schemas`, `docs_examples`, `runbooks`, `operator_checklists`
- Wire into `simplicio memory` subsystem so agents can query growth docs
- Add namespace definitions to memory config

### 6. Cron/Scheduler Integration for Docs Updates
- Add a scheduled task that validates examples against schemas on CI
- `simplicio growth validate-examples` subcommand
- Integrate with existing cron infrastructure (`src/cron_*.rs`)

### 7. Agent Lease/Handoff Behavior
- Document the 4-agent handoff pattern for growth operations:
  1. **Planner** — decomposes campaign into tasks
  2. **Builder** — generates assets and landing pages
  3. **Launcher** — executes checkout/funnel setup
  4. **Monitor** — tracks revenue events and experiments
- Define lease durations, escalation policies, and scope boundaries
- Reference `schemas/agent-lease.schema.json` and `schemas/agent-scope.schema.json`

### 8. Test Coverage (`tests/growth_*.rs`)
- Schema validation tests (load each schema, validate example fixtures)
- CLI integration tests for `simplicio growth` subcommands with `--dry-run`
- Agent handoff state machine tests
- E2E sandbox lifecycle test

### 9. Evidence Ledger Integration
- Log all growth operations to the evidence ledger
- Include schema version, timestamp, operator, and outcome
- Wire into existing `src/evidence_*.rs` infrastructure

## Priority Order

1. Schema Documentation (3) — foundation for everything else
2. Example Fixtures (2) — needed for tests and manual
3. Operational Manual (1) — primary deliverable
4. Operator Checklist (4) — safety-critical
5. Test Coverage (8) — validates all above
6. Agent Handoff Docs (7) — architectural clarity
7. Neural Memory (5) — discoverability
8. Evidence Ledger (9) — audit trail
9. Cron Integration (6) — automation','docs/issues/1211-plan.md','aff08acce25abd0c24ae18e4ba33f0ed5414552bc34ae5720ad3b2f267add546','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1212-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1212-plan.md','doc: Issue #1212 — Computer/Browser Resource Broker — Decomposition Plan','# Issue #1212 — Computer/Browser Resource Broker — Decomposition Plan

## Current State

`src/capability_broker.rs` (611 lines) implements the core CLI broker with subcommands: `list`, `request`, `approve`, `deny`, `revoke`, `run`, and `status`. JSON schemas exist for `capability-request`, `capability-lease`, `capability-broker`, and `capability-registry`.

## Missing Components

The issue requires 8 specialized agents, cron/scheduler integration, 9 neural DB namespaces, an adapter registry, evidence ledger writes, growth-autopilot integration, and dry-run previews. None of these exist yet.

## Sub-Issues

### 1. Adapter Registry (`adapter_registry.rs`)
- Abstract trait for browser/playwright/computer-use/shell/filesystem/MCP adapters
- Registration, discovery, health-check interface
- Schema: `capability-adapter.schema.json`

### 2. Agent: `browser-operator`
- Drives browser sessions via adapter registry
- Tab management, navigation, DOM interaction
- Evidence ledger writes for each action

### 3. Agent: `computer-use`
- Desktop automation agent (mouse, keyboard, screenshots)
- Scope-limited by capability lease
- Evidence ledger writes with screenshot redaction

### 4. Agent: `playwright-e2e`
- End-to-end test execution via Playwright adapter
- Structured test result reporting
- Neural DB writes to `e2e-results` namespace

### 5. Agent: `credential-gate`
- Secure credential storage and injection
- Credential health checks (expiry, rotation)
- Redaction rules for evidence ledger

### 6. Agent: `approval-gate`
- Human-in-the-loop approval workflow
- Escalation policies, auto-approve rules
- Cron: approval reminder notifications

### 7. Agent: `evidence`
- Evidence ledger writes with redaction pipeline
- Append-only log with integrity hashes
- Neural DB namespace: `evidence-ledger`

### 8. Agent: `risk-reviewer`
- Pre-execution risk scoring
- Dry-run preview generation
- Manual fallback trigger when risk exceeds threshold

### 9. Agent: `capability-broker` (enhanced)
- Orchestrates the other 7 agents
- Lease lifecycle management
- Growth-autopilot integration hooks

### 10. Cron/Scheduler Integration
- Lease expiry checker (revoke expired leases)
- Approval reminder sender
- Credential health check scheduler
- Wire into existing `cron.rs` / scheduler infrastructure

### 11. Neural DB Schema (9 namespaces)
- `capability-requests`, `capability-leases`, `capability-runs`
- `adapter-registry`, `credential-vault`, `approval-log`
- `evidence-ledger`, `risk-scores`, `broker-state`
- Migration scripts and namespace initialization

### 12. Growth-Autopilot Wiring
- Hook capability usage metrics into growth-autopilot
- Usage pattern analysis for auto-scaling suggestions
- Dashboard data export

### 13. Tests
- Unit tests for adapter registry trait
- Integration tests for each of the 8 agents
- Cron job scheduling tests
- Evidence ledger integrity tests
- Dry-run preview accuracy tests
- End-to-end scenario: request → approve → run → evidence → revoke

## Suggested Implementation Order

1. Adapter Registry (foundation for all agents)
2. Evidence agent + ledger (needed by all other agents)
3. Credential-gate (needed before browser/computer agents)
4. Approval-gate (needed before any execution)
5. Risk-reviewer (pre-execution check)
6. Browser-operator, Computer-use, Playwright-e2e (parallel)
7. Capability-broker orchestrator (enhanced)
8. Cron/scheduler integration
9. Neural DB namespaces
10. Growth-autopilot wiring
11. Tests for all scenarios','docs/issues/1212-plan.md','2beebd67d3abacab652ecbc75eee2eed811868f92a99b46bcc23c0dcd1bd965a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1213-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1213-plan.md','doc: Epic #1213: Absorver ecossistema de agentes 2026','# Epic #1213: Absorver ecossistema de agentes 2026

## Visao geral

Integrar o simplicio-runtime com o ecossistema moderno de agentes AI (2026), adicionando capacidades de orquestracao, execucao externa, browser automation, benchmarking e novos skills.

## Sub-issues e priorizacao

### Fase 1 — Fundacao (semanas 1-2)

#### #1215 — Hardening do simplicio edit com search/replace blocks
- **Modulo:** `src/edit/mod.rs`
- **Escopo:** Melhorar o mecanismo de edicao para usar search/replace blocks em vez de reescrita completa. Adicionar fallback fuzzy-match, validacao de unicidade do bloco, e testes de regressao.
- **Prioridade:** P0 — base para todos os outros workstreams que geram/editam codigo.
- **Estimativa:** 3-5 dias

#### #1216 — Exec-graph runtime (LangGraph/CrewAI patterns)
- **Modulo:** `src/organism/central_loop.rs`, novo modulo `src/exec_graph/`
- **Escopo:** Implementar um runtime de execucao baseado em grafos (DAG) para orquestrar multiplos agentes/steps. Inspirado em LangGraph e CrewAI, mas usando Rust nativo. Suportar nodes condicionais, loops, e paralelismo via tokio.
- **Prioridade:** P0 — necessario para orquestrar os demais agentes.
- **Estimativa:** 5-8 dias

### Fase 2 — Integracoes externas (semanas 3-4)

#### #1214 — MCP catalog ingestion
- **Modulo:** `src/gateway/mod.rs`, novo modulo `src/mcp_catalog/`
- **Escopo:** Ingerir e indexar catalogos MCP (Model Context Protocol) para descoberta automatica de ferramentas. Parsear JSON schema, manter cache local, e expor via gateway.
- **Prioridade:** P1 — habilita descoberta dinamica de tools.
- **Estimativa:** 3-5 dias

#### #1217 — n8n como backend de execucao
- **Modulo:** `src/action_gate.rs`, novo modulo `src/n8n_backend/`
- **Escopo:** Integrar n8n como backend de execucao para workflows complexos. O action_gate roteia acoes que precisam de integracao externa (email, HTTP, DB) para workflows n8n via API REST.
- **Prioridade:** P1 — desacopla integracao de logica.
- **Estimativa:** 3-5 dias

#### #1218 — Browser Use via CDP/Playwright
- **Modulo:** Novo modulo `src/browser_use/`
- **Escopo:** Controlar browser via Chrome DevTools Protocol (CDP) para automacao web. Implementar client CDP em Rust puro (websocket + JSON-RPC), suportar navegacao, click, fill, screenshot, e extracao de DOM.
- **Prioridade:** P1 — habilita agentes web.
- **Estimativa:** 5-8 dias

### Fase 3 — Validacao e skills (semanas 5-6)

#### #1219 — Benchmark suite contra OpenHands/Aider/claude-task-master
- **Modulo:** `src/benchmark_suite.rs`
- **Escopo:** Criar suite de benchmarks comparativos. Definir tarefas padrao (edit, multi-file refactor, bug fix, test generation), medir tempo/tokens/acuracia, e gerar relatorios comparativos.
- **Prioridade:** P2 — validacao, nao bloqueia funcionalidade.
- **Estimativa:** 3-5 dias

#### #1220 — Email agent skill
- **Modulo:** Novo modulo `src/skills/email_agent.rs`
- **Escopo:** Skill de agente de email: ler inbox (IMAP), classificar, responder com templates, encaminhar. Usar n8n backend (#1217) para envio real.
- **Prioridade:** P2 — primeiro skill concreto do novo runtime.
- **Estimativa:** 3-5 dias

## Dependencias entre sub-issues

```
#1215 (edit hardening) ──┐
                         ├──> #1216 (exec-graph) ──> #1219 (benchmark)
#1214 (MCP catalog) ─────┘         │
                                   ├──> #1220 (email agent)
#1217 (n8n backend) ───────────────┘
#1218 (browser use) ── independente, mas beneficia do exec-graph
```

## Criterios de aceitacao do epic

1. Todos os 7 sub-issues implementados e com `cargo check` passando
2. Benchmark suite rodando e gerando relatorio comparativo
3. Pelo menos 1 skill (email) funcional end-to-end
4. MCP catalog ingerindo tools de pelo menos 2 servidores MCP
5. Browser automation executando um fluxo web completo

## Riscos

- **CDP em Rust puro:** Complexidade do protocolo pode exigir crate externa (tokio-tungstenite para websocket)
- **n8n API:** Dependencia de instancia n8n rodando; precisa mock para testes
- **Benchmark fairness:** Comparacao com OpenHands/Aider requer ambiente controlado','docs/issues/1213-plan.md','7c5be35440fabf8d63ed2cb69d21d96edd7aab5597baab95b8833dda42c74043','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1214-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1214-evidence.md','doc: Issue #1214 — MCP catalog ingestion: Already Implemented','# Issue #1214 — MCP catalog ingestion: Already Implemented

## Evidence

### Schema and catalog (`src/mcp_catalog.rs`)

| Criterion | Location | Details |
|-----------|----------|---------|
| Catalog schema + version | line 733 | `MCP_CATALOG_SCHEMA`, `MCP_CATALOG_VERSION` embedded in JSON output |
| Embedded snapshot (30+ entries) | lines 69-689 | `npm_install!` macro entries for filesystem, github, slack, etc. |
| `search_mcp_catalog` | line 690 | Fuzzy search across catalog entries |
| `lookup_mcp_catalog` | line 706 | Exact-match lookup by name/id |
| `resolve_mcp_install` | line 710 | Returns install resolution with backend, command, args |
| `catalog_list` (JSON output) | line 726 | Lists all entries, supports `--json` flag |
| `catalog_search` (JSON output) | line 743 | Search with JSON output |
| `catalog_install` (dry-run) | line 765-790 | Install with `dry_run` field in output |
| `env_required` gating | line 27 | `env_required: &''static [&''static str]` field on install variants |
| X native MCP entries | `src/mcp_catalog.rs` (`xapi`, `x-docs`) | Official X API + docs entries, including `xurl` bridge args and first-run timeout guidance |
| Tests | line 895+ | `catalog_json_mentions_schema_and_version`, `resolve_mcp_install` tests |

### Subcommand wiring (`src/main.rs`)

| Criterion | Location | Details |
|-----------|----------|---------|
| `mod mcp_catalog` | line 82 | Module imported |
| `mcp catalog` subcommand | line 30173-30195 | Lists entries with optional category filter, JSON output |
| `mcp search` subcommand | line 30205-30220 | Searches catalog, JSON output |
| `mcp install` subcommand | line 30228-30234 | Resolves and installs, supports `--global`, `--dry-run`, `--json` |
| `mcp_catalog_install_entry` | line 29763 | Helper for install JSON output |
| `mcp_install_catalog_entry` | line 29791 | Full install flow with idempotent server registration |
| Remote MCP config materialization | `src/main.rs` (`mcp_catalog_install_entry`) | HTTP/SSE entries now write `url` + `type`; stdio entries can carry `startup_timeout_sec` and resolved env vars |

### Native X front door

The runtime now exposes a direct shortcut for the X integration:

- `simplicio x mcp install --dry-run --json` → installs the official `xapi` catalog entry
- `simplicio x docs --dry-run --json` → installs the hosted `x-docs` entry
- `simplicio x search --json` → searches the MCP catalog for X-related entries

This stays a thin alias over the native MCP catalog/install surface rather than
creating a second parallel integration path.

## Conclusion

All acceptance criteria (schema version, JSON output, dry-run, env_required gating, idempotent install) are fully covered by existing code.','docs/issues/1214-evidence.md','73201948218ed159cb1370035a53afcc834ab3368f0c229aba0c42e054b9eae8','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1215-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1215-evidence.md','doc: Issue #1215 — n8n como backend do Action Bridge','# Issue #1215 — n8n como backend do Action Bridge

**Status:** Already implemented.

## Evidence

### `src/n8n_bridge.rs`
- **Line 1:** Module header references `#1215 n8n workflow backend for the Action Bridge`.
- **Line 11:** Schema constant `N8N_SCHEMA = "simplicio.n8n-bridge/v1"`.
- **Line 28-55:** `build_payload()` — builds JSON payload for n8n webhook trigger with injection sanitization.
- **Line 57-120:** `trigger_webhook()` — fires HTTP POST to n8n webhook URL.
- **Line 124-147:** `run_workflow()` — public entry point with dry-run support and env-based config (`SIMPLICIO_N8N_WEBHOOK`). Returns honest error when env var is missing or empty.
- **Line 162-178:** Tests — `run_workflow_no_env_err` and `run_workflow_dry_run_no_network`.

### `src/action_bridge.rs`
- **Line 355:** `"workflow" | "n8n"` included in the mutating action set.
- **Line 471-476:** `--kind workflow|n8n` routes to `crate::n8n_bridge::run_workflow()`.

## Summary

The n8n backend for Action Bridge is fully wired: webhook payload building with sanitization, `run_workflow()` with dry-run, env-based config, honest errors, and tests.','docs/issues/1215-evidence.md','193d76347c42b85677c679aab6fea5db7a5e9efc77ffe03879fe04605ccf8c04','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1216-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1216-plan.md','doc: Issue #1216 — Browser Use como backend de computer-use','# Issue #1216 — Browser Use como backend de computer-use

## Status atual

O scaffolding principal ja existe em `src/computer_use.rs`:
- `BrowserBackend` enum (Playwright, BrowserUse, DryRun)
- `run_batch()` com dispatch para subprocessos
- `batch_to_json()` serializacao do plano
- `computer_use_command()` CLI handler
- `PostActionVerifier`, `ActionBatch`, `InterruptHandler`, `SmartWait` structs
- Testes unitarios para dry-run e serialization

## Lacunas identificadas

### Sub-issue 1: Runner scripts (prioridade alta)
**Arquivos a criar:**
- `scripts/browser_runner.js` — le o JSON do plano, executa via Playwright Node API
- `scripts/browser_use_runner.py` — le o JSON do plano, executa via browser-use Python lib

`run_batch()` ja espera esses scripts mas eles nao existem. Sem eles, os backends Playwright e BrowserUse retornam erro.

**Criterio de aceite:** `simplicio computer-use --backend playwright` e `--backend browser-use` executam o plano em um browser real.

### Sub-issue 2: Subcomando `computer-use backend status` (prioridade media)
**Arquivos a editar:**
- `src/computer_use.rs` — adicionar funcao `backend_status_command()`
- `src/main.rs` ou `src/tool_registry.rs` — adicionar match arm para `"backend"` como subcomando

Deve reportar: backend disponivel (npx/python no PATH), scripts presentes, versao do browser-use/playwright.

**Criterio de aceite:** `simplicio computer-use backend status --json` retorna JSON com disponibilidade de cada backend.

### Sub-issue 3: Action Gate para seguranca de mutacoes (prioridade alta)
**Arquivos a criar/editar:**
- `src/computer_use.rs` — adicionar `ActionGate` struct
- Integrar com `run_batch()` para bloquear acoes destrutivas sem confirmacao

Regras de seguranca:
- Links suspeitos (dominios desconhecidos em emails/mensagens)
- Deteccao de PII em campos de texto antes de enviar
- Bloqueio de acoes financeiras (submit de formularios de pagamento)
- Escalation para o usuario em casos ambiguos

**Criterio de aceite:** `run_batch()` recusa executar acoes marcadas como perigosas sem flag `--allow-mutations`.

### Sub-issue 4: PostActionVerifier e InterruptHandler conectados ao backend real (prioridade media)
**Arquivos a editar:**
- `src/computer_use.rs` — `verify_all()` e `handle_dialog()` precisam consultar o DOM real via o runner subprocess

Atualmente sao stubs (retornam `true` / primeiro option). Precisam enviar queries ao browser runner e parsear a resposta.

**Criterio de aceite:** `verify_all()` retorna resultado real do DOM. `handle_dialog()` interage com dialogs reais do browser.

### Sub-issue 5: Testes end-to-end (prioridade baixa)
**Arquivos a criar:**
- `tests/computer_use_e2e.rs` — testes com dry-run fixture
- `tests/fixtures/sample_plan.json` — plano de exemplo

**Criterio de aceite:** `cargo test` roda testes e2e com dry-run. Testes com backend real sao opcionais (requerem browser).

## Ordem de execucao recomendada

1. Sub-issue 1 (runner scripts) — desbloqueia tudo
2. Sub-issue 3 (Action Gate) — seguranca antes de uso real
3. Sub-issue 2 (backend status) — DX/observabilidade
4. Sub-issue 4 (verificacao real) — qualidade
5. Sub-issue 5 (testes e2e) — validacao final','docs/issues/1216-plan.md','75eb9b5f5b1472742f60dead83d9675bb5b414e3f1f8d17c91b86834a7c83ec7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1217-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1217-evidence.md','doc: Issue #1217 — Benchmark: OpenHands + Aider + claude-task-master','# Issue #1217 — Benchmark: OpenHands + Aider + claude-task-master

## Status: Already Implemented

## Evidence

### 1. Competitor detection (`src/hermes_parity_benchmark_agents.rs`)

Lines 212-214 — all three agents registered in `detect_competitors()`:
```
212: ("openhands", "openhands"),
213: ("aider", "aider"),
214: ("taskmaster", "task-master"),
```

Lines 361-363 — invocation match arms with proper CLI arguments:
```
361: "openhands" => run_external_benchmark("openhands", &["-m", "openhands.core.main", ...], &fixture),
362: "aider" => run_external_benchmark("aider", &["--yes", "--message", ...], &fixture),
363: "taskmaster" => run_external_benchmark("task-master", &["--task", ...], &fixture),
```

### 2. Agent runner (`src/hermes_parity_agent_runner.rs`)

Lines 146-147 — `WorkerKind` includes both agents:
```
146: "aider",
147: "openhands",
```

Lines 245-250 — `run_external` calls for each agent:
```
245: "aider" => run_external("aider", &["--yes", "--message", task], repo, start),
246: "openhands" => run_external("openhands", ..., "openhands.core.main", ...),
```

### 3. Dedicated skill module (`src/skill_openhands.rs`)

OpenHands has a dedicated 21-line skill module for integration.

## Conclusion

All three benchmark agents (OpenHands, Aider, claude-task-master) are fully wired into the benchmark infrastructure. No further code changes required.','docs/issues/1217-evidence.md','70c71a7f919e556c549b731b28aa1063c302cf0bd7337e2fd1a4a326f670c0ec','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1218-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1218-evidence.md','doc: Issue #1218: Aider search/replace + auto-commit — Evidence','# Issue #1218: Aider search/replace + auto-commit — Evidence

Status: **already implemented**

## 1. `apply_block` operation with unique-match semantics

- **src/main.rs:63917** — match arm for `"apply_block"` op
- **src/main.rs:63922** — validation: search must not be empty
- **src/main.rs:63928** — unique-match enforcement: exactly one match required
- **src/main.rs:85269** — test section header: `#1218: apply_block + CRLF preservation`
- **src/main.rs:85272** — test `edit_apply_block_replaces_exactly_one_match`
- **src/main.rs:85281** — test `edit_apply_block_errors_on_zero_matches`

## 2. `--commit` flag for auto-commit after edit

- **src/main.rs:3805** — CLI parse: `"--commit" => cli.edit_commit_message = ...`
- **src/main.rs:64478** — guard: `"--commit requested but edit made no changes"`
- **src/main.rs:71295-71297** — usage/help text showing `--commit <msg>`

## 3. `--review` flag (dry-run review mode)

- **src/main.rs:3804** — CLI parse: `"--review" => cli.edit_review = true`
- **src/main.rs:85363** — test: `#1218: --review must not write the file`
- **src/main.rs:96332** — test: `#1218: --review must not write the file (--review implies --dry-run)`','docs/issues/1218-evidence.md','8849eb2eaf95d5da289525e3bb660479fb71e477d4cf5ede26a453755f0f0b9d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1219-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/1219-evidence.md','doc: Issue #1219 — LangGraph/CrewAI: exec-graph runtime','# Issue #1219 — LangGraph/CrewAI: exec-graph runtime

**Status:** Already implemented.

## Evidence

### 1. `exec_graph_run` with `--spec` and `--resume`
- `src/exec_graph_runtime.rs:863` — `pub fn exec_graph_run(args: Vec<String>)`
- `src/exec_graph_runtime.rs:615` — `--spec` flag parsing
- `src/exec_graph_runtime.rs:611` — `--resume` flag parsing

### 2. Conditional edges (OnSuccess / OnFailure / Always)
- `src/exec_graph.rs:21-27` — `EdgeCondition` enum with `Always`, `OnSuccess`, `OnFailure`
- `src/exec_graph.rs:53-58` — `EdgeCondition` match logic
- `src/exec_graph.rs:745` — test `conditional_edges_route_on_success_and_failure`

### 3. Checkpoint/resume persists state
- `src/exec_graph_runtime.rs:51` — state dir at `.simplicio-loop/exec-graph`
- `src/exec_graph_runtime.rs:8-10` — schemas for run, state, and current

### 4. Role/goal fields on ExecGraphNodeSpec
- `src/exec_graph_runtime.rs:16-17` — `role` and `goal` fields
- `src/exec_graph_runtime.rs:198-202` — rendered into node prompts

### 5. exec_graph_status implemented
- No "not implemented" string found in `exec_graph_runtime.rs`

### 6. Dispatch routing
- `src/main.rs:2201` — `"exec-graph" => exec_graph_runtime::exec_graph_command(args)`
- Sub-commands: run, status, define, validate, dot','docs/issues/1219-evidence.md','1fd102b0d7c775601e3ec852120354bcad74675f138df00f44222bcee28a2ac6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1238-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1238-plan.md','doc: Epic #1238: Velocidade, tokens e determinismo','# Epic #1238: Velocidade, tokens e determinismo

## Objetivo
Garantir que o Simplicio Runtime otimize velocidade de resposta, minimize consumo de tokens e maximize determinismo de saída, com infraestrutura de benchmark, controle de custo e políticas operacionais.

---

## Sub-issues

### 1. Case Study: Benchmark de Latência e Throughput
**Arquivo:** `docs/case-study-speed-tokens-determinism.md`
- Documentar cenários reais de uso (L0 template routing, memo routing, tool dispatch)
- Medir latência p50/p95/p99 e tokens por request
- Comparar antes/depois de otimizações

### 2. Política Operacional no Manual
**Arquivo:** `docs/SIMPLICIO_OPERATIONAL_MANUAL.md`
- Adicionar seção "Velocidade, Tokens e Determinismo"
- Definir SLOs: latência máxima por tier (L0 < 200ms, L1 < 2s, L2 < 30s)
- Política de token budget por request (max tokens in/out por tier)
- Regras de fallback quando budget é excedido

### 3. Regras em AGENTS.md e CLAUDE.md
**Arquivos:** `AGENTS.md`, `CLAUDE.md`
- Regras de determinismo: seed fixo, temperature=0 para L0
- Token budget awareness para agentes
- Benchmark obrigatório antes de merge em hot path

### 4. Módulo Rust L0 Template/Memo Router
**Arquivos novos:**
- `src/htool_l0_template_router.rs` — roteamento determinístico sem LLM
- `src/htool_l0_memo_router.rs` — memoização de respostas
- `src/l0_schema.json` — schema JSON para templates L0
- Integrar em `src/main.rs` e `src/tool_registry.rs`

### 5. Integração Benchmark Suite + Cost Ledger
**Arquivos existentes:** `src/benchmark_suite.rs`, `src/benchmark_harness.rs`, `src/cost_ledger.rs`
- Benchmarks para L0 router, harness de determinismo, tracking de token savings

## Ordem de execução
1. Sub-issue 3 → 2 → 4 → 5 → 1','docs/issues/1238-plan.md','a8a308eb9d2449ddd9fe82f1a0a0edf5906a23227f6f9775493ad20a011b582e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1243-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1243-plan.md','doc: Epic #1243 — Benchmark/Ledger: L0 vs NO-THINK vs THINK','# Epic #1243 — Benchmark/Ledger: L0 vs NO-THINK vs THINK

## Overview

Extend the benchmark harness and cost ledger to support routing-aware benchmarking across three tiers: L0 (local/cached), LLM NO-THINK (budget mode), and LLM THINK (extended thinking). This enables measuring cost savings and quality tradeoffs per routing decision.

Depends on: #1242 (routing infrastructure).

---

## Sub-issue 1: BenchmarkRow with routing fields

**Files:** `src/benchmark_suite.rs` (new)

- Create `BenchmarkRow` struct with fields:
  - `task_id`, `agent`, `route` (enum: L0Hit, L0Miss, LlmNoThink, LlmThink)
  - `resolved: bool`, `iterations: u32`, `wall_clock_ms: u64`
  - `tokens_input: u64`, `tokens_output: u64`, `tokens_remote: u64`
  - `deterministic: bool`, `cost_usd: f64`
- Implement `serde::Serialize` / `serde::Deserialize` for BenchmarkRow.
- Add `BenchmarkRoute` enum with Display/FromStr.
- Unit tests for serialization round-trip.

**Estimate:** Small (1 PR)

---

## Sub-issue 2: Benchmark harness with L0/LLM scenarios

**Files:** `src/benchmark_harness.rs` (extend existing), `examples/` (fixtures)

- Add scenario definitions for:
  - L0 HIT: task resolved from local cache/deterministic template, zero remote tokens.
  - L0 MISS: cache miss, falls through to LLM.
  - LLM NO-THINK: remote call without extended thinking.
  - LLM THINK: remote call with extended thinking enabled.
- Create fixture files in `examples/benchmark_fixtures/` with representative inputs.
- Each scenario produces a `BenchmarkRow`.
- Add `deterministic` flag to `HarnessTask`.
- Integration tests that run each scenario with mock data and assert BenchmarkRow correctness.

**Estimate:** Medium (1-2 PRs)

---

## Sub-issue 3: DeterministicTemplate mechanism in cost_ledger

**Files:** `src/cost_ledger.rs`

- Add `Mechanism::DeterministicTemplate` variant to the enum.
- Update `as_str()` / `FromStr` to handle `"deterministic_template"`.
- Update `SavingsEntry` serialization/deserialization.
- Update `SavingsReport` aggregation to include the new mechanism.
- Unit tests: ledger append/read round-trip with the new mechanism.

**Estimate:** Small (1 PR)

---

## Sub-issue 4: savings-report schema and report generator

**Files:** `schemas/savings-report.schema.json` (new), `src/cost_ledger.rs` (extend)

- Create JSON Schema for savings reports:
  - Per-mechanism breakdown (cache, dedup, windowing, deterministic_template).
  - Per-route breakdown (L0 hit/miss, no-think, think).
  - Totals: tokens_saved, estimated_cost_saved_usd.
  - Metadata: period, session_count.
- Add `generate_savings_report()` function to cost_ledger that reads the JSONL ledger and produces a report conforming to the schema.
- Validate output against schema in tests.

**Estimate:** Medium (1 PR)

---

## Execution order

1. Sub-issue 3 (DeterministicTemplate in ledger) — no dependencies
2. Sub-issue 1 (BenchmarkRow) — no dependencies
3. Sub-issue 4 (savings-report schema) — depends on sub-issue 3
4. Sub-issue 2 (harness scenarios) — depends on sub-issues 1 and 3

## Acceptance criteria

- `cargo check` and `cargo test` pass with all new code.
- Each routing tier (L0 HIT, L0 MISS, NO-THINK, THINK) has at least one benchmark fixture.
- Cost ledger supports `deterministic_template` mechanism end-to-end.
- `savings-report.schema.json` validates generated reports.
- No `.unwrap()` in production paths; all errors use `Result`.','docs/issues/1243-plan.md','4112180a54a1b59548b32c0e7c50a818cd41a44ccb49aadf6f8b1a00f6eb2dd6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1244-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1244-plan.md','doc: Epic #1244 — Fork Hermes into Simplicio Desktop','# Epic #1244 — Fork Hermes into Simplicio Desktop

## Overview

Decomposition of the Hermes-to-Simplicio Desktop fork into concrete, independently deliverable workstreams.
The desktop seed already exists at `apps/desktop/` but most Definition-of-Done items remain incomplete.

---

## Workstream 1 — Brand Cleanup (Hermes Reference Removal)

**Goal:** Remove all remaining Hermes references (24+ across 9 files) and replace with Simplicio branding.

**Files:**
- `apps/desktop/src/pages/Settings.tsx`
- `apps/desktop/src/pages/Dashboard.tsx`
- `apps/desktop/src/pages/Agents.tsx`
- `apps/desktop/src/components/Layout.tsx`
- `apps/desktop/src/components/Onboarding.tsx`
- `apps/desktop/src/lib/runtime.ts`
- `apps/desktop/src/pages/History.tsx`
- `apps/desktop/src/pages/Logs.tsx`
- `apps/desktop/src/pages/Yool.tsx`

**Tasks:**
1. Search-and-replace all `Hermes` / `hermes` strings with `Simplicio` / `simplicio`.
2. Update logos, icons, and any asset references.
3. Update `package.json` name, description, and metadata.
4. Update Tauri config (`tauri.conf.json`) with Simplicio identifiers.
5. Update window titles, about dialogs, and user-visible strings.

---

## Workstream 2 — License and Third-Party Notices

**Goal:** Create `THIRD_PARTY_NOTICES.md` and ensure license compliance.

**Tasks:**
1. Audit all dependencies (npm + Cargo) for license types.
2. Generate `THIRD_PARTY_NOTICES.md` with attribution for each dependency.
3. Verify Hermes original license allows forking; add attribution if required.
4. Add license headers to new source files.

---

## Workstream 3 — Runtime Bridge to Simplicio CLI

**Goal:** Wire `apps/desktop/src/lib/runtime.ts` to invoke the `simplicio` CLI binary.

**Tasks:**
1. Define Tauri commands in `src-tauri/src/main.rs` to spawn/manage `simplicio` CLI process.
2. Implement IPC protocol between frontend and CLI (stdin/stdout JSON-RPC or similar).
3. Handle CLI lifecycle: start, stop, restart, health-check.
4. Surface CLI version and status in the UI.

---

## Workstream 4 — Token Savings Dashboard

**Goal:** Build a dashboard showing token usage and cost savings from Simplicio optimizations.

**Tasks:**
1. Define data model for token usage tracking (per-session, per-agent, cumulative).
2. Create backend storage (local SQLite or JSON file via Tauri).
3. Build `Dashboard.tsx` charts: tokens saved, cost saved, usage over time.
4. Add real-time counters updated during active sessions.

---

## Workstream 5 — Entitlement and Paywall Gating (Pro/Team/Enterprise)

**Goal:** Gate features behind subscription tiers.

**Tasks:**
1. Define tier matrix: Free vs Pro vs Team vs Enterprise feature sets.
2. Implement entitlement check module (`lib/entitlements.ts`).
3. Add UI gates: disabled states, upgrade prompts, tier badges.
4. Persist entitlement state locally with JWT validation.

---

## Workstream 6 — Stripe Integration

**Goal:** Connect subscription management to Stripe.

**Tasks:**
1. Set up Stripe product/price catalog for Simplicio Desktop tiers.
2. Implement Stripe Checkout flow (open browser to hosted checkout).
3. Handle webhook or polling for subscription status updates.
4. Integrate with entitlement module from Workstream 5.
5. Add billing management page in Settings.

---

## Workstream 7 — BYOK (Bring Your Own Key) Provider Config

**Goal:** Let users configure their own API keys for LLM providers.

**Tasks:**
1. Add BYOK settings UI in `Settings.tsx` (fields for OpenAI, Anthropic, etc.).
2. Secure storage of API keys via Tauri keychain/credential store.
3. Runtime key resolution: BYOK key > platform key > error.
4. Key validation on save (test API call).

---

## Workstream 8 — Build, Signing, and Update Pipeline

**Goal:** Multi-platform build and distribution (Windows, macOS, Linux).

**Tasks:**
1. Configure Tauri build scripts for all three platforms.
2. Set up code signing (Windows Authenticode, macOS notarization).
3. Implement auto-update via Tauri updater plugin.
4. Create CI/CD pipeline (GitHub Actions) for release builds.
5. Set up distribution: GitHub Releases, optional installer hosting.

---

## Workstream 9 — Security Hardening

**Goal:** Harden the desktop app against common attack vectors.

**Tasks:**
1. Audit Tauri CSP (Content Security Policy) configuration.
2. Restrict IPC commands to minimum required surface.
3. Sanitize all user inputs passed to CLI or shell.
4. Enable Tauri isolation pattern.
5. Add integrity checks for CLI binary.

---

## Workstream 10 — QA and Evidence Matrix

**Goal:** Create a test plan and evidence matrix proving all DoD items are met.

**Tasks:**
1. Define acceptance criteria per workstream.
2. Create manual test scripts for each user flow.
3. Add automated tests where feasible (unit + integration).
4. Build evidence matrix document mapping DoD items to test results.

---

## Workstream 11 — Onboarding and Pricing UX

**Goal:** First-run experience and pricing page.

**Tasks:**
1. Design and implement onboarding flow in `Onboarding.tsx`.
2. Show feature highlights and tier comparison.
3. Guide user through initial setup (CLI detection, API key config).
4. Add in-app pricing page with tier comparison and upgrade CTA.

---

## Workstream 12 — Recurring Hermes Sync Pipeline

**Goal:** Establish a process to pull upstream Hermes improvements.

**Tasks:**
1. Document the fork relationship and upstream remote setup.
2. Create a sync script that fetches upstream, identifies relevant changes.
3. Define merge policy (cherry-pick vs rebase vs manual review).
4. Schedule periodic sync checks (monthly or per-release).
5. Document conflict resolution procedures.

---

## Dependency Graph

```
Workstream 1 (Brand Cleanup) — no dependencies, start first
Workstream 2 (License) — no dependencies, start first
Workstream 3 (Runtime Bridge) — no dependencies, start first
Workstream 4 (Savings Dashboard) — depends on 3 (needs runtime data)
Workstream 5 (Entitlements) — no dependencies
Workstream 6 (Stripe) — depends on 5
Workstream 7 (BYOK) —','docs/issues/1244-plan.md','1cba70a91fa567ddd28b84bd95ea1c521f6df19107c56fc5eee1815ebabadbb5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1247-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1247-plan.md','doc: Issue #1247 — [Simplicio Desktop] Replace Hermes backend with runtime bridge','# Issue #1247 — [Simplicio Desktop] Replace Hermes backend with runtime bridge

## Overview

Replace all Hermes backend calls in the Simplicio Desktop (Tauri) app with a runtime bridge that supports three communication modes and includes security, UX states, and tests.

## Current State

- `apps/desktop/src/lib/runtime.ts` already has ~30 Tauri invoke commands (foundation partially in place)
- Hermes references remain across 8+ UI files
- No HTTP or MCP bridge modes exist
- No security allowlist, secret redaction, or bridge tests

## Sub-issues

### Sub-1: HTTP bridge serve mode
**Files:** `src/transport_mcp_bridge.rs`, `apps/desktop/src/lib/runtime.ts`
- Add an HTTP server mode (e.g., `hyper` or `tiny_http`) that exposes the same command set as JSON-RPC or REST endpoints
- Runtime bridge in TS selects HTTP mode when Tauri invoke is unavailable
- Health check endpoint at `/health`

### Sub-2: MCP stdio bridge serve mode
**Files:** `src/transport_mcp_bridge.rs`, `src/main.rs`
- Implement MCP stdio transport (JSON-RPC over stdin/stdout)
- Allow the desktop app to spawn the runtime binary and communicate via stdio
- Handle message framing and error responses

### Sub-3: Wire remaining CLI commands with --json
**Files:** `src/main.rs`, `apps/desktop/src/lib/runtime.ts`
- Wire these CLI commands that are not yet connected:
  - `doctor` — system diagnostics
  - `runtime map` — runtime topology
  - `savings report` — cost/savings data
  - `license status` — license info
  - `evidence show` — evidence/audit trail
- All commands must support `--json` flag for structured output
- Add corresponding Tauri invoke handlers and TS functions

### Sub-4: Runtime discovery UX states
**Files:** `apps/desktop/src/components/Onboarding.tsx`, `apps/desktop/src/components/Layout.tsx`, `apps/desktop/src/pages/Dashboard.tsx`
- Detect runtime status: missing, stale (outdated version), blocked (permission/firewall), healthy
- Show appropriate UX for each state:
  - Missing: install CTA with download link
  - Stale: update CTA with changelog
  - Blocked: troubleshooting guide
  - Healthy: normal operation
- Periodic health polling (every 30s)

### Sub-5: Security allowlist and redaction layer
**Files:** `apps/desktop/src/lib/runtime.ts`, `src/main.rs`
- Command allowlist: only permitted commands can be invoked through the bridge
- Structured renderer requests: validate command shape before execution
- Secret redaction: strip API keys, tokens, passwords from logs and responses
- Configuration file for allowlist rules

### Sub-6: Bridge unit tests
**Files:** new test files in `apps/desktop/src/__tests__/` and `src/` (Rust tests)
- Unit tests for each bridge mode (Tauri invoke, HTTP, MCP stdio)
- Test command serialization/deserialization
- Test security layer (allowlist enforcement, redaction)
- Test fallback logic (Tauri -> HTTP -> CLI)
- Test UX state detection

### Sub-7: Remove Hermes copy from UI
**Files:** `apps/desktop/src/pages/Agents.tsx`, `apps/desktop/src/pages/Settings.tsx`, `apps/desktop/src/pages/Dashboard.tsx`, `apps/desktop/src/pages/History.tsx`, `apps/desktop/src/pages/Logs.tsx`, `apps/desktop/src/pages/Yool.tsx`, `apps/desktop/src/components/Onboarding.tsx`, `apps/desktop/src/components/Layout.tsx`
- Find and replace all ~25 Hermes references in UI copy
- Replace with "Simplicio Runtime" or appropriate branding
- Update tooltips, error messages, and documentation links

## Suggested Order

1. Sub-7 (Hermes removal — low risk, immediate cleanup)
2. Sub-3 (wire CLI commands — foundational)
3. Sub-1 (HTTP bridge)
4. Sub-2 (MCP bridge)
5. Sub-5 (security layer)
6. Sub-4 (UX states)
7. Sub-6 (tests — after all features land)','docs/issues/1247-plan.md','67ebcdad9f562f9532d9d9d3997f6f2653bc3362f52c28c582c36b528eef84a5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1248-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1248-plan.md','doc: Plan: #1248 - [Simplicio Desktop] Token Savings Dashboard','# Plan: #1248 - [Simplicio Desktop] Token Savings Dashboard

## Overview

This epic covers building a full desktop application UI for the Token Savings Dashboard, including a new ledger persistence layer, UI component library, and integration with the existing CLI savings report JSON output.

## Current State

- `src/main.rs` has `savings_dashboard_command`, JSON, and markdown output functions
- `src/cost_ledger.rs` has the cost ledger logic for tracking token usage and savings
- `site/assets/js/i18n.js` has internationalization support
- No `apps/simplicio-desktop` directory exists yet

## Sub-issues / Work Items

### 1. Desktop App Scaffold (Tauri)
- **Files:** `apps/simplicio-desktop/` (new directory tree)
- Create Tauri project with Rust backend and web frontend
- Configure build pipeline, dev server, auto-updater stub
- **Estimate:** 2-3 days

### 2. Desktop Token Ledger Schema (`desktop-token-ledger/v1`)
- **Files:** `src/desktop_ledger.rs` (new), `src/schema/desktop_token_ledger_v1.rs` (new)
- Define new schema distinct from `savings-report/v1`
- Fields: run_id, timestamp, model, input_tokens, output_tokens, cached_tokens, saved_tokens, saved_dollars, strategy_used, is_optimized
- SQLite or JSON-file persistence for offline operation
- **Estimate:** 1-2 days

### 3. Dashboard Cards UI Components
- **Files:** `apps/simplicio-desktop/src/components/` (new)
- Cards: Saved Tokens (total), Dollars Saved, Savings Percentage, Runs Optimized, Best Strategy
- Responsive layout, theme support (light/dark)
- Use CSS variables for theming consistency with site
- **Estimate:** 2-3 days

### 4. Pro Upsell Locked Cards
- **Files:** `apps/simplicio-desktop/src/components/pro_cards.rs` or `.tsx` (new)
- Show locked/blurred cards for Pro-only metrics
- CTA button linking to upgrade flow
- Detect license tier from config
- **Estimate:** 1 day

### 5. Empty / First-Run State
- **Files:** `apps/simplicio-desktop/src/components/empty_state.rs` or `.tsx` (new)
- Welcome screen when no ledger data exists
- Quick-start guide pointing to CLI usage
- **Estimate:** 0.5 days

### 6. Offline Operation
- **Files:** `src/desktop_ledger.rs`, `apps/simplicio-desktop/src/service/sync.rs` (new)
- All dashboard data reads from local SQLite/JSON ledger
- No network required for viewing dashboard
- Optional sync when online
- **Estimate:** 1 day

### 7. Markdown Export
- **Files:** `apps/simplicio-desktop/src/export.rs` (new)
- Export button that generates markdown matching displayed totals
- Reuse/align with existing `savings_dashboard_markdown()` in `main.rs`
- Ensure totals match exactly what the UI shows
- **Estimate:** 0.5 days

### 8. Integration with CLI Savings Report
- **Files:** `src/cost_ledger.rs`, `src/desktop_ledger.rs` (new)
- Parse existing `savings-report/v1` JSON output from CLI
- Transform into `desktop-token-ledger/v1` format
- Watch for new report files or accept piped input
- **Estimate:** 1 day

### 9. i18n for Desktop
- **Files:** `site/assets/js/i18n.js`, `apps/simplicio-desktop/src/i18n/` (new)
- Extend existing i18n with desktop-specific keys
- Support pt-BR and en-US at minimum
- **Estimate:** 1 day

### 10. UI Tests
- **Files:** `apps/simplicio-desktop/tests/` (new)
- Unit tests for ledger schema serialization/deserialization
- Component tests for dashboard cards (empty, populated, locked states)
- Integration test: CLI report -> ledger -> dashboard render
- **Estimate:** 2 days

## Dependency Graph

```
1 (Scaffold) --> 3 (Cards UI)
                 3 --> 4 (Pro Cards)
                 3 --> 5 (Empty State)
2 (Ledger Schema) --> 8 (CLI Integration)
                      8 --> 6 (Offline)
                      8 --> 7 (Markdown Export)
1 + 9 (i18n) --> 3
All --> 10 (Tests)
```

## Total Estimate

~12-15 days of development effort.

## Risks

- Tauri vs Electron decision impacts build complexity and binary size
- Desktop app distribution (signing, notarization) adds overhead
- Keeping markdown export totals in sync with UI requires shared calculation logic','docs/issues/1248-plan.md','6120168591e68bca4dc04d3167f1c46742e74d11f245c1e257fb2f0e7149532a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1249-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1249-plan.md','doc: Epic #1249 — Module Catalog with Locked Capabilities','# Epic #1249 — Module Catalog with Locked Capabilities

Parent epic: #1244

## Overview

Build a module catalog UI for Simplicio Desktop that displays available modules as cards with visual states reflecting the user''s entitlement tier. Modules that exceed the user''s plan are shown as locked and cannot be executed.

## Decomposition

### Sub-task 1: Extend entitlement schema with per-module plan gates

**Files:** `schemas/entitlement.schema.json`

- Add `tier` enum: `free`, `pro`, `team`, `enterprise`
- Add per-module `required_tier` field
- Add module state enum with seven values: `active`, `locked`, `trial`, `unavailable`, `configured`, `blocked`, `pending`
- Add `module_entitlements` map (module_id -> required_tier + state overrides)

### Sub-task 2: Create desktop app scaffold

**Files:** `apps/simplicio-desktop/` (new)

- Initialize Tauri or similar desktop app structure
- Set up basic window with TUI-like rendering
- Wire up to existing `simplicio-runtime` as a library dependency

### Sub-task 3: Build module catalog UI with card components

**Files:** `apps/simplicio-desktop/src/catalog.rs` (new), `src/tui_app.rs`

- Module card component showing: name, description, tier badge, state indicator
- Visual differentiation for each of the 7 states (color, icon, lock overlay)
- Grid/list layout for browsing modules
- Filter/search by name, tier, state
- Detail view on card selection

### Sub-task 4: Implement locked-execution prevention

**Files:** `src/tool_registry.rs`, `src/policy_engine.rs`, `src/license.rs`

- `license.rs`: Add `current_tier()` and `check_module_entitlement(module_id) -> ModuleState`
- `policy_engine.rs`: Add policy rule that blocks execution when module state is `locked`, `unavailable`, or `blocked`
- `tool_registry.rs`: Before dispatching a tool call, query entitlement state; return structured error with upgrade prompt if denied
- Return user-friendly message explaining why execution was blocked and how to upgrade

### Sub-task 5: Add mock entitlement state switching

**Files:** `src/license.rs`, `src/tui_app.rs`

- In-memory entitlement store that can be toggled at runtime
- TUI command or key binding to cycle through tiers (free -> pro -> team -> enterprise)
- Immediate UI refresh when tier changes to show modules locking/unlocking
- Useful for development, demos, and testing

### Sub-task 6: Write UI and integration tests

**Files:** `tests/` (new test files)

- Unit tests for entitlement resolution logic (given tier X, module Y requires Z -> state)
- Unit tests for policy engine blocking locked modules
- Integration test: register module with tier gate, switch tier, verify execution allowed/denied
- UI snapshot tests for card states (if using a testable TUI framework)

## Implementation Order

1. Sub-task 1 (schema) — no dependencies
2. Sub-task 4 (execution prevention) — depends on schema
3. Sub-task 5 (mock switching) — depends on execution prevention
4. Sub-task 2 (desktop scaffold) — can parallel with 4-5
5. Sub-task 3 (catalog UI) — depends on scaffold + schema
6. Sub-task 6 (tests) — after each sub-task, but final pass at end

## Notes

- Use only `std`, `serde`, `serde_json` — no additional dependencies
- No `.unwrap()` in production code; use `Result` propagation throughout
- Each sub-task should be a separate PR for reviewability','docs/issues/1249-plan.md','e53d36427789c6f22c45a3c9110c933a5b0cb886d4fe78b9de2ece7a372ba1fa','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1250-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1250-plan.md','doc: Epic #1250: Simplicio Desktop - Stripe/Gmail Entitlement Activation','# Epic #1250: Simplicio Desktop - Stripe/Gmail Entitlement Activation

## Current State

- **license.rs**: Offline ed25519-signed license verification with 4 tiers (free/trial/economy/pro), grace period support, local file-based storage.
- **growth_stripe.rs**: Stripe checkout session creation, customer portal, subscription funnel via curl-based REST calls.
- **entitlement.schema.json**: Contract defining entitlement policy with Google/Gmail identity, Stripe subscription check, and enforcement fields.
- **site/api/entitlement.php**: Backend endpoint serving subscription status by email.
- **site/api/stripe-checkout.php** / **stripe-sync.php**: Backend Stripe integration.
- **Desktop app directory** (`apps/simplicio-desktop`): Does not exist yet.

## Dependencies

- **#1164**: Backend entitlement API (must be stable before desktop consumes it)
- **#1191**: Stripe webhook license minting (must be in place for paid tiers)

## Decomposition

### Sub-issue 1: Expand license.rs tier model to 8 entitlement states

**Scope**: Extend the current 4-tier enum (`Free/Trial/Economy/Pro`) to support the 8 states required by the desktop app.

**Files**: `src/license.rs`

**Work**:
- Add `EntitlementState` enum: `Free`, `Trial`, `ProActive`, `TeamActive`, `EnterpriseActive`, `Expired`, `OfflineGrace`, `Blocked`
- Add mapping from `(Tier, subscription_status, grace_flag)` -> `EntitlementState`
- Add `--json` output to `simplicio license status` command
- Add serialization for the new states
- Unit tests for all state transitions

**Depends on**: None (can start immediately)

---

### Sub-issue 2: Offline grace with cached signed entitlement

**Scope**: Implement cached entitlement storage so the desktop app works offline.

**Files**: `src/license.rs`, new `src/entitlement_cache.rs`

**Work**:
- Create `EntitlementCache` struct that stores a signed entitlement snapshot to `~/.simplicio-loop/entitlement.cache`
- Implement cache validation (check ed25519 signature, check expiry + grace window)
- Transition to `OfflineGrace` state when cache is valid but network is unavailable
- Transition to `Blocked` when cache has expired beyond grace period
- Define `OFFLINE_GRACE_HOURS` constant (e.g. 72h)
- Tests for cache write/read/expiry/grace scenarios

**Depends on**: Sub-issue 1

---

### Sub-issue 3: Desktop entitlement adapter (CLI bridge)

**Scope**: Create the adapter layer that the desktop app (Electron/Tauri) calls to get entitlement status.

**Files**: New `apps/simplicio-desktop/src/entitlement_adapter.ts` (or Rust if Tauri), `src/license.rs`

**Work**:
- Implement adapter that shells out to `simplicio license status --json` and parses the result
- Map the 8 `EntitlementState` values to UI-facing module lock/unlock decisions
- Hot-reload support: file-watch on `~/.simplicio-loop/entitlement.cache` to detect changes without app restart
- IPC channel from main process to renderer for state updates
- Ensure no secrets (Stripe key, signing key) are accessible in renderer process
- Integration test: mock CLI output and verify adapter produces correct UI state

**Depends on**: Sub-issues 1, 2

---

### Sub-issue 4: Google/Gmail login integration

**Scope**: Add Google OAuth login flow to the desktop app for user identification.

**Files**: New desktop auth module, `schemas/entitlement.schema.json` (if updates needed)

**Work**:
- Implement OAuth 2.0 PKCE flow for Google sign-in (desktop app context)
- Store Gmail email locally for Stripe customer matching (`customer_match: "google_gmail_email"`)
- No tokens stored in renderer process; main process handles OAuth token refresh
- Wire login state to entitlement check: after login, trigger `simplicio license status --email <gmail>`
- Logout clears cached entitlement and reverts to `Free` state
- Tests for OAuth flow (mock Google endpoints)

**Depends on**: Sub-issue 3

---

### Sub-issue 5: Desktop UI - locked module cards and checkout flow

**Scope**: Build the UI that shows module access based on entitlement state.

**Files**: New desktop UI components

**Work**:
- Module card component with locked/unlocked/trial states
- Visual indicators for each of the 8 entitlement states
- "Upgrade" button opens Stripe checkout (via `simplicio growth checkout` or direct Stripe Checkout redirect)
- "Manage subscription" button opens Stripe customer portal (via `simplicio growth portal`)
- Toast/banner for grace period warnings ("X hours remaining offline")
- Toast for state transitions (e.g. "Subscription renewed" after hot-reload detects change)
- Responsive layout for module grid

**Depends on**: Sub-issues 3, 4

---

### Sub-issue 6: Platform tests and CI

**Scope**: End-to-end and platform-specific testing.

**Work**:
- Unit tests for all new Rust code (`cargo test`)
- Integration test: full flow from Google login -> entitlement check -> module unlock
- Platform tests: Windows, macOS, Linux (at minimum the Rust CLI layer)
- Test offline scenarios: disconnect network, verify grace -> blocked transition
- Test hot-reload: update cache file while app is running, verify UI updates
- CI pipeline additions for desktop build artifacts

**Depends on**: All previous sub-issues

## Suggested Execution Order

```
Sub-issue 1 (tier model)
    |
    v
Sub-issue 2 (offline cache)
    |
    v
Sub-issue 3 (desktop adapter) <-- can start scaffold in parallel with 1-2
    |
    +-----> Sub-issue 4 (Google login)
    |            |
    v            v
Sub-issue 5 (UI) ----------> Sub-issue 6 (tests)
```

## Risk Notes

- Desktop framework choice (Electron vs Tauri) is not yet decided; sub-issues 3-5 may need adjustment.
- Google OAuth requires a registered OAuth client ID; this is a configuration dependency.
- Stripe webhook reliability for license minting (#1191) is critical path for paid tiers.','docs/issues/1250-plan.md','56f962749ab48985f216d31e2da9a5bd6f7a358580d45797b631d6789bd2218d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1251-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1251-plan.md','doc: Epic #1251: Multi-source trend research agent','# Epic #1251: Multi-source trend research agent

## Overview

Add a `simplicio research <topic>` CLI command that fans out queries to multiple platform adapters in parallel, merges/dedupes results, ranks by signal weight, and persists findings via neural memory.

## Sub-issues

### 1. CLI command + schema (`research` subcommand)
- Add `research` subcommand to CLI parser in `src/main.rs`
- Define `ResearchRequest` / `ResearchResult` structs (topic, sources, time range, max results)
- Wire to tool registry in `src/tool_registry.rs`
- **Files:** `src/main.rs`, `src/tool_registry.rs`, new `src/cmd_research.rs`

### 2. Platform adapter trait
- Define `trait PlatformAdapter` with async methods: `search(query, params) -> Vec<Signal>`, `name() -> &str`, `is_available() -> bool`
- Define `Signal` struct: source, url, title, snippet, timestamp, engagement metrics, raw json
- **Files:** new `src/research_adapter.rs`

### 3. Individual platform adapters (one sub-issue each)
Each adapter implements the `PlatformAdapter` trait.

| # | Adapter | Data source | Key signals |
|---|---------|-------------|-------------|
| 3a | Reddit | Reddit search API / web extract | upvotes, comments, subreddit relevance |
| 3b | X (Twitter) | X search API / web extract | likes, retweets, quote count |
| 3c | YouTube | YouTube search / web extract | views, like ratio, recency |
| 3d | Hacker News | HN Algolia API | points, comment count |
| 3e | TikTok | TikTok web search / extract | views, shares, hashtag volume |
| 3f | Polymarket | Polymarket API | volume, probability, market activity |
| 3g | GitHub | GitHub search API | stars, forks, recent activity |

- **Files:** new `src/research_adapter_reddit.rs`, `..._x.rs`, `..._youtube.rs`, `..._hn.rs`, `..._tiktok.rs`, `..._polymarket.rs`, `..._github.rs`

### 4. Fan-out / merge engine
- Spawn one tokio task per enabled adapter via `tokio::JoinSet`
- Collect results with timeout per adapter (default 15s)
- Deduplicate by URL normalization
- Rank by configurable signal weights (engagement, recency, source authority)
- Return top-N merged `Signal` list
- **Files:** new `src/research_engine.rs`

### 5. Neural memory integration
- After merge, persist research results to neural memory store
- Tag with topic, timestamp, source breakdown
- Support incremental updates (diff against previous research on same topic)
- **Files:** modifications to existing memory modules, new `src/research_memory.rs`

## Dependencies

- Existing `web_search` tool (`src/tools_web_search.rs`) as fallback search provider
- Existing `tools_web_extract` for HTML extraction from platform pages
- `tokio` for parallel fan-out
- `serde` / `serde_json` for serialization

## Suggested implementation order

1. Sub-issue 2 (trait) — foundation for everything
2. Sub-issue 1 (CLI + schema) — wire the command
3. Sub-issue 3d (HN adapter) — simplest API, good for validation
4. Sub-issue 4 (fan-out engine) — core orchestration
5. Sub-issues 3a-3c, 3e-3g (remaining adapters) — can be parallelized
6. Sub-issue 5 (memory integration) — final layer

## Estimated effort

~5-7 sub-issues, each 1-3 hours of implementation work.','docs/issues/1251-plan.md','d56d4bf5719e428e846809d0c413c5fd43c184c917901f25dbc37850b80cd48f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1252-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1252-plan.md','doc: Epic #1252: [Simplicio Desktop] BYOK Provider + Marketplace','# Epic #1252: [Simplicio Desktop] BYOK Provider + Marketplace

## Overview

This epic adds Bring-Your-Own-Key (BYOK) provider management and a skills marketplace to Simplicio Desktop and CLI. It spans secure credential storage, UI flows for key management, runtime-sourced skill listing/ranking, and Hermes-imported metadata display.

## Sub-Issues

### 1. Secure OS Keychain Integration for API Keys
**Files:** `src/credential_sources.rs`, `src/hermes_parity_provider_ux.rs`
- Integrate with OS keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service) via `keyring` crate
- Store/retrieve/delete provider API keys securely
- Replace any env-var-only key storage with keychain-first, env-var-fallback
- Add `auth add <provider>`, `auth remove <provider>`, `auth list` CLI subcommands with real keychain backend
- Unit tests for credential CRUD (mock keychain in CI)

### 2. Key Redaction and Masking in Desktop UI
**Files:** `apps/desktop/src/pages/Settings.tsx`, `apps/desktop/src/lib/runtime.ts`
- After saving a key, display only last 4 characters (e.g., `sk-...ab3f`)
- Never send full key back to frontend after initial save
- Add "Reveal" toggle with re-authentication prompt
- Add "Delete Key" with confirmation dialog
- UI tests verifying secret redaction (no full key in DOM after save)

### 3. Runtime JSON-Backed Skills List and Ranking Endpoint
**Files:** `src/hermes_parity_provider_ux.rs`, `src/main.rs`
- Define `skills.json` schema: id, name, description, provider, tier (Free/Pro), capabilities tags
- Load skills from bundled JSON + Hermes-imported metadata at startup
- Expose `/skills` and `/skills/rank` endpoints from runtime
- Implement `skills rank` CLI subcommand: rank skills by relevance to a user query
- Implement `capabilities rank` CLI subcommand: rank provider capabilities
- Wire both into CLI dispatch in `main.rs`

### 4. Desktop Marketplace UI: Skills Browser and Recommendations
**Files:** `apps/desktop/src/pages/Agents.tsx`, `apps/desktop/src/lib/runtime.ts`
- Replace hardcoded skills snapshot with runtime-sourced data from `/skills` endpoint
- Add search/filter by capability, provider, tier
- Show "Recommended for this task" section using `/skills/rank`
- Display Free vs Pro badges per skill
- Show Hermes-imported skill metadata (source, version, last synced)

### 5. BYOK Setup Flow in Desktop Settings
**Files:** `apps/desktop/src/pages/Settings.tsx`
- Step-by-step wizard: select provider, paste key, validate key (test API call), save to keychain
- Provider-specific instructions (links to API key pages for OpenAI, Anthropic, etc.)
- Validation feedback: success/invalid/rate-limited
- Multi-provider support: list configured providers with status indicators

## Dependency Order

```
[1] Keychain Integration
       |
       v
[2] Key Masking UI  ----->  [5] BYOK Setup Flow
       
[3] Skills/Ranking Endpoint
       |
       v
[4] Marketplace UI
```

Sub-issues 1 and 3 can be worked in parallel. Sub-issue 2 depends on 1. Sub-issue 4 depends on 3. Sub-issue 5 depends on 1 and 2.

## Acceptance Criteria

- API keys are stored in OS keychain, never in plaintext config files
- Keys are masked in UI after save; full key cannot be retrieved from frontend
- `skills rank` and `capabilities rank` return meaningful ranked results
- Desktop Agents page shows live skill data from runtime
- Free/Pro badges render correctly
- All secret-handling paths have test coverage','docs/issues/1252-plan.md','be067e27e7aa1219f6ea58f057b634f5d0ce6d3b54178942642e88cbcd04632b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1253-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1253-plan.md','doc: Epic #1253 — [Simplicio Desktop] Package desktop binaries','# Epic #1253 — [Simplicio Desktop] Package desktop binaries

## Current state

- Tauri v2 config exists (`apps/desktop/src-tauri/tauri.conf.json`) with `bundle.targets: "all"` and updater plugin configured (empty pubkey).
- `scripts/package.sh` builds the CLI binary only (cargo build --release), not the Tauri desktop app.
- `apps/desktop/package.json` has `dev` and `build` scripts (Vite) but no `dist:*` scripts for platform bundles.
- No checksum generation, no signed release manifest, no third-party notices, no website download page.
- Updater endpoint (`releases.simplicio.dev`) has no channel separation from Hermes.

## Sub-issues

### 1. Add platform dist scripts (`dist:mac`, `dist:win`, `dist:linux`)
**Files:** `apps/desktop/package.json`, `scripts/package-desktop.sh` (new), `scripts/package-desktop.ps1` (new)
- Add npm scripts that invoke `npx tauri build` with platform-specific targets.
- macOS: `.dmg` + `.app` bundle; Windows: `.msi` + `.exe` (NSIS); Linux: `.AppImage` + `.deb`.
- Wire into CI matrix (GitHub Actions) for cross-platform builds.
- Generate codesigning placeholder config (env vars for Apple Developer ID, Windows Authenticode).

### 2. Checksum + signed release manifest
**Files:** `scripts/generate-checksums.sh` (new), `scripts/sign-manifest.sh` (new)
- After each platform build, generate SHA-256 checksums for all artifacts.
- Produce a `latest.json` manifest compatible with Tauri updater v2 format.
- Sign the manifest with an Ed25519 key (populate `bundle.updater.pubkey` in tauri.conf.json).
- Upload artifacts + manifest to `releases.simplicio.dev`.

### 3. Third-party notices + changelog automation
**Files:** `scripts/generate-notices.sh` (new), `THIRD_PARTY_NOTICES.md` (new), `CHANGELOG.md`
- Use `cargo-about` (or `cargo-license`) to collect Rust dependency licenses.
- Use a Node license checker for frontend deps in `apps/desktop`.
- Auto-generate `THIRD_PARTY_NOTICES.md` and embed in the bundle resources.
- Auto-generate changelog from conventional commits between tags.

### 4. Website download page with release notes
**Files:** `website/docs/download.md` (new), `website/src/pages/download.tsx` (new), `website/package.json`
- Create a `/download` page on the Docusaurus website.
- Show platform-specific download links (auto-detect OS via user-agent).
- Display release notes from `CHANGELOG.md` or GitHub Releases API.
- Include checksums and GPG/Ed25519 verification instructions.

### 5. Update channel separation + entitlement gating
**Files:** `apps/desktop/src-tauri/tauri.conf.json`, `src/desktop_app.rs`, `scripts/package-desktop.sh`
- Separate update channels: `stable`, `beta`, `nightly` with distinct endpoint paths.
- Ensure Simplicio Desktop updater does not collide with Hermes update endpoints.
- Add entitlement check at app launch: verify license/subscription before allowing updates.
- Support environment variable or config file to pin a channel.

## Dependency order

```
[1] dist scripts  ──► [2] checksum + manifest  ──► [4] website download page
                                                 ──► [5] channel separation
[3] third-party notices (independent, can parallel with 1-2)
```

## Estimated effort

| Sub-issue | Estimate |
|-----------|----------|
| 1. Dist scripts | M (2-3 days) |
| 2. Checksum + manifest | M (2-3 days) |
| 3. Third-party notices | S (1 day) |
| 4. Website download page | M (2-3 days) |
| 5. Channel separation | L (3-5 days) |','docs/issues/1253-plan.md','33b05b4c0fbb4d7e9c9d627d63dd8557d1cdf8fc9de78fa8ad35a0e4f5e819cf','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1254-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1254-plan.md','doc: Epic #1254: [Simplicio Desktop] Harden security, allowlist, privacy','# Epic #1254: [Simplicio Desktop] Harden security, allowlist, privacy

## Overview

The Simplicio Desktop (Tauri) app currently lacks several security hardening measures. This epic decomposes into 6 independent workstreams that can be implemented in parallel.

---

## Sub-issue 1: Strict Content Security Policy (CSP)

**Problem:** `tauri.conf.json` has CSP set to `null`, allowing unrestricted script/resource loading.

**Files:** `apps/desktop/src-tauri/tauri.conf.json`

**Tasks:**
- Define a strict CSP: `default-src ''self''; script-src ''self''; style-src ''self'' ''unsafe-inline''; img-src ''self'' data:; connect-src ''self'' https://api.openai.com https://api.anthropic.com`
- Remove `''unsafe-eval''` — ensure no runtime `eval()` usage in frontend
- Test that the app loads correctly under the new policy
- Add integration test verifying CSP header is present and strict

---

## Sub-issue 2: Updater public key configuration

**Problem:** The updater `pubkey` is an empty string, meaning unsigned update artifacts could be accepted.

**Files:** `apps/desktop/src-tauri/tauri.conf.json`

**Tasks:**
- Generate an Ed25519 keypair for update signing (`tauri signer generate`)
- Set `pubkey` in `tauri.conf.json` to the generated public key
- Document the signing workflow in `docs/release-signing.md`
- Add CI step to sign artifacts with the private key (stored as secret)
- Add test that verifies `pubkey` is non-empty in config

---

## Sub-issue 3: Command allowlist and argument sanitization

**Problem:** `run_task` and `run_simplicio` Tauri commands pass arbitrary strings to the shell with no validation. Any IPC caller can execute arbitrary commands.

**Files:** `apps/desktop/src-tauri/src/main.rs`, `apps/desktop/src/lib/runtime.ts`

**Tasks:**
- Define a structured command enum (e.g., `AllowedCommand { binary: AllowedBinary, args: Vec<String> }`)
- Allowlist only known binaries: `simplicio`, `node`, `npm`, `npx`, `git`
- Sanitize arguments: reject shell metacharacters (`;`, `|`, `&`, `` ` ``, `$()`, etc.)
- Replace direct `Command::new(shell)` with the validated command builder
- Add deny-by-default: any command not in the allowlist returns an error
- Add unit tests for:
  - Allowed command passes validation
  - Disallowed binary is rejected
  - Shell injection via args is rejected
  - Empty/null arguments are handled

---

## Sub-issue 4: Secret redaction in logs and UI

**Problem:** API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `STRIPE_SECRET`, etc.) can appear in log output shown in the Logs page and emitted by `tail_logs`/`log_message`.

**Files:** `apps/desktop/src-tauri/src/main.rs`, `apps/desktop/src/pages/Logs.tsx`

**Tasks:**
- Create a `redact_secrets(text: &str) -> String` function in Rust
- Define patterns to redact: `sk-...`, `sk-ant-...`, `sk_live_...`, `pk_live_...`, `ghp_...`, `gho_...`, any env var matching `*_KEY`, `*_SECRET`, `*_TOKEN`
- Apply redaction in `tail_logs` and `log_message` commands before returning to frontend
- Apply redaction in the frontend `Logs.tsx` as a defense-in-depth layer
- Add unit tests with known key patterns verifying they are replaced with `[REDACTED]`
- Add test that multi-line log blocks with embedded keys are fully redacted

---

## Sub-issue 5: Desktop-side approval gate enforcement

**Problem:** Approval gates delegate entirely to the CLI with no desktop-side enforcement or evidence recording. A compromised CLI could bypass approvals.

**Files:** `apps/desktop/src/pages/Approvals.tsx`, `apps/desktop/src-tauri/src/main.rs`

**Tasks:**
- Add an approval record store (SQLite or JSON file) in the Tauri app data directory
- Record each approval decision with: timestamp, user, action, approved/denied, evidence hash
- Enforce that certain high-risk commands require an approval record before execution
- Add UI to view approval history in `Approvals.tsx`
- Add tests verifying:
  - Command blocked without prior approval
  - Approval record is persisted and retrievable
  - Approval cannot be replayed (nonce/expiry)

---

## Sub-issue 6: Security test suite

**Problem:** No security-focused tests exist for the desktop app.

**Files:** New test files in `apps/desktop/src-tauri/tests/` and `apps/desktop/src/__tests__/`

**Tasks:**
- CSP validation test: parse `tauri.conf.json`, assert CSP is strict
- Updater pubkey test: assert pubkey is non-empty
- Command bridge denial tests: invoke disallowed commands via IPC, assert rejection
- Secret redaction coverage: parameterized tests with various key formats
- Approval gate tests: mock approval flow, verify enforcement
- Generate a privacy/security report summarizing controls (can be a test output artifact)

---

## Implementation order (suggested)

1. **Sub-issue 4** (secret redaction) — highest immediate risk, standalone
2. **Sub-issue 3** (command allowlist) — highest severity, standalone
3. **Sub-issue 1** (CSP) — config change, low risk
4. **Sub-issue 2** (updater pubkey) — requires key generation workflow
5. **Sub-issue 5** (approval gates) — most complex, depends on architecture decisions
6. **Sub-issue 6** (test suite) — can start early but completes last

## Notes

- The app uses **Tauri** (not Electron). Acceptance criteria from the issue referencing Electron patterns (e.g., `contextIsolation`, `nodeIntegration`) should be adapted to Tauri equivalents (IPC command system, CSP in tauri.conf.json, Tauri allowlist).
- All changes should maintain backward compatibility with existing CLI workflows.','docs/issues/1254-plan.md','d2811f794bb21e7ecf093dbec3f61eb73ffd2454d4658a0c8a0572f181deb031','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1255-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1255-plan.md','doc: Epic #1255 - Simplicio Desktop QA/Evidence Matrix','# Epic #1255 - Simplicio Desktop QA/Evidence Matrix

## Overview

Build a comprehensive QA matrix and evidence-generation pipeline for the Simplicio Desktop app (Tauri + React). The desktop app currently has zero test infrastructure, no QA documentation, and no automated evidence collection.

## Scope Dimensions

- **Platforms**: Windows x64, macOS ARM, macOS x64, Linux x64
- **Product states**: 8 (free, trial, expired-trial, pro, enterprise, offline, degraded, first-run)
- **Runtime states**: 4 (connected, disconnected, updating, error)
- **Core flows**: 10 (onboarding, chat, agents, tasks, approvals, models, connections, settings, notifications, command-palette)

Total matrix cells: 4 x 8 x 4 x 10 = 1,280

## Subtasks

### 1. QA Matrix Document (`docs/qa-matrix.md`)
**Effort**: S | **Deps**: none

Create a markdown document defining the full test matrix with:
- Platform x product-state x runtime-state x flow grid
- Pass/fail/skip status columns
- Links to evidence artifacts per cell
- Priority tiers (P0: critical paths, P1: common paths, P2: edge cases)

Deliverable: `docs/qa-matrix.md`

---

### 2. UI Test Framework Setup
**Effort**: M | **Deps**: none

Add Vitest + Testing Library (React) for component-level tests and Playwright for E2E tests.

Files to create/edit:
- `apps/desktop/package.json` — add `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `@playwright/test`, `jsdom` to devDependencies; add scripts `test`, `test:ui`, `test:e2e`
- `apps/desktop/vitest.config.ts` — configure jsdom environment, setup files
- `apps/desktop/vitest.setup.ts` — import testing-library matchers
- `apps/desktop/playwright.config.ts` — configure for Tauri webview URL
- `apps/desktop/src/__tests__/` — initial test files for each component/page

---

### 3. Tauri Bridge / Runtime Tests
**Effort**: M | **Deps**: subtask 2

Add tests for the Tauri IPC bridge layer (`src/lib/runtime.ts`, `src/lib/desktop-shell.tsx`).

- Mock `@tauri-apps/api` invoke calls
- Test each bridge function: connected/disconnected states, error handling
- Test `persisted-state.ts` read/write cycle
- Test `notifications.ts` permission flow

Files: `apps/desktop/src/lib/__tests__/runtime.test.ts`, etc.

---

### 4. Evidence Generation Script
**Effort**: L | **Deps**: subtask 2

Build a script that runs the test suite and collects evidence artifacts.

- `apps/desktop/scripts/qa-evidence.ts` — orchestrator
- For each matrix cell in P0/P1:
  - Launch app with mocked product/runtime state
  - Run the flow
  - Capture screenshot (Playwright)
  - Record console logs
  - Save to `.simplicio-loop/reports/<run-id>/<platform>/<state>/<flow>/`
- Generate summary JSON: `.simplicio-loop/reports/<run-id>/summary.json`
- Generate markdown report: `.simplicio-loop/reports/<run-id>/report.md`

Files to create:
- `apps/desktop/scripts/qa-evidence.ts`
- `apps/desktop/scripts/state-fixtures.ts` — mock product/runtime state injection
- `.simplicio-loop/reports/.gitkeep`

---

### 5. Platform-Specific Test Scripts
**Effort**: M | **Deps**: subtask 2

Add npm scripts and CI matrix entries for per-platform testing.

- `apps/desktop/package.json` — add `test:desktop:windows`, `test:desktop:macos`, `test:desktop:linux`
- Each script sets platform env vars and runs the appropriate test subset
- Handle platform-specific behavior (tray icon, native menus, file paths)

---

### 6. JSON Fixtures for Product/Runtime States
**Effort**: S | **Deps**: none

Create deterministic fixtures representing each product and runtime state.

Files:
- `apps/desktop/fixtures/product-states/free.json`
- `apps/desktop/fixtures/product-states/trial.json`
- `apps/desktop/fixtures/product-states/expired-trial.json`
- `apps/desktop/fixtures/product-states/pro.json`
- `apps/desktop/fixtures/product-states/enterprise.json`
- `apps/desktop/fixtures/product-states/offline.json`
- `apps/desktop/fixtures/product-states/degraded.json`
- `apps/desktop/fixtures/product-states/first-run.json`
- `apps/desktop/fixtures/runtime-states/connected.json`
- `apps/desktop/fixtures/runtime-states/disconnected.json`
- `apps/desktop/fixtures/runtime-states/updating.json`
- `apps/desktop/fixtures/runtime-states/error.json`

---

### 7. Release Checklist
**Effort**: S | **Deps**: subtask 1

Create a deterministic, copy-pasteable release checklist.

File: `docs/release-checklist.md`

Contents:
- [ ] All P0 matrix cells pass on all 4 platforms
- [ ] All P1 matrix cells pass on primary platform (Windows)
- [ ] Evidence report generated and saved
- [ ] License audit passes (`npx license-checker --production --failOn ''GPL-3.0''`)
- [ ] Binary checksums generated (SHA-256 for each platform artifact)
- [ ] CHANGELOG updated
- [ ] Version bumped in `package.json` and `Cargo.toml`
- [ ] Tauri bundle signed (Windows: Authenticode, macOS: codesign + notarize)
- [ ] Smoke test on clean install (each platform)

---

### 8. CI Integration
**Effort**: L | **Deps**: subtasks 2, 4, 5

Add GitHub Actions workflow for automated evidence collection.

File: `.github/workflows/desktop-qa.yml`

- Matrix strategy: `[windows-latest, macos-latest, ubuntu-latest]`
- Steps: install deps, build Tauri app, run unit tests, run E2E tests, run evidence script
- Upload `.simplicio-loop/reports/` as artifact
- Post summary to PR comment
- Run on: push to `main`, PRs touching `apps/desktop/**`

---

## Suggested Execution Order

```
Phase 1 (parallel): subtasks 1, 6 (no deps, small)
Phase 2: subtask 2 (test framework)
Phase 3 (parallel): subtasks 3, 5 (depend on 2)
Phase 4: subtask 4 (evidence script, depends on 2)
Phase 5 (parallel): subtasks 7, 8 (depend on earlier work)
```

## Out of Scope

- Mobile app testing (separate epic)
- Backend/API testing (covered by runtime crate tests)
- Performance benchmarking (separate epic)','docs/issues/1255-plan.md','a43f4bb4aa913b434e26974649c031e264c9f69b7f8b4e09abab6e8567c3ce79','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1256-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1256-plan.md','doc: Epic #1256 — Simplicio Desktop: Onboarding and Pricing UX','# Epic #1256 — Simplicio Desktop: Onboarding and Pricing UX

## Overview

The current onboarding (`Onboarding.tsx`) is a basic 5-step wizard (welcome, runtime, provider, first-steps, done) with no token savings scan, ROI dashboard, pricing tiers, paywall, upgrade UX, BYOK vs subscription distinction, or i18n support. This epic decomposes the work into concrete, independently deliverable items.

## Work Items

### WI-1: Pricing/Plan Tier Data Model and State Management
**Files:** `apps/desktop/src/lib/pricing.ts`, `apps/desktop/src/types/plans.ts`
- Define Free/Pro/Team/Enterprise tier types with feature flags, limits, and pricing
- Create plan state store (current plan, usage, limits)
- Implement feature-gating utility: `canAccess(feature, currentPlan) -> boolean`
- Add plan persistence (local storage + optional API sync)

### WI-2: Savings Scan Step in Onboarding
**Files:** `apps/desktop/src/components/Onboarding.tsx`, `apps/desktop/src/lib/onboarding.ts`, `apps/desktop/src/components/SavingsScan.tsx`
- Add a new onboarding step between "provider" and "first-steps" that scans configured providers/models for estimated token savings
- Display projected monthly savings based on caching, batching, and routing optimizations
- Show before/after cost comparison

### WI-3: ROI Dashboard Widget
**Files:** `apps/desktop/src/pages/Dashboard.tsx`, `apps/desktop/src/components/ROIDashboard.tsx`
- Create ROI dashboard component showing cumulative savings, tokens processed, cost per request
- Integrate into main Dashboard page
- Pull data from usage telemetry store
- Include time-range selector (7d, 30d, 90d, all-time)

### WI-4: Paywall and Upgrade UX
**Files:** `apps/desktop/src/components/Paywall.tsx`, `apps/desktop/src/components/UpgradeCTA.tsx`, `apps/desktop/src/pages/Settings.tsx`
- Build `<Paywall>` wrapper component that checks plan tier before rendering children
- Build `<UpgradeCTA>` component with tier comparison and upgrade button
- Add pricing/plan management section to Settings page
- Integrate upgrade CTAs on locked modules across the app (Dashboard, provider config, advanced routing)

### WI-5: BYOK Provider Setup Flow
**Files:** `apps/desktop/src/components/BYOKSetup.tsx`, `apps/desktop/src/lib/onboarding.ts`
- Expand the provider step in onboarding to distinguish BYOK (bring your own key) vs managed/subscription
- BYOK flow: user enters API key, selects models, validates connection
- Subscription flow: plan selection, account linking
- Key validation and secure storage

### WI-6: Internationalization (i18n) Infrastructure + PT/EN Copy
**Files:** `apps/desktop/src/lib/i18n.ts`, `apps/desktop/src/locales/en.json`, `apps/desktop/src/locales/pt.json`
- Set up i18n framework (e.g., i18next or lightweight custom solution)
- Extract all hardcoded strings from onboarding, pricing, paywall, and settings components
- Create EN and PT copy decks
- Add language selector to Settings

## Dependency Graph

```
WI-1 (pricing model)
 ├── WI-4 (paywall/upgrade) depends on WI-1
 └── WI-5 (BYOK) depends on WI-1

WI-2 (savings scan) — independent
WI-3 (ROI dashboard) — independent

WI-6 (i18n) — should be applied after WI-2..WI-5 are merged, or done in parallel with string keys
```

## Suggested Implementation Order

1. **WI-1** — Foundation: pricing model and feature gating
2. **WI-2** + **WI-3** — Can be done in parallel: savings scan and ROI dashboard
3. **WI-5** — BYOK setup (depends on WI-1 for plan awareness)
4. **WI-4** — Paywall/upgrade UX (depends on WI-1, benefits from WI-2/3/5 being done)
5. **WI-6** — i18n pass over all new and existing UI','docs/issues/1256-plan.md','171a2165e555bcae2731e6106b7c9e31105ebbcccc2197c0b2896b1f70a9add7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1257-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1257-plan.md','doc: Plan: Retire Hermes Assumptions (#1257)','# Plan: Retire Hermes Assumptions (#1257)

## Overview

Remove or isolate all Hermes/Nous-specific references from simplicio-runtime so the desktop runtime operates on 8 Simplicio-native contracts without assuming Hermes as the backing engine.

## Sub-tasks

### 1. Contract Document Creation
- **Files**: new `docs/contracts/` directory
- **Work**: Define the 8 Simplicio-native runtime contracts (agent lifecycle, capability negotiation, IPC protocol, policy enforcement, provider abstraction, narrative context, task supervision, plugin bridge).
- **Deliverable**: `docs/contracts/*.md` with trait signatures and message schemas.

### 2. hermes_bridge Plugin Isolation
- **Files**: `src/plugins/hermes_bridge/mod.rs`, `src/plugins/hermes_bridge/simplicio_bridge.rs`
- **Work**: Extract the bridge behind a feature flag `hermes-compat`. Move Hermes-specific types into an optional module. The default build compiles without Hermes bridge.

### 3. hermes_parity Module Audit and Migration
- **Files**: `src/hermes_parity_*.rs` (12 modules: readiness, run_loop, agent_runner, benchmark_agents, policy, provider_ux, ipc, narrative, canonical_loop, capabilities_ext, context, adapters, bare_task)
- **Work**: For each module, identify which logic is Hermes-specific vs. generic runtime logic. Generic logic moves to `src/runtime/` under Simplicio-native trait impls. Hermes-specific logic moves behind `#[cfg(feature = "hermes-compat")]`.

### 4. hermes_compat and hermes_import Cleanup
- **Files**: `src/hermes_compat.rs`, `src/hermes_import.rs`
- **Work**: Gate both modules behind `hermes-compat` feature. Provide no-op stubs or remove entirely if no downstream code depends on them outside the feature gate.

### 5. Nous Provider Decoupling
- **Files**: `src/plugins/model_providers/nous.rs`, `src/nous_rate_guard.rs`
- **Work**: Make Nous a pluggable provider behind `#[cfg(feature = "nous")]`. The default build uses a generic provider trait. Rate guard becomes provider-agnostic.

### 6. skill_hermes Retirement
- **Files**: `src/skill_hermes_agent.rs`, `src/skill_hermes_agent_skill_authoring.rs`, `src/skill_hermes_s6_container_supervision.rs`
- **Work**: Rename to `src/skill_agent.rs`, `src/skill_agent_authoring.rs`, `src/skill_container_supervision.rs`. Remove Hermes-specific API calls, replace with Simplicio-native contract calls. Keep old names as `#[deprecated]` re-exports behind feature flag.

### 7. electron_app Hermes Assumption Removal
- **Files**: `src/electron_app.rs`
- **Work**: Audit for hard-coded Hermes endpoints, model IDs, or config keys. Replace with runtime-configurable values from Simplicio config.

### 8. capability_broker and update_command Audit
- **Files**: `src/capability_broker.rs`, `src/update_command.rs`
- **Work**: Check for Hermes-specific capability names or update channels. Replace with Simplicio-native equivalents.

### 9. Schema Fixture Tests
- **Files**: new `tests/fixtures/` and `tests/schema_*.rs`
- **Work**: Create fixture JSON files for each of the 8 contracts. Write `#[test]` functions that deserialize fixtures and validate against the contract structs.

### 10. Final Cleanup Checklist
- Verify `cargo check` passes with default features (no hermes-compat).
- Verify `cargo check --features hermes-compat` still compiles.
- Grep for remaining `hermes` / `Hermes` / `nous` / `Nous` references outside feature-gated code.
- Update `Cargo.toml` with new feature flags.
- Update `README.md` with migration notes.

## Suggested Execution Order

1 (contract docs) -> 3 (parity audit) -> 2 (bridge isolation) -> 4 (compat cleanup) -> 5 (nous decoupling) -> 6 (skill retirement) -> 7 (electron_app) -> 8 (broker/update) -> 9 (tests) -> 10 (checklist)

## Estimated Scope

~235 source files reference Hermes/Nous. Core migration touches ~25 files directly. Feature-gating approach preserves backward compatibility while the migration proceeds.','docs/issues/1257-plan.md','87364a76dbe68f229b69d1e96c7d3db3cb2ac1673bb970aa289f73c4a3e7950c','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1258-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1258-plan.md','doc: Epic #1258 — [Hermes Sync] Scheduled Import Watcher','# Epic #1258 — [Hermes Sync] Scheduled Import Watcher

## Current State

- `src/hermes_import.rs` exists but only handles one-shot migration (sessions, state DB, config, kanban, cron hooks, MCP servers).
- `scripts/hermes-sync-cron.sh` is a basic commit-counter that detects new Hermes commits and logs feature names. It does not classify updates, generate governed reports, or enforce dry-run guarantees.
- `main.rs` references hermes only as a migration source — no `hermes import/diff/sync` subcommand tree exists.
- No update classifier, no JSON report schema `simplicio.hermes-sync-report/v1`, no report persistence, no last-seen SHA tracking in Rust, no fixture tests.

## Decomposition

### Sub-task 1: CLI subcommand tree (`hermes import`, `hermes diff`, `hermes sync`)

**Files:** `src/main.rs`, `src/hermes_import.rs` (or new `src/hermes_cli.rs`)

- Add a `hermes` subcommand group to the CLI parser in `main.rs`.
- `hermes import` — run the existing `HermesDataImportResult` flow with additional flags (`--dry-run`, `--since <sha>`).
- `hermes diff` — show what changed in Hermes since the last-seen SHA without importing.
- `hermes sync` — full governed loop: diff, classify, generate report, optionally apply.
- Wire `cron add hermes-sync` to register the sync as a scheduled task via `cron_scheduler.rs`.

**Acceptance:** `cargo check` passes; `simplicio hermes --help` lists the three subcommands.

---

### Sub-task 2: Update classifier (7 categories)

**Files:** new `src/hermes_classifier.rs`

- Implement a classifier that inspects each Hermes commit/diff and assigns one of:
  - `desktop-ui` — Electron/TUI changes
  - `cli-runtime` — CLI or runtime logic
  - `skill-metadata` — skill definitions, catalog entries
  - `provider-model` — LLM provider or model config
  - `security-policy` — policy engine, threat patterns, audit
  - `docs-pattern` — documentation, README, AGENTS.md
  - `ignore` — CI, formatting, deps-only
- Classification is based on file-path patterns and commit-message heuristics.
- Each category carries a `risk: low | medium | high` and a `recommendation` string.
- Pure function: `fn classify_commit(files: &[&str], message: &str) -> Classification`.

**Acceptance:** Unit tests with at least 10 fixture cases covering all 7 categories.

---

### Sub-task 3: JSON report schema `simplicio.hermes-sync-report/v1`

**Files:** new `src/hermes_report.rs`

- Define `HermesSyncReport` struct with serde derive:
  - `schema: String` (always `"simplicio.hermes-sync-report/v1"`)
  - `date: String` (ISO 8601)
  - `last_seen_sha: String`
  - `new_sha: String`
  - `commits_analyzed: usize`
  - `classifications: Vec<ClassifiedCommit>` (commit SHA, message, category, risk, recommendation, target files)
  - `dry_run: bool`
  - `applied: bool`
  - `warnings: Vec<String>`
- Serialize to JSON, write to `.simplicio-loop/reports/hermes-sync/{date}-{sha_short}.json`.
- Deserialize for `hermes diff` display.

**Acceptance:** Round-trip serde test; report file written to correct path.

---

### Sub-task 4: Governed sync loop and dry-run guarantees

**Files:** `src/hermes_import.rs`, `src/hermes_cli.rs`

- Implement the sync loop:
  1. Read last-seen SHA from `.simplicio-loop/reports/hermes-sync/.last-seen-sha`.
  2. Enumerate Hermes commits since that SHA.
  3. Classify each commit (sub-task 2).
  4. Generate report (sub-task 3).
  5. If `--dry-run` or if any commit has `risk: high`, stop and emit report only.
  6. Otherwise, apply import and update last-seen SHA.
- Ensure dry-run mode never mutates any state (no file writes beyond the report itself).
- Replace the shell script''s logic with this Rust implementation; keep shell script as a thin wrapper that calls `simplicio hermes sync`.

**Acceptance:** Integration test proving dry-run produces report without side effects.

---

### Sub-task 5: Report persistence, last-seen SHA tracking, and cron integration

**Files:** `src/hermes_report.rs`, `src/cron_scheduler.rs`, `scripts/hermes-sync-cron.sh`

- Persist reports under `.simplicio-loop/reports/hermes-sync/` with timestamp-based filenames.
- Track last-seen SHA in `.simplicio-loop/reports/hermes-sync/.last-seen-sha` (atomic write via temp file + rename).
- Add `hermes-sync` as a known cron profile in `cron_scheduler.rs` so `simplicio cron add hermes-sync --interval daily` works.
- Update `scripts/hermes-sync-cron.sh` to delegate to `simplicio hermes sync` instead of doing its own git-log parsing.

**Acceptance:** `simplicio cron list` shows hermes-sync; reports accumulate correctly across multiple runs.

---

### Sub-task 6: Classifier fixture tests

**Files:** new `tests/hermes_classifier_tests.rs` or inline `#[cfg(test)]` in `src/hermes_classifier.rs`

- At least 10 fixture test cases, e.g.:
  - Commit touching `src/tui/*.rs` -> `desktop-ui`
  - Commit touching `src/htool_*.rs` -> `cli-runtime`
  - Commit touching `skills/*.yaml` -> `skill-metadata`
  - Commit with message `fix(security): ...` touching `src/policy_engine.rs` -> `security-policy`
  - Commit touching only `README.md` -> `docs-pattern`
  - Commit touching only `Cargo.lock` -> `ignore`
- Test risk assignment logic.
- Test edge cases (commit touching files in multiple categories -> highest-risk category wins).

**Acceptance:** `cargo test hermes_classifier` passes with all fixtures green.

## Suggested Implementation Order

1. Sub-task 2 (classifier) — standalone, no dependencies
2. Sub-task 3 (report schema) — depends on classifier types
3. Sub-task 6 (fixture tests) — validates sub-tasks 2+3
4. Sub-task 1 (CLI subcommands) — wires everything into main
5. Sub-task 4 (governed sync loop) — orchestrates all pieces
6. Sub-task 5 (persistence + cron) — final integration

## Constraints

- `std` + `serde` + `serde_json` only (no new crate dependencies).
- No `.unwrap()` in production code; use `Result` propagation.
- All file I/O must handle errors gracefully with meaningful messages.','docs/issues/1258-plan.md','aeb0a2f7c68f83b979b2dbd2d32c1e3a6a33a2b05940247a149239955719ed2e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1259-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1259-plan.md','doc: Epic #1259 -- [Hermes Sync] Port Hermes CLI/tools to Rust','# Epic #1259 -- [Hermes Sync] Port Hermes CLI/tools to Rust

## Status

Substantial work already shipped across slices 1-5 plus `hermes-port-complete`.
Existing modules: `hermes_compat.rs`, `hermes_import.rs`, 13+ `hermes_parity_*.rs` files,
`hermes_core_integration.rs` tests, `hermes-sync-cron.sh`, and `hermes_tools_mcp_server.py`.

## Acceptance Criteria (from epic)

1. Import classifier auto-categorises Hermes CLI artifacts for porting
2. Port spec generation from sync reports
3. Rust implementation of each ported tool (parity modules)
4. Integration tests covering ported functionality
5. Evidence trail (docs + commit refs)
6. Documentation (usage, architecture, migration guide)

## Decomposition into Slices

### Slice A -- Import Classifier Completeness

**Files:** `src/hermes_import.rs`, `src/hermes_compat.rs`
**Work:**
- Verify the import classifier handles all known Hermes CLI artifact types
- Add any missing artifact categories (check against upstream Hermes CLI manifest)
- Unit tests for each classification path

### Slice B -- Port Spec Auto-Generation

**Files:** `src/hermes_parity_readiness.rs` (new or extend)
**Work:**
- Given a Hermes sync report, auto-generate a port specification document
- Output format: structured JSON with tool name, input/output schema, parity status
- Wire into `hermes-sync-cron.sh` as optional `--emit-spec` flag

### Slice C -- Contracts Smoke Validation

**Files:** `src/hermes_parity_adapters.rs`, `src/hermes_parity_context.rs`
**Work:**
- For each parity adapter, add a `validate_contract()` method
- Smoke-test that Rust adapter input/output matches the original Hermes tool contract
- Integration test: round-trip a sample payload through each adapter

### Slice D -- Capabilities Rank Validation

**Files:** `src/hermes_parity_capabilities_ext.rs`
**Work:**
- Validate that capability rankings in the Rust port match the upstream Hermes rankings
- Add a comparison test that loads both ranking sources and asserts equivalence
- Handle rank drift detection (warn on mismatch, fail on critical delta)

### Slice E -- Helo Governed Learning Integration

**Files:** `src/hermes_parity_learn_ext.rs`
**Work:**
- Integrate Helo governed learning protocol into the learn extension
- Ensure learning events are gated by policy (`hermes_parity_policy.rs`)
- Add integration test covering the learn -> policy -> persist cycle

### Slice F -- Evidence and Documentation

**Files:** `docs/hermes-port-evidence.md`, `docs/hermes-architecture.md`
**Work:**
- Compile evidence file mapping each Hermes CLI tool to its Rust counterpart (file:line)
- Write architecture doc covering the parity module structure
- Write migration guide for consumers switching from Hermes CLI to Rust runtime

## Dependency Order

```
Slice A (classifier) --> Slice B (spec gen) --> Slice C (contracts)
                                            \-> Slice D (capabilities)
                                            \-> Slice E (learning)
All above -----------> Slice F (evidence + docs)
```

## Existing Coverage

| Module | Status |
|--------|--------|
| hermes_parity_adapters.rs | Shipped (slice 3) |
| hermes_parity_bare_task.rs | Shipped (slice 2) |
| hermes_parity_canonical_loop.rs | Shipped (slice 4) |
| hermes_parity_capabilities_ext.rs | Shipped (slice 4) -- needs rank validation |
| hermes_parity_context.rs | Shipped (slice 3) |
| hermes_parity_ipc.rs | Shipped (slice 5) |
| hermes_parity_learn_ext.rs | Shipped (slice 5) -- needs Helo integration |
| hermes_parity_narrative.rs | Shipped (slice 4) |
| hermes_parity_policy.rs | Shipped (slice 4) |
| hermes_parity_provider_ux.rs | Shipped (slice 5) |
| hermes_parity_agent_runner.rs | Shipped (hermes-port-complete) |
| hermes_parity_run_loop.rs | Shipped |
| hermes_parity_benchmark_agents.rs | Shipped |
| hermes_parity_readiness.rs | Shipped -- needs spec gen extension |
| hermes_import.rs | Shipped (slice 1) |
| hermes_compat.rs | Shipped (slice 1) |
| tests/hermes_core_integration.rs | Shipped -- needs expansion |','docs/issues/1259-plan.md','037ce226285db1264f1eb7e00504e62da2e5a72d4e8996c22088390d6f0e87b8','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1260-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1260-plan.md','doc: Epic #1260: [Hermes Sync] Adapt desktop updates without coupling','# Epic #1260: [Hermes Sync] Adapt desktop updates without coupling

## Overview

Build a multi-mode desktop diff importer that allows Simplicio Runtime to sync upstream desktop source changes without tight coupling. The system inspects diffs, proposes patches, applies safe changes automatically, and flags risky changes for manual review — all while enforcing brand, runtime, and paywall guardrails.

## Sub-issues

### 1. Create `apps/simplicio-desktop` directory scaffold
**Scope:** Initialize the forked desktop directory structure with baseline files, .gitignore, and a manifest describing which upstream paths map to which local paths.
**Files:** `apps/simplicio-desktop/`, `apps/simplicio-desktop/manifest.toml`
**Effort:** Small

### 2. Desktop diff importer — core modes
**Scope:** Implement `src/htool_hermes_sync.rs` with four operating modes:
- `inspect` — parse upstream diff, report changed files and conflict risk
- `patch-propose` — generate a proposed patch set with guardrail annotations
- `apply-safe` — apply non-conflicting, guardrail-passing patches automatically
- `manual-review` — emit a structured report for human review of risky patches

Each mode reads from a diff source (local path or stdin) and writes structured JSON output.
**Files:** `src/htool_hermes_sync.rs`, `src/main.rs` (mod declaration), `src/tool_registry.rs` (match arm)
**Effort:** Large

### 3. Brand / runtime / paywall guardrails
**Scope:** Implement guardrail checks that run during `patch-propose` and `apply-safe`:
- **Brand guard:** reject patches that remove or alter brand-specific strings/assets
- **Runtime guard:** reject patches that modify runtime entrypoints or security-critical paths
- **Paywall guard:** reject patches that bypass or weaken paywall/license checks

Include unit tests for each guardrail with known-good and known-bad diffs.
**Files:** `src/hermes_guardrails.rs`, `tests/hermes_guardrails_test.rs`
**Effort:** Medium

### 4. CLI subcommand `hermes sync --target desktop`
**Scope:** Wire the diff importer into the CLI as `hermes sync --target desktop [--mode inspect|patch-propose|apply-safe|manual-review] [--source <path>]`. Parse args, invoke the importer, print results.
**Files:** `src/main.rs` (CLI arg parsing), `src/htool_hermes_sync.rs`
**Effort:** Small

### 5. Evidence and reporting infrastructure
**Scope:** After each sync operation, produce a structured report (JSON + optional Markdown) documenting:
- Which files were inspected/patched/skipped
- Which guardrails triggered and why
- Summary statistics (files changed, lines added/removed, conflicts)

Store reports under `apps/simplicio-desktop/.hermes-sync/reports/`.
**Files:** `src/hermes_report.rs`, `apps/simplicio-desktop/.hermes-sync/`
**Effort:** Medium

## Dependency order

```
1 (scaffold) → 2 (core importer) → 3 (guardrails) → 4 (CLI) → 5 (reporting)
```

Sub-issues 3 and 5 can be developed in parallel once sub-issue 2 is complete.

## Constraints

- std + serde + serde_json only; no `.unwrap()` in production code
- All modes must return `Result<T, E>` with meaningful error messages
- Guardrail definitions should be data-driven (configurable via manifest.toml) where possible','docs/issues/1260-plan.md','4cd5365a7ebfba63c80adfae32cce69e47a66a6502a9544368206aa435483d3d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1261-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1261-plan.md','doc: Plan: #1261 — [Hermes Sync] Auto-create issues from import reports','# Plan: #1261 — [Hermes Sync] Auto-create issues from import reports

## Context

The current `hermes-sync-cron.sh` only appends feature names to a plain-text file (`tracked-features.txt`). There is no classification of what each feature means for Simplicio, no deduplication, no GitHub issue creation, and no dry-run capability.

This epic decomposes into 5 sub-issues.

---

## Sub-issue 1: Report parser and classifier

**Goal:** Parse the Hermes sync report (commit log + file diffs) and classify each entry into an actionable type.

**Classification types:**
- `cli_port` — CLI command/flag that Simplicio should support
- `desktop_adapt` — Desktop/GUI feature needing adaptation
- `skill_import` — Skill/tool that can be imported or wrapped
- `config_change` — Configuration schema change
- `api_change` — API contract change requiring update
- `irrelevant` — No action needed (docs, CI, cosmetic)

**Files to create/edit:**
- `src/htool_hermes_report_parser.rs` — Parse commit messages + diff summaries from `hermes-sync-cron.sh` output
- Struct: `HermesReportEntry { sha: String, message: String, paths: Vec<String>, classification: Classification }`
- Classification heuristic: path-based (e.g., `src/cli/` -> `cli_port`, `src/skills/` -> `skill_import`) + message keyword matching

**Acceptance criteria:**
- Given a JSON report or raw git log, produces a `Vec<HermesReportEntry>` with classification
- No `.unwrap()` in production paths
- Unit tests with sample commit data

---

## Sub-issue 2: Deduplication engine with stable keys

**Goal:** Prevent duplicate GitHub issues for the same Hermes change.

**Design:**
- Stable key format: `hermes:{sha_short}:{classification}:{path_hash}`
- `path_hash` = first 8 chars of SHA-256 of sorted affected paths
- Persist known keys in `.simplicio-loop/cron/issue-index.json`
- Schema: `{ "version": 1, "entries": { "<key>": { "issue_number": N, "created_at": "...", "status": "open|closed" } } }`

**Files to create/edit:**
- `src/htool_hermes_dedupe.rs` — `IssueIndex` struct with `load()`, `save()`, `contains()`, `insert()` methods
- Serde-based JSON persistence

**Acceptance criteria:**
- `contains(key)` returns true if issue already created
- `insert(key, issue_number)` persists atomically (write-tmp + rename)
- Handles corrupt/missing index file gracefully (recreate empty)

---

## Sub-issue 3: GitHub issue creation via `gh` CLI

**Goal:** Create well-formatted GitHub issues from classified report entries.

**Design:**
- Shell out to `gh issue create` with structured body
- Body template includes: source SHA, affected paths, classification, suggested tests, evidence snippets
- Labels: `hermes-sync`, `auto-created`, plus classification-specific label (`cli-port`, `skill-import`, etc.)
- Link to parent epic #1261 via body mention

**Files to create/edit:**
- `src/htool_hermes_issue_creator.rs`
- Functions: `create_issue(entry, repo, dry_run) -> Result<Option<u64>>` (returns issue number or None in dry-run)
- `format_issue_body(entry) -> String` — Markdown template
- `format_issue_title(entry) -> String` — e.g., `[Hermes Sync] Port CLI command: foo-bar`

**Acceptance criteria:**
- Issues created with correct labels and body
- Returns created issue number for index persistence
- Errors from `gh` are captured and returned as `Result::Err`, not panics

---

## Sub-issue 4: Dry-run mode

**Goal:** Preview planned actions without creating issues.

**Design:**
- `--dry-run` flag on the orchestrator
- When active, `create_issue` prints the title/body/labels to stdout and returns `None`
- Report at end: `N issues would be created, M already exist (skipped)`

**Files to create/edit:**
- Modify orchestrator (sub-issue 5) to accept `dry_run: bool`
- Modify `htool_hermes_issue_creator.rs` to respect dry-run

**Acceptance criteria:**
- `dry_run=true` produces human-readable output but creates zero GitHub issues
- Exit code 0 on success

---

## Sub-issue 5: Orchestrator integration and cron update

**Goal:** Wire everything together as a Simplicio htool and update the cron script.

**Design:**
- New htool: `hermes_sync_issues` registered in `tool_registry.rs`
- Params: `{ "repo": "string", "dry_run": "bool", "report_path": "string?" }`
- Flow: parse report -> classify -> dedupe -> create issues -> update index -> print summary
- Update `hermes-sync-cron.sh` to call the new htool after step 4

**Files to create/edit:**
- `src/htool_hermes_sync_issues.rs` — Orchestrator
- `src/main.rs` — Add `mod htool_hermes_sync_issues`
- `src/tool_registry.rs` — Add match arm
- `scripts/hermes-sync-cron.sh` — Replace text-file tracking with htool invocation

**Acceptance criteria:**
- `simplicio-runtime hermes_sync_issues --repo wesleysimplicio/simplicio-runtime --dry-run` works end-to-end
- Cron script uses new htool instead of `tracked-features.txt`
- Integration test with mock report data

---

## Dependency graph

```
Sub-issue 1 (parser) ─┐
                       ├──> Sub-issue 5 (orchestrator)
Sub-issue 2 (dedupe)  ─┤
                       │
Sub-issue 3 (creator) ─┤
                       │
Sub-issue 4 (dry-run) ─┘
```

Sub-issues 1-4 can be developed in parallel. Sub-issue 5 integrates them all.

## Estimated effort

| Sub-issue | Effort |
|-----------|--------|
| 1 - Parser/classifier | Medium |
| 2 - Dedupe engine | Small |
| 3 - Issue creator | Medium |
| 4 - Dry-run mode | Small |
| 5 - Orchestrator | Medium |','docs/issues/1261-plan.md','1e3f31a34c74f5036e5bea78a88b915e11561a01220b1085a45704bcc32451a8','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1262-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1262-plan.md','doc: Plan: #1262 — [Hermes Sync] Feed Helo with validated imports','# Plan: #1262 — [Hermes Sync] Feed Helo with validated imports

## Current State

- `scripts/hermes-sync-cron.sh` detects new Hermes commits and identifies features, but does not produce structured per-import learning records.
- `src/memory_command.rs` provides memory-db status/reset but no ingestion of import records.
- `.simplicio-loop/reports/hermes-sync/` evidence directory does not exist.
- No ignore-rule learning from skipped imports.
- No automated GitHub closeout comments with evidence links.

## Sub-tasks

### 1. Define per-import evidence schema
- **File:** `src/hermes_import_record.rs` (new)
- Create `HermesImportRecord` struct with fields: `sha`, `classification` (feat/fix/skip/ignore), `evidence_path`, `future_rule`, `timestamp`, `source_commit_msg`.
- Derive `Serialize`/`Deserialize` via serde.
- Schema version: `simplicio.hermes.import/v1`.

### 2. Create evidence directory and writer
- **File:** `src/hermes_evidence.rs` (new)
- On each sync run, ensure `.simplicio-loop/reports/hermes-sync/` exists.
- Write one JSON file per import: `.simplicio-loop/reports/hermes-sync/{sha}.json` containing `HermesImportRecord`.
- Validate no `.unwrap()` — all I/O errors propagated as `Result`.

### 3. Extend hermes-sync-cron.sh to emit per-import records
- **File:** `scripts/hermes-sync-cron.sh`
- After detecting new commits, invoke `simplicio hermes-record --sha <sha> --class <class>` for each commit.
- The Rust binary writes the JSON record to the evidence directory.
- Collect per-commit classification (feat/fix/chore/skip) and persist.

### 4. Wire memory-db ingestion of import records
- **File:** `src/memory_command.rs` (extend)
- Add `ingest_hermes_records()` method that reads all JSON files from `.simplicio-loop/reports/hermes-sync/`, inserts into `memory_items` table with type `hermes_import`.
- Deduplicate by SHA to avoid re-ingestion.

### 5. Add ignore-rule persistence
- **File:** `src/hermes_ignore_rules.rs` (new)
- Maintain `.simplicio-loop/hermes-ignore-rules.json` — a list of patterns (commit-msg regex or file-path glob) that auto-classify future imports as `skip`.
- When a user marks an import as "skip", append the rule.
- `hermes-sync-cron.sh` checks ignore rules before classifying.

### 6. Add CLI subcommand `hermes-record`
- **File:** `src/main.rs` (extend match arm), `src/htool_hermes_record.rs` (new)
- Accepts `--sha`, `--class`, `--evidence`, `--rule` flags.
- Writes `HermesImportRecord` JSON and optionally appends ignore rule.

### 7. GitHub closeout comments with evidence links
- **File:** `scripts/hermes-sync-cron.sh` (extend)
- After processing all imports, for each commit that maps to a GitHub issue (parsed from commit message `#NNNN`), post a comment via `gh issue comment` with a link to the evidence JSON.
- Template: "Hermes import validated. Evidence: `.simplicio-loop/reports/hermes-sync/{sha}.json`. Classification: {class}."

### 8. Feed Helo with validated records
- **File:** `src/hermes_evidence.rs` (extend)
- After writing evidence records, invoke Helo ingestion endpoint (or local Helo memory command) with the batch of validated records.
- This closes the learning loop: Helo receives structured feedback on what was imported, skipped, or ignored.

## Dependency Order

```
1 (schema) --> 2 (writer) --> 3 (cron extension)
                  |
                  v
              4 (memory-db) --> 8 (Helo feed)
                  |
1 (schema) --> 5 (ignore rules) --> 6 (CLI)
                                      |
                                      v
                                  7 (GH comments)
```

## Acceptance Criteria

- `cargo check` passes after each sub-task.
- No `.unwrap()` in production code.
- Evidence directory populated with real JSON after a sync run.
- `simplicio hermes-record` CLI works end-to-end.
- Ignore rules prevent re-classification of known-skip imports.
- GitHub issues receive closeout comments with evidence links.','docs/issues/1262-plan.md','e078c8231861e34dfc8b429433211a2f51fc5a38d8bd18a0f1ff1b9375838e10','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1263-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1263-plan.md','doc: Plan: #1263 — Visual grounding/audit via LocateAnything-3B','# Plan: #1263 — Visual grounding/audit via LocateAnything-3B

## Context

`src/visual_grounding.rs` has scaffolding (structs, `locate` command, Qwen3-VL config) but `locate()` is a placeholder returning `Err`. This epic adds LocateAnything-3B as a backend, implements HF Inference API for remote execution, creates a `simplicio validate --visual` CLI surface, integrates with the `deliver dogfood` pipeline, and benchmarks latency.

## Sub-tasks

### 1. Add LocateAnything-3B backend to `visual_grounding.rs`
- **File**: `src/visual_grounding.rs`
- Add `GroundingBackend` enum: `QwenVL`, `LocateAnything3B`, `HfInference`
- Update `GroundingConfig` with `backend: GroundingBackend` field
- Implement `locate()` for the local LocateAnything-3B path (llama.cpp or transformers CLI invocation via `Command`)
- Parse bounding box output from model stdout (JSON or structured text)
- Keep Qwen3-VL as a fallback backend

### 2. HF Inference API remote backend (MVP)
- **File**: `src/visual_grounding.rs` (or new `src/hf_inference_grounding.rs`)
- HTTP POST to `https://api-inference.huggingface.co/models/OneChart/LocateAnything-3B` (or equivalent endpoint)
- Use `ureq` or `std::process::Command` calling `curl` to avoid heavy deps
- Read `HF_TOKEN` from env for authentication
- Parse JSON response into `Vec<DetectedRegion>`
- Timeout and retry logic (no `.unwrap()`)

### 3. `simplicio validate --visual` CLI surface
- **Files**: `src/main.rs`, `src/visual_grounding.rs`
- Add `--visual` flag to the existing `validate` subcommand (or new subcommand)
- Takes a screenshot (or `--image` path), runs `locate()` against expected UI elements
- Outputs pass/fail with bounding box coordinates
- JSON output mode (`--json`) for CI integration

### 4. Integration with `deliver dogfood` pipeline
- **File**: `src/skill_dogfood.rs`
- After existing delivery checks, optionally run visual grounding validation
- Gate on `--visual` flag or config setting `delivery.visual_check = true`
- Capture screenshot of deployed app, run locate for expected elements
- Append visual check result to `DeliveryCertificate`

### 5. Benchmark latency
- **File**: `src/benchmark_suite.rs` or new `src/bench_visual_grounding.rs`
- Measure: local Qwen3-VL, local LocateAnything-3B, HF Inference API
- Report p50/p95/p99 latency per backend
- Include in `simplicio benchmark` output

## Dependency order

```
[1] LocateAnything-3B backend
[2] HF Inference API backend  (depends on 1 for shared types)
[3] validate --visual CLI     (depends on 1 or 2)
[4] deliver dogfood integration (depends on 3)
[5] Benchmark latency          (depends on 1 and 2)
```

## Acceptance criteria

- `simplicio locate "submit button" --image screenshot.png` returns bounding boxes from LocateAnything-3B
- `simplicio validate --visual` runs against a live screenshot and reports pass/fail
- `simplicio deliver dogfood --visual` includes visual audit in the delivery certificate
- HF Inference API works as fallback when no local model is installed
- No `.unwrap()` in production paths; all errors return `Result`
- Latency benchmark included in CI','docs/issues/1263-plan.md','576bf22214c14182c9bcc9477cbabbe45f7b3571374f61014b5f6f6a6ff34512','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1264-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1264-plan.md','doc: Epic #1264: [Simplicio Mobile] React Native Dispatch App','# Epic #1264: [Simplicio Mobile] React Native Dispatch App

## Overview

Mobile companion app for Simplicio desktop, enabling field dispatchers to approve/reject AI-generated actions, monitor agent activity, and interact via voice-first interface. Built with React Native (Expo) targeting iOS and Android.

**Dependencies:** Desktop epic #1244, related issues #1247-#1258.

---

## Sub-issues Decomposition

### Phase 1: Foundation

#### 1264-A: Expo scaffold and project setup
- Initialize Expo managed workflow with TypeScript
- Configure ESLint, Prettier, Jest
- Set up CI (GitHub Actions) for build/test
- Navigation structure (React Navigation)
- **Estimate:** 3 points

#### 1264-B: Device pairing via QR code
- Desktop generates a time-limited pairing QR containing a signed token
- Mobile scans QR (expo-camera), exchanges token for a session JWT
- Store credentials in expo-secure-store
- Unpair flow and multi-device management
- **Depends on:** #1244 (desktop runtime), 1264-A
- **Estimate:** 5 points

#### 1264-C: Dispatch gateway protocol (WebSocket)
- Define WebSocket message schema (JSON) for dispatch events
- Rust-side gateway endpoint in simplicio-runtime (`src/gateway_ws.rs`)
- Reconnection, heartbeat, and backpressure handling on mobile
- Message signing/verification (HMAC shared secret from pairing)
- **Depends on:** 1264-B
- **Estimate:** 8 points

### Phase 2: Core Features

#### 1264-D: Real-time dispatch streaming UI
- WebSocket integration with React state (zustand or context)
- Live feed of pending dispatches with status badges
- Pull-to-refresh and offline queue
- **Depends on:** 1264-C
- **Estimate:** 5 points

#### 1264-E: Approval/rejection UI
- Swipe-to-approve, swipe-to-reject gestures
- Detail view with full action context (tool name, params, risk level)
- Batch approval for low-risk actions
- Undo window (configurable, default 5s)
- **Depends on:** 1264-D
- **Estimate:** 5 points

#### 1264-F: Growth approval policy sync
- Read and display `growth-approval-policy.schema.json` rules on mobile
- Allow editing thresholds (e.g., auto-approve below $X)
- Sync policy changes back to desktop via WebSocket
- **Depends on:** 1264-C, schema file
- **Estimate:** 5 points

### Phase 3: Voice and Intelligence

#### 1264-G: Voice-first input and TTS
- expo-speech for TTS readout of pending dispatches
- expo-av for voice recording, send audio to desktop for STT
- Voice commands: "approve", "reject", "details", "skip"
- Hands-free mode toggle
- **Depends on:** 1264-E
- **Estimate:** 8 points

#### 1264-H: Token savings dashboard
- Aggregate token usage data from desktop runtime
- Charts (victory-native or react-native-chart-kit): daily/weekly/monthly
- Cost projections and savings vs. manual baseline
- **Depends on:** 1264-C
- **Estimate:** 5 points

### Phase 4: Platform Integration

#### 1264-I: Push notifications
- expo-notifications setup with FCM (Android) and APNs (iOS)
- Desktop triggers push for high-priority dispatches when app is backgrounded
- Notification categories with inline approve/reject actions
- **Depends on:** 1264-C
- **Estimate:** 5 points

#### 1264-J: Entitlement sync
- Sync license/entitlement state from desktop
- Feature gating based on plan tier
- Graceful degradation when entitlement expires
- **Depends on:** 1264-B
- **Estimate:** 3 points

#### 1264-K: App store distribution
- EAS Build configuration for iOS and Android
- App Store Connect and Google Play Console setup
- Beta distribution via TestFlight and internal testing track
- Store listing assets (screenshots, description)
- **Depends on:** all above
- **Estimate:** 5 points

---

## Suggested Implementation Order

```
1264-A → 1264-B → 1264-C → 1264-D → 1264-E → 1264-F
                         ↘ 1264-H
                         ↘ 1264-I
              1264-B → 1264-J
         1264-E → 1264-G
         All → 1264-K
```

## Total Estimate: ~57 points

## Risk Areas
- WebSocket reliability on mobile networks (mitigate with offline queue + retry)
- Voice recognition accuracy for dispatch commands
- App store review timelines for initial submission','docs/issues/1264-plan.md','667f6dd2801853ff72d6596743566f921d3af93741e9b451ccbb697931508076','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1265-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1265-plan.md','doc: Epic Plan: #1265 - [Simplicio Mobile] Define dispatch architecture','# Epic Plan: #1265 - [Simplicio Mobile] Define dispatch architecture

## Overview

Define the dispatch architecture for Simplicio Mobile, covering how tool calls are routed between mobile clients, desktop clients, and the runtime. This includes event schemas, trust/pairing flows, approval mechanisms, and sequence diagrams.

**Parent epic:** #1264  
**Related issues:** #1244 (multi-agent), #1247-#1250, #1254, #1258

---

## Sub-tasks

### 1. Write DISPATCH_ARCHITECTURE.md
**File:** `docs/mobile/DISPATCH_ARCHITECTURE.md`  
**Scope:**
- Define dispatch model: mobile as thin relay vs. local executor
- Document which tool categories execute locally on mobile vs. delegated to desktop/runtime
- Define message routing: mobile -> runtime -> desktop (and reverse)
- Latency and offline behavior requirements
- Capability negotiation protocol (mobile declares what it can handle)

### 2. Define event schemas (JSON)
**File:** `schemas/multi-agent-dispatch.schema.json`  
**Scope:**
- `dispatch_request` schema: source, target, tool_name, params, priority, timeout
- `dispatch_response` schema: result, error, execution_time, executor_id
- `dispatch_ack` schema: received confirmation with estimated completion
- `capability_announcement` schema: agent declares supported tools/platforms
- `session_sync` schema: state synchronization between mobile and desktop

### 3. Create sequence diagrams
**File:** `docs/mobile/DISPATCH_SEQUENCES.md`  
**Scope:**
- Mobile user triggers tool -> runtime dispatches to desktop -> result returns
- Mobile user triggers tool -> runtime executes locally -> result returns
- Desktop initiates action requiring mobile confirmation (camera, GPS, etc.)
- Conflict resolution when both mobile and desktop request same resource
- Timeout and retry sequences

### 4. Document trust/pairing/approval flows
**File:** `docs/mobile/TRUST_AND_PAIRING.md`  
**Scope:**
- Device pairing protocol (QR code, shared secret, or OAuth-based)
- Approval levels: auto-approve (read-only), prompt (write), block (destructive)
- Session token lifecycle and renewal
- Revocation flow (unpair device)
- Relationship to #1254 (security boundaries)

### 5. Document relationship with multi-agent (#1244)
**File:** `docs/mobile/MULTI_AGENT_INTEGRATION.md`  
**Scope:**
- How mobile dispatch integrates with multi-agent orchestration from #1244
- Agent identity: mobile as a distinct agent vs. extension of desktop agent
- Shared context and memory between mobile and desktop agents
- Priority and preemption rules when multiple agents compete for dispatch

### 6. Implement dispatch helpers in Rust
**File:** `src/tool_dispatch_helpers.rs`  
**Scope:**
- `DispatchTarget` enum: `Local`, `Remote(AgentId)`, `MobileRelay`
- `DispatchPolicy` struct: routing rules per tool category
- `resolve_dispatch_target()` function: given a tool call and available agents, return target
- Serialization/deserialization of dispatch events (serde)
- No `.unwrap()` in production paths

---

## Dependency graph

```
#1244 (multi-agent) ─┐
#1247-#1250 (mobile)─┼─> #1265 (this epic) ─> #1264 (parent)
#1254 (security) ────┘
#1258 (offline) ─────┘
```

## Acceptance criteria

- [ ] All 5 documentation files exist and are internally consistent
- [ ] JSON schema validates with `jsonschema` tooling
- [ ] `tool_dispatch_helpers.rs` compiles with `cargo check`
- [ ] Sequence diagrams cover happy path + error/timeout paths
- [ ] Trust model explicitly addresses mobile-specific threats (lost device, untrusted network)','docs/issues/1265-plan.md','5a4fd5d750d1e7262526dc1640fae9f35dbf287aebf72ef6a0608d77ae531f4b','doc,simplicio',1.1);
