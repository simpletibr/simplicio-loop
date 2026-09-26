from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.map_service import MapServiceRegistry
from simplicio_loop.map_service_git import resolve_repository_identity
from simplicio_loop.map_service_mapper import (
    mapper_binary_path,
    mapper_tree_snapshot,
    run_mapper_index,
)
from simplicio_loop.map_service_single_flight import SingleFlightMapStore

# This is the installed-operator contract, not a hermetic core test.  The
# module retains its local skip so the optional lane is clear when selected.
pytestmark = [
    pytest.mark.external_integration,
    pytest.mark.skipif(
        not __import__("shutil").which("simplicio-mapper"),
        reason="EXTERNAL_INTEGRATION_UNAVAILABLE[installed_simplicio_mapper]: simplicio-mapper binary not installed",
    ),
]


def _run(*args: str, cwd: str) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, "git %s failed: %s" % (" ".join(args), result.stderr)


def _init_repo(root: Path) -> None:
    _run("init", "-q", cwd=str(root))
    _run("config", "user.email", "test@example.com", cwd=str(root))
    _run("config", "user.name", "Test", cwd=str(root))
    (root / "app.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    _run("add", "app.py", cwd=str(root))
    _run("commit", "-q", "-m", "initial", cwd=str(root))


def test_mapper_binary_is_actually_reachable() -> None:
    # If this fails, every other test in this file is skipped rather than fabricating
    # a pass - see the module-level skipif.
    assert mapper_binary_path()


def test_run_mapper_index_produces_a_real_project_map(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    envelope = run_mapper_index(str(tmp_path))
    assert envelope["schema"] == "simplicio.mapper-index/v1"
    assert envelope["counts"]["files"] == 1
    assert (tmp_path / ".simplicio-loop" / "project-map.json").is_file()


def test_mapper_tree_snapshot_changes_when_file_content_changes(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    hash_1, files_1 = mapper_tree_snapshot(str(tmp_path))
    assert files_1 == [str((tmp_path / "app.py").resolve())]

    (tmp_path / "app.py").write_text("def hello():\n    return 2\n", encoding="utf-8")
    hash_2, _ = mapper_tree_snapshot(str(tmp_path))
    assert hash_2 != hash_1, "real content change must change the mapper-derived tree hash"


def test_mapper_index_on_a_non_existent_path_fails_closed() -> None:
    with pytest.raises(FileNotFoundError):
        mapper_tree_snapshot("/no/such/path/at/all")


def test_missing_binary_raises_mapper_unavailable(monkeypatch, tmp_path: Path) -> None:
    """Tests THIS module's own resilience code (what happens when the binary is
    absent), via monkeypatch on shutil.which - not a simulation of the mapper's
    behavior, which is exercised for real everywhere else in this file."""
    import simplicio_loop.map_service_mapper as mod
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    with pytest.raises(mod.MapperUnavailableError):
        mod.mapper_binary_path()


def test_non_zero_exit_raises_mapper_index_error(monkeypatch, tmp_path: Path) -> None:
    import simplicio_loop.map_service_mapper as mod

    class _FailedRun:
        returncode = 2
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _FailedRun())
    with pytest.raises(mod.MapperIndexError, match="boom"):
        mod.run_mapper_index(str(tmp_path))


def test_non_json_stdout_raises_mapper_index_error(monkeypatch, tmp_path: Path) -> None:
    import simplicio_loop.map_service_mapper as mod

    class _GarbageRun:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _GarbageRun())
    with pytest.raises(mod.MapperIndexError, match="valid JSON"):
        mod.run_mapper_index(str(tmp_path))


def test_error_field_in_envelope_raises_mapper_index_error(monkeypatch, tmp_path: Path) -> None:
    import json as json_module
    import simplicio_loop.map_service_mapper as mod

    class _ErrorRun:
        returncode = 0
        stdout = json_module.dumps({"schema": "simplicio.mapper-index/v1", "error": "disk full"})
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _ErrorRun())
    with pytest.raises(mod.MapperIndexError, match="disk full"):
        mod.run_mapper_index(str(tmp_path))


def test_missing_project_map_after_reported_success_raises(monkeypatch, tmp_path: Path) -> None:
    """A real edge case worth failing closed on: the binary reports success but never
    actually wrote the project-map.json it claims to have produced."""
    import json as json_module
    import simplicio_loop.map_service_mapper as mod

    class _SuccessNoFileRun:
        returncode = 0
        stdout = json_module.dumps({"schema": "simplicio.mapper-index/v1", "error": None})
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _SuccessNoFileRun())
    with pytest.raises(mod.MapperIndexError, match="does not exist"):
        mod.mapper_tree_snapshot(str(tmp_path))


def test_two_real_worktrees_indexed_by_the_real_mapper_share_one_canonical_build(tmp_path: Path) -> None:
    """The actual #512/#513 AC this closes: two real worktrees, each indexed by the
    REAL simplicio-mapper binary (not a git shortcut), agree on tree_hash for
    identical content and single-flight collapses their concurrent builds to one."""
    main_root = tmp_path / "main"
    main_root.mkdir()
    _init_repo(main_root)
    worktree_root = tmp_path / "wt"
    _run("worktree", "add", "-q", str(worktree_root), "-b", "wt-branch", cwd=str(main_root))

    main_identity = resolve_repository_identity(str(main_root))
    wt_identity = resolve_repository_identity(str(worktree_root))
    tree_hash_main, files_main = mapper_tree_snapshot(str(main_root))
    tree_hash_wt, _ = mapper_tree_snapshot(str(worktree_root))
    assert tree_hash_main == tree_hash_wt, (
        "two real worktrees at the identical commit must produce the identical "
        "mapper-derived tree hash"
    )

    registry = MapServiceRegistry()
    registry.register(main_identity)
    registry.register(wt_identity)
    store = SingleFlightMapStore(registry)
    build_calls = []

    async def real_mapper_builder():
        build_calls.append(1)
        await asyncio.sleep(0)
        return registry.build_canonical(main_identity.key, tree_hash=tree_hash_main, files=files_main)

    async def scenario():
        return await asyncio.gather(
            store.get_or_build(main_identity.key, mode="canonical", tree_hash=tree_hash_main,
                                files=files_main, builder=real_mapper_builder),
            store.get_or_build(main_identity.key, mode="canonical", tree_hash=tree_hash_main,
                                files=files_main, builder=real_mapper_builder),
        )

    handle_a, handle_b = asyncio.run(scenario())
    assert len(build_calls) == 1, "two equivalent concurrent requests must build exactly once"
    assert handle_a.cache_key == handle_b.cache_key
