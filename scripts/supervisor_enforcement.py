#!/usr/bin/env python3
"""simplicio-loop — supervisor enforcement opt-in, observability, and rollout (#516).

Depends conceptually on `simplicio_loop/process_supervisor.py` (#514), which defines the safe
`ProcessSpec`/`ProcessLease`/`ProcessResult` contract for supervised child processes. This worker
adds the missing enforcement layer ON TOP of that contract: a durable, deterministic, opt-in
switch that decides whether "a process looks like it should be supervised but isn't" is merely
REPORTED (default) or ever acted on (never, in this slice — enforcement here is diagnostic-only).

Enforcement is OFF by default and stays OFF until an operator explicitly opts in with
`--i-understand` on `enable`. This worker never scans the live OS process table itself — `detect`
takes a JSON process-list on stdin so behavior is deterministic and testable, matching this repo's
"never fake evidence" discipline (see scripts/check.py).

State: .simplicio-loop/orchestrator/supervisor_enforcement.json (override with $SIMPLICIO_SUPERVISOR_STATE_FILE):
    {"schema": "simplicio.supervisor-enforcement/v1", "enabled": bool, "rollout": {"mode": str,
     "canary_percent": int, "canary_allowlist": [str]}, "updated_at": float}

Verbs:
  status   Print (and --json emit) whether enforcement is enabled and the current rollout mode.
           Also folds in the Hub's ResourceGovernor circuit breaker (#506) when a governor status
           snapshot is available (--governor-state-file FILE, or $SIMPLICIO_GOVERNOR_STATE_FILE):
           a real integration surfacing "breaker open" (sustained resource pressure) as a fact
           about enforcement's environment, never a second/duplicate breaker of its own.
  detect   Read a JSON list of process command-lines from stdin (or --input FILE) and flag which
           ones look like Simplicio-ecosystem processes (argv[0] matches a known operator binary
           pattern) that carry no supervision marker (env var SIMPLICIO_SUPERVISED=1 or a
           --supervised-by/-tagged argv token, or an explicit marker_file that exists). Diagnostic
           only: this verb NEVER kills, signals, or otherwise touches a real process. With
           --scan-os it additionally enumerates the REAL OS process table via `psutil.process_iter`
           (opt-in, off by default) instead of reading stdin; a documented graceful skip (exit 3)
           when psutil is not installed — never a silent empty result mistaken for "all clear".
  enable   Flip enforcement on. Requires --i-understand (or SIMPLICIO_SUPERVISOR_I_UNDERSTAND=1) —
           refuses to silently default to on.
  disable  Flip enforcement off. Always allowed, no guard needed (turning safety back on is safe).
  rollout  Set the rollout mode: shadow (observe + report only, never deny admission — the only
           mode meaningful while enabled=false too), canary (enforce for --percent of workspaces or
           workspaces in --allow NAME, repeatable), or full. Rejects any other mode string. Every
           accepted transition appends one structured event to
           .simplicio-loop/orchestrator/supervisor_enforcement_events.jsonl (schema
           simplicio.supervisor-enforcement-event/v1, via this repo's `_locked_append` convention —
           the same cross-process-safe JSONL append `loop_progress.py`/`loop_journal.py` use) so
           canary/shadow/full transitions are observable after the fact.
  selftest Prove default-off, guarded enable, detect flagging, and rollout validation
           deterministically — no real process interaction, an isolated temp state file.
  metrics  Rollout metrics dashboard: replays the JSONL event log (--events-file, default
           .simplicio-loop/orchestrator/supervisor_enforcement_events.jsonl) and reports transition counts
           per mode, the current mode/state, and the most recent transition. Never fabricates
           a number — an absent/empty event log reports zero transitions honestly instead of
           guessing at history.

Usage:
    python3 scripts/supervisor_enforcement.py status
    python3 scripts/supervisor_enforcement.py status --governor-state-file governor.json
    echo '["mapper --survey", "python3 unrelated.py"]' | \\
        python3 scripts/supervisor_enforcement.py detect
    python3 scripts/supervisor_enforcement.py detect --scan-os
    python3 scripts/supervisor_enforcement.py enable --i-understand
    python3 scripts/supervisor_enforcement.py rollout --mode canary --percent 10
    python3 scripts/supervisor_enforcement.py disable
    python3 scripts/supervisor_enforcement.py metrics --json
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _locked_append import locked_append_line  # noqa: E402

SCHEMA = "simplicio.supervisor-enforcement/v1"
DEFAULT_STATE_FILE = ".simplicio-loop/orchestrator/supervisor_enforcement.json"
DEFAULT_EVENTS_FILE = ".simplicio-loop/orchestrator/supervisor_enforcement_events.jsonl"
ROLLOUT_MODES = ("shadow", "canary", "full")
SIMPLICIO_BINARY_PATTERNS = (
    "simplicio-mapper",
    "simplicio-dev-cli",
    "simplicio-cli",
    "simplicio-runtime",
    "mapper",
    "dev-cli",
)


def _state_file():
    return os.environ.get("SIMPLICIO_SUPERVISOR_STATE_FILE", DEFAULT_STATE_FILE)


def _events_file():
    return os.environ.get("SIMPLICIO_SUPERVISOR_EVENTS_FILE", DEFAULT_EVENTS_FILE)


def emit_rollout_event(mode, percent, allow, path=None):
    rec = {
        "schema": "simplicio.supervisor-enforcement-event/v1",
        "ts": time.time(),
        "event": "rollout_change",
        "mode": mode,
        "canary_percent": int(percent or 0),
        "canary_allowlist": list(allow or []),
    }
    events_path = path or _events_file()
    parent = os.path.dirname(events_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    locked_append_line(events_path, json.dumps(rec, sort_keys=True))
    return rec


def governor_circuit_open(governor_status):
    if not isinstance(governor_status, dict):
        return False
    circuit = governor_status.get("circuit")
    if not isinstance(circuit, dict):
        return False
    return circuit.get("state") == "open"


def load_governor_status(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def default_state():
    return {
        "schema": SCHEMA,
        "enabled": False,
        "rollout": {"mode": "shadow", "canary_percent": 0, "canary_allowlist": []},
        "updated_at": 0.0,
    }


def load_state(path):
    if not os.path.isfile(path):
        return default_state()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return default_state()
    state = default_state()
    if isinstance(raw, dict):
        state["enabled"] = bool(raw.get("enabled", False))
        rollout = raw.get("rollout")
        if isinstance(rollout, dict):
            mode = rollout.get("mode", "shadow")
            state["rollout"]["mode"] = mode if mode in ROLLOUT_MODES else "shadow"
            state["rollout"]["canary_percent"] = int(rollout.get("canary_percent", 0) or 0)
            allowlist = rollout.get("canary_allowlist", [])
            if isinstance(allowlist, list):
                state["rollout"]["canary_allowlist"] = [str(x) for x in allowlist]
        state["updated_at"] = float(raw.get("updated_at", 0.0) or 0.0)
    return state


def save_state(path, state):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    state = dict(state)
    state["schema"] = SCHEMA
    state["updated_at"] = time.time()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)
    return state


def is_simplicio_process(argv0):
    lowered = argv0.lower()
    return any(pattern in lowered for pattern in SIMPLICIO_BINARY_PATTERNS)


def is_supervised(entry):
    if isinstance(entry, str):
        return "SIMPLICIO_SUPERVISED=1" in entry or "--supervised-by" in entry
    if isinstance(entry, dict):
        env = entry.get("env", {}) or {}
        if isinstance(env, dict) and str(env.get("SIMPLICIO_SUPERVISED", "")) == "1":
            return True
        args = entry.get("argv", [])
        if isinstance(args, list) and any("--supervised-by" in str(a) for a in args):
            return True
        marker_file = entry.get("marker_file")
        if marker_file and os.path.isfile(str(marker_file)):
            return True
        return False
    return False


def _argv0(entry):
    if isinstance(entry, str):
        parts = entry.split()
        return parts[0] if parts else ""
    if isinstance(entry, dict):
        argv = entry.get("argv", [])
        if isinstance(argv, list) and argv:
            return str(argv[0])
        return str(entry.get("argv0", ""))
    return ""


def detect_unsupervised(processes):
    flagged = []
    for entry in processes:
        argv0 = _argv0(entry)
        if not argv0:
            continue
        if is_simplicio_process(argv0) and not is_supervised(entry):
            flagged.append({"argv0": argv0, "raw": entry})
    return flagged


def cmd_status(opts):
    state = load_state(_state_file())
    governor_path = getattr(opts, "governor_state_file", None) or os.environ.get(
        "SIMPLICIO_GOVERNOR_STATE_FILE"
    )
    governor_status = load_governor_status(governor_path)
    breaker_open = governor_circuit_open(governor_status)
    state["governor"] = {
        "available": governor_status is not None,
        "circuit_open": breaker_open,
        "circuit": (governor_status or {}).get("circuit"),
    }
    if opts.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print("enforcement: %s" % ("enabled" if state["enabled"] else "disabled (default)"))
        print("rollout: %s" % state["rollout"]["mode"])
        if state["rollout"]["mode"] == "canary":
            print("canary_percent: %d" % state["rollout"]["canary_percent"])
            print("canary_allowlist: %s" % ",".join(state["rollout"]["canary_allowlist"]) or "-")
        if state["governor"]["available"]:
            print("governor_circuit: %s" % ("OPEN (pressure sustained)" if breaker_open else "closed"))
        else:
            print("governor_circuit: unavailable (no --governor-state-file)")
    return 0


def scan_os_processes():
    try:
        import psutil  # type: ignore
    except ImportError:
        return None
    processes = []
    for proc in psutil.process_iter(["pid", "cmdline", "environ"]):
        try:
            info = proc.info
            cmdline = info.get("cmdline") or []
            if not cmdline:
                continue
            env = info.get("environ") or {}
        except Exception:
            continue
        processes.append({"argv": [str(x) for x in cmdline], "env": {str(k): str(v) for k, v in env.items()}})
    return processes


def cmd_detect(opts):
    if getattr(opts, "scan_os", False):
        processes = scan_os_processes()
        if processes is None:
            print(
                "detect: --scan-os requires psutil, which is not installed — "
                "skipping real OS scan (graceful, not a fake pass)",
                file=sys.stderr,
            )
            return 3
    elif opts.input:
        with open(opts.input, "r", encoding="utf-8") as handle:
            raw = handle.read()
        try:
            processes = json.loads(raw) if raw.strip() else []
        except ValueError as exc:
            print("detect: invalid JSON input: %s" % exc, file=sys.stderr)
            return 2
        if not isinstance(processes, list):
            print("detect: input must be a JSON list", file=sys.stderr)
            return 2
    else:
        raw = sys.stdin.read()
        try:
            processes = json.loads(raw) if raw.strip() else []
        except ValueError as exc:
            print("detect: invalid JSON input: %s" % exc, file=sys.stderr)
            return 2
        if not isinstance(processes, list):
            print("detect: input must be a JSON list", file=sys.stderr)
            return 2
    flagged = detect_unsupervised(processes)
    state = load_state(_state_file())
    result = {
        "schema": "simplicio.supervisor-detect/v1",
        "enforcement_enabled": state["enabled"],
        "rollout_mode": state["rollout"]["mode"],
        "scanned": len(processes),
        "unsupervised": flagged,
        "action_taken": "none (diagnostic only)",
    }
    if opts.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("scanned: %d, unsupervised simplicio processes: %d" % (len(processes), len(flagged)))
        for item in flagged:
            print("  - %s" % item["argv0"])
    return 0


def cmd_enable(opts):
    guarded = opts.i_understand or os.environ.get("SIMPLICIO_SUPERVISOR_I_UNDERSTAND") == "1"
    if not guarded:
        print(
            "enable: refused — pass --i-understand to opt in explicitly "
            "(enforcement never defaults to on)",
            file=sys.stderr,
        )
        return 2
    path = _state_file()
    state = load_state(path)
    state["enabled"] = True
    save_state(path, state)
    print("enforcement: enabled (rollout=%s)" % state["rollout"]["mode"])
    return 0


def cmd_disable(opts):
    path = _state_file()
    state = load_state(path)
    state["enabled"] = False
    save_state(path, state)
    print("enforcement: disabled")
    return 0


def cmd_rollout(opts):
    if opts.mode not in ROLLOUT_MODES:
        print(
            "rollout: unknown mode %r — must be one of %s" % (opts.mode, ", ".join(ROLLOUT_MODES)),
            file=sys.stderr,
        )
        return 2
    if opts.percent < 0 or opts.percent > 100:
        print("rollout: --percent must be 0-100", file=sys.stderr)
        return 2
    path = _state_file()
    state = load_state(path)
    state["rollout"] = {
        "mode": opts.mode,
        "canary_percent": opts.percent,
        "canary_allowlist": list(opts.allow or []),
    }
    save_state(path, state)
    emit_rollout_event(opts.mode, opts.percent, opts.allow)
    print("rollout: mode=%s percent=%d allow=%s" % (opts.mode, opts.percent, ",".join(opts.allow or [])))
    return 0


def load_rollout_events(path):
    """Read the rollout-events JSONL log. Missing/empty file -> []. Never fabricates rows;
    a line that fails to parse as JSON is skipped rather than crashing the whole read."""
    if not path or not os.path.isfile(path):
        return []
    events = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                events.append(rec)
    return events


def summarize_rollout_events(events):
    per_mode = {mode: 0 for mode in ROLLOUT_MODES}
    for rec in events:
        mode = rec.get("mode")
        if mode in per_mode:
            per_mode[mode] += 1
    ordered = sorted(events, key=lambda rec: rec.get("ts", 0.0))
    last = ordered[-1] if ordered else None
    return {
        "schema": "simplicio.supervisor-enforcement-metrics/v1",
        "total_transitions": len(events),
        "transitions_by_mode": per_mode,
        "last_transition": last,
    }


def cmd_metrics(opts):
    events_path = getattr(opts, "events_file", None) or _events_file()
    events = load_rollout_events(events_path)
    state = load_state(_state_file())
    summary = summarize_rollout_events(events)
    summary["current_enabled"] = state["enabled"]
    summary["current_mode"] = state["rollout"]["mode"]
    if opts.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print("current: enabled=%s mode=%s" % (state["enabled"], state["rollout"]["mode"]))
        print("total rollout transitions: %d" % summary["total_transitions"])
        for mode in ROLLOUT_MODES:
            print("  %s: %d" % (mode, summary["transitions_by_mode"][mode]))
        if summary["last_transition"]:
            last = summary["last_transition"]
            print(
                "last transition: mode=%s percent=%d at ts=%s"
                % (last.get("mode"), int(last.get("canary_percent", 0) or 0), last.get("ts"))
            )
        else:
            print("last transition: none recorded")
    return 0


def cmd_selftest(_opts):
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="supervisor_enforcement_selftest_")
    checks = []
    try:
        state_file = os.path.join(tmp, "state.json")
        os.environ["SIMPLICIO_SUPERVISOR_STATE_FILE"] = state_file

        state = load_state(state_file)
        checks.append(("default_disabled", state["enabled"] is False))
        checks.append(("default_rollout_shadow", state["rollout"]["mode"] == "shadow"))

        class Opts:
            pass

        enable_opts = Opts()
        enable_opts.i_understand = False
        rc = cmd_enable(enable_opts)
        checks.append(("enable_without_guard_refused", rc == 2))
        checks.append(("still_disabled_after_refused_enable", load_state(state_file)["enabled"] is False))

        enable_opts.i_understand = True
        rc = cmd_enable(enable_opts)
        checks.append(("enable_with_guard_succeeds", rc == 0))
        checks.append(("enabled_after_guarded_enable", load_state(state_file)["enabled"] is True))

        disable_opts = Opts()
        rc = cmd_disable(disable_opts)
        checks.append(("disable_succeeds", rc == 0))
        checks.append(("disabled_after_disable", load_state(state_file)["enabled"] is False))

        processes = [
            "simplicio-mapper --survey",
            "SIMPLICIO_SUPERVISED=1 simplicio-dev-cli --execute",
            "python3 unrelated_tool.py",
            {"argv": ["mapper", "--survey"], "env": {}},
            {"argv": ["mapper", "--survey"], "env": {"SIMPLICIO_SUPERVISED": "1"}},
        ]
        flagged = detect_unsupervised(processes)
        flagged_argv0 = {item["argv0"] for item in flagged}
        checks.append(("detect_flags_unsupervised", "simplicio-mapper" in flagged_argv0))
        checks.append(("detect_ignores_supervised_env_string", "SIMPLICIO_SUPERVISED=1" not in flagged_argv0))
        checks.append(("detect_ignores_unrelated", "python3" not in flagged_argv0))
        checks.append(("detect_flags_dict_unsupervised", "mapper" in flagged_argv0))
        checks.append(("detect_ignores_dict_supervised", len(flagged) == 2))

        rollout_opts = Opts()
        rollout_opts.mode = "bogus"
        rollout_opts.percent = 0
        rollout_opts.allow = []
        rc = cmd_rollout(rollout_opts)
        checks.append(("rollout_rejects_unknown_mode", rc == 2))

        rollout_opts.mode = "canary"
        rollout_opts.percent = 25
        rollout_opts.allow = ["ws-a"]
        rc = cmd_rollout(rollout_opts)
        checks.append(("rollout_accepts_canary", rc == 0))
        state = load_state(state_file)
        checks.append(("rollout_persisted_canary", state["rollout"]["mode"] == "canary" and state["rollout"]["canary_percent"] == 25))

        os.remove(state_file)
        state = load_state(state_file)
        checks.append(("fallback_status_safe_when_no_state_file", state["enabled"] is False))
        flagged_after_fallback = detect_unsupervised(processes)
        checks.append(("detect_unaffected_by_missing_state", len(flagged_after_fallback) == 2))
    finally:
        os.environ.pop("SIMPLICIO_SUPERVISOR_STATE_FILE", None)
        shutil.rmtree(tmp, ignore_errors=True)

    ok = all(passed for _, passed in checks)
    for name, passed in checks:
        print("  %s %s" % ("PASS" if passed else "FAIL", name))
    print("selftest: %s (%d/%d)" % ("PASS" if ok else "FAIL", sum(1 for _, p in checks if p), len(checks)))
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="verb")

    status_p = sub.add_parser("status")
    status_p.add_argument("--json", action="store_true")
    status_p.add_argument(
        "--governor-state-file",
        default=None,
        help="path to a ResourceGovernor.status() JSON snapshot (#506 circuit breaker)",
    )

    detect_p = sub.add_parser("detect")
    detect_p.add_argument("--input", default=None, help="read process list JSON from FILE instead of stdin")
    detect_p.add_argument("--json", action="store_true")
    detect_p.add_argument(
        "--scan-os",
        action="store_true",
        help="enumerate the real OS process table via psutil instead of reading stdin (opt-in)",
    )

    enable_p = sub.add_parser("enable")
    enable_p.add_argument("--i-understand", action="store_true")

    sub.add_parser("disable")

    rollout_p = sub.add_parser("rollout")
    rollout_p.add_argument("--mode", required=True)
    rollout_p.add_argument("--percent", type=int, default=0)
    rollout_p.add_argument("--allow", action="append", default=[])

    sub.add_parser("selftest")

    metrics_p = sub.add_parser("metrics")
    metrics_p.add_argument("--json", action="store_true")
    metrics_p.add_argument(
        "--events-file", default=None, help="path to the rollout events JSONL log (default: %s)" % DEFAULT_EVENTS_FILE
    )

    opts = parser.parse_args()
    if not opts.verb:
        parser.print_help()
        return 2

    handlers = {
        "status": cmd_status,
        "detect": cmd_detect,
        "enable": cmd_enable,
        "disable": cmd_disable,
        "rollout": cmd_rollout,
        "selftest": cmd_selftest,
        "metrics": cmd_metrics,
    }
    return handlers[opts.verb](opts)


if __name__ == "__main__":
    sys.exit(main())
