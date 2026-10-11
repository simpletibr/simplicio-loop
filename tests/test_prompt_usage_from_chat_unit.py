"""``PromptUsage.from_chat_usage`` reads the three counts of a chat ``usage`` object and never invents one (#1608).

``prompt_tokens`` is the whole prompt; the cache reads and writes are inside it, so the new input is what is left.
"""
from __future__ import annotations

import pytest

from simplicio_loop.input_ceiling import PromptUsage


def _usage(prompt=1000, cached=600, written=100):
    details = {}
    if cached is not None:
        details["cached_tokens"] = cached
    if written is not None:
        details["cache_write_tokens"] = written
    return {"prompt_tokens": prompt, "completion_tokens": 50, "prompt_tokens_details": details}


def test_the_three_reported_counts_become_one_usage():
    usage = PromptUsage.from_chat_usage(_usage())
    assert usage == PromptUsage(300, 600, 100)
    assert usage.total == 1000


@pytest.mark.parametrize("usage", [
    None, [], "x",
    {"prompt_tokens": 1000},  # no details at all
    _usage(cached=None),  # the cache read count is absent
    _usage(written=None),  # the cache write count is absent
    _usage(prompt=None),
    _usage(prompt=True),
    _usage(prompt=-1),
    _usage(cached=1500),  # more cached than the whole prompt: the new input would be negative
    _usage(prompt=0, cached=0, written=0),  # an empty prompt is not a measurement
])
def test_anything_but_three_reported_counts_gives_none(usage):
    assert PromptUsage.from_chat_usage(usage) is None
