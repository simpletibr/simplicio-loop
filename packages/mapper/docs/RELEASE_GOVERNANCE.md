# Manual release governance

This is the canonical manual release path for Simplicio Mapper. GitHub Actions
are not required. Every command is fail-closed: missing registry data,
credentials, signatures, SBOMs, consumer acknowledgements, or benchmark
evidence keeps the release in canary.

## State model

A release moves through these states:

1. **built** — wheel and sdist exist and their SHA-256 digests are in the
   component manifest;
2. **signed canary** — the manifest includes a CycloneDX SBOM digest and a
   valid Ed25519 signature;
3. **stable** — PyPI and npm expose the same version, the direct consumer
   acknowledges within 15 minutes, compatibility is not breaking, and
   benchmark evidence has no regression;
4. **revoked** — an immutable release remains available for audit, but a
   deterministic rollback plan restores the previous consumer pin.

Never move or replace an existing tag or registry artifact.

## Prerequisites

- a clean release commit with all version sources synchronized;
- an external Ed25519 private key in an access-controlled file;
- authenticated PyPI, npm, and GitHub sessions;
- current downstream consumer acknowledgement and benchmark evidence.

Install release-only cryptography support:

```bash
python -m pip install -e '.[release]'
```

The private key must never be committed, printed, placed in a command-line
argument, or copied into the manifest. The CLI reads it from the path passed
to `--key` and embeds only the public key and its SHA-256 key identifier.

## 1. Validate and build

```bash
python scripts/check-version-sync.py
python scripts/check_schema_registry_sync.py
npm run lint
npm test
npm run docs:build
npm run test:e2e -- --reporter=list,html
python -m pytest tests/python -q
python -m build --wheel --sdist
python -m twine check dist/*
```

A baseline failure must be recorded and fixed or explicitly separated before
release. Do not infer success from a tag, source version, or one passing test.

## 2. Generate, sign, and verify the manifest

```bash
simplicio-mapper release-manifest --json --root . --dist-dir dist > component-release.json
simplicio-mapper release-governance sign \
  --manifest component-release.json \
  --key /secure/path/mapper-release-ed25519.pem \
  --output component-release.signed.json \
  --sbom-output simplicio-mapper.cdx.json
simplicio-mapper release-governance verify \
  --manifest component-release.signed.json
```

The signing command creates a deterministic CycloneDX 1.6 SBOM, attaches its
digest, and signs the canonical manifest with Ed25519. Any altered field,
artifact digest, SBOM digest, public key, or signature fails verification.

## 3. Classify compatibility

Compare the signed candidate with the previous immutable manifest:

```bash
simplicio-mapper release-governance classify \
  --previous contracts/component-release/v1/fixtures/0.26.25.json \
  --current component-release.signed.json
simplicio-mapper schema-compat --json --fail-on-breaking
```

Removed capabilities/protocols, changed or removed schema versions, and
compatibility-range changes are breaking. A breaking candidate cannot be
presented as compatible.

## 4. Publish both registries and verify parity

Publish only through authenticated local tooling after dry-run inspection:

```bash
python -m twine upload dist/*
npm publish --access public
```

Read the exact versions back from both registries, then run:

```bash
simplicio-mapper release-governance parity \
  --manifest component-release.signed.json \
  --pypi-version X.Y.Z \
  --npm-version X.Y.Z
```

A missing, unpublished, or divergent registry blocks stable. Do not dispatch a
stable event while this command is non-zero.

## 5. Canary, reconciliation, and stable promotion

Build the default canary event:

```bash
python scripts/build_release_event.py \
  --manifest component-release.signed.json \
  --output release-event.json \
  --github-dispatch-payload
```

The authenticated release operator may send the resulting payload with
`gh-axi api`. Consumers deduplicate by `event_id`.

Periodic polling should download immutable release manifests, retain processed
event IDs in an append-only ledger, and reconcile missed events:

```bash
simplicio-mapper release-governance reconcile \
  --manifest previous-release.json \
  --manifest component-release.signed.json \
  --ledger release-event-ledger.json
```

The result is version-ordered, omits processed IDs, and collapses duplicates.

After the direct consumer is green, evaluate promotion:

```bash
simplicio-mapper release-governance promote \
  --previous previous-release.json \
  --manifest component-release.signed.json \
  --pypi-version X.Y.Z \
  --npm-version X.Y.Z \
  --downstream-ack-minutes 15
```

Only `promote-stable` authorizes a stable event:

```bash
python scripts/build_release_event.py \
  --manifest component-release.signed.json \
  --output stable-release-event.json \
  --github-dispatch-payload \
  --channel stable
```

## 6. Rollback and revocation

Rollback never deletes or replaces immutable artifacts:

```bash
simplicio-mapper release-governance rollback \
  --current component-release.signed.json \
  --previous previous-release.json \
  --reason consumer-regression \
  --output rollback-plan.json
```

The deterministic plan revokes the current release, restores the previous
consumer pin, emits an idempotent rollback event, and retains all artifacts.

## Installed conformance fixtures

The wheel includes current and previous component-release fixtures under:

- `contracts/component-release/v1/fixtures/0.26.26.json`
- `contracts/component-release/v1/fixtures/0.26.25.json`

They are historical conformance evidence. Their unsigned status is explicit
and must never be interpreted as a valid signature.
