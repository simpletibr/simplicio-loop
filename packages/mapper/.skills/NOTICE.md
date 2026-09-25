# Third-party skills — NOTICE

## HyperFrames (Apache 2.0)

The following skill directories under `.skills/` are vendored verbatim from
the upstream HyperFrames project and are distributed under the Apache
License, Version 2.0:

- `hyperframes/`
- `hyperframes-cli/`
- `hyperframes-media/`
- `hyperframes-registry/`
- `gsap/`
- `animejs/`
- `css-animations/`
- `lottie/`
- `three/`
- `waapi/`
- `tailwind/`
- `typegpu/`
- `contribute-catalog/`
- `remotion-to-hyperframes/`
- `website-to-hyperframes/`

Upstream source: https://github.com/wesleysimplicio/hyperframes

License text: see `.skills/UPSTREAM-LICENSE` (Apache 2.0).

Modifications: none. Files are copied as-is from `skills/<name>/SKILL.md`
in the upstream repository at the time of import. To refresh, run:

```bash
for s in hyperframes hyperframes-cli hyperframes-media hyperframes-registry \
         gsap animejs css-animations lottie three waapi tailwind typegpu \
         contribute-catalog remotion-to-hyperframes website-to-hyperframes; do
  curl -sSf \
    "https://raw.githubusercontent.com/wesleysimplicio/hyperframes/main/skills/${s}/SKILL.md" \
    -o ".skills/${s}/SKILL.md"
done
```

## Superpowers (MIT)

The following skill directories under `.skills/` are vendored verbatim from
the upstream Superpowers project (Copyright (c) 2025 Jesse Vincent) and are
distributed under the MIT License:

- `using-superpowers/`
- `brainstorming/`
- `writing-plans/`
- `test-driven-development/`
- `subagent-driven-development/`
- `systematic-debugging/`
- `verification-before-completion/`

Upstream source: https://github.com/obra/superpowers

License text: see `.skills/UPSTREAM-LICENSE-superpowers` (MIT).

Modifications: none. Files are copied as-is from `skills/<name>/` in the
upstream repository at the time of import, including each skill's supporting
files (`references/`, `*-prompt.md`, technique docs). Internal path references
inside the vendored files keep their upstream `skills/<name>/...` form. To
refresh, run:

```bash
BASE="https://raw.githubusercontent.com/obra/superpowers/main/skills"
for p in \
  using-superpowers/SKILL.md \
  using-superpowers/references/copilot-tools.md \
  using-superpowers/references/codex-tools.md \
  brainstorming/SKILL.md \
  brainstorming/visual-companion.md \
  writing-plans/SKILL.md \
  test-driven-development/SKILL.md \
  test-driven-development/testing-anti-patterns.md \
  subagent-driven-development/SKILL.md \
  subagent-driven-development/implementer-prompt.md \
  subagent-driven-development/spec-reviewer-prompt.md \
  subagent-driven-development/code-quality-reviewer-prompt.md \
  systematic-debugging/SKILL.md \
  systematic-debugging/root-cause-tracing.md \
  systematic-debugging/defense-in-depth.md \
  systematic-debugging/condition-based-waiting.md \
  verification-before-completion/SKILL.md; do
  mkdir -p ".skills/$(dirname "${p}")"
  curl -sSf "${BASE}/${p}" -o ".skills/${p}"
done
```

## Project-original skills

Local skills (`_template/`, `caveman/`, `ralph-loop/`, `everything-claude-code/`,
`playwright-e2e/`, `conventional-commits/`, `rtk-cli/`) are project-original
and not covered by this notice.
