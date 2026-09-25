---
name: laravel-api-crud-scaffold-review
description: Review Laravel API CRUD scaffold release evidence for routes, JSON codes, tests, and Pint.
trigger: Use when reviewing release evidence for a Laravel API CRUD scaffold before merge, release, or handoff.
auto_generated:
  by: skill-opt
  date: 2026-05-31
  source_goal: Generate a release-evidence reviewer checklist for Laravel API CRUD scaffolds, including route tests, JSON status codes, and Pint expectations.
  planner_model: codex-cli/default
  review_required: true
---

# laravel-api-crud-scaffold-review

## When to use
Use this skill when validating a Laravel API CRUD scaffold and its release evidence. It applies to generated or hand-written resources with API routes, controllers, requests, resources, policies, migrations, factories, and feature tests.

## Steps
1. Identify the scaffolded resource and confirm the expected CRUD surface: `index`, `store`, `show`, `update`, and `destroy`.
2. Verify `routes/api.php` or route registration defines the intended API routes, names, middleware, and model binding.
3. Capture route evidence with `php artisan route:list` or the project-approved equivalent, filtered to the scaffolded resource when possible.
4. Review feature or route tests for every CRUD route, including happy paths, validation failures, missing records, and auth or authorization cases when applicable.
5. Confirm JSON response expectations use explicit status codes: `200` for read/update success, `201` for create, `204` for delete with no body, `404` for missing records, `422` for validation, and `401` or `403` for protected flows.
6. Check that tests assert response JSON shape, persisted database state, validation error keys, and deletion behavior rather than only checking status codes.
7. Run the relevant Laravel test command, such as `php artisan test` or the narrowest project-approved filter, and save the command plus result excerpt as release evidence.
8. Run Pint in check mode, usually `./vendor/bin/pint --test` or the project-approved wrapper, and record the result.
9. Inspect the implementation for scaffold shortcuts: missing FormRequest validation, unsafe mass assignment, inconsistent API resources, unhandled authorization, or controller logic that bypasses domain conventions.
10. Record blockers with exact command, failing excerpt, affected route or test, and likely cause.

## DoD
- [ ] CRUD API routes are present, named or discoverable, and covered by route evidence.
- [ ] Route tests cover success, validation, missing resource, delete, and protected-path behavior where applicable.
- [ ] JSON status codes are explicit and match Laravel API expectations.
- [ ] JSON body, error shape, and database assertions are checked in tests.
- [ ] `php artisan test` or the scoped approved test command passes.
- [ ] Pint check passes with `./vendor/bin/pint --test` or the project wrapper.
- [ ] Release evidence includes commands run, relevant output excerpts, and any artifact paths.
- [ ] Any blocker is documented with command, log excerpt, and likely cause.

## Anti-patterns
- Approving a scaffold because the controller exists without verifying registered routes.
- Testing only `200` responses while skipping `201`, `204`, `404`, `422`, `401`, or `403`.
- Using broad smoke tests that do not assert JSON shape or database state.
- Treating Pint auto-fix as evidence without also running Pint in check mode.
- Ignoring route middleware, policies, validation requests, or model binding behavior.
- Reporting "tests pass" without the exact command and output excerpt.
