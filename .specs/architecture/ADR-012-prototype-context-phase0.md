# ADR-012: `prototype-context` local bounded query (Fase 0) para Prototype-First

> **Addendum (mesma issue #286, sessão concorrente seguinte)**: o passo 6
> ("Integrar precedent ranking e registrar provenance/confidence"), listado
> abaixo como fora de escopo desta ADR na sua versão original, foi
> implementado nesta mesma fatia logo em seguida -- ver a seção "Escopo
> desta ADR (implementado)", item 6, e "Fora de escopo", que foram
> atualizados. O campo `precedents` do envelope reusa
> `query._local_precedent_fallback` (o mesmo fallback local que `ask
> precedent` já usa quando o binário nativo `simplicio` está ausente),
> anotado com `confidence` (contagem de overlap de tokens, nunca uma
> pontuação de relevância medida) e `provenance`. Delegação nativa ao
> runtime `simplicio` para este campo continua fora de escopo -- ver o item
> correspondente na lista atualizada.

> Endereça a issue #286 ("[P0][Prototype-First][Loop #568] Gerar context
> packs, impacto e estruturas mínimas para protótipos"), upstream contract
> `wesleysimplicio/simplicio-loop#568`. Relacionadas: #236 (canonical
> map/overlay, ainda em progresso -- ver ADR-008), #263.
>
> **Esta ADR documenta explicitamente uma Fase 0 parcial**, seguindo o mesmo
> padrão de ADR-010 (`release-manifest-phase0.md`) e ADR-011
> (`adaptive-pipeline-threshold-calibration.md`): a issue #286 descreve um
> pipeline cross-repo completo -- mapa canônico compartilhado entre
> worktrees com overlays incrementais, geração determinística de
> schemas/data-models/testes falhos/vertical slices, precedent ranking com
> provenance/confidence, receipts integrados ao Loop/Runtime, e um benchmark
> contra golden repos em quatro linguagens mais monorepo. Implementar tudo
> isso nesta issue seria especular sobre o ciclo de vida do mapa canônico
> (issue #236, ainda não operacional -- ver `simplicio_mapper/cli/_canonical.py`)
> e sobre um contrato de receipt Loop/Runtime que não existe ainda deste
> lado. Esta ADR escopa deliberadamente **apenas** a fatia local,
> determinística e verificável a partir deste repositório hoje.

---

## Status

`Aceito`

---

## Data

`2026-07-18`

---

## Autores

- Claude (agente, sessão issue #286)

---

## Contexto

A issue #286 pede um comando `simplicio-mapper prototype-context --type ...
--json` (passo 10 do plano de 12 passos) que produza um "context pack"
bounded e hash-bound para orientar geração de protótipos -- símbolos,
arquivos, contratos, testes e precedentes mínimos, mais um "negative space"
(o que não deve ser tocado), com skeletons determinísticos e budget de
tokens.

Boa parte desse plano depende de infraestrutura que este repo ainda não
possui de forma operacional:

- **Mapa canônico compartilhado + overlays por worktree** (issue #236) --
  os módulos existem (`simplicio_mapper/mapper/canonical.py`,
  `cli/_canonical.py`) mas a integração ao ciclo de vida operacional
  (`index`/`scan`/`ask`) ainda está em progresso via #263. Construir
  `prototype-context` sobre um mapa canônico que ainda não é a fonte de
  verdade operacional seria construir sobre areia.
- **Skeletons determinísticos** (passo 5) -- geração de schema/data-model/
  teste falho/vertical slice é uma feature própria e maior, sem decisão de
  formato ainda tomada.
- ~~**Precedent ranking com provenance/confidence** (passo 6) -- `ask
  precedent` já existe como verbo separado (`query.py`); integrar
  confidence scoring ao envelope de `prototype-context` é trabalho
  adicional, não uma dependência bloqueante desta fatia.~~ **Implementado
  no addendum acima** -- ver item 6 da lista "Escopo desta ADR
  (implementado)".
- **Receipts/hash integrados ao Loop/Runtime** (passo 11) e o **benchmark
  full-read/remap vs. prototype-context em golden repos** (passo 12) --
  ambos dependem de consumidores/infraestrutura cross-repo que este
  repositório não controla sozinho.

O que já existe e é reutilizável hoje, sem nenhuma dessas dependências: F10
`ask` (`simplicio_mapper/query.py`) já resolve símbolo->arquivo, calcula
impacto (`_impact`, reusando `build_flow_inventory` + `_symbols_for_files` +
`_scan_manual_docs_for_references`) e testes relacionados (`_tests_for`),
tudo a partir dos artefatos já construídos em memória por `build_artifacts()`
-- exatamente o material bruto que um context pack por tipo precisa.

---

## Decisão

Implementar **apenas** a fatia local, determinística e verificável do plano
de 12 passos da issue #286:

### Escopo desta ADR (implementado)

1. **Query por tipo** (passo 2): `--type {ui, api, data-model, bug,
   benchmark, prompt, workflow}` -- os sete tipos citados literalmente na
   issue, kebab-cased. Tipo desconhecido ou `--arg` vazio levanta
   `PrototypeContextError` (nunca um default silencioso).
2. **Extração de símbolos/arquivos/testes mínimos** (passo 3, parcial):
   resolve o argumento (`--arg`) como um path já conhecido em
   `project_map["files"]` ou como um nome de símbolo via
   `query._resolve_symbol_name`, depois reusa `query._impact` e
   `query._tests_for` -- os mesmos helpers que `ask impact`/`ask tests-for`
   já usam, sem reimplementar a lógica.
3. **Negative-space heurístico** (passo 4, parcial): arquivos sob
   diretórios de topo-de-nível que o conjunto de impacto/alvo nunca toca.
   Documentado explicitamente como heurística grosseira, não uma prova de
   não-impacto -- nem presença nem ausência da lista é uma garantia.
4. **Token/context budget com truncamento** (passo 9): usa o mesmo
   estimador `heuristic:chars-div-4` de `savings.py`/`token_budget.py`;
   trunca a maior lista primeiro, reporta `omitted_counts` por campo, e
   nunca esconde que truncou (`truncated: true/false` sempre presente).
5. **Envelope estável `simplicio.prototype-context/v1`** exposto via
   `simplicio-mapper prototype-context <root> --type <type> --arg <target>
   [--limit N] [--token-budget N] [--json]`, dispatch antes de
   `_parse_args` (mesmo padrão de `canonical`/`benchmark`/
   `release-manifest`/`schema-compat` em `cli/__init__.py::main`).
6. **`skeletons` sempre lista vazia** com `skeletons_note` textual
   explicando que a geração determinística (passo 5 da issue) está fora de
   escopo aqui -- nunca um placeholder que pareça um skeleton real.
7. **Precedent ranking integrado ao envelope** (passo 6, addendum): campo
   `precedents`, reusando `query._local_precedent_fallback` (o mesmo
   fallback local usado por `ask precedent`) sobre `precedent-index.json`,
   com `confidence` (contagem de overlap de tokens via `query._tokenize`,
   reaplicada aqui porque o fallback compartilhado retorna só os itens
   ranqueados, não seus scores) e `provenance` por item. Nunca delega ao
   binário nativo `simplicio` -- diferente de `ask precedent`, que pode.
   Incluído na escada de truncamento (`_TRUNCATABLE_FIELDS`).

### Fora de escopo desta ADR (decisão explícita, não esquecimento)

- Mapa canônico compartilhado / overlays por worktree (passos 1, 7, 8) --
  depende de #236/#263 primeiro. Este comando sempre resolve a partir do
  worktree onde é executado, sem cache cross-worktree.
- Skeletons determinísticos para schemas/data models/testes falhos/vertical
  slices (passo 5) -- feature própria e maior, sem decisão de design ainda.
- Delegação nativa ao binário `simplicio` (runtime) para o campo
  `precedents` -- diferente de `ask precedent`, este envelope só usa o
  fallback local, nunca o caminho nativo/SQLite-FTS5.
- Receipt/hash com Loop/Runtime (passo 11) e benchmark full-read/remap
  contra golden repos multi-linguagem (passo 12) -- dependem de
  infraestrutura/consumidores cross-repo que este repo não controla
  sozinho.
- Exclusão de secrets/binaries/paths proibidos além do que o mapper já faz
  hoje (critério de aceite da issue) -- este comando reusa
  `project_map`/`symbol_index` já filtrados pelo pipeline existente; nenhuma
  lógica de exclusão nova foi adicionada nesta fatia.

---

## Consequências

### Positivas (+)

- Existe agora um comando `prototype-context` real, testado e reusável por
  um agente/Loop antes de gerar um protótipo, sem esperar pelo mapa
  canônico operacional.
- Reusa 100% da lógica já testada de `query._impact`/`query._tests_for` --
  nenhuma duplicação de regra de impacto.
- O budget de tokens com truncamento honesto (`omitted_counts`) evita que
  um consumidor confie silenciosamente em uma lista cortada.

### Negativas (-)

- Sem mapa canônico, cada chamada de `prototype-context` paga o custo de
  `build_artifacts()` do zero (mesma limitação documentada já em F10 `ask`
  no AGENTS.md/CLAUDE.md) -- não há reuso cross-worktree ainda.
- `negative_space` é uma heurística de diretório de topo-de-nível apenas;
  um arquivo em `src/unrelated.py` ainda aparece como "tocável" mesmo que
  não tenha relação real com o alvo, porque a heurística não desce a
  símbolo/import individual.
- `skeletons` sempre vazio -- um consumidor que espere geração de
  boilerplate real desta issue vai encontrar um campo vazio com nota, não a
  feature completa.

### Neutras / observações

- Segue o mesmo padrão de dispatch pré-`_parse_args` já usado por
  `canonical`/`benchmark`/`release-manifest`/`schema-compat`
  (`cli/__init__.py::main`), então nenhuma mudança na tupla `commands` de
  `_args.py` foi necessária.

---

## Alternativas consideradas

### Alternativa A -- Implementar o plano de 12 passos completo nesta issue

Resumo: já entregar mapa canônico compartilhado, skeletons, precedent
ranking com confidence, receipts cross-repo e benchmark multi-linguagem
nesta mesma mudança.

Por que foi descartada: depende de decisões de design ainda não tomadas em
#236/#263 (o próprio mapa canônico ainda não é operacional) e de contratos
cross-repo com `simplicio-loop`/`simplicio-dev-cli` que não existem hoje.
Alto risco de retrabalho completo assim que o design real for definido.

### Alternativa B -- Esperar #236/#263 fecharem antes de tocar nesta issue

Resumo: não fazer nada em #286 até o mapa canônico estar operacional.

Por que foi descartada: existe uma fatia real e útil -- reusar `ask
impact`/`ask tests-for` atrás de uma query-por-tipo com budget -- que não
depende de nenhuma peça do #236 ainda não pronta. Adiá-la também adiaria,
sem necessidade, um comando que um Loop/agente já pode usar hoje.

### Alternativa C -- Adicionar `prototype-context` como sub-verbo de `ask` em vez de comando novo

Resumo: em vez de um comando de topo dispatchado antes de `_parse_args`,
adicionar `type`/`negative-space` como mais um verbo de `ask` (como
`impact`/`tests-for` já são).

Por que foi descartada: a issue #286 pede explicitamente um comando próprio
(`simplicio-mapper prototype-context --type ... --json`), com uma forma de
envelope (`negative_space`, `skeletons`, budget) distinta do formato
`{results, total}` de `ask`. Forçar isso dentro de `ASK_SCHEMA` obrigaria
uma mudança de schema versionada do `ask` existente para um caso de uso
diferente -- um comando novo com schema próprio (`prototype-context/v1`) é
mais limpo e não arrisca quebrar consumidores de `ask`.

---

## Critério de revisão

- Quando #236/#263 entregarem um ciclo de vida de mapa canônico
  operacional, revisitar `build_prototype_context` para consumir
  `EffectiveMapView` em vez de `build_artifacts()` puro.
- Quando o design de skeletons determinísticos for decidido (issue
  separada), revisitar o campo `skeletons` desta ADR para deixar de ser
  sempre vazio.
- Quando `simplicio-loop`/`simplicio-dev-cli` definirem o formato de
  receipt cross-repo, revisitar a integração do passo 11.

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/286
- Upstream contract: https://github.com/wesleysimplicio/simplicio-loop/issues/568
- Relacionadas: #236, #263
- Implementação: `simplicio_mapper/prototype_context.py`,
  `simplicio_mapper/cli/__init__.py`,
  `tests/python/test_prototype_context.py`
- ADRs relacionados: [ADR-008](./ADR-008-canonical-map-overlays.md),
  [ADR-010](./ADR-010-release-manifest-phase0.md),
  [ADR-011](./ADR-011-adaptive-pipeline-threshold-calibration.md)

---

## Addendum — fechamento Mapper-owned da issue #286 (2026-07-18)

Uma fatia seguinte removeu o principal ponto fraco operacional do envelope
local sem assumir contratos cross-repo que o Mapper não controla sozinho. O
comando `prototype-context` agora inclui, dentro do próprio
`simplicio.prototype-context/v1`:

- `source_binding`: `source_sha`, `tree_sha` quando disponível, estado `dirty`,
  `affected_shards`, hash dos shards e política de invalidação
  `invalidate-only-listed-shards-on-source-drift`.
- `context_hash` calculado sobre o payload final bounded/truncado, com
  `context_hash_algorithm = sha256:canonical-json-without-context_hash`.
- `excluded_context`: filtro path-only para nomes secret-like e extensões
  binárias antes de expor targets, símbolos, testes, negative-space ou
  precedentes.
- `measurements`: comparação local honesta entre o tempo do full remap via
  `build_artifacts()` e o tempo de extração do `prototype-context`.
- `canonical_reuse`: metadados de elegibilidade/hash-binding para consumir
  artefatos vindos do caminho canônico quando `index`/`scan` já tiverem feito
  esse opt-in, sem prometer merge parcial de overlay que este comando não faz.

Isso fecha os critérios que são responsabilidade direta do Mapper nesta issue:
context pack bounded/hash-bound, impacto com teste/contrato/artefato via
artefatos existentes, negative-space explícito, skeleton descriptors com
provenance, exclusão de secrets/binários, source-drift por shards e medição
full-remap vs context extraction. Continuam fora de escopo por dependerem de
outros contratos/repositórios: materialização real de protótipos pelo Dev CLI,
receipts Loop/Runtime cross-repo e validação E2E contra o Loop completo.
