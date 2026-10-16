# `simplicio-loop squads run`

`squads run` executes a wave that `squads plan` already planned (issue #1829, the Stretch item of #1812). It takes the
plan's squads, owned paths, contracts and merge order as they are. It never plans again.

```
simplicio-loop squads plan --issues issues.json --json > plan.json
simplicio-loop squads run --plan plan.json --issues issues.json                 # preview only, spawns nothing
simplicio-loop squads run --plan plan.json --issues issues.json --execute       # workers, checks, local commits and tests
simplicio-loop squads run --plan plan.json --issues issues.json --execute --approver LOGIN
```

## What a run does

For each squad, in wave order and then merge order:

1. **Worktree.** `git worktree add -b squads/<run>/<squad> <run-dir>/worktrees/<squad> <base>`. `<run>` is 12 hex digits
   of the plan's canonical JSON, so two plans never share a branch. `<base>` is `main` unless `--base` says otherwise.
2. **One execution worker per squad.** Its model and effort come from the plan (`model_roles`, execution role). Its prompt
   carries the task text (from `--issues`), the owned paths, the shared-file rules, and the contracts it must honor. The
   prompt forbids commits, pushes and PRs: the coordinator does those.
3. **Ownership check, after every launch.** The changed files are `git diff --name-only <base>` plus untracked files,
   minus the run's `.simplicio/` folder. A path the squad does not own, or any shared file (`plan.shared_files`, even inside
   an owned glob), stops that squad at once. The report names the paths. Nothing from that squad is pushed or merged.
   Other squads continue.
4. **Continuation.** A launch that returns `budget_exhausted` writes `.simplicio/handoff.md` in the worktree (the worker's
   own progress note, the files touched, the owned paths). It then launches a continuation whose prompt includes that note.
   This repeats up to `--max-continuations` times (default 3, or `SIMPLICIO_SQUADS_MAX_CONTINUATIONS`). After that the squad
   is BLOCKED with `budget_exhausted after N continuation(s)`. The continuation count is recorded in the state.
5. **Commit and test.** A squad that passed the ownership check is committed on its branch (only owned changes, never the
   `.simplicio/` folder). Then the tests run in its worktree (`SIMPLICIO_SQUADS_TEST_CMD`, default `python3 -m pytest -q`).
   It becomes `ready` when they pass. A failing squad is BLOCKED and never pushed.

## Merge

Merges run only with `--execute` and with at least one `--approver LOGIN`.

* **Without `--approver`** the run stops after step 5. Nothing is pushed, no PR is opened, nothing merges. The result
  is BLOCKED with a `next:` line that says to rerun with `--approver`.
* **With `--approver`** each ready branch is pushed (`git push -u origin <branch>`, never forced), and a PR is opened for it.
  A PR merges only when `squads.squad_gate` finds an authorized approval on that PR's head (the same gate as
  `simplicio-loop squads gate --pr N --approver LOGIN`). The merge goes through `gh api -X PUT .../pulls/N/merge` with the
  reviewed head as `sha`, so GitHub refuses a head that changed.
* `--mode batch` (default): PRs merge one at a time, in merge order, and main is verified after each merge. The first PR
  the gate refuses stops the merges, so the order holds.
* `--mode lockfree`: the approved PRs go through `merge_lockfree.merge_pass`. An approved PR merges without waiting for the
  others, unless its files overlap an unverified merge. A red main after a merge stops the rest of the run. No revert PR is
  opened by `squads run`; the watcher's lockfree mode does that.

A squad whose plan says `blocked_by` a squad that did not merge waits and is not merged.

## Dry run and the preview

Without `--execute` the command prints the preview and spawns nothing: no worktree, no branch, no launch. The preview
is printed before any worker starts, as AGENTS.md requires. It lists, for each squad, its wave, its execution role,
model and effort, its issues, its owned paths, what it is blocked by, its branch and its worktree. It then lists the
shared files, the merge order, the merge policy, and the exact commands. `--json` prints the same preview inside one
JSON document.

## State and resume

Each run keeps `state.json` in its run folder (`<repo>/.simplicio/squads-run/<run>` by default, or `--run-dir`). It records
each squad's status (`pending`, `ready`, `blocked`, `merged`), its branch, its launches and continuations, its changed
files, its offending paths, its head, its PR and its merge commit.

A rerun with the same plan and the same run folder resumes. Ready and merged squads are not run again. Blocked squads keep
their stored reason; to retry one, fix the cause and start over (remove the run folder and the squad branch
with `git branch -D`). A run folder of another plan or another base is refused.

## Injectable launcher contract

The launcher is the only part that talks to a model. `squads run` never calls one itself.

```python
from simplicio_loop import squads_run as sr

def launcher(request: sr.LaunchRequest) -> sr.WorkerOutcome:
    # request.squad, request.worktree (Path), request.model, request.effort,
    # request.owned (tuple of globs), request.prompt (str), request.attempt (1 = first run, n = continuation)
    return sr.WorkerOutcome(sr.STATUS_DONE)          # or STATUS_BUDGET ("budget_exhausted") or STATUS_FAILED ("failed")
```

The result is typed: `WorkerOutcome.status` must be `done`, `budget_exhausted` or `failed`, or the constructor raises.
`detail` is free text for the report. `report` is the worker's own progress note, which goes into the handoff.

The default launcher runs the argv of `SIMPLICIO_SQUADS_WORKER_CMD` in the worktree, with the prompt on stdin.
The template is shell-split first, and `{model}`, `{effort}`, `{squad}` and `{worktree}` are replaced inside each token.
The default is `claude -p --model {model}`. The exit code maps to the status:

| Exit code | Status |
|---|---|
| 0 | `done` |
| 75 (EX_TEMPFAIL) | `budget_exhausted` |
| anything else, or the command is missing, or it times out (1 h) | `failed` |

A worker writes its progress note to `.simplicio/progress.md` with `## Done` and `## Remaining` sections. The note is
read after each launch.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `SIMPLICIO_SQUADS_WORKER_CMD` | `claude -p --model {model}` | The worker command template. |
| `SIMPLICIO_SQUADS_TEST_CMD` | `python3 -m pytest -q` | The tests run in each squad's worktree, and on main after a merge. |
| `SIMPLICIO_SQUADS_MAX_CONTINUATIONS` | `3` | Continuations of a worker that stops at its budget. `--max-continuations` wins. |

## Safety rules

* Dry run by default. `--execute` is required to spawn anything, and `--approver` is required to push or merge.
* Ownership is checked after every launch. A violation stops the squad and nothing from it merges.
* No force is ever used: `git push` is plain, and the merge is pinned to the reviewed head.
* Every BLOCKED result prints one plain `next:` line on stderr (`simplicio/next_step.py`).
* Main is verified after each merge. A red main stops the run.

## Limits

* Each squad runs its worker from the base, not from the squads it is blocked by. The plan's contracts tell the worker
  what the other squad will provide.
* One worker runs per squad, and it takes all of the squad's issues. The plan's per-issue worker records supply the model
  and effort.
* The worker, the tests and the PR host are injected. The tests use fakes and local git repositories. No model call, no
  network. A real `claude -p` run has not been measured here (UNVERIFIED).
* `--mode lockfree` does not open revert PRs. A red main stops the run and is reported.
* No `execution-report/v1` is written yet, so `squads metrics` does not read these runs.
