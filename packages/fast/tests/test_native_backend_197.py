import io
import hashlib
from pathlib import Path
import shutil
import subprocess
import pytest
from simplicio_fast import __version__
from simplicio_fast.native_backend import (
    ABI,
    NativeBackendError,
    PythonBackend,
    ResidentRustSession,
    RustBackend,
    backend_receipt_fields,
    canonical,
    execute_with_fallback,
    platform_tag,
    resolve_packaged_backend,
    select_backend,
)
from simplicio_fast.snapshot import build_snapshot


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("sha256", {"hex": b"abc".hex()}),
        ("catalog_lookup", {"catalog": {"a": "1"}, "key": "a"}),
        ("page", {"hex": b"abcdef".hex(), "offset": 1, "limit": 3}),
        (
            "overlay_merge",
            {
                "base": {"a": b"1".hex(), "b": b"2".hex()},
                "overlay": {"a": b"3".hex(), "b": None},
            },
        ),
    ],
)
def test_python_standalone_hot_paths(operation, payload):
    result, backend, reason = execute_with_fallback(PythonBackend(), operation, payload)
    assert backend == "python" and reason == "RUST_UNAVAILABLE"
    assert result is not None


def test_native_canonical_rejects_non_finite_payloads():
    with pytest.raises(NativeBackendError, match="native_payload_invalid"):
        canonical({"value": float("nan")})
    with pytest.raises(NativeBackendError, match="native_payload_invalid"):
        canonical({"value": float("inf")})


def test_incompatible_or_tampered_artifact_is_never_used(tmp_path):
    artifact = tmp_path / "fast-native"
    artifact.write_bytes(b"binary")
    valid = {
        "abi": ABI,
        "platform": "linux-x86_64",
        "version": __version__,
        "source_commit": "a" * 40,
        "size": len(b"binary"),
        "sha256": hashlib.sha256(b"binary").hexdigest(),
    }
    backend, reason = select_backend(
        artifact,
        {
            "abi": "old",
            "platform": "linux-x86_64",
            "sha256": hashlib.sha256(b"binary").hexdigest(),
        },
    )
    assert isinstance(backend, PythonBackend)
    assert reason == "RUST_ABI_INCOMPATIBLE"
    backend, reason = select_backend(
        artifact,
        {**valid, "sha256": "0" * 64},
        expected_platform="linux-x86_64",
    )
    assert isinstance(backend, PythonBackend)
    assert reason == "RUST_ARTIFACT_HASH_MISMATCH"
    backend, reason = select_backend(
        artifact, {**valid, "version": "0.0.0"}, expected_platform="linux-x86_64"
    )
    assert isinstance(backend, PythonBackend)
    assert reason == "RUST_VERSION_MISMATCH"
    backend, reason = select_backend(
        artifact, {**valid, "size": 999}, expected_platform="linux-x86_64"
    )
    assert isinstance(backend, PythonBackend)
    assert reason == "RUST_ARTIFACT_SIZE_MISMATCH"


class GoldenRust(RustBackend):
    def __init__(self):
        pass

    def call(self, operation, payload):
        value, _, _ = execute_with_fallback(PythonBackend(), operation, payload)
        return value


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("sha256", {"hex": b"portable fixture".hex()}),
        ("page", {"hex": bytes(range(64)).hex(), "offset": 7, "limit": 19}),
        ("overlay_merge", {"base": {"a": "31"}, "overlay": {"b": "32"}}),
    ],
)
def test_differential_golden_python_rust_semantics(operation, payload):
    expected = execute_with_fallback(PythonBackend(), operation, payload)[0]
    actual, backend, reason = execute_with_fallback(GoldenRust(), operation, payload)
    assert actual == expected and backend == "rust" and reason is None


class CrashingRust(GoldenRust):
    def call(self, operation, payload):
        from simplicio_fast.native_backend import NativeBackendError

        raise NativeBackendError("native_crash")


def test_native_crash_degrades_without_mutating_source():
    source = {"a": "31"}
    result, backend, reason = execute_with_fallback(
        CrashingRust(), "overlay_merge", {"base": source, "overlay": {"b": "32"}}
    )
    assert result == {"a": "31", "b": "32"}
    assert source == {"a": "31"}
    assert backend == "python" and reason == "NATIVE_CRASH"


def test_selected_backend_is_serializable_in_generation_receipt():
    assert backend_receipt_fields(PythonBackend(), "RUST_UNAVAILABLE") == {
        "backend": "python",
        "backend_artifact_hash": None,
        "fallback_reason": "RUST_UNAVAILABLE",
    }


def test_packaged_resolver_is_explicit_when_no_precompiled_binary_exists(tmp_path):
    backend, reason = resolve_packaged_backend(
        tmp_path, system="Linux", machine="x86_64"
    )
    assert isinstance(backend, PythonBackend)
    assert reason == "RUST_ARTIFACT_MISSING"


