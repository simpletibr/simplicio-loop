"""doctor.py - `simplicio-py doctor` subcommand.

Prints deterministic environment and dependency status. Local model execution
and provisioning are disabled. With --json, machine-readable output.
"""

from __future__ import annotations

import argparse
import json
import sys

from .commands.versions import versions_report
from .ecosystem import check as eco_check
from .ecosystem import ensure_latest as eco_ensure_latest
from .ecosystem import tracked_packages
from .hardware import detect
from .hub_adapter import HubTaskAdapter
from .local_models import (
    RECOMMENDATIONS,
    ensure_recommended,
    model_file_path,
)
from .observability import events_summary, native_delegation_summary


def _ecosystem_freshness(refresh: bool = False, upgrade: bool = False):
    """Run the dependency-freshness check at least once per doctor invocation.

    Returns (statuses, upgraded) where statuses is a list[DepStatus] and
    upgraded is the list of package names pip actually upgraded (only when
    upgrade=True)."""
    packages = tracked_packages()
    statuses = eco_check(packages, refresh=refresh)
    upgraded: list[str] = []
    if upgrade:
        upgraded = eco_ensure_latest(force=True, packages=packages)
        # Re-read installed versions so the rendered table reflects the upgrade.
        statuses = eco_check(packages, refresh=refresh)
    return statuses, upgraded


def _render_ecosystem(statuses, upgraded) -> None:
    print()
    print("dependency freshness (installed / floor / pypi-latest):")
    drift = False
    for s in statuses:
        if s.needs_upgrade:
            drift = True
        flag = "  <- UPDATE AVAILABLE" if s.needs_upgrade else ""
        print(
            f"  {s.name:24s} {str(s.installed or '-'):>12s}"
            f"  >= {str(s.floor or '-'):<10s}"
            f"  latest {str(s.latest or '-'):<12s}{flag}"
        )
    if upgraded:
        print(f"  upgraded {len(upgraded)} package(s): {', '.join(upgraded)}")
    elif drift:
        print("  -> some packages are behind; run: simplicio-py doctor --upgrade")
    else:
        print("  all tracked packages are current")


def _render_human(result, profile) -> None:
    print("simplicio-py doctor", file=sys.stderr)
    print(f"  os            {profile.os_name}")
    if profile.apple_silicon:
        print(f"  chip          {profile.gpu_name} (Apple Silicon, unified memory)")
    print(f"  ram           {profile.ram_gb:.1f} GB  ({profile.detected_via.get('ram', '?')})")
    print(
        f"  gpu / vram    {profile.gpu_name or '(none)':30s} "
        f"{profile.vram_gb:.1f} GB"
        f"  ({profile.detected_via.get('gpu', '?')})"
    )
    print(f"  detected tier {profile.tier}")
    print()
    print("recommended doer model:")
    print(f"  label         {result.spec.label}")
    print(f"  model id      {result.spec.model_id}")
    print(f"  repo          {result.spec.repo_id}")
    print(f"  file          {result.spec.filename}")
    print(f"  path          {model_file_path(result.spec)}")
    print(f"  size (Q4)     ~{result.spec.size_gb_q4:.1f} GB")
    print(f"  notes         {result.spec.notes}")
    print()
    print("  runtime       deterministic-only (LLM execution disabled)")
    print(f"  can run       {'yes' if result.can_run else 'NO'}")
    print(f"  can download  {'yes' if result.can_download else 'NO'}")
    print(f"  installed     {'YES' if result.installed else 'no'}")
    if result.reason:
        print(f"  status        {result.reason}")
    print()
    print("-> no model execution or provisioning is available in simplicio-py")


def _render_events(summary: dict) -> None:
    """Issue #107: surface the structured event stream (`emit_event`) that
    feeds a host loop's journal, so `doctor` is a place to see it's wired up
    without hand-inspecting `.simplicio/events.jsonl`."""
    print()
    print("observability events (issue #107 unified evidence flow):")
    if not summary["exists"]:
        print(f"  no events recorded yet ({summary['path']})")
        return
    print(f"  path          {summary['path']}")
    print(f"  count         {summary['count']}")
    for record in summary["recent"]:
        print(f"  - [{record.get('ts', '?')}] {record.get('event', '?')}: {record.get('payload', {})}")


def _render_mapper_versions(payload: dict) -> None:
    """Issue #232: surface the Mapper installed/declared/tested versions and
    drift result (`simplicio.component_manifest.detect_drift`) so `doctor`
    shows this without a separate `simplicio-cli versions` call. Read-only —
    never raises, never touches a running task's state (see
    `simplicio/component_manifest.py`'s `DriftResult` docstring)."""
    print()
    print("mapper component versions (issue #232):")
    mapper = payload["mapper"]
    print(f"  installed        {mapper['installed'] or '(not installed)'}")
    print(f"  declared_range   {mapper['declared_range'] or '(none declared)'}")
    tested = mapper["tested_against"] or f"null ({mapper['tested_against_reason']})"
    print(f"  tested_against   {tested}")
    print(f"  latest_known     null ({mapper['unavailable_reason']})")
    drift = payload["drift"]
    if drift["has_drift"]:
        print(f"  drift            {drift['kind']}: {drift['reason']}")
    else:
        print("  drift            none")


