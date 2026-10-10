# Central map: one base per repository, one isolated overlay per worktree

Issue #1574, part of #1429. The mapper keeps one shared map of the default branch. Each worktree
reads it and keeps only its own changes. No worktree writes the shared map.

## What the system stores and where

| Store | Location | Writer | Contents |
|---|---|---|---|
| Central base | `<git-common-dir>/simplicio/canonical/<digest>/` | `simplicio-mapper canonical build`, or the first `canonical overlay` of any worktree, once | `project-map`, `symbol-index`, `precedent-index`, `call-graph`, `file-manifest.jsonl`, `manifest.json` of the default-branch tree. The base never changes after promotion. |
| Build scratch | `<git-common-dir>/simplicio/scratch/canonical-<pid>-*/` | the base build | A checkout of the default-branch commit through a private index (`read-tree`, `checkout-index`). No `git worktree` entry exists. A `build.lock` marks it alive. The build removes it in `finally` and on SIGTERM. |
| Worktree overlay | `<worktree>/.simplicio-loop/` | `simplicio-mapper canonical overlay` (what `orient` runs) | `overlay.json` (base digest, delta, counts) and the three artifacts that `orient` and Dev CLI read: `project-map.json`, `symbol-index.json`, `precedent-index.json`. |
| Runtime baselines | `<git-common-dir>/simplicio/map/baseline-<tree>.json` | the Simplicio Runtime (Rust), not this repository | One file per merge-base tree of each worktree. See the audit. `map gc` keeps the newest N and the ones that a live worktree forks from. |

The digest is `CanonicalMapKey.digest()`: repository identity, default branch, commit, tree, schema,
mapper version and mapping-config fingerprint. `canonical build|status|verify|overlay` and the `index`
adapter use the same config fingerprint, so one default-branch tree gives one base.

The default branch is the target of `refs/remotes/origin/HEAD`, else `main`, else `master`. For each
name the remote-tracking ref wins over the local branch. A worktree never counts its own branch.

## Flow of `orient` in a worktree

1. `_ensure_project_map` checks the tree state. If the tree changed, it starts `index_argv()`: one
   process that runs `simplicio-mapper canonical overlay <worktree> --json` and, only when that cannot
   serve, a full `index`. The process runs `python -P`, so no file in the mapped repository can shadow
   the standard library.
2. `canonical overlay` takes the worktree's `index.lock`, resolves the default branch, and builds the
   base once if it does not exist. Another process or worktree that asks meanwhile waits and reuses
   the result. Then it computes the delta: `git diff --name-status -z -M <base>..HEAD`,
   `git status --porcelain -z`, and the files that git does not watch (`assume-unchanged`,
   `skip-worktree`).
3. It maps the worktree as base facts for the unchanged files plus fresh parsing for the rest, through
   the mapper's own inventory.
4. It writes only the worktree's `.simplicio-loop/` state. It removes an older generation of
   `call-graph`, `architecture-inventory`, `retrieval-index` and `artifact-manifest`, because those
   files describe another tree. A later full `index` replaces `overlay.json`.
5. `simplicio-mapper orient` reads the two JSON artifacts as before.

## The C#/Razor semantic pass and the name-lookup cap (#1631)

The semantic service resolves C#/Razor call sites (`SIMPLICIO_MAPPER_SEMANTIC_COMMAND`). That pass reads
only the C#/Razor files. The service gets only the symbols that C#/Razor files define. A Python or
JavaScript file never enters the request and never changes the answer.

* `semantic_resolution.input_key` in `symbol-index.json` is a digest of the path, language and content
  hash of every C#/Razor file, plus the service command and timeout. A C#/Razor file without a content
  hash makes the key unprovable, so the field is `null`.
* The overlay compares the `input_key` of the base with the one of the worktree. If they are equal, it
  copies the C#/Razor symbols and the `semantic_resolution` of the base and does not start the service.
  If they differ, it parses the C#/Razor files again and runs the service on those files alone.
