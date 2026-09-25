"""Tiny fixture module used by the tests/contracts suite.

Deliberately trivial: the contract tests exercise the mapper/pipeline/CLI
wiring, not this module's own logic.
"""


def greet(name: str) -> str:
    return f"hello, {name}"
