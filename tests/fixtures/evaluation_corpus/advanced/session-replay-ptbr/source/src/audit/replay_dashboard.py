def replay_dashboard_row(event):
    return {
        "session_id": event["session_id"],
        "nonce": event["nonce"],
        "token_status": event["token_status"],
    }
