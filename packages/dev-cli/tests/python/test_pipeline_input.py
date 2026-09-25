from pathlib import Path

from simplicio.pipeline_input import PipelineInput, prepare_pipeline_input


def test_prepare_pipeline_input_normalizes_canonical_and_supplied_identity(tmp_path):
    prepared = prepare_pipeline_input(
        tmp_path,
        repo_root=str(tmp_path),
        scope_root="scope",
        context_snapshot={"snapshot_id": " snap-1 "},
        context_pack={"pack_hash": " pack-1 "},
        context_snapshot_id="snap-1",
        context_pack_hash="pack-1",
        attempt_id="attempt-1",
        integrated_attempt=None,
    )

    assert isinstance(prepared, PipelineInput)
    assert prepared.actual_root == Path(tmp_path).resolve()
    assert prepared.declared_repo_root == Path(tmp_path).resolve()
    assert prepared.declared_scope_root == "scope"
    assert prepared.snapshot_identity == "snap-1"
    assert prepared.pack_identity == "pack-1"
    assert prepared.supplied_snapshot_id == "snap-1"
    assert prepared.supplied_pack_hash == "pack-1"
    assert prepared.attempt_identity == "attempt-1"


def test_prepare_pipeline_input_prefers_integrated_attempt_identity(tmp_path):
    class Attempt:
        attempt_id = "integrated-attempt"

    prepared = prepare_pipeline_input(
        tmp_path,
        repo_root=None,
        scope_root=None,
        context_snapshot=None,
        context_pack=None,
        context_snapshot_id=None,
        context_pack_hash=" supplied-pack ",
        attempt_id=None,
        integrated_attempt=Attempt(),
    )

    assert prepared.pack_identity == "supplied-pack"
    assert prepared.attempt_identity == "integrated-attempt"
