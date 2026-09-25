from __future__ import annotations

import io
import json
import sys
import unittest

from simplicio_mapper.cli._status_engine import _print_json_utf8


class _Cp1252Stdout:
    """Mimic a Windows console that cannot encode arrows."""

    encoding = "cp1252"

    def __init__(self) -> None:
        self.buffer = io.BytesIO()
        self.writes: list[str] = []

    def write(self, text: str) -> int:
        text.encode(self.encoding)
        self.writes.append(text)
        return len(text)

    def flush(self) -> None:
        return None


class HandoffUtf8StdoutTest(unittest.TestCase):
    def test_cp1252_print_raises_on_arrow(self) -> None:
        payload = {"arrow": "→", "path": "src/a → b.py"}
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.assertRaises(UnicodeEncodeError):
            text.encode("cp1252")

    def test_print_json_utf8_writes_arrow_via_buffer(self) -> None:
        payload = {"arrow": "→", "path": "src/a → b.py"}
        fake = _Cp1252Stdout()
        previous = sys.stdout
        try:
            sys.stdout = fake  # type: ignore[assignment]
            _print_json_utf8(payload)
        finally:
            sys.stdout = previous
        raw = fake.buffer.getvalue()
        self.assertTrue(raw.endswith(b"\n"))
        decoded = json.loads(raw.decode("utf-8"))
        self.assertEqual(decoded["arrow"], "→")
        self.assertEqual(decoded["path"], "src/a → b.py")
        self.assertEqual(fake.writes, [])

    def test_print_json_utf8_falls_back_without_buffer(self) -> None:
        payload = {"ok": True}
        sink = io.StringIO()
        previous = sys.stdout
        try:
            sys.stdout = sink
            _print_json_utf8(payload)
        finally:
            sys.stdout = previous
        self.assertEqual(json.loads(sink.getvalue()), payload)


if __name__ == "__main__":
    unittest.main()
