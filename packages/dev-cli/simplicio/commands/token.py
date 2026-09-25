"""``simplicio-py token`` — token-efficient execution primitives.

Extracted from `cli.py`'s `_run_token_command` (issue #103); behavior
unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys

from ._shared import read_text_source

CLI_PROG = "simplicio-py"


def run(a: argparse.Namespace) -> int:
    from ..token_primitives import (
        ContextCache,
        build_retry_payload,
        evaluate_postconditions,
        git_diff_review,
        model_routing_decision,
        summarize_log,
    )

    try:
        if a.token_cmd == "log-summary":
            payload = summarize_log(read_text_source(a.file), max_chars=a.max_chars)
        elif a.token_cmd == "diff-review":
            payload = git_diff_review(a.root, max_patch_chars=a.max_patch_chars)
        elif a.token_cmd == "postconditions":
            checks = json.loads(read_text_source(a.file))
            payload = evaluate_postconditions(checks, root=a.root)
        elif a.token_cmd == "retry":
            log = read_text_source(a.log_file) if a.log_file else ""
            failure = json.loads(a.failure_json) if a.failure_json else {}
            payload = build_retry_payload(
                reason=a.reason,
                failure=failure,
                log=log,
                max_log_chars=a.max_log_chars,
            )
        elif a.token_cmd == "model-routing":
            payload = model_routing_decision(json.loads(read_text_source(a.file)))
        elif a.token_cmd == "context-cache":
            cache = ContextCache(a.root)
            content = read_text_source(a.content_file) if a.content_file else ""
            if a.cache_cmd == "get":
                payload = cache.get(a.key, content)
            elif a.cache_cmd == "put":
                summary = json.loads(read_text_source(a.summary_file))
                payload = cache.put(a.key, content, summary)
            else:
                payload = cache.invalidate(a.key)
        else:
            print(f"{CLI_PROG} token: unsupported command", file=sys.stderr)
            return 2
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"{CLI_PROG} token {a.token_cmd}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0
