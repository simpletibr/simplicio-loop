# Release process (#292)

This document tracks what part of issue #292's release pipeline is real today, and what remains
blocked. It exists so nobody has to reconstruct that history from the issue thread.

## Current, mechanical steps

1. **Version bump — one command, one PR.**

   ```bash
   python3 scripts/version_sync.py check                 # fails on any drift
   python3 scripts/version_sync.py apply --version X.Y.Z # rewrites every derived surface
   python3 scripts/version_sync.py manifest --json        # same shape as release_manifest.py
   ```

   `scripts/version_sync.py` (#292 Fase 1, shipped in PR #328) keeps `pyproject.toml`,
   `packaging/npm/package.json`, `.cursor-plugin/plugin.json`, and the `simplicio_loop/__init__.py`
   fallback in lockstep. `scripts/release_manifest.py` is the underlying parity gate; run it (or
   `version_sync.py check`) before opening a release PR.

2. **Local supply-chain artifacts** (see docs/SUPPLY_CHAIN.md for full scope/limits):

   ```bash
   python3 scripts/install_smoke.py run --expected-version X.Y.Z   # build + clean-room install
   python3 scripts/release_verify.py checksums-generate --dir dist --output dist/SHA256SUMS.json
   python3 scripts/release_verify.py checksums-verify --dir dist --manifest dist/SHA256SUMS.json
   python3 scripts/sbom_generate.py generate --artifact dist/<wheel> --output dist/sbom.json
   python3 scripts/release_verify.py sign --file dist/SHA256SUMS.json   # blocks if no gpg key
   python3 scripts/provenance_generate.py generate --artifact dist/<wheel> --output dist/provenance.json
   ```

   These are real, run-today commands. None of them require CI, a registry, or network access
   beyond what's already installed locally.

3. **Full local rehearsal — one command chains all of the above.**

   ```bash
   python3 scripts/release_rehearsal.py run --repo .
   ```

   `scripts/release_rehearsal.py` (#292 Fase 6, local subset) proves the WHOLE local pipeline
   composes end-to-end, not just that each script works standalone: it first runs the #294
   governance gate (`scripts/repository_budget.py --check` + `scripts/claims_audit.py --only
   8,13` — blob budget + quantitative-claims/canonical-manifest parity) against the real
   checkout, failing closed before anything else runs if the tracked tree is over budget or a
   claim has drifted; then it `git archive`-exports the tracked tree at `HEAD` into a disposable
   scratch copy, bumps the version in that scratch copy only (a safe `+rehearsalNNNN`
   local-version label by default — never the real repo's version files), builds a real wheel,
   generates+verifies checksums, best-effort gpg-signs them, generates an SBOM and a provenance
   statement (see docs/SUPPLY_CHAIN.md), and clean-room install-smokes the result. The receipt's
   `governance` key snapshots the current measured repo size (`docs/repo_size_report.json`) and
   history-migration candidate set (`docs/history_migration_plan.json`), and
   `docs/REPO_SIZE_REPORT.md`/`docs/HISTORY_MIGRATION_PLAN.md` are copied into `dist/` alongside
   the checksums/SBOM/provenance — the #294 "attach the size/claims report to the release"
   requirement, satisfied locally in the absence of a hosted release pipeline. It never touches
   the real repo's version files, never tags, and never publishes anywhere. Pass `--version
   X.Y.Z` to rehearse an explicit real bump instead of the safe label, or `--require-signing` to
   fail closed if no gpg key is configured.

4. **Publish.** PyPI publishing is still the pre-#292 manual/token-based flow described in the
   issue's "Fluxo atual problemático" section. It has NOT been migrated to OIDC/Trusted
   Publishing, and the automatic build-once pipeline (tag → build → attest → publish → verify)
   has NOT been implemented. See "What remains blocked" below for why.

## Running the full gate

The full gate is `python3 scripts/check.py --full`. It runs every test file. It must pass before a release.

Prepare the machine:

1. Make a virtual environment that is NOT under `/tmp`. Use a SHORT path, for example `~/.venvs/sl`.
   The sandbox tests (`tests/watcher247/test_sandbox_proc.py`) mount an empty `/tmp`. That hides an
   interpreter under `/tmp`, and those two tests skip. A long interpreter path also fills the
   gate diagnostics.
2. Install the packages in that environment:

   ```bash
   pip install -e . pytest pytest-cov coverage build setuptools wheel
   ```

3. Put the `simplicio-mapper` of this repository FIRST in `PATH`. It is the one that
   `pip install -e .` puts in the `bin` directory of the environment. An old
   `/usr/local/bin/simplicio-mapper` makes `tests/test_apply_system.py` fail with
   `mapper_provenance_missing`.

The machine does not have to be idle. The timing tests use wide margins. A short burst of other
load does not fail them. The route performance test keeps the 100 ms budget and uses the best of
three measurements. A machine that stays saturated (load average above the number of cores) can
still fail that test, because every measurement is then slow. Run the gate on a machine that is
not saturated.

Tests marked `external_integration` are NOT part of the gate.

The gate stops at the first failing shard. To see all failures, run the whole suite with this
command. It takes about 40 minutes:

```bash
pytest tests -q -p no:cacheprovider --maxfail=1000 -rf
```

## What remains blocked, and why

Two workflows currently exist under `.github/workflows/` (`simplicio-status-sync.yml` and
`windows-progress-smoke.yml`), but neither is an OIDC or release gate and neither was executed or
used as evidence for this work. Issue #292's
Fases 2, 3, 5, 6, 8, and most of 9 are written against a GitHub-Actions-shaped pipeline
specifically:

- Fase 2 (release governance) assumes a required-status-check + protected `release` environment
  model that is a GitHub Actions/branch-protection feature.
- Fase 3 (build-once) assumes a dedicated CI job (`build-release-artifacts`) with a fixed runner
  image and `SOURCE_DATE_EPOCH` control — meaningless without a CI runner to execute it on.
- Fase 5 (OIDC/Trusted Publishing) is **inherently CI-specific**: PyPI/npm Trusted Publishing
  issues short-lived tokens to an OIDC identity minted BY a CI job (`repository`, `workflow`,
  `environment` claims) — there is no such thing as "OIDC from a local machine." This phase
  cannot be satisfied by any local script, by construction, not just for lack of tooling.
- Fase 6 (publish same bytes to each registry) needs an actual publish target to compare against;
  none of PyPI, npm, or GitHub Releases has been published to as part of this change.
  `scripts/release_rehearsal.py` closes the achievable local subset — it proves the whole
  version-bump→build→checksum→sign→SBOM→provenance→smoke chain composes end-to-end against a
  disposable scratch copy — but it deliberately never publishes anywhere, so the actual
  "same bytes land on PyPI/npm/GitHub Release" claim remains unmade.
- Fase 8 (idempotent partial-failure recovery across registries) needs Fase 3/5/6 to exist first.
- Fase 9 (`source_state`/delivery reconciliation on real receipts): re-confirmed still correct.
  `simplicio_loop/source_state.py` defaults `checksums_verified`/`signatures_verified`/
  `sbom_present`/`install_smoke.passed` to `false` and requires `verify_release`/
  `verify_branch_reachability` (in `simplicio_loop/external_verifiers.py`) to flip them — this
  module already downloads real GitHub Release assets, recomputes SHA-256, attempts
  `gh attestation verify`, parses an attached SBOM, and install-smokes the downloaded wheel in a
  throwaway venv (a separate line of work from this issue, but directly relevant to it: the
  GitHub-Release leg of Fase 7/9 is real and byte-level today). What remains genuinely blocked is
  wiring the *PyPI* and *npm* legs the same way, which needs Fases 3/5/6 (an actual publish) first.

**Judgment call:** rather than write GitHub Actions YAML that cannot run (this repo's Actions are
billing-locked) or claim OIDC/Sigstore coverage that doesn't exist, this change implements the
platform-agnostic subset of Fase 4, Fase 6, and Fase 7 as real, tested, local CLI tools (see
docs/SUPPLY_CHAIN.md), and leaves Fases 2/3/5/8, and the PyPI/npm legs of 6/9, explicitly open
pending a CI trigger with OIDC-equivalent capability and the required release controls.

This is now a formal, signed-off decision, not a running judgment call re-litigated every round:
see `docs/adr/0004-release-oidc-trusted-publishing-permanently-blocked.md` for the durable ADR
that freezes Fase 5 (and its structural dependents — Fases 2/3/8, and the PyPI/npm legs of 6/9)
as permanently blocked pending a CI substrate, with the exact precondition for revisiting it.

## Real end-to-end dry run (verification of the local pipeline)

`scripts/release_rehearsal.py run --repo .` was re-run against the actual `main` HEAD (not a
fixture) as part of confirming this document. It produced a consistent artifact set in one pass:
the built wheel's SHA-256 digest matched byte-for-byte across `SHA256SUMS.json`, `sbom.json`'s
`artifact.sha256`, and `provenance.json`'s `subject[0].digest.sha256`; the SBOM's `source_sha` and
the provenance statement's `predicate.invocation.configSource.digest.sha1` both matched the real
`git rev-parse HEAD` of the source tree the scratch copy was exported from; and the clean-room
install-smoke installed that exact wheel into a fresh venv and confirmed the observed version and
module path resolve to the venv, not the checkout. The receipt's final `"ok": true` reflects every
step (export → version-bump → build → checksums → SBOM → provenance → install-smoke) actually
running and passing, not a presumed/short-circuited result.
