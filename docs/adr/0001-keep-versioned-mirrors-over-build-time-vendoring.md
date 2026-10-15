# ADR-0001 — keep versioned `plugin/`/`_bundle/` mirrors + automated sync (close #117 as won't-do)

- **Status:** accepted (the `_bundle/` half superseded by #1817: `simplicio_loop/_bundle/` is now
  generated at build time, git-ignored and no longer versioned; `plugin/` stays versioned and checked)
- **Date:** 2026-07-07
- **Supersedes / relates to:** none. Resolves the #117 vs #98 fork in strategy.

## Context

Two competing proposals exist for how `plugin/` (the lean marketplace plugin tree) and
`simplicio_loop/_bundle/` (the pip-package bundle) stay in sync with the real source
(`.claude/skills/`, `hooks/`, the lean `scripts/`/`tests/` subsets):

- **#98 (shipped)** — keep the mirrors **versioned in git** and sync them automatically:
  `hooks/pre-commit.py` detects a staged change under a watched source path
  (`.claude/skills/`, `hooks/`, `scripts/`) and runs `scripts/sync_plugin.py`, which rewrites
  `plugin/` and stages the regenerated files into the same commit. `scripts/claims_audit.py`
  check 4/5 (`bundle-parity`/`plugin-parity`) is the fail-closed backstop: if the pre-commit hook
  didn't run (or failed open), `python3 scripts/check.py` catches the drift before it lands on
  `main`.
- **#117 (proposed, not implemented)** — stop versioning the mirrors at all; generate `plugin/`
  and `simplicio_loop/_bundle/` at **build/package time** instead (e.g. a `setup.py`/packaging
  build step, or a marketplace-publish step), so there is nothing to keep in sync in git and
  nothing for `claims_audit.py`'s parity checks to enforce.

#117 itself says the two approaches are "mutually substitutable — decide which strategy to adopt
… if the maintainer prefers versioned mirrors, close this in favor of #98."

## Decision

**Keep #98's shipped approach — versioned mirrors + automated pre-commit sync + the fail-closed
`claims_audit.py` parity backstop. Close #117 as won't-do, superseded by #98.**

Rationale:

1. **#98 is already shipped and working.** `hooks/pre-commit.py` + `scripts/sync_plugin.py` +
   `scripts/claims_audit.py` checks 4/5 exist today, are tested (`tests/test_system_check.py::
   test_sync_plugin_check_verb_runs_without_crashing`), and were re-verified passing as part of
   this same change (see below). Ripping that out for an unbuilt, unproven build-time-vendoring
   design would be a large, risky, backwards move to make unilaterally in an automated pass.
2. **Lower coordination risk.** #117's approach needs the generation step wired into BOTH the pip
   packaging build AND the Claude marketplace publish path (`.claude-plugin/marketplace.json`
   `source: ./plugin` expects a real, already-populated directory in the repo tree the marketplace
   clones — there is no build step in that flow to hook a generator into). Versioned mirrors need
   no such coordination: what's in git is exactly what a `pip install` or a marketplace install
   gets, with no separate generation step that can silently go stale relative to a given commit
   SHA/tag.
3. **The parity check is strictly stronger than "trust the build step".** `claims_audit.py`
   checks BOTH directions (source → mirror: nothing missing; mirror → source: no orphan file from
   a rename/delete still shipping) on every `check.py` run, local or CI. A build-time generator
   only ever proves itself at package-build time, not on every commit.
4. **No evidence #117's approach is measurably better.** #117 didn't land an implementation to
   compare against; #98 has a working, tested one. Absent a demonstrated problem with #98 in
   practice, switching costs (git history bloat concerns are the usual argument for #117 — see the
   Known Gap below, which is a real but separate size problem) don't outweigh the risk of a
   from-scratch build-time rewrite.

## Known gap discovered while writing this ADR (flagged, not fixed here)

`hooks/pre-commit.py`'s docstring and inline comment both claim it "auto-sync[s] `plugin/` and
`_bundle/`" — but the actual code only calls `scripts/sync_plugin.py` (which writes `plugin/`) and
only stages `git add plugin/`. **`simplicio_loop/_bundle/` is NOT auto-synced by this hook at
all** — it was kept in parity manually while implementing #119/#121/#118 in this same PR (the new
`.claude/skills/simplicio-loop/references/*.md` files and the shrunk `SKILL.md` were `cp`-ed into
`simplicio_loop/_bundle/skills/simplicio-loop/` by hand, then verified with `scripts/
claims_audit.py`). This is a real, pre-existing gap in #98's implementation (docstring promises
more than the code does), independent of the #117-vs-#98 decision above. **Recommended follow-up
(out of scope for this PR):** either extend `hooks/pre-commit.py` to also regenerate/stage
`simplicio_loop/_bundle/` (mirroring what `sync_plugin.py` does for `plugin/`), or correct the
docstring to stop claiming it does. File a new issue rather than silently patching the hook here —
this ADR's job is the #117-vs-#98 decision, not a #98 bugfix.

## Verification

- `python3 scripts/claims_audit.py` — checks 4 (`bundle-parity`) and 5 (`plugin-parity`) both
  PASS as of this commit (re-verified after the #119 SKILL.md shrink added 8 new reference files
  and a resync of both mirrors).
- `python3 scripts/check.py` — full local gate PASS.

## Consequences

- #117 should be closed on GitHub with a comment pointing at this ADR and recommending
  won't-do/superseded-by-#98, per the issue's own text inviting that outcome.
- The known `_bundle/` auto-sync gap above should get its own issue; this ADR intentionally does
  not fix it (scope discipline — #117 asked for a decision doc, not a `hooks/pre-commit.py` patch).
- No `.gitignore`-the-mirrors refactor, no build-time generation step, and no history rewrite were
  performed as part of this decision.
