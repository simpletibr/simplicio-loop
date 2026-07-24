# Standalone write migration

Issue #301 migrates product mutations to the Runtime Effect API without
silently removing offline workflows. The migration is phase-driven and
fail-closed after an outcome becomes unknown.

## Compatibility contract

`SIMPLICIO_STANDALONE_MIGRATION_PHASE` selects one of these phases:

| Phase | Planned release/date | Local write behavior |
|---|---|---|
| `shadow` | 0.16.x, active from 2026-07-23 | Existing behavior remains compatible. Every selected mutation route emits deprecation telemetry and legacy receipts never claim a Runtime gate. |
| `opt_in` | 0.17.0, target 2026-08-15 | Local writes require `SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE=1`. Without it, task, feature, sprint, and edit fail closed. |
| `warning` | 0.18.0, target 2026-09-01 | Same explicit opt-in, with the legacy route retained only for migration and rollback exercises. |
| `read_only` | 0.19.0, target 2026-10-01 | Opt-in no longer authorizes local product writes. Planning and dry-run remain available. |
| `removed` | 1.0.0, no earlier than 2026-12-01 | Legacy mutation adapter is removed only after the adoption gates and a compatibility decision are recorded. |

Dates after `shadow` are targets, not claims that those releases exist.
Promotion requires measured Runtime/Loop adoption, clean install and
upgrade/downgrade receipts, offline executor parity, and zero unresolved
`effect_unknown` outcomes.

Project configuration may use the equivalent keys in
`.simplicio/execution.json`:

```json
{
  "standalone_migration_phase": "opt_in",
  "enable_legacy_standalone_write": true
}
```

Environment values take precedence. An invalid phase is treated as
`read_only`, never as a permissive phase.

## Routing and receipts

- `auto` continues its compatibility behavior only during `shadow`.
- In `opt_in` and `warning`, `auto` may choose legacy standalone only with
  the explicit compatibility opt-in.
- `read_only` and `removed` block local product writes even when the flag is
  set.
- `effect_unknown` always yields
  `EFFECT_UNKNOWN_RECONCILIATION_REQUIRED`; no phase, kill switch, or opt-in
  permits a second local write.
- Native Runtime edit results use route `runtime_effect_api`. This additive
  route marker keeps `runtime_gated=false`; only Runtime's own causal receipt
  may prove that a gate completed.
- Python task/edit receipts use route `legacy_standalone`,
  `runtime_gated=false`, and `legacy=true`.

`mutation_route_selected` events contain only entrypoint, route, reason,
phase, and the opt-in boolean. Plans, prompts, file contents, credentials,
tokens, and Runtime payloads are excluded.

## Guard against new local writes

Run:

```bash
python scripts/check_effect_boundary.py
python scripts/check_effect_boundary.py --inventory
```

The AST guard inventories mutation primitives and subprocess boundaries in
the Python product, excluding only the production
`RuntimeEffectSink`. The current-main baseline records 188 mutation scopes and
246 calls at digest
`4dfd242520c8c475d48de209168eb2a85605b868041a0c871fb25ec63b15c298`.
The baseline was refreshed after later merged contract slices; this change
adds no new mutation primitive.
Any addition, removal, or scope change outside the approved Effect boundary
fails the guard and requires an explicit inventory review.

## Rollback

Before any effect submission, rollback between `opt_in`/`warning` and
`shadow` is a configuration change. After a Runtime response is lost or an
outcome is `effect_unknown`, a secret-free reconciliation lock blocks later
task/edit mutations. Reconcile the idempotency key with Runtime before
clearing it. Rollback to a previous package version is
supported only while its schemas remain compatible and must be tested from
the built artifacts before a phase promotion.

The current package does not yet contain the required offline executor that
implements the same Effect API contract. Until that cross-repository
dependency exists, `shadow` and the explicit legacy opt-in preserve offline
compatibility but do not satisfy final migration closure.
