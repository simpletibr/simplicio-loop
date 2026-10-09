"""orient maps a worktree as base + overlay first and falls back to a full index (#1574)."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from simplicio_loop import map_service_mapper as msm


def _fake_mapper(directory: Path, *, overlay_exit: int) -> Path:
    """A stand-in `simplicio-mapper` that records its argv and writes the artifacts it would."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "simplicio-mapper"
    script.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, os, sys
        argv = sys.argv[1:]
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calls.log"), "a") as log:
            log.write(" ".join(argv[:2]) + "\\n")
        root = argv[2] if argv[0] == "canonical" else argv[1]
        out = os.path.join(root, ".simplicio-loop")
        os.makedirs(out, exist_ok=True)
        if argv[0] == "canonical":
            if {overlay_exit}:
                print(json.dumps({{"status": "fallback", "fallback_reason": "canonical_build_failed"}}))
                sys.exit({overlay_exit})
            open(os.path.join(out, "project-map.json"), "w").write("{{}}")
            print(json.dumps({{"schema": "simplicio.worktree-overlay-receipt/v1", "status": "ok", "mode": "overlay",
                              "paths": {{"project_map": os.path.join(out, "project-map.json")}}}}))
        else:
            open(os.path.join(out, "project-map.json"), "w").write("{{}}")
            print(json.dumps({{"schema": "simplicio.mapper-index/v1", "paths": {{"project_map": os.path.join(out, "project-map.json")}}}}))
        """), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _calls(binary: Path) -> list[str]:
    log = binary.parent / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    return root


def test_run_mapper_map_prefers_the_overlay(tmp_path, repo, monkeypatch):
    binary = _fake_mapper(tmp_path / "bin", overlay_exit=0)
    monkeypatch.setenv("PATH", str(binary.parent) + os.pathsep + os.environ["PATH"])
    envelope = asyncio.run(msm.run_mapper_map(str(repo)))
    assert envelope["mode"] == "overlay"
    assert _calls(binary) == ["canonical overlay"], "no full index when the overlay applies"
    assert msm.materialize_project_map(str(repo), envelope).is_file()


def test_run_mapper_map_falls_back_to_a_full_index_when_the_overlay_cannot_serve(tmp_path, repo, monkeypatch):
    binary = _fake_mapper(tmp_path / "bin", overlay_exit=1)
    monkeypatch.setenv("PATH", str(binary.parent) + os.pathsep + os.environ["PATH"])
    envelope = asyncio.run(msm.run_mapper_map(str(repo)))
    assert envelope["schema"] == "simplicio.mapper-index/v1"
    assert _calls(binary) == ["canonical overlay", "index " + str(repo.resolve())]


def test_an_old_mapper_without_the_overlay_verb_still_indexes(tmp_path, repo, monkeypatch):
    binary = _fake_mapper(tmp_path / "bin", overlay_exit=2)  # argparse-style "unknown command"
    monkeypatch.setenv("PATH", str(binary.parent) + os.pathsep + os.environ["PATH"])
    envelope = asyncio.run(msm.run_mapper_map(str(repo)))
    assert envelope["schema"] == "simplicio.mapper-index/v1"


def test_run_mapper_index_is_still_a_pure_index(tmp_path, repo, monkeypatch):
    binary = _fake_mapper(tmp_path / "bin", overlay_exit=0)
    monkeypatch.setenv("PATH", str(binary.parent) + os.pathsep + os.environ["PATH"])
    envelope = asyncio.run(msm.run_mapper_index(str(repo)))
    assert envelope["schema"] == "simplicio.mapper-index/v1"
    assert _calls(binary) == ["index " + str(repo.resolve())]


def test_detached_command_is_one_process_that_tries_the_overlay_then_the_index(tmp_path, repo):
    binary = _fake_mapper(tmp_path / "bin", overlay_exit=1)
    argv = msm.index_argv(str(binary), str(repo.resolve()))
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["schema"] == "simplicio.mapper-index/v1"
    assert _calls(binary) == ["canonical overlay", "index " + str(repo.resolve())]

    ok = _fake_mapper(tmp_path / "bin2", overlay_exit=0)
    result = subprocess.run(msm.index_argv(str(ok), str(repo.resolve())), capture_output=True, text=True, timeout=60)
    assert json.loads(result.stdout)["mode"] == "overlay"


def test_orient_spawns_the_overlay_first_command(monkeypatch, tmp_path):
    """The detached orient index (cli_impl) uses `index_argv`, not a bare `index`."""
    from simplicio_loop import cli_impl

    seen = {}

    class FakeProc:
        pid = 1234
        returncode = 0

        def poll(self):
            return 0

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        return FakeProc()

    binary = _fake_mapper(tmp_path / "bin", overlay_exit=0)
    monkeypatch.setattr(msm, "mapper_binary_path", lambda: str(binary))
    monkeypatch.setattr(cli_impl.subprocess, "Popen", fake_popen)
    root = tmp_path / "wt"
    root.mkdir()
    asyncio.run(cli_impl._ensure_project_map_bounded(
        root, root / ".simplicio-loop" / "project-map.json", root / ".simplicio-loop" / "state.json", None, 5.0,
    ))
    assert seen["argv"][:4] == [sys.executable, "-P", "-m", "simplicio_loop.map_service_mapper"]
    assert seen["argv"][-2:] == [str(binary), str(root.resolve())]


def test_an_overlay_that_answers_ok_but_wrote_nothing_does_not_replace_the_index(tmp_path, repo, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "simplicio-mapper"
    script.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        "print(json.dumps({'status': 'ok', 'paths': {'project_map': '/nonexistent/project-map.json'}}"
        " if sys.argv[1] == 'canonical' else {'schema': 'simplicio.mapper-index/v1'}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    envelope = asyncio.run(msm.run_mapper_map(str(repo)))
    assert envelope["schema"] == "simplicio.mapper-index/v1"
    result = subprocess.run(msm.index_argv(str(script), str(repo.resolve())), capture_output=True, text=True)
    assert json.loads(result.stdout)["schema"] == "simplicio.mapper-index/v1"


def test_a_frozen_build_keeps_the_plain_index_for_the_detached_path(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert msm.index_argv("/bin/simplicio-mapper", "/repo") == ["/bin/simplicio-mapper", "index", "/repo", "--json"]


@pytest.mark.parametrize("shadow", ["hashlib.py", "asyncio.py", "json.py", "subprocess.py"])
def test_the_detached_helper_never_runs_code_from_the_mapped_repository(tmp_path, shadow):
    """`python -m` puts the cwd first on sys.path: a stdlib-named file in the repo root must not run."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / shadow).write_text('raise SystemExit("REPO CODE RAN")\n', encoding="utf-8")
    argv = msm.index_argv("/bin/true", str(repo))
    result = subprocess.run(argv, cwd=str(repo), capture_output=True, text=True, timeout=60)
    assert "REPO CODE RAN" not in result.stderr + result.stdout
    assert result.returncode == 0, result.stderr


