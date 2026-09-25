from benchmarks.bench_parser_legacy_parity_244 import run


def test_frozen_python_adapter_matches_legacy_symbols_relations_and_hashes() -> None:
    receipt = run()
    assert receipt["status"] == "pass"
    assert receipt["adapter"]["byte_identical_rebuild"] is True
    assert receipt["parity"] == {"symbols": True, "relations": True, "source_hashes": True}
    assert receipt["python_cases"][0]["symbols"] == 6
    assert receipt["python_cases"][0]["relations"] == 27
    assert receipt["native_languages"]["status"] == "partial"
