from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence

from .. import __version__
from ._shared import CONFIDENCE_RANK, CONFIDENCE_TAG_ORDER, FOR_LLM_FORMATS, HELP_TEXT


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
        "command": "map",
        "against": "",
        "target": "",
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
        "for_llm": "",
        "tagged": False,
        "confidence": "",
        "geometry": False,
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
        "endpoints",
        "screens",
        "flowchart",
        "docs",
        "export-docs",
        "flows",
        "sync",
        "history",
        "diff",
        "ask",
        "business",
        "survey",
        "drift",
    )
    command = argv[0] if argv and argv[0] in commands else "map"
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
        elif command in (
            "index",
            "macro",
            "scan",
            "status",
            "inspect",
            "handoff",
            "endpoints",
            "screens",
            "flowchart",
            "docs",
            "export-docs",
            "flows",
            "sync",
            "history",
            "diff",
            "business",
            "survey",
            "drift",
        ) and not arg.startswith("-"):
            opts["root"] = arg
        elif arg == "--against":
            i += 1
            opts["against"] = argv[i]
        elif arg == "--target":
            i += 1
            opts["target"] = argv[i]
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
    return opts
