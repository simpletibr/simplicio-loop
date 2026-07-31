"""Issue #405 proposal-only authority and no-write contract."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplicio import pipeline_integrated as integrated
from simplicio.atomic_execution import AttemptContext

HANDLE = "sha256:" + "4" * 64


class ReadOnlyCache:
    def __init__(self, _root):
        pass

    def lookup(self, handle):
        return {"schema": "simplicio.context-binding-cache/v1", "hit": False, "context_handle": handle.value}

    def refresh(self, _binding):
        raise AssertionError("proposal-only must not refresh the context binding cache")


def _inputs(tmp_path: Path) -> dict:
    snapshot = {
        "schema": "simplicio.context-snapshot/v1",
        "snapshot_id": "snapshot-405",
        "revision": "rev-405",
    }
    pack = {"schema": "simplicio.context-pack/v1", "pack_hash": "pack-405"}
    view = SimpleNamespace(snapshot_id="snapshot-405", revision="rev-405", root_hash="root-405")
    handle = SimpleNamespace(
        value=HANDLE,
        to_dict=lambda: {
            "schema": "simplicio.dev-cli.context-handle/v1",
            "source_digest": "a" * 64,
            "projection_digest": "b" * 64,
        },
    )
    binding = SimpleNamespace(
        snapshot=SimpleNamespace(view=view), pack=SimpleNamespace(pack_hash="pack-405"), context_handle=handle
    )
    return {
        "root": str(tmp_path),
        "stack": "python",
        "goal": "prepare proposal",
        "target": "src/app.py",
        "criteria": "- source remains unchanged",
        "constraints": "- no writer is reachable",
        "primary_test_cmd": "python -m pytest -q",
        "authorization": None,
        "context_snapshot": snapshot,
        "context_pack": pack,
        "attempt": AttemptContext("attempt-405", "lease-405", "fence-405", HANDLE),
        "binding": binding,
    }


def _install_pure_boundary(monkeypatch, inputs):
    monkeypatch.setattr(integrated, "bind_mapper_context", lambda *args, **kwargs: inputs["binding"])
    monkeypatch.setattr(integrated, "verify_context_sources", lambda *args, **kwargs: None)
    monkeypatch.setattr(integrated, "ContextBindingCache", ReadOnlyCache)


def _proposal(inputs):
    kwargs = {key: value for key, value in inputs.items() if key not in {"binding"}}
    return integrated.run_integrated(
        prompt="deterministic prompt",
        effect_sink=None,
        proposal_only=True,
        **kwargs,
    )


def test_proposal_only_is_deterministic_and_has_no_effect_boundary(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    _install_pure_boundary(monkeypatch, inputs)

    class ExplodingRuntimeSink:
        @classmethod
        def from_environment(cls, **_kwargs):
            raise AssertionError("proposal-only must not construct RuntimeEffectSink")

    monkeypatch.setattr(integrated, "RuntimeEffectSink", ExplodingRuntimeSink)
    monkeypatch.setattr(
        integrated,
        "emit_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("proposal emitted an event")),
    )
    before = {
        str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }

    first = _proposal(inputs)
    second = _proposal(inputs)

    assert first["status"] == "proposal_only"
    assert first["proposal"]["schema"] == "simplicio.change-proposal/v1"
    assert first["proposal"]["envelope"] == "simplicio.change-proposal-envelope/v1"
    assert first["proposal"]["dispatch_context"]["authorization"] is None
    assert first["proposal_digest"] == first["proposal"]["proposal_digest"]
    assert json.dumps(first["proposal"], sort_keys=True, separators=(",", ":")) == json.dumps(
        second["proposal"], sort_keys=True, separators=(",", ":")
    )
    after = {
        str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }
    assert after == before


def test_proposal_only_rejects_multiple_effects(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    _install_pure_boundary(monkeypatch, inputs)
    real_compile = integrated.compile_task_spec_to_plan

    def multi_effect(*args, **kwargs):
        plan, effects, verifications = real_compile(*args, **kwargs)
        return plan, effects + [effects[0]], verifications

    monkeypatch.setattr(integrated, "compile_task_spec_to_plan", multi_effect)
    with pytest.raises(integrated.IntegratedPreparationError, match="MULTI_EFFECT"):
        integrated.prepare_integrated_work_item(
            **{key: value for key, value in inputs.items() if key != "binding"}, proposal_only=True
        )


def test_proposal_only_rejects_path_escape(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    _install_pure_boundary(monkeypatch, inputs)
    real_compile = integrated.compile_task_spec_to_plan

    def escaping_plan(*args, **kwargs):
        plan, effects, verifications = real_compile(*args, **kwargs)
        effect_node = effects[0].plan_node_id
        nodes = [
            replace(node, write_set=["../escape.py"]) if node.node_id == effect_node else node
            for node in plan.nodes
        ]
        return replace(plan, nodes=nodes), effects, verifications

    monkeypatch.setattr(integrated, "compile_task_spec_to_plan", escaping_plan)
    with pytest.raises(integrated.IntegratedPreparationError, match="WRITE_SET_ESCAPE"):
        integrated.prepare_integrated_work_item(
            **{key: value for key, value in inputs.items() if key != "binding"}, proposal_only=True
        )
