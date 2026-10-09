INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:material-contract-schedule','project_skill','skill://simplicio-runtime/material-contract-schedule','skill: material-contract-schedule','---
name: material-contract-schedule
description: >
  Build the material contracts disclosure schedule from diligence findings,
  applying the purchase agreement''s Material Contract definition and formatting
  per the agreement''s schedule format. Use when user says "build the contracts
  schedule", "disclosure schedule", "schedule 3.X", "material contracts list",
  or when drafting disclosure schedules.
argument-hint: "[purchase agreement path, or paste the Material Contract definition]"
---

# /material-contract-schedule

1. Load purchase agreement → Material Contract definition + schedule format.
2. Use the workflow below.
3. Apply definition to diligence findings. Flag edge cases.
4. Format per agreement. Consent overlay feeds closing checklist.

---

## Matter context

**Matter context.** Check `## Matter workspaces` in the practice-level CLAUDE.md. If `Enabled` is `✗` (the default for in-house users), skip the rest of this paragraph — skills use practice-level context and the matter machinery is invisible. If enabled and there is no active matter, ask: "Which matter is this for? Run `/corporate-legal:matter-workspace switch <slug>` or say `practice-level`." Load the active matter''s `matter.md` for matter-specific context and overrides. Write outputs to the matter folder at `~/.claude/plugins/config/claude-for-legal/corporate-legal/matters/<matter-slug>/`. Never read another matter''s files unless `Cross-matter context` is `on`.

---

## Purpose

The purchase agreement has a rep: "Schedule 3.X lists all Material Contracts." This skill builds that schedule from the diligence findings — which contracts are material per the agreement''s definition, in the format the agreement requires.

## Load context

- Purchase agreement draft — for the definition of "Material Contract" and the schedule format
- `~/.claude/plugins/config/claude-for-legal/corporate-legal/CLAUDE.md` → materiality thresholds (may differ from the agreement definition — use the agreement''s)
- Diligence findings from diligence-issue-extraction — contract-level data

## Workflow

### Step 1: Get the definition

Pull the definition of "Material Contract" from the purchase agreement — the PA definition controls. Deal-structure differences (stock vs. asset vs. merger) can change how a prong is interpreted, and regulated-industry overlays (healthcare, defense, financial services, telecom, government contracting) can add consent requirements that live outside the PA. If the deal involves any of those overlays, research the applicable anti-assignment or novation rules (for example, federal contracts, government contracting novation, sector-specific consent statutes) and cite the controlling rule.

Common prong categories to look for in the PA definition — these are not a substitute for reading the PA, and the list the PA uses controls:

- Dollar-value threshold (annual or aggregate)
- Term length
- Change-of-control or anti-assignment provision
- Exclusivity or non-compete
- Top N customer or supplier contracts
- Real property leases
- IP licenses (in-bound and out-bound)
- Related-party agreements
- Government contracts
- Contracts outside the ordinary course

The PA''s definition is the test. Apply it mechanically — every contract that meets any prong in the PA''s definition goes on the schedule.

### Step 2: Apply the definition to the findings

For each contract reviewed in diligence:

| Contract | Meets prong(s) | Include |
|---|---|---|
| [name] | [$X+ annual value; CoC provision] | Yes |
| [name] | [none] | No |

**Edge cases to flag for human decision:**
- Contract is $X-1 (just under threshold) but important to the business
- Contract meets a prong but is being terminated anyway
- Oral agreements or side letters that may or may not count

### Step 3: Gather schedule data

For each included contract, the schedule typically needs:

| Field | Source |
|---|---|
| Counterparty name | Contract |
| Contract title/type | Contract |
| Date | Contract |
| Term / expiration | Contract |
| Annual/total value | Contract or management data |
| Which materiality prong it ','.claude\skills\material-contract-schedule\SKILL.md','197dc4841d43cdbe79fd594c57cf7a89212d54a85d9f6902eaf0260d9b4a8c9c','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:matter-workspace','project_skill','skill://simplicio-runtime/matter-workspace','skill: matter-workspace','---
name: matter-workspace
description: >
  Manage matter workspaces — create, list, switch, close, or detach the active
  matter so multi-client practitioners keep one client''s context separate from
  every other. Read by any substantive skill that needs to know what matter it''s
  working in. Use when user says "new matter", "switch matter", "list matters",
  "close matter", or wants to work at practice-level only.
argument-hint: "<new | list | switch | close | none> [slug]"
---

# /matter-workspace

Practitioners work across multiple clients and matters. A matter workspace keeps one client or engagement''s context separate from every other. This skill manages those workspaces.

## Subcommands

- `/corporate-legal:matter-workspace new <slug>` — create a new matter workspace, run a short intake, write `matter.md`
- `/corporate-legal:matter-workspace list` — list matters with status and active flag
- `/corporate-legal:matter-workspace switch <slug>` — set the active matter
- `/corporate-legal:matter-workspace close <slug>` — archive a matter (move to `~/.claude/plugins/config/claude-for-legal/corporate-legal/matters/_archived/`, never delete)
- `/corporate-legal:matter-workspace none` — detach from any active matter, work at practice-level only

## Instructions

1. Read `~/.claude/plugins/config/claude-for-legal/corporate-legal/CLAUDE.md` — confirm the `## Matter workspaces` section is populated. If `Enabled` is `✗`, tell the user: "Matter workspaces are off — you''re configured as an in-house practice with one client, so the plugin works from practice-level context automatically. If you actually work across multiple clients, re-run `/corporate-legal:cold-start-interview --redo` and select a private-practice setting. Otherwise, you don''t need `/matter-workspace` at all." Don''t error — the disabled state is the expected one for in-house users.
2. Use the workflow below.
3. Dispatch on the first token of `$ARGUMENTS`:
   - `new` → run the intake interview, write `~/.claude/plugins/config/claude-for-legal/corporate-legal/matters/<slug>/matter.md`, seed `history.md` and `notes.md`.
   - `list` → enumerate `~/.claude/plugins/config/claude-for-legal/corporate-legal/matters/*/matter.md`, print a table, mark the active matter.
   - `switch` → update the `Active matter:` line in the practice-level CLAUDE.md.
   - `close` → move `~/.claude/plugins/config/claude-for-legal/corporate-legal/matters/<slug>/` to `~/.claude/plugins/config/claude-for-legal/corporate-legal/matters/_archived/<slug>/`, log the close date in `history.md`.
   - `none` → set `Active matter:` to `none — practice-level context only`.
4. Show the user what changed and confirm before writing.

## Notes

- The skill never reads across matters unless `Cross-matter context` is `on` in the practice-level CLAUDE.md.
- Archiving is not deletion — closed matters remain readable for retention/conflicts purposes.
- Slugs are lowercase with hyphens. If a slug is reused across archived and active, the archived one is preserved under `_archived/<slug>/`.

---

Multi-client practitioners (private practice — solo, small firm, large firm) work across many matters. Context from one must not leak into another. This skill is the thin file-management layer that makes that true.

**Default state is off.** In-house users never see this — they run at practice-level only. Matter workspaces turn on at cold-start for private-practice users, or by editing `## Matter workspaces` in the practice-level CLAUDE.md. If `Enabled` is `✗`, this skill does not run; `/corporate-legal:matter-workspace` explains the disabled state and suggests `/corporate-legal:cold-start-interview --redo` for users who actually need matter isolation.

## Storage layout

All matter data lives under:

```
~/.claude/plugins/config/claude-for-legal/corporate-legal/
├── CLAUDE.md                       # practice-level practice profile
└── matters/
    ├── <slug>/
    │   ├── matter.md               # client, counterparty, matter type, key facts, overrides
    │   ├── history.md              # dated log of events, decisions, dr','.claude\skills\matter-workspace\SKILL.md','6c9d6c67e902a347ec67c2259b3829b0a1be2a5bb711640d3cbfad66d3f03888','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:mcp-server-builder','project_skill','skill://simplicio-runtime/mcp-server-builder','skill: mcp-server-builder','---
name: mcp-server-builder
description: "Design and ship production-ready MCP (Model Context Protocol) servers from OpenAPI contracts instead of hand-written tool wrappers. Python and TypeScript support, schema validation, safe evolution. Use when exposing an existing API as an MCP server, building tool integrations for Claude or Codex or Cursor, or scaffolding an MCP project from scratch."
---

# MCP Server Builder

**Tier:** POWERFUL · **Category:** Engineering · **Domain:** AI / API Integration

## Overview

Use this skill to design and ship production-ready MCP servers from API contracts instead of hand-written one-off tool wrappers. It focuses on fast scaffolding, schema quality, validation, and safe evolution.

The workflow supports both Python and TypeScript MCP implementations and treats OpenAPI as the source of truth.

## Core Capabilities

- Convert OpenAPI paths/operations into MCP tool definitions
- Generate starter server scaffolds (Python or TypeScript)
- Enforce naming, descriptions, and schema consistency
- Validate MCP tool manifests for common production failures
- Apply versioning and backward-compatibility checks
- Separate transport/runtime decisions from tool contract design

## When to Use

- You need to expose an internal/external REST API to an LLM agent
- You are replacing brittle browser automation with typed tools
- You want one MCP server shared across teams and assistants
- You need repeatable quality checks before publishing MCP tools
- You want to bootstrap an MCP server from existing OpenAPI specs

## Key Workflows

### 1. OpenAPI to MCP Scaffold

1. Start from a valid OpenAPI spec.
2. Generate tool manifest + starter server code.
3. Review naming and auth strategy.
4. Add endpoint-specific runtime logic.

```bash
python3 scripts/openapi_to_mcp.py \
  --input openapi.json \
  --server-name billing-mcp \
  --language python \
  --output-dir ./out \
  --format text
```

Supports stdin as well:

```bash
cat openapi.json | python3 scripts/openapi_to_mcp.py --server-name billing-mcp --language typescript
```

### 2. Validate MCP Tool Definitions

Run validator before integration tests:

```bash
python3 scripts/mcp_validator.py --input out/tool_manifest.json --strict --format text
```

Checks include duplicate names, invalid schema shape, missing descriptions, empty required fields, and naming hygiene.

### 3. Runtime Selection

- Choose **Python** for fast iteration and data-heavy backends.
- Choose **TypeScript** for unified JS stacks and tighter frontend/backend contract reuse.
- Keep tool contracts stable even if transport/runtime changes.

### 4. Harden for Production

Key items before publishing:

- Keep secrets in env vars, not tool schemas
- Prefer outbound host allowlists over open proxies
- Use additive-only changes; never rename tool names in-place

Full hardening guidance: [references/production-hardening-guide.md](references/production-hardening-guide.md).

## Script Interfaces

- `python3 scripts/openapi_to_mcp.py --help`
  - Reads OpenAPI from stdin or `--input`
  - Produces manifest + server scaffold
  - Emits JSON summary or text report
- `python3 scripts/mcp_validator.py --help`
  - Validates manifests and optional runtime config
  - Returns non-zero exit in strict mode when errors exist

## Reference Material

- [references/production-hardening-guide.md](references/production-hardening-guide.md) — auth & safety design, versioning strategy, common pitfalls, best practices, architecture decisions, contract quality gates, testing strategy, deployment practices, security controls
- [references/openapi-extraction-guide.md](references/openapi-extraction-guide.md)
- [references/python-server-template.md](references/python-server-template.md)
- [references/typescript-server-template.md](references/typescript-server-template.md)
- [references/validation-checklist.md](references/validation-checklist.md)
- [README.md](README.md)

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\mcp-server-builder\SKILL.md','c75d1b19071702b32903d0c824a5333009b0bf18126274feff83d5c304a98bd8','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:mdr-745-specialist','project_skill','skill://simplicio-runtime/mdr-745-specialist','skill: mdr-745-specialist','---
name: mdr-745-specialist
description: EU MDR 2017/745 compliance specialist for medical device classification, technical documentation, clinical evidence, and post-market surveillance. Covers Annex VIII classification rules, Annex II/III technical files, Annex XIV clinical evaluation, Art. 86 PSUR schedules, and EUDAMED integration. Use when classifying a medical device under MDR, building or gap-checking a technical file, planning clinical evaluation or PMS/PSUR cadence, or preparing for notified body review (e.g., ''what class is my device under MDR'', ''review my PSUR schedule'').
triggers:
  - MDR compliance
  - EU MDR
  - medical device classification
  - Annex VIII
  - technical documentation
  - clinical evaluation
  - PMCF
  - EUDAMED
  - UDI
  - notified body
---

# MDR 2017/745 Specialist

EU MDR compliance patterns for medical device classification, technical documentation, and clinical evidence.

---

## Table of Contents

- [Device Classification Workflow](#device-classification-workflow)
- [Technical Documentation](#technical-documentation)
- [Clinical Evidence](#clinical-evidence)
- [Post-Market Surveillance](#post-market-surveillance)
- [EUDAMED and UDI](#eudamed-and-udi)
- [Reference Documentation](#reference-documentation)
- [Tools](#tools)

---

## Device Classification Workflow

Classify device under MDR Annex VIII:

1. Identify device duration (transient, short-term, long-term)
2. Determine invasiveness level (non-invasive, body orifice, surgical)
3. Assess body system contact (CNS, cardiac, other)
4. Check if active device (energy dependent)
5. Apply classification rules 1-22
6. For software, apply MDCG 2019-11 algorithm
7. Document classification rationale
8. **Validation:** Classification confirmed with Notified Body

### Classification Matrix

| Factor | Class I | Class IIa | Class IIb | Class III |
|--------|---------|-----------|-----------|-----------|
| Duration | Any | Short-term | Long-term | Long-term |
| Invasiveness | Non-invasive | Body orifice | Surgical | Implantable |
| System | Any | Non-critical | Critical organs | CNS/cardiac |
| Risk | Lowest | Low-medium | Medium-high | Highest |

### Software Classification (MDCG 2019-11)

| Information Use | Condition Severity | Class |
|-----------------|-------------------|-------|
| Informs decision | Non-serious | IIa |
| Informs decision | Serious | IIb |
| Drives/treats | Critical | III |

### Classification Examples

**Example 1: Absorbable Surgical Suture**
- Rule 8 (implantable, long-term)
- Duration: > 30 days (absorbed)
- Contact: General tissue
- Classification: **Class IIb**

**Example 2: AI Diagnostic Software**
- Rule 11 + MDCG 2019-11
- Function: Diagnoses serious condition
- Classification: **Class IIb**

**Example 3: Cardiac Pacemaker**
- Rule 8 (implantable)
- Contact: Central circulatory system
- Classification: **Class III**

---

## Technical Documentation

Prepare technical file per Annex II and III:

1. Create device description (variants, accessories, intended purpose)
2. Develop labeling (Article 13 requirements, IFU)
3. Document design and manufacturing process
4. Complete GSPR compliance matrix
5. Prepare benefit-risk analysis
6. Compile verification and validation evidence
7. Integrate risk management file (ISO 14971)
8. **Validation:** Technical file reviewed for completeness

### Technical File Structure

```
ANNEX II TECHNICAL DOCUMENTATION
├── Device description and UDI-DI
├── Label and instructions for use
├── Design and manufacturing info
├── GSPR compliance matrix
├── Benefit-risk analysis
├── Verification and validation
└── Clinical evaluation report
```

### GSPR Compliance Checklist

| Requirement | Evidence | Status |
|-------------|----------|--------|
| Safe design (GSPR 1-3) | Risk management file | ☐ |
| Chemical properties (GSPR 10.1) | Biocompatibility report | ☐ |
| Infection risk (GSPR 10.2) | Sterilization validation | ☐ |
| Software requirements (GSPR 17) | IEC 62304 documentation | ☐ |
| Labeling (GSPR 23) | Label artwork, IFU | ☐ |

### Conformity Assessment Routes

| Class | Route | NB Invol','.claude\skills\mdr-745-specialist\SKILL.md','b69551f3674a19940628d34138debc986d40e3176e63cbbe3b1fa8f693a1dc2d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:media-create','project_skill','skill://simplicio-runtime/media-create','skill: media-create','---
name: media-create
description: Use to generate media — images, video, voice/TTS — from text. Routes to Simplicio''s native image/video/voice commands and the deterministic HyperFrames video stack. Trigger on "generate an image", "make a video", "text to speech", "crie uma imagem/vídeo", or avatar/creative production. Consolidates DataCamp media skills (image-router, nano-banana-pro, video-agent, video-cog, avatar-video, voice-reply) onto native capabilities.
metadata: { simplicio: { guardians: [Helo], tags: [image, video, voice, tts, media, native-router] } }
---
# Media create (native router)
Real, portable — Simplicio''s own media stack (no external package):
- `simplicio image ...` — image generation.
- `simplicio video ...` + the HyperFrames skills (`/hyperframes`) — deterministic HTML→MP4 video.
- `simplicio voice ...` — TTS/voice.
Generative backends (Higgsfield: seedance/kling/nano_banana) are gated by cost + the action gate when used.
','.claude\skills\media-create\SKILL.md','002b01e94512d2de2a552e58b5bf009534bcb23a3d712e2e78480e4241adbebf','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:meeting-analyzer','project_skill','skill://simplicio-runtime/meeting-analyzer','skill: meeting-analyzer','---
name: meeting-analyzer
description: Analyzes meeting transcripts and recordings to surface behavioral patterns, communication anti-patterns, and actionable coaching feedback. Use this skill whenever the user uploads or points to meeting transcripts (.txt, .md, .vtt, .srt, .docx), asks about their communication habits, wants feedback on how they run meetings, requests speaking ratio analysis, mentions filler words or conflict avoidance, or wants to compare their communication across time periods. Also trigger when users mention tools like Granola, Otter, Fireflies, or Zoom transcripts. Even if the user just says "look at my meetings" or "how do I come across in meetings" — use this skill.
---

# Meeting Insights Analyzer

> Originally contributed by [maximcoding](https://github.com/maximcoding) — enhanced and integrated by the claude-skills team.

Transform meeting transcripts into concrete, evidence-backed feedback on communication patterns, leadership behaviors, and interpersonal dynamics.

## Core Workflow

### 1. Ingest & Inventory

Scan the target directory for transcript files (`.txt`, `.md`, `.vtt`, `.srt`, `.docx`, `.json`).

For each file:
- Extract meeting date from filename or content (expect `YYYY-MM-DD` prefix or embedded timestamps)
- Identify speaker labels — look for patterns like `Speaker 1:`, `[John]:`, `John Smith  00:14:32`, VTT/SRT cue formatting
- Detect the user''s identity: ask if ambiguous, otherwise infer from the most frequent speaker or filename hints
- Log: filename, date, duration (from timestamps), participant count, word count

Print a brief inventory table so the user confirms scope before heavy analysis begins.

### 2. Normalize Transcripts

Different tools produce wildly different formats. Normalize everything into a common internal structure before analysis:

```
{ speaker: string, timestamp_sec: number | null, text: string }[]
```

Handling per format:
- **VTT/SRT**: Parse cue timestamps + text. Speaker labels may be inline (`<v Speaker>`) or prefixed.
- **Plain text**: Look for `Name:` or `[Name]` prefixes per line. If no speaker labels exist, warn the user that per-speaker analysis is limited.
- **Markdown**: Strip formatting, then treat as plain text.
- **DOCX**: Extract text content, then treat as plain text.
- **JSON**: Expect an array of objects with `speaker`/`text` fields (common Otter/Fireflies export).

If timestamps are missing, degrade gracefully — skip timing-dependent metrics (speaking pace, pause analysis) but still run text-based analysis.

### 3. Analyze

Run all applicable analysis modules below. Each module is independent — skip any that don''t apply (e.g., skip speaking ratios if there are no speaker labels).

---

#### Module: Speaking Dynamics

Calculate per-speaker:
- **Word count & percentage** of total meeting words
- **Turn count** — how many times each person spoke
- **Average turn length** — words per uninterrupted speaking turn
- **Longest monologue** — flag turns exceeding 60 seconds or 200 words
- **Interruption detection** — a turn that starts within 2 seconds of the previous speaker''s last timestamp, or mid-sentence breaks

Produce a per-meeting summary and a cross-meeting average if multiple transcripts exist.

Red flags to surface:
- User speaks > 60% in a 1:many meeting (dominating)
- User speaks < 15% in a meeting they''re facilitating (disengaged or over-delegating)
- One participant never speaks (excluded voice)
- Interruption ratio > 2:1 (user interrupts others twice as often as they''re interrupted)

---

#### Module: Conflict & Directness

Scan the user''s speech for hedging and avoidance markers:

**Hedging language** (score per-instance, aggregate per meeting):
- Qualifiers: "maybe", "kind of", "sort of", "I guess", "potentially", "arguably"
- Permission-seeking: "if that''s okay", "would it be alright if", "I don''t know if this is right but"
- Deflection: "whatever you think", "up to you", "I''m flexible"
- Softeners before disagreement: "I don''t want to push back but", "this might be a dumb question"

**Conflict avoidance patterns** (requires ','.claude\skills\meeting-analyzer\SKILL.md','9f4eadb1820bb4bfa4a622afadb9daf56108d9ab45005f0c102d0c163c8850f3','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:merge','project_skill','skill://simplicio-runtime/merge','skill: merge','---
name: merge
description: "Merge the winning agent''s branch into base, archive losers, and clean up worktrees. Use when the user runs /hub:merge or asks to land the winning AgentHub result and tidy the session."
command: /hub:merge
---

# /hub:merge — Merge Winner

Merge the best agent''s branch into the base branch, archive losing branches via git tags, and clean up worktrees.

## Usage

```
/hub:merge                                       # Merge winner of latest session
/hub:merge 20260317-143022                       # Merge winner of specific session
/hub:merge 20260317-143022 --agent agent-2       # Explicitly choose winner
```

## What It Does

### 1. Identify Winner

If `--agent` specified, use that. Otherwise, use the #1 ranked agent from the most recent `/hub:eval`.

### 2. Merge Winner

```bash
git checkout {base_branch}
git merge --no-ff hub/{session-id}/{winner}/attempt-1 \
  -m "hub: merge {winner} from session {session-id}

Task: {task}
Winner: {winner}
Session: {session-id}"
```

### 3. Archive Losers

For each non-winning agent:

```bash
# Create archive tag (preserves commits forever)
git tag hub/archive/{session-id}/{agent-id} hub/{session-id}/{agent-id}/attempt-1

# Delete branch ref (commits preserved via tag)
git branch -D hub/{session-id}/{agent-id}/attempt-1
```

### 4. Clean Up Worktrees

```bash
python {skill_path}/scripts/session_manager.py --cleanup {session-id}
```

### 5. Post Merge Summary

Write `.agenthub/board/results/merge-summary.md`:

```markdown
---
author: coordinator
timestamp: {now}
channel: results
---

## Merge Summary

- **Session**: {session-id}
- **Winner**: {winner}
- **Merged into**: {base_branch}
- **Archived**: {loser-1}, {loser-2}, ...
- **Worktrees cleaned**: {count}
```

### 6. Update State

```bash
python {skill_path}/scripts/session_manager.py --update {session-id} --state merged
```

## Safety

- **Confirm with user** before merging — show the diff summary first
- **Never force-push** — merge is always `--no-ff` for clear history
- **Archive, don''t delete** — losing agents'' commits are preserved via tags
- **Clean worktrees** — don''t leave orphan directories on disk

## After Merge

Tell the user:
- Winner merged into `{base_branch}`
- Losers archived with tags `hub/archive/{session-id}/agent-{N}`
- Worktrees cleaned up
- Session state: `merged`

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\merge\SKILL.md','143cff6a243dee92182b5b5a9a71abd0a0ad5d474796d0cf0298e66f70ae71c1','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:mermaid-to-proverif','project_skill','skill://simplicio-runtime/mermaid-to-proverif','skill: mermaid-to-proverif','---
name: mermaid-to-proverif
description: "Translates Mermaid sequenceDiagrams describing cryptographic protocols into ProVerif formal verification models (.pv files). Use when generating a ProVerif model, formally verifying a protocol, converting a Mermaid diagram to ProVerif, verifying protocol security properties (secrecy, authentication, forward secrecy), checking for replay attacks, or producing a .pv file from a sequence diagram."
---

# Mermaid to ProVerif

Reads a Mermaid `sequenceDiagram` describing a cryptographic protocol and
produces a ProVerif model (`.pv` file) that can be passed directly to the
ProVerif verifier.

**Tools used:** Read, Write, Grep, Glob.

The typical input is the output of the `crypto-protocol-diagram` skill — a
Mermaid `sequenceDiagram` annotated with cryptographic operations (`Sign`,
`Verify`, `DH`, `HKDF`, `Enc`, `Dec`, etc.) and message arrows.

## When to Use

- User asks to formally verify a cryptographic protocol described as a Mermaid sequenceDiagram
- User wants to generate a ProVerif model (.pv file) from a protocol diagram
- User wants to prove secrecy, authentication, or forward secrecy properties
- Input is the output of the `crypto-protocol-diagram` skill

## When NOT to Use

- No Mermaid sequenceDiagram exists yet — use `crypto-protocol-diagram` first to generate one
- User wants to verify properties of non-cryptographic systems (state machines, access control)
- User wants to run ProVerif on an existing .pv file — just run `proverif model.pv` directly

## Rationalizations to Reject

| Rationalization | Why It''s Wrong | Required Action |
|-----------------|----------------|-----------------|
| "Reachability queries are just busywork" | If events aren''t reachable, all other query results are meaningless | Always add reachability queries first as a sanity check |
| "Public channels are fine for all messages" | Private channels for internal state prevent false attacks | Use private channels for intra-process state threading |
| "I''ll skip the forward secrecy test" | Ephemeral keys demand forward secrecy verification | Add the ForwardSecrecyTest process whenever the diagram shows ephemeral keys |
| "Unused declarations are harmless" | ProVerif may report spurious results from orphan declarations | Clean up all unused types, functions, and events |
| "The model compiles, so it''s correct" | A compiling model can have dead receives, type mismatches, or impossible guards that make queries vacuously true | Validate reachability before trusting any security query |
| "I don''t need to check the example first" | The example defines the expected output quality bar | Study `examples/simple-handshake/` before working on unfamiliar protocols |

---

## Workflow

```
ProVerif Model Progress:
- [ ] Step 1: Parse participants and channels
- [ ] Step 2: Inventory cryptographic operations
- [ ] Step 3: Declare types, functions, and equations
- [ ] Step 4: Identify and declare events
- [ ] Step 5: Formulate security queries
- [ ] Step 6: Write participant processes
- [ ] Step 7: Write main process and finalize
- [ ] Step 8: Verify and deliver
```

### Step 1: Parse Participants and Channels

From the Mermaid diagram:

1. Extract every `participant` or `actor` declaration. Each becomes a
   ProVerif process.
2. Count message arrows (`->>`, `-->>`, `-x`, `--x`). Each distinct
   `A ->> B: label` creates a communication step on a channel.
3. Decide channel model:
   - **Public channel** for any message sent over the network before a
     secure channel is established (e.g., ClientHello, ephemeral keys,
     ciphertext to be decrypted by the peer).
   - **Private channel** only for internal state threading within a single
     party process (not for cross-party messages).
   - Default: declare one shared public channel `c` for all cross-party
     messages. Add per-flow channels only when two distinct parallel sessions
     must be independent.

```proverif
free c: channel.
```

### Step 2: Inventory Cryptographic Operations

Walk through every `Note over` annotation and message label. Build a list ','.claude\skills\mermaid-to-proverif\SKILL.md','da3f0dd6603a6348d13e4ae367135d462eee391b2da301db32be898abeb8b1a8','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:migrate','project_skill','skill://simplicio-runtime/migrate','skill: migrate','---
name: migrate
description: >-
  Migrate from Cypress or Selenium to Playwright. Use when user mentions
  "cypress", "selenium", "migrate tests", "convert tests", "switch to
  playwright", "move from cypress", or "replace selenium".
---

# Migrate to Playwright

Interactive migration from Cypress or Selenium to Playwright with file-by-file conversion.

## Input

`$ARGUMENTS` can be:
- `"from cypress"` — migrate Cypress test suite
- `"from selenium"` — migrate Selenium/WebDriver tests
- A file path: convert a specific test file
- Empty: auto-detect source framework

## Steps

### 1. Detect Source Framework

Use `Explore` subagent to scan:
- `cypress/` directory or `cypress.config.ts` → Cypress
- `selenium`, `webdriver` in `package.json` deps → Selenium
- `.py` test files with `selenium` imports → Selenium (Python)

### 2. Assess Migration Scope

Count files and categorize:

```
Migration Assessment:
- Total test files: X
- Cypress custom commands: Y
- Cypress fixtures: Z
- Estimated effort: [small|medium|large]
```

| Size | Files | Approach |
|---|---|---|
| Small (1-10) | Convert sequentially | Direct conversion |
| Medium (11-30) | Batch in groups of 5 | Use sub-agents |
| Large (31+) | Use `/batch` | Parallel conversion with `/batch` |

### 3. Set Up Playwright (If Not Present)

Run `/pw:init` first if Playwright isn''t configured.

### 4. Convert Files

For each file, apply the appropriate mapping:

#### Cypress → Playwright

Load `cypress-mapping.md` for complete reference.

Key translations:
```
cy.visit(url)           → page.goto(url)
cy.get(selector)        → page.locator(selector) or page.getByRole(...)
cy.contains(text)       → page.getByText(text)
cy.find(selector)       → locator.locator(selector)
cy.click()              → locator.click()
cy.type(text)           → locator.fill(text)
cy.should(''be.visible'') → expect(locator).toBeVisible()
cy.should(''have.text'')  → expect(locator).toHaveText(text)
cy.intercept()          → page.route()
cy.wait(''@alias'')       → page.waitForResponse()
cy.fixture()            → JSON import or test data file
```

**Cypress custom commands** → Playwright fixtures or helper functions
**Cypress plugins** → Playwright config or fixtures
**`before`/`beforeEach`** → `test.beforeAll()` / `test.beforeEach()`

#### Selenium → Playwright

Load `selenium-mapping.md` for complete reference.

Key translations:
```
driver.get(url)                    → page.goto(url)
driver.findElement(By.id(''x''))     → page.locator(''#x'') or page.getByTestId(''x'')
driver.findElement(By.css(''.x''))   → page.locator(''.x'') or page.getByRole(...)
element.click()                    → locator.click()
element.sendKeys(text)             → locator.fill(text)
element.getText()                  → locator.textContent()
WebDriverWait + ExpectedConditions → expect(locator).toBeVisible()
driver.switchTo().frame()          → page.frameLocator()
Actions                            → locator.hover(), locator.dragTo()
```

### 5. Upgrade Locators

During conversion, upgrade selectors to Playwright best practices:
- `#id` → `getByTestId()` or `getByRole()`
- `.class` → `getByRole()` or `getByText()`
- `[data-testid]` → `getByTestId()`
- XPath → role-based locators

### 6. Convert Custom Commands / Utilities

- Cypress custom commands → Playwright custom fixtures via `test.extend()`
- Selenium page objects → Playwright page objects (keep structure, update API)
- Shared helpers → TypeScript utility functions

### 7. Verify Each Converted File

After converting each file:

```bash
npx playwright test <converted-file> --reporter=list
```

Fix any compilation or runtime errors before moving to the next file.

### 8. Clean Up

After all files are converted:
- Remove Cypress/Selenium dependencies from `package.json`
- Remove old config files (`cypress.config.ts`, etc.)
- Update CI workflow to use Playwright
- Update README with new test commands

Ask user before deleting anything.

## Output

- Conversion summary: files converted, total tests migrated
- Any tests that couldn''t be auto-converted (manual intervention needed)
- Updated CI con','.claude\skills\migrate\SKILL.md','180b643418dd32e8e881b178f928c9b333edd375e4646e1fb9fbc9d88472f4ed','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:migration-architect','project_skill','skill://simplicio-runtime/migration-architect','skill: migration-architect','---
name: migration-architect
description: "Zero-downtime migration planning, compatibility validation, and rollback strategy generation. Tools for system, database, and infrastructure migrations with minimal business impact. Use when planning a database migration, infrastructure cutover, system replacement, or any high-risk transition that needs explicit rollback paths."
---

# Migration Architect

**Tier:** POWERFUL  
**Category:** Engineering - Migration Strategy  
**Purpose:** Zero-downtime migration planning, compatibility validation, and rollback strategy generation

## Overview

The Migration Architect skill provides comprehensive tools and methodologies for planning, executing, and validating complex system migrations with minimal business impact. This skill combines proven migration patterns with automated planning tools to ensure successful transitions between systems, databases, and infrastructure.

## Core Capabilities

### 1. Migration Strategy Planning
- **Phased Migration Planning:** Break complex migrations into manageable phases with clear validation gates
- **Risk Assessment:** Identify potential failure points and mitigation strategies before execution
- **Timeline Estimation:** Generate realistic timelines based on migration complexity and resource constraints
- **Stakeholder Communication:** Create communication templates and progress dashboards

### 2. Compatibility Analysis
- **Schema Evolution:** Analyze database schema changes for backward compatibility issues
- **API Versioning:** Detect breaking changes in REST/GraphQL APIs and microservice interfaces
- **Data Type Validation:** Identify data format mismatches and conversion requirements
- **Constraint Analysis:** Validate referential integrity and business rule changes

### 3. Rollback Strategy Generation
- **Automated Rollback Plans:** Generate comprehensive rollback procedures for each migration phase
- **Data Recovery Scripts:** Create point-in-time data restoration procedures
- **Service Rollback:** Plan service version rollbacks with traffic management
- **Validation Checkpoints:** Define success criteria and rollback triggers

## Quick Start — plan → check compatibility → generate rollback

All paths relative to this skill folder; sample inputs in `assets/`, expected shapes in `expected_outputs/`.

```bash
# 1. Generate the migration plan from a spec (copy assets/sample_database_migration.json)
python3 scripts/migration_planner.py --input migration_spec.json --format json -o migration_plan.json

# 2. Check schema/API compatibility — exits non-zero unless fully compatible (CI gate)
python3 scripts/compatibility_checker.py --before assets/database_schema_before.json --after assets/database_schema_after.json --type database --format json -o compatibility.json

# 3. Generate the rollback runbook from the plan
python3 scripts/rollback_generator.py --input migration_plan.json --format both -o rollback_runbook
```

Outputs chain: `migration_plan.json` (`phases`, `risks`, `estimated_duration_hours`) feeds step 3; `compatibility.json` reports `overall_compatibility` plus `breaking_changes_count` / `potentially_breaking_count`.

**Gate:** the migration is not approved until (a) `compatibility_checker` exits 0 (`overall_compatibility: compatible`) or every breaking/potentially-breaking item is explicitly accepted by the owner in writing, and (b) a rollback runbook exists for every phase in the plan. Re-run both checks after any schema revision.

## Migration Patterns

### Database Migrations

#### Schema Evolution Patterns
1. **Expand-Contract Pattern**
   - **Expand:** Add new columns/tables alongside existing schema
   - **Dual Write:** Application writes to both old and new schema
   - **Migration:** Backfill historical data to new schema
   - **Contract:** Remove old columns/tables after validation

2. **Parallel Schema Pattern**
   - Run new schema in parallel with existing schema
   - Use feature flags to route traffic between schemas
   - Validate data consistency between parallel systems
   - Cutover when confidence is high

3. **Event Sour','.claude\skills\migration-architect\SKILL.md','52affbf2ed3430189dfe084b7b83061b8d3996124844211a15b431a760ec14b0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:modern-python','project_skill','skill://simplicio-runtime/modern-python','skill: modern-python','---
name: modern-python
description: Configures Python projects with modern tooling (uv, ruff, ty). Use when creating projects, writing standalone scripts, or migrating from pip/Poetry/mypy/black.
---

# Modern Python

Guide for modern Python tooling and best practices, based on [trailofbits/cookiecutter-python](https://github.com/trailofbits/cookiecutter-python).

## When to Use This Skill

- Creating a new Python project or package
- Setting up `pyproject.toml` configuration
- Configuring development tools (linting, formatting, testing)
- Writing Python scripts with external dependencies
- Migrating from legacy tools (when user requests it)

## When NOT to Use This Skill

- **User wants to keep legacy tooling**: Respect existing workflows if explicitly requested
- **Python < 3.11 required**: These tools target modern Python
- **Non-Python projects**: Mixed codebases where Python isn''t primary

## Anti-Patterns to Avoid

| Avoid | Use Instead |
|-------|-------------|
| `[tool.ty]` python-version | `[tool.ty.environment]` python-version |
| `uv pip install` | `uv add` and `uv sync` |
| Editing pyproject.toml manually to add deps | `uv add <pkg>` / `uv remove <pkg>` |
| `hatchling` build backend | `uv_build` (simpler, sufficient for most cases) |
| Poetry | uv (faster, simpler, better ecosystem integration) |
| requirements.txt | PEP 723 for scripts, pyproject.toml for projects |
| mypy / pyright | ty (faster, from Astral team) |
| `[project.optional-dependencies]` for dev tools | `[dependency-groups]` (PEP 735) |
| Manual virtualenv activation (`source .venv/bin/activate`) | `uv run <cmd>` |
| pre-commit | prek (faster, no Python runtime needed) |

**Key principles:**
- Always use `uv add` and `uv remove` to manage dependencies
- Never manually activate or manage virtual environments—use `uv run` for all commands
- Use `[dependency-groups]` for dev/test/docs dependencies, not `[project.optional-dependencies]`

## Decision Tree

```
What are you doing?
│
├─ Single-file script with dependencies?
│   └─ Use PEP 723 inline metadata (./references/pep723-scripts.md)
│
├─ New multi-file project (not distributed)?
│   └─ Minimal uv setup (see Quick Start below)
│
├─ New reusable package/library?
│   └─ Full project setup (see Full Setup below)
│
└─ Migrating existing project?
    └─ See Migration Guide below
```

## Tool Overview

| Tool | Purpose | Replaces |
|------|---------|----------|
| **uv** | Package/dependency management | pip, virtualenv, pip-tools, pipx, pyenv |
| **ruff** | Linting AND formatting | flake8, black, isort, pyupgrade, pydocstyle |
| **ty** | Type checking | mypy, pyright (faster alternative) |
| **pytest** | Testing with coverage | unittest |
| **prek** | Pre-commit hooks ([setup](./references/prek.md)) | pre-commit (faster, Rust-native) |

### Security Tools

| Tool | Purpose | When It Runs |
|------|---------|--------------|
| **shellcheck** | Shell script linting | pre-commit |
| **detect-secrets** | Secret detection | pre-commit |
| **actionlint** | Workflow syntax validation | pre-commit, CI |
| **zizmor** | Workflow security audit | pre-commit, CI |
| **pip-audit** | Dependency vulnerability scanning | CI, manual |
| **Dependabot** | Automated dependency updates | scheduled |

See [security-setup.md](./references/security-setup.md) for configuration and usage.

## Quick Start: Minimal Project

For simple multi-file projects not intended for distribution:

```bash
# Create project with uv
uv init myproject
cd myproject

# Add dependencies
uv add requests rich

# Add dev dependencies
uv add --group dev pytest ruff ty

# Run code
uv run python src/myproject/main.py

# Run tools
uv run pytest
uv run ruff check .
```

## Full Project Setup
If starting from scratch, ask the user if they prefer to use the Trail of Bits cookiecutter template to bootstrap a complete project with already preconfigured tooling.

```bash
uvx cookiecutter gh:trailofbits/cookiecutter-python
```

### 1. Create Project Structure

```bash
uv init --package myproject
cd myproject
```

This creates:
```
myproject/
├── pyproject.toml','.claude\skills\modern-python\SKILL.md','310c14290df805d1c8d30dac7299517f37d063142d16f88d310814601fddc5a8','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:monorepo-navigator','project_skill','skill://simplicio-runtime/monorepo-navigator','skill: monorepo-navigator','---
name: monorepo-navigator
description: "Navigate, manage, and optimize monorepos. Covers Turborepo, Nx, pnpm workspaces, and Lerna. Cross-package impact analysis, selective builds/tests on affected packages, remote caching, dependency graph visualization, and structured multi-repo to monorepo migrations. Use when setting up a new monorepo, optimizing CI for a large workspace, debugging cross-package dependency issues, or planning a multi-repo consolidation."
---

# Monorepo Navigator

**Tier:** POWERFUL  
**Category:** Engineering  
**Domain:** Monorepo Architecture / Build Systems  

---

## Overview

Navigate, manage, and optimize monorepos. Covers Turborepo, Nx, pnpm workspaces, and Lerna. Enables cross-package impact analysis, selective builds/tests on affected packages only, remote caching, dependency graph visualization, and structured migrations from multi-repo to monorepo. Includes Claude Code configuration for workspace-aware development.

---

## Core Capabilities

- **Cross-package impact analysis** — determine which apps break when a shared package changes
- **Selective commands** — run tests/builds only for affected packages (not everything)
- **Dependency graph** — visualize package relationships as Mermaid diagrams
- **Build optimization** — remote caching, incremental builds, parallel execution
- **Migration** — step-by-step multi-repo → monorepo with zero history loss
- **Publishing** — changesets for versioning, pre-release channels, npm publish workflows
- **Claude Code config** — workspace-aware CLAUDE.md with per-package instructions

---

## When to Use

Use when:
- Multiple packages/apps share code (UI components, utils, types, API clients)
- Build times are slow because everything rebuilds when anything changes
- Migrating from multiple repos to a single repo
- Need to publish packages to npm with coordinated versioning
- Teams work across multiple packages and need unified tooling

Skip when:
- Single-app project with no shared packages
- Team/project boundaries are completely isolated (polyrepo is fine)
- Shared code is minimal and copy-paste overhead is acceptable

---

## Tool Selection

| Tool | Best For | Key Feature |
|---|---|---|
| **Turborepo** | JS/TS monorepos, simple pipeline config | Best-in-class remote caching, minimal config |
| **Nx** | Large enterprises, plugin ecosystem | Project graph, code generation, affected commands |
| **pnpm workspaces** | Workspace protocol, disk efficiency | `workspace:*` for local package refs |
| **Lerna** | npm publishing, versioning | Batch publishing, conventional commits |
| **Changesets** | Modern versioning (preferred over Lerna) | Changelog generation, pre-release channels |

Most modern setups: **pnpm workspaces + Turborepo + Changesets**

---

## Turborepo
→ See references/monorepo-tooling-reference.md for details

## Workspace Analyzer

```bash
python3 scripts/monorepo_analyzer.py /path/to/monorepo
python3 scripts/monorepo_analyzer.py /path/to/monorepo --json
```

Also see `references/monorepo-patterns.md` for common architecture and CI patterns.

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| Running `turbo run build` without `--filter` on every PR | Always use `--filter=...[origin/main]` in CI |
| `workspace:*` refs cause publish failures | Use `pnpm changeset publish` — it replaces `workspace:*` with real versions automatically |
| All packages rebuild when unrelated file changes | Tune `inputs` in turbo.json to exclude docs, config files from cache keys |
| Shared tsconfig causes one package to break all type-checks | Use `extends` properly — each package extends root but overrides `rootDir` / `outDir` |
| git history lost during migration | Use `git filter-repo --to-subdirectory-filter` before merging — never move files manually |
| Remote cache not working in CI | Check TURBO_TOKEN and TURBO_TEAM env vars; verify with `turbo run build --summarize` |
| CLAUDE.md too generic — Claude modifies wrong package | Add explicit "When working on X, only touch files in apps/X" rules per package CLAUDE.md |

---

## Best Practices

1. **Roo','.claude\skills\monorepo-navigator\SKILL.md','00e41353a1235ca7c165139638484789abd004b9aaff7195dfe6158085c6d218','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:motion-graphics','project_skill','skill://simplicio-runtime/motion-graphics','skill: motion-graphics','---
name: motion-graphics
description: >
  Use when the user wants a short, design-led motion graphic where motion is the
  message: kinetic typography, stat or number count-up, chart/data-viz hit,
  logo sting, brand lockup, lower-third, callout, social overlay, animated
  headline/tweet/news item, motion poster, or quick captured-page highlight.
  Usually under 10s and up to ~30s, with no narration arc, voice-over, or
  live-action subject. Can render to MP4 or transparent overlay. Not for longer,
  multi-scene, narrated, or brand-reel pieces (use general-video), narrated
  website videos (website-to-video), topic explainers
  (faceless-explainer), product promos (product-launch-video), PR videos
  (pr-to-video), or captions on existing footage (embedded-captions). When unsure whether it''s a
  quick motion-first piece or a longer / narrated treatment, see /hyperframes.
metadata:
  {
    "tags": "orchestrator, motion-graphics, kinetic-type, data-viz, logo-reveal, lower-thirds, news, tweet, webpage, asset-fusion, short-form, overlay, no-narration",
  }
---

# motion-graphics — dispatch entry

> **Confirm the route before Step 0.** This skill makes a **short, design-led, unnarrated motion graphic** (motion is the message; ~under 10s, no voice-over). A **longer, multi-scene, or narrated** treatment → `/general-video`; a **narrated video of a website** → `/website-to-video`; a **topic explainer** → `/faceless-explainer`; a **product promo** → `/product-launch-video`; **captions on existing footage** → `/embedded-captions`. **Out of scope**: live / at-render-time data, or footage it can''t capture. Unsure motion-first-vs-narrated? **Read `/hyperframes` first.**

A short design-led motion graphic. **Asset-first**: decide the asset strategy and source real material _before_ designing the shot, then design the shot around what you have, then compose by reusing catalog capabilities. All artifacts go to `PROJECT_DIR = videos/<project-name>/` (created in Step 0); all paths below are relative to it.

| Phase    | Execution                                                             | Primary artifact                                                 | Detailed flow                 |
| -------- | --------------------------------------------------------------------- | ---------------------------------------------------------------- | ----------------------------- |
| init     | Bash                                                                  | `hyperframes.json`                                               | Step 0                        |
| plan     | subagent — **decide search?** + classify + asset strategy             | `shot-plan.json` (draft: category, `asset_needs` queries, brief) | `agents/director.md` (Part 1) |
| source ◇ | Bash — media-use resolve (**skip if `asset_needs` is empty**)         | `assets/` + `assets/index.md`                                    | `phases/source/guide.md`      |
| design   | subagent — shot design around resolved assets                         | `shot-plan.json` (final: block(s) + layout + motion + positions) | `agents/director.md` (Part 2) |
| build    | subagent — reuse-first composition                                    | `compositions/index.html`                                        | `agents/builder.md`           |
| render   | Bash — `hyperframes render` (MP4, or `--format webm/mov` for overlay) | `renders/video.mp4`                                              | Step 5                        |
| verify   | Bash — `lint` / `inspect` -> repair subagent on failure               | (fixes in place)                                                 | `agents/finalize.md`          |

`◇ source` runs only when the chosen category declares assets. Pure code/text categories (e.g. `kinetic-type`, most `charts`/`stat`) have `asset_needs: []` and skip straight from plan to design.

## Categories — split by the search decision

`plan`''s **first decision is: does this need a search?** That fork splits the categories into two groups; then the specific category is picked — for search-driven, **by the ','.claude\skills\motion-graphics\SKILL.md','f1b2e947ccfb1087ba5686d0db217f8e1adbf20ae377e9bc3bb5679d7cf6297a','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:ms365-tenant-manager','project_skill','skill://simplicio-runtime/ms365-tenant-manager','skill: ms365-tenant-manager','---
name: ms365-tenant-manager
description: Microsoft 365 tenant administration for Global Administrators. Automate M365 tenant setup, Office 365 admin tasks, Azure AD user management, Exchange Online configuration, Teams administration, and security policies. Generate PowerShell scripts for bulk operations, Conditional Access policies, license management, and compliance reporting. Use for M365 tenant manager, Office 365 admin, Azure AD users, Global Administrator, tenant configuration, or Microsoft 365 automation.
---

# Microsoft 365 Tenant Manager

Expert guidance and automation for Microsoft 365 Global Administrators managing tenant setup, user lifecycle, security policies, and organizational optimization.

---

## Quick Start

### Run a Security Audit

```powershell
Connect-MgGraph -Scopes "Directory.Read.All","Policy.Read.All","AuditLog.Read.All"
Get-MgSubscribedSku | Select-Object SkuPartNumber, ConsumedUnits, @{N="Total";E={$_.PrepaidUnits.Enabled}}
Get-MgPolicyAuthorizationPolicy | Select-Object AllowInvitesFrom, DefaultUserRolePermissions
```

### Bulk Provision Users from CSV

```powershell
# CSV columns: DisplayName, UserPrincipalName, Department, LicenseSku
Import-Csv .\new_users.csv | ForEach-Object {
    $passwordProfile = @{ Password = (New-Guid).ToString().Substring(0,16) + "!"; ForceChangePasswordNextSignIn = $true }
    New-MgUser -DisplayName $_.DisplayName -UserPrincipalName $_.UserPrincipalName `
               -Department $_.Department -AccountEnabled -PasswordProfile $passwordProfile
}
```

### Create a Conditional Access Policy (MFA for Admins)

```powershell
$adminRoles = (Get-MgDirectoryRole | Where-Object { $_.DisplayName -match "Admin" }).Id
$policy = @{
    DisplayName = "Require MFA for Admins"
    State = "enabledForReportingButNotEnforced"   # Start in report-only mode
    Conditions = @{ Users = @{ IncludeRoles = $adminRoles } }
    GrantControls = @{ Operator = "OR"; BuiltInControls = @("mfa") }
}
New-MgIdentityConditionalAccessPolicy -BodyParameter $policy
```

### Bundled Python Generators

Three stdlib tools generate the PowerShell artifacts deterministically — prefer them over hand-writing scripts for bulk/repeatable work. Sample input: `sample_input.json`; expected shape: `expected_output.json`.

```bash
# Tenant setup: checklist + DNS records + license plan (JSON), or the full setup script
python3 scripts/tenant_setup.py --config sample_input.json --format json -o tenant_plan.json
python3 scripts/tenant_setup.py --config sample_input.json --format powershell -o tenant_setup.ps1

# User lifecycle: validate first, then generate creation/offboarding scripts
python3 scripts/user_management.py --domain acme.com --action validate --users users.json
python3 scripts/user_management.py --domain acme.com --action create --users users.json -o create_users.ps1
python3 scripts/user_management.py --domain acme.com --action offboard --user-email jane@acme.com -o offboard.ps1

# Admin scripts: CA policy / security audit / bulk licensing
python3 scripts/powershell_generator.py --tenant-domain acme.com --task conditional-access --policy-config policy.json -o ca_policy.ps1
python3 scripts/powershell_generator.py --tenant-domain acme.com --task security-audit -o audit.ps1
python3 scripts/powershell_generator.py --tenant-domain acme.com --task bulk-license --users-csv users.csv --license-sku ENTERPRISEPACK -o licenses.ps1
```

**Gate:** for user creation, run `--action validate` first and require every entry to report `"is_valid": true` before generating the creation script. Review every generated `.ps1` against the workflows below before running it in the tenant.

---

## Workflows

### Workflow 1: New Tenant Setup

**Step 1: Generate Setup Checklist**

Run `python3 scripts/tenant_setup.py --config tenant.json --format json` and work through `setup_checklist` phase by phase; `dns_records` feeds Step 2 and `license_recommendations` feeds the licensing workflow.

Confirm prerequisites before provisioning:
- Global Admin account created and secured with MFA
- Custom domain purchased and accessible for D','.claude\skills\ms365-tenant-manager\SKILL.md','18818578860589599175ecb94de1ca25e6dcc2c2a533b51ec5c73ebded9bac3d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:music-to-video','project_skill','skill://simplicio-runtime/music-to-video','skill: music-to-video','---
name: music-to-video
description: "Use when the user has a music track (an audio file, or a video to pull audio from) and wants a beat-synced HyperFrames video, calm to hard-hitting. The music drives everything: one analyzer reads it once, the orchestrator lays out the frames and fills a per-frame plan, and one sub-agent builds each frame. Typography and templates are the floor — a complete video needs zero assets — but any images or videos the user supplies are cut into the frames on the same beat grid (beat-cut / ken-burns). The genre (lyric video, slideshow, kinetic promo) falls out of the per-frame choices; the pipeline never branches on it."
---

# music-to-video — one music-grounded, beat-synced video workflow

Use this skill to turn a **music track** into a beat-synced HyperFrames video. You analyze the track once, lay out the frames, fill in a per-frame plan, and build each frame as a composition. The input is a music track plus optional user images or videos — there is **no narration and no website capture**. Typography and templates are the floor (a complete video needs zero assets); any media the user supplies is cut in on the same beat grid.

You are the **orchestrator**. Work in `videos/<project>/`. Run the steps in order and pass each **Gate** before moving on. Two steps need the user: **Step 3** (plan approval) and **Step 6** (render approval). Do every step yourself except **Step 4**, where you dispatch **one sub-agent per frame**. Keep design and motion rules out of this file — they live in `references/` and the `frame-worker` sub-agent.

`SKILL_DIR` = this skill directory. `PROJECT_DIR` = `videos/<project-name>/`.

Workflow: Step 0 setup → `hyperframes.json` + `assets/bgm.mp3`; Step 1 analyze → `audiomap.json`; Step 2 skeleton → `STORYBOARD.md` (frames, groups `TBD`); Step 3 plan → complete `STORYBOARD.md` + `frame.md`; Step 4 build → `compositions/frames/NN-*.html`; Step 5 assemble → `index.html`; Step 6 render → `renders/video.mp4`.

## Two ideas that shape everything

- **One analyzer, and you trust it.** `analyze-beatgrid.py` is the only beat analyzer — never re-measure beats with another tool or by ear. Its energy / density / rolls / onsets / silences are always reliable. Its `bpm` and `beats_sec` are reliable **only when the music is genuinely rhythmic**; on calm music the grid is a metronome the tracker imposed, so pace by phrases and energy instead and never hard-cut to it. Deciding which case you''re in is each frame''s `pacing` (Step 2).
- **One frame = one file; groups live inside.** Step 2 cuts the track into **frames**, and each frame becomes one composition file `compositions/frames/NN-<frame_id>.html`, built by one frame-worker. A frame can subdivide into **groups** (each a template or a motion-primitives combo). Extra density goes _inside_ a group, so **frame count tracks distinct treatments, not beats** — a fast track does not blow up the number of sub-agents.

---

## Step 0: Setup, BGM, and inputs

Goal: Establish the music source, create the HyperFrames project, and note any user-supplied media.

The **music is the spine** — establish one track before anything else. This skill is tuned for **fast, high-energy BGM**: a strong beat grid drives the cuts (calm tracks work, but pace by phrase rather than beat). If the user gave you audio — a music file, or a video to pull the audio from — use it. If not, generate one: choose the mood from the user''s description (e.g. "driving synthwave", "trap beat", "upbeat corporate") and produce a track via `/hyperframes-media` (`references/bgm.md` — HeyGen retrieval when credentialed, else local Lyria / MusicGen; ElevenLabs or another generator also works). Either way the track lands at `assets/bgm.mp3`. Stage any user-supplied images or videos so frames can weave them in on the beat grid; otherwise typography carries the whole video.

Initialize only if `hyperframes.json` is missing. Name `<project>` from the brief in kebab-case, such as `midnight-drive-loop` — never a timestamp.

```bash
npx hyperframes init "videos/<project>" --non-interactive --','.claude\skills\music-to-video\SKILL.md','3af895018d1f700cdf86b77c60e7acfef8535dbfa94d06e92c6d8bb305324d70','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:mutation-testing','project_skill','skill://simplicio-runtime/mutation-testing','skill: mutation-testing','---
name: mutation-testing
description: "Configures mewt or muton mutation testing campaigns — scopes targets, tunes timeouts, and optimizes long-running runs. Use when the user mentions mewt, muton, mutation testing, or wants to configure or optimize a mutation testing campaign."
allowed-tools: Read Write Bash Grep
---

# Mutation Testing — Campaign Configuration (mewt/muton)

> **Note**: muton and mewt share identical interfaces but target different languages — mewt for general-purpose languages (Rust, Solidity, Go, TypeScript, JavaScript), muton for TON smart contracts (Tact, Tolk, FunC). All examples use `mewt` commands, but they work exactly the same with `muton`. File names change accordingly: `mewt.toml` → `muton.toml`, `mewt.sqlite` → `muton.sqlite`.

## When to Use

Use this skill when the user:
- Mentions "mewt", "muton", or "mutation testing"
- Needs to configure or optimize a mutation testing campaign
- Wants to run `mewt run` and needs help getting set up first

## When NOT to Use

Do not use this skill when the user:
- Wants to analyze or report on completed campaign results
- Asks about tests or coverage without mentioning mutation testing

---

## Quick Start

Load [workflows/configuration.md](workflows/configuration.md) — a 5-phase guide from `mewt init` to a validated, ready-to-run campaign.

**General question or unfamiliar command?**
Run `mewt --help` or `mewt <subcommand> --help`, then assist.

---

## Reference Index

| File | Content |
|------|---------|
| [workflows/configuration.md](workflows/configuration.md) | 5-phase guide: init, scope, optimize, validate, run |
| [references/optimization-strategies.md](references/optimization-strategies.md) | Per-file targeting, two-phase campaigns, mutation type filtering |

---

## Essential Commands

```bash
# Initialize and mutate
mewt init                    # Create mewt.toml and mewt.sqlite
mewt mutate [paths]          # Generate mutants without running tests
mewt run [paths]             # Run the full campaign

# Inspect configuration and scope
mewt print config            # View effective configuration
mewt print targets           # Table of all targeted files
mewt print mutations --language [lang]  # Available mutation types
mewt status                  # Mutant count and per-file breakdown

# Investigate specific mutants
mewt print mutants --target [path]   # All mutants for a file
mewt print mutants --severity high   # Filter by severity
mewt print mutant --id [id]          # View mutated code diff
mewt test --ids [ids]                # Re-test specific mutants
```

---

## What Results Mean

- **Caught/TestFail**: Tests detected the mutation (good)
- **Uncaught**: Mutation survived — indicates untested logic
- **Timeout**: Tests took too long, inconclusive
- **Skipped**: A more severe mutant already failed on the same line

<!-- Source: https://github.com/trailofbits/skills (CC-BY-SA-4.0). Imported into Simplicio (lean: SKILL.md only). Area: security. -->
','.claude\skills\mutation-testing\SKILL.md','1fbcaf0643a3a34629130235e966250c9662f1ad9646f1fca05a1caf5f846412','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:nda-review','project_skill','skill://simplicio-runtime/nda-review','skill: nda-review','---
name: nda-review
description: >
  Reference: fast triage of inbound NDAs into GREEN / YELLOW / RED so the team only
  spends lawyer time on the ones that need it. Built for sales and BD to self-serve
  before pinging legal. Loaded by /commercial-legal:review when an NDA is detected.
user-invocable: false
---

# NDA Review

## Matter context

**Matter context.** Check `## Matter workspaces` in the practice-level CLAUDE.md. If `Enabled` is `✗` (the default for in-house users), skip the rest of this paragraph — skills use practice-level context and the matter machinery is invisible. If enabled and there is no active matter, ask: "Which matter is this for? Run `/commercial-legal:matter-workspace switch <slug>` or say `practice-level`." Load the active matter''s `matter.md` for matter-specific context and overrides. Write outputs to the matter folder at `~/.claude/plugins/config/claude-for-legal/commercial-legal/matters/<matter-slug>/`. Never read another matter''s files unless `Cross-matter context` is `on`.

---

## Destination check

Before producing output, check where it''s going. If the user has named a destination (a channel, a distribution list, a counterparty, "everyone"), ask whether it''s inside the privilege circle. Public channels, company-wide lists, counterparty/opposing counsel, vendors, and clients (for work product) waive the protection. When the destination looks outside the circle, flag it and offer (a) the privileged version for legal only, (b) a sanitized version for the broader channel, or (c) both — don''t silently apply a privileged header and then help paste it somewhere the header won''t protect it. See the canonical `## Shared guardrails → Destination check` in this plugin''s CLAUDE.md.

## Purpose

Most inbound NDAs are fine. A few have landmines. This skill sorts them in under a minute so legal only reads the ones that matter.

**The goal:** a GREEN NDA should need nothing more than a signature. A YELLOW needs a lawyer''s eyes on one or two specific things. A RED stops before anyone wastes time.

## Load the playbook first

**Which side?** Before applying the playbook, determine which side the company is on for this NDA. Usually obvious from the context: if the counterparty is a vendor or partner evaluating your product, you''re sales-side; if you''re evaluating theirs, you''re purchasing-side. Mutual NDAs still have a side — whose paper is it, and which direction is the evaluation running. If it''s not obvious, ask. Read the matching playbook section (`### Sales-side playbook` or `### Purchasing-side playbook`) from the config. Note which side in the output so the reviewer knows which playbook was applied. If the matching side is `[Not configured]`, stop and tell the user to run `/commercial-legal:cold-start-interview --side <side>` before this triage can proceed.

**Before triaging anything, read `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md` → `## Playbook` → the matching side → `NDA triage positions`.** That section is the source of truth for what makes an NDA GREEN, YELLOW, or RED for *this* team on *this* side. This skill does not ship with default positions on NDA terms — the law, the market, and each team''s risk tolerance vary too much for hardcoded defaults to be safe.

If `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md` doesn''t have an `NDA triage positions` section yet, or it''s silent on a term that comes up in the NDA you''re reviewing, ask the user:

> Your playbook doesn''t cover [term — e.g., "residuals clauses," "survival period," "one-way NDAs where you''re the receiver"]. What''s your default position — when should this be GREEN, when YELLOW, when RED? I''ll add it to `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md` so the next review is consistent.

Then record the answer in `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md` and proceed with the triage using the new position.

## Scope check

**Before reviewing NDA-specific provisions, check whether the document is doing more than its name suggests.** Mu','.claude\skills\nda-review\SKILL.md','884929b0ede90966f5f48d802bedbae710973bc7c8b4a5e38c3cc89febd29024','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:notebooklm','project_skill','skill://simplicio-runtime/notebooklm','skill: notebooklm','---
name: notebooklm
description: "Browser automation skill for controlling Google''s NotebookLM. Use when the user wants anything done in NotebookLM (e.g., ''open NotebookLM'', ''check my [name] notebook'', ''ask my notebook about X'', ''add [source] to NotebookLM'', ''generate a Video Overview from my notebook'', ''use NotebookLM Studio''). Handles reading and querying notebooks, adding sources (URLs, text, files, YouTube links, synthesized content), generating Studio outputs (Audio/Video Overviews, Mind Maps, Reports incl. Briefing Doc/Study Guide/FAQ, Flashcards, Quiz, slide decks, infographics — discover the exact set from the live Studio panel; the UI evolves fast), and creating new notebooks. Requires browser automation environment — fails gracefully when unavailable."
license: MIT
metadata:
  source_spec: "megaprompts/03-notebooklm-megaprompt.md"
  build_pattern: "Path B (direct conversion)"
  shape: "browser-automation (distinct from research-pack convention)"
  version: 1.0.0
---

# NotebookLM — Browser Automation

> **Requires:** A browser automation environment (Claude Code CLI with computer-use, Claude Chrome Extension, or equivalent). **Skill will gracefully fail in non-automation contexts with a clear "not supported" message.**

> **Critical:** This skill is the only browser-automation skill in the v2 collection. It does NOT follow the research-pack Agent Integrity Rules convention. Different constraints apply (UI dynamics, async generation, login walls).

## Step 0: Browser Context Setup (Mandatory)

Before any other action, verify browser automation is available:

1. Check whether browser-control tools are loaded in the harness (screenshot, click, find-element, navigate)
2. If unavailable → **halt with clear message:** "This skill requires browser automation. Currently in {context}. Cannot proceed. Use Claude Code CLI with computer-use, Claude Chrome Extension, or equivalent."
3. If available → take initial screenshot, navigate to https://notebooklm.google.com
4. **Detect login wall via screenshot.** If login screen detected: halt with "Please log in to NotebookLM in the browser, then re-invoke this skill." **Never attempt to handle login automatically.**

## Phase 0: Grill-Me Intake (Action-Routing)

Up to 4 forcing questions, one at a time, dependency-ordered. Most invocations stop at Q3.

### Q1 (root) — Action

> **What do you want me to do? Pick one:**
>
> 1. **Read / extract** — ask a question of an existing notebook
> 2. **Add a source** — push content (URL, text, file, Google Doc, or synthesized content) into a notebook
> 3. **Generate a Studio output** — Audio/Video Overview, Mind Map, Report (Briefing Doc, Study Guide, FAQ, Timeline), Flashcards, Quiz, Infographic, or Slides — the exact set comes from the live Studio panel
> 4. **Create a new notebook** — initialize with title + initial sources
>
> *Why I''m asking:* Each action takes a different path through the UI and requires different parameters. Naming the action upfront prevents wasted screenshots and lets me ask only the follow-up questions that apply.

**Forcing choice.** If the user says "open NotebookLM" without specifying an action, **refuse to start** and re-ask Q1.

### Q2 (depends on Q1) — Notebook identity

> **Which notebook?** *(asked for actions 1, 2, 3 — not for "create new")*
>
> *Why I''m asking:* If you give me a name, I''ll search the homepage; if you give me a URL, I''ll navigate directly. Names that are ambiguous will get a disambiguation prompt with screenshots.

For action 4 (create new): replace with "What''s the title for the new notebook?"

### Q3 (depends on Q1) — Action-specific parameter

**Action 1 (read/extract):**
> "What''s the question to ask the notebook? Use natural phrasing — the notebook''s chat handles it best."

**Action 2 (add source):**
> "What source type? Pick one:
> 1. URL / website / YouTube link
> 2. Copied text (paste here or point at content)
> 3. File upload (provide absolute path)
> 4. Google Doc (link)
> 5. Synthesized content (I''ll pre-process and add as ''Copied text'')
>
> *Why I''m asking:* Each source type ','.claude\skills\notebooklm\SKILL.md','881ee2c99e7673d63fda6eecc4a5d46b28c1395afb61c5cbac6de4e57c275cd5','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:observability-designer','project_skill','skill://simplicio-runtime/observability-designer','skill: observability-designer','---
name: observability-designer
description: "Design production-ready observability strategies combining metrics, logs, and traces. Includes SLI/SLO design, golden-signals monitoring, alert optimization. Use when adding observability to a new service, refactoring alerting that is too noisy, or designing an SLO program before scaling production load."
---

# Observability Designer (POWERFUL)

**Category:** Engineering  
**Tier:** POWERFUL  
**Description:** Design comprehensive observability strategies for production systems including SLI/SLO frameworks, alerting optimization, and dashboard generation.

## Overview

Observability Designer creates production-ready dashboards, alert configurations, and monitoring strategies across the three pillars (metrics, logs, traces).

**When NOT to use → slo-architect.** For SLO/SLI design with error-budget math, multi-window burn-rate alerting thresholds, and SLO review gates, route to `slo-architect` — it is the authoritative skill for that half. This skill''s `slo_designer.py` produces a quick scaffold only. This skill''s lane: dashboards (`dashboard_generator.py`) and alert-noise reduction (`alert_optimizer.py`).

## Quick Start

```bash
# Dashboard spec (Grafana JSON + docs) for a service
python3 scripts/dashboard_generator.py --service-type api --name payments --criticality critical --role sre --format grafana -o dashboard.json --doc-output dashboard.md

# Analyze an existing alert config for noise, duplicates, and coverage gaps
python3 scripts/alert_optimizer.py --input alerts.json --analyze-only --report alert_report.json
# ...then emit the optimized config once the report is reviewed:
python3 scripts/alert_optimizer.py --input alerts.json --output alerts_optimized.json

# Quick SLO scaffold (hand off to slo-architect for the real error-budget work)
python3 scripts/slo_designer.py --service-type api --criticality high --user-facing true --service-name payments -o slo_scaffold.json
```

**Verification loop:** after deploying optimized alerts, track the report''s noise metrics for one on-call rotation — if the actionable-alert ratio didn''t improve, re-run `--analyze-only` against the live config and iterate. Import the generated dashboard into Grafana and confirm every golden-signal panel renders with live data before closing the task.

## Core Competencies

### SLI/SLO/SLA Framework Design
- **Service Level Indicators (SLI):** Define measurable signals that indicate service health
- **Service Level Objectives (SLO):** Set reliability targets based on user experience
- **Service Level Agreements (SLA):** Establish customer-facing commitments with consequences
- **Error Budget Management:** Calculate and track error budget consumption
- **Burn Rate Alerting:** Multi-window burn rate alerts for proactive SLO protection

### Three Pillars of Observability

#### Metrics
- **Golden Signals:** Latency, traffic, errors, and saturation monitoring
- **RED Method:** Rate, Errors, and Duration for request-driven services
- **USE Method:** Utilization, Saturation, and Errors for resource monitoring
- **Business Metrics:** Revenue, user engagement, and feature adoption tracking
- **Infrastructure Metrics:** CPU, memory, disk, network, and custom resource metrics

#### Logs
- **Structured Logging:** JSON-based log formats with consistent fields
- **Log Aggregation:** Centralized log collection and indexing strategies
- **Log Levels:** Appropriate use of DEBUG, INFO, WARN, ERROR, FATAL levels
- **Correlation IDs:** Request tracing through distributed systems
- **Log Sampling:** Volume management for high-throughput systems

#### Traces
- **Distributed Tracing:** End-to-end request flow visualization
- **Span Design:** Meaningful span boundaries and metadata
- **Trace Sampling:** Intelligent sampling strategies for performance and cost
- **Service Maps:** Automatic dependency discovery through traces
- **Root Cause Analysis:** Trace-driven debugging workflows

### Dashboard Design Principles

#### Information Architecture
- **Hierarchy:** Overview → Service → Component → Instance drill-down paths','.claude\skills\observability-designer\SKILL.md','fc8ac37e50f1f65b65da55dd9b3f7dbfb0bdd6102fb5309fca92aeeda36312a9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:offers','project_skill','skill://simplicio-runtime/offers','skill: offers','---
name: offers
description: "When the user wants to design, construct, or improve an offer — the thing they actually sell — including value framing, bonus stacking, guarantee design, scarcity/urgency, naming, and payment structure. Also use when the user mentions ''offer,'' ''offer design,'' ''build an offer,'' ''grand slam offer,'' ''irresistible offer,'' ''value stack,'' ''bonus stack,'' ''guarantee,'' ''risk reversal,'' ''money-back guarantee,'' ''scarcity,'' ''urgency,'' ''high-ticket offer,'' ''productize a service,'' ''naming an offer,'' ''payment plan,'' ''down-sell,'' ''upsell offer,'' or ''why isn''t my offer converting.'' Best for services, agencies, courses, coaching, info products, high-ticket B2B, and direct-response. If you run pure self-serve SaaS, read pricing first — tiers and packaging do more work there. For price level itself (tiers, freemium, value metric), see pricing. For the page that presents the offer, see copywriting. For the launch moment, see launch. For sales collateral, see sales-enablement."
metadata:
  version: 1.0.0
---

# Offer Design

You are an expert in offer construction. Your goal is to help the user build offers that move — not by writing better copy on a worse offer, but by improving the offer itself.

## Before Starting

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

---

## Core Philosophy

**The offer is the thing, not the page.** Better copy on a weak offer compounds slowly. A stronger offer with average copy converts immediately. Most "we need better copy" requests are actually "we need a better offer" requests in disguise.

This skill exists because the rest of the repo handles the *expression* of an offer — `copywriting` writes the sales page, `cro` optimizes the conversion path, `pricing` sets the tier structure, `launch` orchestrates the moment, `paywalls` shapes the upgrade prompt. None of them ask the deeper question: **is the offer underneath any of that actually good?**

### When this skill matters

You sell:
- **Services** — consulting, freelance, agency retainers, productized services
- **Courses** — async, cohort-based, live
- **Coaching** — 1:1, group, mastermind
- **Info products** — guides, swipe files, templates, communities
- **High-ticket B2B** — $5K+ ACV with a sales conversation
- **Direct-response** — e-com promo offers, infomercial-style, paid-traffic-to-VSL

### When `pricing` does more of the work

You sell:
- **Self-serve SaaS** with tiered subscriptions — the levers are mostly tier structure, value metric, and packaging; offer construction (bonuses, guarantees) is secondary
- **Marketplaces** — the offer is structural, not constructed

Skim this skill in those cases for the value equation framing, then go to `pricing`.

---

## The Value Equation

The single most useful frame for offer design. Originally from Alex Hormozi''s *$100M Offers* — internalized broadly across direct-response and creator-economy training since.

```
              Dream Outcome  ×  Perceived Likelihood of Achievement
  Value  =  ─────────────────────────────────────────────────────────
              Time Delay     ×   Effort & Sacrifice
```

You move the four levers like this:

| Lever | What it means | How to increase value |
|-------|---------------|-----------------------|
| **Dream outcome** ↑ | What the customer actually wants | Connect to the bigger goal behind the surface ask. Specify and name it. |
| **Perceived likelihood** ↑ | Do they believe they''ll get it | Proof (case studies, named customers, data), guarantees, methodology specificity |
| **Time delay** ↓ | How long until result | Faster onboarding, faster first win, faster end-to-end timeline |
| **Effort & sacrifice** ↓ | What it costs them in time/work/risk besides money | Done-for-you, simpler process, fewer decisions, lower learning curve |

**Implication for offer construc','.claude\skills\offers\SKILL.md','3816d2116b99de1f41e2b8bbd39a0b2ee18b379bb8540de00739c29118fdb407','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:onboarding','project_skill','skill://simplicio-runtime/onboarding','skill: onboarding','---
name: onboarding
description: When the user wants to optimize post-signup onboarding, user activation, first-run experience, or time-to-value. Also use when the user mentions "onboarding flow," "activation rate," "user activation," "first-run experience," "empty states," "onboarding checklist," "aha moment," "new user experience," "users aren''t activating," "nobody completes setup," "low activation rate," "users sign up but don''t use the product," "time to value," or "first session experience." Use this whenever users are signing up but not sticking around. For signup/registration optimization, see signup. For ongoing email sequences, see emails.
metadata:
  version: 2.0.0
---

# Onboarding CRO

You are an expert in user onboarding and activation. Your goal is to help users reach their "aha moment" as quickly as possible and establish habits that lead to long-term retention.

## Initial Assessment

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Before providing recommendations, understand:

1. **Product Context** - What type of product? B2B or B2C? Core value proposition?
2. **Activation Definition** - What''s the "aha moment"? What action indicates a user "gets it"?
3. **Current State** - What happens after signup? Where do users drop off?

---

## Core Principles

### 1. Time-to-Value Is Everything
Remove every step between signup and experiencing core value.

### 2. One Goal Per Session
Focus first session on one successful outcome. Save advanced features for later.

### 3. Do, Don''t Show
Interactive > Tutorial. Doing the thing > Learning about the thing.

### 4. Progress Creates Motivation
Show advancement. Celebrate completions. Make the path visible.

---

## Defining Activation

### Find Your Aha Moment

The action that correlates most strongly with retention:
- What do retained users do that churned users don''t?
- What''s the earliest indicator of future engagement?

**Examples by product type:**
- Project management: Create first project + add team member
- Analytics: Install tracking + see first report
- Design tool: Create first design + export/share
- Marketplace: Complete first transaction

### Activation Metrics
- % of signups who reach activation
- Time to activation
- Steps to activation
- Activation by cohort/source

---

## Onboarding Flow Design

### Immediate Post-Signup (First 30 Seconds)

| Approach | Best For | Risk |
|----------|----------|------|
| Product-first | Simple products, B2C, mobile | Blank slate overwhelm |
| Guided setup | Products needing personalization | Adds friction before value |
| Value-first | Products with demo data | May not feel "real" |

**Whatever you choose:**
- Clear single next action
- No dead ends
- Progress indication if multi-step

### Onboarding Checklist Pattern

**When to use:**
- Multiple setup steps required
- Product has several features to discover
- Self-serve B2B products

**Best practices:**
- 3-7 items (not overwhelming)
- Order by value (most impactful first)
- Start with quick wins
- Progress bar/completion %
- Celebration on completion
- Dismiss option (don''t trap users)

### Empty States

Empty states are onboarding opportunities, not dead ends.

**Good empty state:**
- Explains what this area is for
- Shows what it looks like with data
- Clear primary action to add first item
- Optional: Pre-populate with example data

### Tooltips and Guided Tours

**When to use:** Complex UI, features that aren''t self-evident, power features users might miss

**Best practices:**
- Max 3-5 steps per tour
- Dismissable at any time
- Don''t repeat for returning users

---

## Multi-Channel Onboarding

### Email + In-App Coordination

**Trigger-based emails:**
- Welcome email (immediate)
- Incomplete onboarding (24h, 72h)
- Activation achieved (celebration + next step)
- Feature discovery (days 3','.claude\skills\onboarding\SKILL.md','eba0a2744f0a89708f0ee47d3f33018426b471bd756ae44476148f80fe08b819','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:ossfuzz','project_skill','skill://simplicio-runtime/ossfuzz','skill: ossfuzz','---
name: ossfuzz
type: technique
description: >
  OSS-Fuzz provides free continuous fuzzing for open source projects.
  Use when setting up continuous fuzzing infrastructure or enrolling projects.
---

# OSS-Fuzz

[OSS-Fuzz](https://google.github.io/oss-fuzz/) is an open-source project developed by Google that provides free distributed infrastructure for continuous fuzz testing. It streamlines the fuzzing process and facilitates simpler modifications. While only select projects are accepted into OSS-Fuzz, the project''s core is open-source, allowing anyone to host their own instance for private projects.

## Overview

OSS-Fuzz provides a simple CLI framework for building and starting harnesses or calculating their coverage. Additionally, OSS-Fuzz can be used as a service that hosts static web pages generated from fuzzing outputs such as coverage information.

### Key Concepts

| Concept | Description |
|---------|-------------|
| **helper.py** | CLI script for building images, building fuzzers, and running harnesses locally |
| **Base Images** | Hierarchical Docker images providing build dependencies and compilers |
| **project.yaml** | Configuration file defining project metadata for OSS-Fuzz enrollment |
| **Dockerfile** | Project-specific image with build dependencies |
| **build.sh** | Script that builds fuzzing harnesses for your project |
| **Criticality Score** | Metric used by OSS-Fuzz team to evaluate project acceptance |

## When to Apply

**Apply this technique when:**
- Setting up continuous fuzzing for an open-source project
- Need distributed fuzzing infrastructure without managing servers
- Want coverage reports and bug tracking integrated with fuzzing
- Testing existing OSS-Fuzz harnesses locally
- Reproducing crashes from OSS-Fuzz bug reports

**Skip this technique when:**
- Project is closed-source (unless hosting your own OSS-Fuzz instance)
- Project doesn''t meet OSS-Fuzz''s criticality score threshold
- Need proprietary or specialized fuzzing infrastructure
- Fuzzing simple scripts that don''t warrant infrastructure

## Quick Reference

| Task | Command |
|------|---------|
| Clone OSS-Fuzz | `git clone https://github.com/google/oss-fuzz` |
| Build project image | `python3 infra/helper.py build_image --pull <project>` |
| Build fuzzers with ASan | `python3 infra/helper.py build_fuzzers --sanitizer=address <project>` |
| Run specific harness | `python3 infra/helper.py run_fuzzer <project> <harness>` |
| Generate coverage report | `python3 infra/helper.py coverage <project>` |
| Check helper.py options | `python3 infra/helper.py --help` |

## OSS-Fuzz Project Components

OSS-Fuzz provides several publicly available tools and web interfaces:

### Bug Tracker

The [bug tracker](https://issues.oss-fuzz.com/issues?q=status:open) allows you to:
- Check bugs from specific projects (initially visible only to maintainers, later [made public](https://google.github.io/oss-fuzz/getting-started/bug-disclosure-guidelines/))
- Create new issues and comment on existing ones
- Search for similar bugs across **all projects** to understand issues

### Build Status System

The [build status system](https://oss-fuzz-build-logs.storage.googleapis.com/index.html) helps track:
- Build statuses of all included projects
- Date of last successful build
- Build failures and their duration

### Fuzz Introspector

[Fuzz Introspector](https://oss-fuzz-introspector.storage.googleapis.com/index.html) displays:
- Coverage data for projects enrolled in OSS-Fuzz
- Hit frequency for covered code
- Performance analysis and blocker identification

Read [this case study](https://github.com/ossf/fuzz-introspector/blob/main/doc/CaseStudies.md) for examples and explanations.

## Step-by-Step: Running a Single Harness

You don''t need to host the whole OSS-Fuzz platform to use it. The helper script makes it easy to run individual harnesses locally.

### Step 1: Clone OSS-Fuzz

```bash
git clone https://github.com/google/oss-fuzz
cd oss-fuzz
python3 infra/helper.py --help
```

### Step 2: Build Project Image

```bash
python3 infra/helper.py build_im','.claude\skills\ossfuzz\SKILL.md','4c749da485063e36c8195cfff1c5a58cf847d328b877969cd0b21dd1768d8968','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:patent','project_skill','skill://simplicio-runtime/patent','skill: patent','---
name: patent
description: "Patent prior-art and landscape intelligence skill — not generic patent help. Commits to one of five sub-use-cases via forcing intake (novelty search / freedom-to-operate / competitive landscape / acquisition diligence / litigation prior-art) before any search runs. Searches Google Patents, Espacenet, USPTO, and optionally Lens.org for citation-graph signals. Output is an editable Word document (.docx) with verdict, ranked closest art (claim-text extracted), CPC-class-aware landscape, family-resolved hits, geographic coverage, FTO flags where applicable, strategy recommendations, and full audit log. Use when the user asks for patent searching or analysis (e.g., ''prior art search for [invention]'', ''freedom to operate analysis for [product]''). Produces search signal, not legal advice — always recommends consulting a patent attorney before filing or licensing decisions. Trademark, copyright, and trade-secret questions are out of scope."
license: MIT
metadata:
  source_spec: "megaprompts/11-patent-megaprompt.md"
  build_pattern: "Path B (direct conversion)"
  research_pack_convention: "Agent Integrity Rules verbatim per PR #657 audit; sub-use-case routing variant"
  version: 1.0.0
---

# Patent — Prior-Art + Landscape Intelligence

> **Portability:** Requires `web_fetch` (Google Patents, Espacenet, USPTO), `WebSearch` (adjacent academic art), Node.js with `docx` package, and optionally Lens.org API key for citation-graph signals. Works in Claude Code CLI natively. In Claude.ai with web tools + Code Execution + BYOK Lens.org, the workflow is supported.

> **Out of scope:** trademark, copyright, trade-secret. These are flagged at intake. Use a different skill or qualified counsel.

> **Legal disclaimer:** This skill produces search signal, not legal advice. Verdicts are technical assessments. **Always consult a patent attorney before filing or licensing decisions.**

## Non-Generic Framing — The Differentiator

This skill is **prior-art + landscape intelligence**. It **refuses to be a bucket**. Every invocation commits to one of five sub-use-cases via the grill-me intake before any search runs. The chosen sub-use-case dictates the entire search strategy, ranking heuristics, and DOCX emphasis.

| Sub-use-case | Search strategy | DOCX emphasis |
|---|---|---|
| **Novelty search** | Narrow + claims-text focused; pre-filing date irrelevant | Closest art + claim-differentiation |
| **Freedom-to-operate** | Broad + active patents only; jurisdiction-filtered | FTO flags + claim-by-claim risk |
| **Competitive landscape** | Breadth + filer tally + CPC trends | Filer map + investment hotspots |
| **Acquisition diligence** | Specific assignee + portfolio scope + assignment chain | Portfolio table + ownership verification |
| **Litigation prior-art** | Specific target patent + adjacent art before priority date | Knock-out candidates ranked by relevance |

See [`references/sub_use_case_routing.md`](references/sub_use_case_routing.md) for the canon.

## Agent Integrity Rules (Research-Pack Convention)

Locked verbatim per PR #657 audit.

- **Execution discipline.** Sequential search calls only. **1 query/sec rate limit.** Confirm response received before next call.
- **Source discipline.** Cite only patents returned by THIS session''s tool calls. Training knowledge labeled `[Not from search — reference information]` and excluded from counts.
- **Three-count tracking.** Queries sent / patents received (shown) / patents cited. Surfaced in audit log.
- **Retry policy.** On failure → wait 3s → retry once → log. After 3 consecutive failures across tools: stop, alert user, explain what''s missing.
- **Plan-tier detection.** Lens.org free tier = 1000 queries/month. Google Patents has no auth but rate-limits per IP. Detect and surface caps.

## Phase 1: Grill-Me Intake (6 forcing questions, one at a time)

### Q1 (root) — Invention description

> **Describe the invention in 2–3 sentences. What does it do, and what''s new about it?**
>
> *Why I''m asking:* Concept and keyword extraction depends entirely on a precise descri','.claude\skills\patent\SKILL.md','7bf87d8f9a6eaca50cb849abc7004f44f3ea0270806efbb5f0855311c6b0b8e5','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:paywalls','project_skill','skill://simplicio-runtime/paywalls','skill: paywalls','---
name: paywalls
description: When the user wants to create or optimize in-app paywalls, upgrade screens, upsell modals, or feature gates. Also use when the user mentions "paywall," "upgrade screen," "upgrade modal," "upsell," "feature gate," "convert free to paid," "freemium conversion," "trial expiration screen," "limit reached screen," "plan upgrade prompt," "in-app pricing," "free users won''t upgrade," "trial to paid conversion," or "how do I get users to pay." Use this for any in-product moment where you''re asking users to upgrade. Distinct from public pricing pages (see cro) — this focuses on in-product upgrade moments where the user has already experienced value. For pricing decisions, see pricing.
metadata:
  version: 2.0.0
---

# Paywall and Upgrade Screen CRO

You are an expert in in-app paywalls and upgrade flows. Your goal is to convert free users to paid, or upgrade users to higher tiers, at moments when they''ve experienced enough value to justify the commitment.

## Initial Assessment

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Before providing recommendations, understand:

1. **Upgrade Context** - Freemium → Paid? Trial → Paid? Tier upgrade? Feature upsell? Usage limit?

2. **Product Model** - What''s free? What''s behind paywall? What triggers prompts? Current conversion rate?

3. **User Journey** - When does this appear? What have they experienced? What are they trying to do?

---

## Core Principles

### 1. Value Before Ask
- User should have experienced real value first
- Upgrade should feel like natural next step
- Timing: After "aha moment," not before

### 2. Show, Don''t Just Tell
- Demonstrate the value of paid features
- Preview what they''re missing
- Make the upgrade feel tangible

### 3. Friction-Free Path
- Easy to upgrade when ready
- Don''t make them hunt for pricing

### 4. Respect the No
- Don''t trap or pressure
- Make it easy to continue free
- Maintain trust for future conversion

---

## Paywall Trigger Points

### Feature Gates
When user clicks a paid-only feature:
- Clear explanation of why it''s paid
- Show what the feature does
- Quick path to unlock
- Option to continue without

### Usage Limits
When user hits a limit:
- Clear indication of limit reached
- Show what upgrading provides
- Don''t block abruptly

### Trial Expiration
When trial is ending:
- Early warnings (7, 3, 1 day)
- Clear "what happens" on expiration
- Summarize value received

### Time-Based Prompts
After X days of free use:
- Gentle upgrade reminder
- Highlight unused paid features
- Easy to dismiss

---

## Paywall Screen Components

1. **Headline** - Focus on what they get: "Unlock [Feature] to [Benefit]"

2. **Value Demonstration** - Preview, before/after, "With Pro you could..."

3. **Feature Comparison** - Highlight key differences, current plan marked

4. **Pricing** - Clear, simple, annual vs. monthly options

5. **Social Proof** - Customer quotes, "X teams use this"

6. **CTA** - Specific and value-oriented: "Start Getting [Benefit]"

7. **Escape Hatch** - Clear "Not now" or "Continue with Free"

---

## Specific Paywall Types

### Feature Lock Paywall
```
[Lock Icon]
This feature is available on Pro

[Feature preview/screenshot]

[Feature name] helps you [benefit]:
• [Capability]
• [Capability]

[Upgrade to Pro - $X/mo]
[Maybe Later]
```

### Usage Limit Paywall
```
You''ve reached your free limit

[Progress bar at 100%]

Free: 3 projects | Pro: Unlimited

[Upgrade to Pro]  [Delete a project]
```

### Trial Expiration Paywall
```
Your trial ends in 3 days

What you''ll lose:
• [Feature used]
• [Data created]

What you''ve accomplished:
• Created X projects

[Continue with Pro]
[Remind me later]  [Downgrade]
```

---

## Timing and Frequency

### When to Show
- After value moment, before frustration
- After activation/aha moment
- When ','.claude\skills\paywalls\SKILL.md','5f4a711b5b4a4b60c2ea233be44a7a50bbe880fd49c29f51591b6677b900e568','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:performance-profiler','project_skill','skill://simplicio-runtime/performance-profiler','skill: performance-profiler','---
name: performance-profiler
description: "Systematic performance profiling for Node.js, Python, and Go applications. Identifies CPU, memory, and I/O bottlenecks, generates flamegraphs, analyzes bundle sizes, optimizes database queries, runs load tests with k6 and Artillery. Always measures before and after. Use when investigating a slow endpoint, planning a performance budget, or hunting a memory leak in production."
---

# Performance Profiler

**Tier:** POWERFUL  
**Category:** Engineering  
**Domain:** Performance Engineering  

---

## Overview

Systematic performance profiling for Node.js, Python, and Go applications. Identifies CPU, memory, and I/O bottlenecks; generates flamegraphs; analyzes bundle sizes; optimizes database queries; detects memory leaks; and runs load tests with k6 and Artillery. Always measures before and after.

## Core Capabilities

- **CPU profiling** — flamegraphs for Node.js, py-spy for Python, pprof for Go
- **Memory profiling** — heap snapshots, leak detection, GC pressure
- **Bundle analysis** — webpack-bundle-analyzer, Next.js bundle analyzer
- **Database optimization** — EXPLAIN ANALYZE, slow query log, N+1 detection
- **Load testing** — k6 scripts, Artillery scenarios, ramp-up patterns
- **Before/after measurement** — establish baseline, profile, optimize, verify

---

## When to Use

- App is slow and you don''t know where the bottleneck is
- P99 latency exceeds SLA before a release
- Memory usage grows over time (suspected leak)
- Bundle size increased after adding dependencies
- Preparing for a traffic spike (load test before launch)
- Database queries taking >100ms

---

## Quick Start

```bash
# Analyze a project for performance risk indicators
python3 scripts/performance_profiler.py /path/to/project

# JSON output for CI integration
python3 scripts/performance_profiler.py /path/to/project --json

# Custom large-file threshold
python3 scripts/performance_profiler.py /path/to/project --large-file-threshold-kb 256
```

---

## Golden Rule: Measure First

```bash
# Establish baseline BEFORE any optimization
# Record: P50, P95, P99 latency | RPS | error rate | memory usage

# Wrong: "I think the N+1 query is slow, let me fix it"
# Right: Profile → confirm bottleneck → fix → measure again → verify improvement
```

---

## Node.js Profiling
→ See references/profiling-recipes.md for details

## References

- [references/profiling-recipes.md](references/profiling-recipes.md) — Node.js/Python/Go profiling commands, flamegraph generation, heap snapshots
- [references/optimization-playbook.md](references/optimization-playbook.md) — before/after measurement template, quick-win optimization checklist (DB/Node/bundle/API), common pitfalls, best practices


<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\performance-profiler\SKILL.md','a1ecc9bc2198f6856ee070d2b17e5713da3fb92dd9a297b79d802423ff01224a','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pm-skills','project_skill','skill://simplicio-runtime/pm-skills','skill: pm-skills','---
name: pm-skills
description: "Router/index for the 8 project-management skills bundled in this plugin (senior PM quant toolkit, scrum master, Jira/JQL, Confluence, Atlassian admin, Atlassian templates, meeting analyzer, team communications). Use when a PM request doesn''t obviously match one skill and you need to pick the right one (e.g., ''our sprints feel off'', ''audit our Jira permissions''). Bundles an Atlassian Remote MCP config (.mcp.json) for live Jira/Confluence access."
version: 2.9.0
author: Alireza Rezvani
license: MIT
tags:
  - project-management
  - jira
  - confluence
  - atlassian
  - scrum
  - agile
agents:
  - claude-code
  - codex-cli
  - openclaw
---

# Project Management Skills — Router

This plugin bundles **8 PM skills** (this router is the 9th folder under `project-management/skills/`). Each skill is self-contained. The bundled `.mcp.json` wires the Atlassian Remote MCP (`https://mcp.atlassian.com/v1/sse`, OAuth handled by Claude Code).

## Routing table

Match the request, then load `project-management/skills/<skill>/SKILL.md`. If multiple rows match, ask one clarifying question first.

| Request signals | Skill | Path |
|---|---|---|
| Project health, risk EMV, three-point estimates | senior-pm | `skills/senior-pm/` |
| Sprint velocity, retro analysis, ceremony health | scrum-master | `skills/scrum-master/` |
| JQL queries, Jira workflows, boards | jira-expert | `skills/jira-expert/` |
| Confluence spaces, page structure, content audits | confluence-expert | `skills/confluence-expert/` |
| User/permission/scheme administration | atlassian-admin | `skills/atlassian-admin/` |
| Reusable Confluence/Jira templates | atlassian-templates | `skills/atlassian-templates/` |
| Meeting transcripts, talk-time, action items | meeting-analyzer | `skills/meeting-analyzer/` |
| Status updates, 3P updates, stakeholder comms | team-communications | `skills/team-communications/` |

## Quick start

```bash
# Example: route a sprint-health request
cat project-management/skills/scrum-master/SKILL.md
ls project-management/skills/scrum-master/scripts/
```

## Rules

- Live Jira/Confluence operations go through the Atlassian Remote MCP (camelCase tool names such as `createJiraIssue`, `searchJiraIssuesUsingJql`, `createConfluencePage` — canonical list in `project-management/references/atlassian-mcp-tools.md`). Admin operations are NOT covered by the MCP — use admin.atlassian.com or the REST API per atlassian-admin.
- Route to exactly one skill, then follow that skill''s workflow. This router ships no tools of its own.

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: project-management. -->
','.claude\skills\pm-skills\SKILL.md','fba5eab1710c964586db4d179a08907d60be5226b977fc42938ed87b4d944082','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:popups','project_skill','skill://simplicio-runtime/popups','skill: popups','---
name: popups
description: When the user wants to create or optimize popups, modals, overlays, slide-ins, or banners for conversion purposes. Also use when the user mentions "exit intent," "popup conversions," "modal optimization," "lead capture popup," "email popup," "announcement banner," "overlay," "collect emails with a popup," "exit popup," "scroll trigger," "sticky bar," or "notification bar." Use this for any overlay or interrupt-style conversion element. For forms outside of popups, see cro. For general page conversion optimization, see cro.
metadata:
  version: 2.0.0
---

# Popup CRO

You are an expert in popup and modal optimization. Your goal is to create popups that convert without annoying users or damaging brand perception.

## Initial Assessment

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Before providing recommendations, understand:

1. **Popup Purpose**
   - Email/newsletter capture
   - Lead magnet delivery
   - Discount/promotion
   - Announcement
   - Exit intent save
   - Feature promotion
   - Feedback/survey

2. **Current State**
   - Existing popup performance?
   - What triggers are used?
   - User complaints or feedback?
   - Mobile experience?

3. **Traffic Context**
   - Traffic sources (paid, organic, direct)
   - New vs. returning visitors
   - Page types where shown

---

## Core Principles

### 1. Timing Is Everything
- Too early = annoying interruption
- Too late = missed opportunity
- Right time = helpful offer at moment of need

### 2. Value Must Be Obvious
- Clear, immediate benefit
- Relevant to page context
- Worth the interruption

### 3. Respect the User
- Easy to dismiss
- Don''t trap or trick
- Remember preferences
- Don''t ruin the experience

---

## Trigger Strategies

### Time-Based
- **Not recommended**: "Show after 5 seconds"
- **Better**: "Show after 30-60 seconds" (proven engagement)
- Best for: General site visitors

### Scroll-Based
- **Typical**: 25-50% scroll depth
- Indicates: Content engagement
- Best for: Blog posts, long-form content
- Example: "You''re halfway through—get more like this"

### Exit Intent
- Detects cursor moving to close/leave
- Last chance to capture value
- Best for: E-commerce, lead gen
- Mobile alternative: Back button or scroll up

### Click-Triggered
- User initiates (clicks button/link)
- Zero annoyance factor
- Best for: Lead magnets, gated content, demos
- Example: "Download PDF" → Popup form

### Page Count / Session-Based
- After visiting X pages
- Indicates research/comparison behavior
- Best for: Multi-page journeys
- Example: "Been comparing? Here''s a summary..."

### Behavior-Based
- Add to cart abandonment
- Pricing page visitors
- Repeat page visits
- Best for: High-intent segments

---

## Popup Types

### Email Capture Popup
**Goal**: Newsletter/list subscription

**Best practices:**
- Clear value prop (not just "Subscribe")
- Specific benefit of subscribing
- Single field (email only)
- Consider incentive (discount, content)

**Copy structure:**
- Headline: Benefit or curiosity hook
- Subhead: What they get, how often
- CTA: Specific action ("Get Weekly Tips")

### Lead Magnet Popup
**Goal**: Exchange content for email

**Best practices:**
- Show what they get (cover image, preview)
- Specific, tangible promise
- Minimal fields (email, maybe name)
- Instant delivery expectation

### Discount/Promotion Popup
**Goal**: First purchase or conversion

**Best practices:**
- Clear discount (10%, $20, free shipping)
- Deadline creates urgency
- Single use per visitor
- Easy to apply code

### Exit Intent Popup
**Goal**: Last-chance conversion

**Best practices:**
- Acknowledge they''re leaving
- Different offer than entry popup
- Address common objections
- Final compelling reason to stay

**Formats:**
- "Wait! Before you go..."
- "Forget something?"
- "Get 10% ','.claude\skills\popups\SKILL.md','11fcb5ba134495e81681991e61f1394d9b9a4469796f04e66401f6cf96d6b86d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pr-review-expert','project_skill','skill://simplicio-runtime/pr-review-expert','skill: pr-review-expert','---
name: pr-review-expert
description: "Use when the user asks to review pull requests, analyze code changes, check for security issues in PRs, or assess code quality of diffs."
---

# PR Review Expert

**Tier:** POWERFUL
**Category:** Engineering
**Domain:** Code Review / Quality Assurance

---

## Overview

Structured, systematic code review for GitHub PRs and GitLab MRs. Goes beyond style nits — this skill
performs blast radius analysis, security scanning, breaking change detection, and test coverage delta
calculation. Produces a reviewer-ready report with a 30+ item checklist and prioritized findings.

---

## Core Capabilities

- **Blast radius analysis** — trace which files, services, and downstream consumers could break
- **Security scan** — SQL injection, XSS, auth bypass, secret exposure, dependency vulns
- **Test coverage delta** — new code vs new tests ratio
- **Breaking change detection** — API contracts, DB schema migrations, config keys
- **Ticket linking** — verify Jira/Linear ticket exists and matches scope
- **Performance impact** — N+1 queries, bundle size regression, memory allocations

---

## When to Use

- Before merging any PR/MR that touches shared libraries, APIs, or DB schema
- When a PR is large (>200 lines changed) and needs structured review
- Onboarding new contributors whose PRs need thorough feedback
- Security-sensitive code paths (auth, payments, PII handling)
- After an incident — review similar PRs proactively

---

## Fetching the Diff

### GitHub (gh CLI)
```bash
# View diff in terminal
gh pr diff <PR_NUMBER>

# Get PR metadata (title, body, labels, linked issues)
gh pr view <PR_NUMBER> --json title,body,labels,assignees,milestone

# List files changed
gh pr diff <PR_NUMBER> --name-only

# Check CI status
gh pr checks <PR_NUMBER>

# Download diff to file for analysis
gh pr diff <PR_NUMBER> > /tmp/pr-<PR_NUMBER>.diff
```

### GitLab (glab CLI)
```bash
# View MR diff
glab mr diff <MR_IID>

# MR details as JSON
glab mr view <MR_IID> --output json

# List changed files
glab mr diff <MR_IID> --name-only

# Download diff
glab mr diff <MR_IID> > /tmp/mr-<MR_IID>.diff
```

---

## Workflow

### Step 1 — Fetch Context

```bash
PR=123
gh pr view $PR --json title,body,labels,milestone,assignees | jq .
gh pr diff $PR --name-only
gh pr diff $PR > /tmp/pr-$PR.diff
```

### Step 2 — Blast Radius Analysis

For each changed file, identify:

1. **Direct dependents** — who imports this file?
```bash
# Find all files importing a changed module
grep -r "from [''\"].*changed-module[''\"]" src/ --include="*.ts" -l
grep -r "require([''\"].*changed-module" src/ --include="*.js" -l

# Python
grep -r "from changed_module import\|import changed_module" . --include="*.py" -l
```

2. **Service boundaries** — does this change cross a service?
```bash
# Check if changed files span multiple services (monorepo)
gh pr diff $PR --name-only | cut -d/ -f1-2 | sort -u
```

3. **Shared contracts** — types, interfaces, schemas
```bash
gh pr diff $PR --name-only | grep -E "types/|interfaces/|schemas/|models/"
```

**Blast radius severity:**
- CRITICAL — shared library, DB model, auth middleware, API contract
- HIGH     — service used by >3 others, shared config, env vars
- MEDIUM   — single service internal change, utility function
- LOW      — UI component, test file, docs

### Step 3 — Security Scan

```bash
DIFF=/tmp/pr-$PR.diff

# SQL Injection — raw query string interpolation
grep -n "query\|execute\|raw(" $DIFF | grep -E ''\$\{|f"|%s|format\(''

# Hardcoded secrets
grep -nE "(password|secret|api_key|token|private_key)\s*=\s*[''\"][^''\"]{8,}" $DIFF

# AWS key pattern
grep -nE "AKIA[0-9A-Z]{16}" $DIFF

# JWT secret in code
grep -nE "jwt\.sign\(.*[''\"][^''\"]{20,}[''\"]" $DIFF

# XSS vectors
grep -n "dangerouslySetInnerHTML\|innerHTML\s*=" $DIFF

# Auth bypass patterns
grep -n "bypass\|skip.*auth\|noauth\|TODO.*auth" $DIFF

# Insecure hash algorithms
grep -nE "md5\(|sha1\(|createHash\([''\"]md5|createHash\([''\"]sha1" $DIFF

# eval / exec
grep -nE "\beval\(|\bexec\(|\bsubprocess\.call\(" $DIFF

# Prototype pollution
grep -n "__pro','.claude\skills\pr-review-expert\SKILL.md','264b04a2b8fd9bd6c0dc2290d012b55b0f09eba862ca56922152536c813e3f6f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pr-to-video','project_skill','skill://simplicio-runtime/pr-to-video','skill: pr-to-video','---
name: pr-to-video
description: "turn a GitHub pull request (a PR URL like github.com/<owner>/<repo>/pull/<N>, an <owner>/<repo>#<N> ref, or ''this PR'' in a checked-out repo) into a code-change explainer video, up to ~3 min (sweet spot 30-90s) — changelog, feature reveal, fix, or refactor walkthrough, rendered from the diff / commits / files. The input is a CODE CHANGE read via the gh CLI; there is no website capture. Use this skill for a GitHub PR. Do not use it for a product launch/promo (use /product-launch-video), a tour of a real website (use /website-to-video), a topic explainer with no PR (use /faceless-explainer), captions on existing footage (use /embedded-captions), or a short unnarrated motion graphic (use /motion-graphics). If the intent is unclear, route through /hyperframes first."
---

# PR to HyperFrames

Use this skill to ingest a GitHub pull request, understand the change, plan a code-change explainer, and build it frame by frame in HyperFrames. The input is a **code change** (read via `gh`), not a website — there is **no capture step and no real assets** beyond the contributors'' avatars.

> **Confirm the route before Step 0.** You are the orchestrator. Run each step, verify its gate, and only then continue. This skill is for a **GitHub pull request** (a code change). Route other intents elsewhere: a product launch/promo → `/product-launch-video`; a general website tour → `/website-to-video`; a topic explainer with no PR → `/faceless-explainer`; captions on existing footage → `/embedded-captions`; a short unnarrated motion graphic → `/motion-graphics`; a whole-repo or multi-PR release walkthrough → `/general-video`. **Out of scope:** live / at-render-time data — PR facts are read once at author time and baked in. If the user says only "make a video" or the route is uncertain, read `/hyperframes` first.

You are the orchestrator. Work in `videos/<project>/`. Run steps in order and pass each gate before continuing. User-gated steps are Step 0, Step 3, and Step 6. Do every step yourself except Step 5, where you dispatch one sub-agent per frame. Do not put design or motion rules here; those live in the frame-worker sub-agent, `hyperframes-creative`, and `hyperframes-animation`.

Workflow: Step 0 setup → `hyperframes.json`; Step 1 ingest → `capture/extracted/` + `assets/<login>.png`; Step 2 design system → `frame.md`; Step 3 storyboard/script → `STORYBOARD.md` and `SCRIPT.md`; Step 3.1 audio → `audio_meta.json`; Step 4 visual design → enriched `STORYBOARD.md`; Step 5 frames → `compositions/frames/NN-*.html` and `index.html`; Step 6 final render → `renders/video.mp4`.

---

## Step 0: Setup and Brief

Goal: Lock the PR reference and the core video brief, and create the HyperFrames project if needed.

Get the **PR reference** (a full URL, an `<owner>/<repo>#<N>` ref, or "this PR" in a checked-out repo) and, in one message, confirm the brief — lead with a recommended default for each and pre-fill anything `/hyperframes` already set: **angle** (changelog / feature-reveal / fix-explainer / refactor-walkthrough — default: infer from the PR), **audience** (default: developers), **length** (default ~60-90s), **aspect** (default 16:9), **language**. The style is always **claude**. Proceed only after the user replies; a "go" accepts the defaults.

Initialize only if `hyperframes.json` is missing. Name `<project>` from the PR in kebab-case, such as `acme-sdk-pr-1842`; never use the workspace name or a timestamp.

`npx hyperframes init "videos/<project>" --non-interactive --skip-skills --example=blank`

**Gate:** `hyperframes.json` exists; the PR ref is captured; angle, length, aspect ratio, and language are locked.

---

## Step 1: Ingest the PR (no capture)

Goal: Fetch the PR''s facts and fold them into the project as the source of information. There is **no website capture**. `fetch-pr.mjs` runs `gh` deterministically — completing the files list via paginated `gh api` so a large PR doesn''t truncate at ~100 files, and writing only `capture/pr.json` + `capture/diff.patch` (no scratch dir). Then `ingest.mjs` folds tha','.claude\skills\pr-to-video\SKILL.md','927d7975e48fe6fcd9c294e9c0f8eded249ed0dec3d38768c67fd824affd17b3','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pricing','project_skill','skill://simplicio-runtime/pricing','skill: pricing','---
name: pricing
description: "When the user wants help with pricing decisions, packaging, or monetization strategy. Also use when the user mentions ''pricing,'' ''pricing tiers,'' ''freemium,'' ''free trial,'' ''packaging,'' ''price increase,'' ''value metric,'' ''Van Westendorp,'' ''willingness to pay,'' ''monetization,'' ''how much should I charge,'' ''my pricing is wrong,'' ''pricing page,'' ''annual vs monthly,'' ''per seat pricing,'' or ''should I offer a free plan.'' Use this whenever someone is figuring out what to charge or how to structure their plans. For in-app upgrade screens, see paywalls. For offer construction (bonuses, guarantees, value framing, naming) on services/courses/coaching/high-ticket B2B, see offers."
metadata:
  version: 2.0.1
---

# Pricing Strategy

You are an expert in SaaS pricing and monetization strategy. Your goal is to help design pricing that captures value, drives growth, and aligns with customer willingness to pay.

## Before Starting

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Gather this context (ask if not provided):

### 1. Business Context
- What type of product? (SaaS, marketplace, e-commerce, service)
- What''s your current pricing (if any)?
- What''s your target market? (SMB, mid-market, enterprise)
- What''s your go-to-market motion? (self-serve, sales-led, hybrid)

### 2. Value & Competition
- What''s the primary value you deliver?
- What alternatives do customers consider?
- How do competitors price?

### 3. Current Performance
- What''s your current conversion rate?
- What''s your ARPU and churn rate?
- Any feedback on pricing from customers/prospects?

### 4. Goals
- Optimizing for growth, revenue, or profitability?
- Moving upmarket or expanding downmarket?

---

## Pricing Fundamentals

### The Three Pricing Axes

**1. Packaging** — What''s included at each tier?
- Features, limits, support level
- How tiers differ from each other

**2. Pricing Metric** — What do you charge for?
- Per user, per usage, flat fee
- How price scales with value

**3. Price Point** — How much do you charge?
- The actual dollar amounts
- Perceived value vs. cost

### Value-Based Pricing

Price should be based on value delivered, not cost to serve:

- **Customer''s perceived value** — The ceiling
- **Your price** — Between alternatives and perceived value
- **Next best alternative** — The floor for differentiation
- **Your cost to serve** — Only a baseline, not the basis

**Key insight:** Price between the next best alternative and perceived value.

---

## Value Metrics

### What is a Value Metric?

The value metric is what you charge for—it should scale with the value customers receive.

**Good value metrics:**
- Align price with value delivered
- Are easy to understand
- Scale as customer grows
- Are hard to game

### Common Value Metrics

| Metric | Best For | Example |
|--------|----------|---------|
| Per user/seat | Collaboration tools | Slack, Notion |
| Per usage | Variable consumption | AWS, Twilio |
| Per feature | Modular products | HubSpot add-ons |
| Per contact/record | CRM, email tools | Mailchimp |
| Per transaction | Payments, marketplaces | Stripe |
| Flat fee | Simple products | Basecamp |

### Choosing Your Value Metric

Ask: "As a customer uses more of [metric], do they get more value?"
- If yes → good value metric
- If no → price doesn''t align with value

---

## Tier Structure Overview

### Good-Better-Best Framework

**Good tier (Entry):** Core features, limited usage, low price
**Better tier (Recommended):** Full features, reasonable limits, anchor price
**Best tier (Premium):** Everything, advanced features, 2-3x Better price

### Tier Differentiation

- **Feature gating** — Basic vs. advanced features
- **Usage limits** — Same features, different limits
- **Support level** — Email → Priority → Dedicated
- **Access** — API, SSO, ','.claude\skills\pricing\SKILL.md','7f747d120ac9fa08a560438bc9a6421620fd62c7da4c6aa35d77b7b015bad1dd','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:product-analytics','project_skill','skill://simplicio-runtime/product-analytics','skill: product-analytics','---
name: product-analytics
description: Use when defining product KPIs, building metric dashboards, running cohort or retention analysis, or interpreting feature adoption trends across product stages.
---

# Product Analytics

Define, track, and interpret product metrics across discovery, growth, and mature product stages.

## When To Use

Use this skill for:
- Metric framework selection (AARRR, North Star, HEART)
- KPI definition by product stage (pre-PMF, growth, mature)
- Dashboard design and metric hierarchy
- Cohort and retention analysis
- Feature adoption and funnel interpretation

## Workflow

1. Select metric framework
- AARRR for growth loops and funnel visibility
- North Star for cross-functional strategic alignment
- HEART for UX quality and user experience measurement

2. Define stage-appropriate KPIs
- Pre-PMF: activation, early retention, qualitative success
- Growth: acquisition efficiency, expansion, conversion velocity
- Mature: retention depth, revenue quality, operational efficiency

3. Design dashboard layers
- Executive layer: 5-7 directional metrics
- Product health layer: acquisition, activation, retention, engagement
- Feature layer: adoption, depth, repeat usage, outcome correlation

4. Run cohort + retention analysis
- Segment by signup cohort or feature exposure cohort
- Compare retention curves, not single-point snapshots
- Identify inflection points around onboarding and first value moment

5. Interpret and act
- Connect metric movement to product changes and release timeline
- Distinguish signal from noise using period-over-period context
- Propose one clear product action per major metric risk/opportunity

## KPI Guidance By Stage

### Pre-PMF
- Activation rate
- Week-1 retention
- Time-to-first-value
- Problem-solution fit interview score

### Growth
- Funnel conversion by stage
- Monthly retained users
- Feature adoption among new cohorts
- Expansion / upsell proxy metrics

### Mature
- Net revenue retention aligned product metrics
- Power-user share and depth of use
- Churn risk indicators by segment
- Reliability and support-deflection product metrics

## Dashboard Design Principles

- Show trends, not isolated point estimates.
- Keep one owner per KPI.
- Pair each KPI with target, threshold, and decision rule.
- Use cohort and segment filters by default.
- Prefer comparable time windows (weekly vs weekly, monthly vs monthly).

See:
- `references/metrics-frameworks.md`
- `references/dashboard-templates.md`

## Cohort Analysis Method

1. Define cohort anchor event (signup, activation, first purchase).
2. Define retained behavior (active day, key action, repeat session).
3. Build retention matrix by cohort week/month and age period.
4. Compare curve shape across cohorts.
5. Flag early drop points and investigate journey friction.

## Retention Curve Interpretation

- Sharp early drop, low plateau: onboarding mismatch or weak initial value.
- Moderate drop, stable plateau: healthy core audience with predictable churn.
- Flattening at low level: product used occasionally, revisit value metric.
- Improving newer cohorts: onboarding or positioning improvements are working.

## Anti-Patterns

| Anti-pattern | Fix |
|---|---|
| **Vanity metrics** — tracking pageviews or total signups without activation context | Always pair acquisition metrics with activation rate and retention |
| **Single-point retention** — reporting "30-day retention is 20%" | Compare retention curves across cohorts, not isolated snapshots |
| **Dashboard overload** — 30+ metrics on one screen | Executive layer: 5-7 metrics. Feature layer: per-feature only |
| **No decision rule** — tracking a KPI with no threshold or action plan | Every KPI needs: target, threshold, owner, and "if below X, then Y" |
| **Averaging across segments** — reporting blended metrics that hide segment differences | Always segment by cohort, plan tier, channel, or geography |
| **Ignoring seasonality** — comparing this week to last week without adjusting | Use period-over-period with same-period-last-year context |

## Tooling

### `scripts/metric','.claude\skills\product-analytics\SKILL.md','85e78076d6e36991fc6fd6ac790e3992fdefd117992a524ac0119b69fdc3528f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:product-discovery','project_skill','skill://simplicio-runtime/product-discovery','skill: product-discovery','---
name: product-discovery
description: Use when validating product opportunities, mapping assumptions, planning discovery sprints, or testing problem-solution fit before committing delivery resources.
---

# Product Discovery

Run structured discovery to identify high-value opportunities and de-risk product bets.

## When To Use

Use this skill for:
- Opportunity Solution Tree facilitation
- Assumption mapping and test planning
- Problem validation interviews and evidence synthesis
- Solution validation with prototypes/experiments
- Discovery sprint planning and outputs

## Core Discovery Workflow

1. Define desired outcome
- Set one measurable outcome to improve.
- Establish baseline and target horizon.

2. Build Opportunity Solution Tree (OST)
- Outcome -> opportunities -> solution ideas -> experiments
- Keep opportunities grounded in user evidence, not internal opinions.

3. Map assumptions
- Identify desirability, viability, feasibility, and usability assumptions.
- Score assumptions by risk and certainty.

Use:
```bash
python3 scripts/assumption_mapper.py assumptions.csv
```

4. Validate the problem
- Conduct interviews and behavior analysis.
- Confirm frequency, severity, and willingness to solve.
- Reject weak opportunities early.

5. Validate the solution
- Prototype before building.
- Run concept, usability, and value tests.
- Measure behavior, not only stated preference.

6. Plan discovery sprint
- 1-2 week cycle with explicit hypotheses
- Daily evidence reviews
- End with decision: proceed, pivot, or stop

## Opportunity Solution Tree (Teresa Torres)

Structure:
- Outcome: metric you want to move
- Opportunities: unmet customer needs/pains
- Solutions: candidate interventions
- Experiments: fastest learning actions

Quality checks:
- At least 3 distinct opportunities before converging.
- At least 2 experiments per top opportunity.
- Tie every branch to evidence source.

## Assumption Mapping

Assumption categories:
- Desirability: users want this
- Viability: business value exists
- Feasibility: team can build/operate it
- Usability: users can successfully use it

Prioritization rule:
- High risk + low certainty assumptions are tested first.

## Problem Validation Techniques

- Problem interviews focused on current behavior
- Journey friction mapping
- Support ticket and sales-call synthesis
- Behavioral analytics triangulation

Evidence threshold examples:
- Same pain repeated across multiple target users
- Observable workaround behavior
- Measurable cost of current pain

## Solution Validation Techniques

- Concept tests (value proposition comprehension)
- Prototype usability tests (task success/time-to-complete)
- Fake door or concierge tests (demand signal)
- Limited beta cohorts (retention/activation signals)

## Discovery Sprint Planning

Suggested 10-day structure:
- Day 1-2: Outcome + opportunity framing
- Day 3-4: Assumption mapping + test design
- Day 5-7: Problem and solution tests
- Day 8-9: Evidence synthesis + decision options
- Day 10: Stakeholder decision review

## Tooling

### `scripts/assumption_mapper.py`

CLI utility that:
- reads assumptions from CSV or inline input
- scores risk/certainty priority
- emits prioritized test plan with suggested test types

See `references/discovery-frameworks.md` for framework details.

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: product-team. -->
','.claude\skills\product-discovery\SKILL.md','7a38f6fae269d9a03e250ded08cb7574c80cfeec6a450177832d00c30cc05404','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:product-launch-video','project_skill','skill://simplicio-runtime/product-launch-video','skill: product-launch-video','---
name: product-launch-video
description: "turn a product or marketing URL, pasted script, or brief into a product launch video, including SaaS promos, feature reveals, app launches, company promos, and product marketing videos. Use this skill when the user wants to market, launch, promote, or reveal a product. Do not use it for general non-launch website tours, non-product topic explainers, GitHub pull requests, captioning existing footage, or short unnarrated motion graphics. If the intent is unclear, route through /hyperframes first."
---

# Product Launch to HyperFrames

Use this skill to capture a product, understand its brand, plan a launch video, and build it frame by frame in HyperFrames.

> **Confirm the route before Step 0.** You are the orchestrator. Run each step, verify its gate, and only then continue to the next step. This skill is for a **product being marketed, launched, promoted, or revealed**, including requests such as "promo for our site" when the purpose is promotional. Route other intents elsewhere: a general non-launch website tour -> `/website-to-video`; a topic explainer with no product -> `/faceless-explainer`; a GitHub PR -> `/pr-to-video`; captions on existing footage -> `/embedded-captions`; a short unnarrated motion graphic -> `/motion-graphics`. If the user says only "make a video" or the route is uncertain, read `/hyperframes` first.

You are the orchestrator. Work in `videos/<project>/`. Run steps in order and pass each gate before continuing. User-gated steps are Step 0, Step 3, and Step 6. Do every step yourself except Step 5, where you dispatch one sub-agent per frame. Do not put design or motion rules here; those live in the frame-worker sub-agent, `hyperframes-creative`, and `hyperframes-animation`.

Workflow: Step 0 setup -> `hyperframes.json`; Step 1 capture -> `capture/`; Step 2 design system -> `frame.md`; Step 3 storyboard/script -> `STORYBOARD.md` and `SCRIPT.md`; Step 3.1 audio -> `audio_meta.json`; Step 4 visual design -> enriched `STORYBOARD.md`; Step 5 frames -> `compositions/frames/NN-*.html` and `index.html`; Step 6 final render -> `renders/video.mp4`.

---

## Step 0: Setup and Brief

Goal: Lock the core video brief and create the HyperFrames project if needed.

Initialize only if `hyperframes.json` is missing. Name `<project>` from the brand or domain in kebab-case, such as `acme-promo`; never use workspace name or timestamp.

`npx hyperframes init "videos/<project>" --non-interactive --skip-skills --example=blank`

**Gate:** `hyperframes.json` exists, and angle, length, aspect ratio, and language are locked.

---

## Step 1: Capture assets

Goal: Collect the source material, brand signals, and usable assets for the video.

Classify the input and choose the path. Explicit URL -> capture it and use the site for narration and assets. Pasted script/brief -> save verbatim as `user_script.txt`, ask once "use it verbatim or restructure?", store answer as `VO_MODE`, then resolve capture target: URL in text -> use it; brand name only -> `WebSearch`, confirm URL in one line, then crawl; no URL/site -> no-capture path.

Run capture with: `npx hyperframes capture "<URL>" -o ./capture`

If `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or an OpenRouter key exists, capture auto-captions assets into `capture/extracted/asset-descriptions.md`. This is not a review gate. Without a vision key, use DOM context and continue.

No-capture path: create `capture/extracted/tokens.json`, `capture/extracted/visible-text.txt`, `capture/extracted/asset-descriptions.md`, and `capture/assets/` by hand. `tokens.json` should be `{ "title": "", "description": "", "colors": [], "fonts": [] }`; fill title/description from the brief when possible. `visible-text.txt` contains the full brief or script. `asset-descriptions.md` should say no assets were captured unless the user gave asset notes.

**Gate:** `capture/extracted/tokens.json`, `capture/extracted/visible-text.txt`, `capture/extracted/asset-descriptions.md`, and `capture/assets/` exist; you can state the brand in one clear sentence. Treat `asset-descriptions','.claude\skills\product-launch-video\SKILL.md','efef0645d56ea2b2440c7238eae6fea9cbdbc525ed48d0a437f7d7a51e123a83','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:product-manager-toolkit','project_skill','skill://simplicio-runtime/product-manager-toolkit','skill: product-manager-toolkit','---
name: product-manager-toolkit
description: Comprehensive toolkit for product managers including RICE prioritization, customer interview analysis, PRD templates, discovery frameworks, and go-to-market strategies. Use when prioritizing features, synthesizing user research, writing requirement documentation, or developing product strategy.
---

# Product Manager Toolkit

Essential tools and frameworks for modern product management, from discovery to delivery.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Core Workflows](#core-workflows)
  - [Feature Prioritization](#feature-prioritization-process)
  - [Customer Discovery](#customer-discovery-process)
  - [PRD Development](#prd-development-process)
- [Tools Reference](#tools-reference)
  - [RICE Prioritizer](#rice-prioritizer)
  - [Customer Interview Analyzer](#customer-interview-analyzer)
- [Input/Output Examples](#inputoutput-examples)
- [Integration Points](#integration-points)
- [Common Pitfalls](#common-pitfalls-to-avoid)

---

## Quick Start

### For Feature Prioritization
```bash
# Create sample data file
python scripts/rice_prioritizer.py sample

# Run prioritization with team capacity
python scripts/rice_prioritizer.py sample_features.csv --capacity 15
```

### For Interview Analysis
```bash
python scripts/customer_interview_analyzer.py interview_transcript.txt
```

### For PRD Creation
1. Choose template from `references/prd_templates.md`
2. Fill sections based on discovery work
3. Review with engineering for feasibility
4. Version control in project management tool

---

## Core Workflows

### Feature Prioritization Process

```
Gather → Score → Analyze → Plan → Validate → Execute
```

#### Step 1: Gather Feature Requests
- Customer feedback (support tickets, interviews)
- Sales requests (CRM pipeline blockers)
- Technical debt (engineering input)
- Strategic initiatives (leadership goals)

#### Step 2: Score with RICE
```bash
# Input: CSV with features
python scripts/rice_prioritizer.py features.csv --capacity 20
```

See `references/frameworks.md` for RICE formula and scoring guidelines.

#### Step 3: Analyze Portfolio
Review the tool output for:
- Quick wins vs big bets distribution
- Effort concentration (avoid all XL projects)
- Strategic alignment gaps

#### Step 4: Generate Roadmap
- Quarterly capacity allocation
- Dependency identification
- Stakeholder communication plan

#### Step 5: Validate Results
**Before finalizing the roadmap:**
- [ ] Compare top priorities against strategic goals
- [ ] Run sensitivity analysis (what if estimates are wrong by 2x?)
- [ ] Review with key stakeholders for blind spots
- [ ] Check for missing dependencies between features
- [ ] Validate effort estimates with engineering

#### Step 6: Execute and Iterate
- Share roadmap with team
- Track actual vs estimated effort
- Revisit priorities quarterly
- Update RICE inputs based on learnings

---

### Customer Discovery Process

```
Plan → Recruit → Interview → Analyze → Synthesize → Validate
```

#### Step 1: Plan Research
- Define research questions
- Identify target segments
- Create interview script (see `references/frameworks.md`)

#### Step 2: Recruit Participants
- 5-8 interviews per segment
- Mix of power users and churned users
- Incentivize appropriately

#### Step 3: Conduct Interviews
- Use semi-structured format
- Focus on problems, not solutions
- Record with permission
- Take minimal notes during interview

#### Step 4: Analyze Insights
```bash
python scripts/customer_interview_analyzer.py transcript.txt
```

Extracts:
- Pain points with severity
- Feature requests with priority
- Jobs to be done patterns
- Sentiment and key themes
- Notable quotes

#### Step 5: Synthesize Findings
- Group similar pain points across interviews
- Identify patterns (3+ mentions = pattern)
- Map to opportunity areas using Opportunity Solution Tree
- Prioritize opportunities by frequency and severity

#### Step 6: Validate Solutions
**Before building:**
- [ ] Create solution hypotheses (see `references/frameworks.md`)
- [ ] Test with low-fidelity prototypes
- [ ] Me','.claude\skills\product-manager-toolkit\SKILL.md','74d6668a0c3fd207ec3f7b926956ac8a25b2b65aca2251fff3fb08127dabb753','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:product-marketing','project_skill','skill://simplicio-runtime/product-marketing','skill: product-marketing','---
name: product-marketing
description: "When the user wants to create or update their product marketing context document. Also use when the user mentions ''product context,'' ''marketing context,'' ''set up context,'' ''positioning,'' ''who is my target audience,'' ''describe my product,'' ''ICP,'' ''ideal customer profile,'' or wants to avoid repeating foundational information across marketing tasks. Use this at the start of any new project before using other marketing skills — it creates `.agents/product-marketing.md` that all other skills reference for product, audience, and positioning context."
metadata:
  version: 2.0.0
---

# Product Marketing Context

You help users create and maintain a product marketing context document. This captures foundational positioning and messaging information that other marketing skills reference, so users don''t repeat themselves.

The document is stored at `.agents/product-marketing.md`.

## Workflow

### Step 1: Check for Existing Context

First, check if `.agents/product-marketing.md` already exists. Also check `.claude/product-marketing.md` and the legacy filename `product-marketing-context.md` (in either `.agents/` or `.claude/`) for older setups — if found anywhere other than `.agents/product-marketing.md`, offer to move it to the canonical location.

**If it exists:**
- Read it and summarize what''s captured
- Ask which sections they want to update
- Only gather info for those sections

**If it doesn''t exist, offer two options:**

1. **Auto-draft from codebase** (recommended): You''ll study the repo—README, landing pages, marketing copy, package.json, etc.—and draft a V1 of the context document. The user then reviews, corrects, and fills gaps. This is faster than starting from scratch.

2. **Start from scratch**: Walk through each section conversationally, gathering info one section at a time.

Most users prefer option 1. After presenting the draft, ask: "What needs correcting? What''s missing?"

### Step 2: Gather Information

**If auto-drafting:**
1. Read the codebase: README, landing pages, marketing copy, about pages, meta descriptions, package.json, any existing docs
2. Draft all sections based on what you find
3. Present the draft and ask what needs correcting or is missing
4. Iterate until the user is satisfied

**If starting from scratch:**
Walk through each section below conversationally, one at a time. Don''t dump all questions at once.

For each section:
1. Briefly explain what you''re capturing
2. Ask relevant questions
3. Confirm accuracy
4. Move to the next

Push for verbatim customer language — exact phrases are more valuable than polished descriptions because they reflect how customers actually think and speak, which makes copy more resonant.

---

## Sections to Capture

### 1. Product Overview
- One-line description
- What it does (2-3 sentences)
- Product category (what "shelf" you sit on—how customers search for you)
- Product type (SaaS, marketplace, e-commerce, service, etc.)
- Business model and pricing

### 2. Target Audience
- Target company type (industry, size, stage)
- Target decision-makers (roles, departments)
- Primary use case (the main problem you solve)
- Jobs to be done (2-3 things customers "hire" you for)
- Specific use cases or scenarios

### 3. Personas (B2B only)
If multiple stakeholders are involved in buying, capture for each:
- User, Champion, Decision Maker, Financial Buyer, Technical Influencer
- What each cares about, their challenge, and the value you promise them

### 4. Problems & Pain Points
- Core challenge customers face before finding you
- Why current solutions fall short
- What it costs them (time, money, opportunities)
- Emotional tension (stress, fear, doubt)

### 5. Competitive Landscape
- **Direct competitors**: Same solution, same problem (e.g., Calendly vs SavvyCal)
- **Secondary competitors**: Different solution, same problem (e.g., Calendly vs Superhuman scheduling)
- **Indirect competitors**: Conflicting approach (e.g., Calendly vs personal assistant)
- How each falls short for customers

### 6. Differentiation
- Key differentiators (','.claude\skills\product-marketing\SKILL.md','d08a53862b9b7b12f97c595608730850852d4c10f646c3a3a060652d91289521','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:product-research','project_skill','skill://simplicio-runtime/product-research','skill: product-research','---
name: product-research
description: Use when planning and synthesizing product/user research as a method-and-repository discipline — selecting the right method for the goal (generative interviews vs usability test vs concept test vs validation), computing method-based saturation/sample size with an explicit confidence level, or synthesizing coded observations into insights while flagging single-source anecdotes. Never fabricates user insight; an insight requires recurrence across independent participants. Distinct from product-team/ux-researcher-designer (persona/journey artifacts), product-discovery (discovery-sprint planning), and experiment-designer (live A/B) — this is the research-ops method + insight-repository layer.
version: 2.9.0
author: claude-code-skills
license: MIT
tags: [research-ops, product-research, ux-research, jtbd, usability, saturation, insight-synthesis, research-repository]
compatible_tools: [claude-code, codex-cli, cursor, antigravity, opencode, gemini-cli]
---

# product-research

Product / user research as an operational discipline: choosing the right method, sizing it honestly, and synthesizing findings into governed insights. The core rule: **method must match the goal**, and **an insight requires recurrence across independent participants** — a single quote is an anecdote.

## Purpose

Product researchers, ResearchOps teams, and PMs running discovery need method rigor and an insight repository they can trust. This skill structures three decisions:

Three deterministic tools:

1. `study_designer.py` — Maps (research goal × product stage) to an appropriate method and emits a method-matched plan skeleton (objective, participant criteria, guide structure, success criteria). Redirects live A/B to `product-team/experiment-designer`.
2. `saturation_planner.py` — Method-based sample guidance with an explicit **confidence label**: Nielsen problem-discovery (5/segment), Guest et al. thematic saturation (~12), and evaluative coverage. Never claims a prevalence rate from a small-n usability test.
3. `insight_synthesizer.py` — Clusters coded observations by tag, counts distinct participants, ranks by cross-participant recurrence, and flags any candidate below the source threshold as an **ANECDOTE**, never promoting it to an insight.

## When to use

Invoke this skill when:

- You are planning a study and need the method to match the goal (generative vs evaluative vs validation).
- You need a defensible sample size / saturation rationale with a stated confidence.
- You have raw coded observations and need to synthesize insights without over-claiming.
- You are setting up or auditing a research repository and need the insight-vs-observation discipline.

**Do NOT use this skill to**: generate personas / journey maps (use `product-team/ux-researcher-designer`), plan a discovery sprint or validate an opportunity (use `product-team/product-discovery`), design or analyze a live product A/B experiment (use `product-team/experiment-designer`), or do market sizing / surveys (use the `market-research` sibling).

## Workflow

1. **Frame the study** — Fill `assets/research_plan_template.md` (research questions, method rationale, participant criteria, analysis plan, repository tagging scheme).
2. **Pick the method** — Run `study_designer.py --goal {discovery|evaluative|validation} --stage {concept|prototype|beta|live} --profile {b2b-saas|consumer-app|enterprise|marketplace|hardware|platform}`. Honor the redirect if it routes to experiment-designer.
3. **Size it** — Run `saturation_planner.py --method {usability|thematic|evaluative-coverage} --segments N`. Record the confidence label and limits.
4. **Synthesize** — After fielding, code observations and run `insight_synthesizer.py --input observations.json --min-sources 3`. Treat ANECDOTE-flagged clusters as signals to probe, not findings to ship.
5. **File in the repository** — Tag insights to the atomic schema at synthesis time, with their evidence and confidence.

## Scripts

| Script | Purpose | Profiles |
|---|---|---|
| `scripts/study_designer.py` | (goal × sta','.claude\skills\product-research\SKILL.md','2d0af6ac4895d3928c55b2b65ab77c3abe2767c1d643045f413486217e346800','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:product-skills','project_skill','skill://simplicio-runtime/product-skills','skill: product-skills','---
name: product-skills
description: "Router/index for the 12 product skills bundled in this plugin (RICE prioritization, OKRs, UX research, design tokens, competitive teardown, analytics, experiments, discovery, roadmaps, spec-to-repo, landing pages, SaaS scaffolding). Use when a product request doesn''t obviously match one skill and you need to pick the right one (e.g., ''help me prioritize features'', ''plan a product experiment'')."
version: 2.9.0
author: Alireza Rezvani
license: MIT
tags:
  - product
  - product-management
  - ux
  - ui
  - saas
  - agile
agents:
  - claude-code
  - codex-cli
  - openclaw
---

# Product Skills — Router

This plugin bundles **12 product skills** (this router is the 13th folder under `product-team/skills/`). Each skill is self-contained: read its `SKILL.md`, run its `scripts/`, apply its `references/` and `assets/`.

## Routing table

Match the request against the signals below, then load `product-team/skills/<skill>/SKILL.md`. If two or more rows match, ask the user one clarifying question before loading anything.

| Request signals | Skill | Path |
|---|---|---|
| Prioritize features, RICE scores, interview synthesis | product-manager-toolkit | `skills/product-manager-toolkit/` |
| OKRs, strategy cascade, objective alignment | product-strategist | `skills/product-strategist/` |
| Personas, usability findings, research synthesis | ux-researcher-designer | `skills/ux-researcher-designer/` |
| Design tokens, component specs, WCAG contrast | ui-design-system | `skills/ui-design-system/` |
| Competitor analysis, feature/pricing matrix | competitive-teardown | `skills/competitive-teardown/` |
| Retention, cohorts, funnel analysis | product-analytics | `skills/product-analytics/` |
| A/B test design, sample size, hypothesis gates | experiment-designer | `skills/experiment-designer/` |
| Opportunity trees, assumption mapping, discovery | product-discovery | `skills/product-discovery/` |
| Roadmap formats per audience, changelogs | roadmap-communicator | `skills/roadmap-communicator/` |
| Turn a written spec into a repo scaffold | spec-to-repo | `skills/spec-to-repo/` |
| Landing page (Next.js TSX + Tailwind) | landing-page-generator | `skills/landing-page-generator/` |
| Bootstrap a SaaS app skeleton | saas-scaffolder | `skills/saas-scaffolder/` |

## Quick start

```bash
# Example: route a prioritization request
cat product-team/skills/product-manager-toolkit/SKILL.md
python3 product-team/skills/product-manager-toolkit/scripts/rice_prioritizer.py --help
```

## Related product-team plugins (packaged separately, not in this bundle)

- `product-team/agile-product-owner/` — user stories, sprint capacity
- `product-team/code-to-prd/` — reverse-engineer a PRD from a codebase
- `product-team/apple-hig-expert/` — Apple HIG audits (Liquid Glass era)
- `product-team/research-summarizer/` — document summarization with citation extraction

## Rules

- Route to exactly one skill, then follow that skill''s own workflow.
- This router ships no tools of its own — if no row matches, say so and ask rather than improvising.

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: product-team. -->
','.claude\skills\product-skills\SKILL.md','2097d9635f197704d14c867eced82fdb461363ca50e022ae6a86e41680593afa','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:product-strategist','project_skill','skill://simplicio-runtime/product-strategist','skill: product-strategist','---
name: product-strategist
description: Strategic product leadership toolkit for Head of Product covering OKR cascade generation, quarterly planning, competitive landscape analysis, product vision documents, and team scaling proposals. Use when creating quarterly OKR documents, defining product goals or KPIs, building product roadmaps, running competitive analysis, drafting team structure or hiring plans, aligning product strategy across engineering and design, or generating cascaded goal hierarchies from company to team level.
---

# Product Strategist

Strategic toolkit for Head of Product to drive vision, alignment, and organizational excellence.

---

## Core Capabilities

| Capability | Description | Tool |
|------------|-------------|------|
| **OKR Cascade** | Generate aligned OKRs from company to team level | `okr_cascade_generator.py` |
| **Alignment Scoring** | Measure vertical and horizontal alignment | Built into generator |
| **Strategy Templates** | 5 pre-built strategy types | Growth, Retention, Revenue, Innovation, Operational |
| **Team Configuration** | Customize for your org structure | `--teams` flag |

---

## Quick Start

```bash
# Growth strategy with default teams
python scripts/okr_cascade_generator.py growth

# Retention strategy with custom teams
python scripts/okr_cascade_generator.py retention --teams "Engineering,Design,Data"

# Revenue strategy with 40% product contribution
python scripts/okr_cascade_generator.py revenue --contribution 0.4

# Export as JSON for integration
python scripts/okr_cascade_generator.py growth --json > okrs.json
```

---

## Workflow: Quarterly Strategic Planning

### Step 1: Define Strategic Focus

| Strategy | When to Use |
|----------|-------------|
| **Growth** | Scaling user base, market expansion |
| **Retention** | Reducing churn, improving LTV |
| **Revenue** | Increasing ARPU, new monetization |
| **Innovation** | Market differentiation, new capabilities |
| **Operational** | Improving efficiency, scaling operations |

See `references/strategy_types.md` for detailed guidance.

### Step 2: Gather Input Metrics

```json
{
  "current": 100000,      // Current MAU
  "target": 150000,       // Target MAU
  "current_nps": 40,      // Current NPS
  "target_nps": 60        // Target NPS
}
```

### Step 3: Configure Teams & Run Generator

```bash
# Default teams
python scripts/okr_cascade_generator.py growth

# Custom org structure with contribution percentage
python scripts/okr_cascade_generator.py growth \
  --teams "Core,Platform,Mobile,AI" \
  --contribution 0.3
```

### Step 4: Review Alignment Scores

| Score | Target | Action if Below |
|-------|--------|-----------------|
| Vertical Alignment | >90% | Ensure all objectives link to parent |
| Horizontal Alignment | >75% | Check for team coordination gaps |
| Coverage | >80% | Validate all company OKRs are addressed |
| Balance | >80% | Redistribute if one team is overloaded |
| **Overall** | **>80%** | <60% needs restructuring |

### Step 5: Refine, Validate, and Export

Before finalizing:

- [ ] Review generated objectives with stakeholders
- [ ] Adjust team assignments based on capacity
- [ ] Validate contribution percentages are realistic
- [ ] Ensure no conflicting objectives across teams
- [ ] Set up tracking cadence (bi-weekly check-ins)

```bash
# Export JSON for tools like Lattice, Ally, Workboard
python scripts/okr_cascade_generator.py growth --json > q1_okrs.json
```

---

## OKR Cascade Generator

### Usage

```bash
python scripts/okr_cascade_generator.py [strategy] [options]
```

**Strategies:** `growth` | `retention` | `revenue` | `innovation` | `operational`

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `--teams`, `-t` | Comma-separated team names | Growth,Platform,Mobile,Data |
| `--contribution`, `-c` | Product contribution to company OKRs (0-1) | 0.3 (30%) |
| `--json`, `-j` | Output as JSON instead of dashboard | False |
| `--metrics`, `-m` | Metrics as JSON string | Sample metrics |

### Output Examples

#### Dashboard Output (`growth','.claude\skills\product-strategist\SKILL.md','11f445dcb38f484359fa1e29d87b79f6f824ac168ca51a740ff414cd125607c9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:programmatic-seo','project_skill','skill://simplicio-runtime/programmatic-seo','skill: programmatic-seo','---
name: programmatic-seo
description: When the user wants to create SEO-driven pages at scale using templates and data. Also use when the user mentions "programmatic SEO," "template pages," "pages at scale," "directory pages," "location pages," "[keyword] + [city] pages," "comparison pages," "integration pages," "building many pages for SEO," "pSEO," "generate 100 pages," "data-driven pages," or "templated landing pages." Use this whenever someone wants to create many similar pages targeting different keywords or locations. For auditing existing SEO issues, see seo-audit. For content strategy planning, see content-strategy.
metadata:
  version: 2.0.0
---

# Programmatic SEO

You are an expert in programmatic SEO—building SEO-optimized pages at scale using templates and data. Your goal is to create pages that rank, provide value, and avoid thin content penalties.

## Initial Assessment

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Before designing a programmatic SEO strategy, understand:

1. **Business Context**
   - What''s the product/service?
   - Who is the target audience?
   - What''s the conversion goal for these pages?

2. **Opportunity Assessment**
   - What search patterns exist?
   - How many potential pages?
   - What''s the search volume distribution?

3. **Competitive Landscape**
   - Who ranks for these terms now?
   - What do their pages look like?
   - Can you realistically compete?

---

## Core Principles

### 1. Unique Value Per Page
- Every page must provide value specific to that page
- Not just swapped variables in a template
- Maximize unique content—the more differentiated, the better

### 2. Proprietary Data Wins
Hierarchy of data defensibility:
1. Proprietary (you created it)
2. Product-derived (from your users)
3. User-generated (your community)
4. Licensed (exclusive access)
5. Public (anyone can use—weakest)

### 3. Clean URL Structure
**Use subfolders, not subdomains** — subfolders consolidate domain authority while subdomains split it:
- Good: `yoursite.com/templates/resume/`
- Bad: `templates.yoursite.com/resume/`

### 4. Genuine Search Intent Match
Pages must actually answer what people are searching for.

### 5. Quality Over Quantity
Better to have 100 great pages than 10,000 thin ones.

### 6. Avoid Google Penalties
- No doorway pages
- No keyword stuffing
- No duplicate content
- Genuine utility for users

---

## The 12 Playbooks (Overview)

| Playbook | Pattern | Example |
|----------|---------|---------|
| Templates | "[Type] template" | "resume template" |
| Curation | "best [category]" | "best website builders" |
| Conversions | "[X] to [Y]" | "$10 USD to GBP" |
| Comparisons | "[X] vs [Y]" | "webflow vs wordpress" |
| Examples | "[type] examples" | "landing page examples" |
| Locations | "[service] in [location]" | "dentists in austin" |
| Personas | "[product] for [audience]" | "crm for real estate" |
| Integrations | "[product A] [product B] integration" | "slack asana integration" |
| Glossary | "what is [term]" | "what is pSEO" |
| Translations | Content in multiple languages | Localized content |
| Directory | "[category] tools" | "ai copywriting tools" |
| Profiles | "[entity name]" | "stripe ceo" |

**For detailed playbook implementation**: See [references/playbooks.md](references/playbooks.md)

---

## Choosing Your Playbook

| If you have... | Consider... |
|----------------|-------------|
| Proprietary data | Directories, Profiles |
| Product with integrations | Integrations |
| Design/creative product | Templates, Examples |
| Multi-segment audience | Personas |
| Local presence | Locations |
| Tool or utility product | Conversions |
| Content/expertise | Glossary, Curation |
| Competitor landscape | Comparisons |

You can layer multiple playbooks (e.g., "Best coworking spaces in San Diego").

---','.claude\skills\programmatic-seo\SKILL.md','e522c2f376228b725046c878b1bf4acdf72df81c97f52a39b74cc144428a2130','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:promote','project_skill','skill://simplicio-runtime/promote','skill: promote','---
name: promote
description: "Graduate a proven pattern from auto-memory (MEMORY.md) to CLAUDE.md or .claude/rules/ for permanent enforcement. Use when the user runs /si:promote or asks to make a learned behavior permanent."
---

# /si:promote — Graduate Learnings to Rules

Moves a proven pattern from Claude''s auto-memory into the project''s rule system, where it becomes an enforced instruction rather than a background note.

## Usage

```
/si:promote <pattern description>                    # Auto-detect best target
/si:promote <pattern> --target claude.md             # Promote to CLAUDE.md
/si:promote <pattern> --target rules/testing.md      # Promote to scoped rule
/si:promote <pattern> --target rules/api.md --paths "src/api/**/*.ts"  # Scoped with paths
```

## Workflow

### Step 1: Understand the pattern

Parse the user''s description. If vague, ask one clarifying question:
- "What specific behavior should Claude follow?"
- "Does this apply to all files or specific paths?"

### Step 2: Find the pattern in auto-memory

```bash
# Search MEMORY.md for related entries
MEMORY_DIR="$HOME/.claude/projects/$(pwd | sed ''s|/|%2F|g; s|%2F|/|; s|^/||'')/memory"
grep -ni "<keywords>" "$MEMORY_DIR/MEMORY.md"
```

Show the matching entries and confirm they''re what the user means.

### Step 3: Determine the right target

| Pattern scope | Target | Example |
|---|---|---|
| Applies to entire project | `./CLAUDE.md` | "Use pnpm, not npm" |
| Applies to specific file types | `.claude/rules/<topic>.md` | "API handlers need validation" |
| Applies to all your projects | `~/.claude/CLAUDE.md` | "Prefer explicit error handling" |

If the user didn''t specify a target, recommend one based on scope.

### Step 4: Distill into a concise rule

Transform the learning from auto-memory''s note format into CLAUDE.md''s instruction format:

**Before** (MEMORY.md — descriptive):
> The project uses pnpm workspaces. When I tried npm install it failed. The lock file is pnpm-lock.yaml. Must use pnpm install for dependencies.

**After** (CLAUDE.md — prescriptive):
```markdown
## Build & Dependencies
- Package manager: pnpm (not npm). Use `pnpm install`.
```

**Rules for distillation:**
- One line per rule when possible
- Imperative voice ("Use X", "Always Y", "Never Z")
- Include the command or example, not just the concept
- No backstory — just the instruction

### Step 5: Write to target

**For CLAUDE.md:**
1. Read existing CLAUDE.md
2. Find the appropriate section (or create one)
3. Append the new rule under the right heading
4. If file would exceed 200 lines, suggest using `.claude/rules/` instead

**For `.claude/rules/`:**
1. Create the file if it doesn''t exist
2. Add YAML frontmatter with `paths` if scoped
3. Write the rule content

```markdown
---
paths:
  - "src/api/**/*.ts"
  - "tests/api/**/*"
---

# API Development Rules

- All endpoints must validate input with Zod schemas
- Use `ApiError` class for error responses (not raw Error)
- Include OpenAPI JSDoc comments on handler functions
```

### Step 6: Clean up auto-memory

After promoting, remove or mark the original entry in MEMORY.md:

```bash
# Show what will be removed
grep -n "<pattern>" "$MEMORY_DIR/MEMORY.md"
```

Ask the user to confirm removal. Then edit MEMORY.md to remove the promoted entry. This frees space for new learnings.

### Step 7: Confirm

```
✅ Promoted to {{target}}

Rule: "{{distilled rule}}"
Source: MEMORY.md line {{n}} (removed)
MEMORY.md: {{lines}}/200 lines remaining

The pattern is now an enforced instruction. Claude will follow it in all future sessions.
```

## Promotion Decision Guide

### Promote when:
- Pattern appeared 3+ times in auto-memory
- You corrected Claude about it more than once
- It''s a project convention that any contributor should know
- It prevents a recurring mistake

### Don''t promote when:
- It''s a one-time debugging note (leave in auto-memory)
- It''s session-specific context (session memory handles this)
- It might change soon (e.g., during a migration)
- It''s already covered by existing rules

### CLAUDE.md vs .claude/rules/

| Use CLAUDE.md for','.claude\skills\promote\SKILL.md','8fb3f77d98b30546208998cd372aada108a3fe3e972748e2760924ce23d9551e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:prompt-governance','project_skill','skill://simplicio-runtime/prompt-governance','skill: prompt-governance','---
name: prompt-governance
description: "Use when managing prompts in production at scale: versioning prompts, running A/B tests on prompts, building prompt registries, preventing prompt regressions, or creating eval pipelines for production AI features. Triggers: ''manage prompts in production'', ''prompt versioning'', ''prompt regression'', ''prompt A/B test'', ''prompt registry'', ''eval pipeline''. NOT for writing or improving individual prompts (use senior-prompt-engineer). NOT for RAG pipeline design (use rag-architect). NOT for LLM cost reduction (use llm-cost-optimizer)."
---

# Prompt Governance

> Originally contributed by [chad848](https://github.com/chad848) — enhanced and integrated by the claude-skills team.

You are an expert in production prompt engineering and AI feature governance. Your goal is to treat prompts as first-class infrastructure -- versioned, tested, evaluated, and deployed with the same rigor as application code. You prevent quality regressions, enable safe iteration, and give teams confidence that prompt changes will not break production.

Prompts are code. They change behavior in production. Ship them like code.

## Before Starting

**Check for context first:** If project-context.md exists, read it before asking questions. Pull the AI tech stack, deployment patterns, and any existing prompt management approach.

Gather this context (ask in one shot):

### 1. Current State
- How are prompts currently stored? (hardcoded in code, config files, database, prompt management tool?)
- How many distinct prompts are in production?
- Has a prompt change ever caused a quality regression you did not catch before users reported it?

### 2. Goals
- What is the primary pain? (versioning chaos, no evals, blind A/B testing, slow iteration?)
- Team size and prompt ownership model? (one engineer owns all prompts vs. many contributors?)
- Tooling constraints? (open-source only, existing CI/CD, cloud provider?)

### 3. AI Stack
- LLM provider(s) in use?
- Frameworks in use? (LangChain, LlamaIndex, custom, direct API?)
- Existing test/CI infrastructure?

## How This Skill Works

### Mode 1: Build Prompt Registry
No centralized prompt management today. Design and implement a prompt registry with versioning, environment promotion, and audit trail.

### Mode 2: Build Eval Pipeline
Prompts are stored somewhere but there is no systematic quality testing. Build an evaluation pipeline that catches regressions before production.

### Mode 3: Governed Iteration
Registry and evals exist. Design the full governance workflow: branch, test, eval, review, promote -- with rollback capability.

---

## Mode 1: Build Prompt Registry

**What a prompt registry provides:**
- Single source of truth for all prompts
- Version history with rollback
- Environment promotion (dev to staging to prod)
- Audit trail (who changed what, when, why)
- Variable/template management

### Minimum Viable Registry (File-Based)

For small teams: structured files in version control.

Directory layout:
```
prompts/
  registry.yaml          # Index of all prompts
  summarizer/
    v1.0.0.md            # Prompt content
    v1.1.0.md
  classifier/
    v1.0.0.md
  qa-bot/
    v2.1.0.md
```

Registry YAML schema:
```yaml
prompts:
  - id: summarizer
    description: "Summarize support tickets for agent triage"
    owner: platform-team
    model: claude-sonnet-4-5
    versions:
      - version: 1.1.0
        file: summarizer/v1.1.0.md
        status: production
        promoted_at: 2026-03-15
        promoted_by: eng@company.com
      - version: 1.0.0
        file: summarizer/v1.0.0.md
        status: archived
```

### Production Registry (Database-Backed)

For larger teams: API-accessible prompt registry with key tables for prompts and prompt_versions tracking slug, content, model, environment, eval_score, and promotion metadata.

To initialize a file-based registry, create the directory structure above and populate the registry YAML with your existing prompts, their current versions, and ownership metadata.

---

## Mode 2: Build Eval Pipeline

**The problem:** Prompt ','.claude\skills\prompt-governance\SKILL.md','bfcba4946057d53319f6a170ca47637d8bfd4f3a4697cf54e840202529d0b26b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:property-based-testing','project_skill','skill://simplicio-runtime/property-based-testing','skill: property-based-testing','---
name: property-based-testing
description: Provides guidance for property-based testing across multiple languages and smart contracts. Use when writing tests, reviewing code with serialization/validation/parsing patterns, designing features, or when property-based testing would provide stronger coverage than example-based tests.
---

# Property-Based Testing Guide

Use this skill proactively during development when you encounter patterns where PBT provides stronger coverage than example-based tests.

## When to Invoke (Automatic Detection)

**Invoke this skill when you detect:**

- **Serialization pairs**: `encode`/`decode`, `serialize`/`deserialize`, `toJSON`/`fromJSON`, `pack`/`unpack`
- **Parsers**: URL parsing, config parsing, protocol parsing, string-to-structured-data
- **Normalization**: `normalize`, `sanitize`, `clean`, `canonicalize`, `format`
- **Validators**: `is_valid`, `validate`, `check_*` (especially with normalizers)
- **Data structures**: Custom collections with `add`/`remove`/`get` operations
- **Mathematical/algorithmic**: Pure functions, sorting, ordering, comparators
- **Smart contracts**: Solidity/Vyper contracts, token operations, state invariants, access control

**Priority by pattern:**

| Pattern | Property | Priority |
|---------|----------|----------|
| encode/decode pair | Roundtrip | HIGH |
| Pure function | Multiple | HIGH |
| Validator | Valid after normalize | MEDIUM |
| Sorting/ordering | Idempotence + ordering | MEDIUM |
| Normalization | Idempotence | MEDIUM |
| Builder/factory | Output invariants | LOW |
| Smart contract | State invariants | HIGH |

## When NOT to Use

Do NOT use this skill for:
- Simple CRUD operations without transformation logic
- One-off scripts or throwaway code
- Code with side effects that cannot be isolated (network calls, database writes)
- Tests where specific example cases are sufficient and edge cases are well-understood
- Integration or end-to-end testing (PBT is best for unit/component testing)

## Property Catalog (Quick Reference)

| Property | Formula | When to Use |
|----------|---------|-------------|
| **Roundtrip** | `decode(encode(x)) == x` | Serialization, conversion pairs |
| **Idempotence** | `f(f(x)) == f(x)` | Normalization, formatting, sorting |
| **Invariant** | Property holds before/after | Any transformation |
| **Commutativity** | `f(a, b) == f(b, a)` | Binary/set operations |
| **Associativity** | `f(f(a,b), c) == f(a, f(b,c))` | Combining operations |
| **Identity** | `f(x, identity) == x` | Operations with neutral element |
| **Inverse** | `f(g(x)) == x` | encrypt/decrypt, compress/decompress |
| **Oracle** | `new_impl(x) == reference(x)` | Optimization, refactoring |
| **Easy to Verify** | `is_sorted(sort(x))` | Complex algorithms |
| **No Exception** | No crash on valid input | Baseline property |

**Strength hierarchy** (weakest to strongest):
No Exception → Type Preservation → Invariant → Idempotence → Roundtrip

## Decision Tree

Based on the current task, read the appropriate section:

```
TASK: Writing new tests
  → Read [{baseDir}/references/generating.md]({baseDir}/references/generating.md) (test generation patterns and examples)
  → Then [{baseDir}/references/strategies.md]({baseDir}/references/strategies.md) if input generation is complex

TASK: Designing a new feature
  → Read [{baseDir}/references/design.md]({baseDir}/references/design.md) (Property-Driven Development approach)

TASK: Code is difficult to test (mixed I/O, missing inverses)
  → Read [{baseDir}/references/refactoring.md]({baseDir}/references/refactoring.md) (refactoring patterns for testability)

TASK: Reviewing existing PBT tests
  → Read [{baseDir}/references/reviewing.md]({baseDir}/references/reviewing.md) (quality checklist and anti-patterns)

TASK: Test failed, need to interpret
  → Read [{baseDir}/references/interpreting-failures.md]({baseDir}/references/interpreting-failures.md) (failure analysis and bug classification)

TASK: Need library reference
  → Read [{baseDir}/references/libraries.md]({baseDir}/references/libraries.md) (PBT libraries by ','.claude\skills\property-based-testing\SKILL.md','602451834a05a8299aea1f4b5d460aab004307fbf281f38fd05aa38a0e7fb420','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:prospecting','project_skill','skill://simplicio-runtime/prospecting','skill: prospecting','---
name: prospecting
description: When the user wants to find, qualify, and build a list of prospects to reach out to — across B2B SaaS, general B2B, or local small businesses. Also use when the user mentions "prospecting," "build a prospect list," "find prospects," "find leads," "lead gen list," "find SaaS companies that," "find B2B companies," "find local businesses," "ICP-fit accounts," "who should we go after," "outbound list," "target account list," "find clients near me," "businesses without websites," "prospect research," or "qualified leads." Use this for the list-building and qualification phase. For writing the outbound copy after the list is built, see cold-email. For deep competitive research on specific accounts, see competitor-profiling.
metadata:
  version: 1.0.0
---

# Prospecting

You are an expert at building qualified prospect lists across three motions: B2B SaaS, general B2B, and local small businesses. Your goal is to turn an ICP definition into a verified, scored, ready-to-outreach lead sheet — using the right data sources, qualification signals, and compliance posture for each motion.

## Before Starting

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

## Pick the Branch

Prospecting motions differ enough that the workflow forks at intake. Pick **one** branch based on who the user is selling to:

| Branch | Sell to | What "qualified" looks like | Primary sources |
|--------|---------|----------------------------|----------------|
| **SaaS** | Other SaaS companies / digital businesses | ICP fit + tech stack match + growth signals (funding, hiring, product velocity) | LinkedIn, BuiltWith, Crunchbase, Apollo, Clay, Clearbit, ProductHunt |
| **B2B** | Non-SaaS B2B (services, manufacturers, enterprises, mid-market) | Industry + size + geographic fit + buying signals (trigger events, vendor changes) | Apollo, ZoomInfo, Clay, Clearbit, LinkedIn Sales Nav, industry directories |
| **Local SMB** | Local small businesses (shops, gyms, restaurants, clinics, salons, services) | Active business + website status + proximity + decision-maker access | Google Maps, Yelp, local directories, Facebook, business websites |

If the user describes a hybrid motion (e.g., "SMBs that are also SaaS"), pick the dominant branch and pull in qualification signals from the other.

For the branch-specific deep dives:
- **SaaS** → see [references/saas-prospecting.md](references/saas-prospecting.md)
- **B2B** → see [references/b2b-prospecting.md](references/b2b-prospecting.md)
- **Local SMB** → see [references/local-prospecting.md](references/local-prospecting.md)

---

## Shared Framework (all branches)

Every prospecting engagement follows the same five phases. Tools and qualification signals change per branch; the phases don''t.

### Phase 1 — Define the ICP

Pull from `product-marketing.md` if available. Otherwise, gather:

1. **Firmographic fit** — industry, company size, revenue band, geography, business model
2. **Technographic fit** (SaaS branch) — what tools they already use, what they''re missing
3. **Buying signal** — why now? (trigger event, funding, hiring, new initiative, dissatisfaction with current vendor, recent move/expansion)
4. **Decision-maker profile** — role, seniority, what they care about
5. **Disqualifiers** — what makes a prospect a clear "skip"

Output the ICP as a one-paragraph statement plus a checklist of pass/fail criteria. Don''t move to discovery without this.

### Phase 2 — Build the candidate list (discovery)

Source 2–3× more candidates than the user wants in the final list — qualification will cull aggressively.

- **SaaS / B2B**: combine 2–3 sources for cross-verification. Apollo or ZoomInfo for firmographics; Clearbit or Clay for enrichment; LinkedIn Sales Nav for decision-maker mapping.
- **Local SMB**: browser-assisted rese','.claude\skills\prospecting\SKILL.md','dd0dc6c74df7ad27d08cbc79f4051ddf8ccabb840f847ac997b86968c3029934','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:psychology-of-marketing','project_skill','skill://simplicio-runtime/psychology-of-marketing','skill: psychology-of-marketing','---
name: psychology-of-marketing
description: Use to apply ethical persuasion principles to product, copy, and conversion — why people act, framed as cognitive biases and motivation, used honestly (never dark patterns). Trigger on "increase conversion", "why aren''t users signing up", "pricing/landing strategy", "psicologia de marketing", "persuasão", or any decision about getting a user to take a desired action.
source: methodology skill (sujeitoprogramador.com 2026 list — Psychology of Marketing); Simplicio-native, no external dependency
metadata:
  simplicio:
    guardians: [Helo, Levi]
    tags: [skill, simplicio, marketing, psychology, conversion, persuasion, ethics, content]
---

# Psychology of marketing — ethical persuasion

Why people act, applied to copy, pricing, and flows. **Ethical use only** — these
principles inform honest framing, never manipulation. Pairs with `copywriting`
(the words) and `ui-ux` (the flow).

## Principles (Cialdini + behavioral econ)

1. **Reciprocity.** Give real value first (free tier, useful content); people
   return value. Don''t gate everything behind signup.
2. **Social proof.** Show that others use/trust it — counts, logos, testimonials,
   reviews. Must be true and specific.
3. **Authority.** Credentials, expertise, results build trust. Demonstrate, don''t
   claim.
4. **Scarcity / urgency.** Genuine limits motivate action (real stock, real
   deadline). **Fake urgency is a dark pattern — forbidden.**
5. **Commitment & consistency.** Small first step (one-field signup) → larger
   commitment. Progress indicators leverage the desire to finish.
6. **Liking.** Relatable voice, shared values, human tone build affinity.
7. **Loss aversion.** People fear losing more than they value gaining. Frame around
   what they keep/avoid losing — honestly.
8. **Anchoring.** The first number sets the reference. Present plans so the target
   tier reads as the obvious value (no deception).

## Conversion method

1. Name the **one action** and the **objection** blocking it.
2. Pick the principle that *honestly* addresses that objection (trust → social
   proof/authority; risk → reciprocity/guarantee; inertia → small commitment).
3. Reduce friction (`ui-ux`) and clarify benefit (`copywriting`).
4. Make the value obvious *before* the ask.
5. Measure; iterate on the real funnel, not assumptions.

## Ethics line (hard rule)

No fake scarcity, no forced continuity, no confirmshaming, no hidden costs, no
roach-motel cancellation. Persuasion makes a *true* value obvious; manipulation
extracts an action against the user''s interest. Simplicio ships the first, never
the second. When a tactic would only work because the user is confused, it''s a
dark pattern — drop it.

## Simplicio flow

Recall positioning with `simplicio memory "value prop"`; decide the framing; apply
copy via `simplicio edit`; pair with `copywriting`/`ui-ux`. Levi guards the ethics
line on outward-facing claims.

## When NOT to use

Internal tooling with no conversion goal, or anything that would require deceiving
the user to "work".
','.claude\skills\psychology-of-marketing\SKILL.md','adf0934e61fe0615f43c8d82237701500910fc12e28eca122ae39e099883a555','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:public-relations','project_skill','skill://simplicio-runtime/public-relations','skill: public-relations','---
name: public-relations
description: "When the user wants help with public relations, earned media, press coverage, journalist outreach, or media strategy (not pull requests). Also use when the user mentions ''PR,'' ''public relations,'' ''press,'' ''press release,'' ''press coverage,'' ''media outreach,'' ''pitch a journalist,'' ''get featured,'' ''media list,'' ''media kit,'' ''press kit,'' ''newsjacking,'' ''news hijack,'' ''HARO,'' ''Qwoted,'' ''Featured,'' ''Help A Reporter,'' ''reporter request,'' ''tech press,'' ''TechCrunch,'' ''earned media,'' ''thought leadership placement,'' ''op-ed,'' ''guest article,'' ''press contacts,'' or ''how do I get press.'' Use this for earned media work — finding journalists, pitching stories, newsjacking, and responding to press requests. For startup/SaaS/AI directory submissions, see directory-submissions. For product launches, see launch. For social-media engagement, see social. For cold-email outreach to prospects, see cold-email."
metadata:
  version: 1.0.0
---

# Public Relations & Earned Media

You are an expert in earned media for software products. Your goal is to help the user get covered by journalists, podcasts, and newsletters — efficiently, with respect for the people on the other end of the pitch.

## Before Starting

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

---

## Core Philosophy

PR is not a substitute for distribution. It''s a multiplier for it.

- **Earned media doesn''t drive direct conversions.** A TechCrunch hit will not give you 1,000 paying customers. It will give you backlinks, brand legitimacy, AI-citation surface area, and ammo for sales conversations.
- **Pitch journalists like you''d pitch a customer:** specific, useful, fast, and never about you.
- **The story is not your product. The story is the trend, the data, the conflict, or the human.** Your product is the evidence.
- **Speed beats polish on reactive PR.** A B+ pitch in the first hour of a story beats an A+ pitch on day three.

### When PR is worth it

- You have **a real story** — proprietary data, a strong opinion, a milestone, a customer with a sharp before/after, or a fresh angle on a trending topic
- You have **founder/exec time** — journalists want quotes from people with skin in the game, not from a PR rep
- You have **a destination** — a press page, blog post, or product launch that converts attention into something useful

### When to skip PR (for now)

- Pre-launch with no story beyond "we exist"
- No one on the team can sustain pitching for 4–6 weeks (PR is a momentum game)
- You don''t have a clear ICP — journalists ask "who reads my piece because of this?" and if you can''t answer, neither can they

---

## The PR Mix

Four modes. Most teams over-index on one. Run at least three.

| Mode | What it is | Effort | Speed to coverage |
|------|------------|--------|-------------------|
| **Reactive (newsjacking)** | Inject your POV into trending news | Low–medium | Hours to days |
| **Proactive (pitching)** | Build a media list, pitch original stories | High | 2–8 weeks |
| **Inbound (press requests)** | Respond to journalist queries on HARO/Qwoted/Featured | Low | Days to weeks |
| **Owned (press page + media kit)** | Make it easy for journalists to find you | One-time setup | N/A |

**For the reactive newsjacking workflow** — see [references/newsjacking.md](references/newsjacking.md)

**For proactive journalist pitching** — see [references/journalist-pitching.md](references/journalist-pitching.md)

**For inbound press-request platforms (HARO, Qwoted, etc.)** — see [references/press-platforms.md](references/press-platforms.md)

**For where to pitch (media outlets, podcasts, newsletters)** — see [references/media-outlets.md](references/media-outlets.md). For startup/SaaS/AI directories, use the separate `directory-submissions` skill — different intent, different l','.claude\skills\public-relations\SKILL.md','ef9ab1ea2ca4366d871a7268026be2556fc8a79622eea290d3ea1ecdedc3dbbe','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pulse','project_skill','skill://simplicio-runtime/pulse','skill: pulse','---
name: pulse
description: "Multi-source recency research skill that takes the pulse of any topic across Reddit, Hacker News, the open web, and optionally X/Twitter within a configurable recent window (default 30 days). Forcing intake clarifies topic specificity, angle (trend/sentiment/problems/opportunities/comparison), time window, and platform scope before searching. Returns a synthesized briefing with citations, engagement metrics, and cross-platform pattern analysis. Use when the user requests multi-source recency intelligence on a topic (e.g., ''pulse on [topic]'', ''what''s happening with [topic]'', ''what are people saying about [topic]'', ''current conversation about [topic]'', ''take the pulse of [topic]'', ''trending: [topic]'', ''find me info on [topic]''), and for competitor research, trend discovery, tool comparisons, and audience sentiment analysis."
license: MIT
metadata:
  source_spec: "megaprompts/01-pulse-megaprompt.md"
  build_pattern: "Path B (direct conversion)"
  research_pack_convention: "Agent Integrity Rules block preserved verbatim per PR #657 audit"
  version: 1.0.0
---

# Pulse — Multi-Source Recency Research

> **Portability:** Works in both Claude Code CLI and Claude.ai. The optional X/Twitter phase requires browser automation and is skipped automatically if unavailable.

A recency-oriented research skill that synthesizes what people are saying about a topic across Reddit, Hacker News, the open web, and (optionally) X/Twitter — within a configurable time window. Output is a single coherent briefing with citations, engagement signals, and cross-platform pattern analysis. The skill captures the **current conversation**, not the canonical reference.

## Invocation

**Explicit trigger phrases:**
- "pulse on [topic]"
- "what''s happening with [topic]"
- "what are people saying about [topic]"
- "current conversation about [topic]"
- "take the pulse of [topic]"
- "trending: [topic]"
- "find me info on [topic]"

Also covers: competitor research with recency flavor, trend discovery, tool comparisons, audience sentiment analysis.

## Agent Integrity Rules (Research-Pack Convention)

The following rules apply throughout the run. They are inherited from the research-pack convention and locked down by PR #657''s cross-skill consistency audit.

- **Execution discipline.** Phases 1–3 run in parallel (Reddit + HN + Web are independent). Within each phase, sequential calls only. **1 q/sec rate limit per platform.** Confirm response received before next call within the same phase.
- **Source discipline.** Cite only sources returned by **this session''s tool calls.** Training knowledge is labeled `[Background — not from search]` and excluded from primary findings count.
- **Three-count tracking.** Queries sent / sources received (shown) / sources cited. Surfaced in the audit log inline in the synthesis section. Use `scripts/citation_tracker.py` for the deterministic count.
- **Retry policy.** On failure → wait 3s → retry once → log. After **3 consecutive failures across all sources:** stop, alert user, share what was collected. Never deliver an empty file.
- **Plan-tier detection.** Reddit + HN are unauthenticated public JSON APIs (rate-limited per IP, not per plan). Surface rate-limit signals from response headers when available; degrade gracefully otherwise.

See `references/research_pack_conventions.md` for the canon and `references/parallel_execution_discipline.md` for the rate-limit rationale.

## Phase 0: Grill-Me Intake (2–4 forcing questions, one at a time)

Dependency-ordered. Each question carries explicit "why I''m asking". Stop condition: max 4.

### Q1 (root) — Topic Specificity

> **What''s the topic? State it in 1–2 sentences — be specific. "AI" or "tech" will get you a vague survey; "self-hosted LLM deployment for small teams" or "Claude Code adoption among enterprise engineering orgs" will get you a useful answer.**
>
> *Why I''m asking:* Specificity dictates search quality. Vague topics produce vague briefings. If your topic is broad, I''d rather narrow it now than spend a search budget on noise.

**Refuse mush','.claude\skills\pulse\SKILL.md','84dc14fcac66898a18ad2be01950f9bde42c9595a3f9c3fe941dc09baddc0f36','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pw','project_skill','skill://simplicio-runtime/pw','skill: pw','---
name: pw
description: "Production-grade Playwright testing toolkit. Use when the user mentions Playwright tests, end-to-end testing, browser automation, fixing flaky tests, test migration, CI/CD testing, or test suites. Generate tests, fix flaky failures, migrate from Cypress/Selenium, sync with TestRail, run on BrowserStack. 55 templates, 3 agents, smart reporting."
---

# Playwright Pro

Production-grade Playwright testing toolkit for AI coding agents.

## Available Commands

When installed as a Claude Code plugin, these are available as `/pw:` commands:

| Command | What it does |
|---|---|
| `/pw:init` | Set up Playwright — detects framework, generates config, CI, first test |
| `/pw:generate <spec>` | Generate tests from user story, URL, or component |
| `/pw:review` | Review tests for anti-patterns and coverage gaps |
| `/pw:fix <test>` | Diagnose and fix failing or flaky tests |
| `/pw:migrate` | Migrate from Cypress or Selenium to Playwright |
| `/pw:coverage` | Analyze what''s tested vs. what''s missing |
| `/pw:testrail` | Sync with TestRail — read cases, push results |
| `/pw:browserstack` | Run on BrowserStack, pull cross-browser reports |
| `/pw:report` | Generate test report in your preferred format |

## Quick Start Workflow

The recommended sequence for most projects:

```
1. /pw:init          → scaffolds config, CI pipeline, and a first smoke test
2. /pw:generate      → generates tests from your spec or URL
3. /pw:review        → validates quality and flags anti-patterns      ← always run after generate
4. /pw:fix <test>    → diagnoses and repairs any failing/flaky tests  ← run when CI turns red
```

**Validation checkpoints:**
- After `/pw:generate` — always run `/pw:review` before committing; it catches locator anti-patterns and missing assertions automatically.
- After `/pw:fix` — re-run the full suite locally (`npx playwright test`) to confirm the fix doesn''t introduce regressions.
- After `/pw:migrate` — run `/pw:coverage` to confirm parity with the old suite before decommissioning Cypress/Selenium tests.

### Example: Generate → Review → Fix

```bash
# 1. Generate tests from a user story
/pw:generate "As a user I can log in with email and password"

# Generated: tests/auth/login.spec.ts
# → Playwright Pro creates the file using the auth template.

# 2. Review the generated tests
/pw:review tests/auth/login.spec.ts

# → Flags: one test used page.locator(''input[type=password]'') — suggests getByLabel(''Password'')
# → Fix applied automatically.

# 3. Run locally to confirm
npx playwright test tests/auth/login.spec.ts --headed

# 4. If a test is flaky in CI, diagnose it
/pw:fix tests/auth/login.spec.ts
# → Identifies missing web-first assertion; replaces waitForTimeout(2000) with expect(locator).toBeVisible()
```

## Golden Rules

1. `getByRole()` over CSS/XPath — resilient to markup changes
2. Never `page.waitForTimeout()` — use web-first assertions
3. `expect(locator)` auto-retries; `expect(await locator.textContent())` does not
4. Isolate every test — no shared state between tests
5. `baseURL` in config — zero hardcoded URLs
6. Retries: `2` in CI, `0` locally
7. Traces: `''on-first-retry''` — rich debugging without slowdown
8. Fixtures over globals — `test.extend()` for shared state
9. One behavior per test — multiple related assertions are fine
10. Mock external services only — never mock your own app

## Locator Priority

```
1. getByRole()        — buttons, links, headings, form elements
2. getByLabel()       — form fields with labels
3. getByText()        — non-interactive text
4. getByPlaceholder() — inputs with placeholder
5. getByTestId()      — when no semantic option exists
6. page.locator()     — CSS/XPath as last resort
```

## What''s Included

- **9 skills** with detailed step-by-step instructions
- **3 specialized agents**: test-architect, test-debugger, migration-planner
- **55 test templates**: auth, CRUD, checkout, search, forms, dashboard, settings, onboarding, notifications, API, accessibility
- **2 MCP servers** (TypeScript): TestRail and BrowserStack integrations
- **Smart hooks**:','.claude\skills\pw\SKILL.md','bad980c4452132e4c727a932715dfb2983f343c8609f33268e7e7e5a34b5a3fc','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:qms-audit-expert','project_skill','skill://simplicio-runtime/qms-audit-expert','skill: qms-audit-expert','---
name: qms-audit-expert
description: ISO 13485 internal audit expertise for medical device QMS. Covers audit planning, execution, nonconformity classification, and CAPA verification. Use when planning internal audits, executing audits, classifying findings, preparing for external audits, or managing an audit program.
triggers:
  - ISO 13485 audit
  - internal audit
  - QMS audit
  - audit planning
  - nonconformity classification
  - CAPA verification
  - audit checklist
  - audit finding
  - external audit prep
  - audit schedule
---

# QMS Audit Expert

ISO 13485 internal audit methodology for medical device quality management systems.

---

## Table of Contents

- [Audit Planning Workflow](#audit-planning-workflow)
- [Audit Execution](#audit-execution)
- [Nonconformity Management](#nonconformity-management)
- [External Audit Preparation](#external-audit-preparation)
- [Reference Documentation](#reference-documentation)
- [Tools](#tools)

---

## Audit Planning Workflow

Plan risk-based internal audit program:

1. List all QMS processes requiring audit
2. Assign risk level to each process (High/Medium/Low)
3. Review previous audit findings and trends
4. Determine audit frequency by risk level
5. Assign qualified auditors (verify independence)
6. Create annual audit schedule
7. Communicate schedule to process owners
8. **Validation:** All ISO 13485 clauses covered within cycle

### Risk-Based Audit Frequency

| Risk Level | Frequency | Criteria |
|------------|-----------|----------|
| High | Quarterly | Design control, CAPA, production validation |
| Medium | Semi-annual | Purchasing, training, document control |
| Low | Annual | Infrastructure, management review (if stable) |

### Audit Scope by Clause

| Clause | Process | Focus Areas |
|--------|---------|-------------|
| 4.2 | Document Control | Document approval, distribution, obsolete control |
| 5.6 | Management Review | Inputs complete, decisions documented, actions tracked |
| 6.2 | Training | Competency defined, records complete, effectiveness verified |
| 7.3 | Design Control | Inputs, reviews, V&V, transfer, changes |
| 7.4 | Purchasing | Supplier evaluation, incoming inspection |
| 7.5 | Production | Work instructions, process validation, DHR |
| 7.6 | Calibration | Equipment list, calibration status, out-of-tolerance |
| 8.2.2 | Internal Audit | Schedule compliance, auditor independence |
| 8.3 | NC Product | Identification, segregation, disposition |
| 8.5 | CAPA | Root cause, implementation, effectiveness |

### Auditor Independence

Verify auditor independence before assignment:

- [ ] Auditor not responsible for area being audited
- [ ] No direct reporting relationship to auditee
- [ ] Not involved in recent activities under audit
- [ ] Documented qualification for audit scope

---

## Audit Execution

Conduct systematic internal audit:

1. Prepare audit plan (scope, criteria, schedule)
2. Review relevant documentation before audit
3. Conduct opening meeting with auditee
4. Collect evidence (records, interviews, observation)
5. Classify findings (Major/Minor/Observation)
6. Conduct closing meeting with preliminary findings
7. Prepare audit report within 5 business days
8. **Validation:** All scope items covered, findings supported by evidence

### Evidence Collection

| Method | Use For | Documentation |
|--------|---------|---------------|
| Document review | Procedures, records | Document number, version, date |
| Interview | Process understanding | Interviewee name, role, summary |
| Observation | Actual practice | What, where, when observed |
| Record trace | Process flow | Record IDs, dates, linkage |

### Audit Questions by Clause

**Document Control (4.2):**
- Show me the document master list
- How do you control obsolete documents?
- Show me evidence of document change approval

**Design Control (7.3):**
- Show me the Design History File for [product]
- Who participates in design reviews?
- Show me design input to output traceability

**CAPA (8.5):**
- Show me the CAPA log with open items
- How do you determine root cause?
- Show me effecti','.claude\skills\qms-audit-expert\SKILL.md','7c90a2d88a2acbcfa56ec2e327217944cc008f094d63115ab4980e3d21fd3c8b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:quality-documentation-manager','project_skill','skill://simplicio-runtime/quality-documentation-manager','skill: quality-documentation-manager','---
name: quality-documentation-manager
description: Document control system management for medical device QMS. Covers document numbering, version control, change management, and 21 CFR Part 11 compliance. Use when working on document control procedures, change control workflows, document numbering, version management, electronic signature compliance, or regulatory documentation review.
triggers:
  - document control
  - document numbering
  - version control
  - change control
  - document approval
  - electronic signature
  - 21 CFR Part 11
  - audit trail
  - document lifecycle
  - controlled document
  - document master list
  - record retention
---

# Quality Documentation Manager

Document control system design and management for ISO 13485-compliant quality management systems, including numbering conventions, approval workflows, change control, and electronic record compliance.

---

## Table of Contents

- [Document Control Workflow](#document-control-workflow)
- [Document Numbering System](#document-numbering-system)
- [Approval and Review Process](#approval-and-review-process)
- [Change Control Process](#change-control-process)
- [21 CFR Part 11 Compliance](#21-cfr-part-11-compliance)
- [Reference Documentation](#reference-documentation)
- [Tools](#tools)

---

## Document Control Workflow

Implement document control from creation through obsolescence:

1. Assign document number per numbering procedure
2. Create document using controlled template
3. Route for review to required reviewers
4. Address review comments and document responses
5. Obtain required approval signatures
6. Assign effective date and distribute
7. Update Document Master List
8. **Validation:** Document accessible at point of use; obsolete versions removed

### Document Lifecycle Stages

| Stage | Definition | Actions Required |
|-------|------------|------------------|
| Draft | Under creation or revision | Author editing, not for use |
| Review | Circulated for review | Reviewers provide feedback |
| Approved | All signatures obtained | Ready for training/distribution |
| Effective | Training complete, released | Available for use |
| Superseded | Replaced by newer revision | Remove from active use |
| Obsolete | No longer applicable | Archive per retention schedule |

### Document Types and Prefixes

| Prefix | Document Type | Typical Content |
|--------|---------------|-----------------|
| QM | Quality Manual | QMS overview, scope, policy |
| SOP | Standard Operating Procedure | Process-level procedures |
| WI | Work Instruction | Task-level step-by-step |
| TF | Template/Form | Controlled forms |
| SPEC | Specification | Product/process specs |
| PLN | Plan | Quality/project plans |

### Required Reviewers by Document Type

| Document Type | Required Reviewers | Required Approvers |
|---------------|-------------------|-------------------|
| SOP | Process Owner, QA | QA Manager, Process Owner |
| WI | Area Supervisor, QA | Area Manager |
| SPEC | Engineering, QA | Engineering Manager, QA |
| TF | Process Owner | QA |
| Design Documents | Design Team, QA | Design Control Authority |

---

## Document Numbering System

Assign consistent document numbers for identification and retrieval.

### Numbering Format

Standard format: `PREFIX-CATEGORY-SEQUENCE[-REVISION]`

```
Example: SOP-02-001-A

SOP = Document type (Standard Operating Procedure)
02  = Category code (Document Control)
001 = Sequential number
A   = Revision indicator
```

### Category Codes

| Code | Functional Area | Description |
|------|-----------------|-------------|
| 01 | Quality Management | QMS procedures, management review |
| 02 | Document Control | This area |
| 03 | Human Resources | Training, competency |
| 04 | Design & Development | Design control processes |
| 05 | Purchasing | Supplier management |
| 06 | Production | Manufacturing procedures |
| 07 | Quality Control | Inspection, testing |
| 08 | CAPA | Corrective/preventive actions |
| 09 | Risk Management | ISO 14971 processes |
| 10 | Regulatory Affairs | Submissions, compliance |

### Numbering Workflow

1. ','.claude\skills\quality-documentation-manager\SKILL.md','9160d61b5ecc787eaecdffd5a976cad328b563d233aa0a432539cc3a25754fa0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:quality-manager-qmr','project_skill','skill://simplicio-runtime/quality-manager-qmr','skill: quality-manager-qmr','---
name: quality-manager-qmr
description: Senior Quality Manager Responsible Person (QMR) for HealthTech and MedTech companies. Provides quality system governance, management review leadership, regulatory compliance oversight, and quality performance monitoring per ISO 13485 Clause 5.5.2. Use when leading management reviews, setting quality policy and objectives, monitoring quality KPIs and cost of quality, or exercising QMR governance and regulatory oversight responsibilities.
triggers:
  - management review
  - quality policy
  - quality objectives
  - QMR responsibilities
  - quality system effectiveness
  - quality KPIs
  - cost of quality
  - quality performance
  - management accountability
  - regulatory oversight
  - quality culture
  - quality governance
---

# Senior Quality Manager Responsible Person (QMR)

Quality system accountability, management review leadership, and regulatory compliance oversight per ISO 13485 Clause 5.5.2 requirements.

---

## Table of Contents

- [QMR Responsibilities](#qmr-responsibilities)
- [Management Review Workflow](#management-review-workflow)
- [Quality KPI Management Workflow](#quality-kpi-management-workflow)
- [Quality Objectives Workflow](#quality-objectives-workflow)
- [Quality Culture Assessment Workflow](#quality-culture-assessment-workflow)
- [Regulatory Compliance Oversight](#regulatory-compliance-oversight)
- [Decision Frameworks](#decision-frameworks)
- [Tools and References](#tools-and-references)

---

## QMR Responsibilities

### ISO 13485 Clause 5.5.2 Requirements

| Responsibility | Scope | Evidence |
|----------------|-------|----------|
| QMS effectiveness | Monitor system performance and suitability | Management review records |
| Reporting to management | Communicate QMS performance to top management | Quality reports, dashboards |
| Quality awareness | Promote regulatory and quality requirements | Training records, communications |
| Liaison with external parties | Interface with regulators, Notified Bodies | Meeting records, correspondence |

### QMR Accountability Matrix

| Domain | Accountable For | Reports To | Frequency |
|--------|-----------------|------------|-----------|
| Quality Policy | Policy adequacy and communication | CEO/Board | Annual review |
| Quality Objectives | Objective achievement and relevance | Executive Team | Quarterly |
| QMS Performance | System effectiveness metrics | Management | Monthly |
| Regulatory Compliance | Compliance status across jurisdictions | CEO | Quarterly |
| Audit Program | Audit schedule completion, findings closure | Management | Per audit |
| CAPA Oversight | CAPA effectiveness and timeliness | Executive Team | Monthly |

### Authority Boundaries

| Decision Type | QMR Authority | Escalation Required |
|---------------|---------------|---------------------|
| Process changes within QMS | Approve with owner | Major process redesign |
| Document approval | Final QA approval | Policy-level changes |
| Nonconformity disposition | Accept/reject with MRB | Product release decisions |
| Supplier quality actions | Quality holds, audits | Supplier termination |
| Audit scheduling | Adjust internal audit schedule | External audit timing |
| Training requirements | Define quality training needs | Organization-wide training budget |

---

## Management Review Workflow

Conduct management reviews per ISO 13485 Clause 5.6 requirements.

### Workflow: Prepare and Execute Management Review

1. Schedule management review (minimum annually, typically quarterly or semi-annually)
2. Notify all required attendees minimum 2 weeks prior
3. Collect required inputs from process owners:
   - Audit results (internal and external)
   - Customer feedback (complaints, satisfaction, returns)
   - Process performance and product conformity
   - CAPA status and effectiveness
   - Previous review action items
   - Changes affecting QMS (regulatory, organizational)
   - Recommendations for improvement
4. Compile input summary report with trend analysis
5. Prepare presentation materials with supporting data
6. Distribute agenda and input ','.claude\skills\quality-manager-qmr\SKILL.md','aef6e0cd946bb154d6c03552a4f4d8cc848f514f536d74605e80af338481df5e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:quality-manager-qms-iso13485','project_skill','skill://simplicio-runtime/quality-manager-qms-iso13485','skill: quality-manager-qms-iso13485','---
name: quality-manager-qms-iso13485
description: ISO 13485 Quality Management System implementation and maintenance for medical device organizations. Provides QMS design, documentation control, internal auditing, CAPA management, and certification support. Use when working with medical device quality systems, preparing for ISO 13485 audits, managing regulatory compliance documentation, setting up corrective actions, or building audit preparation programs. Useful for quality management, audit preparation, regulatory compliance, medical device documentation, and corrective action workflows.
triggers:
  - ISO 13485
  - QMS implementation
  - quality management system
  - document control
  - internal audit
  - management review
  - quality manual
  - CAPA process
  - process validation
  - design control
  - supplier qualification
  - quality records
---

# Quality Manager - QMS ISO 13485 Specialist

ISO 13485:2016 Quality Management System implementation, maintenance, and certification support for medical device organizations.

---

## Table of Contents

- [QMS Implementation Workflow](#qms-implementation-workflow)
- [Document Control Workflow](#document-control-workflow)
- [Internal Audit Workflow](#internal-audit-workflow)
- [Process Validation Workflow](#process-validation-workflow)
- [Supplier Qualification Workflow](#supplier-qualification-workflow)
- [QMS Process Reference](#qms-process-reference)
- [Decision Frameworks](#decision-frameworks)
- [Tools and References](#tools-and-references)

---

## QMS Implementation Workflow

Implement ISO 13485:2016 compliant quality management system from gap analysis through certification.

### Workflow: Initial QMS Implementation

1. Conduct gap analysis against ISO 13485:2016 requirements
2. Document current state vs. required state for each clause
3. Prioritize gaps by:
   - Regulatory criticality
   - Risk to product safety
   - Resource requirements
4. Develop implementation roadmap with milestones
5. Establish Quality Manual per Clause 4.2.2:
   - QMS scope with justified exclusions
   - Process interactions
   - Procedure references
6. Create required documented procedures — see [Mandatory Documented Procedures](#quick-reference-mandatory-documented-procedures) for the full list
7. Deploy processes with training
8. **Validation:** Gap analysis complete; Quality Manual approved; all required procedures documented and trained

> Use the Gap Analysis Matrix template in [qms-process-templates.md](references/qms-process-templates.md) to document clause-by-clause current state, gaps, priority, and actions.

### QMS Structure

| Level | Document Type | Example |
|-------|---------------|---------|
| 1 | Quality Manual | QM-001 |
| 2 | Procedures | SOP-02-001 |
| 3 | Work Instructions | WI-06-012 |
| 4 | Records | Training records |

---

## Document Control Workflow

Establish and maintain document control per ISO 13485 Clause 4.2.3.

### Workflow: Document Creation and Approval

1. Identify need for new document or revision
2. Assign document number per numbering convention:
   - Format: `[TYPE]-[AREA]-[SEQUENCE]-[REV]`
   - Example: `SOP-02-001-01`
3. Draft document using approved template
4. Route for review to subject matter experts
5. Collect and address review comments
6. Obtain required approvals based on document type
7. Update Document Master List
8. **Validation:** Document numbered correctly; all reviewers signed; Master List updated

### Document Numbering Convention

| Prefix | Document Type | Approval Authority |
|--------|---------------|-------------------|
| QM | Quality Manual | Management Rep + CEO |
| POL | Policy | Department Head + QA |
| SOP | Procedure | Process Owner + QA |
| WI | Work Instruction | Supervisor + QA |
| TF | Template/Form | Process Owner |
| SPEC | Specification | Engineering + QA |

### Area Codes

| Code | Area | Examples |
|------|------|----------|
| 01 | Quality Management | Quality Manual, policy |
| 02 | Document Control | This procedure |
| 03 | Training | Competency procedures |
| 04 | Design | Design control |
| 05 | Purchasin','.claude\skills\quality-manager-qms-iso13485\SKILL.md','850caae7c5eb19b7a2a09bd5467331dc4aae83ea3e25eff694e46cf8c149fbdf','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:ra-qm-skills','project_skill','skill://simplicio-runtime/ra-qm-skills','skill: ra-qm-skills','---
name: ra-qm-skills
description: "Router/index for the 15 regulatory & quality-management skills bundled in this plugin (ISO 13485 QMS, EU MDR 2017/745, FDA submissions under QMSR, ISO 14971 risk, CAPA, document control, ISO 27001/ISMS, ISO 42001 AIMS, EU AI Act, GDPR/DSGVO, SOC 2, auditing). Use when a compliance request doesn''t obviously match one skill and you need to pick the right one (e.g., ''prepare us for an ISO 13485 audit'', ''is my AI system high-risk under the AI Act'')."
version: 2.9.0
author: Alireza Rezvani
license: MIT
tags:
  - regulatory
  - quality-management
  - iso-13485
  - mdr
  - fda
  - iso-27001
  - gdpr
agents:
  - claude-code
  - codex-cli
  - openclaw
---

# Regulatory Affairs & Quality Management Skills — Router

This plugin bundles **15 compliance skills** for HealthTech/MedTech organizations (this router is the 16th folder under `ra-qm-team/skills/`). Each skill is self-contained.

## Routing table

Match the request, then load `ra-qm-team/skills/<skill>/SKILL.md`. If multiple rows match, ask one clarifying question first.

| Request signals | Skill | Path |
|---|---|---|
| Regulatory strategy, pathway selection, submissions planning | regulatory-affairs-head | `skills/regulatory-affairs-head/` |
| Management review, quality KPIs, QMR governance | quality-manager-qmr | `skills/quality-manager-qmr/` |
| ISO 13485 QMS implementation, process control | quality-manager-qms-iso13485 | `skills/quality-manager-qms-iso13485/` |
| ISO 14971 risk analysis, FMEA, risk files | risk-management-specialist | `skills/risk-management-specialist/` |
| Root cause analysis, corrective/preventive actions | capa-officer | `skills/capa-officer/` |
| Document control, 21 CFR Part 11, DHF/DMR/DHR | quality-documentation-manager | `skills/quality-documentation-manager/` |
| ISO 13485 internal audits, NC classification | qms-audit-expert | `skills/qms-audit-expert/` |
| ISO 27001 audit planning and execution | isms-audit-expert | `skills/isms-audit-expert/` |
| ISMS design, security risk assessment | information-security-manager-iso27001 | `skills/information-security-manager-iso27001/` |
| EU MDR classification, technical files, PSUR | mdr-745-specialist | `skills/mdr-745-specialist/` |
| FDA 510(k)/PMA/De Novo, QMSR | fda-consultant-specialist | `skills/fda-consultant-specialist/` |
| GDPR/DSGVO, DPIA, data subject rights | gdpr-dsgvo-expert | `skills/gdpr-dsgvo-expert/` |
| EU AI Act risk classification, obligations | eu-ai-act-specialist | `skills/eu-ai-act-specialist/` |
| ISO/IEC 42001 AI management system | iso42001-specialist | `skills/iso42001-specialist/` |
| SOC 2 Type I/II readiness, trust criteria | soc2-compliance | `skills/soc2-compliance/` |

## Quick start

```bash
# Example: route a risk-analysis request
cat ra-qm-team/skills/risk-management-specialist/SKILL.md
python3 ra-qm-team/skills/risk-management-specialist/scripts/risk_matrix_calculator.py --help
```

## Rules

- Route to exactly one skill, then follow that skill''s workflow. This router ships no tools of its own.
- All outputs are decision support: final compliance determinations route to the named human owner (QMR, DPO, regulatory counsel) — never auto-decide.
- Verify regulatory citations against the current text (e.g., FDA QMSR effective 2026-02-02 replaced the legacy QSR subsections).

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: ra-qm-team. -->
','.claude\skills\ra-qm-skills\SKILL.md','36ff807290d2c7b717f24bbae6681dd10012302e1ea8c99ac6ae4df1c09c5054','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:rag-architect','project_skill','skill://simplicio-runtime/rag-architect','skill: rag-architect','---
name: rag-architect
description: "Use when the user asks to design a RAG pipeline, choose a chunking strategy or embedding model, pick a vector database, or evaluate retrieval quality (precision@k, recall@k, NDCG). Examples: ''design a RAG system for our docs'', ''what chunk size should I use for this corpus'', ''evaluate my retriever against ground truth''. NOT for general LLM cost tuning (use llm-cost-optimizer) or agent loops over retrieval (use agenthub)."
---

# RAG Architect

Design, tune, and evaluate production RAG pipelines with three deterministic tools. Run the tools against the actual corpus and requirements — do not pick chunk sizes or databases by intuition.

## Hard rules

1. **Never present model names or vendor prices as current facts.** Embedding models and vector-DB pricing rot in months. Recommend a *tier* (see table below), name a current-generation candidate, and tell the user to verify against the provider''s live pricing page.
2. **Every design ends with an evaluation run.** A RAG design without `retrieval_evaluator.py` numbers is a hypothesis, not a deliverable.
3. **Chunking is corpus-driven.** Run `chunking_optimizer.py` on the real documents before choosing a strategy.

## Embedding model tiers (pattern, not price list)

| Tier | Current-generation examples (verify before use) | When |
|---|---|---|
| Fast / self-hosted | `all-MiniLM-L6-v2`, `bge-small` | Cost-sensitive, small scale, real-time |
| Balanced open | `all-mpnet-base-v2`, `bge-large`, `e5-large` | Quality without API dependency |
| Quality API | `text-embedding-3-large`, `voyage-3-large` | Accuracy-priority general retrieval |
| Code | `voyage-code-3`, CodeBERT-family | Code search corpora |

**Pricing discipline:** build the cost model with a placeholder table — columns `model | $/1M tokens (verify) | dims | as-of date` — and have the user fill in live numbers. Same for vector DBs (Pinecone/Weaviate/Qdrant/Chroma/pgvector): the selection criteria (managed vs self-hosted, scale, filtering, existing Postgres) are durable; the dollar figures are not.

## Workflow

All paths relative to this skill folder. Outputs chain: corpus analysis → design → evaluation.

### 1. Analyze the corpus and pick chunking

```bash
python3 chunking_optimizer.py /path/to/docs --extensions .md .txt -o chunking.json
```

Emits `chunking.json` with `corpus_info`, per-strategy `strategy_results`, a `recommendation`, and `sample_chunks`. Use `recommendation.strategy` and its config; show the user 2-3 `sample_chunks` so they can sanity-check boundaries.

### 2. Design the pipeline from requirements

Write a requirements JSON with these keys (all required): `document_types[]`, `document_count`, `avg_document_size` (chars), `queries_per_day`, `query_patterns[]`, `latency_requirement`, `budget_monthly`, `accuracy_priority` (0-1), `cost_priority` (0-1), `maintenance_complexity`.

```bash
python3 rag_pipeline_designer.py requirements.json -o design.json
```

Emits `design.json` with `chunking`, `embedding`, `vector_db`, `retrieval`, `reranking`, `evaluation`, `total_cost`, `architecture_diagram` (mermaid), and `config_templates`. Present the diagram; label every `cost_monthly` figure as an estimate to verify (rule 1).

### 3. Evaluate retrieval quality

Prepare `queries.json` (list of `{id, text}` or `{"queries": [...]}`) and `ground_truth.json` (`{query_id: [relevant_doc_ids]}`), then:

```bash
python3 retrieval_evaluator.py queries.json /path/to/docs ground_truth.json --k-values 3 5 10 -o eval.json
```

Reports precision@k, recall@k, MRR, NDCG@k, plus `poor_precision_examples` / `poor_recall_examples` for failure analysis.

### 4. Verification loop

The design is done only when:

1. `eval.json` meets targets — typical floors: precision@5 ≥ 0.8, recall@10 ≥ 0.85 (set per use case with the user).
2. If below target: inspect the poor-example lists, then change **one** variable (chunking strategy → re-run step 1; embedding tier; add reranking; hybrid retrieval) and re-run step 3. Repeat.
3. Every recommended model/price in the deliverable carries a "verify current pricing','.claude\skills\rag-architect\SKILL.md','7c9fbccd6a215baa7247ffd5505d4e5494ee2c64e58ae9f335a75181d2d93fc9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:red-team','project_skill','skill://simplicio-runtime/red-team','skill: red-team','---
name: red-team
description: "Use when planning or executing authorized red team engagements, attack path analysis, or offensive security simulations. Covers MITRE ATT&CK kill-chain planning, technique scoring, choke point identification, OPSEC risk assessment, and crown jewel targeting."
---

# Red Team

Red team engagement planning and attack path analysis skill for authorized offensive security simulations. This is NOT vulnerability scanning (see security-pen-testing) or incident response (see incident-response) — this is about structured adversary simulation to test detection, response, and control effectiveness.

---

## Table of Contents

- [Overview](#overview)
- [Engagement Planner Tool](#engagement-planner-tool)
- [Kill-Chain Phase Methodology](#kill-chain-phase-methodology)
- [Technique Scoring and Prioritization](#technique-scoring-and-prioritization)
- [Choke Point Analysis](#choke-point-analysis)
- [OPSEC Risk Assessment](#opsec-risk-assessment)
- [Crown Jewel Targeting](#crown-jewel-targeting)
- [Attack Path Methodology](#attack-path-methodology)
- [Workflows](#workflows)
- [Anti-Patterns](#anti-patterns)
- [Cross-References](#cross-references)

---

## Overview

### What This Skill Does

This skill provides the methodology and tooling for **red team engagement planning** — building structured attack plans from MITRE ATT&CK technique selection, access level, and crown jewel targets. It scores techniques by effort and detection risk, assembles kill-chain phases, identifies choke points, and flags OPSEC risks.

### Distinction from Other Security Skills

| Skill | Focus | Approach |
|-------|-------|----------|
| **red-team** (this) | Adversary simulation | Offensive — structured attack planning and execution |
| security-pen-testing | Vulnerability discovery | Offensive — systematic exploitation of specific weaknesses |
| threat-detection | Finding attacker activity | Proactive — detect TTPs in telemetry |
| incident-response | Active incident management | Reactive — contain and investigate confirmed incidents |

### Authorization Requirement

**All red team activities described here require written authorization.** This includes a signed Rules of Engagement (RoE) document, defined scope, and explicit executive approval. The `engagement_planner.py` tool will not generate output without the `--authorized` flag. Unauthorized use of these techniques is illegal under the CFAA, Computer Misuse Act, and equivalent laws worldwide.

---

## Engagement Planner Tool

The `engagement_planner.py` tool builds a scored, kill-chain-ordered attack plan from technique selection, access level, and crown jewel targets.

```bash
# Basic engagement plan — external access, specific techniques
python3 scripts/engagement_planner.py \
  --techniques T1059,T1078,T1003 \
  --access-level external \
  --authorized --json

# Internal network access with crown jewel targeting
python3 scripts/engagement_planner.py \
  --techniques T1059,T1078,T1021,T1550,T1003 \
  --access-level internal \
  --crown-jewels "Database,Active Directory,Payment Systems" \
  --authorized --json

# Credentialed (assumed breach) scenario with scale
python3 scripts/engagement_planner.py \
  --techniques T1059,T1078,T1021,T1550,T1003,T1486,T1048 \
  --access-level credentialed \
  --crown-jewels "Domain Controller,S3 Data Lake" \
  --target-count 50 \
  --authorized --json

# List all 29 supported MITRE ATT&CK techniques
python3 scripts/engagement_planner.py --list-techniques
```

### Access Level Definitions

| Level | Starting Position | Techniques Available |
|-------|------------------|----------------------|
| external | No internal access — internet only | External-facing techniques only (T1190, T1566, etc.) |
| internal | Network foothold — no credentials | Internal recon + lateral movement prep |
| credentialed | Valid credentials obtained | Full kill chain including priv-esc, lateral movement, impact |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Engagement plan generated successfully |
| 1 | Missing authorization or invalid technique |','.claude\skills\red-team\SKILL.md','95a15571307a6bf036b0b8056377f4db4bf56176201f35bbbf77c6364d93c63b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:referrals','project_skill','skill://simplicio-runtime/referrals','skill: referrals','---
name: referrals
description: "When the user wants to create, optimize, or analyze a referral program, affiliate program, or word-of-mouth strategy. Also use when the user mentions ''referral,'' ''affiliate,'' ''ambassador,'' ''word of mouth,'' ''viral loop,'' ''refer a friend,'' ''partner program,'' ''referral incentive,'' ''how to get referrals,'' ''customers referring customers,'' or ''affiliate payout.'' Use this whenever someone wants existing users or partners to bring in new customers. For launch-specific virality, see launch."
metadata:
  version: 2.0.0
---

# Referral & Affiliate Programs

You are an expert in viral growth and referral marketing. Your goal is to help design and optimize programs that turn customers into growth engines.

## Before Starting

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Gather this context (ask if not provided):

### 1. Program Type
- Customer referral program, affiliate program, or both?
- B2B or B2C?
- What''s the average customer LTV?
- What''s your current CAC from other channels?

### 2. Current State
- Existing referral/affiliate program?
- Current referral rate (% who refer)?
- What incentives have you tried?

### 3. Product Fit
- Is your product shareable?
- Does it have network effects?
- Do customers naturally talk about it?

### 4. Resources
- Tools/platforms you use or consider?
- Budget for referral incentives?

---

## Referral vs. Affiliate

### Customer Referral Programs

**Best for:**
- Existing customers recommending to their network
- Products with natural word-of-mouth
- Lower-ticket or self-serve products

**Characteristics:**
- Referrer is an existing customer
- One-time or limited rewards
- Higher trust, lower volume

### Affiliate Programs

**Best for:**
- Reaching audiences you don''t have access to
- Content creators, influencers, bloggers
- Higher-ticket products that justify commissions

**Characteristics:**
- Affiliates may not be customers
- Ongoing commission relationship
- Higher volume, variable trust

---

## Referral Program Design

### The Referral Loop

```
Trigger Moment → Share Action → Convert Referred → Reward → (Loop)
```

### Step 1: Identify Trigger Moments

**High-intent moments:**
- Right after first "aha" moment
- After achieving a milestone
- After exceptional support
- After renewing or upgrading

### Step 2: Design Share Mechanism

**Ranked by effectiveness:**
1. In-product sharing (highest conversion)
2. Personalized link
3. Email invitation
4. Social sharing
5. Referral code (works offline)

### Step 3: Choose Incentive Structure

**Single-sided rewards** (referrer only): Simpler, works for high-value products

**Double-sided rewards** (both parties): Higher conversion, win-win framing

**Tiered rewards**: Gamifies referral process, increases engagement

**For examples and incentive sizing**: See [references/program-examples.md](references/program-examples.md)

---

## Program Optimization

### Improving Referral Rate

**If few customers are referring:**
- Ask at better moments
- Simplify sharing process
- Test different incentive types
- Make referral prominent in product

**If referrals aren''t converting:**
- Improve landing experience for referred users
- Strengthen incentive for new users
- Ensure referrer''s endorsement is visible

### A/B Tests to Run

**Incentive tests:** Amount, type, single vs. double-sided, timing

**Messaging tests:** Program description, CTA copy, landing page copy

**Placement tests:** Where and when the referral prompt appears

### Common Problems & Fixes

| Problem | Fix |
|---------|-----|
| Low awareness | Add prominent in-app prompts |
| Low share rate | Simplify to one click |
| Low conversion | Optimize referred user experience |
| Fraud/abuse | Add verification, limits |
| One-time referrers | Add tiered/gamified rewards |

---

## Measuring S','.claude\skills\referrals\SKILL.md','eaaff642de5aab01641efdaa7f7796c7f6402fcf4f5fca932808f56b2cbfca7f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:regulatory-affairs-head','project_skill','skill://simplicio-runtime/regulatory-affairs-head','skill: regulatory-affairs-head','---
name: regulatory-affairs-head
description: Senior Regulatory Affairs Manager for HealthTech and MedTech companies. Prepares FDA 510(k), De Novo, and PMA submission packages; analyzes regulatory pathways for new medical devices; drafts responses to FDA deficiency letters and Notified Body queries; develops CE marking technical documentation under EU MDR 2017/745; coordinates multi-market approval strategies across FDA, EU, Health Canada, PMDA, and NMPA; and maintains regulatory intelligence on evolving standards. Use when users need to plan or execute FDA submissions, navigate 510(k) or PMA approval processes, achieve CE marking, prepare pre-submission meeting materials, write regulatory strategy documents, respond to agency queries, or manage compliance documentation for medical device market access.
triggers:
  - regulatory strategy
  - FDA submission
  - EU MDR
  - 510(k)
  - PMA approval
  - CE marking
  - regulatory pathway
  - market access
  - clinical evidence
  - regulatory intelligence
  - submission planning
  - notified body
---

# Head of Regulatory Affairs

Regulatory strategy development, submission management, and global market access for medical device organizations.

---

## Table of Contents

- [Regulatory Strategy Workflow](#regulatory-strategy-workflow)
- [FDA Submission Workflow](#fda-submission-workflow)
- [EU MDR Submission Workflow](#eu-mdr-submission-workflow)
- [Global Market Access Workflow](#global-market-access-workflow)
- [Regulatory Intelligence Workflow](#regulatory-intelligence-workflow)
- [Decision Frameworks](#decision-frameworks)
- [Tools and References](#tools-and-references)

---

## Regulatory Strategy Workflow

Develop regulatory strategy aligned with business objectives and product characteristics.

### Workflow: New Product Regulatory Strategy

1. Gather product information:
   - Intended use and indications
   - Device classification (risk level)
   - Technology platform
   - Target markets and timeline
2. Identify applicable regulations per target market:
   - FDA (US): 21 CFR Part 820, 510(k)/PMA/De Novo
   - EU: MDR 2017/745, Notified Body requirements
   - Other markets: Health Canada, PMDA, NMPA, TGA
3. Determine optimal regulatory pathway:
   - Compare submission types (510(k) vs De Novo vs PMA)
   - Assess predicate device availability
   - Evaluate clinical evidence requirements
4. Develop regulatory timeline with milestones
5. Estimate resource requirements and budget
6. Identify regulatory risks and mitigation strategies
7. Obtain stakeholder alignment and approval
8. **Validation:** Strategy document approved; timeline accepted; resources allocated

### Regulatory Pathway Selection Matrix

| Factor | 510(k) | De Novo | PMA |
|--------|--------|---------|-----|
| Predicate Available | Yes | No | N/A |
| Risk Level | Low-Moderate | Low-Moderate | High |
| Clinical Data | Usually not required | May be required | Required |
| Review Time | 90 days (MDUFA) | 150 days | 180 days |
| User Fee | ~$22K (2024) | ~$135K | ~$440K |
| Best For | Me-too devices | Novel low-risk | High-risk, novel |

### Regulatory Strategy Document Template

```
REGULATORY STRATEGY

Product: [Name]   Version: [X.X]   Date: [Date]

1. PRODUCT OVERVIEW
   Intended use: [One-sentence statement of intended patient population, body site, and clinical purpose]
   Device classification: [Class I / II / III]
   Technology: [Brief description, e.g., "AI-powered wound-imaging software, SaMD"]

2. TARGET MARKETS & TIMELINE
   | Market | Pathway        | Priority | Target Date |
   |--------|----------------|----------|-------------|
   | USA    | 510(k) / PMA   | 1        | Q1 20XX     |
   | EU     | Class [X] MDR  | 2        | Q2 20XX     |

3. REGULATORY PATHWAY RATIONALE
   FDA: [510(k) / De Novo / PMA] — Predicate: [K-number or "none"]
   EU:  Class [X] via [Annex IX / X / XI] — NB: [Name or TBD]
   Rationale: [2–3 sentences on key factors driving pathway choice]

4. CLINICAL EVIDENCE STRATEGY
   Requirements: [Summarize what each market needs, e.g., "510(k): bench + usability; EU Class IIb: PMCF stu','.claude\skills\regulatory-affairs-head\SKILL.md','75bced23d1be99802aa6877fa4e732b989831fc71fc1ccdf04e6ba45147700fa','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:remember','project_skill','skill://simplicio-runtime/remember','skill: remember','---
name: remember
description: "Explicitly save important knowledge to auto-memory with timestamp and context. Use when a discovery is too important to rely on auto-capture."
---

# /si:remember — Save Knowledge Explicitly

Writes an explicit entry to auto-memory when something is important enough that you don''t want to rely on Claude noticing it automatically.

## Usage

```
/si:remember <what to remember>
/si:remember "This project''s CI requires Node 20 LTS — v22 breaks the build"
/si:remember "The /api/auth endpoint uses a custom JWT library, not passport"
/si:remember "Reza prefers explicit error handling over try-catch-all patterns"
```

## When to Use

| Situation | Example |
|-----------|---------|
| Hard-won debugging insight | "CORS errors on /api/upload are caused by the CDN, not the backend" |
| Project convention not in CLAUDE.md | "We use barrel exports in src/components/" |
| Tool-specific gotcha | "Jest needs `--forceExit` flag or it hangs on DB tests" |
| Architecture decision | "We chose Drizzle over Prisma for type-safe SQL" |
| Preference you want Claude to learn | "Don''t add comments explaining obvious code" |

## Workflow

### Step 1: Parse the knowledge

Extract from the user''s input:
- **What**: The concrete fact or pattern
- **Why it matters**: Context (if provided)
- **Scope**: Project-specific or global?

### Step 2: Check for duplicates

```bash
MEMORY_DIR="$HOME/.claude/projects/$(pwd | sed ''s|/|%2F|g; s|%2F|/|; s|^/||'')/memory"
grep -ni "<keywords>" "$MEMORY_DIR/MEMORY.md" 2>/dev/null
```

If a similar entry exists:
- Show it to the user
- Ask: "Update the existing entry or add a new one?"

### Step 3: Write to MEMORY.md

Append to the end of `MEMORY.md`:

```markdown
- {{concise fact or pattern}}
```

Keep entries concise — one line when possible. Auto-memory entries don''t need timestamps, IDs, or metadata. They''re notes, not database records.

If MEMORY.md is over 180 lines, warn the user:

```
⚠️ MEMORY.md is at {{n}}/200 lines. Consider running /si:review to free space.
```

### Step 4: Suggest promotion

If the knowledge sounds like a rule (imperative, always/never, convention):

```
💡 This sounds like it could be a CLAUDE.md rule rather than a memory entry.
   Rules are enforced with higher priority. Want to /si:promote it instead?
```

### Step 5: Confirm

```
✅ Saved to auto-memory

  "{{entry}}"

  MEMORY.md: {{n}}/200 lines
  Claude will see this at the start of every session in this project.
```

## What NOT to use /si:remember for

- **Temporary context**: Use session memory or just tell Claude in conversation
- **Enforced rules**: Use `/si:promote` to write directly to CLAUDE.md
- **Cross-project knowledge**: Use `~/.claude/CLAUDE.md` for global rules
- **Sensitive data**: Never store credentials, tokens, or secrets in memory files

## Tips

- Be concise — one line beats a paragraph
- Include the concrete command or value, not just the concept
  - ✅ "Build with `pnpm build`, tests with `pnpm test:e2e`"
  - ❌ "The project uses pnpm for building and testing"
- If you''re remembering the same thing twice, promote it to CLAUDE.md

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering-team. -->
','.claude\skills\remember\SKILL.md','a3847523be8d7d30cfeff894e138d1a51af7048598ebbb6f2b7013476d34b52f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:remotion-to-hyperframes','project_skill','skill://simplicio-runtime/remotion-to-hyperframes','skill: remotion-to-hyperframes','---
name: remotion-to-hyperframes
description: ''Port an existing Remotion (React) composition to HyperFrames HTML. Use ONLY when the user explicitly asks to port/convert/migrate/translate a Remotion source. Do NOT use: (a) authoring a new HyperFrames composition; (b) Remotion mentioned in passing; (c) Remotion code shared as reference only; (d) "same video as my Remotion one" without explicit migrate request — treat as fresh build. Doubt → `/general-video`. One-way, Remotion-only: no reverse export (HyperFrames→Remotion or any framework), no non-Remotion source (After Effects, Framer Motion, plain React/CSS) → out of scope, re-create via `/general-video`. Flags unsupported patterns (useState, useEffect, async calculateMetadata, third-party React libs, `@remotion/lambda`) and recommends runtime interop over lossy translation. Unsure whether to port vs. build fresh, or only a passing Remotion mention? → /hyperframes.''
---

# Remotion to HyperFrames

> **Confirm the route before you build.** Use this **only** to port an existing **Remotion** (React) composition''s source into HyperFrames. Authoring a **new** composition (even one inspired by a Remotion video) → the creation workflows / `/general-video`. **Out of scope** (one-way, Remotion-only): no reverse export (HyperFrames → Remotion or any framework), and a **non-Remotion** source (After Effects, Framer Motion, plain React / CSS) has no Remotion source to translate → re-create via `/general-video`. Unsure, or only a passing Remotion mention? **Read `/hyperframes` first.**

## Overview

Translate Remotion (React-based) video compositions into HyperFrames (HTML + GSAP) compositions. Most Remotion idioms have direct HyperFrames equivalents — the translation is mechanical for ~80% of typical compositions. This skill encodes the mapping and guards against the lossy 20% by refusing to translate patterns that don''t fit HF''s seek-driven model and recommending the runtime interop pattern from [PR #214](https://github.com/heygen-com/hyperframes/pull/214) instead.

The skill ships with a **tiered test corpus** (T1–T4, 4 fixtures total) that grades translations against measured SSIM thresholds. Don''t translate without running the eval — a translation that "looks right" but renders 0.05 SSIM lower than the validated baseline is silently wrong.

## When to use

**Use this skill ONLY when the user explicitly asks to migrate from Remotion.** Example trigger phrases:

- "port my Remotion project to HyperFrames"
- "convert this Remotion code to HyperFrames"
- "migrate from Remotion"
- "translate this Remotion comp"
- "rewrite this as HyperFrames HTML"

**Do NOT use this skill when:**

- (a) The user is authoring a **new** HyperFrames composition, even if they have or are A/B-testing a similar Remotion video.
- (b) The user mentions Remotion in passing without asking for migration.
- (c) The user shares Remotion code as reference material rather than asking for a translation.
- (d) The user asks for "the same video as my Remotion one" without explicitly asking to migrate the source — treat that as a fresh HyperFrames build.

**NOT SUPPORTED (decline — this is not what this skill does):**

- **The reverse direction.** Exporting a HyperFrames composition back out _to_ Remotion (or to any other framework) is not a workflow — the translation is Remotion → HyperFrames only. Say so plainly.
- **Non-Remotion sources.** An After Effects project (`.aep`), a Framer Motion / plain-React / CSS animation, or any other tool''s source is not a Remotion composition — there is no Remotion source to translate. Re-create it natively via `/general-video`, or decline if HyperFrames can''t represent it.

When in doubt, default to authoring a native HyperFrames composition with `/general-video` (the general HyperFrames authoring flow) instead.

## Workflow

### Step 1: Lint the source

Run [`scripts/lint_source.py`](scripts/lint_source.py) over the Remotion source directory. The lint detects patterns that can''t translate cleanly:

- **Blockers** (refuse + recommend interop): `useState`, `useReducer`, `useEffect`/`','.claude\skills\remotion-to-hyperframes\SKILL.md','a254fbf0d516d1da2906b6406ef266ea5d1a5a8d3cf315054e901eb72f91aa1a','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:renewal-tracker','project_skill','skill://simplicio-runtime/renewal-tracker','skill: renewal-tracker','---
name: renewal-tracker
description: >
  Show contracts with cancel-by deadlines coming up and warn before notice windows
  close, working from a maintained renewal register. Use when the user asks "what''s
  renewing soon", "what renewals are due", "did we miss a cancellation window", "add
  this to the renewal tracker", or on a scheduled basis. Receives handoffs from
  saas-msa-review.
argument-hint: "[--days N to change window | --missed for lapsed windows]"
---

# /renewal-tracker

Surfaces what''s renewing and when you have to cancel by.

## Instructions

1. **Read `~/.claude/plugins/config/claude-for-legal/commercial-legal/renewal-register.yaml`** (the config directory — survives plugin updates).

2. **Default mode:** Mode 2 — what''s coming up in the next 90 days, grouped by urgency using half-open intervals so each deadline lands in exactly one band: 🔴 0–13 days, 🟠 14–44 days, 🟡 45–89 days. Days 14, 45, and 90 are boundaries — each belongs to exactly one band, not two.

3. **`--days N`:** Change the window.

4. **`--missed`:** Mode 4 — cancel-by deadlines that passed without recorded cancellation.

5. **If register is empty and the [CLM] is connected:** Offer Mode 3 — scan the [CLM] for active agreements with renewal dates and bulk-load.

6. **Output includes recommended actions:** who to ping (the business owner from each register entry), which ones have uncapped pricing (get leverage before window closes).

## Examples

```
/commercial-legal:renewal-tracker
```

```
/commercial-legal:renewal-tracker --days 180
```

```
/commercial-legal:renewal-tracker --missed
```

---

## Purpose

Nobody reads a contract twice. The renewal date is extracted once, at review time, and then it lives somewhere — ideally somewhere that shouts at you 45 days before the cancel-by deadline, not 45 days after.

This skill maintains the renewal register and surfaces what''s coming.

## The register

Lives at `~/.claude/plugins/config/claude-for-legal/commercial-legal/renewal-register.yaml` (the config directory — survives plugin updates). Each entry:

```yaml
- counterparty: "Acme SaaS Inc."
  agreement: "Acme Platform Subscription Agreement"
  signed_date: 2025-06-15
  initial_term_end: 2026-06-15
  current_term_end: 2026-06-15     # rolls forward after each auto-renewal; compute cancel_by_* from this
  renewal_mechanism: "auto-renew annual"
  notice_period_days: 60
  notice_method: "email"           # email / portal / certified mail / registered post / courier / per contract §X
  transit_buffer_days: 0           # 0 for electronic, 5 for domestic certified mail, 10 for international registered post — or per contract if specified
  cancel_by_calendar: 2026-04-16    # current_term_end minus notice_period_days
  cancel_by_effective: 2026-04-16   # rolled back to last business day if needed
  send_by_effective: 2026-04-16    # cancel_by_effective minus transit_buffer_days — the date you must SEND the notice
  cancel_by_roll_note: ""           # e.g., "rolled back from Sunday 2026-11-01; verify against contract''s business-day definition"
  cancel_by_provenance: "[model calculation — verify against the notice clause]"
  price_on_renewal: "then-current list (uncapped)"
  annual_value: 48000
  business_owner: "jane@company.com"
  clm_id:        "IC-12345"        # if connected
  docusign_envelope: "abc-123"   # if connected
  status: "active"               # active | cancelled | renewed | lapsed
  notes: "Pricing uncapped — revisit before renewal. Alt vendors: X, Y."
```

**Notice transit time — alert off `send_by_effective`, not `cancel_by_effective`.** A 60-day window with a certified-mail requirement is really ~55 days. The tracker that alerts on the received-by date is the tracker that misses the deadline. Compute `send_by_effective = cancel_by_effective - transit_buffer_days` and fire alerts (the 🔴 / 🟠 / 🟡 urgency bands in Mode 2) off `send_by_effective`. Mode 2''s urgency column shows `send_by_effective`; a detail column surfaces `cancel_by_effective`, `notice_method`, and `transit_buffer_days` so the reader can see the delta and challeng','.claude\skills\renewal-tracker\SKILL.md','edd7cc0f712ebec5adb5986c787f7b116af3d7dafb38e18797d0e1c648cb3140','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:report','project_skill','skill://simplicio-runtime/report','skill: report','---
name: report
description: >-
  Generate test report. Use when user says "test report", "results summary",
  "test status", "show results", "test dashboard", or "how did tests go".
---

# Smart Test Reporting

Generate test reports that plug into the user''s existing workflow. Zero new tools.

## Steps

### 1. Run Tests (If Not Already Run)

Check if recent test results exist:

```bash
ls -la test-results/ playwright-report/ 2>/dev/null
```

If no recent results, run tests:

```bash
npx playwright test --reporter=json,html,list 2>&1 | tee test-output.log
```

### 2. Parse Results

Read the JSON report:

```bash
npx playwright test --reporter=json 2> /dev/null
```

Extract:
- Total tests, passed, failed, skipped, flaky
- Duration per test and total
- Failed test names with error messages
- Flaky tests (passed on retry)

### 3. Detect Report Destination

Check what''s configured and route automatically:

| Check | If found | Action |
|---|---|---|
| `TESTRAIL_URL` env var | TestRail configured | Push results via `/pw:testrail push` |
| `SLACK_WEBHOOK_URL` env var | Slack configured | Post summary to Slack |
| `.github/workflows/` | GitHub Actions | Results go to PR comment via artifacts |
| `playwright-report/` | HTML reporter | Open or serve the report |
| None of the above | Default | Generate markdown report |

### 4. Generate Report

#### Markdown Report (Always Generated)

```markdown
# Test Results — {{date}}

## Summary
- ✅ Passed: {{passed}}
- ❌ Failed: {{failed}}
- ⏭️ Skipped: {{skipped}}
- 🔄 Flaky: {{flaky}}
- ⏱️ Duration: {{duration}}

## Failed Tests
| Test | Error | File |
|---|---|---|
| {{name}} | {{error}} | {{file}}:{{line}} |

## Flaky Tests
| Test | Retries | File |
|---|---|---|
| {{name}} | {{retries}} | {{file}} |

## By Project
| Browser | Passed | Failed | Duration |
|---|---|---|---|
| Chromium | X | Y | Zs |
| Firefox | X | Y | Zs |
| WebKit | X | Y | Zs |
```

Save to `test-reports/{{date}}-report.md`.

#### Slack Summary (If Webhook Configured)

```bash
curl -X POST "$SLACK_WEBHOOK_URL" \
  -H ''Content-Type: application/json'' \
  -d ''{
    "text": "🧪 Test Results: ✅ {{passed}} | ❌ {{failed}} | ⏱️ {{duration}}\n{{failed_details}}"
  }''
```

#### TestRail Push (If Configured)

Invoke `/pw:testrail push` with the JSON results.

#### HTML Report

```bash
npx playwright show-report
```

Or if in CI:
```bash
echo "HTML report available at: playwright-report/index.html"
```

### 5. Trend Analysis (If Historical Data Exists)

If previous reports exist in `test-reports/`:
- Compare pass rate over time
- Identify tests that became flaky recently
- Highlight new failures vs. recurring failures

## Output

- Summary with pass/fail/skip/flaky counts
- Failed test details with error messages
- Report destination confirmation
- Trend comparison (if historical data available)
- Next action recommendation (fix failures or celebrate green)

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering-team. -->
','.claude\skills\report\SKILL.md','ba3a143754770cfc473b37298b1d919fa7f326d806cfe8a5a23d3dc18e525e84','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:research','project_skill','skill://simplicio-runtime/research','skill: research','---
name: research
description: Default entry point for any research request — a hybrid router that classifies the question deterministically and either delegates to a specialist research skill (pulse for trends/sentiment, grants for NIH funding, litreview for academic literature, syllabus for course reading, patent for prior-art + IP landscape, dossier for entity research) or runs its own plan-decompose-multi-source-search-synthesize-cite fallback workflow when no specialist matches. Always surfaces the routing decision so users can override. Use when the user makes any research request that doesn''t obviously match a more-specific specialist skill (e.g., "research [topic]", "look into [topic]", "what do we know about [topic]", "investigate [topic]", "find me information on [topic]", "do some research on [topic]", "I need to understand [topic]"). Output is a markdown briefing (default) or .docx document (on request) with full citations and an audit log.
---

# Research — Hybrid Router + Fallback

**The runtime orchestrator for the research domain.** Architecture C: deterministic classification → specialist delegation OR own plan-decompose-search-synthesize-cite workflow.

## Portability

Requires `WebSearch` + `WebFetch` for the fallback workflow; specialist skills (`pulse`, `grants`, `litreview`, `syllabus`, `patent`, `dossier`) must be present for delegation to work. Node.js with `docx` package required if Q2 = document mode. Works in Claude Code CLI natively. In Claude.ai with web tools + Code Execution, the workflow is supported.

## Distinct From `engineering/autoresearch-agent`

These two skills share the word "research" but serve **completely different use cases**:

- **`research/research/`** (this skill) — research-query router + fallback workflow ("Research X")
- **`engineering/autoresearch-agent/`** — Karpathy''s autonomous file-optimization experiment loop ("Make this code faster")

No overlap. They coexist.

## Hybrid Architecture (C)

Every invocation produces one of three outcomes:

1. **Delegation** — Classified as specialist-domain. Routes there. User sees the specialist''s output.
2. **Fallback execution** — Classified as general research. Runs own plan → search → synthesize workflow.
3. **Clarification request** — Classification ambiguous. Asks one forcing question to disambiguate, then routes.

The skill **never silently runs its fallback** when a specialist would have done better. **Routing transparency** is what makes the hybrid architecture trustworthy.

## Specialist Registry

| Specialist | Routing signals | Domain |
|---|---|---|
| `pulse` | reddit / hn / x / buzz / sentiment / trending / "what''s people saying" / "pulse on" / "take the pulse" / "current conversation" | Multi-source recency research |
| `grants` | NIH / grant / R01 / K-award / RePORTER / NOSI / "grants for" / FDA / "study section" / "principal investigator" | NIH grant-funding intelligence |
| `litreview` | literature review / PICO / SPIDER / systematic review / "review papers on" / meta-analysis | Academic literature orientation |
| `syllabus` | syllabus / course outline / curriculum / "reading list" / "for my class" / "for my students" | Course supplementary reading |
| `patent` | prior art / FTO / freedom to operate / patent / "patent landscape" / invention / novelty search / "ip landscape" | Patent prior-art + landscape |
| `dossier` | "dossier on" / "due diligence" / "background check" / "prep me for" / "competitor research" / "investor diligence" / "interview prep" / "background on" | Decision-grade entity research |

## Agent Integrity Rules

This skill obeys the research-pack convention:

- **Execution discipline (fallback only)**: Sequential searches. 1 q/sec rate limit. Confirm response received before next call.
- **Source discipline**: Cite only sources returned by this session''s tool calls. Training knowledge labeled `[Background — not from search]` and excluded from counts.
- **Three-count tracking (fallback only)**: Queries sent / sources received / sources cited.
- **Retry policy**: On failure → wait 3s → retry once ','.claude\skills\research\SKILL.md','c2a9dd22fff97d29cfbc3f6eb23b7b02342f574e8f1d3321486d1e618af95bf1','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:research-finance','project_skill','skill://simplicio-runtime/research-finance','skill: research-finance','---
name: research-finance
description: Use when managing the money for an internal R&D program or portfolio — building a multi-period program budget with the F&A (indirect) split, tracking burn rate and runway against value-inflection milestones, or routing R&D cost items to a capitalize-vs-expense determination. Every budget output surfaces its assumptions block; capitalize-vs-expense is decision-support only and routes to a named finance owner — it never books an entry or decides accounting treatment. Distinct from finance/financial-analysis (corporate DCF, close, valuation) and research/grants (funding discovery — this manages money already won).
version: 2.9.0
author: claude-code-skills
license: MIT
tags: [research-ops, research-finance, rd-budget, burn-rate, runway, fa-rate, capitalize-vs-expense, portfolio]
compatible_tools: [claude-code, codex-cli, cursor, antigravity, opencode, gemini-cli]
---

# research-finance

Financial management of internal R&D programs and portfolios: program budgeting with F&A, burn/runway tracking, and capitalize-vs-expense routing. Every number ships with its **assumptions block**, and accounting-treatment calls **route to a named finance owner** — this skill never books an entry.

## Purpose

R&D finance partners, program controllers, and operations leads manage money that has already been allocated or raised — not the corporate close, not the next funding round, not finding a grant. This skill structures three recurring decisions:

Three deterministic tools:

1. `program_budget_planner.py` — Builds a multi-period budget from work-package line items, applies the F&A (indirect) rate to an MTDC-style eligible base, and rolls up direct / F&A / fully-loaded cost per period with an explicit assumptions block.
2. `burn_runway_tracker.py` — Computes average + trailing burn, runway in periods/months, and whether each value-inflection milestone is reachable before cash runs out. Flags accelerating burn and below-threshold runway.
3. `capex_vs_opex_router.py` — Scores each R&D cost item against the IAS 38 development-phase criteria (or flags US GAAP ASC 730 expense-as-incurred) and routes it to **CAPITALIZE-CANDIDATE / EXPENSE / FINANCE-OWNER-REVIEW** with a named owner. Never auto-decides.

## When to use

Invoke this skill when:

- You are building or revising an R&D program budget and need the F&A split made explicit.
- A program''s runway is in question and you need a milestone-vs-cash read.
- Finance asks whether a development cost can be capitalized and you need a defensible first routing.
- You are preparing a portfolio review and need per-program burn consistency.

**Do NOT use this skill to**: run corporate DCF / valuation / close (use `finance/financial-analysis`), discover or position grants (use `research/grants`), or make the final accounting determination (that is the controller''s + auditor''s call — this tool only routes).

## Workflow

1. **Lay out the program** — Fill `assets/rd_program_budget_template.md` with work-package lines, categories, and per-period amounts.
2. **Build the budget** — Run `program_budget_planner.py --input program.json --profile {pharma-rd|biotech|medtech|deep-tech|software-rd|university-lab} --fa-rate <negotiated rate>`. Read direct / F&A / fully-loaded rollups + assumptions.
3. **Track burn & runway** — Run `burn_runway_tracker.py --input ledger.json --threshold-months 6`. Read runway + milestone verdicts + flags.
4. **Route accounting treatment** — Run `capex_vs_opex_router.py --input costs.json --standard {ifrs|usgaap}`. Read the per-item routing; send CAPITALIZE-CANDIDATE and FINANCE-OWNER-REVIEW items to the named owner.
5. **Assemble the review** — Combine into a program-finance packet. Every number carries its assumptions; treatment calls carry a named owner.

## Scripts

| Script | Purpose | Profiles |
|---|---|---|
| `scripts/program_budget_planner.py` | Multi-period budget + F&A split + assumptions | pharma-rd, biotech, medtech, deep-tech, software-rd, university-lab |
| `scripts/burn_runway_tracker.py` | Burn, runway, milestone-vs-cash alignmen','.claude\skills\research-finance\SKILL.md','51311d7078055f72bcc763949fd53cd1451ee688d38238a4e6ceac4f2cdf407c','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:research-ops-skills','project_skill','skill://simplicio-runtime/research-ops-skills','skill: research-ops-skills','---
name: research-ops-skills
description: Use when planning, funding, scoping, or synthesizing enterprise research across workstreams — clinical study design, R&D program finance, market sizing/surveys, or product/user research. Triggers on "design this clinical study", "what sample size", "R&D budget", "burn rate", "capitalize or expense", "TAM SAM SOM", "market sizing", "survey design", "segment the market", "plan user interviews", "usability test", "synthesize research insights". Forks context to route to one of four Research-Operations sub-skills (clinical-research, research-finance, market-research, product-research) and returns a digest. Distinct from ra-qm-team (regulatory submission), finance (corporate close/valuation), research/grants (funding discovery), product-team (persona/journey/live experiments), and marketing-skill (campaign analytics).
context: fork
version: 2.9.0
author: claude-code-skills
license: MIT
tags: [research-ops, clinical-research, research-finance, market-research, product-research, rd, orchestrator]
compatible_tools: [claude-code, codex-cli, cursor, antigravity, opencode, gemini-cli]
---

# Research Operations — Domain Orchestrator

The Research Operations surface is **how the enterprise plans, funds, scopes, and synthesizes research** across four workstreams: clinical R&D, R&D finance, market research, and product research. This orchestrator forks its context, routes your inquiry to one of four sub-skills, then returns a digest. Heavy intake (protocol drafts, program ledgers, survey exports, interview transcripts) stays in the forked context.

This is the enterprise counterpart to the academic `research/` domain. If your question is about **finding** literature, grants, or patents, use `research/`. If it is about **planning, funding, scoping, or synthesizing** research as an operational discipline, you are in the right place.

## When to invoke

| Symptom | Sub-skill |
|---|---|
| "We''re designing a Phase 2 trial — what''s the endpoint and sample size?" | `clinical-research` |
| "What''s our R&D program burn, and is this cost CapEx or OpEx?" | `research-finance` |
| "What''s the TAM for this product, and how do we survey the segment?" | `market-research` |
| "How many users do we interview, and how do we synthesize the findings?" | `product-research` |

## Routing logic (deterministic)

Same two-signal threshold pattern as `commercial-skills`. Single-signal → clarifying question. Mixed signals → highest-confidence first, chain second in a follow-up turn. Never silently chain.

### Signal table

| Signal class | Keywords | Sub-skill |
|---|---|---|
| **CLINICAL** | clinical trial, study design, protocol, endpoint, sample size, power, phase 1/2/3, biostatistics, eligibility, feasibility, estimand | `clinical-research` |
| **RD_FINANCE** | R&D budget, program budget, burn, runway, F&A, indirect rate, overhead, capitalize vs expense, R&D capex, portfolio ROI, rNPV | `research-finance` |
| **MARKET** | TAM, SAM, SOM, market sizing, survey design, sampling, margin of error, segmentation, competitive intelligence, market research | `market-research` |
| **PRODUCT** | user interview, JTBD, usability test, concept test, prototype test, discovery research, research repository, insight synthesis, saturation | `product-research` |

## Workflow (Matt Pocock grill discipline)

Derived from Matt Pocock''s `grill-with-docs` pattern: **explore-then-ask, one question per turn with a recommended answer, walk the decision tree depth-first, track dependencies, anchor every challenge in the research canon** (`references/` of each sub-skill).

### Step 1 — Explore before asking

Check the user''s working directory first:
- Is there a protocol draft, program ledger, TAM model, or interview guide already in the workspace?
- Does the inquiry already disambiguate the lane (e.g., "what sample size for a two-arm trial" — that''s `clinical-research`, no question needed)?
- Is there an artifact filename that resolves the lane (`protocol.json` → clinical; `program-budget.json` → finance; `tam-model.json` → market; `interview','.claude\skills\research-ops-skills\SKILL.md','8bc98c5f5e6bdfbd10fd379480242d24d73182bbbfcdacd9b01db299b5003a4a','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:research-summarizer','project_skill','skill://simplicio-runtime/research-summarizer','skill: research-summarizer','---
name: research-summarizer
description: "Structured research summarization agent skill for non-dev users. Handles academic papers, web articles, reports, and documentation. Extracts key findings, generates comparative analyses, and produces properly formatted citations. Use when: user wants to summarize a research paper, compare multiple sources, extract citations from documents, or create structured research briefs. Plugin for Claude Code, Codex, Gemini CLI, and OpenClaw."
license: MIT
metadata:
  version: 1.0.0
  author: Alireza Rezvani
  category: product
  updated: 2026-03-16
---

# Research Summarizer

> Read less. Understand more. Cite correctly.

Structured research summarization workflow that turns dense source material into actionable briefs. Built for product managers, analysts, founders, and anyone who reads more than they should have to.

Not a generic "summarize this" — a repeatable framework that extracts what matters, compares across sources, and formats citations properly.

---

## Scope — Distinct From the research/ Domain

This skill summarizes **documents the user already has** (papers, articles, reports pasted or attached). It performs no web search and needs no MCP server. It is NOT:

- `research/litreview` — academic literature *discovery* and review-guide generation (finds papers via Consensus/academic APIs)
- `research/dossier` — entity due-diligence built from live web research
- `research/notebooklm` — drives Google''s NotebookLM product UI
- `research/research` — the router for open-ended "research [topic]" requests that require searching

If the user asks you to *find* sources rather than digest supplied ones, route to the research/ domain instead.

---

## When This Skill Activates

Recognize these patterns from the user:

- "Summarize this paper / article / report"
- "What are the key findings in this document?"
- "Compare these sources"
- "Extract citations from this PDF"
- "Give me a research brief on [topic]"
- "Break down this whitepaper"
- Any request involving: summarize, research brief, literature review, citation, source comparison

If the user has a document and wants structured understanding → this skill applies.

---

## Workflow

### Workflow 1 — Single Source Summary

1. **Identify source type**
   - Academic paper → use IMRAD structure (Introduction, Methods, Results, Analysis, Discussion)
   - Web article → use claim-evidence-implication structure
   - Technical report → use executive summary structure
   - Documentation → use reference summary structure

2. **Scaffold the brief** — `python3 scripts/format_summary.py --template academic` (or `article`/`report`/`executive` per source type), then fill in every section from the source:
   ```
   Title: [exact title]
   Author(s): [names]
   Date: [publication date]
   Source Type: [paper | article | report | documentation]

   ## Key Thesis
   [1-2 sentences: the central argument or finding]

   ## Key Findings
   1. [Finding with supporting evidence]
   2. [Finding with supporting evidence]
   3. [Finding with supporting evidence]

   ## Methodology
   [How they arrived at these findings — data sources, sample size, approach]

   ## Limitations
   - [What the source doesn''t cover or gets wrong]

   ## Actionable Takeaways
   - [What to do with this information]

   ## Notable Quotes
   > "[Direct quote]" (p. X)
   ```

3. **Assess quality**
   - Source credibility (peer-reviewed, reputable outlet, primary vs secondary)
   - Evidence strength (data-backed, anecdotal, theoretical)
   - Recency (when published, still relevant?)
   - Bias indicators (funding source, author affiliation, methodology gaps)

### Workflow 2 — Multi-Source Comparison

1. **Collect sources** (2-5 documents)
2. **Summarize each** using the single-source workflow above
3. **Build comparison matrix**

   ```
   | Dimension        | Source A        | Source B        | Source C        |
   |------------------|-----------------|-----------------|-----------------|
   | Central Thesis   | ...             | ...             | ...             |
   | Methodology   ','.claude\skills\research-summarizer\SKILL.md','48977a29f52347660b78f3505eeb445588cc322de9ef42fbaca4874fe64d9542','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:resume','project_skill','skill://simplicio-runtime/resume','skill: resume','---
name: resume
description: "Resume a paused experiment. Checkout the experiment branch, read results history, continue iterating. Use when the user runs /ar:resume or asks to pick up a previously started autoresearch experiment."
command: /ar:resume
---

# /ar:resume — Resume Experiment

Resume a paused or context-limited experiment. Reads all history and continues where you left off.

## Usage

```
/ar:resume                                  # List experiments, let user pick
/ar:resume engineering/api-speed            # Resume specific experiment
```

## What It Does

### Step 1: List experiments if needed

If no experiment specified:

```bash
python {skill_path}/scripts/setup_experiment.py --list
```

Show status for each (active/paused/done based on results.tsv age). Let user pick.

### Step 2: Load full context

```bash
# Checkout the experiment branch
git checkout autoresearch/{domain}/{name}

# Read config
cat .autoresearch/{domain}/{name}/config.cfg

# Read strategy
cat .autoresearch/{domain}/{name}/program.md

# Read full results history
cat .autoresearch/{domain}/{name}/results.tsv

# Read recent git log for the branch
git log --oneline -20
```

### Step 3: Report current state

Summarize for the user:

```
Resuming: engineering/api-speed
  Target: src/api/search.py
  Metric: p50_ms (lower is better)
  Experiments: 23 total — 8 kept, 12 discarded, 3 crashed
  Best: 185ms (-42% from baseline of 320ms)
  Last experiment: "added response caching" → KEEP (185ms)

  Recent patterns:
  - Caching changes: 3 kept, 1 discarded (consistently helpful)
  - Algorithm changes: 2 discarded, 1 crashed (high risk, low reward so far)
  - I/O optimization: 2 kept (promising direction)
```

### Step 4: Ask next action

```
How would you like to continue?
  1. Single iteration (/ar:run)  — I''ll make one change and evaluate
  2. Start a loop (/ar:loop)     — Autonomous with scheduled interval
  3. Just show me the results    — I''ll review and decide
```

If the user picks loop, hand off to `/ar:loop` with the experiment pre-selected.
If single, hand off to `/ar:run`.

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\resume\SKILL.md','63cbdd79f9b3f1a045f2b3104059aaf32d804e7f083fd186cd104a5063c7fbf9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:review','project_skill','skill://simplicio-runtime/review','skill: review','---
name: review
description: "Analyze auto-memory for promotion candidates, stale entries, consolidation opportunities, and health metrics. Use when the user runs /si:review or asks what has been learned and what should be promoted or pruned."
---

# /si:review — Analyze Auto-Memory

Performs a comprehensive audit of Claude Code''s auto-memory and produces actionable recommendations.

## Usage

```
/si:review                    # Full review
/si:review --quick            # Summary only (counts + top 3 candidates)
/si:review --stale            # Focus on stale/outdated entries
/si:review --candidates       # Show only promotion candidates
```

## What It Does

### Step 1: Locate memory directory

```bash
# Find the project''s auto-memory directory
MEMORY_DIR="$HOME/.claude/projects/$(pwd | sed ''s|/|%2F|g; s|%2F|/|; s|^/||'')/memory"

# Fallback: check common path patterns
# ~/.claude/projects/<user>/<project>/memory/
# ~/.claude/projects/<absolute-path>/memory/

# List all memory files
ls -la "$MEMORY_DIR"/
```

If memory directory doesn''t exist, report that auto-memory may be disabled. Suggest checking with `/memory`.

### Step 2: Read and analyze MEMORY.md

Read the full `MEMORY.md` file. Count lines and check against the 200-line startup limit.

Analyze each entry for:

1. **Recurrence indicators**
   - Same concept appears multiple times (different wording)
   - References to "again" or "still" or "keeps happening"
   - Similar entries across topic files

2. **Staleness indicators**
   - References files that no longer exist (`find` to verify)
   - Mentions outdated tools, versions, or commands
   - Contradicts current CLAUDE.md rules

3. **Consolidation opportunities**
   - Multiple entries about the same topic (e.g., three lines about testing)
   - Entries that could merge into one concise rule

4. **Promotion candidates** — entries that meet ALL criteria:
   - Appeared in 2+ sessions (check wording patterns)
   - Not project-specific trivia (broadly useful)
   - Actionable (can be written as a concrete rule)
   - Not already in CLAUDE.md or `.claude/rules/`

### Step 3: Read topic files

If `MEMORY.md` references or the directory contains additional files (`debugging.md`, `patterns.md`, etc.):
- Read each one
- Cross-reference with MEMORY.md for duplicates
- Check for entries that belong in the main file (high value) vs. topic files (details)

### Step 4: Cross-reference with CLAUDE.md

Read the project''s `CLAUDE.md` (if it exists) and compare:
- Are there MEMORY.md entries that duplicate CLAUDE.md rules? (→ remove from memory)
- Are there MEMORY.md entries that contradict CLAUDE.md? (→ flag conflict)
- Are there MEMORY.md patterns not yet in CLAUDE.md that should be? (→ promotion candidate)

Also check `.claude/rules/` directory for existing scoped rules.

### Step 5: Generate report

Output format:

```
📊 Auto-Memory Review

Memory Health:
  MEMORY.md:        {{lines}}/200 lines ({{percent}}%)
  Topic files:      {{count}} ({{names}})
  CLAUDE.md:        {{lines}} lines
  Rules:            {{count}} files in .claude/rules/

🎯 Promotion Candidates ({{count}}):
  1. "{{pattern}}" — seen {{n}}x, applies broadly
     → Suggest: {{target}} (CLAUDE.md / .claude/rules/{{name}}.md)
  2. ...

🗑️ Stale Entries ({{count}}):
  1. Line {{n}}: "{{entry}}" — {{reason}}
  2. ...

🔄 Consolidation ({{count}} groups):
  1. Lines {{a}}, {{b}}, {{c}} all about {{topic}} → merge into 1 entry
  2. ...

⚠️ Conflicts ({{count}}):
  1. MEMORY.md line {{n}} contradicts CLAUDE.md: {{detail}}

💡 Recommendations:
  - {{actionable suggestion}}
  - {{actionable suggestion}}
```

## When to Use

- After completing a major feature or debugging session
- When `/si:status` shows MEMORY.md is over 150 lines
- Weekly during active development
- Before starting a new project phase
- After onboarding a new team member (review what Claude learned)

## Tips

- Run `/si:review --quick` frequently (low overhead)
- Full review is most valuable when MEMORY.md is getting crowded
- Act on promotion candidates promptly — they''re proven patterns
- Don''t hesitate t','.claude\skills\review\SKILL.md','658eee1acc18c0d14cded05a82b99b729cdc1a1bd3e050724beace51998b374c','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:review-legal','project_skill','skill://simplicio-runtime/review-legal','skill: review-legal','---
name: review-legal
description: >
  Review a vendor agreement, NDA, or SaaS subscription against your playbook.
  Identifies the agreement structure from titles, routes to the right review skill
  (vendor-agreement-review, nda-review, saas-msa-review), and integrates the output
  into a single memo. Use when the user says "review this contract", "check this
  MSA", "is this NDA okay", "look at this SaaS agreement", or attaches an inbound
  agreement for review.
argument-hint: ''[file path | Drive link | [CLM ID] | paste text]''
---

# /review

Reviews an inbound agreement against the playbook in `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md`. Identifies the agreement structure from titles, selects the appropriate skill(s), and — if confirm_routing is enabled — checks with the user before proceeding.

## Instructions

1. **Load `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md`.** If placeholders present, stop and prompt: "Run `/commercial-legal:cold-start-interview` first — I need to learn your playbook before I can review against it."

   Also read `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md` → `## Review preferences` → `confirm_routing`. If the field is missing, treat it as `true`.

2. **Get the agreement:** From file path, Drive link, [CLM ID], or pasted text. If none provided, ask.

3. **Read the document structure — titles first.**

   Before reading the body, extract:
   - The main agreement title (e.g., "Master Services Agreement", "Non-Disclosure Agreement")
   - All exhibit, schedule, addendum, and attachment titles (e.g., "Exhibit A — Data Processing Addendum", "Schedule 1 — Subscription Order Form", "Annex B — Service Level Agreement")

   This is the routing signal. Do not rely on body keywords alone — a 40-page MSA with "confidential" throughout is not an NDA.

4. **Select the skill(s) based on document structure.**

   Map each identified document or section to a skill:

   | Document / section title contains | Skill |
   |---|---|
   | Non-Disclosure, NDA, Confidentiality Agreement (as the *main* agreement) | **nda-review** |
   | Master Services Agreement, Professional Services, Statement of Work, Consulting Agreement | **vendor-agreement-review** |
   | Subscription, SaaS, Cloud Services, Order Form with auto-renewal, Software License with recurring fees | **saas-msa-review** (overlay on vendor-agreement-review) |
   | Data Processing Addendum, DPA, Data Processing Agreement (as exhibit or standalone) | note for **vendor-agreement-review** → data protection section |
   | Service Level Agreement, SLA (as exhibit) | note for **saas-msa-review** → SLA section |

   Multiple skills may apply. Common combinations:
   - MSA + DPA exhibit → vendor-agreement-review, with DPA noted
   - SaaS subscription + Order Form + SLA exhibit → saas-msa-review (covers all three)
   - MSA + Order Form with auto-renewal → vendor-agreement-review + saas-msa-review overlay

   When the structure is genuinely ambiguous after reading titles (e.g., a document titled "Agreement" with no exhibits listed), read the first two pages of the body to resolve it — then stop and route.

5. **Confirm routing if enabled.**

   If `confirm_routing` is `true` in `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md` (or field is absent):

   ```
   I''m going to review this as: [agreement type(s)].

   Documents identified:
   - [Main agreement title] → [skill]
   - [Exhibit A title] → [how it will be handled]
   - [Exhibit B title] → [how it will be handled]

   Sound right? (yes / no — or tell me what I got wrong)
   ```

   Wait for confirmation before proceeding. If the user corrects the routing, apply their instruction and proceed.

   If `confirm_routing` is `false`: proceed silently. Log the routing decision at the top of the review memo so the user can see what was applied.

6. **Run the skill(s).** Follow each skill''s workflow fully. If multiple skills apply, run them in sequence and integrate the output into a single memo — don''t produce separate me','.claude\skills\review-legal\SKILL.md','bf1b29c21bd7a9a072d8ed05d05a8fb06b084c62aaf36f9c5a5678833f8840b3','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:review-proposals','project_skill','skill://simplicio-runtime/review-proposals','skill: review-proposals','---
name: review-proposals
description: >
  Review and approve (or reject) pending playbook update proposals from the
  playbook-monitor agent and apply approved changes to the practice profile. Use
  when the playbook-monitor agent has surfaced proposals, when the user says
  "review playbook proposals", "what playbook updates are pending", or wants to
  step through deviation-driven playbook changes.
argument-hint: "[no arguments needed — works from the pending proposals file]"
---

# /review-proposals

Steps through pending playbook update proposals from the monitor agent and applies approved changes to `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md`.

## Instructions

1. **Load the playbook-monitor agent** and run Step 5 (review and approval flow).

2. **If no proposals file exists** or it is empty: respond *"No pending proposals. Playbook is up to date."* Do not proceed further.

3. **Present proposals one at a time.** For each, show the full proposal block and offer four options: Accept, Reject, Edit, Defer.

4. **For Accept or Edit:** show the exact diff to `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md` before writing. Only apply after the attorney explicitly confirms.

5. **For Reject or Defer:** log the decision. Do not modify `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md`.

6. **After all proposals are resolved:** show a summary of what changed, then archive the proposals file.

## Examples

```
/commercial-legal:review-proposals
```

```
/commercial-legal:review-proposals
(runs automatically after playbook-monitor notifies you)
```

<!-- Source: https://github.com/anthropics/claude-for-legal (Apache-2.0). Imported into Simplicio (lean: SKILL.md only). Area: legal. -->
','.claude\skills\review-proposals\SKILL.md','29c971bf93660ca7b9d2d655d9755628cbf426941c0635b3972210fd651004ab','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:revops','project_skill','skill://simplicio-runtime/revops','skill: revops','---
name: revops
description: "When the user wants help with revenue operations, lead lifecycle management, or marketing-to-sales handoff processes. Also use when the user mentions ''RevOps,'' ''revenue operations,'' ''lead scoring,'' ''lead routing,'' ''MQL,'' ''SQL,'' ''pipeline stages,'' ''deal desk,'' ''CRM automation,'' ''marketing-to-sales handoff,'' ''data hygiene,'' ''leads aren''t getting to sales,'' ''pipeline management,'' ''lead qualification,'' or ''when should marketing hand off to sales.'' Use this for anything involving the systems and processes that connect marketing to revenue. For cold outreach emails, see cold-email. For email drip campaigns, see emails. For pricing decisions, see pricing."
metadata:
  version: 2.0.0
---

# RevOps

You are an expert in revenue operations. Your goal is to help design and optimize the systems that connect marketing, sales, and customer success into a unified revenue engine.

## Before Starting

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Gather this context (ask if not provided):

1. **GTM motion** — Product-led (PLG), sales-led, or hybrid?
2. **ACV range** — What''s the average contract value?
3. **Sales cycle length** — Days from first touch to closed-won?
4. **Current stack** — CRM, marketing automation, scheduling, enrichment tools?
5. **Current state** — How are leads managed today? What''s working and what''s not?
6. **Goals** — Increase conversion? Reduce speed-to-lead? Fix handoff leaks? Build from scratch?

Work with whatever the user gives you. If they have a clear problem area, start there. Don''t block on missing inputs — use what you have and note what would strengthen the solution.

---

## Core Principles

### Single Source of Truth
One system of record for every lead and account. If data lives in multiple places, it will conflict. Pick a CRM as the canonical source and sync everything to it.

### Define Before Automate
Get stage definitions, scoring criteria, and routing rules right on paper before building workflows. Automating a broken process just creates broken results faster.

### Measure Every Handoff
Every handoff between teams is a potential leak. Marketing-to-sales, SDR-to-AE, AE-to-CS — each needs an SLA, a tracking mechanism, and someone accountable for follow-through.

### Revenue Team Alignment
Marketing, sales, and customer success must agree on definitions. If marketing calls something an MQL but sales won''t work it, the definition is wrong. Alignment meetings aren''t optional.

---

## Lead Lifecycle Framework

### Stage Definitions

| Stage | Entry Criteria | Exit Criteria | Owner |
|-------|---------------|---------------|-------|
| **Subscriber** | Opts in to content (blog, newsletter) | Provides company info or shows engagement | Marketing |
| **Lead** | Identified contact with basic info | Meets minimum fit criteria | Marketing |
| **MQL** | Passes fit + engagement threshold | Sales accepts or rejects within SLA | Marketing |
| **SQL** | Sales accepts and qualifies via conversation | Opportunity created or recycled | Sales (SDR/AE) |
| **Opportunity** | Budget, authority, need, timeline confirmed | Closed-won or closed-lost | Sales (AE) |
| **Customer** | Closed-won deal | Expands, renews, or churns | CS / Account Mgmt |
| **Evangelist** | High NPS, referral activity, case study | Ongoing program participation | CS / Marketing |

### MQL Definition

An MQL requires both **fit** and **engagement**:

- **Fit score** — Does this person match your ICP? (company size, industry, role, tech stack)
- **Engagement score** — Have they shown buying intent? (pricing page, demo request, multiple visits)

Neither alone is sufficient. A perfect-fit company that never engages isn''t an MQL. A student downloading every ebook isn''t an MQL.

### MQL-to-SQL Handoff SLA

Define response times and document them:
- MQL','.claude\skills\revops\SKILL.md','e7cfe62984914e73b665d8159eda61f99e7899f4c5069a1aaa5720a44dc441c6','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:risk-management-specialist','project_skill','skill://simplicio-runtime/risk-management-specialist','skill: risk-management-specialist','---
name: risk-management-specialist
description: Medical device risk management specialist implementing ISO 14971 throughout product lifecycle. Provides risk analysis, risk evaluation, risk control, and post-production information analysis. Use when user mentions risk management, ISO 14971, risk analysis, FMEA, fault tree analysis, hazard identification, risk control, risk matrix, benefit-risk analysis, residual risk, risk acceptability, or post-market risk.
---

# Risk Management Specialist

ISO 14971:2019 risk management implementation throughout the medical device lifecycle.

---

## Table of Contents

- [Risk Management Planning Workflow](#risk-management-planning-workflow)
- [Risk Analysis Workflow](#risk-analysis-workflow)
- [Risk Evaluation Workflow](#risk-evaluation-workflow)
- [Risk Control Workflow](#risk-control-workflow)
- [Post-Production Risk Management](#post-production-risk-management)
- [Risk Assessment Templates](#risk-assessment-templates)
- [Decision Frameworks](#decision-frameworks)
- [Tools and References](#tools-and-references)

---

## Risk Management Planning Workflow

Establish risk management process per ISO 14971.

### Workflow: Create Risk Management Plan

1. Define scope of risk management activities:
   - Medical device identification
   - Lifecycle stages covered
   - Applicable standards and regulations
2. Establish risk acceptability criteria:
   - Define probability categories (P1-P5)
   - Define severity categories (S1-S5)
   - Create risk matrix with acceptance thresholds
3. Assign responsibilities:
   - Risk management lead
   - Subject matter experts
   - Approval authorities
4. Define verification activities:
   - Methods for control verification
   - Acceptance criteria
5. Plan production and post-production activities:
   - Information sources
   - Review triggers
   - Update procedures
6. Obtain plan approval
7. Establish risk management file
8. **Validation:** Plan approved; acceptability criteria defined; responsibilities assigned; file established

### Risk Management Plan Content

| Section | Content | Evidence |
|---------|---------|----------|
| Scope | Device and lifecycle coverage | Scope statement |
| Criteria | Risk acceptability matrix | Risk matrix document |
| Responsibilities | Roles and authorities | RACI chart |
| Verification | Methods and acceptance | Verification plan |
| Production/Post-Production | Monitoring activities | Surveillance plan |

### Risk Acceptability Matrix (5x5)

| Probability \ Severity | Negligible | Minor | Serious | Critical | Catastrophic |
|------------------------|------------|-------|---------|----------|--------------|
| **Frequent (P5)** | Medium | High | High | Unacceptable | Unacceptable |
| **Probable (P4)** | Medium | Medium | High | High | Unacceptable |
| **Occasional (P3)** | Low | Medium | Medium | High | High |
| **Remote (P2)** | Low | Low | Medium | Medium | High |
| **Improbable (P1)** | Low | Low | Low | Medium | Medium |

### Risk Level Actions

| Level | Acceptable | Action Required |
|-------|------------|-----------------|
| Low | Yes | Document and accept; still reduce as far as possible (EU MDR) |
| Medium | After reduction AFAP | Reduce as far as possible; document why further reduction is impossible |
| High | After reduction AFAP | Reduction required; demonstrate all further options exhausted |
| Unacceptable | No | Design change mandatory |

> **EU MDR — AFAP, not ALARP:** For CE-marked devices, risks must be reduced **as far as possible (AFAP)** without economic considerations (MDR Annex I, GSPR 1–4; EN ISO 14971:2019/A11:2021 Z-annexes deviation). ALARP ("as low as reasonably practicable"), which permits cost-benefit weighing in acceptability decisions, is **not an acceptable criterion under the EU MDR** — a notified body will flag it. ISO 14971:2019 itself removed ALARP from the normative text. ALARP may persist in some non-EU jurisdictions (e.g., the UK HSE tradition); if used outside the EU, flag the deviation from EU requirements explicitly.

---

## Risk Analysis Workflow

Identify hazards and estimate','.claude\skills\risk-management-specialist\SKILL.md','bc4cb1fe1c19aa21fff08bc115dfd6bce23123ad0983375c4d1b145af6afd1fa','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:roadmap-communicator','project_skill','skill://simplicio-runtime/roadmap-communicator','skill: roadmap-communicator','---
name: roadmap-communicator
description: Use when preparing roadmap narratives, release notes, changelogs, or stakeholder updates tailored for executives, engineering teams, and customers.
---

# Roadmap Communicator

Create clear roadmap communication artifacts for internal and external stakeholders.

## When To Use

Use this skill for:
- Building roadmap presentations in different formats
- Writing stakeholder updates (board, engineering, customers)
- Producing release notes (user-facing and internal)
- Generating changelogs from git history
- Structuring feature announcements

## Roadmap Formats

1. Now / Next / Later
- Best for uncertainty and strategic flexibility.
- Communicate direction without false precision.

2. Timeline roadmap
- Best for fixed-date commitments and launch coordination.
- Requires active risk and dependency management.

3. Theme-based roadmap
- Best for outcome-led planning and cross-team alignment.
- Groups initiatives by problem space or strategic objective.

See `references/roadmap-templates.md` for templates.

## Stakeholder Update Patterns

### Board / Executive
- Outcome and risk oriented
- Focus on progress against strategic goals
- Highlight trade-offs and required decisions

### Engineering
- Scope, dependencies, and sequencing clarity
- Status, blockers, and resourcing implications

### Customers
- Value narrative and timing window
- What is available now vs upcoming
- Clear expectation setting

See `references/communication-templates.md` for reusable templates.

## Release Notes Guidance

### User-Facing Release Notes
- Lead with user value, not internal implementation details.
- Group by workflows or user jobs.
- Include migration/behavior changes explicitly.

### Internal Release Notes
- Include technical details, operational impact, and known issues.
- Capture rollout plan, rollback criteria, and monitoring notes.

## Changelog Generation

Use:
```bash
python3 scripts/changelog_generator.py --from v1.0.0 --to HEAD
```

Features:
- Reads git log range
- Parses conventional commit prefixes
- Groups entries by type (`feat`, `fix`, `chore`, etc.)
- Outputs markdown or plain text

## Feature Announcement Framework

1. Problem context
2. What changed
3. Why it matters
4. Who benefits most
5. How to get started
6. Call to action and feedback channel

## Communication Quality Checklist

- [ ] Audience-specific framing is explicit.
- [ ] Outcomes and trade-offs are clear.
- [ ] Terminology is consistent across artifacts.
- [ ] Risks and dependencies are not hidden.
- [ ] Next actions and owners are specified.

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: product-team. -->
','.claude\skills\roadmap-communicator\SKILL.md','a395c96caf3e8acad036a2a439619a2125a56bb0c1950be14b4a00145aff72da','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:run','project_skill','skill://simplicio-runtime/run','skill: run','---
name: run
description: "Run a single experiment iteration. Edit the target file, evaluate, keep or discard. Use when the user runs /ar:run or asks for one manual autoresearch iteration."
command: /ar:run
---

# /ar:run — Single Experiment Iteration

Run exactly ONE experiment iteration: review history, decide a change, edit, commit, evaluate.

## Usage

```
/ar:run engineering/api-speed              # Run one iteration
/ar:run                                     # List experiments, let user pick
```

## What It Does

### Step 1: Resolve experiment

If no experiment specified, run `python {skill_path}/scripts/setup_experiment.py --list` and ask the user to pick.

### Step 2: Load context

```bash
# Read experiment config
cat .autoresearch/{domain}/{name}/config.cfg

# Read strategy and constraints
cat .autoresearch/{domain}/{name}/program.md

# Read experiment history
cat .autoresearch/{domain}/{name}/results.tsv

# Checkout the experiment branch
git checkout autoresearch/{domain}/{name}
```

### Step 3: Decide what to try

Review results.tsv:
- What changes were kept? What pattern do they share?
- What was discarded? Avoid repeating those approaches.
- What crashed? Understand why.
- How many runs so far? (Escalate strategy accordingly)

**Strategy escalation:**
- Runs 1-5: Low-hanging fruit (obvious improvements)
- Runs 6-15: Systematic exploration (vary one parameter)
- Runs 16-30: Structural changes (algorithm swaps)
- Runs 30+: Radical experiments (completely different approaches)

### Step 4: Make ONE change

Edit only the target file specified in config.cfg. Change one thing. Keep it simple.

### Step 5: Commit and evaluate

```bash
git add {target}
git commit -m "experiment: {short description of what changed}"

python {skill_path}/scripts/run_experiment.py \
  --experiment {domain}/{name} --single
```

### Step 6: Report result

Read the script output. Tell the user:
- **KEEP**: "Improvement! {metric}: {value} ({delta} from previous best)"
- **DISCARD**: "No improvement. {metric}: {value} vs best {best}. Reverted."
- **CRASH**: "Evaluation failed: {reason}. Reverted."

### Step 7: Self-improvement check

After every 10th experiment (check results.tsv line count), update the Strategy section of program.md with patterns learned.

## Rules

- ONE change per iteration. Don''t change 5 things at once.
- NEVER modify the evaluator (evaluate.py). It''s ground truth.
- Simplicity wins. Equal performance with simpler code is an improvement.
- No new dependencies.

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\run\SKILL.md','070881f42cbe1ed82593f17a6d6f7f83e064b96a0fd595c11e7282a3f4e8aa0a','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:runbook-generator','project_skill','skill://simplicio-runtime/runbook-generator','skill: runbook-generator','---
name: runbook-generator
description: "Generate operational runbooks from a service name — deployment, incident response, maintenance, and rollback workflows. Templated structure customizable per environment. Use when documenting on-call procedures for a new service, standardizing incident response across teams, or producing runbooks before launching to production."
---

# Runbook Generator

**Tier:** POWERFUL  
**Category:** Engineering  
**Domain:** DevOps / Site Reliability Engineering

---

## Overview

Generate operational runbooks quickly from a service name, then customize for deployment, incident response, maintenance, and rollback workflows.

## Core Capabilities

- Runbook skeleton generation from a CLI
- Standard sections for start/stop/health/rollback
- Structured escalation and incident handling placeholders
- Reference templates for deployment and incident playbooks

---

## When to Use

- A service has no runbook and needs a baseline immediately
- Existing runbooks are inconsistent across teams
- On-call onboarding requires standardized operations docs
- You need repeatable runbook scaffolding for new services

---

## Quick Start

```bash
# Print runbook to stdout
python3 scripts/runbook_generator.py payments-api

# Write runbook file
python3 scripts/runbook_generator.py payments-api --owner platform --output docs/runbooks/payments-api.md
```

---

## Recommended Workflow

1. Generate the initial skeleton with `scripts/runbook_generator.py`.
2. Fill in service-specific commands and URLs.
3. Add verification checks and rollback triggers.
4. Dry-run in staging.
5. Store runbook in version control near service code.

---

## Reference Docs

- `references/runbook-templates.md`

---

## Common Pitfalls

- Missing rollback triggers or rollback commands
- Steps without expected output checks
- Stale ownership/escalation contacts
- Runbooks never tested outside of incidents

## Best Practices

1. Keep every command copy-pasteable.
2. Include health checks after every critical step.
3. Validate runbooks on a fixed review cadence.
4. Update runbook content after incidents and postmortems.

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\runbook-generator\SKILL.md','b93e770428ca386d1393e1863d05204a9bfe6ff9f3050b323566f0adb794f410','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:runtime-autonomy','project_skill','skill://simplicio-runtime/runtime-autonomy','skill: runtime-autonomy','---
name: runtime-autonomy
description: "Run Simplicio Runtime as one governed execution fabric: mapper, neural memory, skills, local model, Tokio fan-out, gates, evidence, and publication."
metadata:
  version: 1.0.0
  scope: runtime
---

# Runtime autonomy

Use this skill for multi-step runtime work and issue waves. The frontier model
decides scope and reviews evidence; Simplicio owns orientation, deterministic
mutation, leases, execution, validation, receipts, and handoff.

## Fast integrated path

1. Map the repository with `simplicio-mapper scan . --json` and wait for the
   deep index only when the selected change needs it.
2. Recall relevant neural memory and skills before reading broad source. Reuse
   the selected skill instead of regenerating a playbook.
3. Apply one AC-scoped change through `simplicio-dev-cli task` or the Runtime
   deterministic edit surface. Keep unrelated files untouched.
4. Use focused `cargo check`/tests while iterating. Do not run a release build
   until the final publication gate or a release-only behavior is required.
5. For independent work, use isolated worktrees and the governed wave engine;
   Tokio is the scheduler and `simplicio-loop` is the contract owner. Logical
   slots are not real agents: claims, leases, worktrees, heartbeats, and
   evidence must remain visible.
6. Validate the affected journey, record a receipt, feed only runtime lessons
   to Helo, then publish through PR/check/merge gates. Never close an issue from
   a partial slice or an unverified claim.

## Local-model rule

Use the provisioned local GGUF for mechanical fan-out and guided second passes,
not frontier reasoning. A model is usable only after hash validation, offline
status, and an inference smoke. If the configured model is missing, report the
fallback explicitly; an echo or dry-run receipt is not local-model evidence.

## Learning rule

After a meaningful run, persist a short, deduplicated runtime lesson with its
command, evidence path, limitation, and next action. Seeds are generated from
committed skills and validated before publication so a fresh neural database
recovers the same operating contract.
','.claude\skills\runtime-autonomy\SKILL.md','34fccf7977e198c39e92ea93efec7a25343fc32998f9d5e428d7cbdf8146734e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:ruzzy','project_skill','skill://simplicio-runtime/ruzzy','skill: ruzzy','---
name: ruzzy
type: fuzzer
description: >
  Ruzzy is a coverage-guided Ruby fuzzer by Trail of Bits.
  Use for fuzzing pure Ruby code and Ruby C extensions.
---

# Ruzzy

Ruzzy is a coverage-guided fuzzer for Ruby built on libFuzzer. It enables fuzzing both pure Ruby code and Ruby C extensions with sanitizer support for detecting memory corruption and undefined behavior.

## When to Use

Ruzzy is currently the only production-ready coverage-guided fuzzer for Ruby.

**Choose Ruzzy when:**
- Fuzzing Ruby applications or libraries
- Testing Ruby C extensions for memory safety issues
- You need coverage-guided fuzzing for Ruby code
- Working with Ruby gems that have native extensions

## Quick Start

Set up environment:
```bash
export ASAN_OPTIONS="allocator_may_return_null=1:detect_leaks=0:use_sigaltstack=0"
```

Test with the included toy example:
```bash
LD_PRELOAD=$(ruby -e ''require "ruzzy"; print Ruzzy::ASAN_PATH'') \
    ruby -e ''require "ruzzy"; Ruzzy.dummy''
```

This should quickly find a crash demonstrating that Ruzzy is working correctly.

## Installation

### Platform Support

Ruzzy supports Linux x86-64 and AArch64/ARM64. For macOS or Windows, use the [Dockerfile](https://github.com/trailofbits/ruzzy/blob/main/Dockerfile) or [development environment](https://github.com/trailofbits/ruzzy#developing).

### Prerequisites

- Linux x86-64 or AArch64/ARM64
- Recent version of clang (tested back to 14.0.0, latest release recommended)
- Ruby with gem installed

### Installation Command

Install Ruzzy with clang compiler flags:

```bash
MAKE="make --environment-overrides V=1" \
CC="/path/to/clang" \
CXX="/path/to/clang++" \
LDSHARED="/path/to/clang -shared" \
LDSHAREDXX="/path/to/clang++ -shared" \
    gem install ruzzy
```

**Environment variables explained:**
- `MAKE`: Overrides make to respect subsequent environment variables
- `CC`, `CXX`, `LDSHARED`, `LDSHAREDXX`: Ensure proper clang binaries are used for latest features

### Troubleshooting Installation

If installation fails, enable debug output:

```bash
RUZZY_DEBUG=1 gem install --verbose ruzzy
```

### Verification

Verify installation by running the toy example (see Quick Start section).

## Writing a Harness

### Fuzzing Pure Ruby Code

Pure Ruby fuzzing requires two scripts due to Ruby interpreter implementation details.

**Tracer script (`test_tracer.rb`):**

```ruby
# frozen_string_literal: true

require ''ruzzy''

Ruzzy.trace(''test_harness.rb'')
```

**Harness script (`test_harness.rb`):**

```ruby
# frozen_string_literal: true

require ''ruzzy''

def fuzzing_target(input)
  # Your code to fuzz here
  if input.length == 4
    if input[0] == ''F''
      if input[1] == ''U''
        if input[2] == ''Z''
          if input[3] == ''Z''
            raise
          end
        end
      end
    end
  end
end

test_one_input = lambda do |data|
  fuzzing_target(data)
  return 0
end

Ruzzy.fuzz(test_one_input)
```

Run with:

```bash
LD_PRELOAD=$(ruby -e ''require "ruzzy"; print Ruzzy::ASAN_PATH'') \
    ruby test_tracer.rb
```

### Fuzzing Ruby C Extensions

C extensions can be fuzzed with a single harness file, no tracer needed.

**Example harness for msgpack (`fuzz_msgpack.rb`):**

```ruby
# frozen_string_literal: true

require ''msgpack''
require ''ruzzy''

test_one_input = lambda do |data|
  begin
    MessagePack.unpack(data)
  rescue Exception
    # We''re looking for memory corruption, not Ruby exceptions
  end
  return 0
end

Ruzzy.fuzz(test_one_input)
```

Run with:

```bash
LD_PRELOAD=$(ruby -e ''require "ruzzy"; print Ruzzy::ASAN_PATH'') \
    ruby fuzz_msgpack.rb
```

### Harness Rules

| Do | Don''t |
|----|-------|
| Catch Ruby exceptions if testing C extensions | Let Ruby exceptions crash the fuzzer |
| Return 0 from test_one_input lambda | Return other values |
| Keep harness deterministic | Use randomness or time-based logic |
| Use tracer script for pure Ruby | Skip tracer for pure Ruby code |

> **See Also:** For detailed harness writing techniques, patterns for handling complex inputs,
> and advanced strategies, see the **fuzz-harness-writing** technique skill.

## C','.claude\skills\ruzzy\SKILL.md','331f99788fba9123edf87a20291d57eb41f7b59338c375087cb96a893a12b6a6','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:saas-metrics-coach','project_skill','skill://simplicio-runtime/saas-metrics-coach','skill: saas-metrics-coach','---
name: saas-metrics-coach
description: SaaS financial health advisor. Use when a user shares revenue or customer numbers, or mentions ARR, MRR, churn, LTV, CAC, NRR, or asks how their SaaS business is doing.
license: MIT
metadata:
  version: 1.0.0
  author: Abbas Mir
  category: finance
  updated: 2026-03-08
---

# SaaS Metrics Coach

Act as a senior SaaS CFO advisor. Take raw business numbers, calculate key health metrics, benchmark against industry standards, and give prioritized actionable advice in plain English.

## Step 1 — Collect Inputs

If not already provided, ask for these in a single grouped request:

- Revenue: current MRR, MRR last month, expansion MRR, churned MRR
- Customers: total active, new this month, churned this month
- Costs: sales and marketing spend, gross margin %

Work with partial data. Be explicit about what is missing and what assumptions are being made.

## Step 2 — Calculate Metrics

Run `scripts/metrics_calculator.py` with the user''s inputs. If the script is unavailable, use the formulas in `references/formulas.md`.

Always attempt to compute: ARR, MRR growth %, monthly churn rate, CAC, LTV, LTV:CAC ratio, CAC payback period, NRR.

**Additional Analysis Tools:**
- Use `scripts/quick_ratio_calculator.py` when expansion/churn MRR data is available
- Use `scripts/unit_economics_simulator.py` for forward-looking projections

## Step 3 — Benchmark Each Metric

Load `references/benchmarks.md`. For each metric show:
- The calculated value
- The relevant benchmark range for the user''s segment and stage
- A plain status label: HEALTHY / WATCH / CRITICAL

Match the benchmark tier to the user''s market segment (Enterprise / Mid-Market / SMB / PLG) and company stage (Early / Growth / Scale). Ask if unclear.

## Step 4 — Prioritize and Recommend

Identify the top 2-3 metrics at WATCH or CRITICAL status. For each one state:
- What is happening (one sentence, plain English)
- Why it matters to the business
- Two or three specific actions to take this month

Order by impact — address the most damaging problem first.

## Step 5 — Output Format

Always use this exact structure:

```
# SaaS Health Report — [Month Year]

## Metrics at a Glance
| Metric | Your Value | Benchmark | Status |
|--------|------------|-----------|--------|

## Overall Picture
[2-3 sentences, plain English summary]

## Priority Issues

### 1. [Metric Name]
What is happening: ...
Why it matters: ...
Fix it this month: ...

### 2. [Metric Name]
...

## What is Working
[1-2 genuine strengths, no padding]

## 90-Day Focus
[Single metric to move + specific numeric target]
```

## Examples

**Example 1 — Partial data**

Input: "MRR is $80k, we have 200 customers, about 3 cancel each month."

Expected output: Calculates ARPA ($400), monthly churn (1.5%), ARR ($960k), LTV estimate. Flags CAC and growth rate as missing. Asks one focused follow-up question for the most impactful missing input.

**Example 2 — Critical scenario**

Input: "MRR $22k (was $23.5k), 80 customers, lost 9, gained 6, spent $15k on ads, 65% gross margin."

Expected output: Flags negative MoM growth (-6.4%), critical churn (11.25%), and LTV:CAC of 0.64:1 as CRITICAL. Recommends churn reduction as the single highest-priority action before any further growth spend.

## Key Principles

- Be direct. If a metric is bad, say it is bad.
- Explain every metric in one sentence before showing the number.
- Cap priority issues at three. More than three paralyzes action.
- Context changes benchmarks. Five percent churn is catastrophic for Enterprise SaaS but normal for SMB/PLG. Always confirm the user''s target market before scoring.

## Reference Files

- `references/formulas.md` — All metric formulas with worked examples
- `references/benchmarks.md` — Industry benchmark ranges by stage and segment
- `assets/input-template.md` — Blank input form to share with users
- `scripts/metrics_calculator.py` — Core metrics calculator (ARR, MRR, churn, CAC, LTV, NRR)
- `scripts/quick_ratio_calculator.py` — Growth efficiency metric (Quick Ratio)
- `scripts/unit_economics_simulator.py` — 12-mon','.claude\skills\saas-metrics-coach\SKILL.md','9259e1b779bdaa509cde9e8621f495ffbe5390a61580e0faa13299695960d222','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:saas-msa-review','project_skill','skill://simplicio-runtime/saas-msa-review','skill: saas-msa-review','---
name: saas-msa-review
description: >
  Reference: review of SaaS subscription agreements with attention to the terms
  that matter most in subscription deals — auto-renewal mechanics, price escalation,
  data portability, uptime SLAs, and subprocessor rights. Loaded by
  /commercial-legal:review when a SaaS or subscription agreement is detected.
user-invocable: false
---

# SaaS / Subscription Agreement Review

## Matter context

**Matter context.** Check `## Matter workspaces` in the practice-level CLAUDE.md. If `Enabled` is `✗` (the default for in-house users), skip the rest of this paragraph — skills use practice-level context and the matter machinery is invisible. If enabled and there is no active matter, ask: "Which matter is this for? Run `/commercial-legal:matter-workspace switch <slug>` or say `practice-level`." Load the active matter''s `matter.md` for matter-specific context and overrides. Write outputs to the matter folder at `~/.claude/plugins/config/claude-for-legal/commercial-legal/matters/<matter-slug>/`. Never read another matter''s files unless `Cross-matter context` is `on`.

---

## Purpose

SaaS agreements have a distinct risk profile from one-time vendor contracts. The dollars compound over renewals, the data accumulates, and the switching cost grows every month. This skill reviews with that in mind.

It runs the standard playbook check from `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md` and adds a SaaS-specific overlay on the terms that bite hardest in subscription deals.

## Jurisdiction assumption

SaaS terms (auto-renewal notice requirements, price-escalation caps, data-portability mandates, subprocessor rules) are jurisdiction-sensitive — California, New York, and EU rules diverge materially, and some states have auto-renewal statutes that override private contract terms. This review applies the team''s positions from `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md`, which assume the governing law recorded there. If the agreement picks a different governing law, or the deal spans jurisdictions with statutory overrides (e.g., EU-based users, California consumers), flag it — the analysis may not transfer as written.

> **No silent supplement.** If a research query to the configured legal research tool (Westlaw, or firm platform) returns few or no results for a statutory override that might bear on the deal (auto-renewal statute, data-portability mandate, consumer-protection rule), report what was found and stop. Do NOT fill the gap from web search or model knowledge without asking. Say: "The search returned [N] results from [tool]. Coverage appears thin for [jurisdiction / rule]. Options: (1) broaden the search query, (2) try a different research tool, (3) search the web — results will be tagged `[web search — verify]` and should be checked against a primary source before relying, or (4) flag as unverified and stop. Which would you like?" A lawyer decides whether to accept lower-confidence sources.
>
> **Source attribution.** Where the review cites a statute, regulation, or case (e.g., a state auto-renewal law overriding contract terms), tag the citation: `[Westlaw]`, `[statute / regulator site]`, or the MCP tool name for citations retrieved from a legal research connector; `[web search — verify]` for web-search citations; `[model knowledge — verify]` for citations recalled from training data; `[user provided]` for citations from the counterparty draft or house files. Citations tagged `verify` carry higher fabrication risk and should be checked first. Never strip or collapse the tags.

## Load the playbook

**Which side?** Before applying the playbook, determine which side the company is on for this SaaS agreement. Usually obvious: if the counterparty is a SaaS vendor selling you their platform, you''re purchasing-side. If you are the SaaS vendor and the counterparty is your customer, you''re sales-side. If it''s not obvious (a reseller arrangement, a white-label deal), ask: "Which side is [company] on for this agreement — vendor or customer?" Read the m','.claude\skills\saas-msa-review\SKILL.md','44c81112d68bfc119a937f29a250215b8bdf147c80658d774a6dc2d4698556b8','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:saas-scaffolder','project_skill','skill://simplicio-runtime/saas-scaffolder','skill: saas-scaffolder','---
name: saas-scaffolder
description: "Generates complete, production-ready SaaS project boilerplate including authentication, database schemas, billing integration, API routes, and a working dashboard using Next.js 14+ App Router, TypeScript, Tailwind CSS, shadcn/ui, Drizzle ORM, and Stripe. Use when the user wants to create a new SaaS app, start a subscription-based web project, scaffold a Next.js application, or mentions terms like starter template, boilerplate, new project, or wiring up auth and payments."
---

# SaaS Scaffolder

**Tier:** POWERFUL  
**Category:** Product Team  
**Domain:** Full-Stack Development / Project Bootstrapping

---

## Input Format

```
Product: [name]
Description: [1-3 sentences]
Auth: nextauth | clerk | supabase
Database: neondb | supabase | planetscale
Payments: stripe | lemonsqueezy | none
Features: [comma-separated list]
```

---

## File Tree Output

```
my-saas/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   ├── register/page.tsx
│   │   └── layout.tsx
│   ├── (dashboard)/
│   │   ├── dashboard/page.tsx
│   │   ├── settings/page.tsx
│   │   ├── billing/page.tsx
│   │   └── layout.tsx
│   ├── (marketing)/
│   │   ├── page.tsx
│   │   ├── pricing/page.tsx
│   │   └── layout.tsx
│   ├── api/
│   │   ├── auth/[...nextauth]/route.ts
│   │   ├── webhooks/stripe/route.ts
│   │   ├── billing/checkout/route.ts
│   │   └── billing/portal/route.ts
│   └── layout.tsx
├── components/
│   ├── ui/
│   ├── auth/
│   │   ├── login-form.tsx
│   │   └── register-form.tsx
│   ├── dashboard/
│   │   ├── sidebar.tsx
│   │   ├── header.tsx
│   │   └── stats-card.tsx
│   ├── marketing/
│   │   ├── hero.tsx
│   │   ├── features.tsx
│   │   ├── pricing.tsx
│   │   └── footer.tsx
│   └── billing/
│       ├── plan-card.tsx
│       └── usage-meter.tsx
├── lib/
│   ├── auth.ts
│   ├── db.ts
│   ├── stripe.ts
│   ├── validations.ts
│   └── utils.ts
├── db/
│   ├── schema.ts
│   └── migrations/
├── hooks/
│   ├── use-subscription.ts
│   └── use-user.ts
├── types/index.ts
├── middleware.ts
├── .env.example
├── drizzle.config.ts
└── next.config.ts
```

---

## Key Component Patterns

### Auth Config (NextAuth)

```typescript
// lib/auth.ts
import { NextAuthOptions } from "next-auth"
import GoogleProvider from "next-auth/providers/google"
import { DrizzleAdapter } from "@auth/drizzle-adapter"
import { db } from "./db"

export const authOptions: NextAuthOptions = {
  adapter: DrizzleAdapter(db),
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
    }),
  ],
  callbacks: {
    session: async ({ session, user }) => ({
      ...session,
      user: {
        ...session.user,
        id: user.id,
        subscriptionStatus: user.subscriptionStatus,
      },
    }),
  },
  pages: { signIn: "/login" },
}
```

### Database Schema (Drizzle + NeonDB)

```typescript
// db/schema.ts
import { pgTable, text, timestamp, integer } from "drizzle-orm/pg-core"

export const users = pgTable("users", {
  id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
  name: text("name"),
  email: text("email").notNull().unique(),
  emailVerified: timestamp("emailVerified"),
  image: text("image"),
  stripeCustomerId: text("stripe_customer_id").unique(),
  stripeSubscriptionId: text("stripe_subscription_id"),
  stripePriceId: text("stripe_price_id"),
  stripeCurrentPeriodEnd: timestamp("stripe_current_period_end"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
})

export const accounts = pgTable("accounts", {
  userId: text("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  type: text("type").notNull(),
  provider: text("provider").notNull(),
  providerAccountId: text("provider_account_id").notNull(),
  refresh_token: text("refresh_token"),
  access_token: text("access_token"),
  expires_at: integer("expires_at"),
})
```

### Stripe Checkout Route

```typescript
// app/api/billing/checkout/route.ts
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { au','.claude\skills\saas-scaffolder\SKILL.md','723e7287c36de409cc9aad82492afc0cb165f138d505a38a754640e2d139ca80','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:sales-enablement','project_skill','skill://simplicio-runtime/sales-enablement','skill: sales-enablement','---
name: sales-enablement
description: "When the user wants to create sales collateral, pitch decks, one-pagers, objection handling docs, or demo scripts. Also use when the user mentions ''sales deck,'' ''pitch deck,'' ''one-pager,'' ''leave-behind,'' ''objection handling,'' ''deal-specific ROI analysis,'' ''demo script,'' ''talk track,'' ''sales playbook,'' ''proposal template,'' ''buyer persona card,'' ''help my sales team,'' ''sales materials,'' or ''what should I give my sales reps.'' Use this for any document or asset that helps a sales team close deals. For competitor comparison pages and battle cards, see competitors. For marketing website copy, see copywriting. For cold outreach emails, see cold-email. For the offer being sold (bonuses, guarantees, pricing structure), see offers."
metadata:
  version: 2.0.1
---

# Sales Enablement

You are an expert in B2B sales enablement. Your goal is to create sales collateral that reps actually use — decks, one-pagers, objection docs, demo scripts, and playbooks that help close deals.

## Before Starting

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Gather this context (ask if not provided):

1. **Value Proposition & Differentiators**
   - What do you sell and who is it for?
   - What makes you different from the next best alternative?
   - What outcomes can you prove?

2. **Sales Motion**
   - How do you sell? (self-serve, inside sales, field sales, hybrid)
   - Average deal size and sales cycle length
   - Key personas involved in the buying decision

3. **Collateral Needs**
   - What specific assets do you need?
   - What stage of the funnel are they for?
   - Who will use them? (AE, SDR, champion, prospect)

4. **Current State**
   - What materials exist today?
   - What''s working and what''s not?
   - What do reps ask for most?

---

## Core Principles

### Sales Uses What Sales Trusts
Involve reps in creation. Use their language, not marketing''s. If reps rewrite your deck before sending it, you wrote the wrong deck. Test drafts with your top performers first.

### Situation-Specific, Not Generic
Tailor to persona, deal stage, and use case. A deck for a CTO should look different from one for a VP of Sales. A one-pager for post-meeting follow-up serves a different purpose than one for a trade show.

### Scannable Over Comprehensive
Reps need information in 3 seconds, not 30. Use bold headers, short bullets, and visual hierarchy. If a rep can''t find the answer mid-call, the doc has failed.

### Tie Back to Business Outcomes
Every claim connects to revenue, efficiency, or risk reduction. Features mean nothing without the "so what." Replace "AI-powered analytics" with "cut reporting time by 80%."

---

## Sales Deck / Pitch Deck

### 10-12 Slide Framework

1. **Current World Problem** — The pain your buyer lives with today
2. **Cost of the Problem** — What inaction costs (time, money, risk)
3. **The Shift Happening** — Market or technology change creating urgency
4. **Your Approach** — How you solve it differently
5. **Product Walkthrough** — 3-4 key workflows, not a feature tour
6. **Proof Points** — Metrics, logos, analyst recognition
7. **Case Study** — One customer story told well
8. **Implementation / Timeline** — How they get from here to live
9. **ROI / Value** — Expected return and payback period
10. **Pricing Overview** — Transparent, tiered if applicable
11. **Next Steps / CTA** — Clear action with timeline

### Deck Principles

- **Story arc, not feature tour.** Every deck tells a story: the world has a problem, there''s a better way, here''s proof, here''s how to get there.
- **One idea per slide.** If you need two points, use two slides.
- **Design for presenting, not reading.** Slides support the conversation — they don''t replace it. Minimal text, strong visuals.

### Customization by Buyer Type

| Buyer | Emphasize | ','.claude\skills\sales-enablement\SKILL.md','bc242ebf4a1f0c0971edd9fe7d47cc8ccd400293c3041898a3aafd971867794d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:sarif-parsing','project_skill','skill://simplicio-runtime/sarif-parsing','skill: sarif-parsing','---
name: sarif-parsing
description: >-
  Parses and processes SARIF files from static analysis tools like CodeQL, Semgrep, or other
  scanners. Triggers on "parse sarif", "read scan results", "aggregate findings", "deduplicate
  alerts", or "process sarif output". Handles filtering, deduplication, format conversion, and
  CI/CD integration of SARIF data. Does NOT run scans — use the Semgrep or CodeQL skills for that.
allowed-tools: Bash Read Glob Grep
---

# SARIF Parsing Best Practices

You are a SARIF parsing expert. Your role is to help users effectively read, analyze, and process SARIF files from static analysis tools.

## When to Use

Use this skill when:
- Reading or interpreting static analysis scan results in SARIF format
- Aggregating findings from multiple security tools
- Deduplicating or filtering security alerts
- Extracting specific vulnerabilities from SARIF files
- Integrating SARIF data into CI/CD pipelines
- Converting SARIF output to other formats

## When NOT to Use

Do NOT use this skill for:
- Running static analysis scans (use CodeQL or Semgrep skills instead)
- Writing CodeQL or Semgrep rules (use their respective skills)
- Analyzing source code directly (SARIF is for processing existing scan results)
- Triaging findings without SARIF input (use variant-analysis or audit skills)

## SARIF Structure Overview

SARIF 2.1.0 is the current OASIS standard. Every SARIF file has this hierarchical structure:

```
sarifLog
├── version: "2.1.0"
├── $schema: (optional, enables IDE validation)
└── runs[] (array of analysis runs)
    ├── tool
    │   ├── driver
    │   │   ├── name (required)
    │   │   ├── version
    │   │   └── rules[] (rule definitions)
    │   └── extensions[] (plugins)
    ├── results[] (findings)
    │   ├── ruleId
    │   ├── level (error/warning/note)
    │   ├── message.text
    │   ├── locations[]
    │   │   └── physicalLocation
    │   │       ├── artifactLocation.uri
    │   │       └── region (startLine, startColumn, etc.)
    │   ├── fingerprints{}
    │   └── partialFingerprints{}
    └── artifacts[] (scanned files metadata)
```

### Why Fingerprinting Matters

Without stable fingerprints, you can''t track findings across runs:

- **Baseline comparison**: "Is this a new finding or did we see it before?"
- **Regression detection**: "Did this PR introduce new vulnerabilities?"
- **Suppression**: "Ignore this known false positive in future runs"

Tools report different paths (`/path/to/project/` vs `/github/workspace/`), so path-based matching fails. Fingerprints hash the *content* (code snippet, rule ID, relative location) to create stable identifiers regardless of environment.

## Tool Selection Guide

| Use Case | Tool | Installation |
|----------|------|--------------|
| Quick CLI queries | jq | `brew install jq` / `apt install jq` |
| Python scripting (simple) | pysarif | `pip install pysarif` |
| Python scripting (advanced) | sarif-tools | `pip install sarif-tools` |
| .NET applications | SARIF SDK | NuGet package |
| JavaScript/Node.js | sarif-js | npm package |
| Go applications | garif | `go get github.com/chavacava/garif` |
| Validation | SARIF Validator | sarifweb.azurewebsites.net |

## Strategy 1: Quick Analysis with jq

For rapid exploration and one-off queries:

```bash
# Pretty print the file
jq ''.'' results.sarif

# Count total findings
jq ''[.runs[].results[]] | length'' results.sarif

# List all rule IDs triggered
jq ''[.runs[].results[].ruleId] | unique'' results.sarif

# Extract errors only
jq ''.runs[].results[] | select(.level == "error")'' results.sarif

# Get findings with file locations
jq ''.runs[].results[] | {
  rule: .ruleId,
  message: .message.text,
  file: .locations[0].physicalLocation.artifactLocation.uri,
  line: .locations[0].physicalLocation.region.startLine
}'' results.sarif

# Filter by severity and get count per rule
jq ''[.runs[].results[] | select(.level == "error")] | group_by(.ruleId) | map({rule: .[0].ruleId, count: length})'' results.sarif

# Extract findings for a specific file
jq --arg file "src/auth.py" ''.runs[].results[] | select(.locations','.claude\skills\sarif-parsing\SKILL.md','069e0485afc27158d36bb0f22efd29b5aa89ffb4113a1b37ccb2cdc91b932aba','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:schema','project_skill','skill://simplicio-runtime/schema','skill: schema','---
name: schema
description: When the user wants to add, fix, or optimize schema markup and structured data on their site. Also use when the user mentions "schema markup," "structured data," "JSON-LD," "rich snippets," "schema.org," "FAQ schema," "product schema," "review schema," "breadcrumb schema," "Google rich results," "knowledge panel," "star ratings in search," or "add structured data." Use this whenever someone wants their pages to show enhanced results in Google. For broader SEO issues, see seo-audit. For AI search optimization, see ai-seo.
metadata:
  version: 2.0.0
---

# Schema Markup

You are an expert in structured data and schema markup. Your goal is to implement schema.org markup that helps search engines understand content and enables rich results in search.

## Initial Assessment

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Before implementing schema, understand:

1. **Page Type** - What kind of page? What''s the primary content? What rich results are possible?

2. **Current State** - Any existing schema? Errors in implementation? Which rich results already appearing?

3. **Goals** - Which rich results are you targeting? What''s the business value?

---

## Core Principles

### 1. Accuracy First
- Schema must accurately represent page content
- Don''t markup content that doesn''t exist
- Keep updated when content changes

### 2. Use JSON-LD
- Google recommends JSON-LD format
- Easier to implement and maintain
- Place in `<head>` or end of `<body>`

### 3. Follow Google''s Guidelines
- Only use markup Google supports
- Avoid spam tactics
- Review eligibility requirements

### 4. Validate Everything
- Test before deploying
- Monitor Search Console
- Fix errors promptly

---

## Common Schema Types

| Type | Use For | Required Properties |
|------|---------|-------------------|
| Organization | Company homepage/about | name, url |
| WebSite | Homepage (search box) | name, url |
| Article | Blog posts, news | headline, image, datePublished, author |
| Product | Product pages | name, image, offers |
| SoftwareApplication | SaaS/app pages | name, offers |
| FAQPage | FAQ content | mainEntity (Q&A array) |
| HowTo | Tutorials | name, step |
| BreadcrumbList | Any page with breadcrumbs | itemListElement |
| LocalBusiness | Local business pages | name, address |
| Event | Events, webinars | name, startDate, location |

**For complete JSON-LD examples**: See [references/schema-examples.md](references/schema-examples.md)

---

## Quick Reference

### Organization (Company Page)
Required: name, url
Recommended: logo, sameAs (social profiles), contactPoint

### Article/BlogPosting
Required: headline, image, datePublished, author
Recommended: dateModified, publisher, description

### Product
Required: name, image, offers (price + availability)
Recommended: sku, brand, aggregateRating, review

### FAQPage
Required: mainEntity (array of Question/Answer pairs)

### BreadcrumbList
Required: itemListElement (array with position, name, item)

---

## Multiple Schema Types

You can combine multiple schema types on one page using `@graph`:

```json
{
  "@context": "https://schema.org",
  "@graph": [
    { "@type": "Organization", ... },
    { "@type": "WebSite", ... },
    { "@type": "BreadcrumbList", ... }
  ]
}
```

---

## Validation and Testing

### Tools
- **Google Rich Results Test**: https://search.google.com/test/rich-results
- **Schema.org Validator**: https://validator.schema.org/
- **Search Console**: Enhancements reports

### Common Errors

**Missing required properties** - Check Google''s documentation for required fields

**Invalid values** - Dates must be ISO 8601, URLs fully qualified, enumerations exact

**Mismatch with page content** - Schema doesn''t match visible content

---

## Implementation

### Static Sites
- Add JSON-LD directly in','.claude\skills\schema\SKILL.md','0c90966c19418e9704d537595f5ba3e091eb3770b07d882cdda426d858ad381a','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:scrum-master','project_skill','skill://simplicio-runtime/scrum-master','skill: scrum-master','---
name: scrum-master
description: "Advanced Scrum Master skill for data-driven agile team analysis and coaching. Use when the user asks about sprint planning, velocity tracking, retrospectives, standup facilitation, backlog grooming, story points, burndown charts, blocker resolution, or agile team health. Runs Python scripts to analyse sprint JSON exports from Jira or similar tools: velocity_analyzer.py for Monte Carlo sprint forecasting, sprint_health_scorer.py for multi-dimension health scoring, and retrospective_analyzer.py for action-item and theme tracking. Produces confidence-interval forecasts, health grade reports, and improvement-velocity trends for high-performing Scrum teams."
license: MIT
metadata:
  version: 2.0.0
  author: Alireza Rezvani
  category: project-management
  domain: agile-development
  updated: 2026-02-15
  python-tools: velocity_analyzer.py, sprint_health_scorer.py, retrospective_analyzer.py
  tech-stack: scrum, agile-coaching, team-dynamics, data-analysis
---

# Scrum Master Expert

Data-driven Scrum Master skill combining sprint analytics, probabilistic forecasting, and team development coaching. The unique value is in the three Python analysis scripts and their workflows — refer to `references/` and `assets/` for deeper framework detail.

---

## Table of Contents

- [Analysis Tools & Usage](#analysis-tools-usage)
- [Input Requirements](#input-requirements)
- [Sprint Execution Workflows](#sprint-execution-workflows)
- [Team Development Workflow](#team-development-workflow)
- [Key Metrics & Targets](#key-metrics-targets)
- [Limitations](#limitations)

---

## Analysis Tools & Usage

### 1. Velocity Analyzer (`scripts/velocity_analyzer.py`)

Runs rolling averages, linear-regression trend detection, and Monte Carlo simulation over sprint history.

```bash
# Text report
python velocity_analyzer.py sprint_data.json --format text

# JSON output for downstream processing
python velocity_analyzer.py sprint_data.json --format json > analysis.json
```

**Outputs**: velocity trend (improving/stable/declining), coefficient of variation, 6-sprint Monte Carlo forecast at 50 / 70 / 85 / 95% confidence intervals, anomaly flags with root-cause suggestions.

**Validation**: If fewer than 3 sprints are present in the input, stop and prompt the user: *"Velocity analysis needs at least 3 sprints. Please provide additional sprint data."* 6+ sprints are recommended for statistically significant Monte Carlo results.

---

### 2. Sprint Health Scorer (`scripts/sprint_health_scorer.py`)

Scores team health across 6 weighted dimensions, producing an overall 0–100 grade.

| Dimension | Weight | Target |
|---|---|---|
| Commitment Reliability | 25% | >85% sprint goals met |
| Scope Stability | 20% | <15% mid-sprint changes |
| Blocker Resolution | 15% | <3 days average |
| Ceremony Engagement | 15% | >90% participation |
| Story Completion Distribution | 15% | High ratio of fully done stories |
| Velocity Predictability | 10% | CV <20% |

```bash
python sprint_health_scorer.py sprint_data.json --format text
```

**Outputs**: overall health score + grade, per-dimension scores with recommendations, sprint-over-sprint trend, intervention priority matrix.

**Validation**: Requires 2+ sprints with ceremony and story-completion data. If data is missing, report which dimensions cannot be scored and ask the user to supply the gaps.

---

### 3. Retrospective Analyzer (`scripts/retrospective_analyzer.py`)

Tracks action-item completion, recurring themes, sentiment trends, and team maturity progression.

```bash
python retrospective_analyzer.py sprint_data.json --format text
```

**Outputs**: action-item completion rate by priority/owner, recurring-theme persistence scores, team maturity level (forming/storming/norming/performing), improvement-velocity trend.

**Validation**: Requires 3+ retrospectives with action-item tracking. With fewer, note the limitation and offer partial theme analysis only.

---

## Input Requirements

All scripts accept JSON following the schema in `assets/sample_sprint_data.json`:

```json
{
  "team_','.claude\skills\scrum-master\SKILL.md','8e60a7ca3630c7ba6dba43655e406e92d84b340eae94c0cff8d233a5d1d31f3f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:seatbelt-sandboxer','project_skill','skill://simplicio-runtime/seatbelt-sandboxer','skill: seatbelt-sandboxer','---
name: seatbelt-sandboxer
description: "Generates minimal macOS Seatbelt sandbox configurations. Use when sandboxing, isolating, or restricting macOS applications with allowlist-based profiles."
allowed-tools: Read Write Bash Glob Grep
---

# macOS Seatbelt Sandbox Profiling

Generate minimally-permissioned allowlist-based Seatbelt sandbox configurations for applications.

## When to Use

- User asks to "sandbox", "isolate", or "restrict" an application on macOS
- Sandboxing any macOS process that needs restricted file/network access
- Creating defense-in-depth isolation if supply chain attacks are a concern

## When NOT to Use

- Linux containers (use seccomp-bpf, AppArmor, or namespaces instead)
- Windows applications
- Applications that legitimately need broad system access
- Quick one-off scripts where sandboxing overhead isn''t justified

## Profiling Methodology

### Step 1: Identify Application Requirements

Determine what the application needs across these resource categories:

| Category | Operations | Common Use Cases |
|----------|------------|------------------|
| **File Read** | `file-read-data`, `file-read-metadata`, `file-read-xattr`, `file-test-existence`, `file-map-executable` | Reading source files, configs, libraries |
| **File Write** | `file-write-data`, `file-write-create`, `file-write-unlink`, `file-write-mode`, `file-write-xattr`, `file-clone`, `file-link` | Output files, caches, temp files |
| **Network** | `network-bind`, `network-inbound`, `network-outbound` | Servers, API calls, package downloads |
| **Process** | `process-fork`, `process-exec`, `process-exec-interpreter`, `process-info*`, `process-codesigning*` | Spawning child processes, scripts |
| **Mach IPC** | `mach-lookup`, `mach-register`, `mach-bootstrap`, `mach-task-name` | System services, XPC, notifications |
| **POSIX IPC** | `ipc-posix-shm*`, `ipc-posix-sem*` | Shared memory, semaphores |
| **Sysctl** | `sysctl-read`, `sysctl-write` | Reading system info (CPU, memory) |
| **IOKit** | `iokit-open`, `iokit-get-properties`, `iokit-set-properties` | Hardware access, device drivers |
| **Signals** | `signal` | Signal handling between processes |
| **Pseudo-TTY** | `pseudo-tty` | Terminal emulation |
| **System** | `system-fsctl`, `system-socket`, `system-audit`, `system-info` | Low-level system calls |
| **User Prefs** | `user-preference-read`, `user-preference-write` | Reading/writing user defaults |
| **Notifications** | `darwin-notification-post`, `distributed-notification-post` | System notifications |
| **AppleEvents** | `appleevent-send` | Inter-app communication (AppleScript) |
| **Camera/Mic** | `device-camera`, `device-microphone` | Media capture |
| **Dynamic Code** | `dynamic-code-generation` | JIT compilation |
| **NVRAM** | `nvram-get`, `nvram-set`, `nvram-delete` | Firmware variables |

For each category, determine: **Needed?** and **Specific scope** (paths, services, etc.)

If the application has multiple subcommands that perform significantly different operations, such as `build` and `serve` commands for a Javascript bundler like Webpack, do the following:
* Profile the subcommands separately
* Create separate Sandbox configurations for each subcommand
* Create a helper script that acts as a drop-in replacement for the original binary, executing the sandboxed application with the appropriate Seatbelt profile according to the subcommand passed.

### Step 2: Start with Minimal Profile

Begin with deny-all and essential process operations, saved in a suitably-named Seatbelt profile file with the `.sb` extension.

```scheme
(version 1)
(deny default)

;; Essential for any process
(allow process-exec*)
(allow process-fork)
(allow sysctl-read)

;; Metadata access (stat, readdir) - doesn''t expose file contents
(allow file-read-metadata)
```

### Step 3: Add File Read Access (Allowlist)

Use `file-read-data` (not `file-read*`) for allowlist-based reads:

```scheme
(allow file-read-data
    ;; System paths (required for most runtimes)
    (subpath "/usr")
    (subpath "/bin")
    (subpath "/sbin")
    (subpath "/System")
    ','.claude\skills\seatbelt-sandboxer\SKILL.md','4c8087a547fd4998ee4e661e89f6eb1a0cfd3b4d308b426735be556307a0ce92','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:second-opinion','project_skill','skill://simplicio-runtime/second-opinion','skill: second-opinion','---
name: second-opinion
description: "Runs external LLM code reviews (OpenAI Codex or Google Gemini CLI) on uncommitted changes, branch diffs, or specific commits. Use when the user asks for a second opinion, external review, codex review, gemini review, or mentions /second-opinion."
allowed-tools: Bash Read Glob Grep AskUserQuestion
---

# Second Opinion

Shell out to external LLM CLIs for an independent code review powered by
a separate model. Supports OpenAI Codex CLI and Google Gemini CLI.

## When to Use

- Getting a second opinion on code changes from a different model
- Reviewing branch diffs before opening a PR
- Checking uncommitted work for issues before committing
- Running a focused review (security, performance, error handling)
- Comparing review output from multiple models

## When NOT to Use

- Neither Codex CLI nor Gemini CLI is installed
- No API key or subscription configured for either tool
- Reviewing non-code files (documentation, config)
- You want Claude''s own review (just ask Claude directly)

## Safety Note

Gemini CLI is invoked with `--yolo`, which auto-approves all
tool calls without confirmation. This is required for headless
(non-interactive) operation but means Gemini will execute any
tool actions its extensions request without prompting.

## Quick Reference

```
# Codex (headless exec with structured JSON output)
codex exec --sandbox read-only --ephemeral \
  --output-schema codex-review-schema.json \
  -o "$output_file" - < "$prompt_file"

# Gemini (code review extension)
gemini -p "/code-review" --yolo -e code-review
# Gemini (headless with diff — see references/ for full pattern)
git diff HEAD > /tmp/review-diff.txt
{ printf ''%s\n\n'' ''Review this diff for issues.''; cat /tmp/review-diff.txt; } \
  | gemini -p - --yolo -m gemini-3.1-pro-preview
```

## Invocation

### 1. Gather context interactively

Use `AskUserQuestion` to collect review parameters in one shot.
Adapt the questions based on what the user already provided
in their invocation (skip questions they already answered).

Combine all applicable questions into a single `AskUserQuestion`
call (max 4 questions).

**Question 1 — Tool** (skip if user already specified):

```
header: "Review tool"
question: "Which tool should run the review?"
options:
  - "Both Codex and Gemini (Recommended)" → run both in parallel
  - "Codex only"                          → codex exec
  - "Gemini only"                         → gemini CLI
```

**Question 2 — Scope** (skip if user already specified):

```
header: "Review scope"
question: "What should be reviewed?"
options:
  - "Uncommitted changes" → git diff HEAD + untracked files
  - "Branch diff vs main" → git diff <branch>...HEAD (auto-detect default branch)
  - "Specific commit"     → git diff <sha>~1..<sha> (follow up for SHA)
```

**Question 3 — Project context** (skip if neither CLAUDE.md nor AGENTS.md exists):

Check for CLAUDE.md first, then AGENTS.md in the repo root.
Only show this question if at least one exists.

```
header: "Project context"
question: "Include project conventions file so the review
  checks against your standards?"
options:
  - "Yes, include it"
  - "No, standard review"
```

**Question 4 — Review focus** (always ask):

```
header: "Review focus"
question: "Any specific focus areas for the review?"
options:
  - "General review"    → no custom prompt
  - "Security & auth"   → security-focused prompt
  - "Performance"       → performance-focused prompt
  - "Error handling"    → error handling-focused prompt
```

### 2. Run the tool directly

Do not pre-check tool availability. Run the selected tool
immediately. If the command fails with "command not found" or
an extension is missing, report the install command from the
Error Handling table below and skip that tool (if "Both" was
selected, run only the available one).

## Diff Preview

After collecting answers, show the diff stats:

```bash
# For uncommitted (tracked + untracked):
git diff --stat HEAD
git ls-files --others --exclude-standard

# For branch diff:
git diff --stat <branch>...HEAD

# For specific commit:
git d','.claude\skills\second-opinion\SKILL.md','3c6627a1362cbaab10a3401962d9b1f5443bcc404c67ff7d8742cc281694f8c1','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:secrets-vault-manager','project_skill','skill://simplicio-runtime/secrets-vault-manager','skill: secrets-vault-manager','---
name: secrets-vault-manager
description: "Use when the user asks to set up secret management infrastructure, integrate HashiCorp Vault, configure cloud secret stores (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager), implement secret rotation, or audit secret access patterns."
---

# Secrets Vault Manager

**Tier:** POWERFUL
**Category:** Engineering
**Domain:** Security / Infrastructure / DevOps

---

## Overview

Production secret infrastructure management for teams running HashiCorp Vault, cloud-native secret stores, or hybrid architectures. This skill covers policy authoring, auth method configuration, automated rotation, dynamic secrets, audit logging, and incident response.

**Distinct from env-secrets-manager** which handles local `.env` file hygiene and leak detection. This skill operates at the infrastructure layer — Vault clusters, cloud KMS, certificate authorities, and CI/CD secret injection.

### When to Use

- Standing up a new Vault cluster or migrating to a managed secret store
- Designing auth methods for services, CI runners, and human operators
- Implementing automated credential rotation (database, API keys, certificates)
- Auditing secret access patterns for compliance (SOC 2, ISO 27001, HIPAA)
- Responding to a secret leak that requires mass revocation
- Integrating secrets into Kubernetes workloads or CI/CD pipelines

---

## HashiCorp Vault Patterns

### Architecture Decisions

| Decision | Recommendation | Rationale |
|----------|---------------|-----------|
| Deployment mode | HA with Raft storage | No external dependency, built-in leader election |
| Auto-unseal | Cloud KMS (AWS KMS / Azure Key Vault / GCP KMS) | Eliminates manual unseal, enables automated restarts |
| Namespaces | One per environment (dev/staging/prod) | Blast-radius isolation, independent policies |
| Audit devices | File + syslog (dual) | Vault refuses requests if all audit devices fail — dual prevents outages |

### Auth Methods

**AppRole** — Machine-to-machine authentication for services and batch jobs.

```hcl
# Enable AppRole
path "auth/approle/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Application-specific role
vault write auth/approle/role/payment-service \
  token_ttl=1h \
  token_max_ttl=4h \
  secret_id_num_uses=1 \
  secret_id_ttl=10m \
  token_policies="payment-service-read"
```

**Kubernetes** — Pod-native authentication via service account tokens.

```hcl
vault write auth/kubernetes/role/api-server \
  bound_service_account_names=api-server \
  bound_service_account_namespaces=production \
  policies=api-server-secrets \
  ttl=1h
```

**OIDC** — Human operator access via SSO provider (Okta, Azure AD, Google Workspace).

```hcl
vault write auth/oidc/role/engineering \
  bound_audiences="vault" \
  allowed_redirect_uris="https://vault.example.com/ui/vault/auth/oidc/oidc/callback" \
  user_claim="email" \
  oidc_scopes="openid,profile,email" \
  policies="engineering-read" \
  ttl=8h
```

### Secret Engines

| Engine | Use Case | TTL Strategy |
|--------|----------|-------------|
| KV v2 | Static secrets (API keys, config) | Versioned, manual rotation |
| Database | Dynamic DB credentials | 1h default, 24h max |
| PKI | TLS certificates | 90d leaf certs, 5y intermediate CA |
| Transit | Encryption-as-a-service | Key rotation every 90d |
| SSH | Signed SSH certificates | 30m for interactive, 8h for automation |

### Policy Design

Follow least-privilege with path-based granularity:

```hcl
# payment-service-read policy
path "secret/data/production/payment/*" {
  capabilities = ["read"]
}

path "database/creds/payment-readonly" {
  capabilities = ["read"]
}

# Deny access to admin paths explicitly
path "sys/*" {
  capabilities = ["deny"]
}
```

**Policy naming convention:** `{service}-{access-level}` (e.g., `payment-service-read`, `api-gateway-admin`).

---

## Cloud Secret Store Integration

### Comparison Matrix

| Feature | AWS Secrets Manager | Azure Key Vault | GCP Secret Manager |
|---------|--------------------|-----------------|--------------------|
| Rotation | Bu','.claude\skills\secrets-vault-manager\SKILL.md','1cd0fde0988069a717a0b536fa8629ada851e2594a95b0f2f979f09a65b31cdb','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:secure-workflow-guide','project_skill','skill://simplicio-runtime/secure-workflow-guide','skill: secure-workflow-guide','---
name: secure-workflow-guide
description: Guides through Trail of Bits'' 5-step secure development workflow. Runs Slither scans, checks special features (upgradeability/ERC conformance/token integration), generates visual security diagrams, helps document security properties for fuzzing/verification, and reviews manual security areas.
---

# Secure Workflow Guide

## Purpose

Guides through Trail of Bits'' secure development workflow - a 5-step process to enhance smart contract security throughout development.

**Use this**: On every check-in, before deployment, or when you want a security review

---

## The 5-Step Workflow

Covers a security workflow including:

### Step 1: Check for Known Security Issues
Run Slither with 70+ built-in detectors to find common vulnerabilities:
- Parse findings by severity
- Explain each issue with file references
- Recommend fixes
- Help triage false positives

**Goal**: Clean Slither report or documented triages

### Step 2: Check Special Features
Detect and validate applicable features:
- **Upgradeability**: slither-check-upgradeability (17 upgrade risks)
- **ERC conformance**: slither-check-erc (6 common specs)
- **Token integration**: Recommend token-integration-analyzer skill
- **Security properties**: slither-prop for ERC20

**Note**: Only runs checks that apply to your codebase

### Step 3: Visual Security Inspection
Generate 3 security diagrams:
- **Inheritance graph**: Identify shadowing and C3 linearization issues
- **Function summary**: Show visibility and access controls
- **Variables and authorization**: Map who can write to state variables

Review each diagram for security concerns

### Step 4: Document Security Properties
Help document critical security properties:
- State machine transitions and invariants
- Access control requirements
- Arithmetic constraints and precision
- External interaction safety
- Standards conformance

Then set up testing:
- **Echidna**: Property-based fuzzing with invariants
- **Manticore**: Formal verification with symbolic execution
- **Custom Slither checks**: Project-specific business logic

**Note**: Most important activity for security

### Step 5: Manual Review Areas
Analyze areas automated tools miss:
- **Privacy**: On-chain secrets, commit-reveal needs
- **Front-running**: Slippage protection, ordering risks, MEV
- **Cryptography**: Weak randomness, signature issues, hash collisions
- **DeFi interactions**: Oracle manipulation, flash loans, protocol assumptions

Search codebase for these patterns and flag risks

For detailed instructions, commands, and explanations for each step, see [WORKFLOW_STEPS.md](resources/WORKFLOW_STEPS.md).

---

## How I Work

When invoked, I will:

1. **Explore your codebase** to understand structure
2. **Run Step 1**: Slither security scan
3. **Detect and run Step 2**: Special feature checks (only what applies)
4. **Generate Step 3**: Visual security diagrams
5. **Guide Step 4**: Security property documentation
6. **Analyze Step 5**: Manual review areas
7. **Provide action plan**: Prioritized fixes and next steps

Adapts based on:
- What tools you have installed
- What''s applicable to your project
- Where you are in development

---

## Rationalizations (Do Not Skip)

| Rationalization | Why It''s Wrong | Required Action |
|-----------------|----------------|-----------------|
| "Slither not available, I''ll check manually" | Manual checking misses 70+ detector patterns | Install and run Slither, or document why it''s blocked |
| "Can''t generate diagrams, I''ll describe the architecture" | Descriptions aren''t visual - diagrams reveal patterns text misses | Execute slither --print commands, generate actual visual outputs |
| "No upgrades detected, skip upgradeability checks" | Proxies and upgrades are often implicit or planned | Verify with codebase search before skipping Step 2 checks |
| "Not a token, skip ERC checks" | Tokens can be integrated without obvious ERC inheritance | Check for token interactions, transfers, balances before skipping |
| "Can''t set up Echidna now, suggesting it for later" | Property-','.claude\skills\secure-workflow-guide\SKILL.md','a347da10ea7039dd07f5aebd70d9e663f222ea872b027a9a12d4d938cc4217ea','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:security-guidance','project_skill','skill://simplicio-runtime/security-guidance','skill: security-guidance','---
name: security-guidance
description: PreToolUse security-anti-pattern hook for Claude Code. Catches 12 common security risks (command injection, XSS, SQL injection, unsafe deserialization, GitHub Actions workflow injection, eval/new Function code injection) BEFORE the Edit/Write/MultiEdit operation completes. Session-state caching prevents duplicate warnings on the same file+rule combo. Stdlib only — no dependencies. Use when you want a safety net during Claude Code sessions that touch security-sensitive code (auth, payments, user input handling, IaC). Disable with ENABLE_SECURITY_REMINDER=0 if you need to perform a verified-safe operation that would otherwise trip a pattern. Triggers — "add security hook", "block unsafe code", "detect command injection before write", "prevent SQL injection patterns", "security warning hook".
---

# Security Guidance Hook

**A PreToolUse hook that blocks 12 common security anti-patterns before Claude Code writes them.**

This skill is a **hook**, not a slash command. Once installed, it runs automatically before every `Edit`, `Write`, or `MultiEdit` operation and warns + blocks if it detects a known dangerous pattern.

## What It Catches

The hook scans both:

- **The file path being edited** — flags GitHub Actions workflow files with risky `${{ }}` patterns
- **The content being written** — substring matches against 11 anti-patterns

| Pattern | Category | Risk |
|---|---|---|
| GitHub Actions workflow expressions | Path-based | Workflow command injection via untrusted inputs |
| `child_process.exec`, `exec(`, `execSync(` | Substring | Node.js command injection |
| `new Function` | Substring | JS code injection |
| `eval(` | Substring | JS code injection |
| `dangerouslySetInnerHTML` | Substring | React XSS |
| `document.write` | Substring | DOM XSS |
| `.innerHTML =` | Substring | DOM XSS |
| `pickle` | Substring | Python deserialization RCE |
| `os.system`, `from os import system` | Substring | Python command injection |
| `shell=True` (subprocess) | Substring | Python command injection |
| f-string SQL or `.format` SQL | Substring | SQL injection |
| `yaml.load(`, `yaml.unsafe_load` | Substring | YAML deserialization RCE |

## How It Works

1. Claude Code is about to run `Edit`, `Write`, or `MultiEdit`
2. PreToolUse hook fires → invokes `security_reminder_hook.py` with the tool input as JSON on stdin
3. The hook extracts file_path + content + checks against the pattern table
4. If a pattern matches AND this warning hasn''t been shown for this file+rule in this session:
   - Print the warning to stderr (Claude sees it)
   - Exit code 2 → blocks the tool call
   - Save the warning key to `~/.claude/security_warnings_state_<session>.json`
5. If a pattern matches BUT the warning was already shown this session:
   - Allow the tool call (exit code 0) — Claude already saw the warning once
6. If no pattern matches:
   - Allow the tool call (exit code 0)

## Installation

This plugin ships as a Claude Code plugin with `hooks.json` wiring:

```bash
# In Claude Code:
/plugin marketplace add alirezarezvani/claude-skills
/plugin install security-guidance@claude-code-skills
```

Once installed, no further configuration needed — the hook runs automatically.

## Configuration

Disable per-session via environment variable:

```bash
ENABLE_SECURITY_REMINDER=0 claude
# Hook is bypassed for this session
```

Use sparingly — the hook is most useful exactly when you''re tempted to disable it (because you''re under deadline pressure to ship something you know is sketchy).

## Per-File Override Pattern

If a specific file legitimately needs `eval()` or `pickle` (e.g., a sandboxed REPL, a deliberately unsafe parser for a fuzzer), document it in the file with a comment:

```python
# SAFETY: pickle is the required serialization format for this internal tool.
# This file does NOT accept untrusted input. See SECURITY.md for boundary analysis.
import pickle
```

The hook will still warn on first edit per session. After acknowledging, subsequent edits in the same session are allowed (session-state caching).

## Wh','.claude\skills\security-guidance\SKILL.md','4e621c9ec0a69da17012ef80d5e0ef6796bbd22ddb61a03ead490a78e2fa01ef','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:security-pen-testing','project_skill','skill://simplicio-runtime/security-pen-testing','skill: security-pen-testing','---
name: security-pen-testing
description: "Use when the user asks to perform security audits, penetration testing, vulnerability scanning, OWASP Top 10 checks, or offensive security assessments. Covers static analysis, dependency scanning, secret detection, API security testing, and pen test report generation."
---

# Security Penetration Testing

Hands-on offensive security testing skill for finding vulnerabilities before attackers do. This is NOT compliance checking (see senior-secops) or security policy writing (see senior-security) — this is about systematic vulnerability discovery through authorized testing.

---

## Table of Contents

- [Overview](#overview)
- [OWASP Top 10 Systematic Audit](#owasp-top-10-systematic-audit)
- [Static Analysis](#static-analysis)
- [Dependency Vulnerability Scanning](#dependency-vulnerability-scanning)
- [Secret Scanning](#secret-scanning)
- [API Security Testing](#api-security-testing)
- [Web Vulnerability Testing](#web-vulnerability-testing)
- [Infrastructure Security](#infrastructure-security)
- [Pen Test Report Generation](#pen-test-report-generation)
- [Responsible Disclosure Workflow](#responsible-disclosure-workflow)
- [Workflows](#workflows)
- [Anti-Patterns](#anti-patterns)
- [Cross-References](#cross-references)

---

## Overview

### What This Skill Does

This skill provides the methodology, checklists, and automation for **offensive security testing** — actively probing systems to discover exploitable vulnerabilities. It covers web applications, APIs, infrastructure, and supply chain security.

### Distinction from Other Security Skills

| Skill | Focus | Approach |
|-------|-------|----------|
| **security-pen-testing** (this) | Finding vulnerabilities | Offensive — simulate attacker techniques |
| senior-secops | Security operations | Defensive — monitoring, incident response, SIEM |
| senior-security | Security policy | Governance — policies, frameworks, risk registers |
| skill-security-auditor | CI/CD gates | Automated — pre-merge security checks |

### Prerequisites

All testing described here assumes **written authorization** from the system owner. Unauthorized testing is illegal under the CFAA and equivalent laws worldwide. Always obtain a signed scope-of-work or rules-of-engagement document before starting.

---

## OWASP Top 10 Systematic Audit

Use the vulnerability scanner tool for automated checklist generation:

```bash
# Generate OWASP checklist for a web application
python scripts/vulnerability_scanner.py --target web --scope full

# Quick API-focused scan
python scripts/vulnerability_scanner.py --target api --scope quick --json
```

### Quick Reference

| # | Category | Key Tests |
|---|----------|-----------|
| A01 | Broken Access Control | IDOR, vertical escalation, CORS, JWT claim manipulation, forced browsing |
| A02 | Cryptographic Failures | TLS version, password hashing, hardcoded keys, weak PRNG |
| A03 | Injection | SQLi, NoSQLi, command injection, template injection, XSS |
| A04 | Insecure Design | Rate limiting, business logic abuse, multi-step flow bypass |
| A05 | Security Misconfiguration | Default credentials, debug mode, security headers, directory listing |
| A06 | Vulnerable Components | Dependency audit (npm/pip/go), EOL checks, known CVEs |
| A07 | Auth Failures | Brute force, session cookie flags, session invalidation, MFA bypass |
| A08 | Integrity Failures | Unsafe deserialization, SRI checks, CI/CD pipeline integrity |
| A09 | Logging Failures | Auth event logging, sensitive data in logs, alerting thresholds |
| A10 | SSRF | Internal IP access, cloud metadata endpoints, DNS rebinding |

```bash
# Audit dependencies
python scripts/dependency_auditor.py --file package.json --severity high
python scripts/dependency_auditor.py --file requirements.txt --json
```

See [owasp_top_10_checklist.md](references/owasp_top_10_checklist.md) for detailed test procedures, code patterns to detect, remediation steps, and CVSS scoring guidance for each category.

---

## Static Analysis

**Recommended tools:** CodeQL (custom queries for project-spec','.claude\skills\security-pen-testing\SKILL.md','6d3d5cfc6943ed4e24f0ebc493de834aa8a9ed0996644be9db4f1c5882aeabad','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:self-eval','project_skill','skill://simplicio-runtime/self-eval','skill: self-eval','---
name: self-eval
description: "Honestly evaluate AI work quality using a two-axis scoring system. Use after completing a task, code review, or work session to get an unbiased assessment. Detects score inflation, forces devil''s advocate reasoning, and persists scores across sessions."
license: "MIT"
---

# Self-Eval: Honest Work Evaluation

ultrathink

**Tier:** STANDARD
**Category:** Engineering / Quality
**Dependencies:** None (prompt-only, no external tools required)

## Description

Self-eval is a Claude Code skill that produces honest, calibrated work evaluations. It replaces the default AI tendency to rate everything 4/5 with a structured two-axis scoring system, mandatory devil''s advocate reasoning, and cross-session anti-inflation detection.

The core insight: AI self-assessment converges to "everything is a 4" because a single-axis score conflates task difficulty with execution quality. Self-eval separates these axes, then combines them via a fixed matrix that the model cannot override.

## Features

- **Two-axis scoring** — Independently rates task ambition (Low/Medium/High) and execution quality (Poor/Adequate/Strong), then combines via a lookup matrix
- **Mandatory devil''s advocate** — Before finalizing, must argue for both higher AND lower scores, then resolve the tension
- **Score persistence** — Appends scores to `.self-eval-scores.jsonl` in the working directory, building history across sessions
- **Anti-inflation detection** — Reads past scores and flags clustering (4+ of last 5 identical)
- **Matrix-locked scoring** — The composite score comes from the matrix, not from direct selection. Low ambition caps at 2/5 regardless of execution quality

## Usage

After completing work in a Claude Code session:

```
/self-eval
```

With context about what to evaluate:

```
/self-eval the authentication refactor we just completed
```

The skill reviews the conversation history, identifies what was accomplished, scores it on both axes, runs the devil''s advocate check, and appends the result to the score history file.

## Examples

### Example 1: Feature Implementation

```
/self-eval added pagination to the user list API
```

Output:
```
## Self-Evaluation

**Task:** Added cursor-based pagination to the user list API endpoint
**Ambition:** Medium — New feature with established patterns, but required careful backwards compatibility
**Execution:** Strong — All tests pass, handles edge cases, existing clients unaffected

**Devil''s Advocate:**
- Lower: Pagination is well-documented. The pattern was copied from another endpoint with minor changes. Could argue Low ambition.
- Higher: The backwards-compat requirement made this harder than a greenfield implementation. Had to support both offset and cursor modes.
- Resolution: Medium ambition holds — the backwards-compat constraint added real complexity beyond copy-paste.

**Score: 4** — Solid execution on meaningful work with real constraints.
```

### Example 2: Bug Fix

```
/self-eval
```

Output:
```
## Self-Evaluation

**Task:** Fixed race condition in the checkout flow causing duplicate orders
**Ambition:** Medium — Required debugging across 3 services to find the root cause
**Execution:** Adequate — Fix works but the test only covers the exact scenario reported, not the general class of race conditions

**Devil''s Advocate:**
- Lower: The fix was a single line (adding a mutex). Once found, it was trivial.
- Higher: Finding the root cause across 3 services took real investigation. The mutex placement required understanding the full flow.
- Resolution: Medium ambition is correct for the investigation, but execution drops to Adequate — a more thorough fix would address the pattern, not just the instance.

**Score: 3** — Good debugging work but the fix is narrow.
```

---

## What to Evaluate

$ARGUMENTS

If no arguments provided, review the full conversation history to identify what was accomplished this session. Summarize the work in one sentence before scoring.

## How to Score — Two-Axis Model

Score on two independent axes, then combine using the matrix. Do NOT pick','.claude\skills\self-eval\SKILL.md','460ecbd8b12c8da8889666e0caf5996110d0359195964ca6987eb13e2ce7b34b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:self-improving-agent','project_skill','skill://simplicio-runtime/self-improving-agent','skill: self-improving-agent','---
name: self-improving-agent
description: "Curate Claude Code''s auto-memory into durable project knowledge. Analyze MEMORY.md for patterns, promote proven learnings to CLAUDE.md and .claude/rules/, extract recurring solutions into reusable skills. Use when: (1) reviewing what Claude has learned about your project, (2) graduating a pattern from notes to enforced rules, (3) turning a debugging solution into a skill, (4) checking memory health and capacity."
---

# Self-Improving Agent

> Auto-memory captures. This plugin curates.

Claude Code''s auto-memory (v2.1.32+) automatically records project patterns, debugging insights, and your preferences in `MEMORY.md`. This plugin adds the intelligence layer: it analyzes what Claude has learned, promotes proven patterns into project rules, and extracts recurring solutions into reusable skills.

## Quick Reference

| Command | What it does |
|---------|-------------|
| `/si:review` | Analyze MEMORY.md — find promotion candidates, stale entries, consolidation opportunities |
| `/si:promote` | Graduate a pattern from MEMORY.md → CLAUDE.md or `.claude/rules/` |
| `/si:extract` | Turn a proven pattern into a standalone skill |
| `/si:status` | Memory health dashboard — line counts, topic files, recommendations |
| `/si:remember` | Explicitly save important knowledge to auto-memory |

## How It Fits Together

```
┌─────────────────────────────────────────────────────────┐
│                  Claude Code Memory Stack                │
├─────────────┬──────────────────┬────────────────────────┤
│  CLAUDE.md  │   Auto Memory    │   Session Memory       │
│  (you write)│   (Claude writes)│   (Claude writes)      │
│  Rules &    │   MEMORY.md      │   Conversation logs    │
│  standards  │   + topic files  │   + continuity         │
│  Full load  │   First 200 lines│   Contextual load      │
├─────────────┴──────────────────┴────────────────────────┤
│              ↑ /si:promote        ↑ /si:review          │
│         Self-Improving Agent (this plugin)               │
│              ↓ /si:extract    ↓ /si:remember            │
├─────────────────────────────────────────────────────────┤
│  .claude/rules/    │    New Skills    │   Error Logs     │
│  (scoped rules)    │    (extracted)   │   (auto-captured)│
└─────────────────────────────────────────────────────────┘
```

## Installation

### Claude Code (Plugin)
```
/plugin marketplace add alirezarezvani/claude-skills
/plugin install self-improving-agent@claude-code-skills
```

### OpenClaw
```bash
clawhub install self-improving-agent
```

### Codex CLI
```bash
./scripts/codex-install.sh --skill self-improving-agent
```

## Memory Architecture

### Where things live

| File | Who writes | Scope | Loaded |
|------|-----------|-------|--------|
| `./CLAUDE.md` | You (+ `/si:promote`) | Project rules | Full file, every session |
| `~/.claude/CLAUDE.md` | You | Global preferences | Full file, every session |
| `~/.claude/projects/<path>/memory/MEMORY.md` | Claude (auto) | Project learnings | First 200 lines |
| `~/.claude/projects/<path>/memory/*.md` | Claude (overflow) | Topic-specific notes | On demand |
| `.claude/rules/*.md` | You (+ `/si:promote`) | Scoped rules | When matching files open |

### The promotion lifecycle

```
1. Claude discovers pattern → auto-memory (MEMORY.md)
2. Pattern recurs 2-3x → /si:review flags it as promotion candidate
3. You approve → /si:promote graduates it to CLAUDE.md or rules/
4. Pattern becomes an enforced rule, not just a note
5. MEMORY.md entry removed → frees space for new learnings
```

## Core Concepts

### Auto-memory is capture, not curation

Auto-memory is excellent at recording what Claude learns. But it has no judgment about:
- Which learnings are temporary vs. permanent
- Which patterns should become enforced rules
- When the 200-line limit is wasting space on stale entries
- Which solutions are good enough to become reusable skills

That''s what this plugin does.

### Promotion = graduation

When you promote a learning, it moves from Claude''s scratchpad (MEMORY.md) to your project''s rule system (CL','.claude\skills\self-improving-agent\SKILL.md','8fc3f7b142adde3f03cc545770719f5f470b0715c0329faf7b1be7f54f77eaba','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:semgrep','project_skill','skill://simplicio-runtime/semgrep','skill: semgrep','---
name: semgrep
description: >-
  Run Semgrep static analysis scan on a codebase using parallel subagents.
  Supports two scan modes — "run all" (full ruleset coverage) and "important
  only" (high-confidence security vulnerabilities). Automatically detects and
  uses Semgrep Pro for cross-file taint analysis when available. Use when asked
  to scan code for vulnerabilities, run a security audit with Semgrep, find
  bugs, or perform static analysis. Spawns parallel workers for multi-language
  codebases.
allowed-tools: Bash Read Glob Task AskUserQuestion TaskCreate TaskList TaskUpdate
---

# Semgrep Security Scan

Run a Semgrep scan with automatic language detection, parallel execution via Task subagents, and merged SARIF output.

## Essential Principles

1. **Always use `--metrics=off`** — Semgrep sends telemetry by default; `--config auto` also phones home. Every `semgrep` command must include `--metrics=off` to prevent data leakage during security audits.
2. **User must approve the scan plan (Step 3 is a hard gate)** — The original "scan this codebase" request is NOT approval. Present exact rulesets, target, engine, and mode; wait for explicit "yes"/"proceed" before spawning scanners.
3. **Third-party rulesets are required, not optional** — Trail of Bits, 0xdea, and Decurity rules catch vulnerabilities absent from the official registry. Include them whenever the detected language matches.
4. **Spawn all scan Tasks in a single message** — Parallel execution is the core performance advantage. Never spawn Tasks sequentially; always emit all Task tool calls in one response.
5. **Always check for Semgrep Pro before scanning** — Pro enables cross-file taint tracking and catches ~250% more true positives. Skipping the check means silently missing critical inter-file vulnerabilities.

## When to Use

- Security audit of a codebase
- Finding vulnerabilities before code review
- Scanning for known bug patterns
- First-pass static analysis

## When NOT to Use

- Binary analysis → Use binary analysis tools
- Already have Semgrep CI configured → Use existing pipeline
- Need cross-file analysis but no Pro license → Consider CodeQL as alternative
- Creating custom Semgrep rules → Use `semgrep-rule-creator` skill
- Porting existing rules to other languages → Use `semgrep-rule-variant-creator` skill

## Output Directory

All scan results, SARIF files, and temporary data are stored in a single output directory.

- **If the user specifies an output directory** in their prompt, use it as `OUTPUT_DIR`.
- **If not specified**, default to `./static_analysis_semgrep_1`. If that already exists, increment to `_2`, `_3`, etc.

In both cases, **always create the directory** with `mkdir -p` before writing any files.

```bash
# Resolve output directory
if [ -n "$USER_SPECIFIED_DIR" ]; then
  OUTPUT_DIR="$USER_SPECIFIED_DIR"
else
  BASE="static_analysis_semgrep"
  N=1
  while [ -e "${BASE}_${N}" ]; do
    N=$((N + 1))
  done
  OUTPUT_DIR="${BASE}_${N}"
fi
mkdir -p "$OUTPUT_DIR/raw" "$OUTPUT_DIR/results"
```

The output directory is resolved **once** at the start of Step 1 and used throughout all subsequent steps.

```
$OUTPUT_DIR/
├── rulesets.txt                 # Approved rulesets (logged after Step 3)
├── raw/                         # Per-scan raw output (unfiltered)
│   ├── python-python.json
│   ├── python-python.sarif
│   ├── python-django.json
│   ├── python-django.sarif
│   └── ...
└── results/                     # Final merged output
    └── results.sarif
```

## Prerequisites

**Required:** Semgrep CLI (`semgrep --version`). If not installed, see [Semgrep installation docs](https://semgrep.dev/docs/getting-started/).

**Optional:** Semgrep Pro — enables cross-file taint tracking, inter-procedural analysis, and additional languages (Apex, C#, Elixir). Check with:

```bash
semgrep --pro --validate --config p/default 2>/dev/null && echo "Pro available" || echo "OSS only"
```

**Limitations:** OSS mode cannot track data flow across files. Pro mode uses `-j 1` for cross-file analysis (slower per ruleset, but parallel rulesets compensate).
','.claude\skills\semgrep\SKILL.md','1cde197714647ca00ced363f1fc406399a0dc46fa0b697764b6d15ab50f47876','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:semgrep-rule-creator','project_skill','skill://simplicio-runtime/semgrep-rule-creator','skill: semgrep-rule-creator','---
name: semgrep-rule-creator
description: Creates custom Semgrep rules for detecting security vulnerabilities, bug patterns, and code patterns. Use when writing Semgrep rules or building custom static analysis detections.
allowed-tools: Bash Read Write Edit Glob Grep WebFetch
---

# Semgrep Rule Creator

Create production-quality Semgrep rules with proper testing and validation.

## When to Use

**Ideal scenarios:**
- Writing Semgrep rules for specific bug patterns
- Writing rules to detect security vulnerabilities in your codebase
- Writing taint mode rules for data flow vulnerabilities
- Writing rules to enforce coding standards

## When NOT to Use

Do NOT use this skill for:
- Running existing Semgrep rulesets
- General static analysis without custom rules (use `static-analysis` skill)

## Rationalizations to Reject

When writing Semgrep rules, reject these common shortcuts:

- **"The pattern looks complete"** → Still run `semgrep --test --config <rule-id>.yaml <rule-id>.<ext>` to verify. Untested rules have hidden false positives/negatives.
- **"It matches the vulnerable case"** → Matching vulnerabilities is half the job. Verify safe cases don''t match (false positives break trust).
- **"Taint mode is overkill for this"** → If data flows from user input to a dangerous sink, taint mode gives better precision than pattern matching.
- **"One test is enough"** → Include edge cases: different coding styles, sanitized inputs, safe alternatives, and boundary conditions.
- **"I''ll optimize the patterns first"** → Write correct patterns first, optimize after all tests pass. Premature optimization causes regressions.
- **"The AST dump is too complex"** → The AST reveals exactly how Semgrep sees code. Skipping it leads to patterns that miss syntactic variations.

## Anti-Patterns

**Too broad** - matches everything, useless for detection:
```yaml
# BAD: Matches any function call
pattern: $FUNC(...)

# GOOD: Specific dangerous function
pattern: eval(...)
```

**Missing safe cases in tests** - leads to undetected false positives:
```python
# BAD: Only tests vulnerable case
# ruleid: my-rule
dangerous(user_input)

# GOOD: Include safe cases to verify no false positives
# ruleid: my-rule
dangerous(user_input)

# ok: my-rule
dangerous(sanitize(user_input))

# ok: my-rule
dangerous("hardcoded_safe_value")
```

**Overly specific patterns** - misses variations:
```yaml
# BAD: Only matches exact format
pattern: os.system("rm " + $VAR)

# GOOD: Matches all os.system calls with taint tracking
mode: taint
pattern-sources:
  - pattern: input(...)
pattern-sinks:
  - pattern: os.system(...)
```

## Strictness Level

This workflow is **strict** - do not skip steps:
- **Read documentation first**: See [Documentation](#documentation) before writing Semgrep rules
- **Test-first is mandatory**: Never write a rule without tests
- **100% test pass is required**: "Most tests pass" is not acceptable
- **Optimization comes last**: Only simplify patterns after all tests pass
- **Avoid generic patterns**: Rules must be specific, not match broad patterns
- **Prioritize taint mode**: For data flow vulnerabilities
- **One YAML file - one Semgrep rule**: Each YAML file must contain only one Semgrep rule; don''t combine multiple rules in a single file
- **No generic rules**: When targeting a specific language for Semgrep rules - avoid generic pattern matching (`languages: generic`)
- **Forbidden `todook` and `todoruleid` test annotations**: `todoruleid: <rule-id>` and `todook: <rule-id>` annotations in tests files for future rule improvements are forbidden

## Overview

This skill guides creation of Semgrep rules that detect security vulnerabilities and code patterns. Rules are created iteratively: analyze the problem, write tests first, analyze AST structure, write the rule, iterate until all tests pass, optimize the rule.

**Approach selection:**
- **Taint mode** (prioritize): Data flow issues where untrusted input reaches dangerous sinks
- **Pattern matching**: Simple syntactic patterns without data flow requirements

**Why prioritize taint mode?** Pattern','.claude\skills\semgrep-rule-creator\SKILL.md','e7727088d665fd2203ad29d0935ed753459ff033fcf3c21201e46d4770f58d5c','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:semgrep-rule-variant-creator','project_skill','skill://simplicio-runtime/semgrep-rule-variant-creator','skill: semgrep-rule-variant-creator','---
name: semgrep-rule-variant-creator
description: Creates language variants of existing Semgrep rules. Use when porting a Semgrep rule to specified target languages. Takes an existing rule and target languages as input, produces independent rule+test directories for each language.
allowed-tools: Bash Read Write Edit Glob Grep WebFetch
---

# Semgrep Rule Variant Creator

Port existing Semgrep rules to new target languages with proper applicability analysis and test-driven validation.

## When to Use

**Ideal scenarios:**
- Porting an existing Semgrep rule to one or more target languages
- Creating language-specific variants of a universal vulnerability pattern
- Expanding rule coverage across a polyglot codebase
- Translating rules between languages with equivalent constructs

## When NOT to Use

Do NOT use this skill for:
- Creating a new Semgrep rule from scratch (use `semgrep-rule-creator` instead)
- Running existing rules against code
- Languages where the vulnerability pattern fundamentally doesn''t apply
- Minor syntax variations within the same language

## Input Specification

This skill requires:
1. **Existing Semgrep rule** - YAML file path or YAML rule content
2. **Target languages** - One or more languages to port to (e.g., "Golang and Java")

## Output Specification

For each applicable target language, produces:
```
<original-rule-id>-<language>/
├── <original-rule-id>-<language>.yaml     # Ported Semgrep rule
└── <original-rule-id>-<language>.<ext>    # Test file with annotations
```

Example output for porting `sql-injection` to Go and Java:
```
sql-injection-golang/
├── sql-injection-golang.yaml
└── sql-injection-golang.go

sql-injection-java/
├── sql-injection-java.yaml
└── sql-injection-java.java
```

## Rationalizations to Reject

When porting Semgrep rules, reject these common shortcuts:

| Rationalization | Why It Fails | Correct Approach |
|-----------------|--------------|------------------|
| "Pattern structure is identical" | Different ASTs across languages | Always dump AST for target language |
| "Same vulnerability, same detection" | Data flow differs between languages | Analyze target language idioms |
| "Rule doesn''t need tests since original worked" | Language edge cases differ | Write NEW test cases for target |
| "Skip applicability - it obviously applies" | Some patterns are language-specific | Complete applicability analysis first |
| "I''ll create all variants then test" | Errors compound, hard to debug | Complete full cycle per language |
| "Library equivalent is close enough" | Surface similarity hides differences | Verify API semantics match |
| "Just translate the syntax 1:1" | Languages have different idioms | Research target language patterns |

## Strictness Level

This workflow is **strict** - do not skip steps:
- **Applicability analysis is mandatory**: Don''t assume patterns translate
- **Each language is independent**: Complete full cycle before moving to next
- **Test-first for each variant**: Never write a rule without test cases
- **100% test pass required**: "Most tests pass" is not acceptable

## Overview

This skill guides the creation of language-specific variants of existing Semgrep rules. Each target language goes through an independent 4-phase cycle:

```
FOR EACH target language:
  Phase 1: Applicability Analysis → Verdict
  Phase 2: Test Creation (Test-First)
  Phase 3: Rule Creation
  Phase 4: Validation
  (Complete full cycle before moving to next language)
```

## Foundational Knowledge

**The `semgrep-rule-creator` skill is the authoritative reference for Semgrep rule creation fundamentals.** While this skill focuses on porting existing rules to new languages, the core principles of writing quality rules remain the same.

Consult `semgrep-rule-creator` for guidance on:
- **When to use taint mode vs pattern matching** - Choosing the right approach for the vulnerability type
- **Test-first methodology** - Why tests come before rules and how to write effective test cases
- **Anti-patterns to avoid** - Common mistakes like overly broad or overly specific patterns','.claude\skills\semgrep-rule-variant-creator\SKILL.md','e43a8bea9a0bda6a298e0a9bae543fac6f69bcce01c01ed5bfdf5a295e5d3bb1','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:senior-architect','project_skill','skill://simplicio-runtime/senior-architect','skill: senior-architect','---
name: senior-architect
description: This skill should be used when the user asks to "design system architecture", "evaluate microservices vs monolith", "create architecture diagrams", "analyze dependencies", "choose a database", "plan for scalability", "make technical decisions", or "review system design". Use for architecture decision records (ADRs), tech stack evaluation, system design reviews, dependency analysis, and generating architecture diagrams in Mermaid, PlantUML, or ASCII format.
---

# Senior Architect

Architecture design and analysis tools for making informed technical decisions.

## Table of Contents

- [Quick Start](#quick-start)
- [Tools Overview](#tools-overview)
  - [Architecture Diagram Generator](#1-architecture-diagram-generator)
  - [Dependency Analyzer](#2-dependency-analyzer)
  - [Project Architect](#3-project-architect)
- [Decision Workflows](#decision-workflows)
  - [Database Selection](#database-selection-workflow)
  - [Architecture Pattern Selection](#architecture-pattern-selection-workflow)
  - [Monolith vs Microservices](#monolith-vs-microservices-decision)
- [Reference Documentation](#reference-documentation)
- [Tech Stack Coverage](#tech-stack-coverage)
- [Common Commands](#common-commands)

---

## Quick Start

```bash
# Generate architecture diagram from project
python scripts/architecture_diagram_generator.py ./my-project --format mermaid

# Analyze dependencies for issues
python scripts/dependency_analyzer.py ./my-project --output json

# Get architecture assessment
python scripts/project_architect.py ./my-project --verbose
```

---

## Tools Overview

### 1. Architecture Diagram Generator

Generates architecture diagrams from project structure in multiple formats.

**Solves:** "I need to visualize my system architecture for documentation or team discussion"

**Input:** Project directory path
**Output:** Diagram code (Mermaid, PlantUML, or ASCII)

**Supported diagram types:**
- `component` - Shows modules and their relationships
- `layer` - Shows architectural layers (presentation, business, data)
- `deployment` - Shows deployment topology

**Usage:**
```bash
# Mermaid format (default)
python scripts/architecture_diagram_generator.py ./project --format mermaid --type component

# PlantUML format
python scripts/architecture_diagram_generator.py ./project --format plantuml --type layer

# ASCII format (terminal-friendly)
python scripts/architecture_diagram_generator.py ./project --format ascii

# Save to file
python scripts/architecture_diagram_generator.py ./project -o architecture.md
```

**Example output (Mermaid):**
```mermaid
graph TD
    A[API Gateway] --> B[Auth Service]
    A --> C[User Service]
    B --> D[(PostgreSQL)]
    C --> D
```

---

### 2. Dependency Analyzer

Analyzes project dependencies for coupling, circular dependencies, and outdated packages.

**Solves:** "I need to understand my dependency tree and identify potential issues"

**Input:** Project directory path
**Output:** Analysis report (JSON or human-readable)

**Analyzes:**
- Dependency tree (direct and transitive)
- Circular dependencies between modules
- Coupling score (0-100)
- Outdated packages

**Supported package managers:**
- npm/yarn (`package.json`)
- Python (`requirements.txt`, `pyproject.toml`)
- Go (`go.mod`)
- Rust (`Cargo.toml`)

**Usage:**
```bash
# Human-readable report
python scripts/dependency_analyzer.py ./project

# JSON output for CI/CD integration
python scripts/dependency_analyzer.py ./project --output json

# Check only for circular dependencies
python scripts/dependency_analyzer.py ./project --check circular

# Verbose mode with recommendations
python scripts/dependency_analyzer.py ./project --verbose
```

**Example output:**
```
Dependency Analysis Report
==========================
Total dependencies: 47 (32 direct, 15 transitive)
Coupling score: 72/100 (moderate)

Issues found:
- CIRCULAR: auth → user → permissions → auth
- OUTDATED: lodash 4.17.15 → 4.17.21 (security)

Recommendations:
1. Extract shared interface to break circular dependency
2. Update lodash to fix CVE-2020-820','.claude\skills\senior-architect\SKILL.md','18e18c59794e2ca9caeed87ed6510afdaf01d3167458caeffb521697d759a8ad','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:senior-computer-vision','project_skill','skill://simplicio-runtime/senior-computer-vision','skill: senior-computer-vision','---
name: senior-computer-vision
description: Computer vision engineering skill for object detection, image segmentation, and visual AI systems. Covers CNN and Vision Transformer architectures, YOLO/Faster R-CNN/DETR detection, Mask R-CNN/SAM segmentation, and production deployment with ONNX/TensorRT. Includes PyTorch, torchvision, Ultralytics, Detectron2, and MMDetection frameworks. Use when building detection pipelines, training custom models, optimizing inference, or deploying vision systems.
---

# Senior Computer Vision Engineer

Production computer vision engineering skill for object detection, image segmentation, and visual AI system deployment.

## Table of Contents

- [Quick Start](#quick-start)
- [Core Expertise](#core-expertise)
- [Tech Stack](#tech-stack)
- [Workflow 1: Object Detection Pipeline](#workflow-1-object-detection-pipeline)
- [Workflow 2: Model Optimization and Deployment](#workflow-2-model-optimization-and-deployment)
- [Workflow 3: Custom Dataset Preparation](#workflow-3-custom-dataset-preparation)
- [Architecture Selection Guide](#architecture-selection-guide)
- [Reference Documentation](#reference-documentation)

## Quick Start

```bash
# Generate training configuration for YOLO or Faster R-CNN
python scripts/vision_model_trainer.py models/ --task detection --arch yolov8

# Analyze model for optimization opportunities (quantization, pruning)
python scripts/inference_optimizer.py model.pt --target onnx --benchmark

# Build dataset pipeline with augmentations
python scripts/dataset_pipeline_builder.py images/ --format coco --augment
```

## Core Expertise

This skill provides guidance on:

- **Object Detection**: YOLO family (v5-v11), Faster R-CNN, DETR, RT-DETR
- **Instance Segmentation**: Mask R-CNN, YOLACT, SOLOv2
- **Semantic Segmentation**: DeepLabV3+, SegFormer, SAM (Segment Anything)
- **Image Classification**: ResNet, EfficientNet, Vision Transformers (ViT, DeiT)
- **Video Analysis**: Object tracking (ByteTrack, SORT), action recognition
- **3D Vision**: Depth estimation, point cloud processing, NeRF
- **Production Deployment**: ONNX, TensorRT, OpenVINO, CoreML

## Tech Stack

| Category | Technologies |
|----------|--------------|
| Frameworks | PyTorch, torchvision, timm |
| Detection | Ultralytics (YOLO), Detectron2, MMDetection |
| Segmentation | segment-anything, mmsegmentation |
| Optimization | ONNX, TensorRT, OpenVINO, torch.compile |
| Image Processing | OpenCV, Pillow, albumentations |
| Annotation | CVAT, Label Studio, Roboflow |
| Experiment Tracking | MLflow, Weights & Biases |
| Serving | Triton Inference Server, TorchServe |

## Workflow 1: Object Detection Pipeline

Use this workflow when building an object detection system from scratch.

### Step 1: Define Detection Requirements

Analyze the detection task requirements:

```
Detection Requirements Analysis:
- Target objects: [list specific classes to detect]
- Real-time requirement: [yes/no, target FPS]
- Accuracy priority: [speed vs accuracy trade-off]
- Deployment target: [cloud GPU, edge device, mobile]
- Dataset size: [number of images, annotations per class]
```

### Step 2: Select Detection Architecture

Choose architecture based on requirements:

| Requirement | Recommended Architecture | Why |
|-------------|-------------------------|-----|
| Real-time (>30 FPS) | YOLOv8/v11, RT-DETR | Single-stage, optimized for speed |
| High accuracy | Faster R-CNN, DINO | Two-stage, better localization |
| Small objects | YOLO + SAHI, Faster R-CNN + FPN | Multi-scale detection |
| Edge deployment | YOLOv8n, MobileNetV3-SSD | Lightweight architectures |
| Transformer-based | DETR, DINO, RT-DETR | End-to-end, no NMS required |

### Step 3: Prepare Dataset

Convert annotations to required format:

```bash
# COCO format (recommended)
python scripts/dataset_pipeline_builder.py data/images/ \
    --annotations data/labels/ \
    --format coco \
    --split 0.8 0.1 0.1 \
    --output data/coco/

# Verify dataset
python -c "from pycocotools.coco import COCO; coco = COCO(''data/coco/train.json''); print(f''Images: {len(coco.imgs)}, Catego','.claude\skills\senior-computer-vision\SKILL.md','09aae335320327122c86985725a89e467da9b7cc67b71e74d9c14f96e5cbdd2d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:senior-data-engineer','project_skill','skill://simplicio-runtime/senior-data-engineer','skill: senior-data-engineer','---
name: senior-data-engineer
description: Data engineering skill for building scalable data pipelines, ETL/ELT systems, and data infrastructure. Expertise in Python, SQL, Spark, Airflow, dbt, Kafka, and modern data stack. Includes data modeling, pipeline orchestration, data quality, and DataOps. Use when designing data architectures, building data pipelines, optimizing data workflows, implementing data governance, or troubleshooting data issues.
---

# Senior Data Engineer

Production-grade data engineering skill for building scalable, reliable data systems.

## Table of Contents

1. [Trigger Phrases](#trigger-phrases)
2. [Quick Start](#quick-start)
3. [Workflows](#workflows)
4. [Architecture Decision Framework](#architecture-decision-framework)
5. [Tech Stack](#tech-stack)
6. [Reference Documentation](#reference-documentation)
7. [Troubleshooting](#troubleshooting)

---

## Trigger Phrases

Activate this skill when you see:

**Pipeline Design:**
- "Design a data pipeline for..."
- "Build an ETL/ELT process..."
- "How should I ingest data from..."
- "Set up data extraction from..."

**Architecture:**
- "Should I use batch or streaming?"
- "Lambda vs Kappa architecture"
- "How to handle late-arriving data"
- "Design a data lakehouse"

**Data Modeling:**
- "Create a dimensional model..."
- "Star schema vs snowflake"
- "Implement slowly changing dimensions"
- "Design a data vault"

**Data Quality:**
- "Add data validation to..."
- "Set up data quality checks"
- "Monitor data freshness"
- "Implement data contracts"

**Performance:**
- "Optimize this Spark job"
- "Query is running slow"
- "Reduce pipeline execution time"
- "Tune Airflow DAG"

---

## Quick Start

### Core Tools

```bash
# Generate pipeline orchestration config
python scripts/pipeline_orchestrator.py generate \
  --type airflow \
  --source postgres \
  --destination snowflake \
  --schedule "0 5 * * *"

# Validate data quality
python scripts/data_quality_validator.py validate \
  --input data/sales.parquet \
  --schema schemas/sales.json \
  --checks freshness,completeness,uniqueness

# Optimize ETL performance
python scripts/etl_performance_optimizer.py analyze \
  --query queries/daily_aggregation.sql \
  --engine spark \
  --recommend
```

---

## Workflows
→ See references/workflows.md for details

## Architecture Decision Framework

Use this framework to choose the right approach for your data pipeline.

### Batch vs Streaming

| Criteria | Batch | Streaming |
|----------|-------|-----------|
| **Latency requirement** | Hours to days | Seconds to minutes |
| **Data volume** | Large historical datasets | Continuous event streams |
| **Processing complexity** | Complex transformations, ML | Simple aggregations, filtering |
| **Cost sensitivity** | More cost-effective | Higher infrastructure cost |
| **Error handling** | Easier to reprocess | Requires careful design |

**Decision Tree:**
```
Is real-time insight required?
├── Yes → Use streaming
│   └── Is exactly-once semantics needed?
│       ├── Yes → Kafka + Flink/Spark Structured Streaming
│       └── No → Kafka + consumer groups
└── No → Use batch
    └── Is data volume > 1TB daily?
        ├── Yes → Spark/Databricks
        └── No → dbt + warehouse compute
```

### Lambda vs Kappa Architecture

| Aspect | Lambda | Kappa |
|--------|--------|-------|
| **Complexity** | Two codebases (batch + stream) | Single codebase |
| **Maintenance** | Higher (sync batch/stream logic) | Lower |
| **Reprocessing** | Native batch layer | Replay from source |
| **Use case** | ML training + real-time serving | Pure event-driven |

**When to choose Lambda:**
- Need to train ML models on historical data
- Complex batch transformations not feasible in streaming
- Existing batch infrastructure

**When to choose Kappa:**
- Event-sourced architecture
- All processing can be expressed as stream operations
- Starting fresh without legacy systems

### Data Warehouse vs Data Lakehouse

| Feature | Warehouse (Snowflake/BigQuery) | Lakehouse (Delta/Iceberg) |
|---------|-------------------------------|---------------------------','.claude\skills\senior-data-engineer\SKILL.md','e331ad86ca4ed9fbdfdfe1aed696245228e5a00236007c71f8cf564addeb65a0','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:senior-data-scientist','project_skill','skill://simplicio-runtime/senior-data-scientist','skill: senior-data-scientist','---
name: senior-data-scientist
description: World-class senior data scientist skill specialising in statistical modeling, experiment design, causal inference, and predictive analytics. Covers A/B testing (sample sizing, two-proportion z-tests, Bonferroni correction), difference-in-differences, feature engineering pipelines (Scikit-learn, XGBoost), cross-validated model evaluation (AUC-ROC, AUC-PR, SHAP), and MLflow experiment tracking — using Python (NumPy, Pandas, Scikit-learn), R, and SQL. Use when designing or analysing controlled experiments, building and evaluating classification or regression models, performing causal analysis on observational data, engineering features for structured tabular datasets, or translating statistical findings into data-driven business decisions.
---

# Senior Data Scientist

World-class senior data scientist skill for production-grade AI/ML/Data systems.

## Core Workflows

### 1. Design an A/B Test

```python
import numpy as np
from scipy import stats

def calculate_sample_size(baseline_rate, mde, alpha=0.05, power=0.8):
    """
    Calculate required sample size per variant.
    baseline_rate: current conversion rate (e.g. 0.10)
    mde: minimum detectable effect (relative, e.g. 0.05 = 5% lift)
    """
    p1 = baseline_rate
    p2 = baseline_rate * (1 + mde)
    effect_size = abs(p2 - p1) / np.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / 2)
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    z_beta = stats.norm.ppf(power)
    n = ((z_alpha + z_beta) / effect_size) ** 2
    return int(np.ceil(n))

def analyze_experiment(control, treatment, alpha=0.05):
    """
    Run two-proportion z-test and return structured results.
    control/treatment: dicts with ''conversions'' and ''visitors''.
    """
    p_c = control["conversions"] / control["visitors"]
    p_t = treatment["conversions"] / treatment["visitors"]
    pooled = (control["conversions"] + treatment["conversions"]) / (control["visitors"] + treatment["visitors"])
    se = np.sqrt(pooled * (1 - pooled) * (1 / control["visitors"] + 1 / treatment["visitors"]))
    z = (p_t - p_c) / se
    p_value = 2 * (1 - stats.norm.cdf(abs(z)))
    ci_low = (p_t - p_c) - stats.norm.ppf(1 - alpha / 2) * se
    ci_high = (p_t - p_c) + stats.norm.ppf(1 - alpha / 2) * se
    return {
        "lift": (p_t - p_c) / p_c,
        "p_value": p_value,
        "significant": p_value < alpha,
        "ci_95": (ci_low, ci_high),
    }

# --- Experiment checklist ---
# 1. Define ONE primary metric and pre-register secondary metrics.
# 2. Calculate sample size BEFORE starting: calculate_sample_size(0.10, 0.05)
# 3. Randomise at the user (not session) level to avoid leakage.
# 4. Run for at least 1 full business cycle (typically 2 weeks).
# 5. Check for sample ratio mismatch: abs(n_control - n_treatment) / expected < 0.01
# 6. Analyze with analyze_experiment() and report lift + CI, not just p-value.
# 7. Apply Bonferroni correction if testing multiple metrics: alpha / n_metrics
```

### 2. Build a Feature Engineering Pipeline

```python
import pandas as pd
import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.compose import ColumnTransformer

def build_feature_pipeline(numeric_cols, categorical_cols, date_cols=None):
    """
    Returns a fitted-ready ColumnTransformer for structured tabular data.
    """
    numeric_pipeline = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale",  StandardScaler()),
    ])
    categorical_pipeline = Pipeline([
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    transformers = [
        ("num", numeric_pipeline, numeric_cols),
        ("cat", categorical_pipeline, categorical_cols),
    ]
    return ColumnTransformer(transformers, remainder="drop")

def add_time_features(df, date_col):
    """Extract cyclical and lag features from a datetime column."""
    df = df.copy()
    df[date_col] = pd.to_','.claude\skills\senior-data-scientist\SKILL.md','56a905e35374f50133d4bcc46718d88732cec627a840c3904e99f1c1a36f2b77','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:senior-devops','project_skill','skill://simplicio-runtime/senior-devops','skill: senior-devops','---
name: senior-devops
description: Comprehensive DevOps skill for CI/CD, infrastructure automation, containerization, and cloud platforms (AWS, GCP, Azure). Includes pipeline setup, infrastructure as code, deployment automation, and monitoring. Use when setting up pipelines, deploying applications, managing infrastructure, implementing monitoring, or optimizing deployment processes.
---

# Senior Devops

Complete toolkit for senior devops with modern tools and best practices.

## Quick Start

### Main Capabilities

This skill provides three core capabilities through automated scripts:

```bash
# Script 1: Pipeline Generator — scaffolds CI/CD pipelines for GitHub Actions or CircleCI
python scripts/pipeline_generator.py ./app --platform=github --stages=build,test,deploy

# Script 2: Terraform Scaffolder — generates and validates IaC modules for AWS/GCP/Azure
python scripts/terraform_scaffolder.py ./infra --provider=aws --module=ecs-service --verbose

# Script 3: Deployment Manager — generates deployment manifests + runbooks with rollback support
python3 scripts/deployment_manager.py deploy --env=staging --image=app:1.2.3 --strategy=blue-green --verbose --json
```

## Core Capabilities

### 1. Pipeline Generator

Scaffolds CI/CD pipeline configurations for GitHub Actions or CircleCI, with stages for build, test, security scan, and deploy.

**Example — GitHub Actions workflow:**
```yaml
# .github/workflows/ci.yml
name: CI/CD Pipeline
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: ''20''
          cache: ''npm''
      - run: npm ci
      - run: npm run lint
      - run: npm test -- --coverage
      - name: Upload coverage
        uses: codecov/codecov-action@v4

  build-docker:
    needs: build-and-test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build and push image
        uses: docker/build-push-action@v5
        with:
          push: ${{ github.ref == ''refs/heads/main'' }}
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}

  deploy:
    needs: build-docker
    if: github.ref == ''refs/heads/main''
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster production \
            --service app-service \
            --force-new-deployment
```

**Usage:**
```bash
python scripts/pipeline_generator.py <project-path> --platform=github|circleci --stages=build,test,deploy
```

### 2. Terraform Scaffolder

Generates, validates, and plans Terraform modules. Enforces consistent module structure and runs `terraform validate` + `terraform plan` before any apply.

**Example — AWS ECS service module:**
```hcl
# modules/ecs-service/main.tf
resource "aws_ecs_task_definition" "app" {
  family                   = var.service_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory

  container_definitions = jsonencode([{
    name      = var.service_name
    image     = var.container_image
    essential = true
    portMappings = [{
      containerPort = var.container_port
      protocol      = "tcp"
    }]
    environment = [for k, v in var.env_vars : { name = k, value = v }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = "/ecs/${var.service_name}"
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

resource "aws_ecs_service" "app" {
  name            = var.service_name
  cluster         = var.cluster_id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = fals','.claude\skills\senior-devops\SKILL.md','47957bff477a1edc4afdf547a754fc5c6d672aa0ba89e5caf485539a0d724ed2','skill,simplicio,coding',1.3);
