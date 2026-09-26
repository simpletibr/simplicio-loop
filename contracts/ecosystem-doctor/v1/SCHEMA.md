<!-- simplicio-contract:begin -->
contract: ecosystem-doctor/v1
schema: simplicio.contract-doc/v1
purpose: The doctor is a read-only, fail-closed pre-planning receipt.
rules: The JSON schema next to this file is authoritative; mutable data lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# `simplicio.ecosystem-doctor/v1`

The doctor is a read-only, fail-closed pre-planning receipt. It probes the
checkout and installed distributions without changing packages or provider
configuration. Each component reports one of `available`, `missing`,
`disabled`, `degraded`, or `incompatible`, plus its observed version,
entrypoints, capabilities, supported schemas and evidence-backed SHA.

`standalone` requires Loop, Mapper and Dev CLI. Runtime is optional
and is reported as an explicit fallback. `full-stack` requires all four
components. A required mismatch makes `ready=false` and exits non-zero.

When persistence is enabled, the exact receipt is bound by a `handshake_sha`
and appended under the loop journal lock with phase `pre_planning`. The doctor
never upgrades silently; every non-ready component carries a deterministic
remediation instruction.
