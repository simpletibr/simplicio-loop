"""Late binding to cli_impl for the command-group modules (#1818).

Tests monkeypatch names on simplicio_loop.cli_impl (and the cli facade forwards to it). A group module
that calls such a name must look it up when it runs, so it reads impl().name at call time.
"""
from __future__ import annotations


def impl():
    from simplicio_loop import cli_impl

    return cli_impl
