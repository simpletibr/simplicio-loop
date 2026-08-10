# Scripts

Scripts should make the project runnable and verifiable without tribal knowledge.

Expected scripts:

- `start.ps1` / `start.sh`: start local services or print the commands to start them.
- `test.ps1` / `test.sh`: run the project's relevant validation.
- `evidence.ps1` / `evidence.sh`: capture Playwright evidence for a smoke scenario.
- `update-starter.ps1` / `update-starter.sh`: update the installed starter structure safely.

Adapt these scripts to the real stack after applying the starter.

Rules:

- Fail with a non-zero exit code on errors.
- Print clear next steps when a required command is missing.
- Keep secrets out of scripts.
- Prefer environment variables for URLs and credentials.

Update command:

```powershell
.\scripts\update-starter.ps1
```

Use `LLM_PROJECT_MAPPER_SOURCE` to test from a local clone instead of npm:

```powershell
$env:LLM_PROJECT_MAPPER_SOURCE="C:\Users\you\source\repos\llm-project-mapper"
.\scripts\update-starter.ps1
```

## `check-version-sync.py` (issue #102)

Fails if the three release version pins disagree:

- `package.json` → `"version"`
- `pyproject.toml` → `version = "..."`
- `simplicio_mapper/__init__.py` → `__version__ = "..."`

```bash
python scripts/check-version-sync.py
# optional Node twin (same contract):
node scripts/check-version-sync.js
```

CI: `.github/workflows/version-sync.yml` on PR/push to `main`. Documented in
`.specs/workflow/RELEASE.md` (version bump checklist).

## `meta_issue_audit.py` (issue #328)

Builds the deterministic `simplicio.meta-issue-audit/v1` inventory from the
public GitHub API or an offline JSON export. The command is read-only with
respect to GitHub, redacts credential-shaped values, and supports a non-writing
freshness check:

```bash
python scripts/meta_issue_audit.py --fetch --repository wesleysimplicio/simplicio-mapper --output docs/evidence/issue-328-meta-audit.json
python scripts/meta_issue_audit.py --fetch --repository wesleysimplicio/simplicio-mapper --output docs/evidence/issue-328-meta-audit.json --check
```

See [`docs/issue-meta-audit.md`](../docs/issue-meta-audit.md) for the schema,
failure behavior, closure policy, and offline replay instructions.

## `generate-ecosystem-doc.py` (issue #156)

Regenerates [`SIMPLICIO_ECOSYSTEM.md`](../SIMPLICIO_ECOSYSTEM.md) from real
package metadata instead of hand edits:

```bash
python3 scripts/generate-ecosystem-doc.py            # regenerate + write
python3 scripts/generate-ecosystem-doc.py --check    # verify freshness (CI), exit 1 if stale
```

Sources of truth:

- **Current version** — `pyproject.toml` and `package.json` (`version = "..."` /
  `"version": "..."`); the script errors out if these two disagree rather than
  silently pick one.
- **Who depends on this repo** — `scripts/ecosystem-consumers.json`
  (schema `simplicio.ecosystem-consumers/v1`), a manually maintained fixture
  since this repo has no live cross-repo access:

  ```json
  {
    "schema": "simplicio.ecosystem-consumers/v1",
    "consumers": [
      {
        "name": "simplicio-dev-cli",
        "repo": "https://github.com/wesleysimplicio/simplicio-dev-cli",
        "min_version": "0.15.0",
        "constraint_source": "pyproject.toml dependency `simplicio-mapper>=0.15.0`"
      }
    ]
  }
  ```

  Update it by hand whenever a consumer repo bumps its declared
  `simplicio-mapper` floor. Each consumer's `min_version` is compared against
  the real current version and classified as `current`, `behind` (a stale
  constraint that trails the current release — reported as a note, not a
  failure), or `ahead` (the consumer expects a version that has not shipped
  yet — a hard divergence that fails both the default run and `--check`).

`SIMPLICIO_ECOSYSTEM.md` carries a **"generated file, do not hand-edit"**
notice at the top for this reason — edit `scripts/ecosystem-consumers.json`
or bump the version instead, then re-run the generator. CI runs `--check`
(see `.github/workflows/python-ci.yml`) so a stale doc fails the build.

## `simplicio-mapper contract validate` / `scripts/regen_contract_fixtures.py` (issue #157)

The JSON shape of `.simplicio/*.json` mapper artifacts is a versioned,
testable contract under
[`contracts/mapper-artifacts/v1/`](../contracts/mapper-artifacts/v1/README.md).
See that README for schemas, fixtures, the validate command, and how
downstream repos (simplicio-dev-cli, simplicio-loop, simplicio-runtime)
should consume the fixtures in their own tests.

## `simplicio-mapper doctor --contracts` / `scripts/validate_ecosystem_contracts.py` (issue #164)

Extends the above to two cross-repo payloads that originate *outside*
`simplicio-mapper`: the `simplicio-loop` run-journal/task-anchor execution
record and the `simplicio-dev-cli` 6-layer executor contract record, under
[`contracts/ecosystem/v1/`](../contracts/ecosystem/v1/README.md). That
README documents, in full and without spin, that the two schemas are
**hand-written local copies** (not a live cross-repo import — this repo has
no git access to those other repos at contract-authoring time) and the
convention for keeping them in sync.

