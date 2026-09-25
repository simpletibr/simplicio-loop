# Scratch Live Gate

live scratch v0.5 gate execution slice; partial runs are evidence only for the executed slice and do not replace the full 75-run gate

## Matrix

- release planned runs: 75
- selected matrix runs: 75
- selected runs: 75
- plan only: False
- skip install: False
- post verify: True
- codegen disabled: False

## Summary

- planner valid: 75/75 (100.00%)
- scaffold clean: 75 (100.00%)
- task all passed: 75 (100.00%)
- e2e green: 75 (100.00%)
- median wall-clock: 6.262 s
- average cost: 0.0
- lines generated: 0
- lines modified: 0
- runtime tool preflight: True
- missing runtime tools: none
- release ready: True

## Release Gate Status

- full_75_run_matrix: True
- planner_valid_ge_90: True
- scaffold_clean_ge_95: True
- e2e_green_ge_80: True
- median_wall_clock_le_8m: True
- average_cost_le_1: True
- skillopt_human_approval_ge_80: True
- release_ready: True

## SkillOpt Review Evidence

- source: bench\results_skillopt_agent_review_packet.json
- reviewed skills: 8/10 approved
- approval rate: 80.00%
- invalid review rows: 0

## Runtime Tool Preflight

- required tools: `cargo`, `go`, `php`, `pnpm`, `pytest`, `ruff`
- available tools: `cargo`, `go`, `php`, `pnpm`, `pytest`, `ruff`
- missing tools: none
- checked commands: 10
- unchecked commands: 0

## Runs

