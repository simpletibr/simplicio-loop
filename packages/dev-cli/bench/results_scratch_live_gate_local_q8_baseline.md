# Scratch Live Gate

live scratch v0.5 gate execution slice; partial runs are evidence only for the executed slice and do not replace the full 75-run gate

## Matrix

- release planned runs: 75
- selected matrix runs: 75
- selected runs: 12
- plan only: False
- skip install: False
- post verify: True
- codegen disabled: True

## Summary

- planner valid: 0/12 (0.00%)
- scaffold clean: 0 (0.00%)
- task all passed: 0 (0.00%)
- e2e green: 0 (0.00%)
- median wall-clock: 3.083 s
- average cost: None
- lines generated: 0
- lines modified: 0
- runtime tool preflight: True
- missing runtime tools: `cargo`
- release ready: False

## Release Gate Status

- full_75_run_matrix: False
- planner_valid_ge_90: False
- scaffold_clean_ge_95: False
- e2e_green_ge_80: None
- median_wall_clock_le_8m: True
- average_cost_le_1: None
- skillopt_human_approval_ge_80: False
- release_ready: False

## SkillOpt Review Evidence

- source: inline
- reviewed skills: 0/0 approved
- approval rate: 0.00%
- invalid review rows: 0

## Runtime Tool Preflight

- required tools: `cargo`, `go`, `php`, `pnpm`, `pytest`, `ruff`
- available tools: `go`, `php`, `pnpm`, `pytest`, `ruff`
- missing tools: `cargo`
- checked commands: 10
- unchecked commands: 0

## Runs

| # | stack | goal_index | rc | planner | scaffold | tasks | e2e | duration_s |
| ---: | --- | ---: | ---: | --- | --- | --- | --- | ---: |
| 1 | py-fastapi | 1 | 1 | False | None | False | None | 1.178 |
| 2 | ts-nextjs | 1 | 1 | False | None | False | None | 21.452 |
| 3 | go-gin | 1 | 1 | False | None | False | None | 0.988 |
| 4 | rust-axum | 1 | 1 | False | None | False | None | 1.075 |
| 5 | php-laravel | 1 | 1 | False | None | False | None | 8.978 |
| 6 | py-fastapi | 2 | 1 | False | None | False | None | 6.252 |
| 7 | ts-nextjs | 2 | 1 | False | None | False | None | 32.462 |
| 8 | go-gin | 2 | 1 | False | None | False | None | 0.547 |
| 9 | rust-axum | 2 | 1 | False | None | False | None | 0.234 |
| 10 | php-laravel | 2 | 1 | False | None | False | None | 4.987 |
| 11 | py-fastapi | 3 | 1 | False | None | False | None | 0.615 |
| 12 | ts-nextjs | 3 | 1 | False | None | False | None | 10.068 |

## Missing Release Evidence

- full 15 goals x 5 pilot stacks live matrix
- average cost measurement
- SkillOpt human approval evidence >=80%
