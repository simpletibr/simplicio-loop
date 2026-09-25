#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.issue208_ac08_report import build_issue208_ac08_report, render_issue208_ac08_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the issue #208 AC08 evidence-conservative report.")
    parser.add_argument("--json", action="store_true", help="Print the JSON report to stdout.")
    parser.add_argument("--write", action="store_true", help="Write docs/issue-208-ac08-evaluation.(md|json).")
    args = parser.parse_args()

    report = build_issue208_ac08_report(ROOT)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_issue208_ac08_markdown(report), end="")

    if args.write:
        docs_dir = ROOT / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "issue-208-ac08-evaluation.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (docs_dir / "issue-208-ac08-evaluation.md").write_text(
            render_issue208_ac08_markdown(report),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
