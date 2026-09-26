# Release qualification evidence — 2026-09-11

**Conclusion: the requested comparative benchmark is incomplete. No winning flow is proven.**
The release cannot currently admit the fixture on this host's measured capacity.
Do not convert this qualification report into a claim that every flow ran.

## Current native rerun addendum (16:27 UTC)

The requested flow probes were executed again against the same ten-issue private
fixture, with `SIMPLICIO_STORAGE_ROUTE=mapper`, the OpenRouter model
`deepseek/deepseek-v4.1-flash`, and the installed Loop release `3.43.10`. Mapper is
mandatory in every eligible row below and is intentionally omitted as a repeated table
row. These are receipt-backed measurements; provider fields are `UNAVAILABLE` when the
Loop stopped before an LLM call.

| Flow/configuration | Ten-task delivery | Wall s | Child CPU s | Peak RSS MiB | Measured outcome | Receipt |
|---|---:|---:|---:|---:|---|---|
| `run --delivery implemented --max-iterations 1` | 0/10 (one-task intake probe) | 7.592 | 6.579 | 175.5 | `exit=20`, blocked by physical capacity/disk pressure | [receipt](../.simplicio-loop/benchmark/qualification-run-current-GH102/receipt.json) |
| `batch` automatic (`max-workers=0`) | 0/10 | 0.465 | 0.294 | 43.6 | `run is not runnable: blocked` | [receipt](../.simplicio-loop/benchmark/qualification-batch-auto-current/receipt.json) |
| `batch --serial` | 0/10 | 0.343 | 0.264 | 50.0 | same blocked run; no worker dispatched | [receipt](../.simplicio-loop/benchmark/qualification-batch-serial-current/receipt.json) |
| `batch --batch-size 10` (Prism wave width 10) | 0/10 | 0.457 | 0.290 | 43.8 | same blocked run; no wave dispatched | [receipt](../.simplicio-loop/benchmark/qualification-batch-wave10-current/receipt.json) |
| `batch --batch-size 30` (wide wave) | 0/10 | 0.343 | 0.284 | 41.5 | same blocked run; no wave dispatched | [receipt](../.simplicio-loop/benchmark/qualification-batch-wave30-current/receipt.json) |
| `tick --task-index 1` | 0/10 | 1.250 | 0.999 | 75.8 | `STALE_FENCE`; mutation rejected | [receipt](../.simplicio-loop/benchmark/qualification-tick-current/receipt.json) |
| `tasks run --dry-run` installed release | 0/10 | 0.345 | 0.233 | 40.0 | `ValueError: agent command is required`; no plan | [receipt](../.simplicio-loop/benchmark/qualification-tasks-release-dry/receipt.json) |
| `tasks run --dry-run` checkout entrypoint | 0/10 | 10.479 | 2.064 | 88.2 | 10 issues planned, `PLANNED_NOT_EXECUTED`; no delivery | [receipt](../.simplicio-loop/benchmark/qualification-tasks-checkout-entrypoint-dry/receipt.json) |
| Prism arm: `arm_drain_prism.py --slots 0 --batch-size 10` | 0/10 (arm only) | 2.882 | 1.255 | 87.4 | eligible, selected 2 slots / logical capacity 20; no worker | [receipt](../.simplicio-loop/benchmark/qualification-prism-arm/receipt.json) |

`wave` is not a top-level command in `3.43.10`; `simplicio-loop wave --help` returned
`invalid choice`, and the real wave surface is `batch --batch-size N`. “Serial” is the
`batch --serial` lane. “Legado limitado” was exercised through the read-only
`queue --route legacy status/doctor` compatibility surface; it does not represent a
ten-task delivery flow. Mapper queue health (`status/top/doctor`) and legacy health
completed in about 0.34–0.36 s with ~39–43 MiB RSS, but are inspection commands, not
delivery candidates. The `drain evaluate/persist/load`, `single-task-fast`,
`hub-drain-plan`, and `hub-drain-admit` probes likewise produced fail-closed control
receipts, not task delivery.

