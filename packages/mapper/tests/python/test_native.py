"""Tests for the optional Rust acceleration path (PyO3 hybrid, issue #83).

Covers the native shim, the mapper's transparent fall-back to pure Python when
the extension is absent, and that both code paths produce byte-for-byte
identical outputs.
"""

from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _reload_with_native(enabled: bool):
    """Reload _native and mapper with the rust module hidden when needed."""
    import simplicio_mapper._native as native_module
    import simplicio_mapper.mapper as mapper_module

    original_rust = sys.modules.get("simplicio_mapper_rs")
    try:
        if not enabled and "simplicio_mapper_rs" in sys.modules:
            sys.modules["simplicio_mapper_rs"] = None  # type: ignore[assignment]
        importlib.reload(native_module)
        importlib.reload(mapper_module)
        return native_module, mapper_module
    finally:
        if original_rust is None:
            sys.modules.pop("simplicio_mapper_rs", None)
        else:
            sys.modules["simplicio_mapper_rs"] = original_rust


class NativeShimTest(unittest.TestCase):
    def test_shim_reports_availability(self) -> None:
        from simplicio_mapper import _native

        try:
            import simplicio_mapper_rs  # noqa: F401
        except ImportError:
            self.assertFalse(_native.HAS_NATIVE)
            self.assertIsNone(_native.sha256_hex)
            self.assertIsNone(_native.parse_imports)
        else:
            self.assertTrue(_native.HAS_NATIVE)
            self.assertEqual(
                _native.sha256_hex("abc"),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )
            self.assertEqual(
                _native.parse_imports("from os import path\nimport sys\n", "python"),
                ["os", "sys"],
            )


class FallbackEqualsNativeTest(unittest.TestCase):
    """If the native extension is present, both paths must agree."""

    def setUp(self) -> None:
        try:
            import simplicio_mapper_rs  # noqa: F401
        except ImportError:
            self.skipTest("simplicio_mapper_rs not built; skipping byte-for-byte check")

    def test_hash_and_imports_match_fallback(self) -> None:
        native, mapper = _reload_with_native(True)
        try:
            native_hash = mapper._sha256("hello world\n")
            native_imports = mapper._parse_imports(
                "import json\nfrom os import path\nimport sys\n", "python"
            )
        finally:
            _reload_with_native(False)

        fallback_native, fallback_mapper = _reload_with_native(False)
        try:
            self.assertFalse(fallback_native.HAS_NATIVE)
            fallback_hash = fallback_mapper._sha256("hello world\n")
            fallback_imports = fallback_mapper._parse_imports(
                "import json\nfrom os import path\nimport sys\n", "python"
            )
        finally:
            _reload_with_native(True)

        self.assertEqual(native_hash, fallback_hash)
        self.assertEqual(native_imports, fallback_imports)


class MapperRunsWithoutNativeTest(unittest.TestCase):
    """Ensure mapper.build_artifacts works when the native extension is hidden."""

    def test_build_artifacts_without_native(self) -> None:
        _, mapper = _reload_with_native(False)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / "package.json").write_text('{"name":"fallback-host"}')
                (base / "src").mkdir()
                (base / "src" / "index.py").write_text("import os\nimport sys\n")

                result = mapper.build_artifacts(cwd=str(base), meta={"stack": "python"})
                files = result["project_map"]["files"]
                index = next(f for f in files if f["path"] == "src/index.py")
                self.assertEqual(index["imports"], ["os", "sys"])
                self.assertTrue(index["file_hash"])
        finally:
            _reload_with_native(True)


if __name__ == "__main__":
    unittest.main()
