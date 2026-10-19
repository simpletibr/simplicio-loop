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

**simplicio-loop dostarcza trzy deterministyczne operatory, które każdy harness agenta może wywołać jak zwykłe narzędzia: `simplicio-mapper` mapuje repo, `simplicio-dev-cli` stosuje plan edycji dokładnie, a wybór testów wg wpływu (`scripts/impact_tests.py`) uruchamia tylko testy, do których zmiana sięga. Pętla, która zamienia issue z GitHuba w przetestowane PR-y, jest jednym z ich konsumentów.**

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="Animowany przepływ w 8 krokach: issues, intake, główny koordynator, squady, workery (mapper, plan, dev-cli), review squadu, merge train, main i kanban Simplicio Live" width="100%" />
</p>

<p align="center">
  <img src="../docs/assets/readme/how-it-works.webp" alt="Animowany przepływ w 8 krokach: issues, intake, główny koordynator, squady, workery (mapper, plan, dev-cli), review squadu, merge train, main i kanban Simplicio Live" width="100%" />
</p>

## Operatory

Uruchomienie agenta w pętli nie jest już najtrudniejszą częścią: SDK i frameworki agentów to już oferują. Nie może być probabilistyczne czytanie repo, zapis edycji i dobór testów. Te trzy narzędzia wykonują tę pracę, żadne nie uruchamia modelu, a każde drukuje wynik czytelny dla maszyn. Twój agent (Claude Code, Codex, Cursor, graf LangGraph, skrypt shellowy) decyduje; one wykonują.

