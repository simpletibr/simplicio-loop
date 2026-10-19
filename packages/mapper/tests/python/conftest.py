"""Session-wide setup for the mapper Python test suite.

Warms the shared tiktoken ``o200k_base`` disk cache once, before any test
runs. ``simplicio_mapper.savings.estimate_tokens`` (used throughout
``retrieval_index.py``/``task_context.py`` for every token-budget decision,
and by ``scripts/evaluation_scorecard.py``) lazily loads that encoding on
first use per process; on a cold machine that means a network fetch, and
this suite spawns many independent subprocesses (each test-file's own
``simplicio-mapper index`` workers, plus ``scripts/evaluation_scorecard.py``'s
own two ``build`` invocations under
``tests/python/test_behavioral_scorecard.py``) that would otherwise all race
to populate the same on-disk cache the first time it is empty. Any one of
those concurrent fetches hitting a transient network hiccup silently falls
back to a coarser token-count heuristic for just that process -- flipping a
budget check without raising anything, which is exactly the "flaky under
full test-suite load" failure mode this fixture removes (see
``simplicio_mapper.savings.warm_estimator``'s docstring for the full causal
chain). Warming here, before collection reaches anything that spawns a
subprocess, means every later caller -- in-process or subprocess, in this
file or any other -- hits the already-populated disk cache instead of the
network, so the run never races again.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_mapper.savings import warm_estimator  # noqa: E402


def pytest_configure(config) -> None:  # noqa: ANN001 - pytest hook signature
    del config
    if os.environ.get("SIMPLICIO_MAPPER_SKIP_TOKENIZER_WARMUP") == "1":
        return
    # Best-effort: a genuinely offline, never-cached environment still runs
    # the suite (every caller's own except-and-fall-back stays intact), it
    # just no longer gets the determinism guarantee this warms up for.
    warm_estimator()


def _index_workers() -> set[int]:
    """PIDs of detached ``simplicio_mapper.cli index`` workers (Linux /proc)."""
    pids: set[int] = set()
    proc = Path("/proc")
    if not proc.is_dir():
        return pids
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if b"simplicio_mapper.cli" in argv and b"index" in argv:
            pids.add(int(entry.name))
    return pids


@pytest.fixture(autouse=True)
def _reap_background_index_workers():
    """A test that runs ``scan`` without ``--sync`` starts a detached index
    worker (``start_new_session=True``) and may return before it finishes.
    Wait for workers the test started, then terminate stragglers, so no
    worker outlives its test (the gate reports survivors as a leak)."""
    before = _index_workers()
    yield
    started = _index_workers() - before
    deadline = time.monotonic() + 15
    while started and time.monotonic() < deadline:
        started &= _index_workers()
        time.sleep(0.05)
    for pid in started:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


# Committed fixture trees are inputs and must never be written: a test that maps a fixture copies it
# into tmp_path first. The guard records which test created, changed or removed each path under these
# trees, and fails the session at the end if anything changed. Files are compared by (size, mtime_ns),
# so a rewrite with identical bytes is still a write.
MAPPER_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_FIXTURE_ROOTS = (
    MAPPER_ROOT / "tests" / "fixtures",
    *sorted((MAPPER_ROOT / "simplicio_mapper" / "contracts").glob("*/v1/fixtures")),
)
_fixture_baseline: dict[str, tuple] = {}
_fixture_writers: dict[str, str] = {}


def _fixture_snapshot() -> dict[str, tuple]:
    """Every file and directory under the committed fixture trees, keyed by repo-relative path."""
    state: dict[str, tuple] = {}
    for root in COMMITTED_FIXTURE_ROOTS:
        for dirpath, dirnames, filenames in os.walk(root):
            base = Path(dirpath)
            for name in dirnames:
                state[(base / name).relative_to(MAPPER_ROOT).as_posix()] = ("dir",)
            for name in filenames:
                path = base / name
                info = os.lstat(path)
                state[path.relative_to(MAPPER_ROOT).as_posix()] = ("file", info.st_size, info.st_mtime_ns)
    return state


def _fixture_changes(before: dict[str, tuple], after: dict[str, tuple]) -> list[str]:
    """Paths created, removed or changed between two snapshots."""
    return sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))


def pytest_sessionstart(session) -> None:  # noqa: ANN001 - pytest hook signature
    del session
    _fixture_baseline.clear()
    _fixture_baseline.update(_fixture_snapshot())


@pytest.fixture(autouse=True)
def _attribute_fixture_writes(request):
    before = _fixture_snapshot()
    yield
    for path in _fixture_changes(before, _fixture_snapshot()):
        _fixture_writers.setdefault(path, request.node.nodeid)


@pytest.fixture(scope="session", autouse=True)
def _committed_fixtures_untouched():
    yield
    changed = _fixture_changes(_fixture_baseline, _fixture_snapshot())
    if changed:
        listing = "\n".join(
            f"  {path}  (written by {_fixture_writers.get(path, 'outside any test')})" for path in changed
        )
        pytest.fail(
            "committed fixture trees are inputs and must not be written; copy the fixture into tmp_path "
            f"before mapping it:\n{listing}",
            pytrace=False,
        )
