"""Native Rust path, resource and rollout receipt for issue #349."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time
from typing import Any, Mapping

from simplicio_fast.rollout import RolloutController, RolloutError


SCHEMA = "simplicio.fast.native-resource-receipt/v1"
NATIVE_ABI = "simplicio.fast-native/v1"


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class NativeSession:
    def __init__(self, executable: Path) -> None:
        self.process = subprocess.Popen(
            [str(executable), "--session"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.handshake = self._read()
        if (
            self.handshake.get("schema") != "simplicio.fast.engine-session/v1"
            or self.handshake.get("abi") != NATIVE_ABI
            or self.handshake.get("ok") is not True
            or not isinstance(self.handshake.get("capabilities"), list)
        ):
            self.close()
            raise RuntimeError("native_handshake_invalid")

    def _read(self) -> dict[str, Any]:
        if self.process.stdout is None:
            raise RuntimeError("native_stdout_missing")
        line = self.process.stdout.readline()
        if not line or len(line.encode("utf-8")) > 1_048_576:
            raise RuntimeError("native_frame_invalid")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError("native_frame_invalid")
        return value

    def call(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self.process.stdin is None:
            raise RuntimeError("native_stdin_missing")
        request = {"abi": NATIVE_ABI, "operation": operation, "payload": dict(payload)}
        self.process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        return self._read()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def __enter__(self) -> "NativeSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _resource_probe(executable: Path, repetitions: int = 30) -> dict[str, Any]:
    import psutil

    with NativeSession(executable) as session:
        process = psutil.Process(session.process.pid)
        rss_before = process.memory_info().rss
        cpu_before = process.cpu_times()
        payload = bytes(range(256)) * 64
        samples: list[float] = []
        failures: list[str] = []
        for _ in range(repetitions):
            started = time.perf_counter()
            digest = session.call("sha256", {"hex": payload.hex()})
            samples.append((time.perf_counter() - started) * 1000)
            expected = hashlib.sha256(payload).hexdigest()
            if digest.get("ok") is not True or digest.get("result") != expected:
                failures.append("sha256")
        page = session.call("page", {"hex": payload.hex(), "offset": 64, "limit": 128})
        overlay = session.call("overlay_merge", {"base": {"a": 1, "b": 2}, "overlay": {"b": 3, "c": None}})
        bounds = session.call("page", {"hex": payload.hex(), "offset": 0, "limit": 0})
        unknown = session.call("unknown", {})
        rss_after = process.memory_info().rss
        cpu_after = process.cpu_times()
    samples.sort()
    return {
        "status": "pass" if not failures and page.get("ok") and overlay.get("result") == {"a": 1, "b": 3} and bounds.get("reason") == "bounds" and unknown.get("reason") == "operation" else "fail",
        "repetitions": repetitions,
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))], 3),
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_delta_bytes": rss_after - rss_before,
        "cpu_user_ms": round((cpu_after.user - cpu_before.user) * 1000, 3),
        "cpu_system_ms": round((cpu_after.system - cpu_before.system) * 1000, 3),
        "payload_bytes": len(payload),
        "failures": failures,
        "bounds_checked": ["page_limit", "unknown_operation"],
        "raw_samples_ms": [round(value, 3) for value in samples],
    }


def _rollout_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-349-rollout-") as directory:
        state = Path(directory) / "rollout.json"
        controller = RolloutController(state)
        shadow = controller.transition("shadow", generation="SFAST001:1")
        canary = controller.transition("canary", generation="SFAST001:2")
        rollback = controller.transition("rollback", reason="resource-gate")
        state.write_text('{"mode":"forged"}', encoding="utf-8")
        try:
            controller.transition("shadow")
        except RolloutError as error:
            corrupt_reason = error.reason_code
        else:
            corrupt_reason = "accepted"
    return {
        "status": "pass" if shadow["status"] == "accepted" and canary["previous_mode"] == "shadow" and rollback["status"] == "rolled-back" and corrupt_reason == "rollout_state_invalid" else "fail",
        "modes": [shadow["mode"], canary["mode"], rollback["mode"]],
        "rollback_reason": rollback["reason"],
        "corrupt_state_reason": corrupt_reason,
    }


def build_receipt(*, executable: Path, handshake: Mapping[str, Any], resource: Mapping[str, Any], rollout: Mapping[str, Any]) -> dict[str, Any]:
    receipt = {
        "schema": SCHEMA,
        "status": "pass" if resource.get("status") == "pass" and rollout.get("status") == "pass" else "fail",
        "native": {
            "abi": handshake.get("abi"),
            "schema": handshake.get("schema"),
            "capabilities": sorted(str(item) for item in handshake.get("capabilities", [])),
            "transport": handshake.get("transport"),
            "executable": str(executable),
        },
        "resource": dict(resource),
        "rollout": dict(rollout),
        "authority": "derived_read_only",
        "dispatch": False,
        "residuals": [
            "linux_macos_installed_native_assets",
            "cross_platform_consumer_e2e",
            "upgrade_rollback_registry_receipt",
            "rust_python_semantic_surface_parity",
        ],
    }
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


def run(executable: Path) -> dict[str, Any]:
    with NativeSession(executable) as session:
        handshake = dict(session.handshake)
    resource = _resource_probe(executable)
    rollout = _rollout_probe()
    receipt = build_receipt(executable=executable, handshake=handshake, resource=resource, rollout=rollout)
    receipt["environment"] = {"platform": platform.platform(), "python": platform.python_version(), "pid_sampling": "psutil"}
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.native.resolve())
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


__all__ = ["NATIVE_ABI", "SCHEMA", "build_receipt", "run"]


if __name__ == "__main__":
    main()
