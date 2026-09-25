---
title: Skills and Agents
description: How LLM Project Mapper turns repeated conventions into reusable operating context.
sidebar_position: 1
---
# Skills and Agents

LLM Project Mapper is built around a simple idea: agents perform better when project conventions are explicit, reusable, and close to the code.

## The three context layers

1. **Instruction layer**: `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` explain how work should be executed.
2. **Reference layer**: `.specs/`, `docs/`, and the changelog hold durable human-readable context.
3. **Execution layer**: `.skills/`, `.agents/`, hooks, and validation scripts turn that context into repeatable agent behavior.

## Why skills matter

Skills are not dependencies or code generators. They are small operational manuals that an agent can load on demand when a request matches a known pattern such as E2E testing, commit formatting, or multi-agent execution.

## Why this site exists

The repository already contains the source docs. This site simply gives them a navigable hub with:

- versioned docs
- full-text local search
- predictable categories for quickstart, guide, concepts, reference, and community
- GitHub Pages deployment on every push to `main`

For the raw source files, see the repository paths referenced throughout this site.
