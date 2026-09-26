"""CLI for `simplicio-loop intake` — generic task intake (issue #1312).

Drains a list of work items from any tracker export (JSON/CSV/Markdown, or an
http(s) URL returning JSON) into a `tasks.md` file compatible with
`simplicio-loop prepare`/`wave`. This command handles no credentials: when a
source needs auth, fetch it with the host's own connector/CLI first and pass
the exported file here.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from . import intake


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simplicio-loop intake",
        description=(
            "Normalize a tracker export (JSON array/{items|issues|data|value|nodes: [...]}, "
            "CSV, the existing tasks.md Markdown grammar, or an http(s) URL returning JSON) "
            "into a tasks.md file simplicio-loop prepare/wave can compile. Auto-detects the "
            "common field names of GitHub, Jira, Linear, ClickUp, GitLab and Azure DevOps "
            "exports; --map overrides any field. No credentials are handled here — fetch "
            "an authenticated source with your own connector/CLI first."
        ),
    )
    parser.add_argument(
        "--from", dest="from_arg", required=True, metavar="PATH|URL|-",
        help="tracker export to read: a local .json/.csv/.md file, '-' for stdin, "
             "or an http(s) URL returning JSON",
    )
    parser.add_argument(
        "--map", dest="map_pairs", action="append", default=[], metavar="KEY=PATH",
        help="override a normalized field (id, title, body, labels, depends_on, source, url) "
             "with a dotted source path, e.g. --map title=fields.summary. Repeatable.",
    )
    parser.add_argument("--repo", default=".", help="repository root the output tasks.md belongs to")
    parser.add_argument("--out", default="tasks.md", help="where to write the compiled tasks.md")
    parser.add_argument("--json", action="store_true", help="print a machine-readable per-item summary")
    parser.add_argument(
        "--freeze-backlog", action="store_true",
        help="also freeze the item list into --repo's scripts/task_backlog.py backlog "
             "(skipped with a warning if that script is not present in --repo)",
    )
    parser.add_argument(
        "--goal", default="", help="backlog goal text (only used with --freeze-backlog); "
                                    "defaults to 'Drain N intake item(s)'",
    )
    return parser


def _freeze_backlog(repo: Path, items: list, tasks_md_path: str, goal: str) -> dict:
    script = repo / "scripts" / "task_backlog.py"
    if not script.is_file():
        return {"attempted": False, "reason": "scripts/task_backlog.py not found in --repo"}
    backlog_items = intake.build_backlog_items(items, tasks_md_path)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(backlog_items, handle)
        item_file = handle.name
    try:
        result = subprocess.run(
            [
                sys.executable, str(script), "init",
                "--goal", goal or f"Drain {len(items)} intake item(s)",
                "--item-file", item_file,
            ],
            cwd=str(repo), capture_output=True, text=True, check=False,
        )
    finally:
        try:
            os.unlink(item_file)
        except OSError:
            pass
    return {
        "attempted": True,
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        raw, kind = intake.read_source(args.from_arg)
        field_map = intake.parse_field_map(args.map_pairs)
        items = intake.normalize(raw, kind, field_map=field_map)
        rendered = intake.render_tasks_markdown(items)
    except intake.IntakeError as exc:
        print(
            json.dumps({"schema": intake.SCHEMA, "status": "error", "reason_code": exc.reason_code,
                        "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2

    repo = Path(args.repo).resolve()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")

    backlog_result = None
    if args.freeze_backlog:
        backlog_result = _freeze_backlog(repo, items, str(out_path), args.goal)

    id_to_index = {item["id"]: idx for idx, item in enumerate(items, start=1) if item.get("id")}
    summary_items = []
    for index, item in enumerate(items, start=1):
        summary_items.append(
            {
                "task_index": index,
                "id": item.get("id"),
                "title": item.get("title"),
                "source": item.get("source"),
                "url": item.get("url"),
                "depends_on": item.get("depends_on"),
                "depends_on_task_index": [
                    id_to_index[dep] for dep in item.get("depends_on") or [] if dep in id_to_index
                ],
            }
        )
    summary = {
        "schema": intake.SCHEMA,
        "status": "ok",
        "out": str(out_path),
        "item_count": len(items),
        "items": summary_items,
    }
    if backlog_result is not None:
        summary["backlog"] = backlog_result

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"simplicio-loop intake wrote {out_path} ({len(items)} item(s))")
        for row in summary_items:
            deps = f" depends_on task {row['depends_on_task_index']}" if row["depends_on_task_index"] else ""
            print(f"  [task {row['task_index']}] {row['id']}: {row['title']}{deps}")
        if backlog_result is not None:
            if backlog_result.get("attempted"):
                print(f"  backlog: exit={backlog_result['exit_code']} {backlog_result['stdout']}")
            else:
                print(f"  backlog: skipped ({backlog_result['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
