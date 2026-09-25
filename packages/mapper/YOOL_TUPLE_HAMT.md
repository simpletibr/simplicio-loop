# yool · tuple · HAMT — capability addressing for agent systems

> Canonical specification of the **yool / tuple / HAMT** pattern.
> Cross-project pattern doc. Source of truth lives here:
> https://github.com/wesleysimplicio/yool-tuple-hamt (private).
> Vendored into [SendSprint](https://github.com/wesleysimplicio/SendSprint),
> [llm-project-mapper](https://github.com/wesleysimplicio/llm-project-mapper),
> and any future agent-orchestration project.

Status: **draft v0.2** · Maintainer: @wesleysimplicio · Last updated: 2026-05-19

---

## 0. TL;DR

- **yool** — smallest callable capability atom. An opcode: `agent.dev.python`, `ide.cursor.send`, `fs.read_sector`.
- **tuple** — addressable envelope binding yools to map position, authority, lane, budget, source pointers, receipts. Unit of work.
- **HAMT** — Hash Array Mapped Trie cataloging every yool/tuple/agent/operator. O(log32) lookup, immutable structural sharing.
- **tuple-space** (Linda) — producers `out` tuples; workers `in`/`rd` by pattern. No imperative orchestrator.
- **receipts** — content-addressable execution records. Same input → same hash → cache hit, no recompute.
- **MCP edge** — read-mostly snapshot/dispatch surface. NOT the inner loop.
- **guardrails** — CPU throttle + disk GC are mandatory, not optional (see §11).

---

## 1. The Problem (Why We Built This)

Every agent system we built had the same five rots:

1. **Orchestrator accretion** — `flow.py` / `pipeline.py` grow with every new step. Imperative coupling. New step = patching 5 files.
2. **Registry sprawl** — agents/IDEs/operators live in hand-maintained dicts. Adding 1 IDE touches the dict, the dispatcher, the CLI, the docs, the tests.
3. **No cross-run cache** — same input rebuilds because intermediate results have no addressable identity.
4. **Resume/replay is bespoke** — every project serializes run state differently. Crash recovery is "best effort", usually a fresh restart.
5. **Audit is post-hoc** — "what ran, with whose authority, against which input, costing how much" — answered by `grep` over logs.

Symptom that triggered this spec: the **MCP exposure drift** — exposing every internal call as an MCP tool makes the inner loop slow (latency per call), uncacheable (no addressable identity), and unbounded (no budget). The fix isn't "better MCP" — it's keeping MCP at the edge and rebuilding the inner loop on **capability addressing**.

---

## 2. Vocabulary

### 2.1 yool

The atomic, callable capability. **One yool = one opcode = one side-effect or pure computation**.

#### Examples by category

```
# Code-acting agents
agent.dev.python
agent.dev.dotnet
agent.dev.typescript
agent.lint.ruff
agent.lint.eslint
agent.lint.dotnet
agent.test.pytest
agent.test.jest
agent.test.e2e.playwright
agent.security.scan
agent.security.dependabot
agent.pr.create
agent.pr.review

# IDE bridges
ide.cursor.send
ide.zed.send
ide.vscode.send
ide.jetbrains.send

# Project operators
op.jira.fetch_sprint
op.azure.fetch_iteration
op.linear.fetch_cycle
op.github.fetch_issues

# Filesystem & net (primitives)
fs.read_sector
fs.write_receipt
net.fetch
net.post

# Catalog itself (introspection)
catalog.lookup
catalog.list_by_lane
catalog.diff
```

#### Naming rules

| Rule | Example |
|---|---|
| One verb, one direct object | `agent.lint.ruff` (lint is the verb, ruff is the implementation) |
| Stable identifier (rename = breaking) | `agent.dev.python.v1` then bump to `.v2` instead of renaming |
| Namespace by domain.action.tool | `domain` in {agent, ide, op, fs, net, catalog} |
| Pure or single-effect | Yool either reads OR writes, not both implicitly |
| Returns a receipt | Every yool execution emits exactly one receipt |

#### Anti-patterns

```
# NO - multiple verbs
agent.lint_and_test.python

# NO - implicit fan-out
agent.deploy.all_envs

# NO - opaque action
agent.do.thing

# YES - split into independent yools
agent.lint.python
agent.test.python
agent.deploy.staging
agent.deploy.prod
```

A yool is **not** a function. A function might back a yool, but the yool itself is the **addressable symbol + contract**, decoupled from implementation.

### 2.2 tuple

The envelope. Wraps a payload of yools with everything needed to route, authorize, budget, audit, and replay.

#### Canonical schema (v1)

```jsonc
{
  "id":         "sha256:abc123...",
  "schema":     "yool-tuple/v1",
  "map_pos":    {
    "repo":      "EVT",
    "branch":    "feat/JIRA-456",
    "sprint_id": "JIRA-456",
    "stack":     "dotnet"
  },
  "authority":  {
    "user":  "wes",
    "agent": "sendsprint",
    "ci":    false
  },
  "lane":       "build",
  "agent_terms": {
    "budget_usd":     0.50,
    "budget_tokens":  50000,
    "deadline_iso":   "2026-05-19T20:00:00Z",
    "max_retries":    2,
    "cpu_quota_pct":  60,
    "disk_quota_mb":  100
  },
  "src_ptr": [
    "jira://EVT/JIRA-456",
    "commit://abc123"
  ],
  "payload": [
    {"yool": "agent.dev.dotnet",  "args": {}},
    {"yool": "agent.lint.dotnet", "args": {}},
    {"yool": "agent.test.dotnet", "args": {"filter": "Unit"}}
  ],
  "receipts":   [],
  "parent_id":  null,
  "created_at": "2026-05-19T17:30:00Z"
}
```

#### Field semantics

| Field | Purpose | Mutability |
|---|---|---|
| `id` | Content hash of canonical form (excluding `id` itself) | immutable post-creation |
| `schema` | Version of this schema | immutable |
| `map_pos` | Where in the project graph this tuple lives | immutable |
| `authority` | Who/what authorized this work | immutable |
| `lane` | Routing key for workers | immutable (re-emit to change) |
| `agent_terms` | Budget envelope + guardrails | immutable |
| `src_ptr` | Provenance pointers (issue, commit, doc) | immutable |
| `payload` | Ordered yool program | immutable |
| `receipts` | Receipt ids appended as yools complete | append-only |
| `parent_id` | Parent tuple in DAG | immutable |
| `created_at` | Wall clock at creation | immutable |

#### Properties

- **Content-addressable**: `id = sha256(canonical(tuple_without_id))`. Same input -> same id -> free dedupe.
- **Self-describing**: `schema` field allows v1 and v2 to coexist on the bus.
- **Replayable**: every field needed to re-execute is on the envelope.
- **Auditable**: `authority` + `src_ptr` make every action traceable.

#### 1.8.4 Receipt schema reference

Receipts are append-only, content-addressed execution records written under a repo-local `.receipts/` tree.

Minimum receipt shape:

```json
{
  "id": "sha256:<content-hash>",
  "tuple_id": "sha256:<tuple-hash>",
  "yool_id": "agent.dev.python",
  "status": "ok",
  "created_at": "2026-05-19T17:30:00Z",
  "artifacts": [],
  "cost": {
    "tokens": 0,
    "usd": 0
  }
}
```

Required properties:

- `id` is the content hash of the canonical receipt body.
- `tuple_id` links the receipt back to the tuple that dispatched the yool.
- `yool_id` identifies the capability that produced the artifact.
- `status` is terminal (`ok`, `error`, `cached`, `skipped`).
- `artifacts` points to any persisted evidence generated by the run.
- `cost` records token and currency spend when the execution uses metered models or services.

Recommended layout:

```text
.receipts/<sha-prefix-2>/<sha-rest>.json
```

Projects may mirror or compact receipts into `.catalog/receipts/`, but the canonical repo-level convention for scaffolds is `.receipts/` plus content-addressable file names.

### 2.3 HAMT (Hash Array Mapped Trie)

A persistent dictionary structure. Used here to **catalog** all yools, agents, IDEs, operators under a single addressable namespace.

#### Why HAMT vs flat dict

| Concern | Flat dict | HAMT |
|---|---|---|
| Lookup | O(1) avg, O(n) worst | O(log32 n) bounded |
| Memory on update | Rewrite-heavy | Structural sharing (only touched path copied) |
| Concurrency | Mutex required | Lock-free reads (immutable nodes) |
| Distribution | Hard to shard | Trivially shardable by top-level slot |
| Audit history | None | Hashes form Merkle chain |
| Size at scale | Memory bloat at >100k | Bounded depth = bounded memory walk |

#### Parameters used

- Hash: BLAKE2b-64 truncated to 30 bits
- Bits per level: 5 (branching factor = 32)
- Max levels: 6
- Address space pre-collision: 2^30 ~= 1.07 billion

A yool name like `agent.dev.python` is hashed; the 30-bit hash decomposes into 6 slot indices `[s0..s5]` that walk the trie. Collisions beyond level 6 collapse to a `collision` leaf list.

Reference: Phil Bagwell, *Ideal Hash Trees* — https://lampwww.epfl.ch/papers/idealhashtrees.pdf

### 2.4 tuple-space

The coordination substrate. Producers `out` tuples; consumers `in`/`rd` tuples matching a pattern.

**Linda primitives** (Gelernter 1985):

| Primitive | Semantics |
|---|---|
| `out(tuple)` | Publish to space. Non-blocking. |
| `in(pattern)` | Remove and return one matching tuple. Blocks until match. |
| `rd(pattern)` | Read (don't remove) one matching tuple. Blocks until match. |
| `eval(template)` | Spawn an active tuple that computes itself, becoming a passive tuple. |

A worker handling `lane=build`:

```python
while True:
    t = bus.in_({"lane": "build"})
    receipt = run(t)
    bus.out_(t.with_receipt(receipt))
```

That's the entire orchestrator.

Reference: David Gelernter, *Generative Communication in Linda*, ACM TOPLAS 1985.

### 2.5 receipt

The output artifact of a yool execution.

```jsonc
{
  "id":         "sha256:def456...",
  "yool":       "agent.test.pytest",
  "tuple_id":   "sha256:abc123...",
  "started_at": "2026-05-19T17:30:00Z",
  "ended_at":   "2026-05-19T17:31:12Z",
  "exit":       0,
  "stdout_sha": "sha256:111...",
  "stderr_sha": "sha256:222...",
  "artifacts":  [
    {"kind": "junit",    "path": "evidence/sha:333.../junit.xml"},
    {"kind": "coverage", "path": "evidence/sha:444.../coverage.json"}
  ],
  "cost":       {"usd": 0.012, "tokens_in": 1200, "tokens_out": 800, "wall_ms": 72000, "disk_mb": 4.2}
}
```

Receipts are **immutable** and **content-addressable**. Two yool runs with the same input hash MAY share a receipt — that's the cache key.

### 2.6 MCP edge

Model Context Protocol surfaces are **read-mostly snapshots** of the tuple-space, not the bus itself.

| Allowed | Disallowed |
|---|---|
| `catalog.lookup(name)` | `tuple.in()` / `tuple.out()` (inner loop) |
| `catalog.list_by_lane(lane)` | per-yool dispatch |
| `tuple.dispatch(tuple)` (returns receipt id) | streaming raw tuple events without ETag |
| `tuple.observe(id)` (SSE, cacheable) | mutation of catalog/receipts |
| `receipt.get(id)` | |

Why: latency, cost, cacheability. MCP is fine for snapshot dashboards and external agent observation. Putting inner-loop semantics behind MCP turns every tuple emit into a network call.

Reference: MCP tools spec — https://modelcontextprotocol.io/specification/draft/server/tools

---

## 3. Architecture

### 3.1 Static layout

```
+------------------------------------------------------------+
|                    Capability Catalog                       |
|                    (HAMT, addressable)                      |
|                                                             |
|   agent.dev.*    agent.lint.*    agent.test.*               |
|   agent.security.*   agent.pr.*   agent.deploy.*            |
|   ide.*          op.*             fs.*    net.*             |
|                                                             |
|   storage: .catalog/capabilities.json (versioned in repo)   |
+------------------------------------------------------------+
                            ^
                            | resolve(name) -> impl
                            |
+------------------------------------------------------------+
|                       Tuple Space                           |
|                     (Linda bus)                             |
|                                                             |
|   .catalog/tuples.jsonl  (append-only, content-addressable) |
|                                                             |
|   producers --out--> [tuple] --in--> subscribers            |
|                       ^   |                                 |
|                       |   v                                 |
|                .catalog/receipts/  (content-addressable)    |
+------------------------------------------------------------+
                            ^
                            | snapshot
                            |
+------------------------------------------------------------+
|                       MCP Edge                              |
|   catalog.lookup   catalog.list   tuple.dispatch            |
|   tuple.observe (SSE)   receipt.get                         |
+------------------------------------------------------------+
                            ^
                            |
                  Claude / Codex / Copilot / Dashboard
```

### 3.2 Dynamic flow (one item)

```
1. user/CI/agent emits tuple T0
   { lane: "build", map_pos: {...}, payload: [yool_a, yool_b, yool_c] }

2. catalog resolves each yool to an impl
   yool_a -> agent.dev.python.v1
   yool_b -> agent.lint.ruff.v3
   yool_c -> agent.test.pytest.v2

3. worker pool subscribes lane="build"
   worker pulls T0, executes payload sequentially or in parallel per dep graph

4. each yool emits a receipt R_a, R_b, R_c
   each receipt is content-addressed; cache check before recompute

5. final receipt R_T0 = aggregate(R_a, R_b, R_c)
   tuple log appends T0 + R_T0

6. MCP snapshot reflects new state
   dashboard / Claude observe via SSE
```

### 3.3 Failure & resume

```
crash mid-flight
        |
        v
restart reads tuples.jsonl
        |
        v
filter tuples with no terminal receipt
        |
        v
re-emit on bus (idempotent: id collision = skip)
        |
        v
workers reprocess; cached receipts short-circuit
```

### 3.4 HAMT trie example

Sample insertion of 3 yools - trie state after each step.

```
Initial: empty Node { bitmap=0, children={} }

insert(agent.dev.python)        hash=011010... slots=[13, 4, 22, 9, 1, 7]

  Node { bitmap=...10000000000000, children={13: Leaf(agent.dev.python)} }

insert(agent.lint.ruff)         hash=000111... slots=[3, 21, 0, 18, 30, 12]

  Node { bitmap=...10000000001000, children={3:  Leaf(agent.lint.ruff),
                                              13: Leaf(agent.dev.python)} }

insert(agent.dev.dotnet)        hash=011010... slots=[13, 7, 1, 28, 4, 19]
                                collides with agent.dev.python at level 0 (slot 13)

  Node {
    bitmap=...,
    children={
      3:  Leaf(agent.lint.ruff),
      13: Node {                       # subnode created
        bitmap=...,
        children={
          4: Leaf(agent.dev.python),   # at level 1, slot 4
          7: Leaf(agent.dev.dotnet)    # at level 1, slot 7
        }
      }
    }
  }
```

### 3.5 Tuple-space example (Linda flow)

```
Time   Producer              Bus                                Worker(build)
----   ---------------       ----------------------------       --------------
t0     emit(T0)         -->  [T0{lane:build}]
                                                                in({lane:build})
t1                                                              <-- T0
t2                                                              run(agent.dev.dotnet)
                                                                  cache miss; exec
                                                                  emit receipt R_a
t3                            [T0{...receipts:[R_a]}]           run(agent.lint.dotnet)
                                                                  cache HIT; reuse
t4                            [T0{...receipts:[R_a,R_b]}]       run(agent.test.dotnet)
                                                                  cache miss; exec
                                                                  emit receipt R_c
t5                            [T0{...receipts:[R_a,R_b,R_c]}]   out(T0_done)
                                                                aggregate R_T0
t6     observe(T0)       <--  [T0_done]
```

---

## 4. Algorithms

### 4.1 yool name hashing

```python
import hashlib

def yool_hash(name: str) -> int:
    h = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, "big") & ((1 << 30) - 1)
```

### 4.2 HAMT slot decomposition

```python
def slots(h: int, levels: int = 6, bits: int = 5) -> list[int]:
    mask = (1 << bits) - 1
    return [(h >> ((levels - 1 - lvl) * bits)) & mask for lvl in range(levels)]
```

### 4.3 HAMT insert (full)

```python
def insert(root: Node, leaf: Leaf, level: int = 0) -> None:
    if level >= MAX_LEVELS:
        slot = leaf.hash & (BRANCH - 1)
        existing = root.children.get(slot)
        if existing is None:
            root.bitmap |= 1 << slot
            root.children[slot] = Collision(hash_prefix=leaf.hash, leaves=[leaf])
        elif isinstance(existing, Collision):
            existing.leaves.append(leaf)
        else:
            raise RuntimeError("unexpected node at collision depth")
        return

    slot = slot_at(leaf.hash, level)
    existing = root.children.get(slot)

    if existing is None:
        root.bitmap |= 1 << slot
        root.children[slot] = leaf
        return

    if isinstance(existing, Leaf):
        if existing.hash == leaf.hash and existing.key == leaf.key:
            existing.tuple = leaf.tuple
            return
        sub = Node()
        insert(sub, existing, level + 1)
        insert(sub, leaf, level + 1)
        root.children[slot] = sub
        return

    if isinstance(existing, Node):
        insert(existing, leaf, level + 1)
        return
```

### 4.4 HAMT lookup

```python
def lookup(root: Node, key: str) -> Leaf | None:
    h = yool_hash(key)
    node = root
    for lvl in range(MAX_LEVELS):
        slot = slot_at(h, lvl)
        child = node.children.get(slot)
        if child is None:
            return None
        if isinstance(child, Leaf):
            return child if child.key == key else None
        if isinstance(child, Collision):
            for leaf in child.leaves:
                if leaf.key == key:
                    return leaf
            return None
        node = child
    return None
```

### 4.5 Tuple id

```python
import json, hashlib

def tuple_id(t: dict) -> str:
    t_no_id = {k: v for k, v in t.items() if k != "id"}
    canonical = json.dumps(t_no_id, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

### 4.6 Receipt content addressing

```python
def receipt_id(receipt: dict) -> str:
    h = hashlib.sha256()
    h.update(receipt["yool"].encode())
    h.update(str(receipt["exit"]).encode())
    h.update(receipt["stdout_sha"].encode())
    h.update(receipt["stderr_sha"].encode())
    for a in receipt.get("artifacts", []):
        h.update(a["path"].encode())
    return "sha256:" + h.hexdigest()
```

### 4.7 Cache check

```python
def input_hash(yool: str, args: dict, file_shas: list[str], env_whitelist: dict) -> str:
    h = hashlib.sha256()
    h.update(yool.encode())
    h.update(json.dumps(args, sort_keys=True).encode())
    for sha in sorted(file_shas):
        h.update(sha.encode())
    for k, v in sorted(env_whitelist.items()):
        h.update(f"{k}={v}".encode())
    return h.hexdigest()

def cached_receipt(yool: str, ih: str):
    return receipt_store.get(f"{yool}@{ih}")
```

---

## 5. End-to-End Example: SendSprint Adoption

### 5.1 Before - imperative pipeline

```python
class SprintFlow:
    def __init__(self, sprint_id, stack):
        self.sprint_id = sprint_id
        self.stack = stack

    def run(self):
        items = jira.fetch_sprint(self.sprint_id)
        for item in items:
            code = self._dev(item)
            self._lint(code, item)
            self._test(code, item)
            self._security_scan(code, item)
            self._create_pr(code, item)

    def _dev(self, item):
        if self.stack == "python":
            return PythonDevAgent().run(item)
        elif self.stack == "dotnet":
            return DotnetDevAgent().run(item)
        # ... 5 more elifs
```

Problems: adding a stack patches 5 methods; no caching; crash mid-sprint restarts from scratch; no audit beyond logs.

### 5.2 After - yool/tuple/HAMT

```python
class SprintFlow:
    def __init__(self, sprint_id, stack, bus, catalog, receipts):
        self.sprint_id = sprint_id
        self.stack = stack
        self.bus = bus
        self.catalog = catalog
        self.receipts = receipts

    def run(self):
        items = self._emit(yool="op.jira.fetch_sprint", args={"sprint_id": self.sprint_id})
        for item in items:
            tuple_ = Tuple(
                map_pos={"sprint_id": self.sprint_id, "stack": self.stack, "item": item.id},
                lane="build",
                agent_terms={"budget_usd": 0.50, "cpu_quota_pct": 60, "disk_quota_mb": 100},
                payload=[
                    {"yool": f"agent.dev.{self.stack}",  "args": {"item": item}},
                    {"yool": f"agent.lint.{self.stack}", "args": {}},
                    {"yool": f"agent.test.{self.stack}", "args": {}},
                    {"yool": "agent.security.scan",       "args": {}},
                    {"yool": "agent.pr.create",           "args": {}},
                ],
                src_ptr=[f"jira://{item.id}"],
            )
            self.bus.out_(tuple_)
```

Adding a new stack = add `agent.dev.<newstack>` to the catalog. Zero touches to `SprintFlow`.

### 5.3 Worker

```python
async def worker(lane: str, bus, catalog, receipts):
    async for t in bus.subscribe(lane):
        for step in t.payload:
            yool_name = step["yool"]
            args = step["args"]

            ih = input_hash(yool_name, args, file_shas=[], env_whitelist={})
            cached = receipts.find(yool_name, ih)
            if cached and cached.status == "ok" and not t.flags.get("no_cache"):
                t.receipts.append(cached.id)
                continue

            impl = catalog.lookup(yool_name)
            if impl is None:
                raise UnknownYool(yool_name)

            with cpu_throttle(t.agent_terms["cpu_quota_pct"]):
                with disk_quota(t.agent_terms["disk_quota_mb"]):
                    receipt = await impl.run(args)

            receipts.put(receipt)
            t.receipts.append(receipt.id)

        bus.out_(t)
```

### 5.4 Cache hit example

```
# First run
$ sprint run --sprint-id JIRA-456
[t=0]    op.jira.fetch_sprint     MISS  exec  cost=$0.001
[t=4s]   agent.dev.dotnet         MISS  exec  cost=$0.12
[t=18s]  agent.lint.dotnet        MISS  exec  cost=$0.01
[t=19s]  agent.test.dotnet        MISS  exec  cost=$0.04
[t=42s]  agent.security.scan      MISS  exec  cost=$0.02
[t=44s]  agent.pr.create          MISS  exec  cost=$0.01
                                                          TOTAL: $0.201

# Re-run, no source change
$ sprint run --sprint-id JIRA-456
[t=0]    op.jira.fetch_sprint     MISS  exec  cost=$0.001
[t=4s]   agent.dev.dotnet         HIT   skip  cost=$0
[t=4s]   agent.lint.dotnet        HIT   skip  cost=$0
[t=4s]   agent.test.dotnet        HIT   skip  cost=$0
[t=4s]   agent.security.scan      HIT   skip  cost=$0
[t=4s]   agent.pr.create          HIT   skip  cost=$0
                                                          TOTAL: $0.001
```

### 5.5 Crash + resume example

```
$ sprint run --sprint-id JIRA-456
[t=0]    op.jira.fetch_sprint     MISS  exec
[t=4s]   agent.dev.dotnet         MISS  exec
[t=18s]  agent.lint.dotnet        MISS  exec
[t=19s]  agent.test.dotnet        MISS  exec
^C  (kill -9)

$ sprint resume --run-id $(sprint runs list | head -1)
[resume] reading .catalog/tuples.jsonl
[resume] T0 has receipts for [op.jira.fetch_sprint, agent.dev.dotnet, agent.lint.dotnet]
[resume] re-emitting T0 from step 4 (agent.test.dotnet)
[t=0]    agent.test.dotnet        MISS  exec  cost=$0.04
[t=23s]  agent.security.scan      MISS  exec  cost=$0.02
[t=25s]  agent.pr.create          MISS  exec  cost=$0.01
                                                          TOTAL: $0.07
```

---

## 6. End-to-End Example: llm-project-mapper Adoption

### 6.1 Catalog from `AGENTS.md`

llm-project-mapper already defines agents declaratively in `AGENTS.md`. The pattern extends each entry with `yool_id`, `authority`, `lane`, `agent_terms` defaults.

#### Before

```markdown
## Agents

### dev-agent
- Role: implements code from spec
- Triggers: new task in .specs/sprints/
- Stack: auto-detect

### lint-agent
- Role: enforces style
- Triggers: post-edit
```

#### After

```markdown
## Agents

### dev-agent
- yool_id: agent.dev.${stack}.v1
- authority: [user, ci]
- lane: build
- agent_terms:
    budget_usd: 0.50
    cpu_quota_pct: 60
    disk_quota_mb: 100
- Role: implements code from spec
- Triggers: new task in .specs/sprints/

### lint-agent
- yool_id: agent.lint.${stack}.v1
- authority: [user, ci]
- lane: build
- agent_terms:
    budget_usd: 0.05
    cpu_quota_pct: 30
    disk_quota_mb: 10
- Role: enforces style
- Triggers: post-edit
```

### 6.2 `bin/build-hamt-catalog`

```bash
#!/usr/bin/env bash
# Wrapper: node -> python core.

set -euo pipefail

PY=$(command -v python3 || command -v py || { echo "python3 required"; exit 1; })

ROOT="${1:-.}"
"$PY" "$(dirname "$0")/../scripts/build_hamt.py" \
    --source "$ROOT/AGENTS.md" \
    --output "$ROOT/.catalog/capabilities.json"
```

### 6.3 npx flow

```
$ npx @wesleysimplicio/llm-project-mapper my-new-project
[scaffold] writing AGENTS.md, .specs/, .skills/, .catalog/.gitkeep ...
[scaffold] creating .catalog/capabilities.json (stub)
[scaffold] adding .receipts/ to .gitignore
[scaffold] writing bin/build-hamt-catalog

$ npx llm-project-mapper build-hamt-catalog
[build] parsed 7 agents from AGENTS.md
[build] hashing yools ... 7/7
[build] inserting into HAMT ... done
[build] wrote .catalog/capabilities.json (4.2 KB)
[build] popcount root: 7/32
```

---

## 7. Implementation Checklist

### CP1 · Capability catalog (HAMT)

- [ ] Pick storage location: `<project>/.catalog/capabilities.json`.
- [ ] Enumerate existing capabilities.
- [ ] Build catalog generator.
- [ ] Replace existing registry lookups with `catalog.lookup(name)`.
- [ ] Test: lookup unknown name returns explicit error.

### CP2 · Receipt store (content-addressable)

- [ ] Directory layout: `<project>/.catalog/receipts/<sha-prefix-2>/<sha-rest>.json`.
- [ ] `receipt_id(receipt)` helper.
- [ ] Re-key artifacts by SHA.
- [ ] Run-scoped index.
- [ ] Garbage collection policy (see §11.2).

### CP3 · Tuple log

- [ ] Append-only `<project>/.catalog/tuples.jsonl`.
- [ ] Line per emitted tuple + per receipt.
- [ ] Fsync on terminal receipts.
- [ ] Recovery script reads log + filters incomplete tuples.

### CP4 · Worker pool & lanes

- [ ] Define lanes.
- [ ] Worker = `subscribe(lane)` loop with bounded concurrency.
- [ ] Replace imperative orchestrator with emitter.
- [ ] Backpressure: queue depth per lane.
- [ ] Guardrails applied per-step (§11).

### CP5 · MCP edge

- [ ] MCP server exposes: `catalog.lookup`, `catalog.list_by_lane`, `tuple.dispatch`, `tuple.observe`, `receipt.get`.
- [ ] No write semantics besides `dispatch`.
- [ ] Snapshot endpoint cacheable.

### CP6 · Budget enforcement

- [ ] `agent_terms` on every tuple.
- [ ] Worker computes projected cost; reject above remaining budget.
- [ ] Receipt records actual cost.
- [ ] Aggregator emits alarm tuple on threshold.

---

## 8. Migration Playbook

| Step | Mechanism | Risk |
|---|---|---|
| 1. Generate catalog | Run builder against current registry. Commit JSON. | none |
| 2. Dual-read | Existing code uses old dict; new code reads catalog. Diff on mismatch. | low |
| 3. Receipt shim | Wrap existing artifact writes to emit content-addressed copy. | low |
| 4. Tuple log shim | Write tuple lines alongside current run state. | low |
| 5. Cut orchestrator | Refactor flow to emit/await. Old path under feature flag. | medium |
| 6. Workers replace direct calls | Subscribe-based execution. | medium |
| 7. Cache lookup | Before running yool, check receipt store. | medium |
| 8. MCP server | Expose snapshot. | low |
| 9. Budget enforcement | Add `agent_terms` to all tuples, enforce in workers. | low |
| 10. Remove old orchestrator | Once stable for N sprints, delete dual paths. | low |

---

## 9. Reference Implementations

This repo:

- `scripts/build_hamt.py` — Python HAMT builder.
- `examples/python/minimal_bus.py` — minimal Linda-style tuple-space.
- `examples/python/receipts.py` — content-addressable receipt store.
- `examples/node/build-catalog.mjs` — Node wrapper invoking Python core.
- `guardrails/cpu_throttle.py` — CPU quota enforcement (§11.1).
- `guardrails/disk_gc.py` — receipt store GC (§11.2).

Adopters:

- SendSprint — Python: `scripts/build_agent_catalog.py`, `src/sendsprint/bus/`, `src/sendsprint/receipts/`.
- llm-project-mapper — Node + Python: `bin/build-hamt-catalog`, `.catalog/capabilities.json`.

---

## 10. Foundational Literature

| Concept | Reference |
|---|---|
| Tuple spaces / coordination | Gelernter, *Generative Communication in Linda*, ACM TOPLAS 1985 |
| HAMT / persistent hash trie | Bagwell, *Ideal Hash Trees*, EPFL 2001 |
| Locality-preserving multi-attr indexing | Jagadish, *Linear Clustering of Objects with Multiple Attributes* |
| Hilbert clustering analysis | Moon/Jagadish/Faloutsos/Saltz |
| Information theory base | Shannon, *A Mathematical Theory of Communication* |
| Model Context Protocol tools | MCP spec — https://modelcontextprotocol.io/specification/draft/server/tools |
| Content-addressable storage | Merkle, *Protocols for Public Key Cryptosystems*, IEEE S&P 1980 |
| Persistent data structures | Okasaki, *Purely Functional Data Structures*, 1998 |

---

## 11. Guardrails (MANDATORY)

> Origin of this section: field observation from Victor "Dev Hermes" Genaro (2026-05-19):
> *"precisa de guardrail pra não fritar o processador. Você precisa de garbage collector também pra não encher 100% do disco."*
>
> Any adopter MUST implement both before going past CP4 (worker pool). Without them, a runaway agent or receipt-store explosion can take down the host.

### 11.1 CPU throttle (don't fry the CPU)

#### Problem

A worker that pulls tuples as fast as it can will pin every available core. Multiple workers compound. Local dev box becomes unusable; cloud VM hits CPU throttling and gets killed.

#### Policy

Every tuple carries `agent_terms.cpu_quota_pct` (0-100). Worker MUST enforce this before invoking the yool's implementation.

#### Reference implementation (Python, POSIX)

```python
# guardrails/cpu_throttle.py
import os
import contextlib

@contextlib.contextmanager
def cpu_throttle(quota_pct: int):
    """Soft CPU throttle via niceness. For hard throttle, use cgroups (Linux)."""
    if quota_pct >= 100:
        yield
        return

    # Niceness mapping: 60% -> nice 5, 30% -> nice 10, 10% -> nice 15
    nice_delta = max(0, int(round((100 - quota_pct) / 6)))
    try:
        os.nice(nice_delta)
    except OSError:
        pass
    try:
        yield
    finally:
        try:
            os.nice(-nice_delta)
        except OSError:
            pass
```

#### Stricter alternative (cgroups, Linux only)

```bash
cgcreate -g cpu:/yool-worker-${WORKER_ID}
echo $((quota_pct * 1000)) > /sys/fs/cgroup/yool-worker-${WORKER_ID}/cpu.max
cgexec -g cpu:/yool-worker-${WORKER_ID} python -m sendsprint.worker
```

#### macOS alternative

```bash
taskpolicy -c utility python -m sendsprint.worker
```

#### Enforcement points

1. **Worker startup**: read default `cpu_quota_pct` from project config (`.catalog/policy.yaml`).
2. **Per-tuple**: override with `agent_terms.cpu_quota_pct`.
3. **Per-yool**: implementation MAY further reduce (never raise).

#### Test

```python
def test_cpu_throttle_under_quota():
    with cpu_throttle(50):
        burn_cpu(seconds=2)
    assert measured_cpu_time() < 1.5
```

### 11.2 Disk GC (don't fill 100%)

#### Problem

Receipts + tuple logs + cached artifacts grow unbounded. Daily sprint with 100 items × 5 yools × 50 KB artifacts = 25 MB/day = 9 GB/year. Multiply by N projects.

#### Policy — three retention tiers

| Tier | What | Retention | Why |
|---|---|---|---|
| **hot** | Last N runs of receipts, tuple log, artifacts | default 30 days | active debugging, cache hits |
| **warm** | Receipts only (not artifacts), pointer index | default 365 days | replay + audit |
| **cold** | Hash + pointer record only (artifacts purged) | forever | provenance trail |

Receipts themselves are **never deleted**, only their **artifact bodies**. Preserves the immutable Merkle chain.

#### Reference implementation

```python
# guardrails/disk_gc.py
import json, os, pathlib
from datetime import datetime, timedelta, timezone

def gc_run(catalog_dir: pathlib.Path, hot_days: int = 30, warm_days: int = 365, max_total_mb: int = 5000):
    """
    Phase 1: artifact body purge for receipts older than hot_days.
    Phase 2: hard size cap (max_total_mb): purge oldest until under cap.
    Phase 3: rotate tuples.jsonl (daily file, gzip yesterday's).
    """
    now = datetime.now(timezone.utc)
    hot_cutoff = now - timedelta(days=hot_days)

    receipts_dir = catalog_dir / "receipts"
    artifacts_dir = catalog_dir / "artifacts"

    purged_artifacts = 0
    purged_bytes = 0

    for receipt_file in receipts_dir.rglob("*.json"):
        r = json.loads(receipt_file.read_text())
        ts = datetime.fromisoformat(r["ended_at"])
        if ts < hot_cutoff:
            for art in r.get("artifacts", []):
                p = artifacts_dir / art["path"]
                if p.exists():
                    purged_bytes += p.stat().st_size
                    p.unlink()
                    purged_artifacts += 1
            r["artifacts_purged_at"] = now.isoformat()
            receipt_file.write_text(json.dumps(r, indent=2))

    total_mb = _du_mb(catalog_dir)
    while total_mb > max_total_mb:
        oldest = _find_oldest_artifact(artifacts_dir)
        if oldest is None:
            break
        purged_bytes += oldest.stat().st_size
        oldest.unlink()
        purged_artifacts += 1
        total_mb = _du_mb(catalog_dir)

    _rotate_daily(catalog_dir / "tuples.jsonl")

    return {
        "artifacts_purged": purged_artifacts,
        "bytes_freed": purged_bytes,
        "total_mb_after": _du_mb(catalog_dir),
    }
```

#### Schedule

```cron
# Cron: nightly at 03:00
0 3 * * * cd ~/Projetos/SendSprint && python -m sendsprint.gc --hot-days 30 --warm-days 365 --max-mb 5000
```

#### Disk pressure circuit breaker

```python
def check_disk_pressure(catalog_dir: pathlib.Path, free_mb_floor: int = 1000):
    stat = os.statvfs(catalog_dir)
    free_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
    if free_mb < free_mb_floor:
        bus.out_(Tuple(lane="gc.urgent", payload=[{"yool": "fs.gc.run", "args": {}}]))
        raise DiskPressure(f"free={free_mb:.0f}MB below floor={free_mb_floor}MB")
```

#### Test

```python
def test_gc_purges_warm_tier_artifacts(tmp_path):
    setup_receipts(tmp_path, recent=50, old=50)
    result = gc_run(tmp_path, hot_days=30)
    assert result["artifacts_purged"] == 50
    assert len(list((tmp_path / "receipts").rglob("*.json"))) == 100
```

### 11.3 Memory & token guardrails

Every yool implementation MUST:

- Stream large inputs/outputs to disk rather than buffer.
- Respect `agent_terms.budget_tokens` (LLM calls).
- Emit incremental cost into receipt as work progresses.

---

## 12. Glossary

- **address space** — set of distinct identifiers a system can refer to.
- **bitmap** — per-HAMT-node bitfield indicating populated child slots.
- **collision** — two keys hashing to the same path beyond max trie depth.
- **lane** — coarse-grained routing key on a tuple.
- **leaf** — terminal HAMT node holding a key/value pair.
- **map_pos** — semantic coordinates inside a tuple.
- **opcode** — synonym for yool name.
- **payload** — ordered list of yool invocations inside a tuple.
- **popcount** — number of bits set in a HAMT node's bitmap.
- **receipt** — immutable, content-addressed record of one yool execution.
- **slot** — index into a HAMT node's children array.
- **structural sharing** — persistent-data-structure update strategy.
- **tuple space** — Linda-style coordination substrate.

---

## 13. Versioning

| Version | Date | Changes |
|---|---|---|
| v0.1 | 2026-05-19 | Initial draft |
| v0.2 | 2026-05-19 | Expanded examples (SendSprint, llm-project-mapper); guardrails (§11); end-to-end cache/resume flows; HAMT lookup algorithm. |

---

## Appendix A — FAQ

**Q: Isn't this just Kafka + a registry?**
A: Kafka is the bus, fine. The pattern adds: (1) HAMT-addressed catalog, (2) content-addressable receipts as cache keys, (3) tuple as canonical unit of work with budget/authority. Kafka alone gives transport, not addressing.

**Q: Why blake2b for hashing instead of sha256?**
A: HAMT addressing benefits from speed over cryptographic strength. blake2b-64 is faster than sha256 and 30 bits suffices for catalog sizes under ~1M. Receipts use sha256 because content-addressing needs collision resistance.

**Q: How does this interact with my existing MCP server?**
A: Your MCP server becomes the **edge** in §3.1. Expose `catalog.lookup`, `tuple.dispatch`, `tuple.observe`. Don't expose `tuple.in/out`.

**Q: How do I migrate without breaking prod?**
A: §8 playbook. Dual-read step is key: catalog runs alongside old dict, diff on every lookup. When diffs zero for N days, flip the switch.

**Q: What about distributed workers?**
A: Tuple-space scales horizontally — workers on different hosts sharing the bus (Kafka, Redis Streams, NATS). HAMT itself is immutable so distribution is read-trivial.

**Q: Why force guardrails (§11) if my project is small?**
A: Small projects grow. Guardrail cost is low (<=200 LOC for both). Cost of retrofit after a runaway agent fries a laptop is high.

---

## Appendix B — Diagram Index

- §3.1 — Static layout (3 layers)
- §3.2 — Dynamic flow (one item end-to-end)
- §3.3 — Failure & resume
- §3.4 — HAMT trie insertion
- §3.5 — Linda tuple-space timeline

---

## Appendix C — Quick Vendor Instructions

```bash
# Vendor the spec
curl -L https://raw.githubusercontent.com/wesleysimplicio/yool-tuple-hamt/main/YOOL_TUPLE_HAMT.md \
    -o YOOL_TUPLE_HAMT.md

# Or as a submodule (read-only consumer)
git submodule add https://github.com/wesleysimplicio/yool-tuple-hamt vendor/yool-tuple-hamt

# Copy reference impls
cp vendor/yool-tuple-hamt/scripts/build_hamt.py scripts/
cp vendor/yool-tuple-hamt/guardrails/cpu_throttle.py src/guardrails/
cp vendor/yool-tuple-hamt/guardrails/disk_gc.py src/guardrails/

# Generate catalog
python scripts/build_hamt.py --source AGENTS.md --output .catalog/capabilities.json

# Wire workers to use catalog.lookup + receipts + guardrails

# Add GC schedule (cron / launchd / systemd)
```
