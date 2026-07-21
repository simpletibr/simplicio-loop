# Mapper quality gate (#320)

The Mapper release gate is intentionally split into evidence-producing lanes:

- json-boundaries.yml is the fail-closed inventory gate for exact internal-state exceptions.
- mapper-quality-gate.yml runs the inventory, Python tests, Node tests and package-content check on Linux, macOS and Windows.
- The Runtime lane installs simplicio-runtime, runs the non-JSON ecosystem doctor, and requires a Runtime result before release.
- Every lane writes Markdown; unavailable performance or HBP receipt evidence is written as null with a reason, never as zero and never as an internal JSON report.

## Release rules

A release is blocked when:

1. an internal JSON path is unclassified, expired or malformed;
2. Python, Node, package or cross-platform jobs fail;
3. Runtime conformance is unavailable or fails;
4. a benchmark or receipt is claimed without an observed value.

The current TOML inventory intentionally retains legacy .simplicio and .orchestrator artifacts until the published Runtime HBP/HBI migration contract is consumed by Mapper. Those entries are migration exceptions, not a claim that the artifacts are already binary.

## Remaining Runtime-dependent work

The Mapper cannot safely invent an HBI payload schema. Runtime must publish the semantic index sections and conformance vectors before Mapper replaces its index writers. Once that contract lands, remove the dated exceptions, add migration/rollback fixtures, and keep the Runtime lane required.
