# ADR 0011: setup installs the gh and uv releases pinned in this version

- **Status:** Accepted
- **Date:** 2026-10-10
- **Issue:** #1657 (point 5 of #1637: provenance of the release)

## Context

`simplicio-loop setup` downloads the GitHub CLI (`gh`) and `uv` when they are missing. Until now it took the latest
release from the GitHub API and checked the archive against the checksums file of the same release. That protects
against a corrupted download, not against a release that the vendor replaced as a whole.

Options considered:

- (a) verify the vendor's provenance attestation during setup. Circular for `gh` (it would need a `gh` to check the
  `gh` it installs), and it adds a second trust root and a runtime dependency.
- (b) pin the version and the SHA256 of each archive in the repository, and update the pins by a reviewed change.
- (c) keep only the checksum of the same release. Nothing new, and no protection against a replaced release.

## Decision

(b). `simplicio_loop/setup_pins.json` holds, per tool and platform, the tag and the SHA256 of the archive.
`prereqs.ensure` installs only the pinned tag, and only when the downloaded archive matches the pin and its release
checksums. The archive is refused before it is opened. A tool or platform without a pin is not downloaded; setup names
the install page instead. `scripts/update_release_pins.py` writes the pins from the latest releases, and a maintainer
checks each archive with `gh attestation verify` before committing the file.

## Consequences

- Setup installs an older release than the newest one, until the pins are updated.
- Every pin update is a PR; six platforms times two tools.
- Provenance is checked once, by the maintainer, with a `gh` that has `attestation`. Setup itself does not check it.
- UNVERIFIED: the real pins need network. The shipped file has no release, so until it is filled setup installs neither
  gh nor uv and says so.
- UNVERIFIED: `uv` attestations as a stable contract, and macOS and Windows archives under real release conditions.
