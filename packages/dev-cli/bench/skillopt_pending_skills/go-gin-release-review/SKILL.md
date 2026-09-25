---
name: go-gin-release-review
description: Review Go Gin CRUD release evidence before human approval.
trigger: Use when a human must review evidence for a Go Gin CRUD release before closure or publication.
auto_generated:
  by: skill-opt
  date: 2026-05-31
  source_goal: Create skill go-gin-release-review for human review of Go Gin CRUD release evidence.
  planner_model: codex-cli/default
  review_required: true
---

# go-gin-release-review

## When to use
Use this skill to perform a human-facing release evidence review for a Go Gin CRUD implementation. It applies when the implementation is already produced and the reviewer must decide whether the submitted evidence is sufficient to approve release, merge, closure, or publication.

## Steps
1. Identify the release scope: task, PR, resource name, CRUD endpoints, acceptance criteria, and expected release artifact.
2. Confirm the project is a Go Gin service and the evidence matches the actual route handlers, models, persistence layer, and configuration used by the release.
3. Review validation evidence for reproducible commands: build, lint or static checks, unit tests, integration tests, and any release-specific smoke command.
4. Verify CRUD coverage from evidence, including create, list, read by id, update, delete, not found, and invalid payload scenarios.
5. Check that request and response evidence includes method, path, status code, payload, and enough body content to prove the behavior.
6. Confirm persistence evidence uses a real local or test database path, not hardcoded responses, fake-only mocks, or screenshots without command output.
7. Inspect release hygiene: no secrets, no stray debug logs, documented environment variables, migration or seed steps when applicable, and clear rollback or cleanup notes.
8. Produce a review verdict: approved, approved with notes, or changes requested, listing missing or weak evidence as concrete blocking items.

## DoD
- [ ] Task or acceptance criteria are mapped to specific evidence artifacts.
- [ ] Go Gin build and test commands are present with pass/fail output.
- [ ] Every CRUD operation has request and response evidence.
- [ ] At least one validation or bad-request scenario is evidenced.
- [ ] At least one not-found or deleted-resource scenario is evidenced.
- [ ] Evidence demonstrates real persistence behavior.
- [ ] Release notes, version, PR, or closure reference are checked when applicable.
- [ ] Final human review verdict is explicit and actionable.

## Anti-patterns
- Approving based only on a summary without raw command or HTTP evidence.
- Treating unit tests as enough when release criteria require live CRUD behavior.
- Accepting screenshots that omit URL, method, status code, or response body.
- Ignoring missing migrations, seed data, or environment setup needed to reproduce the evidence.
- Approving evidence from mocked handlers when the release claims real persistence.
- Requesting implementation changes during review without tying them to a missing release criterion.