```bash
simplicio-mapper doctor --contracts       # validates both contract roots at once
python3 scripts/validate_ecosystem_contracts.py   # standalone, stdlib-only, vendorable copy
```

`scripts/validate_ecosystem_contracts.py` is deliberately dependency-free
and does not import `simplicio_mapper` — it is meant to be copy-pasted into
`simplicio-loop`/`simplicio-dev-cli`'s own repos (`--schema-root` points it
at a vendored copy of the schemas) rather than shared as an installed
package dependency.

## `critical_coverage_gate.py` / `perf_regression_gate.py` (issue #222)

The CI Quality Gate (`.github/workflows/quality-gate.yml`) blocks merges
that regress precision, contract compatibility, or performance. See
[`docs/ci/quality-gate.md`](../docs/ci/quality-gate.md) for the full
breakdown of what's checked and the documented regression tolerances.

```bash
python -m pytest tests/python -q --cov=simplicio_mapper --cov-report=json:coverage.json
python scripts/critical_coverage_gate.py --coverage-json coverage.json   # 85% global / 90% critical-path

python scripts/perf_regression_gate.py --json               # precision + latency + size + throughput vs docs/evidence/*.json baselines
python scripts/perf_regression_gate.py --skip-runtime-scale  # fast path, skips the ~5000-file throughput benchmark
```

## `simplicio-mapper release-manifest` / `scripts/check_schema_registry_sync.py` (issue #280)

Phase-0 slice of the cross-repo "release train" epic
(wesleysimplicio/simplicio-loop#558; see
[`.specs/architecture/ADR-010-release-manifest-phase0.md`](../.specs/architecture/ADR-010-release-manifest-phase0.md)
for the full scoping decision). Two pieces, both local/offline, no signing/
SBOM/network calls:

```bash
simplicio-mapper release-manifest --json     # simplicio.component-release/v1 manifest:
                                              # version, commit SHA, every schema-version,
                                              # release protocol list and artifact_digest
simplicio-mapper version --json              # compact release identity for consumers:
                                              # version, commit SHA, artifact_digest, protocols
                                              # schema versions
python3 scripts/check_schema_registry_sync.py                  # CI gate: registry vs committed baseline
python3 scripts/check_schema_registry_sync.py --update-baseline # regenerate baseline after a
                                                                  # deliberate, reviewed schema bump
```

This is a sibling to `scripts/check-version-sync.js` (which keeps
`package.json`/`pyproject.toml`/`simplicio_mapper/__init__.py` aligned) --
`check-version-sync.js` itself is unchanged; the new script covers the
separate, previously-uncovered surface of per-artifact schema-version
constants (`ARTIFACT_VERSION`, `CANONICAL_MAP_SCHEMA_VERSION`,
`CONTRACT_VERSION`, etc. -- full inventory in
`simplicio_mapper/release_manifest.py::SCHEMA_VERSION_REGISTRY`).
Cross-repo release events, canary channels, automatic downstream
(simplicio-dev-cli/simplicio-loop) version bumps, and any actual
signing/SBOM step remain explicitly out of scope here -- they need
coordinated infrastructure this repo does not own alone.

## `check-doc-sync.js` / `check-readme-sync.js` (issue #163)

Two checks that replace manual doc mirroring with either a generated file or
a CI gate:

```bash
node scripts/check-doc-sync.js check      # CLAUDE.md in sync with AGENTS.md? copilot-instructions.md still a short stub?
node scripts/check-doc-sync.js sync       # regenerate CLAUDE.md from AGENTS.md (run after editing AGENTS.md)

node scripts/check-readme-sync.js check   # README.md/README.pt-BR.md heading structure within baseline?
node scripts/check-readme-sync.js report  # print the current structural edit-distance, no gate
node scripts/check-readme-sync.js baseline # rewrite scripts/readme-sync-baseline.json to today's distance
```

`CLAUDE.md`'s own header used to say Claude Code needs a *regular file*
("não símbolo"), so a plain `ln -sf AGENTS.md CLAUDE.md` symlink was not
used here — instead `CLAUDE.md` is a **generated** file (fixed preamble +
`AGENTS.md` verbatim), same pattern as `SIMPLICIO_ECOSYSTEM.md` (issue #156)
and the mapper-artifacts contract fixtures (issue #157). `AGENTS.md` is the
one hand-edited source; edit it, then run `sync`.

`.github/copilot-instructions.md` used to be a near-complete hand-copy of
`AGENTS.md`'s shared sections (Stack/Comandos/Workflow loop/DoD/Proibido).
It is now a short stub (~55 lines) that points at `AGENTS.md` for all of
that and keeps only genuinely Copilot-specific content (Agent Mode custom
agents, `.github/copilot/agents/` mirror note). `check-doc-sync.js check`
fails if it grows back past a line-count ceiling or stops linking to
`AGENTS.md`.

`check-readme-sync.js` compares README.md/README.pt-BR.md's heading-*level*
sequence (not text — translations never match byte-for-byte) via edit
distance, and fails only when that distance goes **above** a committed
baseline (`scripts/readme-sync-baseline.json`) — a real, nonzero amount of
structural drift between the two files predates this script (a known,
separately-scoped translation gap), so this is a regression gate, not a
perfection gate. `tests/unit/check-readme-sync.test.js` proves the
mechanism itself catches an intentionally-desynced mirror using synthetic
fixtures, independent of today's real baseline.
