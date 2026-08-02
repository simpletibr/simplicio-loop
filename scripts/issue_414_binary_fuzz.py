"""Deterministic malformed-envelope corpus for issue #414.

Every generated payload must fail closed before a repository mutation.  This
is a bounded regression corpus, not a claim of coverage for an unbounded fuzz
space.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

# Run the evidence harness against the checkout under test, even when an
# older installed simplicio package is present on PATH.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from simplicio.changeset_v2 import execute_changeset_bytes  # noqa: E402

SCHEMA = "simplicio.dev-cli.issue-414-binary-fuzz/v1"


def _valid_payload(root: Path) -> bytes | None:
    try:
        from simplicio_fast.binary_changeset import BinaryChangeSet, ChangeOperation
    except (ImportError, ModuleNotFoundError):
        return None
    content = b"fuzz-seed\n"
    operation = ChangeOperation.from_dict(
        {
            "op": "create",
            "path": "fuzz.txt",
            "content_b64": base64.b64encode(content).decode(),
            "after_sha256": hashlib.sha256(content).hexdigest(),
        }
    )
    return BinaryChangeSet(
        repository=str(root.resolve()),
        base_generation="fuzz-generation",
        overlay_generation="fuzz-overlay",
        attempt="fuzz-attempt",
        worktree_id="fuzz-worktree",
        lease_id="fuzz-lease",
        fencing_token="fuzz-fence",
        allowed_paths=("fuzz.txt",),
        operations=(operation,),
    ).encode()


def _mutations(payload: bytes) -> tuple[bytes, ...]:
    mutations = [
        b"",
        payload[:1],
        payload[:8],
        payload[:-1],
        payload + b"\x00",
        b"SFBCHG00" + payload[8:],
        b'{"schema":"simplicio.fast.binary-changeset/v1"}',
    ]
    for offset in range(min(32, len(payload))):
        mutated = bytearray(payload)
        mutated[offset] ^= 0xFF
        mutations.append(bytes(mutated))
    return tuple(mutations)


def run_fuzz() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="issue-414-fuzz-") as directory:
        root = Path(directory)
        payload = _valid_payload(root)
        if payload is None:
            return {
                "schema": SCHEMA,
                "status": "UNAVAILABLE",
                "reason": "simplicio-fast binary conformance decoder is not installed",
                "cases": 0,
            }
        failures = []
        cases = _mutations(payload)
        for index, candidate in enumerate(cases):
            result = execute_changeset_bytes(candidate, root=root, apply=True, fast_engine="python")
            if result.get("status") == "ok" or (root / "fuzz.txt").exists():
                failures.append({"case": index, "result": result})
        return {
            "schema": SCHEMA,
            "status": "PASS" if not failures else "FAIL",
            "cases": len(cases),
            "rejected": len(cases) - len(failures),
            "failures": failures,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_fuzz()
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["status"] in {"PASS", "UNAVAILABLE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
