"""Intake triage and repo/issue opt-in gates (issues #1465, #1434).

This module gates which repos and issues enter the Loop at intake time:
- Repo opt-in: `.simplicio-loop/loop.toml` must exist and have `enabled = true`
- Issue opt-in: `loop:auto` label required (issue #1465)
- Author filter: Author must be OWNER/MEMBER/COLLABORATOR (part of #1434)
- Triage: Classify as "actionable" or "needs_human" (needs clarification)

The module is async-native and credential-free: repo membership checks are done
via `gh api`, and triage is deterministic based on issue title/body/labels.
"""
from __future__ import annotations

import asyncio
import base64
import re
import tomllib
import unicodedata
from typing import Any, Mapping, Optional

CONFIG_PATH = ".simplicio-loop/loop.toml"  # the loop keeps all its files under .simplicio-loop/
REPO_OPTED_IN_TIMEOUT = 5.0  # seconds for gh api calls
TRIAGE_REASON_CODES = ("actionable", "needs_human")


class IntakeGateError(Exception):
    """Typed error from intake gate operations.

    `reason_code` is a machine-stable string; the human message is in str(exc).
    """

    def __init__(self, message: str, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class TriageResult:
    """Deterministic triage verdict for an issue.

    Attributes:
        verdict: "actionable" (can be executed) or "needs_human" (needs clarification)
        reason_code: Machine-stable code (e.g., "epic", "vague_body", "actionable")
        clarifying_question: If verdict is "needs_human", a Portuguese question to post
    """

    def __init__(
        self,
        verdict: str,
        reason_code: str,
        clarifying_question: str = "",
    ) -> None:
        if verdict not in ("actionable", "needs_human"):
            raise ValueError(f"Invalid verdict: {verdict}")
        self.verdict = verdict
        self.reason_code = reason_code
        self.clarifying_question = clarifying_question

    def __repr__(self) -> str:
        return (
            f"TriageResult(verdict={self.verdict!r}, reason_code={self.reason_code!r}, "
            f"has_question={bool(self.clarifying_question)})"
        )


async def repo_config(
    repo: str,
    *,
    cache: Optional[dict[str, Any]] = None,
    run: Optional[Any] = None,
) -> Optional[dict[str, Any]]:
    """Return the parsed `.simplicio-loop/loop.toml` of repo, or None when absent.

    Reads via `gh api repos/{owner}/{repo}/contents/.simplicio-loop/loop.toml`
    to avoid cloning. Uses optional per-tick cache (dict keyed by repo).

    Args:
        repo: GitHub repo in "owner/name" format
        cache: Optional dict to cache results across calls in one tick
        run: Optional `async (*gh_args) -> (returncode, stdout, stderr)` replacing the
            default `gh` subprocess (the watcher routes it through its own process boundary)

    Returns:
        The parsed TOML table, or None if the file does not exist

    Raises:
        IntakeGateError: If repo format is invalid or gh api call fails
    """
    if cache is None:
        cache = {}

    if repo in cache:
        return cache[repo]

    if "/" not in repo:
        raise IntakeGateError(f"Invalid repo format: {repo!r} (expected owner/name)", "invalid_repo")

    owner, name = repo.split("/", 1)
    if not owner or not name:
        raise IntakeGateError(f"Invalid repo format: {repo!r}", "invalid_repo")

    try:
        config = await asyncio.wait_for(
            _fetch_config(owner, name, run),
            timeout=REPO_OPTED_IN_TIMEOUT,
        )
        cache[repo] = config
        return config
    except asyncio.TimeoutError as exc:
        raise IntakeGateError(
            f"Timeout fetching {CONFIG_PATH} for {repo}",
            "repo_check_timeout",
        ) from exc
    except IntakeGateError:
        raise
    except Exception as exc:
        raise IntakeGateError(
            f"Failed to check repo {repo}: {exc}",
            "repo_check_failed",
        ) from exc


async def _run_gh(*args: str) -> tuple[int, bytes, bytes]:
    """Run `gh <args>` and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "gh",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout, stderr


async def _fetch_config(owner: str, name: str, run: Optional[Any] = None) -> Optional[dict[str, Any]]:
    """Fetch and parse .simplicio-loop/loop.toml via gh api.

    Returns None if the file does not exist.
    Raises IntakeGateError on malformed TOML or gh failures.
    """
    runner = run or _run_gh
    returncode, stdout, stderr = await runner(
        "api",
        f"repos/{owner}/{name}/contents/{CONFIG_PATH}",
        "--jq",
        ".content",
    )
    err = stderr.decode("utf-8", errors="replace")
    if returncode != 0:
        if "404" in err or "Not Found" in err:
            return None
        raise IntakeGateError(f"gh api call exited with {returncode}: {err}", "gh_api_error")

    content_b64 = stdout.decode("utf-8", errors="replace").strip()
    if not content_b64 or content_b64 == "null":
        return None

    try:
        return tomllib.loads(base64.b64decode(content_b64).decode("utf-8"))
    except Exception as exc:
        raise IntakeGateError(f"Malformed {CONFIG_PATH}: {exc}", "invalid_toml") from exc


async def repo_opted_in(
    repo: str,
    *,
    cache: Optional[dict[str, Any]] = None,
    run: Optional[Any] = None,
) -> bool:
    """True only if `.simplicio-loop/loop.toml` exists with a literal `enabled = true`.

    Raises IntakeGateError (see repo_config) on invalid repo, timeout, gh
    failure or malformed TOML.
    """
    config = await repo_config(repo, cache=cache, run=run)
    return config is not None and config.get("enabled") is True


def issue_admitted(
    issue: Mapping[str, Any],
    config: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Check if issue has loop:auto label and author is trusted.

    Author must have OWNER, MEMBER, or COLLABORATOR association.

    Args:
        issue: GitHub issue object (must have labels, author_association)
        config: Optional config dict with allowed_authors, etc. (for future extensions)

    Returns:
        True if issue is admitted, False otherwise
    """
    return admission_reason(issue, config) == "admitted"


def admission_reason(
    issue: Mapping[str, Any],
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    """Machine-stable reason code for the issue admission decision.

    Returns "admitted", "missing_label", "author_unknown" or "author_not_allowed".
    A login listed in `config["allowed_authors"]` (loop.toml) is trusted even
    without a trusted association.
    """
    config = config or {}

    labels = issue.get("labels") or []
    label_names = [label.get("name") if isinstance(label, dict) else label for label in labels]
    if "loop:auto" not in label_names:
        return "missing_label"

    user = issue.get("user")
    login = (user.get("login") if isinstance(user, Mapping) else None) or ""
    allowed = {str(a).lower() for a in (config.get("allowed_authors") or [])}
    if login and login.lower() in allowed:
        return "admitted"

    author_assoc = (issue.get("author_association") or "").upper()
    if not author_assoc:
        return "author_unknown"
    if author_assoc in ("OWNER", "MEMBER", "COLLABORATOR"):
        return "admitted"
    return "author_not_allowed"


def _normalize_text(text: str) -> str:
    """Normalize text by removing accents using NFKD decomposition.

    Converts accented characters to their unaccented equivalents.
    E.g., "criterios" from "critérios", "epico" from "épico".
    """
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def triage(issue: Mapping[str, Any]) -> TriageResult:
    """Classify issue as actionable or needs_human (clarification required).

    An issue is deterministically classified based on:
    - Epic detection: title contains "[EPIC]" or has "epic" label
    - Body quality: empty, very short, or no concrete acceptance criteria/files
    - Vagueness indicators: no file paths or code references

    Returns "needs_human" with a Portuguese clarifying question if the issue
    is too vague or incomplete. Otherwise returns "actionable".

    Args:
        issue: GitHub issue object (must have title, body, labels)

    Returns:
        TriageResult with verdict, reason_code, and optional clarifying_question
    """
    title = issue.get("title", "")
    if title:
        title = title.strip()
    body = issue.get("body")
    if body is None:
        body = ""
    else:
        body = body.strip()
    labels = issue.get("labels") or []
    label_names = [label.get("name") if isinstance(label, dict) else label for label in labels]

    # Check for epic (with accent normalization)
    is_epic = "[EPIC]" in title.upper() or "epic" in _normalize_text(" ".join(label_names)).lower()
    if is_epic:
        return TriageResult(
            verdict="needs_human",
            reason_code="epic",
            clarifying_question=(
                "Esta é uma épica ou um item de nível muito alto. "
                "Por favor, divida-a em tarefas menores e concretas, "
                "cada uma com critérios de aceite específicos e arquivos/comportamentos concretos."
            ),
        )

    # Check body quality
    if not body or len(body) < 20:
        return TriageResult(
            verdict="needs_human",
            reason_code="empty_body",
            clarifying_question=(
                "A descrição da issue está muito vaga ou incompleta. "
                "Por favor, forneça: 1. O que precisa ser feito (objetivo); "
                "2. Por quê (contexto); 3. Critérios de aceite específicos; "
                "4. Arquivos ou funções que serão alterados."
            ),
        )

    # Check for acceptance criteria or concrete behavior description
    # Normalize body for accent-insensitive matching
    body_normalized = _normalize_text(body).lower()
    body_lower = body.lower()
    has_concrete_description = (
        ("given" in body_lower and "when" in body_lower and "then" in body_lower)
        or ("dado" in body_normalized and "quando" in body_normalized and "entao" in body_normalized)
        or re.search(r"(acceptance criteria|criterios de acei|scenario|cenario)", body_normalized)
        or re.search(r"(file|arquivo|function|funcao|line|linha).*:", body_normalized)
    )

    if not has_concrete_description:
        # Check for file/code references as an alternative
        has_file_ref = re.search(r"(`[^`]+`|[a-zA-Z_][a-zA-Z0-9_/.\\-]*\.(py|js|ts|java|go|rs|rb))", body)
        if not has_file_ref:
            return TriageResult(
                verdict="needs_human",
                reason_code="vague_body",
                clarifying_question=(
                    "A issue precisa de detalhes concretos para ser executável. "
                    "Por favor, inclua: 1. Critérios de aceite específicos (Dado/Quando/Então); "
                    "2. Quais arquivos serão afetados; 3. Comportamento esperado ou exemplo de entrada/saída."
                ),
            )

    # Issue is actionable
    return TriageResult(
        verdict="actionable",
        reason_code="actionable",
    )


__all__ = [
    "IntakeGateError",
    "TriageResult",
    "repo_config",
    "repo_opted_in",
    "admission_reason",
    "issue_admitted",
    "triage",
]
