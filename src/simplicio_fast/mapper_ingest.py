"""Fail-closed validation for Mapper-owned Fast handoff artifacts."""

from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version as distribution_version
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "simplicio.fast.mapper-ingest/v1"
HANDOFF_SCHEMA = "simplicio.mapper-fast-handoff/v1"
PUBLIC_HANDOFF_SCHEMA = "simplicio.map-handoff/v1"
PUBLIC_ARTIFACTS = (
    ("context_snapshot", ".simplicio/context-snapshot.json"),
    ("project_map", ".simplicio/project-map.json"),
    ("symbol_index", ".simplicio/symbol-index.json"),
    ("call_graph", ".simplicio/call-graph.json"),
    ("architecture_inventory", ".simplicio/architecture-inventory.json"),
)


class MapperIngestError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return digest.hexdigest(), size


def artifact_digest(artifacts: list[Mapping[str, Any]]) -> str:
    """Return the content-addressed digest of a Mapper artifact manifest.

    The individual artifact digests are the source facts.  This aggregate is
    the identity Fast pins for the canonical handoff, so a changed artifact
    cannot reuse a snapshot merely because its Mapper generation string was
    accidentally reused.
    """

    manifest = [
        {
            "name": str(item.get("name") or ""),
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in sorted(
            artifacts,
            key=lambda value: (str(value.get("path")), str(value.get("name") or "")),
        )
    ]
    encoded = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _head(root: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-git-") as directory:
        stdout_path = Path(directory) / "stdout.txt"
        stderr_path = Path(directory) / "stderr.txt"
        with (
            stdout_path.open("w", encoding="utf-8") as stdout,
            stderr_path.open("w", encoding="utf-8") as stderr,
        ):
            result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                text=True,
                check=False,
                close_fds=True,
            )
        commit = stdout_path.read_text(encoding="utf-8").strip()
    if result.returncode != 0 or len(commit) != 40:
        raise MapperIngestError("mapper_commit_mismatch")
    return commit


def _installed_mapper_version() -> str:
    """Return the observed Mapper distribution version when it is available."""
    try:
        return distribution_version("simplicio-mapper")
    except PackageNotFoundError:
        return "unknown"


def _adapt_public_map_handoff(root: Path, envelope: dict[str, Any]) -> dict[str, Any]:
    """Translate public ``simplicio.map-handoff/v1`` into the ingest envelope."""
    if envelope.get("ready") is not True:
        raise MapperIngestError(
            "mapper_incomplete",
            str(envelope.get("reason") or "public mapper handoff is not ready"),
        )
    artifacts: list[dict[str, Any]] = []
    for name, relative in PUBLIC_ARTIFACTS:
        path = root / relative
        if not path.is_file():
            continue
        digest, size = _sha256(path)
        artifacts.append(
            {"name": name, "path": relative, "bytes": size, "sha256": digest}
        )
    if not artifacts:
        raise MapperIngestError("mapper_incomplete", "no mapper artifacts on disk")
    pack = envelope.get("context_pack") if isinstance(envelope.get("context_pack"), dict) else {}
    snapshot = pack.get("source_snapshot") if isinstance(pack.get("source_snapshot"), dict) else {}
    generation = str(
        snapshot.get("snapshot_id")
        or (envelope.get("status") or {}).get("phase")
        or "mapper-handoff"
    ).strip()
    if not generation:
        generation = "mapper-handoff"
    changed_paths: list[str] = []
    for item in envelope.get("targets") or []:
        if not isinstance(item, str) or not item or Path(item).is_absolute() or ".." in Path(item).parts:
            continue
        changed_paths.append(Path(item).as_posix())
    inner = {
        "schema": HANDOFF_SCHEMA,
        "repository_id": root.name,
        "revision": _head(root),
        "generation": generation,
        "producer": {"name": "simplicio-mapper", "version": _installed_mapper_version()},
        "fidelity": {"gate": "ready", "source": PUBLIC_HANDOFF_SCHEMA},
        "artifacts": artifacts,
        "delta": {"changed_paths": sorted(set(changed_paths))},
    }
    body = json.dumps(inner, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "handoff": inner,
        "receipt": {
            "schema": "simplicio.mapper-fast-handoff-receipt/v1",
            "status": "parsed",
            "handoff_sha256": hashlib.sha256(body).hexdigest(),
            "generation": generation,
            "counters": {"parsed": 1, "reused": 0, "degraded": 0, "fallback": 0},
        },
    }


def validate_handoff(
    root: Path,
    envelope: dict[str, Any],
    *,
    expected_generation: str | None = None,
) -> dict[str, Any]:
    """Validate a Mapper handoff envelope for integrated ingest.

    Accepts the public ``simplicio.map-handoff/v1`` (``simplicio-mapper handoff``)
    and the machine envelope ``simplicio.mapper-fast-handoff/v1``. The adapter
    only consumes documented metadata and artifact digests.
    """
    if not isinstance(envelope, dict):
        raise MapperIngestError("mapper_schema_unsupported")
    if envelope.get("schema") == PUBLIC_HANDOFF_SCHEMA:
        envelope = _adapt_public_map_handoff(root, envelope)
    handoff = envelope.get("handoff")
    receipt = envelope.get("receipt")
    if not isinstance(handoff, dict) or not isinstance(receipt, dict):
        raise MapperIngestError("mapper_schema_unsupported")
    if handoff.get("schema") != HANDOFF_SCHEMA:
        raise MapperIngestError("mapper_schema_unsupported")
    if receipt.get("schema") != "simplicio.mapper-fast-handoff-receipt/v1":
        raise MapperIngestError("mapper_schema_unsupported")
    if receipt.get("status") not in {"parsed", "reused"} or not _is_digest(
        receipt.get("handoff_sha256")
    ):
        raise MapperIngestError("mapper_incomplete")
    if handoff.get("repository_id") != root.name:
        raise MapperIngestError("mapper_repository_mismatch")
    revision = handoff.get("revision")
    if revision != _head(root):
        raise MapperIngestError(
            "mapper_commit_mismatch",
            "Mapper handoff is stale for this checkout; run simplicio-fast refresh",
        )
    generation = handoff.get("generation")
    if not isinstance(generation, str) or not generation.strip():
        raise MapperIngestError("mapper_generation_stale")
    if expected_generation is not None and generation != expected_generation:
        raise MapperIngestError(
            "mapper_generation_stale",
            f"expected={expected_generation} actual={generation}; refresh Mapper context",
        )
    receipt_generation = receipt.get("generation")
    if receipt_generation is not None and receipt_generation != generation:
        raise MapperIngestError("mapper_generation_stale")
    producer = handoff.get("producer")
    if producer is None:
        capabilities = handoff.get("capabilities")
        handoff_schemas = (
            capabilities.get("handoff_schemas")
            if isinstance(capabilities, dict)
            else None
        )
        if not isinstance(handoff_schemas, list) or HANDOFF_SCHEMA not in handoff_schemas:
            raise MapperIngestError("mapper_schema_unsupported")
        producer = {
            "name": "simplicio-mapper",
            "version": _installed_mapper_version(),
        }
    if (
        not isinstance(producer, dict)
        or producer.get("name") != "simplicio-mapper"
        or not isinstance(producer.get("version"), str)
        or not producer["version"].strip()
    ):
        raise MapperIngestError("mapper_schema_unsupported")
    fidelity = handoff.get("fidelity")
    if not isinstance(fidelity, dict):
        counters = receipt.get("counters")
        if (
            not isinstance(counters, dict)
            or counters.get("parsed", 0) + counters.get("reused", 0) < 1
            or counters.get("degraded", 1) != 0
            or counters.get("fallback", 1) != 0
        ):
            raise MapperIngestError("mapper_incomplete")
        fidelity = {"gate": "ready", "source": "receipt-counters"}
    if fidelity.get("gate") != "ready":
        raise MapperIngestError("mapper_incomplete")
    delta = handoff.get("delta", {})
    if not isinstance(delta, dict):
        raise MapperIngestError("mapper_schema_unsupported")

    def validated_paths(value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise MapperIngestError("mapper_schema_unsupported")
        result: list[str] = []
        for item in value:
            if (
                not isinstance(item, str)
                or not item
                or Path(item).is_absolute()
                or ".." in Path(item).parts
            ):
                raise MapperIngestError("mapper_schema_unsupported")
            result.append(Path(item).as_posix())
        return sorted(set(result))

    changed_paths = validated_paths(delta.get("changed_paths", []))
    deleted_paths = validated_paths(delta.get("deleted_paths", []))
    if set(changed_paths).intersection(deleted_paths):
        raise MapperIngestError("mapper_schema_unsupported")

    artifacts = handoff.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise MapperIngestError("mapper_incomplete")
    checked: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise MapperIngestError("mapper_schema_unsupported")
        relative = artifact.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(artifact.get("bytes"), int)
            or isinstance(artifact.get("bytes"), bool)
            or artifact.get("bytes") < 0
            or not _is_digest(artifact.get("sha256"))
        ):
            raise MapperIngestError("mapper_schema_unsupported")
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise MapperIngestError("mapper_digest_mismatch", relative)
        digest, size = _sha256(path)
        if digest != artifact.get("sha256") or size != artifact.get("bytes"):
            raise MapperIngestError("mapper_digest_mismatch", relative)
        checked.append(
            {
                "name": artifact.get("name"),
                "path": relative,
                "bytes": size,
                "sha256": digest,
            }
        )
    aggregate_digest = artifact_digest(checked)
    supplied_artifact_digest = handoff.get("artifact_digest")
    if supplied_artifact_digest is None:
        supplied_artifact_digest = receipt.get("artifact_digest")
    if supplied_artifact_digest is not None:
        normalized_artifact_digest = (
            supplied_artifact_digest.removeprefix("sha256:")
            if isinstance(supplied_artifact_digest, str)
            else None
        )
        if (
            not _is_digest(normalized_artifact_digest)
            or normalized_artifact_digest != aggregate_digest
        ):
            raise MapperIngestError("mapper_artifact_digest_mismatch")
    artifact_names = {str(item.get("name") or "") for item in checked}
    supplied_coverage = handoff.get("capability_coverage")
    if supplied_coverage is not None and not isinstance(supplied_coverage, dict):
        raise MapperIngestError("mapper_schema_unsupported")
    capability_coverage = dict(supplied_coverage or {})
    capability_coverage.setdefault("context_graph", "context_snapshot" in artifact_names)
    capability_coverage.setdefault("files", "project_map" in artifact_names)
    capability_coverage.setdefault("symbols", "symbol_index" in artifact_names)
    capability_coverage.setdefault("relations", "call_graph" in artifact_names)
    capability_coverage.setdefault("source_hashes", True)
    capability_coverage.setdefault("stable_handles", "context_snapshot" in artifact_names)
    return {
        "schema": SCHEMA,
        "mode": "integrated",
        "producer": {
            "name": "simplicio-mapper",
            "version": producer["version"],
        },
        "mapper_schema": HANDOFF_SCHEMA,
        "mapper_version": producer["version"],
        "repository_id": handoff["repository_id"],
        "commit": revision,
        "generation": generation,
        "artifact_digest": aggregate_digest,
        "capability_coverage": capability_coverage,
        "fidelity": fidelity,
        "handoff_sha256": receipt["handoff_sha256"],
        "artifacts": checked,
        "changed_paths": changed_paths,
        "deleted_paths": deleted_paths,
    }


def load_handoff(root: Path, path: Path | None = None) -> dict[str, Any]:
    source = path or root / ".simplicio" / "fast-handoff.json"
    try:
        envelope = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MapperIngestError("mapper_missing", str(source)) from error
    return validate_handoff(root, envelope)


__all__ = [
    "HANDOFF_SCHEMA",
    "MapperIngestError",
    "SCHEMA",
    "artifact_digest",
    "load_handoff",
    "validate_handoff",
]
