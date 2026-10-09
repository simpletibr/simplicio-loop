"""What the PR-quality points share: the files a plan touches (judge, sibling_search). Not a point.

The plan is the turbo plan, ``{"operations": [{"path", "find", "replace"}]}`` (a bare list of operations or of
paths works too); once the apply ran, ``turbo_json["applied"]`` lists the paths it wrote.
"""
import posixpath
from typing import Any


def normalize(path: Any) -> str | None:
    """A repo-relative posix path, or None for anything that is empty, absolute or leaves the repo."""
    if not isinstance(path, str) or not path.strip():
        return None
    cleaned = posixpath.normpath(path.strip().replace("\\", "/"))
    if cleaned.startswith("/") or cleaned == ".." or cleaned.startswith("../") or cleaned == ".":
        return None
    return cleaned


def operations(plan: Any) -> list[dict]:
    """The operations of a plan as dicts (a bare path string becomes {"path": ...})."""
    items = plan.get("operations") if isinstance(plan, dict) else plan
    if not isinstance(items, list):
        return []
    ops = [{"path": item} if isinstance(item, str) else item for item in items]
    return [op for op in ops if isinstance(op, dict)]


def plan_paths(plan: Any, turbo_json: dict | None = None) -> list[str]:
    """The planned files, in order and without repeats; the applied list is used when there is no plan."""
    raw = [op.get("path") or op.get("file") for op in operations(plan)]
    if not raw and isinstance(turbo_json, dict) and isinstance(turbo_json.get("applied"), list):
        raw = turbo_json["applied"]
    paths = [normalize(path) for path in raw]
    return list(dict.fromkeys(path for path in paths if path))
