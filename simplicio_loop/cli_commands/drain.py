"""`drain`: evaluate, persist or load a queue-drain receipt.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

from ._base import impl

from .. import inspection_cli as _inspection_cli
from ..drain import DrainReceiptError
from ..drain import SCHEMA as DRAIN_SCHEMA
from ..drain import evaluate_drain
from ..drain import persist_drain_receipt

def _drain_cli_failure(reason_code: str, reason: str, **extra) -> dict:
    """Compatibility wrapper for the focused command helpers."""
    return _inspection_cli.drain_cli_failure(DRAIN_SCHEMA, reason_code, reason, **extra)


def _read_drain_snapshot(path: str):
    return _inspection_cli.read_drain_snapshot(path, _drain_cli_failure)


def _valid_drain_result(payload) -> bool:
    return _inspection_cli.valid_drain_result(DRAIN_SCHEMA, payload)


def drain(action: str, snapshot_path: str, receipt_path: str, polls_required: int) -> int:
    """Compatibility wrapper that preserves CLI-level dependency monkeypatches."""
    return _inspection_cli.drain(
        action, snapshot_path, receipt_path, polls_required,
        evaluator=evaluate_drain, persist=persist_drain_receipt, load=impl().load_drain_receipt,
        receipt_error=DrainReceiptError, failure=_drain_cli_failure,
        snapshot_reader=_read_drain_snapshot, result_validator=_valid_drain_result,
    )


def add_drain(sub):
    p_drain = sub.add_parser("drain", help="evaluate, persist, or load a queue-drain receipt")
    p_drain.add_argument("action", nargs="?", default="",
                          help="operation to perform: evaluate, persist, or load")
    p_drain.add_argument("--snapshot", "--snapshot-file", dest="snapshot_path", default="",
                         help="JSON scheduler/source snapshot (evaluate and persist)")
    p_drain.add_argument("--receipt", "--receipt-file", dest="receipt_path", default="",
                         help="receipt JSON path (persist and load)")
    p_drain.add_argument("--polls-required", type=int, default=2,
                         help="identical empty polls required (default: %(default)s)")
