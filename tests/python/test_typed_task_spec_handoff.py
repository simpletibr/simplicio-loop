from __future__ import annotations

import hashlib
import io
import json

import pytest

from simplicio import pipeline
from simplicio.atomic_execution import AttemptContext
from simplicio.plan_compiler import RecordingEffectSink
from simplicio.task_spec import TASK_SPEC_SCHEMA, TaskSpec, TaskSpecDocument, TaskSpecValidationError


def _payload() -> dict:
    return {
        "schema": TASK_SPEC_SCHEMA,
        "task_id": "TASK-299",
        "source": {"kind": "github", "locator": "issue:299"},
        "source_hash": hashlib.sha256(b"typed task").hexdigest(),
        "language": "pt-BR",
        "functionality": "Preservar o contrato tipado",
        "narrative": {"goal": "Entregar TaskSpec sem perdas"},
        "acceptance_criteria": [{"id": "AC1", "text": "todos os campos chegam ao compilador"}],
        "business_rules": [{"id": "RN1", "text": "nao reconstruir de texto"}],
        "non_functional_requirements": [{"id": "NFR1", "text": "deterministico"}],
        "dependencies": [{"id": "DEP1", "text": "simplicio-loop"}],
        "uncertainties": [{"id": "U1", "text": "versao do consumidor"}],
        "human_gates": [{"id": "HG1", "question": "aprovar migracao?"}],
        "verification_commands": [{"command": "pytest -q", "verifier": "pytest"}],
        "original_text": "typed task",
        "future_additive_field": {"preserved": True},
    }


def _assert_export_preserved(task: TaskSpec) -> None:
    exported = task.to_dict()
    for key, value in _payload().items():
        assert exported[key] == value


def test_task_spec_round_trip_is_lossless_and_hash_is_stable() -> None:
    payload = _payload()
    task = TaskSpec.from_dict(payload)

    _assert_export_preserved(task)
    assert TaskSpec.from_dict(task.to_dict()).canonical_hash() == task.canonical_hash()


def test_programmatic_additive_fields_cannot_override_canonical_identity() -> None:
    with pytest.raises(TaskSpecValidationError, match="collide"):
        TaskSpec(
            task_id="TASK-299",
            source={"kind": "argument"},
            source_hash="0" * 64,
            language="pt-BR",
            acceptance_criteria=[{"id": "AC1"}],
            extra_fields={"schema": "evil/v9", "task_id": "TASK-EVIL"},
        )


def test_task_spec_document_requires_one_or_more_valid_tasks() -> None:
    document = TaskSpecDocument.from_dict({"schema": TASK_SPEC_SCHEMA, "tasks": [_payload()]})
    assert document.tasks[0].task_id == "TASK-299"

    with pytest.raises(TaskSpecValidationError, match="at least one"):
        TaskSpecDocument.from_dict({"schema": TASK_SPEC_SCHEMA, "tasks": []})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema", "simplicio.task-spec/v3", "unsupported"),
        ("source_hash", "not-a-digest", "SHA-256"),
        ("acceptance_criteria", [], "non-empty"),
    ],
)
def test_task_spec_rejects_incompatible_or_incomplete_payloads(
    field: str, value: object, message: str
) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(TaskSpecValidationError, match=message):
        TaskSpec.from_dict(payload)


def test_task_spec_rejects_structurally_invalid_payloads() -> None:
    with pytest.raises(TaskSpecValidationError, match="must be an object"):
        TaskSpec.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(TaskSpecValidationError, match="missing required"):
        TaskSpec.from_dict({"schema": TASK_SPEC_SCHEMA})

    bad_source = _payload()
    bad_source["source"] = "github"
    with pytest.raises(TaskSpecValidationError, match="source must be"):
        TaskSpec.from_dict(bad_source)

    bad_criteria = _payload()
    bad_criteria["acceptance_criteria"] = ["AC1"]
    with pytest.raises(TaskSpecValidationError, match="acceptance_criteria"):
        TaskSpec.from_dict(bad_criteria)

    duplicate = _payload()
    duplicate["acceptance_criteria"] = [{"id": "AC1"}, {"id": "AC1"}]
    with pytest.raises(TaskSpecValidationError, match="duplicate"):
        TaskSpec.from_dict(duplicate)

    wrong_content = _payload()
    wrong_content["original_text"] = "different"
    with pytest.raises(TaskSpecValidationError, match="does not match"):
        TaskSpec.from_dict(wrong_content)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("narrative", "not-an-object", "narrative"),
        ("business_rules", ["RN1"], "business_rules"),
        ("impact_signals", [], "impact_signals"),
        ("source_span", [], "source_span"),
        ("original_text", 7, "original_text"),
        ("verification_commands", [{"verifier": "pytest"}], "verification command"),
        (
            "verification_commands",
            [{"command": "pytest -q", "verifier": ""}],
            "verifier",
        ),
        (
            "verification_commands",
            [{"command": "pytest -q", "timeout_s": "slow"}],
            "timeout_s",
        ),
        ("future_number", float("nan"), "NaN"),
    ],
)
def test_task_spec_rejects_malformed_known_fields_and_non_finite_values(
    field: str, value: object, message: str
) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(TaskSpecValidationError, match=message):
        TaskSpec.from_dict(payload)


