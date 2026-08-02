from __future__ import annotations

import pytest

from simplicio import pipeline_preparation
from simplicio.execution_mode import ExecutionInputError


def test_prepare_pipeline_inputs_builds_immutable_route_inputs(tmp_path):
    prepared = pipeline_preparation.prepare_pipeline_inputs(
        "standalone",
        root=tmp_path,
        repo_root=tmp_path,
        scope_root=tmp_path,
    )

    assert prepared.input.actual_root == tmp_path.resolve()
    assert prepared.requested_execution_mode == "standalone"
    assert prepared.profile.effective_mode == "standalone"
    assert prepared.execution.attempt is None


def test_prepare_pipeline_inputs_preserves_fail_closed_input_errors(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise ExecutionInputError("INCOMPATIBLE_CONTEXT", "invalid context")

    monkeypatch.setattr(pipeline_preparation, "prepare_execution_inputs", fail)

    with pytest.raises(ExecutionInputError, match="INCOMPATIBLE_CONTEXT"):
        pipeline_preparation.prepare_pipeline_inputs("auto", root=tmp_path)
