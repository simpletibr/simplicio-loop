# Architecture Layers

## asset

- Files: 46
- Modules: ., .claude, .codex, .github, .skills, docs-site, video, vscode-extension

- `.claude/hooks/post-edit.ps1`
- `.claude/hooks/post-edit.sh`
- `.claude/hooks/pre-commit.ps1`
- `.claude/hooks/pre-commit.sh`
- `.claude/hooks/session-start-skills.ps1`
- `.claude/hooks/session-start-skills.sh`
- `.claude/settings.json`
- `.codex/hooks.json`
- `.codex/hooks/pre-commit.ps1`
- `.codex/hooks/pre-commit.sh`
- `.codex/hooks/session-start-skills.ps1`
- `.gitattributes`
- `.github/CODEOWNERS`
- `.github/workflows-templates/llm-project-mapper-init.yml`
- `.github/workflows/ci.yml`
- `.github/workflows/docs-site.yml`
- `.github/workflows/dod.yml`
- `.github/workflows/publish-pypi.yml`
- `.github/workflows/scaffold-self-check.yml`
- `.gitignore`
- `.llm-project-mapper.json`
- `.skills/UPSTREAM-LICENSE`
- `.skills/UPSTREAM-LICENSE-superpowers`
- `.skills/skillopt/example.suite.json`
- `LICENSE`
- `bootstrap.ps1`
- `bootstrap.sh`
- `docs-site/docs/community/_category_.json`
- `docs-site/docs/concepts/_category_.json`
- `docs-site/docs/guide/_category_.json`
- `docs-site/docs/quickstart/_category_.json`
- `docs-site/docs/reference/_category_.json`
- `docs-site/versioned_docs/version-0.2.0/community/_category_.json`
- `docs-site/versioned_docs/version-0.2.0/concepts/_category_.json`
- `docs-site/versioned_docs/version-0.2.0/guide/_category_.json`
- `docs-site/versioned_docs/version-0.2.0/quickstart/_category_.json`
- `docs-site/versioned_docs/version-0.2.0/reference/_category_.json`
- `docs-site/versioned_sidebars/version-0.2.0-sidebars.json`
- `docs-site/versions.json`
- `package-lock.json`
- `video/.gitignore`
- `video/package-lock.json`
- `video/src/why/narration.json`
- `vscode-extension/.gitignore`
- `vscode-extension/LICENSE`
- `vscode-extension/package-lock.json`

## code

- Files: 42
- Modules: .github, bin, docs-site, rust, simplicio_mapper, video, vscode-extension

- `.github/workflows-templates/telemetry-worker.js`
- `bin/auto-map.js`
- `bin/hook-runner.js`
- `bin/map.js`
- `bin/mapper-artifacts.js`
- `docs-site/sidebars.cjs`
- `rust/src/lib.rs`
- `simplicio_mapper/__init__.py`
- `simplicio_mapper/_native.py`
- `simplicio_mapper/cache.py`
- `simplicio_mapper/mapper.py`
- `video/scripts/generate-why-voiceover.mjs`
- `video/scripts/regression.mjs`
- `video/src/LangContext.tsx`
- `video/src/Root.tsx`
- `video/src/SkillsTutorial.tsx`
- `video/src/i18n.ts`
- `video/src/scenes/BestPractices.tsx`
- `video/src/scenes/Catalog.tsx`
- `video/src/scenes/CommitsSkill.tsx`
- `video/src/scenes/CreateYourOwn.tsx`
- `video/src/scenes/HowToInvoke.tsx`
- `video/src/scenes/Intro.tsx`
- `video/src/scenes/Outro.tsx`
- `video/src/scenes/PlaywrightSkill.tsx`
- `video/src/scenes/WhatAreSkills.tsx`
- `video/src/theme.ts`
- `video/src/why/LangContext.tsx`
- `video/src/why/WhyLlmProjectMapper.tsx`
- `video/src/why/audio.ts`
- `video/src/why/i18n.ts`
- `video/src/why/scenes/Anatomy.tsx`
- `video/src/why/scenes/CTA.tsx`
- `video/src/why/scenes/Hook.tsx`
- `video/src/why/scenes/MultiAgent.tsx`
- `video/src/why/scenes/PainList.tsx`
- `video/src/why/scenes/PainTyping.tsx`
- `video/src/why/scenes/Productivity.tsx`
- `video/src/why/scenes/Reveal.tsx`
- `video/src/why/scenes/SideBySide.tsx`
- `vscode-extension/src/extension.ts`
- `vscode-extension/src/scan.ts`

