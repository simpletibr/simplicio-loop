# Scratch Live Gate

live scratch v0.5 gate execution slice; partial runs are evidence only for the executed slice and do not replace the full 75-run gate

## Matrix

- release planned runs: 75
- selected matrix runs: 10
- selected runs: 10
- plan only: False
- skip install: False
- post verify: True
- codegen disabled: True

## Summary

- planner valid: 7/10 (70.00%)
- scaffold clean: 7 (100.00%)
- task all passed: 5 (50.00%)
- e2e green: 5 (71.43%)
- median wall-clock: 262.135 s
- average cost: None
- lines generated: 6914
- lines modified: 2
- runtime tool preflight: True
- missing runtime tools: none
- release ready: False

## Release Gate Status

- full_75_run_matrix: False
- planner_valid_ge_90: False
- scaffold_clean_ge_95: True
- e2e_green_ge_80: False
- median_wall_clock_le_8m: True
- average_cost_le_1: None
- skillopt_human_approval_ge_80: True
- release_ready: False

## SkillOpt Review Evidence

- source: bench\results_skillopt_agent_review_packet.json
- reviewed skills: 8/10 approved
- approval rate: 80.00%
- invalid review rows: 0

## Runtime Tool Preflight

- required tools: `cargo`, `go`, `pnpm`, `pytest`, `ruff`
- available tools: `cargo`, `go`, `pnpm`, `pytest`, `ruff`
- missing tools: none
- checked commands: 8
- unchecked commands: 0

## Runs

| # | stack | goal_index | rc | planner | scaffold | tasks | e2e | duration_s |
| ---: | --- | ---: | ---: | --- | --- | --- | --- | ---: |
| 1 | py-fastapi | 1 | None | False | None | False | None | 900.047 |
| 2 | ts-nextjs | 1 | 0 | True | True | True | True | 491.943 |
| 3 | go-gin | 1 | 0 | True | True | True | True | 204.707 |
| 4 | rust-axum | 1 | 1 | False | None | False | None | 436.272 |
| 5 | ts-nextjs | 2 | 0 | True | True | True | True | 262.791 |
| 6 | go-gin | 2 | 1 | True | True | False | False | 262.135 |
| 7 | go-gin | 3 | 1 | True | True | False | False | 393.191 |
| 8 | go-gin | 4 | 0 | True | True | True | True | 98.077 |
| 9 | go-gin | 5 | 0 | True | True | True | True | 136.973 |
| 10 | go-gin | 6 | 4 | False | None | False | None | 0.414 |

## Missing Release Evidence

- full 15 goals x 5 pilot stacks live matrix
- average cost measurement
