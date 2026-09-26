"""Deterministic cross-component doctor for the Simplicio ecosystem.

The preflight command predates the ecosystem handshake and reports only whether
the bound operators can run.  This module is the stronger, read-only contract
used before planning: it records the identity, version, entry points, source
SHA, supported schemas and observed capabilities of each component and evaluates
them against an explicit profile.  It never installs or upgrades anything.

Contract: ``simplicio.ecosystem-doctor/v1``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform as platform_module
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:  # Keep wheel installs independent from the checkout-only scripts helper.
    import fcntl
except ImportError:  # pragma: no cover - Windows uses the best-effort append below.
    fcntl = None

SCHEMA = "simplicio.ecosystem-doctor/v1"
HANDSHAKE_SCHEMA = "simplicio.ecosystem-handshake/v1"
MINIMUM_PYTHON = (3, 11)
STATUS_AVAILABLE = "available"
STATUS_MISSING = "missing"
STATUS_DISABLED = "disabled"
STATUS_DEGRADED = "degraded"
STATUS_INCOMPATIBLE = "incompatible"
STATUSES = frozenset({STATUS_AVAILABLE, STATUS_MISSING, STATUS_DISABLED,
                      STATUS_DEGRADED, STATUS_INCOMPATIBLE})

_SEMVER = re.compile(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?(?!\d)")
_SCHEMA = re.compile(r"simplicio[.\w-]+/v\d+(?:\.\d+)?")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_TRUE = frozenset({"1", "true", "yes", "on"})
_SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[=:]\s*)[^\s,;]+")

# Conceptual operator roles (SIMPLICIO_ECOSYSTEM.md / bound-operators skill) are
# not always spelled as literal CLI tokens.  Evidence tokens below prove the
# role from real --help surface without requiring the conceptual label.
CAPABILITY_EVIDENCE: dict[str, tuple[str, ...]] = {
    # Mapper: orient/recall roles vs scan/handoff/ask/inspect verbs.
    "orient": ("orient", "scan", "macro", "map "),
    "recall": ("recall", "handoff", "ask", "inspect"),
    # Dev-cli: execute/validate vs task/edit/claims surface.
    "execute": ("execute", "task", "run", "edit", "mechanical-edit"),
    "deterministic_edit": (
        "deterministic_edit",
        "mechanical-edit",
        "changeset",
        "edit",
    ),
    "validate": ("validate", "verify", "claims", "test"),
    "diagnostics": ("diagnostics", "doctor", "smoke", "status", "inspect"),
    # Runtime control plane.
    "contracts": ("contracts", "schema", "doctor"),
    "events": ("events", "journal", "hbp", "checkpoint"),
}


def _capability_proven(capability: str, help_text: str) -> bool:
    """True when help_text proves a conceptual capability via aliases or the name itself."""
    if not help_text:
        return False
    tokens = CAPABILITY_EVIDENCE.get(capability, (capability,))
    return any(token in help_text for token in tokens)


# These are the ecosystem's public operator identities.  Capability names are
# deliberately the same names documented in SIMPLICIO_ECOSYSTEM.md and are not
# inferred from an arbitrary command's prose.
COMPONENTS: dict[str, dict[str, Any]] = {
    "simplicio-loop": {
        "distribution": "simplicio-loop", "command": "simplicio-loop",
        "version_args": ("--version",), "help_args": ("--help",),
        "capabilities": ("plan", "orient", "run", "doctor"),
        "schemas": ("simplicio.ecosystem-doctor/v1", "simplicio.preflight/v1",
                     "simplicio.run-outcome/v1"),
        "entrypoint_names": ("simplicio-loop", "simplicio-hub"),
    },
    "simplicio-mapper": {
        "distribution": "simplicio-mapper", "command": "simplicio-mapper",
        "version_args": ("--version", "--json"), "help_args": ("--help",),
        "capabilities": ("orient", "recall"),
        "schemas": ("simplicio.context-snapshot/v1", "simplicio.mapper/v1"),
        "entrypoint_names": ("simplicio-mapper",),
    },
    "simplicio-dev-cli": {
        "distribution": "simplicio-cli", "command": "simplicio-dev-cli",
        "version_args": ("--version", "--json"), "help_args": ("--help",),
        "capabilities": ("execute", "deterministic_edit", "validate", "diagnostics"),
        "schemas": ("simplicio.task-contract/v1", "simplicio.dev-cli-event/v1"),
        "entrypoint_names": ("simplicio-dev-cli",),
    },
    "simplicio-fast": {
        "distribution": "simplicio-fast", "command": "simplicio-fast",
        "version_args": ("--version",), "help_args": ("--help",),
        "capabilities": ("build", "understand", "plan", "apply", "doctor"),
        "schemas": ("simplicio.fast.integration-status/v1",),
        "entrypoint_names": ("simplicio-fast",),
    },
    "simplicio-runtime": {
        "distribution": "simplicio-runtime", "command": "simplicio",
        "version_args": ("--version",), "help_args": ("--help",),
        "capabilities": ("execute", "contracts", "events"),
        "schemas": ("simplicio.io/v1", "simplicio.runtime/v1"),
        "entrypoint_names": ("simplicio",),
    },
}

# A profile is data, not hidden policy.  An operator may therefore fail closed
# for full-stack execution while still being a valid standalone installation.
PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    "standalone": {
        "simplicio-loop": {"min_version": "3.38.7", "required": True,
                            "capabilities": ("plan", "orient", "run")},
        "simplicio-mapper": {"min_version": "0.26.10", "required": True,
                              "capabilities": ("orient", "recall")},
        "simplicio-dev-cli": {"min_version": "0.18.6", "required": True,
                               "capabilities": ("execute", "validate")},
        "simplicio-fast": {"min_version": "2.0.22", "required": True,
                            "capabilities": ("understand", "plan")},
        "simplicio-runtime": {"min_version": "3.5.0", "required": False,
                               "capabilities": ("contracts",)},
    },
    "full-stack": {
        "simplicio-loop": {"min_version": "3.38.7", "required": True,
                            "capabilities": ("plan", "orient", "run")},
        "simplicio-mapper": {"min_version": "0.26.10", "required": True,
                              "capabilities": ("orient", "recall")},
        "simplicio-dev-cli": {"min_version": "0.18.6", "required": True,
                               "capabilities": ("execute", "validate")},
        "simplicio-fast": {"min_version": "2.0.22", "required": True,
                            "capabilities": ("understand", "plan", "apply")},
        "simplicio-runtime": {"min_version": "3.5.0", "required": True,
                               "capabilities": ("execute", "contracts")},
    },
}


def _version(value: Any) -> tuple[int, int, int]:
    match = _SEMVER.search(str(value or ""))
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)) if match else (0, 0, 0)


def _version_text(value: Sequence[int]) -> str:
    return ".".join(str(x) for x in value)


def _environment_probe() -> dict[str, Any]:
    python = tuple(int(item) for item in sys.version_info[:3])
    system = platform_module.system() or None
    machine = platform_module.machine() or None
    abi = getattr(sys.implementation, "cache_tag", None)
    reasons = []
    if python < MINIMUM_PYTHON + (0,):
        reasons.append("PYTHON_VERSION_INCOMPATIBLE")
    if not system or not machine:
        reasons.append("PLATFORM_IDENTITY_UNAVAILABLE")
    if not abi:
        reasons.append("PYTHON_ABI_UNAVAILABLE")
    return {
        "status": STATUS_AVAILABLE if not reasons else STATUS_INCOMPATIBLE,
        "reason_codes": reasons or ["verified"],
        "python_version": _version_text(python),
        "minimum_python": _version_text(MINIMUM_PYTHON),
        "platform": system,
        "machine": machine,
        "python_abi": abi,
    }


def _redact(value: Any) -> str:
    """Keep diagnostics useful without copying credential-looking values."""
    return _SECRET.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", str(value or ""))


def _run(argv: Sequence[str], cwd: Path, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(list(argv), cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout, env=dict(os.environ), check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(list(argv), 127, "", str(exc))


def _git_sha(root: Path) -> str | None:
    result = _run(("git", "-C", str(root), "rev-parse", "HEAD"), root)
    value = result.stdout.strip()
    return value if _SHA.match(value) else None


def _submodule_shas(root: Path) -> dict[str, str]:
    result = _run(("git", "-C", str(root), "submodule", "status", "--recursive"), root)
    rows: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"[ +-]?([0-9a-f]{40})\s+([^ ]+)", line.strip())
        if match:
            rows[match.group(2)] = match.group(1)
    return rows


def _component_sha(component: str, root: Path, submodules: Mapping[str, str],
                   distribution_path: str | None = None) -> tuple[str | None, str]:
    """Return an evidence-backed component SHA and its source.

    The Loop checkout SHA must never be copied onto an independently installed
    mapper/CLI/Fast/runtime package.  Only a matching submodule or a git checkout
    rooted at the component's path is accepted; wheels report ``unavailable``.
    """
    if component == "simplicio-loop":
        sha = _git_sha(root)
        return (sha, "checkout" if sha else "unavailable")
    names = (component, "vendor/" + component, "deps/" + component)
    for name in names:
        if name in submodules:
            return submodules[name], "submodule"
    candidates = [root / component, root / "vendor" / component, root / "deps" / component]
    if distribution_path:
        candidates.append(Path(distribution_path))
    for candidate in candidates:
        if candidate.is_dir():
            sha = _git_sha(candidate)
            if sha:
                return sha, "checkout"
    return None, "unavailable"


def _distribution(distribution: str) -> dict[str, Any]:
    try:
        dist = importlib.metadata.distribution(distribution)
    except importlib.metadata.PackageNotFoundError:
        # A source checkout is not necessarily installed as a wheel.  The Loop
        # package has a documented fallback literal for that case; reporting it
        # keeps checkout/wheel/mixed installs on the same contract.
        if distribution == "simplicio-loop":
            try:
                from . import __version__
                return {"installed": True, "version": __version__,
                        "path": str(Path(__file__).resolve().parent),
                        "entrypoints": ["simplicio-loop", "simplicio-hub"]}
            except Exception:
                pass
        return {"installed": False, "version": None, "path": None, "entrypoints": []}
    entrypoints = sorted(ep.name for ep in dist.entry_points if ep.group == "console_scripts")
    try:
        path = str(Path(dist.locate_file("")).resolve())
    except OSError:
        path = None
    return {"installed": True, "version": dist.version, "path": path, "entrypoints": entrypoints}


def _disabled(component: str, disabled: Iterable[str]) -> bool:
    env_name = "SIMPLICIO_%s_DISABLED" % re.sub(r"[^A-Z0-9]", "_", component.upper())
    return component in set(disabled) or os.environ.get(env_name, "").lower() in _TRUE


def _probe_component(component: str, spec: Mapping[str, Any], root: Path,
                     minimum: Mapping[str, Any], *, disabled: Iterable[str] = ()) -> dict[str, Any]:
    distribution = _distribution(str(spec["distribution"]))
    command = str(spec["command"])
    executable = shutil.which(command)
    submodules = _submodule_shas(root)
    component_sha, sha_source = _component_sha(component, root, submodules,
                                               distribution.get("path"))
    required_caps = list(minimum.get("capabilities", ()))
    if _disabled(component, disabled):
        return {"name": component, "status": STATUS_DISABLED, "required": bool(minimum.get("required")),
                "command": command, "path": executable, "distribution": spec["distribution"],
                "version": distribution.get("version"), "minimum_version": minimum["min_version"],
                "entrypoints": distribution.get("entrypoints", []), "capabilities": [],
                "required_capabilities": required_caps, "missing_capabilities": required_caps,
                "supported_schemas": list(spec.get("schemas", ())), "git_sha": component_sha,
                "sha_source": sha_source, "submodule_shas": submodules, "reason_code": "disabled",
                "remediation": "unset %s or remove it from --disable" %
                ("SIMPLICIO_%s_DISABLED" % re.sub(r"[^A-Z0-9]", "_", component.upper()))}

    metadata_version = str(distribution.get("version") or "")
    version_text = metadata_version
    help_text = ""
    returncode = 0
    probe_error = ""
    if executable:
        version_result = _run((executable, *spec["version_args"]), root, timeout=60)
        help_result = _run((executable, *spec["help_args"]), root, timeout=60)
        # Prefer clean stdout from a successful --version. Never parse stderr
        # tracebacks as versions (they contain host Python paths like 3.14).
        stdout_version = (version_result.stdout or "").strip()
        if version_result.returncode == 0 and stdout_version:
            version_text = stdout_version
        elif metadata_version:
            version_text = metadata_version
        else:
            version_text = stdout_version or (version_result.stderr or "").strip() or version_text
        help_text = (
            (version_result.stdout or "")
            + "\n"
            + (help_result.stdout or "")
            + "\n"
            + (help_result.stderr or "")
        )
        # Help is the capability surface; version may come from package metadata
        # when the launcher is temporarily broken under mixed installs.
        help_ok = help_result.returncode == 0
        version_ok_probe = version_result.returncode == 0 or bool(metadata_version)
        returncode = 0 if help_ok and version_ok_probe else 1
        probe_error = _redact((version_result.stderr or help_result.stderr or "").strip())

    parsed = _version(version_text)
    # If CLI stdout was a non-version banner but package metadata is present,
    # trust metadata for the floor check (still expose CLI text when useful).
    if metadata_version and parsed < _version(metadata_version):
        meta_parsed = _version(metadata_version)
        if meta_parsed != (0, 0, 0):
            parsed = meta_parsed
            version_text = metadata_version
    provided_caps = set(spec.get("capabilities", ()))
    # A real operator can advertise a subset in --help; static package contracts
    # remain the lower-bound source of truth for checkout/wheel parity.
    # Conceptual roles (e.g. mapper ``recall``) may be proven by CLI synonyms
    # (handoff/ask/inspect) — see CAPABILITY_EVIDENCE.
    advertised = {
        cap
        for cap in provided_caps
        if (not help_text) or _capability_proven(cap, help_text)
    }
    # The installed Loop wheel exposes these capabilities through its Python
    # API; its launcher intentionally has no ``--version``/capability command.
    # Use package metadata for that one component, while external operators must
    # prove their surface through the resolved executable.
    if component == "simplicio-loop" and distribution.get("installed"):
        advertised = set(provided_caps)
        if returncode != 0:
            returncode = 0
    if help_text and component != "simplicio-loop":
        advertised |= {cap for cap in provided_caps if _capability_proven(cap, help_text)}
    if help_text:
        schemas = sorted(set(spec.get("schemas", ())) | set(_SCHEMA.findall(help_text)))
    else:
        schemas = sorted(spec.get("schemas", ()))
    missing_caps = sorted(set(required_caps) - advertised)
    version_ok = parsed >= _version(minimum["min_version"]) and parsed != (0, 0, 0)
    identity_ok = bool(executable or distribution.get("installed") or component == "simplicio-loop")
    available = identity_ok and version_ok and not missing_caps and (not executable or returncode == 0)
    if not identity_ok:
        status, reason = STATUS_MISSING, "command_and_distribution_not_found"
    elif not version_ok or (executable and returncode != 0) or missing_caps:
        status, reason = STATUS_INCOMPATIBLE, "version_or_capability_mismatch"
    elif distribution.get("installed") and not executable and component != "simplicio-loop":
        status, reason = STATUS_DEGRADED, "distribution_installed_but_entrypoint_missing"
    else:
        status, reason = STATUS_AVAILABLE, "verified"
    remediation = _remediation(component, status, reason, minimum["min_version"], missing_caps)
    return {"name": component, "status": status, "required": bool(minimum.get("required")),
            "command": command, "path": executable, "distribution": spec["distribution"],
            "version": version_text or None, "parsed_version": _version_text(parsed),
            "minimum_version": minimum["min_version"], "entrypoints": distribution.get("entrypoints", []),
            "capabilities": sorted(advertised), "required_capabilities": required_caps,
            "missing_capabilities": missing_caps, "supported_schemas": schemas,
            "git_sha": component_sha, "sha_source": sha_source, "submodule_shas": submodules,
            "returncode": returncode, "probe_error": probe_error,
            "reason_code": reason, "remediation": remediation,
            "observed": {"package_installed": bool(distribution.get("installed")),
                          "executable_resolved": bool(executable)}}


def _remediation(component: str, status: str, reason: str, minimum: str,
                 missing: Sequence[str]) -> str | None:
    if status == STATUS_MISSING:
        return "install %s>=%s; rerun `simplicio-ecosystem-doctor --json`" % (component, minimum)
    if status == STATUS_DISABLED:
        return "enable %s explicitly, then rerun the doctor" % component
    if status == STATUS_INCOMPATIBLE:
        detail = ("; missing capabilities: " + ", ".join(missing)) if missing else ""
        return "upgrade %s to >=%s%s; rerun the doctor (no automatic upgrade)" % (component, minimum, detail)
    if status == STATUS_DEGRADED:
        return "repair the %s entrypoint or reinstall the same pinned distribution; rerun the doctor" % component
    return None


def _handshake_digest(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _append_journal_line(target: Path, line: str) -> bool:
    """Append atomically in a wheel install, or reuse the checkout lock helper."""
    try:
        scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
        if (scripts_dir / "_locked_append.py").is_file():
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from _locked_append import locked_append_line
            return bool(locked_append_line(str(target), line))
    except (ImportError, OSError, TypeError, ValueError):
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(target) + ".lock")
    try:
        with lock_path.open("a+") as lock:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                with target.open("a", encoding="utf-8") as output:
                    output.write(line if line.endswith("\n") else line + "\n")
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                if fcntl is not None:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return True
    except OSError:
        return False


def persist_handshake(report: Mapping[str, Any], repo: Path, *, journal_path: Path | None = None) -> dict[str, Any]:
    """Append the handshake before planning, using the loop's cross-process lock."""
    target = journal_path or repo / ".simplicio-loop" / "orchestrator" / "loop" / "journal.jsonl"
    record = {"schema": HANDSHAKE_SCHEMA, "event": "ecosystem_handshake",
              "phase": "pre_planning", "recorded_at": report.get("checked_at"),
              "doctor_schema": SCHEMA, "status": report.get("status"),
              "profile": report.get("profile"), "handshake_sha": _handshake_digest(report),
              "environment": report.get("environment"),
              "components": report.get("components", [])}
    written = _append_journal_line(target, json.dumps(record, ensure_ascii=False, sort_keys=True))
    return {"path": str(target), "written": written, "record": record}