### What can and cannot be ranked

The raw shortest stop was `batch --serial` and `batch --batch-size 30` at 0.343 s,
but both stopped because the same run was already blocked. This is a time-to-rejection
observation, not a speed or cost win. No native flow delivered even one of the ten
tasks, so native 10-task p50/p99, input/output/reasoning/cache tokens, and OpenRouter
cost are `UNAVAILABLE`, not zero. The two Fast preflight checks (Fast on: 5.540 s;
Fast off: 4.254 s) also cannot rank delivery because they were preflight-only.

The only completed 10/10 behavioral result remains the earlier composed diagnostic
(Mapper → OpenRouter worker proposals → native edit → independent oracle), which is
not a native `run`/`batch`/Prism/wave/legacy arm: 11 provider calls, 35,654 input
tokens, 4,694 output tokens, 3,916 reasoning tokens (subset), 1,920 cached-input
tokens observed by the provider, reported cost US$0.01576452, provider-response p50
3.509 s and p99 5.653 s. It must remain a non-comparable diagnostic, not the Loop
default.

### Execution inventory for this rerun

Executed and receipt-backed: `run`; automatic `batch`; `batch --serial`; wave widths
10 and 30; `tick`; release and checkout `tasks run --dry-run`; Prism arm; Mapper and
legacy queue health; `drain evaluate/persist/load`; `single-task-fast`; GitHub
`hub-drain-plan` and `hub-drain-admit`; Fast on/off preflight; plus the 107-invocation
help coverage sweep. OpenRouter/model environment was passed to every provider-capable
probe, but the physical admission gate stopped the native mutation paths before a
provider call. The current central Mapper preparation itself took 9.669 s (10 task
records), snapshot build took 0.350 s, and the Mapper → Fast handoff remained degraded
because the canonical Fast artifact was unavailable; an integrated Fast build also
rejected the legacy Mapper handoff schema. Those are integration qualification results,
not delivery winners. Full receipts are under `.simplicio-loop/benchmark/`.

### Current decision

There is no defensible fastest/economical native configuration from this rerun. The
standard remains: central Mapper preparation → bounded Fast context when available →
Runtime capacity admission → automatic Prism `batch` with the machine-recommended
worker count and wave size → reconcile/verify. Use `--serial` only for a deliberate
diagnostic or when the receipt says Prism is ineligible. Do not override the physical
governor to force a ranking; rerun the same matrix after the project volume is below
the admission threshold and require 10/10 receipts plus provider usage/cost before
choosing a winner.

| Requested flow | Current evidence | Eligible for ranking? |
|---|---|---|
| `run` | Real CLI, Mapper ready, execution blocked by capacity, watcher rejected completion | No |
| `batch --serial` | Real CLI and recovery, zero completed tasks, disk-pressure refusal | No |
| automatic `batch` | Interface discovered; no completed equal-work arm | No |
| `tasks run` | Release dry-run defect; corrected checkout reads 10 live issues without executing them | No |
| Prism | Routing/arming and source examined; no completed real-worker comparative arm | No |
| wave | Batch-width interface examined; no completed equal-work arm | No |
| limited legacy | Synthetic semaphore control identified; not a completed real-worker arm | No |
| Mapper plus Fast variants | Not completed under an identical seed and completion oracle | No |

The prior [paid diagnostic report](QUEUE_BENCHMARK_PROTOCOL.md) and
[graphs](../.lavish/queue-benchmark-20260911/report.html) remain available,
but their measurements must not be relabeled as these comparison arms.


## Dependency repair and recovery probes

Installed `psutil==7.2.2` into the global Python 3.14 environment without changing Loop 3.43.10. The provider key presence check returned true; no key content was printed or persisted.

### qualification-tasks-release-dry

