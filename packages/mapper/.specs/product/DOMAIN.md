# DOMAIN — simplicio-mapper

Vocabulário canônico do produto. Antes de criar nome novo, procura aqui;
antes de mudar nome existente, atualiza tudo que referencia.

---

## Entidades

- **Project** — diretório raiz que o mapper analisa. Identificado por `cwd`
  e (quando disponível) por commit SHA de `git rev-parse HEAD`.
- **ProjectFile** — entry deterministica do `files[]` em `project-map.json`.
  Carrega `path`, `language`, `roles`, `imports`, `exports`, `importance`,
  `file_hash`, `git_status`, `size_bytes`, `last_modified`.
- **Precedent** — snippet de alta qualidade extraído pelo mapper, tagueado
  por `change_type` (`feature`, `bugfix`, `test`, `refactor`, `docs`...).
- **ArchitectureSignal** — flag de framework/biblioteca detectado por
  heurística (e.g. `nextjs`, `fastapi`, `dotnet`, `prisma`).
- **Module / Layer** — agrupamento heurístico em `architecture-inventory.json`
  com camadas `entrypoint`, `domain`, `route`, `ui`, `config`, `test`.
- **Symbol** — classe, função, método ou export detectado, com `defined_in`,
  `line` e `evidence`.
- **CallEdge** — relação `imports` ou `calls` em `call-graph.json` com
  `confidence` (1.0 para imports resolvidos, <1.0 para heurísticas).
- **Endpoint** (`endpoints` command) — par método+path normalizado vindo de
  cliente (`client_calls`) ou servidor (`server_routes`), comparado por
  `missing_from_server`.
- **Screen** (`screens` command) — rota Angular declarativa com persona,
  redirect, guard e parâmetros dinâmicos.
- **IndexState** — `simplicio.mapper-index-state/v1`, fingerprint persistido
  em `.simplicio/index-state.json` que guarda o último HEAD/status para o
  curto-circuito do `index`.
- **Receipt** — registro de execução em `.receipts/`, padrão YOOL_TUPLE_HAMT
  §1.8.4 (com `tuple_id`, `yool_id`, `cost.tokens`, `cost.usd`).

---

## Regras críticas

1. **Schema é contrato.** Mudar shape de `simplicio.project-map/v1`,
   `simplicio.precedent-index/v1`, `simplicio.architecture-inventory/v1`,
   `simplicio.symbol-index/v1`, `simplicio.call-graph/v1`,
   `simplicio.endpoint-inventory/v1` ou `simplicio.screen-inventory/v1`
   exige ADR e bump de schema.
2. **Determinismo.** Mesmo input → mesmo output. Ordenação estável,
   timestamps em UTC, sem inclusão de paths absolutos do host.
3. **Idempotência.** `simplicio-mapper index <path>` deve retornar exit 2
   em <200 ms quando o fingerprint não mudou. Foreground e background não
   podem rodar concorrentes; lock em `.simplicio/index.lock`.
4. **Sem LLM no caminho crítico.** O mapper não chama modelo para gerar
   artefato. Heurísticas e parsers só.
5. **Generalização sobre nomes.** Endpoint path normalization usa só
   placeholders, UUIDs e segments numéricos. Slugs específicos de host
   ficam intactos.
6. **Dependências leves.** `orjson` e `diskcache` são as únicas runtime
   deps obrigatórias do pacote Python. A crate Rust é opt-in e o pacote
   funciona sem ela.
7. **Cross-runtime parity.** A CLI Python (canonical) e a CLI Node em
   `bin/cli.js` devem emitir os mesmos artefatos para a mesma entrada;
   divergência é bug.

---

## Casos de borda

- **Repo sem git** — `_compute_fingerprint` cai no fallback de mtimes.
- **Repo grande (>10k arquivos)** — `--background` evita bloquear o caller;
  o foreground reusa o último JSON estável até o background terminar.
- **Repo com tooling múltiplo** (.NET + Angular + Python) — `.angular`,
  `obj`, `bin/Debug/`, `output/`, `__pycache__`, `.pytest_cache`,
  `.ruff_cache`, `.gradle`, `target` são pulados; `bin/` puro (Node CLI) é
  preservado.
- **Repo com edits unstaged** — `git status --porcelain --untracked-files=all`
  marca como `M`/`??`; mtime fallback usa `mtime_ns` + `size`.
- **Repo overlay (starter dropado sobre host)** — `.specs/`, `.claude/`,
  `.codex/`, `.github/` podem estar gitignored no host sem afetar o
  `project_mode`.

---

## Fronteiras

`simplicio-mapper` **não**:

- Roda LLM nem gera prompt.
- Aplica edits no código do host.
- Publica artefatos remotos (`export-docs` apenas copia local).
- Orquestra agentes (responsabilidade de `simplicio-sprint`).
- Trata billing/pricing (responsabilidade de `simplicio-prompt`).
