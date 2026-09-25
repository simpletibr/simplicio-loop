---
title: Private Overlay Install
description: Install the starter into an existing host project without polluting its git history.
sidebar_position: 1
---
> Step-by-step guide to using LLM Project Mapper as a **private overlay** on top of an existing project (front-end Angular/React/Next, .NET API, monorepo, etc.). The starter files live **on the dev's disk** but **outside the host project's git** — each dev installs their own, the main repo is not polluted.
>
> If you want to run the starter as a standalone repo (direct clone, no host project), see [README.md](/quickstart/get-going). This guide is for **overlay**.

![Animated terminal screencast showing cd into host-project, npx llm-project-mapper, CLI prompts, and ls .specs/](/assets/overlay-install.svg)

> 🇧🇷 Portuguese version: [INSTALL.md](https://github.com/wesleysimplicio/llm-project-mapper/blob/main/INSTALL.md).

---

## TL;DR — 4 steps

1. **Download** llm-project-mapper into a temp directory.
2. **Copy** the contents (excluding `.git`) into the host project's root.
3. **Remove** the temp directory and any starter git traces.
4. **Add** the starter paths to the host's `.gitignore`.

Then run `bootstrap.sh` / `bootstrap.ps1` inside the host to fill placeholders and generate `.starter-meta.json`.

---

## Prerequisites

| Requirement | Purpose |
|---|---|
| Git | clone the starter |
| Bash 4+ or PowerShell 5.1+ | run the bootstrap |
| Node.js >= 16.7 (optional) | use `npx @wesleysimplicio/llm-project-mapper` instead of clone |

---

## Step 1 — Download the starter

### macOS / Linux / Git Bash / WSL

```bash
cd /tmp
git clone --depth=1 https://github.com/wesleysimplicio/llm-project-mapper.git llm-project-mapper-src
```

### Windows PowerShell

```powershell
cd $env:TEMP
git clone --depth=1 https://github.com/wesleysimplicio/llm-project-mapper.git llm-project-mapper-src
```

> Alternative without clone: `npx @wesleysimplicio/llm-project-mapper` inside the host (Steps 2 and 3 happen automatically). Skip to **Step 4** afterwards.

---

## Step 2 — Copy into the host project (without overwriting host files)

Assume the host project is `~/code/my-front` (Linux/macOS) or `C:\Users\me\source\my-front` (Windows).

> ⚠️ **Warning**: the starter ships files with common names (`README.md`, `package.json`, `playwright.config.ts`, `tests/`, `AGENTS.md`, `CLAUDE.md`, `INIT.md`, `.gitignore`). If the host already has any of these, **use `--ignore-existing` (rsync) or `/XC /XN /XO` (robocopy)** to never overwrite. The bootstrap later reads pre-existing files via `.starter-meta.json` and merges through `INIT.md`.

### macOS / Linux / Git Bash / WSL

```bash
cd ~/code/my-front

# copies everything from the starter except its .git, and NEVER overwrites host files
rsync -av --ignore-existing --exclude='.git' /tmp/llm-project-mapper-src/ ./
```

> If `rsync` is not installed, install it (`brew install rsync` / `sudo apt install rsync`). **Do not use `cp -R`** without overwrite protection.

### Windows PowerShell

Always use **double quotes** around paths (Windows may have spaces like `C:\Users\Wesley Simplicio\source`):

```powershell
cd "C:\Users\me\source\my-front"

# /E recursive; /XD .git excludes starter's .git;
# /XC /XN /XO skips files that already exist at destination (changed/newer/older).
robocopy "$env:TEMP\llm-project-mapper-src" "." /E /XD .git /XC /XN /XO
# robocopy returns 0-7 as success; code 1 = files copied, OK.
```

---

## Step 3 — Clean up starter git traces

Ensures the host repo does **not** become a clone of llm-project-mapper.

> `--exclude='.git'` on `rsync` (Step 2) and `/XD .git` on `robocopy` already prevent the starter's `.git` from being copied. This step is just validation + temp dir cleanup.

### macOS / Linux / Git Bash / WSL

```bash
cd ~/code/my-front

# delete the starter temp directory
rm -rf /tmp/llm-project-mapper-src

# confirm there is NO remote pointing at the starter repo
git remote -v
# if something like 'origin → wesleysimplicio/llm-project-mapper' appears,
# the starter's .git was copied by mistake.
# DO NOT blindly run rm -rf .git — you might be deleting the HOST's git.
# Instead:
#   1. Check the host has its own commits:  git log --oneline -5
#   2. If the log is only the starter's, remove the remote:  git remote remove origin
#   3. If host commits are interleaved, ask for manual help.
```

### Windows PowerShell

```powershell
cd "C:\Users\me\source\my-front"

Remove-Item -Recurse -Force "$env:TEMP\llm-project-mapper-src"

# check remotes
git remote -v
# same principle: if it points at the starter, investigate before deleting anything.
```

---

## Step 4 — Add the starter to the host's `.gitignore`

Paste the block below at the end of the host's `.gitignore` to keep the overlay out of the host's git:

```gitignore
# === LLM Project Mapper (private overlay, per-dev) — do not commit on host repo ===
# LLM Project Mapper tracked files
.starter-meta.json
.claude/settings.local.json
AGENTS.md
CLAUDE.md
INIT.md
INIT.en.md
_BOOTSTRAP.md
.agents/
.agents/**
.claude/
.claude/**
.codex/
.codex/**
.github/
.github/**
.skills/
.skills/**
.specs/
.specs/**
docs/**
scripts/**
playwright-report/**
tests/**
test-results/**
coverage/**
bootstrap.ps1
bootstrap.sh
playwright.config.ts
```

> If any of these files is already tracked by the host's git, the file stays on disk and in history but new changes may become less obvious in daily workflow. Before using as a private overlay, confirm with `git ls-files <file>` when in doubt.

### Collision behavior

Because **Step 2 uses `--ignore-existing`**, no host file gets overwritten by the copy. Per-file behavior:

| Starter file | If host already has it | Result |
|---|---|---|
| `README.md` | yes | starter does NOT copy; host stays as-is |
| `package.json` | yes | starter does NOT copy; host stays as-is |
| `playwright.config.ts` | yes | starter does NOT copy |
| `tests/` | yes | starter does NOT merge individual existing files |
| `AGENTS.md` / `CLAUDE.md` / `INIT.md` | yes | starter does NOT copy. Bootstrap registers in `.starter-meta.json -> existing_instruction_files`; `INIT.md` reads and **merges** preserving host content |
| `.gitignore` | yes | starter does NOT overwrite. Bootstrap only **appends** at the end with a marker header (only if you answer `yes` at the prompt) |
| `.github/workflows/` | yes | starter does NOT overwrite existing workflows; only adds `dod.yml` if there is no name clash |

> You will never have "two `package.json` files" — `rsync --ignore-existing` / `robocopy /XC /XN /XO` skip files that already exist.

---

## Step 5 — Run bootstrap inside the host

Replaces placeholders (`<PRODUCT_NAME>`, `<STACK>`) with real values detected from the host and generates `.starter-meta.json`.

### macOS / Linux / Git Bash / WSL

```bash
cd ~/code/my-front
chmod +x ./bootstrap.sh
./bootstrap.sh
```

### Windows PowerShell

```powershell
cd "C:\Users\me\source\my-front"

# PowerShell 7+
pwsh -File .\bootstrap.ps1

# PowerShell 5.1 (Windows 10/11)
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

> Windows does not need `chmod` — PowerShell does not use an executable bit. Just invoke the `.ps1` directly.

### Non-interactive (CI / script)

```bash
./bootstrap.sh --yes --cli skip --append-gitignore no
```

> In overlay mode with `.gitignore` already containing the starter block, answer **no** when the bootstrap asks whether to append. Starter files are already ignored by your block — the bootstrap's block (which targets standalone use) is not needed.

---

## Step 6 — Confirm the host's git is clean

```bash
git status
```

Expected: no starter file appears as untracked/modified. If any appears, adjust `.gitignore` to cover it.

---

## Updating the starter later

When a new version of llm-project-mapper ships:

```bash
# fetch the new version
cd /tmp
rm -rf llm-project-mapper-src
git clone --depth=1 https://github.com/wesleysimplicio/llm-project-mapper.git llm-project-mapper-src

# repeat Step 2 — rsync keeps your specifics
cd ~/code/my-front
rsync -av --exclude='.git' --exclude='.specs/product' --exclude='.specs/architecture' --exclude='.specs/sprints' /tmp/llm-project-mapper-src/ ./
```

The `--exclude`s preserve content **you** wrote in `.specs/` (vision, ADRs, sprints). Adapt if you customized other folders.

---

## Uninstall the starter (overlay)

```bash
cd ~/code/my-front

# safe files (no host collisions)
rm -rf .agents .skills .specs .claude .codex bin
rm -f _BOOTSTRAP.md INSTALL.md INSTALL.en.md .starter-meta.json
rm -f bootstrap.sh bootstrap.ps1
rm -rf .github/copilot presentation video
rm -f .github/copilot-instructions.md .github/workflows/dod.yml

# starter files ONLY if you confirmed they are NOT host files
# (same list commented out in .gitignore — verify first)
# rm -f AGENTS.md CLAUDE.md INIT.md INIT.en.md README.pt-BR.md
# rm -f playwright.config.ts
# rm -rf tests/ presentation/ video/

# remove the "LLM Project Mapper (private overlay)" block from .gitignore manually
```

No `git rm` involved — those files were gitignored and never committed.

---

## When NOT to use private overlay

If your **entire team** is going to use the agents and you want skills/specs/agents shared:

- Do not gitignore the starter files.
- Commit `.agents/`, `.skills/`, `.specs/`, `AGENTS.md`, `CLAUDE.md`, `INIT.md`, `.github/copilot*` in the host repo.
- Keep `.claude/sessions`, `.claude/cache`, `.codex/local`, `.codex/history`, `.starter-meta.json` in `.gitignore` (per-dev local state, not shared).

The recommended block for that case (shared mode) is what `bootstrap.sh --append-gitignore yes` already adds — just that, without the "private overlay" block above.

---

## Quick decision

| Scenario | Mode |
|---|---|
| I am the only dev using agents on this project | **Private overlay** (this guide) |
| I want to test before committing for the team | **Private overlay** first |
| Whole team will work with agents | **Shared** (commit in host repo) |
| Brand-new project, agents from day 1 | **Standalone** — clone llm-project-mapper directly, no overlay |

---

## Next steps

1. Verify `git status` is clean on the host.
2. Open your favorite agent CLI/IDE inside the host folder.
3. Ask the agent to read `INIT.md` (or `INIT.en.md`), or run the handoff the bootstrap configured.
4. The agent will infer VISION/DOMAIN/PERSONAS from the host's code and write to `.specs/`.
5. The first technical task goes through the mandatory loop in `AGENTS.md`.
