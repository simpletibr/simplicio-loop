# Wave10 smoke test (issue #1298 test item)

10-task wave through the real `orient` -> `prepare` -> per-task edit-plans ->
`wave` -> `verify` flow, run against a throwaway git repo under
`/tmp/claude-0/-home-user/0ec94cd2-06f4-56a2-844e-a9f409b7dfea/scratchpad/wave10`
(a tiny `calc/ops.py` package + `tests/test_ops.py`), driving
`simplicio-loop` from this worktree
(`PYTHONPATH=/home/user/wt/i1298:/home/user/wt/i1298/packages/mapper:/home/user/wt/i1298/packages/dev-cli:/home/user/wt/i1298/packages/fast/src`).

The task file declared 10 `Type: Feature` tasks, each adding one arithmetic
helper (`subtract`, `multiply`, `divide`, `modulo`, `power`, `is_even`,
`is_odd`, `maximum`, `minimum`, `average`) plus its test, all editing the same
two files (`calc/ops.py`, `tests/test_ops.py`) -- one shared lane, full
Unit/Integration/System/Regression/Benchmark/Coverage lane matrix declared
per task (no `Type: Docs|Chore|Config`/`Tests: none` shortcut).

## First attempt: BLOCKED, and the loop bug it found

The first run (`run-20260926-054721-gckyouu6`) blocked with
`plan_find_not_found` on task 10's edit plan. Root cause (see "Loop bug found
and fixed" below): `PrismScheduler.ready_set()` broke ties on the raw
`task_id` string, so `"...-task-10"` sorted before `"...-task-2"` and was
admitted second instead of tenth -- its find text (built on the cumulative
state through task 9) did not match the tree as it stood after only task 1.
Fixed with a regression test first (TDD), then the repo was reset and a fresh
run repeated the whole flow end to end.

## Commands run (second, successful attempt)

```bash
export PYTHONPATH=/home/user/wt/i1298:/home/user/wt/i1298/packages/mapper:/home/user/wt/i1298/packages/dev-cli:/home/user/wt/i1298/packages/fast/src
cd /tmp/.../scratchpad/wave10

python3 -m simplicio_loop.cli orient --task "add ten small arithmetic helper functions to calc/ops.py with tests" --json

python3 -m simplicio_loop.cli prepare --task tasks.md --repo .
# -> run_id = run-20260926-055332-vay4bxvk

# edit-plan-1.json .. edit-plan-10.json written under
# .simplicio-loop/loop-runs/run-20260926-055332-vay4bxvk/, each a
# {"operations": [...]} find/replace pair against calc/ops.py and
# tests/test_ops.py, computed against the exact cumulative file content the
# previous task's plan leaves (single shared lane -> strictly sequential).

python3 -m simplicio_loop.cli wave run-20260926-055332-vay4bxvk --repo . --serial
# -> status: VERIFIED (wall time: 1m02s)

python3 -m simplicio_loop.cli verify run-20260926-055332-vay4bxvk --repo .
# -> state.phase: done, completion.verdict: VERIFIED, tag: MEASURED
```

`--serial` was used throughout (single heavy command at a time on this
low-CPU machine); the run's own capacity admission independently capped
concurrency to 1 worker anyway once it saw all 10 tasks share one file
(`serial_fallback_reason: "shared_run_state"`).

## Final `verify` result (excerpt)

```json
{
  "manifest": {
    "run_id": "run-20260926-055332-vay4bxvk",
    "task_count": 10,
    "delivery_target": "verified"
  },
  "state": {
    "phase": "done",
    "attempts": 10,
    "blockers": [],
    "completion": {
      "ready": true,
      "verdict": "VERIFIED",
      "reason_code": "watcher_and_delivery_verified",
      "tag": "MEASURED"
    },
    "delivery": {
      "target": "verified",
      "current_state": "verified",
      "ready": true
    }
  }
}
```

`quality-matrix.json` for the run: `implementation`, `unit`, `integration`,
`system`, `regression`, `benchmark` all `"status": "pass"`; `coverage.measured
= 100.0` (`python3 -m pytest -q --cov=calc --cov-report=term tests`).

## Result

- run_id: `run-20260926-055332-vay4bxvk`
- phase: `done`
- completion: `VERIFIED` / tag `MEASURED`
- wall time (`wave --serial`): **1m 02s**
- all 10 functions present in `calc/ops.py` and exercised by
  `tests/test_ops.py`, coverage 100%.

## Loop bug found and fixed

`simplicio_loop/prism_scheduler.py::PrismScheduler.ready_set()` used
`task.task_id` (a plain string) as the final tiebreaker when several ready
tasks tie on served-count/priority/slot. Task ids in this flow are
`f"{run_id}-task-{index}"`; once a wave has 10+ tasks sharing one file (one
serial lane, `effective_workers=1`), string comparison orders `"...-task-10"`
ahead of `"...-task-2"` through `"...-task-9"`, so `next_batch()` admitted
task 10 second. Its edit plan's `find` text (built against the state after
task 9) then failed to match the tree as it stood after only task 1
(`plan_find_not_found`), and the run blocked permanently (blocked is
terminal; a fresh `prepare` was needed for the retry).

Fix (`simplicio_loop/prism_scheduler.py`): record a monotonic submission
sequence number per `task_id` in `PrismScheduler.submit()`
(`self._sequence[task.task_id] = len(self._sequence)`) and use that instead
of the raw `task_id` string as `ready_set()`'s final sort key. Submission
order (which is task-index order for a `wave` run) is preserved regardless of
how many digits the trailing index has.

Regression test (TDD, red before the fix): `test_ready_set_admits_in_submission_order_not_lexicographic_task_id`
in `tests/test_prism_scheduler_agents_846_847.py` -- submits 10 same-slot,
undifferentiated tasks named `run-abc-task-1` .. `run-abc-task-10` and asserts
`next_batch()` admits them in submission order. It fails red against the
pre-fix scheduler with exactly the observed defect (`task-10` admitted before
`task-2`), and passes green after the fix. The full `tests/test_prism_scheduler_agents_846_847.py`
and `tests/test_prism_budgets_850.py` suites, plus every other `-k prism` test
in the root suite (96 passed, 1 skipped), stayed green.
