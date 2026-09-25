# Issue #241 AC matrix

`fixtures/changeset/v1/issue241-ac-matrix.json` is the current residual
matrix for the public binary changeset lifecycle. It deliberately separates
measured Windows evidence from partial or unverified cross-platform gates.

The matrix is not a closure claim. The remaining blockers are Linux byte and
installed-Dev-CLI parity, real post-timeout reconciliation on installed
platforms, aggregate changed-code coverage, and the complete resource
benchmark matrix. Future updates must change a row only when a new receipt or
test provides the corresponding evidence.