def build_report(repo: str | Path = ".", *, profile: str = "standalone",
                 disabled: Iterable[str] = (), persist: bool = True) -> dict[str, Any]:
    root = Path(repo).resolve()
    if profile not in PROFILES:
        raise ValueError("unknown profile %r; choose one of %s" % (profile, ", ".join(sorted(PROFILES))))
    components = [_probe_component(name, COMPONENTS[name], root, PROFILES[profile][name], disabled=disabled)
                  for name in COMPONENTS]
    environment = _environment_probe()
    required = [item for item in components if item["required"]]
    blockers = [item["name"] for item in required if item["status"] != STATUS_AVAILABLE]
    if environment["status"] != STATUS_AVAILABLE:
        blockers.insert(0, "environment")
    degraded = [item["name"] for item in components if item["status"] == STATUS_DEGRADED]
    status = "BLOCKED" if blockers else ("DEGRADED" if degraded else "READY")
    optional = [item["name"] for item in components if not item["required"]]
    fallbacks = []
    if "simplicio-fast" in optional and next(item for item in components if item["name"] == "simplicio-fast")["status"] != STATUS_AVAILABLE:
        fallbacks.append({"feature": "context_acceleration", "provider": "simplicio-mapper",
                          "when": "simplicio-fast unavailable or incompatible"})
    if "simplicio-runtime" in optional and next(item for item in components if item["name"] == "simplicio-runtime")["status"] != STATUS_AVAILABLE:
        fallbacks.append({"feature": "runtime_integration", "provider": "local_loop",
                          "when": "simplicio-runtime unavailable or incompatible"})
    report: dict[str, Any] = {
        "schema": SCHEMA, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": str(root), "profile": profile, "status": status, "ready": not blockers,
        "blockers": blockers, "degraded": degraded, "environment": environment,
        "components": components,
        "policy": {"automatic_upgrade": False, "required_components": [x["name"] for x in required],
                    "optional_components": optional, "fallbacks": fallbacks},
    }
    report["handshake"] = persist_handshake(report, root) if persist else {"written": False, "path": None}
    return report


