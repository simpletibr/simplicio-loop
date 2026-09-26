"""An agent command may print binary bytes (e.g. `cat` of a sqlite file);
the benchmark must record them, never crash."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench", "llm_ab"))
import measure  # noqa: E402


def test_run_subprocess_tolerates_non_utf8_output():
    out, metrics = measure.run_subprocess(["bash", "-lc", r"printf 'ok\xa7\xff end'"])
    assert metrics["returncode"] == 0
    assert out.startswith("ok") and out.endswith(" end")