| Operator | Co robi | Wywoływalny z dowolnego harnessu |
| --- | --- | --- |
| `simplicio-mapper` (survey) | Przechodzi repo lokalnie, bez LLM, i zwraca ograniczony pakiet kontekstu dla celu zamiast całego drzewa. [Docs](../packages/mapper/README.md) | `simplicio-mapper handoff . --goal "trace the authentication flow" --token-budget 1200 --json` |
| `simplicio-dev-cli` (deterministyczne zastosowanie) | Stosuje plan edycji find/replace, w którym każde `find` musi pasować dokładnie raz, uruchamia ograniczoną weryfikację i drukuje jeden paragon JSON. Według własnego README nie uruchamia LLM. [Docs](../packages/dev-cli/README.md) | `simplicio-dev-cli edit --root . --plan plan.json --apply --check "<tests>" --json` |
| Wybór testów wg wpływu | `scripts/impact_tests.py` porównuje drzewo robocze z referencją bazową na poziomie symboli i wybiera pliki testów, które sięgają zmienionej funkcji, klasy lub przypisania. `scripts/check.py` z niego korzysta, więc zmiana uruchamia tylko testy, na które może wpłynąć. [Docs](../docs/GUIDE.md#-tests--local-checks-no-paid-ci) | `python3 scripts/impact_tests.py --base origin/main --json` |

`pip install simplicio-loop` umieszcza `simplicio-mapper` i `simplicio-dev-cli` w PATH (jedno wheel, Python 3.11+). `scripts/impact_tests.py` to skrypt biblioteki standardowej bez kroku instalacji: uruchom go z checkoutu lub skopiuj do swojego repo.

Ten README nie podaje żadnej liczby oszczędności. Pomiary są w [bench/llm_ab](../bench/llm_ab/README.md), a surowe wyniki poszczególnych uruchomień w `bench/llm_ab/results/` (mały test A/B, jeden model); tego, czego tam nie zmierzono, nie twierdzimy.

## Pętla jest jednym z jej konsumentów

Pętla jest konsumentem referencyjnym: bierze issue z GitHuba, każe mapperowi zmapować repo, pozwala plannerowi w sandboksie napisać plan JSON, przekazuje plan do `simplicio-dev-cli`, uruchamia testy (w tym repo `scripts/check.py` uruchamia podzbiór wybrany wg wpływu) i dopiero potem otwiera PR. Zamień pętlę na inny harness, a operatory działają tak samo.

```mermaid
flowchart LR
  I["GitHub issue"] --> M["simplicio-mapper<br/>maps files, symbols, tests"]
  M -->|"map slice"| P["Planner in a sandbox<br/>claude / codex / grok / gemini<br/>plans, never writes"]
  P -->|"JSON plan"| D["simplicio-dev-cli<br/>deterministic apply"]
  D --> T["tests verify<br/>simplicio-loop turbo --apply - --verify"]
  T -->|"green"| S["secret scan"] --> PR["PR with evidence"]
  T -.->|"2 failures"| E["escalate the model role"] -.-> P
```

## Instalacja

Wymaga Pythona 3.11+, `git` oraz uwierzytelnionego `gh` dla issues na GitHubie.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Użycie

**W Claude Code lub VS Code:**

```text
/simplicio-loop finish all the open issues
```

**Jako watcher 24/7** (usługa, która obserwuje repo `simpletibr/simplicio-*` i otwiera PR-y):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

Szczegóły: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

```mermaid
flowchart LR
  R["repo opts in<br/>.simplicio-loop/loop.toml<br/>enabled = true"] --> L["issue opts in<br/>label loop:auto<br/>owner / member / collaborator"]
  L --> W["worker loop"] --> PR["PR opened"]
  PR -.->|"auto-merge off by default"| H["squad / human merges"]
```

## Jak to działa

<p align="center">
  <img src="../docs/assets/readme/worker-loop.webp" alt="Pętla workera: mapper mapuje repo, planowanie w sandboxie, zastosowanie i weryfikacja, porażka, eskalacja do kolejnej roli modelu, skan sekretów, PR, review squadu" width="100%" />
</p>

```mermaid
flowchart LR
  H["Haiku<br/>mechanical, 1 module"] -->|"2 failures"| S["Sonnet<br/>integration, security"] -->|"2 failures"| O["Opus / Fable<br/>replan only, never executes"]
```

<p align="center">
  <img src="../docs/assets/readme/merge-train.webp" alt="Merge train: 4 PR-y przetestowane raz, czerwono, bisekcja izoluje C, potem A, B i D są mergowane" width="100%" />
</p>

```mermaid
flowchart LR
  A["PR A ✓"] & B["PR B ✓"] & C["PR C ✓"] & D["PR D ✓"] --> G{"test the batch once"}
  G -->|"green"| M["merge all into main"]
  G -->|"red"| X["bisect"] --> BAD["PR C out, back to its squad"]
  X --> OK["A, B and D merge"]
```

<p align="center">
  <img src="../docs/assets/readme/squads.webp" alt="Schemat organizacyjny squadów: główny koordynator, koordynator na squad i do 4 workerów w każdym" width="100%" />
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

## 50 punktów rozszerzenia

```mermaid
pie showData title Extension points in the 24/7 path (of 50)
  "Wired" : 19
  "Partial" : 29
  "Absent" : 2
```

[docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md) · [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509)

## Runtime'y

- **34 `wired`** adaptery mają kod w `adapters/` i test hosta: każdy host instalacji z katalogu, w tym Claude Code, Codex, Cursor, Grok, Kiro, VS Code, 20 `AGENTS.md` i osiem z fali B.
- **0 `listed`** hostów: każdy host z katalogu ma kod adaptera. DeepSeek to dostawca modeli, nie host.
- Operatory powyżej to zwykłe polecenia, więc działają z każdego harnessu, `wired` czy nie. Status każdego hosta: [adapters/MATRIX.md](../adapters/MATRIX.md) i [simplicio_loop/_catalog/harnesses.json](../simplicio_loop/_catalog/harnesses.json).

## Dowiedz się więcej

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Wszystko inne: [docs/GUIDE.md](../docs/GUIDE.md)** (skills, runtimes, pętla, oszczędność tokenów, bezpieczeństwo, testy; po angielsku)
