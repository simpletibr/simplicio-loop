from __future__ import annotations

from unittest.mock import patch

from simplicio_fast.tokenizers import resolve_tokenizer


def test_unconfigured_or_unknown_tokenizer_is_explicitly_unavailable() -> None:
    assert resolve_tokenizer(None) is None
    assert resolve_tokenizer("whitespace-v1") is None
    assert resolve_tokenizer(True) is None
    assert resolve_tokenizer(1) is None
    assert resolve_tokenizer([]) is None


def test_tiktoken_encoding_is_resolved_without_making_dependency_required() -> None:
    fake_encoding = type("Encoding", (), {"encode": lambda self, text: [*text]})()
    fake_module = type(
        "Tiktoken",
        (),
        {"get_encoding": staticmethod(lambda name: fake_encoding)},
    )
    with patch.dict("sys.modules", {"tiktoken": fake_module}):
        tokenizer = resolve_tokenizer("tiktoken:cl100k_base")
    assert tokenizer is not None
    assert tokenizer("abc") == 3


def test_unknown_tiktoken_encoding_falls_back_without_claiming_exactness() -> None:
    fake_module = type(
        "Tiktoken",
        (),
        {"get_encoding": staticmethod(lambda name: (_ for _ in ()).throw(KeyError(name)))},
    )
    with patch.dict("sys.modules", {"tiktoken": fake_module}):
        assert resolve_tokenizer("tiktoken:missing") is None


def test_tiktoken_model_resolution_and_malformed_provider_fail_closed() -> None:
    fake_encoding = type("Encoding", (), {"encode": lambda self, text: [*text]})()
    fake_module = type(
        "Tiktoken",
        (),
        {
            "encoding_for_model": staticmethod(lambda name: fake_encoding),
        },
    )
    with patch.dict("sys.modules", {"tiktoken": fake_module}):
        tokenizer = resolve_tokenizer("tiktoken:model:gpt-4o")
    assert tokenizer is not None
    assert tokenizer("model") == 5

    malformed_module = type("Tiktoken", (), {"get_encoding": staticmethod(lambda _: None)})
    with patch.dict("sys.modules", {"tiktoken": malformed_module}):
        assert resolve_tokenizer("tiktoken:cl100k_base") is None
    empty_model_module = type("Tiktoken", (), {"encoding_for_model": staticmethod(lambda _: fake_encoding)})
    with patch.dict("sys.modules", {"tiktoken": empty_model_module}):
        assert resolve_tokenizer("tiktoken:model: ") is None
