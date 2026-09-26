"""TDD unit tests for bench/llm_ab/arms.py (issue #1337 ablation benchmark):
the 7-arm spec table used to isolate skills + PATH binaries per arm."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import arms  # noqa: E402

EXPECTED_ARMS = (
    "normal", "mapper", "mapper-fast", "devcli", "mapper-devcli", "fast-devcli", "simplicio",
)


def test_arm_names_has_exactly_the_7_ablation_arms():
    assert arms.ARM_NAMES == EXPECTED_ARMS


@pytest.mark.parametrize("name", EXPECTED_ARMS)
def test_every_arm_spec_has_the_required_keys(name):
    s = arms.ARM_SPECS[name]
    assert set(s.keys()) == {"skills", "bins", "prompt_prefix"}
    assert isinstance(s["skills"], list)
    assert isinstance(s["bins"], list)
    assert isinstance(s["prompt_prefix"], str)


def test_normal_arm_has_no_skills_no_bins_no_prefix():
    s = arms.ARM_SPECS["normal"]
    assert s["skills"] == []
    assert s["bins"] == []
    assert s["prompt_prefix"] == ""


def test_simplicio_arm_has_all_bins_and_loop_skill_and_slash_prefix():
    s = arms.ARM_SPECS["simplicio"]
    assert s["skills"] == ["simplicio-loop"]
    assert set(s["bins"]) == {
        "simplicio-mapper", "simplicio-fast", "simplicio-dev-cli", "simplicio-loop",
    }
    assert s["prompt_prefix"] == "/simplicio-loop "


@pytest.mark.parametrize(
    "arm,expected_bins",
    [
        ("mapper", {"simplicio-mapper"}),
        ("mapper-fast", {"simplicio-mapper", "simplicio-fast"}),
        ("devcli", {"simplicio-dev-cli"}),
        ("mapper-devcli", {"simplicio-mapper", "simplicio-dev-cli"}),
        ("fast-devcli", {"simplicio-fast", "simplicio-dev-cli"}),
    ],
)
def test_single_and_pair_arms_expose_exactly_their_bins(arm, expected_bins):
    assert set(arms.ARM_SPECS[arm]["bins"]) == expected_bins


@pytest.mark.parametrize("arm", ["mapper", "mapper-fast", "devcli", "mapper-devcli", "fast-devcli"])
def test_single_and_pair_arm_prefix_names_only_its_own_skills_and_forbids_the_rest(arm):
    s = arms.ARM_SPECS[arm]
    prefix = s["prompt_prefix"]
    assert prefix, f"{arm} must have a non-empty prompt_prefix"
    for skill in s["skills"]:
        assert skill in prefix
    assert "Do not invoke any other simplicio-* binary" in prefix
    # never names a binary it doesn't grant
    forbidden = set(arms.ALL_BINS) - set(s["bins"])
    for binary in forbidden:
        assert binary not in prefix.replace("Do not invoke any other simplicio-* binary", "")


def test_spec_returns_the_same_dict_as_arm_specs():
    assert arms.spec("mapper") is arms.ARM_SPECS["mapper"]


def test_spec_raises_value_error_naming_valid_arms_for_unknown_name():
    with pytest.raises(ValueError, match="unknown arm"):
        arms.spec("bogus-arm")
