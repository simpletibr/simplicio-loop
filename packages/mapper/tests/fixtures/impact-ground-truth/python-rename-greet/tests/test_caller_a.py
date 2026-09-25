from src.caller_a import announce


def test_announce():
    assert announce("x") == "HELLO, X!"
