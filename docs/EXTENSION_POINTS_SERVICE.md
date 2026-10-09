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
| ligado | 5 |
| parcial | 27 |
| ausente | 18 |

## Tabela

Evidência: `arquivo:função` (ou `arquivo:linha`), relativo à raiz do repositório. Caminhos curtos como `watcher247/tick.py` são `simplicio_loop/watcher247/tick.py`.

| # | ponto | estado | evidência | observação |
|---|---|---|---|---|
| 1 | `orient` | ligado | `simplicio_loop/turbo.py:_default_index` → `simplicio_loop/cli_impl.py:_ensure_project_map` → `simplicio_loop/map_service_mapper.py:run_mapper_index`; `turbo.py:mapper_reading` | Índice do Mapper e fatia do mapa; o verbo `orient` não é chamado aqui |
| 2 | `pattern_match` | ausente | sem ocorrências de `patterns.jsonl`, `hit_count` ou root cause no caminho | Armazenamento de padrões está em `scripts/loop_journal.py`, fora do caminho |
| 3 | `recall` | ausente | sem ocorrências de `precedent`, `recall` ou `prior` no caminho | Nenhuma consulta a precedentes ou ADRs no watcher nem no turbo |
| 4 | `normalize` | parcial | `simplicio_loop/turbo_cli.py:build_tasks`; `watcher247/tick.py:task_text` | Forma canônica só para tarefas do turbo; campos da issue do GitHub não são normalizados |
| 5 | `deterministic_edit` | ligado | `simplicio_loop/turbo.py:_apply_operations` (chama `simplicio-dev-cli edit`); `packages/dev-cli/simplicio/cli.py` (comando `edit`) | O Dev CLI escreve a mudança; o plano ainda é escrito pelo modelo |
| 6 | `autoscale` | parcial | `watcher247/config.py:concurrency` (`SIMPLICIO_247_CONCURRENCY`, padrão 1); `simplicio_loop/turbo_provider.py:concurrency` (`SIMPLICIO_TURBO_CONCURRENCY`, padrão 8) | Limites fixos por variável de ambiente; sem dimensionamento pelo perfil da máquina |
| 7 | `plan / decide` | parcial | `simplicio_loop/turbo.py:_PLANNER_SYSTEM`, `_one_lane`; chamada via `turbo_provider.complete` | O modelo remoto decide o plano; não há lógica determinística de decisão no caminho |
| 8 | `execute` | parcial | `simplicio_loop/turbo.py:_run_wave` (`asyncio.gather` com semáforo); `apply_lock` em `run_turbo` | Chamadas paralelas à API remota, não fan-out de agentes locais; o watcher processa 1 issue por padrão |
| 9 | `issue_factory` | ligado | `watcher247/tick.py:tick` (descoberta), `process` (claim), `_run_turbo`, `commit_and_pr` | Ciclo completo descoberta → claim → implementação → PR; o watcher não passa `--verify` |
| 10 | `claim` | parcial | `watcher247/tick.py:process` grava `running` em `claims.json` via `state.py:save`; `tick.py:Gate` (lock asyncio por repo) | Estado em arquivo local e lock em processo; sem label no GitHub, lockfile ou claim entre processos |
| 11 | `worktree` | parcial | `watcher247/tick.py:reset_branch` (`git checkout -B loop/issue-N`); `tick.py:Gate` | Clone compartilhado com branch por issue e serializado por repo; sem worktree isolado |
| 12 | `diagnostics` | parcial | `simplicio_loop/turbo.py:repair_with_test_output`; `turbo_cli.py:_run_provider_async` (repair com a saída do teste) | Repair com o rabo bruto do teste, só com `--verify`; não estruturado; o watcher não passa `--verify` |
| 13 | `validate / smoke` | parcial | `turbo_cli.py:_run_verify`; `turbo_cli.py:_apply_plan_async` | `--verify` roda só se for passado; o watcher nunca passa |
| 14 | `pr / evidence` | parcial | `watcher247/tick.py:commit_and_pr` (`gh pr create` real); `tick.py:process` (comentários da issue) | Abertura de PR é real; sem ledger de evidência nem recibo no caminho |
| 15 | `watcher` | ligado | `watcher247/__main__.py:main` (laço de polling com `INTERVAL_S`); `state.py:_save` (claims e baseline persistidos); `packaging/systemd/simplicio-loop-247.service` | Poller persistente; sobrevive a reboot pela unidade systemd, não pelo código |
| 16 | `savings_ledger` | parcial | `simplicio_loop/turbo_provider.py:_post` (uso e custo por chamada); `turbo_cli.py:_run_provider_async` (totais de tokens e `cost_usd`) | Tokens e custo reais por execução; sem ledger, só logs por tentativa |
| 17 | `capability_rank` | ausente | sem ocorrências de `capability_rank` ou `rank_capab` em `watcher247/`, `turbo*.py`, `cli_impl.py` | Modelo fixo; só sobrescrita por variável de ambiente |
| 18 | `compress` | parcial | `simplicio_loop/turbo.py:mapper_reading` (teto de 12000 caracteres); `turbo.py:current_files` (corte de 6000); `turbo.py:_apply_operations` (cauda de 800) | Só limites de tamanho de entrada; não há compressão de texto nem sumarização |
| 19 | `trajectory` | parcial | `watcher247/tick.py:_run_turbo` e `process` (campos de resultado em `claims.json`); logs por tentativa | Resultado guardado por claim; nenhum consumidor de auto-melhoria no caminho |
| 20 | `learn` | ausente | sem ocorrências de `learn` ou `precedent` em `watcher247/` e `turbo*.py` | Existe só como subcomando da CLI (`learn retrospective` em `cli_impl.py`); o watcher e o turbo não o chamam |
| 21 | `human_gate` | ausente | sem ocorrências de `input(`, `--yes`, `approv` ou `confirm` no caminho | `STOP` é interruptor de emergência, não gate de aprovação; o gate humano fica fora do caminho |
| 22 | `shell_exec` | ligado | `watcher247/proc.py:run` (exec de argv, timeout, `killpg`, `Result`); `turbo.py:_run_verify` (`sh -c`, timeout de 900 s, cauda de 1500 caracteres) | Saída estruturada e limitada; `verify` usa `sh -c` |
| 23 | `retry` | parcial | `watcher247/tick.py:process` (`MAX_ATTEMPTS = 2`); `watcher247/config.py` (`RETRY_AFTER` de 6 h); `turbo.py:repair_with_test_output` | Retry fixo de 6 h, sem classificação de falha e sem backoff |
| 24 | `convergence_policy` | ausente | sem ocorrências de `LoopDecision`, `RunProjection` ou `convergence` no caminho | A definição está só em `simplicio_loop/runner.py`; o turbo tem número fixo de tentativas |
| 25 | `status` | parcial | `watcher247/state.py:write_status` (`status.json`); fases em `tick.py:tick` | Snapshot em arquivo por tick; o dashboard não lê `status.json` |
| 26 | `security` | ausente | sem ocorrências de `gitleaks`, `secret` ou `scan` no caminho; `tick.py:commit_and_pr` faz `git add -A` sem varredura | Só há armazenamento de credencial com permissão 600 (`subscription.py:_store_tokens_sync`) |
| 27 | `intake` | parcial | `watcher247/github.py:repos` e `open_issues` (`gh issue list`, limite 50); `github.py:skipped` (labels) | Ingere issues abertas de repos `simplicio*`; sem board nem sprint |
| 28 | `dependency_graph` | parcial | `turbo.py:build_tasks` (`depends_on` por arquivo compartilhado); `turbo.py:_ready` e `_run_wave` (detecta ciclo) | Grafo só dentro de uma execução do turbo, em memória, sem retomada; o watcher não ordena issues |
| 29 | `durable_workflow` | parcial | `watcher247/tick.py:process` grava `claims.json` no início e no fim | Sem diário de fases; claim preso em `running` após crash nunca é retomado (`state.py:due`) |
| 30 | `work_queue` | parcial | `watcher247/tick.py:Gate`; `state.py:due` (`next_try_at`); `config.py:concurrency`; `turbo.py:run_turbo` (semáforo e `apply_lock`) | Fila é `claims.json`; locks só em processo, sem lockfile, TTL nem prioridade |
| 31 | `resource_governor` | parcial | `watcher247/config.py:concurrency`; `turbo_provider.py:concurrency`; semáforo em `turbo.py:run_turbo` | Limites fixos por variável de ambiente; sem sonda de CPU ou RAM |
| 32 | `delivery_gate` | parcial | `packages/dev-cli/simplicio/commands/edit.py` (`_verification_payload`, testes escopados após o apply); `turbo_cli.py:_apply_plan_async` | Testes escopados rodam no `edit`; o watcher não passa `--verify`; sem AC nem certificado |
| 33 | `action_gate` | ausente | sem ocorrências de `risk`, `blocklist`, `irreversible` ou `classify` no caminho | Só recusa de `write_allowed` em `packages/dev-cli/simplicio/commands/edit.py`; a autoridade de irreversibilidade fica no pipeline (`plan_compiler/authority.py`) |
| 34 | `repo_conventions` | ausente | sem ocorrências de `CONTRIBUTING`, `AGENTS.md` ou `PULL_REQUEST_TEMPLATE` no caminho | O watcher fixa formato de commit e PR (`tick.py:commit_and_pr`) e não lê regras do repo |
| 35 | `pr_template` | ausente | sem ocorrências de `pull_request_template` no caminho | Corpo de PR fixo em `watcher247/tick.py:commit_and_pr` |
| 36 | `reuse_precedent` | ausente | sem ocorrências de `SOLVED` ou `precedent` no caminho | Ranking de precedentes está em `packages/mapper/simplicio_mapper/prototype_context.py`, fora do caminho |
| 37 | `sibling_search` | ausente | só `cli_impl.py:_orient_sibling_test_paths` (testes irmãos) | Acha arquivos de teste irmãos; sem busca de call-site nem de padrão |
| 38 | `source_adapter` | parcial | `watcher247/github.py` (`repos`, `open_issues`, `comment`); `state.py:due` | Funções só do GitHub; sem contrato de conector comum |
| 39 | `prompt_budget` | parcial | `turbo.py` (`_MAPPER_READING_LIMIT = 12000`, `FILE_CHARS = 6000`, cabeçalho idêntico); `watcher247/config.py` (`BODY_CAP = 6000`) | Limites de caracteres, não de tokens; cache é do provedor |
| 40 | `model_route` | parcial | `simplicio_loop/turbo_provider.py` (`DEFAULT_MODEL`, `SIMPLICIO_TURBO_MODEL`); `turbo.py:_one_lane` usa um modelo para todas as chamadas | Um modelo fixo, trocável por ambiente; sem roteamento por subtarefa |
| 41 | `model_preflight` | parcial | `turbo_provider.py:require_key` (falha rápida sem `OPENROUTER_API_KEY`) | Só checa a chave; sem sonda de modelo |
| 42 | `toolchain_detect` | parcial | `packages/mapper/simplicio_mapper/processor.py:_validation_commands` (detecção pytest, npm, cargo); `turbo_cli.py:_run_verify` usa o `--verify` informado | A detecção existe no Mapper; no turbo o comando de verificação não é detectado, só recebido |
| 43 | `checkpoint_restore` | parcial | `packages/dev-cli/simplicio/mechanical_edit.py:_backup_existing` e restauração nas linhas 491 e 508 | Rollback só por lote de edição; sem snapshot git antes do lote |
| 44 | `notify` | parcial | `watcher247/github.py:comment`; `tick.py:process` | Saída só por comentário na issue; sem aprovação de entrada |
| 45 | `endpoint_compare` | ausente | sem ocorrências de `endpoint` ou `compare` no caminho | Só rótulo `endpoints-routes` em `packages/mapper/.../language_capabilities.py` |
| 46 | `web_verify` | ausente | sem ocorrências de `playwright`, `screenshot` ou `browser` no caminho | Existe em `scripts/web_verify.py`, fora do caminho |
| 47 | `video_evidence` | ausente | sem ocorrências de `video`, `ffmpeg` ou `hyperframes` no caminho | Existe em `scripts/video_evidence.py`, fora do caminho |
| 48 | `web_research` | ausente | sem busca web no caminho; só a chamada ao modelo em `turbo_provider.py` | Nenhuma pesquisa na web |
| 49 | `transform_guard` | ausente | sem ocorrências de `transform` ou `preserv` com verificação no caminho | Nenhuma checagem de preservação de tokens, URLs ou paths |
| 50 | `judge` | ausente | sem ocorrências de `judge`, `verdict`, `ACCEPT` ou `REJECT` no caminho; `ACCEPT`/`REJECT` só em `packages/dev-cli/simplicio/commands/prototype.py` | O turbo chama só `edit` do Dev CLI; `prototype` não é invocado |

## Como os testes de fluxo se relacionam com esta tabela

- `tests/flow/test_service_flow_e2e.py` e `tests/flow/test_skill_flow_e2e.py` exercitam o caminho ponta a ponta com um tick real do watcher e um modo host real.
- Os asserts que dependem de integrações ainda não feitas (lease, `--verify` no watcher, comentário de status canônico, `events.jsonl`, relatório de execução) são xfail estritos apontando para #1469.
