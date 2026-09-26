"""Generic task intake — one normalizer for any tracker export (issue #1312).

Any LLM or harness should be able to drain issues/tasks from any source
(GitHub, Jira, Linear, ClickUp, GitLab, Azure DevOps, a spreadsheet, or plain
text) without a dedicated adapter per tool. This module is pure and
credential-free: it never calls an authenticated API. When a source needs
auth, the host fetches it with its own connector/CLI and hands this module the
exported JSON/CSV/Markdown, or a plain http(s) URL that already returns JSON
with no auth required.

Normalized item shape (the public contract): ``id``, ``title``, ``body``,
``labels``, ``depends_on``, ``source``, ``url``. Field auto-detection covers
the common export shapes of GitHub, Jira, Linear, ClickUp, GitLab and Azure
DevOps; ``--map key=dotted.path`` overrides any of those seven keys for
anything else. Dependencies are also mined from body text lines such as
``Depends on #12`` / ``blocked by ABC-3``, in addition to each tracker's own
relation/link field when present.

``render_tasks_markdown`` compiles normalized items into the same ``tasks.md``
grammar ``simplicio_loop.task_contract``/``prepare`` already understand — see
``.claude/skills/simplicio-loop/SKILL.md`` "Task file (tasks.md)". This module
writes no files itself and touches no state directory: the CLI
(``simplicio_loop/intake_cli.py``) owns writing ``tasks.md``, and any backlog
freeze goes through ``scripts/task_backlog.py``'s own CLI/API so the state
directory rename (issue #1311, ``.simplicio`` -> ``.simplicio-loop``) sweeps
that path without this module ever hardcoding it.
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

from . import task_contract

SCHEMA = "simplicio.task-intake-item/v1"

NORMALIZED_FIELDS = ("id", "title", "body", "labels", "depends_on", "source", "url")

_JSON_LIST_KEYS = ("items", "issues", "data", "value", "nodes")

_BODY_DEPENDENCY_RE = re.compile(
    r"(?:depends\s+on|depende\s+de|blocked\s+by|bloquead[oa]\s+por)\s*:?\s*(#?[A-Za-z0-9][\w-]*)",
    re.IGNORECASE,
)

_SOURCE_CODE = {
    "github": "GH",
    "jira": "JIRA",
    "linear": "LIN",
    "clickup": "CU",
    "gitlab": "GL",
    "azure": "AZ",
    "csv": "CSV",
    "markdown": "MD",
    "generic": "SRC",
}


class IntakeError(Exception):
    """A typed, fail-closed error for malformed intake input.

    ``reason_code`` is a short machine-stable string a CLI caller can branch
    on; the human message stays in ``str(exc)``.
    """

    def __init__(self, message: str, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


# ---------------------------------------------------------------------------
# Source reading
# ---------------------------------------------------------------------------

def detect_format(text: str, hint: str = "") -> str:
    """Best-effort format sniff: ``hint`` (a filename/extension) wins, then content."""
    lowered = (hint or "").lower()
    if lowered.endswith(".json"):
        return "json"
    if lowered.endswith(".csv"):
        return "csv"
    if lowered.endswith((".md", ".markdown")):
        return "markdown"
    stripped = (text or "").lstrip()
    if stripped[:1] in "[{":
        return "json"
    first_line = stripped.splitlines()[0] if stripped else ""
    if re.match(r"^\s*(system|sistema)\s*:", first_line, re.IGNORECASE):
        return "markdown"
    if "," in first_line and not first_line.lower().startswith(("system:", "sistema:")):
        return "csv"
    return "markdown"


def read_source(from_arg: str, timeout: float = 10.0) -> tuple[str, str]:
    """Read ``--from``: a local path, ``-`` for stdin, or an http(s) URL.

    Returns ``(raw_text, kind)``. A URL is documented to return JSON only, so
    its kind is always ``"json"``; a local path/stdin is sniffed by extension
    then content. No credentials are ever attached to a URL fetch.
    """
    if from_arg == "-":
        import sys

        return sys.stdin.read(), "markdown_or_sniff"
    parsed = urlparse(from_arg)
    if parsed.scheme in ("http", "https"):
        request = urllib.request.Request(from_arg, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise IntakeError(f"could not fetch {from_arg}: {exc}", "fetch_failed") from exc
        return raw, "json"
    try:
        with open(from_arg, encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
    except OSError as exc:
        raise IntakeError(f"could not read {from_arg}: {exc}", "source_not_found") from exc
    return raw, detect_format(raw, hint=from_arg)


def parse_field_map(pairs: Optional[Sequence[str]]) -> Dict[str, str]:
    """Parse repeated ``--map key=dotted.path`` flags into ``{key: path}``."""
    field_map: Dict[str, str] = {}
    for pair in pairs or ():
        if "=" not in pair:
            raise IntakeError(f"invalid --map value (expected key=path): {pair}", "invalid_map")
        key, _, path = pair.partition("=")
        key = key.strip()
        path = path.strip()
        if key not in NORMALIZED_FIELDS:
            raise IntakeError(
                f"invalid --map key {key!r}; must be one of {', '.join(NORMALIZED_FIELDS)}",
                "invalid_map_key",
            )
        if not path:
            raise IntakeError(f"invalid --map value for {key!r}: empty path", "invalid_map")
        field_map[key] = path
    return field_map


# ---------------------------------------------------------------------------
# Dotted-path resolution
# ---------------------------------------------------------------------------

def _resolve_parts(current: Any, parts: Sequence[str]) -> Any:
    if not parts:
        return current
    if not isinstance(current, Mapping):
        return None
    first = parts[0]
    if first.endswith("[]"):
        key = first[:-2]
        lst = current.get(key)
        if not isinstance(lst, list):
            return []
        remainder = parts[1:]
        if not remainder:
            return list(lst)
        return [_resolve_parts(entry, remainder) for entry in lst]
    # Some trackers (Azure DevOps) use a literal dotted key ("System.Title")
    # rather than nested objects, so try the longest literal-key match first
    # before falling back to per-segment nesting.
    for length in range(len(parts), 0, -1):
        segment = parts[:length]
        if any(part.endswith("[]") for part in segment[:-1]):
            continue
        candidate_key = ".".join(segment)
        if candidate_key in current:
            return _resolve_parts(current[candidate_key], parts[length:])
    return None


def _get_path(obj: Any, path: str) -> Any:
    """Resolve a dotted path. ``a.b.c`` walks nested dicts (or a single literal
    key containing dots, e.g. Azure DevOps' ``fields["System.Title"]``);
    ``a[].b`` maps ``b`` over each element of the list at ``a`` and returns
    that list."""
    return _resolve_parts(obj, path.split("."))


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _as_list_of_str(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]
    if isinstance(value, (list, tuple)):
        out: List[str] = []
        for entry in value:
            if entry is None:
                continue
            if isinstance(entry, str):
                if entry.strip():
                    out.append(entry.strip())
            else:
                out.append(_as_str(entry))
        return out
    return [_as_str(value)]


# ---------------------------------------------------------------------------
# Tracker auto-detection
# ---------------------------------------------------------------------------

def detect_tracker(item: Mapping[str, Any]) -> str:
    if "number" in item and "html_url" in item:
        return "github"
    fields = item.get("fields")
    if "key" in item and isinstance(fields, Mapping) and "summary" in fields:
        return "jira"
    if isinstance(fields, Mapping) and "System.Title" in fields:
        return "azure"
    if "identifier" in item and ("relations" in item or "labels" in item):
        return "linear"
    if "iid" in item and "web_url" in item:
        return "gitlab"
    if "tags" in item and "url" in item and ("dependencies" in item or "name" in item):
        return "clickup"
    return "generic"


_TRACKER_FIELD_PATHS = {
    "github": {"id": "number", "title": "title", "body": "body", "labels": "labels[].name", "url": "html_url"},
    "jira": {
        "id": "key",
        "title": "fields.summary",
        "body": "fields.description",
        "labels": "fields.labels",
        "url": "self",
    },
    "linear": {
        "id": "identifier",
        "title": "title",
        "body": "description",
        "labels": "labels.nodes[].name",
        "url": "url",
    },
    "clickup": {"id": "id", "title": "name", "body": "description", "labels": "tags[].name", "url": "url"},
    "gitlab": {"id": "iid", "title": "title", "body": "description", "labels": "labels", "url": "web_url"},
    "azure": {
        "id": "id",
        "title": "fields.System.Title",
        "body": "fields.System.Description",
        "labels": "fields.System.Tags",
        "url": "url",
    },
    "generic": {"id": "id", "title": "title", "body": "body", "labels": "labels", "url": "url"},
}

_GENERIC_FALLBACKS = {
    "id": ("id", "key", "number", "identifier", "iid"),
    "title": ("title", "name", "summary"),
    "body": ("body", "description", "notes"),
    "labels": ("labels", "tags"),
    "url": ("url", "html_url", "web_url", "link"),
}


def _generic_lookup(item: Mapping[str, Any], key: str) -> Any:
    for candidate in _GENERIC_FALLBACKS[key]:
        if candidate in item:
            return item[candidate]
    return None


# ---------------------------------------------------------------------------
# Dependency mining
# ---------------------------------------------------------------------------

def extract_dependencies_from_body(body: str) -> List[str]:
    deps: List[str] = []
    for line in (body or "").splitlines():
        for match in _BODY_DEPENDENCY_RE.finditer(line):
            ref = match.group(1).lstrip("#").strip()
            if ref:
                deps.append(ref)
    return deps


def _jira_relation_dependencies(item: Mapping[str, Any]) -> List[str]:
    fields = item.get("fields")
    if not isinstance(fields, Mapping):
        return []
    deps: List[str] = []
    for link in fields.get("issuelinks") or []:
        if not isinstance(link, Mapping):
            continue
        link_type = link.get("type") or {}
        inward_label = str((link_type or {}).get("inward") or "").lower()
        inward_issue = link.get("inwardIssue")
        if "blocked" in inward_label and isinstance(inward_issue, Mapping):
            key = inward_issue.get("key")
            if key:
                deps.append(str(key))
    return deps


def _linear_relation_dependencies(item: Mapping[str, Any]) -> List[str]:
    relations = item.get("relations")
    nodes: Iterable[Any]
    if isinstance(relations, Mapping):
        nodes = relations.get("nodes") or []
    elif isinstance(relations, list):
        nodes = relations
    else:
        return []
    deps: List[str] = []
    for entry in nodes:
        if not isinstance(entry, Mapping):
            continue
        rel_type = str(entry.get("type") or "").lower()
        if "block" not in rel_type:
            continue
        related = entry.get("relatedIssue")
        identifier = None
        if isinstance(related, Mapping):
            identifier = related.get("identifier")
        identifier = identifier or entry.get("identifier")
        if identifier:
            deps.append(str(identifier))
    return deps


def _clickup_relation_dependencies(item: Mapping[str, Any]) -> List[str]:
    deps: List[str] = []
    for entry in item.get("dependencies") or []:
        if not isinstance(entry, Mapping):
            continue
        dep_id = entry.get("depends_on") or entry.get("task_id")
        if dep_id:
            deps.append(str(dep_id))
    return deps


_TRACKER_RELATION_EXTRACTORS = {
    "jira": _jira_relation_dependencies,
    "linear": _linear_relation_dependencies,
    "clickup": _clickup_relation_dependencies,
}


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_item(
    raw: Mapping[str, Any],
    index: int,
    field_map: Optional[Mapping[str, str]] = None,
    source_label: str = "",
) -> Dict[str, Any]:
    field_map = field_map or {}
    tracker = source_label if source_label in _TRACKER_FIELD_PATHS else detect_tracker(raw)
    paths = _TRACKER_FIELD_PATHS.get(tracker, _TRACKER_FIELD_PATHS["generic"])

    def resolve(key: str, default_path: Optional[str]) -> Any:
        if key in field_map:
            return _get_path(raw, field_map[key])
        if default_path:
            return _get_path(raw, default_path)
        return None

    item_id = resolve("id", paths.get("id"))
    if item_id is None and tracker == "generic":
        item_id = _generic_lookup(raw, "id")
    title = resolve("title", paths.get("title"))
    if title is None and tracker == "generic":
        title = _generic_lookup(raw, "title")
    body = resolve("body", paths.get("body"))
    if body is None and tracker == "generic":
        body = _generic_lookup(raw, "body")
    labels_raw = resolve("labels", paths.get("labels"))
    if labels_raw is None and tracker == "generic":
        labels_raw = _generic_lookup(raw, "labels")
    url = resolve("url", paths.get("url"))
    if url is None and tracker == "generic":
        url = _generic_lookup(raw, "url")

    item_id_str = _as_str(item_id).strip() or f"item-{index}"
    title_str = _as_str(title).strip() or item_id_str
    body_str = _as_str(body)
    labels = _as_list_of_str(labels_raw)

    depends_on: List[str] = []
    if "depends_on" in field_map:
        depends_on.extend(_as_list_of_str(_get_path(raw, field_map["depends_on"])))
    else:
        extractor = _TRACKER_RELATION_EXTRACTORS.get(tracker)
        if extractor:
            depends_on.extend(extractor(raw))
        elif "depends_on" in raw:
            depends_on.extend(_as_list_of_str(raw.get("depends_on")))
    depends_on.extend(extract_dependencies_from_body(body_str))
    depends_on = _dedupe(depends_on)
    depends_on = [dep for dep in depends_on if dep != item_id_str]

    source_value = "source" if "source" not in field_map else _as_str(_get_path(raw, field_map["source"]))
    source_label_out = source_value if source_value != "source" else (tracker if tracker != "generic" else (source_label or "generic"))

    return {
        "id": item_id_str,
        "title": title_str,
        "body": body_str,
        "labels": labels,
        "depends_on": depends_on,
        "source": source_label_out,
        "url": _as_str(url),
    }


def normalize_json(text: str, field_map: Optional[Mapping[str, str]] = None, source_label: str = "") -> List[Dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IntakeError(f"invalid JSON: {exc}", "invalid_json") from exc
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, Mapping):
        raw_items = None
        for key in _JSON_LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                raw_items = value
                break
        if raw_items is None:
            raise IntakeError(
                "JSON object must contain a list under one of: "
                + ", ".join(_JSON_LIST_KEYS),
                "unrecognized_json_shape",
            )
    else:
        raise IntakeError("JSON input must be an array or an object", "unrecognized_json_shape")
    if not raw_items:
        raise IntakeError("JSON input contains no items", "empty_input")
    items = []
    for idx, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, Mapping):
            raise IntakeError(f"item {idx} is not an object", "malformed_item")
        items.append(normalize_item(raw, idx, field_map=field_map, source_label=source_label))
    return items


def normalize_csv(text: str, field_map: Optional[Mapping[str, str]] = None, source_label: str = "csv") -> List[Dict[str, Any]]:
    stripped = (text or "").strip()
    if not stripped:
        raise IntakeError("CSV input is empty", "empty_input")
    reader = csv.DictReader(io.StringIO(text))
    rows = [row for row in reader if any((value or "").strip() for value in row.values())]
    if not rows:
        raise IntakeError("CSV input has a header but no data rows", "empty_input")
    items = []
    for idx, row in enumerate(rows, start=1):
        items.append(normalize_item(row, idx, field_map=field_map, source_label=source_label or "csv"))
    return items


def normalize_markdown(text: str, source_label: str = "markdown") -> List[Dict[str, Any]]:
    if not re.search(r"(?im)^\s*(system|sistema)\s*:", text or ""):
        raise IntakeError(
            "no 'System:'/'Sistema:' task block found in markdown input",
            "no_tasks_parsed",
        )
    chunks = task_contract.split_tasks(text)
    if not chunks:
        raise IntakeError(
            "no 'System:'/'Sistema:' task block found in markdown input",
            "no_tasks_parsed",
        )
    items = []
    for idx, chunk in enumerate(chunks, start=1):
        contract = task_contract.compile_task(chunk)
        identity = contract.get("identity") or {}
        dependencies = (contract.get("dependencies") or {}).get("items") or []
        external_refs = contract.get("external_references") or []
        url = next((ref.get("value") for ref in external_refs if ref.get("kind") == "url"), "")
        title = identity.get("title") or identity.get("feature") or f"Task {idx}"
        item_id = identity.get("id") or f"MD{idx}"
        items.append(
            {
                "id": item_id,
                "title": title,
                "body": contract.get("original_text", chunk),
                "labels": [],
                "depends_on": [str(dep) for dep in dependencies],
                "source": source_label,
                "url": url,
                "_raw_markdown": chunk,
            }
        )
    return items


def normalize(
    text: str,
    kind: str,
    field_map: Optional[Mapping[str, str]] = None,
    source_label: str = "",
) -> List[Dict[str, Any]]:
    """Dispatch to the right normalizer for ``kind`` (``json``/``csv``/``markdown``).

    ``kind == "markdown_or_sniff"`` (stdin with no extension hint) is sniffed
    from the actual content before dispatch.
    """
    resolved_kind = kind
    if kind == "markdown_or_sniff":
        resolved_kind = detect_format(text)
    if resolved_kind == "json":
        return normalize_json(text, field_map=field_map, source_label=source_label)
    if resolved_kind == "csv":
        return normalize_csv(text, field_map=field_map, source_label=source_label or "csv")
    if resolved_kind == "markdown":
        return normalize_markdown(text, source_label=source_label or "markdown")
    raise IntakeError(f"unsupported intake format: {resolved_kind}", "unsupported_format")


# ---------------------------------------------------------------------------
# tasks.md rendering (compiles with simplicio_loop.task_contract / prepare)
# ---------------------------------------------------------------------------

def _derive_then(item: Mapping[str, Any]) -> str:
    for line in (item.get("body") or "").splitlines():
        cleaned = line.strip().lstrip("-* ")
        if cleaned:
            return cleaned[:240]
    return "the change described in the source item is implemented and verified"


def _feature_id(item: Mapping[str, Any], index: int) -> str:
    code = _SOURCE_CODE.get(item.get("source") or "", "SRC")
    return f"{code}-{index}"


def render_tasks_markdown(items: Sequence[Mapping[str, Any]]) -> str:
    """Render normalized items into ``tasks.md`` blocks ``prepare`` compiles.

    A markdown-origin item is passed through verbatim (its own block already
    compiles); every other item gets a synthesized ``System``/``Feature``/
    ``Type`` block with one Acceptance Criteria scenario derived from its
    body, a ``Depends on: task N`` line per dependency resolved to another
    item's position in this same batch, and ``Source: <url>`` under
    Additional Information.
    """
    id_to_index = {item["id"]: idx for idx, item in enumerate(items, start=1) if item.get("id")}
    blocks: List[str] = []
    for index, item in enumerate(items, start=1):
        raw_markdown = item.get("_raw_markdown")
        if raw_markdown:
            blocks.append(raw_markdown.strip())
            continue
        feature_id = _feature_id(item, index)
        title = item.get("title") or feature_id
        lines = [
            "System: intake",
            f"Feature: {feature_id}: {title}",
            "Type: Intake",
            "",
            "1. Acceptance Criteria",
            f"Scenario 1: {title}",
            f"Given the intake item {item.get('id') or feature_id} from {item.get('source') or 'unknown'}",
            "When the described change is implemented",
            f"Then {_derive_then(item)}",
        ]
        dep_lines = []
        for dep in item.get("depends_on") or []:
            target_index = id_to_index.get(dep)
            if target_index and target_index != index:
                dep_lines.append(f"Depends on: task {target_index}")
            else:
                dep_lines.append(f"Depends on: {dep}")
        if dep_lines:
            lines += ["", "6. Dependencies", *dep_lines]
        additional = []
        if item.get("url"):
            additional.append(f"Source: {item['url']}")
        if item.get("labels"):
            additional.append(f"Labels: {', '.join(item['labels'])}")
        if additional:
            lines += ["", "8. Additional Information", *additional]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------------------
# Backlog wiring (freezes through scripts/task_backlog.py's own item schema)
# ---------------------------------------------------------------------------

def build_backlog_items(items: Sequence[Mapping[str, Any]], tasks_md_path: str) -> List[Dict[str, Any]]:
    """Build ``scripts/task_backlog.py --item-file`` rows for ``items``.

    Ids are ``T{n}`` (1-based, in intake order) so ``depends_on`` values line
    up with the ``task N`` labels ``render_tasks_markdown`` writes into
    ``tasks.md``. This module never opens the backlog file itself; the CLI
    hands this list to ``task_backlog.py``'s own ``init --item-file`` so any
    state-directory path lives entirely inside that script.
    """
    id_to_index = {item["id"]: idx for idx, item in enumerate(items, start=1) if item.get("id")}
    out = []
    for index, item in enumerate(items, start=1):
        depends_on = []
        for dep in item.get("depends_on") or []:
            target_index = id_to_index.get(dep)
            if target_index and target_index != index:
                depends_on.append(f"T{target_index}")
        acs = [f"AC1: {_derive_then(item)}"]
        out.append(
            {
                "id": f"T{index}",
                "goal": item.get("title") or item.get("id") or f"Task {index}",
                "acs": acs,
                "depends_on": depends_on,
                "priority": index * 10,
                "plan_files": [tasks_md_path],
            }
        )
    return out
