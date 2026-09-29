"""Read-only intake and planning for a future GitHub issue drain.

This module intentionally stops before every effect boundary.  It never claims
an issue, submits a job, starts a worker, mutates a worktree, or closes
GitHub state.  A successful run is therefore ``PLANNED_NOT_EXECUTED`` with a
non-zero exit code, not a misleading drain completion.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence


INTAKE_SCHEMA = "simplicio.github-drain-intake/v1"
INTENT_SCHEMA = "simplicio.github-drain-intent/v1"
PLAN_SCHEMA = "simplicio.github-drain-plan/v1"
MAP_SCHEMA = "simplicio.github-drain-map/v1"
PLANNER_REVISION = "simplicio.github-drain-intake-planner/1"
PLANNING_RECEIPT_SCHEMA = "simplicio.github-drain-planning-receipt/v1"
INVALID_REQUEST_EXIT = 2
PLANNED_NOT_EXECUTED_EXIT = 3
FAILED_EXIT = 4

_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}
_VALID_ITEM_STATES = {"planned", "remote_closed"}


class DrainIntakeError(RuntimeError):
    def __init__(self, message: str, *, reason_code: str = "drain_intake_error") -> None:
        self.reason_code = str(reason_code)
        super().__init__(str(message))


class DrainIntentError(DrainIntakeError):
    pass


class DrainPlanError(DrainIntakeError):
    pass


class DrainCheckpointError(DrainIntakeError):
    pass


@dataclass(frozen=True)
class DrainIntent:
    raw_request: str
    repository: str
    language: str

    @property
    def owner(self) -> str:
        return self.repository.split("/", 1)[0]

    @property
    def repo(self) -> str:
        return self.repository.split("/", 1)[1]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": INTENT_SCHEMA,
            "raw_request": self.raw_request,
            "repository": self.repository,
            "language": self.language,
            "scope": "all_open_issues",
        }


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


_REPO_URL = re.compile(
    r"https?://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))"
    r"/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?(?=[/?#\s]|$)",
    re.IGNORECASE,
)
_REPO_SLUG = re.compile(
    r"(?<![A-Za-z0-9_.-])(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))"
    r"/(?P<repo>[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?)(?![A-Za-z0-9_.-])"
)


def _remove_git_suffix(value: str) -> str:
    """Python 3.8-compatible equivalent of ``value.removesuffix('.git')``."""
    return value[:-4] if value.endswith(".git") else value


def _repository_candidates(request: str) -> list[str]:
    candidates: list[str] = []
    scrubbed = request
    for match in reversed(list(_REPO_URL.finditer(request))):
        candidates.append(_remove_git_suffix(f"{match.group('owner')}/{match.group('repo')}"))
        start = match.start()
        end = start + len(request[start:].split(maxsplit=1)[0])
        scrubbed = scrubbed[:start] + (" " * (end - start)) + scrubbed[end:]
    candidates.extend(
        _remove_git_suffix(f"{match.group('owner')}/{match.group('repo')}")
        for match in _REPO_SLUG.finditer(scrubbed)
    )
    unique: list[str] = []
    for candidate in candidates:
        canonical = candidate.strip(" /.")
        if canonical and canonical.lower() not in {item.lower() for item in unique}:
            unique.append(canonical)
    return unique


def parse_natural_drain_request(request: str) -> DrainIntent:
    raw = " ".join(str(request or "").strip().split())
    raw = re.sub(r"^/?simplicio-loop\s+", "", raw, flags=re.IGNORECASE)
    if not raw:
        raise DrainIntentError("drain request is empty", reason_code="empty_request")
    folded = _fold(raw)
    pt_verb = re.search(
        r"\b(termin(?:e|ar)|finaliz(?:e|ar)|conclu(?:a|ir)|resolv(?:a|er)|fech(?:e|ar)|dren(?:e|ar))\b",
        folded,
    )
    en_verb = re.search(r"\b(finish|complete|resolve|close|drain)\b", folded)
    if not (pt_verb or en_verb):
        raise DrainIntentError(
            "request must explicitly ask to finish/close/drain work",
            reason_code="completion_intent_missing",
        )
    if not re.search(r"\b(all|todas|todos)\b", folded):
        raise DrainIntentError("request must select all issues", reason_code="all_scope_missing")
    if re.search(r"\b(except|excluding|exclude|exceto|excluindo|menos)\b", folded) or re.search(r"#\d+", raw):
        raise DrainIntentError(
            "an all-issues request cannot contain exclusions or issue-number scope",
            reason_code="scope_narrowed",
        )
    if re.search(r"github\.com/[^/\s]+/[^/\s]+/issues/\d+", folded):
        raise DrainIntentError(
            "a repository drain cannot target one GitHub issue URL",
            reason_code="scope_narrowed",
        )
    if not re.search(r"\b(issues|tickets|tarefas)\b", folded):
        raise DrainIntentError("request must name plural issues", reason_code="issue_scope_missing")
    repositories = _repository_candidates(raw)
    if not repositories:
        raise DrainIntentError(
            "project must be an explicit GitHub owner/repo or repository URL",
            reason_code="repository_missing",
        )
    if len(repositories) != 1:
        raise DrainIntentError(
            "request resolves to more than one GitHub repository",
            reason_code="repository_ambiguous",
        )
    return DrainIntent(
        raw_request=raw,
        repository=repositories[0],
        language="pt-BR" if pt_verb and not en_verb else "en",
    )


_DEPENDENCY_LINE = re.compile(
    r"^(?:[-*]\s+|\d+[.)]\s+)?(?:depends?\s+on|blocked\s+by|requires?|"
    r"depende\s+de|bloquead[oa]\s+por|requer)\s*:?[ \t]*(?P<refs>[^\n]+)$",
    re.IGNORECASE,
)
_DEPENDENCY_HEADINGS = {
    "dependency", "dependencies", "dependencia", "dependencias", "blocked by", "bloqueado por",
}
_DEPENDENCY_NEGATION = re.compile(
    r"\b(?:not|does\s+not|doesn['’]?t|do\s+not|don['’]?t|nao|sem)\b",
    re.IGNORECASE,
)
_CROSS_REPOSITORY_DEPENDENCY = re.compile(
    r"(?:https?://github\.com/)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/issues/|#)\d+",
    re.IGNORECASE,
)
_EXTERNAL_DEPENDENCY_LABEL = re.compile(
    r"\b(?:runtime|simplicio-runtime)\b[^\n]{0,120}",
    re.IGNORECASE,
)
_MIGRATION_MARKER = re.compile(r"SIMPLICIO-MIGRATION:v1", re.IGNORECASE)


def _local_dependency_numbers(value: str) -> set[int]:
    folded = _fold(value)
    if _DEPENDENCY_NEGATION.search(folded):
        return set()
    local_only = _CROSS_REPOSITORY_DEPENDENCY.sub("", value)
    local_only = _EXTERNAL_DEPENDENCY_LABEL.sub("", local_only)
    return {int(number) for number in re.findall(r"#(\d+)", local_only)}


def extract_issue_dependencies(body: str) -> list[int]:
    if _MIGRATION_MARKER.search(str(body or "")):
        return []
    found: set[int] = set()
    heading = False
    fence = False
    comment = False
    for raw_line in str(body or "").splitlines():
        line = raw_line.strip()
        if "<!--" in line:
            comment = True
        if comment:
            if "-->" in line:
                comment = False
            continue
        if line.startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence or line.startswith(">"):
            continue
        folded = _fold(line)
        if line.startswith("#"):
            heading = folded.lstrip("#").strip().rstrip(":") in _DEPENDENCY_HEADINGS
            continue
        match = _DEPENDENCY_LINE.match(folded)
        if match:
            found.update(_local_dependency_numbers(line))
            continue
        if heading and re.match(r"^(?:[-*]\s+|\d+[.)]\s+)", line):
            found.update(_local_dependency_numbers(line))
        elif heading and line:
            heading = False
    return sorted(found)


def classify_issue_risk(title: str, labels: Sequence[str] = ()) -> str:
    material = _fold(" ".join([str(title or ""), *(str(label) for label in labels)]))
    if re.search(r"(?:\bp0\b|critical|critico|security|seguranca|breaking|migration|migracao|data loss)", material):
        return "high"
    if re.search(r"(?:\bp1\b|\bhigh\b|alto risco|concorrencia|concurrency|performance)", material):
        return "medium"
    return "low"


def plan_issue_waves(items: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    item_ids = {str(key) for key in items}
    resolved = {
        str(key) for key, item in items.items() if str(item.get("state")) == "remote_closed"
    }
    remaining = {
        str(key) for key, item in items.items() if str(item.get("state")) == "planned"
    }
    unknown: Dict[str, list[int]] = {}
    for item_id in remaining:
        external_closed = {str(value) for value in items[item_id].get("external_dependencies_closed", ())}
        missing = sorted(
            int(dependency) for dependency in items[item_id].get("dependencies", ())
            if str(dependency) not in item_ids and str(dependency) not in external_closed
        )
        if missing:
            unknown[item_id] = missing
    if unknown:
        raise DrainPlanError(
            "plan contains unresolved external dependencies: %s" % unknown,
            reason_code="dependency_unresolved",
        )
    waves: list[Dict[str, Any]] = []
    while remaining:
        ready = [
            item_id for item_id in remaining
            if {
                str(dependency) for dependency in items[item_id].get("dependencies", ())
                if str(dependency) in item_ids
            } <= resolved
        ]
        if not ready:
            raise DrainPlanError(
                "issue dependency graph is cyclic or blocked", reason_code="dependency_cycle"
            )
        ready.sort(key=lambda item_id: (
            _RISK_ORDER.get(str(items[item_id].get("risk") or "low"), 99), int(item_id)
        ))
        waves.append({
            "index": len(waves) + 1,
            "issues": [int(item_id) for item_id in ready],
            "risk_order": [str(items[item_id].get("risk") or "low") for item_id in ready],
        })
        resolved.update(ready)
        remaining.difference_update(ready)
    return {
        "schema": PLAN_SCHEMA,
        "waves": waves,
        "issue_count": sum(len(wave["issues"]) for wave in waves),
    }


class SourceReader(Protocol):
    provider: str

    def list_ready(self, *, state: str = "open", labels: Sequence[str] = (),
                   assignee: str = "", milestone: str = "") -> Mapping[str, Any]: ...  # pragma: no cover

    def get_details(self, ref: str) -> Mapping[str, Any]: ...  # pragma: no cover

    def requery(self, ref: str, *, comment_id: Optional[int] = None) -> Mapping[str, Any]: ...  # pragma: no cover


class CanonicalMapReader(Protocol):
    def prepare_canonical(self, repository: str, workspace: str) -> Mapping[str, Any]: ...  # pragma: no cover


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _integrity_payload(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Return every checkpoint field except the hash that authenticates the payload.

    Keeping this as an exclusion list binds schema/revision/run identity, timestamps,
    outcome, and future fields by default instead of silently leaving metadata mutable.
    """
    return {str(key): value for key, value in state.items() if str(key) != "integrity_hash"}


