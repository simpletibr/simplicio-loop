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
