#!/usr/bin/env python3
"""simplicio-loop — `simplicio.dashboard-event/v1` telemetry stream (issue #1398).

One append-only event source per run that the live dashboard consumes instead of polling dozens
of files: ``<run-dir>/events.jsonl``. Contract: ``contracts/dashboard-event/v1/`` (schema.json is
authoritative); guide and kind table: ``docs/DASHBOARD_EVENTS.md``.

Producers:
  * the runner (``simplicio_loop.runner``): every progress event it already records in
    ``state.json`` and every ``transitions.jsonl`` entry is mapped onto the catalog here
    (``specs_from_runner_event`` / ``events_from_transition``), so the runner logic is not
    duplicated;
  * the hooks (``loop_stop``, ``action_gate``, ``user_prompt_submit``) through
    ``emit_from_hook``, which resolves the active run and is a no-op when there is none;
  * any worker or shell host through ``python3 scripts/dashboard_events.py emit``.

Guarantees:
  * ``seq`` is allocated under the cross-process sidecar lock of ``_locked_append`` and is
    gap-free and duplicate-free per run, across processes and across size rotation;
  * FAIL-OPEN: emitting never raises into (or blocks) the loop. Any failure (unwritable sink,
    lock timeout, invalid event) drops the event and records a diagnostic (stderr once per
    reason, an in-process list and ``SIMPLICIO_DASHBOARD_EVENTS_DIAGNOSTICS``, default
    ``<tmp>/simplicio-loop/dashboard-events-diagnostics.jsonl``);
  * kill switch: ``SIMPLICIO_DASHBOARD_EVENTS=0`` writes nothing at all;
  * size rotation: ``events.jsonl`` -> ``events.jsonl.1`` .. ``.N``
    (``SIMPLICIO_DASHBOARD_EVENTS_MAX_BYTES``, default 16 MiB; ``SIMPLICIO_DASHBOARD_EVENTS_KEEP``,
    default 3);
  * runs without a live stream (older runs) are rebuilt from ``transitions.jsonl`` + ``state.json``
    events + receipts by ``derive_events`` and every rebuilt event carries ``derived: true``.

Stdlib only and Python 3.8+ compatible: hooks import it from a plugin install too.

Usage:
    python3 scripts/dashboard_events.py read RUN_DIR [--since N]
    python3 scripts/dashboard_events.py validate FILE [FILE ...]
    python3 scripts/dashboard_events.py emit RUN_DIR --kind KIND --source SOURCE [--phase P]
        [--task-id T] [--lane L] [--iteration N] [--severity S] [--payload JSON] [--ref PATH ...]
    python3 scripts/dashboard_events.py bench [--events N] [--fsync] [--json]
    python3 scripts/dashboard_events.py selftest
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))

try:
    import _locked_append as _locks
except ImportError:  # loaded as a library from a path that is not on sys.path
    _spec = importlib.util.spec_from_file_location(
        "_locked_append", os.path.join(_HERE, "_locked_append.py"))
    _locks = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_locks)
    sys.modules.setdefault("_locked_append", _locks)

SCHEMA = "simplicio.dashboard-event/v1"
DIAGNOSTIC_SCHEMA = "simplicio.dashboard-event-diagnostic/v1"
PRODUCER = "simplicio-loop"
EVENTS_FILE = "events.jsonl"
FIELDS = (
    "schema", "event_id", "seq", "ts", "run_id", "task_id", "scope", "source", "kind",
    "phase", "lane", "iteration", "severity", "payload", "refs", "producer_version",
)
OPTIONAL_FIELDS = ("derived",)

# The loop (coding) kind catalog. Bare names belong to the loop; other products reuse the same
# envelope with their own "<namespace>.<kind>" names (the "loop." namespace is reserved).
KIND_CATALOG = {
    "lifecycle": ("run_started", "phase_entered", "phase_exited", "contract_frozen", "map_ready",
                  "plan_frozen"),
    "lanes_tasks": ("worker_claimed", "lane_progress", "iteration_started", "iteration_finished",
                    "apply_result"),
    "quality": ("test_result", "lint_result", "coverage_result", "gate_evaluated"),
    "recovery": ("retry_scheduled", "stall_detected", "decision_requested"),
    "delivery_cost": ("delivery_reconciled", "pr_opened", "token_usage", "cost_sample"),
    "end": ("run_finished",),
}
LOOP_KINDS_ORDERED = tuple(k for kinds in KIND_CATALOG.values() for k in kinds)
LOOP_KINDS = frozenset(LOOP_KINDS_ORDERED)
SOURCES = ("hook", "runner", "worker", "oracle", "operator")
SCOPES = ("collection", "task", "scenario")
SEVERITIES = ("debug", "info", "warning", "error")
GATES = ("evidence", "watcher", "oracle", "dod", "quality", "action")
TERMINAL_PHASES = frozenset({"done", "partial", "cancelled"})
RUN_ROOTS = (os.path.join(".simplicio-loop", "orchestrator", "runs"),
             os.path.join(".simplicio-loop", "loop-runs"))

ENV_SWITCH = "SIMPLICIO_DASHBOARD_EVENTS"
ENV_MAX_BYTES = "SIMPLICIO_DASHBOARD_EVENTS_MAX_BYTES"
ENV_KEEP = "SIMPLICIO_DASHBOARD_EVENTS_KEEP"
ENV_FSYNC = "SIMPLICIO_DASHBOARD_EVENTS_FSYNC"
ENV_DIAGNOSTICS = "SIMPLICIO_DASHBOARD_EVENTS_DIAGNOSTICS"
DEFAULT_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_KEEP = 3
MAX_PAYLOAD_BYTES = 32 * 1024
LOCK_TIMEOUT_MS = 1000
TAIL_SCAN_LIMIT = 1024 * 1024
ACTIVE_RUN_WINDOW_S = 24 * 3600

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_NAMESPACED_KIND_RE = re.compile(r"^(?!loop\.)[a-z][a-z0-9-]*\.[a-z][a-z0-9_]*$")
_PRODUCER_RE = re.compile(r"^[A-Za-z0-9._-]+@\S+$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FALSE = frozenset({"0", "false", "no", "off", "disabled"})
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:secret|password|passwd|api[_-]?key|authorization|cookie|credentials?|"
    r"private[_-]?key|token)$", re.IGNORECASE)
_SENSITIVE_VALUE = re.compile(
    r"(Bearer\s+\S+|gh[pousr]_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:https?|wss?)://[^/\s:@]+:[^@\s]+@)", re.IGNORECASE)

_DIAGNOSTICS = []
_DIAGNOSTICS_REPORTED = set()
_PRODUCER_VERSION = []


# ---------------------------------------------------------------- primitives

def enabled(env=None):
    """False only when the kill switch ``SIMPLICIO_DASHBOARD_EVENTS`` is set to a falsy value."""
    value = (os.environ if env is None else env).get(ENV_SWITCH, "")
    return str(value).strip().lower() not in _FALSE


def new_ulid(ts_ms=None, randomness=None):
    """Return a 26-char Crockford ULID: 48-bit millisecond time + 80 random bits."""
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
    if randomness is None:
        randomness = os.urandom(10)
    value = ((int(ts_ms) & ((1 << 48) - 1)) << 80) | int.from_bytes(bytes(randomness)[:10], "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def format_ts(epoch_seconds):
    """RFC 3339 UTC with milliseconds: ``2026-10-02T21:00:00.123Z``."""
    ms = int(round(float(epoch_seconds) * 1000))
    secs, ms = divmod(ms, 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(secs)) + ".%03dZ" % ms


def parse_ts(text):
    """Parse an ISO-8601 timestamp (``Z`` or an offset) into epoch seconds; None if unparseable."""
    if not isinstance(text, str) or not text.strip():
        return None
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def producer_version():
    """``simplicio-loop@<version>`` of the installed distribution (cached per process)."""
    if not _PRODUCER_VERSION:
        version = ""
        try:
            from importlib.metadata import version as _dist_version
            version = _dist_version(PRODUCER)
        except Exception:
            version = ""
        if not version:
            try:
                with open(os.path.join(os.path.dirname(_HERE), "pyproject.toml"), encoding="utf-8") as fh:
                    match = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
                version = match.group(1) if match else ""
            except OSError:
                version = ""
        _PRODUCER_VERSION.append("%s@%s" % (PRODUCER, version or "unknown"))
    return _PRODUCER_VERSION[0]


def _redact(value, depth=0):
    if depth > 12:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if _SENSITIVE_KEY.search(str(k)) else _redact(v, depth + 1))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth + 1) for item in value]
    if isinstance(value, str):
        return _SENSITIVE_VALUE.sub("[REDACTED]", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _bounded_payload(payload):
    clean = _redact(dict(payload or {}))
    size = len(json.dumps(clean, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size <= MAX_PAYLOAD_BYTES:
        return clean
    bounded = {"truncated": True, "bytes": size}
    step = clean.get("step")
    if isinstance(step, str) and len(step) <= 200:
        bounded["step"] = step
    return bounded


def _opt_str(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_envelope(*, run_id, kind, source, seq, task_id=None, scope=None, phase=None, lane=None,
                   iteration=None, severity="info", payload=None, refs=None, ts=None,
                   event_id=None, derived=False):
    """Assemble one envelope in canonical field order. It does not validate: see validate_envelope."""
    task_id = _opt_str(task_id)
    if scope not in SCOPES:
        scope = "task" if task_id else "collection"
    elif scope == "collection":
        task_id = None
    elif not task_id:
        scope = "collection"
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        ts_text = format_ts(ts)
    elif isinstance(ts, str) and _TS_RE.match(ts):
        ts_text = ts
    else:
        parsed = parse_ts(ts) if ts else None
        ts_text = format_ts(parsed if parsed is not None else time.time())
    if event_id is None:
        event_id = new_ulid(int(parse_ts(ts_text) * 1000))
    if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
        iteration = None if iteration is None or not str(iteration).isdigit() else int(str(iteration))
    evt = {
        "schema": SCHEMA,
        "event_id": event_id,
        "seq": seq,
        "ts": ts_text,
        "run_id": str(run_id or ""),
        "task_id": task_id,
        "scope": scope,
        "source": source,
        "kind": kind,
        "phase": _opt_str(phase),
        "lane": _opt_str(lane),
        "iteration": iteration,
        "severity": severity,
        "payload": _bounded_payload(payload),
        "refs": [str(r) for r in (refs or []) if r not in (None, "")],
        "producer_version": producer_version(),
    }
    if derived:
        evt["derived"] = True
    return evt


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_envelope(evt):
    """Stdlib structural validation mirroring schema.json; returns a list of error strings."""
    if not isinstance(evt, dict):
        return ["envelope: not an object"]
    errors = []
    for field in FIELDS:
        if field not in evt:
            errors.append("%s: required field missing" % field)
    for field in evt:
        if field not in FIELDS and field not in OPTIONAL_FIELDS:
            errors.append("%s: additional property not allowed" % field)
    if errors:
        return errors
    if evt["schema"] != SCHEMA:
        errors.append("schema: must be %s" % SCHEMA)
    if not isinstance(evt["event_id"], str) or not _ULID_RE.match(evt["event_id"]):
        errors.append("event_id: must be a ULID")
    if not _is_int(evt["seq"]) or evt["seq"] < 1:
        errors.append("seq: must be an integer >= 1")
    if not isinstance(evt["ts"], str) or not _TS_RE.match(evt["ts"]):
        errors.append("ts: must be RFC 3339 UTC with milliseconds")
    if not isinstance(evt["run_id"], str) or not 1 <= len(evt["run_id"]) <= 200:
        errors.append("run_id: must be a non-empty string")
    task_id = evt["task_id"]
    if task_id is not None and (not isinstance(task_id, str) or not task_id):
        errors.append("task_id: must be null or a non-empty string")
    if evt["scope"] not in SCOPES:
        errors.append("scope: must be one of %s" % ", ".join(SCOPES))
    elif evt["scope"] == "collection" and task_id is not None:
        errors.append("task_id: must be null for scope=collection")
    elif evt["scope"] in ("task", "scenario") and not task_id:
        errors.append("task_id: required for scope=%s" % evt["scope"])
    if evt["source"] not in SOURCES:
        errors.append("source: must be one of %s" % ", ".join(SOURCES))
    kind = evt["kind"]
    if not isinstance(kind, str) or not (kind in LOOP_KINDS or _NAMESPACED_KIND_RE.match(kind)):
        errors.append("kind: not in the loop catalog and not a '<namespace>.<kind>' name")
    for field in ("phase", "lane"):
        value = evt[field]
        if value is not None and (not isinstance(value, str) or not value):
            errors.append("%s: must be null or a non-empty string" % field)
    iteration = evt["iteration"]
    if iteration is not None and (not _is_int(iteration) or iteration < 0):
        errors.append("iteration: must be null or an integer >= 0")
    if evt["severity"] not in SEVERITIES:
        errors.append("severity: must be one of %s" % ", ".join(SEVERITIES))
    if not isinstance(evt["payload"], dict):
        errors.append("payload: must be an object")
    refs = evt["refs"]
    if not isinstance(refs, list) or any(not isinstance(r, str) or not r for r in refs):
        errors.append("refs: must be an array of non-empty strings")
    if not isinstance(evt["producer_version"], str) or not _PRODUCER_RE.match(evt["producer_version"]):
        errors.append("producer_version: must look like <producer>@<version>")
    if "derived" in evt and not isinstance(evt["derived"], bool):
        errors.append("derived: must be a boolean")
    return errors


# ---------------------------------------------------------------- diagnostics (fail-open)

def diagnostics_path():
    configured = os.environ.get(ENV_DIAGNOSTICS, "").strip()
    if configured:
        return configured
    return os.path.join(tempfile.gettempdir(), "simplicio-loop", "dashboard-events-diagnostics.jsonl")


def diagnostics():
    """Diagnostics recorded by this process (bounded, newest last)."""
    return list(_DIAGNOSTICS)


def _diagnose(run_dir, reason, detail=""):
    try:
        record = {
            "schema": DIAGNOSTIC_SCHEMA,
            "ts": format_ts(time.time()),
            "run_dir": str(run_dir),
            "reason": reason,
            "detail": str(detail)[:500],
            "pid": os.getpid(),
        }
        _DIAGNOSTICS.append(record)
        del _DIAGNOSTICS[:-100]
        key = (str(run_dir), reason)
        if key in _DIAGNOSTICS_REPORTED:
            return
        _DIAGNOSTICS_REPORTED.add(key)
        try:
            sys.stderr.write("dashboard_events: DEGRADE — event dropped for %s (%s): %s\n"
                             % (run_dir, reason, record["detail"]))
        except Exception:
            pass
        path = diagnostics_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- sink

def _int_env(name, default):
    try:
        value = int(os.environ.get(name, "") or default)
        return value if value >= 0 else default
    except ValueError:
        return default


def _scan_tail(path):
    """Return (last seq or None, file ends with a newline, size) reading only the file's tail."""
    try:
        fh = open(path, "rb")
    except OSError:
        return None, True, 0
    with fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size == 0:
            return None, True, 0
        fh.seek(size - 1)
        ends_with_newline = fh.read(1) == b"\n"
        pos, buf, scanned = size, b"", 0
        while pos > 0 and scanned < TAIL_SCAN_LIMIT:
            step = min(8192, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
            scanned += step
            lines = buf.split(b"\n")
            complete = lines if pos == 0 else lines[1:]
            for raw in reversed(complete):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj.get("schema") == SCHEMA and _is_int(obj.get("seq")):
                    return obj["seq"], ends_with_newline, size
            buf = lines[0] if pos > 0 else b""
        return None, ends_with_newline, size


def _rotate(path, keep):
    if keep <= 0:
        os.remove(path)
        return
    for index in range(keep - 1, 0, -1):
        older = "%s.%d" % (path, index)
        if os.path.exists(older):
            os.replace(older, "%s.%d" % (path, index + 1))
    os.replace(path, path + ".1")


def emit_batch(run_dir, specs, strict=False):
    """Append several events atomically (one lock, contiguous ``seq``). Returns the written events.

    FAIL-OPEN: returns ``[]`` and records a diagnostic on any failure. ``strict=True`` raises
    ``ValueError`` for an invalid event instead (tests and the fixture generator use it).
    """
    if not enabled():
        return []
    try:
        run_dir = os.fspath(run_dir)
        default_run_id = os.path.basename(os.path.normpath(run_dir))
        prepared = []
        for spec in specs:
            spec = dict(spec)
            run_id = spec.pop("run_id", None) or default_run_id
            try:
                evt = build_envelope(run_id=run_id, seq=1, **spec)
                errors = validate_envelope(evt)
            except (TypeError, ValueError) as exc:
                errors = ["spec: %s" % exc]
            if errors:
                if strict:
                    raise ValueError("invalid dashboard event: %s" % "; ".join(errors))
                _diagnose(run_dir, "invalid_event", "; ".join(errors))
                continue
            prepared.append(evt)
        if not prepared:
            return []
        if not os.path.isdir(run_dir):
            _diagnose(run_dir, "run_dir_missing", run_dir)
            return []
        path = os.path.join(run_dir, EVENTS_FILE)
        with _locks.exclusive_lock(path, timeout_ms=LOCK_TIMEOUT_MS) as problem:
            if problem:
                _diagnose(run_dir, "lock_unavailable", problem)
                return []
            seq, ends_with_newline, size = _scan_tail(path)
            if seq is None and size == 0:
                seq = _scan_tail(path + ".1")[0]
            seq = seq or 0
            lines = []
            for evt in prepared:
                seq += 1
                evt["seq"] = seq
                lines.append(json.dumps(evt, ensure_ascii=False, separators=(",", ":")))
            blob = ("" if ends_with_newline else "\n") + "\n".join(lines) + "\n"
            max_bytes = _int_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES)
            if size > 0 and max_bytes and size + len(blob.encode("utf-8")) > max_bytes:
                _rotate(path, _int_env(ENV_KEEP, DEFAULT_KEEP))
                blob = blob.lstrip("\n")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(blob)
                fh.flush()
                if str(os.environ.get(ENV_FSYNC, "")).strip().lower() in ("1", "true", "yes", "on"):
                    os.fsync(fh.fileno())
        return prepared
    except ValueError:
        if strict:
            raise
        _diagnose(run_dir, "emit_failed", "ValueError")
        return []
    except Exception as exc:  # fail-open: telemetry never breaks the loop
        _diagnose(run_dir, "emit_failed", "%s: %s" % (type(exc).__name__, exc))
        return []


