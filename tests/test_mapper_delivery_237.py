import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

from simplicio_fast.delivery import _mapper_symbol_handles
from simplicio_fast.mapper_ingest import MapperIngestError, validate_handoff
from simplicio_fast.mapper_snapshot import compile_mapper_payload
from simplicio_fast.parser_adapter import build_payload_from_mapper


def test_delivery_cli_defaults_to_integrated_mode() -> None:
    from simplicio_fast.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["delivery", "task"])
    assert args.mapper_mode == "integrated"
    for command in ("build", "refresh", "ingest"):
        ingest_args = parser.parse_args([command])
        assert ingest_args.mapper_mode == "integrated"
        assert ingest_args.mapper_handoff is None


def test_delivery_api_defaults_to_integrated_and_requires_mapper_handoff(tmp_path: Path) -> None:
    from simplicio_fast.delivery import DeliveryEngine

    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text("def run():\n    return True\n", encoding="utf-8")
    with pytest.raises(MapperIngestError, match="mapper_missing"):
        DeliveryEngine(root, root / "fast.sfast").prepare(
            "understand run",
            profile="loop-standalone",
            engine_receipt={"backend": "python"},
        )


def _provenance(path: str = ".simplicio/context-snapshot.json") -> dict[str, object]:
    return {"artifacts": [{"name": "context_snapshot", "path": path}]}


def test_mapper_symbol_handles_preserve_public_ids(tmp_path: Path) -> None:
    artifact = tmp_path / ".simplicio" / "context-snapshot.json"
    artifact.parent.mkdir()
    artifact.write_text(
        json.dumps(
            {
                "schema": "simplicio.context-snapshot/v1",
                "graph": {
                    "nodes": [
                        {
                            "id": "symbol:service.py::run",
                            "source": {"file": "service.py", "line": 7},
                        },
                        {
                            "id": "file:service.py",
                            "source": {"file": "service.py", "line": 1},
                        },
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    assert _mapper_symbol_handles(tmp_path, _provenance()) == {
        ("service.py", 7): "symbol:service.py::run"
    }


def test_integrated_traceability_fails_closed_without_symbol_nodes(tmp_path: Path) -> None:
    artifact = tmp_path / ".simplicio" / "context-snapshot.json"
    artifact.parent.mkdir()
    artifact.write_text(
        json.dumps(
            {
                "schema": "simplicio.context-snapshot/v1",
                "graph": {"nodes": [{"id": "file:service.py"}]},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(MapperIngestError, match="mapper_graph_missing"):
        _mapper_symbol_handles(tmp_path, _provenance())


@pytest.mark.parametrize(
    "graph",
    [[], {"schema": "simplicio.context-snapshot/v1", "graph": []}],
)
def test_malformed_mapper_graph_fails_closed_with_stable_reason(
    tmp_path: Path, graph: object
) -> None:
    artifact = tmp_path / ".simplicio" / "context-snapshot.json"
    artifact.parent.mkdir()
    artifact.write_text(json.dumps(graph), encoding="utf-8")

    with pytest.raises(MapperIngestError, match="mapper_schema_unsupported|mapper_graph_missing"):
        _mapper_symbol_handles(tmp_path, _provenance())


def test_malformed_mapper_artifacts_fail_closed_with_stable_reason(tmp_path: Path) -> None:
    with pytest.raises(MapperIngestError, match="mapper_graph_missing"):
        _mapper_symbol_handles(tmp_path, {"artifacts": [1]})


def test_installed_mapper_to_integrated_delivery_traceability(tmp_path: Path) -> None:
    executable = shutil.which("simplicio-mapper")
    if executable is None:
        pytest.fail("simplicio-mapper is required for installed delivery E2E")
    root = tmp_path / "mapper-delivery"
    root.mkdir()
    (root / "service.py").write_text(
        "def helper():\n    return True\n\ndef test_helper():\n    return helper()\n",
        encoding="utf-8",
    )

    def run(*args: str) -> str:
        with tempfile.TemporaryDirectory(prefix="simplicio-fast-e2e-") as logs:
            stdout_path = Path(logs) / "stdout.txt"
            stderr_path = Path(logs) / "stderr.txt"
            with (
                stdout_path.open("w", encoding="utf-8") as stdout,
                stderr_path.open("w", encoding="utf-8") as stderr,
            ):
                result = subprocess.run(
                    [*args],
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    check=False,
                )
            assert result.returncode == 0, stderr_path.read_text(encoding="utf-8")
            return stdout_path.read_text(encoding="utf-8", errors="replace")

    for command in (
        ["git", "init", "--quiet"],
        ["git", "config", "user.email", "e2e@example.invalid"],
        ["git", "config", "user.name", "Fast E2E"],
        ["git", "add", "service.py"],
        ["git", "commit", "--quiet", "-m", "initial"],
    ):
        subprocess.run(
            command,
            cwd=root,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    run(executable, "snapshot", "build", "--root", str(root))
    envelope = json.loads(run(executable, "fast-handoff", str(root)))
    snapshot = root / "fast.sfast"
    provenance = validate_handoff(root, envelope)
    compile_mapper_payload(
        root,
        build_payload_from_mapper(root, envelope),
        snapshot,
        mapper_generation=str(provenance["generation"]),
        handoff_sha256=str(provenance["handoff_sha256"]),
        mapper_provenance=provenance,
    )

    from simplicio_fast.delivery import DeliveryEngine

    receipt = DeliveryEngine(root, snapshot, root / "cache").prepare(
        "helper",
        profile="loop-standalone",
        engine_receipt={"backend": "python"},
        mode="integrated",
        mapper_handoff=envelope,
    )
    assert receipt["mapper"]["traceability"] == "mapper-symbol-id"
    assert receipt["mapper"]["selected_handles"]
    assert all(
        span["handle"].startswith("symbol:")
        for span in receipt["context"]["selected"]
    )
