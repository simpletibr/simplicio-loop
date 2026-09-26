"""CLI for the read-only GitHub drain intake slice."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Sequence

from .github_drain_intake import (
    FAILED_EXIT,
    INTAKE_SCHEMA,
    INVALID_REQUEST_EXIT,
    DrainIntentError,
    GitHubDrainIntake,
    ReadOnlyLocalGitMap,
    parse_natural_drain_request,
)
from .source_adapter import GitHubSourceAdapter


def looks_like_natural_request(argv: Sequence[str]) -> bool:
    text = " ".join(str(value) for value in argv if not str(value).startswith("--"))
    folded = text.lower()
    return bool(re.search(r"\b(issues|tickets|tarefas)\b", folded)) and bool(
        re.search(r"\b(all|todas|todos)\b", folded)
    )


def _emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return int((payload.get("outcome") or {}).get("exit_code", FAILED_EXIT))


def _default_checkpoint(workspace: str, repository: str) -> str:
    return str(
        Path(workspace).resolve()
        / ".simplicio-loop/orchestrator"
        / "drain-intake"
        / (repository.replace("/", "--") + ".json")
    )


def _forbidden_publish(*_args, **_kwargs):  # pragma: no cover - an effect tripwire
    raise RuntimeError("read-only drain intake cannot publish GitHub comments")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simplicio-loop hub-drain-plan",
        description=(
            "Build a read-only GitHub issue drain plan. This command never executes the plan."
        ),
    )
    parser.add_argument("request", nargs="+", help="PT-BR/EN natural all-issues request")
    parser.add_argument("--workspace", default=".", help="local Git checkout used for canonical mapping")
    parser.add_argument("--checkpoint", default="", help="integrity-checked intake checkpoint")
    parser.add_argument(
        "--no-map", action="store_true", help="record canonical mapping as unsupported"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    request = " ".join(args.request)
    try:
        intent = parse_natural_drain_request(request)
        workspace = str(Path(args.workspace).resolve())
        checkpoint = args.checkpoint or _default_checkpoint(workspace, intent.repository)
    except (DrainIntentError, ValueError) as exc:
        return _emit({
            "schema": INTAKE_SCHEMA,
            "execution_authorized": False,
            "outcome": {
                "status": "BLOCKED",
                "reason_code": getattr(exc, "reason_code", "invalid_request"),
                "exit_code": INVALID_REQUEST_EXIT,
                "execution_authorized": False,
                "error": str(exc),
            },
        })

    try:
        source = GitHubSourceAdapter(
            intent.owner,
            intent.repo,
            publish_comment_fn=_forbidden_publish,
        )
        controller = GitHubDrainIntake(
            source=source,
            checkpoint=checkpoint,
            workspace=workspace,
            map_reader=None if args.no_map else ReadOnlyLocalGitMap(),
        )
        return _emit(controller.run(request))
    except Exception as exc:
        return _emit({
            "schema": INTAKE_SCHEMA,
            "execution_authorized": False,
            "outcome": {
                "status": "FAILED",
                "reason_code": getattr(exc, "reason_code", "drain_intake_cli_failed"),
                "exit_code": FAILED_EXIT,
                "execution_authorized": False,
                "error": "%s: %s" % (type(exc).__name__, exc),
            },
        })


if __name__ == "__main__":
    raise SystemExit(main())
