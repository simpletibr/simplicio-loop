#!/usr/bin/env python3
"""simplicio-tasks — token-savings measurement harness (snapshot + offline scorer).

Validates the mandatory savings line with REAL numbers instead of hand-typed estimates.
Two phases, deliberately split so scoring never calls a model:

  snapshot  EXPENSIVE generator. Record, once, the raw baseline + treatment outputs for an
            item plus metadata (label, sample index, char counts, timestamp). Run it as often
            as you take samples; each call appends one immutable record.
  score     CHEAP offline scorer. Re-reads the snapshots with a FIXED tokenizer (no model
            call, fully deterministic) and reports saved tokens + pct, with per-item
            median / min / max / stdev across that item's samples, plus an overall roll-up.

The split is the point: the model is invoked only while producing outputs to snapshot; the
score is reproducible forever from the on-disk snapshot with zero further model spend.

Usage:
    # 1) snapshot a sample (repeat with --sample 1,2,... for stats)
    python3 scripts/savings_harness.py snapshot --item 15 --label "savings harness" \\
        --baseline baseline.txt --treatment treatment.txt [--sample 0] [--store DIR]
    #    (baseline/treatment may be a file path or "-" to read stdin)

    # 2) score everything snapshotted so far
    python3 scripts/savings_harness.py score [--store DIR] [--json]

    # self-check the math (no files needed)
    python3 scripts/savings_harness.py selftest

Tokenizer: reports TWO estimators side by side, labeled, rather than picking one winner (#92) —
`chars4`, the fixed cl100k-style `ceil(chars / 4)` baseline the orchestrator documents, always
runs; `bpe_estimate`, the sibling `engine/simplicio_tokens.py` heuristic (~3.2 chars/token on
dense JSON/code vs `chars4`'s flat 4.0), runs when that module is importable, else its report is
`null` and the CLI prints a note instead of silently omitting it. Both are deterministic and
model-free so two runs of `score` on one snapshot always agree — the split exists because the two
estimators disagree systematically on dense JSON, and `chars4` alone understates savings there.
The TOP-LEVEL `tokenizer`/`items`/`overall` keys stay `chars4` for backward compatibility; the new
`tokenizers` key carries both, explicitly labeled.
"""
import json
import math
import os
import statistics
import sys
import time

try:  # Windows consoles default to cp1252 and choke on non-ASCII — force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_STORE = os.path.join(REPO, ".simplicio-loop/orchestrator", "savings")
SNAPSHOTS = "snapshots.jsonl"

# Optional, more accurate token estimator (~3.2 chars/token on dense JSON vs chars4's flat 4.0).
# Fails open: engine/simplicio_tokens.py is a sibling module, not a hard dependency of this
# worker — an absent/broken import degrades to "bpe_estimate: null" in the report, never a crash.
_ENGINE_DIR = os.path.join(REPO, "engine")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)
try:
    from simplicio_tokens import count_tokens as _bpe_count_tokens  # noqa: E402
    _BPE_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when the sibling module is absent/broken
    _bpe_count_tokens = None
    _BPE_AVAILABLE = False


def log(msg):
    print("  " + msg)


def count_tokens(text):
    """Fixed, model-free tokenizer: ceil(chars / 4). Deterministic by design."""
    return math.ceil(len(text) / 4) if text else 0


def count_tokens_bpe(text):
    """The `engine/simplicio_tokens.py` heuristic estimator, when importable; 0 otherwise.

    Callers should check `_BPE_AVAILABLE` (or the `bpe_estimate` report being non-None) before
    trusting a 0 as a real measurement rather than "estimator absent"."""
    if not text or _bpe_count_tokens is None:
        return 0
    return int(_bpe_count_tokens(text))


def _read_source(spec):
    """A file path, or '-' for stdin."""
    if spec == "-":
        return sys.stdin.read()
    with open(spec, encoding="utf-8") as f:
        return f.read()


def _store_path(store):
    os.makedirs(store, exist_ok=True)
    return os.path.join(store, SNAPSHOTS)


