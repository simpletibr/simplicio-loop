# 🔁 simplicio-loop

<p align="center">
  <a href="../docs/REPOSITORY_GOVERNANCE.md"><img src="https://img.shields.io/badge/CI-local%20gate%20is%20authoritative-888888" alt="Validation status: the local scripts/check.py gate is authoritative; GitHub Actions is not required evidence"></a>
  <a href="https://github.com/simpletibr/simplicio-loop/stargazers"><img src="https://img.shields.io/github/stars/simpletibr/simplicio-loop?style=social" alt="Stars"></a>
  <a href="../docs/EXTENSION_POINTS_SERVICE.md"><img src="https://img.shields.io/badge/extension%20points-50-00E08A" alt="50 extension points"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="https://discord.gg/wM6tr7xVb"><img src="https://img.shields.io/badge/Discord-Join%20Simplicio-5865F2?logo=discord&logoColor=white" alt="Join the Simplicio Discord"></a>
</p>

<p align="center">
  <a href="../README.md">🇬🇧 English</a> |
  <a href="README.pt-BR.md">🇧🇷 Português</a> |
  <a href="README.es-ES.md">🇪🇸 Español</a> |
  <a href="README.fr-FR.md">🇫🇷 Français</a> |
  <a href="README.de-DE.md">🇩🇪 Deutsch</a> |
  <a href="README.it-IT.md">🇮🇹 Italiano</a> |
  <a href="README.ja-JP.md">🇯🇵 日本語</a> |
  <a href="README.ko-KR.md">🇰🇷 한국어</a> |
  <a href="README.zh-CN.md">🇨🇳 简体中文</a> |
  <a href="README.ru-RU.md">🇷🇺 Русский</a> |
  <a href="README.pl-PL.md">🇵🇱 Polski</a> |
  <a href="README.tr-TR.md">🇹🇷 Türkçe</a> |
  <a href="README.nl-NL.md">🇳🇱 Nederlands</a> |
  <a href="README.hi-IN.md">🇮🇳 हिन्दी</a> |
  <a href="README.ar-SA.md">🇸🇦 العربية</a>
</p>

**simplicio-loop offre tre operatori deterministici che qualsiasi harness di agenti può chiamare come strumenti: `simplicio-mapper` mappa il repo, `simplicio-dev-cli` applica un piano di modifica esattamente, e la selezione dei test per impatto (`scripts/impact_tests.py`) esegue solo i test che una modifica raggiunge. Il loop che trasforma le issue di GitHub in PR testate è uno dei loro consumatori.**

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="Flusso animato in 8 passi: issue, intake, coordinatore generale, squad, worker in sandbox, revisione dello squad, merge train, main e il kanban Simplicio Live" width="100%" />
</p>

<p align="center">
  <img src="../docs/assets/readme/how-it-works.webp" alt="Flusso animato in 8 passi: issue, intake, coordinatore generale, squad, worker in sandbox, revisione dello squad, merge train, main e il kanban Simplicio Live" width="100%" />
</p>

## Gli operatori

Far girare un agente in un loop non è più la parte difficile: SDK e framework per agenti lo offrono già. La parte che non deve essere probabilistica è leggere il repo, scrivere la modifica e scegliere i test. Questi tre strumenti fanno quel lavoro, nessuno di essi fornisce un modello e ognuno stampa output leggibile da macchina. Il tuo agente (Claude Code, Codex, Cursor, un grafo LangGraph, uno script shell) decide; loro eseguono.

| Operatore | Cosa fa | Richiamabile da qualsiasi harness |
| --- | --- | --- |
| `simplicio-mapper` (survey) | Scorre il repo in locale, senza LLM, e restituisce un pacchetto di contesto limitato per un obiettivo invece dell'intero albero. [Docs](../packages/mapper/README.md) | `simplicio-mapper handoff . --goal "trace the authentication flow" --token-budget 1200 --json` |
| `simplicio-dev-cli` (applicazione deterministica) | Applica un piano di modifica find/replace in cui ogni `find` deve corrispondere esattamente una volta, esegue una verifica circoscritta e stampa una ricevuta JSON. Non fornisce un LLM, secondo il proprio README. [Docs](../packages/dev-cli/README.md) | `simplicio-dev-cli edit --root . --plan plan.json --apply --check "<tests>" --json` |
| Selezione dei test per impatto | `scripts/impact_tests.py` confronta l'albero di lavoro con un ref di base a livello di simbolo e seleziona i file di test che raggiungono una funzione, classe o assegnazione modificata. `scripts/check.py` lo usa, quindi una modifica esegue solo i test che può influenzare. [Docs](../docs/GUIDE.md#-tests--local-checks-no-paid-ci) | `python3 scripts/impact_tests.py --base origin/main --json` |

