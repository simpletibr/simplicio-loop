# Deterministic execution boundary

simplicio-dev-cli is an executor, not an LLM runtime. A clean installation
does not need a local model, a remote endpoint, an API key, a provider SDK, a
provider CLI, model weights, or network access to perform its supported work.

## Accepted inputs

- Mapper context and TaskSpec contracts;
- mechanical-edit plans;
- Fast changesets;
- Runtime EffectTransaction proposals;
- repository-local verification commands.

## Mutation flow

1. An external coordinator decides the change and produces a typed plan.
2. simplicio-dev-cli validates paths, hashes, contracts and authorization.
3. The mechanical executor applies one bounded changeset.
4. The configured test command runs locally.
5. A receipt records the outcome and evidence.

generate and planner_complete are compatibility boundaries only. They fail
closed with reason_code=llm_execution_disabled before cache access, model
loading, subprocess creation, socket/network I/O, or provider credential
resolution. Use simplicio-py mechanical-edit --help or
simplicio-py changeset --help for explicit plan inputs.