def test_task_spec_document_rejects_non_document_payloads() -> None:
    with pytest.raises(TaskSpecValidationError, match="must be an object"):
        TaskSpecDocument.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(TaskSpecValidationError, match="unsupported"):
        TaskSpecDocument.from_dict({"schema": "simplicio.task-spec/v1", "tasks": []})


def test_integrated_pipeline_passes_original_task_spec_to_compiler(tmp_path, monkeypatch) -> None:
    task = TaskSpec.from_dict(_payload())
    captured = {}

    class Sink(RecordingEffectSink):
        test_only = False

        def __init__(self) -> None:
            super().__init__(state="running")

    context = {
        "schema": "simplicio.context-snapshot/v1",
        "snapshot_id": "snapshot-299",
        "revision": "abc299",
        "digest": "sha256:context",
    }
    mapper_view = type("View", (), {"snapshot_id": "snapshot-299", "revision": "abc299"})()
    mapper_context = type("MapperContext", (), {"payload_bytes": b"context", "view": mapper_view})()

    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr("simplicio.execution_mode.RuntimeEffectSink", Sink)
    monkeypatch.setattr("simplicio.execution_mode.load_mapper_context", lambda *a, **k: mapper_context)
    monkeypatch.setattr("simplicio.pipeline_integrated.load_mapper_context", lambda *a, **k: mapper_context)
    real_compile = __import__(
        "simplicio.pipeline_integrated", fromlist=["compile_task_spec_to_plan"]
    ).compile_task_spec_to_plan

    def capture_compile(received, **kwargs):
        captured["identity"] = received is task
        captured["payload"] = received.to_dict()
        return real_compile(received, **kwargs)

    monkeypatch.setattr("simplicio.pipeline_integrated.compile_task_spec_to_plan", capture_compile)
    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "ignored textual goal",
        "ignored.py",
        "- ignored criterion",
        "- ignored constraint",
        mode="integrated",
        effect_sink=Sink(),
        runtime_handshake={
            "verified": True,
            "version": "3.6.0",
            "capabilities": ["simplicio.effect-transaction/v1"],
            "reason": "ok",
        },
        context_snapshot=context,
        integrated_attempt=AttemptContext("attempt-299", "lease-299", "fence-299", "snapshot-299"),
        task_spec=task,
    )

    assert result["status"] == "integrated_atomic"
    assert captured["identity"] is True
    for key, value in _payload().items():
        assert captured["payload"][key] == value
    assert result["task_spec_hash"] == task.canonical_hash()


def test_standalone_pipeline_rejects_typed_task_spec_without_consuming_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "goal",
        "target.py",
        "- criterion",
        "- constraint",
        mode="standalone",
        task_spec=TaskSpec.from_dict(_payload()),
    )
    assert result["status"] == "blocked"
    assert result["blocked_preconditions"][0]["code"] == "TASK_SPEC_REQUIRES_INTEGRATED_MODE"


def test_cli_task_spec_file_loader_preserves_export(tmp_path) -> None:
    from argparse import Namespace

    from simplicio.commands.task import _load_task_spec

    path = tmp_path / "task-spec.json"
    path.write_text(
        json.dumps({"schema": TASK_SPEC_SCHEMA, "tasks": [_payload()]}),
        encoding="utf-8",
    )
    task = _load_task_spec(Namespace(task_spec=str(path), task_spec_stdin=False))
    _assert_export_preserved(task)


def test_cli_task_spec_stdin_loader_and_multi_task_rejection(monkeypatch, capsys) -> None:
    from argparse import Namespace

    from simplicio.commands.task import _load_task_spec

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"schema": TASK_SPEC_SCHEMA, "tasks": [_payload()]})),
    )
    task = _load_task_spec(Namespace(task_spec=None, task_spec_stdin=True))
    _assert_export_preserved(task)

    duplicate_document = {
        "schema": TASK_SPEC_SCHEMA,
        "tasks": [_payload(), {**_payload(), "task_id": "TASK-SECOND"}],
    }
    pathless = Namespace(task_spec=None, task_spec_stdin=True)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(duplicate_document)))
    assert _load_task_spec(pathless) is False
    assert "exactly one task" in capsys.readouterr().err


def test_cli_single_task_with_future_tasks_field_is_not_misclassified(
    monkeypatch,
) -> None:
    from argparse import Namespace

    from simplicio.commands.task import _load_task_spec

    payload = _payload()
    payload["tasks"] = {"future": "metadata"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

    task = _load_task_spec(Namespace(task_spec=None, task_spec_stdin=True))

    assert task.task_id == "TASK-299"
    assert task.to_dict()["tasks"] == {"future": "metadata"}


def test_cli_malformed_known_field_returns_invalid_input_without_traceback(monkeypatch, capsys) -> None:
    from argparse import Namespace

    from simplicio.commands.task import _load_task_spec

    payload = _payload()
    payload["narrative"] = "not-an-object"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

    assert _load_task_spec(Namespace(task_spec=None, task_spec_stdin=True)) is False
    assert "narrative must be an object" in capsys.readouterr().err
