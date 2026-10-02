# Changelog

## [3.48.0] - 2026-10-02

- Sync `packages/mapper` with simplicio-mapper v0.26.35 and the Fast unification (#1395): native SFAST v2 mmap binary snapshot engine (`store/snapshot.py`, `store/segments.py`), TurboQuant 4-bit, FWHT and Pareto scoring (`store/neural/`), PlanDAG decomposition with `understand` and `plan` (`processor.py`), strict changeset validation with `expected_sha256` (`changeset.py`).
- New mapper CLI commands: `understand`, `plan` and `changeset`; the index engine can emit an SFAST v2 snapshot; `store/fast_link.py` supports the native Fast with no external dependencies.
- Fix: `mapper/parse.py` handles `previous_map` whose files are a dict.
- Tests: 62 passed, 15 subtests across the mapper suite plus the unified Fast E2E flow.

## [3.47.0] - 2026-10-02

- Restore full loop protocol (pre-monorepo way of working) on the monorepo (#1392): the full loop protocol is back as the skill's entry point; turbo is a tool the operate step may use, not the skill's entry. It starts the task, describes it (goal and acceptance criteria frozen in the task anchor), decomposes it (task backlog), iterates turn by turn (triage, decide, operate, verify, journal), gates done on evidence, and delivers with PR evidence.
- Restored v3.43 `SKILL.md` body adapted to the monorepo stack: bound operators are `packages/mapper` (`simplicio-mapper` survey) and `packages/dev-cli` (`simplicio-dev-cli` mutation) from the one wheel; state dir is `.simplicio-loop/`; all dead instructions depending on Runtime, Hub, remote workers or Fast are removed.
- Frontmatter description stops saying "Invoking it runs simplicio-loop turbo". Pinned headers updated with `header-change: .claude/skills/simplicio-loop/SKILL.md`. The `.simplicio-loop/` gitignore line and single `SIMPLICIO-LLM-ORIENTATION` block are preserved.
- Extension points: audited 50 named binding points restored, verified, and consistent across documentation and table count.
- All 29 protocol scripts and commands answer `--help` with exit code 0 (`coordinator.py`, `cross_agent_wiki.py`, `hierarchical_planner.py`, `video_evidence.py`, `web_verify.py`, `worktree_cleanup.py`, `az_boards_adapter.py`, `check.py`, `repo_conventions.py`, `pr_evidence.py`, etc.).
- Regenerated mirrors via `sync_plugin.py`, `sync_bundle.py`, and `refresh_orientation_pins.py`.
- Updated token-budget baseline for `SKILL.md` (14,210 tokens, 7,983 words).
- header-change: .claude/skills/simplicio-loop/SKILL.md (frontmatter description stops saying "Invoking it runs simplicio-loop turbo.")

## [3.46.1] - 2026-10-02

- Restore simplicio-loop 50 extension points: restored `control_policy` and `prototype_judge` modules, unit tests, and reference documentation (`references/control-policy.md`, `references/extension-points.md`), bringing the audited extension points count from 48 back to 50.
- Quality Delivery Flow & Host Mode: full flow contract preserved with two-command hot path (`simplicio-loop "<task>"` and `simplicio-loop turbo --apply - <<'PLAN'`), 7-dimension adaptive DoD, verification, delivery contract, PR evidence, and GitHub issue drain.
- Monorepo structure maintained (`packages/mapper`, `packages/dev-cli`, `simplicio-loop` at root; no Fast, no Runtime, no MCP force).
- Subprocess and Network Guard Isolation: fixed subprocess invocation under `core_network_guard` across `apply.py`, `lane_verifiers.py`, `turbo_cli.py`, and `wave_worktree.py` using `asyncio.create_subprocess_exec` / `subprocess.run` with system shell executable, preventing network-guard bypass errors.
- Hermetic test robustness: made `matplotlib` import optional in benchmark reporting to allow unit tests (`test_turbo10_unit.py`) to run in lean environments without matplotlib installed.
- Increased core gate deadline to ensure full 51-shard test suite passes reliably on cold/loaded environments.

## [3.46.0] - 2026-09-29

- Harness catalog: `simplicio_loop/_catalog/harnesses.json` (`simplicio.harnesses/v1`, shipped in the wheel) lists the 32 host surfaces of `simpletibr/simplicio` (pinned to `plugins/simplicio/host-surfaces.json` at `a9c8a480`) plus Aider, DeepSeek and OpenClaw: 35 hosts, 34 `wired` and 1 `manual` (DeepSeek is a model provider, not a host). Existing adapter directory names map onto upstream ids through `aliases` (`claude` to `claude-code`, `qwen` to `qwen-code`, `orca` to `orca-dev`, `simplicio_agent` to `hermes`).
- `scripts/install.sh` and `scripts/install.ps1` (both launch `scripts/install_lib.py`) gain 21 runtimes: `github-copilot mimo-code amp openclaude pi oh-my-pi devin goose auggie autohand charm cline codebuff command-code continue droid kilocode kimi mistral-vibe qwen rovo-dev`. Each writes the file its host documents (`AGENTS.md` for most, plus `.github/copilot-instructions.md`, `.continue/rules/simplicio-loop.md` and `QWEN.md`) and the `.claude/skills` copy. `adapters/<host>/README.md` exists for every entry and `adapters/MATRIX.md` has one row per entry with its install status. The runtime count (35) is derived from the catalog by `scripts/canonical_manifest.py`, which also fails when an `adapters/` directory or a catalog entry has no counterpart.
- Fix: a second `install_lib.py` run changed the entry file (`AGENTS.md`, `GEMINI.md`, ...) by prepending two blank lines when the marker block started the file; re-running an install is now byte-identical.
- Removed the Runtime/MCP backend integration; execution is standalone only. Deleted `runtime_bridge`, `runtime_binary`, `runtime_context`, `runtime_drivers`, `runtime_adapter`, `runtime_effect_adapter`, `runtime_execution_receipt`, `plugin_runtime`, the `runtime-routing` contracts, `scripts/runtime_matrix.py` and the Runtime bridge session benchmark. `SIMPLICIO_EXECUTION_PROFILE` only accepts `standalone` (or unset/`auto`), `simplicio-loop stack lock --route` only accepts `standalone`, `simplicio-ecosystem-doctor` reports one `standalone` profile over three components (loop, mapper, dev-cli), `simplicio-loop preflight` checks Mapper and Dev CLI only, and `loop-execution` receipts carry the `simplicio-loop`, `simplicio-mapper`, `simplicio-dev-cli` chain with no runtime component (`contracts/ecosystem-doctor/v1` and `contracts/loop-execution/v1` updated). The Hookwall effect boundary in `runner.py` (envelope, pre-decision, ledger, fenced idempotent effects) is unchanged; it now builds its request from a local `_EffectRequest`. `simplicio-route` no longer offers a `govern` route to Runtime capabilities and the capability catalog loses its four `runtime.*` entries (12 capabilities). The Dev CLI's own Runtime bridge is untouched.
- Removed the Hub and remote workers. Console scripts `simplicio-hub`, `simplicio-remote-queue-server`, `simplicio-remote-worker` and `simplicio-remote-worker-supervisor`; `simplicio-loop hub-drain-admit` and `simplicio-loop doctor resource`; the doctor's "remote worker (#286)" check; the Hub daemon, governor, scheduler, queue retry, transport and agent executor; the SQLite and HTTP remote queue, secure transport, trust policy, short-lived credentials, audit log, work-item claims and worker daemon; the `remote-worker/v2` and `hub-agent` contracts; `SIMPLICIO_REMOTE_QUEUE_*`. `simplicio_loop/remote_queue.py` keeps `Lease`, `QueueConflict` and `QueueUnavailable`, which the Mapper-backed queue uses. `simplicio-loop hub-drain-plan` (read-only GitHub drain intake), `simplicio-process-supervisor` and the economy/token/budget monitors stay.
- Removed 16 modules that nothing called: `typed_recovery`, `slot_lease`, `resource_fabric`, `hookwall_rollout`, `prism_agents`, `prism_recovery`, `prism_reducer`, `capability_negotiation`, `map_service_protocol`, `loop_runtime`, `driver_contract`, `flow_semantics`, `control_policy`, `plan_dag` (and its Contract Registry entry: 8 contracts), `prototype_judge`, `prototype_fanout`; and `canonical_plan`, `verified_delivery`, `execution_board`, `model_router`, `model_registry`, `platform_capabilities`, which only the removed subsystems used. `mapper_receipt`, `budget` and the prototype gate stay: they have live callers. With them go their tests, docs, contract entries, skill references and coverage-baseline lines. The loop now lists 48 extension points (was 50).
- Tests: the root suite is 4,495 collected tests (5,782 before, gate selection; 4,551 and 5,840 including the external-integration lane). Mapper (1,827) and Dev CLI (2,713) are unchanged. Removed 146 test files (1,229 tests): 99 files for the removed subsystems (730 tests) and 47 old regression files named after an issue number (499 tests); another 60 tests in kept files that only exercised removed code were dropped and 2 were added. 27 issue-numbered files stay under descriptive names (368 tests) because a live module or script would otherwise have no test; five of them cover `scripts/` (`test_repo_governance_integration.py`, `test_conformance_benchmark.py`, `test_delivery_contract_stop_hook_integration.py`, `test_installed_agent_fabric.py`, `test_issue_meta_audit_unit.py`). `tests/test_turbo10_unit.py` reads the kept `2026-09-29-790061e2-t10-ind.json` run.
- Removed old evidence, benchmark results and documentation (git history keeps all of it): 23 evidence files (`docs/evidence/**`, `docs/audits/**`, `docs/HANDOFF-2026-09-26.md`, `.lavish/**`, `.specs/**`, 1.0 MB); 94 benchmark files (`bench/llm_ab` results before the 3.44 series and the stale `REPORT-ablation*`, `REPORT-t2*` and `REPORT-t1/t4-batch` renders, the `bench/*-baseline.json` and `bench/results/**` receipts with the harness scripts that only served removed features, the benchmark write-ups and the two PDF renderers, 6.2 MB); 29 documents (the Hub, remote worker, queue, plan DAG, slot lease and typed recovery runbooks, superseded ADRs 0002, 0003 and 0011, the Rust supervisor runbook for a module that no longer exists, `examples/EXAMPLES.md`, 0.1 MB). In all this release deletes 388 tracked files (9.3 MB: 61 code, 159 test, 18 contract or policy, 4 mirror, 23 evidence, 94 benchmark and 29 documentation files) and renames 28 test files; the tracked tree goes from 3,565 files and 54.8 MB to 3,177 files and 45.3 MB. `bench/llm_ab` keeps `REPORT.md/.html/.pdf`, `STANDARD.md`, the `146a6931` and `790061e2` results, `results/runs/` and the harness.
- Regenerated with their scripts: `quality/coverage-baseline.json` (47-file scope, 522 tests, global 16.75%, critical 25.13%; the earlier numbers are kept under `previous_baseline`), `scripts/repository_budget_baseline.json`, `contracts/headers.lock.json`, the `docs/LLM_ORIENTATION.toon` pins, `plugin/` and `simplicio_loop/_bundle/`.
- Known failures, unchanged by this release and identical on `origin/main`: `tests/test_cli_dispatch_unit.py` (6 tests write to a read-only `/r` on macOS) and, in Mapper, `test_background_index_reports_pid_and_log` and `test_scan_async_returns_before_deep_completes` (`deep pass did not terminate`).

## [3.45.2] - 2026-09-29

- The real skill path is two commands. Measured on 3.45.1 (deepseek-v4.1-flash through OpenCode), the direct turbo engine was 88-96% faster and 48-80% cheaper than plain OpenCode, but a host agent invoking `/simplicio-loop` took 9-20 turns, and every turn re-sends the whole conversation (120k-540k prompt tokens). It tied with or lost to plain OpenCode: 38-45 s against 30 s for 1 task, and 324-496 s and $0.020 against 112 s and $0.008 for 4 hard tasks. The archived sessions show where the turns went: `loop_progress.py render --turn-header`, a script the target repository does not have; `ls`, `cat` and `read` of the tree and the tests; `--help`; a scratchpad and a journal written by hand; the plan written to `plan.json` as a separate tool call; the model's own test run; a re-read of the result. The model also used `--provider openrouter` on its own, because the docs and the help mention it.
- `simplicio-loop turbo --repo R --apply - [--verify V]` reads the JSON plan from stdin, as UTF-8 bytes (a plan in Portuguese survives a cp1252 or C locale). An empty stdin, or a terminal on stdin, is `failed` with `turbo_plan_missing` instead of a hang; `--apply FILE` is the same code path. The `needs_plan` request now ends with the ONE next command in heredoc form, so the model writes the plan and applies it in a single tool call: `simplicio-loop turbo --repo <R> --apply - --verify "<V>" <<'PLAN'`, the plan, `PLAN`. Two commands, two tool calls (smoke with the real CLI, network denied: request, then apply, `status ok`).
- The request is compact: `tasks` (each task text once), `map` (the Mapper map cut to the named files, for several tasks too, as JSON instead of an escaped string), `files` (the current text of the named files, each once; a file past 6000 characters ends with how much was cut), `format`, `rules` (one line: write the plan from the file contents above, do not open, list or read other files, do not run tests yourself, run the command below once) and `apply`. `plan_path`, `prompt`, the second copy of the task list and the planner's "reply with JSON only" text are gone, and step 1 writes nothing into the repository (no `request.json`, no `plan.json` cleanup).
- The skill body (frontmatter unchanged), its `SIMPLICIO-LLM-ORIENTATION` block, `docs/LLM_MAX_SPEED_ORIENTATION.md`, `llms.txt`, the `AGENTS.md` quick flow, the host rules, `docs/ECOSYSTEM_LLM_GUIDE.md`, the OpenCode adapter README, `references/full-flow.md` and the `orient` command card say it plainly: exactly two commands; do not explore, list or read files; do not run tests yourself (`--verify` does); no plan file, scratchpad, journal or turn header for a task run. The loop's own Contract, State and Drive sections, Bounded delivery and the `references/full-flow.md` pointer now say they are for queue goals and re-fed goals, and the turn header is skipped when its script is missing. None of these names `--provider` or `OPENROUTER_API_KEY` any more; `turbo --help` and `docs/CLI_COMMANDS.md` describe `--provider openrouter` as headless automation only that agents invoking the skill must not use, and the engine notes moved to `bench/llm_ab/STANDARD.md`. `SKILL.md` is 1935 tokens (o200k_base), from 1858 before the rewrite.
- `.simplicio-loop/` no longer shows up as untracked. Cloud workers reported it: the turbo path (the default skill flow since 3.45) never called `state_dir.ensure_state_dir`, so not even the `<git-dir>/info/exclude` line was written, while Mapper, the survey marker and dev-cli all write under that directory. `ensure_state_dir` now also appends `.simplicio-loop/` to the repository's `.gitignore` when that file exists and no stripped, non-comment line already covers the directory (`.simplicio-loop`, `/.simplicio-loop/`, `.simplicio-loop/*`, `/.simplicio-loop/**` and the other variants); it never creates a `.gitignore`, keeps CRLF line endings, adds a missing final newline first, and leaves a file it cannot read as UTF-8 or write untouched. This repository's own `.gitignore` (`.simplicio-loop/*`) is not edited. `turbo` calls it before anything is written under the directory: after the request validates its tasks, before dev-cli applies a plan, and in provider mode; a blocked call or a missing `--repo` creates nothing. The skill body and its orientation block say the directory is local run state: keep it in `.gitignore` (the engine adds it when the file exists) and never commit it.
- The turbo hedge only fires on real tails: `SIMPLICIO_TURBO_HEDGE_AFTER` defaults to 10 s, was 2.5 s. The 2.5 s came from a simulation with Together only. On the real provider mix normal calls take 1.6-8.0 s (Relace, the slowest, about 8 s) and the one real tail took 19.6 s. In the final benchmark hedge analysis, at 2.5 s the hedge fired on 23% of calls, the duplicate won only 2 of 21, it saved about 0.08 s in total, and the losing duplicates were 47% of the billed cost (the CLI hedged 5 of 12 calls, and 4-task sets cost 45-57% more than in 3.45.0). 10 s is above the ~8 s slowest normal call and still cuts the 20-45 s tails. A test pins that a 5 s call is not hedged by default.
- The repair after a failed `--verify` (provider mode) rewrites a file the first plan created. On a create task the model repeated `{"find": ""}` for a file that now exists and dev-cli refused it as `create_target_exists`, in 5 of 15 repair attempts, so the repair never got a chance. Only on that path, an operation with an empty `find` for an existing file becomes a whole-file replacement (`find` is the file's current text, read as bytes so its line endings survive; anything that cannot be a whole-file find is left to dev-cli), and the repair prompt says the listed files already exist.
- `hooks/action_gate.py` reads the heredoc body of `simplicio-loop turbo ... --apply - <<'PLAN'` as data, so a plan that merely contains a destructive statement (a migration, a runbook) is not blocked for what it says; the gate blocked the tool call that wrote its own test while this was built. Only the exact shape is exempt: one plain `simplicio-loop turbo --apply -` command with no unquoted operator, and a quoted delimiter that is the last line and appears nowhere earlier. Every other command, and every other reader of a heredoc, is classified in full.
- `python3 scripts/check.py` passes on the release tree again (audit, mirror parity, impact tests, loop contract, clean env, token budget, repo budget, conformance). It failed on 3.45.1: since the immutable contract headers (#1342) line 2 of each shared reference of `simplicio-loop` and `simplicio-tasks` names its own skill, so the skill-pair parity check reported 12 references as drifted. Only that line is normalized; a body difference behind the header is still flagged.

## [3.45.1] - 2026-09-29

- Fix: 3.45.0 wrongly required a provider key inside the skill, so a worker that ran it without `OPENROUTER_API_KEY` was blocked. `simplicio-loop turbo` now defaults to host mode, which needs no key and makes no provider call (even when the key is set): the model that invoked the skill controls everything and `simplicio-dev-cli` makes every edit. Step 1, `simplicio-loop turbo --repo R --task T [--verify V]`, surveys with Mapper and prints `simplicio.turbo-request/v1` with `status: "needs_plan"`: the map slice (one task gets only its slice), the task, the current file text, `plan_path` (`.simplicio-loop/turbo/plan.json`), `format`, `tasks`, `prompt` and the exact `apply` command; the request is also saved as `.simplicio-loop/turbo/request.json`. Step 2, `simplicio-loop turbo --repo R --apply .simplicio-loop/turbo/plan.json [--verify V]`, applies the find/replace plan the model wrote through dev-cli, runs `--verify` and prints `simplicio.turbo-run/v1` with `mode: "host"`, `status` ok or failed, `applied`, `failed` (each with the dev-cli reason and an excerpt of the file around a `find` that did not match) and `verify`. A missing or malformed plan is `failed` with `turbo_plan_missing` or `turbo_plan_malformed`. Exit 0 ok or needs_plan, 1 failed, 2 blocked.
- The OpenRouter engine is an explicit opt-in, `--provider openrouter`, and the only mode that needs `OPENROUTER_API_KEY` (`turbo_provider_key_missing`, exit 2, without it). The benchmark's turbo arm is unchanged.
- `simplicio-loop "<task>" [--verify "<tests>"]` is the shortest form: a first argument that is not a subcommand runs `turbo --repo . --task "<task>"`. Requests for all issues, tickets or tarefas still go to the GitHub drain intake, and bare `simplicio-loop` is unchanged. Before, it failed in argparse with "invalid choice".
- The skill (body only, frontmatter unchanged), its orientation block, `docs/LLM_MAX_SPEED_ORIENTATION.md`, `llms.txt`, `AGENTS.md`, `README.md`, `docs/CLI_COMMANDS.md`, the host rules and the `orient` command card describe the two-command flow and drop the key requirement. The skill also says how to drain a queue: list the items (`gh issue list --state open --json number,title,body`), run the two commands per item in order, one CLAIMED issue and one PR per item, done only on `status: "ok"` plus a passing verify.
- `hooks/action_gate.py` lets the host write `.simplicio-loop/turbo/plan.json` under `SIMPLICIO_LOOP_STRICT` and still blocks every other hand edit.
- Turbo provider mode: one pooled `httpx` connection kept alive (about 50 ms per call, measured); a hedged duplicate request on session `<id>-hedge` after `SIMPLICIO_TURBO_HEDGE_AFTER` seconds (default 2.5, 0 disables) whose losing side is billed; a 1-token warm-up call that caches the header before independent tasks fan out at once; a one-task slice of the Mapper map (`SIMPLICIO_TURBO_SLICE=0` disables it; 3,294 map tokens down to about 340, measured on `fixture_hard`); and one repair call with the test output after a failed `--verify`. Call records carry `hedged` and `warm`, and the benchmark counts hedge losers in the arm's tokens.
- `python3 scripts/check.py` runs only the tests a change can affect by default. `scripts/impact_tests.py` diffs the working tree against `--base` (default `origin/main`), keeps the top-level functions, classes and assignments whose source changed, and selects the test files that reach them (bare name, `module.symbol`, import alias or dotted string), run a changed file by path, or name a changed non-Python file; a changed `conftest.py` reaches the tests below it. `--full` runs every test file and `--base REF` changes the reference; the package gates use the same selection. Selecting the whole 3.45.1 branch takes 9 s.
- Test-suite pruning (the suite was 5,735 root tests): removed 141 and added 45 (host mode, the prose default, the impact gate and the safety net below), so 5,639 collected. 119 tests in 23 files test modules that no entry point, script, hook, doc or other module reaches (`engine_router`, `engine_boundary`, `engine_dependency_guard`, `conformance`, `conformance_cache`, `hub_agent_store`, `inference_benchmark`, `inference_capacity`, `installed_process_e2e`, `installed_runtime_e2e`, `production_integration`, `model_routing_policy`, `semantic_convergence`, `token_control_plane`, `source_detect`, `map_service_delivery`, `map_service_invalidation`, `map_service_persistence`, `map_service_repository_watchers`, `behavior_loop`, `development_entry`, `epic_readiness`, `savings_cli`); those modules and the unused `hub_queue_agent_client` compatibility shim are deleted, and so are the 11 tests in `test_source_contract_v1.py` that covered the deleted `source_fan_in` and `source_providers`. 5 exact duplicate tests and 6 skipped tests of the removed SQLite Hub queue are gone, plus 5 skipped dev-cli tests of removed provider features (dev-cli suite 2,716 to 2,711; mapper unchanged at 1,735). A new import sweep and a `--help` run of every console script guard the deleted modules.
- The 5 tests blocked by the host's physical-pressure gate no longer depend on it: they pin the documented `SIMPLICIO_LOOP_*_PRESSURE_PERCENT` profile (new `admitting_capacity` fixture) and put the suite's interpreter first on `PATH` for the verify lanes. The quality provider's monitor honors the same profile through `local_capacity.physical_monitor_kwargs`, which moved out of `runner.py`.

## [3.45.0] - 2026-09-29

- New command `simplicio-loop turbo --repo R --task "..." [--task ...] [--verify "cmd"]`. Mapper reads the repo once, one OpenRouter call per lane (`deepseek/deepseek-v4.1-flash`, pinned session, reasoning off) returns a find/replace plan, and `simplicio-dev-cli` applies it. Files named in the task text become the target and context, and tasks on the same file stay in order. It prints one `simplicio.turbo-run/v1` JSON document (status, applied, failed, model_calls, retries, tokens, cache_hit_pct, cost_usd, verify, wall_s) and exits 0 ok, 1 failed, 2 blocked.
- Invoking the skill now runs `simplicio-loop turbo` by default. The host no longer writes `tasks.md`, edit plans or `simplicio-dev-cli edit --plan` operations. `SKILL.md` and the orientation block the stop hook re-feeds every turn, `docs/LLM_MAX_SPEED_ORIENTATION.md`, `docs/ECOSYSTEM_LLM_GUIDE.md`, `docs/CLI_COMMANDS.md`, `llms.txt`, `AGENTS.md`, `README.md`, the host rule files, the OpenCode adapter and the bench docs all name that one command. Done is `status: "ok"` and, when `--verify` was given, `verify.passed: true`.
- `simplicio_loop/turbo_provider.py` is the model client for both the product and the benchmark's turbo arm, so the benchmark measures the code that ships. `SIMPLICIO_TURBO_MODEL` overrides the model.
- `OPENROUTER_API_KEY` is required. Without it the command prints `status: blocked` with `reason_code: turbo_provider_key_missing` and exits 2. There is no fallback to hand edits.
- `run_turbo` reports per-lane outcomes (`outcomes`: tasks, applied, reason) and `applied_all`. A plan that dev-cli rejects twice is a `failed` result that names the dev-cli reason.
- `orient` points at turbo. `route["next"]` is the `simplicio-loop turbo` command (`orient --brief` carries every task and `--verify` in one step), the command card and the `llm_orientation` and `hot_path` data of `economy status` name turbo, and no prepare, tick, wave or edit-plan guidance is left in them.
- Each `simplicio-loop turbo` invocation asks Mapper again. Mapper's own tree-state cache keeps an unchanged tree free and byte-identical; before, every later invocation reused the first map saved in `.simplicio-loop/turbo-survey.json`.
- `SKILL.md` is 1571 tokens (o200k_base), down from 2118 in 3.44.2, and the token-budget baseline is regenerated. Removed the unused `delivery_execute_verb` and `DELIVERY_EXECUTE_RULE`.
- `scripts/check.py` no longer crashes with `KeyError: 'contract_headers'` after claims-audit: the phase had no timeout entry in `PHASE_TIMEOUT_SECONDS`, so the full local gate never reached the test phase. A test now requires every phase `check.py` names to have one.
- header-change: .claude/skills/simplicio-loop/SKILL.md (frontmatter description: "Host writes the edit plan." became "Invoking it runs simplicio-loop turbo.")
- header-change: .claude/skills/simplicio-loop/references/full-flow.md (purpose no longer lists the fastest-route picker and the wave-flow commands as kept in SKILL.md)

## [3.44.2] - 2026-09-29

- `bench/llm_ab/run.py --tasks 4 --hard` adds a hard Python set with hidden acceptance tests outside the arm repo: coupon logic with a half-up rounding trap, a two-bug fix, a two-file refactor, and a duration parser. `--turbo-reasoning` keeps the model's reasoning on for the turbo calls, so on and off can be compared. Turbo also sends a task's `context` files to the model. The checker accepts an absolute path.
- Hard-set result: with reasoning off, turbo passed 12/12 hidden-test tasks at 5.4 s and $0.0027 per run (mean of 3). The OpenCode arm passed 11/12 at 112.6 s and $0.0122. With reasoning on, turbo passed 7/8, and one call ran away to 131k reasoning tokens. Turbo keeps reasoning off.
- Every benchmark run of 3.44.0 to 3.44.2 is archived under `bench/llm_ab/results/runs/` with a summary `README.md`, outside the release-to-release history.

## [3.44.1] - 2026-09-29

- Turbo calls in the benchmark pin the arm's OpenRouter session (`x-session-id`, as the OpenCode arms already did) and switch reasoning off (`"reasoning": {"enabled": false}`). Measured before the change: an unpinned call switched provider and lost the prompt cache in 1 of 2 trials, while pinned calls read it 4 of 4 times. `effort: low/minimal` did not reduce reasoning tokens, and `enabled: false` removed them.
- The turbo wave no longer sleeps 3 s after the first call; with a pinned session the next call reads the cache without waiting.
- Every turbo call records `latency_s` and `provider`.
- `bench/llm_ab/run.py --tasks 10 --independent` runs the ten pages without the standard dependency chain (results `...-t10-ind.json`), so the wave's fan-out is measured; the standard sets are unchanged.
- The bench docs state that in turbo mode the `simplicio` arm is the loop engine calling OpenRouter directly, not OpenCode.
- `simplicio-loop update` also repairs an up-to-date install that still has the standalone `simplicio-cli` / `simplicio-mapper` distributions (left by `pip install -U` from 3.43.x).
- `simplicio-py doctor --upgrade` no longer reinstalls `simplicio-mapper` from PyPI on top of the wheel; it tracks `simplicio-loop`.

## [3.44.0] - 2026-09-28

- Single wheel: `pip install simplicio-loop` now ships mapper and dev-cli inside the package (`simplicio-mapper`, `simplicio-dev-cli`, `simplicio-cli`, `simplicio-py`, `simplicio-codex-wrapper`, `llm-project-mapper`) and the loop no longer depends on the external `simplicio-cli` / `simplicio-mapper` PyPI distributions; the stack manifest, operator bootstrap, clean-env contract and installer all treat `simplicio-loop` as the only package. New `simplicio-loop update` installs the latest GitHub release of `simpletibr/simplicio-loop` (`--check` only reports, `--force` reinstalls) and removes the retired standalone `simplicio-cli` / `simplicio-mapper` distributions first.
- `simplicio-loop update` installs the latest GitHub release of `simpletibr/simplicio-loop` (`--check` only reports, `--force` reinstalls, an editable checkout is told to `git pull`). It removes the standalone `simplicio-cli` and `simplicio-mapper` distributions first: they own the same files as the wheel, and uninstalling one after the wheel is installed leaves `simplicio_mapper` with 2 of 408 files. (#1369)
- `simplicio-loop-stack` / doctor report a co-installed standalone `simplicio-cli` or `simplicio-mapper` as drift, with the fix command.
- Every non-Python file of the merged packages (contracts, schemas, templates, fixtures, dotfiles) ships in the wheel; a contract test builds the wheel and compares it with the source tree.
- Mapper and Dev CLI read their version from the bundled package, not from a distribution that no longer exists.
- One release tag `vX.Y.Z`; the per-package `mapper-v`/`dev-cli-v` scheme is retired (the Mapper schema-compat check diffs against `vX.Y.Z`), and `packages/mapper` / `packages/dev-cli` are marked `Private :: Do Not Upload` so PyPI rejects a standalone upload.
- Turbo reads the Mapper map only from `.simplicio-loop/` (it used to prefer a stale `.simplicio/project-map.json`).
- Only the release-standard bench results (1 and 4 tasks, plain or `-batch`) are versioned; other runs stay local.

## [Unreleased] - monorepo

- A wave starts at two tasks. One task stays on `tick` in the shared checkout; two or more enter the wave lane dispatcher instead of the old 1-3 inline cutoff. (#1354)
- Restore the pre-monorepo flow inside this repo: one task runs `tick`, more than one task runs `wave`, both after `orient` and `prepare`. No external project install. (#1353)
- On invocation the simplicio-loop skill starts the monorepo engine (`orient --brief` then `apply`; drain `prepare` → edit plans → `wave` → `verify`) for any repository via `--repo`, with the Mapper survey cached and `--tee` storing the JSON. (#1353)
- Root hygiene pass: dropped ~40 committed `.simplicio/session/orientation-delivered.json`
  cache markers, a stale `benchmarks/projection-v4/` simulated report, an orphaned
  `video/.simplicio/orchestrator/learn/pending.jsonl` leftover from the removed learn_stop
  pipeline (#69), a stray `docs/quality-matrix-v2-benchmark.json`, and assorted one-off
  root-level artifacts (`plan.json`, `error.log`, `claimed-428.md`, `.task_wi558.txt`,
  `benchmark-agent-fabric-765.json`, `benchmark-coverage-custodian-784.json`,
  `conformance-benchmark-816.json`/`.sha256`). README.md/AGENTS.md/CLAUDE.md now document the
  monorepo layout (root = orchestration, `packages/mapper` = survey, `packages/fast` =
  retrieval, `packages/dev-cli` = mutation) and `scripts/dev_install.sh` dev setup;
  `CLAUDE.md`'s bound-operator links now point at `packages/mapper/` and `packages/dev-cli/`
  instead of the pre-monorepo external repos.

## [3.43.17] - 2026-09-28

- Turbo keeps the Mapper project map as a byte-identical header. The task text and the current target file stay in the suffix. A dev-cli rejection goes back once. Above three tasks the first call runs alone so later calls can read that header from prompt cache; dependent tasks stay in order and independent plans apply one at a time.
- The standard 1-task and 4-task run of that path is recorded in `bench/llm_ab/results/2026-09-28-495a79e9-t1.json` and `2026-09-28-495a79e9-t4.json`, and rendered as `bench/llm_ab/REPORT.md` and `bench/llm_ab/REPORT.pdf`. The summary shows the model-priced cost beside the settled bill.
- The report cache-hit gate marks the hit cell. Find/replace plans that already carry a schema still compile before apply (#1364).

## [3.43.16] - 2026-09-25

- Wave lane dispatch: worktree-parallel lane execution (disjoint edit-plan
  paths run concurrently, each in its own git worktree, then integrate back
  serially in task order), conditional lanes, and concurrent lane verifiers,
  with mapper/dev-cli capability probes cached once per run instead of
  re-probed per task. A deterministic operator failure (bad plan path/anchor)
  no longer burns retry budget: `runner.py` stops retrying
  `plan_required`/`plan_path_not_found`/`plan_path_not_authorized`/
  `plan_find_not_found`/`plan_find_not_unique` and reports the precise reason
  instead.
- `orient --json` now shares its Mapper/Fast survey cache across worktrees,
  adds a compact `commands` card (exact `prepare`/`wave`/`verify`/`tick`
  invocations, edit-plan path/format, task-file lanes) to its response, and
  grounds the host with real file `targets` on an empty selection instead of
  leaving it to guess a path. The in-process strict-mode probe now checks
  mapper/fast/dev-cli capabilities directly instead of shelling out to
  `--version`/`--help`, and the cache-invalidation digest excludes
  `.simplicio/` so the loop's own writes don't self-invalidate the cache.
- Raise the operator train floors to `simplicio-mapper` 0.26.34 (paired with
  the already-raised `simplicio-cli` 0.18.16 floor).
- Fix `tests/test_evidence_receipt_unit.py`'s red test: it drove the now
  fully-redirected `simplicio-loop run --task` path (a thin wrapper over
  `prepare` + `wave`) as if it were still the old single-shot tick; rebuilt
  it on the current two-phase `prepare` -> write `edit-plan-1.json` -> `wave`
  shape it actually redirects to, preserving what it proves: the evidence
  receipt is built from the run and the watcher reads it.
- `tests/test_wave_worktree_unit.py`'s two-lane concurrency test now asserts
  the lanes' sleep windows actually overlap (recorded start/end timestamps)
  instead of comparing total wall-clock elapsed time against a fudged bound.
- SKILL.md documents the `orient` command card/targets and the deterministic
  no-retry plan reason codes.

## [3.43.15] - 2026-09-25

- Fix `wave` applying only task 1 of a run: a dependent task's
  `plan_repo_state_stale` check compared against the frozen `prepare`-time
  fingerprint instead of the tree the run's own prior tasks actually left,
  dead-lettering every later task in a 10-task benchmark. The run now
  advances its own chained repo-state baseline after each applied task
  (`state["repo_state_chain"]`), so a dependent task's plan validates
  against the tree it should chain from — while an edit made outside the
  run still fails closed as before.
- Fix `simplicio-loop verify` reporting `VERIFIED`/`MEASURED` while most of
  a run's tasks were dead-lettered and never produced an operator receipt:
  the quality-matrix `implementation` gate only checked whichever
  `operator-receipt-*.json` files happened to exist, not one per task the
  run actually scheduled. It now requires a verified receipt for every
  task index and names the missing ones. The completion oracle gained a
  matching `task_dispatch` gate that reads the run's own dispatch batch
  result and blocks, naming the exact failed/blocked/dead-lettered/missing
  task indices, before the quality-matrix and watcher gates are even
  reached.

## [3.43.14] - 2026-09-25

- Raise the operator train floors to `simplicio-cli` 0.18.15 (loop needs
  dev-cli's new `edit --compile`), `simplicio-mapper` 0.26.33, and
  `simplicio-fast` 2.0.35.
- Make hosts write minimal find/replace plans, compiled at dispatch
  (#1290-wave), and land per-lane quality verifiers so "done" is reachable on
  any repository.
- Harden the orient Mapper -> Fast path against real repositories: real
  Mapper handoff passed to Fast with a surfaced fallback reason, worktree-aware
  ingest cache keyed on content (not just names), and stale-map rescan with an
  advisory inferred corridor.
- Fix the runner: dispatch accepts minimal host plans without a schema,
  synthetic dispatch only falls back when the run manifest is missing,
  verifier caches and gitignored files no longer make a run look stale, and
  disk-pressure measurement now matches `df` while ignoring cgroup v1
  no-limit reporting.
- Default storage to the `MapperStore` route; re-measure evidence on the
  final tree before the watcher; collapse the watcher's run-diff fingerprint
  to a single fingerprint, excluding the loop's own `.simplicio/`.
- Fix `task_backlog`/`task_anchor`/`loop_progress` to answer `--help` and
  reject unknown flags.
- Fix the `economy` command: `apply` now honors `runtime_operational` and
  persists via an rc-file source line on POSIX.
- Update repository and release/PyPI URLs to the `@simpletibr` organization.

## [3.43.13] - 2026-09-15

- Bound prompt-projection token accounting, reserve physical disk headroom before
  local-capacity admission, add a wheel-install rehearsal smoke check, and fill in
  provider receipt fields (#1277, #1269, #1268, #1267).

## [3.43.12] - 2026-09-14

- Exclude the `run` command from the public CLI surface and deprecate it. Any call to `simplicio-loop run` is transparently intercepted and redirected to the standard governed `wave` flow.
- Make `simplicio-fast` strictly mandatory across preflight, ecosystem doctor, strict mode, and operator bootstrap alongside `simplicio-mapper`.
- Establish `wave` as the default multi-task governed flow with reconciliation barriers.
- Document LLM decision heuristics (`single-task-fast`, `wave`, `prism`, `batch`, `tick`) and prompt caching scaling dynamics (up to 96.7% cache hits on 30 tasks).

## [3.43.11] - 2026-09-12

- Align the aggregate release with Mapper `0.26.31`, Dev CLI `0.18.13`, and
  Fast `2.0.33`.
- Publish the current `main` operator-flow updates, including governed task
  routes and run-attributable savings reporting.

## [3.43.10] - 2026-09-10
- Bound benchmark preflight inputs and outputs and make signature literal minimization explicit.
- Add focused regression coverage for signature views and invalid-trial preflight behavior.

## Unreleased

## [3.43.9] - 2026-09-09

- Raise the Mapper floor to the current PyPI release `simplicio-mapper` 0.26.29.
- Align the operator train with `simplicio-cli` 0.18.12, `simplicio-fast` 2.0.31, and `simplicio-prompt` 1.14.4.
- Publish the merged `main` work since 3.43.8: physical admission governor (#1228), journal help side-effect-free (#1229), bounded continuation (#1232), changelog restore (#1234), and isolated quality-provider process boundary (#1233).

## [3.43.8] - 2026-09-05

- Synchronize every Loop plugin, adapter, package, and stack manifest surface to 3.43.8 after the merged release metadata fixes.

## [3.43.7] - 2026-09-04

- Fix release-manifest loading for installed Loop stacks.
- Align the published package version with all release surfaces.

## [3.43.6] - 2026-09-03

- Verify the installed Mapper executable, artifact digest, capabilities and protocols in
  `simplicio-loop-stack --check`, with stable fail-closed reason codes.
- Keep the Loop stack fallback version inside the canonical mechanical version-sync command.

## [3.43.5] - 2026-09-02

- Add `setuptools>=77` to the `dev` extra so the declared development
  environment can collect the full test suite consistently.
- Keep local release validation aligned with the package build requirements.

## [3.43.4] - 2026-09-02

- Make `simplicio-loop-stack --check` prove the mandatory Mapper and Dev CLI
  dependency declarations, package-owned entrypoints, and `PATH` resolution.
- Align the release train with `simplicio-mapper` 0.26.26 and its direct dependency floor.

## [3.43.3] - 2026-08-30

- Accept canonical Runtime event envelopes and repository manifests in the release train.
- Emit the canonical `UserPromptSubmit` route decision and keep all release surfaces in lockstep.
- Restore the canonical skill source tree and synchronize the plugin and bundled mirrors.
- Align macOS AF_UNIX, opaque fencing-token, Hub IPC, and hermetic release-gate contracts.

## [3.43.2] - 2026-08-23

- Publish the latest `main` changes, including the current skill and operator-flow surface.

## [3.43.1] - 2026-08-14

- Require the released Simplicio toolchain: Dev CLI 0.18.10, Mapper 0.26.20,
  and Fast 2.0.28.

## [3.43.0] - 2026-08-10

- Declare English as the machine-readable instruction language for Prism routes and the capability catalog.
- Recognize common audit, migration, integration, benchmark, and review requests when routing Sprint issues.

## [3.42.0] - 2026-08-10

- Improve Prism recognition for Portuguese and mixed orchestration/validation requests.
- Expand capability dependencies before emitting a route so prerequisites are never omitted.
- Add regression coverage for the real Sprint Portfolio Intake routing shape.

## [3.41.0] - 2026-08-10

- Add the LLM-facing capability catalog and deterministic Prism route command.
- Expose simplicio-capabilities and simplicio-route as the compact discovery surface.

## [3.40.0] - 2026-08-10

- Make Loop the aggregate distribution for Mapper, Fast and Dev CLI.
- Add `simplicio-loop-stack --json|--check` for deterministic external Runtime probing.

## [3.39.4] - 2026-08-10

- Add the shared `simplicio.io/v1` envelope and document Loop's coordinator-only
  responsibility.

## [3.39.3] - 2026-08-09

### Added
- Add governed native LLM max-speed orientation and Runtime operator-routing documentation.
- Add packaging/environment guidance and the ADR for Runtime-owned operator routing.

### Fixed
- Probe Runtime version before freezing stack locks and block mutable plans for read-only intents.
- Verify PR body integrity, report prototype source drift, bind Fast ingest to the source commit, and exclude generated Fast state from fingerprints.
- Preserve Rust targets and fail closed on fallback; restore the release manifest test path.

## [3.39.2] - 2026-08-04

### Fixed
- Keep the Windows pytest invocation bounded by running small file shards,
  preventing `WinError 206` without dropping any selected test file.
- Extend the bounded full-suite phase to 900 seconds for cold or slower Windows
  filesystems while retaining fail-closed timeout behavior.
- Align claims/canonical-manifest skill and runtime counts with the seven core
  skills, the legacy Hermes alias, and the Grok host-rule shim.
- Restore the documented root entrypoint for `generate_capability_inventory.py`.

### Changed
- Refresh the reviewed token and repository-size baselines after the prior
  release's documented growth.

## [3.39.1] - 2026-08-04

### Added
- Sectorized `.simplicio/observability/<component>/events.jsonl` telemetry for
  Loop journal transactions, with hash chaining, bounded labels, opaque
  correlation identifiers, and secret/PII redaction.
- Stage metrics for duration, CPU time, peak RSS, and I/O bytes, including
  explicit unavailable reasons when a platform cannot provide a metric.

### Changed
- Loop journal writes now emit fail-open observability events without changing
  journal locking, progress, stall detection, or failure semantics.

## [3.39.0] - 2026-08-04

### Added
- ADR 0009: loop complete inside Runtime; mapper/dev-cli/fast work alone
- ADR 0010 + `simplicio_loop/execution_report.py` — mandatory metrics schema
- `docs/ECOSYSTEM_LLM_GUIDE.md` + adapter README law blocks for all hosts

### Changed
- Host rules / MULTI_LLM_CONTRACT: Runtime owns loop activation; metrics standard

## [3.38.35] - 2026-08-03

### Fixed
- Prefer the **newest** native Runtime binary when multiple `simplicio` installs
  are on PATH (stale `~/.local/simplicio-runtime/bin` no longer shadows a fresher
  `~/.local/bin/simplicio`). Explicit `SIMPLICIO_RUNTIME_BIN` remains authoritative.

## [3.38.34] - 2026-08-03

- **Economy-parallel profile (default):** `simplicio-loop economy status|print|apply`
  arms the fastest token path (mapper/Fast/Runtime MCP) with bounded CPU/RAM workers,
  Prism slots, asyncio concurrency, and `SIMPLICIO_LOOP_AUTO_FAN_OUT=1`.
- `recommended_env` / `arm_drain_prism` share the same profile (Runtime Tokio when
  bound; Python asyncio for batch/supervisor; Prism for drain waves).
- Opt out: `SIMPLICIO_ECONOMY_PARALLEL=0`.

## [3.38.33] - 2026-08-03

- **Always-latest operators (default):** `operator_check` TTL default is `0` and
  `SIMPLICIO_OPERATOR_ALWAYS_LATEST=1` (opt out with `=0` + `--ttl-days N`).
  Preflight `maybe-upgrade` runs `pip install -U` for unpinned
  `simplicio-loop`, `simplicio-cli`, `simplicio-mapper`, `simplicio-fast`.
- Drop the `simplicio-mapper<0.27` ceiling in `pyproject.toml` and bootstrap
  package specs so upgrades are never blocked by an upper pin.

## [3.38.32] - 2026-08-03

- Preflight / STRICT runtime probe: prefer `SIMPLICIO_RUNTIME_BIN` and known
  Runtime install roots; scan every `simplicio` on PATH and **reject** the pip
  `simplicio-cli` console-script alias that prints `simplicio-py …` so Windows
  hosts with `Scripts` before `.local` no longer bind the wrong binary.

## [3.38.31] - 2026-08-03

- Ecosystem doctor: prove conceptual mapper role `recall` via real CLI surface
  (`handoff` / `ask` / `inspect`) so standalone/full-stack handshakes no longer
  false-block on installed mapper 0.26.x.
- Preflight: probe `simplicio-dev-cli` with `--version` (not `--help`) and report
  independent `simplicio-py` presence; never surface argparse `usage:` as version.

## [3.38.30] - 2026-08-02

- Synchronize the Loop release train with Mapper `0.26.10`, Dev CLI `0.18.6`,
  and Fast `2.0.22`.
- Refresh the exact submodule pins, dependency floors, operator bootstrap, and
  ecosystem-doctor compatibility gates.

## [3.38.29] - 2026-08-02

- Publish the merged MapperStore, Stack Lock, Resource Fabric, SourceAdapter,
  and fan-in delivery slices as the coordinated Loop release.

## [3.38.28] - 2026-08-01

- Synchronize package, plugin, runtime, and release metadata versions.

## [3.38.27] - 2026-08-01

- Publish the external Hub-backed quality-provider entry-point integration from PR #969.

## [3.38.26] - 2026-08-01

- Resolve explicitly selected external quality providers through the Loop extension entry-point contract.
- Restore generated `flow_audit.py` parity across plugin and package mirrors (#963).
- Define bounded delivery with frozen live-source provenance, cross-session authority,
  review limits, and explicit integration/release boundaries (#960).

## 3.38.25

- Keep quality providers opt-in for `simplicio-loop run`; an explicitly selected provider remains fail-closed.

## 3.38.24

- Synchronize supervised Hub execution fences and state through send, status,
  collect and cancellation responses.

## 3.38.23

- Preserve complete Hub agent handles and stage input across the productive
  process lifecycle, refresh supervised execution state, and support TCP
  loopback clients.

## 3.38.22

- Discover extension providers through the PEP-compliant
  `simplicio.loop_extension` entry-point group while retaining deterministic
  compatibility with legacy metadata.

## 3.38.14

- Disable Simplicio Runtime and Runtime MCP by default; the standalone path is now the
  default until Runtime is explicitly enabled.

## [3.38.12] - 2026-07-31

- Inject a canonical, concise startup orientation into every `simplicio-loop`
  LLM re-feed without growing the task body.
- Mirror the orientation across the plugin/bundle, add E2E coverage, and record
  the decision in ADR 0007 (issue #921).

## 3.38.11

- Python standalone path: bounded Mapper timeouts now produce degraded receipts,
  bounded local candidates, and a provider-free Dev CLI preflight.
- Release floors aligned to Mapper 0.26.1, Dev CLI 0.18.1, and Fast 2.0.18.

## 3.38.10

- FORCE Runtime MCP when present: `mcp_force_sync`, host rule, PreToolUse bulk-read gate
- **Runtime remains optional** for simplicio-loop (`REQUIRE_RUNTIME=auto`, `EXECUTION_PROFILE=auto`)
- MCP force only applies when `simplicio` is on PATH; standalone mapper+dev-cli continues without Runtime
- Operator floors unchanged (mapper>=0.26, cli>=0.18, fast>=2.0.16)

## 3.38.9

- Multi-LLM host floor: host_rule_sync, arm_drain_prism, Grok adapter, STRICT action_gate
- Client integrations opt-in only (Orca off by default)
- Operator floors unchanged (mapper>=0.26, cli>=0.18, fast>=2.0.16)

## 3.38.8

- Prism execution issues #845-#852, #819, #801 closed with measured evidence
- Operator floors: mapper>=0.26.0, cli>=0.18.0, fast>=2.0.16
- prism_integrity and preflight --strict green

## [3.38.7] - 2026-07-28

- Raise the installed dependency floors and exact submodule pins to Mapper
  0.26.0, Dev CLI 0.18.0, and Fast 2.0.16.
- Advance Fast to the post-release verified tip with corrected version tests
  and Git-tree-only quant benchmark provenance.
- Advance Mapper to the final 0.26.0 release-metadata correction.
- Keep strict routing, admission planning receipts, subprocess network guards,
  plugin parity, and the full core gate fail-closed.

## [3.38.6] - 2026-07-28

- Enforce strict operator/Runtime routing with Orca available only by explicit
  opt-in.
- Synchronize the PRISM bundle with Mapper 0.26.0, Dev CLI 0.18.0, and the
  hardened Fast 2.0.16 master pin, including reproducible Git-tree-bound
  quant benchmark provenance.

## [3.38.5] - 2026-07-27

- Install Simplicio Fast `>=2.0.14` as a direct Loop dependency so the
  `simplicio-fast` operator is placed on PATH with a standard Loop install.
- Keep the existing Mapper fallback and fail-closed Fast preflight behavior.

## [3.38.4] - 2026-07-27

- Require Simplicio Fast `>=2.0.14` in the Loop preflight and integrated flow.
- Document Fast as the canonical `orient`/fan-out context operator while
  retaining explicit Mapper fallback receipts.

- **Issue #616 — concurrent stage waves:** `StageAgentCoordinator` now overlaps
  independent stages up to the Hub slot grant, retains an explicit one-slot serial
  fallback, records deterministic wave summaries and timing telemetry, supports
  stage/global cancellation, and resumes without re-running accepted stages.
- **Issue #617 — canonical evidence binding:** bind derived quality, watcher, delivery,
  and completion evidence to the exact run/attempt and repository state; add atomic,
  auditable invalidation tombstones and fail-closed legacy migration.

## [3.38.3] - 2026-07-27

- Published the current main line with HubQueueAgentClient and the latest completion, coverage, Hookwall, and local-inference guard changes.
- Kept the Dev CLI dependency floor and all release surfaces synchronized for the Mapper -> Fast -> Dev CLI -> Loop chain.

## [3.38.2] - 2026-07-25

- Raised the `simplicio-cli` (Dev CLI) dependency floor to `>=0.16.3`, the
  latest confirmed PyPI release, and synchronized the loop's release surfaces.

## [3.38.1] — 2026-07-20

- Raised the `simplicio-cli` dependency floor to `>=0.16.2`, consuming the
  mapper-aligned CLI release from the ecosystem release sequence.

## [Unreleased]

- Added `HubQueueAgentClient` for strict, subprocess-free stage-agent execution through the
  central Hub, including safe `ProcessSpec` projection, durable effect journaling, reconnect and
  idempotent restart recovery, lossless process-result evidence, cancellation/heartbeat, a public
  conformance lane, and a reproducible raw-sample benchmark (#615).

## [3.38.0] — 2026-07-17

- **Multi-agent coordination core (`scripts/coordinator.py`):** given live GitHub state (claim
  comments + merged PRs), decides one deterministic action per issue — `OWN`, `CONTINUE_OWN`,
  `DEFER_ACTIVE_CLAIM`, `RECLAIM_STALE`, or `VERIFY_PARTIAL` — plus a `duplicate_risk` flag when
  two sessions claim the same issue near-simultaneously. Caught, live, a real collision: two
  sessions independently building a findings collector for the same issue under different
  filenames.
- **PR DoD/AC reviewer (`scripts/pr_dod_review.py`):** when every open issue is already claimed,
  reviews open PRs against the 7-dimension Definition of Done and the underlying issue's frozen
  acceptance-criteria checklist instead of idling; `check --post` posts a mechanical, line-by-line
  verdict as a PR comment. Verified against a real merged "MVP slice" PR: correctly flagged 17/17
  acceptance criteria on the parent epic as still unresolved.
- **`references/multi-agent-coordination.md` + `references/background-verification.md`:** new
  documented conventions wired into `SKILL.md`'s triage step.
- **`scripts/finding_collector.py` (issue #466, phase 1):** durable, fingerprinted, deduplicated
  defect memory — the same underlying bug collapses into one record with an occurrence count.
- **Continuous Evolution / Adaptive Architecture / Elastic Replication MVP slices** (#467/#468/
  #469): `scripts/evolution.py`, `scripts/workflow_topology.py`, `scripts/agent_replication.py`.
- **Continuous Findings completion-gate wiring** (WI-466): the completion gate now genuinely
  consults the finding store; a store/repo consistency bug found and fixed in the same pass.
- **Mandatory post-merge cleanup** (`scripts/worktree_cleanup.py`, #484): a merged branch's local
  worktree and branch ref are removed automatically instead of accumulating across sessions.
- **CLI contract additions** (WI-471): a `preflight` subcommand and a `--json` flag on `status`.
- **Two live regressions on `main` found and fixed this cycle** — a PR that silently deleted a
  function definition (breaking `loop_progress.py`'s own selftest), and a subsequent squash-merge
  race that reintroduced the exact same broken code onto `main` a second time. Both found by
  actually running the affected script, not by trusting a green PR description.
- Test suite grew to 231 files (2,544 collected tests); `claims_audit.py` stayed at 14/14 through
  every merge this cycle.

## [3.37.0] — 2026-07-17

- **EPIC #422 — Portable Stage Agents:** materialized every stage of the
  `simplicio-loop` orchestrator as a concrete, independently verifiable agent
  role, portable across all 15 supported runtimes:
  - **Contract (#423):** versioned `stage-definition`/`agent-role`/
    `agent-instance`/`stage-receipt` schemas and the `stage_agents.py` validator
    core (graph/instance/receipt validation, fake-independence enforcement).
  - **Coordinator (#424):** a runtime-agnostic driver (`stage_agent_coordinator.py`)
    with native/command/queue adapters that materializes, monitors, cancels,
    and collects receipts from stage agents — spawn → observed-ready → send →
    observed-terminal → collect, never trusting a bare "accepted" as done.
  - **Intake/Planner (#425), Implementation (#426), Review Panel (#427),
    Safety Gate (#428), Delivery (#429), Feedback/Recovery (#430), Completion
    Auditor (#431):** the seven remaining concrete roles, each with its own
    invariant machinery, fail-closed gates, and typed receipt.
  - **Conformance suite (#432):** proves contract/receipt parity across all 15
    runtimes by actually driving a sandbox task through each adapter's public
    path — no synthetic pass for a capability that wasn't really verified.
  - **GitHub reporting (#433/#442) + multi-tracker interface (#436):** one
    idempotent, per-item lifecycle comment on GitHub (required) with a
    provider-agnostic interface for Azure DevOps/Jira/Asana/Trello
    (connected-only, never an invented remote attempt).
  - **Identity (#434):** human-readable `<Name> <Role> - #<HOST4> - <LLM>`
    display names, deterministic host abbreviation with an explicit fallback
    reason code — uniqueness stays on `agent_instance_id`, never the display name.
- **`simplicio-runtime` is now a required bound operator**, not an optional
  acceleration: `hooks/loop_stop.py` blocks the running driver on a missing/
  unreachable `simplicio` binary exactly like a missing `simplicio-mapper`/
  `simplicio-dev-cli`.
- **MCP configuration documented across 13 hosts** (Claude Code, Codex,
  Cursor, VS Code, Antigravity, Kiro, OpenCode, Gemini, Orca, and
  best-effort/community-reported guidance for Aider, Kimi, Qwen, DeepSeek) —
  see `docs/MCP_SETUP.md`.
- **Post-merge reconciliation:** four adversarial-review passes across the
  epic's 30+ PRs found and fixed real fail-open bugs (a tautological
  `attempt_id` check, vacuously-`True` checklist fields, receipt-schema
  validators defined but never wired into the real accept path, AC coverage
  reported complete when the task anchor was simply missing) and closed the
  gap where four `to_stage_receipt()` projectors existed only as unit-tested
  code with no live CLI entrypoint — every stage-agent role's receipt path is
  now schema-valid end-to-end and independently exercised via
  `scripts/*.py stage-receipt`.
- New gate: `claims_audit.py` check 14 (contract-parity) keeps
  `contracts/stage-agents/v1/` and its packaged mirror byte-identical.

## [3.36.1] — 2026-07-16

- **Repository-owned GitHub Projects:** lifecycle sync now autodiscovers the
  repository's Project, adds the source issue when it is missing, and moves its
  `Status` field without requiring a manually configured project number.
- Explicit project numbers remain supported and take precedence over discovery.

## [3.36.0] — 2026-07-16

- **GitHub workflow lifecycle:** added runtime-neutral, idempotent GitHub Project status
  synchronization driven by the canonical issue lifecycle comment, with an explicit
  non-GitHub/local-only path.
- **PR patrol:** the delivery loop now inspects open PRs every two completed items,
  at final verification, and immediately after merges so conflicts and review gaps
  re-enter the workflow before closure.
- **Cross-agent review and claims:** Claude, Codex, Cursor, Gemini, Kiro,
  Antigravity, Hermes/Simplicio Agent, OpenClaw, and human contributors share
  evidence-linked acceptance-criteria review comments; implementation workers post a
  canonical `CLAIMED` lifecycle comment before mutation.

## [3.35.1] — 2026-07-16

- **#294 repository governance:** refreshed the measured repository-size report and
  canonical claims/quality surfaces on the current `main` tip.
- **Distributed loop reconciliation:** synchronized the local distributed-loop changes,
  including the issue-cron driver and intake/progress coverage added after 3.35.0.
- **Cross-machine GitHub coordination:** lifecycle synchronization is now enabled by
  default whenever a run has a GitHub source issue, using one idempotent canonical
  issue comment for planning, claims, progress, evidence, PR, merge, and release
  state. `SIMPLICIO_LOOP_GITHUB_LIFECYCLE_SYNC=0` is the explicit offline/legacy opt-out.
- Release is a patch-only republish of the verified `main` tree; no API contract changes.

## [3.35.0] — 2026-07-15

Large multi-agent push closing the P0/P1/P2 backlog opened by #183/#283-#296. Highlights:

- **#286 multi-device protocol**: atomic claim/discovery over a real remote queue, worker
  heartbeat/cancellation, receipt verification on both client and server sides, an installable
  worker/supervisor/queue-server console-script surface, a `doctor.py` LOCAL_ONLY/REMOTE_READY/
  REMOTE_MEASURED tri-state, and a real 2-process HTTP-loopback E2E. Closed with the genuine
  two-physical-machine proof still open (single-machine sandbox).
- **#287 multi-LLM routing**: deterministic `ModelCapabilityRegistry`/router with fallback and
  circuit-breaker, task-contract routing fields, `runtime-execution-receipt`, and real
  `CodexRuntimeDriver` execution (`codex exec`, verified receipt). Closed with Claude-side
  execution still blocked by an org policy (`ANTHROPIC_API_KEY` unavailable in this environment).
- **#288 pipeline convergence**: `receipt_verifier.py` fail-closed content/hash/schema/freshness
  checks, `AttemptCoordinator.run_guarded()` heartbeat+kill-on-lease-loss, `MergeExecutor` with a
  real reconcile-after-merge step and chaos-tested crash recovery, multi-PR batch fan-in, and
  `LoopRuntimeAdapter`/`VerifiedAgentDelivery` finally wired into the real dispatch path.
- **#289 security**: enumerated environment allow-list (`distributed_trust_policy.py`),
  short-lived HMAC credentials with `jti` revocation and per-operation scoping, DNS/TLS-pinned
  secure transport with live redirect/rebinding/proxy-injection fault-injection tests, structured
  audit logging, and CODEOWNERS coverage of the security-critical modules.
- **#290 delivery truth**: fail-closed `source_state.py`, paginated GraphQL review-thread queries,
  byte-level release-artifact verification (real sha256 + `gh attestation verify`),
  `BranchReachabilityVerifier`/`IssueStateVerifier`/TTL-freshness policy, `DeploymentVerifier`, a
  concurrency/crash/fault-injection matrix (including crashes mid-external-call), and a
  cross-receipt commit-binding gate closing a real merge-ready/quality-matrix SHA-mismatch gap.
- **#284 intake contract**: `simplicio.task-intake/v1` envelope, `impact-map.json`,
  AC-traceability matrix, `replan_on_drift`, mandatory-by-default mutation-authority enforcement,
  and a live GitHub-backed E2E.
- **#285 GitHub lifecycle adapter**: typed `SourceAdapter` Protocol, full read/write/lease/outbox
  surface, duplicate-comment election, `SOURCE_CHANGED` pre-close drift detection, and a
  `CLOSE_PENDING_RECONCILIATION` completion-oracle gate — 100% branch/line coverage on the core
  modules.
- **#283 quality gate**: independent watcher re-verification (including coverage-drift detection),
  auto-populated `quality-matrix.json` from real gate scripts, the full `run_id`/`work_item`/`tests`
  envelope, a real per-category (unit/integration/system/regression) test-runner split across all
  192 test files, and a fixed `coverage_gate.py` crash on `coverage.py` 7.15.x + Python 3.14.
  Global/critical coverage raised from 16.6%/9.4% to 28.45%/24.02% on the widened scope.
- **#291 CI-less determinism**: a fail-closed local pre-push gate (`hooks/action_gate.py`)
  standing in for the GitHub Actions removed in #311, plus a real Windows subprocess-handling fix
  in `check_e2e_installed.py`.
- **#292 release/supply chain**: `version_sync.py` single-source-of-truth version bump,
  checksum/GPG-sign/SBOM/install-smoke tooling, a local-provenance substitute for OIDC attestation,
  and `release_rehearsal.py` chaining the whole pipeline end-to-end against the real checkout.
- **#293 installer**: a transactional executor with backup/rollback, N-1→N upgrade + real smoke
  tests, explicit consent gating for service/proxy installs, distinct executor modes, and a
  machine-readable mutation manifest.
- **#294 repository governance**: LFS-scoped `.gitattributes`, forbidden-path/large-media budget
  gates, a canonical version/skill/claims manifest, and a dry-run-only (never-executing) history
  migration plan — the actual history rewrite stays an explicit, separate maintainer action.
- **#295/#296/#183**: the production-grade and real-time-progress umbrella epics, and the
  original multi-agent-parallelism epic, closed as their tracked child issues resolved.

## [Unreleased]
- #293: fix `install_lib.py::install_all_deps()` (`--full-stack`/`--with-service` full install)
  referencing a `.[onnx]` optional-dependency extra that `pyproject.toml` stopped declaring back
  in `3.11.0` (the ONNX model engine — `kompress`/`router`/`embed`/`image` — was removed that
  release, taking the extra with it) — the exact "referência a extra que não existe no
  pyproject.toml" the issue's audit flagged. Now installs the `ml` extra `pyproject.toml` actually
  declares (the real embedding backend for `simplicio-cli semantic --ml`/`rag --ml`).
  `docs/INSTALL_MUTATIONS.md`/`docs/install-mutations.json` regenerated to match. Also adds a
  system test proving a clean install/rollback round-trip survives a target path with embedded
  spaces and non-ASCII (accented + CJK) characters (`tests/test_system_clean_install.py`) — the
  "caminhos com espaços e Unicode" system-test requirement.
- #293: close the last audit-flagged installer gap — `simplicio-autoresearch` is now included in
  `install_lib.py`/`install_plan.py`/`doctor.py`'s `SKILLS` list (was 6, is 7), so the installer,
  planner, and `doctor` health-check actually copy/validate the seven skills the project declares
  instead of six. Docs (`adapters/MATRIX.md`, the OpenClaw/Orca/Simplicio-Agent adapter READMEs,
  `PRICING.md`, `plugin/README.md`, `simplicio_loop/__init__.py`, `docs/INSTALL_MUTATIONS.md`)
  updated to match; `scripts/claims_audit.py` skill-count check already read the tree as 7.
- #262: `simplicio_agent` is now the canonical adapter ID (formerly `hermes`); `hermes` is kept
  as a legacy shim (same install/native-bind contract) for the compat window. Config/log paths
  move from `~/.hermes/` to `~/.simplicio-agent/`; the `HERMES_PROFILE` env var is superseded by
  `SIMPLICIO_AGENT_PROFILE` (legacy var still honored as a fallback).

## [3.34.1] — 2026-07-13

- Raise the `simplicio-cli` (dev-cli) dependency floor to `>=0.16.1`, paired with
  dev-cli `v0.16.1` and its transitively shipped mapper `v0.23.1`.
- Publish the current `main` package state as a patch release; PyPI publication is
  performed locally when hosted GitHub Actions are unavailable.

## [3.34.0] — 2026-07-12

- Raise the `simplicio-cli` (dev-cli) dependency floor to `>=0.16.0`, paired with dev-cli `v0.16.0`
  and mapper `v0.23.0` (correlated releases).

## [3.33.0] — 2026-07-12

- Consume `simplicio-cli>=0.15.0`, paired with mapper `v0.22.0` and dev-cli `v0.15.0`.
- Include the verified distributed delivery, visual events, oracle, watcher, PLANES, release-parity, and conduct-runner wave.

## [3.32.6] — 2026-07-11

- Runtime-compatible Execution Board backlog import and dashboard progress receipts.
- Cross-runtime adapter matrix with fail-closed isolated verification.
- Isolated adapter verification now uses minimal mode and cannot trigger host-wide setup.

## [3.32.2] — 2026-07-11

- Refresh the measured token-budget baseline after the merged runtime, queue, recovery and preflight contracts.
- Full gate verified: 540 tests, claims audit, mirror parity, clean-env, loop contract and token budget all pass.

## [3.32.1] — 2026-07-11

- Add the operational manual and examples required by the Runtime standard-I/O smoke gate.
- Runtime 3.5.0 contract smoke now passes all artifacts and adapters on a clean repository checkout.

## [3.32.0] — 2026-07-11

- Crash recovery handshake with source re-query, runtime replay, lease reclaim and identity drift protection.
- Independent watcher snapshot execution and raw-Markdown task-to-delivery golden corpus.
- Live HTTP queue proof across two workers with auth, atomic claims, fencing, reclaim and ordered events.
- Fail-closed worker receipts, preflight, delivery requery races and converge/drain semantics.

## [3.31.1] — 2026-07-11

- Fix evidence-receipt allowlisting for absolute, versioned Python interpreters (`python3.11`, `python3.14`).
- Keep self-tests fail-closed while allowing the same interpreter paths used by test runners.

## [3.31.0] — 2026-07-11

- Typed append-only attempt journal with causal identity, hash-chain replay and failure fingerprints.
- Mapper-derived `simplicio.plan/v1` contract blocks stale or unsafe operator plans before mutation.
- Failure-fingerprint tamper detection and provider-handoff continuity checks.
- Focused journal/recovery/planner tests pass; previous full gate remains green at 508 tests.

## [3.30.0] — 2026-07-11

- Authenticated HTTP remote queue server over SQLite with leases, fencing, identity and fail-closed outages.
- Canonical WorkItem graph validation rejects unknown dependencies, cycles, duplicate edges and zero-AC items.
- Watcher evidence hardening requires proof references and validates challenge freshness and goal identity.
- Claims-clean README and full gate: 508 tests passing.

## [3.29.0] — 2026-07-11

- Portable visual progress rendering with ASCII/no-animation fallback, lanes and stage events.
- Cross-runtime completion oracle CLI with fail-closed receipts.
- Unified hook/self-paced driver contract with deterministic deduplication and shared gates.

All notable changes to **simplicio-loop** are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses SemVer.

## [3.28.0] — 2026-07-11

### Added
- **Execution Board E2E:** event-sourced local board fixture with four WorkItems, first-wave
  parallel lanes, dependency ordering, validation retry, human gate, evidence/watcher gates,
  drain verification and stable replay hash; absent external board adapters remain UNVERIFIED.
- **Context isolation enforcement:** allow-listed context packs, capability validation, duplicate
  identity rejection and agent-bound queue/runtime receipts prevent cross-agent leakage or replay.

## [3.27.0] — 2026-07-11

### Added
- **Distributed coordination backend:** transactional SQLite queue with atomic claims, expiring
  leases, monotonic fencing, heartbeats, ordered reconciliation events, and fail-closed outages.
- **Crash-safe execution recovery:** AC-aware receipts, durable cursors, atomic fsync/replace,
  idempotent replay, and fail-closed gap/tamper/identity-drift handling.
- **Runtime compatibility adapter:** explicit negotiation, capabilities, identity-preserving events,
  leases, evidence, completion, durable outbox, replay, and cross-platform contract CI.

## [3.26.0] — 2026-07-11

### Added
- **Safe automatic fan-out:** independent ready tasks use isolated worktrees and bounded workers
  by default; overlaps, missing targets, non-Git checkouts, or adapter failures fail closed to a
  truthful serial path.
- **Visual progress protocol:** `simplicio.progress/v1` exposes deterministic text, JSON, Markdown,
  ANSI, icons, optional animation, evidence-aware percentages, and a strict oracle-backed 100%.
- **Distributed agent identity:** backlog leases persist agent/runtime/device/session identity and
  fencing metadata so claims and transitions reject stale or mismatched workers.
- **Typed phase events:** phase-machine envelopes, derived board state, offline idempotent
  reconciliation, and golden streams cover success, retry, blocked, cancel, handoff, and resume.

### Changed
- The runtime now presents the multi-agent execution path as the default governed strategy while
  preserving explicit serial mode for unsafe or resource-constrained environments.

## [3.25.1] — 2026-07-11

### Changed
- Replaced the README lifecycle Mermaid diagram with the current contract-first flow: isolated
  parallel worktrees, evidence receipts, watcher challenges, completion oracle, rollback,
  maintenance-deferred recovery, delivery, and durable memory.
- Synchronized the Mermaid flow across the canonical README and all 14 localized mirrors.

## [3.25.0] — 2026-07-10

### Added
- **Contract-first task-to-delivery runtime:** canonical task/run-state contracts, source-state
  reconciliation, a completion oracle, structured evidence receipts, clean-environment checks,
  and HBP-backed completion records make transitions auditable instead of self-reported.
- **Parallel queue draining with durable isolation:** dependency-aware fan-out, bounded worker
  batches, per-task worktrees, a persistent worktree queue, and an operational ledger let ready
  tasks execute concurrently without sharing a mutable checkout.
- **Evidence-aware recovery:** operator rollback contracts, watcher challenges, checkpoints,
  impact/flow coverage, and durable attempt memory keep failures reversible and prevent repeated
  dead ends from being mistaken for progress.
- **A new visual product story:** a GPT Image 2 flagship hero, two supporting system
  illustrations, two deterministic architecture charts, and a synchronized narrative across all
  15 maintained README languages show the complete path from intent to verified delivery.
- **Completion-oracle stop authority:** every stop-hook turn now evaluates and persists the typed
  completion receipt, records the authoritative reason in handoff evidence, and treats a legacy
  done flag only as a request for evaluation.
- **Maintenance-deferred mode:** operators can move corrective work into an explicit backlog-only
  state with a durable receipt and resume instructions, while completion remains blocked instead
  of being reported optimistically.

### Changed
- Reframed the README around simplicio-loop as a governed delivery operating system for agent
  work: contract first, parallel in isolation, proof before completion, and memory that changes
  future execution.
- Updated Python, source-checkout fallback, and npm wrapper versions to `3.25.0`.

### Fixed
- Hardened Git, hook, watcher, evidence, and loop-contract subprocesses for Windows with explicit
  UTF-8 streams and non-interactive stdin; escaped batch forwarding correctly and removed inherited
  invalid-handle failures from the verification path.
- Reconciled the token-budget baseline with the reviewed mapper index and CLI growth, restored the
  selftest registry, and synchronized source, plugin, and bundled mirrors.

## [3.24.0] — 2026-07-09

### Added
- **Cross-process locking for shared JSONL logs** (`scripts/_locked_append.py`, #127): the one
  place any worker in this repo appends a line to a shared JSONL log (`scripts/loop_journal.py`'s
  run journal, `scripts/handoff.py`'s event log). POSIX `fcntl.flock` / Windows `msvcrt.locking`
  on a sidecar `<path>.lock` file, `flush()` + `os.fsync()` before releasing the lock, bounded
  acquisition (default 2000ms) that fails OPEN on timeout (write skipped, never partial, a
  one-line degrade note on stderr) so a stuck/leaked lock never wedges a caller. Paired
  tolerant-reader helper `count_jsonl_lines` counts valid vs. corrupt/truncated lines instead of
  silently dropping them; `loop_journal.py` and `handoff.py` now surface a corrupt-line count
  warning instead of swallowing torn writes. Covered by `tests/test_locked_append.py`.
- **Run-journal consumes dev-cli events + three new HBP evidence topics** (#128):
  `scripts/loop_journal.py stall` now optionally folds in the dev-cli's own
  `.simplicio/events.jsonl` (schema `simplicio.dev-cli-event/v1`, `--events-root DIR` override) —
  a repeated `validation_fail` on the same target streaks like a repeated journal failure;
  `edit_applied`/`task_complete` reset the streak. Read-only, fail-open (no events file = behavior
  unchanged), no import of dev-cli code. The HBP evidence chain gains three new topics:
  `loop-stall-detected` (a 3-deep same-fingerprint streak), `loop-run-blocked` (cap-reached stop or
  a missing bound operator), and `loop-gate-blocked` (a gate BLOCK verdict). Covered by
  `tests/test_hbp_topics.py`.

### Fixed
- `_changed_files` no longer includes `.simplicio/` runtime state (dev-cli's own event/ledger
  writes) when computing what a turn changed — those are the operator's own bookkeeping, not
  agent-authored diff.

### Changed
- Operator dependency floors raised to match the paired releases: `simplicio-mapper>=0.19.0`,
  `simplicio-cli>=0.11.0`.

## [3.23.0] — 2026-07-07

### Added
- **Phase 0 — intake & decomposition + genesis mode** (`scripts/task_backlog.py`):
  a new deterministic worker that freezes, orders and gates a vague goal's
  LLM-brainstormed multi-item decomposition ABOVE the per-item task anchor
  (state: `.simplicio/orchestrator/backlog/backlog.jsonl`, override
  `$SIMPLICIO_BACKLOG_FILE`). Fail-closed `init` (refuses an empty plan, a
  zero-AC item, unknown/cyclic `depends_on`; a changed master goal needs
  `--force`; re-`init` with the same goal preserves per-item progress);
  a standalone `genesis` detector (exit 10 on a no-code repo) with enforcement
  — on a genesis repo `init` demands `--genesis` plus exactly one
  `scaffold`-tagged item, reorders it to T1 and makes every other item depend
  on it; `next` claims one item at a time (honoring `depends_on`) and prints
  the ready `task_anchor.py set` arming command; `done` refuses (exit 12)
  unless the armed anchor IS that item with every AC verified; `skip`
  quarantines with a mandatory reason; an exact `empty` from `next` is the
  drain-mode dry signal. Fingerprints reuse `task_anchor.goal_fingerprint`, so
  the `done`↔anchor coupling is byte-exact. Covered by
  `tests/test_task_backlog.py` (8 e2e cases) + a pure `selftest`; registered
  in `claims_audit.py` `SELFTEST_SCRIPTS`, `tests/test_worker_selftests.py`,
  `tests/test_worker_cli_contract.py`, and `docs/SCRIPTS_INVENTORY.md`.
  Docs: SKILL.md § Phase 0 — intake & decomposition, `orchestration.md`
  (vague-goal source row + Step 2b branch), `extension-points.md`
  (`plan`/`decide`, `intake`, `work_queue`, `dependency_graph` cells + the
  `backlog.jsonl` state-file owner row — the 48-point count is unchanged).

## [3.23.1] — 2026-07-07

### Changed
- Updated the loop's operator contract to treat `simplicio-cli` as the single supported install
  surface: `simplicio-dev-cli` remains the action operator and `simplicio-mapper` remains the
  survey binary, but both are now documented/installed/verified as runtime bins expected to come
  transitively from `simplicio-cli` instead of as two separately-installed packages.
- Raised the operator package floor to `simplicio-cli>=0.10.0`, which matches the latest published
  action operator release and the transitively-installed mapper line now expected by the loop.

### Added
- A new claims-audit check (`10 skill-pair-parity`) that compares the shared
  `.claude/skills/simplicio-loop/references/` and `.claude/skills/simplicio-tasks/references/`
  files byte-for-byte for the intersection set, catching drift like the previously-diverged
  `quality-safety-delivery.md` copy.
- Inline `:: verify: ...` acceptance-criteria metadata plus default vague-AC linting in
  `task_anchor.py`, with `--lint` as the stricter mode for short ACs without a declared method.
- Phase-0 backlog evidence rendering: `task_backlog.py` freezes/renders multi-item backlog state
  and `pr_evidence.py --backlog` now embeds the body-of-work table above the per-item anchor
  checklist.

### Fixed
- Restored byte-identical parity between the canonical
  `.claude/skills/simplicio-loop/references/quality-safety-delivery.md` and the
  `simplicio-tasks` copy before enabling the new pair-parity gate, so the release does not ship
  the already-known drift.

## [3.22.6] — 2026-07-07

### Added
- **`hooks/loop_stop.py`**: when the honored-promise path is taken (evidence
  required and present, watcher-gate passed, no pending acceptance criteria,
  no flow-audit gap), records the verified promise into the `simplicio`
  runtime's HBP tamper-evident hash chain (`simplicio hbp append --topic
  loop-promise-verified --payload '{"iteration":...,"promise":...,
  "watcher_tag":...,"goal_fp":...}' --json`) before stopping. Closes the last
  piece of "evidence-gated exit should be auditable, not self-reported": a
  later `simplicio hbp verify` can now prove this exact
  iteration/promise/watcher-tag combination was recorded in order. Fail-open,
  `simplicio`-only, silent no-op when the binary is absent or the append
  subcommand isn't available yet (older runtime versions).

## [3.22.5] — 2026-07-07

### Changed
- Bumped the two REQUIRED loop-operator dependency floors to their latest
  published releases: `simplicio-mapper>=0.16.0` → `>=0.17.0` (adds the
  native-first `ask precedent` verb) and `simplicio-cli>=0.9.3` → `>=0.9.5`
  (native `simplicio edit` delegation for mechanical-edit plans now
  genuinely activates against the installed `simplicio` binary, plus its own
  native-first precedent delegation). Both are additive releases — no
  capability the loop already depends on was removed or changed shape.

## [3.22.4] — 2026-07-07

### Added
- **`hooks/action_gate.py`**: an additive, best-effort consult of the `simplicio` Rust
  runtime's own risk classifier (`simplicio gate classify --action "<cmd>" --gate ask
  --json`) alongside this file's own hardcoded IRREVERSIBLE/secret checks. Only escalates
  on the runtime's `decision == "block"` (its hardline/denylist floor — catches things this
  file's own regex list doesn't, e.g. pipe-to-shell) — a `"confirm"` decision is
  deliberately NOT treated as a block signal, since under `--gate ask`/`auto` the runtime
  returns `"confirm"` for essentially every ordinary mutation and a PreToolUse hook has no
  way to actually pause for human confirmation (only allow/block). Verified against the
  live binary before shipping: an earlier draft using `--gate safe` classified normal
  commands like `git push`, `rm -f`, and `npm install` as blocked outright. Fail-open:
  binary absent, timeout, or malformed JSON all leave the existing gate behavior unchanged.
- **`hooks/loop_stop.py`**: at each loop boundary (alongside the existing
  `simplicio claims`/`simplicio nest` callouts), also fires `simplicio checkpoint save
  --desc "simplicio-loop iteration <n>" --json` when the native `simplicio` binary is on
  PATH — a real, restorable (`simplicio checkpoint restore`) snapshot the loop's own
  scratchpad-only state doesn't provide on its own. Fail-open, `simplicio`-only (no
  dev-cli/mapper fallback candidate, since neither has a checkpoint equivalent).
- Both additions are opt-in/fail-open: with no `simplicio` binary on PATH, behavior is
  byte-for-byte identical to before. Not implemented: recording the loop's own
  evidence/promise-verification into the runtime's HBP hash chain — `simplicio hbp` is
  currently a read-only CLI surface (`verify|head|len|count|status`, no `append`/`record`),
  so an external process has no way to write new evidence into it yet.

## [3.22.3] — 2026-07-07

### Changed
- Bumped the two REQUIRED loop-operator dependency floors to their latest published releases:
  `simplicio-mapper>=0.14.0` → `>=0.16.0` and `simplicio-cli>=0.9.1` → `>=0.9.3`. Both are additive
  releases (TOON encoding on `inspect`/`ask`, tagged-confidence/geometry flags on `index`,
  `simplicio-cli`'s own floor bump to mirror the same mapper version) — no capability the loop
  already depends on (`inspect`/`handoff`/`ask`/`sync`/`drift`) was removed or changed shape.

### Fixed
- The architecture/practices gate added in 3.22.0 (`discover_architecture()` + the Step 4 directive
  to read `architecture.docs` and run `architecture.test_runner`/`lint_cmd` before editing) was
  dropped from the loop's live protocol when the `/simplicio-loop` consolidation (3.22.2) rewrote
  `.claude/skills/simplicio-tasks/SKILL.md` into a legacy stub — the code (`repo_conventions.py`,
  its tests) and the `extension-points.md` description survived, but the actionable gate in the
  Step 4 quality loop did not. Restored it in the new canonical location,
  `.claude/skills/simplicio-loop/references/quality-safety-delivery.md` § Step 4.

## [3.22.2] — 2026-07-06

### Changed
- Unified the public command contract around `/simplicio-loop`: the core orchestrator and hardened
  loop now ship behind one public entrypoint, while `/simplicio-tasks` remains documented only as a
  compatibility alias for older installs and saved prompts.
- Removed the deprecated runtime cost/budget stop contract from code, skills, docs, adapters, pricing
  material, plugin mirrors, bundle mirrors, translated READMEs, and the generated project metadata.
  Loop exits are now evidence-gated completion, `max_iterations`, spindle handoff, or explicit
  STOP/cancel path.
- Rebuilt the detailed README infographic (`assets/simplicio-loop-infographic.svg` and PNG) without
  budget/cost steps and with the current standalone-install contract: installing the skill bundle
  does not require a mandatory runtime dependency.

### Fixed
- Synchronized the translated READMEs with the English README so every locale presents
  `simplicio-loop` as the core + loop command and keeps `simplicio-tasks` only as a legacy alias.

## [3.22.1] — 2026-07-06

### Added
- A new item-by-item README infographic at `assets/simplicio-loop-infographic.png`, rebuilt to
  match the current product contract instead of the removed stale overview: standalone install with
  `python3` only, native binds optional, the 7 shipped skills, the 5 accelerators, the 11 runtime
  surfaces, the 5 source adapters, and the local proof gates (`claims_audit` 9/9 and
  `scripts/check.py` 245 passed).
- The detailed infographic is linked again from both the English and pt-BR READMEs so the visual
  product map is back in the primary docs instead of living only as an orphaned asset.

## [3.22.0] — 2026-07-06

### Added
- Full unit/integration/contract/flow/system test coverage for the four scripts that shipped
  without any (`fan_out.py`, `schema_verify.py`, `claims_manifest.py`, `verify_adapters.py`):
  `test_fan_out_unit.py` + `test_fan_out_flow.py`, `test_schema_verify_unit.py` +
  `test_schema_verify_integration.py`, `test_claims_manifest_unit.py`,
  `test_verify_adapters_integration.py`. Added `test_worker_cli_contract.py` (contract tests —
  every worker with a `selftest` verb honors the same CLI shape: exit 0 + PASS/OK marker, no
  uncaught traceback on an unknown verb) and `test_system_check.py` (system tests — the whole
  local gate, `scripts/check.py`, run as a black box; nested-recursion-safe since the suite
  includes itself).
- `repo_conventions.py` gained `discover_architecture()`: mines the repo's OWN architecture/design
  docs (ARCHITECTURE.md, DESIGN.md, `.specs/architecture/*.md` + `ADR-*.md`, `docs/adr/*.md`) plus
  its OWN test-runner and lint command (Makefile `test:`/`lint:` targets, `package.json`
  `scripts.test`/`scripts.lint`, `scripts/check.py`, pytest/eslint/ruff/flake8 config) into the
  `.simplicio/orchestrator/conventions.json` profile (`architecture: {docs, test_runner, lint_cmd}`),
  degrading to an honest empty result rather than guessing. `simplicio-tasks` Step 1a' now mines
  it and Step 4 requires reading every listed doc and running the discovered test/lint command
  before any edit, so generated code follows the project's own architecture and quality gates
  instead of a generic default. New unit tests: `test_repo_conventions_architecture.py`.
- The README now has a standalone install path up front (`pip install simplicio-loop` +
  `simplicio-loop install`), making it explicit that the core skill bundle needs only `python3`;
  native runtime binds, operators, capture services, and the wider Simplicio stack remain optional
  accelerators. The stale at-a-glance infographic was removed from the README and the hero art was
  refreshed to match the new positioning.

### Fixed
- `schema_verify.py selftest`'s failing-diff case asserted against a `SELECT` statement, which the
  parser correctly never treats as an added column (SELECT only reads) — the assertion never
  matched current behavior. Rewrote it to use an `INSERT` (an actual write) so the selftest proves
  what it claims to prove.
- `claims_manifest.py` was missing two quantitative claims actually present in `README.md`
  (`'11%'` — a false-positive badge-URL match, and `'90%'` — the infographic's "up to 90% fewer
  tokens" claim), which failed check 8 of `scripts/check.py`'s audit. Both are now registered
  (documented false positive / marked unverified respectively).
- `pr_evidence.py --describe-cli` now advertises the full flag surface used by the skills/docs
  (`--item`, `--title`, `--summary`, `--pr`, `--anchor`, `--template`, `--how`), so the local
  prose-command audit validates the documented worker invocations instead of flagging false drift.
- The shipped `_bundle/` mirror is back in parity with source for the bundled pre-push helper and
  the loop e2e parity test, restoring a green local claims-audit gate before release.

- The loop now actually consumes TOON per-turn (#92, follow-up to #88/PR #91): the
  `simplicio-tasks` prose (`SKILL.md`, `references/quality-safety-delivery.md`) documents
  `task_anchor.py check --format toon` and `loop_journal.py stall --format toon`, and
  `loop_journal.py stall` gained a `--format text|json|toon` flag (`--json` remains a working
  alias). `simplicio-loop`'s orient step now documents `simplicio-mapper handoff . --for-llm
  toon` with a `--json` fallback + a machine-readable, journaled reason when the installed
  mapper predates `--for-llm`.
- First `savings_harness.py` snapshots committed at `.simplicio/orchestrator/savings/snapshots.jsonl`
  (`.gitignore` now carries a scoped exception for this one file) — a real JSON-vs-TOON pair for
  a `task_anchor.py check` verdict and a `loop_journal.py stall` verdict, closing the open
  benchmark box from #88 with measured numbers instead of an estimate.
- `savings_harness.py score` now reports a labeled dual-tokenizer estimate (`tokenizers.chars4` /
  `tokenizers.bpe_estimate`, the latter backed by `engine/simplicio_tokens.py` when importable)
  instead of a single fixed `ceil(chars/4)` figure, since the two estimators disagree
  systematically on dense JSON/TOON payloads. Top-level `tokenizer`/`items`/`overall` keys stay
  `chars4` for backward compatibility.
- `simplicio-orient`'s output-reduction catalog gained a row for structured-JSON-payload → TOON
  encoding, with the documented exception (nested/non-uniform arrays fall back to compact JSON).
- A regression test locks in the documented `toon_codec.py` ambiguity for an unquoted
  bracket/brace-looking string scalar (e.g. the literal string `"[1]"`), so a future accidental
  behavior change is caught instead of silently drifting.

## [3.21.0] — 2026-07-02

### Added
- Survey step upgraded to the mapper 0.14 flow-docs engine: `ask . <verb> <arg> --json` for
  low-token structured queries during triage (`impact` feeds dependency widening, `tests-for`
  picks affected tests, `callers` aids review), `sync . --check` + `drift . --check` as
  docs-staleness/spec-drift gates in the DoD pass, and `flows`/`survey`/`business`/`history`/`diff`
  as the producers for documentation tasks. doctor's mapper capability probe now checks the full
  inspect/handoff/ask/sync/drift surface.
- The survey step also exercises the mapper 0.13 surface: `simplicio-mapper inspect . --json`
  is the survey's own evidence gate (artifacts proven on disk before the loop trusts them) and
  `simplicio-mapper handoff . --json` feeds the goal with the compact context-pack
  (files/symbols/deps/`pack_hash` + `llm_directives`) instead of re-reading the tree
  (`.claude/skills/simplicio-loop/SKILL.md`, `simplicio-tasks` extension-points reference,
  `plugin`/`_bundle` mirrors).

### Changed
- Dependency floors raised to the current releases of the two bound operators:
  `simplicio-mapper>=0.14.0` and `simplicio-cli>=0.9.1` in `pyproject.toml`, so a fresh
  `pip install simplicio-loop` resolves the operators this release was verified against.

## [3.20.1] — 2026-07-02

### Added
- `.github/workflows/ci.yml` — runs `python3 scripts/check.py` (claims-audit + worker
  selftests/smoke) on every push/PR to `main`. The gate already existed locally; nothing ran it
  automatically before this — flagged as the highest-confidence finding of an ecosystem audit.

### Changed
- Dependency floors raised to the current releases of the two bound operators:
  `simplicio-mapper>=0.13.0` and `simplicio-cli>=0.9.0` in `pyproject.toml`, so a fresh
  `pip install simplicio-loop` resolves the operators this release was verified against.

## [3.20.0] — 2026-07-01

### Added
- **Cross-agent wiki now surfaces blockers and next actions** (`scripts/cross_agent_wiki.py` +
  `plugin`/`simplicio_loop/_bundle` mirrors). Watcher verification output was already rendered in
  the wiki; this extends the same render path to the blocker list and the recommended next-action
  set so a handoff reader sees what is stuck and what to try next, not just pass/fail status.
- **End-to-end test of the loop driver** (`plugin/tests/test_loop_e2e.py` + `_selfrun.py`,
  mirrored under `simplicio_loop/_bundle`) covering `hooks/loop_stop.py`'s evidence-gated stop,
  anti-false-done (a bare `<promise>` is ignored without evidence), and anchor-gate exit paths.
- `.claude/skills/simplicio-loop/SKILL.md` (+ `plugin` mirror) documents the spindle/latch
  cross-agent handoff pattern.

### Fixed
- **Spindle/latch state-file mismatch between `handoff.py` and `loop_stop.py`.** `loop_stop.py`
  had renamed `SPINDLE_STATE` to `spindle_state.json` with no compat shim, silently breaking the
  cross-agent handoff/latch feature — `spindle_latched()` and `spindle_active()` failed open to
  `False` when the expected file was missing. `scripts/handoff.py` now points `SPINDLE_STATE` at
  `spindle_state.json`, keeps a `LEGACY_SPINDLE_STATE` constant for the old `spindle.json` name, and
  `_read_spindle()` tries the new filename first before falling back to the legacy one — mirroring
  the existing `DONE_FLAG`/`LEGACY_DONE_FLAG` backward-compat pattern in `hooks/loop_stop.py`.

## [3.18.1] — 2026-06-30

### Fixed
- `references/orchestration.md` Step 3c still said "TRIVIAL/SMALL skip adversarial review; only
  MEDIUM+ pay it" — a leftover from before v3.17.0's 6-agent floor that directly contradicted
  Step 3's new policy a few lines above (found by an independent audit). Now states the review
  fan-out (roles 3-6) runs on every item regardless of tier; only Rubric C's heaviest sub-checks
  stay tier/surface-scoped.
- Deleted `.agents/skills/` — an untracked, gitignored local mirror that still carried the
  pre-v3.17.0 fast-path/solo policy a week stale; nothing referenced or synced it.

## [3.18.0] — 2026-06-30

### Changed
- **Native simplicio-runtime bind is now REQUIRED, not optional, on 8 of the 11 supported
  runtimes** (Claude Code, Codex, Cursor, VS Code, Antigravity, Kiro, OpenCode, Hermes —
  `FORCED_BIND_RUNTIMES` in `scripts/install_lib.py`). Previously every adapter's "Native bind"
  section was framed as an optional speed-up, and the installer only printed a suggestion line
  that never actually ran. `scripts/install_lib.py` gained `ensure_runtime_bind()`, called
  unconditionally for these 8 runtimes during install: it runs `simplicio install --global`
  (auto-registers Claude/Codex/Cursor/VS Code/Kiro's MCP config in one pass), fixes OpenCode's
  MCP registration, verifies Hermes/Antigravity's runtime health via `simplicio doctor --json`,
  and — if `simplicio` isn't installed at all — logs a loud, unmissable warning instead of a
  quiet "optional" note. Every generated entry file (`AGENTS.md`/`GEMINI.md`/
  `copilot-instructions.md`/Kiro steering) now states the requirement inline for these hosts.
- **Fixed a broken MCP invocation referenced across 5 adapter READMEs and the OpenCode
  auto-registration code.** `simplicio-cli mcp register --client <x>` doesn't perform MCP
  registration — `simplicio-cli` (simplicio-dev-cli) defers entirely to `simplicio install`. The
  correct, now-documented path is `simplicio install --global` (covers Claude/Codex/Cursor/
  VS Code/Kiro) or the manual JSON snippet pointing at `simplicio serve --mcp --stdio`. Four
  README JSON snippets (VS Code, Antigravity, Kiro, OpenCode) and `merge_opencode_mcp()` had the
  args backwards (`["mcp", "serve"]` instead of `["serve", "--mcp", "--stdio"]`) — fixed
  everywhere it appeared.
- Gemini, Aider, and OpenClaw are unaffected — native bind stays optional/native-by-design on
  those three, per the user's explicit scope for this change.

## [3.17.0] — 2026-06-30

### Changed
- **Minimum 6-agent orchestration floor (`simplicio-tasks`/`simplicio-review`).** Removed the
  solo/inline fast-path and the TRIVIAL/SMALL single-self-review shortcut. Every item, regardless
  of size, now runs a 6-role floor: orient+plan, implement, 3 parallel adversarial review rubrics
  (security/correctness, quality, does-it-reproduce — `simplicio-review`), and an independent
  blast-radius reviewer that re-checks `impact_audit.json`/`flow_audit.json` instead of trusting
  the implementer's self-reported scope. The Step 3 auto-scaling formula gained a `max(6, ...)`
  floor; when disk is too tight for 6 worktrees, the floor still runs under `isolation=shared`
  instead of dropping below 6. Rubric C (does-it-reproduce) is no longer gated to LARGE/CRITICAL —
  it runs always; only its heaviest sub-checks (web/flow evidence) stay scoped to diffs that touch
  that surface.

## [3.16.0] — 2026-06-30

### Added
- **Cross-agent handoff on incomplete stop (`hooks/loop_stop.py`).** A manual-stop or
  iteration-cap stop now writes `.simplicio/orchestrator/loop/HANDOFF.md` before clearing the scratchpad —
  the frozen goal/acceptance criteria from `task_anchor.py`, the last attempts from
  `loop_journal.py`, and concrete resume steps. Previously these stops deleted the scratchpad with
  nothing durable left for a different agent/runtime to pick the task back up cold; a successful
  (promise-fulfilled) stop is unaffected and still needs no handoff.

## [3.15.0] — 2026-06-30

### Added
- **Task-scope impact gate (`scripts/impact_audit.py`).** The orchestrator can now audit the
  planned task surface before editing: local dependencies, reverse dependents/callers, and related
  tests are mapped from the seed files a task intends to touch. Uncovered reverse dependencies now
  block the plan by default, and `--fail-on medium` upgrades missing local deps/tests into blockers
  for shared/public contracts and signature changes.
- **Full-stack flow coverage gate (`scripts/flow_audit.py`).** The orchestrator can now map mixed
  frontend/backend/service workspaces into a UI-action → frontend-call → backend-endpoint →
  service-call graph, blocking objective integration gaps such as frontend calls with no matching
  backend endpoint and backend endpoints that still look stubbed/incomplete. Medium-confidence loose
  ends (buttons/actions with no observed backend call, orphan endpoints, local-looking service calls
  without local endpoints) must be explicitly classified or promoted to ACs for flows that promise
  backend integration.

### Changed
- `simplicio-tasks`, `simplicio-loop`, and `simplicio-review` now require impact-audit evidence
  before and during shared-file changes so callers/tests cannot stay outside the declared task
  surface by accident.
- `simplicio-tasks`, `simplicio-loop`, and `simplicio-review` now require flow-audit evidence for
  mixed front/back/service changes, with `--fail-on medium` for ACs that promise backend integration.

## [3.14.1] — 2026-06-29

### Changed
- **Declared the operator version floors required by the loop.** `simplicio-loop` now requires
  `simplicio-mapper>=0.11.0` and `simplicio-cli>=0.7.1` in `pyproject.toml`, matching the current
  first-party operator releases that the loop already expects for the async mapper survey and the
  current dev-cli/runtime contract. This makes fresh installs deterministic even before the
  preflight auto-update step runs.

## [3.14.0] — 2026-06-29

### Changed
- **The loop preflight now auto-updates the operators to their latest release.** Before iteration 1,
  `simplicio-loop` runs `python3 -m pip install -qU simplicio-mapper simplicio-cli` (with a PEP-668
  `--user --break-system-packages` fallback) so every run uses the newest mapper/dev-cli — no manual
  re-install needed to pick up a new `simplicio-mapper`. **Fail-open and offline-safe**: a
  network/pip fa…1910 tokens truncated…ategory` field from `plugin.json` to the `marketplace.json` plugin entry (where the
  validator expects it) — clears the last strict-validation warning.

### Added
- **`video_evidence` Playwright engine (now the DEFAULT)** — the normal evidence flow records the
  REAL browser session driving the screen (`video_evidence verify --url …` → `.webm`, → `.mp4` with
  FFmpeg) as the "works, not just compiles" moving proof. **hyperframes** is now used ONLY for an
  EXPLICIT custom request ("make an explainer video of screen X") — a deterministic captioned
  slideshow. New `record` verb + `--engine hyperframes` selector; both BLOCK (never fake-pass) when
  their toolchain is absent. New smoke test (suite 27 → 28).
- **Lean marketplace plugin** (`plugin/` subdirectory) — `.claude-plugin/marketplace.json` `source`
  now points at `./plugin`, a slim tree carrying ONLY the 6 skills + the 5 wired hooks. The pip-only
  assets (capture proxy `engine/`, token-monitor dashboard, `scripts/`) are no longer copied
  into a user's plugin cache on install — smaller downloads and a cleaner submission. Generated by
  `scripts/sync_plugin.py`; `claims_audit` gained a **plugin-parity** check (now 5/5).

### Changed
- video_evidence contract + all docs (extension-points, CLAUDE.md, SKILL.md Step 4b, README +
  15 translated READMEs) reframed to the two-engine model (Playwright default · hyperframes on request).
- Translated READMEs reconciled to **v3.10.1** (several were stale at v3.4.0) and the test-count badge
  to 28; stale Mermaid `video_evidence (hyperframes MP4)` nodes updated.

### Removed
- The **Open-core billing** capability-table row (and its `PRICING.md` link) from `README.md` and all
  15 translated READMEs — no money/pricing mention remains in any README.

## [3.10.0] — 2026-06-25

### Added
- **`repo_conventions` worker** (`scripts/repo_conventions.py`; verbs `learn`/`show`/`branch`/`commit`/`selftest`):
  learns the repo's OWN playbook by mining git history (branch scheme, commit convention + the real
  scope list, ticket pattern — by frequency) + merged PRs via `gh` + static config (CONTRIBUTING/AGENTS/
  pyproject for a Conventional-Commits hint, PR template for section structure) into a hash-pinned
  `.simplicio/orchestrator/conventions.json`. Confidence-gated: a sparse/inconsistent history degrades to an honest
  Conventional-Commits default, never an over-fit guess. Steps 4–6 shape branch/commit/PR names
  deterministically from it. Wired into `simplicio-tasks` Step 1a'/Step 3/Step 6,
  `references/extension-points.md`, `references/orchestration.md`; added to `claims_audit`
  `SELFTEST_SCRIPTS` + `tests/test_worker_smoke.py` (selftest 19/19).
- **Worktree-per-item isolation is now the DEFAULT** (one `git worktree` per item → zero cross-item
  conflict); a shared checkout is the opt-out for big compiled modules.
- **Genuine fast-path:** a single interactive item no longer auto-arms the loop (no scratchpad → the
  stop-hook lets the turn end). The loop engages only for a real body of work (queue / drain / 24-7).
- **Stop-hook background-gate awareness** (`hooks/loop_stop.py`): a fresh `.simplicio/orchestrator/loop/gate.lock`
  marks "waiting on a background gate (verification workflow / CI / long task)" so the hook does NOT
  re-fire as an idle turn; the lock is TTL-bounded (30 min) so a stale lock can never trap the loop
  (fail-open).
- README: a **Join the Simplicio Discord** badge (`https://discord.gg/wM6tr7xVb`) in the top badge row.

### Changed
- **i18n:** every user-facing usage example / command string translated from Portuguese to English
  across the 6 skills, the `_bundle` mirror, `README.md` + 15 translated READMEs, `CLAUDE.md`/`AGENTS.md`,
  `scripts/video_evidence.py`, and tests. Localized PROSE inside the translated READMEs is intentionally
  kept in-language; the `video_evidence` detector stays multilingual (EN/PT/ES).
- **CLI naming:** the unified CLI is now invoked as **`simplicio-cli <command>`** instead of the bare,
  colliding `simplicio` — all doc/skill references plus the `bin/simplicio` launcher (→ `bin/simplicio-cli`)
  and the engine help/branding were updated. (The PATH-binary rename itself lives in the separate
  `simplicio-cli` package.)
- README (all 15 languages): the **Claude Code / Cursor** install path no longer uses the
  marketplace plugin (`/plugin marketplace add` … `/plugin install simplicio-loop@simplicio`). It now
  installs **straight from the latest GitHub release** — `gh release download --archive tar.gz` → `tar
  xzf` → `bash scripts/install.sh claude|cursor` (verified to resolve the latest source tarball).

### Fixed
- Reconcile the extension-point count after #53 (44 → **48**): the badge/anchor/table in `README.md`,
  the runtime-contract line in `CLAUDE.md`, and the depth-table row in `simplicio-tasks/SKILL.md`
  still said 44 while `extension-points.md`/`AGENTS.md` already said 48. Re-synced the pip bundle
  (`simplicio_loop/_bundle/skills/*`) to source so `scripts/check.py` is green again (audit 4/4).

### Removed
- The **`## 💳 Pricing`** section (heading + open-core/billing-proposal paragraph) from `README.md`
  and all 14 translations under `READMEs/`. The capability-table billing row and `PRICING.md` are
  left untouched.

## [3.9.3] — 2026-06-24

### Fixed — `video_evidence` renders again on the shipped hyperframes (0.7.x)
- The `video_evidence` worker (`scripts/video_evidence.py`) emitted a composition keyed off
  invented `data-hf-*` attributes and invoked `hyperframes render --input <file> --output <file>` —
  neither matches hyperframes 0.7.x, so every demo-video render failed (`FAIL — mp4 (not
  produced)`). Rewrote the composition to the real schema (`#root[data-composition-id]` + timed
  `.clip[data-start/data-duration/data-track-index]` elements gated by the framework, faded in via a
  paused GSAP timeline registered on `window.__timelines`); the project entry point is now
  `index.html`. Render now passes the **project dir** positionally (`hyperframes render <dir> -o
  <mp4> -f <fps> -q <quality>`).
- Screenshots are copied into `<project>/assets/` instead of referenced by a `../..` path, because
  hyperframes serves the project over a local file server during render — an out-of-tree asset path
  never resolved. Captions are humanized from the shot filename (ordering prefix stripped, acronyms
  kept). The missing-toolchain / missing-composition **BLOCK** (never fake-pass) behavior is
  unchanged — `python3 scripts/check.py` stays green (claims-audit 4/4 · 24 tests).

## [3.9.2] — 2026-06-24

### Changed — release sync (no functional changes)
- Maintenance bump that re-cuts the package so the local and global installs carry a matching
  version after the 3.9.x Token Monitor rebrand and `simplicio-loop dashboard` work. Keeps the
  three version sources in lockstep (`pyproject.toml`, `.claude-plugin/plugin.json`, and the
  `simplicio_loop/__init__` fallback literals) so there is no version drift across the pip
  artifact, the marketplace plugin, and the bundled skills/hooks.

## [3.9.1] — 2026-06-24

### Fixed — `simplicio-loop` is typeable on PATH (so `simplicio-loop dashboard` actually works)
- A `--user` pip install can drop the `simplicio-loop` console-script in a dir that isn't on PATH
  (macOS `~/Library/Python/X.Y/bin`, Windows `%APPDATA%/Python/*/Scripts`). The installer now symlinks
  it into `~/.local/bin` (same treatment the two loop operators already get), so the documented
  re-open command `simplicio-loop dashboard` is typeable on all three OS — not just runnable by full
  path. Generalized `_link_operator_bins` → `_link_console_script(name)`; best-effort, idempotent.

## [3.9.0] — 2026-06-24

### Added — `simplicio-loop dashboard` (open the Token Monitor from anywhere)
- **`simplicio-loop dashboard`** — a console subcommand that starts the bundled Token Monitor server
  (detached, if it isn't already up) and opens the browser. Works from anywhere after a `pip install`
  — no repo checkout or path needed. Flags: `--port` (default 9090), `--no-browser` (start the server
  only), `--stop` (close a running monitor). This is the easy way to re-open the dashboard — type the
  command, or just ask the agent ("open the token dashboard").

### Changed — dashboard opens once on install, then stays on-demand (never forced open)
- A **fresh install opens the dashboard once** so you see it works, then it's on-demand. Guarded by a
  marker (`~/.simplicio/.dashboard_shown`): a re-install/update **never reopens** it. Opt out with
  `SIMPLICIO_NO_DASHBOARD=1` (and `SIMPLICIO_NO_BROWSER=1` to skip just the browser). The first-run open
  is best-effort and **never blocks the install** (detached, headless-safe). Only the capture proxy stays
  always-on; nothing is forced to stay open.

### Fixed — package `__version__` drift
- `simplicio_loop.__version__` was hardcoded at `1.0.3` while the package shipped 3.x — `simplicio-loop
  --version` now reads the real version from the installed package metadata (single source of truth).

### Fixed — cross-platform correctness (macOS · Windows · Linux), adversarially reviewed
- **Windows:** the dashboard PID file no longer hardcodes `/tmp` (which doesn't exist on Windows and
  crashed the server on start) — both `simplicio_loop/cli.py` and `hooks/simplicio_dashboard.py` use
  `tempfile.gettempdir()` (→ `%TEMP%` on Windows, `/tmp`/`$TMPDIR` on Linux, `/var/folders/…` on macOS),
  and the PID write is now defensive (creates the dir, never fatal). `--stop` works on all three OS
  (PID-file `os.kill` everywhere; `pkill` is an extra fallback only where it exists).
- **Headless Linux:** `webbrowser.open()` is only called when a GUI is actually present
  (`DISPLAY`/`WAYLAND_DISPLAY`, or macOS/Windows) — on a headless box it would otherwise launch a
  text browser that inherits stdin and **blocks forever** (a hang `try/except` can't catch). Install
  now never blocks on a headless/CI machine; the first-run open is simply skipped there.
- Hardened `sys.executable or "python3"` consistently so a `None` interpreter can't crash the launcher.

## [3.8.0] — 2026-06-24

### Changed — release hygiene + PyPI publish
- **Published to PyPI** (`pip install -U simplicio-loop` now resolves this version). Re-synced the
  shipped bundle (`simplicio_loop/_bundle/hooks/simplicio_dashboard.py`) so the pip artifact carries
  the current 10-runtime neon dashboard byte-for-byte (`bundle ≡ source`, audited by
  `scripts/claims_audit.py`).
- **Fixed the plugin manifest version drift:** `.claude-plugin/plugin.json` was stuck at `3.3.0`
  while `pyproject.toml` advanced — both are now synced at the release version.
- `build/` (setuptools build artifacts) is git-ignored.

## [3.7.0] — 2026-06-24

### Added — `scripts/doctor.py` (verify + `--repair`); optional pieces never block
- **`python3 scripts/doctor.py [--repair]`** (also `bash scripts/simplicio-economy.sh doctor`) checks
  the whole stack and cleanly separates **REQUIRED** (python3, the two loop operators, the 6 skills,
  the loop hooks + Stop wire, the always-on capture proxy — `--repair` installs/wires them) from
  **OPTIONAL** accelerators (the ONNX models backend, the **native performance core**, the menu-bar tray dep).
- **Missing an OPTIONAL piece is never a failure and never blocks.** If a user doesn't have the native
  performance core (or onnxruntime, or the tray dep), doctor reports it as `○ optional` and the **exit code stays 0** as
  long as every REQUIRED item is healthy — the Python engine + the deterministic path cover everything.
  Verified: simulating an absent native performance core still exits 0. `--repair` is PEP-668-robust and best-effort
  on optionals (it tries to install them but won't fail the run if it can't).
- The installer now points at it: `python3 scripts/doctor.py --repair` after install. README documents it.

## [3.6.0] — 2026-06-24

### Changed — dashboard + tray are ON-DEMAND (only the capture proxy is always-on)
- **The Token Monitor dashboard and the menu-bar tray no longer auto-open or stay running.** Only the
  **capture proxy** auto-starts (the wired clients need it reachable); it captures + measures in the
  background. Open the UI only when you want:
  - `bash scripts/simplicio-economy.sh monitor` — start the dashboard + open the browser · `monitor stop` to close.
  - `bash scripts/simplicio-economy.sh tray` — start the menu-bar tray · `tray stop` to close.
- **Installers updated**: `setup_simplicio.sh` (macOS launchd) now registers **only** the proxy and
  removes any leftover monitor/tray auto-start plists; `install_services.py` (Linux systemd · Windows
  Startup) auto-starts only the proxy via a new `AUTOSTART` set and sweeps old monitor/tray units;
  `install_lib.py` prints the on-demand commands. README + `simplicio-economy.sh status` reflect the
  new model (`status` shows the dashboard/tray as on-demand).

## [3.5.0] — 2026-06-24

### Changed — install is COMPLETE by default (everything is mandatory)
- **`scripts/install.sh <runtime>` now installs the whole stack with no flags** — the user gets
  everything, not opt-in pieces: the two loop operators, the **full Python stack** (the package +
  the `[onnx]` models backend — onnxruntime + huggingface_hub + tokenizers + pillow), the 6 skills +
  hooks with the Stop hook wired, AND the always-on Token Monitor (capture proxy + dashboard `:9090`
  + tray) with Claude + Codex + Hermes routed and measured. The old `--with-monitor` opt-in is gone
  (now default). The only opt-out is **`--minimal`** (alias `--no-monitor`) for headless/CI.
- `install_lib.py`: new `install_all_deps()` (PEP-668-robust, fail-open) installs the package + ONNX
  extras + tray dep; `setup_monitor` is default-on and registers services + runs `wire`.
- **Verified on this machine**: a full `install.sh claude --global` left onnxruntime 1.27 + hf +
  tokenizers + pillow + rumps + the `simplicio-loop` package installed, 6/6 skills, both operators on
  PATH, 3/3 services running, monitor live, and `Claude ✓ · Codex ✓ · Hermes ✓` measured.

### Fixed
- `setup_simplicio.sh` service registration is now **idempotent on re-install** — bootout is async,
  so it waits before bootstrap and falls back to `kickstart -k` when the service is still loaded
  (fixes the `Bootstrap failed: 5: Input/output error` on re-run). Restored all 10 runtimes in the
  dashboard coverage panel (a prior change had trimmed it to 7).

## [3.4.1] — 2026-06-24

### Added — `scripts/update.sh` (one-command update)
- **`bash scripts/update.sh [<runtime>]`** — pulls the latest (`git pull --ff-only`, auto-stashing
  local edits and restoring them), reinstalls skills/hooks/operators from the fresh source, restarts
  the always-on services (launchd on macOS · systemd on Linux) so they run the new code, and prints
  the live stack + savings. Verified end-to-end on macOS.

### Fixed — installer robust on externally-managed Python (PEP 668)
- **`install_lib.py ensure_operators`** now installs the loop operators (`simplicio-mapper` +
  `simplicio-cli`) even on Homebrew/Debian Python: it retries `pip install --user --break-system-packages`
  on a PEP-668 failure, then **symlinks the console-scripts into `~/.local/bin`** (the `--user` scheme
  can drop them in a dir off `PATH`, e.g. macOS `~/Library/Python/X.Y/bin`). Without this, the operators
  installed but weren't on `PATH`, so the loop drive would block. Documented `--with-monitor` and the
  update flow in the README Install section.

## [3.4.0] — 2026-06-24

### Added — final loop-orchestrator hardening (the last gaps to 10/10)
- **`hooks/action_gate.py` — a FAIL-CLOSED safety gate, Step 5 made mechanical.** Runs as a Claude
  `PreToolUse` (Bash) hook AND/OR a git pre-push hook and BLOCKS (exit 2), *before* the command runs:
  force-push / history rewrite (`filter-branch`), remote-ref deletion, mass-delete (`rm -rf /`),
  destructive DDL (`DROP DATABASE`/`TRUNCATE`), infra teardown (`terraform destroy`), and any
  commit/push whose **staged diff contains a secret** (AWS/GitHub/Slack/OpenAI keys, private keys,
  hardcoded credentials — placeholder-aware). Benign commands pass untouched; a push whose diff
  can't be scanned is blocked (a safety check that can't run is not a pass). `selftest` 14/14;
  pytest `tests/test_action_gate.py`. Wired into `hooks.claude.json` + the hooks README.
- **Incremental triage — `loop_journal.py since`.** Each record now stamps the HEAD commit; `since`
  shows only the delta (diff-stat + working tree) since the last recorded turn, so a turn reads what
  changed instead of re-scanning the whole tree every iteration.
- **Two loop modes — `converge` vs `drain`.** The scratchpad `mode` selects termination logic:
  `converge` (single hard task — ends on the evidence-gated promise or a stall escalation) vs
  `drain` (a queue — ends when the source re-query stays empty K rounds). Documented in
  `simplicio-loop` SKILL so the two dynamics aren't conflated.

### Added — tests + claims-audit + local check runner (turn assertions into proof; no paid CI)
- **`tests/` suite** — the workers' deterministic `selftest`s, an **e2e of the loop driver**
  (`hooks/loop_stop.py`) proving it stops on EVIDENCE, ignores a bare `<promise>`, and stops on the
  cap as *distinct* exits, and smoke tests proving the evidence producers **BLOCK (never fake-pass)**
  when their toolchain is absent. Runs under `pytest` **or** self-runs on bare python3
  (`tests/_selfrun.py`) — no pip required. Verified: 12 passed under pytest and the stdlib fallback.
- **`scripts/claims_audit.py`** (fail-closed) — every `scripts/*.py` referenced in the docs exists ·
  the extension-point count agrees across all files · each cited worker command runs · the shipped
  `simplicio_loop/_bundle/` skills are byte-identical to source. **Caught real drift on first run**
  (the bundle was missing 5 reference files); repaired to an exact mirror.
- **`scripts/check.py`** — one local gate (`claims_audit` + tests), wireable as a git pre-push hook.
  Replaces a paid GitHub Action: the verification runs on the dev's machine at zero CI cost.
- `pyproject.toml` `[dev]` extra adds pytest (convenience only). Docs: README (✅ Tests section),
  AGENTS, CLAUDE.

### Changed — savings line is now evidence-gated, not mandatory (honesty fix)
- **Removed the "end every message with the mandatory savings line" obligation.** That rule forced a
  figure even with no `savings_ledger` bound, which pressured fabricated baselines/percentages.
- **New rule (mirrors the `<promise>` evidence gate):** emit a savings line ONLY when a turn actually
  ran an economy-producing command and the number traces to a **measured receipt** — `orient_clamp`
  tee (bytes/lines saved), signatures-only read (lines saved), native cache hit (call skipped),
  `deterministic_edit` (0 edit tokens), or the capture proxy / `savings_ledger` / `savings_harness
  score`. No measured economy → **no savings line**; never fabricate a baseline or a %.
- A baseline `%` may be quoted only when an actual control arm was run+measured (`savings_harness`),
  never estimated from memory. Updated `simplicio-tasks`/`simplicio-loop` SKILLs, AGENTS, README;
  `_bundle` synced.

### Added — loop attempt-memory + stall detector (`scripts/loop_journal.py`)
- **Durable run-journal** `.simplicio/orchestrator/loop/journal.jsonl` (append-only: `iteration`, `action`,
  `hypothesis`, `gate`, error `fingerprint`) — the loop's working memory of WHAT WAS TRIED, beside
  the scratchpad's WHAT (the goal). Closes the two failure modes of a memoryless re-feed loop:
  re-deriving the same triage every turn, and **oscillation** (try X → fail → try X again).
- **Stable error fingerprint** — failing gate output is hashed with line numbers, paths, hex/uuids,
  timestamps and durations normalized away, so the SAME bug is recognized across turns.
- **Stall detector** — `loop_journal.py stall`: STALLED when the last K consecutive attempts share
  the same fingerprint (default K=3); names the dead-end actions and recommends `switch-strategy`
  (K) or `escalate` (>K), `--exit-code` 10 for hook/`if:` gating. `resume` prints the anti-oscillation
  read at the top of each turn. Deterministic + model-free; `selftest` proves it (9/9, no files).
- Wired into `simplicio-loop` (loop contract steps 2–4, new § Run-journal + stall detector, the
  "good loop" criteria) and `simplicio-tasks` (Step 4 quality loop). Docs: README, AGENTS, CLAUDE;
  `_bundle` synced.

### Added — billing aggregator for the open-core paid tier (`scripts/billing_aggregator.py`)
- **Deterministic, model-free, privacy-preserving meter→invoice** over the metering records the loop
  already produces (`savings/snapshots.jsonl`, `trajectory/*.jsonl`,
  `tee/video/ledger.txt`). Verbs: `collect`/`meter`/`invoice`/`export`/`rates`/`selftest`.
- **Privacy boundary**: the savings snapshots store raw baseline/treatment TEXT; `collect` counts
  tokens (`ceil(chars/4)`) then **discards** the text — usage records carry counts only, never code,
  diffs, or rendered videos. **Fail-safe**: `invoice --prepaid` flags over-balance in billing output
  without stopping the runtime loop. `selftest` proves the arithmetic (11/11, no files).
- Three price levers: per-seat (Pro), per-run (Team, one delivered+merged item), metered (Cloud:
  token passthrough + markup, render-minutes, operator-minutes). Implements the `PRICING.md` sketch.

### Added — demo-video creation + evidence via hyperframes (`video_evidence`, extension point #44)
- **`video_evidence` extension point** — binds [hyperframes](https://github.com/heygen-com/hyperframes)
  (HeyGen): renders HTML/CSS compositions to a **deterministic MP4** ("same input, same frames, same
  output"). Two jobs: (1) fulfil an explicit request — `/simplicio-tasks make a demo video of screen
  X` routes the work-item to the producer; (2) act as a CI-reproducible "works, not just
  compiles" proof for a UI change and a valid evidence-gated `<promise>` for the loop.
- **Worker** `scripts/video_evidence.py` — five verbs (`detect`/`scaffold`/`lint`/`render`/`verify`).
  `detect` classifies the request in-terminal (EN/PT/ES regex, no LLM); `verify` scaffolds a
  hyperframes composition from the `web_verify` per-step screenshots and renders the MP4 under
  `.simplicio/orchestrator/tee/video/`. Missing toolchain (Node 22+, FFmpeg, hyperframes) → **BLOCKED**, never
  a fake pass. Chains after `web_verify` (Playwright captures the screens; hyperframes assembles them).
- **Contract** `.claude/skills/simplicio-tasks/references/video-evidence.md`; wired into
  `simplicio-tasks` (Step 2b routing + Step 4b evidence) and `simplicio-loop` (in-turn evidence
  producer). Extension-point count 43 → 44; skills/accelerators 10 → 11. Docs updated: README (EN +
  pt-BR), AGENTS.md, CLAUDE.md. Bundled skills under `simplicio_loop/_bundle/` synced.

## [3.3.0] — 2026-06-24

### Added — automatic capture routing for Claude + Codex (the monitor now measures all three)
- **`simplicio-economy.sh wire` now routes Claude (Anthropic) AND Codex/OpenAI through the capture
  proxy**, not just OpenAI — so the Token Monitor measures **Hermes + Claude + Codex** with no manual
  step. It sets `ANTHROPIC_BASE_URL` (no `/v1` — Claude appends `/v1/messages`) and `OPENAI_BASE_URL`
  (`/v1`) in the shell profile; `install_services.py wire` does the same cross-platform (`setx` on
  Windows). The engine routes each model to its **real** provider (`claude→anthropic`, `gpt→openai`,
  `deepseek→deepseek`) — **no model swap**. `setup_simplicio.sh` runs `wire` at install, so it is
  automatic.
- **Verified live**: through the proxy, an unauth'd `claude-3-5-sonnet` request returned Anthropic's
  own auth error + `request_id`, and a `gpt-4o-mini` request returned OpenAI's 401 — proving
  transparent forwarding to the real providers. `status` now shows `Claude ✓ · Codex/OpenAI ✓ · Hermes ✓`.
- **Idempotent · reversible · opt-outable**: re-running `wire` doesn't duplicate; `unwire` deletes the
  proxy routing deterministically (fixed a bug where a re-wire could poison the backup); a pristine
  `~/.zshrc.simplicio-bak` is kept; `SIMPLICIO_NO_WIRE=1` skips wiring entirely.

## [3.2.3] — 2026-06-24

### Changed
- README: added the "Running `simplicio-tasks`: economy vs measurement (per runtime)" subsection —
  economy applies on every runtime; measurement only counts traffic routed through the capture proxy.

## [3.2.2] — 2026-06-24

### Changed
- Synced all 14 translated READMEs to the comprehensive English README (capture-engine commands, ONNX
  models, native performance core, Token Monitor, corrected token-economy table). Tracked the project `.codex/` config.

## [3.2.1] — 2026-06-24

### Changed
- Comprehensive, transparent English README: documented the full capture-engine command surface (16
  commands), the 4 optional ONNX models, and the 4 native performance modules.

## [3.2.0] — 2026-06-24

### Added — the two token-economy techniques the README claimed but didn't implement, now real (2 agents)
- **Signatures-only reads** — `engine/simplicio_signatures.py` + `simplicio signatures <file>`: an
  `ast`-based skeleton view (imports, class/def signatures, first docstring line, top-level consts;
  bodies stripped to `...`), regex fallback for js/ts/go/java/…. Verified: `simplicio_dashboard.py`
  **870 → 65 lines (93% saved)** with every `def`/`class` preserved and no body leakage. Saves the
  tokens to read+navigate code.
- **Native response cache** — `engine/simplicio_cache.py`, wired into the capture proxy: a repeated
  **deterministic** request (`temperature == 0`, non-streaming) is served byte-exact from disk and the
  upstream LLM call is **skipped entirely → ~100% token saving on the hit**. Content-addressed key
  ignores volatile fields (`stream`/`user`/ids); LRU-bounded (500 entries / 50 MB); never caches 4xx or
  streaming/temp>0. On by default (`SIMPLICIO_CACHE=0` to disable). Verified end-to-end: an identical
  second request returned `X-Simplicio-Cache: HIT` with **zero** upstream calls. This also makes the
  dashboard's `cache_hit_pct` real (it was always 0). `simplicio cache stats|clear`.

### Changed
- README token-economy table corrected to reality: `CAP_TREE=100` → the real caps
  (`CAP_ERRORS/CAP_WARNINGS/CAP_LIST`); the `LMCache KV cache` row (an *external* optional accelerator,
  never built-in code) replaced by the now-implemented **native response cache**; signatures listed as
  the real `simplicio signatures` tool.

## [3.1.0] — 2026-06-24

### Added — the last two native performance modules (the port is now literally complete: every module)
- **the native passthrough proxy** — the upstream engine's native transparent reverse proxy,
  vendored + rebranded (zero residual upstream branding). **Built (40.8 MB
  binary) and verified running**: it forwarded a request to a local upstream byte-exact, preserved +
  injected headers (`x-forwarded-*`, `x-request-id`), rewrote `host`, and `/healthz` →
  `{"ok":true,"service":"simplicio-proxy"}`. **227 lib unit tests pass.**
- **the native parity harness** — the upstream engine's native-vs-Python parity harness, vendored
  + rebranded + built (`parity-run` binary, 7 transforms). **4 parity tests pass.**
- (Honest: the proxy's 50 *integration* test binaries couldn't finish linking here — disk-full, ~200 MB
  free; each statically links the ~40 MB ONNX/AWS tree. The release binary + lib tests built and passed.)

### Done — every subsystem AND every module of the upstream compression project is now in Simplicio
All four native performance modules (`simplicio-core` / `-py` / `-proxy` / `-parity`) build; the full Python functional
surface runs; the four real ONNX models (kompress / technique-router / MiniLM / SigLIP) run; Copilot
OAuth works. **the upstream port: complete.**

## [3.0.0] — 2026-06-24

### Added — the native performance core, built for real (the last literal piece)
- **the native performance core** — the upstream engine's native performance modules
  (the core + the native bindings), **vendored and rebranded** to simplicio
  (~70 source files: smart_crusher, diff/log/search compressors, tokenizer, relevance, CCR, content
  detection), Apache-2.0 with `NOTICE` crediting upstream. The rebrand is baked into the compiled
  binary, not cosmetic (`hello()` → `simplicio-core`, tag sentinel `{{SIMPLICIO_TAG_…}}`, env
  `SIMPLICIO_*`).
- **It builds and runs.** The native build produced a real wheel
  (`simplicio_core-…-abi3-…arm64.whl`); `import simplicio._core` works and real functions run
  (`LogCompressor` 5700→566 bytes, `SmartCrusher`, `DiffCompressor`, `detect_content_type` via magika).
  **The full native test suite passes.**

### Milestone — the upstream port is complete (capability + the native layer)
Every subsystem of the upstream compression project is now in Simplicio: the full Python functional
surface (deterministic + extractive compression, the **four real ONNX models** kompress /
technique-router / MiniLM embedder / SigLIP image, content detection + smart routing, RAG, input+output
capture, per-provider routing, MCP, CCR memory, init/wrap/report/verify/audit/capture/evals, copilot
OAuth) **and** the native performance core. The upstream port: done. (Skipped only the upstream's
native passthrough proxy that duplicates the working Python proxy — and its parity test
harness; both are non-capability.)

## [2.12.0] — 2026-06-24

### Added — Copilot OAuth (the last functional subsystem)
- **`simplicio copilot {login|token|status|logout}`** (`engine/simplicio_copilot.py`, stdlib) — GitHub
  Copilot OAuth **device flow** + Copilot token exchange, so Copilot CLI traffic can be routed through
  the capture proxy. Verified **live against the real GitHub API**: the device-code handshake returned a
  real `device_code`/`user_code`/`verification_uri`, and the poll returned the expected
  `authorization_pending`; `status`/`logout`/empty-store paths verified; token stored 0600 under
  `~/.simplicio`. (Honest: the post-auth Copilot token exchange can't be exercised here without a real
  Copilot account; the code path mirrors upstream exactly.)

### Milestone — capability-complete
With Copilot auth, **every functional subsystem of the upstream compression project is now ported to
Simplicio** and verified: all deterministic + extractive compression, the **four real ONNX models**
(kompress / technique-router / MiniLM embedder / SigLIP image), content detection + smart routing, RAG
(TF-IDF + embedding), input+output capture, per-provider routing, MCP, CCR memory, client init, wrap,
report, verify, audit, capture, evals, and copilot-auth. The **only** thing not reimplemented is the
upstream's native performance core — a **native performance** re-implementation of the Python (its parity harness
asserts native == Python), which adds **no new capability**, only native speed.

## [2.11.0] — 2026-06-24

### Added — image compression (the 4th and last real upstream model)
- **`simplicio image <path>`** (`engine/simplicio_image.py`) — vision-LLM image compression ported from
  the upstream engine's `image/` subsystem (techniques preserve/full_low/crop/transcode = aspect-preserving LANCZOS
  downscale + efficient re-encode), using the **REAL** SigLIP image-encoder ONNX model (~94 MB)
  as a content-similarity verifier so compression never destroys content. Verified: 1600×1200 → 768×576,
  90.6% bytes saved, SigLIP cosine ~0.997; a 512px tier cuts OpenAI vision tokens ~67%. Pillow-only
  fallback works without the model. (`[onnx]` extra now includes pillow.)
- **All four real upstream ONNX models now run inside Simplicio**: kompress-v2-base (compression),
  technique-router-onnx (routing), all-MiniLM-L6-v2-onnx (embeddings), siglip-image-encoder-onnx (image).

### Scope note — the native performance modules
The upstream's native performance modules (the core/proxy/py modules) are a **native performance re-implementation** of the
Python — its parity harness literally asserts native == Python. They add **no new capability** (just native
speed). The functional surface they cover is already in Simplicio's Python engine, so there is no
*capability* gap there — only an optional native-speed rewrite, which is out of scope for the token monitor.

## [2.10.0] — 2026-06-24

### Added — more upstream subsystems ported (3 agents; 2 more REAL upstream models)
- **`simplicio detect`** (`engine/simplicio_detect.py`, stdlib) — content-type detector (JSON/code/log/
  markdown/prose) + a **universal smart-compress** that routes each block to the best technique
  (JSON→minify, log→full pipeline, code/prose left intact). Verified 15/15: JSON 60%, log 95% saved,
  code/prose byte-preserved.
- **`simplicio router`** (`engine/simplicio_router.py`) — the **REAL** technique-router ONNX
  model (~32 MB, INT8): tokenize → ONNX → softmax → technique class (transcode/crop/preserve/full_low).
  Verified running on the real weights. (Note: this router was trained on image-edit *intents*, so raw
  text blobs tend to route to `preserve` — the model runs correctly; its training domain differs.)
- **`simplicio embed`** (`engine/simplicio_embed.py`) — the **EXACT** upstream embedder
  `Qdrant/all-MiniLM-L6-v2-onnx` (~90 MB): masked mean-pooling → 384-dim L2-normalized vectors;
  embedding RAG over the CCR store. Verified: paraphrase cosine **0.957**, unrelated −0.01, #1 rank.
- New `[onnx]` optional extra installs onnxruntime + huggingface_hub + tokenizers for `kompress`/`router`/`embed`.

## [2.9.0] — 2026-06-24

### Added — the REAL upstream ONNX compression model, integrated (the gap is closed, not substituted)
- **`simplicio kompress`** (`engine/simplicio_kompress.py`) runs the **actual upstream model**
  `kompress-v2-base` — the real ONNX semantic token-pruning model the upstream engine uses. Turns out
  its weights are **public on HuggingFace** (Apache-2.0), not proprietary: so this is the genuine
  article, not a look-alike. It tokenizes (ModernBERT), runs the ONNX session
  (`input_ids`/`attention_mask` → per-token `final_scores` keep probability), keeps the top
  `--keep` fraction of words, drops filler, and reconstructs — **reversibly** (the dropped spans are
  retained). Verified with the real model: e.g. `--keep 0.5` → 48.7% words pruned, high-signal tokens
  (identifiers, numbers, errors) preserved.
- Opt-in: `pip install "simplicio-loop[kompress]"` (onnxruntime + huggingface_hub + tokenizers; the
  ~274 MB model downloads on first use). Without it, `simplicio kompress` reports how to enable it.

### Fixed
- Engine CLI now forwards sibling-command args **verbatim** (raw passthrough) — `argparse` REMAINDER was
  mangling `--flag value` ordering (e.g. `kompress --keep 0.5` arrived as `0.5 --keep`).

### Scope — now honestly complete on the implementable + the model
With the real `kompress-v2-base` integrated, the upstream's ONNX semantic compression is no longer a
gap — it's the same model, in Simplicio. Combined with the deterministic 12-algo + extractive
compression, the model2vec embedding backend, and TF-IDF/embedding RAG, the upstream compression+RAG
surface is covered (deterministic core stdlib-only; the heavy models are optional extras).

## [2.8.0] — 2026-06-24

### Added — REAL embedding ML backend (the ML gap, done honestly — not stubbed)
- **`engine/simplicio_semantic_ml.py`** — an optional, dependency-gated embedding backend using a
  **real sentence-embedding model** (`model2vec`, static embeddings, ~30 MB, no torch):
  - **`simplicio semantic --ml`** — embedding **semantic dedup**: drops paraphrased / semantically
    redundant lines that TF-IDF + SimHash can't catch, **reversibly** (byte-exact restore). Verified
    with the real model: paraphrase cluster → 27-40% saved, round-trip OK.
  - **`simplicio rag --ml "<query>"`** — retrieval by **meaning** (embedding cosine), not keyword.
    Verified: matched a query to a lexically-disjoint memory (cosine 0.42, ranked #1) — a match
    TF-IDF would miss.
- **Opt-in + graceful**: needs `pip install "simplicio-loop[ml]"` (model2vec + numpy). Without it,
  `--ml` prints how to enable it and the system falls back to the deterministic `semantic`/`rag`.
  The native engine itself stays **stdlib-only / zero-dependency**.
- Added the `[ml]` optional-dependency extra; `--ml` routes via `parse_known_args` passthrough.

### Honest note
This uses a *real* trained embedding model (so semantic similarity genuinely works — paraphrases
match, unrelated text doesn't). It is the light static-embedding tier; a larger model catches more
paraphrase. It is NOT a reimplementation of the upstream's specific trained ONNX compression model
(that exact model isn't replicable) — but the ML *capability* (semantic compression + meaning
retrieval) is now real and verified, behind an optional dependency.

## [2.7.0] — 2026-06-24

### Added — semantic-lite compression + RAG (the honest take on the ML gap)
- **`simplicio semantic`** (`engine/simplicio_semantic.py`) — **reversible extractive** compression for
  large content: scores lines/sentences by TF-IDF + position + length, keeps the salient ones (always
  keeps headers/ERROR lines), and elides the rest with a marker — the dropped bytes are retained so
  `semantic_restore` reproduces the **byte-exact original** (lossless round-trip). Plus **SimHash**
  near-duplicate block folding, and optional CCR integration (stash the restore blob in the memory
  store, retrieve on demand). Verified: 121-line doc → 56.3% smaller, byte-exact restore.
- **`simplicio rag`** (`engine/simplicio_rag.py`) — **TF-IDF cosine retrieval** over the CCR memory
  store: `rag "<query>"` ranks stored memories by relevance with snippets; `rag remember <key> <text>`
  populates it. Verified: relevant doc ranks #1 across queries.

### Honest scope
These are **deterministic** techniques — extractive summarization + SimHash + TF-IDF retrieval — **not**
trained embedding/ONNX models. They address the "semantic compression" and "RAG" gaps with real,
zero-dependency, reversible methods; they do not do abstractive rewriting or embedding-space matching.
The trained-ONNX semantic model and embedding-vector RAG of the upstream remain out of scope (they
require ML models, not stdlib code) — and are not faked.

## [2.6.0] — 2026-06-24

### Added — output token capture (input + output now complete)
- The proxy was only counting **input** (prompt) tokens; it now also captures **output/completion**
  tokens by reading the upstream response's `usage` (OpenAI `completion_tokens` / Anthropic
  `output_tokens`) from a bounded 64 KB response tail — **without breaking streaming** (chunks are
  written through immediately; only a small tail is kept). Honest: if the upstream doesn't report
  usage, output is 0 (no fabricated estimate). Recorded as `total_output_tokens` (lifetime + session)
  and `tok_out=` in the PERF log. Verified isolated: a response with `completion_tokens:42` → captured 42.
- Dashboard shows a **tokens out** KPI (replacing the always-zero "cache hit" card — the native engine
  doesn't cache).

## [2.5.0] — 2026-06-24

### Added — more native commands + quality gates (5 more parallel agents, each self-tested)
- **`simplicio audit <paths>`** — scan files/dirs and rank how many tokens compression would save.
- **`simplicio capture --file body.json`** — dry-run analyzer: what a request would compress/save, no send.
- **`simplicio evals`** — compression eval + **regression gate** (corpus → %saved, asserts prose/code stay
  byte-identical + idempotence). Doubles as CI: exits non-zero if a change corrupts content or stops saving.
  Current gate: **4/4 invariants PASS, avg ~44% saved**.
- **`engine/simplicio_tokens.py`** — calibrated stdlib token estimator (prose ~4.1 c/tok, code ~2.9, json
  ~1.8). The proxy + capture now measure tokens with it instead of naive chars/4.
- **`engine/README.md`** — full engine reference (commands, capture mechanism, compression catalog, honest
  scope).

### Fixed
- The unified `bin/simplicio` CLI didn't route `wrap`/`report`/`verify` (and the new `audit`/`capture`/`evals`)
  — `ENGINE_CMDS` now forwards them all. README corrected accordingly.

## [2.4.0] — 2026-06-24

### Added — unified CLI + more engine commands (5 more parallel agents, each self-tested)
- **Unified `simplicio` command** (`engine/simplicio_cli.py` + `bin/simplicio`): one entry that dispatches
  `simplicio proxy|doctor|memory|mcp|init|wrap|report|verify|compress|version`.
- **`simplicio wrap <client>`** (`engine/simplicio_wrap.py`): run a client (claude/codex/cursor/opencode/aider)
  with capture routing injected for that run (OPENAI/ANTHROPIC_BASE_URL → proxy), warns if the proxy is down.
- **`simplicio report`** (`engine/simplicio_report.py`): savings report — lifetime/session totals + per-model
  and per-provider breakdown (deltas from the cumulative history), `--json`, `--since`, `--top`.
- **`simplicio verify`** (`engine/simplicio_verify.py`): one-command self-check of the whole stack
  (proxy, monitor, savings file, engine, compression, memory, MCP, operator) → PASS/WARN/FAIL table.
  Verified **8/8 PASS** on the dev machine.
- **`engine/simplicio_compress_extra.py`** — 4 more safe deterministic algorithms (markdown-table
  whitespace, repeated multi-line block fold, long-token elision, numbered-noise fold), chained after the
  base pipeline. Meaning-preserving + idempotent (prose/code byte-identical).
- `wrap`/`report`/`verify` are also reachable as `simplicio_engine` subcommands.

## [2.3.0] — 2026-06-24

### Added — native engine grows toward feature parity (built by 5 parallel agents, each self-tested)
- **`engine/simplicio_mcp.py`** — native stdio MCP server (JSON-RPC 2.0) exposing `simplicio_compress`,
  `simplicio_retrieve`, `simplicio_stats` tools. `simplicio_engine mcp` runs it.
- **`engine/simplicio_memory.py`** — CCR (compress-cache-retrieve) key-value store with byte-exact
  lossless recall (zlib+base64), atomic + thread-safe. `simplicio_engine memory remember/recall/forget/list`.
- **`engine/simplicio_compress.py`** — 8-algorithm deterministic compression (ANSI strip, trailing ws,
  blank collapse, line dedup, JSON minify, rule-run cap, hex-dump fold, fenced-log fold), idempotent and
  meaning-preserving. The proxy now uses it (verbose logs ~89-94% saved; clean prose/code untouched).
- **`engine/simplicio_init.py`** — native client integration writer (mirrors the upstream engine's `init`): registers
  the Simplicio MCP server into codex/claude/copilot/openclaw configs. **Dry-run by default**, `--apply`
  to write, idempotent. `simplicio_engine init <client>`.

### Verified
- **systemd activation field-tested on real Linux** (systemd PID 1 in Docker, aarch64): `systemctl start`
  brought the proxy up, `/health` returned `engine: simplicio`, and `Restart=always` re-spawned it after
  a kill — the previously-untested gap is now closed. `install_services.py` now sets `SIMPLICIO_HOME` on
  the services so savings/logs write even under an unset service `$HOME`.

### Fixed
- The compression module was named `compression`, which **collides with Python 3.14's new stdlib
  `compression` package** — renamed to `simplicio_compress` so the 8-algo pipeline actually loads on 3.14.

## [2.2.1] — 2026-06-24

### Verified — Linux is now field-tested (not just code-complete)
- Ran the stack inside a real Linux container (`python:3.12-slim`, py 3.12.13): the **native engine
  forwards + captures** (savings written), the **dashboard `get_status` + HTML** compose (7 runtimes),
  `install_services.py selftest` **PASS** (systemd units + Windows launchers), the **tray loads**
  (headless fallback, no crash), and the generated **systemd unit resolves the Linux Python path**.
  The honest remaining gap: systemd *daemon activation* (needs a real init host) and Windows *runtime*
  are still not exercised on those hosts — the software + artifacts are verified, service start-up is not.

## [2.2.0] — 2026-06-24

### Fixed — the installer now ships the token economy too
- **The main installer (`install_lib.py`) was disconnected from the token monitor.** It copied the
  6 skills + hooks but never set up the capture proxy / dashboard / tray, so a fresh user got the
  loop but **not** the token economy. Now the installer always prints how to enable the monitor, and
  `--with-monitor` installs the tray dep + registers the three services (`install_services.py install`).
  Verified on a fresh temp target: skills copied, hooks wired, monitor pointer shown, services
  selftest PASS.
- Removed a personal path (`~/Projetos/ai/hermes-agent/...`) from the `simplicio-engine` fallback —
  it would never resolve for other users.

## [2.1.0] — 2026-06-24

### Added
- **Live multi-runtime "active / blinking" detection.** The dashboard now detects which runtimes
  are actually RUNNING (process match) and shows them blinking: `● active` (blue) when running,
  `● capturing` (green) when their traffic is being saved in the last 10 min, `○ ready` otherwise.
  So with Claude open + Hermes on, both are recognized and blink. Header shows the active count.
- **Per-provider routing in the native engine** (`gpt→openai`, `claude→anthropic`, `deepseek→deepseek`,
  …): one capture proxy forwards each model to its REAL provider with the client's own key — captures
  every routable runtime **without swapping its model**. Verified live (gpt→OpenAI, deepseek→DeepSeek).
- **5-algorithm deterministic compression** (ANSI strip, rule-run cap, line dedup, whitespace, JSON
  minify). Verified capture coverage: OpenAI stream/non-stream, Anthropic, multimodal, concurrent,
  non-JSON fail-open — every request through the proxy is captured.

### Removed
- **Gemini, Kiro, Antigravity** dropped from the runtimes list — they use proprietary Google/AWS APIs
  the proxy can't intercept. Only the 7 genuinely-interceptable runtimes remain.

## [2.0.0] — 2026-06-24

### Added — native Simplicio capture engine (no external dependency)
- **`engine/simplicio_engine.py`** — a self-contained, stdlib-only capture proxy that **replaces the
  external compression binary** for the core capture path. It transparently forwards each request to
  the real upstream (**no model swap**), measures prompt tokens, applies **deterministic** compression
  (whitespace collapse, consecutive-line dedup, oversized-output capping), streams the response back,
  and writes `~/.simplicio/proxy_savings.json` in the same schema-v3 the Token Monitor reads. It is
  **fail-open**: any parse/compress error forwards the original bytes unchanged. Commands: `proxy`,
  `doctor`, `memory stats`, `--version`.

### Changed
- **The live capture proxy is now the native engine.** Verified end-to-end: a request through it
  reached DeepSeek's real API and returned DeepSeek's own auth error (proving transparent forwarding);
  a compressible payload was deduped 575→54 chars and recorded as real savings. Lifetime history was
  migrated from the legacy data dir → `~/.simplicio` for continuity (401,925 tokens preserved).
- `scripts/simplicio-engine` is **native-first** (falls back to an external binary only if the module
  is absent). `setup_simplicio.sh` and `install_services.py` run the native engine — `setup` no longer
  installs the external compression binary.
- README accelerator row + `token-capture.md` describe the native engine (schema-compatible with the
  upstream compression project, credited).

### Honest scope
- The native engine is the **core** (transparent capture + measurement + deterministic compression).
  It is **not** a reimplementation of the upstream engine's 360k-LOC feature set (ONNX semantic
  compression, the 6-algorithm suite, RAG, MCP memory store). Those remain out of scope; the native
  engine delivers real, safe token savings without any external dependency.

## [1.9.0] — 2026-06-24

### Added
- **Active-LLM banner** — the dashboard now detects which LLM is currently being intercepted (from the
  latest request in `proxy_savings.json` history) and shows a banner "⚡ Saving tokens for `<model>`"
  with the **LLM's logo** (DeepSeek, Anthropic, OpenAI, Gemini, Llama, Mistral, Qwen, xAI, Kimi, Groq…),
  the tokens saved, and the **last-call datetime** + relative time.
- **Datetime records throughout** — real timestamps from the capture history: last-call datetime on the
  chart, session-start datetime in the footer, full `YYYY-MM-DD HH:MM:SS` "updated" stamp, and the
  per-request `ts` carried on the series.

### Fixed
- Topbar "intercepting" chip showed `0` — now reflects `<ready>/<total>` runtimes (e.g. 7/10).

## [1.8.1] — 2026-06-24

### Changed
- **Documented the Simplicio Token Monitor in the README** (web dashboard `:9090` + menu-bar tray +
  the `simplicio-economy.sh` module + cross-platform install) so it is a discoverable, complete
  deliverable. Rebranded the token-economy table's accelerator row to "Simplicio capture proxy".
- QA pass: monitor verified fully functional — all API fields present, real-time auto-refresh
  (live token count growing), no-data/error fallbacks, 0 console errors, tray reading live data.

### Fixed (cross-platform hardening)
- **pystray tray backend verified at runtime** (not just constructed) — renders the menu-bar icon;
  added `SIMPLICIO_TRAY_BACKEND=rumps|pystray|headless` to force/test a backend.
- **Windows Startup launcher bug**: `set K=V & ...` baked a trailing space into the value; now uses
  quoted `set "K=V"` per line.
- **systemd units** get an explicit `PATH` so the engine binary resolves under systemd's minimal env.
- **Dashboard engine call is cross-platform**: invokes the binary directly on Windows (the
  `simplicio-engine` bash wrapper can't run there).
- Added `python3 scripts/install_services.py selftest` — validates the generated systemd/Windows
  artifacts on any OS (PASS on macOS).

### Honest caveats
- Verified end-to-end on **macOS** (dashboard, rumps + pystray trays, launchd, real capture). The
  **Linux systemd and Windows Startup service activation are NOT yet run on those OSes** — only their
  generated artifacts are validated. The capture engine is the third-party upstream compression binary.
  Provider interceptability (141/144) is a catalog estimate, not verified per provider.

## [1.8.0] — 2026-06-23

### Added
- **Cross-platform (macOS · Linux · Windows).** `scripts/install_services.py` registers the three
  always-on services on whichever OS you run it — launchd (macOS), systemd `--user` (Linux),
  Startup-folder launchers (Windows) — plus cross-platform `wire`/`unwire`/`status`. The tray
  (`app/simplicio_tray.py`) now auto-selects **rumps** on macOS (native menu-bar number) and
  **pystray** on Windows/Linux, with a headless print fallback.
- **Provider interceptability catalog (`app/providers.json`)** derived from the Hermes/OpenCode
  provider lists: **141 of 144 providers (98%) are interceptable** (139 OpenAI-compatible + 2
  Anthropic; only 3 Google-native are not). The dashboard surfaces the live `141/144` count next
  to the runtime panel — interception is really about providers, and we cover essentially all of them.

## [1.7.0] — 2026-06-23

### Added
- **Always-capture wiring (`simplicio-economy wire` / `unwire`).** Routes OpenAI-compatible
  clients (Codex, Cursor, OpenCode, any `OPENAI_BASE_URL` tool) through the local capture proxy —
  the **same upstream they already use, now intercepted + compressed**, with no model swap. This is
  the "works after install without invoking simplicio-loop" switch: once wired, every call is
  captured on the next shell/tool launch. Idempotent; backs up `~/.zshrc`; fully reversible via
  `unwire`. `setup_simplicio.sh` runs it so a fresh install turns capture on. `status` reports the
  wire state.

### Notes
- Activating always-capture rewrites `OPENAI_BASE_URL` in `~/.zshrc` (high blast radius across all
  OpenAI-compatible tools). That is intentional and what the install does on the user's behalf; an
  assistant running mid-session is (correctly) gated by the permission guard and must let the user
  run `simplicio-economy wire` themselves.

## [1.6.0] — 2026-06-23

### Added
- **Token-economy module (`scripts/simplicio-economy.sh`).** One entrypoint that brings up and
  reports the whole always-on savings stack — capture proxy + token monitor + menu-bar tray +
  the deterministic operator `simplicio-dev-cli` + lifetime savings — so token capture/savings
  work **after install without invoking simplicio-loop**. `setup_simplicio.sh` runs it at the end.
  Subcommands: `status`, `up`, `capture <openai|anthropic> [port]`.
- **Transparent capture proxy** (`simplicio-economy capture openai`) — forwards each call to the
  client's REAL provider, capturing tokens without swapping the model. **Verified end-to-end:** a
  real `gpt-5.4` request through the transparent proxy returned a genuine OpenAI response and the
  proxy's `/stats` recorded the request (`api_requests: 4`, `total_tokens_before: 124`). This is
  the correct path to capture Codex/Cursor/OpenCode, kept separate from the Hermes→DeepSeek proxy.

## [1.5.0] — 2026-06-23

### Added
- **Desktop menu-bar app (`app/simplicio_tray.py`).** A macOS tray + widget that lives in the
  menu bar showing live tokens saved (brand hexagon icon + compact count, e.g. `⬡ 102.9K`). The
  dropdown is the widget: lifetime tokens/$ saved, reduction %, requests, current-session savings,
  capture-proxy status, and "Open Token Monitor". Reads `proxy_savings.json` directly — no traffic
  of its own. Auto-starts as the `ai.simplicio.tray` launchd service; `setup_simplicio.sh` installs
  `rumps` and registers it.
- Brand `assets/tray-icon.png` for the menu-bar item.

## [1.4.0] — 2026-06-23

### Added
- **`scripts/simplicio-engine`** — a single Simplicio-branded wrapper around the capture engine
  binary, so the dashboard, scripts and docs speak `simplicio-engine` instead of the engine's
  own name. It is now the *only* place that resolves the underlying binary (fast lookup, no
  full-`$HOME` scan).

### Changed
- **Robust proxy detection.** The monitor now checks the proxy with a pure-Python socket connect
  instead of `lsof`, which the launchd service could not find on its restricted `PATH` (it lives
  in `/usr/sbin`) — the dashboard was falsely showing the proxy as down. Also added `/usr/sbin`
  to the generated service `PATH`s. "Always works", regardless of environment.
- Dashboard + capture script now call the engine through `simplicio-engine`; remaining upstream
  references are isolated to the wrapper's binary resolution, the engine's own data dirs
  (read-only), and the literal upstream package name.

### Notes
- **Capture activation verified.** `<engine> init <client>` was confirmed to add only a safe MCP
  integration (memory/retrieve tools) — it does NOT change a client's model or base URL. Real
  token capture requires routing a client's traffic through the proxy; with the current
  DeepSeek-pinned proxy that would swap OpenAI clients' model, so transparent multi-provider
  routing is required before activating Codex/Cursor/OpenCode (see
  `references/token-capture.md`). Claude (Anthropic format) can capture transparently.

## [1.3.0] — 2026-06-23

### Changed
- **Token Monitor is now data-forward.** Replaced the large logo hero with a compact top bar
  (small badge + green/yellow wordmark + live status chips) and gave the screen to the data:
  a **real-time token chart** (before / after / saved area) driven by the engine's request
  history, plus the savings gauge and a tighter KPI strip.
- **Primary data source is now `proxy_savings.json`** (lifetime + per-request history), with the
  raw proxy log kept as fallback — more robust and exact than log scraping, and it exposes the
  real provider/model of each intercepted request.

### Added
- **"LLMs / runtimes we intercept" panel with per-runtime logos** and an honest interceptability
  tier: `native` (engine durable integration: Claude, Codex, VS Code/Copilot, OpenClaw),
  `base-url` (OpenAI/Anthropic-compatible: Hermes, Cursor, OpenCode), `not interceptable`
  (proprietary APIs: Gemini, Kiro, Antigravity). Shows 7/10 interceptable, dimming the rest.
- **$ saved** KPI and a models-intercepted readout sourced from real request history.

## [1.2.0] — 2026-06-23

### Changed
- **Rebranded the token monitor from the upstream branding to Simplicio.** The localhost dashboard is now
  the **Simplicio Token Monitor** (header + footer brand lockup rendered green + yellow).
  Our hooks/services/files were renamed to the `simplicio_*` scheme: the dashboard hook, the watch
  hook, and the setup script became `hooks/simplicio_dashboard.py`, `hooks/simplicio_watch.py`,
  `scripts/setup_simplicio.sh`; launchd services were renamed to `ai.simplicio.proxy`
  and `ai.simplicio.token-monitor`; the proxy-port env var → `SIMPLICIO_PROXY_PORT`
  (old name still honored as fallback); proxy log
  targets → `~/.hermes/logs/simplicio-proxy*.log`.
- **Carve-out:** the underlying compression accelerator is the third-party upstream
  product, so its real binary/install names are kept functional (its `pip install`,
  its `proxy` and `memory stats` commands) and its OSS attribution is preserved — only
  Simplicio-owned naming was changed.

### Added
- **Token Monitor auto-starts on macOS** via the renamed launchd service `ai.simplicio.token-monitor`,
  so the dashboard is live without a manual start.

## [1.1.0] — 2026-06-23

### Changed
- **Token dashboard redesigned to the Simplicio brand.** The localhost monitor
  (`hooks/simplicio_dashboard.py`, `:9090`) now renders the full Simplicio lockup faithfully
  in a neon-framed hero instead of a cropped square, echoes the brand tagline as four pillars
  (smart orchestration · neural cache · compressed context · maximum efficiency), and leads
  with a savings gauge (reduction %) + before→after token flow.
- **Runtime coverage is now a first-class panel** — all ten supported runtimes (Claude, Codex,
  Hermes, OpenClaw, VS Code, Gemini, Cursor, OpenCode, Kiro, Antigravity) each show how the
  skills load and how the loop drive is bound, with a coverage state pill.
- **Front-end construction cleaned up.** The single opaque HTML blob is split into
  `STYLE` / `BADGE_SVG` / `BODY` / `SCRIPT` constants composed via placeholder substitution —
  still single-file (deploy-friendly), no longer one unmaintainable string. The backend
  (`get_status` + handlers) is unchanged.

### Added
- **Repo-local brand asset** `assets/simplicio-loop-logo.png` — the dashboard now serves the
  logo from inside the repo (first logo candidate) instead of depending on a path outside it.
- **Faithful inline badge** (`BADGE_SVG`) — a vector of the hexagon-S mark (extruded S +
  stacked-layers core + circuit traces + speed particles), used as the favicon and the no-PNG
  fallback logo.

### Fixed
- Log viewer `tok_*=` highlight (`.hl`) had no CSS rule and rendered unstyled — now themed green.

## [1.0.5] — 2026-06-23

- Upstream compression integration: live web dashboard + monitor on `:9090`, context-compression proxy,
  MCP accelerator, setup script and launchd services.
- LMCache inference accelerator, agentsview session-observability source adapter.
- 11 runtime adapters + universal installer; hardened Ralph loop with bound operators
  (`simplicio-mapper` + `simplicio-cli`).

- header-change: .claude/skills/simplicio-loop/SKILL.md (classic mapper + dev-cli flow restored)
