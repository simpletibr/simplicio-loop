"""One export cycle: read every execution report and the run's events, map, scrub, enqueue what the
server has not seen, then flush when the batch window is due. Runs under ``ExportLock``.

Fails closed: no credentials, or a host that is not https, means nothing is written. Errors in the
records themselves (a report without ``started_at_unix``, corrupt JSON) raise to the caller.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .config import CredentialFileError, LangfuseConfig, check_host, resolve_credentials
from .mapping import plan
from .otlp import encode
from .queue import ExportLock, Ledger, Outbox, content_hash, mapping_of
from .redact import scrub

MAX_SPANS_PER_REQUEST = 200
MAX_ATTEMPTS = (
    8  # flush rounds (one per batch window) before a retryable request is dead-lettered
)
SendFn = Callable[[str, Any], Any]


def langfuse_dir(repo: Path) -> Path:
    return Path(repo) / ".simplicio-loop" / "langfuse"


def load_reports(repo: Path) -> list[dict[str, Any]]:
    """Every execution report of the repo, oldest name first (run ids start with their unix time)."""
    reports = Path(repo) / ".simplicio-loop" / "runtime" / "execution-reports"
    if not reports.is_dir():
        return []
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(reports.glob("*.json"))
    ]


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
        outbox.enqueue(
            kind, body_of([i for _, _, i in chunk]), [[k, d] for k, d, _ in chunk]
        )
        for k, d, _ in chunk:
            ledger.mark_pending(k, d)
    return len(fresh)


def flush(outbox: Outbox, ledger: Ledger, send: SendFn) -> dict[str, Any]:
    """Send queued requests oldest first. A retryable failure stops the round (order is kept); a blocking
    one (bad keys, host or path) stops it without counting an attempt, so nothing is lost while fixing it."""
    sent = dead = 0
    blocking: str | None = None
    for item in outbox.pending():
        record = outbox.read(item)
        result = send(record["kind"], record["body"])
        if result.ok:
            outbox.ack(item)
            ledger.mark_sent(mapping_of(record))
            sent += 1
            continue
        if result.blocking:
            blocking = result.error
            break
        if result.retryable:
            if outbox.fail(item, max_attempts=MAX_ATTEMPTS):
                ledger.mark_rejected(
                    mapping_of(record)
                )  # exhausted: stays in dead/ until the content changes
                dead += 1
            break
        outbox.dead_letter(item)  # permanent for this body (for example 400 or 413)
        ledger.mark_rejected(mapping_of(record))
        dead += 1
    return {
        "sent": sent,
        "dead": dead,
        "pending": len(outbox.pending()),
        "blocking": blocking,
    }


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

        try:
            transport = HttpTransport(
                env.get("LANGFUSE_HOST") or config.host,
                public_key=creds.public_key,
                secret_key=creds.secret_key,
            )
        except ValueError:
            return {"status": "blocked", "reason": "host_not_https"}
        send = transport.send
        secrets.append(creds.secret_key)
    else:
        check_host(env.get("LANGFUSE_HOST") or config.host)
    reports = load_reports(repo)
    if not reports:
        return {"status": "no_report"}
    events = _read_events(run_dir)
    if events is None:
        return {"status": "blocked", "reason": "dashboard_events_missing"}

    with ExportLock(base):
        outbox = Outbox(base / "queue", base / "dead")
        ledger = Ledger(base / "ledger.json")
        enqueued = 0
        for report in reports:
            shape = plan(report, events, capture_content=config.capture_content)
            enqueued += _enqueue(
                outbox,
                ledger,
                "traces",
                scrub(shape.spans, secrets),
                lambda s: s["span_id"],
                encode,
                MAX_SPANS_PER_REQUEST,
            )
            enqueued += _enqueue(
                outbox,
                ledger,
                "scores",
                scrub(shape.scores, secrets),
                lambda s: s["id"],
                lambda rows: rows[0],
                1,
            )
        ledger.save()  # pending marks land before any send: a crash here must not queue the same rows twice

        if ledger.last_flush is None:
            ledger.last_flush = (
                now  # the first batch window opens with the first export
            )
        due = force or now - ledger.last_flush >= config.batch_seconds
        summary: dict[str, Any] = {
            "status": "ok",
            "reports": len(reports),
            "enqueued": enqueued,
            "sent": 0,
            "dead": 0,
            "blocking": None,
            "pending": len(outbox.pending()),
        }
        if due:
            summary.update(flush(outbox, ledger, send))
            ledger.last_flush = now
        ledger.save()
    return summary
