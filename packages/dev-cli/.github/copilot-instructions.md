# Copilot Instructions

> Instruction file lido automaticamente pelo **GitHub Copilot Chat** e **Copilot Workspace / Agent Mode**. Espelha [AGENTS.md](../AGENTS.md) com foco em **Agent Mode workflow**.
>
> Ao trabalhar em Agent Mode, o Copilot pode delegar pra custom agents em [`.agents/`](../.agents/) (canônico, padrão AGENTS.md ecosystem) e/ou em `.github/copilot/agents/` (mirror lido pelo Copilot Coding Agent). Lista atual: `tdd.agent.md`, `reviewer.agent.md`, `architect.agent.md`.

---

## Stack

**Python 3.10+** — este repo é o pacote real `simplicio-cli` (entrypoints
`simplicio-cli`/`simplicio-py`/`simplicio-dev-cli`, ~8.8k linhas em
`simplicio/`). Um harness Node/Playwright também vive aqui, mas só como
**starter-kit embutido** — não builda nem testa o pacote Python.

PRODUCT:
- Linguagem principal: **Python 3.10+** (`pyproject.toml`, `setuptools`).
- Test runner unit/contract: **pytest** (`tests/python/`, `tests/contracts/`).
- Linter/formatter: **ruff** (`ruff check .` / `ruff format --check .`).
- Type checker: **mypy** (`mypy simplicio`).
- Quality gate: GitHub Actions executa o gate bloqueante de cobertura em PRs e
  pushes para `main`; o gate completo também é reproduzível localmente.
- Deploy: PyPI (`simplicio-cli`) — ver `.specs/workflow/RELEASE.md`.

STARTER embutido (não é o produto): `package.json` só declara
`test:e2e`/`test:e2e:ui`/`test:e2e:report` (Playwright). Não existe `npm run
dev`/`build`/`lint`/`docs:build` — não invente esses comandos.

> Antes de adicionar dependência nova (Python ou npm): pergunta ao humano. Sem exceção.

---

## Comandos importantes

```bash
# PRODUCT (Python)
pip install -e ".[dev]"      # ruff + mypy + pytest
ruff check .
ruff format --check .
mypy simplicio
pytest

# STARTER embutido (Playwright)
npx playwright install
npx playwright test
npx playwright show-report

# git/PR
git checkout -b feat/<task-id>-<slug>
gh pr create --fill
# anexar ao PR os comandos e resultados do gate local
```

## Codex → Runtime

Quando uma tarefa de código for iniciada pelo Codex CLI, use a integração
reversível documentada em [`docs/codex-wrapper.md`](../docs/codex-wrapper.md).
O wrapper/hook roteia a tarefa de desenvolvimento para `simplicio run` e
preserva `sandbox_mode`/`approval_policy`; nunca adicione flags de bypass nem
execute uma mutação fora do Runtime.

---

## Padrão de sincronização deste projeto

Quando a mudança for **release-relevant** (pacote Python `simplicio-cli`), o padrão deste repositório é fechar o trabalho com tudo sincronizado no mesmo ciclo:

- versão de `pyproject.toml` publicada no PyPI
- tag GitHub `vX.Y.Z`
- GitHub Release correspondente
- `main` limpa e sincronizada com `origin/main`
- `master` preservada apenas como compatibilidade, sem novos commits diretos

Validação obrigatória antes de publicar/sincronizar:

```bash
ruff check . && ruff format --check . && mypy simplicio && pytest
python3 scripts/gen_package_interdependence.py --check
python -m build && python -m twine check dist/*
```

Se qualquer comando falhar, não publique e não crie a release/tag.

---

## Workflow loop OBRIGATÓRIO (Agent Mode)

Em Copilot Workspace/Agent Mode, todo plano de execução segue esse loop. Não pula etapa.

