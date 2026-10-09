"""endpoint_compare (verify): the HTTP route drift of the clone, computed by scripts/flow_audit.py (no route logic here).

Applies only when a changed file, tracked or untracked, is a route or handler; otherwise it is skipped as
not_applicable. It then runs the flow audit CLI (inside the sandbox, scrubbed env) on the base (`git archive HEAD`)
and on the working tree of the clone, and records the endpoints added or removed and the gaps that are new.
An audit that cannot run, exits with anything but 0 (clean) or 1 (findings) or prints no flow-audit JSON is
`error`, never `ok`.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from types import ModuleType

from .. import proc, sandbox
from .registry import PointContext, PointResult, register

NAME = "endpoint_compare"
SCHEMA = "simplicio.flow-audit/v1"
LIST_CAP = 20
_ERROR_CAP = 300
_HERE = Path(__file__).resolve()
_CANDIDATES = (
    _HERE.parents[3] / "scripts" / "flow_audit.py",  # source checkout
    _HERE.parents[2] / "_bundle" / "scripts" / "flow_audit.py",  # installed wheel
)
# tracked changes against HEAD, then untracked files not ignored (NUL separated, so odd names survive)
_CHANGED = (["git", "diff", "--name-only", "-z", "HEAD"], ["git", "ls-files", "--others", "--exclude-standard", "-z"])
_module: list[ModuleType] = []


class _Failed(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def _script() -> Path | None:
    return next((path for path in _CANDIDATES if path.is_file()), None)


def _flow_audit() -> ModuleType | None:
    """scripts/flow_audit.py as a module (for its own route hints and extractor), or None when it is absent."""
    if _module:
        return _module[0]
    script = _script()
    if script is None:
        return None
    spec = importlib.util.spec_from_file_location("flow_audit", script)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["flow_audit"] = module  # its dataclasses resolve their module through sys.modules
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("flow_audit", None)
        return None
    _module.append(module)
    return module


def _changed_files(clone: Path) -> list[str]:
    names: list[str] = []
    for argv in _CHANGED:
        done = subprocess.run(argv, cwd=clone, capture_output=True, text=True, timeout=10)
        if done.returncode != 0:
            raise OSError(f"{' '.join(argv)} exited {done.returncode}")
        names.extend(name for name in done.stdout.split("\0") if name)
    return names


def _is_route_file(audit: ModuleType, clone: Path, rel: str) -> bool:
    """A file the audit scans that sits on a backend path or defines an endpoint by the audit's own patterns."""
    if Path(rel).suffix.lower() not in audit.TEXT_EXTS:
        return False
    if any(hint in "/" + rel.lower() for hint in audit.BACK_HINTS):
        return True
    try:
        path = clone / rel
        if path.stat().st_size > 1_000_000:
            return False
        return bool(audit.extract_endpoints(audit.read_text(path), rel))
    except OSError:
        return False


def _applies(ctx: PointContext) -> bool:
    if ctx.clone is None:
        return False
    audit = _flow_audit()
    if audit is None:
        return True  # the point itself reports the missing audit as an error
    try:
        names = _changed_files(ctx.clone)
    except (OSError, subprocess.SubprocessError):
        return True  # the point itself reports the git failure as an error
    return any(_is_route_file(audit, ctx.clone, name) for name in names)


async def _export_head(clone: Path, work: Path, base: Path) -> None:
    tar = work / "base.tar"
    done = await proc.run(["git", "archive", "--format=tar", "-o", str(tar), "HEAD"], cwd=clone, timeout=60)
    if done.returncode != 0:
        raise _Failed("git_archive_failed", done.stderr)
    base.mkdir()

    def extract() -> None:
        with tarfile.open(tar) as archive:
            archive.extractall(base, filter="data")

    await asyncio.to_thread(extract)


async def _audit(script: Path, root: Path, work: Path) -> dict:
    """One flow-audit run (exit 0 clean, 1 findings) as a parsed report."""
    argv = sandbox.wrap([sys.executable, str(script), "audit", str(root), "--json"], clone=root, state_dir=work)
    env = sandbox.scrubbed_env(os.environ, home=Path.home())
    try:
        done = await proc.run(argv, timeout=120, cwd=root, env=env)
    except TimeoutError as exc:
        raise _Failed("flow_audit_timeout", str(exc)) from exc
    try:
        report = json.loads(done.stdout)
    except ValueError:
        report = None
    if done.returncode not in (0, 1) or not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise _Failed("flow_audit_failed", f"exit {done.returncode}: {done.stderr[-200:]}")
    return report


def _endpoints(report: dict) -> set[str]:
    return {f"{e['method']} {e['path']}" for e in report.get("endpoints", [])}


def _gaps(report: dict) -> dict[str, str]:
    """gap key (no line number, so a moved handler is not a new gap) -> severity."""
    return {" ".join(filter(None, (i["code"], i["file"], i.get("method"), i.get("path")))): i["severity"]
            for i in report.get("issues", [])}


def _compare(before: dict, after: dict) -> dict:
    base, head = _endpoints(before), _endpoints(after)
    old_gaps, gaps = _gaps(before), _gaps(after)
    new_gaps = sorted(key for key in gaps if key not in old_gaps)
    return {
        "audit": "flow_audit",
        "endpoints_base": len(base),
        "endpoints_head": len(head),
        "added": sorted(head - base)[:LIST_CAP],
        "removed": sorted(base - head)[:LIST_CAP],
        "new_gaps": [f"{gaps[key]} {key}" for key in new_gaps][:LIST_CAP],
        "new_high_gaps": sum(1 for key in new_gaps if gaps[key] == "high"),
    }


def _error(code: str, message: str) -> PointResult:
    return PointResult(NAME, "error", {"error": message[:_ERROR_CAP]}, code)


async def compare_endpoints(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    script = _script()
    if script is None:
        return _error("flow_audit_missing", "scripts/flow_audit.py was not found")
    try:
        with tempfile.TemporaryDirectory(prefix="endpoint-compare-") as tmp:
            work = Path(tmp)
            await _export_head(ctx.clone, work, work / "base")
            before = await _audit(script, work / "base", work)
            after = await _audit(script, ctx.clone, work)
    except sandbox.SandboxUnavailable as exc:
        return _error(sandbox.SandboxUnavailable.reason_code, str(exc))
    except _Failed as exc:
        return _error(exc.code, str(exc))
    return PointResult(NAME, "ok", _compare(before, after))


register(NAME, "verify", compare_endpoints, applies=_applies)
