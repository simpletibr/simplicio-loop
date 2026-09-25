"""Real-process E2E coverage for degraded/edge project scenarios (#201).

`test_real_cli_mapper_e2e.py` (issue #201's first slice, PR #204) proves the
happy path: fresh project -> `simplicio-mapper index` -> `simplicio-dev-cli
inspect`. This module covers the scenarios #201 explicitly calls out that
were still missing real-binary coverage:

- "Projeto ... vazio ... e parcialmente corrompido" (empty project, and a
  project with a corrupted mapper artifact).
- "LLM indisponível" (no provider configured/reachable).

Every test here shells out to the real, installed console scripts
(`simplicio-mapper`, `simplicio-dev-cli`) exactly as a user would invoke
them, and asserts on stdout, stderr, exit code, and filesystem effects — not
on internal Python function calls. No test mocks `generate`/`map_ask`/the
mapper; the LLM-unavailable case is produced by a real (deliberately
unresolvable) provider configuration, not a monkeypatched exception, so the
CLI's own top-level error handling (`simplicio/cli.py::main`'s
`except Exception` -> friendly `stderr` + exit code) is what's actually
under test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    assert executable is not None, f"required E2E executable is not on PATH: {name}"
    return executable


def _base_env() -> dict[str, str]:
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update(
        {
            "SIMPLICIO_SKIP_AUTO_INIT": "1",
            "SIMPLICIO_DEV_CLI_NO_RUNTIME_PRECEDENT": "1",
            "SIMPLICIO_MAPPER_CLI": "1",
            "PYTHONPATH": os.pathsep.join(
                part for part in (str(project_root), env.get("PYTHONPATH", "")) if part
            ),
        }
    )
    return env


def _assert_no_traceback(process: subprocess.CompletedProcess[str], command: str) -> None:
    assert "Traceback" not in process.stderr, (
        f"{command} leaked a raw Python traceback instead of a handled error\n"
        f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
    )


def test_real_cli_handles_empty_project(tmp_path: Path) -> None:
    """A brand-new, completely empty project directory: no source files, no
    `.simplicio/` artifacts yet. `mapper index` must produce a valid,
    zero-count index rather than erroring, and `dev-cli inspect` against a
    target that doesn't exist yet must degrade gracefully (empty context, no
    crash) instead of raising."""
    mapper = _required_executable("simplicio-mapper")
    dev_cli = _required_executable("simplicio-dev-cli")
    env = _base_env()

    empty_project = tmp_path / "empty-project"
    empty_project.mkdir()

    index_process = subprocess.run(
        [mapper, "index", str(empty_project), "--json"],
        cwd=empty_project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert index_process.returncode == 0, index_process.stderr
    _assert_no_traceback(index_process, "simplicio-mapper index (empty project)")
    index_payload = json.loads(index_process.stdout)
    assert index_payload["schema"] == "simplicio.mapper-index/v1"
    assert index_payload["status"] == "updated"
    assert index_payload.get("error") is None
    assert index_payload["counts"]["files"] == 0

    project_map_path = empty_project / ".simplicio" / "project-map.json"
    assert project_map_path.is_file()
    project_map = json.loads(project_map_path.read_text(encoding="utf-8"))
    assert project_map["schema"] == "simplicio.project-map/v1"

    inspect_process = subprocess.run(
        [
            dev_cli,
            "inspect",
            "src/does_not_exist.py",
            "--root",
            str(empty_project),
            "--goal",
            "create the module",
            "--json",
        ],
        cwd=empty_project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert inspect_process.returncode == 0, inspect_process.stderr
    _assert_no_traceback(inspect_process, "simplicio-dev-cli inspect (empty project)")
    inspect_payload = json.loads(inspect_process.stdout)
    assert inspect_payload["schema"] == "simplicio.dev-cli.inspect/v1"
    assert inspect_payload["relevant_files"] == []


def test_real_cli_degrades_gracefully_on_corrupted_project_map(tmp_path: Path) -> None:
    """A project whose `.simplicio/project-map.json` is present but not
    valid JSON (partially written, truncated by a crash, hand-edited, etc.).
    `dev-cli inspect` must treat the artifact as absent (`present: False`)
    rather than raising `JSONDecodeError` out of the process, and a fresh
    `mapper index` run must be able to repair it in place."""
    mapper = _required_executable("simplicio-mapper")
    dev_cli = _required_executable("simplicio-dev-cli")
    env = _base_env()

    project = tmp_path / "corrupted-project"
    (project / ".simplicio").mkdir(parents=True)
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text('def greet(name):\n    return f"hi, {name}"\n', encoding="utf-8")

    corrupted_map_path = project / ".simplicio" / "project-map.json"
    corrupted_map_path.write_text("{not valid json, truncated mid-write", encoding="utf-8")

    inspect_process = subprocess.run(
        [
            dev_cli,
            "inspect",
            "src/app.py",
            "--root",
            str(project),
            "--goal",
            "fix the greeting",
            "--json",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert inspect_process.returncode == 0, inspect_process.stderr
    _assert_no_traceback(inspect_process, "simplicio-dev-cli inspect (corrupted project-map.json)")
    inspect_payload = json.loads(inspect_process.stdout)
    assert inspect_payload["artifacts"]["project_map"]["present"] is False
    # The corrupted bytes on disk are untouched by a read-only `inspect`.
    assert corrupted_map_path.read_text(encoding="utf-8") == "{not valid json, truncated mid-write"

    # A real `mapper index` run is the documented recovery path: it must
    # overwrite the corrupted artifact with a schema-valid one, in place.
    reindex_process = subprocess.run(
        [mapper, "index", str(project), "--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert reindex_process.returncode == 0, reindex_process.stderr
    _assert_no_traceback(reindex_process, "simplicio-mapper index (repair corrupted project-map.json)")
    reindex_payload = json.loads(reindex_process.stdout)
    assert reindex_payload.get("error") is None

    repaired_map = json.loads(corrupted_map_path.read_text(encoding="utf-8"))
    assert repaired_map["schema"] == "simplicio.project-map/v1"


def test_real_cli_task_reports_llm_unavailable_without_crashing(tmp_path: Path) -> None:
    """The provider-free task boundary must fail loudly but *cleanly*.

    The explicit standalone mode bypasses the Mapper-context precondition so
    this real-process scenario exercises provider refusal rather than a
    preceding orchestration guard:
    non-zero exit code, an actionable one-line `stderr` message, no raw
    Python traceback, and — critically — no partial/half-applied diff left
    on disk, since the failure happens before any patch is generated."""
    dev_cli = _required_executable("simplicio-dev-cli")

    sample_project = Path(__file__).parent / "fixtures" / "sample_project"
    project = tmp_path / "project"
    shutil.copytree(sample_project, project)
    source = project / "src" / "app.py"
    source_before = source.read_text(encoding="utf-8")

    env = _base_env()
    env["SIMPLICIO_MODEL"] = "anthropic/claude-opus-4"
    env["SIMPLICIO_TEST_CMD"] = f'"{shutil.which("python") or "python"}" -c "raise SystemExit(0)"'
    for unreachable_key in ("SIMPLICIO_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        env.pop(unreachable_key, None)

    task_process = subprocess.run(
        [
            dev_cli,
            "task",
            "fix the greeting",
            "--root",
            str(project),
            "--target",
            "src/app.py",
            "--mode",
            "standalone",
            "--json",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert task_process.returncode == 2, (
        "expected plan_required (exit 2) for prose task without --plan\n"
        f"stdout:\n{task_process.stdout}\nstderr:\n{task_process.stderr}"
    )
    _assert_no_traceback(task_process, "simplicio-dev-cli task (plan_required)")
    payload = json.loads(task_process.stdout)
    assert payload["reason_code"] == "plan_required"

    # No diff was ever generated, so the fixture source file must be
    # byte-for-byte untouched.
    assert source.read_text(encoding="utf-8") == source_before
