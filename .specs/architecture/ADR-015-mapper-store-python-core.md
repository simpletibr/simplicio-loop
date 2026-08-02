# ADR-015: Fundação Python in-process do MapperStore/v1

## Status

Aceito para a issue #474; schemas de domínio e migrations permanecem nas issues
seguintes.

## Decisão

O pacote público `simplicio_mapper.store` concentra somente lifecycle e policy:

- `resolve_store_location` aplica precedence flag → env → home, com escopo repo
  opcional e temp somente quando explicitamente permitido; nunca cria filesystem
  durante resolução/status;
- `StoreProfile` separa read-only, read-write, migration e backup;
- `StoreConnection` abre SQLite com URI `mode=ro` quando aplicável, verifica
  WAL/foreign keys/busy timeout/query-only e expõe somente uma view segura da
  conexão; read-only é side-effect-free por padrão (`immutable=1`), enquanto uma
  leitura viva de WAL opta explicitamente por `immutable=False`;
- `transaction` garante `BEGIN`, commit ou rollback, com validação de fence antes
  de cada chamada SQL pública e sem transações aninhadas ou `executescript`;
- `run_with_retry` repete somente busy/locked até deadline e limite de tentativas;
- `StoreFileLock` usa lock advisory portátil com owner/pid no arquivo de lock;
- `inspect_store` publica `simplicio.mapper-store-status/v1` sem criar arquivo.

Cada domínio continua responsável por seu schema em issues posteriores. O core
não implementa sqlite-vec, daemon, migration automática, dual-write ou deleção
de banco legado.

## Invariantes

1. Resolução e inspeção read-only são side-effect-free.
2. Symlink e path escape são rejeitados antes de abrir o banco.
3. Read-only nunca usa modo de criação e recebe `PRAGMA query_only=ON`.
4. Exceção dentro de transaction sempre faz rollback.
5. Retry é bounded e não captura erros SQLite não relacionados a lock.
6. Writer identity/correlation ID e fence ficam disponíveis antes do primeiro write.

## Alternativas rejeitadas

- um daemon obrigatório: aumenta superfície operacional e quebra Loop standalone;
- uma conexão global/pool implícito: dificulta isolamento por thread/processo;
- configuração espalhada nos consumidores: perpetua divergência de WAL/timeout;
- migration no import: viola side-effect-free e torna startup não determinístico.
