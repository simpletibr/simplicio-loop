# Typed attempt journal

`simplicio_loop.attempt_journal.AttemptJournal` is the machine-facing journal for one
`run_id/work_item_id/attempt_id`. It complements the human-readable
`scripts/loop_journal.py` file and is safe to ship to Runtime or another host.

Each JSONL row uses `simplicio.loop-observation/v1` and contains a typed `kind`:
`hypothesis`, `action`, `tool_execution`, `validation`, `failure`, `observation`, or
`decision`. Rows carry actor and causation identity, acceptance-criterion IDs, a
`MEASURED|UNVERIFIED|ESTIMATED` claim class, and a SHA-256 chain. Appending the same
`event_id` and envelope is idempotent; changing its payload fails closed.

```python
from simplicio_loop.attempt_journal import AttemptJournal, build_observation

journal = AttemptJournal(".simplicio-loop/orchestrator/loop/attempts.jsonl")
journal.append(build_observation(
    run_id="run-1", work_item_id="WI-1", attempt_id="A-1",
    actor="codex@host-a", kind="validation", sequence=1, event_id="evt-1",
    claim_type="MEASURED", ac_ids=["AC-1"], payload={"exit_code": 0},
))
exported = journal.export()       # verified, canonical envelopes
journal.import_events(exported)   # idempotent on a receiving host
```

`import_legacy()` migrates existing `journal.jsonl` rows without modifying the source.
Failure rows include a stable `failure_fingerprint`, so a resumed attempt or provider
handoff can detect an identical failure instead of treating it as a new strategy.
