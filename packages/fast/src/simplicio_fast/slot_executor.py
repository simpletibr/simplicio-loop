"""Passive resident slot executor with isolated overlays and offline receipts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import mmap
from pathlib import Path
import threading
import time
from typing import Any, Mapping, Sequence

try:
    import resource  # Unix peak RSS; absent on Windows
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

ENVELOPE_SCHEMA = "simplicio.fast-slot-envelope/v1"
RECEIPT_SCHEMA = "simplicio.fast-slot-receipt/v1"
SNAPSHOT_SCHEMA = "simplicio.fast-snapshot/v1"
REQUIRED_HASHES = ("source_hash", "tool_hash", "config_hash", "contract_hash")


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class FastExecutorError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


def validate_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema") != ENVELOPE_SCHEMA:
        raise FastExecutorError("invalid_envelope_schema", ENVELOPE_SCHEMA)
    required = (
        "run_id",
        "slot_id",
        "issue_id",
        "commit",
        "generation",
        "fence",
        "idempotency_key",
        "budget",
        *REQUIRED_HASHES,
    )
    missing = [key for key in required if value.get(key) in (None, "")]
    if missing:
        raise FastExecutorError("invalid_envelope", ",".join(missing))
    result = dict(value)
    result["generation"] = int(result["generation"])
    if result["generation"] < 0 or int(result["budget"].get("max_operations", 0)) <= 0:
        raise FastExecutorError("invalid_budget", "generation/budget must be positive")
    expected = digest(
        {
            key: result[key]
            for key in (
                "run_id",
                "slot_id",
                "issue_id",
                "commit",
                "generation",
                "fence",
                *REQUIRED_HASHES,
            )
        }
    )
    if result["idempotency_key"] != expected:
        raise FastExecutorError("idempotency_mismatch", "key is not content addressed")
    return result


def consume_context_packet(
    packet: Mapping[str, Any], *, expected_generation: str | None = None
) -> dict[str, Any]:
    """Validate Mapper's public packet and expose opaque page handles to a slot."""
    if packet.get("schema") != "simplicio.context-packet/v1":
        raise FastExecutorError("packet_schema_invalid", "")
    unsigned = dict(packet)
    unsigned.pop("encoded_bytes", None)
    supplied = unsigned.pop("packet_hash", "")
    if supplied != digest(unsigned):
        raise FastExecutorError("packet_corrupt", supplied)
    if (
        expected_generation is not None
        and packet.get("generation") != expected_generation
    ):
        raise FastExecutorError(
            "packet_generation_stale", str(packet.get("generation"))
        )
    handles = []
    seen = set()
    for item in packet.get("items", []):
        handle = item.get("handle", "")
        content_hash = item.get("content_sha256", "")
        expected_prefix = f"fast://context/{packet.get('graph_digest')}/"
        if not handle.startswith(expected_prefix) or not content_hash:
            raise FastExecutorError("packet_handle_invalid", handle)
        if content_hash in seen:
            raise FastExecutorError("packet_duplicate_content", content_hash)
        seen.add(content_hash)
        handles.append(handle)
    return {
        "schema": "simplicio.fast-context-consumption/v1",
        "packet_hash": supplied,
        "generation": packet.get("generation"),
        "handles": handles,
        "coverage": packet.get("coverage"),
        "truncated": bool(packet.get("truncated")),
        "completion_authority": "LOOP_ONLY",
    }


@dataclass(frozen=True)
class Snapshot:
    root: Path
    snapshot_id: str
    source_hash: str
    manifest: Mapping[str, str]

    def page(
        self, relative_path: str, *, offset: int = 0, limit: int = 4096
    ) -> dict[str, Any]:
        if relative_path not in self.manifest:
            raise FastExecutorError("handle_missing", relative_path)
        if offset < 0 or limit <= 0 or limit > 65536:
            raise FastExecutorError("invalid_page", "offset/limit")
        path = self.root / "objects" / self.manifest[relative_path]
        with path.open("rb") as handle:
            if path.stat().st_size:
                with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as view:
                    data = bytes(view[offset : offset + limit])
            else:
                data = b""
        return {
            "schema": "simplicio.fast-page/v1",
            "snapshot_id": self.snapshot_id,
            "path": relative_path,
            "offset": offset,
            "bytes": data,
            "next_offset": offset + len(data),
            "eof": offset + len(data) >= path.stat().st_size,
        }


