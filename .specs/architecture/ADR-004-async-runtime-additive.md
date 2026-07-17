# ADR-004: Adotar uma camada de concorrência estruturada aditiva (`runtime_async`) em vez de reescrever o pipeline síncrono

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

Issue #212 pede para migrar o pipeline Python (`simplicio/pipeline.py`) para concorrência
estruturada (AnyIO/asyncio), compartilhar `httpx.AsyncClient` e habilitar `uvloop` opcional,
preservando todos os comandos e contratos atuais.

`run_task`/`_apply_and_test_attempt` são funções síncronas com estado vivo em globals de módulo
(`_LAST_VERIFY_RECEIPT`, `_LAST_PATCH_RECEIPT`), fortemente acopladas a `subprocess.run` (git apply,
test command) e a uma máquina de retry/fixer sequencial de 5 tentativas. Reescrever esse núcleo como
`async def` nativo tocaria toda ramificação de retry/fixer/transaction sem ganho real de
corretude — o trabalho bloqueante (subprocess, IO em disco) ainda precisa acontecer em algum
lugar, e o próprio texto da issue já pede o padrão aditivo ("Criar `run_async()`; manter
`run()`/CLI como ponte segura, detectando loop já ativo" — passo 8).

## Decisão

Adicionar uma camada de concorrência estruturada **aditiva** e não invasiva:

- `simplicio/runtime_async.py`: `RuntimeContext` (semáforo de concorrência limitada +
  cliente HTTP assíncrono compartilhado), `gather_bounded()` (fan-out de N thunks
  independentes com `asyncio.gather(return_exceptions=True)`, isolando falha de uma tarefa das
  demais), `run_sync_in_thread()` (ponte para `asyncio.get_running_loop().run_in_executor`,
  encapsulando chamadas bloqueantes em worker threads limitadas) e `install_uvloop()` (opt-in,
  no-op seguro no Windows ou quando o extra não está instalado).
- `simplicio/utils/http_client.py` ganha `aclient()`/`aclose()`/`apost_json()` — a contraparte
  assíncrona do cliente síncrono já existente (`client()`/`post_json()`), reaproveitando a mesma
  `_config()` (timeout/limits/pooling).
- `simplicio/pipeline.py` ganha `run_tasks_async(task_specs, *, concurrency=None)`: despacha N
  chamadas **independentes** de `run_task` (inalterado) para threads limitadas, bounded por
  semáforo. `pipeline.run()`/`pipeline.run_task()` continuam exatamente como antes — nenhuma
  chamada de CLI muda de comportamento.
- Novo extra opcional `simplicio-cli[performance]` (`uvloop>=0.21.0; sys_platform != 'win32'`),
  nunca uma dependência obrigatória.

Escopo: apenas o caminho de execução **concorrente de tarefas independentes** (ex.: um host loop
que quer rodar N tarefas de um backlog em paralelo). Não inclui: reescrita de
`_apply_and_test_attempt`/retry loop como async nativo, circuit breaker/jitter por provider, nem
integração de scheduler com o Simplicio Loop Hub — ficam como trabalho futuro, registrados na
issue #212 como próximos passos.

Quem mantém: mesmo dono de `pipeline.py`/`providers.py`.

---

## Consequências

### Positivas (+)

- Nenhuma regressão possível no caminho síncrono existente: `run()`/`run_task()` não foram
  tocados, só ganharam um vizinho aditivo.
- Ganho de concorrência real e medido: 2.2x de speedup em 8 tarefas independentes com
  concorrência 4 (`bench/results_async_pipeline_bench.json`), sem reescrever a lógica de
  retry/fixer.
- `httpx.AsyncClient` compartilhado segue o mesmo padrão de pooling já validado pelo cliente
  síncrono (`utils/http_client.py`), sem duplicar configuração.
- `uvloop` continua 100% opcional — Windows (onde não há wheel) cai automaticamente para o loop
  padrão do asyncio.

### Negativas (-)

- Não entrega o pipeline "nativamente assíncrono" ponta a ponta que o texto original da issue
  descreve (DAG de dependências, semáforos por provider, circuit breaker) — é um subconjunto
  real e testável, não o escopo completo.
- `run_tasks_async` ainda serializa cada tarefa individual através de um worker thread (não é
  IO assíncrono nativo por tarefa) — o ganho vem de rodar tarefas *independentes* em paralelo,
  não de tornar uma única tarefa mais rápida.

### Neutras / observações

- `run_sync_in_thread` usa o executor padrão do event loop (`run_in_executor(None, ...)`), cujo
  tamanho de pool já é limitado pelo asyncio; o semáforo de `RuntimeContext` adiciona um teto
  explícito e configurável (`SIMPLICIO_ASYNC_CONCURRENCY`) por cima disso.

---

## Alternativas consideradas

### Alternativa A — Reescrever `run_task`/`_apply_and_test_attempt` como `async def` nativo

- Resumo: converter toda a cadeia de geração/apply/test/fixer/impact-test para corrotinas
  nativas, com semáforos por provider e circuit breaker embutidos no pipeline.
- Por que foi descartada: alto risco de regressão no caminho crítico usado por todo comando de
  CLI, para nenhum ganho de corretude — o gargalo real (subprocess, git apply, test runner) segue
  bloqueante de qualquer forma. O próprio plano da issue já pede o padrão de ponte segura
  (`run_async()` aditivo).

### Alternativa B — Não fazer nada (manter só o pipeline síncrono)

- Resumo: fechar a issue como "não aplicável" sem nenhuma mudança.
- Por que foi descartada: existe um caso de uso real e imediato (um host loop rodando N tarefas
  independentes de um backlog) que se beneficia genuinamente de concorrência limitada, e a
  infraestrutura de cliente HTTP compartilhado (`utils/http_client.py`) já existia parcialmente
  no repo sem nunca ter sido conectada a um caminho assíncrono.

---

## Critério de revisão

- Se o pipeline ganhar um segundo transporte de provider genuinamente assíncrono (ex.: streaming
  HTTP nativo em vez de shell-out para CLIs), revisitar se `run_task` interno deveria migrar para
  `async def` de fato.
- Se `SIMPLICIO_ASYNC_CONCURRENCY` em produção mostrar que o teto do executor padrão do asyncio
  (não o semáforo) é o gargalo real, revisitar o tamanho do executor customizado.

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-dev-cli/issues/212
- Implementação: `simplicio/runtime_async.py`, `simplicio/pipeline.py::run_tasks_async`,
  `simplicio/utils/http_client.py`
- Benchmark: `bench/run_async_pipeline_bench.py`, `bench/results_async_pipeline_bench.json`
- Testes: `tests/python/test_runtime_async.py`, `tests/python/test_pipeline_run_tasks_async.py`
- Documentos relacionados: `[DESIGN](./DESIGN.md)`, `[PATTERNS](./PATTERNS.md)`
