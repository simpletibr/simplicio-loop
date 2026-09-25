# Issue 239 indexed Rust query evidence — Windows — 2026-08-01

Measured on the current `master` line with `rust/target/debug/simplicio-fast-rs.exe`, 30 repetitions per scale, using the resident session protocol.

| Symbols | Selected index | Candidates visited | Max records decoded | Median / p95 (ms) | Additional RSS |
| ---: | --- | ---: | ---: | ---: | ---: |
| 10,000 | `persisted.exact` | 2 | 1 | 0.126 / 0.225 | 0 KiB |
| 100,000 | `persisted.exact` | 2 | 1 | 0.130 / 0.190 | 0 KiB |
| 1,000,000 | `persisted.exact` | 2 | 1 | 0.107 / 0.187 | 0 KiB |

The machine receipt is retained locally at `.pytest-basetemp-goal/issue239-rust-query-20260801.json`. All three benchmark gates passed: exact-query p95 <=10ms, bounded indexed candidates/decoding, and additional RSS <=8 MiB. The issue remains open pending its full parity, corruption/fuzz, context-read and cross-platform acceptance matrix.

