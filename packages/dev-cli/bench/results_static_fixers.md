# Static Fixers Benchmark

synthetic verify-loop fixer benchmark with optional real package-manager probe and live scratch-corpus inspection

## Summary

- cases: 50/50 passed
- fixed before LLM retry: 80.00%
- baseline LLM calls: 100
- with-fixer LLM calls: 60
- retry-call reduction: 40.00%
- real package-manager probe: 10/10
- scratch import failure probe: 1/1

## Release Gate Status

- fifty_cases: True
- fixer_resolved_ge_80: True
- retry_calls_down_ge_30: True
- real_package_manager_execution: True
- real_scratch_import_failure_repaired: True
- real_scratch_corpus: True
- real_eligible_failures_observed: True

## Live Scratch Corpus Inspection

- source: bench/results_scratch_live_gate.json
- runs: 75
- e2e green: 75/75
- eligible failure runs: 0
- post-verify failure runs: 0
- scratch returncode failure runs: 0
- stacks: go-gin, php-laravel, py-fastapi, rust-axum, ts-nextjs

## Cases

| case | fixed_before_retry | baseline_calls | with_fixer_calls | passed |
| --- | --- | ---: | ---: | --- |
| missing-pip-01 | True | 2 | 1 | True |
| missing-pip-02 | True | 2 | 1 | True |
| missing-pip-03 | True | 2 | 1 | True |
| missing-pip-04 | True | 2 | 1 | True |
| missing-pip-05 | True | 2 | 1 | True |
| missing-pip-06 | True | 2 | 1 | True |
| missing-pip-07 | True | 2 | 1 | True |
| missing-pip-08 | True | 2 | 1 | True |
| missing-pip-09 | True | 2 | 1 | True |
| missing-pip-10 | True | 2 | 1 | True |
| missing-pip-11 | True | 2 | 1 | True |
| missing-pip-12 | True | 2 | 1 | True |
| missing-pip-13 | True | 2 | 1 | True |
| missing-pip-14 | True | 2 | 1 | True |
| missing-pip-15 | True | 2 | 1 | True |
| missing-pip-16 | True | 2 | 1 | True |
| missing-pip-17 | True | 2 | 1 | True |
| missing-pip-18 | True | 2 | 1 | True |
| missing-pip-19 | True | 2 | 1 | True |
| missing-pip-20 | True | 2 | 1 | True |
| missing-pip-21 | True | 2 | 1 | True |
| missing-pip-22 | True | 2 | 1 | True |
| missing-pip-23 | True | 2 | 1 | True |
| missing-pip-24 | True | 2 | 1 | True |
| missing-pip-25 | True | 2 | 1 | True |
| missing-pip-26 | True | 2 | 1 | True |
| missing-pip-27 | True | 2 | 1 | True |
| missing-pip-28 | True | 2 | 1 | True |
| missing-pip-29 | True | 2 | 1 | True |
| missing-pip-30 | True | 2 | 1 | True |
| missing-pip-31 | True | 2 | 1 | True |
| missing-pip-32 | True | 2 | 1 | True |
| missing-pip-33 | True | 2 | 1 | True |
| missing-pip-34 | True | 2 | 1 | True |
| missing-pip-35 | True | 2 | 1 | True |
| missing-pip-36 | True | 2 | 1 | True |
| missing-pip-37 | True | 2 | 1 | True |
| missing-pip-38 | True | 2 | 1 | True |
| missing-pip-39 | True | 2 | 1 | True |
| missing-pip-40 | True | 2 | 1 | True |
| assertion-01 | False | 2 | 2 | True |
| assertion-02 | False | 2 | 2 | True |
| assertion-03 | False | 2 | 2 | True |
| assertion-04 | False | 2 | 2 | True |
| assertion-05 | False | 2 | 2 | True |
| assertion-06 | False | 2 | 2 | True |
| assertion-07 | False | 2 | 2 | True |
| assertion-08 | False | 2 | 2 | True |
| assertion-09 | False | 2 | 2 | True |
| assertion-10 | False | 2 | 2 | True |

## Real Package-Manager Probe

| case | package | applied | dependency_declared | import_ok | passed | duration_ms |
| --- | --- | --- | --- | --- | --- | ---: |
| packaging-01 | packaging | True | True | True | True | 966 |
| colorama-01 | colorama | True | True | True | True | 976 |
| idna-01 | idna | True | True | True | True | 905 |
| certifi-01 | certifi | True | True | True | True | 914 |
| charset-normalizer-01 | charset-normalizer | True | True | True | True | 953 |
| packaging-02 | packaging | True | True | True | True | 937 |
| colorama-02 | colorama | True | True | True | True | 885 |
| idna-02 | idna | True | True | True | True | 956 |
| certifi-02 | certifi | True | True | True | True | 951 |
| charset-normalizer-02 | charset-normalizer | True | True | True | True | 934 |

## Scratch Import Failure Probe

| case | initial_failure | fixer | dependency_declared | final_pytest | passed | duration_ms |
| --- | --- | --- | --- | --- | --- | ---: |
| static-fixer-import-probe-01 | True | missing-pip-package | True | True | True | 10251 |
