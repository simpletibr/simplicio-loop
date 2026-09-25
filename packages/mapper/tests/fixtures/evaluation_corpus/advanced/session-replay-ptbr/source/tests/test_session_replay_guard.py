from src.security.session_replay_guard import accept_session_nonce


def test_accept_session_nonce_rejects_replay():
    state = {"used_nonces": {"n-1"}}
    assert accept_session_nonce(state, "n-1") is False
    assert accept_session_nonce(state, "n-2") is True
