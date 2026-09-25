import json

from simplicio.stage_main import run_stage_or_legacy
from tests.python.mutation_353_helpers import plan


def test_mutable_stage_handler_gets_pre_and_post_receipt_and_replay(tmp_path, monkeypatch):
    p = plan()
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(p))
    monkeypatch.setenv("SIMPLICIO_STAGE_ABI", "1")
    monkeypatch.setenv("SIMPLICIO_MECHANICAL_PLAN", str(path))
    monkeypatch.setenv("SIMPLICIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("SIMPLICIO_IDEMPOTENCY_KEY", "k")
    calls = []

    def handler(_):
        calls.append(1)
        (tmp_path / "app.py").write_text("changed")
        return 0

    assert run_stage_or_legacy(["edit"], handler) == 0
    assert run_stage_or_legacy(["edit"], handler) == 0
    assert len(calls) == 1


def test_read_only_and_legacy_are_compatible(tmp_path, monkeypatch):
    calls = []

    def handler(argv):
        calls.append(argv)
        return 0

    assert run_stage_or_legacy(["edit"], handler) == 0
    monkeypatch.setenv("SIMPLICIO_STAGE_ABI", "1")
    assert run_stage_or_legacy(["status"], handler) == 0
    assert len(calls) == 2