def emit(run_dir, kind, *, source, strict=False, **spec):
    """Append one event; returns the written envelope or None (fail-open)."""
    spec.update(kind=kind, source=source)
    written = emit_batch(run_dir, [spec], strict=strict)
    return written[0] if written else None


# ---------------------------------------------------------------- derivation (runner + legacy runs)

def _rel_ref(ref, run_dir):
    ref = str(ref or "").strip()
    if not ref:
        return ""
    if run_dir:
        try:
            base = os.path.abspath(os.fspath(run_dir))
            target = os.path.abspath(ref) if os.path.isabs(ref) else ref
            if os.path.isabs(target) and os.path.commonpath([base, target]) == base:
                return os.path.relpath(target, base).replace(os.sep, "/")
        except ValueError:
            pass
    return ref


def _refs(values, run_dir):
    out = []
    for value in values:
        rel = _rel_ref(value, run_dir)
        if rel and rel not in out:
            out.append(rel)
    return out


def events_from_transition(entry, run_dir=None, source="runner"):
    """Map one ``transitions.jsonl`` entry onto lifecycle event specs (live and retroactive)."""
    if not isinstance(entry, dict):
        return []
    to = _opt_str(entry.get("to"))
    if not to:
        return []
    frm = _opt_str(entry.get("from"))
    reason = str(entry.get("reason") or "")
    refs = _refs([entry.get("receipt")], run_dir)
    base = {"source": source, "refs": refs}
    if entry.get("ts"):
        base["ts"] = entry["ts"]
    specs = []
    if frm is None:
        specs.append(dict(base, kind="run_started", phase=to, payload={"reason": reason}))
    else:
        specs.append(dict(base, kind="phase_exited", phase=frm, payload={"to": to, "reason": reason}))
    entered_severity = "error" if to == "blocked" else "info"
    specs.append(dict(base, kind="phase_entered", phase=to, severity=entered_severity,
                      payload={"from": frm, "reason": reason}))
    if to == "awaiting_decision":
        specs.append(dict(base, kind="decision_requested", phase=to, payload={"reason": reason}))
    if to in TERMINAL_PHASES:
        specs.append(dict(base, kind="run_finished", phase=to,
                          severity="info" if to == "done" else "warning",
                          payload={"outcome": to, "reason": reason}))
    return specs


