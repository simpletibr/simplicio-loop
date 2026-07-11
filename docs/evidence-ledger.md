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
Receipts with a different `base_sha` or `plan_hash` are rejected as stale. Missing claims remain
`UNVERIFIED`; the ledger never promotes a claim based on a missing or mismatched artifact.
