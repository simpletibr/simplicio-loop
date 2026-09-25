import random
import string

from simplicio_fast.parser_adapter import ParserAdapterError, validate_payload


def _random_value(rng: random.Random, depth: int = 0) -> object:
    if depth > 2:
        return rng.choice([None, True, False, 0, 1, "x", [], {}])
    return rng.choice(
        [
            None,
            True,
            False,
            rng.randint(-3, 3),
            "".join(rng.choice(string.printable) for _ in range(rng.randint(0, 8))),
            [_random_value(rng, depth + 1) for _ in range(rng.randint(0, 3))],
            {
                str(rng.randint(0, 4)): _random_value(rng, depth + 1)
                for _ in range(rng.randint(0, 3))
            },
        ]
    )


def test_validator_rejects_random_malformed_payloads_without_unexpected_errors() -> None:
    rng = random.Random(244)
    unexpected: list[str] = []
    rejected = 0
    for _ in range(5_000):
        candidate = _random_value(rng)
        if not isinstance(candidate, dict):
            candidate = {"malformed": candidate}
        try:
            validate_payload(candidate)
        except ParserAdapterError:
            rejected += 1
        except Exception as error:  # pragma: no cover - failure diagnostic
            unexpected.append(type(error).__name__)
    assert rejected == 5_000
    assert unexpected == []
