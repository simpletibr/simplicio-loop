from backend.server import handle_request


def test_health():
    assert handle_request("/health") == "ok"