## config

- Files: 13
- Modules: ., .codex, docs-site, rust, video, vscode-extension

- `.codex/config.toml`
- `docs-site/docusaurus.config.cjs`
- `docs-site/package.json`
- `package.json`
- `playwright.config.ts`
- `pyproject.toml`
- `rust/Cargo.toml`
- `rust/pyproject.toml`
- `video/package.json`
- `video/remotion.config.ts`
- `video/tsconfig.json`
- `vscode-extension/package.json`
- `vscode-extension/tsconfig.json`

## documentation

- Files: 140
- Modules: ., .agents, .github, .skills, .specs, docs, docs-site, presentation, rust, scripts, tests, video, vscode-extension

- `.agents/README.md`
- `.agents/_template.agent.md`
- `.agents/architect.agent.md`
- `.agents/ralph-loop.agent.md`
- `.agents/reviewer.agent.md`
- `.agents/tdd.agent.md`
- `.github/ISSUE_TEMPLATE/bug.md`
- `.github/ISSUE_TEMPLATE/feature.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/copilot-instructions.md`
- `.github/copilot/agents/_template.agent.md`
- `.github/copilot/agents/architect.agent.md`
- `.github/copilot/agents/ralph-loop.agent.md`
- `.github/copilot/agents/reviewer.agent.md`
- `.github/copilot/agents/tdd.agent.md`
- `.github/workflows-templates/README.md`
- `.skills/NOTICE.md`
- `.skills/README.md`
- `.skills/_template/SKILL.md`
- `.skills/animejs/SKILL.md`
- `.skills/brainstorming/SKILL.md`
- `.skills/brainstorming/visual-companion.md`
- `.skills/caveman/SKILL.md`
- `.skills/contribute-catalog/SKILL.md`
- `.skills/conventional-commits/SKILL.md`
- `.skills/css-animations/SKILL.md`
- `.skills/everything-claude-code/SKILL.md`
- `.skills/gsap/SKILL.md`
- `.skills/hyperframes-cli/SKILL.md`
- `.skills/hyperframes-media/SKILL.md`
- `.skills/hyperframes-registry/SKILL.md`
- `.skills/hyperframes/SKILL.md`
- `.skills/lottie/SKILL.md`
- `.skills/playwright-e2e/SKILL.md`
- `.skills/ralph-loop/SKILL.md`
- `.skills/remotion-to-hyperframes/SKILL.md`
- `.skills/rtk-cli/SKILL.md`
- `.skills/skillopt/SKILL.md`
- `.skills/skillopt/example.skill.md`
- `.skills/subagent-driven-development/SKILL.md`
- `.skills/subagent-driven-development/code-quality-reviewer-prompt.md`
- `.skills/subagent-driven-development/implementer-prompt.md`
- `.skills/subagent-driven-development/spec-reviewer-prompt.md`
- `.skills/systematic-debugging/SKILL.md`
- `.skills/systematic-debugging/condition-based-waiting.md`
- `.skills/systematic-debugging/defense-in-depth.md`
- `.skills/systematic-debugging/root-cause-tracing.md`
- `.skills/tailwind/SKILL.md`
- `.skills/test-driven-development/SKILL.md`
- `.skills/test-driven-development/testing-anti-patterns.md`
- `.skills/three/SKILL.md`
- `.skills/typegpu/SKILL.md`
- `.skills/using-superpowers/SKILL.md`
- `.skills/using-superpowers/references/codex-tools.md`
- `.skills/using-superpowers/references/copilot-tools.md`
- `.skills/verification-before-completion/SKILL.md`
- `.skills/waapi/SKILL.md`
- `.skills/website-to-hyperframes/SKILL.md`
- `.skills/writing-plans/SKILL.md`
- `.specs/README.md`

