# ADR-008: Mapa canônico da branch default com overlays incrementais por worktree

> Escrita originalmente como Fase 0 (só schemas, #237). **Atualizado
> 2026-07-18 (primeira passada)**: os passos 2-5 do plano de migração (seção
> "Plano de migração" abaixo) já foram implementados e mergeados nas issues
> #254, #256, #258, #259, #261 e reconciliados em #272.
>
> **Atualizado 2026-07-18 (segunda passada, fechamento da issue #236)**: o
> parágrafo acima ficou **stale** por uma revisão inteira -- dizia que os
> passos 6-8 "continuam não implementados", mas o **PR #281** já havia
> mergeado a fatia executável inteira da issue #263 (filhas
> #266/#267/#268/#269/#270): os comandos `canonical build/status/verify/gc`
> existem e funcionam (`simplicio_mapper/cli/_canonical.py`), e o caminho
> opt-in de reuso em `index`/`scan` também
> (`simplicio_mapper/mapper/canonical_reuse.py`,
> `--canonical-reuse`/`SIMPLICIO_MAPPER_CANONICAL_REUSE=1`). Confirmado por
> leitura direta do código nesta revisão, não pelo título dos commits. Duas
> lacunas genuínas permaneciam depois do PR #281, e esta passada as
> endereça:
>
> 1. **Seção 4 (lock single-flight cross-worktree)** -- estava "desenhada,
>    não implementada": `build_canonical_manifest` não usava nenhum lock
>    real, apenas promoção atômica + idempotência ("prefira a cópia já
>    promovida"). **Agora implementado**: a lógica de lock do
>    `_index_engine.py` (`_acquire_index_lock`/`_inspect_index_lock`/
>    `_release_index_lock`) foi extraída e generalizada para
>    `simplicio_mapper/mapper/file_lock.py`
>    (`acquire_lock_at`/`inspect_lock_at`/`release_lock_at`, aceitando um
>    `lock_path` explícito e um `operation` livre), e
>    `canonical_builder.build_canonical_manifest` passou a adquirir esse
>    lock (`operation="canonical-build"`) antes do trabalho caro de
>    checkout/pipeline -- ver seção 4 abaixo, reescrita para descrever a
>    implementação real, não mais o desenho.
> 2. **Passo 8 (API async para o Loop Hub)** -- permanece **genuinamente
>    fora do escopo deste repositório sozinho**: `simplicio-loop`/Loop Hub é
>    um produto/repositório separado (confirmado por
>    `simplicio_mapper/ecosystem_contract.py`, que já trata
>    `simplicio.loop-execution/v1` como um contrato *cross-repo* consumido
>    de fora, não código deste pacote). Ver "Decisão de fechamento" abaixo
>    para o que esta passada efetivamente entrega nessa frente (um modo
>    não-bloqueante `blocking=False` no builder, groundwork reutilizável por
>    uma futura integração) e o que continua bloqueado no outro repositório.

---

## Status

`Aceito` — desenho aprovado e majoritariamente implementado: model layer
completo (identidade, storage, builder, overlay, effective view), CLI
completo (`canonical build/status/verify/gc`, PR #281), reuso opt-in em
`index`/`scan` (PR #281), e agora o lock single-flight cross-worktree da
seção 4 (esta passada). Único item genuinamente pendente: o passo 8 (API
async para o Loop Hub), bloqueado em um repositório externo -- ver "Decisão
de fechamento".

---

## Data

`2026-07-17` (última atualização: `2026-07-18`, fechamento da issue #236)

---

## Autores

- `claude-agent` (Phase-0, issue #236)
- `claude-agent` (atualização de status pós-merge dos passos 2-5, issue #236, 2026-07-18)
- `claude-agent` (lock cross-worktree da seção 4 + fechamento da issue #236, 2026-07-18)

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
- Comandos `canonical build/status/verify/gc` sobre o modelo acima —
  `[implementado]` `simplicio_mapper/cli/_canonical.py` (#266/#267/#268,
  reconciliados em #281).
- Reuso opt-in do manifesto canônico em `index`/`scan` quando o overlay do
  worktree é trivial (`--canonical-reuse`/
  `SIMPLICIO_MAPPER_CANONICAL_REUSE=1`) — `[implementado]`
  `simplicio_mapper/mapper/canonical_reuse.py` (#269, #281). Overlay
  não-trivial cai sempre no full map legado (ver passo 6 abaixo para o
  detalhamento exato do que esse reuso cobre e não cobre).
- GC crash-safe de snapshots/staging dirs órfãos — `[implementado]`
  `simplicio_mapper/mapper/canonical_gc.py` (#268, #281).
- Reaproveitamento do lock single-flight existente (`_index_engine.py`),
  generalizado — não substituído — para a chave canônica —
  **`[implementado]` nesta passada**: o mecanismo de lock (schema/TTL/
  reclamação de dono morto/PID-reuse) foi extraído para
  `simplicio_mapper/mapper/file_lock.py`
  (`acquire_lock_at`/`inspect_lock_at`/`release_lock_at`, aceitando
  `lock_path` explícito + `operation` livre — o mesmo motivo pelo qual
  `process_liveness.py` já havia sido extraído de `_index_engine.py` para
  `simplicio_mapper.mapper`: este pacote não pode importar de
  `simplicio_mapper.cli`, a dependência só corre no sentido oposto).
  `_index_engine._acquire_index_lock`/`_inspect_index_lock` viraram
  wrappers finos com `operation="index"`; `canonical_builder.
  build_canonical_manifest` adquire o mesmo mecanismo com
  `operation="canonical-build"` antes do checkout/pipeline. Ver seção 4
  abaixo para o comportamento completo (espera limitada, reason codes,
  modo não-bloqueante).
- Plano de migração passo a passo preservando contrato/CLI atuais via
  adapter.

Fora do escopo desta ADR (única lacuna genuína remanescente — ver "Decisão
de fechamento" para por que é inerentemente cross-repo):

- API async/sync para o Loop Hub (passo 8) — o builder agora expõe um modo
  não-bloqueante (`blocking=False`) e códigos de motivo estáveis
  (`build_canonical_manifest_with_diagnostics`), que é o *groundwork* do
  lado deste repositório; a superfície de API real consumível pelo Loop Hub
  (contrato de transporte/callback) depende do outro repositório
  (`simplicio-loop`) e não pode ser fechada aqui.

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

### 4. Lock single-flight — reaproveitar, não reinventar — `[implementado]`

A issue pede lock com lease/heartbeat e recuperação de processo morto — isso
**já existia** em `_index_engine.py` (`_acquire_index_lock` /
`_inspect_index_lock` / `_release_index_lock`, ver Contexto acima) e cobria
exatamente os requisitos: `O_CREAT|O_EXCL` atômico, `process_start_identity`
contra PID reuse, TTL, nunca reclama dono vivo. Esta seção descrevia o
desenho de estender esse mecanismo; **agora é a implementação real**
(issue #236 gap #1, fechado nesta passada):

- **Extração**: a lógica de schema/TTL/reclamação (antes só dentro de
  `_index_engine.py`) foi movida para
  `simplicio_mapper/mapper/file_lock.py` — `acquire_lock_at(lock_path, *,
  operation, extra_fields=None)`, `inspect_lock_at(lock_path, *,
  recover=False)`, `release_lock_at(lock)`. Mesma razão de
  `process_liveness.py` já ter sido extraído do mesmo módulo (issue #268):
  `simplicio_mapper.mapper` não pode importar de `simplicio_mapper.cli` (a
  dependência só corre no sentido oposto), e `canonical_builder.py` (que
  vive em `mapper/`) precisa desses primitivos. `_index_engine.py` mantém
  `_acquire_index_lock(root, out)` / `_inspect_index_lock(root, out,
  recover=...)` / `_release_index_lock(lock)` como wrappers finos
  (`operation="index"`) — nenhum comportamento mudou para o caso de uso
  existente; `tests/python/test_lock_recovery.py` continua verde sem
  alteração.
- **Segundo valor de `operation`**: o registro do lock já tinha
  `"operation": "index"`; `canonical_builder.build_canonical_manifest`
  passou a adquirir o mesmo mecanismo com `"operation": "canonical-build"`
  antes do trabalho caro (checkout detached + `build_artifacts()`).
- **Path do lock canônico — ajustado versus o desenho original**: a seção 4
  original sugeria `<...>/<digest>/build.lock` (dentro do próprio diretório
  do manifesto). Na implementação isso foi deliberadamente trocado para
  `<cache_root>/canonical/<digest>.build.lock` — um **irmão** do diretório
  do manifesto, nunca um filho dele. Motivo: `canonical_manifest_dir`'s
  existência já é o sinal de "totalmente promovido" que o builder usa para
  decidir reuso (`if os.path.isdir(digest_dir): ...`), e `os.replace` não
  promove atomicamente um diretório temporário sobre um diretório de
  destino **não vazio** em todas as plataformas suportadas (Windows em
  particular) — colocar o lock dentro do diretório final o deixaria
  não-vazio antes da promoção, quebrando essa invariante. Ver
  `canonical_storage.canonical_build_lock_path`'s docstring para o mesmo
  raciocínio em código.
- **Semântica de espera/falha — implementada exatamente como desenhado**:
  `build_canonical_manifest(..., *, blocking=True, lock_wait_seconds=None)`
  (e sua contraparte com diagnóstico,
  `build_canonical_manifest_with_diagnostics`, que também devolve um
  `reason_code` estável):
  - `blocking=True` (default, preserva o comportamento de todo chamador
    existente): quem perde a corrida de `O_CREAT|O_EXCL` espera, limitado
    por `lock_wait_seconds` ou
    `SIMPLICIO_MAPPER_CANONICAL_BUILD_LOCK_WAIT_SECONDS` (default 600s —
    um orçamento de espera deliberadamente **menor** que o TTL de
    reclamação de dono morto do lock em si,
    `SIMPLICIO_MAPPER_LOCK_TTL_SECONDS`, default 6h: um esperador deve
    desistir bem antes de o próprio lock ser elegível para reclamação como
    abandonado), fazendo polling entre (a) o manifesto do vencedor aparecer
    promovido — devolvido diretamente, nunca reconstruído
    (`reason_code="reused_after_wait"`, o caso comum e o motivo real desta
    correção) — e (b) o lock ficar livre — tenta se tornar o novo dono e
    construir de verdade (`reason_code="built_after_wait"`, cobre o
    vencedor original ter crashado sem promover). Se o prazo esgotar sem
    nenhum dos dois, devolve `None`/`reason_code="lock_wait_timeout"`.
  - `blocking=False`: falha rápido
    (`None`/`reason_code="lock_contended_fail_fast"`) assim que encontra o
    lock ativo em outro dono vivo — para um futuro chamador assíncrono que
    prefira tentar de novo mais tarde a bloquear uma thread.
  - Nunca dois processos escrevem/promovem o mesmo `<digest>` ao mesmo
    tempo: quem detém o lock reconfere a idempotência
    (`_load_existing_manifest`) antes e depois do checkout, então libera o
    lock em um `finally` que cobre todo caminho de saída (sucesso, falha,
    exceção).
  - Testado com uma corrida real de dois processos de SO (não apenas
    threads) via `simplicio-mapper canonical build <path> --json` duas
    vezes contra o mesmo repositório —
    `tests/python/test_canonical_build_lock.py::CanonicalBuildLockConcurrentProcessRaceTest`
    — mesmo padrão de
    `test_lock_recovery.py::IndexLockConcurrentProcessRaceTest`. Prova que
    exatamente um processo reporta `reason_code="built"` e o outro reporta
    um código que prova que ele nunca refez o trabalho
    (`reused_after_wait`/`reused_cache_hit`/`built_after_wait`), e que
    ambos concordam byte-a-byte no manifesto resultante.
- Overlays por worktree continuam usando o lock **existente**, sem mudança
  (`index.lock` já é por-worktree e já está correto para essa camada — só o
  manifesto canônico compartilhado precisava do lock cross-worktree, agora
  implementado acima).
- **Observação sobre `canonical_reuse.py` (corrigido, não mais um TODO)**:
  esse módulo (issue #269, PR #281) já tinha seu próprio lock advisory, mais
  simples (`_single_flight_build`, staleness por mtime, sem PID-reuse/TTL),
  escrito exatamente no mesmo path (`canonical_manifest_dir(...) +
  ".build.lock"`, o mesmo `canonical_storage.canonical_build_lock_path`)
  que o lock real de `build_canonical_manifest_with_diagnostics` também
  passou a travar quando o gap #1 foi implementado. A primeira versão desta
  seção descrevia isso como "redundante, mas não removido nesta passada,
  para manter o escopo cirúrgico" -- na prática, era mais que redundante:
  era um self-deadlock garantido. `_single_flight_build` segurava o arquivo
  durante toda a chamada a `build_fn` (que é exatamente
  `build_canonical_manifest`); quando o lock real tentava
  `os.open(lock_path, O_CREAT | O_EXCL)` no mesmo path, batia em
  `FileExistsError`, e `inspect_lock_at` classificava o conteúdo (um PID cru,
  sem envelope JSON) como um lock "legacy" cujo dono era... o próprio
  processo chamador -- sempre vivo, portanto nunca reclamável. Resultado:
  `build_canonical_manifest_with_diagnostics` esperava o budget inteiro de
  `SIMPLICIO_MAPPER_CANONICAL_BUILD_LOCK_WAIT_SECONDS` (600s) antes de
  desistir com `reason_code="lock_wait_timeout"`, mesmo para um repositório
  isolado, recém-criado, sem nenhuma contenção real
  (`tests/python/test_canonical_reuse.py::AttemptCanonicalReuseIntegrationTests::test_clean_worktree_at_canonical_commit_is_a_hit`
  reproduzia isso em ~601s). Corrigido removendo o lock advisory duplicado:
  `canonical_reuse.attempt_canonical_reuse` agora chama
  `build_canonical_manifest_with_diagnostics` diretamente e deriva
  `single_flight_waited` do `reason_code` real (`reused_after_wait`/
  `built_after_wait`) em vez de manter um segundo mecanismo de lock
  competindo pelo mesmo arquivo. Regressão coberta por
  `test_first_call_never_blocks_on_the_build_lock_wait_budget`.

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

   > **Status (issue #269): parcialmente implementado.** `index`/`scan`
   > ganharam um caminho opt-in (`--canonical-reuse` /
   > `SIMPLICIO_MAPPER_CANONICAL_REUSE=1`, ver
   > `simplicio_mapper/mapper/canonical_reuse.py`) que reaproveita o
   > `CanonicalMapManifest` quando o overlay do worktree é **trivial**
   > (`HEAD` == commit canônico, sem staged/unstaged/untracked fora do
   > próprio `out`) — hit verbatim dos quatro artefatos canônicos +
   > `architecture-inventory` recomputado localmente (barato, derivado). Lock
   > single-flight é *advisory* (best-effort, nunca requerido pra
   > corretude — `build_canonical_manifest` já é idempotente/atômico).
   > Overlay não-trivial (dirty ou divergente) cai sempre no full map legado
   > (`fallback_reason="overlay_not_trivial"`), nunca é mesclado — mesclar um
   > overlay parcial em `symbol-index.json`/`call-graph.json` exigiria
   > re-derivar relações cross-file de um patch parcial, escopo maior que
   > esta issue; fica como follow-up (`status`/`ask` deste passo 6 também não
   > foram tocados, só `index`/`scan`). Benchmark real:
   > `scripts/canonical_reuse_benchmark.py` /
   > `docs/evidence/canonical-reuse-benchmark.json`.
7. Comandos novos `canonical status/build/verify/gc` — camada de
   observabilidade/operação por cima do que já existe, sem substituir os
   comandos atuais.
8. API sync/async para o Loop Hub — depois que 1-7 estiverem estáveis e com
   benchmark comprovando o ganho pedido pela issue.
   > **Status (issue #236, API de biblioteca): implementado.**
   > `simplicio_mapper/mapper/canonical_api.py` expõe
   > `get_effective_map_view()` e `get_effective_map_view_async()` para
   > consumidores in-process/Loop Hub. A API compartilha o mesmo fingerprint
   > do adapter `index`/`scan` quando o caller não informa um fingerprint
   > explícito, constrói/reusa o manifesto canônico, calcula o overlay do
   > worktree atual e retorna a composição lazy. Falhas de identidade, build,
   > overlay ou compatibilidade retornam `None` (fail-closed), nunca uma visão
   > parcial/obsoleta.


Cada passo acima é um PR próprio, sequenciado, cada um preservando o
comportamento observável dos comandos existentes até que o passo 6
(adapter) explicitamente troque o caminho de dados por trás do mesmo
contrato.

**Status confirmado nesta revisão (2026-07-18, segunda passada)**:

- [x] Passo 1 — ADR + `canonical.py` (#237).
- [x] Passo 2 — identidade pura (#254, `canonical_identity.py`).
- [x] Passo 3 — builder real do `CanonicalMapManifest` (#256 storage + #261
      builder, reconciliado em #272), **e agora com lock cross-worktree real
      (issue #236 gap #1, ver seção 4)**.
- [x] Passo 4 — cálculo de `WorktreeOverlay` via tree diff (#258).
- [x] Passo 5 — composição lazy do `EffectiveMapView` (#259).
- [x] Passo 6 — **parcialmente, e esse é o estado final aceito**: adapter
      opt-in para `index`/`scan` (`--canonical-reuse`/
      `SIMPLICIO_MAPPER_CANONICAL_REUSE=1`, #269, PR #281) quando o overlay é
      trivial; `status`/`ask` não foram tocados (ver nota já existente logo
      acima, inalterada). Não é 100% do passo original, mas é o escopo que
      #263/#269 efetivamente entregaram e aceitaram como fatia executável —
      o restante (overlay não-trivial mesclado, `status`/`ask`) é um
      follow-up conhecido, não um gap silencioso.
- [x] Passo 7 — comandos `canonical status/build/verify/gc` —
      **implementado**, `simplicio_mapper/cli/_canonical.py` (#266/#267/#268,
      reconciliados em PR #281). Confirmado por leitura direta do código e
      por `simplicio-mapper canonical --help` expondo os quatro subcomandos
      nesta revisão (a issue #263 original que motivou este item registrava
      exatamente o oposto -- "`simplicio-mapper --help` expõe nenhum comando
      `canonical`" -- isso já não é verdade no `main` atual).
- [x] Passo 8 — API sync/async para o Loop Hub — **implementado** em
      `simplicio_mapper/mapper/canonical_api.py` (PR #293):
      `get_effective_map_view()` e `get_effective_map_view_async()` resolvem
      manifesto canônico + overlay e retornam `EffectiveMapView` lazy, sem
      emitir recibos de CLI nem materializar artefatos por worktree — a
      biblioteca de reuso in-process que um futuro Loop Hub (ou qualquer
      consumidor Python embutido) chamaria. Esta passada (lock cross-worktree,
      issue #236 gap #1) também adicionou um modo não-bloqueante
      (`build_canonical_manifest_with_diagnostics(..., blocking=False)`) e
      códigos de motivo estáveis que `canonical_api.py` pode consumir sem
      bloquear uma thread síncrona. O que permanece genuinamente fora do
      alcance deste repositório sozinho é o **transporte cross-repo**
      (um contrato de request/callback/webhook que o lado `simplicio-loop`
      ainda precisa implementar e consumir) -- essa biblioteca local não
      inventa esse transporte, só o disponibiliza para quando ele existir.

Todos os 8 passos do plano de migração estão implementados nesta revisão. O
transporte cross-repo para o Loop Hub consumir `canonical_api.py` continua
fora do alcance deste repositório sozinho -- ver "Decisão de fechamento".

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
  o commit da branch default) está implementado (#261/#272) e agora inclui o
  lock cross-worktree (seção 4, esta passada), mas o benchmark real de ganho
  de CPU/RSS/I/O (`scripts/runtime_scale_benchmark.py` ou equivalente novo)
  pedido pelos critérios de aceite da issue #236 **ainda não foi executado
  contra o builder canônico especificamente** (existe sim
  `scripts/canonical_reuse_benchmark.py`/
  `docs/evidence/canonical-reuse-benchmark.json` para o caminho de reuso
  opt-in do passo 6, mas não um benchmark N-worktrees dedicado ao builder +
  lock em si). Continua um gap de evidência, não de correção — ver "Decisão
  de fechamento".
- A condição "revisar incondicionalmente após os passos 4-6 estarem em
  produção antes do passo 7" **já não se aplica**: o passo 7 (`canonical
  status/build/verify/gc`) já foi implementado e mergeado (PR #281) em
  paralelo ao passo 6 parcial, não estritamente depois — mantido aqui apenas
  como registro histórico da sequência real, não como bloqueio a reabrir.

---

### Decisão de fechamento (issue #236, atualizado após o gap #1 e reavaliação do gap #2)

Dos 8 passos do plano de migração, 7 estão implementados (1-7, com o passo 6
em escopo parcial aceito -- ver o checklist "Status confirmado" acima). O
único item genuinamente pendente é o **passo 8 (API sync/async para o Loop
Hub)**, e a avaliação honesta desta passada é que ele **não é fechável a
partir deste repositório sozinho**:

- `simplicio-loop`/Loop Hub é um produto/repositório separado do
  `simplicio-mapper`. A evidência disso já existe no próprio código deste
  repo: `simplicio_mapper/ecosystem_contract.py` trata
  `simplicio.loop-execution/v1` explicitamente como um contrato **cross-repo**
  --- um formato de payload que "flui através do ecossistema fora do
  mapper", validado aqui só para garantir compatibilidade, nunca produzido
  ou consumido por código deste pacote. Não existe, nem nunca existiu neste
  repositório, nenhuma implementação do lado Loop Hub para uma API async
  chamar.
- "Publicar uma API async para o Loop Hub" pressupõe, no mínimo: (a) um
  contrato de transporte (payload/schema de request-response, ou um
  mecanismo de callback/webhook/fila) que os dois lados concordem, e (b) um
  consumidor real do lado do Loop Hub que chame essa API -- nenhum dos dois
  pode ser definido unilateralmente por este repositório sem inventar uma
  integração fictícia que o outro lado nunca implementou. Fazer isso seria
  exatamente o tipo de "progresso fake" que esta tarefa pediu para evitar.
- O que **é** legitimamente do lado deste repositório, e foi entregue nesta
  passada como groundwork reaproveitável por uma futura integração real:
  `build_canonical_manifest_with_diagnostics(..., blocking=False)` -- um
  modo não-bloqueante com códigos de motivo estáveis
  (`lock_contended_fail_fast`, `reused_after_wait`, `built_after_wait`,
  `lock_wait_timeout`, etc.), exatamente o tipo de primitivo síncrono
  "fail-fast em vez de bloquear uma thread" que uma futura camada
  async/await ou um poller do lado do Loop Hub precisaria por baixo. Isso
  não é "a API para o Loop Hub" -- é o alicerce que a tornaria possível sem
  reescrever o builder de novo quando ela for especificada.

**Veredito**: a issue **#236 (epic) é fechável** com o passo 8 registrado
como um **follow-up cross-repo explícito**, não como um blocker escondido --
recomendação: abrir uma issue nova e específica (ex. "canonical-map async
API for Loop Hub integration", cross-linkada com a issue equivalente do lado
`simplicio-loop`, quando esse repositório estiver pronto para especificar o
contrato) em vez de manter #236 aberta indefinidamente por um item que só o
outro repositório pode de fato mover. A issue **#263 (fatia executável) é
fechável** integralmente: todas as suas 10 acceptance criteria mapeiam para
os passos 1-7 já implementados (incluindo agora o item 2 -- "usando bounded
single-flight locking e atomic promotion" -- fechado por esta passada), com
exceção do item 9 (benchmark N-worktrees dedicado, gap de evidência
separado, não de #263 per se) e item 14 fora do escopo de #263 (que nunca
prometeu o passo 8, apenas o tracking dele). O benchmark N-worktrees
dedicado ao builder (critério de revisão acima) e o follow-up cross-repo do
passo 8 são os dois itens que a sessão coordenadora deve decidir se tratam
como follow-ups pós-fechamento ou como razão para manter #236 aberta -- a
recomendação desta passada é follow-up, não blocker, já que nenhum dos dois
é um defeito de corretude ou segurança no código já mergeado.

---

## Links

- Issue: [#236](https://github.com/wesleysimplicio/simplicio-mapper/issues/236)
  (epic) — fatia executável tracked em #263, filhas #266/#267/#268/#269/#270.
- PRs de implementação: #237 (Fase 0 — ADR + schemas), #254 (identidade),
  #256 (storage paths), #258 (overlay delta), #259 (effective view),
  #261 (builder real), #272 (fix: reconcilia formato do file-manifest entre
  builder e effective view), #281 (integração executável: `canonical`
  CLI + reuso opt-in em `index`/`scan` + gc, fecha #266/#267/#268/#269/#270),
  e o PR desta passada (lock cross-worktree real, issue #236 gap #1 --
  `simplicio_mapper/mapper/file_lock.py` + wiring em `canonical_builder.py`).
- Documentos relacionados: [DESIGN](./DESIGN.md), [PATTERNS](./PATTERNS.md)
- ADRs relacionados: [ADR-002](./ADR-002-python-rust-hybrid.md) (pipeline
  Python/Rust que o builder canônico reaproveita),
  [ADR-003](./ADR-003-two-tier-async-mapper.md) (two-tier async mapper —
  precedente para composição lazy de camadas)
- Código relevante nesta análise: `simplicio_mapper/mapper/canonical.py`,
  `canonical_identity.py`, `canonical_storage.py`, `canonical_builder.py`,
  `canonical_overlay.py`, `effective_view.py`, `canonical_gc.py`,
  `canonical_verify.py`, `canonical_reuse.py` (model layer + CLI + reuso
  opt-in, ver seção "Escopo desta ADR"); `simplicio_mapper/mapper/file_lock.py`
  (lock single-flight generalizado, issue #236 gap #1, esta passada);
  `simplicio_mapper/cli/_index_engine.py` (wrappers finos
  `operation="index"` sobre `file_lock.py`); `simplicio_mapper/cli/_canonical.py`
  (`canonical build/status/verify/gc`); `simplicio_mapper/cache.py`
  (`FileProcessingCache`, cache por-arquivo hoje não compartilhado entre
  worktrees -- ainda fora do escopo desta ADR).
- Testes do gap #1 (lock cross-worktree): `tests/python/test_canonical_build_lock.py`
  (unit da máquina de espera/timeout, integração com lock real, e corrida
  real de dois processos de SO via `canonical build`); regressão coberta por
  `tests/python/test_lock_recovery.py` (inalterado) e
  `tests/python/test_canonical_builder.py` (inalterado).