def render_human(report: Mapping[str, Any]) -> str:
    lines = ["simplicio ecosystem doctor: %s" % report.get("status"),
             "profile: %s" % report.get("profile"), ""]
    environment = report.get("environment") or {}
    lines.append(
        "environment: python=%s (min=%s) platform=%s/%s abi=%s status=%s"
        % (
            environment.get("python_version") or "unknown",
            environment.get("minimum_python") or "unknown",
            environment.get("platform") or "unknown",
            environment.get("machine") or "unknown",
            environment.get("python_abi") or "unknown",
            environment.get("status") or "unknown",
        )
    )
    for item in report.get("components", []):
        marker = {STATUS_AVAILABLE: "✓", STATUS_MISSING: "✗", STATUS_DISABLED: "○",
                  STATUS_DEGRADED: "△", STATUS_INCOMPATIBLE: "!"}.get(item.get("status"), "?")
        sha = item.get("git_sha") or "unavailable"
        lines.append("%s %-21s %-13s version=%s min=%s sha=%s" %
                     (marker, item.get("name"), item.get("status"), item.get("version") or "unknown",
                      item.get("minimum_version"), sha))
        if item.get("missing_capabilities"):
            lines.append("  missing capabilities: %s" % ", ".join(item["missing_capabilities"]))
        if item.get("remediation"):
            lines.append("  remediation: %s" % item["remediation"])
    handshake = report.get("handshake") or {}
    lines.append("")
    lines.append("handshake journal: %s (%s)" % (handshake.get("path") or "disabled",
                                                 "persisted" if handshake.get("written") else "not persisted"))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio ecosystem-doctor")
    parser.add_argument("--repo", default=".", help="checkout root (default: current directory)")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="standalone")
    parser.add_argument("--disable", action="append", default=[], metavar="COMPONENT",
                        help="mark one component disabled without probing it (repeatable)")
    parser.add_argument("--no-persist", action="store_true", help="do not append the handshake journal record")
    parser.add_argument("--json", action="store_true", help="emit the versioned JSON receipt")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.repo, profile=args.profile, disabled=args.disable, persist=not args.no_persist)
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(render_human(report))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
