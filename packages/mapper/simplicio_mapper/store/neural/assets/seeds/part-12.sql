INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1267-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1267-plan.md','doc: Epic #1267 — [Simplicio Mobile] Secure pairing via QR/device keys','# Epic #1267 — [Simplicio Mobile] Secure pairing via QR/device keys

## Current state

`src/pairing_command.rs` already implements:
- CLI challenge-response pairing (begin/verify flow)
- SHA-256 hash-based code verification with constant-time compare
- Device record persistence (`pairing-devices.json`)
- Pending challenge persistence with TTL (600s)
- Device revocation
- Token generation for paired devices

This covers roughly 30% of the acceptance criteria.

## Gap analysis

| Area | Status | Notes |
|------|--------|-------|
| CLI challenge-response | Done | pairing_command.rs |
| Device record persistence | Done | BTreeMap + JSON file |
| Revocation | Done | remove from devices map |
| Token expiry | Done | challenge TTL |
| QR code generation | Missing | Need QR payload schema + rendering |
| Asymmetric device keypairs | Missing | Ed25519 or similar |
| Scopes per device | Missing | Read-only, full, admin, etc. |
| last_seen tracking | Missing | Timestamp on each API call |
| Mobile app scaffold | Missing | apps/mobile does not exist |
| Mobile-to-desktop scan flow | Missing | E2E protocol |
| Desktop QR display | Missing | Terminal/GUI rendering |

## Sub-issues decomposition

### Sub-issue 1: QR payload schema and generation
**Files:** `src/pairing_command.rs`, new `src/qr_payload.rs`
**Scope:**
- Define QR payload JSON schema: `{ version, desktop_pubkey, challenge_nonce, endpoint, expires_at }`
- Generate QR code as UTF-8 block characters for terminal display
- Add `qrencode` or implement minimal QR encoding (prefer pure-Rust, no C deps)
- Unit tests for payload serialization round-trip

### Sub-issue 2: Asymmetric device keypairs
**Files:** `src/pairing_command.rs`, new `src/device_keys.rs`
**Scope:**
- Generate Ed25519 keypair per device on first pairing
- Store desktop keypair in `~/.simplicio-loop/device_key.json` (private) and embed pubkey in QR
- Mobile device sends its pubkey during verify step
- Replace symmetric token with signed challenge-response using keypairs
- Key rotation command

### Sub-issue 3: Device scopes model
**Files:** `src/pairing_command.rs`
**Scope:**
- Extend `DeviceRecord` with `scopes: Vec<String>` field
- Define scope vocabulary: `read`, `execute`, `admin`, `files.read`, `files.write`
- Scope validation on tool dispatch (integrate with tool_registry)
- CLI command to update scopes for a paired device
- Default scope assignment during pairing

### Sub-issue 4: last_seen tracking and device status
**Files:** `src/pairing_command.rs`
**Scope:**
- Add `last_seen: u64` and `ip_hint: Option<String>` to `DeviceRecord`
- Update last_seen on each authenticated request from device
- `list-devices` command shows last_seen, scope summary, status
- Auto-revoke devices not seen in configurable period (default 90 days)

### Sub-issue 5: Mobile app scaffold
**Files:** new `apps/mobile/` directory
**Scope:**
- Initialize mobile project (likely React Native or Flutter)
- QR scanner screen
- Keypair generation on mobile side
- Secure storage for device private key
- Pairing confirmation UI
- Basic authenticated command sending

### Sub-issue 6: End-to-end pairing protocol
**Files:** `src/pairing_command.rs`, `apps/mobile/`
**Scope:**
- Desktop shows QR containing: desktop pubkey + challenge nonce + local endpoint
- Mobile scans QR, generates its own keypair, signs the nonce with mobile privkey
- Mobile sends `{ mobile_pubkey, signed_nonce, device_name, requested_scopes }` to desktop endpoint
- Desktop verifies signature, persists device with scopes, returns signed ACK
- Both sides store each other''s pubkey for future authenticated communication
- Timeout and replay protection

## Suggested implementation order

1. Sub-issue 2 (keypairs) — foundational crypto layer
2. Sub-issue 3 (scopes) — extends device model
3. Sub-issue 4 (last_seen) — small, independent enhancement
4. Sub-issue 1 (QR generation) — depends on keypair schema
5. Sub-issue 6 (E2E protocol) — integrates all above
6. Sub-issue 5 (mobile app) — largest, depends on protocol being defined

## Dependencies

- `sha2` crate — already in use
- `ed25519-dalek` or `ring` — for asymmetric crypto (sub-issue 2)
- `qrcode` crate — for QR generation (sub-issue 1)
- Mobile framework choice blocks sub-issue 5','docs/issues/1267-plan.md','48a0adedd37db7f2e62fe92de39f8fbf618159b6289675fa385fb12902f656ae','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1268-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1268-plan.md','doc: Plan: Desktop Dispatch Gateway for Simplicio Mobile (#1268)','# Plan: Desktop Dispatch Gateway for Simplicio Mobile (#1268)

## Overview

Enable Simplicio Mobile clients to dispatch and monitor agent runs on the desktop runtime via a local gateway server. Currently, `dispatch` in `main.rs` is just an alias to `orchestrate_run`/`scheduler_tick` — there is no network-facing gateway, no device pairing, and no mobile app scaffold.

## Sub-issues

### 1. Gateway Server Module (`src/gateway_server.rs`)
- TCP/WebSocket listener on a configurable local port (default 9818).
- Accept JSON-RPC style messages over the connection.
- Route inbound requests to existing orchestration functions.
- Graceful shutdown on SIGINT / app exit.
- **No external crate beyond std + serde + serde_json** — use `std::net::TcpListener` + a minimal WebSocket handshake or plain JSON-over-TCP framing (length-prefix).

### 2. Device Pairing & Auth Protocol
- On first connection, gateway generates a 6-digit pairing code displayed in the TUI.
- Mobile sends the code; gateway returns a session token (random 256-bit, hex-encoded).
- Subsequent requests include the token in a header/field; gateway validates.
- Paired devices stored in `~/.simplicio-loop/paired_devices.json`.
- `simplicio unpair <device_id>` CLI command to revoke.

### 3. Structured Endpoints (JSON-RPC methods)
| Method | Description |
|---|---|
| `dispatch.run` | Start an agent run (maps to `orchestrate_run`) |
| `dispatch.status` | Return current agent status as JSON |
| `dispatch.evidence` | List/stream evidence records |
| `dispatch.savings` | Return savings summary |
| `dispatch.approve` | Respond to an approval gate |
| `dispatch.cancel` | Cancel a running agent |
| `dispatch.pause` | Pause a running agent |
| `dispatch.resume` | Resume a paused agent |

### 4. CLI: `simplicio dispatch status --json`
- Add `DispatchStatus` subcommand to the CLI parser in `main.rs`.
- Output JSON to stdout: `{ "running": bool, "agent": "...", "step": N, "elapsed_s": N }`.
- Useful for scripting and for the TUI to poll.

### 5. Event Streaming
- After `dispatch.run`, the mobile client can subscribe to a server-sent event stream.
- Gateway pushes step completions, evidence captures, approval requests, and errors.
- Framing: newline-delimited JSON over the same TCP connection.

### 6. Evidence Recording Bridge
- `dispatch.evidence` returns evidence already captured by the runtime.
- Add an endpoint to submit evidence from the mobile device (photo, voice memo) that the runtime stores alongside desktop evidence.

### 7. TUI Gateway Status Panel (`tui/src/gatewayContext.tsx`, `gatewayClient.ts`, `gatewayTypes.ts`)
- Show gateway listening status, paired devices, and active mobile sessions.
- `gatewayClient.ts`: TypeScript client for the gateway (used by TUI dev tools).
- `gatewayTypes.ts`: Shared type definitions for gateway messages.
- `gatewayContext.tsx`: React context providing gateway state to TUI components.

### 8. Mobile App Scaffold (`apps/mobile/`)
- React Native (Expo) project targeting iOS and Android.
- Screens: Pair, Dashboard, Run, Evidence, Approval.
- Communicates with the desktop gateway over LAN.
- MVP: pair + trigger run + view status + approve gates.

### 9. Multi-Agent Dispatch Schema
- `schemas/multi-agent-dispatch.schema.json`: JSON Schema for dispatch messages.
- Validates all inbound/outbound gateway messages.
- Used by both Rust (serde) and TypeScript (zod or manual) sides.

### 10. Integration Tests
- `tests/gateway_integration.rs`: spin up gateway, connect a mock client, run a dispatch cycle.
- Test pairing, run, status, cancel, evidence retrieval.
- Test invalid token rejection.
- Test concurrent mobile sessions.

## Suggested Implementation Order

1. Sub-issue 9 (schema) — defines the contract.
2. Sub-issue 1 (gateway server) — core networking.
3. Sub-issue 2 (pairing/auth) — security before endpoints.
4. Sub-issue 3 (endpoints) — business logic routing.
5. Sub-issue 4 (CLI status) — quick win, useful for debugging.
6. Sub-issue 5 (event streaming) — real-time updates.
7. Sub-issue 6 (evidence bridge) — mobile evidence capture.
8. Sub-issue 7 (TUI panel) — visibility into gateway state.
9. Sub-issue 8 (mobile app) — consumer of all the above.
10. Sub-issue 10 (integration tests) — end-to-end validation.

## Risks & Open Questions

- **Network discovery**: How does the mobile app find the desktop on the LAN? Options: mDNS, QR code with IP:port, manual entry.
- **NAT traversal**: If mobile is on a different network, a relay or tunnel is needed (out of scope for MVP).
- **Security**: Pairing code + session token is sufficient for LAN; consider TLS for production.
- **Concurrency**: Multiple mobile clients dispatching simultaneously — need queuing or rejection policy.','docs/issues/1268-plan.md','1ef133756dfae474594bd9651c696fafdff14172510ab4c2fafabfded67af020','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1269-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1269-plan.md','doc: Epic #1269: [Simplicio Mobile] LAN/WebSocket/cloud relay transport','# Epic #1269: [Simplicio Mobile] LAN/WebSocket/cloud relay transport

## Overview

This epic covers the full mobile-to-desktop communication layer for Simplicio Mobile.
It spans 6+ distinct concerns that must be decomposed into separate, sequentially deliverable sub-issues.

## Sub-issues

### 1. Transport decision document
**Goal:** Produce a design doc comparing transport options (raw TCP, WebSocket, gRPC, SSE) and recommending the primary protocol.
**Deliverable:** `docs/design/transport-decision.md`
**Dependencies:** None
**Effort:** S

### 2. Event stream schema design
**Goal:** Define the JSON message schema for all event types exchanged between mobile client and desktop agent (commands, responses, heartbeats, errors).
**Deliverable:** `docs/design/event-stream-schema.md` + JSON Schema files
**Dependencies:** Sub-issue 1
**Effort:** S

### 3. Transport architecture diagram
**Goal:** Visual diagram showing LAN discovery, WebSocket gateway, cloud relay, and push-notification fallback paths.
**Deliverable:** `docs/design/transport-diagram.svg` or `.excalidraw`
**Dependencies:** Sub-issues 1, 2
**Effort:** XS

### 4. LAN discovery module
**Goal:** Implement mDNS/DNS-SD based local network discovery so the mobile app can find the desktop agent automatically, plus a manual host:port fallback.
**Deliverable:** `src/transport/lan_discovery.rs`
**Dependencies:** Sub-issues 1, 2
**Effort:** M

### 5. WebSocket gateway endpoint
**Goal:** Add a WebSocket server endpoint to the desktop agent that accepts mobile connections, authenticates via shared secret or token, and streams events using the schema from sub-issue 2.
**Deliverable:** `src/transport/ws_gateway.rs`, `src/transport/mod.rs`
**Dependencies:** Sub-issues 2, 4
**Effort:** L

### 6. Cloud relay design and implementation
**Goal:** Design and implement an optional cloud relay for when LAN is unavailable (e.g., mobile on cellular). Relay forwards encrypted WebSocket frames between mobile and desktop.
**Deliverable:** `docs/design/cloud-relay.md`, `src/transport/cloud_relay.rs`
**Dependencies:** Sub-issues 2, 5
**Effort:** L

### 7. Push notification requirements document
**Goal:** Document push-notification fallback requirements (APNs/FCM) for waking the mobile app when the desktop agent has results but the WebSocket connection dropped.
**Deliverable:** `docs/design/push-notification-requirements.md`
**Dependencies:** Sub-issues 5, 6
**Effort:** S

### 8. Retry and failure UX
**Goal:** Define and implement retry logic, connection state machine, and user-facing error/status messages for all transport modes.
**Deliverable:** `src/transport/retry.rs`, UX copy doc
**Dependencies:** Sub-issues 5, 6, 7
**Effort:** M

## Suggested execution order

1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8

Sub-issues 1-3 (design artifacts) should be completed and reviewed before any implementation begins.
Sub-issues 4 and 7 can proceed in parallel once design is approved.

## Notes

- Existing transport code (`agent_runtime_helpers.rs`, `codex_transport.rs`) handles LLM API provider communication and is **not** related to mobile-to-desktop transport. New code should live in a separate `src/transport/` module.
- No `apps/mobile` directory exists yet; the mobile client is out of scope for this epic (tracked separately).
- Constraint: std + serde + serde_json only for core transport logic; WebSocket/mDNS crates TBD in sub-issue 1.','docs/issues/1269-plan.md','69c5fab84d4131a25883109e97fd89132264c745fb75ffead0904203c4eaf579','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1270-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1270-plan.md','doc: Epic #1270 — [Simplicio Mobile] Mobile task composer','# Epic #1270 — [Simplicio Mobile] Mobile task composer

## Overview
Build a React Native mobile app surface that lets users compose and dispatch tasks to the Simplicio runtime from a mobile device. Part of parent epic #1264.

## Dependencies
- #1244 — Desktop dispatch protocol
- #1247 — Workspace registry
- #1248 — Risk assessment engine
- #1249 — Execution mode definitions
- #1250 — Paired-desktop validation
- #1254 — Task schema definitions
- #1258 — Mobile auth flow

## Decomposition

### Phase 1 — Project scaffolding
1. **#1270-A**: Initialize React Native project under `apps/mobile/` with TypeScript, ESLint, and base navigation structure.
2. **#1270-B**: Set up CI pipeline for mobile builds (lint, type-check, unit tests).

### Phase 2 — Core UI components
3. **#1270-C**: Text input composer — multi-line text input with character count, submit button, and keyboard-aware scroll.
4. **#1270-D**: Repository/workspace selector — dropdown or modal list backed by workspace registry (#1247).
5. **#1270-E**: Execution mode picker — radio/segmented control for available modes (#1249).
6. **#1270-F**: Risk preview panel — read-only summary of risk assessment before dispatch (#1248).

### Phase 3 — Dispatch integration
7. **#1270-G**: Define `MobileDispatchRequest` schema (JSON) aligned with task schema (#1254) and desktop dispatch protocol (#1244).
8. **#1270-H**: Implement dispatch client — sends composed task to runtime, handles success/error responses.
9. **#1270-I**: Paired-desktop validation flow — confirm desktop is online and authorized before dispatch (#1250).

### Phase 4 — Polish & testing
10. **#1270-J**: End-to-end tests for compose → preview → dispatch flow.
11. **#1270-K**: Accessibility pass (screen reader labels, contrast, touch targets).
12. **#1270-L**: Error states and offline handling.

## Acceptance criteria
- User can type a task, select repo/workspace, pick execution mode, preview risk, and dispatch.
- Dispatch is blocked if paired desktop is unavailable.
- All components have unit tests; happy-path e2e test passes.','docs/issues/1270-plan.md','91be05425ce8655787c1f81779c96a20b31045fe59f23cf6e13531246ca3e13c','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1271-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1271-plan.md','doc: Epic #1271 — [Simplicio Mobile] Stream run timeline to mobile','# Epic #1271 — [Simplicio Mobile] Stream run timeline to mobile

Parent epic: #1264

## Overview

Stream desktop runtime run events to a mobile app, displaying a timeline with 9 distinct run states, log redaction, evidence artifact rendering, diff summaries, and cancel/approve actions.

## Sub-issues

### 1. Event Protocol & Schema (`event-protocol`)
- Define `RunEvent` enum with 9 states: `Queued`, `Starting`, `Running`, `WaitingApproval`, `Approved`, `Cancelled`, `Failed`, `Succeeded`, `TimedOut`
- Serde-serializable schema in a new `src/mobile_event_schema.rs`
- Include timestamp, run_id, agent_id, event payload (logs, diffs, artifacts)
- Target files: `src/mobile_event_schema.rs` (new)

### 2. Run Event Emission from Desktop Runtime (`event-emission`)
- Add `RunEventEmitter` trait in `src/run_event_emitter.rs`
- Integrate emission hooks into `src/main.rs`, `src/codex_transport.rs`, `src/delivery_certificate.rs`
- Emit events at each state transition in the existing run loop
- Target files: `src/run_event_emitter.rs` (new), `src/main.rs`, `src/codex_transport.rs`, `src/delivery_certificate.rs`

### 3. Mobile Transport Layer (`mobile-transport`)
- WebSocket or SSE transport for pushing events to mobile clients
- New `src/mobile_transport.rs` with connection management, reconnection, auth token validation
- Event queue with backpressure for offline mobile clients
- Target files: `src/mobile_transport.rs` (new)

### 4. Mobile Event Cache/Store (`mobile-cache`)
- Local event store on the mobile side (SQLite or in-memory ring buffer)
- Deduplication by `(run_id, sequence_number)`
- Retention policy (e.g., last 100 runs or 7 days)
- Target files: `apps/mobile/src/event_store.rs` (new)

### 5. Log Redaction (`log-redaction`)
- Scrub secrets, tokens, API keys, and PII from log payloads before transport
- Extend `src/stream_scrubber.rs` with mobile-specific redaction rules
- Configurable redaction patterns via policy
- Target files: `src/stream_scrubber.rs`, `src/mobile_event_schema.rs`

### 6. Timeline UI Component (`timeline-ui`)
- Mobile timeline view rendering 9 run states with distinct icons/colors
- Real-time updates via the mobile transport subscription
- Expandable log viewer per run step
- Target files: `apps/mobile/src/timeline.rs` (new)

### 7. Evidence Artifact Renderer (`evidence-renderer`)
- Render delivery certificates, screenshots, test results inline in timeline
- Support image, text, and structured JSON artifacts
- Leverage existing `src/delivery_certificate.rs` schema
- Target files: `apps/mobile/src/evidence_renderer.rs` (new)

### 8. Diff Summary Display (`diff-summary`)
- Compact diff view showing files changed, insertions, deletions
- Collapsible per-file diff with syntax highlighting
- Target files: `apps/mobile/src/diff_summary.rs` (new)

### 9. Cancel Action (`cancel-action`)
- Mobile button to cancel a running agent run
- Send cancel command back through mobile transport to desktop runtime
- Integrate with existing `src/conversation_control.rs` cancellation logic
- Target files: `apps/mobile/src/actions.rs` (new), `src/mobile_transport.rs`, `src/conversation_control.rs`

### 10. Approve Action (`approve-action`)
- Approve pending write/destructive actions from mobile
- Send approval response through mobile transport
- Integrate with `src/htool_approval.rs` and `src/htool_write_approval.rs`
- Target files: `apps/mobile/src/actions.rs`, `src/mobile_transport.rs`, `src/htool_approval.rs`

### 11. Mobile App Scaffold (`mobile-scaffold`)
- Create `apps/mobile/` directory structure with Cargo workspace member
- Basic app entry point, auth flow, push notification registration
- Target files: `apps/mobile/Cargo.toml` (new), `apps/mobile/src/main.rs` (new)

### 12. Fixture & UI Tests (`tests`)
- Event schema round-trip tests (serialize/deserialize all 9 states)
- Mock transport tests with synthetic event streams
- Redaction tests ensuring no secrets leak
- Timeline rendering snapshot tests
- Cancel/approve integration tests
- Target files: `tests/mobile_event_tests.rs` (new), `tests/mobile_transport_tests.rs` (new)

## Dependency Graph

```
event-protocol
  ├── event-emission
  ├── log-redaction
  └── mobile-transport
        ├── mobile-cache
        ├── cancel-action
        └── approve-action
mobile-scaffold
  ├── timeline-ui
  ├── evidence-renderer
  └── diff-summary
tests (depends on all above)
```

## Implementation Order

1. `event-protocol` — foundational schema
2. `event-emission` + `log-redaction` — can be parallel
3. `mobile-transport` — depends on schema
4. `mobile-scaffold` — can start in parallel with #2-3
5. `mobile-cache` — depends on transport + scaffold
6. `timeline-ui` + `evidence-renderer` + `diff-summary` — depends on scaffold + schema
7. `cancel-action` + `approve-action` — depends on transport + scaffold
8. `tests` — continuous, but full suite after all above','docs/issues/1271-plan.md','161a3a244b638333359183667d1887128ae1ac30bd6bb452d74cf3ed8e9454de','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1272-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1272-plan.md','doc: Epic #1272: [Simplicio Mobile] Approval Center for Actions','# Epic #1272: [Simplicio Mobile] Approval Center for Actions

## Overview

Create a mobile-friendly approval center that lets users review, approve, or reject
tool-execution requests from Simplicio agents. The backend approval infrastructure
exists in `htool_approval.rs` and `acp_adapter/` but lacks a mobile surface,
push notification integration, and relay API.

## Sub-tasks

### Phase 1 — Backend API for Approval Relay

**1.1 Approval REST API endpoints** (`src/approval_api.rs`)
- `GET /approvals/pending` — list pending approval requests for the authenticated user
- `GET /approvals/:id` — detail view (command, risk level, evidence, TTL)
- `POST /approvals/:id/decide` — submit decision (approve-once, approve-session, reject, manual-fallback)
- Wire into existing `htool_approval.rs` approval queue
- Add serializable DTOs with serde for request/response

**1.2 Push notification dispatch** (`src/push_notify.rs`)
- Abstract push provider trait (FCM / APNs)
- On new approval request, dispatch push with summary + deeplink
- TTL-aware: do not send push if request already expired
- Record delivery status for audit

**1.3 Approval TTL enforcement** (`src/htool_approval.rs` changes)
- Background task to expire stale approvals
- Return `expired` status on decide attempts past TTL
- Emit event on expiry for evidence log

### Phase 2 — Mobile App Scaffolding

**2.1 Project setup**
- Create `mobile/` directory with React Native (or chosen framework) scaffold
- Auth integration (token-based, reuse existing auth)
- Deep link registration for approval notifications

**2.2 Approval inbox screen**
- List of pending approvals with risk-level badge (low/medium/high/critical)
- Sort by TTL remaining (urgent first)
- Pull-to-refresh + real-time updates via WebSocket or polling
- Empty state when no pending approvals

**2.3 Approval detail screen**
- Command preview (tool name, arguments, truncated payload)
- Risk level indicator with explanation
- Evidence preview (context that triggered the request)
- Four action buttons: Approve Once, Approve Session, Reject, Manual Fallback
- Confirmation dialog for high/critical risk actions

**2.4 Push notification handling**
- Register device token on login
- Handle foreground + background notifications
- Tap notification -> navigate to approval detail

### Phase 3 — Evidence and Audit

**3.1 Decision evidence recording** (`src/acp_adapter/`)
- Record: who decided, when, which device, decision type, TTL remaining at decision time
- Store in append-only audit log
- Expose `GET /approvals/:id/evidence` for review

**3.2 Session-scoped approvals**
- Track approve-session grants per (user, tool, session)
- Auto-expire session grants on session end or configurable timeout
- Show active session grants in mobile UI

### Phase 4 — Integration and Hardening

**4.1 End-to-end integration tests**
- Simulated approval flow: request -> push -> decide -> tool proceeds
- TTL expiry flow
- Session approval reuse flow

**4.2 Rate limiting and abuse prevention**
- Rate limit on decide endpoint
- Prevent replay of decisions
- Validate request ownership

**4.3 Offline resilience**
- Queue decisions made offline, sync when connected
- Show stale/expired indicator for approvals fetched while offline

## Dependencies

- Existing: `htool_approval.rs`, `capability_broker.rs`, `acp_adapter/permissions_approval.rs`, `acp_adapter/edit_approval.rs`
- New: push notification service credentials (FCM/APNs), mobile build toolchain

## Estimated effort

- Phase 1: 3-5 days (Rust backend)
- Phase 2: 5-8 days (mobile app)
- Phase 3: 2-3 days (audit/evidence)
- Phase 4: 2-3 days (testing/hardening)
- Total: ~12-19 days','docs/issues/1272-plan.md','41658646f89f8e87c5b05a341f7f8a3e3c6704fc688f69fd03091fb6d9ba9b47','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1273-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1273-plan.md','doc: Plan: #1273 — Mobile Token Savings and ROI Dashboard','# Plan: #1273 — Mobile Token Savings and ROI Dashboard

## Overview

Epic to build a mobile companion app that surfaces token savings, ROI metrics, and upsell opportunities from the existing desktop Simplicio runtime. The backend partially exists (`cost_ledger.rs`, `savings-report.schema.json`) but the entire mobile layer must be built from scratch.

## Dependencies

Desktop issues that must land first (or in parallel):

- #1244 — Cost ledger persistence
- #1247 — Savings report schema finalization
- #1248 — Per-model cost tracking
- #1249 — Per-repo cost breakdown
- #1250 — Weekly savings aggregation
- #1254 — Savings hook integration
- #1258 — Pro tier upsell metadata

## Decomposition

### Sub-issue 1: Savings Report API endpoint

**Scope:** Expose an HTTP endpoint (or local IPC) that returns the savings report JSON conforming to `savings-report.schema.json`.

- Read from `cost_ledger.rs` aggregated data
- Support query params: `period=today|week|month`, `group_by=computer|repo|model`
- Return JSON matching the existing schema
- No `.unwrap()` — proper error handling with `Result`

**Files:** `src/htool_savings_api.rs`, `src/main.rs` (mod + route), `src/tool_registry.rs`

### Sub-issue 2: Mobile app scaffold (apps/mobile)

**Scope:** Create the React Native (or similar) project skeleton under `apps/mobile/`.

- Project init with navigation, theming, auth token storage
- Connect to savings API endpoint
- Offline-first data caching

**Files:** `apps/mobile/` (new directory tree)

### Sub-issue 3: Dashboard UI — today/week/month views

**Scope:** Build the main dashboard screen with three time-period tabs.

- Summary cards: total tokens saved, estimated cost saved (USD), ROI percentage
- Sparkline or bar chart for trend visualization
- Pull-to-refresh

**Files:** `apps/mobile/src/screens/Dashboard.tsx`, `apps/mobile/src/components/SavingsCard.tsx`

### Sub-issue 4: Breakdown views (computer / repo / model)

**Scope:** Drill-down screens showing savings grouped by dimension.

- Sortable list with per-item savings
- Tap-through to evidence (links back to desktop session logs)

**Files:** `apps/mobile/src/screens/BreakdownByComputer.tsx`, `BreakdownByRepo.tsx`, `BreakdownByModel.tsx`

### Sub-issue 5: Weekly push notification summary

**Scope:** Backend scheduled job + mobile push integration.

- Rust-side: generate weekly summary payload via `savings-line.sh` hook or cron
- Mobile-side: register for push notifications, render rich notification with savings highlight

**Files:** `src/push_summary.rs`, `apps/mobile/src/services/notifications.ts`

### Sub-issue 6: Pro upsell cards

**Scope:** Display contextual upsell cards when free-tier limits are approached.

- Read upsell metadata from #1258
- Show cards inline in dashboard with CTA
- Dismiss/snooze logic with local persistence

**Files:** `apps/mobile/src/components/UpsellCard.tsx`, `apps/mobile/src/services/upsell.ts`

## Suggested implementation order

1. Sub-issue 1 (API) — unblocks all mobile work
2. Sub-issue 2 (scaffold) — parallel with 1 using mock data
3. Sub-issue 3 (dashboard) — core feature
4. Sub-issue 4 (breakdowns) — extends dashboard
5. Sub-issue 6 (upsell) — can land independently
6. Sub-issue 5 (push) — most complex, land last

## Estimated effort

- Sub-issues 1-2: ~2 days each
- Sub-issues 3-4: ~3 days each
- Sub-issues 5-6: ~2 days each
- Total: ~14 days (one developer)','docs/issues/1273-plan.md','d341fb12d084a0dfa0fc3bd2cf75d9d587f52bc8d06be3ee14cc18afa48df79c','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1274-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1274-plan.md','doc: Epic Plan: #1274 — [Simplicio Mobile] Mirror Free/Pro/Team entitlements','# Epic Plan: #1274 — [Simplicio Mobile] Mirror Free/Pro/Team entitlements

## Context

The desktop entitlement system exists (`schemas/entitlement.schema.json`, `site/api/entitlement.php`, `site/api/entitlement-public.php`) but there is no mobile consumer code. The `apps/mobile` directory does not exist yet. This epic builds an entire mobile entitlement surface.

## Sub-tasks

### 1. Shared Entitlement Model (`apps/shared/entitlement_model.ts`)
- Create a TypeScript model mirroring `entitlement.schema.json` (tiers: `free`, `pro`, `team`; phases: `free`, `paid`, `trial`).
- Include status types: `active`, `trial`, `expired`, `grace_period`.
- Export helper functions: `canAccessModule(tier, module)`, `isTrialExpired(entitlement)`, `daysRemaining(entitlement)`.

### 2. Mobile Entitlement API Client (`apps/mobile/services/entitlement_service.ts`)
- Fetch entitlement from `site/api/entitlement-public.php`.
- Cache locally with TTL (e.g., 1 hour).
- Implement refresh-on-resume and periodic background refresh.
- Handle offline gracefully (use cached entitlement).

### 3. Module Catalog UI (`apps/mobile/screens/module_catalog.ts`)
- List all available modules with their required tier.
- Show lock/unlock state based on current entitlement.
- Display upgrade CTA for locked modules.

### 4. Dispatch Gating (`apps/mobile/services/dispatch_gate.ts`)
- Before dispatching any tool/module, check entitlement tier.
- If tier insufficient, block dispatch and show upgrade prompt.
- Log gated attempts for analytics.

### 5. Checkout/Portal Integration (`apps/mobile/services/checkout.ts`)
- Deep-link to Stripe checkout for upgrades (Free -> Pro, Pro -> Team).
- Deep-link to Stripe customer portal for plan management.
- Handle post-checkout entitlement refresh.

### 6. Trial/Expired State Rendering (`apps/mobile/components/entitlement_banner.ts`)
- Show trial countdown banner when `current_phase === "trial"`.
- Show expired/grace-period banner with upgrade CTA.
- Show active plan badge in settings/profile.

### 7. Entitlement Refresh Flow (`apps/mobile/services/entitlement_refresh.ts`)
- On app resume: re-fetch entitlement if cache expired.
- On checkout return: force refresh.
- On push notification (subscription change): force refresh.
- Emit state-change events for UI reactivity.

### 8. Secret Scan & Security Review
- Ensure no Stripe keys or secrets are embedded in mobile bundle.
- Validate that `entitlement-public.php` (public endpoint) does not leak sensitive subscription data.
- Review CORS/auth on entitlement endpoints for mobile origins.

### 9. Fixture Tests
- Unit tests for `canAccessModule` across all tier combinations.
- Unit tests for trial expiry logic.
- Integration test mocking API responses (active, trial, expired, offline).
- Snapshot tests for banner/catalog UI states.

## Dependency Order

```
1 (shared model) --> 2 (API client) --> 4 (dispatch gate)
                                    --> 3 (catalog UI)
                                    --> 6 (banners)
                 --> 5 (checkout) --> 7 (refresh flow)
8 (security) — parallel
9 (tests) — after 1-7
```

## Estimated Effort

| Sub-task | Estimate |
|----------|----------|
| 1. Shared model | S |
| 2. API client | M |
| 3. Catalog UI | M |
| 4. Dispatch gate | S |
| 5. Checkout integration | M |
| 6. State banners | S |
| 7. Refresh flow | M |
| 8. Security review | S |
| 9. Tests | M |','docs/issues/1274-plan.md','5d52264ba0870b3ff0f0d6a3bc186d8988c8a1f336bdc315c8e85a15f3c80e9a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1275-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1275-plan.md','doc: Epic #1275 — [Simplicio Mobile] BYOK/provider setup for mobile','# Epic #1275 — [Simplicio Mobile] BYOK/provider setup for mobile

Parent epic: #1264 (Simplicio Mobile)
Related desktop issues: #1244, #1247-1250, #1254, #1258

## Context

The desktop runtime already has provider management in `src/model_command.rs`:
- `show_provider_status()` — displays provider config status
- `is_api_key_configured()` — checks if a key exists for a provider
- `load_api_key()` / `save_api_key()` — keychain-backed key storage
- `run_post_selection_flow()` — guides user through provider setup
- `ProviderEntry` — static registry of supported providers

None of this is exposed as a queryable endpoint or adapted for mobile consumption.
The mobile app directory (`apps/mobile/`) does not exist yet.

## Sub-issues

### 1275-A: Provider status API endpoint
**Scope:** Expose provider configuration state as a JSON-serializable struct that can be queried over the phone-to-desktop dispatch channel.

- Create `src/htool_provider_status.rs` implementing a `provider_status` tool
- Input: optional `provider_id` filter
- Output: for each provider — `id`, `label`, `description`, `has_key: bool`, `is_active: bool`, `requires_byok: bool`
- Reuse `model_command::is_api_key_configured()` and `PROVIDER_ENTRIES`
- Register in `tool_registry.rs`
- No secrets in output — only booleans indicating configured/not

### 1275-B: Secret redaction layer
**Scope:** Guarantee that no API key material ever crosses the desktop-to-mobile boundary.

- Create `src/redact.rs` with `redact_value(key: &str, value: &str) -> String`
- Pattern: if key contains `key`, `token`, `secret`, `password` — return `"***configured***"` or `"(not set)"`
- Unit tests with known dangerous field names
- Integrate into provider status output and any future mobile-facing responses
- Audit `load_api_key` and `save_api_key` to ensure they never serialize raw keys into tool output

### 1275-C: Phone-to-desktop dispatch protocol for provider queries
**Scope:** Define the message format for mobile-to-desktop provider management requests.

- Extend `src/dispatch.rs` (or create if needed) with message types:
  - `ProviderListRequest` / `ProviderListResponse`
  - `ProviderSetupRequest { provider_id }` / `ProviderSetupResponse { deep_link_url, instructions }`
  - `SkillsRankRequest { provider_id }` / `SkillsRankResponse { skills: Vec<SkillRanking> }`
- JSON-over-WebSocket or JSON-over-local-HTTP (aligned with existing dispatch infra)
- All responses pass through redaction layer (1275-B)

### 1275-D: Mobile app scaffold
**Scope:** Create the `apps/mobile/` directory with a minimal cross-platform mobile shell.

- Choose framework (likely React Native or Flutter, aligned with team decision)
- Scaffold with: provider list screen, setup guidance screen, skills ranking screen
- Connect to desktop dispatch endpoint (1275-C)
- No secret input fields on mobile — mobile only shows status and links to desktop

### 1275-E: BYOK setup guidance UI (mobile)
**Scope:** Mobile screen that shows provider setup state and guides the user.

- List all providers with status badges (configured / not configured / active)
- For unconfigured providers: show setup instructions (text) + deep-link button to desktop
- Never render API key input fields on mobile
- Pull data from provider status endpoint (1275-A) via dispatch (1275-C)

### 1275-F: Deep-link from mobile to desktop setup
**Scope:** Allow mobile to open the desktop provider setup flow for a specific provider.

- Define URI scheme: `simplicio://setup/provider/{provider_id}`
- Desktop registers handler that calls `run_post_selection_flow(provider_id, current_model)`
- Mobile generates the deep-link and opens it (via QR code or direct link if on same network)
- Fallback: show manual instructions if desktop is unreachable

### 1275-G: Skills ranking mobile rendering
**Scope:** Show which skills are available/ranked for the active provider on mobile.

- Query desktop for skills ranking via dispatch (1275-C)
- Display skills sorted by compatibility with current provider/model
- Show capability indicators (available / degraded / unavailable)
- Pull from existing skills registry on desktop side

## Dependency graph

```
1275-B (redaction) ─┐
                    ├─> 1275-A (provider status endpoint)
                    │         │
                    │         ├─> 1275-C (dispatch protocol)
                    │         │         │
                    │         │         ├─> 1275-E (BYOK guidance UI)
                    │         │         ├─> 1275-F (deep-link)
                    │         │         └─> 1275-G (skills ranking)
                    │         │
                    └─────────┴─> 1275-D (mobile scaffold)
```

## Implementation order

1. **1275-B** — redaction layer (no external deps, enables safe output)
2. **1275-A** — provider status endpoint (depends on B)
3. **1275-C** — dispatch protocol (depends on A)
4. **1275-D** — mobile scaffold (can start in parallel with C)
5. **1275-E, 1275-F, 1275-G** — mobile features (depend on C and D)','docs/issues/1275-plan.md','ece566d1ae7b50a9774f30414ea77acc09ec29990a2778960125a3b4de54ad42','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1276-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1276-plan.md','doc: Epic #1276 — [Simplicio Mobile] Workspace/repo selector and context map','# Epic #1276 — [Simplicio Mobile] Workspace/repo selector and context map

Parent epic: #1264

## Overview

Mobile module for workspace discovery, repository selection, runtime context map preview, and dirty/blocked state display. Requires new `apps/mobile` scaffold, schema definitions, compression endpoint, and desktop-mobile dispatch pairing.

## Sub-issues

### 1. Workspace list schema definition
- Define `WorkspaceListEntry` schema (id, name, path, last_accessed, repo_count, status).
- Add to `.simplicio-loop/runtime-resource-map.json` under a new `workspaces` key.
- Output: JSON Schema + Rust types in `src/schema/workspace.rs`.

### 2. Mobile app scaffold (`apps/mobile`)
- Create `apps/mobile/` directory structure (Cargo workspace member or wasm target).
- Minimal entry point that can render workspace list.
- Shared types crate between desktop and mobile.

### 3. Repo selector component
- List repos within a selected workspace with mock data fixture.
- Display per-repo metadata: name, branch, last commit, dirty flag, blocked flag.
- Filter/search support.

### 4. Runtime map compression endpoint
- New tool `simplicio_map --compressed` or dedicated `simplicio_map_preview` tool.
- Compresses `runtime-resource-map.json` for mobile bandwidth (strip large fields, summarize counts).
- Expose via tool registry in `tool_registry.rs`.

### 5. Dispatch identity integration
- Pair mobile device with desktop session via shared dispatch identity token.
- Desktop generates pairing code; mobile scans/enters it.
- Shared state sync for active workspace and repo selection.

### 6. Dirty/blocked repo state display
- Detect uncommitted changes (dirty) and lock conflicts (blocked) per repo.
- Surface in both repo selector list and context map preview.
- Color-coded status indicators.

### 7. UI tests and fixtures
- Mock workspace/repo data fixtures in `tests/fixtures/`.
- Unit tests for schema serialization.
- Integration tests for compression endpoint.
- Snapshot tests for repo selector rendering.

## Dependencies

- #1264 (parent epic — mobile architecture decisions)
- #1244–#1258 (related desktop issues for dispatch and map features)

## Acceptance criteria

- [ ] `WorkspaceListEntry` schema defined and validated
- [ ] `apps/mobile` scaffold compiles
- [ ] Repo selector renders mock data
- [ ] Compressed runtime map is <25% of full map size
- [ ] Dispatch pairing flow works end-to-end (desktop + mobile)
- [ ] Dirty/blocked states visible in repo selector
- [ ] All tests pass','docs/issues/1276-plan.md','ff3496dbfdae622d92143bdaaf2da0c55b018f07ca7adc419e9bd6dad9824244','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1277-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1277-plan.md','doc: Epic #1277: Simplicio Mobile - Push Notifications, Offline Queue, Retry','# Epic #1277: Simplicio Mobile - Push Notifications, Offline Queue, Retry

Parent epic: #1264

## Overview

Scaffold a mobile companion for Simplicio Runtime with push notifications, offline task queuing, and visible retry/backoff. The mobile app surfaces approval requests, task completions, failures, and blocked states. Users can queue safe draft actions offline that sync when connectivity returns. Expired approvals are never executed.

## Sub-issues

### 1. Mobile App Scaffold (React Native / Expo)
- Initialize Expo project under `apps/mobile/`
- Navigation: Home (dashboard), Notifications, Queue, Settings
- Auth flow reusing existing Simplicio credentials
- Shared types from `schemas/` directory
- **Depends on:** nothing

### 2. Push Notification Service Integration
- Firebase Cloud Messaging (Android) + APNs (iOS) via Expo Notifications
- Server-side module in `src/plugins/platforms/push/` (Rust) that dispatches notifications
- Notification payload schema in `schemas/push_notification.schema.json`
- Registration endpoint for device tokens
- Reuse design patterns from existing `ntfy` plugin (`plugins/platforms/ntfy/`)
- **Depends on:** Sub-issue 1

### 3. Notification Categories and Routing
- Define four categories: `approval`, `completion`, `failure`, `blocked`
- Category-specific icons, sounds, and priority levels
- User preferences for per-category mute/snooze
- Deep-link from notification tap to relevant task detail
- Schema: `schemas/notification_category.schema.json`
- **Depends on:** Sub-issue 2

### 4. Offline Queue with Safe-Drafts-Only Policy
- Local SQLite queue on device for actions created while offline
- Only "safe draft" actions (no destructive ops) are enqueueable offline
- Queue entries: `{ id, action, payload, created_at, status, retry_count }`
- Sync engine that replays queue on reconnect, respecting order
- Conflict resolution: server wins, user notified of conflicts
- **Depends on:** Sub-issue 1

### 5. Retry / Backoff with UI Visibility
- Exponential backoff with jitter (reuse patterns from `agent/retry_utils.py` and `src/retry_utils.rs`)
- Mobile UI shows: current retry attempt, next retry time, manual retry button
- Max retries configurable per action type
- Schema: extend `schemas/retry.schema.json` with mobile-specific fields
- **Depends on:** Sub-issues 2, 4

### 6. Expired Approval Safety Logic
- Approvals carry a `valid_until` timestamp
- Mobile client checks expiry before allowing user to approve
- Server rejects expired approvals even if client sends them (defense in depth)
- UI shows clear "expired" badge on stale approval notifications
- **Depends on:** Sub-issue 3

### 7. Per-Platform Background Refresh Documentation
- iOS: Background App Refresh, Silent Push constraints
- Android: WorkManager, Doze mode, battery optimization
- Document in `docs/mobile-background-refresh.md`
- **Depends on:** Sub-issues 2, 4

## Existing Code References

| File | Relevance |
|------|-----------|
| `apps/desktop/src/lib/notifications.ts` | Desktop notification patterns (not directly reusable) |
| `plugins/platforms/ntfy/` | Push plugin design reference |
| `agent/retry_utils.py` | Python retry/backoff logic |
| `src/retry_utils.rs` | Rust retry/backoff logic |
| `schemas/retry.schema.json` | Retry configuration schema |

## Dependency Graph

```
Sub-1 (Scaffold)
  |-- Sub-2 (Push Integration)
  |     |-- Sub-3 (Categories)
  |     |     |-- Sub-6 (Expired Approvals)
  |     |-- Sub-5 (Retry UI) --depends-also-on--> Sub-4
  |-- Sub-4 (Offline Queue)
  |-- Sub-7 (Background Refresh Docs) --depends-on--> Sub-2, Sub-4
```

## Priority Order

1. Sub-issue 1 (Scaffold) - unblocks everything
2. Sub-issues 2 + 4 in parallel (Push + Offline Queue)
3. Sub-issues 3 + 5 in parallel (Categories + Retry UI)
4. Sub-issue 6 (Expired Approvals)
5. Sub-issue 7 (Docs)','docs/issues/1277-plan.md','04bd4e3842218a9995fa645ff0c1740e136735ee4212ede8270ee81a4c77d269','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1278-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1278-plan.md','doc: Plan: #1278 — Security/Privacy Model Phone-to-Computer','# Plan: #1278 — Security/Privacy Model Phone-to-Computer

## Context

This epic covers the end-to-end security and privacy model for the Simplicio Mobile
companion app communicating with the desktop runtime. The mobile app (`apps/mobile/`)
does not exist yet, but several server-side building blocks are already in place:

- **Pairing with revocation** — `src/pairing_command.rs` (challenge-response, device records, TTL)
- **Approval system** — `src/htool_approval.rs` (dangerous-command detection, per-session approval state)
- **Action gate risk classification** — `src/action_gate.rs` (risk levels, hardline blocklist, mode-based gating)

## Sub-issues (11 workstreams)

### 1. Threat Model Document
**Files:** `docs/security/threat-model.md` (new)
**Scope:** Create a formal threat model covering the phone-to-computer channel: asset
inventory, trust boundaries, attack surface (local network, relay, BLE), STRIDE
analysis, and mitigations mapped to the other workstreams below.
**Depends on:** None (should be done first to guide the rest).

### 2. Biometric Gate Strategy
**Files:** `apps/mobile/` (new — platform-specific), `src/security_command.rs` (new)
**Scope:** Define how biometric authentication (Face ID, fingerprint, device PIN
fallback) gates sensitive operations on the phone side. The runtime needs a
`security_command.rs` that accepts a biometric-verification token from the mobile app
and validates it before allowing high-risk commands.
**Depends on:** #1 (threat model identifies which operations require biometric gate).

### 3. Transport Encryption
**Files:** `src/gateway/` (extend), `src/pairing_command.rs` (extend)
**Scope:** Ensure all phone-to-computer traffic uses TLS 1.3 (local network) or
end-to-end encryption over relay. Derive session keys from the pairing secret. Add
certificate pinning on the mobile side.
**Depends on:** #1.

### 4. Session Scopes
**Files:** `src/htool_approval.rs` (extend), `src/security_command.rs` (new)
**Scope:** Implement scoped sessions so that a mobile connection only has access to
an explicit set of capabilities (e.g., read-only, file-access, shell). Scopes are
negotiated at pairing time and enforced by the approval system.
**Depends on:** #2, #3.

### 5. Command Allowlist
**Files:** `src/action_gate.rs` (extend), `src/policy_engine.rs` (new)
**Scope:** Create a configurable allowlist/denylist for commands that can be triggered
from the mobile app. Extend `action_gate.rs` risk classification to add a
`mobile_origin` factor and integrate with a new `policy_engine.rs` that loads rules
from `~/.simplicio-loop/mobile-policy.json`.
**Depends on:** #4.

### 6. Approval TTLs
**Files:** `src/htool_approval.rs` (extend)
**Scope:** Add time-to-live for approval grants so that a "session" or "always"
approval from the mobile app expires after a configurable duration. Extend
`ApprovalStore` with expiry timestamps and a reaper sweep.
**Depends on:** #4.

### 7. Audit Logging
**Files:** `src/audit_command.rs` (extend or new module), `src/security_command.rs`
**Scope:** Log every mobile-originated action (command, approval decision, pairing
event) to a structured audit log (`~/.simplicio-loop/audit/mobile.jsonl`). Include
timestamp, device ID, action, risk level, and outcome.
**Depends on:** #5, #6.

### 8. Secret Redaction in Logs
**Files:** `src/tool_guardrails.rs` (new), `src/audit_command.rs` (extend)
**Scope:** Ensure secrets (API keys, tokens, passwords) are redacted from all log
output — both the audit log and any debug/trace logs. Implement pattern-based
redaction in `tool_guardrails.rs` and integrate it as a filter in the logging
pipeline.
**Depends on:** #7.

### 9. Lost Phone Recovery Flow
**Files:** `src/pairing_command.rs` (extend), `docs/security/lost-phone.md` (new)
**Scope:** Add a desktop-side command to revoke all sessions for a specific device
and rotate the pairing secret. Document the user-facing recovery procedure.
`pairing_command.rs` already has device records; add `revoke_device` and
`rotate_secret` methods.
**Depends on:** #1.

### 10. Relay Risk Controls
**Files:** `src/gateway/` (extend), `src/policy_engine.rs` (extend)
**Scope:** When traffic goes through a relay (cloud proxy), add additional controls:
rate limiting, IP allowlisting, connection-origin validation, and a kill switch to
disable relay mode entirely. Document the relay threat surface.
**Depends on:** #3, #5.

### 11. App Lock
**Files:** `apps/mobile/` (new — platform-specific)
**Scope:** Implement an app-level lock screen on the mobile app (separate from device
biometrics) with a configurable inactivity timeout. When locked, no commands can be
sent to the desktop runtime.
**Depends on:** #2.

## Dependency Graph

```
1 (Threat Model)
├── 2 (Biometric Gate)
│   ├── 4 (Session Scopes)
│   │   ├── 5 (Command Allowlist)
│   │   │   ├── 7 (Audit Logging)
│   │   │   │   └── 8 (Secret Redaction)
│   │   │   └── 10 (Relay Risk Controls)
│   │   └── 6 (Approval TTLs)
│   │       └── 7 (Audit Logging)
│   └── 11 (App Lock)
├── 3 (Transport Encryption)
│   ├── 4 (Session Scopes)
│   └── 10 (Relay Risk Controls)
└── 9 (Lost Phone Recovery)
```

## Suggested Execution Order

| Phase | Sub-issues | Rationale |
|-------|-----------|-----------|
| Phase 1 | #1 Threat Model | Foundation — informs all other decisions |
| Phase 2 | #3 Transport Encryption, #9 Lost Phone Recovery | Infrastructure, no mobile app needed |
| Phase 3 | #2 Biometric Gate, #4 Session Scopes | Core auth model |
| Phase 4 | #5 Command Allowlist, #6 Approval TTLs, #11 App Lock | Policy enforcement |
| Phase 5 | #7 Audit Logging, #8 Secret Redaction, #10 Relay Risk | Observability and hardening |

## Acceptance Criteria (from issue)

- [ ] Threat model document reviewed and merged
- [ ] Biometric/app-lock strategy documented and implemented
- [ ] All phone-to-computer traffic encrypted (TLS 1.3 or E2E)
- [ ] Session scopes enforced at pairing time
- [ ] Command allowlist configurable per-project
- [ ] Approval grants expire with co','docs/issues/1278-plan.md','395da095835b3ba814cae39934c882422ce1475e0e662f97be330e088eab424b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1279-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1279-plan.md','doc: Epic #1279 — Simplicio Mobile: Computer Action Lifecycle','# Epic #1279 — Simplicio Mobile: Computer Action Lifecycle

## Overview

Define and implement a complete lifecycle state machine for computer actions dispatched via Simplicio Mobile. The lifecycle governs how tasks flow from claim through execution, validation, evidence collection, savings calculation, and learning feedback.

## Current State

- No mobile app exists (`apps/mobile/` is absent; only `apps/desktop/` and `apps/exo/` exist).
- No lifecycle state machine or task claim/lease code exists in `src/`.
- `action_gate.rs` and `action_bridge.rs` exist but handle different concerns.

## Decomposition

### Sub-issue 1: Lifecycle State Machine in Rust

**Files:** `src/task_lifecycle.rs` (new), `src/main.rs` (add mod)

States: Unclaimed, Claimed, Planning, AwaitingApproval, Approved, Executing, Validating, Repairing, EvidenceCollection, SavingsCalculation, Learning, Completed

Key transitions:
- Unclaimed -> Claimed: worker claims task, starts lease timer
- Claimed -> Planning: worker submits execution plan
- Planning -> AwaitingApproval: plan submitted for review (if approval required)
- Planning -> Approved: auto-approved (low-risk tasks)
- AwaitingApproval -> Approved/Planning: supervisor approves or rejects
- Approved -> Executing -> Validating -> EvidenceCollection -> SavingsCalculation -> Learning -> Completed
- Validating -> Repairing -> Validating: repair loop
- Lease expiry returns task to Unclaimed

Each transition logged with timestamp and actor.

**Effort:** Medium

### Sub-issue 2: Mobile App Scaffold

**Files:** `apps/mobile/` (new directory tree)

- React Native/Expo project boilerplate
- Auth, Task list, Task detail screens
- Status badges mapped to lifecycle states (Unclaimed=Available, Claimed=Yours, Planning=Planning, AwaitingApproval=Pending, Approved=Ready, Executing=Running, Validating=Checking, Repairing=Fixing, EvidenceCollection=Evidence, SavingsCalculation=Savings, Learning=Learning, Completed=Done)

**Effort:** Large

### Sub-issue 3: Dispatch Integration

**Files:** `src/task_dispatch.rs` (new), `src/tool_registry.rs` (add match arm)

- Register task_lifecycle as a tool
- Expose: claim_task, release_task, submit_plan, start_execution, submit_evidence, record_savings
- Lease mechanism with configurable TTL (default 30 min)
- Optimistic locking for concurrent claims

**Effort:** Medium

### Sub-issue 4: Approval Gate Flow

**Files:** `src/approval_gate.rs` (new or extend `src/action_gate.rs`)

- Blocking approval gate at AwaitingApproval state
- Approval via mobile push, desktop UI, or API
- Configurable timeout (auto-reject or escalate)
- Risk classification to determine approval requirement

**Effort:** Medium

### Sub-issue 5: Evidence and Savings Attachment

**Files:** `src/task_evidence.rs` (new)

- Evidence types: screenshots, logs, file diffs, command output
- Local filesystem storage with JSON metadata sidecar
- Savings = estimated manual time minus actual automated time

**Effort:** Small-Medium

### Sub-issue 6: Helo Learning Integration

**Files:** `src/helo_learning.rs` (new)

- Emit learning record on task completion (type, plan, outcome, duration, savings, repairs)
- Batch/queue records if Helo unavailable
- Helo uses records to improve future planning

**Effort:** Small-Medium

## Implementation Order

1. Sub-issue 1 (State Machine) — foundation
2. Sub-issue 3 (Dispatch) — wires into runtime
3. Sub-issue 4 (Approval Gate) — blocking flow
4. Sub-issue 5 (Evidence/Savings) — post-execution
5. Sub-issue 6 (Helo Learning) — final lifecycle step
6. Sub-issue 2 (Mobile App) — parallel after 1, full integration after 1-5

## Dependencies

- Sub-issues 3-6 depend on sub-issue 1
- Sub-issue 2 depends on 1 (state defs) and 3 (API surface)
- Sub-issue 6 may need Helo API schema','docs/issues/1279-plan.md','aa70ee3287e759de4c378bbc47b59f03d4d9d0c2a12353731c12735dbbe12f54','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1280-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1280-plan.md','doc: Plan: #1280 — [Simplicio Mobile] E2E Test Matrix','# Plan: #1280 — [Simplicio Mobile] E2E Test Matrix

Parent epic: #1264

## Overview

Build a comprehensive E2E test matrix for Simplicio Mobile covering unit tests, integration tests with mock gateway, desktop gateway smoke tests, dispatch smoke tests, approval flow tests, offline/failure tests, and screenshot/video evidence capture.

## Dependencies

| Issue | Description | Status |
|-------|-------------|--------|
| #1244 | Mobile app scaffold | Required |
| #1247 | Mock gateway setup | Required |
| #1248 | Auth flow | Required |
| #1249 | Dispatch flow | Required |
| #1250 | Approval flow | Required |
| #1254 | Offline mode | Required |
| #1258 | Desktop gateway integration | Required |

## Sub-tasks

### 1. Test infrastructure setup
- Create `tests/e2e/` directory structure
- Add test runner configuration (cargo test harness)
- Define test matrix schema (JSON) for tracking coverage
- **Deliverable:** `tests/e2e/mod.rs`, `tests/e2e/matrix.json`

### 2. Unit test suite
- Tool handler unit tests (each htool_* module)
- Serialization/deserialization round-trip tests
- Input validation tests
- Error path coverage (no .unwrap() in production)
- **Depends on:** #1244

### 3. Mock gateway integration tests
- Create mock gateway server (`tests/e2e/mock_gateway.rs`)
- Request/response recording and replay
- Auth token exchange mock
- Timeout and error injection
- **Depends on:** #1247, #1248

### 4. Desktop gateway smoke tests
- Connection handshake test
- Tool dispatch round-trip via desktop gateway
- Reconnection after disconnect
- **Depends on:** #1258

### 5. Dispatch flow smoke tests
- End-to-end tool dispatch: request -> gateway -> handler -> response
- Concurrent dispatch handling
- Large payload handling
- **Depends on:** #1249

### 6. Approval flow tests
- Approval request creation and routing
- Approval accept/reject paths
- Timeout on pending approval
- Multi-step approval chains
- **Depends on:** #1250

### 7. Offline and failure mode tests
- Network disconnection during dispatch
- Queue persistence while offline
- Retry logic on reconnection
- Corrupted message handling
- **Depends on:** #1254

### 8. Evidence capture system
- Screenshot capture on test failure
- Test run report generation (JSON + markdown)
- Video recording integration (optional, CI-dependent)
- **Deliverable:** `tests/e2e/evidence.rs`, CI artifact upload config

## Test matrix coverage targets

| Category | Min tests | Priority |
|----------|-----------|----------|
| Unit (tool handlers) | 20+ | P0 |
| Mock gateway integration | 10+ | P0 |
| Desktop gateway smoke | 5+ | P1 |
| Dispatch smoke | 5+ | P1 |
| Approval flow | 8+ | P1 |
| Offline/failure | 8+ | P2 |
| Evidence capture | 3+ | P2 |

## Execution order

1. Test infrastructure setup (no dependencies)
2. Unit test suite (after #1244)
3. Mock gateway integration (after #1247, #1248)
4. Desktop gateway smoke (after #1258)
5. Dispatch + approval flow tests (after #1249, #1250)
6. Offline/failure tests (after #1254)
7. Evidence capture (can start in parallel with 4-6)

## Acceptance criteria

- [ ] Test matrix document exists with all categories
- [ ] Unit tests cover all tool handlers
- [ ] Mock gateway tests pass without real network
- [ ] Desktop gateway smoke tests validate connection lifecycle
- [ ] Dispatch smoke tests cover happy + error paths
- [ ] Approval flow tests cover accept/reject/timeout
- [ ] Offline tests verify queue persistence and retry
- [ ] Evidence capture produces screenshots/reports on failure','docs/issues/1280-plan.md','1e9a034979db0df70972ce3e569d329fca11058637a62f6cdaf458a130558e3a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1281-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1281-plan.md','doc: Plan: #1281 - Simplicio Mobile: Prepare TestFlight, Play Store, privacy labels','# Plan: #1281 - Simplicio Mobile: Prepare TestFlight, Play Store, privacy labels

## Context

No mobile app directory exists yet (only `apps/desktop` and `apps/exo`). This epic covers creating the entire `apps/mobile` Expo project, configuring build pipelines, store presence, legal documents, and release processes.

## Sub-tasks

### Phase 1: Project scaffold

1. **Create `apps/mobile` Expo project** - Initialize with `npx create-expo-app` using the blank TypeScript template. Target SDK 52+.
2. **Configure app identifiers** - Set `bundleIdentifier` (iOS) and `package` (Android) in `app.json` / `app.config.ts`. Proposed: `com.simplicio.runtime` / `com.simplicio.runtime`.
3. **Add base navigation and splash screen** - Minimal shell with expo-router, branded splash and icon assets.

### Phase 2: Build and signing

4. **Set up EAS Build** - Add `eas.json` with profiles: `development`, `preview`, `production`.
5. **iOS code-signing** - Create Apple Distribution certificate and provisioning profile. Store credentials in EAS or document manual process.
6. **Android keystore** - Generate upload keystore. Store in EAS credentials or document secure storage policy.
7. **CI integration** - Add GitHub Actions workflow for `eas build` on push to `main` (preview) and on tag (production).

### Phase 3: Store presence and legal

8. **Apple Developer App Record** - Create app record in App Store Connect with bundle ID, app name, category.
9. **Google Play Console App Record** - Create app in Play Console, set package name, content rating questionnaire.
10. **Privacy Policy document** - Draft `docs/legal/privacy-policy.md` covering: data collected, purpose, third-party sharing, retention, user rights (LGPD/GDPR). Host at a public URL.
11. **App Store Privacy Labels (Nutrition Labels)** - Complete the App Privacy section in App Store Connect. Categories to evaluate:
    - Contact Info (if login exists)
    - Usage Data (analytics)
    - Diagnostics (crash logs)
    - Identifiers (device ID)
12. **Google Play Data Safety form** - Complete the Data Safety section in Play Console, mirroring the privacy policy.

### Phase 4: Internal testing

13. **TestFlight setup** - Upload first build to TestFlight. Create internal testing group. Add testers.
14. **Play Store internal testing track** - Upload first AAB to internal testing. Add testers via email list.
15. **Smoke test checklist** - Document manual QA steps for first build validation.

### Phase 5: Release process

16. **Versioning strategy** - Define semver policy. Use `expo.version` and `expo.ios.buildNumber` / `expo.android.versionCode`. Automate bump via `standard-version` or `semantic-release`.
17. **CHANGELOG.md** - Initialize changelog in `apps/mobile/CHANGELOG.md`.
18. **Release runbook** - Document step-by-step: bump version, build, upload, promote from internal to beta to production.

## Dependencies

- Apple Developer account (Team ID, certificates)
- Google Play Console account (service account for EAS)
- Domain for hosting privacy policy (or use GitHub Pages)
- Brand assets (icon 1024x1024, splash, adaptive icon)

## Acceptance criteria

- `apps/mobile` exists with a buildable Expo project
- `eas build --platform all --profile preview` succeeds
- First build uploaded to TestFlight internal testing
- First build uploaded to Play Store internal testing track
- Privacy policy published at a public URL
- App Store privacy labels completed
- Play Store data safety form completed
- CHANGELOG.md initialized
- Release runbook documented','docs/issues/1281-plan.md','d9cf6cc1eb56b43f5176726a4a8217c5cf0eadafd7a616fa04ae1ad026df4c41','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1282-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1282-plan.md','doc: Epic #1282 — [Simplicio Mobile] Build Launch Demo','# Epic #1282 — [Simplicio Mobile] Build Launch Demo

## Overview

Build an end-to-end launch demo showcasing Simplicio''s mobile-first workflow: a user composes a task on their phone, the desktop gateway processes it, the phone displays an approval gate, a live timeline renders progress, and a results screen shows evidence and savings. A promotional video script ties it all together.

## Dependencies

| Issue | Description | Status |
|-------|-------------|--------|
| #1244 | Mobile app scaffold (apps/mobile) | Pending |
| #1247 | Desktop gateway + pairing flow | Pending |
| #1248 | Approval gate UI (phone) | Pending |
| #1249 | Live timeline rendering | Pending |
| #1250 | Evidence/savings result screen | Pending |
| #1254 | Task composer (mobile) | Pending |
| #1258 | QR pairing protocol | Pending |

## Sub-tasks

### Phase 1 — Mobile App Foundation

1. **#1282-A: Create `apps/mobile` scaffold**
   - Initialize a React Native or Tauri Mobile project under `apps/mobile/`
   - Share design tokens with `apps/desktop`
   - Deliverable: buildable mobile shell with navigation

2. **#1282-B: Task Composer UI**
   - Text input + voice-to-text button
   - Category selector (quick-pick chips)
   - "Send to Simplicio" action button
   - Depends on: #1254, #1282-A

### Phase 2 — Desktop Gateway + Pairing

3. **#1282-C: Desktop gateway endpoint**
   - WebSocket server in `apps/desktop/src-tauri` accepting mobile connections
   - mDNS or QR-code-based discovery
   - Depends on: #1247, #1258

4. **#1282-D: QR pairing flow**
   - Desktop shows QR code with connection token
   - Mobile scans and establishes secure channel
   - Depends on: #1282-C

### Phase 3 — Approval + Timeline

5. **#1282-E: Approval gate UI (mobile)**
   - Push notification when plan is ready
   - Step-by-step plan review with approve/reject per step
   - "Approve All" shortcut
   - Depends on: #1248, #1282-B

6. **#1282-F: Live timeline rendering (mobile)**
   - Real-time progress indicators per step
   - Streaming log output (collapsed by default)
   - Error state with retry option
   - Depends on: #1249, #1282-E

### Phase 4 — Results + Evidence

7. **#1282-G: Evidence & savings result screen**
   - Before/after comparison cards
   - Time saved metric (estimated vs manual)
   - Screenshot/artifact gallery
   - Share/export button
   - Depends on: #1250, #1282-F

### Phase 5 — Demo Assets

8. **#1282-H: Demo script (Markdown)**
   - Step-by-step demo walkthrough with speaker notes
   - Timing cues for each transition
   - File: `docs/demo/launch-demo-script.md`

9. **#1282-I: Screenshot set**
   - Capture each screen state from the demo flow
   - Annotated versions for the presentation deck
   - Directory: `docs/demo/screenshots/`

10. **#1282-J: Promotional video script**
    - 60-90 second narration script
    - Shot list mapped to demo screens
    - Music/SFX cues
    - File: `docs/demo/video-script.md`

## Execution Order

```
#1282-A (mobile scaffold)
    |
    v
#1282-B (task composer) + #1282-C (gateway) + #1282-D (pairing)
    |                          |
    +-----------+--------------+
                |
                v
          #1282-E (approval gate)
                |
                v
          #1282-F (live timeline)
                |
                v
          #1282-G (results screen)
                |
                v
    #1282-H + #1282-I + #1282-J (demo assets, parallel)
```

## Acceptance Criteria

- [ ] Mobile app builds and runs on iOS simulator and Android emulator
- [ ] Full demo flow works end-to-end: compose -> pair -> approve -> execute -> results
- [ ] Demo script covers all screens with timing under 5 minutes
- [ ] Video script is ready for recording
- [ ] Screenshot set covers all 6 key screens','docs/issues/1282-plan.md','ac7385c72dfb66bcde4085f8e3a227ee024a462621ead1794b0167972cbc0826','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1283-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1283-plan.md','doc: Plan: #1283 — Voice-first task input','# Plan: #1283 — Voice-first task input

Parent epic: #1264

## Context

The TUI already has voice state scaffolding (`voiceEnabled`, `voiceRecording`, `voiceProcessing`) and a gateway event handler for `voice.status`. The mobile app (`apps/mobile`) does not exist yet. This epic requires building an entire mobile voice-first input pipeline from scratch.

## Sub-issues

### 1. Mobile app scaffold
- Initialize React Native project under `apps/mobile`
- Navigation shell, theme system, auth flow (reuse existing gateway tokens)
- CI: build check for iOS/Android
- **Estimate:** L

### 2. Mic permission + audio recording
- Platform-specific permission flows (iOS `NSMicrophoneUsageDescription`, Android `RECORD_AUDIO`)
- Push-to-talk UI component (hold-to-record button)
- Audio capture using `expo-av` or `react-native-audio-recorder`
- Waveform visualization during recording
- **Estimate:** M

### 3. Speech-to-text integration
- Integrate STT provider (Whisper API or platform-native: Apple Speech, Google Speech)
- Streaming partial transcripts during recording
- Language detection / PT-BR primary support
- Offline fallback via on-device models
- **Estimate:** M

### 4. Transcript display and edit
- Real-time transcript rendering as speech is recognized
- Editable text field post-recording for corrections
- Word-level confidence highlighting (optional)
- **Estimate:** S

### 5. Intent normalization
- Parse free-form voice transcript into structured task intent
- Map to existing Simplicio tool/action vocabulary
- Handle ambiguous intents with clarification prompts
- Reuse `simplicio_gate` / `simplicio_map` tool patterns from MCP
- **Estimate:** M

### 6. Confirmation UX + dispatch to desktop
- Show normalized intent summary for user confirmation
- Send confirmed intent to desktop TUI via gateway WebSocket
- Handle `voice.status` events round-trip (recording -> processing -> dispatched)
- Error/retry states
- **Estimate:** M

### 7. PT-BR language support
- Default locale PT-BR for STT
- All UI strings localized (PT-BR primary, EN fallback)
- Brazilian Portuguese voice prompts and feedback
- **Estimate:** S

## Dependency graph

```
[1] Mobile scaffold
 |
 +--[2] Mic + recording
 |    |
 |    +--[3] STT integration
 |         |
 |         +--[4] Transcript UI
 |              |
 |              +--[5] Intent normalization
 |                   |
 |                   +--[6] Confirm + dispatch
 |
 [7] PT-BR (parallel, touches 2-6)
```

## Acceptance criteria (from issue)

1. Push-to-talk button on mobile home screen
2. Audio permission requested on first use with clear rationale
3. Real-time transcript displayed during speech
4. User can edit transcript before confirming
5. Intent normalized to actionable task format
6. Confirmation screen before dispatch to desktop
7. PT-BR as default language

## Risks

- STT latency on low-bandwidth connections
- Platform fragmentation (iOS vs Android audio APIs)
- Gateway WebSocket stability for mobile (background/foreground transitions)
- On-device model size for offline PT-BR STT','docs/issues/1283-plan.md','4d05e21591ad39007b32bf3e119da3a700feae83b09ada035aa30a15a6d5f2a7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1284-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1284-plan.md','doc: Epic #1284: Voice Approvals with Risk Readback','# Epic #1284: Voice Approvals with Risk Readback

## Overview

Add voice-driven approval workflow to Simplicio: when a dangerous command requires approval, dispatch it to the user''s mobile device with a spoken risk summary, accept voice intents (approve/reject/explain), and record an evidence ledger.

## Current State

Existing modules provide text-based approval (`htool_approval.rs`), TTS output (`htool_tts_tool.rs`), voice mode (`htool_voice_mode.rs`), voice commands (`voice_command.rs`), STT input (`voice_stt.rs`), and permission gating (`acp_adapter/permissions_approval.rs`, `acp_adapter/permissions_gate.rs`). None of these currently support mobile dispatch, voice-specific approval intents, TTL/replay protection, biometric fallback, or redacted evidence recording.

## Sub-issues

### 1. Voice Approval Inbox & Mobile Dispatch
**Files:** new `src/htool_voice_approval_inbox.rs`, extend `htool_approval.rs`
- Define `VoiceApprovalRequest` struct (command summary, risk tier, TTL, unique nonce).
- Implement mobile push dispatch via notification channel (WebSocket or push notification adapter).
- Inbox stores pending approvals with status tracking (pending/approved/rejected/expired).
- Expose `voice_approval_inbox` htool for querying and acting on pending items.

### 2. TTS Risk Summary Generation
**Files:** extend `htool_tts_tool.rs`, new `src/risk_readback.rs`
- Given an approval request, generate a human-readable risk summary string.
- Classify risk into tiers: low, medium, high, critical.
- Feed summary to TTS engine for spoken playback on the mobile client.
- Include: command description, affected resources, reversibility, and risk tier.

### 3. Voice Intent Classifier for Approve/Reject/Explain
**Files:** extend `voice_command.rs`, extend `voice_stt.rs`
- Parse STT transcriptions for approval intents: "approve", "yes go ahead", "reject", "deny", "explain more", "what does this do", etc.
- Return structured `ApprovalIntent` enum: `Approve`, `Reject`, `Explain`, `Unclear`.
- Support both English and Portuguese phrases.
- On `Explain`, trigger a more detailed risk readback before re-prompting.

### 4. TTL & Replay Protection Layer
**Files:** extend `htool_approval.rs`, new `src/approval_ttl.rs`
- Each approval request gets a unique nonce and expiration timestamp.
- Reject any approval response with an expired TTL or a previously-used nonce.
- Configurable TTL per risk tier (e.g., critical = 60s, low = 300s).
- Store used nonces in a bounded set with automatic eviction.

### 5. Biometric / Tap Fallback for High-Risk Tiers
**Files:** extend `htool_voice_mode.rs`, new `src/biometric_gate.rs`
- For `high` and `critical` risk tiers, voice approval alone is insufficient.
- Require a secondary confirmation: biometric (fingerprint/face) or physical tap on mobile.
- Define `BiometricChallenge` request/response structs.
- Integrate with mobile client via the approval dispatch channel.

### 6. Evidence Ledger with Secret Redaction
**Files:** new `src/approval_evidence.rs`, extend `htool_write_approval.rs`
- Record every approval decision: who, when, what command, risk tier, approval method, outcome.
- Redact secrets (API keys, tokens, passwords) from the recorded command text before storage.
- Use pattern-based redaction (regex for common secret formats) plus explicit parameter tagging.
- Append-only ledger stored as JSON lines, rotatable.

### 7. Mobile App Approval UI (Future)
**Files:** new `apps/mobile/` directory
- React Native or Flutter UI for the approval inbox.
- Displays pending approvals with risk summary.
- Buttons for approve/reject, mic button for voice intent, biometric prompt for high-risk.
- This is a separate deliverable and may be tracked as its own epic.

## Dependency Order

```
[4. TTL/Replay] ──┐
                   ├──> [1. Inbox & Dispatch] ──> [7. Mobile UI]
[2. TTS Risk]  ───┤
[3. Voice Intent] ─┤
[6. Evidence]  ────┘
[5. Biometric] ────────> [1. Inbox & Dispatch]
```

## Acceptance Criteria

- A dangerous command triggers a voice approval request with spoken risk readback.
- User can approve or reject via voice on mobile device.
- High/critical risk commands require biometric or tap confirmation.
- Expired or replayed approval tokens are rejected.
- All approval decisions are recorded with secrets redacted.
- cargo check passes after each sub-issue implementation.','docs/issues/1284-plan.md','45453c2d44782bbad277063185b15edd8402ab02dd1f8152c005e01df1eaf6be','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1285-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1285-plan.md','doc: Epic #1285 — Simplicio Voice: Spoken Status, TTS Narration, Completion Summaries','# Epic #1285 — Simplicio Voice: Spoken Status, TTS Narration, Completion Summaries

## Context

The runtime already has a basic TTS adapter (`tools/tts_tool.py`, `src/tts_provider.rs`, `agent/tts_provider.py`, `agent/tts_registry.py`), but none of the narration-layer features described in the epic exist yet: no mobile push narration, no narration settings, no status phrase catalog, no completion summaries, no stop/pause controls, and no accessibility label alignment.

## Decomposition

### Sub-issue 1: Status Phrase Catalog
- Create `src/narration/status_catalog.rs` with an enum of run states (Queued, Running, Blocked, Succeeded, Failed, Cancelled, TimedOut).
- Map each state to a human-friendly phrase template (e.g., "Task {name} is now running").
- Support locale-aware phrase selection (start with en, pt-BR).
- **Deliverable:** Rust module with unit tests.

### Sub-issue 2: Narration Settings Model
- Define a `NarrationLevel` enum: `Silent`, `Important`, `Verbose`.
- Add a `NarrationSettings` struct with fields: `level`, `voice_id`, `speed`, `locale`.
- Persist settings via serde JSON to `~/.simplicio-loop/narration.json`.
- **Deliverable:** Rust module + serde round-trip tests.

### Sub-issue 3: TTS Adapter Integration for Narration
- Extend existing `src/tts_provider.rs` to accept a `NarrationRequest { phrase, settings }`.
- Route through the current TTS provider (local or remote) based on settings.
- Add a `narrate_status(state, task_name, settings)` high-level function that combines the catalog lookup + TTS call.
- **Deliverable:** Extended TTS provider with integration test.

### Sub-issue 4: Completion Summary Generator
- Create `src/narration/completion_summary.rs`.
- Given a finished task, produce a spoken summary: outcome, duration, tokens used, cost savings estimate.
- Format as a natural sentence (e.g., "Task X completed in 2 minutes, used 1.2k tokens, saved approximately 15 minutes of manual work").
- Respect `NarrationLevel` — silent skips, important gives one-liner, verbose gives full breakdown.
- **Deliverable:** Module with unit tests covering all three levels.

### Sub-issue 5: Stop/Pause Narration Controls
- Add `narration_pause()` and `narration_resume()` functions to the narration module.
- Expose as tool calls: `simplicio_narration_pause`, `simplicio_narration_resume`.
- Register in `tool_registry.rs`.
- **Deliverable:** Tool implementations + registry integration.

### Sub-issue 6: Accessibility Label Alignment
- Audit all existing UI-facing strings in the runtime for consistency with narration phrases.
- Create a shared `labels.rs` module that both screen-reader labels and TTS narration reference.
- Ensure status phrases and accessibility labels use identical wording.
- **Deliverable:** Shared labels module, migration of existing strings.

### Sub-issue 7: Mobile App Scaffold (Future)
- Create `apps/mobile/` directory structure for a minimal mobile client.
- Integrate push notification delivery of narration events.
- Wire TTS playback on the mobile side.
- **Note:** This is a larger effort and may be its own epic. The narration layer (sub-issues 1-6) should be built first as a backend capability.

### Sub-issue 8: Tests and Evidence Artifacts
- End-to-end test: trigger a task run, verify narration events are emitted with correct phrases.
- Test narration settings persistence and level filtering.
- Test stop/pause controls.
- Document evidence in `docs/issues/1285-evidence.md` once complete.

## Suggested Implementation Order

1. Sub-issue 1 (Status Phrase Catalog) — no dependencies
2. Sub-issue 2 (Narration Settings) — no dependencies
3. Sub-issue 3 (TTS Adapter Integration) — depends on 1, 2
4. Sub-issue 4 (Completion Summary) — depends on 1, 2
5. Sub-issue 5 (Stop/Pause Controls) — depends on 3
6. Sub-issue 6 (Accessibility Labels) — depends on 1
7. Sub-issue 8 (Tests) — depends on 3, 4, 5
8. Sub-issue 7 (Mobile App) — depends on 3, separate epic

## Files to Create/Modify

- `src/narration/mod.rs` (new module)
- `src/narration/status_catalog.rs`
- `src/narration/settings.rs`
- `src/narration/completion_summary.rs`
- `src/narration/controls.rs`
- `src/narration/labels.rs`
- `src/tts_provider.rs` (extend)
- `src/tool_registry.rs` (add narration tools)
- `src/main.rs` (add `mod narration`)','docs/issues/1285-plan.md','c0730ffa43b151360b4fbc1c70a44509eefd2a4eb9ff1f05bf4f4b9a9ec3f3f0','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1286-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1286-plan.md','doc: Plan: #1286 - Simplicio Voice - Privacy, Noisy-Environment QA, Multilingual','# Plan: #1286 - Simplicio Voice - Privacy, Noisy-Environment QA, Multilingual

## Context

Epic for adding voice interaction capabilities to Simplicio with three pillars:
voice privacy (no raw audio retention), noisy-environment resilience, and
multilingual support (PT-BR / EN).

No voice/STT/speech module exists today. The existing redaction in `agent_chat.rs`
masks secrets in text, not audio transcriptions. No `apps/mobile` directory exists.

---

## Sub-issues (recommended decomposition)

### 1. Voice Privacy Policy and No-Raw-Audio Retention
**Scope:** Define and enforce a policy where raw audio is never persisted to disk
or transmitted beyond the local STT engine. Transcriptions go through the existing
redaction pipeline before logging.

- Create `src/voice_privacy.rs` with `VoicePrivacyPolicy` struct
- Audio buffer is in-memory only, zeroed after transcription
- Hook transcription output into `agent_chat::redact_secrets()` before any log/store
- Add config flag `voice.retain_audio = false` (default)
- Unit tests: verify buffer is zeroed, verify redaction applies to transcriptions

### 2. STT Integration - Local-First / BYOK
**Scope:** Integrate a speech-to-text engine that runs locally by default (e.g.,
Whisper.cpp via FFI or subprocess), with optional BYOK cloud key.

- Create `src/voice_stt.rs` with trait `SttEngine { fn transcribe(&self, audio: &[u8]) -> Result<Transcription> }`
- `LocalWhisperEngine` - calls whisper.cpp binary, parses JSON output
- `CloudSttEngine` - uses user-provided API key (Azure/Google/Deepgram)
- Config: `voice.stt.provider = "local" | "cloud"`, `voice.stt.api_key`
- Confidence score included in `Transcription` struct

### 3. Confidence Threshold and Confirmation Flow
**Scope:** When STT confidence is below threshold, ask user to confirm or retype.

- Create `src/voice_confirmation.rs`
- Configurable threshold: `voice.confidence_threshold = 0.7` (default)
- Below threshold: present transcription + "Did you mean: X? [y/n/retype]"
- Above threshold: proceed automatically
- Tests with mock STT returning various confidence levels

### 4. Grammar PT-BR / EN with Test Fixtures
**Scope:** Define command grammars for both languages so voice commands map to
Simplicio tool invocations.

- Create `src/voice_grammar.rs`
- Command patterns: "abrir arquivo X" -> `file_open(X)`, "open file X" -> `file_open(X)`
- Language detection from transcription metadata or config `voice.language = "auto" | "pt-BR" | "en"`
- Fixture files: `tests/fixtures/voice_commands_pt_br.json`, `tests/fixtures/voice_commands_en.json`
- Each fixture: `{ "utterance": "...", "expected_tool": "...", "expected_args": {...} }`
- Integration tests parsing fixtures

### 5. Noisy-Environment Fallback
**Scope:** When ambient noise makes STT unreliable, gracefully degrade to typed input.

- Create `src/voice_noise_detect.rs`
- Track rolling confidence average over last N transcriptions
- If average drops below `voice.noise_fallback_threshold = 0.5`, switch to typed mode
- Notify user: "Ambiente ruidoso detectado, alternando para entrada digitada"
- Auto-retry voice after configurable cooldown
- Tests with simulated low-confidence sequences

### 6. Accessibility - Typed Fallback, Captions, Screen-Reader Labels
**Scope:** Ensure voice features are fully accessible.

- All voice prompts have typed-input alternatives (never voice-only paths)
- Live captions of STT output displayed in terminal
- Screen-reader compatible labels (ARIA-like metadata for TUI)
- Create `src/voice_accessibility.rs` with caption rendering and label registry
- Config: `voice.captions = true`, `voice.screen_reader_labels = true`

### 7. Mobile Scaffold (`apps/mobile`)
**Scope:** Create initial project structure for a mobile companion app.

- `apps/mobile/README.md` - architecture overview
- `apps/mobile/Cargo.toml` - workspace member, depends on `simplicio-runtime`
- `apps/mobile/src/lib.rs` - re-export voice modules for mobile FFI
- `apps/mobile/src/ffi.rs` - C-compatible FFI boundary for iOS/Android
- This is scaffold only; actual mobile UI is a separate epic

---

## Dependency graph

```
[1] Voice Privacy Policy
[2] STT Integration -----> depends on [1] (privacy constraints)
[3] Confirmation Flow ---> depends on [2] (needs confidence scores)
[4] Grammar PT-BR/EN ----> depends on [2] (needs transcription output)
[5] Noisy Fallback ------> depends on [3] (uses confidence tracking)
[6] Accessibility -------> depends on [3,4] (captions need transcription + grammar)
[7] Mobile Scaffold -----> depends on [1,2] (re-exports voice modules)
```

## Estimated effort

| Sub-issue | Size | Priority |
|-----------|------|----------|
| 1. Voice Privacy | S | P0 |
| 2. STT Integration | L | P0 |
| 3. Confirmation Flow | M | P1 |
| 4. Grammar PT-BR/EN | M | P1 |
| 5. Noisy Fallback | S | P1 |
| 6. Accessibility | M | P2 |
| 7. Mobile Scaffold | S | P2 |','docs/issues/1286-plan.md','214f48b84195bedb8d2ae76dae0e535df79824ec53e62b4f63bbca939ab56d60','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1288-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1288-plan.md','doc: Epic #1288: Video Editing Skill -- browser-use/video-use Integration','# Epic #1288: Video Editing Skill -- browser-use/video-use Integration

## Context

The current video pipeline (`video_pipeline.rs`) covers: script -> assets -> audio -> timeline -> render -> captions.
There is no post-production stage (filler-word cuts, color grading, video-use integration).
This epic decomposes the work into concrete, independently-implementable subtasks.

---

## Subtask Decomposition

### 1. Post-Production Pipeline Stage
**Files:** `src/video_pipeline.rs`
- Add a `PostProduction` stage between `Render` and `Captions` (or after Captions).
- Define `PostProductionConfig` struct with fields: `remove_filler_words: bool`, `color_grade: Option<String>`, `trim_silence: bool`, `custom_edits: Vec<EditAction>`.
- Wire the new stage into `PipelineStage` enum and the main `run()` execution loop.
- The stage should be a no-op when no post-production config is provided (backward compatible).

### 2. EditAction Abstraction
**Files:** `src/video_edit_action.rs` (new)
- Define `EditAction` enum: `Cut { start_ms, end_ms }`, `ColorGrade { preset }`, `SpeedRamp { start_ms, end_ms, factor }`, `Overlay { asset_id, position, start_ms, duration_ms }`, `AudioDuck { start_ms, end_ms, level }`.
- Implement `serde::Serialize` / `serde::Deserialize` for all variants.
- Add validation (no `.unwrap()`, proper `Result` returns).

### 3. Browser-Use Skill Wrapper
**Files:** `src/htool_video_edit_tool.rs` (new), `src/tool_registry.rs`
- Create `HToolVideoEdit` implementing the tool trait.
- Input schema: `{ video_path, actions: Vec<EditAction>, output_path }`.
- The tool sends edit commands to a browser-use/video-use backend via HTTP POST.
- Register in `tool_registry.rs` match arm.

### 4. Video-Use Provider Integration
**Files:** `src/video_provider.rs`, `src/video_edit_provider.rs` (new)
- Define `VideoEditProvider` trait with `async fn apply_edits(source: &Path, actions: &[EditAction]) -> Result<PathBuf>`.
- Implement `BrowserUseVideoEditProvider` that connects to a self-hosted browser-use instance.
- Implement `LocalFfmpegVideoEditProvider` as fallback for simple cuts/color grading via ffmpeg CLI.

### 5. Remotion Output Integration (#243 dependency)
**Files:** `src/video_pipeline.rs`, `src/video_edit_provider.rs`
- After Remotion render completes (per #243), feed output path into the post-production stage.
- Ensure Remotion''s output format (mp4/webm) is compatible with edit providers.
- Add config field `remotion_output_dir` to pipeline config.

### 6. Action Gate for File Mutations
**Files:** `src/action_gate.rs` (or existing gate module)
- Before any file write/overwrite in the edit pipeline, check `action_gate` approval.
- Gate checks: file size limits, allowed output directories, overwrite confirmation.
- Log all mutations for audit trail.

### 7. Self-Hosted Setup and Configuration
**Files:** `skills/creative/video_edit/` (new directory), config files
- Docker compose for self-hosted browser-use with video-use extension.
- Configuration schema for connecting the runtime to the self-hosted instance (base URL, auth token, timeout).
- Health check endpoint integration.

### 8. ComfyUI Workflow for Video Post-Processing
**Files:** `skills/creative/comfyui/workflows/video_postprocess.json` (new)
- Optional ComfyUI workflow for AI-driven color grading and style transfer.
- Wire into `VideoEditProvider` as an alternative backend.

---

## Execution Order

```
[1] EditAction Abstraction (no dependencies)
[2] Post-Production Pipeline Stage (depends on 1)
[3] Video-Use Provider Integration (depends on 1)
[4] Browser-Use Skill Wrapper / HToolVideoEdit (depends on 1, 3)
[5] Action Gate for File Mutations (depends on 2)
[6] Remotion Output Integration (depends on 2, blocked by #243)
[7] Self-Hosted Setup (depends on 3)
[8] ComfyUI Workflow (depends on 3, optional)
```

## Estimated Effort

| Subtask | Size | Priority |
|---------|------|----------|
| 1. Post-Production Stage | M | P0 |
| 2. EditAction Abstraction | S | P0 |
| 3. Browser-Use Wrapper | M | P0 |
| 4. Video-Use Provider | L | P0 |
| 5. Remotion Integration | M | P1 (blocked) |
| 6. Action Gate | S | P1 |
| 7. Self-Hosted Setup | M | P1 |
| 8. ComfyUI Workflow | S | P2 |','docs/issues/1288-plan.md','7426584617563d72fa8078380ebbf17a4810c8a5e630b47f69ce33eaba0070bb','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1289-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1289-plan.md','doc: Epic #1289: CodeGraph — Pre-indexed Codebase for Agents (-57% tokens)','# Epic #1289: CodeGraph — Pre-indexed Codebase for Agents (-57% tokens)

## Overview

Build a persistent call/dependency graph index so sub-agents can answer
"who calls X?", "what does X depend on?" without reading source files,
cutting token usage by ~57% on navigation-heavy tasks.

## Sub-issues

### 1. Parser / Indexer (`simplicio index` CLI command)
- **Scope:** New CLI subcommand that walks a project tree, parses source
  files (Rust, TypeScript, Python initially), and extracts:
  - Function/method definitions (name, file, line, signature)
  - Call edges (caller -> callee)
  - Import/module dependencies
- **Files:** `src/codegraph_parser.rs`, `src/main.rs` (add subcommand)
- **Effort:** L
- **Acceptance:** `simplicio index .` produces `.simplicio-loop/index/graph.json`

### 2. Graph Storage Format
- **Scope:** Define a compact JSON (or MessagePack) schema for the graph
  stored in `.simplicio-loop/index/`. Must support fast lookup by symbol name.
  Include file-level checksums for incremental updates.
- **Files:** `src/codegraph_store.rs`, `schemas/codegraph.schema.json`
- **Effort:** M
- **Acceptance:** Schema documented; round-trip serialize/deserialize passes.

### 3. Query API
- **Scope:** Expose an MCP tool (`codegraph_query`) that answers:
  - `callers_of(symbol)` — who calls this function?
  - `callees_of(symbol)` — what does this function call?
  - `depends_on(file)` — what files does this file import?
  - `dependents_of(file)` — what files import this file?
  - `symbol_info(name)` — definition location, signature
- **Files:** `src/htool_codegraph.rs`, `src/tool_registry.rs`
- **Effort:** M
- **Acceptance:** Each query returns results from the index without reading
  source files.

### 4. Agent Integration (Auto-consult)
- **Scope:** When a sub-agent receives a task involving code navigation,
  automatically prepend a codegraph query to the context so the agent
  starts with structural knowledge instead of blind file reads.
- **Files:** `src/agent_init.rs`, `src/wave_engine.rs`
- **Effort:** M
- **Acceptance:** Agent tasks that previously required 5+ file reads now
  require <=2 on indexed projects.

### 5. Incremental Updates
- **Scope:** On re-index, compare file checksums against the stored index.
  Only re-parse changed files and update affected edges. Support
  `--watch` mode using filesystem notifications.
- **Files:** `src/codegraph_parser.rs` (extend), `src/codegraph_store.rs`
- **Effort:** M
- **Acceptance:** Re-indexing a project with 1 changed file completes in
  <1s for repos up to 10k files.

## Suggested Order

1 -> 2 -> 3 -> 5 -> 4

Sub-issues 1 and 2 can be developed in parallel. Sub-issue 3 depends on
both. Sub-issue 5 extends 1+2. Sub-issue 4 is last since it requires the
query API to be stable.

## Constraints

- std + serde + serde_json only (no tree-sitter or syn crate initially;
  use regex-based extraction for v1)
- No `.unwrap()` in production code
- Index must be `.gitignore`-able (lives in `.simplicio-loop/index/`)','docs/issues/1289-plan.md','f4229f14a5aaf4da38830c0150fdcdfe7d833cc46db90d1fe86dfea6529d524e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/1290-plan.md','project_doc','doc://simplicio-runtime/docs/issues/1290-plan.md','doc: Plan: #1290 — Knowledge-work plugins (official Anthropic specialist personas)','# Plan: #1290 — Knowledge-work plugins (official Anthropic specialist personas)

## Overview

Port 11 official Anthropic knowledge-work plugins as Simplicio skills with
domain-specialist persona support. Each plugin becomes a skill directory under
`skills/` with a `SKILL.md`, and `persona.rs` gains a `DomainSpecialist` variant
that dispatches to the correct skill context.

## Domain specialists to implement

| # | Persona slug          | Skill directory             | Description                              |
|---|-----------------------|-----------------------------|------------------------------------------|
| 1 | `sales`               | `skills/sales/`             | Pipeline, outreach, objection handling   |
| 2 | `support`             | `skills/customer-support/`  | Ticket triage, escalation, KB lookup     |
| 3 | `marketing`           | `skills/marketing/`         | Campaign copy, SEO, audience analysis    |
| 4 | `legal`               | `skills/legal/`             | Contract review, clause extraction       |
| 5 | `finance`             | `skills/finance-specialist/`| Modeling, forecasting, variance analysis |
| 6 | `hr`                  | `skills/hr/`                | Job descriptions, policy Q&A, onboarding |
| 7 | `product`             | `skills/product-management/`| PRDs, user stories, prioritization       |
| 8 | `data_analyst`        | `skills/data-analyst/`      | SQL generation, dashboards, insights     |
| 9 | `technical_writer`    | `skills/technical-writing/` | Docs, API refs, style guide compliance   |
|10 | `project_manager`     | `skills/project-management/`| Status reports, risk registers, timelines|
|11 | `executive_assistant` | `skills/executive-assistant/`| Briefings, scheduling, meeting prep     |

## Decomposition

### Phase 1 — Extend `Persona` enum (src/persona.rs)

- Add `DomainSpecialist(DomainSpecialty)` variant to `Persona`.
- Define `DomainSpecialty` enum with the 11 slugs above.
- Implement `as_str()`, `parse()`, and `apply()` for the new variants.
- Wire `--persona <slug>` CLI dispatch to accept domain slugs.
- Each specialty configures `UserProfile` with appropriate tone, verbosity,
  and domain-specific system prompt tier-2 layer.

### Phase 2 — Create skill directories (skills/)

For each of the 11 specialists:

1. Create `skills/<name>/SKILL.md` following `skills/_template/` structure.
2. Define trigger phrases, tool allowlist, and prompt preamble.
3. Include domain-specific memory schema (what the skill persists across sessions).
4. Reference the corresponding `DomainSpecialty` variant so `--persona` auto-loads the skill.

### Phase 3 — Register skills in skill store

- Update `src/htool_skill_manager_tool.rs` and `src/skills_v2.rs` to discover
  and load the new skill directories.
- Ensure `simplicio skills list` includes all 11 new entries.
- Wire persona-to-skill auto-activation: when `--persona sales` is used, the
  `skills/sales/` skill is automatically loaded into context.

### Phase 4 — Runtime memory/context integration

- Each domain specialist gets a namespaced memory scope (e.g., `memory/sales/`)
  so domain knowledge persists independently.
- System prompt tier-2 layer pulls from skill SKILL.md preamble.
- Context compression respects domain-specific retention rules (e.g., legal
  keeps clause references longer).

### Phase 5 — Tests

- Unit tests for `DomainSpecialty::parse()` round-trip.
- Unit tests for `Persona::apply()` producing correct `UserProfile` fields.
- Integration test: `--persona sales` loads the sales skill and sets tone.
- Snapshot test for each specialist''s system prompt tier-2 output.

## Dependencies

- #194 (skill store registration) — must be merged or compatible.
- No external crates needed; std + serde + serde_json suffice.

## Estimated sub-issues

| Sub-issue | Phase | Effort |
|-----------|-------|--------|
| Define `DomainSpecialty` enum + `parse`/`apply` | 1 | S |
| Wire `--persona` CLI dispatch for domain slugs | 1 | S |
| Create 11 SKILL.md files | 2 | M |
| Register skills in skill store | 3 | S |
| Namespaced memory scopes | 4 | M |
| System prompt tier-2 integration | 4 | S |
| Test suite | 5 | M |','docs/issues/1290-plan.md','59ba22ea454aac3cdaa90320e47f96ce900913678a7aabde89de3c7543998886','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/2998-handoff-2026-07-10-wave-planning.md','project_doc','doc://simplicio-runtime/docs/issues/2998-handoff-2026-07-10-wave-planning.md','doc: Runtime wave planning handoff — 2026-07-10','# Runtime wave planning handoff — 2026-07-10

Scope of this note:

- record what was done in the planning-only phase
- link the GitHub issues/comments that now anchor the work
- state what is already evidenced versus what remains unproven
- leave a clean restart point for the later correction/execution phase

## What was done

The active Runtime control-plane run was intentionally moved into an issue-first mode.
No new Runtime implementation was accepted as completed in this lane. Instead, the
final goal was translated into explicit GitHub backlog, gates, milestones, evidence
contracts, and cross-repo dependencies.

Central anchors:

- runtime epic: `#2998`
- final scheduler gate: `#3042`

Additional gaps opened from real usage in this lane:

- `#3032` per-lane evidence dirs and state transitions
- `#3039` mirrored-module drift blocking builds
- `#3044` stable official readiness-audit contract
- `#3048` compact-shell structured JSON preservation

## What is already evidenced

Local evidence captured during this planning lane:

- local Runtime binary reports `Simplicio Runtime 3.5.0`
- readiness audit returned `overall_ok=true`
- local LLM was detected and healthy
- neural DB existed and was readable
- seed artifacts existed
- skills tree and seed-sync guard existed
- consciousness wiring evidence existed
- parallelism profile indicated 6+ active-agent capacity

This is enough to justify a partial-ready infrastructure snapshot.
It is not enough to claim the final objective is complete.

## What is still missing

The final requirement is still unproven because the critical scheduler proof does not
exist yet: a real 6-lane wave governed by Runtime with deterministic lifecycle,
leases, bounded Tokio concurrency, evidence dirs, and zero self-mutation.

Operational milestones recorded in GitHub:

- `M0`: safe control-plane maintenance
  - `#3037 #3035 #3036 #3033`
- `M1`: trustworthy Runtime front door
  - `#2999 #3019 #3015 #3016 #3018 #3030`
- `M2`: reusable local infra
  - `#3000 #3021 #3022 #3001 #3031 #3020 #3002`
- `M3`: first honest scheduler proof
  - `#3025 #3026 #3038 #3027 #3032 #3042`
- final release proof
  - `#3003 #3004 #3005`

## GitHub trail created in this lane

### Epic coordination

- `#2998` comment chain:
  - gates and block structure
  - cross-repo coordination
  - requirement-to-issue evidence matrix
  - status snapshot
  - first-PR ordering
  - M0→M3 milestone ladder
  - consolidated handoff summary

### Scheduler gate

- `#3042` comment chain:
  - final-wave evidence checklist
  - operational verification runbook
  - minimum artifact contract for the final proof

### Cross-repo dependency sync

Dependencies for the final wave were synchronized in:

- `simplicio-mapper#176`
- `simplicio-dev-cli#113`
- `simplicio-loop#130`
- `simplicio-agent#29`
- `simplicio-agent#97`
- `simplicio-agent#127`
- `simplicio-agent#128`
- `simplicio-agent#133`

## Additional issues opened from real usage

These were opened specifically because the Runtime surfaces used in this lane exposed
real product-contract gaps:

- `#3044` readiness audit should become an official stable contract
- `#3048` compact shell should preserve structured JSON while keeping compact receipts

## Restart point

When work resumes, start from:

1. `#2998` for the overall plan and dependency order
2. `#3042` for the final-wave proof contract
3. `M0` issues first before any new Runtime self-mutation

## Important constraint from this lane

This planning lane did not produce a safe isolated code diff for Runtime itself.
The shared worktree remained mixed/dirty, so GitHub issue work was the authoritative
deliverable of the session.','docs/issues/2998-handoff-2026-07-10-wave-planning.md','a02e700ab836f6837ede1469d003e098939efc845c4f7bdb246d30427a53bb99','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/3437-performance-baseline.md','project_doc','doc://simplicio-runtime/docs/issues/3437-performance-baseline.md','doc: Issue #3437: performance baseline gate','# Issue #3437: performance baseline gate

The checked-in contract is `schemas/performance-baseline-v1.schema.json` and
the implementation is `scripts/perf_baseline_gate.py`.

## Contract

Each case records exactly four scenarios:

| Scenario | Meaning |
| --- | --- |
| `baseline` | workload without runtime or loop orchestration |
| `runtime` | runtime path without loop orchestration |
| `runtime_loop` | runtime path driven by loop orchestration |
| `full_stack` | the complete configured stack, including local LLM/neural-memory components when the command emits them |

Capture performs at least one warmup and five recorded repetitions. The
warmup is discarded from distributions. Latency, CPU time, and sampled RSS are
measured by the harness. Throughput and startup are recorded only when the
workload emits explicit JSON fields. Provider token/cost fields are copied only
from emitted JSON usage; absent values are `null`, never zero or estimated.

If a command, baseline, provider, local model, neural-memory seed, or metric is
unavailable, the report uses `BLOCKED` and/or `null` with a reason. The CI job
keeps that result visible and fails only on an invalid report or a measured
regression. This allows the gate to be installed before a machine-specific real
benchmark fixture and baseline are provisioned without manufacturing evidence.

## Comparison

The comparator uses p95 for latency/startup/CPU/RSS and p50 for throughput. The
default tolerances are 10% regression for latency/startup/CPU/RSS and 5%
throughput drop. A scenario is not considered passing unless both matching
reports have at least five passed samples for each compared metric.

Configure real workload commands with the repository variable
`PERF_BENCHMARK_FIXTURE` and a previously captured report with
`PERF_BASELINE_FILE`. The fixture must pin runtime/loop/model versions and seed
any neural-memory state itself; the gate does not synthesize or infer those
inputs.

The workflow runs unit/integration/property/invariant checks, captures the four
scenario shape, compares distributions, and uploads the raw reports and gate
receipt as artifacts.','docs/issues/3437-performance-baseline.md','91543b1cef63a96ab352452c9d5fdbc8b0c3148965dcee25522f6947602e8a13','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/issues/3532-completion-evidence.md','project_doc','doc://simplicio-runtime/docs/issues/3532-completion-evidence.md','doc: Issue 3532 — runtime completion evidence','# Issue 3532 — runtime completion evidence

The `simplicio completion` command now derives its command names and descriptions from the Runtime command catalogs. Bash, Zsh, Fish, and PowerShell output is deterministic and advertises the `--json` and `--repo` options. JSON output includes the resolved repository, command catalog, and capability catalog.

Validation performed locally against the Runtime checkout:

```text
cargo test --offline --locked --bin simplicio completion_tests -- --nocapture
3 passed; 0 failed

cargo test --offline --locked --test completion_smoke -- --nocapture
2 passed; 0 failed
```

The repository-wide formatter has pre-existing failures outside this change; `git diff --check` is clean. GitHub Actions were not run, per repository policy.','docs/issues/3532-completion-evidence.md','6d8045f0323f1f8b31d03a2af4e4389a14e388badcc9591de61572bfe7575a5d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/JSON_BOUNDARIES.md','project_doc','doc://simplicio-runtime/docs/JSON_BOUNDARIES.md','doc: Runtime JSON boundary inventory','# Runtime JSON boundary inventory

`config/json-boundaries.toml` is the authoritative review inventory for issue #3495. It is intentionally not an allowlist. Every entry records whether a path is an external edge, a historical read-only artifact, or a migration blocker.

The boundary categories are:

- `internal-state`: Runtime-owned persistence, receipts, caches, queues, journals, and indexes. These migrate to HBP, HBI, or typed TOML.
- `external-export`: explicit CLI contracts such as `doctor --json` and `capabilities --json`. These are rendered only at the final edge and are never re-ingested as Runtime truth.
- `dependency`: a serializer dependency that still has call sites to migrate; dependency presence is not permission to persist JSON.
- `historical`: immutable evidence that is not read as active Runtime state and must not receive new records.

Migration PRs must update the inventory status, add compatibility/rollback tests, and keep the entry exact enough for the policy scanner. New JSON usage requires a reviewed boundary entry before it can merge. Until all `migration_required` entries are migrated, the inventory is a progress gate and the Runtime issue remains open.','docs/JSON_BOUNDARIES.md','00c905b85ba7b5a7aefba1bd3a7d27c7b65a94201899ac6e2fc7695a7d48bceb','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/launch-plan.md','project_doc','doc://simplicio-runtime/docs/launch-plan.md','doc: Simplicio Agent — Plano de Lançamento','# Simplicio Agent — Plano de Lançamento

> **Um organismo vivo em loop.** Simplicio não é "mais um CLI de IA" — é um runtime
> determinístico que aprende, edita e prova cada mutação em um ciclo fechado:
> `orientar -> planejar -> executar -> verificar -> aprender`. Cada execução alimenta
> a memória neural e reduz o custo da próxima. O loop nunca para; o organismo só
> fica mais inteligente.

---

## Sumário

1. [Posicionamento](#1-posicionamento)
2. [Público-Alvo](#2-publico-alvo)
3. [Canais de Distribuição](#3-canais-de-distribuicao)
4. [Comparação com Alternativas](#4-comparacao-com-alternativas)
5. [Cronograma de Lançamento](#5-cronograma-de-lancamento)
6. [Métricas de Sucesso](#6-metricas-de-sucesso)
7. [Riscos e Mitigação](#7-riscos-e-mitigacao)
8. [Plano de Comunicação](#8-plano-de-comunicacao)

---

## 1. Posicionamento

### 1.1 A Tese Central

Simplicio é o **substrato governado, auditável e à prova de adulteração para
mutações de IA** — o control plane que qualquer LLM (Claude, Codex, Gemini,
Cursor) atravessa obrigatoriamente. Não compete com modelos de linguagem;
compete com o **plumbing que falta entre o LLM e o código real**.

```
+-------------------------------------------+
|            Host LLM (qualquer)             |
|  Claude . Codex . Gemini . Cursor . Aider |
+--------------------+----------------------+
                     | propoe (contratos mecanicos)
                     v
+-------------------------------------------+
|          Simplicio Runtime (Rust)          |
|  +---------+ +----------+ +------+       |
|  | Orient  | |  Memory  | | Gate |       |
|  | (map)   | | (neural) | |(risco)|      |
|  +---------+ +----------+ +------+       |
|  +---------+ +----------+ +------------+ |
|  |  Edit   | | Validate | | Local LLM  | |
|  |(zero-tk)| | (oracle) | | (56% $0)   | |
|  +---------+ +----------+ +------------+ |
+--------------------+----------------------+
                     | executa (deterministico)
                     v
            +------------------+
            |   Codigo real     |
            |  (repositorio)    |
            +------------------+
```

### 1.2 "Organismo Vivo em Loop" — O Que Significa

| Caracteristica | Explicacao |
|---|---|
| **Aprende** | Toda execucao vira uma trajetoria indexada na memoria neural (SQLite FTS5 + vetor). Amanha o runtime sabe o que decidiu hoje. |
| **Edita com precisao** | `simplicio edit` aplica planos mecanicos com hash SHA-256 — zero tokens de LLM desperdicados em escrita. |
| **Gateia riscos** | Acao classificada como `allow / ask / block` antes de tocar no disco. Checkpoint salvo antes de cada mutacao. |
| **Prova** | Cadeia de evidencia HBP: cada mudanca e verificavel, reproduzivel e vinculada a um receipt. |
| **Economiza** | ~77-82% de economia media de tokens vs. agentes que rediscoverem contexto e rederivam decisoes. |
| **Escala** | 64 -> 128 -> 256 agentes locais em fan-out, sem custo de API. Perfil `low/normal/full`. |

### 1.3 Mensagens-Chave

* **"Pare de pagar para a IA rediscoverir o que ela ja sabe."** — Memoria neural corta a rederivacao de contexto entre sessoes.
* **"Toda mutacao de IA no seu repo e gated, reversivel e provavelmente logada."** — Action Gate + checkpoint + HBP evidence chain.
* **"Um binario. Zero dependencias. Qualquer LLM."** — 3.4 MB, Rust puro, `curl ... | sh`, funciona com Claude Code, Codex, Cursor, Gemini, Copilot.
* **"O loop que fecha. O organismo que aprende."** — O posicionamento central.

### 1.4 Tom e Voz

* **Idiomas:** Ingles (primario), Portugues-BR (secundario, mercado de origem).
* **Visual:** Neon-green on dark, hexagono-S animado, batimento cardiaco no dashboard.
* **Tom:** Tecnico, direto, sem hype vazio. Numeros reais do ledger de savings.
* **Comparacoes:** Honestas e baseadas em benchmarks objetivos (COMPETITIVE_BENCHMARK.md).

---

## 2. Publico-Alvo

| Segmento | Prioridade | Dor | Como Alcancar |
|---|---|---|---|
| **Desenvolvedores solo / indie** | Alta | Assinatura de Claude/Cursor + tokens caros. Querem controle e economia. | GitHub, Hacker News, Reddit r/programming, r/rust, X/Twitter dev community |
| **Startups (2-20 devs)** | Alta | Time pequeno, cada centavo de API pesa. Precisam de auditoria sem burocracia. | Product Hunt, LinkedIn, dev newsletters |
| **Equipes de plataforma** | Media | Governanca de mutacoes de IA em repositorios criticos. | Blog posts tecnicos, talks, white-papers |
| **Usuarios de Claude Code** | Alta | Ja usam agente de IA mas sentem falta de controle, memoria e economia. | MCP plugin ("Simplicio Core"), docs, community |
| **Usuarios de Cursor** | Alta | Pagam $20/mes+ e querem um substrato auditavel por baixo. | MCP plugin, VS Code extension path |
| **Mercado BR** | Media | Founder solo BR, comunidade PHP/JS que precisa de ferramenta de IA acessivel. | Comunidades BR, YouTube, Telegram |

---

## 3. Canais de Distribuicao

### 3.1 Matriz de Canais

| Canal | Status | Prioridade | Publico | Esforco de Manutencao |
|---|---|---|---|---|
| **install.sh (curl pipe)** | Pronto | Critico | Todos | Baixo |
| **GitHub - wesleysimplicio/simplicio** | Pronto | Critico | Devs globais | Medio |
| **PyPI - simplicio-installer** | Pronto | Critico | Pythonistas | Baixo |
| **Docker - simplicio:latest** | Pronto | Alto | DevOps/CI | Baixo |
| **Homebrew - simplicio/tap** | Em progresso | Alto | macOS devs | Medio |
| **npm - @simplicio/installer** | Planejado | Alto | Node.js devs | Medio |
| **Site - simpleti.com.br/simplicio** | Pronto | Alto | Todos (CDN) | Baixo |
| **AUR - simplicio-bin** | Planejado | Medio | Arch Linux | Baixo |
| **Winget / Scoop** | Planejado | Medio | Windows devs | Baixo |
| **Nix / NixOS** | Planejado | Medio | Nix users | Medio |
| **MCP auto-register** | Pronto | Alto | Usuarios de LLM hosts | Zero (built-in) |

### 3.2 Cadeia de Distribuicao (Release Pipeline)

```
Cargo.toml (v1.x.x)
       |
       v
scripts/deploy-release.sh
       |
       +--> PyPI: simplicio-installer (wheel, sem sdist)','docs/launch-plan.md','b5f7278fe039daf0073c1ff2835663c9f493395510e9761c71946ad9d9e75100','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/LOCAL_NEURAL_BENCHMARK.md','project_doc','doc://simplicio-runtime/docs/LOCAL_NEURAL_BENCHMARK.md','doc: Real local LLM + neural-memory benchmark','# Real local LLM + neural-memory benchmark

Run this on a machine with a compiled `simplicio` binary and a local model:

```bash
python3 scripts/measure-local-neural-runtime.py \
  --repo /path/to/repo \
  --task "run the existing test suite and fix the failing test" \
  --runtime-sha "$(git rev-parse HEAD)" \
  --loop-sha "8155d2203f0018b00d842ddea5910271bd85d3c4" \
  --out .simplicio-loop/evidence/local-neural-benchmark.json \
  --trials 3
```

The runner executes both modes:

- `local_cached`: `SIMPLICIO_INPROCESS=1`, KV cache and neural cache enabled;
- `local_uncached`: those switches disabled.

Each trial measures: version, neural-memory status before/after, KV-cache
status before/after, repository map, neural-memory query, local `simplicio run`,
wall-clock, child CPU, process-tree RSS, exit status, explicit token usage,
cache hits, model/backend fields, evidence paths, and raw stdout/stderr.

A result is valid only when the `run_local` receipt reports a local backend.
The script does not convert missing token fields into zero and does not claim
that a cache was used merely because it was enabled. Compare modes only when
the objective task result is equivalent.','docs/LOCAL_NEURAL_BENCHMARK.md','a699f505c1ecba7456bd49c72d7559a758e659504cf8b1708dfd3fb4169c6c60','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/LOOP_EXECUTION.md','project_doc','doc://simplicio-runtime/docs/LOOP_EXECUTION.md','doc: `simplicio.loop-execution/v1` in Runtime','# `simplicio.loop-execution/v1` in Runtime

Runtime consumes the contract published by Simplicio Loop at
`contracts/loop-execution/v1/schema.json` (loop commit
`8155d2203f0018b00d842ddea5910271bd85d3c4`). Runtime does not reinterpret the
state files or infer success from a subprocess exit code.

An E2E run publishes `.simplicio-loop/loop-execution.json`. The receipt binds the
run to one workspace and one ordered chain:

```text
simplicio-loop 3.38.2
  -> simplicio-mapper 0.24.2
  -> simplicio-dev-cli 0.16.3
  -> simplicio-runtime 3.5.2
```

The receipt must include the loop origin and commit, a path-safe `run_id`, the
canonical workspace, the five required loop artifacts (scratchpad, journal,
anchor, watcher challenge, watcher state), a run-bound mapper artifact and
dev-cli receipt, and a final `verified` result. Paths are resolved beneath the
run directory; a path escape, stale watcher challenge, mismatched run id,
missing version/origin, invalid artifact, or fallback marks the result
`FAIL`. An absent receipt is `UNVERIFIED`.

Inspect the result offline:

```sh
simplicio loop-execution --repo . --json
simplicio ecosystem doctor --repo . --json
```

`ecosystem doctor --json` exposes the same decision under `loop_execution`,
including status, run id, chain, versions, and errors. The dedicated command
returns non-zero unless the result is `VERIFIED`.

The local neural benchmark invokes this gate for every repetition and emits
`benchmark_status: VERIFIED` only when every repetition has a verified loop,
mapper, dev-cli, and runtime chain. Provider tokens and cost remain absent
unless the runtime/provider emitted measured values.','docs/LOOP_EXECUTION.md','4957a344e1aaa69bb558533c51e0cfb7ca484bbc164c5141dffef1e746e7e8fc','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/MCP_CLIENT_ORIENTATION.md','project_doc','doc://simplicio-runtime/docs/MCP_CLIENT_ORIENTATION.md','doc: Simplicio MCP — Client Orientation','# Simplicio MCP — Client Orientation

Give this file to any MCP-capable LLM (Claude, Codex, Cursor, Copilot, Gemini,
gateway bots) connected to the Simplicio MCP server. It tells the client **when**
to reach for each Simplicio tool and **why** (token, latency, evidence). The whole
point: Simplicio does the cheap deterministic work so the model spends tokens only
on reasoning.

## Registration

`.mcp.json` registers the server as:

```json
{
  "mcpServers": {
    "simplicio": {
      "command": "simplicio",
      "args": ["serve", "--mcp", "--stdio"]
    }
  }
}
```

The `simplicio` binary must be on `PATH` (canonical: `~/.local/bin/simplicio`).
Verify the server is alive:

```
printf ''{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'' | simplicio serve --mcp --stdio
```

## The core loop — run the cheap step BEFORE the expensive one

For **every** task in a Simplicio repo, follow this order. Each step replaces
something the model would otherwise pay LLM tokens to do.

1. **Orient → `simplicio_map`** before raw-reading files.
2. **Recall → `simplicio_memory`** before re-deriving any prior decision/fact.
3. **Navigate → `simplicio_search` / `simplicio_symbol` / `simplicio_read`**
   before dumping whole files into context.
4. **Edit → `simplicio_edit`** instead of hand-writing a decided change.
5. **Gate → `simplicio_gate`** before any mutation/destructive action.
6. **Validate → `simplicio_validate`** before declaring anything done.
7. **Execute the spine → `simplicio_run`** when you want the gated
   action-bridge + evidence ledger to carry out a task.
8. **Anything else → `simplicio_exec`** for the rest of the CLI surface.

## When to trigger each tool (imperative)

### `simplicio_map`
- TRIGGER: at the **start of any task** in an unfamiliar or large repo, before
  reading source files.
- WHY: returns a compressed orientation map of the repo. Replaces dozens of raw
  file reads — large token savings and lower latency. Raw-Read only the few files
  the map points at; never bulk-read.

### `simplicio_memory`
- TRIGGER: before re-discovering a decision, convention, past bug, or design
  rationale — i.e. any "why is it like this / what did we decide" question.
- WHY: pulls prior context from the neural memory (FTS + vector) with a token
  budget. Re-deriving known facts from source is the expensive path; recall is
  near-free.

### `simplicio_search`
- TRIGGER: when you need to locate a symbol by name across the codebase.
- WHY: queries the CodeGraph index (id/name/kind/file/line) instead of grepping +
  reading. Run `simplicio index build` (via `simplicio_exec`) once first.

### `simplicio_symbol`
- TRIGGER: when you have a specific symbol and need its definition AND its
  callers/references.
- WHY: find-symbol + find-references in one call (~76% token savings vs reading
  every referencing file). Use it before refactors to scope blast radius.

### `simplicio_read`
- TRIGGER: when you need a file''s API surface (functions, types, signatures) but
  not its full body.
- WHY: returns a signature-level extract instead of the whole file. Pair with
  `simplicio_symbol`/`simplicio_search` to navigate. Sandboxed to the workspace.

### `simplicio_edit`
- TRIGGER: the moment you have **decided** a mechanical change (replace, insert,
  delete lines, append/prepend). Do NOT hand-write the file body.
- WHY: a deterministic mechanical writer applies the plan — **zero LLM output
  tokens for file bodies**, and the plan can be hash-gated. Hand-writing a
  decided change is wasted spend.
- Plan shape: `{"file":"path","operations":[{"op":"replace_all","find":"…","with":"…"}]}`.
  Ops: `replace`/`replace_all`, `insert_before`/`insert_after`,
  `replace_line`/`delete_line`, `append`/`prepend`.

### `simplicio_gate`
- TRIGGER: **before** any mutating or destructive action (writes outside an edit
  plan, shell side effects, deploys, deletes).
- WHY: classifies the action''s risk (ask/auto/safe) and enforces the hardline
  blocklist. Gating before mutation is what makes chat-initiated actions safe and
  auditable.

### `simplicio_validate`
- TRIGGER: **before declaring a task done**, and after applying edits.
- WHY: runs the deterministic validation pipeline on the repo. "Compiles" is not
  "delivered" — validation is the evidence that it actually runs. Findings feed
  the next `simplicio_edit` plan.

### `simplicio_run`
- TRIGGER: when you want Simplicio to **carry out** a task end-to-end through the
  spine (gate → action-bridge → evidence ledger), not just inspect.
- WHY: returns a typed result with `status`, `trace_id`, and receipts on the HBP
  evidence chain. Use `dry_run: true` to classify+gate without executing; set
  `mode` to override the gate (ask|auto|safe).

### `simplicio_exec`
- TRIGGER: for any Simplicio subcommand not covered above (e.g. `doctor`,
  `savings report`, `skills`, `precedent`, `index build`, `sprint`, `plan`,
  `advise`).
- WHY: exposes the full CLI surface through one gated tool. No shell, no
  metacharacters; destructive/networked subcommands (`serve`, `login`, `publish`,
  `deploy`, `release`, `reset`, `mcp`) are blocked over MCP.

## Anti-patterns (do NOT do these)
- Bulk-reading source files → use `simplicio_map` then targeted reads.
- Re-deriving a known decision → use `simplicio_memory`.
- Hand-writing a decided edit into the file → use `simplicio_edit`.
- Mutating without a risk check → use `simplicio_gate` (or `simplicio_run`).
- Declaring "done" off a successful compile → run `simplicio_validate`.

## Proposed tool-description upgrades

The current `tools/list` descriptions are **already strong triggers** — most lead
with the action and the reason (e.g. "run before raw-reading files", "instead of
re-deriving", "zero LLM tokens for file bodies", "before mutating"). They name the
*when* and the *why*, which is exactly what orients a client LLM. No Rust change is
required for correctness.

If a future polish pass is desired, these one-liners sharpen the trigger verb and
keep the','docs/MCP_CLIENT_ORIENTATION.md','2b8f6fd7796bad6b14c5a5f344f7816561094cfb49b7071319eaf36ec10083a5','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/MCP_LATENCY.md','project_doc','doc://simplicio-runtime/docs/MCP_LATENCY.md','doc: MCP Latency — cold self-exec CLI vs a persistent `serve --mcp --stdio` connection','# MCP Latency — cold self-exec CLI vs a persistent `serve --mcp --stdio` connection

Tracks the latency win from moving builtin MCP tools off the per-call
self-exec pattern (`Command::new(exe).args(&argv).output()`, one fresh
`simplicio` process per `tools/call`) onto an in-process fast path served
by one long-lived `simplicio serve --mcp --stdio` connection.

- `simplicio_gate` and `simplicio_run` went in-process first (#2983/#2501,
  PR #2985).
- `simplicio_map`, `simplicio_memory`, `simplicio_edit`, and
  `simplicio_validate` go in-process in this change (#2986), plus two new
  in-process-only tools, `simplicio_checkpoint` and `simplicio_savings`.

Every in-process handler calls the *exact same function* the CLI arm it used
to self-exec calls — see the `#2986` doc comments in `src/mcp_serve.rs` and
the extracted `*_body`/`*_cached`/`(String, Result<..>)`-returning helpers in
`src/main_parts/chunk_01.rs`, `chunk_02.rs`, `chunk_16.rs`, and
`src/action_bridge.rs` — so this is a latency change only: the JSON body a
tool call returns does not change, only how it gets produced (no subprocess
spawn, no argv round-trip through the OS).

## How to measure

```bash
# release binary strongly preferred — debug builds are 5-10x slower and
# not representative of what a real host observes
cargo build --release --locked
scripts/bench-mcp-latency.sh target/release/simplicio [samples]
```

`samples` is optional (default 20 per hop). The script:

1. Builds a throwaway scratch git repo under `$TMPDIR` (never touches the
   real working tree).
2. **Cold CLI pass** — for each of the six loop commands below, spawns a
   fresh `simplicio <argv>` process per sample and times the wall-clock
   round trip (the pre-#2983/#2986 self-exec pattern every builtin MCP tool
   used to fall back to, still what `simplicio_exec`/the non-migrated tool
   catalogue does today).
3. **Persistent MCP pass** — opens **one** `simplicio serve --mcp --stdio`
   connection (a bash `coproc`, matching how a real MCP host holds the pipe
   open for the session) and times `tools/call` round trips for the same six
   operations over that single connection.
4. Prints one `simplicio.mcp-latency-sample` JSON object per line (per hop,
   per path) to stdout, and a `p50`/`saved%` summary table to stderr.

The six hops benchmarked — the deterministic loop''s hot path (see
`CLAUDE.md` § *Token-saving flow*):

| hop | CLI form | MCP tool |
|---|---|---|
| `gate_classify` | `gate classify --action "<a>" --repo <r> --json` | `simplicio_gate` |
| `runtime_map` | `runtime map --repo <r> --for-llm toon` | `simplicio_map` |
| `memory_query` | `memory query "<q>" --repo <r> --json` | `simplicio_memory` |
| `edit` | `edit ''<plan>'' --json` | `simplicio_edit` |
| `checkpoint_record` | `checkpoint save --repo <r> --json` | `simplicio_checkpoint` (`action: record`) |
| `savings_ledger_append` | `savings record --spent N --baseline N --repo <r> --json` | `simplicio_savings` |

## Where to publish the table

Paste the script''s stderr summary table (or the raw JSONL, aggregated with
`jq -s`) into this section, replacing the placeholder below, and note the
binary (`--release`, commit SHA) and machine it was measured on. Per the
project''s savings-report discipline (`docs/SAVINGS_EVENT_SPEC.md`), a number
only belongs here with `proof_kind: measured` from a real run — never a
guess.

## Results

**Status: pending measurement.**

No numbers are published yet. This session could not build a `--release`
binary in its container (disk-constrained sandbox; the standing instruction
for this task was explicitly *not* to run `cargo build --release` here) — so
there is no `measured` figure to report, and per the project''s no-fabrication
rule (`CLAUDE.md` § *Token savings report*, `docs/SAVINGS_EVENT_SPEC.md`)
this section stays a placeholder rather than an invented one.

`scripts/bench-mcp-latency.sh` itself was smoke-tested end-to-end against the
existing **debug** build at `target/debug/simplicio` (produced incidentally
by `cargo test`) to confirm the coproc/JSON-RPC harness, the six hops, and
the percentile/table math all work — debug-binary numbers are not
representative of production latency (unoptimized, 5-10x slower binary
startup) and are intentionally not reproduced here. The first real run
against a `--release` binary should replace this whole section with:

```
simplicio-runtime MCP latency bench: <path> (<N> samples/hop)
binary: <release, commit SHA>
machine: <OS/CPU>
date: <YYYY-MM-DD>

hop                      cold_cli_p50      mcp_p50    saved_%
------------------------------------------------------------
gate_classify                    ??ms         ??ms         ??%
runtime_map                      ??ms         ??ms         ??%
memory_query                     ??ms         ??ms         ??%
edit                             ??ms         ??ms         ??%
checkpoint_record                ??ms         ??ms         ??%
savings_ledger_append            ??ms         ??ms         ??%
```

Expect the largest relative wins on the cheapest operations (`gate_classify`,
`checkpoint_record`, `savings_ledger_append` — pure in-memory/small-file-IO
work where the self-exec process-spawn overhead was most of the cost) and
smaller relative wins on operations that already do substantial real IO
regardless of path (`runtime_map`''s repo survey, `memory_query`''s SQLite FTS
scan, `edit`''s file write) — the process-spawn cost removed is the same in
absolute terms either way, it is just a smaller fraction of a slower
operation''s total time.','docs/MCP_LATENCY.md','20a88350ef0ae203f25e99916cb3ff29d205802847640f89baade977bc35c3bf','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/MCP_SERVER_MODE.md','project_doc','doc://simplicio-runtime/docs/MCP_SERVER_MODE.md','doc: MCP / Server Mode — Design Specification','# MCP / Server Mode — Design Specification

- **Issue:** [#24 — feat: Define MCP/server mode](https://github.com/wesleysimplicio/simplicio-runtime/issues/24)
- **Milestone:** M5 - Integrations
- **Status:** Designed. Implemented for `mcp`, `stdio`, and `local-http` modes
  (`status: "implemented"` in `service_spec_json`); other modes remain
  `design-ready` contracts. See the honest status field in
  `src/main_parts/chunk_10.rs` (`service_spec_json`).
- **Owner:** runtime-first (single `simplicio` binary)

## 1. Goal

Allow tools — IDEs, agents, and assistants — to talk to the Simplicio runtime
as a **long-lived local service**, not only as short-lived CLI invocations.
The CLI and the server mode must share the **same core decision engine**
(`build_decision`), so behavior is identical whether a task arrives via the
terminal or over the wire.

## 2. Interfaces (three transports, one engine)

| Interface | Entrypoint | Framing | Status |
|---|---|---|---|
| `mcp` | `simplicio serve --mcp --stdio` | JSON-RPC over stdio (Model Context Protocol) | implemented |
| `stdio` | `simplicio serve --stdio` | newline-delimited JSON requests/responses | implemented |
| `local-http` | `simplicio serve --http` | HTTP/1.1 on `127.0.0.1:<port>` | implemented |

All three are thin plugin surfaces. The `mcp` server advertises tools
(`simplicio.map`, `simplicio.plan`, `simplicio.run`, `simplicio.dev_cli`,
`simplicio.sprint`, `simplicio.edit`, `simplicio.evidence.show`,
`simplicio.status`, `simplicio.chat`, `simplicio.computer_use`,
`simplicio.browser_cdp`, `simplicio.browser_dialog`) that map 1:1 onto the
core CLI commands.

### Prototype-First artifact boundary

The Runtime-owned `simplicio_prototype_artifact_write` and
`simplicio_prototype_artifact_read` tools persist
`simplicio.prototype-artifact/v1` artifacts only under
`.simplicio-loop/artifacts/prototype-first/`. Artifact IDs are bounded safe ASCII
identifiers; traversal, symlink escapes, oversized payloads, and conflicting
rewrites are rejected. Writes require a valid
`simplicio.effect-transaction/v1` transaction, while reads remain read-only.
Both tools return typed receipts or `simplicio.prototype-artifact-error/v1`
errors. Code and other consumers must use this MCP boundary rather than a
provider-local filesystem fallback.

## 3. Request / response schema

Service descriptor schema: **`simplicio.service/v1`** (emitted by
`service_spec_json`). Per-tool result schemas reuse the existing runtime
contracts:

- `map` → `simplicio.map-result/v1`
- `plan` → `simplicio.decision/v1`
- `run` → `simplicio.run-result/v1`
- `dev_cli` → `simplicio.dev-result/v1`
- `sprint` → `simplicio.sprint-result/v1`
- `edit` → `simplicio.mechanical-edit-result/v1`
- `chat` → `simplicio.chat/v1` ‖ OpenAI `chat.completion` ‖ Anthropic `message`
- `evidence` → `simplicio.evidence-summary/v1`
- `status` → `simplicio.status/v1`
- `computer_use` → `simplicio.computer-use/v1`
- `browser_cdp` → `simplicio.browser-cdp/v1`
- `browser_dialog` → `simplicio.browser-dialog/v1`

The `local-http` route table (see `serve_local_http` in
`src/main_parts/chunk_08.rs`):

```
GET  /healthz                                  # no auth, reports real version
GET  /v1/status                                # live status snapshot
GET  /v1/events?run=latest&tail=50             # event stream (tail)
POST /v1/map                                   # runtime map
POST /v1/validate                              # validation plan
POST /v1/gate                                  # mutation gate classify
POST /v1/cron/jobs/{id}/trigger               # fire cron job immediately (#2333)
POST /shutdown                                 # token-required graceful stop
```

## 4. Event streaming

- Schema: **`simplicio.runtime-event/v1`**.
- Transports: MCP notifications, HTTP event stream (`GET /v1/events`), and
  stdio JSON lines.
- Events are drained before shutdown (see `shutdown.drains_events` in the
  service spec), so long-running tasks report completion before the accept
  loop exits.

## 5. Auth boundary (localhost)

Explicit security assumptions for the local server (`local-http`):

- **Bind:** `127.0.0.1` only. `serve_http` rejects non-loopback peers at the
  socket layer with `HTTP/1.1 403 Forbidden` before reading any bytes.
- **Token:** a per-session bearer token (`http_session_token`) is generated per
  server start, written to `runtime_home(config)/serve-http-token` with `0600`
  permissions (unix), and echoed on startup.
- **Unauthenticated surface:** only `GET /healthz` is open (returns
  `{"status":"ok","version":"…"}`). Every other route requires
  `Authorization: Bearer <token>`; missing/invalid token → `401`.
- **Shutdown:** `POST /shutdown` is token-required by design and triggers a
  graceful drain + loop exit.
- **Browser clients:** any web client must send the token header (CSRF guard);
  failures reject with an unauthorized event and perform **no** repo mutation.
- **Scope:** the token and socket never leave the machine. This is a local
  trust boundary, not a network-facing service — do **not** expose the port to
  non-loopback interfaces.

## 6. Health & shutdown endpoints

- `GET /healthz` → `200 {"status":"ok","version":"<CARGO_PKG_VERSION>"}`.
- `POST /shutdown` → `200 {"status":"shutting-down"}` then the accept loop
  breaks and the process exits after draining events.

## 7. Single core decision engine

`service_spec_json` proves the invariant requested by the acceptance criteria:
the `core_decision_engine` block records `build_decision` as the shared
function and lists both the CLI commands and the server request names that
route through it. The unit test `server_spec_uses_core_decision_engine`
(`src/main_tests_parts/test_part_02.rs`) asserts the spec contains
`"schema":"simplicio.service/v1"` and the `/healthz` + `/shutdown` routes,
locking the contract.

## 8. Service lifecycle (control plane)

`service_control_json` (`simplicio.service-control/v1`) describes the daemon:
opt-in (`simplicio serv','docs/MCP_SERVER_MODE.md','e3dc25dd81942cbeb970a1ab4ff14e51a03de5f81fa844cea1c9c6438bf50405','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/MCP_SIMPLICIO_RUN_V1.md','project_doc','doc://simplicio-runtime/docs/MCP_SIMPLICIO_RUN_V1.md','doc: simplicio.run/v1','# simplicio.run/v1

The unified MCP entry point accepts:

~~~json
{
  "task": "string, required",
  "workspace": "path, optional",
  "tenant": "string, optional",
  "mode": "plan | exec | full, default full",
  "allow_remote": false
}
~~~

The runtime validates the request before dispatch. Blank tasks and blank optional
identifiers are rejected. The allow_remote flag defaults to false.

Every result uses simplicio.run-result/v1:

~~~json
{
  "status": "done | partial | blocked",
  "patch": "unified diff | null",
  "files_changed": ["path"],
  "trace_id": "string",
  "cost": {"tokens": 0, "usd": 0.0},
  "latency_ms": 0,
  "receipts": ["path-or-hash"]
}
~~~

Plan must be non-mutating. Exec may apply the approved plan. Full is the default
end-to-end path. Remote access remains opt-in and must be separately authorized
by the host policy.','docs/MCP_SIMPLICIO_RUN_V1.md','214d0ad2d5908f556fe9e3d41fa9244e8dc16cf745cd3a9843e952868c3b2ea1','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/MECHANICAL_CONTRACTS.md','project_doc','doc://simplicio-runtime/docs/MECHANICAL_CONTRACTS.md','doc: Mechanical contracts registry (issue #347)','# Mechanical contracts registry (issue #347)

Simplicio''s edit safety comes from **mechanical contracts**: the LLM proposes
compact intent, the runtime applies it deterministically behind strong gates, and
every mutation is verifiable (sha256 + oracle). This file is the registry and
versioning policy for those contracts.

## Versioning policy

- A contract is identified by `simplicio.<name>/vN` (e.g. `simplicio.mechanical-edit/v1`).
- The JSON Schema lives in `schemas/<name>.schema.json` with a stable `$id` under
  `https://schemas.simplicio.dev/runtime/`.
- Breaking changes bump `vN`; additive, backward-compatible fields keep the
  version and are marked optional.
- A contract is **implemented** only when the runtime both *accepts* it and
  *enforces* its gate with recorded evidence; otherwise it is **planned**.

## Registry

| contract | schema | status | gate |
|---|---|---|---|
| `simplicio.mechanical-edit/v1` | `schemas/mechanical-edit.schema.json` | **implemented** | anchored ops; `find` must be an exact substring; sha256-verified write |
| `simplicio.test-gated-edit/v1` | `schemas/test-gated-edit.schema.json` | **implemented** | acceptance test (`SIMPLICIO_TEST_CMD`) must exit 0; iterate-until-green up to `max_cycles`; revert on fail |
| `simplicio.mechanical-refactor/v1` | `schemas/mechanical-refactor.schema.json` | **implemented** (proposal) | multi-file coordinated edits, dependency-aware; gate: all affected tests green |
| `simplicio.evidence-bundle/v1` | `schemas/evidence-bundle.schema.json` | **implemented** (proposal) | package tests/screenshots/traces/token-ledger; gate: all items present |
| `simplicio.pr-handoff/v1` | `schemas/pr-handoff.schema.json` | **implemented** (proposal) | commit + PR description + evidence; gate: policy-approved |
| `simplicio.architecture-proposal/v1` | _pending_ | planned | impact analysis + stronger review gate |

All four advanced contracts are emitted by `simplicio contracts-advanced propose
--type <test-gated-edit|mechanical-refactor|evidence-bundle|pr-handoff> --json`
(each carries `schema`, `proposed_at`, `old_hash`, `new_hash`, `status`, and the
type-specific gate fields above). `mechanical-refactor`, `evidence-bundle`, and
`pr-handoff` currently land the **proposal** stage; their full apply/gate
enforcement is a follow-up slice.

## `test-gated-edit/v1` — how it runs today

The runtime already enforces this contract through the native `dev-cli` verify
loop. Set the acceptance command and the loop applies a candidate, runs the
oracle, and **commits only on green**:

```bash
# m.py has the stub; t.py is the oracle (exit 0 == pass)
SIMPLICIO_TEST_CMD="python3 t.py" \
SIMPLICIO_MAX_CYCLES=3 SIMPLICIO_FANOUT_CAP=2 \
  simplicio dev-cli "Implement gcd(a,b) using the Euclidean algorithm." \
    --repo "$DIR" --target m.py --json
```

Behaviour (verified, Battery F in `docs/COMPETITIVE_BENCHMARK.md`):

- candidate fails the oracle → `verify:"failed"`, file reverted, next cycle with
  failure feedback (**the runtime refuses to ship broken code**);
- a candidate passes → `verify:"passed"`, `executed:true`, sha256 before/after
  recorded, loop stops;
- no test command configured → `verify:"skipped"` (plain mechanical-edit apply).

All of the above runs on a local in-process model at **`paid_tokens_used:false`**
($0) or on a configured remote backend, per policy.

## Next slices (#347)

1. ✅ contract schema registry + versioning (this doc) and `test-gated-edit/v1` schema.
2. multi-file `mechanical-refactor/v1` with dependency awareness.
3. `evidence-bundle/v1` + `pr-handoff/v1`.
4. AST-aware / semantic-diff gate primitives beyond substring.
5. TUI visualization of proposed vs applied diff with gate results.','docs/MECHANICAL_CONTRACTS.md','8060799eb9fcad5eaeb5d133c716a2a2208c99898fd35547f13a24db10929d04','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/mobile/DISPATCH_ARCHITECTURE.md','project_doc','doc://simplicio-runtime/docs/mobile/DISPATCH_ARCHITECTURE.md','doc: Simplicio Mobile Dispatch Architecture','# Simplicio Mobile Dispatch Architecture

**Issue:** #1265  
**Parent epic:** #1264  
**Status:** Draft  
**Related:** #1244 (Desktop App), #1247, #1248, #1249, #1250, #1254, #1258

---

## Guiding principle

> **Mobile is NOT the executor. The desktop runtime is.**

The mobile device is a **command surface** — it captures user intent, authenticates the request, and receives result events. Every mutation (file edits, shell commands, deployments) happens on the desktop/server runtime. The phone never directly executes code, writes files, or calls external APIs.

---

## Responsibility split

| Layer | Role | What it NEVER does |
|---|---|---|
| **Mobile app** | Express intent, approve risky actions, receive events | Execute code, write files, call APIs |
| **Desktop gateway** | Validate device/session, enforce policy, route to runtime | Execute business logic directly |
| **Simplicio runtime** | Map/plan/execute, emit events, store evidence | Trust commands without gateway validation |

---

## Required flows

### Flow 1 — Happy path (low-risk command)

```
Phone                Desktop Gateway           Runtime
  |                       |                       |
  |-- DispatchCommand ---> |                       |
  |   (ReadOnly/SafeWrite) |                       |
  |                       |-- policy.check() ----> |
  |                       |   ok (auto-approve)    |
  |                       |-- route to runtime --> |
  |                       |                       |-- map/execute
  |                       |                       |-- emit events
  |<-- DispatchEvent ------+<--- events -----------|
  |   (Queued, Running,   |                       |
  |    Completed)          |                       |
  |                       |                       |-- HBP evidence
```

### Flow 2 — High-risk command (requires approval)

```
Phone                Desktop Gateway           Runtime
  |                       |                       |
  |-- DispatchCommand ---> |                       |
  |   (Deploy/ShellExec)  |                       |
  |                       |-- policy.check() ok   |
  |                       |-- risk >= High        |
  |<-- ApprovalRequest ---|                       |
  |   (summary, deadline) |                       |
  |                       |                       |
  |   [User sees prompt]  |                       |
  |                       |                       |
  |-- ApprovalResponse --> |                       |
  |   (approved=true)     |                       |
  |                       |-- route to runtime --> |
  |<-- DispatchEvent -----|<--- events ------------|
  |   (Running, Completed)|                       |
```

### Flow 3 — Denied by policy

```
Phone                Desktop Gateway
  |                       |
  |-- DispatchCommand ---> |
  |   (class in deny_list)|
  |                       |-- policy.check() FAIL
  |<-- DispatchEvent ------|
  |   (Denied, reason)    |
```

### Flow 4 — User denies risky command

```
Phone                Desktop Gateway
  |                       |
  |<-- ApprovalRequest ---|
  |-- ApprovalResponse --> |
  |   (approved=false)    |
  |<-- DispatchEvent ------|
  |   (Denied, "denied by user")
```

### Flow 5 — Offline behavior

When the phone has no active connection to the desktop gateway:

- `OfflineBehavior::Queue` — commands are held in a durable queue on the device and replayed when the gateway reconnects.
- `OfflineBehavior::Drop` — commands that cannot be delivered immediately are silently dropped (for time-sensitive read-only ops).

The gateway chooses the policy; the mobile client respects it.

---

## Command/event schemas

### DispatchCommand (`simplicio.mobile.dispatch-command/v1`)

```json
{
  "schema": "simplicio.mobile.dispatch-command/v1",
  "command_id": "01J9ABCDEFGH1234",
  "device_id": "dev-iphone16pro-abc123",
  "session_token": "sess-xyz",
  "class": "code_edit",
  "intent": "run cargo test and fix failing unit tests",
  "payload": {
    "repo": "/home/user/myproject",
    "test_filter": "test_dispatch"
  },
  "created_at_ms": 1718500000000,
  "hmac_hex": "a1b2c3d4..."
}
```

### DispatchEvent (`simplicio.mobile.dispatch-event/v1`)

```json
{
  "schema": "simplicio.mobile.dispatch-event/v1",
  "event_id": "evt-001",
  "command_id": "01J9ABCDEFGH1234",
  "device_id": "dev-iphone16pro-abc123",
  "kind": "completed",
  "payload": {
    "summary": "All 23 tests pass",
    "tokens_saved": 4200
  },
  "emitted_at_ms": 1718500045000
}
```

### ApprovalRequest (`simplicio.mobile.approval-request/v1`)

```json
{
  "schema": "simplicio.mobile.approval-request/v1",
  "request_id": "req-01J9ABCDEFGH1234",
  "command_id": "01J9ABCDEFGH1234",
  "device_id": "dev-iphone16pro-abc123",
  "risk": "critical",
  "summary": "Deploy v0.9.3 to production",
  "intent": "run ./scripts/release.sh --version 0.9.3 --push",
  "deadline_secs": 1718500300
}
```

### DispatchEvidence (`simplicio.mobile.dispatch-evidence/v1`)

```json
{
  "schema": "simplicio.mobile.dispatch-evidence/v1",
  "entry_id": "ev-001",
  "command_id": "01J9ABCDEFGH1234",
  "device_id": "dev-iphone16pro-abc123",
  "class": "code_edit",
  "intent": "run cargo test and fix failing unit tests",
  "outcome": "completed",
  "tokens_saved": 4200,
  "timestamp_secs": 1718500045,
  "checkpoint_id": "ckpt-abc"
}
```

---

## Trust and pairing model

1. **Pairing ceremony** — the user pairs a phone with the desktop app via a QR code or PIN. The desktop gateway stores the device''s public key fingerprint and assigns `trusted=true` only after the user confirms.
2. **Session tokens** — every command carries a session token. The gateway verifies the token hash, device ID, and HMAC before accepting any command.
3. **Entitlements** — each device is granted a set of `CommandClass` values. A device paired for read-only queries cannot dispatch `Deploy` commands even if the session is valid.
4. **Revocation** — the desktop user can revoke any device from the gate','docs/mobile/DISPATCH_ARCHITECTURE.md','d3f5a876877a96ef103f363a82dc90a9cb6b3b8983b17c58d1b5a3972d62a051','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/NON_RUST_INVENTORY.md','project_doc','doc://simplicio-runtime/docs/NON_RUST_INVENTORY.md','doc: Non-Rust Inventory — Ownership and Quarantine Matrix','# Non-Rust Inventory — Ownership and Quarantine Matrix

Date: 2026-06-16
Related: #1540, #1498, #1499, #1500

## Summary counts (from audit)
- Rust: 733 files (canonical runtime, always owned)
- Python: 521 files
- JS/TS: 532 files
- Shell: 50 files
- PowerShell: 11 files

## Classification scheme
| Class | Meaning | CI requirement |
|---|---|---|
| runtime_path | Active runtime dependency; must have owner + smoke test | Owner + smoke required |
| fixture | Test fixture; read-only reference | No smoke needed |
| reference | External clone/vendor reference | No smoke; mark as read-only |
| quarantine | Potentially dead; needs review before use | Tagged; CI warns |
| retire | Dead code confirmed; can be deleted | Deletion PR required |

## Python files (521)
| Group | Classification | Owner | Simplicio equivalent |
|---|---|---|---|
| agent/**/*.py | quarantine | runtime team | Rust agents in agent_store.rs |
| tools/**/*.py | quarantine | runtime team | Rust tools in src/ |
| plugins/**/*.py | quarantine | runtime team | Rust skills in src/skill_*.rs |
| scripts/*.py | fixture | build team | scripts/*.sh or cargo commands |
| simplicio-cli adapters | runtime_path | adapter team | simplicio-py binary |

## JS/TS files (532)
| Group | Classification | Owner | Notes |
|---|---|---|---|
| tui/**/*.js | quarantine | TUI team | TUI is now Rust (tui_app.rs) |
| site/** | reference | docs team | Submodule; not runtime |
| packaging/** | runtime_path | build team | Build scripts; needs smoke |
| apps/moneyprinter/** | reference | external | External app reference |

## Shell files (50)
| Group | Classification | Owner | Notes |
|---|---|---|---|
| scripts/bump-version.sh | runtime_path | build team | Used by release flow |
| install.sh | runtime_path | build team | Primary install script |
| hooks/pre-commit | runtime_path | governance team | Git hook; has smoke via gate |
| .codex/hooks/* | quarantine | governance team | Codex hooks; review needed |
| scripts/* (other) | fixture | build team | Various build helpers |

## PowerShell files (11)
| Group | Classification | Owner | Notes |
|---|---|---|---|
| .claude/hooks/*.ps1 | runtime_path | session team | Session hooks (orient-gate etc.) |
| scripts/*.ps1 | quarantine | build team | Windows-specific; audit needed |

## CI enforcement rule

Any new non-Rust script added to runtime_path requires:
1. Owner field in this matrix
2. Simplicio equivalent command or explicit "no-equiv" justification
3. Smoke test (can be minimal: script exits 0 on --help)

Scripts added to quarantine/retire need a tracking issue before deletion.','docs/NON_RUST_INVENTORY.md','b78f050513adab173dbfea0fce1118cf2a7822251638775884c701bf7a068d37','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/observability/STATUS_WATCH.md','project_doc','doc://simplicio-runtime/docs/observability/STATUS_WATCH.md','doc: `simplicio status --watch` — Live Dashboard Spec','# `simplicio status --watch` — Live Dashboard Spec

Issue: #2036

## Overview

`simplicio status --watch` streams a live TUI dashboard that refreshes at a
configurable interval, giving operators a real-time view of the runtime state
without polling manually.

## Existing Groundwork

`src/main.rs` already carries the structural scaffolding:

- `StatusConfig.watch: bool` (line ~1170)
- `StatusConfig.status_interval_ms: u64` (default 1 000 ms, line ~1175)
- `StatusConfig.status_samples: Option<usize>` (optional auto-stop, line ~1176)

What is missing is the rendering loop that reads those fields and drives the
terminal.

## CLI Surface

```
simplicio status [--watch] [--interval <ms>] [--samples <n>] [--json]
```

| Flag | Default | Description |
|---|---|---|
| `--watch` | off | Enable continuous refresh |
| `--interval <ms>` | 1 000 | Refresh period in milliseconds |
| `--samples <n>` | ∞ | Stop after N samples (useful for scripting) |
| `--json` | off | Emit NDJSON lines instead of TUI |

## Dashboard Panels (TUI mode)

```
┌─ simplicio status ────────────────────────────────────────────┐
│  Runtime   v1.1.0  |  uptime 3h 42m  |  profile: normal      │
├───────────────────────────────────────────────────────────────┤
│  Agents   active 12 / 128  |  queued 47  |  idle 116          │
│  Tasks    running 5  |  pending 23  |  done 891  |  failed 2  │
│  Memory   neural 876 items  |  vector ready  |  cache 41 MB   │
│  LLM      local Qwen3.5-4B Q4_K_M  |  tok/s 42  |  queue depth 3    │
│  HBP      chain len 12 441  |  last append 0.3 s ago          │
│  Gate     ask  |  last decision ALLOW (cp tar/build.sh)       │
└───────────────────────────────────────────────────────────────┘
  q quit   r reset counters   p pause   ? help
```

## NDJSON Schema (`--json`)

Each tick emits one line matching `simplicio.queue-status/v1` extended:

```json
{
  "schema": "simplicio.runtime-status/v1",
  "ts": "<ISO-8601>",
  "runtime_version": "1.1.0",
  "uptime_s": 13320,
  "agents": { "active": 12, "queued": 47, "idle": 116, "max": 128 },
  "tasks":  { "running": 5, "pending": 23, "done": 891, "failed": 2 },
  "memory": { "items": 876, "vector_ready": true, "cache_mb": 41 },
  "llm":    { "backend": "local", "model": "simplicio/qwen3.5-4b:q4_k_m", "tok_s": 42, "queue": 3 },
  "hbp":    { "chain_len": 12441, "last_append_ms": 300 },
  "gate":   { "mode": "ask", "last_action": "ALLOW", "last_target": "cp tar/build.sh" }
}
```

## Implementation Steps

1. **Read `StatusConfig`** in the `status` command dispatch arm; branch on
   `config.watch`.
2. **Sampling loop** — `tokio::time::interval(Duration::from_millis(config.status_interval_ms))`;
   break when `samples` count is reached or SIGINT/`q` key.
3. **TUI renderer** — reuse the existing `ratatui` surface already compiled in
   (`tui` feature). One `Frame` per tick; clear + redraw.
4. **Data source** — collect fields from the live runtime state structures already
   exposed: agent fabric counters (`async-runtime`), HBP chain length, gate last
   decision, neural memory item count.
5. **`--json` path** — skip TUI, `println!` one NDJSON line per tick, flush
   stdout.
6. **Graceful exit** — restore terminal on drop via `crossterm::execute!` alternate
   screen / raw-mode cleanup (already done in other TUI paths).

## Acceptance Criteria

- [ ] `simplicio status` (no flag) prints a one-shot snapshot and exits 0.
- [ ] `simplicio status --watch` enters the live dashboard; `q` / Ctrl+C exits
      cleanly with terminal restored.
- [ ] `simplicio status --watch --interval 500 --samples 10 --json` emits exactly
      10 NDJSON lines then exits 0.
- [ ] All fields match the schema above; unknown fields are additive (non-breaking).','docs/observability/STATUS_WATCH.md','413b188724134898bda757aff7642ab1852845bd6403055e5959d91207572498','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/orchestrator/AGENT_WORKFLOW_DASHBOARD.md','project_doc','doc://simplicio-runtime/docs/orchestrator/AGENT_WORKFLOW_DASHBOARD.md','doc: Agent & Workflow Real-Time Dashboard','# Agent & Workflow Real-Time Dashboard

Issue: #2065

## Goal

Provide a live TUI/web view of all 600+ logical agents during a bulk workflow
run, so operators can observe progress, spot bottlenecks, and intervene without
digging through logs.

## Dashboard Panels

### Panel 1 — Agent Fabric Summary

```
Agents  active 47 / 128 (normal tier)  |  queued 312  |  idle 81  |  hibernated 160
Tick batch 8  |  last tick 0.04 s  |  total ticks 12 441
Semaphore slots free: 81 / 128
```

### Panel 2 — Per-Agent Activity (scrollable table, top 20 by CPU time)

```
ID        Kind            State     Task                    Tok  Age
a-0042    coding-loop     running   fix(#2033): split...    341  12 s
a-0091    diagnostics     waiting   cargo check              0    2 s
a-0017    batch-runner    idle      —                        0    —
a-0003    curator         running   compress trajectory     88   45 s
…
```

### Panel 3 — Workflow Progress (per active workflow)

```
Workflow  wf_abc123  (#2064 Extension Points)
  Tasks: 13 total  |  done 4  |  running 2  |  pending 7  |  failed 0
  ETA: ~8 min  |  elapsed 4 min 12 s
  [████████░░░░░░░░░░░░]  31%
```

### Panel 4 — Token Economy

```
Spent this session: 12 441  |  Baseline: 41 200  |  Saved: 28 759 (70%)
Local fan-out: 11 800 tok  |  Remote (VC): 641 tok
HBP chain: 3 421 entries  |  last append 0.1 s ago
```

### Panel 5 — Gate & Delivery Events (live feed, last 10)

```
[12:04:01] GATE ALLOW   agent a-0042: edit src/status.rs
[12:03:58] GATE ASK     agent a-0091: rm -rf target/  → DENIED by user
[12:03:44] DELIVERY OK  #2033 DoD criterion 1/5 passed
[12:03:31] GATE ALLOW   agent a-0003: git commit -m "docs: …"
…
```

## Data Sources

| Panel | Source |
|---|---|
| 1 Fabric summary | `AgentFabric::snapshot()` — in-memory counters |
| 2 Per-agent table | `AgentStore::active_agents()` — sorted by cpu_time |
| 3 Workflow progress | `WorkflowRegistry::running()` |
| 4 Token economy | `SavingsLedger::session_totals()` |
| 5 Gate/delivery feed | `HbpChain::tail(10)` filtered by entry type |

## Refresh Rate

- Default: 1 s (configurable via `--interval <ms>`).
- Panel 2 (agent table) sorts on each refresh — O(n log n) over active agents,
  acceptable for ≤ 600 agents.

## Access Modes

### TUI (default)

```
simplicio agents --watch
simplicio workflow <id> --watch
```

Rendered via `ratatui` (already compiled in `tui` feature).

### Web (`:9119/agents`)

The existing dashboard HTTP server (`src/dashboard.rs`, port 9119) gains two new
routes:

- `GET /api/agents` — JSON snapshot of panel 1 + 2 data.
- `GET /api/workflow/<id>` — JSON snapshot of panel 3 data.
- `GET /api/economy` — JSON snapshot of panel 4 data.
- `GET /api/events?tail=10` — JSON of panel 5 data.

Server-Sent Events (`text/event-stream`) for live push without polling:

- `GET /api/events/stream` — SSE stream; client reconnects on disconnect.

## Implementation Steps

1. Add `AgentFabric::snapshot() -> FabricSnapshot` returning a struct with the
   panel 1 fields.
2. Add `AgentStore::active_agents(limit: usize) -> Vec<AgentSnapshot>` for panel 2.
3. Implement `WorkflowRegistry` (stub exists); add `running() -> Vec<WorkflowStatus>`.
4. Implement TUI renderer for `simplicio agents --watch` using the above sources.
5. Add HTTP routes to `src/dashboard.rs`.
6. Add SSE push via `tokio::sync::broadcast` channel written to on each tick.

## Acceptance Criteria

- [ ] `simplicio agents --watch` renders all 5 panels; refreshes every 1 s.
- [ ] Agent table shows correct state for agents active in a running workflow.
- [ ] `GET /api/agents` returns valid JSON matching the panel 1+2 schema.
- [ ] SSE stream delivers at least one event per second with no dropped frames
      under 600 concurrent logical agents (load test).
- [ ] Dashboard exits cleanly on Ctrl+C with terminal restored.','docs/orchestrator/AGENT_WORKFLOW_DASHBOARD.md','388684525bee657546052fb763dbf5810a96af5bd9ee3503d05d52a4819c691f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/orchestrator/DUAL_PATH_ROUTER.md','project_doc','doc://simplicio-runtime/docs/orchestrator/DUAL_PATH_ROUTER.md','doc: Dual-Path Router — Fast Path vs Heavy Path','# Dual-Path Router — Fast Path vs Heavy Path

Issue: #2073

## Overview

The orchestrator routes each incoming task through one of two execution paths
before dispatch to an agent:

- **Fast path** — deterministic, zero-LLM, < 500 ms end-to-end.
- **Heavy path** — LLM-assisted (local fan-out first, remote last resort), up to
  minutes.

The router''s job is to pick the cheapest path that can still close the task.

## Routing Decision Tree

```
task arrives
  │
  ├─ Is task type deterministic? (map / validate / deliver / gate / checkpoint)
  │    └─ YES → Fast Path (F0: deterministic Simplicio command)
  │
  ├─ Cache / template hit? (memory FTS + trajectory matches ≥ 0.92)
  │    └─ YES → Fast Path (F1: replay from memory)
  │
  ├─ Single mechanical operation? (edit plan already decided, regex/AST match)
  │    └─ YES → Fast Path (F2: simplicio edit, zero-token write)
  │
  ├─ Local fan-out can close it? (Qwen3.5-4B Q4_K_M, ≤ 200 agents, < 60 s)
  │    └─ YES → Heavy Path H1 (local)
  │
  ├─ Extended local run? (Qwen3.5-4B Q4_K_M, 200–600 agents, ≤ 5 min)
  │    └─ YES → Heavy Path H2 (local extended)
  │
  └─ Requires paid remote? (explicit --remote or local H1+H2 both failed)
       └─ YES → Heavy Path H3 (remote VC, recorded escalation evidence)
               (requires SIMPLICIO_API_KEY + --allow-remote policy)
```

## Path Profiles

### Fast Path — F0 (Deterministic Command)

- **Trigger:** `task.kind` in `{Map, Validate, Deliver, Gate, Checkpoint, Status}`
- **Executor:** direct Simplicio runtime call, no LLM.
- **Budget:** 0 LLM tokens, < 100 ms.
- **Evidence:** HBP entry `fast-path/deterministic`.

### Fast Path — F1 (Memory Replay)

- **Trigger:** `memory_score ≥ 0.92` from FTS + vector query.
- **Executor:** apply cached plan via `simplicio edit`.
- **Budget:** 0 LLM tokens, < 500 ms (memory query + edit apply).
- **Evidence:** HBP entry `fast-path/memory-replay`, includes memory item ID.

### Fast Path — F2 (Mechanical Edit)

- **Trigger:** task carries a pre-decided `EditPlan` (from planner output or
  user-supplied JSON).
- **Executor:** `simplicio edit` mechanical writer.
- **Budget:** 0 LLM tokens, < 200 ms.
- **Evidence:** HBP entry `fast-path/mechanical-edit`.

### Heavy Path — H1 (Local Fan-Out)

- **Trigger:** no fast path matched; task requires generation or ambiguous change.
- **Executor:** Qwen3.5-4B Q4_K_M local, 64–200 agents, semaphore-bounded.
- **Budget:** local tokens only (no cost), ≤ 60 s wall time.
- **Evidence:** HBP entry `heavy-path/local-h1`, agent count, tok/s.

### Heavy Path — H2 (Local Extended)

- **Trigger:** H1 failed (all local attempts exhausted or confidence < threshold).
- **Executor:** Qwen3.5-4B Q4_K_M local, 200–600 agents, extended time budget.
- **Budget:** local tokens only, ≤ 5 min wall time.
- **Evidence:** HBP entry `heavy-path/local-h2`, failure evidence from H1.

### Heavy Path — H3 (Remote VC)

- **Trigger:** H1 + H2 both failed, AND `--allow-remote` policy is set.
- **Executor:** paid remote LLM via `SIMPLICIO_BASE_URL` + `SIMPLICIO_API_KEY`.
- **Budget:** metered (token cost recorded); requires explicit user opt-in.
- **Gate:** action-gate `classify_action_risk` fires before H3 dispatch.
- **Evidence:** HBP entry `heavy-path/remote-h3`, escalation chain (H1 failure →
  H2 failure → H3 dispatch), provider, model, tokens spent.

## `DualPathRouter` API

```rust
pub struct DualPathRouter {
    memory:  Arc<dyn MemoryBackend>,
    gate:    Arc<ActionGate>,
    policy:  RemotePolicy,   // Allow | Deny | RequireFlag
}

impl DualPathRouter {
    pub async fn route(&self, task: &Task) -> RoutingDecision;
}

pub enum RoutingDecision {
    FastPath(FastPathKind),
    HeavyPath(HeavyPathKind),
    Blocked(String),   // gate denied or policy violation
}

pub enum FastPathKind  { Deterministic, MemoryReplay(MemoryItemId), MechanicalEdit(EditPlan) }
pub enum HeavyPathKind { LocalH1, LocalH2, RemoteH3 }
```

## Token Savings Integration

Each path decision is reported in the savings line:

| Path | Baseline (without router) | Actual |
|---|---|---|
| F0 | 2 000 tok (LLM would have done it) | 0 |
| F1 | 3 000 tok (re-derive + LLM write) | 0 |
| F2 | 1 500 tok (LLM hand-write) | 0 |
| H1 | 8 000 tok (remote) | ~600 local |
| H2 | 8 000 tok (remote) | ~1 800 local |
| H3 | — | actual remote tokens |

## Configuration

```toml
[router]
memory_replay_threshold = 0.92   # cosine similarity floor for F1
local_h1_timeout_s      = 60
local_h2_timeout_s      = 300
remote_policy           = "deny" # "allow" | "deny" | "require-flag"
```

## Acceptance Criteria

- [ ] A `map` task always routes to F0 with 0 LLM tokens.
- [ ] A task with `memory_score ≥ 0.92` routes to F1; the applied edit matches
      the cached plan.
- [ ] A task with a pre-supplied `EditPlan` routes to F2; file is updated in
      < 200 ms.
- [ ] A novel code task routes to H1; escalates to H2 on H1 failure; never
      reaches H3 without `--allow-remote`.
- [ ] H3 dispatch records escalation evidence on the HBP chain before any remote
      call is made.
- [ ] `remote_policy = "deny"` causes H3 to return `Blocked` without calling the
      remote provider.','docs/orchestrator/DUAL_PATH_ROUTER.md','512105ea8550bde3609b4e38198611d1f73e62835081fcf0c3d60610dfed14fa','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/orchestrator/EXTENSION_POINTS.md','project_doc','doc://simplicio-runtime/docs/orchestrator/EXTENSION_POINTS.md','doc: Orchestrator Extension Points','# Orchestrator Extension Points

Issue: #2064

## Overview

The Simplicio orchestrator (orchestrator-v7, `docs/contracts/orchestrator-v7.md`)
exposes 13 well-defined extension points. Third parties and internal skills can
hook into these points without modifying the core runtime.

## Extension Point Catalogue

### EP-01 — Task Intake Filter

**Where:** before the drain-loop dequeues a task.
**Interface:**

```rust
pub trait IntakeFilter: Send + Sync {
    fn filter(&self, task: &mut Task) -> FilterDecision;
}
pub enum FilterDecision { Allow, Skip, Reject(String) }
```

**Use cases:** block tasks by label, enrich metadata, enforce rate limits.

---

### EP-02 — Task Classifier Override

**Where:** after built-in classification, before dispatch.
**Interface:**

```rust
pub trait TaskClassifier: Send + Sync {
    fn classify(&self, task: &Task) -> Option<TaskKind>;
}
```

**Use cases:** custom `TaskKind` for domain-specific task types (video, audit).

---

### EP-03 — Action Gate Hook

**Where:** inside `action_gate_decide`, after risk classification.
**Interface:**

```rust
pub trait GateHook: Send + Sync {
    fn before_gate(&self, action: &Action, risk: Risk) -> GateVote;
}
pub enum GateVote { Allow, Deny(String), Abstain }
```

**Use cases:** org-specific policy enforcement, compliance logging.

---

### EP-04 — Edit Plan Interceptor

**Where:** inside `simplicio edit` before the mechanical writer applies a plan.
**Interface:**

```rust
pub trait EditInterceptor: Send + Sync {
    fn intercept(&self, plan: &EditPlan) -> InterceptResult;
}
pub enum InterceptResult { Apply(EditPlan), Reject(String) }
```

**Use cases:** enforce style rules, block edits to protected files.

---

### EP-05 — Diagnostics Emitter

**Where:** after `cargo check`/`clippy`/`cargo test` runs in the coding loop.
**Interface:**

```rust
pub trait DiagnosticsEmitter: Send + Sync {
    fn emit(&self, run: &DiagnosticsRun);
}
```

**Use cases:** forward errors to Slack/PagerDuty, populate a dashboard.

---

### EP-06 — Memory Store Backend

**Where:** `simplicio memory` read/write path.
**Interface:**

```rust
pub trait MemoryBackend: Send + Sync {
    fn query(&self, q: &str, limit: usize) -> Vec<MemoryItem>;
    fn upsert(&self, item: &MemoryItem) -> Result<()>;
}
```

**Use cases:** swap SQLite for Postgres, add a remote vector store.

---

### EP-07 — Agent Lifecycle Hook

**Where:** agent fabric — on agent spawn, idle, and terminate.
**Interface:**

```rust
pub trait AgentLifecycle: Send + Sync {
    fn on_spawn(&self,  id: AgentId, kind: &str);
    fn on_idle(&self,   id: AgentId);
    fn on_terminate(&self, id: AgentId, outcome: &str);
}
```

**Use cases:** metrics collection, distributed tracing, audit log.

---

### EP-08 — HBP Chain Listener

**Where:** HBP verifiable chain — every append.
**Interface:**

```rust
pub trait HbpListener: Send + Sync {
    fn on_append(&self, entry: &HbpEntry);
}
```

**Use cases:** replicate to secondary store, trigger alerts on anomalous entries.

---

### EP-09 — Delivery Gate Override

**Where:** `simplicio deliver check` — per acceptance criterion evaluation.
**Interface:**

```rust
pub trait DeliveryGate: Send + Sync {
    fn evaluate(&self, criterion: &Criterion, evidence: &Evidence) -> GateResult;
}
pub enum GateResult { Pass, Fail(String), Skip }
```

**Use cases:** custom test runners, external QA systems.

---

### EP-10 — Trajectory Curator Hook

**Where:** `trajectory` compressor — before a session segment is archived.
**Interface:**

```rust
pub trait TrajectoryCurator: Send + Sync {
    fn curate(&self, segment: &TrajectorySegment) -> CuratorDecision;
}
pub enum CuratorDecision { Keep, Compress, Drop }
```

**Use cases:** PII scrubbing before archival, cost-based pruning.

---

### EP-11 — Video Pipeline Stage

**Where:** `video_pipeline` — between any two stages (script→asset→render→encode).
**Interface:**

```rust
pub trait VideoPipelineStage: Send + Sync {
    fn process(&self, ctx: &mut VideoContext) -> StageResult;
}
```

**Use cases:** inject a watermark step, custom audio mix, CDN upload.

---

### EP-12 — Skill Resolver

**Where:** skill dispatch — resolves a skill name to an implementation.
**Interface:**

```rust
pub trait SkillResolver: Send + Sync {
    fn resolve(&self, name: &str) -> Option<Box<dyn Skill>>;
}
```

**Use cases:** load skills from a plugin directory, remote skill registry.

---

### EP-13 — Savings Reporter Hook

**Where:** end of every LLM response — before the token-savings line is emitted.
**Interface:**

```rust
pub trait SavingsHook: Send + Sync {
    fn on_savings(&self, spent: u64, baseline: u64, saved: u64, pct: u8);
}
```

**Use cases:** aggregate savings metrics to a dashboard, billing allocation.

---

## Registration

All extension points are registered via the `ExtensionRegistry` (to be introduced
in `src/extension_registry.rs`):

```rust
let mut reg = ExtensionRegistry::new();
reg.register_intake_filter(Box::new(MyFilter));
reg.register_gate_hook(Box::new(MyPolicy));
// …
simplicio::run(config, reg)?;
```

Plugins can be loaded from shared libraries (`.so`/`.dylib`/`.dll`) or compiled
in statically. The registry is arc-wrapped and shared across the agent fabric.

## Acceptance Criteria

- [ ] `src/extension_registry.rs` exists and compiles with all 13 trait definitions.
- [ ] At least EP-03 (Gate Hook) and EP-07 (Agent Lifecycle) are wired in the
      runtime and called at the documented call sites.
- [ ] A smoke test registers a no-op implementation for each EP and runs
      `simplicio status` without panics.','docs/orchestrator/EXTENSION_POINTS.md','acf12e1381fe65138ce9a8840a1f98815406c51ac6435654d9f7af228ea79ed2','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/orchestrator/WORKTREE_MANAGEMENT.md','project_doc','doc://simplicio-runtime/docs/orchestrator/WORKTREE_MANAGEMENT.md','doc: Per-Item Isolated Git Worktree Management','# Per-Item Isolated Git Worktree Management

Issue: #2069

## Problem

When the orchestrator processes multiple tasks in parallel, agents edit the same
working tree concurrently, causing merge conflicts and race conditions (see memory
note "Hazard: agente paralelo na worktree"). This makes parallel coding tasks
unsafe without a worktree-isolation layer.

## Solution

Each task item that mutates the filesystem gets its own isolated `git worktree`.
The orchestrator creates a worktree before dispatching, the agent works inside it,
and the orchestrator merges the result back to `main` after the delivery gate
passes.

## Lifecycle

```
[orchestrator]
  1. Reserve a slot: worktree_mgr.reserve(task_id) → WorktreeHandle
  2. Create:  git worktree add .worktrees/<task_id> main
  3. Dispatch agent with WORKTREE_PATH=.worktrees/<task_id>
  4. Agent works inside .worktrees/<task_id>, commits its change there.
  5. Delivery gate runs inside the worktree.
  6. On PASS: orchestrator merges to main (fast-forward or squash).
  7. On FAIL:  orchestrator records evidence, removes worktree (no pollution).
  8. Cleanup:  git worktree remove --force .worktrees/<task_id>
               worktree_mgr.release(task_id)
```

## `WorktreeManager` API

```rust
pub struct WorktreeManager {
    root: PathBuf,          // project root
    max_concurrent: usize,  // default: min(active_agents, 20)
}

impl WorktreeManager {
    pub fn new(root: PathBuf, max_concurrent: usize) -> Self;

    /// Create a worktree for task_id branched from HEAD of base_branch.
    pub async fn create(&self, task_id: &str, base_branch: &str)
        -> Result<WorktreeHandle>;

    /// Merge the worktree''s HEAD commit into base_branch.
    /// Strategy: fast-forward if possible, else squash.
    pub async fn merge(&self, handle: &WorktreeHandle, base_branch: &str)
        -> Result<MergeOutcome>;

    /// Remove the worktree unconditionally (pass or fail).
    pub async fn remove(&self, handle: WorktreeHandle) -> Result<()>;

    /// List all managed worktrees (for dashboard / status).
    pub fn list(&self) -> Vec<WorktreeInfo>;
}

pub struct WorktreeHandle {
    pub task_id: String,
    pub path: PathBuf,
    pub branch: String,   // "wt/<task_id>"
    pub created_at: Instant,
}

pub enum MergeOutcome { FastForward, Squash, Conflict(String) }
```

## Merge Strategy

1. Attempt `git merge --ff-only wt/<task_id>` into `main`.
2. If fast-forward fails (diverged): `git merge --squash wt/<task_id>` then
   `git commit -m "feat(<task_id>): <task title>"`.
3. If conflict: record conflict diff as evidence on HBP chain; mark task FAILED;
   remove worktree; escalate to operator via gate event.

## Concurrency Limits

- `max_concurrent` defaults to `min(active_agents, 20)` to respect the 20-agent
  memory note.
- A `tokio::sync::Semaphore` guards slot acquisition; `reserve()` awaits a slot.
- `.worktrees/` directory is gitignored.

## Cleanup Policy

- Successful worktrees are removed immediately after merge.
- Failed worktrees are kept for 24 h (for operator inspection), then removed by
  a periodic cleanup task (`worktree_cleanup` cron, every 6 h).
- `simplicio worktrees list` shows active, pending-cleanup, and stale worktrees.
- `simplicio worktrees purge` force-removes all stale worktrees.

## `.gitignore` Entry (automatic)

`WorktreeManager::new()` ensures `.worktrees/` is in `.gitignore`:

```
# Simplicio managed worktrees (auto-generated, do not commit)
.worktrees/
```

## Acceptance Criteria

- [ ] Two parallel coding tasks produce no merge conflicts when edits are to
      different files.
- [ ] `git log --oneline -5` after two parallel tasks shows two clean commits on
      `main`.
- [ ] A task whose delivery gate fails leaves no worktree residue in `.worktrees/`
      after 24 h.
- [ ] `simplicio worktrees list` correctly shows count of active / pending / stale.
- [ ] `simplicio worktrees purge` removes all stale entries and reports count removed.
- [ ] `WorktreeManager` unit tests cover: create → merge (ff), create → merge
      (squash), create → fail → cleanup.','docs/orchestrator/WORKTREE_MANAGEMENT.md','e4be75c5376065516c65a2b078be3066f4f76967d09c7f5f371b4367fe00f644','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/osaurus-import/2026-06-25-analysis.md','project_doc','doc://simplicio-runtime/docs/osaurus-import/2026-06-25-analysis.md','doc: Osaurus import analysis (2026-06-25)','# Osaurus import analysis (2026-06-25)

Source: https://github.com/osaurus-ai/osaurus — "Own your AI. The native macOS harness
for AI agents — any model, persistent memory, autonomous execution, cryptographic
identity. Built in Swift. Fully offline. MIT." 6.2k★.

**Why it matters:** osaurus is the SAME product category and vision as Simplicio (the
AI *harness*: agents + memory + tools + identity, local+cloud, offline), but mature and
native macOS. Its feature set maps almost 1:1 to the gaps the connection audit
(wf_13ec3e27-320) found in Simplicio. We **port patterns** (it''s MIT — learn, don''t
copy Swift) into Simplicio-native Rust forms: contract, capability, skill, deterministic
flow, governed memory. This is the Hermes-import discipline applied to osaurus.

## Import candidates, mapped to Simplicio''s audit gaps

| # | Osaurus pattern | Fixes Simplicio gap | Port |
|---|---|---|---|
| 1 | **Skills/Tools/Methods auto-selected via RAG** (no manual config) | SKILLS 1/6 (reachable only via explicit cmd, never used in a turn) | spine ranks relevant skills by embedding recall + injects/uses them; the #1 connection win |
| 2 | **Memory: distill-at-session-end + salience scoring + background consolidator (decay/merge/evict), ~800-token budget, many turns inject zero** | MEMORY 3/6 (today: FTS+vector wired, but no distill/salience/consolidation) | upgrade spine_recall/persist: episodic vs pinned vs identity layers; distill once at session end; salience-ranked single slice |
| 3 | **Agent Loop = every chat is a loop**: working folder → file/search/git tools → markdown todo → execute → verified summary, in the chat window | the whole CONNECTION vision (#2622) | unify the coding loop into the spine: chat picks a folder, gets tools, plans todo, executes, verifies |
| 4 | **Methods = learned workflows agents save + reuse over time** (RAG-selected) | extends skill-capture #2635 (capture but no auto-reuse) | persist successful trajectories as Methods; RAG-select + replay |
| 5 | **Sandbox**: isolated VM for code exec (shell/python/node), agent connects back via bridge | computer-use / safe code execution | Windows: WSL2 / a container abstraction; isolate `exec` actions |
| 6 | **Privacy Filter**: on-device PII classifier, scrub before cloud, fail-closed, [PERSON_1] placeholders, unscrub streaming back | security (upgrades redact_secrets) | deterministic regex (have) + an opt-in classifier pass before remote calls; fail-closed |
| 7 | **Watchers**: monitor folders, trigger agents on file changes | AUTOMATION 2/6 | extend cron_scheduler with a file-watch trigger → spine task |
| 8 | **Document adapters**: CSV/XLSX/PPTX/PDF parsed with STRUCTURE before reaching the agent | FILES/tools | a document adapter registry feeding chat context |
| 9 | **Global hotkey: transcribe into ANY app** (voice) + App Intents/Spotlight/Siri system-wide "Ask" | VOICE / surfaces | Windows: global hotkey → STT → type into the focused app; tray "Ask" |
| 10 | **MCP client aggregation**: one-tap connect ~25 providers (Linear/Notion/GitHub/Stripe…) with OAuth 2.1 + DCR | tools/knowledge | aggregate remote MCP providers in the runtime; one-tap OAuth |
| 11 | **Multi-provider, context+memory persist ACROSS providers** (local MLX/Foundation + cloud) | local-vs-paid routing | ensure memory/context survive provider switches in the spine |

## Reject / not-now
- Swift / Apple-only bits (MLX, Apple Foundation Models, App Intents, Containerization VM)
  — port the CONCEPT to the Windows/Rust stack, not the implementation.
- secp256k1 identity + relay + secure channel (E2E agent-to-agent): valuable but large;
  Simplicio already has HBP crypto-token — defer, track as a stretch.
- Telemetry (Aptabase/Sentry): not now.

## Decision
Port #1 (skills-via-RAG) and #2 (memory consolidator) FIRST — they directly close the
two lowest-connection domains and reinforce the work already in flight. Then #3 (agent
loop in chat) and #4 (Methods). Each lands with a passing functional test in
`scripts/functional-tests.sh`.','docs/osaurus-import/2026-06-25-analysis.md','215382c186b274f66d2fe5ce794377dedbe032455aa539975115412ee662d2f6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/PACKAGING.md','project_doc','doc://simplicio-runtime/docs/PACKAGING.md','doc: Packaging — Docker','# Packaging — Docker

Simplicio ships as a single binary, so the container image is thin. There are
two ways to build it and a `docker-compose.yml` for the common run modes.

## Image targets

The `Dockerfile` has three stages:

| Target                 | What it does                                              | Use when |
|------------------------|----------------------------------------------------------|----------|
| `runtime` *(default)*  | Copies a prebuilt linux binary from `./dist/simplicio`   | You already built `simplicio` (fast) |
| `runtime-from-source`  | Compiles inside the image (`rust:1-bookworm` build stage)| No local binary / multi-arch CI |
| `build`                | Internal build stage (not a run target)                  | — |

Base runtime image is `debian:stable-slim` (glibc, ~30 MB before the binary),
runs as the non-root `simplicio` user (uid 10001), and ships a `HEALTHCHECK`
that calls `simplicio --version`.

### 1. Binary-copy (default, fast)

```bash
# Build a linux binary first (lean, no llama.cpp):
cargo build --release --no-default-features --features tui
mkdir -p dist && cp target/release/simplicio dist/simplicio

docker build --target runtime -t simplicio:latest .
```

### 2. From source (self-contained, multi-arch)

```bash
docker build --target runtime-from-source -t simplicio:latest .
```

By default the build stage compiles the **lean** feature set
(`--no-default-features --features tui`). For the full build (compiles
llama.cpp, needs cmake/clang — already installed in the build stage):

```bash
docker build --target runtime-from-source \
  --build-arg CARGO_BUILD_FLAGS="--locked" \
  -t simplicio:full .
```

## Running

Config and the repo are bind-mounted; nothing secret is baked into the image.

```bash
# Deterministic command — no model, no network needed:
docker run --rm \
  -v "$HOME/.simplicio-loop:/home/simplicio/.simplicio-loop" \
  -v "$PWD:/work" -w /work \
  simplicio:latest map --repo . --json
```

The container''s config dir is `/home/simplicio/.simplicio-loop`
(`SIMPLICIO_HOME`); mount your host `~/.simplicio-loop` there to persist memory and
checkpoints.

## docker-compose

```bash
cp .env.docker.example .env        # fill in only what you need (all optional)

# Long-running Discord gateway:
docker compose --profile gateway up

# One-shot agent run:
docker compose run --rm agent validate --repo .

# Interactive TUI:
docker compose run --rm tui
```

Profiles: `gateway` (listener, restarts, exposes the webhook port), `agent`
(one-shot/scripted), `tui` (interactive REPL). Copy
`docker-compose.override.yml.example` to `docker-compose.override.yml` for
machine-local tweaks (it is gitignored).

## CI / published images

`.github/workflows/docker.yml` builds `linux/amd64` + `linux/arm64` from source
and publishes to `ghcr.io/wesleysimplicio/simplicio` on release (and on a manual
`workflow_dispatch` with `push=true`). It is **not** wired to every push, in
line with the repo''s Actions-billing policy.

```bash
docker pull ghcr.io/wesleysimplicio/simplicio:latest
```


## PyPI installer-only policy

The GitHub release workflow publishes only the public `simplicio-installer`
wheel from `packaging/pypi`. The private `simplicio-runtime` checkout is
not an official PyPI release target and must never be uploaded as an sdist; doing
so would expose source code. Use `scripts/verify-release.py --version vX.Y.Z` to
verify release state after publishing.','docs/PACKAGING.md','c68143476fe03372ce08a04092f527f3ed67f0983d18d9fd800f8c3b763f3663','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/performance-regression-gate.md','project_doc','doc://simplicio-runtime/docs/performance-regression-gate.md','doc: Performance regression baseline gate','# Performance regression baseline gate

Issue #3437 adds a comparison contract without coupling the gate to a
particular provider or benchmark command. A runner produces two receipts with
the same workload, seed, warm-up count, condition matrix, repetition count,
and machine class. The gate compares the four required scenarios:

- `baseline`
- `runtime`
- `runtime+loop`
- `full-stack`

Every condition is compared separately. Receipts must include cold and warm
runs, cache hit and miss, and normal and saturated resource conditions. Each
condition needs at least five repetitions. The gate uses median and linearly
interpolated p95 values. Throughput is higher-is-better; latency, startup, and
RSS are lower-is-better. A metric regresses when either statistic exceeds its
configured tolerance.

`PASS` exits 0, `REGRESSION` exits 1, and `BLOCKED` exits 2. Invalid or
incomplete evidence is also `BLOCKED`; it cannot silently pass. An
`OVERRIDDEN` result exits 0 only when an unexpired JSON override includes a
reason, approver, and expiry. Overrides never convert `BLOCKED` to success.

Provider-reported token and cost fields remain `null` when the provider does
not emit them. The comparator never estimates or fabricates those values.

The CI workflow runs the contract tests on pull requests. The comparison job
requires `benchmarks/performance/baseline.json` and a commit-linked candidate
receipt; missing runtime, binary, model, or candidate evidence is reported as
`BLOCKED`.','docs/performance-regression-gate.md','a51cc43a95be701ebb7e19071fe5372b00dcae1c8e74c5a7f51d837537dd4a67','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/planning/BACKEND_ARCHITECTURE.md','project_doc','doc://simplicio-runtime/docs/planning/BACKEND_ARCHITECTURE.md','doc: Backend Architecture Planning — Issue #2216','# Backend Architecture Planning — Issue #2216

## Problem

The current site (`site/`) is fully static. We need server-side infrastructure for:
- OAuth callbacks (GitHub, Google login)
- Stripe webhooks (subscription lifecycle)
- User data persistence (preferences, usage, billing)
- Protected API endpoints for the desktop app

## Why Not Static

| Need | Static? | Why not |
|------|---------|---------|
| OAuth callback | No | Requires server-side token exchange |
| Stripe webhooks | No | Must verify signature server-side |
| User accounts | No | Needs a database |
| Usage metering | No | Rate limits, counters |
| Email triggers | No | Backend must call Resend/SendGrid |

## Options Evaluated

### Option A: Vercel Edge Functions + Supabase (RECOMMENDED)

**Vercel Edge Functions**
- Deploy alongside the static site in the same repo
- `api/` directory → auto-deployed as Edge Functions
- Free tier: 100K invocations/day, 1 MB memory
- Zero cold starts (Edge runtime, not Node)

**Supabase (PostgreSQL + Auth)**
- Free tier: 500 MB DB, 50K MAU, 2 GB bandwidth
- Built-in Auth: email/password, OAuth (GitHub, Google), magic link
- Row-Level Security for multi-tenant data
- Realtime subscriptions (future: live usage dashboard)
- SDK: `@supabase/supabase-js` + Rust client via REST

**Why this wins:**
- Free until ~500 paying users
- Supabase Auth handles OAuth complexity
- One SQL schema, no ORM needed
- Vercel + Supabase is the de-facto standard stack for SaaS MVPs

### Option B: Cloudflare Workers + D1

- Workers: faster globally, cheaper at scale
- D1: SQLite-based, limited SQL surface vs PostgreSQL
- Auth: must build from scratch or use Clerk (paid add-on)
- **Rejected**: Auth complexity, D1 limitations, no Realtime

### Option C: Self-hosted (VPS + PostgreSQL + Express)

- Full control, cheapest at scale
- Requires ops: TLS, backups, monitoring, uptime
- **Rejected**: too much ops work for current stage

## Recommended Architecture

```
site/ (Vercel static)
  └── api/
        ├── auth/
        │   ├── callback.ts      — OAuth callback (GitHub/Google)
        │   └── session.ts       — JWT validation middleware
        ├── stripe/
        │   ├── webhook.ts       — Handle checkout.session.completed etc.
        │   └── portal.ts        — Customer portal redirect
        ├── users/
        │   ├── me.ts            — GET /api/users/me
        │   └── delete.ts        — DELETE /api/users/me (LGPD #2218)
        └── health.ts            — GET /api/health
```

**Database schema (Supabase / PostgreSQL)**

```sql
-- Managed by Supabase Auth
users (id uuid PK, email, created_at, ...)

-- Application tables
profiles (
  id          uuid PK REFERENCES auth.users,
  plan        text DEFAULT ''free'',  -- free | starter | pro | enterprise
  stripe_customer_id text,
  locale      text DEFAULT ''en'',
  created_at  timestamptz DEFAULT now()
)

subscriptions (
  id                  uuid PK,
  user_id             uuid REFERENCES profiles,
  stripe_subscription_id text,
  status              text,  -- active | canceled | past_due
  current_period_end  timestamptz,
  plan                text,
  created_at          timestamptz DEFAULT now()
)

usage_events (
  id          uuid PK,
  user_id     uuid REFERENCES profiles,
  event_type  text,  -- run | skill_invoke | api_call
  metadata    jsonb,
  created_at  timestamptz DEFAULT now()
)
```

## Environment Variables Required

```
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<secret>
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
NEXT_PUBLIC_SUPABASE_ANON_KEY=<public>
```

## Implementation Phases

| Phase | Scope | Effort |
|-------|-------|--------|
| 1 | Supabase project setup + schema | 2h |
| 2 | Auth: email+OAuth login page | 4h |
| 3 | Stripe integration + webhook handler | 4h |
| 4 | User dashboard (plan, usage, billing portal) | 6h |
| 5 | Delete-account endpoint (LGPD) | 2h |

## Blockers (user-side, cannot be done in session)

- [ ] Wesley creates Supabase project at supabase.com (free tier)
- [ ] Wesley creates Stripe account and activates it
- [ ] Add env vars to Vercel project settings
- [ ] Domain: configure custom domain for API (optional, Vercel subdomain works)

## Related Issues

- Blocks: #2217 (email), #2218 (LGPD deletion endpoint)
- Blocked by: nothing — can start immediately after Supabase/Stripe setup','docs/planning/BACKEND_ARCHITECTURE.md','8e8c8ced1059e8dc080bdb4975bf77e42a782ad88ea4ce4067e2d732156f9f9f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/planning/BUSINESS_MODEL_SIMULATION.md','project_doc','doc://simplicio-runtime/docs/planning/BUSINESS_MODEL_SIMULATION.md','doc: Business Model & Financial Simulation — Issue #2232','# Business Model & Financial Simulation — Issue #2232

## Pricing Tiers

| Plan | Price/mo | Target User | Key Limits |
|------|----------|-------------|------------|
| Free | $0 | Individuals, try-before-buy | 100 API calls/day, 1 device |
| Starter | $12 | Solo professionals | 1000 API calls/day, 3 devices |
| Pro | $29 | Power users, freelancers | 10K API calls/day, 10 devices, priority support |
| Enterprise | $99 | Teams, businesses | Unlimited calls, SSO, SLA, invoicing |

*Prices in USD. Brazilian market: offer BRL pricing (× 5 FX approx).*

## Assumptions

| Parameter | Value | Source |
|-----------|-------|--------|
| Monthly churn rate | 5% | SaaS benchmark (early-stage B2C) |
| Free → Paid conversion | 8% | Freemium SaaS average (4–10%) |
| Starter → Pro upgrade | 15% | of Starter users (after 3 months) |
| CAC (customer acquisition cost) | $18 | Organic + light paid social |
| Gross margin | 85% | Software (infra ~$1.50/active user/mo) |

## LTV Formula

```
LTV = ARPU / churn_rate
```

Where ARPU = blended average revenue per paying user per month.

## Scenario A: 200 Users

### Mix

| Plan | % | Users | Price | MRR contribution |
|------|---|-------|-------|-----------------|
| Free | 60% | 120 | $0 | $0 |
| Starter | 25% | 50 | $12 | $600 |
| Pro | 10% | 20 | $29 | $580 |
| Enterprise | 5% | 10 | $99 | $990 |

**Total MRR (200 users): $2,170**
**ARR: $26,040**

### Unit Economics at 200 Users

```
Paying users: 80
ARPU (paying): $2,170 / 80 = $27.13/mo
LTV (paying): $27.13 / 0.05 = $542.50
CAC: $18
LTV:CAC ratio: 30.1x  ✓ (healthy — target >3x)

Infra costs: 200 users × $1.50 = $300/mo
Gross profit: $2,170 - $300 = $1,870/mo (86%)
```

### Monthly cash flow at 200 users

| Item | Monthly |
|------|---------|
| Revenue | +$2,170 |
| Infra (Supabase, Vercel, Resend, etc.) | -$300 |
| Stripe fees (2.9% + $0.30/transaction) | -$75 |
| **Net** | **+$1,795** |

## Scenario B: 1,000 Users

### Mix (same distribution)

| Plan | % | Users | Price | MRR contribution |
|------|---|-------|-------|-----------------|
| Free | 60% | 600 | $0 | $0 |
| Starter | 25% | 250 | $12 | $3,000 |
| Pro | 10% | 100 | $29 | $2,900 |
| Enterprise | 5% | 50 | $99 | $4,950 |

**Total MRR (1,000 users): $10,850**
**ARR: $130,200**

### Unit Economics at 1,000 Users

```
Paying users: 400
ARPU (paying): $10,850 / 400 = $27.13/mo
LTV (paying): $27.13 / 0.05 = $542.50

Infra costs: $1,500/mo (economies of scale)
Gross profit: $10,850 - $1,500 = $9,350/mo (86%)
```

### Monthly cash flow at 1,000 users

| Item | Monthly |
|------|---------|
| Revenue | +$10,850 |
| Infra | -$1,500 |
| Stripe fees | -$350 |
| Part-time support / ops | -$1,000 |
| **Net** | **+$8,000** |

## Scenario C: 5,000 Users (growth target)

| Plan | % | Users | MRR |
|------|---|-------|-----|
| Free | 60% | 3,000 | $0 |
| Starter | 25% | 1,250 | $15,000 |
| Pro | 10% | 500 | $14,500 |
| Enterprise | 5% | 250 | $24,750 |

**MRR: $54,250 · ARR: $651,000**

## Churn Impact Analysis

```
Starting paying users: 400 (1K total scenario)
Monthly churn: 5% = 20 users lost
Required new paying users to grow: > 20/mo

At 8% free→paid conversion with 50 new signups/mo:
  New paying = 0.08 × 50 = 4/mo  (insufficient — need marketing)

At 200 new signups/mo:
  New paying = 0.08 × 200 = 16/mo  (near break-even)

At 500 new signups/mo:
  New paying = 0.08 × 500 = 40/mo  (net +20 paying/mo = growth)
```

**Key lever: signup volume.** With 5% churn, growth requires 500+ new signups/month at typical conversion.

## Cohort Retention Model

```
Month 0: 100 new paying users
Month 1: 95 (−5%)
Month 3: 86 (−14%)
Month 6: 74 (−26%)
Month 12: 54 (−46%)

Average paying lifespan: 1 / 0.05 = 20 months
Revenue per cohort of 100: 100 × $27.13 × 20 = $54,260
```

## Growth Path to Default Alive

| Milestone | MRR | Infra+Ops Cost | Status |
|-----------|-----|----------------|--------|
| 200 users | $2,170 | $375 | Profitable (solo) |
| 500 users | $5,425 | $800 | Profitable |
| 1,000 users | $10,850 | $2,850 | Profitable, hire support |
| 5,000 users | $54,250 | $10,000 | Series A territory |

**Default Alive threshold (solo founder): ~$3,000 MRR = ~350 users.**

## Brazilian Market Pricing (BRL)

Apply ~5× USD → BRL multiplier (PPP-adjusted for B2C SaaS):

| Plan | USD | BRL |
|------|-----|-----|
| Starter | $12 | R$49 |
| Pro | $29 | R$119 |
| Enterprise | $99 | R$399 |

Stripe supports BRL. Present BRL pricing to users with `navigator.language === ''pt-BR''`.

## Key Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Churn > 10% | Medium | High | Improve onboarding, add value fast |
| Low free→paid conversion (<4%) | Medium | High | Better paywalling, usage-based limits |
| LLM API costs spike | Low | Medium | Local-first architecture already mitigates |
| Stripe/Supabase free tier exceeded early | Low | Low | Costs scale with revenue |

## Infrastructure Cost Breakdown (at 1K users)

| Service | Free Tier | Beyond Free | At 1K users |
|---------|-----------|-------------|-------------|
| Vercel | 100K invocations | $20/mo (Pro) | $20 |
| Supabase | 50K MAU, 500MB | $25/mo (Pro) | $25 |
| Resend | 3K emails/mo | $20/mo (50K) | $20 |
| Domain/DNS | — | $12/yr | $1 |
| Monitoring (Sentry) | 5K errors/mo | $26/mo | $26 |
| **Total** | | | **~$92/mo** |

At 1K users, infra is <1% of MRR. Scales to ~$1,500 at 5K users.

## Next Steps

1. [ ] Wesley creates Stripe account → enables billing flow (#2216)
2. [ ] Set up Stripe products: Free (no charge), Starter $12, Pro $29, Enterprise $99
3. [ ] Implement billing dashboard showing user''s current plan + usage
4. [ ] Add BRL currency detection for Brazilian users
5. [ ] Track conversion funnel: signup → free → paid (Plausible goals)

## Related Issues

- #2216 (backend) — Stripe integration
- #2217 (email) — invoice/dunning emails
- #2218 (LGPD) — billing data handling','docs/planning/BUSINESS_MODEL_SIMULATION.md','d448adc86d1946c895c4182df3e0c51755002b1bd56d5be1f34f4e909e894cd8','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/planning/EMAIL_TRANSACTIONAL.md','project_doc','doc://simplicio-runtime/docs/planning/EMAIL_TRANSACTIONAL.md','doc: Email Transactional Planning — Issue #2217','# Email Transactional Planning — Issue #2217

## Requirement

Send transactional emails reliably for:
- Welcome / onboarding
- Invoice receipts
- Payment failed / dunning sequence
- Password reset / magic link
- Plan upgrade/downgrade confirmation

## Provider Decision: Resend.com (RECOMMENDED)

### Why Resend

| Criterion | Resend | SendGrid | Postmark | Mailgun |
|-----------|--------|----------|----------|---------|
| Free tier | 3K/mo | 100/day | 100/mo | 5K/mo (3 months only) |
| API simplicity | Excellent | Complex | Good | Good |
| React Email support | Native | No | No | No |
| Deliverability | High | High | Very high | High |
| Cost (beyond free) | $20/mo (50K) | $19.95/mo (50K) | $15/mo (10K) | $35/mo (50K) |
| DKIM/SPF setup | Automatic | Manual | Manual | Manual |

**Decision: Resend** — simplest API, native React Email templates, excellent free tier, automatic deliverability setup.

## Template Catalogue

### 1. Welcome (`welcome`)
- **Trigger:** New user signup (Supabase Auth `user.created`)
- **Content:** Welcome message, quick-start link, support contact
- **Locale:** Sent in user''s chosen language (see #2225)

### 2. Invoice Receipt (`invoice_paid`)
- **Trigger:** Stripe `invoice.payment_succeeded`
- **Content:** Invoice number, plan, amount, billing period, PDF link
- **Legal:** Must include company name, address, VAT/CNPJ (LGPD #2218)

### 3. Payment Failed — Dunning Sequence (`payment_failed`)
- **Day 0:** "Your payment failed" — soft reminder, retry link
- **Day 3:** "Second attempt failed" — update card CTA
- **Day 7:** "Account will be downgraded" — urgency
- **Day 10:** "Account downgraded to Free" — confirmation
- **Trigger:** Stripe `invoice.payment_failed`

### 4. Password Reset (`password_reset`)
- **Trigger:** User requests reset (Supabase Auth built-in or custom)
- **Content:** Reset link (expires 1h), security notice
- **Note:** Supabase can handle this natively; only override for branding

### 5. Magic Link (`magic_link`)
- **Trigger:** Passwordless login request
- **Content:** One-click login link (expires 15min)

### 6. Plan Changed (`plan_changed`)
- **Trigger:** Stripe `customer.subscription.updated`
- **Content:** Old plan → new plan, effective date, what changed

### 7. Account Deletion Confirmation (`account_deleted`)
- **Trigger:** User invokes DELETE /api/users/me
- **Content:** Confirmation that data was deleted, LGPD reference
- **Required by:** #2218

## Implementation

### Directory Structure

```
site/
  api/
    emails/
      templates/
        welcome.tsx
        invoice_paid.tsx
        payment_failed.tsx
        password_reset.tsx
        magic_link.tsx
        plan_changed.tsx
        account_deleted.tsx
      send.ts          — shared Resend client + dispatch helper
```

### Send Helper (TypeScript)

```typescript
import { Resend } from ''resend'';

const resend = new Resend(process.env.RESEND_API_KEY);

export async function sendEmail(
  to: string,
  template: string,
  data: Record<string, unknown>,
  locale = ''en''
) {
  const { subject, body } = await renderTemplate(template, data, locale);
  return resend.emails.send({
    from: ''Simplicio <hello@simplicio.app>'',
    to,
    subject,
    react: body,
  });
}
```

### Localization Strategy

Templates use the same i18n key system as the site (#2225):
- Strings stored in `site/js/i18n.js` key format: `email.welcome.subject`
- Template receives `locale` param from user profile
- Fallback: `en`

## DNS / Deliverability Setup

Resend provides DKIM + SPF records automatically on domain verification:

1. Add domain `simplicio.app` in Resend dashboard
2. Add DNS records:
   - `TXT resend._domainkey.simplicio.app` (DKIM)
   - `TXT simplicio.app` (SPF: `v=spf1 include:_spf.resend.com ~all`)
3. Verify in Resend (takes < 5 min)

## Environment Variables Required

```
RESEND_API_KEY=re_...
EMAIL_FROM=hello@simplicio.app
```

## Blockers

- [ ] Backend #2216 must exist (Edge Functions to call Resend)
- [ ] Wesley creates Resend account at resend.com (free)
- [ ] RESEND_API_KEY added to Vercel env
- [ ] Domain DNS updated for DKIM/SPF

## Effort Estimate

| Task | Effort |
|------|--------|
| Resend setup + DNS | 1h |
| Base template (brand, layout) | 2h |
| All 7 templates | 4h |
| Trigger wiring (Stripe + Supabase webhooks) | 3h |
| Dunning sequence (3 emails + scheduling) | 2h |

## Related Issues

- Blocked by: #2216 (backend)
- Blocks: nothing (but #2218 needs account_deleted template)','docs/planning/EMAIL_TRANSACTIONAL.md','af8f6cb78175437488f6019018b26046691039158d47a4165cf24f21b7cc8af2','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/planning/INTEGRATIONS_EPIC.md','project_doc','doc://simplicio-runtime/docs/planning/INTEGRATIONS_EPIC.md','doc: Integrations Epic Planning — Issue #2221','# Integrations Epic Planning — Issue #2221

## Overview

Each integration adds a skill (user-facing, in `.simplicio-loop/skills/`) and a Rust
adapter module (`src/integrations/<name>/`). The adapter handles OAuth/API auth,
request/response mapping, and exposes a typed Rust API. The skill wraps it in
natural language.

## Architecture Pattern

```
User → simplicio chat → skill_<name>.rs → adapter/<name>/mod.rs → External API
                                    ↓
                              action_gate (if mutating)
                                    ↓
                              HBP evidence ledger
```

Every adapter follows this interface:

```rust
pub trait Integration: Send + Sync {
    fn name(&self) -> &str;
    fn capabilities(&self) -> Vec<Capability>;  // list, read, write, webhook
    async fn authenticate(&self, ctx: &AuthContext) -> Result<Token>;
    async fn execute(&self, action: Action, token: &Token) -> Result<ActionResult>;
}
```

OAuth tokens stored encrypted in `.simplicio-loop/tokens/<integration>.enc` (AES-256-GCM, key = machine secret).

## Integration Catalogue

Priority is ordered by user value (highest first).

### Priority 1 — Core Productivity

#### 1.1 Google Calendar
- **Value:** Schedule tasks, set reminders, check availability
- **Auth:** OAuth2 (`calendar.events`, `calendar.readonly`)
- **Skills:** "add event", "what''s on my calendar today", "find a free slot"
- **Effort:** 3h adapter + 2h skill

#### 1.2 Gmail
- **Value:** Read, summarize, draft, send emails from chat
- **Auth:** OAuth2 (`gmail.readonly`, `gmail.send`, `gmail.compose`)
- **Skills:** "summarize unread emails", "draft reply to X", "send email to Y"
- **Effort:** 4h adapter + 3h skill
- **Gate:** `gmail.send` → action_gate (mutating)

#### 1.3 Notion
- **Value:** Create notes, read pages, update databases
- **Auth:** Notion OAuth (integration token)
- **Skills:** "create note about X", "find notes about Y", "update task Z"
- **Effort:** 3h adapter + 2h skill

#### 1.4 Slack
- **Value:** Post messages, read channels, set status
- **Auth:** Slack OAuth (`chat:write`, `channels:read`, `users.profile:write`)
- **Skills:** "post to #general", "what was said in #eng today"
- **Effort:** 3h adapter + 2h skill
- **Gate:** `chat:write` → action_gate

### Priority 2 — Messaging

#### 2.1 Telegram
- **Value:** Send/receive messages via Simplicio (already partially in gateway/)
- **Auth:** Bot token
- **Status:** Gateway module exists in `src/`; needs skill wiring
- **Effort:** 1h wiring

#### 2.2 WhatsApp
- **Value:** Send messages, read recent chats
- **Auth:** WhatsApp Business API or Baileys (unofficial)
- **Note:** Official API requires Meta Business approval; Baileys = unofficial
- **Skills:** "send WhatsApp to X", "read last message from Y"
- **Effort:** 5h (API complexity) + 2h skill

#### 2.3 Discord
- **Value:** Post to channels, read recent messages
- **Auth:** Bot token + OAuth
- **Status:** Gateway module exists; needs skill wiring
- **Effort:** 1h wiring

### Priority 3 — Storage & Files

#### 3.1 Google Drive
- **Value:** Upload, download, search files
- **Auth:** OAuth2 (`drive.file`, `drive.readonly`)
- **Skills:** "upload this file to Drive", "find Drive files about X"
- **Effort:** 3h adapter + 2h skill

#### 3.2 Dropbox
- **Value:** Same as Drive
- **Auth:** OAuth2
- **Effort:** 3h adapter + 2h skill

#### 3.3 Apple Notes (macOS only)
- **Value:** Create/read notes via AppleScript
- **Auth:** Local (no OAuth; AppleScript permission)
- **Platform:** macOS only
- **Effort:** 2h adapter + 1h skill

### Priority 4 — Smart Home

#### 4.1 Home Assistant
- **Value:** Control lights, thermostat, sensors from chat
- **Auth:** Long-lived access token (user-provided)
- **Skills:** "turn off living room lights", "what''s the temperature"
- **Effort:** 3h adapter + 3h skill
- **Gate:** All state mutations → action_gate

#### 4.2 Philips Hue (direct)
- **Value:** Light control without Home Assistant
- **Auth:** Local bridge token
- **Effort:** 2h adapter + 1h skill

### Priority 5 — Entertainment & Utilities

#### 5.1 Spotify
- **Value:** Play/pause, skip, search music, get current track
- **Auth:** OAuth2 (`user-read-playback-state`, `user-modify-playback-state`)
- **Skills:** "play X", "skip", "what''s playing"
- **Effort:** 2h adapter + 2h skill

#### 5.2 Weather (OpenWeatherMap)
- **Value:** Get current weather, forecast
- **Auth:** API key (no OAuth)
- **Skills:** "what''s the weather in São Paulo", "will it rain tomorrow"
- **Effort:** 1h adapter + 1h skill

#### 5.3 Toggl (time tracking)
- **Value:** Start/stop timers, view reports
- **Auth:** API key
- **Skills:** "start timer for X", "how many hours did I work today"
- **Effort:** 2h adapter + 1h skill

## File Structure

```
src/integrations/
  mod.rs                  — trait definitions, token store
  google_calendar/
    mod.rs
    auth.rs
    events.rs
  gmail/
    mod.rs
    auth.rs
    messages.rs
  notion/
    mod.rs
    auth.rs
    pages.rs
  slack/
    mod.rs
    auth.rs
    messages.rs
  home_assistant/
    mod.rs
    auth.rs
    entities.rs
  spotify/
    mod.rs
    auth.rs
    playback.rs
  weather/
    mod.rs               — OpenWeatherMap, no auth module needed
  ...

.simplicio-loop/skills/
  skill_calendar.rs
  skill_gmail.rs
  skill_notion.rs
  skill_slack.rs
  skill_home_assistant.rs
  skill_spotify.rs
  skill_weather.rs
  ...
```

## Priority Roadmap

| Wave | Integrations | Est. total effort |
|------|-------------|-------------------|
| Wave 1 | Weather, Telegram (wiring), Discord (wiring) | 5h |
| Wave 2 | Google Calendar, Notion, Spotify | 14h |
| Wave 3 | Gmail, Slack | 10h |
| Wave 4 | Google Drive, Dropbox, Home Assistant | 13h |
| Wave 5 | WhatsApp, Apple Notes, Philips Hue, Toggl | 13h |

## Related Issues

- Sub-issues of: #2221
- Depends on: #2229 (SDK/Plugin System — adapter format)
- Depends on: action_gate (#231, already implemented)','docs/planning/INTEGRATIONS_EPIC.md','96c52e2efdf40d96779ee8c54409218328267a70bb4d7a0ed04b2d2dea8fc3c3','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/planning/LGPD_GDPR_COMPLIANCE.md','project_doc','doc://simplicio-runtime/docs/planning/LGPD_GDPR_COMPLIANCE.md','doc: LGPD/GDPR Compliance Planning — Issue #2218','# LGPD/GDPR Compliance Planning — Issue #2218

## Scope

Simplicio collects user data via:
1. Website (site/) — analytics, cookies, contact form
2. Backend API (issue #2216) — accounts, billing, usage events
3. Desktop app — local usage, optional telemetry

Primary legal frameworks:
- **LGPD** (Lei Geral de Proteção de Dados — Brazil, Lei 13.709/2018)
- **GDPR** (General Data Protection Regulation — EU, Regulation 2016/679)

Both frameworks share the same core principles; LGPD was modeled on GDPR.

## Data Inventory

| Data Element | Source | Basis | Retention | Sensitive? |
|---|---|---|---|---|
| Email address | Signup | Contract | Active + 90d | No |
| Name | Profile | Contract | Active + 90d | No |
| IP address | Auth logs | Legitimate interest | 30 days | No |
| Billing address | Stripe | Contract / legal obligation | 5 years (tax) | No |
| Payment method | Stripe (tokenized) | Contract | Stripe holds | Yes |
| Usage events | Backend | Legitimate interest | 12 months | No |
| Locale preference | Profile | Contract | Active | No |
| Analytics (page views) | Plausible/Vercel | Legitimate interest | 12 months | No |

**No special categories** (health, biometric, political, etc.) are collected.

## User Rights Implementation

### Right of Access (Art. 18 LGPD / Art. 15 GDPR)
- Endpoint: `GET /api/users/me/export`
- Returns: JSON of all data held (profile, subscriptions, usage events)
- Deadline: 72 hours from request (LGPD art. 18 §3)
- UI: "Export my data" button in account settings

### Right of Correction (Art. 18 II LGPD / Art. 16 GDPR)
- Endpoint: `PATCH /api/users/me`
- UI: Editable profile form

### Right of Deletion (Art. 18 IV LGPD / Art. 17 GDPR) — CRITICAL
- Endpoint: `DELETE /api/users/me`
- Actions:
  1. Cancel active Stripe subscription (if any)
  2. Delete Supabase Auth user (cascades to all tables via RLS)
  3. Delete usage_events for user_id
  4. Anonymize billing records (replace email with `deleted@...`, keep amount for tax)
  5. Send `account_deleted` confirmation email (#2217)
- Exceptions: billing records retained 5 years per Brazilian tax law (RFB)
- Blocked by: #2216 (backend must exist)

### Right of Portability (Art. 18 V LGPD / Art. 20 GDPR)
- Same as export endpoint above, but in CSV format on request

### Right to Object / Opt-out (Art. 18 II LGPD / Art. 21 GDPR)
- Analytics: respect `DNT` header; Plausible is privacy-first (no cookies)
- Marketing emails: unsubscribe link in every email footer

## Required Documents

### Privacy Policy (`site/privacidade.html` — already exists, needs update)

Must include:
- [ ] Data controller identity (company name, CNPJ if applicable, address)
- [ ] DPO contact (or person responsible — `privacidade@simplicio.app`)
- [ ] List of data collected and purpose
- [ ] Legal basis for each processing activity
- [ ] Data retention periods
- [ ] List of sub-processors (Supabase, Stripe, Resend, Vercel)
- [ ] International transfer notice (Supabase/Stripe servers outside Brazil)
- [ ] User rights and how to exercise them
- [ ] Cookie policy section

### Terms of Service (`site/termos.html` — already exists, needs review)
- Must reference Privacy Policy
- Must state governing law (Brazilian law, LGPD)

## Cookie Consent Banner

**Current state:** No consent banner visible in `site/index.html`.

**Required:** Cookie consent for any non-essential cookies.

**Recommended approach:** Minimal banner, since Plausible Analytics is cookieless:
- No consent needed for Plausible (no cookies, no fingerprinting)
- Consent needed if: Google Analytics, Hotjar, Facebook Pixel, or retargeting pixels are added
- Implement as a simple HTML/JS banner stored in `site/partials/cookie-banner.html`

**Banner copy (PT-BR):**
> "Usamos cookies essenciais para o funcionamento do site. [Aceitar] [Configurações]"

## Data Processing Agreements (DPA)

Must sign DPAs with all sub-processors who handle personal data:

| Sub-processor | DPA status | Link |
|---|---|---|
| Stripe | Available automatically | stripe.com/dpa |
| Supabase | Available on request | supabase.com/privacy |
| Resend | Available on request | resend.com/legal/dpa |
| Vercel | Available automatically | vercel.com/legal/dpa |

**Action:** Download and archive each DPA in `docs/legal/dpa/`.

## International Data Transfers

Supabase (US), Stripe (US), Resend (US), Vercel (US) — all outside Brazil.

LGPD art. 33 permits transfer when:
- The destination country provides adequate protection (not yet designated for US), OR
- Standard contractual clauses are in place (DPAs above cover this), OR
- Data subject''s consent is obtained

**Action:** DPAs + explicit consent in Privacy Policy covers this.

## Implementation Checklist

- [ ] Update `site/privacidade.html` with all required sections
- [ ] Review `site/termos.html` for LGPD alignment
- [ ] Implement `DELETE /api/users/me` (#2216)
- [ ] Implement `GET /api/users/me/export` (#2216)
- [ ] Add cookie banner (if non-essential cookies are ever added)
- [ ] Download and archive Stripe/Supabase/Resend/Vercel DPAs
- [ ] Create `privacidade@simplicio.app` email for DPO contact
- [ ] Add "Export my data" and "Delete account" to user dashboard

## Blockers

- [ ] #2216 (backend) — deletion and export endpoints require a server
- [ ] Company legal entity info (CNPJ, address) for Privacy Policy
- [ ] Wesley designates a DPO or responsible contact

## Effort Estimate

| Task | Effort |
|------|--------|
| Privacy Policy rewrite | 3h |
| Terms of Service review | 1h |
| Delete/export endpoints | 3h |
| Cookie banner | 1h |
| DPA collection + archiving | 1h |','docs/planning/LGPD_GDPR_COMPLIANCE.md','e6d81b0e619281619f31af702eab1470d05c1397857648c0bf254a684e141ea7','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/planning/SDK_DESIGN.md','project_doc','doc://simplicio-runtime/docs/planning/SDK_DESIGN.md','doc: Public SDK & Plugin System Planning — Issue #2229','# Public SDK & Plugin System Planning — Issue #2229

## Goal

Let third-party developers extend Simplicio without needing access to the
Rust source. They should be able to:
1. Build plugins (new skills, integrations, tools)
2. Call Simplicio programmatically from their apps
3. Publish plugins to a community marketplace

## Public REST API

Base URL: `https://api.simplicio.app/v1` (backed by #2216 Edge Functions)

### Endpoints

```
GET  /api/v1/skills              — list available skills
POST /api/v1/run                 — run a skill or command
GET  /api/v1/status/:job_id      — get async job status
GET  /api/v1/plugins             — list installed plugins
POST /api/v1/plugins/install     — install a plugin by name or URL
GET  /api/v1/memory              — query neural memory
POST /api/v1/memory              — store a memory item
GET  /api/v1/health              — health check (no auth)
```

### Authentication

All endpoints (except `/health`) require:
```
Authorization: Bearer <simplicio_api_key>
```

API keys issued per user from the dashboard (#2216). Keys prefixed `sk_live_` (production) / `sk_test_` (sandbox).

### POST /api/v1/run

Request:
```json
{
  "skill": "weather",
  "input": "What''s the weather in São Paulo?",
  "locale": "pt-BR",
  "timeout_ms": 30000
}
```

Response (sync, < 5s):
```json
{
  "job_id": "job_abc123",
  "status": "completed",
  "output": "São Paulo: 24°C, partly cloudy.",
  "tokens_used": 42,
  "latency_ms": 312
}
```

Response (async, > 5s):
```json
{
  "job_id": "job_abc123",
  "status": "running",
  "poll_url": "/api/v1/status/job_abc123"
}
```

### Rate Limits

| Plan | Requests/min | Requests/day |
|------|-------------|-------------|
| Free | 10 | 100 |
| Starter | 60 | 1000 |
| Pro | 300 | 10000 |
| Enterprise | unlimited | unlimited |

## Python SDK

### Install

```bash
pip install simplicio-sdk
```

### Usage

```python
from simplicio import Simplicio

client = Simplicio(api_key="sk_live_...")

# Run a skill
result = client.run("weather", "What''s the weather in SP?")
print(result.output)

# Memory
client.memory.store("User prefers metric units")
results = client.memory.search("units preference")

# List skills
skills = client.skills.list()
```

### Async support

```python
import asyncio
from simplicio import AsyncSimplicio

async def main():
    async with AsyncSimplicio(api_key="sk_live_...") as client:
        result = await client.run("gmail", "Summarize unread emails")
        print(result.output)

asyncio.run(main())
```

### Package structure

```
simplicio-sdk/
  pyproject.toml
  simplicio/
    __init__.py        — exports Simplicio, AsyncSimplicio
    client.py          — HTTP client (httpx)
    models.py          — RunResult, SkillInfo, MemoryItem
    skills.py          — SkillsNamespace
    memory.py          — MemoryNamespace
    plugins.py         — PluginsNamespace
    exceptions.py      — SimplicioError, RateLimitError, AuthError
  tests/
    test_client.py
```

Published to PyPI as `simplicio-sdk` (separate from `simplicio-cli`).

## Plugin Format

A plugin is a directory with a YAML manifest and one or more handlers.

### Manifest (`plugin.yaml`)

```yaml
name: simplicio-weather-openmeteo
version: 1.0.0
description: Weather via Open-Meteo (free, no API key)
author: jane@example.com
license: MIT

skills:
  - id: weather_openmeteo
    description: Get current weather and forecast
    trigger_phrases:
      - "what''s the weather"
      - "will it rain"
    handler: handler.py   # or handler.rs (compiled)
    inputs:
      - name: location
        type: string
        required: true
    output_type: text

permissions:
  - http_fetch           # allowed outbound domains
  allowed_domains:
    - api.open-meteo.com
```

### Python handler (`handler.py`)

```python
from simplicio_sdk.plugin import PluginContext, PluginResult

async def run(ctx: PluginContext) -> PluginResult:
    location = ctx.inputs["location"]
    # fetch from Open-Meteo
    data = await ctx.http.get(f"https://api.open-meteo.com/v1/forecast?...")
    return PluginResult(output=f"{location}: {data[''current''][''temperature_2m'']}°C")
```

### Rust handler (optional, compiled)

```rust
// handler.rs — compiled to a cdylib, loaded via dlopen
#[no_mangle]
pub extern "C" fn run(ctx: *const PluginContext) -> *mut PluginResult {
    // ...
}
```

### Plugin sandbox

Python plugins run in a restricted subprocess:
- No filesystem access outside plugin dir
- No subprocess spawning
- Network restricted to `allowed_domains` in manifest
- Memory limit: 128 MB
- Timeout: configurable (default 30s)

## Marketplace

### Model: GitHub-based (MVP)

A public GitHub repo `simplicio-plugins` acts as the registry:

```
simplicio-plugins/
  plugins/
    weather-openmeteo/
      plugin.yaml
      handler.py
      README.md
    calendar-ical/
      ...
  registry.json          — auto-generated index
```

**Submit a plugin:** Open a PR to `simplicio-plugins`. Maintainer reviews and merges. `registry.json` is regenerated on merge via GitHub Actions.

**Install a plugin:**
```bash
simplicio plugin install weather-openmeteo
# or from URL:
simplicio plugin install github:jane/simplicio-my-plugin
```

**Future (v2):** Hosted registry at `plugins.simplicio.app` with ratings, download counts, security scanning.

## Implementation Phases

| Phase | Scope | Effort |
|-------|-------|--------|
| 1 | REST API endpoints (skills, run, status, health) | 4h |
| 2 | API key issuance in dashboard (#2216) | 2h |
| 3 | Python SDK (`simplicio-sdk`) | 6h |
| 4 | Plugin manifest format + loader | 4h |
| 5 | Plugin sandbox (subprocess + network restriction) | 4h |
| 6 | `simplicio plugin install/list/remove` CLI commands | 3h |
| 7 | GitHub marketplace repo + registry.json CI | 2h |
| 8 | SDK documentation + examples | 4h |

## Blockers

- #2216 (backend) — API key issuance requires user accounts
- Plugin marketplace repo creation (Wesley must create `simplicio-plugins` on GitHub)

## Related Issues

- #2221 (integration','docs/planning/SDK_DESIGN.md','f92f7386aa51feaa29d6d1772b41e9310f550acee1b386c34ea85fbf2fdd8241','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/planning/SITE_I18N.md','project_doc','doc://simplicio-runtime/docs/planning/SITE_I18N.md','doc: Site & Docs i18n Planning — Issue #2225','# Site & Docs i18n Planning — Issue #2225

## Current State

The site already has an i18n foundation:

- `site/js/i18n.js` — exists (detected in repo)
- `site/index.html` — main site (Portuguese/English content mix)
- `site/privacidade.html` — privacy policy (Portuguese only)
- `site/termos.html` — terms of service (Portuguese only)

The desktop app also has language pack support (`apps/simplicio-desktop/`) based
on git history (commit: "downloadable i18n language packs + language selector" #2185).

**What''s missing:**
1. Full translation coverage for all site pages (not just `index.html`)
2. Docs (`docs/`) — English only, no translation mechanism
3. Legal pages (`privacidade.html`, `termos.html`) — Portuguese only
4. Consistent key namespace across site + desktop app

## Supported Languages (Target)

15 languages, consistent with the desktop app''s language packs:

| Code | Language | Status |
|------|----------|--------|
| `en` | English | Source (complete) |
| `pt-BR` | Portuguese (Brazil) | Primary market (complete) |
| `es` | Spanish | High priority |
| `fr` | French | High priority |
| `de` | German | High priority |
| `it` | Italian | Medium |
| `nl` | Dutch | Medium |
| `pl` | Polish | Medium |
| `tr` | Turkish | Medium |
| `ru` | Russian | Medium |
| `ar` | Arabic | Low (RTL — extra effort) |
| `hi` | Hindi | Low |
| `zh` | Chinese (Simplified) | Low |
| `ja` | Japanese | Low |
| `ko` | Korean | Low |

## Architecture Decision

### Current approach (inferred from `site/js/i18n.js`)

Likely a JS object keyed by locale → string map, loaded client-side. Extend this.

### Recommended: JSON files per locale, loaded by i18n.js

```
site/
  i18n/
    en.json
    pt-BR.json
    es.json
    fr.json
    de.json
    ...
```

Each file:
```json
{
  "nav.home": "Home",
  "nav.pricing": "Pricing",
  "hero.title": "Your intelligent assistant",
  "hero.cta": "Download Free",
  "email.welcome.subject": "Welcome to Simplicio",
  ...
}
```

`i18n.js` loads the correct file on page load based on:
1. `?lang=` query param
2. `localStorage[''simplicio_locale'']`
3. `navigator.language` auto-detect
4. Fallback: `en`

### Legal pages

`privacidade.html` and `termos.html` are long-form legal text.
Recommended: one file per locale:
```
site/
  legal/
    privacidade.en.html
    privacidade.pt-BR.html
    termos.en.html
    termos.pt-BR.html
```
Redirect `site/privacidade.html` based on locale.

### Docs

Docs are Markdown in `docs/`. Translation of docs is low priority.
Recommended approach when docs are published:
- English is canonical
- Machine-translate to PT-BR + ES via DeepL API for launch
- Community translations for other languages via PR

## Key Namespaces

| Namespace | Usage |
|-----------|-------|
| `nav.*` | Navigation links |
| `hero.*` | Hero section |
| `features.*` | Feature cards |
| `pricing.*` | Pricing section |
| `footer.*` | Footer |
| `auth.*` | Login/signup page |
| `dashboard.*` | User dashboard |
| `email.*` | Email templates (shared with #2217) |
| `legal.*` | Privacy/terms page titles and summaries |
| `error.*` | Error messages |

## RTL Support (Arabic)

Arabic requires:
- `dir="rtl"` on `<html>` when locale = `ar`
- CSS: use `margin-inline-start` not `margin-left` throughout
- Estimated extra effort: +4h

## Gap Analysis

| Item | Status | Gap |
|------|--------|-----|
| `site/index.html` strings | Partial (i18n.js exists) | Audit all hardcoded strings |
| `site/privacidade.html` | PT-BR only | Add EN, translate to ES/FR |
| `site/termos.html` | PT-BR only | Add EN, translate to ES/FR |
| Login/auth pages | Not yet built (#2216) | Build with i18n from day 1 |
| User dashboard | Not yet built (#2216) | Build with i18n from day 1 |
| Email templates | Not yet built (#2217) | Use same locale key system |
| Docs | EN only | MT for PT-BR/ES at launch |

## Implementation Plan

| Phase | Scope | Effort |
|-------|-------|--------|
| 1 | Audit `index.html`, extract all hardcoded strings to `en.json` | 3h |
| 2 | PT-BR translation of all keys (native speaker review) | 2h |
| 3 | Machine-translate ES, FR, DE via DeepL | 2h |
| 4 | Legal pages: EN versions of privacidade + termos | 2h |
| 5 | Locale switcher UI (flag dropdown in nav) | 2h |
| 6 | Auto-detect from `navigator.language` | 1h |
| 7 | Remaining 9 languages (MT) | 3h |
| 8 | RTL support for Arabic | 4h |

## Blockers

- None — can start independently of #2216
- Legal page EN translation needs Wesley''s review (legal content)

## Related Issues

- #2217 (email) uses same i18n key system
- #2216 (backend) — auth/dashboard pages must be built with i18n from day 1
- #2218 (LGPD) — privacy/terms pages must be translated','docs/planning/SITE_I18N.md','c74dffdc876ff725489e335ca14c87921438fc8b4bca2e29aa812c73ff954628','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/plans/2026-06-12-simplicio-hermes-plugin.md','project_doc','doc://simplicio-runtime/docs/plans/2026-06-12-simplicio-hermes-plugin.md','doc: Simplicio Plugin para Hermes e OpenClaw — Plano de Implementação','# Simplicio Plugin para Hermes e OpenClaw — Plano de Implementação

> **Para Hermes:** Usar subagent-driven-development para implementar tarefa por tarefa.

**Objetivo:** Transformar Simplicio num plugin instalável para Hermes Agent e OpenClaw, onde Hermes invoca Simplicio para executar tarefas e o ensina quando ele falha.

**Arquitetura:**

```
┌─────────────────┐      ACP (stdio)      ┌────────────────┐
│  Hermes Agent   │ ◄──────────────────► │  Simplicio     │
│  (Python)       │  JSON-RPC via stdin/  │  (Rust binary) │
│                 │  stdout               │                │
│  plugins/       │                       │  acp_adapter/  │
│  simplicio/     │  prompt message       │  mod.rs        │
│                 │  ─────────────►       │  (prompt →     │
│  simplicio_run  │  teach (skill save)   │   chat reply)  │
│  simplicio_teach│  ◄─────────────       │                │
└─────────────────┘                       └────────────────┘

┌─────────────────┐      Plugin SDK         ┌────────────────┐
│  OpenClaw       │ ◄──────────────────────►│  Simplicio     │
│  (TypeScript)   │  (via extensão)         │  Extension     │
└─────────────────┘                         └────────────────┘
```

**Fluxo de aprendizado:**
1. Hermes envia tarefa → Simplicio via ACP `prompt`
2. Simplicio executa (ou falha)
3. Se falhou → Hermes cria uma skill/lição e envia via `simplicio_teach`
4. Simplicio persiste no seu próprio sistema de memória/skills
5. Próxima execução, Simplicio já sabe fazer

**Tech Stack:**
- Simplicio: Rust (ACP stdio mode)
- Hermes: Python (plugin system + plugin_utils + ACP stdio)
- OpenClaw: TypeScript (plugin SDK + openclaw.plugin.json)

---

## Tarefas

### Tarefa 1: Adicionar modo `acp stdio` no Simplicio

**Objetivo:** Criar um modo contínuo onde Simplicio lê JSON-RPC do stdin e escreve no stdout, mantendo sessão ativa entre chamadas.

**Arquivos:**
- Create: `src/acp_adapter/stdio.rs` (~80 linhas)
- Modify: `src/acp_adapter/mod.rs` (+5 linhas)
- Modify: `src/main.rs` (+15 linhas para comando `acp stdio`)

**Passo 1: Adicionar módulo stdio.rs**

```rust
// src/acp_adapter/stdio.rs
//! ACP stdio server — reads JSON-RPC from stdin, writes to stdout.
//! Keeps session state across prompts (one session per connection).

use std::io::{self, BufRead, Write};
use std::path::Path;
use super::{ACPAdapter, JsonRpcMessage};

pub fn run_stdio(repo: &Path) -> Result<(), String> {
    let adapter = ACPAdapter::new(repo);
    let stdin = io::stdin();
    let mut session_id = String::new();

    for line in stdin.lock().lines() {
        let raw = line.map_err(|e| format!("stdio read error: {e}"))?;
        if raw.trim().is_empty() {
            continue;
        }
        let response = adapter.handle_message(&raw)?;
        if !response.is_empty() {
            println!("{response}");
            io::stdout().flush().map_err(|e| format!("flush error: {e}"))?;
        }
        // Track session ID from new_session response
        if raw.contains("\"new_session\"") && !response.is_empty() {
            if let Some(sid) = extract_session_id(&response) {
                session_id = sid;
            }
        }
    }
    Ok(())
}

fn extract_session_id(json: &str) -> Option<String> {
    // Minimal: extract "sessionId":"..." from response
    json.find("\"sessionId\":\"")
        .and_then(|start| {
            let s = start + "\"sessionId\":\"".len();
            let rest = &json[s..];
            rest.find(''"'').map(|end| rest[..end].to_string())
        })
}
```

**Passo 2: Exportar `stdio` do mod.rs**

```rust
// src/acp_adapter/mod.rs — adicionar:
pub mod stdio;
```

**Passo 3: Adicionar comando `acp stdio` no main.rs**

```rust
// No bloco match acp_command(), adicionar:
"stdio" => {
    acp_adapter::stdio::run_stdio(&repo)?;
    Ok(())
}
```

E no help:
```rust
"stdio" => {
    println!("  stdio               ACP stdio server (stdin/stdout loop)");
}
```

**Passo 4: Verificar compilação**

Run: `cargo build --release --locked`
Expected: build bem-sucedido

**Passo 5: Testar manualmente**

```bash
echo ''{"jsonrpc":"2.0","id":"1","method":"initialize","params":{}}'' | ./target/release/simplicio acp stdio
# Expected: {"jsonrpc":"2.0","id":"1","result":{"protocolVersion":"1.0","server":"simplicio-acp"}}
```

**Passo 6: Commit**

```bash
git add src/acp_adapter/stdio.rs src/acp_adapter/mod.rs src/main.rs
git commit -m "feat: add simplicio acp stdio mode for ACP stdio transport"
```

---

### Tarefa 2: Criar plugin Hermes `simplicio` — estrutura

**Objetivo:** Criar a estrutura do plugin Hermes com `plugin.yaml` e `__init__.py` vazio.

**Arquivos:**
- Create: `plugins/simplicio/plugin.yaml`
- Create: `plugins/simplicio/__init__.py`

**Passo 1: Criar plugin.yaml**

```yaml
name: simplicio
version: 1.0.0
description: >
  Simplicio runtime integration — delegate tasks to the local Simplicio
  binary via ACP stdio. Hermes sends tasks via simplicio_run, and teaches
  Simplicio new skills via simplicio_teach when it fails.
author: Simplicio
kind: standalone
requires_env:
  - name: SIMPLICIO_PATH
    description: "Path to the simplicio binary (default: simplicio on PATH)"
    prompt: "Simplicio binary path"
    password: false
provides_tools:
  - simplicio_run
  - simplicio_teach
provides_hooks:
  - post_tool_call
```

**Passo 2: Criar __init__.py**

```python
"""Simplicio runtime plugin — delegate tasks to the local Simplicio binary.

Registers tools:
- simplicio_run: send a task to Simplicio via ACP
- simplicio_teach: save a skill/lesson to Simplicio''s memory

Requires ``simplicio`` on PATH (or SIMPLICIO_PATH env var).
"""

from __future__ import annotations

from plugins.simplicio.tools import (
    SIMPLICIO_RUN_SCHEMA,
    SIMPLICIO_TEACH_SCHEMA,
    _check_simplicio_available,
    _handle_simplicio_run,
    _handle_simplicio_teach,
)


def register(ctx) -> None:
    """Register Simplicio tools. Called once by the plugin loader."""
    ctx.register_tool(
        name="simplicio_run",','docs/plans/2026-06-12-simplicio-hermes-plugin.md','58bea6669b32417b3827540f1ea6e4ef5be3e6d2a4ccfd5a604d40f3cf561686','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/plans/2026-06-16-install-autocomplete.md','project_doc','doc://simplicio-runtime/docs/plans/2026-06-16-install-autocomplete.md','doc: Install Auto-Complete Plan','# Install Auto-Complete Plan

> **Goal:** Make `simplicio install` (and `simplicio doctor --install`) automatically download local model, init memory DB, run runtime map, and install orient gate — so users have ALL features immediately.

**Architecture:** Add an `install` subcommand that runs a complete setup pipeline. Modify `doctor --repair` (already wired) to auto-download the local model if missing. Add a first-run check in `main()` that auto-runs install if `.simplicio-loop/` is empty.

**Files:**
- Modify: `src/main.rs` — add `install` command dispatch, auto-install check at startup
- Modify: `src/doctor.rs` — ensure `--repair` downloads model + inits memory

---

### Task 1: Survey current doctor_run_checks and repair_local_layout

**Objective:** Understand what `doctor --repair` already does and what''s missing.

**Files:** `src/main.rs:4516-4840` (doctor fn), `src/main.rs:47863+` (repair_local_layout), `src/main.rs:56775+` (doctor_run_checks)

**Steps:**
1. Read `doctor()` function to see current --repair flow
2. Read `repair_local_layout()` to see what it repairs
3. Read `doctor_run_checks()` to see what checks exist
4. Identify gaps: missing model download, missing memory-db init, missing orient gate

**Output:** List of gaps found.

---

### Task 2: Add model download to repair_local_layout

**Objective:** When `doctor --repair` finds local model missing, download it automatically.

**Files:**
- Modify: `src/main.rs` around `repair_local_layout()`

**Approach:**
- If `~/.local/share/simplicio/models/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf` doesn''t exist:
  - Download from HuggingFace (or use `simplicio model download`)
  - Verify checksum
  - Write model manifest

---

### Task 3: Add memory-db init to repair_local_layout

**Objective:** After model download, initialize the neural memory SQLite with schema.

**Files:**
- Modify: `src/main.rs` around `repair_local_layout()`

**Approach:**
- If `~/.simplicio-loop/memory/simplicio-memory.sqlite` doesn''t exist or has no schema:
  - Call `memory-db init` programmatically or run the schema SQL directly
  - Import default skills

---

### Task 4: Add orient gate install to repair flow

**Objective:** Install `.claude/hooks/orient-gate.sh` that enforces `runtime map` before direct file reads.

**Files:**
- Create: `.claude/hooks/orient-gate.sh`

**Approach:**
- Write the bash hook that checks if `runtime map` has been run this session
- Block raw read/grep/find if not

---

### Task 5: Add first-run auto-install check in main()

**Objective:** On first invokation, auto-run install if `.simplicio-loop/` is empty.

**Files:**
- Modify: `src/main.rs` around the `main()` function

**Approach:**
- After parsing args but before dispatch, check if `.simplicio-loop/` exists and has content
- If empty/fresh, print "First run — running auto-install..." and call `doctor --repair`
- Only do this for non-install/doctor commands (don''t recurse)

---

### Task 6: Build, commit, push, PR

**Objective:** Verify compilation, commit changes, push to remote, open PR.

**Steps:**
1. `cargo build 2>&1 | tail -20`
2. `git add -A && git commit -m "fix(install): auto-complete setup on first run"`
3. `git push origin HEAD`
4. `gh pr create --fill`','docs/plans/2026-06-16-install-autocomplete.md','dfeb19bf6d189e18bd413034cf53f75016b03cbe175a31b0ed5971b4ad51ed0d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/policies/TWO_REVIEWS_POLICY.md','project_doc','doc://simplicio-runtime/docs/policies/TWO_REVIEWS_POLICY.md','doc: Two-Reviews Policy','# Two-Reviews Policy

**Issue:** #2208  
**Status:** Active  
**Effective:** 2026-06-18  

## Rule

Every pull request merged into `main` requires **two distinct approvals** before merge:

| Review Type | Reviewer Responsibility |
|-------------|------------------------|
| **Code Review** | Correctness, safety, architecture, naming, test coverage, clippy clean, no regressions in logic. |
| **QA Review** | Acceptance criteria verified, dogfood run passes, no observable regression in runtime behavior, edge cases exercised. |

A PR with only one approval — even from the repo owner — must not be merged until the second approval is recorded.

## Rationale

The Simplicio quality bar is "**it works, not just compiles**" (see CLAUDE.md — Quality Delivery program, épica #250). A single reviewer can miss behavioral regressions that only surface when the binary is actually run. The two-review split forces a separation of concerns: the code reviewer focuses on the diff; the QA reviewer focuses on running evidence.

## Roles

- **Code Reviewer** — any engineer with read access to the repo who has read the diff in full.
- **QA Reviewer** — any engineer (can be the same person for solo projects, on a separate review pass) who has run `cargo test`, `cargo clippy --release`, and exercised the feature manually or via `simplicio deliver check`.

For a solo project, the author may serve as QA Reviewer if they document the run evidence in the PR description (binary version, command run, observed output).

## Enforcement

- GitHub branch protection on `main` requires **2 approving reviews** before merge.
- The `CODEOWNERS` file (`.github/CODEOWNERS`) ensures `@wesleysimplicio` is a required reviewer on every change.
- CI (`.github/workflows/`) must pass before merge is permitted.

## Exceptions

Hotfixes for production-breaking regressions may be merged with one approval if:

1. The second reviewer is notified synchronously (Slack/Discord/message) and gives verbal approval.
2. A follow-up issue is opened within 24 hours to complete the formal QA review.
3. The PR description documents the exception and links the follow-up issue.

## Checklist for Reviewers

### Code Review

- [ ] Does the diff match the issue''s stated acceptance criteria?
- [ ] Are new public symbols documented with `///` doc comments?
- [ ] Is `unsafe` justified with a `// SAFETY:` comment?
- [ ] Does `cargo clippy --release` pass with zero new warnings?
- [ ] Are new code paths covered by tests?
- [ ] No secrets, model identifiers, or credentials in the diff?

### QA Review

- [ ] `cargo test` passes locally (or CI green).
- [ ] The feature was exercised manually (`simplicio <command>` observed to work).
- [ ] No observable regression in adjacent commands.
- [ ] `simplicio deliver check` (or equivalent dogfood gate) passes.
- [ ] Run evidence (version, command, output) documented in the PR or a comment.','docs/policies/TWO_REVIEWS_POLICY.md','2661cebf0677acf27bf87b1f7a174f8f0967236840d363b784ae70c84beb8a6b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/qa/coverage-baseline-2026-06-18.md','project_doc','doc://simplicio-runtime/docs/qa/coverage-baseline-2026-06-18.md','doc: Test Coverage Baseline — 2026-06-18 (#2259)','# Test Coverage Baseline — 2026-06-18 (#2259)

Generated via pub-fn / test-fn ratio scan across `src/*.rs`.

## Summary

| Metric | Value |
|---|---|
| Modules with public functions | 633 |
| Total public functions | 7,838 |
| Total `#[test]` annotations | 9,500 |
| Zero-coverage modules | 20 |

Note: `#[test]` count is a proxy, not a true line-coverage metric. Tools like
`cargo-llvm-cov` or `cargo-tarpaulin` are needed for accurate line coverage and
are recommended as a follow-up CI step.

## Top 5 Uncovered Modules (by public function count)

| Module | pub fns | tests |
|---|---|---|
| `src/openclaw_messaging_1578.rs` | 49 | 0 |
| `src/mobile_transport_1269.rs` | 37 | 0 |
| `src/agent_init.rs` | 33 | 0 |
| `src/mobile_launch_demo_1282.rs` | 29 | 0 |
| `src/vscode_coverage_1563.rs` | 20 | 0 |

## `src/error.rs` Coverage (AC requirement)

| Public function | Test | Added |
|---|---|---|
| `Severity::as_str` | `severity_as_str_covers_all_variants` | 2026-06-18 |
| `SimplicioError::config` | `display_includes_kind_and_message` | pre-existing |
| `SimplicioError::config_detail` | `message_and_detail_accessors` | 2026-06-18 |
| `SimplicioError::network` | `recoverable_variants` | pre-existing |
| `SimplicioError::network_detail` | `detail_constructors_all_set_detail` | 2026-06-18 |
| `SimplicioError::llm` | `recoverable_variants` | pre-existing |
| `SimplicioError::llm_detail` | `detail_constructors_all_set_detail` | 2026-06-18 |
| `SimplicioError::auth` | `recoverable_variants` | pre-existing |
| `SimplicioError::io` | `from_io_error` | pre-existing |
| `SimplicioError::io_detail` | `detail_constructors_all_set_detail` | 2026-06-18 |
| `SimplicioError::parse` | `parse_constructor` | 2026-06-18 |
| `SimplicioError::parse_detail` | `detail_constructors_all_set_detail` | 2026-06-18 |
| `SimplicioError::not_implemented` | `severity_mapping` | pre-existing |
| `SimplicioError::timeout` | `recoverable_variants` | pre-existing |
| `SimplicioError::budget` | `severity_mapping` | pre-existing |
| `SimplicioError::internal` | `severity_mapping` | pre-existing |
| `SimplicioError::internal_detail` | `detail_constructors_all_set_detail` | 2026-06-18 |
| `SimplicioError::message` | `message_and_detail_accessors` | 2026-06-18 |
| `SimplicioError::detail` | `message_and_detail_accessors` | 2026-06-18 |
| `SimplicioError::kind` | `kind_returns_correct_tag_for_each_variant` | 2026-06-18 |
| `SimplicioError::severity` | `severity_mapping` | pre-existing |
| `SimplicioError::is_recoverable` | `recoverable_variants` | pre-existing |
| `SimplicioErrorRecord::new` | `test_error_json_roundtrip` | pre-existing |
| `SimplicioErrorRecord::with_context` | `error_record_with_context_builds_correctly` | 2026-06-18 |
| `SimplicioErrorRecord::json` | `test_error_json_roundtrip` | pre-existing |

All public functions in `src/error.rs` have at least one test.

## Next Steps

- Add `cargo-llvm-cov` to CI (Ubuntu runner) for true line coverage
- Prioritize adding tests to the top 5 uncovered modules above
- Enforce coverage gate in `.github/workflows/dod.yml` (e.g. `--fail-under 60`)','docs/qa/coverage-baseline-2026-06-18.md','7e4318bf35694dafd95756737554e2da99e3da267b99bd77606b3d13a42c2c22','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/QUICKSTART.md','project_doc','doc://simplicio-runtime/docs/QUICKSTART.md','doc: Quick Start — Your First Agent in 5 Minutes','# Quick Start — Your First Agent in 5 Minutes

> 🇧🇷 Versão em português: [QUICKSTART.pt-BR.md](QUICKSTART.pt-BR.md)

This guide takes you from a fresh install to a working AI agent in a repository.
If you have not installed Simplicio yet, start with [INSTALL.md](../INSTALL.md).

---

## 1. Install (30 seconds)

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.ps1 | iex"
```

Verify:

```bash
simplicio version
```

---

## 2. Run the setup wizard (1 minute)

```bash
simplicio setup
```

The wizard checks your environment, seeds local config under `~/.simplicio-loop`, and
reports what is ready. Re-run it any time — it is idempotent.

Then confirm everything is healthy:

```bash
simplicio doctor
```

And confirm the wider ecosystem (mapper / dev-cli / loop, when installed) is
present, compatible, and has a fresh project map:

```bash
simplicio ecosystem doctor --repo . --json
```

See [docs/SIMPLICIO_STACK.md](SIMPLICIO_STACK.md) for what each component is
and the naming policy across the stack.

---

## 3. Inference ownership (current release)

The Runtime is deterministic-only. It does not start a local model or any
provider, and ignores provider configuration for execution. Inference belongs
to Simplicio Agent/Loop and reaches this Runtime through its versioned MCP/Hub
effect boundary.

The future local backend remains prepared, but requires both an explicit build
feature and an explicit mode that is not enabled in released binaries:

```bash
cargo build --features in-process-llm
SIMPLICIO_RUNTIME_INFERENCE=local-experimental \
SIMPLICIO_RUNTIME_INFERENCE_CONFIRM=I_UNDERSTAND_LOCAL_INFERENCE \
simplicio local-model health --json
```

The confirmation variable is intentionally required in addition to the build feature
and mode. Any missing, invalid or conflicting value keeps the runtime fail-closed
and returns the stable reason code `LOCAL_INFERENCE_PAUSED`. Do not run that
experimental path as part of the current integration.

---

## 4. Chat with your repo (1 minute)

```bash
# One-shot question
simplicio chat "what does this project do?" --repo .

# Interactive REPL
simplicio chat --repo .
```

For better answers, populate the neural memory first so the agent has context:

```bash
simplicio memory init --repo .   # create the local memory DB
simplicio map --repo .           # map the repo and auto-ingest into memory
```

Now ask a real task:

```bash
simplicio agent "add input validation to the login handler" --repo .
```

---

## 5. Next steps

You now have a working agent. Useful things to try next:

```bash
# Map your repo to save tokens before reasoning
simplicio map --repo . --for-llm markdown

# Recall prior decisions instead of re-deriving them
simplicio memory "how does auth work" --repo . --json

# Deterministic, zero-LLM-token edit
simplicio edit ''{"file":"README.md","operations":[{"op":"append","text":"\n"}]}''

# Iterate until tests pass
simplicio coding-loop "fix the failing test" --repo . --max-cycles 5

# Quality gates before declaring done
simplicio deliver check --repo .
simplicio deliver certify --repo . --json
```

Run `simplicio --help` for the full command list.

### Where to go from here

- [INSTALL.md](../INSTALL.md) — all install methods and platforms
- [docs/UPGRADE.md](UPGRADE.md) — keeping Simplicio current
- [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) — when something does not work
- [BUILDING.md](../BUILDING.md) — building from source','docs/QUICKSTART.md','2139a1e435134d7177eb5ab3c2fd385c00d93a4f0f02d72015f0e349e5e64877','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/QUICKSTART.pt-BR.md','project_doc','doc://simplicio-runtime/docs/QUICKSTART.pt-BR.md','doc: Início Rápido — Seu Primeiro Agente em 5 Minutos','# Início Rápido — Seu Primeiro Agente em 5 Minutos

> 🇺🇸 English version: [QUICKSTART.md](QUICKSTART.md)

Este guia leva você de uma instalação limpa a um agente de IA funcionando num
repositório. Se ainda não instalou o Simplicio, comece por
[INSTALL.pt-BR.md](../INSTALL.pt-BR.md).

---

## 1. Instale (30 segundos)

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://raw.githubusercontent.com/wesleysimplicio/simplicio/main/install.ps1 | iex"
```

Verifique:

```bash
simplicio version
```

---

## 2. Rode o assistente de setup (1 minuto)

```bash
simplicio setup
```

O assistente checa o ambiente, semeia a config local em `~/.simplicio-loop` e informa
o que está pronto. Rode quantas vezes quiser — é idempotente.

Depois confirme que está tudo saudável:

```bash
simplicio doctor
```

---

## 3. Dono da inferência (versão atual)

O Runtime opera somente no modo determinístico. Ele não inicia modelo local nem
qualquer provedor; a inferência pertence ao Simplicio Agent/Loop e chega ao
Runtime pela fronteira MCP/Hub versionada.

O backend local futuro continua preparado, mas exige feature de build e modo
explícito que não fazem parte dos binários publicados:

```bash
cargo build --features in-process-llm
SIMPLICIO_RUNTIME_INFERENCE=local-experimental simplicio local-model health --json
```

Não execute esse caminho experimental na integração atual.

---

## 4. Converse com o seu repositório (1 minuto)

```bash
# Pergunta única
simplicio chat "o que este projeto faz?" --repo .

# REPL interativo
simplicio chat --repo .
```

Para respostas melhores, popule a memória neural primeiro para o agente ter
contexto:

```bash
simplicio memory init --repo .   # cria o DB de memória local
simplicio map --repo .           # mapeia o repo e auto-ingere na memória
```

Agora peça uma tarefa real:

```bash
simplicio agent "adicione validação de entrada ao handler de login" --repo .
```

---

## 5. Próximos passos

Você agora tem um agente funcionando. Coisas úteis para tentar a seguir:

```bash
# Mapeie o repositório para economizar tokens antes de raciocinar
simplicio map --repo . --for-llm markdown

# Recupere decisões anteriores em vez de redescobri-las
simplicio memory "como funciona a autenticação" --repo . --json

# Edição determinística com zero tokens de LLM
simplicio edit ''{"file":"README.md","operations":[{"op":"append","text":"\n"}]}''

# Itere até os testes passarem
simplicio coding-loop "corrija o teste que falha" --repo . --max-cycles 5

# Gates de qualidade antes de declarar pronto
simplicio deliver check --repo .
simplicio deliver certify --repo . --json
```

Rode `simplicio --help` para a lista completa de comandos.

### Para onde ir agora

- [INSTALL.pt-BR.md](../INSTALL.pt-BR.md) — todos os métodos de instalação
- [docs/UPGRADE.pt-BR.md](UPGRADE.pt-BR.md) — manter o Simplicio atualizado
- [docs/TROUBLESHOOTING.pt-BR.md](TROUBLESHOOTING.pt-BR.md) — quando algo não funciona
- [BUILDING.md](../BUILDING.md) — compilar do código-fonte','docs/QUICKSTART.pt-BR.md','0262f41bf0a8ef3cf7ee3752251f9f5c0e1903e794f3f9c58ef11d529b71340f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/rebrand/HERMES_INVENTORY_REPORT.md','project_doc','doc://simplicio-runtime/docs/rebrand/HERMES_INVENTORY_REPORT.md','doc: Hermes occurrence inventory — issue #3140','# Hermes occurrence inventory — issue #3140

Generated from `wesleysimplicio/simplicio-runtime@9551f74a03b1`. 
Classification schema: wesleysimplicio/simplicio-agent#187. Epic: wesleysimplicio/simplicio-agent#186.


Machine-readable manifest: `docs/rebrand/hermes-inventory.json` (`rename-inventory/v1`). 
Allowlist: `docs/rebrand/hermes-allowlist.json` (`rename-allowlist/v1`).


## Scope

Covers tracked-file text matches of /hermes/i in the simplicio-runtime repo only. Binary artifacts (publish/github, publish/simpleti) are excluded from classification here and must go through #187''s binary/strings scanner. agent/, tools/, tui/, acp_adapter/ are the vendored Simplicio Agent (Hermes-fork) source that currently lives in this repo; their product-identity surface is owned by simplicio-agent#188/#190, not this runtime issue.


This is a **rule-based, path-first classification** of every git-tracked file that contains "hermes" (case-insensitive) as of the commit above — 1,592 files. It does not rename or edit anything; it is the inventory step (plan steps 1-4) that precedes any rename work.


## Totals by classification

| Classification | Files | Meaning |
|---|---:|---|
| `public-must-migrate` | 9 | Confirmed public-identity leak — must be fixed, not allowlisted. |
| `compatibility-temporary` | 411 | Legitimate fork/import/sync/bridge code; allowlisted with an expiry checkpoint for owner re-review. |
| `upstream-attribution` | 597 | Real third-party product/model/author credit; correctly stays as-is. |
| `historical-fixture` | 150 | Frozen record (benchmark, release notes, audit snapshot); not rewritten. |
| `private-internal-reviewed` | 144 | Internal-only reference (comment, test, tooling); no public exposure. |
| `error` | 281 | Not safely classifiable by path alone — needs a manual/line-level pass. |
| **Total** | **1592** | |

## public-must-migrate — fix these, do not allowlist

- `publish/README.md` — Describes the shipped terminal as "Hermes-parity" in a currently-live README, not a frozen release artifact; should describe the feature in Simplicio-native terms.
- `schemas/cron.schema.json` — Schema exposes a field literally named "hermes" inside "hermes_comparison" for a shipped receipt schema; naming-contract violation. Renaming is a breaking schema change and needs its own migration issue, not a silent inventory fix.
- `website/docs/user-guide/api.md` — Public user-guide docs present "Hermes Mode"/"Hermes parity" as the feature''s own name (e.g. chat.md:1 "# Chat with Hermes Mode"). This is exactly the public-identity leak the epic targets; needs rename to Simplicio-native feature names, not just an allowlist entry.
- `website/docs/user-guide/chat.md` — Public user-guide docs present "Hermes Mode"/"Hermes parity" as the feature''s own name (e.g. chat.md:1 "# Chat with Hermes Mode"). This is exactly the public-identity leak the epic targets; needs rename to Simplicio-native feature names, not just an allowlist entry.
- `website/docs/user-guide/examples.md` — Public user-guide docs present "Hermes Mode"/"Hermes parity" as the feature''s own name (e.g. chat.md:1 "# Chat with Hermes Mode"). This is exactly the public-identity leak the epic targets; needs rename to Simplicio-native feature names, not just an allowlist entry.
- `website/docs/user-guide/gateway.md` — Public user-guide docs present "Hermes Mode"/"Hermes parity" as the feature''s own name (e.g. chat.md:1 "# Chat with Hermes Mode"). This is exactly the public-identity leak the epic targets; needs rename to Simplicio-native feature names, not just an allowlist entry.
- `website/docs/user-guide/getting-started.md` — Public user-guide docs present "Hermes Mode"/"Hermes parity" as the feature''s own name (e.g. chat.md:1 "# Chat with Hermes Mode"). This is exactly the public-identity leak the epic targets; needs rename to Simplicio-native feature names, not just an allowlist entry.
- `website/docs/user-guide/index.md` — Public user-guide docs present "Hermes Mode"/"Hermes parity" as the feature''s own name (e.g. chat.md:1 "# Chat with Hermes Mode"). This is exactly the public-identity leak the epic targets; needs rename to Simplicio-native feature names, not just an allowlist entry.
- `website/docs/user-guide/installation.md` — Public user-guide docs present "Hermes Mode"/"Hermes parity" as the feature''s own name (e.g. chat.md:1 "# Chat with Hermes Mode"). This is exactly the public-identity leak the epic targets; needs rename to Simplicio-native feature names, not just an allowlist entry.

## error — needs manual triage before this inventory can close

281 files could not be safely classified by path rules alone — mostly individual `src/*.rs` runtime modules where a bulk directory rule would either wrongly allowlist a real leak or wrongly flag a safe internal comment. Grouped by area:

- **src/ (runtime source, one-off files)**: 276 files
- **other**: 5 files

Full path list is in `hermes-inventory.json` (filter `classification == "error"`). Recommended next step: a follow-up issue that greps each for the actual matched line (not just presence of the token) and reclassifies file-by-file or line-by-line, since several of the flagged directories (`src/tui_app_parts`, `src/commands`, `src/conversation`, `src/asolaria`, `src/main_parts`) contain literal `"hermes"` string values reachable from user input/output, not just comments.


## By surface (all classes)

| Surface | Files |
|---|---:|
| claude-skills | 597 |
| agent-fork-source | 335 |
| unclassified | 242 |
| docs | 167 |
| runtime-source | 130 |
| benchmark-evidence | 45 |
| scripts | 27 |
| governance-docs | 12 |
| public-docs | 10 |
| examples | 6 |
| runtime-tests | 6 |
| internal-state | 5 |
| public-schema | 4 |
| plugins | 3 |
| internal-workspace | 1 |
| release-artifact | 1 |
| public-marketing | 1 |

## Notable findings

- **Vendored agent-fork source lives in this repo.** `agent/`, `tools/`, `tui/`, `acp_adapter/`, and most of `plugins/**` are the actual Simplicio Agent (','docs/rebrand/HERMES_INVENTORY_REPORT.md','c84d65c53bd50fccfaa9a5c413cf831ebc7ceb87412574ed12d08abdd6406efd','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/reference.md','project_doc','doc://simplicio-runtime/docs/reference.md','doc: Simplicio Runtime command and capability reference','# Simplicio Runtime command and capability reference

This file is generated from the Runtime command and capability catalogs.

## Commands

| Command | Purpose | Aliases |
| --- | --- | --- |
| `doctor` | check runtime, policy, adapters, local model, and repo state; --capabilities lists integrations | — |
| `runtime map` | emit the LLM-readable runtime resource map as JSON or Markdown | — |
| `infra-advanced` | experimental preview-only surface for module hot-reload and related infra primitives; not shipped | — |
| `map` | map repository context via the mapper adapter with local fallback | — |
| `plan` | produce a task plan and decision without mutating the repo | — |
| `decide` | route a task through Isa/Helo memory first and avoid model calls when confidence is high | decision |
| `guardians` | show Isa/Helo/Levi guardian status, access policy, and full-stack default execution contract | guardian, neural-guardians |
| `run` | execute a single task with governed agents, validation, and evidence | — |
| `sprint` | run a task graph to Done with optional PR handoff and watch mode | — |
| `resume` | resume an interrupted run from saved state and handoff notes | — |
| `evidence` | show the evidence ledger for a run id | — |
| `validate` | compute the progressive validation plan for a task | validation |
| `precedent` | check CodeMap/file/symbol/test/patch compatibility before replaying a prior plan or diff | precedents |
| `status` | report runtime status; --watch streams updates | — |
| `governor` | simulate adaptive agent capacity from policy and machine signals | — |
| `parallelism` | show max-safe parallel execution across logical agents, read/check pools, model queue, and write locks | parallel, throughput, speed |
| `cache` | inspect or clear the local prompt/result cache | — |
| `chat` | explain runtime state and decisions from local logs and metadata | explain |
| `memory` | describe and query the local neural-db-like memory layer for SQLite/FTS5, recipes, cache, runs, evidence, and skills | memories, neural-db, neuraldb |
| `skill-memory` | show the Hermes-style skill learning loop, usage/provenance sidecars, bundles, and offline skill indexes | skills-memory, skillstore, curator |
| `orientation` | build or inspect the Helo-governed zero-copy mmap pack for docs, examples, schemas, and orientation files | orientacao, zerocopy, zero-copy, mmap |
| `capabilities` | list and rank built-in tools, adapters, connectors, and capability contracts | tools |
| `skills` | list the skills selected for the current task and repo | — |
| `invoke` | show every supported invocation surface while keeping simplicio as the canonical command | invocation, interfaces |
| `advise` | state the runtime opinion, next action, selected skills, and compiled surface for a task | advice, opinion, next |
| `resolve` | run the canonical retrieval-before-thinking fast path and report the chosen reasoning level | resolver |
| `compiled` | report the compiled-binary-first contract and local release build status | binary, compiler, build-contract |
| `cron` | manage scheduled jobs using the compiled runtime cron store | cronjob, routine, routines |
| `login` | report the disabled Google/Gmail identity contract for future paid-update entitlement | auth, account |
| `license` | report entitlement tier, pricing plans, and Stripe subscription gate | licenca, subscription, entitlement, billing |
| `task` | normalize free-text intent into a simplicio.task/v1 contract | contract |
| `learn` | promote a successful run into a reusable recipe with an approval gate | — |
| `benchmark` | measure deterministic runtime scenarios with real timings (fixture rows via --sample) | — |
| `savings` | compare delivery with Simplicio against measured or estimated baselines | economy, tokens |
| `computer-use` | report or run approval-gated desktop automation through an explicit backend | computer_use, desktop |
| `intake` | parse a natural-language sprint instruction and dispatch the discovered work items (--dry-run for the per-item plan) | — |
| `install` | optional global registration of the binary and assistant adapters | bootstrap |
| `serve` | run as MCP, local HTTP, or stdio server | daemon |
| `service` | manage the optional background service/daemon lifecycle | — |
| `adapters` | show, install, or roll back assistant and tool adapters | — |
| `update` | check, apply, roll back, or report update status | upgrade |
| `privacy` | report data-handling, redaction, and local-only policy | — |
| `demo` | run a guided demonstration of the runtime flow | — |
| `reasoning` | show the model/agent routing and reasoning policy; --execute runs the routed backend | router |
| `welcome` | print onboarding and first-run guidance | — |
| `self-test` | run internal self-checks | selftest |
| `version` | print the runtime version | — |
| `completion` | generate deterministic Bash, Zsh, Fish, or PowerShell completion scripts from the live command catalog | completions |
| `prototype` | Prototype-First Gate: run/validate/artifacts/cleanup/promote/doctor a hash-pinned prototype-plan in a quota-bounded sandbox with zero external effect (#3337, Loop #568) | — |
| `help` | print usage | -h, --help |

## Capabilities

| ID | Kind | Pack | Status | When to use |
| --- | --- | --- | --- | --- |
| `terminal/process` | `built-in core` | `repo-intelligence` | `installed` | run supervised commands |
| `file/search/patch` | `built-in core` | `repo-intelligence` | `installed` | inspect and change scoped files |
| `repo-locks` | `built-in core` | `agent-ops` | `installed` | serialize writes and preserve dirty state |
| `evidence-ledger` | `evidence collector` | `tdd-verification` | `installed` | record decisions and proof |
| `progressive-validation` | `built-in core` | `tdd-verification` | `installed` | choose checks by risk |
| `deterministic-shell-checks` | `built-in core` | `tdd-verification` | `installed` | run reproducible format, test, build, and schema checks','docs/reference.md','05fbe19eba67ddd0c5f2b5f8a70d8eb28dc4e321d7d17852185df3ad8658b080','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/REFERENCES.md','project_doc','doc://simplicio-runtime/docs/REFERENCES.md','doc: Simplicio — external references (projects we learn from / integrate)','# Simplicio — external references (projects we learn from / integrate)

Per the import-tracking rule (CLAUDE.md): every project we use to make Simplicio work is
recorded here with its license + WHAT we take + the tracking issue. We port patterns into
Simplicio-native Rust forms (or integrate via MCP); we don''t copy proprietary code. Detailed
analyses: `docs/osaurus-import/`, `docs/cowork-alternatives/`, `docs/innovation-scan/`.

## Computer-use (control the machine — must beat Claude Cowork; Codex has none)
Verdict (2026): HYBRID — UIA accessibility-tree as the fast, no-GPU backbone + a small vision
grounder ONLY for non-UIA elements (canvas/Chromium/games).

**LANDED (2026-06-25):** `src/desktop_control.rs` now has a native UIA-first lane —
`ui-snapshot` (read the live accessibility tree, no vision), `ui-invoke` (click by element
NAME via Invoke/Toggle/Select patterns), `ui-set` (ValuePattern) — Windows via .NET
System.Windows.Automation, wired into the chat spine ("leia a tela" / "clique no botão X").
Proven by the functional harness (`computer-use-uia` reads Notepad''s real UIA tree).

| project | ★ | license | what we use | issue |
|---|---|---|---|---|
| leonhartX/uiautomation-rs | — | MIT | **the Rust UIA crate** — perf upgrade path for the LANDED PowerShell UIA lane (drop the PS spawn): index the element tree + act via UIA PATTERNS, DPI/theme-proof, BACKGROUND (no cursor steal — the edge over Cowork) | #2655 |
| trycua/cua | 19k | Apache-2.0 | the **layered dispatch ladder** to port: UIA pattern → element-indexed click → Win32 pixel fallback; PrintWindow + Graphics.Capture; honest errors; benchmarks to grade | #2660 |
| microsoft/UFO (UFO2/UFO3) | 9k | MIT | hybrid UIA + visual-grounding blueprint for Windows; multi-app HostAgent/AppAgent decomposition | #2660 |
| CursorTouch/Windows-MCP | 6.2k | MIT | **integrate directly as an MCP server** (`uvx windows-mcp`) — instant Snapshot/Click/Type/Scroll (2M+ Claude Desktop installs); fastest path | #2658 |
| CursorTouch/Windows-Use | — | MIT | Ally-Tree agent (PyPI) — API-shape + use_vision/use_annotation flags reference | #2655 |
| browser-use/browser-use | 100k | MIT | **web lane** via the DOM/accessibility tree (89.1% WebVoyager) — route in-browser tasks here, not pixels | #2659 |
| Skyvern-AI/skyvern | 22k | — | form-heavy/visual browser workflows reference | #2657 |
| simular-ai/Agent-S (S2) | 12k | — | OSWorld-SOTA generalist-specialist planner; beat Claude Computer Use | #2657 |
| microsoft/OmniParser v2 | — | MIT | **vision FALLBACK** — Set-of-Marks (numbered interactive boxes) for any LLM, when UIA can''t see | #2660 |
| microsoft/Fara-7B / Fara1.5 (4B/9B/27B) | — | open-weight | **local CUA grounder** option (screenshot-only, on-device; 9B "practical on modest hw") — "better than Cowork in open weights" | #2654-rel |
| Yan98/GTA1 | — | CC-BY-NC-SA | grounding accuracy reference ONLY (non-commercial — do NOT ship weights); steal the judge-model test-time-scaling idea | — |

## Integrations / "do everything" + agent products (the closest twins)
| project | ★ | license | what we use | issue |
|---|---|---|---|---|
| Composio (open-claude-cowork) | 4.3k | MIT | **Composio Tool Router = 500+ SaaS apps** (Gmail/Slack/Notion/GitHub/Drive…) via MCP — the "faz tudo" enabler; integrate as an MCP source | #2662 |
| eigent-ai/eigent | 14.4k | Apache-2.0 | multi-agent **workforce** (CAMEL-AI) parallel execution; local + MCP + custom-model reference | #2663 |
| accomplish-ai/coworker | 10.9k | MIT | local desktop agent: file mgmt + doc writing + browser; **save workflows as skills** + **per-action approve/log/stop** (our gate) | #2663 |
| osaurus-ai/osaurus | 6.2k | MIT | the AI-harness twin: skills-via-RAG, memory consolidator, agent-loop-in-chat, sandbox, privacy filter | #2645 (#2646-2653) |

## Memory (persistent, learning)
| project | what we use | issue |
|---|---|---|
| osaurus memory | distill-at-session-end + salience scoring + background consolidator; layers (identity/pinned/episodic) | #2647 |
| Mem0 / Letta(MemGPT) / Zep / Cognee | vector+graph hybrid memory architectures (state-of-the-art reference) | #2647 |

## Agent loop / skills / tools
| project | what we use | issue |
|---|---|---|
| Claude Skills / agentskills.io | RAG-selected skills (no manual config) — auto-use relevant skills in a turn | #2646 |
| OpenHands, Agent-S, the-open-agent/openagent, smolagents | plan-execute-verify loop, sandboxed exec, RAG tool-selection, self-critique | #2648, #2661 |

## Voice-first (wake → STT → act → TTS, low latency)
| project | ★ | what we use | issue |
|---|---|---|---|
| pipecat-ai/pipecat | 13k | the **real-time voice PIPELINE** pattern (STT→LLM→TTS, full-duplex, interruption, VAD) — make our voice loop fluid/low-latency | (voice) |
| livekit/agents | 11k | WebRTC realtime voice agents — always-on + the orb | (voice) |
| TEN-framework | 10.7k | conversational voice agent framework reference | (voice) |
| moonshine-ai/moonshine | — | very-low-latency STT for short commands / the wake-word path (faster than whisper for short clips) | (voice) |
| fixie-ai/ultravox · hf/speech-to-speech | 4.5k | speech-to-speech models (no separate STT/TTS) — cutting-edge local voice | (voice) |
| whisper.cpp (built, VS 2019) | — | in-process STT (proven: engine "whisper-rs(in-process)") | #2630 |

## Models (local + paid ladder)
| model | use | issue |
|---|---|---|
| Qwen3.5-4B Q4_K_M (GGUF, embedded llama.cpp) | Runtime-owned local default | ADR-2026-07-19-QWEN35-4B-RUNTIME.md |
| DeepSeek deepseek-v4-flash | paid chat provider (reasoning; retry on empty content) | config |
| KOG LaneFormer 2B | fallback only (no GGUF, needs proprietary engine) | #2654 |
| microsoft/Fara1.5-9B | candidate local computer-use grounder | #2660 |

## Ready-made solutions per gap (GitHub, integrable — 2026-06-25)

User: "para todos os gaps, procure soluções prontas no GitHub que nos atendam." Prioritised
**Rust crates we can `cargo add` and integrate directly** (not reimp','docs/REFERENCES.md','21e4e98cb30faf6b8326210cbfc9ef8dec9aa959b2726e451337611ab4bd524e','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/release/ATOMIC_RELEASE_POLICY.md','project_doc','doc://simplicio-runtime/docs/release/ATOMIC_RELEASE_POLICY.md','doc: Atomic Release Policy','# Atomic Release Policy

> Issue: #2215 — [Release] Atomic Release Policy

## Principle

One release is earned by **three completed features**. No partial batches ship.
This keeps releases meaningful, predictable, and worth a social post.

---

## What counts as a "completed feature"

A feature is complete when **all** of the following are true:

1. The implementing PR is merged to `main`.
2. The PR closes at least one GitHub issue labeled `feature` or `enhancement`.
3. CI passes on `main` after the merge (no red checks).
4. The issue moves to **Done** in the milestone board.

Fixes, chores, docs, and refactors do **not** count toward the feature quota unless
they also close a `feature`/`enhancement` issue.

---

## Tracking the batch

Every milestone contains a **release counter** section in its description:

```
## Release counter
- [ ] Feature 1 — #<issue>
- [ ] Feature 2 — #<issue>
- [ ] Feature 3 — #<issue>
```

When all three boxes are checked, the next step is to open the release PR
(see below). The counter resets to zero after each release.

### Labels used

| Label | Meaning |
|---|---|
| `feature` | This issue / PR introduces a user-visible capability |
| `enhancement` | Counts toward feature quota (improvement to existing capability) |
| `release-candidate` | Applied to the release PR while it is being reviewed / social-gated |
| `release-ready` | Applied after social gate passes; signals CI + merge |

---

## Release PR workflow

1. **Create the release PR** pointing `main` → `main` (or the release branch if
   one exists) once the third feature is merged.
   - Title: `chore(release): bump version to <NEW_VERSION>`
   - Body must include the changelog generated by `scripts/release/changelog.sh`.
   - Apply label `release-candidate`.

2. **Run the social gate** (`scripts/release/social-check.sh`).  
   The `release-gate` CI job blocks merge until this passes.

3. **Once the social gate passes**, remove `release-candidate` and apply
   `release-ready`. A maintainer merges the PR.

4. **Tag** the merge commit: `git tag v<NEW_VERSION> && git push origin v<NEW_VERSION>`.

5. The `release.yml` workflow picks up the tag and publishes binaries + changelog.

---

## Versioning

Simplicio follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).

| Change | Bump |
|---|---|
| 3-feature atomic release (normal cadence) | **minor** (`1.2.0 → 1.3.0`) |
| Breaking API / protocol change | **major** (`1.x.x → 2.0.0`) |
| Hot-fix on a released tag (no new features) | **patch** (`1.2.0 → 1.2.1`) |

Version is always bumped via `scripts/bump-version.sh <version>` — never
hand-edit `Cargo.toml`, `pyproject.toml`, or `Cargo.lock` individually.

---

## Edge cases

| Situation | Resolution |
|---|---|
| A feature is partially done at end of milestone | Carries forward to the next batch; the counter does not reset |
| A merged feature PR is reverted | The feature no longer counts; update the counter |
| Hot-fix needed before 3 features accumulate | Ship a patch release; the feature counter is unaffected |
| Two features are ready but the third is blocked | Wait; do not ship a 2-feature "mini-release" |

---

## Changelog

The changelog for each release is generated automatically by
`scripts/generate-changelog.sh` from conventional commits between the previous
tag and `HEAD`. See [Changelog Automation](#) (issue #2223).

Usage: `VERSION=<ver> ./scripts/generate-changelog.sh <prev-tag> HEAD`

---

## Social gate

Every release PR must pass `scripts/release/social-check.sh` before it can be
merged. See [Mandatory Social Gate](#) (issue #2214).

---

## Quality gates

All 6 gates in `docs/release/QUALITY_GATES.md` must pass before tagging.
Full pre/during/post steps are in `docs/release/RELEASE_CHECKLIST.md`.','docs/release/ATOMIC_RELEASE_POLICY.md','92253205112afab8b731a11186e8644d6d37d41192011f020351d515a9ed9403','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/release/QUALITY_GATES.md','project_doc','doc://simplicio-runtime/docs/release/QUALITY_GATES.md','doc: Quality Gates','# Quality Gates

Six mandatory gates that must all pass before any simplicio-runtime release is tagged.
A release is blocked if any gate is red. Gates are ordered cheapest-first.

---

## Gate 1 — Tests Pass

**Command:** `cargo test 2>&1 | tail -5`
**Pass criteria:** Output ends with `test result: ok.` and zero failures.
**Blocking:** Yes. No release ships with failing tests.
**Automation:** CI runs this on every push to `main` (`.github/workflows/`).
**Local fast-path:** `cargo test --quiet` — fix failures before continuing.

```
GATE 1 STATUS: [ ] PASS  [ ] FAIL
```

---

## Gate 2 — Clippy Clean

**Command:** `cargo clippy --release -- -D warnings 2>&1 | grep -c "^error" || true`
**Pass criteria:** Zero lines starting with `error`. New warnings count as failures (`-D warnings`).
**Blocking:** Yes. Clippy warnings indicate real issues and must be resolved, not suppressed with `#[allow]` without comment.
**Note:** Existing `#[allow(...)]` attributes in the codebase are grandfathered; new ones require a justification comment.

```
GATE 2 STATUS: [ ] PASS  [ ] FAIL
```

---

## Gate 3 — No Secrets

**Command:**
```bash
git log "$(git describe --tags --abbrev=0 2>/dev/null || git rev-list --max-parents=0 HEAD)"..HEAD -p \
  | grep -iE ''(api_key|api_secret|password|private_key|bearer |sk-|pk_live|rk_live|pypi-|ghp_|gho_|ghu_|ghs_|ghr_)'' \
  | grep -v "^-" | grep -v "test\|example\|placeholder\|YOUR_" || echo "CLEAN"
```
**Pass criteria:** Output is `CLEAN` or grep finds nothing suspicious.
**Blocking:** Yes — hard stop. Rotate any leaked credential immediately (#762 pattern).
**Automation:** Pre-commit hook recommended; the gate is enforced manually here as a backstop.
**Note:** `SIMPLICIO_API_KEY`, `OPENAI_API_KEY`, and similar env var *names* are fine in code; actual key *values* (starting with `sk-`, `pk_`, etc.) are not.

```
GATE 3 STATUS: [ ] PASS  [ ] FAIL
```

---

## Gate 4 — Changelog Updated

**Command:** `head -5 CHANGELOG.md | grep -c "$(grep ''^version'' Cargo.toml | head -1 | sed ''s/.*= "\(.*\)"/\1/'')"` → must return `1`
**Pass criteria:** The current version from `Cargo.toml` appears in the first 5 lines of `CHANGELOG.md`.
**Blocking:** Yes. A release with no changelog entry is invisible to users and breaks the audit trail.
**How to fix:** Run `VERSION=<ver> ./scripts/generate-changelog.sh <prev-tag> HEAD` then review and commit.

```
GATE 4 STATUS: [ ] PASS  [ ] FAIL
```

---

## Gate 5 — Version Bumped

**Command:** Check all three files agree:
```bash
CARGO="$(grep ''^version'' Cargo.toml | head -1 | sed ''s/.*= "\(.*\)"/\1/'')"
PYPROJECT="$(grep ''^version'' pyproject.toml 2>/dev/null | head -1 | sed ''s/.*= "\(.*\)"/\1/'' || echo N/A)"
LOCK="$(grep -A1 ''name = "simplicio"'' Cargo.lock | grep version | head -1 | sed ''s/.*= "\(.*\)"/\1/'')"
echo "Cargo=$CARGO pyproject=$PYPROJECT lock=$LOCK"
[[ "$CARGO" == "$PYPROJECT" || "$PYPROJECT" == "N/A" ]] && [[ "$CARGO" == "$LOCK" ]] && echo PASS || echo FAIL
```
**Pass criteria:** `PASS` — all files report the same version string.
**Blocking:** Yes. Version skew causes mismatched wheels, confused users, and broken install scripts.
**How to fix:** `./scripts/bump-version.sh <new-version>` — never hand-edit one file alone.

```
GATE 5 STATUS: [ ] PASS  [ ] FAIL
```

---

## Gate 6 — Reviewer Approved

**Criteria (one of):**
- A second human reviewed the diff and left a GitHub approval on the PR, OR
- For a solo/hotfix release: a written justification is recorded in the GitHub Release body explaining why solo release was necessary.

**Blocking:** Yes for major/minor releases. Hotfixes may ship solo with documented justification.
**Automation:** GitHub branch protection (require 1 approval) enforces this on PRs; direct pushes to `main` are gated by the developer''s own judgment and this checklist.
**Evidence:** Link to PR approval or paste justification below before tagging.

```
GATE 6 STATUS: [ ] APPROVED (PR: #____) [ ] SOLO (justification recorded)
```

---

## Gate Summary

| # | Gate | Status |
|---|------|--------|
| 1 | Tests pass | [ ] |
| 2 | Clippy clean | [ ] |
| 3 | No secrets | [ ] |
| 4 | Changelog updated | [ ] |
| 5 | Version bumped | [ ] |
| 6 | Reviewer approved | [ ] |

**All 6 must be checked before `git tag` is run.**','docs/release/QUALITY_GATES.md','b1dc851c71113489dbacc9f69d88a0b298da154b8605fee17668b531105e872b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/release/RELEASE_CHECKLIST.md','project_doc','doc://simplicio-runtime/docs/release/RELEASE_CHECKLIST.md','doc: Release Checklist','# Release Checklist

Checklist for every simplicio-runtime release. Complete all items before tagging.
Run `scripts/bump-version.sh <version>` to bump version — never hand-edit Cargo.toml alone.

---

## Pre-Release

### Code Quality
- [ ] All tests pass locally: `cargo test`
- [ ] Clippy is clean (zero new warnings): `cargo clippy --release -- -D warnings`
- [ ] No secrets or credentials in any committed file (`git log --all -p | grep -iE ''api_key|secret|password|token''` returns nothing new)
- [ ] No `TODO`/`FIXME` comments introduced in this release''s diff

### Version & Changelog
- [ ] Version bumped via `scripts/bump-version.sh <new-version>` (Cargo.toml + pyproject.toml + Cargo.lock in sync)
- [ ] CHANGELOG.md updated: `VERSION=<new-version> ./scripts/generate-changelog.sh <prev-tag> HEAD`
- [ ] CHANGELOG.md entry reviewed — all feat/fix/perf items present, no duplicates
- [ ] Atomic release policy satisfied (see `docs/release/ATOMIC_RELEASE_POLICY.md`)

### Review
- [ ] Diff reviewed: `simplicio deliver review` (self-review gate #254)
- [ ] Reviewer approved (or solo release documented with reason)
- [ ] Open issues blocking this release are closed or explicitly deferred
- [ ] No parallel agent sessions writing to `main` at the same time (check `git log --oneline -5`)

### Build
- [ ] `cargo build --release --locked` succeeds
- [ ] Binary size delta is within expected range (< 20% growth without explanation)
- [ ] Cross-build for Linux succeeds: `./scripts/build-linux-cross.sh` (if shipping Linux binary)
- [ ] Windows build: `./scripts/build-windows-release.sh`

---

## During Release

- [ ] Tag created: `git tag v<version> -m "chore(release): v<version>"`
- [ ] Tag pushed: `git push origin v<version>`
- [ ] GitHub Release drafted with CHANGELOG.md section pasted in
- [ ] Binaries attached to GitHub Release (linux-x64, linux-arm64, windows-x64, macos-arm64, macos-x64)
- [ ] Checksums generated: `./scripts/generate-checksums.sh`
- [ ] Checksums file attached to GitHub Release
- [ ] PyPI installer wheel published (no sdist): `cd packaging/pypi && python3 -m build --wheel && twine upload --skip-existing dist/*.whl`

---

## Post-Release

- [ ] `which simplicio` on the release machine points to updated binary
- [ ] `simplicio --version` returns the new version
- [ ] Smoke test: `simplicio map --repo . --json` returns valid JSON
- [ ] Smoke test: `simplicio memory "release" --repo . --json` returns without error
- [ ] Dashboard accessible at `:9119` (if dashboard feature is enabled)
- [ ] Install script tested: `curl -fsSL https://simplicio.dev/install.sh | sh -n` (dry-run syntax check)
- [ ] Site updated if version string is hardcoded in any landing page
- [ ] Release milestone closed on GitHub
- [ ] Blocking issues referenced in release notes are closed
- [ ] MEMORY.md updated with new release status

---

## Rollback Plan

If a critical regression is found post-release:
1. `git revert <commit>` or `git reset --hard <prev-tag>` on a hotfix branch
2. Re-run this checklist from Pre-Release
3. Tag as `v<version>.1` hotfix
4. Document in CHANGELOG.md under `### Hotfix`','docs/release/RELEASE_CHECKLIST.md','0f33663382b6bc55e375e0b7944f27a3c427156fc07713e58d14c3f904a1c8c8','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/release/RELEASE_READINESS_GATE.md','project_doc','doc://simplicio-runtime/docs/release/RELEASE_READINESS_GATE.md','doc: Release readiness gate (#3162)','# Release readiness gate (#3162)

`scripts/release_readiness_gate.py` is the single offline evaluator for the
five release gates in issue #3162. It is an evidence gate, not a benchmark or
an installer: it consumes receipts that were produced by the responsible
components and never synthesizes measurements.

## Contracts

- `release/release-readiness.toml` is the human-authored policy. It pins issue
  `3162`, the release identifier, `clean-machine`, exactly `G1` through `G5`,
  and the HBP ledger path.
- The ledger is append-only HBP. Each row contains a gate status, release and
  environment identity, receipt reference, `prev_event_hash`, and
  `event_hash`. The event hash is SHA-256 over the complete row without the
  final `event_hash` field.
- JSON is emitted only with `--json` as the external
  `simplicio.release-readiness/v1` report. It contains statuses and receipt
  references, not invented token, cost, timing, or benchmark values.

## Usage

```bash
python3 scripts/release_readiness_gate.py \
  --policy release/release-readiness.toml \
  --json \
  --write-receipt /tmp/release-readiness.hbp
```

The process exits `0` only when all five gates are `PASS` for the same release
and `clean-machine` environment. Missing evidence is `UNVERIFIED`; malformed,
inconsistent, or tampered evidence is `FAIL`. Both states remain blocked and
cannot produce `OPERATIONAL`.

`--write-receipt` appends an HBP evaluation receipt, including blocked runs, so
a missing dependency produces an auditable receipt instead of an empty claim.','docs/release/RELEASE_READINESS_GATE.md','71bd26d6fb40dd147110dd3da9c9cd3df30cc62738e07916f9eb9bf0961e7e8b','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/release/SECURITY_GATES.md','project_doc','doc://simplicio-runtime/docs/release/SECURITY_GATES.md','doc: Security gate policy','# Security gate policy

This repository treats dependency-security findings as release blockers.

- **Critical, high, medium, and low RustSec advisories:** blocking. The CI
  cargo-audit/RustSec gate must pass; there is no silent severity-based
  exception list.
- **Unmaintained, unsound, and yanked dependency warnings:** blocking until the
  dependency is upgraded, removed, or an issue-linked exception is reviewed.
- **Secret-scan findings:** blocking at every severity supported by the scanner.
- **Dependabot updates:** enabled weekly for the Cargo workspace, the root
  Python project, and the public installer package. Security updates follow the
  same blocking CI and review policy.
- Any temporary exception must identify the advisory, severity, owner, expiry,
  and tracking issue in the pull request. It must not be encoded by making the
  CI job advisory or by adding an undocumented ignore.

The policy is intentionally fail-closed: a red security gate prevents build
promotion and therefore prevents package, tag, or release-asset publication.','docs/release/SECURITY_GATES.md','2c11ca878dc5e87bef377b3f310d5bf3294f2a78b25647ad03ddaf90b6a34aa2','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/RELEASE_DEPLOY.md','project_doc','doc://simplicio-runtime/docs/RELEASE_DEPLOY.md','doc: Release & Deploy Runbook','# Release & Deploy Runbook

One release ships to **four** targets. The script
[`scripts/deploy-release.sh`](../scripts/deploy-release.sh) does all of them;
this doc explains each, the gotchas, and how to verify.

| # | Target | What lands there | Auth |
|---|--------|------------------|------|
| 1 | **PyPI** | `simplicio-installer` wrapper wheel (**no sdist**, no runtime source) | `PYPI_TOKEN` |
| 2 | **Private repo** `wesleysimplicio/simplicio-runtime` | source tag + GH release (no binaries) | `gh` (this repo) |
| 3 | **Public repo** `wesleysimplicio/simplicio` | compiled raw binaries + installers | `GH_TOKEN_PUBLIC` PAT |
| 4 | **Site (FTP)** `simpleti.com.br/simplicio` | installers + `dist/` binaries | `FTP_HOST/USER/PASS` |

## Golden rules

- **Binaries live in the PUBLIC repo** `wesleysimplicio/simplicio`. The
  `-runtime` repo is **private/closed source** — never publish source there and
  never point an installer at it.
- **Asset names are raw binaries** `simplicio-<os>-<arch>`:
  `simplicio-linux-x64` · `simplicio-darwin-arm64` · `simplicio-windows-x64`.
  **No tarballs**, arch is `x64`/`arm64` (not `x86_64`/`aarch64`).
- **Never commit secrets.** All tokens/passwords come from the environment.
  If a token ever appears in chat/logs, rotate it.

## Quick start

```bash
# 1. dry-run everything (shows exactly what would ship, sends nothing)
./scripts/deploy-release.sh

# 2. ship it (set the secrets first)
export PYPI_TOKEN=''pypi-…''                 # PyPI project token
export GH_TOKEN_PUBLIC=''ghp_…''             # PAT, contents:write on the public repo
export FTP_HOST=''ftp.simpleti.com.br'' FTP_USER=''wesley@simpleti.com.br'' FTP_PASS=''…''
./scripts/deploy-release.sh --go

# selective
./scripts/deploy-release.sh --go --only site     # just the website
./scripts/deploy-release.sh --go --skip pypi      # everything but PyPI
VERSION=v1.0.3 ./scripts/deploy-release.sh --go    # explicit tag (default: Cargo.toml)
```

The script is **dry-run by default**; nothing leaves the machine without `--go`.
It runs under git-bash on Windows too (uses `curl`, not `lftp`).

## Target details & gotchas

### 1. PyPI (installer wrapper only)
The PyPI target publishes `simplicio-installer`, a small public wrapper that
downloads the compiled binary from the public `wesleysimplicio/simplicio`
release. It does **not** build or upload the private runtime source tree.

```bash
export PYPI_TOKEN=''pypi-…''
./scripts/deploy-release.sh --go --only pypi
```

The command runs `cd packaging/pypi && python3 -m build --wheel` and uploads
only `dist/*.whl`. It must never build or upload an sdist.

### 2. Private repo (source tag)
Tags this repo and opens a GH release as a changelog anchor. No binaries (source
stays closed). Uses your current `gh auth`.

### 3. Public repo (binaries + installers)
Uploads the host binary as `simplicio-<os>-<arch>` to the `vX.Y.Z` release and
keeps `install.sh` in sync. Needs a PAT with `contents:write` on the public repo
(`GH_TOKEN_PUBLIC`); the source repo''s default token can''t write there.
CI (`.github/workflows/release.yml`) already publishes signed binaries for all
three platforms via `RELEASE_REPO_TOKEN` — prefer CI for the cross-platform set;
use this script to patch a single platform fast.

### 4. Site over FTP (the path gotcha)
The web root is **`public_html/simplicio`**, NOT the FTP home `/simplicio`
(that one is a stale staging folder — uploading there does nothing live). The
script defaults to the right path; override with `FTP_PATH` only if the host
changes. It uploads the installers and every `site/simplicio/dist/*` binary so
the **primary** CDN URL (`simpleti.com.br/simplicio/dist/simplicio-linux-x64`)
works without the GitHub fallback.

## Verify a release

```bash
# installer serves the public-repo fallback (0 = good)
curl -fsSL https://simpleti.com.br/simplicio/install.sh | grep -c simplicio-runtime/releases   # → 0
# primary CDN binary is a real ELF
curl -fsSL https://simpleti.com.br/simplicio/dist/simplicio-linux-x64 | file -                  # → ELF 64-bit … x86-64
# public release has the asset
gh release view vX.Y.Z --repo wesleysimplicio/simplicio --json assets --jq ''.assets[].name''
# end-to-end on a Linux box
curl -fsSL https://simpleti.com.br/simplicio/install.sh | sh && simplicio version
```

## Bump the version first

Never hand-edit one file — `scripts/bump-version.sh <version>` updates
Cargo.toml / pyproject.toml / Cargo.lock together, then commit, then deploy.','docs/RELEASE_DEPLOY.md','09eae6f0cb838b0eeae521adffca50c2f3d8c64778682b820b418ef92f289cec','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/RELEASE_MANIFEST.md','project_doc','doc://simplicio-runtime/docs/RELEASE_MANIFEST.md','doc: Release Manifest','# Release Manifest

Every compiled release should include a manifest so the exact local execution brain is reproducible.

## Required Fields

- runtime version;
- runtime git commit;
- target OS/arch;
- `simplicio-mapper` version and commit;
- `simplicio-dev-cli` version and commit;
- `simplicio-prompt` version and commit;
- `simplicio-sprint` version and commit;
- local model id;
- GGUF file name;
- GGUF SHA256;
- llama.cpp or binding version;
- schema versions;
- test evidence hash;
- release artifact SHA256.

## Command

```bash
simplicio version --json
```

The output should validate against `schemas/release-manifest.schema.json`.

```bash
cargo run --quiet -- version --json > /tmp/simplicio-release-manifest.json
npx --yes ajv-cli validate --spec=draft2020 --strict=false \
  -s schemas/release-manifest.schema.json \
  -d /tmp/simplicio-release-manifest.json
```

## Hash Policy

- `0.1.x`: component names, minimum versions, contract schemas, and runtime
  commit are mandatory. Component commits are required once the adapter exposes
  a stable version contract.
- Before `0.2.0` release promotion: binary SHA256, package SHA256, test
  evidence hash, model GGUF hash, and adapter commits become mandatory for
  promoted release artifacts.
- Until then, optional hashes are emitted as `null` rather than omitted so the
  manifest shape is stable.

See the release-manifest example in `examples/EXAMPLES.md`.


## Release source of truth (#3004)

A promoted release is generated from the exact immutable release tag. The
version in `Cargo.toml` is the source value; `pyproject.toml`,
`Cargo.lock`, and `site/simplicio/version.txt` must match it. CI checks this
before publication and rejects a tag/version mismatch.

`scripts/generate-release-manifest.py` is the only release-manifest writer.
It scans the four required assets — Windows x64, macOS arm64, macOS x64, and
Linux x64 — and refuses to publish unless every asset has a real byte size,
URL, SHA256, Ed25519 signature, SPDX SBOM, and provenance sidecar. The
committed JSON under `publish/github/` is a template, not a release claim;
CI replaces it with the generated manifest.

The updater matches an artifact to the current target before validating its
hash/signature. A manifest with no entry for the current target is rejected;
it cannot fall back to another platform''s first asset. The existing pre-update
snapshot and deferred/atomic rollback path remain the compatibility boundary
for memory, consciousness, MCP, and configuration state. VM validation of that
boundary is a release gate and must be evidenced by CI or an operator receipt.','docs/RELEASE_MANIFEST.md','4174f1b4041084968ece894add881f0ccf6467bff76299bb941a1f6785e43ed3','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/RELEASE_TRAIN.md','project_doc','doc://simplicio-runtime/docs/RELEASE_TRAIN.md','doc: Runtime release train','# Runtime release train

`schemas/component-release-v1.schema.json` defines the immutable release
contract produced by `simplicio-runtime`. `release-train/consumers.json` is the
single consumer authority for Loop, Agent and Code; it contains update strategy,
contract paths and required protocols, not copied version numbers.

Generate a source map once and inspect it before creating a release manifest:

```bash
python3 scripts/release-train.py map --root . > /tmp/runtime-source-map.json
```

The map hashes every existing version surface exactly once. A mismatch between
Cargo, PyPI/npm-facing metadata, lockfiles or installers exits with `2` and no
manifest is emitted. Artifacts must provide a SHA-256 digest, positive byte
count, `ed25519:` signature, SBOM and provenance reference.

After the producer manifest is signed and verified, create an idempotent
consumer plan:

```bash
python3 scripts/release-train.py plan \
  --manifest release-train/manifests/runtime.json \
  --consumers release-train/consumers.json \
  --output release-train/ecosystem-release.json
```

The plan is keyed by a canonical hash. Replaying the same release marks each
existing event `deduplicated`; a new release creates `pending` actions for the
three consumers. Promotion remains downstream-gated: N/N-1 contract
conformance, clean install/upgrade/rollback, signatures, and platform CI must
produce receipts before a release is considered stable.

The Runtime remains the execution component. This controller emits the
contract and propagation plan; it does not take ownership of Loop coordination
or silently update a worker during a run.','docs/RELEASE_TRAIN.md','dc83e431381e1c807f29e6c0b609e60d8f5170a3d2bb13152e8aa6792008bc07','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/RELEASE_VERIFICATION.md','project_doc','doc://simplicio-runtime/docs/RELEASE_VERIFICATION.md','doc: Release Verification','# Release Verification

Simplicio''s release closeout must prove the shipped binary, public distribution
metadata, and installer package are aligned without publishing runtime source.

## Official PyPI contract

The only official PyPI package in the release pipeline is
`simplicio-installer`. It
is a public binary installer/wrapper.

Do **not** publish the private runtime checkout as `simplicio-runtime` on PyPI.
Do **not** upload an sdist from this repository. Runtime distribution remains
compiled binaries plus the public installer package; source stays private.

The release workflow enforces the intended path by building from
`packaging/pypi`, running `python3 -m build --wheel`, and uploading only
`dist/*.whl`.

## Manual verification

After creating a release, run:

```bash
python3 scripts/verify-release.py --version v1.4.8 --json
```

The verifier checks:

1. local workflow source policy: wheel-only public installer path;
2. GitHub release exists and is not a draft;
3. release workflow completed successfully;
4. public distribution repo `version.txt` matches;
5. PyPI `simplicio-installer` matches;
6. `simplicio-runtime` PyPI is intentionally skipped.

Use `--skip-network` for a local source-policy-only check:

```bash
python3 scripts/verify-release.py --version v1.4.8 --skip-network
```

## Incremental formatting gate

Historical formatting debt should not block unrelated feature PRs. For scoped
changes, prefer:

```bash
scripts/check-touched-format.sh origin/main
```

Run global `cargo fmt --check` only when the task is a formatting baseline PR or
when a touched-file check indicates the current change needs formatting.','docs/RELEASE_VERIFICATION.md','0e3abdf2bf9ef9d72686bc57c26be3b7e56c432b26cb92d0ea5bf84df83926ac','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/RELIABLE_INSTALL.md','project_doc','doc://simplicio-runtime/docs/RELIABLE_INSTALL.md','doc: Reliable Runtime installation','# Reliable Runtime installation

scripts/install-runtime.sh is the strict installer for machines that need a verified Simplicio Runtime.

## Guarantees

The command fails closed unless it can:

1. use or clone a main checkout;
2. find or explicitly bootstrap Rust;
3. build the locked release binary;
4. atomically install the canonical ~/.local/bin/simplicio binary;
5. verify version --json or --version;
6. initialize neural memory, unless --skip-memory is explicitly supplied;
7. run doctor --json;
8. write a version/hash/install manifest.

It does not ask for Discord or LLM credentials during installation. Provider configuration is a separate, post-install operation.

## Examples

Build an existing authenticated checkout:

    bash scripts/install-runtime.sh --source-dir /path/to/simplicio-runtime

Clone and install in unattended mode:

    bash scripts/install-runtime.sh --yes --bootstrap-rust

Validate an offline existing checkout without fetching or bootstrapping:

    bash scripts/install-runtime.sh --source-dir /path/to/checkout --no-network

The last command is expected to fail with an actionable message if Cargo/Rust or the compiled dependencies are missing. A failure is not reported as a successful installation.

## Local LLM

The installer verifies the Runtime and neural memory. A local model is provisioned separately because model licensing, size, hardware acceleration, and storage policy are deployment-specific. The local-LLM benchmark must confirm the actual backend in its receipt; this installer never claims that a model was loaded when it was not.','docs/RELIABLE_INSTALL.md','2c2a72eeafbd1e2b85c80f53c434a42258b32112609316a9ff84db900a5b582c','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/REMEDIATION_PLAN_858.md','project_doc','doc://simplicio-runtime/docs/REMEDIATION_PLAN_858.md','doc: Remediation plan — epic #858 (anti-fake, 615 findings)','# Remediation plan — epic #858 (anti-fake, 615 findings)

Audit: `docs/AUDIT_FAKE_CODE_2026-06-11.md` (48 agents, 2026-06-11).
Execution: multi-agent workflow (modules parallel w/ exclusive file ownership,
main.rs sequential by disjoint line blocks, tests rewrite, verify+repair loop).
State for resume: `.simplicio-loop/remediation/status/*.md` + git commits on `main`
prefixed `fix(858):`.

## Cluster → issue map

| Issue | Cluster | Scope |
|---|---|---|
| #859 | A | fabricated evidence/benchmarks (benchmark_run_external_agent, value_demo, contracts_smoke, evidence_show, functional gates, sealed_receipt sha, benchmark_cases→savings, cron_tick ok) |
| #860 | B | fake observability #425 (obs_* ×6) |
| #861 | C | fake browser ×3 surfaces |
| #862 | D | fake messaging platforms (email/teams/gchat/irc/mattermost/msg_gw/webhook/whatsapp_audio) |
| #863 | E | provider integrations onboard "ready" w/o HTTP ×5 |
| #864 | F | deploy/infra (daytona, singularity, service, deploy_env) |
| #865 | G | lying persistence (yool get/query, personal_memory, deep_mem, exec_checkpoint, migrate_apply, yool_tokio, memory reset) |
| #866 | H | fake security controls (sandbox policy, logout, hooks test/doctor, stuck_agent, backpressure) |
| #867 | I | fake financial decisions (poly_agent, risk_configure) |
| #868 | J | quality theater (quality_*, auto_learn, hermes_parity_update) |
| #869 | K | schedulers/exec/voice + structured_concurrency + hybrid_state |
| #870 | L | lifecycle commands (setup/update twin/skills/plugins/dump/node_tui/electron/daemon_instances/convo NLU/video_legacy) |
| #871 | M | 232 is_ok()-only tests + offline network-success tests |
| #872 | — | dead code: parity #796–#806, taxonomy #358, orphan modules |
| #873 | N | slash commands "routed" w/o dispatch + ipc narrative |
| #874 | O | static-status families + jira/whatsapp/task_source + pr + adapters |
| #875 | P | voice/STT hardcoded + marketing/community |
| #876 | Q | vertical suites #692–#721 arg-echo |
| #877 | R | web_search fake backends, web_extract, stub modules (lsp/mcp/curator/social_ops/hermes_compat/pairing/error_recovery/levi) |
| #878 | — | MEDIUM batch (21 items) |

## Fix policy (the house rule, enforced)

1. NEVER fake success. Stub ⇒ explicit `Err("not implemented: <what''s missing>")`.
2. Real behavior implementable locally (file I/O, state reads, process spawn,
   hashing, parsing) ⇒ implement for real.
3. Needs external service ⇒ real HTTP via the existing client util, gated on
   config; unconfigured ⇒ explicit Err listing missing config.
4. Fake twin shadowing a real impl ⇒ delete twin, route to the real one.
5. Implemented+tested dead code (#796–#806, #358) ⇒ wire it in.
6. Orphan dead modules ⇒ honest Err + deletion candidate (handoff), removed in
   main.rs phase.
7. Hardcoded metrics ⇒ measure for real, or drop the field, or Err.
8. Every fixed function gets ≥1 behavioral test (observable side effect).
   `is_ok()`-only tests forbidden.
9. Zero new clippy warnings.

## Workflow phases

1. **Modules** (~35 agents, parallel) — each owns exclusive standalone files;
   never touches main.rs; cross-file needs go to `.simplicio-loop/remediation/handoff-*.md`.
2. **BuildFix** (sequential) — cargo check repair + apply handoffs + commit.
3. **MainRS** (~19 sequential block agents) — disjoint line ranges; each agent
   runs lean cargo check, fixes own fallout, commits `fix(858): <block>`.
4. **Tests** (3 sequential agents) — rewrite/delete fake tests in main.rs
   80559–83312.
5. **Verify** (repair loop ≤4) — lean `cargo test --no-default-features
   --features tui` until green, then full release build with LIBCLANG_PATH,
   final commit.

Lean check: `cargo check --no-default-features --features tui`.
Full build: `LIBCLANG_PATH=''C:\Users\Z0059V7A\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\clang\native'' cargo build --release`.

## Resume after token/context loss

1. `git log --oneline -30` — `fix(858):` commits show completed blocks.
2. `.simplicio-loop/remediation/status/` — one file per finished agent.
3. Re-launch remaining blocks with the same prompts (workflow script saved in
   the session dir; resumable via `resumeFromRunId`).','docs/REMEDIATION_PLAN_858.md','6f8e6f07c1b3f7b85b4873ed339980f6ab3ba6a4d4b5fb099e5aa33db38b76b1','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/reports/LEVANTAMENTO_FUNCIONALIDADES.md','project_doc','doc://simplicio-runtime/docs/reports/LEVANTAMENTO_FUNCIONALIDADES.md','doc: Simplicio Runtime — Levantamento Completo de Funcionalidades e Fluxos','# Simplicio Runtime — Levantamento Completo de Funcionalidades e Fluxos

> Gerado via `simplicio runtime map` + `simplicio capabilities list` + `simplicio agent status`
> Data: 2026-06-12 · Runtime: v0.9.4 (commit 6605d461)

---

## 1. COMANDOS CLI — 45 Comandos Registrados

### ✅ Ativos e funcionais

| Comando | Função | Fluxo |
|---------|--------|-------|
| `doctor` | Diagnóstico + repair | `simplicio doctor --repair --json` |
| `map` | Mapeamento de repositório | `simplicio map --repo . --json` |
| `plan` | Plano adaptativo | `simplicio plan "task" --repo . --json` |
| `decide` | Decisão via Isa/Helo (evita LLM) | `simplicio decide "task" --repo . --json` |
| `run` | Executar tarefa com evidência | `simplicio run "task" --repo . --evidence` |
| `sprint` | Task graph + sprint | `simplicio sprint sprint.md --repo . --pr` |
| `resume` | Retomar run crash-safe | `simplicio resume --run-id <id>` |
| `evidence` | Proveniência da run | `simplicio evidence show --run-id <id> --json` |
| `validate` | Plano de validação progressivo | `simplicio validate "task" --repo . --json` |
| `edit` | Edição mecânica (zero tokens) | `simplicio edit --plan plan.json` |
| `savings` | Relatório de tokens economizados | `simplicio savings report --repo . --json` |
| `computer-use` | Automação de desktop | `simplicio computer-use status --json` |
| `agent` | Operações de agente (register, claim, release) | `simplicio agent claim --issue 123 --json` |
| `status` | Snapshot de workers/queue/cache | `simplicio status --json --watch` |
| `cache` | Cache de plan/prompt | `simplicio cache status --json` |
| `memory` | Backend de memória local | `simplicio memory status --json` |
| `memory-db` | Contrato de memória neural-db | `simplicio memory-db "task" --repo . --json` |
| `skill-memory` | Skill usage + proveniência | `simplicio skill-memory "task" --repo . --json` |
| `orientation` | Orientation pack (mmap) | `simplicio orientation pack --repo . --json` |
| `capabilities` | Catálogo de capabilities | `simplicio capabilities list --json` |
| `skills` | Ranking de skills | `simplicio skills rank "task" --json` |
| `learn` | Capturar recipe de uma run | `simplicio learn from-run <id> --yes` |
| `chat` | Chat REPL + API compatível | `simplicio chat --repl --repo .` |
| `runtime` | Resource map | `simplicio runtime map --json` |
| `contracts` | Prova da cadeia standard I/O | `simplicio contracts smoke --json` |
| `version` | Manifesto de release | `simplicio version --json` |
| `update` | Auto-update | `simplicio update auto status --json` |
| `cron` | Jobs agendados | `simplicio cron status --json` |
| `login` | Identidade Google (desabilitado) | `simplicio login google --json` |
| `benchmark` | Benchmark determinístico | `simplicio benchmark run --json` |

### 🟡 Com estabilidade questionável

| Comando | Problema |
|---------|----------|
| `intake` | Parse de sprint intake — depende de NLP, não testado |
| `install` | Global install + adapters — pode falhar sem sudo |
| `serve` | MCP/local-HTTP/stdio server — modo servidor, testar |
| `adapters` | Saúde dos adapters — detecta mas não repara |
| `license` | Entitlement — sempre retorna "free, Stripe disabled" |
| `privacy` | Relatório de privacidade — funcional mas superficial |
| `reasoning` | Escolha de backend — depende de config |
| `parallelism` | Lanes de paralelismo | 

---

## 2. CAPABILITIES — 25 Capacidades Registradas

### 🟢 Installed (built-in, sempre disponíveis)

| Capability | Pack | Status |
|------------|------|--------|
| `terminal/process` | repo-intelligence | ✅ installed |
| `file/search/patch` | repo-intelligence | ✅ installed |
| `repo-locks` | agent-ops | ✅ installed |
| `evidence-ledger` | tdd-verification | ✅ installed |
| `progressive-validation` | tdd-verification | ✅ installed |
| `deterministic-shell-checks` | tdd-verification | ✅ installed |
| `release-packager` | release-ops | ✅ installed |
| `security-review` | code-review | ✅ installed |
| `git-workflow` | source-control | ✅ installed |

### 🟢 Available (adapters instalados)

| Capability | Pack | Caminho real |
|------------|------|-------------|
| `simplicio-mapper` | repo-intelligence | `~/.local/bin/simplicio-mapper` |
| `simplicio-dev-cli` | debugging | `~/.hermes/.../simplicio-dev-cli` |
| `simplicio-prompt` | token-economy | `~/.hermes/.../simplicio-subagents` |
| `simplicio-sprint` | agent-ops | `~/.local/bin/sendsprint` |
| `local-llm` | token-economy | llama.cpp Qwen 1.5B |
| `wavespeed` | generative-media | API externa |

### 🟡 External (conectores opcionais)

| Capability | Pack | Realidade |
|------------|------|-----------|
| `GitHub` | source-control | ✅ gh CLI instalado, funciona |
| `Jira` | agent-ops | ❌ Sem token/config |
| `Azure DevOps` | agent-ops | ❌ Sem token/config |
| `Playwright` | browser-evidence | ✅ Instalado |
| `Context7` | docs-research | ⚠️ Opcional |
| `computer_use` | desktop-automation | ⚠️ Sem backend config |
| `Codex CLI` | code-review | ⚠️ Opcional |
| `Claude CLI` | code-review | ⚠️ Opcional |

### 🔴 Unavailable (não podem ser usados)

| Capability | Pack | Motivo |
|------------|------|--------|
| `browser_cdp` | browser-evidence | Sem CDP URL config |
| `browser_dialog` | browser-evidence | Sem CDP URL config |
| `host-hermes-pack` | agent-ops | Disabled explicitamente |
| `root-cause-notes` | debugging | Skill externa não carregada |

---

## 3. ADAPTERS EXTERNOS — Status Real

| Adapter | Path | Real | Notas |
|---------|------|------|-------|
| `simplicio-mapper` | `~/.local/bin/simplicio-mapper` | ✅ Funciona | |
| `simplicio-dev-cli` | `~/.hermes/.../simplicio-dev-cli` | ✅ Funciona | |
| `simplicio-prompt` | `~/.hermes/.../simplicio-subagents` | ✅ Funciona | Nome do binário diferente do esperado |
| `simplicio-sprint` | `~/.local/bin/sendsprint` | ✅ Funciona | Nome diferente (`sendsprint` ≠ `simplicio-sprint`) |
| `llama-server` | `/opt/homebrew/bin/llama-server` | ✅ Funciona | |

### ❌ Adapters que deveriam existir mas não

| Adapter |','docs/reports/LEVANTAMENTO_FUNCIONALIDADES.md','cab7b5060091b28a92701904870b279fb7685d7a00ca77864ba0e963005b719f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/reports/mapper-output.md','project_doc','doc://simplicio-runtime/docs/reports/mapper-output.md','doc: Simplicio Runtime Resource Map','# Simplicio Runtime Resource Map

Schema: `simplicio.runtime-resource-map/v1` · Runtime `simplicio-runtime` v0.4.0 · Execution mode: `built-binary`

How an LLM should use this runtime:
1. Prefer deterministic built-in tools first; use a local LLM second; escalate to a remote LLM only when justified.
2. `map` before broad repo reasoning, `dev-cli` for implementation, `prompt` for contracts/fan-out, `sprint` for the task graph/status.
3. For a decided mechanical change, use `edit` with a JSON plan (zero tokens).

4. For cross-component work, require `simplicio.io/v1` read/write envelopes and verify with `simplicio contracts smoke --json`.

5. Multi-agent execution follows the compiled operational contract: LLMs orient/review/escalate, Simplicio edits deterministically, local fan-out escalates `64 -> 100 -> 200 -> 600`, and paid fallback is last resort with explicit remote policy.

## Canonical Command

- `simplicio` is the only documented user and assistant command prefix.
- Skills, installers, chat, MCP, Codex, Claude, HTTP, and stdio call the compiled runtime through `simplicio`.
- Direct binary paths and Cargo runners are developer/test harnesses, not product invocations.

## No-install vs installed
- No-install: `./target/release/simplicio runtime map --json` (or `cargo run -- runtime map --json`)
- Installed: `simplicio runtime map --json`

## Standard IO

- Runtime owns the schema registry and compatibility gate.
- Mapper reads context, prompt produces artifacts, dev-cli writes and validates, sprint records evidence, runtime performs final review.
- Smoke command: `simplicio contracts smoke --json` or `simplicio runtime smoke --json`.

## Local Memory

- Default backend order: SQLite+FTS5, SQLite+sqlite-vec, LanceDB, then Qdrant Edge.
- Use `simplicio memory status --json` to inspect availability and `simplicio memory init --json` to write the SQLite bootstrap SQL.
- FTS5 is the lightest default; sqlite-vec adds offline semantic reranking when installed.

## Zero-copy Orientation Pack

- Isa uses SQLite/FTS/vector memory to rank project docs, examples, schemas, and orientation files, then resolves `path + offset + len` into the generated pack.
- `simplicio orientation pack --repo . --json` builds `.simplicio-loop/cache/orientation.pack` and `.simplicio-loop/cache/orientation-index.json` as serialized generated artifacts.
- The runtime opens the pack read-only through `mmap`; source `.md`, docs, examples, and schemas remain editable source of truth.
- Agents never touch the SQLite neural memory or mmap pack directly; they receive materialized snippets through Simplicio, with Isa handling project/user context and Helo handling runtime/function knowledge.

## Neural Guardians

- `Isa` is the user/project neural guardian: project context, user context, docs, examples, and project memory retrieval go through Isa.
- `Helo` is the Simplicio runtime neural guardian: commands, capabilities, adapters, schemas, workflows, evidence contracts, and operational decisions go through Helo.
- All Simplicio runtime functions are indexable governed neural knowledge through Helo; Isa consults Helo when project work needs Simplicio operational knowledge.
- Provider sessions and worker agents must not touch the neural memory directly; they ask through `simplicio agent`, `memory-db`, `skill-memory`, `capabilities`, or `runtime map`.
- `Isa` keeps user-project context scoped to the project; `Levi` is the binary external knowledge acquisition agent for GitHub skills, sites, articles, Reddit, news, X.com, forums, and governed assistant-CLI consultation; Helo coordinates their instructions without bypassing deterministic Simplicio execution.

## Agent IPC

- Same-machine Simplicio agents use `iceoryx2 + rkyv` by default: pub/sub IPC in shared memory with archived binary payloads.
- Same-machine fallback is `rtrb` ring buffer in shared memory with `memmap2` and `rkyv` payloads.
- Cross-machine agents use Aeron (`aeron-rs`) or Cap''n Proto RPC; same-process agents use `Arc<T> + crossbeam-channel`.
- IPC moves typed agent events only; project/user context still goes through Isa and Simplicio runtime knowledge still goes through Helo.

## Commands

| Command | Kind | Summary | Example |
|---|---|---|---|
| `doctor` | diagnostics | check runtime, policy, adapters, model, repo | `simplicio doctor --repair --json` |
| `map` | repo-intelligence | map repository context before broad reasoning | `simplicio map --repo . --json` |
| `plan` | decision | produce an adaptive plan without executing | `simplicio plan "add tests" --repo . --json` |
| `decide` | decision | route through Isa/Helo memory first and avoid LLM calls when confidence is high | `simplicio decide "add tests" --repo . --json` |
| `run` | execution | execute a task with validation and evidence | `simplicio run "fix bug" --repo . --evidence` |
| `sprint` | execution | schedule and run a sprint task graph | `simplicio sprint sprint.md --repo . --pr` |
| `resume` | execution | crash-safe resume of a previous run | `simplicio resume --run-id <id>` |
| `evidence` | evidence | show run provenance and artifacts | `simplicio evidence show --run-id <id> --json` |
| `validate` | verification | emit the progressive validation plan | `simplicio validate "task" --repo . --json` |
| `task` | contract | normalize a task into simplicio.task/v1 | `simplicio task normalize "task" --json` |
| `edit` | deterministic-write | apply a mechanical edit plan and optionally run build/render/assert checks | `simplicio edit --plan plan.json --assert "cargo test focused_case"` |
| `savings` | observability | compare delivery with Simplicio vs a measured or estimated baseline | `simplicio savings report --repo . --json` |
| `computer-use` | desktop-automation | desktop capture/actions through explicit backend and approval policy | `simplicio computer-use status --json` |
| `agent` | agent-ops | register workers, claim issue leases, heartbeat, release, and report the multi-agent board while keeping','docs/reports/mapper-output.md','d3dda446e578ae34e5c667914b2a6943a436afef1ce90610b7bb67e25c4e1068','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/reports/SNAKE_GAME_CHALLENGE_REPORT.md','project_doc','doc://simplicio-runtime/docs/reports/SNAKE_GAME_CHALLENGE_REPORT.md','doc: 🎮 Desafio Snake Game — Relatório Comparativo','# 🎮 Desafio Snake Game — Relatório Comparativo

## Resumo Executivo

Tentativa de executar desafio comparativo **Simplicio (LLM local) × Hermes × Simplicio + DeepSeek V4 Flash** para criação de um Snake Game em React com persistência e scoreboard.

**Data:** 2026-06-08  
**Plataforma:** macOS Apple Silicon M1  
**Repositório:** `wesleysimplicio/simplicio-runtime`

---

## 🏗️ O que foi pedido

1. **Simplicio (only LLM local)** vs **Hermes** — lado a lado
2. **Simplicio + LLM local + DeepSeek V4 Flash** via OpenCodeGo
3. Gravar vídeo do processo
4. Todos devem criar: Snake Game em React com:
   - Componentes funcionais + hooks
   - Controles de teclado (setas)
   - Comida aleatória
   - Game Over + Restart
   - Persistência de pontuação (localStorage)
   - Scoreboard Top 10
   - CSS inline

---

## ✅ O que funcionou

### Simplicio Runtime (LLM Local)

| Aspecto | Status | Detalhes |
|---------|--------|----------|
| Binário compilado | ✅ | `target/release/simplicio` v0.7.0 funcional |
| Modelo local carregado | ✅ | Qwen2.5-Coder-1.5B-Instruct-Q6_K_L.gguf (1.3GB) |
| GPU offload | ✅ | 99 layers no Metal (Apple Silicon) |
| Chat básico | ✅ | Responde perguntas simples em português |
| `simplicio run` | ✅ | Executa mapeamento, evidence, benchmarks |
| Evidence generation | ✅ | Gera relatórios, logs, screenshots, traces |

**Comando que funcionou:**
```bash
./target/release/simplicio chat "crie um snake game em react..." --repo . --local --json
```

**Limitação crítica:** O modelo local **Qwen 2.5 Coder 1.5B** trunca respostas longas. Não conseguiu gerar o código completo do Snake Game (~300+ linhas). A resposta parou no meio da lógica de colisão.

**Tokens usados:** 352 local tokens, 0 remote tokens (100% local, 100% free)

---

## ❌ O que não funcionou

### 1. Hermes Agent

| Aspecto | Status | Bloqueador |
|---------|--------|------------|
| Instalação via pip | ❌ | Requer Python 3.11+ (sistema tem 3.9.6) |
| Instalação via brew | ❌ | `brew` não disponível no ambiente |
| Clone do repo | ⚠️ | Repo clonado em `/tmp/hermes-agent` mas não executável |
| Execução direta | ❌ | `python3 hermes_cli` falha (não é módulo) |

**Tentativas:**
```bash
pip install hermes-agent          # ❌ No matching distribution
python3 -m pip install hermes-agent  # ❌ Requires Python >=3.11
python3 hermes_cli --help         # ❌ can''t find ''__main__'' module
```

**Conclusão:** Hermes **inacessível** sem upgrade de Python ou container Docker.

---

### 2. OpenClaw + DeepSeek V4 Flash

| Aspecto | Status | Bloqueador |
|---------|--------|------------|
| OpenClaw instalado | ✅ | v2026.6.1 via npm global |
| Configuração lida | ✅ | `~/.openclaw/openclaw.json` com providers configurados |
| Modelo configurado | ✅ | `opencode-go/deepseek-v4-flash` como primary |
| Execução | ❌ | **ProviderAuthError: No API key found** |

**Tentativas:**
```bash
openclaw agent --local --session-key agent:snake:1 \
  --message "crie um snake game em react" \
  --model opencode-go/deepseek-v4-flash
# ❌ No API key found for provider "opencode-go"

openclaw agent --local --session-key agent:snake:2 \
  --message "crie um snake game em react" \
  --model openrouter/deepseek/deepseek-v4-flash
# ❌ No API key found for provider "openrouter"
```

**Conclusão:** OpenClaw **configurado mas sem credenciais**. Precisa de:
- API key OpenCodeGo, OU
- API key OpenRouter, OU
- API key GitHub Copilot (fallback configurado)

---

### 3. Gravação de Vídeo

| Aspecto | Status | Bloqueador |
|---------|--------|------------|
| ffmpeg | ❌ | Não instalado |
| screencapture (macOS) | ⚠️ | Disponível (`/usr/sbin/screencapture`) mas captura apenas screenshots |
| Screen recording nativo | ❌ | Sem ferramenta CLI para vídeo encontrada |

**Conclusão:** Sem ffmpeg, não é possível gravar vídeo programaticamente. Alternativa: QuickTime Player manual ou instalar ffmpeg.

---

## 🎯 Resultado do Desafio

Como os agentes (Simplicio local, Hermes, OpenClaw) não conseguiram gerar o código completo devido a limitações técnicas, **o Snake Game foi implementado manualmente** como demonstração do resultado esperado.

### 📁 Arquivos entregues

```
snake-game-demo/
├── package.json          # Dependências React 18
├── README.md             # Documentação completa
├── public/
│   └── index.html        # HTML base com meta tags
└── src/
    ├── index.js          # Entry point React 18
    └── App.js            # 🐍 Snake Game completo (~350 linhas)
```

### 🎮 Funcionalidades implementadas

| Requisito | Status |
|-----------|--------|
| Componentes funcionais + hooks | ✅ useState, useEffect, useCallback, useRef |
| Controles teclado (setas) | ✅ Arrow keys + WASD |
| Comida aleatória | ✅ Sem sobreposição com a cobra |
| Game Over | ✅ Colisão parede + próprio corpo |
| Restart | ✅ Botão + tecla Espaço |
| Persistência localStorage | ✅ Top 10 scores com timestamp |
| Scoreboard | ✅ Com emojis 🥇🥈🥉 |
| CSS inline | ✅ Zero dependências de estilo |
| Aceleração progressiva | ✅ Velocidade aumenta a cada comida |
| Pausa | ✅ Tecla Espaço |
| Dark theme | ✅ Com efeitos glow |

### ▶️ Como rodar

```bash
cd snake-game-demo
npm install
npm start
# Abre em http://localhost:3000
```

---

## 📊 Comparativo Teórico (o que seria)

| Critério | Simplicio (Local) | Hermes | Simplicio + DeepSeek |
|----------|-------------------|--------|----------------------|
| **Modelo** | Qwen 2.5 Coder 1.5B | (variável) | DeepSeek V4 Flash |
| **Custo** | $0 (100% local) | $0-$5 (depende) | ~$0.02-0.10 |
| **Velocidade** | ~30-60s resposta | ~20-40s | ~10-30s |
| **Qualidade código** | ⚠️ Trunca arquivos grandes | ✅ Gera completo | ✅ Gera completo |
| **Validação automática** | ✅ Evidence, tests, lint | ⚠️ Básica | ✅ Via Simplicio runtime |
| **Persistência estado** | ✅ SQLite + Yool | ❌ | ✅ SQLite + Yool |
| **Agentes paralelos** | ✅ 64-600 lógicos | ❌ Single | ✅ 64-600 lógicos |
| **Token economy** | ✅ Máximo | ❌ Médio | ✅ Otimizado |
| **Offline** | ✅ Total | ❌ | ❌ (precisa API) |

---

## 🔧 Próximos passos para ex','docs/reports/SNAKE_GAME_CHALLENGE_REPORT.md','edaba07502f818cb5ff1aaed8dd4bba87f0a4d781bea7c814bd26d70c935237d','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/research/jessebrown1980-repos/backlog.md','project_doc','doc://simplicio-runtime/docs/research/jessebrown1980-repos/backlog.md','doc: Backlog From JesseBrown1980 Repository Extraction','# Backlog From JesseBrown1980 Repository Extraction

## Runtime Backlog

### RT-1: Add `execution_state` To Runtime Envelopes

Problem: agents can overstate planned or dry-run work as executed.

Acceptance criteria:

- Define `execution_state` enum: `proposed`, `planned`, `dry_run`, `authorized`, `executed`, `verified`, `rejected`.
- Apply it to task, result, evidence, workflow, and handoff envelopes where mutation or external action can occur.
- Add schema tests that reject missing state on mutation-capable events.
- Update runtime map docs to explain that `verified` requires evidence refs, not model self-report.

### RT-2: Runtime Ledger JSONL

Problem: evidence exists, but a minimal verifiable event chain should be reusable across workflows, loop runs, and external acquisition.

Acceptance criteria:

- Add `simplicio.runtime-ledger-event/v1`.
- Persist `event_id`, `prev_sha`, `actor`, `tool`, `input_hash`, `output_hash`, `execution_state`, `verdict`, `evidence_refs`.
- Add command: `simplicio hbp append-runtime-event --repo . --json` or fold into existing `hbp/evidence` surfaces.
- Add integrity check: recompute chain and report first broken row.

### RT-3: Typed Memory Handoffs

Problem: cross-agent continuity is currently scattered across summaries, memory, and conversation context.

Acceptance criteria:

- Add `simplicio memory-handoff begin|accept|expire|status --repo . --json`.
- Accept is one-shot and race-safe.
- Fields include `cwd`, `from_agent`, `to_agent`, `summary`, `open_questions`, `next_steps`, `files_touched`, `state`, `evidence_refs`.
- Handoffs are indexed in FTS and linked to runtime ledger events.

### RT-4: Single-Writer Evidence/Memory Actor

Problem: parallel workers and hooks need backpressure and serialized persistence.

Acceptance criteria:

- Add a bounded write queue for hook/evidence/memory ingress.
- Return explicit queued/backpressure status.
- Ensure source row and FTS update happen in the same transaction.
- Add `doctor` checks for queue capacity, WAL mode, and stale writer health.

### RT-5: Critical Path And Conflict Engine

Problem: loop dispatch needs deterministic prioritization and collision avoidance.

Acceptance criteria:

- Add DAG validation: duplicate IDs, missing dependencies, cycles, invalid estimates.
- Compute topological order, earliest/latest timing, slack, and critical path.
- Add generic resource conflict detection using `resource_id`, `resource_type`, window, capacity, participants.
- Emit suggestions: reschedule, split, alternate worker, alternate worktree, wait for dependency.

### RT-6: `policy decide` Surface

Problem: some actions need recommendation artifacts before gated execution.

Acceptance criteria:

- Add a decide-only command that returns recommended action and rationale but never mutates.
- Cover PR merge/close/rebase/hold, release/publish, destructive filesystem/database operations, and external acquisition.
- Include required latch/gate metadata for actions that need approval.

### RT-7: External Repo Intake And Audit Packets

Problem: third-party repo research is ad hoc.

Acceptance criteria:

- Add `simplicio external-repo intake <owner/repo|url> --json`.
- Emit repo URL, commit, license, pushed date, file counts, manifests, scripts, tests, architecture notes, reject list, and candidate Simplicio capabilities.
- Generate audit packet files: `ARCHITECTURE`, `AUDIT_EXTRACT`, `FIX_QUEUE`, `NEXT_STEP_PROMPTS`, `INSTALL_BLOCKED`.
- Include license mode: `copy-ok`, `reimplement-only`, `reference-only`, `reject`.

### RT-8: Artifact Processor Registry

Problem: docs, media, PDFs, JSONL, and knowledge graphs need governed processing.

Acceptance criteria:

- Add processor metadata: input types, toolchain needs, max size, privacy class, output schemas, evidence artifacts.
- Provide initial processors for docs/web pages, repo inventories, audio/video transcription, PDF, JSONL, OWL/RDF.
- Refuse auto-installing missing system packages during request handling; surface `doctor` remediation instead.

### RT-9: Provider Router Hardening

Problem: provider behavior differs across models and APIs.

Acceptance criteria:

- Add provider capability matrix, alias mapping, streaming normalizer, thinking-channel normalizer, rate-limit/backoff, provider trace.
- Treat heuristic tool-call parsing as untrusted until schema and gate validation pass.
- Add tests for SSE normalization, 429 backoff, malformed tool call text, and provider trace redaction.

### RT-10: Hooks Status In Doctor

Problem: MCP/hooks/client installation state is spread across clients.

Acceptance criteria:

- Add `simplicio hooks status --json`.
- Report per client: binary on PATH, hook installed, hook enabled, bundle version, config path, last error.
- Consume results in `simplicio doctor --json`.

## Loop Backlog

### LOOP-1: Critical-Path Prioritization

Problem: queue order should consider dependency pressure, not only age or issue order.

Acceptance criteria:

- Consume runtime critical-path output.
- Rank zero-slack and high-risk tasks ahead of low-pressure tasks.
- Show why a task was selected.

### LOOP-2: Conflict-Aware Dispatch

Problem: workers can collide on same worktree, PR, file scope, release gate, provider quota, or human review slot.

Acceptance criteria:

- Ask runtime conflict engine before worker claim.
- Block or reschedule conflicting claims.
- Emit suggested resolution in loop status.

### LOOP-3: Worker Lease And Two-Latch Flow

Problem: expensive or dangerous actions need a fresh preflight before execution.

Acceptance criteria:

- Every worker claim has a lease, owner, TTL, heartbeat, and release.
- Two-latch mode for risky actions: approve plan, then approve execution with current context.
- Dry-run is default until latch conditions are met.

### LOOP-4: Per-Environment Evidence

Problem: one green local result should not imply global success.

Acceptance criteria:

- Track evidence by vantage: local, CI, browser, registry, GitHub, user-machi','docs/research/jessebrown1980-repos/backlog.md','beba351bff403d050dfe2b237b091a4dfbe7c843912d99d64c4f17ad2f02fce9','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/research/jessebrown1980-repos/extraction-plan.md','project_doc','doc://simplicio-runtime/docs/research/jessebrown1980-repos/extraction-plan.md','doc: JesseBrown1980 Repository Extraction Plan','# JesseBrown1980 Repository Extraction Plan

## Corpus

Inventory source: `gh repo list JesseBrown1980 --limit 200 --json ...` on 2026-06-30.

High-signal repositories inspected directly or by subagents:

| Cluster | Repositories | Signal |
|---|---|---|
| Asolaria / BEHCS | `asolaria-behcs-256`, `asolaria-federation-1024`, `Algorithms-of-Asolaria`, `HYPER-BECHS--the-third-set`, `Asolaria-hermes-work` | Ledgers, receipts, execution-state discipline, worker leases, quorum/policy gates |
| Rust / terminal / memory | `ai-memory`, `intelligent-terminal`, `omnicoder---better-than-termux`, `Asolaria-helper` | Long-term memory, single-writer store, typed handoffs, process topology, no-exec endpoint profile |
| Agent/coding forks | `kimi-code`, `free-claude-code`, `shannon`, `OpenMythos`, `HRM` | Kernel/SDK/TUI boundary, provider normalization, durable multi-agent workflow, adaptive reasoning depth |
| Docs / extraction / local LLM | `Docs-Extractor`, `Local-LLM-Minutes-of-Meeting`, `llama-instruct-dataset-prep-agent`, `my-hybrid-bert-project` | Governed extraction, media-to-knowledge, JSONL stage ledgers, validators |
| Planning / workflow | `scala-critical-path-planner`, `schedule-manager`, `custom-tree`, `EventDriven` | DAG validation, critical path, resource conflicts, dependency tree UX |
| Product apps | `ipa-activity-generator-ptbr`, `Itilitii-health-login-demo`, `daisy-backend`, `daisy-client`, `spread-sheet-demo`, `tech-trades`, `warran` | Audit packets, job lifecycle, provider registry, board UX, safety gates |
| Healthcare / enterprise sampled locally | `AI-healthCare-project`, `FHIR-Lamba`, `Everyrealm-AWS-CDK` | Compliance/audit traces, API/service layering, deployment evidence patterns |

## Best Patterns To Absorb

### 1. Explicit Execution State

Asolaria repos repeatedly distinguish planned capacity from live execution using flags like `E=0`, `spawn_allowed=false`, and "port is not spawn". That discipline is directly useful.

Add an explicit state machine to Simplicio envelopes and workflow events:

```text
proposed -> planned -> dry_run -> authorized -> executed -> verified
                         \-> rejected
```

This prevents README claims, model summaries, or partial receipts from being treated as live execution.

### 2. Append-Only Runtime Ledger

Multiple repos use append-only rows, sidecar hashes, cosign chains, and last-row folding. The durable idea is a simple verifiable ledger, not the BEHCS vocabulary.

Runtime contract candidate:

```json
{
  "schema": "simplicio.runtime-ledger-event/v1",
  "event_id": "uuid-or-sha",
  "prev_sha": "sha256-or-null",
  "actor": "agent-or-tool",
  "tool": "simplicio command or adapter",
  "input_hash": "sha256",
  "output_hash": "sha256",
  "execution_state": "planned|dry_run|authorized|executed|verified|rejected",
  "verdict": "pass|fail|blocked|info",
  "evidence_refs": ["path-or-url"]
}
```

Use JSONL/NDJSON for interoperability; pipe rows can inspire compact append logs but should not replace typed schemas.

### 3. Single-Writer Memory And Evidence Store

`ai-memory` has the cleanest storage lesson: fire-and-forget hooks feed a bounded queue; one writer owns SQLite/WAL writes; markdown/wiki remains inspectable source of truth; FTS5 is first, vector rerank is optional and measurement-gated.

Runtime implication:

- No worker agent writes raw memory/evidence SQL.
- Hook ingress returns queued/backpressure status instead of unbounded buffering.
- Evidence, FTS rows, and derived summaries commit transactionally.
- `sqlite-vec` or heavier vector backends remain optional until p95 latency, corpus size, or recall evals justify them.

### 4. Typed Handoffs

Cross-agent continuity should be a first-class contract. `ai-memory` and `simplicio-loop` both point at the same need: a loop should accept prior state before work and write unresolved state after work.

Runtime command candidate:

```text
simplicio memory-handoff begin --repo . --json
simplicio memory-handoff accept --repo . --json
simplicio memory-handoff expire --repo . --json
simplicio memory-handoff status --repo . --json
```

Suggested fields: `workspace_id`, `project_id`, `cwd`, `from_agent`, `to_agent`, `summary`, `open_questions`, `next_steps`, `files_touched`, `state`, `evidence_refs`.

### 5. Durable Workflow Graphs And Stage Ledgers

`shannon` contributes the strongest workflow shape: preflight, specialist phases, resumable checkpoints, audit sessions, retries, deliverables, and final report assembly. `llama-instruct-dataset-prep-agent` contributes practical JSONL ledgers per stage.

Runtime should formalize:

- `pipeline.stage/v1`: stage id, input schema, output schema, validator, retry policy, evidence ref, cost/token metrics.
- `stage_events.jsonl`: append-only source for resume and postmortem.
- Compact summaries indexed into SQLite/FTS.

Loop should consume this as a graph, not a linear script:

```text
orient -> map -> plan -> fanout -> validate -> repair -> report
```

### 6. Critical Path And Resource Conflict Engine

`scala-critical-path-planner` and `schedule-manager` point to a small deterministic kernel:

- validate duplicate IDs, missing dependencies, bad durations, and cycles
- compute topological order, earliest/latest timing, slack, and critical path
- detect overlapping resources with typed conflicts
- produce suggestions

This belongs in `simplicio-runtime`; `simplicio-loop` should use it to rank work and avoid collisions.

Resource conflict contract should be generic:

```json
{
  "resource_id": "repo:path-or-provider-quota",
  "resource_type": "worktree|file|provider|ci|release|human|token_budget",
  "window_start": "timestamp-or-null",
  "window_end": "timestamp-or-null",
  "capacity": 1,
  "participants": ["worker-id"],
  "suggestions": ["reschedule", "split", "alternate-worker", "alternate-worktree"]
}
```

### 7. Provider Router And Streaming Normalizer

`free-claude-code` is useful as an architectural reference, not as product positioning. Absorb:','docs/research/jessebrown1980-repos/extraction-plan.md','adce22110470932d4c836a207a6cb26a0e8cfd53d61e7334f6ee8efc957d9133','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/research/jessebrown1980-repos/index.md','project_doc','doc://simplicio-runtime/docs/research/jessebrown1980-repos/index.md','doc: JesseBrown1980 Repository Extraction','# JesseBrown1980 Repository Extraction

Date: 2026-06-30

Scope: public repositories under <https://github.com/JesseBrown1980?tab=repositories>, analyzed for patterns worth absorbing into `simplicio-runtime` and `simplicio-loop`.

Artifacts:

- [extraction-plan.md](./extraction-plan.md) - evidence-backed synthesis, absorb/reject decisions, and architecture recommendations.
- [backlog.md](./backlog.md) - concrete implementation backlog split by runtime and loop.

Execution notes:

- `gh repo list JesseBrown1980 --limit 200` returned 59 public repositories.
- 24 high-signal repositories were shallow-cloned under `~/.cache/simplicio-runtime/jessebrown-repos/` for local inspection.
- 6 subagents analyzed independent clusters: Asolaria/BEHCS, Rust/terminal/memory, agent/coding forks, docs/extraction/local LLM, planning/workflows, and product apps.
- `simplicio-runtime 1.4.9` was used for orientation and capability ranking. Runtime parallelism allowed 12 logical agents, but the Codex subagent host capped actual subagent threads at 6.

Primary conclusion:

The best material is not code to copy. The reusable value is a set of control-plane patterns: append-only ledgers, explicit execution state, durable workflows, critical-path planning, typed handoffs, provider routing, bounded extraction, artifact processors, privacy/safety gates, and per-environment evidence. `simplicio-runtime` should own the contracts and gates; `simplicio-loop` should consume them for prioritization, dispatch, UI, and evidence-driven iteration.','docs/research/jessebrown1980-repos/index.md','d43f727b9bd26d4e0312aa438f401d77c44b84ec87fc7c3567f13067350e29be','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/research/zvec-absorption.md','project_doc','doc://simplicio-runtime/docs/research/zvec-absorption.md','doc: Zvec absorption for Simplicio','# Zvec absorption for Simplicio

Date: 2026-07-05  
Source: https://github.com/alibaba/zvec

## Verified upstream facts

The upstream project describes Zvec as:

- an **open-source, in-process vector database**;
- **pure local** / no server by default;
- supporting **dense + sparse vectors**;
- including **native full-text search (FTS)**;
- supporting **hybrid retrieval** across vector, text, and filters;
- using **write-ahead logging (WAL)** for durability;
- offering official SDKs including **Python** (`pip install zvec`) and **Node.js**;
- presenting additional ecosystem references for **Go** and **Rust** SDKs in the README/release notes.

These claims were checked against the upstream README on `main` on 2026-07-05.

## What Zvec means for Simplicio

Zvec is strategically interesting because it compresses three things Simplicio currently splits across separate lanes:

1. vector search,
2. full-text retrieval,
3. hybrid ranking/filtering inside one local engine.

That maps well to Simplicio''s local-first memory model, where today the canonical backend ladder is:

1. `sqlite-fts5`
2. `sqlite-vec`
3. `lancedb`
4. `qdrant-edge`

## Why Zvec is **not** a runtime backend yet

As of this absorption pass, Simplicio does **not** implement a real `zvec` backend. The current runtime memory surface is built around backend ids that are actually recognized by the code and exposed by `memory status`. Adding `zvec` there immediately would be a false claim.

The current gap is architectural, not conceptual:

- Simplicio''s memory backend detection is presently shaped around local binaries / explicit external availability checks.
- Zvec is primarily presented upstream as an **embedded SDK / in-process database**, not as the exact standalone local binary contract Simplicio already uses for `sqlite3`, `sqlite-vec`, `lancedb`, and `qdrant`.
- Therefore the right first absorption is **canonical design knowledge**, not a fake backend label.

## Best fit inside the runtime

Zvec best fits as a future **local hybrid memory backend** when Simplicio wants one engine to own:

- lexical search,
- dense retrieval,
- sparse retrieval,
- structured filtering,
- durability via WAL,
- large-corpus scaling without jumping immediately to a daemon/server architecture.

In Simplicio terms, Zvec is closest to a possible future replacement or superset for the middle-heavy lane between `sqlite-vec` and `lancedb/qdrant-edge`.

## Recommended adoption path

### Phase 1 — done in this pass

- Record a canonical absorption note in the runtime docs.
- Clarify in the operational manual that `zvec` is a tracked candidate, not an active backend.

### Phase 2 — safe implementation path

Do **not** expose backend id `zvec` until all of the following exist:

1. backend contract decision
   - embedded Rust SDK,
   - Python sidecar, or
   - dedicated adapter process.
2. deterministic availability detection
   - e.g. `SIMPLICIO_ZVEC_*` envs or a known adapter executable.
3. real query strategy mapping in `memory status`.
4. real validation path proving insert/query/delete lifecycle.
5. real evidence in docs and receipts.

### Phase 3 — runtime surfacing

Only after Phase 2 should Simplicio update:

- `is_memory_backend(...)`
- memory backend error/help text
- `memory_backend_json(...)`
- `memory_backend_order_json(...)`
- `recommended_next` guidance
- the operational manual
- any map/status receipts that promise available backends

## Design recommendation

If Simplicio adopts Zvec, prefer a **minimal adapter boundary** instead of binding the whole runtime tightly to a new engine-specific API surface. A narrow adapter keeps the current backend ladder honest and preserves the ability to A/B test:

- `sqlite-vec` for cheapest semantic uplift,
- `zvec` for local hybrid retrieval,
- `lancedb` / `qdrant-edge` for heavier corpora or specialized deployments.

## Bottom line

Zvec is a strong candidate for Simplicio''s future local hybrid-memory lane because it combines vector, text, and filtering in one in-process system. But **today it is absorbed as design knowledge, not as an implemented backend**, because that is the only claim the runtime can currently support honestly.','docs/research/zvec-absorption.md','f3d647aefeaf6db7211ef493cb7a59672a6f14b1b046ca58bc8ecc37848e166f','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/RESEARCH_EVALUATION.md','project_doc','doc://simplicio-runtime/docs/RESEARCH_EVALUATION.md','doc: Research & Evaluation Notes','# Research & Evaluation Notes

Documents findings and recommendations for issues #173–#179, #190, #193.

---

## #173 — Skills Framework (superpowers/obsidian-skills/SkillOpt)

**Status**: Evaluated. The existing `simplicio skills` + `simplicio skill-memory`
implements the core of what these frameworks offer:
- SKILL.md metadata per skill
- Hermes-style usage/provenance memory
- Lazy top-k ranking per task (BM25 + neural memory)

**Recommendation**: The existing framework is sufficient. Integration with
`obsidian-skills` patterns can be done by authoring SKILL.md files following
the existing schema. `SkillOpt` patterns (skill composition graphs) are a
future enhancement — file as a separate feature issue when needed.

---

## #174 — Agentic RAG / Graph RAG for neural memory

**Status**: Evaluated. The current FTS5 + BM25 retrieval in `simplicio memory query`
handles standard RAG. Graph RAG would require:
1. `memory_relationships` table (already in schema)
2. Graph traversal at query time
3. Optional: GNN-based re-ranking

**Recommendation**: The `memory_relationships` table is already defined in
migration 0001. Implement graph traversal in `memory_query_sqlite` when
relationship data is populated. Start with 2-hop `REFERENCES` traversal.
Defer GNN ranking to a `sqlite-vec` enhancement.

---

## #175 — MCP / Browser Automation as native skills

**Status**: Evaluated. The existing `simplicio mcp` command provides the MCP
layer. Browser automation via `simplicio browser` uses Playwright.

**Recommendation**: Register browser and MCP tools as SKILL.md entries so
the skills ranker surfaces them for web-related tasks. The skill metadata
should include `tool: mcp` or `tool: playwright` so routing is deterministic.
No new code needed — skill authoring task only.

---

## #176 — Multi-Agent Orchestration (TradingAgents patterns)

**Status**: Evaluated. `simplicio agents` and `simplicio parallel` provide
multi-agent dispatch. The `multi_agent_chat_dispatch_json` function handles
chat-level multi-agent routing.

**Recommendation**: The TradingAgents pattern (specialized sub-agents for
different domains) can be implemented as named agents in `simplicio agents`.
The key missing piece is a structured inter-agent message protocol. File
a concrete issue for "agent message protocol v2" when the use case is clear.

---

## #177 — TradingAgents patterns in Yool / multi-agent orchestration

**Status**: Evaluated. Overlaps with #176. Yool-specific patterns:
- Portfolio allocation → `simplicio run` with `--parallel` flag
- Risk management → action gate (#231) safe mode
- Signal aggregation → multi-agent dispatch

**Recommendation**: The existing runtime covers the orchestration substrate.
Yool-specific agents are adapters on top. No runtime changes needed.

---

## #178 — Codegraph for mapper and neural memory context

**Status**: Evaluated. The current mapper (`simplicio map`) produces
`project-map.json` with function/file/dependency metadata. Codegraph would
extend this with call-graph edges stored in `memory_relationships`.

**Recommendation**: Extend `mapper_neural_integrate` to populate
`memory_relationships` with `relation_type=''calls''` edges from project-map.json.
This is a 1-sprint enhancement to the existing mapper, not a new subsystem.

---

## #179 — Skills Framework (superpowers/obsidian-skills)

**Status**: Overlaps with #173. See #173 recommendation.

The `simplicio skills` command already implements the core: lazy loading,
SKILL.md metadata, usage tracking, provenance. The `superpowers` pattern
(chaining skills) can be expressed as a multi-step plan in `simplicio plan`.

---

## #190 — P1 Hermes: conversational brain with intent, ordered context, memory, skills

**Status**: Partially implemented across multiple PRs.

**What''s done**:
- Intent classification: `classify_task()` in chat routing
- Ordered context slots: `ChatContextSlots` (#233 — this PR)
- Memory retrieval: `chat_memory_results()` + FTS5
- Skills ranking: `chat_context_skills()` + BM25

**What remains**:
- Structured intent types (beyond simple kind classification)
- Multi-turn context window management
- Proactive suggestions from memory

**Recommendation**: The `ChatContextSlots` struct is the foundation for
ordered context. Next step: wire intent classification output into slot
selection (e.g., `smalltalk` intent skips `project_rules` slot).

---

## #193 — P2 Pi.dev: extensions, packages, session/RPC

**Status**: Partially implemented.

**What''s done**:
- Session: `ReplSession` struct with transcript, history, ledger
- Extensions: `simplicio skills` + SKILL.md packages
- RPC: `simplicio serve` (basic HTTP server)

**What remains**:
- Formal extension package format (beyond SKILL.md)
- WebSocket/SSE for `chat --json-stream`
- Plugin hot-reload (experimental; not shipped yet)

**Recommendation**: The existing `simplicio serve` provides the HTTP layer.
`chat --json-stream` can be implemented by streaming `chat_answer` via SSE.
File a specific issue for "chat SSE streaming" when ready.','docs/RESEARCH_EVALUATION.md','a663d9f38d43fa2160135f9e23d6a1679124a68c9a3942195df19dc500f3bc09','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/AUTO_PLATFORM_SPEC.md','project_doc','doc://simplicio-runtime/docs/roadmap/AUTO_PLATFORM_SPEC.md','doc: Auto Platform Specification','# Auto Platform Specification

## Overview

Simplicio Auto brings the personal assistant into the vehicle: EV integration
(BYD, Tesla, BMW), a voice-first in-car interface, and an ambient mode that
provides context-aware information without requiring active interaction.

Target milestones: v0.3 (EV integration + voice-first), v0.4 (ambient mode + fleet).

---

## 1. EV Integration (#2197, #2198, #2199)

### Supported Vehicles

#### Tesla
- API: Tesla Fleet API v2 (OAuth2, `energy:read`, `vehicle_state:read`,
  `vehicle_cmds:write`).
- Data: battery_level, range_km, charging_state, location, climate, lock state.
- Commands: start_charge, stop_charge, set_charge_limit, climate_on/off, lock/unlock.
- Authentication: `simplicio auto tesla auth` → OAuth2 PKCE flow in browser.

#### BYD
- API: BYD Open Platform (REST, `X-BYD-Token`).
- Data: SOC, range_km, charging_state, ADAS status, door state.
- Commands: remote_ac_on/off, charge_now, find_my_car (horn + lights).
- Authentication: `simplicio auto byd auth --vin <VIN> --username <email>`.

#### BMW / Mini
- API: BMW Connected Drive API (OAuth2).
- Data: fuel/SOC, range, door/window state, lock, last_trip, mileage.
- Commands: lock/unlock, flash_lights, start_climate.
- Authentication: `simplicio auto bmw auth`.

### Data Model
```rust
struct VehicleState {
    vin: String,
    make: VehicleMake,      // Tesla | BYD | BMW | Generic
    soc_pct: Option<f32>,   // state of charge
    range_km: Option<f32>,
    charging: Option<ChargingState>,
    location: Option<(f64, f64)>,   // lat, lon
    climate_on: bool,
    locked: bool,
    odometer_km: Option<f32>,
    last_updated: DateTime<Utc>,
}

struct ChargingState {
    connected: bool,
    charging: bool,
    charge_limit_pct: u8,
    minutes_to_full: Option<u32>,
    power_kw: Option<f32>,
}
```

### Commands
```
simplicio auto status [--vin <VIN>]
simplicio auto charge start [--limit 80]
simplicio auto charge stop
simplicio auto climate on [--temp 22]
simplicio auto lock
simplicio auto unlock
simplicio auto navigate "Charging station"    # send destination to car nav
simplicio auto trips list [--days 30]
simplicio auto energy summary [--month 2026-06]
```

### Gate Policy
| Command | Gate level |
|---|---|
| status / trips / energy | safe |
| climate on/off | auto |
| charge start/stop / limit | auto |
| lock | ask |
| unlock | ask |
| navigate | auto |

### Polling
- Background daemon polls vehicle state every 5 min when not charging.
- Every 60 s when charging.
- Proactivity engine triggers:
  - SOC < 20%: alert with nearest charger.
  - Charging complete: notification.
  - Charge limit reached: notification.

---

## 2. Voice-First Interface (#2221)

### In-Car Voice
The in-car voice interface is a specialized profile of the Personal Assistant
voice commands (see `PERSONAL_ASSISTANT_SPEC.md`), optimized for:

- Hands-free, eyes-free operation (no need to look at screen).
- Low-latency responses (< 1 s for mechanical commands).
- Driving-context awareness (location, speed, ETA).
- Integration with Android Auto / CarPlay via companion app (v0.4).

### In-Car Wake Word
- Default: "Hey Simplicio, drive"
- Separate Porcupine model tuned for vehicle cabin noise.

### Driving Intents
```
"What''s my range?"              → auto status --field range_km
"Start charging when I arrive"  → auto charge schedule --on-arrive
"Navigate to the nearest Tesla Supercharger"  → auto navigate "Tesla Supercharger"
"What''s the traffic to work?"   → proactivity traffic --dest work
"Read my messages"              → notify digest --audio
"Call home"                     → computer-use call "Home" via phone
"Set cabin temp to 22"          → auto climate on --temp 22
```

### Response Design
- Driving mode: maximum 2 sentences per response, no lists.
- Non-driving (parked): full response available.
- Speed detection: if `speed_kmh > 5`, enforce driving-mode response format.

### Audio Ducking
- When TTS speaks, reduce media volume to 20% (via OS audio session API).
- Restore after TTS ends.

---

## 3. Ambient Mode (#2199, #2221)

### Model
Ambient mode surfaces contextual information passively — on a small screen
or HUD — without requiring voice interaction or active attention.

### Display Tiers
| Tier | Hardware | Content |
|---|---|---|
| HUD | Windshield projection (CarPlay/AA) | SOC, range, speed, ETA |
| Dashboard | Car infotainment 7-10" | Full ambient card |
| Companion screen | Phone/tablet on dash mount | Extended card |

### Ambient Card Layout
```
┌─────────────────────────────────────┐
│  🔋 78%  ·  312 km  ·  ⚡ 11 kW    │  ← vehicle state
│  📍 ETA: Work 14:23 (22 min)        │  ← navigation
│  🌡  22°C cabin  ·  🌤 Sunny 28°C   │  ← climate
│  📅 Next: Team meeting 15:00        │  ← calendar
│  📩 3 unread · 0 urgent             │  ← messages
└─────────────────────────────────────┘
```

### Update Frequency
- Vehicle state: 60 s
- Navigation ETA: 30 s
- Calendar: 5 min
- Messages: 2 min

### Ambient Triggers (proactive interrupts in ambient mode)
| Event | Display |
|---|---|
| SOC drops below threshold | Banner: "Low battery — charger 3 km ahead" |
| Meeting in 10 min | Banner: "Team meeting in 10 min" |
| Charging complete | Banner: "Charging complete — 100%" |
| Traffic incident on route | Banner: "Heavy traffic ahead — alternate route available" |
| Speed camera (where legal) | Banner: "Speed limit: 80 km/h" |

### Privacy in Ambient Mode
- Ambient display is local-only (no screen capture, no cloud).
- Location used only for ETA + charger search; not stored beyond session.

---

## 4. Fleet Mode (v0.4 Preview)

For users managing multiple vehicles (family, small fleet):

- Multi-vehicle dashboard: all vehicles on one screen.
- Shared charging schedule: optimize charge times across vehicles.
- Trip log aggregation: all vehicles, one report.
- Mesh sync: household devices receive fleet status updates.

---

## Configuration

```toml
[auto]
enabled = false

[[auto.vehicles]]
vin = "5YJ3E1EA0LF000001"
make = "','docs/roadmap/AUTO_PLATFORM_SPEC.md','bc265a64799876a6cdc38814cc8f00948551992f061d03fc1cfc89fa133aeff8','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/BUSINESS_MODEL.md','project_doc','doc://simplicio-runtime/docs/roadmap/BUSINESS_MODEL.md','doc: Simplicio Business Model','# Simplicio Business Model

## Tiers

### Free
- Local execution only (qwen local model)
- Up to 10 tasks/day via CLI
- Community support (Discord/GitHub Issues)
- Core features: map, edit, validate, memory recall
- No Action Bridge (read-only gate)

### Pro — $29/month
- Unlimited local tasks
- Remote LLM escalation (OpenRouter/Anthropic) with usage quota (500k tokens/month)
- Action Bridge + action gate (ask/auto modes)
- Video pipeline (Remotion + HyperFrames, deterministic)
- Priority Discord support
- Delivery certificates + regression guard
- Dashboard + analytics

### Enterprise — $199/month (per seat, 5-seat minimum)
- Unlimited remote LLM usage (metered, billed separately)
- Higgsfield video generation (generative, gated per call)
- Multi-agent fabric (full 600-agent burst)
- SSO + audit log + compliance exports
- Dedicated Slack channel + SLA
- Custom model routing (bring your own key)
- White-label CLI binary option

---

## LLM-as-a-Service Model

Simplicio runs the 5-stage local-first ladder before reaching a paid remote:

```
Stage 1: in-process qwen (64 agents)
Stage 2: qwen expanded (100 agents)
Stage 3: qwen burst (200 agents)
Stage 4: qwen full (600 agents)
Stage 5: remote LLM (paid, gated, explicit --remote flag required)
```

**Revenue lever:** each Stage 5 escalation is a billable event. Pro plan includes a token quota; overages billed at cost + 20% margin. Enterprise negotiates flat usage contracts.

**Model neutrality:** runtime routes to the cheapest capable model; provider is abstracted behind `SIMPLICIO_MODEL` / `SIMPLICIO_BASE_URL`. Locks never vendor a single provider.

---

## Feature Gating

Gating is enforced at the binary level via the Action Gate (`action_gate` / `action_bridge`). License tier is read from `~/.simplicio-loop/license.json` (JWT, verified offline against embedded public key, refreshed weekly).

| Feature | Free | Pro | Enterprise |
|---|---|---|---|
| Local execution (all stages) | 10/day | unlimited | unlimited |
| Remote LLM escalation | — | 500k tokens/mo | unlimited (metered) |
| Action Bridge (write actions) | — | yes | yes |
| Video pipeline (deterministic) | — | yes | yes |
| Higgsfield generative video | — | — | yes (per-call cost) |
| Multi-agent fabric (600-agent) | — | — | yes |
| Delivery certificate | — | yes | yes |
| Audit log / compliance export | — | — | yes |
| Dashboard | read-only | full | full |

---

## Subscription Management

- **Billing:** Stripe (LIVE mode). Plan stored in `~/.simplicio-loop/license.json`.
- **Upgrade flow:** `simplicio account upgrade` → opens browser to Stripe checkout → webhook updates license → CLI polls for updated JWT.
- **Cancellation:** immediate downgrade to Free at end of billing period. Data (memory, checkpoints) retained 90 days.
- **Trial:** 14-day Pro trial on signup (no credit card required for local-only features).

---

## Revenue Streams

1. **Subscription SaaS** — Pro/Enterprise monthly recurring (primary).
2. **Usage overage** — Remote LLM tokens above Pro quota; Higgsfield per-call (Enterprise).
3. **Binary distribution** — one-time purchase option for air-gapped Enterprise deployments ($499 perpetual + $99/yr updates).
4. **Professional services** — onboarding, custom skill development, private model fine-tuning ($200/hr).
5. **Marketplace (future)** — third-party skills/adapters sold through simplicio.sh/marketplace; 30% platform cut.

---

## Usage Tracking

All usage is tracked locally first (append-only HBP ledger), synced to the cloud billing endpoint on connectivity:

- **Events logged:** task start/end, stage reached (1–5), tokens consumed (local vs remote), action gate decisions, delivery certificates issued, video renders.
- **Privacy:** local events are hashed (SHA-256 salted per-install); the cloud endpoint receives aggregated counts + tier-enforcement signals, never raw prompts or file contents.
- **Dashboard:** `simplicio usage` shows local ledger. Pro/Enterprise dashboard at `localhost:9119/usage` and `simplicio.sh/dashboard` (authenticated).
- **Rate limiting:** Free tier enforced via local counter + cloud confirmation on first daily task.','docs/roadmap/BUSINESS_MODEL.md','cab83b12734ae2606ccbfd6628d59c35ff9a0ead036dd3f6eb4db44e0aea3912','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/CLOUD_ARCHITECTURE.md','project_doc','doc://simplicio-runtime/docs/roadmap/CLOUD_ARCHITECTURE.md','doc: Cloud Architecture','# Cloud Architecture

> **STATUS: PLANNED — NOT IMPLEMENTED (verified 2026-06-27).** This is a design
> document only. `src/cloud/*` does not exist; the symbols it describes
> (`CloudGateway`, `cloud_auth`, `crdt_merge`, `from_connectivity`, sync engine, …)
> are absent. Issues #2133–#2137 were closed as "completed" but no code landed
> (see `docs/ISSUE_AUDIT_2026-06-27.md`). Re-open those issues before treating any
> of this as built. (The shipped `simplicio backup` base is the only cloud-adjacent
> code, and it is a gated scaffold, not this architecture.)

## Overview

Simplicio Cloud provides encrypted backup, cross-device sync, and cloud auth
while maintaining an offline-first, privacy-first design. The local runtime is
fully functional without cloud connectivity; cloud features are additive.

Target milestones: v0.2 (sync engine + backup), v0.3 (cloud auth + teams).

---

## 1. Sync Engine Design (#2126, #2127, #2128)

### Principles
- **Offline-first:** every write succeeds locally; sync is background.
- **Conflict-free:** CRDT-based for memory/settings; last-write-wins for files.
- **Minimal surface:** only user-tagged items sync (`scope=cloud`).

### Data Model
```
SyncRecord {
  id:         Uuid          // stable across devices
  kind:       SyncKind      // Memory | File | Setting | Skill
  key:        String
  value_hash: [u8; 32]      // SHA-256 of encrypted payload
  hlc:        HybridLogicalClock
  tombstone:  bool
  device_id:  Uuid
}
```

### Sync Protocol (HTTPS/2, JSON)
```
POST /v1/sync/push
  body: [SyncRecord]        // delta since last_sync_cursor

GET  /v1/sync/pull?since=<cursor>&device=<id>
  response: [SyncRecord]    // server-side delta

PUT  /v1/sync/resolve
  body: {local: SyncRecord, remote: SyncRecord, winner: "local"|"remote"|"merge"}
```

### Conflict Resolution
1. Memory items: HLC timestamp wins; equal timestamp → merge (union of values).
2. Settings: last-write-wins by HLC.
3. Files/skills: three-way diff; present conflict to user if unresolvable.
4. Tombstones propagate (delete wins after 30-day grace period).

### Sync Cursor
- Each device maintains `last_sync_cursor: {server_seq: u64, device_cursors: Map<Uuid, u64>}`.
- Stored in `.simplicio-loop/cloud/sync_state.json` (local, not synced).

---

## 2. Backup System (#2129, #2130)

### What Gets Backed Up
| Item | Default | User-controlled |
|---|---|---|
| Neural memory (FTS+vector) | yes | yes |
| Settings / config | yes | yes |
| Skills (user-authored) | yes | yes |
| Chat history | no | opt-in |
| Binary assets | no | opt-in |
| Credentials / secrets | never | no |

### Backup Format
- Encrypted archive: AES-256-GCM, key derived from user passphrase (Argon2id).
- Key never leaves the device; server stores only ciphertext.
- Snapshots: incremental daily, full weekly, retention 90 days.
- Manifest: `{snapshot_id, timestamp, item_count, size_bytes, hash}` stored in plaintext for listing.

### Backup Flow
```
Trigger: schedule (02:00 local) | manual | pre-update
  → collect changed items since last_backup_cursor
  → serialize to CBOR
  → encrypt with device key
  → upload chunks (4 MB each) to /v1/backup/chunks/<snapshot_id>/<seq>
  → commit manifest to /v1/backup/manifests/<snapshot_id>
  → update last_backup_cursor
```

### Restore Flow
```
simplicio cloud restore [--snapshot <id>] [--dry-run]
  → list snapshots from /v1/backup/manifests
  → download + decrypt chunks
  → validate hash
  → apply to local store (with --dry-run: show diff only)
```

---

## 3. Cloud Auth (#2131, #2132)

### Identity Model
- Primary identity: Ed25519 keypair generated on first run, stored in OS keychain.
- Cloud account: email + password (bcrypt) OR OAuth2 (Google, GitHub).
- Device registration: signed challenge proves possession of device keypair.

### Auth Flow
```
simplicio cloud login
  → POST /v1/auth/challenge  ← {challenge: bytes}
  → sign challenge with device key
  → POST /v1/auth/token  body: {email, password, device_sig, device_pub}
  → receive {access_token (JWT, 1h), refresh_token (opaque, 30d)}
  → store tokens in OS keychain
```

### Token Refresh
- Background refresh 5 min before expiry.
- On 401: silent refresh once; if refresh fails → prompt re-login.

### Multi-Device
- Each device has its own keypair and refresh token.
- Revoke a device: `simplicio cloud devices revoke <device_id>`.
- Server invalidates refresh token; device tokens expire naturally (max 1 h).

### Scopes
| Scope | Grants |
|---|---|
| `sync:read` | Pull sync records |
| `sync:write` | Push sync records |
| `backup:read` | List + download backups |
| `backup:write` | Upload backups |
| `team:read` | Read team membership |

---

## 4. Offline-First Approach (#2133, #2134)

### Core Invariant
> Every Simplicio command works without network. Cloud features degrade gracefully.

### Degradation Table
| Feature | Offline behavior |
|---|---|
| Neural memory read/write | Full (local SQLite) |
| Sync push | Queued in `.simplicio-loop/cloud/outbox.jsonl` |
| Sync pull | Stale data served from last pull |
| Backup | Skipped; retried on next connectivity event |
| Cloud auth | Cached JWT used until expiry; then local-only mode |
| Skill install from registry | Fails with clear error; mesh fallback if available |

### Connectivity Detection
- Passive: system network change events (via OS APIs).
- Active probe: `GET /v1/health` every 60 s when previously offline.
- On reconnect: drain outbox → pull delta → reconcile conflicts.

### Outbox Schema
```json
{"id":"…","kind":"sync_push","payload":{…},"queued_at":"…","attempts":0}
```
- Max outbox size: 50 MB; oldest entries evicted first.
- Retry backoff: 5 s → 30 s → 5 min → 30 min → give up after 24 h.

---

## Configuration

```toml
[cloud]
enabled = false             # opt-in
endpoint = "https://cloud.simplicio.ai"
sync = true
backup = true
backup_schedule = "02:00"
backup_retention_days = 90
offline_jwt_ttl_hours = 24  # how long to accept a cached JWT offline
```

---

## Implementation Phases

| Phase','docs/roadmap/CLOUD_ARCHITECTURE.md','3056dc5485f767b2851889e8f4fe8b578d72d6e43a25c509f88622110c80c4d6','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/DOCUMENTATION_PLAN.md','project_doc','doc://simplicio-runtime/docs/roadmap/DOCUMENTATION_PLAN.md','doc: Simplicio Documentation Plan','# Simplicio Documentation Plan

## Site Structure (simplicio.sh)

```
/                       — landing page (hero, token savings counter, quick install)
/docs/                  — documentation root
  /docs/getting-started — install + first task in 5 minutes
  /docs/concepts/       — local-first ladder, action gate, HBP ledger, memory
  /docs/commands/       — CLI reference (map, edit, memory, gate, deliver, …)
  /docs/api/            — HTTP/MCP API reference (auto-generated)
  /docs/tutorials/      — step-by-step guides
  /docs/video-pipeline/ — Remotion + HyperFrames + Higgsfield guide
  /docs/integrations/   — IDE adapters (Zed, VSCode, JetBrains ACP)
/changelog/             — versioned changelog (auto-generated from git tags)
/faq/                   — frequently asked questions
/benchmark/             — Simplicio × Hermes × OpenClaw live scoreboard
/pricing/               — tier comparison + Stripe checkout
/blog/                  — long-form posts
```

---

## API Reference Generation

The CLI exposes a machine-readable schema via `simplicio schema --json`. The doc pipeline:

1. `simplicio schema --json > docs/api/schema.json` (run in CI on every release).
2. Static site generator (mdBook or Docusaurus) consumes `schema.json` and renders `/docs/api/`.
3. Each command gets: description, flags, examples, return schema, token cost estimate.
4. MCP tool definitions exported separately: `simplicio mcp-schema --json > docs/api/mcp.json`.

**CI hook:** `scripts/gen-api-docs.sh` runs after `cargo test` on every push to `main`; output committed to `docs/api/` if changed.

---

## Video Demos (Remotion)

All demo videos are produced deterministically via Remotion (`apps/simplicio-desktop/src/remotion/`). Each video is a self-contained `.tsx` composition.

### Planned compositions

| File | Title | Length | Purpose |
|---|---|---|---|
| `GettingStarted.tsx` | Install & First Task | 2 min | Getting started page embed |
| `TokenSavingsCounter.tsx` | Token Savings Explainer | 45s | Landing page hero |
| `ActionGateDemo.tsx` | Action Gate in Action | 90s | Concepts page |
| `DeliveryCertificate.tsx` | Delivery Certificate | 60s | Quality delivery page |
| `VideoPipelineDemo.tsx` | Video Creation End-to-End | 3 min | Video pipeline docs |
| `BenchmarkRace.tsx` | Simplicio × Hermes × OpenClaw | 2 min | Benchmark page |

**Render pipeline:**
```
npx remotion render src/remotion/index.tsx <CompositionId> out/<name>.mp4
```
Outputs committed to `docs/assets/video/` (Git LFS) and embedded in docs pages.

---

## Interactive Tutorials

Each tutorial is a guided walkthrough runnable in the browser (via a WASM-compiled Simplicio stub) or locally.

### Planned tutorials

1. **"Your first mechanical edit"** — use `simplicio edit` to rename a variable across a file without touching the LLM.
2. **"Memory recall vs re-derive"** — run `simplicio memory` before solving a problem; see the token diff.
3. **"Closing the loop with delivery gate"** — `simplicio deliver check` + `deliver certify` on a real PR.
4. **"Create a motion-graphics video"** — storyboard → HyperFrames template → `ffmpeg` render → final MP4.
5. **"Multi-agent fan-out"** — `simplicio run --agents 64` on a batch of linting tasks; observe the scaling.

**Implementation:** tutorials are Markdown files with inline runnable shell blocks (rendered by a custom mdBook preprocessor that sends commands to a sandboxed Simplicio WASM instance in the browser). Local option: `simplicio tutorial start <name>`.

---

## Changelog

- **Source:** git tags + GitHub Releases. Format: [Keep a Changelog](https://keepachangelog.com/).
- **Auto-generation:** `scripts/gen-changelog.sh` reads `git log --tags --simplify-by-decoration` and groups commits by type (feat/fix/chore/docs/perf).
- **Published at:** `simplicio.sh/changelog/` and `CHANGELOG.md` in repo root.
- **Notification:** Discord `#releases` channel pinged on every new tag via GitHub Actions webhook.

---

## FAQ

Maintained at `docs/faq.md`. Updated on every GitHub milestone close. Top questions:

1. **Does Simplicio send my code to the cloud?** — No. Local execution uses in-process qwen. Remote escalation requires explicit `--remote` flag.
2. **How is token savings calculated?** — See `docs/concepts/token-savings.md` for the formula.
3. **Can I use my own API key?** — Yes. Set `SIMPLICIO_API_KEY` + `SIMPLICIO_BASE_URL` + `SIMPLICIO_MODEL`.
4. **Is the source code available?** — Runtime is closed-source (compiled binary only). Adapters (`simplicio-cli`, `simplicio-mapper`) are open-source on PyPI/GitHub.
5. **How do I upgrade?** — `simplicio account upgrade` for Pro/Enterprise, or `simplicio self-update` for the binary.
6. **What LLMs are supported?** — Any OpenAI-compatible endpoint + Anthropic + Gemini + DeepSeek + Mistral + local qwen via llama.cpp.

---

## Doc Maintenance Schedule

| Task | Frequency | Owner |
|---|---|---|
| API reference regen | Every release | CI (automated) |
| Tutorial review | Monthly | maintainer |
| FAQ update | On milestone close | maintainer |
| Video re-render | On major feature | maintainer |
| Changelog publish | On every git tag | CI (automated) |
| Site audit (broken links) | Weekly | CI (lychee link checker) |','docs/roadmap/DOCUMENTATION_PLAN.md','41cbf940b4117d7e3674914963b77bf45d9c3dfe46e421d259033e31ca5533ce','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/ENTERPRISE_SPEC.md','project_doc','doc://simplicio-runtime/docs/roadmap/ENTERPRISE_SPEC.md','doc: Enterprise Spec','# Enterprise Spec

## Overview

Enterprise tier features for Simplicio: team management, role-based access control,
manager dashboard, comparative reports, and export/scheduling capabilities.

---

## 1. Team Management

### Concepts
- **Organisation** — top-level billing unit (owns a Stripe customer).
- **Workspace** — sub-unit within an org (e.g. a department or project).
- **Member** — a user with a role in one or more workspaces.

### Data model
```
organisations (id UUID PK, name TEXT, slug TEXT UNIQUE, plan TEXT,
               stripe_customer_id TEXT, created_at TIMESTAMPTZ,
               owner_id UUID FK users)

workspaces (id UUID PK, org_id UUID FK, name TEXT, slug TEXT,
            created_at TIMESTAMPTZ)

org_members (org_id UUID FK, user_id UUID FK, role TEXT, invited_at TIMESTAMPTZ,
             accepted_at TIMESTAMPTZ nullable,
             PRIMARY KEY (org_id, user_id))

workspace_members (workspace_id UUID FK, user_id UUID FK, role TEXT,
                   PRIMARY KEY (workspace_id, user_id))
```

### Invite flow
1. Admin `POST /orgs/{org}/invites` `{ email, role }` → stores pending invite, sends email.
2. Invitee clicks link → `GET /orgs/{org}/invites/{token}` → shows org name + role.
3. If email matches existing account → accept. Else → sign up first.
4. `POST /orgs/{org}/invites/{token}/accept` → creates `org_members` row.

### Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/orgs` | List user''s orgs |
| POST | `/orgs` | Create org |
| GET | `/orgs/{org}` | Org detail |
| PATCH | `/orgs/{org}` | Update org name/settings |
| GET | `/orgs/{org}/members` | List members |
| POST | `/orgs/{org}/invites` | Invite member |
| DELETE | `/orgs/{org}/members/{user}` | Remove member |
| GET | `/orgs/{org}/workspaces` | List workspaces |
| POST | `/orgs/{org}/workspaces` | Create workspace |

---

## 2. Role-Based Access Control (RBAC)

### Org-level roles
| Role | Capabilities |
|------|-------------|
| `owner` | All permissions; transfer ownership; delete org |
| `admin` | Manage members, workspaces, billing; cannot delete org |
| `billing_admin` | View/manage billing only |
| `member` | Use product; cannot manage org settings |
| `viewer` | Read-only access to reports and dashboards |

### Workspace-level roles
| Role | Capabilities |
|------|-------------|
| `workspace_admin` | Manage workspace members and settings |
| `editor` | Create/edit content in workspace |
| `viewer` | Read-only |

### Permission resolution
```
effective_permission = max(org_role_permission, workspace_role_permission)
```

### Enforcement
- Middleware: `require_permission(resource, action)` checks JWT claims + DB lookup.
- JWT includes `org_id`, `org_role`, `workspace_ids[]`.
- DB row-level security (RLS) as second enforcement layer on Postgres.

---

## 3. Manager Dashboard

### Overview panel
- Active members count, seats used vs purchased.
- Token usage by workspace (current month vs previous).
- Cost breakdown (LLM spend, storage, API calls).
- Alert badges (members inactive >30d, approaching quota).

### Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/orgs/{org}/dashboard` | Aggregated overview metrics |
| GET | `/orgs/{org}/usage` | Usage time series (day/week/month) |
| GET | `/orgs/{org}/members/{user}/usage` | Per-member usage |
| GET | `/orgs/{org}/workspaces/{ws}/usage` | Per-workspace usage |

### Response schema (dashboard)
```json
{
  "org_id": "uuid",
  "period": "2026-06",
  "members": { "active": 24, "seats": 30 },
  "tokens": { "used": 4200000, "budget": 10000000 },
  "cost_usd": 84.00,
  "workspaces": [
    { "id": "ws1", "name": "Engineering", "tokens": 2100000, "members": 12 }
  ]
}
```

---

## 4. Comparative Reports

### Report types
| Report | Dimensions | Metrics |
|--------|-----------|---------|
| Member productivity | member × period | tasks completed, tokens used, time saved |
| Workspace comparison | workspace × period | usage, cost, active days |
| Plan ROI | org × period | cost vs baseline (no-Simplicio estimate) |
| Trend | org × day/week/month | growth/decline of key metrics |

### Generation
- Reports run as background jobs (async, < 60s for most).
- Results cached 1 hour; invalidated on new usage data.
- `POST /orgs/{org}/reports` `{ type, period, dimensions[] }` → `{ job_id }`.
- `GET /orgs/{org}/reports/{job_id}` → status + result when ready.

### Export formats
- JSON (default), CSV, PDF (via headless browser render of HTML template).

---

## 5. Export / Scheduling

### On-demand export
`GET /orgs/{org}/export?type=usage&format=csv&from=2026-01-01&to=2026-06-30`
→ Streams CSV/JSON directly or returns signed URL for large files (>10 MB).

### Scheduled reports
```
scheduled_reports (id UUID PK, org_id UUID FK, report_type TEXT,
                   cron TEXT, format TEXT, recipients TEXT[],
                   created_by UUID FK, enabled BOOL, last_run_at TIMESTAMPTZ)
```

- Cron runner (Tokio interval or system cron): generates report, emails to `recipients`.
- UI: "Schedule this report" in manager dashboard → set frequency + recipients.

### Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/orgs/{org}/export` | On-demand export |
| GET | `/orgs/{org}/scheduled-reports` | List schedules |
| POST | `/orgs/{org}/scheduled-reports` | Create schedule |
| PATCH | `/orgs/{org}/scheduled-reports/{id}` | Update |
| DELETE | `/orgs/{org}/scheduled-reports/{id}` | Delete |

---

## 6. Enterprise SSO (Future)

Planned additions (not in initial scope):
- SAML 2.0 IdP integration (Okta, Azure AD, Google Workspace).
- SCIM 2.0 for user provisioning/deprovisioning.
- Audit log export (SOC 2 readiness).
- Custom domain for hosted workspace (`acme.simplicio.ai`).','docs/roadmap/ENTERPRISE_SPEC.md','24d9c92259307bc61387394ad0f5c9a5121408b85e1f546b72513335cafa7a6a','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/GHOST_MODE_SPEC.md','project_doc','doc://simplicio-runtime/docs/roadmap/GHOST_MODE_SPEC.md','doc: Ghost Mode Spec — Counter-Factual Display','# Ghost Mode Spec — Counter-Factual Display

## Overview

Ghost Mode is a display feature that shows the user what Simplicio *prevented*
on every interaction: tokens that would have been spent without it, edits that
would have required LLM output, remote calls that were served locally.
It surfaces the "invisible savings" as a concrete counter-factual in the UI.

Target milestone: v0.4.

## Motivation

Users see what Simplicio does; they do not see what it prevents.
Ghost Mode makes the prevented work visible, reinforcing the value proposition
and letting users tune their usage to maximize savings.

## Counter-Factual Model

For each interaction, the runtime computes a `GhostReport`:

```rust
pub struct GhostReport {
    /// tokens actually spent (LLM I/O this turn)
    pub tokens_spent: u32,
    /// estimated tokens without Simplicio
    pub tokens_baseline: u32,
    /// operations served from local/deterministic path (no LLM)
    pub local_ops: Vec<LocalOp>,
    /// remote escalations avoided
    pub remote_escalations_avoided: u32,
    /// edits applied mechanically (zero LLM output tokens)
    pub mechanical_edits: u32,
    /// memory recalls that replaced re-derivation
    pub memory_recalls: u32,
}
```

### Baseline estimation rules

| What happened | Baseline cost (tokens) |
|---|---|
| `simplicio map` used instead of bulk-reading N files | N × 200 (avg file size) |
| `simplicio memory` recall instead of re-derivation | 500 per query |
| `simplicio edit` mechanical write | output_lines × 3 (LLM would have written them) |
| Local fan-out agent completed task | 2000 (remote LLM alternative) |
| Action gate blocked unsafe action | 1000 (recovery cost prevented) |

These are conservative estimates. The runtime tracks actual tool call results
to refine estimates over time.

## Display Modes

### 1. Token-savings line (always on)

Every response ends with:

```
Simplicio: ~<spent> tokens spent · without Simplicio ~<baseline> · saved ~<saved> (<pct>%)
```

This is already the standing rule in `CLAUDE.md`. Ghost Mode formalizes it as
a structured runtime computation, not a manual estimate.

### 2. Ghost overlay (TUI, opt-in)

When `ghost-mode` is enabled in the REPL, a right-hand panel shows:

```
┌─ Ghost Mode ────────────────────────┐
│ This turn                           │
│  Tokens spent:    142               │
│  Without Simplicio: ~3 400          │
│  Saved: ~3 258 (95%)               │
│                                     │
│ Prevented:                          │
│  • 12 files read via map (saved    │
│    ~2 400 tokens)                   │
│  • 3 memory recalls (saved ~1 500) │
│  • 1 mechanical edit (saved ~500)  │
│  • 0 remote escalations            │
└─────────────────────────────────────┘
```

Toggle: `/ghost` in the REPL, or `--ghost` CLI flag.

### 3. Session summary (on exit)

```
Session ghost report:
  Turns: 24
  Total tokens spent: 4 200
  Estimated without Simplicio: 89 000
  Total saved: 84 800 (95%)
  Remote escalations avoided: 18
  Mechanical edits applied: 7
```

Written to `.simplicio-loop/sessions/<id>/ghost_report.json`.

## Data Sources

| Source | What it provides |
|---|---|
| `simplicio map` call log | files that would have been read |
| `simplicio memory` call log | queries that replaced re-derivation |
| `simplicio edit` call log | mechanical edits (zero LLM tokens) |
| Action gate decision log | unsafe actions blocked |
| HBP evidence chain | ground-truth event sequence |

## Implementation Plan

### Phase 1 — Instrumentation (v0.4-alpha)

- Add `GhostReport` struct to `src/ghost_mode.rs`.
- Instrument `map`, `memory`, `edit`, and `action_gate` to emit events to a
  per-session ghost log (append-only JSONL under `.simplicio-loop/sessions/<id>/`).
- Compute `tokens_spent` from actual LLM response metadata.

### Phase 2 — Display (v0.4-beta)

- Token-savings line: pull from `GhostReport` instead of manual estimates.
- TUI overlay: right-hand ratatui panel, toggled by `/ghost`.
- Session summary: printed on REPL exit.

### Phase 3 — Refinement (v0.4)

- Historical trend: rolling 7-day savings chart in the dashboard (:9119).
- Per-capability breakdown: show which Simplicio feature saved the most.
- Export: `simplicio ghost report --json` for programmatic consumption.

## Schema: `simplicio.ghost-report/v1`

```json
{
  "schema": "simplicio.ghost-report/v1",
  "session_id": "...",
  "turn": 3,
  "tokens_spent": 142,
  "tokens_baseline": 3400,
  "tokens_saved": 3258,
  "pct_saved": 95,
  "local_ops": [
    { "kind": "map", "files": 12, "tokens_saved": 2400 },
    { "kind": "memory_recall", "queries": 3, "tokens_saved": 1500 },
    { "kind": "mechanical_edit", "edits": 1, "tokens_saved": 500 }
  ],
  "remote_escalations_avoided": 0
}
```','docs/roadmap/GHOST_MODE_SPEC.md','1a255557394eb9af2444397c01d68a93d256bc8b6d0e7c72b66a4eb172d19b3c','doc,simplicio',1.1);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('doc:simplicio-runtime:docs/roadmap/LEGAL_COMPLIANCE.md','project_doc','doc://simplicio-runtime/docs/roadmap/LEGAL_COMPLIANCE.md','doc: Legal & Compliance Spec','# Legal & Compliance Spec

## Scope
LGPD (Brazil Lei 13.709/2018) + GDPR (EU 2016/679) dual compliance for Simplicio
web product and runtime telemetry.

---

## 1. LGPD / GDPR Checklist

### Lawful basis
| Data category | Lawful basis (LGPD) | Lawful basis (GDPR) |
|---------------|---------------------|---------------------|
| Account (email, name) | Contract execution (Art. 7 V) | Contract (Art. 6(1)(b)) |
| Usage telemetry | Legitimate interest (Art. 7 IX) | Legitimate interest (Art. 6(1)(f)) |
| Marketing emails | Consent (Art. 7 I) | Consent (Art. 6(1)(a)) |
| Payment data | Legal obligation (Art. 7 II) | Legal obligation (Art. 6(1)(c)) |
| Support tickets | Legitimate interest | Legitimate interest |

### Required disclosures
- [ ] Privacy Policy published at `simplicio.ai/privacy` — bilingual (PT + EN).
- [ ] Terms of Service at `simplicio.ai/terms`.
- [ ] Cookie Policy / Banner (see §3).
- [ ] DPO contact: `privacy@simplicio.ai`.
- [ ] ANPD registration (Brazil) when applicable (>50k subjects).

### Data subject rights (must be fulfilled within 15 days BR / 30 days EU)
| Right | Endpoint | Notes |
|-------|----------|-------|
| Access | `GET /me/data-export` | Returns JSON archive |
| Rectification | `PATCH /me` | Any field except `google_sub` |
| Erasure | `DELETE /me` | Triggers deletion workflow (§5) |
| Portability | `GET /me/data-export?format=csv` | CSV + JSON |
| Restriction | `POST /me/restrict-processing` | Pauses all ML training use |
| Objection | `POST /me/opt-out-marketing` | Removes from marketing lists |

---

## 2. Data Retention Policy

| Data type | Retention | Deletion trigger |
|-----------|-----------|------------------|
| Active account | Indefinite | User-initiated erasure or 2yr inactivity |
| Session tokens | 7 days | Rolling expiry |
| Invoices / receipts | 7 years | Legal obligation (tax) — anonymised after |
| Usage telemetry | 12 months | Auto-purge cron job |
| Support tickets | 3 years | Auto-purge |
| Error logs | 90 days | Log rotation |
| Backups | 30 days | Automated snapshot lifecycle |
| Deleted account data | 30 days grace | Hard delete after grace period |

### Anonymisation vs deletion
After the retention window, PII fields are **anonymised in-place** (not physically
deleted) for records that must be kept for legal/financial reasons:
```sql
UPDATE invoices SET user_email = ''anon@deleted'', user_name = ''Deleted User''
WHERE user_id = $1 AND created_at < NOW() - INTERVAL ''7 years'';
```

---

## 3. Cookie Consent

### Cookie categories
| Category | Cookies | Default state |
|----------|---------|---------------|
| Strictly necessary | `session`, `csrf_token` | Always on — no consent needed |
| Analytics | `_ga`, `_simplicio_analytics` | Off until consent |
| Marketing | `_fbp`, `_ttq` | Off until consent |
| Preferences | `locale`, `theme` | On (legitimate interest) |

### Consent banner
- Shown on first visit, re-shown after 12 months.
- Three buttons: **Accept all**, **Reject all**, **Manage preferences**.
- Consent stored in `localStorage` + synced to `user_consents` table (authenticated).
- No analytics/marketing scripts load until consent given (script injection is consent-gated).

### Implementation
```
user_consents (user_id UUID FK nullable, session_id TEXT,
               analytics BOOL, marketing BOOL,
               consented_at TIMESTAMPTZ, ip_country TEXT)
```

---

## 4. Data Processing Agreement (DPA) Template

### Sections required
1. **Subject matter and duration** — processing on behalf of the Controller.
2. **Nature and purpose** — SaaS service provision, analytics, support.
3. **Type of personal data** — names, emails, usage logs, payment references.
4. **Categories of data subjects** — registered users, trial users.
5. **Obligations of the Processor** (Simplicio):
   - Process only on documented instructions.
   - Ensure personnel confidentiality.
   - Implement appropriate technical/organisational measures (TOMs).
   - Engage sub-processors only with prior written consent.
   - Assist Controller with DSAR requests.
   - Delete/return all data at contract end.
   - Provide audit evidence.
6. **Sub-processors list** (Annex):
   - Stripe Inc — payment processing — USA (SCCs)
   - Resend Inc — transactional email — USA (SCCs)
   - Hetzner Online GmbH — hosting — EU (GDPR-adequate)
   - Cloudflare Inc — CDN/DDoS — USA (SCCs)
7. **International transfers** — SCCs (EU) or Standard Contractual Clauses.
8. **Liability and indemnification**.
9. **Governing law** — Brazilian law (LGPD) for BR customers; Irish law (GDPR) for EU.

DPA template file: `docs/legal/DPA_TEMPLATE.docx` (to be drafted by legal counsel).

---

## 5. Account Deletion Workflow

### Trigger
`DELETE /me` (authenticated) or admin action.

### Steps
```
1. Mark account as pending_deletion (users.status = ''pending_deletion'', deletion_scheduled_at = NOW() + 30d)
2. Send confirmation email (template: account_deleted.html) with undo link.
3. Revoke all active sessions immediately.
4. Stop all billing (cancel Stripe subscription, Mercado Pago plan, PayPal).
5. After 30-day grace period (cron):
   a. Anonymise PII in invoices older than 7yr retention threshold.
   b. Delete invoices within retention window (or anonymise, see §2).
   c. Delete user_consents, sessions, usage_logs, support_tickets.
   d. Delete users row (or set status=''deleted'', nullify PII fields).
   e. Purge from email marketing lists (Resend contact delete).
   f. Write deletion certificate to audit_log (non-PII: user_id hash, timestamp).
6. If user signs in during grace period → cancel deletion, restore account.
```

### Audit log entry
```json
{
  "event": "account_deleted",
  "user_id_hash": "sha256:abc123",
  "timestamp": "2026-06-18T00:00:00Z",
  "requested_by": "user_self|admin",
  "grace_period_end": "2026-07-18T00:00:00Z"
}
```','docs/roadmap/LEGAL_COMPLIANCE.md','8d61d6538e12cd225073bca3e9b7435364ec8d03af2d7e2351791d0f44a9b748','doc,simplicio',1.1);
