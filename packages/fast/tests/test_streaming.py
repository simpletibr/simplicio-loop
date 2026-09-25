from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from simplicio_fast.streaming import StreamingBlockStore, StreamingStoreError
from unittest.mock import patch

import simplicio_fast.streaming as streaming_module


class StreamingBlockStoreTest(unittest.TestCase):
    def test_blocked_round_trip_publishes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            payload = b"abcdefghij" * 100
            store = StreamingBlockStore(root)
            receipt = store.build(
                (payload[index : index + 13] for index in range(0, len(payload), 13)),
                generation="g1",
                block_bytes=64,
            )
            self.assertEqual("published", receipt["status"])
            self.assertEqual(
                hashlib.sha256(payload).hexdigest(), receipt["source_sha256"]
            )
            self.assertEqual(payload, store.read_all("g1"))

    def test_atomic_manifest_replace_retries_transient_windows_lock(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = StreamingBlockStore(root)
            original_replace = streaming_module.os.replace
            calls = 0

            def flaky_replace(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError(5, "access denied")
                original_replace(source, destination)

            with patch.object(
                streaming_module.os, "replace", side_effect=flaky_replace
            ):
                receipt = store.build((b"payload",), generation="retry", block_bytes=4)
            self.assertEqual("published", receipt["status"])
            self.assertGreaterEqual(calls, 2)
            self.assertEqual(b"payload", store.read_all("retry"))

    def test_build_file_streams_source_and_reports_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "source.bin")
            payload = bytes(range(251)) * 17
            source.write_bytes(payload)
            store = StreamingBlockStore(Path(root, "store"))
            receipt = store.build_file(source, generation="g-file", block_bytes=64)
            self.assertEqual(len(payload), receipt["input_bytes"])
            self.assertEqual(payload, store.read_all("g-file"))
            with self.assertRaises(StreamingStoreError) as error:
                store.build_file(Path(root, "missing.bin"), generation="missing")
            self.assertEqual("source_unavailable", error.exception.reason_code)

    def test_resume_uses_valid_checkpoint_and_rejects_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = StreamingBlockStore(root)
            with self.assertRaisesRegex(RuntimeError, "injected_stream_failure"):
                store.build(
                    (b"a" * 32, b"b" * 32, b"c" * 4),
                    generation="g1",
                    block_bytes=32,
                    fail_after_blocks=1,
                )
            with self.assertRaises(StreamingStoreError) as error:
                store.build(
                    (b"x" * 32, b"b" * 32, b"c" * 4),
                    generation="g1",
                    block_bytes=32,
                    resume=True,
                )
            self.assertEqual("resume_source_mismatch", error.exception.reason_code)
            receipt = store.build(
                (b"a" * 32, b"b" * 32, b"c" * 4),
                generation="g1",
                block_bytes=32,
                resume=True,
            )
            self.assertEqual("published", receipt["status"])
            self.assertEqual(b"a" * 32 + b"b" * 32 + b"c" * 4, store.read_all("g1"))

    def test_read_range_is_bounded_and_validates_touched_block(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            payload = bytes(range(64)) * 4
            store = StreamingBlockStore(root)
            store.build((payload,), generation="g1", block_bytes=32)
            self.assertEqual(payload[11:75], store.read_range("g1", 11, 64))
            self.assertEqual(b"", store.read_range("g1", 0, 0))
            with self.assertRaises(StreamingStoreError) as error:
                store.read_range("g1", -1, 1)
            self.assertEqual("invalid_range", error.exception.reason_code)
            segment = Path(root, "g1", "segment-000000.bin")
            data = bytearray(segment.read_bytes())
            data[12] ^= 1
            segment.write_bytes(data)
            with self.assertRaises(StreamingStoreError) as error:
                store.read_range("g1", 0, 16)
            self.assertEqual("block_digest", error.exception.reason_code)
