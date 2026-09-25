from __future__ import annotations

import json
from types import SimpleNamespace

from simplicio import changeset_v2
from simplicio.commands import changeset as changeset_command


def _mapper_envelope(paths: tuple[str, ...]) -> dict:
    return {
        "handoff": {
            "schema": changeset_command.MAPPER_FAST_HANDOFF_SCHEMA,
            "delta": {"changed_paths": list(paths)},
            "revision": "revision-419",
        },
        "receipt": {
            "schema": changeset_command.MAPPER_FAST_RECEIPT_SCHEMA,
            "status": "parsed",
            "generation": "mapper-generation-419",
            "counters": {"parsed": len(paths), "reused": 0, "degraded": 0, "fallback": 0},
        },
    }


def test_mapper_refresh_batches_all_paths_in_one_process(monkeypatch, tmp_path):
    paths = ("alpha.txt", "nested/beta.txt")
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(changeset_command.shutil, "which", lambda _name: "simplicio-mapper.exe")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return changeset_command.subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(_mapper_envelope(paths)), stderr=""
        )

    monkeypatch.setattr(changeset_command.subprocess, "run", fake_run)

    result = changeset_command._mapper_refresh_producer(tmp_path, paths)

    assert result == {
        "producer": "simplicio-mapper",
        "subprocesses": 1,
        "schema": changeset_command.MAPPER_FAST_RECEIPT_SCHEMA,
        "status": "parsed",
        "generation": "mapper-generation-419",
        "revision": "revision-419",
        "changed_paths": list(paths),
        "counters": {"parsed": 2, "reused": 0, "degraded": 0, "fallback": 0},
    }
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[0:3] == ["simplicio-mapper.exe", "fast-handoff", str(tmp_path)]
    assert command.count("--changed-path") == 2
    assert [command[index + 1] for index, value in enumerate(command) if value == "--changed-path"] == list(
        paths
    )
    assert command[-2:] == ["--expect-schema", changeset_command.MAPPER_FAST_HANDOFF_SCHEMA]
    assert "--out" not in command
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stdin"] is changeset_command.subprocess.DEVNULL
    assert kwargs["timeout"] == changeset_command.MAPPER_REFRESH_TIMEOUT_SECONDS


def test_mapper_refresh_missing_or_invalid_producer_stays_fail_closed(monkeypatch, tmp_path):
    paths = ("alpha.txt",)
    monkeypatch.setattr(changeset_command.shutil, "which", lambda _name: None)
    try:
        changeset_command._mapper_refresh_producer(tmp_path, paths)
    except RuntimeError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("missing Mapper must not report a refresh")


def test_changeset_cli_wires_mapper_refresh_only_when_requested(monkeypatch, tmp_path, capsys):
    plan = tmp_path / "changeset.sfb"
    plan.write_bytes(changeset_v2.BINARY_MAGIC + b"payload")
    seen: dict[str, object] = {}

    def fake_execute(payload, **kwargs):
        seen.update(payload=payload, **kwargs)
        return {"status": "ok", "applied": True, "dry_run": False}

    monkeypatch.setattr(changeset_v2, "execute_changeset_bytes", fake_execute)
    args = SimpleNamespace(
        mode="standalone",
        root=str(tmp_path),
        plan=str(plan),
        apply=True,
        current_generation=None,
        fast_engine="python",
        refresh_mapper=True,
        json=True,
    )

    assert changeset_command.run(args) == 0
    assert seen["refresh_producer"] is changeset_command._mapper_refresh_producer
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["execution_mode"]["route"] == "standalone"


def test_changeset_cli_fails_closed_when_refresh_is_pending(monkeypatch, tmp_path, capsys):
    plan = tmp_path / "changeset.sfb"
    plan.write_bytes(changeset_v2.BINARY_MAGIC + b"payload")

    def fake_execute(payload, **kwargs):
        return {
            "status": "ok",
            "applied": True,
            "dry_run": False,
            "refresh": {"status": "REFRESH_PENDING", "paths": ["alpha.txt"]},
        }

    monkeypatch.setattr(changeset_v2, "execute_changeset_bytes", fake_execute)
    args = SimpleNamespace(
        mode="standalone",
        root=str(tmp_path),
        plan=str(plan),
        apply=True,
        current_generation=None,
        fast_engine="python",
        refresh_mapper=False,
        json=True,
    )

    assert changeset_command.run(args) == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "ok"
    assert receipt["refresh"]["status"] == "REFRESH_PENDING"


def test_changeset_cli_without_flag_preserves_pending_contract(monkeypatch, tmp_path, capsys):
    plan = tmp_path / "changeset.sfb"
    plan.write_bytes(changeset_v2.BINARY_MAGIC + b"payload")
    seen: dict[str, object] = {}

    def fake_execute(payload, **kwargs):
        seen.update(payload=payload, **kwargs)
        return {"status": "ok", "applied": True, "dry_run": False}

    monkeypatch.setattr(changeset_v2, "execute_changeset_bytes", fake_execute)
    args = SimpleNamespace(
        mode="standalone",
        root=str(tmp_path),
        plan=str(plan),
        apply=True,
        current_generation=None,
        fast_engine="python",
        refresh_mapper=False,
        json=True,
    )

    assert changeset_command.run(args) == 0
    assert seen["refresh_producer"] is None
    json.loads(capsys.readouterr().out)
