#!/usr/bin/env python3
"""simplicio-report — savings reporting for the proxy savings ledger.

Reads ~/.simplicio-loop/proxy_savings.json (schema v3) and prints a clean
report of lifetime + per-session savings plus per-model / per-provider
breakdowns derived from the cumulative history.

Stdlib only. No network.

Usage:
    python3 simplicio_report.py [summary]
    python3 simplicio_report.py --json
    python3 simplicio_report.py --since 120
    python3 simplicio_report.py --top 5
"""

import argparse
import calendar
import datetime
import json
import os
import sys


def home_dir():
    """Resolve the simplicio home, honoring SIMPLICIO_HOME."""
    override = os.environ.get("SIMPLICIO_HOME")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".simplicio-loop")


def savings_path():
    return os.path.join(home_dir(), "proxy_savings.json")


def load_data(path):
    """Load the savings JSON. Returns None if absent/empty/unparseable."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def parse_iso_utc(ts):
    """Parse an ISO-8601 'Z' timestamp into a UTC epoch (float).

    Returns None if it can't be parsed.
    """
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    # Normalize trailing Z / offset to a naive UTC datetime.
    if s.endswith("Z"):
        s = s[:-1]
    # Drop fractional seconds if present (calendar.timegm needs a struct).
    fmt_candidates = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f")
    dt = None
    for fmt in fmt_candidates:
        try:
            dt = datetime.datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    return calendar.timegm(dt.timetuple()) + dt.microsecond / 1e6


def now_utc_epoch():
    # timezone-aware UTC; avoids the deprecated utcnow() on Python 3.12+.
    return calendar.timegm(datetime.datetime.now(datetime.timezone.utc).timetuple())


def filter_since(history, since_minutes):
    """Keep only history entries within the last N minutes (UTC)."""
    if since_minutes is None:
        return history
    cutoff = now_utc_epoch() - (since_minutes * 60.0)
    out = []
    for entry in history:
        epoch = parse_iso_utc(entry.get("timestamp"))
        if epoch is None:
            continue
        if epoch >= cutoff:
            out.append(entry)
    return out


def _num(value):
    """Coerce to float, defaulting to 0.0 on garbage."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compute_deltas(history):
    """Derive per-entry deltas from cumulative history.

    delta_saved[i]  = saved[i]  - saved[i-1]   (clamped >= 0)
    delta_input[i]  = input[i]  - input[i-1]   (clamped >= 0)
    delta_usd[i]    = usd[i]    - usd[i-1]     (clamped >= 0)

    The first entry's delta is its own cumulative value (treated as the
    baseline from zero), clamped non-negative.

    Returns a list of dicts: timestamp, provider, model,
    delta_saved, delta_input, delta_usd.
    """
    deltas = []
    prev_saved = 0.0
    prev_input = 0.0
    prev_usd = 0.0
    for entry in history:
        cur_saved = _num(entry.get("total_tokens_saved"))
        cur_input = _num(entry.get("total_input_tokens"))
        cur_usd = _num(entry.get("compression_savings_usd"))

        d_saved = cur_saved - prev_saved
        d_input = cur_input - prev_input
        d_usd = cur_usd - prev_usd

        # Clamp non-monotonic / reset quirks to 0.
        if d_saved < 0:
            d_saved = 0.0
        if d_input < 0:
            d_input = 0.0
        if d_usd < 0:
            d_usd = 0.0

        deltas.append({
            "timestamp": entry.get("timestamp"),
            "provider": entry.get("provider") or "unknown",
            "model": entry.get("model") or "unknown",
            "delta_saved": d_saved,
            "delta_input": d_input,
            "delta_usd": d_usd,
        })

        prev_saved = cur_saved
        prev_input = cur_input
        prev_usd = cur_usd
    return deltas


def group_by(deltas, key):
    """Group deltas by 'model' or 'provider' and sum the components.

    Returns a dict: name -> {tokens_saved, input_tokens, usd, requests}.
    """
    out = {}
    for d in deltas:
        name = d.get(key) or "unknown"
        bucket = out.setdefault(name, {
            "tokens_saved": 0.0,
            "input_tokens": 0.0,
            "usd": 0.0,
            "requests": 0,
        })
        bucket["tokens_saved"] += d["delta_saved"]
        bucket["input_tokens"] += d["delta_input"]
        bucket["usd"] += d["delta_usd"]
        bucket["requests"] += 1
    return out


def sorted_breakdown(grouped, top=None):
    """Return a list of (name, stats) sorted by tokens_saved desc."""
    items = sorted(
        grouped.items(),
        key=lambda kv: kv[1]["tokens_saved"],
        reverse=True,
    )
    if top is not None and top >= 0:
        items = items[:top]
    return items


def savings_percent(tokens_saved, input_tokens):
    """Savings % = saved / (saved + input baseline). Defensive on /0."""
    denom = tokens_saved + input_tokens
    if denom <= 0:
        return 0.0
    return (tokens_saved / denom) * 100.0