# runner progress kind -> (catalog kind, source, gate)
RUNNER_KIND_MAP = {
    "contract_frozen": ("contract_frozen", "runner", None),
    "mapper_fresh": ("map_ready", "runner", None),
    "mapper_degraded": ("map_ready", "runner", None),
    "plan_ready": ("plan_frozen", "runner", None),
    "worker_claimed": ("worker_claimed", "worker", None),
    "worktree_created": ("lane_progress", "worker", None),
    "operator_receipt": ("apply_result", "worker", None),
    "operator_bootstrap": ("retry_scheduled", "runner", None),
    "rollback": ("retry_scheduled", "runner", None),
    "test_gate": ("gate_evaluated", "runner", "evidence"),
    "watcher_challenge": ("gate_evaluated", "runner", "watcher"),
    "oracle_verdict": ("gate_evaluated", "oracle", "oracle"),
    "delivery_reconciled": ("delivery_reconciled", "runner", None),
    "handoff": ("lane_progress", "operator", None),
    "blocked": ("stall_detected", "runner", None),
    "stack_lock_frozen": ("lane_progress", "runner", None),
    "storage_route_frozen": ("lane_progress", "runner", None),
    "technical_debt": ("lane_progress", "runner", None),
}
_PAYLOAD_KEYS = ("status", "verdict", "current_state", "execution_state", "route", "generation",
                 "decision_id", "lease_id", "branch", "reason_code")


