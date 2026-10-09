# Central map: one base per repository, one isolated overlay per worktree

Issue #1574 (part of #1429). Requirement: the mapper is centralized and shared, built from the default
branch (`origin/HEAD`, else `main`, else `master`); every worktree keeps consulting it and owns only its
own updates, isolated; the main project stays centralized and no worktree changes it.

## What is stored where

| Store | Location | Written by | Contents |
|---|---|---|---|
| Central base | `<git-common-dir>/simplicio/canonical/<digest>/` | `simplicio-mapper canonical build` / the first `canonical overlay` of any worktree, once (cross-process single-flight lock) | `project-map`, `symbol-index`, `precedent-index`, `call-graph`, `file-manifest.jsonl`, `manifest.json` of the default-branch tree. Immutable. |
| Build scratch | `<git-common-dir>/simplicio/scratch/canonical-<pid>-*/` | the base build | a checkout of the default-branch commit made through a private index (`read-tree` + `checkout-index`): no `git worktree` entry. Holds a `build.lock`; removed in `finally` and on SIGTERM. |
| Worktree overlay | `<worktree>/.simplicio-loop/` | `simplicio-mapper canonical overlay` (what `orient` runs) | `overlay.json` (base digest, delta, counts) plus the three artifacts `orient` and Dev CLI read: `project-map.json`, `symbol-index.json`, `precedent-index.json`. |
| Runtime baselines | `<git-common-dir>/simplicio/map/baseline-<tree>.json` | the Simplicio Runtime (Rust), not this repository | one per merge-base tree of each worktree; see the audit. `map gc` keeps the newest N and the ones a live worktree forks from. |

The digest is `CanonicalMapKey.digest()` (repository identity, default branch, commit, tree, schema,
mapper version, mapping-config fingerprint). `canonical build|status|verify|overlay` and the `index`
adapter now use the same config fingerprint, so one default-branch tree is one base.

## Flow of `orient` in a worktree

1. `_ensure_project_map` (tree-state cached) starts `index_argv()`: one process that runs
   `simplicio-mapper canonical overlay <worktree> --json` and, only if that cannot serve, a full `index`.
2. `canonical overlay` resolves the default branch, builds the base **once** if missing (any other
   process or worktree asking meanwhile waits and reuses it), computes the delta
   (`git diff --name-status -M <base>..HEAD` + `git status` incl. untracked), and maps the worktree as
   base facts for unchanged files + fresh parsing for the rest, through the mapper's own inventory.
3. It writes only the worktree's `.simplicio-loop/` state. A previous full generation of
   `call-graph`, `architecture-inventory`, `retrieval-index` and `artifact-manifest` is removed (it
   describes another tree). A later full `index` replaces `overlay.json`.
4. `simplicio-mapper orient` reads the two JSON artifacts exactly as before.

## Guarantees (each one has a test)

* `base + overlay` equals a fresh full mapping: the canonical digests of project-map, symbol-index and
  precedent-index are identical on clean trees, modified/added/deleted/renamed files (staged or not),
  HEAD ahead of / behind the base, detached HEAD, `package.json` changes, git-ignored files the mapper
  still walks, large files, names with spaces and non-ASCII characters, and random edit sequences
  (`packages/mapper/tests/python/test_central_overlay.py`).
* A change in worktree A is invisible in B and in the base; an overlay run does not alter one byte of
  the base store; the base is built once for N concurrent worktrees (a counter proves it).
* Nothing a build or a test creates is left behind: failing, interrupted and SIGTERM-ed builds leave no
  scratch, no staging directory and no `git worktree` registration.
* `map gc`: stale (> 1 h, unlocked, no process inside) scratch and orphan locks are removed; bases are
  kept when newest-N, referenced by a live worktree overlay (`overlay.json`), current, or locked.

## Commands

```
simplicio-loop map gc --dry-run [--keep 3] [--max-age 3600] [--json]   # list what would go, with sizes
simplicio-loop map gc           [--keep 3] [--max-age 3600] [--json]   # remove only the safe things
simplicio-mapper canonical overlay <worktree> [--json]                 # exit 1 + status=fallback when it cannot serve
simplicio-mapper canonical build|status|verify|gc <path>               # unchanged surface, one shared base key
```

A startup GC (scratch and orphan locks only, never a base) runs before every `index`/`overlay` the loop starts.

## Audit: what was wrong (measured 2026-10-09)

* **Origin of the 102 `baseline-build-*` directories (63-69 MB each, 6.8 GB):** the Simplicio Runtime,
  `simplicio-runtime/src/native_mapper_adapter.rs::build_baseline_map`, which materializes the tree with
  `git read-tree` + `checkout-index --prefix` into `tempfile::Builder::prefix("baseline-build-")` under
  `<git-common-dir>/simplicio/map`. The `TempDir` and the per-key `LockGuard` are removed only by their
  destructors. Reproduced with the real binary on a synthetic repository, two ways:
  1. `simplicio context --task ... --repo <wt>` with no stored baseline starts a detached
     `simplicio-baseline-build` thread and the one-shot process exits: the scratch tree and the lock stay.
  2. a foreground build (`simplicio runtime map`, e.g. under a test timeout) killed with SIGTERM/SIGKILL.
  A stale lock is reclaimed after 5 minutes, so every later call leaks one more tree. The 02:43-02:53
  burst is many worktrees (each has its own merge-base, hence its own baseline key and lock) running
  the suite: `scripts/planes_installed_e2e.py` ran `simplicio runtime map --repo ROOT` against the real
  checkout inside the test, with a 120 s timeout. That fix belongs in the Runtime (join/cancel the
  detached build before exit, or remove the scratch on SIGTERM); this repository now contains it
  (startup GC, `map gc`), refuses the spawn in tests, and no longer produces such trees itself.
* The Runtime keys baselines by `merge-base(HEAD, default)` tree: N worktrees forked at N different
  commits make N baselines (~40 MB each on this repository), not one per default-branch tree.
* Before this change the Python side had a base/overlay design but did not use it: `orient` ran a full
  `simplicio-mapper index` in every worktree (111 MB of `.simplicio-loop` on this repository, ~3,060 files);
  the canonical reuse adapter was opt-in, only served a clean tree at exactly the base commit, copied the
  four artifacts into the worktree, and `canonical build` and `index` used different config
  fingerprints (two bases per tree); the base checkout was `git worktree add` into `/tmp` (a SIGTERM left
  both the copy and a `.git/worktrees` entry); `_default_branch` returned the *worktree's own branch*;
  `map gc` was a no-op.

## Limits (not hidden)

* `call-graph`, `architecture-inventory`, `retrieval-index` and the SFAST `project.sfast` are **not**
  served from the base: a worktree that needs them runs `simplicio-mapper index` (or the Fast build) and
  pays the full cost, as before. Trees with C#/Razor sources also fall back to a full index.
* The assembly in `central_overlay._project_map` mirrors `emit._build_artifacts_sync`; the oracle test
  fails if they drift. Folding the three copies (sync, async, overlay) into one is a follow-up.
* A file counts as unchanged when git reports no delta and its size matches the base entry; a same-size
  edit that git cannot see (`assume-unchanged`, `skip-worktree`) is not detected.
* The Runtime's own `<git-common-dir>/simplicio/map` baselines are GC'd here but built there.
