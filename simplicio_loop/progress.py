"""Honest, portable progress rendering for a simplicio-loop run.

The progress protocol is deliberately independent of a terminal.  Runtimes can consume the
same ``simplicio.progress/v1`` JSON event, render compact text/Markdown, or opt into ANSI
animation.  A run never reports 100% merely because its phase is ``done``: completion must be
backed by a fresh, ready completion receipt from the oracle.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from .execution_route import verify_route_hash
from .event_metadata import metadata_policy, normalise_event

SCHEMA = "simplicio.progress/v1"
PHASES = ("intake", "mapping", "planning", "executing", "validating", "watching", "delivering", "done")
PHASE_META = {
    "intake": ("📥", "Contrato recebido"),
    "mapping": ("🗺️", "Contexto mapeado"),
    "planning": ("🧭", "Plano congelado"),
    "executing": ("⚙️", "Execução em andamento"),
    "validating": ("🧪", "Validação e evidências"),
    "watching": ("👁️", "Watcher verificando"),
    "delivering": ("📦", "Entrega reconciliada"),
    "done": ("✅", "Concluído pelo oracle"),
    "blocked": ("⛔", "Bloqueado"),
    "cancelled": ("🛑", "Cancelado"),
    "awaiting_decision": ("⏸️", "Aguardando decisão"),
}
SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
EVENT_KINDS = frozenset((
    "contract_frozen", "mapper_fresh", "plan_ready", "worker_claimed",
    "worktree_created", "operator_receipt", "test_gate", "watcher_challenge",
    "oracle_verdict", "delivery_reconciled", "rollback", "handoff", "technical_debt",
    "operator_bootstrap",
))
def _ascii(value: Any) -> str:
    """Replace presentation glyphs; payloads remain Unicode-safe and unchanged."""
    text = str(value or "")
    for glyph, replacement in (("📥", "[in]"), ("🗺️", "[map]"), ("🧭", "[plan]"),
                               ("⚙️", "[run]"), ("🧪", "[test]"), ("👁️", "[watch]"),
                               ("📦", "[ship]"), ("✅", "[ok]"), ("⛔", "[blocked]"),
                               ("🛑", "[stop]"), ("⏸️", "[wait]"), ("█", "#"), ("░", "."),
                               ("⠋", "|"), ("⠙", "/"), ("⠹", "-"), ("⠸", "\\"),
                               ("▫️", "[ ]")):
        text = text.replace(glyph, replacement)
    return text


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _completion(run_dir: Path | None, state: Mapping[str, Any]) -> Dict[str, Any]:
    current = dict(state.get("completion") or {})
    if run_dir:
        path = run_dir / "completion-receipt.json"
        if path.is_file():
            try:
                current.update(_load_json(path))
            except (OSError, ValueError, TypeError):
                current["tag"] = "UNVERIFIED"
    return current


def _phase_percent(phase: str) -> int:
    if phase in PHASES:
        return round(PHASES.index(phase) / (len(PHASES) - 1) * 100)
    return 0


def _event_kind(item: Mapping[str, Any]) -> str:
    value = item.get("kind") or item.get("event") or item.get("phase") or "unknown"
    return str(value).strip().lower().replace("-", "_") or "unknown"


def _normalise_ac_ids(item: Mapping[str, Any]) -> list[str]:
    value = item.get("ac_ids", item.get("ac_id", ()))
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(entry) for entry in value if str(entry).strip()]
    return []


def _normalise_events(value: Any, *, run_id: str = "") -> list[Dict[str, Any]]:
    """Normalize events through the versioned collection/task/scenario policy."""
    if not isinstance(value, (list, tuple)):
        return []
    return [normalise_event(item, run_id=run_id) for item in value[-12:]
            if isinstance(item, Mapping)]


def _normalise_technical_debts(state: Mapping[str, Any]) -> list[Dict[str, Any]]:
    raw = state.get("technical_debts") or state.get("technical_debt") or []
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    debts = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        debt = dict(item)
        debt["blocking"] = False
        debt["status"] = str(debt.get("status") or "OPEN").upper()
        debts.append(debt)
    return debts


def _normalise_blockers(state: Mapping[str, Any], events: Iterable[Mapping[str, Any]], *,
                        terminal_verified: bool = False) -> list[str]:
    blockers = []
    raw = state.get("blockers") or []
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, (list, tuple)):
        blockers.extend(str(item) for item in raw if str(item).strip())
    # Event history is append-only and may contain transient failures that were
    # subsequently recovered.  Once the oracle has verified a terminal run, only
    # the current state blockers are actionable; replaying historical blockers in
    # the progress card makes a successful run look blocked.
    if not terminal_verified:
        blockers.extend(str(item["blocker"]) for item in events if item.get("blocker"))
    return list(dict.fromkeys(blockers))


def build_progress(state: Mapping[str, Any], *, run_dir: str | Path | None = None,
                   frame: int = 0) -> Dict[str, Any]:
    """Build one deterministic progress event from ``state.json`` and its receipt.

    ``frame`` is only presentation metadata for an optional spinner. It never affects the
    percentage or completion verdict.
    """
    root = Path(run_dir) if run_dir else None
    phase = str(state.get("phase") or "intake").lower()
    completion = _completion(root, state)
    # ``verify_run`` records the independently measured terminal verdict as
    # ``VERIFIED``; older oracle callers use ``COMPLETE``/``DRAINED``.  All three
    # are terminal only when the receipt explicitly says it is ready.
    ready = bool(completion.get("ready")) and str(completion.get("verdict") or "").upper() in {
        "COMPLETE", "DRAINED", "VERIFIED",
    }
    evidence = dict(state.get("evidence") or {})
    watcher = dict(state.get("watcher") or {})
    execution_route = dict(
        state.get("execution_route")
        or (state.get("operator") or {}).get("execution_route")
        or {}
    )
    if root:
        route_path = root / "execution-route.json"
        if route_path.is_file():
            try:
                candidate = _load_json(route_path)
                if verify_route_hash(candidate):
                    execution_route = dict(candidate)
            except (OSError, ValueError, TypeError):
                execution_route = {}
    route_receipt_status = "MEASURED" if execution_route else "UNVERIFIED"
    # Receipts are authoritative when state.json has not yet been refreshed by a hook.
    if root:
        for path, target in ((root / "evidence-receipt.json", evidence),
                             (root / "loop" / "watcher_state.json", watcher)):
            if path.is_file():
                try:
                    receipt = _load_json(path)
                    target.update(receipt)
                    # Older hooks persisted only a status; promote that measured receipt
                    # over stale state.json flags without weakening the oracle gate.
                    if path.name == "evidence-receipt.json" and str(receipt.get("status") or "").upper() == "VERIFIED":
                        target["ready"] = True
                except (OSError, ValueError, TypeError):
                    target["status"] = "UNVERIFIED"
    evidence_ready = str(evidence.get("status") or "").upper() == "VERIFIED" and (
        bool(evidence.get("ready")) or "ready" not in evidence)
    watcher_status = str(watcher.get("status") or "").upper()
    watcher_ready = bool(watcher.get("ready")) or watcher_status in {"MATCH", "VERIFIED"} or (
        watcher_status == "MEASURED" and watcher.get("match") is True)
    # A producer may persist a measured percentage when a phase has finer-grained
    # milestones (for example 25/50/75% within ``executing``).  It is presentation
    # metadata only: an unverified run can never advertise 100%, even if a stale or
    # malformed producer wrote that value.
    supplied_percent = state.get("progress_percent", state.get("percent"))
    try:
        supplied_percent = int(supplied_percent) if supplied_percent is not None else None
    except (TypeError, ValueError):
        supplied_percent = None
    phase_percent = min(99, _phase_percent(phase))
    if supplied_percent is not None:
        phase_percent = max(0, min(99, supplied_percent))
    if phase == "cancelled":
        percent = 0
    else:
        percent = 100 if ready else phase_percent
    icon, label = PHASE_META.get(phase, ("•", phase.replace("_", " ").title()))
    total = int(state.get("task_count") or 0)
    coverage = state.get("coverage") or {}
    verified = 0
    for item in coverage.values() if isinstance(coverage, Mapping) else ():
        if isinstance(item, Mapping):
            verified += int(item.get("verified") or 0)
    events = _normalise_events(state.get("events") or state.get("phase_events"),
                               run_id=str(state.get("run_id") or ""))
    blockers = _normalise_blockers(state, events, terminal_verified=ready and phase == "done")
    technical_debts = _normalise_technical_debts(state)
    status = "COMPLETE" if ready else ("BLOCKED" if phase == "blocked" else
                                        "CANCELLED" if phase == "cancelled" else
                                        "DEGRADED" if technical_debts else "RUNNING")
    return {
        "schema": SCHEMA,
        "run_id": str(state.get("run_id") or ""),
        "phase": phase,
        "status": status,
        "percent": percent,
        "icon": icon,
        "label": label,
        "spinner": SPINNER[frame % len(SPINNER)],
        "current_action": str(state.get("current_action") or ""),
        "next_action": str(state.get("next_action") or ""),
        "tasks": {"verified": verified, "total": total},
        "gates": {"evidence": evidence_ready, "watcher": watcher_ready, "oracle": ready},
        "completion": {"ready": ready, "verdict": str(completion.get("verdict") or "DELIVERY_PENDING"),
                       "reason_code": str(completion.get("reason_code") or "oracle_incomplete")},
        "execution_route": execution_route,
        "route_receipt_status": route_receipt_status,
        # Optional lanes/events are copied as data, never used to infer completion. This keeps
        # the same JSON contract useful for fan-out dashboards and chat adapters.
        "lanes": _normalise_lanes(state.get("lanes")),
        "events": events,
        "event_metadata_policy": metadata_policy(),
        "blockers": blockers,
        "technical_debt_count": len(technical_debts),
        "technical_debts": technical_debts,
    }


def _normalise_lanes(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    lanes = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        try:
            percent = int(item.get("percent") or 0)
        except (TypeError, ValueError):
            percent = 0
        lanes.append({"id": str(item.get("id") or item.get("lane") or f"lane-{index + 1}"),
                      "status": str(item.get("status") or "UNKNOWN").upper(),
                      "percent": max(0, min(100, percent)),
                      "worktree": str(item.get("worktree") or ""),
                      "action": str(item.get("action") or item.get("current_action") or "")})
    return lanes


def _fit_line(value: str, max_width: int = 80) -> str:
    if max_width < 8 or len(value) <= max_width:
        return value
    return value[:max_width - 1].rstrip() + "…"


def render_text(event: Mapping[str, Any], *, width: int = 24, ascii_only: bool = False,
                max_width: int = 80) -> str:
    """Render a compact, Unicode-safe progress card for chat/LLM output."""
    pct = max(0, min(100, int(event.get("percent") or 0)))
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    gates = event.get("gates") or {}
    marks = " ".join(f"{'✅' if gates.get(k) else '▫️'} {k}" for k in ("evidence", "watcher", "oracle"))
    lines = [f"{event.get('icon', '•')} {event.get('label', 'Progresso')} · {pct:3d}%",
             f"[{bar}] {event.get('spinner', '·')}", marks,
             f"ação: {event.get('current_action') or 'aguardando'} → {event.get('next_action') or '—'}"]
    lanes = event.get("lanes") or []
    if lanes:
        lines.append("lanes: " + " · ".join(f"{x['id']} {x['percent']}%/{x['status']}" for x in lanes))
    events = event.get("events") or []
    if events:
        recent = events[-3:]
        lines.append("etapas: " + " · ".join(
            f"{x['phase']}" + (f"[{x['status']}]" if x.get("status") else "") for x in recent))
    blockers = event.get("blockers") or []
    if blockers:
        lines.append("blockers: " + " · ".join(str(item) for item in blockers))
    debts = event.get("technical_debts") or []
    if debts:
        lines.append("technical debt: " + " · ".join(
            f"{item.get('reason_code', 'unknown')}[{item.get('severity', 'medium')}]"
            for item in debts[-3:] if isinstance(item, Mapping)
        ))
    if ascii_only:
        lines = [_ascii(line) for line in lines]
    return "\n".join(_fit_line(line, max_width) for line in lines)


def render_markdown(event: Mapping[str, Any], *, width: int = 20, ascii_only: bool = False) -> str:
    pct = max(0, min(100, int(event.get("percent") or 0)))
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    gates = event.get("gates") or {}
    marks = " ".join(f"{'✅' if gates.get(k) else '▫️'} {k}" for k in ("evidence", "watcher", "oracle"))
    rendered = (f"**{event.get('icon', '•')} {event.get('label', 'Progresso')} — {pct}%**\n\n"
                f"`{bar}` · `{event.get('status', 'RUNNING')}`\n\n"
                f"Gates: {marks}\n\n"
                f"Ação: `{event.get('current_action') or 'aguardando'}` → `{event.get('next_action') or '—'}`")
    if (event.get("lanes") or []):
        rendered += "\n\nLanes: " + ", ".join(f"`{x['id']}` {x['percent']}% ({x['status']})" for x in event["lanes"])
    events = event.get("events") or []
    if events:
        rendered += "\n\nEtapas: " + ", ".join(
            f"`{x['phase']}` ({x.get('status', 'INFO')})" for x in events[-3:])
    blockers = event.get("blockers") or []
    if blockers:
        rendered += "\n\nBlockers: " + ", ".join(f"`{item}`" for item in blockers)
    debts = event.get("technical_debts") or []
    if debts:
        rendered += "\n\nTechnical debt: " + ", ".join(
            f"`{item.get('reason_code', 'unknown')}` ({item.get('severity', 'medium')})"
            for item in debts[-3:] if isinstance(item, Mapping)
        )
    return _ascii(rendered) if ascii_only else rendered


def render_ansi(event: Mapping[str, Any], *, width: int = 24) -> str:
    return "\x1b[2K\r" + render_text(event, width=width).replace("\n", "\x1b[2K\n")


def load_state(run_dir: str | Path) -> Dict[str, Any]:
    root = Path(run_dir)
    return _load_json(root / "state.json")


def _write_stream_payload(out: Any, rendered: str, fallback: str, suffix: str) -> None:
    ascii_fallback = fallback.encode("ascii", errors="replace").decode("ascii")
    payload = rendered + suffix
    encoding = getattr(out, "encoding", None)
    if encoding:
        try:
            payload.encode(encoding)
        except (LookupError, UnicodeEncodeError):
            payload = ascii_fallback + suffix
    try:
        out.write(payload)
        out.flush()
    except UnicodeEncodeError:
        out.write(ascii_fallback + suffix)
        out.flush()


def stream(run_dir: str | Path, *, fmt: str = "text", interval: float = 0.25,
           once: bool = False, out: Any = None, no_animation: bool = False,
           ascii_only: bool = False) -> Dict[str, Any]:
    """Print progress snapshots until terminal; ``once`` is safe for non-interactive hosts."""
    out = out or sys.stdout
    frame = 0
    root = Path(run_dir)
    while True:
        event = build_progress(load_state(root), run_dir=root, frame=frame)
        if fmt == "json":
            rendered = json.dumps(event, ensure_ascii=False, sort_keys=True)
            fallback = json.dumps(event, ensure_ascii=True, sort_keys=True)
        elif fmt == "markdown":
            rendered = render_markdown(event, ascii_only=ascii_only)
            fallback = render_markdown(event, ascii_only=True)
        elif fmt == "ansi":
            tty = bool(getattr(out, "isatty", lambda: False)())
            animate = not no_animation and not once and tty
            rendered = render_ansi(event) if animate else render_text(
                event, ascii_only=ascii_only,
                max_width=max(40, shutil.get_terminal_size((80, 20)).columns),
            )
            fallback = render_text(
                event, ascii_only=True,
                max_width=max(40, shutil.get_terminal_size((80, 20)).columns),
            )
        else:
            rendered = render_text(event, ascii_only=ascii_only)
            fallback = render_text(event, ascii_only=True)
        _write_stream_payload(out, rendered, fallback, "\n\n" if fmt != "ansi" else "")
        if once or no_animation or event["status"] in {"COMPLETE", "BLOCKED", "CANCELLED"}:
            return event
        frame += 1
        time.sleep(max(0.05, float(interval)))


__all__ = ["EVENT_KINDS", "SCHEMA", "build_progress", "load_state", "render_ansi", "render_markdown", "render_text", "stream"]
