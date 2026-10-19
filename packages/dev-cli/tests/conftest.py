"""Shared isolation for deterministic local and contract tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from simplicio.hbp import HBP_FILE_NAME

REPO_ROOT = Path(__file__).resolve().parents[1]
# Runtime state the CLIs write when run in place. A test that changes any of it has leaked
# into the source tree, so it fails here instead of leaving files behind for later runs.
RUNTIME_STATE = (REPO_ROOT / ".simplicio-loop", REPO_ROOT / HBP_FILE_NAME)


def _runtime_state() -> dict[str, tuple[int, int]]:
    state: dict[str, tuple[int, int]] = {}
    for root in RUNTIME_STATE:
        paths = root.rglob("*") if root.is_dir() else (root,)
        for path in paths:
            if path.is_file():
                status = path.stat()
                state[path.relative_to(REPO_ROOT).as_posix()] = (status.st_mtime_ns, status.st_size)
    return state


@pytest.fixture(autouse=True)
def source_tree_keeps_no_runtime_state() -> Iterator[None]:
    before = _runtime_state()
    yield
    after = _runtime_state()
    if after != before:
        changed = sorted({name for name, _ in set(before.items()) ^ set(after.items())})
        pytest.fail(f"test wrote runtime state into the source tree: {', '.join(changed)}")


@pytest.fixture(autouse=True)
def isolated_execution_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy pipeline tests explicit and independent of host proxies.

    Production defaults remain fail-closed. Tests that exercise the legacy
    standalone pipeline opt in through the same migration switch required of
    real callers; execution-mode tests can still delete or override it.

    Tests must not write into the source tree: a test that writes runtime
    state passes its own tmp directory as the root.
    """
    monkeypatch.setenv("SIMPLICIO_ALLOW_STANDALONE_FALLBACK", "true")
    monkeypatch.delenv("SIMPLICIO_REQUIRE_MUTATION_AUTHORITY", raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
