"""Fixtures for the executor-compatibility contract suite (#100).

No test in this package makes a network call or talks to a real LLM
provider: `simplicio.pipeline.generate` / `simplicio.providers.generate` are
always monkeypatched to a deterministic stub, and the mapper artifacts are
loaded from the small, schema-faithful fixture project checked in under
`tests/contracts/fixtures/sample_project/`.
"""

from __future__ import annotations

import shutil
import stat
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
def stub_runtime_binary(tmp_path, monkeypatch):
    """Point SIMPLICIO_BIN at a fake `simplicio` Rust binary.

    The real Rust runtime (github.com/wesleysimplicio/simplicio-runtime) is
    not built/available in this environment, so the runtime-integrated leg
    of the executor-compatibility contract (simplicio.commands.test_run's
    `_run_via_runtime` delegation) is exercised against a **stub**, not the
    real binary. The stub only has to emit the same
    `simplicio.test-run/v1` JSON contract on `simplicio test run --cmd ...
    --json [--repo ...]` that the real binary would; everything downstream
    (schema field validation, exit-code propagation) exercises the actual
    consumer code path in `simplicio/commands/test_run.py`, which is what
    this contract cares about. This is explicitly a stub, not a real
    integration test against the Rust runtime — see #100 AC.
    """
    script = tmp_path / "bin" / "simplicio"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "# Minimal stub of `simplicio test run --cmd <c> --json [--repo <r>]`\n"
        "# emitting the simplicio.test-run/v1 contract. See conftest.py\n"
        "# docstring: this is NOT the real Rust runtime.\n"
        "args = sys.argv[1:]\n"
        "cmd = args[args.index('--cmd') + 1] if '--cmd' in args else 'pytest'\n"
        "print(json.dumps({\n"
        "    'schema': 'simplicio.test-run/v1',\n"
        "    'cmd': cmd,\n"
        "    'args': [],\n"
        "    'exit_code': 0,\n"
        "    'passed': 1,\n"
        "    'failed': 0,\n"
        "    'errors': 0,\n"
        "    'duration_s': 0.01,\n"
        "    'summary': '1 passed in 0.01s (stub runtime binary)',\n"
        "    'output_tail': '',\n"
        "    'output_truncated': False,\n"
        "}))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("SIMPLICIO_BIN", str(script))
    return script


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
