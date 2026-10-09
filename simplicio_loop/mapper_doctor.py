"""`simplicio-loop doctor mapper`: is the installed simplicio_mapper the build the loop expects?

The loop binds the mapper that is importable in its environment. This check compares that
mapper's build identity with the expectation of this monorepo: origin, state dir and source
commit. Read-only; a blocker names a ``reason_code`` and the command that fixes it.

Contract: ``simplicio.mapper-doctor/v1``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.mapper-doctor/v1"
EXPECTED_ORIGIN = "simplicio-loop/packages/mapper"
EXPECTED_STATE_DIR = ".simplicio-loop"
REINSTALL = ("python3 -m pip uninstall -y simplicio-mapper; "
             "python3 -m pip install --force-reinstall simplicio-loop")
CHECKOUT_REINSTALL = "bash scripts/dev_install.sh"
FIXES: dict[str, str] = {
    "mapper_not_importable": "python3 -m pip install --force-reinstall simplicio-loop",
    "mapper_identity_missing": REINSTALL,
    "origin_mismatch": REINSTALL,
    "state_dir_mismatch": REINSTALL,
    "build_unstamped": REINSTALL,
    "commit_mismatch": CHECKOUT_REINSTALL,
}
REASON_CODES = frozenset({"verified", *FIXES})
_SHA_LEN = 40


def _load_identity() -> dict[str, Any] | None:
    """Identity of the importable mapper; ``None`` for a build that predates the identity module."""
    import simplicio_mapper  # noqa: F401 - ImportError propagates as mapper_not_importable

    try:
        from simplicio_mapper.build_identity import build_identity
    except ImportError:
        return None
    return dict(build_identity())


def _git_head(repo: Path) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and len(sha) == _SHA_LEN else None


def evaluate(identity: Mapping[str, Any] | None, *, checkout_head: str | None) -> dict[str, Any]:
    """Compare an installed identity with the expected build; pure, so every reason is testable."""
    expected = {"origin": EXPECTED_ORIGIN, "state_dir": EXPECTED_STATE_DIR,
                "source_commit": checkout_head}
    installed = dict(identity) if identity is not None else None
    reason = "verified"
    if installed is None:
        reason = "mapper_identity_missing"
    elif installed.get("state_dir") != EXPECTED_STATE_DIR:
        reason = "state_dir_mismatch"
    elif installed.get("origin") is None:
        reason = "build_unstamped"
    elif installed.get("origin") != EXPECTED_ORIGIN:
        reason = "origin_mismatch"
    elif not _is_sha(installed.get("source_commit")):
        reason = "build_unstamped"
    elif checkout_head and installed.get("source_commit") != checkout_head:
        reason = "commit_mismatch"
    return {"schema": SCHEMA, "status": "OK" if reason == "verified" else "BLOCKED",
            "reason_code": reason, "expected": expected, "installed": installed,
            "checkout_head": checkout_head, "fix": FIXES.get(reason)}


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == _SHA_LEN and all(c in "0123456789abcdef" for c in value)


def build_report(repo: str | Path = ".") -> dict[str, Any]:
    repo = Path(repo).resolve()
    try:
        identity = _load_identity()
    except ImportError as exc:
        report = evaluate(None, checkout_head=None)
        report.update(reason_code="mapper_not_importable", status="BLOCKED",
                      fix=FIXES["mapper_not_importable"], error=str(exc))
        return report
    checkout_head = _git_head(repo) if (repo / "packages" / "mapper" / "simplicio_mapper").is_dir() else None
    return evaluate(identity, checkout_head=checkout_head)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio-loop doctor mapper",
                                     description="check the installed simplicio_mapper build")
    parser.add_argument("--repo", default=".", help="monorepo checkout to compare the commit with")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    report = build_report(args.repo)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    elif report["status"] == "OK":
        print("simplicio-mapper: OK (verified)")
    else:
        print(f"simplicio-mapper: BLOCKED ({report['reason_code']})\n  fix: {report['fix']}")
    return 0 if report["status"] == "OK" else 2


__all__ = ["EXPECTED_ORIGIN", "EXPECTED_STATE_DIR", "REASON_CODES", "build_report", "evaluate", "main"]
