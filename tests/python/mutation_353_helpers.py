def plan(key="k"):
    return {
        "schema": "simplicio.mechanical-plan/v1",
        "plan_id": "p",
        "source_hash": "s",
        "idempotency_key": key,
        "effect_set": ["write"],
        "operations": [{"path": "app.py"}],
        "hookwall_pre": {"verdict": "proceed", "plan_id": "p"},
    }
