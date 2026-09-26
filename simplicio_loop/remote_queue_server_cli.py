#!/usr/bin/env python3
"""Packaged CLI: run the stdlib HTTP facade for a simplicio.queue/v1 SQLite backend.

Lives inside the ``simplicio_loop`` package (issue #286 step 11) -- unlike the historical
``scripts/remote_queue_server.py``, this module ships in the installed wheel/sdist, so
``pip install simplicio-loop`` gets a genuinely runnable queue-server binary (the
``simplicio-remote-queue-server`` console script), not just source that only works from a git
checkout. ``scripts/remote_queue_server.py`` is kept as a thin backward-compatible shim over this
module for existing repo-local tooling/tests.
"""
from __future__ import annotations

import argparse
import os
import signal
from pathlib import Path

from .mapper_remote_queue import MapperRemoteQueue
from .local_task_queue_cli import _default_mapper_db
from .remote_queue import SQLiteRemoteQueue, create_http_queue_server, tls_context_from_files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".",
                        help="Loop checkout used to resolve repo-scoped MapperStore data")
    parser.add_argument("--db", default=None, help="legacy shared SQLite queue file path")
    parser.add_argument("--mapper-db", default=None, help="canonical MapperStore operations.sqlite path")
    parser.add_argument("--mapper-init", action="store_true",
                        help="explicitly initialize --mapper-db before serving")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=os.environ.get("SIMPLICIO_QUEUE_TOKEN"),
                        help="legacy static bearer secret; mutually exclusive with --token-secret")
    parser.add_argument("--token-secret", default=os.environ.get("SIMPLICIO_QUEUE_TOKEN_SECRET"),
                        help="#289 short-lived-credential mode: HMAC signing secret; callers must "
                             "present a token minted by scripts/short_lived_credentials.py issue")
    parser.add_argument("--token-scope", default=os.environ.get("SIMPLICIO_QUEUE_TOKEN_SCOPE"),
                        help="required `scope` claim on tokens when --token-secret is set")
    parser.add_argument("--revocation-store",
                        default=os.environ.get("SIMPLICIO_QUEUE_REVOCATION_STORE",
                                               ".simplicio-loop/orchestrator/security/revoked-jti.json"),
                        help="revocation store path checked when --token-secret is set")
    parser.add_argument("--tls-certfile", default=os.environ.get("SIMPLICIO_QUEUE_TLS_CERTFILE"))
    parser.add_argument("--tls-keyfile", default=os.environ.get("SIMPLICIO_QUEUE_TLS_KEYFILE"))
    args = parser.parse_args()
    if args.db and args.mapper_db:
        parser.error("--db and --mapper-db are mutually exclusive")
    if args.mapper_init and args.db:
        parser.error("--mapper-init cannot be combined with legacy --db")
    if not args.token and not args.token_secret:
        parser.error("one of --token/SIMPLICIO_QUEUE_TOKEN or --token-secret/SIMPLICIO_QUEUE_TOKEN_SECRET is required")
    if args.token and args.token_secret:
        parser.error("--token and --token-secret are mutually exclusive auth modes")
    if bool(args.tls_certfile) != bool(args.tls_keyfile):
        parser.error("--tls-certfile and --tls-keyfile must be provided together")
    context = (tls_context_from_files(args.tls_certfile, args.tls_keyfile)
               if args.tls_certfile else None)
    try:
        if args.mapper_db:
            queue = MapperRemoteQueue(args.mapper_db, auto_create=False)
            if args.mapper_init:
                queue.initialize()
        elif args.db:
            # Legacy SQLite remains available only when the operator explicitly names --db.
            queue = SQLiteRemoteQueue(args.db)
        else:
            database = _default_mapper_db(args.repo)
            queue = MapperRemoteQueue(database, auto_create=False)
            if args.mapper_init:
                queue.initialize()
        server = create_http_queue_server(
            queue, args.host, args.port,
            token=args.token, token_secret=args.token_secret, token_scope=args.token_scope,
            revocation_store=Path(args.revocation_store) if args.token_secret else None,
            ssl_context=context,
        )
    except ValueError as exc:
        parser.error(str(exc))
    signal.signal(signal.SIGTERM, lambda *_: server.shutdown())
    print("simplicio queue listening on %s:%d" % (args.host, server.server_port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