def specs_from_runner_event(event, state=None, run_dir=None):
    """Map one runner progress event (``state['events']`` shape) onto dashboard event specs."""
    if not isinstance(event, dict):
        return []
    state = state if isinstance(state, dict) else {}
    if event.get("phase") == "phase_transition" or event.get("kind") == "phase_transition":
        return events_from_transition({
            "from": event.get("from_phase"), "to": event.get("to_phase"),
            "reason": event.get("reason"), "receipt": event.get("receipt"), "ts": event.get("ts"),
        }, run_dir=run_dir)
    step = str(event.get("kind") or event.get("phase") or "").strip() or "unknown"
    kind, source, gate = RUNNER_KIND_MAP.get(step, ("lane_progress", "runner", None))
    blocker = str(event.get("blocker") or "")
    payload = {"step": step}
    for key in ("message", "blocker", "reason"):
        if event.get(key):
            payload[key] = str(event[key])
    for key in _PAYLOAD_KEYS:
        value = event.get(key)
        if value not in (None, "", [], {}) and isinstance(value, (str, int, float, bool)):
            payload[key] = value
    ac_ids = event.get("ac_ids")
    if isinstance(ac_ids, list) and ac_ids:
        payload["ac_ids"] = [str(a) for a in ac_ids][:50]
    debt = event.get("technical_debt")
    if isinstance(debt, dict):
        for key in ("reason_code", "severity", "next_action", "debt_id", "occurrences"):
            if debt.get(key) not in (None, ""):
                payload["debt_" + key] = debt[key]
    if gate:
        payload["gate"] = gate
        if step == "watcher_challenge":
            payload["verdict"] = "pending"
        else:
            if "verdict" in payload:
                payload["verdict_detail"] = payload["verdict"]
            payload["verdict"] = "fail" if blocker else "pass"
    if kind == "stall_detected":
        severity = "error"
    elif blocker or step == "mapper_degraded" or (isinstance(debt, dict) and debt.get("severity") == "high"):
        severity = "warning"
    else:
        severity = "info"
    worktree = event.get("worktree") if isinstance(event.get("worktree"), dict) else {}
    lane = (event.get("lane") or worktree.get("lane_id") or worktree.get("lane")
            or worktree.get("branch") or event.get("branch") or None)
    phase = event.get("phase") if isinstance(event.get("phase"), str) else None
    if not phase or phase == step:
        phase = state.get("phase") if isinstance(state.get("phase"), str) else None
    iteration = event.get("iteration", state.get("iteration"))
    task_id = event.get("task_id") or None
    scope = event.get("scope") if event.get("scope") in SCOPES else None
    spec = {
        "kind": kind, "source": source, "task_id": task_id, "scope": scope, "phase": phase,
        "lane": lane, "iteration": iteration if _is_int(iteration) else None,
        "severity": severity, "payload": payload,
        "refs": _refs([event.get("receipt"), worktree.get("lock_receipt")], run_dir),
    }
    run_id = state.get("run_id") or event.get("run_id")
    if run_id:
        spec["run_id"] = str(run_id)
    if event.get("ts"):
        spec["ts"] = event["ts"]
    return [spec]


