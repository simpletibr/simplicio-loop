# ContextView for Prism agents

`simplicio_fast.context_view` materializes a bounded context packet for one Prism
agent transition. Mapper still owns extraction and the public ContextGraph; Fast
only verifies, selects, caches and transports Mapper-owned items.

## Contract

A request binds all six execution identities (`prism`, `slot`, `task`,
`attempt`, `agent`, `stage`) plus:

- the canonical base generation and optional overlay digest;
- a requested capability and bounded goal fragment;
- byte, token and node budgets;
- the authority digest, lease fence and cache TTL.

Requests and results use versioned, tamper-evident HBP rows:
`simplicio.fast.context-view-request/v1`,
`simplicio.fast.context-view/v1` and
`simplicio.fast.context-view-hbp/v1`. The result handle is content-addressed
and binds the full execution identity, request hash, selected-content digest,
authority and fence. `verify_context_view` must run before consumption.

## Isolation and cache rules

The cache key includes repository, base generation, overlay digest,
capability, goal fragment, stage, budgets, authority, fence and the verified
input-content digest. Equivalent base-only selection may be reused between
tasks; each materialized result still gets a task/agent-specific handle and
lineage. Any overlay item adds task and attempt to the cache scope, so
overlay-sensitive content never crosses tasks.

A generation, overlay, fence or authority mismatch fails closed. Persistent
cache entries are checksummed, TTL-bound, atomically replaced and bounded by
LRU eviction. Source content is rehashed before every lookup, including a warm
lookup, so a forged item cannot hide behind a prior hit.

## Stage policy and budgets

Selection prioritizes evidence, diffs, tests, receipts, impact, facts and spans.
The implementer prompt has the lowest priority and is never eligible for a
reviewer view. A reviewer without independent evidence returns
`reviewer_evidence_missing`; an empty or over-budget packet returns
`insufficient_evidence`. Both are explicit abstentions.

Every selected item consumes the Mapper-reported token count plus measured
UTF-8 bytes and one node. Expansion stops at the declared bounds. Secret-like
assignments and bearer credentials are redacted, and paths outside the
authority roots are rejected.

Cache receipts report observed bytes and Mapper token counts reused. They
deliberately keep `token_savings` null with
`MODEL_TOKEN_ACCOUNTING_NOT_OBSERVED`; no model-billing reduction is inferred
from a cache hit.

## Minimal use

```python
authority = ContextAuthority(
    "loop-agent", "fence-7", ("context:read",), ("src", "tests")
)
request = ContextViewRequest(
    repository="owner/repo",
    identity=ContextIdentity("p1", "s1", "t1", 1, "a1", "implementer"),
    base_generation="g1",
    requested_capability="context:read",
    goal_fragment="verify the change",
    budget=ContextBudget(max_tokens=512, max_bytes=8192, max_nodes=32),
    authority_digest=authority.digest,
    fence=authority.fence,
)
view = ContextViewService().materialize(request, authority, mapper_items)
verified = verify_context_view(view, request=request, authority=authority)
```

The Loop integration seam is the request/result HBP row. Loop owns stage
scheduling and completion; Runtime owns effect authority. Fast neither expands
authority nor marks an issue complete.

## Verification and benchmark

```bash
PYTHONPATH=src python -m pytest -q tests/test_context_view_214.py
PYTHONPATH=src python -m pytest --cov=simplicio_fast.context_view \
  --cov-branch --cov-report=term-missing tests/test_context_view_214.py
PYTHONPATH=src python benchmarks/bench_context_view_214.py \
  --repetitions 10 --tasks 10
```

The benchmark publishes raw cold/warm samples, observed cache hits and quality
coverage for exactly ten tasks. It treats equal cold/warm quality as a gate and
does not publish synthetic token savings.