def cmd_snapshot(opts):
    baseline = _read_source(opts["baseline"])
    treatment = _read_source(opts["treatment"])
    record = {
        "item": str(opts["item"]),
        "label": opts.get("label", ""),
        "sample": int(opts.get("sample", 0)),
        # store the raw bytes so the score is reproducible offline, forever
        "baseline_text": baseline,
        "treatment_text": treatment,
        "baseline_chars": len(baseline),
        "treatment_chars": len(treatment),
        "captured_at": opts.get("_now") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = _store_path(opts.get("store", DEFAULT_STORE))
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    log("snapshot item=%s sample=%s -> %s" % (record["item"], record["sample"], path))


def _load_snapshots(store):
    path = os.path.join(store, SNAPSHOTS)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                # one truncated/corrupt record must not lose the whole snapshot history
                log("! skipping unparseable snapshot line %d" % n)
    return rows


def _stats(values):
    """median / min / max / stdev over a list (population stdev; 0 for a single sample)."""
    if not values:
        return {"n": 0, "median": 0, "min": 0, "max": 0, "stdev": 0.0}
    return {
        "n": len(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "stdev": round(statistics.pstdev(values), 2) if len(values) > 1 else 0.0,
    }


def _score_with(rows, count_fn, tokenizer_label):
    """Pure function: snapshot rows + ONE tokenizer -> report dict for that tokenizer alone."""
    by_item = {}
    for r in rows:
        base = count_fn(r.get("baseline_text", ""))
        treat = count_fn(r.get("treatment_text", ""))
        saved = base - treat
        pct = round(100.0 * saved / base, 1) if base else 0.0
        s = by_item.setdefault(r["item"], {"label": r.get("label", ""), "samples": []})
        s["samples"].append({"baseline": base, "treatment": treat, "saved": saved, "pct": pct})

    items = []
    tot_base = tot_treat = 0
    for item, s in sorted(by_item.items(), key=lambda kv: kv[0]):
        saved_vals = [x["saved"] for x in s["samples"]]
        pct_vals = [x["pct"] for x in s["samples"]]
        # roll the per-item baseline/treatment up using each sample's median spend
        med_base = statistics.median([x["baseline"] for x in s["samples"]])
        med_treat = statistics.median([x["treatment"] for x in s["samples"]])
        tot_base += med_base
        tot_treat += med_treat
        items.append({
            "item": item,
            "label": s["label"],
            "saved": _stats(saved_vals),
            "pct": _stats(pct_vals),
            "median_baseline": med_base,
            "median_treatment": med_treat,
        })

    overall_saved = tot_base - tot_treat
    overall_pct = round(100.0 * overall_saved / tot_base, 1) if tot_base else 0.0
    return {
        "tokenizer": tokenizer_label,
        "items": items,
        "overall": {
            "baseline": tot_base, "treatment": tot_treat,
            "saved": overall_saved, "pct": overall_pct,
        },
    }


def score(rows):
    """Pure function: snapshot rows -> report dict. No I/O, so selftest can call it directly.

    Labeled dual-report (#92): scores with BOTH tokenizers so the two never get silently
    conflated. Top-level `tokenizer`/`items`/`overall` mirror the `chars4` estimator for backward
    compatibility with existing callers/docs; `tokenizers.chars4` and `tokenizers.bpe_estimate`
    carry both explicitly. `tokenizers.bpe_estimate` is `None` (not a crash, not a silent zero)
    when `engine/simplicio_tokens.py` isn't importable."""
    chars4 = _score_with(rows, count_tokens, "ceil(chars/4)")
    bpe = _score_with(rows, count_tokens_bpe, "simplicio_tokens (stdlib BPE heuristic)") \
        if _BPE_AVAILABLE else None
    report = dict(chars4)
    report["tokenizers"] = {"chars4": chars4, "bpe_estimate": bpe}
    return report


def _print_report(report):
    if not report["items"]:
        log("no snapshots found — run `snapshot` first")
        return
    print("item   median-saved   pct(med/min/max/stdev)   samples   label")
    print("-" * 78)
    for it in report["items"]:
        p = it["pct"]
        # floats throughout (median of an even sample count is fractional) — match --json/selftest
        print("%-5s  %12.1f   %5.1f / %4.1f / %4.1f / %4.1f   %7d   %s" % (
            it["item"], it["saved"]["median"],
            p["median"], p["min"], p["max"], p["stdev"],
            it["saved"]["n"], it["label"]))
    o = report["overall"]
    print("-" * 78)
    print("OVERALL  baseline=%.1f  treatment=%.1f  saved=%.1f  (%.1f%%)  [tokenizer=%s]" % (
        o["baseline"], o["treatment"], o["saved"], o["pct"], report["tokenizer"]))
    bpe = report.get("tokenizers", {}).get("bpe_estimate")
    if bpe:
        bo = bpe["overall"]
        print("OVERALL  baseline=%.1f  treatment=%.1f  saved=%.1f  (%.1f%%)  [tokenizer=%s]" % (
            bo["baseline"], bo["treatment"], bo["saved"], bo["pct"], bpe["tokenizer"]))
    else:
        log("bpe_estimate: unavailable (engine/simplicio_tokens.py not importable) — chars4 only")


def cmd_score(opts):
    rows = _load_snapshots(opts.get("store", DEFAULT_STORE))
    report = score(rows)
    if opts.get("json"):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)


def cmd_selftest(opts):
    # two items; item 7 has two samples so stdev/median exercise the multi-sample path
    rows = [
        {"item": "7", "label": "a", "baseline_text": "x" * 400, "treatment_text": "x" * 100},
        {"item": "7", "label": "a", "baseline_text": "x" * 400, "treatment_text": "x" * 200},
        {"item": "9", "label": "b", "baseline_text": "x" * 800, "treatment_text": "x" * 400},
    ]
    r = score(rows)
    # item 7: baseline 100 tok; treatment 25 & 50 -> saved 75 & 50 -> median 62.5; pct 75 & 50
    it7 = next(i for i in r["items"] if i["item"] == "7")
    assert it7["saved"]["median"] == 62.5, it7["saved"]
    assert it7["saved"]["min"] == 50 and it7["saved"]["max"] == 75, it7["saved"]
    assert it7["pct"]["median"] == 62.5, it7["pct"]
    # item 9: baseline 200 tok, treatment 100 -> saved 100, pct 50, stdev 0 (single sample)
    it9 = next(i for i in r["items"] if i["item"] == "9")
    assert it9["saved"]["median"] == 100 and it9["pct"]["stdev"] == 0.0, it9
    # overall: median baselines 100+200=300; median treatments 37.5+100=137.5; saved 162.5
    assert r["overall"]["baseline"] == 300 and r["overall"]["treatment"] == 137.5, r["overall"]
    assert r["overall"]["saved"] == 162.5, r["overall"]
    assert count_tokens("") == 0 and count_tokens("abcd") == 1 and count_tokens("abcde") == 2

    # labeled dual-report (#92): tokenizers.chars4 mirrors the top-level (back-compat) report
    assert r["tokenizers"]["chars4"] == {
        "tokenizer": r["tokenizer"], "items": r["items"], "overall": r["overall"],
    }, r["tokenizers"]["chars4"]
    # bpe_estimate is either a real report (engine/simplicio_tokens.py importable) or an honest
    # None — never a silent 0 masquerading as a measurement
    bpe = r["tokenizers"]["bpe_estimate"]
    if _BPE_AVAILABLE:
        assert bpe is not None and bpe["tokenizer"] != r["tokenizer"], bpe
        assert bpe["overall"]["baseline"] > 0, bpe["overall"]
        assert count_tokens_bpe("") == 0
        assert count_tokens_bpe("x" * 400) > 0
    else:
        assert bpe is None, bpe
    log("selftest OK — tokenizer + per-item stats + overall roll-up + labeled dual-report verified")


def _parse(args):
    """Tiny --flag value parser (matches the dependency-free style of install_lib.py)."""
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
    # --describe-cli: emit JSON spec of accepted verbs + flags
    if argv[0] == "--describe-cli":
        import json
        print(json.dumps({
            "verbs": ["snapshot", "score", "selftest"],
            "flags": ["--item", "--label", "--baseline", "--treatment", "--sample",
                      "--store", "--json", "--help"],
        }))
        sys.exit(0)
    sub, rest = argv[0], argv[1:]
    opts = _parse(rest)
    if sub == "snapshot":
        missing = [k for k in ("item", "baseline", "treatment") if k not in opts]
        if missing:
            print("snapshot requires: %s" % ", ".join("--" + m for m in missing))
            sys.exit(2)
        cmd_snapshot(opts)
    elif sub == "score":
        cmd_score(opts)
    elif sub == "selftest":
        cmd_selftest(opts)
    else:
        print("unknown command '%s'. choices: snapshot score selftest" % sub)
        sys.exit(2)


if __name__ == "__main__":
    main()
