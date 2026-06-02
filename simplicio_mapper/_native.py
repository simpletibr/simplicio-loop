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

try:
    from simplicio_mapper_rs import (  # type: ignore[import-not-found]
        parse_imports as _native_parse_imports,
    )
    from simplicio_mapper_rs import (
        sha256_hex as _native_sha256_hex,
    )
except ImportError:
    pass
else:
    sha256_hex = _native_sha256_hex
    parse_imports = _native_parse_imports
    HAS_NATIVE = True


__all__ = ["HAS_NATIVE", "parse_imports", "sha256_hex"]
