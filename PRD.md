# PRD — Task-to-execution integrated delivery

## Objective

Execute the planned simplicio-mapper epic (#177) through issues #176-#184 with
six orchestrated subagents, maximum safe parallelism, GPT-5.4 medium through
Simplicio Runtime when the authenticated capability exists, and verified
integration with local LLM, neural memory/database, consciousness, seeds,
skills, and Tokio-backed runtime paths.

## Required outcomes

1. Robust index locks and truthful Runtime capability detection (#176).
2. Deterministic raw-task intake and versioned task schemas (#178).
3. Task-aware, relevance-scored handoff/context packs (#179).
4. Zero-target single-task and multi-task ecosystem integration (#180).
5. AC/RN-to-code/test/receipt traceability (#181).
6. PLANES behavioral corpus and deterministic scorecard (#182).
7. Live cross-repo producer/consumer conformance (#183).
8. Product/template separation and green dogfood drift gates (#184).
9. Simplicio Runtime evidence for GPT-5.4 medium, local LLM, neural memory,
   consciousness, seeds, skills, and Tokio. Missing capabilities are work, not
   implicit success.
10. Six distinct subagents participate. The host concurrency cap is four total
    active agents, so work runs as a continuously fed pool across two waves.

## Completion evidence

- Targeted unit, contract, integration, CLI smoke, and installed-package tests.
- PLANES task succeeds without a manually supplied target or abstains with an
  explicit evidence-backed reason.
- Cross-repo conformance uses real producer outputs.
- Runtime capabilities are exercised, not inferred from file presence.
- `sync --check` and `drift --check` pass for the product scope.
- GitHub issues are closed only after live evidence and delivery state agree.

## Safety

- Preserve existing user changes and do not overwrite unrelated dirty files.
- Do not add dependencies without explicit user approval.
- No false completion promise; unknown or unavailable capabilities stay open.
