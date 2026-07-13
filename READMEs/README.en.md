# simplicio-mapper

> Turn a repository into bounded, queryable context that people and AI agents can trust.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/) [![Python](https://img.shields.io/pypi/pyversions/simplicio-mapper?color=22c55e&label=Python)](https://pypi.org/project/simplicio-mapper/)

[All languages and the canonical README](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="A repository becoming bounded, evidence-backed context" width="100%"></p>

`simplicio-mapper` maps a codebase into versioned `.simplicio/` artifacts: architecture, symbols, flows, rules, tests, and task-aware context packs. It is the mapping engine of the Simplicio ecosystem, built to make repository knowledge small enough to inspect and explicit enough to audit.

## Start

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "trace the authentication flow" --token-budget 1200 --json
```

## What is different

- **Bounded retrieval:** `handoff` and `orient` report relevance, coverage, token budget, penalties, and fidelity rather than silently dumping a repository into a prompt.
- **Change-aware context:** `sync`, `history`, `diff`, and `delta` keep a ContextGraph current across changes and sessions.
- **Evidence contracts:** public schemas, validation commands, confidence tags, behavioral receipts, and evidence certificates distinguish measured facts from unsupported claims.
- **Useful outputs:** project maps, architecture docs, endpoint and screen inventories, flows, business rules, surveys, and graph queries.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

The Python package is the canonical mapping engine. The [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) npm package is a complementary project starter.

See the [documentation site](https://wesleysimplicio.github.io/simplicio-mapper/), [contracts](../contracts/), [integration guide](../SIMPLICIO_INTEGRATION.md), and [v0.23.1 release](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). Licensed under [MIT](../LICENSE).
