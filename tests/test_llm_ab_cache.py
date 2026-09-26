"""TDD unit tests for bench/llm_ab/cache.py (pure cache-hit detection)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import cache as bench_cache  # noqa: E402


def test_no_hit_when_previous_is_none():
    assert bench_cache.is_cache_hit(None, "gen-a") is False


def test_no_hit_when_current_is_none():
    assert bench_cache.is_cache_hit("gen-a", None) is False


def test_no_hit_when_both_empty_string():
    assert bench_cache.is_cache_hit("", "") is False


def test_hit_when_identical_non_empty():
    assert bench_cache.is_cache_hit("gen-a", "gen-a") is True


def test_no_hit_when_different():
    assert bench_cache.is_cache_hit("gen-a", "gen-b") is False


def test_extract_generations_from_full_orient_payload():
    payload = {
        "fast": {
            "generation": "sha256:fastgen",
            "ingest": {
                "fast_receipt": {
                    "mapper": {"generation": "sha256:mappergen"},
                },
            },
        },
    }
    got = bench_cache.extract_generations(payload)
    assert got == {"mapper_generation": "sha256:mappergen", "fast_generation": "sha256:fastgen"}


def test_extract_generations_tolerates_missing_fast_block():
    assert bench_cache.extract_generations({}) == {
        "mapper_generation": None,
        "fast_generation": None,
    }


def test_extract_generations_tolerates_none_payload():
    assert bench_cache.extract_generations(None) == {
        "mapper_generation": None,
        "fast_generation": None,
    }


def test_extract_generations_tolerates_partial_nesting():
    payload = {"fast": {"generation": "sha256:fastonly"}}
    got = bench_cache.extract_generations(payload)
    assert got == {"mapper_generation": None, "fast_generation": "sha256:fastonly"}
