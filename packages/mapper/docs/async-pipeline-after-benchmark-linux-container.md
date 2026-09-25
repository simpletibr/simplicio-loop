# Async mapping pipeline -- after benchmark, Linux container run (issue #264)

This is a **second, independent** after-benchmark run of the same
`scripts/async_pipeline_after_benchmark.py` tool used for
`docs/async-pipeline-after-benchmark.md` (the original issue #235
finalization-pass number), executed from this container to close part of
ADR-009's own honestly-documented gap: *"Windows/Linux/macOS: Windows-verified
only in this sandbox... Linux/macOS are NOT independently verified here."*
That statement is no longer fully true for the **inventory/test-suite**
half of the gap -- it remains true for the **uvloop-active** half (see
"What this does and does not close" below).

## Environment

- Platform: `Linux-6.18.5-x86_64-with-glibc2.39` (container), CPU
  `Intel(R) Xeon(R) Processor @ 2.10GHz`, `os.cpu_count() == 4` (matches the
  `min(64, os.cpu_count() * 4)` = 16 default concurrency cap on this
  machine).
- Python: `3.11.15` (the Windows runs in `docs/async-pipeline-*-benchmark.md`
  were measured on `3.14.5` -- **different Python minor version, different
  machine class** -- see caveat below).
- `psutil` is **not installed** in this container and was not installed for
  this measurement (installing a new dependency requires user confirmation
  per this repo's `AGENTS.md`/`CLAUDE.md` policy, and RSS is not the
  measurement this run exists to provide). Peak RSS is reported as `0.0` in
  the raw JSON for every row as a result -- this is an honest gap in this
  run, not a fabricated `0`. RSS numbers for a real measurement remain only
  in the Windows-side reports.
- `--runs 2` (small sample size, chosen for container time budget; see
  "Confidence and limitations" below).
- Raw JSON: `docs/evidence/async-pipeline-after-benchmark-linux-container.json`
  (schema `simplicio.async-pipeline-after-benchmark/v1`, same schema as the
  Windows after-benchmark JSON).
- Command used (from repo root):

  ```bash
  python3 -c "
  import sys, json
  from datetime import datetime, timezone
  from scripts.async_pipeline_after_benchmark import _benchmark_size, SIZES, SCHEMA, _render_markdown

  results = [_benchmark_size(spec, 2) for spec in SIZES]
  # ... payload assembly, see scripts/async_pipeline_after_benchmark.py::main()
  "
  ```

  (Not run via `--write` directly: the script's `--write` flag hardcodes
  `docs/async-pipeline-after-benchmark.md` /
  `docs/evidence/async-pipeline-after-benchmark.json` -- the existing Windows
  evidence files -- and overwriting those with a different machine's numbers
  under the same filenames would destroy the original Windows data point
  and misrepresent which platform each report was measured on. This report
  reuses the exact same `_benchmark_size`/`_render_markdown` functions from
  the unmodified script, just writes to differently-named files.)

## Results (this container, Linux, Python 3.11.15)

| Size | Files | Cold wall p50/p95 (s) | Cold CPU (s) | Cold peak RSS (MB) | Cold files/s | Warm wall p50/p95 (s) | Warm files/s | Warm/Cold speedup |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| small | 4 | 0.0716 / 0.0811 | 0.0236 | 0.0 (unmeasured, no psutil) | 55.89 | 0.0220 / 0.0241 | 181.41 | 3.25x |
| medium | 220 | 0.4895 / 0.5039 | 0.4766 | 0.0 (unmeasured, no psutil) | 449.47 | 0.3844 / 0.3853 | 572.27 | 1.27x |
| large | 1650 | 6.8766 / 7.0665 | 7.7402 | 0.0 (unmeasured, no psutil) | 239.94 | 8.1236 / 8.9285 | 203.11 | **0.85x (warm slower than cold)** |

