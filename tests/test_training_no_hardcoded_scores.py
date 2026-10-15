"""#1813 -- the Simplicio-27B training tree must not publish scores nothing measured.

The README leaderboard, the SVG charts, `benchmarks/compare_top10_2026.py` and the Colab
notebooks carried hard-coded score literals (own and rival), and `benchmark_simplicio_27b.py`
printed a hard-coded token-savings string next to the numbers it really measured. Until an
evaluation with raw logs is published the only honest statement is "No published evaluation yet
(UNVERIFIED)".
"""
import contextlib
import io
import importlib.util
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN_DIR = os.path.join(REPO, "training", "simplicio-27b")
BENCH_SCRIPT = os.path.join(TRAIN_DIR, "benchmark_simplicio_27b.py")

UNVERIFIED_BANNER = "No published evaluation yet (UNVERIFIED)"

# Every score / ratio the old README, charts, notebooks and scripts asserted without a log.
SCORE_LITERAL_RE = re.compile(
    r"(?<![\d.])(?:96\.5|53\.6|72\.4|88\.6|89\.9|94\.2|56\.3|43\.5|84\.2|81\.5|79\.4|81\.2)\s?%"
    r"|\b480 t\b|-68%|68% economy|TOP10_2026_LEADERBOARD|Measured Live on NVIDIA",
    re.I,
)
_TEXT_EXT = (".md", ".py", ".ipynb", ".svg", ".json", ".txt", ".snippet")
# `data/` and `generate_dataset.py` hold synthetic *training samples* (what the model is taught to
# emit); they are data, not published claims about the model.
_SKIP_DIRS = {"data"}
_SKIP_FILES = {"generate_dataset.py"}


def _scan_files():
    for root, dirs, files in os.walk(TRAIN_DIR):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name in _SKIP_FILES or not name.endswith(_TEXT_EXT):
                continue
            yield os.path.join(root, name)


def test_no_score_literals_anywhere_in_training_tree():
    offenders = []
    for path in _scan_files():
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for m in SCORE_LITERAL_RE.finditer(text):
            offenders.append("%s: %r" % (os.path.relpath(path, REPO), m.group(0)))
    assert not offenders, "hard-coded score literals remain:\n" + "\n".join(offenders[:25])


def test_hardcoded_leaderboard_script_is_removed():
    assert not os.path.exists(os.path.join(TRAIN_DIR, "benchmarks", "compare_top10_2026.py"))
    for name in os.listdir(os.path.join(TRAIN_DIR, "benchmarks")):
        if name.endswith(".py"):
            with open(os.path.join(TRAIN_DIR, "benchmarks", name), encoding="utf-8") as fh:
                assert "compare_top10" not in fh.read(), "%s still wires the leaderboard" % name


def test_score_charts_are_removed():
    assets = os.listdir(os.path.join(TRAIN_DIR, "assets"))
    stale = [a for a in assets if re.search(r"leaderboard|tier_list|benchmark_comparison|token_econ|deepseek_v41", a)]
    assert not stale, "score charts still shipped: %s" % stale


def test_readme_states_no_published_evaluation():
    with open(os.path.join(TRAIN_DIR, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    assert UNVERIFIED_BANNER in readme
    assert "Comparative Scorecard" not in readme
    assert "Leaderboard" not in readme and "leaderboard" not in readme
    # no markdown table row may carry a percentage
    for line in readme.splitlines():
        if line.lstrip().startswith("|"):
            assert "%" not in line, "table row still carries a percentage: %s" % line[:120]


# --------------------------------------------------------------------------------------
# benchmark script prints only what it measures
# --------------------------------------------------------------------------------------
class _Batch(dict):
    """Stands in for a tokenizer BatchEncoding: mapping + .to() + .input_ids."""

    def __init__(self, n_prompt_tokens):
        super().__init__(input_ids=self)
        self.input_ids = self
        self.shape = (1, n_prompt_tokens)

    def to(self, _device):
        return self


class _FakeTokenizer:
    def __init__(self, response):
        self.response = response

    def __call__(self, prompts, return_tensors=None):
        return _Batch(10)

    def decode(self, _tokens, skip_special_tokens=False):
        return self.response


class _FakeModel:
    def generate(self, **_kw):
        return [list(range(10)) + list(range(7))]  # 10 prompt tokens + 7 generated


_RESPONSE = (
    "<orient>o</orient><plan>p</plan>"
    "<patch><<<< SEARCH\nreturn rate\n====\nreturn rate or 0\n>>>> REPLACE</patch>"
    "<validate>v</validate><deliver>d</deliver>"
)


def _load_bench_module():
    spec = importlib.util.spec_from_file_location("benchmark_simplicio_27b_under_test", BENCH_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_benchmark_reports_only_measured_fields():
    mod = _load_bench_module()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        metrics = mod.run_benchmark(_FakeModel(), _FakeTokenizer(_RESPONSE), mod.TEST_CASES)
    out = buf.getvalue()
    measured = {
        "total_cases", "phase_conformance_rate", "surgical_diff_accuracy",
        "ast_syntax_pass_rate", "avg_tokens_per_task",
    }
    assert set(metrics) == measured, "unmeasured fields reported: %s" % sorted(set(metrics) - measured)
    assert metrics["avg_tokens_per_task"] == 7.0  # taken from the (fake) generate() output, not a literal
    for forbidden in ("56.3", "vs CoT", "estimated_token_savings", "prolixo"):
        assert forbidden not in out, "hard-coded string printed: %s" % forbidden


def test_benchmark_script_has_no_hardcoded_percentage_literal():
    with open(BENCH_SCRIPT, encoding="utf-8") as fh:
        src = fh.read()
    # f-string format specs such as {x:.1f}% are fine; a digit directly before % is a literal.
    assert not re.search(r"\d\s?%", src), "literal percentage in benchmark script"
    assert "56.3" not in src


def test_benchmark_docstring_does_not_claim_unit_tests_are_run():
    mod = _load_bench_module()
    assert "does not run pytest" in (mod.__doc__ or "").lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
