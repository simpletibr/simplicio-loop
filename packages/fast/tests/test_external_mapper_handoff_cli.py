from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from simplicio_fast.parser_adapter import build_payload_from_mapper


FAST_ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _make_repo(root: Path) -> str:
    root.mkdir()
    (root / "service.py").write_text(
        "def helper():\n    return True\n\n\ndef run():\n    return helper()\n",
        encoding="utf-8",
    )
    _git(root, "init", "--quiet", "-b", "main")
    _git(root, "config", "user.email", "fast-tests@example.invalid")
    _git(root, "config", "user.name", "Fast tests")
    _git(root, "add", "service.py")
    _git(root, "commit", "--quiet", "-m", "fixture")
    return _git(root, "rev-parse", "HEAD")


def _run_fast(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    source_path = str(FAST_ROOT / "src")
    environment["PYTHONPATH"] = ":".join(
        part for part in (source_path, environment.get("PYTHONPATH")) if part
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "simplicio_fast.cli",
            *args,
        ],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _mapper_envelope(root: Path) -> dict[str, object]:
    mapper = shutil.which("simplicio-mapper")
    if mapper is None:
        pytest.fail("simplicio-mapper is required for the documented integration")
    snapshot = subprocess.run(
        [mapper, "snapshot", "build", "--root", str(root)],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert snapshot.returncode == 0, snapshot.stderr
    handoff = subprocess.run(
        [mapper, "fast-handoff", str(root)],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert handoff.returncode == 0, handoff.stderr
    envelope = json.loads(handoff.stdout)
    assert set(envelope) >= {"handoff", "receipt"}
    return envelope


def test_documented_external_mapper_envelope_supports_ingest_and_plan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    _make_repo(root)
    envelope = _mapper_envelope(root)
    external_handoff = tmp_path / "mapper-handoff.json"
    external_handoff.write_text(
        json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8"
    )
    snapshot = tmp_path / "fast.sfast"

    ingest = _run_fast(
        root,
        "ingest",
        str(root),
        "--output",
        str(snapshot),
        "--mapper-mode",
        "integrated",
        "--mapper-handoff",
        str(external_handoff),
        "--json",
    )
    assert ingest.returncode == 0, ingest.stderr + ingest.stdout
    ingest_payload = json.loads(ingest.stdout)
    assert ingest_payload["schema"] == "simplicio.fast.ingest/v2"
    assert ingest_payload["mapper"]["mode"] == "integrated"
    assert ingest_payload["mapper"]["producer"]["name"] == "simplicio-mapper"
    projection = build_payload_from_mapper(root, envelope)
    assert projection["completeness"] == "partial"
    assert any(
        item["code"] == "mapper_relation_confidence_unavailable"
        for item in projection["diagnostics"]
    )

    plan = _run_fast(
        root,
        "plan",
        "change helper",
        "--root",
        str(root),
        "--snapshot",
        str(snapshot),
        "--mapper-mode",
        "integrated",
        "--mapper-handoff",
        str(external_handoff),
    )
    assert plan.returncode == 0, plan.stderr + plan.stdout
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["schema"] == "simplicio.fast.plandag/v2"
    assert plan_payload["nodes"]


@pytest.mark.parametrize("status", ["partial", "blocked"])
def test_partial_or_blocked_mapper_receipt_stays_fail_closed(
    tmp_path: Path, status: str
) -> None:
    root = tmp_path / "repo"
    commit = _make_repo(root)
    artifact = root / ".simplicio" / "context-snapshot.json"
    artifact.parent.mkdir()
    artifact.write_text('{"schema":"simplicio.context-snapshot/v1"}\n', encoding="utf-8")
    envelope = {
        "handoff": {
            "schema": "simplicio.mapper-fast-handoff/v1",
            "repository_id": root.name,
            "revision": commit,
            "generation": "g1",
            "producer": {"name": "simplicio-mapper", "version": "0.26.31"},
            "fidelity": {"gate": "ready"},
            "artifacts": [
                {
                    "name": "context_snapshot",
                    "path": ".simplicio/context-snapshot.json",
                    "bytes": artifact.stat().st_size,
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }
            ],
            "delta": {"changed_paths": []},
        },
        "receipt": {
            "schema": "simplicio.mapper-fast-handoff-receipt/v1",
            "status": status,
            "handoff_sha256": "a" * 64,
        },
    }
    external_handoff = tmp_path / f"mapper-{status}.json"
    external_handoff.write_text(
        json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = _run_fast(
        root,
        "ingest",
        str(root),
        "--output",
        str(tmp_path / "fast.sfast"),
        "--mapper-mode",
        "integrated",
        "--mapper-handoff",
        str(external_handoff),
        "--json",
    )
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["schema"] == "simplicio.fast.error/v1"
    assert payload["error"] == "MapperIngestError"
    assert payload["reason_code"] == "mapper_incomplete"
    assert payload["message"].startswith("mapper_incomplete")
