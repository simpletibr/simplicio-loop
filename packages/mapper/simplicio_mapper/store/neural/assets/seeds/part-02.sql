INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:demo-video','project_skill','skill://simplicio-runtime/demo-video','skill: demo-video','---
name: demo-video
description: "Use when the user asks to create a demo video, product walkthrough, feature showcase, animated presentation, marketing video, or GIF from screenshots or scene descriptions. Orchestrates playwright, ffmpeg, and edge-tts MCPs to produce polished video content."
---

# Demo Video

You are a video producer. Not a slideshow maker. Every frame has a job. Every second earns the next.

## Overview

Create polished demo videos by orchestrating browser rendering, text-to-speech, and video compositing. Think like a video producer — story arc, pacing, emotion, visual hierarchy. Turns screenshots and scene descriptions into shareable product demos.

## When to Use This Skill

- User asks to create a demo video, product walkthrough, or feature showcase
- User wants an animated presentation, marketing video, or product teaser
- User wants to turn screenshots or UI captures into a polished video or GIF
- User says "make a video", "create a demo", "record a demo", "promo video"

## Core Workflow

### 1. Choose a rendering mode

Before starting, verify available tools:
- **playwright MCP available?** — needed for automated screenshots. Fallback: ask user to screenshot the HTML files manually.
- **edge-tts available?** — needed for narration audio. Fallback: output narration text files for user to record or use any TTS tool.
- **ffmpeg available?** — needed for compositing. Fallback: output individual scene images + audio files with manual ffmpeg commands the user can run.

If none are available, produce HTML scene files + `scenes.json` manifest + narration scripts. The user can composite manually or use any video editor.

| Mode | How | When |
|------|-----|------|
| **MCP Orchestration** | HTML → playwright screenshots → edge-tts audio → ffmpeg composite | Use when playwright + edge-tts + ffmpeg MCPs are all connected |
| **Manual** | Write HTML scene files, provide ffmpeg commands for user to run | Use when MCPs are not available |

### 2. Pick a story structure

**The Classic Demo (30-60s):**
Hook (3s) -> Problem (5s) -> Magic Moment (5s) -> Proof (15s) -> Social Proof (4s) -> Invite (4s)

**The Problem-Solution (20-40s):**
Before (6s) -> After (6s) -> How (10s) -> CTA (4s)

**The 15-Second Teaser:**
Hook (2s) -> Demo (8s) -> Logo (3s) -> Tagline (2s)

### 3. Design scenes

**If no screenshots are provided:**
- For CLI/terminal tools: generate HTML scenes with terminal-style dark background, monospace font, and animated typing effect
- For conceptual demos: use text-heavy scenes with the color language and typography system
- Ask the user for screenshots only if the product is visual and descriptions are insufficient

Every scene has exactly ONE primary focus:
- Title scenes: product name
- Problem scenes: the pain (red, chaotic)
- Solution scenes: the result (green, spacious)
- Feature scenes: the highlighted screenshot region
- End scenes: URL / CTA button

### 4. Write narration

- One idea per scene. If you need "and" you need two scenes.
- Lead with the verb. "Organize your tabs" not "Tab organization is provided."
- No jargon. "Your tabs organize themselves" not "AI-powered tab categorization."
- Use contrast. "24 tabs. One click. 5 groups."

## Output Artifacts

For each video, produce these files in a `demo-output/` directory:

1. `scenes/` — one HTML file per scene (1920x1080 viewport)
2. `narration/` — one `.txt` file per scene (for edge-tts input)
3. `scenes.json` — manifest listing scenes in order with durations and narration text
4. `build.sh` — shell script that runs the full pipeline:
   - `playwright screenshot` each HTML scene → `frames/`
   - `edge-tts` each narration file → `audio/`
   - `ffmpeg` concat with crossfade transitions → `output.mp4`

If MCPs are unavailable, still produce items 1-3. Include the ffmpeg commands in `build.sh` for the user to run manually.

## Scene Design System

See [references/scene-design-system.md](references/scene-design-system.md) for the full design system: color language, animation timing, typography, HTML layout, voice options, and pacing guide.

','.claude\skills\demo-video\SKILL.md','215939bac5e82a5f7de02d8a929d680c559bd7f2bb5bcfbde968f723e1a78990','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:dependency-auditor','project_skill','skill://simplicio-runtime/dependency-auditor','skill: dependency-auditor','---
name: dependency-auditor
description: "Audit and manage dependencies across multi-language projects. Identifies vulnerabilities, license conflicts, transitive dependency risks, and safe-upgrade paths. Use when auditing third-party packages before release, investigating a CVE, planning a major version bump, or running a license-compliance review. Examples: ''audit our npm dependencies'', ''do we have GPL contamination'', ''plan the upgrade to React 19''."
---

# Dependency Auditor

> **Skill Type:** POWERFUL · **Category:** Engineering · **Domain:** Dependency Management & Security

Offline, deterministic dependency auditing across 8+ package ecosystems. The three scripts are pattern-matchers over manifests/lockfiles — they do **not** call live advisory APIs; pair their findings with `npm audit` / `pip-audit` / `cargo audit` for current CVE coverage.

## Quick Start

```bash
# 1. Scan for vulnerabilities (built-in offline CVE pattern set; exit non-zero on high severity)
python3 scripts/dep_scanner.py /path/to/project --format json --fail-on-high -o scan.json

# 2. Check license compliance and conflicts
python3 scripts/license_checker.py /path/to/project --policy strict --format json -o licenses.json

# 3. Plan upgrades from the scanner''s inventory
python3 scripts/upgrade_planner.py scan.json --risk-threshold medium --timeline 90 --format json -o plan.json
```

Consume the outputs: `scan.json` findings drive which packages to pin/patch now; `licenses.json` conflicts go to the user as a legal-risk list; `plan.json` orders upgrades by risk with rollback notes. `--quick-scan` skips transitive deps; `--security-only` limits the plan to security fixes.

**Verification loop:** after applying upgrades, re-run step 1 and assert 0 high-severity findings before closing the audit.

## Supported Ecosystems

| Language | Manifests parsed |
|---|---|
| JavaScript/Node | package.json, package-lock.json, yarn.lock |
| Python | requirements.txt, pyproject.toml, Pipfile.lock, poetry.lock |
| Go | go.mod, go.sum |
| Rust | Cargo.toml, Cargo.lock |
| Ruby | Gemfile, Gemfile.lock |
| Java | pom.xml, gradle.lockfile |
| PHP | composer.json, composer.lock |
| C#/.NET | packages.config, project.assets.json |

## License Classification

- **Permissive**: MIT, Apache 2.0, BSD (2/3-clause), ISC
- **Copyleft (strong)**: GPL v2/v3, AGPL v3 — flags contamination risk in permissive projects
- **Copyleft (weak)**: LGPL v2.1/v3, MPL 2.0
- **Proprietary / Dual / Unknown** — unknown licenses are surfaced for manual review

The checker analyzes license inheritance through dependency chains and emits conflict pairs with remediation suggestions.

## Upgrade Risk Matrix

| Risk | Update type | Handling |
|---|---|---|
| Low | Patch, security fixes | Apply immediately |
| Medium | Minor with new features | Batch into scheduled update |
| High | Major version, API changes | Dedicated migration task + tests |
| Critical | Known breaking changes | Planned migration with rollback procedure |

Prioritization: security patches > bug fixes > feature updates > major rewrites; deprecated features get immediate attention.

## Scripts (accurate capability claims)

- **`scripts/dep_scanner.py`** — multi-format parser; built-in offline vulnerability pattern set (~16 CVE patterns — a smoke layer, not a replacement for live advisories); transitive resolution from lockfiles; JSON + text output.
- **`scripts/license_checker.py`** — license detection from package metadata; compatibility matrix across 20+ license types; `--policy permissive|strict`; conflict detection with remediation.
- **`scripts/upgrade_planner.py`** — semver-based breaking-change prediction; risk-ordered migration plan with testing checklist and timeline estimation.

Sample fixtures: `test-project/` and `test-inventory.json` in this folder; expected shapes in `expected_outputs/`.

## CI Integration

```bash
# Security gate in CI
python3 scripts/dep_scanner.py . --format json --fail-on-high
python3 scripts/license_checker.py . --policy strict --format json
```

## Best Practices

1. **Prioritize security**: addre','.claude\skills\dependency-auditor\SKILL.md','aa902f8397b6d73ae68350cd2fc65545ddae210fcecb43365d1d7610f5d6b53f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:designing-workflow-skills','project_skill','skill://simplicio-runtime/designing-workflow-skills','skill: designing-workflow-skills','---
name: designing-workflow-skills
description: >-
  Guides the design and structuring of workflow-based Claude Code skills
  with multi-step phases, decision trees, subagent delegation, and
  progressive disclosure. Use when creating skills that involve
  sequential pipelines, routing patterns, safety gates, task tracking,
  phased execution, or any multi-step workflow. Also applies when
  reviewing or refactoring existing workflow skills for quality.
allowed-tools: Read Glob Grep TodoRead TodoWrite
---

# Designing Workflow Skills

Build workflow-based skills that execute reliably by following structural patterns, not prose.

## Essential Principles

<essential_principles>

<principle name="description-is-the-trigger">
**The `description` field is the only thing that controls when a skill activates.**

Claude decides whether to load a skill based solely on its frontmatter `description`. The body of SKILL.md — including "When to Use" and "When NOT to Use" sections — is only read AFTER the skill is already active. Put your trigger keywords, use cases, and exclusions in the description. A bad description means wrong activations or missed activations regardless of what the body says.

"When to Use" and "When NOT to Use" sections still serve a purpose: they scope the LLM''s behavior once active. "When NOT to Use" should name specific alternatives: "use Semgrep for simple pattern matching" not "not for simple tasks."
</principle>

<principle name="numbered-phases">
**Phases must be numbered with entry and exit criteria.**

Unnumbered prose instructions produce unreliable execution order. Every phase needs:
- A number (Phase 1, Phase 2, ...)
- Entry criteria (what must be true before starting)
- Numbered actions (what to do)
- Exit criteria (how to know it''s done)
</principle>

<principle name="tools-match-executor">
**Tools must match the executor.**

Skills use `allowed-tools:` in frontmatter. Agents use `tools:` in frontmatter. Subagents get tools from their `subagent_type`. Never list tools the component doesn''t use. Never use Bash for operations that have dedicated tools (Glob, Grep, Read, Write, Edit).

Most skills and agents should include `TodoRead` and `TodoWrite` in their tool list — these enable progress tracking during multi-step execution and are useful even for skills that don''t explicitly manage tasks.
</principle>

<principle name="progressive-disclosure">
**Progressive disclosure is structural, not optional.**

SKILL.md stays under 500 lines. It contains only what the LLM needs for every invocation: principles, routing, quick references, and links. Detailed patterns go in `references/`. Step-by-step processes go in `workflows/`. One level deep — no reference chains.
</principle>

<principle name="scalable-tool-patterns">
**Instructions must produce tool-calling patterns that scale.**

Every workflow instruction becomes tool calls at runtime. If a workflow searches N files for M patterns, combine into one regex — not N×M calls. If a workflow spawns subagents per item, use batching — not one subagent per file. Apply the 10,000-file test: mentally run the workflow against a large repo and check that tool call count stays bounded. See [anti-patterns.md](references/anti-patterns.md) AP-18 and AP-19.
</principle>

<principle name="degrees-of-freedom">
**Match instruction specificity to task fragility.**

Not every step needs the same level of prescription. Calibrate per step:
- **Low freedom** (exact commands, no variation): Fragile operations — database migrations, crypto, destructive actions. "Run exactly this script."
- **Medium freedom** (pseudocode with parameters): Preferred patterns where variation is acceptable. "Use this template and customize as needed."
- **High freedom** (heuristics and judgment): Variable tasks — code review, exploration, documentation. "Analyze the structure and suggest improvements."

A skill can mix freedom levels. A security audit skill might use high freedom for the discovery phase ("explore the codebase for auth patterns") and low freedom for the reporting phase ("use exactly thi','.claude\skills\designing-workflow-skills\SKILL.md','a67331eac3a7f3394f116d5a572dd278441f489de3e542f4a38c444bb8d28bcb','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:devcontainer-setup','project_skill','skill://simplicio-runtime/devcontainer-setup','skill: devcontainer-setup','---
name: devcontainer-setup
description: Creates devcontainers with Claude Code, language-specific tooling (Python/Node/Rust/Go), and persistent volumes. Use when adding devcontainer support to a project, setting up isolated development environments, or configuring sandboxed Claude Code workspaces.
---

# Devcontainer Setup Skill

Creates a pre-configured devcontainer with Claude Code and language-specific tooling.

## When to Use

- User asks to "set up a devcontainer" or "add devcontainer support"
- User wants a sandboxed Claude Code development environment
- User needs isolated development environments with persistent configuration

## When NOT to Use

- User already has a devcontainer configuration and just needs modifications
- User is asking about general Docker or container questions
- User wants to deploy production containers (this is for development only)

## Workflow

```mermaid
flowchart TB
    start([User requests devcontainer])
    recon[1. Project Reconnaissance]
    detect[2. Detect Languages]
    generate[3. Generate Configuration]
    write[4. Write files to .devcontainer/]
    done([Done])

    start --> recon
    recon --> detect
    detect --> generate
    generate --> write
    write --> done
```

## Phase 1: Project Reconnaissance

### Infer Project Name

Check in order (use first match):

1. `package.json` → `name` field
2. `pyproject.toml` → `project.name`
3. `Cargo.toml` → `package.name`
4. `go.mod` → module path (last segment after `/`)
5. Directory name as fallback

Convert to slug: lowercase, replace spaces/underscores with hyphens.

### Detect Language Stack

| Language | Detection Files |
|----------|-----------------|
| Python | `pyproject.toml`, `*.py` |
| Node/TypeScript | `package.json`, `tsconfig.json` |
| Rust | `Cargo.toml` |
| Go | `go.mod`, `go.sum` |

### Multi-Language Projects

If multiple languages are detected, configure all of them in the following priority order:

1. **Python** - Primary language, uses Dockerfile for uv + Python installation
2. **Node/TypeScript** - Uses devcontainer feature
3. **Rust** - Uses devcontainer feature
4. **Go** - Uses devcontainer feature

For multi-language `postCreateCommand`, chain all setup commands:
```
uv run /opt/post_install.py && uv sync && npm ci
```

Extensions and settings from all detected languages should be merged into the configuration.

## Phase 2: Generate Configuration

Start with base templates from `resources/` directory. Substitute:

- `{{PROJECT_NAME}}` → Human-readable name (e.g., "My Project")
- `{{PROJECT_SLUG}}` → Slug for volumes (e.g., "my-project")

Then apply language-specific modifications below.

## Base Template Features

The base template includes:

- **Claude Code** with marketplace plugins (anthropics/skills, trailofbits/skills, trailofbits/skills-curated)
- **Sandboxing** via bubblewrap and socat
- **Python 3.13** via uv (fast binary download)
- **Node 22** via fnm (Fast Node Manager)
- **ast-grep** for AST-based code search
- **Network isolation tools** (iptables, ipset) with NET_ADMIN capability
- **Security mounts**: `.devcontainer/` mounted read-only to prevent container escape
- **Token forwarding**: `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` via `remoteEnv`
- **Modern CLI tools**: ripgrep, fd, fzf, tmux, git-delta

---

## Language-Specific Sections

### Python Projects

**Detection:** `pyproject.toml`, `requirements.txt`, `setup.py`, or `*.py` files

**Dockerfile additions:**

The base Dockerfile already includes Python 3.13 via uv. If a different version is required (detected from `pyproject.toml`), modify the Python installation:

```dockerfile
# Install Python via uv (fast binary download, not source compilation)
RUN uv python install <version> --default
```

**devcontainer.json extensions:**

Add to `customizations.vscode.extensions`:
```json
"ms-python.python",
"ms-python.vscode-pylance",
"charliermarsh.ruff"
```

Add to `customizations.vscode.settings`:
```json
"python.defaultInterpreterPath": ".venv/bin/python",
"[python]": {
  "editor.defaultFormatter": "charliermarsh.ruff",
  "editor.','.claude\skills\devcontainer-setup\SKILL.md','d11f03d08fa0c9bbe22c3ac794986ebf27adb993d7f5861e1335f9a77dc72e46','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:diagramming-code','project_skill','skill://simplicio-runtime/diagramming-code','skill: diagramming-code','---
name: diagramming-code
description: >
  Generates Mermaid diagrams from Trailmark code graphs. Produces call graphs,
  class hierarchies, module dependency maps, containment diagrams, complexity
  heatmaps, and attack surface data flow visualizations. Use when visualizing
  code architecture, drawing call graphs, generating class diagrams, creating
  dependency maps, producing complexity heatmaps, or visualizing data flow
  and attack surface paths as Mermaid diagrams.
---

# Diagramming Code

Generates Mermaid diagrams from Trailmark''s code graph. A pre-made script
handles Mermaid syntax generation; Claude selects the diagram type and
parameters.

## When to Use

- Visualizing call paths between functions
- Drawing class inheritance hierarchies
- Mapping module import dependencies
- Showing class structure with members
- Highlighting complexity hotspots with color coding
- Tracing data flow from entrypoints to sensitive functions

## When NOT to Use

- Querying the graph without visualization (use the `trailmark` skill)
- Mutation testing triage (use the `genotoxic` skill)
- Architecture diagrams not derived from code (draw by hand)

## Prerequisites

**trailmark** must be installed. If `uv run trailmark` fails, run:

```bash
uv pip install trailmark
```

**DO NOT** fall back to hand-writing Mermaid from source code reading. The
script uses Trailmark''s parsed graph for accuracy. If installation fails,
report the error to the user.

---

## Quick Start

```bash
uv run {baseDir}/scripts/diagram.py \
    --target {targetDir} --language auto --type call-graph \
    --focus main --depth 2
```

Output is raw Mermaid text. Wrap in a fenced code block:

````markdown
```mermaid
flowchart TB
    ...
```
````

---

## Diagram Types

```
├─ "Who calls what?"               → --type call-graph
├─ "Class inheritance?"             → --type class-hierarchy
├─ "Module dependencies?"           → --type module-deps
├─ "Class members and structure?"   → --type containment
├─ "Where is complexity highest?"   → --type complexity
└─ "Path from input to function?"   → --type data-flow
```

For detailed examples of each type, see
[references/diagram-types.md](references/diagram-types.md).

---

## Workflow

```
Diagram Progress:
- [ ] Step 1: Verify trailmark is installed
- [ ] Step 2: Identify diagram type from user request
- [ ] Step 3: Determine focus node and parameters
- [ ] Step 4: Run diagram.py script
- [ ] Step 5: Verify output is non-empty and well-formed
- [ ] Step 6: Embed diagram in response
```

**Step 1:** Run `uv run trailmark analyze --language auto --summary {targetDir}`. Install
if it fails. Then run pre-analysis via the programmatic API:

```python
from trailmark.query.api import QueryEngine

engine = QueryEngine.from_directory("{targetDir}", language="auto")
engine.preanalysis()
```

Pre-analysis enriches the graph with blast radius, taint propagation,
and privilege boundary data used by `data-flow` diagrams.

If auto-detection is wrong for the target, rerun with an explicit language or
comma-separated list such as `python,rust`.

**Step 2:** Match the user''s request to a `--type` using the decision tree
above.

**Step 3:** For `call-graph` and `data-flow`, identify the focus function.
Default `--depth 2`. Use `--direction LR` for dependency flows.

**Step 4:** Run the script and capture stdout.

**Step 5:** Check: output starts with `flowchart` or `classDiagram`,
contains at least one node. If empty or malformed, consult
[references/mermaid-syntax.md](references/mermaid-syntax.md).

**Step 6:** Wrap output in ` ```mermaid ``` ` code fence.

---

## Script Reference

```
uv run {baseDir}/scripts/diagram.py [OPTIONS]
```

| Argument | Short | Default | Description |
|---|---|---|---|
| `--target` | `-t` | required | Directory to analyze |
| `--language` | `-l` | `python` | Source language |
| `--type` | `-T` | required | Diagram type (see above) |
| `--focus` | `-f` | none | Center diagram on this node |
| `--depth` | `-d` | `2` | BFS traversal depth |
| `--direction` | | `TB` | Layout: `TB` (top-bottom) or `LR` (left-rig','.claude\skills\diagramming-code\SKILL.md','616d832084869884f855ce0c69f5a8419e4214efcfea47c595c2b9dcd9510f27','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:differential-review','project_skill','skill://simplicio-runtime/differential-review','skill: differential-review','---
name: differential-review
description: >
  Performs security-focused differential review of code changes (PRs, commits, diffs).
  Adapts analysis depth to codebase size, uses git history for context, calculates
  blast radius, checks test coverage, and generates comprehensive markdown reports.
  Automatically detects and prevents security regressions.
allowed-tools: Read Write Grep Glob Bash
---

# Differential Security Review

Security-focused code review for PRs, commits, and diffs.

## Core Principles

1. **Risk-First**: Focus on auth, crypto, value transfer, external calls
2. **Evidence-Based**: Every finding backed by git history, line numbers, attack scenarios
3. **Adaptive**: Scale to codebase size (SMALL/MEDIUM/LARGE)
4. **Honest**: Explicitly state coverage limits and confidence level
5. **Output-Driven**: Always generate comprehensive markdown report file

---

## Rationalizations (Do Not Skip)

| Rationalization | Why It''s Wrong | Required Action |
|-----------------|----------------|-----------------|
| "Small PR, quick review" | Heartbleed was 2 lines | Classify by RISK, not size |
| "I know this codebase" | Familiarity breeds blind spots | Build explicit baseline context |
| "Git history takes too long" | History reveals regressions | Never skip Phase 1 |
| "Blast radius is obvious" | You''ll miss transitive callers | Calculate quantitatively |
| "No tests = not my problem" | Missing tests = elevated risk rating | Flag in report, elevate severity |
| "Just a refactor, no security impact" | Refactors break invariants | Analyze as HIGH until proven LOW |
| "I''ll explain verbally" | No artifact = findings lost | Always write report |

---

## Quick Reference

### Codebase Size Strategy

| Codebase Size | Strategy | Approach |
|---------------|----------|----------|
| SMALL (<20 files) | DEEP | Read all deps, full git blame |
| MEDIUM (20-200) | FOCUSED | 1-hop deps, priority files |
| LARGE (200+) | SURGICAL | Critical paths only |

### Risk Level Triggers

| Risk Level | Triggers |
|------------|----------|
| HIGH | Auth, crypto, external calls, value transfer, validation removal |
| MEDIUM | Business logic, state changes, new public APIs |
| LOW | Comments, tests, UI, logging |

---

## Workflow Overview

```
Pre-Analysis → Phase 0: Triage → Phase 1: Code Analysis → Phase 2: Test Coverage
    ↓              ↓                    ↓                        ↓
Phase 3: Blast Radius → Phase 4: Deep Context → Phase 5: Adversarial → Phase 6: Report
```

---

## Decision Tree

**Starting a review?**

```
├─ Need detailed phase-by-phase methodology?
│  └─ Read: methodology.md
│     (Pre-Analysis + Phases 0-4: triage, code analysis, test coverage, blast radius)
│
├─ Analyzing HIGH RISK change?
│  ├─ Read: adversarial.md
│  │  (Phase 5: Attacker modeling, exploit scenarios, exploitability rating)
│  └─ Or delegate to: adversarial-modeler agent
│     (Autonomous attacker modeling with concrete exploit scenarios)
│
├─ Writing the final report?
│  └─ Read: reporting.md
│     (Phase 6: Report structure, templates, formatting guidelines)
│
├─ Looking for specific vulnerability patterns?
│  └─ Read: patterns.md
│     (Regressions, reentrancy, access control, overflow, etc.)
│
└─ Quick triage only?
   └─ Use Quick Reference above, skip detailed docs
```

---

## Agents

**`adversarial-modeler`** — Models attacker perspectives and builds exploit
scenarios for HIGH RISK code changes. Follows the 5-step adversarial
methodology (attacker model, attack vectors, exploitability rating, exploit
scenario, baseline cross-reference) and produces structured vulnerability
reports. Delegate to this agent when Phase 5 analysis is needed on high-risk
changes.

---

## Quality Checklist

Before delivering:

- [ ] All changed files analyzed
- [ ] Git blame on removed security code
- [ ] Blast radius calculated for HIGH risk
- [ ] Attack scenarios are concrete (not generic)
- [ ] Findings reference specific line numbers + commits
- [ ] Report file generated
- [ ] User notified with summary

---

## Integration

**audit-context-building skill:*','.claude\skills\differential-review\SKILL.md','c7b2fd72e566b1fd066f14d8167bda1afe3d1c3a2f0401c1e75b88abdd1a643a','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:diligence-issue-extraction','project_skill','skill://simplicio-runtime/diligence-issue-extraction','skill: diligence-issue-extraction','---
name: diligence-issue-extraction
description: >
  Read VDR documents and extract issues per house categories and materiality
  thresholds, producing findings in house memo format. Use when user says
  "review the data room", "extract issues from [folder]", "diligence review",
  "what''s in the VDR", or points at VDR documents.
argument-hint: "[VDR folder path or category name]"
---

# /diligence-issue-extraction

1. Load `~/.claude/plugins/config/claude-for-legal/corporate-legal/CLAUDE.md` + `~/.claude/plugins/config/claude-for-legal/corporate-legal/deals/[code]/deal-context.md`.
2. Use the workflow below.
3. Check `ai-tool-handoff` — if category is bulk and tool is configured, hand off first.
4. Read docs, apply materiality filter, extract per category.
5. Findings in house memo format. Hand off consents to closing checklist.

---

## Matter context

**Matter context.** Check `## Matter workspaces` in the practice-level CLAUDE.md. If `Enabled` is `✗` (the default for in-house users), skip the rest of this paragraph — skills use practice-level context and the matter machinery is invisible. If enabled and there is no active matter, ask: "Which matter is this for? Run `/corporate-legal:matter-workspace switch <slug>` or say `practice-level`." Load the active matter''s `matter.md` for matter-specific context and overrides. Write outputs to the matter folder at `~/.claude/plugins/config/claude-for-legal/corporate-legal/matters/<matter-slug>/`. Never read another matter''s files unless `Cross-matter context` is `on`.

---

## Purpose

The VDR has 2,000 documents. Somewhere in there are the 30 that matter for the deal. This skill reads documents against the diligence categories and materiality thresholds from `~/.claude/plugins/config/claude-for-legal/corporate-legal/CLAUDE.md`, extracts issues, and writes them in house memo format.

## Load context

- `~/.claude/plugins/config/claude-for-legal/corporate-legal/CLAUDE.md` → Diligence structure (categories, materiality thresholds)
- `~/.claude/plugins/config/claude-for-legal/corporate-legal/CLAUDE.md` → Issues memo format (how findings are stated)
- `~/.claude/plugins/config/claude-for-legal/corporate-legal/deals/[code]/deal-context.md` → deal-specific thresholds, VDR location

If deal-context.md doesn''t exist, ask which deal this is for.

## Workflow

### Step 1: Inventory the VDR

If VDR MCP (Box/Intralinks/Datasite) is connected, pull the index. Map VDR folders to diligence request list categories. Note gaps — request list categories with no corresponding VDR content.

```markdown
## VDR Inventory: [Deal code]

| Request category | VDR folder | Docs | Status |
|---|---|---|---|
| Corporate & Organizational | /01-Corporate | 45 | Reviewed |
| Material Contracts | /02-Contracts | 312 | In progress |
| IP | /03-IP | 89 | Not started |
| [etc.] | | | |

**Gaps:** [Request categories with no VDR content — follow-up request needed]
```

### Step 2: Apply materiality filter

Per `~/.claude/plugins/config/claude-for-legal/corporate-legal/CLAUDE.md` / deal-context thresholds. Don''t review everything if the threshold says contracts >$X.

For contracts specifically: sort by stated value (if in filename/metadata) or by counterparty significance. Review top-down until you hit the threshold or the category is exhausted.

### Step 3: Extract issues

For each document read, check against the standard diligence concerns for its category:

**Material contracts — standard extraction set:**
- Change of control provision (triggered by this deal? consent required?)
- Assignment restriction (can the contract move to buyer?)
- Exclusivity / non-compete (restricts buyer''s business?)
- MFN (most favored nation — pricing constraints)
- Termination rights (can counterparty walk because of the deal?)
- Unusual indemnities or liability exposure

**Corporate — standard extraction set:**
- Cap table accuracy, outstanding options/warrants
- Board consent requirements for the transaction
- Stockholder agreement restrictions (drags, tags, ROFR)
- Subsidiary structure and intercompany arrangements

**IP — stan','.claude\skills\diligence-issue-extraction\SKILL.md','d3ceb0b0adfcf8d4e9b2f0c920681e6ccd96e83cb0de46347d8bc5d4e3992b51','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:dimensional-analysis','project_skill','skill://simplicio-runtime/dimensional-analysis','skill: dimensional-analysis','---
name: dimensional-analysis
description: "Annotates codebases with dimensional analysis comments documenting units, dimensions, and decimal scaling. Use when someone asks to annotate units in a codebase, perform a dimensional analysis, or find vulnerabilities in a DeFi protocol, offchain code, or other blockchain-related codebase with arithmetic. Prevents dimensional mismatches and catches formula bugs early."
allowed-tools: Read Write Grep List Glob Task TodoRead TodoWrite
---

# Dimensional Analysis Skill

This skill orchestrates a dimensional-analysis pipeline for codebases that perform numeric computations with mixed units, precisions, or scaling factors. The main skill context is a workflow controller only: it delegates scanning, vocabulary discovery, annotation, propagation, and validation to specialized subagents, then manages batching, persistence, retries, coverage gates, and final reporting.

## When to Use

- Annotating a codebase with unit/dimension comments (e.g., `D18{tok}`, `D27{UoA/tok}`)
- Performing dimensional analysis on DeFi protocols, financial code, or scientific computations
- Hunting for arithmetic bugs caused by unit mismatches, missing scaling, or precision loss
- Auditing codebases with mixed decimal precisions or fixed-point arithmetic

## When NOT to Use

- Codebases with no numeric arithmetic or unit conversions — there is nothing to annotate
- Pure integer counting logic (loop indices, array lengths) with no physical or financial dimensions
- When you only need a quick spot-check of a single formula — read the code directly instead of running the full pipeline

## Execution Mode

This skill runs in one mode only: `full-auto`.
This is a workflow-based skill that delegates step-specific work to specialized agents via the `Task` tool. You orchestrate the overall process, manage coverage and state persistence, and ensure that every in-scope file is processed through each step of the pipeline.

- Always run the full pipeline in this order: Step 1 -> Step 2 -> Step 3 -> Step 4.
- The main skill context must not perform repository-wide dimensional analysis, annotation, propagation, or bug validation itself when a dedicated subagent exists for that step.
- The main skill context may inspect artifacts, manifests, and subagent outputs only as needed to route work, build prompts, persist state, and determine completion.
- Any mode argument provided by the caller is ignored.
- Report all results at the end in a single summary.

When you start a step, report it:

```text
Starting Step: Step {n}
```

## Scope and Coverage Guarantees

This skill must audit **all in-scope arithmetic files**, including large repositories.

- In-scope files are defined by Step 1 scanner output (`files` array), across **all** priority tiers (CRITICAL, HIGH, MEDIUM, LOW).
- If Step 1 narrows inputs for vocabulary discovery (for example, CRITICAL/HIGH only), that narrowing applies to discovery only. It **never** reduces annotation or validation scope.
- `arithmetic-scanner` persists the in-scope file manifest to `DIMENSIONAL_SCOPE.json` in the project root, and that manifest is the source of truth for Steps 2-4.
- A file is considered fully covered only when all three statuses are present:
  - `step2`: anchor annotation completed (or explicit no-anchor result)
  - `step3`: propagation completed (or explicit no-propagation result)
  - `step4`: validation completed
- `dimension-discoverer` persists the discovered dimensional vocabulary to `DIMENSIONAL_UNITS.md` in the project root for reuse by later steps and future runs.
- When a file ends in a terminal `BLOCKED` state, persist the blocking reason and retry count in `DIMENSIONAL_SCOPE.json` and reflect the same file in `coverage.unprocessed_files`.
- Do not finish while any in-scope file remains unprocessed in any step.

## Delegation Contract

- `arithmetic-scanner` owns repository scanning, arithmetic-file prioritization, and writing `DIMENSIONAL_SCOPE.json`.
- `dimension-discoverer` owns dimensional vocabulary discovery, unit inference, and writing `DIMENSIONAL_UNITS.md`.','.claude\skills\dimensional-analysis\SKILL.md','76ae51091bbd6ba9d3d1b394ccebbb470d9b57d3525e99aafdfc585ca540153b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:directory-submissions','project_skill','skill://simplicio-runtime/directory-submissions','skill: directory-submissions','---
name: directory-submissions
description: When the user wants to submit their product to startup, SaaS, AI, agent, MCP, no-code, or review directories for backlinks, domain rating, and discovery. Also use when the user mentions "directory submissions," "submit to directories," "backlinks from directories," "list my product," "submit to Product Hunt," "BetaList," "TAAFT," "Futurepedia," "G2 listing," "Capterra listing," "AlternativeTo," "SaaSHub," "AI directories," "MCP registry," "agent directory," "dofollow backlinks," "launch directories," or "directory tracker." Use this whenever someone is planning the directory layer of a product launch or an ongoing backlink campaign. For the broader launch moment, see launch. For programmatic SEO pages that should live behind these backlinks, see programmatic-seo. For AI citation optimization, see ai-seo.
metadata:
  version: 2.0.0
---

# Directory Submissions

You are an expert in directory-driven distribution for software products. Your goal is to help the user build a compounding backlink + discovery foundation by submitting to the right directories, in the right order, with the right positioning — and to make sure that foundation actually produces leads instead of vanity backlinks.

## Before Starting

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

---

## Core Philosophy

Directory submissions are the **foundation layer** of distribution — never the whole strategy. They do three things well:

1. **Pass dofollow backlinks** from high domain-rating sites into your marketing pages. This raises your DR, which makes your entire site easier to rank for competitive keywords.
2. **Create discovery surface area** — people browsing AI/SaaS directories are in-market buyers, not random traffic.
3. **Get cited by AI engines** — ChatGPT, Claude, Perplexity, and Google AI Overviews all pull heavily from high-DR directories when answering "what''s the best [category]?" queries. AI-referred traffic converts **6–27× higher** than traditional search traffic.

But directories alone will not generate meaningful leads. They exist to pass link equity into the pages that DO generate leads — template galleries, comparison pages, alternative pages, blog posts. **Build the destination pages first, then submit to directories so the link equity has somewhere useful to land.**

The full directory catalog lives in `references/directory-list.md`. The positioning variant library lives in `references/positioning-variations.md`. The submission tracker template lives in `references/submission-tracker-template.csv`.

---

## The Three Hard Rules

### Rule 1: Foundation before submission
Never submit to a directory until the landing page it will link to is live, indexed, and has:
- A single `<h1>` and sequential heading hierarchy — pages with clean hierarchy have **2.8× higher AI citation rates**, and 87% of ChatGPT-cited pages use a single H1.
- A real pricing page (even "free while in beta" counts — most Tier 1 directories require one).
- Privacy policy + terms.
- Logo assets in PNG + SVG + square 1024×1024 + favicon.
- 5–8 real product screenshots at 1920×1080 (not marketing mockups).
- A 60–90 second demo video — products with video on Product Hunt get **2.7× more upvotes**.
- FAQ schema markup (AI engines heavily weight `FAQPage` JSON-LD for answer extraction).
- Structured data: `Organization`, `Product`, `SoftwareApplication`.

### Rule 2: Destination pages before directories
Directories are the *source* of link equity. You need *destinations* that can convert the resulting traffic. Minimum destinations before submitting to anything:
- 3–5 competitor alternative pages (`/alternatives/[competitor]`) targeting "[competitor] alternative" keywords. Comparison/alternative pages convert at **5–15%** vs 0.5–2% for generic content.
- 3–5 use','.claude\skills\directory-submissions\SKILL.md','1da01b7606ad9ae55b9dbb1cad22b2caee06e137fb57dc05071c777e39f65576','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:docker-development','project_skill','skill://simplicio-runtime/docker-development','skill: docker-development','---
name: docker-development
description: "Docker and container development agent skill and plugin for Dockerfile optimization, docker-compose orchestration, multi-stage builds, and container security hardening. Use when: user wants to optimize a Dockerfile, create or improve docker-compose configurations, implement multi-stage builds, audit container security, reduce image size, or follow container best practices. Covers build performance, layer caching, secret management, and production-ready container patterns."
license: MIT
metadata:
  version: 1.0.0
  author: Alireza Rezvani
  category: engineering
  updated: 2026-03-16
---

# Docker Development

> Smaller images. Faster builds. Secure containers. No guesswork.

Opinionated Docker workflow that turns bloated Dockerfiles into production-grade containers. Covers optimization, multi-stage builds, compose orchestration, and security hardening.

Not a Docker tutorial — a set of concrete decisions about how to build containers that don''t waste time, space, or attack surface.

---

## Slash Commands

| Command | What it does |
|---------|-------------|
| `/docker:optimize` | Analyze and optimize a Dockerfile for size, speed, and layer caching |
| `/docker:compose` | Generate or improve docker-compose.yml with best practices |
| `/docker:security` | Audit a Dockerfile or running container for security issues |

---

## When This Skill Activates

Recognize these patterns from the user:

- "Optimize this Dockerfile"
- "My Docker build is slow"
- "Create a docker-compose for this project"
- "Is this Dockerfile secure?"
- "Reduce my Docker image size"
- "Set up multi-stage builds"
- "Docker best practices for [language/framework]"
- Any request involving: Dockerfile, docker-compose, container, image size, build cache, Docker security

If the user has a Dockerfile or wants to containerize something → this skill applies.

---

## Workflow

### `/docker:optimize` — Dockerfile Optimization

1. **Analyze current state**
   - Read the Dockerfile
   - Identify base image and its size
   - Count layers (each RUN/COPY/ADD = 1 layer)
   - Check for common anti-patterns

2. **Apply optimization checklist**

   ```
   BASE IMAGE
   ├── Use specific tags, never :latest in production
   ├── Prefer slim/alpine variants (debian-slim > ubuntu > debian)
   ├── Pin digest for reproducibility in CI: image@sha256:...
   └── Match base to runtime needs (don''t use python:3.12 for a compiled binary)

   LAYER OPTIMIZATION
   ├── Combine related RUN commands with && \
   ├── Order layers: least-changing first (deps before source code)
   ├── Clean package manager cache in the same RUN layer
   ├── Use .dockerignore to exclude unnecessary files
   └── Separate build deps from runtime deps

   BUILD CACHE
   ├── COPY dependency files before source code (package.json, requirements.txt, go.mod)
   ├── Install deps in a separate layer from code copy
   ├── Use BuildKit cache mounts: --mount=type=cache,target=/root/.cache
   └── Avoid COPY . . before dependency installation

   MULTI-STAGE BUILDS
   ├── Stage 1: build (full SDK, build tools, dev deps)
   ├── Stage 2: runtime (minimal base, only production artifacts)
   ├── COPY --from=builder only what''s needed
   └── Final image should have NO build tools, NO source code, NO dev deps
   ```

3. **Generate optimized Dockerfile**
   - Apply all relevant optimizations
   - Add inline comments explaining each decision
   - Report estimated size reduction

4. **Validate**
   ```bash
   python3 scripts/dockerfile_analyzer.py Dockerfile
   ```

### `/docker:compose` — Docker Compose Configuration

1. **Identify services**
   - Application (web, API, worker)
   - Database (postgres, mysql, redis, mongo)
   - Cache (redis, memcached)
   - Queue (rabbitmq, kafka)
   - Reverse proxy (nginx, traefik, caddy)

2. **Apply compose best practices**

   ```
   SERVICES
   ├── Use depends_on with condition: service_healthy
   ├── Add healthchecks for every service
   ├── Set resource limits (mem_limit, cpus)
   ├── Use named volumes for persistent data
   └── Pin image versio','.claude\skills\docker-development\SKILL.md','bb7e987f16118bd2ae02e089ee4f06d08be984776fc8341497087b46ad13124f','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:dossier','project_skill','skill://simplicio-runtime/dossier','skill: dossier','---
name: dossier
description: "Decision-grade entity research skill — produces a hypothesis-tested dossier on a specific company, person, nonprofit, or government org, not a generic profile. Forcing intake makes the user state their hypothesis upfront (what they already believe and want to verify or disprove) so the dossier tests it rather than confirms it. Output is an editable Word document (.docx) with verdict on the hypothesis, identity facts, 12-month activity timeline, network and reputation signals, red flags, conversation hooks tied to specific findings, and source-provenance audit log. Uses WebSearch + WebFetch + free APIs (SEC EDGAR, GitHub, ProPublica) as workhorses; optional BYOK MCPs enhance coverage. Use when the user asks for background research, diligence, or meeting prep on a specific entity (e.g., ''prep me for a meeting with [person/company]'', ''due diligence on [company]''). Honors sensitivity exclusions for journalism + personal-vetting contexts."
license: MIT
metadata:
  source_spec: "megaprompts/12-dossier-megaprompt.md"
  build_pattern: "Path B (direct conversion)"
  research_pack_convention: "Agent Integrity Rules verbatim per PR #657 audit; hypothesis-testing variant"
  version: 1.0.0
---

# Dossier — Decision-Grade Entity Research

> **Portability:** Requires `WebSearch` + `WebFetch`, Node.js with `docx` package, and optionally `bash_tool` + `curl` for free APIs (SEC EDGAR, GitHub, ProPublica). BYOK MCPs (LinkedIn, Crunchbase, Apollo, Pitchbook, SimilarWeb) are optional enhancements. Works in Claude Code CLI natively.

## Non-Generic Framing — The Differentiator

This skill is **decision-grade entity research with hypothesis-testing**. It **refuses** to be "tell me about Microsoft". Every invocation forces the user to expose their hypothesis upfront (Q4) so the dossier *tests* it rather than confirms it.

The use case shape:

> "I''m pitching Microsoft Tuesday. My hypothesis is they''re consolidating AI spend on their first-party Foundry platform. Validate or disprove, and give me three conversation hooks tied to what you find."

**NOT:**

> "Tell me about Microsoft."

The forcing Q4 — the hypothesis question — is the non-generic anchor. Skip it and the skill produces a Wikipedia summary.

See [`references/hypothesis_testing_discipline.md`](references/hypothesis_testing_discipline.md) for the canon.

## Agent Integrity Rules (Research-Pack Convention)

Locked verbatim per PR #657 audit.

- **Execution discipline.** Sequential search calls. WebSearch + WebFetch have looser rate limits than Consensus but still apply 1 q/sec etiquette. Confirm response received before next call.
- **Source discipline.** Cite only sources returned by this session''s tool calls. Wikipedia / training knowledge labeled `[Background — verify before quoting]` and excluded from primary findings count.
- **Three-count tracking.** Queries sent / sources received / sources cited. Plus **per-tier breakdown** (primary / secondary / tertiary) unique to dossier. Surfaced in audit log.
- **Retry policy.** On failure → wait 3s → retry once → log. After 3 consecutive failures: stop, alert user.
- **Source reliability tier.** Each citation tagged primary (official, SEC, court records) / secondary (mainstream news, trade press) / tertiary (blogs, forums). DOCX surfaces tier on every flag.

## Phase 1: Grill-Me Intake (6 forcing questions, one at a time)

### Q1 (root) — Subject identity

> **Who is the subject? Give me the exact name and, if a company, the website or LinkedIn URL. If a person, their LinkedIn URL or a unique identifier (company affiliation + role).**
>
> *Why I''m asking:* Disambiguation. There are 47 John Smiths. There are three companies called "Atlas". I need a specific entity to research.

If user gives only a name, push for a second identifier. **Refuse to proceed on ambiguous names.**

### Q2 (depends on Q1) — Subject type

> **What kind of subject is this? Pick one: person / company / nonprofit / government org / other.**
>
> *Why I''m asking:* Different source matrices apply. For people I check LinkedIn, GitHub, Sch','.claude\skills\dossier\SKILL.md','546ce14e5a7fd8ccff61b75d8467ca3e48646ac4d2c74d7259a5e8e840412799','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:dwarf-expert','project_skill','skill://simplicio-runtime/dwarf-expert','skill: dwarf-expert','---
name: dwarf-expert
description: Provides expertise for analyzing DWARF debug files and understanding the DWARF debug format/standard (v3-v5). Triggers when understanding DWARF information, interacting with DWARF files, answering DWARF-related questions, or working with code that parses DWARF data.
allowed-tools: Read Bash Grep Glob WebSearch
---
# Overview
This skill provides technical knowledge and expertise about the DWARF standard and how to interact with DWARF files. Tasks include answering questions about the DWARF standard, providing examples of various DWARF features, parsing and/or creating DWARF files, and writing/modifying/analyzing code that interacts with DWARF data.

## When to Use This Skill
- Understanding or parsing DWARF debug information from compiled binaries
- Answering questions about the DWARF standard (v3, v4, v5)
- Writing or reviewing code that interacts with DWARF data
- Using `dwarfdump` or `readelf` to extract debug information
- Verifying DWARF data integrity with `llvm-dwarfdump --verify`
- Working with DWARF parsing libraries (libdwarf, pyelftools, gimli, etc.)

## When NOT to Use This Skill
- **DWARF v1/v2 Analysis**: Expertise limited to versions 3, 4, and 5.
- **General ELF Parsing**: Use standard ELF tools if DWARF data isn''t needed.
- **Executable Debugging**: Use dedicated debugging tools (gdb, lldb, etc) for debugging executable code/runtime behavior.
- **Binary Reverse Engineering**: Use dedicated RE tools (Ghidra, IDA) unless specifically analyzing DWARF sections.
- **Compiler Debugging**: DWARF generation issues are compiler-specific, not covered here.

# Authoritative Sources
When specific DWARF standard information is needed, use these authoritative sources:

1. **Official DWARF Standards (dwarfstd.org)**: Use web search to find specific sections of the official DWARF specification at dwarfstd.org. Search queries like "DWARF5 DW_TAG_subprogram attributes site:dwarfstd.org" are effective.

2. **LLVM DWARF Implementation**: The LLVM project''s DWARF handling code at `llvm/lib/DebugInfo/DWARF/` serves as a reliable reference implementation. Key files include:
   - `DWARFDie.cpp` - DIE handling and attribute access
   - `DWARFUnit.cpp` - Compilation unit parsing
   - `DWARFDebugLine.cpp` - Line number information
   - `DWARFVerifier.cpp` - Validation logic

3. **libdwarf**: The reference C implementation at github.com/davea42/libdwarf-code provides detailed handling of DWARF data structures.

# Verification Workflows
Use `llvm-dwarfdump` verification options to validate DWARF data integrity:

## Structural Validation
```bash
# Verify DWARF structure (compile units, DIE relationships, address ranges)
llvm-dwarfdump --verify <binary>

# Detailed error output with summary
llvm-dwarfdump --verify --error-display=full <binary>

# Machine-readable JSON error summary
llvm-dwarfdump --verify --verify-json=errors.json <binary>
```

## Quality Metrics
```bash
# Output debug info quality metrics as JSON
llvm-dwarfdump --statistics <binary>
```

The `--statistics` output helps compare debug info quality across compiler versions and optimization levels.

## Common Verification Patterns
- **After compilation**: Verify binaries have valid DWARF before distribution
- **Comparing builds**: Use `--statistics` to detect debug info quality regressions
- **Debugging debuggers**: Identify malformed DWARF causing debugger issues
- **DWARF tool development**: Validate parser output against known-good binaries

# Parsing DWARF Debug Information
## readelf
ELF files can be parsed via the `readelf` command ({baseDir}/reference/readelf.md). Use this for general ELF information, but prefer `dwarfdump` for DWARF-specific parsing.

## dwarfdump
DWARF files can be parsed via the `dwarfdump` command, which is more effective at parsing and displaying complex DWARF information than `readelf` and should be used for most DWARF parsing tasks ({baseDir}/reference/dwarfdump.md).

# Working With Code
This skill supports writing, modifying, and reviewing code that interacts with DWARF data. This may involve code that par','.claude\skills\dwarf-expert\SKILL.md','279483a11d49b8096a3f644342d64557c2c295e484aa9d9990172148a3564463','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:ecc-harness','project_skill','skill://simplicio-runtime/ecc-harness','skill: ecc-harness','---
name: ecc-harness
description: Use to run agentic coding work as a hardened harness — delegate scoped work to focused subagents, enforce safety gates before destructive/dangerous commands, manage context by strategic breakpoints (not panic auto-compaction), and turn what a session learns into reusable patterns. Trigger on "set up the agent harness", "make this safe/governed", "delegate to subagents", "audit my agent config/hooks/MCPs", "learn from this session", or any multi-step agentic task that needs governance + continuous improvement.
source: adapted from github.com/affaan-m/ECC ("the agent harness operating system for agentic work")
metadata:
  simplicio:
    guardians: [Helo, Levi]
    tags: [harness, subagents, gate, security, continuous-learning, instincts, memory, mcp, ecc]
---

# ECC harness — governed agentic work + continuous learning

Adapted for Simplicio from **github.com/affaan-m/ECC**, "the agent harness operating
system for agentic work" (67 subagents, 271+ skills, hooks, rules, cross-harness
adapters). This skill imports ECC''s *ideas* as Simplicio-native practice — it does
NOT vendor its 271 skills. Most map onto things Simplicio already has; the valuable
new concepts are called out below.

## Map to what Simplicio already has

| ECC concept | Simplicio equivalent |
|---|---|
| Subagents (scoped delegation) | the async sub-agent fabric (~600), worktree isolation |
| Skills (271+) | the neural-memory skill index (FTS + vector), 270 skills |
| GateGuard (block dangerous commands) | the **action gate** (`simplicio gate` / `action_gate`) + hardline blocklist |
| MCP integration (14 servers) | `simplicio serve --mcp` (10 tools) + ToolSearch to all session MCPs |
| Token optimization | the token economy (map / memory / deterministic edit / savings ledger) |
| Memory persistence across sessions | the neural memory (`.simplicio-loop/memory/`), per-project, evolves |

## Ideas worth ADOPTING (the new value)

1. **Instincts → skills (continuous learning with confidence).** After a session,
   mine high-signal patterns ("when X, do Y — worked"), attach a confidence score,
   and promote the durable ones into a real skill / memory row. Low-confidence stays
   a tentative instinct until it earns its place. (Simplicio: `simplicio-learn` +
   write back to memory; this is the closed learning loop made explicit.)

2. **AgentShield — audit the agent config itself.** Periodically scan the harness''s
   own attack surface: `CLAUDE.md` / `AGENTS.md`, hooks, registered MCP servers, and
   skill bodies — for secrets, dangerous hook commands, untrusted MCP entries, or
   perception-shaping config that could override the safety contract. Treat config as
   code that can be malicious.

3. **Strategic compaction (breakpoints, not panic).** Compact context at sensible
   task breakpoints, not blindly at 95% full. Summarize the finished phase, keep the
   load-bearing facts, drop the transcript. (Simplicio: `simplicio-compress` +
   one-time standing-context compaction.)

4. **Subagent delegation discipline.** Give each subagent a narrow scope + limited
   context + a typed return; spawn many in one message for parallel independent work;
   isolate file-overlapping work in worktrees. Don''t let one agent carry everything.

## Operating rules (always-follow, ECC-style)

- **Gate before mutating.** Destructive/irreversible/networked actions pass the
  action gate; the hardline blocklist is non-negotiable, even chat-initiated.
- **Evidence over claims.** "Done" = verified-and-running with a receipt (HBP chain).
- **Decided changes are mechanical** — `simplicio edit`, never hand-write the decided.
- **Config is untrusted** — load perception-shaping config only after review + hash-pin.

## When NOT to use

A single trivial edit or a plain question — the harness ceremony isn''t worth it; use
the deterministic fast path.

Attribution: harness concepts by affaan-m/ECC; this is a Simplicio-native adaptation
(contract + skill), not a copy of its source or its skill bundle.
','.claude\skills\ecc-harness\SKILL.md','d7f1f6b19aecd484d4cc33a4d126dc666d4cba708f6e8506aab226a770569597','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:email-template-builder','project_skill','skill://simplicio-runtime/email-template-builder','skill: email-template-builder','---
name: email-template-builder
description: "Build complete transactional email systems: React Email templates, provider integration (Resend, Postmark, SendGrid, AWS SES), preview server, i18n support, dark mode, spam optimization, analytics tracking. Use when adding transactional email to a new product, migrating between email providers, refactoring legacy email templates for accessibility, or adding internationalization to existing templates."
---

# Email Template Builder

**Tier:** POWERFUL  
**Category:** Engineering Team  
**Domain:** Transactional Email / Communications Infrastructure

---

## Overview

Build complete transactional email systems: React Email templates, provider integration, preview server, i18n support, dark mode, spam optimization, and analytics tracking. Output production-ready code for Resend, Postmark, SendGrid, or AWS SES.

---

## Core Capabilities

- React Email templates (welcome, verification, password reset, invoice, notification, digest)
- MJML templates for maximum email client compatibility
- Multi-provider support with unified sending interface
- Local preview server with hot reload
- i18n/localization with typed translation keys
- Dark mode support using media queries
- Spam score optimization checklist
- Open/click tracking with UTM parameters

---

## When to Use

- Setting up transactional email for a new product
- Migrating from a legacy email system
- Adding new email types (invoice, digest, notification)
- Debugging email deliverability issues
- Implementing i18n for email templates

---

## Project Structure

```
emails/
├── components/
│   ├── layout/
│   │   ├── email-layout.tsx       # Base layout with brand header/footer
│   │   └── email-button.tsx       # CTA button component
│   ├── partials/
│   │   ├── header.tsx
│   │   └── footer.tsx
├── templates/
│   ├── welcome.tsx
│   ├── verify-email.tsx
│   ├── password-reset.tsx
│   ├── invoice.tsx
│   ├── notification.tsx
│   └── weekly-digest.tsx
├── lib/
│   ├── send.ts                    # Unified send function
│   ├── providers/
│   │   ├── resend.ts
│   │   ├── postmark.ts
│   │   └── ses.ts
│   └── tracking.ts                # UTM + analytics
├── i18n/
│   ├── en.ts
│   └── de.ts
└── preview/                       # Dev preview server
    └── server.ts
```

---

## Base Email Layout

```tsx
// emails/components/layout/email-layout.tsx
import {
  Body, Container, Head, Html, Img, Preview, Section, Text, Hr, Font
} from "@react-email/components"

interface EmailLayoutProps {
  preview: string
  children: React.ReactNode
}

export function EmailLayout({ preview, children }: EmailLayoutProps) {
  return (
    <Html lang="en">
      <Head>
        <Font
          fontFamily="Inter"
          fallbackFontFamily="Arial"
          webFont={{ url: "https://fonts.gstatic.com/s/inter/v13/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMEVuLyfAZ9hiJ-Ek-_EeA.woff2", format: "woff2" }}
          fontWeight={400}
          fontStyle="normal"
        />
        {/* Dark mode styles */}
        <style>{`
          @media (prefers-color-scheme: dark) {
            .email-body { background-color: #0f0f0f !important; }
            .email-container { background-color: #1a1a1a !important; }
            .email-text { color: #e5e5e5 !important; }
            .email-heading { color: #ffffff !important; }
            .email-divider { border-color: #333333 !important; }
          }
        `}</style>
      </Head>
      <Preview>{preview}</Preview>
      <Body className="email-body" style={styles.body}>
        <Container className="email-container" style={styles.container}>
          {/* Header */}
          <Section style={styles.header}>
            <Img src="https://yourapp.com/logo.png" width={120} height={40} alt="MyApp" />
          </Section>
          
          {/* Content */}
          <Section style={styles.content}>
            {children}
          </Section>
          
          {/* Footer */}
          <Hr style={styles.divider} />
          <Section style={styles.footer}>
            <Text style={styles.footerText}>
              MyA','.claude\skills\email-template-builder\SKILL.md','32bfebf3e185070274879fc6ca38ef4ce35c6e5c240f4821ac73c1ecf2cedd2b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:emails','project_skill','skill://simplicio-runtime/emails','skill: emails','---
name: emails
description: When the user wants to create or optimize an email sequence, drip campaign, automated email flow, or lifecycle email program. Also use when the user mentions "email sequence," "drip campaign," "nurture sequence," "onboarding emails," "welcome sequence," "re-engagement emails," "email automation," "lifecycle emails," "trigger-based emails," "email funnel," "email workflow," "what emails should I send," "welcome series," or "email cadence." Use this for any multi-email automated flow. For cold outreach emails, see cold-email. For in-app onboarding, see onboarding.
metadata:
  version: 2.0.0
---

# Email Sequence Design

You are an expert in email marketing and automation. Your goal is to create email sequences that nurture relationships, drive action, and move people toward conversion.

## Initial Assessment

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Before creating a sequence, understand:

1. **Sequence Type**
   - Welcome/onboarding sequence
   - Lead nurture sequence
   - Re-engagement sequence
   - Post-purchase sequence
   - Event-based sequence
   - Educational sequence
   - Sales sequence

2. **Audience Context**
   - Who are they?
   - What triggered them into this sequence?
   - What do they already know/believe?
   - What''s their current relationship with you?

3. **Goals**
   - Primary conversion goal
   - Relationship-building goals
   - Segmentation goals
   - What defines success?

---

## Core Principles

### 1. One Email, One Job
- Each email has one primary purpose
- One main CTA per email
- Don''t try to do everything

### 2. Value Before Ask
- Lead with usefulness
- Build trust through content
- Earn the right to sell

### 3. Relevance Over Volume
- Fewer, better emails win
- Segment for relevance
- Quality > frequency

### 4. Clear Path Forward
- Every email moves them somewhere
- Links should do something useful
- Make next steps obvious

---

## Email Sequence Strategy

### Sequence Length
- Welcome: 3-7 emails
- Lead nurture: 5-10 emails
- Onboarding: 5-10 emails
- Re-engagement: 3-5 emails

Depends on:
- Sales cycle length
- Product complexity
- Relationship stage

### Timing/Delays
- Welcome email: Immediately
- Early sequence: 1-2 days apart
- Nurture: 2-4 days apart
- Long-term: Weekly or bi-weekly

Consider:
- B2B: Avoid weekends
- B2C: Test weekends
- Time zones: Send at local time

### Subject Line Strategy
- Clear > Clever
- Specific > Vague
- Benefit or curiosity-driven
- 40-60 characters ideal
- Test emoji (they''re polarizing)

**Patterns that work:**
- Question: "Still struggling with X?"
- How-to: "How to [achieve outcome] in [timeframe]"
- Number: "3 ways to [benefit]"
- Direct: "[First name], your [thing] is ready"
- Story tease: "The mistake I made with [topic]"

### Preview Text
- Extends the subject line
- ~90-140 characters
- Don''t repeat subject line
- Complete the thought or add intrigue

---

## Sequence Types Overview

### Welcome Sequence (Post-Signup)
**Length**: 5-7 emails over 12-14 days
**Goal**: Activate, build trust, convert

Key emails:
1. Welcome + deliver promised value (immediate)
2. Quick win (day 1-2)
3. Story/Why (day 3-4)
4. Social proof (day 5-6)
5. Overcome objection (day 7-8)
6. Core feature highlight (day 9-11)
7. Conversion (day 12-14)

### Lead Nurture Sequence (Pre-Sale)
**Length**: 6-8 emails over 2-3 weeks
**Goal**: Build trust, demonstrate expertise, convert

Key emails:
1. Deliver lead magnet + intro (immediate)
2. Expand on topic (day 2-3)
3. Problem deep-dive (day 4-5)
4. Solution framework (day 6-8)
5. Case study (day 9-11)
6. Differentiation (day 12-14)
7. Objection handler (day 15-18)
8. Direct offer (day 19-21)

### Re-Engagement Sequence
**Length**: 3-4 emails over 2 weeks
**Trigger**: 30-60 days of inactivity
**Goal**: Win back or clean list','.claude\skills\emails\SKILL.md','103f8f9368b960ba2a59c9c6a9a359414509373df445e2b55043360f7a7de4bd','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:embedded-captions','project_skill','skill://simplicio-runtime/embedded-captions','skill: embedded-captions','---
name: embedded-captions
description: ''Add captions to a talking-head video. ONE catalog (CATALOG.md) of 32 visual identities behind two engines: column-flow (captions composited INTO the scene — matte occlusion + mix-blend; cream/ink/editorial/keynote/documentary/loud/neon/glitch/chrome/velocity) and themed constitutions (anchor/ordnance/terminal/neonsign/stardust/stomp/scoreboard/transit/vhs/arcade/dossier/laser/thunder/hologram/biolume/aurora/spectrum/papercut/popup/chalkboard/graffiti/brush/inkwater/ransom/lastpage/nightcity — e.g. a glyph-decode climax, a neon sign WRITTEN stroke by stroke, or the quiet `anchor` rail default). Route by identity, never by mode. Trigger on "captions/subtitles", "embed/cinematic captions", "VFX captions", "炸/特效/酷炫字幕", a named identity, or top-tier motion-graphics asks. Embedding every word is wrong for most talking-head content — `anchor` is the verbatim default. Pipeline: transcription → hyperframes remove-background matting → HTML render → ffmpeg overlay. Requires hyperframes and a single-subject clip.''
metadata:
  tags: captions, embedded-captions, occlusion, matting, talking-head, rembg-matting, whisper, ffmpeg, cinematic
---

# Embedded Captions

**One catalog, picked up front** ([CATALOG.md](CATALOG.md) — 17 identities; the three engines behind it are backend detail). **Standard** (default) builds a clean verbatim **rail** (lower-third subtitle carrying most text) + an **embed** climax composited _into_ the scene behind the subject at the peak. **Cinematic** is pure embed — no rail, every caption composited behind the subject (hero typography, accumulation, occlusion as the effect). **Theme** is a complete themed constitution — body paradigm × hero setpiece × front fx × plate reaction, composed from registries ([themes/README.md](themes/README.md)): `ordnance` `terminal` `neonsign` `stardust` `stomp`. Most explainer / voiceover is **Standard**; **embed is the scarce, earned peak** — embedding every word is the common mistake; Theme is for VFX-grade asks ("炸", "特效", "像 AE 做的").

---

## Operational flow (TL;DR)

The craft prose below is long; the **pipeline itself is short** — and everything
deterministic is computed or compiled, never hand-written:

1. **Decision gate** (refuse bad clips) → **pick ONE identity from [CATALOG.md](CATALOG.md)** (17 identities; engine/compiler derived by lookup — never surface a mode/category question)
2. `hyperframes init` (skip it if the project dir already exists with the video inside — `matte.cjs`/`transcribe.cjs` adopt any video in the dir as source.mp4) → **`bash scripts/prepare.sh <project>`** (matte ∥ transcribe ∥ audio-envelope in parallel, then safe-zones v2 with scene palette/optics/lighting — one command, nothing forgotten)
3. **author a small JSON of creative choices** (read `safe-zones.json` first):
   Cinematic → `plan.json` → `fill-timings.cjs` → `fit-fonts.cjs` → `make-composition.cjs`;
   Theme → `theme.json` → `make-theme.cjs` (rail/panel/poem/takeover paradigms; `anchor` is the quiet rail default)
4. **Visual QA**: `node scripts/preview-frames.cjs <project>` → faithful composite previews in ~2s/frame (no render). Check § Visual QA before paying for a render.
5. `render-and-composite.sh` → gates (timing / occlusion+hero / overflow / hand-off) → `final.mp4`

Load-bearing rules people miss:

- **rail (default) + embed (promotion).** `drop` (filler, not shown) / `rail` (verbatim lower-third subtitle, in front, carries most text) / `embed` (a peak word composited behind the subject). **Standard mode does both**, embedding only the peak(s). See **§ Caption model**.
- **The video is delivered UNTOUCHED (Standard/Cinematic; **Theme mode''s PLATE budget is the one sanctioned exception** — register-gated reaction beats (charge-dim, punch, shake, grain) defined per theme DNA and applied AFTER the matte composite so subject+text+plate move as one frame)** — captions are the only thing added; the matte just lets the subject occlude the embed track. Never grade/recolor/scanline the footage.
- Two rulebooks: **rail → [references/rail.md](refer','.claude\skills\embedded-captions\SKILL.md','a2c536c8f09a16a76ee46e2a6f50be3c6d3701c5435373aebc5400de35f25f47','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:engineering-advanced-skills','project_skill','skill://simplicio-runtime/engineering-advanced-skills','skill: engineering-advanced-skills','---
name: engineering-advanced-skills
description: "Index of 37 advanced engineering agent skills for Claude Code, Codex, Gemini CLI, Cursor, OpenClaw. Use when browsing or choosing among the POWERFUL-tier engineering skills: agent design, RAG, MCP servers, CI/CD, database design, observability, security auditing, changelog/release automation, reliability (SLO/chaos/flags/operators), platform ops."
version: 2.9.0
author: Alireza Rezvani
license: MIT
tags:
  - engineering
  - architecture
  - agents
  - rag
  - mcp
  - ci-cd
  - observability
agents:
  - claude-code
  - codex-cli
  - openclaw
---

# Engineering Advanced Skills (POWERFUL Tier)

37 advanced engineering skills for complex architecture, automation, reliability, and platform operations.

## Quick Start

### Claude Code
```
/read engineering/skills/agent-designer/SKILL.md
```

### Codex CLI
```bash
npx agent-skills-cli add alirezarezvani/claude-skills/engineering
```

## Skills Overview

| Skill | Folder | Focus |
|-------|--------|-------|
| Agent Designer | `agent-designer/` | Multi-agent architecture: plan, schema-generate, evaluate |
| Agent Workflow Designer | `agent-workflow-designer/` | Workflow orchestration scaffolds |
| API Design Reviewer | `api-design-reviewer/` | REST/GraphQL linting, breaking changes |
| API Test Suite Builder | `api-test-suite-builder/` | API test generation |
| Browser Automation | `browser-automation/` | Playwright/Selenium automation patterns |
| Changelog Generator | `changelog-generator/` | Changelogs, semantic version bumps, hotfix/rollback discipline |
| Chaos Engineering | `chaos-engineering/` | Experiment design, blast-radius, postmortems |
| CI/CD Pipeline Builder | `ci-cd-pipeline-builder/` | Pipeline generation |
| Codebase Onboarding | `codebase-onboarding/` | New dev onboarding guides |
| Database Designer | `database-designer/` | Schema analysis, index optimization, migrations |
| Database Schema Designer | `database-schema-designer/` | ERD, normalization |
| Dependency Auditor | `dependency-auditor/` | Dependency security scanning |
| Env Secrets Manager | `env-secrets-manager/` | Secrets rotation, vault |
| Feature Flags Architect | `feature-flags-architect/` | Flag debt, rollout plans, kill switches |
| Focused Fix | `focused-fix/` | Systematic feature/module repair |
| Full Page Screenshot | `full-page-screenshot/` | Full-page capture tooling |
| Git Worktree Manager | `git-worktree-manager/` | Parallel branch workflows |
| Interview System Designer | `interview-system-designer/` | Hiring pipeline design |
| Kubernetes Operator | `kubernetes-operator/` | CRD validation, reconcile linting |
| MCP Server Builder | `mcp-server-builder/` | MCP tool creation |
| Migration Architect | `migration-architect/` | System migration planning |
| Monorepo Navigator | `monorepo-navigator/` | Monorepo tooling |
| Observability Designer | `observability-designer/` | Dashboards, alert noise (SLOs → slo-architect) |
| Performance Profiler | `performance-profiler/` | CPU, memory, load profiling |
| PR Review Expert | `pr-review-expert/` | Pull request analysis |
| RAG Architect | `rag-architect/` | RAG design, chunking, retrieval evaluation |
| Runbook Generator | `runbook-generator/` | Operational runbooks |
| Secrets Vault Manager | `secrets-vault-manager/` | Vault patterns, HCL |
| Self-Eval | `self-eval/` | Honest work-quality scoring |
| Ship Gate | `ship-gate/` | Pre-production audit (89 checks) |
| Skill Security Auditor | `skill-security-auditor/` | Skill vulnerability scanning |
| Skill Tester | `skill-tester/` | Skill quality evaluation |
| SLO Architect | `slo-architect/` | SLO/SLI design, error budgets, burn-rate alerts |
| Spec-Driven Workflow | `spec-driven-workflow/` | Spec-first development gates |
| SQL Database Assistant | `sql-database-assistant/` | Query optimization, 4 dialects |
| TC Tracker | `tc-tracker/` | Task context lifecycle + handoffs |
| Tech Debt Tracker | `tech-debt-tracker/` | Debt scan → prioritize → dashboard |

Note: release management merged into `changelog-generator/` (version bumper + hotfix','.claude\skills\engineering-advanced-skills\SKILL.md','935ce0acbddd7604144178990663b1a22eb2ed62d196f6b2314756b4e2c511c7','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:engineering-skills','project_skill','skill://simplicio-runtime/engineering-skills','skill: engineering-skills','---
name: engineering-skills
description: "Index of the engineering-team skills bundle for Claude Code, Codex, Gemini CLI, Cursor, OpenClaw, and 6 more tools. Architecture, frontend, backend, QA, DevOps, security, AI/ML, data engineering, Playwright, Stripe, AWS, MS365 (stdlib-only Python tools). Use when browsing or choosing among engineering-team role skills — load only the one specialist SKILL.md you need, never bulk-load the bundle."
version: 2.9.0
author: Alireza Rezvani
license: MIT
tags:
  - engineering
  - frontend
  - backend
  - devops
  - security
  - ai-ml
  - data-engineering
agents:
  - claude-code
  - codex-cli
  - openclaw
---

# Engineering Team Skills

32 production-ready engineering skills organized into core engineering, security, AI/ML/Data, and specialized tools.

## Quick Start

### Claude Code
```
/read engineering-team/skills/senior-fullstack/SKILL.md
```

### Codex CLI
```bash
npx agent-skills-cli add alirezarezvani/claude-skills/engineering-team
```

## Skills Overview

### Core Engineering (13 skills)

| Skill | Folder | Focus |
|-------|--------|-------|
| Senior Architect | `senior-architect/` | System design, architecture patterns |
| Senior Frontend | `senior-frontend/` | React, Next.js, TypeScript, Tailwind |
| Senior Backend | `senior-backend/` | API design, database optimization |
| Senior Fullstack | `senior-fullstack/` | Project scaffolding, code quality |
| Senior QA | `senior-qa/` | Test generation, coverage analysis |
| Senior DevOps | `senior-devops/` | CI/CD, infrastructure, containers |
| Senior SecOps | `senior-secops/` | Security operations, vulnerability management |
| Code Reviewer | `code-reviewer/` | PR review, code quality analysis |
| Senior Security | `senior-security/` | Threat modeling, STRIDE, penetration testing |
| AWS Solution Architect | `aws-solution-architect/` | Serverless, CloudFormation, cost optimization |
| MS365 Tenant Manager | `ms365-tenant-manager/` | Microsoft 365 administration |
| TDD Guide | `tdd-guide/` | Test-driven development workflows |
| Tech Stack Evaluator | `tech-stack-evaluator/` | Technology comparison, TCO analysis |

### AI/ML/Data (5 skills)

| Skill | Folder | Focus |
|-------|--------|-------|
| Senior Data Scientist | `senior-data-scientist/` | Statistical modeling, experimentation |
| Senior Data Engineer | `senior-data-engineer/` | Pipelines, ETL, data quality |
| Senior ML Engineer | `senior-ml-engineer/` | Model deployment, MLOps, LLM integration |
| Senior Prompt Engineer | `senior-prompt-engineer/` | Prompt optimization, RAG, agents |
| Senior Computer Vision | `senior-computer-vision/` | Object detection, segmentation |

### Specialized Tools (5 skills)

| Skill | Folder | Focus |
|-------|--------|-------|
| Playwright Pro | `playwright-pro/` | E2E testing (9 sub-skills) |
| Self-Improving Agent | `self-improving-agent/` | Memory curation (5 sub-skills) |
| Stripe Integration | `stripe-integration-expert/` | Payment integration, webhooks |
| Incident Commander | `incident-commander/` | Incident response workflows |
| Email Template Builder | `email-template-builder/` | HTML email generation |

## Python Tools

30+ scripts, all stdlib-only. Run directly:

```bash
python3 <skill>/scripts/<tool>.py --help
```

No pip install needed. Scripts include embedded samples for demo mode.

## Rules

- Load only the specific skill SKILL.md you need — don''t bulk-load all 32
- Use Python tools for analysis and scaffolding, not manual judgment
- Check CLAUDE.md for tool usage examples and workflows

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering-team. -->
','.claude\skills\engineering-skills\SKILL.md','6c8207233dcbd27fc60e7065734972e70050be8af9d3e8b064d2962563e5a971','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:entity-compliance','project_skill','skill://simplicio-runtime/entity-compliance','skill: entity-compliance','---
name: entity-compliance
description: >
  Entity compliance tracker — initialize, report upcoming deadlines, update
  status, run health audit, export to CSV. Maintains a compliance-tracker.yaml
  built from the entity table, calculates filing deadlines by entity and
  jurisdiction, and surfaces what''s due in the next 30/60/90 days. Use when
  user says "entity compliance", "filing deadlines", "annual reports due",
  "entity tracker", "what filings are due", "entity health", or "good standing".
argument-hint: "[--init | --report [--days N] | --update [--from-report] | --sweep | --audit | --export [--format csv|table]]"
---

# /entity-compliance

1. Load `~/.claude/plugins/config/claude-for-legal/corporate-legal/CLAUDE.md` → `## Entity Management` (entity table, jurisdictions, registered agent).
2. Route to the correct mode below based on flag:
   - No flag or `--init`: Mode 1 — initialize tracker from entity table
   - `--report`: Mode 2 — surface upcoming deadlines and overdue items
   - `--update`: Mode 3a (manual) or 3b (--from-report upload) — update status
   - `--sweep`: Mode 3c — walk through unknown/overdue items one by one
   - `--audit`: Mode 4 — full health audit
   - `--export`: Mode 5 — produce CSV or table export
3. Read/write `~/.claude/plugins/config/claude-for-legal/corporate-legal/entities/compliance-tracker.yaml`.
4. After any update: show summary of changes and next action.

---

## Purpose

Annual reports, franchise taxes, Statements of Information, biennial filings —
every entity in every state has its own schedule and its own consequences for
missing the deadline. This skill maintains a single YAML tracker that knows
what''s due, when, and for which entity. It''s lightweight by design: the tracker
is a file you own, Claude updates it on command, and you export it when you need
to share it.

## Important: deadline reference caveat

> The filing deadlines in this skill''s reference table reflect publicly available
> requirements as of the skill''s build date. State filing requirements and due
> dates can change. **Always confirm deadlines with your registered agent or
> directly with the relevant Secretary of State before relying on them for
> compliance purposes.** If you use CT Corp, National Registered Agents, or
> another registered agent service, their compliance calendar is authoritative
> for your specific entities — use this tracker to organize and surface their
> data, not to replace it.

## Jurisdiction assumption

> This tracker computes deadlines against the state or country of formation / qualification recorded per entity. Filing rules, due-date mechanics, and fee structures vary materially by jurisdiction. If an entity''s actual footprint differs from what''s in `~/.claude/plugins/config/claude-for-legal/corporate-legal/CLAUDE.md` (undisclosed foreign qualification, dissolved entities, jurisdictional re-domestication, international filings managed by a local agent), the output may not apply as written — confirm with the registered agent or local counsel for that jurisdiction.

## Entity-type disambiguation (especially Delaware)

> The filing calendar depends on **entity type**, not just jurisdiction. Treating a "Delaware entity" as a single bucket is a common and consequential error — DE corporations, DE LLCs, and DE LPs have different filings, different deadlines, and different consequences for a miss. Confirm the entity type from the entity table before computing or reporting a deadline, and never copy a deadline from one entity-type to another in the same state.
>
> **Delaware — the split that matters:**
>
> - **DE Corporation (Inc., Corp.):** Annual report AND franchise tax, both due **March 1**. Franchise tax is calculated by the authorized-shares method or the assumed-par-value capital method (whichever is lower); the annual report captures director / officer information. Statutory basis: 8 Del. C. §§ 501–502 [verify current].
> - **DE LLC:** No annual report required. Annual tax is a **flat $300**, due **June 1**. Statutory basis: 6 Del. C. § 18-1107(d) [verify current fee and date]','.claude\skills\entity-compliance\SKILL.md','9ec006328bc44cc39b204e7c7159cd377e69c33f43d4099fa4d787e2dbca1d3f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:entry-point-analyzer','project_skill','skill://simplicio-runtime/entry-point-analyzer','skill: entry-point-analyzer','---
name: entry-point-analyzer
description: Analyzes smart contract codebases to identify state-changing entry points for security auditing. Detects externally callable functions that modify state, categorizes them by access level (public, admin, role-restricted, contract-only), and generates structured audit reports. Excludes view/pure/read-only functions. Use when auditing smart contracts (Solidity, Vyper, Solana/Rust, Move, TON, CosmWasm) or when asked to find entry points, audit flows, external functions, access control patterns, or privileged operations.
allowed-tools: Read Grep Glob Bash
---

# Entry Point Analyzer

Systematically identify all **state-changing** entry points in a smart contract codebase to guide security audits.

## When to Use

Use this skill when:
- Starting a smart contract security audit to map the attack surface
- Asked to find entry points, external functions, or audit flows
- Analyzing access control patterns across a codebase
- Identifying privileged operations and role-restricted functions
- Building an understanding of which functions can modify contract state

## When NOT to Use

Do NOT use this skill for:
- Vulnerability detection (use audit-context-building or domain-specific-audits)
- Writing exploit POCs (use solidity-poc-builder)
- Code quality or gas optimization analysis
- Non-smart-contract codebases
- Analyzing read-only functions (this skill excludes them)

## Scope: State-Changing Functions Only

This skill focuses exclusively on functions that can modify state. **Excluded:**

| Language | Excluded Patterns |
|----------|-------------------|
| Solidity | `view`, `pure` functions |
| Vyper | `@view`, `@pure` functions |
| Solana | Functions without `mut` account references |
| Move | Non-entry `public fun` (module-callable only) |
| TON | `get` methods (FunC), read-only receivers (Tact) |
| CosmWasm | `query` entry point and its handlers |

**Why exclude read-only functions?** They cannot directly cause loss of funds or state corruption. While they may leak information, the primary audit focus is on functions that can change state.

## Workflow

1. **Detect Language** - Identify contract language(s) from file extensions and syntax
2. **Use Tooling (if available)** - For Solidity, check if Slither is available and use it
3. **Locate Contracts** - Find all contract/module files (apply directory filter if specified)
4. **Extract Entry Points** - Parse each file for externally callable, state-changing functions
5. **Classify Access** - Categorize each function by access level
6. **Generate Report** - Output structured markdown report

## Slither Integration (Solidity)

For Solidity codebases, Slither can automatically extract entry points. Before manual analysis:

### 1. Check if Slither is Available

```bash
which slither
```

### 2. If Slither is Detected, Run Entry Points Printer

```bash
slither . --print entry-points
```

This outputs a table of all state-changing entry points with:
- Contract name
- Function name
- Visibility
- Modifiers applied

### 3. Use Slither Output as Foundation

- Parse the Slither output table to populate your analysis
- Cross-reference with manual inspection for access control classification
- Slither may miss some patterns (callbacks, dynamic access control)—supplement with manual review
- If Slither fails (compilation errors, unsupported features), fall back to manual analysis

### 4. When Slither is NOT Available

If `which slither` returns nothing, proceed with manual analysis using the language-specific reference files.

## Language Detection

| Extension | Language | Reference |
|-----------|----------|-----------|
| `.sol` | Solidity | [{baseDir}/references/solidity.md]({baseDir}/references/solidity.md) |
| `.vy` | Vyper | [{baseDir}/references/vyper.md]({baseDir}/references/vyper.md) |
| `.rs` + `Cargo.toml` with `solana-program` | Solana (Rust) | [{baseDir}/references/solana.md]({baseDir}/references/solana.md) |
| `.move` + `Move.toml` with `edition` | [{baseDir}/references/move-sui.md]({baseDir}/references/move-sui.md) |
| `.move` + `Move.','.claude\skills\entry-point-analyzer\SKILL.md','0d1773a51c3484c8f4471b515340a0a27fc4402f557f2f494ce9c5c26a018b79','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:env-secrets-manager','project_skill','skill://simplicio-runtime/env-secrets-manager','skill: env-secrets-manager','---
name: env-secrets-manager
description: "Manage environment-variable hygiene and secrets safety across local development and production. Practical auditing, drift awareness, rotation readiness. Use when auditing .env files for committed secrets, planning a credential rotation, debugging missing-env-var production incidents, or hardening a new project against secrets leakage."
---

# Env & Secrets Manager

**Tier:** POWERFUL
**Category:** Engineering
**Domain:** Security / DevOps / Configuration Management

---

## Overview

Manage environment-variable hygiene and secrets safety across local development and production workflows. This skill focuses on practical auditing, drift awareness, and rotation readiness.

## Core Capabilities

- `.env` and `.env.example` lifecycle guidance
- Secret leak detection for repository working trees
- Severity-based findings for likely credentials
- Operational pointers for rotation and containment
- Integration-ready outputs for CI checks

---

## When to Use

- Before pushing commits that touched env/config files
- During security audits and incident triage
- When onboarding contributors who need safe env conventions
- When validating that no obvious secrets are hardcoded

---

## Quick Start

```bash
# Scan a repository for likely secret leaks
python3 scripts/env_auditor.py /path/to/repo

# JSON output for CI pipelines
python3 scripts/env_auditor.py /path/to/repo --json
```

---

## Recommended Workflow

1. Run `scripts/env_auditor.py` on the repository root.
2. Prioritize `critical` and `high` findings first.
3. Rotate real credentials and remove exposed values.
4. Update `.env.example` and `.gitignore` as needed.
5. Add or tighten pre-commit/CI secret scanning gates.

---

## Reference Docs

- `references/validation-detection-rotation.md`
- `references/secret-patterns.md`

---

## Common Pitfalls

- Committing real values in `.env.example`
- Rotating one system but missing downstream consumers
- Logging secrets during debugging or incident response
- Treating suspected leaks as low urgency without validation

## Best Practices

1. Use a secret manager as the production source of truth.
2. Keep dev env files local and gitignored.
3. Enforce detection in CI before merge.
4. Re-test application paths immediately after credential rotation.

---

## Cloud Secret Store Integration

Production applications should never read secrets from `.env` files or environment variables baked into container images. Use a dedicated secret store instead.

### Provider Comparison

| Provider | Best For | Key Feature |
|----------|----------|-------------|
| **HashiCorp Vault** | Multi-cloud / hybrid | Dynamic secrets, policy engine, pluggable backends |
| **AWS Secrets Manager** | AWS-native workloads | Native Lambda/ECS/EKS integration, automatic RDS rotation |
| **Azure Key Vault** | Azure-native workloads | Managed HSM, Azure AD RBAC, certificate management |
| **GCP Secret Manager** | GCP-native workloads | IAM-based access, automatic replication, versioning |

### Selection Guidance

- **Single cloud provider** — use the cloud-native secret manager. It integrates tightly with IAM, reduces operational overhead, and costs less than self-hosting.
- **Multi-cloud or hybrid** — use HashiCorp Vault. It provides a uniform API across environments and supports dynamic secret generation (database credentials, cloud IAM keys) that expire automatically.
- **Kubernetes-heavy** — combine External Secrets Operator with any backend above to sync secrets into K8s `Secret` objects without hardcoding.

### Application Access Patterns

1. **SDK/API pull** — application fetches secret at startup or on-demand via provider SDK.
2. **Sidecar injection** — a sidecar container (e.g., Vault Agent) writes secrets to a shared volume or injects them as environment variables.
3. **Init container** — a Kubernetes init container fetches secrets before the main container starts.
4. **CSI driver** — secrets mount as a filesystem volume via the Secrets Store CSI Driver.

> **Cross-reference:** See `engineering/secrets-vault-manager` fo','.claude\skills\env-secrets-manager\SKILL.md','c78a9c42c4221da08628c9e546a430b3137837ccb0d7e64eeb6064c390c355c9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:epic-design','project_skill','skill://simplicio-runtime/epic-design','skill: epic-design','---
name: epic-design
description: >
  Build immersive, cinematic 2.5D interactive websites using scroll storytelling,
  parallax depth, text animations, and premium scroll effects — no WebGL required.
  Use this skill for any web design task: landing pages, product sites, hero sections,
  scroll animations, parallax, sticky sections, section overlaps, floating products
  between sections, clip-path reveals, text that flies in from sides, words that light
  up on scroll, curtain drops, iris opens, card stacks, bleed typography, and any
  site that should feel cinematic or premium. Trigger on phrases like "make it feel
  alive", "Apple-style animation", "sections that overlap", "product rises between
  sections", "immersive", "scrollytelling", or any scroll-driven visual effect.
  Covers 45+ techniques across 8 categories. Always inspects, judges, and plans assets before coding. Use aggressively for ANY web design task.
license: MIT
metadata:
  version: 1.0.0
  author: Abbas Mir
  category: engineering-team
  updated: 2026-03-13
---

# Epic Design Skill

You are now a **world-class epic design expert**. You build cinematic, immersive websites that feel premium and alive — using only flat PNG/static assets, CSS, and JavaScript. No WebGL, no 3D modeling software required.

## Before Starting

**Check for context first:**
If `project-context.md` or `product-context.md` exists, read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

## Your Mindset

Every website you build must feel like a **cinematic experience**. Think: Apple product pages, Awwwards winners, luxury brand sites. Even a simple landing page should have:
- Depth and layers that respond to scroll
- Text that enters and exits with intention
- Sections that transition cinematically
- Elements that feel like they exist in space

**Never build a flat, static page when this skill is active.**

---

## How This Skill Works

### Mode 1: Build from Scratch
When starting fresh with assets and a brief. Follow the complete workflow below (Steps 1-5).

### Mode 2: Enhance Existing Site
When adding 2.5D effects to an existing page. Skip to Step 2, analyze current structure, recommend depth assignments and animation opportunities.

### Mode 3: Debug/Fix
When troubleshooting performance or animation issues. Use `scripts/validate-layers.js`, check GPU rules, verify reduced-motion handling.

---

## Step 1 — Understand the Brief + Inspect All Assets

Before writing a single line of code, do ALL of the following in order.

### A. Extract the brief
1. What is the product/content? (brand site, portfolio, SaaS, event, etc.)
2. What mood/feeling? (dark/cinematic, bright/energetic, minimal/luxury, etc.)
3. How many sections? (hero only, full page, specific section?)

### B. Inspect every uploaded image asset

Run `scripts/inspect-assets.py` on every image the user has provided.
> **Optional runtime dependency:** `pip install Pillow` — required for image analysis, not for `--help`.
For each image, determine:

1. **Format** — JPEG never has a real alpha channel. PNG may have a fake one.

2. **Background status** — Use the script output. It will tell you:
   - ✅ Clean cutout — real transparency, use directly
   - ⚠️ Solid dark background
   - ⚠️ Solid light/white background
   - ⚠️ Complex/scene background

3. **JUDGE whether the background actually needs removing** — This is critical.
   Not every image with a background needs it removed. Ask yourself:

   BACKGROUND SHOULD BE REMOVED if the image is:
   - An isolated product (bottle, shoe, gadget, fruit, object on studio backdrop)
   - A character or figure meant to float in the scene
   - A logo or icon that should sit transparently on any background
   - Any element that will be placed at depth-2 or depth-3 as a floating asset

   BACKGROUND SHOULD BE KEPT if the image is:
   - A screenshot of a website, app, or UI
   - A photograph used as a section background or full-bleed image
   - An artwork, illustration, or poster meant to be seen as a complete piece
   - A ','.claude\skills\epic-design\SKILL.md','03a56ebc509afd70695a2c831089f084bf86e6602cf717379a72655bc40fa6e1','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:escalation-flagger','project_skill','skill://simplicio-runtime/escalation-flagger','skill: escalation-flagger','---
name: escalation-flagger
description: >
  Route a contract issue to the right approver per the escalation matrix in
  `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md`, and draft the ask. Use when the user
  says "who needs to approve this", "escalate this", "does this need GC sign-off",
  "route this for approval", or when another skill finds an issue that exceeds the
  reviewer''s authority.
argument-hint: "[describe the issue, or reference a review memo]"
---

# /escalation-flagger

Names the approver for a contract issue per the `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md` escalation matrix and drafts the message so you''re not writing "hey got a sec" at 5pm.

## Instructions

1. **Load `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md`** → Escalation section. If missing, say so — the practice profile needs editing.

2. **Characterize the issue:** dollar threshold / term deviation / automatic trigger / business decision.

3. **Match to matrix, name the approver.** Be specific — a person or role, not "legal leadership."

4. **Draft the ask** per the template below: what the contract says, what playbook says, options with recommendation, decision-by date.

5. **Do not send.** Draft it, show it, let the lawyer send.

## Examples

```
/commercial-legal:escalation-flagger
The Acme MSA has uncapped liability — who approves and what do I say?
```

```
/commercial-legal:escalation-flagger
Reference: acme-review-memo.md
Issue: §8.2 indemnity carveouts
```

---

## Matter context

**Matter context.** Check `## Matter workspaces` in the practice-level CLAUDE.md. If `Enabled` is `✗` (the default for in-house users), skip the rest of this paragraph — skills use practice-level context and the matter machinery is invisible. If enabled and there is no active matter, ask: "Which matter is this for? Run `/commercial-legal:matter-workspace switch <slug>` or say `practice-level`." Load the active matter''s `matter.md` for matter-specific context and overrides. Write outputs to the matter folder at `~/.claude/plugins/config/claude-for-legal/commercial-legal/matters/<matter-slug>/`. Never read another matter''s files unless `Cross-matter context` is `on`.

---

## Purpose

Every contracts team has an escalation matrix, written or not. This skill reads the written one (in `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md`), matches a contract issue against it, names the approver, and drafts the ask so the lawyer isn''t writing "hey do you have a sec" messages at 5pm.

## Load the matrix

**Which side?** Before matching to the matrix, determine which side the company is on for the contract whose issue is being escalated. Usually obvious: if the counterparty is a vendor/supplier providing goods or services, you''re purchasing-side. If the counterparty is a customer buying your product/service, you''re sales-side. If it''s not obvious, ask. Read the matching playbook section (`### Sales-side playbook` or `### Purchasing-side playbook`) to evaluate whether the term is inside fallbacks or triggers an automatic escalation — a term that''s fine on one side can be a hard-no on the other. Note which side in the drafted ask so the approver knows which playbook was applied.

Read `~/.claude/plugins/config/claude-for-legal/commercial-legal/CLAUDE.md` → `## Escalation`. If it''s missing or vague, say so — the cold-start interview should have captured this, and if it didn''t, the practice profile needs editing.

Expected structure:

| Can approve | Threshold | Escalates to | Via |
|---|---|---|---|
| Paralegal | Standard terms, <$50K | Counsel | Slack |
| Counsel | Non-standard but within fallbacks, <$500K | GC | Slack or email |
| GC | Everything else | CFO/Board | Meeting |

Plus **automatic escalation triggers** — things that escalate regardless of dollar value. Typically: unlimited liability, IP assignment, anything on the "never accept" lists.

## Workflow

### Step 1: Characterize the issue

What''s being escalated?

- **Dollar threshold:** Contract value exceeds someon','.claude\skills\escalation-flagger\SKILL.md','2517d861136e7a17a11f47dc6d67760b9f20f4eaf54398bf3ac657685909b01b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:eu-ai-act-specialist','project_skill','skill://simplicio-runtime/eu-ai-act-specialist','skill: eu-ai-act-specialist','---
name: eu-ai-act-specialist
description: "EU AI Act (Regulation (EU) 2024/1689) operational compliance for compliance teams. Three Article-level decisions: (1) What''s the risk tier of this AI system — prohibited (Art. 5), high-risk (Art. 6 + Annex III), limited-risk (Art. 50), or minimal-risk? (2) For high-risk systems, what''s the Article 43 conformity assessment route (Module A internal control vs Module H full QMS + notified body) and what goes in the Annex IV technical documentation? (3) Per organizational role (provider / deployer / importer / distributor / authorized representative), what are the active obligations and deadlines? Use during AI system intake review, when planning conformity assessment, or when scoping deployer obligations. Cites Articles + Annexes for every output. NOT executive AI strategy (see chief-ai-officer-advisor). NOT a legal substitute."
license: MIT
metadata:
  version: 1.0.0
  author: Alireza Rezvani
  category: ra-qm-team
  domain: eu-ai-act-compliance
  updated: 2026-05-13
  python-tools: ai_system_risk_classifier.py, conformity_assessment_planner.py, ai_act_obligation_tracker.py
  frameworks: eu-ai-act, gdpr-overlap, iso-42001-mapping, nist-ai-rmf-mapping
---

# EU AI Act Compliance Specialist

Article-cited operational skill for Regulation (EU) 2024/1689. **Three decisions, no executive AI strategy:**

1. **What tier is this AI system?** — prohibited (Article 5) / high-risk (Article 6 + Annex III) / limited-risk transparency (Article 50) / minimal-risk
2. **For high-risk systems, what''s the conformity assessment route + documentation pack?** — Article 43 Module A vs Module H + Annex IV technical documentation
3. **Per organizational role, what are the obligations?** — provider / deployer / importer / distributor / authorized representative matrix per Article 16, 22, 25, 26

This skill is **NOT chief-ai-officer-advisor**. CAIO decides whether to ship the AI feature at all and accepts business risk. This skill operates the conformity work that turns "we''ll ship it" into Article-compliant artefacts.

This skill is **NOT a legal substitute**. The Act is binding regulation. For novel cases (Is this a GPAI model? Does Article 6(2) carve-out apply? Is fine-tuning a foundation model "substantial modification"?), engage qualified outside counsel. The skill cites Articles + Annexes and uses Commission/EDPB published interpretation but does not provide binding legal opinion.

This skill is **NOT GDPR**. Many AI systems also trigger GDPR (training data, output processing). See `ra-qm-team/skills/gdpr-dsgvo-expert/` for DPIA + lawful basis work. The Acts interact (Recital 10, Article 10 for high-risk training data).

## Keywords

EU AI Act, EU AI Regulation, Regulation 2024/1689, AI Act, AI regulation Europe, high-risk AI, prohibited AI, Article 5 AI Act, Article 6 AI Act, Article 9 AI Act, Article 50 AI Act, Annex III, Annex IV, conformity assessment, CE marking AI, notified body AI, Module A, Module H, technical documentation AI, post-market monitoring AI, fundamental rights impact assessment, FRIA, GPAI, general-purpose AI model, systemic risk GPAI, AI Office, ENISA AI, EDPB AI, AI Act timeline, AI Act penalties, EU AI Act provider, EU AI Act deployer, EU AI Act importer, EU AI Act distributor, EU AI Act fines, AI literacy

## Quick Start

```bash
# Decision A: Classify an AI system per the Act
python scripts/ai_system_risk_classifier.py                       # embedded 5-system sample
python scripts/ai_system_risk_classifier.py path/to/systems.json

# Decision B: Conformity assessment plan for a high-risk system
python scripts/conformity_assessment_planner.py                   # embedded high-risk sample
python scripts/conformity_assessment_planner.py path/to/system.json

# Decision C: Obligation tracker per organizational role
python scripts/ai_act_obligation_tracker.py                       # embedded sample (provider + deployer)
python scripts/ai_act_obligation_tracker.py path/to/roles.json
```

## Key Questions (ask these first)

- **Does this AI system fall under Article 5 (prohibited p','.claude\skills\eu-ai-act-specialist\SKILL.md','1bd062321930671ad66cee27988b98946080dd141879dd7f8d69f5a70526912d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:eval','project_skill','skill://simplicio-runtime/eval','skill: eval','---
name: eval
description: "Evaluate and rank agent results by metric or LLM judge for an AgentHub session. Use when the user runs /hub:eval or asks to score, compare, or pick a winner among completed AgentHub agents."
command: /hub:eval
---

# /hub:eval — Evaluate Agent Results

Rank all agent results for a session. Supports metric-based evaluation (run a command), LLM judge (compare diffs), or hybrid.

## Usage

```
/hub:eval                           # Eval latest session using configured criteria
/hub:eval 20260317-143022           # Eval specific session
/hub:eval --judge                   # Force LLM judge mode (ignore metric config)
```

## What It Does

### Metric Mode (eval command configured)

Run the evaluation command in each agent''s worktree:

```bash
python {skill_path}/scripts/result_ranker.py \
  --session {session-id} \
  --eval-cmd "{eval_cmd}" \
  --metric {metric} --direction {direction}
```

Output:
```
RANK  AGENT       METRIC      DELTA      FILES
1     agent-2     142ms       -38ms      2
2     agent-1     165ms       -15ms      3
3     agent-3     190ms       +10ms      1

Winner: agent-2 (142ms)
```

### LLM Judge Mode (no eval command, or --judge flag)

For each agent:
1. Get the diff: `git diff {base_branch}...{agent_branch}`
2. Read the agent''s result post from `.agenthub/board/results/agent-{i}-result.md`
3. Compare all diffs and rank by:
   - **Correctness** — Does it solve the task?
   - **Simplicity** — Fewer lines changed is better (when equal correctness)
   - **Quality** — Clean execution, good structure, no regressions

Present rankings with justification.

Example LLM judge output for a content task:
```
RANK  AGENT    VERDICT                               WORD COUNT
1     agent-1  Strong narrative, clear CTA            1480
2     agent-3  Good data points, weak intro           1520
3     agent-2  Generic tone, no differentiation       1350

Winner: agent-1 (strongest narrative arc and call-to-action)
```

### Hybrid Mode

1. Run metric evaluation first
2. If top agents are within 10% of each other, use LLM judge to break ties
3. Present both metric and qualitative rankings

## After Eval

1. Update session state:
```bash
python {skill_path}/scripts/session_manager.py --update {session-id} --state evaluating
```

2. Tell the user:
   - Ranked results with winner highlighted
   - Next step: `/hub:merge` to merge the winner
   - Or `/hub:merge {session-id} --agent {winner}` to be explicit

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\eval\SKILL.md','324b529c75defc454cfac95dd04f260bb616e2b5117e120cabf5d4e7171706ce','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:experiment-designer','project_skill','skill://simplicio-runtime/experiment-designer','skill: experiment-designer','---
name: experiment-designer
description: Use when planning product experiments, writing testable hypotheses, estimating sample size, prioritizing tests, or interpreting A/B outcomes with practical statistical rigor.
---

# Experiment Designer

Design, prioritize, and evaluate product experiments with clear hypotheses and defensible decisions.

## When To Use

Use this skill for:
- A/B and multivariate experiment planning
- Hypothesis writing and success criteria definition
- Sample size and minimum detectable effect planning
- Experiment prioritization with ICE scoring
- Reading statistical output for product decisions

## Core Workflow

1. Write hypothesis in If/Then/Because format
- If we change `[intervention]`
- Then `[metric]` will change by `[expected direction/magnitude]`
- Because `[behavioral mechanism]`

2. Define metrics before running test
- Primary metric: single decision metric
- Guardrail metrics: quality/risk protection
- Secondary metrics: diagnostics only

3. Estimate sample size
- Baseline conversion or baseline mean
- Minimum detectable effect (MDE)
- Significance level (alpha) and power

Use:
```bash
python3 scripts/sample_size_calculator.py --baseline-rate 0.12 --mde 0.02 --mde-type absolute
```

4. Prioritize experiments with ICE
- Impact: potential upside
- Confidence: evidence quality
- Ease: cost/speed/complexity

ICE Score = (Impact * Confidence * Ease) / 10

5. Launch with stopping rules
- Decide fixed sample size or fixed duration in advance
- Avoid repeated peeking without proper method
- Monitor guardrails continuously

6. Interpret results
- Statistical significance is not business significance
- Compare point estimate + confidence interval to decision threshold
- Investigate novelty effects and segment heterogeneity

## Hypothesis Quality Checklist

- [ ] Contains explicit intervention and audience
- [ ] Specifies measurable metric change
- [ ] States plausible causal reason
- [ ] Includes expected minimum effect
- [ ] Defines failure condition

## Common Experiment Pitfalls

- Underpowered tests leading to false negatives
- Running too many simultaneous changes without isolation
- Changing targeting or implementation mid-test
- Stopping early on random spikes
- Ignoring sample ratio mismatch and instrumentation drift
- Declaring success from p-value without effect-size context

## Statistical Interpretation Guardrails

- p-value < alpha indicates evidence against null, not guaranteed truth.
- Confidence interval crossing zero/no-effect means uncertain directional claim.
- Wide intervals imply low precision even when significant.
- Use practical significance thresholds tied to business impact.

See:
- `references/experiment-playbook.md`
- `references/statistics-reference.md`

## Tooling

### `scripts/sample_size_calculator.py`

Computes required sample size (per variant and total) from:
- baseline rate
- MDE (absolute or relative)
- significance level (alpha)
- statistical power

Example:
```bash
python3 scripts/sample_size_calculator.py \
  --baseline-rate 0.10 \
  --mde 0.015 \
  --mde-type absolute \
  --alpha 0.05 \
  --power 0.8
```

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: product-team. -->
','.claude\skills\experiment-designer\SKILL.md','6bf9fb6167ee71cecb613aa1af23e45f3eadf2f60b6b04f97bf890a0e9ca8374','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:extract','project_skill','skill://simplicio-runtime/extract','skill: extract','---
name: extract
description: "Turn a proven pattern or debugging solution into a standalone reusable skill with SKILL.md, reference docs, and examples. Use when the user runs /si:extract or asks to package a recurring solution from memory into a skill."
---

# /si:extract — Create Skills from Patterns

Transforms a recurring pattern or debugging solution into a standalone, portable skill that can be installed in any project.

## Usage

```
/si:extract <pattern description>                  # Interactive extraction
/si:extract <pattern> --name docker-m1-fixes       # Specify skill name
/si:extract <pattern> --output ./skills/            # Custom output directory
/si:extract <pattern> --dry-run                     # Preview without creating files
```

## When to Extract

A learning qualifies for skill extraction when ANY of these are true:

| Criterion | Signal |
|---|---|
| **Recurring** | Same issue across 2+ projects |
| **Non-obvious** | Required real debugging to discover |
| **Broadly applicable** | Not tied to one specific codebase |
| **Complex solution** | Multi-step fix that''s easy to forget |
| **User-flagged** | "Save this as a skill", "I want to reuse this" |

## Workflow

### Step 1: Identify the pattern

Read the user''s description. Search auto-memory for related entries:

```bash
MEMORY_DIR="$HOME/.claude/projects/$(pwd | sed ''s|/|%2F|g; s|%2F|/|; s|^/||'')/memory"
grep -rni "<keywords>" "$MEMORY_DIR/"
```

If found in auto-memory, use those entries as source material. If not, use the user''s description directly.

### Step 2: Determine skill scope

Ask (max 2 questions):
- "What problem does this solve?" (if not clear)
- "Should this include code examples?" (if applicable)

### Step 3: Generate skill name

Rules for naming:
- Lowercase, hyphens between words
- Descriptive but concise (2-4 words)
- Examples: `docker-m1-fixes`, `api-timeout-patterns`, `pnpm-workspace-setup`

**Reserved fragments — must NOT appear in the skill name:**
- `claude`
- `anthropic`

For skills about Claude Code itself, use the `cc-` prefix instead:
- ❌ `claude-code-settings` → ✅ `cc-settings`
- ❌ `claude-code-maintenance` → ✅ `cc-maintenance`
- ❌ `claude-mcp-tools` → ✅ `cc-mcp-tools`
- ❌ `claude-plugin-development` → ✅ `cc-plugin-development`

Before writing the skill directory, check the proposed name against this list.
If a reserved fragment is present, transform it (drop the fragment or replace
the `claude*`/`anthropic*` prefix with `cc-`) and confirm with the user.

### Step 4: Create the skill files

**Spawn the `skill-extractor` agent** for the actual file generation.

The agent creates:

```
<skill-name>/
├── SKILL.md            # Main skill file with frontmatter
├── README.md           # Human-readable overview
└── reference/          # (optional) Supporting documentation
    └── examples.md     # Concrete examples and edge cases
```

### Step 5: SKILL.md structure

The generated SKILL.md must follow this format:

```markdown
---
name: "skill-name"
description: "<one-line description>. Use when: <trigger conditions>."
---

# <Skill Title>

> One-line summary of what this skill solves.

## Quick Reference

| Problem | Solution |
|---------|----------|
| {{problem 1}} | {{solution 1}} |
| {{problem 2}} | {{solution 2}} |

## The Problem

{{2-3 sentences explaining what goes wrong and why it''s non-obvious.}}

## Solutions

### Option 1: {{Name}} (Recommended)

{{Step-by-step with code examples.}}

### Option 2: {{Alternative}}

{{For when Option 1 doesn''t apply.}}

## Trade-offs

| Approach | Pros | Cons |
|----------|------|------|
| Option 1 | {{pros}} | {{cons}} |
| Option 2 | {{pros}} | {{cons}} |

## Edge Cases

- {{edge case 1 and how to handle it}}
- {{edge case 2 and how to handle it}}
```

### Step 6: Quality gates

Before finalizing, verify:

- [ ] SKILL.md has valid YAML frontmatter with `name` and `description`
- [ ] `name` matches the folder name (lowercase, hyphens)
- [ ] `name` does NOT contain reserved fragments `claude` or `anthropic` (use `cc-` prefix for Claude Code skills)
- [ ] Description includes "Use wh','.claude\skills\extract\SKILL.md','3b4e84b79bec3c03b387caab5e6ffd71449d910f80148fb4fc24e1032d81f4f0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:faceless-explainer','project_skill','skill://simplicio-runtime/faceless-explainer','skill: faceless-explainer','---
name: faceless-explainer
description: "turn arbitrary text — an article, notes, a topic, a brief — into a faceless explainer video, up to ~3 min (sweet spot 30-90s), where every visual is invented (typography, abstract graphics, diagrams, data-viz) rather than captured. There is no URL, no website capture, and no real assets. Use this skill for topic explainers, concept breakdowns, how-tos, listicles, and narrative explainers. Do not use it for a product launch/promo (use /product-launch-video), a tour of a real website (use /website-to-video), a GitHub PR (use /pr-to-video), captions on existing footage (use /embedded-captions), or a short unnarrated motion graphic (use /motion-graphics). If the intent is unclear, route through /hyperframes first."
---

# Faceless Explainer to HyperFrames

Use this skill to turn a body of text into an explainer video: pick a design system, plan a teaching story, and build it frame by frame in HyperFrames. **Faceless** means every visual is invented downstream — there is no capture step and no real asset inventory.

> **Confirm the route before Step 0.** You are the orchestrator. Run each step, verify its gate, and only then continue. This skill is for **explaining a topic from text, with no product and no website to capture**. Route other intents elsewhere: a product launch/promo → `/product-launch-video`; a tour of a real site → `/website-to-video`; a GitHub PR → `/pr-to-video`; captions on existing footage → `/embedded-captions`; a short unnarrated motion graphic → `/motion-graphics`. If the user says only "make a video" or the route is uncertain, read `/hyperframes` first.

You are the orchestrator. Work in `videos/<project>/`. Run steps in order and pass each gate before continuing. User-gated steps are Step 0, Step 3, and Step 6. Do every step yourself except Step 5, where you dispatch one sub-agent per frame. Do not put design or motion rules here; those live in the frame-worker sub-agent, `hyperframes-creative`, and `hyperframes-animation`.

Workflow: Step 0 setup → `hyperframes.json`; Step 1 brief → `capture/extracted/`; Step 2 design system → `frame.md`; Step 3 storyboard/script → `STORYBOARD.md` and `SCRIPT.md`; Step 3.1 audio → `audio_meta.json`; Step 4 visual design → enriched `STORYBOARD.md`; Step 5 frames → `compositions/frames/NN-*.html` and `index.html`; Step 6 final render → `renders/video.mp4`.

---

## Step 0: Setup and Brief

Goal: Lock the core video brief and create the HyperFrames project if needed.

Initialize only if `hyperframes.json` is missing. Name `<project>` from the topic in kebab-case, such as `compound-interest-explained`; never use workspace name or timestamp.

`npx hyperframes init "videos/<project>" --non-interactive --skip-skills --example=blank`

**Gate:** `hyperframes.json` exists, and angle, length, aspect ratio, and language are locked.

---

## Step 1: Brief (no capture)

Goal: Fold the user''s text into the project as the source of information. There is **no website capture and no real assets** — this is a faceless explainer.

Save the user''s full input verbatim, then create the synthetic capture package by hand:

- `capture/extracted/visible-text.txt` — the full article / notes / topic / brief, verbatim. This is the source of **information**, not a story template (Step 3 reshapes it).
- `capture/extracted/tokens.json` — `{ "title": "", "description": "", "colors": [], "fonts": [] }`. Fill `title`/`description` from the brief. Leave `colors`/`fonts` empty unless the user explicitly gave brand colors or fonts — then add them (the design preset supplies a complete palette regardless).

Do **not** run `npx hyperframes capture` (there is no URL). Do not create `asset-descriptions.md` or populate `capture/assets/` — faceless visuals are invented in Steps 4-5, not captured. The one exception: if the user supplied a real image, place it under `public/<basename>` and note it for Step 3.

**Gate:** `capture/extracted/visible-text.txt` and `capture/extracted/tokens.json` exist; you can state the explainer''s topic and audience in one clear sentence.

','.claude\skills\faceless-explainer\SKILL.md','d9031c71c1b30a4e4d18e8d449b2ab8a9110233a0d872ac7203789552e449e2e','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:fda-consultant-specialist','project_skill','skill://simplicio-runtime/fda-consultant-specialist','skill: fda-consultant-specialist','---
name: fda-consultant-specialist
description: FDA regulatory consultant for medical device companies. Provides 510(k)/PMA/De Novo pathway guidance, QMSR (21 CFR 820, which incorporates ISO 13485:2016 by reference since 2026-02-02; formerly QSR) compliance, HIPAA assessments, and device cybersecurity. Use when user mentions FDA submission, 510(k), PMA, De Novo, QMSR, QSR, ISO 13485 for FDA, premarket, predicate device, substantial equivalence, HIPAA medical device, or FDA cybersecurity.
---

# FDA Consultant Specialist

FDA regulatory consulting for medical device manufacturers covering submission pathways, the Quality Management System Regulation (QMSR, 21 CFR Part 820 — formerly the QSR), HIPAA compliance, and device cybersecurity requirements.

## Table of Contents

- [FDA Pathway Selection](#fda-pathway-selection)
- [510(k) Submission Process](#510k-submission-process)
- [QMSR Compliance (formerly QSR)](#qmsr-compliance-formerly-qsr)
- [HIPAA for Medical Devices](#hipaa-for-medical-devices)
- [Device Cybersecurity](#device-cybersecurity)
- [Resources](#resources)

---

## FDA Pathway Selection

Determine the appropriate FDA regulatory pathway based on device classification and predicate availability.

### Decision Framework

```
Predicate device exists?
├── YES → Substantially equivalent?
│   ├── YES → 510(k) Pathway
│   │   ├── No design changes → Abbreviated 510(k)
│   │   ├── Manufacturing only → Special 510(k)
│   │   └── Design/performance → Traditional 510(k)
│   └── NO → PMA or De Novo
└── NO → Novel device?
    ├── Low-to-moderate risk → De Novo
    └── High risk (Class III) → PMA
```

### Pathway Comparison

| Pathway | When to Use | Timeline | User Fee (FY2024) |
|---------|-------------|----------|-------------------|
| 510(k) Traditional | Predicate exists, design changes | 90 days | $21,760 (FY2024) |
| 510(k) Special | Manufacturing changes only | 30 days | $21,760 (FY2024) |
| 510(k) Abbreviated | Guidance/standard conformance | 30 days | $21,760 (FY2024) |
| De Novo | Novel, low-moderate risk | 150 days | $134,676 (FY2024) |
| PMA | Class III, no predicate | 180+ days | $425,000+ (FY2024) |

> User fees are set annually under MDUFA. Verify current-fiscal-year fees at fda.gov (MDUFA user fee schedule) before budgeting; small-business rates differ.

### Pre-Submission Strategy

1. Identify product code and classification
2. Search 510(k) database for predicates
3. Assess substantial equivalence feasibility
4. Prepare Q-Sub questions for FDA
5. Schedule Pre-Sub meeting if needed

**Reference:** See [fda_submission_guide.md](references/fda_submission_guide.md) for pathway decision matrices and submission requirements.

---

## 510(k) Submission Process

### Workflow

```
Phase 1: Planning
├── Step 1: Identify predicate device(s)
├── Step 2: Compare intended use and technology
├── Step 3: Determine testing requirements
└── Checkpoint: SE argument feasible?

Phase 2: Preparation
├── Step 4: Complete performance testing
├── Step 5: Prepare device description
├── Step 6: Document SE comparison
├── Step 7: Finalize labeling
└── Checkpoint: All required sections complete?

Phase 3: Submission
├── Step 8: Assemble submission package
├── Step 9: Submit via eSTAR
├── Step 10: Track acknowledgment
└── Checkpoint: Submission accepted?

Phase 4: Review
├── Step 11: Monitor review status
├── Step 12: Respond to AI requests
├── Step 13: Receive decision
└── Verification: SE letter received?
```

### Required Sections (21 CFR 807.87)

| Section | Content |
|---------|---------|
| Cover Letter | Submission type, device ID, contact info |
| Form 3514 | CDRH premarket review cover sheet |
| Device Description | Physical description, principles of operation |
| Indications for Use | Form 3881, patient population, use environment |
| SE Comparison | Side-by-side comparison with predicate |
| Performance Testing | Bench, biocompatibility, electrical safety |
| Software Documentation | Level of concern, hazard analysis (IEC 62304) |
| Labeling | IFU, package labels, warnings |
| 510(k) Summary | Public summary of submission ','.claude\skills\fda-consultant-specialist\SKILL.md','894a168d5d9cb8f83df95165c2e8fe588336ce13961fefebe75276e414670ed0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:fda-qsr-audit-prep','project_skill','skill://simplicio-runtime/fda-qsr-audit-prep','skill: fda-qsr-audit-prep','---
name: fda-qsr-audit-prep
description: "/cs:fda-qsr-audit-prep <scope> — FDA 21 CFR 820 (QSR / QMSR) audit 6-question forcing interrogation. Post-Feb 2026 substantially harmonized with ISO 13485. Use before annual internal QSR audit, pre-FDA-inspection readiness, or Form 483 response."
---

# /cs:fda-qsr-audit-prep — FDA QSR Forcing Questions

**Command:** `/cs:fda-qsr-audit-prep <scope>`

The FDA QSR auditor pressure-tests any US medical-device QSR work. Six questions before any internal audit, FDA inspection, Form 483 response, or recall decision.

## When to Run

- Before annual internal QSR audit
- Before pre-FDA-inspection readiness review (any device commercially distributed in US)
- After receiving Form 483 observations
- After Warning Letter receipt
- After MDR-reportable event
- Before recall decision (voluntary vs FDA-initiated)
- Before submitting 510(k) / PMA (where QSR posture affects approval timeline)

## The Six QSR Questions

### 1. Show me the complaint files from the last quarter — and the corresponding MDR reports.
**21 CFR 820.198 + 21 CFR 803 — most-cited FDA inspection area.**
- Complaint log complete: who / what / when / device / batch
- Investigation closure within reasonable timeline
- MDR-reporting decision tree applied: death OR serious injury OR malfunction-that-could-cause = MDR
- 30-day timeline for most MDR reports; 5 days for certain serious events
- Complaint trending input to management review

### 2. When was process validation (IQ/OQ/PQ) last revalidated per 21 CFR 820.75?
**Cross-walks ISO 13485 Clause 7.5.6 (substantially harmonized post-Feb 2026).**
- Initial validation at process introduction
- Revalidation triggers: process / equipment / material change OR periodic schedule
- Statistical techniques per 21 CFR 820.250 where applicable
- Cross-check with cs-cqm-iso13485 for ISO 13485 alignment

### 3. Show me the DHRs for products commercially distributed in last 2 years.
**21 CFR 820.180 — 2-year retention from commercial distribution; check sampling for completeness.**
- Device History Record (DHR) for each unit/lot/batch
- Must include: dates of manufacture, quantity manufactured, quantity released, acceptance records, primary identification label, device identification, control number
- Sample stratified by product class
- Verify DHR closeness to DHF (design history file)

### 4. Show me CAPAs from the last 6 months with effectiveness verification.
**21 CFR 820.100 = ISO 13485 8.5.2 substantially harmonized.**
- Root cause analysis depth (5 Why minimum)
- Effectiveness verification = measurable evidence, not "we updated the procedure"
- Containment / correction / corrective action distinction documented
- Closure approval by appropriate authority
- Aging CAPAs > 90 days flagged

### 5. Show me labeling (21 CFR 801) review for the most recent product launch.
**FDA-specific overlay not in ISO 13485.**
- Labeling per 21 CFR 801 requirements
- For specific device types: also 21 CFR 800 series sectoral overlays
- UDI (Unique Device Identification) per 21 CFR 830
- Promotional materials reviewed for accuracy + non-misleading

### 6. If a Form 483 was issued in the last 3 years, show me the closure status.
**Form 483 = FDA observation; not equivalent to ISO nonconformity.**
- Response within 15 working days
- Each observation has documented corrective + preventive action with timeline
- Effectiveness verification evidence
- For Warning Letters: separate response track + potentially FDA meeting

## Workflow

```bash
# 1. QSR compliance posture
python ra-qm-team/skills/fda-consultant-specialist/scripts/qsr_compliance_checker.py compliance_state.json

# 2. FDA submission tracking (510(k) / PMA / IDE)
python ra-qm-team/skills/fda-consultant-specialist/scripts/fda_submission_tracker.py submissions.json

# 3. HIPAA overlap (if connected device handles PHI)
python ra-qm-team/skills/fda-consultant-specialist/scripts/hipaa_risk_assessment.py phi_inventory.json

# 4. Mock FDA inspection
python ../../skills/compliance-os/scripts/audit_simulator.py fda_qsr_scope.json
```

## Output Format

```','.claude\skills\fda-qsr-audit-prep\SKILL.md','8cf7403bbc95d46bf81cc8dd602e12bb4e6e135a109ffaab0132f1d10db0a4c4','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:feature-flags-architect','project_skill','skill://simplicio-runtime/feature-flags-architect','skill: feature-flags-architect','---
name: feature-flags-architect
description: Use when adding, retiring, or auditing feature flags. Triggers on "add a flag", "ship behind a flag", "rollout plan", "kill switch", "stale flags", "flag debt", "LaunchDarkly", "GrowthBook", "Statsig", "Unleash", "Flipt", or any progressive-delivery question. Ships flag debt scanner, rollout planner, and kill-switch auditor (all stdlib Python), 4 references on flag taxonomy + provider trade-offs + rollout strategies + lifecycle, plus a /flag-cleanup slash command.
context: fork
version: 2.9.0
author: claude-code-skills
license: MIT
tags: [feature-flags, progressive-delivery, rollout, kill-switch, launchdarkly, growthbook, statsig, unleash, flipt, release-engineering]
compatible_tools: [claude-code, codex-cli, cursor, antigravity, opencode, gemini-cli]
---

# Feature Flags Architect

End-to-end discipline for feature flags: classify them, ship them, ramp them, and retire them. Most teams treat flags as throwaway `if`-statements; this skill treats them as a controlled lifecycle with measurable debt.

## When to use

- Adding a new flag and need a rollout plan
- Auditing a codebase for stale or orphaned flags
- Choosing a flag provider (LaunchDarkly vs GrowthBook vs Statsig vs Unleash vs Flipt vs build-your-own)
- Designing a kill-switch path for a risky launch
- Cleaning up flag debt before a release freeze
- Reviewing whether a feature should ship behind a flag at all

## Core principle: flags are a lifecycle, not an `if`

```
request → design → ship → ramp → cleanup → archive
```

Flags that skip cleanup become debt: dead branches, stale defaults, untested code paths, unbounded blast radius. The three scripts in this skill enforce the lifecycle.

## Quick start

```bash
# 1. Audit the repo for flag debt
python scripts/flag_debt_scanner.py --repo . --max-age-days 90

# 2. Plan a progressive rollout for a new flag
python scripts/rollout_planner.py --population 100000 --target-percent 100 --duration-days 14 --strategy ring

# 3. Verify every flag has a documented kill switch
python scripts/kill_switch_audit.py --repo . --flag-doc docs/feature-flags.md
```

## The 4 flag types (taxonomy)

Different flag types have different lifespans and ownership. Misclassifying creates debt.

| Type | Purpose | Typical lifespan | Owner | Cleanup trigger |
|---|---|---|---|---|
| **Release** | Hide unfinished features in production | days–weeks | Eng | 100% rollout reached |
| **Experiment** | A/B test variants | weeks | Product/Marketing | Test concluded; winner picked |
| **Operational** | Circuit breakers, perf toggles, kill switches | months–years | Eng/SRE | Replaced by autoscaling/feature retirement |
| **Permission** | Entitlements per user/account/plan | years (permanent) | Product | Plan/role removed |

Only Release and Experiment flags should be on a debt-scanner watchlist. Operational and Permission flags are by design long-lived. See `references/flag_taxonomy.md` for decision tree.

## The 3 Python tools

All three are stdlib-only. Run with `--help`.

### `flag_debt_scanner.py`

Finds flags older than `--max-age-days` with low usage, suggesting candidates for cleanup.

```bash
python scripts/flag_debt_scanner.py --repo . --max-age-days 90 --format text
python scripts/flag_debt_scanner.py --repo . --max-age-days 60 --format json > debt.json
```

**Detection heuristic:**
1. Walk `--repo` for code references matching common flag-call patterns:
   - `flag("...")`, `isFlagEnabled("...")`, `featureFlag("...")`, `getFlag("...")`
   - `client.variation("...", ...)`, `unleash.isEnabled("...")`, `growthbook.feature("...")`
2. For each unique flag identifier, find the oldest commit that introduced it (`git log --diff-filter=A -S <name>`).
3. Flag as DEBT if introduced > `--max-age-days` ago AND used in ≤`--min-uses` places.

Outputs flag name, age in days, file references, suggested action. JSON mode is CI-friendly.

### `rollout_planner.py`

Generates a phased rollout schedule from population size, target percent, duration, and strategy.

```bash
python scripts/rollout_planner.py --population','.claude\skills\feature-flags-architect\SKILL.md','865be7952f13ffaca78cfc1056f0841f6ce647f36a2ee9098433feca4fcffb4e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:finance-skills','project_skill','skill://simplicio-runtime/finance-skills','skill: finance-skills','---
name: finance-skills
description: "Router/index for the 2 finance skills bundled in this plugin: financial-analyst (ratio analysis, DCF valuation, budget variance, rolling forecasts) and saas-metrics-coach (ARR/MRR, churn, CAC/LTV, NRR, quick ratio). Use when a finance request doesn''t obviously match one skill and you need to pick the right one (e.g., ''analyze these financials'', ''how healthy are my SaaS metrics'')."
version: 2.9.0
author: Alireza Rezvani
license: MIT
tags:
  - finance
  - financial-analysis
  - dcf
  - valuation
  - budgeting
agents:
  - claude-code
  - codex-cli
  - openclaw
---

# Finance Skills — Router

This plugin bundles **2 finance skills** (this router is the 3rd folder under `finance/skills/`). Each skill is self-contained.

## Routing table

| Request signals | Skill | Path |
|---|---|---|
| Ratio analysis, DCF valuation, budget variance, driver-based forecasts | financial-analyst | `skills/financial-analyst/` |
| ARR/MRR, churn, CAC/LTV, NRR, quick ratio, SaaS benchmarks | saas-metrics-coach | `skills/saas-metrics-coach/` |

If both match (e.g., "value my SaaS company"), ask whether the user wants statement-level analysis (financial-analyst) or SaaS operating metrics (saas-metrics-coach).

## Quick start

```bash
# Example: route a statement-analysis request
cat finance/skills/financial-analyst/SKILL.md
python3 finance/skills/financial-analyst/scripts/ratio_calculator.py --help

# Or a SaaS metrics request
python3 finance/skills/saas-metrics-coach/scripts/metrics_calculator.py --help
```

## Related (packaged separately, not in this bundle)

- `finance/business-investment-advisor/` — investment thesis evaluation, ROI modeling (prompt-only skill, separate nested plugin)
- Root commands `/financial-health` and `/saas-health` wrap these skills'' scripts.

## Rules

- Route to exactly one skill, then follow that skill''s workflow. This router ships no tools of its own.
- Always validate financial outputs against the user''s source data; outputs are analysis support, not investment advice.

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: finance. -->
','.claude\skills\finance-skills\SKILL.md','fac7671dcda4e6fc7e4d78dbdfc7cee7b71f98924f5ae55802a7d63ea3744b8b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:financial-analyst','project_skill','skill://simplicio-runtime/financial-analyst','skill: financial-analyst','---
name: financial-analyst
description: Performs financial ratio analysis, DCF valuation, budget variance analysis, and rolling forecast construction for strategic decision-making. Use when analyzing financial statements, building valuation models, assessing budget variances, or constructing financial projections and forecasts. Also applicable when users mention financial modeling, cash flow analysis, company valuation, financial projections, or spreadsheet analysis.
---

# Financial Analyst Skill

## Overview

Production-ready financial analysis toolkit providing ratio analysis, DCF valuation, budget variance analysis, and rolling forecast construction. Designed for financial modeling, forecasting & budgeting, management reporting, business performance analysis, and investment analysis.

## 5-Phase Workflow

### Phase 1: Scoping
- Define analysis objectives and stakeholder requirements
- Identify data sources and time periods
- Establish materiality thresholds and accuracy targets
- Select appropriate analytical frameworks

### Phase 2: Data Analysis & Modeling
- Collect and validate financial data (income statement, balance sheet, cash flow)
- **Validate input data completeness** before running ratio calculations (check for missing fields, nulls, or implausible values)
- Calculate financial ratios across 5 categories (profitability, liquidity, leverage, efficiency, valuation)
- Build DCF models with WACC and terminal value calculations; **cross-check DCF outputs against sanity bounds** (e.g., implied multiples vs. comparables)
- Construct budget variance analyses with favorable/unfavorable classification
- Develop driver-based forecasts with scenario modeling

### Phase 3: Insight Generation
- Interpret ratio trends and benchmark against industry standards
- Identify material variances and root causes
- Assess valuation ranges through sensitivity analysis
- Evaluate forecast scenarios (base/bull/bear) for decision support

### Phase 4: Reporting
- Generate executive summaries with key findings
- Produce detailed variance reports by department and category
- Deliver DCF valuation reports with sensitivity tables
- Present rolling forecasts with trend analysis

### Phase 5: Follow-up
- Track forecast accuracy (target: +/-5% revenue, +/-3% expenses)
- Monitor report delivery timeliness (target: 100% on time)
- Update models with actuals as they become available
- Refine assumptions based on variance analysis

## Tools

### 1. Ratio Calculator (`scripts/ratio_calculator.py`)

Calculate and interpret financial ratios from financial statement data.

**Ratio Categories:**
- **Profitability:** ROE, ROA, Gross Margin, Operating Margin, Net Margin
- **Liquidity:** Current Ratio, Quick Ratio, Cash Ratio
- **Leverage:** Debt-to-Equity, Interest Coverage, DSCR
- **Efficiency:** Asset Turnover, Inventory Turnover, Receivables Turnover, DSO
- **Valuation:** P/E, P/B, P/S, EV/EBITDA, PEG Ratio

```bash
python scripts/ratio_calculator.py assets/sample_financial_data.json
python scripts/ratio_calculator.py assets/sample_financial_data.json --format json
python scripts/ratio_calculator.py assets/sample_financial_data.json --category profitability
```

### 2. DCF Valuation (`scripts/dcf_valuation.py`)

Discounted Cash Flow enterprise and equity valuation with sensitivity analysis.

**Features:**
- WACC calculation via CAPM
- Revenue and free cash flow projections (5-year default)
- Terminal value via perpetuity growth and exit multiple methods
- Enterprise value and equity value derivation
- Two-way sensitivity analysis (discount rate vs growth rate)

```bash
python scripts/dcf_valuation.py assets/sample_financial_data.json
python scripts/dcf_valuation.py assets/sample_financial_data.json --format json
python scripts/dcf_valuation.py assets/sample_financial_data.json --projection-years 7
```

### 3. Budget Variance Analyzer (`scripts/budget_variance_analyzer.py`)

Analyze actual vs budget vs prior year performance with materiality filtering.

**Features:**
- Dollar and percentage variance calculation
- Materiality threshold filtering (def','.claude\skills\financial-analyst\SKILL.md','1582634d8169872c53f4f90002e5d445e835947dcbe6a10b1c67d653db3d63e1','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:firebase-apk-scanner','project_skill','skill://simplicio-runtime/firebase-apk-scanner','skill: firebase-apk-scanner','---
name: firebase-apk-scanner
description: Scans Android APKs for Firebase security misconfigurations including open databases, storage buckets, authentication issues, and exposed cloud functions. Use when analyzing APK files for Firebase vulnerabilities, performing mobile app security audits, or testing Firebase endpoint security. For authorized security research only.
argument-hint: [apk-file-or-directory]
allowed-tools: Bash({baseDir}/scanner.sh:*) Bash(apktool:*) Bash(curl:*) Read Grep Glob
disable-model-invocation: true
---

# Firebase APK Security Scanner

You are a Firebase security analyst. When this skill is invoked, scan the provided APK(s) for Firebase misconfigurations and report findings.

## When to Use

- Auditing Android applications for Firebase security misconfigurations
- Testing Firebase endpoints extracted from APKs (Realtime Database, Firestore, Storage)
- Checking authentication security (open signup, anonymous auth, email enumeration)
- Enumerating Cloud Functions and testing for unauthenticated access
- Mobile app security assessments involving Firebase backends
- Authorized penetration testing of Firebase-backed applications

## When NOT to Use

- Scanning apps you do not have explicit authorization to test
- Testing production Firebase projects without written permission
- When you only need to extract Firebase config without testing (use manual grep/strings instead)
- For non-Android targets (iOS, web apps) - this skill is APK-specific
- When the target app does not use Firebase

## Rationalizations to Reject

When auditing, reject these common rationalizations that lead to missed or downplayed findings:

- **"The database is read-only so it''s fine"** - Data exposure is still a critical finding; PII, API keys, and business data may be leaked
- **"It''s just anonymous auth, not real accounts"** - Anonymous tokens bypass `auth != null` rules and can access "authenticated-only" resources
- **"The API key is public anyway"** - A public API key does not justify open database rules or disabled auth restrictions
- **"There''s no sensitive data in there"** - You cannot know what data will be stored in the future; insecure rules are vulnerabilities regardless of current content
- **"It''s an internal app"** - APKs can be extracted from any device; "internal" apps are not protected from reverse engineering
- **"We''ll fix it before launch"** - Document the finding; pre-launch vulnerabilities frequently ship to production

## Reference Documentation

For detailed vulnerability patterns and exploitation techniques, consult:
- [Vulnerability Patterns Reference](references/vulnerabilities.md)

## How to Use This Skill

The user will provide an APK file or directory: `$ARGUMENTS`

## Workflow

### Step 1: Validate Input

First, verify the target exists:

```bash
ls -la $ARGUMENTS
```

If `$ARGUMENTS` is empty, ask the user to provide an APK path.

### Step 2: Run the Scanner

Execute the bundled scanner script on the target:

```bash
{baseDir}/scanner.sh $ARGUMENTS
```

The scanner will:
1. Decompile the APK using apktool
2. Extract Firebase configuration from all sources (google-services.json, XML resources, assets, smali code, DEX strings)
3. Test authentication endpoints (open signup, anonymous auth, email enumeration)
4. Test Realtime Database (unauthenticated read/write, auth bypass)
5. Test Firestore (document access, collection enumeration)
6. Test Storage buckets (listing, write access)
7. Test Cloud Functions (enumeration, unauthenticated access)
8. Test Remote Config exposure
9. Generate reports in text and JSON format

### Step 3: Present Results

After the scanner completes, read and summarize the results:

```bash
cat firebase_scan_*/scan_report.txt
```

Present findings in this format:

---

## Scan Summary

| Metric | Value |
|--------|-------|
| APKs Scanned | X |
| Vulnerable | X |
| Total Issues | X |

## Extracted Configuration

| Field | Value |
|-------|-------|
| Project ID | `extracted_value` |
| Database URL | `extracted_value` |
| Storage Bucket | `extracted_value` |
| API Key | `extrac','.claude\skills\firebase-apk-scanner\SKILL.md','6621357ff5397f38cc6194f9f83c8dd968af2e093729b67a2c97b0744cf7b05d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:fix','project_skill','skill://simplicio-runtime/fix','skill: fix','---
name: fix
description: >-
  Fix failing or flaky Playwright tests. Use when user says "fix test",
  "flaky test", "test failing", "debug test", "test broken", "test passes
  sometimes", or "intermittent failure".
---

# Fix Failing or Flaky Tests

Diagnose and fix a Playwright test that fails or passes intermittently using a systematic taxonomy.

## Input

`$ARGUMENTS` contains:
- A test file path: `e2e/login.spec.ts`
- A test name: ""should redirect after login"`
- A description: `"the checkout test fails in CI but passes locally"`

## Steps

### 1. Reproduce the Failure

Run the test to capture the error:

```bash
npx playwright test <file> --reporter=list
```

If the test passes, it''s likely flaky. Run burn-in:

```bash
npx playwright test <file> --repeat-each=10 --reporter=list
```

If it still passes, try with parallel workers:

```bash
npx playwright test --fully-parallel --workers=4 --repeat-each=5
```

### 2. Capture Trace

Run with full tracing:

```bash
npx playwright test <file> --trace=on --retries=0
```

Read the trace output. Use `/debug` to analyze trace files if available.

### 3. Categorize the Failure

Load `flaky-taxonomy.md` from this skill directory.

Every failing test falls into one of four categories:

| Category | Symptom | Diagnosis |
|---|---|---|
| **Timing/Async** | Fails intermittently everywhere | `--repeat-each=20` reproduces locally |
| **Test Isolation** | Fails in suite, passes alone | `--workers=1 --grep "test name"` passes |
| **Environment** | Fails in CI, passes locally | Compare CI vs local screenshots/traces |
| **Infrastructure** | Random, no pattern | Error references browser internals |

### 4. Apply Targeted Fix

**Timing/Async:**
- Replace `waitForTimeout()` with web-first assertions
- Add `await` to missing Playwright calls
- Wait for specific network responses before asserting
- Use `toBeVisible()` before interacting with elements

**Test Isolation:**
- Remove shared mutable state between tests
- Create test data per-test via API or fixtures
- Use unique identifiers (timestamps, random strings) for test data
- Check for database state leaks

**Environment:**
- Match viewport sizes between local and CI
- Account for font rendering differences in screenshots
- Use `docker` locally to match CI environment
- Check for timezone-dependent assertions

**Infrastructure:**
- Increase timeout for slow CI runners
- Add retries in CI config (`retries: 2`)
- Check for browser OOM (reduce parallel workers)
- Ensure browser dependencies are installed

### 5. Verify the Fix

Run the test 10 times to confirm stability:

```bash
npx playwright test <file> --repeat-each=10 --reporter=list
```

All 10 must pass. If any fail, go back to step 3.

### 6. Prevent Recurrence

Suggest:
- Add to CI with `retries: 2` if not already
- Enable `trace: ''on-first-retry''` in config
- Add the fix pattern to project''s test conventions doc

## Output

- Root cause category and specific issue
- The fix applied (with diff)
- Verification result (10/10 passes)
- Prevention recommendation

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering-team. -->
','.claude\skills\fix\SKILL.md','ed4c223c1810c6b43be863219d9a2b542dd0533f545180312dc9e534ee08d990','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:focused-fix','project_skill','skill://simplicio-runtime/focused-fix','skill: focused-fix','---
name: focused-fix
description: "Use when the user asks to fix, debug, or make a specific feature/module/area work end-to-end. Triggers: ''make X work'', ''fix the Y feature'', ''the Z module is broken'', ''focus on [area]''. Not for quick single-bug fixes — this is for systematic deep-dive repair across all files and dependencies."
---

# Focused Fix — Deep-Dive Feature Repair

## When to Use

Activate when the user asks to fix, debug, or make a specific feature/module/area work. Key triggers:
- "make X work"
- "fix the Y feature"
- "the Z module is broken"
- "focus on [area]"
- "this feature needs to work properly"

This is NOT for quick single-bug fixes (use systematic-debugging for that). This is for when an entire feature or module needs systematic repair — tracing every dependency, reading logs, checking tests, mapping the full dependency graph.

```dot
digraph when_to_use {
    "User reports feature broken" [shape=diamond];
    "Single bug or symptom?" [shape=diamond];
    "Use systematic-debugging" [shape=box];
    "Entire feature/module needs repair?" [shape=diamond];
    "Use focused-fix" [shape=box];
    "Something else" [shape=box];

    "User reports feature broken" -> "Single bug or symptom?";
    "Single bug or symptom?" -> "Use systematic-debugging" [label="yes"];
    "Single bug or symptom?" -> "Entire feature/module needs repair?" [label="no"];
    "Entire feature/module needs repair?" -> "Use focused-fix" [label="yes"];
    "Entire feature/module needs repair?" -> "Something else" [label="no"];
}
```

## The Iron Law

```
NO FIXES WITHOUT COMPLETING SCOPE → TRACE → DIAGNOSE FIRST
```

If you haven''t finished Phase 3, you cannot propose fixes. Period.

**Violating the letter of these phases is violating the spirit of focused repair.**

## Protocol — STRICTLY follow these 5 phases IN ORDER

```dot
digraph phases {
    rankdir=LR;
    SCOPE [shape=box, label="Phase 1\nSCOPE"];
    TRACE [shape=box, label="Phase 2\nTRACE"];
    DIAGNOSE [shape=box, label="Phase 3\nDIAGNOSE"];
    FIX [shape=box, label="Phase 4\nFIX"];
    VERIFY [shape=box, label="Phase 5\nVERIFY"];

    SCOPE -> TRACE -> DIAGNOSE -> FIX -> VERIFY;
    FIX -> DIAGNOSE [label="fix broke\nsomething else"];
    FIX -> ESCALATE [label="3+ fixes\ncreate new issues"];
    ESCALATE [shape=doubleoctagon, label="STOP\nQuestion Architecture\nDiscuss with User"];
}
```

### Phase 1: SCOPE — Map the Feature Boundary

Before touching any code, understand the full scope of the feature.

1. Ask the user: "Which feature/folder should I focus on?" if not already clear
2. Identify the PRIMARY folder/files for this feature
3. Map EVERY file in that folder — read each one, understand its purpose
4. Create a feature manifest:

```
FEATURE SCOPE:
  Primary path: src/features/auth/
  Entry points: [files that are imported by other parts of the app]
  Internal files: [files only used within this feature]
  Total files: N
  Total lines: N
```

### Phase 2: TRACE — Map All Dependencies (Inside AND Outside)

Trace every connection this feature has to the rest of the codebase.

**INBOUND (what this feature imports):**
1. For every import statement in every file in the feature folder:
   - Trace it to its source
   - Verify the source file exists
   - Verify the imported entity (function, type, component) exists and is exported
   - Check if the types/signatures match what the feature expects
2. Check for:
   - Environment variables used (grep for process.env, import.meta.env, os.environ, etc.)
   - Config files referenced
   - Database models/schemas used
   - API endpoints called
   - Third-party packages imported

**OUTBOUND (what imports this feature):**
1. Search the entire codebase for imports from this feature folder
2. For each consumer:
   - Verify they''re importing entities that actually exist
   - Check if they''re using the correct API/interface
   - Note if any consumers are using deprecated patterns

Output format:
```
DEPENDENCY MAP:
  Inbound (this feature depends on):
    src/lib/db.ts → used in auth/repository.ts (getUserById, createUser)
    src/lib/jwt.t','.claude\skills\focused-fix\SKILL.md','b9410d5747b64f40e6f0b8f868c700bd20e59f8cfb39cc8f33496851b157f8e0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:fp-check','project_skill','skill://simplicio-runtime/fp-check','skill: fp-check','---
name: fp-check
description: "Systematically verifies suspected security bugs to eliminate false positives, producing a TRUE POSITIVE or FALSE POSITIVE verdict with documented evidence for each. Use when asked whether a specific finding is real, exploitable, or a false positive, or to verify or validate a suspected vulnerability — not for hunting or discovering new bugs."
allowed-tools: Read Grep Glob LSP Bash Task Write Edit AskUserQuestion TaskCreate TaskUpdate TaskList TaskGet
---

# False Positive Check

## When to Use

- "Is this bug real?" or "is this a true positive?"
- "Is this a false positive?" or "verify this finding"
- "Check if this vulnerability is exploitable"
- Any request to verify or validate a specific suspected bug

## When NOT to Use

- Finding or hunting for bugs ("find bugs", "security analysis", "audit code")
- General code review for style, performance, or maintainability
- Feature development, refactoring, or non-security tasks
- When the user explicitly asks for a quick scan without verification

## Rationalizations to Reject

If you catch yourself thinking any of these, STOP.

| Rationalization | Why It''s Wrong | Required Action |
|---|---|---|
| "Rapid analysis of remaining bugs" | Every bug gets full verification | Return to task list, verify next bug through all phases |
| "This pattern looks dangerous, so it''s a vulnerability" | Pattern recognition is not analysis | Complete data flow tracing before any conclusion |
| "Skipping full verification for efficiency" | No partial analysis allowed | Execute all steps per the chosen verification path |
| "The code looks unsafe, reporting without tracing data flow" | Unsafe-looking code may have upstream validation | Trace the complete path from source to sink |
| "Similar code was vulnerable elsewhere" | Each context has different validation, callers, and protections | Verify this specific instance independently |
| "This is clearly critical" | LLMs are biased toward seeing bugs and overrating severity | Complete devil''s advocate review; prove it with evidence |

---

## Step 0: Understand the Claim and Context

Before any analysis, restate the bug in your own words. If you cannot do this clearly, ask the user for clarification. Half of false positives collapse at this step — the claim doesn''t make coherent sense when restated precisely.

Document:

- **What is the exact vulnerability claim?** (e.g., "heap buffer overflow in `parse_header()` when `content_length` exceeds 4096")
- **What is the alleged root cause?** (e.g., "missing bounds check before `memcpy` at line 142")
- **What is the supposed trigger?** (e.g., "attacker sends HTTP request with oversized Content-Length header")
- **What is the claimed impact?** (e.g., "remote code execution via controlled heap corruption")
- **What is the threat model?** What privilege level does this code run at? Is it sandboxed? What can the attacker already do before triggering this bug? (e.g., "unauthenticated remote attacker vs privileged local user"; "runs inside Chrome renderer sandbox" vs "runs as root with no sandbox")
- **What is the bug class?** Classify the bug and consult [bug-class-verification.md]({baseDir}/references/bug-class-verification.md) for class-specific verification requirements that supplement the generic phases below.
- **Execution context**: When and how is this code path reached during normal execution?
- **Caller analysis**: What functions call this code and what input constraints do they impose?
- **Architectural context**: Is this part of a larger security system with multiple protection layers?
- **Historical context**: Any recent changes, known issues, or previous security reviews of this code area?

## Route: Standard vs Deep Verification

After Step 0, choose a verification path.

### Standard Verification

Use when ALL of these hold:

- Clear, specific vulnerability claim (not vague or ambiguous)
- Single component — no cross-component interaction in the bug path
- Well-understood bug class (buffer overflow, SQL injection, XSS, integer overflow, etc.)
- No concurrency or','.claude\skills\fp-check\SKILL.md','972483ec793bdddc9975a9846bc33169b7e66916159ac4499d9a7f92e2e7998e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:free-tools','project_skill','skill://simplicio-runtime/free-tools','skill: free-tools','---
name: free-tools
description: When the user wants to plan, evaluate, or build a free tool for marketing purposes — lead generation, SEO value, or brand awareness. Also use when the user mentions "engineering as marketing," "free tool," "marketing tool," "calculator," "generator," "interactive tool," "lead gen tool," "build a tool for leads," "free resource," "ROI calculator," "grader tool," "audit tool," "should I build a free tool," or "tools for lead gen." Use this whenever someone wants to build something useful and give it away to attract leads or earn links. For downloadable content lead magnets (ebooks, checklists, templates), see lead-magnets.
metadata:
  version: 2.0.0
---

# Free Tool Strategy (Engineering as Marketing)

You are an expert in engineering-as-marketing strategy. Your goal is to help plan and evaluate free tools that generate leads, attract organic traffic, and build brand awareness.

## Initial Assessment

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Before designing a tool strategy, understand:

1. **Business Context** - What''s the core product? Who is the target audience? What problems do they have?

2. **Goals** - Lead generation? SEO/traffic? Brand awareness? Product education?

3. **Resources** - Technical capacity to build? Ongoing maintenance bandwidth? Budget for promotion?

---

## Core Principles

### 1. Solve a Real Problem
- Tool must provide genuine value
- Solves a problem your audience actually has
- Useful even without your main product

### 2. Adjacent to Core Product
- Related to what you sell
- Natural path from tool to product
- Educates on problem you solve

### 3. Simple and Focused
- Does one thing well
- Low friction to use
- Immediate value

### 4. Worth the Investment
- Lead value × expected leads > build cost + maintenance

---

## Tool Types Overview

| Type | Examples | Best For |
|------|----------|----------|
| Calculators | ROI, savings, pricing estimators | Decisions involving numbers |
| Generators | Templates, policies, names | Creating something quickly |
| Analyzers | Website graders, SEO auditors | Evaluating existing work |
| Testers | Meta tag preview, speed tests | Checking if something works |
| Libraries | Icon sets, templates, snippets | Reference material |
| Interactive | Tutorials, playgrounds, quizzes | Learning/understanding |

**For detailed tool types and examples**: See [references/tool-types.md](references/tool-types.md)

---

## Ideation Framework

### Start with Pain Points

1. **What problems does your audience Google?** - Search query research, common questions

2. **What manual processes are tedious?** - Spreadsheet tasks, repetitive calculations

3. **What do they need before buying your product?** - Assessments, planning, comparisons

4. **What information do they wish they had?** - Data they can''t easily access, benchmarks

### Validate the Idea

- **Search demand**: Is there search volume? How competitive?
- **Uniqueness**: What exists? How can you be 10x better?
- **Lead quality**: Does this audience match buyers?
- **Build feasibility**: How complex? Can you scope an MVP?

---

## Lead Capture Strategy

### Gating Options

| Approach | Pros | Cons |
|----------|------|------|
| Fully gated | Maximum capture | Lower usage |
| Partially gated | Balance of both | Common pattern |
| Ungated + optional | Maximum reach | Lower capture |
| Ungated entirely | Pure SEO/brand | No direct leads |

### Lead Capture Best Practices
- Value exchange clear: "Get your full report"
- Minimal friction: Email only
- Show preview of what they''ll get
- Optional: Segment by asking one qualifying question

---

## SEO Considerations

### Keyword Strategy
**Tool landing page**: "[thing] calculator", "[thing] generator", "free [tool type]"

**Supporting content**: "How to [use case]",','.claude\skills\free-tools\SKILL.md','6fce47ca10e1430c34b6666cc82d691ac346cd91e15ec07cc441b8a27c78420b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:frontend-design','project_skill','skill://simplicio-runtime/frontend-design','skill: frontend-design','---
name: frontend-design
description: Use when building or reviewing UI to make it look intentional, modern, and production-grade instead of default/AI-generated — spacing, typography, color, hierarchy, responsive layout, and component polish. Trigger on "make this look good", "design the frontend", "improve the UI", "deixa bonito", "melhora o layout", or any task that produces a screen, page, or component a human will look at.
source: methodology skill (sujeitoprogramador.com 2026 list — Frontend Design); Simplicio-native, no external dependency
metadata:
  simplicio:
    guardians: [Helo]
    tags: [skill, simplicio, frontend, design, ui, css, layout, coding]
---

# Frontend design — make UI look intentional, not default

A methodology for turning a working-but-ugly screen into one that reads as
designed. No framework lock-in: applies to plain HTML/CSS, Tailwind, React, etc.
Pairs with `web-design-guidelines` (rules) and `ui-ux` (flows). The frontier
model decides the design; route the *decided* edits through `simplicio edit`.

## The checklist (apply in order)

1. **Spacing system first.** Pick one scale (4/8px or a 1.25 ratio) and use it for
   every margin/padding/gap. Inconsistent spacing is the #1 tell of "AI default".
   Whitespace is a feature — let things breathe; group related elements close,
   separate unrelated ones.
2. **Type hierarchy.** One font family (max two). 3–4 sizes total, clear jumps
   (e.g. 14/16/24/40). Set `line-height` ~1.5 for body, tighter for headings.
   Limit body measure to ~60–75ch. Weight and size carry hierarchy — not color.
3. **Restrained color.** One neutral ramp (background → text) + one accent. Use the
   accent sparingly (CTAs, focus). Ensure WCAG AA contrast (4.5:1 body). Avoid pure
   black on pure white — soften to near-black/off-white.
4. **Visual hierarchy.** The eye should land on the primary action first. Size,
   weight, contrast, and position establish what matters; everything secondary is
   quieter. One primary CTA per view.
5. **Alignment & grid.** Everything aligns to a grid or a shared edge. Optical
   alignment beats mathematical when they disagree. No orphaned, randomly-placed
   elements.
6. **Depth, lightly.** Subtle shadows/borders to separate layers; consistent
   radius. Avoid heavy drop-shadows and gradients unless the brand calls for it.
7. **States & feedback.** Every interactive element needs hover/active/focus/
   disabled; async actions need loading and empty/error states. Missing states are
   what makes a UI feel unfinished.
8. **Responsive.** Design mobile-first; verify at ~360, 768, 1280. Touch targets
   ≥44px. Don''t just shrink — reflow.
9. **Motion with purpose.** Transitions 150–250ms, ease-out; animate to explain a
   change, never for decoration. Respect `prefers-reduced-motion`.

## Anti-patterns (the "AI-generated" tells)

- Same margin everywhere / random spacing · 5+ font sizes · rainbow of colors ·
  centered everything · no hover/focus states · pixel-perfect desktop that breaks
  on mobile · gradient + shadow + border + glow all at once.

## Simplicio flow

`simplicio map` to find the component → decide the design → apply via `simplicio
edit` (deterministic) → `simplicio validate`/preview → self-review against this
checklist. Recall prior design decisions with `simplicio memory "design system"`.

## When NOT to use

A pure backend/CLI task with no rendered surface. Use the deterministic fast path.
','.claude\skills\frontend-design\SKILL.md','8b57242f92ba99ea5b25e8c7b206d1849fd5c97fe6075fe19c58965430bdf10c','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:full-page-screenshot','project_skill','skill://simplicio-runtime/full-page-screenshot','skill: full-page-screenshot','---
name: full-page-screenshot
description: "Use when the user asks to capture a full-page screenshot, long screenshot, or complete page capture of a web page. Handles SPA scroll containers, lazy-loaded images, and very tall pages via Chrome DevTools Protocol with zero external dependencies."
---

# Full Page Screenshot

Capture a full-page screenshot of any web page via Chrome DevTools Protocol. Produces a single PNG that includes all content — even portions that require scrolling. Zero external dependencies beyond Node.js 22+ and Chrome with remote debugging enabled.

## Prerequisites

- **Node.js 22+** (uses built-in `WebSocket`)
- **Chrome/Chromium** with remote debugging enabled

Check environment readiness:

```bash
node "${SKILL_DIR}/scripts/full-page-screenshot.mjs" --check
```

If Chrome check fails, instruct user to open `chrome://inspect/#remote-debugging` and enable **"Allow remote debugging for this browser instance"**.

## Workflow

### Option A: Screenshot an already-open tab (recommended for authenticated pages)

1. List available tabs:

```bash
node "${SKILL_DIR}/scripts/full-page-screenshot.mjs" --list
```

2. Identify the target by title/URL, then capture:

```bash
node "${SKILL_DIR}/scripts/full-page-screenshot.mjs" <targetId> /tmp/screenshot.png --width 1200 --dpr 1
```

### Option B: Screenshot a URL (opens a background tab, captures, closes)

```bash
node "${SKILL_DIR}/scripts/full-page-screenshot.mjs" --url "https://example.com" /tmp/screenshot.png --width 1200 --dpr 1 --wait 15000
```

> **Note:** `--url` mode creates a background tab. Pages requiring authentication (SSO, login walls) should use Option A instead.

### Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `output` | Output PNG file path | `/tmp/screenshot.png` |
| `--width` | Viewport width in CSS pixels (articles: 1200, dashboards: 1440-1920) | 1200 |
| `--dpr` | Device pixel ratio (2 = Retina, but 4x file size) | 1 |
| `--wait` | Page load timeout in ms (`--url` mode only) | 15000 |
| `--css` | Custom CSS to inject before capture (e.g., hide elements) | — |

### Verify Output

```bash
# macOS
sips -g pixelWidth -g pixelHeight /tmp/screenshot.png

# Linux
file /tmp/screenshot.png
```

## Core Capabilities

1. **SPA scroll container expansion** — Detects `overflow-y: auto/scroll` containers, scrolls through them to trigger lazy-loading, then removes overflow constraints (including Tailwind `h-[calc(...)]`) so all content renders in a single pass.

2. **DOM stability detection** — After `readyState=complete`, monitors DOM element count until it stabilizes. This ensures SPA frameworks finish rendering dynamic content.

3. **Lazy-load triggering** — Scrolls the viewport incrementally to fire `IntersectionObserver` callbacks, then waits for all `<img>` elements to complete loading.

4. **Tiled capture for very tall pages** — Pages exceeding 16,000px are captured in 8,000px tiles and automatically stitched using Python PIL. Falls back to saving tiles separately if PIL is unavailable.

5. **Auto-discovery of Chrome** — Reads `DevToolsActivePort` file to find the debugging port. Falls back to probing ports 9222, 9229, 9333.

6. **CDP Proxy fallback** — When a CDP proxy holds the browser WebSocket, the script falls back to proxy API endpoints (`/eval`, `/screenshot`, `/scroll`) for capture.

## How It Works

```
1. Discover Chrome debugging port
2. Connect via WebSocket (CDP)
3. Attach to target / create background tab
4. Set viewport width via Emulation domain
5. Wait: readyState + DOM stability
6. Detect & expand scroll containers
7. Scroll through page (trigger lazy-load)
8. Wait for images to complete
9. Measure final content height
10. Page.captureScreenshot (or tiled capture)
11. Stitch tiles if needed (PIL)
12. Restore viewport, detach, clean up
```

## Anti-Patterns

| Do NOT | Do instead |
|--------|-----------|
| Use `--dpr 2` on pages > 10,000px tall | Use `--dpr 1` to avoid Chrome memory issues |
| Use `--url` for authenticated/SSO pages | Use `--list` + targetId on a tab where user is logge','.claude\skills\full-page-screenshot\SKILL.md','7a55eb845fca8ec061af2befb0e40403d14d5aa4bfe31680be2560326ab280c1','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:fuzzing-dictionary','project_skill','skill://simplicio-runtime/fuzzing-dictionary','skill: fuzzing-dictionary','---
name: fuzzing-dictionary
type: technique
description: >
  Fuzzing dictionaries guide fuzzers with domain-specific tokens.
  Use when fuzzing parsers, protocols, or format-specific code.
---

# Fuzzing Dictionary

A fuzzing dictionary provides domain-specific tokens to guide the fuzzer toward interesting inputs. Instead of purely random mutations, the fuzzer incorporates known keywords, magic numbers, protocol commands, and format-specific strings that are more likely to reach deeper code paths in parsers, protocol handlers, and file format processors.

## Overview

Dictionaries are text files containing quoted strings that represent meaningful tokens for your target. They help fuzzers bypass early validation checks and explore code paths that would be difficult to reach through blind mutation alone.

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Dictionary Entry** | A quoted string (e.g., `"keyword"`) or key-value pair (e.g., `kw="value"`) |
| **Hex Escapes** | Byte sequences like `"\xF7\xF8"` for non-printable characters |
| **Token Injection** | Fuzzer inserts dictionary entries into generated inputs |
| **Cross-Fuzzer Format** | Dictionary files work with libFuzzer, AFL++, and cargo-fuzz |

## When to Apply

**Apply this technique when:**
- Fuzzing parsers (JSON, XML, config files)
- Fuzzing protocol implementations (HTTP, DNS, custom protocols)
- Fuzzing file format handlers (PNG, PDF, media codecs)
- Coverage plateaus early without reaching deeper logic
- Target code checks for specific keywords or magic values

**Skip this technique when:**
- Fuzzing pure algorithms without format expectations
- Target has no keyword-based parsing
- Corpus already achieves high coverage

## Quick Reference

| Task | Command/Pattern |
|------|-----------------|
| Use with libFuzzer | `./fuzz -dict=./dictionary.dict ...` |
| Use with AFL++ | `afl-fuzz -x ./dictionary.dict ...` |
| Use with cargo-fuzz | `cargo fuzz run fuzz_target -- -dict=./dictionary.dict` |
| Extract from header | `grep -o ''".*"'' header.h > header.dict` |
| Generate from binary | `strings ./binary \| sed ''s/^/"&/; s/$/&"/'' > strings.dict` |

## Step-by-Step

### Step 1: Create Dictionary File

Create a text file with quoted strings on each line. Use comments (`#`) for documentation.

**Example dictionary format:**

```conf
# Lines starting with ''#'' and empty lines are ignored.

# Adds "blah" (w/o quotes) to the dictionary.
kw1="blah"
# Use \\ for backslash and \" for quotes.
kw2="\"ac\\dc\""
# Use \xAB for hex values
kw3="\xF7\xF8"
# the name of the keyword followed by ''='' may be omitted:
"foo\x0Abar"
```

### Step 2: Generate Dictionary Content

Choose a generation method based on what''s available:

**From LLM:** Prompt ChatGPT or Claude with:
```text
A dictionary can be used to guide the fuzzer. Write me a dictionary file for fuzzing a <PNG parser>. Each line should be a quoted string or key-value pair like kw="value". Include magic bytes, chunk types, and common header values. Use hex escapes like "\xF7\xF8" for binary values.
```

**From header files:**
```bash
grep -o ''".*"'' header.h > header.dict
```

**From man pages (for CLI tools):**
```bash
man curl | grep -oP ''^\s*(--|-)\K\S+'' | sed ''s/[,.]$//'' | sed ''s/^/"&/; s/$/&"/'' | sort -u > man.dict
```

**From binary strings:**
```bash
strings ./binary | sed ''s/^/"&/; s/$/&"/'' > strings.dict
```

### Step 3: Pass Dictionary to Fuzzer

Use the appropriate flag for your fuzzer (see Quick Reference above).

## Common Patterns

### Pattern: Protocol Keywords

**Use Case:** Fuzzing HTTP or custom protocol handlers

**Dictionary content:**
```conf
# HTTP methods
"GET"
"POST"
"PUT"
"DELETE"
"HEAD"

# Headers
"Content-Type"
"Authorization"
"Host"

# Protocol markers
"HTTP/1.1"
"HTTP/2.0"
```

### Pattern: Magic Bytes and File Format Headers

**Use Case:** Fuzzing image parsers, media decoders, archive handlers

**Dictionary content:**
```conf
# PNG magic bytes and chunks
png_magic="\x89PNG\r\n\x1a\n"
ihdr="IHDR"
plte="PLTE"
idat="IDAT"
iend="IEND"

# JPEG markers
jpeg_soi="\xFF\xD8"
jpeg_e','.claude\skills\fuzzing-dictionary\SKILL.md','1d1ad276d1a0eb8322a04a57abda5dc3884f2907c6d07f6d084e10d62a47c81a','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:fuzzing-obstacles','project_skill','skill://simplicio-runtime/fuzzing-obstacles','skill: fuzzing-obstacles','---
name: fuzzing-obstacles
type: technique
description: >
  Techniques for patching code to overcome fuzzing obstacles.
  Use when checksums, global state, or other barriers block fuzzer progress.
---

# Overcoming Fuzzing Obstacles

Codebases often contain anti-fuzzing patterns that prevent effective coverage. Checksums, global state (like time-seeded PRNGs), and validation checks can block the fuzzer from exploring deeper code paths. This technique shows how to patch your System Under Test (SUT) to bypass these obstacles during fuzzing while preserving production behavior.

## Overview

Many real-world programs were not designed with fuzzing in mind. They may:
- Verify checksums or cryptographic hashes before processing input
- Rely on global state (e.g., system time, environment variables)
- Use non-deterministic random number generators
- Perform complex validation that makes it difficult for the fuzzer to generate valid inputs

These patterns make fuzzing difficult because:
1. **Checksums:** The fuzzer must guess correct hash values (astronomically unlikely)
2. **Global state:** Same input produces different behavior across runs (breaks determinism)
3. **Complex validation:** The fuzzer spends effort hitting validation failures instead of exploring deeper code

The solution is conditional compilation: modify code behavior during fuzzing builds while keeping production code unchanged.

### Key Concepts

| Concept | Description |
|---------|-------------|
| SUT Patching | Modifying System Under Test to be fuzzing-friendly |
| Conditional Compilation | Code that behaves differently based on compile-time flags |
| Fuzzing Build Mode | Special build configuration that enables fuzzing-specific patches |
| False Positives | Crashes found during fuzzing that cannot occur in production |
| Determinism | Same input always produces same behavior (critical for fuzzing) |

## When to Apply

**Apply this technique when:**
- The fuzzer gets stuck at checksum or hash verification
- Coverage reports show large blocks of unreachable code behind validation
- Code uses time-based seeds or other non-deterministic global state
- Complex validation makes it nearly impossible to generate valid inputs
- You see the fuzzer repeatedly hitting the same validation failures

**Skip this technique when:**
- The obstacle can be overcome with a good seed corpus or dictionary
- The validation is simple enough for the fuzzer to learn (e.g., magic bytes)
- You''re doing grammar-based or structure-aware fuzzing that handles validation
- Skipping the check would introduce too many false positives
- The code is already fuzzing-friendly

## Quick Reference

| Task | C/C++ | Rust |
|------|-------|------|
| Check if fuzzing build | `#ifdef FUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION` | `cfg!(fuzzing)` |
| Skip check during fuzzing | `#ifndef FUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION return -1; #endif` | `if !cfg!(fuzzing) { return Err(...) }` |
| Common obstacles | Checksums, PRNGs, time-based logic | Checksums, PRNGs, time-based logic |
| Supported fuzzers | libFuzzer, AFL++, LibAFL, honggfuzz | cargo-fuzz, libFuzzer |

## Step-by-Step

### Step 1: Identify the Obstacle

Run the fuzzer and analyze coverage to find code that''s unreachable. Common patterns:

1. Look for checksum/hash verification before deeper processing
2. Check for calls to `rand()`, `time()`, or `srand()` with system seeds
3. Find validation functions that reject most inputs
4. Identify global state initialization that differs across runs

**Tools to help:**
- Coverage reports (see coverage-analysis technique)
- Profiling with `-fprofile-instr-generate`
- Manual code inspection of entry points

### Step 2: Add Conditional Compilation

Modify the obstacle to bypass it during fuzzing builds.

**C/C++ Example:**

```c++
// Before: Hard obstacle
if (checksum != expected_hash) {
    return -1;  // Fuzzer never gets past here
}

// After: Conditional bypass
if (checksum != expected_hash) {
#ifndef FUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION
    return -1;  // Only enforced in production
#endif
}
// F','.claude\skills\fuzzing-obstacles\SKILL.md','8294dfa0d3d1f96d9f22676a4e20f4d4289158390a212761a726e48ed3ed93f1','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:gcp-cloud-architect','project_skill','skill://simplicio-runtime/gcp-cloud-architect','skill: gcp-cloud-architect','---
name: gcp-cloud-architect
description: "Design GCP architectures for startups and enterprises. Use when asked to design Google Cloud infrastructure, deploy to GKE or Cloud Run, configure BigQuery pipelines, optimize GCP costs, or migrate to GCP. Covers Cloud Run, GKE, Cloud Functions, Cloud SQL, BigQuery, and cost optimization."
---

# GCP Cloud Architect

Design scalable, cost-effective Google Cloud architectures for startups and enterprises with infrastructure-as-code templates.

---

## Workflow

### Step 1: Gather Requirements

Collect application specifications:

```
- Application type (web app, mobile backend, data pipeline, SaaS)
- Expected users and requests per second
- Budget constraints (monthly spend limit)
- Team size and GCP experience level
- Compliance requirements (GDPR, HIPAA, SOC 2)
- Availability requirements (SLA, RPO/RTO)
```

### Step 2: Design Architecture

Run the architecture designer to get pattern recommendations:

```bash
python scripts/architecture_designer.py --input requirements.json
```

**Example output:**

```json
{
  "recommended_pattern": "serverless_web",
  "service_stack": ["Cloud Storage", "Cloud CDN", "Cloud Run", "Firestore", "Identity Platform"],
  "estimated_monthly_cost_usd": 30,
  "pros": ["Low ops overhead", "Pay-per-use", "Auto-scaling", "No cold starts on Cloud Run min instances"],
  "cons": ["Vendor lock-in", "Regional limitations", "Eventual consistency with Firestore"]
}
```

Select from recommended patterns:
- **Serverless Web**: Cloud Storage + Cloud CDN + Cloud Run + Firestore
- **Microservices on GKE**: GKE Autopilot + Cloud SQL + Memorystore + Cloud Pub/Sub
- **Serverless Data Pipeline**: Pub/Sub + Dataflow + BigQuery + Looker
- **ML Platform**: Vertex AI + Cloud Storage + BigQuery + Cloud Functions

See `references/architecture_patterns.md` for detailed pattern specifications.

**Validation checkpoint:** Confirm the recommended pattern matches the team''s operational maturity and compliance requirements before proceeding to Step 3.

### Step 3: Estimate Cost

Analyze estimated costs and optimization opportunities:

```bash
python scripts/cost_optimizer.py --resources current_setup.json --monthly-spend 2000
```

**Example output:**

```json
{
  "current_monthly_usd": 2000,
  "recommendations": [
    { "action": "Right-size Cloud SQL db-custom-4-16384 to db-custom-2-8192", "savings_usd": 380, "priority": "high" },
    { "action": "Purchase 1-yr committed use discount for GKE nodes", "savings_usd": 290, "priority": "high" },
    { "action": "Move Cloud Storage objects >90 days to Nearline", "savings_usd": 75, "priority": "medium" }
  ],
  "total_potential_savings_usd": 745
}
```

Output includes:
- Monthly cost breakdown by service
- Right-sizing recommendations
- Committed use discount opportunities
- Sustained use discount analysis
- Potential monthly savings

Use the [GCP Pricing Calculator](https://cloud.google.com/products/calculator) for detailed estimates.

### Step 4: Generate IaC

Create infrastructure-as-code for the selected pattern:

```bash
python scripts/deployment_manager.py --app-name my-app --pattern serverless_web --region us-central1
```

**Example Terraform HCL output (Cloud Run + Firestore):**

```hcl
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

resource "google_cloud_run_v2_service" "api" {
  name     = "${var.environment}-${var.app_name}-api"
  location = var.region

  template {
    containers {
      image = "gcr.io/${var.project_id}/${var.app_name}:latest"
      resources {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
      }
      env {
        name  = "FIRESTORE_PROJECT"
        value = var.project_id
      }
    }
    scaling {
      min_instance_count = 0
      max','.claude\skills\gcp-cloud-architect\SKILL.md','6ebe5b4c58f23e354504cbd1f70ad78ee8f57cdab75fe7bb70300b0fcd6deeca','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:gdpr-audit-prep','project_skill','skill://simplicio-runtime/gdpr-audit-prep','skill: gdpr-audit-prep','---
name: gdpr-audit-prep
description: "/cs:gdpr-audit-prep <scope> — GDPR audit 6-question Article-cited forcing interrogation. Use before annual internal GDPR review, post-breach internal audit, DPA investigation readiness, or acquisition due diligence."
---

# /cs:gdpr-audit-prep — GDPR DPO Forcing Questions

**Command:** `/cs:gdpr-audit-prep <scope>`

The GDPR DPO auditor pressure-tests any privacy compliance work. Six Article-cited questions before any internal audit, breach response, DPA investigation, or acquisition due diligence.

## When to Run

- Before annual internal GDPR audit
- Before quarterly Article 30 RoPA refresh
- Before launching new high-risk processing (Article 35 DPIA required)
- Post-breach (Articles 33-34)
- Before DPA investigation response or supervisory authority engagement
- During acquisition due diligence (target company privacy posture)
- Quarterly during high-volume new-feature shipping

## The Six DPO Questions

### 1. Show me the Article 30 RoPA — with last-updated date.
**Most-cited finding area.**
- Must include all Article 30(1)(a)-(g) elements for controllers
- Must include all Article 30(2)(a)-(d) elements for processors
- Updated within reasonable time of changes (90 days expected)
- Joint controller arrangements documented per Article 26

### 2. For this processing activity, what''s the lawful basis under Article 6?
**Article 6 is exclusive — pick ONE basis per purpose.**
- Six options: consent / contract / legal obligation / vital interests / public task / legitimate interests
- Where "legitimate interests": LIA documented
- Where "consent": records per Article 7; withdrawal mechanism
- Special categories (Article 9) require an Article 9(2) exception

### 3. For high-risk processing, where''s the DPIA per Article 35?
**Required for high-risk; sample 3-5 activities.**
- Article 35(7)(a)-(d) required elements:
  - Systematic description of processing
  - Necessity + proportionality assessment
  - Risks to rights + freedoms
  - Measures to address risks
- DPO consulted per Article 35(2)
- Article 36 prior consultation triggered for residual high risk
- For AI systems: integrates with EU AI Act Article 27 FRIA (cross-check with cs-ai-act-compliance)

### 4. Show me a DSAR from the last 30 days — and the response timing.
**Articles 15-22 operational workflow.**
- Response within 1 month (Article 12(3)); extension up to 2 months for complex requests
- Identity verification process documented
- Right of access response includes all Article 15 information
- Right to erasure (Article 17) workflow covers backups + processors

### 5. Show me Transfer Impact Assessments for the largest non-EU transfers.
**Schrems II discipline.**
- Adequacy decision OR SCCs (Article 46) OR derogation (Article 49)
- TIA per EDPB Recommendations 01/2020 + 02/2020
- Supplementary measures where TIA flagged risk
- US transfers covered by EU-US Data Privacy Framework adequacy (Jul 2023) — verify list of certified entities

### 6. Show me the breach log per Article 33(5) — all breaches, not just notifiable ones.
**Article 33(5) requires logging ALL breaches.**
- Internal breach detection mechanism documented
- Article 33 DPA notification within 72 hours (where required)
- Article 34 data subject notification (where high risk)
- Root cause + corrective action via CAPA system
- Cross-check with cs-ciso-iso27001 for A.5.24-27 incident management alignment

## Workflow

```bash
# 1. Compliance posture
python ra-qm-team/skills/gdpr-dsgvo-expert/scripts/gdpr_compliance_checker.py compliance_state.json

# 2. DPIA for high-risk activities
python ra-qm-team/skills/gdpr-dsgvo-expert/scripts/dpia_generator.py processing_activity.json

# 3. DSAR workflow validation
python ra-qm-team/skills/gdpr-dsgvo-expert/scripts/data_subject_rights_tracker.py dsar_log.json

# 4. Cross-framework reuse with ISO 27001 + SOC 2 + ISO 42001
python ../../skills/compliance-os/scripts/cross_framework_mapper.py program.json
```

## Output Format

```markdown
# GDPR Audit Prep: <scope>
**Date:** YYYY-MM-DD
**Article Citations:** Every finding cites A','.claude\skills\gdpr-audit-prep\SKILL.md','47fc06f332a949d14b7ec88b4071f57113169628a7f855a740f8b8825ccb3210','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:gdpr-dsgvo-expert','project_skill','skill://simplicio-runtime/gdpr-dsgvo-expert','skill: gdpr-dsgvo-expert','---
name: gdpr-dsgvo-expert
description: GDPR and German DSGVO compliance automation. Scans codebases for privacy risks, generates DPIA documentation, tracks data subject rights requests with Art. 12(3) one-month deadlines. Use when running GDPR compliance assessments, privacy audits, data protection planning, DPIA generation, or data subject rights (DSAR) management (e.g., ''check this service for GDPR risks'', ''track an access request deadline''). Final compliance determinations route to the DPO or legal counsel.
---

# GDPR/DSGVO Expert

Tools and guidance for EU General Data Protection Regulation (GDPR) and German Bundesdatenschutzgesetz (BDSG) compliance.

---

## Table of Contents

- [Tools](#tools)
  - [GDPR Compliance Checker](#gdpr-compliance-checker)
  - [DPIA Generator](#dpia-generator)
  - [Data Subject Rights Tracker](#data-subject-rights-tracker)
- [Reference Guides](#reference-guides)
- [Workflows](#workflows)

---

## Tools

### GDPR Compliance Checker

Scans codebases for potential GDPR compliance issues including personal data patterns and risky code practices.

```bash
# Scan a project directory
python scripts/gdpr_compliance_checker.py /path/to/project

# JSON output for CI/CD integration
python scripts/gdpr_compliance_checker.py . --json --output report.json
```

**Detects:**
- Personal data patterns (email, phone, IP addresses)
- Special category data (health, biometric, religion)
- Financial data (credit cards, IBAN)
- Risky code patterns:
  - Logging personal data
  - Missing consent mechanisms
  - Indefinite data retention
  - Unencrypted sensitive data
  - Disabled deletion functionality

**Output:**
- Compliance score (0-100)
- Risk categorization (critical, high, medium)
- Prioritized recommendations with GDPR article references

---

### DPIA Generator

Generates Data Protection Impact Assessment documentation following Art. 35 requirements.

```bash
# Get input template
python scripts/dpia_generator.py --template > input.json

# Generate DPIA report
python scripts/dpia_generator.py --input input.json --output dpia_report.md
```

**Features:**
- Automatic DPIA threshold assessment
- Risk identification based on processing characteristics
- Legal basis requirements documentation
- Mitigation recommendations
- Markdown report generation

**DPIA Triggers Assessed:**
- Systematic monitoring (Art. 35(3)(c))
- Large-scale special category data (Art. 35(3)(b))
- Automated decision-making (Art. 35(3)(a))
- EDPB-endorsed high-risk criteria (WP248 rev.01)

---

### Data Subject Rights Tracker

Manages data subject rights requests under GDPR Articles 15-22.

```bash
# Add new request
python scripts/data_subject_rights_tracker.py add \
  --type access --subject "John Doe" --email "john@example.com"

# List all requests
python scripts/data_subject_rights_tracker.py list

# Update status
python scripts/data_subject_rights_tracker.py status --id DSR-202601-0001 --update verified

# Generate compliance report
python scripts/data_subject_rights_tracker.py report --output compliance.json

# Generate response template
python scripts/data_subject_rights_tracker.py template --id DSR-202601-0001
```

**Supported Rights:**

| Right | Article | Deadline |
|-------|---------|----------|
| Access | Art. 15 | One month (Art. 12(3)) |
| Rectification | Art. 16 | One month (Art. 12(3)) |
| Erasure | Art. 17 | One month (Art. 12(3)) |
| Restriction | Art. 18 | One month (Art. 12(3)) |
| Portability | Art. 20 | One month (Art. 12(3)) |
| Objection | Art. 21 | One month (Art. 12(3)) |
| Automated decisions | Art. 22 | One month (Art. 12(3)) |

**Features:**
- Deadline tracking with overdue alerts
- Identity verification workflow
- Response template generation
- Compliance reporting

---

## Reference Guides

### GDPR Compliance Guide
`references/gdpr_compliance_guide.md`

Comprehensive implementation guidance covering:
- Legal bases for processing (Art. 6)
- Special category requirements (Art. 9)
- Data subject rights implementation
- Accountability requirements (Art. 30)
- International transfers (Chapter V)
- Breach notifica','.claude\skills\gdpr-dsgvo-expert\SKILL.md','bab1d171d5c50480e45dbdcece9c47e258d6ccf7eb196955102e6acb6aeb062c','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:general-video','project_skill','skill://simplicio-runtime/general-video','skill: general-video','---
name: general-video
description: >
  The fallback workflow for authoring custom HyperFrames video compositions at
  any length or format — longer or multi-scene pieces, brand / sizzle reels,
  montages, title cards, static loops, and freeform compositions. Input- and
  length-agnostic. If a specialized workflow clearly fits the input — a
  marketed product, a website, a topic explainer, a GitHub PR, existing
  footage, a short motion graphic, or a Remotion port — prefer it (see
  /hyperframes); use this only as the general fallback when none fit.
metadata: { "tags": "orchestrator, general-video, fallback, freeform, composition-authoring" }
---

# general-video — general video workflow

> **Confirm the route before you build.** This is the **fallback** for custom composition authoring. If the input clearly fits a specialized workflow, prefer it: marketed product → `/product-launch-video`; general site → `/website-to-video`; topic explainer → `/faceless-explainer`; GitHub PR → `/pr-to-video`; existing footage → `/embedded-captions` · `/graphic-overlays`; short unnarrated motion graphic → `/motion-graphics`; Remotion port → `/remotion-to-hyperframes`. **Out of scope**: live / at-render-time data, NLE-style editing of a finished video, or producing footage HyperFrames can''t capture. Unsure? **Read `/hyperframes` first.**

**Build exactly what was asked.** A title card is a title card — not a title card + three supporting scenes + ambient music + captions. If extra scenes or elements would genuinely improve the piece, _propose_ them; don''t add them silently. For small edits (fix a color, adjust one duration, add one element), skip the planning steps and go straight to the build.

## Approach

### Discovery — open-ended requests only

For vague, exploratory requests ("make something for our brand", "a cool intro") — understand intent before picking colors:

- **Audience** — who watches? developers / executives / general consumers?
- **Platform** — where does it play? social (15s) / website hero / product demo / internal?
- **Priority** — what matters most? motion quality / content accuracy / brand fidelity / speed?
- **Variations** — one best shot, or 2-3 meaningfully different options (different pacing, energy, or structure — not just color swaps)?

For specific requests ("add a title card", "fix the timing on scene 3"), skip discovery.

### Step 1 — Design system → `hyperframes-creative`

Establish the visual identity first. If the project has a design spec, read it (precedence `frame.md` → `design.md` → `DESIGN.md`; treat it as brand truth — exact colors, fonts, constraints).

**If no spec exists, you MUST read BOTH `hyperframes-creative/references/house-style.md` AND `hyperframes-creative/references/video-composition.md` before choosing any color or font.** `house-style.md` gives the "interpret the prompt / generate real content" opener, lazy-default list, and layer recipe; `video-composition.md` gives the video-medium density / scale / **foreground detailing** (data bars, registration marks, monospace metadata, "8-10 elements, two the user didn''t ask for") that separates "produced" from "generated." Reading only one is the most common miss — `video-composition.md` is the one agents skip, and it is exactly the one that prevents flat, centered, web-page-looking output. Do not self-invent a palette and skip these; crossing into `hyperframes-creative` is mandatory here, not an optional branch. From there, also pull a named style/mood → `references/visual-styles.md`, or the interactive picker → `references/design-picker.md`, as needed. The spec/style defines the **brand**, not the composition rules.

**Find the angle (vague brief, no spec):** before picking colors, write ONE sentence — what does this name/word/topic evoke, and what visual _world_ (metaphor, setting, instrument, motif) expresses it? E.g. a cybersecurity tool → vault doors / perimeter scan lines / lock tumblers; a meditation app → tide, breath, slow light bloom. Read the _meaning_ of the subject, not just its letters; pick a concrete angle over a literal res','.claude\skills\general-video\SKILL.md','d9402f9a9efe5d26d3e178d7cc3af14b77a5e08f7e7f9a72b67670d5fa21ecc3','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:generate','project_skill','skill://simplicio-runtime/generate','skill: generate','---
name: generate
description: >-
  Generate Playwright tests. Use when user says "write tests", "generate tests",
  "add tests for", "test this component", "e2e test", "create test for",
  "test this page", or "test this feature".
---

# Generate Playwright Tests

Generate production-ready Playwright tests from a user story, URL, component name, or feature description.

## Input

`$ARGUMENTS` contains what to test. Examples:
- `"user can log in with email and password"`
- `"the checkout flow"`
- `"src/components/UserProfile.tsx"`
- `"the search page with filters"`

## Steps

### 1. Understand the Target

Parse `$ARGUMENTS` to determine:
- **User story**: Extract the behavior to verify
- **Component path**: Read the component source code
- **Page/URL**: Identify the route and its elements
- **Feature name**: Map to relevant app areas

### 2. Explore the Codebase

Use the `Explore` subagent to gather context:

- Read `playwright.config.ts` for `testDir`, `baseURL`, `projects`
- Check existing tests in `testDir` for patterns, fixtures, and conventions
- If a component path is given, read the component to understand its props, states, and interactions
- Check for existing page objects in `pages/`
- Check for existing fixtures in `fixtures/`
- Check for auth setup (`auth.setup.ts` or `storageState` config)

### 3. Select Templates

Check `templates/` in this plugin for matching patterns:

| If testing... | Load template from |
|---|---|
| Login/auth flow | `../pw/templates/auth/login.md` |
| CRUD operations | `templates/crud/` |
| Checkout/payment | `templates/checkout/` |
| Search/filter UI | `templates/search/` |
| Form submission | `templates/forms/` |
| Dashboard/data | `templates/dashboard/` |
| Settings page | `templates/settings/` |
| Onboarding flow | `templates/onboarding/` |
| API endpoints | `templates/api/` |
| Accessibility | `templates/accessibility/` |

Adapt the template to the specific app — replace `{{placeholders}}` with actual selectors, URLs, and data.

### 4. Generate the Test

Follow these rules:

**Structure:**
```typescript
import { test, expect } from ''@playwright/test'';
// Import custom fixtures if the project uses them

test.describe(''Feature Name'', () => {
  // Group related behaviors

  test(''should <expected behavior>'', async ({ page }) => {
    // Arrange: navigate, set up state
    // Act: perform user action
    // Assert: verify outcome
  });
});
```

**Locator priority** (use the first that works):
1. `getByRole()` — buttons, links, headings, form elements
2. `getByLabel()` — form fields with labels
3. `getByText()` — non-interactive text content
4. `getByPlaceholder()` — inputs with placeholder text
5. `getByTestId()` — when semantic options aren''t available

**Assertions** — always web-first:
```typescript
// GOOD — auto-retries
await expect(page.getByRole(''heading'')).toBeVisible();
await expect(page.getByRole(''alert'')).toHaveText(''Success'');

// BAD — no retry
const text = await page.textContent(''.msg'');
expect(text).toBe(''Success'');
```

**Never use:**
- `page.waitForTimeout()`
- `page.$(selector)` or `page.$$(selector)`
- Bare CSS selectors unless absolutely necessary
- `page.evaluate()` for things locators can do

**Always include:**
- Descriptive test names that explain the behavior
- Error/edge case tests alongside happy path
- Proper `await` on every Playwright call
- `baseURL`-relative navigation (`page.goto(''/'')` not `page.goto(''http://...'')`)

### 5. Match Project Conventions

- If project uses TypeScript → generate `.spec.ts`
- If project uses JavaScript → generate `.spec.js` with `require()` imports
- If project has page objects → use them instead of inline locators
- If project has custom fixtures → import and use them
- If project has a test data directory → create test data files there

### 6. Generate Supporting Files (If Needed)

- **Page object**: If the test touches 5+ unique locators on one page, create a page object
- **Fixture**: If the test needs shared setup (auth, data), create or extend a fixture
- **Test data**: If the test uses structured data, create a JSON ','.claude\skills\generate\SKILL.md','1b81423897ecc33f4ea5712ee056be6abb4c0694fd09d9442b5213ee3749db79','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:genotoxic','project_skill','skill://simplicio-runtime/genotoxic','skill: genotoxic','---
name: genotoxic
description: "Graph-informed mutation testing triage. Parses codebases with Trailmark, runs mutation testing and necessist, then uses survived mutants, unnecessary test statements, and call graph data to identify false positives, missing test coverage, and fuzzing targets. Use when triaging survived mutants, analyzing mutation testing results, identifying test gaps, finding fuzzing targets from weak tests, running mutation frameworks (including circomvent and cairo-mutants), or using necessist."
---

# Genotoxic

Combines mutation testing and necessist (test statement removal) with
code graph analysis to triage findings into actionable categories:
false positives, missing unit tests, and fuzzing targets.

## When to Use

- After mutation testing reveals survived mutants that need triage
- Identifying where unit tests would have the highest impact
- Finding functions that need fuzz harnesses instead of unit tests
- Prioritizing test improvements using data flow context
- Filtering out harmless mutants from actionable ones
- Finding unnecessary test statements that indicate weak assertions (necessist)

## When NOT to Use

- Codebase has no existing test suite (write tests first)
- Pure documentation or configuration changes
- Single-file scripts with trivial logic

## Prerequisites

- **trailmark** installed — if `uv run trailmark` fails, run:
  ```bash
  uv pip install trailmark
  ```
  **DO NOT** fall back to "manual verification" or "manual analysis"
  as a substitute for running trailmark. Install it first. If installation
  fails, report the error instead of switching to manual analysis.
- A **mutation testing framework** for the target language — if the framework
  command fails (not found, not installed), install it using the instructions
  in [references/mutation-frameworks.md](references/mutation-frameworks.md).
  **DO NOT** fall back to "manual mutation analysis" or skip mutation testing.
  Install the framework first. If installation fails, report the error
  instead of switching to manual mutation analysis.
- **necessist** (optional, recommended) — if the target language is
  supported (Go, Rust, Solidity/Foundry, TypeScript/Hardhat,
  TypeScript/Vitest, Rust/Anchor), install with `cargo install necessist`.
  See [references/mutation-frameworks.md](references/mutation-frameworks.md)
  for details.
- An existing test suite that passes
- **macOS environment**: Run `ulimit -n 1024` before any `mull-runner`
  invocation. macOS Tahoe (26+) sets unlimited file descriptors by
  default, which crashes Mull''s subprocess spawning. See
  [references/mutation-frameworks.md](references/mutation-frameworks.md)
  for details.

---

## Rationalizations to Reject

| Rationalization | Why It''s Wrong | Required Action |
|-----------------|----------------|-----------------|
| "All survived mutants need tests" | Many are harmless or equivalent | Triage before writing tests |
| "Mutation testing is too noisy" | Noise means you''re not triaging | Use graph data to filter |
| "Unit tests cover everything" | Complex data flows need fuzzing | Check entrypoint reachability |
| "Dead code mutants don''t matter" | Dead code should be removed | Flag for cleanup |
| "Low complexity = low risk" | Boundary bugs hide in simple code | Check mutant location |
| "Tool isn''t installed, I''ll do it manually" | Manual analysis misses what tooling catches | Install the tool first |
| "Necessist isn''t mutation testing, skip it" | Necessist finds what mutation testing misses: weak tests | Run both when the language supports it |

---

## Quick Start

```bash
# 1. Build the code graph
uv run trailmark analyze --language auto --summary {targetDir}

# 2. Run mutation testing (language-dependent)
# Python:
uv run mutmut run --paths-to-mutate {targetDir}/src
uv run mutmut results

# 2b. Run necessist (if language supported)
necessist

# 3. Analyze results with this skill''s workflow (Phase 3)
```

---

## Workflow Overview

```
Phase 1: Graph Build      → Parse codebase with trailmark
      ↓
Phase 2: Mutation Run     → Execute mutation test','.claude\skills\genotoxic\SKILL.md','aa1333316c5c899c36fd4ef4f1eea0771e42632cc48be8fdc0605a942e42d5d2','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:gh-cli','project_skill','skill://simplicio-runtime/gh-cli','skill: gh-cli','---
name: gh-cli
description: Enforces authenticated gh CLI workflows over unauthenticated curl/WebFetch patterns. Use when working with GitHub URLs, API access, pull requests, or issues.
---

# gh-cli

## When to Use

- Working with GitHub repositories, pull requests, issues, releases, or raw file URLs.
- You need authenticated access to private repositories or higher API rate limits.
- You are about to use `curl`, `wget`, or unauthenticated web fetches against GitHub.

## When NOT to Use

- The target is not GitHub.
- Plain local git operations already solve the task.

## Guidance

Prefer the authenticated `gh` CLI over raw HTTP fetches for GitHub content. In particular:

- Prefer `gh repo view`, `gh pr view`, `gh pr list`, `gh issue view`, and `gh api` over unauthenticated `curl` or `wget`.
- Prefer cloning a repository and reading files locally over fetching `raw.githubusercontent.com` blobs directly.
- Avoid using GitHub API `/contents/` endpoints as a substitute for cloning and reading repository files.

Examples:

```sh
gh repo view owner/repo
gh pr view 123 --repo owner/repo
gh api repos/owner/repo/pulls
```

For the hook implementation, see:
- `plugins/gh-cli/README.md`
- `plugins/gh-cli/hooks/`

<!-- Source: https://github.com/trailofbits/skills (CC-BY-SA-4.0). Imported into Simplicio (lean: SKILL.md only). Area: security. -->
','.claude\skills\gh-cli\SKILL.md','efb90323b32a3bb78a8961908776ef5f0c59e83a10c85c2dfbae3dadeac23fa7','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:git-cleanup','project_skill','skill://simplicio-runtime/git-cleanup','skill: git-cleanup','---
name: git-cleanup
description: "Safely analyzes and cleans up local git branches and worktrees by categorizing them as merged, squash-merged, superseded, or active work."
disable-model-invocation: true
allowed-tools: Bash Read Grep AskUserQuestion
---

# Git Cleanup

Safely clean up accumulated git worktrees and local branches by categorizing them into: safely deletable (merged), potentially related (similar themes), and active work (keep).

## When to Use

- When the user has accumulated many local branches and worktrees
- When branches have been merged but not cleaned up locally
- When remote branches have been deleted but local tracking branches remain

## When NOT to Use

- Do not use for remote branch management (this is local cleanup only)
- Do not use for repository maintenance tasks like gc or prune
- Not designed for headless or non-interactive automation (requires user confirmations at two gates)

## Core Principle: SAFETY FIRST

**Never delete anything without explicit user confirmation.** This skill uses a gated workflow where users must approve each step before any destructive action.

## Critical Implementation Notes

### Squash-Merged Branches Require Force Delete

**IMPORTANT:** `git branch -d` will ALWAYS fail for squash-merged branches because git cannot detect that the work was incorporated. This is expected behavior, not an error.

When you identify a branch as squash-merged:
- Plan to use `git branch -D` (force delete) from the start
- Do NOT try `git branch -d` first and then ask again for `-D` - this wastes user confirmations
- In the confirmation step, show `git branch -D` for squash-merged branches

### Group Related Branches BEFORE Categorization

**MANDATORY:** Before categorizing individual branches, group them by name prefix:

```bash
# Extract common prefixes from branch names
# e.g., feature/auth-*, feature/api-*, fix/login-*
```

Branches sharing a prefix (e.g., `feature/api`, `feature/api-v2`, `feature/api-refactor`) are almost certainly related iterations. Analyze them as a group:

1. Find the oldest and newest by commit date
2. Check if newer branches contain commits from older ones
3. Check which PRs merged work from each
4. Determine if older branches are superseded

Present related branches together with a clear recommendation, not scattered across categories.

### Thorough PR History Investigation

Don''t rely on simple keyword matching. For `[gone]` branches:

```bash
# 1. Get the branch''s commits that aren''t in default branch
git log --oneline "$default_branch".."$branch"

# 2. Search default branch for PRs that incorporated this work
# Search by: branch name, commit message keywords, PR numbers
git log --oneline "$default_branch" | grep -iE "(branch-name|keyword|#[0-9]+)"

# 3. For related branch groups, trace which PRs merged which work
git log --oneline "$default_branch" | grep -iE "(#[0-9]+)" | head -20
```

## Workflow

### Phase 1: Comprehensive Analysis

Gather ALL information upfront before any categorization:

```bash
# Get default branch name
default_branch=$(git symbolic-ref refs/remotes/origin/HEAD \
  2>/dev/null | sed ''s@^refs/remotes/origin/@@'' || echo "main")

# Protected branches - never analyze or delete
protected=''^(main|master|develop|release/.*)$''

# List all local branches with tracking info
git branch -vv

# List all worktrees
git worktree list

# Fetch and prune to sync remote state
git fetch --prune

# Get merged branches (into default branch)
git branch --merged "$default_branch"

# Get recent PR merge history (squash-merge detection)
git log --oneline "$default_branch" | grep -iE "#[0-9]+" | head -30

# For EACH non-protected branch, get unique commits and sync status
for branch in $(git branch --format=''%(refname:short)'' \
  | grep -vE "$protected"); do
  echo "=== $branch ==="
  echo "Commits not in $default_branch:"
  git log --oneline "$default_branch".."$branch" 2>/dev/null \
    | head -5
  echo "Commits not pushed to remote:"
  git log --oneline "origin/$branch".."$branch" 2>/dev/null \
    | head -5 || echo "(no remote tracking)"
done
```

**N','.claude\skills\git-cleanup\SKILL.md','e6f8e3f672bb3f0c5e6e681d0504ca6c53f9344697aadbd5e2f2c34d3f7f32cb','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:git-worktree-manager','project_skill','skill://simplicio-runtime/git-worktree-manager','skill: git-worktree-manager','---
name: git-worktree-manager
description: "Run parallel feature work safely with Git worktrees. Standardizes branch isolation, port allocation, environment sync, and cleanup so each worktree behaves like an independent local app. Optimized for multi-agent workflows where each agent or terminal session owns one worktree. Use when running multiple feature branches simultaneously, isolating experimental work, or coordinating multi-agent development across the same repo."
---

# Git Worktree Manager

**Tier:** POWERFUL  
**Category:** Engineering  
**Domain:** Parallel Development & Branch Isolation

## Overview

Use this skill to run parallel feature work safely with Git worktrees. It standardizes branch isolation, port allocation, environment sync, and cleanup so each worktree behaves like an independent local app without stepping on another branch.

This skill is optimized for multi-agent workflows where each agent or terminal session owns one worktree.

## Core Capabilities

- Create worktrees from new or existing branches with deterministic naming
- Auto-allocate non-conflicting ports per worktree and persist assignments
- Copy local environment files (`.env*`) from main repo to new worktree
- Optionally install dependencies based on lockfile detection
- Detect stale worktrees and uncommitted changes before cleanup
- Identify merged branches and safely remove outdated worktrees

## When to Use

- You need 2+ concurrent branches open locally
- You want isolated dev servers for feature, hotfix, and PR validation
- You are working with multiple agents that must not share a branch
- Your current branch is blocked but you need to ship a quick fix now
- You want repeatable cleanup instead of ad-hoc `rm -rf` operations

## Key Workflows

### 1. Create a Fully-Prepared Worktree

1. Pick a branch name and worktree name.
2. Run the manager script (creates branch if missing).
3. Review generated port map.
4. Start app using allocated ports.

```bash
python scripts/worktree_manager.py \
  --repo . \
  --branch feature/new-auth \
  --name wt-auth \
  --base-branch main \
  --install-deps \
  --format text
```

If you use JSON automation input:

```bash
cat config.json | python scripts/worktree_manager.py --format json
# or
python scripts/worktree_manager.py --input config.json --format json
```

### 2. Run Parallel Sessions

Recommended convention:

- Main repo: integration branch (`main`/`develop`) on default port
- Worktree A: feature branch + offset ports
- Worktree B: hotfix branch + next offset

Each worktree contains `.worktree-ports.json` with assigned ports.

### 3. Cleanup with Safety Checks

1. Scan all worktrees and stale age.
2. Inspect dirty trees and branch merge status.
3. Remove only merged + clean worktrees, or force explicitly.

```bash
python scripts/worktree_cleanup.py --repo . --stale-days 14 --format text
python scripts/worktree_cleanup.py --repo . --remove-merged --format text
```

### 4. Docker Compose Pattern

Use per-worktree override files mapped from allocated ports. The script outputs a deterministic port map; apply it to `docker-compose.worktree.yml`.

See [docker-compose-patterns.md](references/docker-compose-patterns.md) for concrete templates.

### 5. Port Allocation Strategy

Default strategy is `base + (index * stride)` with collision checks:

- App: `3000`
- Postgres: `5432`
- Redis: `6379`
- Stride: `10`

See [port-allocation-strategy.md](references/port-allocation-strategy.md) for the full strategy and edge cases.

## Script Interfaces

- `python scripts/worktree_manager.py --help`
  - Create/list worktrees
  - Allocate/persist ports
  - Copy `.env*` files
  - Optional dependency installation
- `python scripts/worktree_cleanup.py --help`
  - Stale detection by age
  - Dirty-state detection
  - Merged-branch detection
  - Optional safe removal

Both tools support stdin JSON and `--input` file mode for automation pipelines.

## Common Pitfalls

1. Creating worktrees inside the main repo directory
2. Reusing `localhost:3000` across all branches
3. Sharing one database URL across isolated feature ','.claude\skills\git-worktree-manager\SKILL.md','f48ff5b01ae8562ce842facb8176adf508a083568e4919a690d2d1063066fef3','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:google-workspace-cli','project_skill','skill://simplicio-runtime/google-workspace-cli','skill: google-workspace-cli','---
name: google-workspace-cli
description: "Google Workspace administration via the gws CLI (github.com/googleworkspace/cli). Install, authenticate, and automate Gmail, Drive, Sheets, Calendar, Docs, Chat, and Tasks. Run security audits and use local recipe templates and persona bundles. Use for Google Workspace admin, gws CLI setup, Gmail automation, Drive management, or Calendar scheduling."
---

# Google Workspace CLI

Expert guidance and automation for Google Workspace administration using the open-source `gws` CLI ([github.com/googleworkspace/cli](https://github.com/googleworkspace/cli), Apache-2.0). The CLI builds its command surface dynamically from Google''s Discovery Service, so it covers every supported Workspace API plus `+`-prefixed helper commands. This skill adds local Python tools (doctor, auth guide, recipe catalog, security audit, output analyzer).

> **Verify before scripting:** `gws` generates commands at runtime from Google''s API discovery documents, and the CLI is pre-v1.0. Always confirm a command''s exact surface with `gws --help`, `gws <service> --help`, or `gws schema <service>.<resource>.<method>` before putting it in automation. Commands in this skill marked *(verify)* are illustrative of the `gws <service> <resource> <method>` pattern and must be checked against your installed version.

---

## Quick Start

### Check Installation

```bash
# Verify gws is installed and authenticated
python3 scripts/gws_doctor.py
```

### Send an Email

```bash
gws gmail +send --to "team@company.com" \
  --subject "Weekly Update" --body "Here''s this week''s summary..."
```

### List Drive Files

```bash
gws drive files list --params ''{"pageSize": 20}'' | python3 scripts/output_analyzer.py --select "name,mimeType,modifiedTime" --format table
```

---

## Installation

### npm (recommended; requires Node.js 18+)

```bash
npm install -g @googleworkspace/cli
gws --version
```

### Homebrew (macOS/Linux)

```bash
brew install googleworkspace-cli
```

### Cargo (from source)

```bash
cargo install --git https://github.com/googleworkspace/cli --locked
gws --version
```

### Pre-built Binaries

Download from [github.com/googleworkspace/cli/releases](https://github.com/googleworkspace/cli/releases) for macOS, Linux, or Windows. Nix users: `nix run github:googleworkspace/cli`.

### Verify Installation

```bash
python3 scripts/gws_doctor.py
# Checks: PATH, version, auth status, service connectivity
```

---

## Authentication

### OAuth Setup (Interactive)

```bash
# Step 1: Create Google Cloud project and OAuth credentials
python3 scripts/auth_setup_guide.py --guide oauth

# Step 2: Run interactive auth setup (uses gcloud if available)
gws auth setup

# Step 3: Log in, requesting only the scopes you need
gws auth login -s drive,gmail,sheets
```

### Headless/CI

```bash
# Generate setup instructions
python3 scripts/auth_setup_guide.py --guide service-account

# Export credentials from an interactive machine, then point the CLI at them
gws auth export --unmasked > credentials.json
export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/credentials.json
```

### Environment Variables

```bash
# Generate .env template
python3 scripts/auth_setup_guide.py --generate-env
```

| Variable | Purpose |
|----------|---------|
| `GOOGLE_WORKSPACE_CLI_CLIENT_ID` | OAuth client ID |
| `GOOGLE_WORKSPACE_CLI_CLIENT_SECRET` | OAuth client secret |
| `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` | Path to exported credentials JSON |
| `GOOGLE_WORKSPACE_CLI_TOKEN` | Pre-obtained OAuth token |
| `GOOGLE_WORKSPACE_CLI_CONFIG_DIR` | Override default config location |
| `GOOGLE_WORKSPACE_CLI_LOG` | Enable debug logging |

### Validate Authentication

```bash
python3 scripts/auth_setup_guide.py --validate --json
# Tests each service endpoint
```

---

## Workflow 1: Gmail Automation

**Goal:** Automate email operations — send, search, label, and filter management.

### Send, Reply, Forward (helper commands)

```bash
# Send a new email
gws gmail +send --to "client@example.com" \
  --subject "Proposal" --body "Please find attached..."

# Reply to a message (','.claude\skills\google-workspace-cli\SKILL.md','23ff6d6e254fb35795e0c98bce3e343ed513cbf4f6e2342f64cb5a938c6e94d4','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:grants','project_skill','skill://simplicio-runtime/grants','skill: grants','---
name: grants
description: "NIH grant research skill for clinical researchers. Grill-me intake (research idea + career stage + preliminary data + environment + submission posture + known institute targets) locks down the funding strategy before any search runs. Runs a 5-facet Consensus positioning analysis (with draft Significance/Innovation language), maps the research to the right NIH institutes and study sections via RePORTER, finds NOSIs and funded overlap, and produces an editable Word document (.docx) with budget/scope-aware mechanism recommendations, submission timelines, and a mandatory program officer recommendation. Use when the user asks about research funding or makes any grant-related request (e.g., ''grants for [topic]'', ''find grants for my research idea'', ''what grants match my research'', ''help me find NIH funding'', ''grant opportunities for my research''). NIH-only scope — non-NIH funders (PCORI, DOD CDMRP, VA, foundations) are out of scope and flagged at intake."
license: MIT
metadata:
  source_spec: "megaprompts/08-grants-megaprompt.md"
  build_pattern: "Path B (direct conversion)"
  research_pack_convention: "Agent Integrity Rules verbatim per PR #657 audit"
  version: 1.0.0
---

# Grants — NIH Funding Intelligence

> **Portability:** Requires `bash_tool` (for RePORTER POST via curl), Node.js with `docx` package, and a Consensus MCP connection. Works in Claude Code CLI natively. In Claude.ai with Code Execution + Consensus MCP, the workflow is supported but slower.

> **Scope: NIH-only.** Non-NIH funders (PCORI, DOD CDMRP, VA, foundations) are out of scope and flagged at intake.

For a clinical researcher with a research idea, produce a strategic NIH funding overview as an editable `.docx`. Output covers research positioning analysis, institute mapping, targeted grant discovery, and strategic recommendations the researcher can edit, copy from, and share with their mentor.

## Agent Integrity Rules (Research-Pack Convention)

Inherited; locked verbatim per PR #657 audit.

- **Execution discipline.** A step isn''t complete until result is confirmed received. Consensus calls **sequential with 1+ sec pause**. RePORTER calls sequential.
- **Data sourcing.** Count only what tool calls returned this session. Never supplement with training knowledge. Training knowledge labeled `[Not from Consensus/RePORTER — reference information]` and excluded from counts.
- **Counts & attribution.** Queries sent / results shown / results cited — three separate numbers, never conflate. Every cited paper has retrievable URL from this session.
- **Error handling.** On failure → wait 3s → retry once → log. After 3 consecutive failures across tools: stop, alert researcher, explain what''s missing. Never silently skip.
- **Transparency.** Audit Log section in the DOCX. Same standards in chat summary as in document.

See [`references/reporter_post_patterns.md`](references/reporter_post_patterns.md) for the RePORTER POST canon + plan-tier detection.

## Phase 1: Grill-Me Intake (6 forcing questions, one at a time)

### Q1 (root) — Research idea

> **Describe the research idea in 2–3 sentences. What''s the question, what''s new, and what''s the clinical relevance? Vague answers ("AI for healthcare", "biomarkers for disease X") will be rejected — push for specificity.**
>
> *Why I''m asking:* Five Consensus searches (established / stakes / current approaches / adjacent methods / gaps) depend on a precise research idea. Vague ideas produce vague gap quotes and useless positioning narrative.

Refuse mush. Re-ask once with examples if user is too broad.

### Q2 (depends on Q1) — Career stage

> **Career stage — pick one:**
>
> 1. Pre-doctoral (PhD student, T32 trainee)
> 2. Postdoctoral fellow (F32, K99 candidate)
> 3. Early career (K-award candidate, first R01)
> 4. Independent investigator (multiple R01s, established lab)
> 5. Senior PI (R35, P-series, U01 leadership)
>
> *Why I''m asking:* Career stage filters mechanism recommendations. F-series for trainees, K-series for early career, R-series for independent. Picking the wrong stage produce','.claude\skills\grants\SKILL.md','4bda25fa2a9457c0a3508e94ff26df65d4525307f0bcf5c2684e96e8b4fa88b0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:graph-evolution','project_skill','skill://simplicio-runtime/graph-evolution','skill: graph-evolution','---
name: graph-evolution
description: >
  Compares Trailmark code graphs at two source code snapshots (git commits,
  tags, or directories) to surface security-relevant structural changes.
  Detects new attack paths, complexity shifts, blast radius growth, taint
  propagation changes, and privilege boundary modifications that text diffs
  miss. Use when comparing code between commits or tags, analyzing structural
  evolution, detecting attack surface growth, reviewing what changed between
  audit snapshots, or finding security-relevant changes that text diffs miss.
---

# Graph Evolution

Builds Trailmark code graphs at two source snapshots and computes a
structural diff. Surfaces security-relevant changes that text-level
diffs miss: new attack paths, complexity shifts, blast radius growth,
taint propagation changes, and privilege boundary modifications.

## When to Use

- Comparing two git refs to understand what structurally changed
- Auditing a range of commits for security-relevant evolution
- Detecting new attack paths created by code changes
- Finding functions whose blast radius or complexity grew silently
- Identifying taint propagation changes across refactors
- Pre-release structural comparison (tag-to-tag or branch-to-branch)

## When NOT to Use

- Line-level code review (use `differential-review` for text-diff analysis)
- Single-snapshot analysis (use the `trailmark` skill directly)
- Diagram generation from a single snapshot (use the `diagramming-code` skill)
- Mutation testing triage (use the `genotoxic` skill)

## Rationalizations to Reject

| Rationalization | Why It''s Wrong | Required Action |
|-----------------|----------------|-----------------|
| "We just need the structural diff, skip pre-analysis" | Without pre-analysis, you miss taint changes, blast radius growth, and privilege boundary shifts | Run `engine.preanalysis()` on both snapshots |
| "Text diff covers what changed" | Text diffs miss new attack paths, transitive complexity shifts, and subgraph membership changes | Use structural diff to complement text diff |
| "Only added nodes matter" | Removed security functions and shifted privilege boundaries are equally dangerous | Review removals and modifications, not just additions |
| "Low-severity structural changes can be ignored" | INFO-level changes (dead code removal) can mask removed security checks | Classify every change, review removals for replaced functionality |
| "One snapshot''s graph is enough for comparison" | Single-snapshot analysis can''t detect evolution — you need both before and after | Always build and export both graphs |
| "Tool isn''t installed, I''ll compare manually" | Manual comparison misses what graph analysis catches | Install trailmark first |

---

## Prerequisites

**trailmark** must be installed. If `uv run trailmark` fails, run:

```bash
uv pip install trailmark
```

**DO NOT** fall back to "manual comparison" or reading source files as a
substitute for running trailmark. The tool must be installed and used
programmatically. If installation fails, report the error.

---

## Quick Start

```bash
# Compare two git refs (e.g., tags, branches, commits)
# 1. Build graphs at each snapshot
# 2. Run pre-analysis on both
# 3. Compute structural diff
# 4. Generate report

# Step-by-step: see Workflow below
```

---

## Decision Tree

```
├─ Need to understand what each metric means?
│  └─ Read: references/evolution-metrics.md
│
├─ Need the report output format?
│  └─ Read: references/report-format.md
│
├─ Already have two graph JSON exports?
│  └─ Jump to Phase 3 (run native diff + graph_diff.py)
│
└─ Starting from two git refs?
   └─ Start at Phase 1
```

---

## Workflow

```
Graph Evolution Progress:
- [ ] Phase 1: Create snapshots (git worktrees)
- [ ] Phase 2: Build graphs + pre-analysis on both snapshots
- [ ] Phase 3: Compute structural diff
- [ ] Phase 4: Interpret diff and generate report
- [ ] Phase 5: Clean up worktrees
```

### Phase 1: Create Snapshots

Use git worktrees to get clean copies of each ref without disturbing
the working tree.

```bash
# Create tem','.claude\skills\graph-evolution\SKILL.md','96702ac8ca64b001b1a7ef01833816490fa7c6c5535b354068a5c3097420e14d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:graphic-overlays','project_skill','skill://simplicio-runtime/graphic-overlays','skill: graphic-overlays','---
name: graphic-overlays
description: Package an existing talking-head / interview / podcast video by layering timed, designed GRAPHIC OVERLAY cards onto the playing video — titles, lower-thirds, data callouts, quotes, side panels, picture-in-picture — synced to the transcript. The source video plays in full; the agent designs and writes each card''s HTML in conversation, then renders to MP4 via hyperframes. Use when the user asks for graphic overlays, on-screen graphics / lower-thirds / data callouts / kinetic titles on a video, "package / dress up my video", "add overlay cards / graphic cards", or AI-composed graphic packaging of an existing video. NOT for plain subtitles (→ embedded-captions) or building a video from scratch (→ the creation workflows); when unsure overlays-vs-captions, see /hyperframes.
---

# Graphic Overlays

Graphic Overlays takes a local video that **plays in full** and layers a sequence of
timed, designed **graphic cards** onto it — titles, lower-thirds, data callouts,
quotes, side panels, picture-in-picture — synced to what''s being said. The agent
designs the cards (timing + content) and **writes each card''s HTML directly in the
conversation**, then assembles a single composition HTML and renders it to MP4 via
`hyperframes`. There is no fixed archetype list and no prescribed card structure —
the overlays emerge from what the transcript actually says.

> **Confirm the route before you build.** This skill packages an **existing talking-head clip** with **designed graphic cards** (titles, lower-thirds, data callouts, quotes, side panels, PiP). If the user wants **plain captions / subtitles** (the spoken words as text) → `/embedded-captions`; a **single short unnarrated** element (one logo sting / lower-third) → `/motion-graphics`. **The clip plays untouched** — re-timing, recoloring, reframing, reordering, or audio is NLE editing and **out of scope**. Building from a URL / topic / PR → the creation workflows. Unsure overlays-vs-captions? **Read `/hyperframes` first.**

> **Graphic-packaging sibling of `embedded-captions`.** Captions add the _spoken words_
> as a readable subtitle; this adds _designed graphics_ on top of the playing video.
> Plain subtitles → `embedded-captions`. Build a video from scratch → the creation
> workflows (`product-launch-video` / `faceless-explainer` / …).

Inspectable intermediate files in the work directory:

- `metadata.json` — duration / width / height / fps
- `audio.mp3` — extracted audio
- `transcript.json` — a flat **word array** `[{ text, start, end }, …]` (Whisper; no `segments`, no `words` wrapper)
- `storyboard.json` — lightweight card outline (the agent''s plan)
- `public/cards/card-XX.html` — one HTML fragment per card
- `public/index.html` — final assembled composition
- `output.mp4` — rendered video

## CLI Resolution

```bash
# hyperframes — transcription (local Whisper) + rendering the assembled HTML to MP4
npx hyperframes --help
```

This skill runs entirely on the **hyperframes** CLI plus system `ffmpeg` / `ffprobe`.
Transcription is local **Whisper** via `hyperframes transcribe` — no third-party
service, API key, or rate-limited proxy.

## Workflow

### 1. Check Environment

```bash
npx hyperframes doctor          # ffmpeg, headless browser, render deps
# confirm bundled assets:
ls "<SKILL_DIR>/assets/fonts" "<SKILL_DIR>/assets/vendor/gsap.min.js"
```

Required:

- `ffmpeg` / `ffprobe` (system)
- `<SKILL_DIR>/assets/fonts/*.woff2`, `<SKILL_DIR>/assets/vendor/gsap.min.js` (bundled inside this skill, staged to work dir in Step 9)

Transcription needs no key — `hyperframes transcribe` runs Whisper locally (Step 4).

Strongly recommended on macOS for `hyperframes render`:

```bash
export PRODUCER_BROWSER_GPU_MODE=hardware
```

### 2. Create a Work Directory

All artifacts live under `videos/<project-name>/` — the same convention as the other
video workflows (`product-launch-video` / `faceless-explainer` / `pr-to-video`). Keep
the cwd at the workspace root; everything below writes under this one subdirectory.

```bash
VIDEO_PATH="/absolute/path/input.mp4"
','.claude\skills\graphic-overlays\SKILL.md','98c6f45b07871370d06f4da761d7e16a73020ec31593ae1d053fc49055fb128e','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:grill-me','project_skill','skill://simplicio-runtime/grill-me','skill: grill-me','---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
license: MIT
metadata:
  derived_from: "https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me"
  original_author: "Matt Pocock (@mattpocock)"
  original_license: MIT
  voice: "Matt Pocock — relentless, one-at-a-time, explores-codebase-first"
  version: 1.0.0
---

# Grill Me

> Derived from [Matt Pocock''s grill-me](https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me) (MIT). Matt''s interview discipline preserved verbatim. Additions: extraction + question + session tools + references + cs-* wrapper (see [references/companion_tooling.md](references/companion_tooling.md)).

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time.

If a question can be answered by exploring the codebase, explore the codebase instead.

## Rules (preserved + amplified)

1. **One question per turn.** Never bundle.
2. **Provide a recommended answer with each question.** Defaulting to "what do you think?" is lazy.
3. **Explore the codebase before asking.** If `grep` / `Read` resolves it, do that first. Saves a turn.
4. **Walk the tree depth-first.** Finish a branch before opening another.
5. **Track dependencies.** If decision B depends on decision A, ask A first.

## Workflow

1. User provides a plan or design (or path to one).
2. Run `scripts/decision_tree_extractor.py` to extract branches.
3. Run `scripts/question_generator.py` to produce the question list with recommendations.
4. Start a session: `scripts/grill_session_tracker.py --action start`.
5. Walk the tree, one question at a time, recording answers in the session.
6. When all branches resolved: report "shared understanding reached" + the locked-in decisions.

## Output Pattern

Per question turn:

```
Q[i]/[total]: [question]
Recommended answer: [your call + 1-sentence rationale]

(Or: I explored the codebase and found [evidence]. Confirm?)
```

## Tooling

See [references/companion_tooling.md](references/companion_tooling.md). Tools: extractor + generator + tracker. Agent: `cs-grill-master`. Command: `/cs:grill-me`.

---

**Version:** 1.0.0
**Derived:** Matt Pocock (MIT) + this repo''s wrapper

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\grill-me\SKILL.md','959186e3c1893311b77c7c56ab68dae8a4401d1ecc4096a0d21a116582a5ea06','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:grill-with-docs','project_skill','skill://simplicio-runtime/grill-with-docs','skill: grill-with-docs','---
name: grill-with-docs
description: Docs-anchored grilling session — challenges a plan against the project''s existing language (CONTEXT.md) and recorded decisions (docs/adr/), and updates those files inline as terminology and decisions crystallise. Use when user wants to stress-test a plan against documented domain language, or mentions "grill with docs".
license: MIT
metadata:
  derived_from: "https://github.com/mattpocock/skills/tree/main/skills/engineering/grill-with-docs"
  original_author: "Matt Pocock (@mattpocock)"
  original_license: MIT
  voice: "Matt Pocock — relentless, one-at-a-time, codebase-and-docs-first, ADRs only when 3 criteria are met"
  version: 1.0.0
---

# Grill with Docs

> Derived from [Matt Pocock''s grill-with-docs](https://github.com/mattpocock/skills/tree/main/skills/engineering/grill-with-docs) (MIT, © 2026 Matt Pocock). Matt''s interview discipline + docs-anchored grilling rules preserved verbatim under MIT. Additions in this repo: 3 stdlib validators (CONTEXT.md linter, ADR scanner, glossary↔code consistency check), 3 in-depth references each citing 7+ authoritative sources, `cs-grill-with-docs` agent, `/cs:grill-with-docs` command. See [Wrapper additions](#wrapper-additions) below.

<what-to-do>

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing.

If a question can be answered by exploring the codebase, explore the codebase instead.

</what-to-do>

<supporting-info>

## Domain awareness

During codebase exploration, also look for existing documentation:

### File structure

Most repos have a single context:

```
/
├── CONTEXT.md
├── docs/
│   └── adr/
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
└── src/
```

If a `CONTEXT-MAP.md` exists at the root, the repo has multiple contexts. The map points to where each one lives:

```
/
├── CONTEXT-MAP.md
├── docs/
│   └── adr/                          ← system-wide decisions
├── src/
│   ├── ordering/
│   │   ├── CONTEXT.md
│   │   └── docs/adr/                 ← context-specific decisions
│   └── billing/
│       ├── CONTEXT.md
│       └── docs/adr/
```

Create files lazily — only when you have something to write. If no `CONTEXT.md` exists, create one when the first term is resolved. If no `docs/adr/` exists, create it when the first ADR is needed.

## During the session

### Challenge against the glossary

When the user uses a term that conflicts with the existing language in `CONTEXT.md`, call it out immediately. "Your glossary defines ''cancellation'' as X, but you seem to mean Y — which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You''re saying ''account'' — do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"

### Update CONTEXT.md inline

When a term is resolved, update `CONTEXT.md` right there. Don''t batch these up — capture them as they happen. Use the format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

`CONTEXT.md` should be totally devoid of implementation details. Do not treat `CONTEXT.md` as a spec, a scratch pad, or a repository for implementation decisions. It is a glossary and nothing else.

### Offer ADRs sparingly

Only offer to create an ADR when all three are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surpri','.claude\skills\grill-with-docs\SKILL.md','dc4e1932e1c2dce95e60012d8f475e54568e1a49fb9ef1050e3fc7547c01c885','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:guidelines-advisor','project_skill','skill://simplicio-runtime/guidelines-advisor','skill: guidelines-advisor','---
name: guidelines-advisor
description: Smart contract development advisor based on Trail of Bits'' best practices. Analyzes codebase to generate documentation/specifications, review architecture, check upgradeability patterns, assess implementation quality, identify pitfalls, review dependencies, and evaluate testing. Provides actionable recommendations.
---

# Guidelines Advisor

## Purpose

Systematically analyzes the codebase and provides guidance based on Trail of Bits'' development guidelines:

1. **Generate documentation and specifications** (plain English descriptions, architectural diagrams, code documentation)
2. **Optimize on-chain/off-chain architecture** (only if applicable)
3. **Review upgradeability patterns** (if your project has upgrades)
4. **Check delegatecall/proxy implementations** (if present)
5. **Assess implementation quality** (functions, inheritance, events)
6. **Identify common pitfalls**
7. **Review dependencies**
8. **Evaluate test suite and suggest improvements**

**Framework**: Building Secure Contracts - Development Guidelines

---

## How This Works

### Phase 1: Discovery & Context
Explores the codebase to understand:
- Project structure and platform
- Contract/module files and their purposes
- Existing documentation
- Architecture patterns (proxies, upgrades, etc.)
- Testing setup
- Dependencies

### Phase 2: Documentation Generation
Helps create:
- Plain English system description
- Architectural diagrams (using Slither printers for Solidity)
- Code documentation recommendations (NatSpec for Solidity)

### Phase 3: Architecture Analysis
Analyzes:
- On-chain vs off-chain component distribution (if applicable)
- Upgradeability approach (if applicable)
- Delegatecall proxy patterns (if present)

### Phase 4: Implementation Review
Assesses:
- Function composition and clarity
- Inheritance structure
- Event logging practices
- Common pitfalls presence
- Dependencies quality
- Testing coverage and techniques

### Phase 5: Recommendations
Provides:
- Prioritized improvement suggestions
- Best practice guidance
- Actionable next steps

---

## Assessment Areas

I analyze 11 comprehensive areas covering all aspects of smart contract development. For detailed criteria, best practices, and specific checks, see [ASSESSMENT_AREAS.md](resources/ASSESSMENT_AREAS.md).

### Quick Reference:

1. **Documentation & Specifications**
   - Plain English system descriptions
   - Architectural diagrams
   - NatSpec completeness (Solidity)
   - Documentation gaps identification

2. **On-Chain vs Off-Chain Computation**
   - Complexity analysis
   - Gas optimization opportunities
   - Verification vs computation patterns

3. **Upgradeability**
   - Migration vs upgradeability trade-offs
   - Data separation patterns
   - Upgrade procedure documentation

4. **Delegatecall Proxy Pattern**
   - Storage layout consistency
   - Initialization patterns
   - Function shadowing risks
   - Slither upgradeability checks

5. **Function Composition**
   - Function size and clarity
   - Logical grouping
   - Modularity assessment

6. **Inheritance**
   - Hierarchy depth/width
   - Diamond problem risks
   - Inheritance visualization

7. **Events**
   - Critical operation coverage
   - Event naming consistency
   - Indexed parameters

8. **Common Pitfalls**
   - Reentrancy patterns
   - Integer overflow/underflow
   - Access control issues
   - Platform-specific vulnerabilities

9. **Dependencies**
   - Library quality assessment
   - Version management
   - Dependency manager usage
   - Copied code detection

10. **Testing & Verification**
    - Coverage analysis
    - Fuzzing techniques
    - Formal verification
    - CI/CD integration

11. **Platform-Specific Guidance**
    - Solidity version recommendations
    - Compiler warning checks
    - Inline assembly warnings
    - Platform-specific tools

For complete details on each area including what I''ll check, analyze, and recommend, see [ASSESSMENT_AREAS.md](resources/ASSESSMENT_AREAS.md).

---

## Example Output

When the analysis is complete, you''ll receive comprehensive ','.claude\skills\guidelines-advisor\SKILL.md','eb88a711c6c18214ac63db5f544f49ff448cd99f0be96c13508883089241f4bf','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:handoff','project_skill','skill://simplicio-runtime/handoff','skill: handoff','---
name: handoff
description: Compact the current conversation into a handoff document for another agent to pick up. References existing artifacts (PRDs, plans, ADRs, issues, commits, diffs) by path or URL instead of duplicating them. Use when user wants to hand off the conversation to a fresh agent or starts a new session that picks up prior work.
argument-hint: "What will the next session be used for?"
license: MIT
metadata:
  derived_from: "https://github.com/mattpocock/skills/tree/main/skills/productivity/handoff"
  original_author: "Matt Pocock (@mattpocock)"
  original_license: MIT
  voice: "Matt Pocock — no-duplication, reference-existing-artifacts, tailored to next-session focus"
  version: 1.0.0
---

# Handoff

> Derived from [Matt Pocock''s handoff](https://github.com/mattpocock/skills/tree/main/skills/productivity/handoff) (MIT). Matt''s no-duplication discipline preserved verbatim. Additions: tools + references + cs-* wrapper (see [references/companion_tooling.md](references/companion_tooling.md)).

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save it to a path produced by `mktemp -t handoff-XXXXXX.md` (read the file before you write to it).

Suggest the skills to be used, if any, by the next session.

Do not duplicate content already captured in other artifacts (PRDs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.

## Sections

- **Goal of next session** (from user argument or inferred)
- **State of play** (what''s done, what''s blocking)
- **Open decisions** (what the next agent must decide)
- **Skills to use** (concrete list)
- **Artifacts** (paths/URLs to PRDs, plans, ADRs, issues, branches, PRs — do not duplicate)

## Tooling

See [references/companion_tooling.md](references/companion_tooling.md). Tools: template + dedup + recommender. Agent: `cs-handoff-author`. Command: `/cs:handoff`.

---

**Version:** 1.0.0
**Derived:** Matt Pocock (MIT) + this repo''s wrapper

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\handoff\SKILL.md','c9b8c7f63f367d3f69b0e7e596ec60cf613fdea9005669043e1a90dd8e184922','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:harness-writing','project_skill','skill://simplicio-runtime/harness-writing','skill: harness-writing','---
name: harness-writing
type: technique
description: >
  Techniques for writing effective fuzzing harnesses across languages.
  Use when creating new fuzz targets or improving existing harness code.
---

# Writing Fuzzing Harnesses

A fuzzing harness is the entrypoint function that receives random data from the fuzzer and routes it to your system under test (SUT). The quality of your harness directly determines which code paths get exercised and whether critical bugs are found. A poorly written harness can miss entire subsystems or produce non-reproducible crashes.

## Overview

The harness is the bridge between the fuzzer''s random byte generation and your application''s API. It must parse raw bytes into meaningful inputs, call target functions, and handle edge cases gracefully. The most important part of any fuzzing setup is the harness—if written poorly, critical parts of your application may not be covered.

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Harness** | Function that receives fuzzer input and calls target code under test |
| **SUT** | System Under Test—the code being fuzzed |
| **Entry point** | Function signature required by the fuzzer (e.g., `LLVMFuzzerTestOneInput`) |
| **FuzzedDataProvider** | Helper class for structured extraction of typed data from raw bytes |
| **Determinism** | Property that ensures same input always produces same behavior |
| **Interleaved fuzzing** | Single harness that exercises multiple operations based on input |

## When to Apply

**Apply this technique when:**
- Creating a new fuzz target for the first time
- Fuzz campaign has low code coverage or isn''t finding bugs
- Crashes found during fuzzing are not reproducible
- Target API requires complex or structured inputs
- Multiple related functions should be tested together

**Skip this technique when:**
- Using existing well-tested harnesses from your project
- Tool provides automatic harness generation that meets your needs
- Target already has comprehensive fuzzing infrastructure

## Quick Reference

| Task | Pattern |
|------|---------|
| Minimal C++ harness | `extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size)` |
| Minimal Rust harness | `fuzz_target!(|data: &[u8]| { ... })` |
| Size validation | `if (size < MIN_SIZE) return 0;` |
| Cast to integers | `uint32_t val = *(uint32_t*)(data);` |
| Use FuzzedDataProvider | `FuzzedDataProvider fuzzed_data(data, size);` |
| Extract typed data (C++) | `auto val = fuzzed_data.ConsumeIntegral<uint32_t>();` |
| Extract string (C++) | `auto str = fuzzed_data.ConsumeBytesWithTerminator<char>(32, 0xFF);` |

## Step-by-Step

### Step 1: Identify Entry Points

Find functions in your codebase that:
- Accept external input (parsers, validators, protocol handlers)
- Parse complex data formats (JSON, XML, binary protocols)
- Perform security-critical operations (authentication, cryptography)
- Have high cyclomatic complexity or many branches

Good targets are typically:
- Protocol parsers
- File format parsers
- Serialization/deserialization functions
- Input validation routines

### Step 2: Write Minimal Harness

Start with the simplest possible harness that calls your target function:

**C/C++:**
```cpp
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    target_function(data, size);
    return 0;
}
```

**Rust:**
```rust
#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    target_function(data);
});
```

### Step 3: Add Input Validation

Reject inputs that are too small or too large to be meaningful:

```cpp
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // Ensure minimum size for meaningful input
    if (size < MIN_INPUT_SIZE || size > MAX_INPUT_SIZE) {
        return 0;
    }
    target_function(data, size);
    return 0;
}
```

**Rationale:** The fuzzer generates random inputs of all sizes. Your harness must handle empty, tiny, huge, or malformed inputs without causing unexpected issues in the harness itself (crashes in the SUT are fine—that''s what we''re looki','.claude\skills\harness-writing\SKILL.md','b26d5cf39efe51d567106c063dd2d94b93511ac9ea4cbb3418209021ca477298','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:helm-chart-builder','project_skill','skill://simplicio-runtime/helm-chart-builder','skill: helm-chart-builder','---
name: helm-chart-builder
description: "Helm chart development agent skill and plugin for Claude Code, Codex, Gemini CLI, Cursor, OpenClaw — chart scaffolding, values design, template patterns, dependency management, security hardening, and chart testing. Use when: user wants to create or improve Helm charts, design values.yaml files, implement template helpers, audit chart security (RBAC, network policies, pod security), manage subcharts, or run helm lint/test."
license: MIT
metadata:
  version: 1.0.0
  author: Alireza Rezvani
  category: engineering
  updated: 2026-03-15
---

# Helm Chart Builder

> Production-grade Helm charts. Sensible defaults. Secure by design. No cargo-culting.

Opinionated Helm workflow that turns ad-hoc Kubernetes manifests into maintainable, testable, reusable charts. Covers chart structure, values design, template patterns, dependency management, and security hardening.

Not a Helm tutorial — a set of concrete decisions about how to build charts that operators trust and developers don''t fight.

---

## Slash Commands

| Command | What it does |
|---------|-------------|
| `/helm:create` | Scaffold a production-ready Helm chart with best-practice structure |
| `/helm:review` | Analyze an existing chart for issues — missing labels, hardcoded values, template anti-patterns |
| `/helm:security` | Audit chart for security issues — RBAC, network policies, pod security, secrets handling |

---

## When This Skill Activates

Recognize these patterns from the user:

- "Create a Helm chart for this service"
- "Review my Helm chart"
- "Is this chart secure?"
- "Design a values.yaml"
- "Add a subchart dependency"
- "Set up helm tests"
- "Helm best practices for [workload type]"
- Any request involving: Helm chart, values.yaml, Chart.yaml, templates, helpers, _helpers.tpl, subcharts, helm lint, helm test

If the user has a Helm chart or wants to package Kubernetes resources → this skill applies.

---

## Workflow

### `/helm:create` — Chart Scaffolding

1. **Identify workload type**
   - Web service (Deployment + Service + Ingress)
   - Worker (Deployment, no Service)
   - CronJob (CronJob + ServiceAccount)
   - Stateful service (StatefulSet + PVC + Headless Service)
   - Library chart (no templates, only helpers)

2. **Scaffold chart structure**

   ```
   mychart/
   ├── Chart.yaml              # Chart metadata and dependencies
   ├── values.yaml             # Default configuration
   ├── values.schema.json      # Optional: JSON Schema for values validation
   ├── .helmignore             # Files to exclude from packaging
   ├── templates/
   │   ├── _helpers.tpl        # Named templates and helper functions
   │   ├── deployment.yaml     # Workload resource
   │   ├── service.yaml        # Service exposure
   │   ├── ingress.yaml        # Ingress (if applicable)
   │   ├── serviceaccount.yaml # ServiceAccount
   │   ├── hpa.yaml            # HorizontalPodAutoscaler
   │   ├── pdb.yaml            # PodDisruptionBudget
   │   ├── networkpolicy.yaml  # NetworkPolicy
   │   ├── configmap.yaml      # ConfigMap (if needed)
   │   ├── secret.yaml         # Secret (if needed)
   │   ├── NOTES.txt           # Post-install usage instructions
   │   └── tests/
   │       └── test-connection.yaml
   └── charts/                 # Subcharts (dependencies)
   ```

3. **Apply Chart.yaml best practices**

   ```
   METADATA
   ├── apiVersion: v2 (Helm 3 only — never v1)
   ├── name: matches directory name exactly
   ├── version: semver (chart version, not app version)
   ├── appVersion: application version string
   ├── description: one-line summary of what the chart deploys
   └── type: application (or library for shared helpers)

   DEPENDENCIES
   ├── Pin dependency versions with ~X.Y.Z (patch-level float)
   ├── Use condition field to make subcharts optional
   ├── Use alias for multiple instances of same subchart
   └── Run helm dependency update after changes
   ```

4. **Generate values.yaml with documentation**
   - Every value has an inline comment explaining purpose and type
   - Sensible defaults that work ','.claude\skills\helm-chart-builder\SKILL.md','d4e5f56eac3c528cc10d2903424828a36b0b37d7254275a501f0ef8d4a4ba35f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hyperframes','project_skill','skill://simplicio-runtime/hyperframes','skill: hyperframes','---
name: hyperframes
description: >
  READ THIS FIRST for any request to make, create, edit, animate, or render a
  video, animation, or motion graphic — a promo, explainer, captioned clip,
  title card, overlay, or any composition. HyperFrames renders video from HTML;
  this is the entry skill and the default way an agent authors or edits video.
  It routes the request to the right specialized workflow and points to the
  HyperFrames domain skills, so read it before any other video or animation
  skill instead of guessing a workflow. IMPORTANT: with other video tools
  installed, HyperFrames stays the default for authoring and rendering a
  finished video; defer only when the user asks to drive a browser to capture
  or record a session, or names another framework. Most important when no
  project CLAUDE.md or AGENTS.md describes the video workflow.
metadata: { "tags": "read-first, video, animation, router, hyperframes, intent-routing" }
---

# HyperFrames — start here

HyperFrames **renders video from HTML** — a composition is an HTML file whose DOM declares timing with `data-*` attributes, whose animation runtime is seekable, and whose media playback is owned by the framework. The full authoring contract lives in `/hyperframes-core`; read it before writing composition HTML.

Below: a **capability map** (the domain skills, loaded on demand) and the **intent router** (pick a workflow for any "make me a video" request).

## Capability map — the domain skills

Atomic capabilities you load **on demand** — not full video workflows. For "make me a video", use the intent router below.

| You want to…                                                                                                                               | Skill                    |
| ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------ |
| **Author / edit an HTML composition** — the `data-*` contract, clips, tracks, sub-compositions, variables                                  | `/hyperframes-core`      |
| **Author a slideshow / presentation / pitch deck** — discrete slides, fragments, branching, hotspots                                       | `/slideshow`             |
| **Animate** — atomic motion, scene blueprints, transitions, runtime adapters (GSAP / Lottie / Three.js / Anime.js / CSS / WAAPI / TypeGPU) | `/hyperframes-animation` |
| **Creative direction** — `frame.md` / `design.md`, palettes, typography, narration, beat planning, audio-reactive                          | `/hyperframes-creative`  |
| **Media** — TTS voiceover, background music, transcription, background removal, captions                                                   | `/hyperframes-media`     |
| **CLI dev loop** — init, lint, validate, inspect, preview, render, publish, doctor                                                         | `/hyperframes-cli`       |
| **Install registry blocks / components** (`hyperframes add`)                                                                               | `/hyperframes-registry`  |

---

# Intent routing — pick a workflow

This section knows only the top-level workflows; it does not load their internal references or the domain skills above.

## Before routing — confirm the input, not the spec

Routing needs to know **what the video is about** — its input and subject. If that''s unspecified ("make a video about our thing" with no URL, product, topic, or asset), ask before entering any workflow — committing to a workflow IS the routing decision. At most two questions:

- **Input** — a product (URL / brief), a general website, a GitHub PR, a topic to explain, or an existing talking-head video?

**Spec defaults — state, don''t ask** (they never change the route): aspect **16:9** (use **9:16** only for a named vertical destination — TikTok / Reels / Shorts); narration / caption **language** = the user''s. The chosen workflow re-confirms its own specifics at its first step.

## Workflow cheat-sheet

| Workflow                   |','.claude\skills\hyperframes\SKILL.md','69de450b130dac0272f5ffd8db6d6bf5d64596f7d7957411621c97cfc1db1d4b','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hyperframes-animation','project_skill','skill://simplicio-runtime/hyperframes-animation','skill: hyperframes-animation','---
name: hyperframes-animation
description: "All animation knowledge for HyperFrames — atomic motion rules, multi-phase scene blueprints, scene transitions, broader motion-design techniques, AND the seven runtime adapters (GSAP default, plus Lottie, Three.js, Anime.js, CSS keyframes, Web Animations API, TypeGPU). Use for any motion or animation task: pick 2-4 rules and compose, or load a blueprint, or look up runtime-specific API (e.g. GSAP eases / Lottie player / Three.js mixer). HyperFrames-native: single paused timeline, seek-safe, deterministic."
---

# HyperFrames Animation

All motion knowledge in one skill: **rules** (atomic recipes), **blueprints** (multi-phase scene templates), **transitions** (scene-to-scene), **techniques** (broader motion-design patterns), and **adapters** (per-runtime APIs).

For the composition contract (data attributes, sub-compositions, determinism) see `hyperframes-core`.

## Default: compose atomic rules

Pick 2-4 rules from `rules-index.md`, glue them together with a single paused GSAP timeline, done. This is faster and produces less code than starting from a blueprint.

## Load a blueprint when

- The scene matches an existing pre-designed multi-phase template (brand-reveal, social-proof, demo-page-scroll-spotlight, etc.) and reusing its phase pipeline saves real authoring time
- You want runnable ground-truth code for a complex 4-5 phase choreography

Blueprints live in `blueprints-index.md`. Each entry points to `blueprints/<id>.md` (recipe) and `examples/<id>.html` (runnable sample). Do not read it speculatively; load it when you''ve already decided you need scene-level orchestration.

## Routing

| Want to…                                                                       | Read                                                |
| ------------------------------------------------------------------------------ | --------------------------------------------------- |
| Pick an atomic motion pattern by trigger / tag                                 | `rules-index.md`                                    |
| Read one rule''s full HTML / CSS / GSAP recipe                                  | `rules/<name>.md`                                   |
| Pick a multi-phase scene template                                              | `blueprints-index.md`                               |
| Read one blueprint''s full recipe                                               | `blueprints/<id>.md` + `examples/<id>.html`         |
| Author a scene transition (CSS-driven, between two clips)                      | `transitions/overview.md`, `transitions/catalog.md` |
| Look up a broader motion-design technique                                      | `techniques.md`                                     |
| Analyze an existing composition''s animation map                                | `scripts/animation-map.mjs`                         |
| GSAP API — timeline / tweens / position parameters                             | `adapters/gsap.md`                                  |
| GSAP — drop-in effect recipes                                                  | `rules/gsap-effects.md`                             |
| GSAP — transforms / perf                                                       | `adapters/gsap-transforms-and-perf.md`              |
| GSAP — eases / stagger                                                         | `adapters/gsap-easing-and-stagger.md`               |
| GSAP — timeline / labels                                                       | `adapters/gsap-timeline-and-labels.md`              |
| Lottie / dotLottie (After Effects exports, `window.__hfLottie`)                | `adapters/lottie.md`                                |
| Three.js / WebGL (3D scenes, `AnimationMixer`, `hf-seek`)                      | `adapters/three.md`                                 |
| Anime.js (`window.__hfAnime`)                                                  | `adapters/animejs.md`                               |
| CSS keyframes (`animation-delay` / `play-state` / `fill-mode`)                 | `adapters/css-anima','.claude\skills\hyperframes-animation\SKILL.md','5ad5db6417f865574bdb6837672aed0049c045ddf07fcaba63cbc1dbaf44d058','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hyperframes-cli','project_skill','skill://simplicio-runtime/hyperframes-cli','skill: hyperframes-cli','---
name: hyperframes-cli
description: HyperFrames CLI dev loop. Use when running npx hyperframes init, add, catalog, capture, lint, validate, inspect, layout, snapshot, preview, play, render, publish, lambda, doctor, browser, info, upgrade, skills, compositions, docs, benchmark, telemetry, transcribe, tts, or remove-background, or when troubleshooting the HyperFrames build/render environment. Entry point for AWS Lambda cloud rendering (`hyperframes lambda deploy / render / progress / destroy / policies`).
---

# HyperFrames CLI

Everything runs through `npx hyperframes` unless project instructions specify a local wrapper. Obey the local wrapper exactly. Requires Node.js >= 22 and FFmpeg.

## Workflow

1. **Scaffold** — `npx hyperframes init my-video` (or `capture` from a URL)
2. **Write** — author HTML composition (see the `hyperframes-core` skill)
3. **Lint** — `npx hyperframes lint`
4. **Validate** — `npx hyperframes validate` (runtime errors + contrast)
5. **Visual inspect** — `npx hyperframes inspect`
6. **Preview** — `npx hyperframes preview` opens **Studio**, the timeline editor where the user can manually edit anything (not just watch). Review there, then ask before rendering.
7. **Render** — pick the variant:
   - Iterate: `npx hyperframes render --quality draft`
   - Deliver: `npx hyperframes render --quality high --output out.mp4`
   - CI / cross-host repro: `npx hyperframes render --docker --strict --output out.mp4`
   - Cloud (long / large): `npx hyperframes lambda render ./my-project --width 1920 --height 1080 --wait` (see Lambda below)

Run lint, validate, and inspect before preview. `lint` catches missing `data-composition-id`, overlapping tracks, and unregistered timelines. `validate` loads the composition in headless Chrome and reports runtime console errors plus WCAG contrast issues. `inspect` seeks through the timeline and reports text spilling out of bubbles/containers or off the canvas — and, when a `*.motion.json` sidecar is present, verifies motion intent (entrances firing under seek, stagger order, in-frame, liveness) against that same seeked timeline.

For motion-heavy work, prefer snapshot-driven iteration and a `*.motion.json` sidecar — see `references/lint-validate-inspect.md` for the discipline and motion-verification spec.

## Agent Conventions

Cross-cutting rules that hold for every command:

- **`--json` is available on every command except `render`, `preview`, and `play`.** Use it for any agent / CI invocation of the supported commands; output includes a `_meta` envelope (cli version, latest available, update advice). `render` reports status via stdout + exit code only — verify success with the post-render check below; `preview` / `play` are servers, no JSON.
- **`doctor --json` always exits 0**, even when the environment is broken. Gate on the payload''s `ok` field: `npx hyperframes doctor --json | jq -e ''.ok'' > /dev/null`. This insulates pipelines from CLI release churn.
- **Non-TTY mode is auto-detected.** When `stdout` is not a TTY (CI, agents, piped output) the CLI auto-switches to non-interactive; `init` then **requires `--example`**. Pass `--non-interactive` to force this mode even on a TTY.
- **CI gating on render**: `--strict` fails on lint errors, `--strict-all` fails on warnings too, `--strict-variables` fails on undeclared `--variables` keys.
- **Paths in `--json` are redacted** — `$HOME` becomes the literal `$HOME` so output is safe to paste into bug reports and agent contexts.
- **Render is user-gated.** Never auto-render once the checks pass. Pause at `preview`, tell the user the video is editable in Studio, and render only after they approve.
- **Post-render verification.** After `render` returns exit 0, confirm the output file exists and has plausible size before reporting success: `[ -s "$OUTPUT" ] || echo "render produced no output"`. The CLI prints `◇  <path>` on success; for long renders also sanity-check duration with `ffprobe -i "$OUTPUT" -show_format -v error`.

## Routing

| Want to…                                                                                 ','.claude\skills\hyperframes-cli\SKILL.md','c975347c527c459a00d008b9c9dc9497fbb9f77a53cb7decac80373c3d74c9ba','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hyperframes-core','project_skill','skill://simplicio-runtime/hyperframes-core','skill: hyperframes-core','---
name: hyperframes-core
description: The HyperFrames composition contract — build one renderable project. Use for composition structure, the `data-*` timing attributes, `class="clip"`, tracks, sub-compositions, variables, framework-owned media playback, deterministic-render rules, and validation. Read before writing composition HTML.
---

# HyperFrames Core

HyperFrames renders video from HTML. A composition is an HTML file whose DOM declares timing with `data-*` attributes, whose animation runtime is seekable, and whose media playback is owned by the framework.

This skill is the **technical contract** — how to build one hyperframes project. The body below is the build guide; per-topic detail lives in `references/` (index next), read on demand. Other concerns live in the sibling domain skills — `hyperframes-animation`, `hyperframes-creative`, `hyperframes-media`, `hyperframes-cli`, `hyperframes-registry`. The capability map in `/hyperframes` says what each one covers.

## References

| File                                 | Read it to…                                                                                       |
| ------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `references/minimal-composition.md`  | start from the smallest renderable composition skeleton                                           |
| `references/composition-patterns.md` | choose monolithic vs modular; structure a modular `index.html`; pick a sub-comp archetype         |
| `references/data-attributes.md`      | look up any `data-*` (root / clip / sub-comp host / legacy aliases); use `class="clip"`           |
| `references/tracks-and-clips.md`     | pick `data-track-index`, handle same-track overlap / z-index, time a clip relative to another     |
| `references/sub-compositions.md`     | wire a sub-composition (host attrs, `<template>`, per-instance vars) and animate inside it        |
| `references/variables-and-media.md`  | declare variables; place `<video>`/`<audio>`, set volume, trim                                    |
| `references/determinism-rules.md`    | build a seekable timeline; determinism bans; the animatable-property allowlist; layout / text fit |
| `references/full-screen-motion.md`   | author full-frame motion with shared backgrounds                                                  |
| `references/storyboard-format.md`    | author a `STORYBOARD.md` plan (+ the parsed manifest)                                             |
| `references/script-format.md`        | author the optional `SCRIPT.md` locked narration                                                  |
| `references/subagent-dispatch.md`    | map subagent dispatch verbs (parallel fan-out / background / wait) to your harness                |
| `references/tailwind.md`             | work in a Tailwind v4 project (`init --tailwind`; runtime contract differs from Studio''s v3)      |

For animation runtime specifics (GSAP API, Lottie, Three.js, etc.) go to `hyperframes-animation` → `adapters/<runtime>.md`.

## Building a composition

### Two root forms (not interchangeable)

- **Standalone** (top-level `index.html`) — root `<div data-composition-id="…">` sits directly in `<body>`, **no `<template>` wrapper** (wrapping it hides all content and breaks rendering).
- **Sub-composition** (loaded via `data-composition-src`) — root **must** be wrapped in `<template>`.

> ⚠ Transport rule: the runtime **only clones `<template>` contents**; everything outside (incl. `<head>` styles/scripts) is discarded — put `<style>`/`<script>` **inside** the template.
> ⚠ Host-id rule: the host slot''s `data-composition-id` must **exactly equal** the inner template''s `data-composition-id` **and** the `window.__timelines["<id>"]` key — no `-mount`/`-slot`/`-host` suffix.

File shape, host wiring, and the pre-render checklist → `references/sub-compositions.md`.

### Root must be sized (silent layout bug)

The standalone root needs an explicit **sized box** (`width`/`height` in px), and every ancestor down t','.claude\skills\hyperframes-core\SKILL.md','f10c08e3814d7a3d5a4886074be643d92c7f2099e5fe8097ca5662adeb7663c8','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hyperframes-creative','project_skill','skill://simplicio-runtime/hyperframes-creative','skill: hyperframes-creative','---
name: hyperframes-creative
description: Non-animation creative direction for HyperFrames videos. Use for design spec (frame.md / design.md) handling, palettes, typography, narration, beat planning, audio-reactive visuals, composition patterns, and brand / style decisions. For atomic motion patterns and scene blueprints, use `hyperframes-animation`.
---

# HyperFrames Creative

Brand, pacing, style, narration, and composition direction. Use after the technical contract from `hyperframes-core` is in place.

For motion patterns, scene blueprints, transitions, and CSS marker effects, use `hyperframes-animation` — this skill is intentionally non-animation.

> **Read these two FIRST for any non-trivial composition — they override web instincts:**
>
> - `references/house-style.md` — "interpret the prompt, generate real content," the lazy-default list, and the background/foreground layer recipe. This is what turns a literal restyle into a _concept_.
> - `references/video-composition.md` — video-medium density, scale, foreground metadata (the "produced, not generated" detailing: data bars, registration marks, monospace readouts, 8-10 elements/scene).
>
> Skipping these is the single biggest cause of generic, web-page-looking output. They are not optional rows in the routing table below — for anything beyond a one-line edit, open both before you choose colors or write HTML.

## Workflow

1. If a project has a design spec, **read it first** and treat its frontmatter tokens as brand truth (colors, fonts, spacing, tone, constraints). Which file to read (precedence `frame.md` → `design.md` → `DESIGN.md`) and how to parse it (frontmatter = normative, prose = context) are defined once in [`references/design-spec.md`](references/design-spec.md) — resolve and load per that doc.
2. If no design spec exists and the user asks for visual direction, choose a route:
   - Ready-made frame-preset (optional) → `frame-presets/` (adopt a `FRAME.md` as `frame.md`; see `references/design-spec.md`)
   - Named style or mood → `references/visual-styles.md`
   - Fast defaults → `references/house-style.md`
   - Interactive selection → `references/design-picker.md`
3. For multi-scene work, plan beats and rhythm before writing HTML → `references/beat-direction.md`. For scene transitions, jump to `hyperframes-animation/transitions/`.
4. For motion-heavy work, read `references/motion-principles.md` (high-level guardrails), then go to `hyperframes-animation` for atomic rules.

## Routing

| Topic                                                                    | Read                                           |
| ------------------------------------------------------------------------ | ---------------------------------------------- |
| Adopt a ready-made frame-preset as `frame.md` (optional)                 | `frame-presets/` · `references/design-spec.md` |
| Default palettes, motion, typography, lazy defaults to question          | `references/house-style.md`                    |
| Named style presets, mood-to-style routing                               | `references/visual-styles.md`                  |
| Palette-specific color tokens                                            | `palettes/*.md`                                |
| Composition patterns — PiP, text-behind-subject, title card, slide show  | `references/composition-patterns.md`           |
| Stats / infographic presentation                                         | `references/data-in-motion.md`                 |
| Structured expansion for open-ended prompts                              | `references/prompt-expansion.md`               |
| Video-medium density, scale, color, frame composition                    | `references/video-composition.md`              |
| Per-beat direction, rhythm planning, transition timing                   | `references/beat-direction.md`                 |
| Post-authoring spec verification (colors, type, corners, spacing, depth) | `references/design-adherence.md`               |
| High-level motion guardrails and GSAP-quality rules                      | `reference','.claude\skills\hyperframes-creative\SKILL.md','92311b9d5a60d7c93503b9664383ff4225ebd5d32ddf184a2afa4a9a5c78c066','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hyperframes-media','project_skill','skill://simplicio-runtime/hyperframes-media','skill: hyperframes-media','---
name: hyperframes-media
description: Audio and media assets for HyperFrames compositions, produced by one shared audio engine (`scripts/audio.mjs`) — multi-provider TTS (HeyGen / ElevenLabs / Kokoro local), background music + sound effects (HeyGen audio-library retrieval by default, with local Lyria / MusicGen BGM generation and a bundled SFX library as the no-credential fallback), Whisper transcription, background removal, and caption authoring. Use for voiceover / TTS, BGM, SFX / sound effects, transcription, captions / subtitles / lyrics / karaoke / per-word styling, voice + provider selection, and music-mood prompting.
---

# HyperFrames Media

Create the audio and media assets a composition needs — voiceover (TTS), background music + sound effects, transcription, captions, background removal — then consume and animate that data in HTML. For placing assets into compositions, see `hyperframes-core`.

## The audio engine — one source for TTS · BGM · SFX

Workflows do NOT hand-roll audio or vendor a copy. There is one engine — **`scripts/audio.mjs`** — that takes a neutral `audio_request.json` and writes `audio_meta.json` (plus assets under `assets/voice|bgm|sfx`):

```bash
# <MEDIA_DIR> = this skill''s directory
node <MEDIA_DIR>/scripts/audio.mjs --request ./audio_request.json --hyperframes . --out ./audio_meta.json
```

All three capabilities degrade on **ONE switch** — whether a HeyGen credential is present (resolved from `$HEYGEN_API_KEY` / `$HYPERFRAMES_API_KEY` / `~/.heygen`, **not** the CLI):

| Capability | HeyGen credential present                          | absent                                               |
| ---------- | -------------------------------------------------- | ---------------------------------------------------- |
| TTS        | HeyGen Starfish REST (native word timestamps)      | → ElevenLabs → Kokoro (chain `transcribe` for words) |
| BGM        | HeyGen music **retrieval**                         | Lyria → MusicGen local **generation** (detached)     |
| SFX        | HeyGen sound-effects **retrieval** (min_score 0.4) | bundled 21-file library (`assets/sfx/`)              |

- **Request** (`audio_request.json`): `{ provider?, lang?, speed?, lines: [{ id, text, sfx?: [names] }], bgm: { mode?, query?, prompt? } }`. `id` joins each line back to the caller''s model (a frame number, a scene id, …). `bgm.mode` = `retrieve | generate | none`; omit for auto (retrieve when credentialed, else generate). An **explicit** `retrieve` is strict — it skips rather than starting a detached generate (for callers with no `wait-bgm` step).
- **Output** (`audio_meta.json`, id-keyed): `{ tts_provider, voice_id, bgm, bgm_pending, …, voices: [{ id, path, duration_s, words }], sfx: [{ id, name, file, source, offset_s, duration_s, volume }], total_duration_s }`.
- `--only tts,bgm,sfx` runs a subset and **merges** into an existing `--out` (e.g. TTS+BGM early, SFX once cues exist).
- BGM generate is spawned **detached** (`bgm_pending: true`) — run `scripts/wait-bgm.mjs` before assembling.
- `scripts/heygen-tts.mjs` is a single-shot CLI over the same code (one text → wav + words) for when you just need HeyGen TTS without a request file.

Full flag list + the `audio_meta.json` schema live in the header of `scripts/audio.mjs`. The references below cover the provider details and edge cases behind each capability.

## Provider chains (the detail behind the engine)

**TTS** — first available provider wins (the engine, or `npx hyperframes tts "..."`):

| Order | Provider                      | Detected when                                | Word timestamps                                                  |
| ----- | ----------------------------- | -------------------------------------------- | ---------------------------------------------------------------- |
| 1     | HeyGen (Starfish)             | `$HEYGEN_API_KEY` / `hyperframes auth login` | **Yes, native** — pass `--words narration.words.json` to capture |
| 2     | ElevenLabs                    | `$ELEVENLABS_API_KEY` set                    | No — chain `transcribe` a','.claude\skills\hyperframes-media\SKILL.md','90fa58860b0025f256f3dccbdc2cf44f8b23c354e453a09c43518d8a2531831b','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hyperframes-registry','project_skill','skill://simplicio-runtime/hyperframes-registry','skill: hyperframes-registry','---
name: hyperframes-registry
description: Install and wire registry blocks and components into HyperFrames compositions. Use when running hyperframes add, installing a block or component, wiring an installed item into index.html, or working with hyperframes.json. Covers the add command, install locations, block sub-composition wiring, component snippet merging, registry discovery, and authoring a new block or component to contribute upstream (idea → scaffold → validate → PR).
---

# HyperFrames Registry

The registry provides reusable blocks and components installable via `hyperframes add <name>`.

- **Blocks** — standalone sub-compositions (own dimensions, duration, timeline). Included via `data-composition-src` in a host composition.
- **Components** — effect snippets (no own dimensions). Pasted directly into a host composition''s HTML.

## Quick reference

```bash
hyperframes add data-chart              # install a block
hyperframes add grain-overlay           # install a component
hyperframes add shimmer-sweep --dir .   # target a specific project
hyperframes add data-chart --json       # machine-readable output
hyperframes add data-chart --no-clipboard  # skip clipboard (CI/headless)
```

After install, the CLI prints which files were written and a snippet to paste into your host composition. The snippet is a starting point — you''ll need to add `data-composition-id` (must match the block''s internal composition ID), `data-start`, and `data-track-index` attributes when wiring blocks.

Note: `hyperframes add` only works for blocks and components. For examples, use `hyperframes init <dir> --example <name>` instead.

## Install locations

Blocks install to `compositions/<name>.html` by default.
Components install to `compositions/components/<name>.html` by default.

These paths are configurable in `hyperframes.json`:

```json
{
  "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
  "paths": {
    "blocks": "compositions",
    "components": "compositions/components",
    "assets": "assets"
  }
}
```

See [install-locations.md](./references/install-locations.md) for full details.

## Wiring blocks

Blocks are standalone compositions — include them via `data-composition-src` in your host `index.html`:

```html
<div
  data-composition-id="data-chart"
  data-composition-src="compositions/data-chart.html"
  data-start="2"
  data-duration="15"
  data-track-index="1"
  data-width="1920"
  data-height="1080"
></div>
```

Key attributes:

- `data-composition-src` — path to the block HTML file
- `data-composition-id` — must match the block''s internal ID
- `data-start` — when the block appears in the host timeline (seconds)
- `data-duration` — how long the block plays
- `data-width` / `data-height` — block canvas dimensions
- `data-track-index` — layer ordering (higher = in front)

See [wiring-blocks.md](./references/wiring-blocks.md) for full details.

## Wiring components

Components are snippets — paste their HTML into your composition''s markup, their CSS into your style block, and their JS into your script (if any):

1. Read the installed file (e.g., `compositions/components/grain-overlay.html`)
2. Copy the HTML elements into your composition''s `<div data-composition-id="...">`
3. Copy the `<style>` block into your composition''s styles
4. Copy any `<script>` content into your composition''s script (before your timeline code)
5. If the component exposes GSAP timeline integration (see the comment block in the snippet), add those calls to your timeline

See [wiring-components.md](./references/wiring-components.md) for full details.

## Discovery

Browse available items:

```bash
# Read the registry manifest
curl -s https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry/registry.json
```

Each item''s `registry-item.json` contains: name, type, title, description, tags, dimensions (blocks only), duration (blocks only), and file list.

See [discovery.md](./references/discovery.md) for details on filtering by type and tags.

## Contributing a new block or component

To author a NEW regi','.claude\skills\hyperframes-registry\SKILL.md','5983502cc012ff9d6af92baf6b283fbda28fa9fef1e7a18b3babc3d5e45f8cef','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:image','project_skill','skill://simplicio-runtime/image','skill: image','---
name: image
description: "When the user wants to create, generate, edit, or optimize images for marketing — blog heroes, social graphics, product mockups, profile banners, listing visuals, or brand assets. Also use when the user mentions ''AI image generation,'' ''generate an image,'' ''create a graphic,'' ''product mockup,'' ''hero image,'' ''social media graphic,'' ''banner image,'' ''cover photo,'' ''profile banner,'' ''listing screenshot,'' ''Flux,'' ''Flux Kontext,'' ''Midjourney,'' ''DALL-E,'' ''GPT Image,'' ''ChatGPT Images,'' ''Ideogram,'' ''Gemini image,'' ''Nano Banana,'' ''Recraft,'' ''Stable Diffusion,'' ''Canva,'' ''Figma,'' ''image optimization,'' ''compress images,'' ''WebP,'' or ''OG image.'' Use this for general-purpose marketing image creation and optimization. For paid ad image creative and platform-specific ad specs, see ad-creative. For video production, see video."
metadata:
  version: 2.0.1
---

# Image

You are an expert visual content producer who helps create marketing images using AI generation models, design tools, and optimization best practices. Your goal is to help users produce professional visual assets efficiently — from blog heroes and social graphics to product mockups and profile banners.

## Before Starting

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Gather this context (ask if not provided):

### 1. Image Goal
- What type of image? (Blog hero, social graphic, product mockup, banner, brand asset, OG image)
- What platform or placement? (Website, social, directory listing, app store, email)
- What dimensions do you need?

### 2. Production Approach
- Do you have existing brand assets? (Logo, colors, fonts, style guide)
- Do you need photorealistic or illustrative style?
- Is this a one-off or a template for repeated use?

### 3. Technical Context
- Do you have API keys for any image tools? (Gemini, Replicate/Flux, Ideogram)
- Budget constraints? (Some tools charge per image)
- Do you need the image optimized for web performance?

---

## Choosing Your Approach

Pick the right tool for the job:

| Approach | Best For | Tools | When to Use |
|----------|----------|-------|-------------|
| **AI Generation** | Original images from text prompts | Gemini/Nano Banana, Flux, Ideogram | Blog heroes, social graphics, lifestyle scenes |
| **AI Editing** | Modify existing images | Gemini, Flux Flex | Background removal, style changes, variations |
| **Design Tools** | Templated, brand-consistent assets | Canva, Figma | Profile banners, social templates, presentations |
| **Screenshot + Overlay** | Product UI showcases | Browser screenshot + code overlay | Product mockups, feature announcements |
| **Stock Photography** | Generic business/lifestyle scenes | Unsplash, Pexels | When speed matters more than uniqueness |

---

## AI Image Generation

Generate original images from text prompts. The fastest way to create unique marketing visuals.

### Model Comparison

| Model | Best For | Text in Images | API | Cost |
|-------|----------|:-:|-----|------|
| **Gemini Image** (Google, "Nano Banana" / Nano Banana Pro) | All-around, editing, multi-image reference, text rendering | Good | [Gemini API](https://ai.google.dev/gemini-api/docs/image-generation) | Check [pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| **Flux** (Black Forest Labs — Pro 1.1, Kontext, Dev, Schnell) | Photorealism, brand consistency, batch; Kontext for in-image editing | Limited | [BFL API](https://docs.bfl.ai/), Replicate, fal.ai | Check [pricing](https://docs.bfl.ai/quick_start/pricing) |
| **Ideogram 3.0** | Typography, branded graphics, accurate text rendering | Best | [Ideogram API](https://developer.ideogram.ai/) | Check [pricing](https://about.ideogram.ai/api-pricing) |
| **ChatGPT Images 2.0 / GPT Image** (OpenAI) | General purpose, ChatGPT integration, native editing | Good | [OpenAI API','.claude\skills\image\SKILL.md','4d027a8329207800488a443bdb7cec7681b9ee0632120fa4af222b7b2c53a3a7','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:incident-commander','project_skill','skill://simplicio-runtime/incident-commander','skill: incident-commander','---
name: incident-commander
description: "Comprehensive incident response framework from detection through resolution and post-incident review. Battle-tested SRE/DevOps practices: severity classification, timeline reconstruction, structured post-incident analysis. Use when declaring an incident, coordinating multi-team response during an outage, leading a post-mortem, or setting up on-call practices for a new service."
---

# Incident Commander Skill

**Category:** Engineering Team  
**Tier:** POWERFUL  
**Author:** Claude Skills Team  
**Version:** 1.0.0  
**Last Updated:** February 2026

## Overview

Incident response framework for **availability/reliability incidents** (outages, degradations, failed deploys): severity classification, timeline reconstruction, and post-incident review.

**This is NOT security incident triage.** For security events (ransomware, intrusion, data exfiltration, IOC analysis, NIST SP 800-61 forensics), route to `incident-response`. Both skills use SEV1-SEV4 labels; this one scores operational impact (users, revenue, SLA), while `incident-response` classifies attack types and forensic handling.

## Key Features

- **Automated Severity Classification** - Intelligent incident triage based on impact and urgency metrics
- **Timeline Reconstruction** - Transform scattered logs and events into coherent incident narratives
- **Post-Incident Review Generation** - Structured PIRs with multiple RCA frameworks
- **Communication Templates** - Pre-built templates for stakeholder updates and escalations
- **Runbook Integration** - Generate actionable runbooks from incident patterns

## Skills Included

### Core Tools

1. **Incident Classifier** (`incident_classifier.py`)
   - Analyzes incident descriptions and outputs severity levels
   - Recommends response teams and initial actions
   - Generates communication templates based on severity

2. **Timeline Reconstructor** (`timeline_reconstructor.py`)
   - Processes timestamped events from multiple sources
   - Reconstructs chronological incident timeline
   - Identifies gaps and provides duration analysis

3. **PIR Generator** (`pir_generator.py`)
   - Creates comprehensive Post-Incident Review documents
   - Applies multiple RCA frameworks (5 Whys, Fishbone, Timeline)
   - Generates actionable follow-up items

## Incident Response Framework

### Severity Classification System

#### SEV1 - Critical Outage
**Definition:** Complete service failure affecting all users or critical business functions

**Characteristics:**
- Customer-facing services completely unavailable
- Data loss or corruption affecting users
- Security breaches with customer data exposure
- Revenue-generating systems down
- SLA violations with financial penalties

**Response Requirements:**
- Immediate escalation to on-call engineer
- Incident Commander assigned within 5 minutes
- Executive notification within 15 minutes
- Public status page update within 15 minutes
- War room established
- All hands on deck if needed

**Communication Frequency:** Every 15 minutes until resolution

#### SEV2 - Major Impact
**Definition:** Significant degradation affecting subset of users or non-critical functions

**Characteristics:**
- Partial service degradation (>25% of users affected)
- Performance issues causing user frustration
- Non-critical features unavailable
- Internal tools impacting productivity
- Data inconsistencies not affecting user experience

**Response Requirements:**
- On-call engineer response within 15 minutes
- Incident Commander assigned within 30 minutes
- Status page update within 30 minutes
- Stakeholder notification within 1 hour
- Regular team updates

**Communication Frequency:** Every 30 minutes during active response

#### SEV3 - Minor Impact
**Definition:** Limited impact with workarounds available

**Characteristics:**
- Single feature or component affected
- <25% of users impacted
- Workarounds available
- Performance degradation not significantly impacting UX
- Non-urgent monitoring alerts

**Response Requirements:**
- Response within 2 hours during business hours
- Next ','.claude\skills\incident-commander\SKILL.md','8549dec0c59a4311d3b4194e9e1f001f575a9e7d4e38051b3791e3ff5d79ed4e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:incident-response','project_skill','skill://simplicio-runtime/incident-response','skill: incident-response','---
name: incident-response
description: "Use when a security incident has been detected or declared and needs classification, triage, escalation path determination, and forensic evidence collection. Covers SEV1-SEV4 classification, false positive filtering, incident taxonomy, and NIST SP 800-61 lifecycle."
---

# Incident Response

Incident response skill for the full lifecycle from initial triage through forensic collection, severity declaration, and escalation routing. This is NOT threat hunting (see threat-detection) or post-incident compliance mapping (see governance/compliance-mapping) — this is about classifying, triaging, and managing declared security incidents.

---

## Table of Contents

- [Overview](#overview)
- [Incident Triage Tool](#incident-triage-tool)
- [Incident Classification](#incident-classification)
- [Severity Framework](#severity-framework)
- [False Positive Filtering](#false-positive-filtering)
- [Forensic Evidence Collection](#forensic-evidence-collection)
- [Escalation Paths](#escalation-paths)
- [Regulatory Notification Obligations](#regulatory-notification-obligations)
- [Workflows](#workflows)
- [Anti-Patterns](#anti-patterns)
- [Cross-References](#cross-references)

---

## Overview

### What This Skill Does

This skill provides the methodology and tooling for **incident triage and response** — classifying security events into typed incidents, scoring severity, filtering false positives, determining escalation paths, and initiating forensic evidence collection under chain-of-custody controls.

### Distinction from Other Security Skills

| Skill | Focus | Approach |
|-------|-------|----------|
| **incident-response** (this) | Active incidents | Reactive — classify, escalate, collect evidence |
| threat-detection | Pre-incident hunting | Proactive — find threats before alerts fire |
| cloud-security | Cloud posture assessment | Preventive — IAM, S3, network misconfiguration |
| red-team | Offensive simulation | Offensive — test detection and response capability |

### Prerequisites

A security event must be ingested before triage. Events can come from SIEM alerts, EDR detections, threat intel feeds, or user reports. The triage tool accepts JSON event payloads; see the input schema below.

---

## Incident Triage Tool

The `incident_triage.py` tool classifies events, checks false positives, scores severity, determines escalation, and performs forensic pre-analysis.

```bash
# Classify an event from JSON file
python3 scripts/incident_triage.py --input event.json --classify --json

# Classify with false positive filtering enabled
python3 scripts/incident_triage.py --input event.json --classify --false-positive-check --json

# Force a severity level for tabletop exercises
python3 scripts/incident_triage.py --input event.json --severity sev1 --json

# Read event from stdin
echo ''{"event_type": "ransomware", "host": "prod-db-01", "raw_payload": {}}'' | \
  python3 scripts/incident_triage.py --classify --false-positive-check --json
```

### Input Event Schema

```json
{
  "event_type": "ransomware",
  "host": "prod-db-01",
  "user": "svc_backup",
  "source_ip": "10.1.2.3",
  "timestamp": "2024-01-15T14:32:00Z",
  "raw_payload": {}
}
```

### Exit Codes

| Code | Meaning | Required Response |
|------|---------|-------------------|
| 0 | SEV3/SEV4 or clean | Standard ticket-based handling |
| 1 | SEV2 — elevated | 1-hour bridge call, async coordination |
| 2 | SEV1 — critical | Immediate 15-minute war room, all-hands |

---

## Incident Classification

Security events are classified into 14 incident types. Classification drives default severity, MITRE technique mapping, and response SLA.

### Incident Taxonomy

| Incident Type | Default Severity | MITRE Technique | Response SLA |
|--------------|-----------------|-----------------|--------------|
| ransomware | SEV1 | T1486 | 15 minutes |
| data_exfiltration | SEV1 | T1048 | 15 minutes |
| apt_intrusion | SEV1 | T1566 | 15 minutes |
| supply_chain_compromise | SEV1 | T1195 | 15 minutes |
| domain_controller_breach | SEV1 | T1078.002 | 15 minutes |
| ','.claude\skills\incident-response\SKILL.md','9cd289fc56de08145b3d3e287f9d4966e68c0b979aca5a7670c98575361c45b5','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:information-security-manager-iso27001','project_skill','skill://simplicio-runtime/information-security-manager-iso27001','skill: information-security-manager-iso27001','---
name: information-security-manager-iso27001
description: ISO 27001 ISMS implementation and cybersecurity governance for HealthTech and MedTech companies. Use when designing an ISMS, running security risk assessments, implementing controls, pursuing ISO 27001 certification, preparing security audits, responding to security incidents, or verifying compliance. Covers ISO 27001, ISO 27002, healthcare security, and medical device cybersecurity.
---

# Information Security Manager - ISO 27001

Implement and manage Information Security Management Systems (ISMS) aligned with ISO 27001:2022 and healthcare regulatory requirements.

---

## Table of Contents

- [Trigger Phrases](#trigger-phrases)
- [Quick Start](#quick-start)
- [Tools](#tools)
- [Workflows](#workflows)
- [Reference Guides](#reference-guides)
- [Validation Checkpoints](#validation-checkpoints)

---

## Trigger Phrases

Use this skill when you hear:
- "implement ISO 27001"
- "ISMS implementation"
- "security risk assessment"
- "information security policy"
- "ISO 27001 certification"
- "security controls implementation"
- "incident response plan"
- "healthcare data security"
- "medical device cybersecurity"
- "security compliance audit"

---

## Quick Start

### Run Security Risk Assessment

```bash
python scripts/risk_assessment.py --scope "patient-data-system" --output risk_register.json
```

### Check Compliance Status

```bash
python scripts/compliance_checker.py --standard iso27001 --controls-file controls.csv
```

### Generate Gap Analysis Report

```bash
python scripts/compliance_checker.py --standard iso27001 --gap-analysis --output gaps.md
```

---

## Tools

### risk_assessment.py

Automated security risk assessment following ISO 27001 Clause 6.1.2 methodology.

**Usage:**

```bash
# Full risk assessment
python scripts/risk_assessment.py --scope "cloud-infrastructure" --output risks.json

# Healthcare-specific assessment
python scripts/risk_assessment.py --scope "ehr-system" --template healthcare --output risks.json

# Quick asset-based assessment
python scripts/risk_assessment.py --assets assets.csv --output risks.json
```

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--scope` | Yes | System or area to assess |
| `--template` | No | Assessment template: `general`, `healthcare`, `cloud` |
| `--assets` | No | CSV file with asset inventory |
| `--output` | No | Output file (default: stdout) |
| `--format` | No | Output format: `json`, `csv`, `markdown` |

**Output:**
- Asset inventory with classification
- Threat and vulnerability mapping
- Risk scores (likelihood × impact)
- Treatment recommendations
- Residual risk calculations

### compliance_checker.py

Verify ISO 27001/27002 control implementation status.

**Usage:**

```bash
# Check all ISO 27001 controls
python scripts/compliance_checker.py --standard iso27001

# Gap analysis with recommendations
python scripts/compliance_checker.py --standard iso27001 --gap-analysis

# Check specific control domains
python scripts/compliance_checker.py --standard iso27001 --domains "access-control,cryptography"

# Export compliance report
python scripts/compliance_checker.py --standard iso27001 --output compliance_report.md
```

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--standard` | Yes | Standard to check: `iso27001`, `iso27002`, `hipaa` |
| `--controls-file` | No | CSV with current control status |
| `--gap-analysis` | No | Include remediation recommendations |
| `--domains` | No | Specific control domains to check |
| `--output` | No | Output file path |

**Output:**
- Control implementation status
- Compliance percentage by domain
- Gap analysis with priorities
- Remediation recommendations

---

## Workflows

### Workflow 1: ISMS Implementation

**Step 1: Define Scope and Context**

Document organizational context and ISMS boundaries:
- Identify interested parties and requirements
- Define ISMS scope and boundaries
- Document internal/external issues

**Validation:** Scope statement reviewed and appro','.claude\skills\information-security-manager-iso27001\SKILL.md','33d32d51bbfcf5421de26cb90b40780e12801ff7e052284f3a1cee6c7fdc016a','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:init','project_skill','skill://simplicio-runtime/init','skill: init','---
name: init
description: >-
  Set up Playwright in a project. Use when user says "set up playwright",
  "add e2e tests", "configure playwright", "testing setup", "init playwright",
  or "add test infrastructure".
---

# Initialize Playwright Project

Set up a production-ready Playwright testing environment. Detect the framework, generate config, folder structure, example test, and CI workflow.

## Steps

### 1. Analyze the Project

Use the `Explore` subagent to scan the project:

- Check `package.json` for framework (React, Next.js, Vue, Angular, Svelte)
- Check for `tsconfig.json` → use TypeScript; otherwise JavaScript
- Check if Playwright is already installed (`@playwright/test` in dependencies)
- Check for existing test directories (`tests/`, `e2e/`, `__tests__/`)
- Check for existing CI config (`.github/workflows/`, `.gitlab-ci.yml`)

### 2. Install Playwright

If not already installed:

```bash
npm init playwright@latest -- --quiet
```

Or if the user prefers manual setup:

```bash
npm install -D @playwright/test
npx playwright install --with-deps chromium
```

### 3. Generate `playwright.config.ts`

Adapt to the detected framework:

**Next.js:**
```typescript
import { defineConfig, devices } from ''@playwright/test'';

export default defineConfig({
  testDir: ''./e2e'',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    [''html'', { open: ''never'' }],
    [''list''],
  ],
  use: {
    baseURL: ''http://localhost:3000'',
    trace: ''on-first-retry'',
    screenshot: ''only-on-failure'',
  },
  projects: [
    { name: "chromium", use: { ...devices[''Desktop Chrome''] } },
    { name: "firefox", use: { ...devices[''Desktop Firefox''] } },
    { name: "webkit", use: { ...devices[''Desktop Safari''] } },
  ],
  webServer: {
    command: ''npm run dev'',
    url: ''http://localhost:3000'',
    reuseExistingServer: !process.env.CI,
  },
});
```

**React (Vite):**
- Change `baseURL` to `http://localhost:5173`
- Change `webServer.command` to `npm run dev`

**Vue/Nuxt:**
- Change `baseURL` to `http://localhost:3000`
- Change `webServer.command` to `npm run dev`

**Angular:**
- Change `baseURL` to `http://localhost:4200`
- Change `webServer.command` to `npm run start`

**No framework detected:**
- Omit `webServer` block
- Set `baseURL` from user input or leave as placeholder

### 4. Create Folder Structure

```
e2e/
├── fixtures/
│   └── index.ts          # Custom fixtures
├── pages/
│   └── .gitkeep          # Page object models
├── test-data/
│   └── .gitkeep          # Test data files
└── example.spec.ts       # First example test
```

### 5. Generate Example Test

```typescript
import { test, expect } from ''@playwright/test'';

test.describe(''Homepage'', () => {
  test(''should load successfully'', async ({ page }) => {
    await page.goto(''/'');
    await expect(page).toHaveTitle(/.+/);
  });

  test(''should have visible navigation'', async ({ page }) => {
    await page.goto(''/'');
    await expect(page.getByRole(''navigation'')).toBeVisible();
  });
});
```

### 6. Generate CI Workflow

If `.github/workflows/` exists, create `playwright.yml`:

```yaml
name: "playwright-tests"

on:
  push:
    branches: [main, dev]
  pull_request:
    branches: [main, dev]

jobs:
  test:
    timeout-minutes: 60
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: lts/*
      - name: "install-dependencies"
        run: npm ci
      - name: "install-playwright-browsers"
        run: npx playwright install --with-deps
      - name: "run-playwright-tests"
        run: npx playwright test
      - uses: actions/upload-artifact@v4
        if: ${{ !cancelled() }}
        with:
          name: "playwright-report"
          path: playwright-report/
          retention-days: 30
```

If `.gitlab-ci.yml` exists, add a Playwright stage instead.

### 7. Update `.gitignore`

Append if not already present:

```
/test-results/
/playwright-report/
/blob-report/
/playwright/.cache/
```

### 8. A','.claude\skills\init\SKILL.md','c454e48273f3ad3e6bdd2f7d1c83c5618cb0947b89f632259a26380a592b81ec','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:init-ali','project_skill','skill://simplicio-runtime/init-ali','skill: init-ali','---
name: init-ali
description: "Create a new AgentHub collaboration session with task, agent count, and evaluation criteria. Use when the user runs /hub:init or asks to start a multi-agent competition on a task."
command: /hub:init
---

# /hub:init — Create New Session

Initialize an AgentHub collaboration session. Creates the `.agenthub/` directory structure, generates a session ID, and configures evaluation criteria.

## Usage

```
/hub:init                                                    # Interactive mode
/hub:init --task "Optimize API" --agents 3 --eval "pytest bench.py" --metric p50_ms --direction lower
/hub:init --task "Refactor auth" --agents 2                  # No eval (LLM judge mode)
```

## What It Does

### If arguments provided

Pass them to the init script:

```bash
python {skill_path}/scripts/hub_init.py \
  --task "{task}" --agents {N} \
  [--eval "{eval_cmd}"] [--metric {metric}] [--direction {direction}] \
  [--base-branch {branch}]
```

### If no arguments (interactive mode)

Collect each parameter:

1. **Task** — What should the agents do? (required)
2. **Agent count** — How many parallel agents? (default: 3)
3. **Eval command** — Command to measure results (optional — skip for LLM judge mode)
4. **Metric name** — What metric to extract from eval output (required if eval command given)
5. **Direction** — Is lower or higher better? (required if metric given)
6. **Base branch** — Branch to fork from (default: current branch)

### Output

```
AgentHub session initialized
  Session ID: 20260317-143022
  Task: Optimize API response time below 100ms
  Agents: 3
  Eval: pytest bench.py --json
  Metric: p50_ms (lower is better)
  Base branch: dev
  State: init

Next step: Run /hub:spawn to launch 3 agents
```

For content or research tasks (no eval command → LLM judge mode):

```
AgentHub session initialized
  Session ID: 20260317-151200
  Task: Draft 3 competing taglines for product launch
  Agents: 3
  Eval: LLM judge (no eval command)
  Base branch: dev
  State: init

Next step: Run /hub:spawn to launch 3 agents
```

## Baseline Capture

If `--eval` was provided, capture a baseline measurement after session creation:

1. Run the eval command in the current working directory
2. Extract the metric value from stdout
3. Append `baseline: {value}` to `.agenthub/sessions/{session-id}/config.yaml`
4. Display: `Baseline captured: {metric} = {value}`

This baseline is used by `result_ranker.py --baseline` during evaluation to show deltas. If the eval command fails at this stage, warn the user but continue — baseline is optional.

## After Init

Tell the user:
- Session created with ID `{session-id}`
- Baseline metric (if captured)
- Next step: `/hub:spawn` to launch agents
- Or `/hub:spawn {session-id}` if multiple sessions exist

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\init-ali\SKILL.md','426ac2f8d7046d6223a6a5b52783b4ddd324a359bbcaf15ef5bf9eb85c63f5e2','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:insecure-defaults','project_skill','skill://simplicio-runtime/insecure-defaults','skill: insecure-defaults','---
name: insecure-defaults
description: "Detects fail-open insecure defaults (hardcoded secrets, weak auth, permissive security) that allow apps to run insecurely in production. Use when auditing security, reviewing config management, or analyzing environment variable handling."
allowed-tools: Read Grep Glob Bash
---

# Insecure Defaults Detection

Finds **fail-open** vulnerabilities where apps run insecurely with missing configuration. Distinguishes exploitable defaults from fail-secure patterns that crash safely.

- **Fail-open (CRITICAL):** `SECRET = env.get(''KEY'') or ''default''` → App runs with weak secret
- **Fail-secure (SAFE):** `SECRET = env[''KEY'']` → App crashes if missing

## When to Use

- **Security audits** of production applications (auth, crypto, API security)
- **Configuration review** of deployment files, IaC templates, Docker configs
- **Code review** of environment variable handling and secrets management
- **Pre-deployment checks** for hardcoded credentials or weak defaults

## When NOT to Use

Do not use this skill for:
- **Test fixtures** explicitly scoped to test environments (files in `test/`, `spec/`, `__tests__/`)
- **Example/template files** (`.example`, `.template`, `.sample` suffixes)
- **Development-only tools** (local Docker Compose for dev, debug scripts)
- **Documentation examples** in README.md or docs/ directories
- **Build-time configuration** that gets replaced during deployment
- **Crash-on-missing behavior** where app won''t start without proper config (fail-secure)

When in doubt: trace the code path to determine if the app runs with the default or crashes.

## Rationalizations to Reject

- **"It''s just a development default"** → If it reaches production code, it''s a finding
- **"The production config overrides it"** → Verify prod config exists; code-level vulnerability remains if not
- **"This would never run without proper config"** → Prove it with code trace; many apps fail silently
- **"It''s behind authentication"** → Defense in depth; compromised session still exploits weak defaults
- **"We''ll fix it before release"** → Document now; "later" rarely comes

## Workflow

Follow this workflow for every potential finding:

### 1. SEARCH: Perform Project Discovery and Find Insecure Defaults

Determine language, framework, and project conventions. Use this information to further discover things like secret storage locations, secret usage patterns, credentialed third-party integrations, cryptography, and any other relevant configuration. Further use information to analyze insecure default configurations.

**Example**
Search for patterns in `**/config/`, `**/auth/`, `**/database/`, and env files:
- **Fallback secrets:** `getenv.*\) or [''"]`, `process\.env\.[A-Z_]+ \|\| [''"]`, `ENV\.fetch.*default:`
- **Hardcoded credentials:** `password.*=.*[''"][^''"]{8,}[''"]`, `api[_-]?key.*=.*[''"][^''"]+[''"]`
- **Weak defaults:** `DEBUG.*=.*true`, `AUTH.*=.*false`, `CORS.*=.*\*`
- **Crypto algorithms:** `MD5|SHA1|DES|RC4|ECB` in security contexts

Tailor search approach based on discovery results.

Focus on production-reachable code, not test fixtures or example files.

### 2. VERIFY: Actual Behavior
For each match, trace the code path to understand runtime behavior.

**Questions to answer:**
- When is this code executed? (Startup vs. runtime)
- What happens if a configuration variable is missing?
- Is there validation that enforces secure configuration?

### 3. CONFIRM: Production Impact
Determine if this issue reaches production:

If production config provides the variable → Lower severity (but still a code-level vulnerability)
If production config missing or uses default → CRITICAL

### 4. REPORT: with Evidence

**Example report:**
```
Finding: Hardcoded JWT Secret Fallback
Location: src/auth/jwt.ts:15
Pattern: const secret = process.env.JWT_SECRET || ''default'';

Verification: App starts without JWT_SECRET; secret used in jwt.sign() at line 42
Production Impact: Dockerfile missing JWT_SECRET
Exploitation: Attacker forges JWTs using ''default'', gains unauthorized access
```

## Quick Verification Check','.claude\skills\insecure-defaults\SKILL.md','4f969633f2435bd590b336638970df087eacc2b5ac689e279c5cf23c54994afc','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:integration-management','project_skill','skill://simplicio-runtime/integration-management','skill: integration-management','---
name: integration-management
description: >
  Post-closing M&A integration tracker — phased workplan, consent tracking,
  contract assignment at scale, weekly status reports. Initializes from whatever
  deal artifacts are available (purchase agreement, deal summary, closing
  checklist) and connects to deal-context.md and closing-checklist.yaml from the
  M&A cold-start. Use when user says "integration", "post-close", "post-closing",
  "consents outstanding", "contract assignment", "integration status", or
  "what''s left on the deal".
argument-hint: "[--init | --contracts | --report | --update | --export [--format csv|table] [--section all|consents|contracts|workplan]] [--deal [code]]"
---

# /integration-management

1. Load `deal-context.md` for deal code, target, close date, deal lead.
2. Load `integration-tracker.yaml` if it exists (or create on --init).
3. Use the workflow below.
4. Route by flag:
   - `--init`: Mode 1 — read PA, build phased workplan, consent tracker
   - `--contracts`: Mode 2 — import contract list (repository or upload), tier and classify
   - `--report`: Mode 3 — generate status report
   - `--update`: Mode 4 — manual update or parse uploaded status document
   - `--export`: Mode 5 — CSV or table export
5. Read/write `~/.claude/plugins/config/claude-for-legal/corporate-legal/deals/[code]/integration-tracker.yaml`.
6. After any write: show summary of changes and surface any new flags.

---

## Matter context

**Matter context.** Check `## Matter workspaces` in the practice-level CLAUDE.md. If `Enabled` is `✗` (the default for in-house users), skip the rest of this paragraph — skills use practice-level context and the matter machinery is invisible. If enabled and there is no active matter, ask: "Which matter is this for? Run `/corporate-legal:matter-workspace switch <slug>` or say `practice-level`." Load the active matter''s `matter.md` for matter-specific context and overrides. Write outputs to the matter folder at `~/.claude/plugins/config/claude-for-legal/corporate-legal/matters/<matter-slug>/`. Never read another matter''s files unless `Cross-matter context` is `on`.

---

## Purpose

Outside counsel closes the deal. Legal inherits the mess. This skill is the
program management layer for post-closing integration — not the business
integration, not IT systems, not HR org design. The legal workstream: consents,
contract assignments, entity rationalization, IP recordals, PA obligations.
It tracks what''s done, what''s due, what''s blocked, and what needs a decision.

---

## Tracker file

Lives at `~/.claude/plugins/config/claude-for-legal/corporate-legal/deals/[code]/integration-tracker.yaml`. Read `deal-context.md` for
the deal code, target name, close date, and deal lead. Inherit any post-close
items from `closing-checklist.yaml` if it exists.

```yaml
# integration-tracker.yaml

metadata:
  deal_code: "[code]"
  target: "[company name]"
  close_date: "[YYYY-MM-DD]"
  deal_lead: "[name]"
  outside_counsel: "[firm and lead attorney]"
  last_updated: "[date]"
  last_status_report: "[date or null]"

pa_dates:
  required_consents_deadline: "[YYYY-MM-DD — extract from PA]"
  rep_survival_expires: "[YYYY-MM-DD]"
  escrow_release: "[YYYY-MM-DD or null]"
  earnout_milestones:
    - description: "[milestone]"
      measurement_date: "[YYYY-MM-DD]"
      payment_date: "[YYYY-MM-DD]"
      owner: "finance"   # always finance — legal tracks date only

workplan:
  day_1:
    target_date: "[close_date + 7 days]"
    items: []
  day_30:
    target_date: "[close_date + 30 days]"
    items: []
  day_90:
    target_date: "[close_date + 90 days]"
    items: []
  day_180:
    target_date: "[close_date + 180 days]"
    items: []

required_consents: []
desired_consents: []

contracts:
  source: "[repository / manual-upload / disclosure-schedule]"
  repository_path: "[path or null]"
  last_imported: "[date]"
  total: 0
  tier_1: []
  tier_2: []
  tier_3: []
  tier_4: []
```

**Workplan item structure:**
```yaml
- id: "W-001"
  description: "[action item]"
  phase: "[day_1 / day_30 / day_90 / day_180]"
  owner: "[legal','.claude\skills\integration-management\SKILL.md','5ac5da3109a3b23981f3f70424856954904411fb844767ae9ae30f9258061d06','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:interpreting-culture-index','project_skill','skill://simplicio-runtime/interpreting-culture-index','skill: interpreting-culture-index','---
name: interpreting-culture-index
description: Interprets Culture Index (CI) surveys, behavioral profiles, and personality assessment data. Supports individual profile interpretation, team composition analysis (gas/brake/glue), burnout detection, profile comparison, hiring profiles, manager coaching, interview transcript analysis for trait prediction, candidate debrief, onboarding planning, and conflict mediation. Accepts extracted JSON or PDF input via OpenCV extraction script.
allowed-tools: Bash Read Grep Glob Write
---

<essential_principles>

**Culture Index measures behavioral traits, not intelligence or skills. There is no "good" or "bad" profile.**

<principle name="never-compare-absolutes">
**Never compare absolute trait values between people.**

The 0-10 scale is just a ruler. What matters is **distance from the red arrow** (population mean at 50th percentile). The arrow position varies between surveys based on EU.

**Why the arrow moves:** Higher EU scores cause the arrow to plot further right; lower EU causes it to plot further left. This does not affect validity—we always measure distance from wherever the arrow lands.

**Wrong**: "Dan has higher autonomy than Jim because his A is 8 vs 5"
**Right**: "Dan is +3 centiles from his arrow; Jim is +1 from his arrow"

Always ask: Where is the arrow, and how far is the dot from it?
</principle>

<principle name="survey-vs-job">
**Survey = who you ARE. Job = who you''re TRYING TO BE.**

> **"You can''t send a duck to Eagle school."** Traits are hardwired—you can only modify behaviors temporarily, at the cost of energy.

- **Top graph (Survey Traits)**: Hardwired by age 12-16. Does not change. Writing with your dominant hand.
- **Bottom graph (Job Behaviors)**: Adaptive behavior at work. Can change. Writing with your non-dominant hand.

Large differences between graphs indicate behavior modification, which drains energy and causes burnout if sustained 3-6+ months.
</principle>

<principle name="distance-interpretation">
**Distance from arrow determines trait strength.**

| Distance | Label | Percentile | Interpretation |
|----------|-------|------------|----------------|
| On arrow | Normative | 50th | Flexible, situational |
| ±1 centile | Tendency | ~67th | Easier to modify |
| ±2 centiles | Pronounced | ~84th | Noticeable difference |
| ±4+ centiles | Extreme | ~98th | Hardwired, compulsive, predictable |

**Key insight:** Every 2 centiles of distance = 1 standard deviation.

Extreme traits drive extreme results but are harder to modify and less relatable to average people.
</principle>

<principle name="l-and-i-exception">
**L (Logic) and I (Ingenuity) use absolute values.**

Unlike A, B, C, D, you CAN compare L and I scores directly between people:
- Logic 8 means "High Logic" regardless of arrow position
- Ingenuity 2 means "Low Ingenuity" for anyone

Only these two traits break the "no absolute comparison" rule.
</principle>

</essential_principles>

## When to Use

- Interpreting Culture Index survey results (individual or team)
- Analyzing CI profiles from PDF or JSON data
- Assessing team composition using Gas/Brake/Glue framework
- Detecting burnout risk by comparing Survey vs Job graphs
- Defining hiring profiles based on CI trait patterns
- Coaching managers on how to work with specific CI profiles
- Predicting CI traits from interview transcripts
- Mediating team conflict using CI profile data

## When NOT to Use

- For non-CI behavioral assessments (DISC, Myers-Briggs, StrengthsFinder, Predictive Index, Enneagram)
- For clinical psychological assessments or diagnoses
- As the sole basis for hiring/firing decisions — CI is one data point among many

<input_formats>

**JSON (Use if available)**

If JSON data is already extracted, use it directly:
```python
import json
with open("person_name.json") as f:
    profile = json.load(f)
```

JSON format:
```json
{
  "name": "Person Name",
  "archetype": "Architect",
  "survey": {
    "eu": 21,
    "arrow": 2.3,
    "a": [5, 2.7],
    "b": [0, -2.3],
    "c": [1, -1.3],
    "d": [3, 0.7],
    "logic": [5, null],','.claude\skills\interpreting-culture-index\SKILL.md','17d2d976ab15964b264dd6a9b5e4b2904c8ab46a9f4ebc563c0637e4c22f37a2','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:interview-system-designer','project_skill','skill://simplicio-runtime/interview-system-designer','skill: interview-system-designer','---
name: interview-system-designer
description: This skill should be used when the user asks to "design interview processes", "create hiring pipelines", "calibrate interview loops", "generate interview questions", "design competency matrices", "analyze interviewer bias", "create scoring rubrics", "build question banks", or "optimize hiring systems". Use for designing role-specific interview loops, competency assessments, and hiring calibration systems.
---

# Interview System Designer

Comprehensive interview loop planning and calibration support for role-based hiring systems.

## Overview

Use this skill to create structured interview loops, standardize question quality, and keep hiring signal consistent across interviewers.

## Core Capabilities

- Interview loop planning by role and level
- Round-by-round focus and timing recommendations
- Suggested question sets by round type
- Framework support for scoring and calibration
- Bias-reduction and process consistency guidance

## Quick Start

```bash
# Generate a loop plan for a role and level
python3 scripts/interview_planner.py --role "Senior Software Engineer" --level senior

# JSON output for integration with internal tooling
python3 scripts/interview_planner.py --role "Product Manager" --level mid --json
```

## Recommended Workflow

1. Run `scripts/interview_planner.py` to generate a baseline loop.
2. Align rounds to role-specific competencies.
3. Validate scoring rubric consistency with interview panel leads.
4. Review for bias controls before rollout.
5. Recalibrate quarterly using hiring outcome data.

## References

- `references/interview-frameworks.md`
- `references/bias_mitigation_checklist.md`
- `references/competency_matrix_templates.md`
- `references/debrief_facilitation_guide.md`

## Common Pitfalls

- Overweighting one round while ignoring other competency signals
- Using unstructured interviews without standardized scoring
- Skipping calibration sessions for interviewers
- Changing hiring bar without documenting rationale

## Best Practices

1. Keep round objectives explicit and non-overlapping.
2. Require evidence for each score recommendation.
3. Use the same baseline rubric across comparable roles.
4. Revisit loop design based on quality-of-hire outcomes.

<!-- Source: https://github.com/alirezarezvani/claude-skills (MIT). Imported into Simplicio (lean: SKILL.md only). Area: engineering. -->
','.claude\skills\interview-system-designer\SKILL.md','4a2aa7bb0045ae8dd8081f7d0bcaaebe113324acddfd973847ed49f4f98d3843','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:isms-audit-expert','project_skill','skill://simplicio-runtime/isms-audit-expert','skill: isms-audit-expert','---
name: isms-audit-expert
description: Information Security Management System (ISMS) audit expert for ISO 27001 compliance verification, security control assessment, and certification support. Use when the user mentions ISO 27001, ISMS audit, Annex A controls, Statement of Applicability (SOA), gap analysis, nonconformity management, internal audit, surveillance audit, or security certification preparation. Helps review control implementation evidence, document audit findings, classify nonconformities, generate risk-based audit plans, map controls to Annex A requirements, prepare Stage 1 and Stage 2 audit documentation, and support corrective action workflows.
triggers:
  - ISMS audit
  - ISO 27001 audit
  - security audit
  - internal audit ISO 27001
  - security control assessment
  - certification audit
  - surveillance audit
  - audit finding
  - nonconformity
---

# ISMS Audit Expert

Internal and external ISMS audit management for ISO 27001 compliance verification, security control assessment, and certification support.

## Table of Contents

- [Audit Program Management](#audit-program-management)
- [Audit Execution](#audit-execution)
- [Control Assessment](#control-assessment)
- [Finding Management](#finding-management)
- [Certification Support](#certification-support)
- [Tools](#tools)
- [References](#references)

---

## Audit Program Management

### Risk-Based Audit Schedule

| Risk Level | Audit Frequency | Examples |
|------------|-----------------|----------|
| Critical | Quarterly | Privileged access, vulnerability management, logging |
| High | Semi-annual | Access control, incident response, encryption |
| Medium | Annual | Policies, awareness training, physical security |
| Low | Annual | Documentation, asset inventory |

### Annual Audit Planning Workflow

1. Review previous audit findings and risk assessment results
2. Identify high-risk controls and recent security incidents
3. Determine audit scope based on ISMS boundaries
4. Assign auditors ensuring independence from audited areas
5. Create audit schedule with resource allocation
6. Obtain management approval for audit plan
7. **Validation:** Audit plan covers all Annex A controls within certification cycle

### Auditor Competency Requirements

- ISO 27001 Lead Auditor certification (preferred)
- No operational responsibility for audited processes
- Understanding of technical security controls
- Knowledge of applicable regulations (GDPR, HIPAA)

---

## Audit Execution

### Pre-Audit Preparation

1. Review ISMS documentation (policies, SoA, risk assessment)
2. Analyze previous audit reports and open findings
3. Prepare audit plan with interview schedule
4. Notify auditees of audit scope and timing
5. Prepare checklists for controls in scope
6. **Validation:** All documentation received and reviewed before opening meeting

### Audit Conduct Steps

1. **Opening Meeting**
   - Confirm audit scope and objectives
   - Introduce audit team and methodology
   - Agree on communication channels and logistics

2. **Evidence Collection**
   - Interview control owners and operators
   - Review documentation and records
   - Observe processes in operation
   - Inspect technical configurations

3. **Control Verification**
   - Test control design (does it address the risk?)
   - Test control operation (is it working as intended?)
   - Sample transactions and records
   - Document all evidence collected

4. **Closing Meeting**
   - Present preliminary findings
   - Clarify any factual inaccuracies
   - Agree on finding classification
   - Confirm corrective action timelines

5. **Validation:** All controls in scope assessed with documented evidence

---

## Control Assessment

### Control Testing Approach

1. Identify control objective from ISO 27002
2. Determine testing method (inquiry, observation, inspection, re-performance)
3. Define sample size based on population and risk
4. Execute test and document results
5. Evaluate control effectiveness
6. **Validation:** Evidence supports conclusion about control status

For detailed technical verification procedures ','.claude\skills\isms-audit-expert\SKILL.md','3266cf8b2fc06346110c8a1827a4adb79daaf4bbe240d766dd4e7c879d356ce1','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:iso13485-audit-prep','project_skill','skill://simplicio-runtime/iso13485-audit-prep','skill: iso13485-audit-prep','---
name: iso13485-audit-prep
description: "/cs:iso13485-audit-prep <scope> — ISO 13485 QMS audit 6-question forcing interrogation. Design controls + CAPA + post-market focused. Use before Clause 8.2.4 internal audit, MDR / FDA QSR alignment review, or product-launch DHF closure audit."
---

# /cs:iso13485-audit-prep — ISO 13485 QMS Forcing Questions

**Command:** `/cs:iso13485-audit-prep <scope>`

The ISO 13485 QMS auditor pressure-tests any medical-device QMS work. Six traceability-obsessed questions before any internal audit, MDR / FDA QSR review, or product launch.

## When to Run

- Before annual Clause 8.2.4 internal audit
- Before MDR / FDA QSR alignment review (substantially harmonized post Feb 2026)
- Before new-device commercial launch (DHF closure audit)
- After significant CAPA closure event (effectiveness verification audit)
- Post-recall event (root cause + corrective action audit)
- Quarterly during regulatory submission preparation

## The Six QMS Questions

### 1. Pull three random DHFs. Are design verification + validation evidence complete?
**Most-cited finding area.**
- DHF must include: design plan + inputs + outputs + verification + validation + transfer + changes
- Sample stratified by product class (I, IIa, IIb, III per MDR)
- Reference `iso13485_audit_playbook.md` for the per-DHF checklist
- Verify traceability matrix from user needs through clinical evidence

### 2. Show me the last 5 CAPAs with effectiveness verification evidence.
**Second-most-cited finding area.**
- Containment / correction / corrective action distinction documented
- Root cause analysis depth: 5 Why minimum
- Effectiveness verification = measurable evidence, not "we updated the procedure"
- Closure approved by appropriate authority
- Repeat CAPAs across products = systemic issue trigger

### 3. When was process validation (IQ/OQ/PQ) last revalidated?
**Clause 7.5.6 — often stale.**
- Initial validation at process introduction
- Revalidation triggers: process change, equipment change, material change, periodic schedule
- Trend monitoring (SPC) where statistical techniques apply per Clause 8.4
- Cross-check with cs-fda-qsr-auditor for 21 CFR 820.75 alignment

### 4. Show me the risk management file for the highest-risk product.
**Clause 7.1 + ISO 14971:2019.**
- Risk management plan exists per product
- Hazard identification covers reasonable foreseeable misuse
- Risk control hierarchy applied: inherent safety > protective measures > information for safety
- Residual risk evaluated + accepted with rationale
- Post-production information feeds back into RMF
- For AI-enabled medical devices: layer ISO 42001 A.5 impact assessment on top

### 5. Show me post-market surveillance evidence — last 6 months.
**Clause 8.2.1 — high-stakes for MDR + FDA.**
- Customer complaint log + investigation closure
- Vigilance reports (serious incident / FSCA) submitted per applicable regulation
- Trend analysis evidence + management review input
- Post-market clinical follow-up (PMCF) for MDR high-risk devices
- MDR reports per 21 CFR 803 for US-marketed devices (cross-check with cs-fda-qsr-auditor)

### 6. Where''s the management review evidence covering all Clause 5.6 inputs?
**Annual minimum; semi-annual for mature programs.**
- Required inputs per Clause 5.6.2: audit results, customer feedback, process performance, product conformity, status of preventive + corrective actions, follow-up from prior reviews, changes that could affect QMS, recommendations for improvement, regulatory requirements
- Outputs per Clause 5.6.3: improvement decisions, product requirement changes, resource needs
- Integrated review across frameworks (per `multi_framework_audit_playbook.md`) preferred

## Workflow

```bash
# 1. Audit programme optimization
python ra-qm-team/skills/qms-audit-expert/scripts/audit_schedule_optimizer.py audit_scope.json

# 2. Mock audit for readiness check
python ../../skills/compliance-os/scripts/audit_simulator.py iso13485_scope.json

# 3. CAPA system review
# Route to ra-qm-team/skills/capa-officer/ tools

# 4. Risk management file review
#','.claude\skills\iso13485-audit-prep\SKILL.md','ce0537b288cd8953f3267178faed06f968a40990f8b3f9b738f1bda4ba488755','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:iso27001-audit-prep','project_skill','skill://simplicio-runtime/iso27001-audit-prep','skill: iso27001-audit-prep','---
name: iso27001-audit-prep
description: "/cs:iso27001-audit-prep <scope> — ISO 27001 ISMS audit readiness 6-question forcing interrogation. Use before annual Clause 9.2 internal audit, surveillance audit prep, or stage 1 certification readiness."
---

# /cs:iso27001-audit-prep — ISO 27001 ISMS Audit Forcing Questions

**Command:** `/cs:iso27001-audit-prep <scope>`

The ISO 27001 ISMS auditor pressure-tests any ISMS work. Six sample-driven questions before any internal audit, stage 1 readiness, or surveillance audit.

## When to Run

- Before annual Clause 9.2 internal audit
- Before stage 1 / stage 2 ISO 27001 certification audit
- Before surveillance audit (year 2 / year 3)
- After material change to ISMS scope (new business unit, new product line, new SaaS adoption)
- Post-incident (breach triggers ad-hoc ISMS audit)
- Quarterly during high-growth phase

## The Six ISMS Questions

### 1. What''s the audit scope, and is rolling 3-year coverage on track?
**No 3-year coverage discipline, no defensible programme.**
- Every Clause 4-10 + every applicable Annex A control must be audited at least once per 3-year cycle
- Run `isms_audit_scheduler.py` in `ra-qm-team/skills/isms-audit-expert/`
- Confirm auditor independence — no self-audit on any sample

### 2. When was the risk register last refreshed, and are treatments linked to Annex A controls?
**Stale risk register = certification finding.**
- Quarterly refresh expected; annual minimum
- Every high/critical risk must link to ≥ 1 Annex A control treating it
- Residual risk acceptance documented + signed
- Review against `iso27001_audit_playbook.md` for stage 1 expectations

### 3. Show me the access review records — quarterly cadence, the last 4 quarters.
**Most-cited finding area.**
- Annex A.5.15 + A.8.2 + A.8.3 access controls
- Sample real records pulled from Okta / IAM, not curated audit-prep packs
- For each terminated employee in last 90 days: deprovisioning evidence within 24-hour SLA
- Privileged access reviewed at finer granularity

### 4. What''s the supplier inventory + last review evidence?
**Second-most-cited finding area.**
- Annex A.5.19-A.5.21 supplier management
- Critical SaaS suppliers reviewed at least annually
- DPAs signed for personal-data sub-processors (cross-check with cs-dpo-gdpr)
- AI-specific contract clauses where third-party AI services in use (cross-check with cs-aims-iso42001)

### 5. Where''s the incident response evidence + post-incident review?
**A.5.24-27 + A.6.8 — high-stakes audit area.**
- Severity definitions documented + consistently applied
- Last 5 incidents have post-incident review (PIR) within 30-day SLA
- GDPR Article 33 / 34 notification timing aligned with A.5.24 (cross-check with cs-dpo-gdpr)
- Blameless retro culture; not punitive

### 6. What''s the management review cadence + inputs?
**Clause 9.3 required inputs are prescriptive — easy to miss.**
- Required inputs: audit results, risks, performance, nonconformities, opportunities
- Schedule: annual minimum; quarterly preferred for mature programs
- Outputs documented + tracked to closure
- Integrated review across frameworks (per `multi_framework_audit_playbook.md`) preferred to separate reviews

## Workflow

```bash
# 1. Audit programme planning
python ra-qm-team/skills/isms-audit-expert/scripts/isms_audit_scheduler.py audit_scope.json

# 2. Mock audit for readiness check
python ../../skills/compliance-os/scripts/audit_simulator.py iso27001_scope.json

# 3. Cross-framework reuse (SOC 2 = 75% overlap; ISO 42001 = 60% reuse)
python ../../skills/compliance-os/scripts/cross_framework_mapper.py program.json
```

## Output Format

```markdown
# ISO 27001 Audit Prep: <scope>
**Date:** YYYY-MM-DD

## The Decision Being Made
[programme-plan | finding-severity | cert-readiness | incident-followup]

## Audit Programme Status
- Clauses scheduled this year: <list>
- Annex A controls scheduled: <count>
- Rolling 3-year coverage: clean | gaps in <list>
- Auditor independence: clean | issues in <list>

## Risk Register Health
- Last refresh: YYYY-MM-DD
- High/critical risks without Ann','.claude\skills\iso27001-audit-prep\SKILL.md','d03caa1885b70657f8b47f18071bf3609a3b2672450407f5cd78a8df7e0a656a','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:iso42001-specialist','project_skill','skill://simplicio-runtime/iso42001-specialist','skill: iso42001-specialist','---
name: iso42001-specialist
description: "ISO/IEC 42001:2023 AI Management System (AIMS) specialist for compliance teams running internal audits. Three decisions: (1) Where are the gaps against Clauses 4-10 and what do we close first? (2) What goes in the AI risk register and which Annex A controls treat each risk? (3) What''s the 12-month internal audit plan that satisfies Clause 9.2? Use when preparing for certification, scoping internal audit cycles, or onboarding AI systems into an existing ISMS (27001) / QMS (13485) program. NOT an executive AI strategy skill (see chief-ai-officer-advisor). NOT EU AI Act compliance (see compliance-team-eu-ai-act)."
license: MIT
metadata:
  version: 1.0.0
  author: Alireza Rezvani
  category: ra-qm-team
  domain: ai-management-system-compliance
  updated: 2026-05-13
  python-tools: aims_gap_analyzer.py, ai_risk_register_builder.py, aims_audit_scheduler.py
  frameworks: iso-42001, iso-23894, iso-38507, nist-ai-rmf, eu-ai-act-mapping
---

# ISO/IEC 42001 AI Management System Specialist

Internal-audit-grade operating skill for ISO/IEC 42001:2023. **Three decisions, no executive AI strategy:**

1. **Where are the AIMS gaps against Clauses 4–10?** — coverage scoring per clause + remediation priority
2. **What''s the AI risk register, and which controls treat each risk?** — Annex A.2–A.10 control mapping per ISO 23894 risk method
3. **What''s the Clause 9.2 internal audit plan?** — 12-month schedule with scope, frequency, auditor independence checks

This skill is **NOT a chief-ai-officer-advisor replacement**. CAIO decides whether to build/buy a model and what business risk to accept. This skill operates the management-system discipline that captures those decisions in audit-ready evidence.

This skill is **NOT an EU AI Act compliance skill**. ISO 42001 is a voluntary management-system standard; EU AI Act is binding product-safety regulation. They overlap (a high-risk AI system per Article 6(2) of the AI Act typically requires the QMS in Article 17, which ISO 42001 can satisfy in part) but the artefacts differ. See `compliance-team-eu-ai-act` for Article-level conformity assessment.

This skill is **NOT a substitute for ISO 23894 + 38507**. 42001 is the management system; 23894 is the AI risk methodology that feeds Clause 6.1; 38507 is the governance lens. The `ai_risk_register_builder.py` tool implements the 23894 process; treat the references as the methodology bridge.

## Keywords

ISO 42001, ISO/IEC 42001:2023, AI Management System, AIMS, AI governance, AI risk management, ISO 23894, AI risk assessment, ISO 38507, AI compliance, AI audit, internal audit AI, Annex A controls, AI risk register, AI policy, AI impact assessment, conformity declaration, AI lifecycle, AI risk treatment, NIST AI RMF, NIST AI Risk Management Framework, ISACA AI audit, BSI AIC4, AI assurance, responsible AI, AI ethics governance, AI system inventory, third-party AI risk, AI vendor management, AI change management, AI incident management

## Quick Start

```bash
# Decision A: AIMS gap analysis against Clauses 4-10
python scripts/aims_gap_analyzer.py                           # embedded sample (mid-stage AI SaaS)
python scripts/aims_gap_analyzer.py path/to/aims_evidence.json

# Decision B: AI risk register + Annex A control mapping
python scripts/ai_risk_register_builder.py                    # embedded 7-risk sample
python scripts/ai_risk_register_builder.py path/to/risks.json

# Decision C: Clause 9.2 internal audit 12-month plan
python scripts/aims_audit_scheduler.py                        # embedded 4-domain sample
python scripts/aims_audit_scheduler.py path/to/scope.json
```

## Key Questions (ask these first)

- **Does the AIMS scope statement (Clause 4.3) name every AI system, including embedded models and third-party AI services?** If "AI features added by our SaaS vendors" is not in scope, the AIMS is incomplete.
- **Does the AI policy (Clause 5.2) commit to lawful use AND beneficial purpose AND human oversight AND continual improvement?** Missing any of the four = nonconformity at certification.
- **Ha','.claude\skills\iso42001-specialist\SKILL.md','c71d896acf6a57199e2a02014e07e4da56130c13fb82db509ea74d174b4692f0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:jira-expert','project_skill','skill://simplicio-runtime/jira-expert','skill: jira-expert','---
name: jira-expert
description: Atlassian Jira expert for creating and managing projects, planning, product discovery, JQL queries, workflows, custom fields, automation, reporting, and all Jira features. Use when setting up or configuring Jira projects, writing JQL and advanced searches, creating dashboards, designing workflows, or performing technical Jira operations.
---

# Atlassian Jira Expert

Master-level expertise in Jira configuration, project management, JQL, workflows, automation, and reporting. Handles all technical and operational aspects of Jira.

## Quick Start — Most Common Operations

All MCP examples in this skill use the real Atlassian Remote MCP tools (camelCase, surfaced as `mcp__atlassian__<toolName>`). The canonical tool list is `project-management/references/atlassian-mcp-tools.md` — never invent tool names; if a capability isn''t listed there, it is not available via MCP.

**Create an issue** (call `getAccessibleAtlassianResources` once first to obtain `cloudId`):
```
mcp__atlassian__createJiraIssue (cloudId, projectKey="MYPROJ", issueTypeName="Story", summary="My new story")
```

**Run a JQL query** (build the JQL from natural language with the bundled script, then execute):
```bash
python3 scripts/jql_query_builder.py "high priority bugs assigned to me"
# → emits validated JQL, e.g.: assignee = currentUser() AND type = Bug AND status != Done
```
```
mcp__atlassian__searchJiraIssuesUsingJql (cloudId, jql="project = MYPROJ AND status != Done AND dueDate < now()")
```

**Create a project**: NOT available via MCP. Use the Jira web UI (`Projects > Create project`) or REST API (`POST /rest/api/3/project`).

For the full tool reference, see [Atlassian MCP Integration](#atlassian-mcp-integration). For JQL functions, see [JQL Functions Reference](#jql-functions-reference). For report templates, see [Reporting Templates](#reporting-templates).

---

## Workflows

### Project Creation

> Project creation is **not available via MCP** — perform steps 2-6 in the Jira web UI (`Projects > Create project`) or via REST API (`POST /rest/api/3/project`). After creation, verify visibility with `mcp__atlassian__getVisibleJiraProjects` and inspect issue types with `mcp__atlassian__getJiraProjectIssueTypesMetadata`.

1. Determine project type (Scrum, Kanban, Bug Tracking, etc.)
2. Create project with appropriate template (web UI / REST)
3. Configure project settings:
   - Name, key, description
   - Project lead and default assignee
   - Notification scheme
   - Permission scheme
4. Set up issue types and workflows
5. Configure custom fields if needed
6. Create initial board/backlog view
7. **HANDOFF TO**: Scrum Master for team onboarding

### Workflow Design

> Workflow/scheme editing is **not available via MCP** — configure in `Jira Settings > Issues > Workflows`. Use the bundled validator to catch anti-patterns before deploying.

1. Map out process states (To Do → In Progress → Done)
2. Define transitions and conditions
3. Lint the design before building it in Jira:
   ```bash
   python3 scripts/workflow_validator.py workflow.json --format json
   ```
   Input: a JSON file with the workflow''s `states` and `transitions`. Consume the output: fix every reported anti-pattern (dead-end states, unreachable states, missing transitions) in the design before touching Jira.
4. Add validators, post-functions, and conditions; configure the workflow scheme (web UI)
5. **Validate**: Deploy to a test project first; verify all transitions, conditions, and post-functions behave as expected before associating with production projects
6. Associate workflow with project
7. Test workflow with sample issues — via MCP: `mcp__atlassian__getTransitionsForJiraIssue` on a sample issue to confirm expected transitions surface, then `mcp__atlassian__transitionJiraIssue` to walk it through the flow

### JQL Query Building

**Start with the bundled builder** — it pattern-matches natural language to validated JQL:
```bash
python3 scripts/jql_query_builder.py "high priority bugs assigned to me" --format json
python3 scripts/jql_query_builder.py --','.claude\skills\jira-expert\SKILL.md','f6ca2dcf4e0a0c15c3e11802a081f8f29e74c960a43cdaf78975b9fbd1517262','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:karpathy-coder','project_skill','skill://simplicio-runtime/karpathy-coder','skill: karpathy-coder','---
name: karpathy-coder
description: Use when writing, reviewing, or committing code to enforce Karpathy''s 4 coding principles — surface assumptions before coding, keep it simple, make surgical changes, define verifiable goals. Triggers on "review my diff", "check complexity", "am I overcomplicating this", "karpathy check", "before I commit", or any code quality concern where the LLM might be overcoding.
context: fork
version: 2.9.0
author: claude-code-skills
license: MIT
tags: [code-quality, discipline, karpathy, simplicity, surgical-changes, anti-patterns, review]
compatible_tools: [claude-code, codex-cli, cursor, antigravity, opencode, gemini-cli]
---

# Karpathy Coder — Active Coding Discipline

Derived from [Andrej Karpathy''s observations](https://x.com/karpathy/status/2015883857489522876) on LLM coding pitfalls. This is **not just guidelines** — it ships Python tools that detect violations, a review agent, a slash command, and a pre-commit hook.

> "The models make wrong assumptions on your behalf and just run along with them without checking. They don''t manage their confusion, don''t seek clarifications, don''t surface inconsistencies, don''t present tradeoffs, don''t push back when they should."
>
> "They really like to overcomplicate code and APIs, bloat abstractions, don''t clean up dead code... implement a bloated construction over 1000 lines when 100 would do."
>
> "LLMs are exceptionally good at looping until they meet specific goals... Don''t tell it what to do, give it success criteria and watch it go."
>
> — Andrej Karpathy

## The four principles

### 1. Think Before Coding

**Don''t assume. Don''t hide confusion. Surface tradeoffs.**

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don''t pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what''s confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn''t requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

**The test:** Would a senior engineer say this is overcomplicated? If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

- Don''t "improve" adjacent code, comments, or formatting.
- Don''t refactor things that aren''t broken.
- Match existing style, even if you''d do it differently.
- If you notice unrelated dead code, mention it — don''t delete it.
- Remove imports/variables/functions that YOUR changes made unused.
- Don''t remove pre-existing dead code unless asked.

**The test:** Every changed line should trace directly to the user''s request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

| Instead of... | Transform to... |
|---|---|
| "Add validation" | "Write tests for invalid inputs, then make them pass" |
| "Fix the bug" | "Write a test that reproduces it, then make it pass" |
| "Refactor X" | "Ensure tests pass before and after" |

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

## Slash command

`/karpathy-check` — Run the full 4-principle review on your staged changes.

## Python tools (`scripts/`)

All tools are stdlib-only. Run with `--help`.

| Script | What it detects |
|---|---|
| `complexity_checker.py` | Over-engineering: too many classes, deep nesting, high cyclomatic complexity, unused params, premature abstractions |
| `diff_surgeon.py` | Diff noise: lines that don''t trace to the stated goal — comment changes, style drift, drive-by refactors |
| `assumption_linter.py` | Hidden assumptions in a plan: unasked features, missing clarifications, silent interpretation choices |
| `goal_verifier.py` | Weak success criteria: vague plans without verifiable checks, missing test assertions |

## Sub-agent

`karpathy-reviewer` — Runs a','.claude\skills\karpathy-coder\SKILL.md','c28d3f80bc9f206c8f9f5bb24c856baf8430de2696bd0b055937325a4a71a34a','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:kubernetes-operator','project_skill','skill://simplicio-runtime/kubernetes-operator','skill: kubernetes-operator','---
name: kubernetes-operator
description: Use when building a Kubernetes Operator — custom controllers that reconcile CRD state. Triggers on "build an operator", "CRD design", "reconcile loop", "controller-runtime", "kubebuilder", "operator-sdk", "metacontroller", "KOPF", "operator capability levels", or "custom resource". Ships CRD validator, reconcile-loop linter, and OperatorHub capability auditor (all stdlib Python), 4 references on the operator pattern + CRD design + reconcile patterns + tooling landscape, and a /operator-audit slash command. NOT a generic k8s skill — specifically the Operator pattern.
context: fork
version: 2.9.0
author: claude-code-skills
license: MIT
tags: [kubernetes, operator, crd, controller-runtime, kubebuilder, operator-sdk, metacontroller, kopf, reconcile, devops]
compatible_tools: [claude-code, codex-cli, cursor, antigravity, opencode, gemini-cli]
---

# Kubernetes Operator

Build operators that reconcile correctly. Most operator bugs are not Kubernetes bugs — they are reconcile-loop bugs: missing finalizers, blocking calls, no requeue on transient errors, status drift, RBAC over-grants. This skill catches them deterministically before they reach a cluster.

## When to use

- Building a new Kubernetes Operator (controller for a CRD)
- Reviewing an existing operator for capability-level gaps
- Auditing a CRD spec for status/conditions/finalizer correctness
- Choosing a framework (controller-runtime / kubebuilder / operator-sdk / metacontroller / KOPF)
- Designing the API surface of a Custom Resource
- Hardening RBAC, leader election, or webhook validation

## When NOT to use

- Plain Helm chart packaging → use `helm-chart-builder`
- Standard kubectl operations / blue-green deploys → use `senior-devops`
- General k8s security posture → use `cloud-security`
- "I want to run a workload" — that''s a Deployment / Job, not an operator

## Core principle: an operator is a reconcile loop, not a script

```
observe(actual) → desired = read(spec) → diff(actual, desired) → act → update(status)
                                                                          ↓
                                                                   requeue / done
```

Operators that fail are the ones that:
1. Treat reconcile as imperative (do this, then this, then this) instead of declarative (make actual=desired, idempotently)
2. Don''t requeue transient failures
3. Don''t use finalizers, leaving orphan resources
4. Mutate spec instead of status
5. Don''t use the status subresource (status updates trigger spec reconciles → loop)
6. Block in reconcile (long HTTP calls, locks)
7. Forget leader election → split-brain on multi-replica deploys

The 3 tools below catch each of these.

## Quick start

```bash
SKILL=engineering/kubernetes-operator/skills/kubernetes-operator

# Validate a CRD design
python "$SKILL/scripts/crd_validator.py" --crd config/crd/myapp.yaml

# Lint a Go reconcile function
python "$SKILL/scripts/reconcile_lint.py" --controller controllers/myapp_controller.go

# Score against OperatorHub Capability Levels (1-5)
python "$SKILL/scripts/operator_capability_audit.py" --operator-dir .
```

## The 3 Python tools

All stdlib-only. Run with `--help`.

### `crd_validator.py`

Validates a CRD YAML against operator-pattern best practices.

```bash
python scripts/crd_validator.py --crd config/crd/myapp.yaml
python scripts/crd_validator.py --crd config/crd/ --format json
```

**Checks:**
- `spec.versions[*].subresources.status` is set (status subresource)
- `spec.scope` is `Namespaced` (not `Cluster`) unless explicitly justified
- Singular and listKind defined
- `spec.versions[*].schema.openAPIV3Schema` has type definitions (no `x-kubernetes-preserve-unknown-fields: true` at top level)
- A version is marked `served: true` AND `storage: true`
- Conditions array is in the schema (allows `metav1.Conditions`)
- Printer columns include `Age` and `Status`/`Phase`

### `reconcile_lint.py`

Lints a Go controller reconcile function for anti-patterns.

```bash
python scripts/reconcile_lint.py --controller controllers/myapp_c','.claude\skills\kubernetes-operator\SKILL.md','48be9e4715b5422d501e0724eae192bf86020d9c75efa29cb53818658b321865','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:landing-page-generator','project_skill','skill://simplicio-runtime/landing-page-generator','skill: landing-page-generator','---
name: landing-page-generator
description: "Generates high-converting landing pages as complete Next.js/React (TSX) components with Tailwind CSS. Creates hero sections, feature grids, pricing tables, FAQ accordions, testimonial blocks, and CTA sections using proven copy frameworks (PAS, AIDA, BAB). Outputs SEO meta tags, structured data, and performance-optimised code targeting Core Web Vitals (LCP < 1s, CLS < 0.1). Use when the user asks to create a landing page, marketing page, homepage, single-page site, lead capture page, campaign page, promo page, or conversion-optimised web page — or when they want to A/B test landing page variants or replace a static page with one designed to convert."
---

# Landing Page Generator

Generate high-converting landing pages from a product description. Output complete Next.js/React components with multiple section variants, proven copy frameworks, SEO optimization, and performance-first patterns. Not lorem ipsum — actual copy that converts.

**Target:** LCP < 1s · CLS < 0.1 · FID < 100ms  
**Output:** TSX components + Tailwind styles + SEO meta + copy variants

---

## Core Capabilities

- 5 hero section variants (centered, split, gradient, video-bg, minimal)
- Feature sections (grid, alternating, cards with icons)
- Pricing tables (2–4 tiers with feature lists and toggle)
- FAQ accordion with schema markup
- Testimonials (grid, carousel, single-quote)
- CTA sections (banner, full-page, inline)
- Footer (simple, mega, minimal)
- 4 design styles with Tailwind class sets

---

## Generation Workflow

Follow these steps in order for every landing page request:

1. **Gather inputs** — collect product name, tagline, audience, pain point, key benefit, pricing tiers, design style, and copy framework using the trigger format below. Ask only for missing fields.
2. **Analyze brand voice** (recommended) — if the user has existing brand content (website copy, blog posts, marketing materials), run it through `marketing-skill/skills/content-production/scripts/brand_voice_analyzer.py` to get a voice profile (formality, tone, perspective). Use the profile to inform design style and copy framework selection:
   - formal + professional → **enterprise** style, **AIDA** framework
   - casual + friendly → **bold-startup** style, **BAB** framework
   - professional + authoritative → **dark-saas** style, **PAS** framework
   - casual + conversational → **clean-minimal** style, **BAB** framework
3. **Select design style** — map the user''s choice (or infer from brand voice analysis) to one of the four Tailwind class sets in the Design Style Reference.
4. **Apply copy framework** — write all headline and body copy using the chosen framework (PAS / AIDA / BAB) before generating components. Match the voice profile''s formality and tone throughout.
5. **Generate sections in order** — Hero → Features → Pricing → FAQ → Testimonials → CTA → Footer. Skip sections not relevant to the product.
6. **Validate against SEO checklist** — run through every item in the SEO Checklist before outputting final code. Fix any gaps inline.
7. **Output final components** — deliver complete, copy-paste-ready TSX files with all Tailwind classes, SEO meta, and structured data included.

---

## Triggering This Skill

```
Product: [name]
Tagline: [one sentence value prop]
Target audience: [who they are]
Key pain point: [what problem you solve]
Key benefit: [primary outcome]
Pricing tiers: [free/pro/enterprise or describe]
Design style: dark-saas | clean-minimal | bold-startup | enterprise
Copy framework: PAS | AIDA | BAB
```

---

## Design Style Reference

| Style | Background | Accent | Cards | CTA Button |
|---|---|---|---|---|
| **Dark SaaS** | `bg-gray-950 text-white` | `violet-500/400` | `bg-gray-900 border border-gray-800` | `bg-violet-600 hover:bg-violet-500` |
| **Clean Minimal** | `bg-white text-gray-900` | `blue-600` | `bg-gray-50 border border-gray-200 rounded-2xl` | `bg-blue-600 hover:bg-blue-700` |
| **Bold Startup** | `bg-white text-gray-900` | `orange-500` | `shadow-xl rounded-3xl` | `bg-orange-500 hover:bg-orange-600 t','.claude\skills\landing-page-generator\SKILL.md','d6774c239c8007fc26892ecc97ac4a693bdfa8561e83a05f2345262a4eb85e48','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:launch','project_skill','skill://simplicio-runtime/launch','skill: launch','---
name: launch
description: "When the user wants to plan a product launch, feature announcement, or release strategy. Also use when the user mentions ''launch,'' ''Product Hunt,'' ''feature release,'' ''announcement,'' ''go-to-market,'' ''beta launch,'' ''early access,'' ''waitlist,'' ''product update,'' ''how do I launch this,'' ''launch checklist,'' ''GTM plan,'' or ''we''re about to ship.'' Use this whenever someone is preparing to release something publicly. For ongoing marketing after launch, see marketing-ideas. For the offer being launched (bonuses, guarantees, scarcity, naming), see offers."
metadata:
  version: 2.0.1
---

# Launch Strategy

You are an expert in SaaS product launches and feature announcements. Your goal is to help users plan launches that build momentum, capture attention, and convert interest into users.

## Before Starting

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

---

## Core Philosophy

The best companies don''t just launch once—they launch again and again. Every new feature, improvement, and update is an opportunity to capture attention and engage your audience.

A strong launch isn''t about a single moment. It''s about:
- Getting your product into users'' hands early
- Learning from real feedback
- Making a splash at every stage
- Building momentum that compounds over time

---

## The ORB Framework

Structure your launch marketing across three channel types. Everything should ultimately lead back to owned channels.

### Owned Channels
You own the channel (though not the audience). Direct access without algorithms or platform rules.

**Examples:**
- Email list
- Blog
- Podcast
- Branded community (Slack, Discord)
- Website/product

**Why they matter:**
- Get more effective over time
- No algorithm changes or pay-to-play
- Direct relationship with audience
- Compound value from content

**Start with 1-2 based on audience:**
- Industry lacks quality content → Start a blog
- People want direct updates → Focus on email
- Engagement matters → Build a community

**Example - Superhuman:**
Built demand through an invite-only waitlist and one-on-one onboarding sessions. Every new user got a 30-minute live demo. This created exclusivity, FOMO, and word-of-mouth—all through owned relationships. Years later, their original onboarding materials still drive engagement.

### Rented Channels
Platforms that provide visibility but you don''t control. Algorithms shift, rules change, pay-to-play increases.

**Examples:**
- Social media (Twitter/X, LinkedIn, Instagram)
- App stores and marketplaces
- YouTube
- Reddit

**How to use correctly:**
- Pick 1-2 platforms where your audience is active
- Use them to drive traffic to owned channels
- Don''t rely on them as your only strategy

**Example - Notion:**
Hacked virality through Twitter, YouTube, and Reddit where productivity enthusiasts were active. Encouraged community to share templates and workflows. But they funneled all visibility into owned assets—every viral post led to signups, then targeted email onboarding.

**Platform-specific tactics:**
- Twitter/X: Threads that spark conversation → link to newsletter
- LinkedIn: High-value posts → lead to gated content or email signup
- Marketplaces (Shopify, Slack): Optimize listing → drive to site for more

Rented channels give speed, not stability. Capture momentum by bringing users into your owned ecosystem.

### Borrowed Channels
Tap into someone else''s audience to shortcut the hardest part—getting noticed.

**Examples:**
- Guest content (blog posts, podcast interviews, newsletter features)
- Collaborations (webinars, co-marketing, social takeovers)
- Speaking engagements (conferences, panels, virtual summits)
- Influencer partnerships

**Be proactive, not passive:**
1. List industry leaders your audience follows
2. Pitch win-win collaborations
3. Use tools like S','.claude\skills\launch\SKILL.md','969e47286f9f8f80bb10c2e55ab8e8f0504967242d8477fb2ee3f4b2702228a6','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:lead-magnets','project_skill','skill://simplicio-runtime/lead-magnets','skill: lead-magnets','---
name: lead-magnets
description: When the user wants to create, plan, or optimize a lead magnet for email capture or lead generation. Also use when the user mentions "lead magnet," "gated content," "content upgrade," "downloadable," "ebook," "cheat sheet," "checklist," "template download," "opt-in," "freebie," "PDF download," "resource library," "content offer," "email capture content," "Notion template," "spreadsheet template," or "what should I give away for emails." Use this for planning what to create and how to distribute it. For interactive tools as lead magnets, see free-tools. For writing the actual content, see copywriting. For the email sequence after capture, see emails.
metadata:
  version: 2.0.0
---

# Lead Magnets

You are an expert in lead magnet strategy. Your goal is to help plan lead magnets that capture emails, generate qualified leads, and naturally lead to product adoption.

## Before Planning

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Gather this context (ask if not provided):

### 1. Business Context
- What does the company do?
- Who is the ideal customer?
- What problems does your product solve?

### 2. Current Lead Generation
- How do you currently capture leads?
- What lead magnets or offers do you have?
- What''s your current conversion rate on email capture?

### 3. Content Assets
- What existing content could be repurposed? (blog posts, guides, data)
- What expertise can you package?
- What templates or tools do you use internally?

### 4. Goals
- Primary goal: email list growth, lead quality, product education?
- Target audience stage: awareness, consideration, or decision?
- Timeline and resource constraints?

---

## Lead Magnet Principles

### 1. Solve a Specific Problem
- Address one clear pain point, not a broad topic
- "How to write cold emails that get replies" > "Marketing guide"

### 2. Match the Buyer Stage
- Awareness leads need education
- Consideration leads need comparison and evaluation
- Decision leads need implementation help

### 3. High Perceived Value, Low Time Investment
- Should look like it''s worth paying for
- Consumable in under 30 minutes (ideally under 10)
- Immediate, actionable takeaway

### 4. Natural Path to Product
- Solves a problem your product also solves
- Creates awareness of a gap your product fills
- Demonstrates your expertise in the space

### 5. Easy to Consume
- One clear format (don''t mix ebook + video + spreadsheet)
- Works on mobile
- No special software required

---

## Lead Magnet Types

| Type | Best For | Effort | Time to Create |
|------|----------|--------|----------------|
| Checklist | Quick wins, process steps | Low | 1-2 hours |
| Cheat sheet | Reference material, shortcuts | Low | 2-4 hours |
| Template (doc/spreadsheet/Notion) | Repeatable processes, workflows | Low-Med | 2-8 hours |
| Swipe file | Inspiration, examples | Medium | 4-8 hours |
| Ebook/guide | Deep education, authority | High | 1-3 weeks |
| Mini-course (email) | Education + nurture | Medium | 1-2 weeks |
| Mini-course (video) | Education + personality | High | 2-4 weeks |
| Quiz/assessment | Segmentation, engagement | Medium | 1-2 weeks |
| Webinar | Authority, live engagement | Medium | 1 week prep |
| Resource library | Ongoing value, return visits | High | Ongoing |
| Free trial/community access | Product experience | Varies | Varies |

**For detailed creation guidance per format**: See [references/format-guide.md](references/format-guide.md)

---

## Matching Lead Magnets to Buyer Stage

### Awareness Stage
Goal: Educate on the problem. Attract people who don''t know you yet.

| Format | Example |
|--------|---------|
| Checklist | "10-Point Website Audit Checklist" |
| Cheat sheet | "SEO Cheat Sheet for Beginners" |
| Ebook/guide | "The Complete Guide to Email Marketing" |
| Quiz | "Wha','.claude\skills\lead-magnets\SKILL.md','76065e7abbb9d6f5a529f19d5201c6039b275e57640061c152b95aa9af91a82f','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:let-fate-decide','project_skill','skill://simplicio-runtime/let-fate-decide','skill: let-fate-decide','---
name: let-fate-decide
description: "Draws the 12 Houses of the Zodiac Tarot spread to inject entropy into planning when prompts are vague, ambiguous, or casually delegated. Interprets the spread to guide next steps. Use when the user says ''let fate decide'', ''YOLO'', ''whatever'', ''idk'', or other nonchalant phrases, makes Yu-Gi-Oh references, or when you are about to arbitrarily pick between multiple reasonable approaches. Prefer over ask-questions-if-underspecified when the user''s tone is casual or playful rather than precision-seeking."
allowed-tools: Bash Read Grep Glob
---

# Let Fate Decide

When the path forward is unclear, let the cards speak.

## Quick Start

1. Run the drawing script:
   ```bash
   uv run --no-config {baseDir}/scripts/draw_cards.py
   ```

2. The script outputs JSON for the default 12 Houses of the Zodiac spread:
   12 houses, each with 1 Major Arcana card and 2 Minor Arcana cards. Each
   house and card includes a `file` path relative to `{baseDir}/`

3. Read each house file and each card''s meaning file to understand the draw.
   For faster reads, use `--content` to include house and card text directly
   in the JSON:
   ```bash
   uv run --no-config {baseDir}/scripts/draw_cards.py --content
   ```

4. Interpret the spread using the guide at [{baseDir}/references/INTERPRETATION_GUIDE.md]({baseDir}/references/INTERPRETATION_GUIDE.md)

5. When the task belongs to a specialized technical workflow, use
   [{baseDir}/references/TECHNICAL_CONTEXT_LENSES.md]({baseDir}/references/TECHNICAL_CONTEXT_LENSES.md)
   to translate the reading into an audit, verification, domain, failure-class,
   or stakeholder lens

6. Apply the interpretation to the task at hand

## When to Use

- **Vague prompts**: The user''s request is ambiguous and multiple reasonable approaches exist
- **Explicit invocations**: "I''m feeling lucky", "let fate decide", "dealer''s choice", "surprise me", "whatever you think", "YOLO"
- **Casual delegation**: "whatever", "up to you", "your call", "idk", "just do something", "wing it", "I trust you", "doesn''t matter", "do what you want", "I don''t care", "any approach works", "you pick"
- **Yu-Gi-Oh energy**: "Heart of the cards", "I believe in the heart of the cards", "you''ve activated my trap card", "it''s time to duel"
- **Shrug-like brevity**: Very short prompts that fully delegate the decision without expressing a preference
- **Redraw requests**: "Try again" or "draw again" when no actual system changes occurred (this means draw new cards, not re-run the same approach)
- **Tie-breaking**: When you are about to arbitrarily pick between 2+ valid approaches, draw cards instead of silently choosing one

## When NOT to Use

- The user has given clear, specific instructions
- The task has a single obvious correct approach
- As the deciding authority for safety-critical work (security, data integrity,
  production deployments, release approval, incident response)
- The user explicitly asks you NOT to use Tarot
- The user''s tone is precision-seeking rather than casual -- use `ask-questions-if-underspecified` instead to gather actual requirements

## Security and Correctness Use

This skill may be used inside a security, audit, or correctness pipeline as a
creative lens for discovery: choosing which angle to inspect next, breaking
analysis paralysis, generating hypotheses, or surfacing blind spots.

It is never sufficient by itself. In security and correctness contexts, the
reading must be followed by ordinary engineering evidence: source review,
tests, proofs, traces, reproduction steps, exploitability analysis, or other
domain-appropriate verification. Do not treat a favorable card as permission to
ship, suppress a finding, skip validation, or overrule a concrete risk.

## How It Works

### The Draw

The script uses `secrets` for cryptographic randomness:

1. Builds separate Major Arcana (22 cards) and Minor Arcana (56 cards) decks
2. Performs Fisher-Yates shuffles via `secrets.randbelow()` (no modulo bias)
3. Deals the default 12 Houses of the Zodiac spread
4. Each house receives 1 Major Arcana ','.claude\skills\let-fate-decide\SKILL.md','cc0fbee16ddfa15ee6933812a2d694fd8dcd8dc8d23caf0c072db4ee8e802d8b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:libafl','project_skill','skill://simplicio-runtime/libafl','skill: libafl','---
name: libafl
type: fuzzer
description: >
  LibAFL is a modular fuzzing library for building custom fuzzers. Use for
  advanced fuzzing needs, custom mutators, or non-standard fuzzing targets.
---

# LibAFL

LibAFL is a modular fuzzing library that implements features from AFL-based fuzzers like AFL++. Unlike traditional fuzzers, LibAFL provides all functionality in a modular and customizable way as a Rust library. It can be used as a drop-in replacement for libFuzzer or as a library to build custom fuzzers from scratch.

## When to Use

| Fuzzer | Best For | Complexity |
|--------|----------|------------|
| libFuzzer | Quick setup, single-threaded | Low |
| AFL++ | Multi-core, general purpose | Medium |
| LibAFL | Custom fuzzers, advanced features, research | High |

**Choose LibAFL when:**
- You need custom mutation strategies or feedback mechanisms
- Standard fuzzers don''t support your target architecture
- You want to implement novel fuzzing techniques
- You need fine-grained control over fuzzing components
- You''re conducting fuzzing research

## Quick Start

LibAFL can be used as a drop-in replacement for libFuzzer with minimal setup:

```c++
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // Call your code with fuzzer-provided data
    my_function(data, size);
    return 0;
}
```

Build LibAFL''s libFuzzer compatibility layer:
```bash
git clone https://github.com/AFLplusplus/LibAFL
cd LibAFL/libafl_libfuzzer_runtime
./build.sh
```

Compile and run:
```bash
clang++ -DNO_MAIN -g -O2 -fsanitize=fuzzer-no-link libFuzzer.a harness.cc main.cc -o fuzz
./fuzz corpus/
```

## Installation

### Prerequisites

- Clang/LLVM 15-18
- Rust (via rustup)
- Additional system dependencies

### Linux/macOS

Install Clang:
```bash
apt install clang
```

Or install a specific version via apt.llvm.org:
```bash
wget https://apt.llvm.org/llvm.sh
chmod +x llvm.sh
sudo ./llvm.sh 15
```

Configure environment for Rust:
```bash
export RUSTFLAGS="-C linker=/usr/bin/clang-15"
export CC="clang-15"
export CXX="clang++-15"
```

Install Rust:
```bash
curl --proto ''=https'' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

Install additional dependencies:
```bash
apt install libssl-dev pkg-config
```

For libFuzzer compatibility mode, install nightly Rust:
```bash
rustup toolchain install nightly --component llvm-tools
```

### Verification

Build LibAFL to verify installation:
```bash
cd LibAFL/libafl_libfuzzer_runtime
./build.sh
# Should produce libFuzzer.a
```

## Writing a Harness

LibAFL harnesses follow the same pattern as libFuzzer when using drop-in replacement mode:

```c++
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // Your fuzzing target code here
    return 0;
}
```

When building custom fuzzers with LibAFL as a Rust library, harness logic is integrated directly into the fuzzer. See the "Writing a Custom Fuzzer" section below for the full pattern.

> **See Also:** For detailed harness writing techniques, see the **harness-writing** technique skill.

## Usage Modes

LibAFL supports two primary usage modes:

### 1. libFuzzer Drop-in Replacement

Use LibAFL as a replacement for libFuzzer with existing harnesses.

**Compilation:**
```bash
clang++ -DNO_MAIN -g -O2 -fsanitize=fuzzer-no-link libFuzzer.a harness.cc main.cc -o fuzz
```

**Running:**
```bash
./fuzz corpus/
```

**Recommended for long campaigns:**
```bash
./fuzz -fork=1 -ignore_crashes=1 corpus/
```

### 2. Custom Fuzzer as Rust Library

Build a fully customized fuzzer using LibAFL components.

**Create project:**
```bash
cargo init --lib my_fuzzer
cd my_fuzzer
cargo add libafl@0.13 libafl_targets@0.13 libafl_bolts@0.13 libafl_cc@0.13 \
  --features "libafl_targets@0.13/libfuzzer,libafl_targets@0.13/sancov_pcguard_hitcounts"
```

**Configure Cargo.toml:**
```toml
[lib]
crate-type = ["staticlib"]
```

## Writing a Custom Fuzzer

> **See Also:** For detailed harness writing techniques, patterns for handling complex inputs,
> and advanced strategies, see the **fuzz-harness-writing** technique skill.

### Fuzzer Components

A','.claude\skills\libafl\SKILL.md','ed4d79f7b0833416663bcd67a7ba8e25213d1ba03d23331010451debd1b23ab3','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:libfuzzer','project_skill','skill://simplicio-runtime/libfuzzer','skill: libfuzzer','---
name: libfuzzer
type: fuzzer
description: >
  Coverage-guided fuzzer built into LLVM for C/C++ projects. Use for fuzzing
  C/C++ code that can be compiled with Clang.
---

# libFuzzer

libFuzzer is an in-process, coverage-guided fuzzer that is part of the LLVM project. It''s the recommended starting point for fuzzing C/C++ projects due to its simplicity and integration with the LLVM toolchain. While libFuzzer has been in maintenance-only mode since late 2022, it is easier to install and use than its alternatives, has wide support, and will be maintained for the foreseeable future.

## When to Use

| Fuzzer | Best For | Complexity |
|--------|----------|------------|
| libFuzzer | Quick setup, single-project fuzzing | Low |
| AFL++ | Multi-core fuzzing, diverse mutations | Medium |
| LibAFL | Custom fuzzers, research projects | High |
| Honggfuzz | Hardware-based coverage | Medium |

**Choose libFuzzer when:**
- You need a simple, quick setup for C/C++ code
- Project uses Clang for compilation
- Single-core fuzzing is sufficient initially
- Transitioning to AFL++ later is an option (harnesses are compatible)

**Note:** Fuzzing harnesses written for libFuzzer are compatible with AFL++, making it easy to transition if you need more advanced features like better multi-core support.

## Quick Start

```c++
#include <stdint.h>
#include <stddef.h>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // Validate input if needed
    if (size < 1) return 0;

    // Call your target function with fuzzer-provided data
    my_target_function(data, size);

    return 0;
}
```

Compile and run:
```bash
clang++ -fsanitize=fuzzer,address -g -O2 harness.cc target.cc -o fuzz
mkdir corpus/
./fuzz corpus/
```

## Installation

### Prerequisites

- LLVM/Clang compiler (includes libFuzzer)
- LLVM tools for coverage analysis (optional)

### Linux (Ubuntu/Debian)

```bash
apt install clang llvm
```

For the latest LLVM version:
```bash
# Add LLVM repository from apt.llvm.org
# Then install specific version, e.g.:
apt install clang-18 llvm-18
```

### macOS

```bash
# Using Homebrew
brew install llvm

# Or using Nix
nix-env -i clang
```

### Windows

Install Clang through Visual Studio. Refer to [Microsoft''s documentation](https://learn.microsoft.com/en-us/cpp/build/clang-support-msbuild?view=msvc-170) for setup instructions.

**Recommendation:** If possible, fuzz on a local x86_64 VM or rent one on DigitalOcean, AWS, or Hetzner. Linux provides the best support for libFuzzer.

### Verification

```bash
clang++ --version
# Should show LLVM version information
```

## Writing a Harness

### Harness Structure

The harness is the entry point for the fuzzer. libFuzzer calls the `LLVMFuzzerTestOneInput` function repeatedly with different inputs.

```c++
#include <stdint.h>
#include <stddef.h>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // 1. Optional: Validate input size
    if (size < MIN_REQUIRED_SIZE) {
        return 0;  // Reject inputs that are too small
    }

    // 2. Optional: Convert raw bytes to structured data
    // Example: Parse two integers from byte array
    if (size >= 2 * sizeof(uint32_t)) {
        uint32_t a = *(uint32_t*)(data);
        uint32_t b = *(uint32_t*)(data + sizeof(uint32_t));
        my_function(a, b);
    }

    // 3. Call target function
    target_function(data, size);

    // 4. Always return 0 (non-zero reserved for future use)
    return 0;
}
```

### Harness Rules

| Do | Don''t |
|----|-------|
| Handle all input types (empty, huge, malformed) | Call `exit()` - stops fuzzing process |
| Join all threads before returning | Leave threads running |
| Keep harness fast and simple | Add excessive logging or complexity |
| Maintain determinism | Use random number generators or read `/dev/random` |
| Reset global state between runs | Rely on state from previous executions |
| Use narrow, focused targets | Mix unrelated data formats (PNG + TCP) in one harness |

**Rationale:**
- **Speed matters:** Aim for 100s-1000s executions per second per core
- **Repr','.claude\skills\libfuzzer\SKILL.md','4b35d4b0b99842c2864bdf4fef8ae24526ef88d855796d01f14e022f5a63f3d5','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:litreview','project_skill','skill://simplicio-runtime/litreview','skill: litreview','---
name: litreview
description: "Academic literature orientation skill that searches papers via Consensus, builds a strategic search plan using PICO (default) or SPIDER / Decomposition / hybrid as fallbacks, and synthesizes findings into a formatted Word (.docx) research guide. Grill-me intake (research question specificity + framework hint + tentative depth) before the recon search; a second forcing checkpoint after Phase 2 confirms framework + sub-areas + depth before searches consume budget. Configurable depth (5/10/20 queries) controls coverage vs. speed. Output is a ''launching pad'' — an orientation guide that lets a researcher dive in confidently, not a finished review. Use when the user starts literature-oriented research (e.g., ''litreview on [topic]'', ''literature review on [topic]'', ''I''m starting a literature review on X'', ''I''m writing a paper on X'', ''help me research X'', ''I''m doing research on X'', ''can you help me research X''). Do NOT use for single one-off paper searches wanting a quick list — that''s a plain Consensus search."
license: MIT
metadata:
  source_spec: "megaprompts/09-litreview-megaprompt.md"
  build_pattern: "Path B (direct conversion)"
  research_pack_convention: "Agent Integrity Rules verbatim per PR #657 audit; sibling of pulse"
  version: 1.0.0
---

# Litreview — Academic Literature Orientation

> **Portability:** Requires a Consensus MCP connection, Node.js with `docx` package for document generation, and (in CLI) `bash_tool`. Works in Claude Code CLI natively. In Claude.ai with Consensus MCP + Code Execution, the workflow is supported.

Produce a **launching pad** — not a finished literature review, but an orientation document that gives a researcher entering an unfamiliar field everything they need to start reading and searching with confidence. Think: what a generous colleague who knows the field would tell you over coffee.

## Agent Integrity Rules (Research-Pack Convention)

Inherited from the research-pack convention; locked verbatim per PR #657''s cross-skill consistency audit.

- **Source discipline.** Only cite Consensus-returned papers from THIS session. Training knowledge labeled `[Not from Consensus — model knowledge]` and excluded from cited count. Sparse results stated explicitly, never silently filled.
- **Counting discipline.** Three numbers tracked: searches executed / unique papers received (deduplicated) / papers cited. Every cited paper has a retrievable Consensus URL from this session. Use `scripts/citation_tracker.py` for deterministic counts.
- **Tool constraints.** Consensus per-query cap depends on plan tier. **Detect at first search**, report at checkpoint. Rate limit is **1 query/sec** — sequential execution mandatory.
- **Retry policy.** On failure → wait 3s → retry once → log. After 3 consecutive failures: stop, alert user, share what was collected.
- **Plan-tier detection.** Parse first-search response for "Showing top 10" / "upgrade" → free tier (10/search). 20 returned → Pro (20/search). Calculate theoretical ceiling and surface at checkpoint so user can recalibrate.

See [`references/search_budget_allocation.md`](references/search_budget_allocation.md) for the sequential-execution rationale + plan-tier signals.

## Error Handling

| Failure | Behavior |
|---|---|
| Consensus rate-limit hit | Wait 3s, retry once, log outcome |
| Search returns 0 results | Note explicitly; "either niche terminology or genuine gap"; never silently fill |
| Plan-tier cap detected | Log tier; report at checkpoint; surface in audit |
| 3 consecutive failures | Stop searching, alert user, share what''s collected, ask how to proceed |
| Sub-area returns thin results (<5 papers) | Flag in audit; suggest manual PubMed/Scholar supplementation |
| User wants to adjust sub-areas | Update table, re-confirm before searching |
| DOCX validation fails | Unpack XML, fix, repack |

## Phase 0: Grill-Me Intake (3 forcing questions, one at a time)

Each question carries explicit "why I''m asking". Stop condition: max 3 before Phase 1.

### Q1 (root) — Research question specificity

> **State the resea','.claude\skills\litreview\SKILL.md','83acd5ecb59eba062cec5ab65b24d97649b48b881eb85fc26fcc24931b2478f7','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:llm-cost-optimizer','project_skill','skill://simplicio-runtime/llm-cost-optimizer','skill: llm-cost-optimizer','---
name: llm-cost-optimizer
description: "Use proactively whenever LLM API costs come up -- or should. Triggers include: ''my AI costs are too high'', ''optimize token usage'', ''which model should I use'', ''LLM spend is out of control'', ''implement prompt caching'', ''we''re about to launch an AI feature'', ''build me an AI endpoint''. Don''t wait for an explicit cost complaint -- if someone is building an AI feature, designing an LLM endpoint, or choosing between models, cost architecture belongs in the conversation. Apply immediately when any of these are true: a system prompt appears that exceeds a few hundred tokens, all requests are hitting the same model, max_tokens is not set, or no per-feature cost logging exists. NOT for RAG pipeline design (use rag-architect). NOT for improving prompt quality or effectiveness (use senior-prompt-engineer)."
---

# LLM Cost Optimizer

You are an expert in LLM cost engineering with deep experience reducing AI API spend at scale. Your goal is to cut LLM costs by 40–80% without degrading user-facing quality -- using model routing, caching, prompt compression, and observability to make every token count.

AI API costs are engineering costs. Treat them like database query costs: measure first, optimize second, monitor always.

---

## Step 0: Classify Before You Ask

Before gathering context, classify which mode applies based on what the user has already said. Pull answers from the conversation first -- don''t ask for what you already have.

| Mode | When to use |
|---|---|
| **Cost Audit** | Spend exists but no clear picture of where it goes |
| **Optimize Existing System** | Cost drivers are known; apply targeted fixes |
| **Design Cost-Efficient Architecture** | Building new AI features; wire in cost controls before launch |

If the mode is ambiguous, ask in one shot using the context questions below. Only ask what you don''t already know.

---

## Context You Need

**Current State**
- Which LLM providers and models are in use?
- Monthly spend? Which features/endpoints drive it?
- Token usage logging in place? Cost-per-request visibility?

**Goals**
- Target cost reduction? (e.g., "cut 50%", "stay under $X/month")
- Latency constraints? (affects caching and routing tradeoffs)
- Quality floor? (what degradation is acceptable?)

**Workload Profile**
- Request volume and distribution (p50, p95, p99 token counts)?
- Repeated or similar prompts? (caching potential)
- Mix of task types? (classification vs. generation vs. reasoning)

---

## Mode 1: Cost Audit

Use when spend exists but the breakdown is unknown. Instrument first; optimize second.

**Step 1 -- Instrument Every Request**

Log per-request: model, input tokens, output tokens, latency, endpoint/feature, user segment, cost (calculated).

**Step 2 -- Find the 20% Causing 80% of Spend**

Sort by: feature × model × token count. Usually 2–3 endpoints drive the majority of cost. Target those first.

**Step 3 -- Classify Requests by Complexity**

| Complexity | Characteristics | Right Model Tier |
|---|---|---|
| Simple | Classification, extraction, yes/no, short output | Small (Haiku, GPT-4o-mini, Gemini Flash) |
| Medium | Summarization, structured output, moderate reasoning | Mid (Sonnet, GPT-4o) |
| Complex | Multi-step reasoning, code gen, long context | Large (Opus, o3) |

**If token logging doesn''t exist yet:** That''s the first deliverable -- not prompt compression, not routing. You cannot optimize what you cannot see. Provide a logging schema and move to optimization only once baseline data exists.

---

## Mode 2: Optimize Existing System

Apply techniques in ROI order. Don''t skip ahead -- measure impact at each step before moving to the next.

### 1. Model Routing (60–80% cost reduction on routed traffic)

Route by task complexity, not by default. Use a lightweight classifier or rule engine.

- **Small models**: classification, extraction, simple Q&A, formatting, short summaries
- **Mid models**: structured output, moderate summarization, code completion
- **Large models**: complex reasoning, long-context analysis, agentic tasks, code ge','.claude\skills\llm-cost-optimizer\SKILL.md','722142ec5ccecab6bf24acc56114d269b44b4d239e46c69e93caa1460ff38170','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:llm-wiki','project_skill','skill://simplicio-runtime/llm-wiki','skill: llm-wiki','---
name: llm-wiki
description: Use when building or maintaining a persistent personal knowledge base (second brain) in Obsidian where an LLM incrementally ingests sources, updates entity/concept pages, maintains cross-references, and keeps a synthesis current. Triggers include "second brain", "Obsidian wiki", "personal knowledge management", "ingest this paper/article/book", "build a research wiki", "compound knowledge", "Memex", or whenever the user wants knowledge to accumulate across sessions instead of being re-derived by RAG on every query.
context: fork
version: 2.9.0
author: claude-code-skills
license: MIT
tags: [knowledge-management, obsidian, second-brain, pkm, rag-alternative, wiki, karpathy, memex]
compatible_tools: [claude-code, codex-cli, cursor, antigravity, opencode, gemini-cli]
---

# LLM Wiki — Second Brain for Claude Code + Obsidian

Inspired by Andrej Karpathy''s LLM Wiki pattern ([gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)). This skill turns Claude Code (or any agent CLI) into a disciplined wiki maintainer that **incrementally builds and maintains** a persistent, interlinked Obsidian vault as you feed it sources. The knowledge compounds — cross-references, contradictions, and synthesis are already there when you query.

## Core principle

Most LLM+docs workflows are **RAG**: retrieve fragments at query time, synthesize from scratch, forget. The wiki is **compounding**: sources are read once, integrated into a persistent markdown knowledge base, and kept current. You curate and ask; the LLM reads, files, cross-references, and maintains.

> Obsidian is the IDE. The LLM is the programmer. The wiki is the codebase.

## When to use

- **Personal**: track goals, health, psychology, journaling, self-improvement
- **Research**: deep dives over weeks on a topic — papers, articles, reports, evolving thesis
- **Book companion**: file chapters as you read; build a fan-wiki-style companion for characters, themes, plot threads
- **Business/team**: internal wiki fed by Slack, meeting notes, calls — LLM does maintenance nobody else wants to do
- **Competitive analysis, due diligence, trip planning, course notes, hobby deep-dives**

**Do NOT use when:** you need one-shot Q&A over a fixed document (use RAG), you don''t plan to add sources over time, or you don''t want Obsidian in the loop.

## Architecture (three layers)

```
vault/
├── raw/                    # Layer 1 — IMMUTABLE source of truth
│   ├── <source files>      # Articles, papers, PDFs, images, data
│   └── assets/             # Downloaded images from clipped articles
├── wiki/                   # Layer 2 — LLM-owned knowledge base
│   ├── index.md            # Content catalog (LLM updates every ingest)
│   ├── log.md              # Append-only timeline (## [YYYY-MM-DD] <op> | <title>)
│   ├── entities/           # Person/Org/Place pages
│   ├── concepts/           # Ideas, theories, frameworks
│   ├── sources/            # One summary page per ingested source
│   ├── comparisons/        # Cross-source analysis pages
│   └── synthesis/          # High-level syntheses, theses, overviews
├── CLAUDE.md               # Schema + conventions (Claude Code)
└── AGENTS.md               # Same content, for Codex/Cursor/Antigravity
```

- **Layer 1 (raw/)** — you own. LLM only reads; never writes.
- **Layer 2 (wiki/)** — LLM owns. It creates, updates, and cross-references pages. You read it.
- **Layer 3 (CLAUDE.md / AGENTS.md)** — the *schema*. Conventions, workflows, frontmatter rules. Co-evolved by you and the LLM.

## Three core operations

1. **Ingest** — LLM reads a source, discusses takeaways with you, writes a source summary, updates 10-15 relevant pages, updates index, appends to log. See `references/ingest-workflow.md`.
2. **Query** — LLM reads `index.md` first, drills into relevant pages, synthesizes with citations. Good answers get **filed back into the wiki** so explorations compound. See `references/query-workflow.md`.
3. **Lint** — Health check: contradictions, stale claims, orphan pages, missing cross-refs, concepts mention','.claude\skills\llm-wiki\SKILL.md','09a946084c07a51395a3e3d273494bcb702c987fd55f2c1687ada2bbbbf8d614','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:loop','project_skill','skill://simplicio-runtime/loop','skill: loop','---
name: loop
description: "Start an autonomous experiment loop with user-selected interval (10min, 1h, daily, weekly, monthly). Uses CronCreate for scheduling. Use when the user runs /ar:loop or asks to run an autoresearch experiment continuously on a schedule."
command: /ar:loop
---

# /ar:loop — Autonomous Experiment Loop

Start a recurring experiment loop that runs at a user-selected interval.

## Usage

```
/ar:loop engineering/api-speed             # Start loop (prompts for interval)
/ar:loop engineering/api-speed 10m         # Every 10 minutes
/ar:loop engineering/api-speed 1h          # Every hour
/ar:loop engineering/api-speed daily       # Daily at ~9am
/ar:loop engineering/api-speed weekly      # Weekly on Monday ~9am
/ar:loop engineering/api-speed monthly     # Monthly on 1st ~9am
/ar:loop stop engineering/api-speed        # Stop an active loop
```

## What It Does

### Step 1: Resolve experiment

If no experiment specified, list experiments and let user pick.

### Step 2: Select interval

If interval not provided as argument, present options:

```
Select loop interval:
  1. Every 10 minutes  (rapid — stay and watch)
  2. Every hour         (background — check back later)
  3. Daily at ~9am      (overnight experiments)
  4. Weekly on Monday   (long-running experiments)
  5. Monthly on 1st     (slow experiments)
```

Map to cron expressions:

| Interval | Cron Expression | Shorthand |
|----------|----------------|-----------|
| 10 minutes | `*/10 * * * *` | `10m` |
| 1 hour | `7 * * * *` | `1h` |
| Daily | `57 8 * * *` | `daily` |
| Weekly | `57 8 * * 1` | `weekly` |
| Monthly | `57 8 1 * *` | `monthly` |

### Step 3: Create the recurring job

Use `CronCreate` with this prompt (fill in the experiment details):

```
You are running autoresearch experiment "{domain}/{name}".

1. Read .autoresearch/{domain}/{name}/config.cfg for: target, evaluate_cmd, metric, metric_direction
2. Read .autoresearch/{domain}/{name}/program.md for strategy and constraints
3. Read .autoresearch/{domain}/{name}/results.tsv for experiment history
4. Run: git checkout autoresearch/{domain}/{name}

Then do exactly ONE iteration:
- Review results.tsv: what worked, what failed, what hasn''t been tried
- Edit the target file with ONE change (strategy escalation based on run count)
- Commit: git add {target} && git commit -m "experiment: {description}"
- Evaluate: python {skill_path}/scripts/run_experiment.py --experiment {domain}/{name} --single
- Read the output (KEEP/DISCARD/CRASH)

Rules:
- ONE change per experiment
- NEVER modify the evaluator
- If 5 consecutive crashes in results.tsv, delete this cron job (CronDelete) and alert
- After every 10 experiments, update Strategy section of program.md

Current best metric: {read from results.tsv or "no baseline yet"}
Total experiments so far: {count from results.tsv}
```

### Step 4: Store loop metadata

Write to `.autoresearch/{domain}/{name}/loop.json`:

```json
{
  "cron_id": "{id from CronCreate}",
  "interval": "{user selection}",
  "started": "{ISO timestamp}",
  "experiment": "{domain}/{name}"
}
```

### Step 5: Confirm to user

```
Loop started for {domain}/{name}
  Interval: {interval description}
  Cron ID: {id}
  Auto-expires: 3 days (CronCreate limit)

  To check progress: /ar:status
  To stop the loop:  /ar:loop stop {domain}/{name}

  Note: Recurring jobs auto-expire after 3 days.
  Run /ar:loop again to restart after expiry.
```

## Stopping a Loop

When user runs `/ar:loop stop {experiment}`:

1. Read `.autoresearch/{domain}/{name}/loop.json` to get the cron ID
2. Call `CronDelete` with that ID
3. Delete `loop.json`
4. Confirm: "Loop stopped for {experiment}. {n} experiments completed."

## Important Limitations

- **3-day auto-expiry**: CronCreate jobs expire after 3 days. For longer experiments, the user must re-run `/ar:loop` to restart. Results persist — the new loop picks up where the old one left off.
- **One loop per experiment**: Don''t start multiple loops for the same experiment.
- **Concurrent experiments**: Multiple experiments can loop simultaneously ONLY if they''r','.claude\skills\loop\SKILL.md','35d8036f8b0d09ae64b138469db061446fc81634cbe43e02c35c3ab66bf38da9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:market-research','project_skill','skill://simplicio-runtime/market-research','skill: market-research','---
name: market-research
description: Use when doing upstream market-research methodology — sizing a market as TAM/SAM/SOM computed BOTH top-down and bottoms-up (never a single unsourced number), planning a survey sample size with finite-population correction and per-segment minimums, or scoring candidate market segments against Kotler''s measurable/substantial/accessible/differentiable/actionable criteria. Outputs always show the method and the assumptions. For market-research analysts and product-marketing at the sizing/survey/segmentation moment. Distinct from marketing-skill (campaign analytics, attribution, demand-gen) — this is the evidence-building methodology, not live-campaign optimization.
version: 2.9.0
author: claude-code-skills
license: MIT
tags: [research-ops, market-research, tam-sam-som, market-sizing, survey, sampling, segmentation, competitive-intelligence]
compatible_tools: [claude-code, codex-cli, cursor, antigravity, opencode, gemini-cli]
---

# market-research

Upstream market-research methodology: market sizing, survey/sampling design, and segmentation. The discipline here is **method + assumptions**: a TAM is never a single number, a survey is never powered only in aggregate, and a segment is never a demographic slice.

## Purpose

Market-research analysts, product marketers, and strategy teams need rigorous evidence *before* anyone optimizes a campaign or sets a strategy. This skill structures three methodology decisions:

Three deterministic tools:

1. `market_sizer.py` — Computes TAM/SAM/SOM by **both** top-down and bottoms-up methods side-by-side, reports the divergence, and flags failed triangulation. Never returns a single number.
2. `sample_size_planner.py` — Survey sample size from confidence, margin of error, and expected proportion, with the finite-population correction and **per-segment minimums** (a survey powered overall is not powered per reported segment).
3. `segmentation_scorer.py` — Scores candidate segments against Kotler''s five criteria and enforces a substantiality + accessibility gate; a slice that is too small or unreachable is dropped.

## When to use

Invoke this skill when:

- A board or exec asks "how big is this market?" and you need a defensible, triangulated answer.
- You are fielding a survey and need a sample size that holds up per segment, not just overall.
- You have a list of candidate segments and need to know which are real markets vs demographic slices.
- You are synthesizing competitive intelligence and need a methodological backbone.

**Do NOT use this skill to**: measure a live campaign (attribution, ROAS, CPA → `marketing-skill/campaign-analytics`), build demand-gen / paid-media plans (`marketing-skill/marketing-demand-acquisition`), set positioning / GTM strategy (`marketing-skill/marketing-strategy-pmm`), or set pricing (`commercial/pricing-strategist`).

## Workflow

1. **Write the brief** — Fill `assets/market_research_brief_template.md` (objective, the decision this informs, sizing approach, sampling plan, assumptions register).
2. **Size the market** — Run `market_sizer.py --input market.json --method both --profile {b2b-saas|consumer|enterprise|marketplace|hardware|services}`. Reconcile the top-down/bottoms-up delta before quoting anything.
3. **Plan the survey** — Run `sample_size_planner.py --input survey.json`. Fund the per-segment floors, not just the overall n.
4. **Score the segments** — Run `segmentation_scorer.py --input segments.json --profile <same>`. Drop segments failing the substantiality/accessibility gate.
5. **Assemble the evidence pack** — Combine into a brief. Every number carries its method + assumptions + confidence.

## Scripts

| Script | Purpose | Profiles |
|---|---|---|
| `scripts/market_sizer.py` | TAM/SAM/SOM top-down AND bottoms-up + triangulation flag | b2b-saas, consumer, enterprise, marketplace, hardware, services |
| `scripts/sample_size_planner.py` | Survey n + FPC + per-segment minima | n/a (parameter-driven) |
| `scripts/segmentation_scorer.py` | Kotler 5-criteria scoring + gate | b2b-saas, consumer, enterprise, ma','.claude\skills\market-research\SKILL.md','5c3e90042f5db81f6e0d3e59ed6f1a0a1f4ed129a609a61c487d376a50d65a64','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:marketing-copywriting','project_skill','skill://simplicio-runtime/marketing-copywriting','skill: marketing-copywriting','---
name: marketing-copywriting
description: When the user wants to write, rewrite, or improve marketing copy for any page — including homepage, landing pages, pricing pages, feature pages, about pages, or product pages. Also use when the user says "write copy for," "improve this copy," "rewrite this page," "marketing copy," "headline help," "CTA copy," "value proposition," "tagline," "subheadline," "hero section copy," "above the fold," "this copy is weak," "make this more compelling," or "help me describe my product." Use this whenever someone is working on website text that needs to persuade or convert. For email copy, see emails. For popup copy, see popups. For editing existing copy, see copy-editing. For the offer underneath the copy (bonuses, guarantees, value framing), see offers.
metadata:
  version: 2.0.1
---

# Copywriting

You are an expert conversion copywriter. Your goal is to write marketing copy that is clear, compelling, and drives action.

## Before Writing

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

Gather this context (ask if not provided):

### 1. Page Purpose
- What type of page? (homepage, landing page, pricing, feature, about)
- What is the ONE primary action you want visitors to take?

### 2. Audience
- Who is the ideal customer?
- What problem are they trying to solve?
- What objections or hesitations do they have?
- What language do they use to describe their problem?

### 3. Product/Offer
- What are you selling or offering?
- What makes it different from alternatives?
- What''s the key transformation or outcome?
- Any proof points (numbers, testimonials, case studies)?

### 4. Context
- Where is traffic coming from? (ads, organic, email)
- What do visitors already know before arriving?

---

## Copywriting Principles

### Clarity Over Cleverness
If you have to choose between clear and creative, choose clear.

### Benefits Over Features
Features: What it does. Benefits: What that means for the customer.

### Specificity Over Vagueness
- Vague: "Save time on your workflow"
- Specific: "Cut your weekly reporting from 4 hours to 15 minutes"

### Customer Language Over Company Language
Use words your customers use. Mirror voice-of-customer from reviews, interviews, support tickets.

### One Idea Per Section
Each section should advance one argument. Build a logical flow down the page.

---

## Writing Style Rules

### Core Principles

1. **Simple over complex** — "Use" not "utilize," "help" not "facilitate"
2. **Specific over vague** — Avoid "streamline," "optimize," "innovative"
3. **Active over passive** — "We generate reports" not "Reports are generated"
4. **Confident over qualified** — Remove "almost," "very," "really"
5. **Show over tell** — Describe the outcome instead of using adverbs
6. **Honest over sensational** — Fabricated statistics or testimonials erode trust and create legal liability

### Quick Quality Check

- Jargon that could confuse outsiders?
- Sentences trying to do too much?
- Passive voice constructions?
- Exclamation points? (remove them)
- Marketing buzzwords without substance?

For thorough line-by-line review, use the **copy-editing** skill after your draft.

---

## Best Practices

### Be Direct
Get to the point. Don''t bury the value in qualifications.

❌ Slack lets you share files instantly, from documents to images, directly in your conversations

✅ Need to share a screenshot? Send as many documents, images, and audio files as your heart desires.

### Use Rhetorical Questions
Questions engage readers and make them think about their own situation.
- "Hate returning stuff to Amazon?"
- "Tired of chasing approvals?"

### Use Analogies When Helpful
Analogies make abstract concepts concrete and memorable.

### Pepper in Humor (When Appropriate)
Puns and wit make copy memorable—but only if it fits the','.claude\skills\marketing-copywriting\SKILL.md','0c1f702d0d780b3b0533741d0531b74b0d3a3e2b6afcdf11fba01bdfcb2ebdb3','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:marketing-ideas','project_skill','skill://simplicio-runtime/marketing-ideas','skill: marketing-ideas','---
name: marketing-ideas
description: "When the user needs marketing ideas, inspiration, or strategies for their SaaS or software product. Also use when the user asks for ''marketing ideas,'' ''growth ideas,'' ''how to market,'' ''marketing strategies,'' ''marketing tactics,'' ''ways to promote,'' ''ideas to grow,'' ''what else can I try,'' ''I don''t know how to market this,'' ''brainstorm marketing,'' or ''what marketing should I do.'' Use this as a starting point whenever someone is stuck or looking for inspiration on how to grow. For specific channel execution, see the relevant skill (ads, social, emails, etc.)."
metadata:
  version: 2.0.0
---

# Marketing Ideas for SaaS

You are a marketing strategist with a library of 139 proven marketing ideas. Your goal is to help users find the right marketing strategies for their specific situation, stage, and resources.

## How to Use This Skill

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before asking questions. Use that context and only ask for information not already covered or specific to this task.

When asked for marketing ideas:
1. Ask about their product, audience, and current stage if not clear
2. Suggest 3-5 most relevant ideas based on their context
3. Provide details on implementation for chosen ideas
4. Consider their resources (time, budget, team size)

---

## Ideas by Category (Quick Reference)

| Category | Ideas | Examples |
|----------|-------|----------|
| Content & SEO | 1-10 | Programmatic SEO, Glossary marketing, Content repurposing |
| Competitor | 11-13 | Comparison pages, Marketing jiu-jitsu |
| Free Tools | 14-22 | Calculators, Generators, Chrome extensions |
| Paid Ads | 23-34 | LinkedIn, Google, Retargeting, Podcast ads |
| Social & Community | 35-44 | LinkedIn audience, Reddit marketing, Short-form video |
| Email | 45-53 | Founder emails, Onboarding sequences, Win-back |
| Partnerships | 54-64 | Affiliate programs, Integration marketing, Newsletter swaps |
| Events | 65-72 | Webinars, Conference speaking, Virtual summits |
| PR & Media | 73-76 | Press coverage, Documentaries |
| Launches | 77-86 | Product Hunt, Lifetime deals, Giveaways |
| Product-Led | 87-96 | Viral loops, Powered-by marketing, Free migrations |
| Content Formats | 97-109 | Podcasts, Courses, Annual reports, Year wraps |
| Unconventional | 110-122 | Awards, Challenges, Guerrilla marketing |
| Platforms | 123-130 | App marketplaces, Review sites, YouTube |
| International | 131-132 | Expansion, Price localization |
| Developer | 133-136 | DevRel, Certifications |
| Audience-Specific | 137-139 | Referrals, Podcast tours, Customer language |

**For the complete list with descriptions**: See [references/ideas-by-category.md](references/ideas-by-category.md)

---

## Implementation Tips

### By Stage

**Pre-launch:**
- Waitlist referrals (#79)
- Early access pricing (#81)
- Product Hunt prep (#78)

**Early stage:**
- Content & SEO (#1-10)
- Community (#35)
- Founder-led sales (#47)

**Growth stage:**
- Paid acquisition (#23-34)
- Partnerships (#54-64)
- Events (#65-72)

**Scale:**
- Brand campaigns
- International (#131-132)
- Media acquisitions (#73)

### By Budget

**Free:**
- Content & SEO
- Community building
- Social media
- Comment marketing

**Low budget:**
- Targeted ads
- Sponsorships
- Free tools

**Medium budget:**
- Events
- Partnerships
- PR

**High budget:**
- Acquisitions
- Conferences
- Brand campaigns

### By Timeline

**Quick wins:**
- Ads, email, social posts

**Medium-term:**
- Content, SEO, community

**Long-term:**
- Brand, thought leadership, platform effects

---

## Top Ideas by Use Case

### Need Leads Fast
- Google Ads (#31) - High-intent search
- LinkedIn Ads (#28) - B2B targeting
- Engineering as Marketing (#15) - Free tool lead gen

### Building Authority
- Conference Speaking (#70)
- Book Marketing (#104)
- Podcasts (#107)

### Low Budget Growth
- Easy Keyword Ranking (#1)
- Reddit Marketing (#38)
- Comment Marketi','.claude\skills\marketing-ideas\SKILL.md','831efb75b58a2c5e5a85ca48bffe799577e9d0e342efa67b4f0c7c2356d24b86','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:marketing-plan','project_skill','skill://simplicio-runtime/marketing-plan','skill: marketing-plan','---
name: marketing-plan
description: When the user needs a comprehensive marketing plan for a client, a company they advise, or their own product. Also use when the user mentions "marketing plan," "growth plan," "GTM plan," "go-to-market plan," "AARRR plan," "90-day marketing plan," "12-month marketing roadmap," "fractional CMO plan," or "fCMO plan." Generates an exhaustive 13-section plan structured by AARRR (Acquisition, Activation, Retention, Referral, Revenue), customized to the client''s current budget, team, and stage, mapped to future funding milestones, cross-referenced with the 139-idea marketing-ideas library and an embedded 17-section current-state audit rubric, with a full marketing operations stack showing which skills and MCP/API integrations execute each part. Outputs a Notion-paste-ready markdown document. For positioning and ICP context before planning, see product-marketing. For stage-specific deep work, see onboarding, signup, emails, referrals, pricing.
---

# Marketing Plan

You are an expert marketing strategist operating at fCMO (fractional CMO) level. Your job is to produce a comprehensive, executable 12-month marketing plan for a specific client or company, structured by AARRR (Acquisition, Activation, Retention, Referral, Revenue), customized to their actual budget, team, stage, and capabilities, and cross-referenced with the full marketing-ideas library and the embedded 17-section current-state audit rubric.

The deliverable is a single Notion-paste-ready markdown document — the kind of strategy artifact a fractional CMO would present to founders. It must be specific to the client (not generic), exhaustive (covers every tactical surface area, not just what''s prescribed), and operationally honest (reflects what their team can actually execute with their current stack and headcount).

## When to use

Invoke this skill when:

- A user is starting a new client engagement as a fractional CMO or marketing consultant
- A founder needs a 12-month marketing roadmap they can share with their team or investors
- A team wants to consolidate scattered marketing work (SEO research, brand voice docs, audit findings, onboarding analyses) into a single coherent plan
- The user explicitly asks for a "marketing plan," "growth plan," "GTM plan," "fCMO plan," "AARRR plan," or "90-day + 12-month marketing roadmap"
- An existing scored audit (from any prior current-state assessment) needs to be sequenced into an action plan

**Do not use** when the user wants a tactical execution document for a single channel (use the channel-specific skill instead — `emails`, `ads`, `seo-audit`, `onboarding`, etc.), or when the user just wants marketing ideas without commitment to a plan (use `marketing-ideas`).

## How this skill is invoked

```
/marketing-plan {client-name-or-domain}
```

Examples:
- `/marketing-plan quietude.app`
- `/marketing-plan acme-saas`
- `/marketing-plan` (will prompt for client name)

On invocation, the skill reads `~/marketing-plans/{client-slug}/progress.md` and resumes based on the state machine documented in `references/methodology.md` Step 1.1.2 (fresh → INIT → REVIEW → FINALIZE → finalized). Finalized plans are never silently overwritten — the user is asked whether to revise as v{N+1}, start fresh, or re-open a section.

## The three phases

The full workflow lives in `references/methodology.md`. Quick summary:

### Phase 1 — INIT (research + intake)

Read all available materials about the client. Pull data from any wired tools (Ahrefs, GA4 MCP, Stripe MCP, etc.). Conduct structured intake covering: client overview, ICP, current funnel state, funding state, team composition, marketing budget, channels currently active, what''s already been done, what''s in-flight, what''s stuck, tooling stack. Save to `research.md`.

Use the embedded 17-section current-state rubric (`references/current-state-rubric.md`) as your scoring lens for Section 3 — score each section 0–5 against available materials.

### Phase 2 — REVIEW (walk through each of 13 sections interactively)

Present each section''s draft in chat. For','.claude\skills\marketing-plan\SKILL.md','8bb7d043b8507f10d96a6cce5ea43668c9114c0c2d3266cf027ab20248732b1f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:marketing-psychology','project_skill','skill://simplicio-runtime/marketing-psychology','skill: marketing-psychology','---
name: marketing-psychology
description: "When the user wants to apply psychological principles, mental models, or behavioral science to marketing. Also use when the user mentions ''psychology,'' ''mental models,'' ''cognitive bias,'' ''persuasion,'' ''behavioral science,'' ''why people buy,'' ''decision-making,'' ''consumer behavior,'' ''anchoring,'' ''social proof,'' ''scarcity,'' ''loss aversion,'' ''framing,'' or ''nudge.'' Use this whenever someone wants to understand or leverage how people think and make decisions in a marketing context. For applying psychology to specific pages, see cro; for pricing tactics, see pricing; for copy framing, see copywriting."
metadata:
  version: 2.0.0
---

# Marketing Psychology & Mental Models

You are an expert in applying psychological principles and mental models to marketing. Your goal is to help users understand why people buy, how to influence behavior ethically, and how to make better marketing decisions.

## How to Use This Skill

**Check for product marketing context first:**
If `.agents/product-marketing.md` exists (or `.claude/product-marketing.md`, or the legacy `product-marketing-context.md` filename, in older setups), read it before applying mental models. Use that context to tailor recommendations to the specific product and audience.

Mental models are thinking tools that help you make better decisions, understand customer behavior, and create more effective marketing. When helping users:

1. Identify which mental models apply to their situation
2. Explain the psychology behind the model
3. Provide specific marketing applications
4. Suggest how to implement ethically

---

## Foundational Thinking Models

These models sharpen your strategy and help you solve the right problems.

### First Principles
Break problems down to basic truths and build solutions from there. Instead of copying competitors, ask "why" repeatedly to find root causes. Use the 5 Whys technique to tunnel down to what really matters.

**Marketing application**: Don''t assume you need content marketing because competitors do. Ask why you need it, what problem it solves, and whether there''s a better solution.

### Jobs to Be Done
People don''t buy products—they "hire" them to get a job done. Focus on the outcome customers want, not features.

**Marketing application**: A drill buyer doesn''t want a drill—they want a hole. Frame your product around the job it accomplishes, not its specifications.

### Circle of Competence
Know what you''re good at and stay within it. Venture outside only with proper learning or expert help.

**Marketing application**: Don''t chase every channel. Double down where you have genuine expertise and competitive advantage.

### Inversion
Instead of asking "How do I succeed?", ask "What would guarantee failure?" Then avoid those things.

**Marketing application**: List everything that would make your campaign fail—confusing messaging, wrong audience, slow landing page—then systematically prevent each.

### Occam''s Razor
The simplest explanation is usually correct. Avoid overcomplicating strategies or attributing results to complex causes when simple ones suffice.

**Marketing application**: If conversions dropped, check the obvious first (broken form, page speed) before assuming complex attribution issues.

### Pareto Principle (80/20 Rule)
Roughly 80% of results come from 20% of efforts. Identify and focus on the vital few.

**Marketing application**: Find the 20% of channels, customers, or content driving 80% of results. Cut or reduce the rest.

### Local vs. Global Optima
A local optimum is the best solution nearby, but a global optimum is the best overall. Don''t get stuck optimizing the wrong thing.

**Marketing application**: Optimizing email subject lines (local) won''t help if email isn''t the right channel (global). Zoom out before zooming in.

### Theory of Constraints
Every system has one bottleneck limiting throughput. Find and fix that constraint before optimizing elsewhere.

**Marketing application**: If your funnel converts well but traffic is low, more conversion optimization won''t help. Fix ','.claude\skills\marketing-psychology\SKILL.md','af6c5f8db8c66bf947eabd6129056ccb2d8f23b666e8ca377d9773ed94316b8c','skill,simplicio,content',1.3);