def _live_spec_ts(specs):
    """Live emission stamps the real emission time (ms precision) instead of the seconds-precision
    timestamp the runner stored; the original stays recoverable from transitions.jsonl/state.json."""
    for spec in specs:
        spec.pop("ts", None)
    return specs


def emit_runner_event(run_dir, state, event):
    """Runner seam: map + emit one progress event. Never raises."""
    try:
        specs = _live_spec_ts(specs_from_runner_event(event, state, run_dir=run_dir))
        return emit_batch(run_dir, specs) if specs else []
    except Exception as exc:
        _diagnose(run_dir, "emit_failed", "%s: %s" % (type(exc).__name__, exc))
        return []


def emit_transition(run_dir, entry, run_id=None):
    """Runner seam for a raw ``transitions.jsonl`` entry. Never raises."""
    try:
        specs = _live_spec_ts(events_from_transition(entry, run_dir=run_dir))
        if run_id:
            for spec in specs:
                spec["run_id"] = run_id
        return emit_batch(run_dir, specs) if specs else []
    except Exception as exc:
        _diagnose(run_dir, "emit_failed", "%s: %s" % (type(exc).__name__, exc))
        return []


# ---------------------------------------------------------------- hooks

def resolve_run_dir(cwd=None, env=None):
    """Find the run a hook event belongs to, or None (then the hook emits nothing).

    Order: ``SIMPLICIO_RUN_DIR``; ``SIMPLICIO_RUN_ID`` under either run root; otherwise the single
    non-terminal run updated in the last 24h. With several active runs the hook cannot tell which
    one it serves, so it emits nothing rather than misattribute the event.
    """
    env = os.environ if env is None else env
    explicit = str(env.get("SIMPLICIO_RUN_DIR") or "").strip()
    if explicit:
        return explicit if os.path.isdir(explicit) else None
    base = cwd or os.getcwd()
    run_id = str(env.get("SIMPLICIO_RUN_ID") or "").strip()
    if run_id:
        if not _RUN_ID_RE.match(run_id):
            return None
        for root in RUN_ROOTS:
            candidate = os.path.join(base, root, run_id)
            if os.path.isdir(candidate):
                return candidate
        return None
    active = []
    now = time.time()
    for root in RUN_ROOTS:
        root_dir = os.path.join(base, root)
        try:
            names = os.listdir(root_dir)
        except OSError:
            continue
        for name in names:
            state_path = os.path.join(root_dir, name, "state.json")
            try:
                if now - os.path.getmtime(state_path) > ACTIVE_RUN_WINDOW_S:
                    continue
                with open(state_path, encoding="utf-8") as fh:
                    phase = (json.load(fh) or {}).get("phase")
            except (OSError, ValueError, AttributeError):
                continue
            if phase not in TERMINAL_PHASES:
                active.append(os.path.join(root_dir, name))
    return active[0] if len(active) == 1 else None