The large-tree warm run being *slower* than cold (0.85x) is reported as
measured, not smoothed over -- with `--runs 2` this could be container I/O
noise (shared disk, noisy-neighbor scheduling) rather than a real
cache-effectiveness regression; a higher `--runs` count on a dedicated
non-shared machine would be needed to tell those apart with confidence. It
is flagged here rather than silently dropped.

## Cross-machine comparison to the Windows numbers (informational only)

| Size | Windows before cold (s) | Windows after cold (s) | Linux-container after cold (s) |
|---|---:|---:|---:|
| small | 0.0682 | 0.1288 | 0.0716 |
| medium | 1.0738 | 1.6082 | 0.4895 |
| large | 25.7289 | 13.8028 | 6.8766 |

**This table is informational, not a rigorous benchmark comparison.** The
Windows and Linux-container numbers were measured on different physical/
virtual machines, different CPU classes, different Python minor versions
(3.14.5 vs 3.11.15), and different filesystem/disk-cache behavior
(container overlay filesystem vs. a Windows NTFS volume) -- differences of
this kind routinely produce 2x-4x swings unrelated to the code under test.
The Linux-container numbers being uniformly faster is **not** evidence that
"Linux is faster than Windows for this pipeline"; it is evidence that two
different machines produced two different numbers, which is expected and
uninteresting on its own. The only claim this table supports is the one in
the section below.

## What this does and does not close (ADR-009 gap tracking)

- **Closes**: "Linux/macOS untested" for (a) a real, non-mocked execution of
  `build_artifacts()` (the async-adapter production entry point) completing
  successfully end-to-end on Linux across small/medium/large trees, and (b)
  the full focused test suites (`tests/python/test_async_pipeline.py`,
  `tests/python/test_mapper_async_inventory.py`) passing on Linux: **26
  passed, 1 skipped** (the 1 skip is
  `UvloopSelectionTest::test_build_artifacts_never_calls_uvloop_installer_on_windows`,
  correctly platform-gated to skip on non-Windows -- itself evidence the
  platform-detection logic behaves as designed, not a gap).
- **Does NOT close**: the uvloop-active code path is still unverified
  against a real uvloop installation. `uvloop` is not installed in this
  container (`pip show uvloop` / `import uvloop` both fail with
  `ModuleNotFoundError`); confirmed directly:

  ```
  >>> from simplicio_mapper.mapper.async_pipeline import _install_uvloop_if_available
  >>> _install_uvloop_if_available()
  False
  ```

  This IS a genuine (not mocked) exercise of the "uvloop not available,
  fall back to stdlib asyncio" branch on a real non-Windows platform --
  which is itself useful evidence, since that is the actual behavior most
  real Linux/macOS installs will see unless they explicitly opt in via
  `pip install simplicio-mapper[uvloop]` (see the operational guide). But it
  does not exercise the branch where `uvloop.EventLoopPolicy()` is actually
  installed and driving the event loop -- that remains verified only via
  `unittest.mock` in `UvloopSelectionTest`, exactly as ADR-009 already
  documented. Installing `uvloop` here would add a new dependency to this
  session's environment without user confirmation, which this repo's
  `AGENTS.md` explicitly requires asking about first -- left as the one
  remaining, honestly-flagged gap.

## Confidence and limitations

- Sample size: `--runs 2` per size (vs. `--runs 3` for the original Windows
  reports). Smaller sample, wider uncertainty on the medians reported above
  -- treat single-digit-percent deltas as noise, not signal.
- Container CPU/disk are very likely shared/virtualized with other
  workloads on the host; no attempt was made to pin CPU affinity or verify
  an idle host, so absolute wall-clock numbers here should not be treated
  as a hardware-performance claim, only as "the pipeline completes
  correctly and produces valid output at these three sizes on Linux."
- No new fixture sizes were introduced beyond the existing small
  (4-file real fixture) / medium (220-file synthetic) / large (1650-file
  synthetic) tiers already defined in
  `scripts/async_pipeline_after_benchmark.py::SIZES`, so this run is
  directly reproducible by anyone re-running the same script on the same
  revision.
