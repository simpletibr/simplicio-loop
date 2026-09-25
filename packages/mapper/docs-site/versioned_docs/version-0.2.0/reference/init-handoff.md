---
title: INIT Handoff Contract
description: The initialization contract that agents follow after bootstrap.
sidebar_position: 2
---
> You are the **init agent**. The human has just run `./bootstrap.sh` (or `pwsh ./bootstrap.ps1`, or `npx @wesleysimplicio/llm-project-mapper`).
> Your job: complete the setup by **reading the real project**, **asking only what is missing** and **merging** what already exists — never destroying the human's content.
>
> CLIs with a native agent loop: **Claude Code**, **Codex CLI**, **Cursor Agent**, **Hermes Agent**, **OpenClaw**, **Aider** (Deepseek/Kimi/MiniMax/GLM via `--model`).
> No native loop (paste prompt manually): **GitHub Copilot CLI**.

> 🇧🇷 Portuguese version: [INIT.md](https://github.com/wesleysimplicio/llm-project-mapper/blob/main/INIT.md).

---

## Rule zero — destroy nothing

Before any Write/Edit, read `.starter-meta.json` at the repo root. It is the contract between `bootstrap` and you.

```jsonc
{
  "product_name": "...",
  "team": "...",
  "domain": "...",
  "stack": "...",
  "bootstrapped_at": "2026-05-08T19:45:00Z",
  "starter_version": "0.2.0",
  "existing_instruction_files": [".github/copilot-instructions.md"],
  "init_must_ask":   ["team", "domain", "vision_oneliner", "primary_personas"],
  "init_must_merge": [".github/copilot-instructions.md"],
  "read_only_globs": ["**/*.razor", "**/*.cs", "package.json", "..."]
}
```

Three non-negotiable rules derived from that file:

1. **`read_only_globs`** — No file matching these globs may appear in `git diff`. You read them, you do **not** write. If you need information from one, paraphrase it into `.specs/`; never touch the original.
2. **`init_must_merge`** — For each path: **read** the current content, **preserve the essence**, **merge** with our standard structure. Never rewrite from scratch.
3. **`init_must_ask`** — Ask the human **only** for these fields. Everything else (`product_name`, `stack`) was auto-detected.

---

## Where you may write (whitelist)

Only these paths are "starter-managed". Anything outside is the human's territory — do not touch.

```
.specs/**          .agents/**         .skills/**
.claude/**         .codex/**
.github/copilot-instructions.md
.github/copilot/**
.github/PULL_REQUEST_TEMPLATE.md
.github/ISSUE_TEMPLATE/**
.github/workflows/ci.yml
.github/workflows/dod.yml
AGENTS.md          CLAUDE.md          README.md          README.pt-BR.md
playwright.config.ts (only if missing or still our template)
```

Path outside this whitelist **and** not part of the original template = do not write.

---

## Flow (5 phases — parallelize everything you can)

### Phase 1 — Read `.starter-meta.json` and ask only what is missing

1. `Read .starter-meta.json`. If missing, abort and tell the human to run `./bootstrap.sh` first.
2. For each item in `init_must_ask`, ask the human **in a single message** (not one by one):
   - **`team`** — Which team owns this? (suggestion: `<meta.team value>`)
   - **`domain`** — Business domain in 1-3 words? (suggestion: `<meta.domain value>`)
   - **`vision_oneliner`** — In one sentence, what problem does this product solve and for whom?
   - **`primary_personas`** — Who uses it? (2-4 roles, e.g. `operations admin`, `end customer`, `financial analyst`)
3. Persist answers by updating `.starter-meta.json` (add/overwrite `team`, `domain`, `vision_oneliner`, `primary_personas`).
4. If the human leaves something unanswered, mark `**TODO: human to fill**` in the doc and move on.

### Phase 2 — Inspection (1 dedicated agent, parallel with the start of phase 3)

Spawn `@inspector` (sub-agent `Explore` or `general-purpose`):

- Read `.starter-meta.json` to know the stack.
- Map top-level folders (`ls -la`, `find . -maxdepth 2 -type d`).
- Read the original `README.md` (if it exists and is not our template) — extract description, badges, commands. **Do not modify.**
- Detect entities by stack convention:
  - **Node/TS** → `**/models/**`, `**/entities/**`, `**/types/**`, `**/schemas/**`, `**/*.dto.ts`
  - **.NET** → `**/Models/**`, `**/Entities/**`, `**/DTOs/**`, `**/*.cs` with `[Table]`/`[Key]`
  - **Python** → `**/models.py`, `**/schemas.py`, `**/entities/**`, `BaseModel`/`SQLAlchemy` classes
  - **Go** → `**/models/**`, structs with `db:` or `json:` tags
  - **Rust** → `**/models.rs`, structs with `#[derive(Serialize)]`
  - **Flutter** → `lib/models/**`, `freezed`/`json_serializable` classes
  - **PHP/Laravel** → `app/Models/**`
  - **Ruby** → `app/models/**`
- Detect external integrations: imports of `axios`/`fetch`/`HttpClient`/`requests`/`reqwest`, env vars (`*_URL`, `*_KEY`, `*_TOKEN`), connection strings.
- Detect real scripts/commands: `package.json` `scripts`, `Makefile`, `composer.json` `scripts`, `pyproject.toml` `[tool.poetry.scripts]`, `*.csproj` targets.
- TODO/FIXME/HACK in production code (exclude `node_modules`/`vendor`/`dist`/`build`).
- Open issues via `gh issue list --limit 50` if `gh` is authenticated.

**Inspector output** — markdown report saved at `.specs/journal/inspection-<YYYY-MM-DD>.md` with sections:
`Real stack`, `Folder structure`, `Detected entities`, `Useful commands`, `Integrations`, `TODOs found`, `Open issues`.

### Phase 3 — Parallel fill (6 agents in a single message)

After phase 1 (answers received) and with phase 2 already running, dispatch **in parallel** (one message, multiple `Agent` calls):

| Agent | Output | Input |
|---|---|---|
| `@vision-writer` | `.specs/product/VISION.md` | `vision_oneliner` + original README + description from `package.json`/`*.csproj`/`pyproject.toml` |
| `@domain-mapper` | `.specs/product/DOMAIN.md` (Mermaid `erDiagram`) | entities detected by inspector |
| `@personas-writer` | `.specs/product/PERSONAS.md` | `primary_personas` + roles/permissions detected in code |
| `@design-mapper` | `.specs/architecture/DESIGN.md` (Mermaid with real boundaries) | folder structure + integrations + frameworks |
| `@patterns-extractor` | `.specs/architecture/PATTERNS.md` | naming/structure/conventions **actually observed** in code (do not invent) |
| `@backlog-collector` | `.specs/sprints/BACKLOG.md` | TODOs + open issues from `gh` |

### Phase 4 — Merge pre-existing files (sequential — uses phase 3 context)

For **each path** in `init_must_merge`:

1. `Read` the human's existing file.
2. Identify the **essence**: important commands, project-specific rules, internal links, glossary, contacts, compliance constraints.
3. Compose a new file with the starter's **template** structure (Stack / Commands / Workflow / DoD / Patterns / Where to find context / Forbidden / Skills / Custom agents) **plus** a `## Preserved content from <original-name>` section at the end with the human's essence.
4. `Write` to the same path. The resulting diff must be **additive enrichment**, never removing what the human wrote.
5. **Mirroring is mandatory:** if you edited `AGENTS.md`, replicate the same change in `CLAUDE.md` and `.github/copilot-instructions.md`. The three stay aligned (or symlink: `ln -sf AGENTS.md CLAUDE.md`).

### Phase 5 — Update real commands and validate

1. **`@instruction-updater`** — updates `AGENTS.md`/`CLAUDE.md`/`.github/copilot-instructions.md`:
   - Replace the `## Important commands` section with **real** commands extracted by the inspector (no placeholders).
   - Add links to docs filled in `.specs/`.
   - Add `## Available skills/agents` listing what exists in `.skills/` and `.agents/`.

2. **DoD checks**:
   - Every tree file exists (`AGENTS.md`, `CLAUDE.md`, `.specs/{product,architecture,workflow,sprints}/...`).
   - No `<PRODUCT_NAME>`/`<TEAM>`/`<DOMAIN>`/`<STACK>` placeholders left in starter-managed paths.
   - Mermaid blocks are syntactically valid (no accents in IDs; labels with spaces wrapped in quotes).
   - No meaningful doc below 30 useful lines.
   - **Critical check:** `git status` must **not** list any file matching `read_only_globs`. If it does, something escaped — revert with `git checkout -- <file>`.

3. **Report to the human**:
   - Files filled (list).
   - Top 5 detected entities.
   - Commands identified.
   - What remained as **TODO: human to fill**.
   - Suggested next action (create `sprint-01/SPRINT.md`, open the first ADR, configure branch protection, etc.).

---

## Optional cleanup

Ask the human:

> "Delete `_BOOTSTRAP.md`, `INIT.md`, `bootstrap.sh`, `bootstrap.ps1` now? (y/N)"

If `y`:

```bash
rm _BOOTSTRAP.md INIT.md bootstrap.sh bootstrap.ps1
git add -A
git commit -m "chore: remove starter bootstrap files after init"
```

Keep `.starter-meta.json` (future reference).

---

## Execution rules

- **Language**: generated content in **English**. Code (vars/functions/classes), commits, identifiers: **English**.
- **Never invent** — if the code cannot give you certain info, mark **`TODO: human to fill`** explicitly.
- **Concrete > generic** — use real names (entities, routes, project commands), not placeholders.
- **No emojis** in source code.
- **Valid Mermaid** — IDs without accents; labels with spaces in quotes (`["Order Service"]`).
- **Aggressive parallelism** — any independent work goes in a single message with multiple `Agent` calls.
- **Read-only is law** — any file matching `read_only_globs` is untouchable. If it appears in `git diff`, revert.
- **Merging is the rule for `init_must_merge`** — never rewrite from scratch, always compose on top.
- **No new dependencies** without asking.

---

## Final agent checklist

- [ ] `.starter-meta.json` read and updated with the human's answers.
- [ ] `init_must_ask` asked **once**, in a single message.
- [ ] Inspector ran and produced a report with real entities/commands/integrations.
- [ ] 6 docs in `.specs/` filled with real info (not placeholders).
- [ ] `init_must_merge` merged with the essence preserved.
- [ ] `AGENTS.md` ↔ `CLAUDE.md` ↔ `.github/copilot-instructions.md` aligned.
- [ ] `git status` does not list any file from `read_only_globs`.
- [ ] No `<PRODUCT_NAME>`/`<STACK>`/`<TEAM>`/`<DOMAIN>` placeholders left in starter paths.
- [ ] Summary delivered to the human: files, entities, commands, TODOs, next action.

---

**INIT.md is disposable after a single run. No config lives here — config lives in `.specs/`.**
