# Issue #2 validation receipt

Repair commits: `79b67f4` (`fix(format): repair issue 2 merge conflicts`), `c53bace`
(`fix(format): merge current origin/master`) and `6bc8151`
(`fix(format): merge latest master generation APIs`)

Pull request: https://github.com/wesleysimplicio/simplicio-fast/pull/12 (OPEN, base `master`)

Mapper was refreshed after the merge. The final handoff was fresh and ready with
`pack_hash=a43da4fd8173ee4a29ebe1c975e54ae4796497112e1dfb6da3cf2b107f778083`, 201 symbols and
283 relationships; `.simplicio/` remains derived and ignored.

## Validation

| Gate | Result |
|---|---|
| Unit, integration and regression | `MEASURED| 20 tests passed: PYTHONPATH=src; python -m unittest discover -s tests -v` and through `simplicio-dev-cli test run --cmd python -- -m unittest discover -s tests -v` |
| Compile | `MEASURED| python -m compileall -q src tests benchmarks` passed |
| CLI/system | `MEASURED| build/search/context/impact/stats/doctor --json` passed; doctor reported `ready=true`, `SFAST001/v2`, 19 files, 201 symbols and 6494 relations |
| Corruption/property-style | `MEASURED| tests.test_snapshot.SnapshotTest.test_corruption_and_truncation_fail_closed` passed; malformed/truncated and checksum-mutated snapshots fail closed |
| v1 migration | `MEASURED| frozen SFAST001/v1 fixture opens and exact lookup succeeds` |
| Coverage | `MEASURED| coverage.py 7.15.1 --branch: snapshot.py 86% combined, cli.py 53%, benchmarks/run.py 38%, workspace.py 83%, total 74%`; touched CLI/benchmark/workspace coverage remains below the 85% target |
| Benchmark | `MEASURED| full python benchmarks/run.py --sizes 1000,10000,100000 --repetitions 10` before latest master: query speedup 9.30x, 18.46x and 9.17x; Windows peak RSS 34,340/95,852/689,968 KiB. `MEASURED|` final `--sizes 1000 --repetitions 10` passed at 15.83x with isolated overlay slots 1/5/20 and peak RSS 35,564 KiB; page faults unavailable (`null`) |

The `simplicio-dev-cli` mapper-backed inspection and native test delegation were `MEASURED|pass`;
source conflict resolution itself used Git/apply-patch because the merge state is not a normal
Dev CLI task. Runtime `simplicio versions --json`/`simplicio doctor --json` were available, but
`simplicio contracts smoke --json` was `UNVERIFIED|blocked` by missing required repository
artifacts `docs/SIMPLICIO_OPERATIONAL_MANUAL.md` and `examples/EXAMPLES.md`; no Runtime effect
authorization receipt is claimed. The PR remains OPEN and was not merged or closed.