* The receipt of `canonical overlay` has the field `semantic`. `not_required` means the worktree has no
  C#/Razor file. `reused_from_base` means the service did not run. `recomputed:<reason>` means it ran.
  The reason is `input_key_unprovable`, `base_without_input_key` or `semantic_input_changed`.
* A call that the service did not resolve keeps at most 32 candidate edges by name lookup. Set
  `SIMPLICIO_MAPPER_CALL_NAME_CANDIDATE_LIMIT` to change the cap. The minimum is 1, and a value that is
  not a number gives 32. The kept candidates are the first ones by file, line and qualified name, so
  the result does not depend on the file order. The edge still reports the real `candidate_count`.
* `call-graph.json` reports the cap in `coverage`: `name_candidate_limit`, `name_capped_call_sites` and
  `name_edges_discarded`. Any discarded edge sets `coverage.status` to `degraded`. The cap never
  applies to an edge that the service resolved.

A startup GC runs before this step: in `run_mapper_index`, in `run_mapper_map`, in the budgeted
`_ensure_project_map_bounded`, and in every `map <command>`. It removes stale scratch and orphan locks.
It never removes a base.

## Guarantees and the tests that prove them

* `base + overlay` equals a fresh full mapping. The canonical digests of project-map, symbol-index
  and precedent-index match on clean trees, on modified, added, removed and renamed files, staged or
  not, with HEAD ahead of or behind the base, on a detached HEAD, after `package.json` changes, for
  git-ignored files that the mapper still walks, for large files, for C#/Razor sources, for names with
  spaces, quotes, backslashes, TAB, newline, ` -> ` or non-ASCII characters, for `assume-unchanged`
  and `skip-worktree` edits, and on random edit sequences
  (`packages/mapper/tests/python/test_central_overlay.py`).
* A change in worktree A stays invisible in worktree B and in the base. An overlay run does not change
  one byte of the base store.
