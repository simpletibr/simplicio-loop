"""One export cycle: read the run's records, map, scrub, enqueue what the server has not seen, flush
when the batch window is due. Fails closed on missing credentials (blocked, nothing written); a real
bug or a corrupt record raises to the caller, which reports it.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .config import CredentialFileError, LangfuseConfig, resolve_credentials
from .mapping import plan
from .otlp import encode
from .queue import Ledger, Outbox, content_hash, mapping_of
from .redact import scrub

MAX_SPANS_PER_REQUEST = 200
MAX_ATTEMPTS = (
    8  # flush rounds (one per batch window) before a retryable request is dead-lettered
)
SendFn = Callable[[str, Any], Any]


def langfuse_dir(repo: Path) -> Path:
    return Path(repo) / ".simplicio-loop" / "langfuse"


def latest_report(repo: Path) -> dict[str, Any] | None:
    reports = Path(repo) / ".simplicio-loop" / "runtime" / "execution-reports"
    if not reports.is_dir():
        return None
    files = sorted(reports.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def _read_events(run_dir: Path | None) -> list[dict[str, Any]] | None:
    if run_dir is None:
        return []
    from ..dashboard_events import load as load_dashboard_events

    module = load_dashboard_events()
    if module is None:
        return None
    return list(module.read_live_events(str(run_dir)))


def _enqueue(
    outbox: Outbox,
    ledger: Ledger,
    kind: str,
    items: Sequence[Any],
    key: Callable[[Any], str],
    body_of: Callable[[Sequence[Any]], Any],
    per_request: int,
) -> int:
    fresh = []
    for item in items:
        digest = content_hash(item)
        if ledger.wants(key(item), digest):
            fresh.append((key(item), digest, item))
    for start in range(0, len(fresh), per_request):
        chunk = fresh[start : start + per_request]
        marks = [[k, d] for k, d, _ in chunk]
        outbox.enqueue(kind, body_of([i for _, _, i in chunk]), marks)
        for k, d, _ in chunk:
            ledger.mark_pending(k, d)
    return len(fresh)


def flush(outbox: Outbox, ledger: Ledger, send: SendFn) -> dict[str, int]:
    """Send queued requests oldest first. A retryable failure stops the round (order is kept)."""
    sent = dead = 0
    for item in outbox.pending():
        record = outbox.read(item)
        result = send(record["kind"], record["body"])
        if result.ok:
            outbox.ack(item)
            ledger.mark_sent(mapping_of(record))
            sent += 1
        elif result.retryable:
            if outbox.fail(item, max_attempts=MAX_ATTEMPTS):
                ledger.forget_pending(mapping_of(record))
                dead += 1
            break
        else:
            outbox.dead_letter(item)
            ledger.mark_rejected(mapping_of(record))
            dead += 1
    return {"sent": sent, "dead": dead, "pending": len(outbox.pending())}


def export_once(
    repo: Path,
    *,
    config: LangfuseConfig,
    env: Mapping[str, str] | None = None,
    run_dir: Path | None = None,
    now: float | None = None,
    send: SendFn | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if not config.enabled:
        return {"status": "disabled"}
    env = os.environ if env is None else env
    now = time.time() if now is None else now
    base = langfuse_dir(repo)
    secrets = [env.get("LANGFUSE_SECRET_KEY", "")]
    if send is None:
        try:
            creds = resolve_credentials(env, base)
        except CredentialFileError:
            return {"status": "blocked", "reason": "credential_file_mode"}
        if creds is None:
            return {"status": "blocked", "reason": "missing_credentials"}
        from .transport import HttpTransport

        transport = HttpTransport(
            env.get("LANGFUSE_HOST") or config.host,
            public_key=creds.public_key,
            secret_key=creds.secret_key,
        )
        send = transport.send
        secrets.append(creds.secret_key)
    report = latest_report(repo)
    if report is None:
        return {"status": "no_report"}
    events = _read_events(run_dir)
    if events is None:
        return {"status": "blocked", "reason": "dashboard_events_missing"}

    shape = plan(report, events, capture_content=config.capture_content)
    spans = scrub(shape.spans, secrets)
    scores = scrub(shape.scores, secrets)
    outbox = Outbox(base / "queue", base / "dead")
    ledger = Ledger(base / "ledger.json")
    enqueued = _enqueue(
        outbox,
        ledger,
        "traces",
        spans,
        lambda s: s["span_id"],
        encode,
        MAX_SPANS_PER_REQUEST,
    )
    enqueued += _enqueue(
        outbox, ledger, "scores", scores, lambda s: s["id"], lambda rows: rows[0], 1
    )
    ledger.save()  # pending marks land before any send: a crash here must not queue the same rows twice

    if ledger.last_flush is None:
        ledger.last_flush = now  # the first batch window opens with the first export
    due = force or now - ledger.last_flush >= config.batch_seconds
    summary: dict[str, Any] = {
        "status": "ok",
        "enqueued": enqueued,
        "sent": 0,
        "dead": 0,
        "pending": len(outbox.pending()),
    }
    if due:
        summary.update(flush(outbox, ledger, send))
        ledger.last_flush = now
    ledger.save()
    return summary
