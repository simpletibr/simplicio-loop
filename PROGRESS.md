# PROGRESS

## Issue #300 digest-bound context progress

- 2026-07-23: implemented a fail-closed local binding between canonical Mapper
  ContextSnapshot bytes, a provenance-bearing ContextPack projection, and one
  SHA-256 context handle. The handle now crosses PlanDAG, EffectPlan, Attempt,
  EffectTransaction causal metadata, observation, and verified receipt.
- 2026-07-23: added pre-dispatch source-drift/path checks, typed projection
  rejection (origin, hash, fidelity, budget, sensitive fields), N-1 downgrade
  refusal for bound plans, hash-only diagnostics, and evidence documenting the
  Mapper/Loop/Runtime blockers that cannot be proven in this repository.

- 2026-07-22: issue #98 verifier strengthened to fail closed when compatibility
  `master` diverges from `main`, with explicit previous/default metadata and
  concrete live receipt. Focused suite: 11 passed, 97.06% branch coverage;
  benchmark best 5.007 us/verification. Publication remains blocked because
  GitHub still reports `default_branch=master`, branch tips diverge, and this
  checkout has no remote, `gh`, or credential. Issue remains open.

- 2026-07-22: issue #262 quality slice ported from master to current main and strengthened. The exact internal-JSON registry now rejects wildcards/traversal/missing accountability, scans wheel/sdist contents, and is wired into both local pre-commit hooks. Focused tests: 14 passed with 88% branch-aware scanner coverage. Measured 10k-entry scanner benchmark and blocker report saved under `docs/evidence/issue-262-*`. Full gate remains red from main-baseline failures; HBI/HBP conformance and cross-repository migration evidence remain explicitly unproven, so the PR is not mergeable.
- 2026-07-23: issue #262 binary slice added a Runtime-compatible HBP completion cache, atomic/idempotent legacy JSONL migration, and `scripts/issue_262_e2e.py` Markdown+HBP evidence runner. Focused cache/HBP/boundary suite passes; installed Runtime/Mapper probes remain `UNVERIFIED` when unavailable and therefore keep release blocked.

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
- 2026-07-23: issue #262 scanner hardening validates exact exception categories/dates, standard-library serializer imports, renamed arrays, symlinks and oversized text; Python/Node evidence is byte-identical and HBP tampering is detected. Focused suite: 44 passed with 90.81% combined branch coverage. A wheel built and installed into an isolated target, reported version 0.16.2, and passed the internal-state archive scan. The shared strict source gate still blocks release with 1448 unclassified findings; Runtime HBI conformance, atomic migration, adjacent released packages and non-Linux hosts remain unavailable.

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

- 2026-07-23: issue #299 replaced the lossy integrated text bridge with an
  optional typed `TaskSpec` handoff. External v2 JSON imports validate schema,
  required identity, SHA-256 source hash, and acceptance-criterion IDs;
  additive fields survive round trips; CLI file/stdin adapters feed the same
  object to the compiler; standalone use fails closed. Focused validation:
  63 passed; the repository-wide run reached 1917 passed, 20 skipped and 41
  pre-existing baseline failures. Final evidence is recorded in
  `docs/evidence/issue-299-validation.md`.
- 2026-07-23: issue #299 adversarial follow-up rejected reserved additive-field
  collisions, fully validates known JSON containers and verification commands,
  rejects non-finite values, and disambiguates a future additive `tasks` field
  from a document wrapper. Rebased affected suite: 118 passed.

- 2026-07-23: installed-entrypoint follow-up added CLI/environment/API inputs
  for canonical snapshot plus coordinator attempt/lease/fence identity, reused
  the production sink's versioned capability handshake, and rejected sink
  lookalikes. Focused result: 121 passed; issue slice 88.74% branch coverage;
  clean wheel build/install passed; negotiation measured 15.05 us/call. Live
  Runtime E2E/DEFAULT/GATED and rollback receipts remain unavailable, so the
  issue is not claimed closed.
