# AGENTS.md

## Simplicio Ecosystem Contract (canonical)

This repository is one component of the Simplicio ecosystem. For every non-trivial task: run `simplicio runtime map --repo . --for-llm markdown`, then `simplicio memory "<task>"`, rank/load relevant skills, execute through the native `simplicio` CLI, validate, and record evidence. MCP is fallback transport only.

### Boundaries and handoff
`simplicio-mapper` observes and emits bounded context; `simplicio-fast` owns snapshots/mmap/PlanDAG; `simplicio-dev-cli` owns focused implementation plans and deterministic edits; `simplicio-runtime` owns contracts, gates, validation and receipts; `simplicio-loop` owns convergence, journals, watcher/close-gates and learning; `simplicio-agent` owns the control plane and conversation. Providers are workers, never authorities.

Use `simplicio`/`simplicio shell compact` for inspection, `simplicio edit --plan` or governed dev-cli for mutation, preserve `simplicio.io/v1`, run `simplicio contracts smoke --json` and `simplicio validate "<task>" --repo . --json`, and close only with real tests plus `simplicio evidence`. Facts are `MEASURED|` only with receipts; otherwise `UNVERIFIED|`. Savings come only from `simplicio savings report --repo . --json`. Missing dependencies fail closed; never fabricate context, tests, savings or provider output.

