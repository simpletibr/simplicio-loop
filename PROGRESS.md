# PROGRESS

- 2026-07-22: issue #98 verifier strengthened to fail closed when compatibility
  `master` diverges from `main`, with explicit previous/default metadata and
  concrete live receipt. Focused suite: 11 passed, 97.06% branch coverage;
  benchmark best 5.007 us/verification. Publication remains blocked because
  GitHub still reports `default_branch=master`, branch tips diverge, and this
  checkout has no remote, `gh`, or credential. Issue remains open.

 - 2026-07-22: issue #262 quality slice ported from master to current main and strengthened. The exact internal-JSON registry now rejects wildcards/traversal/missing accountability, scans wheel/sdist contents, and is wired into both local pre-commit hooks. Focused tests: 14 passed with 88% branch-aware scanner coverage. Measured 10k-entry scanner benchmark and blocker report saved under `docs/evidence/issue-262-*`. Full gate remains red from main-baseline failures; HBI/HBP conformance and cross-repository migration evidence remain explicitly unproven, so the PR is not mergeable.

- 2026-07-22: issue #256 implemented `RuntimeEffectSink` with Runtime HTTP negotiation, typed outcomes, idempotency, atomic journal evidence, reconciliation, circuit-breaker behavior, and write-set/payload guards. Focused suite: 36 passed with 94.86% branch coverage; benchmark median 0.7126 ms, p95 1.0968 ms, 1311.19 transactions/s. Full-gate pre-existing failures remain documented in the PR.
- 2026-07-23: issue #256 follow-up makes post-admission receipt failures durable `effect_unknown` outcomes without persisting untrusted receipt content, distinguishes pre-admission transport failure as `not_started`, and prevents atomic execution from claiming `not_started` was submitted. Focused suite: 63 passed, 93.01% branch coverage; benchmark median 0.2176 ms, p95 0.3307 ms; exact-patch installed-wheel probe passed (SHA-256 `53afe69f2c63f7ec6e803112fad4e057c5e87b3eabcd8a8cc92b5b6ba11db99d`). Live Runtime/Agent receipts remain blocked externally.

- 2026-07-22: issue #258 added coordinator-owned atomic integrated execution with `AttemptContext`, one-dispatch/one-attempt guards, and typed `AtomicObservation`. Focused evidence: 17 tests, 96% touched branch coverage, and 5,000 attempts with one effect call per attempt; baseline mypy debt remains outside the slice.
- 2026-07-22: issue #258 follow-up hardened the sink boundary against causal identity substitution: a caller cannot replace the selected PlanNode or coordinator attempt ID through `EffectDispatchContext`. Ruff, format, compile, and diff checks passed. Focused pytest/coverage were blocked before collection because the Cloud checkout lacks the declared `simplicio-mapper` dependency (`ModuleNotFoundError: simplicio_mapper`); mypy retained the five pre-existing errors in `models.py`, `observability.py`, `task_operator.py`, and `execution_mode.py`.

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

- 2026-07-22: issue #256 adversarial follow-up now validates the complete causal identity in every Runtime receipt; 8 forged coordinator/session/attempt/plan variants fail closed even with a recomputed valid digest. Focused result: 44 passed, 91.22% branch coverage across the sink/integrated slice, clean-wheel probe passed, and 500-transaction benchmark recorded. Live Runtime/Agent cross-repository traces remain unavailable, so the issue remains open and full completion is not claimed.

## Issue #265 audit hardening

 - 2026-07-22: issue #265 live meta-audit hardened after adversarial review. Credential-shaped tokens and complete PEM blocks are redacted from content, metadata, and classifications before JSON/Markdown persistence; unmeasured and explicitly negated evidence claims now fail closed instead of producing `CLOSE-READY`. Live inventory remains 97 issues (90 closed/7 open); 15 focused tests pass at 97.40% branch-aware coverage; 50-iteration benchmark measured 782.8 issues/s. Publication remains dependent on GitHub CLI/API credentials.

 - 2026-07-22: issue #262 quality slice ported from master to current main and strengthened. The exact internal-JSON registry now rejects wildcards/traversal/missing accountability, scans wheel/sdist contents, and is wired into both local pre-commit hooks. Focused tests: 14 passed with 88% branch-aware scanner coverage. Measured 10k-entry scanner benchmark and blocker report saved under `docs/evidence/issue-262-*`. Full gate remains red from main-baseline failures; HBI/HBP conformance and cross-repository migration evidence remain explicitly unproven, so the PR is not mergeable.

- 2026-07-22: issue #256 implemented `RuntimeEffectSink` with Runtime HTTP negotiation, typed outcomes, idempotency, atomic journal evidence, reconciliation, circuit-breaker behavior, and write-set/payload guards. Focused suite: 36 passed with 94.86% branch coverage; benchmark median 0.7126 ms, p95 1.0968 ms, 1311.19 transactions/s. Full-gate pre-existing failures remain documented in the PR.

