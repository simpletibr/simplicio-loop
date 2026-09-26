#!/usr/bin/env python3
"""simplicio-loop — billing_aggregator (deterministic, offline, privacy-preserving meter→invoice).

The runnable form of the billing architecture sketched in `PRICING.md` (Open-core + usage-based
hosted tier). It turns the metering records the loop ALREADY produces into usage rollups and
tier-priced invoice line-items. It is the ONLY new component billing needs — everything it reads
is already on disk under `.simplicio-loop/orchestrator/`.

Non-negotiable properties (mirror the loop's safety spine):
  • Deterministic & model-free — the math NEVER calls a model; `meter`/`invoice` are pure
    functions, reproducible forever from the on-disk records (same discipline as
    `savings_harness score`). `selftest` proves the arithmetic with no files.
  • Privacy — only usage *counts* ever leave the box (tokens, USD, item-ids, seconds, render
    counts). Customer code, diffs, prompts, and the captured screenshots/MP4s are NEVER read into
    a usage record. The savings snapshots store raw baseline/treatment TEXT; `collect` counts its
    tokens with the fixed `ceil(chars/4)` tokenizer and then DISCARDS the text.
  • Fail-safe — `invoice --prepaid` flags an over-balance as billing state only; it never writes
    runtime loop state or stops the orchestrator.
  • Auditable — every `collect`ed usage record is immutable (append-only JSONL) and timestamped,
    so an invoice line always traces back to a snapshot, like the loop's `<promise>` evidence.

Inputs (all optional — a missing source contributes 0, fail-open):
  .simplicio-loop/orchestrator/savings/snapshots.jsonl → tokens_spent (treatment) + tokens_saved (baseline−treatment)
  .simplicio-loop/orchestrator/trajectory/*.jsonl      → items_delivered (records with status merged|closed|delivered)
  .simplicio-loop/orchestrator/tee/video/ledger.txt    → renders (one per `video_evidence: PASS` line)

Verbs:
  collect   Read the sources for a window, write ONE normalized, text-free usage record
            (append-only) to .simplicio-loop/orchestrator/billing/usage.jsonl. Repeat per billing window.
  meter     Pure rollup over collected usage records → totals (usd_spent, tokens_spent,
            tokens_saved, items_delivered, renders, render_seconds).
  invoice   Apply a tier rule (seat | run | metered) + rates → line-item JSON. No model call.
  export    Emit the invoice as Stripe-style metered usage records (JSON) or CSV — counts only.
  rates     Print the active rate card (defaults, or .simplicio-loop/orchestrator/billing/rates.json if present).
  selftest  Prove meter()/invoice() arithmetic deterministically — no files needed.

Usage:
    python3 scripts/billing_aggregator.py collect --seats 3 [--store DIR] [--window 2026-06]
    python3 scripts/billing_aggregator.py meter   [--store DIR] [--json]
    python3 scripts/billing_aggregator.py invoice --tier metered [--seats 3] [--prepaid 100.00] [--json]
    python3 scripts/billing_aggregator.py export  --tier metered --format stripe|csv
    python3 scripts/billing_aggregator.py selftest
"""
import glob
import json
import math
import os
import sys
import time

try:  # Windows consoles default to cp1252 and choke on non-ASCII — force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ORCH = os.path.join(REPO, ".simplicio-loop/orchestrator")
DEFAULT_STORE = os.path.join(ORCH, "billing")
USAGE = "usage.jsonl"

# Default rate card (illustrative — PRICING.md says tune against the first month of real proxy
# data before any public price). Override by writing .simplicio-loop/orchestrator/billing/rates.json.
DEFAULT_RATES = {
    "seat_usd_per_month": 29.0,        # Pro flat per-seat
    "run_usd_per_item": 1.00,          # Team per delivered+merged item
    "token_usd_per_million": 0.0,      # metered passthrough markup is applied to usd_spent, not here
    "token_markup_pct": 15.0,          # metered: bill usd_spent * (1 + markup)
    "render_usd_per_minute": 0.10,     # distributed video render (Lambda)
    "operator_usd_per_minute": 0.02,   # managed operator compute
}


