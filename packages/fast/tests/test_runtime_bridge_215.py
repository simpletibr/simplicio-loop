from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys

import pytest

from simplicio_fast.runtime_backend import (
    HBP_SCHEMA,
    RUNTIME_FAST_ABI,
    platform_tag,
)
from simplicio_fast.runtime_bridge import (
    RuntimeBridgeError,
    discover_native_binary,
    execute_via_bridge,
)


def _manifest(path: Path, *, abi: str | None = RUNTIME_FAST_ABI) -> dict:
    value = {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "version": "3.6.0",
        "platform": platform_tag(),
    }
    if abi is not None:
        value["abi"] = abi
    return value


def _environment(tmp_path: Path, executable: Path, manifest: dict) -> dict[str, str]:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return {
        "SIMPLICIO_RUNTIME_BIN": str(executable),
        "SIMPLICIO_RUNTIME_MANIFEST": str(manifest_path),
    }


def _forged_echo(tmp_path: Path) -> Path:
    """Non-runtime binary that exists on every platform (not /bin/echo)."""
    path = tmp_path / "echo-forged"
    path.write_bytes(b"#!/bin/sh\necho not-a-runtime\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _runtime(tmp_path: Path) -> Path:
    script = tmp_path / "simplicio_runtime_impl.py"
    script.write_text(
        f"""#!/usr/bin/env python3
import hashlib
import json
import sys
request = json.load(sys.stdin)
operation = request["operation"]
if operation == "doctor":
    result = {{
        "runtime": "simplicio-runtime",
        "version": "3.6.0",
        "platform": {platform_tag()!r},
        "abi": {RUNTIME_FAST_ABI!r},
        "healthy": True,
        "capabilities": ["sha256"],
        "conformance": {{"passed": True, "digest": "a" * 64}},
    }}
elif operation == "sha256":
    result = hashlib.sha256(bytes.fromhex(request["payload"]["hex"])).hexdigest()
else:
    raise SystemExit(2)
print(json.dumps({{
    "schema": {HBP_SCHEMA!r},
    "abi": {RUNTIME_FAST_ABI!r},
    "request_id": request["request_id"],
    "ok": True,
    "result": result,
}}))
""",
        encoding="utf-8",
    )
    if os.name == "nt":
        wrapper = tmp_path / "simplicio.cmd"
        wrapper.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
        return wrapper
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_discovery_without_manifest_never_spawns_echo(monkeypatch):
    spawned = False

    def forbidden(*args, **kwargs):
        nonlocal spawned
        spawned = True
        raise AssertionError("unmanifested executable was spawned")

    monkeypatch.setattr("simplicio_fast.runtime_backend.subprocess.Popen", forbidden)
    result = discover_native_binary(environment={"SIMPLICIO_RUNTIME_BIN": "/bin/echo"})
    assert result["cargo_used"] is False
    assert result["status"] == "rejected"
    assert result["reason_code"] == "RUNTIME_MISSING"
    assert spawned is False


def test_manifest_without_explicit_abi_is_rejected_before_spawn(tmp_path, monkeypatch):
    spawned = False

    def forbidden(*args, **kwargs):
        nonlocal spawned
        spawned = True
        raise AssertionError("ABI-less artifact was spawned")

    monkeypatch.setattr("simplicio_fast.runtime_backend.subprocess.Popen", forbidden)
    echo = _forged_echo(tmp_path)
    environment = _environment(tmp_path, echo, _manifest(echo, abi=None))
    result = discover_native_binary(environment=environment)
    assert result["status"] == "rejected"
    assert result["reason_code"] == "ABI_MISMATCH"
    assert spawned is False


def test_echo_with_forged_complete_manifest_fails_handshake(tmp_path):
    echo = _forged_echo(tmp_path)
    environment = _environment(tmp_path, echo, _manifest(echo))
    result = discover_native_binary(environment=environment)
    assert result["status"] == "rejected"
    assert result["reason_code"] in {"PROTOCOL_ERROR", "RUNTIME_UNHEALTHY"}
    with pytest.raises(RuntimeBridgeError) as raised:
        execute_via_bridge(
            {"op": "sha256", "payload": {"hex": "00"}},
            environment=environment,
        )
    assert raised.value.reason_code in {"PROTOCOL_ERROR", "RUNTIME_UNHEALTHY"}


def test_verified_runtime_is_the_only_execution_path(tmp_path):
    runtime = _runtime(tmp_path)
    environment = _environment(tmp_path, runtime, _manifest(runtime))
    discovery = discover_native_binary(environment=environment)
    # Discovery requests the full canonical capability set.  This fixture only
    # exposes sha256, so the strict discovery surface rejects it.
    assert discovery["status"] == "rejected"
    assert discovery["reason_code"] == "RUNTIME_UNHEALTHY"

    out = execute_via_bridge(
        {"op": "sha256", "payload": {"hex": b"verified".hex()}},
        environment=environment,
    )
    assert out["status"] == "verified"
    assert out["backend"] == "rust"
    assert out["handshake"]["abi"] == RUNTIME_FAST_ABI
    assert out["handshake"]["runtime_version"] == "3.6.0"
    assert out["result"] == hashlib.sha256(b"verified").hexdigest()


def test_bridge_has_no_echo_or_python_fallback():
    with pytest.raises(RuntimeBridgeError) as raised:
        execute_via_bridge({"op": "sha256", "payload": {}}, environment={})
    assert raised.value.reason_code == "RUNTIME_MISSING"
    with pytest.raises(RuntimeBridgeError) as raised:
        execute_via_bridge({"op": "capabilities"}, environment={})
    assert raised.value.reason_code == "PROTOCOL_ERROR"
