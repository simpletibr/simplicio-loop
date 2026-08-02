# ADR-014: Congelar ownership e inventário do MapperStore/v1

## Status

Aceito como contrato de inventário e topologia-alvo; não como migração executada

## Data

2026-08-02

## Autores

- Simplicio engineering

## Contexto

SQLite, FTS5 e sqlite-vec aparecem hoje em Mapper, Loop, Dev CLI e Runtime. Cada
consumidor pode escolher path, WAL, busy timeout, migrations, locks e recovery de
forma independente. Antes de uma migração, precisamos de uma fotografia
reproduzível: SHA da branch default, versões, imports, paths/DSNs, DDL, comandos,
bancos materializados e ownership atual.

O inventário é produzido por `scripts/mapper_store_inventory.py` e usa somente
leitura. Source files são evidência de intenção; `sqlite_master` e PRAGMAs de um
banco materializado são evidência do estado físico. Nenhuma dessas evidências
autoriza importar, escrever, migrar, fazer cutover ou remover um banco. A
topologia e o ownership abaixo são alvos normativos para as próximas issues; não
afirmam que os adapters ou schemas de produção já existem.

## Decisão

Adotamos `MapperStore/v1` como a autoridade de contratos, paths, catálogo,
migrations e lifecycle dos stores SQLite, mantendo os bancos físicos separados
por domínio:

| Banco alvo | Domínios | Autoridade após cutover |
|---|---|---|
| `semantic.sqlite` | ContextGraph, símbolos, precedentes e documentos | MapperStore |
| `memory.sqlite` | memória, handoff, FTS5 e embeddings; sqlite-vec opcional | MapperStore |
| `operations.sqlite` | tasks, queues, leases, fences, journals e effect receipts | MapperStore |
| `catalog.sqlite` | catálogo de stores, versões e migration ledger | MapperStore |

As fronteiras de workflow permanecem nos consumidores: Loop continua dono da
semântica de retry/completion, Dev CLI continua dono da aplicação de patches e
Runtime continua dono do gate/receipt de efeitos. Eles usam o MapperStore por
adapters versionados e não criam um segundo schema autoritativo.

Embeddings pertencem a `memory.sqlite`, porque são memória neural; dados
semânticos de contexto pertencem a `semantic.sqlite`. Não há transação ACID
cross-domain: cada write tem uma transação local, causal ID e receipt em
`operations.sqlite`. Reconciliação explícita substitui uma falsa transação global.

O `simplicio-fast` fica fora desta decisão: `.sfast`, mmap e TurboQuant são caches
binários reconstruíveis, não bancos SQLite. DDL de produção novo fora das paths
allowlisted é rejeitado pelo gate local; DDL existente nos consumidores é
registrado como baseline legado até as issues de migração definirem o cutover.

Compatibilidade deve ser negociada por `MapperStore/v1`: Python usa a API
in-process `simplicio_mapper.store`; Runtime usa um adapter Rust para os mesmos
schemas, capabilities e receipts. O modo installed-package registra versões e
não executa imports de aplicação durante o inventário.

## Consequências

### Positivas (+)

- Há uma matriz única de current owner, target owner, readers, writers, path alvo,
  durabilidade, criticidade e estratégia de migração.
- O inventário pode ser repetido em checkout limpo, package instalado e bancos
  materializados sem tocar dados.
- DDL novo fora do MapperStore falha no gate local antes de virar nova autoridade.
- O layout separado limita contenção e blast radius sem criar um SQLite monolítico.

### Negativas (-)

- O inventário inicial registra writers legados que ainda precisam de adapters e
  cutover nas issues seguintes.
- Sem uma transação cross-domain, consumidores precisam reconciliar receipts e
  causalidade explicitamente.
- A matriz não prova sozinha que um caminho foi executado; smokes e receipts de
  migration ficam para #474–#481.

### Neutras / observações

- `sqlite-vec` é capability opcional: ausência deve produzir fallback explícito,
  nunca um anúncio falso de ANN.
- Métricas não observáveis ficam ausentes ou nulas; o scanner não estima ganhos.

## Alternativas consideradas

### Alternativa A — Um único arquivo SQLite

Rejeitada: concentra locks, corrupção e backup de domínios independentes e torna
mais provável que uma migração operacional afete memória semântica.

### Alternativa B — Cada consumidor mantém seu próprio schema

Rejeitada: preserva a fragmentação que motivou a epic, permite migrations
divergentes e mantém múltiplas autoridades físicas.

### Alternativa C — MapperStore centraliza contratos, mas mantém quatro arquivos

Adotada: separa blast radius físico e mantém catálogo, policies, capabilities e
lifecycle uniformes.

## Critério de revisão

Revisar quando uma issue de migration demonstrar que um domínio precisa de outra
topologia física, quando o adapter Rust não puder cumprir o contrato Python sem
subprocesso, ou quando benchmarks/lock traces evidenciarem contenção que o
isolamento por domínio não resolve.

## Links

- Issue: [#473](https://github.com/wesleysimplicio/simplicio-mapper/issues/473)
- Parent: [#472](https://github.com/wesleysimplicio/simplicio-mapper/issues/472)
- Contract: [contracts/mapper-store/v1](../../contracts/mapper-store/v1/README.md)
- Scanner: [scripts/mapper_store_inventory.py](../../scripts/mapper_store_inventory.py)
- Related Runtime issues: #2506, #2668, #3020, #3695
