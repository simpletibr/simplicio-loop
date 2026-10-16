"""`ledger`, `findings` and `learn`: the event ledger and finding reports.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

import json

from ._base import impl

from .. import inspection_cli as _inspection_cli
from ..ops_ledger import LedgerError

def _load_handshake(handshake_json: str, handshake_file: str):
    """Compatibility wrapper that preserves CLI-level validator monkeypatches."""
    return _inspection_cli._load_handshake(
        handshake_json, handshake_file, validator=impl().validate_handshake,
        ledger_error=LedgerError,
    )


def ledger_replay(path: str, compatibility: bool, recover_trailing: bool,
                  handshake_json: str, handshake_file: str, command: str = "replay") -> int:
    """Compatibility wrapper for the focused read-only ledger surface."""
    return _inspection_cli.ledger_replay(
        path, compatibility, recover_trailing, handshake_json, handshake_file,
        command, handshake_loader=_load_handshake, event_ledger=impl().EventLedger,
        ledger_error=LedgerError, context_schema=impl().CONTEXT_SCHEMA,
        handshake_schema=impl().HANDSHAKE_SCHEMA, required_context_fields=impl().REQUIRED_CONTEXT_FIELDS,
    )


def findings_command(args) -> int:
    """Compatibility wrapper for the focused findings command surface."""
    return _inspection_cli.findings_command(args)


def retrospective_command(args) -> int:
    from ..retrospective import retrospective
    result = retrospective(args.repo, args.run_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def add_ledger(sub):
    p_ledger = sub.add_parser("ledger", help="validate/replay the operational event ledger")
    p_findings = sub.add_parser("findings", help="WI-466: inspect and reconcile continuous findings")
    findings_sub = p_findings.add_subparsers(dest="findings_command", required=True)
    p_f_list = findings_sub.add_parser("list", help="list all routed findings (JSONL)")
    p_f_list.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_report = findings_sub.add_parser("report", help="show aggregated finding counts by stage/severity")
    p_f_report.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_reconcile = findings_sub.add_parser("reconcile", help="show dedup state and untracked findings")
    p_f_reconcile.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_doctor = findings_sub.add_parser("doctor", help="health-check the findings store and router state")
    p_f_doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_import = findings_sub.add_parser("import", help="create one GitHub issue for each JSON finding")
    p_f_import.add_argument("path", help="JSON array of findings or object with findings array")
    p_f_import.add_argument("--repo-map", default="", help="JSON map from source parent to owner/repo")
    p_f_import.add_argument("--label", action="append", default=[], help="label to add to each issue (repeatable)")
    p_f_import.add_argument("--dry-run", action="store_true", help="resolve repositories without creating issues")
    p_f_import.add_argument("--receipt", default="", help="persistent batch receipt path for safe retries")
    p_learn = sub.add_parser("learn", help="derive durable lessons from completed runs")
    learn_sub = p_learn.add_subparsers(dest="learn_command", required=True)
    p_ret = learn_sub.add_parser("retrospective", help="deduplicate trajectory lessons and write a receipt")
    p_ret.add_argument("--repo", default=".")
    p_ret.add_argument("--run", dest="run_id", default=None)
    ledger_sub = p_ledger.add_subparsers(dest="ledger_command", required=True)
    for ledger_command in ("replay", "validate"):
        p_ledger_action = ledger_sub.add_parser(
            ledger_command,
            help="%s events with hash-chain and context validation" % ledger_command,
        )
        p_ledger_action.add_argument("--path", required=True, help="JSONL EventLedger path")
        p_ledger_action.add_argument(
            "--compatibility",
            action="store_true",
            help="explicitly allow legacy v1 rows without context/handshake",
        )
        p_ledger_action.add_argument(
            "--recover-trailing",
            action="store_true",
            help="drop one corrupt trailing JSONL row under the ledger lock",
        )
        handshake = p_ledger_action.add_mutually_exclusive_group()
        handshake.add_argument(
            "--handshake-json",
            default="",
            help="inline executor handshake JSON (strict mode requires it)",
        )
        handshake.add_argument(
            "--handshake-file",
            default="",
            help="file containing executor handshake JSON (strict mode requires it)",
        )