def build_report(data, since_minutes=None, top=None):
    """Assemble a structured report dict from the loaded data."""
    history = data.get("history") or []
    if not isinstance(history, list):
        history = []

    scoped = filter_since(history, since_minutes)
    deltas = compute_deltas(scoped)

    by_model = group_by(deltas, "model")
    by_provider = group_by(deltas, "provider")

    lifetime = data.get("lifetime") or {}
    session = data.get("display_session") or {}

    life_saved = _num(lifetime.get("tokens_saved"))
    life_input = _num(lifetime.get("total_input_tokens"))
    life_usd = _num(lifetime.get("compression_savings_usd"))
    life_requests = int(_num(lifetime.get("requests")))

    # When --since is in play the lifetime block is misleading, so we also
    # expose the windowed totals from the deltas themselves.
    window_saved = sum(d["delta_saved"] for d in deltas)
    window_input = sum(d["delta_input"] for d in deltas)
    window_usd = sum(d["delta_usd"] for d in deltas)

    report = {
        "lifetime": {
            "tokens_saved": life_saved,
            "input_tokens": life_input,
            "savings_usd": life_usd,
            "requests": life_requests,
            "savings_percent": round(savings_percent(life_saved, life_input), 2),
        },
        "session": {
            "tokens_saved": _num(session.get("tokens_saved")),
            "input_tokens": _num(session.get("total_input_tokens")),
            "savings_usd": _num(session.get("compression_savings_usd")),
            "requests": int(_num(session.get("requests"))),
            "savings_percent": round(_num(session.get("savings_percent")), 2),
        },
        "window": {
            "since_minutes": since_minutes,
            "entries": len(deltas),
            "tokens_saved": window_saved,
            "input_tokens": window_input,
            "savings_usd": window_usd,
            "savings_percent": round(savings_percent(window_saved, window_input), 2),
        },
        "by_model": [
            {
                "model": name,
                "tokens_saved": stats["tokens_saved"],
                "input_tokens": stats["input_tokens"],
                "savings_usd": stats["usd"],
                "requests": stats["requests"],
                "savings_percent": round(
                    savings_percent(stats["tokens_saved"], stats["input_tokens"]), 2
                ),
            }
            for name, stats in sorted_breakdown(by_model, top=top)
        ],
        "by_provider": [
            {
                "provider": name,
                "tokens_saved": stats["tokens_saved"],
                "input_tokens": stats["input_tokens"],
                "savings_usd": stats["usd"],
                "requests": stats["requests"],
                "savings_percent": round(
                    savings_percent(stats["tokens_saved"], stats["input_tokens"]), 2
                ),
            }
            for name, stats in sorted_breakdown(by_provider, top=None)
        ],
    }
    return report


def _fmt_int(n):
    return "{:,}".format(int(round(n)))


def _fmt_usd(n):
    return "${:,.6f}".format(n)


def _fmt_pct(n):
    return "{:.2f}%".format(n)


def render_text(report):
    """Render the report dict as a clean text block."""
    lines = []
    life = report["lifetime"]
    sess = report["session"]
    win = report["window"]

    lines.append("Simplicio Savings Report")
    lines.append("=" * 40)
    lines.append("")
    lines.append("Lifetime")
    lines.append("  tokens saved : {}".format(_fmt_int(life["tokens_saved"])))
    lines.append("  $ saved      : {}".format(_fmt_usd(life["savings_usd"])))
    lines.append("  requests     : {}".format(_fmt_int(life["requests"])))
    lines.append("  savings %    : {}".format(_fmt_pct(life["savings_percent"])))
    lines.append("")
    lines.append("Current session")
    lines.append("  tokens saved : {}".format(_fmt_int(sess["tokens_saved"])))
    lines.append("  $ saved      : {}".format(_fmt_usd(sess["savings_usd"])))
    lines.append("  requests     : {}".format(_fmt_int(sess["requests"])))
    lines.append("  savings %    : {}".format(_fmt_pct(sess["savings_percent"])))

    if win["since_minutes"] is not None:
        lines.append("")
        lines.append("Window (last {} min)".format(win["since_minutes"]))
        lines.append("  entries      : {}".format(_fmt_int(win["entries"])))
        lines.append("  tokens saved : {}".format(_fmt_int(win["tokens_saved"])))
        lines.append("  $ saved      : {}".format(_fmt_usd(win["savings_usd"])))
        lines.append("  savings %    : {}".format(_fmt_pct(win["savings_percent"])))

    lines.append("")
    lines.append("By model")
    if report["by_model"]:
        for row in report["by_model"]:
            lines.append(
                "  {model:<24} {saved:>14} tok  {usd:>14}  {pct:>8}  ({req} req)".format(
                    model=str(row["model"])[:24],
                    saved=_fmt_int(row["tokens_saved"]),
                    usd=_fmt_usd(row["savings_usd"]),
                    pct=_fmt_pct(row["savings_percent"]),
                    req=row["requests"],
                )
            )
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("By provider")
    if report["by_provider"]:
        for row in report["by_provider"]:
            lines.append(
                "  {prov:<24} {saved:>14} tok  {usd:>14}  {pct:>8}  ({req} req)".format(
                    prov=str(row["provider"])[:24],
                    saved=_fmt_int(row["tokens_saved"]),
                    usd=_fmt_usd(row["savings_usd"]),
                    pct=_fmt_pct(row["savings_percent"]),
                    req=row["requests"],
                )
            )
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="simplicio_report",
        description="Report token/$ savings from the simplicio-cli proxy ledger.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="summary",
        choices=["summary"],
        help="report command (default: summary).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON.",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=None,
        metavar="MINUTES",
        help="restrict history to the last N minutes (UTC).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="show only the top N models by tokens saved.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    path = savings_path()
    data = load_data(path)

    if data is None:
        if args.json:
            print(json.dumps({"status": "empty", "message": "no savings recorded yet"}))
        else:
            print("no savings recorded yet")
        return 0

    report = build_report(data, since_minutes=args.since, top=args.top)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
