import pytest

from simplicio_loop import input_ceiling as ic


# --- pins the estimator constants and kills the mutants that survived the first review (#1613 audit)
def test_scaled_estimate_rounds_up():
    assert ic.estimate_tokens("a") == 1
    assert ic.Projection.estimated("a").tokens == 2  # ceil(1 * 1.20), never 1


def test_env_ceiling_with_trailing_newline_is_invalid():
    with pytest.raises(ic.CeilingConfigError):
        ic.resolve_ceiling("/nonexistent", {ic.ENV_NAME: "98000\n"})


def test_a_lone_newline_costs_a_token():
    assert ic.estimate_tokens("\n") == 1
    assert ic.estimate_tokens("a\nb") == 3


@pytest.mark.parametrize("text,tokens", [
    ("\x1b" * 4, 6), ("\x00" * 4, 6), ("\x0e" * 4, 6), ("\x7f" * 4, 4),   # control characters cost 1.5 tokens each
    ("α" * 4, 4), ("é" * 4, 3),                                          # Greek and up: 1 token; Latin accents: 0.75
    ("hello", 1), ("children", 2), ("implementation", 5),                # words
    ("string", 5), ("bcdfgh", 5), ("bcdfaeio", 6), ("aBcDeF", 5),        # strings that do not read as words cost more
    ("ABCDEFGHIJ", 7), ("bcdfghjklmnpq", 10),
])
def test_estimator_pins_each_character_class(text, tokens):
    assert ic.estimate_tokens(text) == tokens
