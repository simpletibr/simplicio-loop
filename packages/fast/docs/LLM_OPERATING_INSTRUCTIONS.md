# LLM Operating Instructions

This is the normative active English instruction surface for simplicio-fast. Read it before planning, implementation, validation, release, or handoff.

## Language contract

- Write new instructions, plans, route explanations, receipts, issue updates, and active documentation in English.
- Keep code identifiers and public schemas stable unless the task explicitly changes a contract.
- Preserve historical changelogs and localization/reference material; it is not an active instruction source.
- When a localized trigger is part of a compatibility contract, preserve it as an example but keep the surrounding guidance in English.

## Component responsibility

Fast accelerates indexed snapshots, ranking and bounded retrieval; it is not the source of truth or a mutation owner.

## Required workflow

1. Pin repository, revision, scope, and the completion oracle.
2. Survey the repository and load only the skills required for the task.
3. Use canonical component interfaces; do not bypass ownership boundaries.
4. Apply the smallest scoped change and run relevant tests, lint, and contract checks.
5. Record commands, versions, results, and receipts; review the diff before handoff.
6. Stop when revision, scope, dependencies, or mutation authority are unknown.

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

## Evidence rule

Never claim a test, release, merge, or completion without durable evidence.