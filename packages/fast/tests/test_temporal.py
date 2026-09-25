from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from simplicio_fast.temporal import (
    BitemporalOverlay,
    PERSISTENCE_MAGIC,
    TemporalInvariantError,
)


class BitemporalOverlayTest(unittest.TestCase):
    def test_as_of_preserves_previous_version_after_update(self) -> None:
        overlay = BitemporalOverlay(
            "repo", base_generation="base", overlay_generation="slot-1"
        )
        entity = "a" * 64
        overlay.append(
            entity,
            source_commit="c1",
            source_sha256="b" * 64,
            artifact_digest="d" * 64,
        )
        second = overlay.append(
            entity,
            source_commit="c2",
            source_sha256="e" * 64,
            artifact_digest="f" * 64,
        )
        self.assertEqual(["c1"], [fact.source_commit for fact in overlay.as_of(1)])
        self.assertEqual([second.digest], [fact.digest for fact in overlay.as_of(2)])
        self.assertEqual(
            "superseded", overlay.as_of(1, include_tombstones=True)[0].state
        )
        self.assertEqual("valid", overlay.verify()["status"])

    def test_dependency_invalidation_holds_only_affected_facts(self) -> None:
        overlay = BitemporalOverlay("repo", base_generation="base")
        dependent = "a" * 64
        unrelated = "b" * 64
        changed = "c" * 64
        overlay.append(
            dependent,
            source_commit="c1",
            source_sha256="d" * 64,
            artifact_digest="e" * 64,
            dependencies=(changed,),
        )
        overlay.append(
            unrelated,
            source_commit="c1",
            source_sha256="f" * 64,
            artifact_digest="0" * 64,
            dependencies=("1" * 64,),
        )

        receipt = overlay.invalidate_dependencies(
            [changed],
            source_commit="c2",
            source_sha256="2" * 64,
        )
        self.assertEqual("simplicio.fast.invalidation/v1", receipt["schema"])
        self.assertEqual("invalidated", receipt["status"])
        self.assertEqual([dependent], receipt["affected_ids"])
        current = {
            fact.canonical_id: fact
            for fact in overlay.as_of(overlay.receipt()["as_of"])
        }
        self.assertEqual("held", current[dependent].state)
        self.assertEqual("active", current[unrelated].state)
        self.assertEqual("dependency_changed", current[dependent].reason_code)

    def test_rename_and_tombstone_are_auditable(self) -> None:
        overlay = BitemporalOverlay("repo", base_generation="base")
        old_id, new_id = "1" * 64, "2" * 64
        overlay.append(
            old_id, source_commit="c1", source_sha256="3" * 64, artifact_digest="4" * 64
        )
        replacement = overlay.rename(
            old_id,
            new_id,
            source_commit="c2",
            source_sha256="5" * 64,
            artifact_digest="6" * 64,
        )
        current = overlay.as_of(2)
        self.assertEqual([new_id], [fact.canonical_id for fact in current])
        history = overlay.as_of(2, include_tombstones=True)
        self.assertEqual({old_id, new_id}, {fact.canonical_id for fact in history})
        self.assertEqual(
            "renamed",
            next(fact for fact in history if fact.canonical_id == old_id).reason_code,
        )
        self.assertEqual("valid", overlay.receipt()["verification"]["status"])
        self.assertIsNotNone(replacement.digest)

    def test_generation_and_order_guards_fail_closed(self) -> None:
        overlay = BitemporalOverlay(
            "repo", base_generation="base", overlay_generation="slot"
        )
        overlay.append(
            "a" * 64,
            source_commit="c",
            source_sha256="b" * 64,
            artifact_digest="c" * 64,
        )
        with self.assertRaises(TemporalInvariantError) as error:
            overlay.as_of(1, generation="other")
        self.assertEqual("stale_generation", error.exception.reason_code)
        with self.assertRaises(TemporalInvariantError) as error:
            overlay.append(
                "a" * 64,
                source_commit="c",
                source_sha256="b" * 64,
                artifact_digest="c" * 64,
                valid_from=1,
            )
        self.assertEqual("world_time_out_of_order", error.exception.reason_code)

    def test_binary_persistence_round_trip_checksum_and_scope_guards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlay = BitemporalOverlay(
                "repo", base_generation="base", overlay_generation="slot"
            )
            entity = "a" * 64
            overlay.append(
                entity,
                source_commit="c1",
                source_sha256="b" * 64,
                artifact_digest="c" * 64,
                dependencies=("d" * 64,),
            )
            overlay.append(
                entity,
                source_commit="c2",
                source_sha256="e" * 64,
                artifact_digest="f" * 64,
            )
            path = root / "overlay.sft"
            receipt = overlay.save(path)
            loaded = BitemporalOverlay.load(
                path,
                repository="repo",
                base_generation="base",
                overlay_generation="slot",
            )
            self.assertEqual("valid", receipt["status"])
            self.assertEqual(overlay.receipt(), loaded.receipt())
            self.assertEqual(overlay.to_bytes(), loaded.to_bytes())
            corrupted = bytearray(path.read_bytes())
            corrupted[-1] ^= 1
            with self.assertRaises(TemporalInvariantError) as error:
                BitemporalOverlay.from_bytes(bytes(corrupted))
            self.assertEqual("persistence_checksum", error.exception.reason_code)
            with self.assertRaises(TemporalInvariantError) as error:
                BitemporalOverlay.load(path, repository="other")
            self.assertEqual("persistence_scope", error.exception.reason_code)

    def test_persistence_rejects_invalid_envelopes_and_records(self) -> None:
        overlay = BitemporalOverlay(
            "repo", base_generation="base", overlay_generation="slot"
        )
        overlay.append(
            "a" * 64,
            source_commit="c",
            source_sha256="b" * 64,
            artifact_digest="c" * 64,
        )
        data = overlay.to_bytes()
        with self.assertRaises(TemporalInvariantError) as error:
            BitemporalOverlay.from_bytes(b"bad")
        self.assertEqual("persistence_format", error.exception.reason_code)
        with self.assertRaises(TemporalInvariantError) as error:
            BitemporalOverlay.from_bytes(data[:-1])
        self.assertEqual("persistence_truncated", error.exception.reason_code)
        with self.assertRaises(TemporalInvariantError) as error:
            BitemporalOverlay.from_bytes(data, base_generation="wrong")
        self.assertEqual("persistence_scope", error.exception.reason_code)
        with self.assertRaises(TemporalInvariantError) as error:
            BitemporalOverlay.from_bytes(data, overlay_generation="wrong")
        self.assertEqual("persistence_scope", error.exception.reason_code)

        def envelope(value: object) -> bytes:
            payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            return (
                PERSISTENCE_MAGIC
                + struct.pack(">I", len(payload))
                + hashlib.sha256(payload).digest()
                + payload
            )

        value = json.loads(
            data[len(PERSISTENCE_MAGIC) + 4 + hashlib.sha256().digest_size :]
        )
        wrong_schema = dict(value)
        wrong_schema["schema"] = "wrong"
        with self.assertRaises(TemporalInvariantError) as error:
            BitemporalOverlay.from_bytes(envelope(wrong_schema))
        self.assertEqual("persistence_schema", error.exception.reason_code)
        bad_facts = dict(value)
        bad_facts["facts"] = "bad"
        with self.assertRaises(TemporalInvariantError) as error:
            BitemporalOverlay.from_bytes(envelope(bad_facts))
        self.assertEqual("persistence_facts", error.exception.reason_code)
        bad_sequence = dict(value)
        bad_sequence["world_sequence"] = "bad"
        with self.assertRaises(TemporalInvariantError) as error:
            BitemporalOverlay.from_bytes(envelope(bad_sequence))
        self.assertEqual("persistence_sequence", error.exception.reason_code)
        inconsistent_world = dict(
            value, world_sequence=int(value["world_sequence"]) + 1
        )
        with self.assertRaises(TemporalInvariantError) as error:
            BitemporalOverlay.from_bytes(envelope(inconsistent_world))
        self.assertEqual("persistence_sequence", error.exception.reason_code)
        inconsistent_observed = dict(
            value, observed_sequence=int(value["observed_sequence"]) + 1
        )
        with self.assertRaises(TemporalInvariantError) as error:
            BitemporalOverlay.from_bytes(envelope(inconsistent_observed))
        self.assertEqual("persistence_sequence", error.exception.reason_code)
        bad_digest = dict(value)
        bad_digest["facts"] = [dict(value["facts"][0], digest="0" * 64)]
        with self.assertRaises(TemporalInvariantError) as error:
            BitemporalOverlay.from_bytes(envelope(bad_digest))
        self.assertEqual("persistence_digest", error.exception.reason_code)
