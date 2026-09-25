from __future__ import annotations

import json
import os
from pathlib import Path

from .model import User


class JsonUserRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self) -> list[User]:
        if not self.path.exists():
            return []
        return [User(**item) for item in json.loads(self.path.read_text())]

    def save_all(self, users: list[User]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps([user.to_dict() for user in users], indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
