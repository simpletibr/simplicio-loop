#!/usr/bin/env python3
"""Hidden acceptance tests for the hard benchmark set (``--hard``).

This file lives outside ``fixture_hard/`` and is never copied into an arm's
repo, so neither arm can read it. The harness runs it by absolute path with
``cwd`` set to the arm's repo::

    python3 /abs/bench/llm_ab/hidden/check_hard.py --stage N

Stage N checks task N only. Exit 0 and ``PASS: stage N ok`` on success,
exit 1 and one ``FAIL: ...`` line per failed check otherwise.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys


def _fresh(name):
    for key in [k for k in sys.modules if k == name or k.startswith(name + ".") or name.startswith(k + ".")]:
        del sys.modules[key]
    return importlib.import_module(name)


def _raises(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError:
        return True
    except Exception:  # noqa: BLE001 - the wrong exception type is a failure too
        return False
    return False


def stage1(fail):
    order_total = _fresh("pricing").order_total

    def item(price, qty):
        return {"price_cents": price, "qty": qty}

    cases = [
        ([item(1000, 2)], None, 2799, "subtotal plus shipping"),
        ([item(1005, 1)], "PCT10", 1703, "PCT10 rounds 100.5 half up to 101"),
        ([item(1015, 1)], "PCT10", 1712, "PCT10 rounds 101.5 half up to 102"),
        ([item(1004, 1)], "PCT10", 1703, "PCT10 rounds 100.4 down to 100"),
        ([item(2000, 1)], "OFF500", 2299, "OFF500 applies at exactly 2000"),
        ([item(1999, 1)], "OFF500", 2798, "OFF500 does not apply below 2000"),
        ([item(5000, 2)], None, 10000, "free shipping at exactly 10000"),
        ([item(10000, 1)], "OFF500", 9500, "free shipping uses the subtotal before discount"),
        ([item(3000, 4)], "PCT10", 10800, "PCT10 with free shipping"),
        ([], None, 799, "empty order pays shipping"),
        ([item(0, 3)], None, 799, "zero price is allowed"),
    ]
    for items, coupon, expected, label in cases:
        try:
            got = order_total(items, coupon)
        except Exception as exc:  # noqa: BLE001
            fail(f"{label}: raised {type(exc).__name__}")
            continue
        if got != expected or not isinstance(got, int):
            fail(f"{label}: expected {expected}, got {got!r}")
    for items, coupon, label in (
        ([item(100, 0)], None, "qty 0"),
        ([item(100, -1)], None, "negative qty"),
        ([item(-1, 1)], None, "negative price"),
        ([item(100, 1)], "XYZ", "unknown coupon"),
    ):
        if not _raises(order_total, items, coupon):
            fail(f"{label} must raise ValueError")


def stage2(fail):
    Inventory = _fresh("inventory").Inventory
    inv = Inventory()
    inv.add("a", 2)
    inv.add("a", 3)
    if inv.available("a") != 5:
        fail(f"adding to an existing SKU must accumulate: expected 5, got {inv.available('a')}")
    if inv.reserve("a", 5) is not True or inv.available("a") != 0:
        fail("reserving exactly the remaining quantity must succeed and leave 0")
    inv.add("b", 2)
    if inv.reserve("b", 3) is not False or inv.available("b") != 2:
        fail("reserving more than available must return False and change nothing")
    if inv.reserve("zzz", 1) is not False:
        fail("reserving an unknown SKU must return False")
    inv.add("d", 4)
    if inv.reserve("d", 1) is not True or inv.available("d") != 3:
        fail("a partial reservation must succeed and decrement")
    for qty in (0, -1):
        if not _raises(inv.reserve, "d", qty):
            fail(f"reserve qty={qty} must raise ValueError")
    if inv.available("d") != 3:
        fail("a rejected reservation must not change stock")
    if not _raises(inv.add, "c", 0):
        fail("add qty=0 must still raise ValueError")


def stage3(fail):
    try:
        money = _fresh("shop.money")
    except Exception as exc:  # noqa: BLE001
        fail(f"shop/money.py cannot be imported: {type(exc).__name__}")
        return
    report = _fresh("shop.report")
    invoice = _fresh("shop.invoice")
    lines = [
        {"unit_cents": 1999, "qty": 3, "tax_pct": 7},
        {"unit_cents": 250, "qty": 1, "tax_pct": 0},
        {"unit_cents": 333, "qty": 2, "tax_pct": 15},
    ]
    line_total = getattr(money, "line_total", None)
    if not callable(line_total):
        fail("shop.money.line_total is missing")
    else:
        for line, expected in zip(lines, (6417, 250, 766)):
            if line_total(line) != expected:
                fail(f"line_total({line}) expected {expected}, got {line_total(line)!r}")
    if invoice.invoice_total(lines) != 7433:
        fail(f"invoice_total changed: expected 7433, got {invoice.invoice_total(lines)!r}")
    if report.summary(lines) != "3 lines, total 74.33":
        fail(f"summary changed: got {report.summary(lines)!r}")
    for rel in ("shop/report.py", "shop/invoice.py"):
        source = open(rel, encoding="utf-8").read()
        if "line_total" not in source:
            fail(f"{rel} must call line_total")
        if '["tax_pct"]' in source or "['tax_pct']" in source:
            fail(f"{rel} still computes the tax itself")


def stage4(fail):
    parse = _fresh("duration").parse_duration
    for text, expected in (("1h30m", 5400), ("45s", 45), ("2h", 7200), ("1h5s", 3605), ("90m", 5400),
                           ("0s", 0), ("1h2m3s", 3723), ("10m0s", 600)):
        try:
            got = parse(text)
        except Exception as exc:  # noqa: BLE001
            fail(f"parse_duration({text!r}) raised {type(exc).__name__}")
            continue
        if got != expected or not isinstance(got, int):
            fail(f"parse_duration({text!r}) expected {expected}, got {got!r}")
    for text in ("", "1x", "m5", "5m1h", "1h1h", "-5m", "1.5h", "1h 30m", "h", "5", " 1h", "1h30"):
        if not _raises(parse, text):
            fail(f"parse_duration({text!r}) must raise ValueError")


STAGES = {1: stage1, 2: stage2, 3: stage3, 4: stage4}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", type=int, required=True, choices=sorted(STAGES))
    args = parser.parse_args(argv)
    sys.path.insert(0, os.getcwd())
    failures = []
    try:
        STAGES[args.stage](failures.append)
    except Exception as exc:  # noqa: BLE001 - a crash in the code under test is a failure
        failures.append(f"stage {args.stage} crashed: {type(exc).__name__}: {exc}")
    if failures:
        for line in failures:
            print(f"FAIL: {line}")
        return 1
    print(f"PASS: stage {args.stage} ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
