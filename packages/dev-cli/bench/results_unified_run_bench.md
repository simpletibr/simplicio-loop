# Unified Run F5 Bench Fixture

planned fixture comparison for cli+ag, unified feature/sprint, and Codex /goal; fixture rows are replaced by live rows when --live-results-json supplies comparable evidence

## Summary

- issue: #41
- phase: F5
- fixture only: False
- evidence level: live
- cases: 3
- modes: 4
- rows: 12/12
- release ready: True
- ready for live run: True
- live rows: 12/12

## Modes

| mode | entrypoint | decomposition | replan | cost visibility |
| --- | --- | --- | --- | --- |
| cli+ag task loop | `simplicio-py task` | human | none | per atomic task |
| unified run feature | `simplicio-py run --scope feature` | planner | remaining feature tasks | cost governor |
| unified run sprint | `simplicio-py run --scope sprint --max-cost <usd>` | sprint loader and planner | feature tasks inside sprint | required cost governor |
| Codex /goal | `codex /goal` | external agent | opaque | opaque in this repo bench |

## Fixture Matrix

| case | scope | mode | outcome | task runs | planner calls | manual split | replan | cost observable |
| --- | --- | --- | --- | ---: | ---: | --- | --- | --- |
| single-file-task | task | cli+ag task loop | live_success | 1 | 0 | False | False | True |
| single-file-task | task | unified run feature | live_success | 1 | 0 | False | False | True |
| single-file-task | task | unified run sprint | live_success | 1 | 0 | False | False | True |
| single-file-task | task | Codex /goal | live_success | 1 | 0 | False | True | False |
| feature-auth-flow | feature | cli+ag task loop | live_success | 4 | 0 | True | False | True |
| feature-auth-flow | feature | unified run feature | live_success | 4 | 1 | False | True | True |
| feature-auth-flow | feature | unified run sprint | live_success | 4 | 0 | False | False | True |
| feature-auth-flow | feature | Codex /goal | live_success | 4 | 0 | False | True | False |
| sprint-checkout-hardening | sprint | cli+ag task loop | live_success | 7 | 0 | True | False | True |
| sprint-checkout-hardening | sprint | unified run feature | live_success | 7 | 2 | True | True | True |
| sprint-checkout-hardening | sprint | unified run sprint | live_success | 7 | 2 | False | True | True |
| sprint-checkout-hardening | sprint | Codex /goal | live_success | 7 | 0 | False | True | False |
