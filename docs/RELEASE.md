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

## Binary (standalone executable)

Issue #1576. The release can include one executable for each operating system. The executable holds
Python, the loop, the mapper, and the dev-cli. The target machine needs no Python.

### Release contract

| Item | Rule |
|------|------|
| Asset name | `simplicio-loop-v<version>-<os>-<arch>`, with `.exe` on Windows |
| `<os>` | `linux`, `darwin`, or `windows` |
| `<arch>` | `x86_64` or `aarch64` |
| `SHA256SUMS` | One line per asset: 64 lower-case hex digits, two spaces, the file name |
| `simplicio-loop --version` | Prints `simplicio-loop <version>` |
| Frozen build | `sys.frozen` is true. The `update` command uses it to find the distribution |

One executable also runs as `simplicio-mapper`, `simplicio-dev-cli`, `simplicio-cli`, and `simplicio-py`.
The program reads `argv[0]` and starts the matching entry point. The code is in `simplicio_loop/frozen.py`.

- At start, the binary makes the links `~/.simplicio-loop/bin/<key>/<name>` and puts that directory first in
  `PATH`. The loop starts its operators by name, so they find the links.
- Because that directory is first in `PATH`, the binary checks each level before it uses it. Each level
  must be a real directory of the current user. Group and others must not write it. The last level must
  have mode 0700, and the binary removes every file in it that is not one of its links. If a level fails the
  check, the binary prints the reason and uses a new directory from `mkdtemp`. The binary removes that
  directory when it ends.
- A child that the binary starts as `sys.executable` (for example the dashboard server) gets its own unpacked
  copy of the files and the mark `SIMPLICIO_LOOP_SELF_SPAWN`. Only a process with that mark runs `-m MODULE`,
  `-c CODE`, or `FILE.py` as python does. Without the mark, `simplicio-loop fix.py` is a task, and an
  operator name never runs code.
- No child keeps the unpack directory of the bundle on `LD_LIBRARY_PATH`. System programs such as `git` load
  the libraries of the system.

### Tool decision

All numbers come from one Linux x86_64 host with 10 cores and a load average of 7 to 9 from other jobs.
Python was 3.13.15 (python-build-standalone from `uv`) and PyInstaller 6.22.3. Startup is the time of `--version`:
the first run (the cold run), then the median of the next 9 runs.
The times are wall-clock times, so they scale with the load.

| Option | Build time | Size | `--version` first run / median of 9 more | Peak memory | Result |
|--------|-----------|------|-------------------------------------------|-------------|--------|
| Wheel install (baseline) | 15 s to build the wheel | 5.3 MB wheel, 102 MB with its dependencies | 1.2 s / 1.2 s | 38 MiB | Needs Python on the target |
| PyInstaller one-file | 173 to 190 s with a new venv and downloads (five builds). PyInstaller alone: 117 to 141 s | 43.5 MB | 2.6 s / 2.8 s | 42 MiB | Chosen. All smoke checks pass |
| PyInstaller one-dir | 94 s (PyInstaller alone) | 104 MB directory | 1.4 s / 1.5 s (see note) | 45 MiB | Not one file. Faster start |
| Nuitka 4.2.2 | Not measured | Not measured | Not measured | Not measured | Stopped at the 15-minute limit |
| zipapp, shiv, pex | Not tried | Not tried | Not tried | Not tried | Not native binaries: they need Python on the target |

Note: the one-file and wheel rows use Python 3.13.15 from `uv`. The one-dir row and the PyInstaller-alone build
times use the system Python 3.14.4, where the wheel starts in 0.9 s to 1.1 s.
Nuitka used 15 minutes, 833 s of CPU, and 1.4 GB of memory. It finished the Python-level step
after about 12.5 minutes and compiled none of the C files. The hot path (`turbo` survey and apply on a small
repository) takes 11 s to 13 s with the binary and 7 s to 9 s with the wheel.

Decision: PyInstaller, one-file. It is the only candidate that made one native executable
within the time limit. The one-file start is slower than the wheel, because it unpacks about 100 MB
to a temporary directory at every start. The one-dir build starts faster but is a directory, not an asset
of the contract. Use it only when start time matters more than a single file.

### Build the executable

Build on the target system and architecture. PyInstaller does not cross-compile. The build needs network,
because `pip` downloads the dependencies of the wheel and PyInstaller.

```bash
uv python install 3.13                                      # the same Python on every build host
python3 scripts/build_binary.py --python "$(uv python find 3.13)"
```

The script does these steps in the `--work` directory (`build/binary` by default, about 600 MB):

1. It exports the sources: `HEAD` of the git checkout, as a detached worktree. Local changes and old build
   output are not in it. For a tree without git, the script copies the files and skips `build`, `dist`, and cache directories.
2. It builds a wheel from that export.
3. It makes a new venv from `--python` and installs exactly that wheel and `pyinstaller==6.22.3`.
4. It runs PyInstaller from that venv through `packaging/binary/pyinstaller_run.py`.
5. It runs the executable with `--version`. It publishes the asset only if the output is
   `simplicio-loop <version>`.

The result is `dist/binary/simplicio-loop-v<version>-<os>-<arch>` and `dist/binary/SHA256SUMS`.
The script refuses a dirty tree unless you pass `--allow-dirty`. The build uses `HEAD` in both cases, so it
never contains the uncommitted changes. Use `--out` and `--work` to put the files on another disk, and
`--onedir` for a directory build.

