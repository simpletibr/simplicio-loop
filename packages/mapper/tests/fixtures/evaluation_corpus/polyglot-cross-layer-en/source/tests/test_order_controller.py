from src.api.order_controller import normalize_checkout


def test_normalize_checkout() -> None:
    payload = normalize_checkout({"total": 104.5, "discount": 5})
    assert payload["total"] == 104.5
    assert payload["discount"] == 5.0
