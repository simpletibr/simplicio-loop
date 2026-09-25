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
import sys
from pathlib import Path

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
