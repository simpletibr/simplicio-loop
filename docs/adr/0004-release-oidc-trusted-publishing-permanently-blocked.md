# ADR-0004 — PyPI/npm Trusted Publishing (OIDC) permanently blocked pending a CI substrate — #292 Fase 5 sign-off

- **Status:** accepted
- **Date:** 2026-07-15
- **Relates to:** issue #292 (release/supply-chain P0, Fases 2/3/5/6/8/9), PR #328
  (`scripts/version_sync.py`, Fase 1), PR #349 (`scripts/release_verify.py` /
  `scripts/sbom_generate.py` / `scripts/install_smoke.py`, Fase 4/7 local subset), PR #365
  (`scripts/release_rehearsal.py` / `scripts/provenance_generate.py`, Fase 4/6 local subset),
  issue #311 (removal of the specific `distributed-183-proof.yml` workflow),
  `docs/adr/0003-attestation-and-sbom-policy.md` (accepts the local-provenance substitute as the
  frozen SBOM/attestation policy for the *release-verification gate*), `docs/RELEASE.md`,
  `docs/SUPPLY_CHAIN.md`.

## Context

Issue #292 Fase 5 requires: PyPI migrated to Trusted Publishing/OIDC, the static
`PYPI_API_TOKEN` removed from the normal publish path, npm using OIDC/provenance where
supported, per-job least-privilege permissions (`build: contents: read`, `attestation:
id-token` only, `publish: environment identity only`, `release: contents: write` with no
registry secret), third-party actions pinned by commit SHA, and no credential material or
partial hash ever printed.

Every one of these is, by construction, a property of a **CI workflow run**:

- OIDC/Trusted Publishing works because a CI job's `id-token: write` permission lets the
  runner request a short-lived JWT from the CI provider's own OIDC issuer, which PyPI/npm's
  Trusted Publishing endpoint then exchanges for a scoped upload credential tied to that exact
  `repository`/`workflow`/`environment`/`ref` combination. There is no equivalent flow for code
  invoked directly on a developer's machine — a local process has no CI-issued identity token
  to present, and fabricating one (e.g., a self-signed JWT claiming to be a GitHub Actions run)
  would not be honored by PyPI/npm's real OIDC verifiers, and even if it somehow were, it would
  be exactly the kind of fabricated supply-chain proof this issue exists to eliminate.
- Per-job permission separation, environment protection, and pinned third-party actions are
  properties of a `.github/workflows/*.yml` **file that executes on a runner**. Two workflows
  exist (`simplicio-status-sync.yml` and `windows-progress-smoke.yml`), but neither provides
  `id-token: write`, Trusted Publishing, or a release gate, and neither was used as evidence for
  this work. No CI substrate with those required capabilities is configured.

