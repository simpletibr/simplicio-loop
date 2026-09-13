from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from simplicio_fast.mapper_ingest import MapperIngestError, validate_handoff
from simplicio_fast.mapper_snapshot import compile_mapper_payload
from simplicio_fast.parser_adapter import build_payload_from_mapper
from simplicio_fast.delivery import DeliveryEngine
from simplicio_fast.engine import select_engine
from simplicio_fast.snapshot import Snapshot


def _run_mapper(
    root: Path, *args: str, json_output: bool = True
) -> dict[str, object] | str:
    executable = shutil.which("simplicio-mapper")
    if executable is None:
        raise AssertionError("simplicio-mapper is required for installed E2E")
    with tempfile.TemporaryDirectory() as directory:
        stdout_path = Path(directory) / "stdout.json"
        stderr_path = Path(directory) / "stderr.txt"
        with (
            stdout_path.open("w", encoding="utf-8") as stdout,
            stderr_path.open("w", encoding="utf-8") as stderr,
        ):
            result = subprocess.run(
                [executable, *args],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                text=True,
                check=False,
            )
        if result.returncode:
            raise AssertionError(stderr_path.read_text(encoding="utf-8"))
        output = stdout_path.read_text(encoding="utf-8", errors="replace")
        return json.loads(output) if json_output else output


def _envelope(root: Path, commit: str) -> dict[str, object]:
    artifact = root / ".simplicio" / "context-snapshot.json"
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_text(
        '{"schema":"simplicio.context-snapshot/v1"}\n', encoding="utf-8"
    )
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return {
        "handoff": {
            "schema": "simplicio.mapper-fast-handoff/v1",
            "repository_id": root.name,
            "revision": commit,
            "generation": "g1",
            "producer": {"name": "simplicio-mapper", "version": "0.26.5"},
            "fidelity": {"gate": "ready"},
            "artifacts": [
                {
                    "name": "context_snapshot",
                    "path": ".simplicio/context-snapshot.json",
                    "bytes": artifact.stat().st_size,
                    "sha256": digest,
                }
            ],
            "delta": {"changed_paths": []},
        },
        "receipt": {
            "schema": "simplicio.mapper-fast-handoff-receipt/v1",
            "status": "parsed",
            "handoff_sha256": "a" * 64,
        },
    }