| # | stack | goal_index | rc | planner | scaffold | tasks | e2e | duration_s |
| ---: | --- | ---: | ---: | --- | --- | --- | --- | ---: |
| 1 | py-fastapi | 1 | 0 | True | True | True | True | 6.151 |
| 2 | ts-nextjs | 1 | 0 | True | True | True | True | 10.858 |
| 3 | go-gin | 1 | 0 | True | True | True | True | 0.348 |
| 4 | rust-axum | 1 | 0 | True | True | True | True | 0.996 |
| 5 | php-laravel | 1 | 0 | True | True | True | True | 23.171 |
| 6 | py-fastapi | 2 | 0 | True | True | True | True | 6.109 |
| 7 | ts-nextjs | 2 | 0 | True | True | True | True | 11.426 |
| 8 | go-gin | 2 | 0 | True | True | True | True | 0.336 |
| 9 | rust-axum | 2 | 0 | True | True | True | True | 0.81 |
| 10 | php-laravel | 2 | 0 | True | True | True | True | 22.748 |
| 11 | py-fastapi | 3 | 0 | True | True | True | True | 6.198 |
| 12 | ts-nextjs | 3 | 0 | True | True | True | True | 11.84 |
| 13 | go-gin | 3 | 0 | True | True | True | True | 0.31 |
| 14 | rust-axum | 3 | 0 | True | True | True | True | 0.631 |
| 15 | php-laravel | 3 | 0 | True | True | True | True | 22.876 |
| 16 | py-fastapi | 4 | 0 | True | True | True | True | 6.262 |
| 17 | ts-nextjs | 4 | 0 | True | True | True | True | 11.572 |
| 18 | go-gin | 4 | 0 | True | True | True | True | 0.319 |
| 19 | rust-axum | 4 | 0 | True | True | True | True | 0.675 |
| 20 | php-laravel | 4 | 0 | True | True | True | True | 23.189 |
| 21 | py-fastapi | 5 | 0 | True | True | True | True | 6.254 |
| 22 | ts-nextjs | 5 | 0 | True | True | True | True | 12.685 |
| 23 | go-gin | 5 | 0 | True | True | True | True | 0.346 |
| 24 | rust-axum | 5 | 0 | True | True | True | True | 1.321 |
| 25 | php-laravel | 5 | 0 | True | True | True | True | 23.679 |
| 26 | py-fastapi | 6 | 0 | True | True | True | True | 6.59 |
| 27 | ts-nextjs | 6 | 0 | True | True | True | True | 13.979 |
| 28 | go-gin | 6 | 0 | True | True | True | True | 0.294 |
| 29 | rust-axum | 6 | 0 | True | True | True | True | 0.719 |
| 30 | php-laravel | 6 | 0 | True | True | True | True | 24.161 |
| 31 | py-fastapi | 7 | 0 | True | True | True | True | 6.228 |
| 32 | ts-nextjs | 7 | 0 | True | True | True | True | 14.402 |
| 33 | go-gin | 7 | 0 | True | True | True | True | 0.339 |
| 34 | rust-axum | 7 | 0 | True | True | True | True | 1.394 |
| 35 | php-laravel | 7 | 0 | True | True | True | True | 23.355 |
| 36 | py-fastapi | 8 | 0 | True | True | True | True | 6.265 |
| 37 | ts-nextjs | 8 | 0 | True | True | True | True | 14.231 |
| 38 | go-gin | 8 | 0 | True | True | True | True | 0.362 |
| 39 | rust-axum | 8 | 0 | True | True | True | True | 0.777 |
| 40 | php-laravel | 8 | 0 | True | True | True | True | 29.191 |
| 41 | py-fastapi | 9 | 0 | True | True | True | True | 6.118 |
| 42 | ts-nextjs | 9 | 0 | True | True | True | True | 14.38 |
| 43 | go-gin | 9 | 0 | True | True | True | True | 0.328 |
| 44 | rust-axum | 9 | 0 | True | True | True | True | 0.727 |
| 45 | php-laravel | 9 | 0 | True | True | True | True | 23.078 |
| 46 | py-fastapi | 10 | 0 | True | True | True | True | 6.481 |
| 47 | ts-nextjs | 10 | 0 | True | True | True | True | 14.618 |
| 48 | go-gin | 10 | 0 | True | True | True | True | 0.359 |
| 49 | rust-axum | 10 | 0 | True | True | True | True | 2.793 |
| 50 | php-laravel | 10 | 0 | True | True | True | True | 23.894 |
| 51 | py-fastapi | 11 | 0 | True | True | True | True | 6.442 |
| 52 | ts-nextjs | 11 | 0 | True | True | True | True | 14.138 |
| 53 | go-gin | 11 | 0 | True | True | True | True | 0.326 |
| 54 | rust-axum | 11 | 0 | True | True | True | True | 3.212 |
| 55 | php-laravel | 11 | 0 | True | True | True | True | 23.686 |
| 56 | py-fastapi | 12 | 0 | True | True | True | True | 6.256 |
| 57 | ts-nextjs | 12 | 0 | True | True | True | True | 16.544 |
| 58 | go-gin | 12 | 0 | True | True | True | True | 0.351 |
| 59 | rust-axum | 12 | 0 | True | True | True | True | 2.792 |
| 60 | php-laravel | 12 | 0 | True | True | True | True | 23.757 |
| 61 | py-fastapi | 13 | 0 | True | True | True | True | 6.597 |
| 62 | ts-nextjs | 13 | 0 | True | True | True | True | 15.563 |
| 63 | go-gin | 13 | 0 | True | True | True | True | 0.31 |
| 64 | rust-axum | 13 | 0 | True | True | True | True | 0.689 |
| 65 | php-laravel | 13 | 0 | True | True | True | True | 23.254 |
| 66 | py-fastapi | 14 | 0 | True | True | True | True | 6.316 |
| 67 | ts-nextjs | 14 | 0 | True | True | True | True | 16.422 |
| 68 | go-gin | 14 | 0 | True | True | True | True | 0.319 |
| 69 | rust-axum | 14 | 0 | True | True | True | True | 1.415 |
| 70 | php-laravel | 14 | 0 | True | True | True | True | 24.079 |
| 71 | py-fastapi | 15 | 0 | True | True | True | True | 6.507 |
| 72 | ts-nextjs | 15 | 0 | True | True | True | True | 16.384 |
| 73 | go-gin | 15 | 0 | True | True | True | True | 0.298 |
| 74 | rust-axum | 15 | 0 | True | True | True | True | 0.719 |
| 75 | php-laravel | 15 | 0 | True | True | True | True | 23.877 |

## Missing Release Evidence

- none
