"""Authoritative JSON operator commands for persisted generation brokers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .checkpoint_lifecycle import CheckpointLifecycle, LifecycleError
from .generation_broker import GenerationBroker, _digest
from .map_service import MapServiceRegistry, RepositoryIdentity


def _load(attempt: Path) -> GenerationBroker:
    state_path = attempt / "generation-broker-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError("generation broker state missing or corrupt") from exc
    supplied = state.pop("receipt_hash", "")
    if supplied != _digest(state):
        raise LifecycleError("generation broker state receipt mismatch")
    registry = MapServiceRegistry()
    for row in state.get("identities", []):
        value = dict(row)
        key = value.pop("key")
        identity = RepositoryIdentity(**value)
        if identity.key != key:
            raise LifecycleError("generation broker identity key mismatch")
        registry.restore_identity(identity)
    lifecycle = CheckpointLifecycle(
        state["root"],
        task_id=state["task_id"],
        attempt_id=state["attempt_id"],
        source_commit=state["source_commit"],
        mapper_generation=state["mapper_generation"],
        base_path=state["base_path"],
    )
    if lifecycle.attempt.resolve() != attempt:
        raise LifecycleError("generation broker attempt containment mismatch")
    broker = GenerationBroker(registry, lifecycle)
    broker._identity_aliases.update(state.get("identity_aliases", {}))
    broker._promoted_generation = state.get("promoted_generation", lifecycle.mapper_generation)
    return broker


def _emit(value: Any) -> int:
    print(json.dumps(value, sort_keys=True))
    return 0


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio-loop generation-broker")
    sub = parser.add_subparsers(dest="action", required=True)
    action_help = {
        "status": "show the current generation-broker state",
        "reconcile": "reconcile candidate generations against the source identity",
        "doctor": "check generation-broker state and checkpoint bindings",
    }
    for action in ("status", "reconcile", "doctor"):
        command = sub.add_parser(action, help=action_help[action])
        command.add_argument("--attempt-dir", required=True)
    inspect = sub.add_parser("inspect", help="inspect one generation candidate")
    inspect.add_argument("--attempt-dir", required=True)
    inspect.add_argument("--candidate-id", required=True)
    pin = sub.add_parser("pin", help="pin one candidate until an expiry timestamp")
    pin.add_argument("--attempt-dir", required=True)
    pin.add_argument("--candidate-id", required=True)
    pin.add_argument("--expires-ns", required=True, type=int)
    release = sub.add_parser("release", help="release one candidate pin")
    release.add_argument("--attempt-dir", required=True)
    release.add_argument("--candidate-id", required=True)
    args = parser.parse_args(argv)
    broker = _load(Path(args.attempt_dir).resolve())
    if args.action == "inspect":
        return _emit(broker.inspect(args.candidate_id).to_dict())
    if args.action == "pin":
        return _emit(broker.pin(args.candidate_id, expires_ns=args.expires_ns).to_dict())
    if args.action == "release":
        return _emit(broker.release(args.candidate_id).to_dict())
    return _emit(getattr(broker, args.action)())


if __name__ == "__main__":
    raise SystemExit(cli_main())
