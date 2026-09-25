from src.modeling.sort_lines import sort_lines


def test_sort_lines_is_deterministic():
    # ordenacao estrutural temporal modelagem por data de inicio
    assert sort_lines([]) == []
