from src.modeling.sort_lines import sort_lines


def test_sort_lines_is_deterministic():
    rows = [
        {"tipo": "temporal", "inicio": "2024-02-01", "nome": "T1"},
        {"tipo": "estrutural", "inicio": "2024-01-01", "nome": "E1"},
    ]
    assert [row["nome"] for row in sort_lines(rows)] == ["E1", "T1"]
