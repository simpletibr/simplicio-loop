# Canonical map lifecycle (epic #263)

> **Atualizado 2026-07-18 (fechamento da issue #236)**: o parágrafo de status
> abaixo (escrito no branch `issue-270`, antes do PR #281) ficou stale sobre
> vários pontos e é mantido por enquanto só como registro histórico — não
> confie nele para o estado atual do `main`. Correções pontuais confirmadas
> por leitura direta do código nesta revisão: os comandos de CLI `canonical
> status/build/verify/gc` **existem e funcionam**
> (`simplicio_mapper/cli/_canonical.py`, PR #281, fecha #266/#267/#268); o
> caminho opt-in de reuso em `index`/`scan` **existe**
> (`--canonical-reuse`/`SIMPLICIO_MAPPER_CANONICAL_REUSE=1`,
> `simplicio_mapper/mapper/canonical_reuse.py`, PR #281, fecha #269); e o
> lock cross-worktree generalizado **existe** desde esta passada (issue #236
> gap #1) — ver a seção "Single-flight (lock cross-worktree)" abaixo,
> reescrita para descrever a implementação real. O que continua stale e não
> foi corrigido nesta passada cirúrgica (rewrite completo do doc é um
> follow-up separado, fora do escopo do fix de lock): as seções
> "Enablement", "Diagnóstico" e "Fallback"/"Rollback" abaixo ainda descrevem
> `ask`/`query`/`status` como não lendo de `EffectiveMapView` — isso segue
> verdadeiro (passo 6 da ADR-008 só cobriu `index`/`scan`, não esses três),
> mas o texto ao redor ainda fala como se nenhum comando `canonical`
> existisse, o que já não é o caso.
>
> Status honesto original (2026-07-18, branch `issue-270`): este guia
> documenta o desenho **estável** especificado pelo epic #263 e pelas issues
> filhas #266/#267/#268/#269, apoiado na
> [ADR-008](../../.specs/architecture/ADR-008-canonical-map-overlays.md).
> Neste worktree, **apenas os passos 1-5 do plano de migração da ADR-008
> estão implementados**: `simplicio_mapper/mapper/canonical.py` (schemas),
> `canonical_identity.py` (resolução de identidade), `canonical_storage.py`
> (path arithmetic content-addressed), `canonical_builder.py` (builder real
> do manifesto contra o commit da branch default) e `canonical_overlay.py` +
> `effective_view.py` (delta de worktree e composição lazy).

## Objetivo

Eliminar remapeamento redundante entre múltiplos worktrees do mesmo
repositório quando a branch default não mudou: um **manifesto canônico**
imutável, construído uma vez contra o commit da branch default e guardado
fora de qualquer worktree individual (no common git dir compartilhado), mais
um **overlay incremental** por worktree que captura só o delta (commits à
frente, staged/unstaged/untracked), compostos em uma **visão efetiva**
somente-leitura que o pipeline de consumo (`ask`, `query`, `status`) lê no
lugar de recomputar tudo.

## Enablement (opt-in, spec de #269)

O opt-in é o mecanismo que decide se um comando lê da `EffectiveMapView`
(canônico + overlay) em vez do caminho de hoje (`mapper.parse`/`graph`/`emit`
rodando do zero por worktree). **Este worktree não implementa nenhum flag ou
variável de ambiente de opt-in ainda** — a especificação abaixo é o desenho
esperado por #269, não algo verificável nesta árvore hoje:

- Flag esperado: opt-in explícito por comando (ex.: `--canonical` ou
  variável de ambiente equivalente), nunca ligado por padrão até que o
  passo 6 do plano de migração da ADR-008 (adapter de compatibilidade)
  esteja implementado e comprovadamente preserve 100% do contrato de saída
  atual.
- Kill-switch esperado, seguindo o padrão já usado no projeto para outras
  delegações opcionais (`SIMPLICIO_MAPPER_NO_RUNTIME_PRECEDENT`,
  `SIMPLICIO_MAPPER_NO_RUNTIME_IMPACT`, `SIMPLICIO_MAPPER_NO_RUNTIME_TESTS_FOR`,
  ver `AGENTS.md`): uma variável de ambiente para desligar o caminho
  canônico e cair de volta no pipeline de hoje sem qualquer alteração de
  código, mesmo com o opt-in ligado.
- Variável já implementada e real hoje (não é do opt-in de consumo, é de
  armazenamento — ver `canonical_storage.py`):
  `SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR`, override do diretório-raiz
  content-addressed (default: `<git-common-dir>/simplicio`).

## Schemas (estável, implementado)

Os três schemas abaixo já existem em
`simplicio_mapper/mapper/canonical.py`, testados isoladamente
(`tests/python/test_mapper_canonical.py`), sem nenhum wiring em produção
ainda:

| Schema | Constante | Versão | Papel |
|---|---|---|---|
| `simplicio.canonical-map/v1` | `CANONICAL_MAP_SCHEMA` | `CANONICAL_MAP_SCHEMA_VERSION = 1` | `CanonicalMapManifest` — snapshot imutável do commit da branch default |
| `simplicio.worktree-overlay/v1` | `WORKTREE_OVERLAY_SCHEMA` | `WORKTREE_OVERLAY_SCHEMA_VERSION = 1` | `WorktreeOverlay` — delta de um worktree contra um `CanonicalMapKey` base |
| `simplicio.effective-map-view/v1` | `EFFECTIVE_MAP_VIEW_SCHEMA` | `EFFECTIVE_MAP_VIEW_SCHEMA_VERSION = 1` | `EffectiveMapView` — composição lazy canonical + overlay + diagnostics |

### `CanonicalMapKey` — chave de identidade/invalidação

Implementada em `canonical.py`, resolvida por `canonical_identity.py`. Todo
campo participa da decisão de reaproveitamento — nenhum miss é silencioso:

| Campo | Origem |
|---|---|
| `repo_identity` | hash do remoto `origin` normalizado, ou (sem remoto) hash do `git rev-parse --git-common-dir` absoluto |
| `default_branch` | `git symbolic-ref refs/remotes/origin/HEAD` → fallback `git remote show origin` → heurística `main`/`master`/primeira branch local |
| `commit_sha` / `tree_sha` | do commit que a branch default aponta no momento do build |
| `schema_version` | `CANONICAL_MAP_SCHEMA_VERSION` |
| `mapper_version` | `importlib.metadata.version("simplicio-mapper")` |
| `config_fingerprint` | hash determinístico dos parâmetros de mapeamento (filtros, ignore rules, parser, modo de embeddings) |
| `platform_tag` | `None` por padrão; só populado quando um parser futuro declarar `platform_sensitive=True` |

`CanonicalMapKey.digest()` (blake2b, `digest_size=24`) é o nome do
diretório content-addressed. Ver `canonical_storage.resolve_canonical_cache_root`
e `canonical_manifest_dir`/`canonical_manifest_tmp_dir` para a árvore de
paths real (`<cache_root>/canonical/<digest>/`, com staging
`<digest>.tmp-<token>/` promovido via `os.replace`).

### `CanonicalMapManifest`

Construído por `canonical_builder.build_canonical_manifest` (reaproveita
`mapper.emit.build_artifacts` contra um checkout `git worktree add --detach`
temporário do commit da branch default — nunca contra o working tree sujo do
caller — e limpa o worktree temporário incondicionalmente ao final). Além
dos quatro artefatos padrão (project-map/precedent-index/symbol-index/
call-graph), o builder grava um artefato lateral `file_manifest` em **JSON
Lines** (`artifact_paths["file_manifest"]`), consumido de forma lazy por
`effective_view.LazyFileResolver` (ver abaixo).

### `WorktreeOverlay` / `OverlayFileChange`

Computado por `canonical_overlay.compute_worktree_overlay`: duas passagens
git compostas em um único change set relativo ao commit base canônico —
(1) `git diff --name-status -M <base_sha> <head_sha>` para o delta
commitado, (2) `git status --porcelain --untracked-files=all` para
staged/unstaged/untracked. Um arquivo renomeado por commit e depois editado
sem commit resolve para **uma** entrada `renamed` com `previous_path`
apontando pro nome no base canônico, não pro nome intermediário.
`change_type` é um de `added|modified|renamed|removed`; `removed` nunca
carrega `content_digest`; `renamed` sempre exige `previous_path`
(`OverlayFileChange.__post_init__` valida isso e lança `ValueError` se
violado). `WorktreeOverlay.config_fingerprint` deve bater bit-a-bit com
`base_key.config_fingerprint` ou o overlay é rejeitado como incompatível.

### `EffectiveMapView` / `EffectiveMapDiagnostics`

`effective_view.compose_effective_view` é composição pura — nenhum I/O além
do que já está residente em `canonical`/`overlay` (ambos já construídos em
memória). `_build_diagnostics` deriva `files_reused`/`files_remapped` só de
`canonical.counts["files"]` (um int) e do próprio delta do overlay
(`changed_files`/`tombstones`) — o inventário canônico completo nunca é
aberto para calcular diagnostics. `LazyFileResolver.resolve(path)` resolve
overlay primeiro (sem I/O canônico), depois tombstones (sem I/O canônico), e
só cai para leitura lazy linha-a-linha do `file_manifest` JSON Lines quando
o path não está em nenhuma das duas camadas — nunca materializa o
inventário canônico inteiro na memória.

`EffectiveMapDiagnostics` hoje (`effective_view._build_diagnostics`) sempre
popula `cache_hit=True` e `single_flight_waited=False` — **isso é uma
limitação conhecida da composição pura implementada até aqui, não o
contrato final**: esses dois campos só ficam significativos quando o
caminho de build/lock real (single-flight cross-worktree, #266/#267) estiver
plugado na chamada que decide construir vs. reaproveitar um manifesto — a
composição em si não tem visibilidade sobre se houve espera de lock ou
sobre um cache miss real, ela só compõe objetos já resolvidos por quem a
chamou.

## Diagnóstico (`invalidation_reason`)

Contrato estável, ainda **não emitido em produção** neste worktree: todo
reuse rejeitado de um `CanonicalMapManifest` deve popular
`EffectiveMapDiagnostics.invalidation_reason` com o motivo (qual campo do
`CanonicalMapKey` não bateu — schema, config, commit, etc.), nunca um miss
silencioso servindo um mapa obsoleto. A comparação campo-a-campo já está
implementada (`CanonicalMapKey` é um dataclass frozen comparável por
igualdade estrutural) mas o código que decide "reaproveitar ou invalidar" e
grava o motivo ainda não existe como caminho de execução real (é o adapter
do passo 6 da ADR-008, coberto por #266-269, ainda não presente aqui).

## Invalidação (motivos esperados)

Pelo desenho da chave (`CanonicalMapKey`, seção acima), qualquer diferença
nos campos abaixo invalida o reaproveitamento — a lista é a mesma da chave,
não uma taxonomia separada:

- `schema_version` ou `mapper_version` divergentes (upgrade do pacote).
- `config_fingerprint` divergente (filtros/ignore/parser/embeddings
  diferentes entre worktrees).
- `commit_sha`/`tree_sha` divergentes (branch default avançou).
- `platform_tag` divergente, apenas quando algum parser futuro declarar
  `platform_sensitive=True` (hoje nenhum declara — campo sempre `None`).

## Single-flight (lock cross-worktree)

**Implementado (issue #236 gap #1, 2026-07-18).** A ADR-008 (seção 4)
decidiu explicitamente **reaproveitar, não reinventar**: o lock
`O_CREAT|O_EXCL` já maduro que vivia em
`simplicio_mapper/cli/_index_engine.py` (`process_start_identity` contra PID
reuse, TTL configurável via `SIMPLICIO_MAPPER_LOCK_TTL_SECONDS`, nunca
reclama lock de dono vivo) foi extraído para
`simplicio_mapper/mapper/file_lock.py`
(`acquire_lock_at`/`inspect_lock_at`/`release_lock_at`, aceitando um
`lock_path` explícito e um `operation` livre) em vez de duplicar a lógica de
PID/TTL/malformed-grace. `_index_engine._acquire_index_lock`/
`_inspect_index_lock`/`_release_index_lock` viraram wrappers finos
(`operation="index"`) — comportamento inalterado para o caso de uso
existente.

`canonical_builder.build_canonical_manifest` adquire o mesmo mecanismo com
`operation="canonical-build"` antes do checkout/pipeline caro. Path real do
lock canônico — **ajustado versus o path original sugerido pela ADR**:
`<cache_root>/canonical/<digest>.build.lock` (irmão do diretório do
manifesto, não filho dele — colocar o lock dentro do diretório do manifesto
quebraria a invariante de promoção atômica via `os.replace`, que espera o
diretório de destino vazio/inexistente antes da promoção; ver
`canonical_storage.canonical_build_lock_path`'s docstring). Quem perde a
corrida por padrão **espera** (bounded, default 600s, configurável via
`SIMPLICIO_MAPPER_CANONICAL_BUILD_LOCK_WAIT_SECONDS` ou o parâmetro
`lock_wait_seconds`) e lê o manifesto já promovido pelo vencedor — nunca
refaz o trabalho caro; `build_canonical_manifest(..., blocking=False)`
falha rápido em vez de esperar, para um futuro chamador assíncrono. Nunca
dois processos escrevem o mesmo `<digest>` simultaneamente. O lock
por-worktree (`index.lock`) continua existindo sem mudança.

`build_canonical_manifest_with_diagnostics` expõe o mesmo contrato mais um
`reason_code` estável (`built`, `built_after_wait`, `reused_after_wait`,
`reused_cache_hit`, `lock_contended_fail_fast`, `lock_wait_timeout`, entre
outros) — `simplicio-mapper canonical build --json` já surfaceia esse código
no campo `reason_code` do receipt.

Testado com uma corrida real de dois processos de SO (não apenas threads)
via `simplicio-mapper canonical build <path> --json` executado duas vezes
concorrentemente contra o mesmo repositório —
`tests/python/test_canonical_build_lock.py::CanonicalBuildLockConcurrentProcessRaceTest`
— prova que exatamente um processo constrói de verdade e o outro nunca
refaz o trabalho.

## Fallback

Contrato esperado do adapter (passo 6 da ADR-008, ainda não implementado
aqui): qualquer falha no caminho canônico — lock não obtido dentro do
timeout, manifesto corrompido/incompleto, overlay incompatível
(`config_fingerprint` não bate), binário/artefato ausente — cai
automaticamente para o pipeline de hoje (`mapper.parse`/`graph`/`emit` rodando
do zero), nunca finge sucesso. Mesmo padrão de fallback já usado no projeto
para delegação nativa opcional (`query.py`'s `ask precedent/impact/tests-for`,
ver `AGENTS.md`): binário ausente, kill-switch setado, exit != 0, timeout,
JSON malformado ou schema não bate — tudo cai no caminho local existente.

## Rollback

Contrato esperado, não implementado aqui: como o manifesto canônico é
imutável e promovido atomicamente por `<digest>` (`os.replace` de um
diretório de staging `.tmp-<token>` para o diretório final — ver seção de
armazenamento abaixo), "rollback" de um build ruim é sempre **descartar o
digest problemático**, nunca editar um manifesto in-place: apagar
`<cache_root>/canonical/<digest>/` (ou deixar o GC, planejado no passo 7 da
ADR-008, remover automaticamente digests sem referência) força o próximo
consumidor a reconstruir do zero contra a mesma chave. Não existe um
comando `canonical rollback` — o desenho evita precisar de um, porque nada
em `<digest>/` é editado depois de promovido.

## GC (garbage collection)

**Desenhado na ADR-008 (seção 5), não implementado neste worktree** —
confirmado por busca textual (`GC`/`garbage` só aparecem em comentários de
docstring em `canonical.py`/`canonical_storage.py`, nenhum código
executável). Contrato esperado: `generation` (inteiro monotônico já
presente em `CanonicalMapManifest`, ver `canonical.py`) permite ao GC
futuro ordenar snapshots superados sem depender de mtime (não-monotônico em
alguns filesystems sob clock skew). GC remove digests sem manifesto
referenciado por nenhum branch-tip recente nem em uso (lock/lease ativo) —
comando esperado `simplicio-mapper canonical gc`, ainda não existente
(`simplicio-mapper --help` neste worktree não lista nenhum subcomando
`canonical`, verificado nesta sessão).

## Privacidade

Garantias de desenho já refletidas nos dataclasses implementados:

- `WorktreeOverlay.worktree_path` é o único campo que carrega um path
  absoluto de worktree, e o campo é documentado explicitamente como "nunca
  leaked into canonical storage" (`canonical.py`, docstring de
  `WorktreeOverlay`) — overlays vivem em
  `<git-common-dir>/simplicio/overlays/<overlay_digest>/`, um subdiretório
  separado do manifesto canônico (`<git-common-dir>/simplicio/canonical/<digest>/`),
  então mesmo um leitor do diretório canônico nunca vê o path do worktree
  que gerou um overlay.
- `builder` (dict em `CanonicalMapManifest`) registra `pid`/`host`/
  `process_start_identity` do processo que construiu o manifesto — trilha
  de auditoria local, não uma referência de rede/URL remota.
- Nenhum campo de `CanonicalMapManifest`/`WorktreeOverlay`/`EffectiveMapView`
  carrega segredo, token, ou credencial — todos os campos são
  identidade-de-repo/commit/config, paths relativos, ou contadores.
- Quando os comandos `canonical status/verify` existirem (#269), qualquer
  saída para terminal/JSON deve preservar essa garantia: nunca imprimir
  `worktree_path` cru em um contexto que possa ser compartilhado fora da
  máquina local (ex.: colado em um issue/PR) sem redigir; e nunca vazar o
  path do `SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR` quando ele aponta para um
  cache central compartilhado entre máquinas/CI (a ADR-008 menciona esse
  caso explicitamente na seção 3).

## Limitações por plataforma

- `platform_tag` existe em `CanonicalMapKey` justamente para o caso em que
  um parser resolve symlinks de forma diferente entre SOs (ex.: Windows);
  hoje nenhum parser declara `platform_sensitive=True`, então o campo é
  sempre `None` e o manifesto canônico é compartilhável entre plataformas
  por padrão — isso pode mudar sem aviso se um parser futuro declarar essa
  flag, invalidando cache cross-platform que hoje é reaproveitado.
- `process_start_identity` (usado pelo lock single-flight, seção acima) já
  tem fallback por SO documentado em `_index_engine.py`:
  `/proc/<pid>/stat` no Linux, `GetProcessTimes` no Windows, `ps -o lstart=`
  como fallback genérico — mas isso é do lock *por-worktree* existente; o
  lock cross-worktree ainda não implementado herdaria o mesmo mecanismo
  (ADR-008 seção 4), não foi verificado em Windows/macOS neste worktree.
- Builder do manifesto canônico usa `git worktree add --detach` num path
  temporário — em filesystems de rede ou runners com quota de I/O restrita
  isso tem custo mensurável (ver ADR-008 "Consequências negativas"); a
  alternativa mais barata (`git cat-file --batch`) foi considerada e
  adiada por complexidade de integração com o parser atual, que espera
  arquivos no disco.
- **Status final honesto (epic #236, 2026-07-18)**: o benchmark de
  wall/CPU/RSS/I/O agora existe e roda de verdade (ver seção "Benchmark"
  acima) — isso fecha a parte mensurável do critério de aceite do epic.
  A parte de plataforma **não fecha**: nenhuma sessão que trabalhou neste
  epic (incluindo esta) teve acesso a macOS ou Windows, só a um container
  Linux. Isso não é um detalhe a resolver com mais código — é uma
  limitação de ambiente desta sessão/ferramenta que só uma sessão humana
  ou de agente com acesso real a essas plataformas pode fechar. Os epics
  #236 e #263 devem permanecer abertos até que isso aconteça, ou até que
  alguém com autoridade sobre o escopo decida explicitamente que
  "Linux only" é um estado final aceitável.

## Benchmark

> **Atualizado (2026-07-18, epic #236 closure work, worktree
> `issue-236-close-work`)**: o bloqueio descrito abaixo (texto original da
> issue #270) foi resolvido pelas issues filhas #266/#267/#268/#269, todas
> mescladas — o benchmark real existe e roda contra o path opt-in de
> verdade. O que segue documenta o estado atual, não mais um bloqueio.

Benchmark real: [`scripts/canonical_reuse_benchmark.py`](../../scripts/canonical_reuse_benchmark.py)
/ [`docs/canonical-reuse-benchmark.md`](../canonical-reuse-benchmark.md) /
[`docs/evidence/canonical-reuse-benchmark.json`](../evidence/canonical-reuse-benchmark.json)
(schema `simplicio.canonical-reuse-benchmark/v2`). Mede, para N worktrees
reais (`git worktree add --detach`), o caminho `full` (pipeline completo,
sem reuse) vs. `canonical-reuse` (opt-in, `attempt_canonical_reuse`) —
wall time, CPU (processo principal e filhos via
`resource.getrusage(RUSAGE_CHILDREN)`, cobrindo os subprocessos `git` reais
que `canonical_builder._run_git` invoca), peak RSS (idem, principal e
filhos) e um proxy de I/O (`ru_inblock`/`ru_oublock` — contagem de
operações de bloco, não bytes; ver caveats do próprio script para o que
isso não cobre). Rodado de verdade nesta sessão em duas escalas:

- 4 worktrees x 40 arquivos: canonical-reuse foi **mais lento** em wall
  time (0.335s vs 0.210s do full) — nesta escala pequena o custo fixo do
  canonical-build (pago uma vez pelo primeiro worktree) não é amortizado.
- 5 worktrees x 300 arquivos: canonical-reuse foi **1.403x mais rápido**
  em wall time, com CPU do processo principal 54.6% menor e I/O out-blocks
  63.1% menor que o full remap.

Os dois números são reais e não foram editados — a leitura honesta é que o
ganho depende da forma `(arquivos por worktree, N worktrees)`, não é uma
constante universal; ver `docs/canonical-reuse-benchmark.md` para a tabela
completa e a discussão de quando esse tradeoff ajuda ou não.

**O que ainda falta, genuinamente, e não é fabricável nesta sessão**: o
critério de aceite do epic #236 também pede validação em Linux, macOS e
Windows. Esta sessão — como todas as sessões anteriores que trabalharam
neste epic — só teve acesso a um container Linux. O benchmark acima (e o
resto da superfície `canonical status/build/verify/gc`) nunca foi rodado em
macOS ou Windows, e não há como simular esse resultado de forma honesta a
partir daqui. Este é um critério de aceite do epic #236 que permanece em
aberto e depende de uma sessão humana ou de agente com acesso real a essas
plataformas — não é algo que este trabalho resolveu nem finge ter
resolvido.

## Onde encontrar o código (nesta issue)

| Peça | Arquivo | Status |
|---|---|---|
| Schemas | `simplicio_mapper/mapper/canonical.py` | Implementado, sem wiring |
| Identidade | `simplicio_mapper/mapper/canonical_identity.py` | Implementado, sem wiring |
| Storage paths | `simplicio_mapper/mapper/canonical_storage.py` | Implementado, sem wiring |
| Builder do manifesto | `simplicio_mapper/mapper/canonical_builder.py` | Implementado, sem wiring |
| Overlay (delta) | `simplicio_mapper/mapper/canonical_overlay.py` | Implementado, sem wiring |
| Composição efetiva | `simplicio_mapper/mapper/effective_view.py` | Implementado, sem wiring |
| Lock cross-worktree | — | Não implementado (#266/#267) |
| Comandos `canonical status/build/verify/gc` | — | Não implementado (#268/#269) |
| Opt-in de consumo | — | Não implementado (#269) |
| Receipts/eventos | — | Não implementado |
| Benchmark 1/N worktrees | — | Bloqueado por tudo acima |
| ADR | [`.specs/architecture/ADR-008-canonical-map-overlays.md`](../../.specs/architecture/ADR-008-canonical-map-overlays.md) | `Proposto` |

## Test Scenarios (implementados hoje)

- `tests/python/test_mapper_canonical.py` — validação estrutural dos
  dataclasses (`change_type` inválido, `renamed` sem `previous_path`,
  `removed` com `content_digest`, `schema`/`schema_version` incompatíveis).
- `tests/python/test_mapper_canonical_identity.py` — resolução de
  `repo_identity`/`default_branch`/`commit_sha`/`tree_sha` contra
  repositórios git reais (com e sem remoto).
- `tests/python/test_mapper_canonical_storage.py` — path arithmetic
  content-addressed, incluindo o override
  `SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR`.
- `tests/python/test_canonical_builder.py` — builder real contra um
  checkout `git worktree add --detach` temporário, incluindo limpeza
  incondicional do worktree temporário.
- `tests/python/test_canonical_overlay.py` — delta commitado + delta
  staged/unstaged/untracked compostos em um único change set, incluindo o
  caso "renomeado por commit, depois editado sem commit".
- `tests/python/test_canonical_effective_view_integration.py` — composição
  lazy ponta-a-ponta (`compose_effective_view` + `LazyFileResolver`),
  incluindo resolução via overlay, tombstone e fallback para o
  `file_manifest` JSON Lines canônico.

## Known Risks

- Este documento descreve um contrato estável baseado nas specs de
  #266/#267/#268/#269, que podem ainda mudar de forma incompatível antes de
  serem mescladas — nenhuma delas está confirmada neste worktree no
  momento da escrita (2026-07-18). Revisar este guia assim que qualquer uma
  delas for integrada aqui, e atualizar a tabela "Onde encontrar o código"
  acima.
- `EffectiveMapDiagnostics.cache_hit=True`/`single_flight_waited=False`
  fixos hoje (ver seção "Schemas") são um placeholder da composição pura,
  não o comportamento final — qualquer leitor que consuma esses campos
  antes do wiring real (#266/#267) veria sinais sempre otimistas.
- O builder (`canonical_builder.py`) já é funcional e testado, mas nunca é
  chamado por nenhum comando real hoje — só pelos testes unit/integration
  listados acima.
