from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class User:
    id: str
    name: str
    email: str
    active: bool
    created_at: str
    updated_at: str

    @classmethod
    def create(cls, name: str, email: str) -> "User":
        validate(name, email)
        now = datetime.now(UTC).isoformat()
        return cls(str(uuid4()), name.strip(), normalize_email(email), True, now, now)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate(name: str, email: str) -> None:
    if not name.strip():
        raise ValueError("name is required")
    if "@" not in email:
        raise ValueError("email is invalid")
