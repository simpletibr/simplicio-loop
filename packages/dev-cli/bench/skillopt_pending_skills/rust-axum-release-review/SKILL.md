---
name: rust-axum-release-review
description: Human review checklist for Rust Axum CRUD release evidence.
trigger: Use when a human must validate evidence for a Rust Axum CRUD release before approval.
auto_generated:
  by: skill-opt
  date: 2026-05-31
  source_goal: Create skill rust-axum-release-review for human review of Rust Axum CRUD release evidence.
  planner_model: codex-cli/default
  review_required: true
---

# rust-axum-release-review

## When to use

Use this skill when reviewing release evidence for a Rust Axum CRUD implementation, especially before approving an issue closure, merge, deployment, or release note that claims CRUD readiness.

## Steps

1. Confirm the reviewed evidence matches the target Rust Axum CRUD scope, including entity names, endpoints, persistence layer, migrations, validation rules, and release version or issue ID.
2. Verify that required release commands were run from a clean checkout and their outputs are attached or referenced, including `cargo fmt --check`, `cargo clippy`, `cargo test`, and the project build command.
3. Inspect CRUD behavior evidence for create, read/list, read/detail, update, delete, not-found, validation-error, and persistence-after-restart scenarios.
4. Check API evidence for correct HTTP methods, paths, status codes, response shapes, error bodies, and database side effects.
5. Review migration and configuration evidence to ensure the release can be reproduced without hidden local state, secrets, manual database edits, or undocumented environment assumptions.
6. Compare the evidence against the acceptance criteria and mark each item as proven, missing, ambiguous, or failed.
7. Request a rerun or additional artifacts when logs are truncated, commands are missing, screenshots do not prove behavior, or evidence cannot be tied to the claimed commit/version.
8. Record the final human review decision as approved, approved with notes, or rejected with concrete missing evidence.

## DoD

- [ ] Target issue, release, commit, and Rust Axum CRUD scope are identified.
- [ ] Formatting, linting, tests, and build evidence are present and passing.
- [ ] CRUD happy paths are evidenced end to end.
- [ ] Error paths and edge cases are evidenced.
- [ ] Database migration and persistence evidence is sufficient.
- [ ] API status codes, payloads, and validation behavior match expectations.
- [ ] No evidence depends on secrets, hidden local state, or unverifiable manual steps.
- [ ] Human review decision is recorded with clear approval or rejection rationale.

## Anti-patterns

- Approving from a summary without inspecting attached logs or artifacts.
- Treating unit tests alone as proof of release-ready CRUD behavior.
- Accepting screenshots that do not show request inputs, outputs, or identifiers.
- Ignoring failed, skipped, or truncated validation commands.
- Approving evidence from a different commit, branch, entity, or release version.
- Assuming database migrations work without explicit migration or fresh-database evidence.
- Marking ambiguous evidence as passed instead of requesting a targeted rerun.
