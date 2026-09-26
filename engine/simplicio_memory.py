#!/usr/bin/env python3
"""simplicio_memory — native compress-cache-retrieve (CCR) key-value memory store.

Stdlib-only. Stores at ``$SIMPLICIO_HOME/memory.json`` (default ``~/.simplicio-loop``),
matching the rest of the engine. CCR semantics: every ``remember`` keeps a
deterministically-compressed (zlib+base64) form of the value, so ``recall``
returns the byte-exact original (lossless round-trip) while the store tracks how
many bytes compression saved. Atomic writes, thread-safe, fail-open.
"""

import base64
import json
import os
import sys
import threading
import tempfile
import zlib
from pathlib import Path

HOME = os.path.expanduser("~")
DATA_DIR = Path(os.environ.get("SIMPLICIO_HOME", Path(HOME) / ".simplicio-loop"))
STORE_PATH = DATA_DIR / "memory.json"

_LOCK = threading.RLock()


def _load() -> dict:
    """Read the store. Fail-open: any corruption/error starts fresh."""
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _atomic_write(data: dict) -> None:
    """Write the store atomically (tempfile + os.replace) in the store dir."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), prefix=".memory.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STORE_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _compress(value: str) -> tuple:
    """Deterministically compress ``value`` -> (b64 zlib blob, raw bytes len, compressed bytes len)."""
    raw = value.encode("utf-8")
    blob = zlib.compress(raw, 9)
    b64 = base64.b64encode(blob).decode("ascii")
    return b64, len(raw), len(blob)


def _decompress(b64: str) -> str:
    """Inverse of ``_compress``: b64 zlib blob -> exact original string."""
    return zlib.decompress(base64.b64decode(b64.encode("ascii"))).decode("utf-8")


def remember(key, value):
    """Store ``value`` under ``key`` with a compressed form. Returns the entry dict."""
    key = str(key)
    value = str(value)
    b64, raw_len, comp_len = _compress(value)
    entry = {
        "compressed": b64,
        "raw_bytes": raw_len,
        "compressed_bytes": comp_len,
        "bytes_saved": max(0, raw_len - comp_len),
    }
    with _LOCK:
        data = _load()
        data[key] = entry
        _atomic_write(data)
    return entry


def recall(key):
    """Return the byte-exact original value for ``key``, or ``None`` if absent/unreadable."""
    key = str(key)
    with _LOCK:
        data = _load()
        entry = data.get(key)
    if not isinstance(entry, dict) or "compressed" not in entry:
        return None
    try:
        return _decompress(entry["compressed"])
    except (ValueError, zlib.error, UnicodeDecodeError):
        return None


def forget(key):
    """Delete ``key``. Returns True if it existed, False otherwise."""
    key = str(key)
    with _LOCK:
        data = _load()
        if key in data:
            del data[key]
            _atomic_write(data)
            return True
    return False


def stats():
    """Return {entries, bytes_saved, raw_bytes, compressed_bytes}."""
    with _LOCK:
        data = _load()
    bytes_saved = 0
    raw_bytes = 0
    compressed_bytes = 0
    for entry in data.values():
        if isinstance(entry, dict):
            bytes_saved += int(entry.get("bytes_saved", 0))
            raw_bytes += int(entry.get("raw_bytes", 0))
            compressed_bytes += int(entry.get("compressed_bytes", 0))
    return {
        "entries": len(data),
        "bytes_saved": bytes_saved,
        "raw_bytes": raw_bytes,
        "compressed_bytes": compressed_bytes,
    }


def list_keys():
    """Return a sorted list of stored keys."""
    with _LOCK:
        data = _load()
    return sorted(data.keys())


def _usage():
    print(
        "usage:\n"
        "  simplicio_memory.py remember <key> <value>\n"
        "  simplicio_memory.py recall <key>\n"
        "  simplicio_memory.py forget <key>\n"
        "  simplicio_memory.py stats\n"
        "  simplicio_memory.py list",
        file=sys.stderr,
    )


def main(argv):
    if not argv:
        _usage()
        return 2
    cmd = argv[0]
    if cmd == "remember":
        if len(argv) < 3:
            _usage()
            return 2
        key = argv[1]
        value = " ".join(argv[2:])
        remember(key, value)
        print(f"remembered {key} ({len(value.encode('utf-8'))} bytes)")
        return 0
    if cmd == "recall":
        if len(argv) != 2:
            _usage()
            return 2
        val = recall(argv[1])
        if val is None:
            return 1
        sys.stdout.write(val)
        if not val.endswith("\n"):
            sys.stdout.write("\n")
        return 0
    if cmd == "forget":
        if len(argv) != 2:
            _usage()
            return 2
        ok = forget(argv[1])
        print("forgotten" if ok else "not found")
        return 0 if ok else 1
    if cmd == "stats":
        s = stats()
        print(
            f"entries: {s['entries']}\n"
            f"bytes_saved: {s['bytes_saved']}\n"
            f"raw_bytes: {s['raw_bytes']}\n"
            f"compressed_bytes: {s['compressed_bytes']}"
        )
        return 0
    if cmd == "list":
        for k in list_keys():
            print(k)
        return 0
    _usage()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
