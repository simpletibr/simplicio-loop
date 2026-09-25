"""Standalone Fast adapter for the canonical Runtime HBP v1 contract."""

from __future__ import annotations
import hashlib
from dataclasses import dataclass

SCHEMA = "simplicio.hbp/v1"
GENESIS = "0" * 64


class HbpError(ValueError):
    pass


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verified_alias(data: bytes, full_digest: str) -> str:
    if len(full_digest) != 64 or sha256_hex(data) != full_digest:
        raise HbpError("ALIAS_UNVERIFIED")
    return "AGT-" + full_digest[:16]


def seal_receipt(row: str, previous: str = GENESIS) -> str:
    if "\n" in row or "\r" in row:
        raise HbpError("HBP_MALFORMED_ROW")
    body = f"{row}|prev_event_hash={previous}"
    return f"{body}|event_hash={sha256_hex(body.encode())}"


def verify_chain(rows: list[str]) -> str:
    previous = GENESIS
    for row in rows:
        try:
            body, claimed = row.rsplit("|event_hash=", 1)
            _, linked = body.rsplit("|prev_event_hash=", 1)
        except ValueError as exc:
            raise HbpError("HBP_PARTIAL_APPEND") from exc
        if (
            linked != previous
            or len(claimed) != 64
            or sha256_hex(body.encode()) != claimed
        ):
            raise HbpError("HBP_INVALID_CHAIN")
        previous = claimed
    return previous


@dataclass(frozen=True)
class LogicalPointer:
    digest: str
    offset: int
    length: int

    def validate(self, blob_length: int) -> None:
        if len(self.digest) != 64:
            raise HbpError("HBI_DIGEST_INVALID")
        if (
            self.offset < 0
            or self.length <= 0
            or self.offset + self.length > blob_length
        ):
            raise HbpError("HBI_OUT_OF_BOUNDS")