1. **Ler task** — abre `.specs/sprints/sprint-XX/<task-id>.task.md` (ou a issue do GitHub). Lê contexto + acceptance criteria + test plan + DoD.
2. **Plano explícito** — Copilot Workspace gera spec/plan. Revisa antes de implementar.
3. **Carregar contexto** — `.specs/architecture/PATTERNS.md` + ADRs relevantes em `.specs/architecture/ADR-*.md`. Skills aplicáveis em `.skills/`.
4. **Implementar (Agent Mode)** — edits cirúrgicos. Só toca o que a task pede. Sem refactor extra.
5. **Lint + type** — `ruff check .`, `ruff format --check .`, `mypy simplicio`. Vermelho = corrige.
6. **Unit/contract** — `pytest`. Vermelho = corrige (exceto falhas pré-existentes documentadas, sem relação com o diff).
7. **E2E (quando a mudança tocar o harness starter/Playwright)** — `npx playwright test --reporter=list,html`. Captura **trace + screenshot + video** (todos). Sem evidência em `playwright-report/` + `test-results/` = task não fechada.
8. **Fix loop** — falhou? Volta ao 4. Repete até verde.
9. **Commit** — Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`). Mensagem em **inglês**.
10. **PR** — `gh pr create --fill`. Preenche template inteiro.

---

## Definition of Done

PR só faz merge quando todos os itens abaixo estão marcados:

- [ ] `pytest` verde (ou falhas pré-existentes documentadas, sem relação com o diff)
- [ ] **Nenhuma issue ou task fecha sem: implementação + unit + integration + system + regression + benchmark de performance + 85%+ de coverage.** `pytest --cov=simplicio --cov-report=term-missing` reporta o número; abaixo de 85%, fecha a lacuna com teste novo antes de declarar a task feita.
- [ ] `ruff check .` e `ruff format --check .` verdes
- [ ] `mypy simplicio` verde no rigor documentado em `pyproject.toml`
- [ ] E2E Playwright, quando a mudança tocar o starter/harness, **com evidência anexada** — `playwright-report/index.html` + `test-results/<spec>/trace.zip` + screenshots por cenário + video. Hard rule quando aplicável: sem evidência, sem merge.
- [ ] Acceptance Criteria todos marcados (ou partial, com motivo explícito no PR)
- [ ] **Verificação independente/adversarial pós-verde** — uma passada *ortogonal* (não repetição): AC ⇄ resultado, feature rodada de verdade + 1 borda + 1 caminho de erro. Verde ≠ feito. (`.skills/llm-verification/`)
- [ ] PR template preenchido (link task/issue + descrição + evidências)
- [ ] Conventional commit no merge
- [ ] ADR criado se mudou decisão arquitetural
- [ ] Changelog atualizado se release-relevant
- [ ] Sem warning novo, sem `print()`/`console.log` de diagnóstico deixado pra trás em código de biblioteca (exceção documentada: CLI handlers onde stdout é o resultado pretendido)
- [ ] Sem TODO sem dono e sem prazo

O gate bloqueante de cobertura roda em `.github/workflows/ci.yml` e deve ser
exigido pela proteção de `main`. Rode também a validação local documentada em
`docs/ci-quality-gate.md`; os hooks `.claude/hooks/pre-commit.sh`/`.ps1`
aplicam o piso global de 85% quando `pytest-cov` está instalado.

---

## Padrões de código

`.specs/architecture/PATTERNS.md` é a **fonte única**. Naming, estrutura, criação de endpoint/componente/teste, tratamento de erro, logging, validação — tudo lá.

Decisões irreversíveis viram **ADR** em `.specs/architecture/ADR-XXX-*.md` (template em `.specs/architecture/ADR-template.md`).

---

## Observability / unified evidence flow (issues #106, #107)

`simplicio/observability.py`: `emit_data()` -> stdout (resultado pretendido), `info`/`warn`/`error` -> stderr (status humano, respeitando `--quiet`/`--verbose`/`SIMPLICIO_LOG_LEVEL`). `emit_event(event_type, payload, root=)` produz o evento estruturado (`simplicio.dev-cli-event/v1`) que um loop host consome via `<root>/.simplicio/events.jsonl`; já ligado em `pipeline.py` e `mapper.py`. `simplicio-py doctor` mostra um resumo desses eventos. Ruff `T20` bloqueia `print()` novo fora dos CLI handlers documentados.

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
ruff check . && ruff format --check . && mypy simplicio && pytest
# tocou o harness starter/Playwright? roda também: npx playwright test
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

## LLM command and feature index

Use [`docs/CLI_COMMANDS.md`](../docs/CLI_COMMANDS.md) as the complete command
map and run the most specific `--help` before using a command. New commands
must include meaningful `help=` text and a help regression check. Work items
use objective, implementation/deployment, and test evidence; do not add
Acceptance Criteria sections to new or updated issues.

<!-- simplicio-global-llm-architecture-rules:start -->
## Regras arquiteturais obrigatórias para qualquer LLM

Estas regras valem para análise, planejamento, implementação, revisão, testes,
release e documentação neste ecossistema. O agente deve lê-las antes de agir:

1. **Não mantenha compatibilidade retroativa.** O que está obsoleto deve ser
   deletado diretamente. Não adicione camadas de compatibilidade, migrações ou
   fallbacks.
2. **Escolha a implementação mais simples que atende à necessidade atual.**
   Não crie abstrações preventivas nem camadas de configuração desnecessárias.
3. **Divida o sistema em camadas longas.** Faça primeiro uma versão mínima
   end-to-end funcionando; depois adicione capacidades por cima. Não desmonte
   algo que funciona por complexidades inacabadas.
4. **Mantenha os componentes modulares**, com responsabilidades claramente
   separadas e limites explícitos.
5. **Priorize bibliotecas maduras e mantidas.** Não reescreva do zero sem
   motivo técnico explícito e registrado.
6. **Inspecione primeiro as dependências existentes.** Antes de adicionar um
   pacote ou escrever uma solução própria, verifique o que o projeto já possui.
7. **Decida a arquitetura pensando no longo prazo.** Não aceite soluções
   temporárias com a intenção de mudar depois.
8. **Use padrões de produtos maduros.** Pesquise como soluções consolidadas
   resolvem o mesmo problema e reutilize padrões validados; não reinvente a roda.

<!-- simplicio-global-llm-architecture-rules:end -->

