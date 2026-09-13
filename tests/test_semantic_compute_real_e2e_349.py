from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from simplicio_fast.delivery import DeliveryEngine
from simplicio_fast.engine import select_engine
from simplicio_fast.knowledge_projection import KnowledgeFact, KnowledgeProjection
from simplicio_fast.mapper_ingest import validate_handoff
from simplicio_fast.mapper_snapshot import compile_mapper_payload
from simplicio_fast.operations_projection import OperationReceipt, OperationsProjection
from simplicio_fast.parser_adapter import build_payload_from_mapper
from simplicio_fast.projection import ProjectionEnvelope
from simplicio_fast.universal_context import compile_context


def _run_json(command: list[str], *, cwd: Path) -> dict[str, object]:
    result = subprocess.run(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


def _run_mapper(root: Path, *args: str, json_output: bool = True) -> dict[str, object]:
    executable = shutil.which("simplicio-mapper")
    assert executable is not None, "simplicio-mapper is required for real E2E"
    result = subprocess.run(
        [executable, *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    if not json_output:
        return {}
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


def _git_fixture(root: Path) -> None:
    (root / "service.py").write_text(
        "def helper():\n    return True\n\ndef run():\n    return helper()\n",
        encoding="utf-8",
    )
    commands = (
        ["git", "init", "--quiet"],
        ["git", "config", "user.email", "e2e@example.invalid"],
        ["git", "config", "user.name", "Semantic E2E"],
        ["git", "add", "service.py"],
        ["git", "commit", "--quiet", "-m", "initial"],
    )
    for command in commands:
        subprocess.run(command, cwd=root, check=True, stdin=subprocess.DEVNULL)


def test_real_mapper_runtime_devcli_loop_to_context_e2e(tmp_path: Path) -> None:
    root = tmp_path / "real-semantic-e2e"
    root.mkdir()
    _git_fixture(root)

    _run_mapper(root, "snapshot", "build", "--root", str(root), json_output=False)
    handoff = _run_mapper(root, "fast-handoff", str(root))
    mapper = validate_handoff(root, handoff)
    snapshot = root / "fast.sfast"
    compile_mapper_payload(
        root,
        build_payload_from_mapper(root, handoff),
        snapshot,
        mapper_generation=str(mapper["generation"]),
        handoff_sha256=str(mapper["handoff_sha256"]),
        mapper_provenance=mapper,
    )
    delivery = DeliveryEngine(root, snapshot).prepare(
        "understand helper",
        profile="loop-standalone",
        engine_receipt=select_engine("python").receipt(),
        mode="integrated",
        mapper_handoff=handoff,
    )
    assert mapper["mode"] == "integrated"
    assert delivery["mapper"]["traceability"] == "mapper-symbol-id"

    generation = str(mapper["generation"])
    code = ProjectionEnvelope.create(
        "code",
        producer="simplicio-mapper",
        producer_schema="simplicio.mapper-fast-handoff/v1",
        generation=generation,
        stable_handle="code:helper",
        repository_scope=root.name,
        payload={"handles": ["helper"], "generation": generation},
    )
    digest = "sha256:" + hashlib.sha256(b"real precedent").hexdigest()
    knowledge_index = KnowledgeProjection(root.name, "tenant-a", generation)
    knowledge_index.apply_delta([
        KnowledgeFact(
            "precedent", "mapper", "knowledge:precedent", "v1", ("mapper:real",),
            "verified", digest, "helper contract", root.name, "tenant-a",
        )
    ])
    knowledge = ProjectionEnvelope.create(
        "knowledge",
        producer="simplicio-fast.knowledge",
        producer_schema="simplicio.fast.knowledge-projection/v1",
        generation=generation,
        stable_handle="knowledge:precedent",
        repository_scope=root.name,
        payload={"handles": knowledge_index.query("helper contract")["handles"]},
    )
    operations_index = OperationsProjection(root.name, generation)
    operations_index.ingest([
        OperationReceipt(
            "attempt:1", "attempt", "complete", generation, 1,
            "runtime.receipt/v1", {"producer": "runtime", "status": "complete"},
        )
    ])
    operations = ProjectionEnvelope.create(
        "operations",
        producer="runtime",
        producer_schema="runtime.receipt/v1",
        generation=generation,
        stable_handle="operations:attempt:1",
        repository_scope=root.name,
        payload={"status": operations_index.query(status="complete")[0]["status"]},
    )
    context = compile_context(
        [operations, knowledge, code],
        repository_scope=root.name,
        max_bytes=32_000,
        max_tokens=4_000,
    )
    assert context["projection_count"] == 3
    assert context["source_generations"] == [generation]
    assert all("mmap_offset" not in item for item in context["projections"])

    project_root = Path(__file__).parents[1]
    runtime = _run_json(
        ["simplicio-runtime", "contracts", "smoke", "--json", "--repo", str(project_root)],
        cwd=root,
    )
    dev_cli = _run_json(["simplicio-py", "smoke", "--json", "--root", str(root)], cwd=root)
    loop = _run_json(["simplicio-loop", "preflight", "--repo", str(root), "--json"], cwd=root)
    assert runtime["status"] == "passed"
    assert dev_cli["schema"] == "simplicio.dev-cli.smoke/v1"
    assert loop["all_present"] is True
