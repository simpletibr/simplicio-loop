from __future__ import annotations

from simplicio.utils import fs


def test_write_bytes_atomic_retries_transient_windows_replace_lock(tmp_path, monkeypatch):
    target = tmp_path / "receipt.json"
    real_replace = fs.os.replace
    attempts = 0

    def delayed_replace(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(5, "access denied")
        return real_replace(source, destination)

    monkeypatch.setattr(fs.os, "replace", delayed_replace)
    monkeypatch.setattr(fs.time, "sleep", lambda _delay: None)

    assert fs.write_bytes_atomic(target, b"ok") == target
    assert target.read_bytes() == b"ok"
    assert attempts == 2


def test_write_bytes_atomic_does_not_retry_non_windows_permission_error(tmp_path, monkeypatch):
    target = tmp_path / "receipt.json"
    attempts = 0

    def denied_replace(source, destination):
        nonlocal attempts
        attempts += 1
        raise PermissionError(5, "access denied")

    monkeypatch.setattr(fs.os, "replace", denied_replace)
    monkeypatch.setattr(fs, "_is_transient_windows_replace_error", lambda _exc: False)

    try:
        fs.write_bytes_atomic(target, b"ok")
    except PermissionError:
        pass
    else:
        raise AssertionError("expected non-Windows permission error")
    assert attempts == 1