def test_validates_mapper_owned_handoff_and_artifact_digest(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        provenance = validate_handoff(root, _envelope(root, "a" * 40))
    assert provenance["mode"] == "integrated"
    assert provenance["producer"]["name"] == "simplicio-mapper"
    assert provenance["generation"] == "g1"


def test_accepts_complete_reused_mapper_handoff(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    envelope = _envelope(root, "a" * 40)
    envelope["receipt"]["status"] = "reused"
    envelope["receipt"]["counters"] = {
        "parsed": 0,
        "reused": 1,
        "degraded": 0,
        "fallback": 0,
    }
    del envelope["handoff"]["fidelity"]
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        provenance = validate_handoff(root, envelope)
    assert provenance["mode"] == "integrated"


def test_preserves_and_validates_mapper_deleted_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    envelope = _envelope(root, "a" * 40)
    envelope["handoff"]["delta"] = {
        "changed_paths": ["src/changed.py"],
        "deleted_paths": ["src/removed.py"],
    }
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        provenance = validate_handoff(root, envelope)
    assert provenance["changed_paths"] == ["src/changed.py"]
    assert provenance["deleted_paths"] == ["src/removed.py"]

    envelope["handoff"]["delta"]["deleted_paths"] = ["../outside.py"]
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        with pytest.raises(MapperIngestError, match="mapper_schema_unsupported"):
            validate_handoff(root, envelope)


def test_tampered_mapper_artifact_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        envelope = _envelope(root, "a" * 40)
    artifact = root / ".simplicio" / "context-snapshot.json"
    artifact.write_text('{"tampered":true}\n', encoding="utf-8")
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        with pytest.raises(MapperIngestError, match="mapper_digest_mismatch"):
            validate_handoff(root, envelope)


def test_missing_generation_and_malformed_receipt_digest_fail_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    envelope = _envelope(root, "a" * 40)
    envelope["handoff"]["generation"] = ""
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        with pytest.raises(MapperIngestError, match="mapper_generation_stale"):
            validate_handoff(root, envelope)
    envelope = _envelope(root, "a" * 40)
    envelope["receipt"]["handoff_sha256"] = "not-a-digest"
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        with pytest.raises(MapperIngestError, match="mapper_incomplete"):
            validate_handoff(root, envelope)


def test_artifact_metadata_is_validated_before_filesystem_use(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    envelope = _envelope(root, "a" * 40)
    envelope["handoff"]["artifacts"][0]["sha256"] = "short"
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        with pytest.raises(MapperIngestError, match="mapper_schema_unsupported"):
            validate_handoff(root, envelope)


def test_installed_mapper_handoff_is_accepted(tmp_path: Path) -> None:
    root = tmp_path / "mapper-e2e"
    root.mkdir()
    (root / "service.py").write_text(
        "def helper():\n    return True\n\ndef run():\n    return helper()\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "config", "user.email", "e2e@example.invalid"],
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "config", "user.name", "Mapper E2E"],
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "add", "service.py"],
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "initial"],
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    _run_mapper(root, "snapshot", "build", "--root", str(root), json_output=False)
    envelope = _run_mapper(root, "fast-handoff", str(root))
    provenance = validate_handoff(root, envelope)
    reused_envelope = _run_mapper(root, "fast-handoff", str(root))
    reused_provenance = validate_handoff(root, reused_envelope)

    assert provenance["mode"] == "integrated"
    assert provenance["producer"]["name"] == "simplicio-mapper"
    assert provenance["commit"]
    assert len(provenance["artifacts"]) >= 3
    assert reused_envelope["receipt"]["status"] == "reused"
    assert reused_provenance["generation"] == provenance["generation"]

    snapshot = root / "fast.sfast"
    compile_mapper_payload(
        root,
        build_payload_from_mapper(root, envelope),
        snapshot,
        mapper_generation=str(provenance["generation"]),
        handoff_sha256=str(provenance["handoff_sha256"]),
        mapper_provenance=provenance,
    )
    receipt = DeliveryEngine(root, snapshot).prepare(
        "understand helper",
        profile="loop-standalone",
        engine_receipt=select_engine("python").receipt(),
        mode="integrated",
        mapper_handoff=envelope,
    )
    assert receipt["mapper"]["mode"] == "integrated"
    assert receipt["mapper"]["traceability"] == "mapper-symbol-id"
    assert receipt["context"]["selected"]
    compiled = json.loads(
        (snapshot.with_name(snapshot.name + ".mapper.json")).read_text(
            encoding="utf-8"
        )
    )
    assert compiled["schema"] == "simplicio.fast.mapper-snapshot/v1"
    assert compiled["mapper_generation"] == provenance["generation"]
    assert compiled["symbols"] >= 2

    def read_generation() -> tuple[str, int]:
        with Snapshot(snapshot) as reader:
            return reader.generation, len(reader.context(root, "helper"))

    with ThreadPoolExecutor(max_workers=20) as pool:
        readers = list(pool.map(lambda _: read_generation(), range(20)))
    assert len(readers) == 20
    assert {generation for generation, _ in readers} == {compiled["fast_generation"]}
    assert all(count >= 1 for _, count in readers)


def test_ten_physical_worktrees_keep_integrated_generations_isolated(tmp_path: Path) -> None:
    executable = shutil.which("simplicio-mapper")
    if executable is None:
        pytest.fail("simplicio-mapper is required for physical worktree E2E")
    base = tmp_path / "base"
    base.mkdir()
    (base / "service.py").write_text(
        "def helper():\n    return -1\n", encoding="utf-8"
    )
    for command in (
        ["git", "init", "--quiet"],
        ["git", "config", "user.email", "e2e@example.invalid"],
        ["git", "config", "user.name", "Mapper Worktree E2E"],
        ["git", "add", "service.py"],
        ["git", "commit", "--quiet", "-m", "initial"],
    ):
        subprocess.run(
            command,
            cwd=base,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    worktrees: list[Path] = []
    generations: list[str] = []
    try:
        for index in range(10):
            worktree = tmp_path / f"worktree-{index}"
            subprocess.run(
                ["git", "worktree", "add", "--detach", "--quiet", str(worktree), "HEAD"],
                cwd=base,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            worktrees.append(worktree)
            (worktree / "service.py").write_text(
                f"def helper():\n    return {index}\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "add", "service.py"],
                cwd=worktree,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=e2e@example.invalid",
                    "-c",
                    "user.name=Mapper Worktree E2E",
                    "commit",
                    "--quiet",
                    "-m",
                    f"worktree {index}",
                ],
                cwd=worktree,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _run_mapper(worktree, "snapshot", "build", "--root", str(worktree), json_output=False)
            envelope = _run_mapper(worktree, "fast-handoff", str(worktree))
            provenance = validate_handoff(worktree, envelope)
            snapshot = worktree / "fast.sfast"
            receipt = DeliveryEngine(worktree, snapshot).prepare(
                "understand helper",
                profile="loop-standalone",
                engine_receipt=select_engine("python").receipt(),
                mode="integrated",
                mapper_handoff=envelope,
            )
            assert provenance["mode"] == "integrated"
            assert receipt["mapper"]["traceability"] == "mapper-symbol-id"
            selected = receipt["context"]["selected"]
            assert selected
            generations.append(str(selected[0]["generation"]))
            assert all(item["handle"].startswith("symbol:") for item in selected)
    finally:
        for worktree in reversed(worktrees):
            subprocess.run(
                ["git", "worktree", "remove", "--force", "--quiet", str(worktree)],
                cwd=base,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    assert len(generations) == 10
    assert len(set(generations)) == 10
