# Benchmarks

This page holds the benchmark tables of the loop. Each table has the exact command, the number of repetitions and the load of the host.

Labels:

- MEASURED: a tool read the number from the host.
- SIMULATED: the input of the number is a simulation. The text names the part.
- UNVERIFIED: nobody measured the number. The text gives the reason.

A cell shows the median, then the minimum and the maximum of all repetitions in parentheses. The page has no estimate.

## 1. Squads drain, with and without squads (SIMULATED)

This is part of #1549. The real drain with a model is not run here. It stays UNVERIFIED, and #1549 stays open for it.

### Run it

```bash
nice -n 10 python3 bench/benchmark_squads_drain.py --reps 5 --out result.json   # table on screen, JSON in the file
python3 bench/benchmark_squads_drain.py --reps 5 --json                          # JSON on screen
python3 -m pytest -q tests/test_benchmark_squads_drain.py                        # tests of the load generator, the metrics and a tiny drain
```

The script uses the standard library and the loop modules. It needs no network, no model and no git.

### What is real and what is simulated

| Part | Label | Source |
|---|---|---|
| Plan: squads, file ownership, merge order, start role | MEASURED (real code) | `watcher247.squad_flow.plan_repo`, `squads.plan_squads_auto`, `squad_routing.route` |
| Number of workers and squads | MEASURED (real code on the probe) | `squad_capacity.recommend` |
| Merge train | MEASURED (real code) | `merge_train.plan_train` and `merge_train.run_train` |
| Escalation rate, dependency wait | MEASURED (real code on simulated events) | `squad_metrics.task_record` and `summarize_records` |
| CPU time and memory of the orchestrator | MEASURED | `/proc/self/status` and `resource.getrusage` of the process that plans and drains |
| Load average | MEASURED | `os.getloadavg`, read before, during (every 0.25 s) and after |
| Task duration | SIMULATED | `asyncio.sleep`, uniform 0.2 to 1.5 s per attempt |
| First-attempt failure of 15% of the tasks | SIMULATED | Seeded. Exactly 6 of 40 tasks |
| Cost of one merge (0.10 s) and of one integration test of a batch (0.25 s) | SIMULATED | Constants, the same in every mode |
| Idle machine of the `idle` probe | SIMULATED | 10 cores, load 0, 64 GiB free, 500 GiB disk |

### The load

The seed is fixed (`--seed 1`). The same load runs in every mode.

- 40 tasks in a dependency graph with 5 levels. The levels have 9, 3, 10, 12 and 6 tasks, so the widest level has 12 tasks. There are 47 dependency edges. Each task above level 0 depends on 1 or 2 tasks of the level below. The dependencies use the real `depende de #N` syntax of an issue body.
- Each task owns one file. About 20% of the tasks also touch a second module (10 of 40 for seed 1). The real router starts those tasks at the coordination role.
- Each task has a first attempt and a second attempt. Each attempt lasts 0.2 to 1.5 s (SIMULATED, uniform). The first attempts add up to 33.0 s. The second attempts of the failing tasks add up to 4.5 s.
- 6 tasks (15%) fail the first attempt and go up one role. The second attempt then passes.
- A merge costs 0.10 s. One integration test costs 0.25 s.

### The modes

| Mode | What it is | Workers | Start role | Merge |
|---|---|---|---|---|
| `baseline` | The loop before squads | 1 | execution | Each PR is tested and merged before the next task starts |
| `squads-v2-off` | Squads with `SIMPLICIO_247_SQUADS_BASELINE=1`: auto size, but routing, merge batch and contracts are off | Auto (`squad_capacity`) | execution | Batch of 1. Workers do not wait for the merge |
| `squads` | Squads v2 | Auto (`squad_capacity`) | Router (execution or coordination) | Merge train, batch of up to 4. Workers do not wait for the merge |

The probe sets the machine that `squad_capacity` sees.

- `live`: the real host with the load that other jobs put on it (MEASURED).
- `idle`: a fixed idle host of 10 cores (SIMULATED). The workers are `floor(0.8 x 10)` = 8, because the demand is 12.

### How a drain runs

1. `plan_repo` plans the squads and the capacity.
2. A pool starts at most `total_workers` workers, in merge order. A freed slot starts the next worker at once.
3. A worker sleeps for the simulated duration. If the task fails once, the worker goes up one role and sleeps for the second attempt.
4. When the PR is ready, the clock records the instant (`ready_at`).
5. One writer merges. A PR is eligible when it is ready and each dependency is merged or in front of it in the same batch. The writer takes the eligible PRs in merge order and runs `run_train` for the first `merge_batch` of them. It records the instant of each merge (`merged_at`).
6. The wait of a task is the gap from its `ready_at` to the last merge of its dependencies. Tasks without dependency are out of the mean.

The harness runs every repetition in a fresh process. It runs the modes in turn inside each repetition, so all modes see the same drift of the host load. It waits while load1 is above 8, for 10 minutes at most in total, and then measures whatever the load is.

### Result

Not measured yet. All benchmarks were frozen while the host load was 11 to 18 (release work). The table is added after a run on a quiet host. Until then every number of the squads drain is UNVERIFIED.

### Limits