class SlotExecutor:
    """Thread-safe executor. It never schedules, creates slots, or declares completion."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()
        self.workers_started = 0

    def open_snapshot(
        self, run_id: str, source_hash: str, files: Mapping[str, bytes]
    ) -> Snapshot:
        if not run_id or not source_hash:
            raise FastExecutorError("snapshot_binding_missing", "run/source")
        manifest = {
            name: hashlib.sha256(content).hexdigest()
            for name, content in sorted(files.items())
        }
        snapshot_id = digest(
            {"run_id": run_id, "source_hash": source_hash, "manifest": manifest}
        )
        path = self.root / "snapshots" / snapshot_id
        objects = path / "objects"
        with self._lock:
            objects.mkdir(parents=True, exist_ok=True)
            for name, content in files.items():
                object_hash = manifest[name]
                target = objects / object_hash
                if (
                    target.exists()
                    and hashlib.sha256(target.read_bytes()).hexdigest() != object_hash
                ):
                    raise FastExecutorError("snapshot_corrupt", name)
                if not target.exists():
                    target.write_bytes(content)
            metadata = {
                "schema": SNAPSHOT_SCHEMA,
                "snapshot_id": snapshot_id,
                "source_hash": source_hash,
                "manifest": manifest,
            }
            meta_path = path / "snapshot.json"
            if meta_path.exists():
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
                if existing != metadata:
                    raise FastExecutorError("snapshot_stale", snapshot_id)
            else:
                meta_path.write_bytes(canonical(metadata) + b"\n")
        return Snapshot(path, snapshot_id, source_hash, manifest)

    def _receipt_path(self, key: str) -> Path:
        return self.root / "receipts" / f"{key}.json"

    def execute(
        self,
        envelope: Mapping[str, Any],
        snapshot: Snapshot,
        *,
        writes: Mapping[str, bytes] | None = None,
        runtime_available: bool = True,
        rust_available: bool = False,
    ) -> dict[str, Any]:
        env = validate_envelope(envelope)
        if env["source_hash"] != snapshot.source_hash:
            raise FastExecutorError("snapshot_stale", "source hash differs")
        key = env["idempotency_key"]
        receipt_path = self._receipt_path(key)
        with self._lock:
            if receipt_path.exists():
                value = json.loads(receipt_path.read_text(encoding="utf-8"))
                unsigned = dict(value)
                supplied = unsigned.pop("receipt_digest", "")
                if supplied != digest(unsigned):
                    raise FastExecutorError("receipt_corrupt", key)
                value["cache_hit"] = True
                value["duplicate_dispatch"] = True
                return value
            self.workers_started += 1
        started = time.perf_counter()
        cpu_started = time.process_time()
        rss_started = (
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if resource is not None
            else 0
        )
        overlay = (
            self.root
            / "overlays"
            / env["run_id"]
            / (f"{env['slot_id']}-g{env['generation']}-{env['fence']}")
        )
        overlay.mkdir(parents=True, exist_ok=True)
        operations = 0
        bytes_written = 0
        for name, content in sorted((writes or {}).items()):
            operations += 1
            if operations > int(env["budget"]["max_operations"]):
                raise FastExecutorError("budget_exhausted", "max_operations")
            target = (overlay / name).resolve()
            if overlay.resolve() not in target.parents:
                raise FastExecutorError("overlay_escape", name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            bytes_written += len(content)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "run_id": env["run_id"],
            "slot_id": env["slot_id"],
            "issue_id": env["issue_id"],
            "commit": env["commit"],
            "generation": env["generation"],
            "fence": env["fence"],
            "idempotency_key": key,
            "snapshot_id": snapshot.snapshot_id,
            "overlay_id": digest(
                {
                    "slot_id": env["slot_id"],
                    "generation": env["generation"],
                    "fence": env["fence"],
                }
            ),
            "cache_hit": False,
            "duplicate_dispatch": False,
            "operations": operations,
            "bytes_written": bytes_written,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "cpu_ms": round((time.process_time() - cpu_started) * 1000, 3),
            "rss_kib_delta": max(
                0,
                (
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    if resource is not None
                    else 0
                )
                - rss_started,
            ),
            "runtime_mode": "runtime" if runtime_available else "python_fallback",
            "runtime_null_reason": None if runtime_available else "RUNTIME_UNAVAILABLE",
            "engine": "rust" if rust_available else "python",
            "engine_null_reason": None if rust_available else "RUST_UNAVAILABLE",
            "status": "VERIFIED",
            "completion_authority": "LOOP_ONLY",
            "tokens": None,
            "tokens_null_reason": "NO_LLM_USED",
            "bindings": {key: env[key] for key in REQUIRED_HASHES},
        }
        receipt["receipt_digest"] = digest(receipt)
        with self._lock:
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = receipt_path.with_suffix(".tmp")
            temporary.write_bytes(canonical(receipt) + b"\n")
            temporary.replace(receipt_path)
        return receipt

    @staticmethod
    def verify_receipt(
        receipt: Mapping[str, Any], envelope: Mapping[str, Any]
    ) -> tuple[bool, str]:
        try:
            env = validate_envelope(envelope)
            unsigned = dict(receipt)
            supplied = unsigned.pop("receipt_digest")
            if supplied != digest(unsigned):
                return False, "receipt_digest_mismatch"
            for key in (
                "run_id",
                "slot_id",
                "issue_id",
                "commit",
                "generation",
                "fence",
                "idempotency_key",
            ):
                if receipt.get(key) != env.get(key):
                    return False, f"{key}_mismatch"
            if (
                receipt.get("status") != "VERIFIED"
                or receipt.get("completion_authority") != "LOOP_ONLY"
            ):
                return False, "authority_or_status_invalid"
        except (FastExecutorError, KeyError, TypeError, ValueError):
            return False, "malformed_receipt"
        return True, "ok"


def make_envelope(
    slot: int, *, run_id: str = "run", generation: int = 1, fence: str = "f1"
) -> dict[str, Any]:
    value = {
        "schema": ENVELOPE_SCHEMA,
        "run_id": run_id,
        "slot_id": f"slot-{slot}",
        "issue_id": f"issue-{slot}",
        "commit": "a" * 40,
        "generation": generation,
        "fence": fence,
        "budget": {"max_operations": 100},
        "source_hash": "source",
        "tool_hash": "tool",
        "config_hash": "config",
        "contract_hash": "contract",
    }
    value["idempotency_key"] = digest(
        {
            key: value[key]
            for key in (
                "run_id",
                "slot_id",
                "issue_id",
                "commit",
                "generation",
                "fence",
                *REQUIRED_HASHES,
            )
        }
    )
    return value


def quantize(vector: Sequence[float], lane: str) -> tuple[float | int, ...]:
    """Reference Q0/Q1/Q2 encoding used by the reproducible ranking fixture."""
    if lane == "Q0":
        return tuple(float(item) for item in vector)
    if lane == "Q1":
        scale = max(max(abs(item) for item in vector), 1e-12) / 127
        return tuple(max(-127, min(127, round(item / scale))) for item in vector)
    if lane in {"Q2a", "Q2b"}:
        scale = max(max(abs(item) for item in vector), 1e-12) / 7
        return tuple(max(-7, min(7, round(item / scale))) for item in vector)
    raise FastExecutorError("quantization_lane_unknown", lane)


def ranking_metrics(
    expected: Sequence[str], actual: Sequence[str], *, k: int = 10
) -> dict[str, float]:
    expected_set = set(expected[:k])
    top = list(actual[:k])
    hits = [1 if item in expected_set else 0 for item in top]
    recall = sum(hits) / len(expected_set) if expected_set else 1.0
    dcg = sum(
        hit / __import__("math").log2(index + 2) for index, hit in enumerate(hits)
    )
    ideal = sum(
        1 / __import__("math").log2(index + 2)
        for index in range(min(len(expected_set), k))
    )
    reciprocal = next((1 / (index + 1) for index, hit in enumerate(hits) if hit), 0.0)
    return {
        "recall_at_10": recall,
        "ndcg_at_10": dcg / ideal if ideal else 1.0,
        "mrr": reciprocal,
    }


def parity_receipt(payload: Any, rust_digest: str | None = None) -> dict[str, Any]:
    python_digest = digest(payload)
    return {
        "python_digest": python_digest,
        "rust_digest": rust_digest,
        "parity": rust_digest == python_digest if rust_digest is not None else None,
        "parity_null_reason": None if rust_digest is not None else "RUST_UNAVAILABLE",
    }


__all__ = [
    "FastExecutorError",
    "SlotExecutor",
    "Snapshot",
    "make_envelope",
    "quantize",
    "ranking_metrics",
    "parity_receipt",
    "validate_envelope",
    "digest",
    "ENVELOPE_SCHEMA",
    "RECEIPT_SCHEMA",
]
