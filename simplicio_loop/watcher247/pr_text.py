"""The PR title the watcher opens: `loop: #N text`, no closing word, cut at a word boundary (#1644)."""
from .closing_words import sanitize

LIMIT = 70


def fit(head: str, text: str, limit: int = LIMIT) -> str:
    """`head text` in at most `limit` characters; a cut lands on a word with "…" counted in the limit.

    `head` is never cut. One word longer than the room is cut hard.
    """
    title = f"{head} {' '.join(text.split())}".rstrip()
    if len(title) <= limit:
        return title
    room = title[: limit - 1]
    if not title[limit - 1].isspace() and room.rfind(" ") > len(head):
        room = room[: room.rfind(" ")]
    return room.rstrip() + "…"


def pr_title(number: int, text: str) -> str:
    """The issue number comes first, so a long title never cuts it."""
    return fit(f"loop: #{number}", sanitize(text, "PR title"))
