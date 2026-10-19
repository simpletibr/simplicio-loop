"""OpenClaude adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="openclaude",
    name="OpenClaude",
    source="https://github.com/Twigpine/openclaude/blob/main/src/utils/projectInstructions.ts",
    markers=(),
    entry_verified=True,
    note="Source: PRIMARY_PROJECT_INSTRUCTION_FILE = 'AGENTS.md', with CLAUDE.md as the fallback.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
