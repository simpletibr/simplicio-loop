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
merge_edges: Callable[[list[tuple[str, str, str]]], list[tuple[str, str, str]]] | None = None
parse_symbols_batch: (
    Callable[[list[tuple[str, str, str]]], list[tuple[str, str, list[str], list[str]]]] | None
) = None
build_symbol_index: Callable[[list[tuple[str, str, int]]], list[tuple[str, str, int]]] | None = None
schema_registry_sha256: Callable[[str], str] | None = None
CAPABILITIES: dict[str, object] = {
    "schema": "simplicio.mapper-native/v1",
    "version": None,
    "features": [],
    "languages": [],
}

# Availability and selection are separate concerns.  The extension can expose
# more kernels than the Python mapper is allowed to use as native defaults;
# each default is negotiated by capability rather than by one global switch.
NATIVE_DEFAULT_CAPABILITIES = frozenset(
    {"files", "imports", "batch"}
)
_CORE_FEATURE_FOR_CAPABILITY = {
    "files": "sha256",
    "imports": "imports",
    "batch": "batch",
    "symbol-index": "symbol-index",
}


def native_default(capability: str) -> bool:
    """Return whether one named core capability may run natively by default."""
    if not HAS_NATIVE or capability not in NATIVE_DEFAULT_CAPABILITIES:
        return False
    features = CAPABILITIES.get("features")
    feature = _CORE_FEATURE_FOR_CAPABILITY.get(capability, capability)
    return isinstance(features, (list, tuple, set, frozenset)) and feature in features

try:
    from simplicio_mapper_rs import (
        merge_edges as _native_merge_edges,
    )
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
    merge_edges = _native_merge_edges
    parse_symbols_batch = getattr(_native_module, "parse_symbols_batch", None)
    build_symbol_index = getattr(_native_module, "build_symbol_index", None)
    schema_registry_sha256 = getattr(_native_module, "schema_registry_sha256", None)
    HAS_NATIVE = True
    CAPABILITIES = {
        "schema": getattr(_native_module, "__schema__", "simplicio.mapper-native/v1"),
        "version": getattr(_native_module, "__version__", None),
        "features": list(getattr(_native_module, "__features__", [])),
        "languages": list(getattr(_native_module, "__languages__", [])),
    }


__all__ = [
    "CAPABILITIES",
    "HAS_NATIVE",
    "NATIVE_DEFAULT_CAPABILITIES",
    "build_symbol_index",
    "merge_edges",
    "parse_batch",
    "parse_imports",
    "parse_symbols_batch",
    "schema_registry_sha256",
    "sha256_hex",
    "native_default",
]
