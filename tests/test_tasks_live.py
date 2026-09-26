import json
from pathlib import Path

from simplicio_loop import cli
from simplicio_loop import tasks_live

class Source:
    def __init__(self, owner, repo, **kwargs):
        self.owner, self.repo = owner, repo

class Intake:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
    def run(self, request):
        return {"outcome": {"status": "PLANNED_NOT_EXECUTED"}}

class Materializer:
    def __init__(self, root):
        self.root = root
    def __call__(self, plan):
        return [{"task_id": "issue-1", "task_spec": {"goal": "goal", "files_affected": ["src/a.py"]}}]

class Queue:
    instances = []
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.specs = []
        self.__class__.instances.append(self)
    def register_tasks(self, specs):
        self.specs = list(specs)

class Pipeline:
    def __init__(self, command, journal, **kwargs):
        self.command = command
    def __call__(self, dispatched):
        return {"passed": True, "evidence": [{"pr": "https://example/pr/1", "verification": "passed"}]}
    def cancel_all(self, *, reason):
        return [reason]

class Orchestrator:
    def __init__(self, intake, contracts, pipeline, **kwargs):
        self.contracts = contracts
        self.worktree_queue = None
    def run(self, request, action_gate, cancel=False):
        rows = self.contracts({})
        assert self.worktree_queue is Queue.instances[-1]
        return {"state": "completed", "rows": rows}

def test_live_composition_wires_intake_materializer_queue_and_pipeline(tmp_path):
    result = tasks_live.run_live("finish all issues in acme/widgets", workspace=str(tmp_path), agent_command=["agent"], action_gate=True, source_factory=Source, intake_factory=Intake, materializer_factory=Materializer, pipeline_factory=Pipeline, orchestrator_factory=Orchestrator, queue_factory=Queue)
    assert result["state"] == "completed"
    assert Queue.instances[-1].specs[0].id == "issue-1"
    assert Queue.instances[-1].specs[0].files_affected == ["src/a.py"]

def test_live_cancel_persists_before_source_or_intake_construction(tmp_path):
    def forbidden_source(*args, **kwargs):
        raise AssertionError("source must not be constructed during cancellation")

    request = "finish all issues in acme/widgets"
    result = tasks_live.run_live(request, workspace=str(tmp_path), agent_command=["agent"], action_gate=True, cancel=True, source_factory=forbidden_source, pipeline_factory=Pipeline)
    assert result["state"] == "cancelled"
    assert result["cancelled"] == ["cancel_requested"]
    consumed = tasks_live.run_live(request, workspace=str(tmp_path),
                                  agent_command=["agent"], action_gate=True,
                                  source_factory=forbidden_source, pipeline_factory=Pipeline)
    assert consumed["state"] == "cancelled"
    assert consumed["reason"] == "persisted_cancel_enforced"
    assert not (tmp_path / ".simplicio-loop" / "tasks-run" / result["idempotency_key"][:16] / "journals" / "cancel.json").exists()
    assert Path(consumed["cancel_ack"]).exists()
    resumed = tasks_live.run_live(request, workspace=str(tmp_path), agent_command=["agent"],
                                  action_gate=True, source_factory=Source, intake_factory=Intake,
                                  materializer_factory=Materializer, pipeline_factory=Pipeline,
                                  orchestrator_factory=Orchestrator, queue_factory=Queue)
    assert resumed["state"] == "completed"

def test_cli_live_requires_agent_command(capsys):
    assert cli.main(["tasks", "run", "finish all issues in acme/widgets", "--action-gate"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "agent_command_required"

def test_cli_live_forwards_explicit_gate(monkeypatch, capsys):
    captured = {}
    def fake(request, **kwargs):
        captured.update(request=request, **kwargs)
        return {"state": "completed"}
    monkeypatch.setattr(tasks_live, "run_live", fake)
    rc = cli.main(["tasks", "run", "finish all issues in acme/widgets", "--action-gate", "--agent-command", "agent --json", "--max-workers", "2"])
    assert rc == 0
    assert captured["action_gate"] is True
    assert captured["max_workers"] == 2
    assert captured["agent_command"] == ["agent", "--json"]
    assert json.loads(capsys.readouterr().out)["state"] == "completed"
