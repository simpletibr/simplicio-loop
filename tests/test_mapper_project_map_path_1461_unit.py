"""Issue #1461: Mapper envelope paths, .git/info/exclude, error propagation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop.map_service_mapper import materialize_project_map, MapperIndexError
from simplicio_loop.turbo_cli import _request_plan


def test_materialize_copies_from_simplicio_preserves_original(tmp_path, monkeypatch):
    """Envelope paths.project_map in .simplicio/ copied to .simplicio-loop/, original untouched."""
    (tmp_path / ".simplicio").mkdir()
    project_map_data = {"files": [{"path": "app.py", "file_hash": "abc"}]}
    mapper_output = tmp_path / ".simplicio" / "project-map.json"
    mapper_output.write_text(json.dumps(project_map_data))
    
    envelope = {"paths": {"project_map": str(mapper_output)}}
    result = materialize_project_map(str(tmp_path), envelope)
    
    # Copied to expected location
    expected = tmp_path / ".simplicio-loop" / "project-map.json"
    assert result == expected
    assert json.loads(expected.read_text()) == project_map_data
    
    # Original preserved
    assert mapper_output.is_file()
    assert (tmp_path / ".simplicio").is_dir()


def test_materialize_registers_simplicio_in_git_exclude(tmp_path):
    """After copy from .simplicio/, .git/info/exclude contains .simplicio/."""
    (tmp_path / ".git" / "info").mkdir(parents=True)
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.write_text("# git exclude\n*.pyc\n")
    
    (tmp_path / ".simplicio").mkdir()
    mapper_output = tmp_path / ".simplicio" / "project-map.json"
    mapper_output.write_text(json.dumps({"files": []}))
    
    envelope = {"paths": {"project_map": str(mapper_output)}}
    materialize_project_map(str(tmp_path), envelope)
    
    content = exclude.read_text()
    assert ".simplicio/" in content
    assert "*.pyc" in content  # Existing line preserved


def test_mapper_error_propagates_in_turbo_blocked(tmp_path, monkeypatch):
    """MapperIndexError propagates to turbo blocked JSON detail."""
    def fail_mapper(path, **kwargs):
        raise MapperIndexError("simplicio-mapper index failed (exit 1): too many files")
    
    monkeypatch.setattr("simplicio_loop.map_service_mapper.run_mapper_index", fail_mapper)
    
    outputs = []
    monkeypatch.setattr("simplicio_loop.turbo_cli._emit", lambda doc: outputs.append(doc))
    
    _request_plan(str(tmp_path), ["test"], None, [], None, None)
    
    assert outputs
    assert outputs[0]["status"] == "blocked"
    assert "too many files" in outputs[0]["detail"] or "mapper" in outputs[0]["detail"].lower()


def test_missing_binary_still_tolerated(tmp_path, monkeypatch):
    """When mapper binary missing, _ensure_project_map swallows MapperUnavailableError."""
    from simplicio_loop.cli_impl import _ensure_project_map
    from simplicio_loop.map_service_mapper import MapperUnavailableError
    
    def fail_unavailable(path, **kwargs):
        raise MapperUnavailableError("binary not found")
    
    monkeypatch.setattr("simplicio_loop.map_service_mapper.run_mapper_index", fail_unavailable)
    
    # Should not raise, binary missing is tolerated
    _ensure_project_map(tmp_path, budget=None)
