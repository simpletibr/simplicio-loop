# Example: Runtime tiers (#99)

This directory demonstrates the two-tier runtime matrix.

## Usage

```bash
# Verify tier-1 runtimes (Claude Code, Codex, Cursor)
python3 scripts/verify_adapters.py claude codex cursor

# Verify every installer runtime (~20s in total)
python3 scripts/verify_adapters.py

# The claims-audit check 7 runs `verify_adapters.py claude` on every gate
python3 scripts/check.py
```

## Structure

- Tier 1 (guaranteed, gated): Claude Code, Codex, Cursor
- Tier 2 (best-effort, ungate): VS Code, Antigravity, Kiro, OpenCode, Gemini, Aider, Simplicio Agent, OpenClaw

See `adapters/MATRIX.md` for the full rules, including promotion/demotion criteria.
