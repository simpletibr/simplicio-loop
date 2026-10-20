# Monorepo cutover checklist

Issue #1298 merged `simplicio-mapper` and `simplicio-dev-cli` into this
repository as `packages/mapper/` and `packages/dev-cli/` (issue #1343 later
deleted the Fast package, so it is no longer part of the stack). Each package
still ships and tags independently (see AGENTS.md § Releases in a monorepo), so
nothing about publishing changed — only *where the source lives* changed. This
is the maintainer checklist for archiving the now-obsolete standalone
repositories:

- `simpletibr/simplicio-mapper`
- `simpletibr/simplicio-dev-cli`

Do not archive a repo until every item under it is checked. Archiving is
reversible (a maintainer can unarchive), but do the verification first so it
never has to happen.

## 1. Verify before archiving anything

For **each** of these repositories:

- [ ] **PyPI is published from this repo's package tags, not the old repo.**
      Confirm the most recent release of `simplicio-mapper` /
      `simplicio-dev-cli` (`simplicio-cli` entry points) on PyPI matches a
      tag in `simpletibr/simplicio-loop` (`mapper-vX.Y.Z`, `dev-cli-vX.Y.Z`), by diffing the sdist against
      `packages/<pkg>/` at that tag. If the old repo's CI/workflows can still
      publish to PyPI, disable or delete those workflows (or revoke their
      PyPI trusted-publisher/token binding) before archiving, so an accidental
      push there can never ship a stale release again.
- [ ] **No open issues or PRs remain on the old repo.** For each open item:
      migrate it to a `simpletibr/simplicio-loop` issue/PR scoped to
      `packages/<pkg>/` (link back to the original for history), or close it
      with a comment pointing at the new location. `gh issue list --repo
      simpletibr/simplicio-<pkg> --state open` /
      `gh pr list --repo simpletibr/simplicio-<pkg> --state open` should
      both return empty before archiving.
- [ ] **The old repo's README has a banner pointing here.** Add (or verify)
      a top-of-file banner such as:

      ```markdown
      > **This repository has moved.** `simplicio-<pkg>` now lives at
      > [`simpletibr/simplicio-loop/packages/<pkg>`](https://github.com/simpletibr/simplicio-loop/tree/main/packages/<pkg>).
      > This repo is archived and read-only; open issues and PRs there instead.
      ```

      Commit and push that banner *before* archiving — GitHub still serves
      the README on an archived repo, so this is the only thing a visitor
      who lands there from an old link, bookmark, or search result will see.
- [ ] **Outbound links from this monorepo already point at the new home.**
      Issue #1298 item 1 repointed the ~6 doc/README references that named
      the old repos to `https://github.com/simpletibr/simplicio-loop/tree/main/packages/<pkg>`
      (`packages/mapper/README.md` and the three
      `packages/dev-cli/bench/*.md` evidence docs).
      Re-run this check before archiving to catch anything added since:

      ```bash
      grep -rn -E "wesleysimplicio/simplicio-(mapper|dev-cli)" . \
        --exclude=CHANGELOG.md --exclude-dir=.git | grep -v bench/llm_ab/results
      ```

      The legacy owner should have no hits except the deliberate `formerly
      wesleysimplicio/...` provenance notes in `packages/dev-cli/bench/*.md`,
      the verbatim CHANGELOG excerpts quoted by two mapper tests
      (`test_changelog_parser.py`, `test_release_surfaces.py`), and the
      reconciled receipt `packages/dev-cli/config/release-train-lock.json`
      (see section 2). Anything else should be updated.

## 2. Release-authority literals

`packages/dev-cli/simplicio/release_train.py`,
`packages/mapper/simplicio_mapper/release_manifest.py` and the
`packages/dev-cli/config/release-train-*.json` config name the canonical
`simpletibr/simplicio-{mapper,dev-cli,loop}` repositories as functional
identifiers: dispatch targets for the cross-repo release train,
required-repository sets, and authority-owner maps. Their own tests
(`test_cross_repo_conformance.py`, `test_verify_default_branch.py`, etc.) assert
them. They are the release automation's live GitHub API targets, so a change to
one is a functional migration: update the literal and every test that asserts
it in the same change. The reconciled receipt
`packages/dev-cli/config/release-train-lock.json` is the one exception. It is a
historical record that keeps the owner it was reconciled with, and the next
reconcile rewrites it.

## 3. Archive

Once every box above is checked for a given repository:

```bash
gh repo archive simpletibr/simplicio-<pkg>
```

Archiving makes the repo read-only (no new issues/PRs/pushes) but keeps it
browsable, so the README banner from step 1 remains visible indefinitely.

## 4. After archiving

- [ ] Update any external documentation, blog posts, or the organization
      profile README that still link to the archived repo instead of
      `simpletibr/simplicio-loop/tree/main/packages/<pkg>`.
- [ ] Leave the PyPI project descriptions as-is if they already point at the
      new repo (`packages/<pkg>/pyproject.toml` `[project.urls]` already do);
      otherwise update `Homepage`/`Repository` there too and cut a patch
      release so the change reaches PyPI's project page.
