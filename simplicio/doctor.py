"""doctor.py — `simplicio doctor` subcommand.

Prints detected hardware tier + recommended local model + install status.
With --install, opt-in to downloading the recommended GGUF. Without
the flag, never touches the disk. With --json, machine-readable output.
"""
from __future__ import annotations

import argparse
import json
import sys

from .hardware import detect
from .local_models import (
    RECOMMENDATIONS,
    ensure_recommended,
    model_file_path,
)


def _render_human(result, profile) -> None:
    print("simplicio doctor", file=sys.stderr)
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
        print("  simplicio doctor --install")
        print(
            f"  (or manually download {result.spec.repo_id}/{result.spec.filename} "
            f"to {model_file_path(result.spec)})"
        )
    else:
        print("-> hardware is too small for the recommended model; "
              "consider a smaller stack or move to cloud (SIMPLICIO_MODEL = "
              "OpenRouter/HF/etc.)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="simplicio doctor")
    p.add_argument("--install", action="store_true",
                   help="opt-in: download the recommended GGUF if not present")
    p.add_argument("--json", action="store_true",
                   help="machine-readable output")
    p.add_argument("--list-tiers", action="store_true",
                   help="print the full hardware → model map and exit")
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

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    _render_human(result, profile)
    return 0
