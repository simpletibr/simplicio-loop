# Evidence ledger

`simplicio.evidence_ledger.EvidenceLedger` is the append-only AC/RN evidence surface for governed runs.
It stores one JSON object per receipt and returns a consumable claim matrix:

```python
from simplicio.evidence_ledger import EvidenceLedger

ledger = EvidenceLedger(".simplicio/evidence.jsonl", base_sha=base_sha, plan_hash=plan_hash)
ledger.record(criterion_id="AC1", command="pytest tests/e2e/ac1.py", exit_code=0, artifact="artifacts/ac1.json")
matrix = ledger.matrix(["AC1", "AC2"])
```

`MEASURED` receipts require a successful command and an artifact whose SHA-256 is checked before append.
Every receipt also carries the frozen `commit_sha`, base SHA, plan hash, timestamp, environment, and
optional `prototype`/`attachments` metadata; each attachment is captured with its own SHA-256 and is revalidated by the watcher. Receipts with a different commit, `base_sha`, or `plan_hash` are rejected as stale. Missing claims remain
`UNVERIFIED`; the ledger never promotes a claim based on a missing or mismatched artifact.

`matrix()` now revalidates every stored `MEASURED` receipt before reporting success. If the artifact
disappeared or its digest changed (for example, a screenshot from the wrong scenario replaced the
original file), the claim is demoted back to `UNVERIFIED` and exposed under
`claims.<AC>.invalid_receipts` plus the top-level `watcher.failures` list.

Use `ledger.watch(criteria)` for the independent final watcher pass; it rereads and rehashes the
append-only ledger and returns the same JSON-safe matrix consumed by the loop journal, runtime, and MCP. A stale receipt or changed screenshot/trace/video attachment is reported as a watcher failure and cannot remain `MEASURED`.
