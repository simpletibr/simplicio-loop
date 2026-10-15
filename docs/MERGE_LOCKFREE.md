# Lock-free merge mode (#1820)

Status: opt-in, OFF by default. The default merge train is batch (#1504, `simplicio_loop/merge_train.py`), and it is unchanged.
Scaling claims for this mode are UNVERIFIED: no benchmark measures them yet.

## The model

The model is the one Anthropic describes for its in-house source control: <https://www.anthropic.com/engineering/redesigning-source-control>.

- Merge an approved PR when its targeted tests are green. No global lock, no queue.
- Run the impacted tests on main after each merge (`scripts/impact_tests.py`).
- On red, open a revert PR, or a fix task for the owning squad. Never force-push, never rewrite history, never merge a revert.

| | batch (default) | lockfree (opt-in) |
|---|---|---|
| Test before a merge | one cumulative test per batch of up to 4 PRs, bisect on red | the PR's own targeted tests (measured by its worker) |
| Test after a merge | none (the batch test is the test) | impacted tests on main, after each merge |
| On red | bisect, merge the good prefix, mark the bad PR failed | revert PR (or fix task), then no more lock-free merges this tick |
| Ordering | one serial train per repo, under the repo lock | one PR at a time in plan order; the repo lock covers only git steps and the post-merge run |
| Approval gate | `squads gate` rule, the watcher's own login | the same |

## When to use which mode

Use batch, which is the default. Use lockfree only when you accept a post-merge red on main that is repaired by a revert PR,
and when your PRs rarely touch the same files. Whether lockfree is faster or cheaper than batch is not measured here.

## How to turn it on

```bash
simplicio-loop watch247 --mode lockfree      # this run
export SIMPLICIO_247_MERGE_MODE=lockfree     # or for the environment; only the exact value counts
```

`--mode` wins over the environment when given. Without either, the mode is batch. A value other than `batch` or `lockfree` is
refused by the parser.

A merge still needs `SIMPLICIO_247_AUTO_MERGE=1`. Without it, the watcher never merges in either mode.

## Decision rules (per approved PR, in plan order)

`decide_merge` in `simplicio_loop/merge_lockfree.py` returns merge, wait or refuse.

1. Approval gate first. No authorized approval on the reviewed head: refuse, with the gate's reason. The approval is written by
   the watcher's own login, as in batch. In lockfree mode the gate is never skipped.
2. Targeted tests must be green on the reviewed head (measured by the worker's verify). Otherwise refuse.
3. File overlap. If the PR touches a file that an earlier merge in this tick has not yet verified on main, wait, with the PR number
   in the reason. The second PR is never stacked on an unverified change to the same file.
4. Otherwise merge. The merge is `gh pr merge --squash --match-head-commit <reviewed head>`, so only the head that was reviewed
   and tested can land.

After a red, every later PR in the tick is refused with the reason "main is red", so no lock-free merge lands on a red main.

## Post-merge check

After each merge, in the base clone at origin/main:

- `python3 scripts/impact_tests.py --base <parent of the merge commit>` selects the tests.
- If the tool is missing, fails, or selects nothing, the whole verify command of the repo runs. An empty selection is never green.
- A run that cannot finish (timeout, missing git step) is `pending`, not red. The merge stays unverified, its files block overlapping
  PRs, and it is reported in the status. Nothing is called red unless tests ran and failed.

## On red

`on_red` in `merge_lockfree.py` opens exactly one of these:

- a revert PR (default policy `revert`): `git revert --no-edit <merge commit>` on a new branch `revert/pr-<N>-<sha>` made from
  origin/main, pushed without a force flag, then opened as a PR that names the failing tests. The loop does not merge it. A human
  or the merge coordinator merges it after review.
- a fix task (policy `fix`, or when the revert cannot be opened, for example on a conflict): a GitHub issue that names the owning
  squad and the failing tests. It carries no `loop:auto` label, so the watcher does not pick it up on its own.

A failed revert is aborted, and nothing is merged or pushed for it.

## Safety rules

- No force-push, no history rewrite, no deletion of branches or files. The code never builds a force flag.
- A revert PR is never merged by this code. The test suite checks that the revert's argv carries no merge call.
- The approval gate and the head pin are the same as in batch mode.
- Merges run without the repo lock. The repo lock covers the base clone's git steps (the post-merge checkout, the revert branch)
  and the post-merge test run, so a worker's git step waits for a running post-merge test.

## Known limits (UNVERIFIED unless noted)

- No benchmark exists for scaling, lock contention, or the cost of post-merge runs. These are UNVERIFIED.
- A `pending` post-merge check is not re-run by a later tick in this version. Its files stay unverified until the next process run
  (UNVERIFIED: no test of a later re-check exists).
- A PR that waits is not merged by a later tick unless the watcher reviews and merges it again. This is UNVERIFIED on a real drain.
- Impacted tests come from `scripts/impact_tests.py`, which exists in simplicio-loop. On other repos the whole verify runs instead,
  which is slower, and it is UNVERIFIED on those repos.
- The fix task is opened for the squad, not assigned to it. Routing it to the squad is UNVERIFIED.

## Where it lives

- `simplicio_loop/merge_lockfree.py`: decisions, post-merge check, revert or fix task, the pass, and `Forge` (git and gh calls,
  with an injected `run`).
- `simplicio_loop/watcher247/squad_flow.py`: `finish` picks the mode and calls `_merge_lockfree`. `_merge` (batch) is unchanged.
- `simplicio_loop/cli_impl.py`: the `--mode` flag of `watch247`.
- Tests: `tests/test_merge_lockfree.py`, `tests/test_merge_lockfree_cli.py`, `tests/watcher247/test_squads_lockfree.py`.
