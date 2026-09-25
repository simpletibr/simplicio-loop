"""Fixtures for the executor-compatibility contract suite (#100).

No test in this package makes a network call or talks to a real LLM
provider: `simplicio.pipeline.generate` / `simplicio.providers.generate` are
always monkeypatched to a deterministic stub, and the mapper artifacts are
loaded from the small, schema-faithful fixture project checked in under
`tests/contracts/fixtures/sample_project/`.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PROJECT = FIXTURES_DIR / "sample_project"


@pytest.fixture
def sample_project(tmp_path, monkeypatch):
    """A real (schema-faithful, hand-trimmed) mapper artifact pair on disk.

    Copies fixtures/sample_project/ (.simplicio/project-map.json +
    .simplicio/precedent-index.json + src/app.py) into an isolated tmp_path
    so tests can mutate it freely, and disables the Claude Code
    auto-activation side effect the CLI otherwise triggers on first run.
    """
    dest = tmp_path / "project"
    shutil.copytree(SAMPLE_PROJECT, dest)
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    return dest


@pytest.fixture
def stub_local_provider(monkeypatch):
    """Stub `simplicio.pipeline.generate` so no real LLM/network call happens.

    Returns a unified-diff-shaped completion for whatever target path is
    passed to it, matching the shape `tests/python/test_task_json_contract.py`
    already relies on for the same reason.
    """

    def _diff(target: str) -> str:
        return "\n".join(
            [
                f"diff --git a/{target} b/{target}",
                f"--- a/{target}",
                f"+++ b/{target}",
                "@@ -1 +1 @@",
                "-old",
                "+new",
                "",
                "TEST:",
                "assert True",
            ]
        )

    calls: list[str] = []

    def _fake_generate(prompt, feedback=None, *a, **k):
        calls.append(prompt)
        return _diff("src/app.py")

    monkeypatch.setattr("simplicio.pipeline.generate", _fake_generate)
    return calls


def true_cmd() -> str:
    """A cross-platform "always succeeds" command for SIMPLICIO_TEST_CMD."""
    return f'"{sys.executable}" -c "raise SystemExit(0)"'
