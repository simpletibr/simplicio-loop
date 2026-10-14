"""Automatic review gate of the squad (#1649, part of #1649): the mechanical part of a PR review, deterministic and measured.

`model` is the contract (CheckResult, GateReport, Level); `diffs` reads a PR diff; each check is one module
(`redgreen`, `mutation`, `usage`, `coverage`, `docs`, `identity`) and `gate` runs them and writes the report.
"""
