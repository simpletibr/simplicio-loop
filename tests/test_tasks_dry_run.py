from __future__ import annotations

import hashlib

from simplicio_loop import tasks_live


def test_live_dry_run_uses_read_only_orchestrator_path_without_agent_pipeline(tmp_path):
    observed = {}

    class Source:
        def __init__(self, owner, repo, **kwargs):
            observed["source"] = (owner, repo)
            observed["publish_comment_fn"] = kwargs["publish_comment_fn"]

    class Intake:
        def __init__(self, **kwargs):
            observed["intake"] = kwargs

        def run(self, request):
            observed["request"] = request
            return {"outcome": {"status": "PLANNED_NOT_EXECUTED"}}

    def forbidden_pipeline(*args, **kwargs):
        raise AssertionError("dry-run must not construct the agent pipeline")

    def forbidden_queue(*args, **kwargs):
        raise AssertionError("dry-run must not create a worktree queue")

    result = tasks_live.run_live(
        "finish all issues in acme/widgets",
        workspace=str(tmp_path),
        agent_command=(),
        action_gate=True,
        dry_run=True,
        source_factory=Source,
        intake_factory=Intake,
        pipeline_factory=forbidden_pipeline,
        queue_factory=forbidden_queue,
    )

    assert result["state"] == "partial"
    assert result["reason"] == "action_gate_required"
    assert observed["source"] == ("acme", "widgets")
    assert observed["request"] == "finish all issues in acme/widgets"
    assert callable(observed["publish_comment_fn"])


def test_live_dry_run_does_not_consume_persisted_cancellation(tmp_path):
    request = "finish all issues in acme/widgets"
    batch = hashlib.sha256(request.encode("utf-8")).hexdigest()[:16]
    journal_dir = tmp_path / ".simplicio-loop" / "tasks-run" / batch / "journals"
    journal_dir.mkdir(parents=True)
    cancel_path = journal_dir / "cancel.json"
    cancel_path.write_text('{"reason":"cancel_requested"}', encoding="utf-8")

    def forbidden_source(*args, **kwargs):
        raise AssertionError("dry-run must stop at the persisted cancellation read")

    result = tasks_live.run_live(
        request,
        workspace=str(tmp_path),
        agent_command=(),
        action_gate=True,
        dry_run=True,
        source_factory=forbidden_source,
    )

    assert result["state"] == "cancelled"
    assert result["reason"] == "persisted_cancel_observed"
    assert cancel_path.exists()
    assert not (journal_dir / "cancel.ack.json").exists()
