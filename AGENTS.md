# AGENTS.md

## Operational Context

Before changing code, agents should check the project-specific operational docs:

| Need | File |
|---|---|
| Local setup, services, URLs and credentials policy | `docs/local-setup.md` |
| Domain concepts, rules and edge cases | `docs/domain-map.md` |
| Architecture, request path and integrations | `docs/architecture-map.md` |
| Feature entry points and expected scenarios | `docs/features/README.md` |
| Evidence policy and artifact naming | `docs/evidence/README.md` |
| Common failures and fixes | `docs/troubleshooting.md` |
| Reusable local commands | `scripts/README.md` |

Key placeholders to replace in real projects:

- `<APP_NAME>`
- `<FRONTEND_URL>`
- `<BACKEND_URL>`
- `<DATABASE_REQUIREMENT>`
- `<AUTH_FLOW>`
- `<EVIDENCE_COMMAND>`

Agent checklist:

- [ ] Confirm whether the project lives at repo root or under `projects/`.
- [ ] Read `docs/local-setup.md` and relevant `docs/features/*`.
- [ ] Confirm real start/test/build commands.
- [ ] Run validation before edits when practical.
- [ ] Keep changes small and scoped.
- [ ] Run relevant tests/build after edits.
- [ ] Generate screenshot/video/trace for UI or end-to-end flows.
- [ ] Report blockers with the command, log excerpt and likely cause.

> Master instruction file lido por **Claude Code**, **Codex CLI**, **GitHub Copilot**, **Cursor**, **Windsurf**, **Gemini CLI**, **Kiro**, **AntiGravity**, **OpenCode**, **Simplicio Agent**, **OpenClaw**, **Aider** e qualquer outro agent que respeite o padrão `AGENTS.md`. É o contrato entre humano e IA neste repositório.
>
> Mudou algo aqui? Reflete em `CLAUDE.md` e `.github/copilot-instructions.md` (cópias regulares — Claude/Copilot não seguem symlink). Os espelhos `GEMINI.md`, `.windsurf/rules/agents.md` e `.kiro/steering/agents.md` são **symlinks → `AGENTS.md`**, então acompanham automaticamente.

Este arquivo dá ao agent **tudo que ele precisa saber pra entregar uma task** sem perguntar: stack, comandos, fluxo de trabalho, padrões, proibições, skills disponíveis e atalhos. Lê ele inteiro antes de escrever a primeira linha de código.

---

## Modo do projeto (CHECK OBRIGATÓRIO no início de toda task)

Antes de qualquer análise, o agent **DEVE** ler `.starter-meta.json` e respeitar `project_mode`:

- **`root`** — projeto único na raiz do repo (default). Stack/PRODUCT_NAME na raiz; `.specs/` único.
- **`monorepo`** — workspace com vários subprojetos. Detectado via `pnpm-workspace.yaml`, `lerna.json`, `nx.json`, `turbo.json`, `rush.json`, `package.json` com `"workspaces"`, ou **≥2 subpastas com manifesto** em `apps/` / `packages/` / `services/` / `projects/`. Cada subprojeto recebe seu próprio `.specs/`.

**Fallback sem `.starter-meta.json`**: assuma `root`. Não invente monorepo só porque existe uma pasta `apps/` ou `packages/` com um único subprojeto — a regra é workspace signal explícito **OU** ≥2 manifests irmãos.

> Nota sobre instalação overlay: quando o starter é colocado em cima de um projeto host existente (ver `INSTALL.md`), os arquivos do starter podem estar gitignored. Isso não muda o `project_mode` — só muda a visibilidade no git do host.

---

## Stack

**Python 3.10+** — this repo ships the real product, the `simplicio-cli` PyPI
package (entrypoints `simplicio-cli`, `simplicio-py`, `simplicio-dev-cli`,
~8.8k lines under `simplicio/`). A Node.js/Playwright harness also lives in
this repo, but only as an **embedded starter-kit template** (see below) — it
does not build or test the Python product.

Detalhes completos (**PRODUCT** — o pacote Python real):

