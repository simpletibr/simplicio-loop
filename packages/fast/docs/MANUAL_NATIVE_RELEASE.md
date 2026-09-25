# Manual native release fallback

Issue #229 documents the Actions startup failure that prevented the native assets for `v2.0.20` from being published. `scripts/manual_native_release.py` mirrors `.github/workflows/native-release.yml` locally:

1. Build both `native/fast-native` and `rust/simplicio-fast-core` for each requested target.
2. Stage the compatibility and Rust-core binaries in the workflow's ABI directories.
3. Generate and verify the compatibility manifest and Rust engine manifest.
4. Create deterministic `tar.gz` archives.
5. Upload only verified archives with `gh release upload --clobber`.

Run from a clean checkout and keep the source commit explicit for a release receipt:

```powershell
python scripts/manual_native_release.py run `
  --version 2.0.21 `
  --tag v2.0.21 `
  --source-commit $(git rev-parse HEAD) `
  --repo wesleysimplicio/simplicio-fast `
  --json
```

The command is idempotent. A previously verified platform is reused, archives are overwritten only with the same deterministic bytes, and release uploads use `--clobber`. `--platform` can be repeated to retry one target. `--force` rebuilds a staged target.

The runner continues when a target cannot be built. It records that target as `UNVERIFIED` and never creates a placeholder binary. On Windows, Linux targets require a compatible Rust target/linker or `zig`; macOS ARM64 normally requires an Apple SDK/host and is expected to remain `UNVERIFIED` on a Windows-only host. Cross-target Rust-core manifests are source manifests probed by the host; the target executable is not claimed to have run locally.

Before publication, inspect `dist/manual-native/2.0.21/manual-native-release.json`, `manual-native-archives.json`, and `manual-native-publish.json`. Every uploaded archive has a SHA-256 receipt, and the release view is re-read after upload.
