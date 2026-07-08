"""Memory-efficient models used while building mapper artifacts."""

from __future__ import annotations


class ProjectFile:
    """Parsed project file metadata.

    This object is used internally during mapping and converted to a plain dict
    only when the final JSON artifact is assembled.
    """

    __slots__ = (
        "path",
        "language",
        "size_bytes",
        "last_modified",
        "file_hash",
        "git_status",
        "roles",
        "imports",
        "exports",
        "importance",
        "text_preview",
        "bh_address",
        "agent_id",
    )

    def __init__(
        self,
        path: str,
        language: str,
        size_bytes: int,
        last_modified: str,
        file_hash: str,
        git_status: str,
        roles: list[str],
        imports: list[str],
        exports: list[str],
        importance: float = 0.0,
        text_preview: str = "",
        bh_address: str = "",
        agent_id: str = "",
    ) -> None:
        self.path = path
        self.language = language
        self.size_bytes = size_bytes
        self.last_modified = last_modified
        self.file_hash = file_hash
        self.git_status = git_status
        self.roles = roles
        self.imports = imports
        self.exports = exports
        self.importance = importance
        self.text_preview = text_preview
        self.bh_address = bh_address
        self.agent_id = agent_id

    def to_dict(self) -> dict:
        d: dict = {
            "path": self.path,
            "language": self.language,
            "size_bytes": self.size_bytes,
            "last_modified": self.last_modified,
            "file_hash": self.file_hash,
            "git_status": self.git_status,
            "roles": self.roles,
            "imports": self.imports,
            "exports": self.exports,
            "importance": self.importance,
        }
        if self.bh_address:
            d["bh_address"] = self.bh_address
        if self.agent_id:
            d["agent_id"] = self.agent_id
        return d


class CodeEntity:
    """High-level entity extracted from file names and symbols."""

    __slots__ = ("name", "score")

    def __init__(self, name: str, score: int) -> None:
        self.name = name
        self.score = score

    def to_dict(self) -> dict:
        return {"name": self.name, "score": self.score}


class PrecedentItem:
    """Reusable code precedent included in precedent-index.json."""

    __slots__ = (
        "id",
        "path",
        "line",
        "rank",
        "language",
        "change_type",
        "tags",
        "summary",
        "snippet",
    )

    def __init__(
        self,
        id: str,
        path: str,
        line: int,
        language: str,
        change_type: str,
        tags: list[str],
        summary: str,
        snippet: str,
        rank: int = 1,
    ) -> None:
        self.id = id
        self.path = path
        self.line = line
        self.rank = rank
        self.language = language
        self.change_type = change_type
        self.tags = tags
        self.summary = summary
        self.snippet = snippet

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "line": self.line,
            "rank": self.rank,
            "language": self.language,
            "change_type": self.change_type,
            "tags": self.tags,
            "summary": self.summary,
            "snippet": self.snippet,
        }
