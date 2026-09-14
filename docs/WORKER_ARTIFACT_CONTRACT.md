# Worker Bootstrap and Central Artifact Contract

**Status: normative.** This contract applies to every subagent, worker, delegated agent, and capability invoked from this repository. It is intentionally shared across the Simplicio Runtime, Mapper, and Dev CLI repositories.

## 1. Mandatory bootstrap (before any capability)

Before using **any** capability (including map, memory, search, build, test, edit, validation, MCP, delegation, or a provider), a worker MUST, in order:

1. Read this repository's `AGENTS.md` in full.
2. Read this repository's `CLAUDE.md` in full.
3. Identify and read the relevant local skills in `skills/*/SKILL.md` (and, where present, `.skills/*/SKILL.md`) in full before invoking the capability they describe. At minimum, use the repository's component skill and `simplicio-prism`; load `simplicio-mapper`, `simplicio-fast`, `simplicio-dev-cli`, or `simplicio-loop` when that capability is involved. Do not treat Runtime as this mapper's owner or survey path.
4. Read the local operational docs named by those contracts for the requested scope.
5. Record the bootstrap completion in the worker receipt before side effects.

A missing or unreadable instruction file or relevant skill is a hard precondition failure. Do not continue by guessing, using a fallback capability, or asking another worker to infer the missing contract.

## 2. One centrally generated artifact

For a wave of work, the coordinator generates exactly one authoritative artifact bundle from the default `main` branch. The bundle consists of:

- the centrally built `simplicio` binary (or the repository's canonical executable), and
- the centrally generated Mapper artifact set used by the wave.

Workers consume this bundle **read-only**. They MUST NOT rebuild the binary per worker, replace the shared binary, regenerate Mapper artifacts per worker, or treat a worker-local build/map as authoritative. The coordinator is the only actor allowed to publish or replace the shared bundle.

Isolated worktrees are for source changes and receipts only. A worker may write its source diff and execution receipt in its own worktree, but must consume the central bundle and must not put a worker-built binary or regenerated Mapper artifact into the shared bundle or source change.

## 3. Required provenance

The central manifest and every worker receipt MUST identify:

- repository name and canonical repository path/URL;
- source branch (`main`) and exact source revision/commit;
- binary version and SHA-256 digest (plus platform/architecture when relevant);
- Mapper generation version/tool version, source revision, and artifact-set SHA-256 digest;
- bundle generation time, generator/coordinator identity, and schema/version;
- worker identity, worktree path, consumed bundle identifier, and read-only consumption result.

A digest is over the bytes actually consumed. A version without a digest is insufficient evidence; a digest without repository, branch, and revision is also insufficient.

## 4. Missing or stale bundle: fail closed

A worker MUST fail closed before capability execution when the manifest or any required bundle member is missing, unreadable, incompatible, stale, or has a digest/version/revision mismatch. The result must report an actionable reason (`artifact_missing`, `artifact_stale`, `artifact_digest_mismatch`, `artifact_incompatible`, or `bootstrap_incomplete`) and preserve the receipt; no silent fallback is allowed.

Only the central coordinator may rebuild or regenerate the bundle, from the default `main` branch, then publish a new manifest and digests. Workers must not repair a stale/missing bundle locally or continue with an unproven artifact. After central rebuild, workers re-read the manifest and verify every provenance field and digest before retrying.

## 5. Local validation exceptions

A worker MAY build source in an isolated worktree, or generate a temporary Mapper result, only when the explicit purpose is local validation, comparison, debugging, or a test that requires a source-local output. Such output is non-authoritative, must stay outside the shared bundle, must be labeled `local-validation`, and must include its own source revision and digest in the receipt. It MUST NOT satisfy the wave's central-artifact requirement, replace the central binary/artifacts, or be consumed by another worker as authoritative.

These exceptions never permit per-worker rebuilds for ordinary execution, per-worker Mapper regeneration for context, mutation of the central bundle, or bypassing a failed/missing provenance check.