Wall 0.345 s; child CPU 0.233 s; sampled peak RSS 40.05 MiB; exit 2.

Working directory: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T151422687497Z/fixture`.

```sh
simplicio-loop tasks run --dry-run --workspace . "finish all open issues in wesleysimplicio/simplicio-loop-benchmark-20260911"
```

[Receipt](../.simplicio-loop/benchmark/qualification-tasks-release-dry/receipt.json), [stdout](../.simplicio-loop/benchmark/qualification-tasks-release-dry/stdout.txt), [stderr](../.simplicio-loop/benchmark/qualification-tasks-release-dry/stderr.txt).

### qualification-resume-psutil-GH102

Wall 0.462 s; child CPU 0.350 s; sampled peak RSS 40.63 MiB; exit 0.

Working directory: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T151422687497Z/fixture`.

```sh
env SIMPLICIO_STORAGE_ROUTE=mapper SIMPLICIO_MODEL=deepseek/deepseek-v4.1-flash SIMPLICIO_PLANNER=openrouter/deepseek/deepseek-v4.1-flash SIMPLICIO_BASE_URL=https://openrouter.ai/api/v1 SIMPLICIO_LOG_ROOT=/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/provider-qualification-resume simplicio-loop resume --repo . run-20260911-152024-1bat3hs6
```

[Receipt](../.simplicio-loop/benchmark/qualification-resume-psutil-GH102/receipt.json), [stdout](../.simplicio-loop/benchmark/qualification-resume-psutil-GH102/stdout.txt), [stderr](../.simplicio-loop/benchmark/qualification-resume-psutil-GH102/stderr.txt).

### qualification-batch-psutil-GH102

Wall 0.690 s; child CPU 0.527 s; sampled peak RSS 45.08 MiB; exit 0.

