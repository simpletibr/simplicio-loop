# CLAUDE.md


## Active English instruction surface

Read [docs/LLM_OPERATING_INSTRUCTIONS.md](docs/LLM_OPERATING_INSTRUCTIONS.md) before acting. It is the normative English entry point for LLMs; the rest of this file supplies project-specific detail.

Use [`AGENTS.md`](AGENTS.md) as the canonical repository contract.

Before any operation, every subagent/worker reads `AGENTS.md`, this `CLAUDE.md`, and all relevant local skills. The minimum Fast set is `skills/simplicio-prism/SKILL.md` and `skills/simplicio-fast/SKILL.md`; task-specific local skills are loaded before mutation.

Workers use one read-only binary/artifact set built from the canonical default branch. They do not rebuild binaries or regenerate canonical Mapper/Fast artifacts. Worktrees isolate source edits and receipts only. Receipts include repository/revision, binary digest/version, Mapper generation, and artifact digest. Missing, stale, or mismatched central artifacts fail closed and invoke the central rebuild path only.

Use [`docs/CLI_COMMANDS.md`](docs/CLI_COMMANDS.md) as the complete feature and
command index. Before executing a public operation, run:

```bash
simplicio-fast --help
simplicio-fast <command> --help
simplicio-fast changeset <action> --help
simplicio-fast-cross-repo --help
```

Preserve versioned JSON schemas, treat source files as authoritative, keep
writes explicit and stop on missing/incompatible Mapper, Dev CLI, Runtime or
Loop contracts. GitHub issue bodies use objective plus `Execution` for
implementation/deployment and tests; do not add an Acceptance Criteria section.

<!-- simplicio-global-llm-architecture-rules:start -->
## Mandatory architecture rules for every LLM

These rules apply to analysis, planning, implementation, review, testing, release, and documentation. Read them before acting:

1. **Do not preserve backward compatibility.** Delete obsolete behavior directly; do not add compatibility layers, migrations, or fallbacks.
2. **Choose the simplest implementation that meets the current need.** Do not create speculative abstractions or unnecessary configuration layers.
3. **Build long-lived layers incrementally.** Make the minimum end-to-end version work first, then add capabilities without dismantling working code.
4. **Keep components modular**, with clear responsibilities and explicit boundaries.
5. **Prefer mature, maintained libraries.** Do not rewrite from scratch without an explicit, recorded technical reason.
6. **Inspect existing dependencies first.** Before adding a package or writing a custom solution, check what the project already provides.
7. **Make architecture decisions for the long term.** Do not introduce temporary solutions intended to be replaced later.
8. **Reuse validated patterns from mature products** instead of reinventing them.

<!-- simplicio-global-llm-architecture-rules:end -->



## Language precedence

[docs/LLM_OPERATING_INSTRUCTIONS.md](docs/LLM_OPERATING_INSTRUCTIONS.md) is the authoritative active instruction set and is written in English. Any other-language passage retained in this compatibility/reference file is non-normative; do not execute it as an instruction.
