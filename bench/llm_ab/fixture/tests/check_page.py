"""Harness-owned checker for the 10-task turbo pages.

``--stage N`` checks ``pNN.html`` (N from 1 to 10). The model never writes
this file. Stdlib ``html.parser`` only.
"""
from __future__ import annotations

import argparse
import sys
from html.parser import HTMLParser
from pathlib import Path


class PageParser(HTMLParser):
    def __init__(self, form_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.form_id = form_id
        self.in_form = False
        self.form_depth = 0
        self.found_form = False
        self.inputs: list[dict[str, str | None]] = []
        self.buttons: list[dict[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        attr = {k: v for k, v in attrs}
        if tag == "form":
            if (attr.get("id") or "") == self.form_id:
                self.found_form = True
                self.in_form = True
                self.form_depth = 1
            elif self.in_form:
                self.form_depth += 1
            return
        if not self.in_form:
            return
        if tag == "input":
            self.inputs.append(attr)
        elif tag == "button":
            self.buttons.append(attr)

    def handle_endtag(self, tag):
        if tag == "form" and self.in_form:
            self.form_depth -= 1
            if self.form_depth <= 0:
                self.in_form = False


def page_id(stage: int) -> str:
    return f"p{stage:02d}"


def check(path: Path, stage: int) -> list[str]:
    pid = page_id(stage)
    if not path.is_file():
        return [f"FAIL: missing {path.name}"]
    parser = PageParser(pid)
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    errors = []
    if not parser.found_form:
        errors.append(f'FAIL: missing form id="{pid}"')
    email = [
        item for item in parser.inputs
        if (item.get("name") or "") == "email"
        and (item.get("type") or "").lower() == "email"
        and "required" in item
    ]
    if not email:
        errors.append("FAIL: missing required email input name=email type=email")
    submit = [
        item for item in parser.inputs
        if (item.get("type") or "").lower() == "submit"
    ] or parser.buttons
    if not submit:
        errors.append("FAIL: missing submit control")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--path", default=None)
    args = parser.parse_args(argv)
    target = Path(args.path) if args.path else Path(__file__).resolve().parent.parent / f"{page_id(args.stage)}.html"
    errors = check(target, args.stage)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"PASS: stage {args.stage} ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
