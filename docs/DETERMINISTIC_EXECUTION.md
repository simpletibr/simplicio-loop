# Deterministic execution boundary

simplicio-dev-cli is an executor, not an LLM runtime. A clean installation
does not need a local model, a remote endpoint, an API key, a provider SDK, a
provider CLI, model weights, or network access to perform its supported work.

## Accepted inputs

- Mapper context and TaskSpec contracts;
- Dev CLI-owned `simplicio.dev-cli.edit-plan/v1` edit plans and
  `simplicio.dev-cli.scaffold-plan/v1` scaffold plans;
- legacy mechanical-edit plans;
- Fast changesets;
- Runtime EffectTransaction proposals;
- repository-local verification commands.

## Mutation flow

1. Mapper observes exact files/symbols and supplies a canonical repository,
   generation, source-tree, and hash binding.
2. Dev CLI decides the deterministic transform and produces a versioned plan.
3. Runtime authorizes the effect and reuses the Dev CLI kernel to apply one
   bounded changeset with rollback.
4. Mapper remaps after effective source bytes change; the coordinator validates
   the new generation.
5. A Dev CLI plan receipt and Runtime effect receipt record the outcome and
   evidence.

generate and planner_complete are compatibility boundaries only. They fail
closed with reason_code=llm_execution_disabled before cache access, model
loading, subprocess creation, socket/network I/O, or provider credential
resolution. Use simplicio-py edit --help, simplicio-py mechanical-edit --help,
or simplicio-py changeset --help for explicit plan inputs. The canonical
edit/scaffold schemas and typed conflict vocabulary are documented in
`docs/deterministic-edit-scaffold.md`.
