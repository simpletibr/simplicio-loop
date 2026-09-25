import sys

from pathlib import Path

import pytest

from benchmarks import issue246_matrix


def test_shape_covers_requested_symbol_size() -> None:
    for requested in (10_000, 100_000, 1_000_000):
        files, functions = issue246_matrix._shape(requested)
        assert files * functions >= requested


def test_matrix_preserves_raw_receipts_and_marks_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int, int, bool]] = []

    def fake_run(
        *,
        files: int,
        functions: int,
        repetitions: int,
        rust_executable: Path | None,
        resident_executable: Path | None,
        compact_symbols: bool,
    ) -> dict[str, object]:
        calls.append((files, functions, repetitions, compact_symbols))
        return {"status": "partial", "scenarios": {"fast": {"status": "blocked"}}}

    monkeypatch.setattr(issue246_matrix, "run_comparison", fake_run)
    receipt = issue246_matrix.run_matrix(sizes=(10_000, 100_000), repetitions=10)

    assert receipt["schema"] == issue246_matrix.SCHEMA
    assert receipt["status"] == "partial"
    assert receipt["repetitions"] == 10
    assert len(receipt["raw_runs"]) == 2
    assert calls == [
        (*issue246_matrix._shape(size), 10, False) for size in (10_000, 100_000)
    ]


def test_matrix_requires_ten_repetitions() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        issue246_matrix.run_matrix(sizes=(10_000,), repetitions=9)


def test_matrix_preserves_comparison_failure_as_blocked_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(**_: object) -> dict[str, object]:
        raise RuntimeError("snapshot_too_large size=550910038")

    monkeypatch.setattr(issue246_matrix, "run_comparison", fail_run)
    receipt = issue246_matrix.run_matrix(sizes=(1_000_000,), repetitions=10)
    cell = receipt["raw_runs"][0]["receipt"]
    assert receipt["status"] == "partial"
    assert cell["status"] == "blocked"
    assert cell["error"]["type"] == "RuntimeError"
    assert "snapshot_too_large" in cell["error"]["message"]


def test_matrix_uses_compact_corpus_only_for_one_million_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compact_values: list[bool] = []

    def fake_run(**kwargs: object) -> dict[str, object]:
        compact_values.append(bool(kwargs["compact_symbols"]))
        return {"status": "partial"}

    monkeypatch.setattr(issue246_matrix, "run_comparison", fake_run)
    issue246_matrix.run_matrix(sizes=(100_000, 1_000_000), repetitions=10)
    assert compact_values == [False, True]


def test_cli_fails_closed_for_partial_matrix(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        issue246_matrix,
        "run_matrix",
        lambda **_: {"schema": issue246_matrix.SCHEMA, "status": "partial"},
    )
    monkeypatch.setattr(sys, "argv", ["issue246_matrix", "--sizes", "10000"])

    assert issue246_matrix.main() == 1
    assert '"status": "partial"' in capsys.readouterr().out