> Canonical pattern spec: [YOOL_TUPLE_HAMT.md](YOOL_TUPLE_HAMT.md)
>
> Receipt schema reference: [YOOL_TUPLE_HAMT.md §1.8.4](YOOL_TUPLE_HAMT.md#184-receipt-schema-reference)

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

Project identity (this repo is the canonical scaffold itself, so no host
placeholders — fill these row-by-row when copying the file into a host
project):

| Slot | Value here |
|---|---|
| App name | `simplicio-mapper` (npm `@wesleysimplicio/llm-project-mapper`) |
| Frontend URL | n/a — CLI tool, no UI runtime |
| Backend URL | n/a — local mapper, no service endpoint |
| Database | n/a — file-system only, optional `diskcache` on disk |
| Auth flow | n/a — no user auth; PyPI/npm tokens via repo secrets only |
| Evidence command | `npx playwright test --reporter=list,html` (writes to `playwright-report/` + `test-results/`) |

Agent checklist:

- [ ] Confirm whether the project lives at repo root or under `projects/`.
- [ ] Read `docs/local-setup.md` and relevant `docs/features/*`.
- [ ] Confirm real start/test/build commands.
- [ ] Run validation before edits when practical.
- [ ] Keep changes small and scoped.
- [ ] Run relevant tests/build after edits.
- [ ] Generate screenshot/video/trace for UI or end-to-end flows.
- [ ] Report blockers with the command, log excerpt and likely cause.

> Master instruction file lido por **Claude Code**, **Codex CLI**, **GitHub Copilot**, **Simplicio Agent** (consumidor/integrador canônico — `simplicio-agent`), **Hermes Agent** (Nous Research, alias depreciado), **OpenClaw**, **Cursor**, **Aider** e qualquer outro agent que respeite o padrão `AGENTS.md`. É o contrato entre humano e IA neste repositório.
>
> Mudou algo aqui? **Este arquivo é a única fonte editada à mão** (issue #163). `CLAUDE.md` é **gerado** a partir dele — depois de editar, rode `node scripts/check-doc-sync.js sync` (CI roda `check` e falha se esquecer). `.github/copilot-instructions.md` não é mais um hand-copy: é um stub curto que aponta pra cá para tudo que não é específico de Copilot Agent Mode — só precisa de edição manual se a mudança afetar algo genuinamente específico do Copilot.

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

**Python 3.10+ (`orjson`, `diskcache`) + Node.js CLI + optional Rust/PyO3 acceleration crate + Playwright E2E.**

Detalhes:

- Linguagem principal: **Python 3.10+** (canonical PyPI package `simplicio-mapper`); um espelho Node 18+ vive em `bin/cli.js` + `bin/mapper-artifacts.js` mantido em paridade.
- Framework web/API: n/a — projeto é um CLI/library.
- Banco de dados: n/a — cache opcional em disco via `diskcache` (`.simplicio/cache/`).
- Test runner unit: **`python -m unittest discover -s tests/python`** (também roda via `pytest tests/python -q`) e **`node --test tests/unit/*.test.js`**.
- Test runner E2E: **Playwright** (config em `playwright.config.ts`).
- Linter/formatter: **`ruff`** (Python, ver `[tool.ruff]` em `pyproject.toml`) e `node scripts/lint.js` (shell + JS).
- CI/CD: GitHub Actions (ver `.github/workflows/`). DoD gate em `dod.yml`. Publish em `publish-pypi.yml` (PyPI-only desde 0.7.x).
- Distribuição: **PyPI** `simplicio-mapper` é o motor canônico do mapper; o pacote npm `@wesleysimplicio/llm-project-mapper` continua **ativo** como canal do scaffolder e shim Node.
- Opt-in: crate Rust em `rust/` build via `maturin develop --release` (ADR-002).

> Antes de adicionar dependência nova: **pergunta ao usuário**. Sem exceção.

---

## Comandos importantes

```bash
# desenvolvimento / smoke local
node bin/cli.js --help                       # CLI Node
python -m simplicio_mapper.cli --help        # CLI Python (canonical)
python -m build                              # gera dist/*.whl + .tar.gz

# qualidade
npm run lint                                 # JS + shell lint (scripts/lint.js)
ruff check simplicio_mapper tests/python     # Python lint
node scripts/check-version-sync.js           # versões alinhadas (package/pyproject/__init__)
python -m unittest discover -s tests/python  # Python unit
node --test tests/unit/*.test.js             # Node unit
npm test                                     # cross alias (chama node --test)

# E2E
npx playwright install                       # instala browsers (1ª vez)
npx playwright test                          # roda suite E2E
npx playwright test --ui                     # modo interativo
npx playwright show-report                   # abre relatório último run

# Rust opt-in
(cd rust && maturin develop --release)       # builda extensão nativa no venv
python -m pytest tests/python/test_native.py # cobre o caminho nativo

# git/PR
git checkout -b feat/<task-id>-<slug>
gh pr create --fill                          # usa template de PR
gh run watch                                 # acompanha CI do branch atual
```

## Índice canônico para LLMs e contrato de `--help`

O inventário completo de funcionalidades, comandos, aliases, subcomandos
roteados e exemplos de descoberta está em
[`docs/CLI_COMMANDS.md`](docs/CLI_COMMANDS.md). Esse arquivo é a referência
curta que um LLM deve carregar antes de escolher uma operação.

Regras de descoberta:

- `simplicio-mapper --help` e `node bin/cli.js --help` são os pontos de entrada
  oficiais; não invente comandos a partir de nomes de módulos internos.
- Todo comando público precisa responder a `--help` (ou `-h`) com propósito,
  uso, opções e comportamento de saída. Os comandos roteados fora do parser
  principal (`contract`, `canonical`, `benchmark`, `version`, `release-manifest`,
  `changelog` e os demais listados no inventário) mantêm seu próprio help.
- Antes de executar uma operação, consulte o help do nível correspondente:
  `simplicio-mapper <comando> --help` e, quando houver, o subcomando também.
- Saída para automação é JSON versionado quando `--json` estiver disponível;
  preserve o campo `schema` e trate versões major desconhecidas como
  incompatíveis.
- Para issues do GitHub, descreva objetivo, implementação/implantação e testes
  na seção `Execução`; não crie nem reintroduza uma seção `Acceptance Criteria`
  ou `Critérios de aceite`.

O mesmo contrato é espelhado em `CLAUDE.md`, `GEMINI.md`, `llms.txt` e no
stub do Copilot. Ao alterar comandos ou funcionalidades, atualize o índice e
rode `node scripts/check-doc-sync.js sync` antes de commitar.

## Shell token-smart (RTK CLI, opcional)

Se `rtk` estiver instalado na máquina, prefira-o em tarefas shell-heavy e de exploração para reduzir ruído e consumo de tokens:

```bash
rtk read AGENTS.md
rtk grep "pattern" src/
rtk find "*.ts" .
rtk git status
rtk git diff
rtk git log -n 10
rtk npm test
```

Regras:

- Use `rtk read` / `rtk grep` / `rtk find` / `rtk git ...` como primeira opção quando o objetivo é inspeção textual compacta.
- Use `rtk <comando>` em validações verbosas quando o output resumido basta para decidir o próximo passo.
- **Não** passe por RTK comandos interativos, streaming ou em que o output bruto é a evidência principal (`curl`, `playwright`, `gh pr view --web`, logs longos que precisam ser preservados verbatim).
- Se `rtk` não estiver instalado, siga com os comandos normais sem bloquear a task.

---

## Token/context budget guard (issue #174)

`scripts/token_budget.py` porta o padrão do `simplicio-loop`
(`scripts/token_budget.py` lá) para este repo: estima em tokens o custo de
abrir os artefatos que um agent/LLM tipicamente lê inteiros neste projeto —
`AGENTS.md`, `CLAUDE.md`, os maiores módulos de `simplicio_mapper/` (hoje
`mapper/parse.py`, `mapper/graph.py`, `mapper/emit.py`, `cli/_flowchart.py`,
`toon.py`) e os artefatos `.simplicio/*.json`-shaped já commitados em
`contracts/mapper-artifacts/v1/fixtures/python-minimal/artifacts/`
(saída real do mapper contra a fixture `python-minimal`, issue #157;
regenerar com `python3 scripts/regen_contract_fixtures.py update`) — e falha
se algum artefato crescer mais que 25% acima do baseline commitado em
`scripts/token_budget_baseline.json`.

```bash
python3 scripts/token_budget.py                    # relatório + gate contra o baseline
python3 scripts/token_budget.py --check             # mesmo, silencioso a menos que falhe (usado no CI)
python3 scripts/token_budget.py --update-baseline   # regenera o baseline após mudança deliberada de tamanho
python3 scripts/token_budget.py --self-test         # prova negativa: o guard falha de verdade numa regressão simulada
```

Estimador default: heurística stdlib `heuristic:chars-div-4` (~4
caracteres/token); usa `tiktoken` (cl100k_base) quando instalado, sem ser
dependência do pacote. Ligado no CI real deste repo em `python-ci.yml`
(job `python-tests`, step "Token/context budget guard") — `dod.yml`/`ci.yml`
são pulados neste repo (ver notas nos próprios arquivos), então o gate real
vive nos workflows Python.

## Delegação nativa ao runtime `simplicio` (F10 `ask`, issue #174)

`simplicio_mapper/query.py` (F10 `ask`) já delegava `ask precedent` para o
binário Rust `simplicio` (runtime) quando presente no PATH — busca
SQLite/FTS5, envelope validado, timeout de 10s, kill-switch
`SIMPLICIO_MAPPER_NO_RUNTIME_PRECEDENT`, fallback local automático em
qualquer falha. Issue #174 estendeu o MESMO padrão para mais dois verbos,
escolhidos por medição real (não achismo) — ver
`scripts/measure_verbs.py` e o relatório commitado
`scripts/measure_verbs_report.json`, rodado contra a fixture
`contracts/mapper-artifacts/v1/fixtures/python-minimal/source`:

| Verbo | Kill-switch | Por quê |
|---|---|---|
| `ask impact` | `SIMPLICIO_MAPPER_NO_RUNTIME_IMPACT` | ~73x mais caro que o verbo `ask` mais barato (`callers`/`callees`), isolando o custo de `build_artifacts()` (que todo `ask` já paga hoje, ver limitação abaixo) — recomputa flow-inventory do zero e varre todo `.specs/**`/`docs/**` a cada chamada. |
| `ask tests-for` | `SIMPLICIO_MAPPER_NO_RUNTIME_TESTS_FOR` | ~8x mais caro que o mais barato — lê o texto inteiro de cada arquivo de teste a cada chamada, sem cache. |

Mesmo padrão do `precedent`: `shutil.which("simplicio")`, envelope
`simplicio.ask/v1` validado (`schema`/`results`/`total` presentes) antes de
confiar, timeout de 10s, fallback local automático (`_impact`/`_tests_for`)
em qualquer falha — binário ausente, kill-switch setado, exit != 0, timeout,
JSON malformado ou schema não bate. Nenhum silent fake-pass: uma falha do
binário nativo cai no fallback local existente, nunca finge sucesso.

**Savings por verbo**: todo hit nativo (`impact`/`tests-for`) grava um
evento `simplicio.savings-event/v1` em
`<repo>/.simplicio/ledger/savings-events.jsonl` via
`simplicio_mapper/savings.py` (`record_savings_event`, espelha o formato de
`simplicio-dev-cli`'s `simplicio/observability.py::record_savings_event`,
sem importar código de lá) — `source=native-delegation:<verbo>`,
`baseline_tokens`/`actual_tokens`/`saved`/`pct_saved`, `proof_kind` sempre
`"estimated"` aqui (nenhuma chamada real de LLM mede o gasto, então nunca é
apresentado como `"measured"`), com `note` declarando o método do baseline
(`heuristic:chars-div-4`, mesma heurística do token-budget guard acima).
Kill-switch em `SIMPLICIO_DISABLE_RUN_LOG` (compartilhado com os outros
produtores JSONL do ecossistema) desliga a gravação; falha de escrita nunca
propaga para o caminho de query (best-effort).

**Limitação conhecida, documentada e fora de escopo aqui**: `run_query`
ainda chama `build_artifacts()` incondicionalmente antes de despachar para
qualquer verbo — inclusive quando o caminho nativo vai responder e não
precisaria dos artefatos locais (o mesmo já valia para `precedent` antes
desta issue). A delegação nativa desta issue elimina o custo específico da
lógica de `impact`/`tests-for`, não esse custo compartilhado; tornar
`build_artifacts()` lazy por verbo é um refactor maior, fora do escopo
cirúrgico pedido aqui.

**`contract`/`impact`/`tests-for` não são comandos de topo-de-nível da
CLI** (`simplicio_mapper/cli/_args.py`, tupla `commands`): `impact` e
`tests-for` só existem como sub-verbos de `ask` (`simplicio-mapper ask
<root> impact|tests-for <arg>`); `contract` existe como subcomando
especial, despachado antes de `_parse_args` em `cli/__init__.py::main`,
mas serve para validação de contrato de artefatos (`simplicio-mapper
contract validate ...`), não tem relação com F10 `ask`.

---

## Padrão de sincronização deste projeto

Para este repositório, sempre que a mudança for **release-relevant**, o fechamento padrão deve deixar tudo sincronizado no mesmo ciclo:

- npm publicado na versão atual de `package.json`
- tag GitHub `vX.Y.Z` criada e enviada
- GitHub Release correspondente criada/atualizada
- `main` limpa e sincronizada com `origin/main`

Validação padrão obrigatória antes de publicar/sincronizar:

```bash
npm run lint
npm test
npm run docs:build
npm run test:e2e -- --reporter=list,html
```

Se qualquer item acima falhar, **não** publique e **não** crie a release/tag até corrigir.

---

## Workflow loop OBRIGATÓRIO

Toda task técnica passa por esses passos. Não pula etapa.

1. **Ler task** — abre arquivo em `.specs/sprints/sprint-XX/<task-id>.task.md`. Lê contexto + acceptance criteria + test plan + DoD.
2. **Planejar** — escreve plano interno curto: o que muda, quais arquivos, como verificar, efeitos colaterais. Se task ambígua → pergunta antes de codar.
3. **Carregar contexto** — lê `.specs/architecture/PATTERNS.md` + ADRs relevantes em `.specs/architecture/ADR-*.md`. Verifica skills aplicáveis em `.skills/`.
4. **Editar** — aplica edits cirúrgicos. Só toca o que a task pede. Sem refactor extra, sem renomeação, sem comentário a mais.
5. **Lint** — `npm run lint`. Vermelho = corrige antes de seguir.
6. **Unit** — `npm test`. Vermelho = corrige antes de seguir. Coverage do diff >= 80%.
7. **E2E (condicional ao risco/superfície da mudança — issue #162)** — obrigatório **apenas quando a task toca um fluxo end-to-end observável**: CLI ponta-a-ponta sobre uma fixture (`simplicio-mapper index|map|contract ...` rodado de verdade contra um projeto real), o bootstrap/scaffold (`bin/cli.js` instalando o starter num host), o docs-site, ou qualquer superfície com UI navegável. Quando aplicável: `npx playwright test --reporter=list,html`, captura **trace + screenshot + video**. **Quando a task só mexe em parser/serialização/emissão interna, docs, ou refactor sem mudança de comportamento observável, `unit + lint` bastam** — não force Playwright onde não há navegador nem fluxo pra gravar. Ver critério completo logo abaixo desta lista.
8. **Fix loop** — se qualquer etapa falhou: volta ao passo 4. Repete até verde.
9. **Commit** — Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`). Mensagem em **inglês**. Body explica *why*, não *what*.
10. **PR** — `gh pr create`. Preenche template inteiro: link da task, evidências (Playwright quando aplicável, ou snapshot de output/artefato — ver critério abaixo), checklist DoD marcado.

### Critério de "E2E obrigatório" vs "unit+lint bastam" (issue #162)

Este projeto é majoritariamente uma **CLI/lib** (não uma aplicação web com UI
navegável), então "E2E em TODA task, sem exceção" nunca fez sentido literal
aqui — a regra antiga virou dogma descolado da superfície real do projeto.
Critério explícito, substitui o "obrigatório sempre" anterior:

- **E2E (Playwright) obrigatório quando:** a mudança altera um fluxo
  end-to-end observável — comportamento do `bin/cli.js` scaffolder
  instalando num host, o docs-site (`docs-site/`), ou qualquer tela/rota
  navegável que este repo venha a ganhar. Nestes casos, a evidência
  continua sendo `playwright-report/index.html` + `test-results/<spec>/trace.zip`
  + screenshot + video.
- **Unit + lint bastam quando:** a mudança é em parsing/AST/regex
  (`simplicio_mapper/mapper.py`, `bin/mapper-artifacts.js`), serialização
  de artefatos JSON, um script standalone (`scripts/*.py`, `scripts/*.js`),
  documentação, ADRs, ou um refactor interno que não muda comportamento
  observável de nenhum comando. Não existe "fluxo de UI" pra gravar nesses
  casos — exigir um vídeo Playwright deles é teatro de compliance, não
  evidência real.
- **"Evidência" para uma task CLI/lib (não-browser)** — issue #162
  redefine o termo: em vez de "só existe evidência = vídeo Playwright",
  conta como evidência válida **qualquer captura de execução real**:
  stdout do comando real capturado num arquivo/trecho do PR
  (`simplicio-mapper index <fixture> --json > /tmp/out.json`, colado no
  PR), o artefato `.simplicio/*.json`/`contracts/*/fixtures/*` gerado de
  verdade, ou o output de `python3 -m unittest`/`node --test` para o
  arquivo específico que mudou. O que continua proibido é "não rodei nada,
  confio que está certo" — alguma evidência de execução real sempre é
  exigida, só não é sempre um vídeo de navegador.
- Na dúvida sobre qual lado do critério a task cai, trate como
  "E2E obrigatório" (mais seguro) e documente a decisão no PR.

---

## Definition of Done

PR só faz merge quando **todos** os itens abaixo estão marcados:

- [ ] Unit tests passam (`npm test` verde)
- [ ] Lint passa (`npm run lint` verde)
- [ ] **Evidência de execução real, proporcional ao risco/superfície** (critério completo na seção "Workflow loop" acima, issue #162): quando a task toca um fluxo end-to-end observável (scaffolder, docs-site, UI navegável) — E2E Playwright com `playwright-report/index.html` + `test-results/<spec>/trace.zip` + screenshot + video; caso contrário (parser/serialização/script/refactor interno/docs) — snapshot do output/artefato real (stdout capturado, `.simplicio/*.json` gerado, resultado do `unittest`/`node --test` específico). Hard rule: sem NENHUM tipo de evidência de execução real, sem merge — mas não é sempre vídeo de navegador.
- [ ] Coverage do diff >= 80%
- [ ] Acceptance Criteria da task: todos os checkboxes marcados
- [ ] PR template preenchido (link task + descrição + evidências)
- [ ] Conventional commit no merge
- [ ] ADR criado em `.specs/architecture/` se mudou decisão arquitetural
- [ ] Changelog atualizado se release-relevant
- [ ] Sem warning novo no console
- [ ] Sem `console.log` / `print` / `Debug.WriteLine` deixado pra trás
- [ ] Sem TODO sem dono e sem prazo

CI bloqueia merge se DoD falhar (`.github/workflows/dod.yml`).

### DoD específico do pacote Python (`simplicio_mapper/`)

O checklist acima é o DoD genérico do scaffold (Node/npm). Para trabalho dentro
de `simplicio_mapper/` (o pacote Python canônico), nenhuma issue/task fecha
sem cobrir as **7 dimensões** abaixo — regra explícita, não é opcional:

- [ ] **Implementation** — o código de produção que a task pede, sem escopo extra.
- [ ] **Unit** — cobre a lógica isolada do módulo tocado (`tests/python/test_*.py`).
- [ ] **Integration** — cobre a interação entre módulos/CLI (ex.: dispatch via `main()`, `cli/_repo_commands.py`).
- [ ] **System** — cobre o fluxo ponta-a-ponta via entry point real (ex.: `simplicio-mapper snapshot ...` contra um repo de verdade), não só unidades isoladas.
- [ ] **Regression** — todo bug real corrigido ganha um teste que trava a regressão (não só o fix).
- [ ] **Perf benchmark** — quando a mudança toca caminho quente (retrieval, indexação, parsing em escala), roda `python3 scripts/runtime_scale_benchmark.py` (ou o benchmark relevante em `scripts/*_benchmark.py`) e reporta o número; não é "achismo".
- [ ] **Coverage >= 85%** — piso do pacote Python. O gate real de CI (`.github/workflows/python-ci.yml`, job `python-tests`) já roda `python -m pytest tests/python -q --cov=simplicio_mapper --cov-report=term --cov-fail-under=88`, ou seja, o piso de CI (88%) é mais estrito que este mínimo (85%) — nunca reduzir o `--cov-fail-under` do workflow para acomodar uma task.

Comando de verificação local (mesmo usado no CI):

```bash
python -m pytest tests/python -q --cov=simplicio_mapper --cov-report=term --cov-fail-under=88
```

---

## Padrões de código

Padrões completos em `.specs/architecture/PATTERNS.md`. Resumo:

- Naming, estrutura de pastas, criação de endpoint/componente/teste, tratamento de erro, logging, validação — **tudo lá**.
- Decisões irreversíveis viram **ADR** em `.specs/architecture/ADR-XXX-*.md` (template em `.specs/architecture/ADR-template.md`).
- Antes de escrever código novo: lê `PATTERNS.md` da seção relevante. Não inventa estilo próprio.

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

- **Pular validação** — sem unit/lint = sem merge. E2E é obrigatório apenas quando a mudança toca um fluxo end-to-end observável (critério em "Workflow loop", passo 7, issue #162) — pular Playwright numa task que genuinamente não tem fluxo pra gravar não é "pular teste", é seguir o critério; pular quando o critério pede E2E, isso sim é proibido.
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
- **`everything-claude-code`** — bundle de ~60 agents + ~221 skills. Padrão (issue #162: **proporcional ao risco**, não mais "sempre o máximo"): edits pequenos/locais (parser, docs, refactor isolado) → 1-2 reviewers focados na área tocada; mudanças arquiteturais, de segurança, release-sensitive, ou que tocam múltiplos módulos → mais agents ECC em paralelo (single message, múltiplas Agent calls) se o risco justificar. Reviewers da stack + `security-reviewer` continuam obrigatórios após edits que tocam superfície de segurança ou de release.

### Sob demanda

- **`rtk-cli`** — usa RTK CLI para reduzir tokens em exploração de repositório, git, grep/find e comandos shell verbosos sem perder o sinal técnico.
- **`playwright-e2e`** — como escrever teste Playwright neste projeto. Trigger: nova feature de UI ou fluxo end-to-end. Cobre fixtures, page objects, evidências (trace/screenshot/video) e padrões de assert.
- **`conventional-commits`** — regras de commit (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `perf:`, `style:`, `ci:`, `build:`). Trigger: hora de commitar. Inclui exemplos, breaking changes (`!`/`BREAKING CHANGE:`) e scope.
- **`_template`** — base pra criar skill nova. Copia, renomeia pasta, preenche frontmatter (`name`, `description`, `trigger`, `steps`, `dod`).

Detalhes completos: `.skills/README.md`.

---

## Custom agents disponíveis

Sub-agents customizados moram em `.agents/<slug>.agent.md` (padrão **AGENTS.md ecosystem**, lido por Claude Code, Codex, Simplicio Agent, Hermes, OpenClaw, Cursor, Aider). Espelhados em `.github/copilot/agents/` para o GitHub Copilot Workspace. Lista atual:

- **`ralph-loop.agent.md`** — Ralph Loop (padrão autônomo, Ralph Wiggum technique). Loop `read → plan → execute → lint → unit → Playwright → fix → repeat` até DoD verde. **Mapeia para comando nativo de cada ferramenta**: Claude Code → `/ralph-loop "<prompt>"` (plugin oficial `claude-plugins-official`); Codex CLI ≥0.128 → `/goal <objective>`; GitHub Copilot CLI → `copilot --autopilot --max-autopilot-continues N`; VS Code Agent Mode → permission level "Autopilot"; Cursor ≥3.0 → Background Agent / `/multitask`. Aciona em **toda task técnica** com AC mensurável. Tools: `edit`, `terminal`, `search`.
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
npm run lint && npm test -- --coverage && npx playwright test
# se tudo verde -> git commit && git push && gh pr create --fill
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

<!-- yool-tuple-hamt:start -->
## yool / tuple / HAMT (capability addressing)

Spec: [`YOOL_TUPLE_HAMT.md`](YOOL_TUPLE_HAMT.md) (vendored from https://github.com/wesleysimplicio/yool-tuple-hamt, version v0.2).

Every agent registered in this repo MUST declare its capability with the following fields (header `### <Agent Name>` followed by frontmatter-style lines):

```markdown
### My Agent

- yool_id: `agent.dev.python`            # namespace.verb.object, kebab/dot-case
- authority: dev | ops | review | audit  # who is allowed to dispatch this yool
- lane: fast | slow | background         # scheduling lane
- agent_terms:
    cpu_quota_pct: 60       # MANDATORY guardrail (spec §11.1)
    disk_quota_mb: 100      # MANDATORY guardrail (spec §11.2)
    timeout_s: 300
```

Why these fields exist:

- `yool_id` — atomic opcode; key into the HAMT registry; stable across renames of the agent's display name.
- `authority` — gating: only authorized lanes may `in` a tuple addressed to this yool.
- `lane` — Linda-style channel partition; lets workers subscribe selectively.
- `agent_terms.cpu_quota_pct` — soft throttle via `os.nice` or cgroups. Per Victor Genaro's guardrail: *"precisa de guardrail pra não fritar o processador."*
- `agent_terms.disk_quota_mb` — local disk cap before GC kicks in. Per the same review: *"você precisa de garbage collector também pra não encher 100% do disco."*

### Receipts schema

Every repo using this pattern should keep execution receipts under `.receipts/` and treat them as append-only execution evidence, not ad-hoc logs.

Minimum receipt contract:

```json
{
  "id": "sha256:<content-hash>",
  "tuple_id": "sha256:<tuple-hash>",
  "yool_id": "agent.dev.python",
  "status": "ok",
  "created_at": "2026-05-19T17:30:00Z",
  "artifacts": [],
  "cost": {
    "tokens": 0,
    "usd": 0
  }
}
```

Canonical source for receipt semantics, retention, and catalog placement: [YOOL_TUPLE_HAMT.md §1.8.4](YOOL_TUPLE_HAMT.md#184-receipt-schema-reference).

Build the HAMT catalog with:

```bash
node bin/build-hamt-catalog --source AGENTS.md --output .catalog/agents.json
```

Without all four fields, the catalog build skips the entry. CI gate enforces full population for any new agent declaration.

<!-- yool-tuple-hamt:end -->

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
