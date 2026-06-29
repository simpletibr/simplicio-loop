# ADR-003: Two-tier async mapper (instant macro map + deep background pass)

> Closes evaluation requested in https://github.com/wesleysimplicio/simplicio-mapper/issues/120
> (sub-tasks #121, #122, #123).

---

## Status

`Aceito`

---

## Data

2026-06-29

---

## Autores

- wesleysimplicio
- Claude (claude-opus-4-8)

---

## Contexto

`simplicio-mapper index`/`map` runs the whole pipeline synchronously
(project-map with previews, symbol-index, call-graph, architecture-inventory,
flowchart). On large repositories the first useful response is delayed by the
full deep pass, even when a caller only needs a coarse skeleton to start
orienting.

The runtime already ships the foundation for an async model: a detached
`--background` index process with a log, a `--watch` mode, an idempotent `index`
guarded by `index.lock`, a freshness gate persisted in `index-state.json`,
`--incremental` refreshes, the `FileProcessingCache` (diskcache) and the
`ContextCache`. What was missing is a fast first response and a typed way to
poll the deep pass — the `fast`/`background` lanes described in the yool/tuple
spec.

## Decisão

Introduce a two-tier model on top of the existing machinery, without changing
the default synchronous behavior of `map`/`index`.

- **Macro (fast, sub-second)** — `simplicio.macro-map/v1`, built by
  `mapper.build_macro_map(cwd)` and exposed as `simplicio-mapper macro <path>
  [--json]`. The skeleton is derived from filenames plus a few manifests
  (`package.json`, `pyproject.toml`, `.starter-meta.json`) only — no per-file
  content reads, no symbol/call-graph pass. Fields: `product` (name/stack/
  project_mode), `counts` (files, by_language, screens, endpoint_files, tests,
  modules), `modules[]`, `layers[]`, `entry_points[]`, `config_files[]`, `git`
  (head/dirty) and `confidence: "shallow"`.

- **Deep (background)** — the current `index` pipeline running detached, writing
  the `v1` artifacts incrementally and updating `index-state.json`. Reused
  as-is via the extracted `_spawn_background_index` helper.

- **Job envelope** — `simplicio-mapper scan <path>` returns immediately with a
  `simplicio.map-job/v1` envelope: the macro map inline plus deep-pass pointers
  (`pid`, `log`, `poll`, `state_path`, `lock_path`). Default spawns the deep
  pass in the background and returns `phase: macro_done`. When `CI=true` (or
  `--sync`) the deep pass runs synchronously and the envelope returns
  `phase: complete`. `--await` blocks until the deep pass is terminal within a
  bounded `--timeout`. The envelope is persisted to `.simplicio/map-job.json`.
  The deep pass is lock-guarded by the existing `index.lock`, so concurrent
  deep runs are skipped rather than racing.

- **Status** — `simplicio-mapper status <path> [--json]` derives the deep-pass
  phase from `index.lock` presence + `index-state.json` freshness +
  `map-job.json`: `deep_running | complete | failed | unknown`. A shared
  `_await_terminal` helper (used by both `scan --await` and `status --await`)
  blocks until the phase leaves `deep_running` or the timeout fires.

Phase derivation is deterministic:

1. `index.lock` present → `deep_running`.
2. else artifacts present and `index-state.json` signature matches the current
   freshness signature → `complete`.
3. else a `map-job.json` exists but no fresh artifacts and no lock → `failed`
   (a requested deep pass is gone without finishing).
4. else → `unknown`.

## Consequências

Positivas:

- Callers get a useful skeleton in sub-second time and can decide whether to
  wait for the deep pass.
- No new dependency and no schema change to the existing `v1` artifacts; the
  deep pass is the unchanged `index` pipeline.
- `scan`/`status` compose with CI: `CI=true` collapses to a synchronous,
  fully-materialized envelope so pipelines stay deterministic.

Negativas:

- The macro map is explicitly `shallow`: screen/endpoint/test counts are path
  heuristics, not content-verified. Consumers must treat them as hints, which
  is why `confidence` is part of the schema.
- `failed` is inferred, not recorded by the deep pass itself; a background run
  killed mid-flight is reported as `failed` only once its lock is gone and no
  fresh artifacts exist.

## Alternativas consideradas

- **Always run deep, just cache harder** — does not fix the cold first
  response on a large repo with no prior index.
- **A separate long-lived daemon** — heavier operational surface than reusing
  the existing detached `index` process and lock/state files.
- **Embed macro fields inside the deep `project-map`** — couples the fast lane
  to the slow one; a distinct `macro-map/v1` keeps the fast path content-free.

## Plano de adoção

1. ✅ `mapper.build_macro_map` + `simplicio.macro-map/v1` + `macro` command (#121).
2. ✅ `scan` command + `simplicio.map-job/v1` envelope, background/sync/await,
   `.simplicio/map-job.json` persistence (#122).
3. ✅ `status` command + shared `--await` helper + phase derivation (#123).
4. ✅ Document the two-tier model and contracts in `SIMPLICIO_INTEGRATION.md`
   and this ADR.

## Notas de implementação

- Path-only helpers (`_macro_roles_for_path`, `_macro_layers_for_path`,
  `_is_macro_screen`, `_macro_git`) mirror the content-based equivalents
  (`_roles_for`, `_layers_for_file`) so the macro and deep lanes agree on
  module/layer/role vocabulary without the macro lane reading file bodies.
- `_run_background` now delegates to `_spawn_background_index`, which returns the
  `pid`/`log` payload so `scan` can embed the deep-pass pointers.
- The synchronous deep run inside `scan` redirects the inner `index` stdout so
  the only thing printed is the `map-job/v1` envelope.
