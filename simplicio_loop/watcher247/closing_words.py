"""GitHub closing words never leave the watcher: closing an issue is a human decision, not a merge side effect (#1644)."""
import re

KEYWORDS = ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved")
_REF = r"(?:[\w.-]+/[\w.-]+#\d+|#\d+|GH-\d+|https?://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/\d+)"
_CLOSING = re.compile(rf"\b(?:{'|'.join(KEYWORDS)})\b\s*[:=]?\s*(?P<ref>{_REF})", re.IGNORECASE)


def rewrite(text: str) -> str:
    """`Closes #1`, `fixed: o/r#2`, `Resolves <issue url>` become `Parte de <ref>`; everything else is untouched."""
    return _CLOSING.sub(r"Parte de \g<ref>", text)


def has_closing(text: str) -> bool:
    return _CLOSING.search(text) is not None


def sanitize(text: str, what: str) -> str:
    """The one door every text of a PR or commit leaves through: rewritten, then refused when a closing word survives."""
    out = rewrite(text)
    if has_closing(out):
        raise RuntimeError(f"{what} still has a GitHub closing word after rewrite: refusing to publish")
    return out
