# Issue #346 governed advisory receipt

`benchmarks/bench_capability_governed_346.py` collects the installed Loop
preflight, Fast capability manifest and Runtime contract smoke manifest. It
accepts policy and health only from separately supplied owner receipts with
`status=verified`; malformed, unverified or Fast-owned receipts fail closed.

The generated `simplicio.fast.capability-rank-receipt/v1` keeps the catalog
content-addressed, records the accepted owner facts and preserves
`authority=advisory_only`. It records `dispatch.performed=false`: Fast ranks
facts but never authorizes or dispatches a worker, tool or model. Cross-scope
owner facts are ignored by the ranking request, and secret-like fields are
excluded from the output.

Generate a receipt from installed consumers with:

```text
python benchmarks/bench_capability_governed_346.py `
  --repo . `
  --runtime C:\Users\Z0059V7A\.local\simplicio-runtime\bin\simplicio.exe `
  --policy fixtures/delivery/v1/issue346-governed-receipts.json `
  --health fixtures/delivery/v1/issue346-governed-receipts.json `
  --json-out benchmarks/results/issue346-governed-windows-20260802.json
```
