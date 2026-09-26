from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.live_issue_183_identity import build_receipt  # noqa: E402


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _gh_runner(payload: dict, bucket: list[list[str]]):
    def runner(command, capture_output, text, timeout, check):  # noqa: ANN001
        bucket.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    return runner


def test_live_issue_183_identity_receipt_is_measured_when_live_issue_and_local_receipts_align(tmp_path):
    evidence_dir = tmp_path / ".simplicio-loop/orchestrator" / "evidence" / "distributed-183-ac7-integration"
    merge_a = evidence_dir / "WI-183-CODEX-a.json"
    merge_b = evidence_dir / "WI-183-CLAUDE-b.json"
    _write(merge_a, {"ok": True})
    _write(merge_b, {"ok": True})
    _write(
        evidence_dir / "distributed-183-ac7-receipt.json",
        {
            "issue": 183,
            "local_measured": {
                "queue_tasks": {
                    "WI-183-CODEX": {
                        "context_pack": {
                            "issue_ref": "wesleysimplicio/simplicio-loop#183",
                            "issue_url": "https://github.com/wesleysimplicio/simplicio-loop/issues/183",
                        },
                        "allocation_receipt": {"branch": "simplicio/issue-183-ac7/WI-183-CODEX", "path": "wt/codex"},
                    },
                    "WI-183-CLAUDE": {
                        "context_pack": {
                            "issue_ref": "wesleysimplicio/simplicio-loop#183",
                            "issue_url": "https://github.com/wesleysimplicio/simplicio-loop/issues/183",
                        },
                        "allocation_receipt": {"branch": "simplicio/issue-183-ac7/WI-183-CLAUDE", "path": "wt/claude"},
                    },
                },
                "merge_queue_receipts": [
                    {
                        "task_id": "WI-183-CODEX",
                        "merge_queue_receipt_sha": "sha-a",
                        "merge_queue_receipt_path": str(merge_a.relative_to(evidence_dir)),
                        "merge_queue_status": "accepted",
                    },
                    {
                        "task_id": "WI-183-CLAUDE",
                        "merge_queue_receipt_sha": "sha-b",
                        "merge_queue_receipt_path": str(merge_b.relative_to(evidence_dir)),
                        "merge_queue_status": "accepted",
                    },
                ],
            },
        },
    )
    _write(
        tmp_path / ".simplicio-loop/orchestrator" / "evidence" / "distributed-183-local" / "distributed-epic-evidence.json",
        {
            "issue": 183,
            "title": "[EPIC][P0][Distributed] Multi-agent paralelo por default entre Codex, Claude e máquinas",
        },
    )
    commands: list[list[str]] = []
    receipt = build_receipt(
        tmp_path,
        runner=_gh_runner(
            {
                "number": 183,
                "title": "[EPIC][P0][Distributed] Multi-agent paralelo por default entre Codex, Claude e máquinas",
                "state": "OPEN",
                "html_url": "https://github.com/wesleysimplicio/simplicio-loop/issues/183",
            },
            commands,
        ),
    )

    assert commands == [["gh", "api", "repos/wesleysimplicio/simplicio-loop/issues/183"]]
    assert receipt["tag"] == "MEASURED"
    assert receipt["issue"]["owner"] == "wesleysimplicio"
    assert receipt["issue"]["repo"] == "simplicio-loop"
    assert receipt["issue"]["number"] == 183
    assert receipt["checks"]["gh_issue"]["tag"] == "MEASURED"
    assert receipt["checks"]["context_packs_and_merge_receipts"]["tag"] == "MEASURED"
    assert receipt["checks"]["epic_title_receipts"]["tag"] == "MEASURED"
    assert receipt["local_measured"]["matched_context_pack_tasks"] == 2
    assert receipt["local_measured"]["matched_merge_receipts"] == 2
    assert receipt["external_unverified"]["physical_multi_machine"].startswith("UNVERIFIED|")


def test_live_issue_183_identity_receipt_degrades_to_unverified_on_title_mismatch(tmp_path):
    evidence_dir = tmp_path / ".simplicio-loop/orchestrator" / "evidence" / "distributed-183-ac7-manual"
    merge_path = evidence_dir / "WI-183-CODEX-a.json"
    _write(merge_path, {"ok": True})
    _write(
        evidence_dir / "distributed-183-ac7-receipt.json",
        {
            "issue": 183,
            "local_measured": {
                "queue_tasks": {
                    "WI-183-CODEX": {
                        "context_pack": {
                            "issue_ref": "wesleysimplicio/simplicio-loop#183",
                            "issue_url": "https://github.com/wesleysimplicio/simplicio-loop/issues/183",
                        },
                        "allocation_receipt": {"branch": "simplicio/issue-183-ac7/WI-183-CODEX", "path": "wt/codex"},
                    }
                },
                "merge_queue_receipts": [
                    {
                        "task_id": "WI-183-CODEX",
                        "merge_queue_receipt_sha": "sha-a",
                        "merge_queue_receipt_path": str(merge_path.relative_to(evidence_dir)),
                        "merge_queue_status": "accepted",
                    }
                ],
            },
        },
    )
    _write(
        tmp_path / ".simplicio-loop/orchestrator" / "issue183-ac7-proof" / "distributed-epic-evidence.json",
        {
            "issue": 183,
            "title": "stale local title",
        },
    )
    receipt = build_receipt(
        tmp_path,
        runner=_gh_runner(
            {
                "number": 183,
                "title": "live canonical title",
                "state": "OPEN",
                "html_url": "https://github.com/wesleysimplicio/simplicio-loop/issues/183",
            },
            [],
        ),
    )

    assert receipt["tag"] == "UNVERIFIED"
    assert receipt["checks"]["gh_issue"]["tag"] == "MEASURED"
    assert receipt["checks"]["context_packs_and_merge_receipts"]["tag"] == "MEASURED"
    assert receipt["checks"]["epic_title_receipts"]["tag"] == "UNVERIFIED"
    assert "title mismatch" in receipt["checks"]["epic_title_receipts"]["mismatches"][0]
