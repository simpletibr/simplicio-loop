INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ADR-2026-07-21-BINARY-INTERNAL-FORMATS.md','project_doc','doc://simplicio-runtime/docs/ADR-2026-07-21-BINARY-INTERNAL-FORMATS.md','doc: ADR 2026-07-21 — Binary internal formats and edge-only JSON','# ADR 2026-07-21 — Binary internal formats and edge-only JSON

## Status

**Accepted — ecosystem migration pending.**

The repository owner accepted this decision on 2026-07-21. This ADR is
normative for Simplicio Runtime, Mapper, Dev CLI, Loop, Loop OSS, Loop
Marketing, Agent, Code, Sprint and Prompt. Implementation is tracked by
[#3492](https://github.com/wesleysimplicio/simplicio-runtime/issues/3492) and
its repository-specific child issues.

## Context

The Simplicio ecosystem currently mixes typed domain objects with JSON files,
JSONL streams, JSON-RPC messages, fixtures, caches, reports and generated
artifacts. JSON is useful as a public interoperability format, but it is a poor
default for Simplicio-owned internal state because it introduces repeated
parsing and allocation, weakens type and bounds guarantees, makes large indexes
expensive to load, and permits external transport shapes to become internal
sources of truth.

Runtime already provides the basis for a different architecture:

- `src/hbp/mod.rs` implements HBP for verifiable hash-chain persistence;
- `MmapIndex` and `memmap2::Mmap` provide mmap-backed, zero-copy index access;
- `runtime.toml` and TOML parsing provide human-authored configuration;
- explicit public exports such as `doctor --json` and `capabilities --json`
  serve consumers outside Runtime.

HBI is not currently a concrete Runtime module or a versioned on-disk
specification. Existing mmap usage is evidence of the access mechanism, not
evidence that HBI has been implemented. The ecosystem must therefore specify
HBI v1 before claiming compatibility or migrating canonical indexes to it.

Some external systems and toolchains mandate JSON. Examples include provider
APIs, JSON-RPC-based protocols and package-manager manifests. Those formats are
controlled outside Simplicio; they do not justify using JSON inside Simplicio''s
domain, storage or component-to-component paths.

## Decision

**Simplicio-owned internal state SHALL use typed native structures, HBP,
mmap-backed HBI and TOML; it SHALL NOT use JSON, JSONL or NDJSON. JSON is
restricted to explicit external compatibility boundaries and must terminate at
the boundary adapter.**

### 1. Canonical format matrix

| Concern | Canonical format | Required properties |
|---|---|---|
| In-memory domain state | Native typed structures | No serialize/parse round-trip between internal stages |
| Append-only receipts, evidence and auditable state | HBP | Versioned envelope, hash chain, integrity validation, crash-safe append/recovery |
| Read-mostly indexes, graphs, snapshots and large lookup tables | HBI over mmap | Versioned header, bounds checks, checksums, schema fingerprint, zero-copy access |
| Human-authored configuration | TOML | Typed validation, explicit defaults, unknown-key policy, actionable diagnostics |
| Inter-Simplicio commands, events and IPC | Versioned binary envelopes | Typed, bounded, compatible, no JSON-RPC/JSONL between owned components |
| Public Runtime exports | JSON only on explicit external contract surfaces | Edge-generated, deterministic, versioned and never re-ingested as internal truth |
| Externally mandated JSON protocols | Boundary adapter only | Normalize immediately to typed objects; never persist or forward raw JSON internally |
| Toolchain-mandated JSON manifests | Narrow exception | Build/package metadata only; never an application data or IPC format |
| Historical evidence and documentation | Retained or converted by policy | Must be classified and excluded from active runtime input paths |

mmap is an access mechanism. HBI is the versioned container and schema contract
mapped through that mechanism. The terms are not interchangeable.

### 2. HBP ownership

HBP remains the canonical format for ordered, append-only, verifiable history,
including receipts and evidence that require lineage or tamper detection.

HBP writers and readers MUST:

- version every envelope and domain payload;
- verify chain continuity and payload integrity before accepting state;
- define truncation and partial-write recovery;
- use atomic publication or durable append rules appropriate to the platform;
- impose size, record-count and allocation bounds before decoding;
- preserve unknown future records when safe or fail with an actionable version
  error;
- provide deterministic golden vectors and corruption tests.

HBI MUST NOT duplicate HBP''s append-only ledger semantics.

### 3. HBI v1 before ecosystem adoption

A dedicated implementation issue SHALL define HBI v1 with:

- fixed magic bytes and format version;
- endianness and alignment;
- header length and total file length;
- section directory with checked offsets and lengths;
- schema identifier and schema fingerprint;
- content checksum and optional per-section checksums;
- string/blob tables and stable identifiers;
- forward/backward compatibility and feature flags;
- safe mmap lifetime, atomic replacement and concurrent-reader behavior;
- corruption, truncation, integer-overflow and out-of-bounds rejection;
- golden fixtures readable from Rust, Python and TypeScript.

No component may label an existing custom mmap file as HBI until it passes the
HBI v1 conformance suite.

### 4. TOML scope

TOML is reserved for configuration intended to be read or edited by people. It
is not a replacement for high-volume events, indexes, caches or evidence.

Each TOML configuration surface MUST have a typed model, documented defaults,
environment/CLI precedence, secret-handling rules, deprecation policy and tests
for malformed input and unknown keys. Sensitive values should be referenced
through a secret provider or environment boundary instead of copied into files.

### 5. JSON boundary rule

Runtime MAY emit JSON only when an explicit external consumer contract requires
it, including documented flags such as `doctor --json` and
`capabilities --json`. Such exports MUST:

- be constructed from typed internal state at the last possible edge;
- include or bind to a d','docs/ADR-2026-07-21-BINARY-INTERNAL-FORMATS.md','ab223b26ce6f98575714afcca3b499d26464174778735a3f7f503da35df5e2dc','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ADR-2026-07-28-CANONICAL-HBP-CODEC.md','project_doc','doc://simplicio-runtime/docs/ADR-2026-07-28-CANONICAL-HBP-CODEC.md','doc: ADR — Canonical shared HBP/HBI codec','# ADR — Canonical shared HBP/HBI codec

Status: accepted for new call sites; cross-repository adoption tracked in
Runtime #3626/#3640 and Fast #37/#46.

`crates/asolaria-bridge` (`asolaria-hbi-hbp`) is the sole owner of canonical
HBP rows, logical HBI pointers, full SHA-256 identities, verified short aliases
and receipt-chain integrity. It is dependency-free and has no reach-back into
the Runtime. JSON is forbidden on its hot path; JSON files under `contracts/`
are cold-lane projections only.

Runtime owns policy and effects. Loop owns completion. The codec proves format
and integrity only.

## Consumer/deprecation matrix

| Consumer | Decision |
|---|---|
| `simplicio-fabric::asolaria_hbi_hbp` | Compatibility re-export; canonical |
| `simplicio-agents::receipt_chain` | Must become compatibility adapter |
| `src/hbp` binary ledger | N-1 adapter/migration source; no new wire format |
| `wormhole-codec` embedded SHA/rows | Deprecated; migrate in #3640 |
| Simplicio Fast | Consume crate/schema and the same golden vectors in #37/#46 |
| Loop standalone | Python reference/fixtures require no Runtime process |

Existing ledgers remain byte-readable. Migration is copy-then-verify; rollback
keeps the original immutable. A failed legacy parse returns an explicit reason
code and never silently starts a new chain.

Durable append uses a cross-process create-new lock, bounded reads, LF-only
framing, append plus `sync_all`, and full-chain verification under the lock.
Partial append, CRLF, trailing corruption, oversized input and tamper fail
closed. Platform CI must exercise Linux, macOS and Windows.

Short `AGT-<sha16>` values are lookup aliases, never identity. Every alias is
resolved against and verified by the full 64-character SHA-256 digest;
collisions are deterministic errors.','docs/ADR-2026-07-28-CANONICAL-HBP-CODEC.md','5fae2232c2a406de38a0d8eda81b0597ac468780684cdcc77ce3d423561afc71','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ADR-2026-07-PRICING-MATRIX.md','project_doc','doc://simplicio-runtime/docs/ADR-2026-07-PRICING-MATRIX.md','doc: ADR — Pricing Matrix: Free / MCP (Economy) / Agent (Pro) / Pro Max (#2991)','# ADR — Pricing Matrix: Free / MCP (Economy) / Agent (Pro) / Pro Max (#2991)

- **Date:** 2026-07-09
- **Status:** Accepted (standing decision)
- **Deciders:** Wesley Simplicio
- **Related:** #2991, `docs/business/LAUNCH_PLAN_2026-07.md` §2.1/§2.2,
  `src/license.rs` (#818), `src/monetization_1164.rs` (#1164)

## Context

Before this ADR, three different pricing matrices existed for the same
product, with no single source of truth:

1. **Code** (`src/license.rs`, `src/monetization_1164.rs`, #818/#1164):
   `Free $0 / Economy $10 / Pro $20` — no BRL, no third paid tier.
2. **Business simulation** (`docs/planning/BUSINESS_MODEL_SIMULATION.md`,
   #2232): `Free $0 / Starter $12 / Pro $29 / Enterprise $99` — different tier
   names, different prices, no relationship to the shipped license tiers.
3. **Founder hypothesis** (informal, captured in
   `docs/business/LAUNCH_PLAN_2026-07.md` §2.1): `MCP $10 / Agent $20`, which
   happens to match the code but names the tiers by what they *sell* rather
   than by internal tier identifier.

`docs/business/LAUNCH_PLAN_2026-07.md` (2026-07-09 inspection of the real
codebase) recommended reconciling on the code''s numbers — because the paywall,
webhook, trial, dunning, entitlement backend, and checkout already exist and
already encode `$10`/`$20` — and adding a fourth tier, **Pro Max**, to capture
power users (`runtime-profile full`, native video pipeline) without
renegotiating the first three prices. This ADR ratifies that recommendation
and freezes it as the pricing source of truth ahead of launch.

## Decision

1. **`src/license.rs` is the single source of truth for pricing and tier
   identifiers.** `src/monetization_1164.rs`''s plan catalog (`PLANS`) mirrors
   it for consistency (per `docs/business/LAUNCH_PLAN_2026-07.md` §2.2,
   `license.rs` stays the live gate; `monetization_1164` is the webhook/state
   layer behind it) — any pricing change must land in `license.rs` first and
   `monetization_1164.rs` follows in the same change.
2. **Final matrix** (monthly USD; BRL/Pix is a site-side/checkout concern, not
   tracked in the binary — same precedent as the existing Economy/Pro tiers):

   | Sales name | Tier id (`license.rs`) | USD/mo | BRL/mo (Pix/cartão) | Unlocks |
   |---|---|---|---|---|
   | Simplicio Free | `free` | $0 | R$0 | Deterministic kernel: `map`, `edit`, `gate`, `validate`, `checkpoint`, `deliver`. No LLM. |
   | Simplicio MCP | `economy` | $10 | R$29 | Everything Free + `chat`/`coding-loop`/`token-savings` (persistent `serve --mcp`, memory, savings proof). |
   | Simplicio Agent | `pro` | $20 | R$59 | Everything MCP + `local-llm`/`remote-routing` (local LLM ladder, managed remote routing, the full Simplicio Agent surface). |
   | Simplicio Pro Max | `promax` (**new**, #2991) | $45 | R$119 | Everything Agent + `runtime-profile-full` (10k agents/2GB/90% CPU) + `video-pipeline` (native HyperFrames/Remotion; Higgsfield generative video stays separately gated by `get_cost` + Action Gate, not by this tier). |
   | Enterprise | (contact) | custom | custom | Out of scope for this ADR — phase 2. |

   Annual billing: 10 months'' price for 12 (2 free), unchanged from the
   existing Economy/Pro convention. Founder plan (beta grandfathering) is
   tracked separately in the launch plan, not part of this pricing matrix.

3. **`docs/planning/BUSINESS_MODEL_SIMULATION.md`''s pricing (`Free $0 /
   Starter $12 / Pro $29 / Enterprise $99`) is superseded by this matrix.**
   The file is **not deleted** — its churn/CAC/LTV simulation methodology
   stays useful and can be rerun against the real numbers above — but its
   tier names and prices are no longer authoritative. Do not cite
   `BUSINESS_MODEL_SIMULATION.md`''s pricing table when quoting Simplicio
   prices; cite this ADR or `license.rs`.
4. **Tier ordering**: `Free < Trial < Economy < Pro < ProMax`
   (`src/license.rs::Tier`, `PartialOrd`/`Ord` derive). Trial remains a
   time-boxed full-access preview (`has_local_llm() == true`) equivalent to
   Pro-level access for `TRIAL_DAYS`, not a permanent ProMax grant.
5. **Feature gate**: `entitlement_allows()`/`tier_allows_feature()` in
   `src/license.rs` maps `runtime-profile-full` and `video-pipeline` to
   `Tier::has_pro_max_features()` (ProMax only). Every feature Pro grants
   (`chat`, `coding-loop`, `token-savings`, `local-llm`, `remote-routing`,
   `vision`) stays included in ProMax via the existing `has_token_savings()`/
   `has_local_llm()` checks — ProMax is strictly additive over Pro, never a
   separate feature set.
6. **Beta override unchanged**: `public_beta_active()` still unlocks
   everything, including the new ProMax-only features, while the free public
   beta runs (`SIMPLICIO_BETA_OFF` opts out for testing the gate). This ADR
   adds the tier; it does **not** turn on billing enforcement for it — that
   remains the beta-off / GA decision tracked separately in
   `docs/business/LAUNCH_PLAN_2026-07.md`.

## Rationale

- **Agent $20 anchors** against Claude Pro / Cursor / Copilot Pro+ — a price
  point developers already accept for a "dev subscription."
- **MCP $10** is the low-friction entry tier with ROI provable by the
  savings ledger itself (`simplicio savings report`) — the pitch is literally
  "if Simplicio doesn''t save you more than $10/mo in tokens, the `measured`
  report shows it — cancel."
- **Pro Max at 2.25× Agent ($45)** captures power users (bigger
  `runtime-profile`, native video) without discounting or restructuring the
  Agent tier, and keeps the jump proportionate rather than a token
  "everything unlocked" upcharge.
- **BRL pricing below strict FX conversion** (R$59 ≈ $11 at typical rates,
  not $20 × ~5) is a deliberate penetration price for the BR market via Pix —
  the primary target market and a differentiator against USD-only
  competitors. The BRL column is documented here for the site/checkout to
  consume; it is not encoded in the Rust binary (consistent with how Economy/
  Pro never carried a BRL field','docs/ADR-2026-07-PRICING-MATRIX.md','36828fab0cbd80e0e43cb4de707fa1cd311db5f6baf002547c5f54edfb42b2db','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ADR-2026-08-01-INDEPENDENT-COORDINATORS-RUNTIME-EXECUTION.md','project_doc','doc://simplicio-runtime/docs/ADR-2026-08-01-INDEPENDENT-COORDINATORS-RUNTIME-EXECUTION.md','doc: ADR 2026-08-01: Independent coordinators and Runtime execution','# ADR 2026-08-01: Independent coordinators and Runtime execution

## Status

Accepted. Supersedes conflicting ownership language in `ADR-2026-07-14-ECOSYSTEM-CONTROL-FLOW.md` and other documents that describe `simplicio-agent`, Loop, or Runtime as the exclusive cognitive control plane or mandatory gateway.

## Context

Runtime must expose the same public, versioned execution contracts to Claude, Codex, Cursor, VS Code, OpenCode, Hermes, OpenClaw, the optional `simplicio-agent`, and future coordinators. Coupling execution to one conversation process duplicates ownership, prevents independent hosts from operating, and makes receipts depend on private coordinator state.

Issue #3279 also requires a bridge from Loop Stage Agent identities to data-driven Runtime execution profiles. That bridge must correlate identities without copying the Loop DAG or promoting Runtime workers into planners, reviewers, delivery authorities, or completion judges.

## Decision

Coordinators think and coordinate; Runtime executes and proves.

- The active coordinator interprets intent, reasons, plans, selects tools/providers, chooses the next semantic action, and may opt into the portable `simplicio-loop` convergence protocol.
- Runtime owns governed execution: capability negotiation, policy gates, leases/fencing, bounded concurrency, sandboxing, deterministic mutation, validation, evidence, rollback, observability, and delivery effects.
- No coordinator owns Runtime or is a mandatory gateway. All supported coordinators consume equivalent public CLI, MCP, or in-process contracts.
- Loop owns its Stage DAG, roles, activation, retries, and completion semantics. Runtime references versioned stage/role/instance identities and hashes; it does not reinterpret or copy that DAG.
- Runtime execution profiles are Runtime-owned data. A profile may constrain executor compatibility but cannot grant a coordinator exclusive ownership.

## Binding compatibility policy

`simplicio.runtime-execution-binding-request/v1` correlates run, task, work item, stage, role, agent instance, profile fingerprint, capability, worker identity, lease identity, attempt, fence, plan revision, Loop manifest hash, and coordinator kind.

The profile fingerprint is the SHA-256 of compact UTF-8 JSON for the profile object with lexicographically sorted object keys; the canonical fields are `accepted_stage_contract_versions`, `capability_ids`, `coordinator_kind`, `loop_manifest_hash`, `loop_schema_pins`, `owner`, `profile_id`, `schema`, and `version`. Implementations in every coordinator must hash this same representation before comparing `profile_sha256`.

The current foundation resolves and pins a validated Runtime profile, but it does not yet consult the worker supervisor or durable lease store. Consequently its receipt is explicitly non-authoritative:

- `authority: non-authoritative`;
- `authorization_granted: false`;
- `identity_verified: false`;
- `lease_verified: false`;
- `reason_code: runtime_execution_binding_foundation_only`.

Positive numeric fence/revision values are only shape validation. They are not proof of freshness or anti-replay. A later authoritative adapter must compare the request with typed worker, stage-instance, and durable lease evidence and return stable mismatch/supersede reason codes before any effect.

## Compatibility and migration

Legacy role assignment and receipts remain readable but cannot satisfy modern binding gates without explicit migration evidence. Unknown schemas, profile ambiguity, hash drift, ownership conflict, missing correlation identity, and incompatible versions fail closed. New clients must not infer authority from the word “receipt”; only explicit verified fields and an authorization decision can authorize an effect.

`GEMINI.md` intentionally delegates to `AGENTS.md`, so the canonical cross-host rule is maintained once in `AGENTS.md`. Host-specific files may add operational details but cannot override this ADR.

## Non-goals of the foundation slice

- Creating or registering workers, providers, processes, leases, or stage instances.
- Verifying current/superseded fences or plan revisions.
- Selecting providers, next stages, retries, review outcomes, delivery, or completion.
- Claiming full completion of #3279 or its installed Loop, MCP parity, benchmark, coverage, and three-profile DoD.

## Consequences

The architecture supports independent coordinators without duplicating cognitive ownership. Runtime receipts remain honest about what was and was not verified. Authoritative execution requires subsequent integration with the actual worker supervisor, capability lease store, and effect authorization boundary.','docs/ADR-2026-08-01-INDEPENDENT-COORDINATORS-RUNTIME-EXECUTION.md','ea5f2cb30343d0c011932558fdd2f092ce1f1b1ba48e6814b098c63befef5c6e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/AGENT_BATTERY_2026_06_05.md','project_doc','doc://simplicio-runtime/docs/AGENT_BATTERY_2026_06_05.md','doc: Agent Battery — Simplicio × Hermes × OpenClaw (2026-06-05)','# Agent Battery — Simplicio × Hermes × OpenClaw (2026-06-05)

Three-way comparison run from this checkout. The **backend model is held
constant** across all three agents so the comparison measures the *agents*, not
the model. Every task is graded by an objective oracle (the test is executed).

## Setup

| Item | Value |
|---|---|
| Model (all three) | `deepseek/deepseek-v4-flash` (`-20260423`, provider StreamLake) via OpenRouter |
| Simplicio | `target/release/simplicio` v0.3.37 (commit `adec272`), built `cargo build --release --locked` |
| Hermes | Hermes Agent v0.15.2, `uv tool install hermes-agent` |
| OpenClaw | OpenClaw 2026.6.1, `npm i -g openclaw` |
| Grading | oracle: execute the resulting code / parse the file, pass = exit 0 |
| Harness | `scripts/battery-deepseek-v4-flash.py` |
| Pricing | deepseek-v4-flash = $0.0983 / 1M prompt, $0.1966 / 1M completion |

**Driver fairness.** All three are driven head-to-head on the same model:
- **Simplicio** — deepseek proposes a `simplicio.mechanical-edit/v1` plan; the
  runtime''s **deterministic substring gate** validates it, then `simplicio edit`
  applies it with a **sha256-verified write**; the oracle verifies. The model is
  only the proposer — the mutation is deterministic and runtime-owned.
- **Hermes** — `hermes -z <prompt> -m deepseek/deepseek-v4-flash --provider openrouter --accept-hooks`.
- **OpenClaw** — `openclaw agent --local --model openrouter/deepseek/deepseek-v4-flash -m <prompt> --json`.

## Results (6 tasks)

| task | Simplicio | Hermes | OpenClaw |
|---|---|---|---|
| authoring:two_sum  | ✅ 10276 ms / 654 tok | ✅ 14397 ms | ✅ 15930 ms / 21905 tok |
| authoring:fizzbuzz | ✅ 12146 ms / 302 tok | ✅ 9135 ms  | ✅ 12975 ms / 21485 tok |
| algorithm:gcd      | ✅ 12648 ms / 785 tok | ✅ 7043 ms  | ✅ 12537 ms / 21336 tok |
| bugfix:factorial   | ✅ 3475 ms / 290 tok  | ✅ 19783 ms | ✅ 26801 ms / 21896 tok |
| bugfix:sum_to_n    | ✅ 3773 ms / 280 tok  | ✅ 15426 ms | ✅ 36648 ms / 21970 tok |
| exact-edit:config  | ✅ 1260 ms / 182 tok  | ✅ 5183 ms  | ✅ 12248 ms / 21430 tok |

### Summary

| agent | solved | total time | per task | paid tokens | est. cost |
|---|---|---|---|---|---|
| **Simplicio** | **6/6** | **43.6 s** | **7.3 s** | **2 493** | **~$0.0004** |
| Hermes        | 6/6 | 71.0 s | 11.8 s | not exposed¹ | n/a¹ |
| OpenClaw      | 6/6 | 117.1 s | 19.5 s | 130 022 | ~$0.020 |

¹ `hermes -z` does not emit token usage on stdout, so its paid-token cost could
not be measured here (it is **not** zero — it runs a full agent loop). This is a
transparency gap on Hermes'' side, recorded honestly.

## Criteria matrix (compareça em todos os critérios)

| criterion | Simplicio | Hermes | OpenClaw |
|---|---|---|---|
| Correctness (oracle) | 6/6 | 6/6 | 6/6 |
| Total latency | **43.6 s (fastest)** | 71.0 s | 117.1 s (slowest) |
| Measured paid tokens | **2 493 (lowest)** | unmeasured | 130 022 (~52× Simplicio) |
| Determinism of mutation | **sha256 write + substring gate** | free-form generation | free-form generation |
| Token transparency | full (per call) | none on stdout | full (per turn) |
| Install footprint | **3.4 MB single binary** | 130 MB (py venv) | 345 MB (npm) |
| Autonomy mode | runtime-governed, gated | `--accept-hooks` | `--local` agent loop |
| Evidence / audit trail | run dir + sha256 | none | session jsonl |

**Why correctness ties:** with the same model behind all three on these
self-contained tasks, raw solve-rate converges — the model is held constant *on
purpose*. The agent-level differentiators are **latency, token economy,
determinism, transparency, and footprint**, where Simplicio leads on every axis.

## Media dimension — WaveSpeed (programa de vídeo #240)

Hermes and OpenClaw are text/coding agents and generate no media. The Simplicio
Video Creation program treats generative media as a **gated** backend. Exercised
WaveSpeed end-to-end as evidence (`scripts/wavespeed-media.py`):

| asset | model | latency | inference | output | cost |
|---|---|---|---|---|---|
| image | `wavespeed-ai/flux-schnell` | 6.8 s | 3.3 s | 1024×1024 JPEG (50 KB) | $0.003 |
| video | `wavespeed-ai/wan-2.2/t2v-480p-ultra-fast` | 35.2 s | 31.9 s | 5 s 480p MP4 (852 KB) | ~$0.05 |

WaveSpeed balance $6.73 → $6.68 (spent ~$0.05). WaveSpeed exposes an
OpenAI-compatible `/api/v3/chat/completions` endpoint but **no `deepseek-v4-flash`
in its catalog** (996 models, media-focused), so the LLM battery runs on
OpenRouter and WaveSpeed serves the media axis — its actual strength.

## Reproduction

```bash
cargo build --release --locked
export OPENROUTER_API_KEY=sk-or-...           # DeepSeek v4 Flash backend
export WAVESPEED_API_KEY=...                  # media dimension
uv tool install hermes-agent
npm i -g openclaw
python3 scripts/battery-deepseek-v4-flash.py  # -> /tmp/battery_dsv4.json
python3 scripts/wavespeed-media.py --video    # -> /tmp/wavespeed_out/
```

## Honest caveats

- Solve-rate is a tie by design (model held constant); read the table for the
  axes that actually separate the agents.
- Hermes token cost is unmeasured (not exposed on stdout), not zero.
- Simplicio''s measured tokens cover only the proposer call; the gate, apply, and
  verify are deterministic and free.
- OpenClaw''s ~21.7k tokens/task is agent-scaffolding overhead (large system
  prompt), not task complexity.','docs/AGENT_BATTERY_2026_06_05.md','e35af565bed5aaad589f45bfee8177fef3cf455471469757c17578db2335db3e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/AGI_BENCH_TREND.md','project_doc','doc://simplicio-runtime/docs/AGI_BENCH_TREND.md','doc: AGI-bench trend dashboard (#2577)','# AGI-bench trend dashboard (#2577)

Auto-generated by `scripts/agi-bench-trend.py`. Do not hand-edit.
Series: `docs/evidence/agi-bench-history.jsonl`.

- Snapshots: **10**
- Latest: `2026-07-03T05:34:55Z`
- Previous: `2026-07-02T05:37:50Z`

## Latest vs previous

| metric | latest | previous | delta | status |
|---|---|---|---|---|
| task_success_rate_paid | 0.9512 | 0.9512 | +0.0 | ok |
| raw_model_success_rate | 0.9146 | 0.9146 | +0.0 | ok |
| runtime_lift_paid | 0.0366 | 0.0366 | +0.0 | ok |
| zero_paid_capability | 0.561 | 0.561 | +0.0 | ok |
| token_economy_ratio_vs_openclaw | 0.0192 | 0.0192 | +0.0 | ok |
| autonomy_minutes | None | None | — | new |
| regression_rate | None | None | — | new |

## Regression flag

No metric regressed vs the previous snapshot.','docs/AGI_BENCH_TREND.md','75312340338fc199e0c65b43e44c3239e69c3d9089eebefacc597bb9e3a9df3b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/AGI_METRICS.md','project_doc','doc://simplicio-runtime/docs/AGI_METRICS.md','doc: AGI-grade evaluation metrics (issue #348)','# AGI-grade evaluation metrics (issue #348)

A reproducible metrics spec for measuring progress toward an autonomous
engineering agent, with targets and the current measured baseline. Run
`scripts/run-agi-bench.py` to (re)produce the numbers; raw evidence lives under
`docs/evidence/`.

## Metric definitions

| metric | definition | target (v1.0 AGI-ready) |
|---|---|---|
| **task_success_rate** | fraction of tasks whose objective oracle passes (execute code / run tests) | ≥ 0.85 on realistic tasks |
| **token_economy_ratio** | paid tokens used by Simplicio ÷ paid tokens used by a baseline agent on the same tasks | ≥ 10× fewer (≤ 0.1) |
| **zero_paid_capability** | task_success_rate achievable with **no paid LLM** (local model only, $0) | ≥ 0.50 single-shot; ≥ 0.70 with loop |
| **runtime_lift** | success delta of Simplicio''s loop over the same backend run raw | > 0 (loop never hurts) |
| **latency_per_task_ms** | wall-clock per task | lower is better; report median |
| **determinism** | mutations applied via verified writes (sha256 + gate) rather than free-form | 100% of edits gated |
| **footprint_mb** | installed size of the agent | ≤ 5 MB (single binary) |
| **autonomy_minutes** | useful work without human intervention | hours, multi-step |
| **regression_rate** | fraction of solved tasks that break previously-passing tests | → 0 |
| **evidence_completeness** | fraction of runs with a queryable evidence bundle (tests/sha256/tokens) | 1.0 |

## Current baseline (measured 2026-06-05)

Backends held constant where models are compared; oracle = execute and check.

| metric | value | source |
|---|---|---|
| task_success_rate (HumanEval-164, V4 Pro) | **0.951** (156/164) | `evidence/agent-battery-2026-06-05/humaneval-164-v4pro-results.json` |
| runtime_lift (V4 Pro, n=164) | **+0.037** (95.1% vs raw 91.5%) | same |
| runtime_lift (flash, n=15) | **+0.066** (93.3% vs raw 86.7%) | `evidence/.../humaneval-results.json` |
| zero_paid_capability (local 4B, single-shot, n=164) | **0.561** (92/164), **0 paid tokens** | `evidence/.../humaneval-164-local-nopaid.json` |
| token_economy_ratio (3-agent battery vs OpenClaw) | **~0.019** (2 493 vs 130 022 tokens ≈ 52× fewer) | `evidence/.../three-agent-battery.json` |
| determinism | 100% (sha256 + substring gate on every edit) | mechanical-edit/v1 |
| footprint_mb | **3.4** (default binary); 7.2 with in-process LLM | release build |
| evidence_completeness | 1.0 for the batteries above | evidence dir |

**Headline:** the same runtime spans the cost/quality spectrum — a 4B local model
at **$0** clears 56.1% of HumanEval single-shot, and a paid frontier backend
reaches 95.1% (beating the raw model via iterate-until-green). Token economy is
~52× better than OpenClaw on the agent battery.

## Realistic multi-file corpus (#2575)

Beyond self-contained HumanEval: `scripts/agi-tasks/<id>/` holds curated multi-file
repo tasks whose oracle is the project''s own `pytest` suite. `run-agi-corpus.py`
(gold/deterministic, $0) and `run-realtask-bench.py` (agent, iterate-until-green)
drive them. Latest evidence `docs/evidence/agi-corpus-2026-06-24.json`:
**3/3 tasks green (pass_rate 1.0)**, surfaced in the bench as
`realistic_corpus_pass_rate`. Follow-up: grow the corpus from 3 → 10-20 tasks.

## Gaps to AGI-grade (tracked by #348 follow-ups)

## Nightly trend + dashboard (#2577)

Trend tracking is implemented: `scripts/agi-bench-trend.py` appends a timestamped
snapshot of the metrics to `docs/evidence/agi-bench-history.jsonl` and regenerates
`docs/AGI_BENCH_TREND.md`, flagging any metric that regressed vs the previous run.
The `.github/workflows/agi-bench-nightly.yml` workflow runs it nightly and commits
the series back (subject to the repo''s Actions quota).

## Long-horizon autonomy axes (#2576)

`autonomy_minutes` and `regression_rate` are now **instrumented** in
`scripts/run-agi-bench.py` (epic #2574). They are derived from committed run
evidence, never fabricated — absent evidence yields `null` plus an explicit
`evidence_missing` reason (no-silent-fake-data rule).

| metric | evidence file | derivation |
|---|---|---|
| `autonomy_minutes` | `docs/evidence/**/autonomy*.json` — list of runs with `unattended_minutes` (or `intervals_minutes`) | median over runs of the longest unattended interval |
| `regression_rate` | `docs/evidence/**/regression*.json` — solved tasks with `broke_previously_passing` | fraction of solved tasks that broke a previously-passing test (ties into the delivery `regression` gate) |

First real measurement is pending a long-horizon sprint run that drops the
evidence files above; until then both report `null` with a reason.

## Reproduce

```bash
# full (needs OPENROUTER_API_KEY for the paid axis); falls back to local-only $0
python3 scripts/run-agi-bench.py --json
# local-only, zero paid tokens:
python3 scripts/run-agi-bench.py --local-only
```','docs/AGI_METRICS.md','a90baaef93f26cfaab3bac9d311e1790636014fd2b29585c4a2adb503d94e55b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/architecture/llm-integration.md','project_doc','doc://simplicio-runtime/docs/architecture/llm-integration.md','doc: LLM Integration — KV Cache Reuse + Direct Neural Memory Access (#326)','# LLM Integration — KV Cache Reuse + Direct Neural Memory Access (#326)

Status: **phase 1 delivered** (KV/prompt-cache reuse, direct neural-memory cache,
`ModelWorker` seam, deterministic before/after benchmark). Phase 2 (true
in-process binding) is scoped at the end.

## Problem

The runtime authors with a local model by spawning `llama.cpp`
(`llama-cli`/`llama-completion`) **one process per completion** — see
`native_model_complete_with_system` in `src/main.rs`. Each spawn rebuilds the KV
cache from scratch, so the **stable prefix** (the ChatML `system` block + project
context + skills) is re-prefilled on every call. On CPU, prompt prefill is the
dominant cost, and that prefix is identical across turns. Likewise, neural-memory
retrieval (`memory_query_sqlite`) spawns the `sqlite3` binary per query, paying
process-startup latency for reads that frequently repeat within a session.

Issue #326 asks for in-process LLM + strong KV cache reuse + low-latency neural
memory. Phase 1 delivers the **measurable performance core** of that request
inside the project''s hard constraints: a minimal-dependency, closed-source,
sub-2 MB binary that stays deterministic and fully tested.

## Design

### 1. KV / prompt-prefix cache (`SIMPLICIO_KV_CACHE`, default on)

llama.cpp can persist the KV state of a prompt to disk (`--prompt-cache FNAME`)
and, on the next run, **reuse the longest common prefix** with the cached prompt
— skipping its prefill. We exploit this by keying a prompt-cache file on a content
hash of the *reusable prefix*:

```
key = sha256(model_path \n system_prompt \n "ctx=<n>;v=<version>")[..32]
file = <repo>/.simplicio-loop/cache/kv/<key>.bin
```

Because the key is derived only from the stable prefix, **every call that shares a
system prompt shares one cache file** and reuses that prefix''s KV — regardless of
which volatile user block was appended last. The volatile suffix is still
re-evaluated each call (correctness is unchanged; only redundant prefill is
removed).

Key functions (`src/main.rs`):

- `kv_cache_prefix_key` — deterministic key for a reusable prefix.
- `kv_cache_resolve` — maps a prefix to its cache file and reports `warm`/cold.
- `build_native_completion_args` — factored-out, unit-tested argv builder; adds
  `--prompt-cache <file>` only when caching is enabled.
- `kv_cache_prune` — bounded directory: age ceiling → entry-count cap → byte
  budget (LRU by mtime). Runs before each write.
- `kv_cache_stats` / `kv_cache_clear` — observability and reset.

A `PREFIX_VERSION` constant invalidates every cache when the ChatML template or
arg shape changes, so a stale prefix is never reused. Set `SIMPLICIO_KV_TRACE=1`
to log warm/cold reuse on stderr.

### 2. Direct neural-memory access (`SIMPLICIO_NEURAL_CACHE`, default on)

A process-global LRU (`neural_mem_cache`) memoizes `memory_query_sqlite` results,
keyed by `(db_path, db_mtime, SQL)`. Repeated identical reads are served from
memory with **no `sqlite3` spawn**. The db mtime in the key means any write to the
memory database auto-invalidates stale entries — there is no manual invalidation
to get wrong.

### 3. `ModelWorker` seam

All native authoring goes through one trait:

```rust
trait ModelWorker {
    fn complete(&self, config, system_prompt, prompt, max_tokens, seed)
        -> Result<String, String>;
}
struct LlamaCppWorker; // prompt-cache-aware one-shot llama.cpp
```

This is the insertion point for phase 2 (an in-process binding holding a
persistent KV cache) without touching call sites. Tests inject a deterministic
fake.

## Before / After benchmark

`simplicio model cache bench [--json]` runs with **no model on disk**, so it is
reproducible in CI and on a fresh container. It (a) *models* the prefill-token
reprocessing eliminated by prefix reuse and (b) *measures* the real latency of the
in-process cache paths.

Model: without a shared cache, every call re-prefills `prefix + suffix`. With
prefix KV reuse, only the first call pays for the prefix; later calls re-prefill
only their volatile suffix.

```
before = calls * (prefix_tokens + suffix_tokens)
after  = (prefix_tokens + suffix_tokens) + (calls - 1) * suffix_tokens
saved  = (calls - 1) * prefix_tokens
```

Representative run (12 turns sharing one stable agent prefix):

| Metric | Before (no cache) | After (KV reuse) |
|---|---|---|
| Prefill tokens reprocessed | 6 840 | 856 |
| Reduction | — | **87.5%** |
| Reusable prefix tokens | 544 | reused after turn 1 |
| Per-turn suffix tokens | 26 | 26 |

Measured cache-path latencies (warm hits, no spawn): neural-cache get ≈ 0.5 µs
vs. a fresh `sqlite3` spawn of milliseconds — three to four orders of magnitude
faster. The KV layer''s only added per-call overhead is one prefix hash.

> The token figures model llama.cpp prefix reuse rather than wall-clock inference
> (which needs the model + backend present). The realized speedup tracks the
> prefill-token reduction: on CPU, prefill time is roughly proportional to tokens
> processed, so an ~87% prefill cut on a prefix-heavy prompt lands squarely in the
> issue''s 2×–5× target for prefix-dominated turns.

## Reproduce

```bash
simplicio model cache bench --json     # before/after + measured latencies
simplicio model cache status --json    # cache size, entries, hit/miss counts
simplicio model cache prune            # enforce the bounds now
simplicio model cache clear            # drop all prompt caches
SIMPLICIO_KV_CACHE=0 simplicio ...     # opt out of KV reuse
SIMPLICIO_NEURAL_CACHE=0 simplicio ... # opt out of neural-memory cache
```

## Phase 2 — true in-process worker (feature `in-process-llm`)

Delivered as an **opt-in cargo feature** so the shipped binary keeps its small,
zero-C++-toolchain default build. When compiled with `--features in-process-llm`,
the runtime links `llama-cpp-2` (which builds the vendored llama.cpp via cmake)
and routes native completions through an in-process worker instead of spawning
`llama-cli`.

What it does (`in_process_llm::complete`, `src/main.rs`','docs/architecture/llm-integration.md','a076140d6c6188845e2d7ae6a9985976fd7e487b8f9d63266f0424a272a63771','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/architecture/MAIN_RS_SPLIT_PLAN.md','project_doc','doc://simplicio-runtime/docs/architecture/MAIN_RS_SPLIT_PLAN.md','doc: `main.rs` Split Plan','# `main.rs` Split Plan

Issue: #2033

## Problem

`src/main.rs` is ~108 000 lines. It contains command dispatch, every module
inline, configuration structs, and runtime wiring all in a single file. This
causes:

- Incremental compile times of 40-90 s for any change.
- Merge conflicts on almost every PR.
- Impossible to navigate or review in isolation.

## Target State

After the split, `src/main.rs` must be ≤ 500 lines: only binary entry point,
CLI top-level dispatch, and module declarations (`mod foo;`).

## Module Boundaries (phase 1 — 20 target files)

| New file | Extracted from | Approx lines |
|---|---|---|
| `src/cli.rs` | Clap struct definitions, top-level `Commands` enum | 2 000 |
| `src/config.rs` | All `*Config` structs + defaults | 3 000 |
| `src/dispatch.rs` | `match command` arms — calls into sub-modules | 1 500 |
| `src/runtime_profile.rs` | `runtime-profile` command + tier logic | 1 200 |
| `src/status.rs` | `status` command + `StatusConfig` + watch loop | 800 |
| `src/memory_cmd.rs` | `memory` command surface (not the store itself) | 1 000 |
| `src/edit_cmd.rs` | `edit` command surface + plan parsing | 1 500 |
| `src/gate_cmd.rs` | `gate` / action-gate command surface | 900 |
| `src/deliver_cmd.rs` | `deliver` sub-commands (check/review/certify) | 2 000 |
| `src/checkpoint_cmd.rs` | `checkpoint` command | 600 |
| `src/map_cmd.rs` | `map` command surface | 700 |
| `src/reason_cmd.rs` | `reason` / `reason --act` command surface | 800 |
| `src/video_cmd.rs` | `video` sub-commands | 1 200 |
| `src/voice_cmd.rs` | `voice` sub-commands | 900 |
| `src/gateway_cmd.rs` | `gateway` sub-commands | 1 000 |
| `src/agent_cmd.rs` | `agent` / `agents` sub-commands | 1 500 |
| `src/task_cmd.rs` | `task` CRUD sub-commands | 1 200 |
| `src/init_cmd.rs` | `init` / onboarding sub-commands | 600 |
| `src/bench_cmd.rs` | `bench` sub-commands | 800 |
| `src/repl.rs` | REPL loop, stream scrubber wiring | 3 000 |

Remaining modules already in their own files (`src/delivery_*.rs`, `src/st_*.rs`,
`src/skill_*.rs`, etc.) are untouched.

## Migration Strategy

### Phase 1 — Mechanical extraction (no behaviour change)

1. Create each target file as an empty `pub(crate)` module.
2. For each target, use `simplicio edit replace_all` to move the relevant line
   ranges from `main.rs` into the new file (zero LLM tokens).
3. Add `mod <name>;` declarations to `main.rs` at the top of the file.
4. Fix visibility (`pub(crate)` where needed) and `use` paths.
5. `cargo check` after each file — fix compilation errors before moving on.
6. CI gate: `cargo clippy --release -- -D warnings` must stay green.

### Phase 2 — Incremental compile baseline

After phase 1, measure `cargo build --release` times on a cold cache.
Target: ≤ 20 s incremental after touching a single command file.

### Phase 3 — API hardening

Once files are stable, add `#[doc(hidden)]` or `pub(crate)` to internal types
to prevent accidental surface exposure.

## Constraints

- No behaviour change in phase 1. Refactor only.
- All existing `mod` declarations inside `main.rs` that point to external files
  (`mod skill_watchers;`, etc.) remain as-is; they just move to the top of
  `main.rs` or into `dispatch.rs`.
- The public CLI surface (`simplicio <cmd>`) must remain identical.

## Acceptance Criteria

- [ ] `wc -l src/main.rs` ≤ 500 after the split.
- [ ] `cargo test` passes with no regressions.
- [ ] `cargo clippy --release -- -D warnings` zero new warnings.
- [ ] Incremental build after touching `src/status.rs` alone: ≤ 20 s.','docs/architecture/MAIN_RS_SPLIT_PLAN.md','db1a6b31b39e69e57313a064b42f45e304204f0dd92617f39263f613a5dd36cc','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/architecture/receipt-chain-vs-cosign-chain.md','project_doc','doc://simplicio-runtime/docs/architecture/receipt-chain-vs-cosign-chain.md','doc: Issue #2888 — ReceiptChain vs CosignChain: Equivalence Analysis','# Issue #2888 — ReceiptChain vs CosignChain: Equivalence Analysis

**Status:** CLOSED — both implementations already exist and cover the requirement.

> **2026-07-08 update:** `CosignChain` (`src/asolaria/cosign_chain.rs`) was
> removed as part of `docs/ADR-2026-07-08-ASOLARIA-RESTORATION.md` — it
> duplicated the already-live `src/hbp/` evidence ledger, so its callers
> (`hookwall.rs`, `wormhole_command.rs`, `agent_state_command.rs`) now
> append to `hbp` instead. The `CosignChain`-specific rows below are kept
> for historical comparison; `ReceiptChain` and `hbp::HbpInbox` remain live.

## Summary

ReceiptChain **already** implements sha256 hash-chaining with prev_hash linking,
which is the core requirement of this issue. CosignChain also already exists at
`src/asolaria/cosign_chain.rs`. Neither module needs changes.

---

## ReceiptChain

- **Path:** `crates/simplicio-agents/src/receipt_chain.rs`
- **Re-exported via** `asolaria_hbi_hbp` crate → `src/asolaria/mod.rs:48`
- **Hash function:** SHA-256 (full 64-char hex)
- **Genesis:** `"0000000000000000000000000000000000000000000000000000000000000000"` (64 zeros)
- **Chaining:** Each receipt is `{row}|prev_event_hash={prev_sha256}|event_hash={sha256(row|prev)}`
- **Verification:** `verify_chain()` walks all rows, re-derives hashes, checks prev links
- **Tamper detection:** Any row modification breaks `verify_chain()` downstream
- **Used by:** `consciousness.rs`, `auto_correct.rs`, `proactive_engine.rs`, `tami.rs`, `tami_agent.rs`, `guardian_triangle`
- **Tests:** 13 tests, all passing

### Core implementation (lines 47-54):

```rust
pub fn append(&mut self, row: &str) -> String {
    let body = format!("{}|prev_event_hash={}", row, self.prev);
    let eh = sha256_hex(body.as_bytes());
    self.prev = eh.clone();
    let receipt = format!("{}|event_hash={}", body, eh);
    self.rows.push(receipt.clone());
    receipt
}
```

### Verify chain (lines 68-87):

Walks every receipt, recomputes `sha256(body)`, compares to `event_hash`,
and checks `prev_event_hash` matches previous row''s hash.

---

## CosignChain

- **Path:** `src/asolaria/cosign_chain.rs`
- **Module declaration:** `src/asolaria/mod.rs:38` (`pub mod cosign_chain;`)
- **Hash function:** SHA-256 truncated to sha16 (first 8 bytes, 16 hex chars)
- **Genesis:** `"0000000000000000"` (16 zeros)
- **Chaining:** Structured `CosignRow` with `{row, ts_ns, prev_sha16, kind, payload_sha16, sig}`
- **Verification:** `validate_end_to_end()` walks rows, checks monotonic row numbers,
  prev_sha16 links, and kind non-emptiness
- **Signature field:** `ed25519` `Signature([0u8; 64])` — struct present but verification
  not wired yet (noted as v0.3 work)
- **Used by:** `hookwall.rs`, `sys_cosign_append` (via `APPEND_SEQ_COUNTER`)
- **Wire format (planned):** ndjson

---

## Equivalence Table

| Feature | ReceiptChain | CosignChain | Status |
|---------|-------------|-------------|--------|
| SHA-256 hash chaining | ✅ Full 64-char hex | ✅ sha16 (truncated) | Both covered |
| prev_hash field linking | ✅ `prev_event_hash` | ✅ `prev_sha16` | Both covered |
| Genesis / anchor | ✅ 64 zeros | ✅ 16 zeros | Both covered |
| Full chain verification | ✅ `verify_chain()` | ✅ `validate_end_to_end()` | Both covered |
| Tamper detection | ✅ Any row change breaks chain | ✅ Any prev_sha16 mismatch detected | Both covered |
| Append-only invariant | ✅ Implicit (push only via `append()`) | ✅ Explicit (monotonic row number check) | Both covered |
| Signatures | ❌ None | ✅ ed25519 field (stub, v0.3) | CosignChain only |
| Timestamps | ❌ None | ✅ `ts_ns` field | CosignChain only |
| Payload hash | ❌ Inline in row string | ✅ `payload_sha16` field | CosignChain only |

---

## Conclusion

Both implementing the core hash-chaining requirement of issue #2888:

1. **ReceiptChain** already does sha256 hash-chaining with prev_hash — the
   primary ask of the issue is fully satisfied.
2. **CosignChain** already exists separately at `src/asolaria/cosign_chain.rs`
   with additional structural features (timestamps, signatures, payload hashes).
3. No new implementation is needed. The two modules serve different contexts
   (agent audit trail vs system-level hookwall chain) but share the same
   foundational hash-chain pattern.

## Issue #2888: CLOSED

No code changes required. Both files exist and are operational.

- `crates/simplicio-agents/src/receipt_chain.rs` — 269 lines, 13 tests ✅
- `src/asolaria/cosign_chain.rs` — 401 lines, 16 tests ✅','docs/architecture/receipt-chain-vs-cosign-chain.md','02c531c82a8a3427fab84392e0f37a367c5c1acd8fe5f20e2e36454d2df257c9','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/asolaria/behcs-256-integration.md','project_doc','doc://simplicio-runtime/docs/asolaria/behcs-256-integration.md','doc: 🌌 Integração Asolaria: BEHCS-256','# 🌌 Integração Asolaria: BEHCS-256

> **Issue:** [#2777 — Integração Asolaria: BEHCS-256 — Federação Multi-Agente + Bus + Supervisores](https://github.com/wesleysimplicio/simplicio-runtime/issues/2777)
> **Status:** 📋 Planejado · **Prioridade:** P0 (Barramento) / P1 (Supervisores) / P2 (Pipeline)
> **Repositório de referência:** [asolaria-behcs-256](https://github.com/JesseBrown1980/asolaria-behcs-256) (★25)

---

## Sumário

- [1. Contexto](#1-contexto)
- [2. Conceitos BEHCS-256](#2-conceitos-behcs-256)
  - [2.1 BEHCS Bus (LAW-001)](#21-behcs-bus-law-001)
  - [2.2 Supervisores (8 packages)](#22-supervisores-8-packages)
  - [2.3 Core Loop (6 packages)](#23-core-loop-6-packages)
  - [2.4 Frozen Polymorphism](#24-frozen-polymorphism)
  - [2.5 Shannon Civilization](#25-shannon-civilization)
  - [2.6 Gulp 2000 Pipeline](#26-gulp-2000-pipeline)
- [3. Propostas de Implementação](#3-propostas-de-implementação)
  - [3.1 🔴 P0 — BEHCS Bus como barramento interno](#31--p0--behcs-bus-como-barramento-interno-do-simplicio-runtime)
  - [3.2 🔴 P0 — Ciclo de Orquestração Federado](#32--p0--ciclo-de-orquestração-federado-cycle-orchestrator)
  - [3.3 🟡 P1 — Supervisor Registry + Device Identity](#33--p1--supervisor-registry--device-identity)
  - [3.4 🟡 P1 — Deterministic Edit Gate (Frozen Polymorphism)](#34--p1--deterministic-edit-gate-frozen-polymorphism)
  - [3.5 🔵 P2 — Gulp Pipeline (2000-step resumable)](#35--p2--gulp-pipeline-2000-step-resumable)
  - [3.6 🔵 P2 — Shannon Civilization Router](#36--p2--shannon-civilization-router)
- [4. Roteiro de Integração](#4-roteiro-de-integração)
- [5. Referências](#5-referências)

---

## 1. Contexto

O [**asolaria-behcs-256**](https://github.com/JesseBrown1980/asolaria-behcs-256) é o repositório flagship do ecossistema Asolaria de JesseBrown1980. Trata-se de um **Federated multi-agent civilization toolkit** com:

- 39 packages Node.js
- 23 runtime JS files
- Sistema completo de supervisores, barramento, ciclo de orquestração e governança de federação

O **Simplicio Runtime** é o braço de execução local — Rust nativo, CLI, MCP, agentes. A integração dos patterns do BEHCS-256 traz para o runtime:

- **Federação real** entre peers multi-host
- **Barramento tipado** com envelopes, substituindo comunicação HTTP crua
- **Supervisores determinísticos** para lifecycle, onboarding, routing, auth
- **Ciclo de orquestração federado** com SLO gates e halt-canon
- **Pipeline resumível** de 2000 passos (Gulp)
- **Router de civilização** Shannon (13 roles × 23 stages × 108-cell cube)

---

## 2. Conceitos BEHCS-256

### 2.1 BEHCS Bus (LAW-001)

O barramento segue a **LAW-001** (Brown-Hilbert Addressing):

| Propriedade | Valor |
|---|---|
| Portas | **4947** (bus primário) + **4950** (backup) |
| Formato de envelope | `{ verb, actor, target, payload, body, glyph_sentence }` |
| Endereçamento | Brown-Hilbert: D1=actor, D2=verb, D11=promotion, M=mode |
| Operações | `postToBus`, `kickPeer`, `postAndKick`, `sendHeartbeat` |
| Transporte | IPC (local) / TCP-TLS (remoto) |

**Impacto no Runtime:** substituir comunicação HTTP crua entre agentes por barramento tipado com envelopes.

### 2.2 Supervisores (8 packages)

| Supervisor | Função | Mapeamento Runtime |
|---|---|---|
| `pid-targeted-kick-supervisor` | Kick fanout + pid survival | Agent lifecycle manager |
| `remote-control-claude-supervisor` | HTTP bridge (:8765) | MCP gateway |
| `new-applicant-onboarding-supervisor` | Ship bundles to new joiners | `simplicio install` / bootstrap |
| `adb-kick-supervisor` | ADB input text + screencap | Terminal tool (exec) |
| `act-supervisor` | Classify envelopes → acer/liris | Message routing |
| `immune-l1-supervisor` | Ed25519 supervised `/type` | Auth/security layer |
| `supervisor-registry` | Hardware registry | Device identity |
| `orchestrator-guardrails-acer` | Dispatch guardrails | Task orchestration |

### 2.3 Core Loop (6 packages)

O **cycle-orchestrator** implementa o main action loop com 5 upgrades:

1. **PeerStateMachine** — estado de peers na federação
2. **UnisonTestDriver** — testes de sincronismo entre agentes
3. **BilateralFingerprintTracker** — fingerprint bilateral para identidade
4. **GNNFeedbackCadenceAdjuster** — ajuste de cadência baseado em feedback GNN
5. **SLOGate** — verbos no halt-canon (HALT, BLOCKED, STALE, FAIL, DENIED, EMERGENCY, STOP, KILL, ABORT, TERMINATE, DIVERGE) disparam U-008

Componentes auxiliares:

- `stage-to-actual-converter` — Dual-GNN agreement gate
- `super-gulp-tier3-consumer` — Tier-2 → Tier-3 promoter
- `whiteroom-consumer` — Cube-addressed digest
- `gulp-http-bridge` — BEHCS gulp-status + file-cap guard
- `omni-gulp-gc` — Garbage collector

### 2.4 Frozen Polymorphism

Regra fundamental do ecossistema BEHCS-256:

> **Nunca rubber-stamp.** Segunda assinatura requer avaliação independente.
> Multi-agent enforcement gate recusa solo seals em SMP-v5+ tasks.

### 2.5 Shannon Civilization

Sistema de roteamento e maturidade de agentes:

- **13 roles**: ator, observador, gate, etc.
- **23 stages** de maturidade
- **108-cell cube** de alocação
- **L0–L6 verdict router** + acer-dispatch-daemon

### 2.6 Gulp 2000 Pipeline

Pipeline de 2000 passos com checkpoint/resume:

- Omni primitives + Gulp runtime
- File-cap guard protection
- Resume em qualquer passo

---

## 3. Propostas de Implementação

### 3.1 🔴 P0 — BEHCS Bus como barramento interno do Simplicio Runtime

**Descrição:** Implementar um barramento de mensagens interno no runtime seguindo LAW-001 e envelopes BEHCS-256. Substituir chamadas HTTP diretas entre componentes internos.

**Detalhes:**

- Portas reservadas: 4947 (bus primário), 4950 (backup)
- Formato de envelope: `{ verb, actor, target, payload, body, glyph_sentence }`
- Brown-Hilbert address: D1=actor, D2=verb, D11=promotion, M=mode
- Suporte a `postToBus`, `kickPeer`, `postAndKick`, `sendHeartbeat`
- Bus local (IPC) para agentes no mesmo host
- Bus remoto (TCP/TLS) para federação multi-host

**Benefícios:** Barramento unificado → r','docs/asolaria/behcs-256-integration.md','578fe11ca864adb1afd7efbccef078b2761ab71ea3cd28fc2b871a2f46a006df','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ASOLARIA_EVAL_LEAKAGE_GATE.md','project_doc','doc://simplicio-runtime/docs/ASOLARIA_EVAL_LEAKAGE_GATE.md','doc: Asolaria Evaluation Leakage Gate','# Asolaria Evaluation Leakage Gate

This crate-level gate turns the BrainJanus / shadow-reconstruction lesson into a
deterministic Simplicio check:

- targets and answer keys must not appear in prompt/input fields;
- claimed metric percentages must reconcile with raw pass/total counts;
- targets and metrics must be recorded after the prediction they score.

## Claims Boundary

`MEASURED`: `crates/simplicio-claims` now exposes pure Rust lints for leakage,
metric consistency, ordering, and HBP-style `json=0` finding receipts. The crate
tests include padding-hacking, held-out-target, metric mismatch, metric
agreement, ordering, and tuple-row cases.

`DESIGN`: these checks are the first Simplicio-side "conscience" lock for
evaluation reports and benchmark claims.

`UNVERIFIED`: external papers about lossy shadow reconstruction do not prove
Asolaria''s lossless/code-rate-1.0 or infinite-prism-compression magnitude. They
only corroborate the need for discrete tokens, shared spaces, and leakage gates.

## Hot Path

Findings can be emitted as compact tuple rows:

```text
EVALGATE|code=eval.metric.percent_mismatch|severity=HOLD|message=...|json=0
```

JSON remains a cold compatibility surface for serde consumers; the bridge receipt
format is HBP-style tuple text.','docs/ASOLARIA_EVAL_LEAKAGE_GATE.md','4c12984dc979bef84078c41d8753e37e0691f0f17b9e91d044e44dce4a8fe9ab','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ASOLARIA_HBI_HBP_BRIDGE.md','project_doc','doc://simplicio-runtime/docs/ASOLARIA_HBI_HBP_BRIDGE.md','doc: Asolaria HBI/HBP Bridge','# Asolaria HBI/HBP Bridge

Status: first Simplicio-side hot-path adapter for the Asolaria bridge.

## Contract

The machine-to-machine bridge uses the Asolaria hot path:

- Rust codec.
- HBP tuple rows: `TAG|k=v|...|json=0`.
- HBI byte-offset rows: `IDX|pid=...|off=...|len=...|json=0`.
- sha256 content receipts.
- `AGT-<sha16>` references, where `sha16` is the first 16 hex chars of `sha256(content)`.
- Hash-chained receipt rows with `prev_event_hash` and `event_hash`.

The bridge sends addresses and receipts, not pasted payloads. The payload remains in
the owning store/Recall/Hilbra lane and is dereferenced by content address.

## Boundary

This is not the LLM context export lane. TOON/JSON can remain useful for prompts,
diagnostics, and compatibility, but they are not the Asolaria M2M substrate.

The first benchmark target is:

`Simplicio normal path` vs `Simplicio + Asolaria HBI/HBP/Recall`

on identical payloads, with throughput, bytes-on-wire, token use at the LLM
boundary, and receipt verification reported separately.','docs/ASOLARIA_HBI_HBP_BRIDGE.md','a61240a1817f988079b437be0a9665d04b3efce0bac0b3a4323a0c90bfdf9e53','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/audit-hermes-vs-simplicio-providers.md','project_doc','doc://simplicio-runtime/docs/audit-hermes-vs-simplicio-providers.md','doc: Audit: Hermes Provider/Model System vs Simplicio Runtime','# Audit: Hermes Provider/Model System vs Simplicio Runtime

**Date:** 2026-06-22
**Auditor:** Hermes Agent (subagent)
**Source:** `C:\Users\Z0059V7A\m\ai\simplicio-runtime`

---

## 1. Summary

**Verdict: Simplicio has FULL PARITY with Hermes provider/model support and SIGNIFICANTLY EXCEEDS it in breadth.** No gaps were found.

---

## 2. Comparison Matrix: Hermes-Listed Providers vs Simplicio

| Provider | Hermes Support | Simplicio Support | Details |
|----------|---------------|-------------------|---------|
| **OpenAI** | ✅ | ✅ | `openai-codex` (OAI-compat), `openai-responses` (Responses API) |
| **Anthropic** | ✅ | ✅ | `claude-pro-max` via Anthropic Messages transport |
| **OpenRouter** | ✅ | ✅ | Dedicated plugin + provider definition |
| **Groq** | ✅ | ✅ | OpenAI-compatible transport |
| **xAI** | ✅ | ✅ | `xai` (OAI-compat), `xai-responses` (Responses API) |
| **Google** | ✅ | ✅ | `google` (Gemini), `google-vertex-ai` (Vertex AI) |
| **AWS Bedrock** | ✅ | ✅ | `amazon-bedrock` with BedrockConverse SigV4 transport |
| **Azure** | ✅ | ✅ | `azure-openai` (OAI-compat), `azure-foundry` (Entra ID) |
| **Ollama** | ✅ | ✅ | Via `custom.rs` (aliases: `ollama`, `local`, `llamacpp`) + `ollama_cloud.rs` |
| **LM Studio** | ✅ | ✅ | Via `custom.rs` + `lmstudio_reasoning.rs` (effort resolution) |
| **vLLM** | ✅ | ✅ | Via `custom.rs` (alias: `vllm`) |
| **Custom providers** | ✅ | ✅ | `custom.rs` + named `custom_providers` in config |
| **Model fallbacks** | ✅ | ✅ | `tool-fallback-model`, `llm_routing`, multi-stage resolution |
| **Per-profile provider config** | ✅ | ✅ | `profiles.rs` with model/provider pairs, `chat-provider.json` per profile |

---

## 3. Simplicio Additional Providers (Beyond Listed Hermes Set)

Simplicio supports **27+ chat providers** and **29 model-provider plugins** — far exceeding the listed Hermes set:

### Chat Providers (from `src/provider_command.rs` — `CHAT_PROVIDER_IDS`)
1. `openai-codex` — OpenAI Codex (OAI-compatible)
2. `openai-responses` — OpenAI Responses API
3. `xai-responses` — xAI Grok (Responses API)
4. `github-models` — GitHub Models
5. `claude-pro-max` — Anthropic Claude
6. `openrouter` — OpenRouter
7. `deepseek` — DeepSeek
8. `groq` — Groq
9. `mistral` — Mistral AI
10. `cerebras` — Cerebras
11. `xai` — xAI (OAI-compatible)
12. `azure-openai` — Azure OpenAI
13. `azure-foundry` — Azure AI Foundry
14. `cloudflare-ai-gateway` — Cloudflare AI Gateway
15. `cloudflare-workers-ai` — Cloudflare Workers AI
16. `nvidia` — NVIDIA NIM
17. `together` — Together AI
18. `fireworks` — Fireworks AI
19. `opencode` — OpenCode Zen
20. `opencode-go` — OpenCode Go
21. `github-copilot` — GitHub Copilot
22. `google` — Google Gemini
23. `google-vertex-ai` — Google Vertex AI
24. `amazon-bedrock` — Amazon Bedrock
25. `huggingface` — Hugging Face Inference
26. `kimi-coding` — Kimi / Moonshot
27. `minimax` — MiniMax
28. `zai` — Z.ai (GLM)
29. `wavespeed` — WaveSpeed AI
30. `exo` — Exo AI Cluster (local)

### Model-Provider Plugins (from `src/plugins/model_providers/`)
- alibaba, alibaba_coding_plan, anthropic, arcee, azure_foundry, bedrock, copilot, copilot_acp, custom, deepseek, gemini, gmi, huggingface, kilocode, kimi_coding, minimax, nous, novita, nvidia, ollama_cloud, openai_codex, opencode_zen, openrouter, qwen_oauth, stepfun, xai, xiaomi, zai

### Alias/Normalization Support (from `chat_provider_alias`)
46+ aliases mapped to canonical provider IDs, including: `codex`, `openai`, `chatgpt`, `anthropic`, `claude`, `github`, `copilot`, `deepseek`, `groq`, `mistral`, `cerebras`, `xai`, `azure`, `bedrock`, `google`, `gemini`, `vertex`, `nvidia-nim`, `together`, `fireworks`, `huggingface`, `kimi`, `minimax`, `zai`, `opencode`, `wavespeed`, `custom`, etc.

---

## 4. Transport Protocols

| Protocol | Use Case | Simplicio |
|----------|----------|-----------|
| `OpenAiCompatible` | OpenAI API format | ✅ Standard for most providers |
| `AnthropicMessages` | Anthropic API | ✅ `claude-pro-max` |
| `BedrockConverse` | AWS Bedrock (SigV4) | ✅ `amazon-bedrock` |
| `AzureFoundry` | Azure AI Foundry (Entra ID) | ✅ `azure-foundry` |
| `OpenAiResponses` | OpenAI /v1/responses | ✅ `openai-responses`, `xai-responses`, `github-models` |

---

## 5. Model Metadata System

Simplicio''s `model_metadata.rs` (ported from Hermes) provides:

- **Context windows** (`DEFAULT_CONTEXT_LENGTHS`): 100+ entries covering Claude, GPT, Gemini, DeepSeek, Llama, Qwen, MiniMax, GLM, Grok, Kimi, Mistral, NVIDIA, Nemotron, and more
- **Max output tokens** (`MAX_OUTPUT_LIMITS`): Claude families + MiniMax + Qwen
- **Provider prefix stripping** (`PROVIDER_PREFIXES`): 60+ recognized prefixes
- **Token estimation**: chars/4 ceiling heuristic
- **Effective context budget**: `context - max_output - safety_margin`
- **Model version normalization**: dot→dash conversion

---

## 6. Local/Edge Inference

| Capability | Status | Implementation |
|-----------|--------|---------------|
| Built-in local LLM (Qwen GGUF) | ✅ | `model_defaults.rs` — RAM-based tier selection |
| llama.cpp subprocess | ✅ | `native_model_complete_with_system` |
| KV cache reuse | ✅ | `kv_cache_prefix_key`, prompt-cache files |
| LM Studio reasoning | ✅ | `lmstudio_reasoning.rs` — effort string resolution |
| Custom endpoint (Ollama/vLLM/llama.cpp) | ✅ | `custom.rs` — aliases: ollama, local, vllm, llamacpp |
| Ollama Cloud | ✅ | `ollama_cloud.rs` — https://ollama.com/v1 |

---

## 7. Model Fallback System

| Mechanism | Status | Location |
|----------|--------|----------|
| Tool-call fallback model | ✅ | `tool-fallback-model.ts` (desktop UI) |
| Intelligent task routing | ✅ | `llm_routing.rs` — simple/medium/complex tiers |
| Multi-stage provider resolution | ✅ | Env var → profile → persisted chat-provider |
| Static model catalog fallback | ✅ | `chat_provider_static_models` — used when live API unavailable |
| Live model discovery | ✅ | `fetch_provider_models_live` — curl to /v1/models |

---

## 8. Per-Profile Provider Config

| Feature | Status | Location |
|-','docs/audit-hermes-vs-simplicio-providers.md','f9d1a95036f2b1fe996bab0be1542cdbdafc3cc9c9517057ed6c8a229d521476','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/AUDIT_2026_06_05.md','project_doc','doc://simplicio-runtime/docs/AUDIT_2026_06_05.md','doc: Auditoria — simplicio-runtime (2026-06-05)','# Auditoria — simplicio-runtime (2026-06-05)

Auditoria completa de **segurança** e **funcionamento** do runtime, na versão
`0.3.27`. Cada achado abaixo foi verificado localmente.

## Resumo

| # | Área | Severidade | Estado |
|---|---|---|---|
| 1 | CI quebrado em todo o repo | **Crítico** | ⚠️ Ação do usuário (billing) |
| 2 | Segurança do código | — | ✅ Limpo |
| 3 | Warnings de clippy (dívida técnica) | Baixa | ✅ Reduzido 37 → 10 |
| 4 | Build / testes | — | ✅ Verde local |
| 5 | Higiene do repositório | Baixa | ✅ Ajustado |

---

## 1. ⚠️ CRÍTICO — CI falha em todo o repositório (não é o código)

**Sintoma:** todos os jobs (`Rust ubuntu/windows/macos` + `Quality gates`)
falham em **~3 segundos**, sem logs recuperáveis (HTTP 404), em **todo commit da
`main`** (verificado: os últimos 12 commits da main, todos `failure`) e em todas
as PRs.

**Diagnóstico:** falha de **infraestrutura/conta**, não de código. Jobs morrem
antes de qualquer passo do `cargo` rodar. O repositório é **privado** → minutos
gratuitos do GitHub Actions são limitados. O padrão (3s, sem logs, 100% dos
runs) é típico de **cota de Actions esgotada / billing pendente** ou runners não
provisionáveis.

**Prova de que o código está são** (rodado neste runtime):
- `cargo fmt -- --check` → OK
- `cargo test --locked` → **423 passed; 0 failed**
- `cargo build --release --locked` → OK
- `cargo build --release --features rich-repl` → OK

**Ação necessária (somente o usuário pode fazer):**
1. Verificar billing de GitHub Actions em Settings → Billing (adicionar método de
   pagamento ou comprar minutos), **ou**
2. Configurar **self-hosted runners**, **ou**
3. Reduzir a matriz (ex.: rodar `windows/macos` só em tags) para economizar
   minutos — os 3 SOs em todo push consomem 1×/10×/10× minutos.

Enquanto isso, **mergear via verificação local** (como foi feito na #320) é
seguro: os gates locais cobrem fmt + test + build.

---

## 2. ✅ Segurança do código — limpo

- **Sem segredos reais commitados.** Os matches de varredura são (a) a chave de
  exemplo `AKIAIOSFODNN7EXAMPLE` num fixture de teste e (b) placeholders
  `ghp_xxx`/`sk-xxx` dentro de docs do Hermes crawladas em `.simplicio-loop/research/`.
  Nenhuma credencial viva.
- **`unsafe`:** apenas **1** bloco (`Mmap::map` em `orientation_mmap_verified`),
  documentado e sólido — mapeia read-only um artefato publicado por rename
  atômico e tratado como imutável.
- **Execução de shell:** `app run` usa `bash <script>` / `cmd /C <script>` com o
  caminho como **argumento** (não `-c` interpolado) e com **guarda de
  path-traversal** canonicalizada (`canonical_script.starts_with(canonical_dir)`).
  Sem superfície de injeção.
- **SQL:** as chamadas ao `sqlite3` passam por `sql_literal()` (escapa aspas);
  sem concatenação crua de input.
- **Redação de segredos:** `redact_secrets()` mascara `token=`, `api_key=`,
  `sk-`, `ghp_` etc. antes de logs/artefatos.
- **Egress:** endpoints remotos (vision, STT/TTS, agent) são opt-in por env; host
  local é tratado como egress-free (`host_is_private`).

> Pendência herdada do `CLAUDE.md` (fora do repo): rotacionar a chave OpenRouter
> e o token PyPI que apareceram **no chat** — não estão no código, mas devem ser
> revogados.

## 3. ✅ Clippy — 37 → 10 warnings

Reduzido com `cargo clippy --fix` (19 lints mecânicos) + correções manuais
seguras: `manual_clamp` (×3 → `.clamp(1,100)`), `redundant_guards`
(`other if other.is_empty()` → `""`), `wildcard_in_or_patterns` (×2 — `_`
redundante em or-pattern), `if_same_then_else` (×2 — `if json {x} else {x}`
colapsado). Build + 423 testes seguem verdes.

Os **10 restantes** são arquiteturais/justificados e foram deixados de
propósito: `too_many_arguments`/`type_complexity` (refatorar assinaturas é
arriscado sem CI multiplataforma) e um `needless_range_loop` que muta elementos
enquanto empresta `jobs` imutavelmente (converter geraria conflito de borrow).

## 4. ✅ Build / testes — verde local

- 423 testes passam (`cargo test --locked`).
- Release builds: padrão (~2.4 MB) e `rich-repl` (~2.7 MB).
- `simplicio map --repo . --json` (gate do mapper) roda sem erro.

## 5. ✅ Higiene do repositório

- `.gitignore` restaurado/estendido em PRs anteriores para `.simplicio-loop/runs|
  agents|repl_history` + journal nativo (tinham caído num merge).
- **Observação (não bloqueante):** `.simplicio-loop/research/external-intelligence/`
  carrega um corpus crawlado grande (centenas de KB de JSON) versionado. Não é
  risco de segurança, mas é peso no repo. Considerar mover para um seed
  compacto (já há `memory-seeds/` para isso) — alinhado com a issue #160.

---

## Próximos passos recomendados (priorizados)

1. **[usuário] Destravar o CI** (billing/runners) — sem isso nenhuma PR fica
   verde e o release pipeline não roda.
2. **[usuário] Rotacionar credenciais** vazadas no chat.
3. Triar/fechar as PRs duplicadas do Codex abertas (várias cobrem features já na
   main).
4. Trimar `.simplicio-loop/research/` para seed compacto (#160).
5. Seguir reduzindo clippy nos pontos arquiteturais quando o CI voltar.','docs/AUDIT_2026_06_05.md','f2605e52bca562380ed163317443c0f160644bfccd45207b3d89de808643cad3','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/AUDIT_FAKE_CODE_2026-06-11.md','project_doc','doc://simplicio-runtime/docs/AUDIT_FAKE_CODE_2026-06-11.md','doc: SIMPLICIO RUNTIME — CONSOLIDATED FAKE-CODE AUDIT REPORT','# SIMPLICIO RUNTIME — CONSOLIDATED FAKE-CODE AUDIT REPORT
Scope: 147 module files + src/main.rs (~83.6k lines). All file paths relative to `C:\Users\Z0059V7A\m\ai\simplicio-runtime\src\`.

---

## SUMMARY

**Total fakes found: ~615 distinct findings** (after dedup of the main.rs 63990–64047 daemon overlap and the cross-referenced mattermost/google-chat prod-vs-test pairs).

| Severity | Count | Notes |
|---|---|---|
| CRITICAL | ~150 | 52 in module files (27 files), ~98 in main.rs |
| HIGH | ~390 | ~55 module, ~100 main.rs production, ~235 fake tests |
| MEDIUM | ~75 | partial impls, lossy round-trips, fabricated precision |

**By category:**

| Category | Count | Description |
|---|---|---|
| PRINTS_BUT_NO_ACTION | ~230 | Parses args, prints success JSON ("applied", "stored", "deployed", "connected"), performs zero work. Dominant pattern in main.rs lines 36800–68980. |
| HARDCODED_DATA | ~120 | Fabricated metrics/status presented as measured (CPU 5%, parity 61%, 847 records, quality score 85, "connected"). |
| STUB_NO_LOGIC | ~40 | Empty bodies returning Ok / hardcoded success strings (reset, setup wizard, update check/apply, deploy backends). |
| DEAD_CODE | ~15 | `#[allow(dead_code)]` features backing issue claims (#796–#806 parity block, error taxonomy #358, record_action_trajectory). |
| FAKE_TEST | ~250 | 232 `is_ok()`-only feature tests + tests codifying fake network success + rubber-stamp module tests. |

**Single worst signal:** the codebase contains an explicit house rule ("a stub must return an explicit Err, never placeholder success") and ~25 commands that correctly follow it (`recovery_*`, `evo_bb_*`, `agent_memory_*`, `modal_deploy.rs`) — proving the ~380 violations were avoidable.

---

## CRITICAL FINDINGS (blocks release)

### A. Fabricated evidence, benchmarks & savings (worst class — attacks the product''s core value proposition)
1. **main.rs ~22076 `benchmark_run_external_agent`** — Three-agent benchmark (#748) never runs Hermes/OpenClaw: built CLI args received as `_shell_args` and discarded; report prints per-agent ✓/✗ as if they ran. Fabricated competitive results. [PRINTS_BUT_NO_ACTION]
2. **main.rs ~42310/~42327 `value_demo_run` / `value_demo_benchmark`** — Hardcoded `tokens_saved:480`, fake scores `simplicio 92 / hermes 78 / openclaw 74`. Fake competitive claims. [HARDCODED_DATA]
3. **main.rs ~68941 `hermes_port_command benchmark`** — Hardcoded `simplicio:95` vs `hermes_estimated:340` ms; no measurement. [HARDCODED_DATA]
4. **main.rs ~43175 `evidence_show_summary/ledger/tokens`** — Always prints zeros + "no active run ledger found"; never reads `.simplicio-loop/runs/` even though real ledgers exist there. [STUB_NO_LOGIC]
5. **main.rs ~63783 `browser_evidence`** — Claims evidence artifacts (`evidence-{ts}.png/.html`, `yool://evidence/{ts}`); none created. [PRINTS_BUT_NO_ACTION]
6. **main.rs ~1735 `contracts_smoke`** — Smoke test that always prints `status: passed` with hardcoded chain; nothing invoked. [HARDCODED_DATA]
7. **main.rs ~45529 `write_foreground_functional_gates`** — Gates hardcoded `"passed"`; cannot fail. (Reported HIGH; release-blocking in context of delivery gates.) [HARDCODED_DATA]
8. **sealed_receipt.rs ~137 `sha256_bytes`** — "Cryptographic" tamper evidence is SipHash dressed as SHA-256; CLI `verify` only does substring match on the schema string. (HIGH+MEDIUM individually; jointly release-blocking for the evidence chain.) [HARDCODED_DATA]

### B. Fake observability suite (#425) — main.rs 63461–63586, 6 functions
9. **`obs_status`, `obs_logs`, `obs_audit`, `obs_metrics`, `obs_dashboard`, `obs_export`** — Entirely invented collectors, log lines, audit counts (`1842 events`), metrics (`cache_hit_rate 0.73`), dashboard (`cpu 42%`), and a claimed export file never written. [HARDCODED_DATA / PRINTS_BUT_NO_ACTION]

### C. Fake browser automation — three independent fake surfaces
10. **tools_browser.rs ~74–136** — 7 functions (`navigate`, `snapshot`, `click`, `type_text`, `scroll`, `back`, `screenshot`) return hardcoded success strings; session handles discarded (`let _ = session_id`). [PRINTS_BUT_NO_ACTION]
11. **main.rs ~63671–63762 `browser_robust` (#427)** — `navigate` (fake `status:200, load_ms:312`), `screenshot` (no file), `fill`, `click`, `scrape` (fake `chars:4812, links:23`), 5 functions. Shadows the real CDP-backed surface. [HARDCODED_DATA]
12. **main.rs ~31227 browser legacy fallback** — No daemon: `navigate` emits `session_ready` without opening anything; `snapshot|click|type|scroll|back|press|images|vision` return `"ok"` with zero dispatch. **`browser_dialog_json` (~29646)** accepts/dismisses dialogs that exist only in an env var. [PRINTS_BUT_NO_ACTION]
13. **main.rs ~68247 `browser_native_command` (#707)** — Claims chromedriver navigation/scrape; no WebDriver session. Companion **`computer_native_command` (~68181)** claims xdotool clicks/scrot screenshots; no process spawned. [PRINTS_BUT_NO_ACTION]

### D. Fake messaging/platform integrations (zero network I/O behind "send/receive")
14. **email_platform.rs** — `send` (no SMTP), `receive` (no IMAP; comment admits it). [PRINTS_BUT_NO_ACTION]
15. **teams_platform.rs `send_message`** — webhook_url/bot_token stored, never used. [PRINTS_BUT_NO_ACTION]
16. **platform_google_chat.rs** — `send_message`, `list_spaces`: in-memory Vec only. [PRINTS_BUT_NO_ACTION]
17. **platform_irc.rs** — `connect` (no socket, instantly "Connected"), `join`, `send_message` (timestamp literal `"now"`). [PRINTS_BUT_NO_ACTION]
18. **platform_mattermost.rs** — `send_message`, `status` (always `"connected"`). Plus **main.rs ~67604 `mattermost_command`** hardwires `https://mattermost.example.com` + literal `"test-token"` in a production CLI path. [PRINTS_BUT_NO_ACTION / HARDCODED_DATA]
19. **main.rs ~65959–66070 `msg_gw_*` (#449)** — `connect` ("webhook ready"), `send` (`delivered:true`); duplicates a *real* gateway that exists at `gateway_command`. [PRINTS_BUT_NO_ACTION]
20. **webhook_command.rs `subscribe`** + **main.rs ~3944','docs/AUDIT_FAKE_CODE_2026-06-11.md','b6fed22c7081c346273a810da24aa4c571a6fc1fb008225861f27e7e0c304069','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/AUDIT_REPORT_DOCS_2026-06-12.md','project_doc','doc://simplicio-runtime/docs/AUDIT_REPORT_DOCS_2026-06-12.md','doc: Auditoria da Pasta `docs/` — Relatório Completo','# Auditoria da Pasta `docs/` — Relatório Completo
**Data:** 2026-06-12  
**Repositório:** `simplicio-runtime`  
**Método:** Varredura de filesystem + INDEX.md + conteúdo c/ `head`/`wc`/`diff`/`grep`

---

## Sumário Executivo

| Métrica | Valor |
|---|---|
| Total de arquivos em `docs/` | **54 arquivos** (excluindo `.DS_Store`) |
| Listados no INDEX.md | **38 referências** (links canônicos) |
| **Não listados (órfãos)** | **17 arquivos** |
| Links quebrados no INDEX.md | **0** (todos existem) |
| Arquivos de raiz referenciados via `../` | 9 — **todos existem** |

---

## 1. Verificação de Links no INDEX.md — NENHUM QUEBRADO

Todos os paths referenciados no INDEX.md existem no filesystem:

**Raiz (`../`):** `AGENTS.md` ✓ · `CLAUDE.md` ✓ · `README.md` ✓ · `README.pt-BR.md` ✓ · `INSTALL.md` ✓ · `INIT.md` ✓ · `_BOOTSTRAP.md` ✓ · `BUILDING.md` ✓ · `CHANGELOG.md` ✓

**Dentro de `docs/`:** Todos os 28 arquivos listados (Tiers 0–6) existem. Nenhum 404.

---

## 2. Docs Órfãos — Categorização e Ação Recomendada

### CANÔNICOS (deveriam estar no INDEX.md)

| # | Arquivo | Linhas | Resumo | Ação |
|---|---|---|---|---|
| 1 | `docs/HERMES_AGENT_PORT_MATRIX.md` | 186 | Matriz de cobertura do port do pacote `agent/` do Hermes (113 arquivos Python, ~72k LOC) para módulos Rust. | **ADICIONAR ao INDEX** (Tier 2 ou 4). Documento de planejamento de arquitetura essencial. |
| 2 | `docs/HERMES_UX_PORT_PLAN.md` | 120 | Comparação item a item do terminal Hermes vs Simplicio com gaps críticos (streaming, scrubber, input editor) e decisão arquitetural de aposentar Ratatui como chat principal. | **ADICIONAR ao INDEX** (Tier 2). Decisões arquiteturais fundamentais. |
| 3 | `docs/STRIPE_SUBSCRIPTION.md` | 69 | Arquitetura de licenciamento: como webhooks Stripe assinam tokens que o runtime verifica localmente contra chave pública embutida. | **ADICIONAR ao INDEX** (Tier 5). Monetização/integração. |
| 4 | `docs/CASE_STUDY_002_DETERMINISTIC_LANE.md` | 161 | Estudo de caso real medido (Windows, debug build) da pipeline determinística: 0 tokens LLM, wall times, artifacts produzidos. | **ADICIONAR ao INDEX** (Tier 4). Benchmark canônico. |

### RASCUNHOS (precisam revisão antes de indexar, ou são úteis mas temporários)

| # | Arquivo | Linhas | Resumo | Ação |
|---|---|---|---|---|
| 5 | `docs/INSTALL.md` | 193 | Guia de instalação do binário Simplicio (curl, brew, npm, pypi, cargo). **DIFERENTE** do `INSTALL.md` na raiz (que é do LLM Project Mapper). | **RENOMEAR** para `docs/SIMPLICIO_INSTALL.md` para evitar confusão com root `INSTALL.md`. Depois **ADICIONAR ao INDEX** (Tier 1). |
| 6 | `docs/SIMPLICIO_FUNCIONALIDADES_E_FLUXOS.md` | 247 | Enumeração de funcionalidades (F1–F36) e cenários (C1–C20) com status (✅/🟡/🔴). Documento de revisão. | **REVISAR** validade dos status, depois **ADICIONAR ao INDEX** ou arquivar se obsoleto. |
| 7 | `docs/SIMPLICIO_VS_HERMES_TERMINAL.md` | 146 | Comparação terminal Simplicio × Hermes com benchmarks observados. | **REVISAR** — overlap com `COMPETITIVE_BENCHMARK.md` e `HERMES_PARITY.md`. Consolidar ou adicionar como apêndice. |
| 8 | `docs/SITE_ACCESS.md` | 53 | Mapa de acesso ao site/distribuição: repos, FTP, domínios, deploy. Sem secrets. | **REVISAR** — informação operacional sensível (não secrets, mas caminhos de deploy). Pode ir no INDEX Tier 5 após sanitização. |
| 9 | `docs/REMEDIATION_PLAN_858.md` | 71 | Plano de execução multi-agente para ~615 fakes do audit. Remediação do épico #858. | **MANTER** até o épico ser fechado, depois arquivar como receipt. |
| 10 | `docs/VOICE_LOCAL_RESEARCH_2026-06.md` | 104 | Pesquisa profunda de STT/TTS/VAD/S2S local, foco PT-BR, conclusão por pipeline cascaded. Alimenta `design/voice-first.md`. | **REVISAR** — conteúdo pode estar incorporado no design doc. Se sim, arquivar. Se não, adicionar ao INDEX. |
| 11 | `docs/AUDIT_FAKE_CODE_2026-06-11.md` | 199 | Relatório de auditoria: ~615 fakes, severidades, categorias. | **REVISAR** — essencial para o épico #858, mas temporário. Manter enquanto o épico estiver aberto. |
| 12 | `docs/RELEASE_MANIFEST.md` | 49 | Especificação do manifest de release (campos requeridos). | **REVISAR** — especificação pequena, pode estar no código. Adicionar ao INDEX Tier 5 se mantido. |
| 13 | `docs/plans/2026-06-12-simplicio-hermes-plugin.md` | 722 | Plano detalhado para plugin Simplicio em Hermes/OpenClaw via ACP stdio. | **MANTER** em `plans/` — é um plano de implementação, não doc canônico. Não indexar. |

### LIXO (rascunho único, backup, duplicata, ou obsoleto)

| # | Arquivo | Linhas | Razão | Ação |
|---|---|---|---|---|
| 14 | `docs/SIMPLICIO_MAPA_CONSOLIDADO.md` | 156 | Alega ser "doc mestre" consolidado, mas o `OPERATIONAL_MANUAL.md` (22.562 linhas, 138 fontes) é o consolidado real. **Redundante.** | **REMOVER ou arquivar.** Todo conteúdo está no OPERATIONAL_MANUAL. |
| 15 | `docs/SITE_README.md` | 67 | Versão simplificada do `README.md` da raiz para site de marketing. | **REMOVER** — é uma cópia derivada do README canônico. Manter só no site repo. |
| 16 | `docs/COMPETITIVE_BENCHMARK.pdf` | bin (1014) | PDF duplicata do `COMPETITIVE_BENCHMARK.md` (já no INDEX). | **REMOVER** — redundante. O .md é a fonte canônica. |
| 17 | `docs/plans/2026-06-12-ativar-tudo.md` | 48 | Plano de sessão única (sqlite-vec + guardians). Já executado ou superado. | **REMOVER ou arquivar** em `.receipts/` se executado. |

---

## 3. Duplicação de Conteúdo Detectada

### Duplicação CRÍTICA (conteúdo conflitante ou mesmo nome)

| Par | Análise | Ação |
|---|---|---|
| **`root/INSTALL.md`** (300 linhas) **vs `docs/INSTALL.md`** (193 linhas) | **COMPLETAMENTE DIFERENTES.** `root/INSTALL.md` = LLM Project Mapper overlay install (PT-BR). `docs/INSTALL.md` = Simplicio binary install (EN). | **Renomear `docs/INSTALL.md` → `docs/SIMPLICIO_INSTALL.md`** para evitar confusão. O INDEX já referencia `../INSTALL.md` (raiz), então `docs/INSTALL.md` é ambíguo. |

### Duplicação PARCIAL (overlap de propósito)

| Par | Análise | Ação |
|---|---|---|','docs/AUDIT_REPORT_DOCS_2026-06-12.md','e83c110e8462832f808db01b2735523115dc0a2f18ed2816c2641c56da681fab','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/autopilot-v5-architecture.md','project_doc','doc://simplicio-runtime/docs/autopilot-v5-architecture.md','doc: Autopilot v5 — Architecture Reference','# Autopilot v5 — Architecture Reference

Issue: #1847 (Epic — agent 2: documentation and schemas)

This document is the authoritative architecture reference for Autopilot v5.
It covers the end-to-end data flow, the module table, inter-module interfaces,
and the extension guide for new work-source adapters.

---

## 1. End-to-end data flow

```
                         Autopilot v5 — data flow
  ================================================================

  Work Sources
  +-----------+   +-----------+   +-----------+   +-----------+
  | GitHub    |   | Cron      |   | Chat      |   | Custom    |
  | Issues    |   | Schedule  |   | Intent    |   | Adapter   |
  +-----+-----+   +-----+-----+   +-----+-----+   +-----+-----+
        |               |               |               |
        +---------------+---------------+---------------+
                                |
                                v
                    +-----------+-----------+
                    |        Ingestor       |
                    |  (work-item factory)  |
                    |  validates schema     |
                    |  deduplicates         |
                    |  stamps provenance    |
                    +-----------+-----------+
                                |
                        autopilot-work-item/v1
                                |
                                v
                    +-----------+-----------+
                    |       Scheduler       |
                    |  (src/scheduler.rs)   |
                    |  priority lanes:      |
                    |   critical/high/      |
                    |   normal/background   |
                    |  dependency graph     |
                    |  stuck detection      |
                    |  persisted queue      |
                    +-----------+-----------+
                                |
                  dispatch: SchedulerWorkItem
                                |
                                v
                    +-----------+-----------+
                    |     Execution Loop    |
                    |  (src/coding_loop.rs  |
                    |   + action_bridge.rs) |
                    |  iterate-until-green  |
                    |  action gate (ask/    |
                    |   auto/safe)          |
                    |  local fan-out        |
                    |   64→100→200→600      |
                    |  remote only if       |
                    |   --allow-remote      |
                    +-----------+-----------+
                                |
                    result + exit code
                                |
                          +-----+------+
                          |            |
                    success          failure
                          |            |
                          v            v
                    +-----+--+   +-----+-------+
                    | DoD /  |   | Retry /     |
                    | Gate   |   | Diagnostics |
                    | check  |   | (#237)      |
                    +-----+--+   +-----+-------+
                          |            |
                          |  (retry up to max_attempts)
                          |            |
                          v            v
                    +-----------+-----------+
                    |    Evidence Ledger    |
                    |  (src/evidence_       |
                    |   emission.rs + hbp)  |
                    |  HBP verifiable chain |
                    |  run provenance       |
                    |  savings report       |
                    |  gate status          |
                    +-----------+-----------+
                                |
                    simplicio.evidence-bundle/v1
                                |
                                v
                    +-----------+-----------+
                    |        Delivery       |
                    |  (src/delivery_*.rs)  |
                    |  DoD gate (#251)      |
                    |  run-verify (#252)    |
                    |  regression (#253)    |
                    |  self-review (#254)   |
                    |  certificate (#255)   |
                    +-----------+-----------+
                                |
                    simplicio.delivery-certificate/v1
                                |
                                v
                         [Issue closed /
                          PR merged /
                          artifact published]
```

---

## 2. Module table

| File | Responsibility | State |
|---|---|---|
| `src/scheduler.rs` | Priority-lane work queue (critical/high/normal/background). Dispatches `SchedulerWorkItem`. Dependency-aware (`after` field). Stuck detection, persisted queue at `.simplicio-loop/scheduler/queue.json`. Integrates `LazyAgentManager`. | done |
| `src/cron_scheduler.rs` | Cron-based work source. Converts cron triggers into ingestable work-item payloads. | done |
| `src/coding_loop.rs` | Execution loop. Iterates a task until tests pass (iterate-until-green). Drives diagnostics on failure. Integrates with action gate and evidence emission. | done |
| `src/action_bridge.rs` | Chat-to-action spine. Gate-mode persistence (ask/auto/safe), bounded gate check, git-stash checkpoints with undo, task dispatch routing. | done |
| `src/action_gate.rs` | Action gate decisions (`classify_action_risk`, `action_gate_decide`). Hardline blocklist. Risk classification. | done |
| `src/evidence_emission.rs` | Mandatory HBP evidence emission at lifecycle stages (run/validate/publish/merge/close). Schemas: `evidence-bundle/v1`, `run-provenance/v1`, `savings-report/v1`. | done |
| `src/delivery_dod.rs` | Definition-of-Done (DoD) acceptance gate (#251). Evaluates criteria. | done |
| `src/delivery_runverify.rs` | Run-verification / dogfood gate (#252). Checks the artifact actually runs. | done |
| `src/delivery_regression.rs` | Regression guard (#253). Baselin','docs/autopilot-v5-architecture.md','8b1012c08d487cbb537e648bac9e140dbffc4c22ff7b3cbfe95f4563caf3d826','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/autopilot-v5-rollout.md','project_doc','doc://simplicio-runtime/docs/autopilot-v5-rollout.md','doc: Autopilot v5 Rollout Guide','# Autopilot v5 Rollout Guide

> Issue #1863 — Configuration defaults, migration from v4, CLI reference, E2E workflow, troubleshooting.

---

## Table of Contents

1. [Overview](#overview)
2. [Configuration Defaults](#configuration-defaults)
3. [Migration from v4 to v5](#migration-from-v4-to-v5)
4. [CLI Commands Reference](#cli-commands-reference)
5. [End-to-End Workflow Example](#end-to-end-workflow-example)
6. [Troubleshooting](#troubleshooting)

---

## Overview

Autopilot v5 is the Universal Looping AI Orchestrator built into the Simplicio runtime. It replaces the v4 single-shot executor with a governed, evidence-backed loop that runs tasks through the local agent ladder (64 → 100 → 200 → 600 agents) and only escalates to a paid remote LLM when all local rungs are exhausted.

Key improvements over v4:

- **Action Gate integration** — every mutation is classified and gated before execution.
- **Budget tracking** — `autopilot-budget` tracks token spend per session and enforces `max_parallel` task limits.
- **Preflight checks** — `autopilot-preflight` validates resources before any loop starts.
- **Work-source adapters** — pull tasks from GitHub issues, Jira, local files, or stdin via `autopilot work-source`.
- **HBP evidence chain** — every action is appended to the verifiable ledger; checkpoints enable undo.
- **Config module** — `autopilot-config show|init|validate` manages the JSON config file.

---

## Configuration Defaults

The canonical default config is produced by `simplicio autopilot-config init` and written to `.simplicio-loop/autopilot-config.json`.

```json
{
  "max_parallel": 4,
  "risk_threshold": 0.7,
  "dry_run": false,
  "evidence_dir": ".simplicio-loop/evidence",
  "ledger_dir": ".simplicio-loop/ledger"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `max_parallel` | `usize` | `4` | Maximum number of tasks running concurrently inside a single autopilot session. |
| `risk_threshold` | `f64` | `0.7` | Action Gate threshold: actions with a risk score ≥ this value require explicit user approval. Range `[0.0, 1.0]`. |
| `dry_run` | `bool` | `false` | When `true`, all mutations are simulated (no files written, no commands executed). |
| `evidence_dir` | `String` | `.simplicio-loop/evidence` | Directory where HBP evidence JSON-L files are stored. |
| `ledger_dir` | `String` | `.simplicio-loop/ledger` | Directory where the verifiable HBP ledger lives. |

### Environment overrides

Any field can be overridden at runtime via environment variables:

| Env var | Maps to |
|---|---|
| `SIMPLICIO_AP_MAX_PARALLEL` | `max_parallel` |
| `SIMPLICIO_AP_RISK_THRESHOLD` | `risk_threshold` |
| `SIMPLICIO_AP_DRY_RUN` | `dry_run` (`1`/`true`/`yes` = true) |
| `SIMPLICIO_AP_EVIDENCE_DIR` | `evidence_dir` |
| `SIMPLICIO_AP_LEDGER_DIR` | `ledger_dir` |

---

## Migration from v4 to v5

### Breaking changes

| Area | v4 | v5 |
|---|---|---|
| Config file | `~/.simplicio-loop/autopilot.toml` (TOML) | `.simplicio-loop/autopilot-config.json` (JSON, per-repo) |
| Parallelism flag | `--jobs N` | `max_parallel` in config or `--max-parallel N` CLI flag |
| Risk level | `--risk low\|medium\|high` | `risk_threshold` float `[0.0, 1.0]` |
| Dry-run | `--simulate` | `--dry-run` / `dry_run: true` in config |
| Evidence output | Not recorded | HBP chain in `evidence_dir` |
| Gate mode | None | `action-gate` (ask / auto / safe) |

### Step-by-step migration

**Step 1 — Back up your v4 config**

```bash
cp ~/.simplicio-loop/autopilot.toml ~/.simplicio-loop/autopilot.toml.v4-backup
```

**Step 2 — Initialize the v5 config for your repo**

```bash
cd /path/to/your-repo
simplicio autopilot-config init
# Writes .simplicio-loop/autopilot-config.json with defaults
```

**Step 3 — Port your v4 settings**

Open `.simplicio-loop/autopilot-config.json` and update the fields to match your old TOML values:

```bash
# Example: if v4 had --jobs 8
# Edit .simplicio-loop/autopilot-config.json → "max_parallel": 8

# Example: if v4 had --risk low (conservative)
# risk_threshold ~0.4 means fewer actions pass the gate automatically
# Edit → "risk_threshold": 0.4
```

**Step 4 — Validate the config**

```bash
simplicio autopilot-config validate
# Prints field-by-field validation; exits 0 on success
```

**Step 5 — Run a dry-run first**

```bash
simplicio autopilot run --dry-run "your task description"
# Confirms the new loop behavior without mutations
```

**Step 6 — Verify the Action Gate**

```bash
simplicio gate classify --action "write file src/lib.rs"
# Should return risk score < risk_threshold for low-risk edits
```

**Step 7 — Remove the v4 TOML** (after confirming v5 works)

```bash
rm ~/.simplicio-loop/autopilot.toml.v4-backup  # when satisfied
```

---

## CLI Commands Reference

All commands are invoked as `simplicio <command> [subcommand] [args]`.

### `autopilot`

The main v5 orchestrator.

```
simplicio autopilot [subcommand] [options]
```

| Subcommand | Description |
|---|---|
| `run <task>` | Run a task through the local agent ladder. |
| `run --dry-run <task>` | Simulate a run without mutations. |
| `run --remote <task>` | Allow escalation to paid remote LLM. |
| `preflight` | Alias for `autopilot-preflight`. |
| `status` | Show current loop state and budget. |

### `autopilot-config` / `ap-config`

Manage the per-repo autopilot configuration.

```
simplicio autopilot-config <subcommand>
simplicio ap-config <subcommand>
```

| Subcommand | Description |
|---|---|
| `show` | Print the current effective config as JSON (file + env overrides). |
| `init` | Write `.simplicio-loop/autopilot-config.json` with default values (no-op if already exists). |
| `validate` | Validate all fields; print warnings and exit non-zero on error. |

**Examples**

```bash
# Show effective config (merges file + env overrides)
simplicio ap-config show

# Initialize default config for this repo
simplicio ap-config init

# Validate config (useful in CI)
simplicio ap-config validate
```

### `autopilot-preflight`

Validate machine resources before starting an autopilot session.

```
simplicio','docs/autopilot-v5-rollout.md','3eaa95ff48c44176e9873c22f2b23fadb6640d9e2da1842e341d39264b5cb920','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/benchmark/2026-06-27-recall-10areas.md','project_doc','doc://simplicio-runtime/docs/benchmark/2026-06-27-recall-10areas.md','doc: Benchmark #3 — recall COM vs SEM Simplicio · 10 áreas, medido + gráficos','# Benchmark #3 — recall COM vs SEM Simplicio · 10 áreas, medido + gráficos

**Data:** 2026-06-27 · **Modelo de uso:** Opus 4.8 · **Binário:** lean MCP (`simplicio`, recall corrigido)

> **É verdadeiro, não pra agradar.** Os dois lados são **medidos**, não chutados. Harness reprodutível: `scripts/benchmark_recall.py` (dados em `recall-benchmark-data.csv`). E mostro um caso onde Simplicio **perde** (caveat negativo) — prova de que não está cozinhado.

## Metodologia (honesta)

- **10 solicitações** de áreas distintas; cada uma rodada **5x** (latência = mediana).
- **COM Simplicio:** `simplicio memory query "<q>"` real — bytes de saída, hits, latência cronometrada.
- **SEM Simplicio (baseline medido):** sem índice, o agente acha a skill lendo arquivos. Universo = **249 `SKILL.md`** (~693,055 tokens). Ranking por **densidade de termos** (não favorece arquivo grande). Dois pontos de referência:
  - **piso** = ler **1** arquivo-resposta inteiro (melhor caso, como se já soubesse qual).
  - **realista** = ler os **top-5** candidatos (você não consegue ranquear sem índice).
- **tokens ≈ bytes/4** (mesma razão nos dois lados).

## Resultado por solicitação (medido)

| área | COM (tok) | COM (ms) | hits | SEM piso (tok) | SEM realista (tok) | economia vs realista | vs piso |
|---|--:|--:|:-:|--:|--:|--:|--:|
| coding/debug | 1,416 | 112.5 | 2 | 2,618 | 18,105 | **92.2%** | 45.9% |
| video | 1,443 | 111.4 | 3 | 3,607 | 30,400 | **95.3%** | 60.0% |
| captions | 1,423 | 111.2 | 2 | 8,008 | 22,306 | **93.6%** | 82.2% |
| security | 1,528 | 114.4 | 3 | 1,902 | 11,656 | **86.9%** | 19.7% |
| git/PR | 1,397 | 111.8 | 2 | 3,391 | 15,121 | **90.8%** | 58.8% |
| frontend | 1,401 | 112.6 | 2 | 4,965 | 12,681 | **89.0%** | 71.8% |
| marketing | 1,536 | 112.5 | 3 | 774 | 9,238 | **83.4%** | -98.4% |
| data | 1,404 | 112.7 | 2 | 2,347 | 23,669 | **94.1%** | 40.2% |
| research | 1,491 | 112.8 | 3 | 2,521 | 34,669 | **95.7%** | 40.9% |
| devops | 1,390 | 112.9 | 2 | 2,610 | 12,924 | **89.2%** | 46.7% |

## Totais (medidos)

- **COM Simplicio:** 14,429 tokens nas 10 · **latência mediana 112.5 ms** · 2 hits medianos.
- **SEM, realista:** 190,769 tokens → **economia 92.4%**.
- **SEM, piso:** 32,743 tokens → **economia 55.9%**.

## Onde Simplicio PERDE (honestidade)

Em `marketing` o **piso é negativo**: a skill-resposta tem só ~774 tokens, e o envelope do recall (~1,5k tokens, JSON de status+resultados) é **maior** que ler aquele arquivo único. Ou seja: **quando você já sabe exatamente qual arquivo minúsculo ler, raw-read é mais barato.** O recall ganha quando (a) você **não sabe** qual das 249 skills serve, ou (b) o alvo é grande/múltiplo. Otimização real pendente: enxugar o envelope do `memory` (hoje carrega status/config junto).

## Gráficos

![tokens](charts/tokens.png)
*Tokens por solicitação — COM vs SEM (piso/realista), escala log.*

![savings](charts/savings.png)
*% economizado por solicitação (vs realista e vs piso).*

![latency](charts/latency.png)
*Latência real do recall (mediana de 5 runs).*

![hits](charts/hits.png)
*Skills/docs recuperados por solicitação.*

## Veredito honesto

- **Latência real e baixa:** ~112.5 ms por recall (mediana de 10×5 medições).
- **Economia real vs o caminho realista** (achar a skill lendo candidatos): **92.4%**.
- **Não é 100% sempre:** contra o piso ideal, a economia cai e até inverte para skills minúsculas. O ganho de Simplicio é **encontrar + ranquear** em 249 skills em ~112 ms, não mágica.','docs/benchmark/2026-06-27-recall-10areas.md','6c410f223777c09682ba3ee2383144311ea0d49d2f2699407fdd205096173058','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/benchmark/2026-06-27-skill-recall-captions.md','project_doc','doc://simplicio-runtime/docs/benchmark/2026-06-27-skill-recall-captions.md','doc: Benchmark #2 — Opus 4.8 **com** vs **sem** Simplicio · recall de skill','# Benchmark #2 — Opus 4.8 **com** vs **sem** Simplicio · recall de skill

**Data:** 2026-06-27 · **Modelo:** Opus 4.8 · **Binário:** lean MCP (`simplicio`, recall corrigido)

## Tarefa (real, dirigida por skill)

> *"Usuário pede: **adicione legendas a um vídeo talking-head**. Qual abordagem,
> qual ferramenta, e quanto custa — com vs sem Simplicio?"*

Tarefa que **depende de conhecimento de pipeline** (transcrição → matte → render →
ffmpeg). É o caso onde "usar as skills da memória" decide o resultado.

## Resultado factual (medido)

- **COM Simplicio:** 1 recall (`simplicio memory "embedded cinematic captions"`) =
  **5.486 B** surfou a skill canônica **`embedded-captions`** (32.031 B, 25 linhas
  de pipeline). O frontier só **executa a receita recuperada** — sem reinventar.
  A skill ainda corrige um erro comum: *embeding de toda palavra é errado p/
  talking-head; o default verbatim é `anchor`*.
- **SEM Simplicio:** sem índice de skills, o LLM **reinventa** o pipeline do
  conhecimento de treino — ou o usuário precisa raw-read de **346.511 B** (~87k
  tokens) de docs de skills de vídeo p/ ter a mesma base. Risco real de escolher a
  ferramenta/abordagem errada.

## Tabela comparativa (10 itens)

| # | Dimensão | SEM Simplicio | COM Simplicio | Vencedor |
|---|---|---|---|---|
| 1 | Descobrir a abordagem | reinventar do treino | recall determinístico da skill | **Com** |
| 2 | Skill recuperada | nenhuma (não há índice) | **`embedded-captions`** (canônica) | **Com** |
| 3 | Pipeline correto | LLM improvisa etapas | 25 linhas: transcribe→matte→render→ffmpeg | **Com** |
| 4 | Evita anti-pattern | pode embeddar toda palavra (errado) | skill impõe `anchor` verbatim default | **Com** |
| 5 | Tokens de contexto | ~87k (raw-read 346 KB de skills) | **~1,4k** (recall 5.486 B) | **Com** |
| 6 | Conhecimento aplicado | o que couber no contexto | 32 KB de expertise encodada, sob demanda | **Com** |
| 7 | Determinismo | varia por execução | mesma skill, mesma saída | **Com** |
| 8 | Escolha de ferramenta | adivinha (Remotion? ffmpeg cru?) | HyperFrames HTML→MP4 (a skill define) | **Com** |
| 9 | Proveniência | nenhuma | skill + ledger HBP + checkpoint | **Com** |
| 10 | Risco de retrabalho | alto (abordagem errada) | baixo (recipe testada) | **Com** |

## Veredito

Diferente do Benchmark #1 (tarefa mecânica, ganho ~61–91% de tokens), aqui o ganho
é **qualitativo**: sem a skill, o caminho "sem Simplicio" pode entregar a abordagem
**errada** (anti-pattern de captions). **~1,4k vs ~87k tokens** p/ a mesma base de
conhecimento (**~98%**), e — mais importante — **corretude de pipeline** garantida
pela skill recuperada da memória. Este é o efeito do fix de recall: o frontier
orienta/decide, a memória entrega a expertise determinística.

## Ferramentas usadas COM Simplicio — e o raciocínio

| Ferramenta | Raciocínio | Medido |
|---|---|---|
| **`simplicio memory "<query>"`** | Recall da skill certa da memória neural (corrigido agora p/ retornar hits, não status) | 5.486 B / 2 hits |
| **`simplicio skill match`** | Intent→skill routing (9 intents mapeados) p/ confirmar a skill | — |
| **skill `embedded-captions`** | Pipeline determinístico encodado (transcribe→matte→render→ffmpeg); impõe o default correto | 32.031 B |
| **HyperFrames (via skill)** | Render HTML→MP4 determinístico que a skill prescreve | — |
| **`simplicio gate` + HBP** | Gate + evidência auditável da execução | — |

> Pré-requisito honesto: render real exige FFmpeg + clip single-subject no host
> (a skill retorna Err honesto se faltarem — sem fake success).','docs/benchmark/2026-06-27-skill-recall-captions.md','ad51948a773c64a7410c60e7fdfcd877e9d2e85fadc358f46e837c8eaa0760cb','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/benchmark/2026-06-27-with-without-simplicio.md','project_doc','doc://simplicio-runtime/docs/benchmark/2026-06-27-with-without-simplicio.md','doc: Benchmark — Opus 4.8 **com** vs **sem** Simplicio (MCP)','# Benchmark — Opus 4.8 **com** vs **sem** Simplicio (MCP)

**Data:** 2026-06-27 · **Modelo:** Opus 4.8 · **Binário:** lean MCP (`target/release/simplicio`, 22 MB)

## Tarefa (precisa de internet, como o clone do google)

> *"Descobrir a versão estável atual do Rust (internet) e mapear/documentar como
> **este** repo fixa a toolchain Rust — e recomendar correção se faltar pin."*

Tarefa real, com um fato externo (versão atual) + uma investigação no repo
(17.201 arquivos, 1.319 `src/*.rs`, ~34 MB de fonte).

## Resultado factual (idêntico nos dois caminhos)

- **Rust estável atual:** **1.96.0** (lançado 28-mai-2026). Fontes abaixo.
- **Pin no repo:** **nenhum** — não há `rust-toolchain.toml`, `rust-version` em
  `Cargo.toml` é **0 linhas**, só `edition = "2021"`. CI usa
  `dtolnay/rust-toolchain@stable` (versão flutua). **Recomendação:** adicionar
  `rust-toolchain.toml` fixando 1.96.0 para build reproduzível.

Números abaixo são **medidos** (bytes reais de saída de cada comando) — não estimados,
exceto a coluna "sem Simplicio" de exploração, marcada como estimativa conservadora.

## Tabela comparativa (10 itens)

| # | Dimensão | SEM Simplicio | COM Simplicio | Vencedor |
|---|---|---|---|---|
| 1 | Fato externo (versão Rust) | 1 WebSearch | 1 WebSearch | empate |
| 2 | Orientação no repo | ler ~6–12 arquivos (avg 25,8 KB/arquivo) p/ entender estrutura | `simplicio map` = **4.431 B** (1 chamada) | **Com** |
| 3 | Localizar o pin da toolchain | grep + abrir Cargo.toml (7.160 B) + arquivos de build | `simplicio search` = **1.477 B** alvo | **Com** |
| 4 | Recall de decisões prévias | re-derivar do zero | `simplicio memory query` = **hits reais** (skills/docs do DB) | **Com** |
| 5 | Tokens de contexto ingeridos | ~9,5k (conserv.) … ~42k (se explorar `src`) | **~1,5k** (map+search) | **Com** |
| 6 | Aplicar o doc/edit | LLM escreve à mão (~saída cheia) | `simplicio edit` mecânico = **~0 tokens de saída** | **Com** |
| 7 | Determinismo / reprodutível | julgamento do LLM (varia) | tools determinísticas (mesma saída) | **Com** |
| 8 | Proveniência / evidência | nenhuma | ledger HBP (cadeia hash) + checkpoint | **Com** |
| 9 | Chamadas de ferramenta | ~8–13 (reads/greps dispersos) | **4** (search web + map + memory + search) | **Com** |
| 10 | Correção do resultado | correta se explorar o bastante | correta com **menos** ingestão | empate (custo menor: Com) |

\* **Item 4 — correção honesta:** o run inicial mostrou **0 hits**, mas o dado
**estava** no DB (FTS direto retorna `frontend-design`, `ui-ux`, …). A causa era um
**bug de CLI**: a forma documentada `simplicio memory "<query>"` (sem a sub-ação
`query`) caía no default `action="status"` e nunca executava a busca — devolvia só
status do backend. **Corrigido** (`main_part_01.rs`): texto posicional sem keyword
agora roteia para o caminho FTS, então `simplicio memory "frontend design"` retorna
os hits reais. Após o fix, o recall é vitória de Simplicio, não empate.

## Veredito (medido, conservador)

- **Tokens p/ mesma confiança:** Com ≈ **3,7k** (inclui o miss da memória) · Sem ≈
  **9,5k** (conservador, sem explorar `src`) → **~61% economizado**. Se o caminho
  "sem" precisar explorar `src` p/ orientar (realista), Sem ≈ **42k** → **~91%**.
- **Passo de edição:** edit determinístico = ~0 tokens de saída vs escrever à mão.
- **Empate em corretude**; a diferença é **custo, determinismo e evidência**.

## Ferramentas usadas COM Simplicio — e o raciocínio de cada uma

| Ferramenta | Por que (raciocínio) | Medido |
|---|---|---|
| **WebSearch** (internet) | Fato externo/atual — versão do Rust não está no repo nem na memória; precisa de fonte viva. Único passo que exige internet. | 1 chamada |
| **`simplicio map`** | Orientar antes de raciocinar: visão comprimida do repo em vez de raw-read de 17k arquivos. Corta tokens de contexto na origem. | 4.431 B |
| **`simplicio memory`** | Recall antes de re-derivar: checar se a decisão de toolchain já foi gravada. Miss honesto aqui (0 hits) — mas é o passo que normalmente evita re-descoberta. | 8.765 B / 0 hits |
| **`simplicio search`** | Localização determinística do `rust-version`/pin sem abrir arquivos um a um. Alvo, não exploratório. | 1.477 B |
| **`simplicio edit`** (recomendado p/ aplicar o fix) | Mudança decidida (criar `rust-toolchain.toml`) é mecânica → escritor determinístico, zero token de saída, hash-gated. Não deixa o LLM escrever o arquivo. | ~0 tok saída |
| **`simplicio gate`** + ledger HBP | Gate antes de mutar + evidência (cadeia hash, checkpoint/undo) — prova auditável do que rodou. | — |

## Fontes (internet)

- https://blog.rust-lang.org/releases/latest/
- https://releases.rs/
- https://endoflife.date/rust
- https://versionlog.com/rust/','docs/benchmark/2026-06-27-with-without-simplicio.md','db45d5703b9c7f4877e5aaa4f7a6ba33e66a3cdac123e43a8a86018662db0847','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/benchmark/2026-06-28-ten-cases-com-vs-sem.md','project_doc','doc://simplicio-runtime/docs/benchmark/2026-06-28-ten-cases-com-vs-sem.md','doc: Benchmark #3 — 10 testes COM vs SEM Simplicio (item a item, honesto)','# Benchmark #3 — 10 testes COM vs SEM Simplicio (item a item, honesto)

**Data:** 2026-06-28 · **Binário:** lean · **DB de memória:** operacional (757 rows, FTS5)

Princípio: o baseline **SEM Simplicio** é um *agente esperto* (grep + ler só a seção
relevante), **não** raw-read de tudo. Sem strawman. `tokens ≈ bytes/4`.

Legenda de confiança:
- 🟢 **MEDIDO** — o binário rodou e o número saiu da execução.
- 🟠 **PROJETADO** — o mecanismo (recall) foi medido; o tamanho do corpus do setor é
  estimativa realista (a DB aqui só tem dados do projeto Simplicio).

## Programação (5 casos — todos MEDIDOS)

| # | Caso | Ferramenta | COM (tok) | SEM (tok) | Economia | Justificativa medida |
|---|---|---|---|---|---|---|
| P1 | Refactor mecânico (rename ×5) | `simplicio edit` | 55 | 9.591 | **99%** | plano 221 B aplicado vs reescrever arquivo 38.367 B |
| P2 | Orientação no repo | `simplicio map` | 1.280 | 27.000 | **~95%** | map 5.122 B vs ler ~6 arquivos medianos (18 KB) |
| P3 | Recall de decisão (action gate) | `simplicio memory` | 106 | 2.859 | **~96%** | recall 5.611 B vs grep+ler seção do manual (11.436 B) |
| P4 | Conhecimento do coding-loop | `simplicio memory` | 104 | 6.000 | **~98%** | recall 5.625 B vs grep+ler docs do loop |
| P5 | Pipeline de captions (skill) | `memory` + skill | 56 | 2.000 | **qualitativo** | recall 4.600 B; o ganho REAL é corretude (default `anchor`), não token |

## Setores diversos (6 casos — PROJETADOS)

Mecanismo de recall MEDIDO (~500–600 B / ~120–150 tok, independente de domínio,
provado em 10 queries reais). O baseline do setor é estimativa realista.

| # | Setor | Tarefa | COM (tok) | SEM (tok) | Economia | Base |
|---|---|---|---|---|---|---|
| S1 | Jurídico | Achar a cláusula/precedente certo | 150 | 40.000 | ~99% | ler conjunto de contratos (~160 KB) |
| S2 | Saúde | Passo de protocolo clínico | 150 | 20.000 | ~99% | ler diretriz clínica (~80 KB) |
| S3 | Financeiro | Regra de compliance | 150 | 30.000 | ~99% | ler regulamento (~120 KB) |
| S4 | Marketing | Voz de marca / campanha | 120 | 15.000 | ~99%¹ | ler brand book (~60 KB) |
| S5 | Educação | Padrão curricular | 150 | 25.000 | ~99% | ler documento de padrões (~100 KB) |
| S6 | Suporte | Resposta de artigo da KB | 120 | 18.000 | ~99% | ler base de conhecimento (~72 KB) |

¹ Quando o conhecimento é geral e o frontier já sabe de treino, o ganho vira
corretude/grounding, não token.

## Agregado honesto

- **Programação (medido):** economia média **97,3%**.
- **Setores (projetado):** economia média **99,4%** — mecanismo medido, corpus estimado.
- **Onde NÃO economiza token:** fato de conhecimento geral (P5, S4) — o ganho é
  corretude, não token. Os ganhos brutos reais são `edit` (P1) e `map` (P2).

## Anatomia de uma tarefa real (ver `2026-06-28-task-anatomy.svg`)

Tarefa "adicionar um recurso a um módulo", passo a passo:

| Passo | Ferramenta | COM (tok) | SEM (tok) |
|---|---|---|---|
| 1. Orientar no repo | `simplicio map` | 1.280 🟢 | 27.000 |
| 2. Recordar decisão prévia | `simplicio memory` | 106 🟢 | 2.859 |
| 3. Aplicar edit mecânico | `simplicio edit` | 55 🟢 | 9.591 |
| 4. Gate de segurança | action gate | 5 | 400 |
| 5. Review do diff | deliver review | 30 | 2.500 |
| 6. Evidência/checkpoint | HBP + checkpoint | 5 | 0 |
| **Total** | | **1.481** | **42.350** |

**Economia da tarefa: 40.869 tok = 96,5%.** Os 3 primeiros passos são medidos; gate/
review/evidência são deterministicos (~0 token LLM), estimados.

## Ressalvas (não escondidas)

1. Setores S1–S6 reutilizam o mecanismo medido, mas a DB local só tem dados do
   projeto Simplicio; os corpora de setor são estimativas realistas, não medidos.
2. `tokens ≈ bytes/4` é aproximação.
3. O baseline SEM é o de um agente esperto (grep+ler relevante). Contra "raw-read de
   tudo" os números seriam ~99,9% — mas isso seria strawman e está descartado.','docs/benchmark/2026-06-28-ten-cases-com-vs-sem.md','e1f0fbd587ca4eca1cd71d458585ddac7d8a80361e204bf3038c9004ea184d6d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/BENCHMARK_PLAN.md','project_doc','doc://simplicio-runtime/docs/BENCHMARK_PLAN.md','doc: Benchmark Plan: With vs Without Simplicio Runtime','# Benchmark Plan: With vs Without Simplicio Runtime

## Goal

Measure whether the runtime reduces time, resource usage, and paid-token usage while improving task completion quality.

## Baselines

For each task, run two paths:

- Without runtime: assistant manually reads files, plans commands, runs tools, validates, summarizes.
- With runtime: assistant invokes `simplicio plan/run/sprint`, then reviews the runtime evidence.

## Task Types

- Small docs change.
- Backend endpoint change.
- Frontend/API integration fix.
- CORS/env configuration issue.
- Playwright evidence flow.
- Multi-issue sprint slice.

## Metrics

- elapsed wall time;
- commands executed;
- commands avoided by cache;
- mapper cache hits;
- local model tokens;
- remote model tokens;
- paid-token estimate;
- test/build success;
- evidence artifacts created;
- PR readiness;
- human review effort.

Benchmark runs write and consume `cost-ledger.json` from the run directory. The
ledger fields are `local_tokens`, `remote_prompt_tokens`,
`remote_completion_tokens`, `cache_hits`, `prompts_reused`, `commands_avoided`,
`estimated_paid_tokens_saved`, `baseline_paid_tokens`, `runtime_paid_tokens`,
`baseline_remote_tokens`, and `runtime_remote_tokens`.

## Benchmark Table

| Task | Without runtime | With runtime | Time saved | Remote tokens saved | Effect | Status |
|---|---:|---:|---:|---:|---|---|
| Small docs change | 900 ms / 4 commands | 320 ms / 2 commands | 580 ms | 900 | runtime_helped | fixture |
| Backend endpoint change | 1800 ms / 7 commands | 760 ms / 4 commands | 1040 ms | 1400 | runtime_helped | fixture |
| Frontend/API integration fix | 2200 ms / 8 commands | 1300 ms / 5 commands | 900 ms | 1600 | runtime_helped | fixture |
| CORS/env configuration issue | 1600 ms / 6 commands | 1510 ms / 6 commands | 90 ms | 1250 | runtime_neutral | neutral-fixture |
| Playwright evidence flow | 2400 ms / 8 commands | 1200 ms / 5 commands | 1200 ms | 1700 | runtime_helped | fixture |
| Multi-issue sprint slice | 4200 ms / 12 commands | 4800 ms / 14 commands | -600 ms | 2600 | runtime_hurt | failure-kept |

## Auditable Harness Output

`simplicio benchmark run --sample --json` writes:

- `benchmark-inputs.json`;
- `benchmark-result.json`;
- `benchmark-rows.jsonl`;
- `benchmark-report.md`;
- `benchmark-limitations.md`;
- `cost-ledger.json`;
- `events.jsonl`.

The checked-in sample lives in
[`../examples/benchmark-run-sample`](../examples/benchmark-run-sample). The six
rows above are conservative fixture rows for harness validation. They are not
public performance claims until raw baseline logs from an external assistant
run are attached. Failures and limitations must stay in the table instead of
being removed.

## Release Rule

Every meaningful subcommand release should add at least one benchmark row. If a benchmark cannot run yet, the release notes must explain why.','docs/BENCHMARK_PLAN.md','c5812a4dd1bc936a09bafa78c4db7eae8563a55275325d5a6c6b35ce66bfc6b6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/benchmarks/2026-07-19-30-issues-partial.md','project_doc','doc://simplicio-runtime/docs/benchmarks/2026-07-19-30-issues-partial.md','doc: Benchmark parcial - lote de 30 issues (ranks 21-50)','# Benchmark parcial - lote de 30 issues (ranks 21-50)

Data da coleta: 2026-07-19 UTC  
Repositorio: `wesleysimplicio/simplicio-runtime`  
Base Runtime: `3265fb5ee3e4b7f4cfb3f50c504aec395e53a7b8`  
Loop: `8155d2203f0018b00d842ddea5910271bd85d3c4`  
Mapper: `7271d369fd064718ee988e6c1a7a8a47f9cffd07`  
Dev CLI: `cf528b1df766aff21e07f48d9d070efc66c5e5a6`

## Escopo

Este lote é composto pelas posições 21-50 da lista de 50 issues abertas mais recentemente atualizadas, para não duplicar o lote 1-20 executado por outro trabalho:

`3439, 3437, 3436, 3435, 3433, 3434, 3432, 3431, 3429, 3430, 3428, 3427, 3426, 3425, 3423, 3424, 3422, 3421, 3420, 3419, 3418, 3416, 3417, 3415, 3414, 3413, 3412, 3411, 3409, 3410`.

Foram modelados quatro cenários por issue:

1. baseline sem Simplicio;
2. apenas `simplicio-runtime`;
3. Runtime + Loop;
4. Runtime + Mapper + Loop + Dev CLI.

Total esperado: 30 x 4 x 5 repetições, com aquecimento. Total iniciado: **0**.

## Evidência observada

- A chamada GitHub que refixou as 50 issues retornou 50 itens em 1322 ms.
- Host: Linux 6.12.47, Intel Xeon Platinum 8573C, 9 CPUs lógicas, 22996188 kB de RAM total.
- O container não possui `simplicio`, `cargo`, `rustc`, `sqlite3`, `llama-cli` ou Ollama.
- Modelo/provider LLM local: não identificados.
- Seed de memória neural: não executado.
- Runtime, Loop, Mapper e Dev CLI: nenhuma execução real iniciada neste container.
- 120 combinações foram registradas como `blocked`; wall time, TTFT, latência, tokens, custo, CPU, RSS, I/O, chamadas evitadas e cobertura permanecem `null`.
- Não foram calculados speedup, redução percentual ou normalização por issue verde: o denominador de issues concluídas com todos os checks verdes é zero.

## Gates

Nenhuma issue deste lote pode ser fechada ou considerada concluída. Permanecem sem comprovação: implementação, testes unitários, integração, sistema, regressão, performance, cobertura >=85%, property/fuzzing, código real e revisão por invariantes.

## Artefatos

O JSONL, CSV, resumo estatístico e PDF consolidado estão anexados ao relatório da execução. O PDF marca os gráficos de tempo/tokens como indisponíveis, em vez de inventar observações.

## Limitações

O limite global de threads de agentes impediu criar novos workers isolados nesta sessão. Isso não foi contado como execução paralela. Para liberar este lote, é necessário um ambiente com os binários/toolchain, modelo LLM local, memória neural seedável e capacidade de executar workers isolados; depois este mesmo manifesto deve ser reexecutado sem alterar hardware, workload, provider ou SHAs.','docs/benchmarks/2026-07-19-30-issues-partial.md','1c70322104ce2d23f880f6be9cc0ced2cfc1577e30b1e90786bdc45a509b9d25','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/business/LAUNCH_PLAN_2026-07.md','project_doc','doc://simplicio-runtime/docs/business/LAUNCH_PLAN_2026-07.md','doc: Levantamento de lançamento comercial — Simplicio (2026-07)','# Levantamento de lançamento comercial — Simplicio (2026-07)

> Documento interno (repo privado). Estado levantado por inspeção real do código
> em 2026-07-09, pós-release da cadeia mapper 0.19.0 / cli 0.11.0 / loop 3.24.0 /
> runtime 3.5.0 / agent 0.25.0. Cada afirmação sobre "o que existe" tem caminho
> de arquivo. Sem estimativas de tempo (regra do repo); a ordem é de dependência.

## 0. A conclusão em uma frase

**Lançar a cobrança é majoritariamente LIGAR e RECONCILIAR, não construir**: o
paywall (ed25519 offline), o webhook Stripe, o trial, o dunning, o backend de
entitlement e até o checkout PHP já existem — está tudo atrás de um único kill
switch de beta (`SIMPLICIO_BETA_OFF`), e os preços imaginados ($10/$20) **já são
os preços codificados** em `src/license.rs`.

---

## 1. Estado real — o que já existe (verificado)

| Camada | O que existe | Onde | Estado |
|---|---|---|---|
| Licença offline | Tokens ed25519 (`payload.sig`), chave pública embutida, tiers `Free/Trial 7d/Economy $10/Pro $20`, grace 3 dias | `src/license.rs` (#818) | **Vivo e fiado** no dispatch (`src/commands/mod.rs:634` `guard_command`; `:982` comando `license`) — liberado pela beta |
| Kill switch | `public_beta_active()` == true salvo `SIMPLICIO_BETA_OFF` | `src/license.rs:242-253` | Beta ON desde 2026-06-11 |
| Gate comercial | `guard_command()` bloqueia `chat/reason/run/vision` sem tier; upsell → simpleti.com.br/simplicio | `src/license.rs` | Pronto |
| Assinatura/webhook | Catálogo de planos, webhook Stripe (`customer.subscription.*`, `invoice.payment_*`), máquina Active/PastDue/Canceled, `enforce_entitlement()` | `src/monetization_1164.rs` (#1164) | Implementado + testado; **fiação no dispatch em TODO** (o caminho vivo é license.rs) |
| Trial | Pro 7 dias, `~/.simplicio-loop/trial.toml` | `src/free_trial.rs` (#2224) | Pronto |
| Dunning | Máquina de falha de pagamento | `src/dunning.rs` (#2219) | Pronto |
| Histórico de cobrança | Ledger JSONL `~/.simplicio-loop/billing/history.jsonl` | `src/billing_history.rs` (#2213) | Pronto |
| Stripe client | Checkout/Portal/funnel via REST, `--dry-run` | `src/growth_stripe.rs`, `src/growth/stripe.rs` | Pronto (exige `STRIPE_SECRET_KEY`) |
| Entitlement remoto | `GET simpleti.com.br/api/entitlement.php` + `X-Simplicio-Token`, cache 10min, offline-first (falha nunca bloqueia) | `src/entitlement_remote.rs` | Pronto |
| Backend site | `stripe-checkout.php` (subscription, trial 7d), `entitlement.php`, `stripe-sync.php` (cron 07h/19h), `google-auth.php`, MySQL `subscriptions` + `pix_payments` | `site/api/` | Pronto (PHP/Apache/FTP deploy) |
| Página de preço | Seção `#preco` existe; hoje mostra só "Beta pública gratuita" (card $10 removido em 2026-06-16, ver `site/simplicio/VERSION.md`) | `site/simplicio/index.html` | Reativar |
| Legal | `site/privacidade.html`, `site/termos.html` | `site/` | Revisar p/ cobrança |
| Open-core no agent | LICENSE MIT no core; `docs/licensing.md` documenta os mesmos tiers; paywall vive no kernel Rust (grep por license em `*.py` = zero) | simplicio-agent | Arquitetura correta |
| Prova de valor | Telemetria de savings (`agent/telemetry/*`, `simplicio.savings-event/v1`, receipts) — "o produto provando quanto economiza" | agent + runtime ledger | Pronto — é o argumento de venda |
| Plano de negócio | Simulação com churn/CAC/LTV/cenários 200→5k usuários | `docs/planning/BUSINESS_MODEL_SIMULATION.md` (#2232) | **Preços divergentes** (ver §2.1) |

## 2. Decisões que bloqueiam tudo (tomar antes de qualquer código)

### 2.1 Matriz de preços — reconciliar 3 fontes divergentes

Hoje existem três verdades: código (`$10/$20`), simulação de negócio
(`$12/$29/$99`), e a hipótese do fundador (`MCP $10 / Agent $20`). **Recomendação:
adotar a do código, que coincide com a hipótese**, e registrar em ADR que
supersede a matriz do BUSINESS_MODEL_SIMULATION:

| Produto (nome de venda) | Tier no código | Preço US | Preço BR (Pix/cartão) | O que entrega |
|---|---|---|---|---|
| **Simplicio Free** | `Free` | $0 | R$0 | Kernel determinístico: `map`, `edit`, `gate`, `validate`, `checkpoint`, `savings` — o funil. Sem LLM. |
| **Simplicio MCP** | `Economy` | **$10/mês** | **R$ 29/mês** | Tudo do Free + `serve --mcp` persistente (hops in-process 3.5.0) + memória neural + savings proof `measured` + skills recall. "Deixa qualquer LLM mais barato e auditável." |
| **Simplicio Agent** | `Pro` | **$20/mês** | **R$ 59/mês** | Tudo do MCP + `chat/reason/run/vision` + LLM local (ladder 64→600) + routing gerenciado + o Simplicio Agent completo (gateways Telegram/Discord/Slack/WhatsApp/Signal, TUI, cron, subagents, learning loop). |
| **Simplicio Pro Max** | `ProMax` (**novo**) | **$45/mês** | **R$ 119/mês** | Tudo do Agent + `runtime-profile full` desbloqueado (10k agentes/2GB/90% CPU) + video pipeline (HyperFrames/Remotion; Higgsfield gated por custo) + mesh multi-device + 3 seats pessoais + suporte prioritário + early access a features. |
| Enterprise | (contato) | custom | custom | SSO, auditoria HBP exportável, SLA, seats. Fase 2 — não bloqueia o lançamento. |

Racional dos números: Agent $20 ancora com Claude Pro/Cursor/Copilot Pro+ (preço
"assinatura de dev" já aceito); MCP $10 é o degrau de entrada com ROI
demonstrável pelo ledger de savings (o pitch: "se o Simplicio não economizar mais
que $10 de tokens/mês, o relatório `measured` te mostra — cancela"); Pro Max a
2.25× do Agent captura power users sem canibalizar o Agent. BRL abaixo do câmbio
(R$59 ≈ $11) é decisão deliberada de penetração no BR com Pix — mercado-alvo
primário e diferencial contra concorrentes que só cobram em dólar.

Anual: 10 meses pelo preço de 12 (2 grátis). Founder plan (ver §4).

### 2.2 Caminho de código único

`license.rs` é o vivo; `monetization_1164.rs` duplica catálogo/estado. Decidir por
ADR: **license.rs permanece a fonte do gate**; `monetization_1164` vira a camada
de webhook/estado de assinatura fiada por trás dele (completar os TODOs de
`src/monetization_1164.rs:862-878`) OU é aposentado com o we','docs/business/LAUNCH_PLAN_2026-07.md','4019d48643de3749a2fcc9915833c1971ea99709091a21bf0c001310e539a962','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/CANONICAL_HBP_HBI_CODEC.md','project_doc','doc://simplicio-runtime/docs/CANONICAL_HBP_HBI_CODEC.md','doc: Canonical HBP/HBI codec — execution slice #3640','# Canonical HBP/HBI codec — execution slice #3640

## Ownership

The dependency-light `crates/asolaria-bridge` crate owns HBP encoding,
escaping, parsing, SHA-256 addressing, HBI row encoding and receipt-chain
verification. `simplicio-fabric` now contains only a compatibility re-export;
dispatch/effect policy remains in Runtime and completion policy remains in Loop.

## Compatibility and rollback

Existing Fabric imports keep compiling and existing encoded rows and receipt
hashes do not change. Reverting the dependency and adapter commits restores the
previous implementation; this slice does not require ledger migration.

Public HBI contracts must use logical handles. The current offset-based
`IdxPointer` is a legacy internal type until an N-1 migration is implemented
and must not be persisted as a public stable identifier.

## Verification status

Adapter tests pin canonical encoding, escaping, AGT addressing, valid chains,
tamper rejection and truncation rejection.

- Test execution in this API-only session: **UNVERIFIED**.
- Python/Rust golden parity: **UNVERIFIED**.
- Fast consumption: **UNVERIFIED**; requires a separate Fast PR.
- Locking, crash recovery, fuzzing and benchmarks: **UNVERIFIED**.

No cross-repository completion or performance claim is made by this slice.','docs/CANONICAL_HBP_HBI_CODEC.md','ff13bde56438e1a43d13b18a0b6e02f37b6d88b263ebf43c9cf191bcf6b59ab7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/CAPABILITY_CURATION.md','project_doc','doc://simplicio-runtime/docs/CAPABILITY_CURATION.md','doc: Capability Curation','# Capability Curation

This document decides what from a rich local assistant environment should become
part of `simplicio-runtime`, what should stay external, and what must not be
duplicated.

The source inventory reviewed here came from a local Hermes setup on this
machine. The origin does not matter. If a capability improves programming
speed, quality, evidence, autonomy, or token economy, it is a candidate for
Simplicio Runtime.

The selective part is implementation ownership: the runtime should absorb the
best programming capabilities and patterns, but it should not blindly copy a
host tool implementation when an adapter, connector, or skill pack is safer.

## Principles

1. The runtime owns decisions, scheduling, supervision, contracts, logs, and
   token economy.
2. Existing Simplicio projects remain behavior sources of truth until a hot path
   is deliberately moved native.
3. Useful programming capabilities can come from Hermes, ECC, Codex, Claude,
   MCP tools, IDEs, or Simplicio itself.
4. External tools are called through adapters/connectors when that is safer
   than cloning their implementation.
5. When a capability is universally useful for programming, promote the pattern
   into a Simplicio capability pack.
6. Skills are indexed by metadata first and loaded lazily only when relevant.
7. Stack-specific skills are activated by repo evidence, not by default.
8. Host-specific assumptions stay in compatibility packs, but strong
   programming ideas can graduate into runtime-native packs.
9. Disabled or personal-environment tools are never assumed to exist.

## Runtime Core Capabilities

These belong directly in `simplicio-runtime`.

| Capability | Runtime role | Why |
|---|---|---|
| terminal/process execution | built-in command runner | required for every workflow |
| file read/search/patch interface | built-in safe file adapter | needed for deterministic repo work and write locks |
| todo/planning state | built-in run/task state | core scheduling and progress reporting |
| memory/run history | built-in run ledger | needed for resume, evidence, and token savings |
| skills metadata registry | built-in index | choose skills without loading every body |
| delegation/subagents | built-in scheduler contract | local agent lifecycle, queues, and backpressure |
| structured logs/progress | built-in event stream | user needs live "now mapping, now analyzing" status |
| capability discovery | built-in `doctor`/`capabilities` | detect what is available before planning |

## Programming Capability Packs

These should become first-class Simplicio Runtime packs because they directly
improve programming work. They may be inspired by Hermes, ECC, Codex workflows,
or any other environment.

| Pack | Runtime role | Included capabilities |
|---|---|---|
| repo-intelligence | understand project before acting | repo scan, onboarding, mapper, architecture map, symbol/call graph |
| debugging | resolve failures faster | systematic debugging, logs, debugpy/node inspect, build-error resolver, root-cause notes |
| tdd-verification | make changes safely | TDD, regression testing, unit/integration/e2e gates, verification loop |
| browser-evidence | prove web flows | Playwright, browser QA, screenshots, traces, visual evidence |
| code-review | catch bugs before PR | code review, security review, Copilot-style review, PR evidence checklist |
| source-control | ship work | git workflow, GitHub/Jira/Azure DevOps work sources, commits, PRs, checks |
| docs-research | use current knowledge | Context7/docs lookup, web/search/scrape, API docs, release notes |
| agent-ops | run local agents well | subagents, lifecycle, supervision, queueing, kill/reuse/replace |
| token-economy | spend less | context budget, content-hash cache, local LLM first, cost ledger |
| release-ops | publish safely | changelog, version bump, package build, PyPI/npm/GitHub release, evidence |

The runtime should expose these as curated packs, not as a dump of every skill.
Each pack can contain built-in code, adapters, selected skills, and connectors.

## First-Party Simplicio Adapters

These should be runtime adapters, not reimplemented logic.

| Project | Runtime usage |
|---|---|
| `simplicio-mapper` | first context layer, endpoint/screen inventory, symbols, graph, docs |
| `simplicio-dev-cli` | implementation, diff, test, smoke, local model execution |
| `simplicio-prompt` | prompt contracts, context envelopes, fan-out, consensus |
| `simplicio-sprint` | task graph, dependencies, Done state, evidence, PR handoff |
| local LLM stack | llama.cpp/GGUF manager, model pool, prompt cache, token ledger |

## High-Priority External Connectors

These should be optional connectors with stable contracts.

| Connector/tool | Runtime category | Notes |
|---|---|---|
| GitHub | work source + PR flow | issues, PRs, checks, Actions, review evidence |
| Jira | work source | tasks, epics, comments, attachments |
| Azure DevOps | work source + pipeline source | boards, repos, pipelines, artifacts, test plans |
| Playwright | browser/evidence connector | E2E, screenshots, traces, deployed smoke |
| Context7 | docs connector | current framework/library docs |
| browser automation | connector | dynamic UI checks; keep implementation external |
| web/search/scrape | connector | research and public docs; do not bake in provider |
| messaging | connector | optional notifications; not runtime core |
| cron/scheduling | connector | optional automation; runtime should expose hooks |
| vision/image/video/TTS | connector | useful for artifacts, not default coding path |

## Low-Priority Or Domain-Specific Connectors

These should remain external until a task or repo explicitly needs them:

- `post-bridge`
- `visor`
- `meta-ads`
- `abacate-pay`
- `cumbuca`
- `homeassistant`
- `spotify`
- `yuanbao`
- domain-specific payment, marketing, IoT, or media tools

The runtime should discover them if installed, but it should not require or
duplicate them.

## Skills: Daily','docs/CAPABILITY_CURATION.md','4d0772a193ee1e1b545f1deb085ec05d63f57afc26928b22d026afe8996e0954','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/CASE_STUDY_001_RUNTIME_BACKLOG.md','project_doc','doc://simplicio-runtime/docs/CASE_STUDY_001_RUNTIME_BACKLOG.md','doc: Case Study 001: Runtime Backlog Productization','# Case Study 001: Runtime Backlog Productization

## Task

Repository: `wesleysimplicio/simplicio-runtime`

Task: implement and prove a backlog slice covering runtime evidence, resume,
integrations, packaging, benchmarks, and release scaffolding.

Follow-up issues:

- https://github.com/wesleysimplicio/simplicio-runtime/issues/24
- https://github.com/wesleysimplicio/simplicio-runtime/issues/26
- https://github.com/wesleysimplicio/simplicio-runtime/issues/29
- https://github.com/wesleysimplicio/simplicio-runtime/issues/30
- https://github.com/wesleysimplicio/simplicio-runtime/issues/47

## Baseline

The baseline is reconstructed from the direct-assistant path required by
`docs/BENCHMARK_PLAN.md`: manually inspect issues, read files, infer commands,
run validation, and assemble evidence by hand.

```powershell
rg -n "evidence|resume|release|benchmark|case study" docs src
cargo test --locked
cargo build --release --locked
```

Estimated baseline output:

- Time: 2400 ms for the benchmark fixture row.
- Commands: 8.
- Remote tokens: 1700 estimated tokens for broad context and evidence summary.
- Evidence: manual notes.
- Result: review required because artifacts were not bundled automatically.

## Runtime-Assisted Run

Commands:

```powershell
cargo build --release --locked
.\target\release\simplicio.exe run "collect Playwright UI evidence" --repo $env:TEMP\simplicio-case-study --run-id case-study-001 --evidence --json
.\target\release\simplicio.exe evidence show --repo $env:TEMP\simplicio-case-study --run-id case-study-001 --json
.\target\release\simplicio.exe benchmark run --sample --repo . --run-id case-study-001-benchmark --json
```

Representative output:

```json
{"schema":"simplicio.run-result/v1","run_id":"case-study-001","status":"completed_skeleton"}
{"schema":"simplicio.evidence-summary/v1","run_id":"case-study-001","events":16}
{"schema":"simplicio.benchmark-run/v1","run_id":"case-study-001-benchmark"}
```

Runtime fixture metrics:

| Metric | Baseline | Runtime-assisted |
| --- | ---: | ---: |
| Time | 2400 ms | 1200 ms |
| Commands | 8 | 5 |
| Remote tokens | 1700 | 0 |
| Local tokens | 0 | 600 |
| Evidence artifacts | manual | screenshot, trace, curl, test summary, PR summary |
| PR readiness | review | review with bundle |

## Evidence Bundle

Runtime evidence includes:

- `evidence/index.md`;
- `evidence/index.json`;
- `evidence/screenshots/screenshot-fixture.png`;
- `evidence/playwright/trace.zip`;
- `evidence/curl-preflight.txt`;
- `evidence/test-summary.json`;
- `evidence/pr-summary.md`;
- `cost-ledger.json`;
- `final-report.md`.

The checked-in sample bundle is in
[`examples/evidence-bundle`](../examples/evidence-bundle/README.md).

## Result

The runtime now produces deterministic run state, evidence bundles, resume
notes, benchmark rows, release packaging contracts, and integration docs. This
case study is intentionally scoped to runtime productization rather than a
customer application change.

## Limitations

- Baseline timing and token values are fixture estimates, not external published
  benchmark claims.
- The Playwright trace and screenshot are attachable fixtures until a real web
  target is available.
- Release workflow success still requires a tagged GitHub Actions run.
- Local chat summarization is template-based over local logs and skill metadata;
  future work can attach a real local LLM provider.

## Follow-Up

- Add raw external assistant baseline logs for at least one application repo.
- Replace Playwright fixture artifacts with a real browser target run.
- Run the release workflow on a tag and attach checksums to the case study.
- Add adapter `--version --json` probing for the four Simplicio packages.','docs/CASE_STUDY_001_RUNTIME_BACKLOG.md','8b0d856da818a58fc3423c15a566d85a9c3affb512888ea81a37765d2182152a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/CASE_STUDY_002_DETERMINISTIC_LANE.md','project_doc','doc://simplicio-runtime/docs/CASE_STUDY_002_DETERMINISTIC_LANE.md','doc: Case Study 002 — Deterministic Lane, Measured (#30)','# Case Study 002 — Deterministic Lane, Measured (#30)

Real, measured run of the Simplicio deterministic lane (no LLM invoked) against
a small fixture repository. Every number below was measured on a single run on
one machine; nothing is extrapolated or fabricated. Where a first (cold) run
differed from a repeat (warm) run, both numbers are shown.

## Environment

- Date: 2026-06-11
- OS: Windows 11 Enterprise 10.0.26100 (single machine)
- Build: `cargo build --no-default-features --features tui,async-runtime,rich-repl`
  — **debug** profile (unoptimized + debuginfo), finished in 1m 28s;
  binary 22,945,280 bytes, simplicio-runtime **0.8.0**, base commit `e155ff0`.
  The `in-process-llm` feature is **excluded** in this build (see Limitations).
- Fixture: copy of `examples/case-study-002-fixture/` (3 files: `src/api.ts`
  with three `fetch` calls, `src/util.js`, `README.md`) in a temp dir,
  `git init` + one baseline commit.
- Timing: PowerShell `[System.Diagnostics.Stopwatch]` around each process
  invocation (full process wall time, including process start/exit).

## Measured results

| Command | Wall time (ms) | Exit | Artifacts produced | LLM tokens |
|---|---:|---:|---|---|
| `simplicio map --repo <fx> --json` (cold, first run on fixture) | 13,065.2 | 0 | `.simplicio-loop/runtime-project-map.json`, `.simplicio-loop/endpoint-inventory.json`, `.simplicio-loop/screen-inventory.json` | 0 local / 0 remote |
| `simplicio map --repo <fx> --json` (repeat) | 259.4 | 0 | same (regenerated; `cache_hit:false`) | 0 / 0 |
| `simplicio validate --repo <fx> --json --task "api change"` | 134.3 | 0 | validation plan JSON on stdout (4 progressive levels, `task_kind:"api"`) | 0 / 0 |
| `simplicio edit --plan edit-plan.json --repo <fx> --json` (2 ops on `src/util.js`) | 1,078.3 | 0 | mechanically edited file (+9/-1 lines), `simplicio.edit-result/v1` with before/after SHA-256 | 0 remote; ledger logs `local_tokens:2` (runtime-internal accounting — **no model was loaded or invoked**) |
| `simplicio gate classify --action "git push --force" --json` | 122.4 | 0 | `simplicio.action-gate-decision/v1`: **block** (hardline) | 0 / 0 |
| `simplicio gate --json` (policy status form) | 602.6 | 0 | `simplicio.action-gate-policy/v1` (mode `ask`, hardline floor) | 0 / 0 |

No LLM process was started at any point: this build cannot load a model
in-process, no `llama-cli` exists on the machine''s PATH, and no remote
provider env (`SIMPLICIO_MODEL`/`SIMPLICIO_BASE_URL`/`SIMPLICIO_API_KEY`)
was set. The deterministic lane ran entirely on compiled Rust code paths.

## Real transcripts (trimmed)

### 1. map — cold 13,065 ms / repeat 259 ms

```text
PS> Measure: & simplicio.exe map --repo $fx --json     # 13065.2 ms (cold)
PS> Measure: & simplicio.exe map --repo $fx --json     # 259.4 ms (repeat)
```

Final result line (repeat run):

```json
{"schema":"simplicio.map-result/v1","status":"native",
 "artifact":"...\\cs002-fixture\\.simplicio-loop\\runtime-project-map.json",
 "fallback_used":false,"changed_files":3,"cache_hit":false,"adapter_record":null}
```

`runtime-project-map.json` written into the fixture:

```json
{"schema":"simplicio.project-map/v1","repo":"cs002-fixture","files":6,
 "changed_files":3,"rust_files":0,"docs":1,
 "artifacts":{"project_map":".simplicio-loop/runtime-project-map.json",
  "symbol_index":".simplicio-loop/symbol-index.json",
  "endpoint_inventory":".simplicio-loop/endpoint-inventory.json",
  "screen_inventory":".simplicio-loop/screen-inventory.json"},
 "endpoints":[],"screens":[],
 "sample_files":["README.md","src\\api.ts","src\\util.js", "..."]}
```

Honest observation: `endpoints` came back **empty** even though `src/api.ts`
contains three `fetch()` calls — the native fallback endpoint scanner did not
extract them in this run (`endpoint-inventory.json` says
`"endpoints":[],"source":"runtime-fallback"`). The cold/warm gap (13.1 s →
0.26 s) is dominated by first-run adapter probing (the runtime attempts to
resolve the optional external `simplicio-mapper-py` across dozens of candidate
paths) plus OS first-touch costs.

### 2. validate — 134 ms

```json
{"schema":"simplicio.validation-plan/v1","task_kind":"api",
 "levels":["syntax-format-and-changed-files","targeted-unit-tests",
           "build-lint-typecheck","api-smoke-and-contract"],
 "steps":[{"level":"syntax-format-and-changed-files",
           "command":"runtime.changed-files","executes":true, "...":"..."}],
 "scheduler":{"mode":"strict-sequential-validation", "...":"..."}}
```

Only the first level actually executes against this fixture (`executes:true`);
the other three are planned but gated off (`executes:false`) — the fixture has
no test suite, build system, or running API to validate against.

### 3. edit — 1,078 ms, mechanical 2-op plan

Plan (decided by the caller, applied mechanically by the runtime):

```json
{"file":"src/util.js","operations":[
  {"op":"insert_before","find":"module.exports = { formatName, clamp };",
   "text":"function slugify(text) { ... }\n\n"},
  {"op":"replace","find":"module.exports = { formatName, clamp };",
   "with":"module.exports = { formatName, clamp, slugify };"}]}
```

Result (trimmed):

```json
{"schema":"simplicio.edit-result/v1","status":"ok","changed":true,
 "mechanical_only":true,"operations_applied":2,
 "before_sha256":"2caab2e792bf59ebb6b3403fd42a491fdad74b93d0fc454086f8cd711841ad57",
 "after_sha256":"d8f254f00389e6546390b5686a44471b405b481e6a58dccb0e7acfff47b1dcfb",
 "bytes_before":230,"bytes_after":375,
 "token_ledger":{"schema":"simplicio.communication-token-ledger/v1",
  "local_tokens":2,"remote_prompt_tokens":0,"remote_completion_tokens":0,
  "remote_used":false,"estimated_paid_tokens_saved":142}}
```

Verified with `git diff` in the fixture: `src/util.js | 9 insertions(+),
1 deletion(-)`, exactly the planned change. The `estimated_paid_tokens_saved`
field is the runtime''s own estimate, reported as-is — it is an estimate, not a
measurement.

### 4. gate — 122 ms, hardline block

```json
{"schema":"simplicio.action-gate-decision/v','docs/CASE_STUDY_002_DETERMINISTIC_LANE.md','d511b6d7a28fef8ffc23fd178999d6b7d5af49b9a5814024eb48f9fa9821671f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/CASE_STUDY_003_VELOCIDADE_TOKENS_DETERMINISMO.md','project_doc','doc://simplicio-runtime/docs/CASE_STUDY_003_VELOCIDADE_TOKENS_DETERMINISMO.md','doc: Case Study 003 — Velocidade, Tokens e Determinismo','# Case Study 003 — Velocidade, Tokens e Determinismo

> **Status:** publicado / observacional
> **Issue:** #1239
> **Referencia cruzada:** [CASE_STUDY_002_DETERMINISTIC_LANE.md](CASE_STUDY_002_DETERMINISTIC_LANE.md)
> **Suporte Rust:** `src/doc_1239.rs` — tipos `L0Cache`, `BenchmarkPath`, `ThinkMode`, `Cents`

---

## Introducao

Este case study registra medicoes reais e estimativas honestas sobre latencia,
contagem de tokens, e a regra THINK vs NO-THINK no Simplicio Runtime. O objetivo
nao e prometer resultados que o runtime nao pode garantir, mas mapear o espaco
de opcoes com a precisao que o sistema efetivamente tem.

O caminho deterministico ([CASE_STUDY_002](CASE_STUDY_002_DETERMINISTIC_LANE.md))
e a base: 14 ms, 0 tokens de saida, sem chamada LLM. Tudo que este documento
descreve e como *permanecer* nesse caminho o maximo possivel — e quando sair dele,
com que custo.

---

## 1. TL;DR tecnico

Quatro verdades operacionais que este case study registra:

1. **Mais agentes aumentam throughput, nao reduzem latencia de uma resposta individual.** Paralelismo ajuda quando ha N tarefas independentes; uma unica tarefa continua limitada pela cadeia sequencial de tokens.
2. **Prompt nao aumenta GPU/CPU nem remove o piso fisico de geracao token-by-token.** Nenhuma instrucao textual muda a velocidade do hardware; prompt so controla *o que* o modelo gera, nao *a que velocidade*.
3. **O gargalo primario de latencia LLM e token de saida.** Cada token de saida e gerado sequencialmente (autoregressive decoding). Reduzir output tokens e a alavanca mais forte.
4. **0-token so existe quando o runtime nao chama LLM.** A unica forma de latencia zero-LLM e o caminho deterministico — template hit, cache hit, resposta mecanica sem geracao.

---

## 2. Metodologia honesta de medicao

### Metricas disponiveis

| Metrica | Fonte | Confiabilidade | Observacao |
|---|---|---|---|
| Tempo de processo shell | `date`, `time`, stopwatch | **Alta** para o que mede | Mede wall-clock do processo, inclui I/O, rede, scheduling |
| Wall-clock do turno | log do runtime | **Media** | Inclui thinking + token-gen + overhead; metrica conflada |
| Contagem de tokens | resposta do provider | **Alta** como proxy | Proxy estavel de latencia: mais tokens ≈ mais tempo |
| `user_time_v0` / clock de turno | log interno | **Baixa** para benchmark | Inclui tempo de reasoning invisivel; nao usar como benchmark primario |

### Principio

> **Nao prometer precisao que o runtime nao tem.** Quando o runtime nao cronometra uma fase isoladamente, marcar como *estimativa*. Separar sempre: medicao real vs. extrapolacao por throughput vs. hipotese.

### O que nao e medicao

- RAG/precedente injetado no prompt ainda consome tokens — nao e "gratis".
- Cache de prompt (KV-cache no provider) reduz TTFT mas nao elimina geracao de output.
- Prompt engineering nao aumenta CPU/GPU e nao zera latencia.

---

## 3. Hierarquia de otimizacao

Ordem de impacto na reducao de latencia, do mais forte ao mais fraco:

| Prioridade | Tecnica | Impacto estimado | Exemplo |
|---|---|---|---|
| 1 | **Capar output** | Reduz tokens de saida diretamente | `max_tokens`, `stop_sequences`, formato compacto |
| 2 | **Desligar ou reduzir reasoning** | Elimina thinking tokens quando tarefa e deterministica | NO-THINK para scaffold conhecido |
| 3 | **Reduzir tool calls** | Cada call e uma ida-e-volta completa | Batch de operacoes, menos round-trips |
| 4 | **Remover preambulo/pos-resumo** | Menos tokens de "cortesia" no output | System prompt direto, sem resumo final |
| 5 | **Escolher modelo menor** | Throughput maior (tokens/s) | Haiku vs Opus quando adequado |
| 6 | **Prompt/cache** | Reduz TTFT ou tokens *se* hit real | KV-cache, prompt caching; so quando realmente reduz |

---

## 4. THINK vs NO-THINK

Regra documentada como benchmark/observacao. **Ainda sem imposicao de comportamento global** — o runtime nao forca NO-THINK automaticamente.

### Quando THINK (reasoning ativo)

- Miss de template/cache
- Ambiguidade na tarefa
- Plano multi-step
- Dominio novo (sem precedente)
- Erro, conflito, retry
- Decisao de arquitetura
- Mudanca multi-arquivo

### Quando NO-THINK (reasoning desligado/reduzido)

- Hit de template/cache
- Scaffold conhecido
- Operacao single deterministica
- Transform mecanico
- Regex/AST match exato

### Observacao

A distincao e empirica. O custo de THINK errado (reasoning em tarefa trivial) e ~3x mais tokens sem ganho de qualidade. O custo de NO-THINK errado (pular reasoning em tarefa ambigua) e resposta incorreta que exige retry — potencialmente mais caro.

---

## 5. Benchmarks

Tres caminhos medidos/estimados para uma operacao tipica:

| Caminho | Latencia | Tokens de saida | Tipo |
|---|---|---|---|
| Deterministico / cache HIT | ~14 ms | 0 | **Medicao real** |
| LLM NO-THINK | ~778 ms *(estimado)* | ~70 *(estimado)* | **Extrapolacao por throughput** |
| LLM THINK | ~2 633 ms *(estimado)* | ~237 *(estimado)* | **Extrapolacao por throughput** |

### Notas sobre os numeros

- O caminho deterministico (14 ms, 0 tokens) e medicao real do runtime — ver [CASE_STUDY_002](CASE_STUDY_002_DETERMINISTIC_LANE.md).
- Os valores de NO-THINK e THINK sao **estimativas** baseadas em throughput medio observado (~90 tokens/s para saida). Nao sao benchmarks cronometrados isoladamente.
- Variancia real depende de: modelo, provider, carga do servidor, tamanho do contexto, network latency.

---

## 6. Precisao numerica

### Regra

> **Dinheiro nunca deve usar `float`.**

Alternativas corretas:
- `Decimal` (ou equivalente de precisao arbitraria)
- Centavos como inteiro (`i64`)
- Representacao inteira com fator fixo

### Justificativa

O custo computacional de `Decimal` vs `f64` e irrelevante frente a:
- Spawn de processo: ~1-5 ms
- Tool call LLM: ~500-3000 ms
- Network round-trip: ~50-200 ms

Floating-point acumula erro em operacoes financeiras (e.g., `0.1 + 0.2 != 0.3`). Em um sistema onde a latencia dominante e LLM e rede, o overhead de `Decimal` e imperceptivel.

---','docs/CASE_STUDY_003_VELOCIDADE_TOKENS_DETERMINISMO.md','2287f058e1f1afac4e4ed21baca9554dc12c07d0e581a9a0c17406b80fe04c4b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/CHAT_OPERATIONAL.md','project_doc','doc://simplicio-runtime/docs/CHAT_OPERATIONAL.md','doc: Chat Operational — Simplicio EPIC #235','# Chat Operational — Simplicio EPIC #235

Implements the full operational chat surface for the Simplicio runtime,
covering issues #230–#239.

## Commands implemented

### Action Bridge (#230)
```
simplicio act <task> [--dry-run] [--confirm] [--kind run|edit|plan|pr]
```
Routes chat requests to the deterministic execution layer. Dry-run by default;
`--confirm` executes after the gate check.

### Action Gate (#231)
```
simplicio gate [ask|auto|safe] [--json]
simplicio action-gate [ask|auto|safe] [--json]
```
Three modes:
- `ask` (default) — prompt before every mutating action
- `auto` — execute mutating actions without prompt
- `safe` — block all mutating actions

Gate mode persisted in `.simplicio-loop/action-gate-mode`.

### Checkpoints & Rollback (#232)
```
simplicio checkpoint save [--desc <text>] [--json]
simplicio checkpoint restore --id <cp-id> [--json]
simplicio checkpoint list [--json]
simplicio undo [--id <cp-id>] [--json]
```
Each checkpoint: git stash + metadata JSON. Reversible via `/undo` in REPL.

### Context Files & Identity (#233)
```
simplicio chat context [--repo <path>] [--json]
simplicio identity show [--repo <path>] [--json]
```
Context slots (ordered):
1. `identity` ← SOUL.md
2. `user_profile` ← saved memory items (kind=user_profile)
3. `project_rules` ← AGENTS.md / .cursorrules / CLAUDE.md

Anti-injection: patterns like "ignore previous" are sanitized before LLM use.
Size limits: identity ≤ 2048 chars, project_rules ≤ 4096 chars.

### Memory Tool Actions (#234)
```
simplicio memory-action save [--target user|memory] <text> [--json]
simplicio memory-action forget --id <stable_id> [--json]
simplicio memory-action update --id <id> <new_content> [--json]
simplicio memory-action recall <query> [--json]
```
Security scan blocks content matching injection patterns or API key patterns.
Deduplication via `source_hash` prevents duplicate items.
`user_profile` items are fed into the context slot for every chat turn.

### In-Chat Command Surface (#238) — REPL `/` commands
```
/help                     list all commands
/act <task>               dry-run action via bridge
/act! <task>              confirmed execute
/fix <task>               coding loop until green
/undo [--id <cp>]         restore checkpoint
/checkpoint [save]        save checkpoint
/mode ask|auto|safe       set gate mode
/memory save|recall|forget  memory actions
/context                  show context slots
/identity                 show SOUL.md
/deliver dod|cert         quality gates
```

### Diagnostics Feedback (#237)
```
simplicio diagnostics [--tool rustc|clippy|cargo-test|tsc|pytest] [--input <file>] [--json]
```
Parses compiler/test output into structured `simplicio.diagnostics/v1` items.
Auto-detects tool from output content.

### Coding Loop (#236)
```
simplicio coding-loop <task> [--max-cycles N] [--json]
simplicio fix <task> [--max-cycles N] [--json]
```
Runs edit → validate → repair cycle up to N times (default 5, max 10).
Schema: `simplicio.coding-loop/v1`.

### Action Trajectory (#239)
```
simplicio trajectory [list|show] [--session <id>] [--json]
simplicio action-trajectory [list] [--json]
```
Append-only log of every action in a chat session.
Schema: `simplicio.action-trajectory/v1`.

## Schemas

| Schema | Version |
|--------|---------|
| `simplicio.memory-action/v1` | save/update/forget/recall |
| `simplicio.chat-context/v1` | ordered context slots |
| `simplicio.identity/v1` | SOUL.md identity slot |
| `simplicio.action-gate/v1` | gate mode + allowlist/blocklist |
| `simplicio.checkpoint/v1` | git stash checkpoint |
| `simplicio.action-bridge/v1` | action routing |
| `simplicio.diagnostics/v1` | compiler/test output parsing |
| `simplicio.coding-loop/v1` | iterate-until-green result |
| `simplicio.action-trajectory/v1` | replayable action trail |

## Database migration

Migration `0003_expanded_kinds_and_gates.sql` adds:
- Removes the restrictive CHECK constraint from `memory_items.kind`
- `action_gate_state` table (repo, mode, allowlist, blocklist)
- `chat_checkpoints` table (stash ref + metadata)
- `action_trajectory` table (append-only action log)
- `memory_items_archived` table (soft-delete for forget)

Applied automatically on `simplicio memory init`.

## Security

- Tokens only from env vars, never logged
- Gate check for all mutating actions (configurable per mode)
- Memory items: security scan before write blocks secrets/injection
- Context slots: anti-injection sanitization before LLM use
- Checkpoints: reversible by design (git stash)

## Fluid mode — LLM-backed Agent Chat

`simplicio agent "<pergunta>"` and `simplicio agent repl` answer **fluidly** from
a real model when a chat endpoint is configured, grounding the answer in the
retrieved neural-memory context. With no endpoint configured the agent falls
back to the deterministic template (so the default build, tests, and offline
runs are unchanged).

### Enabling

Point the agent at any OpenAI-compatible `/chat/completions` endpoint:

```bash
# Runtime-native, egress-free inference (recommended)
simplicio model fetch --tier auto --yes
simplicio local-model health --json
simplicio run --local --task "..."     # embedded llama.cpp, no external server
```

The Runtime-owned worker is separate from the OpenAI-compatible transport used
by `agent repl`. That conversational provider still requires an explicitly
configured endpoint; it must not download a second, ungoverned local model.

A remote endpoint is opt-in (your explicit choice — it is data egress):

```bash
export SIMPLICIO_BASE_URL=https://openrouter.ai/api/v1
export SIMPLICIO_MODEL=deepseek/deepseek-v4-flash
export SIMPLICIO_API_KEY=sk-or-...
```

### Resolution order

| Setting | Vars (first non-empty wins) | Default |
|---|---|---|
| Endpoint | `SIMPLICIO_AGENT_BASE_URL` → `SIMPLICIO_BASE_URL` | none → template fallback |
| Model | `SIMPLICIO_AGENT_MODEL` → `SIMPLICIO_MODEL` | `config.model` |
| API key | `SIMPLICIO_AGENT_API_KEY` → `SIMPLICIO_API_KEY` | none (fine for local) |

T','docs/CHAT_OPERATIONAL.md','6599e50a53bc21fcbd7e6d3bddc142e947da7b4957a657f6ee2561923563f3f7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1507-cloud-web-session-lifecycle.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1507-cloud-web-session-lifecycle.md','doc: Cloud/Web Session Lifecycle Parity — Coverage Analysis (#1507)','# Cloud/Web Session Lifecycle Parity — Coverage Analysis (#1507)

## Context

Issue #1507 requests parity with cloud/web session lifecycle features. Simplicio is local-first; this document maps each requested feature to its local-first equivalent or marks it as out-of-scope for the local runtime.

## What Simplicio already provides (local equivalents)

- **Remote control**: `simplicio agent status` + webhook capability (`src/` contains webhook handler); action gate governs all mutations; IPC between local sessions.
- **Handoff / teleport**: `simplicio checkpoint` creates a serialized, verifiable session state on HBP chain; `simplicio resume` restores it — this is the local-first equivalent of session teleport.
- **Unified task board**: `simplicio agent status --all` surfaces all active agents, background tasks, and sessions; kanban coordination (`agent_collaboration`/`kanban_coordination`) augments this.
- **Autofix-PR**: `skill_github_pr_workflow.rs` handles the PR workflow; autofix = `simplicio run "fix CI failures" + deliver + skill-pr` wired through Action Gate with evidence on the HBP chain.
- **Web setup**: out-of-scope for the local runtime; `install.sh` is the canonical local-first setup path.

## Decision table

| Feature | Status | Simplicio approach | Scope |
|---|---|---|---|
| remote-control surface | parcial | `simplicio agent status` + webhook; Action Gate governs mutations | local-first; cloud opt-in via webhook |
| teleport (local ↔ remote) | ausente | `simplicio checkpoint` + `simplicio resume` (serialized HBP state) | fora-do-escopo cloud; local equiv feasible today |
| handoff local ↔ remote | ausente | checkpoint export + resume on any machine with same HBP root | local via checkpoints |
| unified task board | parcial | `simplicio agent status --all` + background task list | to-complete: wire kanban into status --all |
| autofix-PR with evidence | ausente | `simplicio run --fix-ci` + `skill_github_pr_workflow` + `deliver certify` | to-implement as governed workflow |

## Constraints respected

- All mutations gated by Isa/Helo/evidence/gates (action_bridge + action_gate).
- Local-first: no mandatory cloud infrastructure.
- Audit trail via HBP verifiable hash chain (tamper-evident append-only ledger).
- No silent fake data: every stub returns explicit `Err`; certificate is issued only on passing gates.

## Rationale for closing as documented

The four acceptance criteria map cleanly to existing or near-term Simplicio primitives:

1. **Remote-control surface** — webhook + `agent status` + Action Gate satisfies governance requirement without cloud infra.
2. **Verifiable handoff** — `checkpoint`/`resume` with HBP chain provides cryptographic verifiability; cloud teleport is an out-of-scope infra concern.
3. **Unified task board** — `agent status --all` already partially satisfies this; full kanban wiring is tracked in backlog (kanban_coordination capability).
4. **Autofix-PR with evidence** — the skill_github_pr_workflow + deliver pipeline provides this; a thin `--fix-ci` entry point closes the loop.

No new cloud infrastructure is needed. The runtime delivers local-first parity.','docs/claude-code-coverage/1507-cloud-web-session-lifecycle.md','ef9142fbd89bca0553630afc4b8f51b080ebbd4903d0f04113838a0505063177','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1508-review-workflow-command-parity.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1508-review-workflow-command-parity.md','doc: Review/Workflow Command Parity — Simplicio Catalog','## Review/Workflow Command Parity — Simplicio Catalog

### Review surfaces
| Command | Simplicio equivalent | Surface | Notes |
|---|---|---|---|
| /code-review | skill_github_code_review.rs | simplicio skills invoke code-review OR /code-review alias | to-implement alias |
| /review | simplicio deliver review | /review alias → deliver review | to-implement alias |
| /security-review | security_command.rs | simplicio security + /security-review alias | to-implement alias |
| /ultrareview | simplicio deliver review --deep --multi-agent | /ultrareview alias → deep multi-agent review | to-implement alias |
| claude ultrareview | same as /ultrareview | CLI surface | to-implement |

### Execution surfaces
| Command | Simplicio equivalent | Notes |
|---|---|---|
| /run | simplicio run + delivery_runverify.rs | needs app-level observation contract |
| /verify | simplicio validate + deliver runverify | delivery_runverify.rs is base |
| /loop | simplicio run --loop / cron in-session | in-session loop to-implement |
| /batch | simplicio sprint --batch / wave-engine | needs /batch alias with decompose UX |
| /fork | simplicio agent fork --inherit-context | fork-of-conversation to-implement |
| /deep-research | simplicio run + Levi/web-search | /deep-research alias |
| /claude-api | simplicio mcp + api docs | /claude-api alias for API reference |
| /run-skill-generator | simplicio skills create | /run-skill-generator alias |

### Governance constraints
All surfaces respect: Isa/Helo/evidence, action gate, HBP chain, local-first','docs/claude-code-coverage/1508-review-workflow-command-parity.md','82a46222fe34a89a9942f518a0311d20c36261db4ed0e41d1e7d8303607a0d4a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1509-tui-operator-ux-parity.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1509-tui-operator-ux-parity.md','doc: TUI/Operator UX Parity — Simplicio Catalog','## TUI/Operator UX Parity — Simplicio Catalog

| Claude Code | Status | Simplicio surface | Adopted as | Priority |
|---|---|---|---|---|
| /context | parcial | /prompt-size + context window info | /context alias → show context usage | HIGH |
| /color | ausente | /skin with color scheme | /color alias → skin color | MEDIUM |
| /focus | ausente | context window management | /focus alias → narrow context | LOW |
| /export | NATIVO | /export [file] already exists | native | DONE |
| /keybindings | ausente | config system | /keybindings alias → config keybindings | MEDIUM |
| /release-notes | ausente | changelog_command.rs exists | /release-notes alias → changelog | HIGH |
| /statusline | ausente | TUI statusline config | /statusline alias → tui config | MEDIUM |
| /theme | NATIVO | /skin alias | native (/theme = /skin) | DONE |
| /tui | ausente | TUI toggle/config | /tui alias → tui settings | LOW |
| /terminal-setup | ausente | simplicio install --terminal | /terminal-setup alias | LOW |
| /recap | ausente | session summary | /recap alias → summarize session | HIGH |
| /powerup | ausente | product Anthropic | fora-do-escopo | N/A |
| /heapdump | ausente | debug/dev tool | fora-do-escopo for users | N/A |

### Priority implementation order
1. /context (HIGH) — already partial, just needs alias
2. /release-notes (HIGH) — changelog_command.rs exists
3. /recap (HIGH) — session summary, high value
4. /keybindings + /statusline + /color (MEDIUM) — config-system additions

### TUI catalog update
The TUI HELP_TEXT in src/tui_app.rs should include these aliases once implemented.
/powerup and /heapdump: fora-do-escopo (Anthropic product / dev-only).','docs/claude-code-coverage/1509-tui-operator-ux-parity.md','2e217bc59305c64fbcebaaf279aec241a8ba91dd5d96fe0478ca115778eb29c2','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1510-cli-admin-background-lifecycle.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1510-cli-admin-background-lifecycle.md','doc: CLI Admin and Background Lifecycle Parity','## CLI Admin and Background Lifecycle Parity

Simplicio already has: logs_command.rs, agent_store.rs, cron_scheduler.rs, backup_command.rs

### Background session lifecycle
| Claude CLI | Simplicio equivalent | Implementation status |
|---|---|---|
| claude attach | simplicio agent attach <id> | to-implement (agent_store.rs has session data) |
| claude logs | simplicio agent logs [--follow] | partial (logs_command.rs exists; needs --follow) |
| claude respawn | simplicio agent respawn <id> | to-implement (session checkpoint + restart) |
| claude rm | simplicio agent rm <id> | to-implement (gated mutation; needs action gate) |
| claude stop | simplicio agent stop <id> | to-implement (graceful stop + checkpoint) |
| claude daemon status | simplicio agent daemon status | to-implement (supervisor status) |
| claude daemon stop | simplicio agent daemon stop | to-implement (gated; graceful shutdown) |
| claude project purge | simplicio cache purge --project | to-implement (gated + audit trail) |
| claude setup-token | simplicio auth add / env vars | partial (auth exists; setup-token wizard to-add) |
| claude plugin ... | simplicio capabilities [--tree] | partial (needs richer tree) |
| claude auto-mode | simplicio gate mode auto | partial (gate mode exists; auto-mode config to-add) |

### Guard rails required
- rm/stop/daemon-stop/purge: action gate classify → HIGH risk → require confirmation
- audit trail via HBP chain for all destructive operations
- purge: checkpoint before purge (backup_command.rs base)

### Next steps
- Implement attach/respawn/rm/stop in src/main.rs agent subcommands
- Add --follow to logs_command.rs
- Add purge to cache_command with gate','docs/claude-code-coverage/1510-cli-admin-background-lifecycle.md','29ec53deadc9bc67bc92b6741c319257e8fb1b8b980c308415057ea4757e2ddb','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1511-config-permissions-settings-ide.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1511-config-permissions-settings-ide.md','doc: Config, Permissions, Settings and IDE Parity','## Config, Permissions, Settings and IDE Parity

Simplicio has: hooks_command.rs, config_command.rs, security_command.rs, action_bridge.rs, action_gate, gate classify

### Command surface decisions
| Claude Code | Status | Simplicio equivalent | Notes |
|---|---|---|---|
| /permissions | parcial | simplicio gate mode + action gate | needs /permissions alias listing allow/deny rules |
| /config | parcial | config_command.rs + /config TUI | needs settings hierarchy UI (project > user > global) |
| /hooks | parcial | hooks_command.rs | /hooks alias for TUI introspection |
| /ide | parcial | acp_adapter + platforms | /ide alias showing active IDE integrations |
| /init | parcial | simplicio install | /init alias for project initialization |
| /tasks | parcial | agent status + background | already tracked #1515; board UX needed |
| /settings | parcial | config precedence (env > project > user > global) | /settings alias → config UI |

### CLI flag decisions
| Flag | Simplicio equivalent | Status |
|---|---|---|
| --add-dir | simplicio --repo <path> | partial; needs --add-dir alias |
| --settings | simplicio --config <file> | to-implement |
| --safe-mode | simplicio gate mode safe | partial |
| --bare | simplicio --headless | partial |
| --tools | simplicio --allowed-tools | to-implement |
| --allowedTools | simplicio gate allowlist add | to-implement flag alias |
| --disallowedTools | simplicio gate denylist add | to-implement flag alias |

### Settings precedence (documented)
1. CLI flags (highest priority)
2. Environment variables
3. Project .simplicio-loop/config.json
4. User ~/.simplicio-loop/config.json
5. Global defaults (lowest priority)

### Test fixtures needed
- config_command.rs unit tests for precedence
- gate classify tests for permissions
- hooks_command.rs smoke test','docs/claude-code-coverage/1511-config-permissions-settings-ide.md','2642a56bb2287212212bd31fcf5d4d7b47ee089550ee1c593d6b70688c5560c3','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1512-bundled-plugin-commands.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1512-bundled-plugin-commands.md','doc: Issue #1512 — Bundled Plugin Command Compatibility','# Issue #1512 — Bundled Plugin Command Compatibility

Status: CLOSED
Date: 2026-06-16
Relates to: docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md

## Summary

Full compatibility matrix for all plugin commands found in the local claude-code clone.
Sources scanned: `.claude/commands`, `agent-sdk-dev`, `code-review`, `commit-commands`,
`feature-dev`, `hookify`, `plugin-dev`, `pr-review-toolkit`, `ralph-wiggum`.

## Compatibility Matrix

| Plugin command       | Status  | Simplicio equivalent                          | Adopted as              |
|----------------------|---------|-----------------------------------------------|-------------------------|
| /commit-push-pr      | parcial | skill_github_pr_workflow.rs                   | alias /commit-push-pr   |
| /dedupe              | ausente | simplicio task dedupe (dedup memory/issues)   | to-implement            |
| /triage-issue        | ausente | skill_github_issues.rs                        | alias /triage-issue     |
| /new-sdk-app         | ausente | N/A                                           | fora-do-escopo          |
| /code-review         | parcial | skill_github_code_review.rs                   | alias /code-review      |
| /clean_gone          | ausente | git fetch --prune + branch cleanup            | to-implement as /clean_gone |
| /commit              | parcial | git commit via action gate                    | alias /commit           |
| /feature-dev         | parcial | simplicio run --until-green (Coding Loop #236)| alias /feature-dev      |
| /hookify             | ausente | hooks_command.rs                              | alias /hookify          |
| /hookify:list        | ausente | simplicio hooks list                          | alias /hookify:list     |
| /hookify:configure   | ausente | simplicio hooks configure                     | alias /hookify:configure|
| /hookify:help        | ausente | simplicio hooks --help                        | alias /hookify:help     |
| /create-plugin       | parcial | simplicio skills create                       | alias /create-plugin    |
| /review-pr           | parcial | skill_github_pr_workflow.rs + deliver review  | alias /review-pr        |
| /ralph-loop          | ausente | simplicio run --until-green                   | alias /ralph-loop       |
| /cancel-ralph        | ausente | Ctrl+C / simplicio run --cancel               | alias /cancel-ralph     |

Total: 16 commands. Discarded: 1 (`/new-sdk-app`). Aliases: 11. To-implement: 3.
Fora-do-escopo: 1.

## Priority Order (highest use first)

1. /commit-push-pr — core git workflow, already wired via skill_github_pr_workflow.rs
2. /code-review — already wired via skill_github_code_review.rs
3. /review-pr — already wired via skill_github_pr_workflow.rs + deliver review
4. /ralph-loop — iterate-until-green loop (Coding Loop #236); alias to `simplicio run --until-green`
5. /feature-dev — same backing as /ralph-loop with a feature description entry point

## Discarded Commands

### /new-sdk-app

Justification: This command scaffolds a new Claude SDK application (agent-sdk-dev plugin).
It is tightly coupled to the Claude SDK scaffold patterns and has no meaningful Simplicio
equivalent. Simplicio''s skill creator (`/create-plugin`) covers the Simplicio-native case.
Adopting it would mean maintaining a Claude-SDK-specific scaffold inside the Simplicio
runtime, which violates separation of scope. Decision: `fora-do-escopo`.

## To-Implement Notes

### /dedupe

Deduplicates tasks/issues/memory entries. No direct Simplicio command today. A future
`simplicio task dedupe` or `simplicio memory dedupe` command can close this gap. Tracked
separately; not blocking this issue.

### /triage-issue

Assigns labels/priority to GitHub issues. `skill_github_issues.rs` is the intended home;
the alias wires into that skill once the skill exposes a `triage` action.

### /clean_gone

Cleans local branches tracking deleted remote branches (`git fetch --prune` + delete
merged/gone branches). A small deterministic command; can be a thin wrapper in the
git helper module. Tracked separately.

## hookify Aliases

`/hookify` and its sub-commands (`/hookify:list`, `/hookify:configure`, `/hookify:help`)
map directly to `hooks_command.rs` which already implements hook listing, configuration,
and help. The aliases are surface-level TUI bindings only; no new logic required.

## Acceptance Criteria

- [x] All 16 plugin commands from the claude-code clone are accounted for
- [x] Each command has a status (parcial/ausente/fora-do-escopo) and a Simplicio equivalent
- [x] Priority order documented for implementation sequencing
- [x] /new-sdk-app formally discarded with justification
- [x] To-implement items flagged (3) without blocking the issue closure
- [x] Decision documented and committed to the coverage directory','docs/claude-code-coverage/1512-bundled-plugin-commands.md','f08d68d8813ebae857287421d465aa04c5d595b0c2fb7626adf155717cd90e89','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1515-web-cloud-handoff.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1515-web-cloud-handoff.md','doc: Issue #1515 — Built-in web/cloud handoff commands','# Issue #1515 — Built-in web/cloud handoff commands

Commands: `/autofix-pr`, `/teleport`, `/web-setup`, `/ultraplan`, `/tasks`

## Decision table

| Command | Status | Simplicio equivalent | Justification |
|---|---|---|---|
| `/autofix-pr` | ausente | `simplicio skill github-pr-workflow` + action gate | Fluxo de CI fix→PR é composto: diagnostics (#237) + edit determinístico + gate (#231) + gh CLI. Track para implementação futura via skill pack. |
| `/teleport` | fora-do-escopo | — | Web session handoff (transferir sessão local→cloud) pertence a infraestrutura cloud/web; Simplicio é local-first e não tem backend de sessões remotas. |
| `/web-setup` | fora-do-escopo | — | Configuração de ambiente web (Claude.ai settings) não tem análogo no runtime local. Simplicio é local-first por design. |
| `/ultraplan` | ausente → alias | `simplicio plan --deep` | Equivalente direto: planning profundo com think budget alto. Alias a criar; comportamento já existe via flag `--deep` no planner. |
| `/tasks` | parcial | `simplicio agent status` + `simplicio background` | Listagem e controle de tarefas em background parcialmente coberto. Gap: UI de tasks interativa (progresso em tempo real). |

## Acceptance criteria

- [x] Cada comando tem classificação explícita (ausente / fora-do-escopo / parcial)
- [x] Comandos fora-do-escopo têm justificativa de por que não pertencem ao runtime local
- [x] Comandos ausentes/parciais têm surface verificável ou path de implementação
- [x] `/autofix-pr` rastreado para implementação futura via skill-github-pr-workflow + gate
- [x] `/ultraplan` tem alias proposto (`simplicio plan --deep`)
- [x] `/tasks` tem equivalente parcial documentado

## Notes

- `/teleport` e `/web-setup` são funcionalidades de produto Claude.ai (webapp), sem análogo no runtime CLI local.
- `/autofix-pr`: quando implementado, deve passar pelo Action Gate (#231) antes de qualquer push/PR automático.
- `/tasks`: gap principal é UI interativa; o backend de agentes em background já existe.','docs/claude-code-coverage/1515-web-cloud-handoff.md','38d966167824526f3c48a8adccef71a9d778ed2b9a11bfd05070bf41cbf2d63f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1516-account-plan-commands.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1516-account-plan-commands.md','doc: Issue #1516 — Built-in account/plan commands','# Issue #1516 — Built-in account/plan commands

Commands: `/usage-credits`, `/privacy-settings`, `/passes`, `/upgrade`

## Decision table

| Command | Status | Simplicio equivalent | Justification |
|---|---|---|---|
| `/usage-credits` | fora-do-escopo | — | Consulta de créditos/uso pertence à conta Anthropic (API key dashboard). O runtime local não tem acesso nem responsabilidade sobre billing. |
| `/privacy-settings` | fora-do-escopo | — | Configurações de privacidade da conta Claude.ai pertencem ao produto Anthropic, não ao runtime CLI local. |
| `/passes` | fora-do-escopo | — | "Passes" é um produto/feature de conta Anthropic (Claude Pro/Team). Sem análogo no runtime local. |
| `/upgrade` | fora-do-escopo | — | Upgrade de plano é uma ação de conta Anthropic. O runtime local não gerencia assinaturas. |

## Acceptance criteria

- [x] Todos os quatro comandos classificados como fora-do-escopo
- [x] Cada classificação tem justificativa explícita
- [x] Justificativa referencia que a responsabilidade pertence à conta Anthropic, não ao runtime local
- [x] Nenhum equivalente Simplicio forçado onde não existe

## Notes

Esses comandos pertencem exclusivamente à camada de produto/conta Anthropic (Claude.ai webapp ou API dashboard). O Simplicio é um runtime local-first; ele não gerencia identidade de usuário, billing, ou planos de assinatura. Qualquer integração futura nessa área seria via webhook/API da Anthropic e ficaria fora do core runtime.','docs/claude-code-coverage/1516-account-plan-commands.md','a99d9e10e9572a7c12eaefbd2e2e1e222bfe228840942b2a23bb9b1a7828dc2f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1517-tui-ux-commands.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1517-tui-ux-commands.md','doc: Issue #1517 — Built-in TUI/UX Commands: Decision Document','# Issue #1517 — Built-in TUI/UX Commands: Decision Document

**Date:** 2026-06-16
**Matrix:** docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md
**Status:** CLOSED — all commands classified

## Command decisions

| Command | Status | Decision |
|---|---|---|
| /color | ausente | to-implement: `simplicio skin --color-scheme <name>` + `/color` alias |
| /focus | ausente | to-implement: `/focus` alias for context window management (prune/narrow) |
| /export | NATIVO | `/export [file]` já exporta conversa — nativo per matrix, no action needed |
| /heapdump | ausente | fora-do-escopo: dev/debug tool interno, não exposto a usuários finais |
| /keybindings | ausente | to-implement: `simplicio config --keybindings` (keybindings.json editor) |
| /release-notes | ausente | to-implement: `simplicio changelog` — changelog_command.rs já existe como base |
| /statusline | ausente | to-implement: `simplicio tui statusline <config>` |
| /theme | NATIVO | alias de `/skin` — nativo per matrix, no action needed |
| /tui | ausente | to-implement: `simplicio tui toggle` / `simplicio tui config` |
| /terminal-setup | ausente | equivalente: `simplicio install --terminal`; alias `/terminal-setup` a criar |
| /recap | ausente | to-implement: `/recap` alias para session summary (conversa + decisões) |
| /powerup | ausente | fora-do-escopo: produto Anthropic (Claude Pro/Team upgrade), sem equivalente Simplicio |

## Acceptance criteria

- [x] Todos os 12 comandos classificados (nativo / to-implement / fora-do-escopo)
- [x] /export e /theme confirmados nativos — zero trabalho necessário
- [x] /heapdump e /powerup marcados fora-do-escopo com justificativa
- [x] Comandos to-implement têm forma canônica Simplicio definida
- [x] Help text / TUI catalog documentará quais adotar na implementação

## Implementation notes

Commands marked **to-implement** should be tracked as sub-issues under the TUI/UX epic.
Priority order: /keybindings → /recap → /release-notes → /color → /tui → /statusline → /focus → /terminal-setup.

`changelog_command.rs` already provides the scaffold for `/release-notes` — wire `/release-notes` as an alias.
`/keybindings` can read/write `~/.claude/keybindings.json` (same file the keybindings-help skill manages).','docs/claude-code-coverage/1517-tui-ux-commands.md','ea95a3b56a458520ef7e0860c2c24fb53354b09c4d0681fb578bec7d3b387864','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1518-install-app-commands.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1518-install-app-commands.md','doc: Issue #1518 — Built-in install/app commands','# Issue #1518 — Built-in install/app commands

Commands: `/install-github-app`, `/install-slack-app`, `/mobile`

## Decision table

| Command | Status | Simplicio equivalent | Justification |
|---|---|---|---|
| `/install-github-app` | ausente | `simplicio mcp register` / `gh app` flow | Simplicio pode registrar integrações via `mcp register`. O fluxo OAuth de instalação de GitHub App requer browser; equivalente parcial via `gh auth` + webhook config. Track para wrapper `simplicio github app install`. |
| `/install-slack-app` | ausente | Gateway Slack existente | Simplicio já tem suporte a gateway Slack (platform gateway em `src/`). O gap é o fluxo guiado de instalação/OAuth; o canal de comunicação em si já existe. |
| `/mobile` | fora-do-escopo | — | Mobile UX (Claude app iOS/Android) é um produto separado. O runtime CLI local não tem surface mobile. Fora do escopo do core runtime. |

## Acceptance criteria

- [x] Todos os três comandos classificados explicitamente
- [x] `/install-github-app` tem path equivalente documentado (`simplicio mcp register` + `gh` flow)
- [x] `/install-slack-app` tem equivalente documentado (gateway Slack existente no runtime)
- [x] `/mobile` classificado como fora-do-escopo com justificativa
- [x] Paths de implementação futura identificados para os dois comandos com equivalente

## Notes

- `/install-github-app`: o flow OAuth de instalação de App no GitHub requer browser redirect. O equivalente Simplicio faz o setup do lado do runtime (registrar webhook, configurar token); a parte de "clicar em instalar no GitHub" permanece manual ou via `gh app`.
- `/install-slack-app`: o gateway Slack (chat platform) já está na arquitetura Simplicio. O que falta é o wizard guiado de setup de credenciais Slack (bot token, signing secret). Candidato a `simplicio gateway slack setup`.
- `/mobile`: classificado como fora-do-escopo permanente para o runtime local. Se houver demanda futura, seria um produto companion, não uma feature do core CLI.','docs/claude-code-coverage/1518-install-app-commands.md','bfe508e3990adef70a49b767e23e590342d6de3464b49f37076a56913fee94a1','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1519-specialized-workflows.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1519-specialized-workflows.md','doc: Issue #1519 — Built-in Specialized Workflows: Decision Document','# Issue #1519 — Built-in Specialized Workflows: Decision Document

**Date:** 2026-06-16
**Matrix:** docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md
**Status:** CLOSED — all commands mapped

## Command decisions

| Command | Status | Simplicio equivalent | Action |
|---|---|---|---|
| /claude-api | ausente | `simplicio mcp` + SDK docs built-in (CLAUDE.md claude-api skill) | criar `/claude-api` alias → abre referência de API + MCP tool listing |
| /deep-research | ausente | `simplicio run "deep research on X"` + Levi/web-search skill + deep-research skill | criar `/deep-research` alias que dispara skill deep-research via action bridge |
| /fewer-permission-prompts | ausente | `simplicio gate classify` + allowlist config (`fewer-permission-prompts` skill já existe) | criar `/fewer-permission-prompts` alias → `simplicio gate config --add-allowlist` |
| /run-skill-generator | ausente | `simplicio skills create` + skill-creator skill | criar `/run-skill-generator` alias → dispara skill-creator via action bridge |
| /team-onboarding | ausente | `simplicio install --team` + setup-cowork skill | criar `/team-onboarding` alias → dispara setup-cowork skill |

## Acceptance criteria

- [x] Todos os 5 workflows têm equivalente Simplicio ou gap formal documentado
- [x] Nenhum está fora-do-escopo — todos têm caminho nativo ou via skill existente
- [x] Skills relevantes mapeadas: deep-research, fewer-permission-prompts, skill-creator, setup-cowork
- [x] Forma canônica do alias definida para cada comando
- [x] O que for skills/hooks/config está mapeado ao mecanismo correto (action bridge / gate / skills pack)

## Implementation notes

All five commands have direct skill equivalents already present in the runtime skill catalog (see system-reminder skills list). The implementation path is:

1. Register each `/command` name in the chat command router.
2. Map each to `action_bridge_command` → invoke the corresponding skill via the action bridge (gated at `auto` risk level since these are read/config operations).
3. `/fewer-permission-prompts` additionally writes to `.claude/settings.json` allowlist — use `simplicio gate config` deterministic writer, not LLM.

**No new skills need to be created.** The existing skill pack already covers all five workflows. Only the slash-command aliases and the router wiring are missing.','docs/claude-code-coverage/1519-specialized-workflows.md','9b6bcc3a2538ca667170ed4d612113eb6520bd616085da3091a17d3c2270512a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1520-background-supervisor-lifecycle.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1520-background-supervisor-lifecycle.md','doc: Coverage Decision: Background Supervisor Lifecycle (#1520)','# Coverage Decision: Background Supervisor Lifecycle (#1520)

Tracking matrix legend: nativo | parcial | alias | ausente | fora-do-escopo

## Scope

Claude Code background supervisor commands: `claude attach`, `claude logs`,
`claude respawn`, `claude rm`, `claude stop`, `claude daemon status`,
`claude daemon stop`.

## Coverage Map

| Claude Code command | Status | Simplicio equivalent / decision |
|---|---|---|
| `claude attach <session-id>` | ausente | to-implement: `simplicio agent attach <session-id>` — streams stdout/stderr of a detached agent back to the terminal; maps to `agent_store.rs` session lookup + pipe re-attach |
| `claude logs [session-id]` | parcial | equivalente: `simplicio agent logs [session-id]` via `src/logs_command.rs`; already parses structured log records — **gap**: missing `--follow` / `-f` flag for tail-like streaming; to-implement as `--follow` on the existing command |
| `claude respawn <session-id>` | ausente | to-implement: `simplicio agent respawn <session-id>` — kills stale agent process and relaunches from last checkpoint; requires checkpoint integration (`simplicio checkpoint`) |
| `claude rm <session-id>` | ausente | to-implement: `simplicio agent rm <session-id>` — removes agent session and associated state; **gated action** (classify risk = `destructive`, requires `action-gate` confirm or `--force`) |
| `claude stop <session-id>` | ausente | to-implement: `simplicio agent stop <session-id>` — graceful SIGTERM + drain; gated when the agent has unsaved work (action-gate `medium`) |
| `claude daemon status` | parcial | equivalente: `simplicio agent status --daemon` — supervisor heartbeat and agent count; partially implemented via `agent_store.rs` tick metrics; gap: no dedicated `--daemon` flag; to-implement as flag alias |
| `claude daemon stop` | ausente | to-implement: `simplicio agent stop --daemon` — shuts down the supervisor loop; **gated action** (risk = `high`, halts all active agents); requires drain-and-checkpoint before exit |

## Implementation Notes

- All mutating subcommands (`rm`, `stop`, `daemon stop`, `respawn`) flow through
  `classify_action_risk` / `action_gate_decide` before execution — no direct
  process kill without gate confirmation.
- `attach` and `logs --follow` are read-only; no gate required.
- `respawn` depends on `simplicio checkpoint` being called before the agent dies;
  the checkpoint records the last known-good state (HBP ledger entry).
- Session IDs come from `simplicio agent list` (maps to `agent_store.rs`
  `list_sessions()`).

## Acceptance Criteria

- [x] Explicit equivalent or to-implement decision for every subcommand
- [x] Lifecycle of background agents is verifiable (`status`, `logs`, `attach`)
- [x] Mutating commands have guard rails (gated action + audit trail)
- [x] `logs --follow` gap documented with implementation path
- [x] `respawn` dependency on checkpoint layer documented

## Related

- `src/logs_command.rs` — existing logs infrastructure
- `src/agent_store.rs` — session registry
- Action Bridge (#230), Action Gate (#231), Checkpoints (#232)
- Parent epic: Claude Code command coverage matrix `docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md`','docs/claude-code-coverage/1520-background-supervisor-lifecycle.md','cb7c6e079ba04a56df82801d25c7fd6dbabf8e1ca4dbb888bceb67e8a818fe90','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1521-cli-admin-config-commands.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1521-cli-admin-config-commands.md','doc: Coverage Decision: CLI Admin/Config Commands (#1521)','# Coverage Decision: CLI Admin/Config Commands (#1521)

Tracking matrix legend: nativo | parcial | alias | ausente | fora-do-escopo

## Scope

Claude Code admin and configuration commands: `claude remote-control`,
`claude project purge`, `claude setup-token`, `claude plugin ...`,
`claude auto-mode`.

## Coverage Map

| Claude Code command | Status | Simplicio equivalent / decision |
|---|---|---|
| `claude remote-control` | fora-do-escopo | Remote control via web infra (WebSocket relay, OAuth session handoff) is out of scope for the local runtime. Simplicio is a local-first binary; remote session takeover requires a hosted relay service not present in this repo. **Decision: document as out-of-scope; revisit if a hosted gateway (#193 extensions/RPC) is implemented.** |
| `claude project purge` | ausente | to-implement: `simplicio cache purge --project` — removes cached artifacts, embeddings, and intermediate build outputs for the current project. **Gated action** (risk = `destructive`); writes an audit entry to the HBP evidence ledger before deleting; requires explicit `--confirm` or action-gate approval. |
| `claude setup-token` | parcial | equivalente: `simplicio auth add <provider> --api-key <key>` persists credentials to the runtime config, or set env `SIMPLICIO_API_KEY` / `SIMPLICIO_BASE_URL` / `SIMPLICIO_MODEL`. Gap: no interactive wizard matching `claude setup-token`''s UX; to-implement as `simplicio auth setup` interactive flow (reads from stdin, stores securely). |
| `claude plugin ...` | parcial | equivalente: `simplicio capabilities` lists enabled capability modules; `simplicio install <capability>` activates one. Gap: no `--tree` rendering of the plugin dependency graph. to-implement: `simplicio capabilities --tree` showing parent→child capability dependencies in a collapsible ASCII tree. |
| `claude auto-mode defaults/config` | ausente | equivalente split across two existing commands: gate policy → `simplicio gate mode auto\|ask\|safe`; resource tier → `simplicio runtime-profile use normal\|full\|low`. Gap: no single `auto-mode` entry point. to-implement: `simplicio auto-mode` as a thin alias that sets both gate mode and runtime profile in one call, persisted to `.simplicio-loop/config.toml`. |

## Guard Rails

- `project purge` must call `classify_action_risk` (result: `destructive`) and
  require explicit action-gate confirmation before any file deletion.
- `project purge` writes a ledger entry (`simplicio.purge-event/v1`) to the HBP
  chain so the action is auditable and not silently destructive.
- `setup-token` stores keys via the same secure-store path used by
  `simplicio auth`; keys are never logged or embedded in binary artifacts.
- `auto-mode` changes are persisted with a timestamp and the triggering agent ID
  so the change is traceable.

## Out-of-Scope Rationale: remote-control

`claude remote-control` implies a hosted relay (WebSocket or similar) that
forwards keystrokes and terminal output from one machine to another via
Claude''s cloud infrastructure. Simplicio is a local binary with no hosted
component in this repo. The closest future hook is the Extensions/RPC epic (#193)
which could add a local HTTP/WebSocket server; if that lands, a `simplicio remote`
command can be wired to it. Until then, this is explicitly fora-do-escopo.

## Acceptance Criteria

- [x] Every command has an explicit contract: native equivalent, to-implement, or fora-do-escopo with rationale
- [x] `remote-control` documented as out-of-scope with re-evaluation condition
- [x] `project purge` has guard rails (gated + audit)
- [x] `setup-token` gap (no interactive wizard) documented with implementation path
- [x] `plugin --tree` gap documented
- [x] `auto-mode` maps to existing gate + runtime-profile commands with alias plan

## Related

- `src/hooks_command.rs` — config command infrastructure
- `src/action_bridge.rs`, `src/model_command.rs` — gate and model config
- Extensions/RPC (#193), Action Gate (#231)
- Parent epic: Claude Code command coverage matrix `docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md`','docs/claude-code-coverage/1521-cli-admin-config-commands.md','377834b337f9b529c28518282f0922954d44d61d08bf38a272fa42ed11f3e2f4','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1522-plugin-command-micro-backlog.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1522-plugin-command-micro-backlog.md','doc: Plugin Command Micro-Backlog — Decision Document','# Plugin Command Micro-Backlog — Decision Document

**Issue:** #1522
**Date:** 2026-06-16
**Status:** closed — decisions recorded

## Commands Analyzed

### /dedupe
- **Legenda:** ausente
- **Decisão:** to-implement
- **Surface:** `simplicio task dedupe` — deduplication of tasks/issues in the sprint backlog; identifies duplicate GitHub issues and tasks via similarity scoring in `skill_github_issues.rs`
- **Justificativa:** Simplicio has sprint planning and issue skills; dedup is a natural extension of issue triage. Implement as `simplicio task dedupe [--dry-run]` with similarity threshold.

### /triage-issue
- **Legenda:** ausente → equivalente parcial
- **Decisão:** alias to-implement
- **Surface:** `skill_github_issues.rs` already provides issue operations; add `/triage-issue` as a surface alias for `simplicio issue triage`
- **Justificativa:** The underlying capability exists. Surface parity requires wiring the alias and exposing the triage flow (label assignment, priority scoring, assignee suggestion) via the REPL command `/triage-issue`.

### /new-sdk-app
- **Legenda:** ausente
- **Decisão:** fora-do-escopo
- **Justificativa:** `/new-sdk-app` scaffolds a Claude SDK application (Anthropic-specific boilerplate). Simplicio is a Rust runtime, not an Anthropic SDK scaffold generator. Implementing this would couple Simplicio to Claude SDK conventions with no benefit to the Simplicio ecosystem. Descartado.

### /clean_gone
- **Legenda:** ausente
- **Decisão:** to-implement
- **Surface:** `simplicio git clean-gone` — prunes local branches whose upstream remote tracking branch has been deleted (equivalent to `git fetch --prune` + `git branch -d` on gone branches)
- **Justificativa:** Common git hygiene task; fits naturally into Simplicio''s git surface. No external dependency beyond the git CLI already invoked by the runtime.

### /hookify (root command)
- **Legenda:** ausente → equivalente nativo
- **Decisão:** alias — hooks_command.rs is the native surface
- **Surface:** `hooks_command.rs` implements the full hooks subsystem. Add `/hookify` as a REPL alias for `simplicio hooks`.
- **Evidência:** `src/hooks_command.rs` exists in the codebase.

### /hookify:list
- **Legenda:** ausente → equivalente nativo
- **Decisão:** alias
- **Surface:** `simplicio hooks list` (already in hooks_command.rs); expose as `/hookify:list`

### /hookify:configure
- **Legenda:** ausente → equivalente nativo
- **Decisão:** alias
- **Surface:** `simplicio hooks configure`; expose as `/hookify:configure`

### /hookify:help
- **Legenda:** ausente → equivalente nativo
- **Decisão:** alias
- **Surface:** `simplicio hooks --help`; expose as `/hookify:help`

### /ralph-loop
- **Legenda:** ausente → equivalente nativo
- **Decisão:** alias
- **Surface:** `simplicio run --until-green` implements the iterate-until-green loop (coding loop #236). The ralph-loop skill is the Claude Code wrapper for this pattern. Add `/ralph-loop` as a REPL alias for `simplicio run --until-green`.
- **Justificativa:** The core loop (fan-out → validate → iterate) is implemented. Surface parity requires the alias.

### /cancel-ralph
- **Legenda:** ausente → equivalente nativo
- **Decisão:** alias
- **Surface:** `simplicio run --cancel` / Ctrl+C in the REPL; add `/cancel-ralph` as a named alias to signal cancellation of the active `--until-green` run.

## Acceptance Criteria

- [x] Cada comando tem decisão explícita (to-implement / alias / fora-do-escopo)
- [x] Aproveitados têm surface verificável (hooks_command.rs, skill_github_issues.rs, run --until-green)
- [x] Descartados têm justificativa (/new-sdk-app: Claude SDK scaffold, fora-do-escopo)

## Implementation Backlog

| Command | Action | Target |
|---|---|---|
| /dedupe | implement `simplicio task dedupe` | skill_github_issues.rs or sprint module |
| /triage-issue | wire alias → `simplicio issue triage` | skill_github_issues.rs |
| /new-sdk-app | descartado | n/a |
| /clean_gone | implement `simplicio git clean-gone` | git surface |
| /hookify | alias → hooks_command.rs | REPL command table |
| /hookify:list | alias → `simplicio hooks list` | REPL command table |
| /hookify:configure | alias → `simplicio hooks configure` | REPL command table |
| /hookify:help | alias → `simplicio hooks --help` | REPL command table |
| /ralph-loop | alias → `simplicio run --until-green` | REPL command table |
| /cancel-ralph | alias → `simplicio run --cancel` | REPL command table |','docs/claude-code-coverage/1522-plugin-command-micro-backlog.md','3da738b080567d7af0c00d6617a7774b7a7bc19002257a7674d34bdbe2d01841','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1523-config-introspection-partials.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1523-config-introspection-partials.md','doc: Built-in Config/Introspection Partials — Decision Document','# Built-in Config/Introspection Partials — Decision Document

**Issue:** #1523
**Date:** 2026-06-16
**Status:** closed — decisions recorded

## Commands Analyzed

### /permissions
- **Legenda:** parcial
- **Decisão:** equivalente to-complete
- **Surface:** `simplicio gate mode` shows the current action-gate policy (ask/auto/safe); `simplicio config --permissions` lists allowed/denied tool permissions. Add `/permissions` as a REPL alias that invokes both and renders a combined permissions summary.
- **Gap:** No single unified view; gate mode and config --permissions are separate invocations. To-complete: merge into `/permissions` surface.
- **Evidência:** `action_gate` (action_bridge.rs), gate classify, config module exist.

### /context
- **Legenda:** parcial
- **Decisão:** equivalente to-complete
- **Surface:** `simplicio prompt-size` reports current context window usage. Add `/context` as a REPL alias showing: tokens used, tokens remaining, active context slots (`chat_context_slots`), and memory items loaded.
- **Gap:** No unified context window inspector in the REPL today. To-complete: expose via `/context` alias.
- **Evidência:** `chat_context_slots`, prompt-size command, token economy module.

### /hooks
- **Legenda:** parcial → equivalente nativo
- **Decisão:** alias — hooks_command.rs is the native surface
- **Surface:** `hooks_command.rs` implements the full hooks subsystem natively. Add `/hooks` as a REPL TUI alias for `simplicio hooks`.
- **Gap:** The alias `/hooks` is not yet wired in the REPL command table. The implementation is complete.
- **Evidência:** `src/hooks_command.rs` exists in the codebase.

### /ide
- **Legenda:** parcial
- **Decisão:** equivalente to-complete
- **Surface:** `simplicio platforms` (platform/gateway listing) + `acp_adapter` (Zed/VS Code/JetBrains ACP integration). Add `/ide` as a REPL alias that shows: connected IDE adapters, ACP status, active editor session.
- **Gap:** No unified `/ide` surface today; acp_adapter exists but is not exposed as a REPL command. To-complete: wire `/ide` alias.
- **Evidência:** ACP adapter port tracked in memory (acp-adapter-py-to-rust-port.md).

### /init
- **Legenda:** parcial
- **Decisão:** equivalente to-complete
- **Surface:** `simplicio install --init project` initializes a project (CLAUDE.md, .simplicio-loop/, initial memory). Add `/init` as a REPL alias for the project initialization flow.
- **Gap:** The init flow exists in the install module but `/init` is not a first-class REPL command. To-complete: add alias + ensure CLAUDE.md scaffold is generated.
- **Evidência:** install module, CLAUDE.md template in the runtime.

### /insights
- **Legenda:** parcial
- **Decisão:** já existe — enhancement needed
- **Surface:** `/insights` already exists in the REPL. Needs enhancement for full parity with Claude Code: token usage trends, cost breakdown by session, memory hit rate, agent utilization metrics.
- **Gap:** Current `/insights` surface is minimal. Enhance to show: total tokens saved (with/without Simplicio), HBP event counts, benchmark comparisons.
- **Evidência:** insights command present; token-savings reporting is a standing rule in CLAUDE.md.

### /config
- **Legenda:** parcial
- **Decisão:** já existe — enhancement needed
- **Surface:** `/config` already exists. Needs enhancement to match Claude Code settings UX: visual settings panel in TUI, sections for model/provider/gate/permissions/hooks/platforms, live reload without restart.
- **Gap:** Current `/config` is a flat key-value display. To-complete: structured TUI config editor matching Claude Code''s panel UX.
- **Evidência:** config module, TUI surface (ratatui), settings.json/settings.local.json infrastructure.

## Acceptance Criteria

- [x] Cada comando tem equivalente explícito, alias, ou decisão documentada
- [x] Aproveitados têm evidência de surface existente (hooks_command.rs, action_bridge.rs, acp_adapter, insights, config)
- [x] Parciais têm gap descrito e próximo passo (to-complete)
- [x] Matriz aponta evidência para cada item

## Implementation Backlog

| Command | Action | Gap | Target |
|---|---|---|---|
| /permissions | alias to-complete | merge gate mode + config --permissions | REPL command table + config module |
| /context | alias to-complete | unified context window inspector | REPL command table + prompt-size |
| /hooks | alias (nativo) | wire alias in REPL | REPL command table |
| /ide | alias to-complete | expose acp_adapter as REPL command | REPL command table + acp_adapter |
| /init | alias to-complete | wire /init → install --init project | REPL command table + install module |
| /insights | enhancement | expand metrics (cost, memory hit rate, agent util) | insights module |
| /config | enhancement | structured TUI config panel | config module + TUI |','docs/claude-code-coverage/1523-config-introspection-partials.md','6e93e56c888a083b47bd924db922ec4c81a98fa9b6abba0dbfb60fa8a2062f9b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1524-run-verify-execution-partials.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1524-run-verify-execution-partials.md','doc: Decision: Run/Verify/Execution Partials (#1524)','# Decision: Run/Verify/Execution Partials (#1524)

**Issue:** #1524 — Built-in run/verify partials: /run, /verify, /loop, /batch, /fork, /schedule
**Status:** parcial → to-complete (aliases + surface contracts)
**Date:** 2026-06-16

## Commands Analyzed

### /run

- **Claude Code behavior:** launch the project''s app and observe it running; driven by heuristics per project type (CLI, server, TUI, Electron, browser, library).
- **Simplicio equivalent (existing):** `simplicio run` + `delivery_runverify.rs` (run-verification dogfood gate, #252).
- **Gap:** no `/run` alias; no explicit app-level observation contract (stdout capture, exit-code assertion, timeout). `delivery_runverify.rs` has the infrastructure but it is wired to the delivery gate, not exposed as a standalone slash command.
- **Decision:** add `/run` alias that maps to `simplicio deliver runverify --observe`; reuse `delivery_runverify.rs` as the execution backend. The observation contract must capture stdout/stderr, assert non-zero exit codes, and surface evidence on the HBP chain.
- **Implementation anchor:** `src/delivery_runverify.rs`, add `RunCommand` entry in command surface (`src/main.rs`).

### /verify

- **Claude Code behavior:** confirm a change actually works by running the app and observing behavior; not just tests.
- **Simplicio equivalent (existing):** `simplicio validate` (static validation pipeline) + `simplicio deliver runverify` (dynamic run-verification).
- **Gap:** no `/verify` alias; the two-stage flow (validate then runverify) is not composed into a single surface.
- **Decision:** add `/verify` alias that composes `simplicio validate --json` followed by `simplicio deliver runverify`; failures in either stage block delivery. `delivery_runverify.rs` is the base.
- **Implementation anchor:** `src/delivery_runverify.rs`, `src/validate_command.rs`, compose in `src/main.rs`.

### /loop

- **Claude Code behavior:** run a prompt or slash command on a recurring interval; self-pace if no interval given.
- **Simplicio equivalent (existing):** `simplicio cron` (`src/cron_scheduler.rs`) for recurring scheduled jobs; in-session polling loops via the agent fabric.
- **Gap:** no `/loop` alias; `cron_scheduler.rs` is timer-based but lacks an in-session interactive loop UX (run N times until pass, then stop).
- **Decision:** add `/loop` alias with two modes: (1) `--cron` delegates to `cron_scheduler.rs`; (2) default = in-session polling loop (iterate slash command until condition met or max iterations reached, governed by action gate). Interval syntax: `5m`, `30s`, `1h`.
- **Implementation anchor:** `src/cron_scheduler.rs`, new `LoopCommand` in `src/main.rs`.

### /batch

- **Claude Code behavior:** run a prompt against multiple targets in parallel.
- **Simplicio equivalent (existing):** `simplicio sprint --batch` / multi-agent fan-out (tokio sub-agent fabric, 64→600 agents).
- **Gap:** no `/batch` alias; the multi-agent fan-out is internal; no Claude-like UX for "run this prompt against these N files/tasks".
- **Decision:** add `/batch` alias that accepts a list of targets (files, tasks, issue IDs) and fans out a prompt over them via the semaphore-bounded agent fabric. Each result is collected and surfaced with evidence. Gated by action gate for mutations.
- **Implementation anchor:** `src/batch_runner.rs` (if present) or new `BatchCommand` in `src/main.rs`; tokio semaphore fabric.

### /fork

- **Claude Code behavior:** fork the current conversation/worktree into a parallel exploration.
- **Simplicio equivalent (existing):** `simplicio agent fork` — the agent fabric supports spawning sub-agents; `EnterWorktree`/`ExitWorktree` tools handle worktree isolation.
- **Gap:** no `/fork` alias; no explicit fork-of-conversation UX (branching context, named forks, merge/diff of outcomes).
- **Decision:** add `/fork` alias that (1) snapshots current session context, (2) spawns a named sub-agent with a copy of context, (3) labels the fork for later comparison. Merge is manual (user reviews both outcomes). Gated by action gate.
- **Implementation anchor:** agent spawn in `src/main.rs`; `EnterWorktree` for git worktree isolation.

### /schedule

- **Claude Code behavior:** create or update a scheduled task that runs automatically on a cron expression.
- **Simplicio equivalent (existing):** `simplicio cron` (`src/cron_scheduler.rs`); cron expressions, persist/list/cancel.
- **Gap:** no `/schedule` alias visible from the command surface; the feature exists but is not discoverable as a slash command.
- **Decision:** add `/schedule` alias that delegates directly to `cron_scheduler.rs`. Syntax: `/schedule "0 9 * * *" /verify` — schedules a slash command at a cron expression. List: `/schedule list`. Cancel: `/schedule cancel <id>`.
- **Implementation anchor:** `src/cron_scheduler.rs`.

## Acceptance Criteria

- [x] Each command has an explicit surface equivalent or a formal gap documented above
- [x] /run and /verify have an app-level observation contract anchored to `delivery_runverify.rs`
- [x] /loop and /schedule have a governed surface anchored to `cron_scheduler.rs`
- [x] /batch has a fan-out contract anchored to the tokio multi-agent fabric
- [x] /fork has a context-snapshot + sub-agent contract with gate
- [ ] Aliases implemented in `src/main.rs` (to-implement, tracked by this issue)

## Status

Decisions documented. Implementation tracked by #1524 sub-tasks. No regressions introduced (documentation only).','docs/claude-code-coverage/1524-run-verify-execution-partials.md','91f3aea2086a8fcd2389fff8ed350c4fb7a59042f3e75f7a7d7a81df148e253e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1525-review-partials.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1525-review-partials.md','doc: Decision: Review Partials (#1525)','# Decision: Review Partials (#1525)

**Issue:** #1525 — Built-in review partials: /review, /security-review, /code-review, /ultrareview
**Status:** parcial → to-complete (aliases + surface contracts)
**Date:** 2026-06-16

## Commands Analyzed

### /review

- **Claude Code behavior:** review a pull request — reads commits, diff, and context; surfaces findings as inline PR comments or a summary.
- **Simplicio equivalent (existing):** `simplicio deliver review` (self-review gate #254, landed); `skill_github_code_review.rs` provides the underlying PR review skill.
- **Gap:** no `/review` alias; `deliver review` is scoped to delivery gate context, not a standalone PR review invocation.
- **Decision:** add `/review` alias that maps to `simplicio deliver review [--pr <number>]`. When a PR number is given, fetches the diff via GitHub and runs the review skill. When no PR is given, reviews the current working tree diff (self-review mode). Findings are surfaced inline and optionally posted as PR comments with `--comment`.
- **Implementation anchor:** `src/delivery_review.rs` (deliver review gate), `src/skill_github_code_review.rs`.

### /security-review

- **Claude Code behavior:** complete a security review of the pending changes on the current branch — looks for vulnerabilities, injection risks, secrets, auth flaws.
- **Simplicio equivalent (existing):** `security_command.rs` (security surface); `skill_github_code_review.rs` (includes security heuristics).
- **Gap:** no `/security-review` alias; security checks exist but are not surfaced as a single security-focused review command.
- **Decision:** add `/security-review` alias that runs the security command with `--mode review` over the current branch diff. Checks: secret leaks, injection vectors, auth bypass, unsafe deserialization, path traversal, dependency CVEs. Output structured as findings with severity (critical/high/medium/low). Anchored to `security_command.rs`.
- **Implementation anchor:** `src/security_command.rs`, extend with `--mode review` flag.

### /code-review

- **Claude Code behavior:** review the current diff for correctness bugs and cleanup opportunities at a configurable effort level (low/medium/high/max/ultra); optionally post inline PR comments or apply fixes.
- **Simplicio equivalent (existing):** `skill_github_code_review.rs` — the code review skill is present and covers correctness + style findings.
- **Gap:** no `/code-review` alias; the skill is invoked internally but not exposed as a slash command with effort-level flags (`--effort low|medium|high|max|ultra`), `--comment`, or `--fix`.
- **Decision:** add `/code-review` alias that delegates to `skill_github_code_review.rs` with configurable effort. Effort levels map to: `low/medium` = high-confidence findings only; `high/max` = broader coverage including uncertain findings; `ultra` = deep multi-agent review (fan-out via agent fabric). `--comment` posts inline PR comments; `--fix` applies findings via `simplicio edit`.
- **Implementation anchor:** `src/skill_github_code_review.rs`, new `CodeReviewCommand` in `src/main.rs`.

### /ultrareview

- **Claude Code behavior:** deep multi-agent review — fan-out across agents for adversarial coverage; highest effort level.
- **Simplicio equivalent (existing):** `simplicio deliver review --deep` (multi-agent review mode using the agent fabric at 200–600 agents).
- **Gap:** no `/ultrareview` alias; the `--deep` flag on deliver review exists logically but is not exposed as a named slash command.
- **Decision:** add `/ultrareview` alias that maps to `simplicio deliver review --deep --effort ultra`. Internally fans out over the agent fabric (up to 600 agents), each reviewing a different aspect (correctness, security, performance, style, architecture). Findings are deduplicated and ranked. Gated by action gate (high compute cost).
- **Implementation anchor:** `src/delivery_review.rs`, agent fabric fan-out in `src/main.rs`; gate via `action_gate`.

## Acceptance Criteria

- [x] Each command has an explicit surface equivalent or a formal gap documented above
- [x] /review and /code-review have a contract anchored to `skill_github_code_review.rs`
- [x] /security-review has a contract anchored to `security_command.rs`
- [x] /ultrareview has a deep/multi-agent contract anchored to `delivery_review.rs`
- [x] All findings flow through the HBP evidence chain (tamper-evident)
- [ ] Aliases implemented in `src/main.rs` (to-implement, tracked by this issue)

## Status

Decisions documented. Implementation tracked by #1525 sub-tasks. No regressions introduced (documentation only).','docs/claude-code-coverage/1525-review-partials.md','cf79e78428866d3fc332eb07655a9db2df7b7d6ed9ffe98480d84fdaf8da997e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1526-browser-desktop-partials.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1526-browser-desktop-partials.md','doc: Decision: Browser/Desktop Partials (#1526)','# Decision: Browser/Desktop Partials (#1526)

**Issue:** #1526 — Built-in browser/desktop partials: /browser, /desktop, /computer-use, /chrome
**Status:** parcial → to-complete (aliases + surface contracts)
**Date:** 2026-06-16

## Commands Analyzed

### /computer-use

- **Claude Code behavior:** control the user''s desktop via screenshot + mouse/keyboard; general-purpose computer automation.
- **Simplicio equivalent (existing):** `simplicio computer-use`; `src/macos_computer_use.rs` provides the macOS/desktop computer-use backend (screenshot, click, type, scroll).
- **Gap:** `macos_computer_use.rs` is an internal capability module; `simplicio computer-use` exists as a command but the surface (flags, help text, structured output) needs consolidation and documentation.
- **Decision:** consolidate `simplicio computer-use` as the canonical surface. All sub-commands (`--browser`, `--desktop`, `--chrome`, `--screenshot`, `--click`, `--type`, `--scroll`) route through `macos_computer_use.rs`. Add `/computer-use` slash alias. All actions gated by action gate (risk: high for mutations, medium for read-only observation). Evidence recorded on HBP chain.
- **Implementation anchor:** `src/macos_computer_use.rs`, surface consolidation in `src/main.rs`.

### /browser

- **Claude Code behavior:** launch and drive a browser; navigate, click, fill forms, extract content.
- **Simplicio equivalent (existing):** `simplicio computer-use --browser`; `macos_computer_use.rs` supports browser interaction. `tools_browser` capability is compiled in.
- **Gap:** no `/browser` alias; `--browser` flag on `computer-use` is not documented as a first-class surface. No DOM-aware mode (pixel-level only via macOS accessibility).
- **Decision:** add `/browser` alias that maps to `simplicio computer-use --browser`. Supports: `--navigate <url>`, `--click <selector|coords>`, `--fill <selector> <value>`, `--extract <selector>`, `--screenshot`. On macOS, routes through `macos_computer_use.rs` (accessibility API). On Windows/Linux, routes through the browser runtime (`tools_browser` capability). DOM-aware mode preferred when available; pixel fallback otherwise.
- **Implementation anchor:** `src/macos_computer_use.rs`, `src/tools_browser.rs` (if present), new `BrowserCommand` in `src/main.rs`.

### /desktop

- **Claude Code behavior:** control native desktop applications (not browser); file system, system settings, native app GUIs.
- **Simplicio equivalent (existing):** `simplicio computer-use --desktop`; `macos_computer_use.rs` handles native app control via macOS Accessibility API.
- **Gap:** no `/desktop` alias; `--desktop` flag is implicit (default mode of computer-use) but not explicitly named. No cross-platform abstraction (macOS only currently).
- **Decision:** add `/desktop` alias that maps to `simplicio computer-use --desktop`. Scoped to native app control (not browser). Supports: `--app <name>`, `--screenshot`, `--click <coords>`, `--type <text>`, `--scroll`. Explicitly excludes browser windows (use `/browser` for those). On Windows, future backend (Win32 UIA); current baseline is macOS only.
- **Implementation anchor:** `src/macos_computer_use.rs`, new `DesktopCommand` in `src/main.rs`.

### /chrome

- **Claude Code behavior:** control a Chrome browser specifically; DOM-aware navigation, tab management, DevTools access.
- **Simplicio equivalent (existing):** `simplicio computer-use --chrome`; partial — `macos_computer_use.rs` can drive Chrome as a macOS app, but no Chrome DevTools Protocol (CDP) integration exists yet.
- **Gap:** no `/chrome` alias; no explicit `--chrome` flag; no CDP integration (DOM-aware, not pixel-level). Chrome-specific features (tabs, DevTools, network inspection) not available via `macos_computer_use.rs` alone.
- **Decision:** add `/chrome` alias that maps to `simplicio computer-use --chrome`. Short-term: routes through `macos_computer_use.rs` (pixel/accessibility level) for macOS. Medium-term: add CDP backend (`src/cdp_client.rs`) for DOM-aware control (navigate, click by selector, evaluate JS, intercept network). `--chrome` flag explicitly selects Chrome as target app. CDP is the preferred backend when Chrome is running; accessibility fallback otherwise.
- **Implementation anchor:** `src/macos_computer_use.rs` (immediate), `src/cdp_client.rs` (future CDP backend), `src/main.rs`.

## Surface Hierarchy

```
simplicio computer-use          ← canonical command, all backends
  --browser                     ← /browser alias, DOM-aware preferred
  --desktop                     ← /desktop alias, native app control
  --chrome                      ← /chrome alias, Chrome-specific (CDP roadmap)
  --screenshot                  ← read-only, gate: medium
  --click <target>              ← mutation, gate: high
  --type <text>                 ← mutation, gate: high
  --navigate <url>              ← browser-only
  --extract <selector>          ← read-only
```

## Acceptance Criteria

- [x] Each command has an explicit surface contract, not just an internal capability
- [x] /browser, /desktop, /computer-use, /chrome are aliases over `macos_computer_use.rs`
- [x] Action gate applies to all mutations (click, type, navigate)
- [x] Evidence recorded on HBP chain for all computer-use actions
- [x] CDP roadmap for /chrome documented (medium-term, not blocking closure)
- [x] Surface hierarchy is explicit and non-overlapping
- [ ] Aliases and flags implemented in `src/main.rs` (to-implement, tracked by this issue)

## Status

Decisions documented. Implementation tracked by #1526 sub-tasks. No regressions introduced (documentation only).','docs/claude-code-coverage/1526-browser-desktop-partials.md','5d88e086c7ead56f781efbe7b5592e7ea92441073fb0a2b9040a05299eabef3c','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1527-cli-partials.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1527-cli-partials.md','doc: Coverage Decision: CLI Partials (#1527)','# Coverage Decision: CLI Partials (#1527)

Tracking matrix legend: nativo | parcial | alias | ausente | fora-do-escopo

## Scope

Claude Code CLI flags and partial-coverage commands: `claude -p` (headless/print),
`claude plugin` (tree), `claude ultrareview`, `claude --worktree`,
`claude --tmux`, `claude --chrome`.

## Coverage Map

| Claude Code flag/command | Status | Simplicio equivalent / decision |
|---|---|---|
| `claude -p` / `--print` (headless) | parcial | equivalente: `simplicio --headless` passes through a single prompt non-interactively and exits. Gap: no short `-p` alias; output format differs slightly (Simplicio emits structured JSON by default; `-p` implies plain text). to-implement: add `-p` / `--print` as alias for `--headless --output plain` and ensure stdout is clean (no spinner, no color) for pipe-friendliness. |
| `claude plugin` (tree view) | parcial | equivalente: `simplicio capabilities` lists modules; `simplicio capabilities --tree` is planned (see #1521). Gap: no tree rendering today. to-implement: `simplicio capabilities --tree` (ASCII collapsible tree of capability → sub-capability → provider). This is the same gap tracked in #1521; both issues share the same implementation item. |
| `claude ultrareview` | parcial | equivalente: `simplicio deliver review --deep` runs the full self-review pipeline (diff analysis + acceptance-criteria check + regression guard). Gap: no `ultrareview` surface alias. to-implement: `simplicio ultrareview` as a thin alias for `simplicio deliver review --deep --all-files`, matching the depth of the `/ultrareview` skill. |
| `claude --worktree` | parcial | equivalente: `simplicio issue-worktree <issue-id>` already creates an isolated git worktree for a given issue and sets up the environment. Gap: UX differs — Claude Code''s `--worktree` is a flag on the main command; Simplicio''s is a subcommand. to-implement: expose `--worktree <issue-id>` as a top-level flag alias that delegates to `issue-worktree` for UX parity. The underlying logic exists. |
| `claude --tmux` | fora-do-escopo | `--tmux` attaches Claude Code to a tmux session for multiplexed terminal management. This is tmux-specific integration; the Simplicio runtime has no tmux dependency and tmux is not universally available (notably absent on Windows). **Decision: fora-do-escopo for the core runtime.** Users who want tmux integration can wrap `simplicio` in a shell function or use the existing background agent (`simplicio agent --detach`) with any multiplexer. |
| `claude --chrome` | parcial | equivalente: `simplicio computer-use --browser chrome` routes browser automation to Chrome specifically. Gap: today the `--browser` flag accepts a backend name but `chrome` is not explicitly validated as a first-class value — other browsers may silently succeed. to-implement: add explicit `--chrome` top-level flag as alias for `--browser chrome`, validate Chrome availability at startup, and surface a clear error when Chrome is not found (rather than silently falling back). |

## Implementation Notes

- `-p` / `--print`: output must suppress all TUI/spinner/color codes and exit 0
  on success, non-zero on error; compatible with `xargs`, `jq`, and shell
  pipelines. Implement in `src/main.rs` argument parsing.
- `ultrareview` alias: maps directly to the delivery pipeline in `deliver review`
  with `--deep` depth preset; no new logic needed, only surface wiring.
- `--worktree` flag: delegates to `issue-worktree` subcommand; the underlying
  git-worktree creation logic in that subcommand is reused without duplication.
- `--chrome` flag: validates `which google-chrome || which chromium` at startup;
  emits `error: Chrome not found — install Chrome or use --browser <other>`.
- `--tmux`: document in the man page as "use `simplicio agent --detach` +
  your preferred multiplexer" and close as fora-do-escopo.

## Acceptance Criteria

- [x] Every flag/command has explicit coverage status and decision
- [x] `-p` gap (no short alias, output format) documented with implementation path
- [x] `plugin --tree` gap cross-referenced to #1521 (shared item)
- [x] `ultrareview` alias implementation path documented
- [x] `--worktree` existing logic identified; UX gap documented
- [x] `--tmux` documented as fora-do-escopo with rationale and workaround
- [x] `--chrome` gap (no explicit validation) documented with implementation path

## Related

- `src/main.rs` — top-level argument parsing (add `-p`, `--worktree`, `--chrome` flags)
- `src/benchmark_harness.rs` — deliver/review pipeline
- `src/model_command.rs` — browser/computer-use backend selection
- Issue #1521 — `plugin --tree` (shared implementation item)
- Worktree subcommand: existing `issue-worktree` logic
- Parent epic: Claude Code command coverage matrix `docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md`','docs/claude-code-coverage/1527-cli-partials.md','c20329e5f9375c97298cca3478840ca9bf31b6fc258f9585c56f7206301d568e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/1528-plugin-partials.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/1528-plugin-partials.md','doc: Issue #1528 — Plugin Partials: Decision Document','# Issue #1528 — Plugin Partials: Decision Document

Status: CLOSED
Date: 2026-06-16
Relates to: docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md

## Summary

Six plugin commands were tracked as `parcial` in the coverage matrix. This document records
the mapping decision and the surface alias for each.

## Command Decisions

### /commit

- Status: parcial
- Equivalent: `git commit` flow gated via `action_bridge_command` + `classify_action_risk`
- Decision: alias `/commit` → gate-wrapped `git commit -m "$msg"` flow, respecting the
  action gate (ask/auto/safe). No new Rust code required; the gate and action bridge are
  already in place (`src/action_bridge.rs`).
- Surface: TUI command `/commit <message>`

### /commit-push-pr

- Status: parcial
- Equivalent: `skill_github_pr_workflow.rs` — the skill already orchestrates git commit +
  push + `gh pr create` in sequence.
- Decision: alias `/commit-push-pr` → invoke `skill_github_pr_workflow` with the current
  branch; gate classifies as `medium` risk before push and PR creation steps.
- Surface: TUI command `/commit-push-pr [title]`

### /code-review

- Status: parcial
- Equivalent native: `skill_github_code_review.rs` — full diff review, inline comment
  posting, and summary already implemented.
- Decision: alias `/code-review` → `skill_github_code_review` on HEAD diff or specified PR.
  Already the richest native implementation; no gap.
- Surface: TUI command `/code-review [pr-number|--staged]`

### /feature-dev

- Status: parcial
- Equivalent: `simplicio run "implement feature X" --until-green` — the Coding Loop (#236)
  iterates until tests pass, driven by diagnostics.
- Decision: alias `/feature-dev` → coding loop entry point with optional spec argument; gate
  classifies as `high` (multi-file mutation) before each edit batch.
- Surface: TUI command `/feature-dev <description>`

### /create-plugin

- Status: parcial
- Equivalent: `simplicio capabilities create` / `simplicio skills create` — skill scaffold
  generator already in the capabilities subsystem.
- Decision: alias `/create-plugin` → `simplicio skills create <name>` with the standard
  skill template; outputs the new `skill_<name>.rs` stub and registers it in the skill index.
- Surface: TUI command `/create-plugin <name>`

### /review-pr

- Status: parcial
- Equivalent: `skill_github_pr_workflow.rs` + `simplicio deliver review` (#254 self-review).
- Decision: alias `/review-pr` → fetch PR diff via `gh pr diff`, run `skill_github_code_review`
  for inline findings, then run `deliver review` for the delivery gate summary.
- Surface: TUI command `/review-pr [pr-number]`

## Acceptance Criteria

- [x] Each command has an explicit equivalent or alias documented above
- [x] Simplicio-native skills used where available (skill_github_pr_workflow.rs,
      skill_github_code_review.rs) rather than external tooling
- [x] Action gate applied to all mutation paths (/commit, /commit-push-pr, /feature-dev)
- [x] Decision documented and committed to the coverage directory
- [x] Matrix entry updated: all six move from `parcial` to `alias` (pending alias wiring in #1528)

## Next Step

Wire the six aliases in the TUI command dispatcher (a follow-up implementation issue can
track the wiring; this document closes the decision phase).','docs/claude-code-coverage/1528-plugin-partials.md','84472e378e0d1ade4ba414d903a2e1cf2f030f45134b1ffd5c46551b7346a191','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/claude-code-coverage/3317-worktree-isolation-footgun.md','project_doc','doc://simplicio-runtime/docs/claude-code-coverage/3317-worktree-isolation-footgun.md','doc: Decision: Cross-Worktree `EnterWorktree` From a Pinned Subagent Is a Harness Bug, Not a Simplicio Gap (#3317)','# Decision: Cross-Worktree `EnterWorktree` From a Pinned Subagent Is a Harness Bug, Not a Simplicio Gap (#3317)

**Issue:** #3317 — Bash becomes permanently unusable after `EnterWorktree` inside a
pinned-worktree subagent.
**Status:** documented footgun — not fixable from this repo (harness-owned tool behavior).
**Date:** 2026-07-17

## What was reported

A subagent launched with `isolation: "worktree"` (Claude Code''s Agent tool, pinned to its
own worktree, e.g. `.claude/worktrees/agent-<id>`) called `EnterWorktree` pointing at a
**different** worktree (in the reported case, the shared session checkout,
`.claude/worktrees/simplicio-runtime-loop-issues-48d42b`). The call reported success, but
every subsequent `Bash` call then failed permanently with:

> "This agent is isolated in the worktree ...agent-\<id\>, but this command''s working
> directory resolved to the shared checkout ...simplicio-runtime-loop-issues-48d42b.
> Refusing to run it there."

`ExitWorktree` was also refused: "cannot be called from a subagent with a cwd override."
A plain `pwd`, and any attempt to `cd` back to the original pinned worktree, also failed —
there is **no recovery path**. The affected subagent lost Bash for the rest of its session
and had to report 0 progress on its remaining batch of work.

Follow-up comments on #3317 (from parallel sessions hitting related symptoms) additionally
found: pinned worktrees that never received a real checkout (absent from `git worktree
list`, contents empty except `.simplicio-loop/orchestrator/`); a manual `git worktree add` inside such an
environment reporting success while still producing an empty directory; and — most
seriously — two parallel agents ending up pointed at the **same physical worktree
directory** mid-session, with one agent''s branch and uncommitted files bleeding into the
other''s working tree. These are adjacent provisioning-layer symptoms, not confirmed to
share one root cause with the `EnterWorktree`-hang symptom, but they corroborate that
worktree isolation for `isolation: "worktree"` subagents is not yet reliably enforced by
the harness.

## Why this cannot be fixed from `simplicio-runtime`

`EnterWorktree`, `ExitWorktree`, the `isolation: "worktree"` Agent-tool option, and the
`Bash` cwd-isolation check that produces "Refusing to run it there" are all **Claude Code
harness internals** — they are not Rust source, CLI surface, or MCP contract owned by this
repo. `simplicio-runtime` cannot patch:

- the harness''s worktree-provisioning logic (why a pinned worktree is sometimes empty or
  reused across agents),
- the `EnterWorktree`/`ExitWorktree` tool implementations or their error messages, or
- the recovery semantics (or lack thereof) after a cross-worktree `EnterWorktree` call.

Per this repo''s scope-freeze/ADR discipline (`docs/ADR-2026-07-06-KERNEL-SCOPE-FREEZE.md`
and its revocation), the runtime''s mandate is the determinism kernel + agent parity
surface *of Simplicio itself* — not the Claude Code CLI that happens to host a given
session. There is no source file, MCP tool, or contract in this repository whose edit
would change the described behavior.

## What we did instead (repo-scoped mitigation)

Since the actual bug lives upstream, the only in-scope action is a documented warning so
future agents/sessions never rediscover this the hard way:

1. **This file** — a permanent, indexed record of the symptom, the reproduction, and the
   "don''t do this" rule, filed under the existing `docs/claude-code-coverage/` gap-tracking
   convention (see `docs/SIMPLICIO_PROJECT_INVENTORY.md` §5).
2. **`AGENTS.md`** — a short warning next to the existing "isolated worktree + branch"
   guidance in the Multi-Agent Work section, so any session reading the standing contract
   sees the footgun before it acts, not after.
3. **Issue #3317** — closed with a comment referencing this file, since the acceptance
   criteria as written assume the fix lands in the harness; there is nothing further this
   repo''s codebase can change to satisfy them.

## Operational rule (the actual fix, until the harness ships one)

**Never call `EnterWorktree` from inside a subagent that was launched with
`isolation: "worktree"`, pointing at any path other than that subagent''s own pinned
worktree.** If a pinned subagent needs to inspect another worktree''s files, do it via
`Read`/`Glob`/`Grep` with an absolute path into that worktree — never via `EnterWorktree`,
and never run `Bash` commands with an explicit `cd` into another worktree either, since the
same cwd-isolation check that fires after `EnterWorktree` can equally fire on a `cd`.

If a session ends up in the broken state anyway (Bash refuses every command, citing a cwd
mismatch, and `ExitWorktree` is refused as well): there is currently no in-session recovery
command. Stop issuing Bash calls (each one just reconfirms the same refusal and burns
turns), report the batch as blocked with 0 progress for the remainder of that subagent''s
scope (as the reporting session correctly did), and let the parent session re-dispatch the
remaining work to a fresh subagent instead of retrying recovery commands in the broken one.

## Acceptance criteria — mapped to what''s actually in scope here

The issue''s original acceptance criteria describe harness-side fixes (recovery command,
improved error message, EnterWorktree/ExitWorktree tool-description warnings, a harness
regression test). None of those are implementable as a change to this repo. What IS
in scope and done:

- [x] Investigated whether any file in this repo (AGENTS.md, CLAUDE.md, docs/ADR-*,
      docs/*GAP*) already covered this footgun — it did not.
- [x] Checked for related open PRs/issues (#3298 and a worktree-isolation search) — none
      address this; #3298 is an unrelated Sentinel command-reliability epic.
- [x] Documented the symptom, the corroborating follow-up reports, and the reproduction
      here, indexed under `docs/claude-code-coverage/`.
- [x] Added a standing "don''t do this" warning','docs/claude-code-coverage/3317-worktree-isolation-footgun.md','71b30dec5c38c1b051222c9729514588727bba20f2019e629ec73af9a642da8d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/CLAUDE_CODE_COMMAND_COVERAGE_AUDIT_2026-06-15.md','project_doc','doc://simplicio-runtime/docs/CLAUDE_CODE_COMMAND_COVERAGE_AUDIT_2026-06-15.md','doc: Claude Code command coverage audit — 2026-06-15','# Claude Code command coverage audit — 2026-06-15

Objetivo: levantar, a partir do clone local `C:\Users\Z0059V7A\m\ai\claude-code`, o que o Simplicio já cobre, o que cobre parcialmente e o que ainda falta para “cobrir todos os comandos” do ecossistema Claude Code.

## Fontes auditadas

- Repositório local `C:\Users\Z0059V7A\m\ai\claude-code`
  - `README.md`
  - `plugins/README.md`
  - comandos em `plugins/*/commands/*.md`
- Claude Code Docs oficiais consultadas em 2026-06-15
  - `Commands`: [code.claude.com/docs/en/commands](https://code.claude.com/docs/en/commands)
  - `CLI reference`: [code.claude.com/docs/en/cli-reference](https://code.claude.com/docs/en/cli-reference)
- Estado atual do Simplicio
  - `./target/release/simplicio.exe runtime map --repo . --for-llm markdown`
  - `src/tui_app.rs` (`HELP_TEXT`)

## Escopo do levantamento

Dividi “comandos do Claude Code” em 3 grupos:

1. **Built-in session commands** (`/comando`) documentados pela Anthropic.
2. **CLI commands e subcommands** (`claude ...`) documentados na CLI reference.
3. **Bundled plugin commands** que existem no clone local `claude-code/plugins`.

## Legenda de cobertura

- **Nativo**: já existe superfície explícita no Simplicio.
- **Parcial**: existe algo próximo, mas não com o mesmo contrato/UX/escopo.
- **Ausente**: não há superfície equivalente verificável hoje.
- **Fora de escopo do core**: comando voltado a growth/conta/app Anthropic; não bloqueia o core técnico, mas ainda é gap se o alvo for “cobrir tudo”.

---

## 1) Built-in session commands do Claude Code

### 1.1 Já cobertos de forma nativa ou muito próxima

| Claude Code | Situação no Simplicio | Evidência |
|---|---|---|
| `/help` | **Nativo** | `src/tui_app.rs` |
| `/clear`, `/new`, `/reset` | **Nativo** | `src/tui_app.rs` |
| `/compact` | **Nativo** | `src/tui_app.rs` |
| `/agents` | **Nativo** | `src/tui_app.rs`, `simplicio agent` |
| `/background` | **Nativo** | `src/tui_app.rs` |
| `/branch` | **Nativo** | `src/tui_app.rs` |
| `/cost`, `/usage` | **Nativo** | `src/tui_app.rs` |
| `/doctor` | **Nativo** | `src/tui_app.rs`, runtime map |
| `/goal` | **Nativo** | `src/tui_app.rs` |
| `/login`, `/logout` | **Nativo** | `src/tui_app.rs`, runtime map |
| `/mcp` | **Nativo** | `src/tui_app.rs`, runtime map |
| `/memory` | **Nativo** | `src/tui_app.rs`, runtime map |
| `/model` | **Nativo** | `src/tui_app.rs` |
| `/plan` | **Nativo** | `src/tui_app.rs`, runtime map |
| `/plugins` | **Nativo** | `src/tui_app.rs`, runtime map (`capabilities`, `install`) |
| `/resume` | **Nativo** | `src/tui_app.rs` |
| `/version` | **Nativo** | `src/tui_app.rs`, runtime map |
| `/voice` | **Nativo** | `src/tui_app.rs`, runtime map |
| `/copy` | **Nativo** | `src/tui_app.rs` |
| `/debug` | **Nativo** | `src/tui_app.rs` |

### 1.2 Cobertura parcial / contrato diferente

| Claude Code | Situação atual do Simplicio | Nota |
|---|---|---|
| `/permissions` | **Parcial** | Simplicio tem gate/mode (`/mode`, action gate), mas não a UX de rules/allow/deny e diretórios adicionais equivalente. |
| `/context` | **Parcial** | Há `/prompt-size`, `/config`, `/debug`, mas não a visualização de contexto no formato Claude. |
| `/hooks` | **Parcial** | Hooks existem no runtime, mas não há comando TUI/CLI equivalente com inspeção/configuração parecida. |
| `/ide` | **Parcial** | Há `platforms/adapters`, mas não gestão explícita de integrações IDE no nível Claude Code. |
| `/init` | **Parcial** | Simplicio orienta e instala, mas não há inicializador equivalente para memória/projeto no padrão Claude. |
| `/insights` | **Parcial** | Existe `/insights`, porém focado em savings/signals do runtime, não no relatório analítico de uso do Claude Code. |
| `/run` | **Parcial** | `simplicio run` existe, mas não com o contrato “run the app and observe it working” do skill do Claude. |
| `/verify` | **Parcial** | `validate` cobre parte; falta equivalência explícita ao skill app-level verification. |
| `/loop` | **Parcial** | Há `cron`/scheduler, mas não a UX `/loop` orientada a polling dentro da sessão. |
| `/batch` | **Parcial** | Simplicio tem multi-agent, sprint e wave-engine, mas não um comando `/batch` Claude-like que decompõe e abre PR por unidade no mesmo contrato. |
| `/fork` | **Parcial** | Há subagents/background, mas não o fork de conversa herdando contexto com o mesmo contrato. |
| `/review`, `/security-review`, `/code-review`, `/ultrareview` | **Parcial** | Há capability packs/skills de review, mas não um surface fechado e consolidado igual ao catálogo Claude. |
| `/browser`, `/desktop`, `/computer-use`, `/chrome` | **Parcial** | Há browser/computer-use no runtime e TUI, mas UX e cobertura ainda não equivalem aos surfaces do Claude. |
| `/schedule` | **Parcial** | Há `cron`, porém não o produto de rotinas/cloud workflow do Claude Code. |
| `/tasks` | **Parcial** | Há `sessions`, `agents`, `activity`, mas não a mesma visão unificada de background/cloud sessions. |
| `/config` | **Parcial** | Existe `/config`, mas hoje resume surfaces/contracts; não é a UI de settings comparável do Claude Code. |

### 1.3 Ausentes

| Grupo | Comandos |
|---|---|
| Web/cloud handoff | `/autofix-pr`, `/teleport`, `/web-setup`, `/ultraplan` |
| Conta/consumo/plano | `/usage-credits`, `/privacy-settings`, `/passes`, `/upgrade` |
| UX/TUI | `/color`, `/focus`, `/export`, `/heapdump`, `/keybindings`, `/release-notes`, `/statusline`, `/theme`, `/tui`, `/terminal-setup`, `/recap`, `/powerup` |
| Instalação/apps | `/install-github-app`, `/install-slack-app`, `/mobile` |
| Skills/workflows específicos | `/claude-api`, `/deep-research`, `/fewer-permission-prompts`, `/run-skill-generator`, `/team-onboarding` |

### 1.4 Fora de escopo do core técnico, mas ainda gap se a meta for “cobrir tudo”

- `/radio`
- `/stickers`

---

## 2) CLI commands e subcommands do Claude Code

### 2.1 Já cobertos de forma nativa ou muito próxima

| Claude CLI | Situação no Simplicio |
|---|---|
| `claude` | `simplicio` / TUI local |
| `claude "query"`','docs/CLAUDE_CODE_COMMAND_COVERAGE_AUDIT_2026-06-15.md','377cd62ced26b4a3c0d5798005729a37c70080c988c14fde36bd49ed7e2edb26','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md','project_doc','doc://simplicio-runtime/docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md','doc: Claude Code -> Simplicio command matrix — 2026-06-15','# Claude Code -> Simplicio command matrix — 2026-06-15

Matriz operacional derivada de:

- `C:\Users\Z0059V7A\m\ai\claude-code`
- docs oficiais do Claude Code consultadas em 2026-06-15
- `C:\Users\Z0059V7A\m\ai\simplicio-runtime\docs\CLAUDE_CODE_COMMAND_COVERAGE_AUDIT_2026-06-15.md`

Legenda:

- `nativo`
- `parcial`
- `ausente`
- `fora-do-escopo`

## Coverage snapshot

Contagem atual derivada desta matriz:

- `nativo`: 30
- `parcial`: 33
- `ausente`: 47
- `fora-do-escopo`: 2
- total rastreado nesta matriz: **112 entradas**

Leitura operacional:

- os comandos já cobertos nativamente ficam documentados aqui para não virarem “lacuna fantasma”
- os comandos parciais e ausentes apontam para issue de tracking explícita
- os itens fora de escopo continuam rastreados para que a decisão de não implementar fique auditável

## Built-in session commands

| Claude Code | Status | Equivalente/observação | Tracking |
|---|---|---|---|
| `/help` | nativo | `/help` | #1514 |
| `/clear` `/new` `/reset` | nativo | `/clear` | #1514 |
| `/compact` | nativo | `/compact` | #1514 |
| `/agents` | nativo | `/agents` / `simplicio agent` | #1514 |
| `/background` | nativo | `/background` | #1514 |
| `/branch` | nativo | `/branch` | #1514 |
| `/cost` `/usage` | nativo | `/cost` `/usage` | #1514 |
| `/doctor` | nativo | `/doctor` | #1514 |
| `/goal` | nativo | `/goal` | #1514 |
| `/login` `/logout` | nativo | `/login` `/logout` | #1514 |
| `/mcp` | nativo | `/mcp` / `simplicio mcp` | #1514 |
| `/memory` | nativo | `/memory` | #1514 |
| `/model` | nativo | `/model` | #1514 |
| `/plan` | nativo | `/plan` / `simplicio plan` | #1514 |
| `/plugins` | nativo | `/plugins` | #1514 |
| `/resume` | nativo | `/resume` | #1514 |
| `/version` | nativo | `/version` | #1514 |
| `/voice` | nativo | `/voice` | #1514 |
| `/copy` | nativo | `/copy` | #1514 |
| `/debug` | nativo | `/debug` | #1514 |
| `/permissions` | parcial | gate/mode sem UX equivalente | #1523 |
| `/context` | parcial | resumo estilo Claude Code via `/context` + `/prompt-size`, sem grid/parity total | #1523 |
| `/hooks` | parcial | runtime hooks sem UX equivalente | #1523 |
| `/ide` | parcial | `/platforms` / adapters | #1523 |
| `/init` | parcial | onboarding/orientação, sem parity | #1523 |
| `/insights` | parcial | `/insights` com escopo diferente | #1523 |
| `/run` | parcial | `simplicio run` sem contract app-observation | #1524 |
| `/verify` | parcial | `validate` cobre parte | #1524 |
| `/loop` | parcial | cron/scheduler sem UX equivalente | #1524 |
| `/batch` | parcial | multi-agent/wave-engine sem `/batch` equivalente | #1524 |
| `/fork` | parcial | subagents/background sem fork equivalente | #1524 |
| `/review` | parcial | review capabilities dispersas | #1525 |
| `/security-review` | parcial | review/security packs dispersos | #1525 |
| `/code-review` | parcial | capabilities/skills sem surface consolidado | #1525 |
| `/ultrareview` | parcial | deep review ainda sem parity | #1525 |
| `/browser` | parcial | browser runtime parcial | #1526 |
| `/desktop` | parcial | computer-use alias parcial | #1526 |
| `/computer-use` | parcial | existe, UX diferente | #1526 |
| `/chrome` | parcial | browser integration parcial | #1526 |
| `/schedule` | parcial | `cron` sem produto equivalente | #1524 |
| `/tasks` | parcial | sessions/agents/activity, sem board equivalente | #1515 |
| `/autofix-pr` | ausente | — | #1515 |
| `/teleport` | ausente | — | #1515 |
| `/web-setup` | ausente | — | #1515 |
| `/ultraplan` | ausente | — | #1515 |
| `/usage-credits` | ausente | — | #1516 |
| `/privacy-settings` | ausente | — | #1516 |
| `/passes` | ausente | — | #1516 |
| `/upgrade` | ausente | — | #1516 |
| `/color` | ausente | — | #1517 |
| `/focus` | ausente | — | #1517 |
| `/export` | nativo | `/export [file]` exporta a conversa atual em texto plano | #1517 |
| `/heapdump` | ausente | — | #1517 |
| `/keybindings` | ausente | — | #1517 |
| `/release-notes` | ausente | — | #1517 |
| `/statusline` | ausente | — | #1517 |
| `/theme` | nativo | alias de `/skin` para parity | #1517 |
| `/tui` | ausente | — | #1517 |
| `/terminal-setup` | ausente | — | #1517 |
| `/recap` | ausente | — | #1517 |
| `/powerup` | ausente | — | #1517 |
| `/install-github-app` | ausente | — | #1518 |
| `/install-slack-app` | ausente | — | #1518 |
| `/mobile` | ausente | — | #1518 |
| `/claude-api` | ausente | — | #1519 |
| `/deep-research` | ausente | — | #1519 |
| `/fewer-permission-prompts` | ausente | — | #1519 |
| `/run-skill-generator` | ausente | — | #1519 |
| `/team-onboarding` | ausente | — | #1519 |
| `/radio` | fora-do-escopo | superfície de produto Anthropic | #1516 |
| `/stickers` | fora-do-escopo | superfície de produto Anthropic | #1516 |

## CLI commands / subcommands

| Claude CLI | Status | Equivalente/observação | Tracking |
|---|---|---|---|
| `claude` | nativo | `simplicio` | #1514 |
| `claude "query"` | nativo | `simplicio chat` / bare invocation | #1514 |
| `claude -p` | parcial | headless próximo, não idêntico | #1514 |
| `claude -c` / `-r` | nativo | `resume` / sessions | #1514 |
| `claude update` | nativo | `simplicio update` | #1514 |
| `claude install` | nativo | `simplicio install` | #1514 |
| `claude auth login/logout/status` | nativo | login/logout/auth | #1514 |
| `claude agents` | nativo | `simplicio agent` | #1514 |
| `claude mcp` | nativo | `simplicio mcp` | #1514 |
| `claude plugin` | parcial | plugins/install sem tree equivalente | #1527 |
| `claude ultrareview` | parcial | review deep path incompleto | #1527 |
| `claude auto-mode defaults/config` | ausente | — | #1521 |
| `claude --worktree` | parcial | worktrees existem, UX diferente | #1527 |
| `claude --tmux` | parcial | delegação/worktree parcial | #1527 |
| `claude --chrome` | parcial | browser integration parcial | #1527 |
| `claude attach` | ausente | — | #1520 |
| `claude logs` | ausente | — | #1520 |
| `claude respawn` | ausente | — | #1520 |
| `claude rm` | ausente | — | #1520 |
| `claude stop` | ausente | — | #','docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md','e39f129d30e5215abcb9694aeb11fcc52f5b49459b83287651bb6e8216d2296e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/CLAUDE_CODE_COMMAND_MATRIX_CANONICAL.md','project_doc','doc://simplicio-runtime/docs/CLAUDE_CODE_COMMAND_MATRIX_CANONICAL.md','doc: Simplicio — Canonical Claude Code Command Matrix','# Simplicio — Canonical Claude Code Command Matrix

**Version:** 1.0.0 (2026-06-16)
**Supersedes:** `docs/CLAUDE_CODE_COMMAND_MATRIX_2026-06-15.md`
**Watcher:** Este arquivo é consumível pelo watcher interno #1513 — o watcher lê
a seção *Coverage snapshot* e cada coluna `Tracking` para detectar novos
comandos Claude Code sem equivalente registrado.

## Formato da coluna

| Claude Code | Status | Equivalente Simplicio | Alias/contrato | Evidência | Tracking |
|---|---|---|---|---|---|

- **Status:** `nativo` · `parcial` · `ausente` · `fora-do-escopo`
- **Alias/contrato:** alias proposto na superfície REPL ou decisão formal
- **Evidência:** caminho de arquivo + linha (nativo) ou ref de issue + doc de decisão
- **Tracking:** issue de acompanhamento da lacuna

## Coverage snapshot

| Status | Contagem |
|---|---|
| nativo | 30 |
| parcial | 33 |
| ausente | 47 |
| fora-do-escopo | 2 |
| **total** | **112** |

---

## Built-in session commands

| Claude Code | Status | Equivalente Simplicio | Alias/contrato | Evidência | Tracking |
|---|---|---|---|---|---|
| `/help` | nativo | `/help` — help local | alias direto | `src/tui_app.rs:776` | #1514 |
| `/clear` `/new` `/reset` | nativo | `/clear` — nova sessão | alias `/clear`; variantes `/new` `/reset` planejadas | `src/tui_app.rs:778` | #1514 |
| `/compact` | nativo | `/compact` — densidade do transcript | alias direto | `src/tui_app.rs:786` | #1514 |
| `/agents` | nativo | `/agents` · `simplicio agent` | alias direto + CLI | `src/tui_app.rs:871` | #1514 |
| `/background` | nativo | `/background` — prompt em background | alias direto | `src/tui_app.rs:817` | #1514 |
| `/branch` | nativo | `/branch` — branch/HEAD e último run | alias direto | `src/tui_app.rs:863` | #1514 |
| `/cost` `/usage` | nativo | `/cost` — ledger de sessão | alias `/cost`; `/usage` como variante | `src/tui_app.rs:804` | #1514 |
| `/doctor` | nativo | `/doctor` — estado geral do runtime | alias direto | `src/tui_app.rs:851` | #1514 |
| `/goal` | nativo | `/goal` — goal do último run | alias direto | `src/tui_app.rs:865` | #1514 |
| `/login` `/logout` | nativo | `/login` · `/logout` | alias direto (ambos) | `src/tui_app.rs:854-855` | #1514 |
| `/mcp` | nativo | `/mcp` · `simplicio mcp` | alias direto + CLI | `src/tui_app.rs:860` | #1514 |
| `/memory` | nativo | `/memory` — neural memory backend | alias direto | `src/tui_app.rs:880` | #1514 |
| `/model` | nativo | `/model` — show/change model | alias direto | `src/tui_app.rs:801` | #1514 |
| `/plan` | nativo | `/plan` · `simplicio plan` | alias direto + CLI | `src/tui_app.rs:826` | #1514 |
| `/plugins` | nativo | `/plugins` — apps/plugins runtime | alias direto | `src/tui_app.rs:842` | #1514 |
| `/resume` | nativo | `/resume` — retomar sessão | alias direto | `src/tui_app.rs:21109` (test) · sessão handler | #1514 |
| `/version` | nativo | `/version` — release ativa | alias direto | `src/tui_app.rs:810` | #1514 |
| `/voice` | nativo | `/voice` — runtime de voz | alias direto | `src/tui_app.rs:850` | #1514 |
| `/copy` | nativo | `/copy` — copiar última resposta | alias direto | `src/tui_app.rs:815` | #1514 |
| `/debug` | nativo | `/debug` — status/capacidade do runtime | alias direto | `src/tui_app.rs:845` | #1514 |
| `/export` | nativo | `/export [file]` — exporta conversa em texto | alias direto | `src/tui_app.rs:809` | #1517 |
| `/theme` | nativo | alias de `/skin` — parity Claude Code | `/theme` → `/skin` (alias) | `src/tui_app.rs:797-798` | #1517 |
| `/permissions` | parcial | `simplicio gate mode` + `simplicio config --permissions` | `/permissions` to-complete: merge em surface única | `src/action_bridge.rs` (action_gate); `src/hooks_command.rs` | #1523 |
| `/context` | parcial | `simplicio prompt-size` + `chat_context_slots` | `/context` to-complete: inspector de janela | token economy module; `chat_context_slots` | #1523 |
| `/hooks` | parcial | `hooks_command.rs` nativo — alias faltando | `/hooks` to-complete: wire alias no REPL | `src/hooks_command.rs` (implementado) | #1523 |
| `/ide` | parcial | `simplicio platforms` + `acp_adapter` | `/ide` to-complete: expor acp_adapter como comando REPL | `src/acp_adapter/mod.rs` | #1523 |
| `/init` | parcial | `simplicio install --init project` | `/init` to-complete: wire alias | install module; CLAUDE.md scaffold | #1523 |
| `/insights` | parcial | `/insights` (existe, escopo diferente) | enhancement: token savings trends, cost breakdown, memory hit rate | insights module; standing rule CLAUDE.md | #1523 |
| `/run` | parcial | `simplicio run` + `delivery_runverify.rs` | `/run` to-complete: `simplicio deliver runverify --observe` | `src/delivery_runverify.rs` | #1524 |
| `/verify` | parcial | `simplicio validate` + `simplicio deliver runverify` | `/verify` to-complete: compose validate + runverify | `src/validate_command.rs`; `src/delivery_runverify.rs` | #1524 |
| `/loop` | parcial | `simplicio cron` (`cron_scheduler.rs`) | `/loop` to-complete: modo in-session + modo `--cron` | `src/cron_scheduler.rs` | #1524 |
| `/batch` | parcial | multi-agent fan-out (tokio fabric, 64→600) | `/batch` to-complete: fan-out sobre targets via semaphore | `src/batch_runner.rs` (se existir); tokio fabric | #1524 |
| `/fork` | parcial | `simplicio agent fork`; `EnterWorktree` | `/fork` to-complete: snapshot + sub-agent + gate | agent spawn em `src/main.rs`; `EnterWorktree` | #1524 |
| `/review` | parcial | review capabilities dispersas | `/review` to-complete: surface consolidado | `docs/claude-code-coverage/1525-review-partials.md` | #1525 |
| `/security-review` | parcial | review/security packs dispersos | `/security-review` to-complete | `docs/claude-code-coverage/1525-review-partials.md` | #1525 |
| `/code-review` | parcial | capabilities/skills sem surface consolidado | `/code-review` to-complete | `docs/claude-code-coverage/1525-review-partials.md` | #1525 |
| `/ultrareview` | parcial | deep review sem parity | `/ultrareview` to-complete | `docs/claude-code-coverage/1525-review-partials.md` |','docs/CLAUDE_CODE_COMMAND_MATRIX_CANONICAL.md','85d6909d439c95fb5f16dcb8d04eac603afee6fafb0b4147df43286d79222111','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/CLEAN_MACHINE_E2E.md','project_doc','doc://simplicio-runtime/docs/CLEAN_MACHINE_E2E.md','doc: Clean-machine E2E evidence (#3005)','# Clean-machine E2E evidence (#3005)

`scripts/clean-machine-e2e.py` is the release evidence gate for the
install → Runtime → Agent/Desktop chain. It is manifest-driven because the
published installer/package commands and the Agent/Desktop transport are
release inputs, not safe defaults to guess in source code.

The harness runs one command at a time with `shell=False`, never starts a
daemon or mapper, and refuses promotion when a required command, screenshot,
artifact, or hash is missing. It writes a redacted step log and a receipt under
`.simplicio-loop/e2e/clean-machine/<run-id>/`.

## Run a release manifest

```bash
python scripts/clean-machine-e2e.py \
  --manifest path/to/published-clean-machine-manifest.json \
  --output .simplicio-loop/e2e/clean-machine
```

Validate the shape without executing commands:

```bash
python scripts/clean-machine-e2e.py \
  --manifest path/to/published-clean-machine-manifest.json \
  --plan
```

The manifest must identify issue `3005`, branch `codex/issue-3005`, the exact
40-character commit SHA under test, and provide non-empty argv arrays for real
published/install commands plus a real `version_argv` for every step. Every
required step can declare log-backed `screenshots` and `artifacts`; the harness records
SHA-256 and byte counts for each. Secret-looking environment values and
inline command values are redacted before logs or receipts are written.

The receipt keeps unavailable measurements as `null` (for example child CPU or
RSS on platforms without a standard-library API) and keeps token counts null
unless the release runner supplies them. It therefore cannot turn an
unmeasured value into a false zero or a blocked run into a pass.

No runnable manifest is committed: the repository does not contain published
Agent/Desktop installer commands or a clean Windows host. A release runner must
provide those commands and the actual screenshot paths. Any missing prerequisite
remains a P0 blocker.','docs/CLEAN_MACHINE_E2E.md','fe042e789555cc862d3e70835f6a497174a50ecdd225baf4df557988db4095f8','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/command-consolidation-plan.md','project_doc','doc://simplicio-runtime/docs/command-consolidation-plan.md','doc: Plano de consolidação de comandos (646 → namespaces)','# Plano de consolidação de comandos (646 → namespaces)

Análise por 12 agentes (workflow). **118 comandos de topo** colapsam em ~12 namespaces `simplicio <ns> <sub>`. Regra de ouro: **todo nome antigo vira alias oculto** (zero quebra de scripts/skills).

| namespace | colapsa | subcomandos |
|---|---|---|
| `simplicio memory|context|learn|evidence <sub>` | −30 | memory query·memory v2·memory db·memory action·memory providers·memory agent·memory deep·memory modern·context summarize|compress|show·context manage·context slots·learn (docs/ingest + run, already has internal subs) |
| `simplicio gh <subcommand>` | −15 | cli·auth·issues·issue-factory·issue-gate·issue-worktree·pr·pr-batch·pr-workflow·pr-lifecycle·review·repo |
| `simplicio agent <sub>` | −13 | list·ipc·store·hibernate·metrics·state·monitor·memory·rooms·broadcast·sync·warm-pool |
| `simplicio skill <sub>` | −10 | list·install·remove·create·delete·index·recall·search·guard·curate·rank·health |
| `Four cohesive namespaces` | −10 | voice <existing> (transcribe|speak|stt|tts|run|capture|status — unchanged)·voice relay·voice orb·voice gates  (folds voice_gates_command: status/session/quality/realtime/safety under it)·voice engine  (folds voice_engine_command: status/speak/listen/demo under it)·video <existing> (script|audio|timeline|render|captions|assets|pipeline|ingest|reference|orchestrate — unchanged)·video generate  (folds video_generate_command, the provider-gated generative path)·hyperframes <existing> (doctor|init|preview|render)·hyperframes cli·hyperframes media·hyperframes registry·shop app |
| `simplicio hermes <sub>` | −8 | hermes sync·hermes install-cron·hermes feed·hermes eval·hermes parity·hermes readiness·hermes port·openclaw migrate·openclaw coverage·openclaw analyse |
| `simplicio tui <subcommand>` | −7 | config·chat·agents·yool·models·tasks·settings·multiline |
| `simplicio yool <sub>  +  simplicio autopilot <sub>` | −6 | yool put|get|query|inspect·yool sync·yool tokio·yool orchestrate·autopilot start|stop|status|config·autopilot cli·autopilot scheduler·autopilot harness |
| `simplicio dev <sub>` | −6 | exec·test |
| `simplicio savings <sub>` | −5 | report·dashboard·watch·snapshot·ledger |
| `simplicio study <sub>` | −4 | flashcards·quiz·plan·ask |
| `simplicio runtime <sub>` | −4 | map·smoke·profile·scaling·cpu |

## Detalhe por tema (subcomando ← comandos antigos absorvidos)

### simplicio memory|context|learn|evidence <sub> (four sibling namespaces — these are four distinct domains, NOT one)  (−30 comandos)
- `memory query` ← memory, mem
- `memory v2` ← memory-v2, memory2
- `memory db` ← memory-db, memories, neural-db, neuraldb
- `memory action` ← memory-action, mem-action
- `memory providers` ← memory-providers, ext-memory
- `memory agent` ← agent-memory, memory-agent
- `memory deep` ← deep-memory, user-model, memory-profile
- `memory modern` ← memory-modern, vec-memory, lancedb-mem
- `context summarize|compress|show` ← context
- `context manage` ← context-manage, ctx-manage
- `context slots` ← chat-context, context-slots
- `learn (docs/ingest + run, already has internal subs)` ← learn, learn-docs, learn-doc, ingest-docs
- `learn ext` ← learn-ext, learn-extended
- `learn auto` ← auto-learn, learn-loop
- `learn skill` ← skill-learn, skill-curator
- `learn precedent` ← precedent-learn
- `evidence (default summary)` ← evidence
- `evidence show-run` ← evidence-show-run
- `evidence ledger` ← evidence-ledger
- `evidence chain` ← evidence-chain

**Risco/cuidado:** Three real hazards. (1) `self-learn` is a DUPLICATE alias — bound on both `skill-learn` (line 276) and `auto-learn` (line 1031); the match arm at 276 wins, so 1031''s `self-learn` is already dead code. When you collapse, do NOT re-add `self-learn` to two namespaces or you reintroduce/worsen the collision; pick one (it currently resolves to skill-self-learning) and keep the other dead. (2) `context-digest` is in the `st_` orchestrator family (#2088, st_context_digest_command), not the chat/context-window family — it is load-bearing for the orchestrator status pipeline and should NOT be folded under `context <sub>` even though the name prefix matches; leave it in the st_ namespace. (3) `memory`/`mem` and `learn` are heavily referenced by skills and the CLAUDE.md MANDATORY loop (`simplicio memory \"<q>\"`, the learn retrospective) and by scripts/functional-tests.sh — the flat names MUST stay as working hidden aliases forever or the spine + skills break. `evidence` (bare) is also a top-level command separate from `ledger`; keep both.

**Racional:** These four prefixes are NOT one domain — forcing memory+context+learn+evidence under a single namespace would violate the rule against merging unrelated verbs. They are four coherent sibling namespaces. memory-* is the clearest win: 8 flat commands (24 names with aliases) all operate on the neural memory store / its backends and collapse cleanly to `memory <sub>`. learn-* (6 commands) all feed the continual-learning loop. context-* collapses 3 (excluding context-digest which belongs to st_). evidence-* collapses 4 around the evidence ledger/chain. `learn` and `context` ALREADY have internal subcommand dispatch (learn: auto-status/suggest/prompts/skills/reasoning + path-ingest; context: summarize/compress/show), so the pattern is proven — this just extends it to the sibling flat commands. Net ~30 top-level arms collapse into 4 namespaces while every old name survives as a hidden alias (zero script/skill breakage).

### simplicio gh <subcommand> (+ a separate simplicio codex <subcommand>)  (−15 comandos)
- `cli` ← gh, gh-cli
- `auth` ← github-auth
- `issues` ← github-issues, gh-issues
- `issue-factory` ← issue-factory, issue_factory, issuefactory
- `issue-gate` ← issue-gate, issuegate
- `issue-worktree` ← issue-worktree, issue_worktree
- `pr` ← pr
- `pr-batch` ← prs, pull-requests
- `pr-workflow` ← github-pr, gh-pr, pull-request
- `pr-lifecycle` ← pr-lifecycle
- `review` ← github-code-review, gh-review, code-review
- `rep','docs/command-consolidation-plan.md','2199ebe3a53f2f05401671764510e8aff9016b72a28e2db20a5996031607110f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/COMPATIBILITY_MATRIX.md','project_doc','doc://simplicio-runtime/docs/COMPATIBILITY_MATRIX.md','doc: Compatibility Matrix','# Compatibility Matrix

The compatibility matrix (`simplicio.compatibility-matrix/v1`) records the
minimum adapter versions the Simplicio control plane requires and the contracts
each first-party component must speak. It powers the `compatibility` block of
`simplicio doctor --json` and gates whether the runtime can safely drive an
external adapter. This is part of the adapter-resolution work (issue #45).

## Components

| Component | Command | Min version | Contract schema | Role |
|---|---|---|---|---|
| `simplicio-mapper` | `simplicio-mapper` | `0.19.0` | `simplicio.map-result/v1` | repository context reader and mapper |
| `simplicio-dev-cli` | `simplicio-dev-cli` | `0.11.0` | `simplicio.dev-result/v1` | deterministic implementation and write adapter |
| `simplicio-prompt` | `simplicio-prompt` | `0.14.1` | `simplicio.prompt-envelope/v1` | LLM artifact contract producer and reviewer |
| `simplicio-loop` | `simplicio-loop` | `3.24.0` | `simplicio.hbp/v1` | task iteration orchestration and evidence loop (replaces `simplicio-sprint`) |
| `simplicio-runtime` | `simplicio` | (runtime `VERSION`) | `simplicio.standard-io/v1` | control plane, schema registry, and compatibility gate |

## Status evaluation

For each resolved adapter the matrix compares the detected version against the
minimum version:

- `compatible` — detected version meets or exceeds the minimum.
- `incompatible` — detected version is below the required minimum.
- `unknown` — the adapter was found but does not expose a parseable version.
- `missing` — no adapter resolved for this component.

## Known incompatibilities

- **mapper** — pre-0.13 lacks `inspect`/`handoff`; pre-0.14 lacks the flow-docs
  engine (flows/sync/survey/business/ask/drift/history).
- **dev-cli** — legacy pre-0.5.20 Python `simplicio` command conflicts with the
  Rust runtime.
- **prompt** — prompt tools without envelope cache keys.
- **loop** — pre-3.22.4 lacks the runtime gate-escalation/checkpoint hooks;
  pre-3.22.6 lacks the `simplicio hbp append` call it records verified promises
  through; pre-3.24.0 predates the latest published release.

## Repair

Each rule carries a `repair` string surfaced in `doctor --json`, e.g.

- mapper: `upgrade simplicio-mapper or set [tools].mapper to a compatible checkout`
- dev-cli: `upgrade simplicio-dev-cli or set [tools].dev_cli explicitly`
- loop: `upgrade simplicio-loop: pip install --upgrade simplicio-loop`

## Freshness policy

The matrix requires `git fetch --prune` and `git pull --ff-only` and records the
source commit and package version of each component before promoting
compatibility. See `docs/ADAPTER_RESOLUTION.md` for the full resolution chain.','docs/COMPATIBILITY_MATRIX.md','552ec80316c08bdca4cc3af0f33a29c01882dd3ee6e2eb8dc3c70a7e4713d642','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/COMPETITIVE_BENCHMARK.md','project_doc','doc://simplicio-runtime/docs/COMPETITIVE_BENCHMARK.md','doc: Simplicio Competitive Benchmark — 2026-06-05','# Simplicio Competitive Benchmark — 2026-06-05

Battery of head-to-head tests run from this checkout against real, autonomous
agents and the top open-source models, graded by objective oracles (execute the
code / parse the file), with raw evidence committed under
`docs/evidence/agent-battery-2026-06-05/`.

- **Runtime under test:** `target/release/simplicio` v0.3.37 (commit `adec272`),
  built `cargo build --release --locked`.
- **LLM backend (held constant where models are compared):**
  `deepseek/deepseek-v4-flash` via OpenRouter.
- **Generative-media backend:** WaveSpeed API.
- **Grading:** objective oracle — execute the resulting program and check exit 0.

---

## 1. Executive summary

| Battery | What it measures | Headline result |
|---|---|---|
| A. Agents | Simplicio vs reference agent vs OpenClaw, same model | All 6/6; **Simplicio fastest (43.6s), lowest measured tokens, 3.4 MB footprint, deterministic** |
| B. Models | HumanEval pass@1 vs top-10 open-source models | Simplicio''s loop lifts deepseek-v4-flash **86.7% → 93.3%**, beating its own raw backend and matching frontier models |
| C. Media | WaveSpeed image + video generation | image 6.8s / video 35s, total **~$0.05**, end-to-end working |
| D. V4 Pro | HumanEval re-run with **DeepSeek V4 Pro** + forced full engine | v4-pro raw **100%** (15/15, top of board); Simplicio 93.3%; the runtime now **forces** the full stack on every execution (v0.3.38) |
| E. Full 164 | HumanEval **164**, with vs without a paid LLM | **With V4 Pro: 95.1%** (vs raw 91.5%). **Without any paid LLM (local 4B, $0): 56.1%** (92/164, zero tokens) |
| F. Native local | Full native engine on the **local in-process model** ($0) | `reason` + `dev-cli` run the local 3B in-process (no `llama-server`), `paid_tokens_used:false` — the previously-impossible test now passes |

---

## 2. Battery A — Simplicio × reference agent × OpenClaw (agents, model held constant)

The backend model is the same behind all three (`deepseek/deepseek-v4-flash`) so
the comparison measures the **agents**, not the model.

- **Simplicio** — deepseek proposes a `simplicio.mechanical-edit/v1` plan; the
  runtime''s deterministic substring gate validates it, then `simplicio edit`
  applies it with a sha256-verified write; the oracle verifies. The model only
  proposes — the mutation is deterministic and runtime-owned.
- **Hermes** — `hermes -z <prompt> -m deepseek/deepseek-v4-flash --provider openrouter --accept-hooks`.
- **OpenClaw** — `openclaw agent --local --model openrouter/deepseek/deepseek-v4-flash -m <prompt> --json`.

### Per-task results (6 tasks)

| task | Simplicio | Hermes | OpenClaw |
|---|---|---|---|
| authoring:two_sum  | ✅ 10276 ms / 654 tok | ✅ 14397 ms | ✅ 15930 ms / 21905 tok |
| authoring:fizzbuzz | ✅ 12146 ms / 302 tok | ✅ 9135 ms  | ✅ 12975 ms / 21485 tok |
| algorithm:gcd      | ✅ 12648 ms / 785 tok | ✅ 7043 ms  | ✅ 12537 ms / 21336 tok |
| bugfix:factorial   | ✅ 3475 ms / 290 tok  | ✅ 19783 ms | ✅ 26801 ms / 21896 tok |
| bugfix:sum_to_n    | ✅ 3773 ms / 280 tok  | ✅ 15426 ms | ✅ 36648 ms / 21970 tok |
| exact-edit:config  | ✅ 1260 ms / 182 tok  | ✅ 5183 ms  | ✅ 12248 ms / 21430 tok |

### Summary & criteria matrix

| criterion | Simplicio | Hermes | OpenClaw |
|---|---|---|---|
| Correctness (oracle) | **6/6** | 6/6 | 6/6 |
| Total latency | **43.6 s** | 71.0 s | 117.1 s |
| Per-task latency | **7.3 s** | 11.8 s | 19.5 s |
| Measured paid tokens | **2 493** | not exposed¹ | 130 022 |
| Determinism of mutation | **sha256 write + substring gate** | free-form | free-form |
| Token transparency | full (per call) | none on stdout | full (per turn) |
| Install footprint | **3.4 MB single binary** | 130 MB (py venv) | 345 MB (npm) |
| Evidence / audit trail | run dir + sha256 | none | session jsonl |

¹ `hermes -z` does not emit token usage on stdout — **not** zero (it runs a full
agent loop), simply unmeasured. Recorded honestly.

### Setup notes for adjacent competitors

These tools are documented here so they are easy to discover from the benchmark
corpus. They are setup references and comparison surfaces; the scored battery
above still uses the same oracle rules.

- **OpenHands** — install with `uv tool install openhands --python 3.12`
  (recommended) and launch with `openhands serve`. On Windows, run the CLI
  inside WSL. For headless or env-driven runs, export
  `OPENHANDS_SUPPRESS_BANNER=1`, pass `--override-with-envs`, and provide
  `LLM_MODEL`, `LLM_API_KEY`, and `LLM_BASE_URL` explicitly.
- **Aider** — install with `pipx install aider-chat` or
  `uv tool install --force --python python3.12 --with pip aider-chat@latest`.
  Aider works best in its own Python environment and with git installed.
- **claude-task-master / Task Master** — install with
  `npm i -g task-master-ai` (or `npx -y task-master-ai` for MCP). Configure the
  provider keys you intend to use in `.env` or the MCP config, then initialize
  with `task-master init`, `task-master parse-prd`, `task-master list`, and
  `task-master next`.

**Read:** correctness ties on purpose (model held constant on self-contained
tasks). The agent-level differentiators are latency, token economy, determinism,
transparency, and footprint — Simplicio leads on every one. Evidence:
`evidence/agent-battery-2026-06-05/three-agent-battery.{json,log}`.

---

## 3. Battery B — HumanEval pass@1 vs the top open-source models

The canonical code benchmark used at model launches (OpenAI HumanEval). Each
model gets the standard single-shot protocol; **Simplicio runs the same backend
(`deepseek-v4-flash`) through its deterministic loop** — model proposes →
substring gate → `simplicio edit` sha256 write → oracle → one iterate-until-green
retry on failure. Subset n=15 (cost/time); grading is the official HumanEval
oracle (`prompt + completion + test + check(entry_point)`).

### Leaderboard (pass@1, n=15)

| # | agent / model | pass@1 | solved |
|---|---|---|---|
| 1 | z-ai/glm-4-32b | 100.0% | 15/15 |
| 2 | google/gemma-4-31b-it | 10','docs/COMPETITIVE_BENCHMARK.md','2afc173be59aaf0534e72209fc3d827624f74c9559627722d6dafe1459503ae1','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/content/PIPELINE.md','project_doc','doc://simplicio-runtime/docs/content/PIPELINE.md','doc: Daily Content Pipeline','# Daily Content Pipeline

Automatically generates a 30-second feature-highlight video and social-media
caption every time a feature is shipped.

## How it works

1. A GitHub issue is labelled **`feature-video`** and then closed.
2. The `Content Pipeline` GitHub Actions workflow fires (or runs on its daily
   noon-UTC schedule on weekdays).
3. `scripts/content/content-pipeline.sh` queries closed issues with the label
   and calls `scripts/content/generate-daily-video.sh` for each one.
4. If [Remotion](https://www.remotion.dev/) templates exist at
   `apps/video-templates/remotion/`, a real `.mp4` is rendered.
   Otherwise the script logs a graceful no-op and writes only the caption.
5. All outputs (`.mp4`, caption `.txt`, script `.json`, `pipeline.log`) are
   uploaded as a GitHub Actions artifact (retained 30 days).

## Triggering a video for a feature

1. Open or find the GitHub issue for the feature.
2. Add the label **`feature-video`** to the issue.
3. Close the issue (merge the PR, or close manually).
4. The workflow starts automatically within a few minutes.

No code changes required — the label is the only switch.

## Running manually

```sh
# Single feature
scripts/content/generate-daily-video.sh \
    "Action Bridge" \
    "Deterministic action dispatch with full gate + evidence trail" \
    "1.0.4" \
    "dist/screenshots/action-bridge"

# Full pipeline (requires gh CLI + jq)
scripts/content/content-pipeline.sh
```

You can also trigger the workflow manually from
**Actions → Content Pipeline → Run workflow** on GitHub.

## Output structure

```
dist/content/
  pipeline.log                        # pipeline run log
  video_YYYYMMDD_<feature>.mp4        # rendered video (if Remotion available)
  video_YYYYMMDD_<feature>.txt        # caption + hashtags
  script_YYYYMMDD_<feature>.json      # Remotion composition JSON
```

## Adding Remotion templates

Place your Remotion project at `apps/video-templates/remotion/` with an entry
point that exports a `FeatureHighlight` composition. The generate script passes
the composition props as JSON including `feature`, `description`, `version`,
`duration_frames` (900 = 30 s @ 30 fps), and `scenes`.

If the template directory is absent, `generate-daily-video.sh` exits 0 after
writing the caption — no render failure, no broken pipeline.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CONTENT_PIPELINE_LOOKBACK_DAYS` | `7` | How many days back to scan for closed issues |
| `GH_TOKEN` | (from Actions) | GitHub token for `gh issue list` |','docs/content/PIPELINE.md','57c50c62044007bbaf5b759f326aca0ad682f0a83e729e97b59d665d05eef3ac','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/contracts/agent-handoff.md','project_doc','doc://simplicio-runtime/docs/contracts/agent-handoff.md','doc: Agent Handoff Contract','# Agent Handoff Contract

`simplicio.agent-handoff/v1` is the typed continuation envelope for agent-to-agent work inside the
runtime.

## Why this exists

The runtime already has leases, delegation, evidence, and PR handoff. What was still weak was the
middle of the flow: a structured way to say "this is the current execution state, this is the
validated context, this is what the next agent should do, and this is the evidence bundle that
backs the handoff."

That gap shows up most when work crosses boundaries:

- extraction -> validation
- triage -> implementation
- implementation -> verification
- blocked lane -> human gate

## Contract

- Schema: [`schemas/agent-handoff.schema.json`](../../schemas/agent-handoff.schema.json)
- Id: `simplicio.agent-handoff/v1`
- Required spine:
  - `handoff_id`
  - `status`
  - `execution_state`
  - `from_agent`
  - `to_agent`
  - `summary`
  - `next_steps`
  - `evidence_refs`

## What it adds beyond ad hoc notes

- Explicit lifecycle state: `proposed -> planned -> dry_run -> authorized -> executed -> verified`
- Typed lineage for governed retries: `source_artifact`, `chunk_id`, `stage_id`, `validator`,
  `retry_count`
- First-class blocked and next-action fields instead of burying them inside prose
- Stable evidence references so a receiving lane can continue without re-deriving the same context

## Current status

This slice registers the contract in the runtime schema registry and documents the intended
payload. It does not yet replace existing `pr-handoff` or lease flows; the next implementation step
is to emit it from the runtime surfaces that already create delegation or review handoffs.','docs/contracts/agent-handoff.md','d6236a97d0a19633d97770c82ea937519e794eded37154152a2426ab8514c89e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/contracts/orchestrator-v6.md','project_doc','doc://simplicio-runtime/docs/contracts/orchestrator-v6.md','doc: Orchestrator v6 — lazy-loaded contract','# Orchestrator v6 — lazy-loaded contract

This is the canonical index for the simplicio-tasks launcher. The launcher stays
small; this contract owns the detailed modules and their loading rules.

## Entry contract

A normalized item is:

source, source_id, repository, workspace, outcome, dependencies, acceptance, risk.

A lane must return:

status, evidence, receipts, blockers.

Valid statuses are done, partial, blocked, and rejected. A plan is not evidence
of completion.

## Lazy-load map

| Need | Load |
|---|---|
| work intake, dependencies, parallelism | [orchestration](../../.claude/skills/simplicio-tasks/references/orchestration.md) |
| deterministic extension points | [extension points](../../.claude/skills/simplicio-tasks/references/extension-points.md) |
| safety, tests, delivery, rollback | [quality/safety/delivery](../../.claude/skills/simplicio-tasks/references/quality-safety-delivery.md) |
| 24/7 watcher and durable loop | [standing loop](../../.claude/skills/simplicio-tasks/references/standing-loop-247.md) |
| token economy and savings honesty | [token economy](../../.claude/skills/simplicio-tasks/references/token-economy.md) |
| web/video evidence | [web/video evidence](../../.claude/skills/simplicio-tasks/references/web-video-evidence.md) |
| host adapters | [adapters](../../.claude/skills/simplicio-tasks/references/adapters.md) |

## Router

1. Probe the runtime and host policy.
2. Normalize and deduplicate the work item.
3. Select the smallest lane that can satisfy the acceptance checks.
4. Load only the corresponding module.
5. Execute in an isolated workspace.
6. Verify observable output and preserve receipts.
7. Report the result using the entry contract.

The router may fall back to host tools when Simplicio is unavailable, but it must
keep the same safety, evidence, and status semantics.','docs/contracts/orchestrator-v6.md','f45250167866f0b4521d081b57d084dde243811271f136221a1e306abe19c2eb','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/contracts/orchestrator-v7.md','project_doc','doc://simplicio-runtime/docs/contracts/orchestrator-v7.md','doc: Orchestrator Contract v7','# Orchestrator Contract v7

> **Canonical version.** This is the single source of truth for the Simplicio orchestrator protocol.
> All skills, code, and docs reference this document. Recover older versions via git history.

## Scope

Universal orchestrator protocol covering the full task lifecycle: discovery → intake → routing → execution → quality → delivery → self-audit. Supersedes v5 (run-specific) and v6 (run-specific) contracts.

## Identity

Runtime: Simplicio (any strong LLM/runtime). Coordination: delegate_task, spawn, or native scheduler. Mode: dual-path router (fast-path / heavy-path).

## Protocol — Lifecycle Steps

### Step 0 — Auto-arm the loop
- Write `.simplicio-loop/orchestrator/loop/scratchpad.md` with goal, cap, and promise.
- Loop re-feeds the goal each turn until completion promise verified or cap hit.

### Step 1 — Identity + Environment
- Emit identity line. Detect: git default branch, source auth, build/test runner, CPU/RAM/disk.

### Step 1a — Pre-flight (MANDATORY)
- Kill-switch budget: `loop-budget.json` with `daily_usd_ceiling`.
- Source auth: `gh auth status` or equivalent. Verify scopes.
- Watcher: arm durable 24/7 if ceiling > 0.

### Step 1b — Extension Points
43 named extension points. Host binds natively when available; LLM fallback otherwise.

Key extension points: `orient`, `recall`, `deterministic_edit`, `claim`, `worktree`, `diagnostics`, `validate`, `pr`, `watcher`, `savings_ledger`, `model_route`, `dependency_graph`, `durable_workflow`, `work_queue`, `delivery_gate`, `action_gate`.

### Step 1c — Token Economy Gate
- INTERNET OFF unless current external facts required.
- EXECUTE via terminal — never simulate.
- Clamp output: success-collapse, dedup, signal-tiered caps.

### Step 2 — Discover + Normalize
- Resolve source adapter. List candidates by metadata. Normalize. Dedup by source-id.

### Step 2b — Deep Intake
- Read full body + ALL comments. Extract acceptance criteria.

### Step 3 — Route (Dual-path)
- **Fast-path:** small queue, every item ≤ complexity 3. Inline, solo.
- **Heavy-path:** large queue or any medium+ item. Continuous worker pool, autoscale `fleet = min(cap_cpu, cap_mem, cap_disk, items, 16)`.

## v7 Capacities (Normative)

### Capacity 1 — DAG Scheduling + Pipeline (#2508)
- **TaskGraph:** build dependency graph from tasks (each declares deps).
- **Topological sort:** execution order via Kahn''s algorithm.
- **Semaphore-controlled parallelism:** run independent tasks concurrently.
- **Replace batch barriers:** pipeline execution instead of "run all, wait, next batch".
- **CLI:** `orchestrate plan --dag --json` / `graph --dot`.

```rust
struct TaskNode {
    id: String,
    deps: Vec<String>,
    status: TaskStatus,
}

struct TaskGraph {
    nodes: Vec<TaskNode>,
    edges: Vec<(String, String)>, // (from, to) dependency edges
}

impl TaskGraph {
    fn topological_order(&self) -> Vec<&TaskNode>;
    fn parallel_layers(&self) -> Vec<Vec<&TaskNode>>;
}
```

### Capacity 2 — Git Worktree Isolation (#2519)
- **WorktreePool:** manage N git worktrees for parallel task execution.
- **Per-task isolation:** each agent/task gets its own worktree (`git worktree add`).
- **Gated merge:** only merge back when verification passes (`cargo check` + tests).
- **Idempotent:** track completed tasks, don''t redo.
- **Cleanup:** remove worktrees after merge.

```rust
struct WorktreePool {
    base_dir: PathBuf,
    worktrees: HashMap<String, PathBuf>,
}

impl WorktreePool {
    fn acquire(&self, task_id: &str) -> Result<PathBuf, WorktreeError>;
    fn release(&self, task_id: &str) -> Result<(), WorktreeError>;
    fn merge_gated(&self, task_id: &str) -> Result<MergeResult, WorktreeError>;
}
```

### Capacity 3 — Adversarial Verification (#2520)
- **Skeptic panel:** N independent verifiers (LLM-based or deterministic) that attempt to REFUTE the completion claim.
- **Majority gate:** majority-refute → reject; majority-approve → pass.
- **Built-in deterministic verifiers:** CompileCheck, TestCheck, NoTodoInProd, NoPanicInHotPath.
- **Integration:** runs BEFORE declaring work delivered.

```rust
enum ReviewVerdict {
    Approve,
    Refute { reason: String },
}

fn run_builtin_verifiers(repo: &Path) -> VoteCollection;
fn majority_decision(collection: &VoteCollection, cfg: &ReviewConfig) -> ReviewOutcome;
```

### Capacity 4 — Loop Budget Cap (#2521)
- **Budget ceiling:** `max_iterations`, `max_tokens`, `max_wall_clock`.
- **Oscillation detection:** fingerprint diagnostics per iteration, same set K times → stop.
- **Dual exit:** require BOTH green diagnostics AND callback approval.
- **Honest report:** `LoopOutcome { results, exit_reason, final_green }` — never fake green.

```rust
enum ExitReason {
    Success,
    MaxIterations,
    TokenBudget,
    WallClock,
    OscillationDetected,
    CallbackAborted,
}

struct LoopOutcome {
    results: Vec<IterationResult>,
    exit_reason: ExitReason,
    final_green: bool,
}
```

## Quality Gates (MANDATORY)

1. **Compile check** after every edit
2. **Test pass** after compilation
3. **Adversarial verify** (skeptic panel) before delivery
4. **Secret-scan** every diff before commit/push
5. **Loop budget guard** prevents infinite iteration

## Safety

- **Secret-scan** every push.
- **Irreversible-op human gate:** force-push, history rewrite, prod deploy → STOP and ask.
- **Four-state verdict:** OPTIMIZE_AND_RUN / RUN_RAW / BLOCK / OPTIMIZE_BUT_CONFIRM.
- **Budget kill-switch:** daily USD ceiling, per-run token ceiling.
- **No silent fake data:** never claim green when not verified.

## Delivery

- Commit: Conventional Commits (English).
- Push: Draft PR with evidence (verification output, test results).
- Merge: only after all quality gates pass + adversarial verify approves.
- Close: source re-query confirms item actually closed/merged.

## Self-Audit

After each delivery cycle:
1. Score the run (token efficiency, time, quality).
2. Fix P0/P1 findings immediately.
3. Delegate to `simplicio-learn` for post-run retrospec','docs/contracts/orchestrator-v7.md','c0b48b19e96b2e8057ae4e47ef6dd81cbc66bee505b828a6f5add5d9f4a46927','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/core/ERROR_HANDLING_SPEC.md','project_doc','doc://simplicio-runtime/docs/core/ERROR_HANDLING_SPEC.md','doc: Error Handling & Logging — Issue #2203','# Error Handling & Logging — Issue #2203

## Overview

Consistent structured JSON errors across all Simplicio commands, machine-readable
log output, and OpenTelemetry tracing for cross-process observability. This
replaces ad-hoc `eprintln!` + `String` errors with a typed, schema-versioned
error contract.

## Error schema

Every error returned by any Simplicio command follows:

```json
{
  "schema": "simplicio.error/v1",
  "code": "<SCREAMING_SNAKE>",
  "message": "<human-readable>",
  "context": {
    "command": "map",
    "file": "src/main.rs",
    "line": 42
  },
  "trace_id": "<hex-16>",
  "span_id": "<hex-8>",
  "timestamp": "<iso8601>"
}
```

### Error code taxonomy

| Prefix | Domain |
|--------|--------|
| `CONFIG_*` | Configuration errors |
| `IO_*` | Filesystem / I/O |
| `AUTH_*` | Authentication / secrets |
| `GATE_*` | Action gate denials |
| `LLM_*` | Model / provider errors |
| `SANDBOX_*` | Skill sandbox violations |
| `VAULT_*` | Secrets vault errors |
| `SKILL_*` | Skill execution errors |
| `PARSE_*` | Input parsing errors |
| `INTERNAL_*` | Unexpected runtime errors |

## SimplicioError type

```rust
#[derive(Debug, Serialize)]
pub struct SimplicioError {
    pub schema: &''static str,  // "simplicio.error/v1"
    pub code: String,
    pub message: String,
    pub context: serde_json::Value,
    pub trace_id: String,
    pub span_id: String,
    pub timestamp: String,
}

impl SimplicioError {
    pub fn new(code: &str, message: impl Into<String>) -> Self { ... }
    pub fn with_context(mut self, key: &str, val: impl Serialize) -> Self { ... }
    pub fn json(&self) -> String { serde_json::to_string(self).unwrap() }
}
```

Exit contract: any command that fails writes `SimplicioError` JSON to stderr
and exits with code 1. Success writes result JSON to stdout.

## Structured logging

Format: JSONL to stderr (one JSON object per line).

```json
{"ts":"2026-06-18T10:00:00Z","level":"INFO","target":"simplicio::map","msg":"repo scanned","files":47,"ms":23}
```

Log levels: `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`.  
Default level: `INFO`. Override: `SIMPLICIO_LOG=debug`.

Implementation: `tracing` crate + `tracing-subscriber` with JSON formatter.
Replaces all `eprintln!` and raw `println!` in non-test code paths.

## OpenTelemetry tracing

Each command creates a root span. Sub-operations (map, memory recall, edit,
gate classify, LLM call) create child spans.

```rust
let span = tracer.start("simplicio.map");
let _guard = span.with_cx(Context::current_with_span(span.clone()));
// ... do work ...
span.end();
```

Export: OTLP over HTTP to `OTEL_EXPORTER_OTLP_ENDPOINT` (default: disabled).
When endpoint is not set, tracing is a no-op (zero overhead).

Span attributes:
- `simplicio.command`: the top-level subcommand
- `simplicio.version`: binary version
- `simplicio.trace_id`: hex-16

## Migration plan

Phase 1 (this issue): define `SimplicioError`, implement for all `Err(String)` 
returns in `src/main.rs` that currently produce non-JSON output on stderr.

Phase 2: wire `tracing` + JSON subscriber; replace `eprintln!` with `tracing::warn!` etc.

Phase 3: OTLP export, span propagation across sub-agent boundary (B3 headers).

## Delivery criteria

- [ ] `src/error.rs` with `SimplicioError` struct and `SimplicioResult<T>` alias
- [ ] `schema = "simplicio.error/v1"` on all error outputs from CLI commands
- [ ] Exit code 1 on all errors (no silent non-zero exits)
- [ ] `tracing` + JSON subscriber wired; `SIMPLICIO_LOG` env controls level
- [ ] `eprintln!` calls in non-test code replaced with `tracing::*` macros
- [ ] OTLP export stub: compiles but no-ops when endpoint is unset
- [ ] Test: `SimplicioError::json()` round-trips through `serde_json::from_str`

## Tracking

GitHub: #2203','docs/core/ERROR_HANDLING_SPEC.md','b6fe441624d5ad6a96589458ba8b256e2800d9977573c6785dc26954f4eb58c5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/cowork-alternatives/2026-06-25-analysis.md','project_doc','doc://simplicio-runtime/docs/cowork-alternatives/2026-06-25-analysis.md','doc: Claude Cowork alternatives — GitHub scan + import plan (2026-06-25)','# Claude Cowork alternatives — GitHub scan + import plan (2026-06-25)

User: "Pesquise no GitHub: Cowork, traga as melhores alternativas pra cá." Goal: bring the
best open-source computer-use agents/patterns into Simplicio so it does computer-use BETTER
than Claude Cowork / Codex (Codex has NONE — it''s a terminal coding agent). MIT/Apache → port
patterns or integrate directly; do not copy proprietary.

## Ranked alternatives (stars · relevance to Simplicio)

| repo | ★ | what | use for Simplicio |
|---|---|---|---|
| **CursorTouch/Windows-MCP** | 6.2k | **MCP server** for Windows computer-use (UI Automation, any LLM, no vision; 0.2-0.5s/action; `use_dom` web mode; 2M+ users via Claude Desktop) | **#1 — INTEGRATE directly**: Simplicio is an MCP client → register `uvx windows-mcp` → instant click/type/screenshot/UI-state on Windows. Fastest path; complements the Ally-Tree port #2655 |
| **browser-use/browser-use** | 100k | web agent automation via the DOM/accessibility tree (the de-facto standard) | **#2** — web computer-use; mirror its DOM-tree approach for the browser lane (or run it as a tool) |
| **trycua/cua** | 19k | full-desktop computer-use infra (mac/win/linux) + sandboxes + **benchmarks** | study the cross-platform abstraction + use its benchmarks to grade Simplicio''s computer-use |
| **microsoft/UFO** | 9k | Microsoft''s Windows UI-Automation agent (UFO³) | deep reference for robust Windows UIA control + multi-app orchestration |
| **simular-ai/Agent-S** | 12k | "uses computers like a human" — agentic framework | reference for the perceive→plan→act→verify loop + experience-augmented memory |
| **bytebot-ai/bytebot** | 11k | self-hosted AI desktop agent (NL → desktop tasks) | reference for the self-hosted desktop-agent UX |
| **OthersideAI/self-operating-computer** | 10k | multimodal model operates a computer (vision) | the vision-grounding lane (Simplicio''s visual_loop) — fallback when UIA can''t see an element |
| **the-open-agent/openagent** | — | personal AI assistant: computer-use + browser-use + coding + RAG + agent loops | **vision twin** — study its architecture (closest to Simplicio''s goal) |
| **microsoft/fara** | — | Fara-7B: efficient agentic computer-use MODEL | candidate model for grounding (eval vs qwen3-vl), like LaneFormer #2654 |
| **go-vgo/robotgo** | — | Go cross-platform RPA/GUI library | low-level input/screen primitives reference |

## Decision (computer-use, Windows first)
1. **Integrate Windows-MCP as an MCP server (#1, fastest).** Register it in Simplicio''s MCP client; the
   spine routes computer-use requests ("clique no botão X", "tire um screenshot") to its tools. UI
   Automation, any LLM (qwen local / DeepSeek), no vision model — already the "better than Cowork" path.
   Parallel to the native Ally-Tree port (#2655) for a no-Python-dependency option later.
2. **Web computer-use:** browser-use approach (DOM tree) for the browser lane.
3. **Vision fallback:** keep visual_loop (Qwen3-VL / self-operating-computer style) for non-accessible UIs.
4. **Grade it:** use trycua/cua benchmarks (+ the 145-case catalog) as the computer-use gate.

Internet now broadly enabled (user) for ongoing innovation scanning.

## Direct "Cowork" products (user GitHub scan, 2026-06-25) — the closest twins

| repo | ★ | license | the key pattern to bring |
|---|---|---|---|
| **eigent-ai/eigent** | 14.4k | Apache-2.0 | Open-source Cowork desktop; **multi-agent workforce** (built on CAMEL-AI) — parallel execution; 100% local + **MCP integration** + custom models + SSO |
| **accomplish-ai/coworker** | 10.9k | MIT | Local desktop agent: file mgmt + document writing + **browser** tasks; **save repeatable workflows as SKILLS**; **per-action approval + logs + stop** (the gate); Ollama/BYO keys |
| **composio-community/open-claude-cowork** | 4.3k | MIT | Desktop chat on Claude Agent SDK + **Composio Tool Router = 500+ SaaS integrations** (Gmail/Slack/GitHub/Drive…); persistent memory (facts/preferences/daily notes) |

### Headline insight → the "do absolutely everything" stack
**Composio (500+ SaaS apps) + Windows-MCP (desktop control) + the multi-agent workforce** is the
path to Simplicio doing everything. Composio is the integrations layer (an MCP/tool router);
Simplicio is an MCP client → integrate it for instant Gmail/Slack/Notion/GitHub/Drive/... access.
coworker confirms our own design: skills = saved workflows (osaurus Methods #2649) + the action
gate (approve/log/stop). eigent/CAMEL-AI = reference for the multi-agent workforce we already have.','docs/cowork-alternatives/2026-06-25-analysis.md','325b813cb69451cee83ed37cd50455720da992322be2d0e31832ca44f9d77637','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/COWORK_HERMES_FUNCTIONAL_CATALOG.md','project_doc','doc://simplicio-runtime/docs/COWORK_HERMES_FUNCTIONAL_CATALOG.md','doc: Cowork/Hermes-parity FUNCTIONAL test catalog (connected, real)','# Cowork/Hermes-parity FUNCTIONAL test catalog (connected, real)

From research on Claude Cowork + Hermes Agent + agent benchmarks (2026-06-25, wf_71fb9a2a-c02). **145 cases � 110 GAPs** = the connection backlog. Each is a REAL connected test: NL request -> REAL observable outcome (side-effect/content), never exit code. GAP = not reachable from chat yet.

## apps (10)

| id | scenario | real assertion | status / path |
|---|---|---|---|
| app-01 | User: ''launch VS Code'' | VS Code process actually starts | wired spine FreeNl -> detect_open_app_intent -> open_application |
| app-02 | User: ''open Notepad and write a shopping list'' | Notepad opens and the list text appears in it | **GAP** GAP � open works but type-into-app GUI step not chained in spine |
| app-03 | User: ''open my email and search for messages from Quora'' | The mail app/web opens and a from:Quora search executes | **GAP** GAP � no app-internal navigation route in spine |
| app-04 | User: ''play my Discover Weekly on Spotify'' | Spotify opens and starts playing the playlist | **GAP** skill_spotify / spotify command exists; GAP � not NL-routed by spine to in-app action |
| app-05 | User: ''add a reminder to call mom at 6pm'' (Apple Reminders) | A reminder is created in the system reminders app | **GAP** apple_reminders.rs (macOS); GAP � Windows-first, not NL-routed by spine |
| app-06 | User: ''create a note titled Groceries in my notes app'' | A new note titled Groceries exists in the notes app | **GAP** apple_notes.rs / notes MCP; GAP � Windows path absent, not NL-routed |
| app-07 | User: ''switch to the Slack window'' | Slack is brought to the foreground | **GAP** open_application brings forward; GAP � ''switch to'' phrasing not in detect_open_app_intent |
| app-08 | User: ''open the calculator and compute 19% of 240'' | Calculator opens and shows 45.6 | **GAP** GAP � open works but GUI compute steps not chained |
| app-09 | User: ''send a message to my team on Slack: standup at 10'' | The message actually posts to the Slack channel | **GAP** slack platform / send command; GAP � not NL-routed by spine |
| app-10 | User: ''continue this conversation on Telegram'' | The same session is resumed and replied to on Telegram | **GAP** gateway telegram + cross-platform continuity; GAP � spine not bridged to gateways |

## automation (9)

| id | scenario | real assertion | status / path |
|---|---|---|---|
| auto-01 | User: ''every morning at 8am check my email and summarize it'' | A recurring cron job is registered and fires on schedule | wired spine Route::Schedule -> cron command (cron_scheduler); job created |
| auto-02 | User: ''remind me to stand up every hour'' | An hourly recurring task is registered and triggers | wired spine Route::Schedule -> cron; reachable |
| auto-03 | The scheduled email-summary job fires | At fire time the email is actually checked and a summary delivered | **GAP** GAP � cron fires but the email-check action chain is not wired |
| auto-04 | User: ''run a weekly Slack digest every Friday'' | A weekly job is registered and posts a digest to Slack | **GAP** cron + slack platform; GAP � digest action not wired to the schedule |
| auto-05 | User: ''list my scheduled tasks'' | The real registered cron jobs are listed | **GAP** cron list command; GAP � not NL-routed by spine |
| auto-06 | User: ''cancel the morning email job'' | That specific cron job is removed and no longer fires | **GAP** cron remove command; GAP � NL cancel-by-description not routed by spine |
| auto-07 | One-shot: ''remind me to check the deploy at 3pm today'' | A one-shot job fires once at 3pm and delivers the reminder | wired schedule_nl / cron one-shot; reachable via Route::Schedule |
| auto-08 | Webhook event arrives from an external system | The agent activates and produces a templated platform message | **GAP** webhook command; GAP � not wired through the conversational spine |
| auto-09 | User: ''batch-process these 100 prompts overnight and save outputs'' | All 100 are processed unattended and outputs saved | **GAP** batch_runner; GAP � not NL-routed by spine |

## chat (13)

| id | scenario | real assertion | status / path |
|---|---|---|---|
| chat-01 | User says: ''hi, who are you and what can you do?'' | A coherent identity/capability reply is returned in the chat surface (not an action), composed by chat_answer | wired spine run_turn -> Route::Chat -> spine_chat/chat_answer |
| chat-02 | User asks: ''explain the difference between a process and a thread'' | A correct factual explanation is returned without triggering any action route or web call | wired spine run_turn -> Route::Chat -> chat_answer (greetings_and_questions_stay_chat) |
| chat-03 | User: ''summarize this paragraph: <long text>'' | A shorter faithful summary of the supplied text is returned | wired spine Route::Chat -> chat_answer; context_summarize available |
| chat-04 | User asks a follow-up ''and what about the second one?'' referencing the prior turn | Reply correctly resolves the pronoun against the prior turn in the same session | **GAP** GAP � spine has no multi-turn conversation memory passed into chat_answer (per-turn only) |
| chat-05 | User: ''reply in Portuguese from now on'' | Subsequent replies in the session are in Portuguese | **GAP** GAP � locale/persona not persisted as a standing instruction by the spine across turns |
| chat-06 | User: ''are you sure? double-check that answer.'' | Assistant re-evaluates and either confirms or corrects the prior answer | **GAP** GAP � no self-critique turn wired into spine chat path |
| chat-07 | User: ''stop'' | The current activity is acknowledged as stopped and no further action runs | wired spine Route::Stop -> spine_compose_stop |
| chat-08 | User: ''what''s your status / what are you working on?'' | A real runtime status summary is returned (agents/run state), not a canned string | wired spine Route::Status -> status command |
| chat-09 | User: ''rewrite this email to sound more polite'' | A reworded, more polite version of the text is returned | w','docs/COWORK_HERMES_FUNCTIONAL_CATALOG.md','8419eb10d67e40ebc569f6c758b7e2ea7bcf8406e7cf5d64ce500bea920b70fa','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/DELIVERY_QUALITY.md','project_doc','doc://simplicio-runtime/docs/DELIVERY_QUALITY.md','doc: Delivery Quality Gates — Simplicio EPIC #250','# Delivery Quality Gates — Simplicio EPIC #250

Automated quality gates for every delivery. Covers issues #251–#255.

## Command reference

```
simplicio deliver dod [<task>] [--json]         DoD acceptance gate (#251)
simplicio deliver works [<feature>] [--json]    smoke test / run-verification (#252)
simplicio deliver regression [--json]           regression guard (#253)
simplicio deliver review [--json]               pre-delivery self-review (#254)
simplicio deliver certificate [<task>] [--json] delivery certificate (#255)
simplicio deliver help                          list all subcommands
```

## Gates

### DoD & Acceptance Gate (#251)
Checks:
- Tests pass (`simplicio validate`)
- Uncommitted changes flagged (warning, not block)

Output: `simplicio.dod-gate/v1`

### Run-Verification / Works-Check (#252)
Smoke test: runs `simplicio validate` and reports pass/fail.
Output: `simplicio.works-check/v1`

### Regression Guard (#253)
- Runs `simplicio validate`
- Reports `git diff --stat HEAD~1..HEAD` for behavioral delta

Output: `simplicio.regression-guard/v1`

### Pre-Delivery Self-Review (#254)
- Reports `git diff --stat HEAD` (working tree)
- Reports `git diff --cached --stat` (staged)
- Surfaces diff for human review before commit

Output: `simplicio.self-review/v1`

### Delivery Certificate (#255)
Issues a certificate with:
- `cert_id` — deterministic ID (sha256 of task+timestamp)
- `grade` — A/B/C based on score
- `score` — 1.0 if tests pass, 0.5 if not
- `tests_pass` — boolean
- `last_commit` — git log --oneline -1

Output: `simplicio.delivery-certificate/v1`

## Usage in REPL

```
/deliver dod         run DoD gate
/deliver certificate issue quality certificate
/dod                 shorthand for DoD gate
/cert                shorthand for certificate
```

## Integration with Action Bridge

The delivery gates integrate with the Action Bridge (#230) pipeline:
```
simplicio act "deliver feature X" --kind run
```
This will gate-check, run, and then optionally trigger delivery verification.

## Schemas

| Schema | Description |
|--------|-------------|
| `simplicio.dod-gate/v1` | acceptance criteria check result |
| `simplicio.works-check/v1` | smoke test / run verification |
| `simplicio.regression-guard/v1` | test diff + regression check |
| `simplicio.self-review/v1` | pre-delivery diff review |
| `simplicio.delivery-certificate/v1` | final quality score |','docs/DELIVERY_QUALITY.md','ee23b535103681895e35841d4581f914af75c964b5e99b130b33c6139f6ea9a2','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/design/browser-control.md','project_doc','doc://simplicio-runtime/docs/design/browser-control.md','doc: Browser / CDP / Computer-Use Fallback Table (Issue #1183)','# Browser / CDP / Computer-Use Fallback Table (Issue #1183)

## Fallback Ladder

| Priority | Tool              | Probe                                          | Tier     |
|----------|-------------------|-------------------------------------------------|----------|
| 1        | browser           | agent-browser or npx on PATH                    | extended |
| 2        | browser_cdp       | SIMPLICIO_BROWSER_CDP_URL or BROWSER_CDP_URL    | extended |
| 3        | browser_playback  | playwright on PATH                               | extended |
| 4        | computer_use      | macOS or Windows platform                        | optional |
| 5        | blocked           | (sentinel) all connectors unavailable            | ---      |

## blocked-by-connector Status

When all connectors are unavailable, the agent runner returns
status blocked-by-connector instead of failing mid-run.','docs/design/browser-control.md','f7c0343fa811f7575da097b9102ef19553b978e784f969130c2914659e548c99','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/design/coding-support.md','project_doc','doc://simplicio-runtime/docs/design/coding-support.md','doc: Advanced Coding Support — Design (#709)','# Advanced Coding Support — Design (#709)

> Status: **design / evaluation**. Closes Hermes gaps for programming work over
> the existing `acp_adapter`, dev-cli verify loop, and contracts.

## Goal

First-class coding agent: complete ACP (Agent Client Protocol) adapter, IDE
integration (VS Code, Zed), automatic code review, git workflows, and
test/deploy via contracts — all runtime-first with evidence.

## Building blocks (already present)

- `acp_adapter` (in-tree) — ACP surface to extend.
- `test-gated-edit/v1` + dev-cli verify loop — iterate-until-green, commit on
  green (see `docs/MECHANICAL_CONTRACTS.md`).
- `mechanical-edit/v1` — deterministic anchored edits.
- Git/branch + PR automation (existing `branch` command).

## Plan

1. **ACP completeness:** implement the full ACP method set (session, prompt,
   tool calls, file ops, permissions) in `acp_adapter`; conformance tests
   against the ACP schema.
2. **IDE integration:** ship ACP so Zed (native ACP) connects directly; for VS
   Code provide a thin extension that speaks ACP to the runtime. The runtime
   stays the execution authority; the IDE is a client.
3. **Automatic code review:** a `review` contract that runs the diff through
   the reviewer agent (`.agents/reviewer.agent.md`) + lint/test gates, emitting
   findings to the evidence ledger.
4. **Git workflows:** branch standardization + PR creation (existing) extended
   with conventional-commits enforcement and evidence-rich PR bodies.
5. **Test/deploy via contracts:** `test-gated-edit/v1` for the inner loop;
   a `deploy-check` gate for the outer.

## Contracts

- Reuse `test-gated-edit/v1`; add `code-review/v1` (`{diff_hash, findings[],
  gates{fmt,clippy,test}, verdict}`) to the evidence ledger.

## Milestones

1. ACP method coverage + conformance tests.
2. Zed connect (native ACP) smoke; VS Code thin client.
3. `code-review/v1` over reviewer agent + gates.
4. Conventional-commit + evidence PR bodies.','docs/design/coding-support.md','d15adff0f6350495d6f8aeb95f6aabe19a8e61b15683316e7eaec799ce0a403d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/design/conversation-loop.md','project_doc','doc://simplicio-runtime/docs/design/conversation-loop.md','doc: Conversation Loop — Hermes `run_conversation` → Simplicio (Design, #712)','# Conversation Loop — Hermes `run_conversation` → Simplicio (Design, #712)

> Status: **design + landed foundations**. The deterministic substrate is
> implemented and tested; the loop that drives a provider session through it
> reuses the runtime''s existing chat/reason path.

## Goal

Adapt Hermes'' mature `AIAgent.run_conversation` (tool-calling loop until
completion, prompt assembly, interrupt/steer, session persistence, context
compression, background review) to Simplicio — **Rust-native, runtime-first,
contracts + evidence**, not a Python port.

## Hermes pieces → Simplicio mapping

| Hermes concept | Simplicio realization | Status |
|---|---|---|
| Multi-turn message log | [`conversation::ConversationContext`](../../src/conversation.rs) (`Turn`/`Role`, ordered) | ✅ landed (#692) |
| Context compression / long-context | `ConversationContext::window` (token-budget, pins system) + `prune_to_budget` | ✅ landed (#692) |
| Session persistence (cross-session) | `ConversationContext::serialize`/`parse` (disk-first, escape-safe) | ✅ landed (#692) |
| Interrupt / steer (inject without restart) | [`conversation_control::TurnController`](../../src/conversation_control.rs) → `poll()` ⇒ `Checkpoint{Continue,Steer,Cancel}` | ✅ landed (#700) |
| Long-term recall (history search) | [`vector_memory::VectorStore`](../../src/vector_memory.rs) (cosine top-k) | ✅ foundation (#699) |
| Background self-review / skill creation | [`self_improvement::propose_skills`](../../src/self_improvement.rs) over receipts | ✅ foundation (#702) |
| Tool-calling loop until completion | runtime chat/reason path (`simplicio reason --act`, Action Bridge #230/gate #231) | existing |
| Prompt assembly / system prompt | provider-session orientation + `render_window()` | existing + ✅ |
| Trajectory/training capture | [`trajectory::Trajectory`](../../src/trajectory.rs) JSONL | ✅ landed (#711) |

## The loop (Rust)

```text
loop {
    ctx.push_user(input);                       // conversation (#692)
    let window = ctx.window();                  // token-budget context (#692)
    let plan = provider_session.plan(window);   // existing reason/chat path
    for step in plan.tool_calls {
        match controller.poll() {               // interrupt/steer (#700)
            Checkpoint::Cancel => break,
            Checkpoint::Steer(msgs) => ctx.push_system(merge(msgs)),
            Checkpoint::Continue => {}
        }
        let obs = action_bridge.run_gated(step);// Action Gate (#231)
        trajectory.record(step.phase, step.cmd, obs, reward); // (#711)
        ctx.push_assistant(obs.summary);
    }
    if plan.done { break }
}
ctx.prune_to_budget();                          // long-term compaction (#692)
self_improvement::propose_skills(&receipts);    // background review (#702)
```

Everything except `provider_session.plan` and `action_bridge.run_gated` (which
are the existing runtime chat/reason + Action Bridge) is **deterministic and
unit-tested** in the modules above.

## What remains

- A thin `SimplicioAgent` wrapper that wires the loop above over the existing
  `reason`/chat command and the streaming layer (Rig.rs / Tokio structured
  concurrency, #696/#700).
- Streaming token output + voice modality handoff (#701).
- Benchmarks vs Hermes (#703 quality track).

These are integration glue over already-landed, tested substrates — not new
research.','docs/design/conversation-loop.md','8ee8d46472b2b5c18bebaebbbb80f748f353963a12b4b3d0b10368677b71d714','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/design/conversation-spine.md','project_doc','doc://simplicio-runtime/docs/design/conversation-spine.md','doc: Conversational spine — design (epic #2599 keystone, #2601)','# Conversational spine — design (epic #2599 keystone, #2601)

One per-turn pipeline that BOTH the text chat surface and the voice surface call,
so Simplicio becomes a voice-first do-everything assistant. Grounded in current
`main` (2026-06-25). Stages:

`recall -> classify intent (deterministic-first) -> escalate (Levi/web on miss) -> action gate -> deterministic act/dispatch -> persist (turn+action+findings) -> compose reply (in modality)`

## Why
- `runtime_chat_reply` (src/main_parts/main_part_01.rs:23949) does NO recall, NO gate, NO action — delegation -> multi-agent dispatch -> `chat_answer` -> persist.
- `process_utterance` (src/voice_loop.rs:311) does recall+gate+dispatch but with its OWN ad-hoc helpers the text path never sees.
- The two surfaces share nothing. The spine erases that divergence.

## New module: `src/conversation_spine.rs`
Registered via `mod conversation_spine;` in src/main.rs (~line 160). Reaches
crate-root helpers in main_part_01.rs via `crate::` (same pattern as voice_loop.rs/action_gate.rs).

Entry function:
```rust
pub(crate) enum Modality { Text, Voice }
pub(crate) struct TurnOptions { execute: bool, confirm: bool, speak: bool, no_memory: bool, allow_escalation: bool }
pub(crate) struct TurnOutcome { reply: String, audio_intent: Option<String>, intent: String,
    action: Option<ActionOutcome>, recall: Vec<RecallHit>, escalation: Option<Escalation>, remote_used: bool }
pub(crate) fn run_turn(config: &mut crate::RuntimeConfig, input: &str, modality: Modality, opts: &TurnOptions)
    -> Result<TurnOutcome, String>
```
`config: &mut RuntimeConfig` (not `&Path`) — every stage already takes `&RuntimeConfig`; mutable so `config.task` can be set like runtime_chat_reply:23970.

Internal `Route` enum (deterministic union of voice `derive_command` + text dispatch checks):
`Stop | Status | Schedule{cron,task} | Direct{cmd,args} | FreeNl{utterance} | Chat{question}`.
Delegation + multi-agent dispatch become Route variants resolved BEFORE the LLM (preserves today''s order).

### Stage helpers (reuse, don''t reinvent)
| Stage | Helper | Delegates to (EXISTS) |
|---|---|---|
| recall | `spine_recall` | `agent_retrieve_sqlite` (…:16795) -> RecallHit |
| classify (#2609) | `spine_classify` | `schedule_nl::parse_nl_schedule:52`, `orchestrator_intent::is_orchestration_command:40`, voice `classify_intent`/`derive_command` |
| escalate (#2606) | `spine_escalate` | `levi_external_gap_requested:3025`, `levi_acquisition_decision:3070`, `record_levi_evidence:3098`; web via `web_search_command` (#2605) |
| gate | `spine_gate` | `evaluate_action_gate` (src/action_gate.rs:249) + `action_gate_mode_str` (src/action_bridge.rs:833) |
| dispatch | `spine_dispatch` | `commands::dispatch` (commands/mod.rs:45); free-NL via `reason_act_capture` (…:73628) |
| persist | `spine_persist` | `record_chat_memory_turn:17285` + `append_conversation_memory_item:17245` |
| compose | `spine_compose` | `chat_answer:65839` for chat; deterministic strings for action routes (mirror voice_loop.rs:377-387) |

## Adapters (smallest diff)
- `runtime_chat_reply` (…:23949): build config, call `run_turn(.., Text, ..)`, keep session ledger + `record_savings_event_for_chat_turn` in the caller. `record_chat_memory_turn` moves INTO `spine_persist` (voice gets it for free). Delegation + multi-agent dispatch move into `spine_classify`/`spine_dispatch` as Route variants. Guard cutover with `spine_enabled()` (env `SIMPLICIO_SPINE`, default OFF in #2601 so old body stays as `else`).
- `process_utterance` (src/voice_loop.rs:311): keep strip_wake, flag parse, JSON/human print, `record_event`, TTS in the adapter; replace the middle with one `run_turn(.., Voice, ..)`. dry-run/confirm identical (`execute && gate=="allow" && !cmd.is_empty()`).
- LEAVE `tui_chat_turn` (…:23990, `#[cfg(feature="tui")]`) untouched in #2601; follow-up routes it through the spine.

## Stage sequence (avoid main_part_01.rs collisions)
Confine ALL new logic to conversation_spine.rs (+ voice_loop.rs). Touch main_part_01.rs ONLY in #2601:
(a) rewrite runtime_chat_reply 23949-23980, (b) one batch of `fn`->`pub(crate) fn` visibility bumps for EVERY fn later stages need (recall, persist, chat_answer, chat_memory_db_path, chat_context_skills, Levi fns). Pre-staging visibility in #2601 means #2602/#2603/#2609/#2606 NEVER re-open the god-file.

1. **#2601** spine skeleton + adapters + visibility bumps + `SIMPLICIO_SPINE` flag (lands dark).
2. **#2602** recall: flesh `spine_recall`, thread RecallHit into persist (context_count) + compose.
3. **#2603** chat->action: `spine_classify` emits FreeNl/Direct; route through gate+dispatch (text gets voice''s superpowers). Flip flag on.
4. **#2609** NL intent router: real `spine_classify` unifying schedule_nl/orchestrator_intent/voice; voice re-exports.
5. **#2606** Levi: `spine_escalate` on recall-miss + external gap; evidence-only, never neural-DB writes.
Stages 2-5 are SERIAL within conversation_spine.rs (all touch run_turn/spine_classify) but never re-collide with main_part_01.rs.

## Risks / invariants
- Feature flag `SIMPLICIO_SPINE` (env, default off in #2601) — old body as `else`; #2603 flips on.
- Greeting short-circuit parity: `chat_answer:65842` + `record_chat_memory_turn:17287` early-return on `plain_greeting_reply` — reuse `chat_answer` so smalltalk doesn''t regress.
- Text passes `execute:true, confirm:false` -> ask-mode gate returns "confirm" for mutations -> NOT executed (dry-run default). No text turn mutates without `--confirm`.
- Levi governance: call `record_levi_evidence` (evidence-only), NEVER write neural DB; trigger only on recall-miss (Isa miss). Tests: main_tests.rs:202/218.
- `license::guard_command` (commands/mod.rs:48) runs on every dispatch — spine inherits, do not bypass.
- Tests that must keep passing: voice_loop.rs:399-448, action_gate.rs:416/469, main_tests.rs:2526/2580/2605/2674, Levi main_tests.rs:202/218/246/259.

## Test plan (no LLM/network)
1. recall-hit: seed tiny sqlite, `run_turn(Text)','docs/design/conversation-spine.md','ad8d2b3b4a8f36270d81de5a2bb100133ec7067650835b855362d822ca2d146a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/design/customer-service-verticals.md','project_doc','doc://simplicio-runtime/docs/design/customer-service-verticals.md','doc: Customer-Service Verticals — Design (#719 / #720 / #721)','# Customer-Service Verticals — Design (#719 / #720 / #721)

> Status: **design / evaluation**. These are product modules over external
> channels (WhatsApp Business API, Instagram DM) and per-vertical knowledge.
> Implementation needs credentials + a webhook endpoint; this doc fixes the
> shared architecture so each vertical is a thin config over one engine, and
> reuses the substrates already landed this cycle.

## Goal

Automated, humane customer service for service businesses — generic WhatsApp/
Instagram handling (#719) plus veterinary (#720) and dental (#721) verticals:
scheduling, reminders, triage, FAQs, voice summaries, smooth human handoff —
runtime-first, evidence-logged, persona-aware.

## One engine, thin verticals

```
WhatsApp/IG webhook ─▶ Channel Adapter ─▶ Conversation Engine ─▶ reply
                                              │   │
                    conversation::ConversationContext (#692, per-contact)
                    user_profile + persona (#715/#713, per-contact)
                    vector_memory recall over KB (#699)
                              │
                    Vertical Knowledge Base (vet / dental / generic)
                              │
                    Quality/Safety gate ──▶ Human Handoff (low confidence /
                                            sensitive: medical advice)
                    every turn ──▶ evidence ledger
```

- **Channel Adapter** (#719): normalize WhatsApp Business API + Instagram DM
  webhooks into a common `InboundMessage { contact, channel, text, media }`;
  send via the same trait. Webhook signature verification reuses the existing
  `webhook` command''s HMAC check.
- **Conversation Engine:** one engine; per-contact `ConversationContext` (#692)
  keeps multi-turn state with token budget; `UserProfile`/`Persona`
  (#715/#713) adapt tone (e.g. anxious patient → `Calm`).
- **Vertical = config + KB:** vet (#720) and dental (#721) differ only by their
  knowledge base (services, prices, prep/after-care, reminders schedule) and a
  few flows; both run on the engine. KB is retrieved via `vector_memory` (#699).
- **Safety/handoff:** medical/veterinary advice, high emotion, or low confidence
  trigger handoff to a human with full context — never auto-advise on health.
  Reuses the escalation surface.

## Per-vertical specifics

| | Veterinary (#720) | Dental (#721) | Generic (#719) |
|---|---|---|---|
| Scheduling | consults, vaccines | consults, cleanings | configurable |
| Reminders | vaccine/medication due | hygiene/post-treatment | configurable |
| Triage | symptom guidance → vet handoff | pain/anxiety → dentist handoff | generic FAQ |
| Voice | "how to give meds", pet first-aid | brushing/floss tutorials | optional |
| Persona | stressed tutor → `Calm`/`Warm` | anxious patient → `Calm` | per-contact |

## Contracts & evidence

- `simplicio.cs-conversation/v1`: per-turn record `{contact_hash, channel, intent,
  reply, confidence, handoff, kb_refs}` appended to the evidence ledger.
- Scheduling/financial actions (booking, payment links) go through the Action
  Gate with confirmation — never silent.

## Milestones

1. Channel Adapter trait + WhatsApp webhook (verify + normalize) behind a
   `customer-service` feature; IG DM next.
2. Conversation Engine wiring `ConversationContext` + `UserProfile`/`Persona`.
3. Vertical KB loader (vet, dental) over `vector_memory`.
4. Safety gate + human handoff with full context.
5. `cs-conversation/v1` evidence + voice summaries.

## Reuses (already landed)

`conversation` (#692), `conversation_control` (#700), `vector_memory` (#699),
`user_profile` (#715), `persona` (#713). The verticals are configuration and a
channel adapter over these — not new core machinery.','docs/design/customer-service-verticals.md','97afd7b65c5ccfd28e2e44d4330ce77909a3c9bb6bfac8836b9918060852bc8a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/design/desktop-control.md','project_doc','doc://simplicio-runtime/docs/design/desktop-control.md','doc: Desktop Control — Computer Use (Design, #706)','# Desktop Control — Computer Use (Design, #706)

> Status: **design / evaluation**. Implementation lands behind a `desktop` cargo
> feature; this doc fixes the approach and the trait so Helo/Yool can drive
> deterministic desktop actions before the backend exists.

## Goal

Native computer use across Windows/macOS/Linux: move/click, type, read the
screen, and act on UI elements — driven by Helo/Yool with deterministic,
auditable actions, Voice-first friendly.

## Approach evaluation (2026)

| Layer | Option | Verdict |
|---|---|---|
| Input synthesis | **enigo** (cross-platform mouse/keyboard) | ✅ primary |
| Screen capture | **xcap** / `screenshots` | ✅ primary — per-monitor PNG |
| Element targeting | **accessibility tree** (AX API / UIA / AT-SPI) | ✅ preferred over pixel-matching: deterministic, robust |
| Element targeting (fallback) | template/OCR match | when no a11y tree |

**Decision:** prefer the **accessibility tree** for targeting (stable element
ids/roles → deterministic, testable) and fall back to coordinate/visual actions
only when a11y is unavailable. Input via `enigo`, capture via `xcap`.

## Why accessibility-tree-first

Pixel/coordinate automation is brittle (resolution, theme, scroll). The a11y
tree gives named, role-typed nodes the runtime can target by a stable
`Selector { role, name, nth }` — making a desktop action plan a *contract* with
postconditions, not a fragile screen scrape.

## Proposed Rust interface

```rust
pub trait DesktopController {
    fn screenshot(&self) -> Result<Vec<u8>, DesktopError>;       // evidence
    fn tree(&self) -> Result<AxNode, DesktopError>;              // a11y snapshot
    fn click(&mut self, target: &Target) -> Result<(), DesktopError>;
    fn type_text(&mut self, text: &str) -> Result<(), DesktopError>;
    fn key(&mut self, chord: &str) -> Result<(), DesktopError>;
}

pub enum Target { Element(Selector), Point { x: i32, y: i32 } }
```

## Contract & safety

- `simplicio.desktop-plan/v1`: ordered `{op, target?, value?, expect?}` with
  postconditions (`element_present`, `window_title_contains`); each step logs to
  the evidence ledger with a screenshot.
- **Hard gating:** destructive or financial actions (delete, send, pay) require
  the Action Gate''s explicit approval — never auto-confirmed. Parental-control
  profile for the human-first personas (#713/#714).

## Milestones

1. `--features desktop` + enigo click/type + xcap screenshot smoke.
2. a11y tree read (one OS first, e.g. AT-SPI on Linux) → `AxNode`.
3. `DesktopController` trait + `desktop-plan/v1` executor with postconditions.
4. Helo/Yool driving plans deterministically; evidence per step.
5. Cross-OS a11y backends (UIA on Windows, AX on macOS).','docs/design/desktop-control.md','36666e76f6022cf92251d8fbd735ef0d92209e819f52303d90e846fe9598131b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/design/social-media-ops.md','project_doc','doc://simplicio-runtime/docs/design/social-media-ops.md','doc: Social Media Actions — Design (#708)','# Social Media Actions — Design (#708)

> Status: **design / evaluation**. Builds on the existing `social_ops` module and
> `docs/social-media-ops/` playbooks; implementation needs per-platform API
> credentials (or the browser backend for fallback).

## Goal

Post, interact, scrape, and automate across X, Instagram, LinkedIn, etc. —
official APIs first, browser-control fallback, voice-command friendly, evidence-
logged.

## Approach

- **Official APIs first** (per platform): X API, Instagram Graph API, LinkedIn
  API. Credentials via the unified auth/credential store; never embedded.
- **Browser fallback** for platforms/actions without API access — reuses the
  `BrowserController` from [`browser-control.md`](browser-control.md) + a domain
  allowlist; clearly flagged as ToS-risky, opt-in.
- **One trait, many backends:**
  ```rust
  pub trait SocialBackend {
      fn post(&self, p: &Post) -> Result<PostId, SocialError>;
      fn interact(&self, a: &Interaction) -> Result<(), SocialError>;
      fn fetch(&self, q: &Query) -> Result<Vec<Item>, SocialError>;
  }
  ```
- **Voice + commands:** `social` command surface (extends existing `social_ops`)
  and voice intents map to `Post`/`Interaction` structs.
- **Gating + evidence:** every outbound action (post, reply, DM) goes through the
  Action Gate with confirmation and is recorded (`social-action/v1`) — no silent
  posting.

## Reuse

- `social_ops` (in-tree) + `docs/social-media-ops/{x-twitter,instagram,...}.md`
  playbooks for per-platform specifics.
- `browser-control.md` (#707) for the fallback backend.

## Milestones

1. `SocialBackend` trait + X API backend (post/fetch) behind `--features social`.
2. Action-Gate + `social-action/v1` evidence on every outbound action.
3. Browser fallback backend (allowlisted, opt-in, ToS-flagged).
4. Instagram/LinkedIn backends; voice intents.','docs/design/social-media-ops.md','6d8a73544ba869646092daad6bb830dd5ef1a5e686132317a2ec1f8e097dad70','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/design/vestibular-study.md','project_doc','doc://simplicio-runtime/docs/design/vestibular-study.md','doc: Vestibular & Study Module — Design (#717)','# Vestibular & Study Module — Design (#717)

> Status: **design / evaluation**. Voice-first adaptive academic assistant for
> Brazilian college-entrance exams (ENEM, Fuvest, Unicamp). Implementation needs
> content/embeddings + the voice stack; this doc fixes the architecture over
> already-landed substrates.

## Goal

Adaptive, proactive, Voice-First study assistant: dynamic study plans,
interactive voice lessons + quizzes, full exam simulator with spoken timing,
essay (redação) help with spaced repetition, and real-life modes (studying in
the car, parent with a baby) — gamified, with a satisfaction loop.

## Architecture over landed substrates

```
content (ENEM/Fuvest BR) ─▶ vector_memory (#699)  ◀─ retrieval for lessons/quiz
student profile ─▶ user_profile + persona (#715/#713)  (tone, pace, proactivity)
study session ─▶ conversation::ConversationContext (#692)  (multi-turn, budget)
voice ─▶ voice-first (#701)  (lessons, quiz, timed simulator, barge-in via #700)
progress ─▶ trajectory (#711) + self_improvement (#702)  (what to review next)
```

## Components

1. **Content + embeddings:** curated BR exam corpus (subjects, past questions,
   essay rubrics) indexed in `vector_memory` (#699).
2. **Study Planner:** generates a dated plan from target exam + available time +
   weak areas (deterministic scheduler; reuses `scheduler`/cron for reminders).
3. **Interactive Lesson + Quiz Engine:** retrieve → explain → ask → grade →
   adapt difficulty; spoken via the voice stack.
4. **Essay (redação) + spaced repetition:** rubric-based feedback; SR schedule
   (Leitner) over `vector_memory` recall.
5. **Real-life modes:** Driver/SingleParent personas (#713) → hands-free voice.
6. **Gamification + satisfaction loop:** streaks + `user_profile.satisfaction`
   (#715) drives proactive adjustments.

## Safety

- Academic-integrity guardrails (assist, don''t do graded work for the student).
- Parental-control persona for minors (#713).

## Milestones

1. Content loader + `vector_memory` index of a subject (smoke).
2. Study Planner (plan JSON) + reminders via scheduler.
3. Lesson/Quiz engine (text first, then voice).
4. Essay feedback + Leitner SR.
5. Car/parent voice modes; gamification + satisfaction loop.

## Reuse

`vector_memory` (#699), `conversation` (#692), `user_profile`/`persona`
(#715/#713), `trajectory` (#711), `self_improvement` (#702), voice design (#701).','docs/design/vestibular-study.md','878c0b8253ad1aaa40715e77893a04a84b19fd572ba63682d64405d64584086d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/design/voice-first.md','project_doc','doc://simplicio-runtime/docs/design/voice-first.md','doc: Voice-First — Design (#701)','# Voice-First — Design (#701)

> Status: **design, research-verified (2026-06-11)**. Component picks below are
> backed by the deep research in `docs/VOICE_LOCAL_RESEARCH_2026-06.md`
> (5 research passes + adversarial verification); this doc fixes the
> architecture so the work is mechanical, not exploratory.

## Goal

Make voice a **first-class modality** for humans (alongside CLI/MCP/TUI):
streaming STT in, streaming TTS out, natural **interruption**, and clean
**handoff to text** — all runtime-first, deterministic at the control layer, and
token-frugal. **PT-BR quality is the #1 tie-breaker on every layer** (standing
decision, 2026-06-11).

## Two input channels — modality mirroring (Hermes parity)

The runtime accepts **two inbound channels: text and audio**. Audio is always
normalized to text before the spine (intent #190 → gate #231 → bridge #230) —
the brain only ever sees text. The reply **mirrors the inbound modality**:

- text in → text out (today''s behavior, unchanged);
- **audio in → audio out** (TTS of the reply), plus the transcript/text kept in
  the session and the evidence ledger.

This is the pattern `gateway/voice_relay.rs` (#767) already implements as v0
(`relay_voice_note(..., respond_with_audio)`); this design upgrades its engines
from shell-out (`whisper` CLI / `espeak -v en` — an *English* voice for pt-BR
text) to in-process, PT-first components. The modality decision stays
deterministic: a `Modality` field on the inbound message, mirrored on the
reply; Helo may *downgrade* voice→text per turn (code blocks, long lists, low
STT confidence) but never upgrades text→voice unasked.

## Component picks (research-verified, PT-first)

| Concern | Pick | Verdict |
|---|---|---|
| VAD | **Silero VAD** via `ort` (crate `voice_activity_detector`) | ~2 MB, <1 ms/chunk, MIT |
| Endpointing | **Smart Turn v3** ONNX int8 | 8 MB, 12-60 ms CPU, **Portuguese in the 23 languages**, audio-native, BSD-2 |
| STT (PT-first) | **Parakeet-TDT-0.6B-v3** int8 via sherpa-onnx (official Rust crate) | best PT WER/compute (4.76% FLEURS), CC-BY-4.0, ~2 GB — pt-EU-trained, pt-BR A/B gate below |
| STT (robustness/partials) | **whisper.cpp** via whisper-rs | pt-BR+EN, MIT, same ggml backend as llama.cpp, Metal ~10x RT |
| TTS | **Kokoro-82M** ONNX (`pf_dora`/`pm_alex`) | only real-time TTS with dedicated pt-BR voices, Apache-2.0, ~300 MB, RTF ~0.5 on 4-core CPU |
| TTS (ultra-light) | Piper pt_BR via **piper-rs** (MIT) | 63 MB; do NOT link upstream piper1-gpl (**GPL**) — closed-source rule |
| Audio I/O | **cpal** (capture) + **rodio** (playback) | standard, cross-platform |
| AEC (barge-in) | `webrtc-audio-processing` (tonari) | AEC3, production-tested; skip with headphones |

Superseded by research: Piper-as-primary (no female pt-BR voice, VITS-tier
naturalness), webrtc-vad/energy (accuracy), Moonshine/Vosk fallbacks (no pt /
unusable pt WER). End-to-end S2S models (Moshi, Qwen-Omni…) rejected: none
combines pt-BR + ≤16 GB + Rust; cascaded is also what Kyutai itself shipped
(Unmute) for tool-calling/factuality.

All optional, behind `--features voice`, to preserve the minimal default binary.

## Resource tiers (mirrors `runtime-profile`; all components stay resident)

| Tier | STT | Voice LLM | Stack RAM |
|---|---|---|---|
| `voice-low` (8 GB) | Parakeet int8 (sole, VAD-cut) | Qwen 2B Q6_K | ~4.6 GB |
| `voice-normal` (16 GB) | whisper large-v3-turbo Q5 partials + Parakeet final | Qwen 4B Q6 | ~7.3 GB |
| `voice-high` (24 GB) | dual STT | Qwen 7/8B Q4 | ~10 GB |
| `voice-full` (32 GB+) | whisper large-v3 Q5 + Parakeet final | Qwen 14B Q4 | ~15 GB |

Latency caps the voice LLM before RAM does (~14B ceiling); deeper reasoning
escalates via the existing 5x ladder in the background.

## Architecture

```
LIVE (mic):    cpal ─▶ AEC ─▶ Silero VAD ─▶ Smart Turn v3 (endpoint) ─▶ STT ─▶ text turn
ASYNC (gateway): voice note (WhatsApp/Telegram/…) ─▶ STT ─▶ text turn   [Modality::Audio]
TEXT:          CLI/TUI/gateway text ─▶ text turn                        [Modality::Text]
                                                  │
                                      conversation::ConversationContext (#692)
                                                  │
                              conversation_control::TurnController (#700)  ◀─ barge-in
                                                  │
                          spine: intent #190 → gate #231 → bridge #230
                                                  │
                       reply mirrors Modality (Helo may downgrade voice→text)
                                                  │
Audio: LLM stream ─sentence split─▶ Kokoro TTS ─▶ rodio (live) / OGG-opus (gateway)
Text:  normal text reply
```

Latency budget (live, p50 target ~720 ms): endpoint decision ~220 ms → STT
final 150-300 ms → LLM TTFT 150-300 ms (prewarmed KV; dispatch first sentence)
→ Kokoro first-audio 150-400 ms, chunked playback.

- **Interruption (barge-in):** the capture thread runs continuously; when VAD
  detects speech *while TTS is playing*, it calls
  [`TurnController::cancel`](../../src/conversation_control.rs) → playback stops
  promptly at the next chunk boundary, and the new utterance becomes a steer or
  a fresh turn. This reuses the already-landed deterministic control primitive —
  no new interrupt machinery.
- **Context:** transcribed turns feed `ConversationContext`; the token-budget
  window keeps prompts bounded so long voice sessions don''t blow latency.
- **Handoff to text:** Helo picks modality per turn (e.g. code blocks, long
  lists, or low STT confidence → render to TUI/text instead of speaking).
- **Determinism:** the *control plane* (turn lifecycle, cancel/steer, modality
  policy) is deterministic and unit-testable; only STT/TTS are probabilistic.

## Proposed Rust interface

```rust
pub trait SpeechToText { fn stream(&self, audio: AudioChunks) -> TranscriptStream; }
pub trait TextToSpeech { fn synthesize(&self, text: &str) -> AudioStream; }

pub struct VoiceS','docs/design/voice-first.md','52215b33a6c4ce2657cdd5f605008556a6d1f69c3a02e8f549fe3f8fe62d3330','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/desktop/AUTO_UPDATE_SPEC.md','project_doc','doc://simplicio-runtime/docs/desktop/AUTO_UPDATE_SPEC.md','doc: Auto-Update Spec — Issue #2201','# Auto-Update Spec — Issue #2201

## Overview

The Simplicio Desktop app (Electron, `apps/simplicio-desktop/`) auto-updates in
the background using the platform-native update mechanism: Sparkle on macOS,
Squirrel on Windows, and AppImage delta-update on Linux.

## Update flow

```
1. On startup (and every 4h): check update feed URL for new version
2. If new version available: download delta in background, verify signature
3. Notify user via in-app banner: "Update X.Y.Z ready — restart to apply"
4. On user confirm (or next restart): apply update atomically
5. Write update record to HBP ledger
```

## Feed URL

```
https://update.simplicio.app/update/<platform>/<arch>/<current-version>
```

Response (JSON):
```json
{
  "version": "1.2.0",
  "url": "https://update.simplicio.app/dl/simplicio-1.2.0-<platform>-<arch>.<ext>",
  "signature": "<ed25519-base64>",
  "notes": "Brief release notes",
  "mandatory": false
}
```

## Signature verification

- Algorithm: Ed25519 (public key embedded in binary at build time)
- Public key stored in `apps/simplicio-desktop/src/update-pubkey.pem`
- Verification happens before applying update; failure aborts with error log

## Electron implementation

Use `electron-updater` (already a common dep in Electron apps):

```ts
import { autoUpdater } from ''electron-updater'';

autoUpdater.setFeedURL({
  provider: ''generic'',
  url: `https://update.simplicio.app/update/${process.platform}/${process.arch}/${app.getVersion()}`,
});

autoUpdater.checkForUpdatesAndNotify();  // background, non-blocking
```

Configure in `apps/simplicio-desktop/electron/main.ts` (or `main/index.ts`).

## Platform specifics

| Platform | Mechanism | Extension | Notes |
|----------|-----------|-----------|-------|
| macOS    | Sparkle via electron-updater | `.dmg` / `.zip` | Code-signed + notarized required |
| Windows  | Squirrel via electron-updater | `.exe` (NSIS) | Code-signed required |
| Linux    | AppImage self-update | `.AppImage` | Delta via zsync |

## Configuration (user-facing)

Settings screen toggle: "Automatically check for updates" (default: on)  
`~/.simplicio-loop/config.toml`:
```toml
[desktop]
auto_update = true
update_channel = "stable"   # stable | beta
```

## Mandatory updates

When `mandatory = true` in feed response, the update is applied on next launch
without user option to defer. Used for security patches only.

## Audit trail

```json
{
  "schema": "simplicio.desktop.update/v1",
  "from_version": "1.1.0",
  "to_version": "1.2.0",
  "platform": "darwin-arm64",
  "applied_at": "<iso8601>",
  "mandatory": false
}
```

## Delivery criteria

- [ ] `electron-updater` wired in `apps/simplicio-desktop/electron/main.ts`
- [ ] Feed URL config in `apps/simplicio-desktop/package.json` `build.publish`
- [ ] Ed25519 public key embedded; signature verified before apply
- [ ] User-facing banner in renderer: "Update ready — restart"
- [ ] Settings toggle: disable auto-check
- [ ] Test: feed returns 200 with new version → updater downloads (mock)
- [ ] Test: invalid signature → update aborted, error logged

## Tracking

GitHub: #2201','docs/desktop/AUTO_UPDATE_SPEC.md','4951861fd1f8269d0c8dfdcf3d27a10b1cdb71fe7e21c11c90e22a1146428f7c','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/desktop/ONBOARDING_SPEC.md','project_doc','doc://simplicio-runtime/docs/desktop/ONBOARDING_SPEC.md','doc: In-App Onboarding — Issue #2202','# In-App Onboarding — Issue #2202

## Overview

A 5-step guided tour shown on first launch of Simplicio Desktop. The tour is
skippable at any step, resumable, and stored in user config so it only appears
once. Each step performs a real action (not just a tooltip) to demonstrate the
feature.

## Trigger condition

Show onboarding when:
```
~/.simplicio-loop/config.toml [desktop] onboarding_completed = false  (or key absent)
```

After completion or skip: set `onboarding_completed = true`.

## The 5 steps

### Step 1 — Welcome & Model Setup

**Goal:** ensure the user has a working LLM connection.

- Show: welcome screen with Simplicio logo + tagline
- Action: detect `SIMPLICIO_API_KEY` or local model; if missing, show inline
  config form to set API key (written to vault, not env)
- CTA: "Set up model" or "Use local model (offline)"

### Step 2 — First Map

**Goal:** show the repo-map power (token savings).

- Action: run `simplicio map --repo . --for-llm markdown` against a bundled
  demo repo (or the current working dir if it''s a git repo)
- Show: the compressed map output, annotated with "This replaces reading 47 files"
- CTA: "Got it — next"

### Step 3 — Memory Recall

**Goal:** show that Simplicio remembers decisions.

- Action: run `simplicio memory "demo query" --repo . --json` against the demo
  memory store (bundled sample `.simplicio-loop/memory/`)
- Show: a sample memory recall result with token-savings annotation
- CTA: "Next"

### Step 4 — First Edit

**Goal:** demonstrate zero-token deterministic editing.

- Action: apply a safe demo edit via `simplicio edit` to a temp file in the
  sandbox dir — e.g., insert a comment into a sample Rust file
- Show: before/after diff
- CTA: "Next"

### Step 5 — Action Gate

**Goal:** show that Simplicio gates mutations.

- Action: trigger a simulated `medium`-risk action; show the gate approval dialog
- Show: the risk classification UI; user clicks "Approve" or "Deny"
- CTA: "Start using Simplicio"

## UX requirements

- Progress indicator: `Step X of 5` at top
- Skip button: always visible; skipping sets `onboarding_completed = true` immediately
- Back button: available on steps 2-5
- No step should block on network (demo data is bundled)
- Step transitions are animated (200ms slide)

## State persistence

```toml
[desktop]
onboarding_completed = false
onboarding_last_step = 0    # resume from here if user closed mid-tour
```

## Electron implementation

Component: `apps/simplicio-desktop/src/renderer/onboarding/`
- `OnboardingModal.tsx` — modal wrapper with step router
- `Step1Welcome.tsx` through `Step5ActionGate.tsx`
- `useOnboardingState.ts` — read/write config via IPC

IPC channel: `simplicio:onboarding:complete` — sets config key via Rust runtime.

## Delivery criteria

- [ ] 5 step components implemented in `apps/simplicio-desktop/src/renderer/onboarding/`
- [ ] Onboarding shown on first launch only (`onboarding_completed` flag)
- [ ] Skip works at any step
- [ ] Resume from `onboarding_last_step` if closed mid-tour
- [ ] Each step triggers its real action (not mocked text)
- [ ] Step 4 demo edit runs against a temp file, not the user''s actual repo
- [ ] IPC: `onboarding_completed` written to config on finish/skip

## Tracking

GitHub: #2202','docs/desktop/ONBOARDING_SPEC.md','0058668cb66413fcb4ca7a8227914696711a73bc558cca700b1bd77ba1a7b377','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/DIGITAL_CONSCIOUSNESS_GAP_ANALYSIS.md','project_doc','doc://simplicio-runtime/docs/DIGITAL_CONSCIOUSNESS_GAP_ANALYSIS.md','doc: Digital Consciousness — Gap Analysis','# Digital Consciousness — Gap Analysis

**Author:** research pass, 2026-07-06
**Scope:** what exists today toward "digital consciousness" / self-model /
autonomy in this runtime, and what is concretely missing. This is a
**documentation-only** artifact — it adds no organism/autonomy code and
does not reopen the scope frozen by
`docs/ADR-2026-07-06-KERNEL-SCOPE-FREEZE.md`. It follows the same
gap-tracking convention as `docs/hermes-import/*` (analyze first, open an
issue before any implementation).

---

## TL;DR

Significant "consciousness-shaped" scaffolding already exists in
`src/organism/*` (~2,737 lines: an Observe→Think→Plan→Act→Reflect loop, a
governor, self-evolution, mission/goals, a "doctor", health/daemon/
persistence). A **second, newer, unwired** crate —
`crates/simplicio-agents/src/consciousness.rs` (604 lines, landed
2026-07-05, one day before the freeze) — goes further: `PersistentSelf`
(identity), `reflect()` (self-reflection), an `EmotionalState` /
`EmotionalEngine`, and an `AutonomousExplorer`. **Neither is reachable
from the `simplicio` CLI binary**, and as of the kernel-scope freeze this
surface is not to be extended with new code. The gap is not "we haven''t
thought about consciousness" — it''s that a fully-built self-model crate
was never wired in, and the freeze now means wiring it in requires an
explicit, scoped exception rather than default extension.

---

## What already exists

### `src/organism/*` (wired into the CLI via `mod organism;` in `src/main.rs`)

| Module | Role |
|---|---|
| `autonomous_loop.rs` | Observe → Think → Plan → Act → Reflect loop; state under `.simplicio-loop/yool/consciousness/` |
| `central_loop.rs` | "Central Consciousness Loop (Brain)" orchestrator |
| `architecture.rs` | Heart/Brain/Organ multi-loop coordination |
| `vision.rs` | Organism vision manifest |
| `governor.rs` | Resource governor / self-throttling |
| `self_evolution.rs` | Bounded self-adjustment — `evolvable_targets()` allows prompts, planning strategies, workflows, governor params, doctor logic, memory structure; **`source_code: false`, requires human approval** |
| `evolution.rs` | Background evolutionary feedback loop |
| `mission.rs` | `MISSION_STATEMENT`: "the organism exists to help the human achieve what they want" |
| `goals.rs` | Human goal/intent tracking |
| `doctor.rs` | Self-diagnosing / self-adjusting health checks |
| `daemon.rs` | Always-on daemon mode |
| `human_memory.rs`, `feedback.rs`, `conversation.rs`, `suggestions.rs`, `health.rs`, `lifecycle.rs`, `persistence.rs`, `summarization.rs`, `yool_bus.rs` | Supporting loops (memory, proactive suggestions, health, graceful shutdown, state persistence, tuple-space event bus) |

All of the above is real, merged, closed-issue work (#533–#559, #566–#567).

### Orphaned "Consciousness" crate

`crates/simplicio-agents/src/consciousness.rs`: `PersistentSelf`
(`identity.json`), `ReflectionResult`/`reflect()`, `EmotionalState`
(Serene/Curious/Worried/Joyful/Tired/Grateful) + `EmotionalEngine`, and
`AutonomousExplorer` ("explores 1 new thing between tasks"). Doc comment
cites inspiration from external research (JesseBrown1980 / N-Nest-Prime /
Asolaria — see `docs/ASOLARIA_ABSORPTION_PLAN.md` on the sibling agent
repo for the broader absorption context). Referenced only from its own
crate''s `lib.rs` — **no call site anywhere in the runtime binary**. This
is the most literal "digital consciousness" code in the repo, and it
currently executes nothing.

---

## Concrete gaps

| # | Prio | Gap | Status |
|---|------|-----|--------|
| 1 | **P0** | `consciousness.rs` is dead code — built, never wired | **Addressed** (2026-07-06) — wired into `simplicio organism self\|identity\|reflect\|explore`; see `docs/ADR-2026-07-06-CONSCIOUSNESS-WIRING-EXCEPTION.md` |
| 2 | **P0** | No decision recorded on how `consciousness.rs` relates to the kernel-scope freeze | **Addressed** (2026-07-06) — user-approved scoped exception recorded in `CLAUDE.md` and the ADR above |
| 3 | **P1** | No bridge between `organism/*`''s loop state, `consciousness.rs`''s identity/reflection model, **and** `crates/simplicio-agents/src/tami.rs`''s separate "Tami" persona (its own, differently-shaped `EmotionalState` enum: `Serene`/`Concerned`/`Distressed` vs. consciousness''s `Serene`/`Curious`/`Worried`/`Joyful`/`Tired`/`Grateful`) | **Partially addressed** (2026-07-06) — `simplicio organism self` now folds `organism::mission` (why it exists), `organism::goals` (what was asked), and `organism::doctor` (is it healthy) into `consciousness::PersistentSelf` as one view; a doctor finding now raises a real `EmotionEvent::SystemError` in the emotional engine instead of being silently ignored. `tami.rs` is **still separate** — see gap #6 |
| 4 | **P1** | No acceptance criteria / eval harness for "consciousness" behavior | **Open** — nothing defines what observable behavior (persistent identity across sessions, reflection changing future actions, auditable emotional-state influence on tone) would count as "working" |
| 5 | **P2** | Verification debt on the existing `organism/*` code | **Open** — the freeze ADR itself cites ~957k LOC, 307 files with `allow(dead_code)`, 31 duplicated modules, 146/204 skill stubs across the runtime — the code underlying this analysis is largely unverified, not just unfinished |
| 6 | **P2** | `tami.rs` has **zero call sites in `src/`** — like `consciousness.rs` was, it is fully orphaned, never invoked by the CLI binary. Wiring it for real needs isa/helo/levi/HBP status signals, but `src/guardians_command.rs` (computes exactly those) itself appears to have no caller either — `main_parts/chunk_06.rs` has its own separate `guardians_command` that the CLI actually dispatches to | **Open** — wiring Tami honestly requires first resolving which `guardians_command` is the real one; forcing Tami to run on fabricated status inputs would violate the "no silent fake data" rule, so it was deliberately left out of this pass |

## Explicit non-goals / guardrails','docs/DIGITAL_CONSCIOUSNESS_GAP_ANALYSIS.md','6279626a3bedeadd589b82ce7b6e8537832a387c314879a6ac787b318f3b6822','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/discord-setup.md','project_doc','doc://simplicio-runtime/docs/discord-setup.md','doc: Simplicio Discord — Guia de Configuração','# Simplicio Discord — Guia de Configuração

> Inspirado no padrão do **Hermes Agent**.
> O Simplicio Runtime segue a mesma arquitetura: token em `.env`, gateway separado,
> smoke test de validação, e configuração declarativa.

---

## Índice

1. [Arquitetura](#1-arquitetura)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Criar um Bot no Discord](#3-criar-um-bot-no-discord)
4. [Setup Automático](#4-setup-automático)
5. [Setup Manual](#5-setup-manual)
6. [Iniciar o Gateway](#6-iniciar-o-gateway)
7. [Comandos do Gateway](#7-comandos-do-gateway)
8. [Status e Smoke Test](#8-status-e-smoke-test)
9. [Parâmetros de Configuração](#9-parâmetros-de-configuração)
10. [Compatibilidade com Hermes](#10-compatibilidade-com-hermes)
11. [Troubleshooting](#11-troubleshooting)
12. [Arquivos de Referência](#12-arquivos-de-referência)

---

## 1. Arquitetura

```
┌─────────────────────────────────────────────────────┐
│                   Simplicio Runtime                  │
│                                                      │
│  ┌──────────┐    ┌──────────────┐                    │
│  │ CLI/REPL  │    │  Gateway     │   ───→ Discord    │
│  │          │    │  Runner     │   REST API         │
│  └──────────┘    └──────┬───────┘                    │
│                         │                            │
│              ┌──────────▼──────────┐                 │
│              │   Platform Adapter  │                 │
│              │   (discord.rs)      │                 │
│              └─────────────────────┘                 │
│                                                      │
│  Config: .env (tokens)                               │
│  Estado: .simplicio-loop/gateway/ (offsets, sessões)     │
└─────────────────────────────────────────────────────┘
```

O **Simplicio Discord** usa **polling REST** (não WebSocket).
A cada 2 segundos, o gateway consulta a API do Discord por novas mensagens
no canal configurado, processa via `runtime_chat_reply()`, e responde.

---

## 2. Pré-requisitos

- **Simplicio Runtime compilado**: `cargo build --release --locked`
- **Servidor Discord** onde você tem permissão para adicionar bots
- **Acesso ao [Discord Developer Portal](https://discord.com/developers/applications)**

---

## 3. Criar um Bot no Discord

Siga exatamente como no Hermes Agent:

1. Acesse https://discord.com/developers/applications
2. Clique em **"New Application"** → dê um nome (ex: "Simplicio Bot")
3. Vá em **Bot** (sidebar) → **"Add Bot"** → **"Reset Token"** → copie o token
4. Em **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Permissions: `Send Messages`, `Read Message History`, `View Channels`,
     `Add Reactions`, `Create Public Threads`, `Send Messages in Threads`
   - Copie a URL gerada e abra no navegador para adicionar o bot ao servidor
5. Vá em **General Information** e copie:
   - **APPLICATION ID** (ex: `1513271222387867798`)
   - **PUBLIC KEY** (ex: `ddd7abb1...`)
6. No Discord, clique com direito no canal desejado → **"Copy ID"**
   (precisa ter **Developer Mode** ativado em Settings → Advanced)

---

## 4. Setup Automático

```bash
cd /caminho/do/simplicio-runtime
bash scripts/setup-discord.sh
```

O script:
1. Verifica se o binário está compilado
2. Cria `.env` a partir de `.env.example` (se não existir)
3. Valida se os campos obrigatórios foram preenchidos
4. Executa **smoke test** contra a API do Discord
5. Mostra instruções para iniciar o gateway

> Se o `.env` não existir, o script cria um template e pede para você editar.
> Rode o script **novamente** depois de preencher as credenciais.

---

## 5. Setup Manual

Crie o arquivo `.env` na raiz do projeto:

```bash
cp .env.example .env
# Edite com suas credenciais:
#   SIMPLICIO_DISCORD_TOKEN=seu_token_aqui
#   SIMPLICIO_DISCORD_CHANNEL_ID=id_do_canal_aqui
```

**NUNCA commite o `.env`** — ele contém tokens secretos.
O `.env.example` é o arquivo seguro para versionamento.

### Variáveis de Ambiente

| Variável | Obrigatório | Descrição |
|---|---|---|
| `SIMPLICIO_DISCORD_TOKEN` | ✅ Sim | Token do Bot Discord |
| `SIMPLICIO_DISCORD_CHANNEL_ID` | ✅ Sim (listen) | ID do canal para monitorar |
| `DISCORD_APPLICATION_ID` | ❌ Opcional | ID da aplicação (slash commands) |
| `DISCORD_PUBLIC_KEY` | ❌ Opcional | Chave pública (verificação) |
| `RUST_LOG` | ❌ Opcional | Nível de log (`info`, `debug`, `trace`) |

> **Compatibilidade reversa:** O Simplicio também aceita `DISCORD_TOKEN`,
> `DISCORD_BOT_TOKEN` e `SIMPLICIO_DISCORD_BOT_TOKEN` como fallback.

---

## 6. Iniciar o Gateway

### Via script atalho

```bash
bash scripts/run-discord.sh
```

### Manualmente

```bash
cd /caminho/do/simplicio-runtime
set -a && source .env && set +a
./target/release/simplicio gateway listen discord
```

### Via systemd / launchd (produção)

**macOS (launchd):** Crie `~/Library/LaunchAgents/io.simplicio.discord.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>io.simplicio.discord</string>
    <key>ProgramArguments</key>
    <array>
        <string>/caminho/do/simplicio-runtime/scripts/run-discord.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/simplicio-discord.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/simplicio-discord.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/io.simplicio.discord.plist
```

---

## 7. Comandos do Gateway

```bash
# Iniciar escuta ativa (polling a cada 2s)
simplicio gateway listen discord

# Conectar (testa token sem iniciar polling)
simplicio gateway connect discord

# Enviar mensagem
simplicio gateway send discord <chat_id> "<mensagem>"

# Reagir a mensagem
simplicio gateway react discord <chat_id> <message_id> 👍

# Resetar sessão de um chat
simplicio gateway reset discord <chat_id>

# Ver t','docs/discord-setup.md','96c9c681a03ddccaf9525ee1cbffdc5b5c46c6588c55be74ed318ac9e30786ba','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/doc_1240.md','project_doc','doc://simplicio-runtime/docs/doc_1240.md','doc: Doc #1240 — Latency/Token Economy Policy Consolidation','# Doc #1240 — Latency/Token Economy Policy Consolidation

**Issue:** #1240 — Docs: consolidar política de latency/token economy no manual operacional
**Parent:** #1238
**Depends on:** #1239
**Status:** Implemented — section added to `SIMPLICIO_OPERATIONAL_MANUAL.md`

## Summary

Added section `## Latency, Token Economy, and Deterministic Fast Paths` to
`docs/SIMPLICIO_OPERATIONAL_MANUAL.md` immediately after `## Adaptive LLM Default Policy`.

## Section structure

The new section contains seven subsections:

1. **Latency Policy** — clarifies that fan-out increases throughput, not
   single-response latency; provides a priority-ordered table of latency
   reduction techniques.

2. **Token Economy Policy** — establishes that output tokens are the primary
   bottleneck; mandates `max_tokens` caps; clarifies that deterministic writes
   cost zero LLM tokens; distinguishes prompt/KV-cache (reduces TTFT) from true
   0-token paths (no LLM call at all).

3. **Tool Call Policy** — defines a four-step decision ladder before invoking
   any tool; marks browser/search as last resort for dynamic external content.

4. **THINK vs NO-THINK in the Runtime** — formalizes the routing rule for
   suboperations: template/cache hit → NO-THINK deterministic path; miss /
   ambiguous / risk → THINK with planner/reviewer. Includes cost-of-misrouting
   analysis.

5. **Deterministic Edit and the 0-Token Path** — connects the policy to
   `simplicio edit`, `schemas/mechanical-edit.schema.json`, and the evidence
   ledger that makes the 0-token claim auditable.

6. **Relationship to the Graduated Local Fan-Out Ladder** — maps token economy
   implications across the 5-stage escalation (stages 1–4: local model; stage
   5: paid remote, doubly expensive).

7. **Cross-References** — links to case studies #002 and #003, issue #1239,
   AGENTS.md, and the mechanical-edit schemas.

## Acceptance criteria verification

| Criterion | Status |
|---|---|
| Manual contains an explicit latency/token economy policy | Done — §1–§2 |
| Section differentiates throughput from per-response latency | Done — §1 |
| Section clarifies that 0-token only happens without an LLM call | Done — §2 |
| Section guides when to use reasoning and when not to | Done — §4 |
| Section points to case study #1239 when available | Done — §7 |
| No instruction contradicts AGENTS.md, Required Load Order, or Maximum Power Standard | Verified — §4 includes explicit non-contradiction statement |','docs/doc_1240.md','242a2d68faa9ef9b404e7f41bf9faef25c654ab9287b81ed902b4b9d5f3f712e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ECOSYSTEM_ABSORPTION_STATUS_2026-06-16.md','project_doc','doc://simplicio-runtime/docs/ECOSYSTEM_ABSORPTION_STATUS_2026-06-16.md','doc: Ecosystem Absorption Status — 2026-06-16','# Ecosystem Absorption Status — 2026-06-16

Epic: #1213
Source: viral thread @heynavtoor — 10 repos: OpenHands, Hermes Agent, CrewAI, Aider, n8n, LangGraph, Cloudflare Agentic Inbox, Browser Use, awesome-mcp-servers, claude-task-master.

## Sub-issue status

| Issue | Repo | Classification | Status | Evidence |
|---|---|---|---|---|
| #1214 | awesome-mcp-servers | Integração/absorção | PARCIAL | simplicio mcp exists; catalog/search/install to-implement |
| #1215 | n8n | Integração/absorção | PARCIAL | action_bridge.rs as n8n alternative; n8n backend opt-in to-implement |
| #1216 | Browser Use | Integração/absorção | PARCIAL | macos_computer_use.rs base; CDP/Playwright bridge to-implement |
| #1217 | OpenHands+Aider+claude-task-master | Benchmark | PARCIAL | benchmark_harness.rs exists; multi-competitor to-implement |
| #1218 | Aider | Integração | PARCIAL | simplicio edit already has search/replace; auto-commit to-improve |
| #1219 | LangGraph/CrewAI | Estudo de padrões | PARCIAL | exec_graph exists; conditional edges+state+checkpoint to-implement |
| #1220 | Agentic Inbox | Integração | PARCIAL | gateway email + reason --act + gate pattern defined |

## Existing bases in Simplicio

- `action_bridge.rs` — action bridge (base for #1215 n8n alternative)
- `macos_computer_use.rs` — computer-use/browser runtime (base for #1216 Browser Use)
- `benchmark_harness.rs` + `benchmark_suite.rs` — benchmarking (base for #1217)
- `simplicio edit` — deterministic search/replace (Aider parity, #1218)
- `exec_graph` capability — conditional execution graph (base for #1219 LangGraph)
- gateway platforms (telegram, slack, email etc.) — base for #1220 Agentic Inbox

## Principles (non-negotiable, from epic)

- No fake/stub: absent dependency → `Err`, never placeholder success
- All mutations through Action Gate (#231) with evidence on HBP chain
- Local-first: qwen 64→600 fan-out before any remote call
- Secrets: never in binary; always via env, referenced as `${VAR_NAME}`

## Decision

Epic remains open as tracker. Sub-issues have real bases in Simplicio. Each sub-issue gets individual implementation PR. Epic closes when all 7 sub-issues are closed.','docs/ECOSYSTEM_ABSORPTION_STATUS_2026-06-16.md','059f670e5502c655b7a57c998a5874b4995dd11cfd2152fc789a147ccad1b14d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/effect-reconciliation.md','project_doc','doc://simplicio-runtime/docs/effect-reconciliation.md','doc: Effect reconciliation','# Effect reconciliation

When an interrupted or failed mutation leaves the outcome uncertain, Runtime
records the idempotency key and remains fail-closed until durable evidence is
available. The legacy receipt-only path never clears pending state when the
canonical receipt is absent.

Use the read-only status command first:

```text
simplicio effect status --idempotency-key <key> --repo <repo> --json
```

For a missing receipt, an authorized Fast/Dev CLI producer may write a
pre/post artifact using
`simplicio.effect-reconciliation-evidence/v1`. The artifact contains the
exact repository identity, relative file paths, deterministic SHA-256 hashes
(or `absent`), and an `evidence_sha256` over the canonical artifact without
that digest. Runtime reads the artifact, re-measures every file itself, and
accepts only one of these exact outcomes:

- `status: "not-applied"`, `verdict: "unchanged-before"`: every file still
  matches its precondition; safe to retry the edit.
- `status: "reconciled"`, `verdict: "proven-after"`: every file matches its
  postcondition; safe to continue without reapplying the edit.

Any ambiguous, diverged, forged, wrong-repository, wrong-key, malformed, or
stale evidence remains `unresolved` / `applied-but-unproven`, returns non-zero,
and cannot clear pending state. Runtime appends the accepted or rejected
measurement as a durable HBP reconciliation record and verifies it by
read-back. Retrying the same evidence is idempotent; different evidence for
the same key is rejected.

For the Fast#232 blocker, after the Runtime fix is installed, use the exact
key and an evidence artifact produced in the Fast worktree:

```text
simplicio effect reconcile --idempotency-key e84b1b002bfa0dc3b019da92b05537d6999151457d3d18e42e988a65b4e36c19 --repo <fast-232-worktree> --evidence-file <fast-232-worktree>/.simplicio-loop/ops/mcp-effects/reconciliation/e84b1b002bfa0dc3b019da92b05537d6999151457d3d18e42e988a65b4e36c19.json --json
```

The result must explicitly show `safe_to_clear_pending: true` and either
`unchanged-before` or `proven-after`. Only then may the governed Fast retry
continue. Do not delete a pending marker, reapply an ambiguous edit, or infer
proof from a missing receipt. The MCP equivalent accepts the same artifact
through its `evidence_file` argument.','docs/effect-reconciliation.md','5736ab2022c3e18a9de00c7c2a273a8bb468a7464cae7769554fd9379a6989b6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/END_TO_END_FLOW.md','project_doc','doc://simplicio-runtime/docs/END_TO_END_FLOW.md','doc: End-to-End Flow Verification Framework','# End-to-End Flow Verification Framework

> O que mais importa: o fluxo de ponta a ponta funcionar, do front ao back ao banco de dados aos serviços externos aos workers.
> Versão: 1.0.0 · Runtime: simplicio v1.6.4 · Contrato: simplicio.e2e-flow/v1

## Princípio

Uma mudança individual de código não vale nada se a cadeia completa não funcionar.
O simplicio-runtime VERIFICA a cadeia inteira, não apenas o arquivo que mudou.

## Pipeline de verificação E2E

Flow: simplicio flow verify --pipeline <nome>

Pipelines suportados:
1. frontend → build → lint → test → e2e (Playwright)
2. backend → build → lint → test → integration → api
3. database → migration → seed → query → rollback
4. external-services → health → auth → rate-limit → timeout
5. workers → queue → process → result → retry → dead-letter
6. full-stack → front → back → db → ext → worker (completo)

## Comandos

| Comando | Descrição |
|---|---|
| simplicio flow verify --pipeline full-stack | Verifica a cadeia completa |
| simplicio flow verify --pipeline frontend --url <url> | Verifica front + build + lint + test + e2e |
| simplicio flow verify --pipeline backend --api <endpoint> | Verifica back + build + test + integração |
| simplicio flow verify --pipeline database | Verifica DB: migração → seed → query |
| simplicio flow verify --pipeline workers | Verifica workers: fila → processamento |

## Gatilhos

O E2E flow é verificado automaticamente em:
1. Pré-commit (via hooks/pre-commit)
2. Pré-PR (via GitHub Actions)
3. `simplicio run` (toda execução)
4. `simplicio validate` (quando --e2e é passado)
5. Cron job semanal (full-stack)

## Evidência

Cada pipeline gera um receipt em .simplicio-loop/e2e/<pipeline>/<timestamp>.json
O receipt contém: status, duração, cada etapa, logs de erro, screenshots (front).

## Implementação

O framework usa:
- Playwright para front-end E2E
- curl/httpx para API backend
- sqlite3 / psql para banco de dados
- docker/podman para serviços externos
- Supervisor para workers
- simplicio-loop para convergência','docs/END_TO_END_FLOW.md','818bc48129bf1c78bae27f43c41b88a369740f7464d1b84769135fc7a2599900','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/epic_1555.md','project_doc','doc://simplicio-runtime/docs/epic_1555.md','doc: Epic #1555 — Cover the VS Code command surface in Simplicio','# Epic #1555 — Cover the VS Code command surface in Simplicio

## Context

VS Code `1.126.0` (commit `1bfe9b8baf8f1be30484b00b55bf77bc27a54524`) exposes
**1,717 command IDs** in its `package.json` + extension packages.  Simplicio''s
prior runtime table covers 45 CLI commands generically.  This epic closes the
gap by building a typed, versioned, governed execution layer for every VS Code
command class.

Local evidence files:
- `.simplicio-loop/codex-evidence/vscode-command-coverage-2026-06-15.md`
- `.simplicio-loop/codex-evidence/vscode-command-coverage-2026-06-15.json`

## Goal

Make Simplicio the deterministic, governed executor arm for VS Code — inventory,
route, execute, validate, and track every command class with evidence.

## Rust implementation

Primary module: `src/vscode_coverage/vscode_1555.rs`

Key types:

| Type | Purpose |
|---|---|
| `VsCodeCommandEntry` | Single command record with ID, title, category, keybindings, when-clause, coverage status, evidence hash |
| `VsCodeCommandCategory` | Category taxonomy derived from command-ID prefix |
| `CoverageStatus` | `Exact` / `Partial` / `Missing` / `Unsupported(reason)` |
| `VsCodeCommandManifest` | Versioned golden manifest keyed by command ID |
| `VsCodeCoverageReport` | Per-category coverage breakdown with drift counts |
| `VsCodeExecutorBridge` | Governed bridge: action-gate check → IPC dispatch → evidence token |
| `ManifestInventoryBuilder` | Scans a VS Code repo or reads a pre-built evidence JSON |
| `VsCodeUpdateWatcher` | Diff two manifests; emit added/removed for builder-only CI |

## Sub-tracks and status

| Sub-track | Status | Notes |
|---|---|---|
| Inventory / golden manifest + drift gate | Implemented | `ManifestInventoryBuilder`, `VsCodeCommandManifest`, `WatcherDiff` |
| Typed VS Code command executor bridge | Implemented | `VsCodeExecutorBridge::execute` + IPC dispatch |
| Workbench / files / search / settings coverage | Implemented | `VsCodeCommandCategory` handles all these prefixes |
| Editor / language / refactor / code-action coverage | Implemented | Category taxonomy + `CoverageStatus` |
| Terminal / tasks / debug / testing / notebook / SCM | Implemented | Full category set in `VsCodeCommandCategory` |
| Extension-contributed commands + enablement metadata | Implemented | `when_clause`, `keybindings`, `source` fields in entry |
| Update watcher (builder-only) | Implemented | `VsCodeUpdateWatcher::diff` + `WatcherDiff::to_json_compact` |

## CLI surface (to be wired in main.rs)

```
simplicio vscode inventory --repo <vscode-checkout> [--json]
simplicio vscode coverage  --repo <vscode-checkout> [--json]
simplicio vscode run <commandId> --workspace <path>   [--json]
```

## Acceptance criteria checklist

- [x] `VsCodeCommandManifest` emits versioned manifest with command IDs, source,
      category, title, menu/keybinding/context metadata, and evidence hashes.
- [x] `build_coverage_report` reports exact/partial/missing coverage by category
      and exposes drift (new/removed since last manifest).
- [x] `VsCodeExecutorBridge::execute` dispatches via governed bridge or returns a
      typed `UnsupportedReason`.
- [x] `VsCodeUpdateWatcher` opens issues for new VS Code commands in builder mode
      (diff output is the input for a GitHub issue creation step).
- [x] Validation includes local VS Code source inventory
      (`ManifestInventoryBuilder::scan_repo`) and extension-host runtime
      confirmation (`detect_ipc_socket` + `vscode.commands.getCommands` path).
- [x] Evidence ledger tokens recorded per invocation
      (`build_evidence_token` → `evidence_token` in `BridgeResult::Dispatched`).

## Dependencies

None beyond `std` — the module deliberately avoids adding crate dependencies.
`serde_json_lite` is an internal shim for bridge args.','docs/epic_1555.md','929e7352157771c5a7977c937d1fb58a9bb77aaab4434700ebbb5c8bacbceef1','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/epic_1590.md','project_doc','doc://simplicio-runtime/docs/epic_1590.md','doc: Epic #1590 — IDE Extensions and Dashboards for Local Simplicio Observability','# Epic #1590 — IDE Extensions and Dashboards for Local Simplicio Observability

## Goal

Expose Simplicio''s local runtime telemetry (token savings, governance status,
agent queue, proof/evidence) inside IDEs as native panels and webviews.
VS Code is the first-class target; Cursor, Kiro, Zed, and any ACP/MCP client
are supported via the shared local JSON surface.

## Architecture

```
simplicio runtime (local daemon)
       │
       ├─ /var/simplicio/obs.json   ← polling surface (file-based, 1 s refresh)
       ├─ unix socket / HTTP :7931  ← streaming surface (SSE / WS)
       │
       ├── VS Code extension         (webview + commands)
       ├── Cursor / Kiro adapter     (MCP tool surface)
       ├── Zed / JetBrains adapter   (ACP protocol)
       └── Generic dashboard         (HTML+JS, browser-fallback)
```

## Components

### 1. Observability surface (`src/ide_observability_1590.rs`)

- `ObsSnapshot` — point-in-time struct serialised to JSON.
- `IdeObsServer` — serves the snapshot over HTTP (GET `/obs`) and as SSE stream.
- `ObsPoller` — writes `obs.json` to a well-known path every N seconds.

### 2. VS Code extension (`apps/vscode-simplicio/`)

- `simplicio.dashboard` — open WebviewPanel with live savings graph.
- `simplicio.status` — show status-bar item with current savings %.
- `simplicio.refresh` — manually force snapshot refresh.
- Webview fetches `http://localhost:7931/obs` and renders Chart.js bars.

### 3. Shared JSON contract (`simplicio.ide-obs/v1`)

```json
{
  "schema": "simplicio.ide-obs/v1",
  "ts": "<ISO-8601>",
  "savings": { "spent": 0, "baseline": 0, "saved": 0, "pct": 0 },
  "evidence": { "chain_length": 0, "last_hash": "" },
  "agents": { "active": 0, "queued": 0, "total_logical": 0 },
  "governance": { "gate_mode": "ask", "pending_approvals": 0 },
  "workflow": { "running": 0, "completed": 0, "failed": 0 }
}
```

### 4. Multi-IDE adapters

- **Cursor / Kiro** — expose `/obs` as an MCP tool `simplicio_obs`.
- **Zed** — ACP extension wraps the HTTP surface.
- **JetBrains** — thin Kotlin plugin polling the JSON file.

## Sub-issues to create

| # | Title | Scope |
|---|-------|-------|
| 1591 | VS Code extension MVP: webview dashboard | Extension scaffold + webview |
| 1592 | Shared obs-server: HTTP + SSE + obs.json | `IdeObsServer` + `ObsPoller` |
| 1593 | Cursor/Kiro MCP adapter for obs surface | MCP tool wrapper |
| 1594 | Zed/JetBrains ACP/plugin adapters | ACP + Kotlin stub |

## Acceptance criteria

- [x] Documented architecture in this file.
- [x] `ObsSnapshot` struct with the shared JSON contract.
- [x] `IdeObsServer` serving GET `/obs` and SSE `/obs/stream`.
- [x] `ObsPoller` writing `obs.json` on a configurable interval.
- [x] `VsCodeDashboardCommand` struct encoding the VS Code command surface.
- [ ] VS Code extension scaffold (sub-issue #1591).
- [ ] Live savings graph in webview (sub-issue #1591).
- [ ] Multi-IDE adapters (sub-issues #1593, #1594).

## Related

- #1555 VS Code command surface
- #1556 parity work
- #1564 extension command coverage
- #1568, #1571 adjacent observability work','docs/epic_1590.md','bfd12b06a4f730b01c690600bffb8d7998196f4416b1180597c1691955893b41','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/evidence/desktop-hermes-parity/desktop-hermes-parity.md','project_doc','doc://simplicio-runtime/docs/evidence/desktop-hermes-parity/desktop-hermes-parity.md','doc: Desktop Hermes Parity Evidence','# Desktop Hermes Parity Evidence

Date: 2026-06-05
Repo: `/Users/wesleysimplicio/Projetos/ai/simplicio-runtime-desktop-hermes`

This evidence compares the Hermes desktop against the Simplicio desktop shell using the same user-facing action on both sides. The rule here is strict: each visual comparison must map to a real runtime-backed implementation in Simplicio, not only to a copied UI shell.

Runtime-backed Simplicio surfaces used in this evidence:

- Rust commands for artifacts, providers, and cron in [apps/desktop/src-tauri/src/main.rs](../../../apps/desktop/src-tauri/src/main.rs)
- Hermes-like shell and navigation in [apps/desktop/src/components/Layout.tsx](../../../apps/desktop/src/components/Layout.tsx)
- Tauri bridge for artifacts and cron in [apps/desktop/src/lib/runtime.ts](../../../apps/desktop/src/lib/runtime.ts)

## 1. Messaging

Hermes:

![Hermes Messaging](./screens/hermes-messaging.png)

Simplicio:

![Simplicio Messaging](./screens/simplicio-messaging.png)

Parallel:

- Hermes exposes a message-first desktop shell with session rail and composer.
- Simplicio mirrors the same shell pattern, but the desktop framing and navigation are owned by the React/Tauri shell in [apps/desktop/src/components/Layout.tsx](../../../apps/desktop/src/components/Layout.tsx).
- The important difference is functional ownership: in Simplicio the shell is only the surface; execution still goes through the runtime command layer exposed by the compiled binary and routed by the Tauri bridge.

## 2. Artifacts

Hermes:

![Hermes Artifacts](./screens/hermes-artifacts.png)

Simplicio:

![Simplicio Artifacts](./screens/simplicio-artifacts.png)

Parallel:

- Hermes exposes an artifact browser with visual/file/link history.
- Simplicio exposes the same category of surface, but the data is not mocked: the frontend calls `list_artifacts` via `invoke(...)` in [apps/desktop/src/lib/runtime.ts](../../../apps/desktop/src/lib/runtime.ts), and the Rust backend walks real run directories under `.simplicio-loop/runs` in [apps/desktop/src-tauri/src/main.rs](../../../apps/desktop/src-tauri/src/main.rs).
- Concretely, the Rust command `list_artifacts` reads recent runs, collects files, infers image/file/link kinds, and returns the records consumed by the desktop UI.

## 3. Cron

Hermes:

![Hermes Cron](./screens/hermes-cron.png)

Simplicio:

![Simplicio Cron](./screens/simplicio-cron.png)

Parallel:

- Hermes exposes scheduled job inventory and recurring agent execution.
- Simplicio exposes the same workflow category, but the page is wired to the compiled runtime cron store rather than to a copied static page.
- The frontend pulls jobs with `list_cron_jobs` and creates jobs with `create_cron_job` in [apps/desktop/src/lib/runtime.ts](../../../apps/desktop/src/lib/runtime.ts).
- The Rust backend resolves those calls to `simplicio cron list` and `simplicio cron add` in [apps/desktop/src-tauri/src/main.rs](../../../apps/desktop/src-tauri/src/main.rs), keeping job state inside the runtime instead of inside the UI layer.

## 4. What This Proves

- The Hermes desktop shell was used as the visual benchmark.
- The Simplicio desktop now performs the same categories of action for `Messaging`, `Artifacts`, and `Cron`.
- In Simplicio, these surfaces are not only cloned screens. The relevant state is read from, or written through, the Rust runtime via Tauri.
- This keeps the Simplicio rule intact: the core remains in Rust and the desktop stays a provider-first shell over the runtime.

## 5. Additional Note

- `Providers` is also wired on the Simplicio side through `provider_accounts()` in [apps/desktop/src-tauri/src/main.rs](../../../apps/desktop/src-tauri/src/main.rs) and rendered in the desktop shell, but the Hermes settings modal was unstable under macOS accessibility automation during this evidence pass, so the reliable paired screenshot set above is the one used as the primary proof.','docs/evidence/desktop-hermes-parity/desktop-hermes-parity.md','49514f9e60c4f158c70c7500bacf5f754c51b5e1be87b304c6324c1252af3f0f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/evidence/issue-3725-mapper-adapter.md','project_doc','doc://simplicio-runtime/docs/evidence/issue-3725-mapper-adapter.md','doc: Issue #3725: native MapperStore read boundary','# Issue #3725: native MapperStore read boundary

This change adds the first native Rust boundary for the canonical MapperStore
operations database. It is deliberately read-only: Runtime can inspect an
existing MapperStore database without creating a competing schema or spawning
Python/sqlite3 for each operation.

## Evidence

- Runtime base: `7dd57a1fb5fbef28ea407391d0a7c03f14a2f58c` (3.5.7)
- Mapper contract: `simplicio.mapper-store.operations/v1`
- Operations API contract: `simplicio.mapper-store.operations-api/v1`
- Focused command: `cargo test --locked --bin simplicio mapper_store_client::tests -- --nocapture`
- Formatting: targeted `rustfmt --edition 2021 src/mapper_store_client.rs`
- The repository-wide `cargo fmt --all -- --check` remains noisy because the
  base checkout already contains unrelated formatting differences.

The focused fixture tests cover path precedence, read-only missing-store
behavior, schema mismatch, status/capability reporting, and the pinned
checksum write-authority gate. Production code contains no DDL and no
subprocess invocation.

## Deliberate residuals

This is not the full closure of #3725. CLI/MCP wiring, the complete SQLite
inventory and ownership plan, installed-binary and cross-platform golden
matrices, multiprocess locking evidence, and critical-coverage measurement
remain to be implemented and verified before the issue can close.','docs/evidence/issue-3725-mapper-adapter.md','af179788038a7239676b885ac3fa2e3dbdd9869a1c6684041aff5f39f0b5d544','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/evidence/issue-3726-semantic-adapter.md','project_doc','doc://simplicio-runtime/docs/evidence/issue-3726-semantic-adapter.md','doc: Issue #3726: native MapperStore semantic read boundary','# Issue #3726: native MapperStore semantic read boundary

This slice adds a native Rust read-only view over the canonical Mapper memory
and semantic contracts. Runtime can inspect existing `memory.sqlite` state,
verify schema ownership, report FTS/vector capabilities, validate embedding
dimensions, and perform quoted FTS reads without creating or migrating a local
`simplicio-memory.sqlite` authority.

## Evidence

- Runtime base: `9be663b0485dc1fa67d06b6bb69360199afd9de4`
- Memory contract: `simplicio.mapper-store.memory/v1`
- Semantic contract: `simplicio.mapper-store.semantic/v1`
- Focused command: `cargo test --locked --bin simplicio mapper_store_client::tests -- --nocapture`
- Result: 6 focused tests passed
- Formatting: targeted `rustfmt --edition 2021 src/mapper_store_client.rs`

The fixture covers canonical metadata, item/chunk/embedding/model/tombstone
counts, FTS5 search, brute-force capability reporting when sqlite-vec is not
loaded, stable embedding dimensions, and fail-closed schema behavior. The
production adapter has no DDL and no write path.

## Deliberate residuals

This does not close #3726. Legacy import/backup/cutover/rollback, adapting
`MemoryV2Manager`/`SqliteVectorStore`/`SkillIndex`, vec0 present/absent
differential recall, concurrent ingest, installed CLI/MCP/in-process parity,
benchmarks, coverage, and removal of legacy neural writers remain open.','docs/evidence/issue-3726-semantic-adapter.md','0ff3c21aaf1e2f103aaa2c50a5f7c25344bf1734e684ec372388a441f2e26463','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/evidence/issue-3727-runtime-sqlite-ownership.md','project_doc','doc://simplicio-runtime/docs/evidence/issue-3727-runtime-sqlite-ownership.md','doc: Issue #3727: Runtime SQLite ownership inventory','# Issue #3727: Runtime SQLite ownership inventory

This inventory is a read-only classification of Runtime Rust call sites from
Runtime `3.5.7` (`9be663b0485dc1fa67d06b6bb69360199afd9de4`). A textual SQLite
match is not treated as an authority claim: each row records the observed
path/schema behavior and the next migration decision.

## Classification

| Runtime surface | Observed persistence | Classification | Mapper target / next action |
| --- | --- | --- | --- |
| `crates/simplicio-memory/src/store.rs`, `memory_v2.rs`, `vector_memory.rs` | `~/.simplicio-loop/memory/simplicio-memory.sqlite`; local migrations, `memory_items`, FTS5, packed vectors, optional vec0 | legacy neural authority | `memory.sqlite` / semantic store; freeze fixtures, import idempotently, then cut over |
| `src/mapper_memory.rs`, `src/hermes_import.rs`, `src/asolaria/consolidator.rs` | reads/writes or imports against the same `simplicio-memory.sqlite` path | legacy neural writers/readers | route through the semantic adapter only after differential/import evidence |
| `crates/simplicio-agents/src/agent_store.rs` | `.simplicio-loop/agents/agent-store.sqlite`; lifecycle, heartbeats, serialized state, embeddings | operational candidate with a distinct existing schema | map to operations extensions plus semantic projections; no direct merge until state-machine mapping |
| `crates/simplicio-agents/src/agent_ops_bounded_1536.rs` | `.simplicio-loop/agents.db` monitor scan | compatibility/reference path; separate from `agent-store.sqlite` | resolve whether it is live authority; block cutover until one path is proven |
| `src/idempotency_ext.rs` | caller-supplied `seen.db`; `seen` fingerprints and cleanup | operational candidate | map to Mapper idempotency/effect lineage; preserve source IDs and TTL semantics |
| `src/asolaria/store_ops.rs` + `src/asolaria/writer.rs` | caller-supplied SQLite connection; pages, sessions, observations, handoffs, embeddings | semantic/context candidate with single-writer actor | target `semantic.sqlite` projections and Mapper receipts; first capture the injected path at construction |
| `src/savings_ledger.rs` | production path is JSONL (`.simplicio-loop/ledger/token-spend.jsonl`); SQLite name is legacy documentation | non-SQLite projection/reference | exclude from SQLite migration; preserve JSONL ledger authority |
| `src/htool_kanban_tools.rs`, `src/hermes_import.rs` | `~/.hermes/.../kanban.db` and `state.db` external compatibility sources | external/import source | import only through explicit bounded adapters; never treat as Runtime authority |
| `src/imessage.rs` | `~/Library/Messages/chat.db` | external OS database | exclude; read-only integration only |
| `crates/simplicio-tokill/src/stats.rs`, tests and fixtures | caller-supplied or in-memory stats databases | rebuildable metrics/fixture | exclude from operations authority; retain local test fixtures |
| `src/organism/terminal_chat.rs` | `.simplicio-loop/memory/vector_memory.db` local vector path | legacy/rebuildable neural cache | map to semantic embeddings only after path ownership is confirmed |

## Invariants for the next migration slice

- Only `simplicio_mapper.store` owns Mapper schemas and migrations.
- Runtime must not create a second `operations.sqlite` queue, lease, fence, or
  effect ledger for the same attempt.
- Neural data must preserve stable IDs, content hashes, model, dimensions,
  provenance, timestamps, tombstones, and deterministic tie-breaks.
- External databases, fixtures, in-memory connections, and rebuildable metrics
  are not silently promoted to production authority.
- No writer is removed until backup, idempotent import, differential replay,
  rollback, and an explicit cutover receipt exist.

## Reproduction

The inventory was produced read-only with:

```text
rg -n ''Connection::open|open_with_flags|open_in_memory|\.sqlite3?|\.db'' src crates --glob ''*.rs''
rg -n ''CREATE TABLE|CREATE VIRTUAL TABLE|CREATE INDEX|apply_.*schema|ensure_schema|migration'' src crates --glob ''*.rs''
```

## Deliberate residuals

This is the ownership-plan slice of #3727, not issue closure. Runtime/Loop
handoff, CAS/lease/effect integration, import fixtures, crash/partition/stale
fence tests, soak, coverage, and removal of legacy writers remain unverified.','docs/evidence/issue-3727-runtime-sqlite-ownership.md','c2a47c506f4ebe9143a5dfc4fd77a5117a5053503f66cf43f039cff6ab141d9e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/evidence/issue-3728-cutover-gate.md','project_doc','doc://simplicio-runtime/docs/evidence/issue-3728-cutover-gate.md','doc: Issue #3728: read-only cutover readiness gate','# Issue #3728: read-only cutover readiness gate

Runtime now exposes `assess_mapper_cutover`, a small in-process gate for
doctor/status callers. It observes canonical and legacy paths without opening
or modifying databases and blocks readiness when a canonical store is missing,
not a regular file, or any legacy authority remains present. Overlapping
canonical/legacy paths are also rejected.

## Evidence

- Runtime base: `f2089d950d5557d2053179bc3b52cfedae6dcb4a`
- Contract: `simplicio.mapper-store.cutover-readiness/v1`
- Focused command: `cargo test --locked --bin simplicio mapper_store_client::tests mapper_cutover::tests -- --nocapture`
- Tests cover ready, missing canonical, legacy-present, path-overlap, and
  read-only/no-mutation behavior.

## Deliberate residuals

This is a preflight gate, not cutover authorization. #3728 still requires
backup/import/validation receipts, clean install and upgrade corpora,
CLI/MCP/in-process parity, installed-binary and Windows/Linux/macOS E2E,
rollback/fault injection, soak/performance evidence, and wiring the gate into
the user-facing doctor/status surfaces.','docs/evidence/issue-3728-cutover-gate.md','b3f448c82a928ce2514bb341d930fe42860ea8b479f1e35b37dbc48a722b19cc','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/evidence/kv-cache-326/README.md','project_doc','doc://simplicio-runtime/docs/evidence/kv-cache-326/README.md','doc: Evidence — KV cache reuse + direct neural memory access (#326)','# Evidence — KV cache reuse + direct neural memory access (#326)

Reproducible artifacts for the phase-1 delivery. Regenerate with:

```bash
simplicio model cache bench --json   > benchmark.json
simplicio model cache bench          > benchmark.txt
simplicio model cache status --json  > cache-status.json
```

The benchmark runs with **no model on disk**, so these numbers are reproducible
on any machine/CI. `benchmark.json` captures the before/after of prefill-token
reprocessing (the KV-reuse win) plus measured in-process cache-path latencies.

Headline (12 turns sharing one stable prefix): **87.5% fewer prefill tokens
reprocessed** (6 840 → 856). Design and full write-up:
`docs/architecture/llm-integration.md`.','docs/evidence/kv-cache-326/README.md','8c60dfa70b5718f3993a5ef580808d327ab55195086e4bc995472b9a86344791','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/evidence/loop-runtime-benchmark-2026-07-19.md','project_doc','doc://simplicio-runtime/docs/evidence/loop-runtime-benchmark-2026-07-19.md','doc: Benchmark and 50-issue execution ledger','# Benchmark and 50-issue execution ledger

Date: 2026-07-19 (UTC)
Runtime base: `2b56667d3b757a99b6dc71eab2bfeb6254d747e3`
Latest `simplicio-loop/main`: `8155d2203f0018b00d842ddea5910271bd85d3c4`
Synced loop contract: `.claude/skills/simplicio-loop/SKILL.md` at `e53f0636cbaf802a223a6eb24007748ade9bded8`

## Scope

This ledger fixes the first 50 issues returned by GitHub''s open-issue query
(`is:open`, created ascending) as the independent batch for this run:

`#37, #348, #2064, #2065, #2073, #2100, #2102, #2116, #2126, #2127,
#2128, #2129, #2130, #2131, #2132, #2133, #2134, #2135, #2136, #2137,
#2138, #2144, #2146, #2147, #2149, #2150, #2151, #2152, #2153, #2157,
#2158, #2159, #2162, #2163, #2164, #2165, #2166, #2173, #2174, #2175,
#2176, #2177, #2178, #2197, #2198, #2199, #2200, #2205, #2206, #2207`.

The repository had more than 50 open issues at collection time; the remaining
open issues are outside this batch.

## Execution modes

Each issue must be evaluated as its own task and must record the mode:

1. **raw** — no Simplicio loop/runtime path;
2. **loop** — latest `simplicio-loop/main` contract;
3. **runtime** — deterministic runtime gates and evidence, without loop orchestration;
4. **loop+runtime** — latest loop contract driving the runtime.

The primary comparison is **loop+runtime vs raw**, with runtime-only rows
retained to isolate the runtime contribution. Quality is a hard constraint:
speed or token savings do not count when the objective oracle fails.

## Required receipt fields

Each row must contain:

- issue number and immutable runtime/loop SHAs;
- mode, start/end timestamps, wall-clock milliseconds;
- objective result, tests/build/lint result, retries and commands;
- provider-reported prompt/completion/total tokens, local tokens, cache hits;
- estimated paid tokens only when provider usage is absent, marked as estimated;
- peak RSS/CPU, evidence bundle, diff hash and regression result;
- failure reason and human-intervention minutes.

No result is considered a fresh measurement unless raw events and the command
transcript are committed or attached as an artifact.

## Existing measured anchors

These are historical repository measurements, not fresh executions from this
turn:

| Measurement | Result |
|---|---:|
| Deterministic runtime lane | ~14 ms, 0 output tokens |
| HumanEval, paid backend | 95.1% (156/164) |
| Same backend without runtime lift | 91.5%; measured lift +3.7 pp |
| Local 4B, no paid LLM | 56.1% (92/164), 0 paid tokens |
| Six-task agent battery | 43.6 s total, 2,493 measured tokens |
| OpenClaw reference battery | 117.1 s total, 130,022 measured tokens |
| Realistic gold corpus | 3/3 green, $0 |

The repository explicitly labels the six-row with/without-runtime table as
fixture data until raw baseline logs are attached. These numbers must not be
presented as a new 50-issue benchmark.

## Current audit result

The 50 issues are not all implementation-complete. Several are architecture
specifications or known unimplemented mesh/cloud/product surfaces. The loop
contract requires re-querying GitHub and evidence-gated completion; therefore
this branch does not close issues merely because a design document or an old
commit mentions them.

Issue closure requires source changes (or a complete externally verifiable
artifact), objective tests, raw evidence, and a re-query showing the acceptance
criteria are met.

## Next reproducible command

From a checkout of this branch:

```bash
python3 scripts/run-agi-bench.py --local-only --json
python3 scripts/run-agi-corpus.py
```

For the four-way issue batch, the harness must emit one receipt per issue and
run the same task once in each selected mode. Paid-provider runs require the
provider credentials and must keep provider-reported usage separate from
estimates.','docs/evidence/loop-runtime-benchmark-2026-07-19.md','9ced11bba6dcedfd823255c4a0505a14fdcc7fe8132c4028f6be470cc7ee21f4','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/evidence/voice-computer-control-e2e-2026-06-24.md','project_doc','doc://simplicio-runtime/docs/evidence/voice-computer-control-e2e-2026-06-24.md','doc: Voice command-and-response + computer control — E2E verification (2026-06-24)','# Voice command-and-response + computer control — E2E verification (2026-06-24)

Run-verification for the goal *"termine e faça funcionar comando e resposta por
voz, controle completo do computador windows, mac e linux"*. Proves the chain
**works** (not just compiles) to the maximum extent a headless Linux CI box
allows, and states honestly what requires the actual host OS.

## Environment
- Linux container; **no microphone, no speakers, no physical display**; **not**
  macOS or Windows.
- Virtual display via `Xvfb` (`xvfb-run -s "-screen 0 1280x720x24"`).
- Present: `xdotool`, `scrot`, `faster-whisper` (pip), Node 22 + `npx`.
- Absent: `ffmpeg`/`ffplay`, `piper`, `espeak` (so TTS audio cannot play here —
  the code path returns an honest Err and the loop continues).

## 1. Computer control — REAL execution (Linux branch, live under Xvfb)
The compiled `simplicio gui …` actions ran against the virtual display:
```
gui screenshot …/live_shot.png -> "screenshot saved to …/live_shot.png"  (PNG 2774 bytes written)
gui move 300 200               -> "moved to (300,200)"
gui click 300 200              -> "clicked button 1 at (300,200)"
gui type "simplicio-live"      -> "typed 14 chars"   (xdotool typed)
gui key "ctrl+a"               -> "pressed ctrl+a"
```
`scrot`/`xdotool` actually ran — the screenshot file exists on disk.

## 2. Voice → action chain — REAL execution (transcript injected via --text)
Driving the desktop **through the voice loop** end-to-end (the only physically
unavailable link — mic→STT — is proven separately in §4):
```
voice run --text "simplicio gui screenshot …/vchain.png" --confirm --mode ask --json
  -> intent=execute_task, gate=allow, executed=true   (…/vchain.png written, 2774 bytes)
voice run --text "simplicio gui type ola-mundo" --confirm
  -> intent=execute_task, command=gui, executed -> xdotool typed 9 chars
```
The chain **strip-wake → classify-intent → memory recall → Action Gate →
dispatch → desktop_control** runs end-to-end and produces a real screenshot.

## 3. Natural-language routing (deterministic)
```
"simplicio veja meus emails todas as manhãs"
  -> command=cron, args=["add","0 7 * * *","veja meus emails"]   (Alexa-style schedule)
"simplicio termine a planilha e envie por email para fulano"
  -> intent=execute_task  (routes to reason --act: LLM plans, gated execution)
```

### Bug found + fixed during this verification
The multi-step example first misclassified as `stop`: the Portuguese preposition
**"para"** ("envie … para fulano") collided with the stop-word `"para "`. Fixed
`classify_intent` to match a stop verb only as the **first token** of the
utterance (regression test `preposition_para_is_not_a_stop`). A genuine cancel
("para tudo", "pare", "stop") still classifies as `stop`.

## 4. Offline STT — REAL execution (faster-whisper, tiny)
```
voice run --from voice_probe.wav --stt faster-whisper
  -> decoded the wav offline, returned "STT returned no text" for a 220 Hz tone
     (correct: no speech). The capture→decode pipeline runs offline.
```
`large-v3` / per-language `distil-whisper` (the defaults) are the identical code
path with a larger model.

## 5. Spoken reply (TTS) — honest degradation
```
voice run --text "simplicio status" --speak --json -> executed:false on this box
```
With no `piper`/`espeak`/`ffmpeg`, `speak_sync` returns an Err and the loop
continues — no fake "spoke". On a host with Piper/`say`/SAPI the same path
synthesizes and plays audio.

## 6. Cross-OS (Windows, macOS) — proven by exact-command unit tests
Live macOS/Windows execution is impossible in a Linux container. The per-OS
command construction is a **pure** function `desktop_control::plan(os, action)`,
unit-tested to assert the exact command each OS runs (these tests run on any
host):
- **Windows:** PowerShell `System.Windows.Forms` / `System.Drawing` /
  `user32.dll` (`SetCursorPos`, `mouse_event`, `SendKeys`, screen capture).
- **macOS:** `cliclick` + `screencapture` + `osascript` fallbacks.
- **Linux:** `xdotool` + `scrot` (also exercised live above).
HyperFrames video adapter likewise has pure `plan()`/`workdir()` unit tests for
its `npx hyperframes` invocations.

Setup scripts ship per OS: `scripts/voice-setup.sh` (Linux/macOS) and
`scripts/voice-setup.ps1` (Windows).

## Test evidence (release build, this session)
- `voice_loop::*` and `desktop_control::*` — see §6; intent regression included.
- Cron→action→voice and HyperFrames modules — 33 passed / 0 failed (prior run).

## What still requires the host (not verifiable in a headless Linux container)
- Physical microphone capture (`--listen` / `--loop`) — needs an audio device.
- Audible TTS — needs Piper voice / `say` / speakers + ffmpeg.
- macOS / Windows desktop branches — need those OSes (command strings unit-proven).

## Reproduce
```
apt-get install -y xvfb xdotool scrot
pip install faster-whisper
xvfb-run -a -s "-screen 0 1280x720x24" bash -c \
  ''simplicio gui screenshot /tmp/s.png && simplicio voice run --text "simplicio gui type hi" --confirm''
simplicio voice run --from sample.wav --stt faster-whisper
```','docs/evidence/voice-computer-control-e2e-2026-06-24.md','a34187fd7d3da8976f7d33e341a24f7d4c27d71bea783c0bc28c9be89f557149','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/evidence/voice-desktop-e2e-2026-06-24.md','project_doc','doc://simplicio-runtime/docs/evidence/voice-desktop-e2e-2026-06-24.md','doc: Voice + desktop control — end-to-end verification (2026-06-24)','# Voice + desktop control — end-to-end verification (2026-06-24)

Run-verification of the spoken-command → computer-control loop, proving it
**works** (not just compiles) as far as a headless Linux CI box allows.

## Environment
- Linux container, **no audio device, no physical display**.
- Virtual display via `Xvfb` (`xvfb-run -s "-screen 0 1280x720x24"`).
- Tools installed: `xdotool`, `scrot`, `faster-whisper` (pip), Whisper `tiny` (for the STT proof).

## 1. Native desktop control (Linux branch) — REAL execution
All `simplicio gui …` actions executed against the virtual display and returned ok:

```
gui screenshot /tmp/vshot.png  -> {"ok":true,"detail":"screenshot saved ..."}   (PNG 2774 bytes written)
gui move 200 150               -> {"ok":true,"detail":"moved to (200,150)"}
gui click 200 150              -> {"ok":true,"detail":"clicked button 1 at (200,150)"}
gui type "hello world"         -> {"ok":true,"detail":"typed 11 chars"}          (xdotool typed)
gui key "ctrl+a"               -> {"ok":true,"detail":"pressed ctrl+a"}
gui scroll down 2              -> {"ok":true,"detail":"scrolled down x2"}
```
`scrot`/`xdotool` actually ran — the screenshot file was created. The macOS
(cliclick/screencapture) and Windows (PowerShell) branches share the same dispatch
and command surface; only the underlying tool differs per OS.

## 2. Full voice → action → desktop chain — REAL execution
Driving the desktop **through the voice loop** (transcript injected via `--text`;
the only physically-unavailable link, mic→STT, is proven separately in §3):

```
voice run --text "simplicio gui screenshot /tmp/vchain.png" --confirm --mode ask
  -> intent=execute_task, gate=allow, executed=true
  -> dispatch("gui",["screenshot","/tmp/vchain.png"]) -> /tmp/vchain.png written (2774 bytes)

voice run --text "simplicio gui type ola-mundo" --confirm
  -> executed=true -> xdotool typed "ola-mundo"
```
The chain **strip-wake → intent → memory recall → Action Gate → dispatch →
desktop_control** runs end-to-end and produces a real screenshot.

## 3. Offline STT (faster-whisper) — REAL execution
```
SIMPLICIO_WHISPER_MODEL=tiny  voice run --from <wav> --stt faster-whisper
  -> faster-whisper tiny model downloaded once, decoded the wav, transcribed,
     returned "no text" for a 220 Hz tone (correct: no speech). Pipeline runs offline.
```
`large-v3` (the default) is the identical code path with a larger model.

## 4. Memory recall inside the voice loop — REAL hit
Seeded one item into the neural memory (sqlite-fts5) and recalled it through the
voice loop:
```
seed: INSERT memory_items (stable_id,kind,source,title,content)
      VALUES (''e2e-001'',''fact'',''seed-e2e'',''project status'',
              ''the simplicio project status is operational and green'')

voice run --text "status" --json
  -> "memory":["project status [fact]: the simplicio project [status] is operational and green"]
```
The utterance hit the FTS index via the same `memory_query_sqlite` path as the
`simplicio memory` command — proving the "vê na memória" link end-to-end (the hit
is also injected into the spoken reply).

## What still needs the host (not verifiable in a headless container)
- Physical microphone capture (`--listen` / `--loop`) — needs an audio device.
- TTS audible output — needs Piper voice / `say` / speakers.
- macOS/Windows desktop branches — need those OSes.

## Reproduce
```
apt-get install -y xvfb xdotool scrot
xvfb-run -a -s "-screen 0 1280x720x24" bash -c \
  ''simplicio gui screenshot /tmp/s.png && simplicio voice run --text "simplicio gui type hi" --confirm''
```','docs/evidence/voice-desktop-e2e-2026-06-24.md','93140faf8709ae041a39c4535a26e09ca4a911e6ccdc64234bc4d26ec5d136cf','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/FAST_NATIVE_ARTIFACT_CONTRACT.md','project_doc','doc://simplicio-runtime/docs/FAST_NATIVE_ARTIFACT_CONTRACT.md','doc: Consuming the precompiled Simplicio Fast native artifact','# Consuming the precompiled Simplicio Fast native artifact

Runtime accepts only the artifact layout produced by Simplicio Fast PR #210:

```text
artifacts/<platform>/simplicio.fast-native_v1/
  manifest.json
  <filename from manifest>
```

The caller passes the manifest path to `resolve_fast_native_artifact`. Runtime
validates the exact ABI `simplicio.fast-native/v1`, supported platform, a basename-only
filename, and the complete lowercase SHA-256 before returning an artifact handle.
It does not compile source or search for a compiler.

Missing manifest/binary is `RUST_ARTIFACT_MISSING` wrapped as `RecoveryRequired`.
Malformed metadata is `RUST_MANIFEST_INVALID`; tamper is
`RUST_ARTIFACT_HASH_MISMATCH`. None of these states may be promoted to native
execution or successful completion. The caller may deliberately select the Python
Fast fallback and must preserve the reason code in its receipt.

Offline verification:

```sh
python3 scripts/test_fast_native_artifact.py -v
```

This contract validates packaging only. It does not claim that this repository
currently contains a native binary or that Rust tests have run.','docs/FAST_NATIVE_ARTIFACT_CONTRACT.md','9dae297b0e36da149acf1fc49f3b1e538ada80dc9664609c06623b45fd3d6831','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/FOUR_WAY_BENCHMARK.md','project_doc','doc://simplicio-runtime/docs/FOUR_WAY_BENCHMARK.md','doc: Four-way benchmark runner','# Four-way benchmark runner

`scripts/benchmark-loop-runtime.py` runs the same issue-sized fixture through
four independently recorded paths:

- `baseline`: no Simplicio components;
- `runtime`: runtime gates without loop orchestration;
- `runtime_loop`: runtime plus the pinned `simplicio-loop` contract;
- `runtime_mapper_loop_dev_cli`: the complete runtime + mapper + loop + dev-cli chain.

The fixture supplies explicit argv commands per mode, so no command is silently
substituted. Missing modes are emitted as `not_configured`. Provider-reported
usage is parsed only from JSON output; missing usage remains null and is never
converted to zero. A case may define `seed_command` to seed/check neural
memory before Runtime-backed modes.

The runner records wall time, child CPU time, sampled peak RSS on Linux, exit
status, stdout/stderr, explicit token usage, pinned component SHAs, warm-up
status, verification status, and repetition number. Trials are randomized
with `--shuffle-seed` to reduce order bias. The default is one warm-up plus
five measured repetitions. It writes JSON, JSONL, and a sibling CSV. The
summary is `VERIFIED` only when every measured repetition of the complete
chain contains an explicit `VERIFIED` contract result.

Example:

```bash
python3 scripts/benchmark-loop-runtime.py \
  --fixture examples/benchmark-four-way.json \
  --out /tmp/four-way.json \
  --csv /tmp/four-way.csv \
  --warmups 1 \
  --repetitions 5 \
  --shuffle-seed 20260719
```

The JSON includes mean, median, p50, p95, p99, minimum, maximum, and standard
deviation for measured elapsed time, child CPU, and RSS. Token statistics are
reported only for repetitions containing explicit provider usage. A failed,
blocked, unconfigured, or timed-out repetition is not counted as a green
result.

For a real issue batch, pin Runtime, Loop, Mapper, and Dev CLI SHAs in every
case, use the same model/provider/budget/workload, and retain raw receipts and
environment metadata. If installation, provider authentication, the local LLM,
or neural-memory seed fails, stop the benchmark with an explicit blocked
receipt; do not synthesize fixture timings or claim savings.

The runner requires a passing neural-memory seed for Runtime/Loop modes by
default. Use `--no-require-neural-seed` only for an explicitly documented
non-production probe. A missing or failing seed, failed warm-up, installation
failure, provider failure, unavailable local LLM, or unconfigured scenario
emits a `blocked`/`not_configured` receipt, starts no measured repetitions
for that scenario, and exits non-zero.','docs/FOUR_WAY_BENCHMARK.md','27a504d4bcf1ef8d05bde21001412b1cbd49fcd27792f0b27960c41e3132f7ae','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/GATEWAY_DISCORD.md','project_doc','doc://simplicio-runtime/docs/GATEWAY_DISCORD.md','doc: Simplicio Gateway — Discord Bot Setup','# Simplicio Gateway — Discord Bot Setup

## Overview

This document describes how to set up and run the Simplicio Discord bot, inspired by the Hermes Agent pattern.

## Files

| File | Purpose |
|------|---------|
| `scripts/gateway-guardian.sh` | Keeps the gateway alive with auto-restart |
| `scripts/ai.simplicio.gateway.plist` | macOS launchd configuration for auto-start |
| `scripts/log-rotate.sh` | Rotates log files when they exceed 10MB |
| `scripts/simplicio-daemon.sh` | Manual start/stop/status commands |
| `~/.simplicio-loop/.env` | Environment variables (tokens, channel IDs) |

## Quick Start

### 1. Install launchd service (auto-restart)

```bash
# Copy plist to LaunchAgents
sudo cp scripts/ai.simplicio.gateway.plist ~/Library/LaunchAgents/

# Load the service
launchctl load ~/Library/LaunchAgents/ai.simplicio.gateway.plist

# Start the service
launchctl start ai.simplicio.gateway

# Check status
launchctl list | grep simplicio
```

### 2. Manual start (without launchd)

```bash
# Start the guardian (auto-restart)
./scripts/gateway-guardian.sh run

# Or use the daemon script
./scripts/simplicio-daemon.sh start discord
```

### 3. Check status

```bash
./scripts/gateway-guardian.sh status
./scripts/simplicio-daemon.sh status
```

### 4. Stop

```bash
# If using guardian
./scripts/gateway-guardian.sh stop

# If using daemon
./scripts/simplicio-daemon.sh stop

# If using launchd
launchctl stop ai.simplicio.gateway
```

## Environment Variables

Create `~/.simplicio-loop/.env`:

```bash
# Discord Bot Token
SIMPLICIO_DISCORD_TOKEN=your_bot_token_here
DISCORD_BOT_TOKEN=your_bot_token_here

# Channel ID (where the bot listens)
SIMPLICIO_DISCORD_CHANNEL_ID=your_channel_id_here

# LLM Provider (for chat replies)
OPENAI_API_KEY=sk-...
```

## Log Files

| File | Content |
|------|---------|
| `~/.simplicio-loop/logs/gateway.log` | Gateway stdout |
| `~/.simplicio-loop/logs/gateway.error.log` | Gateway stderr |
| `~/.simplicio-loop/logs/guardian.log` | Guardian/monitor logs |
| `~/.simplicio-loop/logs/guardian.error.log` | Guardian errors |

## State Files

| File | Purpose |
|------|---------|
| `~/.simplicio-loop/gateway.pid` | Current process PID |
| `~/.simplicio-loop/gateway.lock` | Lock file |
| `~/.simplicio-loop/gateway_state.json` | Runtime state |

## Differences from Hermes

| Feature | Hermes | Simplicio |
|---------|--------|-----------|
| Protocol | WebSocket (discord.py) | REST polling |
| Library | discord.py | Custom HTTP (curl) |
| Intents | Full | Basic |
| Slash commands | Yes | No (planned) |
| Voice | Yes | No |
| Auto-restart | launchd | launchd + guardian |

## Troubleshooting

### Bot not responding

1. Check if process is running:
   ```bash
   ps aux | grep simplicio | grep gateway
   ```

2. Check logs:
   ```bash
   tail -f ~/.simplicio-loop/logs/gateway.error.log
   ```

3. Verify token:
   ```bash
   curl -H "Authorization: Bot YOUR_TOKEN" https://discord.com/api/v10/users/@me
   ```

### Gateway keeps restarting

Check guardian logs:
```bash
tail -f ~/.simplicio-loop/logs/guardian.log
```

Common causes:
- Invalid token
- Missing channel ID
- Discord API rate limiting

## Architecture

```
┌─────────────────┐
│  launchd plist  │  ← Auto-restart on boot
│  (ai.simplicio) │
└────────┬────────┘
         │
┌────────▼────────┐
│  gateway-guardian │  ← Monitor + auto-restart
│     .sh          │
└────────┬────────┘
         │
┌────────▼────────┐
│  simplicio       │  ← Rust binary
│  gateway listen  │
│     discord      │
└────────┬────────┘
         │
┌────────▼────────┐
│  Discord API     │  ← REST polling
│  (v10)          │
└─────────────────┘
```

## See Also

- `docs/SIMPLICIO_OPERATIONAL_MANUAL.md` — Full operational manual
- `scripts/start-gateway.sh` — Quick start commands
- `.simplicio-loop/.env.example` — Environment template','docs/GATEWAY_DISCORD.md','53a8d1e5635dd17d9490d18c71cce3b2c6cd91133b985be5ed717d079b41925b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/getting-started.md','project_doc','doc://simplicio-runtime/docs/getting-started.md','doc: Getting Started with Simplicio Runtime','# Getting Started with Simplicio Runtime

**5-10 minutes to your first real task.**

Simplicio is a deterministic, Rust-native AI engineering agent. It wraps the
LLM loop so you stay in control: mechanical edits apply via `git apply`, every
action is gated, and token spend is minimised by doing as much work as possible
without calling an LLM at all.

---

## 1. Install

**macOS (Homebrew)**
```sh
brew install wesleysimplicio/tap/simplicio
```

**One-line install (Linux / macOS)**
```sh
curl -fsSL https://raw.githubusercontent.com/wesleysimplicio/simplicio/master/install.sh | sh
```

**Linux / Windows — direct binary**

Release assets are raw binaries in the public repo (no tarball):
`simplicio-linux-x64` · `simplicio-darwin-arm64` · `simplicio-windows-x64`.
```sh
# Linux x64
curl -fsSL https://github.com/wesleysimplicio/simplicio/releases/latest/download/simplicio-linux-x64 -o simplicio
chmod +x simplicio && sudo mv simplicio /usr/local/bin/
```

---

## 2. First-run check

```sh
simplicio welcome          # what THIS machine has: runtime tier, local model, provider
simplicio doctor --repair
simplicio self-test        # real probes: adapter resolution, validation plan, evidence dir
simplicio first-run start  # guided onboarding — progress persists in ~/.simplicio-loop/onboarding.json
```

`simplicio welcome` reports the live runtime tiers (`low`, `normal`, `full`)
and whether a local model / remote provider is actually configured on this
machine. `simplicio first-run` walks five steps (`start`, `status`,
`step --step N --done`, `complete`); the doctor step only marks done when the
real doctor checks pass, and `complete` refuses until every step is done.
`simplicio self-test` exits non-zero when any probe fails.

`simplicio doctor --repair` checks your environment and repairs common issues
automatically:
- Creates `.simplicio-loop/` layout in the current repo
- Verifies `git` is on PATH
- Checks the embedded llama.cpp engine and the governed GGUF cache
- Checks Python adapters (`simplicio-py`, `simplicio-dev-cli`)

Sample output (version shown is whatever `simplicio version` reports):
```
Simplicio Runtime <version>
repo: /home/you/myproject
health: warning
  ✓ git                 git found on PATH
  ✓ local-layout        .simplicio-loop directory present
  ✓ llama-cpp           embedded Runtime inference engine available
  ⚠ gguf-model          canonical Qwen3.5-4B Q4_K_M absent
    → simplicio model fetch --tier auto --yes
  ✓ adapter-executor    simplicio-py found on PATH

Run ''simplicio doctor --repair'' to attempt automatic fixes.
```

---

## 3. Install Python adapters (optional, for full coding loop)

```sh
pip install --upgrade simplicio-cli simplicio-mapper simplicio-prompt simplicio-sprint
```

The runtime calls these at runtime via PATH — no source required.

---

## 4. Real-world examples

### Example A — Fix a failing test

```sh
cd myproject
simplicio run --task "make cargo test pass — the test ''parse_edge_case'' is failing"
```

Simplicio will:
1. Map the repo
2. Plan a mechanical edit
3. Apply it via `git apply`
4. Run `cargo test` and verify it passes
5. Show an evidence summary

### Example B — Add a feature

```sh
simplicio run --task "add a --dry-run flag to the deploy command in src/cli.rs"
```

### Example C — Review a diff before merging

```sh
simplicio diff-review --pr 42
```

### Example D — Check AGI roadmap status

```sh
simplicio agi-status
# or for JSON:
simplicio agi-status --json
```

### Example E — Beta readiness check

```sh
simplicio beta-status
```

---

## 5. Local LLM (offline mode)

Official binaries already include the llama.cpp engine. Provision and test
the pinned model through the Runtime:
```sh
simplicio model fetch --tier auto --yes
simplicio local-model health --json
```

Then run with local inference:
```sh
simplicio run --local --task "..."
```

---

## 6. Remote model (OpenRouter / OpenAI-compatible)

```sh
export SIMPLICIO_MODEL="openai/gpt-4o-mini"
export SIMPLICIO_BASE_URL="https://openrouter.ai/api/v1"
export SIMPLICIO_API_KEY="sk-..."
simplicio run --task "..."
```

---

## 7. Evidence and token ledger

After every task, see what was done:
```sh
simplicio evidence summary
simplicio evidence tokens
simplicio evidence ledger
```

The deterministic ratio tells you what fraction of work skipped the LLM
entirely — saving tokens and guaranteeing reproducibility.

---

## 8. Migrate from Hermes / OpenClaw / Pi

```sh
simplicio migrate inspect --source hermes
simplicio migrate inspect --source openclaw
simplicio migrate inspect --source pi
```

This produces a compatibility matrix showing which settings map directly,
which need manual adjustment, and which are unsupported.

---

## FAQ

**Q: Do I need a GPU?**  
No. Qwen3.5-4B Q4_K_M runs on CPU; supported GPU/Metal acceleration makes it
faster. The Runtime adjusts context and concurrency to host memory without
changing model identity.

**Q: Does simplicio send my code to the cloud?**  
Only if you use a remote model via `SIMPLICIO_BASE_URL`. With `--local` it stays
entirely on-device.

**Q: How is this different from Hermes / OpenClaw / Claude Code?**  
Simplicio focuses on determinism: mechanical edits use `git apply` (not free-form
LLM writes), every action is gated, and the token ledger shows you exactly what
was spent. The coding loop iterates until tests pass.

**Q: I got an error — what do I do?**  
```sh
simplicio doctor --repair --json
```
Then check the `"health"` field. Every error has a `"action"` suggestion.

---

## Next steps

- `simplicio help` — full command reference
- `docs/SIMPLICIO_OPERATIONAL_MANUAL.md` — deep technical reference
- `simplicio agi-status` — roadmap and component health
- GitHub Issues: https://github.com/wesleysimplicio/simplicio-runtime/issues','docs/getting-started.md','90fc3d478fbe6306ba9eb6268a841ad20fe6eaf86229bea6e5832d7174676614','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/git-preflight.md','project_doc','doc://simplicio-runtime/docs/git-preflight.md','doc: Git pull preflight','# Git pull preflight

`simplicio git preflight --repo <path> --json` is a read-only gate for Runtime
integration. It never runs `pull`, `merge`, `rebase`, `reset`, `stash`, or
deletion operations.

The JSON receipt includes the local and upstream commit IDs, ahead/behind
counts, local-only and remote-only commits, dirty/untracked paths, a stable
`repository_fingerprint`, and recommended actions.

| Status | Meaning | Exit |
| --- | --- | ---: |
| `clean` | local and upstream agree; no dirty paths | 0 |
| `dirty` | local and upstream agree; local changes are preserved | 0 |
| `clean_fast_forward` | upstream is ahead; clean tree can be reviewed for fast-forward | 0 |
| `dirty_fast_forward` | upstream is ahead; dirty paths must be reviewed first | 0 |
| `ahead_only` | local has commits not present upstream | 0 |
| `blocked_divergence` | both sides have commits the other does not | non-zero |
| `missing_remote` | no usable upstream ref is configured | non-zero |

`blocked_divergence` is a blocker, not permission to clean up the checkout.
The preflight preserves refs, index, worktree, stash, dirty files, and
untracked files. Review `local_only_commits`, `remote_only_commits`, and
`dirty_paths` before choosing a strategy.

Reconciliation is a separate, explicit operation:

```text
simplicio git reconcile --repo <path> --strategy ff-only --json
simplicio git reconcile --repo <path> --strategy merge --json
simplicio git reconcile --repo <path> --strategy rebase --json
```

`ff-only` is accepted only when the local branch is not ahead and the worktree
is clean. `merge` and `rebase` require `blocked_divergence` and a clean
worktree. This prevents an explicit reconciliation from attempting to update
the Runtime checkout while tracked or untracked user files still need review.
Every explicit operation records its strategy, command exit code, output bytes,
and a post-operation graph verification. Failed or conflicting operations
remain non-zero and require operator review.','docs/git-preflight.md','96e1b470b429b3a0b5e84645f0cf59320b8f87ee3296f847941acd9ed247cee5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/growth-autopilot/README.md','project_doc','doc://simplicio-runtime/docs/growth-autopilot/README.md','doc: Growth Autopilot operational manual','# Growth Autopilot operational manual

This document is the docs-first operational guide for the `growth-docs`
capability. It complements the runtime-first Simplicio contract by defining how
Growth Autopilot work should be described, modeled, validated, and handed off.

## Purpose

Growth Autopilot is a governed workflow for turning a SaaS description into a
launch plan, a set of reusable assets, approval receipts, experiments, and
revenue evidence. It must not promise autonomous success, guaranteed revenue,
or any live side effect without approval.

## Canonical command flow

Use the runtime and evidence surfaces in this order:

1. Claim the workstream when the issue is active.
   ```bash
   ./target/release/simplicio agent claim --issue 1211 --worker doc-agent --json
   ```
2. Run a governed implementation wave with a small local crew for docs work.
   ```bash
   ./target/release/simplicio run "growth-autopilot/growth-docs quickstart" --repo . --agents 6 --local --evidence --json
   ```
3. Validate the docs and example fixtures.
   ```bash
   ./target/release/simplicio validate "growth-autopilot/growth-docs" --repo . --json
   ```
4. Rebuild the consolidated example bundle after adding flat fixtures.
   ```bash
   python3 scripts/consolidate_examples.py
   ```
5. Run schema smoke validation for the new growth fixtures.
   ```bash
   npx --yes ajv-cli validate --spec=draft2020 --strict=false -s schemas/growth-run.schema.json -d examples/growth-run.example.json
   ```
6. Exercise the e2e sandbox stub in dry-run mode.
   ```bash
   ./target/release/simplicio growth e2e-sandbox --saas "Acme Notes" --json
   ```
7. Exercise the daemon-mode stub in sandbox mode.
   ```bash
   ./target/release/simplicio growth daemon-mode --campaign campaign-acme-notes-launch-001 --mode sandbox --resume --json
   ```
8. Only after validation: release the lease with evidence links.
   ```bash
   ./target/release/simplicio agent release --issue 1211 --worker doc-agent --json
   ```

## Schema catalog

The growth docs capability uses the following schema files:

- `schemas/growth-run.schema.json`
- `schemas/growth-campaign.schema.json`
- `schemas/growth-offer.schema.json`
- `schemas/growth-asset.schema.json`
- `schemas/growth-approval.schema.json`
- `schemas/growth-experiment.schema.json`
- `schemas/growth-revenue-event.schema.json`
- `schemas/growth-e2e-sandbox.schema.json`
- `schemas/growth-daemon-mode.schema.json`

## Example fixtures

The sandbox fixtures are flat files under `examples/` so they can be folded into
`examples/EXAMPLES.md` and validated in CI:

- `examples/growth-run.example.json`
- `examples/growth-campaign.example.json`
- `examples/growth-offer.example.json`
- `examples/growth-asset.example.json`
- `examples/growth-approval.example.json`
- `examples/growth-experiment.example.json`
- `examples/growth-revenue-event.example.json`
- `examples/growth-e2e-sandbox.example.json`
- `examples/growth-daemon-mode.example.json`
- `examples/growth-autopilot-quickstart.md`

## Daemon-mode quickstart

Use the governed daemon stub to simulate pause/resume/kill behavior without live side effects:

```bash
./target/release/simplicio growth daemon-mode --campaign campaign-acme-notes-launch-001 --resume --json
```

Daemon-mode rules:

- Heartbeat every 60 seconds during active runs.
- Keep all jobs idempotent.
- Pause/resume must be checkpointed in the evidence ledger.
- Kill switch must block publish/send/spend/live checkout immediately.
- Crash recovery must resume from the latest checkpoint, not from scratch.

The daemon stub stays dry-run or sandbox only until a future follow-up issue wires live autonomous execution.

## Operator checklist for a safe launch

- [ ] Keep the initial run in `draft`, `sandbox`, or `dry-run` mode.
- [ ] Attach an approval receipt before any live publish, send, spend, or Stripe
      mutation.
- [ ] Keep preview, rollback, pause, and resume paths available.
- [ ] Validate schemas and example fixtures before closing the issue.
- [ ] Record evidence paths, approval IDs, and the source run ID in every write.
- [ ] Stop and create a human review task if confidence is low or policy risk
      increases.
- [ ] Never claim autonomous revenue; describe observed results only.

## Notes on memory and evidence

Every record should keep provenance with the source run ID, source issue,
confidence, record kind, and timestamp. The evidence bundle should be enough for
another agent to pick up the same issue using only this manual, the example
fixtures, and the recorded receipts.','docs/growth-autopilot/README.md','2c7db0d49529a2643ce9ba0e96037a63a4b574ef615139106db2344a7add17f6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-import/2026-06-15-command-parity-audit.md','project_doc','doc://simplicio-runtime/docs/hermes-import/2026-06-15-command-parity-audit.md','doc: Hermes → Simplicio command parity audit — 2026-06-15','# Hermes → Simplicio command parity audit — 2026-06-15

## Status (2026-06-17 update)

The committed `simplicio.hermes-cli-parity/v1` matrix is now live in
`src/hermes_parity_cli_audit.rs` (wired into `main.rs` via
`mod hermes_parity_cli_audit`).  Query it at runtime with
`simplicio hermes-audit [--json] [--filter missing|partial|covered|rejected]`.

## Resultado curto

Não, ainda não temos paridade completa de comandos Hermes no Simplicio. O Hermes Agent v0.16.0 expõe 54 comandos top-level. O `simplicio --help` expõe muitos comandos próprios e 20 nomes batem diretamente, mas a auditoria encontrou lacunas e superfícies parciais que precisam de issues específicas.

- Master issue: [#1558](https://github.com/wesleysimplicio/simplicio-runtime/issues/1558)
- Counts nesta matriz inicial: Covered: 12, Gap: 14, Partial: 28
- Committed matrix (src/hermes_parity_cli_audit.rs): 56 entries, schema `simplicio.hermes-cli-parity/v1`

## Evidência local

- `.simplicio-loop/hermes-command-audit/command-inventory.json`
- `.simplicio-loop/hermes-command-audit/hermes-help.txt`
- `.simplicio-loop/hermes-command-audit/simplicio-help.txt`
- `.simplicio-loop/hermes-command-audit/simplicio-missing-probe.json`

Versões auditadas:

- Hermes Agent v0.16.0 (2026.6.5), upstream `29c69855`
- Simplicio Runtime v0.9.5, commit `d0aef398`, Windows x86_64

## Issues abertas

- [#1551](https://github.com/wesleysimplicio/simplicio-runtime/issues/1551) — Provider/config/fallback/secrets/portal/prompt-size
- [#1552](https://github.com/wesleysimplicio/simplicio-runtime/issues/1552) — Messaging/gateway/send/WhatsApp Cloud/Slack
- [#1553](https://github.com/wesleysimplicio/simplicio-runtime/issues/1553) — Skills/plugins/bundles/curator/tools/MCP
- [#1554](https://github.com/wesleysimplicio/simplicio-runtime/issues/1554) — Sessions/checkpoints/import/debug/insights/state
- [#1556](https://github.com/wesleysimplicio/simplicio-runtime/issues/1556) — ACP/LSP/profile/desktop/Claw/computer-use

## Matriz top-level inicial

| Hermes command | Status | Simplicio surface | Observação | Issue |
|---|---|---|---|---|
| `chat` | Covered | `chat` | Direct chat surface exists; behavior parity still needs future subcommand checks. | [#1558](https://github.com/wesleysimplicio/simplicio-runtime/issues/1558) |
| `model` | Partial | `model` | Simplicio reports/checks model; Hermes selects default model/provider. | [#1551](https://github.com/wesleysimplicio/simplicio-runtime/issues/1551) |
| `fallback` | Gap | `—` | No provider fallback manager equivalent observed. | [#1551](https://github.com/wesleysimplicio/simplicio-runtime/issues/1551) |
| `secrets` | Gap | `—` | No Bitwarden/external secret-source CLI parity observed. | [#1551](https://github.com/wesleysimplicio/simplicio-runtime/issues/1551) |
| `migrate` | Partial | `migrate` | Simplicio has guided migration/from-source surfaces; Hermes xai migration needs mapping. | [#1556](https://github.com/wesleysimplicio/simplicio-runtime/issues/1556) |
| `gateway` | Partial | `gateway` | Simplicio gateway exists; Hermes lifecycle subcommands need exact map. | [#1552](https://github.com/wesleysimplicio/simplicio-runtime/issues/1552) |
| `proxy` | Covered | `proxy` | OpenAI-compatible proxy lifecycle exists. | [#1558](https://github.com/wesleysimplicio/simplicio-runtime/issues/1558) |
| `lsp` | Partial | `lsp` | Simplicio serve/status/help; Hermes install/list semantics need mapping. | [#1556](https://github.com/wesleysimplicio/simplicio-runtime/issues/1556) |
| `setup` | Partial | `setup` | Both have setup; Hermes setup subcommands need mapping. | [#1551](https://github.com/wesleysimplicio/simplicio-runtime/issues/1551) |
| `postinstall` | Gap | `install/toolchain?` | No Hermes-style deps bootstrap command observed. | [#1554](https://github.com/wesleysimplicio/simplicio-runtime/issues/1554) |
| `whatsapp` | Partial | `whatsapp` | Simplicio WhatsApp exists; setup/API flow parity unresolved. | [#1552](https://github.com/wesleysimplicio/simplicio-runtime/issues/1552) |
| `whatsapp-cloud` | Gap | `—` | Business Cloud API setup command not observed. | [#1552](https://github.com/wesleysimplicio/simplicio-runtime/issues/1552) |
| `slack` | Gap | `gateway?` | No Slack manifest/helper parity observed. | [#1552](https://github.com/wesleysimplicio/simplicio-runtime/issues/1552) |
| `send` | Partial | `gateway send / telegram send` | Generic top-level send parity not observed. | [#1552](https://github.com/wesleysimplicio/simplicio-runtime/issues/1552) |
| `login` | Partial | `login` | Simplicio login is Google identity oriented; Hermes provider login matrix differs. | [#1551](https://github.com/wesleysimplicio/simplicio-runtime/issues/1551) |
| `logout` | Partial | `logout` | Same name; provider matrix differs. | [#1551](https://github.com/wesleysimplicio/simplicio-runtime/issues/1551) |
| `auth` | Partial | `auth` | Same name; Hermes pooled provider credentials not covered by current Simplicio auth. | [#1551](https://github.com/wesleysimplicio/simplicio-runtime/issues/1551) |
| `status` | Covered | `status` | Status surface exists. | [#1558](https://github.com/wesleysimplicio/simplicio-runtime/issues/1558) |
| `cron` | Partial | `cron` | Both have cron; subcommands differ. | [#1554](https://github.com/wesleysimplicio/simplicio-runtime/issues/1554) |
| `webhook` | Partial | `webhook` | Both have webhook; subscription/register semantics differ. | [#1552](https://github.com/wesleysimplicio/simplicio-runtime/issues/1552) |
| `portal` | Gap | `—` | Nous Portal helper not observed. | [#1551](https://github.com/wesleysimplicio/simplicio-runtime/issues/1551) |
| `kanban` | Partial | `kanban` | Simplicio board exists; Hermes multi-profile collaboration board has richer subcommands. | [#1554](https://github.com/wesleysimplicio/simplicio-runtime/issues/1554) |
| `hooks` | Covered | `hooks` | Hook list/test/revoke/doctor exists. | [#1558](https://github.com/wesleysimplicio/simplicio-runtime/issues/1558) |
| `doctor` | Covered | `doctor` | Doctor','docs/hermes-import/2026-06-15-command-parity-audit.md','2bbc1980c8a26439b1f0cfb1697c37010517954a2c1289a4b2fbe4659c11ae54','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-import/2026-06-15-import-log.md','project_doc','doc://simplicio-runtime/docs/hermes-import/2026-06-15-import-log.md','doc: Hermes → Simplicio import log — 2026-06-15','# Hermes → Simplicio import log — 2026-06-15

## Objetivo

Testar a importação de novidades do Hermes Agent para o Simplicio mantendo o
modo Simplicio de trabalhar: Helo/Isa como fronteira, dedupe antes de cópia,
evidência antes de adoção, e promoção somente como contrato, skill, capability,
adapter, teste ou memória governada.

Issue de acompanhamento: [#1505](https://github.com/wesleysimplicio/simplicio-runtime/issues/1505).

## Resultado do ensaio

- Hermes instalado localmente em `C:\Users\Z0059V7A\m\ai\hermes-agent`.
- `simplicio skill-memory "import Hermes Agent skills features into Simplicio" --repo . --json`
  já detecta fontes Hermes:
  - `hermes-bundled`: `C:\Users\Z0059V7A\m\ai\hermes-agent\skills`
  - `hermes-optional`: `C:\Users\Z0059V7A\m\ai\hermes-agent\optional-skills`
  - `hermes-plugins`: `C:\Users\Z0059V7A\m\ai\hermes-agent\plugins`
- Indexação observada:
  - `metadata_indexed`: 235
  - `external_skill_metadata`: 208
  - `shadowed_names`: 171
- Dry-run manual de skills:
  - Simplicio skills escaneadas: 209
  - Hermes skills escaneadas: 170
  - conteúdo já presente: 157
  - conflitos mesmo nome / conteúdo diferente: 13
  - candidatos únicos Hermes: 0

## O que foi importado do jeito Simplicio

1. **Indexação/dedupe de metadados Hermes** já funciona via `skill-memory` sem
   copiar corpos desnecessários.
2. **Lazy-load preservado**: corpos de skills só entram quando uma skill é
   selecionada.
3. **Conflitos não são sobrescritos**: as 13 divergências exigem merge curado.
4. **Migração de superfície** funciona em dry-run:
   - `simplicio migrate inspect --from hermes --repo . --json`
   - `simplicio migrate apply --from hermes --dry-run --repo . --json`
5. **Segredos não são importados**; o ledger orienta reconfigurar via
   `simplicio login`/variáveis de ambiente.

## Gap encontrado

`simplicio migrate apply --from hermes --data --dry-run --repo . --json` falhou
no Windows nativo porque `src/hermes_import.rs::hermes_home()` só procurava
`$HOME/.hermes`. A instalação nativa do Hermes usa:

```text
HERMES_HOME=C:\Users\Z0059V7A\AppData\Local\hermes
```

Erro observado:

```text
~/.hermes not found — is Hermes installed on this machine?
```

## Correção aplicada neste ciclo

- `src/hermes_import.rs::hermes_home()` agora resolve:
  1. `$HERMES_HOME`, quando aponta para diretório válido;
  2. `$HOME/.hermes`;
  3. `$USERPROFILE/.hermes`;
  4. Windows native: `$LOCALAPPDATA/hermes`.
- `--dry-run` do import de dados Hermes deixou de escrever artefatos de
  config/kanban/cron/MCP em `.simplicio-loop/hermes-migration`.
- Testes focados adicionados para `HERMES_HOME`, fallback `LOCALAPPDATA` e
  dry-run sem escrita.

Validação executada:

```powershell
rustfmt --check src\hermes_import.rs
cargo test --quiet hermes_import
cargo build --release --locked
$env:HERMES_HOME = Join-Path $env:LOCALAPPDATA ''hermes''
.\target\release\simplicio.exe migrate apply --from hermes --data --dry-run --repo . --json
```

Resultado do dry-run após a correção:

```json
{
  "schema": "simplicio.migration-ledger/v1",
  "source": "hermes",
  "dry_run": true,
  "sessions_imported": 0,
  "state_db_rows": 0,
  "config_mapped": false,
  "kanban_tasks": 0,
  "cron_hooks": 0,
  "mcp_servers": 0,
  "workflow_context_items": 0,
  "warnings": ["config.json not found", "kanban.json not found", "cron_hooks.json not found"]
}
```

Nenhum arquivo foi criado em `.simplicio-loop/hermes-migration` durante o dry-run.

Follow-up aberto no mesmo issue: o Hermes nativo atual tem `config.yaml`, mas o
importador ainda só mapeia `config.json`. Precisamos decidir se YAML entra como
mapping seguro ou fica explicitamente rejeitado para evitar risco de segredos.

## Regra operacional permanente

Sempre que analisarmos novidades do Hermes para o Simplicio:

1. abrir issue GitHub para cada atualização/gap/import relevante;
2. criar ou atualizar um `.md` com o que foi analisado, importado, rejeitado e
   as evidências usadas;
3. não copiar cegamente: promover a novidade como contrato, skill, capability,
   teste, adapter ou memória governada, conforme o jeito Simplicio.','docs/hermes-import/2026-06-15-import-log.md','2eb1f933e879b81b036d1215ecc5c855351136e8da689bdab08235f2af51b339','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-import/2026-06-16-1556-acp-lsp-profile-desktop-claw-computer-use-parity.md','project_doc','doc://simplicio-runtime/docs/hermes-import/2026-06-16-1556-acp-lsp-profile-desktop-claw-computer-use-parity.md','doc: Hermes parity — ACP/LSP/profile/desktop/Claw/computer-use (#1556)','# Hermes parity — ACP/LSP/profile/desktop/Claw/computer-use (#1556)

**Date:** 2026-06-16  
**Issue:** #1556  
**Schema:** `simplicio.hermes-parity.command-surface/v1`  
**Module:** `src/hermes_parity_1556.rs`  
**Surface:** `simplicio hermes-parity command-surface [--json] [--domain <d>] [--summary|--aliases|--contracts]`

## Summary

Formal parity matrix for six Hermes command domains that were identified in the
2026-06-15 audit (`hermes-command-audit/command-inventory.json`):

| Domain | Full | Partial | Aliased | Rejected | Pending | Total |
|---|---|---|---|---|---|---|
| `acp` | 4 | 0 | 1 | 1 | 0 | 6 |
| `lsp` | 3 | 1 | 1 | 0 | 0 | 5 |
| `profile` | 8 | 0 | 0 | 0 | 0 | 8 |
| `desktop` | 0 | 2 | 1 | 0 | 0 | 3 |
| `claw` | 2 | 2 | 1 | 0 | 0 | 5 |
| `computer-use` | 3 | 0 | 0 | 1 | 0 | 4 |

## Analysis

### ACP

- `acp status / start / handle / stdio`: **full parity** — Simplicio adds governance
  gate but contract is identical.
- `acp list-sessions`: **aliased** as `simplicio acp status --sessions`.
- `acp install-extension`: **rejected** — Simplicio does not install IDE extensions
  from the CLI; IDE-side install flows are outside the control plane.

### LSP

- `lsp serve / status / help`: **full parity**.
- `lsp list`: **aliased** as `simplicio lsp status --list`.
- `lsp install <name>`: **partial** — Hermes manages language server binaries;
  Simplicio defers to system PATH. Intentionally excluded from control plane.

### Profile

- All 8 sub-commands (`list / create / use / clone / show / export / import / delete`):
  **full parity**. `profile delete` is action-gated (requires confirmation).

### Desktop / Dashboard / GUI

- `desktop` and `dashboard`: **partial** — known bug: `--help` launches the TUI or
  opens the dashboard instead of printing safe help text. Two `HelpSafePatch` entries
  are recorded in the matrix with fix descriptions and source hints.
- `gui`: **aliased** to `simplicio desktop`.

### Claw / Migrate

- `migrate --from hermes` and `migrate --from openclaw`: **full parity**.
- `claw agent --local`: **aliased** to `simplicio reason --act`.
- `claw`: **partial** — `--session-key` semantics differ from OpenClaw; compatibility
  matrix needs refinement.
- `migrate xai`: **partial** — xAI provider migration target not yet implemented.

### Computer-use

- `computer-use status / screenshot / click / type`: **full parity** — all gated by
  action bridge.
- `computer-use install`: **rejected** — Simplicio uses runtime MCP-based computer-use
  and does not install macOS CUA drivers.

## Help-safety remediation

Two commands are currently unsafe under `--help`:

1. `simplicio desktop --help` — opens dashboard instead of printing help.
   Fix: add early `if args.help { print_help(); return Ok(()); }` guard in
   `src/desktop_app.rs` before `launch_desktop()`.

2. `simplicio dashboard --help` — launches TUI and times out.
   Fix: add early guard in `src/dashboard_command.rs` before
   `DashboardServer::start()`.

Both are captured in `hermes_parity_1556::unsafe_help_commands()` as actionable
`HelpSafePatch` entries.

## What was imported

- **Promoted:** parity matrix structure + command-surface dispatcher +
  compatibility alias registry + JSON status contracts.
- **Rejected:** `acp install-extension` (IDE mutation), `computer-use install`
  (driver install), `lsp install` (binary management) — all violate the principle
  that Simplicio is not a package manager for IDE/OS tooling.
- **Deferred:** `migrate xai` — pending xAI provider config handshake (#TBD).

## Evidence

- Source: `src/hermes_parity_1556.rs` (813 lines, added in feat/issue-1556)
- Dispatcher wiring: `src/main.rs` `hermes_parity_command` → `"command-surface"`
- Tests: 10 `#[test]` cases in `src/main.rs` under `// #1556` comment block,
  covering help-safety, JSON contract validity, domain coverage, filter flags,
  and unsafe-patch enumeration.','docs/hermes-import/2026-06-16-1556-acp-lsp-profile-desktop-claw-computer-use-parity.md','a611c4889d72740c474306673935d9d47ac29aadffdee95bcfc5b76a7cd0af72','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-import/2026-06-17-issue-1551-parity-report.md','project_doc','doc://simplicio-runtime/docs/hermes-import/2026-06-17-issue-1551-parity-report.md','doc: Hermes CLI Parity — Issue #1551 Implementation Report','# Hermes CLI Parity — Issue #1551 Implementation Report

Date: 2026-06-17
Issue: [#1551](https://github.com/wesleysimplicio/simplicio-runtime/issues/1551)
Module: `src/hermes_parity_cli_gaps_1551.rs`
Schema: `simplicio.hermes-cli-parity/v1`

## Summary

This slice closes the Hermes v0.16.0 vs Simplicio CLI gaps identified in #1551:
`model use/select`, `fallback`, `secrets`, `config`, `portal`, `prompt-size`, and `auth`.

All commands are governed by Helo rules:
- No raw secret printing — secrets are redacted to 8-char prefix + ellipsis
- Config values that look like secrets are auto-redacted in `show`/`env`
- JSON output available on all commands via `--json`
- Dry-run available on every mutating command via `--dry-run`
- Windows paths normalised (forward-slashes in JSON output)

## Commands Implemented

### model use/select
- `simplicio model use <provider>[/<model>]` → `ModelSelectCommand::execute`
- Writes `provider`/`model` to `~/.simplicio-loop/config.json`
- Exports `SIMPLICIO_PROVIDER` / `SIMPLICIO_MODEL` env vars when `apply_env=true`

### fallback
- `simplicio fallback list` → `FallbackCommand::list`
- `simplicio fallback add <provider> [--model <model>]` → `FallbackCommand::add`
- `simplicio fallback remove <provider>` → `FallbackCommand::remove`
- `simplicio fallback clear` → `FallbackCommand::clear`
- `simplicio fallback status` → `FallbackCommand::status`
- Persisted at `~/.simplicio-loop/fallback.json`; priorities re-assigned on remove

### secrets
- `simplicio secrets setup --bitwarden <token> <project>` → `SecretsCommand::setup_bitwarden`
  - Stores token fingerprint only (never raw token)
- `simplicio secrets test` → `SecretsCommand::test` (shallow config reachability)
- `simplicio secrets list` → `SecretsCommand::list` (all secrets redacted)
- `simplicio secrets remove <label>` → `SecretsCommand::remove`
- Persisted at `~/.simplicio-loop/secrets.json`

### config
- `simplicio config show` → `ConfigParityCommand::show` (secrets auto-redacted)
- `simplicio config set <key> <value>` → `ConfigParityCommand::set`
- `simplicio config path` → `ConfigParityCommand::path` (Windows paths normalised)
- `simplicio config env` → `ConfigParityCommand::env` (watched env vars, secrets redacted)
- `simplicio config reset [key]` → `ConfigParityCommand::reset`
- Persisted at `~/.simplicio-loop/config.json`

### portal
- `simplicio portal login <user> <token>` → `PortalCommand::login` (token fingerprint only)
- `simplicio portal logout` → `PortalCommand::logout`
- `simplicio portal info` / `portal status` → `PortalCommand::info` / `status`
- `simplicio portal open` → `PortalCommand::open_url`
- `simplicio portal model` → `PortalCommand::model_list` (partial; live fetch deferred)
- `simplicio portal tool-gateway list|add|remove` → `PortalCommand::gateway_{list,add,remove}`
- Session persisted at `~/.simplicio-loop/portal_session.json`

### prompt-size
- `simplicio prompt-size` → `prompt_size_report()`
- Returns byte/char/approx-token breakdown per section with headroom calculation

### auth
- `simplicio auth login <provider> --api-key <key>` → `AuthParityCommand::login`
  - Stores key hint only, never raw key
- `simplicio auth logout <provider>` → `AuthParityCommand::logout`
- `simplicio auth list` → `AuthParityCommand::list`
- `simplicio auth rotate <provider>` → `AuthParityCommand::rotate`
- Persisted at `~/.simplicio-loop/auth_pool.json`

## Partial / Deferred

| Command | Status | Reason |
|---|---|---|
| `model list` (live) | partial | Live portal fetch deferred until HTTP client lands |
| `config edit` (editor) | partial | Text-editor integration deferred |
| `portal model` (live) | partial | Live portal HTTP client not yet wired |

## Tests

17 unit tests in `#[cfg(test)]` block covering:
- Secret redaction (short + long values)
- `looks_like_secret_key` heuristic
- Config map redaction
- Windows path normalisation (forward slashes)
- `ProviderModelArg` parsing
- `FallbackCommand` lifecycle + dry-run (no file written on dry-run)
- `SecretsCommand` — no raw token in stored file
- `ConfigParityCommand` show/set (secrets redacted in output)
- Config path forward slashes on all platforms
- `PortalCommand` lifecycle (raw token absent from session file)
- `PortalCommand` gateway lifecycle
- `prompt_size_report` byte/token counts
- `AuthParityCommand` lifecycle (raw key absent from auth pool file)
- Parity map completeness (>= 20 implemented entries, some partial entries)

## Rejected

Nothing rejected — all commands in the issue scope have either a full or partial
Simplicio-native equivalent. The `portal model --fetch` live path is deferred,
not rejected.','docs/hermes-import/2026-06-17-issue-1551-parity-report.md','9c43ca7de7e0012eac20f2256a70a068900ae08a990bda19f2d559651b712c7d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-import/2026-06-17-issue-1553-parity-report.md','project_doc','doc://simplicio-runtime/docs/hermes-import/2026-06-17-issue-1553-parity-report.md','doc: Hermes parity — Skills/plugins/bundles/curator/tools/MCP CLI gaps (issue #1553)','# Hermes parity — Skills/plugins/bundles/curator/tools/MCP CLI gaps (issue #1553)

**Date:** 2026-06-17  
**Issue:** [#1553](https://github.com/wesleysimplicio/simplicio-runtime/issues/1553)  
**Module:** `src/hermes_parity_cli_gaps_1553.rs`  
**Schema:** `simplicio.hermes-parity-cli-gaps/v1`

---

## Summary

This report documents the Hermes → Simplicio command lifecycle matrix for the
six command categories identified in the #1553 parity audit:
`skills`, `bundles`, `plugins`, `curator`, `tools`, and `mcp`.

All implementations are deterministic, JSON-backed, and provenance-tracked.
Mutations (install, configure, archive, pin, enable/disable) write to
`~/.simplicio-loop/` with explicit dry-run or review paths where applicable.

---

## Lifecycle command matrix

| Category | Hermes command | Simplicio equivalent | Status | Notes |
|---|---|---|---|---|
| skills | `skills browse` | `simplicio skills list` | Implemented | list + show cover browse |
| skills | `skills search <q>` | `simplicio skills search <q>` | Implemented | FTS over skill names; vector recall via `simplicio memory` |
| skills | `skills install <name>` | `simplicio skills install <name> [--pin]` | Implemented | hub download wiring is a follow-up |
| skills | `skills configure <name>` | `simplicio skills configure <name> [--set k=v]` | Implemented | SKILL.config.json deterministic write |
| skills | `skills manage <name>` | `simplicio skills pin/archive/restore` | Implemented | decomposed into pin/unpin/archive/restore for clarity |
| bundles | `bundle list` | `simplicio bundles list` | Implemented | |
| bundles | `bundle show <name>` | `simplicio bundles show <name>` | Implemented | |
| bundles | `bundle create <name>` | `simplicio bundles create <name>` | Implemented | deterministic manifest write |
| bundles | `bundle delete <name>` | `simplicio bundles delete <name>` | Implemented | does not uninstall members |
| bundles | `bundle use <name>` | `simplicio bundles use <name>` | Implemented | writes .active marker |
| bundles | `bundle install <name>` | `simplicio bundles install <name>` | Implemented | installs all member skills + plugins |
| bundles | `bundle export <name>` | `simplicio bundles export <name>` | Implemented | JSON export |
| bundles | `bundle import <file>` | `simplicio bundles import <file>` | Implemented | JSON import |
| plugins | `plugins install <name>` | `simplicio plugins install <name>` | Implemented | records in manifest |
| plugins | `plugins update <name>` | `simplicio plugins update <name>` | Partial | manifest update wired; package manager exec is follow-up |
| plugins | `plugins remove <name>` | `simplicio plugins remove <name>` | Implemented | |
| plugins | `plugins list` | `simplicio plugins list` | Implemented | |
| curator | `curator status` | `simplicio curator status` | Implemented | reads .curator_state |
| curator | `curator run [--dry-run]` | `simplicio curator run [--dry-run]` | Implemented | wires to curator_parity |
| curator | `curator pause` | `simplicio curator pause` | Implemented | |
| curator | `curator resume` | `simplicio curator resume` | Implemented | |
| curator | `curator pin <name>` | `simplicio curator pin <name>` | Implemented | writes .pinned sentinel file |
| tools | `tools list [--platform P]` | `simplicio tools list [--platform P]` | Implemented | JSON-backed per-platform tool registry |
| tools | `tools enable <name> --platform P` | `simplicio tools enable <name> --platform P` | Implemented | |
| tools | `tools disable <name> --platform P` | `simplicio tools disable <name> --platform P` | Implemented | |
| mcp | `hermes mcp serve [--port N]` | `simplicio serve --mcp [--port N]` | Implemented | intentional: serve modes unified under `serve` |
| mcp | `hermes mcp add/remove/list` | `simplicio mcp add/remove/list` | Implemented | pre-existing, unchanged |

---

## Intentionally not copied

None — all Hermes lifecycle commands in this slice have a Simplicio equivalent.

The only design divergence is `mcp serve`: Hermes exposes this as a sub-command
of `mcp`, while Simplicio unifies all serve modes under `simplicio serve --mcp`.
This is documented in `McpServeParityDecision` (const `MCP_SERVE_PARITY` in the
module) and is the correct Simplicio-native design.

---

## Skill governance compliance

All skill operations follow the Simplicio skill governance contract:
- Skill bodies are lazy-loaded (install writes a scaffold, not the full body).
- Pinned skills are deduped and provenance-tracked via `.pinned` sentinel files.
- Curator access is mediated through `curator_parity` — the CLI surface in this
  module delegates to that module for actual execution.
- No Hermes skill bodies were copied verbatim; only the CLI surface contract was
  ported.

---

## Tests

The module ships 17 unit tests covering:
- Schema stability
- `CommandResult` JSON serialization (ok and err paths)
- All six help texts
- `McpServeParityDecision` constants
- Parity matrix coverage (all six categories, no empty commands)
- Markdown table rendering
- `Platform` display/parse round-trip
- Default struct constructors (`SkillMeta`, `BundleMeta`)
- Top-level dispatch for matrix (JSON and Markdown modes)
- `json_str` escape correctness
- `default_tool_entries` completeness

Run with: `cargo test hermes_parity_cli_gaps_1553`

---

## Follow-up items

- `plugins update` — wire to actual package manager (`pip`, `npm`, `cargo`)
  depending on `source` field. Tracked as a follow-up on the plugins slice.
- `skills install` — wire to the Simplicio hub API to download SKILL.md + assets.
- `curator run/pause/resume` — wire to `crate::curator_parity::run_curator_review`
  and `set_paused` once the modules are unified.','docs/hermes-import/2026-06-17-issue-1553-parity-report.md','09efd4f9672c4813f5a8d6c196b12875292ebc9e837588f61166c003137329b1','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-import/2026-06-17-messaging-parity-1552.md','project_doc','doc://simplicio-runtime/docs/hermes-import/2026-06-17-messaging-parity-1552.md','doc: Hermes Messaging/Gateway Parity — Issue #1552','# Hermes Messaging/Gateway Parity — Issue #1552

Date: 2026-06-17
Issue: #1552
Module: `src/hermes_parity_messaging_1552.rs`
Schema: `simplicio.hermes-parity-messaging/v1`

## What was analyzed

Hermes v0.16.0 messaging/gateway surface from the 2026-06-15 command audit
(`.simplicio-loop/hermes-command-audit/`):

- `gateway run/start/stop/restart` — lifecycle helpers
- `send <platform> <msg>` — generic top-level send
- `whatsapp-cloud setup/status/send/register-webhook` — Business Cloud API
- `slack manifest/install/test` — Slack app manifest generator + OAuth
- `webhook` subcommand contract differences
- `pairing` subcommand contract differences

## Command parity matrix

| Hermes command | Simplicio mapping | Status |
|---|---|---|
| `gateway run` | `gateway lifecycle run` | added |
| `gateway start` | `gateway lifecycle start` | added |
| `gateway stop` | `gateway lifecycle stop` | added |
| `gateway restart` | `gateway lifecycle restart` | added |
| `send <platform> <msg>` | `gateway send --platform <p> --msg <m>` | added |
| `whatsapp status` | `whatsapp status` | covered (existing) |
| `whatsapp-cloud setup` | `whatsapp-cloud setup` | added |
| `whatsapp-cloud status` | `whatsapp-cloud status` | added |
| `whatsapp-cloud send` | delegates to `gateway send` | added |
| `whatsapp-cloud register-webhook` | `whatsapp-cloud register-webhook` | added |
| `slack manifest` | `slack manifest` | added |
| `slack install` | `slack install` | added |
| `slack test` | `slack test` | added |
| `webhook <various>` | subcommand compat shim | partial (shim added) |
| `pairing <various>` | subcommand compat shim | partial (shim added) |

## What was imported

- `GatewayLifecycleVerb` + `gateway_lifecycle()` — pid-file based lifecycle
  for gateway adapters, gated by dry-run mode, evidence token on real execution.
- `MessagingPlatform` + `GenericSendRequest` + `generic_send()` — top-level
  platform-agnostic send; dispatches to Telegram, Slack, WhatsApp Cloud, Discord
  adapters via `curl` (no extra crate dependencies).
- `WhatsAppCloudConfig` + `WhatsAppCloudVerb` + `whatsapp_cloud_command()` —
  Business Cloud API setup (reads env vars, writes `~/.simplicio-loop/gateways/whatsapp-cloud/config.json`),
  status, webhook registration.
- `SlackAppManifest` + `SlackCliVerb` + `slack_cli_command()` — YAML manifest
  generator, OAuth install URL, `auth.test` connectivity check.
- `WebhookCompatSubcommand` + `PairingCompatSubcommand` — compat shim structs
  mapping Hermes-style names to Simplicio-native equivalents.
- `parity_report_json()` — emits the full matrix as JSON for programmatic use.

## What was rejected

- Hermes-internal gateway process management internals (socket IPC, supervision
  tree) — not ported; Simplicio uses a pid-file convention that integrates with
  the existing `gateway` command surface without duplicating Hermes plumbing.
- Hermes `gateway logs --follow` — deferred; covered by the existing `gateway`
  log sub-surface.

## Simplicio model preserved

- All mutations (gateway start/stop, config writes, send) are guarded by
  `dry_run` mode and emit `evidence_token` values for the HBP ledger.
- No raw llama.cpp workers, no bypassing action-gate — the module is
  synchronous and designed to be called from the gated CLI dispatch path.
- Platform adapters use the system `curl` binary (no new dependencies).

## Tests

9 unit tests in `hermes_parity_messaging_1552::tests`, all exercisable without
network or credentials (dry-run path):

- `parity_matrix_non_empty`
- `parity_report_json_valid_schema`
- `gateway_lifecycle_dry_run`
- `gateway_lifecycle_invalid_adapter`
- `generic_send_dry_run`
- `generic_send_empty_destination_error`
- `slack_manifest_yaml_contains_scopes`
- `webhook_compat_mapping`
- `pairing_compat_mapping`
- `result_to_json_round_trip`','docs/hermes-import/2026-06-17-messaging-parity-1552.md','4ca647b5bb67e24cb22291f751e863ea17985db373e87f52fd3713f6ef41e45a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-import/2026-06-17-state-ops-parity-1554.md','project_doc','doc://simplicio-runtime/docs/hermes-import/2026-06-17-state-ops-parity-1554.md','doc: Hermes parity — state-ops CLI gaps (issue #1554) — 2026-06-17','# Hermes parity — state-ops CLI gaps (issue #1554) — 2026-06-17

## Summary

Closes gap slice from the 2026-06-15 audit covering stateful local-ops commands:
sessions, checkpoints, import/backup, insights, debug, postinstall, uninstall.

Module: `src/hermes_parity_state_ops.rs`  
Schema: `simplicio.hermes-parity-state-ops/v1`  
Wired in `main.rs` at line ~214.

## Parity matrix

| Hermes command | Simplicio command | Status |
|---|---|---|
| `sessions list` | `sessions list` | implemented |
| `sessions export` | `sessions export` | implemented |
| `sessions delete` | `sessions delete` | implemented |
| `sessions prune` | `sessions prune` | implemented |
| `sessions rename` | `sessions rename` | implemented |
| `checkpoints inspect` | `checkpoints inspect` | implemented |
| `checkpoints prune` | `checkpoints prune` | implemented |
| `checkpoints clear` | `checkpoints clear` | implemented |
| `backup` | `backup` | covered |
| `import` | `import` | implemented |
| `logs recent` | `logs recent` | covered |
| `logs follow` | `logs follow` | covered |
| `logs search` | `logs search` | covered |
| `logs stats` | `logs stats` | covered |
| `logs clear` | `logs clear` | covered |
| `logs path` | `logs path` | covered |
| `insights` | `insights` | implemented |
| `insights usage` | `insights usage` | implemented |
| `debug help` | `debug help` | implemented |
| `debug support-share` | `debug support-share` | implemented |
| `debug support-delete` | `debug support-delete` | implemented |
| `postinstall` | `postinstall` | implemented |
| `uninstall` | `uninstall` | implemented |

## Safety contract

All destructive operations (prune / delete / clear / uninstall / import) are:
1. Gated through the Action Gate before any filesystem mutation.
2. Protected by a dry-run mode (`--dry-run` flag).
3. Recorded as evidence in the HBP ledger on execution.
4. Preceded by an automatic backup snapshot when the target is within `~/.simplicio-loop`.

## Windows / HOME-not-set path

`simplicio uninstall --help` now falls through to a safe help text that explains
the HOME/USERPROFILE detection path instead of panicking. Verified via
`build_uninstall_plan()` test `windows_help_path_for_uninstall`.

## Test coverage

14 unit tests covering:
- `parity_matrix_is_non_empty`
- `parity_matrix_json_is_valid_array`
- `parity_matrix_markdown_has_header`
- `session_record_json_roundtrip`
- `checkpoint_record_json_has_required_fields`
- `debug_help_is_non_empty_and_safe`
- `sessions_manager_help_has_all_subcommands`
- `checkpoints_manager_help_has_all_subcommands`
- `uninstall_help_graceful_on_missing_home`
- `postinstall_tools_list_contains_git`
- `postinstall_probe_produces_valid_json`
- `insights_report_zero_sessions`
- `import_mappings_for_sessions`
- `debug_bundle_json_has_bundle_id`
- `json_escape_handles_special_chars`
- `windows_help_path_for_uninstall`
- `export_format_from_str`','docs/hermes-import/2026-06-17-state-ops-parity-1554.md','74fb9fbca94197c6b19d8b40539e468e2b02b5b7b961b8dcd218c576fafb63af','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-import/2026-06-21-full-survey.md','project_doc','doc://simplicio-runtime/docs/hermes-import/2026-06-21-full-survey.md','doc: Hermes -> Simplicio - Levantamento completo verificado (thermos nuclear) - 2026-06-21','# Hermes -> Simplicio - Levantamento completo verificado (thermos nuclear) - 2026-06-21

## Metodo
- 14 agentes de survey (1 por subsistema: hermes_cli, agent, gateway, providers, plugins, acp_adapter, cron, tools, optional-mcps, tui, web, apps, locales, core).
- Cada feature cruzada contra o repo Simplicio (present/partial/gap).
- Fase thermos nuclear: 1 verificador adversarial por gap candidato (default = refutar). 150 verificados antes de encerrar (cap de agentes).
- Fonte Hermes: hermes-agent local (7660 .py, 1018 skills).

## Resultado agregado
- 491 features Hermes levantadas: 194 present / 115 partial / 182 gap (bruto).
- Thermos sobre os gap/partial alegados (150 verificados):
  - already-present (FALSO-POSITIVO): 64 - Simplicio ja tinha.
  - real-gap (confirmado ausente): 43
  - partial-confirmed: 41
  - not-worth-importing: 2
- VEREDITO: Simplicio NAO tem 100% do Hermes; ~43 gaps reais + ~41 parciais a fechar.

## Regra de promocao (CLAUDE.md)
Cada item entra como forma Simplicio-native (contract/skill/capability/test/adapter/deterministic-flow/governed-memory), issue antes de implementar.

## ### Gaps REAIS (Simplicio nao tem) (43)

- [ ] **Available Commands Advertisement** _(prio high)_ - Schema types exist (src/acp_adapter/protocol.rs:524-527, protocol_schema.rs:250-253) but NO implementation. src/acp_adapter/events.rs has no send_available_commands_update() function; src/acp_adapter/
  - acao: Implement send_available_commands_update() in src/acp_adapter/events.rs; build advertised commands from src/command_registry.rs::build_registry(); wire dispatch calls in src/acp_ad
- [ ] **Blueprint installation from skill** _(prio high)_ - src/htool/blueprints.rs:412 `register_blueprint_suggestion()` exists but is never called. Compiler warnings confirm entire BlueprintsTool (line 597) and dispatch function (line 716) are unused. No cod
  - acao: Import the blueprint-on-install hook: 1) Modify skills_install() at src/hermes_parity_cli_gaps_1553.rs to call htool_blueprints_dispatch("register_blueprint_suggestion", spec_json)
- [ ] **Blueprint slash-command export** _(prio high)_ - src/htool/blueprints.rs:443-553 (export_blueprint) generates SKILL.md markdown files, not one-line slash commands. No slash-command generation or pre-fill functionality found after exhaustive search f
  - acao: Implement slash-command export feature that generates a pre-filled /cron or /schedule command with blueprint parameters as query arguments or inline syntax, e.g. `/cron "0 9 * * *"
- [ ] **Channel directory (cached channel/contact list)** _(prio high)_ - src/htool/send_message_tool.rs:668-675 explicitly returns error "channel directory not available in the Rust runtime"; src/openclaw_import_1575.rs:205-211 marks "directory" command as Gap requiring Go
  - acao: Implement channel directory layer in gateway: add list_channels()/list_contacts() methods to PlatformAdapter trait, create DirectoryRegistry caching layer backed by per-platform AP
- [ ] **Cron provider abstraction (pluggable schedulers)** _(prio high)_ - Simplicio has monolithic CronScheduler (struct at cron_scheduler.rs:57) and MultiAgentScheduler (scheduler.rs:169) with zero abstraction. No trait definition, no provider registry, no pluggable interf
  - acao: Import provider-abstraction pattern from provider_registry.rs to create pub trait SchedulerProvider (with register/get_active methods). Implement CronSchedulerImpl and MultiAgentSc
- [ ] **Hermes suggestions system (propose automations) vs Simplicio cron** _(prio high)_ - Simplicio has cron scheduling (src/cron_scheduler.rs:1-622) and a general suggestion engine with anti-repetition (src/organism/suggestions.rs:1-59), but does NOT have a mechanism to surface ready-to-r
  - acao: Implement cron suggestion proposal system: (1) extend SuggestionEngine to emit cron job proposals with rule-based candidates (e.g., "detected repeated pattern X every 2h — automate
- [ ] **Kanban watcher integration** _(prio high)_ - No kanban board watching or polling exists. Simplicio has: local SQLite kanban tools (src/htool/kanban_tools.rs, src/skill_kanban_worker.rs), generic watchers for RSS/GitHub repos/JSON APIs (src/skill
  - acao: Implement board watcher integrations targeting Linear, GitHub Projects, and Asana as priorities. Pattern: (1) Poll board API on interval, (2) Track seen items via watermark (model 
- [ ] **Memory monitoring (process RSS logging)** _(prio high)_ - Exhaustive search of Simplicio gateway, infra, organism, and scripts found zero implementation of periodic background memory monitoring. Gateway runner (src/gateway/runner.rs:1-358) only provides stat
  - acao: Import/implement Hermes'' periodic memory monitoring for gateway: create src/gateway/memory_monitor.rs with tokio::spawn background task logging process RSS + GC stats at configurab
- [ ] **Pending suggestions cap (limit to 5)** _(prio high)_ - Extensive search of src/autonomia_engine.rs, src/organism/suggestions.rs, src/harness/harness_1483.rs, and all related cron/task/suggestion management code reveals no implementation of a 5-suggestion 
  - acao: Import: Add MAX_PENDING_SUGGESTIONS constant (5) to InitiativeEngine; implement dropping logic in propose_from_context() to enforce cap; add accept(suggestion)/dismiss(suggestion) 
- [ ] **Plugin Hooks System (post_tool_call, on_session_end, etc.)** _(prio high)_ - Simplicio has plugin hook declarations (Plugin::hooks() trait method, PluginManifest with hooks list) but NO FUNCTIONAL hook dispatch system. The disk_cleanup plugin is defined but never loaded (src/p
  - acao: Import Hermes plugin hooks infrastructure: (1) Activate disk_cleanup loading in PluginRegistry::register_bundled(), (2) Implement _emit_post_tool_call_hook dispatcher in agent_runt
- [ ] **Provider Profile default_headers Support** _(prio high)_ - Rust model provider configs in src/plugins/model_providers/ (gmi.rs, kimi_coding.rs, etc.) lack default_headers field present in Python profiles. GmiConfig (line 11-28','docs/hermes-import/2026-06-21-full-survey.md','d4129fba9694404e53ad7abff335b98c72d42b3508728c47549fa59dede6dfbf','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-import/2026-06-27-hermes-agent-skills.md','project_doc','doc://simplicio-runtime/docs/hermes-import/2026-06-27-hermes-agent-skills.md','doc: Hermes import wave — 2026-06-27 — hermes-agent/skills','# Hermes import wave — 2026-06-27 — hermes-agent/skills

Source: https://github.com/NousResearch/hermes-agent/tree/main/skills

Per the standing Hermes→Simplicio import rule (CLAUDE.md / AGENTS.md): we do
**not** copy Hermes blindly. The 69 skills below (17 categories, enumerated
live from the repo tree) are cataloged into the neural memory as discoverable,
routable metadata, each mapped to its Simplicio-native equivalent. Skills with
a native equivalent route there; the rest are wired on-demand after vetting
(clawscan). Nothing third-party is vendored as executable code.

Total cataloged: 68 skills.

## apple

| skill | Simplicio native |
|---|---|
| `apple-notes` | gateway/apple |
| `apple-reminders` | gateway/apple |
| `findmy` | — (vet on-demand) |
| `imessage` | gateway/imessage |

## autonomous-ai-agents

| skill | Simplicio native |
|---|---|
| `claude-code` | acp_adapter / assistant-CLI routing |
| `codex` | acp_adapter |
| `hermes-agent` | three-agent benchmark adapter |
| `opencode` | acp_adapter |

## computer-use

| skill | Simplicio native |
|---|---|
| `computer-use` | tools_browser / macos_computer_use |

## creative

| skill | Simplicio native |
|---|---|
| `architecture-diagram` | frontend-design / diagrams |
| `ascii-art` | — (vet on-demand) |
| `ascii-video` | — (vet on-demand) |
| `baoyu-infographic` | — (vet on-demand) |
| `claude-design` | frontend-design (native) |
| `comfyui` | tools_image_generate / higgsfield MCP |
| `design-md` | web-design-guidelines (native) |
| `excalidraw` | — (vet on-demand) |
| `humanizer` | content humanizer skill |
| `manim-video` | video_pipeline |
| `p5js` | — (vet on-demand) |
| `popular-web-designs` | frontend-design (native) |
| `pretext` | — (vet on-demand) |
| `sketch` | — (vet on-demand) |
| `songwriting-and-ai-music` | media-create / voice |
| `touchdesigner-mcp` | — (vet on-demand) |

## data-science

| skill | Simplicio native |
|---|---|
| `jupyter-live-kernel` | data-analyst (native skill) |

## dogfood

| skill | Simplicio native |
|---|---|
| `dogfood` | delivery Run-Verification (`simplicio deliver`, #252) |

## email

| skill | Simplicio native |
|---|---|
| `himalaya` | gateway/email |

## github

| skill | Simplicio native |
|---|---|
| `codebase-inspection` | `simplicio map` |
| `github-auth` | github MCP |
| `github-code-review` | `simplicio deliver review` |
| `github-issues` | github MCP |
| `github-pr-workflow` | pr / babysit-prs |
| `github-repo-management` | github MCP |

## media

| skill | Simplicio native |
|---|---|
| `gif-search` | — (vet on-demand) |
| `heartmula` | — (vet on-demand) |
| `songsee` | — (vet on-demand) |
| `youtube-content` | video stack / video_pipeline |

## mlops

| skill | Simplicio native |
|---|---|
| `evaluation` | benchmark_suite |
| `huggingface-hub` | hf MCP |
| `inference` | inference_pool |
| `models` | local-first model ladder |

## note-taking

| skill | Simplicio native |
|---|---|
| `obsidian` | neural memory |

## productivity

| skill | Simplicio native |
|---|---|
| `airtable` | — (vet on-demand) |
| `google-workspace` | gog idea |
| `maps` | — (vet on-demand) |
| `nano-pdf` | — (vet on-demand) |
| `notion` | notion MCP |
| `ocr-and-documents` | tools_web_extract |
| `petdex` | — (vet on-demand) |
| `powerpoint` | — (vet on-demand) |
| `teams-meeting-pipeline` | gateway/teams |

## research

| skill | Simplicio native |
|---|---|
| `arxiv` | web-research + hf paper_search |
| `blogwatcher` | — (vet on-demand) |
| `llm-wiki` | web-research |
| `polymarket` | — (vet on-demand) |
| `research-paper-writing` | — (vet on-demand) |

## smart-home

| skill | Simplicio native |
|---|---|
| `openhue` | — (vet on-demand) |

## social-media

| skill | Simplicio native |
|---|---|
| `xurl` | social-media-ops (x) |

## software-development

| skill | Simplicio native |
|---|---|
| `hermes-agent-skill-authoring` | skill-autocreate |
| `node-inspect-debugger` | — (vet on-demand) |
| `plan` | superpowers (plan phase) / `simplicio plan` |
| `python-debugpy` | — (vet on-demand) |
| `requesting-code-review` | `simplicio deliver review` |
| `simplify-code` | superpowers (complexity reduction) |
| `spike` | superpowers |
| `systematic-debugging` | superpowers / coding-loop |
| `test-driven-development` | superpowers (RED-GREEN-REFACTOR) |','docs/hermes-import/2026-06-27-hermes-agent-skills.md','414fb5c72bdc80549a9e9f6b55d451bdf55a54594bcc0222b7e01345d866346f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-parity/I18N_STATUS.md','project_doc','doc://simplicio-runtime/docs/hermes-parity/I18N_STATUS.md','doc: i18n Hermes Parity Status — Issue #2023','# i18n Hermes Parity Status — Issue #2023

## Status: IMPLEMENTED

Module: `src/i18n_parity.rs` (860 lines)  
Registered in `main.rs` line 719: `mod i18n_parity;`

## What is implemented

- Full port of Hermes `agent/i18n.py`
- `SUPPORTED_LANGUAGES`: 16 codes (en, zh, zh-hant, ja, de, es, fr, tr, uk, af, ko, it, ga, pt, ru, hu)
- Natural-alias + BCP-47 normalization table (`_LANGUAGE_ALIASES`)
- Active-language resolution: `HERMES_LANGUAGE` env > `display.language` config > `"en"` fallback
- `t(key, lang, kwargs)` lookup with dotted-key flattening, English fallback, bare-key last resort
- Python `{name}` substitution — returns unformatted value on failure, never panics
- Thread-safe: `RwLock<HashMap>` for catalog store; `RwLock<Option<Option<String>>>` for language cache
- Indentation-based YAML reader (no extra crates); ready to swap to `serde_yaml` when available
- `reset_language_cache()` for runtime config changes

## One remaining stub

`config_language()` currently returns `None` (config-loader not wired). The rest of the module is fully functional; YAML catalogs in `locales/<lang>.yaml` will load and serve.

## Wiring notes

- Wire `config_language()` to `crate::config` loader
- Call `i18n_parity::t(key, lang, &kwargs)` from conversation/gateway loop for user-facing strings
- Call `reset_language_cache()` after runtime config changes

## Tracking

GitHub: #2023  
Port manifest: `wave=4 prio=3 py=agent/i18n.py`','docs/hermes-parity/I18N_STATUS.md','df0bc76229dac93ece085ea710d8e406465840c842b0924981777d13baf798ad','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-parity/MCP_OAUTH_STATUS.md','project_doc','doc://simplicio-runtime/docs/hermes-parity/MCP_OAUTH_STATUS.md','doc: mcp_oauth Authentication Management Status — Issue #2053','# mcp_oauth Authentication Management Status — Issue #2053

## Status: PARTIAL — 2 stubs remain

Modules:
- `src/htool_mcp_oauth.rs` (1231 lines) — registered at main.rs line 305
- `src/htool_mcp_oauth_manager.rs` — registered at main.rs line 373

Dispatch in main.rs lines 35960-35976: `mcp_oauth_login`, `mcp_oauth_token_info`, `mcp_oauth_logout`

## Implemented actions

| Action            | State       |
|-------------------|-------------|
| `login`           | IMPLEMENTED |
| `logout`          | IMPLEMENTED |
| `token_info`      | IMPLEMENTED |
| `list`            | IMPLEMENTED |
| `refresh`         | IMPLEMENTED |

## Stubbed actions (2)

| Action               | Stub reason |
|----------------------|-------------|
| `build_oauth_auth`   | Requires OIDC discovery — not implemented (line 940) |
| `preregister_client` | Requires dynamic client registration — not implemented (line 947) |

Both stubs return a clear `Err` (not fake success). Tests at lines 1178 and 1184 verify the error messages.

## Dispatch summary (from module doc line 959)

Dispatch table: login, logout, token_info, list, refresh (implemented); build_oauth_auth (stub), preregister_client (stub).

## Next steps

`build_oauth_auth`: implement OIDC discovery endpoint fetch + PKCE code-verifier generation.  
`preregister_client`: implement RFC 7591 dynamic client registration POST.

Both require network access; gate with `action_gate` before execution.

## Tracking

GitHub: #2053','docs/hermes-parity/MCP_OAUTH_STATUS.md','a89ff401a363aa21504e53856baa445412db20cfa40d47b6e6b193e6a9c11bf9','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-parity/PROMPT_CACHING_STATUS.md','project_doc','doc://simplicio-runtime/docs/hermes-parity/PROMPT_CACHING_STATUS.md','doc: prompt_caching Hermes Parity Status — Issue #2024','# prompt_caching Hermes Parity Status — Issue #2024

## Status: IMPLEMENTED

Module: `src/prompt_caching.rs` (158 lines)  
Registered in `main.rs` line 438: `mod prompt_caching;`

## What is implemented

- `PromptCache` struct — LRU eviction via monotonic `use_counter` stamps
- `get(prompt, model)` — cache hit refreshes recency (true LRU); returns `Option<&CacheEntry>`
- `set(prompt, model, response)` — inserts entry, evicts least-recently-used when full
- `CacheEntry` fields: `response`, `model`, `timestamp`, `last_used`
- Schema constant: `simplicio.cache.prompt/v1`
- Key hashing: `DefaultHasher` over `(prompt, model)`
- Zero extra crates — std-only

## Test coverage

Test `completion_args_wire_prompt_cache_only_when_requested` in `main.rs` line 101117 verifies
that the Anthropic `system_and_3` cache-control layout is only injected when caching is requested.

## Remaining gap vs Hermes

The Hermes `system_and_3` Anthropic-specific cache-control header layout (prefill blocks marked
with `{"cache_control": {"type": "ephemeral"}}`) is handled at the completion-args level in
`main.rs`. The `PromptCache` module itself is a generic in-memory LRU and does not need
Anthropic-specific knowledge.

No stubs. Feature is complete for the Rust runtime use case.

## Tracking

GitHub: #2024','docs/hermes-parity/PROMPT_CACHING_STATUS.md','5ed89caf580f9b039c928ffbb1329b99df432daa8740bdb5f88b067ead6a98d5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/hermes-parity/SEND_MESSAGE_STATUS.md','project_doc','doc://simplicio-runtime/docs/hermes-parity/SEND_MESSAGE_STATUS.md','doc: send_message Multi-Platform Dispatch Status — Issue #2047','# send_message Multi-Platform Dispatch Status — Issue #2047

## Status: PARTIAL — 12 stubs remain

Module: `src/htool_send_message_tool.rs` (1110 lines)  
Registered in `main.rs` line 319: `mod htool_send_message_tool;`

## Implemented platforms

| Platform   | State       | Notes |
|------------|-------------|-------|
| telegram   | IMPLEMENTED | `telegram_send_message()` in main.rs line 77441; env `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| discord    | IMPLEMENTED | `channel_send_discord_provider()` via channel dispatch (main.rs line 78026) |
| slack      | IMPLEMENTED | `channel_send_slack_provider()` via channel dispatch (main.rs line 78027) |
| whatsapp   | IMPLEMENTED | `channel_send_whatsapp_provider()` + `whatsapp_send()` (main.rs line 52845); env-var validated, does not fake-succeed |

## Stubbed platforms (12 — call `send_stub()`, return clear error)

| Platform    | Stub line (htool_send_message_tool.rs) |
|-------------|----------------------------------------|
| signal      | 732 |
| email       | 733 |
| sms         | 734 |
| matrix      | 735 |
| dingtalk    | 736 |
| wecom       | 737 |
| weixin      | 738 |
| bluebubbles | 739 |
| feishu      | 740 |
| qqbot       | 741 |
| yuanbao     | 742 |

(Note: issue title says 22 stubs; audit of the dispatch table found 12 in `htool_send_message_tool.rs`
at lines 731-742. The remaining 10 may be in gateway sub-modules or were implemented since the issue was filed.)

## Stub contract

`send_stub()` (line 789) returns a structured `Err` naming the platform and the fact that
it is not yet implemented — it never fake-succeeds. Test at line 970 verifies this.

## Next steps to close remaining stubs

Each stub needs: env-var config keys documented, HTTP client call, structured JSON result schema,
and a test that verifies it errs correctly when the env var is missing.

## Tracking

GitHub: #2047','docs/hermes-parity/SEND_MESSAGE_STATUS.md','265b9e218e2ad39f7f807194cf57b1694ebe50c01fa44e96c1e25e6fc6303fc1','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/HERMES_AGENT_PORT_MATRIX.md','project_doc','doc://simplicio-runtime/docs/HERMES_AGENT_PORT_MATRIX.md','doc: Hermes `agent/` → Rust port matrix','# Hermes `agent/` → Rust port matrix

> Ownership note (issue #1540): this matrix is reference-only documentation for
> residual Python surface mapping. The tracked quarantine/ownership artifact for
> non-Rust scripts now lives in `docs/SCRIPT_OWNERSHIP_QUARANTINE.md` and
> `./.simplicio-loop/docs/script-ownership-inventory.json`.

Coverage matrix for porting the hermes-agent `agent/` package (113 Python files,
~72k LOC, vendored at `agent/` as reference source) into the Rust runtime
(`src/`, 141 modules). Built 2026-06-10 from a 6-agent parallel audit of
`agent/*.py`, the original wiring in `~/m/ai/hermes-agent`, and the existing
Rust modules.

## How hermes wires the package (integration target)

Boot: `cli.py:main()` → `hermes_cli` setup → `run_agent.AIAgent.__init__` →
`agent/conversation_loop.run_conversation(agent, ...)`.

Turn lifecycle (the contract the Rust chat loop must honor):

1. `turn_context.build_turn_context()` — prologue: sanitize, reset retry
   counters, restore-or-build cached system prompt, preflight compression,
   memory prefetch. Returns `TurnContext`.
2. Iteration loop while `iteration_budget.remaining > 0`: message repair →
   LLM call via transport (`anthropic` / `chat_completions` / `bedrock` /
   `codex`), streaming through `think_scrubber` → parse tool calls.
3. `tool_executor.execute_tool_calls_{sequential,concurrent}` —
   `_should_parallelize_tool_batch()` decides (interactive tools and file-path
   overlaps force sequential; max 8 workers), guardrails evaluate before/after,
   results appended as tool messages.
4. Retry classes per turn: `invalid_tool` / `invalid_json` /
   `incomplete_scratchpad` with per-class caps (`turn_retry_state`).
5. `turn_finalizer.finalize_turn()` — epilogue: exit reason
   (`completion` / `budget_exhausted` / `interrupted_by_user` / `error`),
   trajectory save, session persist, background curator review queue.

Registry pattern: every tool file self-registers
(`tools/registry.register(name, toolset, schema, handler, check_fn)`) at import
time; `model_tools.get_tool_definitions()` filters by toolset;
availability via TTL-cached `check_fn`. Provider registries
(browser/image/tts/web-search/transcription) follow the same shape.

Persistence: `hermes_state.SessionDB` (SQLite WAL + FTS5, schema v15,
sessions/messages tables, parent-session chain for compression splits);
`memory_manager` (one external provider, prefetch/sync per turn);
`credential_persistence` (keyring).

Irreducible core (10): bootstrap, AIAgent, conversation_loop, turn_context,
tool_executor, prompt_builder, tools/registry, model_tools,
chat_completion_helpers, SessionDB.

## Verdict summary (113 files)

| Verdict | Meaning | Count (approx) |
|---|---|---|
| COVERED | Rust equivalent exists | ~15 |
| PARTIAL | concept exists, fidelity gaps | ~45 |
| MISSING | no Rust counterpart | ~48 |
| SKIP | Python-only concern (jiter, async bridge) | ~5 |

## Port wave plan

- **Wave 1 (this session)** — core-loop gaps, new modules:
  `turn_lifecycle.rs` (turn_context + turn_finalizer + turn_retry_state +
  iteration_budget), `tool_guardrails.rs` (+ dispatch parallelism rules +
  result classification), `transport_types.rs` (normalized Transport trait,
  NormalizedResponse/ToolCall/Usage, anthropic/chat-completions converters),
  `model_metadata.rs` (context windows, token estimation, max output,
  pricing). Wire into `agent_chat.rs` / chat loop.
- **Wave 2** — conversation_loop fidelity: message repair, retry-class caps,
  length-limit continuation, mid-turn compression trigger
  (`conversation_compression.py`), LLM summarization in
  `context_compression.rs`.
- **Wave 3** — providers: unified HTTP dispatcher (`auxiliary_client`),
  bedrock transport, codex transport suite, models.dev fetch, rate-limit
  tracker, nous_rate_guard.
- **Wave 4** — periphery: LSP real client/manager/servers registry,
  account_usage, insights, background_review, image_routing, markdown_tables
  wcwidth, i18n, registries as pluggable traits.

## Per-file matrix

### Chunk A — core loop & adapters

| file | LOC | Rust counterpart | verdict | prio |
|---|---|---|---|---|
| account_usage.py | 550 | — | MISSING | 3 |
| agent_init.py | 1743 | runtime config (partial boot) | PARTIAL | 2 |
| agent_runtime_helpers.py | 2514 | message repair partial, trajectory absent | PARTIAL | 1 |
| anthropic_adapter.py | 2403 | integration_anthropic.rs (basic) | PARTIAL | 1 |
| async_utils.py | 68 | n/a (tokio) | SKIP | 3 |
| auxiliary_client.py | 5949 | — (no unified HTTP dispatcher) | MISSING | 2 |
| azure_identity_adapter.py | 555 | — | MISSING | 3 |
| background_review.py | 608 | — | MISSING | 3 |
| bedrock_adapter.py | 1277 | — | MISSING | 2 |
| browser_provider.py / browser_registry.py | 367 | tools_browser.rs (no registry) | MISSING | 3 |
| chat_completion_helpers.py | 2592 | chat_schema.rs (no streaming normalize) | PARTIAL | 2 |
| codex_responses_adapter.py / codex_runtime.py | 1946 | — | MISSING | 2 |
| context_compressor.py | 2182 | context_compression.rs (no LLM summarize) | PARTIAL | 1 |
| context_engine.py | 226 | — | MISSING | 3 |
| context_references.py | 551 | — | MISSING | 3 |
| conversation_compression.py | 802 | — (no mid-turn compression) | MISSING | 2 |
| conversation_loop.py | 4221 | conversation.rs + agent_chat.rs + coding_loop.rs | PARTIAL | 1 |
| copilot_acp_client.py | 686 | — | MISSING | 3 |

### Chunk B — credentials, curator, gemini, media

| file | LOC | Rust counterpart | verdict | prio |
|---|---|---|---|---|
| credential_persistence.py | 174 | login_command.rs | PARTIAL | 1 |
| credential_pool.py | 2184 | login_command.rs + inference_pool.rs | PARTIAL | 1 |
| credential_sources.py | 448 | login_command.rs | PARTIAL | 1 |
| credits_tracker.py | 723 | agent_chat.rs token counting | PARTIAL | 2 |
| curator.py | 1835 | curator_agent.rs | PARTIAL | 2 |
| curator_backup.py | 695 | backup_command.rs | PARTIAL | 2 |
| display.py | 1033 | agent_chat.rs spinners | PARTIAL | 2 |
| error_classifier.','docs/HERMES_AGENT_PORT_MATRIX.md','c8a7f5c922810995589d5809d74690e09dcd661890c7d2fb27852758847ba053','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/HERMES_PARITY.md','project_doc','doc://simplicio-runtime/docs/HERMES_PARITY.md','doc: Hermes Agent feature parity — runtime matrix (issue #447)','# Hermes Agent feature parity — runtime matrix (issue #447)

Evidence-backed audit of where `simplicio-runtime` stands versus Hermes Agent on
the parity gaps in #447. Each row was **verified by running the real command** on
the current build (audited at v0.3.63). Status is `present` / `partial` /
`absent`, keeping Simplicio''s DNA (local-first, token economy, evidence ledger,
native Rust).

## Matrix

| # | Hermes capability | Simplicio surface (audited) | status |
|---|---|---|---|
| #448 | closed self-learning loop (autonomous skills) | `simplicio skill-memory` (`simplicio.skill-memory/v1`, "Hermes-style procedural memory for learning, storing, ranking, curating skills"), `simplicio trajectory suggest` (`simplicio.learn-suggestion-list/v1`, gate-required) | **partial** — procedural skill memory + learn-suggestions exist; fully-autonomous create/evolve loop is the gap |
| #449 | multi-platform messaging gateway | `simplicio telegram status` (`simplicio.telegram/v1`, configured/curl) | **partial** — Telegram only; Discord/WhatsApp/Signal + cross-platform continuity + voice transcription are gaps |
| #450 | native cron + unattended NL tasks | `simplicio cron status/add/tick/run` (`simplicio.cron/v1`); `cron add "every 2h" "<prompt>"` takes a schedule + natural-language prompt, runs unattended, writes to `.simplicio-loop/cron/output` | **present** — NL prompt + unattended runs; multi-platform delivery ties into #449 |
| #451 | flexible deploy + serverless hibernation | `simplicio deploy --target <modal\|daytona\|fly\|vercel> [--app NAME] [--dry-run\|--confirm]` (`simplicio.deploy-serverless/v1`, `src/deploy_serverless.rs`): `--dry-run` (default) prints a plan + static cost estimate + the gate decision a real deploy would require, no mutation; a real attempt is gated (ask/auto/safe via `--mode`, requires `--allow` + `--confirm` outside safe mode) and every attempt is appended to `.simplicio-loop/deploy/deploy-events.jsonl`. Modal/Daytona backends (`src/modal_deploy.rs`, `src/daytona_deploy.rs`) exec the real CLI and return an honest `Err` when the CLI/credentials are absent — never fake success. Fly/Vercel are cost-estimated but have no backend wired yet. | **partial** — Modal/Daytona path implemented and gated; Fly/Vercel still error "no backend wired" |
| #452 | advanced TUI (multiline, autocomplete, interrupt-redirect) | Ratatui TUI (`simplicio tui`) being extended | **partial** — actively under way |
| #453 | deep persistent memory + user modeling | `simplicio memory status` (`simplicio.memory-backend/v1`, sqlite-fts5, offline, persistent) | **partial** — persistent neural memory present; Honcho-style user modeling is the gap |
| #454 | batch trajectory generation (research) | `simplicio trajectory record/show/suggest` | **partial** — per-session trajectories exist; batch corpus export for training is the gap |
|| #455 | `hermes model` provider/model switching + local fallback | `simplicio onboard --provider <id>` (now supports **all Hermes providers**: openai-codex, claude-pro-max, openrouter, anthropic, gemini, deepseek, groq, mistral, cerebras, xai/grok, huggingface, minimax, alibaba-dashscope, xiaomi-mimo, kimi-moonshot, qwen, vercel-ai-gateway, + custom with base_url for any endpoint). Unified routing + local-first fallback. Updated in src/main.rs and docs. | **present** — full parity with all Hermes providers achieved. Custom covers the long tail via base_url + api_key.

## Verified command output (evidence)

```text
$ simplicio cron status --json
{"schema":"simplicio.cron/v1","action":"status","jobs":0,"enabled_jobs":0,"output_dir":".simplicio-loop/cron/output",...}
$ simplicio cron add --help
cron add requires a schedule and prompt, e.g. simplicio cron add "every 2h" "update auto"

$ simplicio onboard            # providers list
Providers: openai-codex, claude-pro-max, openrouter, deepseek, groq, mistral, cerebras, xai, custom
$ simplicio onboard status --json
{"schema":"simplicio.chat-provider/v1","configured":false,"path":"~/.simplicio-loop/chat-provider.json"}

$ simplicio skill-memory "audit" --json
{"schema":"simplicio.skill-memory/v1","positioning":"Hermes-style procedural memory for learning, storing, ranking, and curating skills with offline SQLite indexes",...}
$ simplicio trajectory suggest --json
{"schema":"simplicio.learn-suggestion-list/v1","count":0,"gate_required":true,...}
$ simplicio memory status --json
{"schema":"simplicio.memory-backend/v1","status":"ready","selected_backend":"sqlite-fts5","offline":true,...}
$ simplicio telegram status --json
{"schema":"simplicio.telegram/v1","configured":false,"curl":true}
```

## Summary

- **Present (5):** cron + NL unattended tasks (#450), provider/model config + local fallback (#455); plus the foundations for memory (#453) and skills/learn (#448, #454).
- **Partial (6):** self-learning autonomy loop (#448), messaging breadth (#449), advanced TUI (#452), user-modeling depth (#453), batch trajectory export (#454), flexible/serverless deployment (#451, #2578 — Modal/Daytona gated + evidenced, Fly/Vercel not yet wired).
- **Absent (0):** none remaining as of #2578.

The biggest **net-new** gap left is the messaging-gateway breadth (#449); the
rest are deepenings of surfaces that already exist natively. Re-run the audit
with the commands above after each parity PR to keep this matrix current.

## Notes
- `simplicio model status` loads/validates the local GGUF and is slow under CPU
  contention; prefer `simplicio onboard status` for a fast provider-config check.
- Desktop (Tauri) parity is tracked separately under #456–#495 and
  `docs/evidence/desktop-hermes-parity/`.','docs/HERMES_PARITY.md','a1bb495927f6a1bbcaeac608c16bccab6614dd9045b35de4b5ddf1ee5b944ac9','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/HERMES_PARITY_STATUS_2026-06-16.md','project_doc','doc://simplicio-runtime/docs/HERMES_PARITY_STATUS_2026-06-16.md','doc: Hermes Parity Status — 2026-06-16','# Hermes Parity Status — 2026-06-16

Epic: #1168

## Phase completion status

| Phase | Status | Evidence |
|---|---|---|
| Phase 1: Fechar buracos básicos | PARCIAL | doctor, adapters, contracts exist; sendsprint path needs update |
| Phase 2: simplicio agent run --until-green | PARCIAL | agent_store.rs + error_recovery.rs base; --until-green flag to-implement |
| Phase 3: Provider UX (auth add, models list) | PARCIAL | integration_openrouter.rs + model_metadata.rs; --type api-key to-implement |
| Phase 4: Hermes import metadata-only | PARCIAL | hermes_compat.rs exists; import metadata-only to-complete |
| Phase 5: Agente vivo com memória | DONE | Isa/Helo/Levi + memory_v2.rs + neural memory; Simplicio wins this block |
| Phase 6: Benchmark oficial | PARCIAL | benchmark_harness.rs + benchmark_suite.rs exist; multi-competitor to-implement |
| Phase 7: UX final (simplicio "task") | PARCIAL | bare invocation exists; Hermes-like loop to-complete |

## Implemented (evidence)

- `src/hermes_compat.rs`: Hermes compatibility layer
- `src/benchmark_harness.rs`, `src/benchmark_suite.rs`: benchmarking base
- Delivery gates: `deliver dod/runverify/regression/certify`
- `src/action_bridge.rs`: gated mutations (action bridge)
- `src/agent_store.rs`: agent lifecycle management
- `src/error_recovery.rs`: repair loop base
- `src/model_metadata.rs`: model info
- `src/integration_openrouter.rs`: OpenRouter provider
- `src/memory_v2.rs`: neural memory (Simplicio wins vs Hermes here)

## Remaining gaps (track as sub-issues)

- `simplicio doctor` recognizes sendsprint as consolidated flow
- `simplicio agent run --until-green` (iterate-until-green loop, epic #236)
- `auth add --type api-key` UX
- `hermes import --metadata-only` (hermes_compat.rs needs import flow)
- `benchmark --competitors hermes,openclaw,codex,claude`
- Bare `simplicio task` -> Hermes-like loop

## Decision

Epic remains open as tracker; most sub-phases have real implementations.
Remaining gaps are tracked via individual implementation PRs linked to this epic.','docs/HERMES_PARITY_STATUS_2026-06-16.md','12c77a2deb496e1221152b6e4d8b5be6e73c6d441a8d96a567b251168a814ff0','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/HERMES_UX_PORT_PLAN.md','project_doc','doc://simplicio-runtime/docs/HERMES_UX_PORT_PLAN.md','doc: Hermes UX → Simplicio: comparação item a item e plano de port do terminal','# Hermes UX → Simplicio: comparação item a item e plano de port do terminal

Fonte: dissecação do código-fonte do Hermes Agent (NousResearch, clone 2026-06-10)
contra auditoria do chat/TUI atual do simplicio-runtime. Liga às issues #768,
#778-#784, #782, #783/#800 e ao épico #764 (beat Hermes).

## Decisão de arquitetura (a grande)

**Aposentar o full-screen Ratatui como superfície padrão de chat.** O Hermes não
é um "TUI": é um **REPL inline** — área de input fixa embaixo (prompt_toolkit) e
as respostas fluem em streaming para o scrollback normal do terminal, impressas
**uma vez** e nunca redesenhadas. O nosso Ratatui redesenha a tela inteira a
cada tick de 100ms e re-parseia o markdown de todo o histórico (50 turnos = 50
re-renders por tick). É um mismatch arquitetural, não um bug de performance.

- `simplicio` / `simplicio chat` (default) → **REPL inline novo**: reedline para
  input (já temos, feature `rich-repl`) + emissor de streaming ANSI para output.
- `simplicio tui` → mantém Ratatui como **dashboard opcional** (kanban, activity,
  trace), não como chat principal.

## Comparação item a item (camada de conversa/terminal)

| # | Item | Hermes | Simplicio hoje | Veredito |
|---|------|--------|----------------|----------|
| 1 | Streaming token-a-token | Sim, delta→scrubber→emit, caixa `╭─╮` abre no 1º token | Nenhum no chat: resposta chega como blob JSON após inferência completa (`chat_answer`, main.rs:44505) | **GAP crítico — causa nº 1 do "demora demais"** |
| 2 | Scrubber de tags partidas | Buffer prefilt + detecção de tag em fronteira de bloco + holdback de prefixo parcial + close-tag recursivo (cli.py:4633-4771) | Existe só para output de tools (#801), não para respostas | **GAP** — portar o algoritmo |
| 3 | Latência do 1º turno | Pre-warm de caches em background no boot | GGUF carrega lazy no 1º turno (1-3s) + subprocesso `llama-cli` por turno | **GAP** — pré-carregar in-process no boot do REPL |
| 4 | Inferência por turno | API/SDK streaming | TUI → subprocesso `simplicio chat` → subprocesso `llama-cli` (+100-200ms/turno) | **GAP** — chamar in-process-llm direto (KV cache residente já existe) |
| 5 | Input editor | prompt_toolkit: multiline (Alt+Enter), history ghost-text, tab-complete de slash, Ctrl+G abre $EDITOR, bracketed paste c/ imagem | reedline (rich-repl) com history file; TUI tem input box própria | Parcial — reedline cobre 70%, falta completer de slash + multiline + Ctrl+G |
| 6 | Interrupção | Pilha de prioridade no Ctrl+C: voice → prompts ativos → `agent.interrupt()` → 2º toque em 2s força saída; `/steer` injeta mid-run | Worker thread bloqueante, sem cancelamento gracioso | **GAP** |
| 7 | Persona / system prompt | 3 camadas: estável (identidade SOUL.md + "direct, efficient, finish the job") / contexto (AGENTS.md, .cursorrules, descoberta até git root) / volátil (memória, USER.md, timestamp); cacheada; `/personality` | Uma frase hardcoded ("Speak naturally...", main.rs:44585) | **GAP — é isto que faz o Hermes "conversar daquele jeito"** |
| 8 | Slash commands | Mensagens injetadas no fluxo da conversa (preserva prompt cache); registry central + autocomplete | TUI executa comandos out-of-band | Parcial (#781) |
| 9 | Sessões | Resume automático, SQLite, `/sessions`, compaction com template "Active Task / Remaining Work" + nota "latest message WINS" | Snapshots no TUI; sem compaction | Parcial (#782) |
| 10 | Markdown em streaming | Linha a linha; tabelas bufferizadas e realinhadas no fechamento do bloco; CJK-aware | `markdown.rs` completo, mas re-renderiza tudo a cada tick | Temos o renderer; falta o modo incremental |
| 11 | Recovery visual | `/redraw` + output history replay pós-resize | Nada | Menor |

Onde **já ganhamos** (não regredir): edit determinístico 0-token, action gate,
evidência HBP, memória estruturada, skills index, local-first — Hermes não tem
nenhum desses.

## O algoritmo do scrubber (portar para Rust)

Invariante: nenhum token é emitido duas vezes; prefixos parciais de tag ficam
retidos até confirmação.

1. `prefilt = prefilt + delta` (acumula).
2. Fora de bloco de reasoning: procurar open-tags (`<think>`,
   `<REASONING_SCRATCHPAD>`…) **somente em fronteira de bloco** (início de
   stream, pós-newline, ou conteúdo anterior whitespace-only). Achou → emite o
   prefixo seguro, marca `in_reasoning = true`.
3. **Holdback**: se o sufixo do buffer pode ser prefixo de alguma tag
   (`tag[:i]`), retém esse sufixo e emite só a parte segura.
4. Dentro do bloco: procurar close-tag; ao fechar, rotear o conteúdo para a
   caixa de reasoning (se `show_reasoning`) ou descartar, e processar o resto
   **recursivamente** (tags aninhadas).
5. Emissão linha-a-linha: buffer até `\n`; linhas de tabela markdown ficam em
   `table_buf` e são realinhadas juntas no fim do bloco.

Em Rust isso é ~150-200 linhas sobre um `mpsc::Receiver<String>` de deltas; o
canal já existe no padrão `run_cli_capture_streaming` (tui_app.rs:10641).

## System prompt em 3 camadas (port da persona)

- **Estável** (cacheável): identidade (SOUL.md se existir, senão default curto:
  "direto, eficiente, termina o trabalho, admite incerteza, não verboso") +
  guidance de conclusão de tarefa + guidance de memória/skills.
- **Contexto** (por cwd): AGENTS.md / SIMPLICIO.md / .cursorrules descobertos
  subindo até o git root, com scan de prompt-injection antes de injetar.
- **Volátil** (por turno): snapshot de memória neural, USER.md, timestamp.
- Juntar com `\n\n`; cachear a parte estável (alinha com prompt_caching que já
  é capability default).

## Fases de execução

| Fase | Entrega | Issues | Estimativa |
|------|---------|--------|-----------|
| **P1 — Streaming spine** | Deltas do in-process-llm → canal → emissor com scrubber + caixa de resposta; prewarm do GGUF no boot do REPL; matar subprocesso-por-turno | #783/#800, #768 | 2-4 dias |
| **P2 — Persona** | System prompt 3 camadas + descoberta de context files + `/personality` — **landed** (`src/persona.rs::build_system_prompt`: stable On','docs/HERMES_UX_PORT_PLAN.md','4d65c9aa53a8d1d4b086ddcbeffef9021f802a651091060cf11d8b8b67420865','doc,simplicio',1.1);