def _render_native_delegation(summary: dict) -> None:
    """Issue #111: surface the native-vs-python routing telemetry
    (`native_delegation` events, `simplicio.runtime_bridge.record_delegation`)
    per delegable verb, so `doctor` shows what fraction of `gate`/`nest`/
    `edit`/`file`/`test-run` invocations actually reached the native Rust
    binary vs the Python fallback."""
    print()
    print("native-vs-python delegation (issue #111):")
    if not summary["exists"] or not summary["verbs"]:
        print(f"  no delegation events recorded yet ({summary['path']})")
        return
    print(f"  path          {summary['path']}")
    print(f"  overall       {summary['native_pct']:5.1f}% native  ({summary['total']} invocations)")
    for verb, counts in summary["verbs"].items():
        routes = ", ".join(
            f"{route}={n}" for route, n in counts.items() if route not in {"total", "native_pct"}
        )
        print(f"  - {verb:12s} {counts['native_pct']:5.1f}% native  ({counts['total']} total: {routes})")


def _render_hub_status(status: dict) -> None:
    """Issue #231: surface the resolved Hub adapter mode/identity so a
    Hub-driven run's misconfiguration (mode=on with no propagated identity)
    is visible without reading env vars by hand."""
    print()
    print("hub adapter (issue #231):")
    print(f"  mode                    {status['mode']}")
    print(f"  identity complete       {status['identity_complete']}")
    print(f"  local scheduler allowed {status['local_scheduler_allowed']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="simplicio-py doctor")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--list-tiers", action="store_true", help="print the full hardware → model map and exit")
    p.add_argument("--no-check-updates", action="store_true", help="skip the dependency-freshness check")
    p.add_argument("--refresh", action="store_true", help="bypass the 24h PyPI cache and force a live lookup")
    p.add_argument(
        "--upgrade", action="store_true", help="pip install -U every tracked package that is behind"
    )
    p.add_argument(
        "--root",
        default=".",
        help="repo root to read .simplicio/events.jsonl from (issue #107)",
    )
    p.add_argument(
        "--events-limit",
        type=int,
        default=5,
        help="how many recent observability events to show (default 5)",
    )
    args = p.parse_args(argv)

    if args.list_tiers:
        if args.json:
            print(
                json.dumps(
                    {
                        tier: {
                            "model_id": s.model_id,
                            "repo_id": s.repo_id,
                            "filename": s.filename,
                            "label": s.label,
                            "size_gb_q4": s.size_gb_q4,
                            "notes": s.notes,
                        }
                        for tier, s in RECOMMENDATIONS.items()
                    },
                    indent=2,
                )
            )
        else:
            print(f"{'tier':14s}  {'size':>7s}  model id")
            print("-" * 80)
            for tier, spec in RECOMMENDATIONS.items():
                print(f"{tier:14s}  {spec.size_gb_q4:5.1f}GB  {spec.model_id}")
                print(f"  -> {spec.label} - {spec.notes}")
        return 0

    profile = detect()
    result = ensure_recommended(profile)

    check_updates = not args.no_check_updates
    eco_statuses: list = []
    eco_upgraded: list = []
    if check_updates:
        eco_statuses, eco_upgraded = _ecosystem_freshness(
            refresh=args.refresh,
            upgrade=args.upgrade,
        )

    events = events_summary(args.root, limit=args.events_limit)
    delegation = native_delegation_summary(args.root)
    hub_status = HubTaskAdapter.create().doctor_status()
    # Issue #232: read-only, cannot interrupt/block an in-flight `run_task` —
    # see `simplicio/component_manifest.py`'s `DriftResult` docstring and
    # `tests/python/test_versions_command.py::test_versions_report_does_not_interfere_with_active_task`.
    # Deliberately does NOT forward `args.root` (the *target project* root
    # for `.simplicio/events.jsonl`) — the Mapper version/manifest state is
    # about the `simplicio-cli` checkout itself, a different root entirely
    # (see `commands/versions.py::versions_report`'s docstring).
    mapper_versions = versions_report()

    if args.json:
        payload = result.to_dict()
        if check_updates:
            payload["dependencies"] = {
                "checked": [s.to_dict() for s in eco_statuses],
                "upgraded": eco_upgraded,
                "updates_available": [s.name for s in eco_statuses if s.needs_upgrade],
            }
        payload["observability_events"] = events
        payload["native_delegation"] = delegation
        payload["hub"] = hub_status
        payload["mapper_versions"] = mapper_versions
        print(json.dumps(payload, indent=2))
        return 0

    _render_human(result, profile)
    if check_updates:
        _render_ecosystem(eco_statuses, eco_upgraded)
    _render_mapper_versions(mapper_versions)
    _render_events(events)
    _render_native_delegation(delegation)
    _render_hub_status(hub_status)
    return 0
