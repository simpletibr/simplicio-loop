# Issue #348 installed consumer receipt

`benchmarks/bench_installed_sdk_348.py` invokes the installed
`simplicio-fast` console entry point and records the real bounded Python
consumer flow from `installation.python_smoke()`: capability selection,
build, query, context, plan, delivery and refresh. It requires the launcher to
report the checkout version and records all raw step receipts.

Run from the checkout root:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
python benchmarks/bench_installed_sdk_348.py --json-out benchmarks/results/issue348-windows-installed-20260802.json
```

This is a Windows installed Python evidence lane. The receipt intentionally
records Rust as not loaded and leaves Rust/session parity, backpressure and
cancellation, cross-platform artifacts, and upgrade/rollback receipts as
residual acceptance criteria.
