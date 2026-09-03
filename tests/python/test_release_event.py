from __future__ import annotations

import unittest

from scripts.build_release_event import build_release_event, github_dispatch_payload


def _manifest() -> dict:
    return {
        "schema": "simplicio.component-release/v1",
        "component": "simplicio-mapper",
        "version": "0.26.26",
        "commit_sha": "a" * 40,
        "artifact_digest": "sha256:" + "b" * 64,
        "artifact_digests": {"whl": {"filename": "mapper.whl", "digest": "sha256:" + "c" * 64}},
        "schema_versions": {"simplicio_mapper.plugin_context_handle:SCHEMA_V2": "v2"},
        "capabilities": ["simplicio.plugin.context-handle/v2"],
        "compatibility": {"simplicio-dev-cli": {"plugin-context-handle": "v1|v2"}},
        "signing": {"status": "not-implemented"},
    }


class ReleaseEventTest(unittest.TestCase):
    def test_event_is_idempotent_and_contains_consumer_contract(self) -> None:
        first = build_release_event(_manifest())
        second = build_release_event(_manifest())
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(first["dedupe_key"], first["event_id"])
        self.assertEqual(first["event_type"], "simplicio-component-release")
        self.assertEqual(len(first["consumers"]), 2)
        self.assertEqual(first["attestation"], "transport-authenticated-only")
        self.assertEqual(first["delivery"]["channel"], "canary")
        self.assertTrue(first["rollback"]["supported"])

    def test_unsigned_manifest_cannot_emit_stable_event(self) -> None:
        with self.assertRaises(ValueError):
            build_release_event(_manifest(), channel="stable")

    def test_dispatch_payload_has_github_shape(self) -> None:
        payload = github_dispatch_payload(build_release_event(_manifest()))
        self.assertEqual(payload["event_type"], "simplicio-component-release")
        self.assertEqual(payload["client_payload"]["schema"], "simplicio.component-release-event/v1")

    def test_bad_manifest_fails_closed(self) -> None:
        bad = _manifest()
        bad["artifact_digest"] = None
        with self.assertRaises(ValueError):
            build_release_event(bad)


if __name__ == "__main__":
    unittest.main()
