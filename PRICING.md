# 💳 Pricing & Monetization — simplicio-loop

> **Status: proposal (draft).** This document sketches a paid offering on top of the
> open-source simplicio-loop. It is a business proposal for the maintainer to decide on — the
> core stays free and open. Nothing here is billed today.

## Model — Open-core + usage-based hosted tier

The **engine stays MIT and free**: the `/simplicio-tasks` orchestrator, the five satellite
skills, the hooks, the 50 extension points, and the token-economy stack. Adoption is the moat —
the free tier must be fully usable, self-hostable, and never crippled.

The **paid offering is convenience + scale**, not the code:

| Tier | Price (suggested) | Who | What you get beyond the free core |
|---|---|---|---|
| **Community** | **Free, MIT** | individuals, OSS | Full engine self-hosted. All skills, hooks, local token-economy dashboard, local video_evidence (hyperframes local render). No limits you didn't set yourself. |
| **Pro (hosted)** | **~$29 / dev / mo** | small teams | Managed 24/7 watcher (survives reboot, we run it), hosted token-economy dashboard with **history + savings reports**, the `simplicio-mapper` / `simplicio-dev-cli` operators as a service, priority model-routing. Soft usage cap. |
| **Team / Cloud** | **usage-based** (see below) | orgs | Everything in Pro + multi-repo fleets, SSO, audit log, distributed `video_evidence` render (hyperframes on AWS Lambda), per-seat + per-run metering, SLA. |
| **Enterprise** | **custom** | regulated | Self-hosted control plane, on-prem operators, commercial license/indemnity, support. |

Why open-core (vs. dual-license or pure-SaaS): the skill's whole thesis is *"the skill names no
runtime; the runtime detects the skill"* — portability is the product. Gating the engine would
break that. We charge for **running it for you** (the watcher, the operators, the dashboard, the
fleet), which is exactly the part that costs us compute.

### What is free forever (never gated)
- The orchestrator loop + all 7 skills + hooks.
- Local token economy: `orient_clamp.py`, the capture engine, `savings_ledger` on disk, the
  local dashboard at `http://127.0.0.1:9090`.
- `video_evidence` **local** render (hyperframes via local Node 22+/FFmpeg).
- Self-hosting on any of the 12 runtimes.

### What the paid tiers add (convenience + scale, not capability lock-in)
- **We host the 24/7 watcher** so it survives reboots without the user running their own cron.
- **Hosted operators** — `simplicio-mapper` + `simplicio-dev-cli` as a managed service (no local install).
- **Savings history + team dashboard** — the local one-session view becomes a retained,
  multi-repo, multi-seat analytics surface.
- **Distributed video render** — `video_evidence` offloaded to hyperframes/AWS Lambda for big
  walkthroughs (local render stays free).

---

## 💰 Billing architecture — sketch

The good news: the metering primitives **already exist** in the repo. Billing is mostly a matter
of aggregating what the loop already records, never a new measurement layer.

### 1. The meters we already produce

| Primitive | File / source | What it gives billing |
|---|---|---|
| **Savings ledger** | `savings_ledger` ext-point · `scripts/savings_harness.py` · `proxy_savings.json` | REAL token spend per session (snapshot→score, fixed `ceil(chars/4)` tokenizer) + tokens saved |
| **Capture proxy** | `engine/simplicio_engine.py` (`proxy`) · `scripts/simplicio-economy.sh` | actual upstream token usage per provider call (already intercepted) |
| **Run outcomes** | `trajectory` ext-point | per-run records → unit of "a delivered item" for per-run pricing |

```text
loop turn ──> capture proxy (real upstream tokens)
          ──> savings_ledger (spent + saved, deterministic score)
                         │
                         ▼
              billing aggregator (NEW, thin)
                         │
          ┌──────────────┼───────────────┐
          ▼              ▼                ▼
   per-seat (Pro)  per-run (Team)   metered usage (Cloud)
```

### 2. Three meters → three price levers

- **Per-seat (Pro):** flat; the aggregator only checks an active-seat count. No new metering.
- **Per-run (Team):** one `trajectory` record = one billable "delivered item". Count
  closed/merged items from the source re-query the loop already does at delivery (Step 6).
- **Metered usage (Cloud):** sum usage from the capture proxy/savings ledger, plus managed-operator
  minutes and Lambda render seconds. The prepaid-credit guard is billing-only: it flags
  over-balance but never writes runtime stop state.

### 3. The aggregator (the only new component) — ✅ implemented

A thin, **deterministic, model-free** service — same discipline as `savings_harness score`.
Shipped as [`scripts/billing_aggregator.py`](scripts/billing_aggregator.py) (stdlib-only, fail-open,
`selftest` proves the arithmetic with zero files):

```
scripts/billing_aggregator.py
  collect   read .simplicio/orchestrator/{savings/snapshots.jsonl, trajectory/*, tee/video/ledger.txt}
            → ONE append-only, text-free usage record (counts the savings TEXT then DISCARDS it)
  meter     pure roll-up: usd_spent, tokens_spent, tokens_saved, items_delivered, renders, seconds
  invoice   apply the tier rule (seat | run | metered) → line-item JSON (+ optional --prepaid guard)
  export    emit Stripe-style metered usage records / CSV — usage counts only, never customer code
  rates     print the active rate card (DEFAULT_RATES, overridable via .simplicio/orchestrator/billing/rates.json)
  selftest  deterministic arithmetic proof — no files (11/11 checks)
```

```bash
python3 scripts/billing_aggregator.py collect --seats 3
python3 scripts/billing_aggregator.py invoice --tier metered --prepaid 100.00
python3 scripts/billing_aggregator.py selftest      # PASS (11/11)
```

Properties (non-negotiable, mirror the existing safety spine):
- **Deterministic & offline** — billing math never calls a model (reproducible from on-disk
  records, exactly like `savings_harness score`).
- **Privacy** — only usage *counts* leave the box (tokens, USD, item-ids, seconds); **never**
  customer code, diffs, prompts, or the captured screenshots/MP4s.
- **Fail-safe** — prepaid over-balance is flagged in billing output. No runtime halt is written.
- **Auditable** — every invoice line traces to an immutable snapshot record (the same audit
  property the loop requires of its `<promise>` evidence).

### 4. Suggested metered rates (placeholder — tune against real proxy data)

| Meter | Unit | Suggested |
|---|---|---|
| Managed run | per delivered+merged item | $0.50–$2.00 |
| Tokens (passthrough) | per 1M upstream tokens | cost + 15% |
| Distributed video render | per render-minute (Lambda) | $0.10 |
| Managed operator time | per compute-minute | $0.02 |

> Rates are illustrative. The capture proxy already records real per-provider token usage, so the
> first month of `proxy_savings.json` data should set these empirically before any public price.

---

## Open questions for the maintainer

1. **License:** keep pure MIT (open-core, charge for hosting) — recommended — or move to a
   dual-license for the operators? Open-core needs **no** license change; dual-license does.
2. **Billing rail:** Stripe metered billing is the lowest-lift target for the aggregator's
   `export`. Confirm before wiring.
3. **Where the control plane lives:** fully managed by us vs. a self-hosted control plane for
   Enterprise (changes the aggregator's deployment, not its logic).

*Done:* `scripts/billing_aggregator.py` (collect/meter/invoice/export/rates/selftest) is
implemented against the existing `.simplicio/orchestrator/` records, with a deterministic `selftest` like
`savings_harness`. *Next step if approved:* wire `export --format stripe` to a real Stripe metered
subscription, and set the rate card from the first month of `proxy_savings.json` data.
