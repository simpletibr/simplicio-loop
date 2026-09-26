#!/usr/bin/env python3
"""Standalone no-internal-JSON scanner for Python repositories.

It mirrors the Runtime crate's v1 policy contract using only Python's standard
library. Output is Markdown plus one HBP evidence row; no JSON report exists.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 development environment
    import tomli as tomllib  # type: ignore[no-redef]

PATTERNS = (
    ("serialization-library", "import json"),
    ("serialization-library", "from json"),
    ("serialization-library", "serde_json"),
    ("serialization-library", "orjson"),
    ("serialization-call", "json.dumps"),
    ("serialization-call", "json.loads"),
    ("serialization-call", "JSON.parse"),
    ("serialization-call", "JSON.stringify"),
    ("protocol", "JSON-RPC"),
    ("protocol", "json-rpc"),
)
IGNORED = {".git", "target", "node_modules", "vendor", ".venv", ".simplicio-loop"}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXCEPTION_CATEGORIES = {
    "external-adapter",
    "historical-documentation",
    "legacy-internal",
    "scanner-self",
    "toolchain-mandated",
}
MAX_TEXT_BYTES = 4 * 1024 * 1024


def load_policy(path: Path, today: str) -> dict:
    try:
        today_date = dt.date.fromisoformat(today)
    except ValueError as error:
        raise ValueError(f"invalid scan date: {today}") from error
    policy = tomllib.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema") != "simplicio.no-internal-json/v1" or policy.get("version") != 1:
        raise ValueError("unsupported policy schema/version")
    if not policy.get("scanner_version"):
        raise ValueError("scanner_version is required")
    seen = set()
    for exception in policy.get("exceptions", []):
        required = (
            "path",
            "category",
            "owner",
            "external_dependency",
            "justification",
            "review_date",
            "removal_date",
        )
        if any(not exception.get(key) for key in required):
            raise ValueError("exception has a missing required field")
        path_value = exception["path"]
        if (
            path_value in seen
            or path_value.startswith("/")
            or ".." in Path(path_value).parts
            or "\\" in path_value
            or any(c in path_value for c in "*?[]")
        ):
            raise ValueError(f"exception path is not exact: {path_value}")
        if exception["category"] not in EXCEPTION_CATEGORIES:
            raise ValueError(f"unsupported exception category: {exception['category']}")
        seen.add(path_value)
        if not DATE.fullmatch(exception["review_date"]) or not DATE.fullmatch(exception["removal_date"]):
            raise ValueError(f"invalid exception dates: {path_value}")
        try:
            review_date = dt.date.fromisoformat(exception["review_date"])
            removal_date = dt.date.fromisoformat(exception["removal_date"])
        except ValueError as error:
            raise ValueError(f"invalid exception dates: {path_value}") from error
        if review_date > today_date or removal_date < review_date:
            raise ValueError(f"invalid exception date window: {path_value}")
        if removal_date < today_date:
            raise ValueError(f"expired exception: {path_value}")
    return policy


def scan(root: Path, policy: dict) -> list[tuple[str, int, str, str, str]]:
    exceptions = {item["path"]: item["category"] for item in policy.get("exceptions", [])}
    findings = []
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in IGNORED and not name.startswith("."))
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            category = exceptions.get(relative, "unclassified")
            suffix = path.suffix.lower()
            if suffix in {".json", ".jsonl", ".ndjson"}:
                findings.append((relative, 1, "artifact-extension", suffix[1:], category))
            try:
                if path.is_symlink():
                    findings.append((relative, 1, "symlink", "not-followed", category))
                    continue
                size = path.stat().st_size
                if size > MAX_TEXT_BYTES:
                    findings.append((relative, 1, "oversized-text", f"{size}-bytes", category))
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            if b"\0" in data:
                continue
            if len(data) > MAX_TEXT_BYTES:
                findings.append((relative, 1, "oversized-text", f"{len(data)}-bytes", category))
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            trimmed = text.strip()
            if suffix not in {".json", ".jsonl", ".ndjson"}:
                if trimmed.startswith("{") and trimmed.endswith("}"):
                    findings.append((relative, 1, "renamed-json-artifact", "object-document", category))
                elif trimmed.startswith("[") and trimmed.endswith("]"):
                    findings.append((relative, 1, "renamed-json-artifact", "array-document", category))
            for line_number, line in enumerate(text.splitlines(), 1):
                for kind, needle in PATTERNS:
                    if needle in line:
                        findings.append((relative, line_number, kind, needle, category))
    used_exceptions = {item[0] for item in findings if item[4] != "unclassified"}
    for exception_path in sorted(set(exceptions) - used_exceptions):
        findings.append((exception_path, 1, "unused-exception", "no-matching-finding", "unclassified"))
    return sorted(set(findings))


def render(findings: list[tuple[str, int, str, str, str]], policy: dict, mode: str) -> tuple[str, str, int]:
    unclassified = sum(item[4] == "unclassified" for item in findings)
    status = "FAIL" if mode == "strict" and unclassified else ("UNVERIFIED" if unclassified else "PASS")
    lines = [
        "# No-internal-JSON policy scan",
        "",
        f"- status: `{status}`",
        f"- mode: `{mode}`",
        f"- scanner_version: `{policy['scanner_version']}`",
        f"- findings: `{len(findings)}`",
        f"- unclassified: `{unclassified}`",
        "",
        "## Findings",
        "",
        "| Path | Line | Kind | Classification | Evidence |",
        "| --- | ---: | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{path}` | {line} | `{kind}` | `{category}` | `{evidence}` |"
        for path, line, kind, evidence, category in findings
    )
    markdown = "\n".join(lines) + "\n"
    payload = (
        f"mode={mode};status={status};policy_version={policy['version']};"
        f"scanner_version={policy['scanner_version']};findings={len(findings)};"
        f"unclassified={unclassified}"
    )
    fields = ("0", "genesis", "policy-scan", payload, "policy-scanner:" + policy["scanner_version"])
    digest = hashlib.sha256(
        b"".join(len(field).to_bytes(8, "little") + field.encode() for field in fields)
        + (0).to_bytes(8, "little")
    ).hexdigest()
    hbp = (
        "schema=simplicio.hbp/v1\nversion=1.0.0\nseq=0\nprev_hash=genesis\n"
        f"topic=policy-scan\npayload={payload}\nprovenance={fields[-1]}\nhash={digest}\n"
    )
    return markdown, hbp, 1 if status == "FAIL" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--mode", choices=("baseline", "strict"), default="baseline")
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--hbp", type=Path)
    args = parser.parse_args(argv)
    today = os.environ.get("SIMPLICIO_POLICY_SCAN_DATE", dt.date.today().isoformat())
    policy_path = args.policy or args.repo / "policy/no-internal-json.toml"
    policy = load_policy(policy_path, today)
    markdown, hbp, code = render(scan(args.repo, policy), policy, args.mode)
    if args.markdown:
        args.markdown.write_text(markdown, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(markdown)
    if args.hbp:
        args.hbp.write_text(hbp, encoding="utf-8", newline="\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
