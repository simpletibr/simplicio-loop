# PROGRESS

- 2026-07-07: contexto obrigatório lido. `.starter-meta.json` ausente => modo `root`.
- Segurança/robustez implementadas: `mechanical_edit`, `dod`, auto-upgrade opt-in no `ecosystem`, guards de CLI/shared/bench/skill_router, writes atômicas e validação de comandos cross-platform para os testes/contracts existentes.
- Follow-up aplicado: a superfície MCP foi removida do dev-cli (`serve --mcp`, `mcp_server.py`, testes/fixtures/docs correlatos).
- Release prep concluído: `simplicio-mapper` mínimo atualizado para `>=0.18.0`, artefatos versionados de bench re-hashados, e API pública `simplicio.mapper_api` adicionada para expor o pacote `simplicio-mapper` instalado.
- Validações finais verdes: `ruff check .`, `ruff format --check .`, `mypy simplicio`, `pytest -q`, `python scripts/gen_package_interdependence.py --check`, `python -m build`, `python -m twine check dist/*`.
- 2026-07-11: iniciada drenagem das issues abertas. Slice P0 #129 implementado: extração de artifact de arquivo completo, reconstrução determinística de diff quando não há unified diff, fallback após patch stale/corrupt, persistência de parser strategy e metadados de modelo no JSON. Teste focado verde; suite completa ainda revela falhas preexistentes fora do slice.
- 2026-07-11: worker #117 implementou descoberta conservadora de `execution_plan` em `intake --plan-only --json` sem `--target/--stack` quando o mapper já fornece artefatos + queries suficientes; falha fechada com blockers acionáveis para artefatos ausentes, ambiguidade e falta de `tests-for`. Evidência focada verde: `python -m pytest tests/python/test_task_spec.py tests/python/test_cli_help_snapshot.py -q` e `python -m ruff check simplicio/cli.py simplicio/commands/intake.py simplicio/plan_discovery.py tests/python/test_task_spec.py`.
- 2026-07-11: slice evidence/release worker #120/#121 concluído sem provider live: `EvidenceLedger.matrix()` agora revalida receipts medidos e rebaixa claims para `UNVERIFIED` quando artifact some ou muda hash; docs atualizadas e testes focados cobrindo watcher mismatch/screenshot errada/artifact ausente.
- 2026-07-11: worker #119 concluído no recorte intake/DAG/resume/status. `simplicio.orchestrator.multi_task` agora gera preview determinístico de lote a partir de `TaskSpec` multi-card, resolve dependências explícitas/por label único, e bloqueia ambiguidades/desconhecidos; `simplicio-py intake --plan-only/--contract` passa a emitir `task_batch`; `simplicio-py status --json` passa a reportar `.simplicio/task_batch.json` quando presente. Validação focada: `ruff check` nos arquivos alterados, `pytest -q tests/python/test_multi_task.py tests/python/test_run_cli.py -k "task_batch or multi_task or status_json_reports_task_batch"` verde; `tests/python/test_task_spec.py` segue bloqueado por import drift pré-existente em `simplicio.pipeline_stages`.
- 2026-07-11: worker #89 auditou o estado real de memory/HRM. Implementado o menor slice determinístico sem deps externas: `simplicio-py memory validate` (auditoria estrutural markdown+git) e `simplicio-py memory handoff` (pacote cross-vendor derivado de recall + validação) sobre `memory_store`/CLI existentes, sem tocar pipeline/prompt/transaction/multi_task. Integração real com `ai-memory`/HRM Rust continua blocker explícito fora deste recorte.
- 2026-07-12: issue #166 (P0 Plan Compiler) caracterizada via 3 agentes de pesquisa em paralelo (mapper/runtime subprocess+cache, epic schemas, control-plane overlap). Achado bloqueante: `GoalEnvelope`/`ContextSnapshot`/`PlanDAG`/`EffectPlan`/`VerificationPlan` não existem como pacote Python importável em lugar nenhum (`simplicio-runtime` só existe como binário Rust neste repo); decisão confirmada com o usuário de definir esses contratos aqui mesmo, em `simplicio/plan_compiler/`, como implementação de referência versionada (`simplicio.plan-dag/v1` etc.), no mesmo padrão de `simplicio.task-spec/v2`. Slice 1 implementado: dataclasses `GoalEnvelope`/`ContextSnapshot`/`PlanDAG`/`PlanNode`/`EffectPlan`/`VerificationPlan` com `to_dict`/`from_dict`, `PlanDAG.canonical_hash()` (sha256 sobre JSON canônico, mesmo padrão de `orchestrator.multi_task._stable_hash`) e `PlanDAG.validate()` (ciclo, nó órfão, duplicata, autoridade ausente, efeito irreversível sem gate/checkpoint, AC sem verifier, estouro de budget) — puramente aditivo, sem wiring em `cli.py`/`pipeline.py`/`multi_task.py`. Plano completo (roadmap de 7 slices) salvo em `.claude/plans/logical-mapping-reddy.md`.
- 2026-07-12: issue #166 slice 2 implementado via `/simplicio-loop`:
  `simplicio.plan_compiler.compile_task_spec.compile_task_spec_to_plan()`
  compila deterministicamente um `TaskSpec` existente em
  `(PlanDAG, list[EffectPlan], list[VerificationPlan])` (nó `edit.apply`
  write+gate -> nó `test.run` dependente, um `VerificationPlan` por
  `verification_commands`, todo `acceptance_criteria` mapeado nos dois
  nós), rejeitando com `PlanCompilationError`
  (`NEEDS_CLARIFICATION: ...`) quando faltam AC ou verification_commands
  em vez de assumir silenciosamente. Puramente aditivo, ainda sem wiring
  em `cli.py`/`pipeline.py`/`orchestrator/multi_task.py`. Testes focados
  novos em `tests/python/test_compile_task_spec.py` (compile válido,
  determinismo do hash, rejeição de AC/verification_commands ausentes,
  cobertura de AC) verdes; `ruff check`/`ruff format --check` verdes nos
  arquivos tocados; `mypy simplicio` mantém apenas os 3 erros
  pré-existentes em `orchestrator/multi_task.py`/`pipeline.py`
  (não relacionados a este slice); suite completa
  `pytest -q` mostra os mesmos 48 failures pré-existentes de antes deste
  slice (confirmado via `git stash`), nenhum em `test_plan_compiler.py`/
  `test_compile_task_spec.py`.
