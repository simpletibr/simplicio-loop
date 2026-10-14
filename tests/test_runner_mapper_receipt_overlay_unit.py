"""The runner preflight accepts the artifacts an overlay does not serve (#1673) and still needs the ones it does.

A worktree with a valid `overlay.json` serves `project_map`, `symbol_index` and `precedent_index`. The other three
(`call_graph`, `architecture_inventory`, `retrieval_index`) are `not_served_by_overlay` by design and have `exists: false`.
That is not a missing artifact, so it must not stop the run (`mapper artifact evidence is incomplete`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from simplicio_loop import runner

SERVED = ("project_map", "symbol_index", "precedent_index")
NOT_SERVED = ("call_graph", "architecture_inventory", "retrieval_index")


def _payload(served_exist=True, served=SERVED, not_served=NOT_SERVED, extra=None):
    artifacts = {name: {"exists": served_exist, "state": "served_by_overlay"} for name in served}
    artifacts.update({name: {"exists": False, "state": "not_served_by_overlay"} for name in not_served})
    artifacts.update(extra or {})
    return {"inspect": {"stdout": {"status": {"artifacts_present": True, "fresh": True},
                                  "evidence": {"artifacts": artifacts}}}}


def test_the_artifacts_an_overlay_does_not_serve_do_not_block_the_run(tmp_path):
    runner._validate_mapper_receipt(_payload(), Path(tmp_path))


def test_a_full_index_with_every_artifact_present_still_passes(tmp_path):
    payload = _payload(served=SERVED + NOT_SERVED, not_served=())
    runner._validate_mapper_receipt(payload, Path(tmp_path))


def test_a_served_artifact_that_is_missing_still_blocks(tmp_path):
    with pytest.raises(RuntimeError, match="mapper artifact evidence is incomplete"):
        runner._validate_mapper_receipt(_payload(served_exist=False), Path(tmp_path))


def test_one_missing_artifact_without_the_overlay_state_still_blocks(tmp_path):
    payload = _payload(extra={"call_graph": {"exists": False, "state": "missing"}})
    with pytest.raises(RuntimeError, match="mapper artifact evidence is incomplete"):
        runner._validate_mapper_receipt(payload, Path(tmp_path))


def test_an_evidence_with_nothing_served_still_blocks(tmp_path):
    payload = _payload(served=(), not_served=SERVED + NOT_SERVED)
    with pytest.raises(RuntimeError, match="mapper artifact evidence is incomplete"):
        runner._validate_mapper_receipt(payload, Path(tmp_path))
