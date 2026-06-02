# Copilot Instructions

> Instruction file lido automaticamente pelo **GitHub Copilot Chat** e **Copilot Workspace / Agent Mode**. Espelha [AGENTS.md](../AGENTS.md) com foco em **Agent Mode workflow**.
>
> Ao trabalhar em Agent Mode, o Copilot pode delegar pra custom agents em [`.agents/`](../.agents/) (canônico, padrão AGENTS.md ecosystem) e/ou em `.github/copilot/agents/` (mirror lido pelo Copilot Coding Agent). Lista atual: `tdd.agent.md`, `reviewer.agent.md`, `architect.agent.md`.
>
> Canonical pattern spec: [YOOL_TUPLE_HAMT.md](../YOOL_TUPLE_HAMT.md)
>
> Receipt schema reference: [YOOL_TUPLE_HAMT.md §1.8.4](../YOOL_TUPLE_HAMT.md#184-receipt-schema-reference)

---

## Stack

**Python 3.10+ (`orjson`, `diskcache`) + Node.js CLI + optional Rust/PyO3 crate + Playwright E2E.**

- Linguagem principal: **Python 3.10+** (PyPI `simplicio-mapper`); espelho Node 18+ em `bin/cli.js` + `bin/mapper-artifacts.js` mantido em paridade.
- Framework web/API: n/a — projeto é CLI/library.
- Banco de dados: n/a — cache opcional em disco via `diskcache` em `.simplicio/cache/`.
- Test runner unit: **`python -m unittest discover -s tests/python`** (também via `pytest tests/python -q`) e **`node --test tests/unit`**.
- Test runner E2E: **Playwright** (config em `playwright.config.ts`).
- Linter/formatter: **`ruff`** (ver `[tool.ruff]` em `pyproject.toml`) e `node scripts/lint.js` (shell + JS).
- CI/CD: GitHub Actions (`.github/workflows/`). DoD em `dod.yml`. Publish em `publish-pypi.yml` (PyPI-only desde 0.7.x).
- Distribuição: PyPI canonical; npm `@wesleysimplicio/llm-project-mapper` mantido só para versões antigas, sem releases novos.
- Opt-in: crate Rust em `rust/` via `maturin develop --release` (ADR-002).

> Antes de adicionar dependência nova: pergunta ao humano. Sem exceção.

---

## Comandos importantes

```bash
# desenvolvimento / smoke local
node bin/cli.js --help
python -m simplicio_mapper.cli --help
python -m build

# qualidade
npm run lint
ruff check simplicio_mapper tests/python
node scripts/check-version-sync.js
python -m unittest discover -s tests/python
node --test tests/unit
npm test

# E2E
npx playwright install
npx playwright test
npx playwright show-report

# Rust opt-in
(cd rust && maturin develop --release)
python -m pytest tests/python/test_native.py

# git/PR
git checkout -b feat/<task-id>-<slug>
gh pr create --fill
gh run watch
```

---

## Padrão de sincronização deste projeto

Quando a mudança for **release-relevant**, o padrão deste repositório é fechar o trabalho com tudo sincronizado no mesmo ciclo:

- npm publicado na mesma versão de `package.json`
- tag GitHub `vX.Y.Z`
- GitHub Release correspondente
- `main` limpa e sincronizada com `origin/main`

Validação obrigatória antes de publicar/sincronizar:

```bash
npm run lint
npm test
npm run docs:build
npm run test:e2e -- --reporter=list,html
```

Se qualquer comando falhar, não publique e não crie a release/tag.

---

## Workflow loop OBRIGATÓRIO (Agent Mode)

Em Copilot Workspace/Agent Mode, todo plano de execução segue esse loop. Não pula etapa.

1. **Ler task** — abre `.specs/sprints/sprint-XX/<task-id>.task.md`. Lê contexto + acceptance criteria + test plan + DoD.
2. **Plano explícito** — Copilot Workspace gera spec/plan. Revisa antes de implementar.
3. **Carregar contexto** — `.specs/architecture/PATTERNS.md` + ADRs relevantes em `.specs/architecture/ADR-*.md`. Skills aplicáveis em `.skills/`.
4. **Implementar (Agent Mode)** — edits cirúrgicos. Só toca o que a task pede. Sem refactor extra.
5. **Lint** — `npm run lint`. Vermelho = corrige.
6. **Unit** — `npm test`. Vermelho = corrige. Coverage do diff >= 80%.
7. **E2E (OBRIGATÓRIO em TODA task)** — `npx playwright test --reporter=list,html`. Captura **trace + screenshot + video** (todos). Sem evidência em `playwright-report/` + `test-results/` = task não fechada.
8. **Fix loop** — falhou? Volta ao 4. Repete até verde.
9. **Commit** — Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`). Mensagem em **inglês**.
10. **PR** — `gh pr create --fill`. Preenche template inteiro.

---

## Definition of Done

PR só faz merge quando todos os itens abaixo estão marcados:

- [ ] Unit tests passam
- [ ] Lint passa
- [ ] E2E Playwright passa **com evidência anexada em TODA task** — `playwright-report/index.html` + `test-results/<spec>/trace.zip` + screenshots por cenário + video. Hard rule: sem evidência, sem merge.
- [ ] Coverage do diff >= 80%
- [ ] Acceptance Criteria todos marcados
- [ ] PR template preenchido (link task + descrição + evidências)
- [ ] Conventional commit no merge
- [ ] ADR criado se mudou decisão arquitetural
- [ ] Changelog atualizado se release-relevant
- [ ] Sem warning novo, sem `console.log`/`print` deixado pra trás
- [ ] Sem TODO sem dono e sem prazo

CI bloqueia merge se DoD falhar (`.github/workflows/dod.yml`).

---

## Padrões de código

`.specs/architecture/PATTERNS.md` é a **fonte única**. Naming, estrutura, criação de endpoint/componente/teste, tratamento de erro, logging, validação — tudo lá.

Decisões irreversíveis viram **ADR** em `.specs/architecture/ADR-XXX-*.md` (template em `.specs/architecture/ADR-template.md`).

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
| Backlog? | `.specs/sprints/BACKLOG.md` |
| Sprint atual? | `.specs/sprints/sprint-XX/SPRINT.md` |
| Skills? | `.skills/README.md` + `.skills/*/SKILL.md` |

---

## Proibido

- **Pular testes** — sem unit/E2E = sem merge.
- **Mockar pra fazer passar** — mock só pra dep externa real (HTTP, DB), nunca pra esconder falha.
- **Commit com vermelho** — lint/test falhando = não commita.
- **Ignorar ADR** — decisão registrada é lei.
- **Adicionar dependência sem perguntar.**
- **Editar arquivo não lido.**
- **Refactor escondido em PR de feature** — PR separado.
- **Force push em `main`/`master`.**
- **Commitar segredo** (`.env`, token, key, senha).
- **Reformatar arquivo inteiro num PR pequeno.**

---

## Custom agents (Copilot Workspace / Agent Mode)

Copilot pode delegar pra um custom agent quando a tarefa casa com a `description` do agent. Definidos em [`.agents/`](../.agents/) (canônico) e espelhados em `.github/copilot/agents/` (mirror para Copilot Coding Agent):

- **`ralph-loop.agent.md`** — Ralph Loop (padrão autônomo, Ralph Wiggum technique). Loop `read → plan → execute → lint → unit → Playwright → fix → repeat` até DoD verde. **No Copilot CLI**: `copilot --autopilot --yolo --max-autopilot-continues 20 -p "<prompt>"`. **No VS Code Agent Mode**: dropdown Mode → Agent + permission level **Autopilot** = continuous iteration nativo. Em outras ferramentas: Claude Code `/ralph-loop` (plugin oficial), Codex CLI `/goal`, Cursor Background Agent. Tools: `edit`, `terminal`, `search`.
- **`tdd.agent.md`** — TDD Specialist. Escreve teste falhando antes do código. Loop red-green-refactor. Tools: `edit`, `terminal`, `search`. Aciona quando tarefa exige cobertura nova ou regression test.
- **`reviewer.agent.md`** — Code Reviewer. Read-only. Comenta problemas e sugestões em PR. Tools: `search`, `read`. Aciona em revisão de PR aberto, sem editar arquivos.
- **`architect.agent.md`** — Architect. Desenha arquitetura, cria ADRs, atualiza `PATTERNS.md`. **Não escreve código de produção.** Tools: `edit`, `search`, `read`. Aciona em decisão arquitetural, refactor amplo, integração nova.

Pra invocar explicitamente em Copilot Chat: `@ralph-loop`, `@tdd`, `@reviewer`, `@architect`.

---

## Skills disponíveis (`.skills/`)

- **`playwright-e2e`** — como escrever teste Playwright. Trigger: nova feature de UI / fluxo end-to-end.
- **`conventional-commits`** — regras de commit (`feat:`, `fix:`, etc.). Trigger: hora de commitar.
- **`_template`** — base pra criar skill nova.

Detalhes em `.skills/README.md`.

---

## yool / tuple / HAMT

Spec: [YOOL_TUPLE_HAMT.md](../YOOL_TUPLE_HAMT.md).

Required agent fields:

```markdown
- yool_id: `agent.dev.python.v1`
- authority: dev | ops | review | audit
- lane: fast | slow | background
- agent_terms:
    cpu_quota_pct: 60
    disk_quota_mb: 100
    timeout_s: 300
```

Receipts live under `.receipts/` and should follow the canonical schema in [YOOL_TUPLE_HAMT.md §1.8.4](../YOOL_TUPLE_HAMT.md#184-receipt-schema-reference).

Build the HAMT catalog with:

```bash
node bin/build-hamt-catalog --source AGENTS.md --output .catalog/agents.json
```

---

## Comandos especiais

### Criar nova ADR

```bash
cp .specs/architecture/ADR-template.md .specs/architecture/ADR-XXX-<slug>.md
# preenche e commita junto com a feature
```

### Abrir PR

```bash
git push -u origin $(git branch --show-current)
gh pr create --fill
```

### Criar task

```bash
cp .specs/sprints/task-template.md .specs/sprints/sprint-XX/<id>-<slug>.task.md
```

### DoD local antes de push

```bash
npm run lint && npm test -- --coverage && npx playwright test
```

---

## Notas finais

- **Idioma**: docs em pt-BR, código em inglês, commits em inglês.
- **Sem emoji em código fonte.** README/slides ok.
- **Sem resumo no final** de resposta.
- **Sem estimativa de tempo.**
- **Pergunta apenas em ambiguidade real.**
- **Paralelismo** — research + read + review independentes rodam simultâneos em Agent Mode.

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
