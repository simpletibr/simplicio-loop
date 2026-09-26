"""Harness-owned acceptance checker for the `cadastro.html` benchmark tasks.

Stdlib only (``html.parser``). The benchmarked model never writes or sees
this file's content -- it ships with the fixture repo before any arm runs,
and is used, unmodified, as the Independent verifier and every quality-lane
command (Unit/Integration/System/Regression/Benchmark) for both benchmark
tasks in ``bench/llm_ab/tasks.py``. There is no Python application code in
this fixture, so the Coverage lane is intentionally left undeclared (not
applicable) rather than faked.

Stage 1 (task 1, create): ``<form id="cadastro">`` with labeled
name/email/password inputs and a submit control.
Stage 2 (task 2, edit): stage 1 plus a phone field and a password_confirm
field, with the original three fields still present.
"""
from __future__ import annotations

import argparse
import sys
from html.parser import HTMLParser
from pathlib import Path

# tests/check_cadastro.py -> repo root -> cadastro.html
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "cadastro.html"


class FormFieldParser(HTMLParser):
    """Collect every ``<input>``/``<button>`` inside ``<form id="cadastro">``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: list[dict[str, str | None]] = []
        self.buttons: list[dict[str, str | None]] = []
        self.found_form_cadastro = False
        self._form_depth = 0
        self._in_target_form = False

    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag == "form":
            self._form_depth += 1
            if attrs_d.get("id") == "cadastro":
                self._in_target_form = True
                self.found_form_cadastro = True
        elif self._in_target_form and tag == "input":
            self.inputs.append(attrs_d)
        elif self._in_target_form and tag == "button":
            self.buttons.append(attrs_d)

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        # self-closed tags, e.g. <input .../>
        self._start(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._form_depth:
            self._form_depth -= 1
            if self._form_depth == 0:
                self._in_target_form = False


def parse_cadastro(html_text: str) -> FormFieldParser:
    parser = FormFieldParser()
    parser.feed(html_text)
    return parser


def _find_input(parser: FormFieldParser, name: str) -> dict | None:
    for inp in parser.inputs:
        if inp.get("name") == name:
            return inp
    return None


def _has_submit(parser: FormFieldParser) -> bool:
    for inp in parser.inputs:
        if (inp.get("type") or "").lower() == "submit":
            return True
    for btn in parser.buttons:
        # a <button> with no explicit type defaults to type="submit" per the
        # HTML spec.
        if (btn.get("type") or "submit").lower() == "submit":
            return True
    return False


def check_stage1(parser: FormFieldParser) -> list[str]:
    """Return failure reasons for stage 1; an empty list means pass."""
    failures: list[str] = []
    if not parser.found_form_cadastro:
        return ['missing <form id="cadastro">']

    name = _find_input(parser, "name")
    if name is None:
        failures.append("missing input[name=name]")
    else:
        if (name.get("type") or "text").lower() != "text":
            failures.append("input[name=name] must be type=text (or omitted)")
        if "required" not in name:
            failures.append("input[name=name] must be required")

    email = _find_input(parser, "email")
    if email is None:
        failures.append("missing input[name=email]")
    else:
        if (email.get("type") or "").lower() != "email":
            failures.append("input[name=email] must be type=email")
        if "required" not in email:
            failures.append("input[name=email] must be required")

    password = _find_input(parser, "password")
    if password is None:
        failures.append("missing input[name=password]")
    else:
        if (password.get("type") or "").lower() != "password":
            failures.append("input[name=password] must be type=password")
        if "required" not in password:
            failures.append("input[name=password] must be required")
        if password.get("minlength") != "8":
            failures.append('input[name=password] must have minlength="8"')

    if not _has_submit(parser):
        failures.append("missing a submit control in form#cadastro")

    return failures


def check_stage2(parser: FormFieldParser) -> list[str]:
    """Stage 1 plus the phone + password_confirm fields added by task 2."""
    failures = check_stage1(parser)

    phone = _find_input(parser, "phone")
    if phone is None:
        failures.append("missing input[name=phone]")
    elif (phone.get("type") or "").lower() != "tel":
        failures.append("input[name=phone] must be type=tel")

    confirm = _find_input(parser, "password_confirm")
    if confirm is None:
        failures.append("missing input[name=password_confirm]")
    else:
        if (confirm.get("type") or "").lower() != "password":
            failures.append("input[name=password_confirm] must be type=password")
        if "required" not in confirm:
            failures.append("input[name=password_confirm] must be required")
        if confirm.get("minlength") != "8":
            failures.append('input[name=password_confirm] must have minlength="8"')

    return failures


STAGE_CHECKS = {1: check_stage1, 2: check_stage2}


def check_file(path: Path, stage: int) -> list[str]:
    if not path.is_file():
        return [f"{path} does not exist"]
    text = path.read_text(encoding="utf-8", errors="replace")
    return STAGE_CHECKS[stage](parse_cadastro(text))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stage", type=int, choices=sorted(STAGE_CHECKS), required=True,
        help="1: base form (name/email/password/submit); "
             "2: stage 1 plus phone + password_confirm",
    )
    ap.add_argument(
        "--path", default=str(DEFAULT_PATH),
        help="path to cadastro.html (default: repo root, relative to this file)",
    )
    args = ap.parse_args(argv)

    failures = check_file(Path(args.path), args.stage)
    if failures:
        for reason in failures:
            print(f"FAIL: {reason}", file=sys.stderr)
        return 1
    print(f"PASS: stage {args.stage} ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
