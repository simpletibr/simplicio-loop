"""Installed SDK/session/CLI parity and resident transport receipt (#348)."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Mapping, Sequence

from simplicio_fast.resident_daemon import DaemonError, ResidentFastDaemon, make_request
from simplicio_fast.rust_session import RustCoreSession
from simplicio_fast.sdk import ProjectionSDK


SCHEMA = "simplicio.fast.sdk-parity-receipt/v1"
COMMON_READ_ONLY = frozenset({"query", "context"})


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _json_command(command: Sequence[str], root: Path) -> Mapping[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root)))
    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {result.stderr}")
    value = json.loads(result.stdout)
    if not isinstance(value, Mapping):
        raise RuntimeError("command did not return a JSON object")
    return value


async def _transport_probe() -> dict[str, Any]:
    scenarios: dict[str, dict[str, Any]] = {}

    async def slow_handler(request: Any) -> Mapping[str, Any]:
        await asyncio.sleep(0.2)
        return {"operation": request.operation}

    deadline_daemon = ResidentFastDaemon(slow_handler, max_inflight=1, queue_capacity=1)
    await deadline_daemon.start()
    deadline_task = asyncio.create_task(
        deadline_daemon.submit(make_request("deadline", "slot", timeout_seconds=0.01))
    )
    try:
        await deadline_task
    except DaemonError as error:
        scenarios["deadline"] = {"passed": error.reason_code == "deadline_expired", "reason": error.reason_code}
    else:
        scenarios["deadline"] = {"passed": False, "reason": "completed"}
    finally:
        await deadline_daemon.shutdown()

    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_handler(request: Any) -> Mapping[str, Any]:
        started.set()
        await release.wait()
        return {"operation": request.operation}

    backpressure_daemon = ResidentFastDaemon(blocked_handler, max_inflight=1, queue_capacity=1)
    await backpressure_daemon.start()
    first = asyncio.create_task(
        backpressure_daemon.submit(make_request("first", "slot", timeout_seconds=5))
    )
    await started.wait()
    second = asyncio.create_task(
        backpressure_daemon.submit(make_request("second", "slot", timeout_seconds=5))
    )
    await asyncio.sleep(0)
    try:
        await backpressure_daemon.submit(make_request("third", "slot", timeout_seconds=5))
    except DaemonError as error:
        scenarios["backpressure"] = {"passed": error.reason_code == "backpressure", "reason": error.reason_code}
    else:
        scenarios["backpressure"] = {"passed": False, "reason": "accepted"}
    release.set()
    await asyncio.gather(first, second)
    await backpressure_daemon.shutdown()

    cancel_started = asyncio.Event()
    cancel_release = asyncio.Event()

    async def cancellable_handler(request: Any) -> Mapping[str, Any]:
        cancel_started.set()
        await cancel_release.wait()
        return {"operation": request.operation}

    cancel_daemon = ResidentFastDaemon(cancellable_handler, max_inflight=1, queue_capacity=1)
    await cancel_daemon.start()
    cancel_task = asyncio.create_task(
        cancel_daemon.submit(make_request("cancel", "slot", timeout_seconds=5))
    )
    await cancel_started.wait()
    cancelled = await cancel_daemon.cancel("cancel")
    try:
        await cancel_task
    except DaemonError as error:
        scenarios["cancellation"] = {
            "passed": cancelled and error.reason_code == "request_cancelled",
            "reason": error.reason_code,
        }
    else:
        scenarios["cancellation"] = {"passed": False, "reason": "completed"}
    finally:
        cancel_release.set()
        await cancel_daemon.shutdown()

    lifecycle = ResidentFastDaemon(slow_handler, max_inflight=1, queue_capacity=1)
    first_health = await lifecycle.start()
    await lifecycle.crash()
    crashed = lifecycle.health()
    restarted = await lifecycle.start()
    stopped = await lifecycle.shutdown()
    scenarios["lifecycle"] = {
        "passed": (
            first_health["state"] == "READY"
            and crashed["state"] == "CRASHED"
            and restarted["state"] == "READY"
            and stopped["state"] == "STOPPED"
            and restarted["epoch"] > first_health["epoch"]
        ),
        "states": [first_health["state"], crashed["state"], restarted["state"], stopped["state"]],
    }
    return {
        "schema": "simplicio.fast.resident-transport-receipt/v1",
        "status": "pass" if all(item["passed"] for item in scenarios.values()) else "fail",
        "scenarios": scenarios,
        "bounds": {
            "max_inflight": 1,
            "queue_capacity": 1,
            "deadline": True,
            "backpressure": True,
            "cancellation": True,
        },
        "authority": "derived_read_only",
    }


def build_receipt(
    *,
    python_capabilities: Mapping[str, Any],
    cli_capabilities: Mapping[str, Any],
    rust_handshake: Mapping[str, Any],
    transport: Mapping[str, Any],
) -> dict[str, Any]:
    python_operations = frozenset(str(item) for item in python_capabilities.get("operations", []))
    cli_sdk = cli_capabilities.get("sdk")
    cli_operations = frozenset(str(item) for item in cli_sdk.get("operations", [])) if isinstance(cli_sdk, Mapping) else frozenset()
    rust_operations = frozenset(str(item) for item in rust_handshake.get("capabilities", []))
    surfaces = {
        "python_sdk": sorted(python_operations),
        "cli_sdk": sorted(cli_operations),
        "rust_session": sorted(rust_operations),
    }
    common = sorted(python_operations & cli_operations & rust_operations)
    parity = all(COMMON_READ_ONLY <= operations for operations in (python_operations, cli_operations, rust_operations))
    receipt = {
        "schema": SCHEMA,
        "status": "pass" if parity and transport.get("status") == "pass" else "fail",
        "surfaces": surfaces,
        "parity": {
            "scope": "common_read_only",
            "required": sorted(COMMON_READ_ONLY),
            "common_operations": common,
            "passed": parity,
            "python_only": sorted(python_operations - rust_operations),
            "cli_only": sorted(cli_operations - rust_operations),
            "rust_only": sorted(rust_operations - python_operations),
        },
        "rust": {
            "schema": rust_handshake.get("schema"),
            "status": rust_handshake.get("status"),
            "engine_version": rust_handshake.get("engine_version"),
            "binary_digest": rust_handshake.get("binary_digest"),
            "source_commit": rust_handshake.get("source_commit"),
            "conformance_digest": rust_handshake.get("conformance_digest"),
        },
        "transport": dict(transport),
        "authority": "derived_read_only",
        "dispatch": False,
        "residuals": [
            "cross_platform_installed_artifacts",
            "upgrade_rollback_receipts",
            "full_rust_python_surface_equivalence",
        ],
    }
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


def run(root: Path, rust_executable: Path) -> dict[str, Any]:
    python_capabilities = ProjectionSDK("issue-348").capabilities()
    cli_capabilities = _json_command(
        [sys.executable, "-m", "simplicio_fast.cli", "capabilities", "--fast-engine", "python"],
        root,
    )
    session = RustCoreSession(rust_executable)
    try:
        rust_handshake = dict(session.handshake)
        session_cache = session.call("session_cache_stats", {})
        rust_handshake["session_cache_stats"] = session_cache
        rust_handshake["session_metrics"] = session.metrics()
    finally:
        session.close()
    transport = asyncio.run(_transport_probe())
    receipt = build_receipt(
        python_capabilities=python_capabilities,
        cli_capabilities=cli_capabilities,
        rust_handshake=rust_handshake,
        transport=transport,
    )
    receipt["environment"] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "rust_executable": str(rust_executable),
    }
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--rust", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.root.resolve(), args.rust.resolve())
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


__all__ = ["COMMON_READ_ONLY", "SCHEMA", "build_receipt", "run"]


if __name__ == "__main__":
    main()