Working directory: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T151422687497Z/fixture`.

```sh
env SIMPLICIO_STORAGE_ROUTE=mapper SIMPLICIO_MODEL=deepseek/deepseek-v4.1-flash SIMPLICIO_PLANNER=openrouter/deepseek/deepseek-v4.1-flash SIMPLICIO_BASE_URL=https://openrouter.ai/api/v1 SIMPLICIO_LOG_ROOT=/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/provider-qualification-batch-psutil simplicio-loop batch --serial --repo . run-20260911-152024-1bat3hs6
```

[Receipt](../.simplicio-loop/benchmark/qualification-batch-psutil-GH102/receipt.json), [stdout](../.simplicio-loop/benchmark/qualification-batch-psutil-GH102/stdout.txt), [stderr](../.simplicio-loop/benchmark/qualification-batch-psutil-GH102/stderr.txt).

The recovered serial batch measured 1,864,237,056 available RAM bytes and 20,781,002,752 free disk bytes. Admission still rejected execution: `PHYSICAL_CAPACITY_PRESSURE` / `disk_pressure`, against a 21,474,836,480-byte reserve. It returned exit zero but `completed_task_indices=[]`, `blocked_task_indices=[1]`, and a non-ready receipt contract. Exit zero therefore does not establish successful task execution. The earlier missing-RAM worker record is retained historical evidence, not the new capacity sample.

The native `run` advanced to watcher verification although its batch contained blocked rather than failed tasks. The watcher correctly refused completion. Both the run transition and batch exit semantics need qualification before unattended benchmarking.

The reconciled interface pass executed **107 help invocations**, including forwarded `tasks` and `tasks run`; all returned successfully. [Complete command inventory](../.simplicio-loop/benchmark/help-coverage-reconciled-20260911/coverage.json). This is **zero workflow executions** in that help pass and does not establish coverage of every semantic flag combination.

Focused local verification: `tests/test_tasks_cli.py`, `tests/test_tasks_live.py`, `tests/test_tasks_dry_run.py`, and `tests/test_benchmark_help_discovery.py`: **13 passed**. The complete repository gate has not passed; these tests do not qualify all unrelated dirty changes.

## Checkout dry-run and final focused checks

The corrected checkout's real CLI entry point successfully read all ten live
GitHub issues. Its receipt explicitly reports `PLANNED_NOT_EXECUTED`, no delivery
evidence, and unmeasured provider tokens/cost. This qualifies read-only intake,
not implementation. [Command and resource receipt](../.simplicio-loop/benchmark/qualification-tasks-checkout-entrypoint-dry/receipt.json)
and [full intake result](../.simplicio-loop/benchmark/qualification-tasks-checkout-entrypoint-dry/stdout.txt).
An earlier `python -m simplicio_loop` attempt failed because the package has no
`__main__`; [failed invocation receipt](../.simplicio-loop/benchmark/qualification-tasks-checkout-dry/receipt.json).

The generated intake currently lists no dependencies for any issue, including
GH-104, whose benchmark oracle requires GH-102. Its derived criteria reference
issue titles rather than preserving the detailed behavioral oracle. This intake
must be reconciled with the frozen benchmark contract before a paid tasks-run
comparison is admissible.

Final focused command:

```sh
.simplicio-loop/benchmark/telemetry-venv/bin/python -m pytest tests/test_tasks_cli.py tests/test_tasks_live.py tests/test_tasks_dry_run.py tests/test_benchmark_help_discovery.py tests/test_arm_prism_auto_capacity.py tests/test_benchmark_resource_sampler.py tests/test_benchmark_diagnostic_summary.py tests/test_benchmark_proposal_bridge.py tests/test_benchmark_repair_guard.py -q
```

Result: **30 passed, 4 warnings in 2.25 seconds**. `git diff --check` also passed.
This remains focused qualification, not a passing full repository gate, release,
or proof of a fastest/cheapest workflow.

These are failed qualification probes, not completed ten-task benchmark arms. No fastest or cheapest flow can be selected from time-to-failure. The earlier paid diagnostic report remains separate.

## Measured probes

| Probe | Wall seconds | Child CPU seconds | Sampled peak RSS MiB | Exit | Result |
|---|---:|---:|---:|---:|---|
| qualification-run-GH102 | 11.244 | 7.263 | 170.98 | 20 | watcher_unavailable; operator remained dry_run |
| qualification-run-watcher-GH102 | 4.636 | 3.587 | 142.09 | 20 | mapping_failed during background index |
| qualification-run-fresh-GH102 | 7.743 | 6.551 | 191.84 | 20 | watcher_failed; zero execution attempts |
| qualification-batch-serial-GH102 | 0.339 | 0.259 | 42.39 | 1 | run is not runnable: blocked |

Machine: 8 logical CPUs, 8 GiB RAM, macOS 26.3 arm64. Sampling interval: 100 ms. CPU is reaped-child user+system time; RSS sums may double-count shared pages and miss short peaks. These are not model latency measurements. Missing provider usage/cost is unavailable, not zero.

## Exact commands and evidence

### qualification-run-GH102

Working directory: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T151422687497Z/fixture`.

```sh
env SIMPLICIO_STORAGE_ROUTE=mapper SIMPLICIO_MODEL=deepseek/deepseek-v4.1-flash SIMPLICIO_PLANNER=openrouter/deepseek/deepseek-v4.1-flash SIMPLICIO_BASE_URL=https://openrouter.ai/api/v1 simplicio-loop run --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T151422687497Z/GH-102.md --repo . --delivery implemented --max-iterations 1
```

[Resource receipt](../.simplicio-loop/benchmark/qualification-run-GH102/receipt.json), [stdout](../.simplicio-loop/benchmark/qualification-run-GH102/stdout.txt), [stderr](../.simplicio-loop/benchmark/qualification-run-GH102/stderr.txt).

### qualification-run-watcher-GH102

