# ADR-008: Mapa canônico da branch default com overlays incrementais por worktree

> Escrita originalmente como Fase 0 (só schemas, #237). **Atualizado
> 2026-07-18**: os passos 2-5 do plano de migração (seção "Plano de
> migração" abaixo) já foram implementados e mergeados nas issues #254,
> #256, #258, #259, #261 e reconciliados em #272 — confirmado por leitura
> direta do código nesta revisão, não apenas pelo título dos commits. Esta
> ADR permanece a fonte de verdade do desenho; as seções abaixo foram
> atualizadas in-place para não descrever como "futuro" o que já está no
> `main`. Passos 6-8 (adapter dos comandos existentes, `canonical
> status/build/verify/gc`, API async) continuam não implementados e são
> tracked separadamente na issue #263 (fatia executável) com filhas #266
> (status/build), #267 (verify), #268 (gc), #269 (index/scan integration),
> #270 (docs/benchmark) — fora do escopo desta atualização.

---

## Status

`Aceito` — desenho aprovado e parcialmente implementado (model layer completo:
identidade, storage, builder, overlay, effective view; wiring de CLI/lock
cross-worktree ainda pendente, tracked em #263 e filhas).

---

## Data

`2026-07-17` (última atualização: `2026-07-18`)

---

## Autores

- `claude-agent` (Phase-0, issue #236)
- `claude-agent` (atualização de status pós-merge dos passos 2-5, issue #236, 2026-07-18)

---

## Contexto

Cada worktree do mesmo repositório hoje executa um `simplicio-mapper index`
completo e independente: leitura de arquivos, parsing, símbolos, precedentes
e embeddings são recomputados do zero por worktree, mesmo quando a branch
default não mudou entre eles. Isso desperdiça CPU/RAM/I/O e pode produzir
cópias divergentes do "mesmo" estado-base quando o config fingerprint muda
de forma sutil entre worktrees (ex.: filtros diferentes passados via CLI).

Estado atual, verificado nesta issue:

- **Por worktree hoje** (`simplicio_mapper/cli/_index_engine.py`): artefatos
  (`_artifact_paths`), lock (`index.lock`) e estado (`index-state.json`)
  vivem sob `<root>/<out>` — tipicamente `.simplicio/` dentro do próprio
  worktree. `_freshness_signature()` prefere `_git_signature()` (HEAD +
  status porcelain) e cai para `_tree_signature()` (mtime/size de todos os
  arquivos) quando não há git. Nada disso é compartilhado entre worktrees;
  dois worktrees do mesmo repo na mesma branch default recomputam tudo de
  novo cada um no seu `.simplicio/`.
- **Cache de arquivo compartilhável em potencial** (`simplicio_mapper/cache.py`):
  `FileProcessingCache` já usa `diskcache.Cache` com chave
  `blake2b(version:path:size:mtime)` — path absoluto normalizado por
  worktree, então hoje não há reaproveitamento entre worktrees mesmo que o
  conteúdo do arquivo seja idêntico (dois checkouts do mesmo commit em
  caminhos diferentes geram chaves diferentes por causa do path).
- **Lock single-flight já existe e é maduro** (`_acquire_index_lock` /
  `_inspect_index_lock` / `_release_index_lock` em `_index_engine.py`):
  lock exclusivo via `O_CREAT|O_EXCL`, registro JSON com `schema`, `pid`,
  `process_start_identity` (proteção contra reuse de PID via
  `/proc/<pid>/stat` starttime no Linux, `GetProcessTimes` no Windows,
  `ps -o lstart=` como fallback), `owner_token`, `acquired_at`/`heartbeat_at`,
  TTL configurável (`SIMPLICIO_MAPPER_LOCK_TTL_SECONDS`, default 6h),
  reclamação segura de lock morto/PID reusado/TTL expirado sem nunca
  reclamar um lock de dono vivo. **Esse lock é por worktree** (a chave é o
  path `<root>/<out>/index.lock`); não existe ainda um lock cross-worktree
  ancorado no common git dir.
- **Nenhum conceito de "common git dir" ou "branch default" existe hoje** em
  `simplicio_mapper/` — confirmado por busca textual (`common-dir`,
  `worktree`, `git rev-parse`) sem hits em código de produção fora deste ADR.
  `_git_signature()` já roda `git` no root do worktree, então a extensão para
  resolver `git rev-parse --git-common-dir` e a branch default é incremental,
  não uma reescrita.

Decisões anteriores relacionadas: nenhuma ADR cobre cache/lock cross-worktree
ainda; este é o primeiro. ADR-003 (two-tier async mapper) e ADR-002
(python/rust hybrid) tocam o pipeline de mapeamento em si mas não a camada de
armazenamento/identidade de snapshot.

---

## Decisão

Adotamos um design em camadas — **manifesto canônico imutável da branch
default** + **overlay incremental por worktree**, compostos em uma
**visão efetiva somente-leitura** — como a arquitetura alvo para eliminar
mapeamento redundante entre worktrees, implementada em fases; esta ADR
formaliza os schemas e o desenho, e a Fase 0 (este PR) entrega **apenas** os
schemas versionados, sem qualquer wiring no pipeline real.

### Escopo desta ADR

Dentro do escopo (desenho completo; itens marcados `[implementado]` já
existem em código, confirmado nesta revisão por leitura direta dos módulos):

- Schemas `CanonicalMapManifest`, `WorktreeOverlay`, `EffectiveMapView` e a
  chave de identidade/invalidação — `[implementado]`
  `simplicio_mapper/mapper/canonical.py`.
- Resolução pura de identidade (repo/branch default/common-dir) —
  `[implementado]` `simplicio_mapper/mapper/canonical_identity.py` (#254).
- Estratégia de armazenamento content-addressed (path arithmetic) —
  `[implementado]` `simplicio_mapper/mapper/canonical_storage.py` (#256).
- Builder real do `CanonicalMapManifest` contra o commit da branch default
  (via `git worktree add --detach` temporário), incluindo promoção atômica
  via `os.replace` — `[implementado]`
  `simplicio_mapper/mapper/canonical_builder.py` (#261, reconciliado em
  #272).
- Cálculo de `WorktreeOverlay` (tree diff + staged/unstaged/untracked) —
  `[implementado]` `simplicio_mapper/mapper/canonical_overlay.py` (#258).
- Composição lazy do `EffectiveMapView` — `[implementado]`
  `simplicio_mapper/mapper/effective_view.py` (#259).
- Reaproveitamento do lock single-flight existente (`_index_engine.py`),
  estendido — não substituído — para a chave canônica — **ainda não
  implementado**: nenhuma referência a uma operação `canonical-build` existe
  em `_index_engine.py` nesta revisão; o lock cross-worktree descrito na
  seção 4 permanece desenho, não código.
- Plano de migração passo a passo preservando contrato/CLI atuais via
  adapter.

Fora do escopo desta ADR (fases futuras — status confirmado nesta revisão,
tracked na issue #263 e filhas #266/#267/#268/#269/#270, trabalhadas por
outros agents em paralelo, fora do escopo desta atualização):

- Qualquer mudança de comportamento runtime dos comandos existentes
  (`index`, `scan`, `status`) — nenhum comando existente chama
  `canonical_builder`/`effective_view` ainda (confirmado: nenhum hit em
  `simplicio_mapper/cli/`).
- Extensão do lock single-flight para uma operação `canonical-build`
  (seção 4) — desenhado, não implementado.
- GC de snapshots (promoção atômica em si já está implementada, ver acima;
  GC por `generation` continua desenho).
- Comandos `canonical status/build/verify/gc`.
- API async para o Loop Hub.

### 1. Chave de identidade (`CanonicalMapKey`)

A chave que decide se um manifesto canônico pode ser reaproveitado. Nunca
reutilizar quando qualquer campo abaixo não corresponder — miss silencioso é
proibido; toda invalidação deve ser observável (motivo registrado, ver
`EffectiveMapView.diagnostics`).

| Campo | Origem | Observação |
|---|---|---|
| `repo_identity` | hash estável do remoto `origin` (URL normalizada) ou, na ausência de remoto, hash do `git rev-parse --git-common-dir` resolvido a caminho absoluto canônico | não usar path do worktree — dois worktrees do mesmo repo compartilham `repo_identity` |
| `default_branch` | resolvida via `git symbolic-ref refs/remotes/origin/HEAD` com fallback para `git remote show origin` / heurística `main`→`master`→primeira branch local; nunca hardcoded | nome customizado é suportado por design (issue pede explicitamente) |
| `commit_sha` | SHA do commit apontado pela branch default no momento do build | root do snapshot canônico |
| `tree_sha` | SHA da tree raiz desse commit | detecta merges/rebases que reescrevem a branch sem necessariamente mudar arquivos individuais mapeados |
| `schema_version` | constante deste módulo (`CANONICAL_MAP_SCHEMA_VERSION`) | bump em qualquer mudança de forma do manifesto |
| `mapper_version` | `importlib.metadata.version("simplicio-mapper")` (mesmo helper que `_index_engine._mapper_version()`) | |
| `config_fingerprint` | hash determinístico dos parâmetros de mapeamento — filtros, ignore rules, linguagem/parser, modo de embeddings (ver `WorktreeOverlay.config_fingerprint` abaixo, calculado com a mesma função) | dois worktrees com config diferente NUNCA compartilham `CanonicalMapManifest`, mesmo no mesmo commit |
| `platform_tag` | só populado quando o parser/config declarar `platform_sensitive=True` (ex.: paths de symlink resolvidos diferente em Windows); caso contrário `None` | mantém o snapshot compartilhável entre SO por padrão, conforme pedido pela issue ("plataforma somente quando afetar o resultado") |

`CanonicalMapKey.digest()` — hash estável (blake2b, mesmo padrão de
`FileProcessingCache`) de todos os campos acima em ordem fixa — é o nome do
diretório content-addressed (ver seção 3).

### 2. Schemas

Implementados em `simplicio_mapper/mapper/canonical.py` (dataclasses,
`frozen=True` onde imutabilidade é uma invariante, mais constantes de
versão). Campos completos (a serem implementados nesta fase):

```python
CANONICAL_MAP_SCHEMA_VERSION = 1
WORKTREE_OVERLAY_SCHEMA_VERSION = 1
EFFECTIVE_MAP_VIEW_SCHEMA_VERSION = 1

CANONICAL_MAP_SCHEMA = "simplicio.canonical-map/v1"
WORKTREE_OVERLAY_SCHEMA = "simplicio.worktree-overlay/v1"
EFFECTIVE_MAP_VIEW_SCHEMA = "simplicio.effective-map-view/v1"

@dataclass(frozen=True)
class CanonicalMapKey:
    repo_identity: str
    default_branch: str
    commit_sha: str
    tree_sha: str
    schema_version: int
    mapper_version: str
    config_fingerprint: str
    platform_tag: str | None = None

    def digest(self) -> str: ...

@dataclass(frozen=True)
class CanonicalMapManifest:
    schema: str                  # CANONICAL_MAP_SCHEMA
    schema_version: int          # CANONICAL_MAP_SCHEMA_VERSION
    key: CanonicalMapKey
    storage_root: str            # content-addressed dir, relative to common git dir
    artifact_paths: dict[str, str]   # logical name -> relative path inside storage_root
    file_manifest_digest: str    # digest of the full (path, blob_sha) set mapped
    counts: dict[str, int]       # files/symbols/relationships/... at canonical build time
    created_at: str              # ISO-8601 UTC
    builder: dict[str, str]      # pid/host/process_start_identity of the process that built it — audit trail, not a lock
    generation: int              # monotonic counter for promotion/GC ordering

@dataclass(frozen=True)
class WorktreeOverlay:
    schema: str                  # WORKTREE_OVERLAY_SCHEMA
    schema_version: int          # WORKTREE_OVERLAY_SCHEMA_VERSION
    base_key: CanonicalMapKey     # the canonical manifest this overlay is computed against
    worktree_path: str            # absolute path of the worktree that produced this overlay (never leaked into canonical storage)
    worktree_commit_sha: str      # HEAD of the worktree if it diverges from base_key.commit_sha
    config_fingerprint: str       # must match base_key.config_fingerprint bit-for-bit or the overlay is rejected as incompatible
    changed_files: tuple[OverlayFileChange, ...]
    tombstones: tuple[str, ...]   # removed/renamed source paths, relative
    dirty: bool                   # True when staged/unstaged/untracked changes contributed to the overlay
    created_at: str

@dataclass(frozen=True)
class OverlayFileChange:
    path: str                    # relative to repo root
    change_type: str             # "added" | "modified" | "renamed" | "removed"
    previous_path: str | None    # set for "renamed"
    content_digest: str | None   # None for "removed"

@dataclass(frozen=True)
class EffectiveMapView:
    schema: str                  # EFFECTIVE_MAP_VIEW_SCHEMA
    schema_version: int          # EFFECTIVE_MAP_VIEW_SCHEMA_VERSION
    canonical: CanonicalMapManifest
    overlay: WorktreeOverlay | None   # None when the worktree IS the default branch at the canonical commit, no delta
    diagnostics: EffectiveMapDiagnostics

@dataclass(frozen=True)
class EffectiveMapDiagnostics:
    cache_hit: bool
    single_flight_waited: bool
    files_reused: int
    files_remapped: int
    invalidation_reason: str | None   # populated whenever a reuse attempt was rejected
```

`EffectiveMapView` é a única coisa que o pipeline de consumo (query, ask,
status) deveria enxergar depois que o wiring acontecer — é uma visão
lazy/composta, nunca uma cópia materializada do mapa-base inteiro (requisito
explícito da issue, passo 8 do plano).

### 3. Armazenamento content-addressed

- Localização preferencial: `<git-common-dir>/simplicio/canonical/<digest>/`
  — resolvido via `git rev-parse --git-common-dir`, que já aponta para o
  `.git` compartilhado entre todos os worktrees de um mesmo repositório
  (incluindo o worktree principal). Isso satisfaz o requisito da issue de
  ficar "fora do diretório específico do worktree".
- Override configurável: variável de ambiente
  `SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR` (mesmo padrão de nomenclatura de
  `SIMPLICIO_MAPPER_NO_RUNTIME_*` já usado no projeto) para cache central
  compartilhado entre máquinas/CI, quando o common git dir não é persistente
  (ex.: runners efêmeros).
  quando não setado, fallback padrão é o common git dir.
- `<digest>` é `CanonicalMapKey.digest()` — dois worktrees com chave idêntica
  resolvem para o mesmo diretório automaticamente, sem coordenação adicional
  (requisito da issue: "dois worktrees idênticos devem compartilhar o mesmo
  overlay content-addressed" — aqui vale tanto para o manifesto canônico
  quanto, com uma chave análoga que inclui `worktree_commit_sha` +
  `config_fingerprint` + o digest do diff, para overlays).
- Overlays (por serem específicos de um estado de worktree, potencialmente
  dirty) vivem em um subdiretório separado
  `<git-common-dir>/simplicio/overlays/<overlay_digest>/`, nunca dentro do
  diretório do manifesto canônico — mantém o manifesto canônico
  verdadeiramente imutável após a promoção atômica (seção 5).

### 4. Lock single-flight — reaproveitar, não reinventar

A issue pede lock com lease/heartbeat e recuperação de processo morto — isso
**já existe** em `_index_engine.py` (`_acquire_index_lock` /
`_inspect_index_lock` / `_release_index_lock`, ver Contexto acima) e cobre
exatamente os requisitos: `O_CREAT|O_EXCL` atômico, `process_start_identity`
contra PID reuse, TTL, nunca reclama dono vivo. A decisão desta ADR é
**estender esse mecanismo para uma segunda classe de lock com a mesma
implementação**, não escrever um segundo lock do zero:

- Generalizar `_lock_path`/`_acquire_index_lock`/`_inspect_index_lock` para
  aceitarem um `lock_path` explícito e um campo `operation` no registro
  (o registro já tem `"operation": "index"` hoje — só precisa de um segundo
  valor, ex. `"operation": "canonical-build"`), em vez de duplicar toda a
  lógica de PID/TTL/malformed-grace para o novo lock canônico.
  Path do lock canônico:
  `<git-common-dir>/simplicio/canonical/<digest>/build.lock`.
- Semântica idêntica: quem perde a corrida de `O_CREAT|O_EXCL` espera (ou
  falha rápido, conforme o modo síncrono/assíncrono do chamador) e depois lê
  o manifesto já promovido pelo vencedor — nunca dois processos escrevem o
  mesmo `<digest>` simultaneamente.
- Overlays por worktree continuam usando o lock **existente**, sem mudança
  (`index.lock` já é por-worktree e já está correto para essa camada — só o
  manifesto canônico compartilhado precisa do lock cross-worktree novo).

### 5. Promoção atômica e GC

- **Promoção atômica — `[implementado]`**: `canonical_builder.py` escreve em
  um diretório temporário (`<...>/<digest>.tmp-<pid>/`, via
  `canonical_manifest_tmp_dir`) e promove com `os.replace` para
  `<...>/<digest>/` só depois que todos os artefatos estiverem completos.
  Concorrência coberta: se outro processo já promoveu o mesmo digest
  enquanto o build local rodava, o builder prefere a cópia já promovida e
  descarta a própria (idempotência por conteúdo, não por quem chegou
  primeiro).
- `generation` monotônico em `CanonicalMapManifest` permite ao GC futuro
  identificar snapshots superados sem depender de mtime (que pode ser
  não-monotônico em alguns filesystems/clock skew).
  GC remove digests sem manifesto referenciado por nenhum branch-tip
  recente nem em uso (lock/lease ativo) — **ainda desenhado, não
  implementado**; tracked na issue #268.

### 6. Plano de migração (passo a passo, preservando contrato atual)

1. **Esta ADR + `simplicio_mapper/mapper/canonical.py`** (Fase 0, este PR):
   schemas e constantes de versão, testados isoladamente, zero wiring.
2. Resolver identidade de repo/branch default/common-dir
   (`git rev-parse --git-common-dir`, `git symbolic-ref
   refs/remotes/origin/HEAD`) como função pura testável, sem tocar o
   pipeline de index existente.
3. Implementar builder do `CanonicalMapManifest` reaproveitando
   `mapper/parse.py`/`graph.py`/`emit.py` como estão — o builder roda o
   mesmo pipeline de hoje, mas contra o commit da branch default via
   `git worktree add --detach` temporário ou leitura direta de blobs
   (`git cat-file`), nunca contra o working tree sujo de um worktree.
4. Implementar cálculo de `WorktreeOverlay` via tree diff
   (`git diff <base_commit> <worktree_head>` + `git status --porcelain` para
   staged/unstaged/untracked) reaproveitando os mesmos parsers por arquivo
   afetado.
5. Implementar `EffectiveMapView` como composição lazy (overlay sobrepõe
   canonical por path; tombstone remove; sem cópia integral).
6. Adapter: os comandos existentes (`index`, `scan`, `status`, `ask`)
   continuam produzindo exatamente os mesmos artefatos/contratos de hoje —
   o adapter materializa `EffectiveMapView` para o formato atual quando um
   comando pede um artefato concreto, preservando 100% de compatibilidade
   de output.
7. Comandos novos `canonical status/build/verify/gc` — camada de
   observabilidade/operação por cima do que já existe, sem substituir os
   comandos atuais.
8. API sync/async para o Loop Hub — depois que 1-7 estiverem estáveis e com
   benchmark comprovando o ganho pedido pela issue.

Cada passo acima é um PR próprio, sequenciado, cada um preservando o
comportamento observável dos comandos existentes até que o passo 6
(adapter) explicitamente troque o caminho de dados por trás do mesmo
contrato.

**Status confirmado nesta revisão (2026-07-18)**:

- [x] Passo 1 — ADR + `canonical.py` (#237).
- [x] Passo 2 — identidade pura (#254, `canonical_identity.py`).
- [x] Passo 3 — builder real do `CanonicalMapManifest` (#256 storage + #261
      builder, reconciliado em #272).
- [x] Passo 4 — cálculo de `WorktreeOverlay` via tree diff (#258).
- [x] Passo 5 — composição lazy do `EffectiveMapView` (#259).
- [ ] Passo 6 — adapter dos comandos existentes (`index`/`scan`/`status`/
      `ask`) para consumir `EffectiveMapView` sem trocar contrato de saída —
      não implementado; tracked em #263/#269.
- [ ] Passo 7 — comandos `canonical status/build/verify/gc` — não
      implementado; tracked em #263/#266/#267/#268.
- [ ] Passo 8 — API sync/async para o Loop Hub — não implementado, depende
      de 1-7 estarem estáveis com benchmark.

Passos 6-8 são escopo de #263 e das issues filhas, trabalhadas por outros
agents em worktrees separados (`wt-mapper-266`..`wt-mapper-270`) em
paralelo a esta atualização — não duplicados aqui.

---

## Consequências

### Positivas (+)

- Elimina reprocessamento completo por worktree no caso comum (múltiplos
  worktrees na mesma branch default, mesma config).
- Reaproveita um mecanismo de lock já testado e battle-tested em produção
  (`_index_engine.py`) em vez de introduzir uma segunda primitiva de
  concorrência com sua própria superfície de bugs.
- Identidade de chave explícita e auditável elimina a classe de bug "mapa
  obsoleto servido silenciosamente" — todo miss tem `invalidation_reason`.
- Plano de migração incremental mantém cada PR revisável e sem mudança de
  comportamento até o passo do adapter.

### Negativas (-)

- Custo de implementação total é grande (12+ passos no plano da issue);
  esta ADR só cobre o desenho, não entrega o ganho de performance ainda.
- Introduz um segundo local de escrita fora do worktree (common git dir ou
  cache central) — superfície nova para diagnosticar quando algo dá errado
  (mitigado pelos comandos `canonical status/verify` planejados no passo 7).
- Builder do manifesto canônico precisa ler blobs de um commit sem
  necessariamente fazer checkout completo — implementação não trivial
  (`git worktree add --detach` temporário tem custo de I/O; leitura via
  `git cat-file --batch` é mais barata mas mais complexa de integrar com o
  parser atual que espera arquivos no disco).

### Neutras / observações

- `platform_tag` fica `None` por padrão; nenhum parser hoje declara
  `platform_sensitive=True` — o campo existe para o caso futuro (ex.: um
  parser que resolve symlinks de forma distinta em Windows) sem forçar
  invalidação cross-platform desnecessária agora.

---

## Alternativas consideradas

### Alternativa A — Lock/coordenação nova via arquivo de banco (SQLite compartilhado)

- Resumo: usar um arquivo SQLite no common git dir com `BEGIN IMMEDIATE` para
  coordenar single-flight, em vez do lock baseado em arquivo `O_CREAT|O_EXCL`.
- Por que foi descartada: adiciona dependência de runtime (mesmo que
  `sqlite3` seja stdlib, a lógica de retry/timeout de `BEGIN IMMEDIATE` em
  filesystems de rede é uma classe de bug conhecida) para resolver um
  problema que o lock por arquivo já resolve hoje, com testes existentes
  cobrindo PID reuse/TTL/malformed. Reinventar a roda contraria a instrução
  explícita da task de reaproveitar #201 em vez de duplicar.

### Alternativa B — Cache canônico chaveado só por `commit_sha` (sem `config_fingerprint`)

- Resumo: manter o manifesto canônico chaveado apenas por
  `(repo_identity, default_branch, commit_sha)`, ignorando config/schema no
  digest, e invalidar "por fora" quando config mudar.
- Por que foi descartada: viola diretamente o requisito da issue ("nunca
  reutilizar um mapa quando qualquer componente relevante da chave não
  corresponder") e reintroduz exatamente a classe de bug que a issue pede
  para eliminar — dois worktrees com filtros/embedding-mode diferentes
  silenciosamente compartilhando um mapa incompatível.

> Não fazer nada (continuar mapeando cada worktree do zero) foi considerado e
> rejeitado — é o status quo que motivou a issue, com custo de CPU/I/O que
> cresce linearmente com o número de worktrees ativos.

---

## Critério de revisão

- O passo 3 do plano de migração (builder do `CanonicalMapManifest` contra
  o commit da branch default) já está implementado (#261/#272), mas o
  benchmark real de ganho de CPU/RSS/I/O (`scripts/runtime_scale_benchmark.py`
  ou equivalente novo) pedido pelos critérios de aceite da issue #236 ainda
  não foi executado contra o builder canônico — tracked em #270. Rodar esse
  benchmark antes de declarar o ganho de performance comprovado; se o ganho
  for marginal, reavaliar se o content-addressing por `config_fingerprint`
  está fragmentando demais o cache.
- Revisar incondicionalmente após os passos 4-6 (overlay + composição +
  adapter) estarem em produção por um ciclo de release, antes de prosseguir
  para os comandos `canonical status/build/verify/gc` (passo 7). Passos 4-5
  (overlay, composição) já estão mergeados; passo 6 (adapter) segue
  pendente em #263/#269 — a condição desta revisão ainda não foi
  totalmente satisfeita.

---

## Links

- Issue: [#236](https://github.com/wesleysimplicio/simplicio-mapper/issues/236)
  (epic) — fatia executável tracked em #263, filhas #266/#267/#268/#269/#270.
- PRs de implementação: #237 (Fase 0 — ADR + schemas), #254 (identidade),
  #256 (storage paths), #258 (overlay delta), #259 (effective view),
  #261 (builder real), #272 (fix: reconcilia formato do file-manifest entre
  builder e effective view).
- Documentos relacionados: [DESIGN](./DESIGN.md), [PATTERNS](./PATTERNS.md)
- ADRs relacionados: [ADR-002](./ADR-002-python-rust-hybrid.md) (pipeline
  Python/Rust que o builder canônico reaproveita),
  [ADR-003](./ADR-003-two-tier-async-mapper.md) (two-tier async mapper —
  precedente para composição lazy de camadas)
- Código relevante nesta análise: `simplicio_mapper/mapper/canonical.py`,
  `canonical_identity.py`, `canonical_storage.py`, `canonical_builder.py`,
  `canonical_overlay.py`, `effective_view.py` (model layer completo, ver
  seção "Escopo desta ADR"); `simplicio_mapper/cli/_index_engine.py` (lock
  single-flight ainda não estendido para operação `canonical-build`);
  `simplicio_mapper/cache.py` (`FileProcessingCache`, cache por-arquivo hoje
  não compartilhado entre worktrees).
