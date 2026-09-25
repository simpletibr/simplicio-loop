from __future__ import annotations

from pathlib import Path

import pytest

from simplicio_fast.snapshot import Snapshot, Symbol, _build_v2


@pytest.mark.parametrize("kind", ["test", "property", "attribute"])
def test_snapshot_accepts_parser_symbol_kinds(tmp_path: Path, kind: str) -> None:
    output = tmp_path / "project.sfast"
    symbol = Symbol(
        f"{kind}_example",
        f"{kind}_example",
        kind,
        "tests/test_example.py",
        1,
        1,
        "0" * 64,
    )
    _build_v2(
        [("tests/test_example.py", b"\x00" * 32, 1, (symbol,))],
        (),
        output,
    )
    snapshot = Snapshot(output)
    try:
        assert any(symbol.kind == kind for symbol in snapshot.symbols())
    finally:
        snapshot.close()