`pip install simplicio-loop` mette `simplicio-mapper` e `simplicio-dev-cli` nel PATH (un'unica wheel, Python 3.11+). `scripts/impact_tests.py` è uno script della libreria standard senza passaggi di installazione: eseguilo da un checkout o copialo nel tuo repo.

Questo README non riporta alcuna cifra di risparmio. Le misure sono in [bench/llm_ab](../bench/llm_ab/README.md), dove i risultati grezzi per esecuzione sono in `bench/llm_ab/results/` (A/B piccolo, un solo modello); ciò che non è misurato lì non viene affermato.

## Il loop è uno dei suoi consumatori

Il loop è il consumatore di riferimento: prende una issue di GitHub, fa mappare il repo a mapper, lascia che un pianificatore in sandbox scriva un piano JSON, consegna il piano a `simplicio-dev-cli`, esegue i test (in questo repo, `scripts/check.py` esegue il sottoinsieme selezionato per impatto) e poi apre una PR. Sostituisci il loop con un altro harness e gli operatori funzionano allo stesso modo.

```mermaid
flowchart LR
  I["GitHub issue"] --> M["simplicio-mapper<br/>maps files, symbols, tests"]
  M -->|"map slice"| P["Planner in a sandbox<br/>claude / codex / grok / gemini<br/>plans, never writes"]
  P -->|"JSON plan"| D["simplicio-dev-cli<br/>deterministic apply"]
  D --> T["tests verify<br/>simplicio-loop turbo --apply - --verify"]
  T -->|"green"| S["secret scan"] --> PR["PR with evidence"]
  T -.->|"2 failures"| E["escalate the model role"] -.-> P
```

## Installazione

Richiede Python 3.11+, `git` e un `gh` autenticato per le issue di GitHub.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Uso

**In Claude Code o VS Code:**

```text
/simplicio-loop finish all the open issues
```

**Come watcher 24/7** (un servizio che osserva i repo `simpletibr/simplicio-*` e apre PR):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

Dettagli: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

```mermaid
flowchart LR
  R["repo opts in<br/>.simplicio-loop/loop.toml<br/>enabled = true"] --> L["issue opts in<br/>label loop:auto<br/>owner / member / collaborator"]
  L --> W["worker loop"] --> PR["PR opened"]
  PR -.->|"auto-merge off by default"| H["squad / human merges"]
```

## Come funziona

<p align="center">
  <img src="../docs/assets/readme/worker-loop.webp" alt="Loop del worker: pianifica nella sandbox, applica e verifica, un fallimento, escalation al ruolo di modello successivo, scansione dei segreti, PR, revisione dello squad" width="100%" />
</p>

```mermaid
flowchart LR
  H["Haiku<br/>mechanical, 1 module"] -->|"2 failures"| S["Sonnet<br/>integration, security"] -->|"2 failures"| O["Opus / Fable<br/>replan only, never executes"]
```

<p align="center">
  <img src="../docs/assets/readme/merge-train.webp" alt="Merge train: 4 PR testate una volta, rosso, la bisezione isola C, poi A, B e D vengono mergiate" width="100%" />
</p>

```mermaid
flowchart LR
  A["PR A ✓"] & B["PR B ✓"] & C["PR C ✓"] & D["PR D ✓"] --> G{"test the batch once"}
  G -->|"green"| M["merge all into main"]
  G -->|"red"| X["bisect"] --> BAD["PR C out, back to its squad"]
  X --> OK["A, B and D merge"]
```

<p align="center">
  <img src="../docs/assets/readme/squads.webp" alt="Organigramma degli squad: un coordinatore generale, un coordinatore per squad e fino a 4 worker ciascuno" width="100%" />
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
  <img src="../docs/assets/readme/agents-before-after-cartoon.webp" alt="1 coordinator and 29 workers versus squads: before and after" width="100%" />
</p>

## I 50 punti di estensione

```mermaid
pie showData title Extension points in the 24/7 path (of 50)
  "Wired" : 19
  "Partial" : 29
  "Absent" : 2
```

[docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md) · [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509)

## Runtime

- **6 `wired`** adapter contengono codice in `adapters/` e un test di host: Claude Code, Codex, Cursor, Grok, Kiro e VS Code.
- **29 `listed`** host sono voci del catalogo con README e senza codice di adapter; 28 di loro hanno anche un target di installazione generico che scrive le skill e il file di ingresso dell'host. Essere elencato non prova che l'host esegua il loop.
- Gli operatori sopra sono comandi semplici, quindi funzionano da qualsiasi harness, `wired` o no. Stato per host: [adapters/MATRIX.md](../adapters/MATRIX.md) e [simplicio_loop/_catalog/harnesses.json](../simplicio_loop/_catalog/harnesses.json).

## Per saperne di più

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Tutto il resto: [docs/GUIDE.md](../docs/GUIDE.md)** (skill, runtime, il loop, risparmio di token, sicurezza, test; in inglese)
