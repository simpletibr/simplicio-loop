# Os 50 pontos de extensão no caminho do serviço

Caminho do serviço = o watcher 24h (`simplicio_loop/watcher247/`), o motor turbo que ele chama
(`simplicio_loop/turbo.py`, `turbo_cli.py`, `turbo_provider.py`), a fiação de CLI em `simplicio_loop/cli_impl.py`
e o Mapper e o Dev CLI que eles invocam (`packages/mapper`, `packages/dev-cli`).
O runner (`simplicio_loop/runner.py`) e a skill `/simplicio-loop` não entram aqui, salvo quando o caminho do serviço os chama.

Lista de nomes e definições: `simplicio-loop.project.json` → `extension_points_50.points`.
Um teste (`tests/flow/test_extension_points_doc.py`) garante que esta tabela lista exatamente esses 50 nomes, na mesma ordem.

## Estados

- **ligado**: o caminho do serviço executa a capacidade hoje.
- **parcial**: só em parte, só por opção de ambiente ou fallback, ou só fora do caminho do serviço.
- **ausente**: nenhuma implementação no caminho do serviço (a busca foi feita nos arquivos do caminho; quando existe em outro lugar, a observação diz onde).

## Resumo

| estado | quantidade |
|---|---|
| ligado | 11 |
| parcial | 24 |
| ausente | 15 |

## Tabela

Evidência: `arquivo:função` (ou `arquivo:linha`), relativo à raiz do repositório. Caminhos curtos como `watcher247/tick.py` são `simplicio_loop/watcher247/tick.py`.

