import json
import struct
import unittest

from simplicio_fast.ipc import (
    HEADER,
    IpcFrame,
    IpcFrameDecoder,
    IpcFrameError,
    MAGIC,
    MAX_FRAME_BYTES,
    MAX_HEADER_BYTES,
    MAX_PAYLOAD_BYTES,
    SCHEMA,
    decode_frame,
)


class BoundedIpcFrameTest(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = IpcFrame("req-1", "query", "SFAST001:generation", b"small payload")

    def test_round_trip_is_deterministic_and_preserves_payload(self) -> None:
        encoded = self.frame.encode()
        self.assertEqual(encoded, self.frame.encode())
        self.assertEqual(self.frame, decode_frame(encoded))

    def test_decoder_handles_fragmented_and_consecutive_frames(self) -> None:
        second = IpcFrame("req-2", "context", "g", b"second")
        decoder = IpcFrameDecoder()
        self.assertEqual((), decoder.feed(self.frame.encode()[:3]))
        decoded = decoder.feed(self.frame.encode()[3:] + second.encode())
        self.assertEqual((self.frame, second), decoded)
        self.assertEqual(0, decoder.buffered_bytes)
        decoder.finish()

    def test_decoder_fails_closed_on_bounds_and_truncated_finish(self) -> None:
        with self.assertRaises(IpcFrameError) as error:
            IpcFrameDecoder(max_frame_bytes=HEADER.size + 1).feed(self.frame.encode())
        self.assertEqual("frame_too_large", error.exception.reason_code)
        decoder = IpcFrameDecoder()
        decoder.feed(self.frame.encode()[:-1])
        with self.assertRaises(IpcFrameError) as error:
            decoder.finish()
        self.assertEqual("truncated_frame", error.exception.reason_code)

    def test_limits_reject_payload_header_and_total_frame(self) -> None:
        with self.assertRaises(IpcFrameError) as error:
            IpcFrame("r", "q", "g", b"1234").encode(max_payload_bytes=3)
        self.assertEqual("payload_too_large", error.exception.reason_code)
        with self.assertRaises(IpcFrameError) as error:
            self.frame.encode(max_frame_bytes=HEADER.size + 1)
        self.assertEqual("frame_too_large", error.exception.reason_code)
        with self.assertRaises(ValueError):
            self.frame.encode(max_header_bytes=0)
        self.assertEqual(
            MAX_FRAME_BYTES, HEADER.size + MAX_HEADER_BYTES + MAX_PAYLOAD_BYTES
        )

    def test_decode_rejects_bad_magic_truncation_and_trailing_bytes(self) -> None:
        encoded = self.frame.encode()
        with self.assertRaises(IpcFrameError) as error:
            decode_frame(b"BADMAGIC" + encoded[8:])
        self.assertEqual("invalid_magic", error.exception.reason_code)
        with self.assertRaises(IpcFrameError) as error:
            decode_frame(encoded[:-1])
        self.assertEqual("truncated_frame", error.exception.reason_code)
        with self.assertRaises(IpcFrameError) as error:
            decode_frame(encoded + b"x")
        self.assertEqual("trailing_bytes", error.exception.reason_code)

    def test_decode_rejects_schema_metadata_and_digest_tampering(self) -> None:
        encoded = self.frame.encode()
        _, header_length, payload_length = HEADER.unpack_from(encoded)
        header_start = HEADER.size
        header = json.loads(encoded[header_start : header_start + header_length])
        header["schema"] = "simplicio.fast.ipc/v2"
        changed = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
        tampered_schema = (
            struct.pack(">8sII", MAGIC, len(changed), payload_length)
            + changed
            + encoded[header_start + header_length :]
        )
        with self.assertRaises(IpcFrameError) as error:
            decode_frame(tampered_schema)
        self.assertEqual("unsupported_schema", error.exception.reason_code)
        with self.assertRaises(IpcFrameError) as error:
            invalid_header = b"{" + b" " * (header_length - 1)
            decode_frame(
                encoded[:header_start]
                + invalid_header
                + encoded[header_start + header_length :]
            )
        self.assertEqual("invalid_header", error.exception.reason_code)
        payload_start = header_start + header_length
        tampered_payload = (
            encoded[:payload_start]
            + bytes([encoded[payload_start] ^ 1])
            + encoded[payload_start + 1 :]
        )
        with self.assertRaises(IpcFrameError) as error:
            decode_frame(tampered_payload)
        self.assertEqual("payload_digest_mismatch", error.exception.reason_code)

    def test_metadata_and_frame_type_fail_closed(self) -> None:
        with self.assertRaises(IpcFrameError) as error:
            IpcFrame("", "query", "g", b"")
        self.assertEqual("invalid_metadata", error.exception.reason_code)
        with self.assertRaises(IpcFrameError) as error:
            decode_frame("not-bytes")
        self.assertEqual("invalid_frame", error.exception.reason_code)
        self.assertEqual(
            SCHEMA,
            json.loads(
                self.frame.encode()[
                    HEADER.size : HEADER.size
                    + HEADER.unpack_from(self.frame.encode())[1]
                ]
            )["schema"],
        )


if __name__ == "__main__":
    unittest.main()
