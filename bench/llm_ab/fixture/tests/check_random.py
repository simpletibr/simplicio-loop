"""Harness checker for tasks drawn by ``bench.llm_ab.random_tasks``.

``--stage N`` reads ``tests/random_spec.json`` and checks that page. The
model does not write this checker or the spec.
"""
from __future__ import annotations

import argparse
import json
import sys
from html.parser import HTMLParser
from pathlib import Path


class FormParser(HTMLParser):
    def __init__(self, form_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.form_id = form_id
        self.in_form = False
        self.depth = 0
        self.found_form = False
        self.inputs: list[dict[str, str | None]] = []
        self.buttons: list[dict[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        attr = {key: value for key, value in attrs}
        if tag == "form":
            if (attr.get("id") or "") == self.form_id:
                self.found_form = True
                self.in_form = True
                self.depth = 1
            elif self.in_form:
                self.depth += 1
            return
        if not self.in_form:
            return
        if tag == "input":
            self.inputs.append(attr)
        elif tag == "button":
            self.buttons.append(attr)

    def handle_endtag(self, tag):
        if tag == "form" and self.in_form:
            self.depth -= 1
            if self.depth <= 0:
                self.in_form = False


def load_spec(spec_path: Path) -> list[dict]:
    return json.loads(spec_path.read_text(encoding="utf-8"))


def check(path: Path, stage: int, spec: list[dict]) -> list[str]:
    item = next(row for row in spec if int(row["stage"]) == stage)
    page = str(item["id"])
    if not path.is_file():
        return [f"FAIL: missing {page}.html"]
    parser = FormParser(page)
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    errors: list[str] = []
    if not parser.found_form:
        errors.append(f'FAIL: missing form id="{page}"')
    wanted = [
        field for field in parser.inputs
        if (field.get("name") or "") == item["name"]
        and (field.get("type") or "").lower() == str(item["type"]).lower()
        and "required" in field
    ]
    if not wanted:
        errors.append(
            f"FAIL: missing required input name={item['name']} type={item['type']}"
        )
    submit = [
        field for field in parser.inputs
        if (field.get("type") or "").lower() == "submit"
    ] or parser.buttons
    if not submit:
        errors.append("FAIL: missing submit control")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--path", default=None)
    parser.add_argument("--spec", default=None)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    spec_path = Path(args.spec) if args.spec else Path(__file__).resolve().parent / "random_spec.json"
    spec = load_spec(spec_path)
    item = next(row for row in spec if int(row["stage"]) == args.stage)
    target = Path(args.path) if args.path else root / f"{item['id']}.html"
    errors = check(target, args.stage, spec)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"PASS: stage {args.stage} ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
