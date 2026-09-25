# ADR-005: Consumir mapa canônico + overlay de worktree via contratos client-side (`map_view`), sem cliente de Map Service remoto

---

## Status

`Aceito`

---

## Data

`2026-07-17`

---

## Autores

- `Claude Code (agente, sessão simplicio-loop)`

---

## Contexto

Issue #213 pede que o dev-cli reutilize um mapa canônico da branch default + overlay do
worktree atual, evitando full remap redundante por task/retry/agent, e define os contratos
`CanonicalMapManifest`, `WorktreeOverlay`, `EffectiveMapView`, além de consulta prévia a um "Map
Service do Hub".

Este repositório (`simplicio-dev-cli`) só consome artefatos já construídos pelo pacote externo
`simplicio-mapper` (via `simplicio/mapper.py::run_mapper_json`, que já faz memoização por
processo chaveada em `(root, subcommand, revision, snapshot_id, extra)`). Não existe aqui nenhum
cliente HTTP para um "Map Service"/Hub — esse serviço, se existir, vive num pacote/repo
diferente (`simplicio-loop`). O que falta de fato neste código é: (1) nenhuma identidade git
(worktree/HEAD/merge-base/estado sujo) alimenta a decisão de reaproveitar contexto; (2) cada
worktree trata a si mesmo como totalmente isolado, sem reaproveitar um "núcleo" comum entre
worktrees irmãos do mesmo repositório; (3) nenhum "snapshot ID" é exposto para propagação em
receipts.

## Decisão

Implementar `simplicio/map_view.py` com os contratos exatos pedidos pela issue —
`CanonicalMapManifest`, `WorktreeOverlay`, `EffectiveMapView` — como a metade **standalone** do
plano da issue ("Implementar fallback standalone usando os mesmos contratos"), que uma futura
integração de cliente do Hub reaproveitaria sem mudar de forma:

- `resolve_git_identity(root)`: resolve `common_dir` (`git rev-parse --git-common-dir` — o mesmo
  truque que o próprio git usa para compartilhar o object database entre worktrees), `git_dir`
  (por-worktree), `head_sha`, `default_branch`, `merge_base_sha`, `dirty_fingerprint` (hash do
  `git status --porcelain`) e `mapper_config_fingerprint` (versão do binário `simplicio-mapper`).
- `CanonicalMapManifest`: persistido sob `common_dir` (compartilhado por todos os worktrees do
  mesmo repo), chaveado por `(common_dir, head_sha, mapper_config_fingerprint)`.
- `WorktreeOverlay`: persistido sob o `git_dir` **daquele worktree** (nunca sob
  `<root>/.simplicio`), chaveado por `(worktree_root, merge_base_sha, dirty_fingerprint)`.
- `EffectiveMapView`: combina os dois (ou cai para `full_remap`/`fallback_standalone` quando um
  deles está ausente/desatualizado), expõe `snapshot_id` propagável e um cache de processo
  (`_VIEW_CACHE`) que reutiliza o mesmo handle entre chamadas com a MESMA identidade viva —
  atende ao AC "Reutilizar o mesmo view handle durante todo o run/retry".
- `doctor_map_view_status()`: canonical_hit / overlay_hit / changed_files / source, pronto para
  um hook de `simplicio-py doctor`.

Fora de escopo (registrado para follow-up): cliente HTTP para o Map Service do Hub, invalidação
por-entidade fina (hoje a invalidação é por manifest inteiro, não por símbolo/arquivo
individual), e Process Supervisor central para o mapper.

---

## Consequências

### Positivas (+)

- Nenhuma dependência de rede nova: o standalone funciona hoje, sem exigir um Hub.
- Dois bugs reais foram encontrados e corrigidos durante a implementação (ver seção de testes):
  gravar o overlay dentro de `<root>/.simplicio` e logar via `emit_event(root=...)` ambos
  sujavam a própria árvore de trabalho a cada chamada, deslocando o `dirty_fingerprint` (e
  portanto o `snapshot_id`) para fora de si mesmo — exatamente o tipo de instabilidade que o
  contrato de reuso deveria evitar. Corrigido armazenando o overlay sob o `git_dir` (fora da
  árvore rastreada) e trocando o log estruturado por `info()` (stderr, sem escrita em disco).
- `_run_git` ganhou retry limitado para falha de spawn (`OSError` transitória), evitando que uma
  falha passageira de subprocess seja tratada como "não é um repo git" e force fallback/full
  remap desnecessário.

### Negativas (-)

- Não cobre a integração real com um Map Service remoto (Hub) — é a metade client-side/
  standalone do contrato, não o pedido completo da issue.
- Invalidação ainda é por manifest inteiro; não há "invalidar apenas as entidades afetadas"
  (AC 6 da issue) granular por símbolo.

### Neutras / observações

- `mapper_config_fingerprint` usa a string de versão do binário `simplicio-mapper` como proxy,
  já que não existe convenção de arquivo de config do mapper neste repositório ainda.

---

## Alternativas consideradas

### Alternativa A — Implementar o cliente HTTP do Map Service do Hub também

- Resumo: adicionar um cliente de rede que consulta um Hub externo antes de qualquer resolução
  local.
- Por que foi descartada: não há endpoint/contrato de Hub definido neste repositório nem no
  pacote `simplicio-mapper` instalado; construir um cliente contra uma API inexistente seria
  fabricar integração sem correspondência real, violando a política de não fabricar evidência.

### Alternativa B — Guardar o overlay em `<root>/.simplicio/worktree-overlay/`

- Resumo: primeira tentativa de implementação, guardando o overlay dentro da árvore rastreada.
- Por que foi descartada: descoberta em teste real (`test_map_view.py`) — o próprio arquivo do
  overlay aparece como untracked no `git status` da PRÓXIMA chamada, mudando o
  `dirty_fingerprint` e invalidando o próprio overlay que acabou de ser escrito. Substituído pelo
  armazenamento sob o `git_dir` do worktree (fora da árvore).

---

## Critério de revisão

- Se um cliente real de Map Service/Hub for definido em algum pacote deste ecossistema, revisitar
  para que `get_effective_map_view` consulte-o antes do caminho standalone, preservando os mesmos
  contratos.
- Se o mapper ganhar uma convenção de arquivo de config real, trocar `mapper_config_fingerprint`
  de "versão do binário" para hash do arquivo de config.

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-dev-cli/issues/213
- Implementação: `simplicio/map_view.py`
- Testes: `tests/python/test_map_view.py`
- Documentos relacionados: `[DESIGN](./DESIGN.md)`, `[PATTERNS](./PATTERNS.md)`, `[ADR-004](./ADR-004-async-runtime-additive.md)`