Three prior rounds of work on this issue (PRs #328, #349, #365) each independently re-examined
this constraint before writing any code and reached the same conclusion — recorded in the
issue's own comment thread and in `docs/RELEASE.md`/`docs/SUPPLY_CHAIN.md`: Fase 5 is not an
implementation gap that a cleverer local script could close, it is a structural precondition
this repository does not currently satisfy. This round re-verified that conclusion again by
re-reading the full issue AC list and `docs/RELEASE.md` fresh, and it still holds: no CI
substrate exists, so no OIDC token can be minted, so Fase 5 cannot be produced, full stop.

## Decision

**Fase 5 (OIDC/Trusted Publishing for PyPI and npm) is formally accepted as a permanent,
structural blocker — not a TODO, not a gap in this round's scope, and not something a future
round should re-attempt without first confirming the precondition below has changed.**

1. This ADR is the single, durable, signed-off record of that decision, matching the pattern
   already used for issue #290's attestation-policy narrowing
   (`docs/adr/0003-attestation-and-sbom-policy.md`). (The earlier record for issue #289's OIDC
   broker exchange lived in the distributed-worker ADR, removed with that stack in 3.46.0; see
   git history.)
2. The **precondition for revisiting this decision** is explicit and mechanically checkable: a
   CI identity provider capable of minting an OIDC token with `id-token: write` semantics exists
   again in this repository — either a workflow with those release/OIDC controls is introduced,
   or an equivalent CI substrate lands with OIDC-equivalent capability. Until then, no amount of
   local tooling closes Fase 5; re-attempting it without that precondition is out of scope by
   construction and reviewers should reject any PR claiming otherwise.
3. **The accepted interim approach for everything Fase 5 blocks that has a real local
   substitute is the local-provenance chain already shipped in PR #365 and governed by
   `docs/adr/0003-attestation-and-sbom-policy.md`:** `scripts/provenance_generate.py` produces a
   real, gpg-signed, in-toto/SLSA-`Statement/v1`-shaped provenance record from actual git
   commit + build-artifact digest data, explicitly labeled `ci_attested: false` / `oidc: false`
   / `builder_identity: "local-machine"` so it is never mistaken for CI-rooted attestation.
   `scripts/release_rehearsal.py` chains that alongside checksums, SBOM, and clean-room
   install-smoke into one composable pipeline rehearsal. This is the intentionally weaker,
   honestly-labeled trust root this repository operates under until the precondition in item 2
   is met — it is not presented as, and must never be upgraded in receipts to look like,
   OIDC-rooted proof.
4. **Everything downstream of Fase 5 that Fase 5 itself gates is carved out of this issue's
   Definition of Done as the same permanent, structural blocker**, not as separate unresolved
   work items:
   - Fase 2 (release governance via a protected `release` GitHub Environment with required
     status checks) and Fase 3 (a dedicated `build-release-artifacts` CI job with a fixed
     runner and `SOURCE_DATE_EPOCH` control) are GitHub-Actions-shaped by definition and have
     nowhere to execute.
   - Fase 6's PyPI/npm legs (publish the build-once artifact set, byte-identical, to each
     registry) need an actual OIDC-authenticated publish target; nothing has been published to
     either registry from this repository as part of this work, and Fase 5 is the only path
     issue #292 specifies for authenticating that publish without a long-lived static token.
   - Fase 8 (idempotent partial-failure recovery across registries) depends on Fases 3/5/6
     existing first — there is nothing to recover a partial failure *of*.
   - Fase 9's PyPI/npm legs of delivery-truth reconciliation (`source_state.py` consuming real
     publish receipts) depend on a real publish having happened at all.

   The **GitHub-Release leg** of Fases 6/7/9 is explicitly **not** part of this carve-out: it
   does not require OIDC (GitHub Releases are authenticated by the repository's own `gh`
   credentials, not a registry Trusted Publisher), and `simplicio_loop/external_verifiers.py`
   already performs real, byte-level verification against it (downloads release assets,
   recomputes SHA-256, attempts `gh attestation verify`, parses SBOM, install-smokes the
   downloaded wheel). That leg is real and working today and is not blocked by this ADR.

## Consequences

- Issue #292 cannot be closed under its own literal Definition of Done (which requires OIDC
  replacing the static PyPI token) while this ADR's precondition remains unmet. Closing the
  issue therefore requires the issue itself to explicitly carve Fase 5 (and its structural
  dependents in item 4) out as "permanently blocked, tracked here, not part of this round's
  completion claim" — exactly the pattern this ADR formalizes — rather than silently declaring
  victory against a DoD line that cannot honestly be checked.
- Any future contributor picking up #292 (or a successor issue) should read this ADR first and
  check the precondition in Decision item 2 before spending effort on OIDC/Trusted Publishing
  again. If the precondition is unmet, that effort is better spent elsewhere until it changes.
- `docs/RELEASE.md` and `docs/SUPPLY_CHAIN.md` remain the operational/how-to documents (what
  commands exist, what they prove, how to run the local rehearsal); this ADR is the durable
  policy record of *why* Fase 5 and its dependents stay open, so that reasoning survives issue
  comment threads being summarized or truncated in future rounds.
- This ADR does not authorize skipping or weakening any other AC in #292 — Fase 4 (checksums,
  SBOM, provenance, signature) and Fase 7's local-build and GitHub-Release legs remain fully
  gated exactly as `docs/adr/0003-attestation-and-sbom-policy.md` already specifies.
