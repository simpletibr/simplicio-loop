# 🔁 simplicio-loop

<p align="center">
  <a href="docs/REPOSITORY_GOVERNANCE.md"><img src="https://img.shields.io/badge/CI-local%20gate%20is%20authoritative-888888" alt="Validation status: the local scripts/check.py gate is authoritative; GitHub Actions is not required evidence"></a>
  <a href="https://github.com/simpletibr/simplicio-loop/stargazers"><img src="https://img.shields.io/github/stars/simpletibr/simplicio-loop?style=social" alt="Stars"></a>
  <a href="docs/EXTENSION_POINTS_SERVICE.md"><img src="https://img.shields.io/badge/extension%20points-50-00E08A" alt="50 extension points"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="https://discord.gg/wM6tr7xVb"><img src="https://img.shields.io/badge/Discord-Join%20Simplicio-5865F2?logo=discord&logoColor=white" alt="Join the Simplicio Discord"></a>
</p>

<p align="center">
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

**simplicio-loop turns GitHub issues into tested PRs: it maps the repo, an AI plans, a deterministic editor applies, tests verify, squads review.**

<p align="center">
  <img src="docs/assets/readme/overview-cartoon.webp" alt="Animated flow in 8 steps: issues, intake, general coordinator, squads, workers (mapper, plan, dev-cli), squad review, merge train, main and the Simplicio Live kanban" width="100%" />
</p>

<p align="center">
  <img src="docs/assets/readme/how-it-works.webp" alt="Animated flow in 8 steps: issues, intake, general coordinator, squads, workers (mapper, plan, dev-cli), squad review, merge train, main and the Simplicio Live kanban" width="100%" />
</p>

## What it does

```mermaid
flowchart LR
  I["GitHub issue"] --> M["simplicio-mapper<br/>maps files, symbols, tests"]
  M -->|"map slice"| P["Planner in a sandbox<br/>claude / codex / grok / gemini<br/>plans, never writes"]
  P -->|"JSON plan"| D["simplicio-dev-cli<br/>deterministic apply"]
  D --> T["tests verify<br/>simplicio-loop turbo --apply - --verify"]
  T -->|"green"| S["secret scan"] --> PR["PR with evidence"]
  T -.->|"2 failures"| E["escalate the model role"] -.-> P
```

## Install

Needs Python 3.11+, `git`, and an authenticated `gh` for GitHub issues.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop login              # sign in; shares the login with simplicio-runtime
simplicio-loop doctor             # check the installed stack
```

## Use it

**In Claude Code or VS Code:**

```text
/simplicio-loop finish all the open issues
```

```mermaid
flowchart LR
  A["1. You write /simplicio-loop and the goal"] --> B["2. Mapper maps, planner plans, dev-cli applies, tests verify"]
  B --> C["3. PR with evidence"]
```

**As a 24/7 watcher** (a service that watches `simpletibr/simplicio-*` repos and opens PRs):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

```mermaid
flowchart LR
  R["repo opts in<br/>.simplicio/loop.toml<br/>enabled = true"] --> L["issue opts in<br/>label loop:auto<br/>owner / member / collaborator"]
  L --> W["worker loop"] --> PR["PR opened"]
  PR -.->|"auto-merge off by default"| H["squad / human merges"]
```

Details: [docs/WATCHER_247.md](docs/WATCHER_247.md).

## How it works

<p align="center">
  <img src="docs/assets/readme/worker-loop.webp" alt="Worker loop: simplicio-mapper maps the repo, plan in the sandbox with the map slice, apply and verify, a failure, escalation to the next model role, secret scan, PR, squad review" width="100%" />
</p>

```mermaid
flowchart LR
  H["Haiku<br/>mechanical, 1 module"] -->|"2 failures"| S["Sonnet<br/>integration, security"] -->|"2 failures"| O["Opus / Fable<br/>replan only, never executes"]
```

<p align="center">
  <img src="docs/assets/readme/merge-train.webp" alt="Merge train: 4 PRs tested once, red, bisect isolates C, then A, B and D merge" width="100%" />
</p>

```mermaid
flowchart LR
  A["PR A ✓"] & B["PR B ✓"] & C["PR C ✓"] & D["PR D ✓"] --> G{"test the batch once"}
  G -->|"green"| M["merge all into main"]
  G -->|"red"| X["bisect"] --> BAD["PR C out, back to its squad"]
  X --> OK["A, B and D merge"]
```

<p align="center">
  <img src="docs/assets/readme/squads.webp" alt="Squads org chart: a general coordinator, a coordinator per squad and up to 4 workers each" width="100%" />
</p>

```mermaid
flowchart TD
  G["General coordinator<br/>Opus / Fable: plans, never executes"] --> S1["Squad 1<br/>Sonnet coordinator"] & S2["Squad 2<br/>Sonnet coordinator"] & S3["Squad 3<br/>Sonnet coordinator"]
  S1 --> W1["up to 4 Haiku workers"]
  S2 --> W2["up to 4 Haiku workers"]
  S3 --> W3["up to 4 Haiku workers"]
  S1 & S2 & S3 -.->|"APPROVED BY SQUAD"| MC["Merge coordinator<br/>Sonnet: merges in series"] --> MAIN["main"]
```

<p align="center">
  <img src="docs/assets/readme/agents-before-after-cartoon.webp" alt="1 coordinator and 29 workers versus squads: before and after" width="100%" />
</p>

## The 50 extension points

```mermaid
pie showData title Extension points in the 24/7 path (of 50)
  "Wired" : 19
  "Partial" : 29
  "Absent" : 2
```

[docs/EXTENSION_POINTS_SERVICE.md](docs/EXTENSION_POINTS_SERVICE.md) · [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509)

## Learn more

- [INSTALL.md](INSTALL.md) · [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](docs/DASHBOARD.md) · [CHANGELOG.md](CHANGELOG.md)
- **Everything else: [docs/GUIDE.md](docs/GUIDE.md)** (skills, runtimes, the loop, token economy, safety, tests)
