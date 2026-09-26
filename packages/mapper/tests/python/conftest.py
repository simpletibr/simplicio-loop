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
