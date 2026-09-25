# ADR-010: Manifest de release local (Fase 0) para o Mapper (`simplicio.component-release/v1`)

> Endereça a issue #280 ("[P0][Release Train] Publicar release verificável
> do Mapper e disparar atualização downstream"), fatia executável do épico
> pai cross-repo `wesleysimplicio/simplicio-loop#558`. Relacionadas: #236,
> #263, #279, `wesleysimplicio/simplicio-dev-cli#231`.
>
> **Esta ADR documenta explicitamente uma Fase 0 parcial.** O plano de 12
> passos e os critérios de aceite da issue #280 descrevem um release train
> completo — manifest assinado, SBOM, eventos cross-repo autenticados,
> canal canary, bump automático de consumidores downstream em até 15
> minutos, verificação de digest/assinatura, rollback. Implementar tudo
> isso nesta issue seria especular sobre infraestrutura que este repositório
> não possui e não controla sozinho (autoridade de assinatura, receptor de
> evento/webhook cross-repo do lado do Dev CLI, canal de distribuição
> canary). Esta ADR escopa deliberadamente **apenas** a fatia local,
> determinística e verificável a partir deste repositório hoje.

---

## Status

`Aceito`

---

## Data

`2026-07-18`

---

## Autores

- Claude (agente, sessão issue #280)

---

## Contexto

### (a) Inventário dos version fields hoje existentes neste repo

Version fields de **pacote** (identidade do release como um todo):

| Fonte | Campo | Valor observado nesta revisão |
|---|---|---|
| `package.json` | `"version"` | `0.24.1` |
| `pyproject.toml` | `version = "..."` | `0.24.1` |
| `simplicio_mapper/__init__.py` | `__version__` | `"0.24.1"` |

`node scripts/check-version-sync.js` **já existe e já mantém esses três
campos sincronizados** — confirmado por leitura direta do script
(`scripts/check-version-sync.js`): ele lê os três arquivos, compara os
valores e falha (`exitCode = 1`) se divergirem, com uma mensagem apontando
para `.specs/workflow/CONTRIBUTING.md`/`RELEASE.md`. A alegação da issue
#280 de que "hoje não existe uma fonte única de versão" está **parcialmente
desatualizada**: a fonte única de versão *de pacote* já existe e já é
verificada em CI/local — o que genuinamente falta é tudo o resto do plano
de 12 passos (manifest assinado, eventos, canary, etc.).

Version fields de **schema de artefato** (identidade de cada formato JSON
que o mapper produz) são uma categoria **separada** e **não coberta** por
`check-version-sync.js` — cada uma vive como uma constante independente em
algum módulo de `simplicio_mapper/`, sem checagem cruzada de consistência
até esta ADR. Inventário completo (via `grep -rn "SCHEMA_VERSION\|_VERSION\s*="`
sobre `simplicio_mapper/`, excluindo usos/imports — apenas definições):
ver `simplicio_mapper/release_manifest.py::SCHEMA_VERSION_REGISTRY`, que é
o registro hand-maintained canônico usado pelo gerador de manifest desta
ADR. Ele cobre, entre outras: `ARTIFACT_VERSION` (`mapper/parse.py`),
`CANONICAL_MAP_SCHEMA_VERSION`/`WORKTREE_OVERLAY_SCHEMA_VERSION`/
`EFFECTIVE_MAP_VIEW_SCHEMA_VERSION` (`mapper/canonical.py`),
`CANONICAL_GC_SCHEMA_VERSION`, `CANONICAL_VERIFY_SCHEMA_VERSION`,
`RECEIPT_SCHEMA_VERSION` (`mapper/canonical_reuse.py`), `CONTRACT_VERSION`
(duas instâncias independentes: `contract.py` para mapper-artifacts/v1 e
`ecosystem_contract.py` para ecosystem/v1 — namespaces distintos, não
precisam concordar entre si), `CONTEXT_CACHE_STRUCTURED_VERSION`,
`SCHEMA_VERSION` (`context_dag.py` e `context_snapshot.py`, também
independentes), `BUSINESS_RULES_VERSION`, `CLUSTERING_VERSION`,
`DOCS_SYNC_VERSION`, `SPEC_DRIFT_VERSION`, `FLOW_ARTIFACT_VERSION`,
`DOC_HISTORY_VERSION`, `RETRIEVAL_INDEX_VERSION`, `ONBOARDING_VERSION`,
`VISUALIZATION_VERSION`/`PREVIEW_VERSION`, e as duas constantes de
`cli/_shared.py` (`CANONICAL_BUILD_SCHEMA_VERSION`,
`CANONICAL_STATUS_SCHEMA_VERSION`).

Nenhum desses ~25 pontos era, antes desta ADR, comparado contra um baseline
— um bump acidental (ou uma constante renomeada/removida sem querer) não
tinha nenhum gate local para pegar.

### (b) Por que não existe hoje um manifest de release do ecossistema

Confirmado por leitura do repo: não existe nenhum arquivo/schema
`simplicio.component-release/v1` (ou equivalente) hoje. `SIMPLICIO_ECOSYSTEM.md`
(`scripts/generate-ecosystem-doc.py`, issue #156) documenta *quem depende*
do Mapper e a versão mínima esperada — mas é gerado a partir de
`scripts/ecosystem-consumers.json`, mantido **manualmente**, e não publica
identidade assinada, digests, SBOM, nem dispara evento nenhum. Não existe
publicação de evento cross-repo, canal canary, nem verificação automática
de bump downstream.

### (c) Relação com ADRs anteriores

- ADR-006 (`package-identity-channels.md`) já decide os dois canais de
  distribuição (PyPI `simplicio-mapper` canônico, npm
  `@wesleysimplicio/llm-project-mapper` como shim/scaffolder) — esta ADR
  não reabre essa decisão, apenas referencia os dois nomes de pacote no
  manifest.
- ADR-008 (`canonical-map-overlays.md`) e ADR-009
  (`async-mapping-pipeline.md`) usam o mesmo padrão de "escopar
  explicitamente o que fica de fora, tracked em issue separada" — esta ADR
  segue o mesmo padrão para o release train.

---

## Decisão

Implementar **apenas** a fatia local, determinística e verificável do plano
de 12 passos da issue #280:

### Escopo desta ADR (implementado)

1. **Forma do manifest `simplicio.component-release/v1`** (issue #280 passo
   1-3, parcial): um dicionário com os campos abaixo, gerado localmente por
   `simplicio_mapper/release_manifest.py::build_release_manifest()` e
   exposto via `simplicio-mapper release-manifest [--json]`:

   ```json
   {
     "schema": "simplicio.component-release/v1",
     "component": "simplicio-mapper",
     "version": "<simplicio_mapper.__version__, fonte única existente>",
     "commit_sha": "<git rev-parse HEAD, ou null>",
     "commit_sha_source": "git rev-parse HEAD | unavailable: <motivo>",
     "generated_at": "<ISO-8601 UTC>",
     "distribution": {
       "pypi_package": "simplicio-mapper",
       "npm_package": "@wesleysimplicio/llm-project-mapper"
     },
     "schema_versions": { "<modulo>:<constante>": "<valor>", "...": "..." },
     "protocols": ["simplicio.component-release/v1", "simplicio.mapper-artifacts/v1", "..."],
     "artifact_digest": "sha256:<digest-estavel-da-identidade-de-release>",
     "signing": {
       "status": "not-implemented",
       "digest": null,
       "signature": null,
       "sbom": null,
       "note": "Fase-0 local apenas -- ver decisão abaixo."
     },
     "downstream_events": {
       "status": "not-implemented",
       "note": "Cross-repo, canary e bump automático ficam fora de escopo -- ver decisão abaixo."
     }
   }
   ```

   `digest`/`signature`/`sbom` são explicitamente `null` com um `note`
   textual — nunca um valor fake/placeholder que pareça real. Nenhuma
   chamada de rede, nenhuma dependência nova.

2. **Registro de schema-versions consistente** (issue #280 passo 8, apenas
   a metade verificável localmente): `SCHEMA_VERSION_REGISTRY` em
   `release_manifest.py` é uma lista hand-maintained de `(módulo, atributo)`
   — o *valor* nunca é hardcoded na ADR/registro, é importado ao vivo em
   `collect_schema_versions()`, então o registro em si nunca pode divergir
   da fonte. O que pode divergir é o **baseline commitado**
   (`scripts/schema_registry_baseline.json`) vs. o valor ao vivo — checado
   por `check_registry_baseline()` / `scripts/check_schema_registry_sync.py`.
   Isso é literalmente o mesmo padrão já usado por
   `scripts/token_budget.py` (issue #174): baseline commitado + gate que
   falha em drift não reconhecido + flag `--update-baseline` para uma
   mudança deliberada.

### Fora de escopo desta ADR (decisão explícita, não esquecimento)

Os itens abaixo do plano de 12 passos da issue #280 **não** são
implementados aqui porque dependem de infraestrutura que este repositório
não possui/controla sozinho:

- **Assinatura/digest/SBOM reais** (passo 3) — requer uma autoridade de
  assinatura (chave, processo de custódia, verificação) que não existe
  hoje em nenhum repo do ecossistema. Decisão futura e separada, uma vez
  que essa autoridade seja escolhida.
- **Evento autenticado cross-repo após release confirmada / reconciliação
  por polling / bump downstream em até 15 minutos** (passos 6, 7, 12
  critério de aceite) — requer um receptor de evento/webhook do lado de
  `simplicio-dev-cli`/`simplicio-loop` que este repo não pode construir
  unilateralmente. Precisa de design coordenado nesses repos (ver o épico
  pai `wesleysimplicio/simplicio-loop#558` e
  `wesleysimplicio/simplicio-dev-cli#231`).
- **Canal canary + promoção condicionada a consumidor verde** (passo 10) —
  requer um canal de distribuição que não existe (PyPI/npm hoje só têm um
  canal `stable`).
- **Detecção de divergência PyPI/npm real** (passo 8, metade não coberta
  aqui) — exigiria chamadas reais às APIs de registry (PyPI JSON API, npm
  registry API) para comparar a versão publicada vs. local; especular essa
  integração sem um caso de uso real e sem decidir autenticação/rate-limit
  seria exatamente o tipo de infraestrutura inventada que esta ADR evita.
- **Classificação automática compatible/breaking de mudanças de
  project-map/precedent-index/ContextSnapshot/overlays** (passo 4) e
  **fixtures de conformance N/N-1 versionadas** (passo 5) — dependem de um
  histórico de releases publicadas com o manifest desta ADR já em uso por
  mais de uma versão; não há ainda uma "release N-1" com este formato para
  comparar. Revisitar depois da primeira release real usando este
  manifest.
- **Rollback/revogação reproduzíveis** (critério de aceite) — depende do
  canal canary e do evento cross-repo acima; sem eles, não há o que
  reverter de forma automatizada.

---

### Adendo (mesma ADR, mesma issue #280): digests reais de artefatos `dist/`

Depois da versão original desta ADR, ficou claro que existe uma fatia
adicional, honesta e ainda de baixo risco dentro do passo 3 da issue #280
("digests, signatures, SBOM"): um **digest SHA256** dos arquivos
`dist/*.whl`/`dist/*.tar.gz` já construídos é **apenas um checksum de bytes
que já existem em disco** -- diferente de uma **assinatura criptográfica**,
que continua exigindo uma autoridade de assinatura que este repo não possui
(decisão original desta ADR, inalterada). Este adendo documenta a extensão:

- `simplicio_mapper/release_manifest.py::compute_artifact_digests()` calcula
  `sha256:<hex>` real dos artefatos encontrados em um `dist_dir` (default
  `dist/` na raiz do repo, `--dist-dir <path>` na CLI). Quando o diretório
  ou os arquivos não existem, o campo correspondente fica `None`/ausente
  com uma `note` honesta -- nunca um placeholder fabricado. Se houver mais
  de um arquivo `.whl`/`.tar.gz` no diretório (build ambígua), a função se
  recusa a adivinhar qual é "o" artefato do release e retorna `None` com
  nota explicando a ambiguidade.
- O manifest ganha um campo **novo e distinto** de `signing`:
  `artifact_digests: {"whl": {"filename": ..., "digest": "sha256:..."},
  "sdist": {...}}`. O bloco `signing` permanece com `status:
  "not-implemented"` e `digest: null` para a *assinatura* em si -- o
  checksum honesto não é apresentado como, nem substitui, uma assinatura.
- `simplicio_mapper/release_manifest.py::verify_artifact_digests()` (exposto
  via `simplicio-mapper release-manifest --verify-digests <manifest.json>
  --dist-dir <path>`) compara os digests gravados num manifest já gerado
  contra os arquivos reais em `dist_dir` -- reporta `match`/`mismatch`/
  `missing-on-disk`/`missing-in-manifest` por artefato. Isso é a fatia
  "impedir tag se ... divergirem" do passo 8 que é verificável **puramente
  localmente** (integridade artefato-vs-manifest) -- **não** é a checagem de
  divergência PyPI/npm real do passo 8 (que exigiria chamadas de rede à API
  de registry, permanece fora de escopo, ver seção "Fora de escopo" acima,
  inalterada por este adendo).
- Escolha de teste documentada em `tests/python/test_release_manifest.py`
  (classe `ArtifactDigestsTest`): a suíte usa arquivos `.whl`/`.tar.gz`
  fake-mas-reais (bytes conhecidos, digest esperado calculado
  independentemente via `hashlib.sha256` no próprio teste) para a maioria
  dos casos, porque um `python -m build` completo é lento (ambiente de build
  isolado) para um teste que só precisa provar "bytes reais em disco ->
  sha256 real". Um teste de integração único (`test_real_python_build_
  produces_verifiable_digests`) roda um `python -m build --wheel` de
  verdade contra o wheel real do próprio repo, para provar o caminho
  completo contra um artefato genuíno -- pulado (`skipTest`) caso o pacote
  `build` não esteja disponível no ambiente.

Este adendo não reabre nenhuma das decisões "fora de escopo" originais desta
ADR: assinatura criptográfica real, SBOM, eventos cross-repo, canal canary e
detecção de divergência PyPI/npm ao vivo continuam fora de escopo, pelas
mesmas razões já documentadas.

---

## Consequências

### Positivas (+)

- Existe agora, pela primeira vez, uma forma machine-readable única que
  reúne versão + commit + todo o inventário de schema-versions do Mapper —
  puramente local, sem custo de infraestrutura nova.
- O drift de schema-version (renomear/remover uma constante, ou mudar seu
  valor sem querer) agora falha em CI/local da mesma forma que um bump de
  versão de pacote parcial já falhava antes — gap real fechado.
- Nenhuma infraestrutura especulativa foi construída; o próximo passo
  (assinatura, eventos cross-repo) fica claramente definido e não-fingido.

### Negativas (-)

- O manifest desta ADR **não** é assinado e **não** prova integridade
  criptográfica nenhuma — é só um inventário local. Um consumidor que
  tratar `signing.status: "not-implemented"` como se fosse uma assinatura
  real está usando o campo errado (o `note` existe exatamente para evitar
  essa confusão).
- `SCHEMA_VERSION_REGISTRY` é mantido à mão; um novo módulo com uma
  constante de schema-version só entra no manifest se alguém lembrar de
  adicionar a entrada — não há descoberta automática (aceito
  explicitamente como custo de Fase 0, ver `.specs/architecture/PATTERNS.md`
  sobre "hand-maintained é aceitável quando documentado").
- A issue #280 permanece parcialmente aberta — a maior parte dos critérios
  de aceite dela não é resolvida por esta ADR/PR. Isso é intencional (ver
  seção "Fora de escopo" acima), mas precisa ficar claro no fechamento do
  PR para não ser lido como "issue resolvida".

### Neutras / observações

- `check-version-sync.js` (Node, 3 fontes de versão de pacote) e
  `check_schema_registry_sync.py` (Python, ~25 constantes de schema-version)
  são gates **irmãos**, deliberadamente não fundidos em um único script —
  um é Node porque os 3 arquivos que ele lê são triviais de parsear sem
  importar o pacote Python; o outro precisa importar `simplicio_mapper` de
  verdade para ler os valores ao vivo das constantes, o que só faz sentido
  em Python.

---

## Alternativas consideradas

### Alternativa A — Implementar o plano de 12 passos completo nesta issue

Resumo: tentar já entregar assinatura, SBOM, evento cross-repo, canary e
rollback nesta mesma mudança.

Por que foi descartada: nenhuma dessas peças tem uma decisão de design already
tomada (que autoridade assina? qual formato de SBOM? qual protocolo de
evento o Dev CLI vai escutar?) — implementá-las agora seria inventar
contratos que outro repositório teria que aceitar sem ter sido consultado.
Alto risco de retrabalho completo assim que o design real do lado
`simplicio-dev-cli`/`simplicio-loop` for definido.

### Alternativa B — Não fazer nada nesta issue até o design cross-repo estar pronto

Resumo: esperar o épico pai `simplicio-loop#558` definir o desenho completo
antes de tocar em qualquer código no Mapper.

Por que foi descartada: existe uma fatia real, útil e de baixo risco
(inventário local + gate de drift) que não depende de nenhuma decisão
cross-repo — adiá-la também adiaria, sem necessidade, um gate de qualidade
que já vale a pena hoje.

### Alternativa C — Fundir `check_schema_registry_sync.py` dentro de `check-version-sync.js` (chamando Python via subprocess)

Resumo: um único script Node que, além dos 3 campos de versão de pacote,
dispara `python -m simplicio_mapper.release_manifest --check-registry`.

Por que foi descartada: acopla o gate de versão de pacote (hoje
independente de qualquer ambiente Python instalado) à disponibilidade de
um interpretador Python funcional só para essa checagem adicional — risco
de regressão no gate existente sem benefício real sobre manter os dois
scripts irmãos e independentes.

---

## Critério de revisão

- Quando a primeira release real usando este manifest existir, revisitar
  o passo "fixtures de conformance N/N-1" (fora de escopo aqui por falta
  de histórico).
- Quando uma autoridade de assinatura for escolhida (por qualquer repo do
  ecossistema), abrir uma ADR nova (não reabrir esta) para o formato de
  assinatura/SBOM real — esta ADR fica como o registro da decisão de
  *não* especular esse formato antes da hora.
- Quando `simplicio-dev-cli`/`simplicio-loop` decidirem o formato do
  receptor de evento cross-repo, revisitar `downstream_events` neste
  manifest para apontar para o formato real (hoje é só um placeholder
  textual).

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/280
- Épico pai (cross-repo): https://github.com/wesleysimplicio/simplicio-loop/issues/558
- Relacionadas: #236, #263, #279, `wesleysimplicio/simplicio-dev-cli#231`
- Implementação: `simplicio_mapper/release_manifest.py`,
  `scripts/check_schema_registry_sync.py`,
  `scripts/schema_registry_baseline.json`
- ADRs relacionados: [ADR-006](./ADR-006-package-identity-channels.md),
  [ADR-008](./ADR-008-canonical-map-overlays.md),
  [ADR-009](./ADR-009-async-mapping-pipeline.md)
