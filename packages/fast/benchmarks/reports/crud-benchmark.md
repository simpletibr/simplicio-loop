# Simplicio Fast - User CRUD Benchmark

**Date:** 2026-07-26  
**Schema:** `simplicio.fast.crud-benchmark/v1`  
**Simplicio Fast:** 2.0.2  
**Python:** 3.12.13  
**Repetitions:** 100 complete CRUD cycles

## Objective

Validate the real user CRUD proof of concept and measure:

- direct service execution;
- execution through the HTTP API;
- semantic context retrieval through Simplicio Fast;
- cold, warm and incremental snapshot behavior;
- functional correctness of create, read, update and delete.

Simplicio Fast is outside the production request path. It accelerates repository orientation,
context selection and incremental agent workflows; it is not expected to reduce CRUD HTTP latency.

## Workload

Every repetition performed:

1. Create a user.
2. Read the created user.
3. Update the name and set `active=false`.
4. Delete the user.
5. Verify that the repository is empty.

The HTTP scenario executed the same lifecycle through `POST`, `GET`, `PUT`, `DELETE` and final
`GET /users`. The semantic scenario queried the hash-verified `UserService` context from an mmap
snapshot. All scenarios ran on the same host and Python process.

## Results

| Measurement | Median | P95 | Result |
|---|---:|---:|---|
| Direct CRUD cycle | 0.536 ms | 0.864 ms | Pass |
| HTTP CRUD cycle | 3.990 ms | 8.843 ms | Pass |
| Fast `UserService` context | 0.330 ms | 0.396 ms | Pass |

## Snapshot results

| Operation | Wall time | Parsed files | Reused files |
|---|---:|---:|---:|
| Cold build | 4.824 ms | 4 | 0 |
| No-change rebuild | 3.235 ms | 0 | 4 |
| One-file incremental rebuild | 3.852 ms | 1 | 3 |

- Initial symbols: 30.
- Symbols after the controlled change: 31.
- Snapshot after change: 87,498 bytes.
- Peak process RSS: 28,120 KiB.
- The changed symbol became visible after the incremental refresh.

## Functional validation

| Assertion | Status |
|---|---|
| Create user | Pass |
| Read user | Pass |
| Update user | Pass |
| Delete user | Pass |
| Normalize email | Pass |
| Reject duplicate email | Pass |
| HTTP lifecycle | Pass |
| Fast context retrieval | Pass |
| Incremental refresh | Pass |

The repository's two official user-service tests also passed.

## Interpretation

The complete HTTP CRUD lifecycle has a median latency of 3.990 ms. Direct domain and persistence
execution has a median latency of 0.536 ms. Retrieving verified semantic context for `UserService`
through Fast has a median latency of 0.330 ms.

These numbers describe different operations and must not be presented as an HTTP speedup ratio.
The measured Fast benefit is rapid, bounded project understanding plus incremental reuse:
after changing one of four source files, Fast parsed only that file and reused the other three.

## Reproduction

Run the official functional tests:

```bash
PYTHONPATH=src python -m unittest tests.test_users -v
```

The machine-readable receipt is stored at:

```text
benchmarks/results/crud-latest.json
```

## Conclusion

The user CRUD is functionally complete across the service and HTTP layers. Simplicio Fast provides
sub-millisecond semantic retrieval for this small project and correctly performs incremental
refresh without reparsing unchanged files. A separate full-stack LLM benchmark is required before
claiming token, provider cost or end-to-end software-delivery savings.
