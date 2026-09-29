# Optional uvloop rollout

simplicio_loop.event_loop treats uvloop as an optional Unix-only optimization.

- Windows always uses the standard asyncio policy.
- Unix uses uvloop only when the optional uvloop extra is installed and SIMPLICIO_LOOP_UVLOOP is not disabled.
- SIMPLICIO_LOOP_UVLOOP=0 is the rollback switch; auto is the default.
- Benchmark receipts include workload, throughput, p95, process CPU time/percent and peak RSS (resource or tracemalloc fallback).
- Reproduce a baseline with (receipts are no longer committed; the old ones were removed in 3.46.0, see git history):
  python scripts/benchmark_event_loop.py --iterations 1000 --workload gather --output event-loop-baseline.json
- A canary is explicit: run the same command with SIMPLICIO_LOOP_UVLOOP=1 on Unix, compare the JSON fields against the baseline, and enable only after review.
- Roll back immediately with SIMPLICIO_LOOP_UVLOOP=0; missing uvloop is always a safe fallback and never an installation error.

A baseline is not a claim of Unix uvloop performance; Unix canary evidence must be produced on Unix with the optional extra installed.

## Real Unix canary (#510)

The #510 canary was a real, non-simulated run on a Linux host with `uvloop` actually installed via
`pip install -e ".[uvloop]"` (its JSON receipt was removed in 3.46.0; see git history):

- `select_event_loop()` genuinely resolves to `name: "uvloop"` and the coroutine passed to `run()`
  is confirmed to execute on an actual `uvloop.Loop` instance (checked via
  `asyncio.get_running_loop()` inside the coroutine), not merely inferred from the selection flag.
- The fallback was verified the same way, for real: a separate venv had the project installed
  *without* the `uvloop` extra (`import uvloop` raises `ModuleNotFoundError` there), and
  `select_event_loop(enabled=True)` still resolves to `asyncio` / `uvloop_unavailable`, `run()`
  still executes the coroutine, and the full `tests/test_event_loop.py` +
  `tests/test_benchmark_event_loop.py` suite still passes in that clean venv. The
  never-obrigatório / fallback-comprovado invariant holds under a genuinely absent package, not
  just a mocked one.
- Recomputed throughput/p95/CPU/RSS numbers show uvloop **slower** than the default loop for this
  benchmark's `noop`/`gather` workloads: `scripts/benchmark_event_loop.py` calls `asyncio.run()`
  once per iteration, so every iteration pays uvloop's libuv construction/teardown cost instead of
  amortizing it across a long-lived loop, which is where uvloop's advantage normally shows up.
  This is a real methodology limit of the current microbenchmark, not a defect in the selection
  code — the receipt's `finding`/`recommendation` fields said the same. Rollout stays
  opt-in (`SIMPLICIO_LOOP_UVLOOP=auto`, default off unless the extra is present and not disabled);
  do not read this canary as a throughput win.
- `tests/test_event_loop.py::test_unix_falls_back_when_optional_extra_is_absent` used to rely on
  the *ambient* test environment not having uvloop installed to pass; it now hermetically forces
  `importlib.import_module("uvloop")` to raise instead, so the test is correct regardless of
  whether uvloop happens to be installed in the environment running it (it was not, until this
  real canary installed it — the previous version would have silently broken here).
