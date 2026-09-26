"""Support command surfaces extracted from :mod:`simplicio_loop.cli`."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import shutil
import time
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

from . import drain as _drain

from .ops_ledger import (
    CONTEXT_SCHEMA,
    HANDSHAKE_SCHEMA,
    REQUIRED_CONTEXT_FIELDS,
    EventLedger,
    LedgerError,
    validate_handshake,
)


def drain_cli_failure(schema: str, reason_code: str, reason: str, **extra) -> dict:
    """Return an explicitly unverified drain result for invalid CLI input."""
    payload = {
        "schema": schema,
        "verdict": "CONTINUE",
        "ready": False,
        "reason_code": reason_code,
        "reason": reason,
        "tag": "UNVERIFIED",
    }
    payload.update(extra)
    return payload


def read_drain_snapshot(path: str, failure):
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, failure("snapshot_invalid", "could not read drain snapshot", error=str(exc))
    if not isinstance(payload, dict):
        return None, failure("snapshot_invalid", "drain snapshot must be a JSON object")
    return payload, None


def valid_drain_result(schema: str, payload) -> bool:
    """Check the minimum result envelope before exposing a loaded receipt."""
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        return False
    if payload.get("verdict") not in {"DRAINED", "CONTINUE", "BLOCKED"}:
        return False
    if not isinstance(payload.get("ready"), bool):
        return False
    if payload.get("tag") not in {"MEASURED", "UNVERIFIED"}:
        return False
    return not (payload["ready"] and payload["verdict"] != "DRAINED")


def drain(action: str, snapshot_path: str, receipt_path: str, polls_required: int, *,
          evaluator, persist, load, receipt_error, failure, snapshot_reader, result_validator) -> int:
    """Evaluate, persist, or load a drain receipt and emit exactly one JSON value."""
    if action in {"evaluate", "persist"}:
        if not snapshot_path:
            print(json.dumps(failure("snapshot_required", "--snapshot is required"),
                             ensure_ascii=False, sort_keys=True))
            return 2
        snapshot, error = snapshot_reader(snapshot_path)
        if error is not None:
            print(json.dumps(error, ensure_ascii=False, sort_keys=True))
            return 2
        try:
            result = evaluator(snapshot, polls_required=polls_required)
        except (TypeError, ValueError, KeyError) as exc:
            result = failure("snapshot_invalid", "drain snapshot could not be evaluated", error=str(exc))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 2
        if action == "evaluate":
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if not receipt_path:
            print(json.dumps(failure("receipt_required", "--receipt is required"),
                             ensure_ascii=False, sort_keys=True))
            return 2
        try:
            result = persist(receipt_path, result=result)
        except (receipt_error, OSError, TypeError, ValueError) as exc:
            result = failure("receipt_persist_failed", "could not persist drain receipt", error=str(exc))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 2
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    if action == "load":
        if not receipt_path:
            print(json.dumps(failure("receipt_required", "--receipt is required"),
                             ensure_ascii=False, sort_keys=True))
            return 2
        try:
            result = load(receipt_path)
        except (receipt_error, OSError, TypeError, ValueError) as exc:
            result = failure("receipt_invalid", "could not load drain receipt", error=str(exc))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 2
        if result is None:
            print(json.dumps(failure("receipt_missing", "drain receipt does not exist"),
                             ensure_ascii=False, sort_keys=True))
            return 2
        if not result_validator(result):
            print(json.dumps(failure("receipt_invalid", "drain receipt has an invalid result envelope"),
                             ensure_ascii=False, sort_keys=True))
            return 2
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    print(json.dumps(failure("action_invalid", "unknown drain action"),
                     ensure_ascii=False, sort_keys=True))
    return 2


def _load_handshake(handshake_json: str, handshake_file: str, validator=None, ledger_error=None):
    """Load and validate one optional executor handshake."""
    if validator is None:
        validator = validate_handshake
    if ledger_error is None:
        ledger_error = LedgerError
    if handshake_json and handshake_file:
        raise ValueError("--handshake-json and --handshake-file are mutually exclusive")
    if not handshake_json and not handshake_file:
        return None
    raw = (Path(handshake_file).read_text(encoding="utf-8")
           if handshake_file else handshake_json)
    try:
        return validator(json.loads(raw))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        if isinstance(exc, ledger_error):
            raise
        raise ledger_error("executor handshake JSON must be an object") from exc


def ledger_replay(path: str, compatibility: bool, recover_trailing: bool,
                  handshake_json: str, handshake_file: str, command: str = "replay",
                  handshake_loader=None, event_ledger=None, ledger_error=None,
                  context_schema=None, handshake_schema=None, required_context_fields=None) -> int:
    """Replay and validate a ledger through a deterministic, read-only JSON surface."""
    requested_path = str(path)
    try:
        if handshake_loader is None:
            handshake_loader = _load_handshake
        if event_ledger is None:
            event_ledger = EventLedger
        if ledger_error is None:
            ledger_error = LedgerError
        if context_schema is None:
            context_schema = CONTEXT_SCHEMA
        if handshake_schema is None:
            handshake_schema = HANDSHAKE_SCHEMA
        if required_context_fields is None:
            required_context_fields = REQUIRED_CONTEXT_FIELDS
        handshake = handshake_loader(handshake_json, handshake_file)
        if not compatibility and handshake is None:
            raise ledger_error(
                "strict ledger replay requires --handshake-json or --handshake-file"
            )
        events = event_ledger(path, compatibility=compatibility).replay(
            recover_trailing=recover_trailing
        )
        result = {
            "command": "ledger.%s" % command,
            "compatibility": bool(compatibility),
            "context_schema": context_schema,
            "event_count": len(events),
            "events": events,
            "handshake": handshake,
            "handshake_schema": handshake_schema if handshake is not None else None,
            "ok": True,
            "path": requested_path,
            "required_context": list(required_context_fields),
            "schema": "simplicio.ledger-replay/v1",
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (ledger_error, OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "command": "ledger.%s" % command,
            "compatibility": bool(compatibility),
            "error": {"kind": exc.__class__.__name__, "message": str(exc)},
            "handshake": None,
            "ok": False,
            "path": requested_path,
            "schema": "simplicio.ledger-replay/v1",
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 2

_REPO_COMPONENT = r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9])?"
_REPO_RE = re.compile(rf"^{_REPO_COMPONENT}/{_REPO_COMPONENT}$")
_IMPORT_RECEIPT_SCHEMA = "simplicio.findings-import-receipt/v2"
_MARKER_PREFIX = "simplicio-findings-import:"
_MARKER_STATE_SCHEMA = "simplicio.findings-marker-state/v1"
_MARKER_LEASE_SECONDS = 60.0
_MARKER_WAIT_SECONDS = 60.0
_GH_TIMEOUT_SECONDS = 60.0
_MARKER_LEASE_MARGIN_SECONDS = 5.0


class _MarkerStateError(ValueError):
    pass


def _valid_repo(repo: str):
    candidate = repo.strip().removesuffix(".git")
    return candidate if _REPO_RE.fullmatch(candidate) else None


def _github_repo_from_remote(remote: str):
    remote = remote.strip()
    scp = re.fullmatch(r"git@github\.com:(.+)", remote)
    if scp:
        return _valid_repo(scp.group(1))
    parsed = urlparse(remote)
    if parsed.scheme not in {"git", "https", "ssh"} or parsed.hostname != "github.com":
        return None
    return _valid_repo(parsed.path.strip("/"))


def _source_parent(source: str) -> Path:
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path if path.is_dir() else path.parent


def _git_context(directory: Path):
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or len(lines) != 2:
        return None
    return Path(lines[0]).resolve(), Path(lines[1]).resolve()


def _canonical_file(source: str, root: Path) -> str:
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"finding file is outside repository root: {source}") from exc
    return relative.as_posix().casefold()


def _target_for_source(source: str, repo_map):
    parent = _source_parent(source).resolve()
    mapped = (repo_map or {}).get("repos", repo_map or {})
    for directory in (parent, *parent.parents):
        value = mapped.get(str(directory), mapped.get(directory.as_posix()))
        if value is not None:
            if not isinstance(value, str) or not _valid_repo(value):
                raise ValueError(f"invalid GitHub repository mapping for {directory}")
            context = _git_context(directory)
            root, common = context if context else (directory, directory / ".git")
            return _valid_repo(value), _canonical_file(source, root), common
        context = _git_context(directory)
        if context:
            root, common = context
            try:
                result = subprocess.run(
                    ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
                    capture_output=True, text=True, timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            repo = _github_repo_from_remote(result.stdout) if result.returncode == 0 else None
            if repo:
                return repo, _canonical_file(source, root), common
    return None


def _repo_for_source(source: str, repo_map):
    target = _target_for_source(source, repo_map)
    return target[0] if target else None


def _load_findings_import(path: str):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid findings file: {exc}") from exc
    findings = payload.get("findings") if isinstance(payload, dict) else payload
    if not isinstance(findings, list):
        raise ValueError("findings input must be a JSON array or an object with a findings array")
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise ValueError(f"findings[{index}] must be an object")
        required = {"file": str, "line": int, "summary": str, "failure_scenario": str}
        if any(not isinstance(finding.get(key), kind) for key, kind in required.items()):
            raise ValueError(f"findings[{index}] requires file, line, summary, and failure_scenario")
        if finding["line"] < 1 or any(not finding[key].strip() for key in ("file", "summary", "failure_scenario")):
            raise ValueError(f"findings[{index}] canonical fields must be non-empty and line positive")
        if "verdict" in finding and (not isinstance(finding["verdict"], str) or not finding["verdict"].strip()):
            raise ValueError(f"findings[{index}].verdict must be a non-empty string")
    return findings


def _canonical_finding(finding, canonical_file: str):
    canonical = {key: finding[key] for key in ("line", "summary", "failure_scenario")}
    canonical["file"] = canonical_file
    if "verdict" in finding:
        canonical["verdict"] = finding["verdict"]
    return canonical


def _finding_hash(finding, repo: str, canonical_file=None) -> str:
    canonical = _canonical_finding(finding, canonical_file or str(finding["file"]).replace("\\", "/").casefold())
    text = json.dumps({"repo": repo.casefold(), "finding": canonical}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _marker(finding_hash: str) -> str:
    return _MARKER_PREFIX + finding_hash


def _issue_url(repo: str, url) -> bool:
    return isinstance(url, str) and bool(re.fullmatch(rf"https://github\.com/{re.escape(repo)}/issues/[0-9]+", url))


def _receipt_path(args) -> Path:
    explicit = str(getattr(args, "receipt", "") or "")
    return Path(explicit) if explicit else Path(".simplicio-loop/orchestrator/findings/import-receipt.json")


def _load_import_receipt(path: Path):
    if not path.exists():
        return {"schema": _IMPORT_RECEIPT_SCHEMA, "entries": {}}
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid import receipt JSON: {exc}") from exc
    if not isinstance(receipt, dict) or receipt.get("schema") != _IMPORT_RECEIPT_SCHEMA or not isinstance(receipt.get("entries"), dict):
        raise ValueError("import receipt must be a v2 object with entries")
    for marker, entry in receipt["entries"].items():
        if not isinstance(marker, str) or not marker.startswith(_MARKER_PREFIX) or not isinstance(entry, dict):
            raise ValueError("import receipt entry is invalid")
        repo, finding_hash, url = entry.get("repo"), entry.get("finding_hash"), entry.get("url")
        if marker != _marker(str(finding_hash)) or not isinstance(repo, str) or not _valid_repo(repo) or not _issue_url(repo, url):
            raise ValueError("import receipt entry provenance is invalid")
    return receipt


def _save_import_receipt(path: Path, receipt) -> None:
    _drain._atomic_write_receipt(path, receipt)


def _import_error(code: str, message: str, urls=None):
    return {"error": {"code": code, "message": message}, "urls": dict(urls or {})}


def _marker_state_path(coordination_root: Path, finding_hash: str) -> Path:
    return coordination_root / "simplicio-findings-import-markers" / f"{finding_hash}.json"


def _state_digest(state) -> str:
    payload = {key: value for key, value in state.items() if key != "digest"}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _state_payload(status, repo, finding_hash, owner, fence, created, expires, url=None):
    state = {"schema": _MARKER_STATE_SCHEMA, "status": status, "repo": repo, "finding_hash": finding_hash, "owner": owner, "pid": os.getpid(), "fence": fence, "created": created, "expires": expires}
    if url is not None:
        state["url"] = url
    state["digest"] = _state_digest(state)
    return state


def _read_marker_state(path: Path):
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _MarkerStateError(f"invalid marker state JSON: {exc}") from exc
    required = {"schema", "status", "repo", "finding_hash", "owner", "pid", "fence", "created", "expires", "digest"}
    if not isinstance(value, dict) or not required.issubset(value) or value.get("schema") != _MARKER_STATE_SCHEMA or value.get("digest") != _state_digest(value):
        raise _MarkerStateError("marker state schema or digest is invalid")
    return value


def _active_lease_seconds():
    return max(_MARKER_LEASE_SECONDS, _GH_TIMEOUT_SECONDS + _MARKER_LEASE_MARGIN_SECONDS)


def _claim_marker(path: Path, repo: str, finding_hash: str, owner: str):
    now = time.time()
    with _drain._receipt_lock(path):
        state = _read_marker_state(path)
        if state and state.get("repo") == repo and state.get("finding_hash") == finding_hash:
            if state.get("status") == "resolved" and _issue_url(repo, state.get("url")):
                return "resolved", state
            if state.get("status") == "in_progress" and float(state.get("expires", 0)) > now:
                return "wait", state
        fence = uuid.uuid4().hex
        state = _state_payload("in_progress", repo, finding_hash, owner, fence, now, now + _active_lease_seconds())
        _drain._atomic_write_receipt(path, state)
        return "owner", state


def _finish_marker(path: Path, claim, repo: str, finding_hash: str, url=None):
    with _drain._receipt_lock(path):
        current = _read_marker_state(path)
        if not current or current.get("fence") != claim.get("fence"):
            return False
        now = time.time()
        status = "resolved" if url else "failed"
        expires = now + _MARKER_LEASE_SECONDS if url else now
        state = _state_payload(status, repo, finding_hash, claim["owner"], claim["fence"], claim["created"], expires, url)
        _drain._atomic_write_receipt(path, state)
        return True


def _issue_title(finding, marker):
    return f"[finding] {finding['summary']} [{marker}]"


def _issue_body(finding, marker):
    return f"File: {finding['file']}:{finding['line']}\n\nFailure scenario: {finding['failure_scenario']}\n\n<!-- {marker} -->"


def _run_gh(command):
    executable = shutil.which(command[0])
    if os.name == "nt" and executable and Path(executable).suffix.casefold() in {".cmd", ".bat"}:
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", executable, *command[1:]]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS)
    except OSError as exc:
        if os.name != "nt" or getattr(exc, "winerror", None) != 6:
            raise
        with tempfile.TemporaryDirectory(prefix="simplicio-gh-") as directory:
            stdout_path = Path(directory) / "stdout.txt"
            stderr_path = Path(directory) / "stderr.txt"
            shell_command = subprocess.list2cmdline(command) + f' > "{stdout_path}" 2> "{stderr_path}"'
            completed = subprocess.run(shell_command, shell=True, timeout=_GH_TIMEOUT_SECONDS)
            return subprocess.CompletedProcess(command, completed.returncode, stdout_path.read_text(encoding="utf-8"), stderr_path.read_text(encoding="utf-8"))


def _find_remote_issue(repo: str, finding, labels, marker: str):
    command = ["gh", "issue", "list", "--repo", repo, "--state", "all", "--author", "@me", "--search", f'"{marker}" in:title,body', "--json", "url,title,body,author,labels", "--limit", "1000"]
    try:
        result = _run_gh(command)
        rows = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        rows = None
    if not isinstance(rows, list):
        return False, None
    expected_labels = {label.casefold() for label in labels}
    for row in rows:
        actual_labels = {str(item.get("name", "")).casefold() for item in row.get("labels", [])} if isinstance(row, dict) else set()
        author = row.get("author") if isinstance(row, dict) else None
        creator_ok = not author or bool(author.get("login"))
        if isinstance(row, dict) and row.get("title") == _issue_title(finding, marker) and row.get("body") == _issue_body(finding, marker) and expected_labels == actual_labels and creator_ok and _issue_url(repo, row.get("url")):
            return True, row["url"]
    return True, None


def _create_remote_issue(repo: str, finding, labels, marker: str):
    command = ["gh", "issue", "create", "--repo", repo, "--title", _issue_title(finding, marker), "--body", _issue_body(finding, marker)]
    for label in labels:
        command.extend(("--label", label))
    try:
        result = _run_gh(command)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    urls = [line.strip() for line in result.stdout.splitlines() if _issue_url(repo, line.strip())]
    return urls[-1] if urls else None


def _coordinate_finding(finding, repo: str, labels, coordination_root: Path, canonical_file: str):
    canonical = dict(finding)
    canonical["file"] = canonical_file
    finding_hash = _finding_hash(canonical, repo, canonical_file)
    marker = _marker(finding_hash)
    path = _marker_state_path(coordination_root, finding_hash)
    try:
        reconciled, remote_url = _find_remote_issue(repo, canonical, labels, marker)
        if not reconciled:
            return marker, finding_hash, None, "remote_reconciliation_failed"
        if remote_url:
            return marker, finding_hash, remote_url, None
        owner = f"{os.getpid()}:{uuid.uuid4().hex}"
        claim_kind, claim = _claim_marker(path, repo, finding_hash, owner)
        if claim_kind == "resolved":
            reconciled, verified = _find_remote_issue(repo, canonical, labels, marker)
            return marker, finding_hash, verified if reconciled else None, None if verified else "remote_reconciliation_failed"
        if claim_kind == "owner":
            url = _create_remote_issue(repo, canonical, labels, marker)
            _finish_marker(path, claim, repo, finding_hash, url)
            return marker, finding_hash, url, None if url else "issue_create_failed"
        deadline = time.monotonic() + _MARKER_WAIT_SECONDS
        while time.monotonic() < deadline:
            state = _read_marker_state(path)
            if state and state.get("status") == "resolved" and _issue_url(repo, state.get("url")):
                reconciled, verified = _find_remote_issue(repo, canonical, labels, marker)
                if reconciled and verified:
                    return marker, finding_hash, verified, None
            if not state or state.get("status") == "failed" or float(state.get("expires", 0)) <= time.time():
                return _coordinate_finding(finding, repo, labels, coordination_root, canonical_file)
            time.sleep(0.05)
        return marker, finding_hash, None, "finding_in_progress"
    except _MarkerStateError as exc:
        return marker, finding_hash, None, f"marker_state_corrupt:{exc}"


def _import_findings(args):
    try:
        findings = _load_findings_import(args.path)
        repo_map = json.loads(Path(args.repo_map).read_text(encoding="utf-8")) if args.repo_map else {}
        if not isinstance(repo_map, dict):
            raise ValueError("repo map must be a JSON object")
        labels = list(getattr(args, "label", []) or [])
        if any(not isinstance(label, str) or not label.strip() for label in labels):
            raise ValueError("labels must be non-empty strings")
        targets = []
        for index, finding in enumerate(findings):
            target = _target_for_source(finding["file"], repo_map)
            if not target:
                raise ValueError(f"could not resolve repository for findings[{index}]")
            targets.append(target)
        receipt_path = _receipt_path(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps(_import_error("invalid_import_input", str(exc)), sort_keys=True))
        return 2
    if args.dry_run:
        print(json.dumps({str(i): f"https://github.com/{target[0]}/issues/dry-run-{i}" for i, target in enumerate(targets)}, sort_keys=True))
        return 0
    try:
        with _drain._receipt_lock(receipt_path):
            receipt = _load_import_receipt(receipt_path)
    except (ValueError, _drain.DrainReceiptError) as exc:
        print(json.dumps(_import_error("corrupt_import_receipt", str(exc)), sort_keys=True))
        return 2
    urls = {}
    for index, (finding, target) in enumerate(zip(findings, targets)):
        repo, canonical_file, coordination_root = target
        marker, finding_hash, url, error = _coordinate_finding(finding, repo, labels, coordination_root, canonical_file)
        if error:
            code, _, detail = error.partition(":")
            print(json.dumps(_import_error(code, detail or f"could not import findings[{index}]", urls), sort_keys=True))
            return 1
        receipt["entries"][marker] = {"repo": repo, "finding_hash": finding_hash, "url": url}
        try:
            with _drain._receipt_lock(receipt_path):
                latest = _load_import_receipt(receipt_path)
                latest["entries"].update(receipt["entries"])
                receipt = latest
                _save_import_receipt(receipt_path, receipt)
        except (OSError, ValueError, _drain.DrainReceiptError) as exc:
            urls[str(index)] = url
            print(json.dumps(_import_error("receipt_write_failed", str(exc), urls), sort_keys=True))
            return 1
        urls[str(index)] = url
    print(json.dumps(urls, ensure_ascii=False, sort_keys=True))
    return 0
def findings_command(args) -> int:
    """List, report, import, reconcile, or diagnose continuous findings."""
    from . import finding_report as fr
    from . import finding_router as rt

    cmd = getattr(args, "findings_command", None)
    json_output = bool(getattr(args, "json", False))
    if cmd == "import":
        return _import_findings(args)
    if cmd == "list":
        records = fr.read_findings()
        if json_output:
            print(json.dumps(records, ensure_ascii=False, indent=2))
        else:
            for record in records:
                print("%s [%s] %s:%s confirmed=%s" % (
                    record["ts"], record["severity"], record["stage"],
                    record["finding_id"], record["confirmed"],
                ))
        return 0
    if cmd == "report":
        records = fr.read_findings()
        by_stage = {}
        by_severity = {}
        for record in records:
            by_stage[record["stage"]] = by_stage.get(record["stage"], 0) + 1
            severity = record["severity"]
            by_severity[severity] = by_severity.get(severity, 0) + 1
        payload = {"schema": "simplicio.finding-report-aggregate/v1", "total": len(records),
                   "by_stage": by_stage, "by_severity": by_severity}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if json_output else
              "total=%s by_stage=%s by_severity=%s" % (
                  payload["total"], by_stage, by_severity))
        return 0
    if cmd == "reconcile":
        untracked = rt.untracked_problems()
        blocked = rt.completion_blocked()
        payload = {"schema": "simplicio.finding-reconcile/v1", "untracked_count": len(untracked),
                   "untracked": untracked, "completion_blocked": blocked}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if json_output else
              "untracked_confirmed_findings=%s (completion gate will block if >0)" %
              len(untracked))
        return 1 if blocked else 0
    if cmd == "doctor":
        findings_store = fr._FINDINGS_DIR / "findings.jsonl"
        routes_store = rt.LOCAL_STORE
        findings_present = findings_store.exists()
        routes_present = routes_store.exists()
        payload = {
            "schema": "simplicio.finding-doctor/v1",
            "findings_store_path": str(findings_store),
            "findings_store_present": findings_present,
            "routes_store_path": str(routes_store),
            "routes_store_present": routes_present,
            "store_present": findings_present and routes_present,
            "router_importable": True,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2) if json_output else
              "findings_store_present=%s routes_store_present=%s router_ok=%s" % (
                  findings_present, routes_present, payload["router_importable"]))
        return 0

    payload = {
        "schema": "simplicio.finding-command-error/v1",
        "ok": False,
        "error": {"code": "unknown_findings_command", "message": "unknown findings subcommand", "value": cmd},
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 2
