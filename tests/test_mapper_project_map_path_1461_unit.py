"""Issue #1461: Mapper envelope paths, error propagation."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from simplicio_loop.map_service_mapper import materialize_project_map, MapperIndexError
from simplicio_loop.turbo_cli import _request_plan


def test_materialize_copies_from_elsewhere_preserves_original(tmp_path, monkeypatch):
    """Envelope paths.project_map outside .simplicio-loop/ is copied there, original untouched."""
    (tmp_path / "elsewhere").mkdir()
    project_map_data = {"files": [{"path": "app.py", "file_hash": "abc"}]}
    mapper_output = tmp_path / "elsewhere" / "project-map.json"
    mapper_output.write_text(json.dumps(project_map_data))

    envelope = {"paths": {"project_map": str(mapper_output)}}
    result = materialize_project_map(str(tmp_path), envelope)

    # Copied to expected location
    expected = tmp_path / ".simplicio-loop" / "project-map.json"
    assert result == expected
    assert json.loads(expected.read_text()) == project_map_data

    # Original preserved
    assert mapper_output.is_file()


def test_mapper_error_propagates_in_turbo_blocked(tmp_path, monkeypatch):
    """MapperIndexError propagates to turbo blocked JSON detail."""
    async def fail_mapper(path, **kwargs):
        raise MapperIndexError("simplicio-mapper index failed (exit 1): too many files")
    
    monkeypatch.setattr("simplicio_loop.map_service_mapper.run_mapper_index", fail_mapper)
    
    outputs = []
    monkeypatch.setattr("simplicio_loop.turbo_cli._emit", lambda doc: outputs.append(doc))
    
    _request_plan(str(tmp_path), ["test"], None, [], None, None)
    
    assert outputs
    assert outputs[0]["status"] == "blocked"
    assert "too many files" in outputs[0]["detail"]


def test_mapper_failure_carries_exit_code_and_truncated_stderr(tmp_path, monkeypatch):
    """The raised error names the exit code and keeps only the tail of a long stderr."""
    from simplicio_loop import map_service_mapper as msm

    class _Proc:
        returncode = 3

        async def communicate(self):
            return b"", ("x" * 5000 + "BOOM").encode()

    async def fake_exec(*_argv, **_kwargs):
        return _Proc()

    monkeypatch.setattr(msm, "mapper_binary_path", lambda: "/bin/simplicio-mapper")
    monkeypatch.setattr(msm.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(MapperIndexError) as info:
        asyncio.run(msm.run_mapper_index(str(tmp_path)))
    message = str(info.value)
    assert "exit 3" in message and message.endswith("BOOM") and len(message) < 600


def test_missing_binary_still_tolerated(tmp_path, monkeypatch):
    """When mapper binary missing, _ensure_project_map swallows MapperUnavailableError."""
    from simplicio_loop.cli_impl import _ensure_project_map
    from simplicio_loop.map_service_mapper import MapperUnavailableError
    
    async def fail_unavailable(path, **kwargs):
        raise MapperUnavailableError("binary not found")
    
    monkeypatch.setattr("simplicio_loop.map_service_mapper.run_mapper_index", fail_unavailable)
    
    # Should not raise, binary missing is tolerated
    asyncio.run(_ensure_project_map(tmp_path, budget=None))
