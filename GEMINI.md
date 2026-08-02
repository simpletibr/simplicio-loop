# Gemini instructions

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

