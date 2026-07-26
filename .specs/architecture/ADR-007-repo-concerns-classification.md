# ADR-007: `Classificação de concerns do repo (tool / scaffold / site-marketing / meta-doc) + corte mínimo seguro`

> Resolve https://github.com/wesleysimplicio/simplicio-mapper/issues/161

---

## Status

`Aceito` (corte mínimo — ver escopo abaixo)

---

## Data

`2026-07-07`

---

## Autores

- `Claude (agent) — a pedido de wesleysimplicio`

---

## Contexto

Este repositório mistura, sob uma raiz só, quatro concerns bem diferentes:
o **tool** (o mapper de verdade), o **scaffold/template** que o tool
distribui (`bin/cli.js`'s `TEMPLATE_PATHS`), material de **site/marketing**
(landing page, vídeos, apresentação), e uma pilha de **meta-docs** na raiz.
A issue #161 pede: inventariar, classificar, e cortar o mínimo seguro pra
reduzir o artefato publicado — sem quebrar o scaffolder nem os links que já
existem.

## Inventário + classificação

| Item | Classificação | Publicado hoje? |
|---|---|---|
| `simplicio_mapper/`, `bin/`, `rust/`, `scripts/`, `contracts/`, `package.json`, `pyproject.toml`, `action.yml`, `template-manifest.json` | **tool** | sim (PyPI wheel/sdist + npm) |
| `AGENTS.md`, `CLAUDE.md`, `INIT.md`, `INIT.en.md`, `_BOOTSTRAP.md`, `YOOL_TUPLE_HAMT.md`, `README.md`, `README.pt-BR.md`, `INSTALL.md`, `INSTALL.en.md`, `.agents/`, `.claude/`, `.codex/`, `.github/` (parcial), `.skills/`, `.specs/`, `docs/` (parcial), `bootstrap.sh`, `bootstrap.ps1`, `playwright.config.ts`, `tests/` (parcial) | **scaffold/template** — literalmente `bin/cli.js`'s `TEMPLATE_PATHS` / `template-manifest.json`'s `template_root_paths` (ADR-004) | sim, no pacote npm (é o produto do scaffolder) |
| `docs-site/` (Docusaurus), `presentation/`, `video/`, `assets/`, `READMEs/` (traduções da landing page), `SHOWCASE.md` | **site/marketing** | `docs-site/`, `presentation/`, `video/` **já não estavam** em `package.json`'s `files` nem em `pyproject.toml`'s include-lists — só `assets/` estava incluído no npm (ver corte abaixo) |
| `PYPI.md` | **meta-doc, mas obrigatório na raiz** — é o `readme` do `pyproject.toml`; hatchling resolve `readme` relativo à raiz do projeto | sim (é literalmente o texto do PyPI) |
| `TOON-CONTRACT.md`, `YOOL_TUPLE_HAMT.md`, `SIMPLICIO_INTEGRATION.md`, `SIMPLICIO_ECOSYSTEM.md` | **meta-doc técnico, fortemente linkado** (dezenas de referências cruzadas em README/AGENTS.md/contracts/scripts/testes) | sim (`SIMPLICIO_INTEGRATION.md` no wheel/sdist Python) |
| `PRD.md`, `PROGRESS.md`, `GOAL_RESULT.md` | **meta-doc, mas convenção padrão entre-repos** — ver "Por que NÃO movidos" abaixo | não publicados hoje |
| `.catalog/`, `.simplicio/orchestrator/`, `.serena/`, `.simplicio/`, `.ruff_cache/`, `.llm-project-mapper.json` | **artefato de ferramenta/cache local** | não publicados (fora das listas de `files`/`include`) |
| `packaging/`, `vscode-extension/`, `examples/`, `fixtures/` | **auxiliar de build/exemplo** | não publicados hoje |

## Decisão — corte mínimo seguro

### 1. `assets/` sai de `package.json`'s `files` (feito, verificado)

`assets/` (8.4 MB, 4 PNGs "hero" de ~2 MB cada, usados só em tags
`<img>` do README pra exibição no GitHub/npm) estava incluído em
`package.json`'s `files` mas **não está em `TEMPLATE_PATHS`** — nenhum
código (`bin/*.js`, `simplicio_mapper/*.py`) referencia `assets/` fora do
markdown do README. GitHub/npmjs.com renderizam essas imagens direto do
repositório/registry, não do pacote instalado — nenhum consumidor do
pacote instalado precisa desses arquivos em disco. Removido de `files`;
`npm pack --dry-run` cai de **10.4 MB / 261 arquivos** para **~2 MB / 256
arquivos** (medido antes/depois, ver PR).

### 2. `video/`, `docs-site/`, `presentation/` — já não publicados (nada a fazer)

Verificado: nenhum dos três aparecia em `package.json`'s `files` nem em
`pyproject.toml`'s `[tool.hatch.build.targets.wheel]`/`[tool.hatch.build.targets.sdist]`
include-lists antes desta ADR. `python -m build --wheel` já produzia um
wheel contendo só `simplicio_mapper/`. O AC da issue ("verificar que
video/presentation/docs-site/assets não vão no artefato publicado") já
estava satisfeito pros três primeiros; só `assets/` precisava do corte
acima.

### 3. Consolidação de `.md` da raiz — **NÃO feita nesta ADR** (risco real, não cosmético)

A issue pede "mover docs de processo/relatório pra `docs/`, deixar só
README/LICENSE/CHANGELOG/CONTRIBUTING-like na raiz". Analisando cada
candidato real:

- **`PRD.md`/`PROGRESS.md`/`GOAL_RESULT.md`** — não são lixo de processo
  desta sessão: são a convenção padrão do "Universal Long-Running Agent
  Overlay" que `CLAUDE.md`/`AGENTS.md` documentam explicitamente ("PRD.md
  is the task source of truth for long-running sessions", etc.) — a mesma
  convenção de raiz aparece em `simplicio-runtime` e `simplicio-dev-cli`
  (outros repos do ecossistema, mesmo texto). Mover só neste repo quebra
  uma expectativa entre-repos (ferramentas/agents que procuram `PRD.md` na
  raiz de qualquer repo Simplicio não achariam mais aqui). **Risco real,
  não cosmético — não movido.**
- **`AGENTS.md`, `CLAUDE.md`, `INIT.md`, `INIT.en.md`, `_BOOTSTRAP.md`,
  `YOOL_TUPLE_HAMT.md`, `README.md`, `README.pt-BR.md`, `INSTALL.md`,
  `INSTALL.en.md`** — são literalmente `TEMPLATE_PATHS`
  (`bin/cli.js`) — mover qualquer um pra `docs/` quebra o scaffolder (ele
  copia esses caminhos exatos pro host). **Não movidos.**
- **`PYPI.md`** — é o `readme` declarado em `pyproject.toml`; hatchling
  resolve caminhos de `readme` relativos à raiz do projeto. Mover exigiria
  editar `pyproject.toml` E confirmar que o build ainda resolve — possível,
  mas sem ganho real (é 1 arquivo, ~5 KB) frente ao risco de quebrar o
  publish. **Não movido.**
- **`TOON-CONTRACT.md`, `SIMPLICIO_INTEGRATION.md`,
  `SIMPLICIO_ECOSYSTEM.md`** — dezenas de referências cruzadas
  (`README.md`, `AGENTS.md`, `contracts/*/README.md`, `scripts/README.md`,
  testes, o próprio `SIMPLICIO_INTEGRATION.md`) apontam pro caminho atual
  na raiz. Mover exigiria atualizar cada referência sem quebrar nenhuma —
  uma tarefa real e válida, mas um escopo próprio, não um "corte mínimo".
  `SIMPLICIO_ECOSYSTEM.md` também é **gerado** (issue #156) com o caminho
  hard-coded no gerador. **Não movidos.**
- **`SHOWCASE.md`** — pequeno (1.1 KB), baixo risco, mas também baixo
  ganho; deixado de fora deste corte por não valer, sozinho, o
  overhead de revisão de uma mudança de caminho.

**Resultado honesto**: a raiz continua com a mesma quantidade de arquivos
`.md` depois desta ADR. O ganho real e mensurável desta issue é o corte de
`assets/` (item 1) — que é also o que efetivamente reduz o artefato
publicado, que era o objetivo mensurável do AC ("prova que o artefato
encolheu"). A reorganização de arquivos de processo é documentada aqui como
avaliada e conscientemente adiada, não esquecida.

---

## Consequências

### Positivas (+)

- Pacote npm publicado cai de 10.4 MB para ~2 MB (medido) sem perder
  nenhuma funcionalidade (nenhum código depende de `assets/`).
- Classificação documentada evita reabrir a mesma pergunta ("por que
  `video/`/`docs-site/` não estão no pacote?") — já eram excluídos, agora
  está registrado o porquê.

### Negativas (-)

- A raiz continua com uma lista longa de arquivos `.md` — a issue #161 não
  foi satisfeita no ponto "raiz com poucos .md, resto em docs/". Ver
  Critério de revisão.

### Neutras / observações

- `assets/` continua existindo no **git**, só não é mais publicado no
  pacote npm — GitHub/npmjs.com continuam mostrando as imagens do README
  normalmente (renderização direta do repositório/registry, não do tarball
  instalado).

---

## Alternativas consideradas

### Alternativa A — mover PRD.md/PROGRESS.md/GOAL_RESULT.md pra docs/ mesmo assim
- Descartada: quebra a convenção padrão entre-repos documentada no próprio
  "Universal Long-Running Agent Overlay" — risco real de ferramentas
  externas (ou operadores humanos treinados na convenção) não acharem os
  arquivos onde esperam em QUALQUER repo Simplicio.

### Alternativa B — mover os meta-docs técnicos (TOON-CONTRACT.md etc.) e atualizar todas as referências
- Tecnicamente viável, mas é um escopo de PR próprio (dezenas de arquivos
  de referência pra atualizar, mais o gerador de `SIMPLICIO_ECOSYSTEM.md`).
  Adiada pra não misturar um refactor de path-rewriting grande com o corte
  de pacote, que é o item de maior valor mensurável desta issue.

### Alternativa C — não fazer nada
- Descartada: `assets/` no pacote publicado é 80%+ do peso do tarball por
  4 imagens que nenhum consumidor instalado usa — correção simples, óbvia,
  sem trade-off real.

---

## Critério de revisão

- Se `SIMPLICIO_INTEGRATION.md`/`TOON-CONTRACT.md`/`SIMPLICIO_ECOSYSTEM.md`
  crescerem a ponto de a raiz ficar difícil de navegar, revisitar a
  Alternativa B como um PR dedicado (path-rewrite + atualização de
  gerador).
- Se o "Universal Long-Running Agent Overlay" for descontinuado como
  convenção entre-repos, revisitar a Alternativa A.

## Addendum (2026-07-07, issue #161 follow-up)

O item 3 ("Consolidação de `.md` da raiz — NÃO feita nesta ADR") deixou
`SHOWCASE.md` fora do corte por "baixo risco, mas também baixo ganho... não
vale sozinho o overhead de revisão". Numa passada de follow-up, sozinho
não valia — mas junto de `PRIVACY.md` (idem: baixo risco, só 2 links
markdown pra atualizar, `README.md`/`README.pt-BR.md`, mais 2 menções em
comentário de código sem link real) o corte passou a valer o overhead:

- `docs/PRIVACY.md` e `docs/SHOWCASE.md` — **movidos** para `docs/`.
  Atualizados: os 2 links markdown (`README.md:602`, `README.pt-BR.md:527`),
  o texto de ajuda do CLI (`bin/cli.js`) e o comentário do template
  (`.github/workflows-templates/telemetry-worker.js`). `package.json`'s
  `files` já inclui `docs/` como entrada própria, então as entradas
  standalone `"PRIVACY.md"`/`"SHOWCASE.md"` foram removidas (redundantes,
  não uma remoção de cobertura — `npm pack --dry-run` confirma que ambos
  continuam no tarball, agora em `docs/`).
- Os demais itens do item 3 (`PRD.md`/`PROGRESS.md`/`GOAL_RESULT.md`,
  `TEMPLATE_PATHS`, `PYPI.md`, os meta-docs técnicos fortemente
  cross-linkados) continuam **não movidos** pelas mesmas razões já
  documentadas acima — nenhuma delas mudou. `INIT.en.md`/`INSTALL.en.md`
  (não listados explicitamente na tabela original, adicionados depois)
  também ficam: não estão em `TEMPLATE_PATHS` mas são o par de tradução
  direto de `INIT.md`/`INSTALL.md` (que estão), linkados um do outro
  (`INIT.md:3`, `INSTALL.md:3`), listados em `package.json`'s `files`, e
  fixados por path absoluto em `tests/unit/overlay-docs.test.js` — mover
  quebraria esse teste e o link do irmão TEMPLATE_PATHS.

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/161
- ADR relacionada: `.specs/architecture/ADR-004-template-vs-product-content-manifest.md`
  (issue #140 — classificação template vs produto que este ADR estende
  pro eixo scaffold vs site/marketing vs meta-doc)
- `package.json` (`files`), `pyproject.toml` (`[tool.hatch.build...]`),
  `template-manifest.json`
