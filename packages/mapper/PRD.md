# PRD — GitHub issue #320 release quality gate

## Objective

Make the internal-JSON migration release-blocking and require reproducible,
explicit evidence for binary-format interoperability before publication.

## Acceptance focus for this checkout

1. Preserve the exact, dated TOML exception registry and baseline scanner.
2. Reject every owned internal JSON artifact in release/strict mode.
3. Require observed cross-repository E2E, performance, HBP receipt, and HBI
   conformance evidence; missing evidence must remain `null` and block release.
4. Produce a Markdown-only report safe for arbitrary command output.
5. Keep npm publication behind the fail-closed gate.
6. Record focused unit, integration, system, regression, package, performance,
   lint, and coverage evidence available in Codex Cloud.

## External completion dependencies

The remaining repository-wide migration depends on conformant Runtime HBI/HBP
contracts and released adjacent consumers. The gate must not claim those
criteria pass while those capabilities or observations are unavailable.