* N concurrent worktrees trigger one base build. A counter test proves it.
* Disk budget (#1672): on a synthetic repository with 3 worktrees and 2 edited files each, every
  overlay holds at most 50 % of the bytes of a full index of the same worktree, and the base plus the
  3 overlays hold at most 60 % of 3 full indexes. A second overlay run without changes adds no file
  and no bytes. Mutants that copy `call-graph` or `retrieval-index` into a worktree, or that build a
  second base, break the test (`packages/mapper/tests/python/test_central_map_disk_budget.py`).
* Failing, interrupted and SIGTERM builds leave no scratch, no staging directory and no
  `git worktree` entry.
* `map gc` removes only what is safe. It keeps a scratch directory that has a live lock, a process
  inside it, or a write in the last hour. It keeps a baseline that is among the newest N, that a live
  worktree forks from, that has a fresh lock, or that a writer finished in the last 60 seconds. It keeps a
  canonical base that is among the newest N, current, or referenced by a live `overlay.json`. It
  checks each baseline again just before it removes it. It never touches the bases of another
  repository that shares `SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR`.

## Commands

```
simplicio-loop map gc --dry-run [--keep 3] [--max-age 3600] [--json]   # list what would go, with sizes
simplicio-loop map gc           [--keep 3] [--max-age 3600] [--json]   # remove only the safe things
simplicio-mapper canonical overlay <worktree> [--json]                 # exit 1 and status=fallback when it cannot serve
simplicio-mapper canonical build|status|verify|gc <path>               # same surface, one shared base key
```

## Audit: what was wrong (measured 2026-10-09)

* **Origin of the 102 `baseline-build-*` directories (63 to 69 MB each, 6.8 GB):** the Simplicio
  Runtime. The code is `simplicio-runtime/src/native_mapper_adapter.rs::build_baseline_map`. It
  materializes the tree with `git read-tree` and `checkout-index --prefix` into
  `tempfile::Builder::prefix("baseline-build-")` under `<git-common-dir>/simplicio/map`. Only
  destructors remove the temp directory and the per-key lock. I reproduced the leak with the real
  binary on a synthetic repository, two ways:
  1. `simplicio context --task ... --repo <wt>` with no stored baseline starts a detached
     `simplicio-baseline-build` thread. The one-shot process exits. The scratch tree and the lock stay.
  2. A foreground `simplicio runtime map` that SIGTERM or SIGKILL stops leaves the same files.

  The Runtime reclaims a stale lock after 5 minutes, so every later call leaks one more tree. The
  burst between 02:43 and 02:53 matches many worktrees that run the suite. Each worktree has its own
  merge-base, so its own baseline key and lock. Before this change `scripts/planes_installed_e2e.py`
  ran `simplicio runtime map --repo ROOT` on the real checkout inside a test, with a 120 s timeout.
  The fix for the Runtime itself belongs in simplicio-runtime: join or cancel the detached build
  before exit, or clean up on SIGTERM. This repository now reclaims such trees (startup GC, `map gc`),
  refuses the spawn in tests, and does not produce them.
* The Runtime keys baselines by the tree of `merge-base(HEAD, default)`. N worktrees forked at N
  commits make N baselines of about 40 MB each, not one per default-branch tree.
* Before this change `orient` ran a full `simplicio-mapper index` in every worktree (111 MB of
  `.simplicio-loop` for about 3,060 files here). The base and overlay design existed in
  `packages/mapper`, but reuse was opt-in and served only a clean tree at exactly the base commit.
  `canonical build` and `index` used different config fingerprints. The base checkout used
  `git worktree add` in `/tmp`, so a SIGTERM left the copy and a `.git/worktrees` entry. The
  default-branch lookup returned the worktree's own branch. `map gc` did nothing.

## Known limits

* **A change to one C#/Razor file runs the service on every C#/Razor file of the tree.** The service
  resolves symbols across files, so the overlay cannot run it on the changed file alone. The overlay
  skips the service only when the C#/Razor files, the command and the timeout equal those of the base.
  The result stays exact: the three artifacts match the full mapping. Before #1631 the overlay on this
  repository took 500.9 s and a fresh full mapping took 506.5 s, because the overlay ran a global pass
  over all files.
  Measured after #1631 on a `git clone --shared` of commit 43d53da1 (3,644 files, 8 C#/Razor files,
  ambient load about 8, `nice -n 10`). The run had no semantic service, so no C#/Razor file went
  through a real service:
  * `canonical overlay` on an unchanged worktree with the base in the cache: 8.35 s wall time and
    160 MB maximum RSS. `semantic` is `reused_from_base`. The overlay reused 3,644 of 3,644 files.
    Before #1631 the same run did not finish in 120 s (exit 124).
  * The build of the base (a full mapping of the clone): 114.4 s and 1.21 GB maximum RSS.
  * Oracle on the clone, three runs: unchanged tree, one Python file and one C# file with a new
    comment, and a new function in the Python file plus a new class in the C# file and a comment in
    a second C# file. In each run the digests of project-map, symbol-index and precedent-index of
    the overlay equal those of a fresh full mapping. The overlay took 6.5 s to 7.6 s. The full
    mapping took 73.7 s to 99.6 s.
  * UNVERIFIED: the time of a changed C#/Razor file with a real semantic service. The service did
    not run in these measurements.

  The tests count operations instead:
  `packages/mapper/tests/python/test_call_graph_scaling.py` shows 0 service runs for a Python-only
  delta in a repository of more than 2,000 files with 8 C#/Razor files. In the same test file, a
  synthetic call graph of 2,000 files iterated `files` 80,026 times before and iterates it 5 times now.
* **Disk gain measured on synthetic repositories only.** See the measurements below. The real repository
  has no disk number yet.
