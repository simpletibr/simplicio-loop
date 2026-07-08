"""Small filesystem helpers shared across modules."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_bytes_atomic(path: str | Path, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, target)
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
    return target


def write_text_atomic(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    return write_bytes_atomic(path, text.encode(encoding))
