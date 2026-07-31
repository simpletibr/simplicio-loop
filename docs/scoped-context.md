# Scoped foreground context contract

`scoped-handoff` returns a bounded foreground corridor without waiting for a repository-wide deep scan.

## Lifecycle

1. Normalize `repo_root`, `scope_root`, and targets. Resolved targets must remain inside the scope; traversal and symlink escapes fail closed.
2. Read canonical Mapper artifacts only on a cold or artifact-stale request. The target corridor contains every explicit target, symbol target, direct caller/callee dependency, nearest matching test (bounded to three), and nearest ancestor manifest. Precedents are ranked deterministically and bounded to three optional items.
3. Enforce `context_budget` as bytes. If the deterministic corridor cannot fit, the response visibly reports `budget.expanded`, `effective_bytes`, `required_paths`, `optional_paths`, `nearest_test_limit`, `precedent_limit`, and `expansion_bytes`; required rows are never silently dropped.
4. Publish an immutable SHA-bound generation. A promotion pointer is swapped atomically; an existing generation is validated for canonical identity/content before reuse. Load and pin validation recomputes the generation ID from canonical inputs (including Mapper version), recomputes the content digest, checks the aggregate artifact digest, repository identity, resolved path containment, every span SHA-256, and stat receipt.
5. An `attempt_id` creates a durable pin. Later promotions cannot change retrieval for that attempt, even when the current worktree changes.
6. Enqueue a durable background record and leave it `queued` with a strict opaque 32-character lowercase-hex work ID. Mapper does not spawn a detached process or mark completion; Loop/#408 owns the real deep-scan start, validation, and promotion boundary.

## Cache and metrics

The default cache is shared under `SIMPLICIO_MAPPER_SCOPED_CACHE` (or the user Simplicio cache) and keyed by repository identity, Git revision/tree, scope, target, task, configuration fingerprints, selected source/artifact digests, and Mapper package version. Canonical generations may be reused across worktrees, but the handoff always renders the current request root/scope while retaining the canonical repository identity. The output includes a stable `artifact_digest` aggregate and `generation.producer.version`. Every span carries its source SHA-256 and source stat receipt. Warm requests reuse cached rows before source/artifact parsing and hash selected sources; same-size mutations with restored mtimes therefore miss. Incremental requests report exact `actual_changed_paths`, selected `dependency_invalidations`, `parsed_paths`, `reused_paths`, `source_files_parsed`, and `source_files_reused`.

The frozen foreground threshold is `250 ms` wall time per invocation. The response includes `performance_threshold_ms` and `performance_threshold_passed`; `scripts/scoped_context_benchmark.py` measures wall time, CPU time, parsed/reused files, and artifact bytes for cold, warm, and incremental modes, uses configurable warmups and a p95 gate, and requires at least ten samples.

## Operator examples

```text
python -m simplicio_mapper.cli scoped-handoff . --target simplicio_mapper/scoped_context.py --json
python -m simplicio_mapper.cli scoped-handoff . --scope-root src --target target.py --no-background --json
```

`simplicio-mapper` owns observation and the bounded handoff. `simplicio-loop` owns convergence and background scheduling; a missing or corrupt cache is never a reason to use stale context.
