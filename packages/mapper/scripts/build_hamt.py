#!/usr/bin/env python3
"""Build a YOOL/HAMT agent catalog from AGENTS.md.

This script is stdlib-only by design so the Node wrapper can vendor it into
projects without adding Python dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

BRANCH_BITS = 5
BRANCH_FACTOR = 1 << BRANCH_BITS
MAX_LEVELS = 6
HEADING_RE = re.compile(r"^###\s+(?P<name>.+?)\s*$")
FIELD_RE = re.compile(r"^-\s+(?P<key>[a-zA-Z_][\w-]*)\s*:\s*(?P<value>.*)$")
INDENT_FIELD_RE = re.compile(r"^\s{2,}(?P<key>[a-zA-Z_][\w-]*)\s*:\s*(?P<value>.*)$")


@dataclass
class Leaf:
    key: str
    value: dict[str, Any]
    hash_value: int


def yool_hash(name: str) -> int:
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & ((1 << (BRANCH_BITS * MAX_LEVELS)) - 1)


def hash_hex(name: str) -> str:
    return hashlib.blake2b(name.encode("utf-8"), digest_size=8).hexdigest()


def slot_path(hash_value: int) -> list[int]:
    mask = BRANCH_FACTOR - 1
    return [
        (hash_value >> ((MAX_LEVELS - 1 - level) * BRANCH_BITS)) & mask
        for level in range(MAX_LEVELS)
    ]


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        value = value[1:-1]
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        return value[1:-1]
    if value.startswith("'") and value.endswith("'") and len(value) >= 2:
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value.replace("'", '"'))
        except json.JSONDecodeError:
            parts = [item.strip().strip("`").strip("'").strip('"') for item in value[1:-1].split(",")]
            return [item for item in parts if item]
    return value


def heading_anchor(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "agent"


def parse_agent_terms(lines: list[str], start_index: int) -> tuple[dict[str, Any], int]:
    terms: dict[str, Any] = {}
    index = start_index
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("### "):
            break
        if line.startswith("- "):
            break
        match = INDENT_FIELD_RE.match(line)
        if not match:
            break
        terms[match.group("key")] = parse_scalar(match.group("value"))
        index += 1
    return terms, index


def parse_agents(markdown: str, source_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lines = markdown.splitlines()
    parsed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    current_name: str | None = None
    current: dict[str, Any] | None = None
    heading_line = 0
    index = 0

    def finalize() -> None:
        nonlocal current_name, current, heading_line
        if not current_name or current is None:
            return
        required = ["yool_id", "authority", "lane", "agent_terms"]
        missing = [field for field in required if not current.get(field)]
        entry = {
            "name": current_name,
            "source": {"file": source_name, "line": heading_line, "anchor": heading_anchor(current_name)},
            **current,
        }
        if missing:
            skipped.append({"name": current_name, "missing": missing, "line": heading_line})
        else:
            parsed.append(entry)
        current_name = None
        current = None
        heading_line = 0

    while index < len(lines):
        line = lines[index]
        heading = HEADING_RE.match(line)
        if heading:
            finalize()
            current_name = heading.group("name").strip()
            current = {}
            heading_line = index + 1
            index += 1
            continue
        if current is None:
            index += 1
            continue
        field_match = FIELD_RE.match(line)
        if field_match:
            key = field_match.group("key")
            raw_value = field_match.group("value")
            if key == "agent_terms":
                terms, index = parse_agent_terms(lines, index + 1)
                current[key] = terms
                continue
            current[key] = parse_scalar(raw_value)
        index += 1

    finalize()
    return parsed, skipped


def blank_node() -> dict[str, Any]:
    return {"bitmap": 0, "children": {}}


def insert_leaf(root: dict[str, Any], leaf: Leaf, level: int = 0) -> None:
    if level >= MAX_LEVELS:
        slot = leaf.hash_value & (BRANCH_FACTOR - 1)
        children = root["children"]
        existing = children.get(str(slot))
        if existing is None:
            root["bitmap"] |= 1 << slot
            children[str(slot)] = {
                "kind": "collision",
                "hash_prefix": f"{leaf.hash_value:08x}",
                "leaves": [leaf.value],
            }
            return
        if existing["kind"] == "collision":
            existing["leaves"].append(leaf.value)
            return
        raise RuntimeError("unexpected non-collision node at max depth")

    slot = slot_path(leaf.hash_value)[level]
    children = root["children"]
    key = str(slot)
    existing = children.get(key)

    if existing is None:
        root["bitmap"] |= 1 << slot
        children[key] = {"kind": "leaf", "entry": leaf.value}
        return

    if existing["kind"] == "leaf":
        prior_entry = existing["entry"]
        if prior_entry["yool_id"] == leaf.key:
            existing["entry"] = leaf.value
            return
        subnode = blank_node()
        insert_leaf(subnode, Leaf(prior_entry["yool_id"], prior_entry, yool_hash(prior_entry["yool_id"])), level + 1)
        insert_leaf(subnode, leaf, level + 1)
        children[key] = {"kind": "node", **subnode}
        return

    if existing["kind"] == "node":
        insert_leaf(existing, leaf, level + 1)
        return

    if existing["kind"] == "collision":
        existing["leaves"].append(leaf.value)
        return

    raise RuntimeError(f"unknown HAMT node kind: {existing['kind']}")


def build_catalog(entries: list[dict[str, Any]], source_file: pathlib.Path) -> dict[str, Any]:
    root = blank_node()
    leaves: list[dict[str, Any]] = []

    for entry in entries:
        hash_value = yool_hash(entry["yool_id"])
        leaf = {
            **entry,
            "hash": {
                "algorithm": "blake2b-64-truncated-30",
                "hex": hash_hex(entry["yool_id"]),
                "value": hash_value,
                "slots": slot_path(hash_value),
            },
        }
        leaves.append(leaf)
        insert_leaf(root, Leaf(entry["yool_id"], leaf, hash_value))

    payload = {
        "schema": "yool-catalog/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source_file),
        "entries": sorted(leaves, key=lambda item: item["yool_id"]),
        "hamt": {
            "algorithm": "hamt/blake2b-30/v1",
            "branch_bits": BRANCH_BITS,
            "branch_factor": BRANCH_FACTOR,
            "max_levels": MAX_LEVELS,
            "root": root,
        },
    }
    payload["id"] = "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    payload["stats"] = {
        "entries": len(leaves),
        "root_popcount": root["bitmap"].bit_count(),
    }
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a HAMT catalog from AGENTS.md")
    parser.add_argument("project_root", nargs="?", default=".", help="Project root used to resolve defaults")
    parser.add_argument("--source", help="Path to AGENTS.md")
    parser.add_argument("--output", help="Path to output catalog JSON")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    project_root = pathlib.Path(args.project_root).resolve()
    source_file = pathlib.Path(args.source).resolve() if args.source else project_root / "AGENTS.md"
    output_file = pathlib.Path(args.output).resolve() if args.output else project_root / ".catalog" / "agents.json"

    if not source_file.exists():
        print(f"[build] AGENTS source not found: {source_file}", file=sys.stderr)
        return 2

    parsed, skipped = parse_agents(source_file.read_text(encoding="utf-8"), source_file.name)
    catalog = build_catalog(parsed, source_file)
    catalog["stats"]["parsed_agents"] = len(parsed)
    catalog["stats"]["skipped_agents"] = len(skipped)
    if skipped:
        catalog["skipped"] = skipped

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[build] parsed {len(parsed)} agent(s) from {source_file.name}")
    if skipped:
        print(f"[build] skipped {len(skipped)} incomplete agent(s)")
    print(f"[build] wrote {output_file}")
    print(f"[build] root popcount: {catalog['stats']['root_popcount']}/{BRANCH_FACTOR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
