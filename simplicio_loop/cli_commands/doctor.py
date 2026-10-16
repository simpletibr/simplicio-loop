"""`extensions`, `stack`, `doctor` and `inspect`: diagnostics and stack locks.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

import json

from ._base import impl


def extensions_doctor(provider: str, policy: str, schema: str) -> int:
    from ..extension_handshake import ExtensionHandshakeError, extension_handshake
    try:
        payload = extension_handshake(provider, policy, requested_schema=schema)
    except ExtensionHandshakeError as exc:
        payload = {"schema": schema, "status": "BLOCKED", "reason_code": exc.reason_code, "detail": exc.detail}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _load_stack_components(path: str):
    from ..stack_lock import load_component_observations

    try:
        return load_component_observations(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read component observations: {exc}") from exc


def stack_command(args) -> int:
    from ..stack_lock import (
        StackLock,
        StackLockError,
        diagnose_stack,
        load_stack_lock,
        load_stack_registry,
        write_stack_lock,
    )

    try:
        if args.stack_command == "lock":
            components = _load_stack_components(args.components)
            registry_path = getattr(args, "registry", "")
            if registry_path:
                diagnosis = diagnose_stack(
                    components,
                    load_stack_registry(registry_path),
                    args.route,
                )
                if diagnosis.status != "READY":
                    print(json.dumps({
                        "schema": "simplicio.stack-lock-command/v1",
                        "status": "BLOCKED",
                        "reason_code": "stack_compatibility_blocked",
                        "diagnostics": diagnosis.to_dict(),
                    }, ensure_ascii=False, sort_keys=True))
                    return 2
            lock = StackLock.create(components, args.route, run_id=args.run_id)
            path = write_stack_lock(lock, args.output)
            result = {
                "schema": "simplicio.stack-lock-command/v1",
                "status": "LOCKED",
                "path": str(path),
                "lock_hash": lock.lock_hash,
                "route": lock.route,
                "run_id": lock.run_id,
            }
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0

        lock = load_stack_lock(args.lock)
        route = args.route or lock.route
        lock.verify_unchanged(_load_stack_components(args.components), route)
        result = {
            "schema": "simplicio.stack-lock-command/v1",
            "status": "VERIFIED",
            "path": str(args.lock),
            "lock_hash": lock.lock_hash,
            "route": route,
            "run_id": lock.run_id,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, StackLockError) as exc:
        print(json.dumps({
            "schema": "simplicio.stack-lock-command/v1",
            "status": "BLOCKED",
            "reason_code": "stack_lock_invalid",
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2


def stack_doctor_command(args) -> int:
    """Report installed stack identity and route readiness without side effects."""
    from ..stack_lock import discover_installed_components

    try:
        components = discover_installed_components()
        by_name = {component.name: component for component in components}
        required = ("simplicio-loop", "simplicio-mapper")
        missing = [name for name in required if not by_name.get(name, None) or not by_name[name].available]
        routes = {
            "standalone": {
                "available": not missing,
                "missing": missing,
            },
        }
        status = "READY" if routes["standalone"]["available"] else "BLOCKED"
        result = {
            "schema": "simplicio.stack-doctor/v1",
            "status": status,
            "components": [component.to_dict() for component in components],
            "routes": routes,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if status == "READY" else 2
    except (OSError, ValueError) as exc:
        print(json.dumps({
            "schema": "simplicio.stack-doctor/v1",
            "status": "BLOCKED",
            "reason_code": "stack_observation_invalid",
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2


def source_doctor_command(args) -> int:
    """Report SourceAdapter v1 contract readiness without contacting a provider."""
    from ..source_contract import SourceCapabilities

    profiles = {
        "local": "local-reference",
        "github": "github-reference",
        "azure-devops": "azure-devops-fixture",
        "jira-cloud": "jira-cloud-fixture",
        "asana": "asana-fixture",
        "trello": "trello-fixture",
    }
    provider = str(args.source_provider)
    capabilities = SourceCapabilities(provider, profiles[provider])
    result = {
        "schema": "simplicio.source-doctor/v1",
        "status": "READY",
        "provider": provider,
        "profile": capabilities.profile,
        "capabilities": capabilities.as_dict(),
        "transport": "fixture-or-injected",
        "real_provider_auth": "UNVERIFIED",
        "effects_attempted": False,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def add_extensions(sub):
    p_extensions = sub.add_parser("extensions", help="negotiate installed Loop extension runtimes")
    extensions_sub = p_extensions.add_subparsers(dest="extensions_command", required=True)
    p_ext_doctor = extensions_sub.add_parser("doctor", help="dry-run an exact provider/runtime handshake")
    p_ext_doctor.add_argument("--provider", required=True)
    p_ext_doctor.add_argument("--policy", default="strict-default")
    p_ext_doctor.add_argument("--schema", default="simplicio.extension-handshake/v1")
    p_ext_doctor.add_argument("--json", action="store_true", help="machine-readable output (always JSON)")


def add_stack(sub):
    p_stack = sub.add_parser("stack", help="create or verify an installed-stack lock")
    stack_sub = p_stack.add_subparsers(dest="stack_command", required=True)
    p_stack_lock = stack_sub.add_parser(
        "lock", help="persist a deterministic lock from JSON component observations"
    )
    p_stack_lock.add_argument("--components", required=True, help="JSON component observations")
    p_stack_lock.add_argument(
        "--registry",
        default="",
        help="optional simplicio.stack-registry/v1 compatibility registry; blocks incompatible locks",
    )
    p_stack_lock.add_argument("--route", choices=("standalone",), required=True)
    p_stack_lock.add_argument("--run-id", default="")
    p_stack_lock.add_argument(
        "--output", default=impl().os.path.join(".simplicio-loop", "orchestrator", "stack-lock.json")
    )
    p_stack_verify = stack_sub.add_parser(
        "verify", help="verify current observations against a persisted lock"
    )
    p_stack_verify.add_argument("--lock", required=True, help="persisted stack lock JSON")
    p_stack_verify.add_argument("--components", required=True, help="JSON component observations")
    p_stack_verify.add_argument("--route", choices=("standalone",), default=None)


def add_doctor(sub):
    p_doctor = sub.add_parser(
        "doctor",
        help="inspect the installed stack or storage routing (default: stack health overview)",
        description=(
            "Inspect stack health and component readiness. "
            "Running without a subcommand executes the general stack health overview "
            "(equivalent to 'doctor all') without requiring --storage or a subcommand."
        ),
    )
    p_doctor.set_defaults(doctor_command=None, stack_json=False, doctor_json=False, all_json=False, all_online=False,
                          login_json=False, online=False)
    p_doctor.add_argument("--online", action="store_true",
                          help="overview: ask GitHub for the latest release (offline by default)")
    p_doctor.add_argument("--storage", action="store_true",
                          help="inspect the Loop storage adapter boundary")
    p_doctor.add_argument("--route", choices=("legacy", "shadow", "mapper"), default="mapper")
    p_doctor.add_argument("--data-dir", default=None)
    p_doctor.add_argument("--repo", default=".", help="repository root for cutover diagnostics")
    p_doctor.add_argument("--require-capability", action="append", default=[])
    p_doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    doctor_sub = p_doctor.add_subparsers(
        dest="doctor_command",
        title="subcommands",
        description="subcommands for targeted component inspection (default: runs overview)",
    )
    p_doctor_stack = doctor_sub.add_parser(
        "stack", help="report installed component identity and route readiness"
    )
    p_doctor_stack.add_argument("--json", dest="stack_json", action="store_true",
                                help="emit machine-readable JSON")
    p_doctor_source = doctor_sub.add_parser(
        "source", help="report SourceAdapter v1 contract readiness"
    )
    p_doctor_source.add_argument(
        "--provider",
        dest="source_provider",
        choices=("local", "github", "azure-devops", "jira-cloud", "asana", "trello"),
        default="local",
    )
    p_doctor_source.add_argument("--json", dest="doctor_json", action="store_true",
                                 help="emit machine-readable JSON")

    p_doctor_all = doctor_sub.add_parser(
        "all", help="overview: login, update, distribution, Runtime, PATH operators, disk (same as bare `doctor`)"
    )
    p_doctor_all.add_argument("--json", dest="all_json", action="store_true", help="emit machine-readable JSON")
    p_doctor_all.add_argument("--online", dest="all_online", action="store_true",
                              help="ask GitHub for the latest release (offline by default)")
    p_doctor_login = doctor_sub.add_parser("login", help="only the login check (shared with the Runtime)")
    p_doctor_login.add_argument("--json", dest="login_json", action="store_true", help="emit machine-readable JSON")

    p_doctor_mapper = doctor_sub.add_parser(
        "mapper", help="check that the installed simplicio_mapper is the expected build"
    )
    p_doctor_mapper.add_argument("--repo", default=".", help="monorepo checkout to compare the commit with")
    p_doctor_mapper.add_argument("--json", dest="mapper_json", action="store_true",
                                 help="emit machine-readable JSON")


def add_inspect(sub):
    p_inspect = sub.add_parser("inspect", help="inspect storage routing and MapperStore capabilities")
    p_inspect.add_argument("--storage", action="store_true", required=True,
                           help="inspect the Loop storage adapter boundary")
    p_inspect.add_argument("--route", choices=("legacy", "shadow", "mapper"), default="mapper")
    p_inspect.add_argument("--data-dir", default=None)
    p_inspect.add_argument("--repo", default=".", help="repository root for cutover diagnostics")
    p_inspect.add_argument("--require-capability", action="append", default=[])
    p_inspect.add_argument("--json", action="store_true", help="emit machine-readable JSON")
