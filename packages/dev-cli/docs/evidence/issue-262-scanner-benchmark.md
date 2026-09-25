# Internal JSON scanner benchmark

- Platform: `Linux-6.12.13-x86_64-with-glibc2.39`
- Python: `3.12.13`
- Workload: 10000 archive entries, 7 measured scans
- Median: 386.622 ms
- Minimum: 377.807 ms
- Maximum: 458.468 ms
- Peak Python allocation: 6565.1 KiB

## Shared source scanner

- Date: `2026-07-23`
- Workload: repository checkout, 5 baseline scans
- Elapsed samples: `248`, `235`, `228`, `231`, `233` ms
- Median: `233` ms
- Peak RSS: `null` (`/usr/bin/time` is unavailable in the execution image)
- Result: `1469` findings, `1448` unclassified; strict mode is release-blocking
- Determinism: all five Markdown reports had SHA-256
  `7e3cce1e085b3b34817c847cbdb6151533bc7d86d5a11a95eabe5dfb55e147c9`;
  all five HBP receipts had SHA-256
  `6247966c5fef45e7d9a2ca5899a1cb9e7472ded423993cb48666f9dcf9e4635d`
