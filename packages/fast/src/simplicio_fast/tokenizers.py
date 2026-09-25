"""Optional exact provider tokenizer resolution for delivery preparation."""

from __future__ import annotations

from collections.abc import Callable


def resolve_tokenizer(tokenizer_id: str | None) -> Callable[[str], int] | None:
    """Resolve a configured tiktoken encoding/model without making it required.

    ``tokenizer_id`` accepts ``tiktoken:<encoding>`` or ``tiktoken:model:<name>``.
    A missing optional dependency or unknown model returns ``None`` so callers
    retain the explicit estimated-token receipt rather than claiming precision.
    """
    if tokenizer_id is None:
        return None
    if not isinstance(tokenizer_id, str):
        return None
    value = tokenizer_id.strip()
    if not value.startswith("tiktoken:"):
        return None
    target = value.removeprefix("tiktoken:").strip()
    if not target:
        return None
    try:
        import tiktoken  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        if target.startswith("model:"):
            model = target.removeprefix("model:").strip()
            if not model:
                return None
            encoding = tiktoken.encoding_for_model(model)
        else:
            encoding = tiktoken.get_encoding(target)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if not callable(getattr(encoding, "encode", None)):
        return None
    return lambda text: len(encoding.encode(text))


__all__ = ["resolve_tokenizer"]