| # | ponto | estado | evidência | observação |
|---|---|---|---|---|
| 1 | `orient` | ligado | `simplicio_loop/turbo.py:_default_index` → `simplicio_loop/cli_impl.py:_ensure_project_map` → `simplicio_loop/map_service_mapper.py:run_mapper_index`; `turbo.py:mapper_reading` | Índice do Mapper e fatia do mapa; o verbo `orient` não é chamado aqui |
| 2 | `pattern_match` | ausente | sem ocorrências de `patterns.jsonl`, `hit_count` ou root cause no caminho | Armazenamento de padrões está em `scripts/loop_journal.py`, fora do caminho |
| 3 | `recall` | ausente | sem ocorrências de `precedent`, `recall` ou `prior` no caminho | Nenhuma consulta a precedentes ou ADRs no watcher nem no turbo |
| 4 | `normalize` | parcial | `simplicio_loop/turbo_cli.py:build_tasks`; `watcher247/tick.py:task_text`; `simplicio_loop/intake_gate.py:_normalize_text` (usado por `triage`) | Forma canônica das tarefas do turbo e normalização de acentos na triagem; os demais campos da issue não são normalizados |
| 5 | `deterministic_edit` | ligado | `simplicio_loop/turbo.py:_apply_operations` (chama `simplicio-dev-cli edit`); `packages/dev-cli/simplicio/cli.py` (comando `edit`) | O Dev CLI escreve a mudança; o plano ainda é escrito pelo modelo |
| 6 | `autoscale` | parcial | `watcher247/config.py:concurrency` (`SIMPLICIO_247_CONCURRENCY`, padrão 1); `simplicio_loop/turbo_provider.py:concurrency` (`SIMPLICIO_TURBO_CONCURRENCY`, padrão 8) | Limites fixos por variável de ambiente; sem dimensionamento pelo perfil da máquina |
| 7 | `plan / decide` | parcial | `simplicio_loop/turbo.py:_PLANNER_SYSTEM`, `_one_lane`; chamada via `turbo_provider.complete` | O modelo remoto decide o plano; não há lógica determinística de decisão no caminho |
| 8 | `execute` | parcial | `simplicio_loop/turbo.py:_run_wave` (`asyncio.gather` com semáforo); `apply_lock` em `run_turbo` | Chamadas paralelas à API remota, não fan-out de agentes locais; o watcher processa 1 issue por padrão |
| 9 | `issue_factory` | ligado | `watcher247/tick.py:tick` (descoberta), `process` (claim), `_run_turbo`, `commit_and_pr`; `tests/flow/test_service_flow_e2e.py` (um tick completo) | Ciclo completo descoberta → claim → implementação → verify → PR, exercitado de ponta a ponta |
| 10 | `claim` | ligado | `watcher247/tick.py:process` (`ClaimStore.acquire` com `owner_token`, TTL e `heartbeat`; `release` ao fim); `simplicio_loop/claim_lease.py:ClaimStore._flock_acquire` (flock entre processos); `simplicio_loop/watcher_github.py:claim_on_github` (claim visível na issue) | Lease com TTL e heartbeat, travado por flock, mais claim verificado no GitHub; `tests/flow/test_service_flow_e2e.py::test_lease_acquired_and_released` |
| 11 | `worktree` | parcial | `watcher247/tick.py:reset_branch` (`git checkout -B loop/issue-N`); `tick.py:Gate` | Clone compartilhado com branch por issue e serializado por repo; sem worktree isolado |
| 12 | `diagnostics` | parcial | `simplicio_loop/turbo.py:repair_with_test_output`; `turbo_cli.py:_run_provider_async` (repair com a saída do teste) | Repair com o rabo bruto do teste, só quando há comando de teste (o watcher o detecta); não estruturado |
| 13 | `validate / smoke` | ligado | `watcher247/verify.py:turbo_argv` e `decide` (PR só se o teste passou, falha fechada); `simplicio_loop/turbo_cli.py:_run_verify`; `tests/flow/test_service_flow_e2e.py::test_verify_ran` | O watcher detecta o comando de teste do repo, passa `--verify` e rotula o PR (`MEASURED\|verify_passed` ou `UNVERIFIED\|no_test_command`) |
| 14 | `pr / evidence` | parcial | `watcher247/tick.py:commit_and_pr` (`gh pr create` com `Closes #N` e rótulo de verify); `simplicio_loop/turbo_run.py:TurboRun.persist_receipts` (recibos do Dev CLI com sha256) | PR e recibos por execução existem; o corpo do PR não aponta para os recibos nem há ledger de evidência |
| 15 | `watcher` | ligado | `watcher247/__main__.py:main` (laço de polling com `INTERVAL_S`); `state.py:_save` (claims e baseline persistidos); `packaging/systemd/simplicio-loop-247.service` | Poller persistente; sobrevive a reboot pela unidade systemd, não pelo código |
| 16 | `savings_ledger` | parcial | `simplicio_loop/turbo_provider.py:_post` (uso e custo por chamada); `simplicio_loop/turbo_run.py:usage_totals` e `TurboRun.finish` (tokens no `simplicio.execution-report/v1`) | Tokens medidos por execução no relatório (nulos quando o provedor não informa); sem ledger de economia |
| 17 | `capability_rank` | ausente | sem ocorrências de `capability_rank` ou `rank_capab` em `watcher247/`, `turbo*.py`, `cli_impl.py` | Modelo fixo; só sobrescrita por variável de ambiente |
| 18 | `compress` | parcial | `simplicio_loop/turbo.py:mapper_reading` (teto de 12000 caracteres); `turbo.py:current_files` (corte de 6000); `turbo.py:_apply_operations` (cauda de 800) | Só limites de tamanho de entrada; não há compressão de texto nem sumarização |
| 19 | `trajectory` | parcial | `simplicio_loop/turbo_run.py:TurboRun.enter` (`events.jsonl` por etapa); `watcher247/tick.py:process` (resultado em `claims.json`); logs por tentativa | Trajetória gravada por execução e legível pelo dashboard; nenhum consumidor de auto-melhoria no caminho |
| 20 | `learn` | ausente | sem ocorrências de `learn` ou `precedent` em `watcher247/` e `turbo*.py` | Existe só como subcomando da CLI (`learn retrospective` em `cli_impl.py`); o watcher e o turbo não o chamam |
| 21 | `human_gate` | parcial | `simplicio_loop/intake_gate.py:triage` e `watcher247/tick.py:process` (issue vaga ou épica vira `BLOCKED` com pergunta de esclarecimento) | Pede esclarecimento antes de agir; não há aprovação humana antes do PR nem do merge, e `STOP` é só interruptor de emergência |
| 22 | `shell_exec` | ligado | `watcher247/proc.py:run` (exec de argv, timeout, `killpg`, `Result`); `turbo_cli.py:_run_verify` (`sh -c`, timeout de 900 s, cauda de 1500 caracteres) | Saída estruturada e limitada; `verify` usa `sh -c` |
| 23 | `retry` | parcial | `watcher247/verify.py:retry_or_dead`; `watcher247/tick.py:process` (`MAX_ATTEMPTS = 2`); `watcher247/config.py` (`RETRY_AFTER` de 6 h); `turbo.py:repair_with_test_output` | Retry fixo de 6 h e fila morta após 2 tentativas; sem classificação de falha e sem backoff |
| 24 | `convergence_policy` | ausente | sem ocorrências de `LoopDecision`, `RunProjection` ou `convergence` no caminho | A definição está só em `simplicio_loop/runner.py`; o turbo tem número fixo de tentativas |
| 25 | `status` | ligado | `watcher247/tick.py:_phase` (um comentário de status canônico por issue, via `simplicio_loop/watcher_github.py:post_status`); `watcher247/state.py:write_status`; `simplicio_loop/turbo_run.py` (`state.json` lido por `dashboard/runs.py`); `tests/flow/test_service_flow_e2e.py::test_one_canonical_status_comment_updated_across_phases` | Comentário editado CLAIMED → PLANNED → IN_PROGRESS → VERIFYING → PR_OPEN e execução visível no kanban |
| 26 | `security` | ligado | `watcher247/secret_scan.py:check_staged` (varredura do diff antes do commit e do push, #1501); `watcher247/prompt_guard.py:untrusted` (texto da issue cercado no prompt); `watcher247/sandbox.py:wrap` e `scrubbed_env`; `subscription.py:_store_tokens_sync` (permissão 600) | Segredo no diff bloqueia o push; texto não confiável é isolado no prompt; subprocesso em bwrap com env por allowlist |
| 27 | `intake` | ligado | `simplicio_loop/intake_gate.py:repo_opted_in` (`.simplicio/loop.toml` com `enabled = true`), `issue_admitted`, `triage`; `watcher247/github.py:open_issues`; `tests/flow/test_service_flow_e2e.py::test_issue_admitted` | Só repos com opt-in; a issue passa por admissão (autor e label) e triagem antes do claim; sem board nem sprint |
| 28 | `dependency_graph` | parcial | `turbo_cli.py:build_tasks` (`depends_on` por arquivo compartilhado); `turbo.py:_ready` e `_run_wave` (detecta ciclo) | Grafo só dentro de uma execução do turbo, em memória, sem retomada; o watcher não ordena issues |
| 29 | `durable_workflow` | parcial | `watcher247/tick.py:tick` (`ClaimStore.reap_expired` solta lease vencido após crash); `process` (`claims.json` no início e no fim); `simplicio_loop/turbo_run.py` (`state.json` e `events.jsonl` por execução) | Lease vencido volta para a fila; sem diário de fases que retome a execução do ponto onde parou |
| 30 | `work_queue` | parcial | `simplicio_loop/claim_lease.py:ClaimStore` (lease com TTL, `next_try_at`); `watcher247/tick.py:Gate`; `config.py:concurrency`; `turbo.py:run_turbo` (semáforo e `apply_lock`) | Fila é `claims.json` com lease e flock; sem prioridade nem ordenação entre issues |
| 31 | `resource_governor` | parcial | `watcher247/budget.py:reached` e `issues_left` (teto diário de issues, PRs e chamadas de modelo); `watcher247/config.py:concurrency`; `turbo_provider.py:concurrency`; semáforo em `turbo.py:run_turbo` | Tetos diários e limites de concorrência por variável de ambiente; sem sonda de CPU ou RAM |
| 32 | `delivery_gate` | parcial | `watcher247/verify.py:decide` (sem teste verde não há PR; sem relatório de verify a decisão é retry); `packages/dev-cli/simplicio/commands/edit.py` (`_verification_payload`) | O gate é o teste do repo; sem verificação de critérios de aceite nem certificado de entrega |
| 33 | `action_gate` | parcial | `watcher247/sandbox.py:wrap` e `refusal` (sem sandbox o tick não roda subprocesso); `watcher247/budget.py:reached`; recusa de `write_allowed` em `packages/dev-cli/simplicio/commands/edit.py` | Limita onde o turbo escreve e quantas ações por dia; não classifica o risco da ação (`plan_compiler/authority.py` está fora do caminho) |
| 34 | `repo_conventions` | ausente | sem ocorrências de `CONTRIBUTING`, `AGENTS.md` ou `PULL_REQUEST_TEMPLATE` no caminho | O watcher fixa formato de commit e PR (`tick.py:commit_and_pr`) e não lê regras do repo |
| 35 | `pr_template` | ausente | sem ocorrências de `pull_request_template` no caminho | Corpo de PR fixo em `watcher247/tick.py:commit_and_pr` |
| 36 | `reuse_precedent` | ausente | sem ocorrências de `SOLVED` ou `precedent` no caminho | Ranking de precedentes está em `packages/mapper/simplicio_mapper/prototype_context.py`, fora do caminho |
| 37 | `sibling_search` | ausente | só `cli_impl.py:_orient_sibling_test_paths` (testes irmãos) | Acha arquivos de teste irmãos; sem busca de call-site nem de padrão |
| 38 | `source_adapter` | parcial | `watcher247/github.py` (`repos`, `open_issues`); `simplicio_loop/watcher_github.py` (`post_status`, `claim_on_github`, `patrol_open_prs`) | Funções só do GitHub; o `source_adapter` do runner não é usado e não há contrato de conector comum |
| 39 | `prompt_budget` | parcial | `turbo.py` (`_MAPPER_READING_LIMIT = 12000`, `FILE_CHARS = 6000`, cabeçalho idêntico); `watcher247/config.py` (`BODY_CAP = 6000`) | Limites de caracteres, não de tokens; `PLAN_PROMPT_VERSION` (`turbo-plan/v1`) versiona o prompt do plano; cache é do provedor |
| 40 | `model_route` | parcial | `simplicio_loop/turbo_provider.py` (`DEFAULT_MODEL`, `SIMPLICIO_TURBO_MODEL`); `turbo.py:_one_lane` usa um modelo para todas as chamadas | Um modelo fixo, trocável por ambiente; `simplicio_loop/executor_select.py` (#1495) escolhe executor por papel, mas nem o watcher nem o turbo o chamam |
| 41 | `model_preflight` | parcial | `turbo_provider.py:require_key` (falha rápida sem `OPENROUTER_API_KEY`) | Só checa a chave; sem sonda de modelo |
| 42 | `toolchain_detect` | ligado | `watcher247/verify.py:detect_test_command` (pytest, npm, cargo, make); `watcher247/tick.py:_run_turbo` | O watcher detecta o comando de teste do repo alvo e o passa ao turbo; o turbo isolado só recebe `--verify` |
| 43 | `checkpoint_restore` | parcial | `packages/dev-cli/simplicio/mechanical_edit.py:_backup_existing` e restauração nas linhas 491 e 508 | Rollback só por lote de edição; sem snapshot git antes do lote |
| 44 | `notify` | parcial | `watcher247/tick.py:_phase` (comentário de status canônico editado a cada fase) | Saída só por comentário na issue; sem push, e-mail nem aprovação de entrada |
| 45 | `endpoint_compare` | ausente | sem ocorrências de `endpoint` ou `compare` no caminho | Só rótulo `endpoints-routes` em `packages/mapper/.../language_capabilities.py` |
| 46 | `web_verify` | ausente | sem ocorrências de `playwright`, `screenshot` ou `browser` no caminho | Existe em `scripts/web_verify.py`, fora do caminho |
| 47 | `video_evidence` | ausente | sem ocorrências de `video`, `ffmpeg` ou `hyperframes` no caminho | Existe em `scripts/video_evidence.py`, fora do caminho |
| 48 | `web_research` | ausente | sem busca web no caminho; só a chamada ao modelo em `turbo_provider.py` | Nenhuma pesquisa na web |
| 49 | `transform_guard` | ausente | sem ocorrências de `transform` ou `preserv` com verificação no caminho | Nenhuma checagem de preservação de tokens, URLs ou paths |
| 50 | `judge` | ausente | sem ocorrências de `judge`, `ACCEPT` ou `REJECT` no caminho; `ACCEPT`/`REJECT` só em `packages/dev-cli/simplicio/commands/prototype.py`; `turbo.py:_verdict` decide a recusa do apply e não julga qualidade | O turbo chama só `edit` do Dev CLI; `prototype` não é invocado |

## Como adicionar um ponto

Um ponto é um módulo novo em `simplicio_loop/watcher247/points/<nome>.py`; ninguém edita `tick.py` (#1509). O pacote importa todos os módulos e cada um se registra ao ser importado. O contrato está em `points/registry.py`.

```python
from .registry import PointContext, PointResult, register

async def run(ctx: PointContext) -> PointResult:
    return PointResult("meu_ponto", "ok", {"chave": "valor"})

register("meu_ponto", "verify", run)                      # etapa: intake, plan, apply, verify, pr ou done
# register(..., applies=lambda ctx: ctx.role == "ui")    # condicional: sem o gatilho vira `skipped`
# register(..., blocking=True)                           # erro ou `blocked` (PointBlocked) ou `deferred` (PointDeferred) interrompe a etapa
```

- `fn` é `async (ctx) -> PointResult`. `status` é `ok`, `skipped`, `error`, `blocked` ou `deferred`; `evidence` é um dict serializável em JSON; `reason_code` nomeia o motivo quando não é `ok`.
- `ctx` é um `PointContext` imutável (`repo`, `issue`, `clone`, `state_dir`, `run_dir`, `task_text`, `plan`, `turbo_json`, `verify`, `pr_url`, `role`, `family`). O que a etapa ainda não sabe vem `None`: `plan` é `None` em `intake` e `plan`, `pr_url` só existe em `done`.
- O `tick.py` chama `points.run(etapa, ctx)` uma vez por etapa: `intake` (clone pronto, issue admitida), `plan` (antes do planner), `apply` (depois do apply do turbo), `verify` (depois do verify), `pr` (antes do commit e do PR) e `done` (ao fim, com `pr_url`). Os pontos de uma etapa rodam na ordem de registro.
- Uma exceção do ponto vira `PointResult(status="error", reason_code="point_exception")` e o tick segue. Um resultado `blocked` na etapa `pr` impede o PR. `blocking=True` não vale para `done`.
- **`blocked` x `deferred`** (só interrompem a etapa em ponto `blocking=True`; `raise_if_blocked` os trata na etapa `pr`):
  - `blocked` (ex.: `judge` REJECT, `convergence_policy` parou) é uma **tentativa falha**, igual a uma falha de verify: o tick tenta de novo com os motivos (`reason_code` e `evidence` entram no contexto da próxima tentativa e no comentário de status), a tentativa conta no escalonamento de papéis, e a issue só vira `dead` ao atingir o limite de tentativas. É a exceção `PointBlocked`; um erro ou exceção de ponto `blocking` segue o mesmo caminho.
  - `deferred` (ex.: pouco disco ou carga alta no `resource_governor`) é uma condição **transitória**: o tick pula a issue nesta rodada **sem consumir tentativa**, escreve só a linha `deferred: <motivo>` no comentário de status e solta claim e lease; a issue volta a ser elegível no próximo tick. É a exceção `PointDeferred` (subclasse de `PointBlocked`, por isso capture `PointDeferred` primeiro). Nunca leva a `dead`, por mais que se repita.
- Cada resultado vai para o `events.jsonl` (`watcher.point`, em `.simplicio-loop/orchestrator/points/<repo>-<issue>/`) e para o relatório de execução do watcher (`<estado>/.simplicio-loop/runtime/execution-reports/`), uma tarefa por ponto.
- Teste: `tests/watcher247/points/test_<nome>.py`, usando a fixture `point_contract` de `tests/watcher247/points/conftest.py` (confere registro único, etapa válida, resultado tipado, evidência serializável) e `make_ctx`. Exemplo: `points/toolchain_detect.py` (etapa `intake`, envolve `verify.detect_test_command`).
- Depois de ligar o ponto, atualize a linha dele na tabela acima e a contagem do resumo.

## Como os testes de fluxo se relacionam com esta tabela

- `tests/flow/test_service_flow_e2e.py` e `tests/flow/test_skill_flow_e2e.py` exercitam o caminho ponta a ponta com um tick real do watcher e um modo host real. Só `gh` e o modelo são falsos; o Mapper, o Dev CLI e o turbo são os do checkout.
- No caminho do serviço passam hoje: admissão, lease, mapa do Mapper, plano aplicado, verify, commit com `Closes #N` e `gh pr create`, um único comentário de status editado a cada fase, `events.jsonl` legível pelo dashboard e relatório de execução.
- Falta, e é um xfail estrito apontando para #1469: as etapas `intake` e `pr` do watcher dentro do `events.jsonl` da execução (hoje só as etapas do turbo são gravadas).
- `tests/flow/test_extension_points_doc.py` confere os 50 nomes, os estados e a contagem do resumo.
