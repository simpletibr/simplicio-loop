"""Intake triage and repo/issue opt-in gates (issues #1465, #1434).

This module gates which repos and issues enter the Loop at intake time:
- Repo opt-in: `.simplicio/loop.toml` must exist and have `enabled = true`
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


async def repo_opted_in(
    repo: str,
    *,
    cache: Optional[dict[str, Any]] = None,
) -> bool:
    """Check if repo has `.simplicio/loop.toml` with enabled=true.

    Reads via `gh api repos/{owner}/{repo}/contents/.simplicio/loop.toml`
    to avoid cloning. Uses optional per-tick cache (dict keyed by repo).

    Args:
        repo: GitHub repo in "owner/name" format
        cache: Optional dict to cache results across calls in one tick

    Returns:
        True if repo is opted in, False otherwise

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
        result = await asyncio.wait_for(
            _fetch_toml_via_gh(owner, name),
            timeout=REPO_OPTED_IN_TIMEOUT,
        )
        cache[repo] = result
        return result
    except asyncio.TimeoutError as exc:
        raise IntakeGateError(
            f"Timeout fetching .simplicio/loop.toml for {repo}",
            "repo_check_timeout",
        ) from exc
    except IntakeGateError:
        raise
    except Exception as exc:
        raise IntakeGateError(
            f"Failed to check repo {repo}: {exc}",
            "repo_check_failed",
        ) from exc


async def _fetch_toml_via_gh(owner: str, name: str) -> bool:
    """Fetch .simplicio/loop.toml via gh api and check if enabled=true.

    Returns False if file doesn't exist, True if enabled, False otherwise.
    Raises IntakeGateError on malformed TOML or other errors.
    """
    cmd = [
        "gh",
        "api",
        f"repos/{owner}/{name}/contents/.simplicio/loop.toml",
        "--jq",
        ".content",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        # Exit code 1 means file not found (404)
        if proc.returncode == 1:
            if b"404" in stderr or b"Not Found" in stderr:
                return False
            raise IntakeGateError(
                f"gh api call failed: {stderr.decode('utf-8', errors='replace')}",
                "gh_api_error",
            )

        if proc.returncode != 0:
            raise IntakeGateError(
                f"gh api call exited with {proc.returncode}: {stderr.decode('utf-8', errors='replace')}",
                "gh_api_error",
            )

        # Content is base64-encoded JSON value; decode it
        content_b64 = stdout.decode("utf-8", errors="replace").strip()
        if not content_b64 or content_b64 == "null":
            return False

        # Decode base64
        content_str = base64.b64decode(content_b64).decode("utf-8")

        # Parse TOML
        try:
            config = tomllib.loads(content_str)
        except Exception as exc:
            raise IntakeGateError(
                f"Malformed .simplicio/loop.toml: {exc}",
                "invalid_toml",
            ) from exc

        # Check enabled field
        return config.get("enabled", False)

    except IntakeGateError:
        raise


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
    config = config or {}

    # Check loop:auto label
    labels = issue.get("labels") or []
    label_names = [label.get("name") if isinstance(label, dict) else label for label in labels]
    if "loop:auto" not in label_names:
        return False

    # Check author association
    author_assoc = issue.get("author_association")
    if author_assoc is None:
        return False
    author_assoc = author_assoc.upper()
    if author_assoc in ("OWNER", "MEMBER", "COLLABORATOR"):
        return True

    # Anything else (NONE, CONTRIBUTOR, etc.) is not trusted
    return False


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
                "Esta eh uma epica ou um item de muito alto nivel. "
                "Por favor, divida-a em tarefas menores e concretas, "
                "cada uma com criterios de aceite especificos e arquivos/comportamentos concretos."
            ),
        )

    # Check body quality
    if not body or len(body) < 20:
        return TriageResult(
            verdict="needs_human",
            reason_code="empty_body",
            clarifying_question=(
                "A descricao da issue esta muito vaga ou incompleta. "
                "Por favor, forneca: 1. O que precisa ser feito (objetivo); "
                "2. Por que (contexto); 3. Criterios de aceite especificos; "
                "4. Arquivos ou funcoes que serao alteradas."
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
                    "A issue precisa de detalhes concretos para ser executavel. "
                    "Por favor, inclua: 1. Criterios de aceite especificos (Dado/Quando/Entao); "
                    "2. Quais arquivos serao afetados; 3. Comportamento esperado ou exemplo de entrada/saida."
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
    "repo_opted_in",
    "issue_admitted",
    "triage",
]
