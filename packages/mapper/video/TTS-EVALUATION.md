# TTS Evaluation

Issue `#56` asked for a practical evaluation of the three hosted TTS providers that best fit the `why-llm-project-mapper` video pipeline.

## Quick comparison

| Provider | Strengths | Trade-offs | Fit for this repo |
|---|---|---|---|
| ElevenLabs | Best voice realism, strong emotional delivery, broad voice cloning options | Highest recurring cost, another vendor account, caption timing still needs a custom pipeline | Best for polished marketing exports when budget is available |
| OpenAI `tts-1-hd` | Good quality, simple API, fast developer ergonomics, easier automation than marketplace tools | Requires API key, per-character cost, still external to local validation | Best hosted upgrade path for this repo if secrets are available |
| Azure Neural | Broad enterprise voice catalog, governance/compliance story, SSML control | Heavier setup, Azure subscription complexity, slower to onboard for a tiny media repo | Best for organizations already standardized on Azure |

## Decision for this repository

For the repo-local implementation, the narration pipeline uses macOS `say` plus `ffmpeg` and checks the generated assets into `video/public/voice/`.

Why this path was chosen now:

- No new npm dependency
- No secret or paid account required
- Fully reproducible local validation on this machine
- Keeps the Remotion composition and captions pipeline inside the repository

## Recommended future upgrade

If hosted TTS credentials become available, `OpenAI tts-1-hd` is the cleanest upgrade path for this repo:

1. Keep `video/src/why/narration.json` as the single source of truth.
2. Swap the synthesis step in `video/scripts/generate-why-voiceover.mjs`.
3. Regenerate `video/public/voice/why-{pt,en}.m4a`.
4. Re-render `video/assets/why-llm-project-mapper{,-en}.mp4`.
