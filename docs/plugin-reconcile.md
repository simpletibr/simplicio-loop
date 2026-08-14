# Plugin v1 partial reconcile

Dev CLI inspects a partial edit or test attempt and emits
`simplicio.plugin.dev-reconciliation-evidence/v1`. Runtime decides
authority. This runbook does not reset, stash, or check out user work.

## Inspect

```text
python -m simplicio.plugin_reconcile inspect --json \
  --root <repo> --attempt-id <id> --lease-id <lease> --plan <plan.json>
```

Optional `--receipt`, `--journal`, and `--tests` supply hashes and
validation state. The evidence names each operation as `not_applied`,
`applied`, `partial`, or `ambiguous`.

## Resume (dry-run)

Resume only when `recommended_action` is `resume`. Applied operations
are omitted. Ambiguous files block resume (`USER_MUTATION_DETECTED`,
`no_retry`).

```text
python -m simplicio.plugin_reconcile resume --json --dry-run \
  --root <repo> --attempt-id <id> --lease-id <lease> --plan <plan.json>
```

## Rollback

A rollback plan is emitted only when every applied file still matches
the stored after-hash and a before-hash exists. Restore those bytes.
Do not run `git reset`, `git stash`, `git checkout`, or `git restore`.

## Tests

`validation_delta` lists unrun, stale, or failed commands. Timeouts and
kills stay unrun. Unexecuted tests are never marked pass.

## Crash markers

Crash state is written to `.simplicio/plugin-reconcile/<attempt_id>.crash.json`
and can be deleted after a successful inspect. Cleanup is file-local.
