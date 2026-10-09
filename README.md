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
  <img src="docs/assets/readme/how-it-works.gif" alt="Animated flow in 8 steps: issues, intake, general coordinator, squads, sandboxed workers, squad review, merge train, main and the Simplicio Live kanban" width="920" />
</p>

## What it does

- **Plans, never writes:** an AI (an exec CLI such as claude, codex, grok or gemini) plans each change inside a sandbox; only the deterministic `dev-cli` edits files.
- **Proves before it opens a PR:** `turbo --apply - --verify` runs your tests, and a secret scan runs before the push.
- **Squads review and merge in batches** (in progress: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504), [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)). Today the watcher stops at an open PR.

## Install

Needs Python 3.11+, `git`, and an authenticated `gh` for GitHub issues.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Use it

**In Claude Code or VS Code:**

```text
/simplicio-loop finish all the open issues
```

```mermaid
flowchart LR
  A["1. You write /simplicio-loop and the goal"] --> B["2. Map, plan, dev-cli applies, tests verify"]
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

- **Opt-in per repo:** add `.simplicio/loop.toml` with `enabled = true`.
- **Opt-in per issue:** the label `loop:auto`, from a trusted author (owner, member or collaborator).
- **Auto-merge is off.** The watcher only opens PRs; `SIMPLICIO_247_AUTO_MERGE=1` is in progress ([#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)).

Details: [docs/WATCHER_247.md](docs/WATCHER_247.md).

## How it works

**The worker loop** (on `main` today): plan in the sandbox, `turbo --apply - --verify`, two failures escalate the model role, secret scan, PR. Squad review is in progress ([#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)).

<p align="center">
  <img src="docs/assets/readme/worker-loop.gif" alt="Worker loop: plan in the sandbox, apply and verify, a failure, escalation to the next model role, secret scan, PR, squad review" width="920" />
</p>

**The merge train** (in progress: [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)): approved PRs are tested once as a batch; on red it bisects to the bad PR and merges the rest.

<p align="center">
  <img src="docs/assets/readme/merge-train.gif" alt="Merge train: 4 PRs tested once, red, bisect isolates C, then A, B and D merge" width="920" />
</p>

**The squads** (in progress: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)): a general coordinator, one coordinator per squad, up to 4 workers each. Why: [one coordinator versus squads](docs/assets/readme/agents-before-after-cartoon.webp).

<p align="center">
  <img src="docs/assets/readme/squads-cartoon.webp" alt="Squads org chart: a general coordinator, a coordinator per squad and up to 4 workers each" width="920" />
</p>

<p align="center">
  <img src="docs/assets/readme/overview-cartoon.webp" alt="The whole flow: issues, intake, general coordinator, squads, sandboxed workers, dev-cli, squad approval, merge train, main and the Simplicio Live kanban" width="920" />
</p>

## The 50 extension points

The 24/7 service path wires 11 of the 50 (24 partial, 15 absent): [docs/EXTENSION_POINTS_SERVICE.md](docs/EXTENSION_POINTS_SERVICE.md). The plan to wire the rest is [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509).

## Learn more

- [INSTALL.md](INSTALL.md) · [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](docs/DASHBOARD.md) · [CHANGELOG.md](CHANGELOG.md)
- **Everything else: [docs/GUIDE.md](docs/GUIDE.md)** (skills, runtimes, the loop, token economy, safety, tests)
