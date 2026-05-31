# Changelog

All notable changes to **LLM Project Mapper** are documented in this file.

Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.10] - 2026-05-31

### Added
- `simplicio-mapper screens <path> --json` inventories Angular route screens,
  redirects, personas, guarded routes and dynamic route parameters using the
  stable `simplicio.screen-inventory/v1` schema. This supports full-screen
  evidence runs such as EVT's web/API/PostgreSQL Playwright validation.

## [0.6.9] - 2026-05-31

### Changed
- Endpoint inventory JSON now includes `sources` on each
  `missing_from_server` item, so cross-repo alignment work can jump straight
  from a missing route to the screen or client file that requires it.

## [0.6.8] - 2026-05-31

### Changed
- `simplicio-mapper index` now accepts `--update` as a compatibility alias for
  refresh workflows, so existing Simplicio scripts can call the Python indexer
  without special branching.
- Endpoint inventory now resolves Angular service `baseUrl` constants,
  `environment.apiUrl`, and template-string path parameters. This lets
  `simplicio-mapper endpoints ./web --against ./api` inventory real Angular
  services instead of only literal URLs in tests.
- Python endpoint inventory now captures direct page/client calls such as
  `api.patch(...)` and `api._client.put(...)`, while ignoring test files and
  FastAPI route decorators so AI-Agents runtime demand is not undercounted or
  duplicated.

## [0.6.7] - 2026-05-31

### Added
- `simplicio-mapper endpoints <path> --against <server-root> --json` extracts
  normalized client calls and server HTTP routes, then reports
  `missing_from_server` using the stable
  `simplicio.endpoint-inventory/v1` schema. This turns cross-repo endpoint
  alignment checks into a reusable mapper workflow.

## [0.6.6] - 2026-05-31

### Changed
- Git status collection now uses `--untracked-files=all`, so files inside new
  directories are marked as `??` in `files[].git_status`, `changed_files`, and
  `recent_changes` instead of looking clean in mapper artifacts.

## [0.6.5] - 2026-05-31

### Changed
- Python mapper now skips generated `output/` trees, including Playwright
  HTML reports and trace result folders, so live evidence artifacts do not
  pollute `.simplicio/project-map.json`.

## [0.6.4] - 2026-05-31

### Changed
- Python mapper skips generated dependency/cache directories from real
  Angular/.NET/Python projects (`.angular`, `obj`, `.pytest_cache`,
  `.mypy_cache`, `.ruff_cache`, `.gradle`, `target`) while preserving source
  `bin/` folders outside .NET project roots.
- `simplicio-mapper index` now returns exit code `0` for `already_fresh`
  indexes, preserving the structured `status=skipped` payload without making
  idempotent automation look failed.
- C# / ASP.NET symbol extraction now records controller classes and route
  attributes for endpoint-alignment work.

## [0.6.3] - 2026-05-31

### Changed
- Refresh Node, docs-site, video, VS Code extension, and Python dependency
  floors to the latest compatible releases used by the Simplicio E2E flow.
- Keep `@mermaid-js/layout-elk` on the Docusaurus-compatible `0.1.x` line while
  updating the surrounding Docusaurus and React packages.

## [0.6.2] - 2026-05-30

### Changed
- `--update` no longer appends or rewrites `.gitignore` unless
  `--append-gitignore yes` is passed explicitly.
- The recommended `.gitignore` block now keeps shared starter context visible
  in Git (`AGENTS.md`, `.agents/`, `.skills/`, `.specs/`,
  `.starter-meta.json`) and only ignores local state, caches, build output,
  env files, logs, and test artifacts.

### Added
- `simplicio-mapper index <path>` idempotent orchestration command for
  SendSprint. It writes the standard `.simplicio/project-map.json` and
  `precedent-index.json`, short-circuits fresh indexes with exit code `2`, and
  exposes a stable `--json` payload with artifact paths, counts, changed files
  and skipped reason.

## [0.6.0] - 2026-05-28

