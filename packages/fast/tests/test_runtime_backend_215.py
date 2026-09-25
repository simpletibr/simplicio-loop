from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time

import pytest

from simplicio_fast.runtime_backend import (
    HBP_SCHEMA,
    READ_ONLY_OPERATIONS,
    REASON_CODES,
    RUNTIME_FAST_ABI,
    RuntimeArtifact,
    RuntimeBackendError,
    RuntimeFastBackend,
    platform_tag,
    select_runtime_backend,
)


def _fake_runtime(
    root: Path,
    *,
    version: str = "3.6.0",
    response_abi: str = RUNTIME_FAST_ABI,
    response_platform: str | None = None,
    healthy: bool = True,
    conformance: bool = True,
    bad_json: bool = False,
    crash_operation: str | None = None,
    sleep_operation: str | None = None,
    capabilities: tuple[str, ...] | None = None,
    doctor_kind: str = "normal",
    response_kind: str = "normal",
) -> RuntimeArtifact:
    host = response_platform or platform_tag() or "unsupported"
    source = f"""#!/usr/bin/env python3
import hashlib
import json
import sys
import time
request = json.load(sys.stdin)
operation = request["operation"]
if operation == {crash_operation!r}:
    raise SystemExit(7)
if operation == {sleep_operation!r}:
    time.sleep(5)
if {bad_json!r}:
    print("not-json")
    raise SystemExit(0)
if operation == "doctor" and {doctor_kind!r} == "scalar":
    result = "invalid"
elif operation == "doctor":
    result = {{
        "runtime": "simplicio-runtime",
        "version": {version!r},
        "platform": "other-platform" if {doctor_kind!r} == "platform" else {host!r},
        "abi": {response_abi!r},
        "healthy": {healthy!r},
        "capabilities": "invalid" if {doctor_kind!r} == "capabilities" else {sorted(capabilities or READ_ONLY_OPERATIONS)!r},
        "conformance": {{"passed": {conformance!r}, "digest": "a" * 64}},
    }}
elif operation == "sha256":
    result = hashlib.sha256(bytes.fromhex(request["payload"]["hex"])).hexdigest()
elif operation == "page":
    data = bytes.fromhex(request["payload"]["hex"])
    start = int(request["payload"]["offset"])
    result = data[start:start + int(request["payload"]["limit"])].hex()
elif operation == "catalog_lookup":
    result = request["payload"]["catalog"].get(request["payload"]["key"])
elif operation == "overlay_merge":
    result = dict(request["payload"]["base"])
    for key, value in sorted(request["payload"]["overlay"].items()):
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
else:
    result = {{"operation": operation}}
response = {{
    "schema": {HBP_SCHEMA!r},
    "abi": {RUNTIME_FAST_ABI!r},
    "request_id": request["request_id"],
    "ok": True,
    "result": result,
}}
if {response_kind!r} == "list":
    response = []
elif {response_kind!r} == "envelope":
    response["schema"] = "wrong"
elif {response_kind!r} == "reject":
    response = {{
        "schema": {HBP_SCHEMA!r}, "abi": {RUNTIME_FAST_ABI!r},
        "request_id": request["request_id"], "ok": False,
        "reason_code": "TIMEOUT", "detail": "fixture rejection",
    }}
elif {response_kind!r} == "missing":
    response.pop("result")
elif {response_kind!r} == "large":
    response["result"] = "x" * 5000
print(json.dumps(response, sort_keys=True))
"""
    script = root / "simplicio_runtime_impl.py"
    script.write_text(source, encoding="utf-8")
    if os.name == "nt":
        path = root / "simplicio.cmd"
        path.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
    else:
        path = root / "simplicio"
        path.write_text(source, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return RuntimeArtifact(
        executable=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        version=version,
        platform=platform_tag() or "unsupported",
        source_commit="b" * 40,
    )


def test_modes_auto_rust_python_off_and_explicit_receipts(tmp_path):
    artifact = _fake_runtime(tmp_path)
    selected = select_runtime_backend("auto", artifact=artifact)
    assert selected.selected == "rust"
    receipt = selected.receipt()
    assert receipt["backend_artifact_hash"] == artifact.sha256
    assert receipt["abi"] == RUNTIME_FAST_ABI
    assert receipt["runtime_source_commit"] == "b" * 40
    assert receipt["python_hot_path_loaded"] is False
    assert select_runtime_backend("python").selected == "python"
    assert select_runtime_backend("off").selected == "off"
    assert select_runtime_backend("rust", artifact=artifact).selected == "rust"


def test_runtime_path_does_not_load_python_hot_path(tmp_path):
    artifact = _fake_runtime(tmp_path)
    script = """
import hashlib
from pathlib import Path
import sys
from simplicio_fast.runtime_backend import RuntimeArtifact, select_runtime_backend
artifact = RuntimeArtifact(
    executable=Path(sys.argv[1]), sha256=sys.argv[2], version=sys.argv[3],
    platform=sys.argv[4], source_commit="b" * 40,
)
assert "simplicio_fast.native_backend" not in sys.modules
selected = select_runtime_backend(
    "rust", artifact=artifact, required_capabilities=("sha256",)
)
assert selected.execute("sha256", {"hex": b"abc".hex()}) == hashlib.sha256(b"abc").hexdigest()
assert "simplicio_fast.native_backend" not in sys.modules
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(artifact.executable),
            artifact.sha256,
            artifact.version,
            artifact.platform,
        ],
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env={**dict(os.environ), "PYTHONPATH": "src"},
    )
    assert completed.returncode == 0, completed.stderr


def test_python_mode_is_complete_for_golden_hbp_operations():
    selected = select_runtime_backend("python")
    assert (
        selected.execute("sha256", {"hex": b"abc".hex()})
        == hashlib.sha256(b"abc").hexdigest()
    )
    assert (
        selected.execute("catalog_lookup", {"catalog": {"a": "1"}, "key": "a"}) == "1"
    )
    assert (
        selected.execute("page", {"hex": b"abcdef".hex(), "offset": 1, "limit": 3})
        == b"bcd".hex()
    )
    assert selected.execute(
        "overlay_merge",
        {"base": {"a": "31"}, "overlay": {"a": "32", "b": "33"}},
    ) == {"a": "32", "b": "33"}


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("sha256", {"hex": b"portable fixture".hex()}),
        (
            "catalog_lookup",
            {"catalog": {"alpha": "1", "beta": "2"}, "key": "beta"},
        ),
        ("page", {"hex": bytes(range(64)).hex(), "offset": 7, "limit": 19}),
        (
            "overlay_merge",
            {
                "base": {"a": "31", "b": "32"},
                "overlay": {"a": "33", "b": None},
            },
        ),
    ],
)
def test_python_and_runtime_use_the_same_hbp_golden_fixtures(
    tmp_path, operation, payload
):
    artifact = _fake_runtime(tmp_path)
    python = select_runtime_backend("python")
    runtime = select_runtime_backend(
        "rust", artifact=artifact, required_capabilities=(operation,)
    )
    assert runtime.execute(operation, payload) == python.execute(operation, payload)


@pytest.mark.parametrize(
    "mutator,reason",
    [
        (lambda artifact: {"sha256": "0" * 64}, "HASH_MISMATCH"),
        (lambda artifact: {"abi": "old"}, "ABI_MISMATCH"),
        (lambda artifact: {"platform": "plan9-mips"}, "PLATFORM_UNSUPPORTED"),
        (lambda artifact: {"version": ""}, "VERSION_MISMATCH"),
    ],
)
def test_artifact_is_verified_before_process_spawn(
    tmp_path, monkeypatch, mutator, reason
):
    artifact = _fake_runtime(tmp_path)
    values = {
        "executable": artifact.executable,
        "sha256": artifact.sha256,
        "version": artifact.version,
        "platform": artifact.platform,
        "abi": artifact.abi,
        "source_commit": artifact.source_commit,
    }
    values.update(mutator(artifact))
    invalid = RuntimeArtifact(**values)
    spawned = False

    def forbidden(*args, **kwargs):
        nonlocal spawned
        spawned = True
        raise AssertionError("unverified artifact spawned")

    monkeypatch.setattr("simplicio_fast.runtime_backend.subprocess.Popen", forbidden)
    with pytest.raises(RuntimeBackendError) as raised:
        select_runtime_backend("rust", artifact=invalid)
    assert raised.value.reason_code == reason
    assert spawned is False


def test_runtime_artifact_hashing_streams_and_enforces_size_bound(
    tmp_path, monkeypatch
):
    artifact = _fake_runtime(tmp_path)
    # Ensure the fixture exceeds the 1 KiB enforcement bound on every platform
    # (Windows .cmd wrappers are otherwise only a few hundred bytes).
    padded = artifact.executable
    padded.write_bytes(padded.read_bytes() + (b"#pad\n" * 400))
    sized = RuntimeArtifact(
        executable=padded,
        sha256=hashlib.sha256(padded.read_bytes()).hexdigest(),
        version=artifact.version,
        platform=artifact.platform,
        source_commit=artifact.source_commit,
        size=padded.stat().st_size,
    )
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("whole-file read is forbidden")
        ),
    )
    receipt = RuntimeFastBackend(sized).verify_artifact()
    assert receipt["artifact_size"] == sized.size
    with pytest.raises(RuntimeBackendError) as raised:
        RuntimeFastBackend(sized, max_artifact_bytes=1024).verify_artifact()
    assert raised.value.reason_code == "HASH_MISMATCH"


def test_signature_policy_fails_closed_and_accepts_verified_signature(tmp_path):
    unsigned = _fake_runtime(tmp_path)
    signed = RuntimeArtifact(
        executable=unsigned.executable,
        sha256=unsigned.sha256,
        version=unsigned.version,
        platform=unsigned.platform,
        signature="release-signature",
        signature_required=True,
    )
    with pytest.raises(RuntimeBackendError) as raised:
        RuntimeFastBackend(signed).verify_artifact()
    assert raised.value.reason_code == "SIGNATURE_MISMATCH"
    receipt = RuntimeFastBackend(
        signed,
        signature_verifier=lambda path, digest, signature: (
            digest == signed.sha256 and signature == "release-signature"
        ),
    ).verify_artifact()
    assert receipt["signature_verified"] is True


def test_required_signature_missing_and_missing_artifact_fail_closed(tmp_path):
    artifact = _fake_runtime(tmp_path)
    required = RuntimeArtifact(
        executable=artifact.executable,
        sha256=artifact.sha256,
        version=artifact.version,
        platform=artifact.platform,
        signature_required=True,
    )
    with pytest.raises(RuntimeBackendError) as signature:
        RuntimeFastBackend(required).verify_artifact()
    assert signature.value.reason_code == "SIGNATURE_MISMATCH"
    missing = RuntimeArtifact(
        executable=tmp_path / "missing",
        sha256="0" * 64,
        version="3.6.0",
        platform=platform_tag() or "unsupported",
    )
    with pytest.raises(RuntimeBackendError) as absent:
        RuntimeFastBackend(missing).verify_artifact()
    assert absent.value.reason_code == "RUNTIME_MISSING"


def test_manifest_and_environment_discovery(tmp_path):
    artifact = _fake_runtime(tmp_path)
    manifest = {
        "sha256": artifact.sha256,
        "abi": RUNTIME_FAST_ABI,
        "runtime": {
            "version": artifact.version,
            "target": artifact.platform,
            "commit": "c" * 40,
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    selected = select_runtime_backend(
        "auto",
        artifact=RuntimeArtifact.from_manifest(artifact.executable, manifest),
        required_capabilities=("sha256",),
    )
    assert selected.selected == "rust"
    assert selected.receipt()["runtime_source_commit"] == "c" * 40
    from simplicio_fast.runtime_backend import runtime_artifact_from_environment

    discovered = runtime_artifact_from_environment(
        {
            "SIMPLICIO_RUNTIME_BIN": str(artifact.executable),
            "SIMPLICIO_RUNTIME_MANIFEST": str(manifest_path),
        }
    )
    assert discovered is not None and discovered.sha256 == artifact.sha256
    assert runtime_artifact_from_environment({}) is None
    manifest_path.write_text("not-json", encoding="utf-8")
    assert (
        runtime_artifact_from_environment(
            {
                "SIMPLICIO_RUNTIME_BIN": str(artifact.executable),
                "SIMPLICIO_RUNTIME_MANIFEST": str(manifest_path),
            }
        )
        is None
    )
    manifest_path.write_text("[]", encoding="utf-8")
    assert (
        runtime_artifact_from_environment(
            {
                "SIMPLICIO_RUNTIME_BIN": str(artifact.executable),
                "SIMPLICIO_RUNTIME_MANIFEST": str(manifest_path),
            }
        )
        is None
    )


def test_constructor_and_unknown_reason_validation(tmp_path):
    artifact = _fake_runtime(tmp_path)
    with pytest.raises(ValueError):
        RuntimeFastBackend(artifact, timeout_seconds=0)
    with pytest.raises(ValueError):
        RuntimeFastBackend(artifact, max_response_bytes=100)
    assert RuntimeBackendError("UNKNOWN").reason_code == "PROTOCOL_ERROR"
    with pytest.raises(ValueError):
        select_runtime_backend("turbo")


@pytest.mark.parametrize(
    "artifact_factory,reason",
    [
        (lambda root: _fake_runtime(root, response_abi="old"), "ABI_MISMATCH"),
        (
            lambda root: RuntimeArtifact(
                **{
                    **{
                        field: getattr(_fake_runtime(root, version="3.7.0"), field)
                        for field in (
                            "executable",
                            "sha256",
                            "platform",
                            "abi",
                            "source_commit",
                        )
                    },
                    "version": "3.6.0",
                }
            ),
            "VERSION_MISMATCH",
        ),
        (lambda root: _fake_runtime(root, healthy=False), "RUNTIME_UNHEALTHY"),
        (lambda root: _fake_runtime(root, conformance=False), "RUNTIME_UNHEALTHY"),
        (lambda root: _fake_runtime(root, bad_json=True), "PROTOCOL_ERROR"),
    ],
)
def test_handshake_reason_codes_are_stable(tmp_path, artifact_factory, reason):
    artifact = artifact_factory(tmp_path)
    with pytest.raises(RuntimeBackendError) as raised:
        select_runtime_backend("rust", artifact=artifact)
    assert raised.value.reason_code == reason


@pytest.mark.parametrize(
    "artifact_factory,reason",
    [
        (lambda root: _fake_runtime(root, doctor_kind="scalar"), "PROTOCOL_ERROR"),
        (
            lambda root: _fake_runtime(root, doctor_kind="platform"),
            "PLATFORM_UNSUPPORTED",
        ),
        (
            lambda root: _fake_runtime(root, doctor_kind="capabilities"),
            "PROTOCOL_ERROR",
        ),
        (
            lambda root: _fake_runtime(root, capabilities=("sha256",)),
            "RUNTIME_UNHEALTHY",
        ),
    ],
)
def test_doctor_rejects_malformed_or_incomplete_contract(
    tmp_path, artifact_factory, reason
):
    with pytest.raises(RuntimeBackendError) as raised:
        select_runtime_backend("rust", artifact=artifact_factory(tmp_path))
    assert raised.value.reason_code == reason


def test_auto_fallback_is_explicit_but_rust_mode_fails_closed(tmp_path):
    artifact = _fake_runtime(tmp_path, healthy=False)
    automatic = select_runtime_backend("auto", artifact=artifact)
    assert automatic.selected == "python"
    assert automatic.receipt()["reason_code"] == "RUNTIME_UNHEALTHY"
    with pytest.raises(RuntimeBackendError) as raised:
        select_runtime_backend("rust", artifact=artifact)
    assert raised.value.reason_code == "RUNTIME_UNHEALTHY"


def test_missing_runtime_auto_falls_back_and_rust_fails_closed():
    automatic = select_runtime_backend("auto", artifact=None)
    assert automatic.selected == "python"
    assert automatic.reason_code == "RUNTIME_MISSING"
    with pytest.raises(RuntimeBackendError) as raised:
        select_runtime_backend("rust", artifact=None)
    assert raised.value.reason_code == "RUNTIME_MISSING"


def test_timeout_and_cancel_are_distinct_and_source_remains_immutable(tmp_path):
    artifact = _fake_runtime(tmp_path, sleep_operation="page")
    # Keep timeout << sleep(5) while allowing python process spawn.
    short_timeout = 0.5
    backend = RuntimeFastBackend(
        artifact, required_capabilities=("page",), timeout_seconds=short_timeout
    )
    backend.handshake()
    payload = {"hex": b"immutable".hex(), "offset": 0, "limit": 4}
    original = json.loads(json.dumps(payload))
    with pytest.raises(RuntimeBackendError) as timed_out:
        backend.call("page", payload)
    assert timed_out.value.reason_code == "TIMEOUT"
    assert payload == original

    backend = RuntimeFastBackend(
        artifact, required_capabilities=("page",), timeout_seconds=2
    )
    backend.handshake()
    cancelled = threading.Event()
    timer = threading.Timer(0.03, cancelled.set)
    timer.start()
    try:
        with pytest.raises(RuntimeBackendError) as stopped:
            backend.call("page", payload, cancel_event=cancelled)
    finally:
        timer.cancel()
    assert stopped.value.reason_code == "CANCELLED"
    assert payload == original


def test_runtime_crash_does_not_retry_in_rust_or_mutate_input(tmp_path):
    artifact = _fake_runtime(tmp_path, crash_operation="overlay_merge")
    backend = RuntimeFastBackend(
        artifact, required_capabilities=("overlay_merge",), timeout_seconds=1
    )
    backend.handshake()
    payload = {"base": {"a": "31"}, "overlay": {"b": "32"}}
    with pytest.raises(RuntimeBackendError) as raised:
        backend.call("overlay_merge", payload)
    assert raised.value.reason_code == "RUNTIME_UNHEALTHY"
    assert payload == {"base": {"a": "31"}, "overlay": {"b": "32"}}


def test_protocol_rejects_effectful_and_unknown_operations(tmp_path):
    backend = RuntimeFastBackend(_fake_runtime(tmp_path))
    backend.handshake()
    with pytest.raises(RuntimeBackendError) as raised:
        backend.call("write_source", {"path": "x.py"})
    assert raised.value.reason_code == "RUNTIME_UNHEALTHY"
    with pytest.raises(RuntimeBackendError) as direct:
        backend._request("write_source", {"path": "x.py"})
    assert direct.value.reason_code == "PROTOCOL_ERROR"


@pytest.mark.parametrize(
    "response_kind,reason",
    [
        ("list", "PROTOCOL_ERROR"),
        ("envelope", "PROTOCOL_ERROR"),
        ("reject", "TIMEOUT"),
        ("missing", "PROTOCOL_ERROR"),
        ("large", "PROTOCOL_ERROR"),
    ],
)
def test_response_boundary_rejects_invalid_envelopes(tmp_path, response_kind, reason):
    artifact = _fake_runtime(tmp_path, response_kind=response_kind)
    backend = RuntimeFastBackend(
        artifact,
        required_capabilities=("sha256",),
        max_response_bytes=1024,
    )
    with pytest.raises(RuntimeBackendError) as raised:
        backend.handshake()
    assert raised.value.reason_code == reason


def test_spawn_os_error_and_lazy_handshake(tmp_path, monkeypatch):
    artifact = _fake_runtime(tmp_path)
    backend = RuntimeFastBackend(artifact, required_capabilities=("sha256",))
    original = backend.handshake
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(backend, "handshake", counted)
    assert (
        backend.call("sha256", {"hex": b"x".hex()}) == hashlib.sha256(b"x").hexdigest()
    )
    assert calls == 1

    broken = RuntimeFastBackend(artifact, required_capabilities=("sha256",))
    monkeypatch.setattr(
        "simplicio_fast.runtime_backend.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("blocked")),
    )
    with pytest.raises(RuntimeBackendError) as raised:
        broken.handshake()
    assert raised.value.reason_code == "RUNTIME_UNHEALTHY"


def test_reason_code_contract_and_platform_aliases_are_complete():
    assert {
        "RUNTIME_MISSING",
        "ABI_MISMATCH",
        "VERSION_MISMATCH",
        "PLATFORM_UNSUPPORTED",
        "HASH_MISMATCH",
        "RUNTIME_UNHEALTHY",
        "PROTOCOL_ERROR",
        "TIMEOUT",
        "CANCELLED",
    }.issubset(REASON_CODES)
    assert platform_tag(system="Linux", machine="amd64") == "linux-x86_64"
    assert platform_tag(system="Darwin", machine="arm64") == "macos-aarch64"
    assert platform_tag(system="Windows", machine="AMD64") == "windows-x86_64"
    assert platform_tag(system="Plan9", machine="mips") is None


def test_adapter_source_contains_no_local_rust_toolchain_spawn():
    source = Path("src/simplicio_fast/runtime_backend.py").read_text(encoding="utf-8")
    forbidden = ('["car' + 'go"', '["rust' + 'c"')
    assert all(item not in source.lower() for item in forbidden)


def test_off_mode_is_observable_and_not_executable():
    selected = select_runtime_backend("off")
    assert selected.receipt()["reason_code"] == "DISABLED"
    with pytest.raises(RuntimeBackendError) as raised:
        selected.execute("sha256", {"hex": ""})
    assert raised.value.reason_code == "DISABLED"


def test_cancellation_before_spawn_is_deterministic(tmp_path):
    event = threading.Event()
    event.set()
    started = time.perf_counter()
    with pytest.raises(RuntimeBackendError) as raised:
        select_runtime_backend(
            "rust", artifact=_fake_runtime(tmp_path), cancel_event=event
        )
    assert raised.value.reason_code == "CANCELLED"
    assert time.perf_counter() - started < 0.5
