# Canonical map lifecycle (epic #263)

> Status honesto (2026-07-18, branch `issue-270`): este guia documenta o
> desenho **estável** especificado pelo epic #263 e pelas issues filhas
> #266/#267/#268/#269, apoiado na [ADR-008](../../.specs/architecture/ADR-008-canonical-map-overlays.md).
> Neste worktree, **apenas os passos 1-5 do plano de migração da ADR-008
> estão implementados**: `simplicio_mapper/mapper/canonical.py` (schemas),
> `canonical_identity.py` (resolução de identidade), `canonical_storage.py`
> (path arithmetic content-addressed), `canonical_builder.py` (builder real
> do manifesto contra o commit da branch default) e `canonical_overlay.py` +
> `effective_view.py` (delta de worktree e composição lazy). **Não existem
> ainda**: comandos de CLI `canonical status/build/verify/gc`, o path
> opt-in de consumo (`ask`/`query`/`status` lendo de `EffectiveMapView` em
> vez do pipeline de hoje), o lock cross-worktree generalizado (só o lock
> por-worktree `index.lock` existe), nem qualquer emissão de receipts. Este
> documento é escrito para descrever o contrato estável assim que essas
> peças (#266/#267/#268/#269) forem mescladas — as seções que dependem
> delas dizem isso explicitamente e não inventam saída de comando que não
> roda neste worktree hoje.

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

**Não implementado neste worktree.** A ADR-008 (seção 4) decide
explicitamente **reaproveitar, não reinventar**: generalizar o lock
`O_CREAT|O_EXCL` já maduro em `simplicio_mapper/cli/_index_engine.py`
(`_acquire_index_lock`/`_inspect_index_lock`/`_release_index_lock` —
`process_start_identity` contra PID reuse, TTL configurável via
`SIMPLICIO_MAPPER_LOCK_TTL_SECONDS`, nunca reclama lock de dono vivo) para
aceitar um `lock_path` explícito e um segundo valor de `operation`
(`"canonical-build"`, ao lado do `"index"` existente), em vez de duplicar a
lógica de PID/TTL/malformed-grace. Path esperado do lock canônico:
`<git-common-dir>/simplicio/canonical/<digest>/build.lock`. Quem perde a
corrida espera (ou falha rápido, síncrono/assíncrono) e lê o manifesto já
promovido pelo vencedor — nunca dois processos escrevem o mesmo `<digest>`
simultaneamente. O lock por-worktree (`index.lock`) continua existindo sem
mudança — só o manifesto canônico compartilhado precisaria do lock novo.
Verificado por busca textual neste worktree: `operation.*canonical-build`
não tem nenhum resultado em `_index_engine.py` hoje.

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

## Benchmark

**Bloqueado nesta issue, não fabricado.** O critério de aceite de #270 pede
um benchmark versionado (1/N worktrees, caminho canônico opt-in vs. full
remap, medindo wall/CPU/RSS/I/O/cache hit-miss/waits, com raw JSON +
Markdown gerados pelo mesmo comando, ambiente/versão/fixture/data/
variabilidade declarados). Isso depende de:

1. Um comando `canonical status`/`build` real para medir (#266/#268/#269) —
   não existe neste worktree (`simplicio-mapper --help` não lista
   `canonical` como subcomando).
2. O opt-in de consumo (#269) para comparar "canônico ligado" vs.
   "full remap" no mesmo processo, não apenas o builder isolado.
3. O lock single-flight cross-worktree (#266/#267) para medir `waits` de
   verdade sob concorrência entre worktrees.

Nenhum desses três está presente neste worktree — rodar qualquer script de
benchmark contra o estado atual só mediria o builder isolado
(`canonical_builder.build_canonical_manifest`) chamado fora do fluxo real
de comando, o que não corresponde ao que o critério de aceite pede
("caminho canônico opt-in" vs "full remap", ambos via comando real). Este
guia registra o bloqueio explicitamente em vez de inventar números — ver a
mensagem de commit desta mudança para o mesmo registro. Quando #266/#267/
#268/#269 estiverem mesclados neste worktree (ou num worktree subsequente
que já os tenha), o bundle de benchmark deve seguir o padrão já
estabelecido em `scripts/runtime_scale_benchmark.py` (fixture
determinística versionada em `tests/fixtures/`, schema
`simplicio.<nome>-benchmark/v1`, JSON + Markdown emitidos pelo mesmo
comando, sem duplicar lógica de medição entre os dois formatos de saída).

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