### Added
- Optional Rust acceleration crate `rust/simplicio_mapper_rs` exposing
  `sha256_hex` and `parse_imports` via PyO3, plus `simplicio_mapper._native`
  shim that routes mapper hot paths to it when installed and falls back to the
  pure-Python implementation otherwise (closes #83). ADR-002 documents the
  evaluation.
- Standalone Python distribution `simplicio-mapper` on PyPI: lightweight
  `simplicio_mapper.mapper` port of the Node mapper plus a `map` / `update` CLI
  exposed as the `simplicio-mapper` and `llm-project-mapper` console scripts.
  Generates the same `.simplicio/project-map.json` and `precedent-index.json`
  without requiring a Node toolchain.
- Performance optimizations for the Python mapper (closes #82): `orjson` for
  faster JSON serialization, persistent `diskcache` of per-file processing keyed
  by path/size/mtime, and `__slots__`-backed internal models (`ProjectFile`,
  `CodeEntity`, `PrecedentItem`) for lower memory on large projects. Schema and
  artifact contracts remain stable; the package now ships with two lightweight
  runtime dependencies (`orjson`, `diskcache`) instead of being dependency-free.
- `map` / `update` CLI subcommands for generating and incrementally refreshing
  `.simplicio/project-map.json` and `.simplicio/precedent-index.json`.
- Rich machine-readable mapper artifacts with file inventory, roles, imports,
  exports, entity extraction, architecture signals, dependency context, changed
  files, and precedent snippets for downstream consumers.
- `SIMPLICIO_INTEGRATION.md` documenting the JSON contract and Python consumer
  example for `simplicio-dev-cli`.
- `skillopt` command and `bin/skillopt.js` wrapper implementing the [SkillOpt](https://microsoft.github.io/SkillOpt/) loop (Rollout → Reflect → Edit → Gate): optimizes a natural-language skill document against a task suite, treating the skill as the only trainable artifact. Emits `best_skill.md`, an optional run report, and a content-addressed receipt under `.catalog/receipts/`. Engine in `scripts/skillopt/engine.js` is deterministic, dependency-free, and exposes a pluggable scorer for real LLM adapters.
- `.skills/skillopt/SKILL.md` skill manifest plus runnable `example.skill.md` / `example.suite.json` fixtures.
- Root-level `YOOL_TUPLE_HAMT.md` vendored alongside the existing `docs/` copy so the canonical pattern spec is reachable directly from the repository root and ships with the npm package.
- `build-hamt-catalog` wrapper plus stdlib-only `scripts/build_hamt.py`, enabling `npx @wesleysimplicio/llm-project-mapper build-hamt-catalog` to emit `.catalog/agents.json`.
- Runtime scaffold defaults for `.catalog/.gitkeep`, `.catalog/agents.json`, `.receipts/.gitkeep`, and optional `mcp/server.{ts,py}` edge adapters via `--mcp-edge`.
- Dedicated docs-site coverage for YOOL / tuple / HAMT, including the public `/yool-tuple-hamt` route and regression tests for the new page.

### Changed
- Bootstrap now writes the structured mapper artifacts automatically and records
  the `simplicio` integration block in `.starter-meta.json`.
- INIT prompts now require validation of `.simplicio/project-map.json` and
  `.simplicio/precedent-index.json` during agent inspection.
- `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` now point to the root spec, document the receipts schema, and align the generated catalog output on `.catalog/agents.json`.
- The Node bootstrap path now mirrors the shell/PowerShell runtime scaffold so fresh `npx` installs create the catalog, receipts, and optional MCP edge templates consistently.

## [0.4.2] - 2026-05-19

### Added
- `.skills/rtk-cli/SKILL.md` skill manifest (force-added past the `.skills/`
  gitignore exclusion to match the other tracked starter skills). Documents
  RTK CLI usage with trigger, steps, do-not list, and DoD. Already shipped
  via npm tarball; now tracked in git so consumers can discover it on
  GitHub.

### Notes
- Closes #71. RTK guidance was already present in AGENTS.md, CLAUDE.md and
  `.github/copilot-instructions.md` — the missing piece was the skill folder
  visibility on GitHub.

## [0.4.1] - 2026-05-19

### Added
- Vendored YOOL/tuple/HAMT spec at `docs/YOOL_TUPLE_HAMT.md` (v0.2 from
  https://github.com/wesleysimplicio/yool-tuple-hamt) plus `AGENTS.md` /
  `CLAUDE.md` blocks defining the agent capability declaration template
  (`yool_id`, `authority`, `lane`, `agent_terms` with **mandatory**
  `cpu_quota_pct`, `disk_quota_mb`, `timeout_s`).
- `bootstrap.sh` now scaffolds `.catalog/` (receipts/, artifacts/, README) so
  the HAMT catalog has a predictable home in every starter-generated project.
- Guardrail rationale anchored to Victor Genaro's review: *"precisa de
  guardrail pra não fritar o processador. Você precisa de garbage collector
  também pra não encher 100% do disco."*

## [0.4.0] - 2026-05-19

### Added
- Added a local `rtk-cli` skill that teaches agents when and how to use RTK's compact shell output for repository exploration, `git`, `grep/find`, and verbose validation commands.

### Changed
- Updated `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, and session-start hooks to prefer RTK for shell-heavy workflows when it is installed, while explicitly keeping `curl`, `playwright`, and interactive or streaming commands on raw output.
- Allowed `Bash(rtk *)` in `.claude/settings.json` so Claude Code sessions can invoke RTK without extra local permission friction.
- Extended regression coverage to assert the shipped RTK skill, hook reminders, and contributor docs stay aligned.

## [0.3.2] - 2026-05-18

### Changed
- Documented a project-specific default release policy: release-relevant work in `llm-project-mapper` must finish with npm, Git tag, GitHub Release, `main`, and validation all synchronized in the same cycle.

## [0.3.1] - 2026-05-18

### Changed
- Replaced the remaining historical legacy-name references in repository documentation so the package and project naming stay fully aligned as `llm-project-mapper`.

## [0.3.0] - 2026-05-18

### Added
- Automatic local project mapping immediately after bootstrap. `bin/auto-map.js` now inspects the host project, infers stack/domain/team/integrations, generates `.specs/journal/inspection-YYYY-MM-DD.md`, and pre-fills the starter-managed docs without waiting for a manual `INIT.md` handoff.
- Regression coverage for the automatic mapping flow in both `tests/unit/cli-install.test.js` and `tests/e2e/cli.spec.ts`, including placeholder-clean assertions on the generated starter-managed files.
- `vscode-extension/` scaffold for `wesleysimplicio.llm-project-mapper-vscode`. Ships a TreeView for `.specs/sprints/`, plus commands `lpm.openCurrentTask`, `lpm.createAdr`, `lpm.runInit`, `lpm.refresh` and a live status-bar indicator. Pure filesystem walker (`src/scan.ts`) covered by `node --test` unit tests.
- `--telemetry on|off` flag on `bin/cli.js` (default off). Honored via `LLM_PROJECT_MAPPER_TELEMETRY` env var. Persists user choice to `~/.config/llm-project-mapper/telemetry.json`. Hard-disabled under `CI`, `--dry-run`, or when no `LLM_PROJECT_MAPPER_TELEMETRY_URL` is set.
- `PRIVACY.md` documenting telemetry payload shape, opt-in mechanics, and kill switches.
- `.github/workflows-templates/telemetry-worker.js` — reference Cloudflare Worker template (PII-sanitized aggregator).
- README sections (EN + PT-BR) under "Companion tooling" linking the new extension and PRIVACY.md.
- `tests/unit/cli-telemetry.test.js` — 5 new tests covering opt-in/out persistence and help-text presence.

### Changed
- Bootstrap messaging now explains that the mapping pass starts automatically and that `INIT.md` is an optional second-pass refinement step.
- Package version bumped to `0.3.0` to ship the automatic mapping workflow and updated regression coverage.

## [0.2.2] - 2026-05-18

### Added
- Local PT-BR + EN narration pipeline for `video/assets/why-llm-project-mapper{,-en}.mp4`, generated from `video/src/why/narration.json` via `say` + `ffmpeg`.
- Burned-in captions for the Why video via `@remotion/captions`, driven by the same narration source file.
- Versioned `video/public/captions/why-{pt,en}.srt` exports from the narration pipeline for timing review.
- `video/TTS-EVALUATION.md` comparing ElevenLabs, OpenAI `tts-1-hd`, and Azure Neural for future upgrades.

### Changed
- `video/public/sfx/rock-bg.mp3` is now mixed under narration at `volume=0.15`.
- Root lint now checks `video/scripts/*.mjs`.

## [0.2.1] - 2026-05-18

### Added
- `docs-site/` Docusaurus hub with GitHub Pages deployment workflow, local search, and versioned docs generated from repository markdown sources.
- Animated overlay-install screencast at `assets/overlay-install.svg`, embedded in the README and install guides.
- `LICENSE` (MIT) at repository root and shipped in npm tarball.
- `CHANGELOG.md` (this file) covering history v0.1.0 → v0.2.0.
- `npm run lint` script — wraps ESLint-equivalent checks for `bin/`, `tests/`, `scripts/`, shell scripts and Markdown.
- `npm test` script — `node --test tests/unit` runner (no extra dependency).
- Unit tests for `bin/cli.js`: `parseArgs`, `detectStack`, `detectProjectMode`, `mergeGitignore`, `.starter-meta.json` shape.
- Concrete `tests/e2e/smoke.spec.ts` exercising the real `npx` install flow (dry-run, fresh install, update, stack detection, monorepo detection).
- `INIT.en.md` + `INSTALL.en.md` — English translations of the install guide.
- `docs/placeholders.md` — catalog of every `<PLACEHOLDER>` token used by the starter.
- `docs/api-examples/{rest,graphql,webhook,cli}.md` — fill-in templates for documenting APIs.
- `SHOWCASE.md` — community list of consumer projects.
- PSScriptAnalyzer job in `scaffold-self-check.yml` covering `bootstrap.ps1` and `*.ps1` scripts.
- Cross-platform matrix (ubuntu/macos/windows) in `scaffold-self-check.yml`.
- `--preset <stack>` flag in `bin/cli.js` (nextjs, dotnet, fastapi, go, rails, flutter) — preset list at `--preset list`.
- `--no-update-check` flag and embedded semver notifier in `bin/cli.js`.
- `.github/workflows-templates/llm-project-mapper-init.yml` — GitHub Action wrapper template.
- `docs/sessionstart-hook.md` — operational doc for `.claude/hooks/session-start-skills.sh`.

### Changed
- `package.json` now lists `LICENSE`, `CHANGELOG.md`, `INIT.en.md`, `INSTALL.en.md` in `files[]` so they ship with the npm package.
- `ci.yml` and `dod.yml` no longer skip the `llm-project-mapper` repo itself (eat-your-own-dog-food).
- `presentation/slides.md` regenerated after rename — PDF + PPTX rebuilt.

### Fixed
- Residual legacy naming mentions removed from `_BOOTSTRAP.md` and inline examples (legacy detection in `bin/cli.js` preserved for back-compat overlays).

## [0.2.0] - 2026-05-16

### Changed
- **BREAKING** Renamed the npm package to `@wesleysimplicio/llm-project-mapper`. ([#15](https://github.com/wesleysimplicio/llm-project-mapper/pull/15))
- **BREAKING** Renamed the CLI command to `npx @wesleysimplicio/llm-project-mapper`.
- **BREAKING** Source override env var renamed to `LLM_PROJECT_MAPPER_SOURCE`.
- Video compositions renamed to `WhyLlmProjectMapper{PT,EN}`.
- Assets renamed to `assets/llm-project-mapper-*.png`.

### Deprecated
- The previous package name is marked deprecated and redirects users to `@wesleysimplicio/llm-project-mapper`.

## [0.1.6] - 2026-05-15

### Added
- Rock backing track on the Why explainer video (kick/snare/hi-hat/power chord drone synthesized with ffmpeg). ([#14](https://github.com/wesleysimplicio/llm-project-mapper/pull/14))
- Static cover linked from `README.md` and `README.pt-BR.md`.

### Changed
- Why video re-paced: 80s → 53s, 17.7 MB → 14.1 MB. Animation delays reduced from `frame - 50..280` to `frame - 4..170`.

## [0.1.5] - 2026-05-15

### Added
- WhyLlmProjectMapper explainer video in PT-BR and EN (9 scenes, 80s, 1080p). ([#12](https://github.com/wesleysimplicio/llm-project-mapper/pull/12))
- `video/src/why/` isolated directory with own i18n provider (`WhyLangProvider`, `STRINGS_WHY`).
- npm scripts `build:why`, `build:why:en`, `build:why:all`, `still:why`, `still:why:en`.

### Fixed
- Hook execution repair + starter hero image.

## [0.1.4] - 2026-05-14

### Added
- `workflow_dispatch:` trigger on the `Publish to npm` workflow. ([#10](https://github.com/wesleysimplicio/llm-project-mapper/pull/10))
- `Verify npm auth (whoami)` early-failure step on the publish workflow.

## [0.1.3] - 2026-05-14

### Added
- Safe starter update command (`npx ... --update`).
- `scripts/update-starter.sh` / `scripts/update-starter.ps1`.

## [0.1.2] - 2026-05-13

### Added
- `.github/workflows/publish-npm.yml` — auto-publishes to npm on every push to `main` when `package.json` version differs from registry, with `--provenance --access public` and automatic `vX.Y.Z` tag. ([#7](https://github.com/wesleysimplicio/llm-project-mapper/pull/7))

## [0.1.1] - 2026-05-13

### Added
- `INSTALL.md` — step-by-step overlay install guide for existing host projects. ([#4](https://github.com/wesleysimplicio/llm-project-mapper/pull/4))
- Always-on skills: `ralph-loop`, `caveman`, `everything-claude-code`. ([#3](https://github.com/wesleysimplicio/llm-project-mapper/pull/3))
- `.claude/hooks/session-start-skills.sh` SessionStart hook.
- `# Agentic starter tracked files` block to `.gitignore`. ([#5](https://github.com/wesleysimplicio/llm-project-mapper/issues/5), [#6](https://github.com/wesleysimplicio/llm-project-mapper/pull/6))

### Changed
- Replaced `projects/` convention with workspace-signal mode detection (`pnpm-workspace.yaml`, `lerna.json`, `nx.json`, `turbo.json`, `rush.json`, `package.json` workspaces, or ≥2 manifests under `apps/`/`packages/`/`services/`). ([#4](https://github.com/wesleysimplicio/llm-project-mapper/pull/4))
- Unified `.starter-meta.json` schema across `bootstrap.sh`, `bootstrap.ps1`, `bin/cli.js`.

## [0.1.0] - 2026-05-09

### Added
- Initial release.
- Master instruction file `AGENTS.md` + mirrors `CLAUDE.md` and `.github/copilot-instructions.md`.
- `.specs/` skeleton (product, architecture, workflow, sprints).
- `.skills/` catalog (playwright-e2e, conventional-commits, _template).
- `.agents/` catalog (ralph-loop, tdd, reviewer, architect).
- `.claude/` hooks (post-edit, pre-commit).
- `.codex/config.toml`.
- CI workflows (`ci.yml`, `dod.yml`, `scaffold-self-check.yml`).
- PR + Issue templates.
- Bootstrap installers: `bootstrap.sh`, `bootstrap.ps1`, `bin/cli.js` (`npx @wesleysimplicio/llm-project-mapper`).
- Marp presentation (`presentation/slides.md` → PDF + PPTX).
- Remotion skills tutorial video in PT-BR. ([#1](https://github.com/wesleysimplicio/llm-project-mapper/pull/1))
- i18n layer + English skills tutorial video. ([#2](https://github.com/wesleysimplicio/llm-project-mapper/pull/2))

[Unreleased]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.6.3...HEAD
[0.6.3]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.6.1...v0.6.2
[0.4.0]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.2.0
[0.1.6]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.6
[0.1.5]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.5
[0.1.4]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.4
[0.1.3]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.3
[0.1.2]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.2
[0.1.1]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.1
[0.1.0]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.0

## Unreleased / In Progress (EVT Alignment Work)

### Improvements to mapper for real enterprise monorepos
- Enhanced C# symbol extraction to detect ASP.NET controllers (`*Controller` classes) and HTTP attributes (`[HttpGet]`, `[HttpPost]`, `[Route]`, etc.).
- This was driven by the need to map endpoints across `beyondlabs-maturity_matrix-api` (.NET), `-web` (Angular), and `-ai-agents`.
- Better support for mixed-stack monorepos (Angular + .NET + Python agents).

These changes make `simplicio-mapper` significantly more useful for reverse-engineering and contract alignment tasks on existing large codebases.
