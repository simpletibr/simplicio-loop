"""``simplicio-py intake`` — provider-free TaskSpec v2 parsing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..execution_contract import ContractCompilationError, compile_execution_contracts
from ..orchestrator.multi_task import BatchBuildError, TaskBatch, build_batch_preview
from ..plan_discovery import PlanDiscoveryError, build_plan_preview
from ..task_spec import SourceRef, TaskSpecValidationError, parse_task_document

CLI_PROG = "simplicio-py"
_URL_TIMEOUT_SECONDS = 10
_MAX_URL_BYTES = 2 * 1024 * 1024


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


def _read_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TaskSpecValidationError(["URL input must use an absolute http:// or https:// URL"])
    request = Request(url, headers={"User-Agent": "simplicio-dev-cli/1"})
    try:
        with urlopen(request, timeout=_URL_TIMEOUT_SECONDS) as response:
            raw = response.read(_MAX_URL_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise TaskSpecValidationError([f"could not read URL input: {exc}"]) from exc
    if len(raw) > _MAX_URL_BYTES:
        raise TaskSpecValidationError([f"URL input exceeds {_MAX_URL_BYTES} bytes"])
    return _decode(raw)


def _read_input(a: argparse.Namespace) -> tuple[str, SourceRef]:
    url = getattr(a, "url", None)
    provided = int(a.text is not None) + int(a.file is not None) + int(a.stdin) + int(url is not None)
    if provided > 1:
        raise TaskSpecValidationError(
            ["choose exactly one input source: text argument, --file, --stdin, or --url"]
        )
    if url:
        text, encoding = _read_url(url)
        return text, SourceRef(kind="url", locator=url, encoding=encoding)
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
    if getattr(a, "batch_path", None) and getattr(a, "plan_only", False):
        diagnostic = "--batch-path mutates state and cannot be combined with --plan-only"
        if a.json:
            print(
                json.dumps(
                    {"schema": "simplicio.intake-validation/v1", "valid": False, "errors": [diagnostic]}
                )
            )
        else:
            print(f"{CLI_PROG} intake: {diagnostic}", file=sys.stderr)
        return 2
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
        if getattr(a, "batch_path", None):
            identity = batch_preview["identity"]
            batch = TaskBatch.create(
                a.batch_path,
                batch_preview["tasks"],
                source_hash=identity["source_hash"],
                plan_hash=identity["plan_hash"],
                base_sha=identity["base_sha"],
            )
            batch_preview = batch.status()
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
                **(
                    {"batch_path": str(Path(a.batch_path).resolve())}
                    if getattr(a, "batch_path", None)
                    else {}
                ),
            }
        else:
            payload = {
                "schema": "simplicio.intake-result/v1",
                "task_spec": payload,
                "contracts": contracts_payload,
                "task_batch": batch_preview,
                **(
                    {"batch_path": str(Path(a.batch_path).resolve())}
                    if getattr(a, "batch_path", None)
                    else {}
                ),
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
