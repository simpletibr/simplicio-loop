import json
import subprocess
from types import SimpleNamespace

from simplicio_loop import runner as runner_mod


def test_run_cmd_decodes_utf8_output_on_windows(tmp_path, monkeypatch):
    calls = []

    def fake_subprocess_run(argv, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, "\U0001f501 mapper receipt", "")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_subprocess_run)
    result = runner_mod._run_cmd(["simplicio-mapper", "handoff", "."], tmp_path)

    assert result.stdout == "\U0001f501 mapper receipt"
    assert calls[0]["encoding"] == "utf-8"
    assert calls[0]["errors"] == "replace"


def test_run_mapper_recovers_pack_hash_from_compact_handoff(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    calls = []

    monkeypatch.setattr(runner_mod, "_preflight_mapper", lambda *args: {"task_aware_supported": True, "help_stdout": ""})
    monkeypatch.setattr(runner_mod, "_validate_mapper_receipt", lambda *args: None)

    def fake_run(argv, cwd):
        calls.append(list(argv))
        if argv[:2] == ["simplicio-mapper", "handoff"]:
            count = sum(item[:2] == ["simplicio-mapper", "handoff"] for item in calls)
            pack = {"files": [{"path": "src/app.py"}]}
            pack["serialization_budget"] = {"compacted": True, "estimated_tokens": 10, "token_budget": 5}
            if count > 1:
                pack["pack_hash"] = "pack-recovered"
            return SimpleNamespace(returncode=0, stdout=json.dumps({"context_pack": pack}), stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")

    monkeypatch.setattr(runner_mod, "_run_cmd", fake_run)
    result = runner_mod._run_mapper(repo, run_root, task_path="task.md", goal="goal", target_hint="src/app.py")

    handoffs = [argv for argv in calls if argv[:2] == ["simplicio-mapper", "handoff"]]
    assert len(handoffs) == 2
    assert "--task-file" not in handoffs[1]
    assert handoffs[1][handoffs[1].index("--token-budget") + 1] == "128000"
    assert result["handoff"]["stdout"]["context_pack"]["pack_hash"] == "pack-recovered"


def test_run_mapper_tolerates_missing_optional_task_metadata(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    monkeypatch.setattr(runner_mod, "_preflight_mapper", lambda *args: {"task_aware_supported": True, "help_stdout": ""})
    monkeypatch.setattr(runner_mod, "_validate_mapper_receipt", lambda *args: None)
    monkeypatch.setattr(runner_mod, "_run_cmd", lambda argv, cwd: SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr=""))
    result = runner_mod._run_mapper(repo, run_root, task_path=None, goal=None, task_fingerprint=None, target_hint=None)
    assert result["handoff"]["stdout"] == {}


def test_context_reference_expands_to_canonical_artifact(tmp_path):
    repo = tmp_path / "repo"
    objects = repo / ".simplicio-loop" / "handoff-objects"
    objects.mkdir(parents=True)
    run_root = tmp_path / "run"
    run_root.mkdir()
    snapshot = objects / "context_snapshot-good.json"
    execution = objects / "execution_context-good.json"
    snapshot.write_text(json.dumps({"schema": "simplicio.context-snapshot/v1"}), encoding="utf-8")
    execution.write_text(json.dumps({"schema": "simplicio.execution-context/v1"}), encoding="utf-8")
    reference = lambda schema, path: {"schema": "simplicio.context-reference/v1", "expansion_handle": {"path": path}}
    (run_root / "mapper-context.json").write_text(json.dumps({"handoff": {"stdout": {
        "context_snapshot": reference("simplicio.context-snapshot/v1", ".simplicio-loop/handoff-objects/context_snapshot-good.json"),
        "context_pack": {"schema": "simplicio.context-pack/v1", "pack_hash": "pack-1"},
        "execution_context": reference("simplicio.execution-context/v1", ".simplicio-loop/handoff-objects/execution_context-good.json"),
    }}}), encoding="utf-8")
    args, receipt = runner_mod._context_handoff_args(repo, run_root)
    assert receipt["status"] == "propagated"
    assert args[args.index("--context-snapshot") + 1] == str(snapshot.resolve())
    assert args[args.index("--execution-context") + 1] == str(execution.resolve())
