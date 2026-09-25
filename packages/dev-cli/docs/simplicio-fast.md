# Simplicio Fast (optional)

Simplicio Fast is not installed by the base package. Negotiate it without
importing implementation internals:

```console
simplicio-py fast capabilities --json
simplicio-py fast doctor --json --snapshot .simplicio/context-snapshot.json
```

Install from the package index with `pip install 'simplicio-cli[fast]'`. For a
hermetic or offline environment, download the dev-cli and Fast wheels plus
dependencies into a wheelhouse on a connected machine, transfer it, then run
`pip install --no-index --find-links=/path/to/wheels 'simplicio-cli[fast]'`.
`fast doctor --offline` reports this correction when Fast is absent and never
attempts a download.

To test a local Fast checkout, install its wheel into a dedicated virtual
environment rather than adding its source tree to `PYTHONPATH`. Uninstall with
`pip uninstall simplicio-fast`; the dev-cli continues in its normal path.

The preflight states are stable: `ready` exits 0, `absent` exits 2,
`incompatible` exits 3, and `degraded` exits 4. `fast capabilities` exits 0
even when Fast is unavailable so supervisors can always negotiate the
contract. `--receipt PATH` is opt-in and appends only versions, status, command,
and `source_included=false`; it never records source text or snapshot paths.
