#!/usr/bin/env python3
"""Live identity proof for issue #183.

This producer consults GitHub through ``gh api`` for the canonical issue
identity, then reconciles those live fields against local distributed E2E
artifacts already present under ``.simplicio-loop/orchestrator``.

It proves only what can be observed locally in this repository plus the live
GitHub issue metadata. Physical multi-machine execution remains explicitly
UNVERIFIED.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _canonical(owner: str, repo: str, number: int) -> dict[str, Any]:
    return {
        "owner": owner,
        "repo": repo,
        "number": int(number),
        "issue_ref": f"{owner}/{repo}#{int(number)}",
        "url": f"https://github.com/{owner}/{repo}/issues/{int(number)}",
    }


def _parse_repo_from_url(value: str) -> tuple[str, str]:
    parsed = urlparse(str(value or "").strip())
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc != "github.com" or len(parts) < 4 or parts[2] != "issues":
        raise ValueError(f"non-canonical GitHub issue URL: {value}")
    return parts[0], parts[1]


def _query_issue(owner: str, repo: str, number: int, *, runner: Runner, timeout: int) -> dict[str, Any]:
    command = ["gh", "api", f"repos/{owner}/{repo}/issues/{number}"]
    completed = runner(command, capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"gh api failed: {stderr or 'unknown error'}")
    payload = json.loads(completed.stdout)
    live_title = str(payload.get("title") or "").strip()
    live_number = int(payload.get("number") or 0)
    live_url = str(payload.get("html_url") or "").strip()
    live_owner, live_repo = _parse_repo_from_url(live_url)
    if (live_owner, live_repo, live_number) != (owner, repo, int(number)):
        raise ValueError("live issue identity does not match requested owner/repo/number")
    return {
        **_canonical(owner, repo, number),
        "title": live_title,
        "state": str(payload.get("state") or "").strip(),
        "gh_command": " ".join(command),
    }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _resolve_artifact_path(root: Path, source_file: Path, value: str) -> Path:
    candidate = Path(str(value))
    if candidate.is_absolute():
        return candidate
    joined = source_file.parent / candidate
    if joined.exists():
        return joined
    return root / candidate


def _preferred_artifacts(root: Path, relative: str, pattern: str) -> list[Path]:
    """Use the current canonical wave artifact, falling back to historical fixtures in tests."""
    preferred = root / relative
    if preferred.exists():
        return [preferred]
    return sorted(root.glob(pattern))


def _scan_ac7_receipts(root: Path, canonical: dict[str, Any]) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    mismatches: list[str] = []
    merge_receipts: list[dict[str, Any]] = []
    files = _preferred_artifacts(
        root,
        ".simplicio-loop/orchestrator/evidence/distributed-183-ac7-integration/distributed-183-ac7-receipt.json",
        ".simplicio-loop/orchestrator/**/distributed-183-ac7-receipt.json",
    )
    for file_path in files:
        payload = _load_json(file_path)
        if int(payload.get("issue") or 0) != canonical["number"]:
            mismatches.append(f"{file_path}: issue field != {canonical['number']}")
            continue
        queue_tasks = (((payload.get("local_measured") or {}).get("queue_tasks")) or {})
        for task_id, task in sorted(queue_tasks.items()):
            context = dict(task.get("context_pack") or {})
            issue_ref = str(context.get("issue_ref") or "").strip()
            issue_url = str(context.get("issue_url") or "").strip()
            if issue_ref != canonical["issue_ref"] or issue_url != canonical["url"]:
                mismatches.append(f"{file_path}:{task_id}: context pack issue identity mismatch")
                continue
            allocation = dict(task.get("allocation_receipt") or {})
            matches.append(
                {
                    "artifact": str(file_path),
                    "task_id": str(task_id),
                    "issue_ref": issue_ref,
                    "issue_url": issue_url,
                    "branch": str(allocation.get("branch") or ""),
                    "worktree_path": str(allocation.get("path") or ""),
                }
            )
        for row in ((payload.get("local_measured") or {}).get("merge_queue_receipts") or []):
            receipt_path = _resolve_artifact_path(root, file_path, str(row.get("merge_queue_receipt_path") or ""))
            merge_receipts.append(
                {
                    "artifact": str(file_path),
                    "task_id": str(row.get("task_id") or ""),
                    "merge_queue_receipt_sha": str(row.get("merge_queue_receipt_sha") or ""),
                    "merge_queue_status": str(row.get("merge_queue_status") or ""),
                    "merge_queue_receipt_path": str(receipt_path),
                    "exists": receipt_path.exists(),
                }
            )
    measured = bool(files and matches and merge_receipts) and not mismatches and all(
        row["exists"] and row["merge_queue_status"] == "accepted" and row["merge_queue_receipt_sha"]
        for row in merge_receipts
    )
    return {
        "tag": "MEASURED" if measured else "UNVERIFIED",
        "files_scanned": [str(path) for path in files],
        "task_matches": matches,
        "merge_receipts": merge_receipts,
        "mismatches": mismatches,
    }


def _scan_epic_receipts(root: Path, canonical: dict[str, Any]) -> dict[str, Any]:
    files = _preferred_artifacts(
        root,
        ".simplicio-loop/orchestrator/evidence/issue183-ac7-integration/distributed-epic-evidence.json",
        ".simplicio-loop/orchestrator/**/distributed-epic-evidence.json",
    )
    titles: list[dict[str, Any]] = []
    mismatches: list[str] = []
    expected_title = str(canonical.get("title") or "").strip()
    for file_path in files:
        payload = _load_json(file_path)
        issue_number = int(payload.get("issue") or 0)
        title = str(payload.get("title") or "").strip()
        if issue_number != canonical["number"]:
            mismatches.append(f"{file_path}: issue field != {canonical['number']}")
            continue
        titles.append({"artifact": str(file_path), "issue": issue_number, "title": title})
        if expected_title and title != expected_title:
            mismatches.append(f"{file_path}: title mismatch against live GitHub issue")
    measured = bool(files and titles) and not mismatches
    return {
        "tag": "MEASURED" if measured else "UNVERIFIED",
        "files_scanned": [str(path) for path in files],
        "titles": titles,
        "mismatches": mismatches,
    }


def build_receipt(
    root: str | Path = HERE,
    *,
    owner: str = "wesleysimplicio",
    repo: str = "simplicio-loop",
    number: int = 183,
    runner: Runner = subprocess.run,
    timeout: int = 20,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    canonical = _canonical(owner, repo, number)
    try:
        live = _query_issue(owner, repo, number, runner=runner, timeout=timeout)
        live_check = {"tag": "MEASURED", **live}
    except Exception as exc:
        live_check = {
            "tag": "UNVERIFIED",
            **canonical,
            "title": "",
            "state": "",
            "gh_command": f"gh api repos/{owner}/{repo}/issues/{number}",
            "error": f"{type(exc).__name__}: {exc}",
        }

    ac7 = _scan_ac7_receipts(root_path, canonical if live_check["tag"] != "MEASURED" else live_check)
    epic = _scan_epic_receipts(root_path, canonical if live_check["tag"] != "MEASURED" else live_check)

    measured = live_check["tag"] == "MEASURED" and ac7["tag"] == "MEASURED" and epic["tag"] == "MEASURED"
    return {
        "schema": "simplicio.live-issue-183-identity/v1",
        "tag": "MEASURED" if measured else "UNVERIFIED",
        "issue": {
            "owner": live_check["owner"],
            "repo": live_check["repo"],
            "number": live_check["number"],
            "title": live_check["title"],
            "url": live_check["url"],
            "state": live_check["state"],
        },
        "checks": {
            "gh_issue": live_check,
            "context_packs_and_merge_receipts": ac7,
            "epic_title_receipts": epic,
        },
        "local_measured": {
            "matched_context_pack_tasks": len(ac7["task_matches"]),
            "matched_merge_receipts": sum(1 for row in ac7["merge_receipts"] if row["exists"]),
            "matched_epic_titles": sum(
                1
                for row in epic["titles"]
                if row["title"] == live_check["title"] and live_check["title"]
            ),
        },
        "external_unverified": {
            "physical_multi_machine": "UNVERIFIED| this proof only reconciles live GitHub metadata with local receipts/context packs",
            "remote_queue_service": "UNVERIFIED| no external durable distributed queue was exercised here",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile live GitHub issue #183 identity with local distributed receipts")
    parser.add_argument("--root", default=str(HERE))
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args(argv)
    receipt = build_receipt(args.root, timeout=args.timeout)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["tag"] == "MEASURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
