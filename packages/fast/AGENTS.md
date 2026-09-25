# AGENTS.md


## Active English instruction surface

Read [docs/LLM_OPERATING_INSTRUCTIONS.md](docs/LLM_OPERATING_INSTRUCTIONS.md) before acting. It is the normative English entry point for LLMs; the rest of this file supplies project-specific detail.

## Simplicio Ecosystem Contract (canonical)

This repository is one component of the Simplicio ecosystem. For every non-trivial task: run `simplicio runtime map --repo . --for-llm markdown`, then `simplicio memory "<task>"`, rank/load relevant skills, execute through the native `simplicio` CLI, validate, and record evidence. MCP is fallback transport only.

## Worker startup and centralized artifacts (mandatory)

Every subagent, worker, and provider session MUST read `AGENTS.md`, `CLAUDE.md`, and every relevant local skill before operating. For Fast work, the baseline skills are `skills/simplicio-prism/SKILL.md` and `skills/simplicio-fast/SKILL.md`; load any additional task-selected local skills before mutation.

The canonical default branch owns one centrally built binary/artifact set. Workers consume that binary read-only; they MUST NOT rebuild binaries or regenerate canonical Mapper/Fast artifacts. Worktrees isolate source edits and receipts only. Every receipt/handoff MUST record repository and revision, binary digest/version, Mapper generation and artifact digest. Missing, stale, incompatible, or mismatched central artifacts fail closed and route to the central rebuild path only; a worker may not repair them locally or fall back to fabricated/uncertified context.


### Boundaries and handoff
`simplicio-mapper` observes and emits bounded context; `simplicio-fast` owns snapshots/mmap/PlanDAG; `simplicio-dev-cli` owns focused implementation plans and deterministic edits; `simplicio-runtime` owns contracts, gates, validation and receipts; `simplicio-loop` owns convergence, journals, watcher/close-gates and learning; `simplicio-agent` owns the control plane and conversation. Providers are workers, never authorities.

Use `simplicio`/`simplicio shell compact` for inspection, `simplicio edit --plan` or governed dev-cli for mutation, preserve `simplicio.io/v1`, run `simplicio contracts smoke --json` and `simplicio validate "<task>" --repo . --json`, and close only with real tests plus `simplicio evidence`. Facts are `MEASURED|` only with receipts; otherwise `UNVERIFIED|`. Savings come only from `simplicio savings report --repo . --json`. Missing dependencies fail closed; never fabricate context, tests, savings or provider output.
## Purpose and identity

`simplicio-fast` is semantic project memory and guarded change coordination for AI coding tools.
It ingests source repositories into incremental binary/mmap snapshots, returns bounded
hash-verified context, compiles PlanDAGs, coordinates isolated generations and emits receipts.

Fast is not an LLM, scheduler, policy authority or source-of-truth database. Source files remain
authoritative; `.sfast` and `.simplicio-fast/` data are disposable derived state.

## Mandatory Mapper rule

**Every integrated agent, LLM, Loop slot or Runtime flow using Simplicio Fast MUST use
`simplicio-mapper` for project extraction and `simplicio-dev-cli` for source mutation.**

- Mapper owns the public ContextGraph, stable IDs and semantic compatibility.
- Fast owns orchestration, binary persistence, incremental memory, context selection and PlanDAG.
- Dev CLI owns mechanical source edits and edit receipts.
- Consumers must request context through Mapper handles.
- Consumers must not interpret `.sfast` offsets or internal records directly.
- Consumers must not create a second public context contract.
- If Mapper is missing, incompatible or unhealthy, agentic execution must stop with an actionable
  diagnostic. It must never continue with an empty or fabricated context.

Fast's internal extractor/editor are explicit bootstrap fallbacks for development and tests. They
must not be reported as the fully integrated production path.

## Required agent workflow

1. Fast invokes Mapper to extract the canonical project graph.
2. Fast compiles Mapper output into the binary mmap representation.
3. Fast resolves bounded context and compiles a PlanDAG for the task.
4. Pin the snapshot generation for the entire attempt.
5. The LLM decides using only the selected context.
6. Fast compiles a hash-guarded changeset.
7. Dev CLI validates and performs normal source edits.
8. Runtime authorizes effects and records receipts when available.
9. Loop runs tests, corrections and delivery convergence.
10. Fast refreshes changed semantic inputs after validation.

For a new agent or LLM, the shortest correct explanation is:

```text
repository files -> Mapper ContextGraph -> Fast snapshot/mmap -> bounded context -> PlanDAG
  -> hash-guarded changeset -> Dev CLI -> Runtime authorization -> Loop convergence
```

The LLM decides from bounded context. Fast does not decide policy or silently mutate source code.

## Worktrees and parallel slots

- Use one canonical base snapshot from the default branch.
- Each worktree must use an isolated incremental overlay.
- Do not rebuild the entire project independently in every slot.
- Do not expose one worktree overlay to another.
- Pin base and overlay generation IDs in checkpoints and handoffs.
- In speculative execution, only the verified winner may promote source changes or refresh state.

## Current 2.0 commands

