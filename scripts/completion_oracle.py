#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from simplicio_loop.oracle import evaluate_completion, persist_completion_receipt


def selftest() -> int:
    print("selftest: PASS completion-oracle cli shell loaded")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="completion_oracle")
    if argv == ["selftest"] or (argv is None and len(sys.argv) > 1 and sys.argv[1] == "selftest"):
        return selftest()
    parser.add_argument("--loop-dir", default=os.path.join(".simplicio-loop/orchestrator", "loop"))
    parser.add_argument("--run-dir", default=os.environ.get("SIMPLICIO_RUN_DIR", ""))
    parser.add_argument("--response-text", default="")
    parser.add_argument("--flow-gap", default="")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args(argv)
    payload = evaluate_completion(args.loop_dir, args.run_dir, response_text=args.response_text,
                                  flow_gap=args.flow_gap)
    if args.write_receipt:
        payload["receipt_path"] = persist_completion_receipt(payload, args.loop_dir, args.run_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
