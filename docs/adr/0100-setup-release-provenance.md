# ADR 0100: Release provenance for gh and uv installed by `setup` (#1657, point 5 of #1637)

Status: accepted

## Context

`release_fetch.install_binary` downloads the `gh` and `uv` release archives and checks their SHA256 against the
`checksums.txt` published in the same release. That detects corruption and a tampered mirror, but it does not
protect against a compromised release, because the attacker controls both the archive and its checksum file.

Three options were evaluated:

- **(a) Verify the provenance attestation** the vendor publishes (for example `gh attestation verify`).
  Verifying `gh` needs a trusted `gh` already installed (chicken and egg), and `uv` would need `gh` as a new hard
  prerequisite just to install itself. It also adds a network call to the GitHub attestation API on every setup.
- **(b) Pin version and hash in the repository** and update them by pull request. This is the only option that
  closes the compromised-release gap, but every gh/uv release then needs a repository change, and a stale pin
  leaves users on old, possibly vulnerable binaries.
- **(c) Keep the same-release checksum only** and document the residual risk.

## Decision

Option **(c)**: keep the SHA256 check against the same release's `checksums.txt` and accept the risk of a
compromised vendor release. The residual risk is documented here and nowhere else is it papered over.

Why: the simplest option that works today. (a) is circular for `gh` and makes `gh` mandatory for `uv`; (b) adds a
recurring maintenance burden and ships stale binaries. The download is already restricted to exact HTTPS hosts
(`setup_hardening.is_allowed_download`), redirects are validated (`redirect_target`), probes run with a minimal
environment, and the installed files are recorded with their SHA256 so later runs execute exactly those files.

## Consequences

- A release compromised at the vendor (archive and checksum replaced together) is installed without detection.
- Users who need provenance can install `gh` and `uv` through their own package manager; `setup` then finds them
  on a safe PATH entry and downloads nothing.
- Revisit if the vendors ship a provenance format that can be verified offline with a pinned public key, or if
  `setup` gains a hard dependency on `gh` for another reason.

## Not verified

- UNVERIFIED: the actual asset hosts used by `gh` and `uv` releases beyond the three in
  `ALLOWED_DOWNLOAD_HOSTS` (no network access when this was written).
- UNVERIFIED: the attestation workflows of `gh` and `uv` on real releases; this ADR is based on the decision
  trade-offs, not on a run against a real release.
