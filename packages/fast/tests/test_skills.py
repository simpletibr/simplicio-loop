from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from simplicio_fast.skills import (
    AuthorizedSkill,
    SKILL_CATALOG_SCHEMA,
    SKILL_MATERIALIZATION_SCHEMA,
    SkillCatalog,
)


def skill(
    name: str, *, content: str, triggers: tuple[str, ...], scope: str = "repo-a"
) -> AuthorizedSkill:
    return AuthorizedSkill(
        name=name,
        version="1.0.0",
        origin=f"host://skills/{name}",
        description=f"{name} workflow",
        content=content,
        triggers=triggers,
        capabilities=(name,),
        scope=scope,
    )


class SkillCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.catalog = SkillCatalog(
            Path(self.directory.name), "SFAST001:generation", scope="repo-a"
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_resolve_returns_bounded_t0_handles_without_content(self) -> None:
        handle = self.catalog.register(
            skill("python-tests", content="SECRET BODY", triggers=("pytest",))
        )
        self.catalog.register(
            skill("deploy", content="deploy body", triggers=("release",))
        )

        result = self.catalog.resolve("run pytest", max_results=1)

        self.assertEqual(SKILL_CATALOG_SCHEMA, result["schema"])
        self.assertEqual([handle], result["handles"])
        self.assertEqual("python-tests", result["skills"][0]["name"])
        self.assertNotIn("content", result["skills"][0])
        self.assertEqual("available", result["source"]["status"])
        self.assertFalse(result["source"]["runtime_required"])

    def test_ranking_is_deterministic_and_irrelevant_skills_are_excluded(self) -> None:
        first = skill("one", content="one", triggers=("build",))
        second = skill("two", content="two", triggers=("build", "test"))
        self.catalog.register_many((first, second))

        result = self.catalog.resolve("build test")

        self.assertEqual(["two", "one"], [item["name"] for item in result["skills"]])
        self.assertEqual(["build", "test"], result["skills"][0]["matched_triggers"])
        self.assertFalse(result["truncated"])

    def test_materialize_is_scoped_and_byte_bounded(self) -> None:
        first = self.catalog.register(
            skill("first", content="12345", triggers=("one",))
        )
        second = self.catalog.register(
            skill("second", content="67890", triggers=("two",))
        )

        result = self.catalog.materialize((first, second), max_entries=2, max_bytes=5)

        self.assertEqual(SKILL_MATERIALIZATION_SCHEMA, result["schema"])
        self.assertEqual(1, result["entries_materialized"])
        self.assertEqual(5, result["bytes_materialized"])
        self.assertTrue(result["truncated"])
        self.assertEqual("12345", result["materialized"][0]["content"])
        self.assertEqual(
            hashlib.sha256(b"12345").hexdigest(),
            result["materialized"][0]["content_sha256"],
        )

    def test_materialize_deduplicates_handles_and_preserves_provenance(self) -> None:
        handle = self.catalog.register(
            skill("python-tests", content="pytest", triggers=("pytest",))
        )

        result = self.catalog.materialize((handle, handle))

        self.assertEqual(1, result["entries_materialized"])
        self.assertEqual(handle, result["materialized"][0]["handle"])
        self.assertEqual(
            "host://skills/python-tests", result["materialized"][0]["origin"]
        )
        self.assertEqual("repo-a", result["materialized"][0]["scope"])

    def test_scope_is_required_and_cross_scope_registration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "scope"):
            self.catalog.register(
                skill("other", content="x", triggers=(), scope="repo-b")
            )
        with self.assertRaises(ValueError):
            SkillCatalog(Path(self.directory.name), "SFAST001:generation", scope="")

    def test_handle_is_not_accepted_by_another_generation_catalog(self) -> None:
        handle = self.catalog.register(
            skill("python-tests", content="pytest", triggers=("pytest",))
        )
        other = SkillCatalog(
            Path(self.directory.name), "SFAST001:other", scope="repo-a"
        )

        with self.assertRaisesRegex(ValueError, "unknown catalog handle"):
            other.materialize((handle,))


if __name__ == "__main__":
    unittest.main()
