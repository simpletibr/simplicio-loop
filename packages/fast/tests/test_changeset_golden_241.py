import hashlib
import json
from pathlib import Path

from simplicio_fast.binary_changeset import BinaryChangeSet, decode_binary


FIXTURE = Path(__file__).parents[1] / "fixtures" / "changeset" / "v1" / "operation-matrix.json"


def test_operation_matrix_binary_is_byte_deterministic() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    changeset = BinaryChangeSet.from_dict(payload["fixture"])
    encoded = changeset.encode()

    assert changeset.changeset_id == payload["changeset_id"]
    assert len(encoded) == payload["bytes"]
    assert hashlib.sha256(encoded).hexdigest() == payload["binary_sha256"]
    assert decode_binary(encoded) == changeset
    assert [operation.op for operation in changeset.operations] == [
        "create",
        "replace-range",
        "rename",
        "delete",
    ]
