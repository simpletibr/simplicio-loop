"""Tiny Python fixture for the context-pack tests."""


def load_user(user_id: int) -> dict:
    return {"id": user_id, "name": f"user-{user_id}"}
