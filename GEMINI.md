# Gemini instructions


## Active English instruction surface

Read [docs/LLM_OPERATING_INSTRUCTIONS.md](docs/LLM_OPERATING_INSTRUCTIONS.md) before acting. It is the normative English entry point for LLMs; the rest of this file supplies project-specific detail.

Use [`AGENTS.md`](AGENTS.md) as the canonical repository contract. The full
LLM-readable feature and command index is
[`docs/CLI_COMMANDS.md`](docs/CLI_COMMANDS.md).

Before using a public operation, run the matching help command:

```bash
simplicio-mapper --help
simplicio-mapper <command> --help
node bin/cli.js --help
```

Do not infer commands from internal modules. Preserve versioned JSON schemas,
keep source files authoritative, and stop when Mapper/Fast/Dev CLI contracts
are unavailable or incompatible.

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

