# Loop-owned agent slots

`simplicio_loop.agent_slots` is the Loop-owned lifecycle boundary for
multi-agent lanes. The default CLI route is MapperStore-backed and persists in
the repo-scoped `operations.sqlite`; the old local SQLite registry remains
available only through the explicit `--route legacy` compatibility route.

The default capacity is six. `pending` and `running` consume capacity;
`completed` and `shutdown` release it immediately while remaining visible for
audit; `reclaimable` is a derived, idempotent post-cleanup capability on those
terminal records. Status returns counts
for all states, current holders, available capacity, and blockers for
descendants, worktrees, or leases.

The CLI surface is JSON-first:

```text
python -m simplicio_loop.cli agent-slots status --repo . --mapper-db .simplicio-loop/data/operations.sqlite
python -m simplicio_loop.cli agent-slots acquire agent-a --repo . --mapper-db .simplicio-loop/data/operations.sqlite --mapper-init
python -m simplicio_loop.cli agent-slots start agent-a --repo . --mapper-db .simplicio-loop/data/operations.sqlite
python -m simplicio_loop.cli agent-slots close agent-a --status completed --repo . --mapper-db .simplicio-loop/data/operations.sqlite
python -m simplicio_loop.cli agent-slots reclaim --repo . --mapper-db .simplicio-loop/data/operations.sqlite
```

For a legacy database during the migration window, pass
`--route legacy --db .simplicio-loop/orchestrator/agent-slots.sqlite` explicitly.

`spawn_batch` is the programmatic seam for a real adapter. It retries a failed
spawn at most `retry_limit` times, reuses the same logical agent record, and
never creates a duplicate slot. No operation starts a local LLM.
