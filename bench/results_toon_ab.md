# TOON A/B — mapper context path (issue #85 AC3 / #88 AC2)

Estimator: `observability.estimate_tokens (words*4/3)` (issue #88 AC4 — single canonical estimator).

build_mapper_context() driven end-to-end with SIMPLICIO_PROMPT_TOON=0/1, map_handoff() monkeypatched to a representative (non-live-captured) simplicio.map-handoff/v1 pack per case target — isolates the handoff-path TOON gate fixed in #88 from mapper-binary availability.

| Case | Target | Legacy tokens | TOON tokens | Saved | % saved |
|---|---|---|---|---|---|
| hide the Delete button when the user is not admi | src/app/screen/screen.component.html | 52 | 38 | 14 | 26.92% |
| enable the email field only for the editor profi | src/app/profile/profile.component.html | 52 | 38 | 14 | 26.92% |
| **Total** |  | **104** | **76** | **28** | **26.92%** |
