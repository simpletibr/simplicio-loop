def accept_session_nonce(state, nonce):
    if nonce in state["used_nonces"]:
        return False
    state["used_nonces"].add(nonce)
    return True
