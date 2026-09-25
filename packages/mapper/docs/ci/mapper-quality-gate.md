# Mapper quality gate (#320)

The gate is local-first and does not require GitHub Actions or paid CI.

Run the fast policy gate:

    python scripts/mapper_quality_gate.py

Run all available local checks:

    python scripts/mapper_quality_gate.py --full

For a release decision, require every local tool and the installed Runtime:

    python scripts/mapper_quality_gate.py --release --full --require-tools --require-runtime \
      --evidence artifacts/release-evidence.toml

`--release` switches the scanner from the migration baseline to strict mode.
Strict mode rejects every owned JSON artifact, including a still-valid legacy
exception. Therefore the release command remains blocked until the binary/TOML
migration has removed the artifact; an inventory entry can never become a
release waiver.

Release mode also requires explicit TOML observations for
`cross_repository_e2e`, `performance`, `hbp_receipt`, and `hbi_conformance`.
Each `[evidence.<name>]` table must contain `observed = true` and a non-empty
`detail` describing versions, hashes, workload, receipt, or conformance result.
Missing, malformed, or negative observations remain `null`/`fail` and block
publication; the gate never converts absent evidence into a passing zero.

The command writes Markdown to artifacts/mapper-quality-summary.md. It never writes an internal JSON report. Missing evidence is recorded as null with a reason and is never treated as zero.

## What is checked

- exact TOML inventory and strict internal-JSON scanner;
- Python tests;
- Node unit tests;
- npm package contents;
- non-JSON simplicio-runtime ecosystem doctor;
- explicit unavailable markers for cross-repository E2E, performance observations and HBP receipts.

Run this command on Linux, macOS and Windows as part of the release checklist. The repository no longer adds a GitHub Actions workflow for this gate.

## Runtime-dependent work

The Mapper cannot invent the semantic HBI payload sections. Runtime must publish those sections and conformance vectors before the dated JSON exceptions can be removed and the index writers migrated. Until then, the local gate reports that dependency explicitly instead of labeling a custom mmap layout as HBI.