def test_the_budgeted_orient_path_runs_the_startup_gc_too(monkeypatch, tmp_path, repo):
    """`orient` takes the budgeted path; the stale-scratch GC must run there as well."""
    from simplicio_loop import cli_impl

    scratch = repo / ".git" / "simplicio" / "map" / "baseline-build-stale1"
    (scratch / "tree").mkdir(parents=True)
    (scratch / "tree" / "f.py").write_text("x = 1\n", encoding="utf-8")
    old = os.path.getmtime(scratch) - 6 * 3600
    for path in (scratch / "tree" / "f.py", scratch / "tree", scratch):
        os.utime(path, (old, old))

    class FakeProc:
        pid = 1
        returncode = 0

        def poll(self):
            return 0

    binary = _fake_mapper(tmp_path / "bin", overlay_exit=0)
    monkeypatch.setattr(msm, "mapper_binary_path", lambda: str(binary))
    real_popen = subprocess.Popen

    def popen(argv, *args, **kwargs):  # fake only the detached helper; git (used by the GC) stays real
        if "simplicio_loop.map_service_mapper" in " ".join(map(str, argv)):
            return FakeProc()
        return real_popen(argv, *args, **kwargs)

    monkeypatch.setattr(cli_impl.subprocess, "Popen", popen)
    asyncio.run(cli_impl._ensure_project_map_bounded(
        repo, repo / ".simplicio-loop" / "project-map.json", repo / ".simplicio-loop" / "state.json", None, 5.0,
    ))
    assert not scratch.exists()
