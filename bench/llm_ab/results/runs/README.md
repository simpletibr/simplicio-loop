# Archived benchmark runs

Runs kept as evidence that are outside the release-standard files in `../`: repeated runs, the independent and hard sets, and failed runs. `aggregate.load_history` reads only `../*.json`, so nothing here enters the release-to-release history. The model is `deepseek/deepseek-v4.1-flash` on OpenRouter, the arm `normal` is OpenCode, and the arm `simplicio` is turbo.

In turbo mode the `simplicio` arm is the loop engine calling OpenRouter directly, not OpenCode. See `../../STANDARD.md`.

Cost is the summed per-task cost: the settled ledger cost where available, otherwise computed from tokens.

## Standard set, 3.44.0 vs 3.44.1 (simplicio arm, mean of two runs)

| tasks | wall | cost | reasoning tokens |
|---|---|---|---|
| 1 | 15.5 s → 2.2 s | $0.00280 → $0.00142 | 1,103 → 0 |
| 4 | 17.0 s → 7.7 s | $0.00507 → $0.00247 | 820 → 0 |
| 10 | 54.6 s → 12.0 s | $0.00467 → $0.00381 | 166 → 0 |
| 10 independent (3.44.1) | 5.3 s | $0.00308 | 0 |

Files:
- 3.44.0 run 1: `../2026-09-28-146a6931-t{1,4}.json`; the t10 file is attached to release v3.44.0.
- 3.44.0 run 2: `2026-09-28-v3.44.0-run2/`.
- 3.44.1 run A: `../2026-09-29-790061e2-t{1,4,10,10-ind}.json`.
- 3.44.1 run B: `2026-09-29-v3.44.1-runB/`.

## Hard set, turbo reasoning off vs on (`2026-09-29-hard/`)

Four Python tasks with hidden tests (`--tasks 4 --hard`, loop at `5d11aca9`).

| task | normal, 3 runs | simplicio reasoning off, 3 runs | simplicio reasoning on, 2 valid runs |
|---|---|---|---|
| 1 pricing (half-up rounding) | ✓ ✗ ✓ | ✓ ✓ ✓ | ✓ ✓ |
| 2 inventory bug fix | ✓ ✓ ✓ | ✓ ✓ ✓ | ✓ ✓ |
| 3 two-file refactor | ✓ ✓ ✓ | ✓ ✓ ✓ | ✓ ✓ |
| 4 duration parser | ✓ ✓ ✓ | ✓ ✓ ✓ | ✓ ✗ |
| passed | 11/12 | 12/12 | 7/8 |
| wall, mean | 112.6 s | 5.4 s | 18.1 s / 302.5 s |
| cost, mean | $0.0122 | $0.0027 | $0.0090 / $0.1621 |
| reasoning tokens, mean | 2,485 | 0 | 5,306 / 132,832 |

- `normal` off-2, task 1: half-up rounding was wrong (expected 1703 and 1712, got 1704 and 1713).
- Reasoning-on `on-2`, task 4: one call ran to 131,072 reasoning tokens in 294 s and returned no plan, so `duration.py` was never written.
- `on-3-http402/` and `on-3-rerun-http402/` are invalid runs. The key ran out of credits (HTTP 402), so every call failed. They are kept only as a record.

Decision: turbo keeps reasoning off.
