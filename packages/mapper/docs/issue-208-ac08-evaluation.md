# Issue #208 AC08 evaluation

Overall verdict: **UNVERIFIED**

This report is intentionally baseline-backed and evidence-conservative: it only uses committed corpus/evidence already present in the repository. It does **not** infer or fabricate missing baselines.

## Measured corpus facts

- Cases in frozen corpus: 3
- Languages covered: en, pt-BR
- Abstention cases: 1
- Expected target labels: 2
- Expected test labels: 2
- Expected AC labels: 6
- Fixtures with committed task file: 3
- Existing expected target files: 2
- Existing expected test files: 2

## Supporting artifacts checked

- `contracts/behavioral/v1/corpus.json` — present; Committed frozen corpus with labeled expected targets/tests/AC ids.
- `docs/toon-benchmark.md` — present; Measures TOON serialization on survey artifacts, not adaptive-vs-full context packs on the issue #208 frozen corpus.
- `scripts/measure_verbs_report.json` — present; Measures isolated ask-verb latency on a minimal fixture, not full-vs-incremental causal-cone refresh p95 on the issue #208 corpus.

## Hypothesis verdicts

### H1

- Statement: Adaptive context packs reduce serialized tokens by at least 30% versus the full snapshot while keeping task pass rate within 2 percentage points of baseline.
- Verdict: **UNVERIFIED**
- Baseline status: `missing_required_baseline`
- Missing metrics: baseline_full_snapshot_tokens, candidate_adaptive_context_tokens, baseline_task_pass_rate, candidate_task_pass_rate
- Note: The committed corpus labels tasks, targets, tests, and AC ids, but does not commit paired baseline/candidate metric runs for this hypothesis.

### H2

- Statement: For local changes, incremental work grows with the affected causal cone rather than repository size, and cuts p95 by at least 3x on the frozen corpus.
- Verdict: **UNVERIFIED**
- Baseline status: `missing_required_baseline`
- Missing metrics: baseline_full_scan_p95_ms, candidate_incremental_p95_ms, affected_causal_cone_size, repository_size, bytes_read, files_parsed, nodes_recomputed
- Note: The committed corpus labels tasks, targets, tests, and AC ids, but does not commit paired baseline/candidate metric runs for this hypothesis.

## Negative findings

- No committed paired baseline/candidate token measurements exist for adaptive-vs-full context packs.
- No committed task pass-rate baseline exists for the issue #208 frozen corpus.
- No committed full-scan vs incremental p95 measurements exist for local-change causal-cone refresh on this corpus.
- No committed bytes-read/files-parsed/nodes-recomputed counters are attached to the issue #208 corpus cases.

## Case inventory

- `planes-ordering-ptbr` (pt-BR) — task_exists=true, targets=1/1, tests=1/1, ac_ids=AC01, AC02, AC03
- `frontend-ordering-en` (en) — task_exists=true, targets=1/1, tests=1/1, ac_ids=AC01, AC02
- `no-match-abstention` (en) — task_exists=true, targets=0/0, tests=0/0, ac_ids=AC01

## Conclusion

H1 and H2 cannot be accepted or refuted from the currently committed issue #208 corpus and evidence alone. The honest state is `UNVERIFIED` until paired baseline/candidate measurements are committed.
