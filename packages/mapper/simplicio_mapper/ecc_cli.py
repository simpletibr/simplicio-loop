"""CLI for the optional, bounded ECC advisory provider."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence

from .ecc_guidance import EccGuidanceError, EccGuidanceProvider


def _provider(args: argparse.Namespace) -> EccGuidanceProvider:
    env_required = os.environ.get("SIMPLICIO_ECC_REQUIRED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }
    env_require_ref = os.environ.get("SIMPLICIO_ECC_REQUIRE_REF", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }
    root = args.ecc_root or os.environ.get("SIMPLICIO_ECC_ROOT")
    manifest_path = args.manifest or os.environ.get("SIMPLICIO_ECC_MANIFEST")
    required = bool(args.require or env_required)
    if args.ecc_root or args.manifest or args.require:
        return EccGuidanceProvider(
            root,
            manifest_path=manifest_path,
            enabled=True,
            required=required,
            require_ref=bool(args.require or env_require_ref or env_required),
            max_context_chars=args.max_context_chars,
        )
    return EccGuidanceProvider.from_environment() or EccGuidanceProvider(
        required=required,
        max_context_chars=args.max_context_chars,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simplicio-mapper ecc",
        description="Inspect or materialize the bounded ECC advisory guidance.",
    )
    parser.add_argument("--ecc-root", default="", help="checked-out ECC repository")
    parser.add_argument("--manifest", default="", help="Simplicio-owned ECC manifest")
    parser.add_argument("--max-context-chars", type=int, default=None)
    parser.add_argument("--require", action="store_true", help="fail when ECC guidance is unavailable")
    parser.add_argument("--json", action="store_true", help="emit the machine-readable payload (default)")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="report ECC provenance and policy")
    doctor.add_argument("--json", action="store_true", help="emit the machine-readable payload (default)")
    doctor.add_argument("--ecc-root", default=argparse.SUPPRESS, help="checked-out ECC repository")
    doctor.add_argument("--manifest", default=argparse.SUPPRESS, help="Simplicio-owned ECC manifest")
    doctor.add_argument("--require", action="store_true", default=argparse.SUPPRESS)
    pack = sub.add_parser("pack", help="emit one bounded ECC guidance pack")
    pack.add_argument("--stage", default="planning")
    pack.add_argument("--role", default="mapper-planner")
    pack.add_argument("--json", action="store_true", help="emit the machine-readable payload (default)")
    pack.add_argument("--ecc-root", default=argparse.SUPPRESS, help="checked-out ECC repository")
    pack.add_argument("--manifest", default=argparse.SUPPRESS, help="Simplicio-owned ECC manifest")
    pack.add_argument("--require", action="store_true", default=argparse.SUPPRESS)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        provider = _provider(args)
        if args.command == "doctor":
            payload = provider.doctor()
            code = 0 if payload["status"] in {"READY", "DISABLED", "UNAVAILABLE"} else 2
        else:
            payload = provider.pack(args.stage, role_id=args.role)
            code = 0 if payload["status"] == "READY" else 2
    except (EccGuidanceError, OSError, ValueError) as exc:
        payload = {"schema": "simplicio.ecc-cli/v1", "status": "BLOCKED", "error": str(exc)}
        code = 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


__all__ = ["main"]
