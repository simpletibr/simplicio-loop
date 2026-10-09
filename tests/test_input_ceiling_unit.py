"""Unit tests for the agent input ceiling (#1608, part A): ceiling config, token estimator, budget decision.

Owner rule: no LLM request of a loop agent may carry more than 98,000 input tokens. The ceiling applies to the TOTAL
prompt of the request (new input + cache reads + cache writes), because the price tier depends on the whole prompt.

Reference fixture ``tests/fixtures/input_ceiling_reference.json``: texts are frozen in the file (hand-written prose,
seeded random blobs, excerpts of this repo). The reference counts are tiktoken ``o200k_base`` counts. To recompute them
from the frozen texts (offline, tiktoken is already installed):

    python3 -c "import json,tiktoken;p='tests/fixtures/input_ceiling_reference.json';d=json.load(open(p));e=tiktoken.get_encoding('o200k_base');[s.update(ref_tokens=len(e.encode(s['text'],disallowed_special=()))) for s in d['samples']];json.dump(d,open(p,'w'),ensure_ascii=False,indent=1);open(p,'a').write('\\n')"

The tests never import tiktoken and never use the network. Counts for non-OpenAI tokenizers (Claude) are UNVERIFIED.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from simplicio_loop import input_ceiling as ic

REF = json.loads((Path(__file__).parent / "fixtures" / "input_ceiling_reference.json").read_text(encoding="utf-8"))


# --- ceiling configuration -------------------------------------------------------------------------------------------

def _toml(repo: Path, text: str) -> None:
    (repo / ".simplicio-loop").mkdir(exist_ok=True)
    (repo / ".simplicio-loop" / "loop.toml").write_text(text, encoding="utf-8")


def test_constants():
    assert ic.DEFAULT_CEILING == 98_000
    assert ic.MAX_CEILING == 1_000_000
    assert ic.ENV_NAME == "SIMPLICIO_AGENT_INPUT_TOKEN_CEILING"
    assert ic.TOML_KEY == "agent_input_token_ceiling"
    assert ic.SOFT_PERCENT == 90
    assert ic.SAFETY_PERCENT == 120
    assert ic.ESTIMATOR_LABEL == "conservative-v2"


def test_default_when_nothing_is_configured(tmp_path):
    assert ic.resolve_ceiling(tmp_path, environ={}) == 98_000


def test_default_when_toml_exists_without_the_key(tmp_path):
    _toml(tmp_path, 'verify = "pytest -q"\n')
    assert ic.resolve_ceiling(tmp_path, environ={}) == 98_000


def test_toml_value_is_used(tmp_path):
    _toml(tmp_path, "agent_input_token_ceiling = 50000\n")
    assert ic.resolve_ceiling(tmp_path, environ={}) == 50_000


def test_env_beats_toml(tmp_path):
    _toml(tmp_path, "agent_input_token_ceiling = 50000\n")
    assert ic.resolve_ceiling(tmp_path, environ={ic.ENV_NAME: "70000"}) == 70_000


def test_env_default_reads_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(ic.ENV_NAME, "12345")
    assert ic.resolve_ceiling(tmp_path) == 12_345


def test_bounds_are_accepted(tmp_path):
    assert ic.resolve_ceiling(tmp_path, environ={ic.ENV_NAME: "1"}) == 1
    assert ic.resolve_ceiling(tmp_path, environ={ic.ENV_NAME: str(ic.MAX_CEILING)}) == ic.MAX_CEILING


@pytest.mark.parametrize("bad", ["98k", "", " ", " 98000", "98000 ", "0", "-5", "+5", "1.5", "98000.0", "1_000", "1e5",
                                 "0x10", "٩٨٠٠٠", str(1_000_001), "true"])
def test_invalid_env_fails_loud_even_when_toml_is_valid(tmp_path, bad):
    _toml(tmp_path, "agent_input_token_ceiling = 50000\n")
    with pytest.raises(ic.CeilingConfigError) as exc:
        ic.resolve_ceiling(tmp_path, environ={ic.ENV_NAME: bad})
    assert exc.value.reason_code == "ceiling_invalid"
    assert ic.ENV_NAME in str(exc.value)


@pytest.mark.parametrize("bad", ['"98000"', '"98k"', "98000.0", "1e5", "true", "false", "0", "-1", "1000001", "[1]",
                                 "{ a = 1 }", "1979-05-27"])
def test_invalid_toml_fails_loud(tmp_path, bad):
    _toml(tmp_path, "agent_input_token_ceiling = %s\n" % bad)
    with pytest.raises(ic.CeilingConfigError) as exc:
        ic.resolve_ceiling(tmp_path, environ={})
    assert exc.value.reason_code == "ceiling_invalid"
    assert ic.TOML_KEY in str(exc.value)


def test_malformed_toml_fails_loud(tmp_path):
    _toml(tmp_path, "agent_input_token_ceiling = \n")
    with pytest.raises(ic.CeilingConfigError) as exc:
        ic.resolve_ceiling(tmp_path, environ={})
    assert exc.value.reason_code == "ceiling_invalid"


def test_valid_env_wins_without_reading_a_broken_toml(tmp_path):
    _toml(tmp_path, "agent_input_token_ceiling = \n")
    assert ic.resolve_ceiling(tmp_path, environ={ic.ENV_NAME: "70000"}) == 70_000


def test_never_reads_the_dot_simplicio_directory(tmp_path):
    (tmp_path / ".simplicio").mkdir()
    (tmp_path / ".simplicio" / "loop.toml").write_text("agent_input_token_ceiling = 5000\n", encoding="utf-8")
    assert ic.resolve_ceiling(tmp_path, environ={}) == 98_000


# --- estimator -------------------------------------------------------------------------------------------------------

def test_estimator_is_pure_python_with_no_tokenizer_dependency():
    tree = ast.parse(Path(ic.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "os", "re", "tomllib", "dataclasses", "pathlib", "typing"}


def test_estimate_basics():
    assert ic.estimate_tokens("") == 0
    assert ic.estimate_tokens("hello world") == ic.estimate_tokens("hello world")
    assert ic.estimate_tokens("hello world") >= 2
    for bad in (None, b"abc", 5):
        with pytest.raises(TypeError):
            ic.estimate_tokens(bad)


def test_estimate_survives_lone_surrogates_and_control_characters():
    assert ic.estimate_tokens("ok \ud800 \x00\x1b[0m") > 0


def test_estimate_grows_with_size():
    unit = "def f(x):\n    return x + 1\n"
    assert ic.estimate_tokens(unit * 100) > 50 * ic.estimate_tokens(unit)


@pytest.mark.parametrize("sample", REF["samples"], ids=[s["name"] for s in REF["samples"]])
def test_estimate_never_undercounts_the_reference_and_is_not_absurd(sample):
    est, ref = ic.estimate_tokens(sample["text"]), sample["ref_tokens"]
    assert ref > 0
    assert est >= ref * 1.15, "%s: estimate %d is below 1.15 x reference %d" % (sample["name"], est, ref)
    assert est <= ref * 4, "%s: estimate %d is above 4 x reference %d" % (sample["name"], est, ref)
    if sample["name"].startswith("prose_"):
        assert est <= ref * 2.5


def test_safety_factor_covers_the_measured_error_of_the_estimator():
    """The raw estimator has no undercount on the reference; SAFETY_PERCENT stacks on top of that margin.
    Worst case (lowest estimate/reference ratio) is printed for the PR evidence; Claude tokenizer error is UNVERIFIED."""
    ratios = {s["name"]: ic.estimate_tokens(s["text"]) / s["ref_tokens"] for s in REF["samples"]}
    worst_name = min(ratios, key=ratios.get)
    worst = ratios[worst_name]
    print("worst raw ratio: %s %.3f; with safety factor: %.3f" % (worst_name, worst, worst * ic.SAFETY_PERCENT / 100))
    assert worst >= 1.15
    assert worst * ic.SAFETY_PERCENT / 100 >= 1.38


# --- measured total prompt ---------------------------------------------------------------------------------------------

USAGE = {"input_tokens": 10, "cache_read_input_tokens": 90_000, "cache_creation_input_tokens": 500, "output_tokens": 7}


def test_prompt_usage_total_is_new_plus_cache_read_plus_cache_write():
    u = ic.PromptUsage.from_usage(USAGE)
    assert (u.input_tokens, u.cache_read_input_tokens, u.cache_creation_input_tokens) == (10, 90_000, 500)
    assert u.total == 90_510


def test_prompt_usage_each_count_matters():
    assert ic.PromptUsage(1, 0, 0).total == 1
    assert ic.PromptUsage(0, 1, 0).total == 1
    assert ic.PromptUsage(0, 0, 1).total == 1


@pytest.mark.parametrize("missing", ["input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"])
def test_prompt_usage_requires_all_three_counts(missing):
    usage = {k: v for k, v in USAGE.items() if k != missing}
    with pytest.raises(ValueError):
        ic.PromptUsage.from_usage(usage)


@pytest.mark.parametrize("bad", [True, False, -1, 1.5, "5", None])
def test_prompt_usage_rejects_non_counts(bad):
    for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        with pytest.raises(ValueError):
            ic.PromptUsage.from_usage({**USAGE, key: bad})


def test_prompt_usage_rejects_a_non_mapping():
    with pytest.raises(ValueError):
        ic.PromptUsage.from_usage(None)


# --- projection of the NEXT request -----------------------------------------------------------------------------------

def _added(text):
    return (ic.estimate_tokens(text) * ic.SAFETY_PERCENT + 99) // 100


def test_measured_projection_is_last_total_plus_safety_scaled_estimate_of_the_addition():
    last = ic.PromptUsage.from_usage(USAGE)
    text = "tool result line\n" * 200
    p = ic.Projection.measured(last, text)
    assert p.basis == "MEASURED"
    assert p.measured_base == 90_510
    assert p.estimated_tokens == _added(text) > ic.estimate_tokens(text)
    assert p.tokens == 90_510 + _added(text)
    assert p.estimator == ic.ESTIMATOR_LABEL


def test_measured_projection_without_addition_is_the_last_total():
    p = ic.Projection.measured(ic.PromptUsage(5, 6, 7), "")
    assert (p.tokens, p.estimated_tokens, p.measured_base) == (18, 0, 18)


def test_estimated_projection_scales_the_whole_prompt_by_the_safety_factor():
    text = "word " * 400
    p = ic.Projection.estimated(text)
    assert p.basis == "ESTIMATED"
    assert p.measured_base is None
    assert p.estimated_tokens == p.tokens == _added(text)
    assert p.tokens > ic.estimate_tokens(text)
    assert p.estimator == ic.ESTIMATOR_LABEL


def test_projection_constructors_check_their_arguments():
    with pytest.raises(TypeError):
        ic.Projection.measured(90_000, "x")
    with pytest.raises(TypeError):
        ic.Projection.measured(ic.PromptUsage(1, 1, 1), None)
    with pytest.raises(TypeError):
        ic.Projection.estimated(None)


def test_projection_labels_cannot_be_mixed():
    ok = dict(tokens=10, basis="MEASURED", measured_base=10, estimated_tokens=0, estimator=ic.ESTIMATOR_LABEL)
    assert ic.Projection(**ok).tokens == 10
    for override in (
        {"measured_base": None},                                  # MEASURED without a measured base
        {"basis": "ESTIMATED"},                                   # ESTIMATED that carries a measured base
        {"basis": "measured"},                                    # unknown label
        {"tokens": 11},                                           # total does not add up
        {"estimator": None},
        {"tokens": True, "measured_base": True},
        {"measured_base": -1, "tokens": -1},
    ):
        with pytest.raises(ValueError):
            ic.Projection(**{**ok, **override})


# --- budget decision -------------------------------------------------------------------------------------------------

def _p(total):
    return ic.Projection.measured(ic.PromptUsage(total, 0, 0), "")


@pytest.mark.parametrize("total,status", [
    (1, "ok"), (88_199, "ok"),
    (88_200, "handoff"), (97_999, "handoff"), (98_000, "handoff"),
    (98_001, "over"), (200_000, "over"),
])
def test_status_boundaries_for_the_98k_ceiling(total, status):
    v = ic.check_budget(_p(total), 98_000)
    assert v.status == status
    assert v.tokens == total and v.ceiling == 98_000
    assert v.headroom == 98_000 - total
    assert v.soft_limit == 88_200
    assert v.ratio == pytest.approx(total / 98_000)


def test_verdict_carries_the_basis_of_the_projection():
    assert ic.check_budget(_p(10), 98_000).basis == "MEASURED"
    assert ic.check_budget(ic.Projection.estimated("x"), 98_000).basis == "ESTIMATED"


def test_cache_reads_and_writes_count_against_the_ceiling():
    only_uncached_would_pass = ic.PromptUsage(10, 97_000, 2_000)
    v = ic.check_budget(ic.Projection.measured(only_uncached_would_pass, ""), 98_000)
    assert v.tokens == 99_010 and v.status == "over"
    assert ic.check_budget(ic.Projection.measured(ic.PromptUsage(10, 0, 97_990), ""), 98_000).status == "handoff"


def test_decision_is_on_the_projection_not_on_the_last_request():
    last = ic.PromptUsage(0, 87_000, 0)
    assert ic.check_budget(ic.Projection.measured(last, ""), 98_000).status == "ok"
    big_addition = "tool output line with some words in it\n" * 2_000
    v = ic.check_budget(ic.Projection.measured(last, big_addition), 98_000)
    assert v.status == "over"
    assert v.tokens > 98_000 > 87_000


def test_soft_threshold_is_configurable_and_validated():
    assert ic.check_budget(_p(499), 1_000, soft_percent=50).status == "ok"
    assert ic.check_budget(_p(500), 1_000, soft_percent=50).status == "handoff"
    assert ic.check_budget(_p(1_000), 1_000, soft_percent=50).status == "handoff"
    assert ic.check_budget(_p(1_001), 1_000, soft_percent=50).status == "over"
    for bad in (0, 100, 101, -1, True, 50.0, "50", None):
        with pytest.raises(ValueError):
            ic.check_budget(_p(1), 1_000, soft_percent=bad)


@pytest.mark.parametrize("bad", [0, -1, True, False, 98_000.0, "98000", None])
def test_ceiling_argument_is_validated(bad):
    with pytest.raises(ValueError):
        ic.check_budget(_p(1), bad)


def test_projection_argument_must_be_a_projection():
    for bad in (5, 98_000, "5", None, {"tokens": 5}):
        with pytest.raises(TypeError):
            ic.check_budget(bad, 98_000)


def test_enforce_budget_raises_only_above_the_ceiling():
    assert ic.enforce_budget(_p(10), 98_000).status == "ok"
    assert ic.enforce_budget(_p(90_000), 98_000).status == "handoff"
    assert ic.enforce_budget(_p(98_000), 98_000).status == "handoff"
    with pytest.raises(ic.InputCeilingExceeded) as exc:
        ic.enforce_budget(_p(98_001), 98_000)
    assert exc.value.reason_code == "input_ceiling_exceeded"
    assert exc.value.verdict.status == "over" and exc.value.verdict.tokens == 98_001
    assert re.search(r"98001|98,001", str(exc.value))


# --- reviewer additions (#1613) ------------------------------------------------------------------------------------------
def test_zero_usage_is_not_a_measurement():
    with pytest.raises(ValueError):
        ic.PromptUsage(0, 0, 0)
    with pytest.raises(ValueError):
        ic.PromptUsage.from_usage({"input_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})


@pytest.mark.parametrize("ceiling", [1, 2, 10, 99, 98001])
def test_soft_limit_is_the_first_handoff_token(ceiling):
    soft = ic.check_budget(ic.Projection.estimated(""), ceiling).soft_limit
    def at(n):
        return ic.check_budget(ic.Projection(n, ic.ESTIMATED, None, n, "x"), ceiling).status
    assert at(soft) != ic.OK and (soft == 0 or at(soft - 1) == ic.OK)


def test_toml_with_bytes_that_are_not_utf8_is_a_config_error(tmp_path):
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / ".simplicio-loop" / "loop.toml").write_bytes(b"agent_input_token_ceiling = \xff\xfe")
    with pytest.raises(ic.CeilingConfigError):
        ic.resolve_ceiling(tmp_path, {})
