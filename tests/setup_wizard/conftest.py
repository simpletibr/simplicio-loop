"""Shared fixture of the setup tests: HOME is a temporary folder, so no real login or summary is ever read."""
import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SIMPLICIO_HOME", raising=False)
    return tmp_path
