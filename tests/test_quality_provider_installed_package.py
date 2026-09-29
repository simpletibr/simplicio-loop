"""Clean-room installed-package regression coverage for issue #1233."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TIMEOUT_SECONDS = 120.0

pytestmark = pytest.mark.external_integration


def _run(
    command: list[str], *, cwd: Path, deadline: float,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        pytest.fail("installed-package regression exceeded its total runtime bound")
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=remaining,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail("installed-package regression timed out: %s" % exc)


def _failure(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join((result.stdout, result.stderr)).strip()[-4000:]


def test_quality_provider_imports_from_clean_installed_wheel(tmp_path: Path) -> None:
    """Build and import the provider without the checkout on the interpreter path."""
    deadline = time.monotonic() + TEST_TIMEOUT_SECONDS
    source = tmp_path / "source"
    shutil.copytree(
        REPO_ROOT,
        source,
        ignore=shutil.ignore_patterns(".git", "build", ".pytest_cache", "__pycache__", "*.pyc"),
    )
    dist = tmp_path / "dist"
    dist.mkdir()
    build = _run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            str(source),
            "--wheel-dir",
            str(dist),
        ],
        cwd=source,
        deadline=deadline,
    )
    assert build.returncode == 0, _failure(build)
    wheels = sorted(dist.glob("*.whl"))
    assert len(wheels) == 1, [wheel.name for wheel in wheels]

    venv = tmp_path / "venv"
    created = _run(
        [sys.executable, "-m", "venv", "--clear", str(venv)],
        cwd=source,
        deadline=deadline,
    )
    assert created.returncode == 0, _failure(created)
    venv_python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    installed = _run(
        [str(venv_python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheels[0])],
        cwd=tmp_path,
        deadline=deadline,
    )
    assert installed.returncode == 0, _failure(installed)

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    probe = _run(
        [
            str(venv_python),
            "-I",
            "-c",
            (
                "import importlib.metadata as metadata, json\n"
                "import tempfile\n"
                "from pathlib import Path\n"
                "from simplicio_loop.quality_providers import simplicio_loop_quality as provider\n"
                "class AdmittedMonitor:\n"
                "    def refresh(self, *, force=False): return self\n"
                "    def due(self): return False\n"
                "    def admission_status(self): return {'admitted': True, 'action': 'admit', 'reason_code': 'PHYSICAL_CAPACITY_AVAILABLE'}\n"
                "    def status(self): return {'admission': self.admission_status()}\n"
                "provider._build_monitor = lambda _repo: AdmittedMonitor()\n"
                "files = {str(path) for path in (metadata.files('simplicio-loop') or [])}\n"
                "with tempfile.TemporaryDirectory() as temp:\n"
                "    repo = Path(temp)\n"
                "    check_script = repo / 'scripts' / 'check.py'\n"
                "    check_script.parent.mkdir()\n"
                "    check_script.write_text(\"print('installed-quality-ok')\\n\", encoding='utf-8')\n"
                "    outcome = provider.run(run_id='installed', tasks=[], attempt=1, repo=str(repo), worktree=str(repo), head='h', diff_hash='d', policy='strict-default')\n"
                "print(json.dumps({\"version\": metadata.version('simplicio-loop'), \"module_file\": str(Path(provider.__file__).resolve()), \"quality_helper_packaged\": \"simplicio_loop/quality_process.py\" in files, \"top_level_scripts_packaged\": any(path.startswith('scripts/') for path in files), \"status\": outcome['status'], \"output_preserved\": 'installed-quality-ok' in outcome['detail'], \"receipt_preserved\": str(check_script) in outcome['receipts'], \"quality_timeout\": provider.QUALITY_TIMEOUT_SECONDS}, sort_keys=True))"
            ),
        ],
        cwd=tmp_path,
        env=env,
        deadline=deadline,
    )
    assert probe.returncode == 0, _failure(probe)
    observed = json.loads(probe.stdout)
    assert observed["version"]
    assert str(venv.resolve()) in observed["module_file"]
    assert observed["quality_helper_packaged"] is True
    assert observed["top_level_scripts_packaged"] is False
    assert observed["status"] == "PASS"
    assert observed["output_preserved"] is True
    assert observed["receipt_preserved"] is True
    assert observed["quality_timeout"] == 900.0
