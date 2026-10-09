# Repository Governance (#294)

Reproducible governance for repository **size**, **mirrors**, **documentation**, and
**quantitative claims**, implemented without ever rewriting history unsafely. This
document is the canonical "how to" that backs the acceptance criteria in
[issue #294](https://github.com/wesleysimplicio/simplicio-loop/issues/294). The
history-rewrite step (clone/worktree size target after migration) is explicitly
**out of scope** for this work — #294's own Definition of Done requires a separate,
written maintainer approval after the dry-run below.

## 1. Measured current state (read-only scan)

| Metric | Value | Source |
|---|---|---|
| Tracked tree size | ~19.2 MB (736 files) | `scripts/repository_budget.py` |
| Git pack (all history) | ~1.40 GiB | `docs/repo_size_report.json` (`git count-objects -vH`) |
| Distinct historical blobs | 11,239 (~4.1 GB uncompressed) | `docs/repo_size_report.json` |
| Dominant historical bloat | `rust/target/` build output + `video/out/` generated media | `docs/HISTORY_MIGRATION_PLAN.md` |

Re-measure any time:

```bash
python3 scripts/repo_history_scan.py --write-report   # historical blob inventory
python3 scripts/repository_budget.py                  # current-tracked tree budget + gate
```

## 2. Stop new growth (enforced on every commit/PR)

### 2.1 LFS routing — `.gitattributes`

Large generated media is routed to Git LFS **only inside the designated staging area
`assets/_lfs/`**:

```
assets/_lfs/**  filter=lfs diff=lfs merge=lfs -text
```

Deliberately **no global `*.mp4 filter=lfs` rule**: a stray video/archive committed
anywhere else (repo root, `docs/`, …) is treated as a raw, pack-inflating blob and is
**blocked** by the budget gate (rule 2 below), forcing it into `assets/_lfs/` or into
GitHub Releases / release artifacts. See `.gitattributes` for the full LFS + binary
normalization rules.

### 2.2 Forbidden media gate — `scripts/repository_budget.py`

The gate runs the two rules below against every tracked file (`git ls-files` +
on-disk stats — read-only, never rewrites a ref):

1. **Forbidden prefix** — a file under `video/out/`, `rust/target/`, `node_modules/`,
   `dist/`, or `build/` is blocked **unconditionally** (raw or LFS). These are ephemeral
   / gitignored outputs, reproduced by build tooling or fetched from Releases — they
   must never live in the git tree (AC: *"mídia em caminho proibido bloqueia"*).
2. **Large-media suffix** — a `.mp4`/`.mov`/`.webm`/`.avi`/`.wav`/`.mp3`/`.m4a`/`.flac`/
   `.ogg`/`.zip`/`.tar.gz`/`.tgz`/`.iso`/`.bin` committed **outside** `assets/_lfs/` is
   blocked unless `.gitattributes` routes it to LFS (AC: *"asset LFS permitido passa"*).

Plus the pre-existing size caps:

- **Per-file cap** `MAX_SINGLE_FILE_BYTES = 2 MiB` — a new file over the cap fails the
  gate; pre-existing oversized hero images are grandfathered in
  `scripts/repository_budget_baseline.json` but may not grow past `+25%` (AC: *"blob
  acima do limite bloqueia"*).
- **Line budget (owner rule: no file above 9000 lines)** — `MAX_LINES = 9000` applies to
  tracked TEXT files (valid UTF-8; binary blobs are exempt). A new text file over the cap
  fails the gate. A file already over the cap is recorded in the baseline under
  `known_long_files` and may only stay at its recorded size: growth fails, and so does a
  shrink until `--update-baseline` records it (so a regrowth cannot slip back under a stale
  record). A recorded file that is no longer a tracked text file also fails. Today only
  `simplicio_loop/runner.py` is recorded (9290 lines, owned by another session).
- **Total tree budget** — growth over the committed baseline past `THRESHOLD_GROWTH = 0.25`
  fails the gate. Regenerate the baseline deliberately with
  `python3 scripts/repository_budget.py --update-baseline` (never to silence a
  regression you have not reviewed).

### 2.3 How to reproduce media that is not in git

- Demo video/audio: regenerate from sources — `video/storyboard.master.json` +
  `video/build_composition.py` / `video/build_audio.py` (then `bash video/render.sh`).
  `video/out/` is gitignored; its content is derivable, never a source of truth.
- Rust build output (`rust/target/`): `cargo build` / `cargo test`.
- Packaged deliverables (`simplicio-loop_deliverables.zip`): rebuilt from
  `packaging/`.

## 3. History migration (dry-run only — explicit approval required)

`scripts/history_migration_plan.py --dry-run --write` computes (read-only, reusing the
real `repo_history_scan` object scan) that ~8,605 historical blobs (~4.0 GB, ~98.6% of
historical bytes) match a conservative removal set (`rust/target/`, `video/out/`,
oversized historical media). It writes `docs/HISTORY_MIGRATION_PLAN.md` with a full
backup/rollback/communication/approval plan template.

**This repo contains NO code path that rewrites history.** `history_migration_plan.py`
has only a `--dry-run` mode; there is no `--execute`/`--apply` and no invocation of
`git filter-repo`/`filter-branch`/`bfg` anywhere in it (asserted by its own selftest).
A real rewrite requires the explicit maintainer sign-off described in that doc.

## 4. Canonical manifest & claims parity

- `scripts/canonical_manifest.py` ties `release_manifest` (version), skill count,
  runtime/adapter count, `CHANGELOG.md` latest version, `claims_manifest`, and
  `mirror_manifest` into one manifest + `check` gate. Run
  `python3 scripts/canonical_manifest.py check`.
- `scripts/claims_audit.py` fails the build on drift between README/PYPI/CHANGELOG and
  the manifest; a quantitative claim without a receipt is rendered `UNVERIFIED`
  consistently across surfaces (AC: *README/PYPI/changelog não divergem*; *percentuais
  sem receipt aparecem como UNVERIFIED*).
- `scripts/package_content_check.py` (`python3 scripts/check.py --package-content`)
  actually builds the sdist/wheel/npm pack and proves no media/mirrors leak into the
  published artifacts (AC: *wheel/npm/plugin não incluem arquivos pesados*).

## 5. CI / local enforcement

GitHub workflow files exist under `.github/workflows/`, but they are not a required gate or
evidence source for this work and were not executed here. The governance gates are enforced
**locally**, not by relying on CI:

```bash
# Pre-push hook (fail-closed, runs the mandatory core gate incl. repo-budget):
printf '#!/bin/sh\npython3 scripts/check.py --core-gate\n' > .git/hooks/pre-push
chmod +x .git/hooks/pre-push

# Or run any gate on demand:
python3 scripts/check.py                 # audit + tests + loop-contract + token-budget + repo-budget
python3 scripts/check.py --repo-budget   # repository size budget gate only
python3 scripts/check.py --audit-only    # claims/manifest parity only
python3 scripts/repository_budget.py selftest   # gate self-tests
```

The README CI badge honestly reflects this ("locally enforced") instead of pointing at a
dead `actions/workflows/ci.yml` badge. Re-adding a live GitHub Actions badge is gated on
restoring Actions billing (per `docs/RELEASE.md`) and then wiring `.github/workflows/ci.yml`
to run the same `scripts/check.py` gates.

## 6. Required gates (acceptance criteria → where enforced)

| Acceptance criterion | Enforced by |
|---|---|
| Blob acima do limite bloqueia | `repository_budget.py` per-file cap |
| Mídia em caminho proibido bloqueia | `repository_budget.py` forbidden-prefix rule |
| Asset LFS permitido passa | `repository_budget.py` LFS-exempt rule + `.gitattributes` |
| Manifest detecta versão/skill/adapter/launcher/installer divergentes | `canonical_manifest.py check` |
| Claim quantitativo sem receipt não aparece como medido | `claims_audit.py` check 8 + `canonical_manifest` |
| Receipt de outro commit/versão rejeitado | `claims_manifest.py` receipt validation |
| README/PYPI/changelog driftam → gate falha | `claims_audit.py` |
| Package build não inclui artifacts/mídia | `package_content_check.py` (`--package-content`) |
| Dry-run de migração não altera refs | `history_migration_plan.py` dry-run-only (selftest asserts no rewrite call) |
| Clone do snapshot migrado preserva código/tags/testes | **Out of scope** — requires approved history rewrite |
