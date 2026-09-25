from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simplicio_mapper.ecc_guidance import (
    ECC_DEFAULT_REF,
    ECC_GUIDANCE_SCHEMA,
    ECC_MANIFEST_SCHEMA,
    ECC_SOURCE_REPOSITORY,
    EccGuidanceError,
    EccGuidanceProvider,
    EccManifest,
    load_manifest,
)


def _manifest(*, skills=("plan-orchestrate",), agents=("planner",), max_context_chars=2048):
    return EccManifest(
        schema=ECC_MANIFEST_SCHEMA,
        source=ECC_SOURCE_REPOSITORY,
        ref=ECC_DEFAULT_REF,
        enabled=True,
        max_components_per_stage=3,
        max_context_chars=max_context_chars,
        allow_hooks=False,
        forbidden_components=("autonomous-loops", "continuous-agent-loop", "loop-operator"),
        stages={"planning": {"skills": skills, "agents": agents}},
    )


def _root(tmp: Path) -> Path:
    root = tmp / "ECC"
    (root / "skills" / "plan-orchestrate").mkdir(parents=True)
    (root / "agents").mkdir()
    (root / "skills" / "plan-orchestrate" / "SKILL.md").write_text(
        "---\nname: plan-orchestrate\n---\nUse bounded planning.\n", encoding="utf-8"
    )
    (root / "agents" / "planner.md").write_text(
        "---\nname: planner\n---\nKeep the plan evidence-backed.\n", encoding="utf-8"
    )
    return root


class EccGuidanceTest(unittest.TestCase):
    def test_provider_is_disabled_without_explicit_opt_in(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(EccGuidanceProvider.from_environment())

    def test_pack_is_bounded_and_hashes_raw_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = EccGuidanceProvider(_root(Path(directory)), manifest=_manifest())
            with patch.object(
                provider,
                "provenance",
                return_value={
                    "status": "VERIFIED",
                    "expected_ref": ECC_DEFAULT_REF,
                    "observed_ref": ECC_DEFAULT_REF,
                },
            ):
                pack = provider.pack("planning")

        self.assertEqual(pack["schema"], ECC_GUIDANCE_SCHEMA)
        self.assertEqual(pack["status"], "READY")
        self.assertEqual(pack["authority"], "simplicio-mapper")
        self.assertEqual(pack["execution_policy"], "advisory-only")
        self.assertEqual(pack["hooks"], "disabled")
        self.assertEqual(pack["orchestration"], "disabled")
        self.assertLessEqual(len(pack["prompt"]), 2048)
        raw = b"---\nname: plan-orchestrate\n---\nUse bounded planning.\n"
        self.assertEqual(pack["skills"][0]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertTrue(pack["agents"][0]["content"])
        self.assertEqual(len(pack["pack_hash"]), 64)

    def test_required_pinned_ref_fails_closed_without_matching_git_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = EccGuidanceProvider(_root(Path(directory)), manifest=_manifest(), require_ref=True)
            pack = provider.pack("planning")

        self.assertEqual(pack["status"], "BLOCKED")
        self.assertNotEqual(pack["provenance"]["status"], "VERIFIED")

    def test_forbidden_component_is_never_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ECC"
            (root / "skills" / "autonomous-loops").mkdir(parents=True)
            (root / "skills" / "autonomous-loops" / "SKILL.md").write_text(
                "do not run a second loop", encoding="utf-8"
            )
            provider = EccGuidanceProvider(
                root,
                manifest=_manifest(skills=("autonomous-loops",), agents=()),
            )
            with patch.object(
                provider,
                "provenance",
                return_value={
                    "status": "VERIFIED",
                    "expected_ref": ECC_DEFAULT_REF,
                    "observed_ref": ECC_DEFAULT_REF,
                },
            ):
                pack = provider.pack("planning")

        self.assertEqual(pack["status"], "BLOCKED")
        self.assertEqual(pack["blocked_components"], ["autonomous-loops"])
        self.assertEqual(pack["skills"], [])

    def test_manifest_requires_a_full_commit_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.toml"
            path.write_text(
                'schema = "simplicio.ecc-manifest/v1"\nsource = "x"\nref = "main"\n',
                encoding="utf-8",
            )
            with self.assertRaises(EccGuidanceError):
                load_manifest(path)


if __name__ == "__main__":
    unittest.main()
