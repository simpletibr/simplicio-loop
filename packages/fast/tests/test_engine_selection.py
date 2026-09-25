from __future__ import annotations

import unittest

from simplicio_fast.engine_selection import (
    EngineSelectionError,
    resolve_mode,
    select_engine,
)


class EngineSelectionTest(unittest.TestCase):
    def test_auto_selects_rust_only_after_health_and_conformance(self) -> None:
        selected = select_engine(
            rust_probe={"healthy": True, "capabilities_ok": True},
            conformance_passed=True,
        )
        self.assertEqual(selected.selected, "rust")
        self.assertTrue(selected.usable)

    def test_auto_fallback_is_explicit(self) -> None:
        selected = select_engine(
            rust_probe={"healthy": True, "capabilities_ok": True},
            conformance_passed=False,
        )
        self.assertEqual(selected.selected, "python")
        self.assertEqual(selected.reason, "rust_conformance_missing")

    def test_mode_precedence_is_cli_workspace_user_default(self) -> None:
        self.assertEqual(
            ("python", "cli"), resolve_mode(cli="python", workspace="rust", user="off")
        )
        self.assertEqual(
            ("rust", "workspace"), resolve_mode(workspace="rust", user="off")
        )
        self.assertEqual(("off", "user"), resolve_mode(user="off"))
        self.assertEqual(("auto", "default"), resolve_mode())

    def test_invalid_mode_reports_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "workspace"):
            resolve_mode(workspace="turbo")

    def test_explicit_rust_is_fail_closed(self) -> None:
        with self.assertRaises(EngineSelectionError):
            select_engine(
                "rust", rust_probe={"healthy": False}, conformance_passed=False
            )

    def test_off_does_not_select_python(self) -> None:
        selected = select_engine("off", python_available=True)
        self.assertIsNone(selected.selected)
        self.assertFalse(selected.usable)


if __name__ == "__main__":
    unittest.main()
