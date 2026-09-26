"""Mapper receipt normalization (runtime issue #3853)."""
from __future__ import annotations

from typing import Any, Mapping


def normalize_mapper_index_receipt(
    receipt: Mapping[str, Any],
    *,
    repo: str,
    content_hash,
    valid_receipt,
) -> dict[str, Any]:
    """Accept nested or flat simplicio.mapper-index/v1 as a verifiable receipt."""
    if valid_receipt(receipt, "simplicio.mapper-receipt/v1") and receipt.get("verified") is True:
        generation = str(receipt.get("generation") or "")
        if not generation or receipt.get("repo") != str(repo):
            raise RuntimeError("Mapper receipt is not bound to repo/generation")
        return {"verified": True, "generation": generation, "receipt": dict(receipt)}

    result = receipt.get("result")
    if not isinstance(result, Mapping) or not isinstance(result.get("paths"), Mapping):
        if (
            receipt.get("schema") == "simplicio.mapper-index/v1"
            and receipt.get("status") in {"updated", "unchanged", "skipped"}
            and isinstance(receipt.get("paths"), Mapping)
        ):
            result = {
                "paths": receipt.get("paths"),
                "counts": receipt.get("counts"),
                "status": receipt.get("status"),
                "changed_files": receipt.get("changed_files"),
            }
        else:
            raise RuntimeError("Mapper does not support a verifiable standalone receipt")
    elif receipt.get("schema") != "simplicio.mapper-index/v1" or receipt.get("status") not in {
        "updated",
        "unchanged",
        "skipped",
    }:
        raise RuntimeError("Mapper does not support a verifiable standalone receipt")

    generation = str(
        receipt.get("generation")
        or result.get("generation")
        or content_hash({"repo": str(repo), "result": result})
    )
    normalized = {
        "schema": "simplicio.mapper-receipt/v1",
        "verified": True,
        "repo": str(repo),
        "generation": generation,
        "artifact_digest": content_hash(result),
        "source_receipt": dict(receipt),
    }
    return {"verified": True, "generation": generation, "receipt": normalized}
