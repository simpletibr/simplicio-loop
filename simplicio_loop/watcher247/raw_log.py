"""The planner's raw reply, kept beside the step log: redacted first, cut after (a secret cut in half would escape the pattern)."""
from pathlib import Path

from ..dashboard.runs import redact_text

RAW_LOG_CHARS = 20_000


def clip(raw: str | None, reason: str = "") -> str:
    if raw is None:
        return f"[sem resposta do planejador: {reason or 'desconhecido'}]\n"
    text = redact_text(raw)
    if len(text) <= RAW_LOG_CHARS:
        return text
    return f"{text[:RAW_LOG_CHARS]}\n[truncado: {len(text) - RAW_LOG_CHARS} caracteres]\n"


def write(path: Path, raw: str | None, reason: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(clip(raw, reason), encoding="utf-8")
