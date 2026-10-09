INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/LIFE_ASSISTANT_SPEC.md','project_doc','doc://simplicio-runtime/docs/roadmap/LIFE_ASSISTANT_SPEC.md','doc: Life Assistant Specification','# Life Assistant Specification

## Overview

The Life Assistant cluster extends Simplicio beyond programming into personal
productivity domains: job search, health, family, social media, and ecommerce.
Each agent is a governed skill (Action Gate required for mutations) that runs
deterministically in the Rust runtime, with LLM escalation only for generation.

Target milestones: v0.2 (job + health scaffolds), v0.3 (family + social + ecommerce).

---

## 1. Job Search Agent (#2135, #2136)

### Capabilities
- Parse and store structured CV/resume (`simplicio life job cv-import <file>`).
- Search job boards via tool adapters (LinkedIn, Indeed, Glassdoor scrape or API).
- Score job matches against CV + user preferences (skills, salary, location, remote).
- Draft tailored cover letters (LLM, gated).
- Track application pipeline (applied / interview / offer / rejected).
- Daily digest: new matches + pipeline status.

### Data Model
```rust
struct JobListing {
    id: Uuid,
    title: String,
    company: String,
    location: Option<String>,
    remote: bool,
    salary_range: Option<(u32, u32)>,
    skills_required: Vec<String>,
    url: String,
    fetched_at: DateTime<Utc>,
}

struct Application {
    listing_id: Uuid,
    status: AppStatus,  // Saved|Applied|Interview|Offer|Rejected
    applied_at: Option<DateTime<Utc>>,
    notes: String,
}
```

### Commands
```
simplicio life job search [--remote] [--salary-min N] [--skills rust,python]
simplicio life job apply <listing_id> [--cover-letter]
simplicio life job pipeline
simplicio life job digest
```

### Gate Policy
- `search`: safe (read-only web fetch)
- `apply` with `--cover-letter`: auto (LLM generation, no external POST)
- actual form submission to external site: ask (user confirms each)

---

## 2. Health Assistant (#2137, #2138)

### Capabilities
- Log health metrics: weight, sleep, steps, HRV, medications, mood.
- Import from Apple Health / Google Fit via CSV export.
- Trend analysis: weekly/monthly charts (text-based ASCII or web dashboard).
- Medication reminders (`simplicio life health remind --med X --time 08:00`).
- Symptom journal with optional pattern detection.
- No diagnostic LLM outputs by default (safety policy; opt-in with disclaimer).

### Data Model
```rust
enum HealthEntry {
    Weight    { value_kg: f32, ts: DateTime<Utc> },
    Sleep     { hours: f32, quality: u8, ts: DateTime<Utc> },
    Steps     { count: u32, date: NaiveDate },
    HRV       { ms: f32, ts: DateTime<Utc> },
    Mood      { score: u8, note: String, ts: DateTime<Utc> },
    Symptom   { description: String, severity: u8, ts: DateTime<Utc> },
    Medication{ name: String, dose_mg: f32, ts: DateTime<Utc> },
}
```

### Commands
```
simplicio life health log weight 72.5
simplicio life health log sleep 7.5 --quality 4
simplicio life health trend weight --days 30
simplicio life health remind --med Vitamin-D --time 09:00
simplicio life health import apple-health export.xml
```

### Privacy
- All data stored locally (`.simplicio-loop/life/health.db`).
- Never synced to cloud by default (`scope=local`).
- Opt-in: `simplicio life health export --format csv` for user-controlled sharing.

---

## 3. Family Assistant (#2139, #2140)

### Capabilities
- Shared family calendar (local + optional mesh sync to household devices).
- Contact management with relationship tags (family/friend/colleague).
- Birthday and anniversary reminders with suggested messages (LLM, gated).
- Gift tracking: ideas, budget, purchased.
- Household task assignment and chore tracker.
- Shared grocery list (mesh-synced to paired phones/tablets).

### Data Model
```rust
struct FamilyEvent {
    id: Uuid,
    title: String,
    datetime: DateTime<Utc>,
    recurrence: Option<Recurrence>,
    attendees: Vec<String>,  // contact refs
    notes: String,
}

struct Contact {
    id: Uuid,
    name: String,
    relation: Vec<String>,
    birthday: Option<NaiveDate>,
    anniversary: Option<NaiveDate>,
    notes: String,
}
```

### Commands
```
simplicio life family event add "School play" --date 2026-07-15 --who Alice,Bob
simplicio life family contacts add "Mom" --relation parent --birthday 1955-03-12
simplicio life family reminders
simplicio life family chores add "Take out trash" --assigned Alice --recur weekly
simplicio life family groceries add "Milk x2"
```

---

## 4. Social Media Agent (#2141, #2142)

### Capabilities
- Draft posts for multiple platforms (LLM, gated).
- Platform adapters: Twitter/X, LinkedIn, Instagram (caption only), Mastodon.
- Scheduling queue: write now, post at configured time via adapter.
- Engagement digest: mentions, replies, follower delta (read-only polling).
- Content calendar integration (links to `docs/roadmap/` editorial calendar).
- Analytics summary: reach, engagement rate, top posts.

### Gate Policy
- Draft generation: auto (LLM, no external call)
- Schedule (queue only): auto
- Post to platform: ask (user confirms per post)
- Read-only polling: safe

### Commands
```
simplicio life social draft "Launch post for v0.3" --platform linkedin,twitter
simplicio life social schedule --post <id> --at "2026-07-01 09:00"
simplicio life social digest
simplicio life social analytics --platform linkedin --days 30
```

---

## 5. Ecommerce Agent (#2143, #2144)

### Capabilities
- Price tracking: monitor product URLs, alert on price drop.
- Purchase history import (CSV/email parsing).
- Wish list management with budget tracking.
- Return deadline tracker.
- Seller research: aggregate reviews (read-only scrape, gated).
- Subscription tracker: recurring charges, renewal dates, cancel assist.

### Data Model
```rust
struct TrackedProduct {
    id: Uuid,
    name: String,
    url: String,
    target_price: Option<f32>,
    current_price: f32,
    last_checked: DateTime<Utc>,
    price_history: Vec<(DateTime<Utc>, f32)>,
}

struct Subscription {
    id: Uuid,
    service: String,
    monthly_cost: f32,
    renewal_date: NaiveDate,
    category: String,
    notes: String,
}
```

### Com','docs/roadmap/LIFE_ASSISTANT_SPEC.md','a3e7fe824cc5c667b8889d78c945b600dcf5914c5e8b252881c24762e2caa09e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/MARKETING_STRATEGY.md','project_doc','doc://simplicio-runtime/docs/roadmap/MARKETING_STRATEGY.md','doc: Simplicio Marketing Strategy','# Simplicio Marketing Strategy

## Brand Positioning

**Tagline:** "Code that ships. Proven."

Simplicio is the runtime that makes AI coding deterministic — every edit is mechanical, every delivery is certified, every token saved is measured. We compete on correctness and transparency, not hype.

**Target audience:**
1. Senior engineers tired of LLM hallucinations breaking their codebase.
2. Indie hackers and solopreneurs automating their dev workflow.
3. Engineering leads evaluating AI coding tools for their team.

---

## Social Media Accounts

| Platform | Handle | Primary content | Cadence |
|---|---|---|---|
| GitHub | github.com/wesleysimplicio/simplicio | releases, issues, README | on release |
| Twitter/X | @simplicio_sh | quick demos, benchmarks, threads | 3×/week |
| LinkedIn | linkedin.com/company/simplicio | case studies, product updates | 2×/week |
| YouTube | youtube.com/@simplicio_sh | full demos, tutorials, benchmarks | 1×/week |
| TikTok | @simplicio.sh | 60s before/after clips | 3×/week |
| Instagram | @simplicio.sh | visual before/after, code aesthetics | 3×/week |
| Discord | discord.gg/simplicio | community, support, early access | always-on |

---

## Content Calendar (recurring themes)

### Weekly rhythm
- **Monday:** "Week in Simplicio" — what shipped, what''s next (Twitter thread + LinkedIn post).
- **Wednesday:** Technical deep-dive — one capability explained (YouTube video + blog).
- **Friday:** Community spotlight — user tip, PR of the week, or benchmark result.

### Monthly themes
- **Month 1:** Local-first AI (vs cloud dependency). Focus: 5-stage ladder, zero-token edits.
- **Month 2:** Deterministic delivery. Focus: delivery certificate, regression guard, action gate.
- **Month 3:** Video creation. Focus: Remotion/HyperFrames pipeline, Higgsfield integration.
- **Month 4:** Memory & context. Focus: neural memory, token savings, recall vs re-derive.
- **Month 5:** Multi-agent fabric. Focus: 600-agent burst, async Tokio, structured concurrency.
- **Month 6:** Benchmark season. Focus: Simplicio × Hermes × OpenClaw head-to-head.

---

## Higgsfield-Style Video Content

Use the Higgsfield MCP (seedance/kling/soul/nano_banana) gated by Action Gate for generative marketing videos. All generative video is approved via `simplicio gate classify` before render.

### Series: "Zero to Shipped"
- 30–60 second vertical videos showing a task going from natural language → code → tests green → delivery certificate.
- Hook (0–3s): the problem ("my LLM just broke prod"). Reveal (3–20s): Simplicio fixing it deterministically. Payoff (20–30s): certificate issued, token savings shown.
- Rendered via Higgsfield kling for cinematic quality; fallback to HyperFrames for deterministic motion graphics.

### Series: "Before / After"
- Split-screen: left = raw LLM output (broken, hallucinated). Right = Simplicio pipeline (passes tests, certified).
- Formats: 9:16 (TikTok/Instagram Reels), 16:9 (YouTube), 1:1 (LinkedIn).
- Production: HyperFrames template (deterministic HTML→MP4) for consistency; Remotion for animated code diffs.

### Series: "Token Savings Counter"
- Animated counter showing tokens saved per interaction, comparing with/without Simplicio.
- Data sourced from real sessions (anonymized). Counter animates via Remotion.

---

## Analytics Tracking

All marketing analytics use privacy-first tooling (no Google Analytics on the main site).

| Signal | Tool | Metric |
|---|---|---|
| Site traffic | Plausible (self-hosted) | visitors, referrers, top pages |
| GitHub | GitHub Insights + star-history.com | stars/week, clone trend |
| YouTube | YouTube Studio | watch time, CTR, retention |
| Twitter/X | native analytics | impressions, link clicks, follows |
| Discord | native + MEE6 | member growth, active users/week |
| CLI installs | install script counter (simplicio.sh/api/install-count) | installs/day by OS/arch |
| Conversion | Stripe dashboard | Free→Pro upgrades, churn, MRR |

### KPIs (6-month targets)
- GitHub stars: 2,000
- Discord members: 500
- YouTube subscribers: 1,000
- Pro subscribers: 50
- Monthly CLI installs: 5,000

---

## Launch Playbook

1. **Teaser week (T-7):** "Something is coming" posts with token-savings counter animation. No product name yet.
2. **Launch day:** GitHub repo goes public + Product Hunt submission + Hacker News "Show HN" post + YouTube full demo.
3. **Launch week:** daily posts on each platform; Discord community goes live; early adopter Pro trial (30 days free).
4. **Post-launch (T+30):** first benchmark video (Simplicio × Hermes × OpenClaw); case study from a beta user; blog post on the local-first ladder.','docs/roadmap/MARKETING_STRATEGY.md','e9f970f6fa423933fcc2dc683f9bd1994c271ea8f8cae204f6625b8738f2a086','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/MESH_NETWORK_ARCHITECTURE.md','project_doc','doc://simplicio-runtime/docs/roadmap/MESH_NETWORK_ARCHITECTURE.md','doc: Mesh Network Architecture','# Mesh Network Architecture

> **STATUS: PLANNED — NOT IMPLEMENTED (verified 2026-06-27).** This is a design
> document only. `src/mesh/*` does not exist; the symbols it describes
> (`best_peer_for`, `discover_services`, `hive_memory`, `scatter_gather`, …) are
> absent from the codebase. Issues #2127–#2131 were closed as "completed" but no
> code landed (see `docs/ISSUE_AUDIT_2026-06-27.md`). Re-open those issues before
> treating any of this as built.

## Overview

Simplicio Mesh enables peer-to-peer collaboration between Simplicio instances on a local
network (LAN/Wi-Fi) without requiring cloud infrastructure. Each node is autonomous;
the mesh is opportunistic — nodes join and leave without breaking the swarm.

Target milestones: v0.2 (discovery + protocol), v0.3 (skill sync + hive memory).

---

## 1. mDNS Peer Discovery (#2099, #2100)

### Service Advertisement
- Service type: `_simplicio._tcp.local.`
- TXT records: `version`, `node_id` (UUID), `capabilities` (comma-separated feature flags),
  `mesh_port` (default 7421).
- Each node broadcasts on startup; rebroadcasts every 60 s.

### Discovery Flow
```
Node A starts
  → announces _simplicio._tcp.local. via mDNS
Node B (already running)
  → receives mDNS query response
  → adds A to peer table (ip, port, node_id, caps, last_seen)
  → opens MCP handshake to A
A ↔ B exchange capability manifests
  → both update routing tables
```

### Peer Table Schema
```rust
struct MeshPeer {
    node_id: Uuid,
    addr: SocketAddr,
    caps: Vec<String>,
    last_seen: Instant,
    latency_ms: u32,
    trust_level: TrustLevel, // Local | Paired | Untrusted
}
```

### Failure Handling
- Node silent for > 90 s → marked stale; removed after 180 s.
- Split-brain: each island maintains independent operation; merges on reconnect
  via vector-clock reconciliation.

---

## 2. MCP Local Protocol (#2101, #2102)

### Transport
- TCP with TLS 1.3 (self-signed per-node cert; trust-on-first-use similar to SSH).
- Port 7421 (configurable via `mesh.port`).
- Framing: 4-byte length-prefixed JSON messages (same envelope as the remote MCP SDK).

### Handshake
```
→ {"type":"hello","node_id":"…","version":"1","caps":[…]}
← {"type":"hello-ack","node_id":"…","version":"1","caps":[…],"session_id":"…"}
```

### Message Types
| Type | Direction | Purpose |
|---|---|---|
| `task.delegate` | → | Offload a task to peer |
| `task.result` | ← | Return execution result |
| `skill.query` | → | Ask if peer has a skill |
| `skill.manifest` | ← | Return skill metadata |
| `memory.sync` | ↔ | Hive memory delta exchange |
| `heartbeat` | ↔ | Liveness ping every 15 s |
| `gate.ask` | → | Request Action Gate approval from peer |
| `gate.reply` | ← | Approve / deny |

### Security
- All messages signed with node private key (Ed25519).
- `trust_level = Local` auto-granted for same subnet (192.168/10./172.16–31.).
- `trust_level = Paired` requires explicit QR-code pairing.
- Task delegation blocked for `Untrusted` peers.

---

## 3. Skill Sync (#2103, #2104)

### Skill Manifest
```json
{
  "skill_id": "summarize-v1",
  "version": "1.2.0",
  "hash": "sha256:…",
  "capabilities": ["text","summarize"],
  "size_bytes": 4096
}
```

### Sync Protocol
1. On peer connect, exchange skill manifest lists.
2. Diff by `(skill_id, version, hash)`.
3. Missing skills fetched via `skill.fetch` request (chunked transfer, max 512 KB chunks).
4. Installed under `.simplicio-loop/skills/mesh/<node_id>/`.
5. Checksum verified before activation.

### Conflict Resolution
- Same `skill_id`, different `version`: higher semver wins.
- Same `skill_id` + `version`, different `hash`: local wins; peer notified.

---

## 4. Hive Memory (#2110, #2111)

### Model
- Each node owns a local `memory.sqlite` (FTS + vector).
- Hive layer adds a replicated CRDT log on top: `hive_log.jsonl` (append-only).
- Log entries: `{id, node_id, ts_us, kind, key, value_hash, payload}`.
- Convergence: last-write-wins per `key`; `ts_us` from hybrid logical clock.

### Sync
- On connect: exchange `(last_id, node_id)` watermarks.
- Stream missing entries delta.
- On conflict (same key, same ts, different value): lexicographic `node_id` wins.

### Privacy
- Items tagged `scope=local` never leave the originating node.
- Items tagged `scope=mesh` replicate to all paired peers.
- Default scope: `local`.

---

## 5. Distributed Processing (#2112, #2113, #2114, #2115)

### Task Routing
```
Incoming task
  → estimate complexity (token count heuristic)
  → if local agent pool < 80% utilization: run local
  → else: find peer with lowest latency + sufficient caps
  → delegate via MCP local protocol
```

### Load Balancing
- Each node broadcasts `load_report` every 5 s: `{cpu_pct, active_agents, queue_depth}`.
- Coordinator (highest-uptime node) maintains routing table; followers cache it.
- Coordinator election: Bully algorithm on `uptime_s DESC, node_id ASC`.

### Failure & Retry
- Task timeout: configurable per task type (default 30 s for LLM, 5 s for tool).
- On peer timeout: requeue locally or try next peer.
- Idempotency: tasks carry `task_id`; duplicate deliveries deduplicated by receiver.

### Capability Matching
- Each task declares required caps (e.g. `["gpu","vision"]`).
- Router selects only peers advertising all required caps.

---

## Configuration

```toml
[mesh]
enabled = true
port = 7421
discovery = "mdns"          # mdns | static | both
static_peers = []           # ["192.168.1.10:7421"]
trust_mode = "local-auto"   # local-auto | manual | off
skill_sync = true
hive_memory = true
hive_scope_default = "local"
```

---

## Implementation Phases

| Phase | Issues | Deliverable |
|---|---|---|
| v0.2-alpha | #2099–#2104 | mDNS + MCP local protocol + skill sync |
| v0.2 | #2110–#2115 | Hive memory + distributed task routing |
| v0.3 | TBD | GUI mesh dashboard, pairing UX |','docs/roadmap/MESH_NETWORK_ARCHITECTURE.md','a8503c69e1f1e8ba976be464077a594b9263d69d55fc200e173b9e19a1299c79','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/MOBILE_ROADMAP.md','project_doc','doc://simplicio-runtime/docs/roadmap/MOBILE_ROADMAP.md','doc: Mobile Roadmap — Simplicio Runtime','# Mobile Roadmap — Simplicio Runtime

## Overview

This document describes the plan for bringing Simplicio to mobile platforms
(Android and iOS) via a shared Rust core exposed through `uniffi-rs`, with
native UI layers in Kotlin/Jetpack Compose (Android) and Swift/SwiftUI (iOS).
Target milestones: v0.4–v0.6.

## Architecture

```
┌──────────────────────────────────────────────┐
│           Native UI (per platform)           │
│  Android: Kotlin + Jetpack Compose           │
│  iOS:     Swift + SwiftUI                    │
└───────────────────┬──────────────────────────┘
                    │ uniffi-rs generated bindings
┌───────────────────▼──────────────────────────┐
│           Simplicio Mobile Core (Rust)       │
│  src/mobile/                                 │
│  - chat.rs        (message I/O)              │
│  - memory.rs      (SQLite recall)            │
│  - action_gate.rs (gate classify)            │
│  - edit.rs        (deterministic edits)      │
│  - sync.rs        (desktop↔mobile sync)      │
└──────────────────────────────────────────────┘
```

## Shared Rust Core via uniffi-rs

### Crate setup

A new crate `simplicio-mobile` under `crates/simplicio-mobile/` exposes a
`uniffi`-annotated API surface:

```rust
// crates/simplicio-mobile/src/lib.rs
uniffi::setup_scaffolding!();

#[uniffi::export]
pub fn chat_send(message: String) -> String { … }

#[uniffi::export]
pub fn memory_recall(query: String, limit: u32) -> Vec<MemoryItem> { … }

#[uniffi::export]
pub fn action_gate_classify(action: String) -> GateDecision { … }
```

### Build targets

| Platform | Target triple | Output |
|---|---|---|
| Android arm64 | `aarch64-linux-android` | `.so` via Android NDK |
| Android x64 | `x86_64-linux-android` | `.so` (emulator) |
| iOS arm64 | `aarch64-apple-ios` | `.a` / XCFramework |
| iOS Simulator | `aarch64-apple-ios-sim` | `.a` / XCFramework |

### Generated bindings

```
cargo run --bin uniffi-bindgen generate \
  --library target/aarch64-apple-ios/release/libsimplicio_mobile.a \
  --language swift --out-dir ios/Sources/SimplicioCore/
```

```
cargo run --bin uniffi-bindgen generate \
  --library target/aarch64-linux-android/release/libsimplicio_mobile.so \
  --language kotlin --out-dir android/app/src/main/java/com/simplicio/core/
```

## Android (Kotlin + Jetpack Compose)

### Project structure

```
apps/android/
  app/
    src/main/
      java/com/simplicio/
        core/          # uniffi-generated bindings
        ui/            # Compose screens
          ChatScreen.kt
          MemoryScreen.kt
          SettingsScreen.kt
        MainActivity.kt
      jniLibs/         # compiled .so files
  build.gradle.kts
```

### UI screens (Compose)

| Screen | Function |
|---|---|
| ChatScreen | Full chat with streaming, action gate indicator |
| MemoryScreen | Browse/search memory items |
| SettingsScreen | Provider config, local model toggle |

### Build

```bash
./gradlew assembleRelease
# Signs with release keystore
./gradlew bundleRelease  # AAB for Play Store
```

### Minimum SDK: API 26 (Android 8.0)

## iOS (Swift + SwiftUI)

### Project structure

```
apps/ios/
  Simplicio/
    Sources/
      SimplicioCore/   # uniffi-generated Swift bindings
      Views/
        ChatView.swift
        MemoryView.swift
        SettingsView.swift
      SimplicioApp.swift
  Simplicio.xcodeproj
  Simplicio.xcworkspace
```

### UI views (SwiftUI)

| View | Function |
|---|---|
| ChatView | Full chat with streaming, gate badge |
| MemoryView | Recall and browse memory |
| SettingsView | Provider / local model config |

### Build

```bash
xcodebuild -scheme Simplicio -configuration Release \
  -destination generic/platform=iOS archive \
  -archivePath build/Simplicio.xcarchive
xcodebuild -exportArchive -archivePath build/Simplicio.xcarchive \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath build/ipa/
```

### Minimum deployment target: iOS 16

## Mobile–Desktop Sync

### Sync surface (`src/mobile/sync.rs`)

Bidirectional sync of:
- Memory items (SQLite → cloud intermediate → device SQLite).
- Action history (evidence ledger subset).
- Settings (provider config, tier preference).

### Transport options (in priority order)

1. **Local Wi-Fi (mDNS)** — zero-latency when on same network.
2. **Relay server** (user-hosted or Simplicio cloud) — E2E encrypted.
3. **iCloud / Google Drive** — file-based sync (fallback, higher latency).

### Conflict resolution

Last-write-wins on memory items (timestamp from HBP chain).
Settings: device-local wins (no override from remote without user approval).

### Sync protocol

```
POST /sync/push  { items: [...], since: <timestamp>, device_id: "..." }
POST /sync/pull  { since: <timestamp>, device_id: "..." }
```

Payload is JSONL, gzipped. Each item carries an HBP hash for tamper detection.

## Feature Parity (Mobile vs Desktop)

| Feature | Desktop | Android | iOS |
|---|---|---|---|
| Chat (streaming) | yes | yes | yes |
| Memory recall | yes | yes | yes |
| Action gate | yes | yes | yes |
| Deterministic edit | yes | no (mobile is read-only for edits) | no |
| Local LLM (in-process) | yes | future (Qualcomm NPU) | future (ANE) |
| TUI | yes | no | no |
| Dashboard (:9119) | yes | no | no |
| Voice input | yes | yes | yes |

## Milestones

| Milestone | Deliverable |
|---|---|
| v0.4 | uniffi-rs crate + Android proof-of-concept (ChatScreen) |
| v0.5 | iOS proof-of-concept (ChatView) + mobile–desktop sync v1 |
| v0.6 | Play Store + App Store submissions; local LLM investigation |','docs/roadmap/MOBILE_ROADMAP.md','41bff0d384096fe55ac4ee44f54601edf1eee868db2778621b93345fc7b7b8f7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/OPERATIONS_RUNBOOK.md','project_doc','doc://simplicio-runtime/docs/roadmap/OPERATIONS_RUNBOOK.md','doc: Operations Runbook','# Operations Runbook

## Scope
Production operations for Simplicio: observability stack, management channels,
alert policies, log centralization, uptime monitoring, and infrastructure requirements.

---

## 1. Observability Stack

### Metrics (Prometheus + Grafana)
- **Prometheus** scrapes metrics from:
  - Simplicio runtime (`/metrics` on port 9119, existing dashboard endpoint).
  - Postgres exporter (`postgres_exporter`).
  - Node exporter (host CPU/memory/disk).
  - Caddy/nginx for HTTP metrics.
- **Grafana** dashboards:
  - "Simplicio Runtime" — agent count, token throughput, LLM latency, queue depth.
  - "Infrastructure" — CPU/memory/disk/network per host.
  - "API" — request rate, error rate, p50/p95/p99 latency.
  - "Billing" — MRR, churn, failed payments (via webhook events table).

### Traces (OpenTelemetry)
- Instrument: `opentelemetry-rust` SDK, exporter to **Jaeger** or **Tempo**.
- Trace: every HTTP request, LLM call, DB query > 100ms.
- Sampling: 10% for healthy traffic; 100% for errors.

### Metrics endpoint (existing)
The runtime already exposes `GET /api/summary` → extend to Prometheus text format
at `GET /metrics` (feature-gated behind `--metrics` flag or env `SIMPLICIO_METRICS=1`).

---

## 2. Management Channels

### Primary on-call: PagerDuty
- Service: "Simplicio Production".
- Escalation policy:
  - L1 (on-call engineer): 5 min acknowledge / 15 min resolve.
  - L2 (team lead): page if L1 doesn''t acknowledge in 5 min.
  - L3 (owner): page if L2 doesn''t resolve in 30 min.

### Secondary alerting: Slack
- `#alerts-critical` — P0/P1 incidents, auto-posted from Alertmanager.
- `#alerts-warning` — P2/P3 warnings (digest every 30 min).
- `#deploys` — CI/CD events (deploy started/succeeded/failed).
- `#billing-events` — payment failures, subscription changes.

### Status page
- Public status page at `status.simplicio.ai` (Instatus or Cachet).
- Auto-update incident status from Alertmanager webhook.

---

## 3. Alert Policies

### P0 — Critical (page immediately)
| Alert | Condition | Action |
|-------|-----------|--------|
| API down | HTTP 5xx rate > 50% for 2 min | Rollback, page |
| DB unreachable | Connection errors for 1 min | Failover to replica |
| Memory OOM | Host memory > 95% for 5 min | Restart service, scale |
| Disk full | Disk usage > 90% | Expand volume immediately |
| Payment webhook failing | 0 events processed in 15 min | Check Stripe → alert |

### P1 — High (page, 15 min SLA)
| Alert | Condition |
|-------|-----------|
| API p99 latency > 5s for 5 min | |
| Error rate > 5% for 5 min | |
| LLM call failure rate > 20% | |
| Job queue depth > 1000 for 10 min | |

### P2 — Medium (Slack only)
| Alert | Condition |
|-------|-----------|
| CPU > 80% for 15 min | |
| API p95 latency > 2s | |
| Disk usage > 75% | |
| Certificate expiry < 14 days | |

### P3 — Low (daily digest)
| Alert | Condition |
|-------|-----------|
| Unused index detected | weekly DB analysis |
| Token budget > 80% consumed | |
| Backup older than 24h | |

---

## 4. Log Centralization

### Log pipeline
```
App (structured JSON logs) → Promtail/Fluent Bit → Loki → Grafana
```

### Log format (all services)
```json
{
  "timestamp": "2026-06-18T00:00:00.000Z",
  "level": "info|warn|error",
  "service": "simplicio-runtime|api|worker",
  "request_id": "uuid",
  "user_id": "uuid|null",
  "message": "...",
  "fields": {}
}
```

### Retention (matches §2 of LEGAL_COMPLIANCE.md)
- Error logs: 90 days.
- Access logs: 30 days.
- Audit logs (security events): 1 year.

### Log sources
| Source | Format | Collection |
|--------|--------|------------|
| Simplicio runtime | JSON (tracing-subscriber) | Promtail |
| Caddy/nginx | Combined log | Promtail |
| Postgres | CSV log | Promtail |
| CI/CD | GitHub Actions logs | Exported to S3 |

---

## 5. Uptime Monitoring

### External monitors (Better Uptime or UptimeRobot)
| Check | URL | Interval | Alert if |
|-------|-----|----------|---------|
| Homepage | `https://simplicio.ai` | 1 min | HTTP != 200 |
| API health | `https://api.simplicio.ai/health` | 1 min | HTTP != 200 |
| Dashboard | `https://simplicio.ai/dashboard` | 5 min | HTTP != 200 |
| Checkout page | `https://simplicio.ai/pricing` | 5 min | HTTP != 200 |

### Health endpoint
`GET /health` → `200 OK`
```json
{ "status": "ok", "version": "1.1.0", "db": "ok", "cache": "ok" }
```
Returns `503` with `{ "status": "degraded", "component": "db" }` on partial failure.

### SLA targets
- API availability: 99.9% monthly (< 44 min downtime/month).
- Dashboard availability: 99.5%.
- Scheduled maintenance window: Sundays 02:00–04:00 UTC.

---

## 6. Infrastructure Requirements

### Production topology
```
[Cloudflare CDN + DDoS] → [Caddy reverse proxy] → [Simplicio API (2× instances)]
                                                 → [Postgres (primary + 1 replica)]
                                                 → [Redis (sessions + job queue)]
                                                 → [Object storage (S3-compatible)]
```

### Minimum specs (initial)
| Component | Spec | Count |
|-----------|------|-------|
| API server | 4 vCPU, 8 GB RAM, 50 GB NVMe | 2 (active-active) |
| Postgres primary | 4 vCPU, 16 GB RAM, 500 GB SSD | 1 |
| Postgres replica | 4 vCPU, 16 GB RAM, 500 GB SSD | 1 |
| Redis | 2 vCPU, 4 GB RAM | 1 |
| Object storage | S3-compatible (Hetzner/Backblaze) | — |
| Monitoring stack | 2 vCPU, 4 GB RAM | 1 |

### Backup policy
- Postgres: continuous WAL archiving to S3 + daily base backups, 30-day retention.
- Redis: daily RDB snapshot to S3, 7-day retention.
- Object storage: cross-region replication.

### Network security
- All inter-service traffic via private VLAN (no public IPs on DB/Redis).
- API servers accept inbound only from Cloudflare IPs (maintained via IP list).
- SSH access via Tailscale (no direct 22/tcp open to internet).
- Secrets managed via Vault or environment injection from CI (no secrets in code).

### Deployment
- CI: GitHub Actions (ubuntu runners, main branch only','docs/roadmap/OPERATIONS_RUNBOOK.md','fd3bac4495787079e1d80a30c4bb57f1b52af732fb5143f79cb2c12c4ee05b74','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/PERFORMANCE_SLAS.md','project_doc','doc://simplicio-runtime/docs/roadmap/PERFORMANCE_SLAS.md','doc: Performance SLAs','# Performance SLAs

## Overview

Latency targets, token budgets, resource limits, and benchmark matrix for the
Simplicio runtime across tiers and deployment contexts.

---

## 1. Latency Targets

### HTTP API (web product)
| Endpoint category | p50 | p95 | p99 | Max |
|-------------------|-----|-----|-----|-----|
| Health / static | 5 ms | 15 ms | 30 ms | 100 ms |
| Auth (login/me) | 30 ms | 100 ms | 200 ms | 500 ms |
| Billing read | 50 ms | 150 ms | 300 ms | 1 s |
| Dashboard / reports | 200 ms | 800 ms | 2 s | 5 s |
| Export (small < 1 MB) | 500 ms | 2 s | 5 s | 10 s |

### Runtime commands (CLI / API)
| Command | p50 | p95 | p99 | Notes |
|---------|-----|-----|-----|-------|
| `simplicio map` | 50 ms | 200 ms | 500 ms | Repo < 50k LOC |
| `simplicio memory` | 20 ms | 80 ms | 200 ms | FTS + vector |
| `simplicio edit` (mechanical) | 10 ms | 30 ms | 80 ms | Zero LLM tokens |
| `simplicio validate` | 100 ms | 400 ms | 1 s | Per file |
| `simplicio gate classify` | 5 ms | 20 ms | 50 ms | Rule-based |
| `simplicio deliver check` | 200 ms | 600 ms | 1.5 s | |

### LLM inference (Runtime, Qwen3.5-4B Q4_K_M, one resident slot)
| Metric | Target |
|--------|--------|
| Time to first token (TTFT) | < 200 ms |
| Tokens/second (generation) | > 25 tok/s on M1 / > 15 tok/s on x86 |
| TTFT after prewarm (REPL) | < 50 ms (KV cache hit) |

### LLM inference (remote provider)
| Metric | Target |
|--------|--------|
| TTFT | < 1 s (provider SLA dependent) |
| End-to-end (1k token response) | < 10 s |

---

## 2. Token Budgets

### Per-turn budget (CLI/chat)
| Tier | Input tokens | Output tokens | Notes |
|------|-------------|---------------|-------|
| Free | 4,000 | 1,000 | |
| Pro | 32,000 | 8,000 | |
| Enterprise | 128,000 | 32,000 | Configurable |
| Internal (dev) | 200,000 | 50,000 | |

### Per-session budget (rolling 24h)
| Tier | Total tokens |
|------|-------------|
| Free | 50,000 |
| Pro | 1,000,000 |
| Enterprise | Unlimited (fair use) |

### Simplicio efficiency budget (standing rule)
Every turn must emit the token-savings line (CLAUDE.md):
```
Simplicio: ~<spent> tokens spent · without Simplicio ~<baseline> · saved ~<saved> (<pct>%)
```
Target: **> 60% savings** on routine file-reading + editing turns via `map` + `edit`.

### Token budget enforcement
- Checked pre-flight before LLM call: if `remaining < request_tokens` → error 429.
- Streaming: kill stream if output exceeds budget mid-generation.
- Budget resets at UTC midnight (free/pro) or month start (enterprise).

---

## 3. Resource Limits

### Runtime process limits (production)
| Resource | `normal` tier | `full` tier | `low` tier |
|----------|--------------|------------|------------|
| Logical agents | 5,000 | 10,000 | 1,000 |
| Active agents | 128 | 256 | 64 |
| Agent memory (RAM) | 512 MB | 2 GB | 128 MB |
| CPU utilisation cap | 75% | 90% | 60% |
| Tick batch size | 8 | 16 | 4 |
| LLM context window | 32k tokens | 128k tokens | 8k tokens |
| Max concurrent LLM calls | 8 | 32 | 4 |

### Job queue limits
| Limit | Value |
|-------|-------|
| Max queued jobs per user | 20 |
| Max job execution time | 5 min (free), 30 min (pro), 120 min (enterprise) |
| Max job output size | 10 MB |
| Max concurrent jobs per org | 10 (pro), 100 (enterprise) |

### API rate limits
| Tier | Requests/min | Burst | Webhooks/min |
|------|-------------|-------|-------------|
| Free | 60 | 10 | 10 |
| Pro | 600 | 60 | 100 |
| Enterprise | 6,000 | 600 | 1,000 |

### Storage limits per user
| Resource | Free | Pro | Enterprise |
|----------|------|-----|------------|
| Memory items | 1,000 | 100,000 | Unlimited |
| File uploads | 100 MB | 10 GB | Custom |
| Report history | 7 days | 1 year | Custom |

---

## 4. Benchmark Matrix

### Benchmark suite (`simplicio benchmark`)
Canonical benchmarks run on every release. Results tracked in `docs/benchmarks/`.

#### Coding tasks (primary quality metric — "better than Hermes")
| Benchmark | Metric | Simplicio target | Hermes baseline |
|-----------|--------|-----------------|-----------------|
| make-test-pass (simple) | pass rate | > 90% | baseline |
| make-test-pass (hard) | pass rate | > 70% | baseline |
| multi-file refactor | correctness | > 85% | baseline |
| token efficiency | tokens/task | < 50% of Hermes | 1× |
| latency (task completion) | p50 | < 60s | baseline |

#### Runtime performance
| Benchmark | Input | Target |
|-----------|-------|--------|
| `simplicio map` | 10k file repo | < 500 ms |
| `simplicio map` | 100k file repo | < 5 s |
| `simplicio memory search` | 876k items | < 100 ms (FTS), < 200 ms (vector) |
| `simplicio edit` (100 ops) | — | < 1 s total |
| Agent fan-out (64 agents) | — | < 2 s spawn time |
| Agent fan-out (600 agents) | — | < 10 s spawn time |

#### Throughput
| Scenario | Target |
|----------|--------|
| Concurrent API users | 1,000 (pro tier) |
| Requests/sec sustained | 500 |
| Token throughput (local) | 5,000 tok/s aggregate (64 agents) |

### Benchmark execution
```bash
# Run full suite
simplicio benchmark --suite all --output docs/benchmarks/$(date +%Y-%m-%d).json

# Compare against baseline
simplicio benchmark --compare docs/benchmarks/baseline.json
```

### Regression gate
CI fails if any benchmark regresses > 10% vs the baseline stored in
`docs/benchmarks/baseline.json`. The gate runs on `main` pushes only
(not PRs, to avoid flakiness on shared runners).

### Three-agent benchmark (Simplicio × Hermes × OpenClaw)
Per CLAUDE.md instructions, fair runs use the same model (OpenRouter DeepSeek v4 Flash).
Results logged to `docs/benchmarks/three-agent/`.
| Dimension | Simplicio | Hermes | OpenClaw |
|-----------|-----------|--------|----------|
| pass@1 (make-test-pass) | TBD | baseline | baseline |
| tokens/task | TBD | 1× | 1× |
| wall-clock latency | TBD | 1× | 1× |
| token savings (vs raw) | TBD | ~0% | ~0% |','docs/roadmap/PERFORMANCE_SLAS.md','c59f94400863c7b3a1801cc9ea441f30ec46b7f4e2029ec58bb1c44c24cc27a5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/PERSONAL_ASSISTANT_SPEC.md','project_doc','doc://simplicio-runtime/docs/roadmap/PERSONAL_ASSISTANT_SPEC.md','doc: Personal Assistant Specification','# Personal Assistant Specification

## Overview

The Personal Assistant layer makes Simplicio proactive and ambient: voice commands,
computer-use agent, a proactivity engine that surfaces insights without being asked,
a routine engine for daily automation, and a long-term memory system that accumulates
personal context across all interactions.

Target milestones: v0.2 (voice + computer use), v0.3 (proactivity + routine + long-term memory).

---

## 1. Voice Commands (#2145, #2146)

### Architecture
```
Microphone input
  → Wake-word detector (Picovoice Porcupine or Whisper.cpp local)
  → Speech-to-text (Whisper.cpp, runs locally on CPU/GPU)
  → Intent classifier (fast local model, < 50 ms)
  → Simplicio command dispatcher
  → Response generator (TTS via Piper or system TTS)
  → Speaker output
```

### Wake Word
- Default: "Hey Simplicio"
- Custom wake word: `simplicio voice set-wake "<phrase>"`
- Porcupine model file stored at `.simplicio-loop/voice/wake.ppn`.

### Intent Classification
Intent mapped to command via a small lookup table + regex, avoiding LLM for
mechanical commands. LLM only invoked for open-ended requests.

```
"What''s on my calendar today"  → simplicio life family event list --today
"Remind me to call mom at 5"   → simplicio life family reminders add ...
"Search for Rust jobs remote"  → simplicio life job search --remote --skills rust
"Read my messages"             → simplicio notify digest
"Start a coding session"       → simplicio runtime start
```

### TTS Response
- Short responses (< 80 chars): spoken directly.
- Long responses: summary spoken; full output written to REPL / notification.
- Voice: Piper neural TTS, model `en_US-lessac-medium` (offline, 60 MB).

### Commands
```
simplicio voice start          # start wake-word listener daemon
simplicio voice stop
simplicio voice status
simplicio voice set-wake "Hey Simplicio"
simplicio voice calibrate      # background noise calibration
```

### Privacy
- All STT runs locally (Whisper.cpp); no audio leaves the device.
- Wake-word detection is CPU-only, always-on; audio buffer discarded if no wake.

---

## 2. Computer Use Agent (#2197, #2198)

### Architecture
The computer-use agent wraps the existing `tools_browser` + `macos_computer_use`
capabilities into a governed agent with a planning layer.

```
User command: "Book the cheapest flight to London in July"
  → Planner: decompose into steps (open browser, search, compare, select, confirm)
  → Each step: action_gate classify → approve/ask/block
  → Execute: screenshot → identify target → click/type
  → After each step: verify state (screenshot diff)
  → Present result to user; await confirmation before form submission
```

### Step Types
| Step | Gate level |
|---|---|
| Navigate to URL | safe |
| Read page / screenshot | safe |
| Click (navigation, search) | auto |
| Type in form field | auto |
| Submit form (no payment) | ask |
| Payment / checkout | block (present to user) |
| Download file | ask |

### Capabilities
- Chromium control (via CDP / Playwright).
- macOS native GUI (macOS only; via Accessibility API).
- Web scraping with anti-bot awareness (randomized timing, human-like mouse paths).
- Session persistence (cookies saved to `.simplicio-loop/computer_use/sessions/`).
- Task recording: all actions logged to HBP chain for audit.

### Commands
```
simplicio computer-use run "Open Notion and create a task called X"
simplicio computer-use record --name "daily-standup"   # record a macro
simplicio computer-use play daily-standup
simplicio computer-use sessions list
```

---

## 3. Proactivity Engine (#2199, #2221)

### Model
The proactivity engine observes context signals and surfaces actionable insights
without being asked. It runs as a background daemon with configurable check
intervals.

### Signal Sources
| Source | Check interval | Examples |
|---|---|---|
| Calendar | 5 min | Meeting in 15 min: prepare agenda |
| Email (local IMAP) | 10 min | Urgent email from boss |
| Job pipeline | 1 h | Interview tomorrow: send reminder |
| Health trends | 24 h | Sleep < 6 h for 3 days: flag |
| Price tracker | 6 h | Target price reached |
| News (RSS) | 1 h | Relevant to user''s interest tags |
| CI/Build status | 2 min | Build failed on main |
| Git activity | 5 min | PR review requested |

### Proactivity Levels
```toml
[proactivity]
level = "medium"  # off | low | medium | high
```
- `off`: no proactive interrupts.
- `low`: only high-priority signals (meeting in 5 min, broken build).
- `medium`: includes daily digests and trend alerts.
- `high`: includes news, price changes, social mentions.

### Insight Format
```
[PROACTIVE] Meeting "Design Review" in 12 min.
  Participants: Alice, Bob, Carol.
  Last meeting notes: docs/meetings/2026-06-10.md
  → simplicio computer-use run "Open meeting notes"
  → Snooze 5 min  → Dismiss
```

### Gate Policy
Proactive suggestions are always read-only. Actions triggered by a suggestion
go through the normal Action Gate.

---

## 4. Routine Engine (#2136)

### Model
Routines are named sequences of Simplicio commands with scheduling, conditions,
and inter-step dependencies.

```yaml
# .simplicio-loop/routines/morning.yaml
name: morning
schedule: "07:00 Mon-Fri"
steps:
  - id: digest
    cmd: simplicio notify digest
  - id: calendar
    cmd: simplicio life family event list --today
    depends_on: []
  - id: prices
    cmd: simplicio life ecom prices
    depends_on: []
  - id: standup
    cmd: simplicio engineering standup
    condition: "git status --porcelain | grep -q ."
```

### Commands
```
simplicio routine add morning --from morning.yaml
simplicio routine list
simplicio routine run morning
simplicio routine enable morning
simplicio routine disable morning
simplicio routine delete morning
```

### Scheduler
- Integrates with OS scheduler (launchd on macOS, systemd on Linux, Task Scheduler on Windows).
- Fallback: built-in Tokio scheduler when OS integration unavailable.
- Run log: `.simplicio-loop/routines/run_log.jsonl`.

---

## 5. Long-Term Me','docs/roadmap/PERSONAL_ASSISTANT_SPEC.md','ecee7df52737575df85d16208050e66a9fee5f8cbef5d135cf332c21831a8aa6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/PREDICTIVE_PREWARM_SPEC.md','project_doc','doc://simplicio-runtime/docs/roadmap/PREDICTIVE_PREWARM_SPEC.md','doc: Predictive Prewarm Spec — Pattern-Based Pre-Execution','# Predictive Prewarm Spec — Pattern-Based Pre-Execution

## Overview

Predictive Prewarm observes usage patterns and pre-executes cheap deterministic
operations (map, memory recall, skill load) before the user''s next turn begins,
so the results are ready instantly when the LLM needs them.
The goal is to eliminate the latency of the "orient" step on repeated patterns.

Target milestone: v0.4–v0.5.

## Motivation

The canonical per-turn flow is:
1. `simplicio map` (orient) — 200–800 ms.
2. `simplicio memory` (recall) — 50–300 ms.
3. LLM reasoning — variable.
4. `simplicio edit` (write) — ~50 ms.

Steps 1 and 2 are deterministic and cheap. If patterns predict that the next
turn will need them, they can be pre-executed while the user is still typing,
dropping perceived latency to near zero.

## Pattern Model

### Turn-transition patterns

```rust
pub struct TurnPattern {
    /// hash of the command/intent sequence (last 3 turns)
    pub context_hash: u64,
    /// predicted next operations
    pub predicted_ops: Vec<PrewarmOp>,
    /// confidence (0.0–1.0)
    pub confidence: f32,
    /// observed count
    pub count: u32,
}

pub enum PrewarmOp {
    Map { repo: PathBuf },
    MemoryRecall { query: String },
    SkillLoad { skill_id: String },
    FileRead { path: PathBuf },
}
```

### Pattern storage

Stored in `.simplicio-loop/prewarm/patterns.sqlite` (FTS + frequency table).
Updated after every turn with the actual ops consumed.

### Confidence threshold

A prewarm is triggered only when `confidence >= 0.75` and `count >= 3`.
Below threshold, no prewarm (avoid wasted work on cold patterns).

## Pre-Execution Engine

### Architecture

```
┌─────────────────────────────────────────────┐
│  PrewarmScheduler (async task, always on)   │
│                                             │
│  on turn_end(turn_ctx):                     │
│    patterns = pattern_store.predict(ctx)    │
│    for op in patterns.high_confidence():    │
│      spawn prewarm_task(op)                 │
│                                             │
│  prewarm_task(op):                          │
│    result = execute(op)                     │
│    prewarm_cache.insert(op.key(), result)   │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  Per-turn flow (modified)                   │
│                                             │
│  on turn_start(intent):                     │
│    if prewarm_cache.hit(map_key):           │
│      map_result = cache.get()  // instant  │
│    else:                                    │
│      map_result = simplicio_map()  // live │
└─────────────────────────────────────────────┘
```

### Cache structure

```rust
pub struct PrewarmCache {
    entries: HashMap<PrewarmKey, PrewarmEntry>,
}

pub struct PrewarmEntry {
    pub result: PrewarmResult,
    pub produced_at: Instant,
    pub ttl: Duration,  // default: 30 s for map, 120 s for memory
}
```

TTL is short because file system and memory state can change between turns.
Stale entries are evicted before use; on eviction, the live path runs.

## Patterns to Prewarm

### Pattern 1: Sequential coding session

Trigger: last 3 turns all included `simplicio map`.
Prewarm: `map --repo . --for-llm markdown` immediately after each turn.

### Pattern 2: Memory-heavy recall

Trigger: last 2 turns both included `simplicio memory "<topic>"` with same topic prefix.
Prewarm: `memory "<topic>" --repo . --json --limit 20`.

### Pattern 3: Skill reuse

Trigger: same skill loaded in last 3 turns.
Prewarm: load skill binary/script into memory (keep warm).

### Pattern 4: File hotspot

Trigger: same file read 3+ times in last 5 turns.
Prewarm: read file into a hot-file cache (64 KB max per file, 20 file slots).

## Streaming REPL Integration

The `PrewarmScheduler` is initialized at REPL boot alongside the existing
prewarm hook (`src/stream_scrubber.rs`). It runs as a background Tokio task,
consuming < 5% CPU when idle.

REPL output:

```
[prewarm] map ready (32 ms ahead)
[prewarm] memory:coding-loop ready (18 ms ahead)
```

These lines are shown only with `--verbose` or `/debug prewarm`.

## Controls

| Command | Effect |
|---|---|
| `simplicio prewarm status` | show cache contents + pattern table |
| `simplicio prewarm flush` | clear cache and pattern history |
| `simplicio prewarm disable` | disable scheduler for session |
| `SIMPLICIO_PREWARM=0` | disable globally |

## Implementation Plan

### Phase 1 — Pattern tracking (v0.4-alpha)

- `src/prewarm/pattern_store.rs` — SQLite-backed pattern recorder.
- Record actual ops consumed per turn (map, memory, skill, file reads).
- Expose `simplicio prewarm status` showing raw pattern table.

### Phase 2 — Pre-execution (v0.4-beta)

- `src/prewarm/scheduler.rs` — background Tokio task.
- `src/prewarm/cache.rs` — TTL-aware in-memory cache.
- Hook into per-turn flow: check cache before running live ops.

### Phase 3 — Tuning + UI (v0.4)

- Expose cache hit rate in ghost report (`prewarm_hits`, `latency_saved_ms`).
- Dashboard widget: prewarm hit rate over rolling 24 h.
- Auto-tune TTLs based on observed staleness rate.

## Schema: `simplicio.prewarm-event/v1`

```json
{
  "schema": "simplicio.prewarm-event/v1",
  "session_id": "...",
  "turn": 4,
  "kind": "hit",
  "op": { "type": "map", "repo": "." },
  "latency_saved_ms": 340,
  "produced_at_ms_ago": 280
}
```

## Constraints

- Prewarm tasks are **read-only** — they never mutate state.
- Prewarm is **cancelled** immediately if the action gate classifies the
  incoming intent as `unsafe` (no speculative execution ahead of a gate check).
- Maximum concurrent prewarm tasks: 4 (bounded semaphore).
- Memory budget: 32 MB for prewarm cache (configurable via
  `SIMPLICIO_PREWARM_CACHE_MB`).','docs/roadmap/PREDICTIVE_PREWARM_SPEC.md','3f421c1722f59d408015c6a7bd7f61195a6f7884c50d210b8540c1268082bcb6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/QA_STRATEGY.md','project_doc','doc://simplicio-runtime/docs/roadmap/QA_STRATEGY.md','doc: QA Strategy — Simplicio Runtime','# QA Strategy — Simplicio Runtime

## Overview

This document defines the quality assurance strategy for simplicio-runtime,
covering CI matrix, integration tests, cross-platform compatibility,
load tests, and security tests. Target milestones: v0.4–v0.5.

## CI Matrix

### Platforms

| OS | Architecture | Rust toolchain | Runner |
|---|---|---|---|
| Ubuntu 22.04 | x86_64 | stable | GitHub Actions (ubuntu-latest) |
| macOS 13 | arm64 (Apple Silicon) | stable | GitHub Actions (macos-latest) |
| Windows 11 | x86_64 | stable-msvc | GitHub Actions (windows-latest) |

### Trigger policy

- **PRs:** Ubuntu only (cost control; ~2× minutes).
- **Push to main:** all three platforms.
- **Nightly:** full matrix + load tests + security scan.

### Gate criteria

A build is green when:
1. `cargo build --release --locked` exits 0 on all three platforms.
2. `cargo test` passes (unit + integration).
3. `cargo clippy --release -- -D warnings` is clean (zero new warnings).
4. Binary size regression < 10% vs previous release.

## Integration Tests

### Test categories

| Category | Tool | Location |
|---|---|---|
| CLI smoke | `assert_cmd` | `tests/integration/cli/` |
| Action gate | custom harness | `tests/integration/gate/` |
| Memory recall | SQLite fixture | `tests/integration/memory/` |
| Edit pipeline | temp git repo | `tests/integration/edit/` |
| Delivery gates | fixture tasks | `tests/integration/delivery/` |
| Video pipeline | mock renderer | `tests/integration/video/` |

### Contract tests

Every public Simplicio schema (`simplicio.reasoning-action/v1`,
`simplicio.delivery-certificate/v1`, etc.) has a schema-validation test that
runs against a golden fixture. Schema changes require a new version suffix.

### Coverage targets

- Unit tests: ≥ 70% line coverage (`cargo-llvm-cov`).
- Integration tests: every CLI subcommand covered by at least one happy-path + one error-path case.

## Cross-Platform Compatibility

### Filesystem

- All path construction uses `std::path::Path` / `PathBuf` — no hardcoded `/` or `\`.
- Temp files via `tempfile` crate.
- Config root: `dirs::config_dir()` / `dirs::data_dir()`.

### Line endings

- `.gitattributes` enforces `* text=auto` and `*.sh text eol=lf`.
- Shell scripts tested with `sh -n` before merge.

### Binary distribution

- Linux: musl static build via `cargo-zigbuild` (no glibc dependency).
- macOS: universal binary (`x86_64-apple-darwin` + `aarch64-apple-darwin`) via `lipo`.
- Windows: MSVC toolchain; no Cygwin/MinGW dependency at runtime.

### Feature parity matrix (per platform)

| Feature | Linux | macOS | Windows |
|---|---|---|---|
| TUI (ratatui) | yes | yes | yes |
| In-process LLM | yes | yes (Metal) | yes |
| Dashboard (:9119) | yes | yes | yes |
| Voice (TTS/STT) | yes | yes | partial |
| Computer use | — | yes | yes |

## Load Tests

### Scenarios

| Scenario | Agents | Duration | Pass criteria |
|---|---|---|---|
| Baseline chat throughput | 1 | 60 s | p99 latency < 2 s |
| Normal tier fan-out | 128 | 120 s | no OOM, no deadlock |
| Full tier fan-out | 256 | 120 s | no OOM, no deadlock |
| 600-agent burst | 600 | 300 s | completes, evidence chain intact |
| HBP chain append | — | 60 s, 10k ops | p99 append < 50 ms |

### Tool

`cargo bench` (criterion) for microbenchmarks; custom async harness under
`tests/load/` for agent fan-out scenarios.

### Regression gate

A load test run is tagged against the release SHA. If p99 latency increases
> 20% vs the previous tagged run, the CI job is marked failing.

## Security Tests

### Static analysis

- `cargo audit` on every PR (checks advisory database).
- `cargo deny` for license policy enforcement.

### Fuzzing

- `cargo-fuzz` targets for: action gate classifier, edit plan parser, HBP chain verifier.
- Fuzz corpus stored under `fuzz/corpus/`.
- Nightly CI runs each target for 300 s.

### Secret scanning

- `trufflehog` pre-commit hook (local) and CI step.
- Policy: no API keys, tokens, or model identifiers in any committed artifact.

### Dependency supply-chain

- Dependabot PRs auto-opened for CVEs with CVSS ≥ 7.
- Lock file (`Cargo.lock`) committed and verified with `--locked`.

### Penetration targets (manual, per release)

- Action gate bypass attempts (prompt injection via chat).
- HBP chain tampering (hash collision / replay).
- Dashboard (:9119) unauthenticated access.

## Ownership

| Area | DRI |
|---|---|
| CI matrix config | release engineer |
| Integration test harness | runtime team |
| Load scenarios | performance team |
| Security scans | security team |
| Cross-platform compat | all (platform owners) |','docs/roadmap/QA_STRATEGY.md','c134f513cbec00ae8cb33d460efbca8ca4157e8bb918a74b0d1ddea573a2fb3a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/RELEASE_PIPELINE.md','project_doc','doc://simplicio-runtime/docs/roadmap/RELEASE_PIPELINE.md','doc: Release Pipeline — Simplicio Runtime','# Release Pipeline — Simplicio Runtime

## Overview

This document describes the end-to-end release pipeline for simplicio-runtime:
binary build, cross-compilation, PyPI wheel publishing, desktop package
generation, website sync, and private-repo release flow.
Target milestones: v0.4–v0.5.

## Versioning

Single source of truth: `scripts/bump-version.sh <version>`.
Updates: `Cargo.toml`, `pyproject.toml`, `Cargo.lock`.
Never hand-edit individual files.

Version scheme: `MAJOR.MINOR.PATCH` (SemVer).

## Binary Build System

### Targets

| Target triple | Platform | Method |
|---|---|---|
| `x86_64-unknown-linux-musl` | Linux x64 | `cargo-zigbuild` (static musl) |
| `aarch64-unknown-linux-musl` | Linux arm64 | `cargo-zigbuild` (static musl) |
| `x86_64-apple-darwin` | macOS x64 | native CI runner |
| `aarch64-apple-darwin` | macOS arm64 (M-series) | native CI runner |
| `x86_64-pc-windows-msvc` | Windows x64 | native CI runner |

### macOS Universal Binary

```
lipo -create \
  target/x86_64-apple-darwin/release/simplicio \
  target/aarch64-apple-darwin/release/simplicio \
  -output dist/simplicio-macos-universal
```

### Cross-Compile (Linux from Windows)

`scripts/build-linux-cross.sh` uses `zig` + `cargo-zigbuild`.
Reduced feature set (`--no-default-features --features tui`) — no in-process-llm.
Full feature build requires a Linux or macOS runner.

### Build flags (release profile)

```toml
[profile.release]
strip = true
lto = true
panic = "abort"
codegen-units = 1
opt-level = 3
```

### Artifact naming

```
simplicio-<version>-<os>-<arch>[.exe]
```

Examples:
- `simplicio-1.2.0-linux-x64`
- `simplicio-1.2.0-macos-universal`
- `simplicio-1.2.0-windows-x64.exe`

## PyPI Publishing

### Package: `simplicio-installer`

PyPI publishes only the public installer wrapper from `packaging/pypi`. The
private runtime checkout is not a PyPI package and must never be uploaded as an
sdist or root runtime wheel.

### Workflow

1. `scripts/bump-version.sh <version>`
2. `cd packaging/pypi`
3. `python3 -m build --wheel`
4. `twine upload --skip-existing dist/*.whl`
5. Requires `PYPI_API_TOKEN` secret (rotate after any leak).

### Extras

- `simplicio-cli[local]` — pulls `llama-cpp-python`.
- `simplicio-cli[bench]` — benchmark dependencies.

### Install policy (consumers)

Always latest: `pip install --upgrade --upgrade-strategy eager simplicio-cli`.

## Desktop Packages

### macOS (.dmg)

- Tool: `create-dmg` or `hdiutil`.
- Contents: `Simplicio.app` bundle (signed + notarized).
- Code signing: `codesign --deep --sign "Developer ID Application: ..."`.
- Notarization: `xcrun notarytool submit`.

### Windows (.exe installer)

- Tool: `NSIS` or `WiX Toolset`.
- Includes: `simplicio.exe`, runtime DLLs (if any), Start Menu shortcut.
- Code signing: `signtool sign /tr http://timestamp.digicert.com ...`.

### Linux (.AppImage)

- Tool: `appimagetool`.
- Base: musl static binary (no system lib deps).
- Desktop entry: `simplicio.desktop`.

### GitHub Release asset upload

```bash
gh release create v<version> \
  dist/simplicio-<version>-linux-x64 \
  dist/simplicio-<version>-macos-universal \
  dist/simplicio-<version>-windows-x64.exe \
  --title "v<version>" \
  --notes-file CHANGELOG.md
```

## Website Sync

### Site source: `site/`

Static HTML/CSS/JS. Served from `public_html/simplicio` on the FTP host.

### Sync script

`scripts/deploy-site.sh`:
1. Substitutes `{{VERSION}}` with the release version in `site/index.html`.
2. Strips CRLF from all `.sh` files.
3. FTP upload via `curl --ftp-create-dirs -T`.

### Installer script

`site/install.sh` is the `curl | sh` installer.
Tested with `sh -n site/install.sh` before every release.
Version string is dynamic (fetched from GitHub releases API, not hardcoded).

## Private Repo Release Flow

### Repos

- `simplicio-runtime` (private, source) — tag + GitHub Release with compiled binaries.
- `simplicio` (public) — mirror of compiled binaries only; no source.

### Release checklist

1. All CI checks green on `main`.
2. `scripts/bump-version.sh <version>` committed and pushed.
3. Build all targets (CI matrix completes).
4. `gh release create` on `simplicio-runtime` (private, with source tarball excluded).
5. Upload binaries to `simplicio` (public) as release assets.
6. `scripts/deploy-site.sh` — update public website.
7. PyPI wheel publish.
8. Announce in project channels.

### Rollback

- Yank PyPI version: `pip install pip-yank && pip-yank simplicio-cli==<version>`.
- GitHub: delete release assets, re-upload patched binaries.
- Site: redeploy previous installer script.

## Secrets Management

| Secret | Used by | Rotate on |
|---|---|---|
| `PYPI_API_TOKEN` | twine upload for `simplicio-installer` wheel | any leak or annually |
| Code signing cert | codesign / signtool | annually or on revocation |
| FTP credentials | deploy-site.sh | any leak |
| GitHub token | gh release | standard rotation |

Never embed secrets in binaries or commit history.','docs/roadmap/RELEASE_PIPELINE.md','cc9909111ae0769b0fdbfe6e0501a59b251e9a9ff7dbec151f244c41fc0ad3ec','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/SDK_PLUGIN_SYSTEM.md','project_doc','doc://simplicio-runtime/docs/roadmap/SDK_PLUGIN_SYSTEM.md','doc: SDK & Plugin System Spec','# SDK & Plugin System Spec

## Overview

Public REST API, Python SDK, and plugin marketplace architecture enabling third-party
integrations with the Simplicio runtime.

---

## 1. REST API Spec

### Base URL
`https://api.simplicio.ai/v1`

### Authentication
- Bearer token: `Authorization: Bearer <api_key>`.
- API keys managed at `GET/POST/DELETE /me/api-keys`.
- Scopes: `read`, `write`, `admin`, `billing`.
- Rate limits: 60 req/min (free), 600 req/min (pro), unlimited (enterprise).

### Core endpoints

#### Runtime
| Method | Path | Description |
|--------|------|-------------|
| POST | `/run` | Execute a Simplicio command |
| POST | `/chat` | Send a chat message, stream response |
| GET | `/agents` | List active agents |
| GET | `/agents/{id}` | Agent status |
| DELETE | `/agents/{id}` | Cancel agent |

##### POST /run
```json
Request:
{
  "command": "map|edit|validate|deliver|gate|memory|reason",
  "args": {},
  "options": { "timeout_ms": 30000, "stream": false }
}

Response:
{
  "job_id": "uuid",
  "status": "queued|running|done|error",
  "result": {},
  "tokens_spent": 120,
  "duration_ms": 340
}
```

##### POST /chat (streaming)
```
Content-Type: text/event-stream

data: {"type":"text","delta":"Hello"}
data: {"type":"tool_use","tool":"simplicio_edit","input":{}}
data: {"type":"tool_result","output":{}}
data: {"type":"done","tokens":{"input":200,"output":150}}
```

#### Memory
| Method | Path | Description |
|--------|------|-------------|
| GET | `/memory` | Query memory (FTS + vector) |
| POST | `/memory` | Insert memory item |
| DELETE | `/memory/{id}` | Delete item |

#### Tasks
| Method | Path | Description |
|--------|------|-------------|
| GET | `/tasks` | List tasks |
| POST | `/tasks` | Create task |
| GET | `/tasks/{id}` | Task detail |
| PATCH | `/tasks/{id}` | Update task |
| DELETE | `/tasks/{id}` | Cancel task |

#### Plugins
| Method | Path | Description |
|--------|------|-------------|
| GET | `/plugins` | List installed plugins |
| POST | `/plugins` | Install plugin from marketplace |
| DELETE | `/plugins/{id}` | Uninstall plugin |
| POST | `/plugins/{id}/invoke` | Invoke plugin tool |

### OpenAPI spec
Full spec maintained at `docs/api/openapi.yaml` (auto-generated from Rust code via `utoipa`).

---

## 2. Python SDK Design

### Package
`pip install simplicio-sdk`

### Client
```python
from simplicio import Simplicio

client = Simplicio(api_key="sk_...", base_url="https://api.simplicio.ai/v1")

# Run a command
result = client.run("map", args={"repo": ".", "format": "markdown"})

# Chat (streaming)
for chunk in client.chat.stream("Refactor this function", context={"file": "src/main.rs"}):
    print(chunk.text, end="", flush=True)

# Memory
items = client.memory.search("action bridge implementation")
client.memory.insert(content="Decision: use tokio for async fabric", tags=["arch"])

# Tasks
task = client.tasks.create(title="Implement OAuth", body="...", milestone=15)
client.tasks.update(task.id, status="done")
```

### Async client
```python
import asyncio
from simplicio import AsyncSimplicio

async def main():
    async with AsyncSimplicio(api_key="sk_...") as client:
        async for chunk in client.chat.stream("Hello"):
            print(chunk.text, end="")

asyncio.run(main())
```

### Module structure
```
simplicio/
  __init__.py          — re-exports Simplicio, AsyncSimplicio
  _client.py           — HTTP client (httpx-based, sync + async)
  resources/
    chat.py            — ChatResource (stream, send)
    memory.py          — MemoryResource (search, insert, delete)
    tasks.py           — TasksResource (CRUD)
    agents.py          — AgentsResource (list, status, cancel)
    plugins.py         — PluginsResource (list, install, invoke)
    billing.py         — BillingResource (history, checkout)
  types/
    chat.py            — ChatChunk, ChatResponse
    memory.py          — MemoryItem
    task.py            — Task
  exceptions.py        — SimplicioError, AuthError, RateLimitError, APIError
  pagination.py        — SyncPage, AsyncPage
```

### Error handling
```python
from simplicio.exceptions import RateLimitError, APIError

try:
    result = client.run("map")
except RateLimitError as e:
    time.sleep(e.retry_after)
except APIError as e:
    print(e.status_code, e.message)
```

---

## 3. Plugin Marketplace Architecture

### Plugin definition
A Simplicio plugin is a manifest + tool implementations:

```toml
# plugin.toml
[plugin]
id = "com.example.my-plugin"
name = "My Plugin"
version = "1.0.0"
description = "Adds custom tools to Simplicio."
author = "Example Corp"
homepage = "https://example.com"
license = "MIT"

[plugin.tools]
[[plugin.tools.tool]]
name = "my_tool"
description = "Does something useful."
input_schema = "schemas/my_tool_input.json"
```

### Plugin types
| Type | Description |
|------|-------------|
| `tool` | Adds new tools callable in chat/agent context |
| `skill` | Adds reusable skill flows (`.skill` files) |
| `provider` | Adds a new LLM/TTS/STT/embedding provider |
| `action` | Adds action bridge handlers |

### Runtime plugin loading
```rust
// src/plugins.rs
pub struct Plugin {
    pub manifest: PluginManifest,
    pub tools: Vec<ToolDefinition>,
    pub wasm_module: Option<WasmModule>,  // sandboxed execution
}
fn load_plugin(path: &Path) -> Result<Plugin>
fn invoke_plugin_tool(plugin: &Plugin, tool: &str, input: Value) -> Result<Value>
```

Plugins run in **Wasmtime** sandbox (WASI, no network/fs by default; capabilities
granted via manifest `[permissions]` + user approval).

### Marketplace API
| Method | Path | Description |
|--------|------|-------------|
| GET | `/marketplace/plugins` | Search/list marketplace plugins |
| GET | `/marketplace/plugins/{id}` | Plugin detail + versions |
| GET | `/marketplace/plugins/{id}/versions/{v}` | Download manifest + WASM |
| POST | `/marketplace/plugins/{id}/reviews` | Submit review |

### Marketplace data model
```
marketplace_plugins (id TEXT PK, name TEXT, description TEXT, author_','docs/roadmap/SDK_PLUGIN_SYSTEM.md','02d234d59267ef00d8469b40c82671c3271a58bf3ede5e54e4d2288ec3e1a9e1','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/SITE_BACKEND_SPEC.md','project_doc','doc://simplicio-runtime/docs/roadmap/SITE_BACKEND_SPEC.md','doc: Site Backend Spec','# Site Backend Spec

## Overview

Backend services for the Simplicio web site and user-facing product: authentication,
payments, billing history, transactional email, and internationalisation.

---

## 1. Google OAuth Login

### Flow
1. User clicks "Sign in with Google" → redirect to Google OAuth 2.0 consent screen.
2. Google redirects back with `code`; backend exchanges for `access_token` + `id_token`.
3. Verify `id_token` signature (JWKS endpoint), extract `sub`, `email`, `name`, `picture`.
4. Upsert user record; create signed session JWT (HS256, 7-day expiry, refresh via sliding window).
5. Return `Set-Cookie: session=<jwt>; HttpOnly; Secure; SameSite=Lax`.

### Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/auth/google` | Redirect to Google consent |
| GET | `/auth/google/callback` | Handle code exchange |
| POST | `/auth/logout` | Invalidate session |
| GET | `/auth/me` | Return current user profile |

### Data model
```
users (id UUID PK, google_sub TEXT UNIQUE, email TEXT, name TEXT, avatar_url TEXT,
       created_at TIMESTAMPTZ, last_login_at TIMESTAMPTZ, plan TEXT DEFAULT ''free'')
sessions (id UUID PK, user_id UUID FK, token_hash TEXT, expires_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ, revoked BOOL DEFAULT false)
```

---

## 2. Stripe Checkout + Webhooks

### Plans
| Plan | Price | Stripe Price ID |
|------|-------|-----------------|
| Pro Monthly | USD 19/mo | price_pro_monthly |
| Pro Annual | USD 190/yr | price_pro_annual |
| Enterprise | Contact sales | — |

### Checkout flow
1. Authenticated user hits `POST /billing/checkout` with `{ plan: "pro_monthly" }`.
2. Backend creates Stripe `Checkout.Session` with `customer_email`, `success_url`,
   `cancel_url`, `metadata.user_id`.
3. Return `{ url }` to redirect the frontend.
4. On success Stripe fires `checkout.session.completed` webhook.

### Webhooks (endpoint: `POST /webhooks/stripe`)
| Event | Action |
|-------|--------|
| `checkout.session.completed` | Activate subscription, set `users.plan` |
| `customer.subscription.updated` | Sync plan/status |
| `customer.subscription.deleted` | Downgrade to free |
| `invoice.payment_failed` | Email dunning notice, flag account |

Security: verify `Stripe-Signature` header with `STRIPE_WEBHOOK_SECRET`.

### Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/billing/checkout` | Create Stripe checkout session |
| GET | `/billing/portal` | Redirect to Stripe Customer Portal |
| POST | `/webhooks/stripe` | Receive Stripe events |

---

## 3. Mercado Pago / PayPal Fallbacks

### Mercado Pago (LATAM)
- Integration: Checkout Pro (hosted) via SDK `mercadopago` Python/Rust.
- Preference creation: `POST /billing/checkout/mercadopago` → returns `init_point` URL.
- IPN webhook: `POST /webhooks/mercadopago` — verify `x-signature` header.
- On `payment.approved` → activate subscription same as Stripe flow.

### PayPal
- Integration: PayPal Orders API v2.
- `POST /billing/checkout/paypal` → create order, return `approve_url`.
- `POST /webhooks/paypal` — verify with PayPal webhook ID + cert.
- On `PAYMENT.CAPTURE.COMPLETED` → activate subscription.

### Provider routing
```
if user.country in LATAM_COUNTRIES → offer Mercado Pago first
elif user.currency == "BRL"       → offer Mercado Pago first
else                               → Stripe primary, PayPal secondary
```

---

## 4. Billing History

### Endpoint
`GET /billing/history` → paginated list of invoices/charges.

### Response schema
```json
{
  "invoices": [
    {
      "id": "inv_xxx",
      "provider": "stripe|mercadopago|paypal",
      "amount": 1900,
      "currency": "USD",
      "status": "paid|open|void",
      "period_start": "2026-01-01",
      "period_end": "2026-02-01",
      "pdf_url": "https://...",
      "created_at": "2026-01-01T00:00:00Z"
    }
  ],
  "next_cursor": "cursor_abc"
}
```

### Storage
```
invoices (id TEXT PK, user_id UUID FK, provider TEXT, external_id TEXT,
          amount_cents INT, currency TEXT, status TEXT,
          period_start DATE, period_end DATE, pdf_url TEXT,
          created_at TIMESTAMPTZ)
```

---

## 5. Transactional Email

### Provider
- Primary: **Resend** (resend.com) — REST API, SPF/DKIM auto-setup.
- Fallback: **SendGrid** if Resend quota exceeded.

### Templates (HTML + plain-text pairs)
| Trigger | Template |
|---------|----------|
| Welcome after OAuth | `welcome.html` |
| Subscription activated | `subscription_activated.html` |
| Payment failed | `payment_failed.html` |
| Subscription cancelled | `subscription_cancelled.html` |
| Password reset (if added) | `password_reset.html` |
| LGPD/GDPR data export ready | `data_export_ready.html` |
| Account deletion confirmation | `account_deleted.html` |

### Sending contract
```rust
fn send_email(to: &str, template: EmailTemplate, vars: HashMap<String, String>) -> Result<()>
```
All sends are idempotent (deduplicated by `idempotency_key = sha256(user_id + template + date)`).
Failed sends retry with exponential backoff (3 attempts, max 1 hour).

---

## 6. i18n for Site

### Supported locales
`en`, `pt-BR`, `es`, `fr`, `de`, `it`, `nl`, `pl`, `tr`, `ru`, `ar`, `hi`, `zh`, `ja`, `ko`

### Implementation
- Translation files: `site/locales/<locale>.json` (flat key-value).
- Locale detection order: (1) `?lang=` query param, (2) `Accept-Language` header,
  (3) geo-IP country → default locale map, (4) fallback `en`.
- Backend injects `window.__locale` and `window.__messages` into HTML at render time.
- All transactional email templates also honour locale stored in `users.locale`.

### Key namespaces
```
nav.*       — navigation items
hero.*      — landing page hero copy
pricing.*   — pricing page
billing.*   — billing UI
auth.*      — auth flow
errors.*    — error messages
emails.*    — email subject lines
```','docs/roadmap/SITE_BACKEND_SPEC.md','e4274bfcdbed00acabc07e2f4f55acacca3fc143e583bb29a219007982695493','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/RUN_PROVENANCE.md','project_doc','doc://simplicio-runtime/docs/RUN_PROVENANCE.md','doc: Run Provenance & Evidence Ledger (`simplicio.evidence-ledger/v1`)','# Run Provenance & Evidence Ledger (`simplicio.evidence-ledger/v1`)

This document covers the evidence ledger and run-provenance stream shipped for
issue #46. It explains the two provenance streams every `simplicio` run emits,
the on-disk layout, the redaction policy, and how to inspect a finished run.

## Two append-only streams

Every run materializes a stable run directory under
`.simplicio-loop/runs/<run-id>/`. The runtime writes two independent, line-delimited
JSONL streams there:

| File          | Schema id                       | Writer             | Contents |
|---------------|---------------------------------|--------------------|----------|
| `events.jsonl`| `simplicio.runtime-event/v1`    | `RunContext::log`  | The raw event stream: run start, repo lock, task normalize, capability decisions, command start/finish, model calls, agent spawn/kill, validation, cost, commit/push/PR handoff. |
| `ledger.jsonl`| `simplicio.evidence-ledger/v1`  | `RunContext::ledger` | The curated **evidence ledger**: the same lifecycle, but shaped for human audit and replay. Each line carries a secret-redacted `details` payload. |

Both streams share the same line shape, validated by
[`schemas/run-provenance.schema.json`](../../schemas/run-provenance.schema.json):

```json
{
  "schema":   "simplicio.evidence-ledger/v1",
  "run_id":   "run-1717200000000-4242",
  "event":    "command_finished",
  "timestamp":"unix:1717200012",
  "status":   "success",
  "details":  { "command": "cargo build", "exit_code": 0, "duration_ms": 9821 }
}
```

Each line is written with `writeln!` and is independently parseable, so a
partial or crashed run still leaves a valid, replayable tail.

## Ledger events (acceptance criteria coverage)

The `simplicio.evidence-ledger/v1` stream records, at minimum:

- `task_normalized`
- `repo_mapped`
- `capability_decisions_recorded` (selected or skipped)
- `command_started` / `command_finished` / `command_failed`
- `file_changed`
- `model_called`
- `agent_spawned` / `agent_killed` / `agent_reused`
- `validation_passed` / `validation_failed`
- `screenshot_captured` (Playwright)
- `api_smoke_captured`
- `cost_recorded` (token/cost event)
- `commit_pushed` / `pr_handoff`

## Persistence & stable run directory

The run directory is stable and stable-named (`<mode>-<unix_millis>-<pid>` when
no `--run-id` is supplied). It is the single source of truth that ties every
provenance line, artifact, and evidence path to one auditable run. A sampled,
sanitized copy of the provenance stream is committed as
[`examples/run-provenance.example.json`](../../examples/run-provenance.example.json).

## Artifact references

The evidence bundle under `<run-dir>/evidence/` references every artifact a run
produces: screenshots, logs, traces, reports, diffs, and PR summaries. The
bundle manifest (`evidence/index.json`, schema
[`schemas/evidence-ledger.schema.json`](../../schemas/evidence-ledger.schema.json),
id `simplicio.evidence-index/v1`) lists those artifact paths and the access
policy. See [`examples/run-directory/README.md`](../run-directory/README.md) for
the full layout.

## Inspecting a run

```powershell
simplicio evidence show --repo . --run-id run-1717200000000-4242 --json
```

`simplicio evidence show` prints a human-readable run summary assembled from the
ledger and the evidence index.

## Redaction policy

Every `details` payload written to either stream is passed through the runtime''s
secret redaction before serialization. Tokens, passwords, API keys, and
credential material are masked (`***REDACTED***`). The redaction contract lives
in `src/secrets_vault.rs` and the `agent/redact.py` helper; the same policy
guards the final evidence bundle, so committed fixtures stay free of secrets.

## Final evidence bundle

`RunContext` emits a final evidence bundle (`evidence/index.json` +
`evidence/index.md`) plus `final-report.md`/`final-report.json`. The bundle is
the shareable, human-reviewable proof of what happened, why, and which evidence
supports completion — satisfying the "proof, not just an answer" requirement
from issue #46.

## Validation

- The runtime validates every live provenance line against
  `schemas/run-provenance.schema.json`.
- The evidence index validates against `schemas/evidence-ledger.schema.json`.
- The sanitized fixture in `examples/run-provenance.example.json` validates with
  the same schema under the repo''s targeted unit tests.','docs/RUN_PROVENANCE.md','d13249fa33e1520e94f6ad7376c5c74b076d0fce062d413d38a836e1e9345fbb','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/runtime-load-100.md','project_doc','doc://simplicio-runtime/docs/runtime-load-100.md','doc: Runtime-100 / RR88 load harness (#3435)','# Runtime-100 / RR88 load harness (#3435)

`scripts/load_100_work_items.py` is the executable contract for 100
deterministic work items. It uses a bounded thread pool and condition-backed
CPU/I/O quotas, priority round-robin dispatch, a 10% fixture failure rate, a
cancel wave, and a per-item SHA-256 receipt chain.

Run the focused suite:

```bash
python3 -m unittest discover -s issue-3435/tests -p ''test_*.py''
python3 issue-3435/scripts/load_100_work_items.py \
  --output issue-3435/receipts/runtime-load-100.json
```

The benchmark always performs one warmup plus at least five measured
repetitions for `baseline`, `runtime`, `runtime+loop`, and `full-stack`.
Baseline is the real in-process scheduler. The other modes accept commands via
`--runtime-command`, `--loop-command`, and `--full-stack-command` (or the
corresponding `SIMPLICIO_*_BIN` environment variables). Missing adapters are
`BLOCKED`, with `samples_ms`, medians, and comparison ratios set to `null`.

Provider tokens and cost are never estimated by this harness. `provider_usage`
remains `null` unless an adapter emits a usage object in its JSON response.
The fixture seed (`88`) is also passed to adapters; a local neural adapter is
reported `BLOCKED` unless `SIMPLICIO_LOCAL_NEURAL_BIN` is present.

The receipt reports unit, integration, system, regression, performance,
coverage (threshold 85%), property-fuzz, real-code, and invariant gates. The
coverage gate is `BLOCKED` unless a measured percentage is supplied with
`--coverage-percent`; record the output from a real coverage tool, for example:

```bash
coverage run -m unittest discover -s issue-3435/tests -p ''test_*.py''
coverage report --fail-under=85
python3 issue-3435/scripts/load_100_work_items.py --coverage-percent 100 \
  --output issue-3435/receipts/runtime-load-100.json
```

This receipt does not certify provider economics or system/full-stack
behavior when the corresponding binary/toolchain is absent.','docs/runtime-load-100.md','4dbf240a3caf73642f37cfb09e61b00c8dd3158d892b63ccf0ee5a13aff831c2','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SAVINGS_EVENT_SPEC.md','project_doc','doc://simplicio-runtime/docs/SAVINGS_EVENT_SPEC.md','doc: `simplicio.savings-event/v1` — canonical ecosystem spec','# `simplicio.savings-event/v1` — canonical ecosystem spec

**Status:** canonical, versioned. **Reference implementation:** this repo, Rust,
closed-source (`publish = false`) — `crates/simplicio-savings/src/analytics.rs`
(schema + ledger), `auto_meter.rs` (auto-recording, refuses to fabricate),
`pricing_catalog.rs` (`PriceConfidence`), `token_counter.rs` (canonical
tokenizer ids + the shared `chars/4` heuristic), `watch.rs` + `dashboard.rs`
(the two blessed live aggregators — see [§6](#6-the-two-blessed-aggregators)).

**Why this doc exists (issue [#2775](https://github.com/wesleysimplicio/simplicio-runtime/issues/2775)):**
the reference implementation lives in a closed-source crate. Without an
extracted, versioned doc, the ecosystem''s other (open) repos — mapper,
dev-cli, prompt, sprint, loop, loop-marketing — have no choice but to
informally re-derive the schema from whatever JSON they happen to observe on
disk, and they already had **≥5 divergent token estimators** disagreeing
~30% on dense JSON (`ceil(chars/4)` in the loop harness, `words*4/3` vs
`chars/4` in dev-cli, BPE-approx `simplicio_tokens.py`, tiktoken in the agent,
HF tokenizers here — still a stub, see [§4](#4-tokenizer-policy)). This doc is
the single source of truth those repos vendor from, the same way the mapper
vendors [`YOOL_TUPLE_HAMT.md`](https://github.com/wesleysimplicio/yool-tuple-hamt)
(this doc **supersedes** that spec''s §1.8.4 "Receipt schema reference"
specifically for token-cost/savings receipts — §1.8.4 remains the general HAMT
receipt contract for everything else).

**Companion doc:** [`SIMPLICIO_TOKEN_RECEIPT.md`](SIMPLICIO_TOKEN_RECEIPT.md)
is the practitioner''s how-to / sales framing built on top of this schema (how
to *produce* an honest receipt for a specific claim). This doc is the field-by-
field reference; that one is the narrative.

---

## 1. Required fields

Every `simplicio.savings-event/v1` record is one JSON object, one line in an
append-only, hash-chained JSONL ledger (see [§5](#5-the-ledger)). Field names
below match the Rust structs in `analytics.rs` verbatim.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema` | string | yes | always `"simplicio.savings-event/v1"` |
| `event_id` | string | yes | content-derived short hash, unique per event |
| `timestamp` / `timezone` | string | yes | RFC3339 UTC + the recording host''s `TZ` |
| `prev_event_hash` | string\|null | yes | previous event''s `event_hash`, or `null` for the first event — the hash-chain link |
| `event_hash` | string | yes | SHA-256 of this event with `event_hash` itself cleared — see [§5](#5-the-ledger) |
| `user.id` / `user.email_hash` / `user.display` | string/string?/string | yes | never invented — `"unknown"` when absent, email hashed, never raw |
| `team.id` / `team.name` | string | yes | `"unknown"` when absent |
| `actor.kind` | `human\|agent\|ci\|service` | yes | who actually ran the operation |
| `actor.worker_id` / `actor.provider_session` | string? | no | sub-agent / session identity when applicable |
| `repo.path` / `repo.remote` / `repo.branch` / `repo.commit` | string | yes | `"unknown"` when git context is unavailable, never fabricated |
| `task.id` / `task.source` / `task.title` | string | yes | `source` is the free-text origin (`chat`, `issue`, `pr`, `workflow`, …) — see [§3](#3-leversource-taxonomy) for the `source` values this runtime uses today |
| `llm.provider` / `llm.model` / `llm.surface` | string | yes | `surface` identifies the calling context (`codex`, `claude`, `simplicio-cli/<cmd>`, `runtime/map--for-llm-toon`, …) |
| `llm.pricing_version` / `llm.pricing_source_url` / `llm.pricing_known` | string?/string?/bool | yes | ties cost to a versioned pricing catalog entry — never a guessed price |
| `tokens.actual_input` / `tokens.actual_output` / `tokens.actual_total` | u64 | yes | tokens spent *with* Simplicio |
| `tokens.baseline_total` | u64 | yes | tokens the same outcome would have cost *without* Simplicio |
| `tokens.saved_total` | u64 | yes | `baseline_total − actual_total`, saturating (never negative) |
| `tokens.input_chars` / `tokens.output_chars` | u64? | no | raw character counts, set only on `llm_spend` events (`savings record --input-chars N --output-chars N`, [#3158](https://github.com/wesleysimplicio/simplicio-runtime/issues/3158)) — omitted (not `null`) on every other event, so pre-#3158 ledger lines re-hash identically |
| `cost.currency` / `cost.actual` / `cost.baseline` / `cost.saved` / `cost.status` | string/f64?/f64?/f64?/string | yes | `status` is `"versioned_catalog"` or `"unknown"` — an `"unknown"` status MUST NOT be paired with a non-null dollar figure (mirrors `PriceConfidence::Unknown`, [§4](#4-tokenizer-policy)) |
| `proof.kind` | `measured\|estimated\|replayed\|benchmark` | yes | see [§2](#2-proofkind) |
| `proof.confidence` | string | yes | `"high"` (measured/replayed/benchmark) or `"low"`/`"medium"` (estimated) |
| `proof.evidence_refs` / `proof.command_hashes` / `proof.log_refs` / `proof.methodology_chain` | array | yes/no* | audit trail; the three `*` fields are omitted (not `[]`) when empty, to keep pre-#2775 ledger bytes stable — see [§5](#5-the-ledger) |
| `proof.methodology` | string | yes | one-line human summary of how the numbers were produced |
| `proof.upgraded_from` / `proof.original_kind` | string?/string? | no | set only when `savings upgrade` promoted an `estimated` event to `measured` — the *original* event is never mutated, a new chained event is appended instead |
| `proof.tokenizer_id` | string? | **conditionally required — see [§4](#4-tokenizer-policy)** | which tokenizer/method produced this event''s token counts |
| `simplicio.surfaces` / `simplicio.run_id` | array/string | yes | which Simplicio flows contributed, and the run this event belongs to |
| `privacy.sync_opt_in` / `privacy.redaction_profile` | bool/string | yes | remote sync is opt-in and off by default; see [`SIMPLICIO_TOKEN_RECEIPT.md`](SIMPLICIO_TOKEN_RECEIPT.md) |

A minimal c','docs/SAVINGS_EVENT_SPEC.md','d7048e768180efb52c4ef00d1563e289c4eb021de8d2302e0972334baf1784c0','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SCHEDULER.md','project_doc','doc://simplicio-runtime/docs/SCHEDULER.md','doc: Decision engine, scheduler & capacity governor (issue #346)','# Decision engine, scheduler & capacity governor (issue #346)

The runtime already ships real decision/scheduling/capacity surfaces. This doc
consolidates what exists today, the schemas behind each, and the gaps remaining
for #346 — so follow-up slices build on the current implementation instead of
re-inventing it.

## Surfaces that exist today

| command | what it does | schema |
|---|---|---|
| `simplicio decide "<task>" --repo . --json` | decision router: route, confidence, backend choice, whether a model call was avoided, token ledger | `simplicio.decision-route/v1` (`schemas/decision-route.schema.json`) |
| `simplicio parallelism --repo . --agents N --json` | computes the safe parallel plan: logical vs active agents, worker pools, throttle reason | `simplicio.parallel-execution/v1` (`schemas/parallel-execution.schema.json`) |
| `simplicio agents status --agents N --json` | live capacity: active/queued/paused agents, model workers, machine signals, lifecycle policy | `simplicio.agent-capacity/v1` |
| `simplicio governor simulate --repo . --agents N --json` | simulates the governor against a sampled machine profile (requested-vs-granted) | `simplicio.governor-simulation/v1` |
| `simplicio agents delegate … / pause / resume / interrupt` | agent lifecycle control | `agent-worker`, `agent-lease`, `agent-queue-item` |

### Observed governor behaviour (real output)

Requesting more agents than the host can serve is **capped and throttled**, not
naively spawned. Example (`--agents 600` on a 16-thread host):

```json
{ "schema":"simplicio.parallel-execution/v1",
  "summary":{ "requested_agents":600, "logical_agents":100, "active_agents":16,
    "parallel_read_workers":16, "parallel_command_workers":8,
    "parallel_evidence_workers":4, "model_workers":1, "write_workers":1,
    "throttled":true,
    "reason":"requested_capped_by_max_logical_agents,cpu_thread_capacity" } }
```

`agents status --agents 200` → `active_agents:25, queued_agents:175, mode:"turbo"`
with lifecycle policy (`idle_kill_ttl_seconds`, `stuck_timeout_seconds`,
`reuse_warm_agents`, `separate_model_workers`). So the capacity governor, worker
pools, queueing, and lifecycle *policy* already exist; `--agents N` is logical
concurrency over a governed pool, not N physical model copies.

Current desktop-safe defaults:
- scheduler active cap defaults to roughly `threads * 4`, bounded to 128;
- worker pool defaults to max 16 threads;
- model workers default to 1 shared worker in the scheduler policy;
- `full` profile is still the top profile, but with adaptive CPU/memory/IO
  ceilings intended to preserve workstation responsiveness.

## Mapping to #346 acceptance criteria

| #346 criterion | status today | gap / next slice |
|---|---|---|
| Stable orchestration of 100+ logical agents with controlled resources | **partial** — governor caps logical=100 + worker pools + queue exist | stress benchmark proving stability under real load (slice 6) |
| Auditable, explainable decision traces | **present** — `simplicio.decision-route/v1` records route, confidence, backend, token ledger | richer per-decision rationale strings + ledger query (slice 5) |
| Warm reuse reduces latency >3× | **policy only** — `reuse_warm_agents` flag exists | implement warm KV/mapped-state pool + measure (slice 2) |
| TUI shows real-time capacity & agent health | **partial** — `agents status` JSON | live TUI capacity bars + agent table (slice 4) |
| Benchmarks vs naive spawning | not yet | stress harness (ties into #348) |

## Lifecycle policy (already modeled)

`agent-capacity/v1` exposes: `queued / running / paused / idle / stuck / killed`
counts, `reused_model_workers`, and a `lifecycle_policy`
(`idle_kill_ttl_seconds`, `stuck_timeout_seconds`, `reuse_warm_agents`,
`separate_model_workers`). The remaining work is to *enforce* warm reuse and
stuck-kill with evidence, not to invent the model.

## Remaining slices (#346)

1. ✅ Document existing decision/scheduler/governor surfaces + gap map (this doc).
2. Warm agent pool: keep KV cache + mapped repo state across tasks; measure reuse hit-rate.
3. Yool-backed shared scheduling state (depends on #345).
4. Live TUI capacity/agent-health views.
5. Policy engine + per-decision audit rationale + ledger query.
6. Stress benchmark: N agents on limited hardware (ties into #348 harness).

## References
- `schemas/{decision-route,parallel-execution,agent-worker,agent-lease,agent-queue-item,action-gate-decision}.schema.json`
- `docs/SIMPLICIO_OPERATIONAL_MANUAL.md` (decision engine, capacity, parallelism)
- #345 (Yool shared state), #348 (benchmark harness)','docs/SCHEDULER.md','4b841c3357d8bfaa11d1308faded3cdbd8ea45a0e5043ddd822f3ac205280145','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SCRIPT_OWNERSHIP_QUARANTINE.md','project_doc','doc://simplicio-runtime/docs/SCRIPT_OWNERSHIP_QUARANTINE.md','doc: Script ownership & quarantine matrix','# Script ownership & quarantine matrix

Artefato humano mínimo para a #1540. O inventário canônico legível por máquina fica em
`./.simplicio-loop/docs/script-ownership-inventory.json`.

## Escopo

- cobre `scripts/`, `hooks/` e `.github/workflows/`
- registra ownership + quarentena de Python/Node/Shell/workflows residuais
- não promove esses arquivos a runtime core; `src/main.rs` continua fora deste patch

## Gate mínimo

- `hooks/pre-commit` roda `py scripts/audit-script-ownership.py --check`
- o gate só dispara quando há mudanças staged em scripts/hooks/workflows/docs observados
- se o inventário/doc estiver desatualizado, o commit falha com instrução de refresh

## Snapshot

- total rastreado: **274**
- linguagens: `{"node": 2, "python": 174, "shell": 87, "workflow": 11}`
- quarentena: `{"ci-contract": 11, "mandatory-gate": 13, "operator-shell": 74, "residual-node": 2, "residual-python": 174}`
- owners: `{"backlog-ops": 9, "ci-release": 11, "distribution-ops": 38, "gateway-ops": 6, "repo-governance": 13, "research-evidence": 35, "runtime-ops": 162}`

## Docs observados

- `docs/HERMES_AGENT_PORT_MATRIX.md`
- `docs/SCRIPT_OWNERSHIP_QUARANTINE.md`

## Regras de ownership/quarentena

| Classe | Owner | Quarentena | Uso |
|---|---|---|---|
| hook | repo-governance | mandatory-gate | enforcement local de commit/push |
| workflow | ci-release | ci-contract | execução apenas em GitHub Actions |
| benchmark-audit | research-evidence | residual-python / operator-shell | evidência, auditoria e comparação |
| packaging-bootstrap | distribution-ops | residual-python / operator-shell | instalação, bootstrap, release e empacotamento |
| gateway-ops | gateway-ops | residual-python / operator-shell | suporte operacional de gateway/Discord/daemon |
| issue-ops / utility | backlog-ops / runtime-ops | residual-python / residual-node / operator-shell | utilitários explícitos, não core |

## Refresh

```bash
py scripts/audit-script-ownership.py
```

## Amostra

| Path | Lang | Owner | Quarentena | Refs docs |
|---|---|---|---|---:|
| `.github/workflows/agi-bench-nightly.yml` | `workflow` | `ci-release` | `ci-contract` | 1 |
| `.github/workflows/build-matrix.yml` | `workflow` | `ci-release` | `ci-contract` | 0 |
| `.github/workflows/canvas-evidence-bridge.yml` | `workflow` | `ci-release` | `ci-contract` | 0 |
| `.github/workflows/ci.yml` | `workflow` | `ci-release` | `ci-contract` | 12 |
| `.github/workflows/content-pipeline.yml` | `workflow` | `ci-release` | `ci-contract` | 0 |
| `.github/workflows/perf-bench-nightly.yml` | `workflow` | `ci-release` | `ci-contract` | 0 |
| `.github/workflows/performance-baseline.yml` | `workflow` | `ci-release` | `ci-contract` | 0 |
| `.github/workflows/performance-regression.yml` | `workflow` | `ci-release` | `ci-contract` | 0 |
| `.github/workflows/qwen35-snake-e2e.yml` | `workflow` | `ci-release` | `ci-contract` | 0 |
| `.github/workflows/release-publish.yml` | `workflow` | `ci-release` | `ci-contract` | 0 |
| `.github/workflows/skill-seed-sync.yml` | `workflow` | `ci-release` | `ci-contract` | 0 |
| `hooks/README.md` | `shell` | `repo-governance` | `mandatory-gate` | 0 |
| `hooks/action_gate.py` | `shell` | `repo-governance` | `mandatory-gate` | 0 |
| `hooks/hooks.claude.json` | `shell` | `repo-governance` | `mandatory-gate` | 0 |
| `hooks/hooks.json` | `shell` | `repo-governance` | `mandatory-gate` | 0 |
| `hooks/loop_capture.py` | `shell` | `repo-governance` | `mandatory-gate` | 0 |
| `hooks/loop_stop.py` | `shell` | `repo-governance` | `mandatory-gate` | 0 |
| `hooks/orient_clamp.py` | `shell` | `repo-governance` | `mandatory-gate` | 0 |
| `hooks/orient_rewrite.py` | `shell` | `repo-governance` | `mandatory-gate` | 0 |
| `hooks/pre-commit` | `shell` | `repo-governance` | `mandatory-gate` | 3 |

_A lista completa fica no JSON canônico sob `.simplicio-loop/docs/`._','docs/SCRIPT_OWNERSHIP_QUARANTINE.md','952e0f2a78d4304c55c933fe5bd818c85488de9dd1e498eb4af43aedd3607adb','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/security/PRIVACY.md','project_doc','doc://simplicio-runtime/docs/security/PRIVACY.md','doc: Simplicio Runtime — Privacy Policy (Local-First)','# Simplicio Runtime — Privacy Policy (Local-First)

> Companion to [`SECURITY.md`](SECURITY.md) · Issue [#32](https://github.com/wesleysimplicio/simplicio-runtime/issues/32)

This policy explains what the Simplicio Runtime collects, how it is minimized,
and the controls that keep private repositories and enterprise usage safe.

## Data minimization

Simplicio is designed to need as little personal data as possible:

- **No raw e-mail ever leaves the process.** E-mail is SHA-256 hashed
  (`sha256:` prefix) before any analytics payload or report
  (`email_fingerprint`, `crates/simplicio-savings/src/identity_1573.rs`).
- **No raw secrets.** All credential shapes are redacted before logging,
  event emission, or evidence persistence (`redact_secrets`).
- **Identity is never invented.** When a field is absent, the resolver returns
  `"unknown"` / `None` — never a fabricated value
  (`resolve_identity`).

## Redaction profiles

Selected via `SIMPLICIO_REDACTION_PROFILE`:

| Profile | E-mail | Repo path | Task title | Use |
|---|---|---|---|---|
| `none` | raw (local only) | as-is | as-is | Local use only; do not sync. |
| `hashed-email` (default) | hashed | as-is | as-is | Safe local + opt-in sync. |
| `strict` | hashed | hashed | hashed | Enterprise/private; no PII leaves. |

Under `strict`, `no_pii_in_sync` is forced on and repo path + task title are
hashed (`path_fingerprint`, `redact_task_title`).

## Sync & consent

- Sync is **off by default**.
- Enabling it (`--sync-opt-in` / `SIMPLICIO_SYNC_OPT_IN`) does not bypass
  redaction; only hashed/redacted fields are eligible.
- CI contexts are **always offline-only** — an opt-in request is ignored.
- `SIMPLICIO_OFFLINE_ONLY=1` forces all-local operation.

## Transparency

Any permitted or actual remote-LLM usage is recorded in the event ledger via
the `simplicio.remote-llm-policy/v1` event (`event_log_required: true`). Users
can audit when a remote model was used and for what reason.

## Data the runtime may know

| Field | Source | Redacted? |
|---|---|---|
| OS username / git `user.name` | env / git config | Kept locally; not synced as PII. |
| E-mail | env / git config | Hashed before sync. |
| Team / org / project | env / config | Synced only under opt-in. |
| Actor kind (human/agent/ci/service) | env / surface | Non-PII classification. |
| Usage analytics (tokens saved) | local events | Aggregated; PII stripped per profile. |

## User rights & control

- Set `SIMPLICIO_OFFLINE_ONLY=1` to guarantee zero egress.
- Set `SIMPLICIO_REDACTION_PROFILE=strict` to guarantee no PII in any payload.
- Delete local state any time: `.simplicio-loop/` is local and git-ignored.','docs/security/PRIVACY.md','db47989a18061e1ad12ff7ff37cfa7388d42a5d5d5859474e26945b13a8a6ac5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/security/SECRETS_VAULT_SPEC.md','project_doc','doc://simplicio-runtime/docs/security/SECRETS_VAULT_SPEC.md','doc: Secrets Vault — Issue #2222','# Secrets Vault — Issue #2222

## Overview

Encrypted local store for API keys, tokens, and credentials. Replaces raw
env-var leakage and plaintext config files. All secret access goes through the
vault API; the vault is locked at rest and unlocked per-session with a
master passphrase or OS keychain integration.

## Threat model

- Secrets must not appear in plaintext on disk, in git history, or in log files
- A compromised process should not be able to read secrets without the unlock key
- Skills and sub-agents receive secrets only via injected env vars, never via
  command-line args or stdout

## Storage format

File: `~/.simplicio-loop/vault.enc`

```
[4 bytes] magic "SIMV"
[1 byte]  version = 1
[16 bytes] salt (random, per-vault)
[12 bytes] nonce (random, per-write)
[N bytes]  AES-256-GCM ciphertext of JSON payload
[16 bytes] GCM authentication tag
```

JSON payload (plaintext inside ciphertext):
```json
{
  "version": 1,
  "entries": {
    "<key_name>": {
      "value": "<secret>",
      "created_at": "<iso8601>",
      "last_accessed": "<iso8601>",
      "tags": ["api-key", "openrouter"]
    }
  }
}
```

Key derivation: `PBKDF2-HMAC-SHA256`, 600000 iterations, 32-byte output.  
Cipher: `AES-256-GCM` (via `aes-gcm` crate, `ring`, or `openssl`).

## OS keychain integration

On unlock, the derived key may be stored in:
- macOS: Keychain Services (`security` CLI or `keychain` crate)
- Windows: DPAPI / Credential Manager
- Linux: `libsecret` / `secret-service` D-Bus protocol

When OS keychain is available, the session unlock key is stored there and the
vault auto-unlocks for the session lifetime without re-prompting.

## CLI surface

```
simplicio vault init                     # create vault, set master passphrase
simplicio vault set <name> [--value V]   # add/update secret (prompts if --value omitted)
simplicio vault get <name>               # print value (prompts for passphrase)
simplicio vault list                     # list key names (no values)
simplicio vault delete <name>            # remove entry
simplicio vault lock                     # clear in-memory session key
simplicio vault rotate-passphrase        # re-derive key, re-encrypt
simplicio vault export --format env      # emit `export KEY=VALUE` (no plaintext file)
```

## Runtime integration

At startup, if the vault is present and a session key is cached (OS keychain),
secrets are available via `vault_get(name)` without user interaction.

Environment injection for skills:
```rust
pub fn inject_secrets(cmd: &mut Command, keys: &[&str], vault: &Vault) {
    for key in keys {
        if let Ok(val) = vault.get(key) {
            cmd.env(key, val);
        }
    }
}
```

Secrets are never passed via command-line args or written to log files.

## Gate integration

- `vault set` and `vault delete` are `high` risk — always prompt user
- `vault get` in non-interactive context (skill, sub-agent) is `medium` risk
- `vault export` is `high` risk — always prompt + log to HBP

## Audit trail

Every vault access (read or write) appends to HBP ledger:
```json
{
  "schema": "simplicio.vault.access/v1",
  "operation": "get|set|delete",
  "key_name": "<name>",
  "actor": "user|skill:<id>|agent:<id>",
  "timestamp": "<iso8601>"
}
```

Value is never written to the ledger.

## Delivery criteria

- [ ] `src/secrets_vault.rs`: `Vault` struct, encrypt/decrypt, PBKDF2 key derivation
- [ ] `vault init/set/get/list/delete/lock` CLI commands wired in `main.rs`
- [ ] OS keychain integration for macOS (DPAPI stub for Windows, D-Bus stub for Linux)
- [ ] `inject_secrets()` used by `SkillSandbox` instead of raw env pass-through
- [ ] Test: value round-trips encrypt/decrypt correctly
- [ ] Test: wrong passphrase returns `Err` with no value leak
- [ ] Gate: `set`/`delete`/`export` are `high` risk

## Tracking

GitHub: #2222','docs/security/SECRETS_VAULT_SPEC.md','4d4b78efb74a45a324da6ed2a5a92d1e8498116f374168b1571d40910bddf74d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/security/SECURITY.md','project_doc','doc://simplicio-runtime/docs/security/SECURITY.md','doc: Simplicio Runtime — Local-First Security & Privacy Review','# Simplicio Runtime — Local-First Security & Privacy Review

> Issue: [#32 — chore: Add local-first security and privacy review](https://github.com/wesleysimplicio/simplicio-runtime/issues/32)
> Milestone: M8 — Security and Reliability
> Status: implemented (docs + redaction tests + explicit remote-LLM event logging)

This document is the canonical security/privacy review for the Simplicio
Runtime. It defines what stays local, when a remote LLM is allowed, how secrets
are redacted, how evidence artifacts are protected, and documents the opt-in
network behavior. It is the acceptance reference for issue #32.

---

## 1. Local-first principle

Simplicio is a **local-first** runtime. By default:

- All reasoning, orchestration, deterministic edits, validation, and evidence
  collection happen **on the local machine**.
- No data leaves the machine unless the user has **explicitly opted in** to a
  remote capability, and even then only the minimum required payload is sent.
- When a remote LLM is used, the fact is **always recorded in the event log**
  (see §4). Nothing remote is silent.

The offline-first policy is enforced in `src/main_parts/chunk_11.rs`
(`remote_llm_policy_event_json`) and surfaced through the
`simplicio.remote-llm-policy/v1` event, which carries
`requires_explicit_opt_in: true` and `event_log_required: true`.

---

## 2. What stays local

| Data | Stays local? | Notes |
|---|---|---|
| Source code, worktree, git state | ✅ Always | Never transmitted. |
| Repo path / file paths | ✅ By default | Hashed under the `strict` redaction profile before any sync. |
| Task titles | ✅ By default | Kept as-is under `hashed-email`; hashed under `strict`. |
| E-mail | ✅ Always | SHA-256 hashed (`sha256:` prefix) before leaving the process. |
| Raw secrets / credentials | ✅ Always | Stripped from all logs, events, and reports (see §3). |
| Savings analytics identity | ✅ Unless opted in | `IdentityPrivacy.sync_opt_in` gates any upload. |

CI environments are **always offline-only**: even an explicit sync opt-in is
ignored for `ActorKind::Ci` (see `crates/simplicio-savings/src/identity_1573.rs`).

---

## 3. Secret redaction

Secrets are redacted at multiple layers. The canonical scrubber is
`redact_secrets` in `src/main_parts/chunk_16.rs`. It is exercised continuously
by `redaction_self_test_json`, which runs a built-in corpus of *synthetic*
secrets through the scrubber and reports `executed: true, failed: 0, status: passed`.

### Redacted shapes

- `Authorization: Bearer <token>` → `[REDACTED:bearer]`
- JWT (3 dot-separated base64url segments, len > 40) → `[REDACTED:jwt]`
- AWS access key id (`AKIA…`) → `[REDACTED:aws-key]`
- `aws_secret_access_key=…` → `[REDACTED:aws-secret]`
- GitHub token families (`ghp_`, `gho_`, `ghs_`, `ghu_`, `ghr_`, `github_pat_`) → `[REDACTED:gh-token]`
- OpenAI-style `sk-…` keys → `[REDACTED:api-key]`
- `key=value` pairs (`token=`, `password=`, `secret=`, `api_key=`, …) in CLI args, URLs, and JSON bodies → `[REDACTED:<kind>]`
- E-mail addresses (savings identity) → SHA-256 hash, `sha256:` prefix

The scrubber is **idempotent** (re-redacting a redacted string changes nothing)
and **whitespace-preserving** (newlines and layout are kept; only the secret
value is replaced).

### Tests

Secret-redaction behavior is covered by unit tests that must pass:

- `redacts_common_secret_shapes` (`src/main_tests_parts/test_part_01.rs`)
- `redacts_bearer_jwt_aws_url_and_json_shapes`
- `redaction_self_test_executes_and_passes_all_probes`

Redaction is also proven at report time via `privacy_report_json`, which embeds
the live `redaction-self-test` result rather than statically asserting it works.

---

## 4. Remote LLM calls are explicit in event logs

Every runtime step that *could* escalate to a remote model emits a
`simplicio.remote-llm-policy/v1` event with:

```json
{
  "schema": "simplicio.remote-llm-policy/v1",
  "remote_allowed": false,
  "remote_used": false,
  "requires_explicit_opt_in": true,
  "event_log_required": true,
  "reason": "offline-first policy keeps communication and classification local"
}
```

When `remote_allowed` is `true`, the reason explains the policy; `remote_used`
reflects whether a paid/remote call actually occurred. Because
`event_log_required` is always `true`, an auditor can scan the event ledger and
see exactly when a remote model was permitted or used — no silent egress.

---

## 5. Protecting evidence artifacts

Evidence and receipts are written under `.simplicio-loop/` (local). They never
contain raw secrets: the redaction layer is applied to command records and
privacy reports before they are persisted (see the `CommandRecord` redactions in
`redacts_common_secret_shapes`). Evidence files are git-ignored by default and
excluded from any sync unless explicitly opted in.

---

## 6. Opt-in network behavior

Network egress is opt-in and disclosed:

- `SIMPLICIO_OFFLINE_ONLY=1` (or CI detection) forces offline-only.
- `SIMPLICIO_SYNC_OPT_IN=1` / `--sync-opt-in` enables analytics sync — but only
  after redaction; CI and `strict` profile contexts still refuse PII sync.
- `SIMPLICIO_REDACTION_PROFILE` selects `none` / `hashed-email` (default) /
  `strict`.

See `crates/simplicio-savings/src/identity_1573.rs` for the full
`IdentityPrivacy` / `RedactionProfile` resolution logic.

---

## 7. Evidence & fixtures

- Redaction examples: `redaction_self_test_json` corpus (synthetic, clearly
  fake) executed on every privacy report.
- Privacy policy doc: [`PRIVACY.md`](PRIVACY.md).
- Redaction location: `src/main_parts/chunk_16.rs` (`redact_secrets`,
  `redaction_self_test_json`), `privacy_report_json` in `src/main_parts/chunk_10.rs`.
- Remote-LLM event: `src/main_parts/chunk_11.rs` (`remote_llm_policy_event_json`).
- Identity/redaction profiles: `crates/simplicio-savings/src/identity_1573.rs`.

Validate with:

```bash
simplicio privacy-report --repo . --json   # embeds redaction-self-test=passed
simplicio validate "task" --repo . --json  # secret-redaction te','docs/security/SECURITY.md','1f39b88634d3794b24fcd6c75eeb5532a90c2660ccf0efa442553811754fa75b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/security/SKILL_SANDBOX_SPEC.md','project_doc','doc://simplicio-runtime/docs/security/SKILL_SANDBOX_SPEC.md','doc: Skill Sandbox — Issue #2200','# Skill Sandbox — Issue #2200

## Overview

Skills run in an isolated subprocess with restricted permissions and resource
limits. The sandbox is a mandatory wrapper around all skill execution; there is
no bypass path except `--sandbox=none` with explicit user confirmation and a
gate-level `high` risk approval.

## Threat model

- A skill (including auto-created skills) may execute arbitrary shell commands
- A compromised or malicious skill must not be able to: read secrets, write
  outside the skill working directory, exhaust system resources, or exfiltrate
  data via network

## Isolation layers

### Process isolation

Skills run as a child process spawned via `std::process::Command` with:
- `stdin` closed (no piped input)
- `stdout`/`stderr` captured (never inherited)
- Working directory set to a per-execution temp dir under `.simplicio-loop/sandbox/runs/<id>/`
- Environment stripped to an allowlist (see below)

### Environment allowlist

Only these env vars are passed to the skill process:

```
SIMPLICIO_SKILL_ID
SIMPLICIO_RUN_ID
SIMPLICIO_WORK_DIR    # the per-run temp dir
PATH                  # system PATH only, no SIMPLICIO_API_KEY etc.
```

Secrets (`SIMPLICIO_API_KEY`, `OPENAI_API_KEY`, `*_TOKEN`, `*_SECRET`, etc.)
are explicitly excluded.

### Filesystem restrictions

- Write access: only `.simplicio-loop/sandbox/runs/<id>/` (the temp dir)
- Read access: project directory (read-only via bind mount on Linux; path restriction on Windows/macOS)
- Skill cannot write to `~/.simplicio-loop/`, `~/.config/`, or any system path

Implementation: use OS jail on Linux (`seccomp` + `unshare`), `sandbox-exec` on macOS,
job objects + restricted token on Windows.

### Resource limits

| Resource | Limit | Mechanism |
|----------|-------|-----------|
| CPU time | 60s wall clock | `RLIMIT_CPU` / job object timeout |
| Memory | 512 MB RSS | `RLIMIT_AS` / job object |
| Output size | 4 MB stdout+stderr combined | read loop byte counter |
| Child processes | 0 (no fork) | `RLIMIT_NPROC=0` / job object |
| Network | Blocked by default | `seccomp` deny / Windows firewall rule |

Network can be unblocked per-skill via `[sandbox] network = true` in `skill.toml`,
which triggers a `medium` gate approval before the run.

## SandboxConfig (skill.toml)

```toml
[sandbox]
timeout_secs = 60       # default
memory_mb = 512         # default
network = false         # default
allow_write = []        # additional paths user explicitly grants
```

## SkillSandbox struct

```rust
pub struct SkillSandbox {
    pub config: SandboxConfig,
    pub run_id: String,
    pub work_dir: PathBuf,
}

impl SkillSandbox {
    pub fn spawn(&self, skill_cmd: &[&str]) -> Result<SandboxOutput, SandboxError>;
    pub fn cleanup(&self);  // removes work_dir
}

pub struct SandboxOutput {
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
    pub wall_time_ms: u64,
    pub peak_rss_mb: Option<u64>,
}
```

## Audit trail

Every sandbox execution appends to HBP ledger:
```json
{
  "schema": "simplicio.sandbox.run/v1",
  "skill_id": "...",
  "run_id": "...",
  "exit_code": 0,
  "wall_time_ms": 1234,
  "resource_limit_hit": false
}
```

## Delivery criteria

- [ ] `src/skill_sandbox.rs` with `SkillSandbox` and `SandboxOutput`
- [ ] Environment allowlist enforced (test: API key not visible inside sandbox)
- [ ] Resource limits wired for Linux (`RLIMIT_*`), macOS (`sandbox-exec`), Windows (job objects)
- [ ] Output size cap enforced (test: 5 MB output truncated at 4 MB with error)
- [ ] Gate: `network = true` triggers medium-risk approval
- [ ] HBP audit record written on every run

## Tracking

GitHub: #2200','docs/security/SKILL_SANDBOX_SPEC.md','0e2c123968b0933a344ff070686ea256370aa3f1419535ae662ba5babd70d5e6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SELF_MUTATION_GOVERNANCE.md','project_doc','doc://simplicio-runtime/docs/SELF_MUTATION_GOVERNANCE.md','doc: Runtime self-mutation governance','# Runtime self-mutation governance

Runtime has two different operating lanes:

- **Active control-plane lane**: the running Runtime binary governs a multi-lane
  execution. Runtime-owned source and controlling-binary rebuild/update paths are
  frozen. Downstream repositories and isolated lane worktrees remain available.
- **Maintenance/update lane**: a separately provisioned Runtime worktree with
  separately recorded evidence. Runtime changes are allowed only when the lane
  is explicit and complete.

## Mode contract

The active lane is declared with either:

```sh
SIMPLICIO_CONTROL_PLANE_RUN=1
# or
SIMPLICIO_RUNTIME_MODE=active-control-plane
```

A maintenance lane must declare all three values before a Runtime source write
or binary rebuild is allowed:

```sh
SIMPLICIO_RUNTIME_MODE=maintenance
SIMPLICIO_MAINTENANCE_WORKTREE=/path/to/runtime-maintenance-worktree
SIMPLICIO_MAINTENANCE_EVIDENCE=/path/to/maintenance-evidence
```

Conflicting active and maintenance declarations fail closed. A maintenance mode
without an existing isolated worktree and evidence directory also fails closed;
Runtime mutation commands must run with `--repo` set to that declared worktree.

## Operator surface

Inspect the current mode without mutating anything:

```sh
simplicio self-mutation status --repo /path/to/runtime --json
```

The same split is discoverable from the normal operator surfaces:

```sh
simplicio doctor --help
simplicio self-mutation help --json
simplicio self-mutation status --repo /path/to/runtime --json
simplicio self-mutation maintenance --repo /path/to/runtime --json
```

`status` is observational. `maintenance`/`handoff` prints the required
next-action and never edits the active checkout. A successful return to the
control plane is an explicit handoff: seal the maintenance evidence, stop the
maintenance process, unset the maintenance markers, and re-check `status`
before resuming downstream issue execution.

The protected paths are the deterministic `simplicio edit` writer when its target
is Runtime-owned source, edit post-phases that invoke a rebuild/check, and
`update apply`/`update rollback` binary replacement paths. A blocked operation
returns `simplicio.self-mutation-receipt/v1` with the reason, current mode,
maintenance lane metadata, and the next action. It does not silently redirect
or claim that a maintenance change was applied.

After maintenance evidence is sealed, the operator explicitly hands control back
to the existing run by removing the maintenance markers and re-checking status;
the active run keeps its existing binary until the handoff is deliberate.','docs/SELF_MUTATION_GOVERNANCE.md','da6fe96ca460344547c6524cd66dce6dca744720f5f9bacf954ce00fd72b9291','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SEMANTIC_ABI_SPEC.md','project_doc','doc://simplicio-runtime/docs/SEMANTIC_ABI_SPEC.md','doc: Federated semantic ABI v1 — Runtime''s owned slice (#3135)','# Federated semantic ABI v1 — Runtime''s owned slice (#3135)

**Status:** Phase 1 slice, canonical for the Runtime-owned families only.
**Parent epic:** [#3134](https://github.com/wesleysimplicio/simplicio-runtime/issues/3134)
(Agent-driven ecosystem architecture). **This issue:** [#3135](https://github.com/wesleysimplicio/simplicio-runtime/issues/3135).

## Why this doc exists

#3134 replaces the earlier "Runtime as global scheduler" decision with a
federated model: five projects, five owners, no cross-repo schema registry
sovereign over another producer''s semantics. This repo (Runtime) is one of
those five producers. This doc formalizes **only what Runtime owns** —
`EffectRequest`, `GateDecision`, `EffectReceipt`, `ValidationReceipt` — and
documents where the other four producers'' schemas plug in by reference.
Following the same "vendor the doc, not the crate" pattern as
[`SAVINGS_EVENT_SPEC.md`](SAVINGS_EVENT_SPEC.md) and the narrower
[`docs/contracts/`](contracts/) docs.

## Ownership table (from #3134)

| Producer/owner | Schemas | Owned here? |
|---|---|---|
| Agent | `GoalEnvelope`, `AgentEvent`, session/turn identity | No — referenced by id/version only |
| Mapper | `ContextSnapshot`, `ContextGraph` | No |
| Dev CLI | `PlanDAG`, `EffectProposal`, `VerificationPlan` | No |
| Loop | `ControlDecision`, `ConvergenceState` | No |
| **Runtime** | **`EffectRequest`, `GateDecision`, `EffectReceipt`, `ValidationReceipt`** | **Yes — this doc** |

Runtime is not a "sovereign registry" of the other four producers'' semantics
(#3135 invariant #1: schema owner coincides with producer of truth). If
another repo''s schema needs to be referenced from this runtime (e.g. a
`PlanDAG` node id inside an `EffectRequest.payload`), it is carried
opaquely — this runtime validates its own envelope, not the payload''s
internal shape.

## The causal-id spine

Every family below embeds the same core ids (#3135 step 7-8), implemented
once in `crate::contracts_abi::CausalIds`:

| Id | Meaning |
|---|---|
| `trace_id` | The end-to-end trace this effect belongs to. |
| `session_id` | The Agent session (Runtime never owns session state itself — CLAUDE.md''s "Runtime does not possess transcript, memory, goal, or provider" applies here too). |
| `turn_id` | The conversational turn. |
| `attempt_id` | Retry/attempt counter within the turn. |
| `subworkflow_id` | Optional — set when the effect belongs to a Loop-managed subworkflow. |
| `effect_id` | This effect''s own id — the correlation key an `EffectReceipt` points back to. |
| `causal_parent` | The id of whatever caused this effect (another effect, a control decision, a plan node). `None` only at the root of a trace. |

Runtime does not mint `trace_id`/`session_id`/`turn_id` — those are the
Agent''s authority (per #3134''s "Autoridades reais" table). Runtime consumes
them as opaque strings and never treats an `EffectRequest` as more
authoritative than the `InvocationContext` it carries (#3135 invariant #6).

## Runtime-owned schemas

### `GateDecision` = `simplicio.action-gate-decision/v1` (no new schema)

Already mature and tested: `crate::action_gate` /
[`schemas/action-gate-decision.schema.json`](../schemas/action-gate-decision.schema.json).
`classify_action_risk` + `action_gate_decide` are the reference
implementation. #3135 does **not** introduce a competing `GateDecision` —
it formalizes this one as the federated shape, and flags (not yet
resolved) that five *other* local `GateDecision`-shaped enums exist
elsewhere in this codebase (`crates/simplicio-security/src/gate.rs`,
`src/unified_gate.rs`, `src/st_internet_gate.rs`,
`src/htool_write_approval.rs`, `src/orchestration/mod.rs`) — consolidating
those onto this one is tracked as a known gap below, not done by this doc.

### `EffectRequest` — [`schemas/effect-request.schema.json`](../schemas/effect-request.schema.json)

A single authorized effect a producer (typically the Agent''s
`ToolInvocationPipeline`) asks Runtime to gate/validate/apply. Deliberately
narrower than the pre-existing `read-request`/`write-request` schemas,
which it wraps rather than replaces — those describe *what kind* of
mechanical operation; `EffectRequest` describes *the causal envelope*
around any Runtime capability invocation. Rust type + validation:
`crate::contracts_abi::EffectRequest`. CLI: `simplicio contracts-abi
request [--effect-id ...] [--capability ...] [--repo ...] [--risk ...]`.

### `EffectReceipt` — [`schemas/effect-receipt.schema.json`](../schemas/effect-receipt.schema.json)

Proof that Runtime applied (or refused) exactly one `EffectRequest`,
correlated by `request_effect_id`. Per #3135 invariant #7, a receipt proves
*validation/effect only* — it never asserts anything about the Agent''s
reasoning. `deduped: true` signals the effect was not re-executed because
its `idempotency_key` had already been applied (invariant #8: unknown
version/capability fails explicitly rather than silently re-running).
Rust type: `crate::contracts_abi::EffectReceipt`.

### `ValidationReceipt` — [`schemas/validation-receipt.schema.json`](../schemas/validation-receipt.schema.json)

The **outcome** of running a `simplicio.validation-plan/v1`
([`schemas/validation-plan.schema.json`](../schemas/validation-plan.schema.json)) —
distinct from the plan, which is the intent. `passed: true` must never
carry a non-empty `failures` array (enforced in
`ValidationReceipt::validate`). Rust type:
`crate::contracts_abi::ValidationReceipt`.

## Manifest

`simplicio contracts-abi manifest` (`crate::contracts_abi::abi_manifest_json`)
prints the Runtime-owned slice of the federated manifest: schema ids, their
files, and an explicit `not_owned_here` list of the other four producers''
schema ids so a consumer can tell at a glance what this repo does and does
not assert semantics for. This is narrower than
`compatibility_matrix()`/`resolve_all_adapters()` in
`src/main_parts/chunk_11.rs`, which negotiates adapter *versions*
(mapper/dev-cli/prompt/loop/runtime); that mechanism i','docs/SEMANTIC_ABI_SPEC.md','ef64a0cec99ee9622065c218ae361a4af6d97e06fcc5ea2e79c11a486624fea0','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SESSION_BENCHMARKS_2026-06-05.md','project_doc','doc://simplicio-runtime/docs/SESSION_BENCHMARKS_2026-06-05.md','doc: Session summary — benchmark batteries & local-model engine (2026-06-05)','# Session summary — benchmark batteries & local-model engine (2026-06-05)

Index of the work done in this session. The substantive changes were committed
to `main` directly (per the standing "always main" policy); this document is the
single review entry point and links to the merged artifacts and raw evidence.

## What was done

### Runtime change (merged to main)
- **`force_all_resources` — mandatory full engine (v0.3.38).** `run`/`dev-cli`/
  `sprint` refuse to execute unless the full Simplicio stack is engaged (mapper +
  dev-cli fan-out + prompt + sprint + a model backend + indexed skills); degraded
  bypass ignored while forced; opt out via `--no-force-all-resources` /
  `SIMPLICIO_FORCE_ALL_RESOURCES=0`. Model flow satisfied by a local model **or**
  a configured remote backend. (`feat(runtime): force full-engine use…`)
- **Test isolation fix.** `with_no_provider_env` makes the chat-fallback tests
  hermetic to ambient provider env vars (removes a CI flake).

### Benchmark batteries (report + PDF + raw evidence, merged to main)
- Report: `docs/COMPETITIVE_BENCHMARK.md` (+ self-contained `…​.pdf`).
- Evidence: `docs/evidence/agent-battery-2026-06-05/`.
- Harnesses: `scripts/battery-deepseek-v4-flash.py`,
  `scripts/humaneval-top-open-models.py`, `scripts/humaneval-local-qwen.py`,
  `scripts/humaneval-local-fullengine-retry.py`, `scripts/wavespeed-media.py`.

| Battery | Result |
|---|---|
| A — Simplicio × Hermes × OpenClaw (same model) | all 6/6; Simplicio fastest (43.6 s), fewest measured tokens (2 493), 3.4 MB footprint, deterministic sha256 edits |
| B — HumanEval vs top-10 open models (flash, n=15) | runtime loop lifts deepseek-v4-flash 86.7% → 93.3% |
| C — WaveSpeed media | image 6.8 s + 5 s video 35 s, ~$0.05 |
| D — DeepSeek V4 Pro + forced engine (n=15) | v4-pro raw 100%; force-engine active |
| **E — HumanEval 164, with vs without a paid LLM** | **With V4 Pro: 95.1% (156/164) vs raw 91.5%; Without any paid LLM (local 4B, $0): 56.1% (92/164), zero tokens** |
| **F — native engine on the LOCAL in-process model ($0)** | `simplicio reason` + `dev-cli` run the local model in-process (no `llama-server`); with `SIMPLICIO_TEST_CMD` the verify iterate-until-green loop reaches `verify:passed` on a clean, oracle-verified result — all $0 |

### Headline
- The same runtime spans the cost/quality spectrum: a 4B local model at **$0**
  clears **56.1%** of HumanEval single-shot; the paid DeepSeek V4 Pro backend
  takes it to **95.1%**, beating the raw model (91.5%) via iterate-until-green.

## Known blockers (operator/account side, not code)
- **GitHub Actions** jobs fail in ~2 s with `runner_id:0`, no logs — an Actions
  minutes/billing/runner problem on the private repo. CI cannot go green until
  this is resolved in account settings.
- **Distribution:** the `main-latest` prerelease is stale (frozen ~2026-06-02)
  because the release workflow shares the same broken runners; no stable `v*`
  release / PyPI wheels yet (need a `v*` tag + `PYPI_API_TOKEN`).

## Notes
- Leaked API keys (OpenRouter + WaveSpeed) appeared in chat during this session —
  treat both as compromised and rotate.','docs/SESSION_BENCHMARKS_2026-06-05.md','b02facdcb1c5a05934e389c57077babba63153458560fc602274d8431ac7cae5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIGNING.md','project_doc','doc://simplicio-runtime/docs/SIGNING.md','doc: Code-signing & notarization runbook (desktop installers)','# Code-signing & notarization runbook (desktop installers)

How to produce **trusted, distribution-ready** Simplicio desktop installers on
macOS and Windows. The packaging itself (electron-builder targets, the Rust-binary
bootstrap) already works; this doc covers only the **signing** that stops Gatekeeper
(macOS) and SmartScreen (Windows) from blocking a non-programmer''s first launch.

> Source of truth for the config: `apps/simplicio-desktop/package.json` (`build`),
> `apps/simplicio-desktop/electron/entitlements.mac.plist`,
> `apps/simplicio-desktop/scripts/notarize.cjs`, and the (currently disabled)
> `.github/workflows/desktop-build.yml.disabled`.

Verify your environment at any time with:

```bash
scripts/verify-signing.sh            # checks env + (if given) a built artifact
scripts/verify-signing.sh path/to/Simplicio.app   # also verifies a built .app
scripts/verify-signing.sh path/to/Simplicio.exe   # also verifies a built .exe
```

---

## 1. macOS — Developer ID signing + notarization

**You need (user-side, one-time):**
- An **Apple Developer Program** membership ($99/yr).
- A **Developer ID Application** certificate (for the `.app`/`.dmg`) and, if you
  ship a `.pkg`, a **Developer ID Installer** certificate. Create them in
  *Certificates, Identifiers & Profiles*, export each as a password-protected
  `.p12`.
- An **App Store Connect API key** for notarization (Issuer ID, Key ID, and the
  `AuthKey_XXXX.p8`), **or** a notarytool keychain profile.

**CI secrets** (GitHub → Settings → Secrets and variables → Actions):

| Secret | What it is |
|---|---|
| `MACOS_CODESIGN_CERTIFICATE_P12_BASE64` | `base64 -i DeveloperIDApplication.p12` |
| `MACOS_CODESIGN_CERTIFICATE_PASSWORD` | the `.p12` export password |
| `MACOS_CODESIGN_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_API_KEY` | base64 of the `AuthKey_XXXX.p8` (or a file path in CI) |
| `APPLE_API_KEY_ID` | the Key ID |
| `APPLE_API_ISSUER` | the Issuer ID |

`notarize.cjs` already supports **either** an `APPLE_NOTARY_PROFILE` keychain
profile **or** the `APPLE_API_KEY` / `APPLE_API_KEY_ID` / `APPLE_API_ISSUER` trio,
and silently skips when neither is set — so an unsigned local build still succeeds,
it just won''t pass Gatekeeper.

**Entitlements** are already declared in `electron/entitlements.mac.plist`
(`allow-jit`, `allow-unsigned-executable-memory`, `disable-library-validation`,
`audio-input` — the last is required for the always-on voice mic). The hardened
runtime is on; do not remove `audio-input` or the mic dies under notarization.

**Local build + sign + notarize (on a Mac):**

```bash
cd apps/simplicio-desktop
export CSC_LINK=DeveloperIDApplication.p12
export CSC_KEY_PASSWORD=********
export APPLE_API_KEY=AuthKey_XXXX.p8 APPLE_API_KEY_ID=XXXX APPLE_API_ISSUER=...-...-...
npm run dist:mac
# verify:
codesign --verify --deep --strict --verbose=2 "dist/mac/Simplicio.app"
spctl --assess --type execute --verbose "dist/mac/Simplicio.app"   # → "accepted, source=Notarized Developer ID"
xcrun stapler validate "dist/Simplicio-<ver>-arm64.dmg"
```

> arm64 and x64 are built **separately** (two DMGs) on purpose — `node-pty` N-API
> prebuilts can''t be `lipo`-merged into a universal binary. That is expected, not a bug.

---

## 2. Windows — Authenticode signing

**You need (user-side):** a **code-signing certificate** (usually OV; EV is optional,
but no longer gives an automatic SmartScreen bypass) from a CA (DigiCert, Sectigo, …), exported as a
password-protected `.pfx`. EV certs typically live on a hardware token / cloud HSM —
for those, use the CA''s signing tool (e.g. an Azure Trusted Signing / `signtool`
with a CSP) rather than a local `.pfx`.

**CI secrets:**

| Secret | What it is |
|---|---|
| `WIN_CSC_LINK` | base64 of the `.pfx` (or a path in CI) |
| `WIN_CSC_KEY_PASSWORD` | the `.pfx` password |

**Enable signing:** in `apps/simplicio-desktop/package.json`, set the Windows
build''s `signAndEditExecutable: true` (it is `false` today — installers build but
are **unsigned**). electron-builder reads `CSC_LINK` / `CSC_KEY_PASSWORD`
(or `WIN_CSC_*`) automatically.

**Important (current Microsoft behavior):** a valid Authenticode signature proves
publisher integrity, but **SmartScreen reputation is still built over time**.
Buying EV purely to avoid the warning is no longer justified; Microsoft now treats
EV and OV the same for SmartScreen reputation bootstrap.

```bash
cd apps/simplicio-desktop
set CSC_LINK=cert.pfx
set CSC_KEY_PASSWORD=********
npm run dist:win
# verify:
signtool verify /pa /v "dist\Simplicio Setup <ver>.exe"
```

---

## 3. Turn CI back on

`.github/workflows/desktop-build.yml.disabled` already contains the multi-OS build
logic. To use it: rename off the `.disabled` suffix, seed the secrets above, and
make sure **GitHub Actions billing** is healthy (see the repo note — jobs that fail
in <11s with no runner = a billing/quota stop, not a code error). macOS jobs need a
real macOS runner (`macos-14` arm64 + `macos-13` x64); there is no cross-compile for
Apple notarization.

A pre-build guard (`scripts/verify-signing.sh --require`) fails fast in CI when the
signing env for the target OS is incomplete, so a release never silently ships
unsigned.

---

## Quick reference — what blocks distribution today

| Platform | Status | Unblock |
|---|---|---|
| macOS | builds **unsigned** | Apple cert + API key → secrets above |
| Windows | builds **unsigned** (`signAndEditExecutable:false`) | code-signing cert → `WIN_CSC_*` + flip the flag |
| Linux | ready (AppImage/deb/rpm) | optional repo GPG signing only |
| CI | `desktop-build.yml.disabled` | re-enable + Actions billing + secrets |','docs/SIGNING.md','b9f4384244bee7ed361b935ad099512f9900118b615c7b8b7f069c22ff5c4946','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/simplicio-loop-compliance.md','project_doc','doc://simplicio-runtime/docs/simplicio-loop-compliance.md','doc: Simplicio Loop Compliance','# Simplicio Loop Compliance

> **O loop É o motor de execução do simplicio-runtime.**
> Não há mais divisão upstream/downstream — simplicio-loop É EMBUTIDO no runtime
> como capability obrigatória. Toda execução do runtime passa pelo loop de convergência.
>
> Issue: [#2779](https://github.com/wesleysimplicio/simplicio-runtime/issues/2779)
> Contrato versionado: [`LOOP-CONTRACT.md`](../LOOP-CONTRACT.md)
> Port nativo: [`src/loop_contract.rs`](../src/loop_contract.rs)

---

## 1. Inversão de Dependência — A Mudança Radical

**ANTES (removido):** simplicio-loop era um super-plugin OPCIONAL que podia usar
simplicio-runtime como executor. Duas doutrinas competiam — drift garantido.

**AGORA (unificado):** simplicio-loop é parte INTEGRANTE do simplicio-runtime.
Não há mais divisão "upstream" vs "downstream". O loop **é** o motor de execução
do runtime. Toda operação — run, edit, validate, install, MCP — passa pelo loop.

| Era | Relação | Problema |
|---|---|---|
| **Pré-inversão** | simplicio-loop: super-plugin opcional ↔ simplicio-runtime: executor opcional | Duas doutrinas = drift |
| **Pós-inversão** | **simplicio-runtime + simplicio-loop (unificados)** — loop é o motor de execução | Doutrina única, zero drift |

---

## 2. O que mudou (Princípios Atualizados)

### 2.1 Dependência única e mandatória

simplicio-loop não é mais opcional, instalável, ou um skill externo. Ele é
**built-in** no runtime, como capability obrigatória registrada no
`capability_catalog` com o id `simplicio-loop`.

### 2.2 Regras de execução obrigatórias

- **`simplicio run`** SEMPRE invoca o loop internamente — não existe `run` sem loop.
- **`simplicio edit --evidence`** SEMPRE passa pelo gate de evidência do loop
  antes de liberar a escrita.
- **Toda task** tem `max_iterations` e uma promessa de evidência obrigatória
  no contrato.
- **`simplicio validate`** SEMPRE verifica o contrato do loop
  (`LOOP-CONTRACT.md`) como parte da validação — falha se o contrato estiver
  ausente ou desatualizado.
- **`simplicio install --global`** agora instala os 5 skills satélites do
  simplicio-loop automaticamente (ver seção 7).
- O runtime usa os skills do simplicio-loop como os **5 satélites obrigatórios**
  para toda execução de convergência.

### 2.3 Capability obrigatória na catalog

No `capability_catalog` do runtime, `simplicio-loop` passa de capability opcional
para **obrigatória**, com prioridade máxima:

```json
{
  "id": "simplicio-loop",
  "kind": "builtin",
  "mandatory": true,
  "priority": 0,
  "description": "Motor de convergência — loop obrigatório do simplicio-runtime",
  "contract": "LOOP-CONTRACT.md",
  "port": "src/loop_contract.rs"
}
```

---

## 3. Doutrina Unificada

A separação antiga entre duas doutrinas é eliminada. Agora existe **uma** doutrina:

| Doutrina Única | Fluxo | Mecânica |
|---|---|---|
| **simplicio-runtime + simplicio-loop** | `discover → anchor → orient → execute → verify → merge → learn` | Gates mecânicos EMBUTIDOS no runtime (task anchor, journal, watcher, evidence gate, loop_contract) |

Nenhum subsistema do runtime pode executar um loop autônomo paralelo — todo
fluxo de convergência é o **mesmo** fluxo do loop, implementado nativamente.

---

## 4. Mapeamento de Gates (1:1)

Gates que antes eram "do loop" agora são gates **do runtime**, diretamente
acessíveis e executados em toda operação:

| Gate | Implementação no Runtime | Status |
|---|---|---|
| **task anchor** (AC congelados, drift guard, done gate) | `simplicio deliver` acceptance gate (#251) + `src/loop_contract.rs` | **Built-in** |
| **watcher challenge** (verificação independente) | run-verification/dogfood (#252) | Built-in |
| **journal/stall** (attempt memory, anti-oscilação) | `trajectory` + loop_journal nativo | Built-in |
| **promise + evidence** | delivery certificate (#255) + evidence gate obrigatório | Built-in |
| **evidence gate** | Gate que Toda `simplicio edit --evidence` e `simplicio run` atravessam | **Obrigatório** |

---

## 5. Oráculo Dual (Dual Oracle)

Antes: oráculo dual entre Python (simplicio-loop) e Rust (simplicio-runtime).
Agora: não há mais dois repositórios para comparar. O oráculo dual é
**intra-runtime**: o port Rust puro vs a implementação integrada, ambos no
mesmo repositório.

| Port Puro (Rust, referência) | Implementação Integrada | Estado Compartilhado | Status |
|---|---|---|---|
| `src/loop_contract.rs` (pure functions) | Motor de convergência interno do runtime | `.tasks/` state + ledger | ✅ Dual oracle verde |

O teste de oráculo dual roda sem dependência externa — não precisa mais de
`$SIMPLICIO_LOOP_REPO` porque o loop foi incorporado.

---

## 6. Impacto no MCP

As **10 MCP tools** expostas pelo runtime (registradas via `simplicio mcp register`)
agora SEMPRE passam pelo **loop gate** antes de executar:

1. **Toda tool MCP** → invoca `loop_contract::gate_decision` primeiro
2. **Se o gate bloqueia** → a tool retorna erro com a razão do gate
3. **Se o gate libera** → a tool executa normalmente, mas com evidência obrigatória
   registrada no ledger do loop

Isso garante que mesmo chamadas via MCP (Claude, Cursor, Windsurf, Kiro, Gemini,
Codex, VS Code, etc.) respeitem o contrato do loop.

---

## 6.1 Closure gate — PR to `main` with details

O fluxo não termina em branch solta. Toda mudança deve fechar como **PR para
`main`** com o resumo explícito de:

- o que mudou;
- como foi validado;
- onde estão a evidência e os recibos;
- qual risco ou gap restante ficou aberto, se houver.

Se o fluxo travar antes desse fechamento, aplique a regra anti-wedge: re-anchor,
re-validar ou escalar pelo loop; não ficar girando em vazio.

---

## 7. Satélites Obrigatórios (5 skills do simplicio-loop)

O runtime mantém 5 skills do simplicio-loop como satélites obrigatórios,
instalados automaticamente por `simplicio install --global`:

| # | Skill | Função |
|---|---|---|
| 1 | **loop-anchor** | Task anchor: AC congelados, drift guard, done gate |
| 2 | **loop-watcher** | Verificação independente / watch','docs/simplicio-loop-compliance.md','ac3b32945a7f1fc46d353ce3cfafca2b4d1c76eba5e7d0ecd48ca09ba3cc8ef6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_AGENT_CAPABILITY_CONTRACT.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_AGENT_CAPABILITY_CONTRACT.md','doc: Simplicio Agent — Capability Contract','# Simplicio Agent — Capability Contract

> Contrato canônico para Hermes/Simplicio agents. Ler antes de executar qualquer tarefa.

## Regra de absorção total
- Conhecer e usar o Runtime, banco neural, fast stack Rust, Tokio, catálogo de comandos e inventário de skills.
- Consultar o índice abaixo e carregar o SKILL.md completo apenas quando a tarefa acionar aquela skill.

## Fluxo obrigatório
1. Orientar: `simplicio runtime map --repo <repo> --for-llm markdown`.
2. Memória: `simplicio memory <query>`; contexto amplo: `simplicio memory all`.
3. Executar via CLI Simplicio; MCP é fallback.
4. Editar: `simplicio edit --plan <plan.json>`.
5. Validar com `simplicio validate` e testes reais.
6. Evidenciar com receipts; claims `MEASURED|` ou `UNVERIFIED|`.

## Potência operacional
- Runtime: schema registry, action gate, edit, validate, evidence, memória e fan-out.
- Tokio: paralelismo assíncrono; serializar apenas operações no mesmo arquivo/contrato.
- Fast stack: HAVE_RUST, orjson, msgspec, uvloop, tiktoken e h2; verificar sempre.
- Banco neural: SQLite + FTS5 + vector quando disponível; seeds + migrations.
- Economia: cache, mapas compactos, edição determinística, modelo local antes de remoto.
- Qualidade: funciona, não só compila; não declarar conclusão sem evidência.

## Comandos canônicos
```text
simplicio doctor --json
simplicio runtime map --repo <repo> --for-llm markdown
simplicio memory <query>
simplicio edit --plan <plan.json> --repo <repo>
simplicio validate "<task>" --repo <repo>
simplicio run "<task>" --repo <repo>
simplicio contracts smoke --json
simplicio evidence show --run-id <id>
simplicio agents delegate "<goal>"
simplicio shell -- <command>
```

## Skills
Índice gerado de **157 skills** em `~/.simplicio_agent/skills/`. O índice é persistido na memória neural; o procedimento completo permanece no SKILL.md.

| Skill | Descrição | Caminho |
|---|---|---|
| `apple` | Manage Apple Notes via memo CLI: create, search, edit. | `.simplicio_agent/skills/apple/apple-notes/SKILL.md` |
| `apple` | Apple Reminders via remindctl: add, list, complete. | `.simplicio_agent/skills/apple/apple-reminders/SKILL.md` |
| `apple` | Track Apple devices/AirTags via FindMy.app on macOS. | `.simplicio_agent/skills/apple/findmy/SKILL.md` |
| `apple` | Send and receive iMessages/SMS via the imsg CLI on macOS. | `.simplicio_agent/skills/apple/imessage/SKILL.md` |
| `asolaria-act-halting` | Adaptive Computation Time — decide quando parar de iterar com base em confiança + evidência real. Economiza tokens sem fabricar saída. | `.simplicio_agent/skills/asolaria-act-halting/SKILL.md` |
| `asolaria-agent-table` | Agent definition table — agents como dados. Describe roles, prerequisites, toolsets, evidence, and deliverables in one table. | `.simplicio_agent/skills/asolaria-agent-table/SKILL.md` |
| `asolaria-consolidation` | Karpathy-style consolidation: compila observações brutas em páginas markdown no fim da sessão e registra lessons duráveis. | `.simplicio_agent/skills/asolaria-consolidation/SKILL.md` |
| `asolaria-patterns` | Port dos padrões Asolaria (JesseBrown1980) para o Simplicio Runtime como primitivas determinísticas testáveis — N-Nest cosign/corrective gate, HRM two-level planner, BEHCS-256 supervisor federado. | `.simplicio_agent/skills/asolaria-patterns/SKILL.md` |
| `asolaria` | Monitorar diariamente os repositorios de JesseBrown1980/Asolaria, extrair conceitos, e integrar melhorias no ecossistema Simplicio. | `.simplicio_agent/skills/asolaria/asolaria-ecosystem-monitor/SKILL.md` |
| `autonomous-ai-agents` | Delegate coding to Claude Code CLI (features, PRs). | `.simplicio_agent/skills/autonomous-ai-agents/claude-code/SKILL.md` |
| `autonomous-ai-agents` | Delegate coding to OpenAI Codex CLI (features, PRs). | `.simplicio_agent/skills/autonomous-ai-agents/codex/SKILL.md` |
| `autonomous-ai-agents` | Configure, extend, or contribute to Hermes Agent. | `.simplicio_agent/skills/autonomous-ai-agents/hermes-agent/SKILL.md` |
| `autonomous-ai-agents` | Workflow e integração MCP+CLI do Simplicio como camada de execução do Hermes: Hermes = cérebro, Simplicio = mãos. | `.simplicio_agent/skills/autonomous-ai-agents/hermes-simplicio-hybrid/SKILL.md` |
| `autonomous-ai-agents` | Delegate coding to OpenCode CLI (features, PR review). | `.simplicio_agent/skills/autonomous-ai-agents/opencode/SKILL.md` |
| `autonomous-ai-agents` | Use when you want to cut agent input-token cost by rendering bulky context as dense PNG pages via pxpipe, especially for Claude Fable 5 or GPT 5.6, while keeping exact-string risk out of the image path. | `.simplicio_agent/skills/autonomous-ai-agents/pxpipe/SKILL.md` |
| `browser-harness` | Direct browser control via CDP. Use when the user wants to automate, scrape, test, or interact with web pages. Connects to the user''s already-running Chrome. | `.simplicio_agent/skills/browser-harness/SKILL.md` |
| `browser-harness` | Create and configure Discord servers, categories, channels, and messages via Playwright browser automation. Covers login flow, DOM interaction patterns specific to Discord''s React UI, and known pitfalls. | `.simplicio_agent/skills/browser-harness/discord-server-setup/SKILL.md` |
| `close-autopilot-issues` | Close Autopilot v5 issues and create new feature issues | `.simplicio_agent/skills/close-autopilot-issues/SKILL.md` |
| `code-review` | Comprehensive security and correctness audit of a branch''s changes. Use for thermo nuclear, thermonuclear, or deep review requests, or branch/PR diff audits focused on bugs, breaking changes, security issues, devex regressions, and feature- | `.simplicio_agent/skills/code-review/thermo-nuclear-review/SKILL.md` |
| `code-review` | Launch both thermo-nuclear review subagents in parallel, then synthesize their findings. Use for thermos, double thermo review, or combined bug/security and code-quality branch audits. | `.simplicio_agent/skills/code-review/thermos/SKILL.md` |
| `computer-use` | / | `.simplicio_agent/skills/computer-use/SKILL','docs/SIMPLICIO_AGENT_CAPABILITY_CONTRACT.md','918c8f1edfddd477ffed587a9904f47690c738fd0816fec61846d564027aebdf','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_COMMAND_SURFACE.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_COMMAND_SURFACE.md','doc: Simplicio Runtime — Complete Command Surface','# Simplicio Runtime — Complete Command Surface

Generated from `simplicio --help` (runtime 3.5.0). Agents must consult this file before inventing a command; use `simplicio <command> --help` for the live contract.

Total documented command signatures: **112**.

```text
simplicio doctor [--json] [--repo <path>] [--repair] [--capabilities]
simplicio toolchain [--json]
simplicio endpoints compare --web <dir> --api <dir> [--agents-dir <dir>] [--format markdown|json]
simplicio pr status|open|update-evidence --repo <path> [--json]
simplicio precedent init|index|status|search|check --repo <path> [--from-runs <path>] [--text <query>] [--precedent <id-or-path>|--issue <n>] [--top N] [--json]
simplicio issue-worktree prepare|status|cleanup --repo <path> [--issue N] [--run-id ID] [--force] [--json]
simplicio issue-factory run --repo <path> --source github [--max-parallel N] [--reuse-precedents] [--evidence] [--json]
simplicio cloud-watch [--repo <path>] [--json]
simplicio evidence web --flow <name> --base-url <url> [--json]
simplicio issue-factory discover|claim|pr-handoff|comment --repo <path> [--json]
simplicio runtime map [--json|--for-llm markdown|--for-llm json|--for-llm toon] [--repo <path>]
simplicio infra-advanced [--json]   experimental preview for module hot-reload
simplicio contracts smoke [--json] [--repo <path>]
simplicio runtime smoke [--json] [--repo <path>]
simplicio exec-graph run|status|define|validate|dot [--json] [--repo <path>]
simplicio map --repo <path> [--json]
simplicio plan "<task>" --repo <path> [--agents N] [--json]
simplicio decide "<task>" --repo <path> [--json]
simplicio run "<task>" --repo <path> [--agents N] [--local|--remote] [--evidence]
simplicio sprint <sprint-path-or-text> --repo <path> [--agents N] [--evidence] [--pr] [--watch] [--reuse-precedents]
simplicio sprint send --issue <n> --repo <path> --reuse-precedents --evidence --json
simplicio workflow list|run|status|watch|events|resume|retry|evidence|failures [<workflow_id>] [--repo <path>] [--view compact|detail] [--json]
simplicio issue-factory mvp --repo <path> --fixture examples/issue-factory/mvp [--reuse-precedents] [--evidence] [--json]
simplicio edit --plan <plan.json|-> [--file <path>] [--repo <path>] [--dry-run] [--review] [--commit <msg>] [--json]
simplicio edit ''{"file":"...","operations":[...]}'' [--dry-run] [--review] [--commit <msg>] [--json]
simplicio edit --plan <plan.json|-> [--build <cmd>] [--render <cmd>] [--assert <cmd>] [--check <cmd>] [--repo <path>] [--review] [--commit <msg>] [--json]
simplicio exec "<simplicio subcommand>"              gated runtime subcommand router; no raw shell
simplicio runtime map [--json | --for-llm] [--repo <path>]
simplicio self-mutation status|maintenance|handoff [--repo <runtime>] [--json]
simplicio agents status [--agents N] [--machine-profile <name>] [--json]
simplicio agents delegate <goal>|--file tasks.json | children | pause|resume|interrupt [--json]
simplicio dev-cli "<task>" --repo <path> [--target <file>] [--stack <stack>] [--remote] [--json]
simplicio model status|check <file>|smoke [--json]
simplicio benchmark run|measure [--sample] [--json]   (run = measured timings; --sample = fixture rows)
simplicio benchmark savings [--json]
simplicio issue-factory benchmark --repo <path> --fixture examples/issue-factory [--json]
simplicio issue-factory metrics --repo <path> --last 10 [--json]
simplicio savings report --repo <path> [--user <id>] [--team <id>] [--model <id>] [--proof-kind <kind>] [--json]
simplicio savings compare --with-simplicio <run-dir> --without-simplicio <baseline.json> [--proof-kind replayed|measured|benchmark] [--json]
simplicio savings record --spent <N> --baseline <N> [--source codex] [--task <desc>] [--model <id>] [--provider <id>] [--proof-kind measured|estimated|replayed|benchmark] [--json]
simplicio savings prove [--repo <path>] [--run-id <id>] [--json]
simplicio savings pricing [--model <provider/model>] [--json]
simplicio savings whoami [--repo <path>] [--json]
simplicio savings export --format json|csv|markdown [--repo <path>] [--json]
simplicio savings dashboard --repo <path> [--json]
simplicio savings sync --dry-run [--endpoint <url>] [--repo <path>] [--json]
simplicio savings sync --yes --endpoint <url> [--repo <path>] [--json]
simplicio measure tokens [--text <text> | --file <path>] [--output-text <text>] [--model <id>] [--json]   offline cl100k_base BPE token counter, no network (#3160)
simplicio shell [compact] [--json] [--no-spill] [--repo <path>] -- <cmd> [args...]  supervised external command runner
simplicio compact text <text> [--json] | compact file <path> [--output <path>|--write] [--json]
simplicio packages update [--dry-run] [--json] | bundle [--json]
simplicio update auto status|check [--window morning|night] [--json] | update check|apply|rollback|sign <sha256> [--json]
simplicio cron status|list|add|tick|run|pause|resume|remove [--json]
simplicio login google [--json] | auth status [--json] | logout [--json]
simplicio license status [--json]
simplicio telegram send "<msg>" | report | listen | status [--json]
simplicio discord send "<msg>" | guilds | channels | messages | server-info | roles | pins | member-info | search-members | thread | pin | unpin | delete | add-role | remove-role | status [--json]
simplicio browser status|navigate <url>|snapshot|click|type|scroll|back|press|images|vision|console [--json]
simplicio browser connect --cdp <http://127.0.0.1:9222>|disconnect|cdp --method <CDP.method>|dialog --action accept|dismiss [--json]
simplicio computer-use status|capture|click|double_click|right_click|drag|scroll|type|key|set_value|wait|list_apps|focus_app [--json]
simplicio validate "<task>" --repo <path> [--json]
simplicio diagnostics --repo <path> [--toolchain rustc|clippy|tsc|pytest|pyright] [--from-file <log>] [--json]
simplicio trajectory record <session> --intent <i> --outcome green|red|blocked [--exec-command <c>] [--task-kind <k>] [--errors N] [--warnings N]
simplicio trajectory show <session> [--repo','docs/SIMPLICIO_COMMAND_SURFACE.md','850bea0f2267c909d0631d628ecf6dafe7f6c31e3477a41e76fc9dd02e603e8b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_CORE_BUILD.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_CORE_BUILD.md','doc: Simplicio Core build — the real CLI already is the product','# Simplicio Core build — the real CLI already is the product

**Verified 2026-06-27** (toolchain rustc/cargo 1.94.1). Corrects a material error in the earlier
inventory ("no release binary built / won''t build"): that referred to a **missing pre-built artifact**,
NOT a compile failure. **The monolith compiles fine.**

## The lean build works (no C/C++ toolchain)

```bash
cargo check --no-default-features        # EXIT 0 · 0 errors · ~2 min · 8524 warnings (dead-code, non-blocking)
cargo build --no-default-features        # EXIT 0 · produces target/debug/simplicio (227 MB debug)
```

The default build is provider/model-neutral and runs in `deterministic-only` inference mode; it leaves
`in-process-llm` disabled. `--no-default-features`
drops `in-process-llm` (llama.cpp), `tui`, `async-runtime`, `rich-repl`,
`mic-capture` — so **no C/C++ toolchain (cmake/clang) is needed**. The 8524 warnings are the known
dead-code debt (199 orphan files etc.), not errors.

Shippable product build (VERIFIED 2026-06-27):

```bash
cargo build --release --no-default-features   # lean, stripped/LTO via [profile.release]
# -> target/release/simplicio = 22 MB (vs 227 MB debug). EXIT 0.
# Verified: SIMPLICIO_BIN=./target/release/simplicio python3 scripts/exercise-mcp-serve.py -> 6/6
#           (initialize, tools/list, gate, map, edit, edit-persisted; workspace sandbox active).
```

## The MCP product is already there: `simplicio serve --mcp --stdio`

The real binary exposes the full deterministic tool surface over MCP stdio (verified handshake):

| tool | description (from the live server) |
|---|---|
| `simplicio_map` | compressed repo orientation map (token-saving) |
| `simplicio_memory` | recall from neural memory (FTS + vector) |
| `simplicio_edit` | deterministic mechanical edit plan (zero LLM tokens for bodies) |
| `simplicio_gate` | classify an action''s risk through the action gate |
| `simplicio_validate` | run the deterministic validation pipeline |
| `simplicio_run` | route a task through the runtime spine (gate→bridge→evidence) |

Other verified commands: `doctor` (`simplicio.progress/v1` + health), `license status`
(`simplicio.license/v1`, state `free_missing`), `memory status` (`simplicio.memory-backend/v1`,
sqlite-fts5). The full surface (`--help`): doctor, runtime map, edit, plan, run, sprint, workflow,
agents, model, benchmark, savings, cron, login, license, telegram/discord, browser, computer-use, …

## Exercise it (connected flow)

```bash
python3 scripts/exercise-mcp-serve.py
# == 6/6 checks passed == (initialize, tools/list, gate, map, edit, edit-persisted)
```

## What this means for the product

- **One harness, not two.** The product is the real `simplicio serve --mcp` (lean build) — it already
  has everything. The earlier standalone `crates/simplicio-mcp` experiment was a **second, parallel MCP
  server**; it has been **removed** so there is exactly one harness to ship, document, and support.
- Nothing of value was lost: the only fix that lived in that crate — the **workspace-root sandbox** —
  was already ported into the real serve edit handler before removal (see below, now DONE).

## Workspace-root sandbox — DONE (was the one open adjustment)

The real `simplicio_edit` MCP path now enforces a **workspace-root sandbox** (a closed binary writing to
a host repo must not be coaxed outside it): `mcp_normalize_path()` + `mcp_edit_sandbox()` reject any plan
whose target file escapes the repo root. Verified live — in-repo edits apply; `/etc/passwd` and
`../escape` are blocked. Tracked under epic #2671 / #2674.

Refs: `docs/SIMPLICIO_PLUGGABILITY_SURVEY.md`, `docs/SIMPLICIO_GTM_STRATEGY.md`.','docs/SIMPLICIO_CORE_BUILD.md','cc4f0cba02c80de3b52378626b4f5764cbfe046eca833586be6b25baae7a22ee','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_FUNCIONALIDADES_E_FLUXOS.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_FUNCIONALIDADES_E_FLUXOS.md','doc: Simplicio — Funcionalidades e Fluxos (para revisão)','# Simplicio — Funcionalidades e Fluxos (para revisão)

Documento de revisão. Tudo enumerado para você mandar observações por número
(ex.: "F12 está errado", "C3 falta passo de X", "Fluxo 2 passo 4 inverter").

- **F#** = Funcionalidade
- **C#** = Cenário de solicitação até a entrega
- Passos de fluxo numerados dentro de cada cenário

Estado de cada item: ✅ testado ao vivo · 🟡 existe, não validei ao vivo · 🔴 gap conhecido

Princípio do produto (confirmado com você):
- O Simplicio **não tem LLM própria**. Usa (a) o **modelo local** (qwen, $0) para
  trabalho mecânico, ou (b) **a LLM que o usuário já usa** (Claude/GPT/Gemini —
  a conta dele), com o Simplicio como camada obrigatória que corta tokens.
- O binário em Rust executa as tarefas, principalmente de programação.
- O fluxo é sempre: **o chat que o usuário pede** OU **pré-determinado** (automático,
  conforme a LLM vai mexendo, via hook/MCP).

---

## 1. Orientação e contexto (economia de entrada)

- **F1** `simplicio map` / `runtime map` — mapa comprimido do repositório em vez de
  despejar arquivos na LLM. Corta milhares de tokens de contexto. ✅
- **F2** `simplicio orientation` — guia de como a LLM deve usar o runtime na sessão. ✅ (`status`+`pack`, mmap_verified)
- **F3** `simplicio capabilities` — lista o que o runtime sabe fazer. ✅
- **F4** `simplicio intake` — captura/normaliza a solicitação inicial. ✅
- **F5** `simplicio welcome` — onboarding/primeiros passos. ✅
- **F6** `simplicio endpoints` — mapa de rotas/telas (via mapper). ✅ (`compare` nativo)

## 2. Memória neural (não re-derivar)

- **F7** `simplicio memory "<consulta>"` — recall do que já foi decidido (FTS + vetor),
  em vez de re-explicar à LLM. ✅
- **F8** `simplicio memory-db` — backend SQLite FTS5 da memória. ✅
- **F9** `simplicio memory-v` / `memory-v2` — memória vetorial (recall semântico). ✅ (`status`: FTS5 ok)
- **F10** `simplicio skill-memory` — skills armazenadas na memória neural. ✅
- **F11** `simplicio learn` — aprende com a interação (loop de aprendizado). ✅ (gera recipe de run)
- **F12** `simplicio trajectory` — registro/compressão de trajetória das execuções. ✅ (`suggest`)

## 3. Edição e código (zero token de escrita)

- **F13** `simplicio edit ''{…}''` — escrita mecânica de arquivo (replace, insert,
  append, delete_line…). A LLM decide, o Simplicio aplica. **Zero token.** ✅
- **F14** `simplicio dev-cli` — coding loop nativo em Rust (escreve, testa, itera até
  passar). É Rust, não o adapter Python. ✅ Resolve com `--target <arquivo>` +
  `SIMPLICIO_TEST_CMD`. Validado ao vivo: bug `a-b` → qwen local corrigiu sozinho →
  `verify:passed`, `cycles:1`, **0 tokens pagos**, 11,3s. (O stub anterior era falta
  do `--target`.)
- **F15** `simplicio run` — orquestra a tarefa: mapa + plano de validação + evidência
  ("skeleton"). Não aplica o código sozinho. ✅
- **F16** `simplicio decide` — decide a próxima ação para a tarefa. ✅
- **F17** `simplicio plan` — gera o plano de implementação. ✅
- **F18** `simplicio contracts` — contratos/critérios de aceite da tarefa. ✅ (`smoke`)

## 4. Chat e IA (modelo local ou a LLM do usuário)

- **F19** `simplicio chat` — chat que interpreta e age. Local-first; usa a LLM do
  usuário quando precisa do modelo grande. ✅ (inferência local validada)
- **F20** `simplicio reason` (`decide`) — raciocínio + ação gated (escolhe ação segura,
  confiança, próximo passo). ✅
- **F21** `simplicio advise` — sugestão proativa de melhoria. ✅
- **F22** `simplicio invoke` — invoca uma capacidade/skill específica. ✅
- **F23** `simplicio model` — seleciona modelo/provedor (local ou o do usuário). ✅

## 5. Validação e entrega (funciona, não só compila)

- **F24** `simplicio validate` — pipeline de validação progressiva. ✅ (plano gerado ao vivo)
- **F25** `simplicio evidence` — ledger de evidência (HBP, append-only, verificável). ✅ (`show --run-id`)
- **F26** `simplicio self-test` — autoteste do runtime. ✅ (5/5 checks)
- **F27** `simplicio diagnostics` — diagnósticos da execução. ✅ (rustc live: 0 erros)
- **F28** `simplicio doctor` — checa runtime, adapters, modelo local, repo. ✅
- **F29** `deliver` (DoD/aceitação) — só declara "entregue" quando roda e passa nos
  critérios; gera certificado. ✅ (`check` determinístico)

## 6. Segurança, portão e licença

- **F30** `simplicio gate classify` — classifica risco da ação antes de mutar
  (block/confirm/auto). ✅
- **F31** `simplicio security` — verificações de segurança. ✅ (251 crates via OSV; **fix Windows**: resolução do curl não usa mais path unix do `which`)
- **F32** `simplicio governor` — governa o loop autônomo (limites, freios). ✅ (`simulate`)
- **F33** `simplicio license` — emitir/ativar/checar assinatura (ed25519 offline). ✅
- **F34** `simplicio login` — autentica o provedor de IA do usuário / a conta. ✅ (`auth status`; login Google interativo não exercitado)
- **F35** `simplicio pairing` — pareamento de dispositivo/sessão. ✅ (`list`)

## 7. Agentes e orquestração (fan-out local 64→600)

- **F36** `simplicio agents` — gerencia o exército de agentes locais. ✅ (`status`: 37 ativos)
- **F37** `simplicio parallelism` — controla o paralelismo (semáforo, escala). ✅
- **F38** `simplicio sprint` — workflow multi-agente de entrega de sprint. ✅ (run completo com evidence/ledger/final-report; exige modelo local resolvível no repo)
- **F39** `simplicio task` — fila/estado de tarefas. ✅ (`normalize`)
- **F40** `simplicio cron` — agendamento de jobs. ✅ (`status`)

## 8. Ação no mundo (navegação, computer-use)

- **F41** `simplicio browser` — navega, lê, preenche, posta; missões em lote com
  evidência por passo. ✅ (navigate+snapshot ao vivo em example.com)
- **F42** `simplicio computer-use` — controle de GUI (ver tela, agir). ✅ (`status` responde; ações reais gated por policy — default disabled)
- **F43** `simplicio integrations` — conectores externos. ✅ (`audit`)
- **F44** `simplicio telegram` — gateway Telegram (e outros: discord, whatsapp…). ✅ (estrutural: `status` gracioso sem credenciais; envio real precisa de b','docs/SIMPLICIO_FUNCIONALIDADES_E_FLUXOS.md','189780e446da78e1ff1a7d1a5f3af1518dc548c61b4a6ecb3eaddf1d3b540c5d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_GROWTH_PLAN.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_GROWTH_PLAN.md','doc: Simplicio Growth Plan — live reports, WOW entrance, promo video, Claude container','# Simplicio Growth Plan — live reports, WOW entrance, promo video, Claude container

Four initiatives requested 2026-06-17. The savings ledger
(`.simplicio-loop/ledger/savings-events.jsonl`) already captures every dimension we
need; the dashboard (`simplicio web-dashboard`, :9119, compiled-in React app +
the living "ser vivo" layer) is the surface. Default English, 15 languages
(see [[site-branding-and-i18n]]). Brand = neon-green on dark (logo).

## 1. Comprehensive live reports (every dimension, live)

The ledger event already has the raw fields — this is aggregation + UI, not new
collection:

| Report axis | Ledger field |
|---|---|
| by conversation / task | `task.id`, `task.title`, `task.source` |
| by session | `simplicio.run_id`, `actor.provider_session` |
| by hour / day / month | `timestamp` (ISO) + `timezone` |
| by LLM | `llm.provider` + `llm.model` |
| by repository | `repo.remote` / `repo.path` / `repo.branch` |
| by IDE / surface | `llm.surface` (shell, shell-compact, vscode, …) |
| by user / team | `user.*`, `team.*` |
| tokens / cost | `tokens.saved_total/baseline_total/actual_total`, `cost.*` |

Phases:
- **R1** — extend `/api/summary` (savings_analytics) to group by **time bucket**
  (hour/day/month) and by **session/conversation/IDE**, returning per-axis series.
- **R2** — dashboard: add an axis selector + drill-down; reuse the 7 chart slots,
  add a time-bucket toggle and a "by session" + "by IDE" view. Live refresh (the
  app already polls `/api/summary`).
- **R3** — exportable reports (`simplicio savings report --by <axis> --period <h|d|m> --json|--csv`).
- **R4** — "live" = SSE/poll push so numbers move as events land (heartbeat already
  reacts to KPI deltas via living.js).

## 2. WOW entrance + re-engagement + data persistence

- **WOW intro** — a one-shot organism "boot" sequence on first paint: the logo''s
  hexagon-S draws itself (stroke-dashoffset), the heart starts beating, KPIs count
  up from 0, synapses ignite. ~2.5s, then settles into the live dashboard.
  Skippable, plays once per session (localStorage flag), `prefers-reduced-motion`
  honored. Lives in `assets/dashboard/living.js` + a `boot.css`.
- **Re-deliver the URL when they close it** — options (pick per channel):
  1. `simplicio` CLI prints the URL on every run footer + a `simplicio dashboard`
     alias that reopens it.
  2. Desktop/menubar tray entry "Open dashboard" (when desktop app present).
  3. Opt-in: email/Telegram a daily "your savings" digest with the link (uses the
     existing gateways) — requires `privacy.sync_opt_in`.
- **Data survives updates (guarantee)** — user data lives under `~/.simplicio-loop/`
  and the repo''s `.simplicio-loop/ledger/`. Updates replace only the **binary**
  (`~/.local/bin/simplicio`), never `~/.simplicio-loop/`. Add a test/assertion that the
  installer + `simplicio update` never touch `.simplicio-loop/ledger/` or
  `~/.simplicio-loop/runtime.toml` / `action-gate-mode`. Document the contract.

## 3. Remotion promo video (60s, "best token-saving system")

Backend: Remotion (React→MP4, deterministic) per the video epic (#240/#243).
- 60s, **scene cut every 2–3s** (≈24 beats), each beat: one claim on screen + a
  matching visual (real terminal capture, a chart, a before/after token count).
- Narrative arc: hook ("LLMs burn tokens") → the Simplicio loop (map/recall/edit/
  gate) → real savings numbers from the ledger → the living dashboard → CTA
  (`curl … | sh`). English VO + 15-language subtitles (SRT/ASS, #248).
- Pull REAL numbers from the savings ledger so the demo isn''t fabricated.
- Render via the Coding Loop (#236) so it''s reproducible; store under
  `apps/` or `site/assets/`.

## 4. Run Simplicio inside the Claude container

Goal: a user who signs into Claude gets Simplicio working — even in Claude Desktop
"cloud" sessions.
- **Vector A — MCP server (already built):** `simplicio mcp register` exposes the
  runtime to Claude as MCP tools. In a cloud/container session the binary must be
  present in that container. Plan: ship a tiny bootstrap the Claude session runs
  (`curl … | sh` → installs the linux-x64 binary into the container, registers MCP).
- **Vector B — hosted runtime:** a remote Simplicio endpoint the container talks to
  over MCP/HTTP, so no local binary is needed (binds to the user''s account).
- **Data:** keyed by the user''s identity (`user.id`/email_hash) so the ledger and
  savings follow the account across desktop/cloud.
- Open questions for the user: which Claude surface (Desktop app, claude.ai code,
  API)? self-host vs hosted? These decide A vs B.

## Sequencing
R1→R2 (reports, data exists) and the WOW intro are the fastest wins on top of the
just-landed living dashboard. The video and the Claude-container work are larger,
separate tracks. Each gets a GitHub issue before implementation (repo rule).','docs/SIMPLICIO_GROWTH_PLAN.md','8ddd96ef0d48feb30a91086fe2da8d2545acbd36a321cb5c0ad7a97b597fd7b4','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_GTM_STRATEGY.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_GTM_STRATEGY.md','doc: Simplicio — Estratégia de Formato de Produto & Go-to-Market','# Simplicio — Estratégia de Formato de Produto & Go-to-Market

**Date:** 2026-06-26 · **Method:** judge-panel + adversarial verify (15 agentes, ~825k tokens) grounded
no inventário consolidado (`SIMPLICIO_PROJECT_INVENTORY.md`/`.json`) + `CLAUDE.md` + leitura de código real.
Fases: Ground → 5 painéis de formato → 5 painéis de GTM → 3 céticos adversariais → síntese.

> **Aviso de honestidade:** a fase adversarial leu o código e achou que o produto e o SKU **não existem
> hoje**. Os números são auto-reportados. Trate este doc como um plano de **~3 meses de build**, não um
> empacotamento de algo pronto.

## Placar dos painéis

**Formato** (fit / revenue-speed / moat, 1-10):

| Formato | Fit | Rev | Moat |
|---|---|---|---|
| **MCP plugin / "Simplicio Core"** | **8** | 4 | 5 |
| Super-harness / control plane | 8 | 4 | 5 |
| Layered engine + surfaces | 8 | 4 | **7** |
| Vertical (esconder o runtime) — vídeo determinístico | 7 | **5** | 4 |
| Standalone agent runtime | 6 | 4 | 5 |

**GTM** (atratividade, 1-10):

| Modelo | Score |
|---|---|
| **Closed-source per-seat BYOK (Cursor/JetBrains-style)** | **7** |
| Open-core + cloud gerenciado | 6 |
| Vertical SaaS (vender o resultado) | 6 |
| Free runtime + marketplace + enterprise | 6 |
| Usage/outcome (savings-as-a-service) | 5 |

---

# Recomendação Final

## 1. Veredito

A recomendação é **um core Rust único exposto como "Simplicio Core" — um MCP server + thin CLI que acopla o
substrato determinístico (edit/memory/gate/evidence) sob qualquer host LLM (Claude Code, Cursor, Codex)** —
vendido **não como "edição mais barata" (commodity que os hosts vão absorver), mas como o substrato
governado, auditável e à prova de adulteração para mutações de IA**, monetizado via **licença closed-source
per-seat BYOK com um tier Team de governança/auditoria**. Vence porque inverte as três maiores fraquezas da
Simplicio (thesis de control-plane hostil, falta de empacotamento limpo, distribuição BR/PHP) em
não-problemas: você pede ao dev para *adicionar um plugin* ao agente que ele já ama, não para abandoná-lo —
o custo de troca colapsa de "troque seu agente" para "adicione um MCP server". As críticas adversariais
estão certas e são incorporadas, não escondidas: o produto **não está 80% pronto, está ~3 meses de build**
(não existe `core` Cargo feature, não existe seat/Team em `license.rs`, o beta público desliga todo o
gating hoje, as credenciais #762 seguem sem rotação). Mas a tese é estruturalmente sólida e o sequenciamento
das correções é claro — e nenhum outro formato resolve simultaneamente o problema de distribuição de um solo
founder BR contra Anthropic/Cursor.

## 2. Formato recomendado

**Arquitetura: um core, um wedge, um caminho de expansão.**

- **Um core Rust** — o engine determinístico já real: `crates/simplicio-edit` (334 LOC, `git apply`
  mecânico, zero-token, standalone e testado), `src/action_gate.rs`, `src/action_bridge.rs`
  (checkpoint save/restore/list), neural memory SQLite/FTS5+vector, e a HBP evidence chain. As 6 SPINE tools
  MCP **já estão wired e despacham para comandos determinísticos reais** (`simplicio_edit → ["edit", plan,
  "--json"]`, `simplicio_run` faz gate→bridge→evidence inline) — verificável em `src/main_parts/
  main_part_01.rs`, não é vapor.

- **Wedge primário (liderar com): o MCP plugin "Simplicio Core".**
  - Por que não os 4 surfaces simultâneos (layered)? Diluição de foco é fatal para time solo — "evite apostar
    em um formato" vira "nunca termine nenhum". O layered é a *arquitetura* certa; o MCP plugin é a *porta*
    para abrir primeiro. CLI/desktop/wheels são derivativos quase-grátis do mesmo Core build, sequenciados
    *depois* de seats pagantes.
  - Por que não standalone agent (fit 6)? Convida à comparação de raciocínio bruto, onde o modelo local 4B
    (56,1% HumanEval) perde, e o número vencedor (95,1%) silenciosamente exige LLM remoto pago. O moat vive
    no plumbing determinístico/auditável, que o packaging de standalone *de-enfatiza*.
  - Por que não os verticais como wedge? Viram negócio operacional (cada conta banida, cada reel fora de
    brand é seu suporte/refund) — insustentável para solo BR. Ficam como **expansão**, não wedge.

- **Reframe obrigatório do wedge (a correção que faz o combo sobreviver):** liderar com **"toda mutação de IA
  no seu repo é gated, reversível e provavelmente logada"** — o bundle de proveniência auditável (gate →
  apply determinístico → HBP receipt → checkpoint/undo, sobre MCP) — **não** com "economizamos tokens".
  Cursor/Anthropic vão commoditizar edição barata e memória de codebase (já fazem: apply-models, indexing,
  hooks, CLAUDE.md). O que eles são **estruturalmente desincentivados a construir** é uma trilha de auditoria
  à prova de adulteração das mutações do *próprio agente deles* — porque implica desconfiar do próprio
  agente. Esse é o único wedge durável.

- **Caminho de expansão:** MCP plugin (Pro individual) → Team (governança/auditoria, motor de receita) → CLI
  headless em CI → desktop/wheels (defer-mas-spec) → verticais (vídeo determinístico, vertical SaaS BR) como
  linhas de receita independentes uma vez que o core tenha tração.

**O que construir primeiro (keystone, NÃO "wrapper work"):**
1. **A `core` Cargo feature** — `--no-default-features --features core`, compilando edit+memory+gate+evidence
   **sem** tui/async-runtime/in-process-llm/mic-capture, **sem toolchain C/C++**. Hoje o default arrasta
   llama.cpp (cmake+clang). Sem isso, "adicione este MCP server, é frictionless" é falso. **Verdadeiro gate v0.**
2. **Seat/org/Team em `license.rs`** (hoje só Free/Trial/Economy/Pro, zero seat-count) **e desligar o beta
   público** (`public_beta_active()` default true desbloqueia tudo). Sem isso não há perímetro para cobrar.

## 3. Como vender (GTM sequenciado)

**Modelo: licença closed-source per-seat BYOK (atratividade 7)** — único cujo enforcement (ed25519 offline)
já existe parcialmente, e único alinhado com o mandato compiled-only (binário ships','docs/SIMPLICIO_GTM_STRATEGY.md','306e82aeee21aa0685a3ca4e10ab38a709c5a13f2d6026dc4f76135d93d13e6e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_INSTALL.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_INSTALL.md','doc: Simplicio — Install & Quick Start','# Simplicio — Install & Quick Start

> Single binary, zero runtime deps. Just download and run.

A terminal-based AI coding agent and runtime. Ships as a single compiled binary.

---

## Install

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.sh | sh
```

### Windows (PowerShell)

```powershell
powershell -c "irm https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.ps1 | iex"
```

The Windows installer prefers the **portable ZIP** (`simplicio-windows-x64.zip`)
and falls back to the raw `.exe` only if the ZIP is unavailable.

### Windows portable (manual)

Download and extract:

```powershell
Invoke-WebRequest `
  -Uri https://simpleti.com.br/simplicio/dist/simplicio-windows-x64.zip `
  -OutFile $env:TEMP\simplicio-windows-x64.zip
Expand-Archive $env:TEMP\simplicio-windows-x64.zip -DestinationPath $env:USERPROFILE\simplicio-portable -Force
$env:PATH += ";$env:USERPROFILE\simplicio-portable\simplicio-x86_64-pc-windows-msvc"
simplicio version
```

### npm / pnpm / bun (cross-platform)

```bash
npm install -g simplicio
pnpm add -g simplicio
bun add -g simplicio
```

The binary is downloaded on first run and cached in `~/.cache/simplicio/bin/`.

### Homebrew (macOS / Linux)

```bash
brew install wesleysimplicio/tap/simplicio
```

### Arch Linux (AUR)

```bash
paru -S simplicio-bin
yay -S simplicio-bin
```

### Manual Download

Download the binary for your platform from the
[releases](https://github.com/wesleysimplicio/simplicio/releases):

| Platform | File |
|----------|------|
| macOS ARM64 | `simplicio-v<ver>-macos-aarch64.tar.gz` |
| macOS x86_64 | `simplicio-v<ver>-macos-x86_64.tar.gz` |
| Linux x86_64 | `simplicio-v<ver>-linux-x86_64.tar.gz` |
| Windows x86_64 | `simplicio-windows-x64.zip` |

```bash
# Example: extract and install
curl -sSfL https://github.com/wesleysimplicio/simplicio/releases/latest/download/simplicio-v0.7.0-macos-aarch64.tar.gz \
  | tar xz -C /tmp
sudo mv /tmp/simplicio /usr/local/bin/
```

## Verify Installation

```bash
simplicio help
```

Expected output starts with `simplicio <version>`.

---

## System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| RAM | 8 GB | 16 GB+ |
| Storage | 5 MB | 1.5 GB (with local LLM) |
| OS | macOS 13+, Linux, Windows 10+ | macOS ARM64 |
| Terminal | any modern terminal | WezTerm / Alacritty / Ghostty |

---

## Configuration

### LLM Provider (required for AI features)

Simplicio works with **local** or **remote** LLM providers.

#### Local (default, no API key needed)

Simplicio includes an in-process llama.cpp engine. Its single canonical local
model is `simplicio/qwen3.5-4b:q4_k_m` (Q4_K_M). The Runtime downloads the
pinned artifact, verifies its fixed SHA-256, and keeps it outside the binary.

```bash
simplicio model fetch --tier auto --yes
simplicio local-model health --json
simplicio run "fix the bug" --repo . --local
```

#### Remote (OpenRouter, Anthropic, DeepSeek, etc.)

Set environment variables to use a remote provider:

```bash
export SIMPLICIO_MODEL="deepseek/deepseek-v4-flash"
export SIMPLICIO_BASE_URL="https://openrouter.ai/api/v1"
export SIMPLICIO_API_KEY="your-key-here"

simplicio run "fix the bug" --repo . --remote
```

### Runtime Profile

Control resource usage with profiles:

```bash
# Normal: balanced desktop throughput
simplicio runtime-profile use normal

# Full: maximum feature set with adaptive desktop-safe ceilings
simplicio runtime-profile use full

# Low: constrained environments / background execution
simplicio runtime-profile use low
```

`full` remains the default profile, but it now uses adaptive limits to avoid
saturating RAM/disk on common developer machines. The bootstrap flow also seeds
`.simplicio-loop/runtime.toml` with conservative capacity defaults and evidence
retention (`max_runs = 20`).

---

## Core Commands

```bash
# Map your repo (saves tokens vs reading files)
simplicio runtime map --repo . --for-llm markdown

# Recall from memory (don''t re-derive known facts)
simplicio memory "how does auth work" --repo . --json

# Deterministic edit (zero LLM tokens for file writes)
simplicio edit ''{"file":"src/main.rs","operations":[{"op":"replace","find":"old","with":"new"}]}''

# Chat REPL
simplicio chat "hello" --repo .
simplicio chat --repl --repo .

# Run a task with agents
simplicio run "add pagination to the API" --repo . --local --agents 4

# Coding loop (iterate until tests pass)
simplicio coding-loop "fix the failing test" --repo . --max-cycles 5

# Delivery gates (quality check before shipping)
simplicio deliver check --repo .
simplicio deliver certify --repo . --json

# Health check
simplicio doctor --repo .
```

See `simplicio --help` for the full command list.

---

## What''s Included

- **Chat REPL** — conversational AI assistant
- **Agent mode** — multi-turn task execution with sub-agent fabric
- **Memory system** — SQLite/FTS5 neural memory with optional sqlite-vec ANN
- **Deterministic editing** — mechanical edits with zero LLM tokens
- **Delivery gates** — Definition-of-done, certification, regression checks
- **Gateways** — Telegram, Discord, Slack, WhatsApp bridges
- **ACP adapter** — Agent Client Protocol server for IDE integration
- **CLI commands** — doctor, config, model, skill, map, memory, and more
- **Setup wizard** — `simplicio setup` or `bash setup-simplicio.sh`

---

## IDE Integration

Simplicio integrates with editors via the ACP adapter:

- **VS Code**: Install the Simplicio extension (search "simplicio" in marketplace)
- **JetBrains**: Use the Simplicio plugin
- **Zed**: ACP adapter built-in

---

## Using with AI Assistants

Simplicio is designed to be used **by** AI assistants (Claude, Codex, Gemini)
as their execution backbone:

1. The AI assistant reasons about the task
2. Simplicio provides: repo map, memory recall, deterministic edits, validation
3. The AI reviews results and iterates

### Claude Code

Add to your project''s `CLAUDE.md`:

```markdown
## Simp','docs/SIMPLICIO_INSTALL.md','612dc6324dc52040fa3eec8caa2705b7a996f970087955b0b25d5954136c3ed8','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_OPERATIONAL_MANUAL.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_OPERATIONAL_MANUAL.md','doc: Simplicio Operational Manual','# Simplicio Operational Manual
This is the single consolidated Markdown manual for the Simplicio Runtime `docs/` corpus. It preserves the previous human-facing documentation, ADRs, operations guides, benchmark notes, research notes, and the extracted text of documentation PDFs in one organized file.
Root `README.md` and translated `READMEs/` are intentionally left separate because they are public language-specific entrypoints. Machine-readable schemas also remain separate under `schemas/` because the runtime validates and emits those contracts directly.
## Consolidation Scope
- Generated on: `2026-06-04`.
- Canonical docs file: `docs/SIMPLICIO_OPERATIONAL_MANUAL.md`.
- Docs sources consolidated: `138`.
- Markdown docs consolidated: `137`.
- PDF docs converted to text and consolidated: `1`.
- Source paths are preserved in the archive sections below for historical traceability.
- The old scattered files in `docs/` can be removed after this manual is committed.
- Updates kept in this single manual (newest first):
   - `2026-07-22` — **Provider/model-neutral Runtime**: the default and `official-runtime` Cargo profiles no longer compile the local `in-process-llm`; the feature remains available as an explicit future opt-in.
   - `2026-06-12` — **Post-#53 evolution ledger** (compact; one row per wave):

     | Date | Wave | What actually changed |
     |---|---|---|
     | `2026-06-09` | Full-potential default | `default = ["tui","async-runtime","rich-repl","in-process-llm"]`; a reduced build is an explicit opt-out, never the default. |
     | `2026-06-10` | v0.8.0 beta | Version unified at 0.8.0 across Cargo.toml/pyproject/Cargo.lock; CI re-enabled (ubuntu on PRs, macOS/Windows gate `main`); free public beta published with signed update manifest. |
     | `2026-06-11` | Voice & gateway wave | `voice-orb` push-to-talk loop; gateway audio channel with modality mirroring for Telegram/WhatsApp voice notes; Discord parity (sessions, multi-channel, attachments). |
     | `2026-06-12` | Tier-B/C completion (#38/#39/#53) | `self-test` runs real probes (adapter resolution, validation-plan emission, evidence write+readback, schema round-trip, doctor layout) and exits non-zero on failure; `first-run` persists `onboarding.json` with verified steps; `welcome` reports the live tiers (low/normal/full) plus this machine''s model/provider state. |

   - `2026-06-08` — **Agent Scale Limits Verified — 10,000 Logical / 256 Active**:
     Maximum agent capacity tested and documented. See `## Agent Scale Limits` below.
     - 10,000 logical agents confirmed (hibernated on disk/SQLite)
     - 128 active default (balanced profile), 256 with `--max-active 256`
     - 10,000 active possible with `--max-active 10000` (CPU/FD-limited)
     - With local 1.5B LLM: ~24-32 inference-active agents (3-4 workers * batch 8)
     - With local 3B LLM: ~16 inference-active agents (2 workers * batch 8)
     - Non-inference agents (shell/IO/web): up to ~10,000 (file descriptor limit)
   - `2026-06-08` — **All 195 issues closed — v0.5.0 released**:
     Audit + implementation wave completed:
     - 99 ghost issues reopened and linked to existing code (6 batch commits)
     - 16 new features implemented: HBP Bus, structured concurrency, sync
       patterns, agent collaboration, chat schema, Docusaurus site
     - 31 Hermes parity + TUI issues committed and closed
     - Version bumped to v0.5.0
     - 0 open issues remaining
  - `2026-06-08` — **99 reopened issues verified and implemented in 6 batches**:
    Audit discovered 97 issues closed without code references. All issues were
    reopened and linked to existing implementation via 6 batch commits:
    1. `feat(organism)` — Living digital organism core (#535-#558, #566-#567)
    2. `feat(gateway)` — Multi-platform messaging (#413-#421, #427, #449)
    3. `feat(async)` — Tokio runtime for 600+ agents (#435-#441)
    4. `feat(memory)` — Persistence, profiles, low-RAM (#562, #565, #453, #570, #568-#569)
    5. `feat(desktop)` — Tauri app + Ratatui (#456-#506)
    6. `feat(advanced)` — Daemon, sandboxing, voice, eval (#428-#432, #450-#455, #571)
    See `.github/ISSUE_IMPLEMENTATION_LOG.md` for per-issue file mapping.
  - `2026-06-07` — **Discord bot deploy + gateway starter script**:
    Discord `Simplicio_bot` (app `1513271222387867798`) authenticated and
    live. Adapter uses REST API v10 (polling, not websocket). Env token read
    from `SIMPLICIO_DISCORD_TOKEN` or `DISCORD_BOT_TOKEN`. Requires
    `SIMPLICIO_DISCORD_CHANNEL_ID` for listen mode. Starter script at
    `scripts/start-gateway.sh`. Example env template at
    `.simplicio-loop/.env.example`. See `## Discord Bot Deployment` below.
  - `2026-06-06` — **Tokio async fabric enabled by default** (`v0.3.67`):
    `async-runtime` is now in `default` features; `simplicio tokio-runtime`
    runs real `JoinSet` + semaphore spawns, `fabric` (inference pool + async
    Yool), and live inference-pool smoke — no stub JSON.
  - `2026-06-06` — **Scale epic (#562–#571) shipped** in `v0.3.66`: AgentStore
    (`simplicio agent-store`), Lazy Activation (`simplicio lazy-agent`),
    Multi-Agent Scheduler (`simplicio scheduler`), Yool↔SQLite sync
    (`simplicio yool-sync`), Low-RAM tuning (`simplicio low-ram`), runtime
    hardware profiles (`simplicio runtime-profile`), scale metrics
    (`simplicio scale-metrics`), and distributed inference peer registry
    (`simplicio distributed`). See `## Scale Epic (#562–#571)` below.
  - `2026-06-05` — the Rust TUI now exposes `/migrate` as a terminal-native
    runtime surface. The command summarizes `simplicio migrate inspect`,
    `simplicio migrate matrix`, and a safe `simplicio migrate apply --dry-run`
    flow for Hermes, OpenClaw, and Pi migration work, so migration no longer
    depends on leaving the TUI for the compiled runtime contract.
  - `2026-06-05` — the Rust TUI session orchestrator now supports direct
    `/sessions next` and `/sessions prev` cycling across live lanes. Those
    command','docs/SIMPLICIO_OPERATIONAL_MANUAL.md','d4c72cc3cba86d0c6d17a5009a2bf2128bda8aef94126cd3649e6cd60c1fc6cd','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_PLUGGABILITY_SURVEY.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_PLUGGABILITY_SURVEY.md','doc: Simplicio Pluggability Survey — "Simplicio Core" as a Rust plugin for any LLM','# Simplicio Pluggability Survey — "Simplicio Core" as a Rust plugin for any LLM

**Date:** 2026-06-26 · **Status:** survey + Core v0 proposal · **Author:** orchestrated via `/simplicio-tasks`

## Thesis

Stop competing with Hermes on the **commodity** (the chat/agent loop — every frontier LLM
already does it). Repackage Simplicio''s **differentiated substrate** — deterministic edit,
neural memory, action gate, evidence chain, token economy — as a **Rust plugin couplable into
any LLM** (Claude Code, Cursor, Hermes, OpenClaw, an MCP chat client). The coupling surface is
**MCP** (Model Context Protocol), which every LLM client can consume. This is repositioning, not
a rewrite: most of the hard parts already exist.

## Key finding — the plugin already started

`simplicio mcp serve` already exists and exposes an MCP tool surface:

- **`simplicio_run`** (`src/mcp_serve.rs`) — routes a task through the spine
  (action gate #231 → action-bridge #230 → HBP evidence ledger), returns a typed
  `simplicio.run/v1` receipt. This is the mutating entry point, already gated.
- **~9 read/metric tools** (`MCP_TOOLS_JSON` in `src/main_parts/main_part_01.rs`):
  `repo_map`, `memory_recall`, `skills_recall`, `token_economy`, `success_rate`,
  `regression_rate`, `pr_acceptance`, `evidence_completeness`, `autonomy_time`.

So Tier A below is **shipping today**. The gap to a compelling Core v0 is small and well-defined:
expose the **deterministic mutators** (edit / gate / checkpoint / validate / deliver) as MCP tools,
and split a `simplicio-core` build profile that compiles **without** the heavy runtime
(`tui` / `async-runtime` fabric / `in-process-llm`).

## Acoplabilidade table

Legend: **A** = MCP-ready today (already exposed) · **B** = pure deterministic, zero-model,
trivially MCP-wrappable (the Core v0 work) · **C** = needs a model (couplable anywhere a provider
is configured; mark "model-backed") · **D** = runtime-bound, needs refactor to extract (NOT Core v0).

| Capability | CLI / module | Tier | Notes for coupling |
|---|---|---|---|
| Route task through spine (gate→bridge→evidence) | `simplicio_run` / `mcp_serve.rs` | **A** | Already an MCP tool. The mutating entry point. |
| Repo map (compressed repo view) | `repo_map` / `map` | **A** | Already MCP. Zero model. |
| Neural memory recall (FTS+vector) | `memory_recall` / `memory_command.rs` | **A** | Already MCP. Reads `.simplicio-loop/memory/*.sqlite`. |
| Skills recall (rank/lazy-load) | `skills_recall` | **A** | Already MCP. Zero model. |
| Token-economy + delivery metrics | `token_economy`,`success_rate`,`regression_rate`,`pr_acceptance`,`evidence_completeness`,`autonomy_time` | **A** | Already MCP. Pure read. |
| **Deterministic mechanical edit** (zero-token writer) | `edit` (dispatch in `main.rs`) | **B** | ⭐ Highest-value gap. Git-apply ops: replace/insert/replace_line/append. The crown jewel for "any LLM edits via Simplicio". |
| Action gate classify | `gate classify` / `action_gate.rs` | **B** | `classify_action_risk` / `action_gate_decide`. Pure decision, no model. |
| Checkpoint / undo | `checkpoint` | **B** | Snapshot + restore. Deterministic. |
| Validation pipeline | `validate` | **B** | Runs build/test/lint phases; reports. Zero model (drives external tools). |
| Delivery gates (DoD/acceptance/regression/certify) | `deliver check`/`regression`/`certify` | **B** | Deterministic gates over the validation pipeline + criteria. (`deliver review` = Tier C.) |
| Signatures-only read | `signatures` | **B** | Token-saving API-surface read. Pure. |
| Response cache | `cache` | **B** | LRU; skips repeat LLM calls. Pure infra. |
| Dry-run action classify | `act --dry-run` | **B** | Gate + plan without executing. Pure. |
| Reason (first-pass + `--act`) | `reason` / `reason --act` | **C** | `simplicio.reasoning-action/v1`. Needs a model; gated act is reusable. |
| Coding loop (iterate-until-green #236) | dispatch + diagnostics #237 | **C** | Needs model for generation; the loop/diagnostics harness is reusable. |
| Generate (local-first ladder 64→600→remote) | `llm_routing.rs` / `llm_providers` | **C** | Needs model. The ladder/escalation policy is the value. |
| Self-review of diff (#254) | `deliver review` / `adversarial_review_ext.rs` | **C** | Model-backed reviewer. |
| Chat (operational chat → action) | `chat` / `agent_chat.rs` | **C** | Needs model. The intent→action mapping is the value. |
| TUI / rich REPL | `tui`,`tui_app.rs`,`node_tui.rs`,`repl_theme.rs` | **D** | UI surface. Not a tool. Exclude from Core. |
| 600-agent tokio fabric | `agent_ops_bounded_1536.rs`,`async-runtime` | **D** | Process architecture. Optional backend, not a plugin tool. |
| In-process LLM worker (llama.cpp) | `in-process-llm` feature | **D** | Heavy C/C++ build. Make it an optional backend behind the model-backed tier. |
| Gateways (telegram/discord/signal/whatsapp/matrix/slack/…) | `gateway/`,`*_gateway_*.rs` | **D** | These are servers, not MCP tools. Separate product line. |
| Organism / daemon / autonomia (autonomous loop) | `organism/`,`growth_daemon.rs`,`autonomia_engine.rs` | **D** | Long-running loop; not a stateless tool. |
| Voice (TTS/STT/wake-word) | `voice_*.rs`,`mic-capture` | **D** | Device-bound. Exclude from Core. |
| Video generative (Higgsfield) | external MCP | **D** | Already external/gated. Out of scope. |

## Proposal — "Simplicio Core" MCP server v0

**Definition.** A `simplicio-core` build profile that compiles **without**
`tui` / `async-runtime` / `in-process-llm`, shipping the deterministic spine as an MCP server over
stdio, plus a thin CLI for non-MCP hosts. Two coupling tiers, both honest:

- **Core (deterministic)** — works **instantly, any host, zero model**. Tools = Tier A (already
  there) **+ Tier B** (the v0 work): `edit`, `gate`, `checkpoint`, `validate`, `deliver` (check/
  regression/certify), `signatures`, `cache`, `act --dry-run`.
- **Core+ (model-backed)** — `reason`, coding-loop, `generate`, `deliver review`, `chat`. Requires a
  conf','docs/SIMPLICIO_PLUGGABILITY_SURVEY.md','41e93efb867cbc1e96ea3de0ff1b2e3b57c5ce9e1206e17d4086149340155de6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_PROJECT_INVENTORY.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_PROJECT_INVENTORY.md','doc: Simplicio Runtime — Master Project Inventory (consolidated, all areas)','# Simplicio Runtime — Master Project Inventory (consolidated, all areas)

**Date:** 2026-06-26 · **Method:** `/simplicio-tasks` orchestration — two reader waves (9 + 20 parallel
agents) across the entire documentation + code surface.
**Scope read:** 1290 markdown files (697 skills · 295 `docs/` · 81 `.simplicio-loop/` memory · ~30 root canon ·
23k-line operational manual consolidating 142 source docs) + `src/` (851 `.rs`, Cargo features, CLI dispatch)
+ `apps/`, `proofs/`, `specs/`, `.github/`, `scripts/`, `site/`, `website/`.

> **Map, not audit.** Status tags reflect what docs/code assert (sampled broadly). "Done" = "documented as
> built"; confirm against a run before shipping. Where waves disagreed, the disagreement is flagged inline.
> Machine-readable form: `SIMPLICIO_PROJECT_INVENTORY.json`.

---

## 0. What Simplicio is

A **single compiled Rust binary** (`src/main.rs`) that is both an AI coding agent and a **control plane**:
every LLM (Claude, Codex, Gemini, Copilot, Hermes, OpenClaw) routes execution **through** Simplicio rather
than bypassing it (enforced by git hook + MCP-everywhere + orient-gate). It maps repos cheaply, recalls from
neural memory, edits deterministically (zero-token), gates mutations, and proves them on the HBP verifiable
evidence chain — cutting token cost while staying auditable. Distribution: **compiled-only / closed-source**
(multi-arch binaries + simplicio-installer wheel). Default build = **full potential** (`tui` + `async-runtime` 600-agent
fabric + `rich-repl` + `in-process-llm` + `oauth-refresh` + `mic-capture`).

**Self-reported standing:** AUDITORIA_COMPARATIVA scores 39/39 features (100% vs Claude Code 42% / Codex 12%
/ Copilot 32%); AGI bench (2026-06-24→26) 91.46% raw-model / 95.12% paid task success, 56.1% tasks solved at
$0; token-economy ~77-82% average savings.

---

## 1. Root canon (project identity & standing decisions)

`README(.pt-BR)` (96% savings pitch) · `CLAUDE.md` (Claude context, 3 build programs, full-mode rules) ·
`AGENTS.md` (cross-agent control-plane contract) · `BUILDING/INSTALL(.pt-BR)/PUBLISHING/CONTRIBUTING` ·
`CHANGELOG` (v1.3.1) · `INIT/_BOOTSTRAP/GEMINI` (llm-project-mapper bootstrap) · `COMMAND_DISPATCH_MAP`
(84-command dispatch table) · `MODULOS_E_ISSUES` (partial-work audit) · `codex_cli_slash_commands` /
`copilot-complete-reference` (external CLI refs).

**Audits (root):** `ANALYSIS_DUPLICATES_DEADCODE` + `SIMPLICIO_LOOSE_ENDS_REPORT` (31 `st_*` dup pairs,
~199 orphan `.rs`, ~27k LOC unreachable, mock tools returning ""), `RISCO_DELECAO` (54% false-positive rate
on naive orphan scans — 3-level mod chain; **rule: no automatic `.rs` deletion**), `AUDITORIA_*` ×4 (vs
Hermes/Claude/Codex on tools, gaps, memory, terminal).

**Standing decisions:** (1) Simplicio is the control plane — bypass = violation; (2) naming: bare
`simplicio` = Rust, `-py` = Python; (3) distribution = compiled-only/closed-source, simplicio-installer wheel (no
sdist/runtime source), never embed secrets/model-IDs; (4) default = full potential, reduced is explicit opt-out; (5)
resource tiers low/normal(default)/full; (6) two-review merge gate (Code + QA, Policy #2208); (7) every
response reports token savings; (8) branch policy "SEMPRE main" (CLAUDE.md) vs this session''s feature branch
(task directive) — **conflict noted**; (9) binary centralized at `~/.local/bin/simplicio`.

---

## 2. Operational manual (`docs/SIMPLICIO_OPERATIONAL_MANUAL.md`, ~23k lines, consolidates 142 docs)

**Fundamentals:** runtime rule · adaptive-LLM default (fast/think/internet routing) · latency & token economy
& deterministic fast-paths (0-token `simplicio edit`; THINK vs NO-THINK) · required load order (map→memory→
gate before action) · deterministic flow (mapper→dev-cli→prompt→sprint) · multi-agent loop.

**Operational patterns:** wave recovery + evidence (`workflow.json`/`events.jsonl` resume) · governed
third-party delegation (codex/claude/kimi/hermes/openclaw as workers, never control plane) · cloud watcher ·
validation cadence (tiered) · **graduated local fan-out 64→100→200→600 → remote last** · agent scale limits
(10,000 logical agents tested on M1, ~24-32 inference-active; 256 active default) · **Scale Epic #562-#571**
(AgentStore → lazy activation → Yool sync → scheduler → runtime profiles → low-RAM tuning → scale metrics →
distributed).

**Architecture:** Hermes-parity foundations · Neural Guardians (**Helo** runtime-knowledge / **Isa**
project-memory / **Levi** external-acquisition) · zero-copy orientation pack · agent IPC (iceoryx2+rkyv,
rtrb fallback) · typed tool bus · Tokio async fabric + Yool tuple-space.

**Contracts:** the runtime emits **~188 versioned `simplicio.*/v1` contracts** — task, capability, intake,
decision, invocation, recipe, workflow; agent/agent-lease/agent-event/agent-ipc/subagent; evidence-ledger/
evidence-index/run-result/run-state/edit-result/mechanical-edit/validation-plan/**delivery-certificate**;
neural-guardian-policy/mapper-memory/memory-db/memory-ingest/skill-memory; action-gate-decision/
action-checkpoint/fast-path-decision; chat/channel; browser-*/computer-use; scale-metrics/tool-event/
runtime-event/ops-board/health/status; release-manifest/update-manifest/packaging-mode; **io/v1** (MCP
stdio), **orientation-pack/v1**, **agent-ipc/v1**, **cloud-watch/v1**, plus mechanical-edit JSON schemas +
signed release manifest.

---

## 3. Architecture, core, contracts, design, orchestrator, observability (`docs/`)

- **Dual-path router** (`orchestrator/DUAL_PATH_ROUTER.md`): fast-path F0 deterministic / F1 memory replay
  ≥0.92 / F2 mechanical edit = **0 LLM tokens, <500ms**; heavy-path H1 local fan-out ≤60s / H2 extended
  ≤5min / H3 remote VC (explicit `--allow-remote` + escalation evidence on HBP). [spec]
- **Orchestrator-v7 contract** (`contracts/orchestrator-v7.md`): canonical task lifecycle; 4 capacities (DAG
  topo-sort, git-worktree isolation, adversarial skeptic panel, loop-budget cap + oscillation detection); 5
  quality gates (comp','docs/SIMPLICIO_PROJECT_INVENTORY.md','b40e73aaa94b77b3a3763018f4646f202b8b81584f22cc8fc0a86a882ab1998b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_PROJECT_INVENTORY_DEEP.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_PROJECT_INVENTORY_DEEP.md','doc: Simplicio Runtime — Deep Project Inventory (per-area, 50-agent sweep)','# Simplicio Runtime — Deep Project Inventory (per-area, 50-agent sweep)

**Date:** 2026-06-26 · **Method:** `/simplicio-tasks` deep sweep — 48/50 slices via 50 parallel deep analyzers (read the actual files) + 9 synthesizers. 59 agents, ~3.5M tokens.

> Companion to `SIMPLICIO_PROJECT_INVENTORY.md` (consolidated) and `.json` (machine). This is the **deep, per-area** form — each section synthesized from analyzers that read the files directly. Map not audit: status = documented/observed, confirm against a run.


---


## G1 Identity & root canon

### root-readme-claude-agents

The five root governance/entry files define Simplicio as a local-first, single-binary Rust AI coding agent/runtime claiming up to 96% token savings by orienting/editing/gating deterministically while the frontier LLM only orients and reviews. `AGENTS.md` is the canonical cross-agent contract (one source of truth); the other rule files symlink to it.

- **/home/user/simplicio-runtime/README.md** — English entrypoint: one-line install (curl/PowerShell), Docker quick-start (ghcr.io image, compose), feature list (chat REPL, agent mode, neural memory, deterministic edit, delivery gates, local llama.cpp), docs table, quick-taste commands (map/memory/coding-loop/deliver certify). [reference]
- **/home/user/simplicio-runtime/README.pt-BR.md** — Portuguese mirror of README.md; links to INSTALL.pt-BR.md and pt-BR docs (QUICKSTART/UPGRADE/TROUBLESHOOTING). Same 96% token-saving claim and command samples. [reference]
- **/home/user/simplicio-runtime/AGENTS.md** — Canonical cross-agent contract (Tier 0). Core Rule: Simplicio is the control plane, providers are only sessions. Enforcement via pre-commit hook, MCP register (~10 clients), .claude/hooks/orient-gate.sh, symlinked rule files. Covers Super-Harness flows, runtime profiles (low/normal/full), neural guardians Isa/Helo/Levi, local fan-out 64-600, wave-engine, git closure on main, binary centralization, safety rules. [reference]
- **/home/user/simplicio-runtime/CLAUDE.md** — Claude-specific durable project context: the Rust runtime (src/main.rs), active build programs (Operational Chat #235, Video Creation #240, Quality Delivery #250 with sub-issues), FULL POTENTIAL default mode, naming convention (-py suffix), closed-source distribution, local model qwen3.5-2b, mandatory token-savings report, release engineering decisions, pending user-side items. [reference]
- **/home/user/simplicio-runtime/GEMINI.md** — Symlink to AGENTS.md (verified GEMINI.md -> AGENTS.md). Per the contract, all rule files (.cursorrules, .windsurfrules, .github/copilot-instructions.md, GEMINI.md) symlink to AGENTS.md rather than duplicating it. [done]

### root-audits-deadcode

Three root-level audit reports on duplicate/dead-code in the Rust runtime. `ANALYSIS_DUPLICATES_DEADCODE.md` scopes 46 files (~43,067 LOC) finding 32 unreachable files (~27,100 lines); `SIMPLICIO_LOOSE_ENDS_REPORT.md` is a 100-agent scan of ~1,400 .rs files (main.rs = 84,496 lines) reporting 199 orphans and ~15,000+ dead/dup lines; `RISCO_DELECAO.md` is a cautionary post-mortem (30 agents nearly deleted 26 compiled files, 54% false-positive rate) concluding .rs deletion must not be automated.

- **/home/user/simplicio-runtime/ANALYSIS_DUPLICATES_DEADCODE.md** — Scoped audit of 46 files (~43,067 LOC) in vscode_*/codex_*/coverage*/desktop*; 32 dead files (~27,100 lines), 14 alive, 1 exact dup pair (codex_transport.rs), 1 overlap (desktop_distribute.rs vs desktop/desktop_1787.rs). [audit]
- **/home/user/simplicio-runtime/SIMPLICIO_LOOSE_ENDS_REPORT.md** — 100-agent scan (2026-06-20) of ~1,400 .rs files; 199 orphans, 31 st_* dup pairs, 146/204 stub skills, 138 #[allow(dead_code)], 16+ broken dispatch arms, ~15,000+ dead lines; 0 hardcoded secrets. [audit]
- **/home/user/simplicio-runtime/RISCO_DELECAO.md** — Risk post-mortem (Portuguese): 30 agents nearly deleted 26 compiled files, 54% false-positive rate, due to 3-4 level Rust mod chains; recommends NOT automating .rs deletion. [audit]
- **src/codex_transport.rs** — Flat duplicate of transports/codex_transport.rs (2589 lines each, 1-char/type-annotation diff on line 1186); NOT registered — recommended for deletion. [audit]
- **src/transports/codex_transport.rs** — Live registered version (via transports/mod.rs); the canonical copy to keep. [done]
- **src/desktop_distribute.rs** — 326-line simpler version of issue #1787 distribution; superseded/dead, NOT registered. [audit]
- **src/desktop/desktop_1787.rs** — 1065-line complete orchestration for issue #1787 (redo of #1253); registered and alive. [done]
- **src/vscode_savings_dashboard_1591.rs** — Only registered vscode_* file (in main.rs); 12 other vscode_* files (~10,118 lines) are dead/unregistered. [done]
- **src/codex_parity_1541.rs** — One of 6 codex_parity_154[1-5,7].rs dead refactoring artifacts (~6,670 lines total) split from monolith, originals never removed; have #![allow(dead_code)]. [audit]
- **src/codex_watcher.rs** — 1,050-line codex upstream watcher, orphaned — not declared as mod anywhere, no #[allow(dead_code)]. [audit]
- **src/coverage_1530.rs** — 546-line delivery-gate registry/smoke-by-schema (#1530), dead; coverage/ subdir (coverage_1529, coverage_1531) is the live version. [audit]
- **src/coverage_1532.rs** — 829-line compiled/configured/exercised state (#1532), dead/unregistered. [audit]
- **src/conversation/compression.rs** — 1,924 lines dead/orphaned (largest single conversation dead-code item). [audit]
- **src/context_references.rs** — 1,369 lines dead, marked #![allow(dead_code)]. [audit]
- **src/skill_canvas.rs** — Duplicates skill_canvas_lms.rs (both implement Canvas LMS, same API); flagged to merge; also listed as orphan skill. [audit]
- **src/skill_powerpoint.rs** — 878-line full impl duplicated by skill_pptx_author.rs (20-line stub) for same concept. [audit]
- **simplicio-tokill/src/filters/gh.rs** — 3 mock stubs (filter_gh_pr/issue/run) all return String::new() — silently discard output. [audit]
- **sim','docs/SIMPLICIO_PROJECT_INVENTORY_DEEP.md','b5a31b4a1fc75218608136f414f9eded896e7d4d23f98622d80e36301e9f3c56','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_STACK.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_STACK.md','doc: The Simplicio Stack — canonical map (#2954)','# The Simplicio Stack — canonical map (#2954)

One page answering "what are all these `simplicio-*` repos, which one do I
actually run, and what do I call it." If you arrived via `simplicio-dev-cli`,
`llm-project-mapper`, or `simplicio-loop` standalone, see
[Migrating from a standalone component](#migrating-from-a-standalone-component)
below.

---

## The recommended path

Run everything through the **runtime** (`simplicio`, this repo). It is the
front door — see [#2951](https://github.com/wesleysimplicio/simplicio-runtime/issues/2951)
and [`docs/workspace-dispatch-guide.md`](workspace-dispatch-guide.md) for the
dispatch internals:

```bash
simplicio ecosystem doctor --repo . --json   # is the whole stack present & compatible? (#2950)
simplicio map --repo . --json                # orient (repo/endpoint/screen map)
simplicio run "<task>" --repo . --json        # gate -> bridge -> evidence
simplicio serve --mcp --stdio                 # expose the deterministic MCP tool surface
```

`simplicio ecosystem doctor` is the one command to run first in any repo, in
CI, or when something feels off — it tells you exactly which component is
missing, outdated, or has a stale artifact, and what to run to fix it.

---

## Repo-by-repo table

| Repo | What it is | Canonical command | Standalone use? |
|---|---|---|---|
| **`simplicio-runtime`** (this repo) | The Rust control plane. Single compiled binary. Orchestrates everything below: planning, agents, local LLM, validation, evidence, token economy. | `simplicio` | This IS the entry point — nothing to "stand alone" from. |
| **`simplicio-mapper`** | Repo/endpoint/screen mapper. Produces `.simplicio-loop/project-map.json` and the flow/docs/business-rules engine. Python, PyPI `simplicio-mapper`. | `simplicio-mapper` (or `simplicio-mapper-py`) | Yes — usable directly (`simplicio-mapper --repo . --json`), but the runtime has a native embedded fallback so `simplicio map` never hard-fails when it''s absent. |
| **`simplicio-dev-cli`** (aka `simplicio-cli`, ships `simplicio-py`) | Deterministic implementation/write adapter — the mechanical editor + `simplicio-py task` precedent/skill-router flow. PyPI `simplicio-cli`. | `simplicio-dev-cli` / `simplicio-py` | Yes, same story as the mapper: `simplicio edit`/`simplicio run` fall back to the runtime''s own embedded writer when it''s absent. |
| **`simplicio-loop`** | Runtime-agnostic super-plugin: the autonomous Ralph-style loop (`/simplicio-loop`) plus satellite skills (orient, review, compress, learn, autoresearch). Distributed as a skill bundle for Claude/Codex/Cursor/etc., not primarily a PATH binary. | the `/simplicio-loop` skill inside your assistant | Yes — it is designed to run standalone in any AGENTS.md-compatible host. When paired with `simplicio-runtime`, its two bound operators (`simplicio-mapper`, `simplicio-dev-cli`) are the same components in this table. |
| **`simplicio-prompt`** | LLM artifact contract producer/reviewer (prompt envelopes, diff review, codemod plans). | `simplicio-prompt` | Yes, with the same embedded-fallback relationship as mapper/dev-cli. |
| **`simplicio-sprint`** | Workflow/task-graph + evidence + PR ledger. | `simplicio-sprint` | Yes. |

The compatibility contract between these (minimum versions, claimed schemas,
validation commands) lives in the compatibility matrix inside the runtime
(`simplicio doctor --json` → `compatibility`) and is what `simplicio ecosystem
doctor` reports on in a stack-shaped view.

---

## Naming and alias policy

- The runtime owns the **bare** command `simplicio` (compiled Rust binary, no
  suffix). This is a hard rule — see `CLAUDE.md` "Naming convention".
- Every Python-only component ships a binary that ends in **`-py`**
  (`simplicio-mapper-py`, `simplicio-dev-cli-py`/`simplicio-py`,
  `simplicio-prompt`, `simplicio-sprint`). Adapter resolution inside the
  runtime always prefers the `-py` name first, falls back to the legacy name,
  and **never** resolves to the bare `simplicio` (that would just be the
  runtime calling itself).
- `simplicio-cli` (PyPI package name) is the distribution unit; it provides
  the `simplicio-dev-cli` and `simplicio-py` console scripts. They are the
  same tool under two invocation names for historical reasons — pick either.
- `simplicio-loop` is a skill/plugin bundle name, not a binary convention —
  it is invoked as `/simplicio-loop` (or the legacy `/simplicio-tasks` alias)
  inside whatever assistant loaded it, never as a shell command on most
  hosts.

---

## What it''s not

- **Not a monorepo.** Each component above is its own repository with its own
  release cadence, versioning, and CI. `simplicio-runtime`''s `crates/`
  workspace (see [`crates/README.md`](../crates/README.md) and
  [`docs/workspace-architecture.md`](workspace-architecture.md)) is an
  *internal* decomposition of the Rust binary — it has nothing to do with the
  cross-repo boundary described on this page.
- **Not a requirement to install every component.** The runtime works with
  zero external components installed (it has embedded fallbacks for mapper
  and dev-cli, and a local LLM with no API key). Installing the satellite
  components upgrades you to their standalone release cadence and full CLI
  surface; it does not unlock functionality that is otherwise hidden.
- **Not a rebrand of `simplicio-agent`.** The Agent-parity product
  (chat/gateways/video/computer-use) is a separate fork
  (`docs/ADR-2026-07-06-KERNEL-SCOPE-FREEZE.md`) that consumes this kernel via
  `kernel_binding`/MCP. This stack page describes the **determinism kernel**
  side only: map, memory, edit, gate, validate, deliver/checkpoint, savings,
  skills recall, `serve --mcp`.

---

## Migrating from a standalone component

**Arrived via `simplicio-dev-cli` (or `simplicio-cli`) alone?**
Nothing changes about how the tool itself works. To get the wider stack view
(compatibility checks, mapper artifact freshness, MCP surface), install
`simplicio-runtime` and run `simplicio ecosyste','docs/SIMPLICIO_STACK.md','287f68d9bad0355b8f0daa5ac0d654521924372c19f3dbd5209205c2e66a03ec','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_TOKEN_RECEIPT.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_TOKEN_RECEIPT.md','doc: Simplicio Token Receipt — reproducible host-side savings proof','# Simplicio Token Receipt — reproducible host-side savings proof

> Field-by-field schema reference, `proof.kind`, tokenizer policy, and the two blessed aggregators:
> [`SAVINGS_EVENT_SPEC.md`](SAVINGS_EVENT_SPEC.md) (#2775). This doc stays the practitioner''s how-to /
> sales framing for producing one receipt; that one is the canonical spec other repos vendor from.

**Schema:** `simplicio.savings-event/v1` · **CLI:** `simplicio savings` (the real binary — one harness, no
separate server). Subcommands: `record · report · dashboard · compare · prove · upgrade`.

The receipt is the **sales asset**: instead of asking a buyer to trust a vendor number, they reproduce
the savings on their own repo. It is deliberately honest about scope, and every event is appended to a
hash-chained local ledger (`prev_event_hash` → `event_hash`), so the proof is tamper-evident.

## What it measures (and what it does NOT)

Simplicio is a **substrate under the host LLM** (Claude Code / Cursor / Codex), exposed over one MCP
server (`simplicio serve --mcp --stdio`). The host still does the reasoning. So the savings apply **only
to the mechanical slice**:

- the LLM does **not** re-read whole files → `simplicio_map` / `simplicio_symbol` (orient cheaply);
- the LLM does **not** re-derive prior decisions → `simplicio_memory` (recall);
- the LLM does **not** hand-write the patch token-by-token → `simplicio_edit` (apply mechanically).

**Expect ~20–40% on a realistic plug-under workload, NOT 96%.** The 96% figure is when Simplicio does
both reasoning AND execution in its own loop — a different setup. The receipt never claims the headline
number for the substrate case.

## How to produce a receipt

### Honest path — measured host-side counts

Run the SAME task twice and read the host''s reported token usage each time:

1. **baseline:** the task with the host LLM alone.
2. **spent:** the same task with `simplicio mcp register` active, routing edit/map/recall through the
   one MCP server.

```bash
simplicio savings record --task "add a field to struct X" --spent 380 --baseline 1200 --json
# {"schema":"simplicio.savings-event/v1","tokens":{"actual_total":380,"baseline_total":1200,
#   "saved_total":820},"prev_event_hash":"…","event_hash":"…", …}
simplicio savings report          # aggregate the ledger by repo/task/LLM/user/team
simplicio savings prove --json    # show proof/methodology for the latest event
```

### Estimate path — before real usage arrives

Record an estimate now, then upgrade it to measured when the host reports actual counts:

```bash
simplicio savings record --task "…" --spent 400 --baseline 1200 --estimate
simplicio savings upgrade --run-id <id> --actual-input 380 --actual-output 0 --json
```

`prove` always states which path produced the number and the scope caveat, so a reader can judge it.

## Rules for an honest claim

- Same task, same model, same repo — only the Simplicio plugin differs between baseline and spent.
- Prefer **measured** host-side counts (`--actual-*` via `upgrade`) over estimates for any public claim.
- Publish the methodology + the hash-chained ledger so the buyer reproduces it. A receipt without
  reproducible inputs is marketing, not proof.
- Report the realistic mechanical-slice number; never quote the 96% loop figure for the substrate case.

## Event fields (`simplicio.savings-event/v1`)

| field | meaning |
|---|---|
| `task` | what was done |
| `tokens.baseline_total` | baseline tokens (host LLM alone) |
| `tokens.actual_total` | tokens with Simplicio |
| `tokens.saved_total` | `baseline_total - actual_total` (saturating) |
| `prev_event_hash` / `event_hash` | tamper-evident chain links |
| `proof` | which measurement path produced it + the scope caveat |

Refs: epic #2671 (Simplicio product), #2673 (token-receipt), `docs/SIMPLICIO_GTM_STRATEGY.md`.','docs/SIMPLICIO_TOKEN_RECEIPT.md','853694fd3001d0fdb0438a4a12561ea4c1cbb0f767ad45230e98c4b1dbdfd81d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_VS_HERMES_TERMINAL.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_VS_HERMES_TERMINAL.md','doc: Simplicio — comparação de terminal e benchmark','# Simplicio — comparação de terminal e benchmark

Documento de comparação da experiência de **terminal** entre o `simplicio` (runtime
Rust compilado) e um **agente de referência** (`hermes-agent`, NousResearch), com o
objetivo de deixar o Simplicio **fluido e funcional** no terminal. Gerado durante
uma sessão de engenharia; valores marcados como *observado* foram medidos nesta
máquina.

## Metodologia

- **Mesmo modelo nos dois** (regra de fairness do projeto): OpenRouter
  `deepseek/deepseek-v4-flash` (resolve para `deepseek-v4-flash-*`, provider StreamLake).
  Confirmado funcionando via `POST /chat/completions` (retornou conteúdo).
- **Simplicio**: binário release `target/release/simplicio` (v0.3.26+), offline-first,
  determinístico. Configuração remota via `SIMPLICIO_BASE_URL` / `SIMPLICIO_API_KEY` /
  `SIMPLICIO_MODEL`.
- **Hermes**: `pip install hermes-agent` (0.15.2) em venv isolado; registro de
  provider OpenRouter via `hermes auth`.
- Ambiente headless (sem `webkit2gtk`; o app desktop Tauri não é o foco aqui).

## Diferença de arquitetura (a raiz de tudo)

| Eixo | Simplicio | Hermes |
|---|---|---|
| Modelo mental | **Determinístico-first**: classifica intenção e roda ferramentas Rust; LLM é segundo | **LLM-nativo**: toda virada chama o modelo, que decide tool-calls |
| Chat | Respostas determinísticas (sem chamar LLM por padrão) | Conversa via LLM com tool-calling autônomo |
| Ação | Ponte explícita gated (`act`/`fix`) + checkpoint + evidência | Autônomo (`--accept-hooks`/`--yolo`), edita e roda direto |
| Offline | Sim (responde sem rede) | Não (precisa do provider) |
| Determinismo | Forte (mesmo input → mesma saída) | Fraco (depende do modelo) |

O diferencial do Simplicio é **previsibilidade, custo zero offline e gates**; o
alvo do projeto é **manter o determinismo e ganhar a fluidez** — sem autonomia
escondida.

## Superfície de terminal (observado)

**Hermes** (`hermes --help`): superfície enorme —
`chat, model, fallback, lsp, skills, memory, tools, mcp, checkpoints, computer-use,
cron, webhook, kanban, dashboard, logs, sessions, insights, …` + flags de sessão
(`--resume/--continue`), `--tui`, `--worktree`, `--accept-hooks`, `--yolo`, `--skills`.

**Simplicio**: superfície igualmente rica e **determinística** —
`chat, act, fix/coding-loop, gate, checkpoint/undo, diagnostics, trajectory, deliver,
agent, sprint, memory, mcp, serve, tui, browser, computer-use, voice, …`.
Pontos fortes próprios: `diagnostics` (contrato `simplicio.diagnostics/v1`),
`trajectory` (replay + curator), `deliver` (certificado), `gate`/`undo` (reversível).

## Achados desta sessão (gaps de "fluido e funcional")

1. **🐞 Bug funcional — `--repo` quebrado em comandos task-style.**
   `simplicio fix "..." --repo .` e `simplicio act "..." --repo .` falhavam com
   `--repo requires a value`: o parser tratava `--repo` como flag sem valor e o
   valor (`.`) virava palavra da task. **Corrigido**: flags com valor
   (`runtime_cli_flag_takes_value`) são encaminhadas com o valor. Afetava 4
   comandos (`act`, `fix`, e dois outros task-style).

2. **✍️ Chat defletia ação sem próximo passo.** Um pedido de ação respondia
   "posso pedir uma ação segura para a camada de execução" — sem dizer **como**.
   **Melhorado**: o fallback agora devolve os comandos concretos
   (`simplicio fix/act "<task>" --repo .` prévia; `--confirm` para executar) com a
   moldura de gate + checkpoint reversível + diagnósticos.

3. **🔌 Gap maior (aberto): o `chat` nunca chama o LLM.** Mesmo com chave + modelo
   configurados (e `--remote`), `simplicio chat` retorna apenas strings
   determinísticas — não conversa nem raciocina via modelo. O Hermes é LLM-nativo.
   **Recomendação**: rotear turnos conversacionais/raciocínio do `chat` para o LLM
   (local llama.cpp quando presente; remoto quando configurado/justificado),
   mantendo o determinístico como fallback offline. Isto é o maior salto de
   fluidez e está alinhado à política "determinístico-first, LLM segundo".

4. **Classificação de intenção de código incompleta.** Frases como "faça os testes
   passarem" são classificadas como conversa, não ação — então não alcançam a
   ponte `fix`. Melhorar `classify_task` para intenções de codificação aumenta a
   taxa de "agir de verdade" (liga-se a #190).

## Melhorias aplicadas nesta sessão

- Correção do parsing de `--repo`/`--model`/etc. em `act`/`fix`/coding-loop
  (funcional: o fluxo documentado agora roda).
- Fallback de ação do chat agora é **acionável** (mostra o comando exato + gates).

## Próximos passos recomendados para ganhar fluidez no terminal

1. **Wire `chat` → LLM** (remoto/local) para turnos conversacionais, mantendo
   determinístico offline. ⭐ maior ganho de fluidez.
2. **Streaming de tokens** no `chat`/REPL (o Simplicio hoje imprime de uma vez).
3. **Sessões** (`--resume`/`--continue`) no REPL.
4. **Melhorar `classify_task`** para intenções de codificação dispararem `fix`.
5. **Benchmark de tarefa real**: mesma issue de código (teste falhando) atrás de
   `simplicio fix --confirm` e `hermes --accept-hooks`, com o mesmo modelo, medindo
   sucesso (teste passa), nº de ciclos, tokens e tempo. Requer chave do provider
   ativa na sessão (rotacionar a chave exposta antes de uso prolongado).

## Nota de segurança

Uma chave OpenRouter foi compartilhada em chat durante a sessão para habilitar o
benchmark. Trate-a como **comprometida** e **rotacione** após os testes; nunca a
embuta em binários, commits ou artefatos.

## Benchmark de execução real (run-of-truth) — DeepSeek v4 flash

Task: crate Rust `bench_add` com um teste falhando (`add(a,b)` faz `a - b`;
`assert_eq!(add(2,3), 5)` falha). Mesmo modelo nos dois: OpenRouter
`deepseek/deepseek-v4-flash`. Objetivo: o agente edita e faz `cargo test` passar.

### Simplicio (`fix` / `run`, `--remote`)
- `simplicio fix "..." --repo bench_add --remote --max-cycles 3` →
  `status: max_cycles_reached`, **todos os ciclos com `edit:"error"`**; arquivo
  inalterado; teste continua vermelho.','docs/SIMPLICIO_VS_HERMES_TERMINAL.md','4b5179fc8bb441785782aaf4b765a3b008f650a6b098f9a4ff3af417b02b40d2','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SIMPLICIO_VS_SERENA.md','project_doc','doc://simplicio-runtime/docs/SIMPLICIO_VS_SERENA.md','doc: Simplicio Core vs Serena — the finished MCP product, and why we''re better','# Simplicio Core vs Serena — the finished MCP product, and why we''re better

**Serena** (oraios-software) is an open-source MCP server + IDE plugin that turns any LLM into a coding
agent via the Language Server Protocol (semantic symbol tools: find-symbol, find-references,
symbol-level edits). It''s the closest comparable to what Simplicio Core ships.

**Simplicio Core** is the same coupling shape — an MCP server any LLM host plugs under — but it adds the
layers Serena doesn''t have: **deterministic sandboxed edits, an action gate, a tamper-evident evidence
chain, neural memory, a local-first model bridge, and a reproducible token receipt.** All verified
running on the real `simplicio` binary (lean build, no C/C++).

## Install (Serena-style, already shipped)

```bash
cargo build --release --no-default-features      # lean binary, no C/C++ toolchain
simplicio mcp register                           # registers `serve --mcp --stdio` in every installed
                                                 # agent (Claude Code / Gemini / Codex), self-contained
# then, in your LLM host, Simplicio''s tools are available.
simplicio serve --mcp --stdio                    # the MCP server itself
```

Serena installs via `uvx`/Python + an IDE plugin. Simplicio is a **single self-contained binary** with a
built-in `mcp register` — no runtime, no Python.

## Tool surface (verified live on `simplicio serve --mcp --stdio`)

`simplicio_map` (orientation), `simplicio_memory` (FTS + vector recall), `simplicio_edit` (deterministic
mechanical edit, **now workspace-sandboxed**), `simplicio_gate` (risk classify), `simplicio_validate`
(validation pipeline), `simplicio_run` (gate→bridge→evidence spine). Plus the full CLI: doctor, plan,
run, sprint, workflow, agents, savings, license, lsp, browser, computer-use, …

## Head-to-head (honest)

| Dimension | Serena | Simplicio Core |
|---|---|---|
| Coupling surface | MCP server, any LLM | same (`serve --mcp`) |
| Code edits | LSP-driven (rename/symbol ops) | **deterministic op-plan, zero-token, sandboxed** |
| Semantic navigation | strong (LSP symbols/refs) | **`simplicio_symbol` (def + callers in one) + `simplicio_search` over the CodeGraph index, ~76% token savings** |
| Risk gating | none | **action gate (allow/ask/block)** |
| Evidence / audit | none | **HBP evidence chain + run receipt** |
| Memory | project memory files | **neural memory (FTS + vector)** |
| Local model | host LLM only | **local-first reason bridge (Ollama/llama.cpp/serve/exo)** |
| Token-savings proof | none | **reproducible token receipt** |
| Install | uvx (Python) + IDE plugin | **single binary + `simplicio mcp register`** |
| Distribution | open-source | closed-source, per-seat BYOK |

## Serena''s home turf — gap CLOSED

Serena''s headline is semantic symbol nav (`find_symbol`, `find_referencing_symbols`). Simplicio now
exposes **`simplicio_symbol`** and **`simplicio_search`** over its CodeGraph index — and goes one
better: `simplicio_symbol` returns the **definition AND the callers/references in a single call**
(Serena needs two tools), with the CodeGraph''s ~76% token savings vs a naive scan. Verified live on
`simplicio serve --mcp` (8 tools; `scripts/test-symbol-tools.py` → ALL PASS).

## The pitch

Serena makes any LLM a *coding agent*. Simplicio Core makes any LLM a coding agent **that edits
deterministically, gates risky actions, remembers, runs local-first, and proves what it changed** — the
governed, auditable substrate Serena leaves out. Same one-command install; more product underneath.

Refs: `docs/SIMPLICIO_CORE_BUILD.md` (it builds + serves), `docs/SIMPLICIO_GTM_STRATEGY.md`,
`docs/SIMPLICIO_PLUGGABILITY_SURVEY.md`. Epic #2671.','docs/SIMPLICIO_VS_SERENA.md','525b3b16d2728f869694cb673f7ffe376fb29d6f4f3384593038f9527a268520','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SITE_ACCESS.md','project_doc','doc://simplicio-runtime/docs/SITE_ACCESS.md','doc: Site & distribution access map (no secrets)','# Site & distribution access map (no secrets)

Everything needed to keep working on the marketing site and the public install
channel from any machine. **Secrets are NOT here** — passwords/keys live only in
local gitignored files or `~/.simplicio-loop/`; fetch them from the password manager
or the original machine.

## Repos

| Repo | Path (Mac) | Remote | Branch |
|---|---|---|---|
| Runtime (Rust, closed-source) | `~/Projetos/ai/simplicio-runtime` | `github.com/wesleysimplicio/simplicio-runtime` | `main` |
| Marketing site | `~/Projetos/ai/site_simpleti` | `github.com/wesleysimplicio/site_simpleti` | `master` |
| Public install repo | `~/Projetos/ai/simplicio` | `github.com/wesleysimplicio/simplicio` | `master` |

## Live site

- Domain: `https://simpleti.com.br` (product page `/simplicio/`, docs `/simplicio/docs.html`)
- Hosting: shared host with cPanel, docroot `/public_html`
- Edge cache is aggressive — verify deploys with a cache-buster query string
  (`?v=<timestamp>`).

## FTP deploy

- Script: `deploy/deploy-ftp.sh` in the site repo (lftp `mirror -R`, no delete)
- Host: `ftp.simpleti.com.br` · user: `wesley@simpleti.com.br` · path: `/public_html`
- Credentials file (gitignored, chmod 600): `deploy/.ftp-credentials` with
  `FTP_HOST` / `FTP_USER` / `FTP_PASS` / `FTP_PATH`. **Recreate it on a new
  machine; the password is not in git.**
- Deploy: `cd ~/Projetos/ai/site_simpleti && bash deploy/deploy-ftp.sh`

## Install channels (public)

- mac/linux: `curl -fsSL https://simpleti.com.br/simplicio/install.sh | sh`
- Windows: `irm https://simpleti.com.br/simplicio/install.ps1 | iex`
- GitHub: `curl -fsSL https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.sh | sh`
- Binaries served from `simpleti.com.br/simplicio/dist/` (dir is gitignored in
  the site repo; upload via FTP). Checksums: `publish/SHA256SUMS` in the runtime repo.

## Build / signing

- Release build (embeds the update-channel public key):
  `SIMPLICIO_UPDATE_PUBLIC_KEY="o6YT6wYlhyziBwYk/e4OtjsswOAEcq5o/te1qDSdOq8=" cargo build --release --locked`
- Private signing keys (NEVER in git): `~/.simplicio-loop/license-signing-key.b64`,
  `~/.simplicio-loop/update-signing-key.b64` — copy them between machines manually.
- Version: 1.0.0 public/free distribution. Runtime source remains private;
  publish compiled GitHub Release assets only. Auto-update is disabled by
  default: users see an update-available message and choose when to stage it.

## Payments

- Stripe Checkout via `POST /api/stripe-checkout.php` (site repo `api/`);
  email collected client-side (no Google login). Stripe keys live in
  `config/secrets.php` on the host (gitignored).','docs/SITE_ACCESS.md','da10850b84c84c2c0f9b09960a3ff15d9425d94d912fec0e71121affd02a140d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/skill-catalog/crossaitools-top-marketplaces.md','project_doc','doc://simplicio-runtime/docs/skill-catalog/crossaitools-top-marketplaces.md','doc: Catalog — crossaitools / claudemarketplaces top-starred marketplaces','# Catalog — crossaitools / claudemarketplaces top-starred marketplaces

Source: https://crossaitools.com/marketplaces (aggregator of 21,600+ Claude Code skills).

> We catalog the highest-starred marketplace **sources**, not 21k untrusted
> packages. `superpowers` is already a native Simplicio skill. The rest are
> discovery sources / vet-on-demand entries (clawscan posture).

| marketplace | stars | what it is | Simplicio status |
|---|---|---|---|
| `obra/superpowers` | ~94k | Dev methodology as a skills framework (TDD/debug/review) | superpowers (native SKILL.md) |
| `awesome-claude-code` | ~28.5k | Curated index of Claude Code skills/hooks/commands | discovery source |
| `anthropics/skills` | official | Anthropic''s public Agent Skills reference | discovery source |
| `alirezarezvani/claude-skills` | — | 337 skills/plugins across 13 coding agents | vet on-demand (clawscan) |
| `daymade/claude-code-skills` | — | 66 production-ready dev-workflow skills | vet on-demand (clawscan) |
| `netresearch/claude-code-marketplace` | — | Portable Agent Skills (agentskills.io standard) | vet on-demand (clawscan) |
| `travisvn/awesome-claude-skills` | — | Curated list of Claude Skills + resources | discovery source |
| `aiskillstore/marketplace` | — | Security-audited skills, one-click install | vet on-demand (clawscan) |
| `mhattingpete/claude-skills-marketplace` | — | Git/testing/code-review workflow skills | deliver / pr (native) |','docs/skill-catalog/crossaitools-top-marketplaces.md','8f65f4316da043fc5fa2080a1a0c7f39e1c40043ede8e727f40314b8a96a9c6d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/skill-catalog/datacamp-top-agent-skills.md','project_doc','doc://simplicio-runtime/docs/skill-catalog/datacamp-top-agent-skills.md','doc: Catalog — DataCamp Top Agent Skills (cataloged, not vendored)','# Catalog — DataCamp Top Agent Skills (cataloged, not vendored)

Source: https://www.datacamp.com/pt/blog/top-agent-skills

> These 109 community/ClawHub skills are **cataloged into the neural memory
> for discoverability**, NOT vendored as executable code (third-party,
> API-keyed, network — the project''s own clawscan/skill-flag posture). The
> `native` column maps the ones Simplicio already provides; the rest are
> wired on-demand after vetting.

## Search & Research
| skill | what it does | Simplicio native |
|---|---|---|
| `arxiv-watcher` | Search + summarize ArXiv papers | — |
| `pubmed-edirect` | Query PubMed biomedical literature | — |
| `wikipedia` | Retrieve + summarize Wikipedia | — |
| `google-search` | Web search via Google CSE | tools_web_search |
| `google-search-grounding` | Web search via Gemini grounding | tools_web_search |
| `serper-search` | Google search via Serper.dev | tools_web_search |
| `web-scraper-as-a-service` | Production web scrapers, clean output | tools_web_extract |
| `exa-web-search-free` | Free AI web search via Exa | tools_web_search (Exa backend exists) |
| `newsapi-search` | Query global news sources | — |
| `brightdata` | Scraping/search via Bright Data | — |

## Code Orchestration & Copilot
| skill | what it does | Simplicio native |
|---|---|---|
| `buildlog` | Record/export code sessions as build logs | — |
| `cc-godmode` | Multi-agent software orchestration | agent fabric / workflow |
| `codebuddy-code` | Install CodeBuddy CLI config | — |
| `debug-pro` | Systematic debugging methodology | coding-loop / superpowers |
| `coder-workspaces` | Manage Coder remote workspaces | — |
| `cursor-agent` | Drive the Cursor CLI agent | — |
| `ec-task-orchestrator` | Autonomous multi-agent orchestration | sprint / workflow |
| `codex-orchestration` | Orchestration layer for Codex agents | — |
| `codex-quota` | Check Codex quotas/limits | — |
| `coding-agent` | Run Codex/Claude Code CLIs in one skill | — |

## Git, GitHub, PRs & Repo Intelligence
| skill | what it does | Simplicio native |
|---|---|---|
| `auto-pr-merger` | Auto-check + merge PRs on rules met | pr / babysit-prs |
| `backup` | Backup/restore agent config & skills | backup (Simplicio base) |
| `bat-cat` | Git-aware file viewer (bat styling) | — |
| `bitbucket-automation` | Automate Bitbucket repo/PR flows | — |
| `commit-analyzer` | Analyze commit patterns / risk | — |
| `conventional-commits` | Conventional Commits formatting | native commit convention |
| `deepwiki` | Query repo docs/wiki via MCP | — |
| `gitclassic` | Lightweight GitHub browser for agents | — |
| `gitclaw` | Mirror agent workspace to a GitHub repo | — |
| `github` | GitHub via CLI: issues/PRs/repo actions | github MCP |

## DevOps & Cloud
| skill | what it does | Simplicio native |
|---|---|---|
| `docker-essentials` | Production Docker build/tag/run | docs/PACKAGING + docker |
| `k8-multicluster` | Manage many K8s clusters/contexts | — |
| `nginx-config-creator` | Generate Nginx/OpenResty reverse-proxy | — |
| `appdeploy` | Deploy web apps (backend + DB) | — |
| `aws-infra` | AWS infra via CLI + best practices | — |
| `aws-ecs-monitor` | Monitor ECS + CloudWatch health | — |
| `aws-security-scanner` | Scan AWS for common security issues | — |
| `azd-deployment` | Deploy to Azure Container Apps via azd | — |
| `azure-cli` | Manage Azure via Azure CLI | — |
| `hetzner` | Control Hetzner Cloud via hcloud | — |

## Data Science & ML
| skill | what it does | Simplicio native |
|---|---|---|
| `peft` | Fine-tune LLMs LoRA/QLoRA adapters | — |
| `wandb-monitor` | Monitor/compare W&B runs | — |
| `senior-computer-vision` | End-to-end CV pipelines | — |
| `senior-data-engineer` | Scalable ETL/ELT pipelines | — |
| `hugging-face-model-trainer` | Train/fine-tune LLMs (TRL), GGUF export | — |
| `duckdb` | Fast analytics on CSV/Parquet/JSON | data-analyst (native skill) |
| `senior-data-scientist` | World-class data science | senior-data-scientist (native) |
| `data-analyst` | SQL/spreadsheet analysis + charts | data-analyst (native skill) |
| `hugging-face-datasets` | Create/manage HF datasets | hf MCP |
| `hugging-face-evaluation` | Model-card eval + benchmarks | hf MCP |

## Security & Governance
| skill | what it does | Simplicio native |
|---|---|---|
| `agentguard` | Guardrails to reduce risky agent behavior | action gate |
| `agentmemory` | Encrypted cloud memory across devices | backup (gated) + neural memory |
| `clawscan` | Scan skill packages for security alerts | ecc-harness AgentShield idea |
| `clawsec-feed` | Pull CVE/security advisory signals | — |
| `clawskillshield` | Local scanner for suspicious skills | ecc-harness AgentShield idea |
| `config-guardian` | Validate config changes are safe | transform_guard |
| `prompt-guard` | Defend against prompt injection | untrusted-content contract |
| `skill-flag` | Detect malicious patterns/backdoors in skills | — |
| `skill-scanner` | Scan skills/MCP for spyware behavior | — |
| `skills-audit` | Audit installed skills vs policy | skills audit (native verbs) |

## Communication & Messaging
| skill | what it does | Simplicio native |
|---|---|---|
| `discord-voice` | Real-time Discord voice conversations | gateway/discord + voice |
| `giphy` | Find/send context-matched GIFs | — |
| `mailchannels` | Send email via MailChannels | — |
| `google-messages-openclaw-skill` | SMS/RCS via Google Messages | — |
| `lark-integration` | Connect Lark/Feishu via webhooks | gateway/feishu |
| `clawsignal` | Real-time inter-agent messaging | HBP bus |
| `olvid-channel` | Secure Olvid messenger channel | — |
| `disclawd` | Discord-like env for agents | — |
| `agent-mail` | Mailbox for AI agents | agentmail adapter |
| `whatsapp-styling-guide` | Consistent WhatsApp formatting | gateway/whatsapp |

## Notes & Knowledge
| skill | what it does | Simplicio native |
|---|---|---|
| `logseq` | Read/write a local Logseq vault | — |
| `notesctl-skill-for-openclaw` | Control Apple Notes via CLI ops | — |','docs/skill-catalog/datacamp-top-agent-skills.md','7b4d6fd36c1bc589ddf43b091cad25dec1ac0a58959c314f448010d8fd795b5e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/skill-catalog/sujeitoprogramador-2026.md','project_doc','doc://simplicio-runtime/docs/skill-catalog/sujeitoprogramador-2026.md','doc: Catalog — sujeitoprogramador.com best skills 2026','# Catalog — sujeitoprogramador.com best skills 2026

Source: https://sujeitoprogramador.com/melhores-skills-que-todo-programador-precisa-usar-em-2026/

> The five design/marketing methodology skills were authored as **real
> native SKILL.md files** under `.claude/skills/` (no external dependency).
> The rest route to existing native Simplicio flows — cataloged here so the
> agent can recall the mapping.

| skill | what it does | Simplicio native |
|---|---|---|
| `frontend-design` | Make UI look intentional/production-grade (spacing, type, color, hierarchy) | frontend-design (native SKILL.md) |
| `ui-ux-pro-max` | Design the experience — flows, usability, accessibility, friction | ui-ux (native SKILL.md) |
| `copywriting` | Clear, benefit-led, persuasive UI + marketing copy | copywriting (native SKILL.md) |
| `web-design-guidelines` | Objective do/don''t rulebook for web design + a11y + perf | web-design-guidelines (native SKILL.md) |
| `psychology-of-marketing` | Ethical persuasion principles for conversion (no dark patterns) | psychology-of-marketing (native SKILL.md) |
| `agent-browser` | Drive a real browser for JS-heavy pages / scraping | web-research + `simplicio browser` |
| `token-efficiency` | Cut token spend — map/recall/compress instead of raw context | simplicio-compress + savings ledger |
| `brainstorming` | Refine requirements through dialogue before coding | superpowers (brainstorm phase) |
| `code-review` | Adversarial, multi-stage review of a diff | simplicio-review / `simplicio deliver review` |
| `impeccable` | Only declare done when it actually runs + meets every AC | delivery gates (`simplicio deliver`) |
| `huashu-design` | Persuasive structured-narrative design methodology | frontend-design + copywriting |','docs/skill-catalog/sujeitoprogramador-2026.md','c26b96d5f5d027f3e27400034193007286d5edcf5595012cf24be4088a138551','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/skills/AUTO_SKILL_CREATOR.md','project_doc','doc://simplicio-runtime/docs/skills/AUTO_SKILL_CREATOR.md','doc: Automatic Skill Creator — Issue #2125','# Automatic Skill Creator — Issue #2125

## Overview

When Simplicio detects a recurring pattern in user commands or task outcomes, it
proposes and optionally creates a new skill automatically. Skills are
deterministic TOML+Rust artifacts — no LLM autonomy; the pattern detector is
rule-based and the skill template is a parameterized scaffold.

## Pattern detection

The `PatternDetector` scans the command history (HBP ledger) for:

| Pattern type | Detection rule |
|-------------|----------------|
| `FrequentSequence` | Same N-gram of commands appears >= 5× in 7 days |
| `HighErrorTask` | Task type with error rate > 30% over 10 runs |
| `RepeatedArgs` | Same `--flag value` pair used in > 80% of invocations of a command |

## Skill scaffold

Auto-created skills are placed in `.simplicio-loop/skills/<name>/skill.toml`:

```toml
[skill]
name = "<auto-detected-name>"
version = "0.1.0"
trigger = ["<command-sequence>"]
source = "auto"
created_at = "<iso8601>"

[steps]
# one step per command in the detected sequence
[[steps.step]]
command = "<cmd>"
args = ["<arg1>", "<arg2>"]
```

## AutoSkillCreator struct

```rust
pub struct AutoSkillCreator {
    detector: PatternDetector,
    gate: ActionGate,           // gate before writing any file
    cooldown: Duration,         // min 24h between auto-create proposals for same pattern
    max_auto_skills: usize,     // cap at 20 auto-created skills
}
```

## Flow

1. `detect_patterns(ledger)` — returns `Vec<DetectedPattern>`
2. For each new pattern above threshold: propose `SkillDraft`
3. Gate: classify as `medium` risk (creates files); present to user as suggestion
4. On approval: render scaffold → write `.simplicio-loop/skills/<name>/skill.toml`
5. Register in skill registry; log to HBP evidence chain

## Naming heuristic

- `FrequentSequence`: join command tokens with `-`, truncate at 32 chars
- `HighErrorTask`: `retry-<task-type>`
- `RepeatedArgs`: `<command>-with-<flag-name>`

## Guardrails

- Never overwrite an existing skill without explicit user confirmation
- `max_auto_skills = 20` global cap; warn user when reached
- Auto-skills are tagged `source = "auto"` and can be bulk-deleted via `simplicio skills purge --auto`
- No LLM call in the happy path; LLM may be invoked for a description field only when `--enrich` is passed

## Delivery criteria

- [ ] `PatternDetector` in `src/skill_auto_creator.rs` with 3 pattern types
- [ ] Scaffold writer produces valid `skill.toml`
- [ ] Gate integration: file write is medium-risk, always proposed before applying
- [ ] Test: 5 identical command sequences trigger pattern detection
- [ ] Test: duplicate skill name is rejected without `--force`

## Tracking

GitHub: #2125','docs/skills/AUTO_SKILL_CREATOR.md','1e7358ef2d880234690ad0fcc1735ed2d7afabc5c858562400a7943bc955cb81','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/skills/PROACTIVE_SUGGESTION_LOOP.md','project_doc','doc://simplicio-runtime/docs/skills/PROACTIVE_SUGGESTION_LOOP.md','doc: Proactive Suggestion Loop — Issue #2123','# Proactive Suggestion Loop — Issue #2123

## Overview

Observe user activity, detect patterns, and surface a single relevant suggestion
at the right moment — without interrupting flow. Suggestions are deterministic
(rule-based or memory-backed), never raw LLM output.

## Design principles

- One suggestion at a time; suppress if user is mid-task
- Cooldown: minimum 5 minutes between suggestions to the same user
- All suggestions sourced from memory (`simplicio memory`) or static rule tables
- No unsupervised LLM generation; LLM may rank candidates when explicitly enabled
- Gate: suggestion mutations (e.g. auto-apply a fix) go through `action_gate`

## Trigger taxonomy

| Trigger class | Example condition | Example suggestion |
|---------------|-------------------|-------------------|
| `ErrorRepeat` | Same error type 3× in 10 min | "You''ve hit X three times — want to add a lint rule?" |
| `CommandRepeat` | Same command 5× in session | "Add `alias sim=''simplicio map''` to save keystrokes?" |
| `LongIdle` | No command for 20 min, queue non-empty | "You have 3 tasks pending — resume now?" |
| `SlowBuild` | Last 3 builds > 60s | "Enable incremental compilation? (see #2033)" |
| `StaleMemory` | Memory item not accessed in 30 days | "Prune stale memory item: ''<title>''?" |

## SuggestionEngine struct

```rust
pub struct SuggestionEngine {
    cooldown_tracker: HashMap<String, Instant>,  // user_id -> last suggestion time
    rule_table: Vec<SuggestionRule>,
    memory_client: MemoryClient,
    gate: ActionGate,
}
```

## SuggestionRule

```rust
pub struct SuggestionRule {
    pub id: &''static str,
    pub trigger: Box<dyn Fn(&ActivityWindow) -> bool + Send + Sync>,
    pub suggest: Box<dyn Fn(&ActivityWindow) -> Suggestion + Send + Sync>,
    pub cooldown: Duration,
}
```

## ActivityWindow

Rolling window (default: last 30 minutes) of:
- Command invocations with timestamps
- Error events with type codes
- Build durations
- Memory access log

## Output format

```json
{
  "schema": "simplicio.suggestion/v1",
  "id": "error-repeat-abc123",
  "rule": "ErrorRepeat",
  "message": "You''ve hit E0308 three times — add a clippy lint?",
  "action": {"type": "dry_run", "command": "cargo clippy --fix"},
  "cooldown_until": "2026-06-18T12:35:00Z"
}
```

## Delivery criteria

- [ ] `SuggestionEngine` in `src/skill_proactive_suggestion.rs`
- [ ] 5 built-in rules implemented
- [ ] Cooldown tracker tested (no double-suggestions within window)
- [ ] Gate integration: any `action` field goes through `action_gate` before execution
- [ ] TUI surface: suggestion appears as a dismissable banner line (not blocking)

## Tracking

GitHub: #2123','docs/skills/PROACTIVE_SUGGESTION_LOOP.md','35068f0336644dec6456964e4c06260f3922c9ac8b7b5b23f1b4c5f1c3e88979','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/skills/SIMPLICIO_TASKS_SLIM_PLAN.md','project_doc','doc://simplicio-runtime/docs/skills/SIMPLICIO_TASKS_SLIM_PLAN.md','doc: simplicio-tasks Slim Plan — Lazy-Loaded Orchestrator v6 Modules','# simplicio-tasks Slim Plan — Lazy-Loaded Orchestrator v6 Modules

Issue: #2034

## Problem

The `/simplicio-tasks` skill (orchestrator-v7, `docs/contracts/orchestrator-v7.md`)
currently loads its full module set at startup — including heavy components
(diagnostics engine, trajectory compressor, batch runner, curator agent) that are
only needed for specific task types. This inflates the cold-start time and memory
footprint for every invocation, even lightweight drains.

## Goal

Extract heavy modules into lazy-loaded units so the thin orchestrator core starts
in < 200 ms while the full stack is available on demand.

## Module Classification

### Always-On Core (loaded at startup, < 200 ms)

| Module | Role |
|---|---|
| `intake` | Parse task queue, classify items |
| `issue-factory` | Create GitHub issues from plan |
| `action-gate` | Gate mutations before execution |
| `simplicio-edit` | Deterministic zero-token file edits |
| `drain-loop` | Iterate over task queue, dispatch |
| `savings-reporter` | Token savings line per turn |

### Lazy Group A — Coding Loop (loaded on first `code`/`fix` task)

| Module | Role |
|---|---|
| `diagnostics` | `cargo check` / `clippy` / `cargo test` output parser |
| `coding-loop` | Iterate-until-green (#236) |
| `patch-applicator` | `git apply` deterministic patch |
| `error-recovery` | Classify + retry on build failure |

### Lazy Group B — Planning & Memory (loaded on first `plan`/`arch` task)

| Module | Role |
|---|---|
| `planner` | Multi-step plan decomposition |
| `memory-recall` | FTS + vector pull from neural memory |
| `trajectory` | Session trajectory + compressor |
| `curator-agent` | Dedup / prune / score plan steps |

### Lazy Group C — Bulk Execution (loaded on first `bulk`/`drain-all` task)

| Module | Role |
|---|---|
| `batch-runner` | Parallel fan-out up to 20 agents |
| `auto-scale` | Agent count scaler per queue depth |
| `watcher` | File-system / CI change detector |
| `fast-heavy-router` | Route task to fast-path vs heavy-path |

## Lazy-Load Mechanism

Each lazy group is compiled as a Rust feature flag:

```toml
[features]
orchestrator-core    = []
orchestrator-coding  = ["orchestrator-core"]
orchestrator-planning= ["orchestrator-core"]
orchestrator-bulk    = ["orchestrator-core"]
orchestrator-full    = ["orchestrator-coding","orchestrator-planning","orchestrator-bulk"]
```

At runtime the drain-loop checks the task type before dispatching:

```rust
fn load_group(task: &Task) -> LazyGroup {
    match task.kind {
        TaskKind::Code | TaskKind::Fix  => LazyGroup::Coding,
        TaskKind::Plan | TaskKind::Arch => LazyGroup::Planning,
        TaskKind::Bulk | TaskKind::Drain => LazyGroup::Bulk,
        _                               => LazyGroup::None,
    }
}
```

Groups are loaded via `once_cell::sync::Lazy` — first access pays the init cost;
subsequent tasks of the same type pay nothing.

## Expected Impact

| Scenario | Before | After |
|---|---|---|
| Cold start, simple drain | ~800 ms | < 200 ms |
| First code task | ~800 ms | ~350 ms (A loads) |
| Subsequent code tasks | ~800 ms | ~200 ms (A cached) |
| Full bulk drain | ~800 ms | ~500 ms (all groups) |

## Migration Steps

1. Audit `docs/contracts/orchestrator-v7.md` — label each module with its group.
2. Add feature flags to `Cargo.toml`.
3. Wrap heavy `mod` declarations in `#[cfg(feature = "orchestrator-coding")]` etc.
4. Implement `once_cell::sync::Lazy` wrappers for each group''s init function.
5. Update drain-loop dispatch to call `load_group()` before each task.
6. Benchmark cold-start before and after with `hyperfine`.

## Acceptance Criteria

- [ ] `simplicio-tasks` cold start with an empty queue: < 200 ms (`hyperfine`).
- [ ] First code task dispatched correctly with group A loaded.
- [ ] `cargo test` passes for all feature combinations.
- [ ] `--features orchestrator-full` compiles and passes all existing integration tests.','docs/skills/SIMPLICIO_TASKS_SLIM_PLAN.md','d6ba2971c87ce8aa1e324cf205efc978d4a71d52efc1edfb7ac855dd9968e6eb','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/skills/SKILL_BEHAVIOR_LOOP.md','project_doc','doc://simplicio-runtime/docs/skills/SKILL_BEHAVIOR_LOOP.md','doc: Skill-Driven Behavior Loop — Issue #2116','# Skill-Driven Behavior Loop — Issue #2116

## Overview

Skills that run in a continuous loop, observing state and triggering actions
deterministically. The loop is governed, gated, and does not run unsupervised
LLM calls.

## Architecture

```
SkillBehaviorLoop
  ├── tick_interval: Duration          // configurable, default 30s
  ├── skill_registry: Vec<LoopSkill>   // registered behavior skills
  ├── state_snapshot: StateSnapshot    // last-known runtime state
  └── action_gate: ActionGate          // gate before any mutation
```

## LoopSkill trait

```rust
pub trait LoopSkill: Send + Sync {
    fn name(&self) -> &str;
    fn observe(&self, state: &StateSnapshot) -> Option<BehaviorSignal>;
    fn act(&self, signal: &BehaviorSignal, gate: &ActionGate) -> Result<ActionRecord, String>;
}
```

## Loop lifecycle

1. `tick()` — collect `StateSnapshot` (memory usage, task queue depth, error rate, last user interaction)
2. For each registered skill: call `observe(state)` — if `Some(signal)`, call `act(signal, gate)`
3. `gate.classify(action)` — auto-approved if risk=low; ask if risk=medium; block if risk=high
4. `ActionRecord` appended to HBP evidence ledger
5. Sleep `tick_interval`, repeat

## StateSnapshot fields

- `task_queue_depth: usize`
- `error_rate_1m: f32`
- `last_user_interaction: Instant`
- `memory_used_mb: u64`
- `active_agents: usize`

## Built-in loop skills (phase 1)

| Skill | Signal condition | Action |
|-------|-----------------|--------|
| `IdleGcSkill` | no interaction > 10 min | purge stale memory items |
| `QueueDepthAlertSkill` | queue depth > 50 | log warning + notify user |
| `ErrorRateSuppressorSkill` | error rate > 0.1/s for 60s | pause new task intake |

## Integration points

- `src/organism/` daemon loop — owns the tick scheduler
- `src/action_gate.rs` — classify + approve/deny each action
- `src/hbp.rs` — append `ActionRecord` to verifiable chain
- `simplicio runtime-profile` — expose `tick_interval` in config

## Delivery criteria

- [ ] `LoopSkill` trait compiled in `src/skill_behavior_loop.rs`
- [ ] Three built-in skills implemented and tested
- [ ] Tick loop wired into organism daemon
- [ ] Gate integration tested: medium-risk action prompts user

## Tracking

GitHub: #2116 (Epic)','docs/skills/SKILL_BEHAVIOR_LOOP.md','433fc79c0a1297445ce08793d91d852c1345132f5ab1d19388668d9d760010fd','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SLA.md','project_doc','doc://simplicio-runtime/docs/SLA.md','doc: Simplicio Performance Budget & SLAs','# Simplicio Performance Budget & SLAs

Canonical reference for issue #2226. These are hard ceilings — not aspirational targets.
CI gates and delivery checks enforce them.

---

## 1. CLI Response Time

| Command class            | Budget   | Measurement                                     |
|--------------------------|----------|-------------------------------------------------|
| Simple / deterministic   | < 200 ms | `time simplicio map --repo . --json`            |
| LLM-assisted (local)     | < 2 s    | `time simplicio memory "query" --repo . --json` |
| LLM-assisted (remote VC) | < 10 s   | `time simplicio reason "question" --act`        |

**How to measure:**

```bash
# single shot
time simplicio map --repo . --json > /dev/null

# statistical (requires hyperfine)
hyperfine --warmup 3 --runs 20 ''simplicio map --repo . --json''
```

Threshold is measured from process start to exit on a cold binary (warm binary
is informational). P95 must satisfy the budget, not just median.

---

## 2. Memory Footprint

| State              | Ceiling  | Measurement tool                                      |
|--------------------|----------|-------------------------------------------------------|
| Base (idle REPL)   | < 256 MB | `/usr/bin/time -v simplicio repl --no-llm --exit`     |
| Under load (100 agents) | < 1 GB | `simplicio benchmark --agents 100 --measure-mem` |

**How to measure (Linux/macOS):**

```bash
# resident set size at peak
/usr/bin/time -v simplicio repl --no-llm --exit 2>&1 | grep "Maximum resident"

# continuous monitoring during a run
while sleep 1; do
  ps -o rss= -p $(pgrep simplicio) 2>/dev/null
done
```

On Windows use Task Manager → Details → Memory (private working set), or:

```powershell
Get-Process simplicio | Select-Object WorkingSet64, PrivateMemorySize64
```

---

## 3. Token Efficiency

| Metric                       | Target      | How to verify                                              |
|------------------------------|-------------|------------------------------------------------------------|
| Savings vs raw-read baseline | > 50%       | Token-savings line printed at end of each LLM response     |
| Memory recall hit rate       | > 70%       | `simplicio memory stats --repo .`                          |
| Zero-token mechanical edits  | 100% of decided changes | Audit: no LLM output tokens for `simplicio edit` ops |

**How to measure:**

The MANDATORY token-savings line format is:

```
Simplicio: ~<spent> tokens spent · without Simplicio ~<baseline> · saved ~<saved> (<pct>%)
```

To audit a session, count lines where `pct < 50` — each is a regression.
The `--token-report` flag (coming: issue #237) will export a JSON summary.

---

## 4. Build Time

| Build type         | Ceiling | Command                                              |
|--------------------|---------|------------------------------------------------------|
| Clean release      | < 3 min | `cargo clean && cargo build --release`               |
| Incremental (touch one file) | < 30 s | touch src/main.rs && cargo build --release |
| Tests              | < 60 s  | `cargo test --release`                               |
| Clippy             | < 45 s  | `cargo clippy --release`                             |

**How to measure:**

```bash
# clean build
cargo clean
time cargo build --release

# incremental
touch src/main.rs
time cargo build --release
```

CI reports wall-clock job time in the Actions summary — compare against the
ceilings above after every build-touching commit.

---

## 5. Enforcement

- **CI gate:** a `sla-check` step in `.github/workflows/ci.yml` runs
  `hyperfine` against the two CLI tiers and fails the build if P95 exceeds
  budget. (Implementation: issue #2226 follow-up.)
- **Delivery gate:** `simplicio deliver check` will embed a `perf_budget` check
  reading this file as ground truth (issue #251).
- **Memory regression:** tracked via `cargo-criterion` nightly benchmark
  artifacts stored in `benches/`.

---

*Last updated: 2026-06-18 — issue #2226*','docs/SLA.md','78a2b47611160668ad1230e526f39e07a140759188b549f72276cc3b71cffa85','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/social-media-ops/facebook.md','project_doc','doc://simplicio-runtime/docs/social-media-ops/facebook.md','doc: Facebook Playbook — Simplicio Agents','# Facebook Playbook — Simplicio Agents

**Issue #315** | Platform: `facebook`

## Algorithm Signals (2026)

1. **Meaningful comments** — deep replies, not just "nice!"
2. **Shares to friends/family** — highest-weight signal
3. **Time spent** on post / profile
4. **Reels watch time** — same as Instagram Reels algorithm

## Ecosystem Context

- Organic Page reach: very low (~2–5%); ads almost mandatory for scale
- **Groups**: Still highly effective for niche communities
- Meta ecosystem: cross-post with Instagram via Business Suite
- Reels on Facebook: distributed well, especially in Groups and Reels tab

## Account Setup

- **Professional Page** + Meta Business Manager
- Link to Instagram account for cross-posting
- Groups: create or moderate niche groups (e.g., "Dev BR Rust & Agents", "Nearshore Brasil")
- Admin tools for Group moderation

## Content Strategy

### Pages (Organic)

- Posts with high text + image/carousel for comments
- Reels cross-posted from Instagram (same video, new caption angle)
- Native video (uploaded directly) outperforms links
- Boost top-performing organic posts with ads ($5–20 for reach)

### Groups (High ROI)

- Questions and polls generate most engagement
- Step-by-step guides get saves and comments
- No spam — community-first approach
- Behind-the-scenes content from the dev journey
- Pinned posts with resources

### Reels

- Cross-post from Instagram; adjust caption for FB audience
- Slightly longer hooks acceptable (3–5s)
- Add subtitles (many watch without sound)

## Posting Times (UTC-3 BR)

- **Peak**: 19h–22h weekdays, weekends 10h–14h
- **Groups**: test for each group''s peak (use Group Insights)
- **Pages**: Wed–Thu perform well

## API Integration

```
Meta Graph API (same credentials as Instagram)
  POST /{page-id}/feed            → text/link/photo post
  POST /{page-id}/videos          → video upload
  POST /{page-id}/live_videos     → Live
  GET  /{page-id}/insights        → page analytics
  POST /{group-id}/feed           → group post (limited; requires group access)
```

Groups API is restricted — may require manual moderation for group posts.

## Ads Strategy

- **Lookalike Audiences BR**: build from existing followers/email list
- **Retargeting**: website visitors + video viewers
- **Lead Ads**: collect emails directly (no landing page friction)
- Budget: start with R$30–50/day per campaign, optimize for leads/conversions
- Funnel: Reels ad (awareness) → carousel (consideration) → lead ad (conversion)

## Skill Interface

```
simplicio social post --platform facebook --type post  --caption "…"
simplicio social post --platform facebook --type video --caption "…" --media /path/to/video
simplicio social analyze --platform facebook --period 7d
```

## Evidence Fields (SocialPostReceipt)

Key fields: `reach`, `impressions`, `likes`, `comments`, `shares`

## Multi-Agent Flow

```
Content Agent  → writes post text optimized for comments
Group Agent    → manages Group posts + moderates comments (human approval for bans)
Ads Agent      → manages boosting budget, creates lookalike audiences
Analyst Agent  → pulls Page Insights, monitors Group health, flags engagement drops
```

## Risks

- Organic reach so low that effort without ads may have poor ROI; track cost/engagement
- Group spam → permanent ban from Group; always human-review before posting in groups
- Ad account suspension → avoid click-bait ad copy, use real images, comply with policies
- LGPD: Lead ad data → explicit consent, data retention policy required','docs/social-media-ops/facebook.md','56bb8edeaf45c4375c2d65221e49e231142ef6d0af5b0942b11dd7ac347b21c9','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/social-media-ops/instagram.md','project_doc','doc://simplicio-runtime/docs/social-media-ops/instagram.md','doc: Instagram Playbook — Simplicio Agents','# Instagram Playbook — Simplicio Agents

**Issue #311** | Platform: `instagram`

## Algorithm Signals (2026)

1. **Watch time / retention** — most important for Reels; hook in ≤3s
2. **DM shares** — strongest signal for non-follower distribution
3. **Saves** — indicates durable value; optimize carousels for saves
4. **Likes per reach** — drives followers feed distribution

## Account Setup

- Use **Creator** or **Business** account (required for API access)
- Connect to Meta Business Suite for cross-posting and analytics
- Complete warm-up: 2 weeks of manual posting before agent automation
- Auth: Meta Graph API long-lived token (refresh handled by runtime)

## Content Formats

| Format    | Frequency     | Primary goal         | Optimal length |
|-----------|---------------|----------------------|----------------|
| Reels     | 3–5×/week     | Discovery, growth    | 7–30s          |
| Carousel  | 2–4×/week     | Saves, authority     | 5–10 slides    |
| Stories   | Daily or 3–5× | Retention, warmth    | 1–5 stories/day|

## Posting Times (UTC-3 BR)

- **Best**: 18h–23h weekdays (especially Wed–Thu)
- **Secondary**: 07h–09h (before-work scroll)
- **Consistency** beats volume — 1 great Reel + 3–5 Stories daily

## Reel Hook Formula

```
[Visual shock OR bold text overlay OR trend sound] + value in 15s + CTA share/DM/save
```

- Include: "Manda pra quem precisa ver" (send to someone who needs this)
- Screen recordings work well for dev/tech content

## Carousel Structure

- Slide 1: Hook (bold claim, question, or surprising stat)
- Slides 2–8: Value (step-by-step, listicle, comparison)
- Last slide: CTA (follow, save, DM for template)
- Optimize captions for keywords + storytelling

## API Integration

```
Meta Graph API v19+
  POST /me/media          → upload photo/video
  POST /me/media_publish  → publish staged media
  GET  /{media-id}/insights → performance
  GET  /me/stories        → story insights
```

Auth: OAuth 2.0, Business Manager. Rate: ~200 calls/hr per app.

## Skill Interface

```
simplicio social post --platform instagram --type reel   --caption "…" [--at ISO8601]
simplicio social post --platform instagram --type carousel --caption "…" --media /path/to/zip
simplicio social post --platform instagram --type story  --caption "…" --media /path/to/img
simplicio social analyze --platform instagram --period 7d
```

## Evidence Fields (SocialPostReceipt)

Key fields to track: `watch_time_pct`, `dm_shares`, `saves`, `reach`, `impressions`

## Shadowban Detection

- Sudden reach drop (>50% week-over-week) → flag
- Posts not appearing in hashtag search → potential shadowban
- Analyst Agent checks `reach` trend in evidence ledger weekly

## Risks

- Automation without API → ban risk; always use Meta Graph API
- Burst posting → space posts ≥4h apart
- Copyright music → use licensed or original audio
- LGPD: no personal data stored from comments/DMs without consent','docs/social-media-ops/instagram.md','e5da36307189fd0b618d57ccbe9e0b72270d401afa4b6d90e1c833c5833c1d70','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/social-media-ops/pinterest.md','project_doc','doc://simplicio-runtime/docs/social-media-ops/pinterest.md','doc: Pinterest Playbook — Simplicio Agents','# Pinterest Playbook — Simplicio Agents

**Issue #316** | Platform: `pinterest`

## Platform Context (2026)

Pinterest is a **visual discovery + purchase intent** platform, not a social feed.
Pins can generate traffic for months or years — long content lifecycle.
High ROI for e-commerce, digital products, infographics, productivity tools.

## Algorithm Signals

1. **Relevance** — pin content matches user interests and search intent
2. **Freshness** — new pins get initial distribution boost
3. **Visual quality** — high-res, vertical images perform best
4. **SEO** — title, description, alt text are heavily weighted
5. **Saves (repins)** — primary engagement signal

## Account Setup

- **Business Account**: required for analytics, ads, Rich Pins, API
- Rich Pins: sync product metadata (price, availability) automatically
- Boards: organized by theme (e.g., "AI Tools BR", "Produtividade Dev", "Nearshore Setup")
- Profile: keyword-rich bio, link to landing page
- Verified Merchant: for e-commerce pins

## Content Strategy

### Pin Types

| Type         | Format        | Goal                        |
|--------------|---------------|-----------------------------|
| Static Pin   | Vertical image (2:3) | Traffic, saves         |
| Video Pin    | 4–15s loop    | Awareness, engagement        |
| Idea Pin     | 2–20 slides   | Educational, followers       |
| Carousel Pin | 2–5 images    | Product showcase             |

### Image Specs

- Format: vertical 2:3 ratio (1000×1500px minimum)
- Bold text overlay with keyword
- High contrast, professional quality
- Face or result in image increases clicks

### SEO (Critical)

```
Title: 50–60 chars, primary keyword first
  e.g. "Runtime Rust para Agentes IA — Simplicio Yool 2026"
Description: 150–300 chars, 2–3 relevant keywords, PT-BR
Alt text: describe the image with keywords
Board name: keyword-rich (e.g. "Dev Tools Brasil")
```

Long-tail keywords work best: "melhor runtime para agentes ai rust brasil",
"como criar ai agent local", "ferramentas dev br produtividade 2026".

## Posting Schedule

- **Consistency**: 5–10 pins/day for active growth (can include repins)
- **Best times**: 19h–23h (especially Friday–Sunday)
- **Fresh content**: at least 1–2 new original pins/day
- Pinterest rewards accounts that pin consistently over time

## API Integration

```
Pinterest API v5
  POST /v5/pins                    → create pin
  POST /v5/boards                  → create board
  GET  /v5/pins/{pin_id}/analytics → pin performance
  GET  /v5/user_account/analytics  → account-level metrics
  POST /v5/ad_accounts/{id}/campaigns → ads
```

Auth: OAuth 2.0. Rate limits per endpoint in docs.
Image gen integration: Grok Imagine or Higgsfield for visual pin creation.

## Skill Interface

```
simplicio social post --platform pinterest --type pin --caption "Title|Description" --media /path/to/image
simplicio social analyze --platform pinterest --period 30d
simplicio social trends  --platform pinterest --region br
```

## Multi-Agent Flow

```
Research Agent  → identifies trending keywords via Pinterest API /trends/interests
Visual Agent    → generates pin image (Grok Imagine) with text overlay + SEO title
Pinner Agent    → creates pin via API with optimized metadata
Analyst Agent   → monitors saves, impressions, outbound clicks; flags low performers
```

## Evidence Fields (SocialPostReceipt)

Key fields: `impressions`, `saves` (repins), `shares` (outbound clicks)

## E-commerce Integration

- Rich Pins: add product schema to website for automatic price sync
- Catalog: upload product CSV to Pinterest Business for Shopping pins
- Ads: Promoted Pins for top-of-funnel, Shopping Ads for conversion
- Track: saves → product page visits → purchases in evidence ledger

## Risks

- Low-quality images → algorithm de-prioritizes; always generate high-res
- Copyright on images → only use licensed or AI-generated originals
- Spam behavior → pinning identical content to many boards = penalized
- Seasonal content: use seasonal keywords for time-sensitive boosts
- LGPD: no personal data from analytics stored without consent','docs/social-media-ops/pinterest.md','55beaf24c5f04766591c8e7506e47f02f8606794cd1bfca01512b155d3699af4','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/social-media-ops/README.md','project_doc','doc://simplicio-runtime/docs/social-media-ops/README.md','doc: Social Media Ops — Cross-Platform Framework','# Social Media Ops — Cross-Platform Framework

**Epic #310** — Playbook for Simplicio agents operating social accounts.

## Overview

Simplicio agents can post, schedule, analyze, and optimize content across all
major platforms. Every action flows through the **Action Bridge (#230)** and is
logged to the **Evidence Ledger** as a `SocialPostReceipt`
(`simplicio.social-post-receipt/v1`).

## CLI

```
simplicio social post      --platform <p> --type <t> --caption "…" [--at ISO8601] [--dry-run]
simplicio social analyze   --platform <p> [--period 7d]
simplicio social trends    --platform <p> [--region br]
simplicio social platforms
```

Supported platforms: `instagram`, `x`, `tiktok`, `kwai`, `youtube`, `facebook`, `pinterest`

## Multi-Agent Orchestration (Yool)

```
Content Planner Agent
  → Caption / Visual Gen Agent   (LLM + image gen)
  → Scheduler Agent              (picks optimal time, emits SocialPostReceipt)
  → Engager Agent                (monitors replies/comments, proposes responses)
  → Analyst Agent                (pulls API analytics, updates evidence, flags issues)
```

Each agent writes its state to the Yool tuple-space; the Token Governor limits
daily LLM and image-gen spend per platform against expected ROI.

## Evidence Schema

`schemas/social-post-receipt.schema.json` — records:
- platform, post_type, post_id, caption_hash
- scheduled_at, status (queued | posted | failed | dry_run | requires_approval)
- performance counters: reach, impressions, likes, comments, shares, saves,
  dm_shares, watch_time_pct, completion_rate

## Platform Playbooks

| Platform   | File                      | Key metric              |
|------------|---------------------------|-------------------------|
| Instagram  | [instagram.md](instagram.md) | Watch time %, DM shares |
| X.com      | [x-twitter.md](x-twitter.md) | Replies, bookmarks      |
| TikTok/Kwai| [tiktok-kwai.md](tiktok-kwai.md) | Completion rate     |
| YouTube    | [youtube.md](youtube.md)  | Watch time, CTR         |
| Facebook   | [facebook.md](facebook.md)| Comments, Groups        |
| Pinterest  | [pinterest.md](pinterest.md) | Saves, outbound clicks |

## Token Economy

- Caption gen: ~400-800 tokens/post (LLM)
- Image gen (Grok Imagine / Higgsfield): priced per generation
- All costs tracked in `SocialPostReceipt.token_cost`
- Daily budget enforced by Token Governor via Yool policy tuple

## Human-in-the-Loop

DM responses and first posts on a new account always go through
`requires_approval` status. The Scheduler Agent upgrades to `queued` only after
human approval or after the account has a confirmed warm-up history in the ledger.

## Brazil-Specific

- Timezone: UTC-3 (São Paulo)
- Peak hours: 18h–23h weekdays, mornings on weekends
- Language: PT-BR natural, avoid forced formality
- Trends: TikTok BR, X devBR community, Kwai popular niches','docs/social-media-ops/README.md','741ff8a7de6653999396366f17dd54d0703a7f7d153b86c6eec119b0d60b1886','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/social-media-ops/tiktok-kwai.md','project_doc','doc://simplicio-runtime/docs/social-media-ops/tiktok-kwai.md','doc: TikTok & Kwai Playbook — Simplicio Agents','# TikTok & Kwai Playbook — Simplicio Agents

**Issue #313** | Platforms: `tiktok`, `kwai`

## Algorithm Signals (2026)

1. **Watch time % / Completion rate** — most important; aim >50%
2. **Rewatch rate** — indicates highly engaging content
3. **Shares to DM / external** — strong non-follower distribution signal
4. **Likes + Comments** — secondary but still counted
5. **Early scroll-away** — negative signal; hook must be instant

## Platform Differences

| | TikTok | Kwai |
|---|---|---|
| Global reach | Very high | Strong in BR/LatAm |
| Niche saturation | Higher | Lower — growth easier |
| Algorithm | FYP-based | Similar FYP |
| Dev/tech content | Growing | Less competition |
| API | Research/Commercial (restricted) | Less documented |

## Posting Times (UTC-3 BR)

- **Peak**: 18h–23h (post-work), especially Tue–Sat
- **Secondary**: 07h–09h (morning scroll)
- **Frequency**: 1–3 high-quality videos/day; consistency > volume

## Hook Formula (First 1.5s)

```
[Visual shock OR bold text OR trend sound + twist]
→ Value delivery in 15–60s
→ CTA: follow, duet, share, "manda pra quem precisa"
```

BR hooks that work:
- "O erro que 90% dos devs BR cometem com AI…"
- "Como eu montei meu runtime em Rust gastando R$0"
- "Dica de SP que mudou minha produtividade"

## Content Formats

| Format        | Length   | Goal               |
|---------------|----------|--------------------|
| Standard short | 15–60s  | FYP reach          |
| Extended       | 1–3min  | Authority          |
| Duet / Stitch  | Any     | Engagement, reach  |
| Series (Part N)| 15–60s  | Follow conversion  |

## Kwai BR Strategy

- Audience: more popular, practical, less pure-tech
- Niches: finanças, tutoriais práticos, vida real, humor
- Language: even more colloquial PT-BR, SP references
- Less competition for dev content → faster growth

## API Integration

```
TikTok: Commercial API (requires application + approval)
  POST /v2/post/publish/video/init   → upload
  GET  /v2/video/list               → video metrics
  GET  /v2/research/video/query     → Research API (restricted)

Kwai: Limited public API — fallback to browser-use with human approval
```

**Recommended**: For new accounts, prioritize human-in-the-loop posting
until account has 2+ weeks history; then enable queued automation.

## Skill Interface

```
simplicio social post --platform tiktok --type short --caption "…" --media /path/to/video
simplicio social post --platform kwai   --type short --caption "…" --media /path/to/video [--dry-run]
simplicio social analyze --platform tiktok --period 7d
simplicio social trends  --platform tiktok --region br
```

## Evidence Fields (SocialPostReceipt)

Key fields: `watch_time_pct`, `completion_rate`, `shares`, `likes`, `comments`

## Trend Scout Agent

```
Input:  platform=tiktok, region=br
Output: list of trending sounds/hashtags + suggested BR/dev twist
Flow:   TikTok Research API → filter relevance → LLM generates twist + script hook
Yool:   stores (sound_id, trend_score, used_at) to avoid repeats
```

## Shadowban Detection

- Views stagnate at <500 for non-followers
- FYP reach drops to 0 (all views from followers only)
- No appearance in hashtag searches
- Mitigate: vary content, natural posting intervals, no burst uploads

## Risks

- Gray-market bots → ban waves common in 2026; use official API only
- Burst posting → space >2h apart
- Copyright music → use TikTok''s licensed sound library or original
- Duplicate content → always produce variations; same video twice = penalized','docs/social-media-ops/tiktok-kwai.md','7b736c9a8402c4535d8298135af1094fbb84804e6744b61c06b36e4ed21571a8','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/social-media-ops/x-twitter.md','project_doc','doc://simplicio-runtime/docs/social-media-ops/x-twitter.md','doc: X.com (Twitter) Playbook — Simplicio Agents','# X.com (Twitter) Playbook — Simplicio Agents

**Issue #312** | Platform: `x`

## Algorithm Signals (2026)

1. **Replies** — most weighted signal for For You distribution
2. **Reposts (with comment)** — second strongest
3. **Bookmarks** — saves signal; valuable for threads
4. **Early engagement** — first 1–2 hours after posting are critical

## Account Setup

- X Premium / Verified badge: improves reach, enables edit, longer posts
- Business/Professional account: analytics + API access
- Bio: keywords + CTA + link (Linktree or landing page)
- Warm-up: 2 weeks manual posting + community engagement before automation

## Content Formats

| Format       | Goal                      | Optimal timing        |
|--------------|---------------------------|-----------------------|
| Threads (5–15 tweets) | Authority, saves, shares | Sun–Thu 07h/18h–22h |
| Short tweets | Engagement, replies       | Real-time, trends     |
| Polls        | High engagement, FYP boost| Any day               |
| Quote tweets | Trend-jacking             | Within 24h of trend   |

## Posting Times (UTC-3 BR)

- **Before work**: 07h–09h
- **Lunch**: 12h–13h
- **Evening**: 18h–22h (Tue–Thu best)
- Threads: post at high-activity times to maximize early replies

## Thread Formula

```
Tweet 1: Hook (bold claim / surprising stat / open question)
Tweets 2–N: Development (numbered points, code snippets, data)
Last tweet: CTA (reply "agree?", repost, follow, link)
```

BR topics that work: Rust/AI deep dives, GitHub issue-to-feature stories,
nearshore lessons, "por que X falha em produção", prompt engineering vs contracts.

## API

```
X API v2 (paid tiers)
  POST /2/tweets          → post tweet
  POST /2/tweets (reply)  → reply to tweet
  GET  /2/tweets/search/recent → trends (free tier limited)
  GET  /2/users/:id/tweets → user timeline
```

Free tier: very limited; Basic tier (~$100/mo) for moderate automation.
Rate limit handler with exponential backoff required in runtime.

## Skill Interface

```
simplicio social post --platform x --type thread --caption "Thread content…"
simplicio social post --platform x --type post   --caption "Short tweet"
simplicio social analyze --platform x --period 7d
simplicio social trends  --platform x --region br
```

## Evidence Fields (SocialPostReceipt)

Key fields: `impressions`, `likes`, `shares` (reposts), `comments` (replies), `saves` (bookmarks)

## Virality Formula BR

```
Emotion + Utility + Surprise + Identity ("nós devs BR")
+ explicit CTA for repost/reply
+ timing aligned with trend or event
```

## Shadowban Detection

- Tweets not appearing in search for non-followers
- Impression drop >40% week-over-week
- Analyst Agent checks impressions trend; flag if anomaly detected

## Risks

- Automation spam → X detects aggressive bots; use official API
- Mass DMs → never; ToS violation
- Misinformation / hate → account suspension
- API cost: monitor monthly spend; Basic tier quota strict','docs/social-media-ops/x-twitter.md','ba3a290c308995b9035f8a81fdcedf1188430664cb73f4550f4fec98abb68b18','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/social-media-ops/youtube.md','project_doc','doc://simplicio-runtime/docs/social-media-ops/youtube.md','doc: YouTube Playbook — Simplicio Agents','# YouTube Playbook — Simplicio Agents

**Issue #314** | Platform: `youtube`

## Algorithm Signals (2026)

### Long-form

1. **Total watch time** — absolute minutes watched across channel
2. **Average view duration** — % of video watched; aim >50%
3. **CTR (thumbnail + title)** — impressions → views conversion; aim >5%
4. **Session time** — videos that keep viewers on YouTube longer are rewarded

### Shorts

1. **Completion rate** — % who watched to end; aim >70%
2. **Browse feeds reach** — algorithm serves to non-subscribers
3. **Volume** — Shorts reward consistency more than long-form

## Content Strategy

### Long-form (8–20min+)

```
Title: 60-70 chars, keyword front-loaded, curiosity + benefit
  e.g. "Como Construí um Runtime Nativo em Rust para Agentes AI | Simplicio Yool"
Thumbnail: face expression + bold text + high contrast colors
Structure:
  Intro hook 10-15s (problem + promise)
  Content with chapters/timestamps
  CTA at 30s, mid-roll, end screen
  End screen + cards
```

BR topics: Rust/agents tutorials, GitHub issues → feature stories,
AI tool comparisons (local vs cloud), nearshore lessons, builder journey.

### Shorts (15–60s)

- Hook: instant value or question
- Repurpose: clip from long-form + new hook text
- CTA: "subscribe", "full video in description"
- Shorts feed long-form (teaser → watch full)

## Posting Schedule (UTC-3 BR)

| Format    | Frequency      | Best times        |
|-----------|----------------|-------------------|
| Long-form | 1×/week        | 19h–22h, Sat–Sun  |
| Shorts    | 3–7×/week      | 18h–23h daily     |

Consistency matters more than volume for long-form.

## SEO

- Description: 200+ words, timestamps, links, keyword variations
- Tags: 10–15 mix of broad + specific + long-tail PT-BR
- Chapters: always add for long-form
- End screens + cards for session time
- Community posts: use between uploads to maintain algorithm signals

## API Integration

```
YouTube Data API v3
  POST /youtube/v3/videos?part=snippet,status → upload
  PUT  /youtube/v3/videos?part=snippet        → update metadata
  GET  /youtube/v3/videos?chart=mostPopular   → trending
  GET  /youtube/v3/channels?part=statistics   → analytics
  GET  /youtube/v3/videoAnalytics             → detailed metrics
```

Quota: 10,000 units/day free tier. Upload costs ~1,600 units. Cache aggressively.

## Skill Interface

```
simplicio social post --platform youtube --type video --caption "Title|Description" --media /path/to/video
simplicio social post --platform youtube --type short --caption "…" --media /path/to/short.mp4
simplicio social analyze --platform youtube --period 28d
simplicio social trends  --platform youtube --region br
```

## Multi-Agent Flow

```
Research Agent    → identifies trending topics, keyword gaps
Script Agent      → writes long-form script with hooks + CTAs + chapters
Visual Agent      → generates thumbnail variants (A/B test)
Upload Agent      → publishes via API, sets metadata, adds to playlists
Analyst Agent     → monitors CTR + retention, flags drop-off points, suggests edits
```

## Thumbnail A/B Testing

Generate 2–3 variants per video via image gen tool. Track CTR per variant
in the evidence ledger. Analyst Agent picks winner after 48h, updates metadata.

## Evidence Fields (SocialPostReceipt)

Key fields: `watch_time_pct`, `impressions`, `likes`, `comments`, `shares`

## Retention Analysis

Pull `youtubeAnalytics.query` audience retention graph.
Flag videos with >40% drop-off in first 30s — these need hook improvements.

## Risks

- Quota overrun → implement caching + batching in runtime
- Copyright → never use unlicensed music; use YouTube Audio Library
- Thumbnail clickbait → honest thumbnails, else CTR spike then retention tank
- LGPD → no personal data stored from comments without consent','docs/social-media-ops/youtube.md','60270bf47c24cc1dd65261cdb67e3727bce54873e4fd3e74d6b31f39f054708f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/specs/HBI-v1-cross-language.md','project_doc','doc://simplicio-runtime/docs/specs/HBI-v1-cross-language.md','doc: HBI v1 cross-language conformance','# HBI v1 cross-language conformance

The container contract has one deterministic golden vector at
`tests/golden/hbi-v1-example.hbi.b64`. It contains schema ID
`example-schema!!`, flags `3`, section `1 = strings`, and section `2 = blob`.

The reference Rust implementation and the dependency-free Python and Node
readers must all:

- validate magic, version, endianness, alignment, reserved bytes, total length,
  section bounds, duplicate kinds, zero padding, and both checksum layers;
- expose section payloads only after complete validation;
- preserve unknown section kinds as opaque bytes;
- reject a one-byte mutation of the vector.

Run the conformance check without network access or project-specific tooling:

```sh
base64 -d tests/golden/hbi-v1-example.hbi.b64 > /tmp/hbi-v1-example.hbi
python tools/hbi_conformance.py /tmp/hbi-v1-example.hbi
node tools/hbi_conformance.mjs /tmp/hbi-v1-example.hbi
```

The vector covers the HBI container layer only. String-table, blob-table, and
semantic index schemas remain versioned by their owning consumers; they must
not be inferred from the generic container or from `MmapIndex`.','docs/specs/HBI-v1-cross-language.md','63d29d568b2735f0bf169c0bbfde3002cc10556f7abf9ab7efca2150266bd531','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/specs/HBI-v1.md','project_doc','doc://simplicio-runtime/docs/specs/HBI-v1.md','doc: HBI v1 — mmap-backed bounded index container','# HBI v1 — mmap-backed bounded index container

Status: implementation slice for issue #3494. This document defines the
container contract implemented by `src/hbi/`. It does not relabel the legacy
`src/memmap_index.rs` cache as HBI.

HBI is the canonical read-mostly container for indexes, graphs, and snapshots.
HBP remains the append-only, hash-chained format for receipts, evidence, and
lineage. TOML remains the human-authored configuration format. HBI is a binary
contract; JSON is not a representation of any HBI field or payload.

## Compatibility boundary

A producer writes a complete HBI file and publishes it as one artifact. A
reader must validate the complete byte range, directory, section bounds,
per-section checksums, padding, and aggregate checksum before exposing a
section slice. The backing byte range may be a `memmap2::Mmap`; the owner of
that mapping must outlive the HBI reader. This slice does not add legacy-layout
migration or atomic publication.

Version 1 is little-endian only. A reader rejects other endianness markers,
unknown format versions, truncated input, integer overflow, overlapping
sections, non-zero padding, and out-of-bounds offsets. Unknown section kinds
are retained in the directory and can be read as opaque bytes; a semantic
consumer decides whether an unknown kind is ignorable or required.

## File layout

All integer fields are unsigned and little-endian. Offsets and lengths are
64-bit. Every section offset is aligned to 8 bytes. Alignment gaps are present
in the file and must contain zero bytes. The total file length is exact: extra
trailing bytes are invalid.

### Fixed header (112 bytes)

| Offset | Size | Field | Rule |
|---:|---:|---|---|
| 0 | 8 | magic | ASCII bytes `HBI\\0v1\\0\\0` |
| 8 | 2 | format version | `1` |
| 10 | 2 | header length | `112` for v1; 8-byte aligned |
| 12 | 1 | endianness | `1` = little-endian; other values rejected |
| 13 | 1 | alignment | `8`; other values rejected |
| 14 | 2 | reserved | zero in v1 |
| 16 | 4 | container flags | bit assignments are schema-owned; unknown bits are preserved |
| 20 | 4 | section count | at most 4096 |
| 24 | 8 | total length | must equal the mapped byte range length |
| 32 | 16 | schema ID | opaque stable identifier for the payload schema |
| 48 | 32 | schema fingerprint | SHA-256 of the canonical schema descriptor |
| 80 | 32 | content checksum | SHA-256 over the canonical integrity stream below |

The header and directory are fixed in this implementation slice. Future
backward-compatible header extensions must increase `header length`, preserve
the fixed prefix, and be explicitly versioned; a v1 reader rejects extensions
it cannot interpret.

### Section directory (56 bytes per entry)

The directory starts at `header length` and contains exactly
`section count` entries.

| Offset | Size | Field | Rule |
|---:|---:|---|---|
| 0 | 4 | section kind | stable numeric kind; unknown kinds are opaque |
| 4 | 4 | section flags | section-schema-owned bits; unknown bits are preserved |
| 8 | 8 | offset | absolute file offset, 8-byte aligned |
| 16 | 8 | length | byte length; checked addition required |
| 24 | 32 | section checksum | SHA-256 of exactly the section payload bytes |

A v1 encoder emits section kinds in ascending order and rejects duplicate
kinds. A decoder preserves directory order and exposes all validated kinds,
including unknown kinds.

The first semantic section kinds are reserved as follows:

| Kind | Meaning |
|---:|---|
| 1 | string table |
| 2 | blob table |
| 3 | index/graph payload |
| 0x80000000..0xffffffff | extension-owned kinds |

The table payload schemas are schema-owned and must use stable 64-bit IDs;
ID zero is reserved as the null/unset reference. Their payload definitions
will be added by the semantic index slice without changing the container
header or directory contract.

## Integrity stream

The aggregate checksum is calculated over this exact logical sequence, in
directory order, without implicit text encoding:

1. version as a 2-byte little-endian integer;
2. header length as a 2-byte little-endian integer;
3. the two one-byte markers (endianness, alignment);
4. flags, section count, and total length in their little-endian widths;
5. the 16-byte schema ID;
6. the 32-byte schema fingerprint;
7. for every directory entry: kind, flags, offset, and length in their
   little-endian widths, followed by the exact section payload bytes.

The per-section checksum covers only the section payload. Padding is not part
of either checksum and is required to be zero. This makes directory mutation,
payload corruption, and non-canonical padding fail closed.

## Encoder and reader API

The reference implementation provides:

- `HbiBuilder`: deterministic v1 encoder with bounded section count,
  ascending-kind ordering, duplicate rejection, checked size arithmetic, and
  per-section plus aggregate SHA-256 checksums;
- `HbiReader::open(&[u8])`: validates the complete range before returning;
- `HbiReader::section(kind)`: returns a zero-copy `&[u8]` slice tied to the
  caller-owned byte range;
- `HbiReader::sections()` and `metadata()`: inspect metadata and directory
  without dumping payloads;
- `verify_schema_fingerprint`: explicit consumer-side schema compatibility
  check.

No reader may fall back to `MmapIndex`, JSON, or another unversioned layout
after HBI validation fails.

## File-backed publication
`src/hbi/file.rs` provides the file boundary for the container:

- `HbiMapped::open` memory-maps a file and validates the complete byte range before returning;
- `HbiMapped::reader` creates a borrow-scoped zero-copy reader, so the map always outlives the reader;
- `publish_atomic` validates bytes, writes a unique sibling temporary file, calls `sync_all`, and publishes with one rename;
- failures before rename remove the temporary file and leave the destination unchanged; a post-rename directory-sync error reports uncertain durability after the new destination is visible; Windows use','docs/specs/HBI-v1.md','0b1af040dddf396a1e24e2175840657d9178356a5b71e5d32d15e1bacd808dbd','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/specs/HBP-v1.md','project_doc','doc://simplicio-runtime/docs/specs/HBP-v1.md','doc: HBP v1 — append-only binary receipt ledger','# HBP v1 — append-only binary receipt ledger

Status: implemented by `src/hbp/mod.rs`. HBP v1 is the Runtime-owned format
for ordered receipts, evidence, handoffs, and replay lineage. It is distinct
from HBI v1, which stores read-mostly mmap indexes.

## File and record layout

All integers are unsigned little-endian. The file begins with the eight-byte
header `HBP1`, version `u16 = 1`, flags `u16 = 0`. Each following record is a
`u32` byte length and exactly that many body bytes. A body contains `seq u64`,
`timestamp u64`, then length-prefixed UTF-8 topic, payload, and provenance; a
one-byte optional-token marker and optional length-prefixed token; and
length-prefixed lowercase hexadecimal `prev_hash` and `hash` strings.

Fields are bounded to 4 MiB, records to 16 MiB, and a ledger to 64 MiB before
allocation. Unknown versions or flags, invalid UTF-8, invalid option markers,
trailing bytes, truncation, sequence gaps, broken links, and content-hash
mismatches fail closed. There is no implicit JSON fallback.

## Integrity and compatibility

Sequence zero links to `genesis`. Each row hash is SHA-256 over the following
length-delimited values in order: decimal sequence, previous hash, topic,
payload, provenance, and the token or empty bytes. Version 1 readers accept
only version 1 with flags zero. A new incompatible layout requires a new file
version and magic identity; it must not be interpreted as v1.

`HbpInbox::append_checked` locks the ledger, verifies the complete existing
chain, appends one encoded record, and calls `sync_all`. Reopening constructs
state by verifying the file again, which is the restart/replay contract.
`migrate_legacy_jsonl` is an explicit bounded upgrade adapter: it validates the
legacy chain, retains a backup, publishes binary HBP atomically, and is
idempotent. Legacy input is never selected automatically.

Consumers pin the machine-readable identity returned by
`simplicio contracts binary-formats --json` or the Runtime MCP tool
`simplicio_binary_contracts`. That receipt binds semantic versions to the
specification and HBI golden-vector SHA-256 digests.','docs/specs/HBP-v1.md','b36938b673d27c194045574b3f00db72e33fb404ef87b296bcb0855caef11ef5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SPRINT-2026-07-IMPROVEMENTS.md','project_doc','doc://simplicio-runtime/docs/SPRINT-2026-07-IMPROVEMENTS.md','doc: Sprint 2026-07 — Melhorias do ecossistema (análise validada contra o código)','# Sprint 2026-07 — Melhorias do ecossistema (análise validada contra o código)

> Origem: análise externa de melhorias (2026-07-09) validada repo a repo.
> Resultado: parte do "curto prazo" pedido **já estava implementada**; os gaps
> reais confirmados viraram as issues linkadas abaixo. Este documento é o
> plano de execução com milestones.

## O que a análise pedia e já existe (não virou issue)

| Pedido da análise | Estado real |
|---|---|
| `serve --mcp` persistente como caminho warm | Implementado — loop JSON-RPC persistente (`src/main_parts/chunk_08.rs`), warm-pool, prewarm no boot |
| `simplicio mcp status` / observability MCP | Implementado (#2977, `clientInfo` no handshake) |
| Gate rápido no caminho quente | `simplicio_gate`/`simplicio_run` in-process (#2985, ~160-174×) |
| Runtime como single front door | Implementado (#2951) + `ecosystem doctor` (#2950) |
| Ledger de savings com prova | `savings record/report/dashboard/compare/prove/watch` + `docs/SAVINGS_EVENT_SPEC.md` (#2775) |
| Gate arquitetural no CI | `scripts/check-architecture.py` + baseline (tetos + ciclos), job no `ci.yml` (#2953) |
| Decomposição em crates iniciada | Workspace com 19 crates; `simplicio-security` já extraída |
| Delegation nativa no dev-cli | `gate`, `nest`, `edit`, `file read`, `test run` via `runtime_bridge.py`, com kill-switches |
| Warm MCP no agent | gate classify quente (~160-174×, agent #122) |

## Gaps confirmados → issues

| # | Repo | Issue | Gap |
|---|---|---|---|
| 1 | runtime | [#2986](https://github.com/wesleysimplicio/simplicio-runtime/issues/2986) (sub de #2983) | `map/memory/edit/validate` ainda self-execam por chamada; `checkpoint`/`savings` não são tools MCP; sem tabela de latência per-hop |
| 2 | runtime | [#2982](https://github.com/wesleysimplicio/simplicio-runtime/issues/2982) (já aberta) | Harness A/B de qualidade com/sem o stack — só documentado no ADR, zero implementação |
| 3 | runtime | [#2987](https://github.com/wesleysimplicio/simplicio-runtime/issues/2987) (sub de #2953) | Crates `simplicio-memory` e `simplicio-delivery` não extraídas; `main_parts/` ~88k linhas |
| 4 | runtime | [#2988](https://github.com/wesleysimplicio/simplicio-runtime/issues/2988) | Sem gate de CI de compatibilidade cross-repo; live-probe do loop nunca retestada com `xattr -c` |
| 5 | runtime | [#2989](https://github.com/wesleysimplicio/simplicio-runtime/issues/2989) | Dogfooding do stack sobre o próprio runtime não existe como prática registrada |
| 6 | mapper | [#174](packages/mapper/) (historical issue, pre-monorepo simplicio-mapper repo) | Sem token budget guard; delegação nativa mínima (só precedent); sem savings por verbo. Nota: `contract/impact/tests-for` não existem na CLI |
| 7 | dev-cli | [#111](packages/dev-cli/) (historical issue, pre-monorepo simplicio-dev-cli repo) | Delegação madura mas invisível: sem métrica de % native path por verbo; sem token budget guard |
| 8 | loop | [#127](https://github.com/wesleysimplicio/simplicio-loop/issues/127) | Zero file locking no journal/handoffs/ledger — corrupção possível multi-worker |
| 9 | loop | [#128](https://github.com/wesleysimplicio/simplicio-loop/issues/128) | Journal não consome `simplicio.dev-cli-event/v1`; HBP só appenda em promise-honrada |

## Milestones

### M1 — Fechar o feedback real do usuário (latency + quality) — prioridade máxima
- **#2986** (runtime): MCP 100% in-process + `scripts/bench-mcp-latency.sh` + tabela cold×warm.
- **#2982** (runtime): harness A/B reproduzível, ≥10 tarefas com gabarito, números `measured`.
- Saída: tabela de latência publicada; relatório A/B com zero regressão de qualidade nos tiers do ADR (ou thresholds recalibrados no mesmo PR).

### M2 — Fundação (decomposição, guards, medição)
- **#2987** (runtime): extrair `simplicio-memory` e `simplicio-delivery` (um PR por crate).
- **#174** (mapper) e **#111** (dev-cli): token budget guard cross-repo + savings por verbo de delegação.
- **#127** (loop): locking multi-worker.
- Saída: baseline arquitetural reduzido; % native path visível no doctor do dev-cli; journal à prova de concorrência.

### M3 — Integração e prova (evidência, cross-repo, dogfood)
- **#128** (loop): journal ↔ eventos dev-cli + HBP em stall/gate-blocked/run-blocked.
- **#2988** (runtime): gate de compatibilidade cross-repo no CI + reteste da live-probe.
- **#2989** (runtime): dogfooding do stack sobre o próprio runtime + TUI do agent.
- Saída: evidência auditável ponta a ponta; matriz de versões com fonte única; gaps de dogfood virando issues.

## Regras de execução (valem para todas as issues)

- Implementação via o próprio stack (loop + dev-cli + mapper) com edits mecânicos onde a mudança for pré-decidida; evidência no ledger/HBP.
- Medir antes e depois (tokens, latência, tamanho de `main_parts/`), proof-kind honesto (`measured` vs `estimated` explícito — `docs/SAVINGS_EVENT_SPEC.md`).
- Fail-open + kill-switch em toda delegação nova.
- Antes de cada issue: checar PRs abertos e últimos ~20 commits (regra de coordenação do CLAUDE.md).

## Fora deste sprint (estratégico, sem issue por ora)

- pt-BR/localização de SKILL.md/AGENTS.md/claims; benchmarks padronizados publicados nos READMEs; `simplicio-py` LITE; `skills publish`/registry; benchmarks Asolaria/BEHCS vs abordagem puramente LLM.','docs/SPRINT-2026-07-IMPROVEMENTS.md','e8483c7fdedf0ca44433dc96c92db54a867c612279b87926f48e0fc2d997f3c5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/STAGE_ABI_HOOKWALL_MATRIX.md','project_doc','doc://simplicio-runtime/docs/STAGE_ABI_HOOKWALL_MATRIX.md','doc: Stage ABI mutable-entrypoint matrix (#3629)','# Stage ABI mutable-entrypoint matrix (#3629)

| Runtime entrypoint | Hookwall pre | Effect | Hookwall post | HBP receipt | Bypass behavior |
|---|---:|---:|---:|---:|---|
| Fabric publish | required | gated publish | required | required | block + receipt intent |
| Worker spawn | required | gated spawn | required | required | block + receipt intent |
| Effect execute | required | exactly-once callback | required | required | block + receipt intent |
| Delivery | required | gated delivery | required | required | block + receipt intent |

The executable source of truth is `MUTABLE_ENTRYPOINT_MATRIX` in
`src/asolaria/dispatch_gate.rs`. CI tests require every row to be the complete
`hookwall_pre > effect > hookwall_post > hbp` sequence.

Lifecycle levels are monotonic: address emitted, dispatch accepted, execution
started, effect confirmed, evidence verified. Runtime returns only an HBP evidence
handle at the final level; it never claims `DELIVERED`. Loop remains completion
authority.

## Crash and retry

The durable ledger synchronizes an `EFFECT_INTENT` before invoking an effect. A
retry with a completed `EXECUTION` replays the same evidence handle. A retry that
finds an intent without completion fails closed with `RecoveryRequired`; operators
must reconcile the external effect and append evidence rather than re-run it.

## Cross-language check

Run `python3 scripts/test_stage_abi_golden.py`. The Rust unit test consumes the
same `tests/fixtures/stage_abi_v1.hbp` bytes. Both implementations also verify
that a one-byte semantic tamper invalidates the HBP receipt hash.','docs/STAGE_ABI_HOOKWALL_MATRIX.md','70c3654ec2585afd660feb5788174d97517e5eec2dfb1e801b7b5e67ca42572f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/STATUS-HANDOFF-2026-07-10.md','project_doc','doc://simplicio-runtime/docs/STATUS-HANDOFF-2026-07-10.md','doc: Simplicio Agent + Runtime — handoff audit (2026-07-10)','# Simplicio Agent + Runtime — handoff audit (2026-07-10)

Status: **INCOMPLETO; não promover como release**.

## Feito

- Épica `#2998` e backlog de drenagem organizados no GitHub.
- Issues P0 abertas para identidade, CI, migrations/seeds, LLM local, consciência, Desktop, updater, release e E2E.
- `simplicio version --json` executado com sucesso; o contrato mantém Stripe/Google default-off e descreve update/rollback futuro.
- PRs recentes de MCP, memória, consciência, savings e receipts foram auditados no histórico.

## Incompleto, com evidência

- `doctor --json` reporta ausência de llama-server/GGUF e `offline_ready=false`.
- O auditado possui drift entre fonte, binário, versão e resolução de `SIMPLICIO_BIN`/PATH.
- Migrations/seeds, Desktop layout/kernel, updater/installer, CI gates, matriz MCP/CLI e E2E clean-machine não têm prova completa.
- Há mudanças não commitadas em worktrees de implementação; elas não fazem parte deste commit de handoff.

## Ordem de retomada

1. `#2999` + `#3003` + Agent `#126`.
2. `#3000` + mapper `#176` + dev-cli `#113` + loop `#130`.
3. `#3001` + Agent `#127`/`#132`.
4. `#3002` + Agent `#128`/`#133`.
5. Agent `#129`/`#130`/`#134`/`#135` + `#3004` + `simplicio#5`.
6. `#3005`, install/update/rollback/uninstall e releases.

Nenhuma issue P0 deve fechar sem PR mergeado, checks verdes, logs/exit codes, screenshots quando aplicável, hashes/assets e reconsulta live do GitHub. A épica `#2998` só fecha após todos os gates.

Relatório detalhado e links: Runtime `#3054`, Agent `#144`.','docs/STATUS-HANDOFF-2026-07-10.md','6b52693455702c5d96b022b23a9a8c10dee04576821787ca1fa543218f92cac4','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/STRIPE_SUBSCRIPTION.md','project_doc','doc://simplicio-runtime/docs/STRIPE_SUBSCRIPTION.md','doc: Stripe subscription → Simplicio token','# Stripe subscription → Simplicio token

How a monthly Stripe subscription unlocks the paid features. The binary is
offline-first: it never calls Stripe. Your webhook signs a short-lived token
that the runtime verifies locally against the embedded public key.

## One-time setup (vendor)

1. **Generate the authority keypair** (keep the private key secret — it never
   ships in the binary):
   ```
   python3 - <<''PY''
   from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
   from cryptography.hazmat.primitives import serialization
   import base64
   p = Ed25519PrivateKey.generate()
   priv = p.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
   pub = p.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
   print("PRIVATE (webhook env):", base64.b64encode(priv).decode())
   print("PUBLIC  (embed):", ", ".join(f"0x{b:02x}" for b in pub))
   PY
   ```
2. Replace `PUBLIC_KEY_BYTES` in `src/license.rs` with the printed public bytes,
   rebuild, ship that binary. **The DEMO key currently embedded must be replaced
   before selling** (its private key was exposed during development).
3. Put the private key in your webhook host''s env as
   `SIMPLICIO_LICENSE_SIGNING_KEY`.

## Stripe side

- Create a **monthly recurring Price** and a Checkout link. Point the runtime''s
  upsell at it: customers see `SIMPLICIO_CHECKOUT_URL` (defaults to
  `https://simplicio.dev/subscribe`).
- Subscribe to webhook events: `invoice.paid` (issue/renew),
  `customer.subscription.deleted` (let it lapse).

## Webhook handler (issue + renew)

On `invoice.paid`, mint a token valid until the next billing date and deliver it
to the customer (email / dashboard):

```bash
# env: SIMPLICIO_LICENSE_SIGNING_KEY=<private b64>
EMAIL="$1"          # invoice.customer_email
PERIOD_END="$2"     # invoice.lines.data[0].period.end  (YYYY-MM-DD, UTC)
TOKEN=$(simplicio license issue --email "$EMAIL" --tier pro --expires "$PERIOD_END" --json | jq -r .key)
# deliver $TOKEN to the customer; they run:  simplicio license activate <token>
```

Renewal is automatic: each monthly `invoice.paid` re-issues with a later
`--expires`. On cancellation you simply stop issuing — the last token expires at
period end (plus a 3-day grace), then the runtime falls back to the free tier.

## What the customer does

```
simplicio license activate <token>     # one paste after subscribing
simplicio license status               # tier: pro · status: valid
```

## Tiers

- **free** — deterministic commands always work: `map`, `validate`, `gate`,
  `edit`, `deliver`, `checkpoint`. No subscription needed.
- **economy / pro** — paid: `chat`, `reason`, `run` (coding loop), `vision`,
  local-LLM + managed remote routing.

The paywall is enforced in `license::guard_command`; `SIMPLICIO_LICENSE_DISABLE=1`
bypasses it for local development only.','docs/STRIPE_SUBSCRIPTION.md','ea9664f4b0b518cda2ac576e68b677c62d64a46ac54f5bb70319b769e5a05021','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/SUPER_RUNTIME.md','project_doc','doc://simplicio-runtime/docs/SUPER_RUNTIME.md','doc: Simplicio Super Runtime — North Star','# Simplicio Super Runtime — North Star

> Issue #38 — define the Simplicio Super Runtime north star. This document is
the product boundary: what the runtime *is*, what it explicitly is *not*, and
how it optimizes for speed, low resource usage, and token economy.

## One-line definition

Simplicio is a **local, native, fast, resource-aware super runtime** for
programming work and engineering tasks — the local execution brain that maps,
plans, executes, validates, reviews, collects evidence, and hands off work
with minimal remote-token usage.

It is more than a launcher, plugin, CLI, or MCP server. It is the local
control plane that turns an LLM into a governed, cheap, deterministic engine
instead of an expensive, unbounded one.

## Design pillars

1. **Native + fast.** Single compiled binary, zero runtime dependencies, fast
   startup, cross-platform distribution.
2. **Local-first.** Local LLMs for low-risk work, classification, summaries,
   and communication. Remote/premium LLM only for planning, architecture,
   high-risk review, and escalation.
3. **Resource-aware.** An operating profile (low / normal / full) caps agents,
   KV cache, and CPU so the runtime fits the machine instead of exhausting it.
4. **Token economy.** The frontier LLM orients and reviews; Simplicio supplies
   the cheap, deterministic muscle (map, memory, edit, gate, validate,
   evidence) so each task costs a fraction of the tokens it otherwise would.
5. **Evidence-first delivery.** Every run ships logs, traces, tests, and final
   reports — tamper-evident, not asserted.

## Product boundary (what it is NOT)

- Not a raw file-access helper — it gates every mutation behind an action
  gate and a quality gate.
- Not an unbounded chat — it follows the evidence-gated converge/drain model
  with a durable run journal.
- Not a cloud service — local execution is the default; remote is the
  exception, explicitly gated by policy and evidence.

## Runtime-first rule

Simplicio is the task runner and control plane. Provider LLMs are only
provider sessions: they orient, decompose, review, escalate, and produce
structured plans, but must not bypass Simplicio for task execution, mutation,
validation, evidence, leases, or handoff. This boundary is what keeps the
runtime fast, cheap, and provable.

## Roadmap alignment

Roadmap issues align with the four execution properties above:

- **Local / native / fast:** native binary, in-process llama.cpp engine,
  zero-dependency packaging.
- **Resource-aware:** tiered operating profiles and bounded fan-out.
- **Token economy:** neural memory recall, deterministic editing, MCP + CLI
  tool surface.
- **Evidence-first:** delivery gates, certification, regression checks.

## Example invocations

```bash
simplicio install --global --dry-run --json
simplicio serve --mcp --json
simplicio run "fix the API CORS issue" --repo . --local --agents 20 --evidence
simplicio map --repo . --for-llm markdown
simplicio memory "how does auth work" --repo . --json
simplicio deliver certify --repo . --json
```

## Acceptance criteria for issue #38

- [x] `docs/SUPER_RUNTIME.md` captures the north star.
- [x] README links to the north-star doc.
- [x] Roadmap issues align with local/native/fast/resource-aware execution.
- [x] Runtime can explain this product boundary in install/integration docs.
- [x] The product explicitly optimizes for speed, low resource usage, and
      token economy.','docs/SUPER_RUNTIME.md','a41cec14fec5412889ec174508eeaa7aa25220b93cf88c2570f7fd2bab401b57','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/TROUBLESHOOTING.md','project_doc','doc://simplicio-runtime/docs/TROUBLESHOOTING.md','doc: Troubleshooting','# Troubleshooting

> 🇧🇷 Versão em português: [TROUBLESHOOTING.pt-BR.md](TROUBLESHOOTING.pt-BR.md)

When something does not work, start here:

```bash
simplicio doctor            # full environment self-diagnosis
simplicio doctor --json     # machine-readable, for bug reports
```

`doctor` checks your `PATH`, the binary location, the model cache, the neural
memory database, and the optional toolchain. Most issues below are flagged there.

---

## Common issues

### 1. `simplicio: command not found`

The binary is not on your `PATH`. The canonical location is `~/.local/bin`.

```bash
# Confirm the binary exists
ls -l ~/.local/bin/simplicio

# Add ~/.local/bin to PATH (bash/zsh)
echo ''export PATH="$HOME/.local/bin:$PATH"'' >> ~/.bashrc
exec "$SHELL"
```

On Windows, add `%USERPROFILE%\.local\bin` to your user `PATH` via
*System Properties → Environment Variables*, then open a new terminal.

---

### 2. `simplicio: unknown command: --version`

`--version` is not a flag. Use the subcommand:

```bash
simplicio version
```

---

### 3. macOS refuses to run the binary ("cannot be opened" / "unidentified developer")

Gatekeeper quarantined the downloaded binary. Clear the attribute:

```bash
xattr -d com.apple.quarantine ~/.local/bin/simplicio
```

---

### 4. `agent` / `chat` replies "No relevant memory found"

The neural memory is empty. Initialize and populate it:

```bash
simplicio memory init --repo .
simplicio map --repo .
```

Answer quality depends on the memory being populated. Without it, the agent
correctly reports that it has no context.

---

### 5. Interactive terminal feels stuck / no history

You are running the basic terminal front-end in a limited terminal. Either run
inside a richer terminal (WezTerm, Alacritty, Ghostty, Windows Terminal), or, if
you build from source, enable the rich editor:

```bash
cargo build --release --features rich-repl
```

The rich front-end adds persistent history, `Ctrl-R` search, hints, and
multiline editing. (Release binaries already ship with it.)

---

### 6. Linker error `cc not found` when building from source

You are missing a C/C++ compiler (needed for the in-process LLM engine).

```bash
# Debian / Ubuntu
sudo apt install build-essential

# macOS
xcode-select --install
```

For the in-process LLM build you also need `cmake` and `libclang`. See
[BUILDING.md](../BUILDING.md). To skip the model engine entirely:

```bash
cargo build --release --no-default-features --features tui
```

---

### 7. Stale binary — "I updated but the command did not change"

You have more than one `simplicio` on disk. Find the one your shell resolves:

```bash
which simplicio     # expect ~/.local/bin/simplicio
where.exe simplicio # Windows — lists every match
```

If it resolves to a copy in `~/.cargo/bin`, replace that copy with a symlink to
the canonical binary:

```bash
ln -sf ~/.local/bin/simplicio ~/.cargo/bin/simplicio
```

See [docs/UPGRADE.md](UPGRADE.md#verifying-which-binary-you-are-running).

---

### 8. Remote provider not used / requests stay local

Remote inference needs all three environment variables set, and either the
variables alone or an explicit `--remote`:

```bash
export SIMPLICIO_MODEL="deepseek/deepseek-v4-flash"
export SIMPLICIO_BASE_URL="https://openrouter.ai/api/v1"
export SIMPLICIO_API_KEY="your-key-here"

simplicio chat "hello" --repo . --remote
```

`--local` always overrides these and forces the in-process model. Never commit
your API key — keep it in your shell profile or a secret manager.

---

### 9. Out of memory / machine slows to a crawl

Lower the runtime resource tier:

```bash
simplicio runtime-profile use normal   # balanced default (good for <=16 GB)
simplicio runtime-profile use low       # constrained / background execution
```

`normal` is the right tier for most laptops; `full` is an opt-in for large
machines.

---

## Debug mode

Increase log verbosity to see what Simplicio is doing:

```bash
# Most commands accept a verbose/JSON flag
simplicio doctor --json
RUST_LOG=debug simplicio <command> ...
```

Capture a diagnostics bundle for a bug report:

```bash
simplicio dump      # writes a diagnostics dump under .simplicio-loop/dump/
```

---

## Community & support

- **Issues / bug reports:** <https://github.com/wesleysimplicio/simplicio-runtime/issues>
  (include `simplicio doctor --json` output and your OS/arch)
- **Official site:** <https://simpleti.com.br/simplicio/#start>
- **Build help for developers:** [BUILDING.md](../BUILDING.md)

When filing a bug, attach the output of `simplicio version` and
`simplicio doctor --json` so we can reproduce your environment.','docs/TROUBLESHOOTING.md','ea310054e7918d4f28f6c77d1380c96d56784ea821c6d6335cf9043f0acfe383','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/TROUBLESHOOTING.pt-BR.md','project_doc','doc://simplicio-runtime/docs/TROUBLESHOOTING.pt-BR.md','doc: Solução de Problemas','# Solução de Problemas

> 🇺🇸 English version: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

Quando algo não funciona, comece por aqui:

```bash
simplicio doctor            # autodiagnóstico completo do ambiente
simplicio doctor --json     # legível por máquina, para relatórios de bug
```

O `doctor` checa o seu `PATH`, o local do binário, o cache de modelo, o banco de
memória neural e a toolchain opcional. A maioria dos problemas abaixo é
sinalizada ali.

---

## Problemas comuns

### 1. `simplicio: command not found`

O binário não está no seu `PATH`. O local canônico é `~/.local/bin`.

```bash
# Confirme que o binário existe
ls -l ~/.local/bin/simplicio

# Adicione ~/.local/bin ao PATH (bash/zsh)
echo ''export PATH="$HOME/.local/bin:$PATH"'' >> ~/.bashrc
exec "$SHELL"
```

No Windows, adicione `%USERPROFILE%\.local\bin` ao `PATH` do usuário via
*Propriedades do Sistema → Variáveis de Ambiente* e abra um novo terminal.

---

### 2. `simplicio: unknown command: --version`

`--version` não é uma flag. Use o subcomando:

```bash
simplicio version
```

---

### 3. O macOS recusa rodar o binário ("não pode ser aberto" / "desenvolvedor não identificado")

O Gatekeeper colocou o binário baixado em quarentena. Limpe o atributo:

```bash
xattr -d com.apple.quarantine ~/.local/bin/simplicio
```

---

### 4. `agent` / `chat` responde "No relevant memory found"

A memória neural está vazia. Inicialize e popule:

```bash
simplicio memory init --repo .
simplicio map --repo .
```

A qualidade das respostas depende da memória estar populada. Sem ela, o agente
corretamente informa que não tem contexto.

---

### 5. Terminal interativo parece travado / sem histórico

Você está rodando o front-end básico de terminal num terminal limitado. Rode
dentro de um terminal mais rico (WezTerm, Alacritty, Ghostty, Windows Terminal),
ou, se compilar do código-fonte, habilite o editor rico:

```bash
cargo build --release --features rich-repl
```

O front-end rico adiciona histórico persistente, busca `Ctrl-R`, hints e edição
multiline. (Os binários de release já vêm com ele.)

---

### 6. Erro de linker `cc not found` ao compilar do código-fonte

Está faltando um compilador C/C++ (necessário para a engine LLM in-process).

```bash
# Debian / Ubuntu
sudo apt install build-essential

# macOS
xcode-select --install
```

Para o build com LLM in-process você também precisa de `cmake` e `libclang`. Veja
[BUILDING.md](../BUILDING.md). Para pular a engine de modelo por completo:

```bash
cargo build --release --no-default-features --features tui
```

---

### 7. Binário obsoleto — "atualizei mas o comando não mudou"

Você tem mais de um `simplicio` em disco. Descubra qual o seu shell resolve:

```bash
which simplicio     # espere ~/.local/bin/simplicio
where.exe simplicio # Windows — lista todas as ocorrências
```

Se resolver para uma cópia em `~/.cargo/bin`, substitua essa cópia por um symlink
para o binário canônico:

```bash
ln -sf ~/.local/bin/simplicio ~/.cargo/bin/simplicio
```

Veja [docs/UPGRADE.pt-BR.md](UPGRADE.pt-BR.md#verificando-qual-binário-você-está-rodando).

---

### 8. Provedor remoto não é usado / requisições ficam locais

A inferência remota precisa das três variáveis de ambiente setadas e, ou só as
variáveis, ou um `--remote` explícito:

```bash
export SIMPLICIO_MODEL="deepseek/deepseek-v4-flash"
export SIMPLICIO_BASE_URL="https://openrouter.ai/api/v1"
export SIMPLICIO_API_KEY="sua-chave-aqui"

simplicio chat "olá" --repo . --remote
```

`--local` sempre sobrescreve isso e força o modelo in-process. Nunca commite sua
chave de API — mantenha no perfil do shell ou num gerenciador de segredos.

---

### 9. Sem memória / máquina fica lenta

Reduza o tier de recursos do runtime:

```bash
simplicio runtime-profile use normal   # padrão balanceado (bom para <=16 GB)
simplicio runtime-profile use low       # restrito / execução em background
```

`normal` é o tier certo para a maioria dos laptops; `full` é opt-in para máquinas
grandes.

---

## Modo debug

Aumente a verbosidade dos logs para ver o que o Simplicio está fazendo:

```bash
# A maioria dos comandos aceita uma flag verbose/JSON
simplicio doctor --json
RUST_LOG=debug simplicio <comando> ...
```

Capture um pacote de diagnóstico para um relatório de bug:

```bash
simplicio dump      # escreve um dump de diagnóstico em .simplicio-loop/dump/
```

---

## Comunidade & suporte

- **Issues / relatórios de bug:** <https://github.com/wesleysimplicio/simplicio-runtime/issues>
  (inclua a saída de `simplicio doctor --json` e seu SO/arquitetura)
- **Site oficial:** <https://simpleti.com.br/simplicio/#start>
- **Ajuda de build para devs:** [BUILDING.md](../BUILDING.md)

Ao abrir um bug, anexe a saída de `simplicio version` e `simplicio doctor --json`
para reproduzirmos o seu ambiente.','docs/TROUBLESHOOTING.pt-BR.md','1b42094351d3981c8205eadf53f9f7490c328cb7b6718353570c3c3c939086f4','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/UNIVERSAL_COMMAND_MATRIX.md','project_doc','doc://simplicio-runtime/docs/UNIVERSAL_COMMAND_MATRIX.md','doc: UNIVERSAL COMMAND COVERAGE MATRIX','# UNIVERSAL COMMAND COVERAGE MATRIX

> Mapeamento canônico: todo comando de toda LLM/IDE → simplicio-runtime.
> Versão: 1.0.0 · Runtime: simplicio v1.6.4 · Cobertura: 14 runtimes/ferramentas + git + terminal + bash + PowerShell
> Contrato: simplicio.compatibility-matrix/v1

---

## Sumário

- [1. Claude Code CLI (171+ comandos)](#1-claude-code-cli-171-comandos)
- [2. Codex CLI (50+ comandos)](#2-codex-cli-50-comandos)
- [3. Hermes Agent (40+ comandos)](#3-hermes-agent-40-comandos)
- [4. VSCode / Copilot](#4-vscode--copilot)
- [5. Cursor IDE](#5-cursor-ide)
- [6. OpenCode CLI](#6-opencode-cli)
- [7. Kiro CLI](#7-kiro-cli)
- [8. Antigravity CLI](#8-antigravity-cli)
- [9. Gemini CLI](#9-gemini-cli)
- [10. Aider CLI](#10-aider-cli)
- [11. OpenClaw](#11-openclaw)
- [12. git](#12-git)
- [13. Bash / Terminal](#13-bash--terminal)
- [14. PowerShell](#14-powershell)
- [Anexo A: Simplicio Runtime — 66+ comandos indexados](#anexo-a-simplicio-runtime--66-comandos-indexados)
- [Anexo B: Gaps e prioridades](#anexo-b-gaps-e-prioridades)

---

## Regras da matriz

1. **MCP routes tudo** — `simplicio serve --mcp --stdio` expõe 10+ tools MCP que cobrem 90% dos casos
2. **CLI cobre o restante** — `simplicio <comando>` com 66+ subcomandos (87+ na dispatch real)
3. **simplicio-loop é obrigatório** — toda task DEVE passar pelo loop de convergência
4. **simplicio-dev-cli** — implementação focada com `simplicio dev-cli "<task>" --target <file>`
5. **End-to-end flow** — `simplicio flow verify --pipeline <front|back|db|worker>` verifica a cadeia completa
6. **Evidence obrigatória** — toda execução termina com `simplicio evidence show --run-id <id>`
7. **Cobertura universal é a regra** — qualquer comando de qualquer runtime deve ter um equivalente simplicio

### Legenda de status

| Status | Significado |
|---|---|
| ✅ MCP | Coberto via `simplicio serve --mcp` (tool MCP) |
| ✅ CLI | Coberto via comando CLI direto |
| ✅ loop | Coberto via `simplicio-loop` (convergência) |
| ✅ dev-cli | Coberto via `simplicio dev-cli` |
| ✅ edit | Coberto via `simplicio edit` |
| ✅ shell | Coberto via `simplicio shell` |
| ✅ sprint | Coberto via `simplicio sprint` |
| ✅ chat | Coberto via `simplicio chat` |
| ✅ agent | Coberto via `simplicio agent` |
| ✅ validate | Coberto via `simplicio validate` |
| ✅ memory | Coberto via `simplicio memory` |
| ✅ plan | Coberto via `simplicio plan` |
| ✅ run | Coberto via `simplicio run` |
| ✅ cron | Coberto via `simplicio cron` |
| ✅ invoke | Coberto via `simplicio invoke` |
| ✅ update | Coberto via `simplicio update` |
| ✅ install | Coberto via `simplicio install` |
| ⚠️ parcial | Cobertura parcial (contrato/UX diferente) |
| ❌ gap | Sem cobertura direta |

---

## 1. Claude Code CLI (171+ comandos)

### 1.1 Built-in session commands (slash commands)

| Claude Code (/) | Simplicio Runtime | Status |
|---|---|---|
| `/help` | `simplicio invoke --json` / `simplicio help` | ✅ CLI |
| `/clear` `/new` `/reset` | `simplicio chat --repl` (/clear) | ✅ chat |
| `/compact` | `simplicio compact text <text>` | ✅ CLI |
| `/agents` | `simplicio agent` / `simplicio agents delegate` | ✅ agent |
| `/background` | `simplicio agent claim --background` | ✅ agent |
| `/branch` | `simplicio edit --git branch` / `simplicio shell -- "git branch"` | ✅ shell |
| `/cost` `/usage` | `simplicio savings report --json` | ✅ CLI |
| `/doctor` | `simplicio doctor --json` | ✅ CLI |
| `/goal` | `simplicio plan "<task>" --json` | ✅ plan |
| `/login` `/logout` | `simplicio login google` / `simplicio logout` | ✅ CLI |
| `/mcp` | `simplicio serve --mcp --stdio` | ✅ MCP |
| `/memory` | `simplicio memory query "<query>"` / `simplicio memory-v2 search` | ✅ memory |
| `/model` | `simplicio model status` / `simplicio capabilities list` | ✅ CLI |
| `/plan` | `simplicio plan "<task>" --repo . --json` | ✅ plan |
| `/plugins` | `simplicio capabilities list` / `simplicio app list` | ✅ CLI |
| `/resume` | `simplicio chat --repl --repo .` (session handler) | ✅ chat |
| `/version` | `simplicio version --json` | ✅ CLI |
| `/voice` | `simplicio voice` / `simplicio voice-relay` | ✅ CLI |
| `/copy` | `simplicio chat --repl` (output copy) | ✅ chat |
| `/debug` | `simplicio diagnostics --json` | ✅ CLI |
| `/export` | `simplicio evidence show --run-id <id> --json` | ✅ CLI |
| `/theme` | `simplicio config theme` (parcial) | ⚠️ parcial |
| `/permissions` | `simplicio gate mode` + `simplicio config --permissions` | ⚠️ parcial |
| `/context` | `simplicio runtime map --for-llm` | ✅ MCP |
| `/hooks` | `simplicio hooks list` / `simplicio hooks doctor` | ✅ CLI |
| `/ide` | `simplicio integrations` / `simplicio acp` | ⚠️ parcial |
| `/init` | `simplicio install --global --dry-run --json` | ✅ install |
| `/insights` | `simplicio savings dashboard --json` | ✅ CLI |
| `/run` | `simplicio run "<task>" --repo . --evidence --json` | ✅ run |
| `/verify` | `simplicio validate "<task>" --repo . --json` | ✅ validate |
| `/loop` | `simplicio cron tick` / `simplicio-loop` | ✅ cron |
| `/batch` | `simplicio sprint <sprint> --agents N` | ✅ sprint |
| `/fork` | `simplicio agent fork` / `simplicio issue-worktree prepare` | ✅ agent |
| `/review` | `simplicio validate "review" --repo . --json` | ✅ validate |
| `/security-review` | `simplicio security --json` | ✅ CLI |
| `/code-review` | `simplicio validate "code-review"` | ✅ validate |
| `/ultrareview` | `simplicio diagnostics --toolchain` | ⚠️ parcial |
| `/browser` | `simplicio browser navigate <url>` / `simplicio browser status` | ✅ CLI |
| `/desktop` | `simplicio computer-use status` | ✅ CLI |
| `/computer-use` | `simplicio computer-use click\|type\|scroll` | ✅ CLI |
| `/chrome` | `simplicio browser connect --cdp <url>` | ✅ CLI |
| `/schedule` | `simplicio cron add\|tick\|run` | ✅ cron |
| `/tasks` | `simplicio sprint status` / `simplicio agents status` | ✅ sprint |
| `/config` | `simplicio invoke --json` / `simplicio runtime map` | ✅ invoke |
| `/config apply/set` | `simplicio install --global --dry-run` | ✅ install |
| `/auto','docs/UNIVERSAL_COMMAND_MATRIX.md','eb4fffcc41e08594eb6de0707772ab37760dad542f9d29790c1af61e80f67397','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/UPDATE_CORE_ONLY.md','project_doc','doc://simplicio-runtime/docs/UPDATE_CORE_ONLY.md','doc: Update model — core refreshes, the user''s neural DB is never touched','# Update model — core refreshes, the user''s neural DB is never touched

**Requirement (owner):** when Simplicio ships an update, it must recognize the
**core** changes (new/updated skills, docs, behavior, tools) and apply them, while
**leaving the user''s captured neural memory untouched**.

## How it works

Two disjoint sets of rows live in the same `memory_items` table, distinguished by
`kind` + `stable_id`:

| set | `kind` | `stable_id` shape | owner |
|---|---|---|---|
| **core** (ships with Simplicio) | `project_skill` / `project_doc` / `project_behavior` / `project_tool` | `skill:simplicio-runtime:*`, `doc:*`, `behavior:*`, `tools:*` | the product |
| **user capture** | anything else (`user_capture`, ingested code/git/decisions) | the user''s own ids | the user |

- The committed **core artifact** is `.simplicio-loop/memory/seeds.sql` — regenerated by
  `scripts/build_seed_sql.py` whenever skills/docs change, and it contains **only
  core rows**.
- On `doctor`, first memory access, or after a binary update, `ensure_memory_operational()`
  re-applies `seeds.sql` with **`INSERT OR IGNORE`** (keyed on `stable_id`).
- `INSERT OR IGNORE` is purely additive: a new/changed core row is inserted; an
  existing one is ignored; **nothing the user captured is ever updated or deleted**
  (their `stable_id`s aren''t in `seeds.sql`).

So an update = "merge the latest core into memory." The user''s decisions, code
ingests, and captured context survive every update.

## Proof (run against the release binary, no rebuild)

```
1. fresh init            -> 575 core rows
2. user captures a row   -> kind=user_capture, total 576
3. UPDATE: re-apply seeds.sql, now carrying a NEW core skill
4. result:
   - user row "I decided to use Postgres for orders"  -> STILL PRESENT
   - new core skill "skill: new-core"                 -> ARRIVED
   - user_capture count                                -> still 1
```

The user gets the new core skill; their own row is untouched. Verified 2026-06-27.

## Where it is wired

- `ensure_memory_operational()` (src/main_parts/main_part_01.rs) — the single path.
- Called by `simplicio doctor` and on first memory access (lazy init).
- After a binary auto-update, the next session''s first memory touch refreshes core.

(To make it explicit, `simplicio update` can also call `ensure_memory_operational`
directly — a one-line addition; the behavior above already holds via doctor/init.)','docs/UPDATE_CORE_ONLY.md','844fedaafc7eef87bc93486e5caa4cda21488bdee9b574fc2f218595f7a7887e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/UPGRADE.md','project_doc','doc://simplicio-runtime/docs/UPGRADE.md','doc: Upgrading Simplicio','# Upgrading Simplicio

> 🇧🇷 Versão em português: [UPGRADE.pt-BR.md](UPGRADE.pt-BR.md)

Upgrade with the same method you used to install. After upgrading, always verify:

```bash
simplicio version
simplicio doctor
```

---

## One-liner installer (curl | sh)

Re-running the installer fetches and installs the latest release in place:

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.ps1 | iex"
```

The installer overwrites the binary at the canonical location
(`~/.local/bin/simplicio`) so there is never a stale second copy.

---

## Homebrew

```bash
brew update
brew upgrade simplicio
```

---

## Cargo

```bash
cargo install --git https://github.com/wesleysimplicio/simplicio-runtime --locked --force
```

The `--force` flag replaces the existing installed binary.

---

## Arch Linux (AUR)

```bash
paru -Syu simplicio-bin
# or
yay -Syu simplicio-bin
```

---

## Scoop / Winget (Windows)

```powershell
# Scoop
scoop update simplicio

# Winget
winget upgrade wesleysimplicio.simplicio
```

---

## Docker

Pull the latest image tag:

```bash
docker pull ghcr.io/wesleysimplicio/simplicio:latest
```

Pin a specific version for reproducibility, e.g.
`ghcr.io/wesleysimplicio/simplicio:0.8.0`.

---

## From source

```bash
cd simplicio-runtime
git pull --ff-only
cargo build --release
install -m 0755 target/release/simplicio ~/.local/bin/simplicio
```

If you keep a `~/.cargo/bin/simplicio` entry, make sure it is a symlink to
`~/.local/bin/simplicio` rather than a stale copy:

```bash
ln -sf ~/.local/bin/simplicio ~/.cargo/bin/simplicio
```

---

## After upgrading

- Run `simplicio doctor` to confirm the environment is still healthy.
- Your data under `~/.simplicio-loop` (config, memory, evidence) is preserved across
  upgrades; the binary is the only thing replaced.
- If a command behaves unexpectedly after an upgrade, check
  [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Verifying which binary you are running

```bash
which simplicio        # macOS / Linux — expect ~/.local/bin/simplicio
where.exe simplicio    # Windows
simplicio version
```

If `which` points at an old location (for example `~/.cargo/bin/simplicio` that
is a copy, not a symlink), you upgraded the repo but the command is stale. Fix it
by re-running the installer or recreating the symlink as shown above.

## Local state-preservation gate

Before publishing a release, run the isolated rehearsal:

```bash
simplicio upgrade test --from v1 --to v2 --json
simplicio upgrade test --from v2 --to v1 --json
```

The command creates a temporary fixture and verifies reopening neural-memory
SQLite plus preservation of config, runtime profile, and evidence. `--repo
<path>` only validates the caller directory and does not write to it.

This is a local pre-release gate: tag arguments are direction labels. It does
not check out tags, execute historical binaries, prove migrations between real
releases, or install a CI gate. Those criteria require a release executor and
versioned artifacts.

For the complete local pre-release rehearsal (build plus both state-preservation
directions), run:

```bash
python3 scripts/release/verify_tag_build.py --offline --upgrade-test \
  --report .simplicio-loop/release/tag-build-upgrade-gate.md
```

The Markdown receipt records command status and duration without copying
stdout/stderr. A failed build or failed `v1 -> v2` / `v2 -> v1` report blocks
the gate; no GitHub Actions are required.','docs/UPGRADE.md','4cd34eeac3549a6cfe59f60edfb27209b7fb861dd2851b7bc8fb98498b91c817','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/UPGRADE.pt-BR.md','project_doc','doc://simplicio-runtime/docs/UPGRADE.pt-BR.md','doc: Atualizando o Simplicio','# Atualizando o Simplicio

> 🇺🇸 English version: [UPGRADE.md](UPGRADE.md)

Atualize pelo mesmo método que usou para instalar. Após atualizar, sempre
verifique:

```bash
simplicio version
simplicio doctor
```

---

## Instalador one-liner (curl | sh)

Rodar o instalador de novo busca e instala o último release no lugar:

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.ps1 | iex"
```

O instalador sobrescreve o binário no local canônico (`~/.local/bin/simplicio`),
então nunca há uma segunda cópia obsoleta.

---

## Homebrew

```bash
brew update
brew upgrade simplicio
```

---

## Cargo

```bash
cargo install --git https://github.com/wesleysimplicio/simplicio-runtime --locked --force
```

A flag `--force` substitui o binário instalado existente.

---

## Arch Linux (AUR)

```bash
paru -Syu simplicio-bin
# ou
yay -Syu simplicio-bin
```

---

## Scoop / Winget (Windows)

```powershell
# Scoop
scoop update simplicio

# Winget
winget upgrade wesleysimplicio.simplicio
```

---

## Docker

Puxe a última tag da imagem:

```bash
docker pull ghcr.io/wesleysimplicio/simplicio:latest
```

Fixe uma versão específica para reprodutibilidade, ex.
`ghcr.io/wesleysimplicio/simplicio:0.8.0`.

---

## Do código-fonte

```bash
cd simplicio-runtime
git pull --ff-only
cargo build --release
install -m 0755 target/release/simplicio ~/.local/bin/simplicio
```

Se você mantém uma entrada `~/.cargo/bin/simplicio`, garanta que ela é um symlink
para `~/.local/bin/simplicio` e não uma cópia obsoleta:

```bash
ln -sf ~/.local/bin/simplicio ~/.cargo/bin/simplicio
```

---

## Após atualizar

- Rode `simplicio doctor` para confirmar que o ambiente continua saudável.
- Seus dados em `~/.simplicio-loop` (config, memória, evidência) são preservados entre
  atualizações; apenas o binário é substituído.
- Se um comando se comportar de forma inesperada após atualizar, veja
  [docs/TROUBLESHOOTING.pt-BR.md](TROUBLESHOOTING.pt-BR.md).

---

## Verificando qual binário você está rodando

```bash
which simplicio        # macOS / Linux — espere ~/.local/bin/simplicio
where.exe simplicio    # Windows
simplicio version
```

Se o `which` apontar para um local antigo (por exemplo um `~/.cargo/bin/simplicio`
que é cópia, não symlink), você atualizou o repo mas o comando está obsoleto.
Corrija rodando o instalador de novo ou recriando o symlink como mostrado acima.

## Gate local de preservação de estado

Antes de publicar uma release, execute o ensaio isolado:

```bash
simplicio upgrade test --from v1 --to v2 --json
simplicio upgrade test --from v2 --to v1 --json
```

O comando cria uma fixture temporária e verifica a reabertura do SQLite de
memória neural, além da preservação de config, runtime profile e evidence.
`--repo <path>` apenas valida o diretório informado e não o altera.

Este é um gate local de pré-release: as tags são rótulos de direção. O ensaio
não faz checkout das tags, não executa binários históricos, não prova migração
entre releases reais e não instala um gate de CI. Esses critérios exigem um
executor de release e artefatos versionados reais.

Para o ensaio local completo de pré-release (build e as duas direções de
preservação), execute:

```bash
python3 scripts/release/verify_tag_build.py --offline --upgrade-test \
  --report .simplicio-loop/release/tag-build-upgrade-gate.md
```

O receipt Markdown registra status e duração dos comandos sem copiar
stdout/stderr. Build falho ou relatório falho em `v1 -> v2` / `v2 -> v1`
bloqueia o gate; não são necessários GitHub Actions.','docs/UPGRADE.pt-BR.md','21c94078492379c45ceb625e9329a3b429d73755b50fe3bbb10764ac0f628234','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/ux/ONBOARDING_SPEC.md','project_doc','doc://simplicio-runtime/docs/ux/ONBOARDING_SPEC.md','doc: First-Run Guided Experience — Onboarding Spec','# First-Run Guided Experience — Onboarding Spec

Issue: #2027

## Goal

A new user who installs `simplicio` and types the bare command for the first time
should be guided to a working state in under two minutes without reading any docs.

## Trigger Condition

Show the onboarding wizard when **all** of the following are true on `simplicio`
startup:

- No `.simplicio-loop/` directory exists in `$HOME` or the current repo root.
- `SIMPLICIO_SKIP_ONBOARDING` is not set.
- stdin is a TTY (not piped/CI).

## Flow (6 steps, ~90 s total)

```
Step 1 — Welcome banner (2 s)
  "Welcome to Simplicio v{VERSION}. Let''s get you set up."
  Keypress: [Enter] continue  [s] skip onboarding

Step 2 — Detect environment (auto, 3 s)
  ✓ Rust toolchain: cargo 1.78
  ✓ Git: 2.45
  ✗ Local LLM not found — will use remote provider
  ✓ Neural memory: fresh (will create .simplicio-loop/)

Step 3 — Provider selection (interactive)
  Which LLM backend should Simplicio use?
  [1] Local Runtime (Qwen3.5-4B Q4_K_M, minimum 8 GB RAM)  ← default
  [2] Remote via SIMPLICIO_BASE_URL + SIMPLICIO_API_KEY
  [3] Skip for now (deterministic commands only)

Step 4 — Credentials (only if [2] chosen)
  Base URL: ___________  (default: https://openrouter.ai/api/v1)
  API key:  ___________  (masked, stored in ~/.simplicio-loop/credentials.toml, mode 0600)

Step 5 — Smoke test (auto, 10 s)
  Running: simplicio map --repo . --for-llm markdown
  ✓ Map produced 42 tokens — Simplicio is working.

Step 6 — Summary + next steps
  Setup complete. Try:
    simplicio memory "what is this repo?"
    simplicio status
    simplicio help
  Docs: https://simplicio.dev/docs
```

## Implementation Notes

- Wizard lives in `src/onboarding.rs`; called from `main()` before command
  dispatch when trigger conditions are met.
- Uses `reedline` (already compiled) for masked password input.
- Creates `~/.simplicio-loop/` with `config.toml` and `credentials.toml` (mode 0600).
- `SIMPLICIO_SKIP_ONBOARDING=1` skips silently (CI/scripting).
- Every step is skippable via `s`; partial completion is valid.
- On re-run after partial setup, show "Welcome back. Your config: …" summary
  and offer to re-run individual steps.

## Acceptance Criteria

- [ ] Fresh install → `simplicio` → onboarding wizard appears.
- [ ] Completing step 3 (local) creates a valid `config.toml`; `simplicio status`
      exits 0 immediately after.
- [ ] Completing step 4 writes credentials file with mode 0600; key never echoed
      to terminal or logs.
- [ ] Smoke test (step 5) runs `simplicio map` and reports pass/fail.
- [ ] `SIMPLICIO_SKIP_ONBOARDING=1 simplicio` never shows the wizard.
- [ ] Second run after completed setup never shows the wizard again.','docs/ux/ONBOARDING_SPEC.md','67520049220f42eff99ee09c94e4ce74affd3c4fc0400646cae09da8c8260b8f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/VIDEO_PIPELINE.md','project_doc','doc://simplicio-runtime/docs/VIDEO_PIPELINE.md','doc: Video Pipeline — Simplicio EPIC #240','# Video Pipeline — Simplicio EPIC #240

Deterministic video creation pipeline: topic → script → assets → audio →
timeline → render → captions. Covers issues #241–#249.

## Command reference

### Video Orchestrator (#241)
```
simplicio video pipeline <topic> [--json]
simplicio vid pipeline <topic> [--json]
```
Full pipeline orchestration. Each step is a separate command:
`script` → `assets` → `audio` → `timeline` → `render` → `captions`.

### Script / Storyboard (#242)
```
simplicio video script <topic> [--duration <secs>] [--lang pt-BR] [--json]
```
Generates `simplicio.video-script/v1` JSON with scenes, narration, on-screen text,
b-roll descriptions, and durations.

Saved to `.simplicio-loop/video/script-<topic>.json`.

### Audio / Voiceover (#247)
```
simplicio video audio <script.json> [--voice <name>] [--json]
```
Plans TTS voiceover via `simplicio voice` or external TTS provider.
Schema: `simplicio.video-audio/v1`.

### Timeline / EDL (#246)
```
simplicio video timeline <assets/> [--json]
```
Composes ffmpeg EDL from video + audio segments.
Schema: `simplicio.video-timeline/v1`.

### Render (#243 Remotion, #244 HyperFrames, #245 Higgsfield)
```
simplicio video render <timeline.json> [--backend ffmpeg|remotion|hyperframes|higgsfield] [--json]
```
Supported backends:
- `ffmpeg` — local deterministic render (default)
- `remotion` — React→MP4 via CLI
- `hyperframes` — HTML/CSS/JS→MP4 (headless)
- `higgsfield` — cloud generation (gated, requires `SIMPLICIO_HIGGSFIELD_KEY`)

Schema: `simplicio.video-render/v1`.

### Captions / Subtitles (#248)
```
simplicio video captions <video.mp4> [--format srt|ass] [--json]
```
Generates SRT/ASS from script narration. Word-level timestamps require whisper.
Schema: `simplicio.video-captions/v1`.

### Assets (#249)
```
simplicio video assets <script.json> [--json]
```
Downloads and caches b-roll assets with content-addressed provenance.
Schema: `simplicio.video-assets/v1`.

## Schemas

| Schema | Description |
|--------|-------------|
| `simplicio.video-script/v1` | scenes, narration, on-screen text, durations |
| `simplicio.video-audio/v1` | voiceover plan |
| `simplicio.video-timeline/v1` | EDL / cut list |
| `simplicio.video-render/v1` | render config + backend |
| `simplicio.video-captions/v1` | SRT/ASS generation plan |
| `simplicio.video-assets/v1` | asset inventory with provenance |
| `simplicio.video-pipeline/v1` | full pipeline orchestration status |

## End-to-end example

```bash
# 1. Generate script
simplicio video script "inteligência artificial em 2026" --duration 90 --json

# 2. Plan assets
simplicio video assets .simplicio-loop/video/script-intelig.json --json

# 3. Plan audio
simplicio video audio .simplicio-loop/video/script-intelig.json --json

# 4. Plan timeline
simplicio video timeline .simplicio-loop/video/assets/ --json

# 5. Render
simplicio video render .simplicio-loop/video/timeline.json --backend ffmpeg --json

# 6. Captions
simplicio video captions output.mp4 --format srt --json
```

## Cloud backends (gated)

**Higgsfield (#245)**: `SIMPLICIO_HIGGSFIELD_KEY` required. Supports:
- `generate_video` — scene-by-scene generation
- `upscale_video` — resolution upscaling
- `reframe` — aspect ratio change

**Remotion (#243)**: React component pipeline. Requires Node.js + Remotion CLI.

**HyperFrames (#244)**: HTML/CSS/JS rendering. Requires headless browser.','docs/VIDEO_PIPELINE.md','d75f5cc5473dd0ae493c837015a8bc17b359eb111813edd67b79a6a3981dc98a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/VOICE_LOCAL_RESEARCH_2026-06.md','project_doc','doc://simplicio-runtime/docs/VOICE_LOCAL_RESEARCH_2026-06.md','doc: Local Real-Time Voice Stack — Deep Research (2026-06-11)','# Local Real-Time Voice Stack — Deep Research (2026-06-11)

Verified survey for the real-time voice agent (Product 2): fully local, Rust-integrable
(llama.cpp/ort in the single binary), Brazilian Portuguese + English, <1 s
voice-to-voice, consumer hardware tiers 8/16/24/32+ GB. Five parallel research
passes (STT, TTS, VAD/orchestration, end-to-end S2S models, real-world stacks)
plus adversarial verification of the load-bearing claims. Feeds
`docs/design/voice-first.md` (#701).

**Standing decision: PT-BR quality is the #1 tie-breaker on every layer.**

## Verdict: cascaded pipeline, not end-to-end

No end-to-end speech-to-speech model satisfies pt-BR + ≤16 GB + Rust today:

- The only open model with Portuguese **speech output** is Qwen3-Omni-30B-A3B
  (Apache-2.0), but Q4_K_M GGUF is 18.6 GB and llama.cpp does not implement its
  Talker — audio understanding only, text out
  ([ggml-org GGUF](https://huggingface.co/ggml-org/Qwen3-Omni-30B-A3B-Instruct-GGUF),
  [llama.cpp #17634](https://github.com/ggml-org/llama.cpp/issues/17634)).
- Moshi (Kyutai) fits quantized and has a first-party Rust/Candle server, but is
  English-only and community-documented as conversationally weak.
- LFM2.5-Audio-1.5B would fit 8 GB but is English-only; llama.cpp S2S support is
  an unmerged draft ([PR #18641](https://github.com/ggml-org/llama.cpp/pull/18641)).
- Decisive precedent: Kyutai itself shipped **Unmute** as a *cascaded* system
  because function calling/factuality suffer in native full-duplex — exactly the
  properties Simplicio needs (gating, tool use, determinism).

Practitioner consensus 2025-2026: cascaded dominates production (<15% S2S
adoption) for debuggability and tool calling; well-engineered streaming cascades
reach 400-800 ms. Proof points: RealtimeVoiceChat ~500 ms voice-to-voice on a
4090 with per-stage breakdown ([HN](https://news.ycombinator.com/item?id=43899028),
author-confirmed: LLM TTFT ~220 ms, TTS first audio ~80 ms); LocalCat ~400-600 ms
fully local on Apple Silicon M2.

## Verified component picks (PT-first)

| Layer | Pick | Size | Why (verified) |
|---|---|---|---|
| VAD | **Silero VAD** via `ort` (crate `voice_activity_detector`) | ~2 MB | <1 ms/chunk single CPU thread, MIT, mature crate (73k downloads) |
| Endpointing | **Smart Turn v3** ONNX int8 (pipecat-ai) | ~8 MB | 12-60 ms CPU, **Portuguese confirmed** in the 23-language list, audio-native (no STT partials needed), BSD-2 ([repo](https://github.com/pipecat-ai/smart-turn)) |
| STT (PT-first) | **Parakeet-TDT-0.6B-v3** int8 via sherpa-onnx (official Rust crate) | ~2 GB RAM | Best PT WER per compute: 4.76% FLEURS vs ~6% Whisper large-v3; CC-BY-4.0; word/char timestamps. Caveat: trained on **European** pt — pt-BR A/B required (below) |
| STT (robustness/partials) | **whisper.cpp** via whisper-rs | 0.4-2.5 GB by size | pt-BR+EN one model, MIT, same ggml backend as our llama.cpp; Metal ~10x realtime on M-series |
| LLM | Existing local Qwen ladder | tiered | TTFT 100-300 ms warm-KV at 2-4B; voice needs short TTFT, not a big model |
| TTS | **Kokoro-82M** ONNX, voices `pf_dora`/`pm_alex`/`pm_santa` | ~300 MB | Only real-time-class TTS with **dedicated pt-BR voices** (confirmed in VOICES.md), Apache-2.0, RTF ~0.5 on a 4-core CPU = 2x faster than realtime; Rust paths: Kokoros crate, sherpa-onnx Kokoro family |
| TTS (ultra-light) | Piper `pt_BR` voices via **piper-rs** (MIT) | ~63 MB | 4 pt-BR voices exist (cadu/edresson/faber/jeff — all male). Use piper-rs, NOT new upstream piper1-gpl (**GPL**) — closed-source distribution rule |
| AEC (barge-in) | `webrtc-audio-processing` (tonari) | small | AEC3, production-tested; skip when headphones |

Eliminated (verified): XTTS-v2 (CPML non-commercial, Coqui defunct — no license
path), F5-TTS for real-time (CPU RTF off by 2-3 orders of magnitude; keep
[firstpixel/F5-TTS-pt-br](https://huggingface.co/firstpixel/F5-TTS-pt-br) as an
*offline* pt-BR cloning asset), Fish/OpenAudio (non-commercial), Orpheus (no pt,
3B), MeloTTS/Dia/CSM/StyleTTS2 (no pt), Vosk pt (WER 27-68%), Kyutai STT/TTS
(en/fr only, but watch: best streaming architecture + Rust server), Moonshine
(en-only, watch for multilingual), sherpa-onnx streaming zipformer (no pt model;
would require training one with icefall).

## Resource tiers (mirrors `runtime-profile`)

Fixed on all tiers (~320 MB): Silero + Smart Turn v3 + Kokoro pt-BR + AEC.
Scaling axes: STT and the voice LLM. Everything stays resident (no per-turn
load/unload — swap kills latency).

| Tier | STT | Voice LLM | Stack RAM |
|---|---|---|---|
| `voice-low` (8 GB) | Parakeet-TDT-0.6B int8 (sole STT, VAD-cut) | Qwen 2B Q6_K | ~4.6 GB |
| `voice-normal` (16 GB) | whisper large-v3-turbo Q5 (partials) + Parakeet (final pass) | Qwen 4B Q6 | ~7.3 GB |
| `voice-high` (24 GB) | dual STT idem | Qwen 7/8B Q4 | ~10 GB |
| `voice-full` (32 GB+) | whisper large-v3 Q5 + Parakeet final | Qwen 14B Q4 | ~15 GB |

Design rules:
1. **Latency caps the LLM before RAM does** — voice brain tops out ~14B; deep
   reasoning escalates through the existing 5x ladder in the background.
2. Tier = detected ceiling (`voice-profile use low|normal|high|full`), same
   philosophy as `force_all_resources`.
3. Watchlist for `voice-full`: Qwen3-Omni Talker in llama.cpp (native pt speech),
   LFM2.5-Audio multilingual, Gemma 3n audio-in (140+ spoken languages, already
   in llama.cpp) as unified STT+understanding.

## Latency budget (local, p50 target ~720 ms)

endpoint decision ~220 ms (Silero silence ~200 ms + Smart Turn ~12-60 ms)
→ STT final 150-300 ms → LLM TTFT 150-300 ms (sentence-split, dispatch first
sentence) → Kokoro TTFA 150-400 ms, chunked playback. Non-negotiable tricks:
transcribe *while* the user speaks where partials exist; synthesize
sentence-by-sentence *while* the LLM streams; prewarmed KV cache.

## Mandatory empirical gates before locking defaults

1. **Parakeet (pt-EU-trained) vs Whisper on real pt-BR audio** — CORAA corpus +
   real WhatsApp voice notes, WER via `benchmark_s','docs/VOICE_LOCAL_RESEARCH_2026-06.md','689aa01d66d4ce90ca919efca6a3df950d31de60d1e59eba5cc7a98fa6f6c41c','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/workspace-architecture.md','project_doc','doc://simplicio-runtime/docs/workspace-architecture.md','doc: Workspace Architecture Guide — Issue #1872 (tracker continued at #2953)','# Workspace Architecture Guide — Issue #1872 (tracker continued at #2953)

Monolith decomposition plan for the `simplicio` binary crate into a Cargo
workspace with focused library crates.

**Status as of 2026-07-07 (#2953 — this section is the accurate, current one;
"Crate Inventory" below is the original 2026-06-17 plan and is kept for
extraction-order guidance, but its own "Already Extracted"/"Planned" split had
drifted out of date — see the corrected checklist immediately below.**

Real measurements (see `scripts/check-architecture.py`, which also gates
these numbers going forward):

| Metric | Value |
|---|---|
| `src/main.rs` (thin orchestrator: `mod`/`include!` declarations + `fn main()`) | 1,028 lines |
| `src/main_parts/*.rs` (20 `chunk_NN.rs` files `include!()`d into the crate-root module — this is the actual remaining monolith body, not `main.rs` itself) | 87,595 lines |
| `src/*.rs` + subdirectories (891 files declared via `mod`, e.g. `src/commands/`, `src/autopilot_*`) | 959,205 lines |
| `crates/*` (already-extracted Cargo workspace members) | 54,762 lines across 20 crates (was 47,761 / 19 before `simplicio-memory`, #2987) |

The historical "107,701 lines, 709 source files" figure quoted by the original
2026-06-17 plan below is stale; the monolith has both grown (new features) and
shrunk in places (organic extraction) since. Treat the table above as current.
The `src/main.rs` / `src/main_parts/*.rs` rows above were not re-measured for
#2987 — that extraction moved 11 `src/*.rs` files (not `src/main_parts/*.rs`)
into `crates/simplicio-memory`, so it grows `crates/*` and shrinks the
broader `src/*.rs` tree without moving the `main_parts_total_lines` needle
tracked by `scripts/architecture-baseline.json` (see the `simplicio-memory`
row in the checklist below for what did and did not move).

### Extraction checklist — real status per target crate

The original plan (below) named 9 target crates. Reality has diverged: two
were completed out of order, and 16 *additional* crates were extracted for
unrelated initiatives (mostly the Asolaria absorption) that the original plan
never anticipated. This table is the one to trust; update it whenever a
crate''s status changes.

| Crate | Status | Notes |
|---|---|---|
| `simplicio-core` | ✅ Done | Original plan''s crate 0. Foundational pure utilities. |
| `simplicio-agents` | ✅ Mostly done (cleanup gap) | 15,149 lines extracted — substantially larger than the original plan''s 21-file estimate. **Gap:** the original `src/agent_bootstrap.rs`, `agent_broadcast.rs`, `agent_collaboration.rs`, `agent_init.rs`, `agent_ipc.rs`, `agent_ops_bounded_1536.rs` source files are still present in `src/` post-extraction and are **no longer referenced by any `mod` declaration** (verified: no `mod agent_bootstrap` etc., no `agent_bootstrap::` call sites outside the crate) — i.e. Extraction Rule 4 ("delete originals after merge") was never completed for this crate. They are dead weight, not live duplicates (cargo does not compile them), but they should be deleted in a follow-up PR to avoid confusing future readers about which copy is authoritative. |
| `simplicio-security` | ⚠️ Partial — stub only | `crates/simplicio-security` exists (180 lines) but is an **honest-stub router** ("all sub-commands are honest stubs... pointing the caller to the real action-gate subcommands rather than silently succeeding" — see its own doc comment). The actual security logic the original plan targeted (`src/action_gate.rs`, `src/action_bridge.rs`, `src/seguranca_audit.rs`, `src/novelty_gate.rs`, `src/issue_gate.rs`, etc.) is **still in the un-extracted `src/` tree**. Do not count this crate as satisfying the original plan''s Crate 5. |
| `simplicio-memory` | ✅ Done (partial, #2987) | ~5,900 lines extracted: `memory_command.rs`, `memory_v2.rs`, `memoria_v2.rs`, `vector_memory.rs`, `memory_rerank.rs`, `htool_memory_tool.rs`, `lmdb_store.rs`, `prompt_caching.rs`, `result_cache.rs`, `l0_memo.rs`, `memory_manager.rs`. **Gap (deliberate, not a leftover):** `src/mapper_memory.rs` and `src/tools_memory_providers.rs` stay un-extracted — both reach back into binary-only shared state (`RuntimeConfig`, the hand-rolled `Json` enum, `parse_json`, `find_on_path`, `run_command_timeout`, …) that would itself need extracting first to avoid a circular dependency on the binary. `src/memory_manager_parity.rs`, `src/memory_provider_parity.rs`, `src/memmap_index.rs`, `src/memory_consolidate.rs` were also left in place: none of them are reachable from any `mod`/`include!` in `src/main.rs` (dead code, pre-dating this extraction) and moving dead code adds no value. `src/main.rs` and `src/lib.rs` re-export the moved module names at the crate root (`pub(crate) use simplicio_memory::memory_v2;` etc.) rather than rewriting every call site, since most call sites already reach in at the item level (`crate::memory_v2::MemoryV2Manager`, `vector_memory::SkillIndex`, …), not through a single dispatch function. |
| `simplicio-providers` | ❌ Not started | Still fully in `src/` (`src/integration_*.rs`, `src/provider_command.rs`, `src/transport_*.rs`, …). |
| `simplicio-delivery` | ❌ Not started | Still fully in `src/` (`src/delivery/` module tree, `src/benchmark_*.rs`, `src/cost_ledger.rs`, …). Not attempted in #2987 — the memory-domain extraction alone used the change budget for that sub-issue; delivery gates extraction is a separate follow-up. |
| `simplicio-skills`/catalog | ❌ Not started | Still fully in `src/` (~201 `src/skill_*.rs` files) — the single largest remaining extraction target by file count. |
| `simplicio-gateway` | ✅ Done (organic) | 207 lines. Not part of the original 9-crate plan''s ordering but matches its Crate 2 domain description. |
| `simplicio-voice` | ❌ Not started | Original plan''s Crate 3; still fully in `src/` (`src/voice_*.rs`, `src/tts_provider.rs`, …). |
| `simplicio-video` | ❌ Not started | Original plan''s Crate 4; still fully in `src/` (`src/video_pipeline.rs`, `src/video_provider.rs`,','docs/workspace-architecture.md','4497d12ee0cd3ba659e8a377446aa6d7808dbc071f074863e64768af6775b9d4','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/workspace-dispatch-guide.md','project_doc','doc://simplicio-runtime/docs/workspace-dispatch-guide.md','doc: Workspace Dispatch Guide (issue #1872)','# Workspace Dispatch Guide (issue #1872)

`src/main.rs` is being decomposed from a ~107 k-line monolith into focused
workspace crates under `crates/`. This document is the step-by-step recipe for
adding a new command via that pattern, the naming contract every crate must
follow, and a few rules that keep the `main.rs` match block free of merge
conflicts.

---

## Flow diagram

```
user invokes: simplicio <command> [sub] [args...]
                         |
              src/main.rs  match command { ... }
                         |
              one match arm per domain (thin)
                         |
              crates/simplicio-<name>/src/lib.rs
                         |
              pub fn <domain>_dispatch(cmd, args) -> Result<(), String>
                         |
              module / helper inside the crate
```

The binary owns routing. The crate owns logic. No logic lives in the match arm
itself — only the three-line delegation:

```rust
"my-command" => {
    let sub = args.first().cloned().unwrap_or_default();
    let rest = args.into_iter().skip(1).collect();
    simplicio_myname::myname_dispatch(&sub, rest)
}
```

---

## Step 1 — create the crate

```
crates/
  simplicio-<name>/
    Cargo.toml
    src/
      lib.rs
```

Minimal `Cargo.toml`:

```toml
[package]
name = "simplicio-<name>"
version = "1.0.1"          # keep in sync with root via scripts/bump-version.sh
edition = "2021"
description = "One line description."
license-file = "../../LICENSE"
publish = false

[lib]
name = "simplicio_<name>"   # underscore form of the crate name
path = "src/lib.rs"
```

Do not add runtime crate types (`serde_json`, `rusqlite`, `tokio`, …) unless
the domain genuinely needs them. The whole point of extracting a crate is to
keep it dependency-free so it compiles instantly and is easy to test in
isolation.

---

## Step 2 — implement the dispatch function

Every crate that participates in workspace dispatch **must** export exactly one
public function with this signature:

```rust
pub fn <domain>_dispatch(cmd: &str, args: Vec<String>) -> Result<(), String>
```

Where `<domain>` is the lower-snake-case form of the crate name without the
`simplicio-` prefix. Examples:

| crate name         | function name          |
|--------------------|------------------------|
| `simplicio-core`   | `core_dispatch`        |
| `simplicio-video`  | `video_dispatch`       |
| `simplicio-delivery` | `delivery_dispatch`  |

The function must never panic. Unknown subcommands return `Err(format!("unknown
<domain> subcommand: {cmd}"))`.

---

## Step 3 — register in root Cargo.toml

Open `Cargo.toml` at the repo root. Find the `[dependencies]` block and add:

```toml
simplicio-<name> = { path = "crates/simplicio-<name>" }
```

Also add `"crates/simplicio-<name>"` to the `[workspace] members` list at the
top of the same file.

---

## Step 4 — add exactly one arm in main.rs

Open `src/main.rs`. Find the block labelled:

```
// #1872: workspace dispatch pilot — add new workspace crate arms here
```

Insert a new arm **immediately above** that comment (never below the `_ =>`
wildcard). The arm must be exactly three lines of delegation:

```rust
"<command-name>" => {
    let sub = args.first().cloned().unwrap_or_default();
    let rest = args.into_iter().skip(1).collect();
    simplicio_<name>::<domain>_dispatch(&sub, rest)
}
```

Rules:
- Do **not** touch any existing arm above this block.
- Do **not** put business logic in the arm — only the three delegation lines.
- One arm per domain. Multiple subcommands are handled inside the crate''s
  dispatch function.

---

## Step 5 — run tests per crate

```
cargo test -p simplicio-<name>
```

This runs only the unit tests in that crate without rebuilding or linking the
full binary. Use it during development to stay fast.

Full workspace check (no heavy optional features):

```
cargo check --no-default-features --features tui
```

Full workspace tests:

```
cargo test --workspace
```

---

## Merge-conflict avoidance

The `main.rs` match block has hundreds of arms. Parallel branches that each
touch random arms produce conflicts on every merge.

Rules that prevent this:
1. **Never modify an existing arm** in the context of adding a new domain.
2. **Always add new arms at the designated block** (the `#1872` comment).
3. The block is at the very end of the match, just before `_ =>`. Inserting
   there means two parallel branches both insert at the same location; Git
   will still conflict, but only at that one spot — not throughout the file.
4. If two branches add different domains at the same spot, resolve by
   concatenating both new arms in either order. The `_ =>` wildcard stays last.

---

## Pilot example — `simplicio-core`

`crates/simplicio-core` is the first concrete slice of this decomposition.
It exposes:

```rust
pub fn core_dispatch(cmd: &str, args: Vec<String>) -> Result<(), String>
```

Registered in `Cargo.toml`:

```toml
simplicio-core = { path = "crates/simplicio-core" }
```

Arm in `main.rs`:

```rust
"core-dispatch-demo" => {
    let sub = args.first().cloned().unwrap_or_default();
    let rest = args.into_iter().skip(1).collect();
    simplicio_core::core_dispatch(&sub, rest)
}
```

Usage:

```
simplicio core-dispatch-demo truncate "hello world" 5
# => he...

simplicio core-dispatch-demo slugify "Fix the Bug!"
# => fix-the-bug
```

Run tests for the crate only:

```
cargo test -p simplicio-core
```','docs/workspace-dispatch-guide.md','faae6414ab1d499371033d78c94a46fa6338061a17ed5e099c4174a260835c37','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/YOOL_INTEGRATION.md','project_doc','doc://simplicio-runtime/docs/YOOL_INTEGRATION.md','doc: Yool tuple-space integration — design & contract (issue #345)','# Yool tuple-space integration — design & contract (issue #345)

Yool (tuple-space + HAMT) is the planned coordination/memory layer for
multi-agent work. The kernel lives in a separate project; this document defines
the **integration contract** the runtime exposes/consumes so the binding can land
cleanly once the kernel is wired in, without faking primitives that don''t exist
yet.

## Model

- **Tuple** (`simplicio.yool-tuple/v1`, `schemas/yool-tuple.schema.json`) is the
  addressable unit of shared state: `namespace` (scope) + `key`
  (HAMT-addressable) + `kind` + `payload` + `provenance`.
- **Blackboard**: agents `put` observations/plans/partial results; others
  `get`/`query`/`subscribe` and react — no prompt-bloat broadcast.
- **Namespacing** isolates concurrent sprints/agents so they don''t collide.

## Runtime API surface (to implement, slice 1)

```text
yool_put(namespace, key, tuple) -> ()
yool_get(namespace, key)        -> Option<tuple>
yool_query(namespace, pattern)  -> [tuple]
yool_subscribe(namespace, pattern) -> stream<tuple>
```

CLI/observability (slice 5):

```bash
simplicio yool inspect --namespace <ns> --json
simplicio yool query   --namespace <ns> --pattern <glob> --json
simplicio agents list  --yool --json
```

## How it maps to what already exists

| existing surface | Yool-backed evolution |
|---|---|
| `simplicio.decision-route/v1` (decision router) | routing reads/writes shared task + agent registry tuples |
| `simplicio.agent-capacity/v1` / governor | global agent-state view via registry tuples (#346) |
| evidence ledger | evidence tuples → queryable/auditable by key |
| mapper artifacts / prompt contracts / sprint state | addressable via `namespace/key` instead of re-derived per agent |
| `simplicio memory` / `skill-memory` | Yool-powered persistent tuple spaces |

## Implementation slices (kernel-dependent)

1. Minimal Yool binding (Rust FFI or native port) + `put`/`get` behind the API above.
2. Agent registry + task blackboard on Yool.
3. Decision engine routes via shared state (ties into #346).
4. Evidence ledger migrated to Yool addressing.
5. TUI + CLI observability (`yool inspect/query`).
6. Performance benchmark vs in-memory (ties into #348 harness).
7. Docs + example multi-agent sprint.

## Non-goals (initial)
- Distributed Yool across machines (single-node high-performance first).
- Replacing all in-memory structures at once (incremental adoption).

## Status
- ✅ Integration contract + tuple schema (this slice).
- ⏳ Slices 1–7 require the Yool kernel to be available in the build; tracked here
  and under epic #344.','docs/YOOL_INTEGRATION.md','033f83b08360d950cd44b10748f5b55b040443196794d35efe3de6ac88a18c75','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('tools:simplicio-runtime:cli-surface','project_tool','tool://simplicio-runtime/cli','tools: simplicio CLI command surface','simplicio commands: map memory edit gate validate run sprint workflow agents savings license serve doctor plan precedent skills learn checkpoint deliver index social hyperframes voice — deterministic control plane.','src/main.rs','03cc2fa55727f0060b1701c1ce6a5875705f4a8e1c742206b2dc7b706e0174a8','tool,cli,command,simplicio',1.2);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('tools:simplicio-runtime:mcp-surface','project_tool','tool://simplicio-runtime/mcp','tools: simplicio MCP server tools','simplicio serve --mcp --stdio exposes 8 tools: simplicio_map (orient), simplicio_memory (FTS+vector recall), simplicio_edit (deterministic sandboxed edit), simplicio_gate (risk classify), simplicio_validate (pipeline), simplicio_run (gate->bridge->evidence), simplicio_symbol (def+callers via CodeGraph), simplicio_search (symbol search). One harness; install via `simplicio mcp register`.','src/main_parts/main_part_01.rs','1429df7302a113474201f622f9328bb488e5023be03dbc71903ba03e91cb5e76','tool,mcp,server,simplicio',1.4);
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('a11y-audit','skill:simplicio-runtime:a11y-audit','coding','.claude\skills\a11y-audit\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ab-testing','skill:simplicio-runtime:ab-testing','coding','.claude\skills\ab-testing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ad-creative','skill:simplicio-runtime:ad-creative','coding','.claude\skills\ad-creative\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('address-sanitizer','skill:simplicio-runtime:address-sanitizer','coding','.claude\skills\address-sanitizer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ads','skill:simplicio-runtime:ads','content','.claude\skills\ads\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('adversarial-reviewer','skill:simplicio-runtime:adversarial-reviewer','coding','.claude\skills\adversarial-reviewer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('aflpp','skill:simplicio-runtime:aflpp','coding','.claude\skills\aflpp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('agent-designer','skill:simplicio-runtime:agent-designer','orchestration','.claude\skills\agent-designer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('agent-workflow-designer','skill:simplicio-runtime:agent-workflow-designer','coding','.claude\skills\agent-workflow-designer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('agenthub','skill:simplicio-runtime:agenthub','content','.claude\skills\agenthub\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('agentic-actions-auditor','skill:simplicio-runtime:agentic-actions-auditor','coding','.claude\skills\agentic-actions-auditor\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('agile-product-owner','skill:simplicio-runtime:agile-product-owner','coding','.claude\skills\agile-product-owner\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ai-act-readiness','skill:simplicio-runtime:ai-act-readiness','coding','.claude\skills\ai-act-readiness\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ai-security','skill:simplicio-runtime:ai-security','coding','.claude\skills\ai-security\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ai-seo','skill:simplicio-runtime:ai-seo','content','.claude\skills\ai-seo\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ai-tool-handoff','skill:simplicio-runtime:ai-tool-handoff','coding','.claude\skills\ai-tool-handoff\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('aims-audit','skill:simplicio-runtime:aims-audit','coding','.claude\skills\aims-audit\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('algorand-vulnerability-scanner','skill:simplicio-runtime:algorand-vulnerability-scanner','coding','.claude\skills\algorand-vulnerability-scanner\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('amendment-history','skill:simplicio-runtime:amendment-history','coding','.claude\skills\amendment-history\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('analytics','skill:simplicio-runtime:analytics','coding','.claude\skills\analytics\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('api-design-reviewer','skill:simplicio-runtime:api-design-reviewer','coding','.claude\skills\api-design-reviewer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('api-test-suite-builder','skill:simplicio-runtime:api-test-suite-builder','coding','.claude\skills\api-test-suite-builder\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('apple-hig-expert','skill:simplicio-runtime:apple-hig-expert','coding','.claude\skills\apple-hig-expert\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ask-questions-if-underspecified','skill:simplicio-runtime:ask-questions-if-underspecified','coding','.claude\skills\ask-questions-if-underspecified\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('aso','skill:simplicio-runtime:aso','coding','.claude\skills\aso\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('atheris','skill:simplicio-runtime:atheris','coding','.claude\skills\atheris\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('atlassian-admin','skill:simplicio-runtime:atlassian-admin','coding','.claude\skills\atlassian-admin\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('atlassian-templates','skill:simplicio-runtime:atlassian-templates','content','.claude\skills\atlassian-templates\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('audit-augmentation','skill:simplicio-runtime:audit-augmentation','coding','.claude\skills\audit-augmentation\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('audit-context-building','skill:simplicio-runtime:audit-context-building','coding','.claude\skills\audit-context-building\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('audit-prep-assistant','skill:simplicio-runtime:audit-prep-assistant','coding','.claude\skills\audit-prep-assistant\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('autoresearch-agent','skill:simplicio-runtime:autoresearch-agent','coding','.claude\skills\autoresearch-agent\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('aws-solution-architect','skill:simplicio-runtime:aws-solution-architect','coding','.claude\skills\aws-solution-architect\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('azure-cloud-architect','skill:simplicio-runtime:azure-cloud-architect','coding','.claude\skills\azure-cloud-architect\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('behuman','skill:simplicio-runtime:behuman','video','.claude\skills\behuman\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('board','skill:simplicio-runtime:board','coding','.claude\skills\board\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('board-minutes','skill:simplicio-runtime:board-minutes','coding','.claude\skills\board-minutes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('brief-section-drafter','skill:simplicio-runtime:brief-section-drafter','coding','.claude\skills\brief-section-drafter\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('browser-automation','skill:simplicio-runtime:browser-automation','coding','.claude\skills\browser-automation\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('browserstack','skill:simplicio-runtime:browserstack','coding','.claude\skills\browserstack\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('burpsuite-project-parser','skill:simplicio-runtime:burpsuite-project-parser','coding','.claude\skills\burpsuite-project-parser\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('business-investment-advisor','skill:simplicio-runtime:business-investment-advisor','coding','.claude\skills\business-investment-advisor\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('c-review','skill:simplicio-runtime:c-review','coding','.claude\skills\c-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('cairo-vulnerability-scanner','skill:simplicio-runtime:cairo-vulnerability-scanner','coding','.claude\skills\cairo-vulnerability-scanner\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('capa-officer','skill:simplicio-runtime:capa-officer','coding','.claude\skills\capa-officer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('cargo-fuzz','skill:simplicio-runtime:cargo-fuzz','coding','.claude\skills\cargo-fuzz\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('caveman','skill:simplicio-runtime:caveman','coding','.claude\skills\caveman\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('changelog-generator','skill:simplicio-runtime:changelog-generator','coding','.claude\skills\changelog-generator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('chaos-engineering','skill:simplicio-runtime:chaos-engineering','coding','.claude\skills\chaos-engineering\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('chrome-mcp-troubleshooting','skill:simplicio-runtime:chrome-mcp-troubleshooting','coding','.claude\skills\chrome-mcp-troubleshooting\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('chronology','skill:simplicio-runtime:chronology','coding','.claude\skills\chronology\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('churn-prevention','skill:simplicio-runtime:churn-prevention','coding','.claude\skills\churn-prevention\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ci-cd-pipeline-builder','skill:simplicio-runtime:ci-cd-pipeline-builder','coding','.claude\skills\ci-cd-pipeline-builder\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('claim-chart','skill:simplicio-runtime:claim-chart','content','.claude\skills\claim-chart\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('claude-coach','skill:simplicio-runtime:claude-coach','coding','.claude\skills\claude-coach\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('clinical-research','skill:simplicio-runtime:clinical-research','coding','.claude\skills\clinical-research\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('closing-checklist','skill:simplicio-runtime:closing-checklist','coding','.claude\skills\closing-checklist\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('cloud-security','skill:simplicio-runtime:cloud-security','coding','.claude\skills\cloud-security\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('co-marketing','skill:simplicio-runtime:co-marketing','video','.claude\skills\co-marketing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('code-maturity-assessor','skill:simplicio-runtime:code-maturity-assessor','coding','.claude\skills\code-maturity-assessor\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('code-reviewer','skill:simplicio-runtime:code-reviewer','coding','.claude\skills\code-reviewer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('code-to-prd','skill:simplicio-runtime:code-to-prd','coding','.claude\skills\code-to-prd\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('code-tour','skill:simplicio-runtime:code-tour','coding','.claude\skills\code-tour\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('codebase-onboarding','skill:simplicio-runtime:codebase-onboarding','coding','.claude\skills\codebase-onboarding\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('codeql','skill:simplicio-runtime:codeql','coding','.claude\skills\codeql\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('cold-email','skill:simplicio-runtime:cold-email','coding','.claude\skills\cold-email\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('cold-start-interview','skill:simplicio-runtime:cold-start-interview','coding','.claude\skills\cold-start-interview\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('collab-proof','skill:simplicio-runtime:collab-proof','coding','.claude\skills\collab-proof\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('community-marketing','skill:simplicio-runtime:community-marketing','coding','.claude\skills\community-marketing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('competitive-teardown','skill:simplicio-runtime:competitive-teardown','content','.claude\skills\competitive-teardown\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('competitor-profiling','skill:simplicio-runtime:competitor-profiling','coding','.claude\skills\competitor-profiling\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('competitors','skill:simplicio-runtime:competitors','coding','.claude\skills\competitors\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('compliance-os','skill:simplicio-runtime:compliance-os','orchestration','.claude\skills\compliance-os\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('compliance-readiness','skill:simplicio-runtime:compliance-readiness','coding','.claude\skills\compliance-readiness\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('confluence-expert','skill:simplicio-runtime:confluence-expert','content','.claude\skills\confluence-expert\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('constant-time-analysis','skill:simplicio-runtime:constant-time-analysis','coding','.claude\skills\constant-time-analysis\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('constant-time-testing','skill:simplicio-runtime:constant-time-testing','coding','.claude\skills\constant-time-testing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('content-strategy','skill:simplicio-runtime:content-strategy','content','.claude\skills\content-strategy\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('copy-editing','skill:simplicio-runtime:copy-editing','content','.claude\skills\copy-editing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('copywriting','skill:simplicio-runtime:copywriting','coding','.claude\skills\copywriting\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('cosmos-vulnerability-scanner','skill:simplicio-runtime:cosmos-vulnerability-scanner','coding','.claude\skills\cosmos-vulnerability-scanner\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('coverage','skill:simplicio-runtime:coverage','coding','.claude\skills\coverage\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('coverage-analysis','skill:simplicio-runtime:coverage-analysis','coding','.claude\skills\coverage-analysis\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('cro','skill:simplicio-runtime:cro','coding','.claude\skills\cro\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('crypto-protocol-diagram','skill:simplicio-runtime:crypto-protocol-diagram','coding','.claude\skills\crypto-protocol-diagram\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('customer-research','skill:simplicio-runtime:customer-research','coding','.claude\skills\customer-research\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('customize','skill:simplicio-runtime:customize','coding','.claude\skills\customize\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('data-quality-auditor','skill:simplicio-runtime:data-quality-auditor','coding','.claude\skills\data-quality-auditor\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('database-designer','skill:simplicio-runtime:database-designer','coding','.claude\skills\database-designer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('database-schema-designer','skill:simplicio-runtime:database-schema-designer','coding','.claude\skills\database-schema-designer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('deal-team-summary','skill:simplicio-runtime:deal-team-summary','coding','.claude\skills\deal-team-summary\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('debug-buttercup','skill:simplicio-runtime:debug-buttercup','coding','.claude\skills\debug-buttercup\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('demo-video','skill:simplicio-runtime:demo-video','video','.claude\skills\demo-video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('dependency-auditor','skill:simplicio-runtime:dependency-auditor','coding','.claude\skills\dependency-auditor\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('designing-workflow-skills','skill:simplicio-runtime:designing-workflow-skills','coding','.claude\skills\designing-workflow-skills\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('devcontainer-setup','skill:simplicio-runtime:devcontainer-setup','coding','.claude\skills\devcontainer-setup\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('diagramming-code','skill:simplicio-runtime:diagramming-code','coding','.claude\skills\diagramming-code\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('differential-review','skill:simplicio-runtime:differential-review','coding','.claude\skills\differential-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('diligence-issue-extraction','skill:simplicio-runtime:diligence-issue-extraction','coding','.claude\skills\diligence-issue-extraction\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('dimensional-analysis','skill:simplicio-runtime:dimensional-analysis','coding','.claude\skills\dimensional-analysis\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('directory-submissions','skill:simplicio-runtime:directory-submissions','coding','.claude\skills\directory-submissions\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('docker-development','skill:simplicio-runtime:docker-development','orchestration','.claude\skills\docker-development\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('dossier','skill:simplicio-runtime:dossier','coding','.claude\skills\dossier\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('dwarf-expert','skill:simplicio-runtime:dwarf-expert','coding','.claude\skills\dwarf-expert\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ecc-harness','skill:simplicio-runtime:ecc-harness','coding','.claude\skills\ecc-harness\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('email-template-builder','skill:simplicio-runtime:email-template-builder','coding','.claude\skills\email-template-builder\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('emails','skill:simplicio-runtime:emails','coding','.claude\skills\emails\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('embedded-captions','skill:simplicio-runtime:embedded-captions','video','.claude\skills\embedded-captions\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('engineering-advanced-skills','skill:simplicio-runtime:engineering-advanced-skills','coding','.claude\skills\engineering-advanced-skills\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('engineering-skills','skill:simplicio-runtime:engineering-skills','coding','.claude\skills\engineering-skills\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('entity-compliance','skill:simplicio-runtime:entity-compliance','coding','.claude\skills\entity-compliance\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('entry-point-analyzer','skill:simplicio-runtime:entry-point-analyzer','coding','.claude\skills\entry-point-analyzer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('env-secrets-manager','skill:simplicio-runtime:env-secrets-manager','coding','.claude\skills\env-secrets-manager\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('epic-design','skill:simplicio-runtime:epic-design','coding','.claude\skills\epic-design\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('escalation-flagger','skill:simplicio-runtime:escalation-flagger','coding','.claude\skills\escalation-flagger\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('eu-ai-act-specialist','skill:simplicio-runtime:eu-ai-act-specialist','coding','.claude\skills\eu-ai-act-specialist\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('eval','skill:simplicio-runtime:eval','coding','.claude\skills\eval\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('experiment-designer','skill:simplicio-runtime:experiment-designer','coding','.claude\skills\experiment-designer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('extract','skill:simplicio-runtime:extract','coding','.claude\skills\extract\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('faceless-explainer','skill:simplicio-runtime:faceless-explainer','video','.claude\skills\faceless-explainer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('fda-consultant-specialist','skill:simplicio-runtime:fda-consultant-specialist','coding','.claude\skills\fda-consultant-specialist\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('fda-qsr-audit-prep','skill:simplicio-runtime:fda-qsr-audit-prep','coding','.claude\skills\fda-qsr-audit-prep\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('feature-flags-architect','skill:simplicio-runtime:feature-flags-architect','coding','.claude\skills\feature-flags-architect\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('finance-skills','skill:simplicio-runtime:finance-skills','coding','.claude\skills\finance-skills\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('financial-analyst','skill:simplicio-runtime:financial-analyst','coding','.claude\skills\financial-analyst\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('firebase-apk-scanner','skill:simplicio-runtime:firebase-apk-scanner','coding','.claude\skills\firebase-apk-scanner\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('fix','skill:simplicio-runtime:fix','coding','.claude\skills\fix\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('focused-fix','skill:simplicio-runtime:focused-fix','coding','.claude\skills\focused-fix\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('fp-check','skill:simplicio-runtime:fp-check','coding','.claude\skills\fp-check\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('free-tools','skill:simplicio-runtime:free-tools','coding','.claude\skills\free-tools\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('frontend-design','skill:simplicio-runtime:frontend-design','coding','.claude\skills\frontend-design\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('full-page-screenshot','skill:simplicio-runtime:full-page-screenshot','coding','.claude\skills\full-page-screenshot\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('fuzzing-dictionary','skill:simplicio-runtime:fuzzing-dictionary','coding','.claude\skills\fuzzing-dictionary\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('fuzzing-obstacles','skill:simplicio-runtime:fuzzing-obstacles','coding','.claude\skills\fuzzing-obstacles\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('gcp-cloud-architect','skill:simplicio-runtime:gcp-cloud-architect','coding','.claude\skills\gcp-cloud-architect\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('gdpr-audit-prep','skill:simplicio-runtime:gdpr-audit-prep','coding','.claude\skills\gdpr-audit-prep\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('gdpr-dsgvo-expert','skill:simplicio-runtime:gdpr-dsgvo-expert','coding','.claude\skills\gdpr-dsgvo-expert\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('general-video','skill:simplicio-runtime:general-video','video','.claude\skills\general-video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('generate','skill:simplicio-runtime:generate','coding','.claude\skills\generate\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('genotoxic','skill:simplicio-runtime:genotoxic','coding','.claude\skills\genotoxic\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('gh-cli','skill:simplicio-runtime:gh-cli','coding','.claude\skills\gh-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('git-cleanup','skill:simplicio-runtime:git-cleanup','coding','.claude\skills\git-cleanup\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('git-worktree-manager','skill:simplicio-runtime:git-worktree-manager','coding','.claude\skills\git-worktree-manager\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('google-workspace-cli','skill:simplicio-runtime:google-workspace-cli','coding','.claude\skills\google-workspace-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('grants','skill:simplicio-runtime:grants','coding','.claude\skills\grants\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('graph-evolution','skill:simplicio-runtime:graph-evolution','coding','.claude\skills\graph-evolution\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('graphic-overlays','skill:simplicio-runtime:graphic-overlays','video','.claude\skills\graphic-overlays\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('grill-me','skill:simplicio-runtime:grill-me','coding','.claude\skills\grill-me\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('grill-with-docs','skill:simplicio-runtime:grill-with-docs','coding','.claude\skills\grill-with-docs\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('guidelines-advisor','skill:simplicio-runtime:guidelines-advisor','coding','.claude\skills\guidelines-advisor\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('handoff','skill:simplicio-runtime:handoff','coding','.claude\skills\handoff\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('harness-writing','skill:simplicio-runtime:harness-writing','coding','.claude\skills\harness-writing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('helm-chart-builder','skill:simplicio-runtime:helm-chart-builder','coding','.claude\skills\helm-chart-builder\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes','skill:simplicio-runtime:hyperframes','video','.claude\skills\hyperframes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-animation','skill:simplicio-runtime:hyperframes-animation','video','.claude\skills\hyperframes-animation\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-cli','skill:simplicio-runtime:hyperframes-cli','video','.claude\skills\hyperframes-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-core','skill:simplicio-runtime:hyperframes-core','video','.claude\skills\hyperframes-core\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-creative','skill:simplicio-runtime:hyperframes-creative','video','.claude\skills\hyperframes-creative\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-media','skill:simplicio-runtime:hyperframes-media','video','.claude\skills\hyperframes-media\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-registry','skill:simplicio-runtime:hyperframes-registry','video','.claude\skills\hyperframes-registry\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('image','skill:simplicio-runtime:image','content','.claude\skills\image\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('incident-commander','skill:simplicio-runtime:incident-commander','coding','.claude\skills\incident-commander\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('incident-response','skill:simplicio-runtime:incident-response','coding','.claude\skills\incident-response\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('information-security-manager-iso27001','skill:simplicio-runtime:information-security-manager-iso27001','coding','.claude\skills\information-security-manager-iso27001\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('init','skill:simplicio-runtime:init','coding','.claude\skills\init\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('init-ali','skill:simplicio-runtime:init-ali','coding','.claude\skills\init-ali\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('insecure-defaults','skill:simplicio-runtime:insecure-defaults','coding','.claude\skills\insecure-defaults\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('integration-management','skill:simplicio-runtime:integration-management','coding','.claude\skills\integration-management\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('interpreting-culture-index','skill:simplicio-runtime:interpreting-culture-index','coding','.claude\skills\interpreting-culture-index\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('interview-system-designer','skill:simplicio-runtime:interview-system-designer','coding','.claude\skills\interview-system-designer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('isms-audit-expert','skill:simplicio-runtime:isms-audit-expert','coding','.claude\skills\isms-audit-expert\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('iso13485-audit-prep','skill:simplicio-runtime:iso13485-audit-prep','content','.claude\skills\iso13485-audit-prep\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('iso27001-audit-prep','skill:simplicio-runtime:iso27001-audit-prep','coding','.claude\skills\iso27001-audit-prep\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('iso42001-specialist','skill:simplicio-runtime:iso42001-specialist','coding','.claude\skills\iso42001-specialist\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('jira-expert','skill:simplicio-runtime:jira-expert','coding','.claude\skills\jira-expert\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('karpathy-coder','skill:simplicio-runtime:karpathy-coder','coding','.claude\skills\karpathy-coder\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('kubernetes-operator','skill:simplicio-runtime:kubernetes-operator','coding','.claude\skills\kubernetes-operator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('landing-page-generator','skill:simplicio-runtime:landing-page-generator','coding','.claude\skills\landing-page-generator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('launch','skill:simplicio-runtime:launch','coding','.claude\skills\launch\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('lead-magnets','skill:simplicio-runtime:lead-magnets','content','.claude\skills\lead-magnets\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('let-fate-decide','skill:simplicio-runtime:let-fate-decide','coding','.claude\skills\let-fate-decide\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('libafl','skill:simplicio-runtime:libafl','coding','.claude\skills\libafl\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('libfuzzer','skill:simplicio-runtime:libfuzzer','coding','.claude\skills\libfuzzer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('litreview','skill:simplicio-runtime:litreview','coding','.claude\skills\litreview\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('llm-cost-optimizer','skill:simplicio-runtime:llm-cost-optimizer','coding','.claude\skills\llm-cost-optimizer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('llm-wiki','skill:simplicio-runtime:llm-wiki','coding','.claude\skills\llm-wiki\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('loop','skill:simplicio-runtime:loop','coding','.claude\skills\loop\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('market-research','skill:simplicio-runtime:market-research','coding','.claude\skills\market-research\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('marketing-copywriting','skill:simplicio-runtime:marketing-copywriting','coding','.claude\skills\marketing-copywriting\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('marketing-ideas','skill:simplicio-runtime:marketing-ideas','coding','.claude\skills\marketing-ideas\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('marketing-plan','skill:simplicio-runtime:marketing-plan','coding','.claude\skills\marketing-plan\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('marketing-psychology','skill:simplicio-runtime:marketing-psychology','content','.claude\skills\marketing-psychology\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('material-contract-schedule','skill:simplicio-runtime:material-contract-schedule','coding','.claude\skills\material-contract-schedule\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('matter-workspace','skill:simplicio-runtime:matter-workspace','coding','.claude\skills\matter-workspace\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('mcp-server-builder','skill:simplicio-runtime:mcp-server-builder','coding','.claude\skills\mcp-server-builder\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('mdr-745-specialist','skill:simplicio-runtime:mdr-745-specialist','coding','.claude\skills\mdr-745-specialist\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('media-create','skill:simplicio-runtime:media-create','video','.claude\skills\media-create\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('meeting-analyzer','skill:simplicio-runtime:meeting-analyzer','coding','.claude\skills\meeting-analyzer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('merge','skill:simplicio-runtime:merge','coding','.claude\skills\merge\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('mermaid-to-proverif','skill:simplicio-runtime:mermaid-to-proverif','coding','.claude\skills\mermaid-to-proverif\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('migrate','skill:simplicio-runtime:migrate','coding','.claude\skills\migrate\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('migration-architect','skill:simplicio-runtime:migration-architect','coding','.claude\skills\migration-architect\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('modern-python','skill:simplicio-runtime:modern-python','coding','.claude\skills\modern-python\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('monorepo-navigator','skill:simplicio-runtime:monorepo-navigator','coding','.claude\skills\monorepo-navigator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('motion-graphics','skill:simplicio-runtime:motion-graphics','video','.claude\skills\motion-graphics\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ms365-tenant-manager','skill:simplicio-runtime:ms365-tenant-manager','coding','.claude\skills\ms365-tenant-manager\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('music-to-video','skill:simplicio-runtime:music-to-video','video','.claude\skills\music-to-video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('mutation-testing','skill:simplicio-runtime:mutation-testing','coding','.claude\skills\mutation-testing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('nda-review','skill:simplicio-runtime:nda-review','coding','.claude\skills\nda-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('notebooklm','skill:simplicio-runtime:notebooklm','video','.claude\skills\notebooklm\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('observability-designer','skill:simplicio-runtime:observability-designer','coding','.claude\skills\observability-designer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('offers','skill:simplicio-runtime:offers','coding','.claude\skills\offers\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('onboarding','skill:simplicio-runtime:onboarding','coding','.claude\skills\onboarding\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ossfuzz','skill:simplicio-runtime:ossfuzz','coding','.claude\skills\ossfuzz\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('patent','skill:simplicio-runtime:patent','coding','.claude\skills\patent\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('paywalls','skill:simplicio-runtime:paywalls','coding','.claude\skills\paywalls\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('performance-profiler','skill:simplicio-runtime:performance-profiler','coding','.claude\skills\performance-profiler\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pm-skills','skill:simplicio-runtime:pm-skills','coding','.claude\skills\pm-skills\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('popups','skill:simplicio-runtime:popups','coding','.claude\skills\popups\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pr-review-expert','skill:simplicio-runtime:pr-review-expert','coding','.claude\skills\pr-review-expert\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pr-to-video','skill:simplicio-runtime:pr-to-video','video','.claude\skills\pr-to-video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pricing','skill:simplicio-runtime:pricing','coding','.claude\skills\pricing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('product-analytics','skill:simplicio-runtime:product-analytics','coding','.claude\skills\product-analytics\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('product-discovery','skill:simplicio-runtime:product-discovery','coding','.claude\skills\product-discovery\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('product-launch-video','skill:simplicio-runtime:product-launch-video','video','.claude\skills\product-launch-video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('product-manager-toolkit','skill:simplicio-runtime:product-manager-toolkit','coding','.claude\skills\product-manager-toolkit\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('product-marketing','skill:simplicio-runtime:product-marketing','coding','.claude\skills\product-marketing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('product-research','skill:simplicio-runtime:product-research','coding','.claude\skills\product-research\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('product-skills','skill:simplicio-runtime:product-skills','coding','.claude\skills\product-skills\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('product-strategist','skill:simplicio-runtime:product-strategist','coding','.claude\skills\product-strategist\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('programmatic-seo','skill:simplicio-runtime:programmatic-seo','coding','.claude\skills\programmatic-seo\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('promote','skill:simplicio-runtime:promote','coding','.claude\skills\promote\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('prompt-governance','skill:simplicio-runtime:prompt-governance','coding','.claude\skills\prompt-governance\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('property-based-testing','skill:simplicio-runtime:property-based-testing','coding','.claude\skills\property-based-testing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('prospecting','skill:simplicio-runtime:prospecting','coding','.claude\skills\prospecting\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('psychology-of-marketing','skill:simplicio-runtime:psychology-of-marketing','coding','.claude\skills\psychology-of-marketing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('public-relations','skill:simplicio-runtime:public-relations','coding','.claude\skills\public-relations\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pulse','skill:simplicio-runtime:pulse','coding','.claude\skills\pulse\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pw','skill:simplicio-runtime:pw','coding','.claude\skills\pw\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('qms-audit-expert','skill:simplicio-runtime:qms-audit-expert','coding','.claude\skills\qms-audit-expert\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('quality-documentation-manager','skill:simplicio-runtime:quality-documentation-manager','coding','.claude\skills\quality-documentation-manager\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('quality-manager-qmr','skill:simplicio-runtime:quality-manager-qmr','coding','.claude\skills\quality-manager-qmr\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('quality-manager-qms-iso13485','skill:simplicio-runtime:quality-manager-qms-iso13485','coding','.claude\skills\quality-manager-qms-iso13485\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ra-qm-skills','skill:simplicio-runtime:ra-qm-skills','coding','.claude\skills\ra-qm-skills\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('rag-architect','skill:simplicio-runtime:rag-architect','coding','.claude\skills\rag-architect\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('red-team','skill:simplicio-runtime:red-team','coding','.claude\skills\red-team\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('referrals','skill:simplicio-runtime:referrals','coding','.claude\skills\referrals\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('regulatory-affairs-head','skill:simplicio-runtime:regulatory-affairs-head','coding','.claude\skills\regulatory-affairs-head\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('remember','skill:simplicio-runtime:remember','coding','.claude\skills\remember\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('remotion-to-hyperframes','skill:simplicio-runtime:remotion-to-hyperframes','video','.claude\skills\remotion-to-hyperframes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('renewal-tracker','skill:simplicio-runtime:renewal-tracker','coding','.claude\skills\renewal-tracker\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('report','skill:simplicio-runtime:report','coding','.claude\skills\report\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('research','skill:simplicio-runtime:research','coding','.claude\skills\research\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('research-finance','skill:simplicio-runtime:research-finance','coding','.claude\skills\research-finance\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('research-ops-skills','skill:simplicio-runtime:research-ops-skills','coding','.claude\skills\research-ops-skills\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('research-summarizer','skill:simplicio-runtime:research-summarizer','coding','.claude\skills\research-summarizer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('resume','skill:simplicio-runtime:resume','coding','.claude\skills\resume\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('review','skill:simplicio-runtime:review','video','.claude\skills\review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('review-legal','skill:simplicio-runtime:review-legal','coding','.claude\skills\review-legal\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('review-proposals','skill:simplicio-runtime:review-proposals','coding','.claude\skills\review-proposals\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('revops','skill:simplicio-runtime:revops','coding','.claude\skills\revops\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('risk-management-specialist','skill:simplicio-runtime:risk-management-specialist','coding','.claude\skills\risk-management-specialist\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('roadmap-communicator','skill:simplicio-runtime:roadmap-communicator','coding','.claude\skills\roadmap-communicator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('run','skill:simplicio-runtime:run','coding','.claude\skills\run\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('runbook-generator','skill:simplicio-runtime:runbook-generator','coding','.claude\skills\runbook-generator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('runtime-autonomy','skill:simplicio-runtime:runtime-autonomy','coding','.claude\skills\runtime-autonomy\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ruzzy','skill:simplicio-runtime:ruzzy','coding','.claude\skills\ruzzy\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('saas-metrics-coach','skill:simplicio-runtime:saas-metrics-coach','coding','.claude\skills\saas-metrics-coach\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('saas-msa-review','skill:simplicio-runtime:saas-msa-review','coding','.claude\skills\saas-msa-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('saas-scaffolder','skill:simplicio-runtime:saas-scaffolder','coding','.claude\skills\saas-scaffolder\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('sales-enablement','skill:simplicio-runtime:sales-enablement','coding','.claude\skills\sales-enablement\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('sarif-parsing','skill:simplicio-runtime:sarif-parsing','coding','.claude\skills\sarif-parsing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('schema','skill:simplicio-runtime:schema','coding','.claude\skills\schema\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('scrum-master','skill:simplicio-runtime:scrum-master','coding','.claude\skills\scrum-master\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('seatbelt-sandboxer','skill:simplicio-runtime:seatbelt-sandboxer','coding','.claude\skills\seatbelt-sandboxer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('second-opinion','skill:simplicio-runtime:second-opinion','coding','.claude\skills\second-opinion\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('secrets-vault-manager','skill:simplicio-runtime:secrets-vault-manager','coding','.claude\skills\secrets-vault-manager\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('secure-workflow-guide','skill:simplicio-runtime:secure-workflow-guide','coding','.claude\skills\secure-workflow-guide\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('security-guidance','skill:simplicio-runtime:security-guidance','coding','.claude\skills\security-guidance\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('security-pen-testing','skill:simplicio-runtime:security-pen-testing','coding','.claude\skills\security-pen-testing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('self-eval','skill:simplicio-runtime:self-eval','coding','.claude\skills\self-eval\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('self-improving-agent','skill:simplicio-runtime:self-improving-agent','coding','.claude\skills\self-improving-agent\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('semgrep','skill:simplicio-runtime:semgrep','coding','.claude\skills\semgrep\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('semgrep-rule-creator','skill:simplicio-runtime:semgrep-rule-creator','coding','.claude\skills\semgrep-rule-creator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('semgrep-rule-variant-creator','skill:simplicio-runtime:semgrep-rule-variant-creator','coding','.claude\skills\semgrep-rule-variant-creator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-architect','skill:simplicio-runtime:senior-architect','coding','.claude\skills\senior-architect\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-computer-vision','skill:simplicio-runtime:senior-computer-vision','coding','.claude\skills\senior-computer-vision\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-data-engineer','skill:simplicio-runtime:senior-data-engineer','orchestration','.claude\skills\senior-data-engineer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-data-scientist','skill:simplicio-runtime:senior-data-scientist','coding','.claude\skills\senior-data-scientist\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-devops','skill:simplicio-runtime:senior-devops','coding','.claude\skills\senior-devops\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-frontend','skill:simplicio-runtime:senior-frontend','coding','.claude\skills\senior-frontend\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-fullstack','skill:simplicio-runtime:senior-fullstack','coding','.claude\skills\senior-fullstack\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-ml-engineer','skill:simplicio-runtime:senior-ml-engineer','coding','.claude\skills\senior-ml-engineer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-pm','skill:simplicio-runtime:senior-pm','coding','.claude\skills\senior-pm\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-prompt-engineer','skill:simplicio-runtime:senior-prompt-engineer','coding','.claude\skills\senior-prompt-engineer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-qa','skill:simplicio-runtime:senior-qa','coding','.claude\skills\senior-qa\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-secops','skill:simplicio-runtime:senior-secops','coding','.claude\skills\senior-secops\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('senior-security','skill:simplicio-runtime:senior-security','coding','.claude\skills\senior-security\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('seo-audit','skill:simplicio-runtime:seo-audit','coding','.claude\skills\seo-audit\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('setup','skill:simplicio-runtime:setup','coding','.claude\skills\setup\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('sharp-edges','skill:simplicio-runtime:sharp-edges','coding','.claude\skills\sharp-edges\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ship-gate','skill:simplicio-runtime:ship-gate','coding','.claude\skills\ship-gate\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('signup','skill:simplicio-runtime:signup','coding','.claude\skills\signup\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplicio-autoresearch','skill:simplicio-runtime:simplicio-autoresearch','coding','.claude\skills\simplicio-autoresearch\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplicio-compress','skill:simplicio-runtime:simplicio-compress','orchestration','.claude\skills\simplicio-compress\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplicio-honest-metrics','skill:simplicio-runtime:simplicio-honest-metrics','coding','.claude\skills\simplicio-honest-metrics\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplicio-learn','skill:simplicio-runtime:simplicio-learn','orchestration','.claude\skills\simplicio-learn\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplicio-loop','skill:simplicio-runtime:simplicio-loop','orchestration','.claude\skills\simplicio-loop\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplicio-orient','skill:simplicio-runtime:simplicio-orient','orchestration','.claude\skills\simplicio-orient\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplicio-review','skill:simplicio-runtime:simplicio-review','orchestration','.claude\skills\simplicio-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplicio-tasks','skill:simplicio-runtime:simplicio-tasks','orchestration','.claude\skills\simplicio-tasks\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('site-architecture','skill:simplicio-runtime:site-architecture','coding','.claude\skills\site-architecture\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('skill-improver','skill:simplicio-runtime:skill-improver','coding','.claude\skills\skill-improver\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('skill-security-auditor','skill:simplicio-runtime:skill-security-auditor','coding','.claude\skills\skill-security-auditor\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('skill-tester','skill:simplicio-runtime:skill-tester','coding','.claude\skills\skill-tester\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('slideshow','skill:simplicio-runtime:slideshow','video','.claude\skills\slideshow\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('slo-architect','skill:simplicio-runtime:slo-architect','coding','.claude\skills\slo-architect\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('sms','skill:simplicio-runtime:sms','video','.claude\skills\sms\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('snowflake-development','skill:simplicio-runtime:snowflake-development','coding','.claude\skills\snowflake-development\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('soc2-audit-prep','skill:simplicio-runtime:soc2-audit-prep','coding','.claude\skills\soc2-audit-prep\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('soc2-compliance','skill:simplicio-runtime:soc2-compliance','coding','.claude\skills\soc2-compliance\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('social','skill:simplicio-runtime:social','content','.claude\skills\social\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('solana-vulnerability-scanner','skill:simplicio-runtime:solana-vulnerability-scanner','coding','.claude\skills\solana-vulnerability-scanner\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('spawn','skill:simplicio-runtime:spawn','coding','.claude\skills\spawn\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('spec-driven-workflow','skill:simplicio-runtime:spec-driven-workflow','coding','.claude\skills\spec-driven-workflow\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('spec-to-code-compliance','skill:simplicio-runtime:spec-to-code-compliance','coding','.claude\skills\spec-to-code-compliance\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('spec-to-repo','skill:simplicio-runtime:spec-to-repo','coding','.claude\skills\spec-to-repo\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('sql-database-assistant','skill:simplicio-runtime:sql-database-assistant','coding','.claude\skills\sql-database-assistant\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('stakeholder-summary','skill:simplicio-runtime:stakeholder-summary','coding','.claude\skills\stakeholder-summary\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('statistical-analyst','skill:simplicio-runtime:statistical-analyst','coding','.claude\skills\statistical-analyst\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('status','skill:simplicio-runtime:status','coding','.claude\skills\status\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('status-ali','skill:simplicio-runtime:status-ali','coding','.claude\skills\status-ali\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('stripe-integration-expert','skill:simplicio-runtime:stripe-integration-expert','coding','.claude\skills\stripe-integration-expert\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('substrate-vulnerability-scanner','skill:simplicio-runtime:substrate-vulnerability-scanner','coding','.claude\skills\substrate-vulnerability-scanner\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('superpowers','skill:simplicio-runtime:superpowers','coding','.claude\skills\superpowers\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('supply-chain-risk-auditor','skill:simplicio-runtime:supply-chain-risk-auditor','coding','.claude\skills\supply-chain-risk-auditor\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('syllabus','skill:simplicio-runtime:syllabus','coding','.claude\skills\syllabus\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('tabular-review','skill:simplicio-runtime:tabular-review','coding','.claude\skills\tabular-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('tc-tracker','skill:simplicio-runtime:tc-tracker','coding','.claude\skills\tc-tracker\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('tdd-guide','skill:simplicio-runtime:tdd-guide','coding','.claude\skills\tdd-guide\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('team-communications','skill:simplicio-runtime:team-communications','coding','.claude\skills\team-communications\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('tech-debt-tracker','skill:simplicio-runtime:tech-debt-tracker','coding','.claude\skills\tech-debt-tracker\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('tech-stack-evaluator','skill:simplicio-runtime:tech-stack-evaluator','coding','.claude\skills\tech-stack-evaluator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('terraform-patterns','skill:simplicio-runtime:terraform-patterns','coding','.claude\skills\terraform-patterns\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('testing-handbook-generator','skill:simplicio-runtime:testing-handbook-generator','content','.claude\skills\testing-handbook-generator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('testrail','skill:simplicio-runtime:testrail','coding','.claude\skills\testrail\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('threat-detection','skill:simplicio-runtime:threat-detection','coding','.claude\skills\threat-detection\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('token-integration-analyzer','skill:simplicio-runtime:token-integration-analyzer','coding','.claude\skills\token-integration-analyzer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ton-vulnerability-scanner','skill:simplicio-runtime:ton-vulnerability-scanner','coding','.claude\skills\ton-vulnerability-scanner\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('trailmark','skill:simplicio-runtime:trailmark','coding','.claude\skills\trailmark\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('trailmark-structural','skill:simplicio-runtime:trailmark-structural','coding','.claude\skills\trailmark-structural\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('trailmark-summary','skill:simplicio-runtime:trailmark-summary','coding','.claude\skills\trailmark-summary\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ui-design-system','skill:simplicio-runtime:ui-design-system','coding','.claude\skills\ui-design-system\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ui-ux','skill:simplicio-runtime:ui-ux','coding','.claude\skills\ui-ux\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('universal-scraping-architect','skill:simplicio-runtime:universal-scraping-architect','coding','.claude\skills\universal-scraping-architect\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ux-researcher-designer','skill:simplicio-runtime:ux-researcher-designer','coding','.claude\skills\ux-researcher-designer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('variant-analysis','skill:simplicio-runtime:variant-analysis','coding','.claude\skills\variant-analysis\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('vector-forge','skill:simplicio-runtime:vector-forge','coding','.claude\skills\vector-forge\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('vendor-agreement-review','skill:simplicio-runtime:vendor-agreement-review','coding','.claude\skills\vendor-agreement-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('video','skill:simplicio-runtime:video','video','.claude\skills\video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('web-design-guidelines','skill:simplicio-runtime:web-design-guidelines','coding','.claude\skills\web-design-guidelines\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('web-research','skill:simplicio-runtime:web-research','coding','.claude\skills\web-research\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('website-to-video','skill:simplicio-runtime:website-to-video','video','.claude\skills\website-to-video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('workflow-builder','skill:simplicio-runtime:workflow-builder','orchestration','.claude\skills\workflow-builder\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('write-a-skill','skill:simplicio-runtime:write-a-skill','coding','.claude\skills\write-a-skill\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('written-consent','skill:simplicio-runtime:written-consent','coding','.claude\skills\written-consent\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('wycheproof','skill:simplicio-runtime:wycheproof','coding','.claude\skills\wycheproof\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('yara-rule-authoring','skill:simplicio-runtime:yara-rule-authoring','coding','.claude\skills\yara-rule-authoring\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('zeroize-audit','skill:simplicio-runtime:zeroize-audit','coding','.claude\skills\zeroize-audit\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('1password','skill:simplicio-runtime:1password','coding','.simplicio-loop\skills\1password\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('3-statement-model','skill:simplicio-runtime:3-statement-model','coding','.simplicio-loop\skills\3-statement-model\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('_template','skill:simplicio-runtime:_template','coding','.simplicio-loop\skills\_template\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('accelerate','skill:simplicio-runtime:accelerate','orchestration','.simplicio-loop\skills\accelerate\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('agentmail','skill:simplicio-runtime:agentmail','coding','.simplicio-loop\skills\agentmail\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('airtable','skill:simplicio-runtime:airtable','coding','.simplicio-loop\skills\airtable\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('animejs','skill:simplicio-runtime:animejs','video','.simplicio-loop\skills\animejs\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('antigravity-cli','skill:simplicio-runtime:antigravity-cli','coding','.simplicio-loop\skills\antigravity-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('apple-notes','skill:simplicio-runtime:apple-notes','coding','.simplicio-loop\skills\apple-notes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('apple-reminders','skill:simplicio-runtime:apple-reminders','coding','.simplicio-loop\skills\apple-reminders\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('architecture-diagram','skill:simplicio-runtime:architecture-diagram','coding','.simplicio-loop\skills\architecture-diagram\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('arxiv','skill:simplicio-runtime:arxiv','coding','.simplicio-loop\skills\arxiv\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ascii-art','skill:simplicio-runtime:ascii-art','coding','.simplicio-loop\skills\ascii-art\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ascii-video','skill:simplicio-runtime:ascii-video','video','.simplicio-loop\skills\ascii-video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('baoyu-article-illustrator','skill:simplicio-runtime:baoyu-article-illustrator','coding','.simplicio-loop\skills\baoyu-article-illustrator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('baoyu-comic','skill:simplicio-runtime:baoyu-comic','coding','.simplicio-loop\skills\baoyu-comic\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('baoyu-infographic','skill:simplicio-runtime:baoyu-infographic','coding','.simplicio-loop\skills\baoyu-infographic\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('bioinformatics','skill:simplicio-runtime:bioinformatics','coding','.simplicio-loop\skills\bioinformatics\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('blackbox','skill:simplicio-runtime:blackbox','coding','.simplicio-loop\skills\blackbox\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('blender-mcp','skill:simplicio-runtime:blender-mcp','coding','.simplicio-loop\skills\blender-mcp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('blogwatcher','skill:simplicio-runtime:blogwatcher','coding','.simplicio-loop\skills\blogwatcher\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('brainstorming','skill:simplicio-runtime:brainstorming','coding','.simplicio-loop\skills\brainstorming\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('canvas','skill:simplicio-runtime:canvas','coding','.simplicio-loop\skills\canvas\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('caveman','skill:simplicio-runtime:caveman:skills','coding','.simplicio-loop\skills\caveman\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('chroma','skill:simplicio-runtime:chroma','orchestration','.simplicio-loop\skills\chroma\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('claude','skill:simplicio-runtime:claude','coding','.simplicio-loop\skills\claude\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('claude-code','skill:simplicio-runtime:claude-code','orchestration','.simplicio-loop\skills\claude-code\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('claude-design','skill:simplicio-runtime:claude-design','video','.simplicio-loop\skills\claude-design\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('cli','skill:simplicio-runtime:cli','video','.simplicio-loop\skills\cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('clip','skill:simplicio-runtime:clip','content','.simplicio-loop\skills\clip\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('code-wiki','skill:simplicio-runtime:code-wiki','coding','.simplicio-loop\skills\code-wiki\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('codebase-inspection','skill:simplicio-runtime:codebase-inspection','coding','.simplicio-loop\skills\codebase-inspection\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('codex','skill:simplicio-runtime:codex','coding','.simplicio-loop\skills\codex\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('comfyui','skill:simplicio-runtime:comfyui','video','.simplicio-loop\skills\comfyui\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('comps-analysis','skill:simplicio-runtime:comps-analysis','coding','.simplicio-loop\skills\comps-analysis\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('concept-diagrams','skill:simplicio-runtime:concept-diagrams','coding','.simplicio-loop\skills\concept-diagrams\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('contribute-catalog','skill:simplicio-runtime:contribute-catalog','video','.simplicio-loop\skills\contribute-catalog\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('conventional-commits','skill:simplicio-runtime:conventional-commits','coding','.simplicio-loop\skills\conventional-commits\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('creative-ideation','skill:simplicio-runtime:creative-ideation','coding','.simplicio-loop\skills\creative-ideation\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('css-animations','skill:simplicio-runtime:css-animations','video','.simplicio-loop\skills\css-animations\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('darwinian-evolver','skill:simplicio-runtime:darwinian-evolver','coding','.simplicio-loop\skills\darwinian-evolver\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('dcf-model','skill:simplicio-runtime:dcf-model','coding','.simplicio-loop\skills\dcf-model\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('design-md','skill:simplicio-runtime:design-md','coding','.simplicio-loop\skills\design-md\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('docker-management','skill:simplicio-runtime:docker-management','coding','.simplicio-loop\skills\docker-management\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('dogfood','skill:simplicio-runtime:dogfood','coding','.simplicio-loop\skills\dogfood\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('domain-intel','skill:simplicio-runtime:domain-intel','coding','.simplicio-loop\skills\domain-intel\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('drug-discovery','skill:simplicio-runtime:drug-discovery','coding','.simplicio-loop\skills\drug-discovery\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('duckduckgo-search','skill:simplicio-runtime:duckduckgo-search','video','.simplicio-loop\skills\duckduckgo-search\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('everything-claude-code','skill:simplicio-runtime:everything-claude-code','coding','.simplicio-loop\skills\everything-claude-code\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('evm','skill:simplicio-runtime:evm','coding','.simplicio-loop\skills\evm\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('excalidraw','skill:simplicio-runtime:excalidraw','coding','.simplicio-loop\skills\excalidraw\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('excel-author','skill:simplicio-runtime:excel-author','coding','.simplicio-loop\skills\excel-author\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('extraction-plan','skill:simplicio-runtime:extraction-plan','coding','.simplicio-loop\skills\extraction-plan\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('faiss','skill:simplicio-runtime:faiss','orchestration','.simplicio-loop\skills\faiss\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('fastmcp','skill:simplicio-runtime:fastmcp','coding','.simplicio-loop\skills\fastmcp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('findmy','skill:simplicio-runtime:findmy','coding','.simplicio-loop\skills\findmy\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('fitness-nutrition','skill:simplicio-runtime:fitness-nutrition','coding','.simplicio-loop\skills\fitness-nutrition\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('flash-attention','skill:simplicio-runtime:flash-attention','coding','.simplicio-loop\skills\flash-attention\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('gif-search','skill:simplicio-runtime:gif-search','coding','.simplicio-loop\skills\gif-search\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('github-auth','skill:simplicio-runtime:github-auth','coding','.simplicio-loop\skills\github-auth\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('github-code-review','skill:simplicio-runtime:github-code-review','coding','.simplicio-loop\skills\github-code-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('github-issues','skill:simplicio-runtime:github-issues','coding','.simplicio-loop\skills\github-issues\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('github-pr-workflow','skill:simplicio-runtime:github-pr-workflow','coding','.simplicio-loop\skills\github-pr-workflow\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('github-repo-management','skill:simplicio-runtime:github-repo-management','coding','.simplicio-loop\skills\github-repo-management\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('gitnexus-explorer','skill:simplicio-runtime:gitnexus-explorer','coding','.simplicio-loop\skills\gitnexus-explorer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('godmode','skill:simplicio-runtime:godmode','coding','.simplicio-loop\skills\godmode\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('google-workspace','skill:simplicio-runtime:google-workspace','coding','.simplicio-loop\skills\google-workspace\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('google_meet','skill:simplicio-runtime:google_meet','video','.simplicio-loop\skills\google_meet\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('grok','skill:simplicio-runtime:grok','orchestration','.simplicio-loop\skills\grok\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('gsap','skill:simplicio-runtime:gsap','video','.simplicio-loop\skills\gsap\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('guidance','skill:simplicio-runtime:guidance','orchestration','.simplicio-loop\skills\guidance\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('heartmula','skill:simplicio-runtime:heartmula','coding','.simplicio-loop\skills\heartmula\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('here-now','skill:simplicio-runtime:here-now','coding','.simplicio-loop\skills\here-now\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hermes-agent','skill:simplicio-runtime:hermes-agent','coding','.simplicio-loop\skills\hermes-agent\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hermes-agent-skill-authoring','skill:simplicio-runtime:hermes-agent-skill-authoring','coding','.simplicio-loop\skills\hermes-agent-skill-authoring\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hermes-s6-container-supervision','skill:simplicio-runtime:hermes-s6-container-supervision','coding','.simplicio-loop\skills\hermes-s6-container-supervision\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('himalaya','skill:simplicio-runtime:himalaya','coding','.simplicio-loop\skills\himalaya\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('honcho','skill:simplicio-runtime:honcho','coding','.simplicio-loop\skills\honcho\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('huggingface-hub','skill:simplicio-runtime:huggingface-hub','coding','.simplicio-loop\skills\huggingface-hub\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('huggingface-tokenizers','skill:simplicio-runtime:huggingface-tokenizers','coding','.simplicio-loop\skills\huggingface-tokenizers\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('humanizer','skill:simplicio-runtime:humanizer','content','.simplicio-loop\skills\humanizer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes','skill:simplicio-runtime:hyperframes:skills','video','.simplicio-loop\skills\hyperframes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-cli','skill:simplicio-runtime:hyperframes-cli:skills','video','.simplicio-loop\skills\hyperframes-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-media','skill:simplicio-runtime:hyperframes-media:skills','video','.simplicio-loop\skills\hyperframes-media\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-registry','skill:simplicio-runtime:hyperframes-registry:skills','video','.simplicio-loop\skills\hyperframes-registry\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperliquid','skill:simplicio-runtime:hyperliquid','coding','.simplicio-loop\skills\hyperliquid\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('imessage','skill:simplicio-runtime:imessage','coding','.simplicio-loop\skills\imessage\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('instructor','skill:simplicio-runtime:instructor','orchestration','.simplicio-loop\skills\instructor\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('jira-task-runner','skill:simplicio-runtime:jira-task-runner','coding','.simplicio-loop\skills\jira-task-runner\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('jupyter-live-kernel','skill:simplicio-runtime:jupyter-live-kernel','coding','.simplicio-loop\skills\jupyter-live-kernel\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('kanban-orchestrator','skill:simplicio-runtime:kanban-orchestrator','orchestration','.simplicio-loop\skills\kanban-orchestrator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('kanban-video-orchestrator','skill:simplicio-runtime:kanban-video-orchestrator','video','.simplicio-loop\skills\kanban-video-orchestrator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('kanban-worker','skill:simplicio-runtime:kanban-worker','coding','.simplicio-loop\skills\kanban-worker\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('lambda-labs','skill:simplicio-runtime:lambda-labs','orchestration','.simplicio-loop\skills\lambda-labs\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('lbo-model','skill:simplicio-runtime:lbo-model','coding','.simplicio-loop\skills\lbo-model\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('llava','skill:simplicio-runtime:llava','coding','.simplicio-loop\skills\llava\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('llm-verification','skill:simplicio-runtime:llm-verification','coding','.simplicio-loop\skills\llm-verification\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('llm-wiki','skill:simplicio-runtime:llm-wiki:skills','coding','.simplicio-loop\skills\llm-wiki\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('lottie','skill:simplicio-runtime:lottie','video','.simplicio-loop\skills\lottie\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('macos-computer-use','skill:simplicio-runtime:macos-computer-use','coding','.simplicio-loop\skills\macos-computer-use\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('manim-video','skill:simplicio-runtime:manim-video','video','.simplicio-loop\skills\manim-video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('maps','skill:simplicio-runtime:maps','coding','.simplicio-loop\skills\maps\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('mcporter','skill:simplicio-runtime:mcporter','coding','.simplicio-loop\skills\mcporter\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('meme-generation','skill:simplicio-runtime:meme-generation','coding','.simplicio-loop\skills\meme-generation\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('memento-flashcards','skill:simplicio-runtime:memento-flashcards','content','.simplicio-loop\skills\memento-flashcards\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('merger-model','skill:simplicio-runtime:merger-model','coding','.simplicio-loop\skills\merger-model\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('minecraft-modpack-server','skill:simplicio-runtime:minecraft-modpack-server','coding','.simplicio-loop\skills\minecraft-modpack-server\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('modal','skill:simplicio-runtime:modal','orchestration','.simplicio-loop\skills\modal\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('nano-pdf','skill:simplicio-runtime:nano-pdf','coding','.simplicio-loop\skills\nano-pdf\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('nemo-curator','skill:simplicio-runtime:nemo-curator','video','.simplicio-loop\skills\nemo-curator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('neuroskill-bci','skill:simplicio-runtime:neuroskill-bci','video','.simplicio-loop\skills\neuroskill-bci\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('node-inspect-debugger','skill:simplicio-runtime:node-inspect-debugger','coding','.simplicio-loop\skills\node-inspect-debugger\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('notion','skill:simplicio-runtime:notion','coding','.simplicio-loop\skills\notion\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('obliteratus','skill:simplicio-runtime:obliteratus','coding','.simplicio-loop\skills\obliteratus\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('obsidian','skill:simplicio-runtime:obsidian','content','.simplicio-loop\skills\obsidian\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ocr-and-documents','skill:simplicio-runtime:ocr-and-documents','coding','.simplicio-loop\skills\ocr-and-documents\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('one-three-one-rule','skill:simplicio-runtime:one-three-one-rule','coding','.simplicio-loop\skills\one-three-one-rule\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('openclaw-migration','skill:simplicio-runtime:openclaw-migration','coding','.simplicio-loop\skills\openclaw-migration\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('opencode','skill:simplicio-runtime:opencode','coding','.simplicio-loop\skills\opencode\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('openhands','skill:simplicio-runtime:openhands','coding','.simplicio-loop\skills\openhands\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('openhue','skill:simplicio-runtime:openhue','coding','.simplicio-loop\skills\openhue\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('osint-investigation','skill:simplicio-runtime:osint-investigation','coding','.simplicio-loop\skills\osint-investigation\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('oss-forensics','skill:simplicio-runtime:oss-forensics','coding','.simplicio-loop\skills\oss-forensics\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('p5js','skill:simplicio-runtime:p5js','video','.simplicio-loop\skills\p5js\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('page-agent','skill:simplicio-runtime:page-agent','coding','.simplicio-loop\skills\page-agent\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('parallel-cli','skill:simplicio-runtime:parallel-cli','coding','.simplicio-loop\skills\parallel-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('payments','skill:simplicio-runtime:payments','coding','.simplicio-loop\skills\payments\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('peft','skill:simplicio-runtime:peft','orchestration','.simplicio-loop\skills\peft\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pinecone','skill:simplicio-runtime:pinecone','orchestration','.simplicio-loop\skills\pinecone\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pinggy-tunnel','skill:simplicio-runtime:pinggy-tunnel','coding','.simplicio-loop\skills\pinggy-tunnel\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pixel-art','skill:simplicio-runtime:pixel-art','video','.simplicio-loop\skills\pixel-art\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('plan','skill:simplicio-runtime:plan','coding','.simplicio-loop\skills\plan\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('playwright-e2e','skill:simplicio-runtime:playwright-e2e','coding','.simplicio-loop\skills\playwright-e2e\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pokemon-player','skill:simplicio-runtime:pokemon-player','coding','.simplicio-loop\skills\pokemon-player\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('polymarket','skill:simplicio-runtime:polymarket','coding','.simplicio-loop\skills\polymarket\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('popular-web-designs','skill:simplicio-runtime:popular-web-designs','coding','.simplicio-loop\skills\popular-web-designs\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('powerpoint','skill:simplicio-runtime:powerpoint','coding','.simplicio-loop\skills\powerpoint\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pptx-author','skill:simplicio-runtime:pptx-author','coding','.simplicio-loop\skills\pptx-author\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pretext','skill:simplicio-runtime:pretext','coding','.simplicio-loop\skills\pretext\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('python-debugpy','skill:simplicio-runtime:python-debugpy','coding','.simplicio-loop\skills\python-debugpy\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pytorch-fsdp','skill:simplicio-runtime:pytorch-fsdp','orchestration','.simplicio-loop\skills\pytorch-fsdp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pytorch-lightning','skill:simplicio-runtime:pytorch-lightning','orchestration','.simplicio-loop\skills\pytorch-lightning\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('qdrant','skill:simplicio-runtime:qdrant','orchestration','.simplicio-loop\skills\qdrant\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('qmd','skill:simplicio-runtime:qmd','coding','.simplicio-loop\skills\qmd\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ralph-loop','skill:simplicio-runtime:ralph-loop','orchestration','.simplicio-loop\skills\ralph-loop\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('remotion-to-hyperframes','skill:simplicio-runtime:remotion-to-hyperframes:skills','video','.simplicio-loop\skills\remotion-to-hyperframes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('requesting-code-review','skill:simplicio-runtime:requesting-code-review','coding','.simplicio-loop\skills\requesting-code-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('research-paper-writing','skill:simplicio-runtime:research-paper-writing','orchestration','.simplicio-loop\skills\research-paper-writing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('rest-graphql-debug','skill:simplicio-runtime:rest-graphql-debug','coding','.simplicio-loop\skills\rest-graphql-debug\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('revisao-humanizada','skill:simplicio-runtime:revisao-humanizada','content','.simplicio-loop\skills\revisao-humanizada\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('rtk-cli','skill:simplicio-runtime:rtk-cli','coding','.simplicio-loop\skills\rtk-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('saelens','skill:simplicio-runtime:saelens','orchestration','.simplicio-loop\skills\saelens\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('scrapling','skill:simplicio-runtime:scrapling','coding','.simplicio-loop\skills\scrapling\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('searxng-search','skill:simplicio-runtime:searxng-search','coding','.simplicio-loop\skills\searxng-search\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('sherlock','skill:simplicio-runtime:sherlock','content','.simplicio-loop\skills\sherlock\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('shop-app','skill:simplicio-runtime:shop-app','coding','.simplicio-loop\skills\shop-app\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('shopify','skill:simplicio-runtime:shopify','coding','.simplicio-loop\skills\shopify\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplicio-cli','skill:simplicio-runtime:simplicio-cli','coding','.simplicio-loop\skills\simplicio-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplify-code','skill:simplicio-runtime:simplify-code','coding','.simplicio-loop\skills\simplify-code\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simpo','skill:simplicio-runtime:simpo','orchestration','.simplicio-loop\skills\simpo\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('siyuan','skill:simplicio-runtime:siyuan','coding','.simplicio-loop\skills\siyuan\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('sketch','skill:simplicio-runtime:sketch','coding','.simplicio-loop\skills\sketch\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('skill','skill:simplicio-runtime:skill','coding','.simplicio-loop\skills\skill\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('skill-opt','skill:simplicio-runtime:skill-opt','coding','.simplicio-loop\skills\skill-opt\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('slime','skill:simplicio-runtime:slime','orchestration','.simplicio-loop\skills\slime\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('social-media-ops','skill:simplicio-runtime:social-media-ops','content','.simplicio-loop\skills\social-media-ops\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('solana','skill:simplicio-runtime:solana','coding','.simplicio-loop\skills\solana\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('songsee','skill:simplicio-runtime:songsee','coding','.simplicio-loop\skills\songsee\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('songwriting-and-ai-music','skill:simplicio-runtime:songwriting-and-ai-music','coding','.simplicio-loop\skills\songwriting-and-ai-music\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('spike','skill:simplicio-runtime:spike','coding','.simplicio-loop\skills\spike\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('stable-diffusion','skill:simplicio-runtime:stable-diffusion','orchestration','.simplicio-loop\skills\stable-diffusion\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('stocks','skill:simplicio-runtime:stocks','coding','.simplicio-loop\skills\stocks\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('subagent-driven-development','skill:simplicio-runtime:subagent-driven-development','coding','.simplicio-loop\skills\subagent-driven-development\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('systematic-debugging','skill:simplicio-runtime:systematic-debugging','coding','.simplicio-loop\skills\systematic-debugging\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('tailwind','skill:simplicio-runtime:tailwind','video','.simplicio-loop\skills\tailwind\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('teams-meeting-pipeline','skill:simplicio-runtime:teams-meeting-pipeline','coding','.simplicio-loop\skills\teams-meeting-pipeline\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('telephony','skill:simplicio-runtime:telephony','coding','.simplicio-loop\skills\telephony\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('tensorrt-llm','skill:simplicio-runtime:tensorrt-llm','orchestration','.simplicio-loop\skills\tensorrt-llm\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('test-driven-development','skill:simplicio-runtime:test-driven-development','coding','.simplicio-loop\skills\test-driven-development\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('three','skill:simplicio-runtime:three','video','.simplicio-loop\skills\three\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('torchtitan','skill:simplicio-runtime:torchtitan','orchestration','.simplicio-loop\skills\torchtitan\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('touchdesigner-mcp','skill:simplicio-runtime:touchdesigner-mcp','coding','.simplicio-loop\skills\touchdesigner-mcp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('typegpu','skill:simplicio-runtime:typegpu','video','.simplicio-loop\skills\typegpu\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('unreal-engine-mcp','skill:simplicio-runtime:unreal-engine-mcp','coding','.simplicio-loop\skills\unreal-engine-mcp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('using-superpowers','skill:simplicio-runtime:using-superpowers','coding','.simplicio-loop\skills\using-superpowers\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('verification-before-completion','skill:simplicio-runtime:verification-before-completion','coding','.simplicio-loop\skills\verification-before-completion\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('viral-product-strategist','skill:simplicio-runtime:viral-product-strategist','coding','.simplicio-loop\skills\viral-product-strategist\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('waapi','skill:simplicio-runtime:waapi','video','.simplicio-loop\skills\waapi\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('watchers','skill:simplicio-runtime:watchers','coding','.simplicio-loop\skills\watchers\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('web-pentest','skill:simplicio-runtime:web-pentest','coding','.simplicio-loop\skills\web-pentest\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('website-to-hyperframes','skill:simplicio-runtime:website-to-hyperframes','video','.simplicio-loop\skills\website-to-hyperframes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('whisper','skill:simplicio-runtime:whisper','orchestration','.simplicio-loop\skills\whisper\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('writing-plans','skill:simplicio-runtime:writing-plans','coding','.simplicio-loop\skills\writing-plans\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('xurl','skill:simplicio-runtime:xurl','content','.simplicio-loop\skills\xurl\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('youtube-content','skill:simplicio-runtime:youtube-content','video','.simplicio-loop\skills\youtube-content\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('yuanbao','skill:simplicio-runtime:yuanbao','coding','.simplicio-loop\skills\yuanbao\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('revisao-humanizada','skill:simplicio-runtime:revisao-humanizada:.skills','content','.skills\revisao-humanizada\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('adversarial-ux-test','skill:simplicio-runtime:adversarial-ux-test','coding','.simplicio-loop\skills\dogfood\adversarial-ux-test\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('google_meet','skill:simplicio-runtime:google_meet:plugins','video','plugins\google_meet\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('skill','skill:simplicio-runtime:skill:simplicio','coding','publish\simpleti\simplicio\skill\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('_template','skill:simplicio-runtime:_template:skills','coding','skills\_template\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('apple-notes','skill:simplicio-runtime:apple-notes:apple','coding','skills\apple\apple-notes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('apple-reminders','skill:simplicio-runtime:apple-reminders:apple','coding','skills\apple\apple-reminders\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('findmy','skill:simplicio-runtime:findmy:apple','coding','skills\apple\findmy\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('imessage','skill:simplicio-runtime:imessage:apple','coding','skills\apple\imessage\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('macos-computer-use','skill:simplicio-runtime:macos-computer-use:apple','coding','skills\apple\macos-computer-use\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('asolaria-patterns','skill:simplicio-runtime:asolaria-patterns','coding','skills\asolaria\asolaria-patterns\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('antigravity-cli','skill:simplicio-runtime:antigravity-cli:autonomous-ai-agents','coding','skills\autonomous-ai-agents\antigravity-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('blackbox','skill:simplicio-runtime:blackbox:autonomous-ai-agents','coding','skills\autonomous-ai-agents\blackbox\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('claude-code','skill:simplicio-runtime:claude-code:autonomous-ai-agents','orchestration','skills\autonomous-ai-agents\claude-code\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('codex','skill:simplicio-runtime:codex:autonomous-ai-agents','coding','skills\autonomous-ai-agents\codex\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('grok','skill:simplicio-runtime:grok:autonomous-ai-agents','orchestration','skills\autonomous-ai-agents\grok\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hermes-agent','skill:simplicio-runtime:hermes-agent:autonomous-ai-agents','coding','skills\autonomous-ai-agents\hermes-agent\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('honcho','skill:simplicio-runtime:honcho:autonomous-ai-agents','coding','skills\autonomous-ai-agents\honcho\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('opencode','skill:simplicio-runtime:opencode:autonomous-ai-agents','coding','skills\autonomous-ai-agents\opencode\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('openhands','skill:simplicio-runtime:openhands:autonomous-ai-agents','coding','skills\autonomous-ai-agents\openhands\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('evm','skill:simplicio-runtime:evm:blockchain','coding','skills\blockchain\evm\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperliquid','skill:simplicio-runtime:hyperliquid:blockchain','coding','skills\blockchain\hyperliquid\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('solana','skill:simplicio-runtime:solana:blockchain','coding','skills\blockchain\solana\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('one-three-one-rule','skill:simplicio-runtime:one-three-one-rule:communication','coding','skills\communication\one-three-one-rule\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('conventional-commits','skill:simplicio-runtime:conventional-commits:skills','coding','skills\conventional-commits\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('architecture-diagram','skill:simplicio-runtime:architecture-diagram:creative','coding','skills\creative\architecture-diagram\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ascii-art','skill:simplicio-runtime:ascii-art:creative','coding','skills\creative\ascii-art\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ascii-video','skill:simplicio-runtime:ascii-video:creative','video','skills\creative\ascii-video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('baoyu-article-illustrator','skill:simplicio-runtime:baoyu-article-illustrator:creative','coding','skills\creative\baoyu-article-illustrator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('baoyu-comic','skill:simplicio-runtime:baoyu-comic:creative','coding','skills\creative\baoyu-comic\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('baoyu-infographic','skill:simplicio-runtime:baoyu-infographic:creative','coding','skills\creative\baoyu-infographic\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('blender-mcp','skill:simplicio-runtime:blender-mcp:creative','coding','skills\creative\blender-mcp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('claude-design','skill:simplicio-runtime:claude-design:creative','video','skills\creative\claude-design\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('comfyui','skill:simplicio-runtime:comfyui:creative','video','skills\creative\comfyui\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('concept-diagrams','skill:simplicio-runtime:concept-diagrams:creative','coding','skills\creative\concept-diagrams\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('creative-ideation','skill:simplicio-runtime:creative-ideation:creative','coding','skills\creative\creative-ideation\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('design-md','skill:simplicio-runtime:design-md:creative','coding','skills\creative\design-md\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('excalidraw','skill:simplicio-runtime:excalidraw:creative','coding','skills\creative\excalidraw\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('humanizer','skill:simplicio-runtime:humanizer:creative','content','skills\creative\humanizer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes','skill:simplicio-runtime:hyperframes:creative','video','skills\creative\hyperframes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('kanban-video-orchestrator','skill:simplicio-runtime:kanban-video-orchestrator:creative','video','skills\creative\kanban-video-orchestrator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('manim-video','skill:simplicio-runtime:manim-video:creative','video','skills\creative\manim-video\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('meme-generation','skill:simplicio-runtime:meme-generation:creative','coding','skills\creative\meme-generation\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('p5js','skill:simplicio-runtime:p5js:creative','video','skills\creative\p5js\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pixel-art','skill:simplicio-runtime:pixel-art:creative','video','skills\creative\pixel-art\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('popular-web-designs','skill:simplicio-runtime:popular-web-designs:creative','coding','skills\creative\popular-web-designs\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pretext','skill:simplicio-runtime:pretext:creative','coding','skills\creative\pretext\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('sketch','skill:simplicio-runtime:sketch:creative','coding','skills\creative\sketch\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('songwriting-and-ai-music','skill:simplicio-runtime:songwriting-and-ai-music:creative','coding','skills\creative\songwriting-and-ai-music\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('touchdesigner-mcp','skill:simplicio-runtime:touchdesigner-mcp:creative','coding','skills\creative\touchdesigner-mcp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('unreal-engine-mcp','skill:simplicio-runtime:unreal-engine-mcp:creative','coding','skills\creative\unreal-engine-mcp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('jupyter-live-kernel','skill:simplicio-runtime:jupyter-live-kernel:data-science','coding','skills\data-science\jupyter-live-kernel\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('cli','skill:simplicio-runtime:cli:devops','video','skills\devops\cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('docker-management','skill:simplicio-runtime:docker-management:devops','coding','skills\devops\docker-management\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hermes-s6-container-supervision','skill:simplicio-runtime:hermes-s6-container-supervision:devops','coding','skills\devops\hermes-s6-container-supervision\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('kanban-orchestrator','skill:simplicio-runtime:kanban-orchestrator:devops','orchestration','skills\devops\kanban-orchestrator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('kanban-worker','skill:simplicio-runtime:kanban-worker:devops','coding','skills\devops\kanban-worker\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pinggy-tunnel','skill:simplicio-runtime:pinggy-tunnel:devops','coding','skills\devops\pinggy-tunnel\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('watchers','skill:simplicio-runtime:watchers:devops','coding','skills\devops\watchers\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('adversarial-ux-test','skill:simplicio-runtime:adversarial-ux-test:dogfood','coding','skills\dogfood\adversarial-ux-test\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('dogfood','skill:simplicio-runtime:dogfood:skills','coding','skills\dogfood\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('agentmail','skill:simplicio-runtime:agentmail:email','coding','skills\email\agentmail\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('himalaya','skill:simplicio-runtime:himalaya:email','coding','skills\email\himalaya\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('brainstorming','skill:simplicio-runtime:brainstorming:engineering','coding','skills\engineering\brainstorming\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('llm-verification','skill:simplicio-runtime:llm-verification:engineering','coding','skills\engineering\llm-verification\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('subagent-driven-development','skill:simplicio-runtime:subagent-driven-development:engineering','coding','skills\engineering\subagent-driven-development\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('systematic-debugging','skill:simplicio-runtime:systematic-debugging:engineering','coding','skills\engineering\systematic-debugging\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('test-driven-development','skill:simplicio-runtime:test-driven-development:engineering','coding','skills\engineering\test-driven-development\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('using-superpowers','skill:simplicio-runtime:using-superpowers:engineering','coding','skills\engineering\using-superpowers\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('verification-before-completion','skill:simplicio-runtime:verification-before-completion:engineering','coding','skills\engineering\verification-before-completion\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('writing-plans','skill:simplicio-runtime:writing-plans:engineering','coding','skills\engineering\writing-plans\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('everything-claude-code','skill:simplicio-runtime:everything-claude-code:skills','coding','skills\everything-claude-code\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('3-statement-model','skill:simplicio-runtime:3-statement-model:finance','coding','skills\finance\3-statement-model\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('comps-analysis','skill:simplicio-runtime:comps-analysis:finance','coding','skills\finance\comps-analysis\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('dcf-model','skill:simplicio-runtime:dcf-model:finance','coding','skills\finance\dcf-model\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('excel-author','skill:simplicio-runtime:excel-author:finance','coding','skills\finance\excel-author\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('lbo-model','skill:simplicio-runtime:lbo-model:finance','coding','skills\finance\lbo-model\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('merger-model','skill:simplicio-runtime:merger-model:finance','coding','skills\finance\merger-model\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pptx-author','skill:simplicio-runtime:pptx-author:finance','coding','skills\finance\pptx-author\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('stocks','skill:simplicio-runtime:stocks:finance','coding','skills\finance\stocks\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('minecraft-modpack-server','skill:simplicio-runtime:minecraft-modpack-server:gaming','coding','skills\gaming\minecraft-modpack-server\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pokemon-player','skill:simplicio-runtime:pokemon-player:gaming','coding','skills\gaming\pokemon-player\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('codebase-inspection','skill:simplicio-runtime:codebase-inspection:github','coding','skills\github\codebase-inspection\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('github-auth','skill:simplicio-runtime:github-auth:github','coding','skills\github\github-auth\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('github-code-review','skill:simplicio-runtime:github-code-review:github','coding','skills\github\github-code-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('github-issues','skill:simplicio-runtime:github-issues:github','coding','skills\github\github-issues\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('github-pr-workflow','skill:simplicio-runtime:github-pr-workflow:github','coding','skills\github\github-pr-workflow\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('github-repo-management','skill:simplicio-runtime:github-repo-management:github','coding','skills\github\github-repo-management\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('fitness-nutrition','skill:simplicio-runtime:fitness-nutrition:health','coding','skills\health\fitness-nutrition\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('neuroskill-bci','skill:simplicio-runtime:neuroskill-bci:health','video','skills\health\neuroskill-bci\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes','skill:simplicio-runtime:hyperframes:hyperframes','video','skills\hyperframes\hyperframes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-cli','skill:simplicio-runtime:hyperframes-cli:hyperframes','video','skills\hyperframes\hyperframes-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-media','skill:simplicio-runtime:hyperframes-media:hyperframes','video','skills\hyperframes\hyperframes-media\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hyperframes-registry','skill:simplicio-runtime:hyperframes-registry:hyperframes','video','skills\hyperframes\hyperframes-registry\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('remotion-to-hyperframes','skill:simplicio-runtime:remotion-to-hyperframes:hyperframes','video','skills\hyperframes\remotion-to-hyperframes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('website-to-hyperframes','skill:simplicio-runtime:website-to-hyperframes:hyperframes','video','skills\hyperframes\website-to-hyperframes\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('viral-product-strategist','skill:simplicio-runtime:viral-product-strategist:marketing-vendas','coding','skills\marketing-vendas\viral-product-strategist\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('fastmcp','skill:simplicio-runtime:fastmcp:mcp','coding','skills\mcp\fastmcp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('mcporter','skill:simplicio-runtime:mcporter:mcp','coding','skills\mcp\mcporter\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('gif-search','skill:simplicio-runtime:gif-search:media','coding','skills\media\gif-search\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('heartmula','skill:simplicio-runtime:heartmula:media','coding','skills\media\heartmula\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('songsee','skill:simplicio-runtime:songsee:media','coding','skills\media\songsee\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('youtube-content','skill:simplicio-runtime:youtube-content:media','video','skills\media\youtube-content\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('openclaw-migration','skill:simplicio-runtime:openclaw-migration:migration','coding','skills\migration\openclaw-migration\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('accelerate','skill:simplicio-runtime:accelerate:mlops','orchestration','skills\mlops\accelerate\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('chroma','skill:simplicio-runtime:chroma:mlops','orchestration','skills\mlops\chroma\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('clip','skill:simplicio-runtime:clip:mlops','content','skills\mlops\clip\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('lm-evaluation-harness','skill:simplicio-runtime:lm-evaluation-harness','orchestration','skills\mlops\evaluation\lm-evaluation-harness\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('weights-and-biases','skill:simplicio-runtime:weights-and-biases','orchestration','skills\mlops\evaluation\weights-and-biases\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('faiss','skill:simplicio-runtime:faiss:mlops','orchestration','skills\mlops\faiss\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('flash-attention','skill:simplicio-runtime:flash-attention:mlops','coding','skills\mlops\flash-attention\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('guidance','skill:simplicio-runtime:guidance:mlops','orchestration','skills\mlops\guidance\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('huggingface-hub','skill:simplicio-runtime:huggingface-hub:mlops','coding','skills\mlops\huggingface-hub\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('huggingface-tokenizers','skill:simplicio-runtime:huggingface-tokenizers:mlops','coding','skills\mlops\huggingface-tokenizers\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('llama-cpp','skill:simplicio-runtime:llama-cpp','orchestration','skills\mlops\inference\llama-cpp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('obliteratus','skill:simplicio-runtime:obliteratus:inference','coding','skills\mlops\inference\obliteratus\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('outlines','skill:simplicio-runtime:outlines','orchestration','skills\mlops\inference\outlines\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('vllm','skill:simplicio-runtime:vllm','orchestration','skills\mlops\inference\vllm\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('instructor','skill:simplicio-runtime:instructor:mlops','orchestration','skills\mlops\instructor\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('lambda-labs','skill:simplicio-runtime:lambda-labs:mlops','orchestration','skills\mlops\lambda-labs\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('llava','skill:simplicio-runtime:llava:mlops','coding','skills\mlops\llava\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('modal','skill:simplicio-runtime:modal:mlops','orchestration','skills\mlops\modal\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('audiocraft','skill:simplicio-runtime:audiocraft','orchestration','skills\mlops\models\audiocraft\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('segment-anything','skill:simplicio-runtime:segment-anything','orchestration','skills\mlops\models\segment-anything\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('nemo-curator','skill:simplicio-runtime:nemo-curator:mlops','video','skills\mlops\nemo-curator\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('obliteratus','skill:simplicio-runtime:obliteratus:mlops','coding','skills\mlops\obliteratus\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('peft','skill:simplicio-runtime:peft:mlops','orchestration','skills\mlops\peft\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pinecone','skill:simplicio-runtime:pinecone:mlops','orchestration','skills\mlops\pinecone\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pytorch-fsdp','skill:simplicio-runtime:pytorch-fsdp:mlops','orchestration','skills\mlops\pytorch-fsdp\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('pytorch-lightning','skill:simplicio-runtime:pytorch-lightning:mlops','orchestration','skills\mlops\pytorch-lightning\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('qdrant','skill:simplicio-runtime:qdrant:mlops','orchestration','skills\mlops\qdrant\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('dspy','skill:simplicio-runtime:dspy','orchestration','skills\mlops\research\dspy\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('saelens','skill:simplicio-runtime:saelens:mlops','orchestration','skills\mlops\saelens\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simpo','skill:simplicio-runtime:simpo:mlops','orchestration','skills\mlops\simpo\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('slime','skill:simplicio-runtime:slime:mlops','orchestration','skills\mlops\slime\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('stable-diffusion','skill:simplicio-runtime:stable-diffusion:mlops','orchestration','skills\mlops\stable-diffusion\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('tensorrt-llm','skill:simplicio-runtime:tensorrt-llm:mlops','orchestration','skills\mlops\tensorrt-llm\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('torchtitan','skill:simplicio-runtime:torchtitan:mlops','orchestration','skills\mlops\torchtitan\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('axolotl','skill:simplicio-runtime:axolotl','orchestration','skills\mlops\training\axolotl\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('trl-fine-tuning','skill:simplicio-runtime:trl-fine-tuning','orchestration','skills\mlops\training\trl-fine-tuning\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('unsloth','skill:simplicio-runtime:unsloth','orchestration','skills\mlops\training\unsloth\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('whisper','skill:simplicio-runtime:whisper:mlops','orchestration','skills\mlops\whisper\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('obsidian','skill:simplicio-runtime:obsidian:note-taking','content','skills\note-taking\obsidian\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('payments','skill:simplicio-runtime:payments:skills','coding','skills\payments\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('playwright-e2e','skill:simplicio-runtime:playwright-e2e:skills','coding','skills\playwright-e2e\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('airtable','skill:simplicio-runtime:airtable:productivity','coding','skills\productivity\airtable\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('canvas','skill:simplicio-runtime:canvas:productivity','coding','skills\productivity\canvas\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('google-workspace','skill:simplicio-runtime:google-workspace:productivity','coding','skills\productivity\google-workspace\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('here-now','skill:simplicio-runtime:here-now:productivity','coding','skills\productivity\here-now\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('maps','skill:simplicio-runtime:maps:productivity','coding','skills\productivity\maps\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('memento-flashcards','skill:simplicio-runtime:memento-flashcards:productivity','content','skills\productivity\memento-flashcards\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('nano-pdf','skill:simplicio-runtime:nano-pdf:productivity','coding','skills\productivity\nano-pdf\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('notion','skill:simplicio-runtime:notion:productivity','coding','skills\productivity\notion\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ocr-and-documents','skill:simplicio-runtime:ocr-and-documents:productivity','coding','skills\productivity\ocr-and-documents\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('powerpoint','skill:simplicio-runtime:powerpoint:productivity','coding','skills\productivity\powerpoint\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('shop-app','skill:simplicio-runtime:shop-app:productivity','coding','skills\productivity\shop-app\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('shopify','skill:simplicio-runtime:shopify:productivity','coding','skills\productivity\shopify\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('siyuan','skill:simplicio-runtime:siyuan:productivity','coding','skills\productivity\siyuan\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('teams-meeting-pipeline','skill:simplicio-runtime:teams-meeting-pipeline:productivity','coding','skills\productivity\teams-meeting-pipeline\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('telephony','skill:simplicio-runtime:telephony:productivity','coding','skills\productivity\telephony\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('ralph-loop','skill:simplicio-runtime:ralph-loop:skills','orchestration','skills\ralph-loop\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('godmode','skill:simplicio-runtime:godmode:red-teaming','coding','skills\red-teaming\godmode\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('arxiv','skill:simplicio-runtime:arxiv:research','coding','skills\research\arxiv\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('bioinformatics','skill:simplicio-runtime:bioinformatics:research','coding','skills\research\bioinformatics\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('blogwatcher','skill:simplicio-runtime:blogwatcher:research','coding','skills\research\blogwatcher\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('darwinian-evolver','skill:simplicio-runtime:darwinian-evolver:research','coding','skills\research\darwinian-evolver\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('domain-intel','skill:simplicio-runtime:domain-intel:research','coding','skills\research\domain-intel\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('drug-discovery','skill:simplicio-runtime:drug-discovery:research','coding','skills\research\drug-discovery\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('duckduckgo-search','skill:simplicio-runtime:duckduckgo-search:research','video','skills\research\duckduckgo-search\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('gitnexus-explorer','skill:simplicio-runtime:gitnexus-explorer:research','coding','skills\research\gitnexus-explorer\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('llm-wiki','skill:simplicio-runtime:llm-wiki:research','coding','skills\research\llm-wiki\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('osint-investigation','skill:simplicio-runtime:osint-investigation:research','coding','skills\research\osint-investigation\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('parallel-cli','skill:simplicio-runtime:parallel-cli:research','coding','skills\research\parallel-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('polymarket','skill:simplicio-runtime:polymarket:research','coding','skills\research\polymarket\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('qmd','skill:simplicio-runtime:qmd:research','coding','skills\research\qmd\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('research-paper-writing','skill:simplicio-runtime:research-paper-writing:research','orchestration','skills\research\research-paper-writing\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('scrapling','skill:simplicio-runtime:scrapling:research','coding','skills\research\scrapling\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('searxng-search','skill:simplicio-runtime:searxng-search:research','coding','skills\research\searxng-search\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('1password','skill:simplicio-runtime:1password:security','coding','skills\security\1password\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('godmode','skill:simplicio-runtime:godmode:security','coding','skills\security\godmode\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('oss-forensics','skill:simplicio-runtime:oss-forensics:security','coding','skills\security\oss-forensics\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('sherlock','skill:simplicio-runtime:sherlock:security','content','skills\security\sherlock\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('web-pentest','skill:simplicio-runtime:web-pentest:security','coding','skills\security\web-pentest\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('claude','skill:simplicio-runtime:claude:simplicio','coding','skills\simplicio\claude\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('rtk-cli','skill:simplicio-runtime:rtk-cli:simplicio','coding','skills\simplicio\rtk-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplicio-cli','skill:simplicio-runtime:simplicio-cli:simplicio','coding','skills\simplicio\simplicio-cli\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('contribute-catalog','skill:simplicio-runtime:contribute-catalog:skill-tooling','video','skills\skill-tooling\contribute-catalog\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('skill-opt','skill:simplicio-runtime:skill-opt:skill-tooling','coding','skills\skill-tooling\skill-opt\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('openhue','skill:simplicio-runtime:openhue:smart-home','coding','skills\smart-home\openhue\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('xurl','skill:simplicio-runtime:xurl:social-media','content','skills\social-media\xurl\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('code-wiki','skill:simplicio-runtime:code-wiki:software-development','coding','skills\software-development\code-wiki\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('hermes-agent-skill-authoring','skill:simplicio-runtime:hermes-agent-skill-authoring:software-development','coding','skills\software-development\hermes-agent-skill-authoring\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('node-inspect-debugger','skill:simplicio-runtime:node-inspect-debugger:software-development','coding','skills\software-development\node-inspect-debugger\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('plan','skill:simplicio-runtime:plan:software-development','coding','skills\software-development\plan\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('python-debugpy','skill:simplicio-runtime:python-debugpy:software-development','coding','skills\software-development\python-debugpy\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('requesting-code-review','skill:simplicio-runtime:requesting-code-review:software-development','coding','skills\software-development\requesting-code-review\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('rest-graphql-debug','skill:simplicio-runtime:rest-graphql-debug:software-development','coding','skills\software-development\rest-graphql-debug\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('simplify-code','skill:simplicio-runtime:simplify-code:software-development','coding','skills\software-development\simplify-code\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('spike','skill:simplicio-runtime:spike:software-development','coding','skills\software-development\spike\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('subagent-driven-development','skill:simplicio-runtime:subagent-driven-development:software-development','coding','skills\software-development\subagent-driven-development\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('systematic-debugging','skill:simplicio-runtime:systematic-debugging:software-development','coding','skills\software-development\systematic-debugging\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('test-driven-development','skill:simplicio-runtime:test-driven-development:software-development','coding','skills\software-development\test-driven-development\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('animejs','skill:simplicio-runtime:animejs:web-animation','video','skills\web-animation\animejs\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('css-animations','skill:simplicio-runtime:css-animations:web-animation','video','skills\web-animation\css-animations\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('gsap','skill:simplicio-runtime:gsap:web-animation','video','skills\web-animation\gsap\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('lottie','skill:simplicio-runtime:lottie:web-animation','video','skills\web-animation\lottie\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('tailwind','skill:simplicio-runtime:tailwind:web-animation','video','skills\web-animation\tailwind\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('three','skill:simplicio-runtime:three:web-animation','video','skills\web-animation\three\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('typegpu','skill:simplicio-runtime:typegpu:web-animation','video','skills\web-animation\typegpu\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('waapi','skill:simplicio-runtime:waapi:web-animation','video','skills\web-animation\waapi\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('page-agent','skill:simplicio-runtime:page-agent:web-development','coding','skills\web-development\page-agent\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('jira-task-runner','skill:simplicio-runtime:jira-task-runner:work-sources','coding','skills\work-sources\jira-task-runner\SKILL.md');
INSERT OR IGNORE INTO skills_registry(skill_name,stable_id,domain,artifact_path) VALUES('yuanbao','skill:simplicio-runtime:yuanbao:skills','coding','skills\yuanbao\SKILL.md');
COMMIT;
