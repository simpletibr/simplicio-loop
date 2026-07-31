# Scoped foreground context contract

`scoped-handoff` returns a bounded foreground corridor without waiting for a repository-wide deep scan.

## Lifecycle

1. Normalize `repo_root`, `scope_root`, and targets. Resolved targets must remain inside the scope; traversal and symlink escapes fail closed.
2. Read canonical Mapper artifacts only on a cold or artifact-stale request. The target corridor contains explicit targets, one-hop callers/callees, nearest matching tests, and in-scope manifests.
3. Enforce `context_budget` as bytes. If the deterministic corridor cannot fit, the response visibly reports `budget.expanded`, `effective_bytes`, and `expansion_bytes`; it never silently drops the explicit target.
4. Publish an immutable SHA-bound generation. A promotion pointer is swapped atomically; generation files are never overwritten.
5. An `attempt_id` creates a durable pin. Later promotions cannot change retrieval for that attempt.
6. Enqueue a durable background record and, unless `--no-background` is set, start the explicit worker boundary. Deep repository work remains owned by Loop/#408.

## Cache and metrics

The default cache is shared under `SIMPLICIO_MAPPER_SCOPED_CACHE` (or the user Simplicio cache) and keyed by repository identity, Git revision/tree, scope, target, task, and configuration fingerprints. Every span carries its source SHA-256 and source stat receipt. Warm requests reuse cached rows before source/artifact parsing; incremental requests report `actual_changed_paths`, `dependency_invalidations`, `source_files_parsed`, and `source_files_reused`.

The frozen foreground threshold is `250 ms` wall time per invocation. The response includes `performance_threshold_ms` and `performance_threshold_passed`; benchmark gates must measure cold, warm, and incremental modes with at least ten repetitions.

## Operator examples

```text
python -m simplicio_mapper.cli scoped-handoff . --target simplicio_mapper/scoped_context.py --json
python -m simplicio_mapper.cli scoped-handoff . --scope-root src --target target.py --no-background --json
```

`simplicio-mapper` owns observation and the bounded handoff. `simplicio-loop` owns convergence and background scheduling; a missing or corrupt cache is never a reason to use stale context.
