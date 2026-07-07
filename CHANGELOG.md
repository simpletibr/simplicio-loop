# Changelog

## [Unreleased]

### Added
- **Native-first precedent search via `simplicio precedent search`.**
  `mapper.rank_precedents()` now attempts the compiled `simplicio` Rust
  binary before its existing `precedent-index.json` + `rank_entries()`
  ranking: `simplicio precedent search --repo <root> --text <task> --top
  <k> --json` is parsed as `simplicio.precedent-search/v1` and each
  `candidates[]` entry (`precedent_id`, `score`, `reuse_level`,
  `suggested_next_action`) is translated into this module's existing item
  shape (`path`, `line`, `summary`, `tags`) so every current caller
  (`build_precedent_block()`, `build_mapper_context()`, `inspect_target()`)
  keeps working unmodified. Fail-open like every other native/Python pair in
  this package: the new `SIMPLICIO_DEV_CLI_NO_RUNTIME_PRECEDENT` kill-switch
  (named after the existing `SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT`), a missing
  binary, non-zero exit, timeout, unparseable JSON, or a payload missing
  `candidates` all fall through unchanged to the existing mapper-index chain
  — never raises, never breaks a caller. One deliberate deviation from
  `simplicio-mapper`'s own `ask precedent` verb (which this mirrors): a
  valid but *empty* candidate list is also treated as "nothing gained" and
  falls through, rather than being trusted as a final answer, because the
  native precedent-memory database (`.simplicio/precedents/*.sqlite`, built
  from run history via `simplicio precedent index`) and this repo's
  `precedent-index.json` artifact are independent stores — an
  uninitialized native store must not shadow real candidates the
  artifact-file chain might still have. The free-text query comes from
  `rank_precedents()`'s own existing `task` parameter (already threaded
  through by every caller — `build_precedent_block()`'s `goal`,
  `inspect_target()`/`build_mapper_context()`'s `f"{goal} {target}"`), so no
  new plumbing was needed to source it.

## [0.9.4] — 2026-07-07

### Added
- **Native `simplicio edit` delegation for mechanical-edit plans.**
  `mechanical_edit.execute_plan()` now attempts the compiled `simplicio` Rust
  binary before running its own pure-Python implementation: the parsed plan
  is written to a temp file and passed via `simplicio edit --plan <file>
  --repo <root> --json` (plus `--dry-run` when not applying), and a clean
  JSON result matching `simplicio.mechanical-edit-result/v1` is translated
  into this module's own return shape. Fail-open like every other
  native/Python pair in this package: binary missing, the
  `SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT` kill-switch (same one the existing
  `simplicio-dev-cli edit` alias honors), a non-zero or unparseable response,
  a timeout, or a schema mismatch all fall through unchanged to the existing
  Python patcher — never raises, never breaks a caller. Note: the currently
  installed `simplicio` binary's `edit` command answers with a different,
  incompatible contract (`schema: simplicio.edit-result/v1`), so today this
  safely no-ops in practice until the native and Python plan/result schemas
  converge; the delegation path itself is exercised and asserted by
  `tests/python/test_mechanical_edit.py`.

## [0.9.3] — 2026-07-07

### Changed
- Bumped the `simplicio-mapper` dependency floor to `>=0.16.0` (was
  `>=0.15.0`), the latest published release on PyPI.

