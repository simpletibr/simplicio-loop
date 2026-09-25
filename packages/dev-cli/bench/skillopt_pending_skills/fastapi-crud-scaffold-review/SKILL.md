---
name: fastapi-crud-scaffold-review
description: Validate generated FastAPI CRUD scaffolds before they enter release evidence.
trigger: Use when reviewing generated FastAPI CRUD code, tests, or docs before accepting it as release evidence.
auto_generated:
  by: skill-opt
  date: 2026-05-31
  source_goal: "Generate a focused review checklist for validating generated FastAPI CRUD scaffolds before accepting them into release evidence."
  planner_model: codex-cli/default
  review_required: true
---

# fastapi-crud-scaffold-review

## When to use
Use this skill before accepting generated FastAPI CRUD scaffolds as release evidence, especially when code was produced by an agent, template, or generator and must be trusted for a release decision.

## Steps
1. Confirm the scaffold targets the correct entity, routes, schemas, database model, service layer, and repository/session pattern for the project.
2. Verify CRUD behavior end to end: create, read one, list, update, partial update if supported, delete, not-found, duplicate/conflict, and validation failure paths.
3. Check FastAPI contracts: path prefixes, HTTP methods, status codes, response models, request schemas, dependency injection, tags, and OpenAPI output.
4. Review data safety: auth dependencies, authorization boundaries, tenant/user scoping, soft-delete rules, unique constraints, transactions, and rollback behavior.
5. Inspect schema/model consistency: Pydantic fields, required/optional defaults, ORM mapping, migrations, enum handling, timestamps, IDs, and serialization.
6. Validate error handling: no raw tracebacks, stable error shapes, correct 4xx/5xx use, and no leakage of secrets or internal database details.
7. Run the smallest relevant automated checks: unit tests, API tests, lint/type checks, and any migration or OpenAPI generation checks used by the repo.
8. Exercise the generated endpoints manually or with an API client when evidence requires runtime proof, including one happy path, one edge case, and one error path.
9. Review release evidence for completeness: exact commands, outputs, screenshots/logs if applicable, artifact paths, commit hash, environment, and known limitations.
10. Reject or send back for fixes if any generated code is unused, untested, unsafe by default, inconsistent with project patterns, or unsupported by reproducible evidence.

## DoD
- [ ] Every generated CRUD endpoint maps to the intended domain behavior and project conventions.
- [ ] Happy path, edge case, and error path behavior were validated.
- [ ] Auth, authorization, tenant scoping, and data safety rules were explicitly checked.
- [ ] Schemas, ORM models, migrations, and response contracts are consistent.
- [ ] Automated validation commands ran and their outputs are captured in release evidence.
- [ ] Release evidence includes enough detail for an independent reviewer to reproduce the result.
- [ ] Any accepted limitation is documented with impact, owner, and follow-up path.

## Anti-patterns
- Accepting scaffolded CRUD because it compiles without testing runtime behavior.
- Treating generated OpenAPI output as proof that authorization and data rules are correct.
- Ignoring delete, not-found, duplicate, pagination, and validation failure paths.
- Hiding generator mistakes behind broad mocks or tests that only assert status codes.
- Accepting release evidence that omits commands, environment, artifact paths, or failed checks.
