"""GitHub closing words never leave the watcher: closing an issue is a human decision, not a merge side effect (#1644)."""
import re

KEYWORDS = ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved")
_REF = r"(?:[\w.-]+/[\w.-]+#\d+|#\d+|GH-\d+|https?://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/\d+)"
# A plain `owner/repo#N` is tried first and left alone: a repo named `fix` or `closes` is not a keyword, and without this the
# keyword search read `fix#4` inside `acme/fix#4` (rewrite mangled it, then the check refused the text). It starts at the beginning of
# a run of name characters, so the scan stays linear. A real keyword in front (`Closes acme/fix#4`) still takes the whole reference.
_PLAIN = r"(?<![\w.-])[\w.-]+/[\w.-]+#\d+"
_CLOSING = re.compile(rf"(?P<plain>{_PLAIN})|\b(?:{'|'.join(KEYWORDS)})\b\s*(?:[:=]\s*)?(?P<ref>{_REF})", re.IGNORECASE)


def _need_str(text: object) -> None:
    if not isinstance(text, str):
        raise TypeError(f"closing_words needs a str, got {type(text).__name__}")


def rewrite(text: str) -> str:
    """`Closes #1`, `fixed: o/r#2`, `Resolves <issue url>` become `Parte de <ref>`; everything else is untouched."""
    _need_str(text)
    return _CLOSING.sub(lambda m: m.group(0) if m.group("ref") is None else f"Parte de {m.group('ref')}", text)


def has_closing(text: str) -> bool:
    _need_str(text)
    return any(m.group("ref") is not None for m in _CLOSING.finditer(text))


def sanitize(text: str, what: str) -> str:
    """The one door every text of a PR or commit leaves through: rewritten, then refused when a closing word survives."""
    out = rewrite(text)
    if has_closing(out):
        raise RuntimeError(f"{what} still has a GitHub closing word after rewrite: refusing to publish")
    return out
