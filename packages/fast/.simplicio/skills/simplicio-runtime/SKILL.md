---
name: simplicio-runtime
description: Govern and execute Simplicio workflows through native execution, MCP, gates, checkpoints, receipts, backpressure, pools, memory, and subagents. Use when a task needs durable evidence, controlled side effects, native acceleration, MCP compatibility, or Runtime reconciliation. Do not make Loop depend on Runtime for ordinary orchestration.
---

# Simplicio Runtime

Use Runtime as the governed execution layer around Loop and Dev CLI. It provides controls and evidence; it does not replace Mapper's survey or Dev CLI's mutation contract. Read `references/capabilities.yaml` and `references/interfaces.md` for exact gates and receipt rules.

## Complete interface map

Use the generated Prism inventory for the installed Runtime release. Record CLI/MCP tools, Python/Rust/native APIs, configuration, effect policies, evidence inputs/outputs, error codes, fallbacks, dependencies, measured cost, version, and MCP/OS compatibility before enabling a capability.

## Routing

- Invoke for MCP tools, native executors, gates, checkpoints, durable receipts, subagents, memory, pools, backpressure, or reconciliation.
- Require explicit capability, repository, scope, and effect policy before side effects.
- Reconcile only from durable evidence; never synthesize a receipt or delete an unknown-effect lock.
- Support old and new MCP tool shapes through the compatibility capability.
- Fall back to Loop without Runtime when governance/native execution is not required and the Loop path is available.

## Required workflow

1. Validate capability, policy, inputs, and preconditions.
2. Acquire a bounded execution slot and emit a checkpoint.
3. Execute through the selected native/MCP/subagent adapter.
4. Persist receipt and evidence before reporting a verdict.
5. Recompute the result independently when reconciliation is requested.
6. Return proven, unchanged, failed, or ambiguous/diverged; preserve locks for ambiguity.

## Contract

Return `run_id`, `execution_id`, `capability_id`, `policy`, `checkpoint`, `receipt`, `evidence`, `reported`, `recomputed`, `verdict`, and `cleanup_status`.

## Resources

- `references/capabilities.yaml`: machine-readable capability map.
- `references/interfaces.md`: MCP, gates, receipts, reconciliation, pools, and fallback rules.
- `scripts/probe-capabilities.py`: validate the capability manifest and detect duplicate IDs.
