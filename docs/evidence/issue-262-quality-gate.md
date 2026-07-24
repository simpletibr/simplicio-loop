# Issue #262 quality-gate evidence

Date: 2026-07-22. Branch base: `bf2e293` (`main` checkout). Python 3.12.13 on
Linux x86_64.

## Implemented and exercised

- `python3 scripts/check_json_boundaries.py --strict`: 0 unclassified findings.
- `pytest -q tests/python/test_json_boundaries.py
  tests/python/test_local_quality_gate.py::test_ci_blocks_internal_json_in_sources_and_release_archives_on_supported_platforms
  --cov=scripts.check_json_boundaries --cov-branch --cov-report=term-missing`:
  16 passed; scanner coverage 89% including branches.
- `python -m build` built the wheel and sdist. Then
  `python scripts/check_json_boundaries.py --strict --artifact-dir dist` scanned
  every release archive and returned 0 packaged internal JSON findings.
- `.github/workflows/ci.yml` now runs those source/build/package checks as a
  blocking job on `ubuntu-latest`, `macos-latest`, and `windows-latest`; the
  workflow contract test proves none of the release stages can be omitted.
- Adversarial archive tests inject `.simplicio/generated.json` into wheel and
  sdist layouts; strict scanning rejects both. A malformed archive fails closed,
  while an external `schema.json` remains allowed.
- Exact-registry tests reject traversal, absolute paths, wildcard paths, missing
  owners, missing reasons, and missing expiration dates.
- The benchmark command and measured values are recorded in
  `issue-262-scanner-benchmark.md`; unobservable metrics are not represented as
  zero.

## Repository-wide gate state

The focused issue gate is green. A broader focused run also executes the
pre-existing workflow-reference regression and reports 1 unrelated failure:
`docs/evidence/issue-265-meta-audit.md` names four deleted workflow files. The
repository-wide commands are not green on the `main` baseline: `ruff check .`
reports 23 unrelated findings and `mypy simplicio` reports 5 unrelated errors.
The complete `pytest -q` run finished with 1927 passed, 20 skipped and 39
failed. One failure was the local-gate documentation line wrapping changed in
this patch; it was corrected and its targeted test then passed. The remaining
baseline failures cover stale CLI snapshots/version pins, provider behavior,
missing console entrypoints/dependencies and unrelated codegen/runtime tests;
they were not rewritten in this focused change.

## Criteria not proven by this repository change

This PR does not claim Runtime HBI conformance, HBP migration lineage, atomic
legacy migration or cross-repository released-package compatibility. The
Linux/macOS/Windows matrix is configured but cannot be claimed green until the
new pull-request checks execute. The repository still contains the dated legacy
exceptions listed in `config/json-boundaries.toml`; classification is enforced,
but their underlying producers have not all migrated. These are explicit
release blockers rather than passing zeroes. The PR must remain unmerged until
those criteria have executable evidence and the repository-wide gate is green.

## Scanner hardening follow-up — 2026-07-23

The pinned Python and Node scanners now have executable parity coverage. They:

- detect direct standard-library imports in addition to serializer calls;
- reject unsupported exception categories, invalid calendar dates, expired
  exceptions, traversal and wildcard paths;
- classify renamed arrays, symlinks and oversized text as findings rather than
  following or silently skipping them, with size checked before reading;
- default expiry evaluation to the actual scan date;
- emit byte-identical Markdown and HBP evidence for the same fixture.

Focused validation:

```text
PYTHONPATH=/tmp/pytest-deps python3 -m pytest -q \
  tests/python/test_policy_scan.py tests/python/test_json_boundaries.py \
  tests/test_json_boundaries.py tests/python/test_local_quality_gate.py
44 passed in 0.44s; 90.81% combined branch coverage
```

Installed-package probe:

```text
python3 -m pip wheel --no-deps --no-build-isolation .
Successfully built simplicio-cli
python3 -m pip install --no-deps --target <temporary> simplicio_cli-0.16.2-py3-none-any.whl
Successfully installed simplicio-cli-0.16.2
importlib.metadata.version("simplicio-cli") == "0.16.2"
python3 scripts/check_json_boundaries.py --strict --artifact-dir <temporary-wheel-dir>
json-boundaries: 0 finding(s); strict=pass
```

The wheel SHA-256 was
`5fdb54f0b2470bc18fb11c6c9528e39f7c070fd40e7465585ab77c4cd3d7097f`.
The full installed CLI could not be exercised in isolation because its declared
runtime dependencies were not installed and network installation was outside
this run; that lane is `null`, not pass.

The shared source scan remains intentionally red: baseline found `1469`
occurrences, `1448` unclassified. Strict mode therefore blocks release. This
repository still has no locally available Runtime HBI conformance suite,
versioned HBI codec, atomic legacy migrator, released adjacent package matrix,
or macOS/Windows hosts. HBI conformance, codec corruption/migration behavior,
cross-repository upgrade/rollback and supported-OS results remain `null` with
those reasons. No custom binary format or synthetic cross-repository result was
introduced to make the gate appear green.

## Current checkout recheck — 2026-07-23

The strict source scanner was rerun after the Runtime resource-map cache was
observed in `.simplicio/cache/resource-map-full.json`. It is an exact
`simplicio.runtime-resource-map/v1` cache owned by `simplicio-runtime`, so it
now has one dated HBI migration exception in
`config/json-boundaries.toml`.

```text
python3 scripts/check_json_boundaries.py --strict
json-boundaries: 0 finding(s); strict=pass
```

This changes only local classification. It does not claim Runtime HBI
conformance, HBP migration lineage, installed-package E2E, or release
readiness; those remain explicit external gates.

## Dev CLI HBP adapter slice — 2026-07-24

`simplicio.hbp/v1` is now available through the additive
`simplicio.hbp.HbpEvidenceLedger` adapter. It mirrors Runtime's `HBP1` header,
little-endian length-delimited records, typed `hbp-fields/v1` evidence payload,
chain links, and SHA-256 row hashes. It rejects legacy JSONL, unknown
version/flags, truncation, tampering, and invalid chain state before append or
verification.

Local evidence: `5 passed`; touched-module coverage `85%`; the Runtime MCP test
runner also passed the HBP adapter suite. Existing JSON writers remain in place
until Mapper/Loop/Runtime installed migration and upgrade/rollback evidence is
available, so #262 remains open.
