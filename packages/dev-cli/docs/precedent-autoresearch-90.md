# Autoresearch run — `build_precedent_block()` (issue #90)

Real run of the `simplicio-autoresearch` worker (`simplicio-loop#95`,
`scripts/autoresearch.py`) against `simplicio/precedent.py::build_precedent_block()`,
using the harness in `bench/precedent_autoresearch_*.py`.

## Result

| | score cases (avg tokens) | holdout cases (avg tokens, never seen by the loop) |
|---|---|---|
| baseline | 34.3333 | 29.5000 |
| final    | 20.3333 | 15.5000 |
| reduction | 40.8% | 47.5% |

Estimator: `observability.estimate_tokens` (words*4/3, the single canonical estimator
unified in #88). Holdout improving *more* than the score cases (not less) is a good sign
against overfitting to the exact wording of `SCORE_CASES`.

## Run log (6 iterations, `.simplicio/orchestrator/autoresearch/simplicio_precedent.py/iterations.jsonl`)

| iter | mutate | gate | score | accepted |
|---|---|---|---|---|
| 1 | ok | pass | 27.6667 | yes (34.33 → 27.67) |
| 2 | ok | pass | 24.3333 | yes |
| 3 | ok | pass | 21.3333 | yes |
| 4 | ok | **fail** | — | no (gate rejected the candidate — a real correctness gate rejection, not a plateau) |
| 5 | ok | pass | 20.3333 | yes |
| 6 | ok | pass | 20.3333 | no (tied — no improvement past the 1% margin) |

Gate = `bash bench/precedent_autoresearch_gate.sh` (existing precedent-related pytest
subset + `ruff check simplicio/precedent.py`), run BEFORE the score on every iteration —
never bypassed. Content-preservation markers (`[PRECEDENT]`, the literal
`{path}:{line}` pattern) held on every accepted iteration; the eval script would have
hard-failed (`sys.exit(1)`) otherwise.

## Two real bugs found and fixed by actually running the loop (not just wiring it)

1. **`bench/precedent_autoresearch_mutate.py`** — the `claude -p` subprocess call had
   `--tools ""` (disable all tools) placed BEFORE the prompt argument. `--tools` is
   variadic and swallowed the prompt string into its own value list, so `--print` got no
   prompt at all (`Input must be provided either through stdin or as a prompt argument`).
   Without `--tools ""` at all, the nested session tried to `Edit` the file itself, got
   blocked by this sandbox's nested-permission model, and printed an apology sentence
   instead of plain file content (failed `ast.parse`, every iteration). Fixed order:
   prompt first, `--tools ""` last.
2. **`tests/python/test_mapping_retry_flow.py::test_precedent_unknown_stack_falls_back_without_keyerror`**
   asserted the literal sentence `"no stack-specific precedent scanner"` — exactly one of
   the strings this autoresearch run exists to reword. The gate rejected every legitimate
   wording improvement by construction. Fixed to assert the structural invariant
   (`"[PRECEDENT]"` + `repr(stack)` present), matching the same philosophy as the eval's
   own anti-Goodhart content-preservation markers.

## What this is NOT

This run mutates wording via a real `claude -p` call per iteration (not the qwen
local-ladder / `simplicio-runtime#2774` motor the issue's "Fase 2" framing eventually
wants) — sufficient to actually exercise the loop end-to-end in this sandbox (no API key
config, no Angular fixture needed, unlike the originally-assessed blocker in PR #91).
Swapping the mutation engine later is a drop-in change to `--mutate-cmd`, not a rewrite.

`simplicio.savings-event/v1` schema (receipt was not auto-written because this run was
manually driven/interrupted mid-loop rather than left to its natural `max_iterations`/
plateau stop — the iteration log above is the equivalent evidence):

```json
{
  "schema": "simplicio.savings-event/v1",
  "source": "autoresearch",
  "target": "simplicio/precedent.py",
  "baseline": {"score": 34.3333},
  "actual": {"score": 20.3333},
  "holdout": {"baseline": 29.5, "actual": 15.5},
  "iterations": 6,
  "accepted": 4,
  "proof": {"kind": "autoresearch-run", "tokenizer": "words*4/3 (observability.estimate_tokens)"}
}
```
