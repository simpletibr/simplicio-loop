# Mapper release train (#232)

The Dev CLI consumes `simplicio.component-release-event/v1` from Mapper. The
checked-in workflow is deliberately fail-closed:

1. `release-train-reconcile.yml` accepts a direct event or a
   `repository_dispatch` envelope, rejects revoked/yanked/incompatible
   releases, updates only the Mapper lower bound, resolves the exact candidate
   in `uv.lock`, and records event plus artifact digests in
   `config/release-train-lock.json`.
2. The fixed `release-train/mapper-latest` branch and concurrency group make
   retries update one bump PR. No event creates a second PR.
3. `release-train-gate.yml` verifies the installed candidate, lock digests,
   Mapper contract lanes, and the real map → retrieve → mechanical edit → test
   → receipt smoke. Missing N-1 evidence is `UNVERIFIED`, never green.
4. `release-train-promote.yml` enables auto-merge only after that gate has a
   successful workflow conclusion.
5. `release-train-drift.yml` opens one deduplicated issue when the installed
   Mapper drifts from the declared or last-tested state without a justification.
6. `publish.yml` verifies the tag and PyPI artifact digests, builds the signed
   Dev CLI component manifest, and dispatches Loop only after PyPI confirms the
   exact artifacts.

## Local evidence

```bash
uv sync --extra dev --frozen
mkdir -p .simplicio/release-train-sources
git clone --quiet --depth 1 --branch v0.26.28 \
  https://github.com/wesleysimplicio/simplicio-mapper.git \
  .simplicio/release-train-sources/n
git clone --quiet --depth 1 --branch v0.26.27 \
  https://github.com/wesleysimplicio/simplicio-mapper.git \
  .simplicio/release-train-sources/n-minus-1
PYTHONPATH=. .venv/bin/python scripts/release_train_conformance.py \
  --root . --event config/release-train-lock.json \
  --n-minus-1-version 0.26.27 \
  --mapper-source .simplicio/release-train-sources/n \
  --n-minus-1-source .simplicio/release-train-sources/n-minus-1 \
  --output .simplicio/release-train-conformance.json
```

The published Mapper wheel currently does not ship its `contracts/` tree, so
the contract lane uses exact immutable Mapper tag checkouts instead of treating
the installed wheel as if it contained source-only fixtures. A missing or
commit-mismatched checkout reports `UNVERIFIED`; the local map/edit smoke and
the Dev CLI release-train tests remain observable and digest-bound and must not
be promoted as a substitute for that missing lane.

GitHub Actions are disabled for this repository (`actions/permissions` is
`enabled: false`), so an empty check set is not evidence of success. Attach
the local quality-gate receipt and the conformance receipt to the PR; do not
auto-merge while either is `UNVERIFIED`.

Rollback is event-driven: a revoked, recalled, yanked, or withdrawn Mapper
event is rejected and the last immutable lock remains untouched. The
published Dev CLI manifest is required to carry signature, SBOM, and
provenance values before Loop propagation.