## domain

- Files: 1
- Modules: simplicio_mapper

- `simplicio_mapper/models.py`

## entrypoint

- Files: 6
- Modules: bin, docs, simplicio_mapper, video

- `bin/build-hamt-catalog`
- `bin/cli.js`
- `bin/skillopt.js`
- `docs/api-examples/cli.md`
- `simplicio_mapper/cli.py`
- `video/src/index.ts`

## model

- Files: 1
- Modules: simplicio_mapper

- `simplicio_mapper/models.py`

## script

- Files: 15
- Modules: scripts

- `scripts/README.md`
- `scripts/build_hamt.py`
- `scripts/check-placeholders.sh`
- `scripts/coverage.js`
- `scripts/evidence.ps1`
- `scripts/evidence.sh`
- `scripts/lint.js`
- `scripts/skillopt/engine.js`
- `scripts/start.ps1`
- `scripts/start.sh`
- `scripts/sync-docs-site.mjs`
- `scripts/test.ps1`
- `scripts/test.sh`
- `scripts/update-starter.ps1`
- `scripts/update-starter.sh`

## test

- Files: 38
- Modules: .skills, .specs, scripts, tests, vscode-extension

- `.skills/subagent-driven-development/spec-reviewer-prompt.md`
- `.skills/test-driven-development/SKILL.md`
- `.skills/test-driven-development/testing-anti-patterns.md`
- `.specs/README.md`
- `.specs/architecture/ADR-001-example.md`
- `.specs/architecture/ADR-002-python-rust-hybrid.md`
- `.specs/architecture/ADR-template.md`
- `.specs/architecture/DESIGN.md`
- `.specs/architecture/PATTERNS.md`
- `.specs/product/DOMAIN.md`
- `.specs/product/PERSONAS.md`
- `.specs/product/VISION.md`
- `.specs/sprints/BACKLOG.md`
- `.specs/sprints/sprint-01/01-example.task.md`
- `.specs/sprints/sprint-01/SPRINT.md`
- `.specs/sprints/task-template.md`
- `.specs/workflow/CONTRIBUTING.md`
- `.specs/workflow/RELEASE.md`
- `.specs/workflow/WORKFLOW.md`
- `scripts/test.ps1`
- `scripts/test.sh`
- `tests/e2e/README.md`
- `tests/e2e/build-hamt-catalog.spec.ts`
- `tests/e2e/cli.spec.ts`
- `tests/e2e/skillopt.spec.ts`
- `tests/e2e/smoke.spec.ts`
- `tests/python/test_cli.py`
- `tests/python/test_native.py`
- `tests/unit/build-hamt-catalog.test.js`
- `tests/unit/cli-args.test.js`
- `tests/unit/cli-install.test.js`
- `tests/unit/cli-telemetry.test.js`
- `tests/unit/docs-site.test.js`
- `tests/unit/mapping-artifacts.test.js`
- `tests/unit/overlay-docs.test.js`
- `tests/unit/skillopt.test.js`
- `tests/unit/why-video-narration.test.js`
- `vscode-extension/test/scan.test.js`

## ui

- Files: 11
- Modules: .agents, .github, .skills, video

- `.agents/reviewer.agent.md`
- `.github/copilot/agents/reviewer.agent.md`
- `.skills/subagent-driven-development/code-quality-reviewer-prompt.md`
- `.skills/subagent-driven-development/spec-reviewer-prompt.md`
- `video/src/components/AnimatedText.tsx`
- `video/src/components/BackgroundFX.tsx`
- `video/src/components/Bullet.tsx`
- `video/src/components/Card.tsx`
- `video/src/components/CodeBlock.tsx`
- `video/src/components/SceneTransition.tsx`
- `video/src/components/Terminal.tsx`
