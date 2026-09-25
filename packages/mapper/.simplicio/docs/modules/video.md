# Module: video

Groups 45 files across 6 detected layers.

## Structure

- Files: 45
- Layers: asset, code, config, documentation, entrypoint, ui
- Entry points: `video/src/index.ts`
- Tests: none detected

## Files

- `video/.gitignore`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: asset
- `video/README.md`: Documents product, architecture, operation or contributor workflow. Layers: documentation
- `video/TTS-EVALUATION.md`: Documents product, architecture, operation or contributor workflow. Layers: documentation
- `video/package-lock.json`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: asset
- `video/package.json`: Configures tooling, build, runtime or packaging behavior. Layers: config
- `video/remotion.config.ts`: Configures tooling, build, runtime or packaging behavior. Layers: config
- `video/scripts/generate-why-voiceover.mjs`: Defines exported symbols: buildCaptions, buildTrack, cueAudioPath, ensureCommand, main. Layers: code
- `video/scripts/regression.mjs`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: code
- `video/src/LangContext.tsx`: Defines exported symbols: LangProvider, useLang, useT. Layers: code
- `video/src/Root.tsx`: Defines exported symbols: RemotionRoot. Layers: code
- `video/src/SkillsTutorial.tsx`: Defines exported symbols: SkillsTutorial, TOTAL_DURATION. Layers: code
- `video/src/components/AnimatedText.tsx`: Defines exported symbols: AnimatedText. Layers: ui
- `video/src/components/BackgroundFX.tsx`: Defines exported symbols: BackgroundFX. Layers: ui
- `video/src/components/Bullet.tsx`: Defines exported symbols: Bullet. Layers: ui
- `video/src/components/Card.tsx`: Defines exported symbols: Card. Layers: ui
- `video/src/components/CodeBlock.tsx`: Defines exported symbols: CodeBlock, c. Layers: ui
- `video/src/components/SceneTransition.tsx`: Defines exported symbols: SceneTransition. Layers: ui
- `video/src/components/Terminal.tsx`: Defines exported symbols: Terminal. Layers: ui
- `video/src/i18n.ts`: Defines exported symbols: STRINGS. Layers: code
- `video/src/index.ts`: Starts a CLI, runtime or package entrypoint. Layers: entrypoint
- `video/src/scenes/BestPractices.tsx`: Defines exported symbols: BestPractices. Layers: code
- `video/src/scenes/Catalog.tsx`: Defines exported symbols: Catalog. Layers: code
- `video/src/scenes/CommitsSkill.tsx`: Defines exported symbols: CommitsSkill. Layers: code
- `video/src/scenes/CreateYourOwn.tsx`: Defines exported symbols: CreateYourOwn. Layers: code
- `video/src/scenes/HowToInvoke.tsx`: Defines exported symbols: HowToInvoke. Layers: code
- `video/src/scenes/Intro.tsx`: Defines exported symbols: Intro. Layers: code
- `video/src/scenes/Outro.tsx`: Defines exported symbols: Outro. Layers: code
- `video/src/scenes/PlaywrightSkill.tsx`: Defines exported symbols: PlaywrightSkill. Layers: code
- `video/src/scenes/WhatAreSkills.tsx`: Defines exported symbols: WhatAreSkills. Layers: code
- `video/src/theme.ts`: Defines exported symbols: fps, theme. Layers: code
- `video/src/why/LangContext.tsx`: Defines exported symbols: WhyLangProvider, useWhyLang, useWhyT. Layers: code
- `video/src/why/WhyLlmProjectMapper.tsx`: Defines exported symbols: WHY_TOTAL_DURATION, WhyLlmProjectMapper, buildCaptionPages. Layers: code
- `video/src/why/audio.ts`: Defines exported symbols: SFX_CUES. Layers: code
- `video/src/why/i18n.ts`: Defines exported symbols: STRINGS_WHY. Layers: code
- `video/src/why/narration.json`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: asset
- `video/src/why/scenes/Anatomy.tsx`: Defines exported symbols: Anatomy. Layers: code
- `video/src/why/scenes/CTA.tsx`: Defines exported symbols: CTA. Layers: code
- `video/src/why/scenes/Hook.tsx`: Defines exported symbols: Hook. Layers: code
- `video/src/why/scenes/MultiAgent.tsx`: Defines exported symbols: MultiAgent. Layers: code
- `video/src/why/scenes/PainList.tsx`: Defines exported symbols: PainList. Layers: code
- `video/src/why/scenes/PainTyping.tsx`: Defines exported symbols: PainTyping. Layers: code
- `video/src/why/scenes/Productivity.tsx`: Defines exported symbols: Productivity. Layers: code
- `video/src/why/scenes/Reveal.tsx`: Defines exported symbols: Reveal. Layers: code
- `video/src/why/scenes/SideBySide.tsx`: Defines exported symbols: SideBySide. Layers: code
- `video/tsconfig.json`: Configures tooling, build, runtime or packaging behavior. Layers: config

## Public Symbols

- `buildCaptionPages`
- `buildCaptions`
- `buildTrack`
- `cueAudioPath`
- `ensureCommand`
- `main`
- `renderCueFiles`
- `run`
- `selectLanguages`
- `totalDurationSeconds`
- `useT`
- `useWhyT`
- `voiceFor`
- `writeCaptions`