- Linguagem principal: **Python 3.10+** (`pyproject.toml`, `setuptools` build backend).
- Empacotamento: `python -m build` → sdist + wheel; ver `docs/PYTHON_PACKAGE_INTERDEPENDENCE.md` (gerado) para o grafo de deps/extras.
- Test runner unit/contract: **pytest** (`tests/python/`, `tests/contracts/`; `[tool.pytest.ini_options]` em `pyproject.toml`).
- Linter/formatter: **ruff** (`ruff check .` / `ruff format --check .`; `[tool.ruff]` em `pyproject.toml`, issue #102).
- Type checker: **mypy** (`mypy simplicio`; `[tool.mypy]` em `pyproject.toml`, baseline documentado, issue #102).
- CI/CD: GitHub Actions (`.github/workflows/ci.yml` — jobs `python`, `lint`, `extras`, `packaging`; este é o gate real que bloqueia merge).
- Deploy/release: PyPI (`simplicio-cli`), tag `vX.Y.Z` — ver `.specs/workflow/RELEASE.md`.

Detalhes do **STARTER embutido** (harness de exemplo, não é o produto):

- `package.json` na raiz só declara os scripts `test:e2e`/`test:e2e:ui`/`test:e2e:report` do harness Playwright (`playwright.config.ts`, `tests/e2e/`). Não há `npm run dev`/`build`/`lint`/`docs:build` — não invente esses comandos.
- Test runner E2E do starter: **Playwright**, rodado isoladamente no workflow `.github/workflows/starter-e2e.yml` (não gate do pacote Python).

> Antes de adicionar dependência nova (Python ou npm): **pergunta ao usuário**. Sem exceção.

---

## Comandos importantes

```bash
# PRODUCT (Python — simplicio-cli) ------------------------------------------
# setup
pip install -e ".[dev]"        # editable install + ruff/mypy/pytest (issue #102)
pip install -e ".[test]"       # só pytest, sem ruff/mypy (o que a CI usa no job "python")

# qualidade
ruff check .                   # lint (E/F/I/UP/B)
ruff format --check .          # format check (--check só verifica; sem --check reescreve)
mypy simplicio                 # type check (baseline documentado em pyproject.toml)

# testes
pytest                         # tests/python + tests/contracts (testpaths em pyproject.toml)
pytest --cov                   # com coverage, se pytest-cov estiver instalado

# docs geradas
python3 scripts/gen_package_interdependence.py --check   # falha se a doc de deps driftou (#101)

# CLI real
simplicio-py --help            # (ou simplicio-cli / simplicio-dev-cli — mesmo entrypoint)

# STARTER embutido (Playwright — não é o produto) ----------------------------
npx playwright install         # instala browsers (1a vez)
npx playwright test            # roda a suite E2E do harness starter
npx playwright test --ui       # modo interativo
npx playwright show-report     # abre relatorio ultimo run

# git/PR (produto e starter) -------------------------------------------------
git checkout -b feat/<task-id>-<slug>
gh pr create --fill            # usa template de PR
gh run watch                   # acompanha CI do branch atual
```

---

## Padrão de sincronização deste projeto

Para este repositório, sempre que a mudança for **release-relevant** (o pacote Python `simplicio-cli`), o fechamento padrão deve deixar tudo sincronizado no mesmo ciclo:

- versão de `pyproject.toml` publicada no PyPI (`simplicio-cli`)
- tag GitHub `vX.Y.Z` criada e enviada
- GitHub Release correspondente criada/atualizada
- `master` limpa e sincronizada com `origin/master`

Validação padrão obrigatória antes de publicar/sincronizar:

```bash
ruff check .
ruff format --check .
mypy simplicio
pytest
python3 scripts/gen_package_interdependence.py --check
python -m build && python -m twine check dist/*
```

Se qualquer item acima falhar, **não** publique e **não** crie a release/tag até corrigir.

---

## Workflow loop OBRIGATÓRIO

Toda task técnica passa por esses passos. Não pula etapa.

1. **Ler task** — abre arquivo em `.specs/sprints/sprint-XX/<task-id>.task.md` (ou a issue do GitHub). Lê contexto + acceptance criteria + test plan + DoD.
2. **Planejar** — escreve plano interno curto: o que muda, quais arquivos, como verificar, efeitos colaterais. Se task ambígua → pergunta antes de codar.
3. **Carregar contexto** — lê `.specs/architecture/PATTERNS.md` + ADRs relevantes em `.specs/architecture/ADR-*.md`. Verifica skills aplicáveis em `.skills/`.
4. **Editar** — aplica edits cirúrgicos. Só toca o que a task pede. Sem refactor extra, sem renomeação, sem comentário a mais.
5. **Lint + type** — `ruff check .` e `ruff format --check .` e `mypy simplicio`. Vermelho = corrige antes de seguir.
6. **Unit/contract** — `pytest`. Vermelho = corrige antes de seguir (exceto falhas pré-existentes já documentadas e sem relação com a mudança — cite-as explicitamente no PR).
7. **E2E (quando a mudança tocar o harness starter/Playwright)** — `npx playwright test --reporter=list,html`. Captura **trace + screenshot + video** (todos, não "ou"). Sem evidência salva em `playwright-report/` + `test-results/` = task não fechada. Vermelho = corrige. (A maior parte das tasks deste repo mexe no pacote Python e não passa por este passo — não é o gate universal.)
8. **Fix loop** — se qualquer etapa falhou: volta ao passo 4. Repete até verde.
9. **Commit** — Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`). Mensagem em **inglês**. Body explica *why*, não *what*.
10. **PR** — `gh pr create`. Preenche template inteiro: link da task/issue, evidências, checklist DoD marcado.

---

## Definition of Done

PR só faz merge quando **todos** os itens abaixo estão marcados:

- [ ] `pytest` verde (ou falhas pré-existentes documentadas explicitamente, sem relação com o diff)
- [ ] `ruff check .` e `ruff format --check .` verdes
- [ ] `mypy simplicio` verde no rigor documentado em `pyproject.toml` (`[tool.mypy]`)
- [ ] `python3 scripts/gen_package_interdependence.py --check` verde se `pyproject.toml` mudou (#101)
- [ ] E2E Playwright, **quando a mudança tocar o starter/harness**, com evidência anexada — `playwright-report/index.html` + `test-results/<spec>/trace.zip` + screenshots por cenário + video (when retry). Hard rule quando aplicável: sem evidência, sem merge.
- [ ] Acceptance Criteria da task/issue: todos os checkboxes marcados (ou partial, com motivo explícito no PR)
- [ ] **Verificação independente/adversarial pós-verde** — depois do DoD verde, UMA passada *ortogonal* (não repetição da mesma checagem): AC relida lado a lado com o resultado, feature exercitada de verdade + 1 cenário de borda + 1 caminho de erro, resultado registrado. Verde no DoD ≠ feito. (`.skills/llm-verification/`)
- [ ] PR template preenchido (link task/issue + descrição + evidências)
- [ ] Conventional commit no merge
- [ ] ADR criado em `.specs/architecture/` se mudou decisão arquitetural
- [ ] Changelog atualizado se release-relevant
- [ ] Sem warning novo no console
- [ ] Sem `print()`/`console.log` de diagnóstico deixado pra trás em código de biblioteca (ver `simplicio/observability.py` / módulo de output central, issue #106) — CLI handlers onde stdout É o resultado pretendido são a exceção documentada
- [ ] Sem TODO sem dono e sem prazo

CI (`.github/workflows/ci.yml`, job `python` + `lint`) bloqueia merge se o gate falhar.

---

## Padrões de código

Padrões completos em `.specs/architecture/PATTERNS.md`. Resumo:

- Naming, estrutura de pastas, criação de endpoint/componente/teste, tratamento de erro, logging, validação — **tudo lá**.
- Decisões irreversíveis viram **ADR** em `.specs/architecture/ADR-XXX-*.md` (template em `.specs/architecture/ADR-template.md`).
- Antes de escrever código novo: lê `PATTERNS.md` da seção relevante. Não inventa estilo próprio.

---

## Observability / unified evidence flow (issues #106, #107)

`simplicio/observability.py` é a camada central de output/logging + eventos estruturados deste pacote:

- **stdout vs stderr (#106)**: `emit_data()` escreve o payload máquina-consumível (o resultado pretendido) em stdout; `info()`/`warn()`/`error()` escrevem status/diagnóstico humano em stderr via um `logging.Logger("simplicio")`, configurável por `configure_logging(quiet=, verbose=)` e `SIMPLICIO_LOG_LEVEL` (`--quiet`/`-q`/`--verbose`/`-v` antes do subcomando em `simplicio-py` fazem essa configuração — ver `_extract_global_verbosity` em `cli.py`). `simplicio/mcp_server.py` roda sobre stdio: qualquer coisa que não seja um frame JSON-RPC no stdout dele corrompe o transporte, então código adjacente ao MCP usa `info`/`warn`/`error`, nunca `print()`. CLI *handlers* (`cli.py`, `commands/*.py`, `doctor.py`, etc.) são a exceção documentada — stdout ali É o resultado do subcomando.
- **Eventos estruturados / evidência unificada (#107)**: `emit_event(event_type, payload, level=, root=, tokens_saved=)` emite uma linha humana em stderr **e**, quando `root` é passado, um registro JSON em `<root>/.simplicio/events.jsonl` (schema `simplicio.dev-cli-event/v1`, documentado no docstring de `emit_event`). Este é o **contrato** que um loop host (ex.: `loop_journal.py` do simplicio-loop) pode ler — dev-cli não importa nem depende do código do loop, só se compromete com esse formato. Produtores já ligados: `pipeline.run_task` (`task_start`/`task_complete`/`validation_fail`/`token_usage`), `mapper.py` (`evidence_captured` nos três blocos TOON), `mcp_server.py` (`edit_applied`/`handoff`/`validation_fail` em cada `tools/call`).
- `simplicio-py doctor` (humano e `--json`) mostra um resumo desses eventos (`events_summary()`, flags `--root`/--events-limit`) — não é preciso inspecionar `.simplicio/events.jsonl` a mão para ver se a emissão está funcionando.
- Regra de regressão: ruff `T20` (flake8-print) está no `select` do lint — um `print()` reintroduzido em código de biblioteca/MCP-adjacente quebra o CI; a exceção fica em `[tool.ruff.lint.per-file-ignores]`, restrita aos CLI handlers documentados.

---

## Onde encontrar contexto

| Pergunta | Onde olha |
|---|---|
| Por que esse produto existe? | `.specs/product/VISION.md` |
| Quem é o usuário? | `.specs/product/PERSONAS.md` |
| Quais entidades de negócio? | `.specs/product/DOMAIN.md` |
| Como o sistema é desenhado? | `.specs/architecture/DESIGN.md` |
| Como escrever código aqui? | `.specs/architecture/PATTERNS.md` |
| Por que decidimos X? | `.specs/architecture/ADR-*.md` |
| Como faço PR/branch/release? | `.specs/workflow/WORKFLOW.md`, `RELEASE.md`, `CONTRIBUTING.md` |
| O que tá no backlog? | `.specs/sprints/BACKLOG.md` |
| Sprint atual? | `.specs/sprints/sprint-XX/SPRINT.md` |
| Tasks abertas? | `.specs/sprints/sprint-XX/*.task.md` |
| Skills/capacidades reutilizáveis? | `.skills/README.md` + `.skills/*/SKILL.md` |
| Custom agents (sub-agents)? | `.agents/README.md` + `.agents/*.agent.md` |

---

## Proibido

Lista negra. Nada aqui é negociável.

- **Pular testes** — sem unit/E2E = sem merge.
- **Mockar pra fazer passar** — mock só pra isolar dependência externa real (HTTP, DB), nunca pra esconder falha.
- **Commit com vermelho** — lint/test falhando = não commita. Hook `.claude/hooks/pre-commit.sh` bloqueia.
- **Ignorar ADR** — decisão registrada em ADR é lei. Reverter/mudar ADR exige novo ADR ("Supersedes ADR-XXX").
- **Adicionar dependência sem perguntar** — toda nova dep (`npm install`, `dotnet add`, etc.) passa por confirmação humana.
- **Editar arquivo não lido** — lê antes de editar. Sempre.
- **Refactor escondido em PR de feature** — refactor = PR separado.
- **Force push em `main`/`master`** — bloqueado por hook e por settings do repo.
- **Commitar segredo** — `.env`, token, key, senha → nunca. Usa `.gitignore` + secrets manager.
- **Reformatar arquivo inteiro num PR pequeno** — diff polui review.

---

## Skills disponíveis

Skills moram em `.skills/<nome>/SKILL.md` e são capacidades reutilizáveis que o agent invoca quando o trigger casa. Lista atual:

### Ativadas por padrão no início da sessão

Estas três skills são **ativadas automaticamente em toda sessão** (via `.claude/settings.json` SessionStart hook). Isso define o estado inicial padrão; a obrigatoriedade e a possibilidade de desativação dependem da política de cada skill:

- **`caveman`** — modo terse de resposta. Economiza ~65% tokens de output sem perder substância técnica. Default level: `full`. Boundaries: código, commits, PRs e docs canônicos permanecem em prosa normal. **É ativada por padrão, mas pode ser desativada explicitamente** quando a tarefa exigir resposta em prosa normal, via `stop caveman` / `normal mode`.
- **`ralph-loop`** — loop autônomo `read → plan → execute → lint → unit → e2e → fix → repeat` até DoD verde. **Obrigatório** em TODA task técnica com AC mensurável. Dual exit gate: indicadores verdes + `EXIT_SIGNAL: true`.
- **`everything-claude-code`** — bundle de ~60 agents + ~221 skills. Padrão: usar o **máximo de agents ECC em paralelo** a cada alteração (single message, múltiplas Agent calls). Reviewers da stack + `security-reviewer` obrigatórios após edits.

### Sob demanda

- **`playwright-e2e`** — como escrever teste Playwright neste projeto. Trigger: nova feature de UI ou fluxo end-to-end. Cobre fixtures, page objects, evidências (trace/screenshot/video) e padrões de assert.
- **`conventional-commits`** — regras de commit (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `perf:`, `style:`, `ci:`, `build:`). Trigger: hora de commitar. Inclui exemplos, breaking changes (`!`/`BREAKING CHANGE:`) e scope.
- **`llm-verification`** — passada de verificação independente/adversarial **depois** do DoD verde, antes de declarar "feito". Trigger: fechar task técnica, ou pergunta "deu ok?" / "verifica de novo". Operacionaliza o item de DoD "Verificação independente/adversarial pós-verde": uma passada *ortogonal* (não repetição), AC ⇄ resultado, feature rodada de verdade + borda + caminho de erro.
- **`_template`** — base pra criar skill nova. Copia, renomeia pasta, preenche frontmatter (`name`, `description`, `trigger`, `steps`, `dod`).

Detalhes completos: `.skills/README.md`.

---

## Custom agents disponíveis

Sub-agents customizados moram em `.agents/<slug>.agent.md` (padrão **AGENTS.md ecosystem**, lido por Claude Code, Codex, Simplicio Agent, OpenClaw, Cursor, Aider). Espelhados em `.github/copilot/agents/` para o GitHub Copilot Workspace. Lista atual:

- **`ralph-loop.agent.md`** — Ralph Loop (padrão autônomo, Ralph Wiggum technique). Loop `read → plan → execute → lint → unit → Playwright → fix → repeat` até DoD verde. **Mapeia para comando nativo de cada ferramenta**: Claude Code → `/ralph-loop "<prompt>"` (plugin oficial `claude-plugins-official`); Codex CLI ≥0.128 → `/goal <objective>`; GitHub Copilot CLI → `copilot --autopilot --max-autopilot-continues N`; VS Code Agent Mode → permission level "Autopilot"; Cursor ≥3.0 → Background Agent / `/multitask`. Aciona em **toda task técnica** com AC mensurável. Tools: `edit`, `terminal`, `search`.
- **`simplicio-ralph.agent.md`** — Composição Ralph Loop + simplicio-cli. Loop autônomo onde o passo `execute` delega geração ao `simplicio-py task` (precedent + skill_router) em vez de edit direto. Aciona em task técnica que se beneficie do prompt afiado do simplicio-cli (stacks medidas no `bench/`). Aditivo: não modifica `simplicio/*.py`. Tools: `edit`, `terminal`, `search`.
- **`tdd.agent.md`** — TDD Specialist. Escreve teste falhando antes do código. Loop red-green-refactor. Tools: `edit`, `terminal`, `search`. Aciona em feature/bugfix com cobertura nova.
- **`reviewer.agent.md`** — Code Reviewer. Read-only. Comenta problemas e sugestões. Tools: `search`, `read`. Aciona em revisão de PR aberto, sem editar.
- **`architect.agent.md`** — Architect. Desenha arquitetura, cria ADRs, atualiza `PATTERNS.md`. Não escreve código de produção. Tools: `edit`, `search`, `read`. Aciona em decisão arquitetural, refactor amplo, integração nova.
- **`_template.agent.md`** — base para criar agent novo. Copia, renomeia, preenche frontmatter (`name`, `description`, `tools`).

Detalhes completos: `.agents/README.md`.

---

## Comandos especiais

### Criar nova ADR

```bash
# encontra proximo numero
ls .specs/architecture/ADR-*.md | tail -1
# copia template
cp .specs/architecture/ADR-template.md .specs/architecture/ADR-XXX-<slug>.md
# edita: Status, Contexto, Decisao, Consequencias, Alternativas
# commita junto com a feature que motivou a decisao
```

### Abrir PR

```bash
git push -u origin $(git branch --show-current)
gh pr create --fill        # usa template padrao (.github/PULL_REQUEST_TEMPLATE.md)
gh pr view --web           # abre no browser pra revisar
gh run watch               # acompanha CI
```

### Criar task nova

```bash
cp .specs/sprints/task-template.md .specs/sprints/sprint-XX/<id>-<slug>.task.md
# preenche: Contexto, Acceptance Criteria, Out of scope, Test plan, DoD, Pegadinhas, Links
# adiciona linha em .specs/sprints/BACKLOG.md
```

### Criar skill nova

```bash
cp -R .skills/_template .skills/<nome-da-skill>
# edita SKILL.md: name, description, trigger, steps, padroes, DoD
# referencia em .skills/README.md
```

### Rodar checklist DoD localmente antes de PR

```bash
ruff check . && ruff format --check . && mypy simplicio && pytest
# se tudo verde -> git commit && git push && gh pr create --fill
# tocou o harness starter/Playwright? roda também: npx playwright test
```

---

## Notas finais pro agent

- **Idioma**: respostas/docs em **pt-BR**, código (vars/funções/classes) em **inglês**, commits em **inglês**.
- **Sem emoji em código**. README/slides ok.
- **Sem resumo no final** de uma resposta. Entrega o trabalho e finaliza.
- **Sem estimativa de tempo** (não tem como prever, não promete).
- **Pergunta apenas em ambiguidade real** do pedido. Não pergunta pra confirmar trabalho de execução.
- **Paralelo é o padrão** — research + read + review independentes rodam simultâneos.
- **Hooks do `.claude/hooks/`** rodam automaticamente: post-edit faz lint/format, pre-commit bloqueia commit vermelho.

<!-- codex-long-running-agent-overlay:start -->
## Universal Long-Running Agent Overlay

This section complements the repository-specific guidance already in this file. If anything here conflicts with the repo-specific rules above, the repo-specific rules win.

- `PRD.md` is the task source of truth for long-running sessions.
- `PROGRESS.md` is the persistent checkpoint log.
- `GOAL_RESULT.md` is the final execution report.
- Before coding, read this file, `PRD.md`, `PROGRESS.md` when it exists, `README.md`, project manifests, tests, and the relevant source folders.
- Work in small checkpoints, run the smallest relevant validation after each meaningful change, update `PROGRESS.md`, and continue until complete or genuinely blocked.
- Stop only when the requested work is complete, validation is documented, and `GOAL_RESULT.md` reflects the outcome.
- Do not rewrite unrelated architecture, fake successful validation, expose secrets, or push without explicit operator instruction for the active session.
<!-- codex-long-running-agent-overlay:end -->