Run the smoke test. It copies only the executable to an empty directory, scrubs the environment, and compares
the results with the wheel install in the build venv:

```bash
python3 scripts/smoke_binary.py dist/binary/simplicio-loop-v<version>-linux-x86_64 \
    --wheel build/binary/wheel/simplicio_loop-<version>-py3-none-any.whl \
    --reference-bin build/binary/venv/bin --timing 10
```

The slow pytest version is `tests/test_binary_smoke_external.py`. Set `SIMPLICIO_BINARY` to run it.

Reproducibility is not guaranteed. The build sets `SOURCE_DATE_EPOCH` to the time of the last commit and
`PYTHONHASHSEED` to 0. The work path stays the same, and `pyinstaller_run.py` sorts the entries of
`base_library.zip`. Without the sort, 1 of 4 builds of one commit gave another SHA-256, because the entries of
`base_library.zip` came in another order. With the sort, 5 of 5 builds of commit `00d1e604` and 3 of 3 builds of
commit `3bbe3bbe` gave one SHA-256 each (Python 3.13.15, one host, one work path). That is a measurement, not a
proof. Another host, Python, work path, or dependency version can give another SHA-256. The executable also holds
the commit hash (the build stamp of the mapper), so each commit has its own SHA-256. Publish the `SHA256SUMS`
of the build that you release. Do not rebuild and publish the old `SHA256SUMS`.

macOS (UNVERIFIED, no one ran it on a Mac):

```bash
python3 scripts/build_binary.py        # darwin-x86_64 on Intel, darwin-aarch64 on Apple silicon
```

Windows (UNVERIFIED, no one ran it on Windows):

```powershell
py -3.13 scripts\build_binary.py       # simplicio-loop-v<version>-windows-x86_64.exe
```

Linux aarch64 uses the Linux commands on an aarch64 machine (UNVERIFIED).

### Attach to a GitHub Release

Put the assets of all systems in one directory. Then write one `SHA256SUMS` for all of them. Record the
Python packages of each build too, because the SBOM does not list them all (see "Limits"):

```bash
python3 scripts/build_binary.py --checksums-only dist/binary --version <version>
python3 scripts/sbom_generate.py generate --artifact dist/binary/simplicio-loop-v<version>-linux-x86_64 \
    --output dist/binary/sbom-linux-x86_64.json
build/binary/venv/bin/python -m pip freeze > dist/binary/requirements-linux-x86_64.txt
gh release create v<version> --repo simpletibr/simplicio-loop --title "v<version>" --notes-file <notes> \
    dist/binary/simplicio-loop-v<version>-linux-x86_64 dist/binary/simplicio-loop-v<version>-darwin-aarch64 \
    dist/binary/SHA256SUMS      # one path for each asset, never a directory
```

Add an asset to a release that exists with `gh release upload v<version> --repo simpletibr/simplicio-loop <file>`.
Then write `SHA256SUMS` again and upload it with `--clobber`.
By the contract of issue #1575, the `update` command downloads the asset for its system, compares it with `SHA256SUMS`, and replaces the executable.

The optional `--binary` flag of `scripts/release_rehearsal.py run` runs `scripts/build_binary.py` on the
rehearsal copy, checks `SHA256SUMS` and `--version`, and writes `sbom-binary.json`. It needs network
and takes minutes. It is off by default.

### Limits

- Build one executable on each system. No one ran the Linux build on another distribution.
- Linux: the executable bundles `libstdc++` and the other libraries of the build host. The build here
  needs glibc 2.38 or newer (Ubuntu 24.04 or newer, Debian 13 or newer). A system Python 3.14 from the
  same host raised the need to glibc 2.42. For a wider range, build on an older distribution, for
  example Debian 12 or Ubuntu 22.04. UNVERIFIED: no one made that build.
- macOS: no code signing and no notarization. Gatekeeper blocks the download until the user removes the
  quarantine attribute (`xattr -d com.apple.quarantine <file>`). UNVERIFIED.
- Windows: no code signature. SmartScreen warns about an unknown publisher, and some antivirus programs flag
  one-file PyInstaller programs. The operator links are hard links or copies, not symbolic links, and the
  owner and mode checks of the link directory do not run. UNVERIFIED.
- The executable cannot run `pip`. The `-m pip` commands of the old `update` and operator bootstrap fail
  in the binary. The binary must update itself by replacing the file.
- The executable cannot run `python -m pytest` or any module that the build did not bundle.
  A `--verify` command that calls `pytest` on `PATH` uses the pytest of the user.
- The one-file executable unpacks about 100 MB into the temporary directory at each start. A system
  where `/tmp` has the `noexec` mount option must set `TMPDIR` to another directory.
- The SBOM lists the Python dependencies of `pyproject.toml`. It does not list the transitive Python packages
  that the executable holds (for example `anyio`, `attrs`, `certifi`, `h11`, `httpcore`, `idna`, `requests`,
  and `urllib3`), and it does not list the native libraries that PyInstaller bundles, such as `libssl` and
  `libstdc++`. The `pip freeze` file above lists the Python packages. Nothing lists the native libraries.
- The module `_sysconfigdata` of the build Python is in the executable. It holds the install prefix of
  that Python. `simplicio_loop/operator_bootstrap.py` calls `sysconfig.get_path`, which reads that module, so it stays.
- The build downloads the dependencies at build time, and `pyproject.toml` sets only lower limits. Two builds on
  different days can hold different versions of a dependency. They then have different SHA-256 values.

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