def emit_from_hook(kind, cwd=None, source="hook", **spec):
    """Hook seam: emit into the resolved run, no-op without one. Never raises."""
    try:
        if not enabled():
            return None
        run_dir = resolve_run_dir(cwd=cwd)
        if not run_dir:
            return None
        return emit(run_dir, kind, source=source, **spec)
    except Exception:
        return None


# ---------------------------------------------------------------- readers

def _event_files(run_dir):
    run_dir = os.fspath(run_dir)
    path = os.path.join(run_dir, EVENTS_FILE)
    rotated = []
    try:
        for name in os.listdir(run_dir):
            match = re.match(r"^events\.jsonl\.(\d+)$", name)
            if match:
                rotated.append((int(match.group(1)), os.path.join(run_dir, name)))
    except OSError:
        return []
    return [p for _, p in sorted(rotated, reverse=True)] + [path]


def read_live_events(run_dir):
    """Every ``dashboard-event/v1`` line of the run (rotated files first), ordered by ``seq``.
    Torn lines and foreign records (older progress events) are skipped."""
    events = []
    for path in _event_files(run_dir):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(obj, dict) and obj.get("schema") == SCHEMA and _is_int(obj.get("seq")):
                        events.append(obj)
        except OSError:
            continue
    events.sort(key=lambda e: e["seq"])
    return events


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


_RECEIPT_STEPS = (
    ("task-contract.json", "contract_frozen"),
    ("mapper-context.json", "mapper_fresh"),
    ("plan.json", "plan_ready"),
    ("operator-receipt.json", "operator_receipt"),
    ("evidence-receipt.json", "test_gate"),
    ("delivery-receipt.json", "delivery_reconciled"),
    ("completion-receipt.json", "oracle_verdict"),
)


def _receipt_event(run_dir, name, step):
    path = os.path.join(run_dir, name)
    receipt = _load_json(path)
    if receipt is None:
        return None
    event = {"kind": step, "receipt": path}
    if isinstance(receipt, dict):
        if step == "test_gate":
            event["status"] = str(receipt.get("status") or "UNVERIFIED")
            if event["status"] != "VERIFIED":
                event["blocker"] = "evidence_unverified"
        elif step == "oracle_verdict" and receipt.get("ready") is not True:
            event["blocker"] = "oracle_incomplete"
        elif step == "delivery_reconciled" and receipt.get("ready") is not True:
            event["blocker"] = "delivery_reconciliation_failed"
        stamp = receipt.get("checked_at") or receipt.get("measured_at") or receipt.get("updated_at") \
            or receipt.get("created_at")
        if isinstance(stamp, str) and parse_ts(stamp) is not None:
            event["ts"] = stamp
    if "ts" not in event:
        try:
            event["ts"] = format_ts(os.path.getmtime(path))
        except OSError:
            return None
    return event


def token_usage_specs(run_dir, only=None):
    """``token_usage`` specs from the run's own ``execution-route*.json`` records.

    Only integer counts the run recorded become events. A record with null counts (route decided before
    any provider call) or without a ``token_usage`` block yields nothing: counts are never invented.
    """
    run_dir = os.fspath(run_dir)
    try:
        names = sorted(n for n in os.listdir(run_dir)
                       if n.startswith("execution-route") and n.endswith(".json")
                       and (only is None or n == only))
    except OSError:
        return []
    specs = []
    for name in names:
        path = os.path.join(run_dir, name)
        record = _load_json(path)
        usage = record.get("token_usage") if isinstance(record, dict) else None
        if not isinstance(usage, dict):
            continue
        counts = {k: usage.get(k) for k in ("input_tokens", "output_tokens")}
        if not all(_is_int(v) and v >= 0 for v in counts.values()):
            continue
        payload = dict(counts)
        for key in ("model",):
            if isinstance(record.get(key), str) and record[key]:
                payload[key] = record[key]
        if isinstance(usage.get("reason"), str):
            payload["reason"] = usage["reason"]
        spec = {"kind": "token_usage", "source": "runner", "payload": payload, "refs": [path]}
        if isinstance(record.get("task_id"), str) and record["task_id"]:
            spec["task_id"] = record["task_id"]
        if isinstance(record.get("route"), str) and record["route"]:
            spec["lane"] = record["route"]
        try:
            spec["ts"] = format_ts(os.path.getmtime(path))
        except OSError:
            pass
        specs.append(spec)
    return specs


