# Scratch Release Gate Preflight

preflight for the live scratch v0.5 release gate; does not replace credentialed planner/doer execution

## Gate

- goals: 15
- pilot stacks: 5
- planned runs: 75
- planner valid minimum: 90%
- scaffold clean minimum: 95%
- e2e green minimum: 80%
- median wall-clock maximum: 8 min
- average cost maximum: $1.00

## Readiness

- ready for live gate: True
- blocker count: 0

## Stacks

| stack | present | missing tools |
| --- | --- | --- |
| py-fastapi | True | - |
| ts-nextjs | True | - |
| go-gin | True | - |
| rust-axum | True | - |
| php-laravel | True | - |

## Goals

- CRUD app for condo units with owner contact search
- CRUD app for invoices with paid and overdue filters
- CRUD app for maintenance tickets with assignee status
- CRUD app for visitors with check-in and check-out timestamps
- CRUD app for amenity bookings with date conflict checks
- CRUD app for announcements with publish and archive state
- CRUD app for documents with category filtering
- CRUD app for vendors with active contract tracking
- CRUD app for inventory items with low-stock flag
- CRUD app for package deliveries with resident pickup
- CRUD app for parking spaces with vehicle assignment
- CRUD app for board meetings with minutes status
- CRUD app for access devices with revocation state
- CRUD app for payments with receipt reference
- CRUD app for service requests with priority queue