### Fixed
- **`numpy>=2.5.0` was an unsatisfiable dependency floor.** No `numpy` release
  `>=2.5.0` has ever been published on PyPI (latest is `2.4.6` at the time of
  this fix), so a clean `pip install simplicio-cli` could never resolve —
  caught by `simplicio-loop`'s new wheel-install-smoke CI step
  (wesleysimplicio/simplicio-loop#71/#102). `numpy` is a real, direct
  dependency (`simplicio/precedent.py`, `simplicio/skill_router.py`,
  `simplicio/cache.py`), not something to move behind an extras group;
  lowered the floor to `>=2.1.0`, a real published release compatible with
  this project's `requires-python = ">=3.10"`.
- **TOON was dead code on the real handoff path (#88).** `build_mapper_context()`
  returned the legacy hand-rolled bullets from `_render_handoff_context()`
  *before* ever reaching the TOON branch merged in #85/PR #87 — which only
  lived in the project-map fallback path below the `handoff` pre-empt. Since
  `simplicio-mapper` >= 0.13 always answers `handoff`, `SIMPLICIO_PROMPT_TOON`
  was a no-op in production. The `files[]` block on the handoff path, and the
  `Precedent candidates` block on the fallback path, now honor the same
  `SIMPLICIO_PROMPT_TOON` gate the `Relevant files` block always did.
- `pipeline.py`'s per-task `cost_usd` was hardcoded to `0.0` regardless of
  configured pricing. It is now computed from the same pricing helper the
  cost governor charges against, with an explicit `cost_basis` field
  (`"estimated"` vs `"unknown_no_pricing_configured"`) — never a silently
  fake real cost.
- Unified the two token estimators that used to disagree by up to ~30% on
  the same text (`observability.estimate_tokens`'s `words*4/3` vs
  `orchestrator/cost_governor.py`'s own `chars/4`). There is now exactly one
  canonical estimator; `cost_governor._estimate_tokens` delegates to it.

### Added
- **`SIMPLICIO_PROMPT_TOON`** (default on) — TOON-encodes the uniform-array
  context blocks embedded into generation prompts (mapper handoff `files[]`,
  project-map `Relevant files`, `Precedent candidates`) instead of
  hand-rolled bullets; ~27% fewer tokens on the same content, measured with
  the canonical estimator over `bench/cases.json` — see
  `bench/results_toon_ab.md`. Falls back to compact JSON per-value for
  non-uniform arrays (logged at DEBUG). Set `SIMPLICIO_PROMPT_TOON=0` to
  restore the legacy bullet rendering.
- **`SIMPLICIO_LOG_ROOT`** — opt-in per-provider-call usage logging.
  `generate()`/`planner_complete()` append one `.simplicio/runs.jsonl` event
  per call (cache hit or miss) when this points at a project root; token
  counts are labeled `usage_source: "provider"` when the SDK/endpoint
  reported real usage (Anthropic `usage.input_tokens`/`output_tokens`,
  OpenAI-compatible `usage.prompt_tokens`/`completion_tokens`) or
  `"estimated"` otherwise.
- `simplicio.observability.record_savings_event()` — the producer side of
  the `.simplicio/ledger/savings-events.jsonl` ledger (`simplicio.savings-
  event/v1`), previously only hosted, never written, by this repo. TOON
  activation now emits one event per render call; the door is open for
  `#90`'s autoresearch template optimization to emit `source=autoresearch`
  events against the same ledger.
- `simplicio-dev-cli serve --mcp` — runs this CLI as a stdlib-only MCP
  stdio server (newline-delimited JSON-RPC 2.0, no new dependency) exposing
  `dev_cli_edit`, `dev_cli_validate`, and `dev_cli_memory` as MCP tools for
  any MCP client (Claude Code, Codex, Cursor, VS Code).
- `simplicio-dev-cli memory init|store|recall` — cross-vendor memory
  handoff, markdown + git under `~/.simplicio/memory/`
  (`SIMPLICIO_MEMORY_DIR` to override). Deterministic keyword recall, no
  LLM call. Ports the P0 slice of the `ai-memory`
  (JesseBrown1980/ai-memory) pattern; FTS5/vector-hybrid recall and the
  HRM validation toolchain are P1/P2 follow-up, not implemented here.
- mapper 0.14 `ask` wired into the pipeline: `map_ask(root, verb, arg)` runs the
  low-token structured queries (`simplicio.ask/v1`) and `inspect_target()` now
  embeds `impact` (dependents/flows the target touches) and `affected_tests`
  (`tests-for`) straight from the built artifacts. Fail-open like the 0.13
  integration: keys are only present when the CLI answered. Dependency floor
  raised to `simplicio-mapper>=0.14.0`.

### Added
- Exercise the mapper 0.13 surface end-to-end (fail-open, kill-switch
  `SIMPLICIO_MAPPER_CLI=0`): `artifact_status()` now embeds the per-artifact
  on-disk evidence + warnings from `simplicio-mapper inspect --json`
  (`simplicio.map-inspection/v1`) — surfacing through the `status` and
  `inspect` CLI payloads — and `build_mapper_context()` prefers the compact
  `handoff` context-pack (files/symbols/deps/`pack_hash`) over re-deriving
  context from `project-map.json`, honoring `needs_broader_context` as the
  fallback trigger. Any miss (binary absent, timeout, bad JSON) keeps the
  previous artifact-file behavior byte-for-byte.

## [0.9.1] — 2026-07-02

### Changed
- Raised the `simplicio-mapper` dependency floor to `>=0.13.0` (current release), so a
  fresh install resolves the mapper version this package is developed against.

## [0.9.0] — 2026-07-01

### Added
- `simplicio-dev-cli claims gate status` — explicit claims-gate command exposing
  the MEASURED/CANON/UNVERIFIED discipline as a first-class CLI surface, plus a
  resilient `inspect status` path that degrades gracefully when the compiled
  runtime is unavailable.
- `simplicio-dev-cli file read` — read raw file contents with optional
  line-range slicing, delegating to the native Rust `simplicio file read`
  binary when available (via `simplicio.runtime_bridge`) and falling back to a
  pure-Python implementation otherwise.
- `simplicio-dev-cli test run` — run the project's test suite through the CLI,
  mirroring the Rust CLI contract for consistent output between the compiled
  runtime and the Python fallback.

### Changed
- Documented the runtime-first execution chain: `simplicio-runtime` owns
  task/run/gate/evidence orchestration, `simplicio-dev-cli` remains the focused
  development/test executor, and decided mechanical writes should flow through
  `simplicio edit` when the compiled runtime is available.
- Added `simplicio-dev-cli edit` as a runtime-aware alias: it delegates to the
  compiled `simplicio edit` when available and falls back to the existing Python
  mechanical-edit executor when the runtime is absent or explicitly disabled.

## [0.7.1] — 2026-06-29

### Changed
- Bumped the Simplicio ecosystem mapper dependency floor to
  `simplicio-mapper>=0.11.0` so new installs pick up the latest Tier 1/2/3
  language coverage, async scan flow, and flowchart contracts already shipped
  by the mapper package.

## [0.7.0] — 2026-06-29

### Added
- Every LLM contact (doer `generate()` and planner `planner_complete()`, across
  all provider paths — Anthropic native, OpenAI-compatible, `claude-cli`/
  `codex-cli` shell-out, and in-process llama.cpp) now prepends a fixed
  `[OPERATING CONSTRAINTS]` block to the prompt: **no thinking** (no
  chain-of-thought, output only the result), **no internet** (no browsing/
  fetching), **tools only as strictly necessary**, **skills only as strictly
  necessary**. The doer is a mechanical task-to-diff worker and does not need
  to reason or reach the network. Prepended (not appended) so the template's
  strict `[OUTPUT]` block stays the last thing the model reads. Opt out with
  `SIMPLICIO_NO_LLM_DIRECTIVES=1`. The directives are part of the completion
  cache key, so cached entries stay consistent with what was sent.

## [0.6.0] — 2026-06-29

### Added
- `simplicio-py doctor` now runs a dependency-freshness check on every
  invocation: it compares each tracked package's installed version against
  its pyproject floor and the latest release on PyPI, and prints which
  packages have updates available. Tracked set = the Simplicio ecosystem
  triplet plus every declared pyproject dependency.
  - `--upgrade` runs `pip install -U` for every tracked package that is behind.
  - `--refresh` bypasses the 24h PyPI cache and forces a live lookup.
  - `--no-check-updates` skips the freshness block entirely.
  - `--json` output gains a `dependencies` object (`checked`, `upgraded`,
    `updates_available`).

### Changed
- Bumped Simplicio ecosystem dependency floors to the latest releases:
  `simplicio-mapper>=0.9.0` and `simplicio-prompt>=1.14.1`.
- Bumped third-party dependency floors: `sentence-transformers>=5.6.0`,
  `numpy>=2.5.0`, `anthropic>=0.112.0`, `openai>=2.44.0`. Optional `local`
  extra moved to `llama-cpp-python>=0.3.32` and `huggingface-hub>=1.21.0`.

- `simplicio-cli` console-script alias (alongside `simplicio-py` and `simplicio-dev-cli`), all
  pointing at `simplicio.cli:main`. Gives the package a command that matches its name on PATH;
  the bare `simplicio` stays reserved for the compiled Rust `simplicio-runtime`. Non-breaking —
  the existing entrypoints are unchanged.

### Fixed
- Made the runtime doctor contract use installed package metadata when available
  and report explicit Python adapter entrypoints without treating the reserved
  `simplicio` runtime command as a dev-cli tool.

## [0.5.20] — 2026-06-02

### Changed
- Renamed the Python CLI entrypoint from `simplicio` to `simplicio-py`.
  The canonical `simplicio` command now belongs to the compiled Rust
  `simplicio-runtime`; `simplicio-dev-cli` remains available as the explicit
  adapter command.

## [0.5.19] — 2026-06-02

### Added
- Standardized the local llama.cpp default on `openbmb/minicpm5:latest`, backed
  by `openbmb/MiniCPM5-1B-GGUF::MiniCPM5-1B-Q4_K_M.gguf`, while keeping
  `local-llama/default` as a backward-compatible alias.
- Added `simplicio.mechanical-edit/v1` dry-run/apply execution with compact
  result evidence, hash preconditions, allowlist checks, rollback on validation
  failure, and a `simplicio mechanical-edit` CLI.
- Added token-efficient primitives for log summaries, diff review, context
  cache, postconditions, structured retry payloads, codemod plans, and
  model-routing policy decisions.
- Added runtime-facing JSON contracts and a `simplicio-dev-cli` console
  entrypoint so `simplicio-runtime` can resolve the package as a first-party
  adapter.
- Expanded scratch recipes with FastAPI file upload, websocket, background
  worker, scheduled job, OAuth integration, and admin CRUD parity for Laravel,
  Gin, and Axum.

### Changed
- Updated ecosystem dependency floors to `simplicio-mapper>=0.8.0` and
  `simplicio-prompt>=1.14.0`.
- Clamped local `llama.cpp` execution defaults to avoid accidental memory
  spikes: context `2048`/max `4096`, threads max `4`, and output cap
  `512`/max `2048`, batch `128`, micro-batch `32`, GPU layers `0`,
  `mmap=true`, and `mlock=false`.

## [0.5.18] — 2026-06-02

### Changed
- Updated Python package dependency floors to the latest PyPI-compatible
  releases for the supported Python 3.10 runtime.
- Refreshed Python project templates and FastAPI recipes with current PyPI
  floors for generated projects.

## [0.5.17] — 2026-06-01

### Changed
- Changed the no-config and `--local` execution default to `local-llama/default`
  via `llama-cpp-python`, removing Ollama from the local default path.
- Updated `simplicio doctor` to validate/download the default
  `Qwen_Qwen3.5-2B-Q6_K.gguf` GGUF model instead of checking/pulling Ollama.
- Added GGUF header validation so corrupt local model files are not silently
  reused.

## [0.5.16] — 2026-06-01

### Changed
- Restored the original benchmark-heavy README guide under the new multilingual landing page so evidence, model comparisons, and operating policy remain visible.
- Added Project DNA notes to the localized README set and updated the globalization standard to require additive documentation refreshes.
- Updated ecosystem dependency floors to `simplicio-mapper>=0.7.3` and `simplicio-prompt>=1.13.3`.

## [0.5.15] — 2026-06-01

### Changed
- Rebuilt the README as a multilingual, benchmark-informed landing page with Star History, ecosystem graph, proof-first ordering, and the Simplicio globalization standard.
- Added canonical translations under `READMEs/` for English, Portuguese, Spanish, Japanese, Korean, Simplified Chinese, Italian, French, Russian, Polish, Hindi, Arabic, Hebrew, Malay, and Indonesian.
- Updated ecosystem dependency floors to `simplicio-mapper>=0.7.2` and `simplicio-prompt>=1.13.2`.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.14] — 2026-06-01

### Changed
- Default no-config local execution now uses Ollama
  `openbmb/minicpm5:latest`.
- `local-llama/default` is retained only as the fallback GGUF route and now
  points to `Qwen_Qwen3.5-2B-Q6_K.gguf` from
  `bartowski/Qwen_Qwen3.5-2B-GGUF`.
- Removed the automatic Qwen2.5-Coder GGUF fallback chain from the local
  provider defaults.
- Python package metadata now reflects the current ecosystem floors:
  `simplicio-mapper>=0.7.1` and `simplicio-prompt>=1.13.1`.
- Added `docs/PYTHON_PACKAGE_INTERDEPENDENCE.md` to record the acyclic package
  graph across mapper, prompt, cli, and sprint.

## [0.5.13] — 2026-06-01

### Changed
- Default local execution now prefers `Qwen3.5-2B-Q6_K.gguf` from
  `bartowski/Qwen_Qwen3.5-2B-GGUF`.
- The previous Qwen2.5-Coder 1.5B `Q8_0` and `Q6_K_L` GGUF files remain in the
  automatic fallback chain for offline setups that have not downloaded the new
  Qwen3.5 executor yet.
- Python package metadata now reflects the current ecosystem floors:
  `simplicio-mapper>=0.6.10` and `simplicio-prompt>=1.12.3`.

## [0.5.12] — 2026-05-31

### Changed
- `simplicio detect` now classifies Playwright + web + API + PostgreSQL local
  evidence prompts as feature-scale real-stack work and emits a feature-scope
  hint for the full-flow verification path.

## [0.5.11] — 2026-05-31

### Changed
- `simplicio detect` now treats remaining/missing endpoint or route backlogs
  (for example "32 rotas restantes") as sprint-scale work, so endpoint
  alignment continuations stay in the planner/decomposition path.

## [0.5.10] — 2026-05-31

### Changed
- `simplicio detect` now reports sprint scope for broad "all screens/all
  endpoints" alignment prompts and emits a sprint-scale hint, matching the
  multi-repo endpoint inventory workflow used by EVT.

## [0.5.9] — 2026-05-31

### Added
- `simplicio env-export <file>` parses dotenv files without evaluating them as
  shell code and prints shell-safe `export` lines, preserving semicolon-heavy
  values such as PostgreSQL connection strings.

## [0.5.8] — 2026-05-31

### Changed
- `simplicio index` now accepts a positional project root (`simplicio index
  path/to/repo`) in addition to `--root`, matching the mapper invocation style
  used during cross-repo endpoint alignment.

## [0.5.7] — 2026-05-31

### Changed
- Verify commands that invoke Node tooling now honor a project `.nvmrc` when
  `nvm` is installed, preventing false failures when the ambient shell uses an
  unsupported Node version.
- The ecosystem dependency floor now requires `simplicio-mapper>=0.6.6`, which
  preserves untracked-file Git status in mapper artifacts.

## [0.5.6] — 2026-05-31

### Changed
- `simplicio detect` now recognizes Portuguese Playwright/API/PostgreSQL
  evidence requests as code work, so QA prompts such as local web-to-API smoke
  validation are routed into the Simplicio execution flow.

## [0.5.5] — 2026-05-31

### Changed
- Precedent indexing now maps rich stack labels such as `node-ts-angular`,
  `react-vite`, `csharp-aspnet` and `dotnet-*` onto the existing lightweight
  scanners instead of raising `KeyError`.
- Unknown stack labels now return no grep candidates during `simplicio index`
  and keep the existing safe fallback message in prompt precedent generation.
- `simplicio index` no longer loads the legacy embedding model by default,
  avoiding native OpenMP crashes during cheap repo scans; set
  `SIMPLICIO_ENABLE_EMBED_INDEX=1` to opt into the old embedding cache path.
- The `simplicio-mapper` dependency floor now points at `0.6.5`, which skips
  generated Playwright output during project-map refreshes.

## [0.5.4] — 2026-05-31

### Changed
- `simplicio run --scope scratch` now forwards `--root` into the scratch
  stack detector, allowing existing projects to be analyzed by filesystem
  markers before a planner is called.
- Scratch stack inference now detects existing `.slnx`/`.csproj`, Angular,
  FastAPI, Streamlit and Typer projects from the target root.
- `simplicio detect` accepts positional prompt text and recognizes
  Portuguese endpoint/screen alignment requests as code work.
- Auto-scope classification treats broad endpoint/screen inventories as
  sprint-scale work so the planner can decompose them instead of forcing a
  single-file task path.

## [0.5.3] — 2026-05-31

### Changed
- `SIMPLICIO_PLANNER=local-llama/default` now runs the planner through the same
  local GGUF backend as the doer, preserving the Q8_0 primary and Q6_K_L
  fallback route in fully local SendSprint/SimplicioCode flows.
- Added a deterministic Markdown evidence executor and php-vanilla docs-marker
  recipe so explicit `docs/*.md` marker tasks can complete without planner
  drift.
- Feature-scope orchestration now tries deterministic scratch codegen before
  falling back to the LLM pipeline, matching the path used by SendSprint.

## [0.5.2] — 2026-05-31

### Changed
- Default local execution now prefers `Qwen2.5-Coder-1.5B-Instruct-Q8_0`
  with `Q6_K_L` fallback from `~/.simplicio/models/executor`.
- `simplicio task` now applies generated diffs through `git apply` before
  reporting success, propagates failed non-JSON runs with exit code `1`, and
  records the extracted patch at `.simplicio/last_patch.diff`.
- The patch gate accepts external `SIMPLICIO_TEST_CMD` evidence and retries
  Git hunk count mismatches with `git apply --recount`, making small local
  models usable in SendSprint/SimplicioCode flows without weakening Git's
  apply check.

## [0.5.1] — 2026-05-31

### Changed
- Close out the **LLM-reduction roadmap (issue #33)**. All four levers ship and
  are exercised by the test suite:
  - **D — content-addressed completion cache** (`simplicio/_cache.py`,
    `simplicio cache stats|clear`) with session hit/miss/put telemetry.
  - **C — static verify-loop fixers** (`simplicio/pipeline_fixers.py`).
  - **A — declarative plan recipes** (`simplicio/scratch/recipes.py`).
  - **B — mechanical task executors** (`simplicio/scratch/codegen/*`) for
    Python, TypeScript, Go, Rust and PHP, dispatched ahead of any task-level
    LLM call.
- The remaining empirical release-validation gate — a real 50-goal
  codegen-disabled LLM baseline measuring B/codegen pass-rate and latency — is
  tracked separately as a dedicated release-validation issue and does not block
  this release. The repo-local closure audit
  (`bench/results_issue_closure_audit.*`) continues to report that gate as open
  by design, so partial evidence is never claimed as complete.

## [0.5.0] — 2026-05-31

### Added
- **Path 4: in-process local inference via `llama-cpp-python`** (issue #42).
  A new offline-first provider runs a GGUF model directly in the Python
  process — zero API key, zero HTTP overhead. The model is loaded once and
  reused across calls.
  - **Default local model:** `Qwen2.5-Coder-1.5B-Instruct-Q5_K_M` from
    `bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF`, fetched once from the
    Hugging Face Hub.
  - **Auto-default:** when neither `SIMPLICIO_MODEL` nor `SIMPLICIO_BASE_URL`
    is set, simplicio now routes to this local model instead of erroring.
  - **Explicit route:** `SIMPLICIO_MODEL=local-llama/<repo>::<file.gguf>`,
    `local-llama/default`, or `local-llama//abs/path/model.gguf`.
  - **`simplicio task --local`** forces the local model regardless of ambient
    config.
  - **Tuning knobs:** `SIMPLICIO_LOCAL_MODEL_PATH`, `SIMPLICIO_LOCAL_MODEL_REPO`,
    `SIMPLICIO_LOCAL_MODEL_FILE`, `SIMPLICIO_LOCAL_CTX`,
    `SIMPLICIO_LOCAL_THREADS`, `SIMPLICIO_LOCAL_GPU_LAYERS`,
    `SIMPLICIO_LOCAL_MAX_TOKENS`, `SIMPLICIO_LOCAL_TEMP`.
  - New optional extra: `pip install 'simplicio-cli[local]'`
    (`llama-cpp-python>=0.3.2`, `huggingface-hub>=0.23`).

### Changed
- `simplicio` with no provider configured no longer raises — it falls back to
  the local Qwen model (offline-first). Set `SIMPLICIO_BASE_URL` or
  `SIMPLICIO_MODEL` to opt back into a remote provider.

## [0.4.4] — 2026-05-30

### Added
- Commit `.simplicio/project-map.json` and `.simplicio/precedent-index.json`
  so downstream LLM executions can load the repository map directly.

## [0.4.3] — 2026-05-29

### Changed
- Align Simplicio ecosystem dependency floors with the latest published
  releases: `simplicio-mapper>=0.6.1` and `simplicio-prompt>=1.12.0`.
- Synchronize the package runtime `__version__` with the PyPI release version.

## [0.4.2] — 2026-05-29

### Added
- `simplicio task --dry-run-task --json` for SendSprint orchestration. It
  generates the would-be task output, returns the stable
  `{task_id, applied, files_changed, tokens_used, cost_usd, diff_summary,
  warnings}` JSON contract, and does not write `.simplicio/last_output.txt` or
  run the test/apply loop.
- `simplicio task --bound-paths <glob>` repeatable edit-surface guard. Generated
  diffs outside the allowed globs are refused before the test loop and reported
  as JSON warnings.

### Changed
- **`rust/simplicio-core`: PyO3 `0.22` → `0.28`** (manual major dependency bump,
  per `.specs/workflow/DEPENDENCY_POLICY.md`). The `build_6layer_prompt` / `hello`
  extension now builds against current PyO3. No source changes to `lib.rs` — the
  existing `Bound<'_, PyModule>` / `#[pyfunction]` API is forward-compatible.

### Fixed
- **Build blocker on Python 3.14.** PyO3 0.22 capped at CPython 3.13, so the crate
  failed to compile against the 3.14 default interpreter. Now builds natively on
  CPython 3.14.5 (cp314 wheel): parity suite 5/5, ~8.5x over the Python reference,
  and the Rust-assembled prompt drives `qwen2.5-coder:3b` to 5/6 on the real-pytest
  exec bench. See `bench/results_rust_qwen.md`.

## [0.4.1] — 2026-05-28

### Added
- **Dependency-update policy and enforcement** (closes #21):
  - `.specs/workflow/DEPENDENCY_POLICY.md` — ecosystem version policy:
    semver, floor-pinning (`>=`), 15-day floor-bump rule after upstream
    release, no cyclic deps, release-sync checklist.
  - `.github/workflows/check-deps.yml` — daily CI (and on every PR
    touching `pyproject.toml`) that compares pinned floors against the
    latest published version of every ecosystem dependency on PyPI and
    fails the build with `::error::` annotations when one is at least
    a minor behind.
  - `.github/dependabot.yml` — weekly grouped updates for `pip`
    (ecosystem packages grouped), `cargo` (`rust/simplicio-core`), and
    `github-actions`. Patches auto-merge, minor/major wait for review.

### Changed
- `simplicio-mapper>=0.5.0` → `>=0.6.0` (catch up with upstream 0.6.0).
- `simplicio-prompt>=1.7.0` → `>=1.9.0` (catch up with upstream 1.9.0).

Both bumps validated locally: `pytest tests/python` stays 38/38 green
with the new versions installed.

## [0.4.0] — 2026-05-28

### Added
- **Real-execution benchmark on a real project (`wesleysimplicio/sistema-sindico`).**
  New `bench/run_exec_sindico.py` harness writes each model's PHP output
  into a working copy and scores by `vendor/bin/phpunit` exit code over the
  full production suite. 12 cases cover `src/Core/`, `src/Middleware/`,
  `src/Repositories/`, routing, and one bug-fix scenario that scores
  against the existing `PasswordPolicyTest`. Headline on 9 models × 4
  tasks: baseline 33% → simplicio-cli **64%** (+31 pts).
  Reports: `bench/results_exec_sindico.{md,pdf,json}`.
- **17-model regex re-run + old→new comparison.** `bench/run_offline.py`
  gained a local `transformers` backend for HF-only small models, HTTP
  retry with exponential backoff (`BENCH_HTTP_RETRIES`), and `--pdf-only` /
  `--report-only` modes for regenerating reports without re-calling models.
  New `bench/compare_versions.py` joins the published per-model numbers
  with the fresh re-run side by side; 14 of 17 returned clean data
  (with simplicio averaged 86% → **88%**, within noise of the prior
  publication). Three frontier models hit account-level provider failures
  and are flagged `n/a` with the reason in the report.
  Reports: `bench/results_comparison.{md,pdf}`, merged data in
  `bench/results_all.json`.
- **Fan-out benchmark using the real `simplicio-prompt` kernel.** New
  `bench/run_fanout.py` instantiates `kernel.subagent_runtime.SubagentRuntime`
  from the PyPI package and launches real parallel LLM calls through
  `LaneWorkerPool`. Every subagent output gets scored two ways: real
  PHPUnit (functional) and a structural regex check. Default N=200 (the
  level where harder tasks recover from per-call noise).
- **Three-side comparison report (`bench/compare_sp.py`).** Generates a
  focused "with vs without simplicio-prompt" report from any sp-enabled
  exec validation JSON, with a data-quality guard that flags models whose
  calls returned no model output (HTTP 402 / empty bodies / etc.) so the
  numbers never silently average in noise.
- **`simplicio/utils/` package (Performance Phase 1, closes #14):**
  - `http_client.py` — lazy singleton `httpx.Client` with connection
    pooling and env-driven timeouts; `post_json()` helper.
  - `serialization.py` — orjson-backed `dumps` / `dumps_str` / `loads`,
    with stdlib `json` fallback so the import never breaks.
  - `cache.py` — `diskcache` namespaces under `.simplicio/cache/` plus a
    `memoize_disk(namespace=, ttl=)` decorator.
- **`simplicio-core` Rust crate (closes #15, #17, #18):**
  - New `rust/simplicio-core/` with PyO3 0.22 + bumpalo. Build with
    `cd rust/simplicio-core && maturin develop --release`.
  - `simplicio_core.build_6layer_prompt(...)` runs the substitution +
    comment-strip step of `build_prompt` in Rust. **4.9x faster
    (12.4 µs → 2.5 µs)** on the real template, byte-equal to the Python
    reference. UTF-8-safe walker handles multibyte content (em-dashes,
    etc.) without corruption.
  - `simplicio/prompt.py` picks the Rust path when the extension is
    installed and falls back to the extracted `_assemble_python`
    reference implementation otherwise. The CLI's runtime deps do not
    include `simplicio-core`, so a pip-only install (no Rust toolchain)
    keeps working.
- **`simplicio-prompt>=1.7.0` and `simplicio-mapper>=0.5.0` as runtime
  dependencies.** README install section documents the three Simplicio
  packages and their per-scope roles.
- **README rewrite to "real project, real tasks, real test suite".**
  Section 1 leads with the real-PHPUnit benchmark on sistema-sindico;
  Section 2 explicitly labels the regex tables as a complementary
  *contract-adherence* metric (not a runtime proof). The HF Qwen2.5-Coder
  re-run is documented honestly with the n/a callouts for the
  paywall-blocked frontier models.

### Changed
- `simplicio/mapper.py`, `simplicio/observability.py`, `simplicio/init.py`
  switched from stdlib `json` to the new orjson-backed helpers (13x
  faster on the bench payloads).
- `simplicio/prompt.py` caches the 6-layer template through an
  `lru_cache(maxsize=4)` so it is read once per process instead of every
  call.
- `bench/run_offline.py` extracts report generation into
  `build_reports(by_model, cases)` so md/pdf/charts can be regenerated
  from results.json without re-calling any model (`--report-only`).
- README fanout claim rewritten against actually measured data (the
  earlier "N=64 is the sweet spot" came from a single-task run with
  `use_cache=True` that triggered ReceiptCache dedup; cache-off partial
  data shows N depends on task difficulty).
- `BENCH_FANOUT_NS` defaults to a single value (`"200"`) for our chosen
  production operating point; sweep across multiple Ns by setting the
  env var explicitly.

### Fixed
- 7B-only re-run in the Qwen2.5-Coder benchmark recovered one case
  that hit a transient SSL `CERTIFICATE_VERIFY_FAILED` on the HF router
  (single-call empty result was inflating the gap by ~2 points). Merged
  cleanly with the 1.5B/3B data through the new `--report-only` path.

## [0.3.0] — 2026-05-27

### Added
- Real mapper consumption for `.simplicio/project-map.json` and
  `.simplicio/precedent-index.json`, including relevant files, architecture
  signals, modules, recent changes, and fallback target inspection.
- Structured precedent retrieval from the mapper `precedent-index.json` before
  falling back to embedding-based grep candidates.
- Model-adaptive prompt scaffolding plus lightweight task decomposition for
  smaller/local models.
- Pre-apply output validation, failure classification, and targeted retry
  feedback for syntax, assertion, dependency, timeout, runtime, and unknown
  failures.
- Opt-in run observability at `.simplicio/runs.jsonl`, recording prompt
  variant, model/provider, estimated tokens, modes, targets, attempts, and
  failure class.

### Changed
- Benchmarks now log baseline/pipeline runs and report hallucinated-target
  flags alongside pass rate.
- Prompt template now injects a model adaptation/decomposition layer while
  preserving the DIFF + TEST + EVIDENCE output contract.

## [0.2.12] — 2026-05-26

### Added
- **Zero-step bootstrap**: the first time `simplicio` is invoked after
  `pip install`, if `~/.claude/` exists and the hook is missing, the skill +
  UserPromptSubmit hook are installed automatically. PEP 517 wheels can't run
  code on `pip install`, so the bootstrap happens on first CLI use — the
  closest equivalent that works on every machine. Idempotent. Subcommands
  `init` and `detect` are excluded (no loops). All failure modes silently
  no-op so the CLI never breaks because of auto-activation. Opt-out:
  `export SIMPLICIO_SKIP_AUTO_INIT=1` before the first call.
- README sections:
  - "How it works at runtime" — explains the two layers (skill = semantic,
    hook = deterministic) and what flows on every prompt.
  - "Why UserPromptSubmit and not PreToolUse" — UserPromptSubmit fires once,
    before tool decision, with the raw prompt; PreToolUse fires after the
    decision and per tool call without access to the prompt.
  - "Disable / re-enable" matrix — env var, manual removal, dry-run, repair,
    skill-only path.
  - "How you use it — pick your path" — upfront 2-path matrix (Claude Code
    zero-key vs standalone CLI with API key), with end-to-end examples for
    each path so the user can decide which one applies in 30 seconds.
  - "The pipeline (both paths)" — clarifies that whichever entry point is
    used, the underlying engine (precedent → skill → 6-layer → LLM → apply
    → test → retry) is the same.
  - "Common questions" FAQ — covers the four most asked questions: does it
    work with a Claude Pro subscription alone, how to run it in CI without
    Claude Code, the ChatGPT Plus / Codex CLI situation (not auto-wired),
    when the skill actually fires, and how to turn it off.
  - Tagline updated to lead with "Zero API key inside Claude Code" so the
    PyPI / GitHub landing page makes the no-key-needed path obvious.
- `tests/python/test_cli_autoinstall.py` — 5 tests covering the env opt-out,
  missing `~/.claude/`, `init`/`detect` subcommand exclusion, fresh install,
  and already-installed short-circuit.

### Changed
- `simplicio/cli.py`: new `maybe_autoinstall(cmd)` helper called once after
  argparse, before dispatch. Errors are caught and logged to stderr without
  raising. `from __future__ import annotations` added for Python 3.9
  compatibility on the new type hints.

## [0.2.11] — 2026-05-26

### Added
- `simplicio init` — one-shot installer that drops the `simplicio-cli` skill
  into `~/.claude/skills/simplicio-cli/SKILL.md` and merges a
  `UserPromptSubmit` hook entry into `~/.claude/settings.json` (with a
  `.bak` backup of the previous settings). Idempotent. `--dry-run` shows the
  plan without writing.
- `simplicio detect` — pure-Python heuristic (no LLM) that scores a prompt for
  code-edit intent (verbs + file extension + code nouns + explicit invocation
  cues, with a negative-cue list for read-only questions). Prints a
  `[SIMPLICIO_PROMPT_HINT]` block to stderr when the score crosses the
  threshold. `--json` for machine-readable output, `--quiet` to suppress the
  hint.
- Shipped templates: `simplicio/templates/SKILL.md` (skill body) and
  `simplicio/templates/userpromptsubmit-hook.sh` (hook wrapper). Both packaged
  in the wheel via `tool.setuptools.package-data`.
- README section "Auto-activation in Claude Code" explaining the
  two-mechanism (skill + hook) design and the single-command install flow.

### Changed
- `simplicio/cli.py` — heavy imports (numpy via `precedent`, providers SDKs)
  are now lazy: `simplicio init`, `simplicio detect`, and `--help` start
  instantly without paying for them.
- `tool.setuptools.package-data` now includes `templates/*.sh`.

### Notes
- Skill-only path: when `simplicio` is not on PATH or the user never runs
  `simplicio init`, behavior degrades gracefully — the hook script no-ops, and
  the skill still triggers on description match when the project ships a copy
  in `.skills/simplicio-cli/`. End-users without `simplicio init` get the
  description-matching tier (~80% coverage); with `simplicio init` they get
  the deterministic-fallback tier (~98%).

## [0.2.10] — 2026-05-26

### Added
- Skill `simplicio-cli` (`.skills/simplicio-cli/SKILL.md` + global mirror at
  `~/.claude/skills/simplicio-cli/SKILL.md`) — auto-triggers when the user asks
  for a small/medium code edit on a known file. Maps the natural-language goal
  to `simplicio task --stack <s> --target <f> --criteria <…> --constraints <…>`,
  runs verify-loop, and reports diff + test result. Pushy trigger description
  covers explicit invocations (`$simplicio`, "use simplicio") plus implicit
  cues (small/local model, verify-loop / pass-rate / 6-layer keywords).
- Registered the skill in `.skills/README.md` table.

## [0.2.9] — 2026-05-26

### Added
- Wider 4-quadrant run: 3 models × 10 cases (qwen partial 5/10),
  max_iters=5 — `google/gemma-3-4b-it`, `meta-llama/llama-3.2-3b-instruct`,
  `qwen/qwen-2.5-7b-instruct`. Aggregate over 25 observed (model × case)
  tuples: Q1 = 0%, Q2 = 64%, Q3 = 44%, **Q4 = 76%**. All three falsifiable
  hypotheses (loop-alone closes the gap, simplicio-alone is enough, gains
  stack linearly) **rejected** at |Δ| ≥ 5 pts.
- New report `bench/results_4quadrant_wide.md` + raw artefact
  `bench/results_4quadrant_wide.json` reconstructed from the wide run log.
- README "Run 2 — wider multi-model" subsection with per-model breakdown,
  decomposition table and hypothesis verdicts.

### Changed
- `pyproject.toml` version bumped 0.2.8 → 0.2.9.
- README "First run on record" subsection renamed to "Run 1 — focused
  single-model" for symmetry with Run 2.

### Notes
- Wide run was killed mid-execution; `claude-3.5-haiku` not reached.
  Reproduce command for the full intended run is documented in
  `bench/results_4quadrant_wide.md`.

## [0.2.8] — 2026-05-26

### Added
- 4-quadrant benchmark harness `bench/run_4quadrant.py` — isolates two
  axes (prompt structure × execution model) on the same model, same cases,
  same checks. Q1 raw 1-shot (baseline), Q2 simplicio 1-shot (current bench),
  Q3 loop on raw goal, Q4 loop on simplicio goal (composition).
- Methodology doc `docs/benchmark-4quadrant.md` — explains the matrix,
  feedback shape, metrics, hypothesis decomposition (loop-alone /
  simplicio-alone / linear-stacking falsification tests), cost model and
  limitations.
- README section "### 4-quadrant bench — agent × simplicio matrix" with
  reproduce command and matrix decomposition formulas (Q2-Q1, Q3-Q1, Q4-Q3,
  Q4-Q2, Q4-max(Q2,Q3), Q4-linear).
- Optional dependency group `[project.optional-dependencies] bench`
  shipping `fpdf2>=2.7` for the PDF report. Install via `pip install -e ".[bench]"`.
- Outputs `bench/results_4quadrant.{md,pdf,json}`, charts under
  `bench/charts/4q_*.svg`, raw per-iteration outputs under
  `.simplicio/bench_4q/<model>/case_NN/q*_iter*.txt` for audit.

### Changed
- `pyproject.toml` version bumped 0.2.7 → 0.2.8.

## [0.2.7] — 2026-05-26

### Added
- Agent spec `.agents/simplicio-ralph.agent.md` — composição do padrão Ralph Loop
  com o `simplicio-cli` como gerador de código no passo `execute`. Lido por
  Claude Code, Codex CLI, GitHub Copilot, Cursor, Hermes, OpenClaw, Aider.
- ADR-002 `.specs/architecture/ADR-002-simplicio-ralph-composition.md` —
  registra a decisão arquitetural de **compor** com ralph-loop em vez de
  inchar o CLI com `simplicio review`, `simplicio refactor`, etc. Documenta
  alternativas avaliadas, trade-offs e critério de revisão (6 meses).
- Doc `docs/agent-architecture.md` — visão única da arquitetura agentic
  (4 camadas: orquestrador → roteamento → simplicio-cli → provedores LLM),
  matriz de roteamento por tipo de task, fluxo end-to-end, invocação por
  ferramenta, limitações conhecidas e como o orquestrador compensa.

### Changed
- `AGENTS.md` e `CLAUDE.md` (mirror) — entry novo na lista de "Custom agents
  disponíveis" apontando para `simplicio-ralph.agent.md`.
- `.agents/README.md` — diagrama de arquivos listados inclui o agent novo.

### Notes
- **Aditivo only.** Zero linha de código mexida em `simplicio/*.py`, `bench/`,
  `README.md` ou `README.pt-BR.md`. Benchmarks publicados permanecem
  reproduzíveis com a mesma versão do código.

## [0.2.6] — 2026-05-26

### Added
- Third bench run on record — **tiny sub-4B models** via OpenRouter. Five
  models, 10 cases, 50 runs/side, 260 checks:
  - `google/gemma-3-4b-it`: **38% → 96%** (+58 pts)
  - `meta-llama/llama-3.2-3b-instruct`: **28% → 73%** (+45 pts)
  - `google/gemma-3n-e4b-it`: **44% → 88%** (+44 pts)
  - `microsoft/phi-4-mini-instruct`: **36% → 73%** (+37 pts)
  - `meta-llama/llama-3.2-1b-instruct`: **26% → 40%** (+14 pts)
  - **Tiny avg: 35% → 74% (+39 pts, +112% relative)**
- `bench/results.md` now has three sections (tiny → frontier → mid-tier
  archival), 14 models total across three runs.

### Changed
- README headline updated: **"Fourteen models tested across three runs"**
  with the tiny table positioned **above** the frontier table per request.

### Notes
- 8 of the 11 originally requested sub-4B models are **not hosted on
  OpenRouter** (Gemma 3 270M, Gemma 3 1B, Gemma 2 2B, Qwen3 0.6B, Qwen3 1.7B,
  Qwen2.5 0.5B, Qwen2.5 1.5B, Qwen 3B, Nemotron Nano 4B — OR's smallest
  Nemotron is 9B). Closest available substitutes were used.
- Output-quality on tiny rerun: DIFF block **0% → 74%**, target file
  mentioned **0% → 84%**, TEST block **82% → 80%**.
- Cost on tiny rerun: tokens 1,006 → 1,289 per run (+28%); wall-clock
  **15.6s → 9.1s per run (−42% — faster *with* simplicio)** because the
  raw side often emits long chatty answers while the contract clamps output
  shape.

## [0.2.5] — 2026-05-26

### Changed
- README and `bench/results.md` now list **all nine models** tested across both
  bench runs — six frontier 2026 models (current headline) plus the three
  mid-tier 7B–12B open models from the earlier v0.2.2 run (archival). The full
  set is explicit so readers can see every model the harness has hit.
- Re-ran the frontier bench (same 6 models, same 10 cases, `max_tokens=8192`).
  Headline moved **40% → 95%** (prior 0.2.4 numbers) to **41% → 99%** (+58 pts,
  +136% relative). Five of six frontier models hit **100% pass-rate**; smallest
  per-model gain is **+52 pts** (DeepSeek V4 Pro), largest **+62 pts** (GPT-5.5).
- Output-quality signals on the rerun: DIFF block **36% → 98%**, target file
  mentioned **1% → 100%**, TEST block **88% → 98%**.
- Cost on the rerun: tokens 1,967 → 3,168 per run (+61%); wall-clock 46.1s →
  57.6s per run (+24%); 118,040 → 190,119 total tokens across 60 runs/side.

## [0.2.4] — 2026-05-26

### Changed
- Re-ran the full offline bench against six **frontier 2026 models** —
  DeepSeek V4 Pro, Qwen 3.7 Max, Kimi K2.6, GPT-5.5, Claude Opus 4.7,
  and Gemini 3.5 Flash — replacing the previous trio of mid-tier 7B–12B
  open models in the headline numbers.
- Bench harness (`bench/run_offline.py`):
  - Raised `max_tokens` from 900 → 8192 to accommodate reasoning-heavy
    models (GPT-5.5, Kimi K2.6, Claude Opus 4.7) that need room to emit
    DIFF + TEST + EVIDENCE without hitting the length cap.
  - Added a `reasoning` field fallback when `message.content` is null
    (some providers return the answer under `reasoning` for thinking models).
- README and `bench/results.md` refreshed with the new headline numbers.

### Results (60 runs per side, 312 checks)
- Overall: **40% → 95%** (+55 pts, +139% relative).
- Per-model gains:
  - Kimi K2.6: **36% → 100%** (+64 pts).
  - GPT-5.5: **36% → 98%** (+62 pts).
  - Gemini 3.5 Flash: **40% → 100%** (+60 pts).
  - Claude Opus 4.7: **44% → 96%** (+52 pts).
  - Qwen 3.7 Max: **42% → 92%** (+50 pts).
  - DeepSeek V4 Pro: **40% → 88%** (+48 pts).
- DIFF block presence: **33% → 95%**.
- Target file mentioned: **0% → 98%**.
- TEST block presence: **85% → 95%**.

### Cost
- Tokens / run: 1,566 → 2,686 (+71%) — reasoning-class models spend more
  completion tokens when wrapped in the contract because they produce the
  full DIFF + TEST + EVIDENCE the contract demands.
- Wall-clock / run: 35.4s → 45.6s (+29%).
- Trade-off: ~2× tokens, +55 pass-rate points and a 95% DIFF-block rate.

## [0.2.3] — 2026-05-26

### Changed (BREAKING)
- Translated the entire codebase to English: docstrings, comments, variable
  names, function names, prompt template, and bench case data.
- **CLI flag renames** (breaking for any saved invocations):
  - `--alvo` → `--target`
  - `--criterios` → `--criteria`
  - `--restricoes` → `--constraints`
  - positional `objetivo` → `goal`
- **Internal function renames** (breaking for anyone importing `simplicio.*`):
  - `prompt.montar` → `prompt.build_prompt`
  - `providers.gerar` → `providers.generate`
  - `precedent.montar_bloco_precedente` → `precedent.build_precedent_block`
  - `precedent.grep_candidatos` → `precedent.grep_candidates`
  - `skill_router.montar_bloco_skill` → `skill_router.build_skill_block`
- **Bench JSON keys renamed** in `bench/cases.json` and
  `bench/cases_offline.json`: `objetivo/alvo/criterios/restricoes` →
  `goal/target/criteria/constraints`.
- Prompt template slot renames: `{{OBJETIVO}}/{{ALVO}}/{{PRECEDENTE}}/{{CRITERIOS}}/{{RESTRICOES}}`
  → `{{GOAL}}/{{TARGET}}/{{PRECEDENT}}/{{CRITERIA}}/{{CONSTRAINTS}}`.
- Prompt template now emits `[GOAL] / [TARGET] / [CONTRACT] / [OUTPUT]`
  blocks instead of the Portuguese `[OBJETIVO] / [ALVO] / [CONTRATO] / [SAIDA]`.

### Why
- Repo is intended for an international audience; mixed-language internals
  hurt onboarding and review.
- Aligns with the project's own English-first README, benchmark, and PyPI
  copy that were already in place since v0.2.0.

## [0.2.2] — 2026-05-26

### Added
- Benchmark harness (`bench/run_offline.py`) now captures per-call token
  usage (`usage.prompt_tokens` / `completion_tokens` / `total_tokens`) and
  wall-clock latency (`time.perf_counter()`) for every model call.
- `bench/results.md` gained a "Cost — tokens & wall-clock" section with a
  per-model table and aggregate totals over 30 runs per side.
- README now reports honest cost numbers alongside pass-rate.

### Changed
- Re-ran the full bench against OpenRouter; refreshed all numbers in
  `README.md` and `bench/results.md`:
  - Overall: **35% → 90%** (+55 pts, +156% relative) over 156 checks.
  - Gemma 3 12B: **34% → 92%** (+58 pts).
  - Llama 3.1 8B: **36% → 90%** (+54 pts).
  - Qwen 2.5 7B: **34% → 88%** (+54 pts).
- Wall-clock per run dropped from **12.4s → 9.9s (−21%)**; token cost per
  run shifted from 759 → 770 (+1%). simplicio is faster *and* better at
  ~same token bill.

### Results
- DIFF block presence: **0% → 100%**.
- Target file mentioned: **0% → 96%**.
- TEST block presence: **80% → 96%**.

## [0.2.1] — 2026-05-26

### Added
- README hero image generated with `gpt-image-2`, including a web-sized PNG and
  source PNG under `output/imagegen/`.

### Changed
- README top section now includes the visual pipeline summary from one-line task
  to verified code change.

## [0.2.0] — 2026-05-26

### Added
- Multi-model offline benchmark harness (`bench/run_offline.py`):
  3 models · 10 cases · 156 checks · SVG charts (stdlib only).
- Output-quality signals: DIFF block, TEST block, target-file mention,
  criteria-keyword coverage, output length.
- PyPI metadata: authors, license, classifiers, keywords, project URLs,
  package-data for `simplicio/templates/*.md`.
- PyPI badges and marketing hero in README with real numbers.
- `.gitignore` entry for `.env`.

### Changed
- Bumped version `0.1.0` → `0.2.0`.
- README: provider-agnostic install instructions (`pip install simplicio-cli`).
- Benchmark results re-generated against working OpenRouter models
  (qwen 2.5 7B, llama 3.1 8B, gemma 3 12B).

### Results
- Overall: **37% → 91%** (+54 pts, +145% relative) over 156 checks.
- Llama 3.1 8B: **34% → 98%** (+64 pts).
- Gemma 3 12B: **38% → 94%** (+56 pts).
- Qwen 2.5 7B: **38% → 80%** (+42 pts).
- DIFF block presence: **0% → 100%**.
- Target file mentioned: **3% → 96%**.

## [0.1.0] — 2026-05-25

### Added
- Initial release of `simplicio-cli`.
- Pipeline: mapper → precedent → skill-router → 6-layer prompt → verify loop.
- Content-hash embedding cache under `.simplicio/`.
- Provider-agnostic LLM client (any OpenAI-compatible endpoint + Anthropic native).
- CLI commands: `index`, `task`, `bench`, `smoke`.

[0.2.12]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.12
[0.2.11]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.11
[0.2.10]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.10
[0.2.9]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.9
[0.2.8]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.8
[0.2.7]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.7
[0.2.6]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.6
[0.2.5]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.5
[0.2.4]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.4
[0.2.3]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.3
[0.2.2]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.2
[0.2.1]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.1
[0.2.0]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.2.0
[0.1.0]: https://github.com/wesleysimplicio/simplicio-cli/releases/tag/v0.1.0

## Improvements during EVT real-stack validation (2026-05-31)

- Enhanced support for analysis of existing projects with real backend + DB (used while validating Web + API + local Postgres connection via Playwright).
- Better guidance and helpers for E2E contract validation tasks between frontend and backend.

These changes were driven by the need to generate strong evidence that the Web is correctly wired to the real API + real PostgreSQL.