def emit_token_usage(run_dir, only=None):
    """Emit recorded token usage (one route file when ``only`` is set) to the live stream, fail-open."""
    try:
        specs = token_usage_specs(run_dir, only=only)
        return emit_batch(run_dir, specs) if specs else []
    except Exception:  # telemetry never blocks the loop
        return []


def derive_events(run_dir):
    """Rebuild a run's stream from ``transitions.jsonl`` + ``state.json`` events + receipts.

    Every event is marked ``derived: true``; ``event_id`` is deterministic (same run -> same ids),
    so a consumer can de-duplicate across re-reads.
    """
    run_dir = os.fspath(run_dir)
    state = _load_json(os.path.join(run_dir, "state.json"))
    state = state if isinstance(state, dict) else {}
    run_id = str(state.get("run_id") or os.path.basename(os.path.normpath(run_dir)))
    specs = []
    try:
        with open(os.path.join(run_dir, "transitions.jsonl"), encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    entry = json.loads(raw)
                except ValueError:
                    continue
                specs.extend(events_from_transition(entry, run_dir=run_dir))
    except OSError:
        pass
    state_events = [e for e in (state.get("events") or [])
                    if isinstance(e, dict) and e.get("phase") != "phase_transition"
                    and e.get("kind") != "phase_transition"]
    if state_events:
        for event in state_events:
            specs.extend(specs_from_runner_event(event, state, run_dir=run_dir))
    else:
        for name, step in _RECEIPT_STEPS:
            event = _receipt_event(run_dir, name, step)
            if event:
                specs.extend(specs_from_runner_event(event, state, run_dir=run_dir))
    specs.extend(token_usage_specs(run_dir))
    ordered = []
    for index, spec in enumerate(specs):
        stamp = parse_ts(spec.get("ts")) if spec.get("ts") else None
        ordered.append((stamp if stamp is not None else 0.0, index, spec))
    ordered.sort(key=lambda item: (item[0], item[1]))
    events = []
    current_phase = None
    for stamp, index, spec in ordered:
        spec = dict(spec)
        if spec["kind"] in ("run_started", "phase_entered"):
            current_phase = spec.get("phase")
        elif spec["kind"] not in ("phase_exited", "decision_requested", "run_finished") and current_phase:
            spec["phase"] = current_phase  # the phase the run was in when this receipt was written
        spec["run_id"] = run_id
        spec["ts"] = format_ts(stamp)
        digest = hashlib.sha256(("%s|%d|%s" % (run_id, index, json.dumps(spec, sort_keys=True, default=str)))
                                .encode("utf-8")).digest()
        spec.setdefault("event_id", new_ulid(int(round(stamp * 1000)), digest[:10]))
        evt = build_envelope(seq=len(events) + 1, derived=True, **spec)
        if not validate_envelope(evt):  # invalid legacy data is skipped, never fabricated
            events.append(evt)
    for seq, evt in enumerate(events, start=1):
        evt["seq"] = seq
    return events


def read_events(run_dir, since_seq=0):
    """The run's dashboard stream: live events when present, else the derived reconstruction."""
    events = read_live_events(run_dir) or derive_events(run_dir)
    return [e for e in events if e["seq"] > since_seq] if since_seq else events


# ---------------------------------------------------------------- benchmark + CLI

def bench(events=2000, run_dir=None, warmup=50):
    """Measure the per-event cost of ``emit`` (lock + seq + append) on the local filesystem."""
    owned = run_dir is None
    run_dir = run_dir or tempfile.mkdtemp(prefix="dashboard-events-bench-")
    try:
        for _ in range(warmup):
            emit(run_dir, "lane_progress", source="worker", payload={"warmup": True})
        samples = []
        for index in range(events):
            start = time.perf_counter()
            emit(run_dir, "lane_progress", source="worker", phase="executing", lane="lane-a",
                 iteration=index, payload={"step": "bench", "index": index})
            samples.append((time.perf_counter() - start) * 1000.0)
        samples.sort()

        def pct(p):
            return round(samples[min(len(samples) - 1, int(len(samples) * p))], 4)

        return {"schema": "simplicio.dashboard-event-bench/v1", "events": events,
                "fsync": str(os.environ.get(ENV_FSYNC, "")).lower() in ("1", "true", "yes", "on"),
                "p50_ms": pct(0.50), "p95_ms": pct(0.95), "p99_ms": pct(0.99),
                "max_ms": round(samples[-1], 4), "written": len(read_live_events(run_dir)) - warmup}
    finally:
        if owned:
            import shutil
            shutil.rmtree(run_dir, ignore_errors=True)


def selftest():
    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        previous_diag = os.environ.get(ENV_DIAGNOSTICS)
        os.environ[ENV_DIAGNOSTICS] = os.path.join(tmp, "diagnostics.jsonl")
        try:
            _selftest_checks(tmp, checks)
        finally:
            if previous_diag is None:
                os.environ.pop(ENV_DIAGNOSTICS, None)
            else:
                os.environ[ENV_DIAGNOSTICS] = previous_diag
    ok = all(passed for _, passed in checks)
    for name, passed in checks:
        print("[%s] %s" % ("ok" if passed else "XX", name))
    print("selftest: %s" % ("pass" if ok else "FAILED"))
    return 0 if ok else 1


def _selftest_checks(tmp, checks):
    run_dir = os.path.join(tmp, "run-selftest")
    os.makedirs(run_dir)
    first = emit(run_dir, "run_started", source="runner", phase="intake", strict=True)
    second = emit(run_dir, "phase_entered", source="runner", phase="intake", strict=True)
    checks.append(("seq is contiguous", first["seq"] == 1 and second["seq"] == 2))
    checks.append(("envelopes validate", all(not validate_envelope(e) for e in read_events(run_dir))))
    previous = os.environ.get(ENV_SWITCH)
    os.environ[ENV_SWITCH] = "0"
    try:
        checks.append(("kill switch writes nothing",
                       emit(run_dir, "run_finished", source="runner") is None))
    finally:
        if previous is None:
            os.environ.pop(ENV_SWITCH, None)
        else:
            os.environ[ENV_SWITCH] = previous
    blocked = os.path.join(run_dir, "blocked")
    os.makedirs(os.path.join(blocked, EVENTS_FILE))  # a directory: the sink cannot be opened
    checks.append(("unwritable sink fails open",
                   emit(blocked, "run_started", source="runner") is None))
    legacy = os.path.join(tmp, "run-legacy")
    os.makedirs(legacy)
    with open(os.path.join(legacy, "transitions.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2026-01-01T00:00:00Z", "from": None, "to": "intake"}) + "\n")
    derived = read_events(legacy)
    checks.append(("legacy run is derived", bool(derived) and all(e.get("derived") for e in derived)))
    checks.append(("failure recorded a diagnostic", os.path.isfile(os.environ[ENV_DIAGNOSTICS])))


