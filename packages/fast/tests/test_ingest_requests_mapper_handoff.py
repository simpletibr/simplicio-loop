"""`simplicio-fast ingest .` works without a hand-made --mapper-handoff file.

Integrated mode still requires Mapper facts; when no file is given Fast asks
the installed Mapper for the canonical handoff instead of failing. It never
bootstraps: without Mapper it fails closed with mapper_missing.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from simplicio_fast import cli
from simplicio_fast.mapper_ingest import MapperIngestError


def _completed(argv, payload, code=0):
    return subprocess.CompletedProcess(argv, code, json.dumps(payload), "")


def test_missing_handoff_is_requested_from_mapper(monkeypatch, tmp_path):
    calls = []
    envelope = {"schema": "simplicio.map-handoff/v1", "ready": True}

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return _completed(argv, envelope)

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli._load_mapper_handoff(None, tmp_path) == envelope
    assert calls[0][:2] == ["/bin/simplicio-mapper", "handoff"]
    assert "--goal" not in calls[0]


def test_not_ready_map_is_refreshed_once_then_retried(monkeypatch, tmp_path):
    answers = iter(
        [
            {
                "schema": "simplicio.map-handoff/v1",
                "ready": False,
                "reason": "artifacts_not_fresh",
            },
            {"phase": "complete"},
            {"schema": "simplicio.map-handoff/v1", "ready": True},
        ]
    )
    verbs = []

    def fake_run(argv, **_kwargs):
        verbs.append(argv[1])
        return _completed(argv, next(answers))

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli._load_mapper_handoff(None, tmp_path)["ready"] is True
    assert verbs == ["handoff", "scan", "handoff"]


def test_without_mapper_installed_it_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(MapperIngestError, match="mapper_missing"):
        cli._load_mapper_handoff(None, tmp_path)


def test_directory_handoff_is_a_typed_error(tmp_path):
    with pytest.raises(MapperIngestError, match="mapper_handoff_unreadable"):
        cli._load_mapper_handoff(str(tmp_path), tmp_path)
