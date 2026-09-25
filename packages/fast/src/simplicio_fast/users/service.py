from dataclasses import replace
from datetime import UTC, datetime

from .model import User, normalize_email, validate
from .repository import JsonUserRepository


class UserNotFoundError(LookupError):
    pass


class EmailConflictError(ValueError):
    pass


class UserService:
    def __init__(self, repository: JsonUserRepository) -> None:
        self.repository = repository

    def list(self) -> list[User]:
        return self.repository.list()

    def get(self, user_id: str) -> User:
        for user in self.list():
            if user.id == user_id:
                return user
        raise UserNotFoundError("user not found")

    def create(self, name: str, email: str) -> User:
        users = self.list()
        normalized = normalize_email(email)
        if any(user.email == normalized for user in users):
            raise EmailConflictError("email already exists")
        user = User.create(name, normalized)
        self.repository.save_all([*users, user])
        return user

    def update(
        self,
        user_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
        active: bool | None = None,
    ) -> User:
        users = self.list()
        current = self.get(user_id)
        normalized = normalize_email(email) if email is not None else current.email
        if any(user.email == normalized and user.id != user_id for user in users):
            raise EmailConflictError("email already exists")
        next_name = name.strip() if name is not None else current.name
        validate(next_name, normalized)
        updated = replace(
            current,
            name=next_name,
            email=normalized,
            active=current.active if active is None else active,
            updated_at=datetime.now(UTC).isoformat(),
        )
        self.repository.save_all(
            [updated if user.id == user_id else user for user in users]
        )
        return updated

    def delete(self, user_id: str) -> None:
        users = self.list()
        if not any(user.id == user_id for user in users):
            raise UserNotFoundError("user not found")
        self.repository.save_all([user for user in users if user.id != user_id])