def _parser():
    parser = argparse.ArgumentParser(prog="dashboard_events.py",
                                     description="simplicio.dashboard-event/v1 stream tools")
    sub = parser.add_subparsers(dest="command", required=True)
    read = sub.add_parser("read", help="print a run's events as JSONL (derived for older runs)")
    read.add_argument("run_dir")
    read.add_argument("--since", type=int, default=0, help="only events with seq greater than this")
    validate = sub.add_parser("validate", help="validate JSONL files of dashboard events")
    validate.add_argument("files", nargs="+")
    emit_p = sub.add_parser("emit", help="append one event to a run (fail-open)")
    emit_p.add_argument("run_dir")
    emit_p.add_argument("--kind", required=True)
    emit_p.add_argument("--source", required=True, choices=SOURCES)
    emit_p.add_argument("--phase")
    emit_p.add_argument("--task-id")
    emit_p.add_argument("--lane")
    emit_p.add_argument("--iteration", type=int)
    emit_p.add_argument("--severity", default="info", choices=SEVERITIES)
    emit_p.add_argument("--payload", default="{}", help="JSON object")
    emit_p.add_argument("--ref", action="append", default=[], help="receipt/file path (repeatable)")
    bench_p = sub.add_parser("bench", help="measure per-event emit overhead (p50/p95/p99)")
    bench_p.add_argument("--events", type=int, default=2000)
    bench_p.add_argument("--fsync", action="store_true", help="fsync every append")
    bench_p.add_argument("--json", action="store_true")
    sub.add_parser("selftest", help="run the built-in self-check")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "selftest":
        return selftest()
    if args.command == "read":
        for evt in read_events(args.run_dir, since_seq=args.since):
            sys.stdout.write(json.dumps(evt, ensure_ascii=False, separators=(",", ":")) + "\n")
        return 0
    if args.command == "validate":
        bad = 0
        for path in args.files:
            with open(path, encoding="utf-8") as fh:
                for number, raw in enumerate(fh, start=1):
                    if not raw.strip():
                        continue
                    try:
                        errors = validate_envelope(json.loads(raw))
                    except ValueError as exc:
                        errors = ["not JSON: %s" % exc]
                    for error in errors:
                        bad += 1
                        print("%s:%d: %s" % (path, number, error))
        print("validate: %s" % ("ok" if not bad else "%d error(s)" % bad))
        return 0 if not bad else 1
    if args.command == "emit":
        try:
            payload = json.loads(args.payload)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            print("emit: --payload must be a JSON object", file=sys.stderr)
            return 2
        evt = emit(args.run_dir, args.kind, source=args.source, phase=args.phase,
                   task_id=args.task_id, lane=args.lane, iteration=args.iteration,
                   severity=args.severity, payload=payload, refs=args.ref)
        print(json.dumps(evt, ensure_ascii=False))
        return 0
    if args.command == "bench":
        if args.fsync:
            os.environ[ENV_FSYNC] = "1"
        result = bench(events=args.events)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("dashboard-event emit: %d events, fsync=%s, p50=%.4fms p95=%.4fms p99=%.4fms max=%.4fms"
                  % (result["events"], result["fsync"], result["p50_ms"], result["p95_ms"],
                     result["p99_ms"], result["max_ms"]))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
