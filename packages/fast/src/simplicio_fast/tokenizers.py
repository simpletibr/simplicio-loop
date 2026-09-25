"""Optional exact provider tokenizer resolution for delivery preparation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class TokenizerCacheMiss(Exception):
    """Raised when a tiktoken encoding's data file is not already cached locally.

    tiktoken lazily fetches its BPE data files from a remote blob store on
    first use. Reaching out to the network from inside a resolution helper
    is exactly the behaviour that makes this module's callers (including
    unit tests and the tokenizer-matrix benchmark) network-dependent and
    non-hermetic. ``resolve_tokenizer`` blocks that fetch primitive for the
    duration of the resolve call, so an encoding that is not already cached
    surfaces as an explicit, immediate "unavailable" instead of a slow (and
    here, environment-blocked) network attempt.
    """


def _blocked_read_file(blobpath: str) -> bytes:
    raise TokenizerCacheMiss(f"tiktoken data file not cached locally: {blobpath}")


def _load_encoding_without_network(tiktoken_module: Any, loader: Callable[[], Any]) -> Any:
    """Call ``loader`` (a tiktoken encoding constructor) with network fetches blocked.

    If the underlying data file is already present in tiktoken's local cache,
    the block never engages and the call proceeds normally. When ``tiktoken``
    has been replaced (e.g. by a test double) with something that has no
    ``tiktoken.load`` submodule, there is no network primitive to block, so
    the loader runs unguarded exactly as before.
    """
    try:
        import tiktoken.load as tiktoken_load
    except ImportError:
        return loader()
    original_read_file = tiktoken_load.read_file
    tiktoken_load.read_file = _blocked_read_file
    try:
        return loader()
    finally:
        tiktoken_load.read_file = original_read_file


def resolve_tokenizer(tokenizer_id: str | None) -> Callable[[str], int] | None:
    """Resolve a configured tiktoken encoding/model without making it required.

    ``tokenizer_id`` accepts ``tiktoken:<encoding>`` or ``tiktoken:model:<name>``.
    A missing optional dependency, unknown model, or an encoding whose data
    file is not already cached locally returns ``None`` so callers retain the
    explicit estimated-token receipt rather than claiming precision or
    reaching out to the network.
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
            encoding = _load_encoding_without_network(
                tiktoken, lambda: tiktoken.encoding_for_model(model)
            )
        else:
            encoding = _load_encoding_without_network(
                tiktoken, lambda: tiktoken.get_encoding(target)
            )
    except (AttributeError, KeyError, TypeError, ValueError, TokenizerCacheMiss):
        return None
    if not callable(getattr(encoding, "encode", None)):
        return None
    return lambda text: len(encoding.encode(text))


__all__ = ["resolve_tokenizer", "TokenizerCacheMiss"]
