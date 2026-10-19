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

**simplicio-loop ships three deterministic operators that any agent harness can call as plain tools: `simplicio-mapper` surveys a repo, `simplicio-dev-cli` applies an edit plan exactly, and impact-based test selection (`scripts/impact_tests.py`) runs only the tests a change can reach. The loop that turns GitHub issues into tested PRs is one consumer of them.**

## The operators

Looping an agent is no longer the hard part: agent SDKs and frameworks now ship it. The part that must not be probabilistic is reading the repo, writing the edit and choosing the tests. These three tools do that work, none of them provisions a model, and each prints machine-readable output. Your agent (Claude Code, Codex, Cursor, a LangGraph graph, a shell script) decides; they execute.

| Operator | What it does | Call it from any harness |
| --- | --- | --- |
| `simplicio-mapper` (survey) | Walks the repo locally, without an LLM, and returns a bounded context pack for a goal instead of the whole tree. [Docs](packages/mapper/README.md) | `simplicio-mapper handoff . --goal "trace the authentication flow" --token-budget 1200 --json` |
| `simplicio-dev-cli` (deterministic apply) | Applies a find/replace edit plan where each `find` must match exactly once, runs a scoped verification and prints one JSON receipt. It never provisions an LLM, per its README. [Docs](packages/dev-cli/README.md) | `simplicio-dev-cli edit --root . --plan plan.json --apply --check "<tests>" --json` |
| Impact-based test selection | `scripts/impact_tests.py` diffs the working tree against a base ref at symbol level and selects the test files that reach a changed function, class or assignment. `scripts/check.py` uses it, so a change runs only the tests it can affect. [Docs](docs/GUIDE.md#-tests--local-checks-no-paid-ci) | `python3 scripts/impact_tests.py --base origin/main --json` |

`pip install simplicio-loop` puts `simplicio-mapper` and `simplicio-dev-cli` on your PATH (one wheel, Python 3.11+). `scripts/impact_tests.py` is a standard-library script with no install step: run it from a checkout or copy it into your repo.

This README quotes no savings figure. Measurements live in [bench/llm_ab](bench/llm_ab/README.md), where the raw per-run results are in `bench/llm_ab/results/` (small A/B, a single model), and anything not measured there is not claimed.

## The loop is one consumer of them

The loop is the reference consumer: it takes a GitHub issue, has the mapper survey the repo, lets a planner in a sandbox write a JSON plan, hands that plan to `simplicio-dev-cli`, then runs the tests (in this repo, `scripts/check.py` runs the impact-selected subset) before it opens a PR. Swap the loop for any other harness and the operators work the same.

<p align="center">
  <img src="docs/assets/readme/overview-cartoon.webp" alt="Animated flow in 8 steps: issues, intake, general coordinator, squads, workers (mapper, plan, dev-cli), squad review, merge train, main and the Simplicio Live kanban" width="100%" />
</p>

<p align="center">
  <img src="docs/assets/readme/how-it-works.webp" alt="Animated flow in 8 steps: issues, intake, general coordinator, squads, workers (mapper, plan, dev-cli), squad review, merge train, main and the Simplicio Live kanban" width="100%" />
</p>

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
simplicio-loop doctor             # check the installed stack
simplicio-loop prepare --example  # print a valid task file: copy it, edit it, pass it to --task
```

`prepare --example` starts like this:

```text
System: calc
Feature: add mul(a, b)
Type: Feature
```

Then give your agent the goal in [Use it](#use-it).

`simplicio-loop login` is not needed for this. It signs in through the Simplicio Runtime, and only the 24/7 watcher needs a login. Until you sign in, `doctor` shows the login as a warning; that is expected. Without the Runtime, `login` prints the public installer command for your OS and does not run it.

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
  R["repo opts in<br/>.simplicio-loop/loop.toml<br/>enabled = true"] --> L["issue opts in<br/>label loop:auto<br/>owner / member / collaborator"]
  L --> W["worker loop"] --> PR["PR opened"]
  PR -.->|"auto-merge off by default"| H["squad / human merges"]
```

Details: [docs/WATCHER_247.md](docs/WATCHER_247.md).

**Live Dashboard (Simplicio Live):**

```bash
simplicio-loop dashboard                  # start or reuse dashboard on 127.0.0.1:8765
simplicio-loop dashboard --status         # check dashboard status
simplicio-loop dashboard --stop           # stop the dashboard
```

Remote access routes:
- **Local / SSH tunnel (recommended)**: `ssh -L 8765:127.0.0.1:8765 user@remote` then open `http://127.0.0.1:8765/?t=<token>`.
- **Tailscale**: Connect via Tailscale MagicDNS (`http://<node>.ts.net:8765/?t=<token>` or HTTPS `https://<node>.ts.net/?t=<token>`) with a valid access token.
- **Custom host**: Allow specific Host headers with `--allow-host <hostname>` (e.g. `simplicio-loop dashboard --allow-host mybox.internal`).

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

## Runtimes

- **26 wired adapters** ship code in `adapters/` and a host test: Claude Code, Codex, Cursor, Grok, Kiro, VS Code, and
  20 `AGENTS.md` hosts on the `.claude/skills/` surface (see [adapters/MATRIX.md](adapters/MATRIX.md)).
- **9 listed hosts** are catalog entries with a README and no adapter code; 8 of them also have a generic installer target that writes the skills and the host's entry file. A listing is not proof that the host runs the loop.
- The operators above are plain commands, so they work from any harness, wired or not. Per-host status: [adapters/MATRIX.md](adapters/MATRIX.md) and [simplicio_loop/_catalog/harnesses.json](simplicio_loop/_catalog/harnesses.json).

## Learn more

- [INSTALL.md](INSTALL.md) · [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](docs/DASHBOARD.md) · [CHANGELOG.md](CHANGELOG.md)
- **Everything else: [docs/GUIDE.md](docs/GUIDE.md)** (skills, runtimes, the loop, token economy, safety, tests)