- 2026-07-22: issue #257 follow-up corrected the integrated ContextSnapshot boundary to use Mapper's real `simplicio.context-snapshot/v1` contract and full adapter validation at negotiation and dispatch. Focused evidence: 25 passed, 94% branch-aware touched-module coverage, clean fail-closed CLI JSON, and 68.16 microseconds/negotiation over 10,000 calls. Repository-wide baseline lint/type/test debt remains recorded in `docs/evidence/issue-257.md`.

 - 2026-07-22: issue #262 quality slice ported from master to current main and strengthened. The exact internal-JSON registry now rejects wildcards/traversal/missing accountability, scans wheel/sdist contents, and is wired into both local pre-commit hooks. Focused tests: 14 passed with 88% branch-aware scanner coverage. Measured 10k-entry scanner benchmark and blocker report saved under `docs/evidence/issue-262-*`. Full gate remains red from main-baseline failures; HBI/HBP conformance and cross-repository migration evidence remain explicitly unproven, so the PR is not mergeable.

## Issue #301 standalone migration progress

- 2026-07-23: added governed migration phases, explicit legacy-write opt-in,
  fail-closed `effect_unknown`, route telemetry, legacy/integrated receipt
  classification, and an AST baseline guard covering 184 mutation scopes /
  241 candidate calls. Focused result: 86 passed with 98% branch coverage;
  package build/install and installed fail-closed/compatibility probes passed.
  Compatibility remains `shadow` by default. Offline Effect API parity,
  published upgrade/downgrade, adoption receipts, and final removal remain
  external blockers recorded in
  `docs/evidence/issue-301.md`.

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


## Issue #232 release-train progress

- 2026-09-06: worked from `origin/main` on `feat/232-mapper-release-train`; the
  pre-existing `GEMINI.md` deletion remains intentionally untouched.
- Added Mapper 0.26.28 as the verified lock candidate, immutable artifact
  digests, component/release-event metadata, a fail-closed repository-dispatch
  reconciler, fixed-branch single-PR automation, drift-issue deduplication,
  scoped gate/auto-merge workflows, signed Dev CLI manifest publication, and
  post-PyPI Loop propagation.
- Added executable conformance for installed N/N-1 Mapper contract checkouts
  and the real map -> retrieve -> edit -> test -> receipt smoke. The published
  Mapper wheel does not contain source-only `contracts/`, so the proof uses the
  exact immutable `v0.26.28`/`v0.26.27` tag checkouts and records this provenance.
- Focused validation is green: 111 tests, targeted Ruff, targeted format, and
  targeted mypy. Mapper source conformance is green for N/N-1 and the smoke
  reports a measured 5,706 JSON bytes within the 30,000 ms budget. Package build,
  Twine check, generated dependency documentation, JSON/TOML validation, and
  reconciliation idempotence are green.
- Full local pytest reached 2,702 passed and 24 skipped with 17 unrelated
  baseline failures; global coverage is 85.42% (floor 85%). The independent
  coverage script still reports the pre-existing critical `simplicio/mapper.py`
  85.46% < 90% failure. GitHub Actions are disabled in repository settings, so
  no hosted check result is treated as evidence. Stable promotion remains
  fail-closed until signing/SBOM/provenance and external Loop receipts exist.

- Push/PR handoff is blocked by the authenticated GitHub OAuth token: GitHub
  rejected the workflow-bearing push because the token has `repo` but not
  `workflow` scope. `gh auth refresh --hostname github.com --scopes workflow`
  requires device authorization unavailable in this session. No remote branch,
  PR, merge, or hosted check is claimed.

## Issue #691 local progress

- 2026-09-06: implemented the Dev CLI-owned deterministic edit and scaffold
  boundary from `origin/main`. `TextEdit`, single-anchor replacement,
  expected-hash conflict detection, atomic pure batch planning/application,
  versioned receipts, canonical Mapper binding, and Rust/Python/Node scaffold
  planning now live in the Dev CLI. Canonical `simplicio edit` plans bypass
  the legacy native Mapper edit vocabulary; Runtime contract metadata and
  checked-in JSON schemas describe the authorization/effect handoff.
- Focused validation: 153 passed, 2 skipped; full-suite critical coverage is
  92.53% for `mechanical_edit.py` and focused coverage is 93.24% for
  `scaffold_contract.py`.
- The bounded kernel benchmark measured a 30.044 microsecond median per call over 10 x
  1,000 iterations. Independent adversarial checks passed for effective edit,
  CRLF/portable paths, hash drift, and all four scaffold kinds.
- Full local validation remains limited by the existing environment baseline:
  2,743 passed, 23 skipped, 21 unrelated failures; global coverage 85.60%;
  full Ruff and mypy retain pre-existing failures; package build lacks the
  uninstalled `build` module. Runtime #5525, Mapper #613, hosted Actions, and
  cross-repository Loop E2E conformance were unavailable and are not claimed.