Working directory: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T151422687497Z/fixture`.

```sh
env SIMPLICIO_STORAGE_ROUTE=mapper SIMPLICIO_MODEL=deepseek/deepseek-v4.1-flash SIMPLICIO_PLANNER=openrouter/deepseek/deepseek-v4.1-flash SIMPLICIO_BASE_URL=https://openrouter.ai/api/v1 SIMPLICIO_LOG_ROOT=/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/provider-qualification-watcher simplicio-loop run --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T151422687497Z/GH-102.md --repo . --delivery implemented --max-iterations 1
```

[Resource receipt](../.simplicio-loop/benchmark/qualification-run-watcher-GH102/receipt.json), [stdout](../.simplicio-loop/benchmark/qualification-run-watcher-GH102/stdout.txt), [stderr](../.simplicio-loop/benchmark/qualification-run-watcher-GH102/stderr.txt).

### qualification-run-fresh-GH102

Working directory: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T151422687497Z/fixture`.

```sh
env SIMPLICIO_STORAGE_ROUTE=mapper SIMPLICIO_MODEL=deepseek/deepseek-v4.1-flash SIMPLICIO_PLANNER=openrouter/deepseek/deepseek-v4.1-flash SIMPLICIO_BASE_URL=https://openrouter.ai/api/v1 SIMPLICIO_LOG_ROOT=/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/provider-qualification-fresh simplicio-loop run --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T151422687497Z/GH-102.md --repo . --delivery implemented --max-iterations 1
```

[Resource receipt](../.simplicio-loop/benchmark/qualification-run-fresh-GH102/receipt.json), [stdout](../.simplicio-loop/benchmark/qualification-run-fresh-GH102/stdout.txt), [stderr](../.simplicio-loop/benchmark/qualification-run-fresh-GH102/stderr.txt).

### qualification-batch-serial-GH102

Working directory: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T151422687497Z/fixture`.

```sh
env SIMPLICIO_STORAGE_ROUTE=mapper SIMPLICIO_MODEL=deepseek/deepseek-v4.1-flash SIMPLICIO_PLANNER=openrouter/deepseek/deepseek-v4.1-flash SIMPLICIO_BASE_URL=https://openrouter.ai/api/v1 SIMPLICIO_LOG_ROOT=/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/provider-qualification-batch simplicio-loop batch --serial --repo . run-20260911-152024-1bat3hs6
```

[Resource receipt](../.simplicio-loop/benchmark/qualification-batch-serial-GH102/receipt.json), [stdout](../.simplicio-loop/benchmark/qualification-batch-serial-GH102/stdout.txt), [stderr](../.simplicio-loop/benchmark/qualification-batch-serial-GH102/stderr.txt).

## Fixture and corrections

Private test repository: https://github.com/wesleysimplicio/simplicio-loop-benchmark-20260911. Ten requirement issues were created; they are not evidence of completed deliveries. Seed revision after binding the installed watcher: `d1d9ca48a90936cbd78839d58c8e2c68652352d4`.

The watcher binding invokes the unchanged installed 3.43.10 producer and verifies SHA-256 `02f6f990f720e260193314fd52a13cd46a1050eb9f36ae5acd12863a005baf37`. No watcher evidence was fabricated. The first post-binding run caught Mapper while its background index was active; a subsequent central scan/inspection established freshness before the next attempt. The next attempt passed Mapper but failed independent verification with zero execution attempts.

`tasks run --dry-run` also fails in the installed release because it constructs an agent pipeline with an empty agent command. A checkout-only correction passed nine focused tests; this is not an installed release fix. Preserve release and patched-checkout results separately.

## Decision

Do not publish a fastest/cheapest default yet. Keep Mapper mandatory, stable certified context prefixes, dependency-aware admission, physical backpressure and independent behavioral validation. A cache request is not proof of a provider cache hit. Require observed provider usage and equal completion boundaries before ranking flows. All combinations have not been executed; help coverage is interface discovery only.
