# Issue #349 fault-injection receipt

`benchmarks/bench_security_faults_349.py` runs eight deterministic cases across
the current Semantic Compute boundaries: baseline packet acceptance, forged
authority, instruction boundary, private mmap layout field, cross-scope packet,
payload digest tampering, revoked Knowledge fact and corrupt rollout state.

Each rejection is matched to its typed reason code. The revoked-fact case is
expected to return no handle; it is not treated as an exception because the
projection correctly removes revoked content from authoritative results.

Run from the checkout root:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
python benchmarks/bench_security_faults_349.py --json-out benchmarks/results/issue349-windows-faults-20260802.json
```

The receipt is a local fault-injection gate only. Installed-consumer E2E, Rust
parity, resource benchmarks and final rollout receipts remain explicit residuals
for #349.