- The task durations are SIMULATED. This is not a real drain with a model. The real comparison of #1549 stays UNVERIFIED.
- The executor is an asyncio model of the rules. It is not the watcher tick. The real tick takes a repo lock for the whole run of a worker (`tick.process`), so on one repo it runs one worker at a time. The model describes the `/simplicio-loop` squads flow. It has one worktree per worker, workers in parallel and one writer for the merge.
- A dependency orders the merge only. A worker never waits for the merge of its dependency. This is what `plan_squads` does. The contracts of v2 make it safe in a real drain. The model does not test that.
- The tasks that fail are the same in every mode. The model does not test whether routing avoids a failure. For that reason the escalation rate is 15% by construction in every mode. The start roles show what the real router does.
- The merge cost and the test cost are constants, and their size sets the result. The writer is the limit when the batch is 1.
- The `idle` probe is a fixed synthetic machine. Real workers use CPU and memory, and the model does not. The CPU time in the table is the CPU time of the orchestrator only.
- With `live`, a host load near the core count gives 1 worker (the `load` limit of `squad_capacity`). The number of workers chosen is in the table. With 1 worker, `squads` and `baseline` differ in the merge train only.
- The load average is a value of the whole host and other jobs dominate it. The peak RSS includes the interpreter and the imports.
- One seed. Repetitions with the same seed show the spread of scheduling and of the host load. They do not show the spread caused by the shape of the load.

## 2. Existing benchmarks, run again on `main`

The files are the ones of `main` at `3f5fd701`. Nothing was changed. Each benchmark ran 5 times, one process per repetition, one benchmark at a time, with `nice -n 10`. The host has 10 cores, Linux 7.0 and Python 3.14.4. Other jobs loaded the host, and the load1 range is in the table.

| Benchmark | Command | Result, median (min-max) of 5 | Load1 during | Label |
|---|---|---|---|---|
| Merge train (#1543), 8 PRs, all good | `python3 scripts/benchmark_merge_train.py --n 8 --repeats 1` | Serial 10 848 ms (8 917-11 385). Train 3 100 ms (2 677-4 124). Serial / train per run: 3.05 (2.73-4.25). Smoke runs 8 against 2. | 8.89-10.28 | MEASURED |
| Merge train (#1543), 8 PRs, 2 bad | `python3 scripts/benchmark_merge_train.py --n 8 --bad 2 --repeats 1` | Serial 9 532 ms (8 239-15 714). Train 12 657 ms (10 086-20 217). Serial / train per run: 0.78 (0.72-0.92). Smoke runs 8 against 8, 6 bisect steps. The train is slower than serial when 2 of 8 PRs fail. | 8.89-14.88 | MEASURED |
| Dashboard (#1540) | `python3 -m simplicio_loop.dashboard.bench --runs 50 --events 10000 --idle-seconds 30 --json` | List of runs 5 652 ms (4 760-6 561). Run detail 149 ms (107-202). SSE replay 3 525 ms (2 754-5 781), 10 000 of 10 000 frames each time. Idle CPU 4.6% (3.5-12.6) over 30 s. RSS after the run 59.0 MiB (58.9-59.2). | 10.98-13.55 | MEASURED |
| Local task queue (#889), default sizes | `python3 bench/benchmark_local_task_queue_889.py` | Did not finish. One run was stopped after more than 400 s. The limit for this table is 2 minutes. | not recorded | UNVERIFIED |
| Local task queue (#889), `--sizes 1,10,100` | `python3 bench/benchmark_local_task_queue_889.py --sizes 1,10,100` | Each run took 153-181 s and returned exit code 1. Both thresholds (30 000 us per operation) failed in all 5 runs. Enqueue per operation: 20.7 ms (12.5-44.6) at 1 task, 26.4 ms (21.1-49.1) at 10, 215.5 ms (179.0-233.4) at 100. Claim per operation: 27.0 ms (16.5-43.6), 39.1 ms (31.0-61.9), 1 441 ms (1 282-1 579). | 10.98-18.95 | MEASURED |
| Generation broker (#888) | `python3 bench/benchmark_generation_broker_888.py` | Cold 9.6 ms (8.1-19.0). Warm total 687.5 ms (654.0-1 580.2). Uncached 1 285.5 ms (1 159.0-2 016.8). Time saved 484.4 ms (0-1 317.0). 99 cache hits of 100 and 2 builds in all runs. Threshold `positive_savings` failed in 1 of 5 runs (saved 0 ns, exit code 1). | 14.01-14.36 | MEASURED |

Reading the table:

- The dashboard target of #1400 is an idle CPU below 2% and a RAM below 80 MB. RAM passes. The idle CPU of 4.6% does not pass on this loaded host. `docs/DASHBOARD.md` records 0.23% on a quiet host.
- The queue cost per operation grows with the number of queued tasks. At 100 tasks the claim costs about 1.4 s per operation on this host.
- The timings are those of a loaded host. Use them to compare the modes inside one table, not as absolute values.

## 3. UNVERIFIED

| Item | Reason |
|---|---|
| Drain with a real model and real GitHub (#1549) | No run exists. The squads drain above is a simulation. |
| Escalation rate and dependency wait of a real drain | Same reason. The squads table only checks that the metrics code works on simulated events. |
| Dashboard bench on Windows and macOS | A person must run the command on those systems (`docs/DASHBOARD.md`). |
| Local task queue with the default sizes | It does not finish in 2 minutes on this host. |
| Squads drain table | Waiting for a quiet host. See the Result section. |
