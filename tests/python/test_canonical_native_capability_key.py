from __future__ import annotations

import unittest

from simplicio_mapper.mapper.canonical import CanonicalMapKey


class CanonicalNativeCapabilityKeyTest(unittest.TestCase):
    def _key(self, native_capabilities: str) -> CanonicalMapKey:
        return CanonicalMapKey(
            repo_identity="repo",
            default_branch="main",
            commit_sha="commit",
            tree_sha="tree",
            schema_version=1,
            mapper_version="0.26.6",
            config_fingerprint="config",
            native_capabilities=native_capabilities,
        )

    def test_native_capabilities_participate_in_canonical_digest(self) -> None:
        self.assertNotEqual(self._key("python-only").digest(), self._key("rust-v1").digest())

    def test_legacy_key_defaults_capabilities_to_empty(self) -> None:
        self.assertEqual(self._key("").native_capabilities, "")


if __name__ == "__main__":
    unittest.main()
