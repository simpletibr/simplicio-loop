---
title: YOOL / tuple / HAMT
description: Capability addressing pattern, receipt flow, and MCP edge guidance.
sidebar_position: 4
slug: /yool-tuple-hamt
---
# YOOL / tuple / HAMT

The YOOL / tuple / HAMT pattern is the capability-addressing model that LLM Project Mapper is standardizing for multi-agent repositories.

## Why it exists

- Agents need stable capability ids, not only friendly names.
- Dispatch needs explicit authority and lane routing.
- Receipts need a canonical place and schema.
- MCP should stay at the edge for snapshot and dispatch, not become the inner loop.

## Try it

```bash
npx @wesleysimplicio/llm-project-mapper --mcp-edge
bin/build-hamt-catalog
```

That flow gives you:

- `.catalog/agents.json` as the generated HAMT catalog
- `.receipts/` as the default local receipt store
- `mcp/server.ts` and `mcp/server.py` as edge adapters when `--mcp-edge` is enabled

## Static layout

```json
{
  "yool_id": "agent.dev.python.v1",
  "authority": "dev",
  "lane": "fast",
  "agent_terms": {
    "cpu_quota_pct": 60,
    "disk_quota_mb": 100
  }
}
```

## Dynamic flow

```text
AGENTS.md
  -> bin/build-hamt-catalog
      -> .catalog/agents.json
          -> MCP snapshot / dispatch edge
              -> workers subscribe by lane
                  -> .receipts/ evidence
```

## MCP is the edge

MCP is for read-mostly snapshots and external dispatch entrypoints. Keep tuple matching, scheduling, retries, and worker coordination outside the MCP adapter.

## Canonical spec

- [Root spec on GitHub](https://github.com/wesleysimplicio/llm-project-mapper/blob/main/YOOL_TUPLE_HAMT.md)
- [Vendored source in this repo](https://github.com/wesleysimplicio/llm-project-mapper/blob/main/docs/YOOL_TUPLE_HAMT.md)
