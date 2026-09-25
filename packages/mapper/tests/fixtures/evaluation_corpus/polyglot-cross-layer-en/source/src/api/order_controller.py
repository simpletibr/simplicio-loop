from __future__ import annotations


def normalize_checkout(payload: dict[str, float]) -> dict[str, float]:
    total = round(float(payload["total"]), 2)
    discount = round(float(payload["discount"]), 2)
    return {"total": total, "discount": discount}
