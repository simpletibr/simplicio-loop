#!/usr/bin/env python3
"""Smoke test of a local Langfuse (issue #1611).

Sends one synthetic run (one task, two gates) through the loop's own exporter, then reads the trace
and the gate scores back from the Langfuse API and checks that they arrived. It never fakes a pass:

- OK          the observations and both scores were read back. Exit 0.
- FAILED      the export or the read-back did not work. Exit 1.
- UNVERIFIED  there is nothing to test against (no Docker, no LANGFUSE_HOST, no keys). Exit 0, with the reason.

Keys come from the environment (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY), the target from LANGFUSE_HOST.
One JSON line goes to stdout; the secret key is never printed. See docs/LANGFUSE_LOCAL.md.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from simplicio_loop.langfuse_export import export_once  # noqa: E402
from simplicio_loop.langfuse_export.config import check_host, load_config  # noqa: E402
from simplicio_loop.langfuse_export.ids import trace_id as trace_id_of  # noqa: E402

OK = "OK"
FAILED = "FAILED"
UNVERIFIED = "UNVERIFIED"

OBSERVATIONS_PATH = "/api/public/v2/observations"  # Langfuse v4 real-time read path
SCORES_PATH = "/api/public/v3/scores"
READ_REFUSED = frozenset({401, 403, 404})  # wrong keys, or a server without the v4 read API

# What the fixture must produce. A type of None means any type; only the generation is typed because
# it is the one observation the mapping tells apart (measured tokens).
EXPECTED_OBSERVATIONS: dict[str, str | None] = {
    "simplicio-loop run": None,
    "task T1": None,
    "generation T1": "GENERATION",
    "gate tests": None,
    "gate lint": None,
}
EXPECTED_SCORES: dict[str, bool] = {"gate:tests": True, "gate:lint": False}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None  # the auth header must not follow a redirect to another host


_OPENER = urllib.request.build_opener(_NoRedirect)


def verdict(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, **extra}


def build_fixture(root: Path, run_id: str, now: float) -> tuple[Path, Path]:
    """A synthetic repo (one execution report) and run dir (two gate events). No real data."""
    repo = Path(root) / "repo"
    reports = repo / ".simplicio-loop" / "runtime" / "execution-reports"
    reports.mkdir(parents=True)
    started = now - 10
    report = {
        "schema": "simplicio.execution-report/v1",
        "owner": "simplicio-loop",
        "run_id": run_id,
        "repo": "/smoke/fixture",
        "status": "CLOSED",
        "started_at_unix": started,
        "finished_at_unix": now,
        "wall_ms": 10_000,
        "tasks": [
            {
                "task_id": "T1",
                "title": "Smoke fixture task",
                "wall_ms": 8_000,
                "tokens": {"tokens_in": 1200, "tokens_out": 340, "source": "cli_measured"},
                "outcome": "COMPLETE",
                "agent": {"role": "executor", "model": "fixture-model"},
            }
        ],
        "consolidated": {},
    }
    (reports / f"{run_id}.json").write_text(json.dumps(report), encoding="utf-8")
    stamp = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    events = [
        {
            "schema": "simplicio.dashboard-event/v1",
            "event_id": f"evt-{seq}",
            "seq": seq,
            "ts": stamp,
            "run_id": run_id,
            "task_id": "T1",
            "scope": "loop",
            "source": "langfuse-smoke",
            "kind": "gate_evaluated",
            "phase": "verify",
            "lane": None,
            "iteration": 1,
            "severity": "info",
            "payload": {"gate": gate, "passed": passed},
            "refs": [],
            "producer_version": "langfuse-smoke",
        }
        for seq, (gate, passed) in enumerate((("tests", True), ("lint", False)), start=1)
    ]
    run_dir = Path(root) / "run"
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    return repo, run_dir


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(
    host: str, path: str, query: Mapping[str, Any], auth: str, timeout: float
) -> tuple[int | None, list[dict[str, Any]] | None]:
    """GET one page. Returns (status, rows); rows is None unless the answer was 200 with a ``data`` list."""
    request = urllib.request.Request(
        f"{host}{path}?{urllib.parse.urlencode(query)}",
        headers={"Authorization": auth, "Accept": "application/json"},
        method="GET",
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8")).get("data")
            return int(response.status), data if isinstance(data, list) else None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, AttributeError):
        return None, None  # network or protocol trouble, or a body that is not the API's JSON


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return None


def missing_items(
    trace_id: str, observations: Sequence[Mapping[str, Any]], scores: Sequence[Mapping[str, Any]]
) -> list[str]:
    """What the fixture should have produced and the API did not show (empty list = everything arrived)."""
    missing: list[str] = []
    mine = [o for o in observations if o.get("traceId") == trace_id]
    for name, kind in EXPECTED_OBSERVATIONS.items():
        found = [o for o in mine if o.get("name") == name]
        if not found:
            missing.append(f"observation {name}")
        elif kind is not None and not any(str(o.get("type")).upper() == kind for o in found):
            got = str(found[0].get("type")).upper()
            missing.append(f"observation {name} (expected {kind}, got {got})")
    for name, expected in EXPECTED_SCORES.items():
        found = [s for s in scores if s.get("name") == name]
        if not found:
            missing.append(f"score {name}")
        elif not any(_as_bool(s.get("value")) is expected for s in found):
            missing.append(f"score {name} (expected {expected}, got {found[0].get('value')!r})")
    return missing


def run_smoke(
    host: str,
    public_key: str,
    secret_key: str,
    *,
    timeout: float = 120.0,
    poll: float = 2.0,
    request_timeout: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: float | None = None,
) -> dict[str, Any]:
    try:
        host = check_host(host).rstrip("/")
    except ValueError as exc:
        return verdict(FAILED, "host_not_allowed", detail=str(exc))
    now = time.time() if now is None else now
    run_id = f"smoke-{int(now)}-{uuid.uuid4().hex[:8]}"  # fresh per run: an older trace can never pass
    trace_id = trace_id_of(run_id)
    base = {"host": host, "run_id": run_id, "trace_id": trace_id}
    env = {
        "LANGFUSE_HOST": host,
        "LANGFUSE_PUBLIC_KEY": public_key,
        "LANGFUSE_SECRET_KEY": secret_key,
    }
    config = load_config(
        {"langfuse_enabled": True, "langfuse_host": host, "langfuse_batch_seconds": 1}, env=env
    )
    with tempfile.TemporaryDirectory(prefix="langfuse-smoke-") as tmp:
        repo, run_dir = build_fixture(Path(tmp), run_id, now)
        exported = export_once(repo, config=config, env=env, run_dir=run_dir, force=True)
    if exported.get("status") != "ok":
        return verdict(FAILED, f"export_{exported.get('status')}", detail=exported.get("reason"), **base)
    if exported.get("blocking"):
        return verdict(FAILED, "export_blocked", detail=exported["blocking"], **base)
    if not exported.get("sent") or exported.get("pending") or exported.get("dead"):
        return verdict(FAILED, "export_incomplete", detail=json.dumps(exported, sort_keys=True), **base)

    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
    auth = f"Basic {token}"
    window = {"fromStartTime": _iso(now - 3600), "toStartTime": _iso(now + 3600)}
    started = clock()
    deadline = started + timeout
    missing: list[str] = []
    while True:
        o_status, observations = _get(
            host, OBSERVATIONS_PATH, {"traceId": trace_id, "limit": 100, **window}, auth, request_timeout
        )
        s_status, scores = _get(
            host, SCORES_PATH, {"traceId": trace_id, "limit": 100}, auth, request_timeout
        )
        for path, status in ((OBSERVATIONS_PATH, o_status), (SCORES_PATH, s_status)):
            if status in READ_REFUSED:
                return verdict(FAILED, "read_refused", detail=f"{path} answered {status}", **base)
        missing = missing_items(trace_id, observations or [], scores or [])
        waited = round(clock() - started, 3)
        if not missing:
            return verdict(
                OK, "arrived", sent=exported["sent"], waited_seconds=waited,
                observations=len(observations or []), scores=len(scores or []), **base,
            )
        if clock() >= deadline:
            return verdict(FAILED, "not_arrived", missing=missing, waited_seconds=waited, **base)
        sleep(poll)


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds to wait for ingestion (default 120)")
    parser.add_argument("--poll", type=float, default=2.0, help="seconds between reads (default 2)")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    host = env.get("LANGFUSE_HOST", "").strip()
    public_key = env.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = env.get("LANGFUSE_SECRET_KEY", "")
    if not host and which("docker") is None:
        result = verdict(
            UNVERIFIED,
            "docker_not_installed",
            detail="LANGFUSE_HOST is not set and Docker is not on PATH, so no local Langfuse can run here",
        )
    elif not host:
        result = verdict(
            UNVERIFIED,
            "langfuse_host_not_set",
            detail="start the stack from docs/LANGFUSE_LOCAL.md, then export LANGFUSE_HOST and the two keys",
        )
    elif not (public_key and secret_key):
        result = verdict(
            UNVERIFIED,
            "missing_credentials",
            detail="set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in the environment",
        )
    else:
        result = run_smoke(host, public_key, secret_key, timeout=args.timeout, poll=args.poll)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
