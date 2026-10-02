# Scripts inventory — core vs satellite (#118)

This is a maintainer-curated inventory of the gate-relevant boundaries, not a count or a
classification of every utility under `scripts/`: **core** is required for the
`/simplicio-loop` drive or the local `check.py` gate, while **satellite** is opt-in/advanced (a
source adapter, an extension point not wired into the base loop, or a separate economy/demo
stack). The checkout and its latest local gate receipt are authoritative for inventory and result
counts; `scripts/test_categories.py` reports any tests that remain uncategorized.
`scripts/check.py --core-gate` runs the mandatory local gate: claims audit, mirror parity, core pytest selection,
loop contract, clean-environment contract, token/repository budgets, and portable stage-contract
validation. The default `scripts/check.py` uses the same phases with the full core+satellite pytest
selection. GitHub Actions is not required or accepted as evidence for either mode; the local
result is authoritative.

Status legend: **active** (invoked today, tested), **experimental** (tested but not yet wired to
any skill/doc invoker), **legacy** (superseded, kept for compatibility/history).

## Core (required for the loop drive or the local gate)

| Script | Invoker | Status |
|---|---|---|
| `check.py` | manual (`python3 scripts/check.py`) · git pre-push hook (fail-closed) · local result is authoritative; GitHub Actions is not required evidence | active |
| `check_runtime.py` | imported by `check.py` — sanitized environment, bounded subprocess tree, timeout/reason contracts | active |
| `claims_audit.py` | `check.py` | active |
| `claims_manifest.py` | imported by `claims_audit.py` (quantitative-claims registry) | active |
| `check_loop_contract.py` | `check.py` | active |
| `check_dashboard_event_contract.py` | `check.py` — `simplicio.dashboard-event/v1` schema + producer-fixture drift gate (#1398) | active |
| `dashboard_events.py` | runner, hooks and workers — `simplicio.dashboard-event/v1` emitter, reader and retroactive adapter (#1398); `docs/DASHBOARD_EVENTS.md` | active |
| `mirror_parity.py` | `check.py` — source/bundle/plugin parity is a distinct fail-closed phase | active |
| `clean_env_contract.py` | `check.py` — installed package metadata/entrypoint/bundle contract | active |
| `conformance_suite.py` | `check.py` — portable graph/receipt validation only; never claims an external runtime executed | active |
| `token_budget.py` | `check.py` (#121) | active |
| `repository_budget.py` | `check.py` (#294) — tracked-tree size budget: per-file cap (2 MiB) + total-growth gate + **forbidden-media rule** (video/out/, rust/target/, node_modules/, dist/, build/ blocked; large media only exempt under `assets/_lfs/` LFS per `.gitattributes`); read-only, history untouched | active |
| `mirror_manifest.py` | imported by `sync_plugin.py` + `claims_audit.py` (single source of truth for the lean hooks/scripts/tests sets) | active |
| `sync_plugin.py` | manual, after editing `.claude/skills/` or a shipped hook; `tests/test_system_check.py` exercises `--check` | active |
| `verify_adapters.py` | `claims_audit.py` check 7 (adapter-install-contract) | active |
| `doctor.py` | manual (`python3 scripts/doctor.py [--repair]`), also wrapped by `scripts/simplicio-engine doctor` | active |
| `preflight.py` | fail-closed identity, minimum-version, capability, and Runtime contract smoke gate (`python3 scripts/preflight.py --json`) | active |
| `ecosystem_doctor.py` | pre-planning cross-component version/capability/schema/SHA handshake (`python3 scripts/ecosystem_doctor.py --json`) | active |
| `install.sh` / `install.ps1` | README § Install; the plugin/marketplace install path | active |
| `install_lib.py` | imported by `install.sh` / `install.ps1` | active |
| `install_services.py` | install flow (service/daemon registration) | active |
| `setup_simplicio.sh` | install flow (environment bootstrap) | active |
| `update.sh` | manual update entrypoint (re-runs the install flow against a newer release) | active |
| `loop_journal.py` | SKILL.md § The loop contract / § Run-journal + stall detector; `hooks/loop_stop.py` | active |
| `task_anchor.py` | SKILL.md § The loop contract step 2; `hooks/loop_stop.py` (DoD gate) | active |
| `task_backlog.py` | SKILL.md § Phase 0 — intake & decomposition (frozen multi-item backlog above the anchor; genesis guard; `next`/`done` drain gate) | active |
| `watcher_verify.py` | SKILL.md § The loop contract step 3 (watcher-gate); `hooks/loop_stop.py` | active |
| `hierarchical_planner.py` | SKILL.md § HRM-style hierarchical planner; `hooks/loop_stop.py` (`plan` before re-feed) | active |
| `cross_agent_wiki.py` | SKILL.md § Cross-agent persistent wiki (per-turn capture) | active |
| `handoff.py` | SKILL.md § Agent-to-agent handoff (spindle/latch); `hooks/loop_stop.py` | active |
| `impact_audit.py` | SKILL.md § The loop contract step 2 (blast-radius gate) | active |
| `flow_audit.py` | SKILL.md § The loop contract step 2/3 (integration gate) | active |
| `video_evidence.py` | SKILL.md § Video evidence producer; `pr_evidence.py` | active |
| `web_verify.py` | `video_evidence.py`; manual/local invocation | active |
| `pr_evidence.py` | PR-open flow (`pr_evidence.py build --require-evidence`) | active |
| `toon_codec.py` | imported by `task_anchor.py` / `loop_journal.py` (TOON-rendered `--format toon` output) | active |
| `coverage_gate.py` | manual/local quality measurement — 85% global / 90% critical-path line coverage gate | active |
| `perf_gate.py` | manual/local performance measurement — latency/throughput/RSS vs `scripts/perf_baseline.json` + bounded convergence check | active |
| `flaky_gate.py` | manual/local repetition of the convergence/drain-critical test subset (or full suite in `--stress`) | active |
| `regression_test_gate.py` | manual/local source-to-test-change check | active |
| `test_categories.py` | `quality_matrix.py populate`/`independent_reverify_quality_matrix` (#283) — per-category (`unit`/`integration`/`system`/`regression`) test-runner split, reads the `tests/*_<category>.py` filename convention | active |
| `package_content_check.py` | explicit `check.py --package-content` release lane; not part of default/core because it builds real artifacts | active |

## Satellite (opt-in / advanced capabilities)

| Script | Invoker | Status |
|---|---|---|
| `journal_replay.py` | manual offline replay of journal/recovery fixtures; `tests/test_journal_replay_harness.py` | active |
| `issue_meta_audit.py` | manual read-only GitHub specification audit for issue #647; supports deterministic offline fixtures and writes `docs/audits/` evidence | active |
| `autoresearch.py` | the `simplicio-autoresearch` satellite skill | active |
| `agentsview_adapter.py` | AgentsView source adapter (README § Source adapters) | active |
| `az_boards_adapter.py` | Azure Boards source adapter (`.claude/skills/simplicio-loop/references/azure-devops-adapter.md`) | active |
| `repo_conventions.py` | the `repo_conventions` extension point (learns repo conventions on demand) | active |
| `schema_verify.py` | optional schema/migration-diff gate (invoked by hand or from a task's own AC, not every turn) | active |
| `billing_aggregator.py` | `scripts/simplicio-economy.sh` (economy/billing stack) | active |
| `savings_harness.py` | `scripts/simplicio-economy.sh`; `e2e_demo.py` | active |
| `e2e_demo.py` | manual capstone acceptance demo (README § the e2e savings demo) | active |
| `independent_watcher.py` | `docs/INDEPENDENT_WATCHER.md`; clean committed-snapshot behavioral verification | active |
| `simplicio-economy.sh` | manual (`bash scripts/simplicio-economy.sh {status\|up\|monitor\|tray\|wire}`) | active |
| `simplicio-capture.sh` | token-capture proxy control (pip-only asset, not shipped in the marketplace `plugin/`) | active |
| `simplicio-engine` | wrapper CLI around the capture/economy stack (`simplicio-engine doctor`, etc.) | active |
| `fan_out.py` | parallel task distribution — tested (`selftest` registered in `claims_audit.py`) but no documented invoker in any skill/reference doc yet | experimental |
| `blast-radius.sh` | none found — no reference in README/AGENTS/CLAUDE/skill docs, no test coverage; a shell-based selective-test-runner that predates (and overlaps with) `impact_audit.py`/`flow_audit.py` | legacy — candidate for removal or for being wired into `check.py --core-gate` in a follow-up issue, not decided here |

## How this maps to `scripts/check.py`

- `scripts/check.py` (no flags) — claims audit + mirror parity + full pytest suite excluding the
  marked `external_integration` lane + loop contract + clean-env + token budget + repository
  budget + portable contract validation. A marker-only pytest `--collect-only` probe reports the
  typed count as `EXTERNAL_INTEGRATION_EXCLUDED[marker_selection]=N` before execution.
- `scripts/check.py --core-gate` — the same mandatory phases with `SATELLITE_TEST_STEMS` removed
  (including the manual/snapshot `e2e_demo`, `check_e2e_demo_contract`, and
  `independent_watcher` suites) and `external_integration` deselected explicitly. Subprocess environment is allowlisted, pytest
  plugin autoload is disabled, and pytest plus Python descendants inheriting the gate environment
  allow only loopback/AF_UNIX sockets (arbitrary external CLIs are not network-sandboxed). The core
  has a 600-second global deadline, and every subprocess retains its shorter phase deadline.
- A zero pytest exit with no passed mandatory test is `pytest_all_tests_skipped`; missing pytest,
  test directories, or phase scripts fail with typed `*_unavailable`/`*_missing` reasons.
- External installed-runtime/live/sibling/release lanes are not core proof. The portable
  conformance phase validates only the shared graph/receipt fixture and reports zero external
  runtimes executed unless a separate real adapter lane supplies that evidence.
- `scripts/check.py --audit-only` / `--tests-only` / `--mirror-parity-only` /
  `--loop-contract-only` / `--clean-env-only` / `--token-budget` / `--repo-budget` /
  `--conformance` run the named local phase; `--package-content` is an explicit release lane.

Regenerating this table: there is no automated generator (it is maintainer-curated, cross-checked
against `scripts/claims_audit.py`'s `SELFTEST_SCRIPTS`/`SELFTEST_EXEMPT` and the doc references
each script's docstring/reference file points at). Re-verify it whenever a script is added,
removed, or its invoker changes.
