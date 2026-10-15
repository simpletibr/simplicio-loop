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

**simplicio-loop incluye tres operadores deterministas que cualquier harness de agentes puede llamar como herramientas: `simplicio-mapper` relevea el repo, `simplicio-dev-cli` aplica un plan de edición exactamente, y la selección de tests por impacto (`scripts/impact_tests.py`) ejecuta solo los tests que el cambio alcanza. El loop que convierte issues de GitHub en PRs probados es un consumidor de ellos.**

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="Flujo animado en 8 pasos: issues, intake, coordinador general, squads, workers en sandbox, revisión del squad, merge train, main y el kanban Simplicio Live" width="100%" />
</p>

<p align="center">
  <img src="../docs/assets/readme/how-it-works.webp" alt="Flujo animado en 8 pasos: issues, intake, coordinador general, squads, workers en sandbox, revisión del squad, merge train, main y el kanban Simplicio Live" width="100%" />
</p>

## Los operadores

Hacer que un agente itere ya no es lo difícil: los SDK y frameworks de agentes ya lo incluyen. La parte que no debe ser probabilística es leer el repo, escribir la edición y elegir los tests. Estas tres herramientas hacen ese trabajo, ninguna provisiona un modelo y todas imprimen salida legible por máquina. Tu agente (Claude Code, Codex, Cursor, un grafo de LangGraph, un script de shell) decide; ellas ejecutan.

| Operador | Qué hace | Llámalo desde cualquier harness |
| --- | --- | --- |
| `simplicio-mapper` (survey) | Recorre el repo localmente, sin LLM, y devuelve un paquete de contexto acotado para un objetivo en vez de todo el árbol. [Docs](../packages/mapper/README.md) | `simplicio-mapper handoff . --goal "trace the authentication flow" --token-budget 1200 --json` |
| `simplicio-dev-cli` (aplicación determinista) | Aplica un plan de edición find/replace donde cada `find` debe coincidir exactamente una vez, ejecuta una verificación acotada e imprime un recibo JSON. No provisiona un LLM, según su propio README. [Docs](../packages/dev-cli/README.md) | `simplicio-dev-cli edit --root . --plan plan.json --apply --check "<tests>" --json` |
| Selección de tests por impacto | `scripts/impact_tests.py` compara el árbol de trabajo con una ref base a nivel de símbolo y selecciona los archivos de test que alcanzan una función, clase o asignación cambiada. `scripts/check.py` lo usa, así que un cambio ejecuta solo los tests que puede afectar. [Docs](../docs/GUIDE.md#-tests--local-checks-no-paid-ci) | `python3 scripts/impact_tests.py --base origin/main --json` |

`pip install simplicio-loop` pone `simplicio-mapper` y `simplicio-dev-cli` en tu PATH (una wheel, Python 3.11+). `scripts/impact_tests.py` es un script de la biblioteca estándar sin paso de instalación: ejecútalo desde un checkout o cópialo a tu repo.

Este README no cita ninguna cifra de ahorro. Las mediciones están en [bench/llm_ab](../bench/llm_ab/README.md), donde los resultados brutos por ejecución están en `bench/llm_ab/results/` (A/B pequeño, un solo modelo); lo que no se midió allí no se afirma.

## El loop es uno de sus consumidores

El loop es el consumidor de referencia: toma un issue de GitHub, pide al mapper el mapa del repo, deja que un planificador en sandbox escriba un plan JSON, entrega ese plan a `simplicio-dev-cli` y ejecuta los tests (en este repo, `scripts/check.py` ejecuta el subconjunto seleccionado por impacto) antes de abrir un PR. Cambia el loop por otro harness y los operadores funcionan igual.

```mermaid
flowchart LR
  I["GitHub issue"] --> M["simplicio-mapper<br/>maps files, symbols, tests"]
  M -->|"map slice"| P["Planner in a sandbox<br/>claude / codex / grok / gemini<br/>plans, never writes"]
  P -->|"JSON plan"| D["simplicio-dev-cli<br/>deterministic apply"]
  D --> T["tests verify<br/>simplicio-loop turbo --apply - --verify"]
  T -->|"green"| S["secret scan"] --> PR["PR with evidence"]
  T -.->|"2 failures"| E["escalate the model role"] -.-> P
```

## Instalación

Requiere Python 3.11+, `git` y un `gh` autenticado para las issues de GitHub.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Uso

**En Claude Code o VS Code:**

```text
/simplicio-loop finish all the open issues
```

**Como watcher 24/7** (un servicio que vigila los repos `simpletibr/simplicio-*` y abre PRs):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

Detalles: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

```mermaid
flowchart LR
  R["repo opts in<br/>.simplicio-loop/loop.toml<br/>enabled = true"] --> L["issue opts in<br/>label loop:auto<br/>owner / member / collaborator"]
  L --> W["worker loop"] --> PR["PR opened"]
  PR -.->|"auto-merge off by default"| H["squad / human merges"]
```

## Cómo funciona

<p align="center">
  <img src="../docs/assets/readme/worker-loop.webp" alt="Loop del worker: planifica en el sandbox, aplica y verifica, un fallo, escalada al siguiente rol del modelo, escaneo de secretos, PR, revisión del squad" width="100%" />
</p>

```mermaid
flowchart LR
  H["Haiku<br/>mechanical, 1 module"] -->|"2 failures"| S["Sonnet<br/>integration, security"] -->|"2 failures"| O["Opus / Fable<br/>replan only, never executes"]
```

<p align="center">
  <img src="../docs/assets/readme/merge-train.webp" alt="Merge train: 4 PRs probados una vez, rojo, la bisección aísla C, luego A, B y D hacen merge" width="100%" />
</p>

```mermaid
flowchart LR
  A["PR A ✓"] & B["PR B ✓"] & C["PR C ✓"] & D["PR D ✓"] --> G{"test the batch once"}
  G -->|"green"| M["merge all into main"]
  G -->|"red"| X["bisect"] --> BAD["PR C out, back to its squad"]
  X --> OK["A, B and D merge"]
```

<p align="center">
  <img src="../docs/assets/readme/squads.webp" alt="Organigrama de los squads: un coordinador general, un coordinador por squad y hasta 4 workers cada uno" width="100%" />
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

## Los 50 puntos de extensión

```mermaid
pie showData title Extension points in the 24/7 path (of 50)
  "Wired" : 19
  "Partial" : 29
  "Absent" : 2
```

[docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md) · [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509)

## Runtimes

- **6 `wired`** adaptadores tienen código en `adapters/` y un test de host: Claude Code, Codex, Cursor, Grok, Kiro y VS Code.
- **29 `listed`** hosts son entradas del catálogo con README y sin código de adaptador; 28 de ellos también tienen un destino de instalación genérico que escribe las skills y el archivo de entrada del host. Estar listado no prueba que el host ejecute el loop.
- Los operadores de arriba son comandos simples, así que funcionan desde cualquier harness, `wired` o no. Estado por host: [adapters/MATRIX.md](../adapters/MATRIX.md) y [simplicio_loop/_catalog/harnesses.json](../simplicio_loop/_catalog/harnesses.json).

## Más información

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Todo lo demás: [docs/GUIDE.md](../docs/GUIDE.md)** (skills, runtimes, el loop, economía de tokens, seguridad, tests; en inglés)