* **`call-graph`, `architecture-inventory`, `retrieval-index` and `project.sfast` do not come from the
  base.** A worktree that needs them runs `simplicio-mapper index` or the Fast build and pays the full
  cost. Since #1673 the search path (`scan`, `inspect`, `handoff`) stays on the overlay:
  * `scan` on a worktree with a valid `overlay.json` refreshes the overlay and answers `fresh`
    (`deep.skipped_reason = served_by_overlay`). It starts no full index and keeps `overlay.json`.
    If the overlay cannot serve (fallback), `scan` runs the full index as before.
  * `inspect` treats the overlay as valid for `project-map`, `symbol-index` and `precedent-index`
    (`evidence.artifacts.<name>.state = served_by_overlay`). `call-graph`, `architecture-inventory` and
    `retrieval-index` are `not_served_by_overlay`; that is not a reason for `fresh=false`.
    `status.artifact_service` lists both groups. A worktree whose `overlay.json` names a base that is
    no longer in the cache is not valid: `artifacts_present` is `false`.
  * `canonical overlay` and `scan` write `index-state.json` with the freshness signature of the tree,
    so `inspect` can tell a refreshed overlay from a stale one.
  * `ask callers|callees|reaches|impact` build the unserved artifacts in memory when the query needs
    them, and the answer declares the cost in `on_demand_cost` (`seconds`, `built`, `persisted: false`).
    `scan`, `inspect` and `handoff` never build them.
  * MEASURED on 2026-10-10 in this repository (main `c92d399b`, one run for each step, three other jobs
    ran on the same machine, the cache was in a scratch folder). The base took 113.3 s and 36.5 MB,
    once. In a second worktree `canonical overlay` took 12.3 s, `scan` 1.5 s, `inspect` 0.9 s and
    `handoff` 14.3 s. `scan` kept `overlay.json` and answered `skipped_reason = served_by_overlay`.
    `inspect` answered `artifacts_present = true` and `fresh = true`. The `.simplicio-loop` folder of
    the worktree holds 30.8 MB. The full index there cost 114.7 s and 89 MB, measured before #1673.
    The tests count full indexes (0) on a synthetic repository.
* **The assembly in `central_overlay._project_map` mirrors `emit._build_artifacts_sync`.** The oracle
  test fails if they drift. Folding the sync, async and overlay copies into one is a follow-up.
* **A file stays unchanged only when git reports no delta, git does not hide it, and its size matches
  the base.** An edit that keeps the size and that git cannot see by any other means has no detector.
* **`map gc` handles Runtime baselines but does not build or unify them.**
* **The conftest guard is best effort.** It refuses `simplicio` mapping subcommands (`map`,
  `runtime`, `context`, `orient`, `orientation`, `plan`, `decide`, `run`, `sprint`, `validate`,
  `dev-cli`, `serve`) that act on this checkout or on the main worktree. Four bypasses exist:
  `env simplicio ...`, `shell=True`, `os.system`, and a renamed binary. The environment variable
  `SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR` does not affect the Runtime.
* **Two default-branch resolvers exist.** The loop resolves `origin/HEAD`, `main`, `master`. The
  mapper adds the first local branch as a last choice. They differ only in a repository that has
  neither `main` nor `master` nor `origin/HEAD`.

## Measurements

Benchmark: `scripts/benchmark_central_map.py --files 3000 --worktrees 5 --funcs 15 --edits 3` on a
synthetic Python repository without C#. Ambient load was about 9 on 10 cores.

| | Full `index` in each worktree | Central base and overlay |
|---|---|---|
| `.simplicio-loop` per worktree | 50.5 MB | 16.2 MB |
| Central store | 0 | 18.1 MB (one base) |
| Total for 5 worktrees | 252.7 MB | 99.0 MB |
| Worktree 1 | 21.7 s | 13.8 s (includes the one-time base build) |
| Worktrees 2 to 5, mean | 21.8 s | 5.4 s |

On the real repository (3,296 files, with C#/Razor) the oracle showed equal artifacts and no time gain
before #1631. The one-time base build took 626 s under load.
