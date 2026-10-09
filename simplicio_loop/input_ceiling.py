"""Input-token ceiling for loop agents (#1608).

Owner rule: no LLM request made by a loop agent may carry more than 98,000 input tokens. Above that, the agent writes a
checkpoint (a handoff) and a fresh agent continues. The number comes from the price table: up to 100,000 prompt tokens a
request costs the cheap tier, above it the whole request costs five times more.

Three things live here:

* ``resolve_ceiling``: the configured ceiling. Order: env ``SIMPLICIO_AGENT_INPUT_TOKEN_CEILING``, then key
  ``agent_input_token_ceiling`` in ``<repo>/.simplicio-loop/loop.toml``, then 98,000. A bad value raises; it never falls
  back to the default.
* ``estimate_tokens``: a deterministic estimate for hosts that do not report usage. Pure Python, no tokenizer package,
  no network. It is conservative: on the reference samples it is never below 1.15 x the tiktoken ``o200k_base`` count
  (tests/fixtures/input_ceiling_reference.json). Error against non-OpenAI tokenizers (Claude) is UNVERIFIED, which is why
  an estimate is multiplied by SAFETY_PERCENT before it is compared with the ceiling.
* ``check_budget``: the one decision function. It compares the PROJECTED total prompt of the NEXT request with the
  ceiling. The total prompt is new input + cache reads + cache writes, never only the uncached part.

Labels never mix. A projection is MEASURED when its base is the total the provider reported for the last request
(``PromptUsage``); only the addition since then is estimated. It is ESTIMATED when nothing was measured.

Known limits (UNVERIFIED against Claude, whose token counts are not available offline): even with SAFETY_PERCENT the
estimate falls under the tiktoken count for rare Han (0.78 x o200k_base, 0.64 x cl100k_base), Ethiopic (0.75, 0.50) and
mathematical symbols (0.96 x cl100k_base). Text made only of such characters needs a measured count (``PromptUsage``).
Prose and code come out at about 1.3 to 1.6 x the o200k_base count before SAFETY_PERCENT.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DEFAULT_CEILING = 98_000
# Largest context window in use today. A ceiling above it can never trigger, so it is a typing error.
MAX_CEILING = 1_000_000
ENV_NAME = "SIMPLICIO_AGENT_INPUT_TOKEN_CEILING"
TOML_KEY = "agent_input_token_ceiling"

# At or above this share of the ceiling the agent must hand off before it sends the next request.
SOFT_PERCENT = 90
# An estimate is multiplied by this before the comparison: tokenizers differ (UNVERIFIED for Claude).
SAFETY_PERCENT = 120
ESTIMATOR_LABEL = "conservative-v2"

MEASURED = "MEASURED"
ESTIMATED = "ESTIMATED"
OK, HANDOFF, OVER = "ok", "handoff", "over"


class CeilingConfigError(ValueError):
    """The configured ceiling is not an integer from 1 to MAX_CEILING."""

    reason_code = "ceiling_invalid"


class InputCeilingExceeded(Exception):
    """The next request would carry more than the ceiling. It must not be sent."""

    reason_code = "input_ceiling_exceeded"

    def __init__(self, verdict: "BudgetVerdict") -> None:
        super().__init__("next request projects %d tokens, above the ceiling %d (%s)"
                         % (verdict.tokens, verdict.ceiling, verdict.basis))
        self.verdict = verdict


# --- configuration -----------------------------------------------------------------------------------------------------

def _check_ceiling(value: Any, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CEILING:
        raise CeilingConfigError("%s: %r is not an integer from 1 to %d" % (source, value, MAX_CEILING))
    return value


def resolve_ceiling(repo_root: str | Path, environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    if ENV_NAME in env:
        raw = env[ENV_NAME]
        if not re.fullmatch(r"[0-9]{1,7}", raw):
            raise CeilingConfigError("%s: %r is not an integer from 1 to %d" % (ENV_NAME, raw, MAX_CEILING))
        return _check_ceiling(int(raw), ENV_NAME)
    path = Path(repo_root) / ".simplicio-loop" / "loop.toml"
    if not path.is_file():
        return DEFAULT_CEILING
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        raise CeilingConfigError("%s: %s" % (path, exc)) from exc
    if TOML_KEY not in data:
        return DEFAULT_CEILING
    return _check_ceiling(data[TOML_KEY], "%s key %s" % (path, TOML_KEY))


# --- estimator ---------------------------------------------------------------------------------------------------------

# Pieces: ASCII letter/digit runs, whitespace runs, runs of one repeated ASCII punctuation mark, any other character.
_PIECE = re.compile(r"[A-Za-z0-9]+|\s+|(?P<p>[\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e])(?P=p)*|.", re.S)
# Cost in quarter tokens of one non-ASCII character, by UTF-8 length (emoji and joiners are the dearest). Two-byte
# characters from U+0370 up (Greek, Cyrillic, Hebrew, Arabic) cost one whole token: cl100k_base spends about that on Greek.
_NON_ASCII_QUARTERS = {2: 3, 3: 5, 4: 12}
_VOWELS = frozenset("aeiouyAEIOUY")


def _wordlike(piece: str) -> bool:
    """A letters-only run that reads like a word: a quarter vowels at least, no four consonants in a row, and no capital
    inside it unless it is all capitals of five letters or fewer. Random strings fail this about four times in five; real words pass it."""
    if not (piece[1:].islower() or (piece.isupper() and len(piece) <= 5)):
        return False
    vowels = run = 0
    for ch in piece:
        if ch in _VOWELS:
            vowels += 1
            run = 0
        else:
            run += 1
            if run > 3:
                return False
    return vowels * 4 >= len(piece)


def estimate_tokens(text: str) -> int:
    """Deterministic, conservative token estimate. Integer arithmetic only, so the result is the same everywhere."""
    if not isinstance(text, str):
        raise TypeError("estimate_tokens needs str, got %s" % type(text).__name__)
    quarters = 0
    for match in _PIECE.finditer(text):
        piece = match.group()
        size = len(piece)
        first = piece[0]
        if first.isascii() and first.isalnum():
            if piece.isdigit():
                quarters += 4 * ((size + 1) // 2)
            elif piece.isalpha():
                if size <= 2:
                    quarters += 4
                elif size <= 8 and _wordlike(piece):
                    quarters += 4 + max(0, size - 6)   # a word: one token, a quarter more per letter past six
                elif size <= 8:
                    quarters += (28 * size + 9) // 10  # random letters tokenize near 0.55 token per character
                elif _wordlike(piece):
                    quarters += 4 + 2 * (size - 6)
                else:
                    quarters += (28 * size + 9) // 10
            else:
                quarters += 4 * ((9 * size + 9) // 10)  # letters mixed with digits: hashes, ids, base64
        elif first.isspace():
            quarters += 4 * (1 + size // 8) if size > 1 or first == "\n" else 0
        elif match.lastgroup == "p":
            quarters += 4 * (1 + size // 16)
        elif first.isascii():
            # Control characters (0x00-0x1f) are costlier; other ASCII punctuation/symbols are 1 token.
            quarters += 6 if ord(first) < 0x20 else 4
        else:
            nbytes = len(first.encode("utf-8", "surrogatepass"))
            quarters += 4 if nbytes == 2 and ord(first) >= 0x370 else _NON_ASCII_QUARTERS.get(nbytes, 12)
    return (quarters + 3) // 4


# --- measured total prompt and projection ------------------------------------------------------------------------------

def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("%s must be an integer >= 0, got %r" % (name, value))
    return value


@dataclass(frozen=True)
class PromptUsage:
    """What the provider reported for one request. The three counts together are the TOTAL prompt."""

    input_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int

    def __post_init__(self) -> None:
        for name in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            _count(getattr(self, name), name)
        if self.total == 0:
            # A request always carries a prompt. Zero means the host did not know: use Projection.estimated.
            raise ValueError("usage reports an empty prompt (0 tokens); that is not a measurement")

    @property
    def total(self) -> int:
        return self.input_tokens + self.cache_read_input_tokens + self.cache_creation_input_tokens

    @classmethod
    def from_usage(cls, usage: Mapping[str, Any]) -> "PromptUsage":
        """Read the provider ``usage`` object. All three counts must be present: a host that omits the cache counts cannot
        give a MEASURED total and must use ``Projection.estimated``."""
        if not isinstance(usage, Mapping):
            raise ValueError("usage must be a mapping, got %s" % type(usage).__name__)
        names = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        missing = [n for n in names if n not in usage]
        if missing:
            raise ValueError("usage lacks %s" % ", ".join(missing))
        return cls(*(usage[n] for n in names))


def _scaled(text: str) -> int:
    return (estimate_tokens(text) * SAFETY_PERCENT + 99) // 100


@dataclass(frozen=True)
class Projection:
    """Projected total prompt of the NEXT request.

    MEASURED: ``measured_base`` is the last provider total; ``estimated_tokens`` is the safety-scaled estimate of what is
    added since (the assistant reply, tool results, the new message). ESTIMATED: no measured base; ``estimated_tokens``
    is the safety-scaled estimate of the whole prompt.
    """

    tokens: int
    basis: str
    measured_base: int | None
    estimated_tokens: int
    estimator: str

    def __post_init__(self) -> None:
        if self.basis not in (MEASURED, ESTIMATED):
            raise ValueError("basis must be MEASURED or ESTIMATED, got %r" % (self.basis,))
        _count(self.tokens, "tokens")
        _count(self.estimated_tokens, "estimated_tokens")
        if (self.basis == MEASURED) != (self.measured_base is not None):
            raise ValueError("measured_base is required for MEASURED and forbidden for ESTIMATED")
        if self.measured_base is not None:
            _count(self.measured_base, "measured_base")
        if not isinstance(self.estimator, str) or not self.estimator:
            raise ValueError("estimator names the estimate in both bases")
        if self.tokens != (self.measured_base or 0) + self.estimated_tokens:
            raise ValueError("tokens must be measured_base + estimated_tokens")

    @classmethod
    def measured(cls, last: PromptUsage, added_text: str) -> "Projection":
        if not isinstance(last, PromptUsage):
            raise TypeError("last must be a PromptUsage")
        if not isinstance(added_text, str):
            raise TypeError("added_text must be str")
        added = _scaled(added_text)
        return cls(last.total + added, MEASURED, last.total, added, ESTIMATOR_LABEL)

    @classmethod
    def estimated(cls, prompt_text: str) -> "Projection":
        if not isinstance(prompt_text, str):
            raise TypeError("prompt_text must be str")
        whole = _scaled(prompt_text)
        return cls(whole, ESTIMATED, None, whole, ESTIMATOR_LABEL)


# --- the decision ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class BudgetVerdict:
    status: str        # ok | handoff | over
    basis: str         # MEASURED | ESTIMATED, copied from the projection
    tokens: int        # projected total prompt of the next request
    ceiling: int
    soft_limit: int    # tokens at or above this need a handoff
    headroom: int      # ceiling - tokens (negative when over)
    ratio: float       # tokens / ceiling, for display only


def check_budget(projection: Projection, ceiling: int, soft_percent: int = SOFT_PERCENT) -> BudgetVerdict:
    """The only decision function. ``over``: tokens > ceiling, do not send. ``handoff``: tokens >= soft share of the
    ceiling, hand off before sending. ``ok`` otherwise."""
    if not isinstance(projection, Projection):
        raise TypeError("check_budget needs a Projection")
    if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling <= 0:
        raise ValueError("ceiling must be an integer > 0, got %r" % (ceiling,))
    if isinstance(soft_percent, bool) or not isinstance(soft_percent, int) or not 0 < soft_percent < 100:
        raise ValueError("soft_percent must be an integer from 1 to 99, got %r" % (soft_percent,))
    tokens = projection.tokens
    if tokens > ceiling:
        status = OVER
    elif tokens * 100 >= ceiling * soft_percent:
        status = HANDOFF
    else:
        status = OK
    return BudgetVerdict(status, projection.basis, tokens, ceiling, -(-ceiling * soft_percent // 100),
                         ceiling - tokens, tokens / ceiling)


def enforce_budget(projection: Projection, ceiling: int, soft_percent: int = SOFT_PERCENT) -> BudgetVerdict:
    """``check_budget`` that raises ``InputCeilingExceeded`` when the status is ``over``."""
    verdict = check_budget(projection, ceiling, soft_percent)
    if verdict.status == OVER:
        raise InputCeilingExceeded(verdict)
    return verdict
