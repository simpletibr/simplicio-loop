"""Harness-owned acceptance checker for the `login.html` benchmark tasks
(``--tasks 4``, task indices 3-4 in ``bench/llm_ab/tasks.py``).

Stdlib only (``html.parser``), mirrors ``check_cadastro.py``'s structure.
The benchmarked model never writes or sees this file's content -- it ships
with the fixture repo before any arm runs, and is used, unmodified, as the
Independent verifier and every quality-lane command
(Unit/Integration/System/Regression/Benchmark) for both login.html tasks.
There is no Python application code in this fixture, so the Coverage lane is
intentionally left undeclared (not applicable) rather than faked.

Stage 1 (task 3, create): ``<form id="login">`` with labeled email/password
inputs and a submit control.
Stage 2 (task 4, edit): stage 1 plus a ``remember`` checkbox inside the form,
and a link to ``cadastro.html`` anywhere on the page (not required to be
inside the form -- it's page navigation to the signup flow, not a form
field).
"""
from __future__ import annotations

import argparse
import sys
from html.parser import HTMLParser
from pathlib import Path

# tests/check_login.py -> repo root -> login.html
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "login.html"


class LoginFieldParser(HTMLParser):
    """Collect every ``<input>``/``<button>`` inside ``<form id="login">``,
    plus every ``<a>`` anywhere in the document (signup link lives outside
    the form)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: list[dict[str, str | None]] = []
        self.buttons: list[dict[str, str | None]] = []
        self.anchors: list[dict[str, str | None]] = []
        self.found_form_login = False
        self._form_depth = 0
        self._in_target_form = False

    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag == "form":
            self._form_depth += 1
            if attrs_d.get("id") == "login":
                self._in_target_form = True
                self.found_form_login = True
        elif tag == "a":
            self.anchors.append(attrs_d)
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


def parse_login(html_text: str) -> LoginFieldParser:
    parser = LoginFieldParser()
    parser.feed(html_text)
    return parser


def _find_input(parser: LoginFieldParser, name: str) -> dict | None:
    for inp in parser.inputs:
        if inp.get("name") == name:
            return inp
    return None


def _has_submit(parser: LoginFieldParser) -> bool:
    for inp in parser.inputs:
        if (inp.get("type") or "").lower() == "submit":
            return True
    for btn in parser.buttons:
        # a <button> with no explicit type defaults to type="submit" per the
        # HTML spec.
        if (btn.get("type") or "submit").lower() == "submit":
            return True
    return False


def _has_cadastro_link(parser: LoginFieldParser) -> bool:
    for a in parser.anchors:
        href = a.get("href") or ""
        if "cadastro.html" in href:
            return True
    return False


def check_stage1(parser: LoginFieldParser) -> list[str]:
    """Return failure reasons for stage 1; an empty list means pass."""
    failures: list[str] = []
    if not parser.found_form_login:
        return ['missing <form id="login">']

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

    if not _has_submit(parser):
        failures.append("missing a submit control in form#login")

    return failures


def check_stage2(parser: LoginFieldParser) -> list[str]:
    """Stage 1 plus the ``remember`` checkbox and the signup link added by
    task 4."""
    failures = check_stage1(parser)

    remember = _find_input(parser, "remember")
    if remember is None:
        failures.append("missing input[name=remember]")
    elif (remember.get("type") or "").lower() != "checkbox":
        failures.append("input[name=remember] must be type=checkbox")

    if not _has_cadastro_link(parser):
        failures.append('missing a link to "cadastro.html" (signup page)')

    return failures


STAGE_CHECKS = {1: check_stage1, 2: check_stage2}


def check_file(path: Path, stage: int) -> list[str]:
    if not path.is_file():
        return [f"{path} does not exist"]
    text = path.read_text(encoding="utf-8", errors="replace")
    return STAGE_CHECKS[stage](parse_login(text))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stage", type=int, choices=sorted(STAGE_CHECKS), required=True,
        help="1: base form (email/password/submit); "
             "2: stage 1 plus a remember checkbox and a cadastro.html link",
    )
    ap.add_argument(
        "--path", default=str(DEFAULT_PATH),
        help="path to login.html (default: repo root, relative to this file)",
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
