---
name: simplicio-loop
description: Orchestrate multi-step Simplicio work with agents, slots, stages, retries, fan-out, recovery, verification, and convergence. Use for multiple issues, iterative implementation, parallel tasks, reviewer cycles, bounded retries, or workflows that must discover, act, test, correct, record, and repeat. Remain operational without Runtime.
---

# Simplicio Loop

Use Loop as the runtime-agnostic orchestration layer. It coordinates Mapper, Fast, Dev CLI, and optional Runtime capabilities without becoming the owner of repository mutations. Read `references/capabilities.yaml` and `references/interfaces.md` before selecting a stage or recovery path.

## Complete interface map

Use the generated Prism inventory for the installed Loop release. Include orchestration CLI/MCP/API surfaces, configuration, event inputs/outputs, slot and worktree effects, errors, recovery fallbacks, dependencies, concurrency cost, version, and compatibility. Mark unmeasured scheduling cost explicitly.

## Routing

- Invoke for multi-step work, multiple issues, agent slots, fan-out/fan-in, retryable tasks, review cycles, or convergence.
- Use one issue/task per slot unless the task contract explicitly allows grouping.
- Require Mapper and Dev CLI for implementation workflows; use Fast when it is available and compatible.
- Use Runtime only for capabilities requiring native execution, MCP, gates, receipts, checkpoints, backpressure, or governed subagents.
- Do not hide a failed slot, fabricate completion, or retry an ambiguous effect without reconciliation.

## Canonical flow

`discover → understand → decide → act → verify → correct → record → repeat`

Keep each stage bounded and emit an event with task ID, capability ID, inputs, outputs, evidence, and status. Stop when the completion oracle is proven, not when an agent merely reports success.

## Contract

Return `run_id`, `plan`, `slots`, `events`, `attempts`, `receipts`, `completion_verdict`, and `unresolved`. Preserve causality across retries and make parallel work reproducible.

## Resources

- `references/capabilities.yaml`: machine-readable capability map.
- `references/interfaces.md`: stages, slots, concurrency, recovery, and Runtime boundary.
- `scripts/probe-capabilities.py`: validate the capability manifest and detect duplicate IDs.

<!-- simplicio-global-llm-architecture-rules:start -->
## Regras arquiteturais globais (obrigatórias)

- Delete diretamente o que está obsoleto; não preserve compatibilidade retroativa,
  não crie migrações e não deixe fallbacks.
- Escolha a implementação mais simples para a necessidade atual; sem abstrações
  preventivas ou configuração desnecessária.
- Entregue primeiro o mínimo end-to-end e evolua por camadas longas, sem desmontar
  o que funciona por complexidade inacabada.
- Mantenha modularidade e separação clara de responsabilidades.
- Prefira bibliotecas maduras e mantidas; reescreva do zero apenas com motivo
  técnico explícito.
- Inspecione as dependências existentes antes de adicionar pacotes ou reimplementar.
- Tome decisões arquiteturais para o longo prazo; não deixe soluções temporárias.
- Reutilize padrões validados por produtos maduros; não reinvente a roda.

<!-- simplicio-global-llm-architecture-rules:end -->

