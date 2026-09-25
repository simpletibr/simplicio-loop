# Scratch Planner Cache Gate

cold/warm scratch planner cache measurement; this proves planner cache replay for identical prompts. Optional live-gate input links the cache evidence to the shared real scratch release corpus without overstating the cold/warm sample size.

## Summary

- goals: 50
- cold valid plans: 50
- warm valid plans: 50
- warm cache hit-rate: 100.00%
- warm hits/misses: 50/0
- cold cache puts: 50
- selected corpus goals: 50/50
- merged slices: 12

## Live Corpus Link

- source: bench/results_scratch_live_gate.json
- runs: 75
- e2e green: 75
- e2e green rate: 100.00%
- stacks: go-gin, php-laravel, py-fastapi, rust-axum, ts-nextjs

## Release Gate Status

- warm_hit_rate_ge_80: True
- warm_plans_all_valid: True
- cold_populated_cache: True
- real_50_scratch_corpus: True
- cold_warm_measured_on_50_real_scratches: True

## Warm Cases

| goal | passed | tasks | duration_ms |
| --- | --- | ---: | ---: |
| Build a FastAPI audit log service with export filters and retention policy | True | 20 | 3 |
| Build a FastAPI feature flag service with rollout rules and audit trail | True | 28 | 2 |
| Build a FastAPI webhook ingestion service with replay controls | True | 30 | 3 |
| Build a FastAPI data export service with signed download links | True | 36 | 2 |
| Build a FastAPI notification preference service with channel rules | True | 27 | 5 |
| Build a FastAPI incident escalation service with severity routing | True | 28 | 3 |
| Build a FastAPI maintenance scheduling service with recurring windows | True | 30 | 3 |
| Build a FastAPI resident profile merge service with conflict reports | True | 32 | 2 |
| Build a FastAPI document indexing service with access policy checks | True | 44 | 3 |
| Build a FastAPI visitor preapproval service with expiry reminders | True | 29 | 2 |
| Build a FastAPI package pickup workflow with identity verification | True | 35 | 3 |
| Build a FastAPI payment reconciliation service with exception queues | True | 29 | 2 |
| Build a FastAPI amenity capacity service with blackout dates | True | 38 | 2 |
| Build a FastAPI parking allocation service with waitlist promotion | True | 33 | 2 |
| Build a FastAPI vendor insurance tracker with renewal alerts | True | 25 | 4 |
| Build a FastAPI board vote recording service with quorum rules | True | 25 | 2 |
| Build a FastAPI announcement targeting service with audience segments | True | 31 | 2 |
| Build a FastAPI key fob lifecycle service with revocation audits | True | 28 | 2 |
| Build a FastAPI work order triage service with SLA timers | True | 35 | 3 |
| Build a FastAPI occupancy analytics service with monthly summaries | True | 26 | 2 |
| Build a FastAPI service request intake flow with duplicate detection | True | 21 | 2 |
| Build a FastAPI lease compliance service with document reminders | True | 24 | 3 |
| Build a FastAPI inspection checklist service with photo evidence slots | True | 26 | 3 |
| Build a FastAPI utility meter ingestion service with anomaly flags | True | 25 | 3 |
| Build a FastAPI budget variance service with approval thresholds | True | 37 | 3 |
| Build a FastAPI invoice dispute workflow with reviewer assignment | True | 18 | 2 |
| Build a FastAPI procurement quote comparison service with scoring | True | 34 | 3 |
| Build a FastAPI security patrol log service with geofence events | True | 38 | 2 |
| Build a FastAPI elevator outage notification service with ETA updates | True | 25 | 2 |
| Build a FastAPI pool access rule service with seasonal schedules | True | 43 | 2 |
| Build a FastAPI guest parking permit service with plate validation | True | 15 | 2 |
| Build a FastAPI storage locker assignment service with waitlist rules | True | 33 | 2 |
| Build a FastAPI pet registration service with vaccine reminders | True | 16 | 2 |
| Build a FastAPI move-in coordination service with deposit tracking | True | 31 | 2 |
| Build a FastAPI architectural request review service with attachments | True | 21 | 2 |
| Build a FastAPI violation notice workflow with appeal deadlines | True | 21 | 2 |
| Build a FastAPI insurance claim tracker with status milestones | True | 27 | 2 |
| Build a FastAPI emergency contact broadcast service with opt-out rules | True | 36 | 3 |
| Build a FastAPI reserve study task service with funding categories | True | 16 | 2 |
| Build a FastAPI janitorial route tracker with completion evidence | True | 14 | 2 |
| Build a FastAPI landscaping issue queue with seasonal priorities | True | 22 | 2 |
| Build a FastAPI snow removal dispatch service with weather holds | True | 47 | 2 |
| Build a FastAPI energy usage report service with building comparisons | True | 32 | 3 |
| Build a FastAPI noise complaint workflow with quiet-hour policies | True | 23 | 3 |
| Build a FastAPI access camera incident log with retention controls | True | 25 | 3 |
| Build a FastAPI owner portal preference service with language settings | True | 14 | 2 |
| Build a FastAPI meeting agenda builder with attachment ordering | True | 28 | 2 |
| Build a FastAPI contractor onboarding service with credential checks | True | 27 | 2 |
| Build a FastAPI warranty inventory service with expiration alerts | True | 22 | 3 |
| Build a FastAPI recurring assessment calculator with proration rules | True | 25 | 3 |
