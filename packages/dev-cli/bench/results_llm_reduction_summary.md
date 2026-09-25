# LLM Reduction Summary

aggregate issue #33 evidence view; separates local synthetic gates from the real release corpus and LLM-baseline gates

## Summary

- local synthetic gates pass: True
- release evidence complete: False
- target reduction met for release: True
- modeled local call path: 19 -> 6 (68.42% reduction)
- release call proof: 210 -> 0 (100.00% reduction)

## Lever Evidence

| lever | gate | key evidence | release gap |
| --- | --- | --- | --- |
| D cache | True | warm hit-rate 100.00%, hits/misses 50/0 | real corpus True |
| C static fixers | True | fixed 80.00%, retry calls down 40.00%, real pkg probe 10/10, scratch import probe 1/1 | real corpus True |
| A recipes | True | match-rate 60.00%, planner calls saved 30 | LLM baseline True, real corpus True |
| B codegen | True | codegen share 100.00%, pass-rate 100.00%, avg 51 ms | LLM baseline True, real corpus True |
| scratch preflight | True | blockers 0 | ready for matrix execution |
| scratch live gate | True | 75/75 e2e green, SkillOpt 8/10 approved, median 6.262 s | full matrix True |

## Modeled Call Path

- baseline: 19 calls
- D_cache: 18 calls, gate=True
- C_static_fixers: 16 calls, gate=True
- A_recipes: 16 calls, gate=True
- B_codegen: 6 calls, gate=True

## Release Call Proof

- release matrix present: True
- baseline calls: 210
- actual calls: 0
- calls saved: 210
- planner calls saved by recipes: 75
- task calls handled by codegen: 135
- remaining task-level LLM calls: 0

## Missing Release Evidence

- real scratch LLM baseline for B/codegen pass-rate and latency
