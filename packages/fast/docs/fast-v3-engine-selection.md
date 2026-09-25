# Fast V3 engine selection contract

ADR-0003 supersedes the direct Rust-engine assumption in this document. Rust is
owned and released by `simplicio-runtime`; Fast uses the narrow
`RuntimeFastBackend` HBP adapter and retains a complete Python reference path.

`select_runtime_backend()` implements `auto|rust|python|off`. `auto` records a
stable reason when it selects Python, explicit `rust` fails closed, `python`
does not probe Runtime, and `off` selects no backend. Runtime is admitted only
after SHA-256/platform/ABI/version/doctor/capability/conformance verification.

The older pure `select_engine()` policy helper remains a compatibility API.
New consumers should persist `simplicio.fast.runtime-selection/v1` from
`RuntimeSelection.receipt()`.
