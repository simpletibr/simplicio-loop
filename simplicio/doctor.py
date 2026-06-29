"""doctor.py - `simplicio-py doctor` subcommand.

Prints detected hardware tier + recommended local model + install status.
With --install, opt-in to downloading the recommended GGUF. Without
the flag, never touches the disk. With --json, machine-readable output.
"""
from __future__ import annotations

import argparse
import json
import sys

from .ecosystem import check as eco_check
from .ecosystem import ensure_latest as eco_ensure_latest
from .ecosystem import tracked_packages
from .hardware import detect
from .local_models import (
    RECOMMENDATIONS,
    ensure_recommended,
    model_file_path,
)


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
        print(f"  {s.name:24s} {str(s.installed or '-'):>12s}"
              f"  >= {str(s.floor or '-'):<10s}"
              f"  latest {str(s.latest or '-'):<12s}{flag}")
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
    print(f"  ram           {profile.ram_gb:.1f} GB"
          f"  ({profile.detected_via.get('ram', '?')})")
    print(f"  gpu / vram    {profile.gpu_name or '(none)':30s} "
          f"{profile.vram_gb:.1f} GB"
          f"  ({profile.detected_via.get('gpu', '?')})")
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
    print("  runtime       llama.cpp via llama-cpp-python")
    print(f"  can run       {'yes' if result.can_run else 'NO'}")
    print(f"  can download  {'yes' if result.can_download else 'NO'}")
    print(f"  installed     {'YES' if result.installed else 'no'}")
    if result.reason:
        print(f"  status        {result.reason}")
    print()
    if result.installed:
        print("-> set SIMPLICIO_MODEL to use it explicitly:")
        print(f"  export SIMPLICIO_MODEL={result.spec.model_id}")
        print("  unset SIMPLICIO_BASE_URL SIMPLICIO_API_KEY")
    elif result.can_download:
        print("-> to install:")
        print("  simplicio-py doctor --install")
        print(
            f"  (or manually download {result.spec.repo_id}/{result.spec.filename} "
            f"to {model_file_path(result.spec)})"
        )
    else:
        print("-> hardware is too small for the recommended model; "
              "consider a smaller stack or move to cloud (SIMPLICIO_MODEL = "
              "OpenRouter/HF/etc.)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="simplicio-py doctor")
    p.add_argument("--install", action="store_true",
                   help="opt-in: download the recommended GGUF if not present")
    p.add_argument("--json", action="store_true",
                   help="machine-readable output")
    p.add_argument("--list-tiers", action="store_true",
                   help="print the full hardware → model map and exit")
    p.add_argument("--no-check-updates", action="store_true",
                   help="skip the dependency-freshness check")
    p.add_argument("--refresh", action="store_true",
                   help="bypass the 24h PyPI cache and force a live lookup")
    p.add_argument("--upgrade", action="store_true",
                   help="pip install -U every tracked package that is behind")
    args = p.parse_args(argv)

    if args.list_tiers:
        if args.json:
            print(json.dumps({
                tier: {
                    "model_id": s.model_id,
                    "repo_id": s.repo_id,
                    "filename": s.filename,
                    "label": s.label,
                    "size_gb_q4": s.size_gb_q4,
                    "notes": s.notes,
                }
                for tier, s in RECOMMENDATIONS.items()
            }, indent=2))
        else:
            print(f"{'tier':14s}  {'size':>7s}  model id")
            print("-" * 80)
            for tier, spec in RECOMMENDATIONS.items():
                print(f"{tier:14s}  {spec.size_gb_q4:5.1f}GB  {spec.model_id}")
                print(f"  -> {spec.label} - {spec.notes}")
        return 0

    profile = detect()
    result = ensure_recommended(profile, auto_download=args.install)

    check_updates = not args.no_check_updates
    eco_statuses: list = []
    eco_upgraded: list = []
    if check_updates:
        eco_statuses, eco_upgraded = _ecosystem_freshness(
            refresh=args.refresh, upgrade=args.upgrade,
        )

    if args.json:
        payload = result.to_dict()
        if check_updates:
            payload["dependencies"] = {
                "checked": [s.to_dict() for s in eco_statuses],
                "upgraded": eco_upgraded,
                "updates_available": [
                    s.name for s in eco_statuses if s.needs_upgrade
                ],
            }
        print(json.dumps(payload, indent=2))
        return 0

    _render_human(result, profile)
    if check_updates:
        _render_ecosystem(eco_statuses, eco_upgraded)
    return 0
