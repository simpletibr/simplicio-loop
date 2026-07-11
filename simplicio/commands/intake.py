"""``simplicio-py intake`` — provider-free TaskSpec v2 parsing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..execution_contract import ContractCompilationError, compile_execution_contracts
from ..orchestrator.multi_task import BatchBuildError, build_batch_preview
from ..plan_discovery import PlanDiscoveryError, build_plan_preview
from ..task_spec import SourceRef, TaskSpecValidationError, parse_task_document

CLI_PROG = "simplicio-py"


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding), "utf-8" if encoding == "utf-8-sig" else encoding
        except UnicodeDecodeError:
            continue
    raise TaskSpecValidationError(["input is neither valid UTF-8 nor Windows-1252 text"])


def _read_stdin() -> tuple[str, str]:
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        return _decode(buffer.read())
    return sys.stdin.read(), "utf-8"


def _read_input(a: argparse.Namespace) -> tuple[str, SourceRef]:
    provided = int(a.text is not None) + int(a.file is not None) + int(a.stdin)
    if provided > 1:
        raise TaskSpecValidationError(["choose exactly one input source: text argument, --file, or --stdin"])
    if a.file:
        path = Path(a.file)
        if not path.is_file():
            raise TaskSpecValidationError([f"input file does not exist: {path}"])
        text, encoding = _decode(path.read_bytes())
        return text, SourceRef(kind="file", locator=str(path), encoding=encoding)
    if a.text is not None:
        return a.text, SourceRef(kind="argument", locator=a.source_url, encoding="utf-8")
    text, encoding = _read_stdin()
    return text, SourceRef(kind="stdin", locator=a.source_url, encoding=encoding)


def run(a: argparse.Namespace) -> int:
    try:
        text, source = _read_input(a)
        document = parse_task_document(text, source=source)
    except (TaskSpecValidationError, ContractCompilationError) as exc:
        diagnostics = getattr(exc, "diagnostics", None) or getattr(exc, "errors", None) or [str(exc)]
        if a.json:
            print(
                json.dumps(
                    {
                        "schema": "simplicio.task-spec-validation/v1",
                        "valid": False,
                        "errors": list(diagnostics),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            for diagnostic in diagnostics:
                print(f"{CLI_PROG} intake: {diagnostic}", file=sys.stderr)
        return 2

    payload = document.to_dict()
    if getattr(a, "contract", False) or getattr(a, "plan_only", False):
        try:
            contracts = compile_execution_contracts(
                document, execution_mode=getattr(a, "execution_mode", False)
            )
            batch_preview = build_batch_preview(document)
        except ContractCompilationError as exc:
            diagnostics = list(exc.errors)
            if a.json:
                print(
                    json.dumps(
                        {
                            "schema": "simplicio.execution-contract-validation/v1",
                            "valid": False,
                            "errors": diagnostics,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            else:
                for diagnostic in diagnostics:
                    print(f"{CLI_PROG} intake: {diagnostic}", file=sys.stderr)
            return 2
        except BatchBuildError as exc:
            diagnostics = list(exc.diagnostics)
            if a.json:
                print(
                    json.dumps(
                        {
                            "schema": "simplicio.task-batch-validation/v1",
                            "valid": False,
                            "errors": diagnostics,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            else:
                for diagnostic in diagnostics:
                    print(f"{CLI_PROG} intake: {diagnostic}", file=sys.stderr)
            return 2
        contracts_payload = [contract.to_dict() for contract in contracts]
        if getattr(a, "plan_only", False):
            try:
                preview = (
                    build_plan_preview(
                        getattr(a, "root", "."),
                        document.tasks[0],
                        contracts[0],
                        task_spec_payload=payload["tasks"][0],
                    )
                    if len(document.tasks) == 1
                    else {
                        "schema": "simplicio.plan-preview/v1",
                        "status": "blocked",
                        "dispatch": False,
                        "mutated": False,
                        "root": str(Path(getattr(a, "root", ".")).resolve()),
                        "discovery_mode": "mapper-single-repo/v1",
                        "blockers": [
                            (
                                "plan-only execution discovery currently supports exactly one "
                                "task card per preview"
                            ),
                            "split the intake into one task per preview or use the frozen task_batch output",
                        ],
                    }
                )
            except PlanDiscoveryError as exc:
                preview = {
                    "schema": "simplicio.plan-preview/v1",
                    "status": "blocked",
                    "dispatch": False,
                    "mutated": False,
                    "root": str(Path(getattr(a, "root", ".")).resolve()),
                    "discovery_mode": "mapper-single-repo/v1",
                    "blockers": list(exc.diagnostics),
                }
            payload = {
                **preview,
                "task_spec": payload,
                "contracts": contracts_payload,
                "task_batch": batch_preview,
            }
        else:
            payload = {
                "schema": "simplicio.intake-result/v1",
                "task_spec": payload,
                "contracts": contracts_payload,
                "task_batch": batch_preview,
            }
    if a.validate_only:
        payload = {
            "schema": "simplicio.task-spec-validation/v1",
            "valid": True,
            "task_count": len(document.tasks),
            "task_spec": payload,
        }
    if a.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{CLI_PROG} intake: valid TaskSpec v2 ({len(document.tasks)} task(s))")
        for task in document.tasks:
            print(f"  {task.task_id}: {task.functionality or task.narrative.get('i_want') or 'untitled'}")
    return 0
