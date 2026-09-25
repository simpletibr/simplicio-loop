# Spec Drift Report

Auto-generated. Verifies `.specs/**` and `docs/**` against the real code: unresolved template placeholders, specs referencing paths that no longer exist, high-impact code with no spec/doc mention, and stale generated docs.

- Findings: 127 (threshold: 10, FAIL)
- Specs tracked: 36 (7 with at least one code reference)

## orphan-spec

| Severity | Target | Message |
| --- | --- | --- |
| warn | `.specs/architecture/ADR-002-python-rust-hybrid.md:111` | references a path that does not exist: src/lib.rs |

## placeholder

| Severity | Target | Message |
| --- | --- | --- |
| warn | `.specs/README.md:52` | template placeholder content detected |
| warn | `.specs/README.md:52` | template placeholder content detected |
| warn | `.specs/README.md:52` | template placeholder content detected |
| warn | `.specs/README.md:52` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:1` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:18` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:52` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:109` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:113` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:114` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:115` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:116` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:117` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:156` | template placeholder content detected |
| warn | `.specs/architecture/DESIGN.md:177` | template placeholder content detected |
| warn | `.specs/architecture/PATTERNS.md:1` | template placeholder content detected |
| warn | `.specs/architecture/PATTERNS.md:26` | template placeholder content detected |
| warn | `.specs/architecture/PATTERNS.md:84` | template placeholder content detected |
| warn | `.specs/architecture/PATTERNS.md:87` | template placeholder content detected |
| warn | `.specs/architecture/PATTERNS.md:181` | template placeholder content detected |
| warn | `.specs/architecture/PATTERNS.md:213` | template placeholder content detected |
| warn | `.specs/workflow/CONTRIBUTING.md:1` | template placeholder content detected |
| warn | `.specs/workflow/CONTRIBUTING.md:3` | template placeholder content detected |
| warn | `.specs/workflow/CONTRIBUTING.md:3` | template placeholder content detected |
| warn | `.specs/workflow/CONTRIBUTING.md:3` | template placeholder content detected |
| warn | `.specs/workflow/CONTRIBUTING.md:3` | template placeholder content detected |
| warn | `.specs/workflow/CONTRIBUTING.md:53` | template placeholder content detected |
| warn | `.specs/workflow/CONTRIBUTING.md:61` | template placeholder content detected |
| warn | `.specs/workflow/CONTRIBUTING.md:200` | template placeholder content detected |
| warn | `.specs/workflow/RELEASE.md:1` | template placeholder content detected |
| warn | `.specs/workflow/RELEASE.md:3` | template placeholder content detected |
| warn | `.specs/workflow/RELEASE.md:3` | template placeholder content detected |
| warn | `.specs/workflow/RELEASE.md:3` | template placeholder content detected |
| warn | `.specs/workflow/RELEASE.md:3` | template placeholder content detected |
| warn | `.specs/workflow/RELEASE.md:28` | template placeholder content detected |
| warn | `.specs/workflow/RELEASE.md:122` | template placeholder content detected |
| warn | `.specs/workflow/RELEASE.md:145` | template placeholder content detected |
| warn | `.specs/workflow/RELEASE.md:202` | template placeholder content detected |
| warn | `.specs/workflow/RELEASE.md:220` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:1` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:3` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:3` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:3` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:34` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:109` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:120` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:121` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:122` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:134` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:178` | template placeholder content detected |
| warn | `.specs/workflow/WORKFLOW.md:180` | template placeholder content detected |
| warn | `docs/architecture-map.md:8` | template placeholder content detected |
| warn | `docs/architecture-map.md:9` | template placeholder content detected |
| warn | `docs/architecture-map.md:10` | template placeholder content detected |
| warn | `docs/architecture-map.md:11` | template placeholder content detected |
| warn | `docs/architecture-map.md:12` | template placeholder content detected |
| warn | `docs/architecture-map.md:18` | template placeholder content detected |
| warn | `docs/architecture-map.md:18` | template placeholder content detected |
| warn | `docs/architecture-map.md:19` | template placeholder content detected |
| warn | `docs/architecture-map.md:19` | template placeholder content detected |
| warn | `docs/architecture-map.md:26` | template placeholder content detected |
| warn | `docs/architecture-map.md:26` | template placeholder content detected |
| warn | `docs/architecture-map.md:26` | template placeholder content detected |
| warn | `docs/architecture-map.md:26` | template placeholder content detected |
| warn | `docs/architecture-map.md:26` | template placeholder content detected |
| warn | `docs/architecture-map.md:33` | template placeholder content detected |
| warn | `docs/architecture-map.md:33` | template placeholder content detected |
| warn | `docs/architecture-map.md:37` | template placeholder content detected |
| warn | `docs/architecture-map.md:38` | template placeholder content detected |
| warn | `docs/architecture-map.md:39` | template placeholder content detected |
| warn | `docs/architecture-map.md:40` | template placeholder content detected |
| warn | `docs/architecture-map.md:44` | template placeholder content detected |
| warn | `docs/architecture-map.md:45` | template placeholder content detected |
| warn | `docs/architecture-map.md:46` | template placeholder content detected |
| warn | `docs/architecture-map.md:47` | template placeholder content detected |
| warn | `docs/architecture-map.md:51` | template placeholder content detected |
| warn | `docs/architecture-map.md:52` | template placeholder content detected |
| warn | `docs/architecture-map.md:53` | template placeholder content detected |
| warn | `docs/evidence/README.md:43` | template placeholder content detected |
| warn | `docs/features/README.md:14` | template placeholder content detected |
| warn | `docs/features/README.md:18` | template placeholder content detected |
| warn | `docs/features/README.md:22` | template placeholder content detected |
| warn | `docs/features/README.md:23` | template placeholder content detected |
| warn | `docs/features/README.md:24` | template placeholder content detected |
| warn | `docs/features/README.md:30` | template placeholder content detected |
| warn | `docs/features/README.md:31` | template placeholder content detected |
| warn | `docs/features/README.md:32` | template placeholder content detected |
| warn | `docs/features/README.md:33` | template placeholder content detected |
| warn | `docs/features/README.md:34` | template placeholder content detected |
| warn | `docs/features/README.md:40` | template placeholder content detected |
| warn | `docs/features/README.md:40` | template placeholder content detected |
| warn | `docs/features/README.md:40` | template placeholder content detected |
| warn | `docs/features/README.md:46` | template placeholder content detected |
| warn | `docs/features/README.md:46` | template placeholder content detected |
| warn | `docs/features/README.md:50` | template placeholder content detected |
| warn | `docs/features/README.md:54` | template placeholder content detected |
| warn | `docs/features/README.md:58` | template placeholder content detected |
| warn | `docs/features/README.md:59` | template placeholder content detected |
| warn | `docs/features/README.md:60` | template placeholder content detected |
| warn | `docs/features/README.md:64` | template placeholder content detected |
| warn | `docs/local-setup.md:7` | template placeholder content detected |
| warn | `docs/local-setup.md:8` | template placeholder content detected |
| warn | `docs/local-setup.md:9` | template placeholder content detected |
| warn | `docs/local-setup.md:10` | template placeholder content detected |
| warn | `docs/local-setup.md:11` | template placeholder content detected |
| warn | `docs/local-setup.md:17` | template placeholder content detected |
| warn | `docs/local-setup.md:17` | template placeholder content detected |
| warn | `docs/local-setup.md:17` | template placeholder content detected |
| warn | `docs/local-setup.md:22` | template placeholder content detected |
| warn | `docs/local-setup.md:37` | template placeholder content detected |
| warn | `docs/local-setup.md:37` | template placeholder content detected |
| warn | `docs/local-setup.md:38` | template placeholder content detected |
| warn | `docs/local-setup.md:38` | template placeholder content detected |
| warn | `docs/local-setup.md:50` | template placeholder content detected |
| warn | `docs/local-setup.md:51` | template placeholder content detected |
| warn | `docs/local-setup.md:52` | template placeholder content detected |
| warn | `docs/local-setup.md:59` | template placeholder content detected |
| warn | `docs/local-setup.md:61` | template placeholder content detected |
| warn | `docs/troubleshooting.md:7` | template placeholder content detected |
| warn | `docs/troubleshooting.md:13` | template placeholder content detected |
| warn | `docs/troubleshooting.md:20` | template placeholder content detected |
| warn | `docs/troubleshooting.md:27` | template placeholder content detected |
| warn | `docs/troubleshooting.md:48` | template placeholder content detected |
| warn | `docs/troubleshooting.md:50` | template placeholder content detected |
| warn | `docs/troubleshooting.md:51` | template placeholder content detected |
| warn | `docs/troubleshooting.md:52` | template placeholder content detected |