- 2026-07-22: issue #258 added coordinator-owned atomic integrated execution with `AttemptContext`, one-dispatch/one-attempt guards, and typed `AtomicObservation`. Focused evidence: 17 tests, 96% touched branch coverage, and 5,000 attempts with one effect call per attempt; baseline mypy debt remains outside the slice.

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

## Issue #262 quality-gate progress

 - 2026-07-22: issue #262 follow-up wired the strict source and built-archive scanner into blocking CI across Linux/macOS/Windows. `--artifact-dir` fails closed for missing/empty release directories and scans every wheel/sdist. Focused evidence: 16 passed, 89% branch-aware scanner coverage; real wheel/sdist scan: 0 findings; 10k-entry median: 899.739 ms. Runtime HBI/HBP and released cross-repository migration evidence remain external blockers.

 - 2026-07-22: issue #262 quality slice ported from master to current main and strengthened. The exact internal-JSON registry now rejects wildcards/traversal/missing accountability, scans wheel/sdist contents, and is wired into both local pre-commit hooks. Focused tests: 14 passed with 88% branch-aware scanner coverage. Measured 10k-entry scanner benchmark and blocker report saved under `docs/evidence/issue-262-*`. Full gate remains red from main-baseline failures; HBI/HBP conformance and cross-repository migration evidence remain explicitly unproven, so the PR is not mergeable.

- 2026-07-22: issue #256 implemented `RuntimeEffectSink` with Runtime HTTP negotiation, typed outcomes, idempotency, atomic journal evidence, reconciliation, circuit-breaker behavior, and write-set/payload guards. Focused suite: 36 passed with 94.86% branch coverage; benchmark median 0.7126 ms, p95 1.0968 ms, 1311.19 transactions/s. Full-gate pre-existing failures remain documented in the PR.

- 2026-07-22: issue #258 added coordinator-owned atomic integrated execution with `AttemptContext`, one-dispatch/one-attempt guards, and typed `AtomicObservation`. Focused evidence: 17 tests, 96% touched branch coverage, and 5,000 attempts with one effect call per attempt; baseline mypy debt remains outside the slice.

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

## Issue #257 integrated-mode progress

- 2026-07-22: issue #257 follow-up corrected the integrated ContextSnapshot boundary to use Mapper's real `simplicio.context-snapshot/v1` contract and full adapter validation at negotiation and dispatch. Focused evidence: 25 passed, 94% branch-aware touched-module coverage, clean fail-closed CLI JSON, and 68.16 microseconds/negotiation over 10,000 calls. Repository-wide baseline lint/type/test debt remains recorded in `docs/evidence/issue-257.md`.

 - 2026-07-22: issue #262 quality slice ported from master to current main and strengthened. The exact internal-JSON registry now rejects wildcards/traversal/missing accountability, scans wheel/sdist contents, and is wired into both local pre-commit hooks. Focused tests: 14 passed with 88% branch-aware scanner coverage. Measured 10k-entry scanner benchmark and blocker report saved under `docs/evidence/issue-262-*`. Full gate remains red from main-baseline failures; HBI/HBP conformance and cross-repository migration evidence remain explicitly unproven, so the PR is not mergeable.

- 2026-07-22: issue #256 implemented `RuntimeEffectSink` with Runtime HTTP negotiation, typed outcomes, idempotency, atomic journal evidence, reconciliation, circuit-breaker behavior, and write-set/payload guards. Focused suite: 36 passed with 94.86% branch coverage; benchmark median 0.7126 ms, p95 1.0968 ms, 1311.19 transactions/s. Full-gate pre-existing failures remain documented in the PR.

- 2026-07-22: issue #258 added coordinator-owned atomic integrated execution with `AttemptContext`, one-dispatch/one-attempt guards, and typed `AtomicObservation`. Focused evidence: 17 tests, 96% touched branch coverage, and 5,000 attempts with one effect call per attempt; baseline mypy debt remains outside the slice.

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

- 2026-07-22: issue #256 adversarial follow-up now validates the complete causal identity in every Runtime receipt; 8 forged coordinator/session/attempt/plan variants fail closed even with a recomputed valid digest. Focused result: 44 passed, 91.22% branch coverage across the sink/integrated slice, clean-wheel probe passed, and 500-transaction benchmark recorded. Live Runtime/Agent cross-repository traces remain unavailable, so the issue remains open and full completion is not claimed.
## Issue #298 canonical PlanDAG contract

- 2026-07-23: added the canonical ownership manifest, digest-bound consumer
  projections, explicit node conflicts, ADR-007, adversarial conformance tests
  and a measured benchmark. Focused result: 51 passed; new conformance module
  99% branch-aware coverage; 1,000-iteration benchmark mean 0.288002 ms and
  p95 0.313495 ms. Full baseline: 1,915 passed, 20 skipped and 41 pre-existing
  failures; cross-repository Loop/Runtime adoption remains an explicit closure
  gate.
