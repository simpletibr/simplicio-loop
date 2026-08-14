from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence

from .. import __version__
from ._shared import (
    CONFIDENCE_RANK,
    CONFIDENCE_TAG_ORDER,
    DEFAULT_TOON_COMMANDS,
    FOR_LLM_FORMATS,
    HELP_TEXT,
)

_DEFAULT_TOON_ENABLED = os.environ.get("SIMPLICIO_TOON", "1").strip().lower() not in {
    "0",
    "false",
    "off",
    "no",
}


def _read_json_safe(file: str) -> dict:
    try:
        with open(file, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _parse_args(argv: Sequence[str]) -> dict:
    opts = {
        "root": os.getcwd(),
        "out": ".simplicio",
        "stack": "",
        "product_name": "",
        "incremental": False,
        "watch": False,
        "silent": False,
        "json": False,
        "verbose": False,
        "docs": False,
        "docs_only": False,
        "background": False,
        "sync": False,
        "await": False,
        "timeout": 120,
        "command": "scan",
        "against": "",
        "target": "",
        "goal": "",
        "task_file": "",
        "task_batch_file": "",
        "task_json": "",
        "stdin": False,
        "task_fingerprint": "",
        "minimum_query_coverage": 0.2,
        "token_budget": 8000,
        "range": "",
        "staged": False,
        "check": False,
        "from_id": "",
        "to_id": "",
        "retention": 50,
        "verb": "",
        "query_arg": "",
        "depth": 3,
        "limit": 20,
        "effect": "",
        "category": "",
        "threshold": 10,
        "scope": "all",
        "for_llm": "",
        "_default_for_llm": False,
        "tagged": False,
        "confidence": "",
        "geometry": False,
        "path": "",
        "entity_id": "",
        "line": 1,
        "max_lines": 200,
        "max_bytes": 16384,
        "allow_full_content": False,
        "full_rescan": False,
        "snapshot": "",
        "clustering_config": "",
        "changed_paths": [],
        "canonical_reuse": False,
        "execution_context": False,
    }
    commands = (
        "index",
        "map",
        "update",
        "macro",
        "scan",
        "status",
        "inspect",
        "handoff",
        "orient",
        "endpoints",
        "screens",
        "flowchart",
        "docs",
        "export-docs",
        "flows",
        "visualize",
        "preview",
        "sync",
        "history",
        "diff",
        "ask",
        "business",
        "survey",
        "drift",
        "delta",
        "snapshot",
    )
    command = argv[0] if argv and argv[0] in commands else "scan"
    opts["command"] = command
    if command == "index":
        opts["silent"] = True
    if command == "update":
        opts["incremental"] = True
    i = 1 if argv and argv[0] in commands else 0
    ask_positional = 0
    while i < len(argv):
        arg = argv[i]
        if command == "ask" and not arg.startswith("-"):
            if ask_positional == 0:
                opts["root"] = arg
            elif ask_positional == 1:
                opts["verb"] = arg
            elif ask_positional == 2:
                opts["query_arg"] = arg
            ask_positional += 1
        elif command == "snapshot" and not arg.startswith("-"):
            # `snapshot` parses its own sub-command + args in _snapshot.py;
            # the top-level parser must not swallow its positionals.
            break
        elif command in (
            "index",
            "map",
            "macro",
            "scan",
            "status",
            "inspect",
            "handoff",
            "orient",
            "endpoints",
            "screens",
            "flowchart",
            "docs",
            "export-docs",
            "flows",
            "visualize",
            "preview",
            "sync",
            "history",
            "diff",
            "business",
            "survey",
            "drift",
            "delta",
        ) and not arg.startswith("-"):
            opts["root"] = arg
        elif arg == "--against":
            i += 1
            opts["against"] = argv[i]
        elif arg == "--target":
            i += 1
            opts["target"] = argv[i]
        elif arg == "--goal":
            i += 1
            try:
                opts["goal"] = argv[i]
            except IndexError:
                print("--goal requires a value", file=sys.stderr)
                sys.exit(2)
        elif arg == "--task-file":
            i += 1
            try:
                opts["task_file"] = argv[i]
            except IndexError:
                print("--task-file requires a value", file=sys.stderr)
                sys.exit(2)
        elif arg == "--task-batch-file":
            i += 1
            try:
                opts["task_batch_file"] = argv[i]
            except IndexError:
                print("--task-batch-file requires a value", file=sys.stderr)
                sys.exit(2)
        elif arg == "--task-json":
            i += 1
            try:
                opts["task_json"] = argv[i]
            except IndexError:
                print("--task-json requires a file", file=sys.stderr)
                sys.exit(2)
        elif arg == "--stdin":
            opts["stdin"] = True
        elif arg == "--task-fingerprint":
            i += 1
            try:
                opts["task_fingerprint"] = argv[i]
            except IndexError:
                print("--task-fingerprint requires a value", file=sys.stderr)
                sys.exit(2)
        elif arg == "--minimum-query-coverage":
            i += 1
            try:
                value = float(argv[i])
            except (ValueError, IndexError):
                print("--minimum-query-coverage requires a number between 0 and 1", file=sys.stderr)
                sys.exit(2)
            if not 0.0 <= value <= 1.0:
                print("--minimum-query-coverage requires a number between 0 and 1", file=sys.stderr)
                sys.exit(2)
            opts["minimum_query_coverage"] = value
        elif arg == "--token-budget":
            i += 1
            try:
                value = int(argv[i])
            except (ValueError, IndexError):
                print("--token-budget requires a positive integer", file=sys.stderr)
                sys.exit(2)
            if value <= 0:
                print("--token-budget requires a positive integer", file=sys.stderr)
                sys.exit(2)
            opts["token_budget"] = value
        elif arg == "--range":
            i += 1
            opts["range"] = argv[i]
        elif arg == "--staged":
            opts["staged"] = True
        elif arg == "--check":
            opts["check"] = True
        elif arg == "--depth":
            i += 1
            try:
                opts["depth"] = max(1, int(argv[i]))
            except (ValueError, IndexError):
                print(f"Invalid --depth value: {argv[i] if i < len(argv) else ''}", file=sys.stderr)
                sys.exit(2)
        elif arg == "--limit":
            i += 1
            try:
                opts["limit"] = max(1, int(argv[i]))
            except (ValueError, IndexError):
                print(f"Invalid --limit value: {argv[i] if i < len(argv) else ''}", file=sys.stderr)
                sys.exit(2)
        elif arg == "--effect":
            i += 1
            opts["effect"] = argv[i]
        elif arg == "--category":
            i += 1
            opts["category"] = argv[i]
        elif arg == "--threshold":
            i += 1
            try:
                opts["threshold"] = max(0, int(argv[i]))
            except (ValueError, IndexError):
                print(f"Invalid --threshold value: {argv[i] if i < len(argv) else ''}", file=sys.stderr)
                sys.exit(2)
        elif arg == "--scope":
            i += 1
            try:
                value = argv[i]
            except IndexError:
                print("--scope requires all, product, or template", file=sys.stderr)
                sys.exit(2)
            if value not in {"all", "product", "template"}:
                print("--scope requires all, product, or template", file=sys.stderr)
                sys.exit(2)
            opts["scope"] = value
        elif arg == "--from":
            i += 1
            opts["from_id"] = argv[i]
        elif arg == "--to":
            i += 1
            opts["to_id"] = argv[i]
        elif arg == "--retention":
            i += 1
            try:
                opts["retention"] = max(0, int(argv[i]))
            except (ValueError, IndexError):
                print(f"Invalid --retention value: {argv[i] if i < len(argv) else ''}", file=sys.stderr)
                sys.exit(2)
        elif arg == "--root":
            i += 1
            opts["root"] = argv[i]
        elif arg == "--out":
            i += 1
            opts["out"] = argv[i]
        elif arg == "--stack":
            i += 1
            opts["stack"] = argv[i]
        elif arg == "--product-name":
            i += 1
            opts["product_name"] = argv[i]
        elif arg == "--incremental":
            opts["incremental"] = True
        elif arg == "--update":
            opts["incremental"] = True
        elif arg == "--watch":
            opts["watch"] = True
        elif arg == "--docs":
            opts["docs"] = True
        elif arg == "--no-docs":
            opts["docs"] = False
        elif arg == "--json-only":
            opts["docs"] = False
        elif arg == "--docs-only":
            opts["docs"] = True
            opts["docs_only"] = True
        elif arg == "--changed-only":
            opts["incremental"] = True
        elif arg == "--canonical-reuse":
            opts["canonical_reuse"] = True
        elif arg == "--no-canonical-reuse":
            opts["canonical_reuse"] = False
        elif arg == "--execution-context":
            opts["execution_context"] = True
        elif arg == "--background":
            opts["background"] = True
        elif arg == "--sync":
            opts["sync"] = True
        elif arg == "--await":
            opts["await"] = True
        elif arg == "--timeout":
            i += 1
            try:
                opts["timeout"] = max(0, int(argv[i]))
            except (ValueError, IndexError):
                print(f"Invalid --timeout value: {argv[i] if i < len(argv) else ''}", file=sys.stderr)
                sys.exit(2)
        elif arg == "--silent":
            opts["silent"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--for-llm":
            i += 1
            try:
                value = argv[i]
            except IndexError:
                print("--for-llm requires a value (e.g. --for-llm toon)", file=sys.stderr)
                sys.exit(2)
            if value not in FOR_LLM_FORMATS:
                print(
                    f"Unknown --for-llm format: {value!r} (supported: {', '.join(sorted(FOR_LLM_FORMATS))})",
                    file=sys.stderr,
                )
                sys.exit(2)
            opts["for_llm"] = value
        elif arg == "--tagged":
            opts["tagged"] = True
        elif arg == "--confidence":
            i += 1
            try:
                value = argv[i]
            except IndexError:
                print(f"--confidence requires a value ({', '.join(CONFIDENCE_TAG_ORDER)})", file=sys.stderr)
                sys.exit(2)
            if value not in CONFIDENCE_RANK:
                print(
                    f"Unknown --confidence tag: {value!r} (supported: {', '.join(CONFIDENCE_TAG_ORDER)})",
                    file=sys.stderr,
                )
                sys.exit(2)
            opts["confidence"] = value
            opts["tagged"] = True
        elif arg == "--geometry":
            opts["geometry"] = True
        elif arg == "--path":
            i += 1
            opts["path"] = argv[i]
        elif arg == "--entity-id":
            i += 1
            opts["entity_id"] = argv[i]
        elif arg == "--line":
            i += 1
            opts["line"] = max(1, int(argv[i]))
        elif arg == "--max-lines":
            i += 1
            opts["max_lines"] = max(1, int(argv[i]))
        elif arg == "--max-bytes":
            i += 1
            opts["max_bytes"] = max(1, int(argv[i]))
        elif arg == "--allow-full-content":
            opts["allow_full_content"] = True
        elif arg == "--full-rescan":
            opts["full_rescan"] = True
        elif arg == "--snapshot":
            i += 1
            opts["snapshot"] = argv[i]
        elif arg == "--changed-paths":
            i += 1
            opts["changed_paths"] = [item.replace("\\", "/") for item in argv[i].split(",") if item]
        elif arg == "--clustering-config":
            i += 1
            opts["clustering_config"] = argv[i]
        elif arg == "--verbose":
            opts["verbose"] = True
            opts["silent"] = False
        elif arg in ("-h", "--help"):
            print(HELP_TEXT)
            sys.exit(0)
        elif arg in ("-V", "--version"):
            print(__version__)
            sys.exit(0)
        else:
            print(f"Unknown {command} option: {arg}", file=sys.stderr)
            print("Run `simplicio-mapper --help` for usage.", file=sys.stderr)
            sys.exit(2)
        i += 1
    if (
        _DEFAULT_TOON_ENABLED
        and not opts["json"]
        and not opts["for_llm"]
        and command in DEFAULT_TOON_COMMANDS
    ):
        opts["for_llm"] = "toon"
        opts["_default_for_llm"] = True
    return opts