def test_packaged_resolver_validates_manifest_and_sha_without_toolchain(tmp_path):
    directory = tmp_path / "artifacts" / "linux-x86_64" / ABI.replace("/", "_")
    directory.mkdir(parents=True)
    artifact = directory / "simplicio-fast-native"
    artifact.write_bytes(b"precompiled-fixture")
    (directory / "manifest.json").write_text(
        '{"abi":"simplicio.fast-native/v1","filename":"simplicio-fast-native",'
        f'"platform":"linux-x86_64","version":"{__version__}",'
        '"source_commit":"'
        + ("a" * 40)
        + '","size":19,"sha256":"'
        + hashlib.sha256(artifact.read_bytes()).hexdigest()
        + '"}',
        encoding="utf-8",
    )
    backend, reason = resolve_packaged_backend(
        tmp_path, system="linux", machine="amd64"
    )
    assert isinstance(backend, RustBackend) and reason is None
    artifact.write_bytes(b"x" * len(b"precompiled-fixture"))
    backend, reason = resolve_packaged_backend(
        tmp_path, system="linux", machine="x86_64"
    )
    assert isinstance(backend, PythonBackend)
    assert reason == "RUST_ARTIFACT_HASH_MISMATCH"


def test_platform_aliases_are_canonical_and_unknown_is_rejected():
    assert platform_tag(system="Darwin", machine="arm64") == "macos-aarch64"
    assert platform_tag(system="plan9", machine="mips") is None


def test_artifact_hashing_is_streamed_and_size_bounded(tmp_path, monkeypatch):
    artifact = tmp_path / "fast-native"
    artifact.write_bytes(b"streamed-artifact")
    manifest = {
        "abi": ABI,
        "platform": "linux-x86_64",
        "version": __version__,
        "source_commit": "a" * 40,
        "size": artifact.stat().st_size,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("whole-file read is forbidden")
        ),
    )
    backend, reason = select_backend(
        artifact, manifest, expected_platform="linux-x86_64"
    )
    assert isinstance(backend, RustBackend)
    assert reason is None
    monkeypatch.setattr("simplicio_fast.native_backend.MAX_NATIVE_ARTIFACT_BYTES", 4)
    backend, reason = select_backend(
        artifact, manifest, expected_platform="linux-x86_64"
    )
    assert isinstance(backend, PythonBackend)
    assert reason == "RUST_ARTIFACT_TOO_LARGE"


def test_resident_session_handshake_and_framed_call(monkeypatch):
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(
                '{"schema":"simplicio.fast.engine-session/v1",'
                '"abi":"simplicio.fast-native/v1","ok":true}\n'
                '{"abi":"simplicio.fast-native/v1","ok":true,"result":"ok"}\n'
                '{"abi":"simplicio.fast-native/v1","ok":true,"result":"again"}\n'
            )

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr(
        "simplicio_fast.native_backend.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    session = ResidentRustSession(Path("native"), {})
    assert session.call("sha256", {"hex": "00"}) == "ok"
    assert session.call("sha256", {"hex": "01"}) == "again"
    metrics = session.metrics()
    assert metrics["starts"] == 1
    assert metrics["reconnects"] == 0
    assert metrics["requests"] == 2
    assert metrics["failures"] == 0
    assert metrics["bytes_in"] == 158
    assert metrics["bytes_out"] == 121
    assert metrics["wall_ms"] >= 0
    session.close()


def test_resident_session_compiled_binary_lifecycle(tmp_path: Path) -> None:
    cargo = shutil.which("cargo")
    if cargo is None:
        pytest.skip("cargo is required for compiled native lifecycle E2E")
    root = Path(__file__).parents[1]
    subprocess.run(
        [cargo, "build", "--manifest-path", "native/fast-native/Cargo.toml", "--quiet"],
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=180,
    )
    binary = root / "native" / "fast-native" / "target" / "debug" / (
        "simplicio-fast-native.exe" if shutil.which("cmd.exe") else "simplicio-fast-native"
    )
    assert binary.is_file()
    session = ResidentRustSession(binary, {})
    try:
        assert session.call("sha256", {"hex": "616263"}) == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
        assert session.call("page", {"hex": "616263", "offset": 1, "limit": 1}) == "62"
        (tmp_path / "service.py").write_text(
            "def helper():\n    return True\n", encoding="utf-8"
        )
        snapshot = tmp_path / "service.sfast"
        build_snapshot(tmp_path, snapshot)
        assert session.call("session_cache_stats", {})["snapshots"] == 0
        query = session.call(
            "query",
            {"snapshot": str(snapshot), "term": "helper", "limit": 1},
        )
        assert query["matches"][0]["qualified_name"] == "helper"
        assert session.call("session_cache_stats", {})["snapshots"] == 1
        context = session.call(
            "context",
            {
                "snapshot": str(snapshot),
                "root": str(tmp_path),
                "term": "helper",
                "limit": 1,
                "max_lines": 10,
                "max_bytes": 1000,
                "max_tokens": 100,
            },
        )
        assert context["spans"][0]["symbol"] == "helper"
        assert session.call("session_cache_stats", {})["snapshots"] == 1
        metrics = session.metrics()
        assert metrics["starts"] == 1
        assert metrics["reconnects"] == 0
        assert metrics["requests"] == 7
        assert metrics["failures"] == 0
    finally:
        process = session._process
        process.kill()
        process.wait(timeout=2)
        with pytest.raises(NativeBackendError, match="session_crashed"):
            session.call("sha256", {"hex": "00"})
        session.restart()
        assert session.call("sha256", {"hex": "616263"}).startswith("ba7816")
        restarted = session.metrics()
        assert restarted["starts"] == 2
        assert restarted["reconnects"] == 1
        assert restarted["failures"] == 1
        session.close()
    assert session._process.poll() is not None
