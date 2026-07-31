"""Small filesystem helpers shared across modules."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

_WINDOWS_REPLACE_RETRY_DELAYS = (0.01, 0.02, 0.04)


def _is_transient_windows_replace_error(exc: PermissionError) -> bool:
    """Return whether an AV/indexer lock can safely be retried on Windows."""
    if os.name != "nt":
        return False
    return exc.winerror in {5, 32} or exc.errno in {5, 13, 32}


def write_bytes_atomic(path: str | Path, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        for delay in (*_WINDOWS_REPLACE_RETRY_DELAYS, None):
            try:
                os.replace(tmp_name, target)
                break
            except PermissionError as exc:
                if delay is None or not _is_transient_windows_replace_error(exc):
                    raise
                time.sleep(delay)
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
    return target


def write_text_atomic(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    return write_bytes_atomic(path, text.encode(encoding))