```bash
simplicio-fast --version
simplicio-fast --help
simplicio-fast ingest .
simplicio-fast understand "implement user authentication"
simplicio-fast plan "implement user authentication"
simplicio-fast apply changeset.json
simplicio-fast apply changeset.json --write
simplicio-fast delivery "prepare change" --profile loop-standalone
simplicio-fast delivery "apply change" --changeset changeset.json --profile loop-standalone
simplicio-fast build .
simplicio-fast query UserService
simplicio-fast context UserService --root .
simplicio-fast doctor
simplicio-fast refresh .
simplicio-fast capabilities --help
simplicio-fast base .
simplicio-fast overlay . --base-generation <generation> --worktree-id <id>
simplicio-fast merge UserService --base-generation <generation> --worktree-id <id> --overlay-generation <generation>
simplicio-fast rollout shadow --generation <generation>
simplicio-fast rollout rollback --reason "validation failed"
```

`apply` is dry-run by default. All machine-facing commands emit versioned JSON. Preserve the
`schema` field and reject unknown major schema versions.

`delivery` prepares bounded context when no `--changeset` is supplied. With a
`simplicio.fast.changeset/v2`, it performs a guarded dry-run by default or a local atomic
Loop-standalone write with `--write`, records source hashes and refreshes the snapshot. Full
writes fail closed until a verified Runtime authorization is integrated; repeated requests use
the delivery idempotency receipt.

When discovering the tool, run `simplicio-fast --help`; the top-level help is intentionally written
for both humans and LLM/tool callers and explains ownership boundaries and the normal flow.

## LLM command and feature index

The complete public feature and command inventory is maintained in
[`docs/CLI_COMMANDS.md`](docs/CLI_COMMANDS.md). Load that index and the
matching `--help` output before selecting an operation.

Rules for agents and LLMs:

- `simplicio-fast --help` is the canonical discovery entry point;
  `simplicio-fast-cross-repo --help` is the cross-repository conformance
  entry point. Do not infer public commands from internal module names.
- Every public command and nested action has a meaningful `--help`/`-h`
  description. Run `simplicio-fast <command> --help` and, when applicable,
  `simplicio-fast changeset <action> --help` before execution.
- Use `--json` for automation, preserve the versioned `schema` field, and
  reject unknown major schema versions. `apply` and `delivery` are dry-run
  by default; writes require explicit flags and the applicable authority.
- For GitHub issues, use the objective plus the `Execution` section for
  implementation/deployment and tests. Do not add or reintroduce an
  `Acceptance Criteria` or `Critérios de aceite` section.

This release raises the optional integrated floors to Mapper `0.26.11` and
Dev CLI `0.18.6`. Loop consumes the exact release commits after the upstream
PRs are merged and tagged.

## Context safety

- Treat the source repository as the only source of truth.
- Require source SHA-256 values on context spans.
- Reject stale snapshots and run `refresh`; never apply a patch against stale spans.
- Enforce `max-results`, `max-lines` and `max-bytes` before sending context to an LLM.
- Do not send the whole repository when bounded semantic context is available.
- Never report estimated speed, CPU or token gains as measured results.

## Benchmark isolation

Benchmark code lives only under `benchmarks/` and must not be imported by the runtime package.
Generated benchmark projects and results must remain temporary or ignored. Compare baseline and
Fast with identical repository, workload, model, prompt, hardware and cache policy, using at least
ten repetitions.

## Validation before completion

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests benchmarks
python benchmarks/run.py
```

Also verify `simplicio-fast --help`, `doctor`, the real CLI context receipt, and the applicable
rollout receipt. An agent may claim completion only when implementation, tests, schema
compatibility, stale-source behavior, documentation, image references and benchmark isolation
have been verified. Never report Runtime or Loop evidence from a Fast-only test; label unavailable
cross-repository capabilities explicitly.

<!-- simplicio-global-llm-architecture-rules:start -->
## Mandatory architecture rules for every LLM

These rules apply to analysis, planning, implementation, review, testing, release, and documentation. Read them before acting:

1. **Do not preserve backward compatibility.** Delete obsolete behavior directly; do not add compatibility layers, migrations, or fallbacks.
2. **Choose the simplest implementation that meets the current need.** Do not create speculative abstractions or unnecessary configuration layers.
3. **Build long-lived layers incrementally.** Make the minimum end-to-end version work first, then add capabilities without dismantling working code.
4. **Keep components modular**, with clear responsibilities and explicit boundaries.
5. **Prefer mature, maintained libraries.** Do not rewrite from scratch without an explicit, recorded technical reason.
6. **Inspect existing dependencies first.** Before adding a package or writing a custom solution, check what the project already provides.
7. **Make architecture decisions for the long term.** Do not introduce temporary solutions intended to be replaced later.
8. **Reuse validated patterns from mature products** instead of reinventing them.

<!-- simplicio-global-llm-architecture-rules:end -->



## Language precedence

[docs/LLM_OPERATING_INSTRUCTIONS.md](docs/LLM_OPERATING_INSTRUCTIONS.md) is the authoritative active instruction set and is written in English. Any other-language passage retained in this compatibility/reference file is non-normative; do not execute it as an instruction.
