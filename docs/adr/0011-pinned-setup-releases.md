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
checksums. The archive is refused before it is opened. `ensure` takes the pins as a required argument: a tool or
platform without a usable pin is refused with reason code `no_pin` and nothing is downloaded; setup names the install
page instead. `scripts/update_release_pins.py` writes the pins from the latest releases, and a maintainer checks each
archive with `gh attestation verify` before committing the file.

## Consequences

- The shipped pins are gh v2.102.0 and uv 0.13.0, for linux, macOS and Windows on amd64 and arm64 (six platforms per
  tool). Setup installs exactly these until a reviewed change replaces them.
- Setup installs an older release than the newest one, until the pins are updated.
- Every pin update is a PR; six platforms times two tools.
- MEASURED on 2026-10-10: all 12 pinned archives (gh v2.102.0 and uv 0.13.0, six platforms each) were downloaded again. The
  SHA256 of every one matches its pin, and `gh attestation verify <archive> --repo cli/cli` or `--repo astral-sh/uv` (run with
  the pinned gh 2.102.0) exited 0 for every one.
- Provenance is a maintainer step, not a setup step: before merging a new pin, the maintainer runs `gh attestation verify`
  on each archive with a `gh` that has `attestation`. Setup itself does not check it.
- UNVERIFIED: `uv` attestations as a stable contract, and macOS and Windows archives under real release conditions.