def _planner_config() -> Dict[str, Any]:
    return {
        "mode": "read_only_intake",
        "scope": "all_open_issues",
        "source_provider": "github",
        "map_mode": "canonical_only",
        "execution_authorized": False,
        "metering": "unmeasured",
    }


def _run_digest(*, run_id: str, task_digest: str, config_digest: str,
                workspace: str, created_at: str) -> str:
    return _digest({
        "run_id": run_id,
        "task_digest": task_digest,
        "config_digest": config_digest,
        "workspace": workspace,
        "created_at": created_at,
    })


def _derive_acceptance_criteria(snapshot: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Normalize a GitHub issue into a minimal set of acceptance criteria.

    Every planned item is guaranteed at least one criterion so the planning
    phase satisfies the loop's ``no_acceptance_criteria`` gate.  ``origin`` is
    always ``source`` (quoted from the issue itself) or ``derived`` (a
    loop-protocol requirement) -- never ``guessed`` -- so the criteria survive
    ``lint_task_intake``-style origin checks downstream.
    """
    title = str(snapshot.get("title") or "").strip()
    body = str(snapshot.get("body") or "")
    acs: List[Dict[str, str]] = []
    if title:
        acs.append({
            "id": "AC-TITLE",
            "text": "Implementar e verificar: %s" % title,
            "origin": "source",
            "state": "pending",
        })
    in_ac_section = False
    idx = 0
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = _fold(line)
        header = re.sub(r"^#{1,6}\s*|^[*\s_]+", "", low).strip()
        if re.fullmatch(r"(acceptance criteria|crit.rios de aceite|crit.rio de aceite|definition of done|done when|aceite)", header):
            in_ac_section = True
            continue
        if in_ac_section:
            content = re.sub(r"^[-*•]\s*", "", line).strip()
            checkbox = re.match(r"^\[[ xX]\]\s*(.*)$", content)
            if checkbox:
                content = checkbox.group(1).strip()
            elif not re.match(r"^[-*•]\s+", line):
                in_ac_section = False
                continue
            if content:
                idx += 1
                acs.append({
                    "id": "AC-BODY-%d" % idx,
                    "text": content,
                    "origin": "source",
                    "state": "pending",
                })
        elif re.match(r"^\[[ xX]\]\s+", line) or re.match(r"^[-*•]\s+", line):
            content = re.sub(r"^\[[ xX]\]\s*|^[-*•]\s*", "", line).strip()
            if content and re.search(r"\b(ac|aceite|crit.rio)\b", _fold(content)):
                idx += 1
                acs.append({
                    "id": "AC-BODY-%d" % idx,
                    "text": content,
                    "origin": "source",
                    "state": "pending",
                })
    acs.append({
        "id": "AC-EVIDENCE-GATE",
        "text": "Concluir somente com evidência concreta em-turno, watcher match com challenge e receipt de entrega; nunca por texto de modelo.",
        "origin": "derived",
        "state": "pending",
    })
    if not acs:
        acs.append({
            "id": "AC-TITLE",
            "text": "Implementar e verificar o item conforme título/descrição do issue.",
            "origin": "source",
            "state": "pending",
        })
    return acs


def _build_item_planning_receipt(*, item_number: int, source_revision: str,
                                 acceptance_criteria: Sequence[Mapping[str, str]],
                                 planner_revision: str) -> Dict[str, Any]:
    """Deterministic planning receipt binding the frozen plan before mutation.

    Carries the planner revision, the frozen issue ``source_revision``, a hash
    of the derived acceptance criteria, and a self-contained ``receipt_hash``.
    A later mutation (execution) must reference this receipt to satisfy the
    #284/#329 mutation-authority gate.
    """
    ac_hash = _digest({"acceptance_criteria": list(acceptance_criteria)})
    plan_hash = _digest({
        "number": int(item_number),
        "source_revision": str(source_revision),
        "acs": ac_hash,
    })
    receipt_hash = _digest({
        "planner_revision": str(planner_revision),
        "number": int(item_number),
        "source_revision": str(source_revision),
        "acs": ac_hash,
    })
    return {
        "schema": PLANNING_RECEIPT_SCHEMA,
        "planner_revision": str(planner_revision),
        "item_number": int(item_number),
        "source_revision": str(source_revision),
        "acceptance_criteria_hash": ac_hash,
        "plan_hash": plan_hash,
        "receipt_hash": receipt_hash,
        "created_at": _now(),
    }


def _is_pull_request(value: Mapping[str, Any]) -> bool:
    if "pull_request" in value or value.get("is_pull_request") is True:
        return True
    typed = str(value.get("type") or value.get("kind") or "").strip().lower()
    if typed in {"pr", "pull_request", "pull-request"}:
        return True
    return bool(re.search(r"/(?:pull|pulls)/\d+(?:[/?#]|$)", str(value.get("url") or "")))


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
        if os.name != "nt":  # pragma: no branch - platform-specific durability path
            directory = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _checkpoint_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        if os.name == "nt":  # pragma: no cover - Windows transport lane
            import msvcrt
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise DrainCheckpointError(
                    "checkpoint is already locked", reason_code="checkpoint_locked"
                ) from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise DrainCheckpointError(
                    "checkpoint is already locked", reason_code="checkpoint_locked"
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class ReadOnlyLocalGitMap:
    """Canonical Map Service view; no worktree overlay is built by this slice."""

    def __init__(self) -> None:
        from .map_service import MapServiceRegistry
        self.registry = MapServiceRegistry()

    @staticmethod
    def _repo_from_remote(remote: str) -> str:
        value = _remove_git_suffix(str(remote or "").strip())
        if value.startswith("git@") and ":" in value:
            value = value.split(":", 1)[1]
        elif "github.com/" in value:
            value = value.split("github.com/", 1)[1]
        return value.strip("/")

    def prepare_canonical(self, repository: str, workspace: str) -> Dict[str, Any]:
        from .map_service_git import real_tree_snapshot, resolve_repository_identity
        observed = resolve_repository_identity(workspace)
        local_repo = self._repo_from_remote(observed.repository)
        if not local_repo or local_repo.lower() != str(repository).lower():
            raise DrainIntakeError(
                "workspace GitHub remote does not match requested repository",
                reason_code="workspace_repository_mismatch",
            )
        canonical = resolve_repository_identity(observed.canonical_root)
        identity_key = self.registry.register(canonical)
        tree_hash, files = real_tree_snapshot(observed.canonical_root)
        view = self.registry.build_canonical(identity_key, tree_hash=tree_hash, files=files)
        return {
            "schema": MAP_SCHEMA,
            "status": "ready",
            "mode": "canonical",
            "repository": repository,
            "root": observed.canonical_root,
            "tree_hash": view.tree_hash,
            "cache_key": view.cache_key,
            "trace_id": view.trace_id,
            "files": len(view.files),
            "source": "map_service_git",
        }


class GitHubDrainIntake:
    """Build an integrity-checked plan and stop before effect authorization."""

    def __init__(self, *, source: SourceReader, checkpoint: str | Path, workspace: str,
                 map_reader: Optional[CanonicalMapReader] = None) -> None:
        self.source = source
        self.checkpoint = Path(checkpoint).resolve()
        self.workspace = str(Path(workspace).resolve())
        self.map_reader = map_reader
        self.state: Dict[str, Any] = {}

    def _save(self) -> None:
        self.state["updated_at"] = _now()
        self.state["integrity_hash"] = _digest(_integrity_payload(self.state))
        _atomic_json(self.checkpoint, self.state)

    def _load_or_initialize(self, intent: DrainIntent) -> None:
        if not self.checkpoint.exists():
            created_at = _now()
            run_id = uuid.uuid4().hex
            planner_config = _planner_config()
            config_digest = _digest(planner_config)
            task_digest = _digest(intent.to_dict())
            self.state = {
                "schema": INTAKE_SCHEMA,
                "planner_revision": PLANNER_REVISION,
                "planner_config": planner_config,
                "run_identity": {"run_id": run_id, "request_digest": task_digest},
                "digests": {
                    "config": config_digest,
                    "task": task_digest,
                    "run": _run_digest(
                        run_id=run_id,
                        task_digest=task_digest,
                        config_digest=config_digest,
                        workspace=self.workspace,
                        created_at=created_at,
                    ),
                },
                "intent": intent.to_dict(),
                "workspace": self.workspace,
                "created_at": created_at,
                "updated_at": created_at,
                "items": {},
                "external_dependencies": {},
                "plan": {"schema": PLAN_SCHEMA, "waves": [], "issue_count": 0},
                "map": {"canonical": None, "overlays": {}},
                "execution_authorized": False,
                "metering": {
                    "measurement_state": "unmeasured", "tokens": None, "cost_usd": None,
                },
                "outcome": {},
            }
            self._save()
            return
        try:
            payload = json.loads(self.checkpoint.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DrainCheckpointError(
                "checkpoint is not valid JSON", reason_code="checkpoint_invalid"
            ) from exc
        if not isinstance(payload, Mapping) or payload.get("schema") != INTAKE_SCHEMA:
            raise DrainCheckpointError("checkpoint schema is invalid", reason_code="checkpoint_invalid")
        if payload.get("integrity_hash") != _digest(_integrity_payload(payload)):
            raise DrainCheckpointError(
                "checkpoint integrity hash is invalid", reason_code="checkpoint_integrity_failed"
            )
        stored_intent = payload.get("intent") if isinstance(payload.get("intent"), Mapping) else {}
        if str(stored_intent.get("repository") or "").lower() != intent.repository.lower():
            raise DrainCheckpointError(
                "checkpoint belongs to another repository", reason_code="checkpoint_scope_mismatch"
            )
        if str(Path(str(payload.get("workspace") or "")).resolve()) != self.workspace:
            raise DrainCheckpointError(
                "checkpoint belongs to another workspace", reason_code="checkpoint_workspace_mismatch"
            )
        self._validate_checkpoint_metadata(payload, intent)
        items = payload.get("items")
        if not isinstance(items, Mapping):
            raise DrainCheckpointError("checkpoint items are invalid", reason_code="checkpoint_invalid")
        for key, item in items.items():
            if not isinstance(item, Mapping) or str(item.get("number") or "") != str(key):
                raise DrainCheckpointError("checkpoint item identity is invalid", reason_code="checkpoint_invalid")
            if item.get("state") not in _VALID_ITEM_STATES:
                raise DrainCheckpointError("checkpoint item state is invalid", reason_code="checkpoint_invalid")
        self.state = dict(payload)

    def _validate_checkpoint_metadata(
        self, payload: Mapping[str, Any], intent: DrainIntent
    ) -> None:
        planner_config = _planner_config()
        if payload.get("planner_revision") != PLANNER_REVISION:
            raise DrainCheckpointError(
                "checkpoint planner revision is invalid", reason_code="checkpoint_identity_invalid"
            )
        if payload.get("planner_config") != planner_config:
            raise DrainCheckpointError(
                "checkpoint planner configuration is invalid",
                reason_code="checkpoint_identity_invalid",
            )
        created_at = payload.get("created_at")
        run_identity = payload.get("run_identity")
        digests = payload.get("digests")
        if (
            not isinstance(created_at, str) or not created_at
            or not isinstance(run_identity, Mapping)
            or set(run_identity) != {"run_id", "request_digest"}
            or not isinstance(digests, Mapping)
            or set(digests) != {"config", "task", "run"}
        ):
            raise DrainCheckpointError(
                "checkpoint run identity is invalid", reason_code="checkpoint_identity_invalid"
            )
        run_id = run_identity.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise DrainCheckpointError(
                "checkpoint run id is invalid", reason_code="checkpoint_identity_invalid"
            )
        config_digest = _digest(planner_config)
        stored_intent = payload.get("intent")
        if not isinstance(stored_intent, Mapping):
            raise DrainCheckpointError(
                "checkpoint intent is invalid", reason_code="checkpoint_identity_invalid"
            )
        stored_task_digest = _digest(stored_intent)
        expected_run_digest = _run_digest(
            run_id=run_id,
            task_digest=stored_task_digest,
            config_digest=config_digest,
            workspace=str(payload.get("workspace") or ""),
            created_at=created_at,
        )
        if (
            digests.get("config") != config_digest
            or digests.get("task") != stored_task_digest
            or run_identity.get("request_digest") != stored_task_digest
            or digests.get("run") != expected_run_digest
        ):
            raise DrainCheckpointError(
                "checkpoint digests are invalid", reason_code="checkpoint_identity_invalid"
            )
        if stored_task_digest != _digest(intent.to_dict()):
            raise DrainCheckpointError(
                "checkpoint belongs to another request", reason_code="checkpoint_request_mismatch"
            )
        if payload.get("execution_authorized") is not False:
            raise DrainCheckpointError(
                "checkpoint cannot authorize execution", reason_code="checkpoint_invalid"
            )
        expected_metering = {
            "measurement_state": "unmeasured", "tokens": None, "cost_usd": None,
        }
        if payload.get("metering") != expected_metering:
            raise DrainCheckpointError(
                "checkpoint metering must remain explicitly unmeasured",
                reason_code="checkpoint_invalid",
            )
        outcome = payload.get("outcome")
        if not isinstance(outcome, Mapping):
            raise DrainCheckpointError("checkpoint outcome is invalid", reason_code="checkpoint_invalid")
        if outcome:
            expected_exits = {
                "PLANNED_NOT_EXECUTED": PLANNED_NOT_EXECUTED_EXIT,
                "BLOCKED": PLANNED_NOT_EXECUTED_EXIT,
                "FAILED": FAILED_EXIT,
            }
            status = outcome.get("status")
            exit_code = outcome.get("exit_code")
            if (
                status not in expected_exits
                or isinstance(exit_code, bool)
                or exit_code != expected_exits.get(status)
                or outcome.get("execution_authorized") is not False
                or not str(outcome.get("reason_code") or "")
            ):
                raise DrainCheckpointError(
                    "checkpoint outcome is invalid", reason_code="checkpoint_invalid"
                )

    def _listing(self) -> tuple[Dict[str, Any], set[int]]:
        listing = self.source.list_ready(state="open")
        repository = str(self.state["intent"]["repository"])
        if not isinstance(listing, Mapping) or listing.get("provider") != "github":
            raise DrainIntakeError("source listing is not GitHub", reason_code="github_listing_invalid")
        if str(listing.get("repo") or "").lower() != repository.lower():
            raise DrainIntakeError("source listing has wrong repository", reason_code="github_listing_scope_mismatch")
        raw_items = listing.get("items")
        if not isinstance(raw_items, list) or listing.get("count") != len(raw_items):
            raise DrainIntakeError("source listing count is invalid", reason_code="github_listing_invalid")
        numbers: set[int] = set()
        for summary in raw_items:
            number = summary.get("number") if isinstance(summary, Mapping) else None
            if isinstance(summary, Mapping) and _is_pull_request(summary):
                raise DrainIntakeError(
                    "GitHub pull requests are excluded from issue intake",
                    reason_code="github_pull_request_excluded",
                )
            if not isinstance(number, int) or number < 1 or number in numbers:
                raise DrainIntakeError("source listing issue id is invalid", reason_code="github_listing_invalid")
            if str(summary.get("state") or "").lower() != "open":
                raise DrainIntakeError("open listing contains non-open state", reason_code="github_listing_invalid")
            numbers.add(number)
        return dict(listing), numbers

    def _snapshot(self, value: Any, issue: str, *, reason_code: str) -> Dict[str, Any]:
        repository = str(self.state["intent"]["repository"])
        if not isinstance(value, Mapping) or value.get("provider") != "github":
            raise DrainIntakeError("issue snapshot is not GitHub", reason_code=reason_code)
        if str(value.get("repo") or "").lower() != repository.lower():
            raise DrainIntakeError("issue snapshot has wrong repository", reason_code=reason_code)
        if str(value.get("issue") or "") != str(issue):
            raise DrainIntakeError("issue snapshot has wrong id", reason_code=reason_code)
        state = str(value.get("state") or "").lower()
        if _is_pull_request(value) and state != "closed":
            raise DrainIntakeError(
                "GitHub pull requests are excluded from issue intake",
                reason_code="github_pull_request_excluded",
            )
        if state not in {"open", "closed"} or not str(value.get("source_revision") or ""):
            raise DrainIntakeError("issue snapshot state/revision is ambiguous", reason_code=reason_code)
        return dict(value)

    def _read_items(self, listing: Mapping[str, Any], live_open: set[int]) -> None:
        items = self.state["items"]
        for summary in listing["items"]:
            key = str(summary["number"])
            snapshot = self._snapshot(
                self.source.get_details(key), key, reason_code="github_snapshot_invalid"
            )
            if snapshot["state"] != "open":
                raise DrainIntakeError(
                    "open listing disagrees with issue snapshot", reason_code="github_snapshot_state_mismatch"
                )
            previous = items.get(key)
            if isinstance(previous, Mapping) and previous.get("source_revision") != snapshot["source_revision"]:
                raise DrainIntakeError(
                    "frozen issue source changed", reason_code="source_revision_changed"
                )
            dependencies = extract_issue_dependencies(str(snapshot.get("body") or ""))
            if int(key) in dependencies:
                raise DrainPlanError("issue depends on itself", reason_code="dependency_cycle")
            acceptance_criteria = _derive_acceptance_criteria(snapshot)
            planning_receipt = _build_item_planning_receipt(
                item_number=int(key),
                source_revision=str(snapshot["source_revision"]),
                acceptance_criteria=acceptance_criteria,
                planner_revision=PLANNER_REVISION,
            )
            items[key] = {
                "number": int(key),
                "title": str(snapshot.get("title") or ""),
                "url": str(snapshot.get("url") or ""),
                "labels": list(snapshot.get("labels") or []),
                "source_revision": str(snapshot["source_revision"]),
                "observed_at": str(snapshot.get("observed_at") or ""),
                "dependencies": dependencies,
                "external_dependencies_closed": list(
                    (previous or {}).get("external_dependencies_closed", [])
                    if isinstance(previous, Mapping) else []
                ),
                "risk": classify_issue_risk(str(snapshot.get("title") or ""), snapshot.get("labels") or []),
                "state": "planned",
                "acceptance_criteria": acceptance_criteria,
                "planning_receipt": planning_receipt,
            }
        for key, item in list(items.items()):
            if int(key) in live_open or item.get("state") == "remote_closed":
                continue
            current = self._snapshot(
                self.source.requery(key), key, reason_code="github_requery_invalid"
            )
            if current["state"] != "closed":
                raise DrainIntakeError(
                    "previously planned issue disappeared from open listing",
                    reason_code="github_listing_incomplete",
                )
            item["state"] = "remote_closed"
            item["source_revision"] = str(current["source_revision"])

    def _resolve_external_dependencies(self) -> None:
        items = self.state["items"]
        external = self.state["external_dependencies"]
        for key, item in items.items():
            closed = {int(value) for value in item.get("external_dependencies_closed", ())}
            for dependency in item.get("dependencies", ()):
                if str(dependency) in items or int(dependency) in closed:
                    continue
                snapshot = self._snapshot(
                    self.source.requery(str(dependency)),
                    str(dependency),
                    reason_code="github_requery_invalid",
                )
                if snapshot["state"] != "closed":
                    raise DrainPlanError(
                        "dependency #%s for issue #%s is unresolved" % (dependency, key),
                        reason_code="dependency_unresolved",
                    )
                closed.add(int(dependency))
                external[str(dependency)] = {
                    "state": "closed",
                    "source_revision": str(snapshot["source_revision"]),
                    "observed_at": str(snapshot.get("requeried_at") or snapshot.get("observed_at") or ""),
                }
            item["external_dependencies_closed"] = sorted(closed)

    def _outcome(self, status: str, reason_code: str, exit_code: int, **details: Any) -> Dict[str, Any]:
        self.state["execution_authorized"] = False
        self.state["outcome"] = {
            "status": status,
            "reason_code": reason_code,
            "exit_code": int(exit_code),
            "execution_authorized": False,
            "observed_at": _now(),
            **details,
        }
        self._save()
        return dict(self.state)

    def run(self, request: str) -> Dict[str, Any]:
        intent = parse_natural_drain_request(request)
        with _checkpoint_lock(self.checkpoint):
            try:
                self._load_or_initialize(intent)
                if self.state["map"].get("canonical") is None:
                    if self.map_reader is None:
                        self.state["map"]["canonical"] = {
                            "schema": MAP_SCHEMA,
                            "status": "unsupported",
                            "mode": "canonical",
                            "reason_code": "map_adapter_unavailable",
                        }
                    else:
                        receipt = self.map_reader.prepare_canonical(intent.repository, self.workspace)
                        if not isinstance(receipt, Mapping) or receipt.get("mode") != "canonical":
                            raise DrainIntakeError(
                                "canonical map receipt is invalid", reason_code="canonical_map_invalid"
                            )
                        self.state["map"]["canonical"] = dict(receipt)
                    self._save()
                listing, live_open = self._listing()
                self._read_items(listing, live_open)
                self._resolve_external_dependencies()
                self.state["plan"] = plan_issue_waves(self.state["items"])
                self.state["source_observation"] = {
                    "observed_at": str(listing.get("observed_at") or _now()),
                    "open_issues": sorted(live_open),
                    "digest": _digest(sorted(live_open)),
                }
                return self._outcome(
                    "PLANNED_NOT_EXECUTED",
                    "execution_not_authorized_in_intake_slice",
                    PLANNED_NOT_EXECUTED_EXIT,
                    planned_issues=self.state["plan"]["issue_count"],
                )
            except DrainIntakeError as exc:
                if not self.state:
                    raise
                return self._outcome(
                    "BLOCKED", exc.reason_code, PLANNED_NOT_EXECUTED_EXIT, error=str(exc)
                )
            except Exception as exc:
                if not self.state:
                    raise
                return self._outcome(
                    "FAILED", "unexpected_intake_error", FAILED_EXIT,
                    error="%s: %s" % (type(exc).__name__, exc),
                )


__all__ = [
    "FAILED_EXIT", "INTAKE_SCHEMA", "INVALID_REQUEST_EXIT", "MAP_SCHEMA", "PLAN_SCHEMA",
    "PLANNER_REVISION",
    "PLANNED_NOT_EXECUTED_EXIT", "DrainCheckpointError", "DrainIntakeError", "DrainIntent",
    "DrainIntentError", "DrainPlanError", "GitHubDrainIntake", "ReadOnlyLocalGitMap",
    "classify_issue_risk", "extract_issue_dependencies", "parse_natural_drain_request",
    "plan_issue_waves",
]
