# Simplicio public I/O

`simplicio.io/v1` is the single public envelope exchanged with Mapper, Fast
and Loop. Dev CLI owns only `change` and `verify`; it does not interpret Fast
storage or coordinate other components. The outer fields are stable:
`schema`, `operation`, `request_id`, `repository`, `payload`, `evidence`, and
`error`. Internal changeset and execution contracts stay private to Dev CLI.