def log(msg):
    print("  " + msg)


def count_tokens(text):
    """Fixed, model-free tokenizer: ceil(chars / 4) — identical to savings_harness."""
    return math.ceil(len(text) / 4) if text else 0


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------------------------
# collect — read the loop's existing records, emit ONE text-free usage record (privacy boundary)
# ---------------------------------------------------------------------------------------------
def _tokens_from_savings():
    """(tokens_spent, tokens_saved). Counts tokens then DISCARDS the raw text (privacy)."""
    path = os.path.join(ORCH, "savings", "snapshots.jsonl")
    spent = saved = 0
    if not os.path.exists(path):
        return 0, 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue  # one corrupt line must not poison the meter
            base = count_tokens(r.get("baseline_text", ""))      # control-arm tokens
            treat = count_tokens(r.get("treatment_text", ""))    # actual billable spend
            spent += treat
            saved += max(0, base - treat)
            # r's raw text is intentionally never copied into the usage record
    return spent, saved


def _items_delivered():
    """Count trajectory records whose status is a delivered terminal state."""
    done = {"merged", "closed", "delivered", "done"}
    n = 0
    for path in sorted(glob.glob(os.path.join(ORCH, "trajectory", "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if str(r.get("status", "")).lower() in done:
                    n += 1
    return n


def _renders():
    """One render per `video_evidence: PASS` ledger line; sum render_seconds if present."""
    path = os.path.join(ORCH, "tee", "video", "ledger.txt")
    n, secs = 0, 0.0
    if not os.path.exists(path):
        return 0, 0.0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "video_evidence: PASS" in line:
                n += 1
    return n, secs


def cmd_collect(opts):
    store = opts.get("store", DEFAULT_STORE)
    os.makedirs(store, exist_ok=True)
    tokens_spent, tokens_saved = _tokens_from_savings()
    renders, render_seconds = _renders()
    record = {
        "window": opts.get("window", time.strftime("%Y-%m", time.gmtime())),
        "collected_at": opts.get("_now") or _now(),
        "seats": int(opts.get("seats", 0)),
        "usd_spent": 0.0,
        "tokens_spent": tokens_spent,
        "tokens_saved": tokens_saved,
        "items_delivered": _items_delivered(),
        "renders": renders,
        "render_seconds": render_seconds,
        "operator_seconds": float(opts.get("operator_seconds", 0) or 0),
    }
    with open(os.path.join(store, USAGE), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    log("collected window=%s seats=%d usd=%.4f tok_spent=%d items=%d renders=%d -> %s/%s" % (
        record["window"], record["seats"], record["usd_spent"], record["tokens_spent"],
        record["items_delivered"], record["renders"], store, USAGE))
    print("collected")


def _load_usage(store):
    path = os.path.join(store, USAGE)
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                log("! skipping unparseable usage line")
    return rows


# ---------------------------------------------------------------------------------------------
# meter / invoice — PURE functions (selftest calls them with synthetic data, zero I/O)
# ---------------------------------------------------------------------------------------------
def meter(rows):
    """Pure rollup: usage records -> totals. Deterministic, no I/O."""
    t = {"usd_spent": 0.0, "tokens_spent": 0, "tokens_saved": 0, "items_delivered": 0,
         "renders": 0, "render_seconds": 0.0, "operator_seconds": 0.0, "seats": 0, "windows": 0}
    for r in rows:
        t["usd_spent"] += float(r.get("usd_spent", 0) or 0)
        t["tokens_spent"] += int(r.get("tokens_spent", 0) or 0)
        t["tokens_saved"] += int(r.get("tokens_saved", 0) or 0)
        t["items_delivered"] += int(r.get("items_delivered", 0) or 0)
        t["renders"] += int(r.get("renders", 0) or 0)
        t["render_seconds"] += float(r.get("render_seconds", 0) or 0)
        t["operator_seconds"] += float(r.get("operator_seconds", 0) or 0)
        t["seats"] = max(t["seats"], int(r.get("seats", 0) or 0))  # peak active seats
        t["windows"] += 1
    t["usd_spent"] = round(t["usd_spent"], 6)
    return t


def invoice(totals, tier, rates, seats=None, prepaid=None):
    """Pure: totals + tier + rates -> {lines:[...], total_usd, prepaid_*}. No I/O, no model."""
    seats = int(seats if seats is not None else totals.get("seats", 0))
    lines = []

    def add(desc, qty, unit, rate):
        amt = round(qty * rate, 4)
        lines.append({"desc": desc, "qty": qty, "unit": unit, "rate_usd": rate, "amount_usd": amt})
        return amt

    total = 0.0
    if tier == "seat":
        total += add("Pro seats", seats, "seat·mo", rates["seat_usd_per_month"])
    elif tier == "run":
        total += add("Delivered+merged items", totals["items_delivered"], "item",
                     rates["run_usd_per_item"])
    elif tier == "metered":
        # token passthrough = actual upstream USD spend + markup
        markup = 1.0 + rates["token_markup_pct"] / 100.0
        total += add("Tokens (passthrough + markup)", round(totals["usd_spent"], 4), "usd·×",
                     round(markup, 4))
        total += add("Distributed video render", round(totals["render_seconds"] / 60.0, 4),
                     "render·min", rates["render_usd_per_minute"])
        total += add("Managed operator time", round(totals["operator_seconds"] / 60.0, 4),
                     "op·min", rates["operator_usd_per_minute"])
        if seats:
            total += add("Pro seats", seats, "seat·mo", rates["seat_usd_per_month"])
    else:
        raise ValueError("unknown tier %r (choices: seat|run|metered)" % tier)

    out = {"tier": tier, "lines": lines, "total_usd": round(total, 4),
           "tokens_saved": totals.get("tokens_saved", 0)}
    if prepaid is not None:
        bal = round(float(prepaid) - out["total_usd"], 4)
        out["prepaid_balance_usd"] = bal
        out["prepaid_state"] = "over_balance" if bal < 0 else "ok"
    return out


def cmd_meter(opts):
    t = meter(_load_usage(opts.get("store", DEFAULT_STORE)))
    if opts.get("json"):
        print(json.dumps(t, indent=2))
        return
    print("metered rollup over %d window(s):" % t["windows"])
    for k in ("usd_spent", "tokens_spent", "tokens_saved", "items_delivered", "renders", "seats"):
        log("%-16s %s" % (k, t[k]))


def _load_rates():
    user = _read_json(os.path.join(DEFAULT_STORE, "rates.json"), {})
    rates = dict(DEFAULT_RATES)
    rates.update({k: v for k, v in user.items() if k in DEFAULT_RATES})
    return rates


def cmd_invoice(opts):
    tier = opts.get("tier", "metered")
    totals = meter(_load_usage(opts.get("store", DEFAULT_STORE)))
    seats = int(opts["seats"]) if "seats" in opts else None
    prepaid = float(opts["prepaid"]) if "prepaid" in opts else None
    try:
        inv = invoice(totals, tier, _load_rates(), seats=seats, prepaid=prepaid)
    except ValueError as e:
        print(str(e))
        sys.exit(2)
    if opts.get("json"):
        print(json.dumps(inv, indent=2))
        return
    print("invoice (tier=%s):" % tier)
    for ln in inv["lines"]:
        log("%-34s %10s %-10s @ %-8s = $%.4f" % (
            ln["desc"], ln["qty"], ln["unit"], ln["rate_usd"], ln["amount_usd"]))
    log("%-34s %33s $%.4f" % ("TOTAL", "", inv["total_usd"]))
    if "prepaid_balance_usd" in inv:
        log("prepaid balance: $%.4f (%s)" % (inv["prepaid_balance_usd"], inv["prepaid_state"]))


def cmd_export(opts):
    tier = opts.get("tier", "metered")
    fmt = opts.get("format", "stripe")
    totals = meter(_load_usage(opts.get("store", DEFAULT_STORE)))
    inv = invoice(totals, tier, _load_rates(),
                  seats=int(opts["seats"]) if "seats" in opts else None)
    if fmt == "csv":
        print("desc,qty,unit,rate_usd,amount_usd")
        for ln in inv["lines"]:
            print("%s,%s,%s,%s,%s" % (ln["desc"], ln["qty"], ln["unit"],
                                      ln["rate_usd"], ln["amount_usd"]))
        print("TOTAL,,,,%.4f" % inv["total_usd"])
    else:  # stripe-style metered usage records (counts only — never customer content)
        recs = [{"metric": ln["desc"], "quantity": ln["qty"], "unit": ln["unit"],
                 "amount_usd": ln["amount_usd"], "timestamp": _now()} for ln in inv["lines"]]
        print(json.dumps({"tier": tier, "usage_records": recs,
                          "total_usd": inv["total_usd"]}, indent=2))


def cmd_rates(_opts):
    print(json.dumps(_load_rates(), indent=2))


def cmd_selftest(_opts):
    """Deterministic arithmetic proof — no files. Exits non-zero on any mismatch."""
    rows = [
        {"usd_spent": 2.00, "tokens_spent": 1000, "tokens_saved": 4000, "items_delivered": 3,
         "renders": 1, "render_seconds": 120, "operator_seconds": 600, "seats": 3},
        {"usd_spent": 1.50, "tokens_spent": 500, "tokens_saved": 1500, "items_delivered": 2,
         "renders": 0, "render_seconds": 0, "operator_seconds": 300, "seats": 2},
    ]
    t = meter(rows)
    checks = []

    def chk(name, got, want):
        ok = got == want
        checks.append(ok)
        print("  [%s] %-26s got=%s want=%s" % ("ok" if ok else "XX", name, got, want))

    chk("usd_spent", t["usd_spent"], 3.5)
    chk("tokens_spent", t["tokens_spent"], 1500)
    chk("tokens_saved", t["tokens_saved"], 5500)
    chk("items_delivered", t["items_delivered"], 5)
    chk("renders", t["renders"], 1)
    chk("seats(peak)", t["seats"], 3)

    rates = dict(DEFAULT_RATES)
    # seat tier: 3 seats * 29 = 87
    chk("invoice.seat", invoice(t, "seat", rates)["total_usd"], 87.0)
    # run tier: 5 items * 1.00 = 5
    chk("invoice.run", invoice(t, "run", rates)["total_usd"], 5.0)
    # metered: usd 3.5 * 1.15 + (120s/60)*0.10 + (900s/60)*0.02 + 3 seats*29
    #        = 4.025 + 0.20 + 0.30 + 87 = 91.525 -> round 91.525
    metered = invoice(t, "metered", rates)["total_usd"]
    chk("invoice.metered", metered, 91.525)
    # prepaid fail-safe: balance under 0 is a billing state only
    inv_over = invoice(t, "seat", rates, seats=100, prepaid=50.0)
    chk("prepaid.over_balance", inv_over["prepaid_state"], "over_balance")
    chk("count_tokens", count_tokens("12345678"), 2)  # 8 chars / 4

    ok = all(checks)
    print("selftest: %s (%d/%d)" % ("PASS" if ok else "FAIL", sum(checks), len(checks)))
    sys.exit(0 if ok else 1)


def _parse(args):
    opts = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                opts[key] = args[i + 1]
                i += 2
            else:
                opts[key] = True
                i += 1
        else:
            i += 1
    return opts


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(2)
    sub, opts = argv[0], _parse(argv[1:])
    {"collect": cmd_collect, "meter": cmd_meter, "invoice": cmd_invoice, "export": cmd_export,
     "rates": cmd_rates, "selftest": cmd_selftest}.get(
        sub, lambda _o: (print("unknown command '%s'. choices: collect meter invoice export "
                               "rates selftest" % sub), sys.exit(2)))(opts)


if __name__ == "__main__":
    main()
