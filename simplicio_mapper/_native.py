"""Optional Rust acceleration shim.

When the companion ``simplicio_mapper_rs`` Rust extension is installed (built
with maturin from the ``rust/`` directory), the mapper uses it for content
hashing and import parsing. Otherwise the pure-Python implementations in
``mapper`` are used. The Python package always works without the extension —
this module simply exposes whether the native fast path is available.
"""

from __future__ import annotations

from collections.abc import Callable

HAS_NATIVE: bool = False
sha256_hex: Callable[[str], str] | None = None
parse_imports: Callable[[str, str], list[str]] | None = None
parse_batch: Callable[[list[tuple[str, str, str]]], list[tuple[str, str, list[str]]]] | None = None
CAPABILITIES: dict[str, object] = {
    "schema": "simplicio.mapper-native/v1",
    "version": None,
    "features": [],
    "languages": [],
}

try:
    from simplicio_mapper_rs import (  # type: ignore[import-not-found]
        parse_batch as _native_parse_batch,
    )
    from simplicio_mapper_rs import (
        parse_imports as _native_parse_imports,
    )
    from simplicio_mapper_rs import (
        sha256_hex as _native_sha256_hex,
    )
except ImportError:
    pass
else:
    _native_module = __import__("simplicio_mapper_rs")
    sha256_hex = _native_sha256_hex
    parse_imports = _native_parse_imports
    parse_batch = _native_parse_batch
    HAS_NATIVE = True
    CAPABILITIES = {
        "schema": getattr(_native_module, "__schema__", "simplicio.mapper-native/v1"),
        "version": getattr(_native_module, "__version__", None),
        "features": list(getattr(_native_module, "__features__", [])),
        "languages": list(getattr(_native_module, "__languages__", [])),
    }


__all__ = ["CAPABILITIES", "HAS_NATIVE", "parse_batch", "parse_imports", "sha256_hex"]
