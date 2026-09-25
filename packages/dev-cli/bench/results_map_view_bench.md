# Canonical map + worktree overlay benchmark (issue #213)

- Repeats: 5
- Cold (`force_remap=True`, rebuild both halves): 0.5831s avg
- Warm (matching canonical + overlay already on disk): 0.4888s avg
- Speedup: 1.19x
- Platform: Windows-11-10.0.26100-SP0 / Python 3.14.5

Note: both paths pay the same ~9 `git` subprocess spawns in
`resolve_git_identity` (dominant cost on this synthetic single-repo,
single-commit fixture) — the warm path only saves the two manifest writes
(mkdir + file write). This repo does not itself invoke `simplicio-mapper
scan` (see ADR-005), so this benchmark cannot measure the larger real-world
win of skipping an actual mapper re-scan across sibling worktrees; it
measures exactly what this module controls: avoided redundant disk writes
and a stable, reusable identity resolution.
